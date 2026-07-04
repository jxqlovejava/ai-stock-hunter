"""信源适配器抽象基类。

Ref: .references/daily_stock_analysis/data_provider/ — DataProvider ABC 模式
每个信息平台（微博/知乎/财联社/华泰研报等）实现此 ABC。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.information.schema import ProcessedItem, RawItem, SentimentResult, SourceType, Topic


@dataclass
class SourceMeta:
    """信源元数据（声明式配置）。"""

    source_type: SourceType
    platform: str  # "weibo" / "zhihu" / "eastmoney" / "huatai_research"
    label: str  # 人类可读名称
    description: str = ""
    requires_auth: bool = False
    rate_limit_per_minute: int = 30
    default_days_back: int = 7
    max_days_back: int = 90
    credibility: float = 0.5  # 默认可信度（子类可覆盖）
    enabled: bool = True


class InformationSource(ABC):
    """信源适配器抽象基类。

    每个信息平台实现此 ABC，提供：
    1. search() — 按主题搜索原始条目
    2. get_sentiment() — 对条目做情感分析
    3. estimate_credibility() — 估算信源可信度

    使用方式：
        source = WeiboSource()
        items = await source.search(topic, days_back=7)
        sentiment = await source.get_sentiment(items)
    """

    meta: SourceMeta

    def __init__(self) -> None:
        self._validate_meta()

    def _validate_meta(self) -> None:
        """确保子类定义了 meta。"""
        if not hasattr(self, "meta") or not isinstance(self.meta, SourceMeta):
            raise TypeError(
                f"{self.__class__.__name__} must define 'meta: SourceMeta' class attribute"
            )

    @abstractmethod
    async def search(self, topic: Topic, days_back: int | None = None) -> list[RawItem]:
        """搜索与主题相关的原始条目。

        Args:
            topic: 要搜索的主题
            days_back: 回看天数，默认使用 meta.default_days_back

        Returns:
            原始条目列表（可能为空）
        """
        ...

    @abstractmethod
    async def get_sentiment(self, items: list[RawItem]) -> SentimentResult:
        """对条目做情感分析。

        实现方式可以是：
        - 调用 LLM（Claude）做情感分类
        - 使用平台自带的情感标签
        - 关键词规则匹配

        Args:
            items: 原始条目列表

        Returns:
            批量情感分析结果
        """
        ...

    def estimate_credibility(self, item: RawItem) -> float:
        """估算单条信息的可信度。

        默认基于信源类型。子类可根据作者认证、历史准确率等覆盖。

        Args:
            item: 原始条目

        Returns:
            可信度评分 0-1
        """
        return self.meta.credibility

    def filter_by_relevance(
        self, items: list[RawItem], topic: Topic, min_score: float = 0.3
    ) -> list[RawItem]:
        """基于关键词匹配过滤相关条目。

        默认使用简单关键词匹配。子类可用语义相似度覆盖。
        """
        keywords_lower = [k.lower() for k in topic.keywords]
        if not keywords_lower:
            return items

        relevant: list[RawItem] = []
        for item in items:
            text = f"{item.title} {item.content}".lower()
            score = sum(1 for kw in keywords_lower if kw in text) / max(
                len(keywords_lower), 1
            )
            if score >= min_score:
                relevant.append(item)
        return relevant

    def build_raw_item(
        self,
        title: str,
        content: str = "",
        url: str | None = None,
        author: str | None = None,
        published_at: str | None = None,
        metadata: dict | None = None,
    ) -> RawItem:
        """快捷构建 RawItem 的工具方法。"""
        from datetime import datetime

        return RawItem(
            source_type=self.meta.source_type,
            platform=self.meta.platform,
            title=title,
            content=content,
            url=url,
            author=author,
            published_at=datetime.fromisoformat(published_at) if published_at else None,
            metadata=metadata or {},
            credibility_score=self.meta.credibility,
        )
