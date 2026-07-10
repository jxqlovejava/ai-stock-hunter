# -*- coding: utf-8 -*-
"""统一资讯上下文获取器。

并行拉取多通道资讯数据：
  - 个股新闻 (mx-search → 东财个股新闻 → 东财 7×24 快讯)
  - 公告 (mx-search → 巨潮 cninfo)
  - 研报 (mx-search → 东财 reportapi)
  - 7×24 全球快讯 (东财 np-weblist，独立通道)
  - 快查问财 (kuaicha iwencai)
  - 最近 30 日新闻 (last30days)

所有通道并行拉取，互不阻塞。单个通道失败不影响其他通道。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.data.schema import NewsItem

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Dataclass
# ------------------------------------------------------------------


@dataclass
class NewsContext:
    """多通道资讯上下文。"""

    symbol: str = ""
    name: str = ""

    # 个股新闻
    news: list[NewsItem] = field(default_factory=list)

    # 公告
    announcements: list[NewsItem] = field(default_factory=list)

    # 研报
    research_reports: list[NewsItem] = field(default_factory=list)

    # 7×24 全球快讯 (已按个股/行业关键词过滤)
    flash_24x7: list[NewsItem] = field(default_factory=list)

    # 快查问财结果
    kuaicha_news: list[NewsItem] = field(default_factory=list)

    # 最近 30 日综合新闻
    last30days: list[NewsItem] = field(default_factory=list)

    # 元信息
    fetched_at: str = ""
    errors: list[str] = field(default_factory=list)
    total_items: int = 0

    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now().isoformat()
        self.total_items = (
            len(self.news)
            + len(self.announcements)
            + len(self.research_reports)
            + len(self.flash_24x7)
            + len(self.kuaicha_news)
            + len(self.last30days)
        )

    @property
    def has_any(self) -> bool:
        return self.total_items > 0

    @property
    def summary(self) -> str:
        """单行摘要。"""
        parts = []
        if self.news:
            parts.append(f"新闻{len(self.news)}")
        if self.announcements:
            parts.append(f"公告{len(self.announcements)}")
        if self.research_reports:
            parts.append(f"研报{len(self.research_reports)}")
        if self.flash_24x7:
            parts.append(f"7×24{len(self.flash_24x7)}")
        if self.kuaicha_news:
            parts.append(f"快查{len(self.kuaicha_news)}")
        if self.last30days:
            parts.append(f"30日{len(self.last30days)}")
        if not parts:
            return "无资讯"
        return " | ".join(parts)


# ------------------------------------------------------------------
# Fetcher
# ------------------------------------------------------------------


class NewsContextFetcher:
    """统一资讯上下文获取器。

    用法:
        fetcher = NewsContextFetcher()
        ctx = fetcher.fetch("003009", "中天火箭")
        print(ctx.summary)  # 新闻5 | 公告3 | 研报2 | 7×24 8
    """

    # 7×24 快讯最大条数 (拉取后按关键词过滤)
    FLASH_MAX = 80

    # 各通道最大返回条数
    NEWS_MAX = 15
    ANNOUNCEMENT_MAX = 10
    RESEARCH_MAX = 5
    LAST30DAYS_MAX = 20
    KUAICHA_MAX = 5

    def __init__(self):
        self._agg = None

    @property
    def agg(self):
        """懒加载 DataAggregator。"""
        if self._agg is None:
            from src.data.aggregator import DataAggregator
            self._agg = DataAggregator()
        return self._agg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, symbol: str, name: str = "") -> NewsContext:
        """并行拉取所有资讯通道。

        Args:
            symbol: 6 位股票代码
            name: 股票名称 (用于构造搜索关键词)

        Returns:
            NewsContext: 所有通道结果
        """
        ctx = NewsContext(symbol=symbol, name=name)

        # 构建各通道任务
        tasks = {
            "news": lambda: self._fetch_news_channel(symbol, name),
            "announcements": lambda: self._fetch_announcements_channel(symbol),
            "research_reports": lambda: self._fetch_research_channel(symbol),
            "flash_24x7": lambda: self._fetch_flash_channel(symbol, name),
            "kuaicha_news": lambda: self._fetch_kuaicha_channel(name, symbol),
            "last30days": lambda: self._fetch_last30days_channel(symbol, name),
        }

        # 并行执行
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    setattr(ctx, key, result)
                except Exception as e:
                    err_msg = f"{key} 通道失败: {e}"
                    logger.debug(err_msg)
                    ctx.errors.append(err_msg)

        ctx.total_items = (
            len(ctx.news)
            + len(ctx.announcements)
            + len(ctx.research_reports)
            + len(ctx.flash_24x7)
            + len(ctx.kuaicha_news)
            + len(ctx.last30days)
        )

        return ctx

    # ------------------------------------------------------------------
    # Channel implementations
    # ------------------------------------------------------------------

    def _fetch_news_channel(self, symbol: str, name: str) -> list[NewsItem]:
        """个股新闻通道。

        降级链: mx-search → 东财个股新闻 → 东财 7×24 快讯
        """
        query = f"{name} {symbol}" if name else symbol
        try:
            return self.agg.search_news(query, max_results=self.NEWS_MAX)
        except Exception as e:
            logger.debug("个股新闻通道异常: %s", e)
            return []

    def _fetch_announcements_channel(self, symbol: str) -> list[NewsItem]:
        """公告通道。

        降级链: mx-search → 巨潮 cninfo
        """
        try:
            items = self.agg.search_announcements(symbol)
            return items[: self.ANNOUNCEMENT_MAX] if items else []
        except Exception as e:
            logger.debug("公告通道异常: %s", e)
            return []

    def _fetch_research_channel(self, symbol: str) -> list[NewsItem]:
        """研报通道。

        降级链: mx-search → 东财 reportapi
        """
        try:
            items = self.agg.search_research_reports(symbol)
            return items[: self.RESEARCH_MAX] if items else []
        except Exception as e:
            logger.debug("研报通道异常: %s", e)
            return []

    def _fetch_flash_channel(self, symbol: str, name: str) -> list[NewsItem]:
        """7×24 快讯通道 (东财 np-weblist 零鉴权)。

        拉取最新快讯，按个股名称/代码关键词过滤。
        """
        try:
            from src.data.eastmoney_fallback import fetch_em_global_news

            raw = fetch_em_global_news(page_size=self.FLASH_MAX)
            if not raw:
                return []

            # 关键词过滤：股票名称 + 股票代码
            keywords = [symbol]
            if name:
                keywords.append(name)

            items = []
            for entry in raw:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = f"{title} {summary}"

                if any(kw in text for kw in keywords):
                    items.append(NewsItem(
                        title=title,
                        source=entry.get("source", "eastmoney-global"),
                        date=entry.get("time", ""),
                        content=summary[:500],
                        url=entry.get("url", ""),
                        provider="eastmoney-global",
                    ))
                    if len(items) >= 20:
                        break

            # 如果个股关键词没命中，返回最新 5 条通用快讯作为市场背景
            if not items:
                for entry in raw[:5]:
                    items.append(NewsItem(
                        title=entry.get("title", ""),
                        source=entry.get("source", "eastmoney-global"),
                        date=entry.get("time", ""),
                        content=entry.get("summary", "")[:500],
                        url=entry.get("url", ""),
                        provider="eastmoney-global",
                    ))

            return items
        except Exception as e:
            logger.debug("7×24 快讯通道异常: %s", e)
            return []

    def _fetch_kuaicha_channel(self, name: str, symbol: str) -> list[NewsItem]:
        """快查问财通道 (kuaicha CLI)。

        使用 iwencai 自然语言查询获取 AI 摘要。
        """
        try:
            kc = self.agg.kuaicha
            if kc is None or not kc.health_check():
                return []

            query = f"{name} 最新新闻 公告 研报"
            result = kc.iwencai("astock_finance", query, limit=self.KUAICHA_MAX)
            if result is None or not result.raw_data:
                return []

            items = []
            for row in result.raw_data[: self.KUAICHA_MAX]:
                if not isinstance(row, dict):
                    continue
                # 问财返回的字段可能是股票代码/名称/最新价/涨跌幅等
                parts = []
                for k, v in row.items():
                    if v is not None and str(v).strip():
                        parts.append(f"{k}: {v}")
                content = "; ".join(parts[:8])
                items.append(NewsItem(
                    title=f"问财: {name}({symbol})",
                    source="kuaicha-iwencai",
                    date=datetime.now().strftime("%Y-%m-%d"),
                    content=content[:500],
                    url="",
                    provider="kuaicha",
                ))
            return items
        except Exception as e:
            logger.debug("快查通道异常: %s", e)
            return []

    def _fetch_last30days_channel(self, symbol: str, name: str) -> list[NewsItem]:
        """最近 30 日新闻通道。

        使用东财个股新闻 + 百度新闻搜索获取近期资讯。
        降级链: 东财搜索 → 空
        """
        items: list[NewsItem] = []
        today = datetime.now()
        cutoff = today - timedelta(days=30)

        try:
            from src.data.eastmoney_fallback import fetch_em_stock_news

            # 东财个股新闻 (一次拉取较多条数，用时间过滤)
            query = f"{name} {symbol}" if name else symbol
            raw = fetch_em_stock_news(query, max_results=self.LAST30DAYS_MAX * 2)

            for entry in raw:
                title = entry.get("title", "")
                content = entry.get("content", "")
                source = entry.get("source", "eastmoney-news")
                date_str = entry.get("time", "")
                url = entry.get("url", "")

                # 尝试解析日期并过滤 30 天内
                item_date = self._parse_date(date_str)
                if item_date and item_date < cutoff:
                    continue

                items.append(NewsItem(
                    title=title,
                    source=source,
                    date=date_str,
                    content=content[:500],
                    url=url,
                    provider="eastmoney-news",
                ))

                if len(items) >= self.LAST30DAYS_MAX:
                    break

        except Exception as e:
            logger.debug("last30days 东财通道异常: %s", e)

        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """尝试解析日期字符串。"""
        if not date_str:
            return None
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d",
            "%m-%d %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str[: len("YYYY-MM-DD HH:MM:SS")], fmt)
            except (ValueError, IndexError):
                continue
        return None


# ------------------------------------------------------------------
# Convenience
# ------------------------------------------------------------------


def fetch_news_context(symbol: str, name: str = "") -> NewsContext:
    """便捷函数：拉取完整资讯上下文。"""
    fetcher = NewsContextFetcher()
    return fetcher.fetch(symbol, name)
