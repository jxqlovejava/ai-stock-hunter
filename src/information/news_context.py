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
# anysearch 催化剂通道配置
# ------------------------------------------------------------------
# 板块级催化剂（发射失利/火箭推迟/政策/产业链事件）标题常不含个股名称，
# 仅靠东财个股关键词过滤会整条漏掉。anysearch 全网搜索作补充通道。
ANYSEARCH_ENDPOINT = "https://api.anysearch.com/mcp"
ANYSEARCH_TIMEOUT = 25
CATALYST_MAX = 8
# anysearch freshness=week 实测不可靠（可能返回数月前结果），本地兜底时效窗口
CATALYST_FRESH_DAYS = 7
# 去重/截断魔数
_CATALYST_TITLE_DEDUP_LEN = 30
_CATALYST_CONTENT_LEN = 300

# 催化剂通道噪音标题 token（行情/工具页，非新闻催化剂）
_CATALYST_NOISE_TOKENS = (
    "行情", "走势", "股吧", "百科", "F10", "讨论区",
    "最新价格", "个股资讯", "年度报告", "K线",
)

# 常用板块 token → 板块搜索词 (best-effort 板块关键词层)。
# 个股名含左列 token 时，追加对应板块查询，补足"个股名称关键词白名单"盲区。
# 可移植启发式：个股名不匹配任何 token 则跳过板块查询，不影响个股查询。
_SECTOR_KEYWORD_HINTS = (
    ("卫星", "卫星 商业航天"),
    ("航天", "航天 军工"),
    ("银行", "银行 金融"),
    ("证券", "券商 金融"),
    ("保险", "保险 金融"),
    ("医药", "医药 医疗"),
    ("半导体", "半导体 芯片"),
    ("芯片", "芯片 半导体"),
    ("软件", "软件 信创"),
    ("汽车", "汽车 新能源"),
    ("白酒", "白酒 食品饮料"),
    ("电力", "电力 绿电"),
    ("煤炭", "煤炭 能源"),
    ("地产", "地产 房地产"),
    ("军工", "军工 国防"),
    ("机器人", "机器人 智能制造"),
    ("光伏", "光伏 新能源"),
    ("锂", "锂电 新能源"),
    ("算力", "算力 AI"),
)


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

    # 板块催化剂资讯 (anysearch 全网搜索补充, 补个股关键词盲区)
    catalyst_news: list[NewsItem] = field(default_factory=list)

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
            + len(self.catalyst_news)
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
        if self.catalyst_news:
            parts.append(f"催化剂{len(self.catalyst_news)}")
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
            "catalyst_news": lambda: self._fetch_catalyst_channel(symbol, name),
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
            + len(ctx.catalyst_news)
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

            # 如果个股关键词没命中，返回最新 5 条通用快讯作为市场背景。
            # 注意：不扩大到"稀疏命中"场景——通用快讯以不相关市场新闻为主，
            # 板块级催化剂由 anysearch 催化剂通道 (catalyst_news) 负责补充。
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

    def _fetch_catalyst_channel(self, symbol: str, name: str) -> list[NewsItem]:
        """板块催化剂资讯通道 (anysearch 全网搜索)。

        补足 7×24 快讯 / 东财个股新闻的「个股名称关键词白名单」盲区——
        板块级催化剂（发射失利/火箭推迟/政策/产业链事件）标题常不含个股名称，
        仅靠个股关键词过滤会整条漏掉。anysearch 覆盖新华社/新浪/凤凰/163/东财
        等更广信源，按 freshness=week 拉取近期资讯作补充。

        失败静默降级返回 []，不影响其他通道。
        """
        try:
            queries = self._build_catalyst_queries(symbol, name)
            if not queries:
                return []
            raw_items = _anysearch_batch_search(queries)
            # anysearch freshness 不可靠，本地按 URL/正文日期剔除过期条目
            cutoff = (datetime.now() - timedelta(days=CATALYST_FRESH_DAYS)).strftime("%Y-%m-%d")
            items: list[NewsItem] = []
            seen: set[str] = set()
            for r in raw_items:
                title = (r.get("title") or "").strip()
                if not title or title[: _CATALYST_TITLE_DEDUP_LEN] in seen:
                    continue
                # 过滤行情/工具页噪音（如 中财网行情/同花顺F10/股吧）
                if any(tok in title for tok in _CATALYST_NOISE_TOKENS):
                    continue
                date = _extract_item_date(f"{r.get('url', '')} {r.get('content', '')}")
                if date and date < cutoff:
                    continue  # 已确认过期，剔除
                seen.add(title[: _CATALYST_TITLE_DEDUP_LEN])
                items.append(NewsItem(
                    title=title,
                    source="anysearch",
                    date=date,
                    content=(r.get("content") or "")[:_CATALYST_CONTENT_LEN],
                    url=r.get("url", ""),
                    provider="anysearch",
                ))
                if len(items) >= CATALYST_MAX:
                    break
            return items
        except Exception as e:
            logger.warning("catalyst 通道异常 %s: %s", symbol, e)
            return []

    def _build_catalyst_queries(self, symbol: str, name: str) -> list[str]:
        """构造催化剂搜索查询。

        策略: 异动原因（双向） + 个股板块消息 + 板块关键词层。
        - "大跌/涨停 原因" 类查询能带回解释板块/个股异动的文章（会点名催化
          事件，如中星4B 发射失利、火箭推迟），比纯板块词更能兜住催化剂
        - 个股"板块 消息"补足东财个股关键词过滤的盲区
        - _SECTOR_KEYWORD_HINTS 板块关键词层: 个股名含已知板块 token 时追加
          板块级查询（如 中国卫星 → "卫星 商业航天 板块 消息"）
        注: 不做东财 f127 行业探测——东财接口在本环境不可靠，且重试耗时。
        """
        queries: list[str] = []
        if name:
            queries.append(f"{name} 大跌 原因")
            queries.append(f"{name} 涨停 原因")
            queries.append(f"{name} 板块 消息")
            sector = _find_sector_keyword(name)
            if sector:
                queries.append(f"{sector} 板块 消息")
        else:
            queries.append(f"{symbol} 大跌 原因")
        return queries

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


# ------------------------------------------------------------------
# anysearch batch_search API 客户端
# ------------------------------------------------------------------


def _anysearch_batch_search(queries: list[str], max_results: int = 5) -> list[dict]:
    """调用 anysearch batch_search API (JSON-RPC 2.0)。

    Args:
        queries: 查询词列表 (≤5)
        max_results: 每条查询返回条数 (1-100)

    Returns:
        [{title, url, content, date}, ...]；失败/无结果返回 []。
    """
    import os

    import requests

    if not queries:
        return []
    api_key = os.environ.get("ANYSEARCH_API_KEY", "")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "batch_search",
            "arguments": {
                "queries": [
                    {
                        "query": q,
                        "content_types": ["news"],
                        "freshness": "week",
                        "max_results": max_results,
                        "zone": "cn",
                    }
                    for q in queries[:5]
                ]
            },
        },
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.post(
            ANYSEARCH_ENDPOINT, json=payload, headers=headers, timeout=ANYSEARCH_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.debug("anysearch API error: %s", data["error"])
            return []
        text = ""
        for item in data.get("result", {}).get("content", []):
            if item.get("type") == "text":
                text += item.get("text", "")
        return _parse_anysearch_markdown(text)
    except Exception as e:
        logger.debug("anysearch 调用失败: %s", e)
        return []


def _parse_anysearch_markdown(text: str) -> list[dict]:
    """解析 anysearch 搜索结果 markdown → [{title, url, content, date}]。

    服务端格式:
        ## Search Results (N results, Xms)
        ### 1. 标题
        - **URL**: https://...
        - 摘要/正文...
    """
    import re

    items: list[dict] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if line.startswith("### "):
            title = re.sub(r"^\d+\.\s*", "", line[4:].strip())
            url = ""
            content: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("### "):
                l = lines[i].strip()
                m = re.match(r"-\s*\*\*URL\*\*:\s*(\S+)", l)
                if m:
                    url = m.group(1)
                elif l and not l.startswith("## "):
                    content.append(l)
                i += 1
            if title:
                items.append({
                    "title": title,
                    "url": url,
                    "content": " ".join(content)[:_CATALYST_CONTENT_LEN],
                    "date": "",
                })
        else:
            i += 1
    return items


def _find_sector_keyword(name: str) -> str:
    """从个股名匹配常用板块 token，返回板块搜索词。

    best-effort: 无匹配返回 ""（跳过板块级查询），不阻塞个股查询。
    """
    for token, keyword in _SECTOR_KEYWORD_HINTS:
        if token in name:
            return keyword
    return ""


def _extract_item_date(text: str) -> str:
    """从 URL/正文提取 YYYY-MM-DD 日期，失败返回 ''。

    供催化剂通道本地时效过滤（anysearch freshness 不可靠）。
    """
    import re

    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    # 无分隔符: 20260810 (常见于东财 URL /a/202607133804226284.html)
    # 8 位窗口逐个试，校验月/日合法性，避免把长数字串误判为日期
    for m in re.finditer(r"(20\d{2})(\d{2})(\d{2})", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""
