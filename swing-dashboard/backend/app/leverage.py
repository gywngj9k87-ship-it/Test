"""
§2c — the leveraged-ETP module.

The one part of the dashboard that has to be *measured*, not assumed. A 5x
product on an underlying that rose 14% returned 4%; a 4x product on an
underlying that rose 94% returned 419%. Same mechanism, opposite sign.
Leverage rewards trend and punishes chop, and neither RSI nor MACD tells you
which regime you are in — so this module says it explicitly.

Everything here is pure numpy over two aligned close series (the ETP and its
unleveraged underlying). No sources, no cache, no I/O — which is why the
regression test in tests/test_services.py can pin it to real IBKR numbers.

Reference values, 12 months to 2026-08-06, real IBKR data:

    MAG7.L 5x vs MAGS : underlying +14.2%, naive +70.8%, actual  +4.0%,
                        gap -66.9pp, beta 4.64, vol drag 54.5%, max DD -68.7%
    SOXL.L 4x vs SMH  : underlying +94.1%, naive +376.3%, actual +419.1%,
                        gap +42.8pp, beta 4.18, vol drag 61.0%, max DD -72.2%

Convention notes that matter for reproducing those numbers:
  * returns are simple (not log) percentage changes;
  * realised beta is the OLS slope *with* an intercept, over the full window;
  * volatility is the population standard deviation (ddof=0) annualised by
    sqrt(periods_per_year) — that is what the reference figures were measured
    with, and with ~52 observations the ddof choice moves the drag by ~1pp.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from .models import Instrument, LeverageAnalysis

_log = logging.getLogger(__name__)

# A daily-rebalanced product held longer than this is no longer doing the job
# it was designed for. Spec §2c: "a nudge when a position designed for daily
# rebalancing has been held for weeks".
DAILY_REBALANCE_HOLD_LIMIT_DAYS = 10

# Default financing assumption when the caller supplies no short rate.
DEFAULT_SHORT_RATE_PCT = 4.0

# Rolling window (in observations) for the beta-stability note.
DEFAULT_ROLLING_BETA_WINDOW = 20


# ─────────────────────────── primitives ───────────────────────────


def simple_returns(closes: Sequence[float] | np.ndarray) -> np.ndarray:
    """Period-over-period simple returns."""
    a = np.asarray(closes, dtype=float)
    if a.size < 2:
        return np.zeros(0, dtype=float)
    return np.diff(a) / a[:-1]


def total_return_pct(closes: Sequence[float] | np.ndarray) -> float:
    a = np.asarray(closes, dtype=float)
    if a.size < 2 or a[0] == 0:
        return 0.0
    return float((a[-1] / a[0] - 1.0) * 100.0)


def annualised_vol_pct(returns: np.ndarray, periods_per_year: int) -> float:
    """Population sigma, annualised, in percent."""
    if returns.size < 2:
        return 0.0
    return float(np.std(returns, ddof=0) * math.sqrt(periods_per_year) * 100.0)


def ols_beta(y: np.ndarray, x: np.ndarray) -> float:
    """OLS slope of y on x, with an intercept. cov(x, y) / var(x)."""
    if y.size != x.size or x.size < 2:
        return float("nan")
    xc = x - x.mean()
    yc = y - y.mean()
    denom = float(xc @ xc)
    if denom == 0.0:
        return float("nan")
    return float((xc @ yc) / denom)


def rolling_beta(y: np.ndarray, x: np.ndarray,
                 window: int = DEFAULT_ROLLING_BETA_WINDOW) -> np.ndarray:
    """Rolling-regression beta series. Used for the tracking-stability note.

    `realized_beta` on the model is the full-window slope (that is the number
    the reference values were measured with); this series is what tells you
    whether the product's tracking is *degrading* rather than merely off.
    """
    n = min(y.size, x.size)
    if n < window or window < 2:
        return np.zeros(0, dtype=float)
    return np.array([ols_beta(y[i - window:i], x[i - window:i])
                     for i in range(window, n + 1)], dtype=float)


def max_drawdown_pct(closes: Sequence[float] | np.ndarray) -> float:
    """Worst peak-to-trough decline over the window, in percent (negative)."""
    a = np.asarray(closes, dtype=float)
    if a.size == 0:
        return 0.0
    peak = np.maximum.accumulate(a)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, a / peak - 1.0, 0.0)
    return float(np.min(dd) * 100.0)


def pct_from_high(closes: Sequence[float] | np.ndarray) -> float:
    a = np.asarray(closes, dtype=float)
    if a.size == 0:
        return 0.0
    hi = float(np.max(a))
    if hi == 0:
        return 0.0
    return float((a[-1] / hi - 1.0) * 100.0)


def recovery_needed_pct(drawdown_pct: float) -> float:
    """The asymmetry: 1/(1-dd) - 1. -68.7% needs +220%, not +68.7%."""
    dd = drawdown_pct / 100.0
    if dd >= 0:
        return 0.0
    if dd <= -1.0:
        return float("inf")
    return float((1.0 / (1.0 + dd) - 1.0) * 100.0)


def volatility_drag_annual_pct(leverage: float, underlying_vol_pct: float) -> float:
    """0.5 * L * (L-1) * sigma^2, in percent per year.

    Inverse products are handled by the same formula: L=-3 gives
    L*(L-1) = 12, i.e. a *larger* drag than a 3x long. That is correct.
    """
    sigma = underlying_vol_pct / 100.0
    return float(0.5 * leverage * (leverage - 1.0) * sigma * sigma * 100.0)


def single_day_wipeout_pct(leverage: float) -> float:
    """The single-day *underlying* move that takes the product to zero.

    -20% for a 5x long, -25% for 4x, -33% for 3x; for an inverse product the
    killing move is a rally, so the sign flips.
    """
    if leverage == 0:
        return float("nan")
    return float(-100.0 / leverage)


def carry_cost_annual_pct(leverage: float, ter_bps: int | None,
                          short_rate_pct: float = DEFAULT_SHORT_RATE_PCT) -> float:
    """TER plus financing on the borrowed (L-1) notional."""
    ter_pct = (ter_bps or 0) / 100.0
    financing = abs(leverage - 1.0) * short_rate_pct
    return float(ter_pct + financing)


def autocorrelation(returns: np.ndarray, lag: int = 1) -> float:
    """Lag-1 autocorrelation of returns. Positive = trending, negative = chop."""
    if returns.size <= lag + 1:
        return float("nan")
    a = returns[:-lag]
    b = returns[lag:]
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


# ─────────────────────────── regime ───────────────────────────

RegimeT = Literal["trending", "choppy", "unclear"]

ADX_TRENDING = 25.0
ADX_CHOPPY = 20.0
AC_TRENDING = 0.05
AC_CHOPPY = -0.05


def classify_regime(adx: float | None, autocorr: float | None) -> tuple[RegimeT, str]:
    """Trending / choppy from ADX **of the underlying** plus return autocorrelation.

    Both inputs describe the UNDERLYING, never the ETP. The ETP's own ADX is
    contaminated by the leverage itself and would read "trending" on noise.
    """
    trend_votes: list[str] = []
    chop_votes: list[str] = []

    if adx is not None and not _isnan(adx):
        if adx >= ADX_TRENDING:
            trend_votes.append(f"ADX {adx:.0f} (>= {ADX_TRENDING:.0f})")
        elif adx < ADX_CHOPPY:
            chop_votes.append(f"ADX {adx:.0f} (< {ADX_CHOPPY:.0f})")

    if autocorr is not None and not _isnan(autocorr):
        if autocorr >= AC_TRENDING:
            trend_votes.append(f"return autocorrelation +{autocorr:.2f}")
        elif autocorr <= AC_CHOPPY:
            chop_votes.append(f"return autocorrelation {autocorr:.2f}")

    if trend_votes and not chop_votes:
        return "trending", (
            "Underlying is trending — " + " and ".join(trend_votes)
            + ". Leverage compounds in your favour while this holds."
        )
    if chop_votes and not trend_votes:
        return "choppy", (
            "Underlying is choppy — " + " and ".join(chop_votes)
            + ". This is the regime that costs leveraged holders the most."
        )
    if not trend_votes and not chop_votes:
        return "unclear", (
            "Neither ADX nor return autocorrelation is decisive on the "
            "underlying; treat the regime as unknown, not as benign."
        )
    return "unclear", (
        "Mixed signal on the underlying: "
        + "; ".join(trend_votes + chop_votes)
        + ". Regime is transitioning."
    )


def _isnan(x: float | None) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


# ─────────────────────────── the analysis ───────────────────────────


@dataclass
class Holding:
    """What the user actually owns, when the ETP is in the book."""
    entry_date: date | None = None
    entry_index: int | None = None        # index into the supplied close series
    days_held: int | None = None
    quantity: float | None = None


def compute_leverage_analysis(
    instrument: Instrument,
    underlying: Instrument,
    etp_closes: Sequence[float],
    underlying_closes: Sequence[float],
    *,
    dates: Sequence[date] | None = None,
    periods_per_year: int = 252,
    stated_leverage: float | None = None,
    ter_bps: int | None = None,
    short_rate_pct: float = DEFAULT_SHORT_RATE_PCT,
    underlying_adx: float | None = None,
    issuer_reset_threshold_pct: float | None = None,
    holding: Holding | None = None,
    daily_rebalanced: bool = True,
    window_days: int | None = None,
    rolling_window: int = DEFAULT_ROLLING_BETA_WINDOW,
) -> LeverageAnalysis:
    """Build a `LeverageAnalysis` from two aligned close series.

    `periods_per_year` must match the sampling of the series: 252 for daily
    bars, 52 for weekly. It only affects the annualised vol and, through it,
    the volatility drag.
    """
    lev = np.asarray(etp_closes, dtype=float)
    und = np.asarray(underlying_closes, dtype=float)
    n = min(lev.size, und.size)
    if n < 2:
        raise ValueError("need at least two aligned observations")
    lev, und = lev[-n:], und[-n:]

    L = stated_leverage
    if L is None:
        L = instrument.leverage
    if L is None:
        raise ValueError(
            f"{instrument.symbol} ({instrument.conid}) has no leverage factor. "
            "IBKR does not expose it; add the conid to config.LEVERAGED_ETPS."
        )
    L = float(L)
    if ter_bps is None:
        ter_bps = instrument.ter_bps

    r_lev = simple_returns(lev)
    r_und = simple_returns(und)

    underlying_return = total_return_pct(und)
    actual_return = total_return_pct(lev)
    naive_expected = L * underlying_return
    gap = actual_return - naive_expected

    beta = ols_beta(r_lev, r_und)
    roll = rolling_beta(r_lev, r_und, window=min(rolling_window, max(2, n - 1)))

    und_vol = annualised_vol_pct(r_und, periods_per_year)
    prod_vol = annualised_vol_pct(r_lev, periods_per_year)
    drag = volatility_drag_annual_pct(L, und_vol)

    dd = max_drawdown_pct(lev)
    und_dd = max_drawdown_pct(und)

    regime, regime_note = classify_regime(underlying_adx, autocorrelation(r_und))
    if roll.size >= 2:
        spread = float(np.nanmax(roll) - np.nanmin(roll))
        regime_note += (
            f" Rolling {min(rolling_window, max(2, n - 1))}-period beta ranged "
            f"{np.nanmin(roll):.2f}-{np.nanmax(roll):.2f} (spread {spread:.2f}) "
            f"against a stated {L:g}x."
        )

    # ── entry-anchored, only when the user holds it ──
    since_entry_gap: float | None = None
    days_held: int | None = None
    warning: str | None = None

    if holding is not None:
        idx = holding.entry_index
        if idx is None and holding.entry_date is not None and dates:
            idx = _index_for_date(dates[-n:], holding.entry_date)
        if idx is not None and 0 <= idx < n - 1:
            u_since = total_return_pct(und[idx:])
            l_since = total_return_pct(lev[idx:])
            since_entry_gap = float(l_since - L * u_since)

        days_held = holding.days_held
        if days_held is None and holding.entry_date is not None and dates:
            days_held = _sessions_since(dates[-n:], holding.entry_date)

        if daily_rebalanced and days_held is not None and days_held > DAILY_REBALANCE_HOLD_LIMIT_DAYS:
            warning = (
                f"Held {days_held} sessions. {instrument.symbol} rebalances daily — "
                f"it tracks {L:g}x the underlying's *daily* move, not its "
                f"{days_held}-session move. Path dependence, not tracking error, "
                f"is what you are now exposed to"
                + (f"; the gap since entry is {since_entry_gap:+.1f}pp."
                   if since_entry_gap is not None else ".")
            )

    return LeverageAnalysis(
        instrument=instrument,
        underlying=underlying,
        window_days=int(window_days if window_days is not None else n),
        underlying_return_pct=round(underlying_return, 4),
        naive_expected_pct=round(naive_expected, 4),
        actual_return_pct=round(actual_return, 4),
        gap_pp=round(gap, 4),
        realized_beta=round(beta, 4),
        stated_leverage=L,
        beta_drift=round(beta - L, 4),
        underlying_vol_annual=round(und_vol, 4),
        product_vol_annual=round(prod_vol, 4),
        volatility_drag_annual_pct=round(drag, 4),
        max_drawdown_pct=round(dd, 4),
        underlying_max_drawdown_pct=round(und_dd, 4),
        pct_from_high=round(pct_from_high(lev), 4),
        recovery_needed_pct=round(recovery_needed_pct(dd), 4),
        regime=regime,
        regime_note=regime_note,
        single_day_wipeout_pct=round(single_day_wipeout_pct(L), 4),
        issuer_reset_threshold_pct=issuer_reset_threshold_pct,
        carry_cost_annual_pct=round(carry_cost_annual_pct(L, ter_bps, short_rate_pct), 4),
        days_held=days_held,
        holding_period_warning=warning,
        since_entry_gap_pp=None if since_entry_gap is None else round(since_entry_gap, 4),
    )


def _index_for_date(dates: Sequence[date], target: date) -> int | None:
    for i, d in enumerate(dates):
        if d >= target:
            return i
    return None


def _sessions_since(dates: Sequence[date], target: date) -> int | None:
    idx = _index_for_date(dates, target)
    if idx is None:
        return None
    return len(dates) - 1 - idx


# ─────────────────────────── service entry points ───────────────────────────


def instrument_from_registry(conid: int, registry: dict[int, dict]) -> Instrument:
    """Build an `Instrument` for a leveraged ETP out of config.LEVERAGED_ETPS."""
    from .models import AssetClass

    meta = registry[conid]
    return Instrument(
        conid=conid,
        symbol=meta["symbol"],
        name=meta.get("name"),
        exchange=meta["exchange"],
        country=meta.get("country"),
        currency=meta.get("currency", "USD"),
        asset_class=AssetClass.LEVERAGED_ETP,
        leverage=float(meta["leverage"]),
        underlying_conid=meta.get("underlying_conid"),
        ter_bps=meta.get("ter_bps"),
    )


def analyse_from_bars(
    instrument: Instrument,
    underlying: Instrument,
    etp_bars: Sequence,
    underlying_bars: Sequence,
    **kw,
) -> LeverageAnalysis:
    """Adapter for `Bar` sequences: aligns on date, then delegates."""
    a = {b.t: b.c for b in etp_bars}
    b = {x.t: x.c for x in underlying_bars}
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        raise ValueError(
            f"{instrument.symbol} and {underlying.symbol} share only "
            f"{len(common)} session(s) — cannot measure decay"
        )
    kw.setdefault("dates", common)
    kw.setdefault("periods_per_year", 252)
    return compute_leverage_analysis(
        instrument, underlying,
        [a[d] for d in common], [b[d] for d in common], **kw,
    )


def leveraged_conids(registry: dict[int, dict] | None = None) -> list[int]:
    if registry is None:
        from .config import LEVERAGED_ETPS
        registry = LEVERAGED_ETPS
    return list(registry.keys())


# ─────────────────────────── ±10% round-trip table ───────────────────────────

# The illustration behind rule §2c: a daily-rebalanced product does NOT return
# leverage × the underlying's path return. Twenty alternating ±10% moves leave
# the underlying down ~9.6%; the same path takes a 5x down ~94%. Pure math, no
# I/O — a compounding identity, not a measurement, so it is exact and pinned.
ROUND_TRIP_MOVES = 20                     # ten up/down pairs
ROUND_TRIP_STEP_PCT = 10.0
# An example product at each factor, for the note column. Keyed on leverage.
_ROUND_TRIP_EXAMPLES: dict[int, str] = {4: "SOXL.L", 5: "MAG7.L"}


def _round_trip_pct(leverage: float, moves: int, step_pct: float) -> float:
    """
    Final percentage return of a daily-rebalanced `leverage`x product after
    `moves` alternating ±`step_pct`% underlying moves.

    Each up/down pair multiplies wealth by (1 + L·s)(1 − L·s) = 1 − (L·s)², so
    n pairs give (1 − (L·s)²)ⁿ − 1. With L=1, s=0.10, 10 pairs → −9.56%.
    """
    s = step_pct / 100.0
    pairs = moves // 2
    factor = (1.0 - (leverage * s) ** 2) ** pairs
    return (factor - 1.0) * 100.0


def round_trip_table(
    leverages: Sequence[float] = (1, 2, 3, 4, 5),
    *,
    moves: int = ROUND_TRIP_MOVES,
    step_pct: float = ROUND_TRIP_STEP_PCT,
) -> list["RoundTripRow"]:
    """The ±10% alternating-move table, one row per leverage factor."""
    from .models import RoundTripRow

    underlying_pct = round(_round_trip_pct(1.0, moves, step_pct), 1)
    return [
        RoundTripRow(
            leverage=float(L),
            underlying_pct=underlying_pct,
            levered_pct=round(_round_trip_pct(float(L), moves, step_pct), 1),
            note=_ROUND_TRIP_EXAMPLES.get(int(L)),
        )
        for L in leverages
    ]


# ─────────────────────────── ticker collisions ───────────────────────────

def ticker_collisions(
    collisions: dict[str, list[int]] | None = None,
    leveraged: dict[int, dict] | None = None,
    unleveraged: dict[int, dict] | None = None,
) -> list["TickerCollision"]:
    """
    Every contract behind a symbol that resolves to more than one instrument,
    in a deterministic order (symbols in config order, conids in listed order).

    A leg is `inverse` when its leverage factor is negative — that is the only
    row that ships with the ⛔ chip. Metadata comes from LEVERAGED_ETPS for the
    leveraged legs and UNLEVERAGED_SIBLINGS for the plain ones; a conid missing
    from both is skipped with a warning rather than guessed, because a wrong
    description here points the collision warning at the wrong product.
    """
    from .config import LEVERAGED_ETPS, SYMBOL_COLLISIONS, UNLEVERAGED_SIBLINGS
    from .models import TickerCollision

    collisions = SYMBOL_COLLISIONS if collisions is None else collisions
    leveraged = LEVERAGED_ETPS if leveraged is None else leveraged
    unleveraged = UNLEVERAGED_SIBLINGS if unleveraged is None else unleveraged

    rows: list[TickerCollision] = []
    for symbol, conids in collisions.items():
        for conid in conids:
            meta = leveraged.get(conid) or unleveraged.get(conid)
            if meta is None:
                _log.warning(
                    "collision symbol %s lists conid %s but it is in neither "
                    "LEVERAGED_ETPS nor UNLEVERAGED_SIBLINGS — skipped, not guessed",
                    symbol, conid,
                )
                continue
            rows.append(TickerCollision(
                symbol=symbol,
                conid=conid,
                exchange=meta["exchange"],
                country=meta.get("country", ""),
                description=meta.get("name", ""),
                inverse=float(meta.get("leverage", 0.0)) < 0,
            ))
    return rows
