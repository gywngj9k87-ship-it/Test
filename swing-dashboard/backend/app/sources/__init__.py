"""
Data sources.

    ibkr      PRIMARY — prices, history, quotes, positions, watchlists (read-only)
    yahoo     SECONDARY — fundamentals, earnings, targets, dividends, cross-check series
    finnhub   headlines, analyst actions, earnings surprises (free tier, degrades to [])
    reconcile the dual-source cross-check; nothing silently picks a winner
    base      the PriceSource protocol, retry/backoff, token bucket

Every entry point here is keyed on (conid, exchange). `symbol` is a display
label, and `resolve(symbol, exchange)` is the only place it is an input.
"""
from app.sources.base import (
    BAR_COLUMNS,
    NoCoverage,
    PriceSource,
    RateLimited,
    RetryPolicy,
    SourceError,
    TokenBucket,
    empty_bars,
    normalize_bars,
    per_minute,
    with_retry,
)

__all__ = [
    "BAR_COLUMNS",
    "NoCoverage",
    "PriceSource",
    "RateLimited",
    "RetryPolicy",
    "SourceError",
    "TokenBucket",
    "empty_bars",
    "normalize_bars",
    "per_minute",
    "with_retry",
]
