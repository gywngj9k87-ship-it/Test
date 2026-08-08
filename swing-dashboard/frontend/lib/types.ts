/**
 * THE API CONTRACT, in TypeScript.
 *
 * Hand-written mirror of `backend/app/models.py`. That file is the single
 * source of truth; this one follows it. Change a shape there and change it
 * here in the same commit.
 *
 * Conventions used when translating pydantic → TypeScript:
 *   * `X | None = None`      → `x: X | null`      (the field is always present
 *                              on the wire because FastAPI serialises defaults)
 *   * `date` / `datetime`    → `string` (ISO-8601). Parse at the edge, never
 *                              store a Date in props.
 *   * `Literal[...]`         → a string union
 *   * `str, Enum`            → a const object + union type, so the values are
 *                              usable at runtime (screen names, severities)
 *   * `Field(default_factory=list)` → a required array
 *
 * Design rules baked into the shapes, carried over from the Python docstring:
 *   * Every instrument is keyed on (conid, exchange). `symbol` is a display
 *     label. SOXL is a 4x LSE ETP and a 3x US ETF; MAGS is a 1x US ETF and a
 *     -3x LSE inverse. Symbols are not identities.
 *   * Every numeric that came from more than one source carries a
 *     Reconciliation.
 *   * Nothing silently picks a winner when sources disagree.
 */

// ─────────────────────────── identity ───────────────────────────

export const AssetClass = {
  EQUITY: 'equity',
  ETF: 'etf',
  LEVERAGED_ETP: 'leveraged_etp',
  PREFERRED: 'preferred',
  INDEX: 'index',
  FX: 'fx',
  FUND: 'fund',
  OTHER: 'other',
} as const;
export type AssetClass = (typeof AssetClass)[keyof typeof AssetClass];

/** The identity of a tradable thing. NEVER identify by symbol alone. */
export interface Instrument {
  /** IBKR contract id — the real primary key. */
  conid: number;
  /** Display label only. */
  symbol: string;
  name: string | null;
  /** LSEETF, ARCA, NASDAQ, FWB, ... */
  exchange: string;
  /** GB, US, DE, KR, JP */
  country: string | null;
  currency: string;
  asset_class: AssetClass;
  sector: string | null;
  industry: string | null;
  /** Our own grouping: Semis, Space tech, Shipping... */
  theme: string | null;

  // leveraged ETP only
  /** 5.0, 4.0, 3.0, -3.0 (negative = inverse). */
  leverage: number | null;
  underlying_conid: number | null;
  /** Total expense ratio, basis points. */
  ter_bps: number | null;
}

/** Mirror of the Python `Instrument.key` property. */
export function instrumentKey(i: Pick<Instrument, 'conid' | 'exchange'>): string {
  return `${i.conid}@${i.exchange}`;
}

// ─────────────────────────── prices ───────────────────────────

export interface Bar {
  /** ISO date. */
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Quote {
  conid: number;
  last: number | null;
  bid: number | null;
  ask: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  /** ISO datetime. */
  ts: string | null;
  /** IBKR returns 900 on delayed feeds — surface it. */
  delayed_seconds: number;
}

/** Emitted whenever IBKR and Yahoo disagree beyond tolerance. */
export interface Reconciliation {
  field: string;
  ibkr: number | null;
  yahoo: number | null;
  diff_pct: number | null;
  tolerance_pct: number;
  breached: boolean;
  note: string | null;
}

// ─────────────────────────── indicators ───────────────────────────

export interface TrendBlock {
  ema20: number | null;
  ema50: number | null;
  ema200: number | null;
  /** 20 > 50 > 200 and price above all. */
  stack_aligned: boolean | null;
  golden_cross: boolean | null;
  days_since_cross: number | null;
  adx14: number | null;
  /** ADX >= 20 — GATES the momentum block. */
  trend_strong: boolean | null;
  slope20: number | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
}

export type RsiRegime = 'strong' | 'neutral' | 'weak';
export type MacdCross = 'bullish' | 'bearish' | 'none';

export interface MomentumBlock {
  rsi14: number | null;
  rsi_regime: RsiRegime | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  macd_cross: MacdCross | null;
  stoch_k: number | null;
  stoch_d: number | null;
  roc5: number | null;
  roc20: number | null;
  /** Excess return, percentage points. */
  rs_vs_index_4w: number | null;
  rs_vs_index_13w: number | null;
  rs_vs_sector_13w: number | null;
  /** True when ADX < 20; UI greys these out. */
  gated: boolean;
}

export interface VolatilityBlock {
  atr14: number | null;
  /** Drives position sizing AND stops. */
  atr_pct: number | null;
  bb_upper: number | null;
  bb_lower: number | null;
  bb_pct_b: number | null;
  bb_width: number | null;
  /** Width in the lowest decile of 6m. */
  bb_squeeze: boolean | null;
  realized_vol_20d: number | null;
  beta_vs_index: number | null;
  drawdown_from_swing_high: number | null;
}

export type ObvTrend = 'up' | 'down' | 'flat';

export interface VolumeBlock {
  /** vs 20d average. */
  rel_volume: number | null;
  obv: number | null;
  obv_trend: ObvTrend | null;
  obv_divergence: boolean | null;
  anchored_vwap_earnings: number | null;
  mfi14: number | null;
}

export interface LevelsBlock {
  support: number[];
  resistance: number[];
  prior_day_high: number | null;
  prior_day_low: number | null;
  prior_close: number | null;
  gap_pct: number | null;
}

export interface ScoreComponent {
  name: string;
  /** 0-100 */
  value: number;
  /** Sums to 1.0 */
  weight: number;
  note: string | null;
}

export type SetupVerdict = 'strong' | 'constructive' | 'neutral' | 'weak';

/** Never a black box. `components` is always populated and always shown. */
export interface SetupScore {
  total: number;
  components: ScoreComponent[];
  verdict: SetupVerdict;
}

export interface IndicatorSet {
  conid: number;
  symbol: string;
  /** ISO date. */
  as_of: string;
  close: number;
  change_pct: number | null;
  trend: TrendBlock;
  momentum: MomentumBlock;
  volatility: VolatilityBlock;
  volume: VolumeBlock;
  levels: LevelsBlock;
  score: SetupScore | null;
  reconciliation: Reconciliation[];
}

// ─────────────────────────── market view ───────────────────────────

export type BreadthVerdict = 'broad' | 'mixed' | 'narrow';

export interface BreadthSnapshot {
  universe_size: number;
  above_50dma: number;
  above_50dma_pct: number;
  above_200dma: number | null;
  advancers: number;
  decliners: number;
  new_highs_52w: number;
  new_lows_52w: number;
  median_return_4w: number;
  index_return_13w: number;
  equal_weight_return_13w: number;
  /** Equal-weight minus index; negative = narrow. */
  spread_13w: number;
  verdict: BreadthVerdict;
}

export interface ThemeRow {
  theme: string;
  count: number;
  return_1w: number;
  return_4w: number;
  return_13w: number;
  rs_vs_index_13w: number;
}

/** One row of the index-driver / relative-strength table. */
export interface DriverRow {
  conid: number;
  symbol: string;
  exchange: string;
  theme: string | null;
  last: number;
  return_1w: number;
  return_4w: number;
  return_13w: number;
  rs_vs_index_13w: number;
  above_50dma: boolean;
  pct_from_high: number;
  at_new_high: boolean;
}

export interface IndexTile {
  label: string;
  conid: number;
  last: number;
  return_1w: number;
  return_4w: number;
  return_13w: number;
  pct_from_high: number;
  at_new_high: boolean;
}

export interface MarketOverview {
  /** ISO datetime. */
  as_of: string;
  tiles: IndexTile[];
  breadth: BreadthSnapshot;
  themes: ThemeRow[];
  drivers: DriverRow[];
  /** Indexed to 100. */
  index_series: number[];
  equal_weight_series: number[];
  /** ISO dates. */
  dates: string[];
  /** Cache older than the refresh interval. */
  stale: boolean;
}

// ─────────────────────────── screens ───────────────────────────

export const ScreenName = {
  GAINERS: 'gainers',
  LOSERS: 'losers',
  UNUSUAL_VOLUME: 'unusual_volume',
  NEW_HIGHS: 'new_highs',
  NEW_LOWS: 'new_lows',
  RS_LEADERS: 'rs_leaders',
  GAP_UP: 'gap_up',
  GAP_DOWN: 'gap_down',
  EARNINGS_MOVERS: 'earnings_movers',
  SQUEEZE: 'squeeze',
  DMA_CROSS: 'dma_cross',
} as const;
export type ScreenName = (typeof ScreenName)[keyof typeof ScreenName];

export const SCREEN_NAMES: ScreenName[] = Object.values(ScreenName);

export interface ScreenResult {
  screen: ScreenName;
  rows: DriverRow[];
  /** If capped, SAY SO — never silent truncation. */
  truncated_at: number | null;
}

// ─────────────────────────── events ───────────────────────────

export const EventClass = {
  EARNINGS: 'earnings',
  PRICE_ANOMALY: 'price_anomaly',
  ANALYST: 'analyst',
  CORPORATE_ACTION: 'corporate_action',
  MACRO: 'macro',
  HEADLINE: 'headline',
} as const;
export type EventClass = (typeof EventClass)[keyof typeof EventClass];

export const Severity = {
  GOOD: 'good',
  NEUTRAL: 'neutral',
  WARNING: 'warning',
  SERIOUS: 'serious',
  CRITICAL: 'critical',
} as const;
export type Severity = (typeof Severity)[keyof typeof Severity];

/** Every event is paired with its price reaction. That pairing is the point. */
export interface MarketEvent {
  /** ISO datetime. */
  ts: string;
  conid: number | null;
  symbol: string | null;
  event_class: EventClass;
  title: string;
  detail: string;
  /** What the price actually did. */
  reaction_pct: number | null;
  /** "Calendar", "Flagged" when not a % move. */
  reaction_label: string | null;
  severity: Severity;
  /** Ranking key — filters out pure noise. */
  moved_price: boolean;
  url: string | null;
}

export type Guidance = 'raised' | 'maintained' | 'cut' | 'none';

export interface EarningsRow {
  conid: number;
  symbol: string;
  /** ISO date. */
  report_date: string;
  days_until: number | null;
  eps_actual: number | null;
  eps_estimate: number | null;
  eps_surprise_pct: number | null;
  revenue_actual: number | null;
  revenue_estimate: number | null;
  guidance: Guidance | null;
  reaction_pct: number | null;
  drift_5d_pct: number | null;
}

// ─────────────────────────── portfolio ───────────────────────────

export const CostBasisStatus = {
  OK: 'ok',
  /** e.g. NAKA: avg 169.65 vs mkt 4.85 */
  UNVERIFIED: 'unverified',
  CORPORATE_ACTION_SUSPECTED: 'corporate_action_suspected',
} as const;
export type CostBasisStatus = (typeof CostBasisStatus)[keyof typeof CostBasisStatus];

export interface Position {
  instrument: Instrument;
  quantity: number;
  avg_cost: number;
  last: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pct: number;
  weight_pct: number;
  day_pnl: number | null;
  contribution_to_day_return: number | null;
  cost_basis_status: CostBasisStatus;
  cost_basis_note: string | null;
}

export interface RiskFlag {
  severity: Severity;
  /** Status colour NEVER carries meaning alone. */
  icon: string;
  title: string;
  detail: string;
  conid: number | null;
}

export interface PortfolioSnapshot {
  /** ISO datetime. */
  as_of: string;
  net_liquidation: number;
  cash: number;
  gross_position_value: number;
  deployed_pct: number;
  leverage: number;
  positions: Position[];
  total_market_value: number;
  total_unrealized_pnl: number;
  day_pnl: number | null;
  beta_vs_index: number | null;
  sector_exposure: Record<string, number>;
  largest_position_pct: number | null;
  flags: RiskFlag[];
  reconciliation: Reconciliation[];
}

// ─────────────────────────── leverage (§2c) ───────────────────────────

export type LeverageRegime = 'trending' | 'choppy' | 'unclear';

/**
 * The module that makes leveraged ETPs legible. Measured, not assumed.
 *
 * Reference values verified against IBKR data on 2026-08-06:
 *   MAG7.L 5x : underlying +14.2%, naive +70.8%, actual +4.0%, beta 4.64,
 *               vol drag 54.5%/yr, max DD -68.7%
 *   SOXL.L 4x : underlying +94.1%, naive +376.3%, actual +419.1%, beta 4.18,
 *               vol drag 61.0%/yr, max DD -72.2%
 */
export interface LeverageAnalysis {
  instrument: Instrument;
  underlying: Instrument;
  window_days: number;

  underlying_return_pct: number;
  /** leverage * underlying_return */
  naive_expected_pct: number;
  actual_return_pct: number;
  /** actual - naive; the decay number. */
  gap_pp: number;

  /** Rolling regression vs underlying. */
  realized_beta: number;
  stated_leverage: number;
  /** realized - stated; tracking degradation. */
  beta_drift: number;

  underlying_vol_annual: number;
  product_vol_annual: number;
  /** 0.5 * L * (L-1) * sigma^2 */
  volatility_drag_annual_pct: number;

  max_drawdown_pct: number;
  underlying_max_drawdown_pct: number;
  pct_from_high: number;
  /** 1/(1-dd) - 1. Not intuitive; show it. */
  recovery_needed_pct: number;

  regime: LeverageRegime;
  regime_note: string;

  /** -20% underlying kills a 5x. */
  single_day_wipeout_pct: number;
  issuer_reset_threshold_pct: number | null;
  /** TER + financing on (L-1). */
  carry_cost_annual_pct: number | null;

  days_held: number | null;
  holding_period_warning: string | null;

  /** Entry-anchored: only when the user holds it. */
  since_entry_gap_pp: number | null;
}

// ─────────────────────────── income sleeve (§2b) ───────────────────────────

export type Liquidity = 'good' | 'moderate' | 'thin';

export interface IncomeRow {
  instrument: Instrument;
  price: number;
  current_yield: number | null;
  yield_on_cost: number | null;
  /** ISO date. */
  ex_div_date: string | null;
  /** ISO date. */
  pay_date: string | null;
  annual_distribution: number | null;
  dividend_growth_5y: number | null;
  consecutive_years: number | null;
  payout_ratio: number | null;
  cash_flow_coverage: number | null;
  // preferred-specific
  /** ISO date. */
  call_date: string | null;
  yield_to_call: number | null;
  par_value: number | null;
  cumulative: boolean | null;
  // risk
  adv_usd_20d: number | null;
  liquidity: Liquidity | null;
  days_to_exit: number | null;
  rate_beta_tnx: number | null;
  pct_from_52w_high: number | null;
  above_200dma: boolean | null;
}

// ─────────────────────────── alerts & journal ───────────────────────────

export type AlertScope = 'portfolio' | 'watchlist' | 'universe';

export interface AlertRule {
  id: string;
  name: string;
  /** "rsi14 < 35 and close > ema200 and rel_volume > 1.5" */
  expression: string;
  scope: AlertScope;
  watchlist_id: string | null;
  enabled: boolean;
}

export interface AlertHit {
  rule_id: string;
  rule_name: string;
  conid: number;
  symbol: string;
  /** ISO datetime. */
  triggered_at: string;
  snapshot: Record<string, number>;
}

export type TradeDirection = 'long' | 'short';

/**
 * Snapshots indicator state at entry so the dashboard can later tell you
 * which of YOUR setups actually work. This is the feature that compounds.
 */
export interface JournalEntry {
  id: string;
  conid: number;
  symbol: string;
  /** ISO datetime. */
  opened_at: string;
  /** ISO datetime. */
  closed_at: string | null;
  direction: TradeDirection;
  entry_price: number;
  exit_price: number | null;
  size: number;
  thesis: string;
  exit_reason: string | null;
  entry_snapshot: Record<string, number>;
  realized_pnl: number | null;
  r_multiple: number | null;
}

// ─────────────────── front-end-only view models ───────────────────
// Not in models.py. These exist because the UI needs shapes the API does not
// (yet) return. Keep them below the contract line so the mirror stays obvious.

/** A watchlist as returned by /api/watchlists. */
export interface Watchlist {
  id: string;
  name: string;
  count: number;
}

/** One row of the §2c ticker-collision table. */
export interface TickerCollision {
  symbol: string;
  conid: number;
  exchange: string;
  country: string;
  description: string;
  /** True for the inverse product — the one that ships with a ⛔ chip. */
  inverse: boolean;
}

/** A ±10% round-trip row on the leverage page. */
export interface RoundTripRow {
  leverage: number;
  underlying_pct: number;
  levered_pct: number;
  note: string | null;
}

/** Indexed series used by the leverage chart: unlevered / naive / actual. */
export interface LeverageSeries {
  weeks: string[];
  underlying: number[];
  naive: number[];
  actual: number[];
}

/** What the leverage endpoint hands the page: analysis + its chart series. */
export interface LeverageView {
  analysis: LeverageAnalysis;
  series: LeverageSeries;
}

/** Deep-dive payload: the indicator set plus the bars the charts need. */
export interface InstrumentDetail {
  instrument: Instrument;
  indicators: IndicatorSet;
  /** ISO dates, aligned with the series below. */
  dates: string[];
  close: number[];
  ema20: number[];
  ema50: number[];
  rsi14: (number | null)[];
  macd_hist: number[];
  volume: number[];
  signals: SignalRow[];
  fundamentals: FundamentalsBlock | null;
  peers: PeerRow[];
  /** How `peers` was chosen — shown as the card caption, never left implicit. */
  peers_basis: string;
}

/** A plain-English signal line with the number beside it. */
export interface SignalRow {
  label: string;
  detail: string;
  severity: Severity;
  chip_icon: string;
  chip_label: string;
}

export interface FundamentalsBlock {
  forward_pe: number | null;
  eps_growth_pct: number | null;
  revenue_growth_pct: number | null;
  next_earnings_date: string | null;
  days_to_earnings: number | null;
  short_interest_pct: number | null;
  days_to_cover: number | null;
  analyst_target: number | null;
  upside_to_target_pct: number | null;
  float_shares: number | null;
}

export interface PeerRow {
  conid: number;
  symbol: string;
  exchange: string;
  last: number;
  return_13w: number;
  rs_vs_index_13w: number;
  rsi14: number | null;
  atr_pct: number | null;
  setup_score: number | null;
}
