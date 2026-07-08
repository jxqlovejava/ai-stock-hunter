# -*- coding: utf-8 -*-
"""测试护栏系统 — SourceCitation 创建和 GuardrailEnforcer 违规检测。"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta


class TestSourceCitation:
    """测试 SourceCitation 数据类。"""

    def test_create_citation(self):
        """创建基本引用。"""
        from src.data.source_citation import SourceCitation
        cit = SourceCitation(
            provider="mootdx",
            field="quote",
            confidence=0.85,
        )
        assert cit.provider == "mootdx"
        assert cit.field == "quote"
        assert cit.confidence == 0.85
        assert cit.url_or_endpoint == ""
        assert cit.is_cached is False

    def test_citation_is_fresh(self):
        """新鲜度检查 — 刚创建的引用应该是新鲜的。"""
        from src.data.source_citation import SourceCitation
        cit = SourceCitation(
            provider="mootdx",
            field="quote",
            data_freshness=timedelta(hours=1),
        )
        assert cit.is_fresh is True

    def test_citation_is_stale(self):
        """过期引用检测。"""
        from src.data.source_citation import SourceCitation
        cit = SourceCitation(
            provider="mootdx",
            field="quote",
            fetch_timestamp=datetime.now() - timedelta(hours=2),
            data_freshness=timedelta(hours=1),
        )
        assert cit.is_fresh is False

    def test_citation_age(self):
        """引用年龄计算。"""
        from src.data.source_citation import SourceCitation
        cit = SourceCitation(
            provider="mootdx",
            field="quote",
            fetch_timestamp=datetime.now() - timedelta(minutes=30),
        )
        assert cit.age.total_seconds() > 0

    def test_make_citation_shortcut(self):
        """快捷创建引用函数。"""
        from src.data.source_citation import make_citation
        cit = make_citation("mootdx", "close_price", data_type="realtime_quote")
        assert cit.provider == "mootdx"
        assert cit.confidence == 0.85
        # 实时行情应为 5 分钟有效期
        assert cit.data_freshness == timedelta(minutes=5)

    def test_make_citation_unknown_provider(self):
        """未知数据源使用默认置信度。"""
        from src.data.source_citation import make_citation
        cit = make_citation("unknown_source", "field")
        assert cit.confidence == 0.5

    def test_provider_confidence_map(self):
        """验证所有已知数据源都有置信度定义。"""
        from src.data.source_citation import PROVIDER_CONFIDENCE
        expected_providers = ["guosen", "mootdx", "eastmoney", "huatai",
                             "tencent", "akshare", "cninfo", "tonghuashun"]
        for p in expected_providers:
            assert p in PROVIDER_CONFIDENCE, f"缺失: {p}"
            assert 0 <= PROVIDER_CONFIDENCE[p] <= 1.0

    def test_freshness_limits(self):
        """验证所有数据类型都有新鲜度上限。"""
        from src.data.source_citation import FRESHNESS_LIMITS
        expected_types = ["realtime_quote", "daily_bar", "factor",
                         "financials", "topic_policy", "analyst_report", "fundamental"]
        for t in expected_types:
            assert t in FRESHNESS_LIMITS, f"缺失: {t}"
            assert FRESHNESS_LIMITS[t].total_seconds() > 0


class TestGuardrailEnforcer:
    """测试 GuardrailEnforcer 护栏执行器。"""

    def test_empty_citations_warning(self):
        """空引用列表应产生 WARNING。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(stage="diagnosis", source_citations=[])
        assert len(violations) > 0
        assert any(v.rule == "G001_NO_SOURCES" for v in violations)

    def test_low_confidence_fatal(self):
        """低置信度在裁决阶段应是 FATAL。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(stage="verdict", confidence=0.5)
        assert any(
            v.rule == "G002_LOW_CONFIDENCE" and v.severity == "FATAL"
            for v in violations
        )

    def test_low_confidence_warning_in_l1(self):
        """低置信度在诊断阶段应只是 WARNING。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(stage="diagnosis", confidence=0.5)
        assert any(
            v.rule == "G002_LOW_CONFIDENCE" and v.severity == "WARNING"
            for v in violations
        )

    def test_moderate_confidence_info(self):
        """中等置信度应产生 INFO。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(stage="diagnosis", confidence=0.75)
        assert any(v.rule == "G003_MODERATE_CONFIDENCE" for v in violations)

    def test_high_confidence_no_warning(self):
        """高置信度 (≥0.8) 不应触发任何置信度违规。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(stage="diagnosis", confidence=0.90)
        assert not any(
            v.rule in ("G002_LOW_CONFIDENCE", "G003_MODERATE_CONFIDENCE")
            for v in violations
        )

    def test_stale_data_warning(self):
        """过期数据应产生 WARNING。"""
        from src.routing.guardrails import GuardrailEnforcer
        from src.data.source_citation import SourceCitation
        enforcer = GuardrailEnforcer()
        stale_cit = SourceCitation(
            provider="mootdx",
            field="quote",
            fetch_timestamp=datetime.now() - timedelta(hours=3),
            data_freshness=timedelta(hours=1),
        )
        violations = enforcer.enforce(stage="diagnosis", source_citations=[stale_cit])
        assert any(v.rule == "G004_STALE_DATA" for v in violations)

    def test_fresh_data_no_stale_warning(self):
        """新鲜数据不应产生过期警告。"""
        from src.routing.guardrails import GuardrailEnforcer
        from src.data.source_citation import SourceCitation
        enforcer = GuardrailEnforcer()
        fresh_cit = SourceCitation(
            provider="mootdx",
            field="quote",
            data_freshness=timedelta(hours=1),
        )
        violations = enforcer.enforce(
            stage="diagnosis", source_citations=[fresh_cit],
            data_freshness_check=True,
        )
        assert not any(v.rule == "G004_STALE_DATA" for v in violations)

    def test_is_blocked_fatal(self):
        """FATAL 违规应触发 is_blocked。"""
        from src.routing.guardrails import GuardrailEnforcer, GuardrailViolation
        enforcer = GuardrailEnforcer()
        fatal = GuardrailViolation(
            rule="G002_LOW_CONFIDENCE",
            severity="FATAL",
            message="test",
        )
        assert enforcer.is_blocked([fatal]) is True

    def test_is_not_blocked_warning_only(self):
        """仅有 WARNING 不应触发 is_blocked。"""
        from src.routing.guardrails import GuardrailEnforcer, GuardrailViolation
        enforcer = GuardrailEnforcer()
        warn = GuardrailViolation(
            rule="G001_NO_SOURCES",
            severity="WARNING",
            message="test",
        )
        assert enforcer.is_blocked([warn]) is False

    def test_get_warnings(self):
        """提取所有 WARNING 消息。"""
        from src.routing.guardrails import GuardrailEnforcer, GuardrailViolation
        enforcer = GuardrailEnforcer()
        violations = [
            GuardrailViolation(rule="G001", severity="WARNING", message="w1"),
            GuardrailViolation(rule="G002", severity="FATAL", message="f1"),
            GuardrailViolation(rule="G003", severity="WARNING", message="w2"),
            GuardrailViolation(rule="G004", severity="INFO", message="i1"),
        ]
        warnings = enforcer.get_warnings(violations)
        assert len(warnings) == 2
        assert "w1" in warnings
        assert "w2" in warnings
        assert "f1" not in warnings
        assert "i1" not in warnings

    def test_unsourced_detection(self):
        """未标注来源的数据点检测。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(
            stage="diagnosis",
            has_unsourced=True,
            unsourced_count=1,
            total_data_points=10,
        )
        assert any(v.rule == "G006_HAS_UNSOURCED" for v in violations)

    def test_excessive_unsourced(self):
        """超过阈值的未标注来源比例。"""
        from src.routing.guardrails import GuardrailEnforcer
        enforcer = GuardrailEnforcer()
        violations = enforcer.enforce(
            stage="diagnosis",
            has_unsourced=True,
            unsourced_count=5,
            total_data_points=10,  # 50% > 30% threshold
        )
        assert any(v.rule == "G005_EXCESSIVE_UNSOURCED" for v in violations)
