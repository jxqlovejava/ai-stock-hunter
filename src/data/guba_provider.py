# -*- coding: utf-8 -*-
"""东财股吧 (guba.eastmoney.com) 情绪信源。

直接解析股吧列表页内嵌的 `var article_list` JSON，提取：
  - 热帖列表（标题 / 发布时间 / 点击量 / 评论数 / 转发数）
  - 讨论热度指标（帖子数 / 点击量 / 评论数）
  - 多空标记（bullish_bearish）

Tier: T1（东财官方论坛，数据结构化程度高，置信度 0.80）
数据性质: 帖子计数 = fact / 情绪解读 = interpretation

Usage:
    provider = GubaProvider()
    sentiment = provider.fetch_sentiment("600519")
    # → GubaSentiment(post_count, hot_titles, total_clicks, ...)
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .source_citation import (
    NATURE_FACT,
    NATURE_INTERPRETATION,
    SOURCE_TIER_T1,
    SourceCitation,
    make_citation,
)

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
GUBA_LIST_URL = "https://guba.eastmoney.com/list,{code}.html"
EM_MIN_INTERVAL = 1.0  # 秒

_session: Optional[requests.Session] = None
_last_call: float = 0.0


def _get_session() -> requests.Session:
    """获取或创建复用的 requests.Session（绕过系统代理，直连东财）。"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
        _session.headers.update({"User-Agent": UA})
        try:
            _session.mount(
                "https://",
                HTTPAdapter(
                    max_retries=Retry(
                        total=3,
                        connect=3,
                        backoff_factor=0.6,
                        status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=["GET"],
                    )
                ),
            )
            _session.mount(
                "http://",
                HTTPAdapter(
                    max_retries=Retry(
                        total=2,
                        connect=2,
                        backoff_factor=0.5,
                        status_forcelist=[500, 502, 503],
                        allowed_methods=["GET"],
                    )
                ),
            )
        except Exception:
            pass
    return _session


def _throttle() -> None:
    """请求节流：最小间隔 1.0s + 随机抖动。"""
    global _last_call
    wait = EM_MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    _last_call = time.time()


# ── DTO ──────────────────────────────────────────────────────────────────


@dataclass
class GubaPost:
    """单条股吧帖子。"""

    post_id: int
    title: str
    user_nickname: str
    click_count: int
    comment_count: int
    forward_count: int
    publish_time: datetime
    bullish_bearish: int  # 0=未标记, 1=看多, 2=看空
    has_pic: bool = False
    is_top: bool = False

    @property
    def engagement_score(self) -> int:
        """互动热度 = 点击 + 评论×10 + 转发×5。"""
        return self.click_count + self.comment_count * 10 + self.forward_count * 5


@dataclass
class GubaSentiment:
    """股吧情绪快照。"""

    symbol: str
    post_count: int  # 首页帖子数
    hot_titles: list[str] = field(default_factory=list)  # Top 10 热帖标题
    total_clicks: int = 0  # 首页总点击量
    total_comments: int = 0  # 首页总评论数
    engagement_per_post: float = 0.0  # 帖均互动热度
    # 发布时间分布
    posts_last_hour: int = 0
    posts_last_6h: int = 0
    posts_last_24h: int = 0
    # 多空比
    bullish_count: int = 0
    bearish_count: int = 0
    # 溯源
    citation: Optional[SourceCitation] = None

    @property
    def bull_bear_ratio(self) -> float | None:
        """多空比。>1 = 偏多，<1 = 偏空。无标记时返回 None。"""
        total = self.bullish_count + self.bearish_count
        if total == 0:
            return None
        return self.bullish_count / total

    @property
    def heat_score(self) -> float:
        """归一化热度分 (0-100)，基于帖均互动 + 帖子密度。"""
        density = min(1.0, self.posts_last_6h / 30.0)
        engagement = min(1.0, self.engagement_per_post / 5000.0)
        return round((density * 0.3 + engagement * 0.7) * 100, 1)


# ── Provider ─────────────────────────────────────────────────────────────


class GubaProvider:
    """东财股吧情绪数据提供者。

    直接从股吧列表页提取结构化数据（无 API Key 依赖）。
    """

    source_name: str = "guba"

    def fetch_sentiment(
        self,
        symbol: str,
        page: int = 1,
    ) -> Optional[GubaSentiment]:
        """获取指定股票股吧情绪数据。

        Args:
            symbol: 6 位股票代码（如 "600519"）
            page: 页码（默认第 1 页，85 条/页）

        Returns:
            GubaSentiment，失败返回 None
        """
        code = symbol.zfill(6)
        try:
            raw_posts = self._fetch_raw_posts(code, page)
            if raw_posts is None:
                return None
            return self._parse_sentiment(symbol, raw_posts)
        except Exception:
            logger.warning("guba fetch failed for %s", symbol, exc_info=True)
            return None

    def fetch_sentiments_batch(
        self,
        symbols: list[str],
        page: int = 1,
        max_workers: int = 6,
    ) -> dict[str, Optional[GubaSentiment]]:
        """批量获取多只股票股吧情绪数据。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[str, Optional[GubaSentiment]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch_sentiment, s, page): s
                for s in symbols
            }
            for future in as_completed(futures):
                s = futures[future]
                try:
                    results[s] = future.result(timeout=20)
                except Exception:
                    logger.warning("guba batch fetch timeout for %s", s)
                    results[s] = None
        return results

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _fetch_raw_posts(self, code: str, page: int = 1) -> list[dict] | None:
        """请求股吧列表页，解析内嵌 JSON。

        Returns:
            [{post_id, post_title, post_click_count, ...}, ...]，失败返回 None
        """
        url = GUBA_LIST_URL.format(code=code)
        if page > 1:
            url = f"https://guba.eastmoney.com/list,{code}_{page}.html"

        _throttle()
        try:
            resp = _get_session().get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("guba HTTP request failed for %s page %s", code, page)
            return None

        # 解析 var article_list = {...}
        try:
            m = re.search(r"var article_list=(\{.+?\});\s*var", resp.text, re.DOTALL)
            if not m:
                # 尝试更宽松的匹配
                m = re.search(r"var article_list=(\{.+)", resp.text, re.DOTALL)
            if not m:
                logger.warning("guba article_list not found for %s", code)
                return None
            json_str = m.group(1)
            data = json.loads(json_str)
            return list(data.get("re") or [])
        except (json.JSONDecodeError, AttributeError, KeyError):
            logger.warning("guba JSON parse failed for %s", code)
            return None

    def _parse_sentiment(
        self, symbol: str, raw_posts: list[dict]
    ) -> GubaSentiment:
        """将原始帖子列表转换为情绪快照。"""
        now = datetime.now()
        posts: list[GubaPost] = []
        hot_titles: list[str] = []
        total_clicks = 0
        total_comments = 0
        bullish_count = 0
        bearish_count = 0
        posts_last_hour = 0
        posts_last_6h = 0
        posts_last_24h = 0

        for raw in raw_posts:
            try:
                pub_time_str = raw.get("post_publish_time", "")
                pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d %H:%M:%S")

                post = GubaPost(
                    post_id=int(raw.get("post_id", 0)),
                    title=raw.get("post_title", ""),
                    user_nickname=raw.get("user_nickname", ""),
                    click_count=int(raw.get("post_click_count", 0)),
                    comment_count=int(raw.get("post_comment_count", 0)),
                    forward_count=int(raw.get("post_forward_count", 0)),
                    publish_time=pub_time,
                    bullish_bearish=int(raw.get("bullish_bearish", 0)),
                    has_pic=bool(raw.get("post_has_pic", False)),
                    is_top=int(raw.get("post_top_status", 0)) > 0,
                )
            except (ValueError, TypeError):
                continue

            posts.append(post)
            total_clicks += post.click_count
            total_comments += post.comment_count

            if post.bullish_bearish == 1:
                bullish_count += 1
            elif post.bullish_bearish == 2:
                bearish_count += 1

            age = (now - post.publish_time).total_seconds()
            if age <= 3600:
                posts_last_hour += 1
            if age <= 21600:
                posts_last_6h += 1
            if age <= 86400:
                posts_last_24h += 1

        # 按互动热度排序取 Top 10 热帖标题
        sorted_posts = sorted(posts, key=lambda p: p.engagement_score, reverse=True)
        hot_titles = [p.title for p in sorted_posts[:10]]

        post_count = len(posts)
        engagement_per_post = (
            round(sum(p.engagement_score for p in posts) / post_count, 1)
            if post_count > 0
            else 0.0
        )

        citation = make_citation(
            provider="guba",
            field="guba_sentiment",
            data_type="daily_bar",
            source_tier=SOURCE_TIER_T1,
            nature=NATURE_INTERPRETATION,
            url=GUBA_LIST_URL.format(code=symbol),
        )

        return GubaSentiment(
            symbol=symbol,
            post_count=post_count,
            hot_titles=hot_titles,
            total_clicks=total_clicks,
            total_comments=total_comments,
            engagement_per_post=engagement_per_post,
            posts_last_hour=posts_last_hour,
            posts_last_6h=posts_last_6h,
            posts_last_24h=posts_last_24h,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            citation=citation,
        )

    def health_check(self) -> bool:
        """快速连通性检查。"""
        try:
            _throttle()
            resp = _get_session().get(
                GUBA_LIST_URL.format(code="600519"), timeout=10
            )
            return resp.status_code == 200 and "article_list" in resp.text
        except Exception:
            return False
