# -*- coding: utf-8 -*-
"""Tests for US overnight market snapshot integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.data.aggregator import DataAggregator
from src.data.us_overnight import (
    EASTMONEY_US_API_URL,
    USIndexSnapshot,
    USOvernightSnapshot,
    fetch_us_overnight,
)
from src.routing.diagnosis import DiagnosisEngine


def _mock_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = payload
    return mock


def _index_item(em_code: str, close: float, change_pct: float, prev_close: float, ts: int) -> dict:
    names = {"SPX": "标普500", "NDX": "纳斯达克", "DJIA": "道琼斯"}
    return {
        "f12": em_code,
        "f2": close,
        "f3": change_pct,
        "f18": prev_close,
        "f14": names.get(em_code, ""),
        "f124": ts,
    }


class TestUSIndexSnapshot:
    def test_to_dict(self):
        snap = USIndexSnapshot(
            symbol="^GSPC",
            name="S&P 500",
            trade_date=date(2026, 7, 10),
            close=5500.0,
            prev_close=5600.0,
            change_pct=-1.7857,
        )
        d = snap.to_dict()
        assert d["symbol"] == "^GSPC"
        assert d["change_pct"] == pytest.approx(-1.7857)


class TestFetchUSOvernight:
    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_computes_change_pct(self, mock_get):
        ts = 1783713588  # 2026-07-10 UTC
        payload = {
            "data": {
                "diff": [
                    _index_item("SPX", 5500.0, -1.79, 5600.0, ts),
                    _index_item("NDX", 17500.0, -0.85, 17650.0, ts + 10),
                    _index_item("DJIA", 42000.0, 0.35, 41855.0, ts + 5),
                ]
            }
        }
        mock_get.return_value = _mock_response(payload)

        result = fetch_us_overnight()

        assert result is not None
        assert result.sp500 is not None
        assert result.sp500.close == pytest.approx(5500.0)
        assert result.sp500.prev_close == pytest.approx(5600.0)
        assert result.sp500.change_pct == pytest.approx(-1.79)
        assert result.nasdaq is not None
        assert result.dow is not None
        assert "S&P500 -1.79%" in result.summary
        assert result.trade_date.isoformat() == "2026-07-10"

    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_returns_none_on_empty_response(self, mock_get):
        mock_get.return_value = _mock_response({"data": {"diff": []}})

        result = fetch_us_overnight()
        assert result is None

    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_partial_failure(self, mock_get):
        payload = {
            "data": {
                "diff": [
                    _index_item("SPX", 5500.0, -1.79, 5600.0, 1783713588),
                ]
            }
        }
        mock_get.return_value = _mock_response(payload)

        result = fetch_us_overnight()
        assert result is not None
        assert result.sp500 is not None
        assert result.nasdaq is None
        assert result.dow is None

    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_retry_then_fail(self, mock_get):
        mock_get.side_effect = Exception("network error")

        result = fetch_us_overnight()
        assert result is None
        assert mock_get.call_count == 3

    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_computes_prev_from_change_pct(self, mock_get):
        # f18 缺失时从 change_pct 反推 prev_close
        payload = {
            "data": {
                "diff": [
                    {"f12": "SPX", "f2": 5500.0, "f3": -1.7857, "f18": 0.0, "f14": "标普500", "f124": 1783713588},
                ]
            }
        }
        mock_get.return_value = _mock_response(payload)

        result = fetch_us_overnight()
        assert result is not None
        assert result.sp500 is not None
        assert result.sp500.prev_close == pytest.approx(5600.0, rel=1e-3)

    @patch("src.data.us_overnight.requests.get")
    def test_fetch_us_overnight_change_pct_minus_100(self, mock_get):
        # change_pct == -100 时不能除零
        payload = {
            "data": {
                "diff": [
                    {"f12": "SPX", "f2": 0.0, "f3": -100.0, "f18": 0.0, "f14": "标普500", "f124": 1783713588},
                ]
            }
        }
        mock_get.return_value = _mock_response(payload)

        result = fetch_us_overnight()
        assert result is None  # close <= 0 被跳过


class TestDataAggregatorUSOvernight:
    @patch("src.data.aggregator.fetch_us_overnight")
    def test_get_us_overnight_caches_result(self, mock_fetch):
        snapshot = USOvernightSnapshot(
            trade_date=date(2026, 7, 10),
            sp500=USIndexSnapshot(
                symbol="^GSPC",
                name="S&P 500",
                trade_date=date(2026, 7, 10),
                close=5500.0,
                prev_close=5600.0,
                change_pct=-1.79,
            ),
            nasdaq=None,
            dow=None,
        )
        mock_fetch.return_value = snapshot

        agg = DataAggregator()
        first = agg.get_us_overnight()
        second = agg.get_us_overnight()

        assert first is second
        mock_fetch.assert_called_once()

    @patch("src.data.aggregator.fetch_us_overnight")
    def test_get_us_overnight_respects_ttl(self, mock_fetch):
        snapshot = USOvernightSnapshot(
            trade_date=date(2026, 7, 10),
            sp500=None,
            nasdaq=None,
            dow=None,
        )
        mock_fetch.return_value = snapshot

        agg = DataAggregator()
        # Inject an expired cache entry manually
        agg._cache["us_overnight"] = (datetime.now() - timedelta(minutes=15), snapshot)
        result = agg.get_us_overnight()

        assert result is snapshot
        mock_fetch.assert_called_once()


class TestDiagnosisMacroScoring:
    def test_score_macro_punishes_sp500_crash(self):
        engine = DiagnosisEngine()
        macro = {
            "us_overnight": {
                "sp500": {"change_pct": -2.5},
                "nasdaq": {"change_pct": -3.0},
            }
        }
        score = engine._score_macro(macro)
        assert score < 50

    def test_score_macro_rewards_sp500_rally(self):
        engine = DiagnosisEngine()
        macro = {
            "us_overnight": {
                "sp500": {"change_pct": 2.5},
            }
        }
        score = engine._score_macro(macro)
        assert score > 50

    def test_score_macro_ignores_missing_us_data(self):
        engine = DiagnosisEngine()
        score = engine._score_macro({})
        assert 0 <= score <= 100


class TestOrchestratorUSOvernightIntegration:
    @patch("src.routing.orchestrator.DataAggregator.get_us_overnight")
    @patch("src.routing.orchestrator.DataAggregator.get_cross_validated_quote")
    @patch("src.routing.orchestrator.DataAggregator.get_financials")
    @patch("src.routing.orchestrator.DataAggregator.get_fundamental_metrics")
    @patch("src.routing.orchestrator.DataAggregator.get_industry_pe_pb")
    @patch("src.routing.orchestrator.DataAggregator.get_earnings_growth")
    @patch("src.routing.orchestrator.DataAggregator.get_dividend_data")
    def test_us_overnight_injected_into_result(
        self,
        mock_dividend,
        mock_earnings_growth,
        mock_industry_pe_pb,
        mock_fundamental_metrics,
        mock_financials,
        mock_quote,
        mock_us_overnight,
    ):
        from src.data.schema import Quote
        from src.routing.orchestrator import Orchestrator

        mock_quote.return_value = (
            Quote(
                symbol="600519",
                name="Kweichow Moutai",
                price=1500.0,
                change_pct=0.5,
                volume=10000,
                turnover=1.5e7,
                source="test",
            ),
            False,
            False,
        )
        mock_financials.return_value = []
        mock_fundamental_metrics.return_value = None
        mock_industry_pe_pb.return_value = (None, None)
        mock_earnings_growth.return_value = None
        mock_dividend.return_value = None

        snapshot = USOvernightSnapshot(
            trade_date=date(2026, 7, 10),
            sp500=USIndexSnapshot(
                symbol="^GSPC",
                name="S&P 500",
                trade_date=date(2026, 7, 10),
                close=5500.0,
                prev_close=5600.0,
                change_pct=-2.5,
            ),
            nasdaq=None,
            dow=None,
        )
        mock_us_overnight.return_value = snapshot

        orch = Orchestrator()
        result = orch.run("600519", "SH", skip_t0=True)

        assert result.us_overnight is not None
        assert result.us_overnight["sp500"]["change_pct"] == pytest.approx(-2.5)
