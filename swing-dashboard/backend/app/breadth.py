"""
Market breadth — "is *any* long setup worth taking today".

The single best tell in the spec is equal-weight versus cap-weight: when the
equal-weight basket is keeping up, the rally is broad; when it is 2+ points
behind over 13 weeks, seven stocks are carrying the tape and a swing long in
the eighth is fighting the market.

Pure computation over member series — no sources, no cache.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from .models import BreadthSnapshot, IndicatorSet

log = logging.getLogger(__name__)

SESSIONS_1W = 5
SESSIONS_4W = 20
SESSIONS_13W = 65

# Spec thresholds. Equal-weight minus cap-weight, 13 weeks, percentage points.
SPREAD_BROAD = 0.0
SPREAD_MIXED = -2.0


def breadth_verdict(spread_13w: float) -> Literal["broad", "mixed", "narrow"]:
    """spread >= 0 -> broad; >= -2 -> mixed; else narrow."""
    if spread_13w >= SPREAD_BROAD:
        return "broad"
    if spread_13w >= SPREAD_MIXED:
        return "mixed"
    return "narrow"


# ─────────────────────────── members ───────────────────────────


@dataclass
class BreadthMember:
    """One scanned name, reduced to the handful of facts breadth needs."""
    conid: int
    symbol: str
    closes: np.ndarray | None = None
    change_pct: float | None = None
    above_50dma: bool | None = None
    above_200dma: bool | None = None
    at_new_high_52w: bool | None = None
    at_new_low_52w: bool | None = None
    return_4w: float | None = None

    def __post_init__(self) -> None:
        if self.closes is not None and not isinstance(self.closes, np.ndarray):
            self.closes = np.asarray(self.closes, dtype=float)

    @classmethod
    def from_indicator_set(cls, ind: IndicatorSet,
                           closes: Sequence[float] | None = None) -> "BreadthMember":
        t = ind.trend
        above50 = None if t.ema50 is None else ind.close > t.ema50
        above200 = None if t.ema200 is None else ind.close > t.ema200
        # "at a new 52w high" = within a rounding error of the high, not merely near it.
        hi = t.pct_from_52w_high
        lo = t.pct_from_52w_low
        return cls(
            conid=ind.conid,
            symbol=ind.symbol,
            closes=None if closes is None else np.asarray(closes, dtype=float),
            change_pct=ind.change_pct,
            above_50dma=above50,
            above_200dma=above200,
            at_new_high_52w=None if hi is None else hi >= -0.05,
            at_new_low_52w=None if lo is None else lo <= 0.05,
            return_4w=ind.momentum.roc20,
        )


def _window_return_pct(closes: np.ndarray | None, sessions: int) -> float | None:
    if closes is None or closes.size < 2:
        return None
    n = min(sessions, closes.size - 1)
    start = closes[-(n + 1)]
    if start == 0:
        return None
    return float((closes[-1] / start - 1.0) * 100.0)


def _indexed(series: np.ndarray) -> np.ndarray:
    if series.size == 0 or series[0] == 0:
        return series
    return series / series[0] * 100.0


def equal_weight_series(members: Sequence[BreadthMember],
                        length: int | None = None) -> np.ndarray:
    """Equal-weight basket indexed to 100, built by averaging normalised members.

    Members shorter than the requested window are dropped rather than
    forward-filled — a padded series would quietly flatten the spread, which is
    the one number the verdict turns on.
    """
    usable = [m.closes for m in members
              if m.closes is not None and m.closes.size >= 2]
    if not usable:
        return np.zeros(0, dtype=float)
    n = length or min(s.size for s in usable)
    kept = [_indexed(s[-n:]) for s in usable if s.size >= n]
    if not kept:
        return np.zeros(0, dtype=float)
    dropped = len(usable) - len(kept)
    if dropped:
        log.info("breadth: %d member(s) too short for a %d-session window, dropped",
                 dropped, n)
    return np.mean(np.vstack(kept), axis=0)


# ─────────────────────────── the snapshot ───────────────────────────


@dataclass
class BreadthChart:
    """The two indexed series the overview chart draws, plus their dates."""
    dates: list[date]
    index_series: list[float]
    equal_weight_series: list[float]


def compute_breadth(
    members: Sequence[BreadthMember],
    benchmark_closes: Sequence[float] | None = None,
    *,
    benchmark_dates: Sequence[date] | None = None,
    equal_weight_closes: Sequence[float] | None = None,
) -> tuple[BreadthSnapshot, BreadthChart]:
    """Breadth across the scanned universe, plus the overview chart series.

    `equal_weight_closes` (e.g. RSP) is used for the equal-weight leg when it is
    supplied; otherwise the equal-weight basket is synthesised from the members
    themselves. Both are legitimate — RSP is the market's answer, the synthetic
    basket is *this universe's* answer — so the caller chooses.
    """
    n_members = len(members)
    bench = None if benchmark_closes is None else np.asarray(benchmark_closes, dtype=float)

    above50 = sum(1 for m in members if m.above_50dma)
    known50 = sum(1 for m in members if m.above_50dma is not None)
    above200 = sum(1 for m in members if m.above_200dma)
    known200 = sum(1 for m in members if m.above_200dma is not None)

    advancers = sum(1 for m in members if (m.change_pct or 0) > 0)
    decliners = sum(1 for m in members if (m.change_pct or 0) < 0)
    new_highs = sum(1 for m in members if m.at_new_high_52w)
    new_lows = sum(1 for m in members if m.at_new_low_52w)

    r4 = [m.return_4w if m.return_4w is not None
          else _window_return_pct(m.closes, SESSIONS_4W) for m in members]
    r4 = [x for x in r4 if x is not None]
    median_4w = float(np.median(r4)) if r4 else 0.0

    # ── the 13-week spread ──
    index_13w = _window_return_pct(bench, SESSIONS_13W) or 0.0

    if equal_weight_closes is not None:
        ew_closes = np.asarray(equal_weight_closes, dtype=float)
    else:
        ew_closes = equal_weight_series(members)
    ew_13w = _window_return_pct(ew_closes, SESSIONS_13W) or 0.0

    spread = ew_13w - index_13w

    snapshot = BreadthSnapshot(
        universe_size=n_members,
        above_50dma=above50,
        above_50dma_pct=round(100.0 * above50 / known50, 2) if known50 else 0.0,
        above_200dma=above200 if known200 else None,
        advancers=advancers,
        decliners=decliners,
        new_highs_52w=new_highs,
        new_lows_52w=new_lows,
        median_return_4w=round(median_4w, 4),
        index_return_13w=round(index_13w, 4),
        equal_weight_return_13w=round(ew_13w, 4),
        spread_13w=round(spread, 4),
        verdict=breadth_verdict(spread),
    )

    chart = _build_chart(bench, ew_closes, benchmark_dates)
    return snapshot, chart


def _build_chart(bench: np.ndarray | None, ew: np.ndarray,
                 dates: Sequence[date] | None) -> BreadthChart:
    lengths = [x.size for x in (bench, ew) if x is not None and x.size]
    if not lengths:
        return BreadthChart(dates=[], index_series=[], equal_weight_series=[])
    n = min(lengths)
    if dates:
        n = min(n, len(dates))
    idx = _indexed(bench[-n:]) if bench is not None and bench.size else np.zeros(0)
    eqw = _indexed(ew[-n:]) if ew.size else np.zeros(0)
    return BreadthChart(
        dates=list(dates[-n:]) if dates else [],
        index_series=[round(float(x), 4) for x in idx],
        equal_weight_series=[round(float(x), 4) for x in eqw],
    )
