"""
The book: positions, cost-basis reconciliation, risk flags.

The ordering rule here is the whole point of the module: **cost basis is
reconciled before any P&L is trusted.** NAKA sits in this account at an average
price of $169.65 against a $4.85 market — a 35x ratio that is either a real
-97% or a reverse-split artefact in IBKR's cost field. Until
`detect_corporate_action` settles it, that position's P&L is not summed into
the total and the dashboard says so in words, with an icon, at critical
severity.

Every `RiskFlag` carries an icon *and* a title. Colour never carries meaning
alone — the icon names below are lucide identifiers the front end renders next
to the text, so the flag survives a greyscale screen and a colour-blind reader.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from .config import Settings, settings as default_settings
from .models import (
    CostBasisStatus,
    Instrument,
    PortfolioSnapshot,
    Position,
    Reconciliation,
    RiskFlag,
    Severity,
)
from .universe import to_instrument

log = logging.getLogger(__name__)

# An average cost this far from the market is not a loss, it is a data problem
# until proven otherwise.
COST_BASIS_RATIO_LIMIT = 3.0

# Informational only: a book this far in cash is not "risky", but it is a fact
# worth stating on a dashboard whose other numbers are all about deployed risk.
CASH_DRAG_PCT = 50.0

ICON = {
    Severity.CRITICAL: "alert-octagon",
    Severity.SERIOUS: "alert-triangle",
    Severity.WARNING: "clock-alert",
    Severity.NEUTRAL: "info",
    Severity.GOOD: "check-circle",
}


# ─────────────────────────── inputs ───────────────────────────


@dataclass
class PositionInput:
    """One IBKR position, normalised. `market_value` etc. stay optional so we
    can cross-check IBKR's own arithmetic rather than assume it."""
    instrument: Instrument
    quantity: float
    avg_cost: float
    last: float
    market_value: float | None = None
    unrealized_pnl: float | None = None
    day_pnl: float | None = None
    prior_close: float | None = None
    beta_vs_index: float | None = None
    next_earnings: date | None = None
    stop: float | None = None

    @classmethod
    def from_ibkr(cls, row: Any, *,
                  stops: Mapping[int, float] | None = None,
                  betas: Mapping[int, float] | None = None,
                  earnings: Mapping[int, date] | None = None) -> "PositionInput | None":
        get = row.get if isinstance(row, Mapping) else (lambda k, d=None: getattr(row, k, d))
        raw_inst = get("instrument") or row
        inst = to_instrument(raw_inst)
        if inst is None:
            log.warning("position without a conid skipped: %r", row)
            return None
        qty = float(get("quantity", get("position", 0)) or 0)
        last = float(get("last", get("mktPrice", get("marketPrice", 0))) or 0)
        avg = float(get("avg_cost", get("avgCost", get("avgPrice", 0))) or 0)
        mv = get("market_value", get("mktValue", get("marketValue")))
        return cls(
            instrument=inst,
            quantity=qty,
            avg_cost=avg,
            last=last,
            market_value=None if mv is None else float(mv),
            unrealized_pnl=_maybe_float(get("unrealized_pnl", get("unrealizedPnl"))),
            day_pnl=_maybe_float(get("day_pnl", get("dailyPnl"))),
            prior_close=_maybe_float(get("prior_close", get("priorClose"))),
            beta_vs_index=(betas or {}).get(inst.conid),
            next_earnings=(earnings or {}).get(inst.conid),
            stop=(stops or {}).get(inst.conid),
        )


def _maybe_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class AccountSummary:
    net_liquidation: float = 0.0
    cash: float = 0.0
    gross_position_value: float = 0.0
    day_pnl: float | None = None

    @classmethod
    def from_ibkr(cls, raw: Any) -> "AccountSummary":
        get = raw.get if isinstance(raw, Mapping) else (lambda k, d=None: getattr(raw, k, d))
        return cls(
            net_liquidation=float(get("net_liquidation",
                                      get("netliquidation", get("NetLiquidation", 0))) or 0),
            cash=float(get("cash", get("totalcashvalue", get("TotalCashValue", 0))) or 0),
            gross_position_value=float(get("gross_position_value",
                                           get("grosspositionvalue",
                                               get("GrossPositionValue", 0))) or 0),
            day_pnl=_maybe_float(get("day_pnl", get("dailyPnL"))),
        )


# ─────────────────────────── cost basis ───────────────────────────

CorpActionDetector = Callable[[PositionInput], Any]


def _default_detector(pos: PositionInput) -> Any:
    """Lazy bridge to `app.sources.reconcile.detect_corporate_action`.

    Tolerant about the callee's signature because that module is owned by
    another agent; a detector that cannot be called is reported as "unknown",
    never as "fine".
    """
    try:
        from .sources.reconcile import detect_corporate_action  # type: ignore
    except Exception as exc:                                   # pragma: no cover
        log.warning("detect_corporate_action unavailable (%s) — cost basis stays unverified", exc)
        return None
    try:
        return detect_corporate_action(
            conid=pos.instrument.conid,
            symbol=pos.instrument.symbol,
            avg_cost=pos.avg_cost,
            last=pos.last,
        )
    except TypeError:                                          # pragma: no cover
        try:
            return detect_corporate_action(pos.instrument.conid, pos.avg_cost, pos.last)
        except Exception as exc:
            log.warning("detect_corporate_action failed for %s: %s",
                        pos.instrument.symbol, exc)
            return None
    except Exception as exc:                                   # pragma: no cover
        log.warning("detect_corporate_action failed for %s: %s", pos.instrument.symbol, exc)
        return None


def _detector_says_action(result: Any) -> tuple[bool, str | None]:
    """Normalise whatever the detector returns into (suspected, note)."""
    if result is None or result is False:
        return False, None
    if result is True:
        return True, "corporate action suspected"
    if isinstance(result, Mapping):
        suspected = bool(result.get("suspected", result.get("detected", True)))
        note = result.get("note") or result.get("description")
        ratio = result.get("ratio")
        if note is None and ratio:
            note = f"implied ratio {ratio}"
        return suspected, note
    suspected = bool(getattr(result, "suspected", getattr(result, "detected", True)))
    return suspected, getattr(result, "note", None)


def verify_cost_basis(pos: PositionInput,
                      detector: CorpActionDetector | None = None
                      ) -> tuple[CostBasisStatus, str | None]:
    """Is this average cost believable against the market price?"""
    if pos.avg_cost <= 0 or pos.last <= 0:
        return CostBasisStatus.OK, None
    ratio = pos.avg_cost / pos.last
    if 1 / COST_BASIS_RATIO_LIMIT <= ratio <= COST_BASIS_RATIO_LIMIT:
        return CostBasisStatus.OK, None

    suspected, note = _detector_says_action((detector or _default_detector)(pos))
    base = (f"average cost {pos.avg_cost:,.2f} vs market {pos.last:,.2f} "
            f"({ratio:,.1f}x). ")
    if suspected:
        return CostBasisStatus.CORPORATE_ACTION_SUSPECTED, base + (
            note or "consistent with a split / reverse split not applied to the "
                    "cost field. P&L on this line is not trustworthy."
        )
    return CostBasisStatus.UNVERIFIED, base + (
        note or "no corporate action found to explain it — either a real loss of "
                "this size or a bad cost field. Resolve with IBKR's "
                "include_corporate_actions flag before trusting P&L."
    )


# ─────────────────────────── the snapshot ───────────────────────────


def build_snapshot(
    positions: Sequence[PositionInput],
    account: AccountSummary,
    *,
    cfg: Settings | None = None,
    detector: CorpActionDetector | None = None,
    as_of: datetime | None = None,
    today: date | None = None,
) -> PortfolioSnapshot:
    cfg = cfg or default_settings
    as_of = as_of or datetime.now(timezone.utc)
    today = today or as_of.date()

    rows: list[Position] = []
    recs: list[Reconciliation] = []

    gross = account.gross_position_value or sum(
        abs((p.market_value if p.market_value is not None else p.quantity * p.last))
        for p in positions
    )

    total_mv = 0.0
    verified_pnl = 0.0
    unverified: list[PositionInput] = []
    total_day_pnl = 0.0
    have_day_pnl = False

    for p in positions:
        computed_mv = p.quantity * p.last
        mv = p.market_value if p.market_value is not None else computed_mv
        if p.market_value is not None and computed_mv:
            diff = abs(p.market_value - computed_mv) / abs(computed_mv) * 100.0
            if diff > cfg.tol_market_value_pct:
                recs.append(Reconciliation(
                    field=f"market_value:{p.instrument.symbol}",
                    ibkr=round(p.market_value, 4),
                    yahoo=round(computed_mv, 4),
                    diff_pct=round(diff, 4),
                    tolerance_pct=cfg.tol_market_value_pct,
                    breached=True,
                    note="IBKR market value disagrees with quantity x last",
                ))

        status, note = verify_cost_basis(p, detector)
        cost = p.avg_cost * p.quantity
        pnl = p.unrealized_pnl if p.unrealized_pnl is not None else mv - cost
        pct = ((p.last / p.avg_cost - 1.0) * 100.0) if p.avg_cost else 0.0

        day_pnl = p.day_pnl
        if day_pnl is None and p.prior_close:
            day_pnl = (p.last - p.prior_close) * p.quantity
        if day_pnl is not None:
            total_day_pnl += day_pnl
            have_day_pnl = True

        total_mv += mv
        if status is CostBasisStatus.OK:
            verified_pnl += pnl
        else:
            unverified.append(p)

        rows.append(Position(
            instrument=p.instrument,
            quantity=p.quantity,
            avg_cost=p.avg_cost,
            last=p.last,
            market_value=round(mv, 4),
            unrealized_pnl=round(pnl, 4),
            unrealized_pct=round(pct, 4),
            weight_pct=round(100.0 * mv / gross, 4) if gross else 0.0,
            day_pnl=None if day_pnl is None else round(day_pnl, 4),
            contribution_to_day_return=None,
            cost_basis_status=status,
            cost_basis_note=note,
        ))

    # contribution to the portfolio's day return, on the prior day's net liq
    day_total = account.day_pnl if account.day_pnl is not None else (
        total_day_pnl if have_day_pnl else None)
    base = (account.net_liquidation - (day_total or 0.0)) or account.net_liquidation
    if base:
        for r in rows:
            if r.day_pnl is not None:
                r.contribution_to_day_return = round(100.0 * r.day_pnl / base, 4)

    # portfolio beta, weighted by market value over gross exposure
    betas = [(p, r) for p, r in zip(positions, rows) if p.beta_vs_index is not None]
    beta = None
    if betas and gross:
        beta = round(sum((r.market_value / gross) * (p.beta_vs_index or 0.0)
                         for p, r in betas), 4)

    sector_exposure: dict[str, float] = {}
    for r in rows:
        key = r.instrument.sector or r.instrument.theme or "Unclassified"
        sector_exposure[key] = round(
            sector_exposure.get(key, 0.0) + (r.weight_pct or 0.0), 4)

    largest = max((r.weight_pct for r in rows), default=None)

    snap = PortfolioSnapshot(
        as_of=as_of,
        net_liquidation=account.net_liquidation,
        cash=account.cash,
        gross_position_value=round(gross, 4),
        deployed_pct=round(100.0 * gross / account.net_liquidation, 4)
        if account.net_liquidation else 0.0,
        leverage=round(gross / account.net_liquidation, 4)
        if account.net_liquidation else 0.0,
        positions=rows,
        total_market_value=round(total_mv, 4),
        total_unrealized_pnl=round(verified_pnl, 4),
        day_pnl=None if day_total is None else round(day_total, 4),
        beta_vs_index=beta,
        sector_exposure=sector_exposure,
        largest_position_pct=None if largest is None else round(largest, 4),
        reconciliation=recs,
    )
    snap.flags = build_risk_flags(snap, positions, cfg=cfg, today=today,
                                  unverified=unverified)
    return snap


# ─────────────────────────── risk flags ───────────────────────────


def build_risk_flags(
    snap: PortfolioSnapshot,
    inputs: Sequence[PositionInput],
    *,
    cfg: Settings | None = None,
    today: date | None = None,
    unverified: Sequence[PositionInput] = (),
) -> list[RiskFlag]:
    cfg = cfg or default_settings
    today = today or date.today()
    by_conid = {p.instrument.conid: p for p in inputs}
    flags: list[RiskFlag] = []

    # 1 ── cost basis unverified. CRITICAL: it invalidates P&L, not just a view.
    for row in snap.positions:
        if row.cost_basis_status is CostBasisStatus.OK:
            continue
        label = ("corporate action suspected"
                 if row.cost_basis_status is CostBasisStatus.CORPORATE_ACTION_SUSPECTED
                 else "unverified")
        flags.append(RiskFlag(
            severity=Severity.CRITICAL,
            icon=ICON[Severity.CRITICAL],
            title=f"{row.instrument.symbol}: cost basis {label}",
            detail=(row.cost_basis_note or "")
            + " This line is excluded from total unrealised P&L until it is resolved.",
            conid=row.instrument.conid,
        ))

    # 2 ── single-name concentration, measured against DEPLOYED capital.
    # KKR at 49% of a $6,205 book is a concentration problem even though it is
    # 1.6% of net liquidation. Deployed is the denominator that can hurt you.
    for row in snap.positions:
        if (row.weight_pct or 0) > cfg.concentration_limit_pct:
            flags.append(RiskFlag(
                severity=Severity.SERIOUS,
                icon=ICON[Severity.SERIOUS],
                title=f"{row.instrument.symbol}: {row.weight_pct:.0f}% of deployed capital",
                detail=(f"Above the {cfg.concentration_limit_pct:.0f}% single-name limit. "
                        f"{row.market_value:,.0f} of {snap.gross_position_value:,.0f} "
                        f"deployed ({row.weight_pct:.1f}%)."),
                conid=row.instrument.conid,
            ))

    # 3 ── earnings inside the warning window
    for row in snap.positions:
        p = by_conid.get(row.instrument.conid)
        if p is None or p.next_earnings is None:
            continue
        days = (p.next_earnings - today).days
        if 0 <= days <= cfg.earnings_warning_days:
            flags.append(RiskFlag(
                severity=Severity.WARNING,
                icon=ICON[Severity.WARNING],
                title=f"{row.instrument.symbol} reports in {days}d",
                detail=(f"Earnings {p.next_earnings.isoformat()} — inside the "
                        f"{cfg.earnings_warning_days}-day window, on "
                        f"{row.weight_pct:.1f}% of deployed capital."),
                conid=row.instrument.conid,
            ))

    # 4 ── stop breached
    for row in snap.positions:
        p = by_conid.get(row.instrument.conid)
        if p is None or p.stop is None:
            continue
        if (p.quantity > 0 and p.last < p.stop) or (p.quantity < 0 and p.last > p.stop):
            flags.append(RiskFlag(
                severity=Severity.SERIOUS,
                icon="shield-alert",
                title=f"{row.instrument.symbol}: stop breached",
                detail=(f"Last {p.last:,.2f} through the {p.stop:,.2f} stop "
                        f"({(p.last / p.stop - 1) * 100:+.1f}%)."),
                conid=row.instrument.conid,
            ))

    # 5 ── cash drag. Informational, never dressed up as a risk.
    if snap.net_liquidation:
        cash_pct = 100.0 * snap.cash / snap.net_liquidation
        if cash_pct >= CASH_DRAG_PCT:
            flags.append(RiskFlag(
                severity=Severity.NEUTRAL,
                icon=ICON[Severity.NEUTRAL],
                title=f"{cash_pct:.0f}% in cash",
                detail=(f"{snap.cash:,.0f} of {snap.net_liquidation:,.0f} uninvested; "
                        f"{snap.deployed_pct:.1f}% deployed. Informational — "
                        f"position sizes below are a small fraction of the account."),
            ))

    order = {Severity.CRITICAL: 0, Severity.SERIOUS: 1, Severity.WARNING: 2,
             Severity.NEUTRAL: 3, Severity.GOOD: 4}
    flags.sort(key=lambda f: order[f.severity])
    return flags


# ─────────────────────────── service entry point ───────────────────────────


def build_portfolio(
    ibkr: Any,
    *,
    stops: Mapping[int, float] | None = None,
    betas: Mapping[int, float] | None = None,
    earnings: Mapping[int, date] | None = None,
    cfg: Settings | None = None,
    detector: CorpActionDetector | None = None,
) -> PortfolioSnapshot:
    """Pull positions + account summary from IBKR and build the snapshot."""
    raw_positions = ibkr.get_positions() or []
    inputs = [pi for pi in (PositionInput.from_ibkr(r, stops=stops, betas=betas,
                                                    earnings=earnings)
                            for r in raw_positions) if pi is not None]
    account = AccountSummary.from_ibkr(ibkr.get_account_summary() or {})
    return build_snapshot(inputs, account, cfg=cfg, detector=detector)


def empty_snapshot(as_of: datetime | None = None) -> PortfolioSnapshot:
    """What the API serves when the cache has nothing yet. Not an error — the
    read path never blocks on the network, it just says it has nothing."""
    return PortfolioSnapshot(
        as_of=as_of or datetime.now(timezone.utc),
        net_liquidation=0.0, cash=0.0, gross_position_value=0.0,
        deployed_pct=0.0, leverage=0.0, positions=[],
        total_market_value=0.0, total_unrealized_pnl=0.0,
    )
