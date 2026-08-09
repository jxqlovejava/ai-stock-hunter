# -*- coding: utf-8 -*-
"""股吧情绪预取注入 (防 LLM 编造) 测试。"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

from src.data.guba_provider import GubaSentiment
from src.information.guba_sentiment_llm import (
    GubaSentimentLLMAnalyzer,
    _render_extra_block,
    _render_guba_block,
)


def _fake_guba(symbol: str = "600519") -> GubaSentiment:
    return GubaSentiment(
        symbol=symbol,
        post_count=12,
        hot_titles=["业绩超预期，明天高开？", "主力开始吸筹了", "看看这股能不能翻倍"],
        total_clicks=12000,
        total_comments=800,
        engagement_per_post=500.0,
        posts_last_6h=10,
        bullish_count=8,
        bearish_count=3,
        posts_last_hour=5,
        posts_last_24h=12,
    )


class TestRenderBlocks:
    def test_guba_block_contains_titles_and_counts(self):
        block = _render_guba_block(_fake_guba())
        assert "帖子数: 12" in block
        assert "看多 8 / 看空 3" in block
        assert "业绩超预期" in block
        assert "<start_of_guba>" not in block  # 标记由 prompt 层加

    def test_extra_block_formats_items(self):
        items = [
            {"title": "微博热帖", "content": "这个票要起飞", "sentiment_tag": "Bullish"},
            {"title": "另一条", "engagement": 999},
        ]
        block = _render_extra_block(items)
        assert "微博热帖" in block
        assert "[标签:Bullish]" in block
        assert "互动:999" in block

    def test_extra_block_empty(self):
        assert "(无外部社交条目)" in _render_extra_block([])


class TestAnalyze:
    def test_success_returns_dto(self):
        analyzer = GubaSentimentLLMAnalyzer(guba_provider=mock.Mock(spec=["fetch_sentiment"]))
        analyzer._guba.fetch_sentiment.return_value = _fake_guba()
        with mock.patch(
            "src.information.guba_sentiment_llm.invoke_structured_or_freetext",
            return_value={
                "overall_band": "Mildly Bullish",
                "overall_score": 6.5,
                "confidence": 0.6,
                "narrative": "股吧看多标题居多，互动热度中等。",
            },
        ) as invoke:
            result = analyzer.analyze("600519")

        invoke.assert_called_once()
        # prompt 必须含预取块与"禁止编造"约束
        prompt = invoke.call_args.args[0]
        assert "<start_of_guba>" in prompt
        assert "<end_of_guba>" in prompt
        assert "禁止编造" in invoke.call_args.kwargs["system"]
        assert result.is_gap() is False
        assert result.overall_band == "Mildly Bullish"
        assert result.confidence == 0.6
        assert result.citation is not None  # 溯源三要素
        assert result.source == "guba_llm"

    def test_confidence_clamped_to_unit_interval(self):
        analyzer = GubaSentimentLLMAnalyzer(guba_provider=mock.Mock(spec=["fetch_sentiment"]))
        analyzer._guba.fetch_sentiment.return_value = _fake_guba()
        with mock.patch(
            "src.information.guba_sentiment_llm.invoke_structured_or_freetext",
            return_value={"overall_band": "Bullish", "overall_score": 8.0, "confidence": 1.5, "narrative": "x"},
        ):
            result = analyzer.analyze("600519")
        assert result.confidence == 1.0

    def test_llm_fallback_returns_data_gap(self):
        analyzer = GubaSentimentLLMAnalyzer(guba_provider=mock.Mock(spec=["fetch_sentiment"]))
        analyzer._guba.fetch_sentiment.return_value = _fake_guba()
        with mock.patch(
            "src.information.guba_sentiment_llm.invoke_structured_or_freetext",
            return_value="纯文本降级结果",
        ):
            result = analyzer.analyze("600519")
        assert result.is_gap() is True
        assert result.fallback_text != ""

    def test_no_guba_no_extra_returns_data_gap(self):
        analyzer = GubaSentimentLLMAnalyzer(guba_provider=mock.Mock(spec=["fetch_sentiment"]))
        analyzer._guba.fetch_sentiment.return_value = None
        with mock.patch("src.information.guba_sentiment_llm.invoke_structured_or_freetext") as invoke:
            result = analyzer.analyze("600519")
        invoke.assert_not_called()  # 无数据不调 LLM
        assert result.is_gap() is True

    def test_guba_missing_but_weibo_present_still_analyzes(self):
        analyzer = GubaSentimentLLMAnalyzer(guba_provider=mock.Mock(spec=["fetch_sentiment"]))
        analyzer._guba.fetch_sentiment.return_value = None
        with mock.patch(
            "src.information.guba_sentiment_llm.invoke_structured_or_freetext",
            return_value={
                "overall_band": "Bullish",
                "overall_score": 7.0,
                "confidence": 0.7,
                "narrative": "微博讨论偏多。",
            },
        ):
            result = analyzer.analyze("600519", extra_sources=[{"title": "微博帖子"}])
        assert result.is_gap() is False
        assert result.overall_score == 7.0
