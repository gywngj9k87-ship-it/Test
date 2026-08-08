"""
The orchestrator: bars in, one IndicatorSet out.

Two hard rules, both from the spec:
  1. RESILIENCE. A short or ragged series returns None fields. `compute_all`
     does not raise for data reasons — a dashboard that 500s because one
     Frankfurt listing has 12 bars of history is worse than one that says
     "not enough data".
  2. AssetClass.PREFERRED gets NO momentum oscillators and NO setup score.
     Per §2b, RSI/MACD on a thin preferred mostly measures the bid-ask spread;
     that sleeve is scored on yield, coverage and rate sensitivity instead.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, TypeVar

import numpy as np
import pandas as pd

from app.models import (
    AssetClass,
    IndicatorSet,
    Instrument,
    LevelsBlock,
    MomentumBlock,
    TrendBlock,
    VolatilityBlock,
    VolumeBlock,
)

from .levels import build_levels_block
from .momentum import build_momentum_block
from .score import build_setup_score
from .trend import build_trend_block
from .volatility import build_volatility_block
from .volume import build_volume_block

__all__ = ["compute_all", "normalise_bars", "REQUIRED_COLUMNS"]

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("o", "h", "l", "c", "v")

T = TypeVar("T")


def normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce input to the house convention: a DataFrame indexed by date with
    float columns o,h,l,c,v, sorted ascending, de-duplicated on the index, and
    with rows missing a close dropped. Missing columns are filled with NaN
    (volume-less index series are a real case) rather than raising.
    """
    if bars is None or not isinstance(bars, pd.DataFrame) or len(bars) == 0:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS), dtype=float)

    df = bars.copy()
    df.columns = [str(c).lower() for c in df.columns]
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[list(REQUIRED_COLUMNS)].astype(float)

    if not isinstance(df.index, (pd.DatetimeIndex, pd.Index)):
        df.index = pd.Index(df.index)
    df = df[~df.index.duplicated(keep="last")]
    try:
        df = df.sort_index()
    except TypeError:                       # unsortable index — leave as given
        pass
    return df.dropna(subset=["c"])


def _safe(what: str, fn: Callable[[], T], fallback: T) -> T:
    """Run a block builder; log and degrade to an empty block on any failure."""
    try:
        return fn()
    except Exception:                       # pragma: no cover - defensive
        log.exception("indicator block %s failed; degrading to empty", what)
        return fallback


def _as_of(df: pd.DataFrame) -> date:
    ts = df.index[-1]
    if isinstance(ts, date) and not isinstance(ts, pd.Timestamp):
        return ts
    try:
        return pd.Timestamp(ts).date()
    except Exception:                       # pragma: no cover - defensive
        return date.today()


def compute_all(
    bars: pd.DataFrame,
    benchmark: pd.Series | None = None,
    sector: pd.Series | None = None,
    instrument: Instrument | None = None,
    earnings_anchor: date | None = None,
) -> IndicatorSet:
    """
    Compute every indicator block for one instrument.

    bars            date-indexed DataFrame with columns o,h,l,c,v
    benchmark       date-indexed close series for the RS/beta baseline (VOO)
    sector          date-indexed close series for the instrument's sector ETF
    instrument      identity; asset_class routes the PREFERRED sleeve
    earnings_anchor last earnings date, the anchor for the anchored VWAP

    Short series come back with None fields; nothing here raises on thin data.
    """
    df = normalise_bars(bars)

    if len(df) == 0:
        return IndicatorSet(
            conid=instrument.conid if instrument else 0,
            symbol=instrument.symbol if instrument else "",
            as_of=date.today(),
            close=float("nan"),
            trend=TrendBlock(),
            momentum=MomentumBlock(gated=True),
            volatility=VolatilityBlock(),
            volume=VolumeBlock(),
            levels=LevelsBlock(),
            score=None,
        )

    close = float(df["c"].iloc[-1])
    change_pct = None
    if len(df) >= 2:
        prev = float(df["c"].iloc[-2])
        if prev != 0 and np.isfinite(prev):
            change_pct = (close / prev - 1.0) * 100.0

    is_preferred = bool(instrument and instrument.asset_class == AssetClass.PREFERRED)

    trend = _safe("trend", lambda: build_trend_block(df), TrendBlock())
    volatility = _safe(
        "volatility", lambda: build_volatility_block(df, benchmark), VolatilityBlock()
    )
    volume = _safe(
        "volume", lambda: build_volume_block(df, earnings_anchor), VolumeBlock()
    )
    levels = _safe("levels", lambda: build_levels_block(df), LevelsBlock())

    if is_preferred:
        # income sleeve: oscillators are false precision here. Emit an empty,
        # explicitly gated momentum block and no score.
        momentum = MomentumBlock(gated=True)
        score = None
    else:
        momentum = _safe(
            "momentum",
            lambda: build_momentum_block(df, benchmark, sector, trend.adx14),
            MomentumBlock(gated=True),
        )
        score = _safe(
            "score",
            lambda: build_setup_score(trend, momentum, volatility, volume, close),
            None,
        )

    return IndicatorSet(
        conid=instrument.conid if instrument else 0,
        symbol=instrument.symbol if instrument else "",
        as_of=_as_of(df),
        close=close,
        change_pct=change_pct,
        trend=trend,
        momentum=momentum,
        volatility=volatility,
        volume=volume,
        levels=levels,
        score=score,
    )
