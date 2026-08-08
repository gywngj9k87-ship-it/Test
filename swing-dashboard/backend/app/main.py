"""
The FastAPI app.

Two rules hold across every route in this file:

  1. **Response models come from `models.py`.** No ad-hoc dicts, because
     `frontend/lib/types.ts` is generated from that contract and an untyped
     response here becomes an `any` there.
  2. **Read paths never block on the network.** Every GET is served out of the
     DuckDB cache that the nightly job fills. When the cached data is older
     than its refresh interval the response is still returned — marked stale,
     via `MarketOverview.stale` where the model has the field and via the
     `X-Cache-Stale` / `X-Cache-As-Of` headers everywhere else. A slow IBKR
     gateway must never turn into a slow dashboard.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, TypeVar

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import jobs as jobs_module
from .config import LEVERAGED_ETPS, settings
from .deps import ServiceContext, build_context, get_context, set_context
from .models import (
    AlertHit,
    AlertRule,
    Bar,
    EarningsRow,
    EventClass,
    IncomeRow,
    IndicatorSet,
    Instrument,
    JournalEntry,
    JournalStats,
    LeverageAnalysis,
    MarketEvent,
    MarketOverview,
    PortfolioSnapshot,
    RoundTripRow,
    ScreenName,
    ScreenResult,
    TickerCollision,
)
from . import journal as journal_module
from . import leverage as leverage_module
from .portfolio import empty_snapshot

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


# ─────────────────────────── cache plumbing ───────────────────────────


def _rows(ctx: ServiceContext, table: str, **filters: Any) -> Any:
    """Read from the cache. Never raises, never fetches."""
    if ctx.cache is None:
        return None
    try:
        return ctx.cache.read(table, **filters)
    except Exception as exc:                                # noqa: BLE001
        log.warning("cache read %s%s failed: %s", table, filters or "", exc)
        return None


def _stale(ctx: ServiceContext, table: str, payload: Any = None,
           key: str | int | None = None, kind: str = "daily") -> bool:
    if payload is None:
        return True
    if ctx.cache is not None:
        try:
            return bool(ctx.cache.is_stale(
                table, key, ctx.refresh_interval_seconds(kind)))
        except Exception:                                   # noqa: BLE001
            pass
    return ctx.is_stale(_as_of_of(payload), kind)


def _as_of_of(payload: Any) -> datetime | date | None:
    if isinstance(payload, Mapping):
        v = payload.get("as_of") or payload.get("ts")
    else:
        v = getattr(payload, "as_of", None) or getattr(payload, "ts", None)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return v


def _mark(response: Response, stale: bool, payload: Any = None) -> None:
    response.headers["X-Cache-Stale"] = "true" if stale else "false"
    as_of = _as_of_of(payload)
    if as_of is not None:
        response.headers["X-Cache-As-Of"] = str(as_of)


def _coerce_many(model: type[M], rows: Any) -> list[M]:
    """Cache rows -> contract models. Rows that do not validate are dropped
    with a warning rather than crashing a page."""
    if rows is None:
        return []
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    out: list[M] = []
    for r in rows if isinstance(rows, (list, tuple)) else [rows]:
        try:
            out.append(r if isinstance(r, model) else model.model_validate(r))
        except Exception as exc:                            # noqa: BLE001
            log.warning("dropping malformed %s row: %s", model.__name__, exc)
    return out


def _coerce_one(model: type[M], row: Any) -> M | None:
    if row is None:
        return None
    if isinstance(row, (list, tuple)):
        row = row[0] if row else None
        if row is None:
            return None
    try:
        return row if isinstance(row, model) else model.model_validate(row)
    except Exception as exc:                                # noqa: BLE001
        log.warning("malformed %s row: %s", model.__name__, exc)
        return None


def _empty_overview(stale: bool = True) -> MarketOverview:
    from .models import BreadthSnapshot
    return MarketOverview(
        as_of=datetime.now(timezone.utc),
        tiles=[], themes=[], drivers=[],
        breadth=BreadthSnapshot(
            universe_size=0, above_50dma=0, above_50dma_pct=0.0, advancers=0,
            decliners=0, new_highs_52w=0, new_lows_52w=0, median_return_4w=0.0,
            index_return_13w=0.0, equal_weight_return_13w=0.0, spread_13w=0.0,
            verdict="mixed",
        ),
        index_series=[], equal_weight_series=[], dates=[], stale=stale,
    )


# ─────────────────────────── app ───────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = build_context()
    set_context(ctx)
    jobs = jobs_module.build_jobs(ctx)
    app.state.ctx = ctx
    app.state.jobs = jobs
    try:
        jobs.start()
    except Exception as exc:                                # noqa: BLE001
        log.warning("scheduler did not start: %s", exc)
    try:
        yield
    finally:
        jobs.shutdown()


app = FastAPI(
    title="Swing, Income & Leverage Dashboard",
    version="0.3.0",
    description=(
        "Read-only market service. Every instrument is keyed on "
        "(conid, exchange); symbols are display labels only."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Cache-Stale", "X-Cache-As-Of"],
)


# ─────────────────────────── routes ───────────────────────────


@app.get("/api/overview", response_model=MarketOverview)
def get_overview(response: Response, ctx: ServiceContext = Depends(get_context)) -> MarketOverview:
    """Index tiles, breadth, themes, drivers and the index vs equal-weight chart."""
    raw = _rows(ctx, jobs_module.TBL_OVERVIEW)
    overview = _coerce_one(MarketOverview, raw)
    if overview is None:
        _mark(response, True)
        return _empty_overview()
    overview.stale = _stale(ctx, jobs_module.TBL_OVERVIEW, raw)
    _mark(response, overview.stale, overview)
    return overview


@app.get("/api/screens/{screen}", response_model=ScreenResult)
def get_screen(screen: ScreenName, response: Response,
               ctx: ServiceContext = Depends(get_context)) -> ScreenResult:
    """One of the eleven daily screens. `truncated_at` is populated whenever
    the screen capped its output — never silent truncation."""
    raw = _rows(ctx, jobs_module.TBL_SCREENS, screen=screen.value)
    if isinstance(raw, Mapping) and screen.value in raw:
        raw = raw[screen.value]
    result = _coerce_one(ScreenResult, raw)
    _mark(response, _stale(ctx, jobs_module.TBL_SCREENS, raw, screen.value), raw)
    return result or ScreenResult(screen=screen, rows=[], truncated_at=None)


@app.get("/api/instrument/{conid}", response_model=IndicatorSet)
def get_instrument(conid: int, response: Response,
                   ctx: ServiceContext = Depends(get_context)) -> IndicatorSet:
    """The full indicator set for one contract. Keyed on conid: SOXL is a 4x
    LSE ETP *and* a 3x US ETF, so a symbol lookup here would be a bug."""
    raw = _rows(ctx, jobs_module.TBL_INDICATORS, conid=conid)
    ind = _coerce_one(IndicatorSet, raw)
    if ind is None:
        raise HTTPException(404, f"no cached indicators for conid {conid}")
    _mark(response, _stale(ctx, jobs_module.TBL_INDICATORS, raw, conid), ind)
    return ind


@app.get("/api/instrument/{conid}/bars", response_model=list[Bar])
def get_bars(conid: int, response: Response,
             limit: int = Query(500, ge=1, le=5000),
             ctx: ServiceContext = Depends(get_context)) -> list[Bar]:
    raw = _rows(ctx, jobs_module.TBL_BARS, conid=conid)
    if isinstance(raw, Mapping) and conid in raw:
        raw = raw[conid]
    bars = _coerce_many(Bar, raw)
    if not bars:
        raise HTTPException(404, f"no cached bars for conid {conid}")
    _mark(response, _stale(ctx, jobs_module.TBL_BARS, raw, conid), None)
    return bars[-limit:]


@app.get("/api/portfolio", response_model=PortfolioSnapshot)
def get_portfolio(response: Response,
                  ctx: ServiceContext = Depends(get_context)) -> PortfolioSnapshot:
    """Positions, reconciled cost basis and risk flags. Every flag carries an
    icon as well as a severity — colour never carries meaning alone."""
    raw = _rows(ctx, jobs_module.TBL_PORTFOLIO)
    snap = _coerce_one(PortfolioSnapshot, raw)
    _mark(response, _stale(ctx, jobs_module.TBL_PORTFOLIO, raw, kind="quote"), raw)
    return snap or empty_snapshot()


@app.get("/api/leverage", response_model=list[LeverageAnalysis])
def get_leverage(response: Response,
                 ctx: ServiceContext = Depends(get_context)) -> list[LeverageAnalysis]:
    """§2c for every leveraged ETP in the registry or the book."""
    raw = _rows(ctx, jobs_module.TBL_LEVERAGE)
    rows = _coerce_many(LeverageAnalysis, raw)
    _mark(response, _stale(ctx, jobs_module.TBL_LEVERAGE, raw), None)
    return rows


@app.get("/api/leverage/round-trip", response_model=list[RoundTripRow])
def get_round_trip() -> list[RoundTripRow]:
    """The ±10% alternating-move table. Pure math (a compounding identity),
    so it is computed on demand rather than served from the nightly cache —
    declared before `/{conid}` so the literal path is not read as a conid."""
    return leverage_module.round_trip_table()


@app.get("/api/leverage/collisions", response_model=list[TickerCollision])
def get_collisions() -> list[TickerCollision]:
    """Every contract behind a symbol that resolves to more than one
    instrument (rule #1). Derived from config, not the cache."""
    return leverage_module.ticker_collisions()


@app.get("/api/leverage/{conid}", response_model=LeverageAnalysis)
def get_leverage_one(conid: int, response: Response,
                     ctx: ServiceContext = Depends(get_context)) -> LeverageAnalysis:
    raw = _rows(ctx, jobs_module.TBL_LEVERAGE, conid=conid)
    analysis = _coerce_one(LeverageAnalysis, raw)
    if analysis is None:
        for row in _coerce_many(LeverageAnalysis, _rows(ctx, jobs_module.TBL_LEVERAGE)):
            if row.instrument.conid == conid:
                analysis = row
                break
    if analysis is None:
        known = conid in LEVERAGED_ETPS
        raise HTTPException(
            404,
            f"no leverage analysis cached for conid {conid}"
            + ("" if known else
               " — and it is not in config.LEVERAGED_ETPS, so its leverage "
               "factor is unknown (IBKR does not expose it)"),
        )
    _mark(response, _stale(ctx, jobs_module.TBL_LEVERAGE, raw, conid), None)
    return analysis


@app.get("/api/income", response_model=list[IncomeRow])
def get_income(response: Response,
               ctx: ServiceContext = Depends(get_context)) -> list[IncomeRow]:
    """§2b. Yield, coverage, calendar, liquidity, rate beta — and deliberately
    no momentum oscillators."""
    raw = _rows(ctx, jobs_module.TBL_INCOME)
    rows = _coerce_many(IncomeRow, raw)
    _mark(response, _stale(ctx, jobs_module.TBL_INCOME, raw), None)
    return rows


@app.get("/api/events", response_model=list[MarketEvent])
def get_events(
    response: Response,
    event_class: EventClass | None = Query(None),
    conid: int | None = Query(None),
    moved_only: bool = Query(False, description="drop events with no price reaction"),
    limit: int = Query(200, ge=1, le=2000),
    ctx: ServiceContext = Depends(get_context),
) -> list[MarketEvent]:
    """The tape. Already ranked by `moved_price` then reaction size, so a
    headline that moved nothing is at the bottom by construction."""
    raw = _rows(ctx, jobs_module.TBL_EVENTS)
    events = _coerce_many(MarketEvent, raw)
    if event_class is not None:
        events = [e for e in events if e.event_class == event_class]
    if conid is not None:
        events = [e for e in events if e.conid == conid]
    if moved_only:
        events = [e for e in events if e.moved_price]
    _mark(response, _stale(ctx, jobs_module.TBL_EVENTS, raw, kind="quote"), None)
    return events[:limit]


@app.get("/api/earnings", response_model=list[EarningsRow])
def get_earnings(
    response: Response,
    days: int = Query(30, ge=1, le=180),
    conid: int | None = Query(None),
    ctx: ServiceContext = Depends(get_context),
) -> list[EarningsRow]:
    raw = _rows(ctx, jobs_module.TBL_EARNINGS)
    rows = _coerce_many(EarningsRow, raw)
    if conid is not None:
        rows = [r for r in rows if r.conid == conid]
    rows = [r for r in rows if r.days_until is None or abs(r.days_until) <= days]
    rows.sort(key=lambda r: (r.days_until is None, r.days_until or 0))
    _mark(response, _stale(ctx, jobs_module.TBL_EARNINGS, raw), None)
    return rows


@app.get("/api/watchlists", response_model=dict[str, list[Instrument]])
def get_watchlists(response: Response,
                   ctx: ServiceContext = Depends(get_context)
                   ) -> dict[str, list[Instrument]]:
    """The six IBKR watchlists, keyed by watchlist id. These *are* the
    configuration — edit them in IBKR and the dashboard follows."""
    raw = _rows(ctx, jobs_module.TBL_WATCHLISTS)
    out: dict[str, list[Instrument]] = {}
    if isinstance(raw, Mapping):
        for wid, members in raw.items():
            out[str(wid)] = _coerce_many(Instrument, members)
    _mark(response, _stale(ctx, jobs_module.TBL_WATCHLISTS, raw), None)
    return out


@app.get("/api/alerts", response_model=list[AlertHit])
def get_alerts(response: Response, rule_id: str | None = Query(None),
               ctx: ServiceContext = Depends(get_context)) -> list[AlertHit]:
    raw = _rows(ctx, "alert_hits")
    hits = _coerce_many(AlertHit, raw)
    if rule_id:
        hits = [h for h in hits if h.rule_id == rule_id]
    hits.sort(key=lambda h: h.triggered_at, reverse=True)
    _mark(response, _stale(ctx, "alert_hits", raw, kind="quote"), None)
    return hits


@app.get("/api/alerts/rules", response_model=list[AlertRule])
def get_alert_rules(ctx: ServiceContext = Depends(get_context)) -> list[AlertRule]:
    return _coerce_many(AlertRule, _rows(ctx, "alert_rules"))


@app.post("/api/alerts/rules", response_model=AlertRule)
def put_alert_rule(rule: AlertRule,
                   ctx: ServiceContext = Depends(get_context)) -> AlertRule:
    if ctx.cache is None:
        raise HTTPException(503, "cache unavailable — cannot persist the rule")
    ctx.cache.upsert("alert_rules", [rule.model_dump(mode="json")])
    return rule


@app.get("/api/journal", response_model=list[JournalEntry])
def get_journal(response: Response, conid: int | None = Query(None),
                ctx: ServiceContext = Depends(get_context)) -> list[JournalEntry]:
    """Entries snapshot indicator state at entry, so after twenty trades this
    can tell you which of *your* setups actually work."""
    raw = _rows(ctx, "journal")
    rows = _coerce_many(JournalEntry, raw)
    if conid is not None:
        rows = [r for r in rows if r.conid == conid]
    rows.sort(key=lambda r: r.opened_at, reverse=True)
    _mark(response, False, None)
    return rows


@app.get("/api/journal/stats", response_model=JournalStats)
def get_journal_stats(ctx: ServiceContext = Depends(get_context)) -> JournalStats:
    """Which of the user's own setups actually work: closed-trade performance
    grouped by the app's setup score at entry. Derived from the journal rows,
    not a separate feed — declared before nothing that could shadow it, but
    kept a literal path so it never reads as a journal id."""
    entries = _coerce_many(JournalEntry, _rows(ctx, "journal"))
    return journal_module.summarize(entries)


@app.post("/api/journal", response_model=JournalEntry)
def put_journal(entry: JournalEntry,
                ctx: ServiceContext = Depends(get_context)) -> JournalEntry:
    if ctx.cache is None:
        raise HTTPException(503, "cache unavailable — cannot persist the entry")
    ctx.cache.upsert("journal", [entry.model_dump(mode="json")])
    return entry


@app.get("/api/health")
def health(ctx: ServiceContext = Depends(get_context)) -> dict[str, Any]:
    """Deliberately not a contract model — the front end does not render it.

    Reports what is wired and how stale the two write paths are, which is what
    you actually want at 07:00 when the overview looks wrong.
    """
    last = getattr(getattr(app.state, "jobs", None), "last_report", None)
    return {
        "status": "ok",
        "version": app.version,
        "sources": {
            "ibkr": ctx.ibkr is not None,
            "yahoo": ctx.yahoo is not None,
            "finnhub": ctx.finnhub is not None,
            "cache": ctx.cache is not None,
        },
        "ibkr_readonly": settings.ibkr_readonly,
        "nightly_cron": settings.nightly_refresh_cron,
        "quote_poll_seconds": settings.quote_poll_seconds,
        "last_refresh": None if last is None else {
            "started_at": last.started_at.isoformat(),
            "duration_s": round(last.duration_s, 2),
            "universe_size": last.universe_size,
            "unclassified": last.unclassified,
            "truncated_screens": last.truncated,
            "errors": last.errors,
        },
        "stale": {
            "overview": _stale(ctx, jobs_module.TBL_OVERVIEW,
                               _rows(ctx, jobs_module.TBL_OVERVIEW)),
            "portfolio": _stale(ctx, jobs_module.TBL_PORTFOLIO,
                                _rows(ctx, jobs_module.TBL_PORTFOLIO), kind="quote"),
        },
    }


def create_app() -> FastAPI:
    return app
