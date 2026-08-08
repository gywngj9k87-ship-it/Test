"""Swing / income / leverage dashboard — Python service layer.

Module map (see CLAUDE.md and the design spec):

    config.py       settings + the static universe/routing tables   [contract]
    models.py       the API contract shared with the front end      [contract]
    cache.py        DuckDB cache                                    [other agent]
    sources/        ibkr / yahoo / finnhub / reconcile              [other agent]
    indicators/     the pandas indicator engine                     [other agent]

    deps.py         wiring — one place that builds sources + cache
    universe.py     layers 0-4 and the eleven daily screens
    breadth.py      the market breadth snapshot
    events.py       the event tape
    portfolio.py    positions, cost-basis reconciliation, risk flags
    leverage.py     the §2c leveraged-ETP module
    income.py       the §2b income sleeve
    jobs.py         APScheduler nightly refresh + intraday polling
    main.py         FastAPI app; every read path is cache-served
"""

__version__ = "0.3.0"
