"""
The indicator engine.

Input convention for every public function: a pandas DataFrame indexed by date
with columns o, h, l, c, v (and benchmark/sector passed as date-indexed close
Series). Pure pandas/numpy — no TA-Lib, no pandas-ta.

Typical use:

    from app.indicators import compute_all
    iset = compute_all(bars, benchmark=voo, sector=xlk,
                       instrument=inst, earnings_anchor=last_earnings)
"""
from __future__ import annotations

from .engine import REQUIRED_COLUMNS, compute_all, normalise_bars
from .levels import (
    build_levels_block,
    cluster_levels,
    gap_pct,
    prior_day,
    support_resistance,
    swing_high_price,
    swing_pivots,
)
from .momentum import (
    build_momentum_block,
    macd,
    macd_cross,
    macd_hist_divergence,
    relative_strength,
    roc,
    rsi,
    rsi_regime,
    stochastic,
)
from .score import build_setup_score, component_weights, verdict_for
from .trend import (
    adx,
    build_trend_block,
    cross_state,
    ema,
    linreg_slope,
    pct_from_52w_high,
    pct_from_52w_low,
    slope20,
    sma,
    true_range,
    wilder_rma,
)
from .volatility import (
    atr,
    atr_pct,
    bb_squeeze,
    beta,
    bollinger,
    build_volatility_block,
    drawdown_from_swing_high,
    percent_b,
    realized_vol,
)
from .volume import (
    anchored_vwap,
    build_volume_block,
    mfi,
    obv,
    obv_divergence,
    obv_trend,
    rel_volume,
)

__all__ = [
    # engine
    "compute_all", "normalise_bars", "REQUIRED_COLUMNS",
    # trend
    "ema", "sma", "wilder_rma", "true_range", "adx", "cross_state",
    "linreg_slope", "slope20", "pct_from_52w_high", "pct_from_52w_low",
    "build_trend_block",
    # momentum
    "rsi", "rsi_regime", "macd", "macd_cross", "macd_hist_divergence",
    "stochastic", "roc", "relative_strength", "build_momentum_block",
    # volatility
    "atr", "atr_pct", "bollinger", "percent_b", "bb_squeeze", "realized_vol",
    "beta", "drawdown_from_swing_high", "build_volatility_block",
    # volume
    "rel_volume", "obv", "obv_trend", "obv_divergence", "anchored_vwap", "mfi",
    "build_volume_block",
    # levels
    "swing_pivots", "swing_high_price", "cluster_levels", "support_resistance",
    "prior_day", "gap_pct", "build_levels_block",
    # score
    "build_setup_score", "verdict_for", "component_weights",
]
