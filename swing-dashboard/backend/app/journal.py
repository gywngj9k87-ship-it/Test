"""
Trade-journal analytics — the feature that compounds.

The raw journal is a list of `JournalEntry` rows, each snapshotting the app's
own indicator state at entry. On its own that is a log. `summarize()` turns it
into the answer the log cannot give: *which of your own setups actually work.*

The grouping dimension is the app's own **setup score** at entry (read from
`entry_snapshot["setup_score"]`). That is deliberate — it makes the journal a
running back-test of the dashboard's own signal against the outcomes the user
really got, rather than against a paper universe. If high-score entries do not
out-earn low-score ones in *this* book, the score is not earning its place on
the screen, and this is where that shows up.

Everything here is pure Python over the entries — no sources, no cache, no I/O —
so `tests/test_services.py` pins it to asserted values.

Conventions that matter for reproducing those values:
  * A trade is **closed** iff `closed_at` is set.
  * Win/loss and the R-multiple aggregates use `r_multiple`; a closed trade
    with no `r_multiple` still counts in `closed_trades` and `total_pnl` but is
    excluded from the rate/R stats (and logged, so it is not silently dropped).
  * `expectancy_r` is the mean R across a bucket — win_rate·avg_win + loss_rate·
    avg_loss by construction — because expectancy per trade is what compounds,
    not the hit rate alone.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from .models import JournalEntry, JournalStats, SetupPerformance

_log = logging.getLogger(__name__)

# Setup-score buckets. The thresholds match the score bands the rest of the app
# already uses to colour the setup score (see indicators/score.py): a "strong"
# reading is 70+, "moderate" 50–69, "weak" below 50.
STRONG_MIN = 70.0
MODERATE_MIN = 50.0

_STRONG = "strong (score ≥ 70)"
_MODERATE = "moderate (50–69)"
_WEAK = "weak (score < 50)"
_UNSCORED = "unscored"

# Bucket display order — strongest first, unscored last.
_BUCKET_ORDER = {_STRONG: 0, _MODERATE: 1, _WEAK: 2, _UNSCORED: 3}

# Below this many closed-with-R trades a bucket is too thin to crown "best",
# and below this many closed trades overall the whole breakdown is provisional.
MIN_SETUP_SAMPLE = 3
TRUSTWORTHY_SAMPLE = 20


def _score_bucket(snapshot: dict[str, float]) -> str:
    """Map an entry's snapshot to its setup-score bucket."""
    score = snapshot.get("setup_score")
    if score is None:
        return _UNSCORED
    if score >= STRONG_MIN:
        return _STRONG
    if score >= MODERATE_MIN:
        return _MODERATE
    return _WEAK


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _perf(setup: str, entries: Sequence[JournalEntry]) -> SetupPerformance:
    """Aggregate one bucket's closed trades into a SetupPerformance."""
    closed = [e for e in entries if e.closed_at is not None]
    with_r = [e for e in closed if e.r_multiple is not None]

    skipped = len(closed) - len(with_r)
    if skipped:
        _log.info(
            "journal setup %r: %d closed trade(s) carry no r_multiple — counted "
            "in total_pnl but excluded from win-rate/R stats",
            setup, skipped,
        )

    win_r = [e.r_multiple for e in with_r if e.r_multiple > 0]        # type: ignore[misc]
    loss_r = [e.r_multiple for e in with_r if e.r_multiple <= 0]      # type: ignore[misc]
    all_r = [e.r_multiple for e in with_r]                           # type: ignore[misc]

    win_rate = len(win_r) / len(with_r) if with_r else 0.0
    total_pnl = sum(e.realized_pnl for e in closed if e.realized_pnl is not None)

    return SetupPerformance(
        setup=setup,
        trades=len(closed),
        wins=len(win_r),
        win_rate=round(win_rate, 4),
        avg_win_r=round(_mean(win_r), 2),
        avg_loss_r=round(_mean(loss_r), 2),
        expectancy_r=round(_mean(all_r), 2),
        total_pnl=round(total_pnl, 2),
    )


def summarize(entries: Iterable[JournalEntry]) -> JournalStats:
    """Aggregate a journal into overall and per-setup performance."""
    entries = list(entries)
    closed = [e for e in entries if e.closed_at is not None]
    open_positions = len(entries) - len(closed)
    closed_with_r = [e for e in closed if e.r_multiple is not None]

    # per-setup breakdown, in a stable strongest-first order
    buckets: dict[str, list[JournalEntry]] = {}
    for e in entries:
        buckets.setdefault(_score_bucket(e.entry_snapshot), []).append(e)
    by_setup = sorted(
        (_perf(name, es) for name, es in buckets.items()),
        key=lambda p: _BUCKET_ORDER.get(p.setup, 99),
    )

    # Best setup: the highest-expectancy bucket that clears the sample floor,
    # counted in trades that actually carry an R-multiple (a bucket of closed
    # trades with no R data has expectancy 0 and cannot earn the crown).
    def _scored(p: SetupPerformance) -> int:
        return sum(
            1 for e in buckets[p.setup]
            if e.closed_at is not None and e.r_multiple is not None
        )

    eligible = [p for p in by_setup if _scored(p) >= MIN_SETUP_SAMPLE]
    best_setup = max(eligible, key=lambda p: p.expectancy_r).setup if eligible else None

    all_r = [e.r_multiple for e in closed_with_r]                    # type: ignore[misc]
    win_r = [r for r in all_r if r > 0]
    loss_r = [r for r in all_r if r <= 0]
    total_pnl = sum(e.realized_pnl for e in closed if e.realized_pnl is not None)

    warning = None
    if 0 < len(closed) < TRUSTWORTHY_SAMPLE:
        warning = (
            f"{len(closed)} closed trade(s) — under ~{TRUSTWORTHY_SAMPLE} the "
            "per-setup breakdown is provisional, not a verdict."
        )
    elif not closed:
        warning = "No closed trades yet — nothing to measure until a position is closed."

    return JournalStats(
        total_entries=len(entries),
        open_positions=open_positions,
        closed_trades=len(closed),
        win_rate=round(len(win_r) / len(all_r), 4) if all_r else None,
        avg_win_r=round(_mean(win_r), 2) if win_r else None,
        avg_loss_r=round(_mean(loss_r), 2) if loss_r else None,
        expectancy_r=round(_mean(all_r), 2) if all_r else None,
        total_realized_pnl=round(total_pnl, 2),
        best_setup=best_setup,
        by_setup=by_setup,
        sample_warning=warning,
    )
