"""
Volume & flow — "is the move confirmed".
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from app.models import VolumeBlock

from .trend import _as_float, _last, linreg_slope

__all__ = [
    "rel_volume",
    "obv",
    "obv_trend",
    "obv_divergence",
    "anchored_vwap",
    "mfi",
    "build_volume_block",
]

OBV_WINDOW = 20
OBV_FLAT_BAND = 0.10        # |normalised slope| below this reads as flat


def rel_volume(bars: pd.DataFrame, n: int = 20) -> float | None:
    """
    Today's volume divided by the mean of the PREVIOUS n sessions.

    Judgement call: the baseline excludes today. Including it would let a 5x
    volume day inflate its own denominator and understate itself by ~20%.
    """
    if bars is None or len(bars) < n + 1:
        return None
    v = _as_float(bars["v"])
    base = float(v.iloc[-(n + 1) : -1].mean())
    today = float(v.iloc[-1])
    if base <= 0 or not np.isfinite(base):
        return None
    return today / base


def obv(bars: pd.DataFrame) -> pd.Series:
    """
    On-balance volume. +volume on an up close, -volume on a down close, 0 on
    an unchanged close, cumulated from the first bar (level is arbitrary; only
    its direction carries information).
    """
    if bars is None or len(bars) == 0:
        return pd.Series(dtype=float)
    c = _as_float(bars["c"])
    v = _as_float(bars["v"])
    direction = np.sign(c.diff().fillna(0.0))
    return (direction * v).fillna(0.0).cumsum()


def obv_trend(
    obv_series: pd.Series, bars: pd.DataFrame, n: int = OBV_WINDOW
) -> Literal["up", "down", "flat"] | None:
    """
    Classify the OBV slope over the last n bars.

    The raw slope is in shares/bar, which is meaningless on its own, so it is
    normalised by the mean daily volume of the same window:
        norm = slope_per_bar / mean_volume
    |norm| < 0.10 (i.e. accumulating less than a tenth of a day's volume per
    day) reads as flat; positive is up, negative is down.
    """
    o = pd.Series(obv_series, dtype=float).dropna()
    if len(o) < n or bars is None or len(bars) < n:
        return None
    slope = linreg_slope(o, n)
    mean_vol = float(_as_float(bars["v"]).iloc[-n:].mean())
    if slope is None or mean_vol <= 0:
        return None
    norm = slope / mean_vol
    if abs(norm) < OBV_FLAT_BAND:
        return "flat"
    return "up" if norm > 0 else "down"


def obv_divergence(
    obv_series: pd.Series, bars: pd.DataFrame, n: int = OBV_WINDOW
) -> bool | None:
    """
    True when price and OBV disagree in direction over the last n bars: price
    up while OBV falls (distribution into strength), or price down while OBV
    rises (accumulation into weakness). Both are measured as normalised
    regression slopes, so a flat leg on either side is not a divergence.
    """
    o = pd.Series(obv_series, dtype=float).dropna()
    if len(o) < n or bars is None or len(bars) < n:
        return None
    c = _as_float(bars["c"])
    p_slope = linreg_slope(c, n)
    o_slope = linreg_slope(o, n)
    mean_price = float(c.iloc[-n:].mean())
    mean_vol = float(_as_float(bars["v"]).iloc[-n:].mean())
    if None in (p_slope, o_slope) or mean_price <= 0 or mean_vol <= 0:
        return None
    p_norm = p_slope / mean_price          # fraction of price per bar
    o_norm = o_slope / mean_vol            # fraction of a day's volume per bar
    if abs(p_norm) < 0.001 or abs(o_norm) < OBV_FLAT_BAND:
        return False
    return bool(np.sign(p_norm) != np.sign(o_norm))


def anchored_vwap(bars: pd.DataFrame, anchor: date | None) -> float | None:
    """
    Volume-weighted average price anchored at `anchor` (we anchor on the last
    earnings date — the level institutions actually reference).

        typical = (h + l + c) / 3
        avwap   = cumsum(typical * v) / cumsum(v),  from the anchor forward

    Returns the latest value. None when the anchor is missing, is after the
    last bar, or the anchored window has no volume.
    """
    if bars is None or len(bars) == 0 or anchor is None:
        return None
    idx = pd.to_datetime(pd.Index(bars.index))
    mask = idx >= pd.Timestamp(anchor)
    window = bars.loc[mask]
    if len(window) == 0:
        return None
    typical = (_as_float(window["h"]) + _as_float(window["l"]) + _as_float(window["c"])) / 3.0
    v = _as_float(window["v"])
    total_v = float(v.sum())
    if total_v <= 0 or not np.isfinite(total_v):
        return None
    return float((typical * v).sum() / total_v)


def mfi(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """
    Money Flow Index(14) — "volume-weighted RSI".

        typical    = (h + l + c) / 3
        raw flow   = typical * volume, signed by the change in typical price
        MFI        = 100 - 100 / (1 + positive_flow_n / negative_flow_n)

    Judgement call: the pos/neg flows are SIMPLE rolling sums over n, which is
    the standard MFI definition, not Wilder-smoothed like RSI. Zero negative
    flow gives 100.
    """
    idx = getattr(bars, "index", None)
    if bars is None or len(bars) < n + 1:
        return pd.Series(np.nan, index=idx, dtype=float)
    typical = (_as_float(bars["h"]) + _as_float(bars["l"]) + _as_float(bars["c"])) / 3.0
    flow = typical * _as_float(bars["v"])
    delta = typical.diff()
    pos = flow.where(delta > 0, 0.0)
    neg = flow.where(delta < 0, 0.0)
    pos_n = pos.rolling(n, min_periods=n).sum()
    neg_n = neg.rolling(n, min_periods=n).sum()
    ratio = pos_n / neg_n.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + ratio)
    return out.where(~((neg_n == 0.0) & pos_n.notna()), 100.0)


def build_volume_block(
    bars: pd.DataFrame, earnings_anchor: date | None = None
) -> VolumeBlock:
    if bars is None or len(bars) == 0:
        return VolumeBlock()
    o = obv(bars)
    return VolumeBlock(
        rel_volume=rel_volume(bars, 20),
        obv=_last(o),
        obv_trend=obv_trend(o, bars),
        obv_divergence=obv_divergence(o, bars),
        anchored_vwap_earnings=anchored_vwap(bars, earnings_anchor),
        mfi14=_last(mfi(bars, 14)),
    )
