"""
IBKR — the PRIMARY source. Prices, history, quotes, positions, watchlists.

READ-ONLY BY CONSTRUCTION.
    `IB().connect(..., readonly=True)` is passed unconditionally from
    `settings.ibkr_readonly`, and if that setting is ever flipped to False this
    module refuses to connect (see `_assert_readonly`). There is no import of
    `Order`, `MarketOrder`, `LimitOrder`, `placeOrder` or `whatIfOrder` anywhere
    in this repo, and `test_sources.py` greps the tree to keep it that way.

WHY IBKR IS PRIMARY
    It is the execution venue, and it is the only one of our three sources that
    covers LSEETF / FWB / KSE / TSEJ listings consistently. Yahoo's coverage of
    the Leverage Shares products is patchy-to-absent.

EXCHANGE HANDLING — the thing that bites
    `SMART` is IBKR's US smart-router. Sending `exchange="SMART"` for a London
    ETP either fails outright or silently resolves the *US* contract with the
    same ticker, which is exactly the SOXL 4x-LSE / 3x-ARCA confusion this
    dashboard exists to prevent. So: the caller's exchange is passed through
    verbatim, always. We never substitute SMART for a listed non-US venue, and
    `resolve()` requires an exchange rather than defaulting one.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

from app.config import LEVERAGED_ETPS, WATCHLIST_ROUTING, settings, theme_for
from app.models import AssetClass, Instrument, Quote
from app.sources.base import (
    BasePriceSource,
    NoCoverage,
    SourceError,
    canon_period,
    canon_step,
    empty_bars,
    normalize_bars,
    safe_float,
    with_retry,
)

log = logging.getLogger(__name__)

SOURCE_NAME = "ibkr"

# IBKR market data types (reqMarketDataType).
MDT_LIVE = 1
MDT_FROZEN = 2
MDT_DELAYED = 3
MDT_DELAYED_FROZEN = 4

#: IBKR delayed feeds are 15 minutes. Surfaced on Quote.delayed_seconds so the
#: UI can put "15m delayed" next to the number instead of implying it is live.
DELAYED_SECONDS = 900

_DELAYED_TYPES = {MDT_DELAYED, MDT_DELAYED_FROZEN}


# ─────────────────────────── exchange policy ───────────────────────────

#: Venues that must never be routed through SMART. Not exhaustive — the rule is
#: "anything the caller gave us is passed through"; this set exists only so we
#: can *assert* it and log loudly if some future caller tries to override.
NON_SMART_EXCHANGES: frozenset[str] = frozenset({
    "LSEETF", "LSE", "LSEIOB1", "BVL",          # London
    "FWB", "FWB2", "IBIS", "IBIS2", "SWB", "TRADEGATE", "GETTEX",  # Germany
    "KSE",                                       # Korea
    "TSEJ", "JPNNEXT", "CHIXJ",                  # Japan
    "SEHK", "SEHKNTL", "SEHKSZSE",               # Hong Kong / China connect
    "AEB", "SBF", "BVME", "EBS", "VSE", "SFB", "CPH", "HEX", "OSE",
    "ASX", "TSE", "VENTURE",                     # Sydney / Toronto
    "MEXI", "BM", "BVMF",
})

#: Purely cosmetic normalisation. Case only — never a venue substitution.
def normalize_exchange(exchange: str | None) -> str:
    if exchange is None:
        return ""
    return exchange.strip().upper()


def is_non_smart(exchange: str | None) -> bool:
    return normalize_exchange(exchange) in NON_SMART_EXCHANGES


def routing_exchange(exchange: str | None) -> str:
    """
    The exchange string we hand IBKR.

    Pass-through, with exactly one fallback: an *empty* exchange for a US-style
    request becomes SMART. A non-empty exchange is never rewritten, so LSEETF
    stays LSEETF and FWB stays FWB.
    """
    ex = normalize_exchange(exchange)
    if not ex:
        return "SMART"
    return ex


# ─────────────────────────── lightweight DTOs ───────────────────────────

@dataclass(frozen=True)
class RawPosition:
    """
    What IBKR actually tells us about a holding.

    Deliberately *not* `models.Position`: that model needs last price, weight
    and a reconciled cost-basis status, which are portfolio.py's job. Keeping
    the raw shape separate is what lets the NAKA cost-basis question be settled
    downstream in `reconcile.detect_corporate_action` instead of being baked in
    here.
    """
    account: str
    conid: int
    symbol: str
    exchange: str
    currency: str
    sec_type: str
    quantity: float
    avg_cost: float


@dataclass(frozen=True)
class AccountSummary:
    account: str
    values: dict[str, float]
    currencies: dict[str, str] = field(default_factory=dict)

    def get(self, tag: str, default: float | None = None) -> float | None:
        return self.values.get(tag, default)

    @property
    def net_liquidation(self) -> float | None:
        return self.values.get("NetLiquidation")

    @property
    def cash(self) -> float | None:
        return self.values.get("TotalCashValue")

    @property
    def gross_position_value(self) -> float | None:
        return self.values.get("GrossPositionValue")


@dataclass(frozen=True)
class WatchlistEntry:
    conid: int
    symbol: str
    exchange: str
    name: str | None = None


@dataclass(frozen=True)
class Watchlist:
    id: str
    name: str
    entries: tuple[WatchlistEntry, ...] = ()

    @property
    def sleeve(self) -> str:
        return WATCHLIST_ROUTING.get(self.id, {}).get("sleeve", "swing")

    @property
    def emphasis(self) -> str | None:
        return WATCHLIST_ROUTING.get(self.id, {}).get("emphasis")


# ─────────────────────────── period/step translation ───────────────────────────

_DURATION = {
    "5d": "5 D", "1mo": "1 M", "3mo": "3 M", "6mo": "6 M",
    "1y": "1 Y", "2y": "2 Y", "5y": "5 Y", "max": "15 Y",
}
_BAR_SIZE = {
    "1min": "1 min", "5min": "5 mins", "15min": "15 mins", "1h": "1 hour",
    "1d": "1 day", "1wk": "1 week", "1mo": "1 month",
}


def ib_duration(period: str) -> str:
    return _DURATION[canon_period(period)]


def ib_bar_size(step: str) -> str:
    return _BAR_SIZE[canon_step(step)]


def _asset_class_for(conid: int, sec_type: str, symbol: str) -> AssetClass:
    if conid in LEVERAGED_ETPS:
        return AssetClass.LEVERAGED_ETP
    st = (sec_type or "").upper()
    if st == "IND":
        return AssetClass.INDEX
    if st == "CASH":
        return AssetClass.FX
    if st == "FUND":
        return AssetClass.FUND
    if st == "STK":
        # IBKR does not distinguish ETF from common stock on the contract; the
        # ETF flag lives on ContractDetails.stockType. `_instrument_from` uses
        # it when details are available, otherwise we stay honest and say EQUITY.
        return AssetClass.EQUITY
    return AssetClass.OTHER


# ─────────────────────────── the source ───────────────────────────

class IBKRSource(BasePriceSource):
    """
    Async-first client over `ib_async` (the maintained fork of ib_insync —
    `import ib_async`, never `ib_insync`).

    `ib_factory` is injectable so the tests can drive a fake IB with recorded
    responses; nothing in this class does live I/O of its own.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        readonly: bool | None = None,
        ib_factory: Callable[[], Any] | None = None,
        market_data_type: int = MDT_LIVE,
        watchlist_client: "WatchlistClient | None" = None,
        timeout: float = 10.0,
    ) -> None:
        self.host = host if host is not None else settings.ibkr_host
        self.port = int(port if port is not None else settings.ibkr_port)
        self.client_id = int(client_id if client_id is not None else settings.ibkr_client_id)
        self.readonly = bool(readonly if readonly is not None else settings.ibkr_readonly)
        self.timeout = timeout
        self.market_data_type = market_data_type
        self._ib_factory = ib_factory or _default_ib_factory
        self._ib: Any | None = None
        self._contracts: dict[str, Any] = {}       # "conid@exchange" -> qualified Contract
        self._mdt_applied: int | None = None
        self.watchlists_client = watchlist_client

    # -- connection ------------------------------------------------

    def _assert_readonly(self) -> None:
        if not self.readonly:
            raise SourceError(
                "settings.ibkr_readonly is False. This repo has no order-placement "
                "code and must not hold a writable IBKR session. Refusing to connect."
            )

    @property
    def ib(self) -> Any:
        if self._ib is None:
            raise SourceError("not connected — use `async with source.session():`")
        return self._ib

    @property
    def connected(self) -> bool:
        ib = self._ib
        return bool(ib is not None and getattr(ib, "isConnected", lambda: False)())

    async def connect(self) -> Any:
        """Idempotent. Always read-only."""
        self._assert_readonly()
        if self.connected:
            return self._ib
        ib = self._ib or self._ib_factory()
        await _maybe_await(
            ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=True,          # belt and braces: literal, not a variable
                timeout=self.timeout,
            )
            if hasattr(ib, "connectAsync")
            else ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=True,
                timeout=self.timeout,
            )
        )
        self._ib = ib
        self._mdt_applied = None
        await self._apply_market_data_type(self.market_data_type)
        return ib

    async def disconnect(self) -> None:
        ib, self._ib = self._ib, None
        self._contracts.clear()
        if ib is None:
            return
        try:
            await _maybe_await(ib.disconnect())
        except Exception as exc:  # pragma: no cover - teardown must never raise
            log.warning("IBKR disconnect failed (ignored): %s", exc)

    @asynccontextmanager
    async def session(self):
        """
        ``async with IBKRSource().session() as ib:``

        Disconnects on the way out even if the body raised, because a leaked
        clientId blocks the next connection with the same id.
        """
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()

    async def _apply_market_data_type(self, mdt: int) -> None:
        if self._mdt_applied == mdt or self._ib is None:
            return
        fn = getattr(self._ib, "reqMarketDataType", None)
        if fn is None:
            return
        await _maybe_await(fn(mdt))
        self._mdt_applied = mdt

    # -- contract resolution --------------------------------------

    @with_retry()
    async def contract_for(self, conid: int, exchange: str) -> Any:
        """
        Qualify by conid. This is the *only* correct way to address one of the
        colliding tickers: `Contract(conId=..., exchange=...)`. No symbol is
        sent, so IBKR cannot hand back the wrong SOXL.
        """
        from ib_async import Contract  # local import keeps unit tests import-light

        key = self._key(conid, exchange)
        cached = self._contracts.get(key)
        if cached is not None:
            return cached

        ex = routing_exchange(exchange)
        contract = Contract(conId=int(conid), exchange=ex)
        qualified = await _maybe_await(self.ib.qualifyContractsAsync(contract))
        got = _first_contract(qualified) or contract

        # Guard the collision case: if IBKR echoes a different conid, bail out
        # rather than quietly returning the wrong product.
        got_conid = int(getattr(got, "conId", 0) or 0)
        if got_conid and got_conid != int(conid):
            raise SourceError(
                f"qualifyContractsAsync returned conid {got_conid} for requested "
                f"{conid}@{ex} — refusing an ambiguous contract"
            )
        # Preserve the caller's venue: IBKR sometimes blanks `exchange` on the
        # qualified contract and leaves only primaryExchange.
        if not getattr(got, "exchange", ""):
            try:
                got.exchange = ex
            except Exception:  # pragma: no cover
                pass

        self._contracts[key] = got
        return got

    @with_retry()
    async def resolve(self, symbol: str, exchange: str) -> Instrument:
        """
        Symbol + exchange → Instrument. Exchange is MANDATORY.

        Raises when the pair is ambiguous (more than one contract) instead of
        picking one — an ambiguous SOXL is precisely the failure mode that puts
        you 4x long London when you meant 3x long ARCA.
        """
        from ib_async import Contract

        if not exchange:
            raise ValueError(
                f"resolve({symbol!r}) needs an exchange — symbols are not identities "
                "(SOXL is both a 4x LSEETF ETP and a 3x ARCA ETF)"
            )
        ex = routing_exchange(exchange)
        probe = Contract(secType="STK", symbol=symbol, exchange=ex)
        if is_non_smart(ex):
            # For a listed venue IBKR wants currency-agnostic lookup; leaving
            # currency unset lets it infer GBP/EUR/KRW/JPY from the venue.
            probe.primaryExchange = ex
        details = await _maybe_await(self.ib.reqContractDetailsAsync(probe))
        details = list(details or [])
        if not details:
            raise NoCoverage(f"IBKR has no contract for {symbol}@{ex}")
        conids = {int(getattr(d.contract, "conId", 0)) for d in details}
        if len(conids) > 1:
            raise SourceError(
                f"{symbol}@{ex} is ambiguous — IBKR returned conids {sorted(conids)}. "
                "Resolve by conid, not by symbol."
            )
        return self._instrument_from(details[0], fallback_exchange=ex)

    def _instrument_from(self, detail: Any, *, fallback_exchange: str = "") -> Instrument:
        contract = getattr(detail, "contract", detail)
        conid = int(getattr(contract, "conId", 0) or 0)
        symbol = getattr(contract, "symbol", "") or ""
        exchange = normalize_exchange(
            getattr(contract, "primaryExchange", "")
            or getattr(contract, "exchange", "")
            or fallback_exchange
        )
        sec_type = getattr(contract, "secType", "STK") or "STK"

        asset_class = _asset_class_for(conid, sec_type, symbol)
        stock_type = (getattr(detail, "stockType", "") or "").upper()
        if asset_class is AssetClass.EQUITY and "ETF" in stock_type:
            asset_class = AssetClass.ETF
        if asset_class is AssetClass.EQUITY and "PREFERRED" in stock_type:
            asset_class = AssetClass.PREFERRED

        meta = LEVERAGED_ETPS.get(conid, {})
        return Instrument(
            conid=conid,
            symbol=symbol,
            name=meta.get("name") or getattr(detail, "longName", None) or None,
            exchange=exchange,
            country=meta.get("country") or _country_for(exchange),
            currency=getattr(contract, "currency", "USD") or "USD",
            asset_class=asset_class,
            sector=getattr(detail, "industry", None) or None,
            industry=getattr(detail, "subcategory", None) or getattr(detail, "category", None) or None,
            theme=theme_for(symbol),
            leverage=meta.get("leverage"),
            underlying_conid=meta.get("underlying_conid"),
            ter_bps=meta.get("ter_bps"),
        )

    async def instrument(self, conid: int, exchange: str) -> Instrument:
        """Full metadata for an already-known identity."""
        from ib_async import Contract

        ex = routing_exchange(exchange)
        details = await _maybe_await(
            self.ib.reqContractDetailsAsync(Contract(conId=int(conid), exchange=ex))
        )
        details = list(details or [])
        if not details:
            raise NoCoverage(f"IBKR has no contract details for {conid}@{ex}")
        return self._instrument_from(details[0], fallback_exchange=ex)

    # -- history ---------------------------------------------------

    @with_retry()
    async def get_bars(
        self,
        conid: int,
        exchange: str,
        period: str = "1y",
        step: str = "1d",
        *,
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        end: datetime | str | None = "",
    ) -> pd.DataFrame:
        """
        Historical OHLCV via `reqHistoricalDataAsync`.

        `whatToShow="TRADES"` is right for equities and ETFs. Indices (secType
        IND) have no trades, so we fall back to MIDPOINT automatically rather
        than returning a mysteriously empty frame.
        """
        contract = await self.contract_for(conid, exchange)
        bars = await self._hist(contract, period, step, what_to_show, use_rth, end)

        if not bars and (getattr(contract, "secType", "") or "").upper() in {"IND", "CASH"}:
            bars = await self._hist(contract, period, step, "MIDPOINT", use_rth, end)

        if not bars:
            return empty_bars(self.name)

        frame = pd.DataFrame(
            [
                {
                    "date": b.date,
                    "open": safe_float(b.open),
                    "high": safe_float(b.high),
                    "low": safe_float(b.low),
                    "close": safe_float(b.close),
                    # IBKR daily volume is in *lots* of 100 for US equities on
                    # some feeds; it is reported raw here and the tolerance in
                    # reconcile.py is what catches a unit mismatch, rather than
                    # us guessing a multiplier.
                    "volume": safe_float(b.volume),
                }
                for b in bars
            ]
        )
        return normalize_bars(frame, source=self.name, conid=conid, exchange=exchange)

    async def _hist(
        self, contract: Any, period: str, step: str, what: str, rth: bool, end: Any
    ) -> list[Any]:
        result = await _maybe_await(
            self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end or "",
                durationStr=ib_duration(period),
                barSizeSetting=ib_bar_size(step),
                whatToShow=what,
                useRTH=rth,
                formatDate=1,
            )
        )
        return list(result or [])

    # -- quotes ----------------------------------------------------

    @with_retry()
    async def get_quote(self, conid: int, exchange: str) -> Quote:
        """
        Snapshot quote.

        Tries live (`reqMarketDataType(1)`); if the returned ticker comes back
        tagged delayed — which it will for LSE/FWB/KSE/TSEJ without those market
        data subscriptions — we retry explicitly at type 3 and record
        `delayed_seconds = 900` on the Quote so nothing downstream can mistake a
        15-minute-old print for a live one.
        """
        contract = await self.contract_for(conid, exchange)

        await self._apply_market_data_type(self.market_data_type)
        ticker = await self._snapshot(contract)

        mdt = int(getattr(ticker, "marketDataType", 0) or 0)
        if _ticker_is_empty(ticker) and self.market_data_type not in _DELAYED_TYPES:
            # No live entitlement for this venue — fall back to delayed.
            await self._apply_market_data_type(MDT_DELAYED)
            ticker = await self._snapshot(contract)
            mdt = int(getattr(ticker, "marketDataType", MDT_DELAYED) or MDT_DELAYED)

        return self._quote_from(ticker, conid=conid, market_data_type=mdt)

    async def _snapshot(self, contract: Any) -> Any:
        """
        ib_async exposes the async snapshot as `reqTickersAsync`; there is no
        `reqMktDataAsync` in the 2.x API (see module notes in the task report).
        We prefer `reqMktDataAsync` if a future version adds it — and the fakes
        in the test-suite provide it — otherwise `reqTickersAsync`.
        """
        fn = getattr(self.ib, "reqMktDataAsync", None)
        if fn is not None:
            return await _maybe_await(fn(contract))
        tickers = await _maybe_await(self.ib.reqTickersAsync(contract))
        tickers = list(tickers or [])
        if not tickers:
            raise NoCoverage(f"no ticker returned for conid {getattr(contract, 'conId', '?')}")
        return tickers[0]

    def _quote_from(self, ticker: Any, *, conid: int, market_data_type: int) -> Quote:
        last = safe_float(getattr(ticker, "last", None))
        close = safe_float(getattr(ticker, "close", None))
        mark = safe_float(getattr(ticker, "markPrice", None))
        bid = safe_float(getattr(ticker, "bid", None))
        ask = safe_float(getattr(ticker, "ask", None))

        price = last if last is not None else (mark if mark is not None else None)
        if price is None and bid is not None and ask is not None:
            price = (bid + ask) / 2.0

        change = change_pct = None
        if price is not None and close:
            change = price - close
            change_pct = (change / close) * 100.0

        ts = getattr(ticker, "time", None)
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return Quote(
            conid=int(conid),
            last=price,
            bid=bid,
            ask=ask,
            change=change,
            change_pct=change_pct,
            volume=safe_float(getattr(ticker, "volume", None)),
            ts=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
            delayed_seconds=DELAYED_SECONDS if market_data_type in _DELAYED_TYPES else 0,
        )

    async def get_quotes(self, keys: Sequence[tuple[int, str]]) -> dict[str, Quote]:
        """Batched snapshots, keyed `conid@EXCHANGE`. Failures are skipped, not fatal."""
        out: dict[str, Quote] = {}
        for conid, exchange in keys:
            try:
                out[self._key(conid, exchange)] = await self.get_quote(conid, exchange)
            except Exception as exc:
                log.warning("quote failed for %s@%s: %s", conid, exchange, exc)
        return out

    # -- account ---------------------------------------------------

    @with_retry()
    async def positions(self, account: str = "") -> list[RawPosition]:
        """
        `reqPositionsAsync()` — note ib_async 2.x names it `reqPositionsAsync`,
        not `positionsAsync`.

        `avgCost` for a multiplier-1 stock is per share; we pass it through
        untouched so that `reconcile.detect_corporate_action` sees the raw
        number (NAKA: 34 @ 169.65 against a 4.85 market).
        """
        fn = getattr(self.ib, "reqPositionsAsync", None) or getattr(self.ib, "positionsAsync")
        raw = await _maybe_await(fn())
        out: list[RawPosition] = []
        for p in list(raw or []):
            contract = getattr(p, "contract", None)
            if contract is None:
                continue
            acct = getattr(p, "account", "") or ""
            if account and acct != account:
                continue
            out.append(
                RawPosition(
                    account=acct,
                    conid=int(getattr(contract, "conId", 0) or 0),
                    symbol=getattr(contract, "symbol", "") or "",
                    exchange=normalize_exchange(
                        getattr(contract, "primaryExchange", "")
                        or getattr(contract, "exchange", "")
                    ),
                    currency=getattr(contract, "currency", "USD") or "USD",
                    sec_type=getattr(contract, "secType", "STK") or "STK",
                    quantity=float(getattr(p, "position", 0.0) or 0.0),
                    avg_cost=float(getattr(p, "avgCost", 0.0) or 0.0),
                )
            )
        return out

    @with_retry()
    async def account_summary(self, account: str = "") -> AccountSummary:
        raw = await _maybe_await(self.ib.accountSummaryAsync(account))
        values: dict[str, float] = {}
        currencies: dict[str, str] = {}
        acct = account
        for av in list(raw or []):
            tag = getattr(av, "tag", "")
            if not tag:
                continue
            acct = acct or getattr(av, "account", "") or ""
            num = safe_float(getattr(av, "value", None))
            if num is not None:
                values[tag] = num
            cur = getattr(av, "currency", "") or ""
            if cur:
                currencies[tag] = cur
        return AccountSummary(account=acct, values=values, currencies=currencies)

    # -- watchlists ------------------------------------------------

    async def watchlists(self) -> list[Watchlist]:
        """
        The user's IBKR watchlists ARE the universe configuration (config.py).

        CAVEAT — the TWS socket API that `ib_async` speaks has no watchlist
        endpoint at all; watchlists live only in the Client Portal Web API
        (`GET /iserver/watchlists`). So this delegates to `WatchlistClient`,
        which talks to a locally-running Client Portal Gateway over HTTPS and
        issues GETs only. If no client is configured we return [] and log —
        never raise, because a missing watchlist must not take the page down.
        """
        client = self.watchlists_client
        if client is None:
            log.info("no WatchlistClient configured — watchlist universe unavailable")
            return []
        try:
            return await client.fetch_all()
        except Exception as exc:
            log.warning("watchlist retrieval failed (degrading to empty): %s", exc)
            return []


# ─────────────────────────── watchlists over Client Portal ───────────────────────────

class WatchlistClient:
    """
    Read-only Client Portal Web API client for watchlists.

    `http_get(path, params) -> dict` is injected, which keeps this unit-testable
    and keeps the HTTP library choice out of the source layer. The default
    implementation uses `requests` against a locally running gateway.
    """

    def __init__(
        self,
        base_url: str = "https://localhost:5000/v1/api",
        *,
        http_get: Callable[[str, dict[str, Any]], Any] | None = None,
        verify_tls: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_tls = verify_tls
        self._http_get = http_get or self._requests_get

    def _requests_get(self, path: str, params: dict[str, Any]) -> Any:  # pragma: no cover
        import requests

        # The gateway ships a self-signed cert on localhost; verification is
        # off only for that loopback host, and only for GETs.
        resp = requests.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_all(self) -> list[Watchlist]:
        index = await _maybe_await(self._http_get("/iserver/watchlists", {"SC": "USER_LISTS"}))
        raw_lists = (((index or {}).get("data") or {}).get("user_lists")) or []
        out: list[Watchlist] = []
        for item in raw_lists:
            wid = str(item.get("id") or item.get("ID") or "")
            if not wid:
                continue
            name = item.get("name") or WATCHLIST_ROUTING.get(wid, {}).get("name") or wid
            try:
                out.append(await self.fetch(wid, name=name))
            except Exception as exc:
                log.warning("watchlist %s (%s) failed: %s", wid, name, exc)
                out.append(Watchlist(id=wid, name=name, entries=()))
        return out

    async def fetch(self, watchlist_id: str, *, name: str | None = None) -> Watchlist:
        payload = await _maybe_await(self._http_get("/iserver/watchlist", {"id": watchlist_id}))
        payload = payload or {}
        entries: list[WatchlistEntry] = []
        for row in payload.get("instruments") or []:
            conid = row.get("C") or row.get("conid") or row.get("conId")
            if conid in (None, ""):
                continue
            entries.append(
                WatchlistEntry(
                    conid=int(conid),
                    symbol=(row.get("ticker") or row.get("symbol") or "").strip(),
                    # The CP payload calls the venue `listingExchange`; keep it
                    # verbatim so LSEETF survives the round trip.
                    exchange=normalize_exchange(
                        row.get("listingExchange") or row.get("exchange") or ""
                    ),
                    name=row.get("name") or row.get("fullName") or None,
                )
            )
        return Watchlist(
            id=str(watchlist_id),
            name=name or payload.get("name") or str(watchlist_id),
            entries=tuple(entries),
        )


# ─────────────────────────── helpers ───────────────────────────

def _default_ib_factory() -> Any:
    from ib_async import IB

    return IB()


async def _maybe_await(value: Any) -> Any:
    """Accept coroutines, futures and plain values — lets the tests use simple
    synchronous fakes in place of the real async IB client."""
    if asyncio.isfuture(value) or asyncio.iscoroutine(value):
        return await value
    if hasattr(value, "__await__"):
        return await value
    return value


def _first_contract(qualified: Any) -> Any:
    """`qualifyContractsAsync` returns a list which may itself hold lists."""
    if qualified is None:
        return None
    items: Iterable[Any] = qualified if isinstance(qualified, (list, tuple)) else [qualified]
    for item in items:
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            inner = _first_contract(item)
            if inner is not None:
                return inner
            continue
        return item
    return None


def _ticker_is_empty(ticker: Any) -> bool:
    for attr in ("last", "close", "bid", "ask", "markPrice"):
        if safe_float(getattr(ticker, attr, None)) is not None:
            return False
    return True


_COUNTRY_BY_EXCHANGE = {
    "LSEETF": "GB", "LSE": "GB", "LSEIOB1": "GB",
    "FWB": "DE", "FWB2": "DE", "IBIS": "DE", "IBIS2": "DE", "SWB": "DE",
    "TRADEGATE": "DE", "GETTEX": "DE",
    "KSE": "KR", "TSEJ": "JP", "JPNNEXT": "JP",
    "SEHK": "HK", "AEB": "NL", "SBF": "FR", "BVME": "IT", "EBS": "CH",
    "ASX": "AU", "TSE": "CA", "VENTURE": "CA",
    "ARCA": "US", "NASDAQ": "US", "NYSE": "US", "BATS": "US", "AMEX": "US",
    "CBOE": "US", "IEX": "US", "SMART": "US",
}


def _country_for(exchange: str) -> str | None:
    return _COUNTRY_BY_EXCHANGE.get(normalize_exchange(exchange))
