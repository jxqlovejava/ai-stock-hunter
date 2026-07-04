"""机构研报适配器 — 华泰/国信 skill 封装。

覆盖：华泰 diagnosisStock + marketInsight、国信结构化宏观/行业数据

设计说明：
    华泰 skill 返回 Markdown（黑盒 NLP），由 LLM 结构化提取。
    国信 skill 返回结构化 JSON，直接映射。

Ref: data-source-analysis.md — 3B.2/3B.3 节
"""

from __future__ import annotations

from src.information.schema import (
    EventCategory,
    ProcessedItem,
    RawItem,
    SentimentResult,
    SourceType,
    Topic,
)
from src.information.sources.base import InformationSource, SourceMeta


class HuataiResearchSource(InformationSource):
    """华泰证券研报适配器。

    独有能力：个股诊断 (diagnosisStock)、市场洞察 (marketInsight)。
    定位：AI 增强层（定性），不进入回测数据管道。

    Ref: 计划 3B.2 — diagnosisStock 结构化提取 (DiagnosisExtract)
    """

    meta = SourceMeta(
        source_type=SourceType.RESEARCH_REPORT,
        platform="huatai",
        label="华泰证券",
        description="个股诊断 + 市场洞察（AI 解读）",
        requires_auth=True,
        rate_limit_per_minute=5,
        default_days_back=7,
        max_days_back=90,
        credibility=0.8,  # 机构研报可信度高
    )

    async def search(self, topic: Topic, days_back: int | None = None) -> list[RawItem]:
        """通过华泰 skill 搜索。

        调用方式（由 Claude Code orchestrator 执行）：
            Skill(financial-analysis) → diagnosisStock(query=topic.keywords)
            Skill(financial-analysis) → marketInsight(query=topic.name)

        结构化提取（Phase 3）:
            LLM 将 diagnosisStock Markdown 输出提取为 DiagnosisExtract
        """
        return []

    async def get_sentiment(self, items: list[RawItem]) -> SentimentResult:
        """华泰研报情感分析。

        华泰研报本身已经是分析结论，情感抽取相对直接。
        默认偏向研报自身的情感判断。
        """
        if not items:
            return SentimentResult(
                source_type=self.meta.source_type,
                platform=self.meta.platform,
                items_count=0,
            )

        # 华泰研报通常直接表达观点，使用 metadata 中的预提取字段
        processed: list[ProcessedItem] = []
        bullish = bearish = neutral = 0
        scores: list[float] = []

        for item in items:
            # 尝试从 metadata 读取预计算的情感（由 orchestrator 在采集时预填）
            score = item.metadata.get("huatai_sentiment", 0.0)
            scores.append(score)
            if score > 0.2:
                bullish += 1
            elif score < -0.2:
                bearish += 1
            else:
                neutral += 1

            processed.append(
                ProcessedItem(
                    source_item=item,
                    sentiment_score=score,
                    sentiment_confidence=item.metadata.get("extraction_confidence", 0.7),
                    extracted_entities=item.metadata.get("stock_codes", []),
                    event_category=self._map_event(item.metadata.get("valuation_stance", "")),
                    keywords=item.metadata.get("risk_flags", []),
                    summary=item.metadata.get("diagnosis_summary", ""),
                )
            )

        n = len(scores)
        mean_score = sum(scores) / n if n else 0.0
        variance = sum((s - mean_score) ** 2 for s in scores) / n if n > 1 else 0.0

        return SentimentResult(
            source_type=self.meta.source_type,
            platform=self.meta.platform,
            items_count=n,
            sentiment_mean=round(mean_score, 3),
            sentiment_std=round(variance ** 0.5, 3),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            processed_items=processed,
        )

    @staticmethod
    def _map_event(valuation_stance: str) -> EventCategory:
        mapping = {
            "undervalued": EventCategory.POSITIVE_MEDIUM,
            "fair": EventCategory.NEUTRAL,
            "overvalued": EventCategory.NEGATIVE_MEDIUM,
        }
        return mapping.get(valuation_stance, EventCategory.NEUTRAL)


class GuosenResearchSource(InformationSource):
    """国信证券数据适配器。

    返回结构化 JSON（固定 schema），可直接映射。
    覆盖：行情、财务、宏观、选股、基金、ETF。
    """

    meta = SourceMeta(
        source_type=SourceType.RESEARCH_REPORT,
        platform="guosen",
        label="国信证券",
        description="结构化行情/财务/宏观数据",
        requires_auth=True,
        rate_limit_per_minute=10,
        default_days_back=7,
        max_days_back=365,
        credibility=0.85,  # 结构化数据可信度最高
    )

    async def search(self, topic: Topic, days_back: int | None = None) -> list[RawItem]:
        """通过国信 skill 搜索。

        调用方式（由 Claude Code orchestrator 执行）：
            Skill(gs-stock-market-query) — 实时行情/资金流向
            Skill(gs-stock-financial-query) — 财务报表
            Skill(gs-economy-query) — 宏观数据
            Skill(gs-smart-stock-picking) — 自然语言选股（≤100 只）
        """
        return []

    async def get_sentiment(self, items: list[RawItem]) -> SentimentResult:
        """国信数据情感分析。

        国信返回结构化数据，情感从数据中推导而非 NLP。
        """
        if not items:
            return SentimentResult(
                source_type=self.meta.source_type,
                platform=self.meta.platform,
                items_count=0,
            )

        processed: list[ProcessedItem] = []
        bullish = bearish = neutral = 0
        scores: list[float] = []

        for item in items:
            # 国信结构化数据的情感由 orchestrator 预填
            score = item.metadata.get("guosen_sentiment", 0.0)
            scores.append(score)
            if score > 0.1:
                bullish += 1
            elif score < -0.1:
                bearish += 1
            else:
                neutral += 1

            processed.append(
                ProcessedItem(
                    source_item=item,
                    sentiment_score=score,
                    sentiment_confidence=0.85,  # 结构化数据置信度高
                    extracted_entities=item.metadata.get("stock_codes", []),
                    event_category=EventCategory.NEUTRAL,
                    keywords=item.metadata.get("data_dimensions", []),
                )
            )

        n = len(scores)
        mean_score = sum(scores) / n if n else 0.0
        variance = sum((s - mean_score) ** 2 for s in scores) / n if n > 1 else 0.0

        return SentimentResult(
            source_type=self.meta.source_type,
            platform=self.meta.platform,
            items_count=n,
            sentiment_mean=round(mean_score, 3),
            sentiment_std=round(variance ** 0.5, 3),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            processed_items=processed,
        )
