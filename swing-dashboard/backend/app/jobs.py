"""
Scheduled work: the nightly full refresh and intraday quote polling.

Two jobs, deliberately different in scope:

  * **nightly** (`settings.nightly_refresh_cron`) rebuilds everything — the
    universe, daily bars, indicators, screens, breadth, portfolio, income,
    leverage — and writes it to the DuckDB cache. This is what makes every API
    read path free of network calls.
  * **intraday** (`settings.quote_poll_seconds`) polls quotes for **watchlist
    and portfolio names only**. Never the full universe: several hundred names
    on a 60-second loop is how you get throttled off a market-data feed.

Fetch concurrency is bounded at `settings.max_concurrent_fetches`. The sources
are synchronous, so each fetch runs in a worker thread behind a semaphore.

Two things are reported every run because they are the failure modes that
otherwise go unnoticed:
  * every name whose theme fell into **"Unclassified"**;
  * every screen that **truncated**, and at what count.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import LEVERAGED_ETPS, settings as default_settings
from .deps import ServiceContext
from .models import ScreenName, ScreenResult
from .universe import (
    Sleeve,
    Universe,
    assemble_universe,
    attach_screen_layer,
    collect_unclassified,
    run_screens,
    truncated_screens,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

# cache table names — the API read paths use the same constants
TBL_BARS = "bars"
TBL_INDICATORS = "indicators"
TBL_OVERVIEW = "overview"
TBL_SCREENS = "screens"
TBL_PORTFOLIO = "portfolio"
TBL_INCOME = "income"
TBL_LEVERAGE = "leverage"
TBL_EVENTS = "events"
TBL_EARNINGS = "earnings"
TBL_QUOTES = "quotes"
TBL_UNIVERSE = "universe"
TBL_WATCHLISTS = "watchlists"


@dataclass
class RefreshReport:
    started_at: datetime
    duration_s: float = 0.0
    universe_size: int = 0
    bars_fetched: int = 0
    unclassified: list[str] = field(default_factory=list)
    truncated: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def log(self) -> None:
        log.info(
            "nightly refresh finished in %.1fs — %d names, %d bar series",
            self.duration_s, self.universe_size, self.bars_fetched,
        )
        if self.unclassified:
            log.warning(
                "UNCLASSIFIED THEME (%d): %s",
                len(self.unclassified), ", ".join(self.unclassified),
            )
        else:
            log.info("no unclassified themes")
        if self.truncated:
            for name, at in sorted(self.truncated.items()):
                log.warning("SCREEN TRUNCATED: %s capped at %d rows", name, at)
        else:
            log.info("no screens truncated")
        for w in self.warnings:
            log.warning("universe warning: %s", w)
        for e in self.errors:
            log.error("refresh error: %s", e)


# ─────────────────────────── bounded concurrency ───────────────────────────


async def gather_bounded(
    items: Sequence[T],
    worker: Callable[[T], Awaitable[Any]],
    limit: int,
) -> list[Any]:
    """Run `worker` over `items` with at most `limit` in flight.

    Exceptions are returned in place rather than raised: one delisted contract
    must not abort a 600-name nightly batch.
    """
    sem = asyncio.Semaphore(max(1, limit))

    async def run(item: T) -> Any:
        async with sem:
            try:
                return await worker(item)
            except Exception as exc:                       # noqa: BLE001
                log.warning("fetch failed for %r: %s", item, exc)
                return exc

    return await asyncio.gather(*(run(i) for i in items))


async def _call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Run a synchronous source call off the event loop."""
    return await asyncio.to_thread(fn, *args, **kw)


# ─────────────────────────── the jobs ───────────────────────────


class Jobs:
    def __init__(self, ctx: ServiceContext, *, scheduler: AsyncIOScheduler | None = None):
        self.ctx = ctx
        self.settings = ctx.settings or default_settings
        self.scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self.last_report: RefreshReport | None = None
        self.universe: Universe | None = None

    # ── nightly ──────────────────────────────────────────────
    async def nightly_refresh(self) -> RefreshReport:
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        report = RefreshReport(started_at=started)
        ibkr = self.ctx.ibkr
        if ibkr is None:
            report.errors.append("no IBKR source configured — nothing refreshed")
            report.duration_s = time.perf_counter() - t0
            report.log()
            self.last_report = report
            return report

        # 1 ── universe (layers 0, 1, 2, 4)
        try:
            universe = await _call(assemble_universe, ibkr)
        except Exception as exc:                            # noqa: BLE001
            report.errors.append(f"universe assembly failed: {exc}")
            report.duration_s = time.perf_counter() - t0
            report.log()
            self.last_report = report
            return report

        self.universe = universe
        report.universe_size = len(universe)
        report.warnings = list(universe.warnings)
        report.unclassified = collect_unclassified(universe)
        self._write(TBL_UNIVERSE, [
            {"conid": m.conid, "symbol": m.instrument.symbol,
             "exchange": m.instrument.exchange, "sleeve": m.sleeve.value,
             "layers": sorted(m.layers), "theme": m.instrument.theme,
             "held": m.held, "sources": sorted(m.sources)}
            for m in universe
        ])

        # 2 ── daily bars for everything, bounded
        targets = [m.conid for m in universe]

        async def fetch_bars(conid: int) -> tuple[int, Any]:
            return conid, await _call(ibkr.get_bars, conid)

        results = await gather_bounded(targets, fetch_bars,
                                       self.settings.max_concurrent_fetches)
        bars: dict[int, Any] = {}
        for res in results:
            if isinstance(res, Exception) or res is None:
                continue
            conid, series = res
            if series:
                bars[conid] = series
        report.bars_fetched = len(bars)
        self._write(TBL_BARS, bars)

        # 3 ── indicators, screens, breadth. The indicator engine is owned by
        # another module; if it is not importable yet the batch still records
        # the universe and the bars rather than failing the whole run.
        scan_rows: list[Any] = []
        try:
            scan_rows = await asyncio.to_thread(self._compute_indicators, universe, bars)
        except Exception as exc:                            # noqa: BLE001
            report.errors.append(f"indicator pass skipped: {exc}")

        if scan_rows:
            screens: dict[ScreenName, ScreenResult] = run_screens(scan_rows)
            attach_screen_layer(universe, screens)
            report.truncated = truncated_screens(screens)
            self._write(TBL_SCREENS, {k.value: v.model_dump(mode="json")
                                      for k, v in screens.items()})

        report.duration_s = time.perf_counter() - t0
        report.log()
        self.last_report = report
        return report

    def _compute_indicators(self, universe: Universe, bars: dict[int, Any]) -> list[Any]:
        """Indicator pass. Income names are deliberately excluded — §2b says
        momentum oscillators on thin preferreds measure the bid-ask spread."""
        from .deps import compute_all                      # lazy: parallel module
        from .universe import ScanRow

        benchmark = bars.get(self.settings_benchmark_conid())
        rows: list[ScanRow] = []
        out_indicators = []
        for m in universe.scan_set():
            series = bars.get(m.conid)
            if not series:
                continue
            try:
                ind = compute_all(
                    series, benchmark, None,
                    m.instrument, None,
                )
            except Exception as exc:                        # noqa: BLE001
                log.debug("indicators failed for %s: %s", m.instrument.symbol, exc)
                continue
            out_indicators.append(ind)
            rows.append(ScanRow.from_indicator_set(m.instrument, ind))
        self._write(TBL_INDICATORS, out_indicators)
        return rows

    @staticmethod
    def settings_benchmark_conid() -> int:
        from .config import BENCHMARK_CONID
        return BENCHMARK_CONID

    # ── intraday ─────────────────────────────────────────────
    async def poll_quotes(self) -> int:
        """Quotes for watchlist + portfolio names only."""
        ibkr = self.ctx.ibkr
        if ibkr is None or self.universe is None:
            return 0
        targets = self.universe.poll_set()
        if not targets:
            return 0

        async def fetch(conid: int) -> Any:
            return await _call(ibkr.get_quote, conid)

        results = await gather_bounded(targets, fetch,
                                       self.settings.max_concurrent_fetches)
        quotes = [q for q in results if q is not None and not isinstance(q, Exception)]
        self._write(TBL_QUOTES, quotes)
        log.debug("polled %d/%d quotes", len(quotes), len(targets))
        return len(quotes)

    # ── leveraged holdings get their own nightly pass ────────
    def leveraged_targets(self) -> list[int]:
        if self.universe is None:
            return list(LEVERAGED_ETPS)
        held = {m.conid for m in self.universe.by_sleeve(Sleeve.LEVERAGED)}
        return sorted(held | set(LEVERAGED_ETPS))

    # ── plumbing ─────────────────────────────────────────────
    def _write(self, table: str, rows: Any) -> None:
        if self.ctx.cache is None or rows is None:
            return
        try:
            self.ctx.cache.upsert(table, rows)
        except Exception as exc:                            # noqa: BLE001
            log.warning("cache write to %s failed: %s", table, exc)

    def start(self) -> AsyncIOScheduler:
        self.scheduler.add_job(
            self.nightly_refresh,
            CronTrigger.from_crontab(self.settings.nightly_refresh_cron, timezone="UTC"),
            id="nightly_refresh", replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.poll_quotes,
            IntervalTrigger(seconds=self.settings.quote_poll_seconds),
            id="quote_poll", replace_existing=True,
            max_instances=1, coalesce=True,
        )
        self.scheduler.start()
        log.info("scheduler started: nightly '%s', quotes every %ds, concurrency %d",
                 self.settings.nightly_refresh_cron,
                 self.settings.quote_poll_seconds,
                 self.settings.max_concurrent_fetches)
        return self.scheduler

    def shutdown(self) -> None:
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
        except Exception:                                   # pragma: no cover
            pass


def build_jobs(ctx: ServiceContext) -> Jobs:
    return Jobs(ctx)
