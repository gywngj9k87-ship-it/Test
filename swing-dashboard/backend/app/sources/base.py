"""
Shared contract for every data source.

Three rules this module exists to enforce:

  1. **Identity is (conid, exchange).** Every method that touches an instrument
     takes both. `symbol` appears only in `resolve()`, which is the one place we
     are allowed to go from a human label to an identity — and even there the
     exchange is mandatory, because SOXL is a 4x LSE ETP *and* a 3x US ETF.

  2. **Bars have one canonical shape.** Whoever fetched them, a bar frame is a
     `DatetimeIndex` named ``date`` with columns
     ``open, high, low, close, volume`` and a ``source`` label in ``df.attrs``.
     `reconcile.py` can then compare IBKR against Yahoo without caring who
     produced what.

  3. **Nothing here places orders.** This repo is read-only against IBKR by
     construction; see `ibkr.py`.

Also provides the two cross-cutting utilities every source needs: a
retry/backoff decorator that works on sync *and* async callables, and a
monotonic token-bucket rate limiter.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

import pandas as pd

from app.models import Instrument, Quote

log = logging.getLogger(__name__)


# ─────────────────────────── canonical bar shape ───────────────────────────

BAR_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
BAR_INDEX_NAME = "date"


def empty_bars(source: str = "") -> pd.DataFrame:
    """An empty frame with the right shape — never return a bare DataFrame()."""
    df = pd.DataFrame(
        {c: pd.Series(dtype="float64") for c in BAR_COLUMNS},
        index=pd.DatetimeIndex([], name=BAR_INDEX_NAME),
    )
    df.attrs["source"] = source
    return df


def normalize_bars(
    df: pd.DataFrame,
    *,
    source: str = "",
    conid: int | None = None,
    exchange: str | None = None,
) -> pd.DataFrame:
    """
    Coerce any reasonably-shaped frame into the canonical bar shape.

    Accepts a ``date`` column or an existing datetime index, any casing of the
    OHLCV column names, and Yahoo's ``Adj Close`` (ignored — we ask yfinance for
    already-adjusted data and cross-check the adjustment separately in
    `reconcile.detect_split_adjustment`).
    """
    if df is None or len(df) == 0:
        return empty_bars(source)

    out = df.copy()

    # column names → lowercase, spaces collapsed
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]

    # index
    if BAR_INDEX_NAME in out.columns:
        idx = pd.to_datetime(out[BAR_INDEX_NAME], errors="coerce", utc=False)
        out = out.drop(columns=[BAR_INDEX_NAME])
    else:
        idx = pd.to_datetime(out.index, errors="coerce", utc=False)

    # Drop any tz so IBKR (exchange-local) and Yahoo (often tz-aware) align on
    # calendar date. Bars are daily-or-coarser for every consumer of this layer.
    try:
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
    except (TypeError, AttributeError):  # pragma: no cover - defensive
        pass
    idx = pd.DatetimeIndex(idx).normalize()
    idx.name = BAR_INDEX_NAME
    out.index = idx

    for col in BAR_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.loc[:, list(BAR_COLUMNS)]
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()

    out.attrs["source"] = source
    if conid is not None:
        out.attrs["conid"] = conid
    if exchange is not None:
        out.attrs["exchange"] = exchange
    return out


# ─────────────────────────── period / step vocabulary ───────────────────────────

# The dashboard speaks in these; each source translates to its own dialect.
PERIODS: tuple[str, ...] = ("5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max")
STEPS: tuple[str, ...] = ("1min", "5min", "15min", "1h", "1d", "1wk", "1mo")

_PERIOD_ALIASES = {
    "1m": "1mo", "3m": "3mo", "6m": "6mo", "12m": "1y", "1w": "5d",
    "ytd": "1y",
}
_STEP_ALIASES = {
    "1m": "1min", "5m": "5min", "15m": "15min", "60min": "1h",
    "1hour": "1h", "day": "1d", "daily": "1d", "week": "1wk", "weekly": "1wk",
}


def canon_period(period: str) -> str:
    p = (period or "1y").strip().lower()
    p = _PERIOD_ALIASES.get(p, p)
    if p not in PERIODS:
        raise ValueError(f"unsupported period {period!r}; expected one of {PERIODS}")
    return p


def canon_step(step: str) -> str:
    s = (step or "1d").strip().lower()
    s = _STEP_ALIASES.get(s, s)
    if s not in STEPS:
        raise ValueError(f"unsupported step {step!r}; expected one of {STEPS}")
    return s


# ─────────────────────────── the protocol ───────────────────────────

@runtime_checkable
class PriceSource(Protocol):
    """
    What every price-bearing source must offer.

    Note the absence of anything symbol-keyed apart from `resolve`: once you
    have an Instrument you address it by (conid, exchange) forever after.
    """

    #: short stable label written into `df.attrs["source"]` and the cache
    name: str

    def get_bars(
        self, conid: int, exchange: str, period: str = "1y", step: str = "1d"
    ) -> pd.DataFrame:
        """Canonical OHLCV frame (see `normalize_bars`). Empty frame, not None,
        when the source has no coverage."""
        ...

    def get_quote(self, conid: int, exchange: str) -> Quote:
        """Latest snapshot. `delayed_seconds` must reflect reality, not zero."""
        ...

    def resolve(self, symbol: str, exchange: str) -> Instrument:
        """Symbol + exchange → identity. The only symbol-keyed entry point."""
        ...


class SourceError(RuntimeError):
    """Anything a source could not do. Callers degrade; they do not crash."""


class NoCoverage(SourceError):
    """The source simply does not carry this instrument (Yahoo + LSE ETPs)."""


class RateLimited(SourceError):
    """Upstream said slow down. Retryable."""


class BasePriceSource:
    """
    Small mixin with the bits every concrete source repeats.

    Deliberately not an ABC over `PriceSource` — sources differ in which parts
    of the protocol they can honestly implement (Yahoo cannot mint conids), and
    a hard ABC would push them into returning fake identities.
    """

    name: str = "base"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} name={self.name!r}>"

    @staticmethod
    def _key(conid: int, exchange: str) -> str:
        return f"{int(conid)}@{(exchange or '').upper()}"


# ─────────────────────────── retry / backoff ───────────────────────────

@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    multiplier: float = 2.0
    jitter: float = 0.25            # +/- fraction of the computed delay
    retry_on: tuple[type[BaseException], ...] = (
        RateLimited,
        TimeoutError,
        asyncio.TimeoutError,
        ConnectionError,
        OSError,
    )
    give_up_on: tuple[type[BaseException], ...] = (NoCoverage,)

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """`attempt` is 1-based: the wait *after* the first failure."""
        raw = min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)
        if self.jitter:
            r = rng or random
            raw *= 1.0 + r.uniform(-self.jitter, self.jitter)
        return max(0.0, raw)


DEFAULT_RETRY = RetryPolicy()


def with_retry(
    policy: RetryPolicy | None = None,
    *,
    attempts: int | None = None,
    sleep: Callable[[float], Any] | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
):
    """
    Retry with exponential backoff + jitter. Wraps sync and async callables.

    `sleep` is injectable so tests never actually wait; `on_retry` is a hook the
    nightly job uses to log which source is flapping.
    """
    pol = policy or DEFAULT_RETRY
    if attempts is not None:
        pol = RetryPolicy(**{**pol.__dict__, "attempts": attempts})

    def decorate(fn):
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                last: BaseException | None = None
                for attempt in range(1, pol.attempts + 1):
                    try:
                        return await fn(*args, **kwargs)
                    except pol.give_up_on:
                        raise
                    except pol.retry_on as exc:
                        last = exc
                        if attempt >= pol.attempts:
                            break
                        wait = pol.delay_for(attempt)
                        if on_retry:
                            on_retry(attempt, exc, wait)
                        log.warning(
                            "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                            getattr(fn, "__qualname__", fn), attempt, pol.attempts, exc, wait,
                        )
                        await asyncio.sleep(wait)
                assert last is not None
                raise last

            return awrapper

        _sleep = sleep or time.sleep

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last: BaseException | None = None
            for attempt in range(1, pol.attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except pol.give_up_on:
                    raise
                except pol.retry_on as exc:
                    last = exc
                    if attempt >= pol.attempts:
                        break
                    wait = pol.delay_for(attempt)
                    if on_retry:
                        on_retry(attempt, exc, wait)
                    log.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                        getattr(fn, "__qualname__", fn), attempt, pol.attempts, exc, wait,
                    )
                    _sleep(wait)
            assert last is not None
            raise last

        return wrapper

    return decorate


# ─────────────────────────── token bucket ───────────────────────────

@dataclass
class TokenBucket:
    """
    Classic token bucket. Finnhub's free tier is 60 calls/min, so
    ``TokenBucket(rate=60/60, capacity=60)`` — one token per second, a minute's
    worth of burst.

    Thread-safe, and usable from asyncio via `acquire_async` (which yields
    rather than blocking the loop). `clock`/`sleep` are injectable so the tests
    are deterministic and instant.
    """

    rate: float                       # tokens added per second
    capacity: float = 1.0
    tokens: float = field(default=None)  # type: ignore[assignment]
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Any] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _updated: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be > 0")
        self.capacity = float(max(self.capacity, 1.0))
        if self.tokens is None:
            self.tokens = self.capacity
        self._updated = self.clock()

    # -- internals -------------------------------------------------
    def _refill(self) -> None:
        now = self.clock()
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def _take(self, n: float) -> float:
        """Return 0.0 if taken, else seconds to wait before retrying."""
        with self._lock:
            self._refill()
            if self.tokens >= n:
                self.tokens -= n
                return 0.0
            return (n - self.tokens) / self.rate

    # -- public ----------------------------------------------------
    def try_acquire(self, n: float = 1.0) -> bool:
        return self._take(n) == 0.0

    def acquire(self, n: float = 1.0, timeout: float | None = None) -> bool:
        """Block until `n` tokens are available. False if `timeout` expires."""
        waited = 0.0
        while True:
            wait = self._take(n)
            if wait == 0.0:
                return True
            if timeout is not None and waited + wait > timeout:
                return False
            self.sleep(wait)
            waited += wait

    async def acquire_async(self, n: float = 1.0, timeout: float | None = None) -> bool:
        waited = 0.0
        while True:
            wait = self._take(n)
            if wait == 0.0:
                return True
            if timeout is not None and waited + wait > timeout:
                return False
            await asyncio.sleep(wait)
            waited += wait

    def rate_limited(self, n: float = 1.0):
        """Decorator form — every call spends `n` tokens."""

        def decorate(fn):
            if asyncio.iscoroutinefunction(fn):

                @functools.wraps(fn)
                async def awrapper(*a, **kw):
                    await self.acquire_async(n)
                    return await fn(*a, **kw)

                return awrapper

            @functools.wraps(fn)
            def wrapper(*a, **kw):
                self.acquire(n)
                return fn(*a, **kw)

            return wrapper

        return decorate


def per_minute(calls: int, *, burst: int | None = None, **kw: Any) -> TokenBucket:
    """`per_minute(60)` → the Finnhub free tier."""
    return TokenBucket(rate=calls / 60.0, capacity=float(burst or calls), **kw)


# ─────────────────────────── misc helpers ───────────────────────────

def first_not_none(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def safe_float(value: Any) -> float | None:
    """IBKR sends nan for 'no data'; yfinance sends None, nan, or the string
    'Infinity'. All of them mean the same thing here."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
