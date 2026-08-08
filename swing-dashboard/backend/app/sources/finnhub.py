"""
Finnhub — headlines, analyst actions, earnings surprises.

Free tier. Three constraints shape this whole module:

  1. **60 calls/minute.** Enforced locally with the token bucket from `base`,
     so we throttle ourselves rather than collecting 429s.
  2. **The key may be blank.** `settings.finnhub_api_key` defaults to "" and
     plenty of installs will never set it. Every method returns an empty list
     in that case — no exception, no network call.
  3. **Finnhub goes down.** The news tape is the *least* important thing on the
     page; it must never be the reason the page fails. Every public method is
     wrapped so any transport, JSON, or schema error degrades to [].

Everything is returned as `models.MarketEvent`, so the tape in `events.py` can
merge Finnhub items with price anomalies without a translation layer. Note the
spec's organising idea: an event is only interesting paired with its price
reaction, so `moved_price` and `reaction_pct` are left None here and filled in
downstream by `events.py`, which has the bars.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence

from app.config import settings
from app.models import EventClass, MarketEvent, Severity
from app.sources.base import (
    RateLimited,
    RetryPolicy,
    TokenBucket,
    per_minute,
    safe_float,
    with_retry,
)

log = logging.getLogger(__name__)

SOURCE_NAME = "finnhub"
BASE_URL = "https://finnhub.io/api/v1"

#: Free tier: 60 API calls/minute (and 30 calls/second, which the per-minute
#: bucket subsumes at our volumes).
FREE_TIER_CALLS_PER_MIN = 60

#: Deliberately shallow. The news tape is the least important thing on the page,
#: so an outage should cost a fraction of a second and then degrade — not three
#: exponential backoffs while the user waits. The nightly job can pass a longer
#: policy in, since nothing is waiting on it.
FAST_FAIL_RETRY = RetryPolicy(attempts=2, base_delay=0.25, max_delay=1.0)


class FinnhubSource:
    """
    `http_get(url, params) -> (status_code, json)` is injected so tests never
    touch the network and so a future swap to httpx does not reach into this
    file. The default uses `requests`.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: Callable[[str, dict[str, Any]], tuple[int, Any]] | None = None,
        bucket: TokenBucket | None = None,
        retry: RetryPolicy | None = None,
        timeout: float = 10.0,
        base_url: str = BASE_URL,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.finnhub_api_key) or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.bucket = bucket or per_minute(FREE_TIER_CALLS_PER_MIN)
        self.retry = retry or FAST_FAIL_RETRY
        self._http_get = http_get or self._requests_get
        self._session: Any = None

    # ── availability ────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """False when the key is blank. Callers may check this to skip work,
        but they do not have to — every method already degrades."""
        return bool(self.api_key.strip())

    # ── transport ───────────────────────────────────────────────────

    def _requests_get(self, url: str, params: dict[str, Any]) -> tuple[int, Any]:  # pragma: no cover
        import requests

        if self._session is None:
            self._session = requests.Session()
        resp = self._session.get(url, params=params, timeout=self.timeout)
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        return resp.status_code, payload

    def _call(self, path: str, params: dict[str, Any]) -> Any:
        """One throttled, retried request. Raises; `_safe` swallows."""
        return with_retry(self.retry)(self._call_once)(path, params)

    def _call_once(self, path: str, params: dict[str, Any]) -> Any:
        self.bucket.acquire()
        url = f"{self.base_url}/{path.lstrip('/')}"
        status, payload = self._http_get(url, {**params, "token": self.api_key})
        if status == 429:
            raise RateLimited("finnhub rate limit (60/min free tier)")
        if status == 401 or status == 403:
            # Bad or expired key. Not retryable, not fatal — the tape degrades.
            raise PermissionError(f"finnhub rejected the API key (HTTP {status})")
        if status >= 500:
            raise ConnectionError(f"finnhub HTTP {status}")
        if status >= 400:
            raise RuntimeError(f"finnhub HTTP {status} for {path}")
        return payload

    def _safe(self, what: str, fn: Callable[[], list], default: list | None = None) -> list:
        """
        The graceful-degradation boundary. Everything public goes through here.

        A Finnhub outage produces a log line and an empty list; it does not
        produce a 500 on the dashboard.
        """
        if not self.enabled:
            log.debug("finnhub disabled (blank settings.finnhub_api_key) — %s → []", what)
            return default if default is not None else []
        try:
            return fn() or (default if default is not None else [])
        except Exception as exc:
            log.warning("finnhub %s failed (degrading to empty): %s", what, exc)
            return default if default is not None else []

    # ── headlines ───────────────────────────────────────────────────

    def headlines(
        self,
        symbol: str,
        *,
        conid: int | None = None,
        since: date | None = None,
        until: date | None = None,
        limit: int = 25,
    ) -> list[MarketEvent]:
        """
        Company news. Finnhub is symbol-keyed and US-centric; we pass `conid`
        through purely so the resulting events stay joined to the right
        instrument, since the symbol alone is not an identity here either.
        """
        def run() -> list[MarketEvent]:
            frm = (since or (date.today() - timedelta(days=7))).isoformat()
            to = (until or date.today()).isoformat()
            payload = self._call("company-news", {"symbol": symbol, "from": frm, "to": to})
            rows = payload if isinstance(payload, list) else []
            events = [self._headline_event(r, symbol, conid) for r in rows]
            events = [e for e in events if e is not None]
            events.sort(key=lambda e: e.ts, reverse=True)
            return events[:limit]

        return self._safe(f"headlines({symbol})", run)

    def _headline_event(self, row: Any, symbol: str, conid: int | None) -> MarketEvent | None:
        if not isinstance(row, dict):
            return None
        headline = (row.get("headline") or "").strip()
        if not headline:
            return None
        return MarketEvent(
            ts=_epoch_to_dt(row.get("datetime")),
            conid=conid,
            symbol=symbol,
            event_class=EventClass.HEADLINE,
            title=headline,
            detail=(row.get("summary") or row.get("source") or "").strip(),
            reaction_label="Unscored",   # events.py pairs it with the price move
            severity=Severity.NEUTRAL,
            moved_price=False,
            url=row.get("url") or None,
        )

    # ── analyst actions ─────────────────────────────────────────────

    def analyst_actions(
        self,
        symbol: str,
        *,
        conid: int | None = None,
        since: date | None = None,
        limit: int = 25,
    ) -> list[MarketEvent]:
        """
        Upgrades, downgrades, initiations and price-target changes, merged into
        one chronological list. Two endpoints (`upgrade-downgrade` and
        `stock/price-target`) so this costs two of the 60 calls/min.
        """
        def run() -> list[MarketEvent]:
            frm = since or (date.today() - timedelta(days=90))
            events: list[MarketEvent] = []

            payload = self._call(
                "upgrade-downgrade",
                {"symbol": symbol, "from": frm.isoformat(), "to": date.today().isoformat()},
            )
            for row in payload if isinstance(payload, list) else []:
                ev = self._rating_event(row, symbol, conid)
                if ev is not None:
                    events.append(ev)

            try:
                pt = self._call("stock/price-target", {"symbol": symbol})
            except Exception as exc:
                # A missing price-target endpoint on the free tier must not lose
                # the upgrades we already have.
                log.debug("finnhub price-target unavailable for %s: %s", symbol, exc)
                pt = None
            ev = self._price_target_event(pt, symbol, conid)
            if ev is not None:
                events.append(ev)

            events.sort(key=lambda e: e.ts, reverse=True)
            return events[:limit]

        return self._safe(f"analyst_actions({symbol})", run)

    def _rating_event(self, row: Any, symbol: str, conid: int | None) -> MarketEvent | None:
        if not isinstance(row, dict):
            return None
        from_g = (row.get("fromGrade") or "").strip()
        to_g = (row.get("toGrade") or "").strip()
        action = (row.get("action") or "").strip().lower()
        firm = (row.get("company") or "").strip() or "Analyst"
        if not to_g and not action:
            return None

        severity = Severity.NEUTRAL
        if action in {"up", "upgrade"}:
            severity = Severity.GOOD
            verb = "upgrade"
        elif action in {"down", "downgrade"}:
            severity = Severity.WARNING
            verb = "downgrade"
        elif action in {"init", "initiate", "initiated"}:
            verb = "initiation"
        elif action in {"reit", "maintain", "maintains"}:
            verb = "reiteration"
        else:
            verb = action or "rating change"

        detail = f"{firm}: {from_g or 'n/a'} → {to_g or 'n/a'}"
        return MarketEvent(
            ts=_grade_date(row.get("gradeTime")),
            conid=conid,
            symbol=symbol,
            event_class=EventClass.ANALYST,
            title=f"{symbol} {verb} — {firm}",
            detail=detail,
            reaction_label="Unscored",
            severity=severity,
            moved_price=False,
        )

    def _price_target_event(self, payload: Any, symbol: str, conid: int | None) -> MarketEvent | None:
        if not isinstance(payload, dict):
            return None
        mean = safe_float(payload.get("targetMean"))
        if mean is None:
            return None
        high = safe_float(payload.get("targetHigh"))
        low = safe_float(payload.get("targetLow"))
        parts = [f"mean {mean:,.2f}"]
        if high is not None and low is not None:
            parts.append(f"range {low:,.2f}–{high:,.2f}")
        n = payload.get("numberOfAnalysts")
        if n:
            parts.append(f"{n} analysts")
        return MarketEvent(
            ts=_iso_to_dt(payload.get("lastUpdated")),
            conid=conid,
            symbol=symbol,
            event_class=EventClass.ANALYST,
            title=f"{symbol} price target {mean:,.2f}",
            detail=" · ".join(parts),
            reaction_label="Calendar",
            severity=Severity.NEUTRAL,
            moved_price=False,
        )

    # ── earnings surprises ──────────────────────────────────────────

    def earnings_surprises(
        self, symbol: str, *, conid: int | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        """
        Last N reported quarters: actual vs estimate and the surprise %.

        Returned as plain dicts rather than `EarningsRow`, because EarningsRow
        needs the price reaction and the 5-day drift, which only the bars can
        supply. `events.py` assembles them.
        """
        def run() -> list[dict[str, Any]]:
            payload = self._call("stock/earnings", {"symbol": symbol, "limit": limit})
            rows = payload if isinstance(payload, list) else []
            out: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                actual = safe_float(row.get("actual"))
                estimate = safe_float(row.get("estimate"))
                surprise_pct = safe_float(row.get("surprisePercent"))
                if surprise_pct is None and actual is not None and estimate not in (None, 0):
                    surprise_pct = (actual - estimate) / abs(estimate) * 100.0
                out.append(
                    {
                        "conid": conid,
                        "symbol": symbol,
                        "period": row.get("period"),
                        "quarter": row.get("quarter"),
                        "year": row.get("year"),
                        "eps_actual": actual,
                        "eps_estimate": estimate,
                        "eps_surprise_pct": surprise_pct,
                    }
                )
            out.sort(key=lambda r: str(r.get("period") or ""), reverse=True)
            return out[:limit]

        return self._safe(f"earnings_surprises({symbol})", run)

    def earnings_calendar(
        self, symbols: Sequence[str] | None = None, *, days_ahead: int = 21
    ) -> list[dict[str, Any]]:
        """Upcoming reports across the universe; optionally filtered to `symbols`."""
        def run() -> list[dict[str, Any]]:
            frm = date.today()
            to = frm + timedelta(days=days_ahead)
            payload = self._call(
                "calendar/earnings", {"from": frm.isoformat(), "to": to.isoformat()}
            )
            rows = (payload or {}).get("earningsCalendar") if isinstance(payload, dict) else None
            rows = rows or []
            wanted = {s.upper() for s in symbols} if symbols else None
            out = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = (row.get("symbol") or "").upper()
                if wanted is not None and sym not in wanted:
                    continue
                out.append(
                    {
                        "symbol": sym,
                        "report_date": row.get("date"),
                        "hour": row.get("hour"),
                        "eps_estimate": safe_float(row.get("epsEstimate")),
                        "revenue_estimate": safe_float(row.get("revenueEstimate")),
                    }
                )
            return out

        return self._safe("earnings_calendar", run)

    # ── bulk ────────────────────────────────────────────────────────

    def tape(self, symbols: Iterable[str], *, conids: dict[str, int] | None = None) -> list[MarketEvent]:
        """
        Headlines + analyst actions for a whole watchlist, in one call site.

        Individual symbol failures are absorbed, so one delisted ticker does not
        empty the tape.
        """
        conids = conids or {}
        events: list[MarketEvent] = []
        for symbol in symbols:
            conid = conids.get(symbol)
            events.extend(self.headlines(symbol, conid=conid))
            events.extend(self.analyst_actions(symbol, conid=conid))
        events.sort(key=lambda e: e.ts, reverse=True)
        return events


# ── helpers ─────────────────────────────────────────────────────────

def _epoch_to_dt(value: Any) -> datetime:
    f = safe_float(value)
    if f is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(f, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return datetime.now(timezone.utc)


def _grade_date(value: Any) -> datetime:
    """`gradeTime` is an epoch second on upgrade-downgrade."""
    return _epoch_to_dt(value)


def _iso_to_dt(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        txt = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
