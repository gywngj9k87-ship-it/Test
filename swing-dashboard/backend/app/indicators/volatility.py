"""
Volatility & risk — "how much room, and what stop".

ATR drives position sizing and stop placement, so it is Wilder's ATR, not a
simple mean of true ranges; the two differ by enough to move a stop.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import settings
from app.models import VolatilityBlock

from .levels import swing_high_price
from .trend import _as_float, _last, sma, true_range, wilder_rma

__all__ = [
    "atr",
    "atr_pct",
    "bollinger",
    "percent_b",
    "bb_squeeze",
    "realized_vol",
    "beta",
    "drawdown_from_swing_high",
    "build_volatility_block",
]

TRADING_DAYS = 252
SQUEEZE_WINDOW = 126        # ~6 months of sessions
MIN_SQUEEZE_OBS = 40        # below this the percentile is not meaningful
BETA_WINDOW = 252
MIN_BETA_OBS = 30


# ───────────────────────── ATR ─────────────────────────

def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """
    Wilder's ATR(n): Wilder smoothing of the true range, seeded on the simple
    mean of the first n true ranges. The first bar has no previous close and
    is excluded from the seed.
    """
    if bars is None or len(bars) < n + 1:
        return pd.Series(np.nan, index=getattr(bars, "index", None), dtype=float)
    tr = true_range(bars)
    return wilder_rma(tr.iloc[1:], n).reindex(bars.index)


def atr_pct(bars: pd.DataFrame, n: int = 14) -> float | None:
    """ATR as a percent of the last close — the scale-free form used for sizing."""
    a = _last(atr(bars, n))
    c = _last(bars["c"]) if bars is not None and len(bars) else None
    if a is None or c in (None, 0):
        return None
    return a / c * 100.0


# ───────────────────────── Bollinger ─────────────────────────

def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """
    Bollinger Bands (20, 2) with %B and bandwidth.

        mid    = SMA(close, n)
        sd     = POPULATION standard deviation over the same window (ddof=0 —
                 the window is the whole population of interest, and it is the
                 convention every charting package uses)
        upper  = mid + k*sd,  lower = mid - k*sd
        %B     = (close - lower) / (upper - lower)   -> 0 at lower, 0.5 at mid,
                                                        1 at upper
        width  = (upper - lower) / mid * 100         (percent of the mid band)
    """
    c = _as_float(close)
    idx = c.index
    if len(c) < n:
        nan = pd.Series(np.nan, index=idx, dtype=float)
        return pd.DataFrame(
            {"mid": nan, "upper": nan, "lower": nan, "pct_b": nan, "width": nan}
        )
    mid = sma(c, n)
    sd = c.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    span = (upper - lower).replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "mid": mid,
            "upper": upper,
            "lower": lower,
            "pct_b": (c - lower) / span,
            "width": (upper - lower) / mid.replace(0.0, np.nan) * 100.0,
        },
        index=idx,
    )


def percent_b(price: float, upper: float, lower: float) -> float | None:
    """%B as a pure function of the three numbers. 0.5 at mid, 1.0 at upper."""
    if upper is None or lower is None or price is None or upper == lower:
        return None
    return (price - lower) / (upper - lower)


def bb_squeeze(
    width: pd.Series,
    percentile: float | None = None,
    window: int = SQUEEZE_WINDOW,
) -> bool | None:
    """
    Squeeze = current bandwidth sits in the lowest `percentile` of its own
    trailing 6-month distribution (default 0.10 from settings.squeeze_percentile).

    Judgement call: the reference distribution is the trailing `window` bars of
    bandwidth INCLUDING today, so the test is "is today among the tightest 10%
    of the last six months" — a rolling, self-referential percentile rather
    than a fixed historical threshold. Needs MIN_SQUEEZE_OBS observations,
    otherwise None (an unknown, not a False).
    """
    p = settings.squeeze_percentile if percentile is None else percentile
    w = pd.Series(width, dtype=float).dropna()
    if len(w) < MIN_SQUEEZE_OBS:
        return None
    ref = w.iloc[-window:]
    threshold = float(ref.quantile(p))
    return bool(float(w.iloc[-1]) <= threshold)


# ───────────────────────── vol, beta, drawdown ─────────────────────────

def realized_vol(close: pd.Series, n: int = 20) -> float | None:
    """
    Annualised realised volatility, in percent: the sample standard deviation
    (ddof=1) of the last n daily LOG returns, scaled by sqrt(252).
    """
    c = _as_float(close).dropna()
    if len(c) < n + 1 or (c <= 0).any():
        return None
    r = np.log(c / c.shift(1)).dropna().iloc[-n:]
    if len(r) < n:
        return None
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100.0)


def beta(close: pd.Series, benchmark: pd.Series | None, window: int = BETA_WINDOW) -> float | None:
    """
    OLS beta of daily simple returns against the benchmark's, over the last
    `window` overlapping sessions. Series are inner-joined on date first, so
    mismatched calendars cannot fabricate a return. Beta of a series against
    itself is exactly 1.0.
    """
    if benchmark is None:
        return None
    a = _as_float(close).dropna()
    b = _as_float(benchmark).dropna()
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if len(joined) < MIN_BETA_OBS + 1:
        return None
    r = joined.pct_change().dropna().iloc[-window:]
    if len(r) < MIN_BETA_OBS:
        return None
    var_b = float(r["b"].var(ddof=1))
    if var_b == 0 or not np.isfinite(var_b):
        return None
    cov = float(r["a"].cov(r["b"]))
    return cov / var_b


def drawdown_from_swing_high(bars: pd.DataFrame, lookback: int = 3) -> float | None:
    """
    Percent below the most recent confirmed swing high (<= 0, or 0 when price
    has already exceeded it).
    """
    if bars is None or len(bars) == 0:
        return None
    high = swing_high_price(bars, lookback)
    close = _last(bars["c"])
    if high in (None, 0) or close is None:
        return None
    return min(0.0, (close / high - 1.0) * 100.0)


# ───────────────────────── block ─────────────────────────

def build_volatility_block(
    bars: pd.DataFrame, benchmark: pd.Series | None = None
) -> VolatilityBlock:
    if bars is None or len(bars) == 0:
        return VolatilityBlock()

    c = _as_float(bars["c"])
    bb = bollinger(c, 20, 2.0)

    return VolatilityBlock(
        atr14=_last(atr(bars, 14)),
        atr_pct=atr_pct(bars, 14),
        bb_upper=_last(bb["upper"]),
        bb_lower=_last(bb["lower"]),
        bb_pct_b=_last(bb["pct_b"]),
        bb_width=_last(bb["width"]),
        bb_squeeze=bb_squeeze(bb["width"]),
        realized_vol_20d=realized_vol(c, 20),
        beta_vs_index=beta(c, benchmark),
        drawdown_from_swing_high=drawdown_from_swing_high(bars),
    )
