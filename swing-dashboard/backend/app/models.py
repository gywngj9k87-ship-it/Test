"""
THE API CONTRACT.

This file is the single source of truth shared by the Python service and the
Next.js front end. `frontend/lib/types.ts` is generated from it (see CLAUDE.md).
Change a shape here and you must regenerate the TypeScript types.

Design rules baked in:
  * Every instrument is keyed on (conid, exchange). `symbol` is a display label.
    SOXL is a 4x LSE ETP and a 3x US ETF; MAGS is a 1x US ETF and a -3x LSE
    inverse. Symbols are not identities.
  * Every numeric that came from more than one source carries a Reconciliation.
  * Nothing silently picks a winner when sources disagree.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ─────────────────────────── identity ───────────────────────────

class AssetClass(str, Enum):
    EQUITY = "equity"          # ordinary stock / ADR / GDR
    ETF = "etf"                # unleveraged fund
    LEVERAGED_ETP = "leveraged_etp"   # gets the §2c module
    PREFERRED = "preferred"    # gets the income sleeve
    INDEX = "index"
    FX = "fx"
    FUND = "fund"
    OTHER = "other"


class Instrument(BaseModel):
    """The identity of a tradable thing. NEVER identify by symbol alone."""
    conid: int                       # IBKR contract id — the real primary key
    symbol: str                      # display label only
    name: str | None = None
    exchange: str                    # LSEETF, ARCA, NASDAQ, FWB, ...
    country: str | None = None       # GB, US, DE, KR, JP
    currency: str = "USD"
    asset_class: AssetClass = AssetClass.EQUITY
    sector: str | None = None
    industry: str | None = None
    theme: str | None = None         # our own grouping: Semis, Space tech, Shipping...

    # leveraged ETP only
    leverage: float | None = None    # 5.0, 4.0, 3.0, -3.0 (negative = inverse)
    underlying_conid: int | None = None
    ter_bps: int | None = None       # total expense ratio, basis points

    @property
    def key(self) -> str:
        return f"{self.conid}@{self.exchange}"


# ─────────────────────────── prices ───────────────────────────

class Bar(BaseModel):
    t: date
    o: float
    h: float
    l: float
    c: float
    v: float


class Quote(BaseModel):
    conid: int
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    ts: datetime | None = None
    delayed_seconds: int = 0         # IBKR returns 900 on delayed feeds — surface it


class Reconciliation(BaseModel):
    """Emitted whenever IBKR and Yahoo disagree beyond tolerance."""
    field: str
    ibkr: float | None = None
    yahoo: float | None = None
    diff_pct: float | None = None
    tolerance_pct: float
    breached: bool
    note: str | None = None


# ─────────────────────────── indicators ───────────────────────────

class TrendBlock(BaseModel):
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    stack_aligned: bool | None = None       # 20 > 50 > 200 and price above all
    golden_cross: bool | None = None
    days_since_cross: int | None = None
    adx14: float | None = None
    trend_strong: bool | None = None        # ADX >= 20 — GATES the momentum block
    slope20: float | None = None
    pct_from_52w_high: float | None = None
    pct_from_52w_low: float | None = None


class MomentumBlock(BaseModel):
    rsi14: float | None = None
    rsi_regime: Literal["strong", "neutral", "weak"] | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    macd_cross: Literal["bullish", "bearish", "none"] | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    roc5: float | None = None
    roc20: float | None = None
    rs_vs_index_4w: float | None = None      # excess return, percentage points
    rs_vs_index_13w: float | None = None
    rs_vs_sector_13w: float | None = None
    gated: bool = False                      # True when ADX < 20; UI greys these out


class VolatilityBlock(BaseModel):
    atr14: float | None = None
    atr_pct: float | None = None             # drives position sizing AND stops
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_pct_b: float | None = None
    bb_width: float | None = None
    bb_squeeze: bool | None = None           # width in the lowest decile of 6m
    realized_vol_20d: float | None = None
    beta_vs_index: float | None = None
    drawdown_from_swing_high: float | None = None


class VolumeBlock(BaseModel):
    rel_volume: float | None = None          # vs 20d average
    obv: float | None = None
    obv_trend: Literal["up", "down", "flat"] | None = None
    obv_divergence: bool | None = None
    anchored_vwap_earnings: float | None = None
    mfi14: float | None = None


class LevelsBlock(BaseModel):
    support: list[float] = Field(default_factory=list)
    resistance: list[float] = Field(default_factory=list)
    prior_day_high: float | None = None
    prior_day_low: float | None = None
    prior_close: float | None = None
    gap_pct: float | None = None


class ScoreComponent(BaseModel):
    name: str
    value: float                 # 0-100
    weight: float                # sums to 1.0
    note: str | None = None


class SetupScore(BaseModel):
    """Never a black box. `components` is always populated and always shown."""
    total: float
    components: list[ScoreComponent]
    verdict: Literal["strong", "constructive", "neutral", "weak"]


class IndicatorSet(BaseModel):
    conid: int
    symbol: str
    as_of: date
    close: float
    change_pct: float | None = None
    trend: TrendBlock
    momentum: MomentumBlock
    volatility: VolatilityBlock
    volume: VolumeBlock
    levels: LevelsBlock
    score: SetupScore | None = None
    reconciliation: list[Reconciliation] = Field(default_factory=list)


# ─────────────────────────── market view ───────────────────────────

class BreadthSnapshot(BaseModel):
    universe_size: int
    above_50dma: int
    above_50dma_pct: float
    above_200dma: int | None = None
    advancers: int
    decliners: int
    new_highs_52w: int
    new_lows_52w: int
    median_return_4w: float
    index_return_13w: float
    equal_weight_return_13w: float
    spread_13w: float                # equal-weight minus index; negative = narrow
    verdict: Literal["broad", "mixed", "narrow"]


class ThemeRow(BaseModel):
    theme: str
    count: int
    return_1w: float
    return_4w: float
    return_13w: float
    rs_vs_index_13w: float


class DriverRow(BaseModel):
    """One row of the index-driver / relative-strength table."""
    conid: int
    symbol: str
    exchange: str
    theme: str | None = None
    last: float
    return_1w: float
    return_4w: float
    return_13w: float
    rs_vs_index_13w: float
    above_50dma: bool
    pct_from_high: float
    at_new_high: bool


class IndexTile(BaseModel):
    label: str
    conid: int
    last: float
    return_1w: float
    return_4w: float
    return_13w: float
    pct_from_high: float
    at_new_high: bool


class MarketOverview(BaseModel):
    as_of: datetime
    tiles: list[IndexTile]
    breadth: BreadthSnapshot
    themes: list[ThemeRow]
    drivers: list[DriverRow]
    index_series: list[float]            # indexed to 100
    equal_weight_series: list[float]
    dates: list[date]
    stale: bool = False                  # cache older than the refresh interval


# ─────────────────────────── screens ───────────────────────────

class ScreenName(str, Enum):
    GAINERS = "gainers"
    LOSERS = "losers"
    UNUSUAL_VOLUME = "unusual_volume"
    NEW_HIGHS = "new_highs"
    NEW_LOWS = "new_lows"
    RS_LEADERS = "rs_leaders"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    EARNINGS_MOVERS = "earnings_movers"
    SQUEEZE = "squeeze"
    DMA_CROSS = "dma_cross"


class ScreenResult(BaseModel):
    screen: ScreenName
    rows: list[DriverRow]
    truncated_at: int | None = None      # if capped, SAY SO — never silent truncation


# ─────────────────────────── events ───────────────────────────

class EventClass(str, Enum):
    EARNINGS = "earnings"
    PRICE_ANOMALY = "price_anomaly"
    ANALYST = "analyst"
    CORPORATE_ACTION = "corporate_action"
    MACRO = "macro"
    HEADLINE = "headline"


class Severity(str, Enum):
    GOOD = "good"
    NEUTRAL = "neutral"
    WARNING = "warning"
    SERIOUS = "serious"
    CRITICAL = "critical"


class MarketEvent(BaseModel):
    """Every event is paired with its price reaction. That pairing is the point."""
    ts: datetime
    conid: int | None = None
    symbol: str | None = None
    event_class: EventClass
    title: str
    detail: str
    reaction_pct: float | None = None    # what the price actually did
    reaction_label: str | None = None    # "Calendar", "Flagged" when not a % move
    severity: Severity = Severity.NEUTRAL
    moved_price: bool = False            # ranking key — filters out pure noise
    url: str | None = None


class EarningsRow(BaseModel):
    conid: int
    symbol: str
    report_date: date
    days_until: int | None = None
    eps_actual: float | None = None
    eps_estimate: float | None = None
    eps_surprise_pct: float | None = None
    revenue_actual: float | None = None
    revenue_estimate: float | None = None
    guidance: Literal["raised", "maintained", "cut", "none"] | None = None
    reaction_pct: float | None = None
    drift_5d_pct: float | None = None


# ─────────────────────────── portfolio ───────────────────────────

class CostBasisStatus(str, Enum):
    OK = "ok"
    UNVERIFIED = "unverified"            # e.g. NAKA: avg 169.65 vs mkt 4.85
    CORPORATE_ACTION_SUSPECTED = "corporate_action_suspected"


class Position(BaseModel):
    instrument: Instrument
    quantity: float
    avg_cost: float
    last: float
    market_value: float
    unrealized_pnl: float
    unrealized_pct: float
    weight_pct: float
    day_pnl: float | None = None
    contribution_to_day_return: float | None = None
    cost_basis_status: CostBasisStatus = CostBasisStatus.OK
    cost_basis_note: str | None = None


class RiskFlag(BaseModel):
    severity: Severity
    icon: str                            # status colour NEVER carries meaning alone
    title: str
    detail: str
    conid: int | None = None


class PortfolioSnapshot(BaseModel):
    as_of: datetime
    net_liquidation: float
    cash: float
    gross_position_value: float
    deployed_pct: float
    leverage: float
    positions: list[Position]
    total_market_value: float
    total_unrealized_pnl: float
    day_pnl: float | None = None
    beta_vs_index: float | None = None
    sector_exposure: dict[str, float] = Field(default_factory=dict)
    largest_position_pct: float | None = None
    flags: list[RiskFlag] = Field(default_factory=list)
    reconciliation: list[Reconciliation] = Field(default_factory=list)


# ─────────────────────────── leverage (§2c) ───────────────────────────

class LeverageAnalysis(BaseModel):
    """
    The module that makes leveraged ETPs legible. Measured, not assumed.

    Reference values verified against IBKR data on 2026-08-06:
      MAG7.L 5x : underlying +14.2%, naive +70.8%, actual +4.0%, beta 4.64,
                  vol drag 54.5%/yr, max DD -68.7%
      SOXL.L 4x : underlying +94.1%, naive +376.3%, actual +419.1%, beta 4.18,
                  vol drag 61.0%/yr, max DD -72.2%
    """
    instrument: Instrument
    underlying: Instrument
    window_days: int

    underlying_return_pct: float
    naive_expected_pct: float            # leverage * underlying_return
    actual_return_pct: float
    gap_pp: float                        # actual - naive; the decay number

    realized_beta: float                 # rolling regression vs underlying
    stated_leverage: float
    beta_drift: float                    # realized - stated; tracking degradation

    underlying_vol_annual: float
    product_vol_annual: float
    volatility_drag_annual_pct: float    # 0.5 * L * (L-1) * sigma^2

    max_drawdown_pct: float
    underlying_max_drawdown_pct: float
    pct_from_high: float
    recovery_needed_pct: float           # 1/(1-dd) - 1. Not intuitive; show it.

    regime: Literal["trending", "choppy", "unclear"]
    regime_note: str

    single_day_wipeout_pct: float        # -20% underlying kills a 5x
    issuer_reset_threshold_pct: float | None = None
    carry_cost_annual_pct: float | None = None   # TER + financing on (L-1)

    days_held: int | None = None
    holding_period_warning: str | None = None

    # entry-anchored: only when the user holds it
    since_entry_gap_pp: float | None = None


class TickerCollision(BaseModel):
    """
    One contract in a symbol that resolves to more than one instrument.

    Rule #1: identity is `(conid, exchange)`, never the symbol. `SOXL` is both a
    Leverage Shares 4x LSE ETP and a Direxion 3x US ETF; `MAGS` is an
    unleveraged US long and a Leverage Shares -3x LSE inverse. This table names
    every contract behind a colliding ticker so the UI can disambiguate them.
    """
    symbol: str
    conid: int
    exchange: str
    country: str
    description: str
    inverse: bool                        # the -3x product ships with a ⛔ chip


class RoundTripRow(BaseModel):
    """
    One row of the ±10% alternating-move table: what a daily-rebalanced product
    of a given leverage returns after the underlying round-trips to roughly
    where it started. The point is the asymmetry — the underlying loses ~9.6%
    to twenty alternating moves, a 5x loses ~94%.
    """
    leverage: float
    underlying_pct: float                # the 1x round-trip outcome (same every row)
    levered_pct: float
    note: str | None = None              # an example product at this leverage


# ─────────────────────────── income sleeve (§2b) ───────────────────────────

class IncomeRow(BaseModel):
    instrument: Instrument
    price: float
    current_yield: float | None = None
    yield_on_cost: float | None = None
    ex_div_date: date | None = None
    pay_date: date | None = None
    annual_distribution: float | None = None
    dividend_growth_5y: float | None = None
    consecutive_years: int | None = None
    payout_ratio: float | None = None
    cash_flow_coverage: float | None = None
    # preferred-specific
    call_date: date | None = None
    yield_to_call: float | None = None
    par_value: float | None = None
    cumulative: bool | None = None
    # risk
    adv_usd_20d: float | None = None
    liquidity: Literal["good", "moderate", "thin"] | None = None
    days_to_exit: float | None = None
    rate_beta_tnx: float | None = None
    pct_from_52w_high: float | None = None
    above_200dma: bool | None = None


# ─────────────────────────── alerts & journal ───────────────────────────

class AlertRule(BaseModel):
    id: str
    name: str
    expression: str                      # "rsi14 < 35 and close > ema200 and rel_volume > 1.5"
    scope: Literal["portfolio", "watchlist", "universe"] = "watchlist"
    watchlist_id: str | None = None
    enabled: bool = True


class AlertHit(BaseModel):
    rule_id: str
    rule_name: str
    conid: int
    symbol: str
    triggered_at: datetime
    snapshot: dict[str, float]


class JournalEntry(BaseModel):
    """Snapshots indicator state at entry so the dashboard can later tell you
    which of YOUR setups actually work. This is the feature that compounds."""
    id: str
    conid: int
    symbol: str
    opened_at: datetime
    closed_at: datetime | None = None
    direction: Literal["long", "short"] = "long"
    entry_price: float
    exit_price: float | None = None
    size: float
    thesis: str
    exit_reason: str | None = None
    entry_snapshot: dict[str, float] = Field(default_factory=dict)
    realized_pnl: float | None = None
    r_multiple: float | None = None


class SetupPerformance(BaseModel):
    """How one class of setup has actually performed, in the user's own trades.

    A `setup` is a bucket of the app's own setup score at entry — the point is
    to check whether the score the dashboard shows predicts the outcomes the
    user actually gets. R-multiple stats cover only closed trades that recorded
    an `r_multiple`; `total_pnl` covers every closed trade with a realised P&L.
    """
    setup: str
    trades: int                          # closed trades in this bucket
    wins: int
    win_rate: float                      # 0..1, over trades with a known outcome
    avg_win_r: float                     # mean R of winners (0 if none)
    avg_loss_r: float                    # mean R of losers, <= 0 (0 if none)
    expectancy_r: float                  # mean R across the bucket — the number
    total_pnl: float


class JournalStats(BaseModel):
    """The compounding feature: after ~20 trades this says which of the user's
    own setups actually work. Everything here is derived from `JournalEntry`
    rows — no new data, just the aggregation the raw log cannot show."""
    total_entries: int
    open_positions: int
    closed_trades: int
    win_rate: float | None = None        # None until a trade with an outcome closes
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    expectancy_r: float | None = None
    total_realized_pnl: float
    best_setup: str | None = None        # highest-expectancy bucket at min sample
    by_setup: list[SetupPerformance] = Field(default_factory=list)
    # Set while the sample is too thin to trust — the breakdown is provisional
    # under ~20 closed trades. Reported, never silently omitted.
    sample_warning: str | None = None
