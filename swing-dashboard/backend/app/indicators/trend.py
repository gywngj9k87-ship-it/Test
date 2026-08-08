"""
Trend indicators — "which way, and how strongly".

Input convention everywhere in this package: a pandas DataFrame indexed by
date with columns o, h, l, c, v. Pure pandas/numpy; no TA-Lib, no pandas-ta.

Every function returns None (or a series of NaN) rather than raising when the
input is too short. The engine relies on that.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import settings
from app.models import TrendBlock

__all__ = [
    "ema",
    "sma",
    "wilder_rma",
    "true_range",
    "adx",
    "cross_state",
    "linreg_slope",
    "slope20",
    "pct_from_52w_high",
    "pct_from_52w_low",
    "build_trend_block",
]

# 52 weeks of trading sessions, and the minimum sample we accept for a
# "52-week" reading (a name that only listed 3 months ago still gets a number,
# but we refuse to call 20 bars a year).
BARS_52W = 252
MIN_52W_BARS = 60


# ───────────────────────── primitives ─────────────────────────

def ema(s: pd.Series, n: int) -> pd.Series:
    """
    Exponential moving average, recursive form, seeded on the first observation.

        alpha  = 2 / (n + 1)
        ema[0] = x[0]
        ema[t] = alpha * x[t] + (1 - alpha) * ema[t-1]

    This is pandas `ewm(span=n, adjust=False)`. Chosen over the SMA-seeded
    variant because it is the convention MACD is defined with, and because it
    is the one a reader can reproduce by hand from the first bar.
    """
    s = _as_float(s)
    if s.empty:
        return s
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    """Simple moving average. NaN until n observations exist."""
    s = _as_float(s)
    return s.rolling(n, min_periods=n).mean()


def wilder_rma(s: pd.Series, n: int) -> pd.Series:
    """
    Wilder's smoothing (a.k.a. RMA / SMMA), used by RSI, ATR and ADX.

        rma[n-1] = mean(x[0..n-1])                  (simple seed)
        rma[t]   = (rma[t-1] * (n-1) + x[t]) / n

    Equivalent to an EWMA with alpha = 1/n but with Wilder's simple-average
    seed, which is what the published worked examples use. NaN before the seed.
    """
    s = _as_float(s)
    v = s.to_numpy(dtype=float)
    out = np.full(v.shape, np.nan)
    if v.size < n or n < 1:
        return pd.Series(out, index=s.index, name=s.name)
    if np.isnan(v[:n]).any():
        return pd.Series(out, index=s.index, name=s.name)
    prev = float(np.mean(v[:n]))
    out[n - 1] = prev
    for i in range(n, v.size):
        x = v[i]
        if np.isnan(x):
            out[i] = prev
            continue
        prev = (prev * (n - 1) + x) / n
        out[i] = prev
    return pd.Series(out, index=s.index, name=s.name)


def true_range(bars: pd.DataFrame) -> pd.Series:
    """max(h-l, |h-prev_c|, |l-prev_c|). First bar is NaN (no previous close)."""
    h, l, c = _as_float(bars["h"]), _as_float(bars["l"]), _as_float(bars["c"])
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    return tr


# ───────────────────────── ADX ─────────────────────────

def adx(bars: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """
    Wilder's ADX(14). Returns a frame with plus_di, minus_di, dx, adx.

    Directional movement is the classic asymmetric rule:
        +DM = up_move   if up_move > down_move and up_move > 0   else 0
        -DM = down_move if down_move > up_move and down_move > 0 else 0
    Both +DM/-DM and TR are Wilder-smoothed over n; DX is then Wilder-smoothed
    over n again, so the first ADX print lands on bar 2n-1 (index 27 for n=14).
    """
    idx = bars.index
    empty = pd.DataFrame(
        {k: np.full(len(idx), np.nan) for k in ("plus_di", "minus_di", "dx", "adx")},
        index=idx,
    )
    if len(bars) < 2 * n:
        return empty

    h, l = _as_float(bars["h"]), _as_float(bars["l"])
    up = h.diff()
    down = -l.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=idx)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=idx)
    tr = true_range(bars)

    # drop the leading NaN bar so the Wilder seed uses n real observations
    atr_n = wilder_rma(tr.iloc[1:], n).reindex(idx)
    plus_n = wilder_rma(plus_dm.iloc[1:], n).reindex(idx)
    minus_n = wilder_rma(minus_dm.iloc[1:], n).reindex(idx)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_n / atr_n
        minus_di = 100.0 * minus_n / atr_n
        denom = plus_di + minus_di
        dx = 100.0 * (plus_di - minus_di).abs() / denom.replace(0.0, np.nan)

    adx_line = wilder_rma(dx.dropna(), n).reindex(idx)
    return pd.DataFrame(
        {"plus_di": plus_di, "minus_di": minus_di, "dx": dx, "adx": adx_line},
        index=idx,
    )


# ───────────────────────── crosses ─────────────────────────

def cross_state(fast: pd.Series, slow: pd.Series) -> tuple[bool | None, int | None]:
    """
    Golden / death cross state for two moving averages (we use SMA50 / SMA200).

    Returns (golden, days_since_cross):
      golden           True when fast is currently above slow, else False.
      days_since_cross bars elapsed since the most recent sign change of
                       (fast - slow); None when no cross exists in the sample.
    "days" are trading bars, which is what the series actually carries.
    """
    diff = (_as_float(fast) - _as_float(slow)).dropna()
    if diff.empty:
        return None, None
    sign = np.sign(diff.to_numpy())
    golden = bool(sign[-1] > 0)
    changes = np.flatnonzero((sign[1:] != sign[:-1]) & (sign[1:] != 0))
    if changes.size == 0:
        return golden, None
    last_cross_pos = int(changes[-1]) + 1          # position within `diff`
    return golden, int(len(diff) - 1 - last_cross_pos)


# ───────────────────────── slope & range ─────────────────────────

def linreg_slope(s: pd.Series, n: int = 20) -> float | None:
    """
    Ordinary-least-squares slope of the last n observations against bar number.
    Units: price per bar. None if fewer than n usable observations.
    """
    s = _as_float(s).dropna()
    if len(s) < n or n < 2:
        return None
    y = s.iloc[-n:].to_numpy(dtype=float)
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope


def slope20(bars: pd.DataFrame) -> float | None:
    return linreg_slope(bars["c"], 20)


def slope_pct_per_bar(bars: pd.DataFrame, n: int = 20) -> float | None:
    """
    Scale-free version of the slope: percent of the window's mean price per
    bar. Used by the setup score so a $900 stock and a $9 stock compare.
    """
    s = _as_float(bars["c"]).dropna()
    if len(s) < n:
        return None
    slope = linreg_slope(s, n)
    base = float(s.iloc[-n:].mean())
    if slope is None or base == 0:
        return None
    return slope / base * 100.0


def pct_from_52w_high(bars: pd.DataFrame) -> float | None:
    """Percent distance of the last close from the trailing 52-week high (<= 0)."""
    w = _window(bars["h"], BARS_52W)
    c = _last(bars["c"])
    if w is None or c is None:
        return None
    hi = float(w.max())
    if hi == 0:
        return None
    return (c / hi - 1.0) * 100.0


def pct_from_52w_low(bars: pd.DataFrame) -> float | None:
    """Percent distance of the last close above the trailing 52-week low (>= 0)."""
    w = _window(bars["l"], BARS_52W)
    c = _last(bars["c"])
    if w is None or c is None:
        return None
    lo = float(w.min())
    if lo == 0:
        return None
    return (c / lo - 1.0) * 100.0


# ───────────────────────── block ─────────────────────────

def build_trend_block(bars: pd.DataFrame) -> TrendBlock:
    """Assemble the TrendBlock. Short series simply carry None fields."""
    if bars is None or len(bars) == 0:
        return TrendBlock()

    c = _as_float(bars["c"])
    close = _last(c)

    e20 = _last(ema(c, 20)) if len(c) >= 20 else None
    e50 = _last(ema(c, 50)) if len(c) >= 50 else None
    e200 = _last(ema(c, 200)) if len(c) >= 200 else None

    stack = None
    if None not in (e20, e50, e200, close):
        stack = bool(e20 > e50 > e200 and close > e20)

    golden, days_since = (None, None)
    if len(c) >= 200:
        golden, days_since = cross_state(sma(c, 50), sma(c, 200))

    adx14 = _last(adx(bars, 14)["adx"])
    trend_strong = None if adx14 is None else bool(adx14 >= settings.adx_gate)

    return TrendBlock(
        ema20=e20,
        ema50=e50,
        ema200=e200,
        stack_aligned=stack,
        golden_cross=golden,
        days_since_cross=days_since,
        adx14=adx14,
        trend_strong=trend_strong,
        slope20=slope20(bars),
        pct_from_52w_high=pct_from_52w_high(bars),
        pct_from_52w_low=pct_from_52w_low(bars),
    )


# ───────────────────────── shared helpers ─────────────────────────

def _as_float(s: pd.Series) -> pd.Series:
    return pd.Series(s, copy=False).astype(float)


def _last(s: pd.Series | None) -> float | None:
    """Last finite value of a series, as a plain float, else None."""
    if s is None or len(s) == 0:
        return None
    v = pd.Series(s).dropna()
    if v.empty:
        return None
    x = float(v.iloc[-1])
    return None if not np.isfinite(x) else x


def _window(s: pd.Series, n: int, minimum: int = MIN_52W_BARS) -> pd.Series | None:
    v = _as_float(s).dropna()
    if len(v) < minimum:
        return None
    return v.iloc[-n:]
