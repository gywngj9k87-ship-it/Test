"""
One-shot cache refresh — `python -m app.refresh`.

The nightly job normally fills the DuckDB cache on a cron (after the US close).
On a fresh machine the cache is empty until that fires, so the dashboard has
nothing to show on the first run. This runs the same nightly refresh once, now,
prints a plain-language summary, and exits — so "fill it with my data" is a
single command rather than a Python one-liner.

Read-only, like everything else here: it pulls prices, history, positions and
watchlists from IBKR; it never places an order. Exit code is 0 on success and 1
if the refresh reported errors (e.g. IB Gateway was not running), so it can be
wired into a script.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from .deps import build_context
from .jobs import build_jobs


async def _run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("refresh")

    ctx = build_context()                     # connects to IBKR (read-only)
    if ctx.cache is None:
        log.error("no cache available — check settings.duckdb_path is writable")
        return 1
    if ctx.ibkr is None:
        log.error(
            "no IBKR connection. Is IB Gateway running and the API enabled? "
            "Check IBKR_HOST / IBKR_PORT in your .env (paper = 4002, live = 4001)."
        )
        return 1

    log.info("refreshing the cache from IBKR — this can take a few minutes…")
    report = await build_jobs(ctx).nightly_refresh()

    print()
    print("─" * 60)
    print(f"  Finished in {report.duration_s:.0f}s")
    print(f"  Instruments loaded : {report.universe_size}")
    print(f"  Price histories    : {report.bars_fetched}")
    if report.truncated:
        capped = ", ".join(f"{n} (@{at})" for n, at in sorted(report.truncated.items()))
        print(f"  Screens capped     : {capped}")
    if report.errors:
        print(f"  Errors             : {len(report.errors)}")
        for e in report.errors:
            print(f"    • {e}")
    if report.warnings:
        print(f"  Warnings           : {len(report.warnings)}")
        for w in report.warnings[:3]:
            print(f"    • {w}")
        if len(report.warnings) > 3:
            print(f"    • …and {len(report.warnings) - 3} more (see the log above)")
    print("─" * 60)

    # Honest success test: an empty universe means nothing loaded, even when no
    # exception was raised — do not claim the dashboard is live when it is not.
    if report.errors:
        print("\nRefresh hit errors — the dashboard is missing data. See above.")
        return 1
    if report.universe_size == 0:
        print(
            "\nConnected, but loaded 0 instruments. Two usual causes:\n"
            "  1. IB Gateway isn't actually answering on IBKR_HOST/IBKR_PORT, or\n"
            "  2. the IBKR data wiring is unfinished (see CLAUDE.md P0 #2 —\n"
            "     the universe layer and the live IBKR source disagree on method\n"
            "     names/shapes, which only shows up against a real socket).\n"
            "The dashboard will keep showing sample data until this loads real names."
        )
        return 1
    print("\nDone. Start the app (or reload it) and the badge should read “● IBKR”.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
