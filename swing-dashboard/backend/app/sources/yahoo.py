"""
Yahoo — the SECONDARY source.

What it is for:
  * fundamentals (forward P/E, EPS & revenue growth, float, short interest)
  * earnings dates + history and surprise
  * analyst price targets
  * dividend history and ex-dividend dates
  * a **second daily close series**, used purely to cross-check IBKR

What it is NOT for:
  * identity. Yahoo has no conid namespace, and a Yahoo ticker is exactly the
    symbol-as-identity mistake this dashboard is built to avoid — "SOXL" on
    Yahoo is the Direxion 3x, full stop; the 4x LSE product is "SOXL.L" if it is
    covered at all. So `resolve()` here is deliberately identity-free: it fills
    metadata onto an Instrument that IBKR already minted (`enrich`), and returns
    None when Yahoo has no coverage.

EVERY public method returns None / an empty collection on failure. Yahoo is a
scraped, unversioned, rate-limited endpoint; a bad afternoon at Yahoo must
degrade the fundamentals block, not break a page render.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable

import pandas as pd
from pydantic import BaseModel, Field

from app.models import Instrument
from app.sources.base import (
    BasePriceSource,
    canon_period,
    canon_step,
    empty_bars,
    normalize_bars,
    safe_float,
)

log = logging.getLogger(__name__)

SOURCE_NAME = "yahoo"


# ═══════════════════════════ symbol mapping ═══════════════════════════
#
# IBKR exchange code → Yahoo suffix. IBKR is the identity authority, so the
# mapping always runs *from* an (conid, exchange)-keyed Instrument, never from a
# bare ticker.
#
# The four the spec names explicitly: .L London, .DE Frankfurt, .KS Korea,
# .T Tokyo. The rest are here because the "track" watchlist has European and
# Nordic shipping names in it.

EXCHANGE_SUFFIX: dict[str, str] = {
    # United Kingdom
    "LSEETF": ".L",
    "LSE": ".L",
    "LSEIOB1": ".L",
    # Germany  (IBIS/IBIS2 = Xetra, FWB = Frankfurt floor — Yahoo lumps both
    # under .DE; .F exists for the floor but is far thinner, so .DE it is)
    "FWB": ".DE",
    "FWB2": ".DE",
    "IBIS": ".DE",
    "IBIS2": ".DE",
    "SWB": ".DE",
    "TRADEGATE": ".DE",
    "GETTEX": ".DE",
    # Korea (KOSPI .KS; KOSDAQ is .KQ but IBKR uses KSE for both — see below)
    "KSE": ".KS",
    # Japan
    "TSEJ": ".T",
    "JPNNEXT": ".T",
    # Rest of the watchlist's footprint
    "SEHK": ".HK",
    "AEB": ".AS",
    "SBF": ".PA",
    "BVME": ".MI",
    "EBS": ".SW",
    "VSE": ".VI",
    "SFB": ".ST",
    "CPH": ".CO",
    "HEX": ".HE",
    "OSE": ".OL",
    "ASX": ".AX",
    "TSE": ".TO",          # IBKR TSE = Toronto. Tokyo is TSEJ. Do not merge.
    "VENTURE": ".V",
    "BVMF": ".SA",
    "MEXI": ".MX",
}

#: US venues take no suffix on Yahoo.
US_EXCHANGES: frozenset[str] = frozenset(
    {"ARCA", "NASDAQ", "NYSE", "AMEX", "BATS", "IEX", "CBOE", "SMART", "PINK", "NYSENAT", ""}
)


class NoYahooCoverage(Exception):
    """Raised only internally; the public API returns None instead."""


def yahoo_ticker(symbol: str, exchange: str) -> str | None:
    """
    (symbol, exchange) → Yahoo ticker, or None when we cannot map the venue.

    Returning None rather than guessing matters: an unsuffixed "SOXL" for the
    LSEETF 4x product would silently cross-check the London ETP against the
    Direxion 3x and flag a permanent, meaningless divergence.

        >>> yahoo_ticker("SOXL", "LSEETF")
        'SOXL.L'
        >>> yahoo_ticker("RHM", "FWB")
        'RHM.DE'
        >>> yahoo_ticker("NVDA", "NASDAQ")
        'NVDA'
    """
    if not symbol:
        return None
    ex = (exchange or "").strip().upper()
    base = _clean_symbol(symbol)
    if not base:
        return None

    if ex in US_EXCHANGES:
        # Yahoo writes US share classes with a hyphen: BRK.B → BRK-B.
        return base.replace(".", "-").rstrip("-") or None

    suffix = EXCHANGE_SUFFIX.get(ex)
    if suffix is None:
        log.info("no Yahoo suffix known for exchange %r (symbol %s)", ex, symbol)
        return None
    return f"{base}{suffix}"


def _clean_symbol(symbol: str) -> str:
    """
    Normalise IBKR's local symbols.

    IBKR writes Rolls-Royce as ``RR.`` and Berkshire B as ``BRK B``. A trailing
    dot would produce ``RR..L``; a space would produce ``BRK B.L``.
    """
    s = symbol.strip().upper()
    s = s.replace(" ", "-")
    while s.endswith("."):
        s = s[:-1]
    return s


def yahoo_ticker_for(instrument: Instrument) -> str | None:
    return yahoo_ticker(instrument.symbol, instrument.exchange)


# ═══════════════════════════ DTOs ═══════════════════════════
#
# These are source-layer shapes, not part of models.py (the frozen API
# contract). They exist so the cache and the fundamentals block have something
# typed to hold; the API models are assembled downstream.

class Fundamentals(BaseModel):
    conid: int
    symbol: str
    ticker: str                       # the Yahoo ticker actually used
    as_of: date | None = None
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    market_cap: float | None = None
    float_shares: float | None = None
    shares_outstanding: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    eps_trailing: float | None = None
    eps_forward: float | None = None
    eps_growth_yoy: float | None = None       # fraction, 0.18 == +18%
    revenue_growth_yoy: float | None = None
    profit_margin: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None


class AnalystTargets(BaseModel):
    conid: int
    ticker: str
    current_price: float | None = None
    target_mean: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_median: float | None = None
    analyst_count: int | None = None
    recommendation_mean: float | None = None   # 1 = strong buy … 5 = sell
    recommendation_key: str | None = None

    @property
    def upside_pct(self) -> float | None:
        if self.current_price and self.target_mean:
            return (self.target_mean / self.current_price - 1.0) * 100.0
        return None


class EarningsEvent(BaseModel):
    conid: int
    ticker: str
    report_date: date
    eps_estimate: float | None = None
    eps_actual: float | None = None
    surprise_pct: float | None = None
    is_future: bool = False


class DividendEvent(BaseModel):
    conid: int
    ticker: str
    ex_date: date
    amount: float
    pay_date: date | None = None


class ShortInterest(BaseModel):
    conid: int
    ticker: str
    shares_short: float | None = None
    short_ratio: float | None = None            # days to cover
    short_pct_of_float: float | None = None
    short_pct_of_shares_outstanding: float | None = None
    as_of: date | None = None


@dataclass(frozen=True)
class _Unmapped:
    """Sentinel for 'we could not even build a Yahoo ticker'."""


# ═══════════════════════════ the source ═══════════════════════════

class YahooSource(BasePriceSource):
    """
    Thin, defensive wrapper over `yfinance`.

    `ticker_factory` is injected so the tests can hand in a fake Ticker with
    recorded `.info` / `.history()` payloads. Nothing here does live I/O
    directly.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        ticker_factory: Callable[[str], Any] | None = None,
        enabled: bool | None = None,
    ) -> None:
        from app.config import settings

        self.enabled = bool(enabled if enabled is not None else settings.yahoo_enabled)
        self._ticker_factory = ticker_factory or _default_ticker_factory
        self._cache: dict[str, Any] = {}

    # -- plumbing --------------------------------------------------

    def _ticker(self, ticker: str) -> Any:
        t = self._cache.get(ticker)
        if t is None:
            t = self._ticker_factory(ticker)
            self._cache[ticker] = t
        return t

    def _map(self, symbol: str, exchange: str) -> str | None:
        if not self.enabled:
            return None
        return yahoo_ticker(symbol, exchange)

    @staticmethod
    def _info(tk: Any) -> dict[str, Any]:
        """`.info` raises, returns {}, or returns junk depending on the day."""
        for attr in ("get_info", "info"):
            try:
                raw = getattr(tk, attr)
                info = raw() if callable(raw) else raw
                if isinstance(info, dict) and info:
                    return info
            except Exception as exc:
                log.debug("yfinance %s failed: %s", attr, exc)
        return {}

    # -- PriceSource surface --------------------------------------

    def get_bars(
        self,
        conid: int,
        exchange: str,
        period: str = "1y",
        step: str = "1d",
        *,
        symbol: str = "",
        auto_adjust: bool = False,
    ) -> pd.DataFrame:
        """
        The cross-check series. `auto_adjust=False` on purpose: we want Yahoo's
        *unadjusted* close so `reconcile.detect_split_adjustment` can compare
        like with like against IBKR's, and detect the case where one of them has
        applied a split and the other has not.

        Needs `symbol` because Yahoo is symbol-addressed; the conid is carried
        through only so the frame can be labelled and cached under the right key.
        """
        yt = self._map(symbol, exchange)
        if yt is None:
            return empty_bars(self.name)
        try:
            tk = self._ticker(yt)
            raw = tk.history(
                period=_yf_period(period),
                interval=_yf_interval(step),
                auto_adjust=auto_adjust,
                actions=False,
            )
        except Exception as exc:
            log.warning("yahoo history failed for %s: %s", yt, exc)
            return empty_bars(self.name)

        if raw is None or len(raw) == 0:
            log.info("yahoo has no history for %s", yt)
            return empty_bars(self.name)

        df = normalize_bars(raw, source=self.name, conid=conid, exchange=exchange)
        df.attrs["yahoo_ticker"] = yt
        return df

    def get_quote(self, conid: int, exchange: str, *, symbol: str = ""):
        """
        Yahoo quotes exist but are 15-min delayed and not what the dashboard
        prices from — IBKR is the execution venue. Kept for completeness and for
        reconciliation of the last close; returns None when uncovered.
        """
        from app.models import Quote

        yt = self._map(symbol, exchange)
        if yt is None:
            return None
        info = self._info(self._ticker(yt))
        if not info:
            return None
        last = safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        prev = safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        change = (last - prev) if (last is not None and prev is not None) else None
        return Quote(
            conid=int(conid),
            last=last,
            bid=safe_float(info.get("bid")),
            ask=safe_float(info.get("ask")),
            change=change,
            change_pct=((change / prev) * 100.0) if (change is not None and prev) else None,
            volume=safe_float(info.get("regularMarketVolume") or info.get("volume")),
            ts=datetime.now(),
            delayed_seconds=900,      # Yahoo's free feed is delayed. Say so.
        )

    def resolve(self, symbol: str, exchange: str) -> Instrument | None:
        """
        NOT an identity lookup — Yahoo cannot mint a conid, and pretending
        otherwise is how you end up with two SOXLs sharing a primary key.

        Returns None always; the method exists so `YahooSource` fails loudly
        against the `PriceSource` protocol rather than fabricating identities.
        Use `enrich(instrument)` to attach Yahoo metadata to an IBKR-resolved
        Instrument.
        """
        log.debug(
            "YahooSource.resolve(%s, %s) called — identity comes from IBKR only",
            symbol, exchange,
        )
        return None

    def enrich(self, instrument: Instrument) -> Instrument:
        """Copy Yahoo's sector / industry / name onto an IBKR identity.
        Returns the input unchanged when Yahoo has no coverage."""
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return instrument
        info = self._info(self._ticker(yt))
        if not info:
            return instrument
        return instrument.model_copy(
            update={
                "name": instrument.name or info.get("longName") or info.get("shortName"),
                "sector": instrument.sector or info.get("sector"),
                "industry": instrument.industry or info.get("industry"),
            }
        )

    # -- fundamentals ----------------------------------------------

    def fundamentals(self, instrument: Instrument) -> Fundamentals | None:
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return None
        info = self._info(self._ticker(yt))
        if not info:
            log.info("yahoo has no fundamentals for %s", yt)
            return None
        return Fundamentals(
            conid=instrument.conid,
            symbol=instrument.symbol,
            ticker=yt,
            as_of=date.today(),
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=info.get("currency"),
            market_cap=safe_float(info.get("marketCap")),
            float_shares=safe_float(info.get("floatShares")),
            shares_outstanding=safe_float(info.get("sharesOutstanding")),
            trailing_pe=safe_float(info.get("trailingPE")),
            forward_pe=safe_float(info.get("forwardPE")),
            peg_ratio=safe_float(info.get("pegRatio") or info.get("trailingPegRatio")),
            price_to_book=safe_float(info.get("priceToBook")),
            eps_trailing=safe_float(info.get("trailingEps")),
            eps_forward=safe_float(info.get("forwardEps")),
            eps_growth_yoy=safe_float(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")),
            revenue_growth_yoy=safe_float(info.get("revenueGrowth")),
            profit_margin=safe_float(info.get("profitMargins")),
            dividend_yield=safe_float(info.get("dividendYield")),
            beta=safe_float(info.get("beta")),
        )

    def analyst_targets(self, instrument: Instrument) -> AnalystTargets | None:
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return None
        info = self._info(self._ticker(yt))
        if not info:
            return None
        targets = AnalystTargets(
            conid=instrument.conid,
            ticker=yt,
            current_price=safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
            target_mean=safe_float(info.get("targetMeanPrice")),
            target_high=safe_float(info.get("targetHighPrice")),
            target_low=safe_float(info.get("targetLowPrice")),
            target_median=safe_float(info.get("targetMedianPrice")),
            analyst_count=_as_int(info.get("numberOfAnalystOpinions")),
            recommendation_mean=safe_float(info.get("recommendationMean")),
            recommendation_key=info.get("recommendationKey"),
        )
        if targets.target_mean is None and targets.recommendation_mean is None:
            return None
        return targets

    def short_interest(self, instrument: Instrument) -> ShortInterest | None:
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return None
        info = self._info(self._ticker(yt))
        if not info:
            return None
        si = ShortInterest(
            conid=instrument.conid,
            ticker=yt,
            shares_short=safe_float(info.get("sharesShort")),
            short_ratio=safe_float(info.get("shortRatio")),
            short_pct_of_float=safe_float(info.get("shortPercentOfFloat")),
            short_pct_of_shares_outstanding=safe_float(
                info.get("sharesPercentSharesOut")
            ),
            as_of=_as_date(info.get("dateShortInterest")),
        )
        if si.shares_short is None and si.short_ratio is None and si.short_pct_of_float is None:
            return None
        return si

    # -- events ----------------------------------------------------

    def earnings_history(self, instrument: Instrument, limit: int = 12) -> list[EarningsEvent]:
        """
        Past reports with actual vs estimate, plus any scheduled future date.
        Empty list — never an exception — when Yahoo is unhelpful.
        """
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return []
        tk = self._ticker(yt)
        rows: list[EarningsEvent] = []
        today = date.today()

        for attr in ("get_earnings_dates", "earnings_dates"):
            try:
                raw = getattr(tk, attr, None)
                df = raw(limit=limit) if callable(raw) else raw
            except TypeError:
                try:
                    df = getattr(tk, attr)()
                except Exception:
                    df = None
            except Exception as exc:
                log.debug("yfinance %s failed for %s: %s", attr, yt, exc)
                df = None
            if df is None or len(df) == 0:
                continue

            frame = df.reset_index()
            cols = {str(c).strip().lower(): c for c in frame.columns}
            dcol = cols.get("earnings date") or cols.get("index") or cols.get("date")
            if dcol is None:
                continue
            for _, r in frame.iterrows():
                d = _as_date(r[dcol])
                if d is None:
                    continue
                est = safe_float(r.get(cols.get("eps estimate", ""), None))
                act = safe_float(r.get(cols.get("reported eps", ""), None))
                sur = safe_float(r.get(cols.get("surprise(%)", ""), None))
                if sur is None and est not in (None, 0) and act is not None:
                    sur = (act - est) / abs(est) * 100.0
                rows.append(
                    EarningsEvent(
                        conid=instrument.conid,
                        ticker=yt,
                        report_date=d,
                        eps_estimate=est,
                        eps_actual=act,
                        surprise_pct=sur,
                        is_future=d > today,
                    )
                )
            break

        rows.sort(key=lambda e: e.report_date, reverse=True)
        return rows[:limit]

    def next_earnings_date(self, instrument: Instrument) -> date | None:
        upcoming = [e.report_date for e in self.earnings_history(instrument) if e.is_future]
        return min(upcoming) if upcoming else None

    def dividends(self, instrument: Instrument, limit: int = 40) -> list[DividendEvent]:
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return []
        try:
            series = self._ticker(yt).dividends
        except Exception as exc:
            log.warning("yahoo dividends failed for %s: %s", yt, exc)
            return []
        if series is None or len(series) == 0:
            return []
        out: list[DividendEvent] = []
        for idx, amount in series.items():
            d = _as_date(idx)
            amt = safe_float(amount)
            if d is None or amt is None:
                continue
            out.append(DividendEvent(conid=instrument.conid, ticker=yt, ex_date=d, amount=amt))
        out.sort(key=lambda e: e.ex_date, reverse=True)
        return out[:limit]

    def next_ex_dividend(self, instrument: Instrument) -> date | None:
        yt = self._map(instrument.symbol, instrument.exchange)
        if yt is None:
            return None
        info = self._info(self._ticker(yt))
        return _as_date(info.get("exDividendDate")) if info else None

    # -- convenience ------------------------------------------------

    def close_series(
        self, conid: int, exchange: str, symbol: str, period: str = "1y"
    ) -> pd.Series:
        """Just the closes, for `reconcile_series`. Empty Series when uncovered."""
        df = self.get_bars(conid, exchange, period=period, step="1d", symbol=symbol)
        if df.empty:
            return pd.Series(dtype="float64")
        return df["close"]


# ═══════════════════════════ helpers ═══════════════════════════

_YF_PERIOD = {
    "5d": "5d", "1mo": "1mo", "3mo": "3mo", "6mo": "6mo",
    "1y": "1y", "2y": "2y", "5y": "5y", "max": "max",
}
_YF_INTERVAL = {
    "1min": "1m", "5min": "5m", "15min": "15m", "1h": "1h",
    "1d": "1d", "1wk": "1wk", "1mo": "1mo",
}


def _yf_period(period: str) -> str:
    return _YF_PERIOD[canon_period(period)]


def _yf_interval(step: str) -> str:
    return _YF_INTERVAL[canon_step(step)]


def _as_int(value: Any) -> int | None:
    f = safe_float(value)
    return int(f) if f is not None else None


def _as_date(value: Any) -> date | None:
    """Yahoo hands back epoch ints, Timestamps, datetimes and strings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        f = safe_float(value)
        if f is None:
            return None
        try:
            return datetime.utcfromtimestamp(f).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if ts is None or ts is pd.NaT or (isinstance(ts, float) and ts != ts):
        return None
    try:
        return ts.date()
    except AttributeError:
        return None


def _default_ticker_factory(ticker: str) -> Any:  # pragma: no cover - live path
    import yfinance as yf

    return yf.Ticker(ticker)
