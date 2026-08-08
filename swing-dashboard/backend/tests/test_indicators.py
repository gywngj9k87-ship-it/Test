"""
Tests for the indicator engine.

These verify the ARITHMETIC, not merely that the code runs. Where a published
worked example exists (Wilder's RSI) the expected values are hard-coded and
also re-derived by an independent plain-Python loop written from the formula,
so a bug in the pandas implementation cannot be masked by reusing it.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.indicators import (
    adx,
    anchored_vwap,
    atr,
    beta,
    bollinger,
    build_momentum_block,
    build_setup_score,
    build_trend_block,
    build_volatility_block,
    build_volume_block,
    cluster_levels,
    compute_all,
    component_weights,
    cross_state,
    ema,
    macd,
    mfi,
    percent_b,
    rel_volume,
    relative_strength,
    rsi,
    stochastic,
    swing_pivots,
    verdict_for,
)
from app.models import AssetClass, IndicatorSet, Instrument

# ─────────────────────────── fixtures ───────────────────────────

# Wilder's classic RSI worked example (the 33-close series reproduced in every
# textbook treatment of RSI).
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
    46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
    43.42, 42.66, 43.13,
]


def _dates(n: int, start: date = date(2024, 1, 1)) -> pd.DatetimeIndex:
    """n consecutive business days."""
    return pd.bdate_range(start=pd.Timestamp(start), periods=n)


def make_bars(closes, spread: float = 1.0, volume: float = 1_000_000.0) -> pd.DataFrame:
    """
    Wrap a close series into o,h,l,c,v bars with a deterministic range.
    The high/low are derived from the close alone so that two adjacent bars
    never share an exact high (which would suppress fractal pivot detection
    as a fixture artefact rather than a real one).
    """
    c = pd.Series([float(x) for x in closes])
    h = c + spread / 2.0
    l = c - spread / 2.0
    o = c.shift(1).fillna(c.iloc[0]).clip(lower=l, upper=h)
    v = pd.Series([volume] * len(c))
    df = pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "v": v})
    df.index = _dates(len(c))
    return df


@pytest.fixture
def trending_bars() -> pd.DataFrame:
    """400 bars of a noisy uptrend — enough history for every indicator."""
    rng = np.random.default_rng(20260808)
    steps = rng.normal(loc=0.0012, scale=0.012, size=400)
    closes = 100.0 * np.exp(np.cumsum(steps))
    df = make_bars(closes, spread=1.2)
    df["v"] = 1_000_000 * (1.0 + rng.normal(0, 0.15, size=400)).clip(0.3, None)
    return df


@pytest.fixture
def choppy_bars() -> pd.DataFrame:
    """A directionless saw-tooth: ADX stays well under the 20 gate."""
    closes = [100.0 + (1.0 if i % 2 == 0 else -1.0) * 0.4 for i in range(120)]
    return make_bars(closes, spread=0.3)


# ─────────────────────── RSI: Wilder reference ───────────────────────

def _rsi_reference(closes: list[float], n: int = 14) -> list[float]:
    """
    Independent plain-Python RSI, written straight from Wilder's definition.
    Deliberately does NOT touch the app code.
    """
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        d = cur - prev
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    out = []
    rs = float("inf") if avg_l == 0 else avg_g / avg_l
    out.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + rs))
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        rs = float("inf") if avg_l == 0 else avg_g / avg_l
        out.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + rs))
    return out


def test_rsi_matches_wilder_worked_example():
    """
    First print, computed by hand from the first 14 changes:
        gains  0.06 0.72 0.50 0.27 0.32 0.42 0.24 0.14 0.67  -> sum 3.34
        losses 0.25 0.54 0.19 0.42                           -> sum 1.40
        avg gain 3.34/14 = 0.238571 ; avg loss 1.40/14 = 0.100000
        RS = 2.385714 ; RSI = 100 - 100/(1+RS) = 70.46
    Then Wilder smoothing carries the series forward.
    """
    expected = [
        70.46, 66.25, 66.48, 69.35, 66.29, 57.92, 62.88, 63.21, 56.01, 62.34,
        54.67, 50.39, 40.02, 41.49, 41.90, 45.50, 37.32, 33.09, 37.79,
    ]
    got = rsi(pd.Series(WILDER_CLOSES), 14).dropna()

    # the first print lands on bar 14 (0-based), i.e. the 15th close
    assert got.index[0] == 14
    assert len(got) == len(expected)
    for i, (g, e) in enumerate(zip(got.tolist(), expected)):
        assert round(g, 2) == pytest.approx(e, abs=0.005), f"RSI[{i}] {g} != {e}"

    # and against the independent reference implementation
    ref = _rsi_reference(WILDER_CLOSES, 14)
    assert got.tolist() == pytest.approx(ref, abs=1e-9)


def test_rsi_hand_arithmetic_of_first_value():
    avg_gain = (0.06 + 0.72 + 0.50 + 0.27 + 0.32 + 0.42 + 0.24 + 0.14 + 0.67) / 14
    avg_loss = (0.25 + 0.54 + 0.19 + 0.42) / 14
    expected = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    first = float(rsi(pd.Series(WILDER_CLOSES), 14).dropna().iloc[0])
    assert round(first, 2) == round(expected, 2) == 70.46


def test_rsi_all_up_closes_is_100():
    s = pd.Series([100 + i for i in range(30)], dtype=float)
    assert float(rsi(s, 14).dropna().iloc[-1]) == pytest.approx(100.0)


# ─────────────────────── EMA: hand-computed ───────────────────────

def test_ema_5_period_hand_computed():
    """
    alpha = 2/(5+1) = 1/3, seeded on the first observation.
        e1 = 10
        e2 = 10 + (1/3)(12-10)     = 10.666666...
        e3 = 10.666667 + (1/3)(14 - 10.666667) = 11.777777...
        e4 = 11.777778 + (1/3)(16 - 11.777778) = 13.185185...
        e5 = 13.185185 + (1/3)(18 - 13.185185) = 14.790123...
        e6 = 14.790123 + (1/3)(20 - 14.790123) = 16.526748...
    """
    prices = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
    expected = [
        10.0,
        10.0 + (12.0 - 10.0) / 3.0,
        11.0 + 7.0 / 9.0,
        13.0 + 5.0 / 27.0,
        14.0 + 64.0 / 81.0,
        16.0 + 128.0 / 243.0,
    ]
    got = ema(prices, 5).tolist()
    assert got == pytest.approx(expected, abs=1e-9)
    assert round(got[-1], 6) == pytest.approx(16.526749, abs=1e-6)


def test_ema_of_a_constant_series_is_that_constant():
    s = pd.Series([7.0] * 50)
    assert ema(s, 20).tolist() == pytest.approx([7.0] * 50)


# ─────────────────────── ATR: hand-computed ───────────────────────

def test_atr_hand_computed_3_period():
    """
    Bars (h, l, c):
        1: 10.0  9.0   9.5   -> no prior close, TR undefined
        2: 10.5  9.5  10.0   TR = max(1.00, |10.5-9.5|, |9.5-9.5|)  = 1.00
        3: 11.0  9.8  10.8   TR = max(1.20, |11.0-10.0|, |9.8-10.0|)= 1.20
        4: 12.0 10.5  11.5   TR = max(1.50, |12.0-10.8|, |10.5-10.8|)=1.50
        5: 11.8 10.0  10.2   TR = max(1.80, |11.8-11.5|, |10.0-11.5|)=1.80
        6: 10.6  9.4   9.6   TR = max(1.20, |10.6-10.2|, | 9.4-10.2|)=1.20
    ATR(3) seed = mean(1.00, 1.20, 1.50) = 1.2333333
       bar 5    = (1.2333333*2 + 1.80)/3 = 1.4222222
       bar 6    = (1.4222222*2 + 1.20)/3 = 1.3481481
    """
    df = pd.DataFrame(
        {
            "o": [9.2, 9.6, 10.1, 10.9, 11.6, 10.3],
            "h": [10.0, 10.5, 11.0, 12.0, 11.8, 10.6],
            "l": [9.0, 9.5, 9.8, 10.5, 10.0, 9.4],
            "c": [9.5, 10.0, 10.8, 11.5, 10.2, 9.6],
            "v": [1e6] * 6,
        },
        index=_dates(6),
    )
    got = atr(df, 3)
    assert np.isnan(got.iloc[2])                      # seed needs 3 true ranges
    assert float(got.iloc[3]) == pytest.approx((1.00 + 1.20 + 1.50) / 3.0, abs=1e-9)
    assert float(got.iloc[4]) == pytest.approx(1.4222222222, abs=1e-9)
    assert float(got.iloc[5]) == pytest.approx(1.3481481481, abs=1e-9)


def test_atr_true_range_uses_prior_close_gaps():
    """A gap down makes |low - prior close| the binding leg, not high-low."""
    df = pd.DataFrame(
        {
            "o": [10.0, 5.0, 5.0, 5.0],
            "h": [10.0, 6.0, 6.0, 6.0],
            "l": [9.0, 5.0, 5.0, 5.0],
            "c": [10.0, 5.5, 5.5, 5.5],
            "v": [1e6] * 4,
        },
        index=_dates(4),
    )
    # bar 2 TR = max(1.0, |6-10|, |5-10|) = 5.0 ; seed over bars 2..4 with n=3
    assert float(atr(df, 3).iloc[3]) == pytest.approx((5.0 + 1.0 + 1.0) / 3.0)


# ─────────────────────── MACD identities ───────────────────────

def test_macd_histogram_and_signal_identities(trending_bars):
    c = trending_bars["c"]
    m = macd(c, 12, 26, 9)

    # macd line == ema12 - ema26
    assert m["macd"].tolist() == pytest.approx(
        (ema(c, 12) - ema(c, 26)).tolist(), abs=1e-12
    )
    # signal == ema9 of the macd line
    assert m["signal"].tolist() == pytest.approx(ema(m["macd"], 9).tolist(), abs=1e-12)
    # hist == macd - signal, everywhere
    assert m["hist"].tolist() == pytest.approx(
        (m["macd"] - m["signal"]).tolist(), abs=1e-12
    )


def test_macd_cross_flag_detects_a_sign_change(trending_bars):
    from app.indicators import macd_cross

    m = macd(trending_bars["c"])
    flag = macd_cross(m)
    assert flag in {"bullish", "bearish", "none"}

    # force a bullish flip on the final bar
    forced = m.copy()
    forced.iloc[-2, forced.columns.get_loc("hist")] = -0.5
    forced.iloc[-1, forced.columns.get_loc("hist")] = 0.5
    assert macd_cross(forced) == "bullish"
    forced.iloc[-2, forced.columns.get_loc("hist")] = 0.5
    forced.iloc[-1, forced.columns.get_loc("hist")] = -0.5
    assert macd_cross(forced) == "bearish"


# ─────────────────────── Bollinger ───────────────────────

BB_BASE = [
    100.0, 101.0, 99.0, 102.0, 98.0, 103.0, 97.0, 104.0, 96.0, 105.0,
    100.5, 101.5, 99.5, 102.5, 98.5, 103.5, 97.5, 104.5, 96.5,
]  # 19 values; the 20th is the one under test


def _bb_last(x: float) -> pd.Series:
    return bollinger(pd.Series(BB_BASE + [x]), 20, 2.0).iloc[-1]


def test_percent_b_pure_function():
    assert percent_b(105.0, 110.0, 100.0) == pytest.approx(0.5)   # middle band
    assert percent_b(110.0, 110.0, 100.0) == pytest.approx(1.0)   # upper band
    assert percent_b(100.0, 110.0, 100.0) == pytest.approx(0.0)   # lower band
    assert percent_b(100.0, 100.0, 100.0) is None                 # degenerate


def test_bollinger_pct_b_is_half_at_the_middle_band():
    """
    If the last close equals the mean of the preceding 19, the 20-bar mean is
    that same value (20m = 19m + m), so price sits exactly on the mid band
    and %B must be 0.5.
    """
    x = float(np.mean(BB_BASE))
    row = _bb_last(x)
    assert float(row["mid"]) == pytest.approx(x, abs=1e-9)
    assert float(row["pct_b"]) == pytest.approx(0.5, abs=1e-9)
    assert float(row["upper"]) > float(row["mid"]) > float(row["lower"])


def test_bollinger_pct_b_is_one_at_the_upper_band():
    """
    Solve for the close that sits exactly on its own upper band (both bands
    depend on the close, so it is a fixed point) by bisection, then assert %B.
    """
    f = lambda x: float(_bb_last(x)["upper"]) - x
    lo, hi = float(np.mean(BB_BASE)), 10_000.0
    assert f(lo) > 0 and f(hi) < 0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    x = (lo + hi) / 2.0
    row = _bb_last(x)
    assert float(row["upper"]) == pytest.approx(x, abs=1e-6)
    assert float(row["pct_b"]) == pytest.approx(1.0, abs=1e-6)


def test_bollinger_bands_are_two_population_sigma_wide():
    s = pd.Series(BB_BASE + [100.0])
    row = bollinger(s, 20, 2.0).iloc[-1]
    window = s.iloc[-20:]
    assert float(row["mid"]) == pytest.approx(window.mean())
    assert float(row["upper"] - row["mid"]) == pytest.approx(2 * window.std(ddof=0))


# ─────────────────────── beta & relative strength ───────────────────────

def test_beta_of_a_series_against_itself_is_one(trending_bars):
    c = trending_bars["c"]
    assert beta(c, c) == pytest.approx(1.0, abs=1e-12)


def test_beta_of_a_doubled_return_series_is_two(trending_bars):
    bench = trending_bars["c"]
    r = bench.pct_change().fillna(0.0)
    levered = 100.0 * (1.0 + 2.0 * r).cumprod()
    assert beta(levered, bench) == pytest.approx(2.0, abs=1e-9)


def test_relative_strength_against_itself_is_zero(trending_bars):
    c = trending_bars["c"]
    assert relative_strength(c, c, 20) == pytest.approx(0.0, abs=1e-12)
    assert relative_strength(c, c, 65) == pytest.approx(0.0, abs=1e-12)


def test_relative_strength_is_excess_return_in_percentage_points():
    idx = _dates(30)
    asset = pd.Series(np.linspace(100.0, 130.0, 30), index=idx)      # +30% end to end
    bench = pd.Series(np.linspace(100.0, 110.0, 30), index=idx)      # +10% end to end
    n = 29
    expected = (asset.iloc[-1] / asset.iloc[0] - 1) * 100 - (
        bench.iloc[-1] / bench.iloc[0] - 1
    ) * 100
    assert relative_strength(asset, bench, n) == pytest.approx(expected, abs=1e-9)
    assert relative_strength(asset, bench, n) == pytest.approx(20.0, abs=1e-9)


def test_relative_strength_returns_none_without_a_benchmark(trending_bars):
    assert relative_strength(trending_bars["c"], None, 20) is None


# ─────────────────────── setup score ───────────────────────

def test_score_weights_sum_to_one_and_total_is_bounded(trending_bars):
    iset = compute_all(trending_bars, benchmark=trending_bars["c"] * 0.5)
    score = iset.score
    assert score is not None
    assert len(score.components) == 5
    assert sum(c.weight for c in score.components) == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= score.total <= 100.0
    assert all(0.0 <= c.value <= 100.0 for c in score.components)
    assert all(c.note for c in score.components)          # never a black box
    # total is exactly the weighted sum of the components it shows
    assert score.total == pytest.approx(
        sum(c.value * c.weight for c in score.components), abs=0.01
    )


def test_score_weights_match_settings():
    w = component_weights()
    assert w["relative_strength"] == pytest.approx(settings.w_relative_strength)
    assert w["trend"] == pytest.approx(settings.w_trend)
    assert w["momentum"] == pytest.approx(settings.w_momentum)
    assert w["volume"] == pytest.approx(settings.w_volume)
    assert w["volatility"] == pytest.approx(settings.w_volatility)
    assert sum(w.values()) == pytest.approx(1.0)


def test_score_components_always_populated_even_with_no_data():
    from app.models import MomentumBlock, TrendBlock, VolatilityBlock, VolumeBlock

    s = build_setup_score(TrendBlock(), MomentumBlock(), VolatilityBlock(), VolumeBlock())
    assert len(s.components) == 5
    assert all(c.value == 50.0 for c in s.components)     # neutral, not zero
    assert s.total == pytest.approx(50.0)
    assert s.verdict == "neutral"


def test_score_is_monotonic_in_relative_strength():
    from app.models import MomentumBlock, TrendBlock, VolatilityBlock, VolumeBlock

    totals = []
    for rs in (-30.0, -10.0, 0.0, 10.0, 30.0):
        m = MomentumBlock(rs_vs_index_13w=rs, rs_vs_index_4w=rs, rs_vs_sector_13w=rs)
        totals.append(
            build_setup_score(TrendBlock(), m, VolatilityBlock(), VolumeBlock()).total
        )
    assert totals == sorted(totals)
    assert totals[0] < totals[-1]


def test_verdict_thresholds():
    assert verdict_for(100.0) == "strong"
    assert verdict_for(75.0) == "strong"
    assert verdict_for(74.99) == "constructive"
    assert verdict_for(55.0) == "constructive"
    assert verdict_for(54.99) == "neutral"
    assert verdict_for(40.0) == "neutral"
    assert verdict_for(39.99) == "weak"
    assert verdict_for(0.0) == "weak"


# ─────────────────────── graceful degradation ───────────────────────

def test_five_bars_returns_an_indicator_set_with_none_fields():
    bars = make_bars([100.0, 101.0, 102.0, 101.5, 103.0])
    inst = Instrument(conid=1, symbol="TINY", exchange="ARCA")

    iset = compute_all(bars, benchmark=None, sector=None, instrument=inst)

    assert isinstance(iset, IndicatorSet)
    assert iset.close == pytest.approx(103.0)
    assert iset.conid == 1 and iset.symbol == "TINY"

    # trend
    assert iset.trend.ema20 is None
    assert iset.trend.ema50 is None
    assert iset.trend.ema200 is None
    assert iset.trend.adx14 is None
    assert iset.trend.slope20 is None
    assert iset.trend.pct_from_52w_high is None
    # momentum
    assert iset.momentum.rsi14 is None
    assert iset.momentum.stoch_k is None
    assert iset.momentum.rs_vs_index_4w is None
    # volatility
    assert iset.volatility.atr14 is None
    assert iset.volatility.bb_upper is None
    assert iset.volatility.bb_squeeze is None
    assert iset.volatility.beta_vs_index is None
    # volume
    assert iset.volume.rel_volume is None
    assert iset.volume.mfi14 is None
    assert iset.volume.anchored_vwap_earnings is None
    # levels still work — prior day needs only two bars
    assert iset.levels.prior_close == pytest.approx(101.5)
    assert iset.levels.support == [] and iset.levels.resistance == []


def test_empty_and_single_bar_inputs_do_not_raise():
    empty = pd.DataFrame(columns=["o", "h", "l", "c", "v"], dtype=float)
    iset = compute_all(empty)
    assert isinstance(iset, IndicatorSet)
    assert iset.trend.ema20 is None

    one = make_bars([50.0])
    iset = compute_all(one)
    assert iset.close == pytest.approx(50.0)
    assert iset.change_pct is None


def test_ragged_input_is_normalised_not_rejected():
    """Unsorted index, duplicate dates, a missing volume column."""
    idx = list(_dates(6))
    df = pd.DataFrame(
        {"O": [1, 2, 3, 4, 5, 6], "H": [2, 3, 4, 5, 6, 7],
         "L": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5], "C": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]},
        index=[idx[3], idx[1], idx[0], idx[2], idx[4], idx[4]],
        dtype=float,
    )
    iset = compute_all(df)
    assert isinstance(iset, IndicatorSet)
    assert iset.close == pytest.approx(6.5)


# ─────────────────────── ADX gating ───────────────────────

def test_momentum_is_gated_when_adx_is_below_the_gate(choppy_bars):
    assert settings.adx_gate == 20.0
    trend = build_trend_block(choppy_bars)
    assert trend.adx14 is not None
    assert trend.adx14 < 20.0
    assert trend.trend_strong is False

    mom = build_momentum_block(choppy_bars, adx14=trend.adx14)
    assert mom.gated is True

    iset = compute_all(choppy_bars)
    assert iset.momentum.gated is True


def test_gating_boundary_and_unknown_adx(trending_bars):
    assert build_momentum_block(trending_bars, adx14=19.99).gated is True
    assert build_momentum_block(trending_bars, adx14=20.0).gated is False
    assert build_momentum_block(trending_bars, adx14=35.0).gated is False
    # unknown ADX gates too: we never present an oscillator as tradable
    # without having established that a trend exists
    assert build_momentum_block(trending_bars, adx14=None).gated is True


def test_strong_trend_is_not_gated():
    closes = [100.0 * (1.02 ** i) for i in range(80)]     # relentless uptrend
    bars = make_bars(closes, spread=0.5)
    trend = build_trend_block(bars)
    assert trend.adx14 > 20.0
    assert trend.trend_strong is True
    assert build_momentum_block(bars, adx14=trend.adx14).gated is False


def test_adx_is_bounded_and_directional_indices_agree(trending_bars):
    frame = adx(trending_bars, 14)
    last = frame.dropna().iloc[-1]
    assert 0.0 <= last["adx"] <= 100.0
    assert 0.0 <= last["plus_di"] <= 100.0
    assert 0.0 <= last["minus_di"] <= 100.0
    expected_dx = 100.0 * abs(last["plus_di"] - last["minus_di"]) / (
        last["plus_di"] + last["minus_di"]
    )
    assert last["dx"] == pytest.approx(expected_dx, abs=1e-9)
    # first ADX print lands on bar 2n-1
    assert frame["adx"].notna().argmax() == 27


# ─────────────────────── other blocks ───────────────────────

def test_golden_and_death_cross_state_and_days_since():
    fast = pd.Series([1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=float)
    slow = pd.Series([3, 3, 3, 3, 3, 3, 3, 3, 3], dtype=float)
    golden, days = cross_state(fast, slow)
    # fast crosses below slow at position 6 (value 3 -> below at 2 on pos 7)
    assert golden is False
    assert days == 1
    up_golden, up_days = cross_state(pd.Series([1.0, 2.0, 4.0]), pd.Series([3.0] * 3))
    assert up_golden is True and up_days == 0
    assert cross_state(pd.Series([1.0, 1.0]), pd.Series([2.0, 2.0])) == (False, None)


def test_stochastic_is_zero_at_the_low_and_hundred_at_the_high():
    closes = [10.0] * 20
    df = make_bars(closes, spread=2.0)
    df.loc[df.index[-3:], "c"] = df.loc[df.index[-3:], "h"]   # close on the highs
    st = stochastic(df)
    assert float(st["k"].iloc[-1]) == pytest.approx(100.0, abs=1e-9)

    df2 = make_bars(closes, spread=2.0)
    df2.loc[df2.index[-3:], "c"] = df2.loc[df2.index[-3:], "l"]
    st2 = stochastic(df2)
    assert float(st2["k"].iloc[-1]) == pytest.approx(0.0, abs=1e-9)


def test_relative_volume_baseline_excludes_today():
    bars = make_bars([100.0] * 25)
    bars["v"] = 1_000_000.0
    bars.loc[bars.index[-1], "v"] = 3_000_000.0
    assert rel_volume(bars, 20) == pytest.approx(3.0, abs=1e-9)


def test_mfi_is_bounded_and_hits_100_on_relentless_buying():
    up = make_bars([100.0 + i for i in range(30)])
    m = mfi(up, 14).dropna()
    assert float(m.iloc[-1]) == pytest.approx(100.0)
    assert ((m >= 0) & (m <= 100)).all()


def test_anchored_vwap_from_the_earnings_date():
    bars = make_bars([100.0] * 10)
    bars["h"] = bars["c"] + 1.0
    bars["l"] = bars["c"] - 1.0
    anchor = bars.index[5].date()
    # typical price is flat at 100 from the anchor forward
    assert anchored_vwap(bars, anchor) == pytest.approx(100.0, abs=1e-9)
    assert anchored_vwap(bars, None) is None
    assert anchored_vwap(bars, date(2099, 1, 1)) is None

    # weighting actually uses volume
    bars2 = make_bars([100.0, 100.0, 100.0, 110.0])
    bars2["h"] = bars2["c"]
    bars2["l"] = bars2["c"]
    bars2["v"] = [1.0, 1.0, 1.0, 3.0]
    a = bars2.index[0].date()
    assert anchored_vwap(bars2, a) == pytest.approx(
        (100 * 1 + 100 * 1 + 100 * 1 + 110 * 3) / 6.0
    )


def test_swing_pivots_and_clustering():
    closes = [10, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12, 11, 12, 13]
    bars = make_bars([float(c) for c in closes], spread=0.2)
    highs, lows = swing_pivots(bars, lookback=2)
    assert len(highs) >= 1 and len(lows) >= 1

    bands = cluster_levels([100.0, 100.5, 101.0, 120.0, 120.4], tolerance_pct=1.5)
    assert len(bands) == 2
    assert bands[0][1] == 3 and bands[1][1] == 2
    assert bands[0][0] == pytest.approx((100.0 + 100.5 + 101.0) / 3)


def test_levels_prior_day_and_gap():
    bars = make_bars([100.0, 100.0, 105.0])
    bars.loc[bars.index[-1], "o"] = 102.0
    iset = compute_all(bars)
    assert iset.levels.prior_close == pytest.approx(100.0)
    assert iset.levels.gap_pct == pytest.approx(2.0)


def test_obv_and_divergence_directions():
    from app.indicators import obv, obv_trend

    up = make_bars([100.0 + i for i in range(40)])
    o = obv(up)
    assert float(o.iloc[-1]) > 0
    assert obv_trend(o, up) == "up"

    down = make_bars([100.0 - i for i in range(40)])
    od = obv(down)
    assert obv_trend(od, down) == "down"


def test_bollinger_squeeze_flags_a_quiet_stretch():
    rng = np.random.default_rng(7)
    noisy = 100 + np.cumsum(rng.normal(0, 1.5, 150))
    quiet = np.full(40, noisy[-1]) + rng.normal(0, 0.02, 40)
    bars = make_bars(np.concatenate([noisy, quiet]), spread=0.4)
    vol = build_volatility_block(bars)
    assert vol.bb_squeeze is True
    assert vol.bb_width is not None and vol.bb_width >= 0


def test_realized_vol_and_atr_pct_are_sane(trending_bars):
    vol = build_volatility_block(trending_bars, benchmark=trending_bars["c"])
    assert 0.0 < vol.atr_pct < 50.0
    assert 0.0 < vol.realized_vol_20d < 200.0
    assert vol.beta_vs_index == pytest.approx(1.0, abs=1e-12)
    assert vol.drawdown_from_swing_high <= 0.0


# ─────────────────────── asset-class routing ───────────────────────

def test_preferred_gets_no_momentum_and_no_score(trending_bars):
    pref = Instrument(
        conid=42, symbol="ABC PRA", exchange="NYSE", asset_class=AssetClass.PREFERRED
    )
    iset = compute_all(trending_bars, benchmark=trending_bars["c"], instrument=pref)

    assert iset.score is None
    assert iset.momentum.rsi14 is None
    assert iset.momentum.macd is None
    assert iset.momentum.rs_vs_index_13w is None
    assert iset.momentum.gated is True
    # the rest of the sleeve still gets trend/volatility/volume/levels
    assert iset.trend.ema20 is not None
    assert iset.volatility.atr14 is not None
    assert iset.volume.obv is not None


def test_equity_gets_the_full_set(trending_bars):
    eq = Instrument(conid=7, symbol="NVDA", exchange="NASDAQ")
    bench = trending_bars["c"] * 0.9
    sector = trending_bars["c"] * 1.1
    anchor = trending_bars.index[-30].date()

    iset = compute_all(trending_bars, bench, sector, eq, anchor)

    assert iset.score is not None
    assert iset.momentum.rsi14 is not None
    assert iset.momentum.rs_vs_index_13w is not None
    assert iset.momentum.rs_vs_sector_13w is not None
    assert iset.volume.anchored_vwap_earnings is not None
    assert iset.trend.ema200 is not None
    assert iset.as_of == trending_bars.index[-1].date()
    assert iset.change_pct == pytest.approx(
        (trending_bars["c"].iloc[-1] / trending_bars["c"].iloc[-2] - 1) * 100
    )


def test_benchmark_with_a_different_calendar_is_joined_not_shifted(trending_bars):
    """Drop a fifth of the benchmark's sessions; RS must still be computable."""
    bench = trending_bars["c"].iloc[::1].copy()
    bench = bench.drop(bench.index[5:15])
    iset = compute_all(trending_bars, benchmark=bench)
    assert iset.momentum.rs_vs_index_13w is not None
    assert iset.volatility.beta_vs_index == pytest.approx(1.0, abs=1e-9)
