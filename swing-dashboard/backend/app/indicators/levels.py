"""
Levels — auto-detected pivots clustered into support and resistance bands,
plus the prior session's high/low/close and today's gap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.models import LevelsBlock

from .trend import _as_float, _last

__all__ = [
    "swing_pivots",
    "swing_high_price",
    "cluster_levels",
    "support_resistance",
    "prior_day",
    "gap_pct",
    "build_levels_block",
]

DEFAULT_LOOKBACK = 3          # fractal half-width: 3 bars either side
DEFAULT_TOLERANCE_PCT = 1.5   # pivots within this % of each other are one band
MAX_BANDS = 3                 # how many bands we surface per side


def swing_pivots(
    bars: pd.DataFrame, lookback: int = DEFAULT_LOOKBACK
) -> tuple[pd.Series, pd.Series]:
    """
    Fractal pivot detection.

    A bar is a pivot high when its high is the maximum of the window
    [i-lookback, i+lookback] and strictly greater than every neighbour in that
    window; a pivot low is the mirror image on lows. `lookback` is
    configurable — 3 for swing trading, larger for structural levels.

    Returns (pivot_highs, pivot_lows) as date-indexed price series. The last
    `lookback` bars can never be pivots: confirmation needs bars to the right,
    and inventing an unconfirmed pivot would be lying about the level.
    """
    empty = pd.Series(dtype=float)
    if bars is None or len(bars) < 2 * lookback + 1 or lookback < 1:
        return empty, empty

    h = _as_float(bars["h"]).to_numpy()
    l = _as_float(bars["l"]).to_numpy()
    idx = bars.index

    hi_dates, hi_vals, lo_dates, lo_vals = [], [], [], []
    for i in range(lookback, len(h) - lookback):
        win = slice(i - lookback, i + lookback + 1)
        others_h = np.delete(h[win], lookback)
        others_l = np.delete(l[win], lookback)
        if h[i] > others_h.max():
            hi_dates.append(idx[i])
            hi_vals.append(float(h[i]))
        if l[i] < others_l.min():
            lo_dates.append(idx[i])
            lo_vals.append(float(l[i]))

    return (
        pd.Series(hi_vals, index=pd.Index(hi_dates), dtype=float),
        pd.Series(lo_vals, index=pd.Index(lo_dates), dtype=float),
    )


def swing_high_price(
    bars: pd.DataFrame, lookback: int = DEFAULT_LOOKBACK
) -> float | None:
    """
    The most recent CONFIRMED swing high. Falls back to the running maximum of
    the last 60 highs when no fractal pivot exists (very short or one-way
    series) so drawdown always has an anchor.
    """
    if bars is None or len(bars) == 0:
        return None
    highs, _ = swing_pivots(bars, lookback)
    if not highs.empty:
        return float(highs.iloc[-1])
    h = _as_float(bars["h"]).dropna()
    if h.empty:
        return None
    return float(h.iloc[-60:].max())


def cluster_levels(
    prices: list[float] | pd.Series, tolerance_pct: float = DEFAULT_TOLERANCE_PCT
) -> list[tuple[float, int]]:
    """
    Single-pass agglomerative clustering of pivot prices into bands.

    Prices are sorted; a price joins the open cluster while it sits within
    `tolerance_pct` of that cluster's running mean, otherwise it starts a new
    one. Returns [(band_price, touch_count), ...] where band_price is the mean
    of the cluster — touch count is what makes a level worth respecting, so it
    is carried out rather than discarded.
    """
    vals = sorted(float(p) for p in pd.Series(prices, dtype=float).dropna())
    if not vals:
        return []
    bands: list[list[float]] = [[vals[0]]]
    for p in vals[1:]:
        centre = float(np.mean(bands[-1]))
        if centre != 0 and abs(p - centre) / abs(centre) * 100.0 <= tolerance_pct:
            bands[-1].append(p)
        else:
            bands.append([p])
    return [(float(np.mean(b)), len(b)) for b in bands]


def support_resistance(
    bars: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    max_bands: int = MAX_BANDS,
) -> tuple[list[float], list[float]]:
    """
    Support = clustered pivot LOWS below the last close, nearest first.
    Resistance = clustered pivot HIGHS above the last close, nearest first.
    Bands on the wrong side of price are dropped: a "support" above spot is
    resistance, and mislabelling it would be worse than omitting it.
    """
    close = _last(bars["c"]) if bars is not None and len(bars) else None
    if close is None:
        return [], []
    highs, lows = swing_pivots(bars, lookback)
    sup = [p for p, _ in cluster_levels(lows, tolerance_pct) if p < close]
    res = [p for p, _ in cluster_levels(highs, tolerance_pct) if p > close]
    sup.sort(reverse=True)          # nearest support first
    res.sort()                      # nearest resistance first
    return [round(p, 4) for p in sup[:max_bands]], [round(p, 4) for p in res[:max_bands]]


def prior_day(bars: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """(prior_high, prior_low, prior_close) — the bar before the last one."""
    if bars is None or len(bars) < 2:
        return None, None, None
    row = bars.iloc[-2]
    return float(row["h"]), float(row["l"]), float(row["c"])


def gap_pct(bars: pd.DataFrame) -> float | None:
    """Today's open against the prior close, in percent."""
    if bars is None or len(bars) < 2:
        return None
    prev_close = float(bars["c"].iloc[-2])
    today_open = float(bars["o"].iloc[-1])
    if prev_close == 0 or not np.isfinite(prev_close):
        return None
    return (today_open / prev_close - 1.0) * 100.0


def build_levels_block(
    bars: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> LevelsBlock:
    if bars is None or len(bars) == 0:
        return LevelsBlock()
    sup, res = support_resistance(bars, lookback, tolerance_pct)
    ph, pl, pc = prior_day(bars)
    return LevelsBlock(
        support=sup,
        resistance=res,
        prior_day_high=ph,
        prior_day_low=pl,
        prior_close=pc,
        gap_pct=gap_pct(bars),
    )
