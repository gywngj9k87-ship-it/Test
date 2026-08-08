"""
The Swing Setup Score (0-100).

NEVER A BLACK BOX. Every component is returned with its raw-to-score transform
described in `note`, and `components` is always populated — including when an
input is missing, in which case the component scores a neutral 50 and says so.

Transform rules used throughout:
  * `_lin(x, lo, hi)` maps lo -> 0 and hi -> 100, linearly, clamped to [0,100].
    It is monotonic increasing when hi > lo and monotonic decreasing when
    hi < lo. Every component is built only from `_lin` and fixed-value maps,
    so each component is monotonic in each of its raw inputs by construction.
  * Missing input -> 50 ("no opinion"), never 0, because 0 is a bearish claim.

Weights come from settings (0.30 / 0.25 / 0.20 / 0.15 / 0.10) and are
renormalised defensively so the reported weights always sum to 1.0.

Verdict: >= 75 strong, >= 55 constructive, >= 40 neutral, else weak.
"""
from __future__ import annotations

import math
from typing import Literal

from app.config import settings
from app.models import (
    MomentumBlock,
    ScoreComponent,
    SetupScore,
    TrendBlock,
    VolatilityBlock,
    VolumeBlock,
)

__all__ = ["build_setup_score", "verdict_for", "component_weights"]


def _lin(x: float | None, lo: float, hi: float) -> float | None:
    """Clamped linear map: lo -> 0, hi -> 100. Monotonic in x."""
    if x is None or not math.isfinite(x) or lo == hi:
        return None
    return max(0.0, min(100.0, (x - lo) / (hi - lo) * 100.0))


def _blend(parts: list[tuple[float | None, float]]) -> float | None:
    """Weighted mean of the sub-scores that exist. None when none exist."""
    live = [(v, w) for v, w in parts if v is not None and w > 0]
    if not live:
        return None
    total_w = sum(w for _, w in live)
    return sum(v * w for v, w in live) / total_w


def component_weights() -> dict[str, float]:
    """The five weights from settings, renormalised to sum to exactly 1.0."""
    raw = {
        "relative_strength": settings.w_relative_strength,
        "trend": settings.w_trend,
        "momentum": settings.w_momentum,
        "volume": settings.w_volume,
        "volatility": settings.w_volatility,
    }
    total = sum(raw.values())
    if total <= 0:
        n = len(raw)
        return {k: 1.0 / n for k in raw}
    return {k: v / total for k, v in raw.items()}


def verdict_for(total: float) -> Literal["strong", "constructive", "neutral", "weak"]:
    if total >= 75.0:
        return "strong"
    if total >= 55.0:
        return "constructive"
    if total >= 40.0:
        return "neutral"
    return "weak"


# ───────────────────────── components ─────────────────────────

def _relative_strength(m: MomentumBlock) -> tuple[float, str]:
    """
    Excess return vs the index and vs the sector, in percentage points.
    -20pp -> 0, 0pp -> 50, +20pp -> 100 (clamped).
    13w vs index carries 60%, 13w vs sector 25%, 4w vs index 15%; a stock
    beating a sector that is beating the market is the setup we want to rank
    highest, so the sector leg is explicit rather than folded in.
    """
    idx13 = _lin(m.rs_vs_index_13w, -20.0, 20.0)
    sec13 = _lin(m.rs_vs_sector_13w, -20.0, 20.0)
    idx4 = _lin(m.rs_vs_index_4w, -12.0, 12.0)
    val = _blend([(idx13, 0.60), (sec13, 0.25), (idx4, 0.15)])
    if val is None:
        return 50.0, "no benchmark series available — neutral 50"
    return val, (
        "excess return vs index/sector: -20pp->0, 0pp->50, +20pp->100 "
        f"(13w idx {_fmt(m.rs_vs_index_13w)}pp, 13w sector {_fmt(m.rs_vs_sector_13w)}pp, "
        f"4w idx {_fmt(m.rs_vs_index_4w)}pp)"
    )


def _trend(t: TrendBlock, close: float | None) -> tuple[float, str]:
    """
    Three legs, equally weighted at 40/30/30:
      alignment  25 points each for close>EMA20, EMA20>EMA50, EMA50>EMA200,
                 close>EMA200 (a step function, monotonic in each condition)
      ADX        10 -> 0, 40 -> 100
      slope20    normalised to % of price per bar: -0.5%/bar -> 0, +0.5% -> 100
    """
    conds = []
    if close is not None and t.ema20 is not None:
        conds.append(close > t.ema20)
    if t.ema20 is not None and t.ema50 is not None:
        conds.append(t.ema20 > t.ema50)
    if t.ema50 is not None and t.ema200 is not None:
        conds.append(t.ema50 > t.ema200)
    if close is not None and t.ema200 is not None:
        conds.append(close > t.ema200)
    align = (sum(1 for x in conds if x) / len(conds) * 100.0) if conds else None

    adx_s = _lin(t.adx14, 10.0, 40.0)

    slope_pct = None
    if t.slope20 is not None and close not in (None, 0):
        slope_pct = t.slope20 / close * 100.0
    slope_s = _lin(slope_pct, -0.5, 0.5)

    val = _blend([(align, 0.40), (adx_s, 0.30), (slope_s, 0.30)])
    if val is None:
        return 50.0, "insufficient history for EMAs/ADX/slope — neutral 50"
    return val, (
        f"EMA alignment {_fmt(align)}/100 (w.40), ADX 10->0/40->100 "
        f"[{_fmt(t.adx14)}] (w.30), 20d slope +/-0.5%/bar [{_fmt(slope_pct)}%/bar] (w.30)"
    )


def _momentum(m: MomentumBlock, close: float | None) -> tuple[float, str]:
    """
    RSI 30->0 / 70->100 (w .40), MACD histogram as % of price -1%->0 / +1%->100
    (w .30), 20d ROC -15%->0 / +15%->100 (w .30).

    RSI is mapped monotonically on purpose: an overbought reading is NOT
    penalised here. Swing entries are timed with the stochastic and the levels
    block, not by punishing strength in the composite.

    Gating: when MomentumBlock.gated is True (ADX below settings.adx_gate) the
    component is shrunk halfway toward 50, so a strong oscillator in a
    directionless tape cannot carry the score. This is an affine map, so the
    component stays monotonic.
    """
    rsi_s = _lin(m.rsi14, 30.0, 70.0)
    hist_pct = None
    if m.macd_hist is not None and close not in (None, 0):
        hist_pct = m.macd_hist / close * 100.0
    macd_s = _lin(hist_pct, -1.0, 1.0)
    roc_s = _lin(m.roc20, -15.0, 15.0)

    val = _blend([(rsi_s, 0.40), (macd_s, 0.30), (roc_s, 0.30)])
    if val is None:
        return 50.0, "insufficient history for RSI/MACD/ROC — neutral 50"
    note = (
        f"RSI 30->0/70->100 [{_fmt(m.rsi14)}] (w.40), MACD hist +/-1% of price "
        f"[{_fmt(hist_pct)}%] (w.30), ROC20 +/-15% [{_fmt(m.roc20)}%] (w.30)"
    )
    if m.gated:
        val = 50.0 + (val - 50.0) * 0.5
        note += f"; GATED (ADX < {settings.adx_gate}) — shrunk 50% toward neutral"
    return val, note


def _volume(v: VolumeBlock) -> tuple[float, str]:
    """
    Relative volume on a log2 scale (0.5x -> 0, 1x -> 50, 2x -> 100) at w .65,
    OBV trend (up 100 / flat 50 / down 0) at w .35. Log2 because volume is
    multiplicative: 2x and 0.5x should sit equally far from normal.
    A confirmed OBV/price divergence caps the component at 50.
    """
    rv_s = None
    if v.rel_volume is not None and v.rel_volume > 0:
        rv_s = _lin(math.log2(v.rel_volume), -1.0, 1.0)
    obv_s = {"up": 100.0, "flat": 50.0, "down": 0.0}.get(v.obv_trend or "", None)

    val = _blend([(rv_s, 0.65), (obv_s, 0.35)])
    if val is None:
        return 50.0, "no volume history — neutral 50"
    note = (
        f"rel volume log2 0.5x->0/1x->50/2x->100 [{_fmt(v.rel_volume)}x] (w.65), "
        f"OBV trend [{v.obv_trend}] (w.35)"
    )
    if v.obv_divergence:
        val = min(val, 50.0)
        note += "; OBV/price divergence — capped at 50"
    return val, note


def _volatility(vol: VolatilityBlock) -> tuple[float, str]:
    """
    Risk headroom, not "more vol is better":
      ATR%      8% -> 0, 1.5% -> 100 (monotonic DECREASING in ATR%: a wide
                average range means a wider stop and a smaller position)
      drawdown  -25% from the last swing high -> 0, 0% -> 100
    Equally weighted. A Bollinger squeeze is reported in the note but does not
    move the number: compression is a setup precondition, not an edge on its own.
    """
    atr_s = _lin(vol.atr_pct, 8.0, 1.5)
    dd_s = _lin(vol.drawdown_from_swing_high, -25.0, 0.0)
    val = _blend([(atr_s, 0.5), (dd_s, 0.5)])
    if val is None:
        return 50.0, "insufficient history for ATR/drawdown — neutral 50"
    note = (
        f"ATR% 8%->0/1.5%->100 [{_fmt(vol.atr_pct)}%] (w.50), drawdown from swing "
        f"high -25%->0/0%->100 [{_fmt(vol.drawdown_from_swing_high)}%] (w.50)"
    )
    if vol.bb_squeeze:
        note += "; Bollinger squeeze active (context only, unscored)"
    return val, note


# ───────────────────────── assembly ─────────────────────────

def build_setup_score(
    trend: TrendBlock,
    momentum: MomentumBlock,
    volatility: VolatilityBlock,
    volume: VolumeBlock,
    close: float | None = None,
) -> SetupScore:
    """Build the SetupScore. `components` is ALWAYS five entries long."""
    w = component_weights()
    specs = [
        ("Relative strength", w["relative_strength"], _relative_strength(momentum)),
        ("Trend", w["trend"], _trend(trend, close)),
        ("Momentum", w["momentum"], _momentum(momentum, close)),
        ("Volume", w["volume"], _volume(volume)),
        ("Volatility", w["volatility"], _volatility(volatility)),
    ]
    components = [
        ScoreComponent(name=name, value=round(max(0.0, min(100.0, val)), 2),
                       weight=round(weight, 6), note=note)
        for name, weight, (val, note) in specs
    ]
    total = sum(c.value * c.weight for c in components)
    total = round(max(0.0, min(100.0, total)), 2)
    return SetupScore(total=total, components=components, verdict=verdict_for(total))


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"
