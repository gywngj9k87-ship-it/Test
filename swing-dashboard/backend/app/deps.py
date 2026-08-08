"""
Wiring. The single place that knows how to build the cache and the sources.

Everything else in the service layer takes a `ServiceContext` (or the pieces of
one) as an argument, which is what makes the whole layer testable with fakes —
`tests/test_services.py` builds a context out of stub objects and never touches
a socket.

Import rule: the concrete `app.sources.*` / `app.cache` modules are imported
*lazily*, inside `build_context()`. They are owned by other agents and are being
written in parallel; the pure-computation modules (leverage, breadth, ...) must
stay importable and testable without them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from .config import Settings, settings

log = logging.getLogger(__name__)


# ─────────────────────────── structural types ───────────────────────────
# Written as Protocols so the tests (and the type checker) can substitute
# anything with the right shape. No inheritance required.


@runtime_checkable
class CacheLike(Protocol):
    def upsert(self, table: str, rows: Any) -> None: ...
    def read(self, table: str, **filters: Any) -> Any: ...
    def is_stale(self, table: str, key: str | int | None = None,
                 max_age_seconds: int | None = None) -> bool: ...


@runtime_checkable
class IBKRLike(Protocol):
    def get_bars(self, conid: int, duration: str = ..., bar_size: str = ...) -> Any: ...
    def get_quote(self, conid: int) -> Any: ...
    def resolve(self, symbol: str, exchange: str | None = ...) -> Any: ...
    def get_positions(self) -> Any: ...
    def get_account_summary(self) -> Any: ...
    def get_watchlists(self) -> Any: ...
    def get_watchlist(self, watchlist_id: str) -> Any: ...


@runtime_checkable
class YahooLike(Protocol):
    def get_bars(self, symbol: str, **kw: Any) -> Any: ...


@runtime_checkable
class FinnhubLike(Protocol):
    def get_news(self, symbol: str, **kw: Any) -> Any: ...


# ─────────────────────────── the context ───────────────────────────


@dataclass
class ServiceContext:
    """Everything a service function needs, in one object."""
    cache: CacheLike | None = None
    ibkr: IBKRLike | None = None
    yahoo: YahooLike | None = None
    finnhub: FinnhubLike | None = None
    settings: Settings = field(default_factory=lambda: settings)

    # ── staleness ──────────────────────────────────────────────
    # Read paths NEVER block on the network. They serve whatever the cache has
    # and mark `stale=True` when it is older than the relevant refresh interval.

    def refresh_interval_seconds(self, kind: str = "quote") -> int:
        if kind == "quote":
            return self.settings.quote_poll_seconds
        # everything else is refreshed by the nightly batch
        return 26 * 3600

    def is_stale(self, as_of: datetime | date | None, kind: str = "quote") -> bool:
        if as_of is None:
            return True
        if isinstance(as_of, datetime):
            ts = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        else:
            ts = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        return age > timedelta(seconds=self.refresh_interval_seconds(kind))


_context: ServiceContext | None = None


def build_context(*, connect: bool = True) -> ServiceContext:
    """Construct the real context. Lazy imports on purpose — see module docstring."""
    cache = ibkr = yahoo = finnhub = None

    try:
        from .cache import Cache  # type: ignore
        cache = Cache(settings.duckdb_path)
    except Exception as exc:                                   # pragma: no cover
        log.warning("cache unavailable: %s", exc)

    if connect:
        try:
            from .sources.ibkr import IBKRSource  # type: ignore
            ibkr = IBKRSource(
                host=settings.ibkr_host,
                port=settings.ibkr_port,
                client_id=settings.ibkr_client_id,
                readonly=settings.ibkr_readonly,
            )
        except Exception as exc:                               # pragma: no cover
            log.warning("IBKR source unavailable: %s", exc)

        if settings.yahoo_enabled:
            try:
                from .sources.yahoo import YahooSource  # type: ignore
                yahoo = YahooSource()
            except Exception as exc:                           # pragma: no cover
                log.warning("Yahoo source unavailable: %s", exc)

        if settings.finnhub_api_key:
            try:
                from .sources.finnhub import FinnhubSource  # type: ignore
                finnhub = FinnhubSource(settings.finnhub_api_key)
            except Exception as exc:                           # pragma: no cover
                log.warning("Finnhub source unavailable: %s", exc)

    return ServiceContext(cache=cache, ibkr=ibkr, yahoo=yahoo, finnhub=finnhub,
                          settings=settings)


def set_context(ctx: ServiceContext | None) -> None:
    """Install a context. Used by app startup and by the tests."""
    global _context
    _context = ctx


def get_context() -> ServiceContext:
    """FastAPI dependency. Never raises — an empty context serves empty caches."""
    global _context
    if _context is None:
        _context = build_context(connect=False)
    return _context


def reconcile_series(*args: Any, **kw: Any) -> Any:
    """Thin lazy proxy to `app.sources.reconcile.reconcile_series`."""
    from .sources.reconcile import reconcile_series as _f  # type: ignore
    return _f(*args, **kw)


def detect_corporate_action(*args: Any, **kw: Any) -> Any:
    """Thin lazy proxy to `app.sources.reconcile.detect_corporate_action`."""
    from .sources.reconcile import detect_corporate_action as _f  # type: ignore
    return _f(*args, **kw)


def compute_all(*args: Any, **kw: Any) -> Any:
    """Thin lazy proxy to `app.indicators.engine.compute_all`."""
    from .indicators.engine import compute_all as _f  # type: ignore
    return _f(*args, **kw)
