"""
Momentum indicators — "is it accelerating or tiring".

GATING: per the spec, ADX below `settings.adx_gate` means the oscillators here
are noise. `build_momentum_block` takes the ADX reading and sets
MomentumBlock.gated so the UI can grey the whole panel out. An unknown ADX
(too few bars to compute one) also gates — we never present an oscillator as
tradable when we cannot establish there is a trend to trade.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from app.config import settings
from app.models import MomentumBlock

from .trend import _as_float, _last, ema, sma, wilder_rma

__all__ = [
    "rsi",
    "rsi_regime",
    "macd",
    "macd_cross",
    "macd_hist_divergence",
    "stochastic",
    "roc",
    "relative_strength",
    "build_momentum_block",
]

BARS_4W = 20
BARS_13W = 65


# ───────────────────────── RSI ─────────────────────────

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """
    Wilder's RSI(14).

        gain/loss  = positive / negative parts of the close-to-close change
        avg        = Wilder smoothing, seeded on the simple mean of the first n
        RS         = avg_gain / avg_loss
        RSI        = 100 - 100 / (1 + RS)

    First print lands on bar n (0-based), i.e. the (n+1)-th close, exactly as
    in Wilder's published worked example. A zero average loss yields 100.
    """
    c = _as_float(close)
    out = pd.Series(np.nan, index=c.index, dtype=float)
    if len(c) < n + 1:
        return out

    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_rma(gain.iloc[1:], n).reindex(c.index)
    avg_loss = wilder_rma(loss.iloc[1:], n).reindex(c.index)

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # avg_loss == 0 with a real seed means "nothing but up bars" -> 100
    out = out.where(~((avg_loss == 0.0) & avg_gain.notna()), 100.0)
    return out


def rsi_regime(value: float | None) -> Literal["strong", "neutral", "weak"] | None:
    """
    The regime read, not the 30/70 read. In a healthy uptrend RSI holds the
    40-80 band; losing 40 is the warning that matters.
        >= 60  strong   40-60  neutral   < 40  weak
    """
    if value is None:
        return None
    if value >= 60.0:
        return "strong"
    if value >= 40.0:
        return "neutral"
    return "weak"


# ───────────────────────── MACD ─────────────────────────

def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """
    MACD(12,26,9): line = EMA12 - EMA26, signal = EMA9 of the line,
    histogram = line - signal. All EMAs are the recursive adjust=False form.
    """
    c = _as_float(close)
    if len(c) == 0:
        return pd.DataFrame(columns=["macd", "signal", "hist"], dtype=float)
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig}, index=c.index)


def macd_cross(frame: pd.DataFrame) -> Literal["bullish", "bearish", "none"] | None:
    """
    Cross flag for the most recent bar: the histogram changing sign.
    bullish  hist <= 0 on the prior bar and > 0 now
    bearish  hist >= 0 on the prior bar and < 0 now
    none     no sign change on this bar
    """
    if frame is None or "hist" not in frame or len(frame) < 2:
        return None
    h = frame["hist"].dropna()
    if len(h) < 2:
        return None
    prev, now = float(h.iloc[-2]), float(h.iloc[-1])
    if prev <= 0.0 < now:
        return "bullish"
    if prev >= 0.0 > now:
        return "bearish"
    return "none"


def macd_hist_divergence(
    close: pd.Series, frame: pd.DataFrame, lookback: int = 20
) -> Literal["bullish", "bearish"] | None:
    """
    Histogram divergence over `lookback` bars, compared against the preceding
    window of the same length:
      bearish  price made a higher high while the histogram peak fell
      bullish  price made a lower low while the histogram trough rose
    None when neither holds or there is not enough history.
    """
    c = _as_float(close).dropna()
    if frame is None or "hist" not in frame:
        return None
    h = frame["hist"].dropna()
    if len(c) < 2 * lookback or len(h) < 2 * lookback:
        return None
    c_now, c_prev = c.iloc[-lookback:], c.iloc[-2 * lookback : -lookback]
    h_now, h_prev = h.iloc[-lookback:], h.iloc[-2 * lookback : -lookback]

    if c_now.max() > c_prev.max() and h_now.max() < h_prev.max():
        return "bearish"
    if c_now.min() < c_prev.min() and h_now.min() > h_prev.min():
        return "bullish"
    return None


# ───────────────────────── stochastic ─────────────────────────

def stochastic(
    bars: pd.DataFrame, k: int = 14, k_smooth: int = 3, d_smooth: int = 3
) -> pd.DataFrame:
    """
    Slow stochastic (14,3,3).

        raw %K = 100 * (close - lowest_low_k) / (highest_high_k - lowest_low_k)
        %K     = SMA(raw %K, k_smooth)      <- the "slow" line that is reported
        %D     = SMA(%K, d_smooth)

    A flat range (high == low over the window) gives 50, the neutral read,
    rather than a divide-by-zero.
    """
    idx = bars.index
    if len(bars) < k:
        nan = pd.Series(np.nan, index=idx, dtype=float)
        return pd.DataFrame({"k": nan, "d": nan})
    h, l, c = _as_float(bars["h"]), _as_float(bars["l"]), _as_float(bars["c"])
    hh = h.rolling(k, min_periods=k).max()
    ll = l.rolling(k, min_periods=k).min()
    rng = (hh - ll)
    raw = 100.0 * (c - ll) / rng.replace(0.0, np.nan)
    raw = raw.where(rng != 0.0, 50.0)
    kk = sma(raw, k_smooth)
    dd = sma(kk, d_smooth)
    return pd.DataFrame({"k": kk, "d": dd}, index=idx)


# ───────────────────────── rate of change / RS ─────────────────────────

def roc(s: pd.Series, n: int) -> pd.Series:
    """Percent change over n bars."""
    v = _as_float(s)
    return (v / v.shift(n) - 1.0) * 100.0


def _period_return_pct(s: pd.Series, n: int) -> float | None:
    v = _as_float(s).dropna()
    if len(v) < n + 1:
        return None
    start, end = float(v.iloc[-(n + 1)]), float(v.iloc[-1])
    if start == 0 or not np.isfinite(start) or not np.isfinite(end):
        return None
    return (end / start - 1.0) * 100.0


def relative_strength(
    price: pd.Series, benchmark: pd.Series | None, n: int
) -> float | None:
    """
    Excess return in PERCENTAGE POINTS over n bars:

        rs = asset_return_pct - benchmark_return_pct

    The two series are inner-joined on date first, so a benchmark with a
    different holiday calendar cannot silently shift the window. By
    construction a series measured against itself returns exactly 0.0.
    """
    if benchmark is None:
        return None
    a = _as_float(price).dropna()
    b = _as_float(benchmark).dropna()
    if a.empty or b.empty:
        return None
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if len(joined) < n + 1:
        return None
    ra = _period_return_pct(joined["a"], n)
    rb = _period_return_pct(joined["b"], n)
    if ra is None or rb is None:
        return None
    return ra - rb


# ───────────────────────── block ─────────────────────────

def build_momentum_block(
    bars: pd.DataFrame,
    benchmark: pd.Series | None = None,
    sector: pd.Series | None = None,
    adx14: float | None = None,
) -> MomentumBlock:
    """
    Assemble the MomentumBlock.

    `adx14` is the gate: pass the TrendBlock's adx14 in. gated is True when
    ADX < settings.adx_gate, and also when ADX is unknown.
    """
    gated = True if adx14 is None else bool(adx14 < settings.adx_gate)

    if bars is None or len(bars) == 0:
        return MomentumBlock(gated=gated)

    c = _as_float(bars["c"])

    rsi_v = _last(rsi(c, 14))
    m = macd(c)
    st = stochastic(bars)

    return MomentumBlock(
        rsi14=rsi_v,
        rsi_regime=rsi_regime(rsi_v),
        macd=_last(m["macd"]) if len(m) else None,
        macd_signal=_last(m["signal"]) if len(m) else None,
        macd_hist=_last(m["hist"]) if len(m) else None,
        macd_cross=macd_cross(m),
        stoch_k=_last(st["k"]),
        stoch_d=_last(st["d"]),
        roc5=_last(roc(c, 5)),
        roc20=_last(roc(c, 20)),
        rs_vs_index_4w=relative_strength(c, benchmark, BARS_4W),
        rs_vs_index_13w=relative_strength(c, benchmark, BARS_13W),
        rs_vs_sector_13w=relative_strength(c, sector, BARS_13W),
        gated=gated,
    )
