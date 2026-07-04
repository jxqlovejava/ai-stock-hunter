"""Tests for policy NLP engine."""

import pytest
from src.policy.nlp import (
    PolicyAnalysis,
    PolicyNlpEngine,
    POLICY_QUERIES,
)


class TestPolicyAnalysis:
    def test_default_construction(self):
        a = PolicyAnalysis()
        assert a.sentiment_score == 0.0
        assert a.urgency_level == "LOW"
        assert a.policy_cycle_phase == "中性"

    def test_easing_signal(self):
        a = PolicyAnalysis(
            source="政治局会议",
            sentiment_score=0.6,
            urgency_level="HIGH",
            policy_cycle_phase="宽松",
            keywords=["降准", "积极财政"],
        )
        assert a.urgency_level == "HIGH"
        assert a.policy_cycle_phase == "宽松"


class TestPolicyNlpEngine:
    def setup_method(self):
        self.engine = PolicyNlpEngine()

    def test_basic_sentiment_easing(self):
        text = "中央经济工作会议提出加大逆周期调节力度，适度宽松货币政策，扩大内需促消费"
        score = self.engine._basic_sentiment(text)
        assert score > 0  # Easing language

    def test_basic_sentiment_tightening(self):
        text = "央行强调防风险，去杠杆，加强监管，抑制资产泡沫"
        score = self.engine._basic_sentiment(text)
        assert score < 0  # Tightening language

    def test_basic_sentiment_neutral(self):
        text = "继续实施稳健的货币政策"
        score = self.engine._basic_sentiment(text)
        assert -0.1 <= score <= 0.1

    def test_extract_policy_keywords(self):
        text = "降准降息支持实体经济，推动人工智能和芯片产业发展"
        keywords = self.engine._extract_policy_keywords(text)
        assert "降准" in keywords
        assert "降息" in keywords
        assert "人工智能" in keywords
        assert "芯片" in keywords

    def test_extract_policy_keywords_empty(self):
        keywords = self.engine._extract_policy_keywords("今日天气晴好")
        assert len(keywords) == 0

    def test_to_urgency_high(self):
        assert self.engine._to_urgency(0.7) == "HIGH"
        assert self.engine._to_urgency(-0.8) == "HIGH"

    def test_to_urgency_low(self):
        assert self.engine._to_urgency(0.2) == "LOW"

    def test_detect_cycle_phase_easing(self):
        assert self.engine._detect_cycle_phase("央行宣布降准降息") == "宽松"

    def test_detect_cycle_phase_tightening(self):
        assert self.engine._detect_cycle_phase("监管部门加强风险防范去杠杆") == "收紧"

    def test_detect_cycle_phase_structural(self):
        assert self.engine._detect_cycle_phase("精准滴灌定向降准支持小微企业") == "结构性"

    def test_detect_cycle_phase_neutral(self):
        assert self.engine._detect_cycle_phase("经济平稳运行") == "中性"

    def test_policy_queries_complete(self):
        assert "政治局会议" in POLICY_QUERIES
        assert "国常会" in POLICY_QUERIES
        assert "央行货币政策报告" in POLICY_QUERIES
        assert len(POLICY_QUERIES) >= 3

    def test_cache_operations(self):
        a = PolicyAnalysis(source="test", sentiment_score=0.5)
        self.engine._cache_set("test_key", a)
        assert self.engine._cache_get("test_key") is not None
        self.engine.cache_clear()
        assert self.engine._cache_get("test_key") is None
