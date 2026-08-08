# Swing · Income · Leverage Dashboard

A US-and-global equity dashboard built around one person's actual book rather
than a generic index screen. Three instrument classes, three sets of metrics:

- **Swing** (days–weeks) — trend, momentum, volatility, volume, levels, and a
  relative-strength-weighted setup score.
- **Income** — the ~100-name shipping/preferreds/ADR sleeve, where yield,
  coverage, call risk and liquidity replace RSI and MACD.
- **Leverage** — the 4× and 5× LSE ETPs, where decay, effective leverage,
  carry and distance-to-impairment are the whole story.

Data comes from IBKR (primary — prices, history, positions, watchlists, and the
only source covering the London/Frankfurt/Seoul/Tokyo listings) cross-checked
against Yahoo, with Finnhub for headlines. **Read-only: there is no
order-placement code in this repository.**

Your IBKR watchlists are the configuration. Edit them in IBKR; the dashboard
follows.

## Quick start

    cd backend && pip install -r requirements.txt && pytest -q && uvicorn app.main:app --port 8000
    cd frontend && npm install && npm run dev

Front end runs on mock data with no backend. See `CLAUDE.md` for the build
instructions, the non-negotiable design rules, and the open work list;
`docs/spec-v0.3.md` for the design rationale; `docs/approved-mockup.html` for
the signed-off visual reference.

Not investment advice. Historical figures are history, not forecast.
