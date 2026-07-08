# -*- coding: utf-8 -*-
"""高管数据管道测试 — 从 adapter 到 诊断评分到 仓位调度信号全链路。"""

import pytest
from unittest.mock import patch, MagicMock

from src.data.schema import ExecutiveTrade, ExecutiveProfile, BoardChange
from src.data.miaoxiang_provider import _safe_int, _safe_float


# ------------------------------------------------------------------
# _safe_int / _safe_float
# ------------------------------------------------------------------

class TestSafeConverters:
    def test_safe_int_normal(self):
        assert _safe_int(123) == 123
        assert _safe_int("456") == 456
        assert _safe_int("1,234") == 1234
        assert _safe_int("1，234") == 1234

    def test_safe_int_none(self):
        assert _safe_int(None) is None
        assert _safe_int("abc") is None
        assert _safe_int("") is None

    def test_safe_float_normal(self):
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5

    def test_safe_float_none(self):
        assert _safe_float(None) is None
        assert _safe_float("abc") is None


# ------------------------------------------------------------------
# _extract_table_rows
# ------------------------------------------------------------------

class TestExtractTableRows:
    @pytest.fixture
    def mock_table_result(self):
        return {
            "data": {
                "dataTableDTOList": [
                    {
                        "headName": ["姓名", "职务", "变动股数"],
                        "col_1": ["张三", "李四"],
                        "col_2": ["董事长", "总经理"],
                        "col_3": [10000, -5000],
                    }
                ]
            }
        }

    def test_extract_rows(self, mock_table_result):
        from src.data.miaoxiang_adapter import MiaoXiangAdapter
        rows = MiaoXiangAdapter._extract_table_rows(mock_table_result)
        assert len(rows) == 2
        assert rows[0]["姓名"] == "张三"
        assert rows[0]["职务"] == "董事长"
        assert rows[0]["变动股数"] == 10000
        assert rows[1]["姓名"] == "李四"

    def test_extract_empty(self):
        from src.data.miaoxiang_adapter import MiaoXiangAdapter
        assert MiaoXiangAdapter._extract_table_rows({}) == []
        assert MiaoXiangAdapter._extract_table_rows({"data": {"dataTableDTOList": []}}) == []


# ------------------------------------------------------------------
# _parse_executive_trades_from_raw
# ------------------------------------------------------------------

class TestParseExecutiveTrades:
    def test_parse_trades(self):
        from src.data.miaoxiang_provider import MiaoXiangProvider
        raw = [
            {"高管姓名": "张三", "职务": "董事长", "变动方向": "增持", "变动日期": "2025-03-15",
             "变动股数": 50000, "交易均价": 25.5, "变动金额": 1275000, "变动后持股比例": 15.2},
            {"高管姓名": "李四", "职务": "总经理", "变动方向": "减持", "变动日期": "2025-04-01",
             "变动股数": 20000, "交易均价": 28.0, "变动金额": 560000},
        ]
        result = MiaoXiangProvider._parse_executive_trades_from_raw(raw)
        assert len(result) == 2
        assert result[0].executive_name == "张三"
        assert result[0].trade_type == "buy"
        assert result[0].volume == 50000
        assert result[1].executive_name == "李四"
        assert result[1].trade_type == "sell"

    def test_parse_trades_empty(self):
        from src.data.miaoxiang_provider import MiaoXiangProvider
        assert MiaoXiangProvider._parse_executive_trades_from_raw(None) == []
        assert MiaoXiangProvider._parse_executive_trades_from_raw([]) == []


# ------------------------------------------------------------------
# _parse_executive_profiles_from_raw
# ------------------------------------------------------------------

class TestParseExecutiveProfiles:
    def test_parse_profiles(self):
        from src.data.miaoxiang_provider import MiaoXiangProvider
        raw = [
            {"姓名": "张三", "职务": "董事长", "年龄": 55, "学历": "博士",
             "履历": "曾任XX公司CEO", "任职起始日": "2019-03-01"},
        ]
        result = MiaoXiangProvider._parse_executive_profiles_from_raw(raw)
        assert len(result) == 1
        assert result[0].name == "张三"
        assert result[0].age == 55
        assert result[0].education == "博士"

    def test_parse_profiles_empty(self):
        from src.data.miaoxiang_provider import MiaoXiangProvider
        assert MiaoXiangProvider._parse_executive_profiles_from_raw(None) == []
        assert MiaoXiangProvider._parse_executive_profiles_from_raw([]) == []


# ------------------------------------------------------------------
# _parse_board_changes_from_raw
# ------------------------------------------------------------------

class TestParseBoardChanges:
    def test_parse_changes(self):
        from src.data.miaoxiang_provider import MiaoXiangProvider
        raw = [
            {"姓名": "王五", "原职务": "副总经理", "新职务": "", "变动日期": "2025-06-01",
             "变动原因": "个人原因辞职"},
            {"姓名": "赵六", "原职务": "董事", "新职务": "董事长", "变动日期": "2025-05-15",
             "变动原因": "任期届满"},
        ]
        result = MiaoXiangProvider._parse_board_changes_from_raw(raw)
        assert len(result) == 2
        assert result[0].person_name == "王五"
        assert result[0].reason == "个人原因辞职"
        assert result[1].person_name == "赵六"
        assert result[1].reason == "任期届满"


# ------------------------------------------------------------------
# _score_executive
# ------------------------------------------------------------------

class TestScoreExecutive:
    def test_no_data(self):
        from src.routing.diagnosis import DiagnosisEngine
        result = DiagnosisEngine._score_executive(None)
        assert result["score"] == 50.0
        assert "数据不可用" in result["risks"][0]

    def test_empty_context(self):
        from src.routing.diagnosis import DiagnosisEngine
        result = DiagnosisEngine._score_executive({"trades": [], "profiles": [], "changes": []})
        assert result["score"] == 45.0  # -5 for missing profiles
        assert any("缺失" in r for r in result["risks"])

    def test_net_buying_boost(self):
        from src.routing.diagnosis import DiagnosisEngine
        ctx = {
            "trades": [
                {"trade_type": "buy", "volume": 250000},
            ],
            "profiles": [{"name": "张三", "tenure_start": "2020-01-01"}],
            "changes": [],
        }
        result = DiagnosisEngine._score_executive(ctx)
        assert result["score"] > 60  # 50 + 25(buy) + 5(profiles) + 5(long_tenure)
        assert result["score"] <= 85

    def test_net_selling_penalty(self):
        from src.routing.diagnosis import DiagnosisEngine
        ctx = {
            "trades": [
                {"trade_type": "sell", "volume": 300000},
            ],
            "profiles": [],
            "changes": [],
        }
        result = DiagnosisEngine._score_executive(ctx)
        assert result["score"] < 45  # 50 - 25(sell) - 5(no profiles)
        assert any("净减持" in r for r in result["risks"])

    def test_abnormal_board_change(self):
        from src.routing.diagnosis import DiagnosisEngine
        ctx = {
            "trades": [],
            "profiles": [],
            "changes": [
                {"person_name": "王五", "reason": "个人原因辞职"},
            ],
        }
        result = DiagnosisEngine._score_executive(ctx)
        assert result["score"] <= 35  # 50 - 10 - 5(no profiles)
        assert any("王五" in r for r in result["risks"])

    def test_tenure_expiry_not_penalized(self):
        from src.routing.diagnosis import DiagnosisEngine
        ctx = {
            "trades": [],
            "profiles": [],
            "changes": [
                {"person_name": "赵六", "reason": "任期届满"},
            ],
        }
        result = DiagnosisEngine._score_executive(ctx)
        assert result["score"] >= 45  # only penalized for no profiles, not for tenure expiry


# ------------------------------------------------------------------
# AnalysisReport fields
# ------------------------------------------------------------------

class TestAnalysisReportFields:
    def test_default_executive_fields(self):
        from src.routing.l1_analyze import AnalysisReport
        r = AnalysisReport(symbol="000001", name="平安银行")
        assert r.executive_score == 50.0
        assert r.executive_risks == []


# ------------------------------------------------------------------
# Verdict executive risks passthrough
# ------------------------------------------------------------------

class TestVerdictExecutiveRisks:
    def test_verdict_stores_executive_risks(self):
        from src.routing.l2_judge import Verdict
        v = Verdict(symbol="000001", score=70, executive_risks=["高管净减持"])
        assert len(v.executive_risks) == 1
        assert "高管净减持" in v.executive_risks


# ------------------------------------------------------------------
# TradeSignal executive_risk flag
# ------------------------------------------------------------------

class TestTradeSignalExecutiveRisk:
    def test_signal_default_no_risk(self):
        from src.routing.l3_trade import TradeSignal
        s = TradeSignal(symbol="000001", action="HOLD", target_weight=0.0)
        assert s.executive_risk is False

    def test_signal_with_risk(self):
        from src.routing.l3_trade import TradeSignal
        s = TradeSignal(symbol="000001", action="HOLD", target_weight=0.0, executive_risk=True)
        assert s.executive_risk is True


# ------------------------------------------------------------------
# Orchestrator _get_executive_context
# ------------------------------------------------------------------

class TestOrchestratorExecutiveContext:
    def test_no_miaoxiang_returns_empty(self):
        from src.routing.orchestrator import Orchestrator
        with patch("src.routing.orchestrator.DataAggregator") as mock_agg_class:
            mock_agg = MagicMock()
            mock_agg.miaoxiang = None
            mock_agg_class.return_value = mock_agg
            ctx = Orchestrator._get_executive_context("000001")
            assert ctx == {"trades": [], "profiles": [], "changes": []}

    def test_exception_returns_empty(self):
        from src.routing.orchestrator import Orchestrator
        with patch("src.routing.orchestrator.DataAggregator") as mock_agg_class:
            mock_agg_class.side_effect = RuntimeError("boom")
            ctx = Orchestrator._get_executive_context("000001")
            assert ctx == {"trades": [], "profiles": [], "changes": []}


# ------------------------------------------------------------------
# Schema model_dump round-trip
# ------------------------------------------------------------------

class TestSchemaModelDump:
    def test_executive_trade_dump(self):
        t = ExecutiveTrade(executive_name="张三", position="董事长",
                          trade_type="buy", trade_date="2025-06-01",
                          volume=10000, price=25.5)
        d = t.model_dump()
        assert d["executive_name"] == "张三"
        assert d["trade_type"] == "buy"

    def test_executive_profile_dump(self):
        p = ExecutiveProfile(name="李四", position="总经理", age=50)
        d = p.model_dump()
        assert d["name"] == "李四"

    def test_board_change_dump(self):
        c = BoardChange(person_name="王五", old_position="董事",
                       new_position="董事长", change_date="2025-06-01",
                       reason="任期届满")
        d = c.model_dump()
        assert d["reason"] == "任期届满"
