"""
§2b — the income sleeve.

Different job, different metrics. Running RSI and MACD across a hundred thinly
traded preferreds and small-cap shipping ADRs would be false precision: on a
name that trades $300k a day, a momentum oscillator mostly measures the
bid-ask spread. So this module computes **no momentum oscillators at all** —
the only two technicals that survive are distance from the 52-week high and
whether price is above its 200 DMA. `assert_no_momentum()` below makes that a
checkable property rather than a promise in a comment.

What this sleeve does compute: yield and yield on cost, the ex-div / pay
calendar, distribution growth and consistency, payout ratio and cash-flow
coverage, the preferred-specific fields (call date, yield to call, par,
cumulative), a liquidity classification with a days-to-exit estimate, and rate
sensitivity to the 10-year — which is what actually drives preferred prices.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import numpy as np

from .config import THIN_LIQUIDITY_ADV_USD
from .models import IncomeRow, Instrument

log = logging.getLogger(__name__)

# Momentum lives in the swing sleeve. Naming them here so the prohibition is
# testable: tests/test_services.py asserts none of these appear on IncomeRow.
FORBIDDEN_TECHNICALS = ("rsi", "macd", "stoch", "adx", "obv", "mfi", "roc")

ADV_WINDOW = 20
# "good" needs real depth, not merely more than the thin bar.
LIQUIDITY_GOOD_MULT = 5.0
# You can realistically be this much of a day's volume without moving the price.
PARTICIPATION_RATE = 0.20

DIVIDEND_CUT_TOLERANCE = 0.99      # a 1% wobble is rounding, not a cut


def assert_no_momentum() -> None:
    """Raise if a momentum field ever leaks onto `IncomeRow`."""
    bad = [f for f in IncomeRow.model_fields
           if any(t in f.lower() for t in FORBIDDEN_TECHNICALS)]
    if bad:
        raise AssertionError(
            f"momentum oscillators do not belong in the income sleeve: {bad}"
        )


# ─────────────────────────── inputs ───────────────────────────


@dataclass
class IncomeInput:
    instrument: Instrument
    price: float
    closes: Sequence[float] = field(default_factory=list)
    volumes: Sequence[float] = field(default_factory=list)
    # (ex_date, amount per share), oldest first
    dividends: Sequence[tuple[date, float]] = field(default_factory=list)
    next_ex_div: date | None = None
    next_pay_date: date | None = None
    periods_per_year: int | None = None     # 4 quarterly, 12 monthly; inferred if None
    eps_ttm: float | None = None
    operating_cash_flow_per_share: float | None = None
    # holding
    quantity: float | None = None
    avg_cost: float | None = None
    # preferred
    call_date: date | None = None
    par_value: float | None = None
    cumulative: bool | None = None
    # rate sensitivity
    tnx_levels: Sequence[float] = field(default_factory=list)
    # sizing for the exit estimate when the name is not held
    reference_notional_usd: float | None = None


# ─────────────────────────── distributions ───────────────────────────


def infer_frequency(dividends: Sequence[tuple[date, float]]) -> int | None:
    """Payments per year, inferred from the median gap between ex-dates."""
    if len(dividends) < 2:
        return None
    ds = sorted(d for d, _ in dividends)
    gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
    if not gaps:
        return None
    med = float(np.median(gaps))
    for days, freq in ((31, 12), (95, 4), (190, 2), (400, 1)):
        if med <= days:
            return freq
    return 1


def annual_distribution(dividends: Sequence[tuple[date, float]],
                        periods_per_year: int | None = None,
                        as_of: date | None = None) -> float | None:
    """Trailing-twelve-month distribution, falling back to annualising the last
    payment when there is less than a year of history."""
    if not dividends:
        return None
    as_of = as_of or max(d for d, _ in dividends)
    ttm = [a for d, a in dividends if (as_of - d).days <= 366]
    freq = periods_per_year or infer_frequency(dividends)
    if len(ttm) >= (freq or 1):
        return float(sum(ttm))
    if freq:
        return float(dividends[-1][1] * freq)
    return float(sum(ttm)) if ttm else None


def _by_year(dividends: Sequence[tuple[date, float]]) -> dict[int, float]:
    out: dict[int, float] = {}
    for d, a in dividends:
        out[d.year] = out.get(d.year, 0.0) + a
    return out


def dividend_growth_5y(dividends: Sequence[tuple[date, float]]) -> float | None:
    """CAGR of the annual distribution over the last five complete years, in %."""
    years = _by_year(dividends)
    if len(years) < 2:
        return None
    ordered = sorted(years)
    # ignore the current (incomplete) year
    complete = ordered[:-1] if len(ordered) > 2 else ordered
    if len(complete) < 2:
        return None
    span = min(5, len(complete) - 1)
    start, end = years[complete[-1 - span]], years[complete[-1]]
    if start <= 0 or end <= 0:
        return None
    return float(((end / start) ** (1 / span) - 1.0) * 100.0)


def consecutive_years(dividends: Sequence[tuple[date, float]]) -> int | None:
    """Consecutive complete years without a cut, counting back from the latest.

    Consistency, not growth: a REIT that holds its distribution flat for a
    decade scores ten, which is the right answer for an income sleeve.
    """
    years = _by_year(dividends)
    if len(years) < 2:
        return None
    ordered = sorted(years)
    complete = ordered[:-1] if len(ordered) > 2 else ordered
    if len(complete) < 2:
        return None
    streak = 1
    for prev, cur in zip(reversed(complete[:-1]), reversed(complete[1:])):
        # iterating newest-first: cur is the later year
        if years[cur] >= years[prev] * DIVIDEND_CUT_TOLERANCE:
            streak += 1
        else:
            break
    return streak


# ─────────────────────────── liquidity ───────────────────────────


def adv_usd(closes: Sequence[float], volumes: Sequence[float],
            window: int = ADV_WINDOW) -> float | None:
    n = min(len(closes), len(volumes))
    if n == 0:
        return None
    c = np.asarray(closes[-n:], dtype=float)[-window:]
    v = np.asarray(volumes[-n:], dtype=float)[-window:]
    if c.size == 0:
        return None
    return float(np.mean(c * v))


def classify_liquidity(adv: float | None) -> Literal["good", "moderate", "thin"] | None:
    if adv is None:
        return None
    if adv < THIN_LIQUIDITY_ADV_USD:
        return "thin"
    if adv < THIN_LIQUIDITY_ADV_USD * LIQUIDITY_GOOD_MULT:
        return "moderate"
    return "good"


def days_to_exit(position_value: float | None, adv: float | None,
                 participation: float = PARTICIPATION_RATE) -> float | None:
    """Sessions to liquidate at `participation` of average daily dollar volume.

    Returns None when the size is unknown — an exit estimate against an
    invented position size would be decoration, and this is a risk field.
    """
    if not position_value or not adv or adv <= 0:
        return None
    return float(position_value / (adv * participation))


# ─────────────────────────── rate sensitivity ───────────────────────────


def rate_beta_tnx(closes: Sequence[float], tnx_levels: Sequence[float]) -> float | None:
    """Sensitivity of the security's return to a 1pp move in the 10-year yield.

    Regressed on the *change in yield*, not on TNX's own return — a yield going
    3.9 -> 4.0 is a 0.1pp move, and that is the unit an income investor thinks in.
    """
    n = min(len(closes), len(tnx_levels))
    if n < 10:
        return None
    c = np.asarray(closes[-n:], dtype=float)
    t = np.asarray(tnx_levels[-n:], dtype=float)
    r = np.diff(c) / c[:-1] * 100.0
    dy = np.diff(t)
    if np.std(dy) == 0:
        return None
    xc = dy - dy.mean()
    return float((xc @ (r - r.mean())) / (xc @ xc))


# ─────────────────────────── the two permitted technicals ───────────────────────────


def pct_from_52w_high(closes: Sequence[float], sessions: int = 252) -> float | None:
    if not closes:
        return None
    w = np.asarray(closes[-sessions:], dtype=float)
    hi = float(np.max(w))
    return None if hi == 0 else float((w[-1] / hi - 1.0) * 100.0)


def above_200dma(closes: Sequence[float]) -> bool | None:
    if len(closes) < 200:
        return None
    w = np.asarray(closes[-200:], dtype=float)
    return bool(closes[-1] > float(np.mean(w)))


# ─────────────────────────── preferreds ───────────────────────────


def yield_to_call(price: float, par: float | None, annual_dist: float | None,
                  call_date: date | None, as_of: date | None = None) -> float | None:
    """Approximate YTC: (income + amortised pull-to-par) / average invested."""
    if not price or par is None or annual_dist is None or call_date is None:
        return None
    as_of = as_of or date.today()
    years = (call_date - as_of).days / 365.25
    if years <= 0:
        return None
    ytc = (annual_dist + (par - price) / years) / ((par + price) / 2.0) * 100.0
    return None if math.isnan(ytc) else float(ytc)


# ─────────────────────────── rows ───────────────────────────


def build_income_row(inp: IncomeInput, *, as_of: date | None = None) -> IncomeRow:
    as_of = as_of or date.today()
    price = float(inp.price)

    annual = annual_distribution(inp.dividends, inp.periods_per_year, as_of=as_of)
    cur_yield = (annual / price * 100.0) if annual and price else None
    yoc = (annual / inp.avg_cost * 100.0) if annual and inp.avg_cost else None

    payout = None
    if annual is not None and inp.eps_ttm:
        payout = float(annual / inp.eps_ttm * 100.0)
    coverage = None
    if annual and inp.operating_cash_flow_per_share:
        coverage = float(inp.operating_cash_flow_per_share / annual)

    adv = adv_usd(inp.closes, inp.volumes)
    position_value = ((inp.quantity or 0) * price) or inp.reference_notional_usd

    is_pref = inp.instrument.asset_class.value == "preferred" or inp.par_value is not None

    return IncomeRow(
        instrument=inp.instrument,
        price=price,
        current_yield=_r(cur_yield),
        yield_on_cost=_r(yoc),
        ex_div_date=inp.next_ex_div,
        pay_date=inp.next_pay_date,
        annual_distribution=_r(annual, 6),
        dividend_growth_5y=_r(dividend_growth_5y(inp.dividends)),
        consecutive_years=consecutive_years(inp.dividends),
        payout_ratio=_r(payout),
        cash_flow_coverage=_r(coverage),
        call_date=inp.call_date if is_pref else None,
        yield_to_call=_r(yield_to_call(price, inp.par_value, annual,
                                       inp.call_date, as_of)) if is_pref else None,
        par_value=inp.par_value if is_pref else None,
        cumulative=inp.cumulative if is_pref else None,
        adv_usd_20d=_r(adv, 2),
        liquidity=classify_liquidity(adv),
        days_to_exit=_r(days_to_exit(position_value, adv), 3),
        rate_beta_tnx=_r(rate_beta_tnx(inp.closes, inp.tnx_levels), 4),
        pct_from_52w_high=_r(pct_from_52w_high(inp.closes)),
        above_200dma=above_200dma(inp.closes),
    )


def _r(v: float | None, nd: int = 4) -> float | None:
    return None if v is None else round(float(v), nd)


def build_income_sleeve(inputs: Iterable[IncomeInput],
                        *, as_of: date | None = None) -> list[IncomeRow]:
    """The whole sleeve, sorted by the thing the sleeve is for: yield, with
    thin names surfaced by the liquidity column rather than hidden."""
    assert_no_momentum()
    rows = [build_income_row(i, as_of=as_of) for i in inputs]
    rows.sort(key=lambda r: (r.current_yield is None, -(r.current_yield or 0.0)))
    thin = [r.instrument.symbol for r in rows if r.liquidity == "thin"]
    if thin:
        log.info("income sleeve: %d thin name(s): %s", len(thin), ", ".join(thin[:20]))
    return rows
