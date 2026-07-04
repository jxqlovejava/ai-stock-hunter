"""多源采集管道 — 统一采集接口 + 去重 + 时间对齐 + 信源标注。

设计原则：
- 所有信源通过统一的 InformationSource 接口接入
- 并行采集（asyncio.gather），独立超时
- 去重基于 (title + platform) 的标准化哈希
- 每个条目标注信源可信度权重

Ref: OpenStock adanos.actions.ts — Promise.all 并行获取 4 源
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.information.schema import ProcessedItem, RawItem, SentimentResult, Topic
from src.information.sources.base import InformationSource

if TYPE_CHECKING:
    from collections.abc import Sequence


class CollectionResult:
    """一次采集操作的结果。"""

    def __init__(self) -> None:
        self.raw_items: list[RawItem] = []
        self.sentiment_results: list[SentimentResult] = []
        self.errors: list[tuple[str, str]] = []  # (source_name, error_message)
        self.timing_ms: dict[str, float] = {}  # source_name → elapsed_ms
        self.total_items_before_dedup: int = 0


class MultiSourceCollector:
    """多源采集器。

    使用方式：
        collector = MultiSourceCollector([weibo_source, eastmoney_source])
        result = await collector.collect(topic, days_back=7)
        result = await collector.collect_with_sentiment(topic, days_back=7)
    """

    def __init__(self, sources: Sequence[InformationSource] | None = None) -> None:
        self._sources: dict[str, InformationSource] = {}
        if sources:
            for s in sources:
                self.add_source(s)

    def add_source(self, source: InformationSource) -> None:
        """注册信源。"""
        key = f"{source.meta.source_type.value}:{source.meta.platform}"
        self._sources[key] = source

    def remove_source(self, platform: str) -> None:
        """移除信源。"""
        keys_to_remove = [k for k in self._sources if platform in k]
        for k in keys_to_remove:
            del self._sources[k]

    @property
    def source_count(self) -> int:
        return len(self._sources)

    async def collect(
        self,
        topic: Topic,
        *,
        days_back: int = 7,
        sources: list[str] | None = None,
        timeout_per_source: float = 30.0,
    ) -> CollectionResult:
        """并行从所有（或指定）信源采集原始条目。

        Args:
            topic: 要搜索的主题
            days_back: 回看天数
            sources: 指定信源 key 列表，None = 全部
            timeout_per_source: 单信源超时秒数

        Returns:
            包含去重后原始条目和元数据的采集结果
        """
        result = CollectionResult()
        target_sources = self._resolve_sources(sources)

        if not target_sources:
            return result

        # 并行采集（Ref: OpenStock Promise.all 模式）
        async def _fetch_one(key: str, src: InformationSource) -> list[RawItem]:
            t0 = datetime.now()
            try:
                items = await asyncio.wait_for(
                    src.search(topic, days_back=days_back), timeout=timeout_per_source
                )
            except asyncio.TimeoutError:
                result.errors.append((key, "timeout"))
                return []
            except Exception as e:
                result.errors.append((key, str(e)))
                return []
            finally:
                result.timing_ms[key] = (datetime.now() - t0).total_seconds() * 1000
            return items

        tasks = {key: _fetch_one(key, src) for key, src in target_sources.items()}
        gathered = await asyncio.gather(*tasks.values())

        all_items: list[RawItem] = []
        for items in gathered:
            all_items.extend(items)

        result.total_items_before_dedup = len(all_items)
        result.raw_items = self._deduplicate(all_items)
        return result

    async def collect_with_sentiment(
        self,
        topic: Topic,
        *,
        days_back: int = 7,
        sources: list[str] | None = None,
    ) -> CollectionResult:
        """采集 + 情感分析一体化。

        先采集，再对每个信源的条目批量做情感分析。
        """
        result = await self.collect(topic, days_back=days_back, sources=sources)
        target_sources = self._resolve_sources(sources)

        # 按信源分组做情感分析
        items_by_source: dict[str, list[RawItem]] = {}
        for item in result.raw_items:
            key = f"{item.source_type.value}:{item.platform}"
            items_by_source.setdefault(key, []).append(item)

        async def _sentiment_one(key: str, items: list[RawItem]) -> SentimentResult | None:
            src = target_sources.get(key)
            if not src:
                return None
            try:
                return await src.get_sentiment(items)
            except Exception:
                return None

        sentiment_tasks = {
            key: _sentiment_one(key, items) for key, items in items_by_source.items()
        }
        sentiment_results = await asyncio.gather(*sentiment_tasks.values())

        for sr in sentiment_results:
            if sr is not None:
                result.sentiment_results.append(sr)

        return result

    # ── 内部方法 ───────────────────────────────────────────────────────────

    def _resolve_sources(
        self, sources: list[str] | None
    ) -> dict[str, InformationSource]:
        """解析要使用的信源。"""
        if sources is None:
            return dict(self._sources)
        return {k: v for k, v in self._sources.items() if k in sources or any(s in k for s in sources)}

    @staticmethod
    def _deduplicate(items: list[RawItem]) -> list[RawItem]:
        """基于 (标准化标题 + 平台) 的哈希去重。保留首次出现。"""
        seen: set[str] = set()
        unique: list[RawItem] = []
        for item in items:
            text = f"{_normalize(item.title)}|{item.platform}"
            h = hashlib.sha256(text.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(item)
        return unique


def _normalize(text: str) -> str:
    """标准化文本用于去重哈希。"""
    import re

    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    return t
