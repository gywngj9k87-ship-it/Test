"""
Configuration and the universe definition.

Design principle from the spec: YOU NEVER MAINTAIN A TICKER LIST BY HAND.
Your IBKR watchlists are the configuration — edit them in IBKR and the
dashboard follows. The constants here are only the market-context layer
(indices, sectors) plus the metadata IBKR cannot tell us (leverage factors,
theme grouping, sleeve routing).
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # ── IBKR (read-only; no order-placement code exists in this repo) ──
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4001          # 4001 IB Gateway live, 4002 paper, 7496 TWS
    ibkr_client_id: int = 17
    ibkr_readonly: bool = True     # ib_async connect(readonly=True). Do not change.

    # ── secondary sources ──
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")
    yahoo_enabled: bool = True

    # ── cross-check tolerances (spec: flag, never silently pick a winner) ──
    tol_close_pct: float = 0.25
    tol_volume_pct: float = 5.0
    tol_market_value_pct: float = 0.5

    # ── cache & jobs ──
    duckdb_path: str = str(ROOT / "data" / "cache.duckdb")
    nightly_refresh_cron: str = "30 22 * * 1-5"   # after the US close, local time
    quote_poll_seconds: int = 60
    max_concurrent_fetches: int = 8

    # ── indicator parameters ──
    adx_gate: float = 20.0         # below this, momentum signals are greyed out
    squeeze_percentile: float = 0.10
    concentration_limit_pct: float = 25.0
    earnings_warning_days: int = 7

    # ── setup score weights (must sum to 1.0) ──
    w_relative_strength: float = 0.30
    w_trend: float = 0.25
    w_momentum: float = 0.20
    w_volume: float = 0.15
    w_volatility: float = 0.10

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()


# ═══════════════════════════════════════════════════════════════════
# Layer 0 — market context. Resolve conids at startup via search_contracts
# and cache them; the numbers below are IBKR conids already verified where
# a comment says "verified", otherwise resolve by symbol+exchange on boot.
# ═══════════════════════════════════════════════════════════════════

BENCHMARK_CONID = 136155102          # VOO — verified. S&P 500 proxy and the RS baseline.
SEMIS_CONID = 229725622              # SMH — verified.

CONTEXT_SYMBOLS: list[tuple[str, str]] = [
    ("SPY", "ARCA"), ("QQQ", "NASDAQ"), ("IWM", "ARCA"),
    ("RSP", "ARCA"),                  # equal-weight S&P — the breadth tell
    ("VIX", "CBOE"), ("TNX", "CBOE"),
]

SECTOR_ETFS: list[tuple[str, str]] = [
    ("XLK", "ARCA"), ("XLC", "ARCA"), ("XLY", "ARCA"), ("XLP", "ARCA"),
    ("XLV", "ARCA"), ("XLF", "ARCA"), ("XLI", "ARCA"), ("XLE", "ARCA"),
    ("XLB", "ARCA"), ("XLRE", "ARCA"), ("XLU", "ARCA"),
]


# ═══════════════════════════════════════════════════════════════════
# Watchlist routing. IBKR watchlist id -> how the dashboard treats it.
# Discovered live via get_watchlists(); ids below are the user's real ones.
# ═══════════════════════════════════════════════════════════════════

WATCHLIST_ROUTING: dict[str, dict] = {
    "10":  {"name": "Favorites",  "sleeve": "swing",  "emphasis": None},
    "100": {"name": "track",      "sleeve": "income", "emphasis": None},
    "101": {"name": "Watch",      "sleeve": "swing",  "emphasis": None},
    "102": {"name": "Buy",        "sleeve": "swing",  "emphasis": "entry"},
    "103": {"name": "Hold",       "sleeve": "swing",  "emphasis": "exit"},
    "104": {"name": "space tech", "sleeve": "swing",  "emphasis": "thematic"},
}


# ═══════════════════════════════════════════════════════════════════
# Leveraged ETP registry (§2c).
#
# IBKR does not expose the leverage factor, so it lives here. Keyed on conid
# because SYMBOLS COLLIDE — all five rows below were resolved through IBKR
# contract search and two pairs share a ticker.
# ═══════════════════════════════════════════════════════════════════

LEVERAGED_ETPS: dict[int, dict] = {
    693388390: {  # verified
        "symbol": "MAG7", "exchange": "LSEETF", "country": "GB",
        "name": "Leverage Shares 5x Long Magnificent 7",
        "leverage": 5.0, "underlying_conid": 624756922,   # MAGS US, unleveraged
        "ter_bps": 75, "issuer": "Leverage Shares",
    },
    693388387: {  # verified
        "symbol": "SOXL", "exchange": "LSEETF", "country": "GB",
        "name": "Leverage Shares 4x Long Semiconductors",
        "leverage": 4.0, "underlying_conid": SEMIS_CONID,
        "ter_bps": 75, "issuer": "Leverage Shares",
    },
    73340487: {   # verified — DIFFERENT PRODUCT, SAME TICKER
        "symbol": "SOXL", "exchange": "ARCA", "country": "US",
        "name": "Direxion Daily Semiconductor Bull 3x",
        "leverage": 3.0, "underlying_conid": SEMIS_CONID,
        "ter_bps": 75, "issuer": "Direxion",
    },
    693388345: {  # resolve-and-verify on boot
        "symbol": "MAGS", "exchange": "LSEETF", "country": "GB",
        "name": "Leverage Shares -3x Short Magnificent 7",
        "leverage": -3.0, "underlying_conid": 624756922,
        "ter_bps": 75, "issuer": "Leverage Shares",
        "warning": "INVERSE. Shares a ticker with the unleveraged US long (624756922).",
    },
}

# Unleveraged instruments that share a symbol with a leveraged one.
# Present so the UI can render the collision warning on BOTH sides.
SYMBOL_COLLISIONS: dict[str, list[int]] = {
    "SOXL": [693388387, 73340487],
    "MAGS": [624756922, 693388345],
}

# The non-leveraged legs of a collision. IBKR does not group these — a symbol
# lookup would silently pick one — so the metadata the collision table needs
# (which are absent from LEVERAGED_ETPS because these carry no leverage factor)
# lives here. Resolved through IBKR contract search on 2026-08-06.
UNLEVERAGED_SIBLINGS: dict[int, dict] = {
    624756922: {
        "symbol": "MAGS", "exchange": "BATS", "country": "US",
        "name": "Roundhill Magnificent Seven ETF — unleveraged long",
    },
}


# ═══════════════════════════════════════════════════════════════════
# Theme grouping. Used for rotation and for the sector-relative RS line.
# Extend freely; anything unmapped falls into "Unclassified" and is
# reported in the nightly job log so it does not silently vanish.
# ═══════════════════════════════════════════════════════════════════

THEMES: dict[str, list[str]] = {
    "Semis":          ["NVDA", "AVGO", "AMD", "TSM", "INTC", "MU", "ARM", "ASML",
                       "SMCI", "CRDO", "SNPS", "SMH", "SOXL", "WDC", "SNDK"],
    "Mega tech":      ["AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NFLX", "ORCL"],
    "AI software":    ["PLTR", "CRWD", "CRWV", "DELL"],
    "Space tech":     ["PL", "RKLB", "ASTS", "LUNR", "RDW", "ACHR"],
    "Alt managers":   ["KKR", "BX", "APO", "BRK.B", "BRK B"],
    "Uranium & nuclear": ["URA", "NLR", "NEE"],
    "Miners & metals":   ["RIO", "MT", "BHP", "GOLD", "XAGUSD"],
    "Shipping":       ["FLNG", "HAFN", "TRMD", "BWLP", "HSHP", "GASS", "SB", "TK"],
    "Consumer / EV":  ["TSLA", "NIO", "PONY"],
    "Healthcare":     ["LLY", "UNH", "JNJ", "ABBV"],
    "China ADR":      ["BABA", "PDD", "JD"],
    "Defence":        ["RHM", "RR.", "BAH"],
}

_SYMBOL_TO_THEME = {s: t for t, syms in THEMES.items() for s in syms}


def theme_for(symbol: str) -> str:
    return _SYMBOL_TO_THEME.get(symbol, "Unclassified")


# ═══════════════════════════════════════════════════════════════════
# Income sleeve routing (§2b). A name lands in the income sleeve if it is in
# the "track" watchlist, OR is a preferred, OR its yield clears this bar and
# its liquidity does not. Momentum oscillators are NOT computed for these.
# ═══════════════════════════════════════════════════════════════════

INCOME_YIELD_FLOOR = 4.0
THIN_LIQUIDITY_ADV_USD = 1_000_000
PREFERRED_SYMBOL_MARKERS = (" PR", "-P", ".PR", "PRA", "PRB", "PRC")
