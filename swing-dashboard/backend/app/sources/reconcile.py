"""
The cross-check layer.

The spec's rule, in one line: **nothing silently picks a winner.**

Both sources are pulled and compared on close, volume and split adjustment.
Where they agree within tolerance the value passes through with a non-breached
Reconciliation attached (so the UI can show a quiet tick). Where they disagree
beyond tolerance the value is *still returned* — IBKR's for price, Yahoo's for
fundamentals — but with `breached=True` on the Reconciliation, and the UI is
required to badge it. A discrepancy is information, not an error to swallow.

Tie-break rules, from the spec:
  * **IBKR wins for price.** It is the execution venue and it is the only source
    that covers LSEETF / FWB / KSE / TSEJ consistently.
  * **Yahoo wins for fundamentals.** IBKR's fundamental data is licensed,
    partial, and frequently absent for non-US listings.

Plus `detect_corporate_action`, which exists for one concrete open question:

    NAKA — 34 shares, average cost $169.65, market price $4.85.

That is either a genuine −97% loss or a reverse-split artifact in the cost
basis, and the difference matters enormously to the portfolio P&L. The test is
whether the price history *corroborates* the cost basis: if the stock ever
traded anywhere near $169.65 in the window we hold, the loss is real; if the
whole history sits under $12, the cost basis is a pre-split number that was
never re-based, and we say CORPORATE_ACTION_SUSPECTED rather than printing a
−97% that may be fiction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from app.config import settings
from app.models import CostBasisStatus, Reconciliation
from app.sources.base import BAR_INDEX_NAME, safe_float

log = logging.getLogger(__name__)


# ═══════════════════════════ tolerances ═══════════════════════════

@dataclass(frozen=True)
class Tolerances:
    """
    Percentage tolerances. Defaults come from `settings` so they are tunable
    without a code change.

    `volume_pct` is deliberately loose (5%): IBKR reports consolidated tape
    volume for US names while Yahoo reports primary-listing volume, and the two
    legitimately differ by a few percent every day. A *large* gap still matters,
    because a 100x gap means one of them is quoting round lots.
    """

    close_pct: float = settings.tol_close_pct
    volume_pct: float = settings.tol_volume_pct
    market_value_pct: float = settings.tol_market_value_pct
    split_pct: float = 1.0             # ratio must sit within 1% of 1.0
    min_overlap_days: int = 5          # fewer than this and we cannot judge
    max_detail_rows: int = 10          # per-date rows emitted before we summarise

    @classmethod
    def from_settings(cls) -> "Tolerances":
        return cls(
            close_pct=settings.tol_close_pct,
            volume_pct=settings.tol_volume_pct,
            market_value_pct=settings.tol_market_value_pct,
        )


DEFAULT_TOLERANCES = Tolerances()

#: Reverse/forward split ratios worth naming when we spot one.
_COMMON_SPLIT_RATIOS: tuple[float, ...] = (
    1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0,
)


# ═══════════════════════════ small helpers ═══════════════════════════

def pct_diff(a: float | None, b: float | None) -> float | None:
    """|a − b| as a percentage of |b| (the reference). None if either is missing."""
    fa, fb = safe_float(a), safe_float(b)
    if fa is None or fb is None:
        return None
    if fb == 0:
        return None if fa == 0 else float("inf")
    return abs(fa - fb) / abs(fb) * 100.0


def _closes(df: pd.DataFrame | None, column: str) -> pd.Series:
    if df is None or len(df) == 0 or column not in df.columns:
        return pd.Series(dtype="float64")
    s = pd.to_numeric(df[column], errors="coerce")
    idx = df.index
    if BAR_INDEX_NAME in getattr(df, "columns", []):
        idx = pd.to_datetime(df[BAR_INDEX_NAME], errors="coerce")
    s.index = pd.DatetimeIndex(pd.to_datetime(idx, errors="coerce")).normalize()
    return s.dropna()


def _source_label(df: pd.DataFrame | None, fallback: str) -> str:
    try:
        return str((df.attrs or {}).get("source") or fallback)
    except Exception:
        return fallback


# ═══════════════════════════ series reconciliation ═══════════════════════════

def reconcile_series(
    ibkr_df: pd.DataFrame | None,
    yahoo_df: pd.DataFrame | None,
    tolerances: Tolerances | None = None,
    *,
    label: str = "",
) -> list[Reconciliation]:
    """
    Compare two daily bar frames across their overlapping dates.

    Returns a list of `Reconciliation`, always containing at least the summary
    rows for `close` and `volume` (breached or not) plus a `split_adjustment`
    row, so the caller can attach the whole list to an `IndicatorSet` and the UI
    can render "checked, agrees" as readily as "checked, disagrees".

    Per-date detail rows (``close@2026-08-04``) are emitted for breaches only,
    capped at `tolerances.max_detail_rows` with a note when truncated — the spec
    forbids silent truncation.
    """
    tol = tolerances or DEFAULT_TOLERANCES
    prefix = f"{label}." if label else ""

    ibkr_close = _closes(ibkr_df, "close")
    yahoo_close = _closes(yahoo_df, "close")

    if ibkr_close.empty or yahoo_close.empty:
        missing = "yahoo" if ibkr_close.size else ("ibkr" if yahoo_close.size else "both")
        return [
            Reconciliation(
                field=f"{prefix}coverage",
                tolerance_pct=tol.close_pct,
                breached=False,
                note=(
                    f"no cross-check available — {missing} series empty. "
                    "IBKR value used unverified."
                ),
            )
        ]

    overlap = ibkr_close.index.intersection(yahoo_close.index)
    if len(overlap) == 0:
        return [
            Reconciliation(
                field=f"{prefix}coverage",
                tolerance_pct=tol.close_pct,
                breached=True,
                note=(
                    "IBKR and Yahoo series do not overlap on any date "
                    f"(IBKR {ibkr_close.index.min().date()}..{ibkr_close.index.max().date()}, "
                    f"Yahoo {yahoo_close.index.min().date()}..{yahoo_close.index.max().date()}). "
                    "Likely the wrong Yahoo ticker for this listing."
                ),
            )
        ]

    out: list[Reconciliation] = []

    if len(overlap) < tol.min_overlap_days:
        out.append(
            Reconciliation(
                field=f"{prefix}coverage",
                tolerance_pct=tol.close_pct,
                breached=False,
                note=(
                    f"only {len(overlap)} overlapping session(s); "
                    f"below the {tol.min_overlap_days}-day confidence floor"
                ),
            )
        )

    out.extend(
        _reconcile_column(
            ibkr_df, yahoo_df, "close", tol.close_pct, overlap, tol, prefix
        )
    )
    out.extend(
        _reconcile_column(
            ibkr_df, yahoo_df, "volume", tol.volume_pct, overlap, tol, prefix
        )
    )
    out.append(
        detect_split_adjustment(
            ibkr_close.reindex(overlap), yahoo_close.reindex(overlap), tol, prefix
        )
    )
    return out


def _reconcile_column(
    ibkr_df: pd.DataFrame,
    yahoo_df: pd.DataFrame,
    column: str,
    tolerance_pct: float,
    overlap: pd.DatetimeIndex,
    tol: Tolerances,
    prefix: str,
) -> list[Reconciliation]:
    a = _closes(ibkr_df, column).reindex(overlap)
    b = _closes(yahoo_df, column).reindex(overlap)
    both = pd.concat([a.rename("ibkr"), b.rename("yahoo")], axis=1).dropna()

    if both.empty:
        return [
            Reconciliation(
                field=f"{prefix}{column}",
                tolerance_pct=tolerance_pct,
                breached=False,
                note=f"no comparable {column} values on the overlapping dates",
            )
        ]

    denom = both["yahoo"].replace(0, np.nan)
    diff = (both["ibkr"] - both["yahoo"]).abs() / denom.abs() * 100.0
    diff = diff.dropna()
    if diff.empty:
        return [
            Reconciliation(
                field=f"{prefix}{column}",
                tolerance_pct=tolerance_pct,
                breached=False,
                note=f"{column} reference values were zero; comparison skipped",
            )
        ]

    breaches = diff[diff > tolerance_pct]
    worst_date = diff.idxmax()
    worst = float(diff.loc[worst_date])

    summary = Reconciliation(
        field=f"{prefix}{column}",
        ibkr=float(both.loc[worst_date, "ibkr"]),
        yahoo=float(both.loc[worst_date, "yahoo"]),
        diff_pct=worst,
        tolerance_pct=tolerance_pct,
        breached=bool(len(breaches) > 0),
        note=(
            f"{len(breaches)}/{len(diff)} sessions exceed {tolerance_pct:g}%; "
            f"worst {worst:.3f}% on {pd.Timestamp(worst_date).date()}. "
            "IBKR value retained (execution venue)."
            if len(breaches)
            else f"agrees within {tolerance_pct:g}% across {len(diff)} sessions "
                 f"(worst {worst:.3f}%)"
        ),
    )
    rows = [summary]

    shown = breaches.sort_values(ascending=False)
    capped = shown.iloc[: tol.max_detail_rows]
    for ts, d in capped.items():
        rows.append(
            Reconciliation(
                field=f"{prefix}{column}@{pd.Timestamp(ts).date().isoformat()}",
                ibkr=float(both.loc[ts, "ibkr"]),
                yahoo=float(both.loc[ts, "yahoo"]),
                diff_pct=float(d),
                tolerance_pct=tolerance_pct,
                breached=True,
                note="per-session divergence",
            )
        )
    if len(shown) > len(capped):
        rows.append(
            Reconciliation(
                field=f"{prefix}{column}.truncated",
                tolerance_pct=tolerance_pct,
                breached=True,
                note=(
                    f"{len(shown) - len(capped)} further breached session(s) not listed "
                    f"(cap {tol.max_detail_rows})"
                ),
            )
        )
    return rows


def detect_split_adjustment(
    ibkr_close: pd.Series,
    yahoo_close: pd.Series,
    tolerances: Tolerances | None = None,
    prefix: str = "",
) -> Reconciliation:
    """
    Catch the failure that silently corrupts every indicator downstream: one
    source has applied a split adjustment and the other has not.

    Two shapes:
      * **Whole-series offset** — the IBKR/Yahoo close ratio is a constant ≠ 1
        (e.g. 10.0 after an un-applied 1:10 reverse split).
      * **Step change** — the ratio is 1.0 before some date and 10.0 after,
        which is the more dangerous case because the recent prices look fine.
    """
    tol = tolerances or DEFAULT_TOLERANCES
    field = f"{prefix}split_adjustment"

    both = pd.concat(
        [ibkr_close.rename("ibkr"), yahoo_close.rename("yahoo")], axis=1
    ).dropna()
    both = both[both["yahoo"] != 0]
    if len(both) < 3:
        return Reconciliation(
            field=field,
            tolerance_pct=tol.split_pct,
            breached=False,
            note="too few overlapping sessions to test the split adjustment",
        )

    ratio = both["ibkr"] / both["yahoo"]
    median = float(ratio.median())
    spread_pct = float((ratio.max() - ratio.min()) / abs(median) * 100.0) if median else float("inf")

    offset_pct = abs(median - 1.0) * 100.0
    if offset_pct > tol.split_pct:
        named = _nearest_split_ratio(median)
        return Reconciliation(
            field=field,
            ibkr=float(both["ibkr"].iloc[-1]),
            yahoo=float(both["yahoo"].iloc[-1]),
            diff_pct=offset_pct,
            tolerance_pct=tol.split_pct,
            breached=True,
            note=(
                f"IBKR/Yahoo close ratio is {median:.4f} across the whole window"
                + (f" — consistent with an unapplied {named} split adjustment" if named else "")
                + ". Indicators computed on the unadjusted series would be wrong; "
                "resolve before trusting any level."
            ),
        )

    # step change: compare the first and last thirds of the ratio series
    third = max(1, len(ratio) // 3)
    early, late = float(ratio.iloc[:third].median()), float(ratio.iloc[-third:].median())
    step_pct = abs(late - early) / abs(early) * 100.0 if early else float("inf")
    if step_pct > tol.split_pct:
        return Reconciliation(
            field=field,
            ibkr=float(both["ibkr"].iloc[-1]),
            yahoo=float(both["yahoo"].iloc[-1]),
            diff_pct=step_pct,
            tolerance_pct=tol.split_pct,
            breached=True,
            note=(
                f"IBKR/Yahoo close ratio steps from {early:.4f} to {late:.4f} within the "
                "window — one source applied a corporate action the other did not."
            ),
        )

    return Reconciliation(
        field=field,
        diff_pct=offset_pct,
        tolerance_pct=tol.split_pct,
        breached=False,
        note=(
            f"close ratio stable at {median:.4f} (spread {spread_pct:.2f}%) — "
            "both series carry the same adjustment"
        ),
    )


def _nearest_split_ratio(ratio: float) -> str | None:
    if ratio <= 0:
        return None
    for r in _COMMON_SPLIT_RATIOS:
        for candidate, label in ((r, f"1:{r:g}"), (1.0 / r, f"{r:g}:1")):
            if abs(ratio - candidate) / candidate < 0.05:
                return label
    return None


# ═══════════════════════════ single-value resolution ═══════════════════════════

@dataclass(frozen=True)
class Resolved:
    """A value plus the audit trail of how it was chosen."""
    value: float | None
    winner: str                       # "ibkr" | "yahoo" | "only-source" | "none"
    reconciliation: Reconciliation

    @property
    def breached(self) -> bool:
        return self.reconciliation.breached


def _resolve(
    field: str,
    ibkr_value: float | None,
    yahoo_value: float | None,
    tolerance_pct: float,
    *,
    prefer: str,
    reason: str,
) -> Resolved:
    a, b = safe_float(ibkr_value), safe_float(yahoo_value)

    if a is None and b is None:
        return Resolved(
            None, "none",
            Reconciliation(
                field=field, tolerance_pct=tolerance_pct, breached=False,
                note="neither source supplied a value",
            ),
        )
    if a is None or b is None:
        only = "yahoo" if a is None else "ibkr"
        return Resolved(
            b if a is None else a, "only-source",
            Reconciliation(
                field=field, ibkr=a, yahoo=b, tolerance_pct=tolerance_pct,
                breached=False, note=f"single source ({only}); not cross-checked",
            ),
        )

    d = pct_diff(a, b)
    breached = d is not None and d > tolerance_pct
    winner_value = a if prefer == "ibkr" else b
    return Resolved(
        winner_value, prefer,
        Reconciliation(
            field=field, ibkr=a, yahoo=b, diff_pct=d,
            tolerance_pct=tolerance_pct, breached=breached,
            note=(f"sources disagree by {d:.3f}% — {reason}" if breached
                  else f"sources agree within {tolerance_pct:g}%"),
        ),
    )


def resolve_price(
    field: str,
    ibkr_value: float | None,
    yahoo_value: float | None,
    tolerance_pct: float | None = None,
) -> Resolved:
    """IBKR wins. It is the execution venue and covers the non-US listings."""
    return _resolve(
        field, ibkr_value, yahoo_value,
        tolerance_pct if tolerance_pct is not None else DEFAULT_TOLERANCES.close_pct,
        prefer="ibkr",
        reason="IBKR retained (execution venue); value flagged, not corrected",
    )


def resolve_fundamental(
    field: str,
    ibkr_value: float | None,
    yahoo_value: float | None,
    tolerance_pct: float = 1.0,
) -> Resolved:
    """Yahoo wins. IBKR's fundamental coverage is partial and licence-gated."""
    return _resolve(
        field, ibkr_value, yahoo_value, tolerance_pct,
        prefer="yahoo",
        reason="Yahoo retained (fundamentals authority); value flagged, not corrected",
    )


def reconcile_market_value(
    ibkr_market_value: float | None,
    computed_market_value: float | None,
    tolerances: Tolerances | None = None,
) -> Resolved:
    """Portfolio guard: IBKR's reported market value vs quantity × our last price."""
    tol = tolerances or DEFAULT_TOLERANCES
    return resolve_price(
        "market_value", ibkr_market_value, computed_market_value, tol.market_value_pct
    )


# ═══════════════════════════ corporate actions ═══════════════════════════

#: A cost basis this many times the market price cannot be explained by ordinary
#: drawdown without corroborating price history. 10x == a −90% loss.
COST_BASIS_RATIO_THRESHOLD = 10.0

#: If the highest close in the available history reaches this fraction of the
#: average cost, the history corroborates the basis and the loss is real.
HISTORY_CORROBORATION_FRACTION = 0.5


def detect_corporate_action(
    bars: pd.DataFrame | pd.Series | None,
    avg_cost: float | None,
    last_price: float | None,
    *,
    ratio_threshold: float = COST_BASIS_RATIO_THRESHOLD,
    corroboration_fraction: float = HISTORY_CORROBORATION_FRACTION,
) -> CostBasisStatus:
    """
    Is this cost basis a real loss, or a reverse-split artifact?

    The motivating case, verbatim from the account:

        NAKA — 34 shares, avg cost $169.65, market $4.85.

    Ratio 34.98x. A −97% drawdown is possible; so is a 1:20 reverse split that
    IBKR never re-based in the cost field. We separate them with the price
    history:

      * ratio ≤ `ratio_threshold`            → OK. A −50% drawdown (ratio 2.0)
                                               is an ordinary bad trade.
      * ratio > threshold, history reaches
        ≥ 50% of avg_cost                    → OK. The stock really did trade
                                               there; the loss is genuine.
      * ratio > threshold, history nowhere
        near avg_cost                        → CORPORATE_ACTION_SUSPECTED.
      * ratio > threshold, no history at all → UNVERIFIED. We will not guess.

    Returns the status only; use `assess_cost_basis` when you also want the
    human-readable note for `Position.cost_basis_note`.
    """
    return assess_cost_basis(
        bars, avg_cost, last_price,
        ratio_threshold=ratio_threshold,
        corroboration_fraction=corroboration_fraction,
    )[0]


def assess_cost_basis(
    bars: pd.DataFrame | pd.Series | None,
    avg_cost: float | None,
    last_price: float | None,
    *,
    ratio_threshold: float = COST_BASIS_RATIO_THRESHOLD,
    corroboration_fraction: float = HISTORY_CORROBORATION_FRACTION,
) -> tuple[CostBasisStatus, str]:
    """`detect_corporate_action` plus the explanation."""
    cost = safe_float(avg_cost)
    price = safe_float(last_price)

    if cost is None or price is None or cost <= 0 or price <= 0:
        return (
            CostBasisStatus.UNVERIFIED,
            "cost basis or market price missing; P&L not verified",
        )

    ratio = cost / price
    if ratio <= ratio_threshold:
        return (
            CostBasisStatus.OK,
            f"cost basis {ratio:.2f}x market price — within ordinary drawdown range",
        )

    highs = _history_highs(bars)
    if highs is None or highs.empty:
        return (
            CostBasisStatus.UNVERIFIED,
            (
                f"cost basis {cost:,.2f} is {ratio:.1f}x the {price:,.2f} market price "
                "and there is no price history to corroborate it. Do not trust the "
                "unrealised P&L until the history is loaded."
            ),
        )

    peak = float(highs.max())
    if peak >= cost * corroboration_fraction:
        return (
            CostBasisStatus.OK,
            (
                f"cost basis {cost:,.2f} is {ratio:.1f}x market, but the history peaks at "
                f"{peak:,.2f} — the drawdown is corroborated and the loss is genuine."
            ),
        )

    implied = cost / peak if peak else float("inf")
    named = _nearest_split_ratio(implied)
    return (
        CostBasisStatus.CORPORATE_ACTION_SUSPECTED,
        (
            f"cost basis {cost:,.2f} is {ratio:.1f}x the {price:,.2f} market price, but the "
            f"price history never exceeds {peak:,.2f} ({implied:.1f}x below the basis)"
            + (f" — consistent with an un-rebased {named} reverse split" if named else "")
            + ". Treat the unrealised P&L as unverified until the corporate action is "
              "confirmed against IBKR."
        ),
    )


def _history_highs(bars: pd.DataFrame | pd.Series | None) -> pd.Series | None:
    """Highest observed price per bar — prefers `high`, falls back to `close`."""
    if bars is None:
        return None
    if isinstance(bars, pd.Series):
        s = pd.to_numeric(bars, errors="coerce").dropna()
        return s if len(s) else None
    if len(bars) == 0:
        return None
    for col in ("high", "close", "High", "Close"):
        if col in bars.columns:
            s = pd.to_numeric(bars[col], errors="coerce").dropna()
            if len(s):
                return s
    return None


def corporate_action_reconciliation(
    status: CostBasisStatus,
    note: str,
    avg_cost: float | None,
    last_price: float | None,
) -> Reconciliation | None:
    """
    Turn a suspected corporate action into a Reconciliation so it rides along
    with `PortfolioSnapshot.reconciliation` and gets badged like any other
    unresolved disagreement.
    """
    if status is CostBasisStatus.OK:
        return None
    cost, price = safe_float(avg_cost), safe_float(last_price)
    return Reconciliation(
        field="cost_basis",
        ibkr=cost,
        yahoo=price,
        diff_pct=(cost / price * 100.0 - 100.0) if (cost and price) else None,
        tolerance_pct=COST_BASIS_RATIO_THRESHOLD * 100.0,
        breached=status is CostBasisStatus.CORPORATE_ACTION_SUSPECTED,
        note=note,
    )


# ═══════════════════════════ reporting ═══════════════════════════

def breached(recs: Iterable[Reconciliation]) -> list[Reconciliation]:
    return [r for r in recs if r.breached]


def any_breached(recs: Iterable[Reconciliation]) -> bool:
    return any(r.breached for r in recs)


def summarize(recs: Sequence[Reconciliation]) -> str:
    """One line for the nightly job log."""
    bad = breached(recs)
    if not bad:
        return f"{len(recs)} check(s), all within tolerance"
    fields = ", ".join(sorted({r.field.split("@")[0] for r in bad}))
    return f"{len(bad)}/{len(recs)} check(s) breached: {fields}"
