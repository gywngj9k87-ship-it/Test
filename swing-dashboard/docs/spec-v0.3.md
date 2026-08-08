# Swing, Income & Leverage Dashboard — Design Spec v0.3

**For review before any code is written.** *v0.2 rebuilt the spec around live IBKR data; v0.3 adds the leveraged ETP class (§2c).*

| Decision | Locked |
|---|---|
| Data | **Dual-source with cross-checking** — IBKR and Yahoo both pulled, discrepancies flagged |
| IBKR scope | **Read-only.** No order-placement code exists in the repo |
| Stack | Next.js + React front end, Python data service behind it |
| Horizon | Swing trading (days–weeks), with separate income and leveraged sleeves |
| Instrument classes | Equities/ETFs · income & preferreds (§2b) · **leveraged ETPs (§2c)** |
| Universe | **S&P 500 + Nasdaq 100 for context and discovery, PLUS all six IBKR watchlists** |
| News | Finnhub free tier |
| Handoff | Runnable scaffold + `CLAUDE.md` build spec |

### What the IBKR connection revealed

Verified live: account summary, positions, daily OHLCV history, live snapshots (bid/ask, volume, 52w range, historical vol), and all six watchlists.

- **Account**: net liquidation $191,421, of which $185,196 is cash. Gross position value $6,205 — roughly 3% deployed.
- **Holdings**: ACHR, BABA, KKR, NAKA, VOO.
- **Watchlists**: Favorites (56 names), track (100), Watch (19), Hold (18), Buy (10), space tech (5).

The watchlists reshaped the spec. The real interest set spans semiconductors, space tech, alternative asset managers, uranium and nuclear, gold and miners, a large shipping-and-preferreds income cluster, and listings in London, Seoul, Frankfurt and Tokyo. A dashboard scoped to two US indices would have covered a minority of it.

**Open data-quality item:** NAKA shows 34 shares at an average price of $169.65 against a $4.85 market price. Real loss or reverse-split artifact in the cost basis — to be resolved with IBKR's `include_corporate_actions` flag during the build. Portfolio P&L gets a reconciliation step either way rather than trusting the raw field.

---

## 1. Which stocks to monitor

Not a fixed list. Four layers, three of which are static and one recomputed every day.

### Layer 0 — Market context (always on screen)

| Group | Tickers |
|---|---|
| Indices | `^GSPC` S&P 500, `^NDX` Nasdaq 100, `^IXIC` Nasdaq Composite, `^RUT` Russell 2000 |
| Risk / macro | `^VIX` volatility, `^TNX` 10y yield, `DX-Y.NYB` dollar, `CL=F` oil, `GC=F` gold |
| Breadth proxy | `RSP` equal-weight S&P vs `SPY` — the single best "is this rally broad or just 7 stocks" tell |
| Sectors (11 GICS) | `XLK` tech, `XLC` comms, `XLY` cons disc, `XLP` staples, `XLV` health, `XLF` financials, `XLI` industrials, `XLE` energy, `XLB` materials, `XLRE` real estate, `XLU` utilities |

### Layer 1 — Index drivers (the ~20 that *are* the index)

`NVDA MSFT AAPL AMZN GOOGL META AVGO TSLA BRK-B LLY JPM V XOM UNH MA COST NFLX AMD PLTR ORCL`

These carry roughly 40% of S&P 500 weight and over half of the Nasdaq 100. When the index moves and you don't know why, the answer is almost always on this list. Shown as a contribution-to-index-move table, not just a price grid.

### Layer 2 — Sector representatives (3–5 leaders per sector)

So you can see **rotation**, not just megacap tech. Example: financials `JPM GS BAC SCHW`, energy `XOM CVX COP SLB`, industrials `CAT GE HON UNP`, healthcare `LLY UNH JNJ ABBV`, staples `COST WMT PG KO`. Auto-selected as the top N by market cap within each GICS sector from the live universe, so the list maintains itself.

### Layer 3 — Dynamic screens (recomputed daily over all ~520 unique S&P 500 + Nasdaq 100 names)

By **movement**:

- Top 20 gainers / losers on the day
- **Unusual volume** — relative volume > 2× the 20-day average
- New 52-week highs / new 52-week lows (count *and* names — this is a breadth signal in itself)
- **Relative strength leaders** — outperforming SPY over 1m and 3m, the single most useful swing screen
- Gap ups / gap downs > 3% at the open
- Earnings-reaction movers — moved > 5% within two sessions of reporting
- Fresh technical triggers — 50/200 DMA crosses, Bollinger squeeze breakouts, RSI exiting oversold while above the 200 DMA

By **market cap** bucket, as a filter across all of the above: Mega > $200B · Large $10–200B · Mid $2–10B. (Both indices skew large, so mid-cap is thin by construction — worth knowing rather than expecting.)

By **industry**, as a filter using GICS sector and sub-industry.

### Layer 4 — Your book (added in v0.2)

Synced live from IBKR, no manual maintenance:

| Source | Contents | Treatment |
|---|---|---|
| **Positions** | ACHR, BABA, KKR, NAKA, VOO | Full indicator set + risk flags, always visible |
| **Favorites** (56) | Megacaps, semis, alt managers, uranium, miners, foreign listings | Full swing indicator set |
| **Buy** (10) | VOO, AVGO, TSM, MRVL, NFLX, RR., PONY, SK Hynix… | Full set + entry-timing emphasis |
| **Hold** (18) | URA, RIO, MT, BABA, NVDA, MU, AMD, KKR, TSM, SOXL… | Full set + exit/stop emphasis |
| **Watch** (19) | INTC, MU, SNDK, WDC, NEE, LLY, SNPS, GOOG, ARM, DELL… | Full set |
| **space tech** (5) | PL, RKLB, ASTS, LUNR, RDW | Full set + thematic group view |
| **track** (100) | Shipping, preferreds, small-cap ADRs, income names | **Income sleeve** — different metrics, see §2b |

Non-US listings (RR. London, 000660 Seoul, RHM Frankfurt, 9513 Tokyo, EZJ London) are handled through IBKR, which is precisely why IBKR is now a primary source rather than a supplement — Yahoo's coverage of these is inconsistent.

**Design principle:** you never maintain a ticker list by hand. Your IBKR watchlists *are* the configuration — edit them in IBKR and the dashboard follows.

---

## 2. Indicators to visualise

Tuned for a days-to-weeks holding period. Anything that only matters intraday is out; anything that only matters over years is context, not a signal.

### Trend — "which way, and how strongly"

- Price vs **20 / 50 / 200 EMA**, with the stack order flagged (20>50>200 = clean uptrend)
- **50/200 cross** — golden / death cross, with days since
- **ADX(14)** — trend strength. Below 20 means the momentum signals below are noise; this gates the others
- Distance from 52-week high and low, in %
- 20-day linear-regression slope

### Momentum — "is it accelerating or tiring"

- **RSI(14)** — read on two levels: the classic 30/70, and the regime read (in an uptrend RSI holds 40–80; losing 40 is the real warning)
- **MACD (12,26,9)** — line, signal, histogram, plus a cross flag and histogram-divergence detection
- **Stochastic (14,3,3)** — for timing entries within a trend
- Rate of change, 5d and 20d
- **Relative strength vs SPY and vs its own sector ETF** — the indicator most retail dashboards omit and the one that matters most for swing selection. A stock beating its sector which is beating the market is a different animal from one merely going up

### Volatility & risk — "how much room, and what stop"

- **ATR(14)** and ATR as % of price — this drives position sizing and stop placement, not just decoration
- **Bollinger Bands (20,2)** with %B and bandwidth — bandwidth compression flags **squeezes**, which precede the moves swing traders want
- 20-day realised volatility, and beta vs SPY
- Drawdown from the most recent swing high

### Volume & flow — "is the move confirmed"

- **Relative volume** vs 20-day average
- **OBV** trend and divergence from price
- **Anchored VWAP from the last earnings date** — the level institutions actually reference
- Money Flow Index(14)

### Levels

- Auto-detected swing pivot highs/lows → support and resistance bands
- Prior day high / low / close, and today's gap %

### Fundamental context (light — swing horizon, but it explains the moves)

Forward P/E · EPS growth · revenue growth · **next earnings date with a countdown** · short interest and days-to-cover · analyst consensus target vs current price · float.

### Two composites

1. **Swing Setup Score (0–100)** — a weighted blend of trend alignment, momentum, relative strength and volume confirmation. Always displayed with its component breakdown open, so it is never a black box you're asked to trust.
2. **Market Breadth Gauge** — % of S&P 500 above its 50 DMA, advance/decline line, new highs vs new lows, RSP/SPY ratio. Tells you whether *any* long setup is worth taking today.

## 2b. The income sleeve — different job, different metrics

Running RSI and MACD across the "track" list would be false precision. Momentum oscillators on thinly traded preferreds and small-cap shipping ADRs mostly measure the bid-ask spread. That list gets its own view:

- **Yield** — current, and yield on cost if held
- **Ex-dividend date and payment calendar**, with a forward income projection
- **Dividend history** — growth, cuts, consecutive years, payout consistency
- **Coverage** — payout ratio, and for the shipping names, cash-flow coverage of the distribution
- **For preferreds** — call date and call risk, current yield vs yield-to-call, par vs market price, cumulative or non-cumulative
- **Liquidity warning** — average daily dollar volume, flagged where a position could not be exited in a day
- **Distance from 52w range** and simple 200 DMA trend, as the only technicals worth keeping
- **Rate sensitivity** — correlation to `^TNX`, since that is what actually drives preferred prices

## 2c. Leveraged ETPs — a third instrument class (added in v0.3)

### What you actually hold

I resolved the contracts through IBKR. Two of them are not what their tickers suggest:

| In your list | Contract | What it actually is |
|---|---|---|
| MAG7 | 693388390 · LSEETF | **Leverage Shares 5× Long Magnificent 7** — five times, not three |
| SOXL | 693388387 · LSEETF | **Leverage Shares 4× Long Semiconductors** |
| SOXL | 73340487 · ARCA | **Direxion Daily Semiconductor Bull 3×** — a different product, same ticker |
| MAGS | 624756922 · BATS | Roundhill Magnificent Seven — **unleveraged**, long |
| SPCX | 890493863 · NASDAQ | SpaceX Class A — ordinary stock, not an ETP |
| HY9H | 517397504 · FWB | SK Hynix GDR, Frankfurt — ordinary stock |

**Two ticker collisions worth naming.** You hold both a 4× LSE `SOXL` and a 3× US `SOXL` — same four letters, different issuer, different leverage, different currency. And `MAGS` on LSE is *Leverage Shares −3× **Short** Magnificent 7* while `MAGS` on BATS is the unleveraged long you hold. Anyone typing a symbol instead of selecting a contract could end up 3× short the position they meant to buy 1× long.

**Consequence for the build:** every instrument is keyed on `contract_id + exchange`, never on symbol. Symbols are display labels only. The UI shows the exchange badge and the leverage factor next to every ticker.

### What the data shows

Measured over the last twelve months, against unleveraged proxies (MAGS for the basket, SMH for semis):

| | MAG7.L 5× | SOXL.L 4× |
|---|---|---|
| Underlying return | +14.2% | +94.1% |
| Naive expectation (L × underlying) | +70.8% | +376.3% |
| **Actual return** | **+4.0%** | **+419.1%** |
| Gap vs naive | **−66.9 pp** | +42.8 pp |
| Realised beta | 4.64× | 4.18× |
| Annualised volatility | 114.9% | 146.7% |
| Max drawdown | **−68.7%** | **−72.2%** |
| Underlying's max drawdown | −18.4% | −18.1% |
| Currently below 1y high | −35.4% | −68.2% |

This is the whole argument for treating these separately. MAG7.L's underlying rose 14% and the 5× product returned 4% — the compounding drag ate the entire leverage premium and more. SOXL.L did the opposite, beating 4× because semis trended, then gave back 68% of it in seven weeks. Same mechanism, opposite sign: **leverage rewards trend and punishes chop, and neither RSI nor MACD tells you which regime you're in.**

The intuition, from twenty alternating ±10% moves — an underlying that ends down 9.6%:

| Leverage | Underlying | Levered outcome |
|---|---|---|
| 1× | −9.6% | −9.6% |
| 2× | −9.6% | −33.5% |
| 3× | −9.6% | −61.1% |
| 4× | −9.6% | −82.5% |
| **5×** | −9.6% | **−94.4%** |

### The leveraged ETP module

Every leveraged holding gets these on top of the standard technicals:

- **Effective vs stated leverage** — rolling regression of the ETP against its underlying. Drift away from the stated factor means tracking is degrading
- **Decay tracker** — actual return vs naive L × underlying, since your entry date. The single number that answers "is leverage still working for me here"
- **Realised vol of the underlying, and the implied drag** — `0.5 × L × (L−1) × σ²`. At 23% underlying vol, a 5× product bleeds ~55%/yr; at 32% vol, a 4× bleeds ~61%/yr. Shown as a live figure, not a footnote
- **Regime flag** — trending or choppy, from ADX and autocorrelation of the underlying. This is the gate on whether a leveraged position is appropriate at all right now
- **Recovery math** — after MAG7.L's −68.7% you need +220% to break even; after SOXL.L's −72.2% you need +260%. Displayed alongside drawdown, because the asymmetry is not intuitive
- **Distance to impairment** — the single-day underlying move that would take the product to near-zero: −20% for 5×, −25% for 4×, −33% for 3×. Plus the issuer's intraday reset threshold where one applies
- **Total cost of carry** — TER plus financing on the borrowed multiple. A 5× product at ~4% short rates carries roughly 16–18% a year in financing alone before the TER
- **Currency exposure** — LSE and Frankfurt listings, USD- or GBP-denominated, held in a USD account
- **Holding-period alert** — leveraged positions get a "days held" counter and a nudge when a position designed for daily rebalancing has been held for weeks

**Position sizing** uses the ETP's own ATR, never the underlying's. A 1% account risk on a 147%-vol instrument is a very small position, and the dashboard should say so rather than let the standard sizing formula quietly suggest otherwise.

**A note on scope, not advice.** The dashboard's job here is to make the mechanics visible — what leverage is costing, how far from impairment, what recovery requires. Whether these instruments suit your objectives is your call, and the numbers above are history rather than forecast.

---

## 3. News and events on the dashboard

A single chronological "tape", filterable to watchlist-only or portfolio-only. Each item is a card: **timestamp · ticker · event type · one line on what happened · the price/volume reaction · why it matters.**

| # | Event class | What gets published |
|---|---|---|
| 1 | **Earnings** | Upcoming with T-minus countdown · reported: EPS and revenue actual vs consensus, surprise % · guidance raised/cut/maintained · the post-print price reaction · post-earnings drift tracking for 5 sessions |
| 2 | **Price & volume anomalies** | Move greater than 2× ATR · relative volume > 3× · gap > 3% · 52-week high/low break · DMA cross · Bollinger squeeze release |
| 3 | **Analyst actions** | Upgrades, downgrades, price-target changes, initiations — with the size of the target change |
| 4 | **Corporate actions** | Splits, dividend declarations and ex-dates, buyback announcements, M&A, index add/delete |
| 5 | **Macro calendar** | CPI, PCE, FOMC, NFP, PPI, jobless claims — pre-flagged with date and time, since these dominate single-name moves |
| 6 | **Headlines** | Ticker-linked news, ranked by whether the price actually moved on it — the filter that keeps this from becoming noise |

The organising idea: **every event is paired with its price reaction.** A headline with no move is trivia; a 6% move with no headline is the thing you most need to see.

---

## 4. Functionality

**A. Market Overview (home)** — index tiles with intraday sparklines · breadth gauges · sector heatmap ranked by rotation · movers tables (gainers, losers, volume, 52w breaks) · today's event tape · your portfolio's day P&L as a summary strip.

**B. Stock Deep Dive** — click any ticker anywhere and get: candlestick + volume with selectable overlays and multiple timeframes · stacked indicator panels (RSI, MACD, ATR, OBV) · a signal table with plain-English flags · fundamentals block · earnings history with a surprise chart · peer comparison within sub-industry · that ticker's news · the Setup Score with its full breakdown · one-click add to watchlist or portfolio.

**C. Portfolio** — manual entry, CSV import, **and IBKR sync** · positions with cost basis, unrealised P&L, weight, and daily contribution to portfolio return · portfolio-level beta, sector exposure, concentration and a correlation matrix · risk flags: any holding reporting earnings within 7 days, any position over your concentration limit, any stop level breached · optional: watchlist "what if I had bought" shadow tracking.

**D. News & Earnings Feed** — the tape from section 3, as a full page with filters and an earnings calendar view.

**E. Screener & Watchlists** — build filters over any indicator from section 2, save them as named screens, keep multiple watchlists.

**F. Alerts** — a rule builder (e.g. `RSI < 35 AND price > 200 DMA AND relvol > 1.5`), evaluated on each refresh, surfaced in-app with optional email.

**G. Trade journal** *(optional, worth considering)* — log why you entered and exited. It snapshots the indicator state at entry, so after 20 trades the dashboard can tell you which of your own setups actually work. This is the feature that compounds.

### Architecture

```
Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui
   charts: lightweight-charts (price) + Recharts (everything else)
        │  REST / JSON
Python FastAPI service
   ├── sources/ibkr.py     → prices, history, quotes, positions, watchlists  [PRIMARY]
   ├── sources/yahoo.py    → fundamentals, earnings estimates, analyst targets,
   │                          and a second price series for cross-checking
   ├── sources/finnhub.py  → headlines, analyst actions, earnings surprises
   ├── sources/reconcile.py→ dual-source comparison + discrepancy flags
   ├── indicators/         → pandas/numpy engine, unit-tested
   ├── universe.py         → layers 0-4, daily screens
   ├── events.py           → event detection and the tape
   ├── portfolio.py        → positions, P&L reconciliation, risk flags
   ├── income.py           → the §2b sleeve
   └── DuckDB cache        → nightly full refresh + intraday quote polling
```

**On dual-source cross-checking.** Both sources are pulled and compared on close, volume and split-adjustment. Where they disagree beyond a tolerance, the UI shows the value with a discrepancy badge rather than silently picking one. IBKR wins ties for price (it is the execution venue and covers the non-US listings); Yahoo wins for fundamentals. This costs roughly double the fetch volume, which the nightly-batch design absorbs. It is also what will settle the NAKA cost-basis question, and it guards against the class of error where a bad split adjustment silently corrupts every indicator downstream.

Rationale for Python in the data layer: every indicator is a few lines of pandas rather than hand-rolled TypeScript, and the cache means the UI never waits on hundreds of network calls.

---

## Status

Steps 1–4 agreed. All eleven design questions resolved. **Next: step 5 — the build package.**
