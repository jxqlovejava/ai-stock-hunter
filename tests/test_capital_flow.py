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
from src.game_theory.capital_flow import CapitalFlowAnalyzer, DivergenceType


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
    def _mock_today_fail(self, provider, monkeypatch):
        """模拟当日实时源不可用（同花顺/efinance 当日接口失败），
        使降级链回退到历史序列（东财/efinance history/AKShare）。"""
        monkeypatch.setattr(provider, "_fetch_intraday_ths", lambda *a, **k: (None, None, "[DATA_GAP] 同花顺不可用"))
        monkeypatch.setattr(provider, "_fetch_today_bill", lambda *a, **k: (None, None, "[DATA_GAP] efinance 当日不可用"))

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

        self._mock_today_fail(provider, monkeypatch)
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
        self._mock_today_fail(provider, monkeypatch)
        monkeypatch.setattr(provider, "_fetch_em_daykline", lambda *a, **k: (None, None))
        monkeypatch.setattr(
            provider, "_fetch_efinance_fallback",
            lambda *a, **k: (None, None, "efinance failed"),
        )
        monkeypatch.setattr(provider, "_fetch_akshare_fallback", lambda *a, **k: (None, None, "all failed"))

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        assert snap.data_gap_reason != ""
        assert snap.empty is False  # data_gap_reason makes it non-empty

    def test_get_money_flow_akshare_fallback(self, monkeypatch):
        provider = CapitalFlowProvider()
        self._mock_today_fail(provider, monkeypatch)
        monkeypatch.setattr(provider, "_fetch_em_daykline", lambda *a, **k: (None, None))
        # efinance 介于东财与 akshare 之间，模拟其失败以验证 akshare 兜底路径
        monkeypatch.setattr(
            provider, "_fetch_efinance_fallback",
            lambda *a, **k: (None, None, "[DATA_GAP] efinance 不可用"),
        )

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

    def test_today_source_priority(self, monkeypatch):
        """当日实时源（同花顺即时）优先于历史序列——返回当日数据且不与当日涨跌脱节。"""
        provider = CapitalFlowProvider()

        def mock_today(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-08-10"]),
                "super_large_net": [0.0],
                "large_net": [-25300.0],
                "medium_net": [0.0],
                "small_net": [0.0],
                "main_net": [-25300.0],
                "total_turnover": [942100.0],
                "close": [74.88],
                "change_pct": [0.0564],
                "volume": [0],
            })
            citation = SourceCitation(provider="tonghuashun", field="test")
            return df, citation, ""

        monkeypatch.setattr(provider, "_fetch_intraday_ths", mock_today)
        # 历史序列模拟提供 3 日历史，用于连续天数计算
        def mock_hist(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-08-05", "2026-08-06", "2026-08-07"]),
                "super_large_net": [100.0, 200.0, 300.0],
                "large_net": [5.0, 5.0, 5.0],
                "medium_net": [0.0, 0.0, 0.0],
                "small_net": [-5.0, -10.0, -15.0],
                "main_net": [105.0, 205.0, 305.0],
                "total_turnover": [1000.0, 1200.0, 1500.0],
                "close": [100.0, 101.0, 104.0],
                "change_pct": [0.0, 0.01, 0.0297],
                "volume": [1000, 1000, 1000],
            })
            citation = SourceCitation(provider="eastmoney", field="test")
            return df, citation
        monkeypatch.setattr(provider, "_fetch_em_daykline", mock_hist)

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        # 当日值来自同花顺即时源（当日涨跌幅 +5.64% 未被 T-1 污染）
        assert snap.price_change_pct == 0.0564
        assert snap.main_net == -25300.0
        assert snap.total_turnover == 942100.0
        # 连续天数由历史序列（3日流入 105/205/305）+ 当日流出拼接计算
        assert snap.citation is not None
        assert snap.citation.provider == "tonghuashun"

    def test_history_breakdown_backfill(self, monkeypatch):
        """同花顺当日源仅给主力净额时，用历史序列最新一日拆单比例回填拆单，
        main_net 方向保持同花顺当日值不变。"""
        provider = CapitalFlowProvider()

        def mock_today(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-08-10"]),
                "super_large_net": [0.0],
                "large_net": [-25300.0],
                "medium_net": [0.0],
                "small_net": [0.0],
                "main_net": [-25300.0],
                "total_turnover": [942100.0],
                "close": [74.88],
                "change_pct": [0.0564],
                "volume": [0],
            })
            citation = SourceCitation(provider="tonghuashun", field="test")
            return df, citation, ""

        def mock_hist(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            # 历史最新日 08-07：main=305, super=300, large=5 → 拆单比例 super≈0.984 large≈0.016
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-08-05", "2026-08-06", "2026-08-07"]),
                "super_large_net": [100.0, 200.0, 300.0],
                "large_net": [5.0, 5.0, 5.0],
                "medium_net": [0.0, 0.0, 0.0],
                "small_net": [-5.0, -10.0, -15.0],
                "main_net": [105.0, 205.0, 305.0],
                "total_turnover": [1000.0, 1200.0, 1500.0],
                "close": [100.0, 101.0, 104.0],
                "change_pct": [0.0, 0.01, 0.0297],
                "volume": [1000, 1000, 1000],
            })
            citation = SourceCitation(provider="eastmoney", field="test")
            return df, citation

        monkeypatch.setattr(provider, "_fetch_intraday_ths", mock_today)
        monkeypatch.setattr(provider, "_fetch_em_daykline", mock_hist)
        monkeypatch.setattr(provider, "_fetch_efinance_fallback", lambda *a, **k: (None, None, ""))
        monkeypatch.setattr(provider, "_fetch_akshare_fallback", lambda *a, **k: (None, None, ""))

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        # main_net 保持同花顺当日权威值
        assert snap.main_net == -25300.0
        # 拆单按历史比例回填：super≈300/305, large≈5/305 → super≈-24918, large≈-415
        assert abs(snap.super_large_net + snap.large_net - snap.main_net) < 1.0
        assert snap.super_large_net < 0  # 主力净流出方向
        # 当日涨跌幅不被历史污染
        assert snap.price_change_pct == 0.0564
        # 连续天数由历史（3日流入）+ 当日流出拼接
        assert snap.main_consecutive_days <= 0

    def test_history_stale_date_annotated(self, monkeypatch):
        """当日实时源失败、仅历史序列可用时，显式标记数据滞后日期。"""
        provider = CapitalFlowProvider()
        self._mock_today_fail(provider, monkeypatch)

        def mock_hist(*args, **kwargs):
            import pandas as pd
            from src.data.source_citation import SourceCitation
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-08-07"]),
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
            citation = SourceCitation(provider="eastmoney", field="test")
            return df, citation
        monkeypatch.setattr(provider, "_fetch_em_daykline", mock_hist)
        monkeypatch.setattr(provider, "_fetch_efinance_fallback", lambda *a, **k: (None, None, ""))
        monkeypatch.setattr(provider, "_fetch_akshare_fallback", lambda *a, **k: (None, None, ""))

        snap = provider.get_money_flow("600519", weeks=4)
        assert snap is not None
        # 历史源最新 08-07，非当日 → 应标注滞后日期
        assert "滞后" in snap.data_gap_reason
        assert "2026-08-07" in snap.data_gap_reason


class TestTurnoverMissingGuard:
    """total_turnover 缺失（上游接口失败兜底为 0）时，背离幅度不可计算。

    回归: 2026-08-10 科士达(002518) 东财资金流断连 → turnover=0 →
    分母兜底 max(0,1)=1 → 2748万主力净流入算出 55 万分 → 封顶 100，
    触发 verdict ×0.7 折扣 + 置信度 -0.15，把本可出裁决的分析拦在门外。
    """

    _KSTAR_FLOW = dict(
        symbol="002518",
        super_large_net=486.7,
        large_net=2261.2,
        medium_net=-66.0,
        small_net=-2681.9,
        price_change_pct=-0.031,
        main_consecutive_days=1,
    )

    def test_zero_turnover_does_not_saturate_divergence_score(self):
        result = CapitalFlowAnalyzer().analyze(total_turnover=0.0, **self._KSTAR_FLOW)
        # 定性分类保留（方向已知），但幅度分必须归零
        assert result.divergence_type == DivergenceType.BEAR_TRAP
        assert result.divergence_score == 0.0
        # 不得触发 verdict.py 的 >60 → ×0.7 折扣线（本场景严格为 0）
        assert result.manipulation_risk_score == 0.0
        assert any("DATA_GAP" in g for g in result.data_gaps)

    def test_zero_turnover_bull_trap_also_zeroed(self):
        result = CapitalFlowAnalyzer().analyze(
            **{**self._KSTAR_FLOW,
               "price_change_pct": 0.031,
               "super_large_net": -486.7,
               "large_net": -2261.2},
            total_turnover=0.0,
        )
        assert result.divergence_type == DivergenceType.BULL_TRAP
        assert result.divergence_score == 0.0
        assert any("DATA_GAP" in g for g in result.data_gaps)

    def test_zero_turnover_skips_consecutive_days_bonus(self):
        """turnover=0 时即使主力连续流出≥3天，+20 加成也被 turnover_known 守卫抑制。"""
        result = CapitalFlowAnalyzer().analyze(
            **{**self._KSTAR_FLOW, "main_consecutive_days": -3},
            total_turnover=0.0,
        )
        assert result.divergence_score == 0.0          # +20 加成不得混入
        assert result.manipulation_risk_score == 15.0  # 仅连续流出风险块（方向已知）生效
        assert not any("背离加剧" in s for s in result.signals)

    def test_normal_turnover_scores_small_divergence(self):
        """对照组：成交额正常时同样的主力流入只得个位数分（≈9，远低于 60 折扣线）。"""
        result = CapitalFlowAnalyzer().analyze(total_turnover=60000.0, **self._KSTAR_FLOW)
        assert result.divergence_score == pytest.approx(9.2, abs=2.0)
        assert not result.data_gaps
