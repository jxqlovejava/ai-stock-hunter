# -*- coding: utf-8 -*-
"""个股资金流模块测试。"""

from __future__ import annotations

import pytest

from src.data.capital_flow_provider import (
    CapitalFlowProvider,
    _compute_main_consecutive_days,
    _recent_price_trend,
    _symbol_to_market,
    _to_secid,
)
from src.data.schema import MoneyFlowSnapshot


class TestSecidConversion:
    def test_shanghai_stock(self):
        assert _to_secid("600519") == "1.600519"

    def test_shenzhen_stock(self):
        assert _to_secid("000001") == "0.000001"

    def test_stock_with_prefix(self):
        assert _to_secid("sh600519") == "1.600519"
        assert _to_secid("sz000001") == "0.000001"


class TestSymbolToMarket:
    def test_shanghai(self):
        assert _symbol_to_market("600519") == "sh"

    def test_shenzhen(self):
        assert _symbol_to_market("000001") == "sz"

    def test_beijing(self):
        assert _symbol_to_market("920000") == "bj"

    def test_stock_with_prefix(self):
        assert _symbol_to_market("sh600519") == "sh"


class TestParseEmKlines:
    def test_parse_typical_klines(self):
        klines = [
            "2026-07-01,1000000,-200000,-300000,400000,1100000,0.10,-0.02,-0.03,0.04,0.11,100.0,1.0,10000,5000000",
            "2026-07-02,2000000,-400000,-600000,800000,1200000,0.12,-0.024,-0.036,0.048,0.12,101.0,1.0,20000,10000000",
        ]
        provider = CapitalFlowProvider()
        df = provider._parse_em_klines(klines)

        assert len(df) == 2
        # 元 → 万元
        assert df["super_large_net"].iloc[0] == 110.0  # 1,100,000 / 10000
        assert df["large_net"].iloc[0] == 40.0
        assert df["medium_net"].iloc[0] == -30.0
        assert df["small_net"].iloc[0] == -20.0
        assert df["main_net"].iloc[0] == 150.0
        assert df["total_turnover"].iloc[0] == 500.0
        assert df["close"].iloc[0] == 100.0
        assert df["change_pct"].iloc[0] == 0.01

    def test_parse_incomplete_line_is_skipped(self):
        klines = [
            "2026-07-01,1000000,-200000",
            "2026-07-02,2000000,-400000,-600000,800000,1200000,0.12,-0.024,-0.036,0.048,0.12,101.0,0.01,20000,10000000",
        ]
        provider = CapitalFlowProvider()
        df = provider._parse_em_klines(klines)
        assert len(df) == 1


class TestMainConsecutiveDays:
    def test_consecutive_inflow(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "main_net": [100.0, 200.0, 50.0],
        })
        assert _compute_main_consecutive_days(df) == 3

    def test_consecutive_outflow(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "main_net": [-100.0, -200.0, -50.0],
        })
        assert _compute_main_consecutive_days(df) == -3

    def test_interrupted_consecutive(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
            "main_net": [100.0, -200.0, 50.0, 80.0],
        })
        # 最后两天流入
        assert _compute_main_consecutive_days(df) == 2

    def test_latest_zero(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02"],
            "main_net": [100.0, 0.0],
        })
        assert _compute_main_consecutive_days(df) == 0


class TestRecentPriceTrend:
    def test_up_trend(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"],
            "close": [100.0, 101.0, 102.0, 103.0, 105.0],
        })
        assert _recent_price_trend(df) == "up"

    def test_down_trend(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"],
            "close": [100.0, 99.0, 98.0, 97.0, 95.0],
        })
        assert _recent_price_trend(df) == "down"

    def test_neutral_trend(self):
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
            "close": [100.0, 101.0, 101.5],
        })
        assert _recent_price_trend(df) == "neutral"


class TestMoneyFlowSnapshot:
    def test_empty_when_no_data(self):
        snap = MoneyFlowSnapshot(symbol="600519")
        assert snap.empty is True

    def test_not_empty_with_main_net(self):
        snap = MoneyFlowSnapshot(symbol="600519", main_net=100.0)
        assert snap.empty is False

    def test_not_empty_with_data_gap(self):
        snap = MoneyFlowSnapshot(symbol="600519", data_gap_reason="missing")
        assert snap.empty is False


class TestCapitalFlowProviderWithMock:
    def test_get_money_flow_returns_snapshot_from_em(self, monkeypatch):
        provider = CapitalFlowProvider()

        def mock_fetch_em(*args, **kwargs):
            import pandas as pd
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
                "super_large_net": [10.0, 20.0, 30.0],
                "large_net": [5.0, 5.0, 5.0],
                "medium_net": [0.0, 0.0, 0.0],
                "small_net": [-5.0, -10.0, -15.0],
                "main_net": [15.0, 25.0, 35.0],
                "total_turnover": [100.0, 120.0, 150.0],
                "close": [100.0, 101.0, 104.0],
                "change_pct": [0.0, 0.01, 0.0297],
                "volume": [1000, 1000, 1000],
            })
            from src.data.source_citation import SourceCitation
            citation = SourceCitation(provider="eastmoney", field="test")
            return df, citation

        monkeypatch.setattr(provider, "_fetch_em_daykline", mock_fetch_em)
        monkeypatch.setattr(provider, "_fetch_akshare_fallback", lambda *a, **k: (None, None, ""))

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        assert snap.symbol == "600519"
        assert snap.super_large_net == 30.0
        assert snap.large_net == 5.0
        assert snap.main_net == 35.0
        assert snap.main_consecutive_days == 3
        assert snap.recent_price_trend == "up"
        assert snap.citation is not None
        assert snap.citation.provider == "eastmoney"

    def test_get_money_flow_returns_data_gap_when_all_fail(self, monkeypatch):
        provider = CapitalFlowProvider()
        monkeypatch.setattr(provider, "_fetch_em_daykline", lambda *a, **k: (None, None))
        monkeypatch.setattr(provider, "_fetch_akshare_fallback", lambda *a, **k: (None, None, "all failed"))

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        assert snap.data_gap_reason != ""
        assert snap.empty is False  # data_gap_reason makes it non-empty

    def test_get_money_flow_akshare_fallback(self, monkeypatch):
        provider = CapitalFlowProvider()
        monkeypatch.setattr(provider, "_fetch_em_daykline", lambda *a, **k: (None, None))

        def mock_akshare(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-07-03"]),
                "super_large_net": [0.0],
                "large_net": [100.0],
                "medium_net": [0.0],
                "small_net": [0.0],
                "main_net": [100.0],
                "total_turnover": [500.0],
                "close": [100.0],
                "change_pct": [0.01],
                "volume": [1000],
            })
            citation = SourceCitation(provider="akshare", field="test")
            return df, citation, "[DATA_GAP] missing detail"

        monkeypatch.setattr(provider, "_fetch_akshare_fallback", mock_akshare)

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        assert snap.main_net == 100.0
        assert "missing detail" in snap.data_gap_reason
