"""
DuckDB cache.

The division of labour, from the spec:

    **The nightly job writes. The API only reads.**

Which means every read path here is a local query with no network fallback —
if the cache is cold the API returns empty plus a staleness flag, and the UI
says "stale" rather than blocking a page render on a few hundred IBKR calls.
`is_stale(key, max_age)` is how a caller finds out, and `MarketOverview.stale`
is where it surfaces.

Keys follow the contract: bars, quotes, instruments and fundamentals are all
keyed on **(conid, exchange)**, plus `source` where two sources supply the same
field. That last part is what makes the reconciliation layer possible — IBKR's
and Yahoo's close for the same date coexist as separate rows rather than one
overwriting the other.

Upserts are delete-then-insert inside a transaction: idempotent by construction,
and immune to the DuckDB version differences in `ON CONFLICT` support.
"""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb
import pandas as pd

from app.config import settings
from app.models import Instrument, MarketEvent, Quote

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS instruments (
        conid            BIGINT      NOT NULL,
        exchange         VARCHAR     NOT NULL,
        symbol           VARCHAR     NOT NULL,
        name             VARCHAR,
        country          VARCHAR,
        currency         VARCHAR,
        asset_class      VARCHAR,
        sector           VARCHAR,
        industry         VARCHAR,
        theme            VARCHAR,
        leverage         DOUBLE,
        underlying_conid BIGINT,
        ter_bps          INTEGER,
        updated_at       TIMESTAMP   NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars (
        conid      BIGINT    NOT NULL,
        exchange   VARCHAR   NOT NULL,
        date       DATE      NOT NULL,
        open       DOUBLE,
        high       DOUBLE,
        low        DOUBLE,
        close      DOUBLE,
        volume     DOUBLE,
        source     VARCHAR   NOT NULL,
        step       VARCHAR   NOT NULL DEFAULT '1d',
        updated_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quotes (
        conid           BIGINT    NOT NULL,
        exchange        VARCHAR   NOT NULL,
        source          VARCHAR   NOT NULL,
        last            DOUBLE,
        bid             DOUBLE,
        ask             DOUBLE,
        change          DOUBLE,
        change_pct      DOUBLE,
        volume          DOUBLE,
        ts              TIMESTAMP,
        delayed_seconds INTEGER   NOT NULL DEFAULT 0,
        updated_at      TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamentals (
        conid      BIGINT    NOT NULL,
        exchange   VARCHAR   NOT NULL,
        source     VARCHAR   NOT NULL,
        as_of      DATE,
        payload    VARCHAR   NOT NULL,   -- JSON; kept opaque so the source-layer
                                         -- DTOs can evolve without a migration
        updated_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id             VARCHAR   NOT NULL,
        conid          BIGINT,
        symbol         VARCHAR,
        ts             TIMESTAMP NOT NULL,
        event_class    VARCHAR   NOT NULL,
        title          VARCHAR   NOT NULL,
        detail         VARCHAR,
        reaction_pct   DOUBLE,
        reaction_label VARCHAR,
        severity       VARCHAR,
        moved_price    BOOLEAN   NOT NULL DEFAULT FALSE,
        url            VARCHAR,
        source         VARCHAR,
        updated_at     TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key          VARCHAR   NOT NULL,
        last_refresh TIMESTAMP NOT NULL,
        note         VARCHAR,
        rows         BIGINT
    )
    """,
)

_INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_instruments ON instruments (conid, exchange)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_bars ON bars (conid, exchange, step, source, date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_quotes ON quotes (conid, exchange, source)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_fundamentals ON fundamentals (conid, exchange, source)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_events ON events (id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_meta ON meta (key)",
    "CREATE INDEX IF NOT EXISTS ix_bars_date ON bars (date)",
    "CREATE INDEX IF NOT EXISTS ix_events_ts ON events (ts)",
)

BAR_COLUMNS = ("open", "high", "low", "close", "volume")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm_exchange(exchange: str | None) -> str:
    return (exchange or "").strip().upper()


class Cache:
    """
    Thin, synchronous DuckDB wrapper.

    Open it once per process and share it — DuckDB connections are not
    thread-safe, so every statement is guarded by a lock. Use as a context
    manager or call `close()`.

        with Cache() as cache:
            cache.upsert_bars(693388387, "LSEETF", df, source="ibkr")
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        read_only: bool = False,
        create_dirs: bool = True,
    ) -> None:
        raw = str(path if path is not None else settings.duckdb_path)
        self.path = raw
        self.read_only = read_only
        self._lock = threading.RLock()

        if raw != ":memory:" and create_dirs:
            Path(raw).parent.mkdir(parents=True, exist_ok=True)

        if read_only and raw != ":memory:" and not Path(raw).exists():
            # Opening a non-existent file read-only fails; create the schema
            # first so a cold API process starts rather than crash-looping.
            duckdb.connect(raw).close()
            Cache(raw, read_only=False).close()

        self.conn = duckdb.connect(raw, read_only=read_only)
        if not read_only:
            self._migrate()

    # ── lifecycle ──────────────────────────────────────────────────

    def _migrate(self) -> None:
        with self._lock:
            for ddl in _DDL:
                self.conn.execute(ddl)
            for idx in _INDEXES:
                try:
                    self.conn.execute(idx)
                except duckdb.Error as exc:  # pragma: no cover - older duckdb
                    log.debug("index skipped (%s): %s", idx.split()[5], exc)
            self.conn.execute(
                "INSERT INTO meta (key, last_refresh, note, rows) "
                "SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM meta WHERE key = ?)",
                ["schema_version", _now(), str(SCHEMA_VERSION), SCHEMA_VERSION, "schema_version"],
            )

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except Exception:  # pragma: no cover
                pass

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                yield self.conn
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def _guard_write(self) -> None:
        if self.read_only:
            raise RuntimeError(
                "this Cache is open read-only — the API never writes; the nightly job does"
            )

    # ══════════════════ instruments ══════════════════

    def upsert_instruments(self, instruments: Iterable[Instrument]) -> int:
        """Idempotent on (conid, exchange)."""
        self._guard_write()
        rows = [
            (
                int(i.conid), _norm_exchange(i.exchange), i.symbol, i.name, i.country,
                i.currency, i.asset_class.value if hasattr(i.asset_class, "value") else str(i.asset_class),
                i.sector, i.industry, i.theme, i.leverage, i.underlying_conid, i.ter_bps, _now(),
            )
            for i in instruments
        ]
        if not rows:
            return 0
        with self._tx() as conn:
            conn.executemany(
                "DELETE FROM instruments WHERE conid = ? AND exchange = ?",
                [(r[0], r[1]) for r in rows],
            )
            conn.executemany(
                "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
        return len(rows)

    def upsert_instrument(self, instrument: Instrument) -> int:
        return self.upsert_instruments([instrument])

    def get_instrument(self, conid: int, exchange: str) -> Instrument | None:
        row = self._one(
            "SELECT conid, exchange, symbol, name, country, currency, asset_class, "
            "sector, industry, theme, leverage, underlying_conid, ter_bps "
            "FROM instruments WHERE conid = ? AND exchange = ?",
            [int(conid), _norm_exchange(exchange)],
        )
        return _instrument_from_row(row) if row else None

    def get_instruments(self, *, theme: str | None = None) -> list[Instrument]:
        sql = (
            "SELECT conid, exchange, symbol, name, country, currency, asset_class, "
            "sector, industry, theme, leverage, underlying_conid, ter_bps FROM instruments"
        )
        params: list[Any] = []
        if theme:
            sql += " WHERE theme = ?"
            params.append(theme)
        sql += " ORDER BY symbol, exchange"
        return [_instrument_from_row(r) for r in self._all(sql, params)]

    # ══════════════════ bars ══════════════════

    def upsert_bars(
        self,
        conid: int,
        exchange: str,
        bars: pd.DataFrame,
        *,
        source: str,
        step: str = "1d",
    ) -> int:
        """
        Replace the (conid, exchange, step, source, date) rows the frame covers.

        Two sources' bars for the same date coexist — that is deliberate, it is
        what `reconcile_series` reads back to compare.
        """
        self._guard_write()
        if bars is None or len(bars) == 0:
            return 0

        ex = _norm_exchange(exchange)
        df = bars.copy()
        if "date" not in df.columns:
            df = df.reset_index()
        cols = {str(c).strip().lower(): c for c in df.columns}
        dcol = cols.get("date") or cols.get("index")
        if dcol is None:
            raise ValueError("bar frame has no date column or index")

        dates = pd.to_datetime(df[dcol], errors="coerce")
        try:
            if getattr(dates.dt, "tz", None) is not None:
                dates = dates.dt.tz_localize(None)
        except (AttributeError, TypeError):
            pass

        rows: list[tuple] = []
        now = _now()
        for i, ts in enumerate(dates):
            if pd.isna(ts):
                continue
            r = df.iloc[i]
            rows.append(
                (
                    int(conid), ex, pd.Timestamp(ts).date(),
                    *[_num(r.get(cols.get(c, c))) for c in BAR_COLUMNS],
                    source, step, now,
                )
            )
        if not rows:
            return 0

        with self._tx() as conn:
            conn.executemany(
                "DELETE FROM bars WHERE conid = ? AND exchange = ? AND step = ? "
                "AND source = ? AND date = ?",
                [(r[0], r[1], r[9], r[8], r[2]) for r in rows],
            )
            conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def get_bars(
        self,
        conid: int,
        exchange: str,
        *,
        source: str | None = None,
        step: str = "1d",
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """
        Local read. Never touches the network — a cold cache returns an empty
        frame and the caller checks `is_stale`.
        """
        sql = (
            "SELECT date, open, high, low, close, volume FROM bars "
            "WHERE conid = ? AND exchange = ? AND step = ?"
        )
        params: list[Any] = [int(conid), _norm_exchange(exchange), step]
        if source:
            sql += " AND source = ?"
            params.append(source)
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date"
        if limit:
            sql = (
                "SELECT * FROM (" + sql.replace("ORDER BY date", "ORDER BY date DESC")
                + f" LIMIT {int(limit)}) ORDER BY date"
            )

        with self._lock:
            df = self.conn.execute(sql, params).fetch_df()

        if df is None or len(df) == 0:
            idx = pd.DatetimeIndex([], name="date")
            out = pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS}, index=idx)
        else:
            out = df.copy()
            out.index = pd.DatetimeIndex(pd.to_datetime(out.pop("date"))).normalize()
            out.index.name = "date"
        out.attrs["source"] = source or "cache"
        out.attrs["conid"] = int(conid)
        out.attrs["exchange"] = _norm_exchange(exchange)
        return out

    def bar_sources(self, conid: int, exchange: str, step: str = "1d") -> list[str]:
        return [
            r[0]
            for r in self._all(
                "SELECT DISTINCT source FROM bars WHERE conid = ? AND exchange = ? AND step = ? "
                "ORDER BY source",
                [int(conid), _norm_exchange(exchange), step],
            )
        ]

    def latest_bar_date(self, conid: int, exchange: str, source: str | None = None) -> date | None:
        sql = "SELECT max(date) FROM bars WHERE conid = ? AND exchange = ?"
        params: list[Any] = [int(conid), _norm_exchange(exchange)]
        if source:
            sql += " AND source = ?"
            params.append(source)
        row = self._one(sql, params)
        return row[0] if row and row[0] is not None else None

    # ══════════════════ quotes ══════════════════

    def upsert_quote(self, quote: Quote, exchange: str, *, source: str = "ibkr") -> int:
        self._guard_write()
        row = (
            int(quote.conid), _norm_exchange(exchange), source,
            quote.last, quote.bid, quote.ask, quote.change, quote.change_pct,
            quote.volume, _strip_tz(quote.ts), int(quote.delayed_seconds or 0), _now(),
        )
        with self._tx() as conn:
            conn.execute(
                "DELETE FROM quotes WHERE conid = ? AND exchange = ? AND source = ?",
                [row[0], row[1], row[2]],
            )
            conn.execute("INSERT INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
        return 1

    def upsert_quotes(self, quotes: Mapping[str, Quote], *, source: str = "ibkr") -> int:
        """`quotes` keyed `"conid@EXCHANGE"`, as `IBKRSource.get_quotes` returns."""
        n = 0
        for key, quote in quotes.items():
            _, _, exchange = key.partition("@")
            n += self.upsert_quote(quote, exchange, source=source)
        return n

    def get_quote(self, conid: int, exchange: str, *, source: str = "ibkr") -> Quote | None:
        row = self._one(
            "SELECT conid, last, bid, ask, change, change_pct, volume, ts, delayed_seconds "
            "FROM quotes WHERE conid = ? AND exchange = ? AND source = ?",
            [int(conid), _norm_exchange(exchange), source],
        )
        if not row:
            return None
        return Quote(
            conid=int(row[0]), last=row[1], bid=row[2], ask=row[3], change=row[4],
            change_pct=row[5], volume=row[6], ts=row[7], delayed_seconds=int(row[8] or 0),
        )

    # ══════════════════ fundamentals ══════════════════

    def upsert_fundamentals(
        self,
        conid: int,
        exchange: str,
        payload: Any,
        *,
        source: str = "yahoo",
        as_of: date | None = None,
    ) -> int:
        """`payload` may be a pydantic model, a dataclass-like, or a plain dict."""
        self._guard_write()
        blob = _to_json(payload)
        row = (
            int(conid), _norm_exchange(exchange), source,
            as_of or date.today(), blob, _now(),
        )
        with self._tx() as conn:
            conn.execute(
                "DELETE FROM fundamentals WHERE conid = ? AND exchange = ? AND source = ?",
                [row[0], row[1], row[2]],
            )
            conn.execute("INSERT INTO fundamentals VALUES (?,?,?,?,?,?)", row)
        return 1

    def get_fundamentals(
        self, conid: int, exchange: str, *, source: str = "yahoo"
    ) -> dict[str, Any] | None:
        row = self._one(
            "SELECT payload, as_of FROM fundamentals WHERE conid = ? AND exchange = ? AND source = ?",
            [int(conid), _norm_exchange(exchange), source],
        )
        if not row:
            return None
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        if isinstance(data, dict):
            data.setdefault("as_of", row[1].isoformat() if row[1] else None)
        return data

    # ══════════════════ events ══════════════════

    def upsert_events(self, events: Iterable[MarketEvent], *, source: str = "") -> int:
        """
        Deduped on a deterministic id (ts + conid + class + title), so re-running
        the nightly job does not multiply the tape.
        """
        self._guard_write()
        rows = []
        now = _now()
        for e in events:
            rows.append(
                (
                    event_id(e), e.conid, e.symbol, _strip_tz(e.ts),
                    e.event_class.value, e.title, e.detail, e.reaction_pct,
                    e.reaction_label,
                    e.severity.value if hasattr(e.severity, "value") else str(e.severity),
                    bool(e.moved_price), e.url, source, now,
                )
            )
        if not rows:
            return 0
        with self._tx() as conn:
            conn.executemany("DELETE FROM events WHERE id = ?", [(r[0],) for r in rows])
            conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def get_events(
        self,
        *,
        conid: int | None = None,
        since: datetime | None = None,
        moved_price_only: bool = False,
        limit: int = 200,
    ) -> list[MarketEvent]:
        sql = (
            "SELECT ts, conid, symbol, event_class, title, detail, reaction_pct, "
            "reaction_label, severity, moved_price, url FROM events WHERE 1 = 1"
        )
        params: list[Any] = []
        if conid is not None:
            sql += " AND conid = ?"
            params.append(int(conid))
        if since is not None:
            sql += " AND ts >= ?"
            params.append(_strip_tz(since))
        if moved_price_only:
            sql += " AND moved_price = TRUE"
        sql += f" ORDER BY ts DESC LIMIT {int(limit)}"

        out: list[MarketEvent] = []
        for r in self._all(sql, params):
            out.append(
                MarketEvent(
                    ts=r[0], conid=r[1], symbol=r[2], event_class=r[3], title=r[4],
                    detail=r[5] or "", reaction_pct=r[6], reaction_label=r[7],
                    severity=r[8] or "neutral", moved_price=bool(r[9]), url=r[10],
                )
            )
        return out

    # ══════════════════ meta / staleness ══════════════════

    def set_last_refresh(
        self, key: str, *, when: datetime | None = None, note: str | None = None, rows: int | None = None
    ) -> None:
        self._guard_write()
        with self._tx() as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", [key])
            conn.execute(
                "INSERT INTO meta VALUES (?,?,?,?)",
                [key, _strip_tz(when) or _now(), note, rows],
            )

    def get_last_refresh(self, key: str) -> datetime | None:
        row = self._one("SELECT last_refresh FROM meta WHERE key = ?", [key])
        return row[0] if row else None

    def is_stale(self, key: str, max_age: timedelta | float) -> bool:
        """
        True when `key` was never refreshed, or was refreshed longer ago than
        `max_age` (a timedelta, or seconds).

        A missing key is stale — never fresh — so a cold cache degrades to
        "stale" instead of silently serving nothing as if it were current.
        """
        age = max_age if isinstance(max_age, timedelta) else timedelta(seconds=float(max_age))
        last = self.get_last_refresh(key)
        if last is None:
            return True
        return (_now() - _strip_tz(last)) > age

    def age(self, key: str) -> timedelta | None:
        last = self.get_last_refresh(key)
        return None if last is None else (_now() - _strip_tz(last))

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("instruments", "bars", "quotes", "fundamentals", "events", "meta"):
            row = self._one(f"SELECT count(*) FROM {table}", [])
            out[table] = int(row[0]) if row else 0
        return out

    # ── internals ──────────────────────────────────────────────────

    def _one(self, sql: str, params: Sequence[Any]) -> tuple | None:
        with self._lock:
            return self.conn.execute(sql, list(params)).fetchone()

    def _all(self, sql: str, params: Sequence[Any]) -> list[tuple]:
        with self._lock:
            return self.conn.execute(sql, list(params)).fetchall()


# ── module-level helpers ────────────────────────────────────────────

def open_read_only(path: str | Path | None = None) -> Cache:
    """What the FastAPI process uses. Cannot write, cannot fetch, cannot block."""
    return Cache(path, read_only=True)


def event_id(event: MarketEvent) -> str:
    """Stable, content-derived id so the tape dedupes across nightly runs."""
    import hashlib

    raw = "|".join(
        [
            (event.ts.isoformat() if event.ts else ""),
            str(event.conid or ""),
            str(event.symbol or ""),
            str(event.event_class.value if hasattr(event.event_class, "value") else event.event_class),
            (event.title or "").strip().lower(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _strip_tz(ts: Any) -> Any:
    if isinstance(ts, datetime) and ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _to_json(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    for attr in ("model_dump", "dict"):
        fn = getattr(payload, attr, None)
        if callable(fn):
            try:
                return json.dumps(fn(mode="json") if attr == "model_dump" else fn(), default=str)
            except TypeError:
                return json.dumps(fn(), default=str)
    return json.dumps(payload, default=str)


def _instrument_from_row(row: Sequence[Any]) -> Instrument:
    return Instrument(
        conid=int(row[0]), exchange=row[1], symbol=row[2], name=row[3], country=row[4],
        currency=row[5] or "USD", asset_class=row[6] or "equity", sector=row[7],
        industry=row[8], theme=row[9], leverage=row[10],
        underlying_conid=int(row[11]) if row[11] is not None else None,
        ter_bps=int(row[12]) if row[12] is not None else None,
    )
