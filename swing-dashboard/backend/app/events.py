"""
The tape — one chronological event stream across all six event classes.

The organising rule, straight from the spec: **every event is paired with its
price reaction.** A headline with no move is trivia; a 6% move with no headline
is the thing you most need to see. `moved_price` is therefore the primary sort
key, not the timestamp — the tape ranks by consequence and lets pure noise sink.

Event classes:
  1 earnings          — countdown, surprise, guidance, reaction, 5-day drift
  2 price_anomaly     — > 2x ATR, relvol > 3x, gap > 3%, 52w break, DMA cross,
                        squeeze release
  3 analyst           — upgrades / downgrades / target changes, with the size
  4 corporate_action  — splits, dividends and ex-dates, buybacks, M&A, index
  5 macro             — CPI, PCE, FOMC, NFP, PPI, claims
  6 headline          — ticker-linked news, ranked by whether price moved
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timezone
from typing import Any

from .models import EarningsRow, EventClass, Instrument, MarketEvent, Severity
from .universe import ScanRow

log = logging.getLogger(__name__)

# ── price-anomaly thresholds (spec §3, class 2) ──
MOVE_ATR_MULT = 2.0
RELVOL_MULT = 3.0
GAP_PCT = 3.0

# A headline "moved price" if the reaction clears this. Below it the story is
# noise however dramatic the wording.
HEADLINE_MOVE_PCT = 2.0
EARNINGS_MOVE_PCT = 5.0

MACRO_RELEASES = ("CPI", "PCE", "FOMC", "NFP", "PPI", "Jobless Claims")


def _utc(ts: datetime | date | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.combine(ts, time(0, 0), tzinfo=timezone.utc)


def _sev_for_move(pct: float | None, *, good_is_up: bool = True) -> Severity:
    if pct is None:
        return Severity.NEUTRAL
    mag = abs(pct)
    if mag >= 10:
        strong = True
    elif mag >= 5:
        strong = False
    else:
        return Severity.NEUTRAL
    up = pct > 0 if good_is_up else pct < 0
    if up:
        return Severity.GOOD
    return Severity.CRITICAL if strong else Severity.SERIOUS


# ═══════════════════════ 2 · price & volume anomalies ═══════════════════════


def detect_price_anomalies(rows: Sequence[ScanRow],
                           *, ts: datetime | None = None) -> list[MarketEvent]:
    """Six detectors over the day's scan. All of these moved price by
    construction, so every event they emit carries `moved_price=True`."""
    when = _utc(ts)
    out: list[MarketEvent] = []

    for r in rows:
        sym, conid = r.symbol, r.conid

        # move greater than 2x ATR
        if r.atr14 and r.last:
            move_abs = abs(r.change_pct) / 100.0 * r.last
            if move_abs > MOVE_ATR_MULT * r.atr14:
                out.append(MarketEvent(
                    ts=when, conid=conid, symbol=sym,
                    event_class=EventClass.PRICE_ANOMALY,
                    title=f"{sym} moved {r.change_pct:+.1f}%, "
                          f"{move_abs / r.atr14:.1f}x its ATR",
                    detail=(f"ATR(14) is {r.atr14:,.2f}; today's range covered "
                            f"{move_abs:,.2f}. Position sizing and stops keyed to "
                            f"ATR are now stale."),
                    reaction_pct=r.change_pct, severity=_sev_for_move(r.change_pct),
                    moved_price=True,
                ))

        # relative volume > 3x
        if r.rel_volume and r.rel_volume > RELVOL_MULT:
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym} trading on {r.rel_volume:.1f}x average volume",
                detail=(f"Relative volume {r.rel_volume:.1f}x the 20-day average on a "
                        f"{r.change_pct:+.1f}% move — participation confirms the move."),
                reaction_pct=r.change_pct,
                severity=_sev_for_move(r.change_pct), moved_price=True,
            ))

        # gap > 3%
        if abs(r.gap_pct) > GAP_PCT:
            direction = "up" if r.gap_pct > 0 else "down"
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym} gapped {direction} {abs(r.gap_pct):.1f}%",
                detail=(f"Opened {r.gap_pct:+.1f}% against the prior close; "
                        f"closed the session {r.change_pct:+.1f}%."),
                reaction_pct=r.change_pct,
                severity=_sev_for_move(r.gap_pct), moved_price=True,
            ))

        # 52-week break
        if r.at_new_high:
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym} at a new 52-week high",
                detail=f"No overhead supply. 13-week return {r.return_13w:+.1f}%.",
                reaction_pct=r.change_pct, severity=Severity.GOOD, moved_price=True,
            ))
        elif r.at_new_low:
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym} at a new 52-week low",
                detail=f"13-week return {r.return_13w:+.1f}%; no support overhead to lean on.",
                reaction_pct=r.change_pct, severity=Severity.SERIOUS, moved_price=True,
            ))

        # DMA cross
        if r.dma_cross in ("golden", "death") and (r.days_since_cross or 99) <= 5:
            golden = r.dma_cross == "golden"
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym}: {'golden' if golden else 'death'} cross "
                      f"{r.days_since_cross}d ago",
                detail=("50 DMA crossed above the 200" if golden else
                        "50 DMA crossed below the 200")
                       + f"; price is {'above' if r.above_200dma else 'below'} the 200 DMA.",
                reaction_pct=r.change_pct,
                severity=Severity.GOOD if golden else Severity.SERIOUS,
                moved_price=True,
            ))

        # squeeze release
        if r.squeeze_released:
            out.append(MarketEvent(
                ts=when, conid=conid, symbol=sym,
                event_class=EventClass.PRICE_ANOMALY,
                title=f"{sym}: Bollinger squeeze released {r.change_pct:+.1f}%",
                detail=("Bandwidth was in the lowest decile of six months and has "
                        "expanded — the compression that precedes swing moves has "
                        "resolved."),
                reaction_pct=r.change_pct,
                severity=_sev_for_move(r.change_pct), moved_price=True,
            ))

    return out


# ═══════════════════════ 1 · earnings ═══════════════════════


def earnings_events(rows: Iterable[EarningsRow],
                    *, ts: datetime | None = None) -> list[MarketEvent]:
    out: list[MarketEvent] = []
    for e in rows:
        when = _utc(e.report_date)
        upcoming = e.eps_actual is None and (e.days_until or 0) >= 0
        if upcoming:
            out.append(MarketEvent(
                ts=when, conid=e.conid, symbol=e.symbol,
                event_class=EventClass.EARNINGS,
                title=f"{e.symbol} reports in {e.days_until}d",
                detail=(f"Scheduled {e.report_date.isoformat()}"
                        + (f"; consensus EPS {e.eps_estimate:.2f}."
                           if e.eps_estimate is not None else ".")),
                reaction_pct=None, reaction_label="Calendar",
                severity=Severity.WARNING if (e.days_until or 99) <= 7 else Severity.NEUTRAL,
                moved_price=False,
            ))
            continue

        bits = []
        if e.eps_actual is not None and e.eps_estimate is not None:
            bits.append(f"EPS {e.eps_actual:.2f} vs {e.eps_estimate:.2f} "
                        f"({e.eps_surprise_pct:+.1f}%)"
                        if e.eps_surprise_pct is not None
                        else f"EPS {e.eps_actual:.2f} vs {e.eps_estimate:.2f}")
        if e.revenue_actual is not None and e.revenue_estimate is not None:
            bits.append(f"revenue {e.revenue_actual:,.0f} vs {e.revenue_estimate:,.0f}")
        if e.guidance and e.guidance != "none":
            bits.append(f"guidance {e.guidance}")
        if e.drift_5d_pct is not None:
            bits.append(f"5-session drift {e.drift_5d_pct:+.1f}%")

        moved = e.reaction_pct is not None and abs(e.reaction_pct) >= EARNINGS_MOVE_PCT
        out.append(MarketEvent(
            ts=when, conid=e.conid, symbol=e.symbol,
            event_class=EventClass.EARNINGS,
            title=(f"{e.symbol} reported: {e.reaction_pct:+.1f}%" if e.reaction_pct is not None
                   else f"{e.symbol} reported"),
            detail="; ".join(bits) or "Reported; no consensus data available.",
            reaction_pct=e.reaction_pct,
            reaction_label=None if e.reaction_pct is not None else "Reported",
            severity=_sev_for_move(e.reaction_pct),
            moved_price=moved,
        ))
    return out


# ═══════════════════════ 3 · analyst actions ═══════════════════════


def analyst_events(actions: Iterable[Any],
                   reactions: Mapping[int, float] | None = None) -> list[MarketEvent]:
    """`actions` are Finnhub-shaped rows: action, from/to grade, target changes."""
    reactions = reactions or {}
    out: list[MarketEvent] = []
    for a in actions:
        get = a.get if isinstance(a, Mapping) else (lambda k, d=None: getattr(a, k, d))
        conid = get("conid")
        sym = get("symbol") or "?"
        action = (get("action") or get("gradeAction") or "update").lower()
        frm, to = get("from_grade") or get("fromGrade"), get("to_grade") or get("toGrade")
        firm = get("firm") or get("company") or "an analyst"
        old_t, new_t = get("target_from") or get("targetFrom"), get("target_to") or get("targetTo")

        detail_bits = [f"{firm}"]
        if frm and to:
            detail_bits.append(f"{frm} -> {to}")
        elif to:
            detail_bits.append(str(to))
        if old_t and new_t:
            try:
                chg = (float(new_t) / float(old_t) - 1) * 100
                detail_bits.append(f"target {float(old_t):,.0f} -> {float(new_t):,.0f} ({chg:+.0f}%)")
            except (TypeError, ValueError, ZeroDivisionError):
                detail_bits.append(f"target -> {new_t}")
        elif new_t:
            detail_bits.append(f"target {new_t}")

        reaction = reactions.get(conid) if conid is not None else None
        sev = (Severity.GOOD if "up" in action or "initiat" in action and "buy" in str(to).lower()
               else Severity.SERIOUS if "down" in action else Severity.NEUTRAL)
        out.append(MarketEvent(
            ts=_utc(get("ts") or get("date")), conid=conid, symbol=sym,
            event_class=EventClass.ANALYST,
            title=f"{sym}: {action} by {firm}",
            detail="; ".join(detail_bits),
            reaction_pct=reaction,
            reaction_label=None if reaction is not None else "Flagged",
            severity=sev,
            moved_price=reaction is not None and abs(reaction) >= HEADLINE_MOVE_PCT,
            url=get("url"),
        ))
    return out


# ═══════════════════════ 4 · corporate actions ═══════════════════════


def corporate_action_events(actions: Iterable[Any],
                            reactions: Mapping[int, float] | None = None
                            ) -> list[MarketEvent]:
    reactions = reactions or {}
    out: list[MarketEvent] = []
    for a in actions:
        get = a.get if isinstance(a, Mapping) else (lambda k, d=None: getattr(a, k, d))
        conid = get("conid")
        sym = get("symbol") or "?"
        kind = (get("type") or get("kind") or "corporate action")
        reaction = reactions.get(conid) if conid is not None else None
        sev = Severity.WARNING if str(kind).lower() in {
            "split", "reverse_split", "delisting", "index_delete"} else Severity.NEUTRAL
        out.append(MarketEvent(
            ts=_utc(get("ts") or get("date") or get("ex_date")),
            conid=conid, symbol=sym,
            event_class=EventClass.CORPORATE_ACTION,
            title=f"{sym}: {kind}",
            detail=get("detail") or get("description") or str(kind),
            reaction_pct=reaction,
            reaction_label=None if reaction is not None else "Flagged",
            severity=sev,
            moved_price=reaction is not None and abs(reaction) >= HEADLINE_MOVE_PCT,
            url=get("url"),
        ))
    return out


# ═══════════════════════ 5 · macro calendar ═══════════════════════


def macro_events(calendar: Iterable[Any]) -> list[MarketEvent]:
    """Pre-flagged with date and time. These have no single-name reaction, so
    they carry `reaction_label="Calendar"` and never claim `moved_price`."""
    out: list[MarketEvent] = []
    for c in calendar:
        get = c.get if isinstance(c, Mapping) else (lambda k, d=None: getattr(c, k, d))
        name = get("name") or get("event") or "Macro release"
        out.append(MarketEvent(
            ts=_utc(get("ts") or get("date")), conid=None, symbol=None,
            event_class=EventClass.MACRO,
            title=str(name),
            detail=get("detail") or (
                f"Consensus {get('consensus')}, prior {get('prior')}"
                if get("consensus") is not None else
                "Scheduled release — these dominate single-name moves on the day."),
            reaction_pct=None, reaction_label="Calendar",
            severity=Severity.WARNING if any(
                k in str(name).upper() for k in MACRO_RELEASES) else Severity.NEUTRAL,
            moved_price=False,
            url=get("url"),
        ))
    return out


# ═══════════════════════ 6 · headlines ═══════════════════════


def headline_events(news: Iterable[Any],
                    reactions: Mapping[int, float] | None = None) -> list[MarketEvent]:
    """Ticker-linked news. The reaction is what decides whether it belongs on
    the page at all — this is the filter that keeps the tape from becoming a
    news reader."""
    reactions = reactions or {}
    out: list[MarketEvent] = []
    for n in news:
        get = n.get if isinstance(n, Mapping) else (lambda k, d=None: getattr(n, k, d))
        conid = get("conid")
        sym = get("symbol") or get("related")
        reaction = reactions.get(conid) if conid is not None else None
        moved = reaction is not None and abs(reaction) >= HEADLINE_MOVE_PCT
        out.append(MarketEvent(
            ts=_utc(get("ts") or get("datetime") or get("date")),
            conid=conid, symbol=sym,
            event_class=EventClass.HEADLINE,
            title=str(get("headline") or get("title") or "Headline"),
            detail=str(get("summary") or get("detail") or get("source") or ""),
            reaction_pct=reaction,
            reaction_label=None if reaction is not None else "No price reaction",
            severity=_sev_for_move(reaction) if moved else Severity.NEUTRAL,
            moved_price=moved,
            url=get("url"),
        ))
    return out


# ═══════════════════════ the tape ═══════════════════════


def rank_events(events: Sequence[MarketEvent]) -> list[MarketEvent]:
    """moved_price first, then by the size of the reaction, then recency.

    Headlines with no price move sort to the bottom by construction.
    """
    return sorted(
        events,
        key=lambda e: (
            not e.moved_price,
            -abs(e.reaction_pct or 0.0),
            -(e.ts.timestamp() if e.ts.tzinfo else e.ts.replace(tzinfo=timezone.utc).timestamp()),
        ),
    )


def build_tape(
    *,
    scan_rows: Sequence[ScanRow] = (),
    earnings: Iterable[EarningsRow] = (),
    analyst: Iterable[Any] = (),
    corporate: Iterable[Any] = (),
    macro: Iterable[Any] = (),
    news: Iterable[Any] = (),
    reactions: Mapping[int, float] | None = None,
    limit: int | None = None,
    event_classes: Sequence[EventClass] | None = None,
    conids: Sequence[int] | None = None,
    ts: datetime | None = None,
) -> list[MarketEvent]:
    """All six classes, merged and ranked. `limit` is applied after ranking, so
    what gets cut is always the least consequential end of the tape."""
    reactions = dict(reactions or {})
    # a scan row is itself a price reaction — use it for the classes that only
    # know a ticker, so a headline is never published without its move
    for r in scan_rows:
        reactions.setdefault(r.conid, r.change_pct)

    events: list[MarketEvent] = []
    events += detect_price_anomalies(scan_rows, ts=ts)
    events += earnings_events(earnings, ts=ts)
    events += analyst_events(analyst, reactions)
    events += corporate_action_events(corporate, reactions)
    events += macro_events(macro)
    events += headline_events(news, reactions)

    if event_classes:
        wanted = set(event_classes)
        events = [e for e in events if e.event_class in wanted]
    if conids is not None:
        keep = set(conids)
        events = [e for e in events if e.conid is None or e.conid in keep]

    ranked = rank_events(events)
    return ranked[:limit] if limit else ranked


def build_earnings_calendar(rows: Iterable[EarningsRow],
                            today: date | None = None) -> list[EarningsRow]:
    """Fills `days_until` and sorts upcoming-soonest-first, reported after."""
    today = today or date.today()
    out: list[EarningsRow] = []
    for r in rows:
        if r.days_until is None:
            r = r.model_copy(update={"days_until": (r.report_date - today).days})
        out.append(r)
    out.sort(key=lambda r: (r.eps_actual is not None, abs(r.days_until or 0)))
    return out


def instrument_label(inst: Instrument) -> str:
    """`SOXL 4x · LSEETF` — the badge that stops a ticker collision becoming a
    trade in the wrong product."""
    lev = f" {inst.leverage:g}x" if inst.leverage else ""
    return f"{inst.symbol}{lev} · {inst.exchange}"
