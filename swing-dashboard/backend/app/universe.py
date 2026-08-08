"""
The universe — layers 0 to 4 — and the eleven daily screens.

Design principle from the spec, restated because it drives every decision here:
**you never maintain a ticker list by hand.** Layer 0 (indices, sectors) and
layer 1 (the ~20 names that *are* the index) are the only hard-coded lists, and
they are market structure rather than opinion. Layer 2 auto-selects the top N by
market cap per GICS sector. Layer 3 is recomputed daily. Layer 4 is whatever
IBKR says is in the book and the six watchlists — edit them in IBKR and the
dashboard follows.

Two rules enforced mechanically in this module:

  1. Every instrument is keyed on conid. SOXL is a 4x LSE ETP *and* a 3x US ETF;
     MAGS is a 1x US ETF *and* a -3x LSE inverse. Symbols are display labels.
  2. Every screen that caps its output sets `ScreenResult.truncated_at`.
     `_capped()` is the only path by which rows leave a screen, so silent
     truncation is not expressible here.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import (
    CONTEXT_SYMBOLS,
    INCOME_YIELD_FLOOR,
    LEVERAGED_ETPS,
    PREFERRED_SYMBOL_MARKERS,
    SECTOR_ETFS,
    THIN_LIQUIDITY_ADV_USD,
    WATCHLIST_ROUTING,
    theme_for,
)
from .models import (
    AssetClass,
    DriverRow,
    IndicatorSet,
    Instrument,
    ScreenName,
    ScreenResult,
)

log = logging.getLogger(__name__)


# ═══════════════════════ layer 1 — the index drivers ═══════════════════════
# ~40% of S&P 500 weight and over half the Nasdaq 100. Market structure, not a
# view: when the index moves and you don't know why, the answer is on this list.

INDEX_DRIVERS: list[tuple[str, str]] = [
    ("NVDA", "NASDAQ"), ("MSFT", "NASDAQ"), ("AAPL", "NASDAQ"),
    ("AMZN", "NASDAQ"), ("GOOGL", "NASDAQ"), ("META", "NASDAQ"),
    ("AVGO", "NASDAQ"), ("TSLA", "NASDAQ"), ("BRK B", "NYSE"),
    ("LLY", "NYSE"), ("JPM", "NYSE"), ("V", "NYSE"), ("XOM", "NYSE"),
    ("UNH", "NYSE"), ("MA", "NYSE"), ("COST", "NASDAQ"),
    ("NFLX", "NASDAQ"), ("AMD", "NASDAQ"), ("PLTR", "NASDAQ"),
    ("ORCL", "NYSE"),
]

SECTOR_LEADERS_PER_SECTOR = 4          # spec: "3-5 leaders per sector"

MEGA_CAP_USD = 200e9
LARGE_CAP_USD = 10e9
MID_CAP_USD = 2e9


class Sleeve(str, Enum):
    SWING = "swing"
    INCOME = "income"
    LEVERAGED = "leveraged"


class Layer(int, Enum):
    MARKET_CONTEXT = 0
    INDEX_DRIVERS = 1
    SECTOR_LEADERS = 2
    SCREENS = 3
    BOOK = 4


# ═══════════════════════ membership ═══════════════════════


@dataclass
class UniverseMember:
    instrument: Instrument
    layers: set[int] = field(default_factory=set)
    sleeve: Sleeve = Sleeve.SWING
    sources: set[str] = field(default_factory=set)   # "positions", "watchlist:102", ...
    emphasis: str | None = None                      # entry / exit / thematic
    held: bool = False

    @property
    def conid(self) -> int:
        return self.instrument.conid

    @property
    def key(self) -> str:
        return self.instrument.key


@dataclass
class Universe:
    members: dict[int, UniverseMember] = field(default_factory=dict)
    unclassified: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.members)

    def __iter__(self):
        return iter(self.members.values())

    def add(self, instrument: Instrument, layer: int, *,
            sleeve: Sleeve | None = None, source: str | None = None,
            emphasis: str | None = None, held: bool = False) -> UniverseMember:
        """Merge on conid. A name can be in several layers at once — VOO is a
        position, a benchmark and a Buy-list name — and we keep all of it."""
        m = self.members.get(instrument.conid)
        if m is None:
            m = UniverseMember(instrument=instrument)
            self.members[instrument.conid] = m
        else:
            m.instrument = _merge_instrument(m.instrument, instrument)
        m.layers.add(int(layer))
        if source:
            m.sources.add(source)
        if emphasis and not m.emphasis:
            m.emphasis = emphasis
        m.held = m.held or held
        if sleeve is not None:
            # leveraged and income are stickier than swing: a name that qualifies
            # for a specialist sleeve keeps it even if a swing watchlist also
            # holds it, because the specialist view is the safer default.
            if m.sleeve == Sleeve.SWING or sleeve != Sleeve.SWING:
                m.sleeve = sleeve
        return m

    # ── views ──
    def by_layer(self, layer: int) -> list[UniverseMember]:
        return [m for m in self.members.values() if int(layer) in m.layers]

    def by_sleeve(self, sleeve: Sleeve) -> list[UniverseMember]:
        return [m for m in self.members.values() if m.sleeve == sleeve]

    def conids(self) -> list[int]:
        return list(self.members)

    def instruments(self) -> list[Instrument]:
        return [m.instrument for m in self.members.values()]

    def held(self) -> list[UniverseMember]:
        return [m for m in self.members.values() if m.held]

    def scan_set(self) -> list[UniverseMember]:
        """Names that get the full swing indicator set + go into the screens."""
        return [m for m in self.members.values() if m.sleeve != Sleeve.INCOME]

    def poll_set(self) -> list[int]:
        """Intraday quote polling: watchlists and the book only. Never the
        whole universe — that is what the nightly batch is for."""
        return [m.conid for m in self.members.values()
                if m.held or any(s.startswith("watchlist:") for s in m.sources)]


def _merge_instrument(old: Instrument, new: Instrument) -> Instrument:
    """Field-wise merge; a non-null new value wins, nulls never overwrite."""
    data = old.model_dump()
    for k, v in new.model_dump().items():
        if v is not None and (data.get(k) is None or k in {"symbol", "exchange"}):
            data[k] = v
    return Instrument(**data)


# ═══════════════════════ instrument construction ═══════════════════════


def to_instrument(obj: Any, *, symbol: str | None = None,
                  exchange: str | None = None) -> Instrument | None:
    """Normalise whatever the IBKR source hands back into an `Instrument`.

    Accepts an `Instrument`, a mapping, or anything with attributes. Returns
    None when there is no conid — a nameless row is not an identity and must
    not silently become one keyed on its symbol.
    """
    if obj is None:
        return None
    if isinstance(obj, Instrument):
        return apply_registry(obj)
    if isinstance(obj, Mapping):
        get = obj.get
    else:
        def get(k, default=None):
            return getattr(obj, k, default)

    conid = get("conid") or get("conId")
    if conid is None:
        return None
    sym = get("symbol") or symbol or str(conid)
    exch = get("exchange") or get("listingExchange") or exchange or "SMART"
    inst = Instrument(
        conid=int(conid),
        symbol=str(sym),
        name=get("name") or get("companyName"),
        exchange=str(exch),
        country=get("country"),
        currency=get("currency") or "USD",
        asset_class=_asset_class(get("asset_class") or get("assetClass")),
        sector=get("sector"),
        industry=get("industry"),
    )
    return apply_registry(inst)


def _asset_class(raw: Any) -> AssetClass:
    if isinstance(raw, AssetClass):
        return raw
    if isinstance(raw, str):
        try:
            return AssetClass(raw.lower())
        except ValueError:
            mapped = {"stk": AssetClass.EQUITY, "etf": AssetClass.ETF,
                      "ind": AssetClass.INDEX, "cash": AssetClass.FX,
                      "fund": AssetClass.FUND}
            return mapped.get(raw.lower(), AssetClass.EQUITY)
    return AssetClass.EQUITY


def apply_registry(inst: Instrument) -> Instrument:
    """Stamp leverage metadata and the theme. Keyed on conid — never on symbol,
    because two of these products share a ticker with something else entirely.
    """
    data = inst.model_dump()
    meta = LEVERAGED_ETPS.get(inst.conid)
    if meta:
        data.update(
            asset_class=AssetClass.LEVERAGED_ETP,
            leverage=float(meta["leverage"]),
            underlying_conid=meta.get("underlying_conid"),
            ter_bps=meta.get("ter_bps"),
            name=data.get("name") or meta.get("name"),
            exchange=meta.get("exchange", data["exchange"]),
            country=data.get("country") or meta.get("country"),
        )
    elif is_preferred(inst.symbol):
        data["asset_class"] = AssetClass.PREFERRED
    if not data.get("theme"):
        data["theme"] = theme_for(inst.symbol)
    return Instrument(**data)


def is_preferred(symbol: str) -> bool:
    s = (symbol or "").upper()
    return any(s.endswith(m) or m in s for m in PREFERRED_SYMBOL_MARKERS)


# ═══════════════════════ sleeve routing ═══════════════════════


def route_sleeve(
    instrument: Instrument,
    *,
    watchlist_sleeve: str | None = None,
    current_yield: float | None = None,
    adv_usd_20d: float | None = None,
) -> Sleeve:
    """Which of the three views owns this instrument.

    Order matters and is deliberate:
      1. the leveraged registry (keyed on conid) — §2c beats everything;
      2. preferred-symbol markers — §2b, momentum oscillators would be noise;
      3. the watchlist routing table ("track" -> income);
      4. the yield/liquidity rule: yield clears the floor AND liquidity does
         not clear the bar. A high-yielder that trades $50m a day is still a
         swing name; a thin one is an income holding whether you like it or not.
    """
    if instrument.conid in LEVERAGED_ETPS or instrument.asset_class is AssetClass.LEVERAGED_ETP:
        return Sleeve.LEVERAGED
    if instrument.asset_class is AssetClass.PREFERRED or is_preferred(instrument.symbol):
        return Sleeve.INCOME
    if watchlist_sleeve == Sleeve.INCOME.value:
        return Sleeve.INCOME
    if (current_yield is not None and current_yield >= INCOME_YIELD_FLOOR
            and adv_usd_20d is not None and adv_usd_20d < THIN_LIQUIDITY_ADV_USD):
        return Sleeve.INCOME
    return Sleeve.SWING


# ═══════════════════════ layers ═══════════════════════


def _resolve_many(ibkr: Any, pairs: Sequence[tuple[str, str]],
                  universe: Universe) -> list[Instrument]:
    out: list[Instrument] = []
    for symbol, exchange in pairs:
        try:
            inst = to_instrument(ibkr.resolve(symbol, exchange),
                                 symbol=symbol, exchange=exchange)
        except Exception as exc:
            universe.warnings.append(f"resolve failed for {symbol}@{exchange}: {exc}")
            continue
        if inst is None:
            universe.warnings.append(f"{symbol}@{exchange} resolved without a conid — skipped")
            continue
        out.append(inst)
    return out


def build_layer0(ibkr: Any, universe: Universe) -> Universe:
    """Market context: indices, risk/macro proxies, the breadth pair, 11 sectors."""
    for inst in _resolve_many(ibkr, CONTEXT_SYMBOLS, universe):
        universe.add(inst, Layer.MARKET_CONTEXT, sleeve=Sleeve.SWING, source="context")
    for inst in _resolve_many(ibkr, SECTOR_ETFS, universe):
        universe.add(inst, Layer.MARKET_CONTEXT, sleeve=Sleeve.SWING, source="sector_etf")
    return universe


def build_layer1(ibkr: Any, universe: Universe) -> Universe:
    """The ~20 names that *are* the index."""
    for inst in _resolve_many(ibkr, INDEX_DRIVERS, universe):
        universe.add(inst, Layer.INDEX_DRIVERS, sleeve=Sleeve.SWING, source="index_driver")
    return universe


def build_layer2(
    universe: Universe,
    candidates: Iterable[Instrument],
    market_caps: Mapping[int, float],
    *,
    per_sector: int = SECTOR_LEADERS_PER_SECTOR,
) -> Universe:
    """Sector representatives: top N by market cap within each GICS sector.

    Auto-selected so the list maintains itself. Names with no sector or no
    market cap cannot be ranked and are reported rather than dropped quietly.
    """
    buckets: dict[str, list[Instrument]] = {}
    unranked: list[str] = []
    for inst in candidates:
        if not inst.sector:
            unranked.append(f"{inst.symbol}#{inst.conid} (no sector)")
            continue
        if market_caps.get(inst.conid) is None:
            unranked.append(f"{inst.symbol}#{inst.conid} (no market cap)")
            continue
        buckets.setdefault(inst.sector, []).append(inst)

    for sector, names in buckets.items():
        names.sort(key=lambda i: market_caps.get(i.conid) or 0.0, reverse=True)
        for inst in names[:per_sector]:
            universe.add(inst, Layer.SECTOR_LEADERS, sleeve=Sleeve.SWING,
                         source=f"sector_leader:{sector}")
    if unranked:
        universe.warnings.append(
            f"layer 2: {len(unranked)} candidate(s) could not be ranked by market cap"
        )
        log.info("layer 2 unranked: %s", ", ".join(unranked[:25]))
    return universe


def build_layer4(ibkr: Any, universe: Universe) -> Universe:
    """The book: positions plus every name in the six IBKR watchlists.

    Watchlist ids come from `config.WATCHLIST_ROUTING`; a watchlist that turns
    up in IBKR but not in the routing table is ingested as a swing list *and*
    reported, because silently ignoring a list the user created is the failure
    mode this layer exists to prevent.
    """
    # ── positions ──
    try:
        positions = ibkr.get_positions() or []
    except Exception as exc:
        universe.warnings.append(f"get_positions failed: {exc}")
        positions = []

    for p in positions:
        raw = p.get("instrument") if isinstance(p, Mapping) else getattr(p, "instrument", p)
        inst = to_instrument(raw if raw is not None else p)
        if inst is None:
            continue
        universe.add(inst, Layer.BOOK, sleeve=route_sleeve(inst),
                     source="positions", held=True)

    # ── watchlists ──
    try:
        discovered = ibkr.get_watchlists() or []
    except Exception as exc:
        universe.warnings.append(f"get_watchlists failed: {exc}")
        discovered = []

    ids: list[str] = []
    for wl in discovered:
        wid = wl.get("id") if isinstance(wl, Mapping) else getattr(wl, "id", None)
        if wid is not None:
            ids.append(str(wid))
    for wid in WATCHLIST_ROUTING:
        if wid not in ids:
            ids.append(wid)

    for wid in ids:
        routing = WATCHLIST_ROUTING.get(wid)
        if routing is None:
            routing = {"name": f"watchlist {wid}", "sleeve": Sleeve.SWING.value,
                       "emphasis": None}
            universe.warnings.append(
                f"watchlist {wid} is not in WATCHLIST_ROUTING — treated as swing"
            )
        try:
            rows = ibkr.get_watchlist(wid) or []
        except Exception as exc:
            universe.warnings.append(f"get_watchlist({wid}) failed: {exc}")
            continue

        for row in rows:
            inst = to_instrument(row)
            if inst is None:
                sym = (row.get("symbol") if isinstance(row, Mapping)
                       else getattr(row, "symbol", "?"))
                universe.warnings.append(
                    f"{routing['name']}: '{sym}' has no conid — cannot be keyed, skipped"
                )
                continue
            universe.add(
                inst, Layer.BOOK,
                sleeve=route_sleeve(inst, watchlist_sleeve=routing.get("sleeve")),
                source=f"watchlist:{wid}",
                emphasis=routing.get("emphasis"),
            )
    return universe


def collect_unclassified(universe: Universe) -> list[str]:
    """Names whose theme fell through to 'Unclassified'. Logged nightly so they
    do not silently vanish from the rotation view."""
    out = sorted({m.instrument.symbol for m in universe
                  if (m.instrument.theme or "Unclassified") == "Unclassified"})
    universe.unclassified = out
    return out


def assemble_universe(
    ibkr: Any,
    *,
    market_caps: Mapping[int, float] | None = None,
    sector_candidates: Iterable[Instrument] | None = None,
) -> Universe:
    """Layers 0, 1, 2 and 4. Layer 3 is the screens and needs indicator data,
    so it is applied afterwards via `run_screens` + `attach_screen_layer`."""
    u = Universe()
    build_layer0(ibkr, u)
    build_layer1(ibkr, u)
    build_layer4(ibkr, u)
    if market_caps:
        candidates = list(sector_candidates) if sector_candidates is not None else u.instruments()
        build_layer2(u, candidates, market_caps)
    collect_unclassified(u)
    return u


def attach_screen_layer(universe: Universe,
                        results: Mapping[ScreenName, ScreenResult]) -> Universe:
    """Anything a screen surfaced today is in layer 3 for today."""
    for res in results.values():
        for row in res.rows:
            m = universe.members.get(row.conid)
            if m is not None:
                m.layers.add(int(Layer.SCREENS))
                m.sources.add(f"screen:{res.screen.value}")
    return universe


def cap_bucket(market_cap: float | None) -> str | None:
    """Mega / Large / Mid / Small — the cross-cutting filter on every screen."""
    if market_cap is None:
        return None
    if market_cap >= MEGA_CAP_USD:
        return "mega"
    if market_cap >= LARGE_CAP_USD:
        return "large"
    if market_cap >= MID_CAP_USD:
        return "mid"
    return "small"


# ═══════════════════════ layer 3 — the eleven screens ═══════════════════════


@dataclass
class ScanRow:
    """One scanned name, flattened to exactly what the screens need.

    Built from an `IndicatorSet` plus the few event-shaped facts the indicator
    engine does not own (earnings recency, squeeze release, cross recency).
    """
    instrument: Instrument
    last: float
    change_pct: float = 0.0
    return_1w: float = 0.0
    return_4w: float = 0.0
    return_13w: float = 0.0
    rs_vs_index_4w: float = 0.0
    rs_vs_index_13w: float = 0.0
    above_50dma: bool = False
    above_200dma: bool = False
    pct_from_high: float = 0.0
    pct_from_low: float = 0.0
    at_new_high: bool = False
    at_new_low: bool = False
    rel_volume: float = 1.0
    gap_pct: float = 0.0
    atr14: float | None = None
    rsi14: float | None = None
    bb_squeeze: bool = False
    squeeze_released: bool = False
    dma_cross: str | None = None            # "golden" | "death"
    days_since_cross: int | None = None
    days_since_earnings: int | None = None
    earnings_reaction_pct: float | None = None
    market_cap: float | None = None

    @property
    def conid(self) -> int:
        return self.instrument.conid

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @classmethod
    def from_indicator_set(cls, instrument: Instrument, ind: IndicatorSet,
                           **extra: Any) -> "ScanRow":
        t, m, v, vol, lv = ind.trend, ind.momentum, ind.volatility, ind.volume, ind.levels
        hi = t.pct_from_52w_high
        lo = t.pct_from_52w_low
        row = cls(
            instrument=instrument,
            last=ind.close,
            change_pct=ind.change_pct or 0.0,
            return_4w=m.roc20 or 0.0,
            rs_vs_index_4w=m.rs_vs_index_4w or 0.0,
            rs_vs_index_13w=m.rs_vs_index_13w or 0.0,
            above_50dma=bool(t.ema50 is not None and ind.close > t.ema50),
            above_200dma=bool(t.ema200 is not None and ind.close > t.ema200),
            pct_from_high=hi if hi is not None else 0.0,
            pct_from_low=lo if lo is not None else 0.0,
            at_new_high=bool(hi is not None and hi >= -0.05),
            at_new_low=bool(lo is not None and lo <= 0.05),
            rel_volume=vol.rel_volume if vol.rel_volume is not None else 1.0,
            gap_pct=lv.gap_pct or 0.0,
            atr14=v.atr14,
            rsi14=m.rsi14,
            bb_squeeze=bool(v.bb_squeeze),
            dma_cross=("golden" if t.golden_cross else
                       "death" if t.golden_cross is False and t.days_since_cross is not None
                       else None),
            days_since_cross=t.days_since_cross,
        )
        for k, val in extra.items():
            if hasattr(row, k):
                setattr(row, k, val)
        return row

    def to_driver_row(self) -> DriverRow:
        return DriverRow(
            conid=self.instrument.conid,
            symbol=self.instrument.symbol,
            exchange=self.instrument.exchange,
            theme=self.instrument.theme,
            last=self.last,
            return_1w=self.return_1w,
            return_4w=self.return_4w,
            return_13w=self.return_13w,
            rs_vs_index_13w=self.rs_vs_index_13w,
            above_50dma=self.above_50dma,
            pct_from_high=self.pct_from_high,
            at_new_high=self.at_new_high,
        )


# Per-screen caps. Every one of these is reported through `truncated_at`.
SCREEN_LIMITS: dict[ScreenName, int] = {
    ScreenName.GAINERS: 20,
    ScreenName.LOSERS: 20,
    ScreenName.UNUSUAL_VOLUME: 25,
    ScreenName.NEW_HIGHS: 50,
    ScreenName.NEW_LOWS: 50,
    ScreenName.RS_LEADERS: 25,
    ScreenName.GAP_UP: 25,
    ScreenName.GAP_DOWN: 25,
    ScreenName.EARNINGS_MOVERS: 25,
    ScreenName.SQUEEZE: 25,
    ScreenName.DMA_CROSS: 25,
}

UNUSUAL_VOLUME_MULT = 2.0
GAP_THRESHOLD_PCT = 3.0
EARNINGS_MOVE_PCT = 5.0
EARNINGS_WINDOW_SESSIONS = 2
CROSS_FRESH_SESSIONS = 5


def _capped(screen: ScreenName, rows: Sequence[ScanRow],
            limit: int | None = None) -> ScreenResult:
    """The ONLY way rows leave a screen. If the list was cut, say where."""
    cap = SCREEN_LIMITS.get(screen) if limit is None else limit
    truncated = None
    kept = list(rows)
    if cap is not None and len(kept) > cap:
        truncated = cap
        kept = kept[:cap]
    return ScreenResult(
        screen=screen,
        rows=[r.to_driver_row() for r in kept],
        truncated_at=truncated,
    )


def screen_gainers(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    s = sorted(rows, key=lambda r: r.change_pct, reverse=True)
    return _capped(ScreenName.GAINERS, [r for r in s if r.change_pct > 0], **kw)


def screen_losers(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    s = sorted(rows, key=lambda r: r.change_pct)
    return _capped(ScreenName.LOSERS, [r for r in s if r.change_pct < 0], **kw)


def screen_unusual_volume(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [r for r in rows if r.rel_volume > UNUSUAL_VOLUME_MULT]
    hits.sort(key=lambda r: r.rel_volume, reverse=True)
    return _capped(ScreenName.UNUSUAL_VOLUME, hits, **kw)


def screen_new_highs(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [r for r in rows if r.at_new_high]
    hits.sort(key=lambda r: r.return_13w, reverse=True)
    return _capped(ScreenName.NEW_HIGHS, hits, **kw)


def screen_new_lows(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [r for r in rows if r.at_new_low]
    hits.sort(key=lambda r: r.return_13w)
    return _capped(ScreenName.NEW_LOWS, hits, **kw)


def screen_rs_leaders(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    """Outperforming the benchmark over BOTH 1m and 3m. The single most useful
    swing screen in the spec, and the reason RS is 30% of the setup score."""
    hits = [r for r in rows if r.rs_vs_index_4w > 0 and r.rs_vs_index_13w > 0]
    hits.sort(key=lambda r: r.rs_vs_index_13w, reverse=True)
    return _capped(ScreenName.RS_LEADERS, hits, **kw)


def screen_gap_up(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [r for r in rows if r.gap_pct > GAP_THRESHOLD_PCT]
    hits.sort(key=lambda r: r.gap_pct, reverse=True)
    return _capped(ScreenName.GAP_UP, hits, **kw)


def screen_gap_down(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [r for r in rows if r.gap_pct < -GAP_THRESHOLD_PCT]
    hits.sort(key=lambda r: r.gap_pct)
    return _capped(ScreenName.GAP_DOWN, hits, **kw)


def screen_earnings_movers(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [
        r for r in rows
        if r.days_since_earnings is not None
        and 0 <= r.days_since_earnings <= EARNINGS_WINDOW_SESSIONS
        and abs(r.earnings_reaction_pct if r.earnings_reaction_pct is not None
                else r.change_pct) > EARNINGS_MOVE_PCT
    ]
    hits.sort(key=lambda r: abs(r.earnings_reaction_pct
                                if r.earnings_reaction_pct is not None
                                else r.change_pct), reverse=True)
    return _capped(ScreenName.EARNINGS_MOVERS, hits, **kw)


def screen_squeeze(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    """Bollinger compression, and the release that follows it. Released
    squeezes rank first — the compression is the setup, the release is the
    trade."""
    hits = [r for r in rows if r.bb_squeeze or r.squeeze_released]
    hits.sort(key=lambda r: (r.squeeze_released, abs(r.change_pct)), reverse=True)
    return _capped(ScreenName.SQUEEZE, hits, **kw)


def screen_dma_cross(rows: Sequence[ScanRow], **kw) -> ScreenResult:
    hits = [
        r for r in rows
        if r.dma_cross in ("golden", "death")
        and r.days_since_cross is not None
        and r.days_since_cross <= CROSS_FRESH_SESSIONS
    ]
    hits.sort(key=lambda r: (r.days_since_cross or 0, -r.return_13w))
    return _capped(ScreenName.DMA_CROSS, hits, **kw)


SCREENS = {
    ScreenName.GAINERS: screen_gainers,
    ScreenName.LOSERS: screen_losers,
    ScreenName.UNUSUAL_VOLUME: screen_unusual_volume,
    ScreenName.NEW_HIGHS: screen_new_highs,
    ScreenName.NEW_LOWS: screen_new_lows,
    ScreenName.RS_LEADERS: screen_rs_leaders,
    ScreenName.GAP_UP: screen_gap_up,
    ScreenName.GAP_DOWN: screen_gap_down,
    ScreenName.EARNINGS_MOVERS: screen_earnings_movers,
    ScreenName.SQUEEZE: screen_squeeze,
    ScreenName.DMA_CROSS: screen_dma_cross,
}
assert set(SCREENS) == set(ScreenName), "all eleven ScreenName values must be implemented"


def run_screen(screen: ScreenName, rows: Sequence[ScanRow],
               *, cap_filter: str | None = None,
               sector: str | None = None) -> ScreenResult:
    """Run one screen, with the optional cross-cutting cap / sector filters."""
    subset = rows
    if cap_filter:
        subset = [r for r in subset if cap_bucket(r.market_cap) == cap_filter]
    if sector:
        subset = [r for r in subset if (r.instrument.sector or "") == sector]
    return SCREENS[screen](subset)


def run_screens(rows: Sequence[ScanRow], **kw) -> dict[ScreenName, ScreenResult]:
    """All eleven. Truncations are logged as well as reported on the model —
    the nightly job asserts on this log line."""
    results: dict[ScreenName, ScreenResult] = {}
    for name in ScreenName:
        res = run_screen(name, rows, **kw)
        results[name] = res
        if res.truncated_at is not None:
            log.info("screen %s truncated at %d rows", name.value, res.truncated_at)
    return results


def truncated_screens(results: Mapping[ScreenName, ScreenResult]) -> dict[str, int]:
    return {n.value: r.truncated_at for n, r in results.items()
            if r.truncated_at is not None}
