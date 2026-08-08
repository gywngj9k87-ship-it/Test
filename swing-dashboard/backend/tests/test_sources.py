"""
Unit tests for the data-source layer.

No network. IBKR, Yahoo and Finnhub are all driven through injected fakes with
recorded-shape payloads, because the sandbox has no route to any of them and
because these behaviours must hold whether or not the venue is up.

The five the spec asks for, plus the invariants that would be expensive to
discover in production:

  * reconcile flags a >0.25% close divergence and passes a 0.1% one
  * detect_corporate_action fires on the NAKA shape (34 @ 169.65 vs 4.85) and
    does NOT fire on a genuine −50% drawdown
  * the Yahoo suffix table maps LSEETF→.L and FWB→.DE
  * cache upsert is idempotent
  * finnhub returns [] rather than raising when the key is blank
  * (extra) IBKR never routes a non-US listing through SMART
  * (extra) no order-placement code exists anywhere in the repo
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cache import Cache, event_id                                    # noqa: E402
from app.models import (                                                 # noqa: E402
    AssetClass,
    CostBasisStatus,
    EventClass,
    Instrument,
    MarketEvent,
    Quote,
    Severity,
)
from app.sources import base, finnhub, ibkr, reconcile, yahoo            # noqa: E402


# ═══════════════════════════ fixtures ═══════════════════════════

def _sessions(n: int = 60, start: str = "2026-05-01") -> pd.DatetimeIndex:
    """n business days — bars are daily and we only ever compare on dates."""
    return pd.bdate_range(start=start, periods=n, name="date")


def make_bars(closes, index=None, *, source: str = "ibkr", volume=1_000_000.0) -> pd.DataFrame:
    idx = index if index is not None else _sessions(len(closes))
    closes = list(closes)
    frame = pd.DataFrame(
        {
            "open": [c * 0.99 for c in closes],
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": [volume] * len(closes),
        },
        index=idx[: len(closes)],
    )
    return base.normalize_bars(frame, source=source)


@pytest.fixture
def cache(tmp_path) -> Cache:
    c = Cache(tmp_path / "test.duckdb")
    yield c
    c.close()


SOXL_LSE = Instrument(
    conid=693388387, symbol="SOXL", exchange="LSEETF", country="GB", currency="USD",
    asset_class=AssetClass.LEVERAGED_ETP, leverage=4.0,
)
SOXL_US = Instrument(
    conid=73340487, symbol="SOXL", exchange="ARCA", country="US",
    asset_class=AssetClass.LEVERAGED_ETP, leverage=3.0,
)


# ═══════════════════════════ 1. reconcile — close divergence ═══════════════════════════

class TestReconcileSeries:
    def test_flags_close_divergence_above_tolerance(self):
        """0.4% > the 0.25% tolerance from settings → breached."""
        idx = _sessions(40)
        base_closes = [100.0 + i * 0.1 for i in range(40)]
        ibkr_df = make_bars(base_closes, idx, source="ibkr")
        # every session 0.4% adrift
        yahoo_df = make_bars([c / 1.004 for c in base_closes], idx, source="yahoo")

        recs = reconcile.reconcile_series(ibkr_df, yahoo_df, reconcile.Tolerances())
        close_rec = next(r for r in recs if r.field == "close")

        assert close_rec.breached is True
        assert close_rec.tolerance_pct == pytest.approx(0.25)
        assert close_rec.diff_pct == pytest.approx(0.4, abs=0.02)
        assert reconcile.any_breached(recs) is True
        # the value is returned WITH the flag, never silently resolved
        assert close_rec.ibkr is not None and close_rec.yahoo is not None
        assert "IBKR value retained" in (close_rec.note or "")

    def test_passes_close_divergence_below_tolerance(self):
        """0.1% < 0.25% → not breached, but still reported."""
        idx = _sessions(40)
        base_closes = [100.0 + i * 0.1 for i in range(40)]
        ibkr_df = make_bars(base_closes, idx, source="ibkr")
        yahoo_df = make_bars([c / 1.001 for c in base_closes], idx, source="yahoo")

        recs = reconcile.reconcile_series(ibkr_df, yahoo_df, reconcile.Tolerances())
        close_rec = next(r for r in recs if r.field == "close")

        assert close_rec.breached is False
        assert close_rec.diff_pct == pytest.approx(0.1, abs=0.02)
        assert not reconcile.any_breached(recs)
        assert "agrees within" in (close_rec.note or "")

    def test_boundary_is_strictly_greater_than(self):
        """Exactly at tolerance is a pass; a hair over is a breach."""
        idx = _sessions(10)
        at = reconcile.reconcile_series(
            make_bars([100.0] * 10, idx), make_bars([100.0 / 1.0025] * 10, idx)
        )
        over = reconcile.reconcile_series(
            make_bars([100.0] * 10, idx), make_bars([100.0 / 1.0030] * 10, idx)
        )
        assert next(r for r in at if r.field == "close").breached is False
        assert next(r for r in over if r.field == "close").breached is True

    def test_single_session_divergence_is_caught_and_itemised(self):
        """One bad print in an otherwise clean series still breaches."""
        idx = _sessions(30)
        closes = [50.0] * 30
        ibkr_df = make_bars(closes, idx)
        bad = list(closes)
        bad[17] = 50.0 * 1.06          # a 6% divergence on one day
        yahoo_df = make_bars(bad, idx, source="yahoo")

        recs = reconcile.reconcile_series(ibkr_df, yahoo_df)
        summary = next(r for r in recs if r.field == "close")
        assert summary.breached is True
        detail = [r for r in recs if r.field.startswith("close@")]
        assert len(detail) == 1
        assert detail[0].field == f"close@{idx[17].date().isoformat()}"

    def test_volume_uses_its_own_looser_tolerance(self):
        idx = _sessions(20)
        ibkr_df = make_bars([10.0] * 20, idx, volume=1_000_000.0)
        yahoo_df = make_bars([10.0] * 20, idx, source="yahoo", volume=1_030_000.0)

        recs = reconcile.reconcile_series(ibkr_df, yahoo_df)
        vol = next(r for r in recs if r.field == "volume")
        assert vol.tolerance_pct == pytest.approx(5.0)
        assert vol.breached is False      # 3% < 5%

    def test_no_overlap_is_breached_not_silent(self):
        a = make_bars([10.0] * 10, _sessions(10, "2026-01-05"))
        b = make_bars([10.0] * 10, _sessions(10, "2025-01-06"), source="yahoo")
        recs = reconcile.reconcile_series(a, b)
        assert len(recs) == 1
        assert recs[0].field == "coverage"
        assert recs[0].breached is True

    def test_missing_yahoo_series_degrades_without_breaching(self):
        """LSE ETPs Yahoo does not carry: no cross-check, but not an error."""
        recs = reconcile.reconcile_series(make_bars([10.0] * 10), base.empty_bars("yahoo"))
        assert len(recs) == 1
        assert recs[0].breached is False
        assert "unverified" in (recs[0].note or "").lower()

    def test_truncation_is_announced(self):
        idx = _sessions(40)
        ibkr_df = make_bars([10.0] * 40, idx)
        yahoo_df = make_bars([10.0 * 1.05] * 40, idx, source="yahoo")
        recs = reconcile.reconcile_series(ibkr_df, yahoo_df)
        assert any(r.field == "close.truncated" and r.breached for r in recs)


class TestSplitAdjustment:
    def test_constant_ratio_flags_unapplied_reverse_split(self):
        idx = _sessions(30)
        closes = [4.0 + i * 0.05 for i in range(30)]
        ibkr_df = make_bars(closes, idx)
        yahoo_df = make_bars([c / 20.0 for c in closes], idx, source="yahoo")

        rec = reconcile.detect_split_adjustment(ibkr_df["close"], yahoo_df["close"])
        assert rec.breached is True
        assert "20:1" in (rec.note or "") or "1:20" in (rec.note or "")

    def test_step_change_in_ratio_is_flagged(self):
        """
        The nastier case: the two series agree for most of the window, then one
        of them applies a 1:2 split and the other does not. The median ratio is
        still 1.0, so only the step test catches it.
        """
        idx = _sessions(30)
        ibkr_closes = [10.0] * 30
        yahoo_closes = [10.0] * 20 + [5.0] * 10
        rec = reconcile.detect_split_adjustment(
            pd.Series(ibkr_closes, index=idx), pd.Series(yahoo_closes, index=idx)
        )
        assert rec.breached is True
        assert "steps from" in (rec.note or "")

    def test_matching_adjustment_passes(self):
        idx = _sessions(30)
        s = pd.Series([10.0 + i * 0.1 for i in range(30)], index=idx)
        rec = reconcile.detect_split_adjustment(s, s * 1.0005)
        assert rec.breached is False


class TestResolution:
    def test_ibkr_wins_for_price_and_carries_the_flag(self):
        r = reconcile.resolve_price("last", 4.85, 4.90)
        assert r.value == 4.85
        assert r.winner == "ibkr"
        assert r.breached is True                      # ~1% > 0.25%
        assert "IBKR retained" in (r.reconciliation.note or "")

    def test_yahoo_wins_for_fundamentals(self):
        r = reconcile.resolve_fundamental("forward_pe", 30.0, 28.0)
        assert r.value == 28.0
        assert r.winner == "yahoo"
        assert r.breached is True
        assert "Yahoo retained" in (r.reconciliation.note or "")

    def test_single_source_is_not_a_breach(self):
        r = reconcile.resolve_price("last", 4.85, None)
        assert r.value == 4.85
        assert r.winner == "only-source"
        assert r.breached is False


# ═══════════════════════════ 2. corporate action / NAKA ═══════════════════════════

class TestDetectCorporateAction:
    #: The real position from the account, verbatim.
    NAKA_QTY = 34
    NAKA_AVG_COST = 169.65
    NAKA_LAST = 4.85

    def test_fires_on_the_naka_shape(self):
        """
        34 shares @ $169.65 against a $4.85 market, and a price history that
        never trades above ~$12 → the basis is a pre-split number.
        """
        history = make_bars([11.0, 10.2, 9.4, 8.1, 7.5, 6.9, 6.0, 5.4, 5.1, 4.85])
        status = reconcile.detect_corporate_action(
            history, self.NAKA_AVG_COST, self.NAKA_LAST
        )
        assert status is CostBasisStatus.CORPORATE_ACTION_SUSPECTED

    def test_naka_note_explains_the_ambiguity(self):
        history = make_bars([11.0, 9.0, 7.0, 5.0, 4.85])
        status, note = reconcile.assess_cost_basis(
            history, self.NAKA_AVG_COST, self.NAKA_LAST
        )
        assert status is CostBasisStatus.CORPORATE_ACTION_SUSPECTED
        assert "169.65" in note and "4.85" in note
        assert "unverified" in note.lower()

    def test_does_not_fire_on_a_genuine_50pct_drawdown(self):
        """avg 100 → last 50 is ratio 2.0. An ordinary bad trade, not a split."""
        history = make_bars([105.0, 98.0, 90.0, 80.0, 70.0, 62.0, 55.0, 50.0])
        status = reconcile.detect_corporate_action(history, 100.0, 50.0)
        assert status is CostBasisStatus.OK

    def test_does_not_fire_when_history_corroborates_a_deep_loss(self):
        """
        The other half of the NAKA ambiguity: same ratio, but the stock really
        did trade at 169. That is a genuine −97%, and we must not cry split.
        """
        history = make_bars([175.0, 140.0, 90.0, 40.0, 15.0, 8.0, 4.85])
        status = reconcile.detect_corporate_action(history, 169.65, 4.85)
        assert status is CostBasisStatus.OK

    def test_no_history_is_unverified_not_suspected(self):
        status = reconcile.detect_corporate_action(base.empty_bars(), 169.65, 4.85)
        assert status is CostBasisStatus.UNVERIFIED

    def test_missing_inputs_are_unverified(self):
        assert reconcile.detect_corporate_action(make_bars([1.0]), None, 4.85) is (
            CostBasisStatus.UNVERIFIED
        )
        assert reconcile.detect_corporate_action(make_bars([1.0]), 169.65, 0.0) is (
            CostBasisStatus.UNVERIFIED
        )

    def test_boundary_at_ten_times(self):
        history = make_bars([12.0] * 5)
        assert reconcile.detect_corporate_action(history, 100.0, 10.0) is CostBasisStatus.OK
        assert (
            reconcile.detect_corporate_action(history, 110.0, 10.0)
            is CostBasisStatus.CORPORATE_ACTION_SUSPECTED
        )

    def test_reconciliation_is_attached_for_the_ui(self):
        history = make_bars([11.0, 8.0, 4.85])
        status, note = reconcile.assess_cost_basis(history, 169.65, 4.85)
        rec = reconcile.corporate_action_reconciliation(status, note, 169.65, 4.85)
        assert rec is not None and rec.breached is True and rec.field == "cost_basis"

    def test_ok_status_produces_no_reconciliation(self):
        assert reconcile.corporate_action_reconciliation(
            CostBasisStatus.OK, "fine", 100.0, 50.0
        ) is None


# ═══════════════════════════ 3. Yahoo symbol mapping ═══════════════════════════

class TestYahooSuffixMapping:
    @pytest.mark.parametrize(
        "symbol,exchange,expected",
        [
            ("SOXL", "LSEETF", "SOXL.L"),      # the 4x LSE ETP — required by the spec
            ("MAG7", "LSEETF", "MAG7.L"),
            ("EZJ", "LSE", "EZJ.L"),
            ("RHM", "FWB", "RHM.DE"),          # Frankfurt — required by the spec
            ("HY9H", "FWB", "HY9H.DE"),
            ("SIE", "IBIS", "SIE.DE"),         # Xetra also maps to .DE
            ("000660", "KSE", "000660.KS"),    # Seoul
            ("9513", "TSEJ", "9513.T"),        # Tokyo
            ("NVDA", "NASDAQ", "NVDA"),        # US takes no suffix
            ("VOO", "ARCA", "VOO"),
            ("SOXL", "ARCA", "SOXL"),          # the 3x US ETF, same ticker
        ],
    )
    def test_mapping(self, symbol, exchange, expected):
        assert yahoo.yahoo_ticker(symbol, exchange) == expected

    def test_lseetf_and_arca_soxl_map_to_different_yahoo_tickers(self):
        """The whole point of keying on (conid, exchange)."""
        a = yahoo.yahoo_ticker_for(SOXL_LSE)
        b = yahoo.yahoo_ticker_for(SOXL_US)
        assert a == "SOXL.L" and b == "SOXL"
        assert a != b

    def test_case_and_whitespace_are_tolerated(self):
        assert yahoo.yahoo_ticker("soxl", "lseetf") == "SOXL.L"
        assert yahoo.yahoo_ticker(" RHM ", " fwb ") == "RHM.DE"

    def test_ibkr_local_symbol_quirks(self):
        assert yahoo.yahoo_ticker("RR.", "LSE") == "RR.L"       # trailing dot
        assert yahoo.yahoo_ticker("BRK B", "NYSE") == "BRK-B"   # space → hyphen

    def test_unknown_exchange_returns_none_rather_than_guessing(self):
        assert yahoo.yahoo_ticker("XYZ", "SOMEVENUE") is None
        assert yahoo.yahoo_ticker("", "LSEETF") is None

    def test_tokyo_and_toronto_are_not_confused(self):
        """IBKR TSE is Toronto; Tokyo is TSEJ."""
        assert yahoo.yahoo_ticker("9513", "TSEJ") == "9513.T"
        assert yahoo.yahoo_ticker("SHOP", "TSE") == "SHOP.TO"


class _FakeYFTicker:
    def __init__(self, *, info=None, history=None, dividends=None):
        self._info = info or {}
        self._history = history
        self._dividends = dividends

    @property
    def info(self):
        return self._info

    def history(self, **kwargs):
        if self._history is None:
            raise RuntimeError("Yahoo says no")
        return self._history

    @property
    def dividends(self):
        if self._dividends is None:
            return pd.Series(dtype="float64")
        return self._dividends


class TestYahooSourceDegradation:
    def test_uncovered_listing_returns_empty_frame_not_an_exception(self):
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker())
        df = src.get_bars(999, "SOMEVENUE", symbol="XYZ")
        assert df.empty and list(df.columns) == list(base.BAR_COLUMNS)

    def test_history_error_degrades_to_empty(self):
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(history=None))
        assert src.get_bars(693388387, "LSEETF", symbol="SOXL").empty

    def test_fundamentals_return_none_when_yahoo_is_blank(self):
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(info={}))
        assert src.fundamentals(SOXL_LSE) is None
        assert src.analyst_targets(SOXL_LSE) is None
        assert src.short_interest(SOXL_LSE) is None
        assert src.dividends(SOXL_LSE) == []
        assert src.earnings_history(SOXL_LSE) == []

    def test_fundamentals_are_parsed_when_present(self):
        info = {
            "longName": "NVIDIA Corporation", "sector": "Technology",
            "industry": "Semiconductors", "currency": "USD",
            "marketCap": 3.4e12, "forwardPE": 31.2, "trailingPE": 48.9,
            "trailingEps": 3.1, "forwardEps": 5.4, "earningsGrowth": 0.62,
            "revenueGrowth": 0.55, "beta": 1.7, "sharesShort": 2.4e8,
            "shortRatio": 1.2, "shortPercentOfFloat": 0.011,
            "targetMeanPrice": 210.0, "currentPrice": 180.0,
            "numberOfAnalystOpinions": 58, "recommendationKey": "buy",
        }
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(info=info))
        nvda = Instrument(conid=4815747, symbol="NVDA", exchange="NASDAQ")

        f = src.fundamentals(nvda)
        assert f is not None
        assert f.ticker == "NVDA"
        assert f.forward_pe == pytest.approx(31.2)
        assert f.eps_growth_yoy == pytest.approx(0.62)
        assert f.revenue_growth_yoy == pytest.approx(0.55)

        t = src.analyst_targets(nvda)
        assert t is not None and t.upside_pct == pytest.approx(16.667, abs=1e-2)

        si = src.short_interest(nvda)
        assert si is not None and si.short_ratio == pytest.approx(1.2)

    def test_resolve_refuses_to_mint_an_identity(self):
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(info={"longName": "x"}))
        assert src.resolve("SOXL", "LSEETF") is None

    def test_enrich_fills_metadata_onto_an_ibkr_identity(self):
        info = {"longName": "Leverage Shares 4x Semis", "sector": "Technology",
                "industry": "Semiconductors"}
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(info=info))
        out = src.enrich(SOXL_LSE)
        assert out.conid == SOXL_LSE.conid and out.exchange == "LSEETF"
        assert out.sector == "Technology"

    def test_cross_check_series_is_unadjusted_and_normalized(self):
        idx = _sessions(10)
        raw = pd.DataFrame(
            {"Open": [1.0] * 10, "High": [1.1] * 10, "Low": [0.9] * 10,
             "Close": [1.05] * 10, "Volume": [10_000] * 10, "Adj Close": [1.0] * 10},
            index=idx,
        )
        src = yahoo.YahooSource(ticker_factory=lambda t: _FakeYFTicker(history=raw))
        df = src.get_bars(693388387, "LSEETF", symbol="SOXL")
        assert list(df.columns) == list(base.BAR_COLUMNS)
        assert df.attrs["source"] == "yahoo"
        assert df.attrs["yahoo_ticker"] == "SOXL.L"
        assert df["close"].iloc[0] == pytest.approx(1.05)


# ═══════════════════════════ 4. cache ═══════════════════════════

class TestCacheUpsert:
    def test_bar_upsert_is_idempotent(self):
        """Re-running the nightly job must not duplicate or mutate rows."""
        with Cache(":memory:") as c:
            df = make_bars([10.0, 11.0, 12.0])
            first = c.upsert_bars(693388387, "LSEETF", df, source="ibkr")
            assert first == 3
            assert c.stats()["bars"] == 3

            for _ in range(4):
                c.upsert_bars(693388387, "LSEETF", df, source="ibkr")
            assert c.stats()["bars"] == 3

            back = c.get_bars(693388387, "LSEETF", source="ibkr")
            assert len(back) == 3
            assert back["close"].tolist() == [10.0, 11.0, 12.0]

    def test_upsert_overwrites_a_revised_bar_in_place(self):
        with Cache(":memory:") as c:
            idx = _sessions(3)
            c.upsert_bars(1, "ARCA", make_bars([10.0, 11.0, 12.0], idx), source="ibkr")
            c.upsert_bars(1, "ARCA", make_bars([10.0, 11.0, 99.0], idx), source="ibkr")
            back = c.get_bars(1, "ARCA", source="ibkr")
            assert len(back) == 3
            assert back["close"].iloc[-1] == 99.0

    def test_the_two_soxls_never_collide(self):
        """Same symbol, same dates, different (conid, exchange) → separate rows."""
        with Cache(":memory:") as c:
            idx = _sessions(5)
            c.upsert_bars(693388387, "LSEETF", make_bars([4.0] * 5, idx), source="ibkr")
            c.upsert_bars(73340487, "ARCA", make_bars([25.0] * 5, idx), source="ibkr")
            assert c.stats()["bars"] == 10
            assert c.get_bars(693388387, "LSEETF")["close"].iloc[0] == 4.0
            assert c.get_bars(73340487, "ARCA")["close"].iloc[0] == 25.0

    def test_two_sources_coexist_for_the_same_bar(self):
        """Required by reconcile: IBKR and Yahoo closes are separate rows."""
        with Cache(":memory:") as c:
            idx = _sessions(5)
            c.upsert_bars(1, "ARCA", make_bars([10.0] * 5, idx), source="ibkr")
            c.upsert_bars(1, "ARCA", make_bars([10.04] * 5, idx, source="yahoo"), source="yahoo")
            assert c.stats()["bars"] == 10
            assert sorted(c.bar_sources(1, "ARCA")) == ["ibkr", "yahoo"]
            recs = reconcile.reconcile_series(
                c.get_bars(1, "ARCA", source="ibkr"), c.get_bars(1, "ARCA", source="yahoo")
            )
            assert next(r for r in recs if r.field == "close").breached is True

    def test_instrument_upsert_is_idempotent(self, cache):
        for _ in range(3):
            cache.upsert_instruments([SOXL_LSE, SOXL_US])
        assert cache.stats()["instruments"] == 2
        got = cache.get_instrument(693388387, "LSEETF")
        assert got is not None and got.leverage == 4.0 and got.exchange == "LSEETF"
        assert cache.get_instrument(693388387, "ARCA") is None   # exchange is part of the key

    def test_quote_upsert_is_idempotent_and_keeps_delayed_seconds(self, cache):
        q = Quote(conid=693388387, last=4.21, bid=4.20, ask=4.22, delayed_seconds=900,
                  ts=datetime(2026, 8, 7, 15, 30, tzinfo=timezone.utc))
        for _ in range(3):
            cache.upsert_quote(q, "LSEETF", source="ibkr")
        assert cache.stats()["quotes"] == 1
        back = cache.get_quote(693388387, "LSEETF")
        assert back is not None and back.delayed_seconds == 900 and back.last == 4.21

    def test_fundamentals_upsert_is_idempotent(self, cache):
        payload = yahoo.Fundamentals(conid=4815747, symbol="NVDA", ticker="NVDA", forward_pe=31.2)
        for _ in range(3):
            cache.upsert_fundamentals(4815747, "NASDAQ", payload, source="yahoo")
        assert cache.stats()["fundamentals"] == 1
        assert cache.get_fundamentals(4815747, "NASDAQ")["forward_pe"] == pytest.approx(31.2)

    def test_event_upsert_dedupes_on_content(self, cache):
        ev = MarketEvent(
            ts=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc), conid=4815747, symbol="NVDA",
            event_class=EventClass.HEADLINE, title="NVDA beats", detail="…",
            severity=Severity.GOOD,
        )
        for _ in range(3):
            cache.upsert_events([ev], source="finnhub")
        assert cache.stats()["events"] == 1
        assert event_id(ev) == event_id(ev.model_copy())
        assert len(cache.get_events(conid=4815747)) == 1

    def test_exchange_is_normalized_but_never_substituted(self, cache):
        cache.upsert_bars(693388387, "lseetf", make_bars([4.0] * 3), source="ibkr")
        assert len(cache.get_bars(693388387, "LSEETF")) == 3
        assert len(cache.get_bars(693388387, "SMART")) == 0


class TestCacheStaleness:
    def test_missing_key_is_stale(self, cache):
        assert cache.is_stale("bars", timedelta(hours=24)) is True
        assert cache.age("bars") is None

    def test_fresh_key_is_not_stale(self, cache):
        cache.set_last_refresh("bars", note="nightly", rows=1234)
        assert cache.is_stale("bars", timedelta(hours=24)) is False
        assert cache.is_stale("bars", 0.0) is True

    def test_old_key_is_stale(self, cache):
        cache.set_last_refresh(
            "bars", when=datetime.now(timezone.utc) - timedelta(days=3)
        )
        assert cache.is_stale("bars", timedelta(hours=24)) is True
        assert cache.age("bars") > timedelta(days=2)

    def test_seconds_accepted_as_well_as_timedelta(self, cache):
        cache.set_last_refresh("quotes")
        assert cache.is_stale("quotes", 60) is False


class TestCacheReadPaths:
    def test_cold_read_returns_empty_frame_and_never_blocks(self, cache):
        df = cache.get_bars(999999, "ARCA")
        assert df.empty
        assert list(df.columns) == list(base.BAR_COLUMNS)
        assert cache.get_quote(999999, "ARCA") is None
        assert cache.get_instrument(999999, "ARCA") is None
        assert cache.get_events(conid=999999) == []

    def test_read_only_cache_refuses_writes(self, tmp_path):
        path = tmp_path / "ro.duckdb"
        with Cache(path) as w:
            w.upsert_instruments([SOXL_LSE])
        from app.cache import open_read_only

        ro = open_read_only(path)
        try:
            assert ro.get_instrument(693388387, "LSEETF") is not None
            with pytest.raises(RuntimeError, match="read-only"):
                ro.upsert_instruments([SOXL_US])
        finally:
            ro.close()

    def test_date_window_and_limit(self, cache):
        idx = _sessions(30)
        cache.upsert_bars(1, "ARCA", make_bars([float(i) for i in range(30)], idx), source="ibkr")
        window = cache.get_bars(1, "ARCA", start=idx[10].date(), end=idx[19].date())
        assert len(window) == 10
        assert cache.latest_bar_date(1, "ARCA") == idx[29].date()
        assert len(cache.get_bars(1, "ARCA", limit=5)) == 5


# ═══════════════════════════ 5. finnhub ═══════════════════════════

class TestFinnhubDegradation:
    def test_blank_key_returns_empty_lists_and_makes_no_calls(self):
        calls: list[tuple] = []

        def http_get(url, params):
            calls.append((url, params))
            raise AssertionError("must not call Finnhub without a key")

        src = finnhub.FinnhubSource(api_key="", http_get=http_get)
        assert src.enabled is False
        assert src.headlines("NVDA") == []
        assert src.analyst_actions("NVDA") == []
        assert src.earnings_surprises("NVDA") == []
        assert src.earnings_calendar(["NVDA"]) == []
        assert src.tape(["NVDA", "AVGO"]) == []
        assert calls == []

    def test_whitespace_only_key_counts_as_blank(self):
        src = finnhub.FinnhubSource(api_key="   ")
        assert src.enabled is False
        assert src.headlines("NVDA") == []

    def test_outage_degrades_to_empty_rather_than_raising(self):
        def boom(url, params):
            raise ConnectionError("finnhub is down")

        src = finnhub.FinnhubSource(
            api_key="k", http_get=boom,
            bucket=base.per_minute(60, clock=_fast_clock(), sleep=lambda s: None),
        )
        assert src.headlines("NVDA") == []
        assert src.analyst_actions("NVDA") == []
        assert src.earnings_surprises("NVDA") == []

    def test_http_500_degrades_to_empty(self):
        src = finnhub.FinnhubSource(
            api_key="k", http_get=lambda u, p: (500, None),
            bucket=base.per_minute(60, clock=_fast_clock(), sleep=lambda s: None),
        )
        assert src.headlines("NVDA") == []

    def test_bad_key_is_not_fatal(self):
        src = finnhub.FinnhubSource(api_key="wrong", http_get=lambda u, p: (401, None))
        assert src.headlines("NVDA") == []

    def test_malformed_payload_degrades(self):
        src = finnhub.FinnhubSource(api_key="k", http_get=lambda u, p: (200, {"unexpected": 1}))
        assert src.headlines("NVDA") == []

    def test_headlines_are_parsed_into_market_events(self):
        payload = [
            {"datetime": 1_785_000_000, "headline": "NVDA tops estimates",
             "summary": "Beat on data centre", "url": "https://x/1", "source": "Reuters"},
            {"datetime": 1_784_900_000, "headline": "", "summary": "dropped: no headline"},
        ]
        src = finnhub.FinnhubSource(api_key="k", http_get=lambda u, p: (200, payload))
        events = src.headlines("NVDA", conid=4815747)
        assert len(events) == 1
        e = events[0]
        assert e.event_class is EventClass.HEADLINE
        assert e.conid == 4815747 and e.symbol == "NVDA"
        assert e.moved_price is False        # events.py pairs it with the reaction

    def test_analyst_actions_map_direction_to_severity(self):
        def http_get(url, params):
            if "upgrade-downgrade" in url:
                return 200, [
                    {"gradeTime": 1_785_000_000, "company": "Morgan Stanley",
                     "fromGrade": "Equal-Weight", "toGrade": "Overweight", "action": "up"},
                    {"gradeTime": 1_784_000_000, "company": "HSBC",
                     "fromGrade": "Buy", "toGrade": "Hold", "action": "down"},
                ]
            return 200, {"targetMean": 210.0, "targetHigh": 260.0, "targetLow": 150.0,
                         "numberOfAnalysts": 58, "lastUpdated": "2026-08-01T00:00:00Z"}

        src = finnhub.FinnhubSource(api_key="k", http_get=http_get)
        events = src.analyst_actions("NVDA", conid=4815747)
        assert len(events) == 3
        sev = {e.title: e.severity for e in events}
        assert any(v is Severity.GOOD for v in sev.values())
        assert any(v is Severity.WARNING for v in sev.values())
        assert all(e.event_class is EventClass.ANALYST for e in events)

    def test_price_target_failure_does_not_lose_the_upgrades(self):
        def http_get(url, params):
            if "upgrade-downgrade" in url:
                return 200, [{"gradeTime": 1_785_000_000, "company": "UBS",
                              "fromGrade": "Hold", "toGrade": "Buy", "action": "up"}]
            return 404, None

        src = finnhub.FinnhubSource(
            api_key="k", http_get=http_get,
            bucket=base.per_minute(60, clock=_fast_clock(), sleep=lambda s: None),
        )
        assert len(src.analyst_actions("NVDA")) == 1

    def test_earnings_surprises_computed_when_absent(self):
        payload = [
            {"period": "2026-06-30", "actual": 1.10, "estimate": 1.00, "quarter": 2, "year": 2026},
            {"period": "2026-03-31", "actual": 0.90, "estimate": 1.00,
             "surprisePercent": -10.0, "quarter": 1, "year": 2026},
        ]
        src = finnhub.FinnhubSource(api_key="k", http_get=lambda u, p: (200, payload))
        rows = src.earnings_surprises("NVDA", conid=4815747)
        assert rows[0]["eps_surprise_pct"] == pytest.approx(10.0)
        assert rows[1]["eps_surprise_pct"] == pytest.approx(-10.0)

    def test_rate_limiter_is_wired_to_the_free_tier(self):
        src = finnhub.FinnhubSource(api_key="k", http_get=lambda u, p: (200, []))
        assert src.bucket.capacity == pytest.approx(60.0)
        assert src.bucket.rate == pytest.approx(1.0)     # 60 per 60s

    def test_retry_is_shallow_so_an_outage_cannot_stall_a_render(self):
        calls = {"n": 0}

        def boom(url, params):
            calls["n"] += 1
            raise ConnectionError("down")

        src = finnhub.FinnhubSource(
            api_key="k", http_get=boom,
            retry=base.RetryPolicy(attempts=2, base_delay=0.0, jitter=0.0),
            bucket=base.per_minute(60, clock=_fast_clock(), sleep=lambda s: None),
        )
        assert src.headlines("NVDA") == []
        assert calls["n"] == 2                # attempts, not an unbounded loop
        assert finnhub.FAST_FAIL_RETRY.attempts == 2


# ═══════════════════════════ base: retry + token bucket ═══════════════════════════

def _fast_clock():
    """A monotonic clock that leaps a minute per call — makes bucket waits free."""
    state = {"t": 0.0}

    def clock():
        state["t"] += 60.0
        return state["t"]

    return clock


class TestRetry:
    def test_retries_then_succeeds(self):
        calls = {"n": 0}
        slept: list[float] = []

        @base.with_retry(base.RetryPolicy(attempts=4, base_delay=0.01, jitter=0.0),
                         sleep=slept.append)
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("nope")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 3
        assert len(slept) == 2
        assert slept[1] > slept[0]           # exponential

    def test_gives_up_and_reraises(self):
        @base.with_retry(base.RetryPolicy(attempts=2, base_delay=0.0, jitter=0.0),
                         sleep=lambda s: None)
        def always():
            raise ConnectionError("still nope")

        with pytest.raises(ConnectionError):
            always()

    def test_no_coverage_is_not_retried(self):
        calls = {"n": 0}

        @base.with_retry(base.RetryPolicy(attempts=5, base_delay=0.0, jitter=0.0),
                         sleep=lambda s: None)
        def uncovered():
            calls["n"] += 1
            raise base.NoCoverage("yahoo has never heard of this")

        with pytest.raises(base.NoCoverage):
            uncovered()
        assert calls["n"] == 1

    def test_async_callables_are_supported(self):
        calls = {"n": 0}

        @base.with_retry(base.RetryPolicy(attempts=3, base_delay=0.0, jitter=0.0))
        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return 42

        assert asyncio.run(flaky()) == 42

    def test_backoff_is_capped(self):
        pol = base.RetryPolicy(base_delay=1.0, multiplier=10.0, max_delay=5.0, jitter=0.0)
        assert pol.delay_for(1) == 1.0
        assert pol.delay_for(2) == 5.0
        assert pol.delay_for(9) == 5.0


class TestTokenBucket:
    def test_burst_then_throttle(self):
        now = {"t": 0.0}
        slept: list[float] = []
        b = base.TokenBucket(
            rate=1.0, capacity=3.0, clock=lambda: now["t"],
            sleep=lambda s: (slept.append(s), now.__setitem__("t", now["t"] + s)),
        )
        assert all(b.try_acquire() for _ in range(3))
        assert b.try_acquire() is False          # bucket empty
        b.acquire()                              # blocks one second
        assert slept and slept[0] == pytest.approx(1.0)

    def test_refills_over_time(self):
        now = {"t": 0.0}
        b = base.TokenBucket(rate=2.0, capacity=2.0, clock=lambda: now["t"],
                             sleep=lambda s: None)
        assert b.try_acquire(2.0)
        assert b.try_acquire() is False
        now["t"] = 1.0
        assert b.try_acquire(2.0)

    def test_per_minute_helper(self):
        b = base.per_minute(60)
        assert b.rate == pytest.approx(1.0) and b.capacity == pytest.approx(60.0)

    def test_decorator_form(self):
        b = base.TokenBucket(rate=1000.0, capacity=5.0, sleep=lambda s: None)
        seen = []

        @b.rate_limited()
        def work(x):
            seen.append(x)
            return x * 2

        assert [work(i) for i in range(3)] == [0, 2, 4]
        assert seen == [0, 1, 2]


class TestNormalizeBars:
    def test_accepts_a_date_column_or_an_index(self):
        idx = _sessions(3)
        a = base.normalize_bars(
            pd.DataFrame({"date": idx, "Open": [1, 2, 3], "High": [1, 2, 3],
                          "Low": [1, 2, 3], "Close": [1, 2, 3], "Volume": [1, 2, 3]})
        )
        b = base.normalize_bars(
            pd.DataFrame({"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
                          "close": [1, 2, 3], "volume": [1, 2, 3]}, index=idx)
        )
        assert a.index.equals(b.index)
        assert list(a.columns) == list(base.BAR_COLUMNS)

    def test_tz_aware_index_is_flattened_to_dates(self):
        idx = pd.date_range("2026-08-03", periods=3, freq="D", tz="Europe/London")
        df = base.normalize_bars(pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx))
        assert df.index.tz is None
        assert df.index[0] == pd.Timestamp("2026-08-03")

    def test_duplicates_keep_the_last_and_sort(self):
        idx = pd.DatetimeIndex(["2026-08-05", "2026-08-03", "2026-08-05"])
        df = base.normalize_bars(pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx))
        assert len(df) == 2
        assert df["close"].tolist() == [2.0, 3.0]

    def test_period_and_step_vocabulary(self):
        assert base.canon_period("6m") == "6mo"
        assert base.canon_step("daily") == "1d"
        with pytest.raises(ValueError):
            base.canon_period("17 fortnights")


# ═══════════════════════════ IBKR (fakes only — no network) ═══════════════════════════

class _FakeContract:
    def __init__(self, conId=0, symbol="", exchange="", secType="STK",
                 currency="USD", primaryExchange=""):
        self.conId = conId
        self.symbol = symbol
        self.exchange = exchange
        self.secType = secType
        self.currency = currency
        self.primaryExchange = primaryExchange


class _FakeBar:
    def __init__(self, d, c):
        self.date = d
        self.open = c * 0.99
        self.high = c * 1.01
        self.low = c * 0.98
        self.close = c
        self.volume = 1_000.0


class _FakeTicker:
    def __init__(self, **kw):
        for k in ("last", "close", "bid", "ask", "volume", "markPrice"):
            setattr(self, k, kw.get(k))
        self.marketDataType = kw.get("marketDataType", 1)
        self.time = kw.get("time", datetime(2026, 8, 7, 15, 30, tzinfo=timezone.utc))


class _FakePosition:
    def __init__(self, contract, position, avgCost, account="U123"):
        self.contract = contract
        self.position = position
        self.avgCost = avgCost
        self.account = account


class _FakeAccountValue:
    def __init__(self, tag, value, currency="USD", account="U123"):
        self.tag = tag
        self.value = value
        self.currency = currency
        self.account = account


class _FakeIB:
    """Records what the source asked for — that is what we assert on."""

    def __init__(self, *, bars=None, ticker=None, positions=None, summary=None,
                 delayed_only=False):
        self._connected = False
        self.connect_kwargs: dict = {}
        self.market_data_types: list[int] = []
        self.qualified: list = []
        self.hist_calls: list[dict] = []
        self._bars = bars if bars is not None else []
        self._ticker = ticker
        self._positions = positions or []
        self._summary = summary or []
        self._delayed_only = delayed_only

    async def connectAsync(self, host, port, clientId, readonly, timeout=10.0):
        self.connect_kwargs = dict(host=host, port=port, clientId=clientId,
                                   readonly=readonly, timeout=timeout)
        self._connected = True

    def isConnected(self):
        return self._connected

    def disconnect(self):
        self._connected = False

    def reqMarketDataType(self, mdt):
        self.market_data_types.append(mdt)

    async def qualifyContractsAsync(self, *contracts):
        self.qualified.extend(contracts)
        out = []
        for c in contracts:
            out.append(_FakeContract(conId=c.conId, exchange=c.exchange, symbol="SOXL"))
        return out

    async def reqHistoricalDataAsync(self, contract, **kw):
        self.hist_calls.append({"contract": contract, **kw})
        return self._bars

    async def reqTickersAsync(self, *contracts):
        current = self.market_data_types[-1] if self.market_data_types else 1
        if self._delayed_only and current not in (3, 4):
            return [_FakeTicker(marketDataType=current)]     # empty on live
        t = self._ticker or _FakeTicker(last=4.21, close=4.10, marketDataType=current)
        t.marketDataType = current
        return [t]

    async def reqPositionsAsync(self):
        return self._positions

    async def accountSummaryAsync(self, account=""):
        return self._summary


def _run(coro):
    return asyncio.run(coro)


def _strip_comments_and_strings(source: str) -> str:
    """Executable tokens only — used by the no-order-placement guard below."""
    import io
    import tokenize

    kept: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(tok.string)
    except tokenize.TokenError:  # pragma: no cover - malformed file
        return source
    return "\n".join(kept)


class TestIBKRExchangeHandling:
    @pytest.mark.parametrize("exchange", ["LSEETF", "FWB", "KSE", "TSEJ", "IBIS", "SEHK"])
    def test_non_us_exchange_is_never_defaulted_to_smart(self, exchange):
        assert ibkr.routing_exchange(exchange) == exchange
        assert ibkr.is_non_smart(exchange) is True

    def test_only_a_blank_exchange_falls_back_to_smart(self):
        assert ibkr.routing_exchange("") == "SMART"
        assert ibkr.routing_exchange(None) == "SMART"
        assert ibkr.routing_exchange("ARCA") == "ARCA"

    def test_contract_is_built_from_conid_and_exchange_only(self):
        ib = _FakeIB()
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            await src.connect()
            return await src.contract_for(693388387, "LSEETF")

        contract = _run(go())
        assert contract.conId == 693388387
        assert contract.exchange == "LSEETF"          # NOT SMART
        sent = ib.qualified[0]
        assert sent.conId == 693388387
        assert sent.exchange == "LSEETF"
        assert not getattr(sent, "symbol", "")        # no symbol was sent

    def test_mismatched_conid_from_ibkr_is_rejected(self):
        class Sneaky(_FakeIB):
            async def qualifyContractsAsync(self, *contracts):
                return [_FakeContract(conId=73340487, exchange="ARCA", symbol="SOXL")]

        ib = Sneaky()
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            await src.connect()
            return await src.contract_for(693388387, "LSEETF")

        with pytest.raises(base.SourceError, match="refusing an ambiguous contract"):
            _run(go())

    def test_resolve_requires_an_exchange(self):
        src = ibkr.IBKRSource(ib_factory=_FakeIB)
        with pytest.raises(ValueError, match="needs an exchange"):
            _run(src.resolve("SOXL", ""))


class TestIBKRReadOnly:
    def test_connect_passes_readonly_true(self):
        ib = _FakeIB()
        src = ibkr.IBKRSource(ib_factory=lambda: ib)
        _run(src.connect())
        assert ib.connect_kwargs["readonly"] is True

    def test_refuses_to_connect_when_readonly_is_disabled(self):
        src = ibkr.IBKRSource(ib_factory=_FakeIB, readonly=False)
        with pytest.raises(base.SourceError, match="readonly"):
            _run(src.connect())

    def test_settings_default_is_readonly(self):
        from app.config import settings

        assert settings.ibkr_readonly is True

    def test_session_context_manager_disconnects(self):
        ib = _FakeIB()
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            async with src.session():
                assert ib.isConnected()
            return ib.isConnected()

        assert _run(go()) is False

    def test_session_disconnects_even_on_error(self):
        ib = _FakeIB()
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            async with src.session():
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            _run(go())
        assert ib.isConnected() is False

    def test_no_order_placement_code_in_the_repo(self):
        """
        The spec's hard constraint. Scans the whole backend for the ib_async
        order surface — a future edit that adds one fails here.

        Comments and docstrings are stripped first, so prose *about* the ban
        (this file, and ibkr.py's module docstring) does not trip it while real
        code does.
        """
        banned = ("placeOrder", "MarketOrder", "LimitOrder", "StopOrder",
                  "BracketOrder", "whatIfOrder", "reqIds")
        offenders = []
        for path in (BACKEND / "app").rglob("*.py"):
            code = _strip_comments_and_strings(path.read_text(encoding="utf-8"))
            for token in banned:
                if token in code:
                    offenders.append(f"{path.name}:{token}")
        assert offenders == [], f"order-placement surface found: {offenders}"

    def test_no_ib_insync_import(self):
        """ib_async is the maintained fork; ib_insync must not appear."""
        for path in (BACKEND / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "import ib_insync" not in text
            assert "from ib_insync" not in text


class TestIBKRBarsAndQuotes:
    def test_bars_are_normalized(self):
        bars = [_FakeBar(date(2026, 8, 3), 4.0), _FakeBar(date(2026, 8, 4), 4.1),
                _FakeBar(date(2026, 8, 5), 4.2)]
        ib = _FakeIB(bars=bars)
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            await src.connect()
            return await src.get_bars(693388387, "LSEETF", period="6m", step="1d")

        df = _run(go())
        assert list(df.columns) == list(base.BAR_COLUMNS)
        assert df.attrs["source"] == "ibkr"
        assert df["close"].tolist() == [4.0, 4.1, 4.2]
        call = ib.hist_calls[0]
        assert call["durationStr"] == "6 M"
        assert call["barSizeSetting"] == "1 day"
        assert call["whatToShow"] == "TRADES"
        assert call["contract"].exchange == "LSEETF"

    def test_empty_history_returns_the_canonical_empty_frame(self):
        src = ibkr.IBKRSource(ib_factory=lambda: _FakeIB(bars=[]))

        async def go():
            await src.connect()
            return await src.get_bars(1, "ARCA")

        df = _run(go())
        assert df.empty and list(df.columns) == list(base.BAR_COLUMNS)

    def test_live_quote_has_zero_delayed_seconds(self):
        ib = _FakeIB(ticker=_FakeTicker(last=25.10, close=24.80, bid=25.09, ask=25.11,
                                        volume=1e6, marketDataType=1))
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            await src.connect()
            return await src.get_quote(73340487, "ARCA")

        q = _run(go())
        assert q.delayed_seconds == 0
        assert q.last == pytest.approx(25.10)
        assert q.change_pct == pytest.approx((25.10 / 24.80 - 1) * 100, abs=1e-6)

    def test_falls_back_to_delayed_and_records_900_seconds(self):
        """
        LSEETF without a London market-data subscription: the live request comes
        back blank, we retry at reqMarketDataType(3), and the Quote says so.
        """
        ib = _FakeIB(ticker=_FakeTicker(last=4.21, close=4.10), delayed_only=True)
        src = ibkr.IBKRSource(ib_factory=lambda: ib)

        async def go():
            await src.connect()
            return await src.get_quote(693388387, "LSEETF")

        q = _run(go())
        assert ibkr.MDT_DELAYED in ib.market_data_types
        assert q.delayed_seconds == ibkr.DELAYED_SECONDS == 900
        assert q.last == pytest.approx(4.21)

    def test_explicit_delayed_mode_is_honoured(self):
        ib = _FakeIB(ticker=_FakeTicker(last=4.21, close=4.10))
        src = ibkr.IBKRSource(ib_factory=lambda: ib, market_data_type=ibkr.MDT_DELAYED)

        async def go():
            await src.connect()
            return await src.get_quote(693388387, "LSEETF")

        assert _run(go()).delayed_seconds == 900


class TestIBKRAccount:
    def test_positions_pass_raw_avg_cost_through(self):
        """
        NAKA's basis must reach reconcile untouched — no clever re-basing here.
        """
        positions = [
            _FakePosition(_FakeContract(conId=777, symbol="NAKA", exchange="NASDAQ"),
                          34, 169.65),
            _FakePosition(_FakeContract(conId=136155102, symbol="VOO", exchange="ARCA"),
                          10, 480.20),
        ]
        src = ibkr.IBKRSource(ib_factory=lambda: _FakeIB(positions=positions))

        async def go():
            await src.connect()
            return await src.positions()

        got = _run(go())
        naka = next(p for p in got if p.symbol == "NAKA")
        assert naka.quantity == 34
        assert naka.avg_cost == pytest.approx(169.65)
        assert naka.conid == 777

    def test_naka_position_end_to_end_flags_the_corporate_action(self):
        """The full path the spec cares about: IBKR position → reconcile verdict."""
        positions = [
            _FakePosition(_FakeContract(conId=777, symbol="NAKA", exchange="NASDAQ"),
                          34, 169.65)
        ]
        src = ibkr.IBKRSource(ib_factory=lambda: _FakeIB(positions=positions))

        async def go():
            await src.connect()
            return await src.positions()

        p = _run(go())[0]
        history = make_bars([11.5, 9.8, 8.0, 6.4, 5.2, 4.85])
        status, note = reconcile.assess_cost_basis(history, p.avg_cost, 4.85)
        assert status is CostBasisStatus.CORPORATE_ACTION_SUSPECTED
        rec = reconcile.corporate_action_reconciliation(status, note, p.avg_cost, 4.85)
        assert rec.breached is True

    def test_account_summary_parses_numeric_tags(self):
        summary = [
            _FakeAccountValue("NetLiquidation", "191421.00"),
            _FakeAccountValue("TotalCashValue", "185196.00"),
            _FakeAccountValue("GrossPositionValue", "6205.00"),
            _FakeAccountValue("AccountType", "INDIVIDUAL"),   # non-numeric, skipped
        ]
        src = ibkr.IBKRSource(ib_factory=lambda: _FakeIB(summary=summary))

        async def go():
            await src.connect()
            return await src.account_summary()

        s = _run(go())
        assert s.net_liquidation == pytest.approx(191_421.0)
        assert s.cash == pytest.approx(185_196.0)
        assert "AccountType" not in s.values


class TestIBKRWatchlists:
    PAYLOADS = {
        "/iserver/watchlists": {
            "data": {"user_lists": [{"id": "10", "name": "Favorites"},
                                    {"id": "104", "name": "space tech"}]}
        },
        "/iserver/watchlist": {
            "10": {"name": "Favorites", "instruments": [
                {"C": "693388387", "ticker": "SOXL", "listingExchange": "LSEETF"},
                {"C": "73340487", "ticker": "SOXL", "listingExchange": "ARCA"},
            ]},
            "104": {"name": "space tech", "instruments": [
                {"C": "1001", "ticker": "RKLB", "listingExchange": "NASDAQ"},
            ]},
        },
    }

    def _client(self):
        def http_get(path, params):
            if path == "/iserver/watchlists":
                return self.PAYLOADS[path]
            return self.PAYLOADS["/iserver/watchlist"][params["id"]]

        return ibkr.WatchlistClient(http_get=http_get)

    def test_watchlists_preserve_exchange_and_conid(self):
        lists = _run(self._client().fetch_all())
        favorites = next(w for w in lists if w.id == "10")
        assert [(e.conid, e.exchange) for e in favorites.entries] == [
            (693388387, "LSEETF"), (73340487, "ARCA")
        ]
        # same ticker, two identities — exactly the collision case
        assert len({e.symbol for e in favorites.entries}) == 1

    def test_routing_comes_from_config(self):
        lists = _run(self._client().fetch_all())
        assert next(w for w in lists if w.id == "10").sleeve == "swing"
        assert next(w for w in lists if w.id == "104").emphasis == "thematic"

    def test_missing_watchlist_client_degrades_to_empty(self):
        src = ibkr.IBKRSource(ib_factory=_FakeIB)
        assert _run(src.watchlists()) == []

    def test_watchlist_outage_does_not_raise(self):
        def boom(path, params):
            raise ConnectionError("gateway down")

        src = ibkr.IBKRSource(
            ib_factory=_FakeIB, watchlist_client=ibkr.WatchlistClient(http_get=boom)
        )
        assert _run(src.watchlists()) == []


# ═══════════════════════════ contract-level invariants ═══════════════════════════

class TestIdentityInvariants:
    def test_instrument_key_includes_the_exchange(self):
        assert SOXL_LSE.key == "693388387@LSEETF"
        assert SOXL_US.key == "73340487@ARCA"
        assert SOXL_LSE.symbol == SOXL_US.symbol      # …and yet

    def test_leveraged_registry_is_keyed_on_conid(self):
        from app.config import LEVERAGED_ETPS, SYMBOL_COLLISIONS

        assert LEVERAGED_ETPS[693388387]["leverage"] == 4.0
        assert LEVERAGED_ETPS[73340487]["leverage"] == 3.0
        assert LEVERAGED_ETPS[693388345]["leverage"] == -3.0   # the LSE inverse
        assert set(SYMBOL_COLLISIONS["SOXL"]) == {693388387, 73340487}

    def test_sources_expose_the_price_source_protocol_surface(self):
        for cls in (ibkr.IBKRSource, yahoo.YahooSource):
            for method in ("get_bars", "get_quote", "resolve"):
                assert callable(getattr(cls, method)), f"{cls.__name__}.{method}"
            assert isinstance(getattr(cls, "name"), str)
