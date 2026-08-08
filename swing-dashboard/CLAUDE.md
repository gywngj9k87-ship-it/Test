# CLAUDE.md — build instructions for Claude Code

You are finishing a stock dashboard for a single user (Sharad, Dubai, UTC+4). The
design is settled and written down; most of the backend is written and tested.
**Read this file before touching anything.** The two documents that govern the
build are this file and `docs/spec-v0.3.md`.

---

## What already works — do not rewrite it

```
backend/   246 tests passing.  Run: cd backend && pytest -q
frontend/  next build clean, tsc --noEmit clean, all 6 routes render on mock data.
```

| Layer | State |
|---|---|
| `app/models.py` | **The contract.** Frozen. Changing a shape here means regenerating `frontend/lib/types.ts`. |
| `app/config.py` | Universe, watchlist routing, leveraged-ETP registry, themes, score weights. |
| `app/indicators/` | Trend, momentum, volatility, volume, levels, setup score, engine. Math verified against hand-computed references. |
| `app/sources/` | IBKR (primary), Yahoo (secondary), Finnhub, reconciliation, DuckDB cache. Unit-tested against fixtures — **never integration-tested against a live endpoint.** |
| `app/leverage.py` | §2c. Reproduces measured reference values to within 0.2. |
| `app/{universe,breadth,portfolio,income,events,jobs,main}.py` | Service layer + FastAPI routes. |
| `frontend/` | All pages render from `lib/mock.ts` with no backend running. |

---

## The five rules that are not negotiable

These came out of real defects found while designing this. Breaking one silently
produces a dashboard that lies.

**1. Identity is `(conid, exchange)`. Never the symbol.**
`SOXL` is a Leverage Shares 4× LSE ETP *and* a Direxion 3× US ETF — the user
holds both in one watchlist. `MAGS` is an unleveraged US long *and* a Leverage
Shares −3× LSE inverse. Any code path that looks up an instrument by ticker is a
bug. The UI shows the exchange badge and leverage factor next to every ticker.

**2. No dual-axis charts, ever.**
Two measures of different scale get indexed to a common base on one axis, or a
log scale. The leverage charts span 17× and must stay log. This is the single
fastest way to make a chart lie and it is already handled in
`components/LineChart.tsx` — read the header block there.

**3. Sources are cross-checked, never silently resolved.**
Where IBKR and Yahoo disagree beyond tolerance the value ships **with** a
breached `Reconciliation` attached and the UI renders a badge. IBKR wins ties on
price (execution venue, and the only source that covers the LSE/Frankfurt/Seoul/
Tokyo listings). Yahoo wins on fundamentals.

**4. Status colour never carries meaning alone.**
Every `RiskFlag` and status chip ships an icon *and* a label. Three of the light-
mode series colours sit below 3:1 contrast, so charts also need direct labels or
the table view — every chart has a table-view twin already.

**5. Truncation is always reported.**
`ScreenResult.truncated_at` is set whenever a screen caps its rows. A silently
short list reads as "nothing else qualified," which is a different claim.

---

## Getting it running

```bash
# 1. IB Gateway (read-only). Live 4001 / paper 4002. Enable the API,
#    add 127.0.0.1 to trusted IPs, and tick Read-Only API.
# 2. Client Portal Gateway on :5000 — REQUIRED for watchlists. See "Watchlists" below.

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env      # add FINNHUB_API_KEY
pytest -q                    # expect 246 passed
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                  # http://localhost:3000
```

---

## Known gaps — this is your work list, in priority order

### P0 — blocking a first real run

**1. Watchlists need a second daemon, and that decision is unmade.**
IBKR watchlists **do not exist in the TWS socket API.** They are only in the
Client Portal Web API (`GET /iserver/watchlists`), which means running CP Gateway
on :5000 alongside IB Gateway. `sources/ibkr.py` has a separate GET-only
`WatchlistClient` for this that degrades to `[]`.
*Ask the user before building around it.* The alternatives are: run both
daemons; or drop watchlist sync and define the universe in `config.py` by hand,
which breaks the "your watchlists are the configuration" principle the whole
design rests on.

**2. Nothing has ever touched a live IBKR socket.** The sandbox had no route to
it. Expect the first connection to surface method-signature drift — the agent
that wrote `sources/ibkr.py` already found that `positionsAsync` and
`reqMktDataAsync` do not exist in `ib_async` 2.1.0 (`reqPositionsAsync` and
`reqTickersAsync` do) and wrote fallbacks. Run against **paper (port 4002)
first**.

**3. IBKR volume units are unverified.** IBKR reports some US equity volume in
100-share lots where Yahoo reports shares. No multiplier was applied on purpose —
a wrong guess silently corrupts every relative-volume signal. The 5% volume
tolerance will surface a 100× mismatch as a breached `Reconciliation` on the
first run. **Confirm against live data, then fix once, in `sources/ibkr.py`.**

### P1 — makes the dashboard true rather than illustrative

**4. Breadth runs over 16 names, not ~520.** Wire `jobs.py`'s nightly refresh to
the full S&P 500 + Nasdaq 100 constituent list so "62% above the 50-day average"
becomes a real breadth reading rather than a large-cap sample. Constituents are
not in IBKR — scrape them once and cache, or hard-code with a dated comment.

**5. The event tape is placeholder.** `events.py` has the detection logic and the
taxonomy; it needs the Finnhub key wired and the price-anomaly detectors pointed
at real bars. Keep the ranking rule: `moved_price` sorts headlines with no price
reaction to the bottom.

**6. The income sleeve metrics are illustrative.** Real tickers from the `track`
watchlist, invented yields. Needs Yahoo dividend history and, for the preferreds,
call dates and par values — which Yahoo covers badly. Expect to hand-maintain a
small table for the preferred terms.

**7. Resolve and verify the fifth leveraged ETP.** `config.LEVERAGED_ETPS` conid
`693388345` (MAGS LSE −3× inverse) is the one row not confirmed by contract
search. Verify it on boot; if wrong, the collision warning points at the wrong
product, which is worse than not showing it.

### P2 — designed but not built

**8. The global filter row is wired but not honoured.** Scope / watchlist / range
live in `useFilters()` context and no page reads them yet — it needs backend
query params. This is a context read away, not a rewrite.

**9. Alerts and the trade journal have types and routes, no UI.**
`AlertRule`, `AlertHit`, `JournalEntry` are in the contract; `/api/alerts/rules`
and `/api/journal` exist. The journal is the feature that compounds — it
snapshots indicator state at entry so that after ~20 trades the dashboard can
tell the user which of *their own* setups actually work. Worth building early
even though it looks like the least urgent thing here.

**10. Two front-end routes call endpoints that may not exist:**
`/api/leverage/round-trip` and `/api/leverage/collisions`. Either add them to
`main.py` or fold them into `/api/leverage` and fix `lib/api.ts`. Two lines
either way.

---

## Open decisions — ask, do not guess

- **`recovery_needed_pct` is computed from max drawdown**, matching the spec
  (−68.7% → +220%). The mockup showed recovery from the *current* level, a
  different number. Both are defensible; the user has not chosen.
- **NAKA's P&L is excluded from the portfolio total** while its per-line number
  still shows, because the cost basis is unverified (34 shares, avg $169.65,
  market $4.85 — genuine −97% or a reverse-split artifact). The spec said
  reconcile before trusting P&L; excluding it is one interpretation. One line in
  `portfolio.build_snapshot` if the user wants it included.
- **Concentration is measured against deployed capital, not net liquidation.**
  KKR is 49% of $6,205 deployed → fires at `serious`. Against $191k net liq it
  would be 1.6% and never fire. Given the book is ~97% cash this matters a lot
  and the user should confirm which they mean.
- **`include_corporate_actions` does not exist in the TWS API.** The spec assumed
  it would settle the NAKA question. It is a Client Portal / Flex concept. The
  substitute in `sources/reconcile.py` infers from price history: if the stock
  ever traded near $169.65 the loss is genuine; if the whole series sits under
  ~$12 it is a suspected corporate action; with no history it stays `UNVERIFIED`
  rather than guessing.

---

## House style

- Python: type hints everywhere, pydantic v2, no bare `dict` in a response model.
- Tests assert *values*, not that code ran. The leverage regression test in
  `tests/test_services.py` is the model to copy.
- Comments explain **why**, especially where a convention is load-bearing —
  simple vs log returns, `ddof=0` vs `ddof=1`, which denominator. Several
  reference numbers only reproduce under one choice.
- When you cap, sample, or skip something, log it. The nightly job already logs
  every unclassified theme and every truncated screen.
- This repo is **read-only against IBKR**. There is no order-placement code in
  it and there should never be. `settings.ibkr_readonly` is checked at connect
  time and `sources/ibkr.py` refuses to connect if it is flipped false.
