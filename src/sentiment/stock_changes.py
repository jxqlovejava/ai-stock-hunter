# -*- coding: utf-8 -*-
"""盘中异动监控 — 封装东财 push2ex 异动 API。

借鉴 go-stock stock_changes_api.go，覆盖 22 种盘中异动类型，
分 bullish（看多）和 bearish（看空）两组，可作为情绪辅助信号。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 东财 API 直连 Session（绕过系统代理如 Clash，避免 ProxyError）
_EM_SESSION = requests.Session()
_EM_SESSION.trust_env = False
_EM_SESSION.proxies = {"http": None, "https": None}
_EM_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
})

# 东财异动 API
_EM_CHANGES_URL = "https://push2ex.eastmoney.com/getAllStockChanges"

# ── 异动类型映射（来自 go-stock changeTypeNames） ──────────────────────

BULLISH_CHANGE_TYPES: dict[int, str] = {
    8201: "火箭发射",
    8202: "快速反弹",
    8193: "大笔买入",
    4: "封涨停板",
    32: "打开跌停板",
    64: "有大买盘",
    8207: "竞价上涨",
    8209: "高开5日线",
    8211: "向上缺口",
    8213: "60日新高",
    8215: "60日大幅上涨",
}

BEARISH_CHANGE_TYPES: dict[int, str] = {
    8204: "加速下跌",
    8203: "高台跳水",
    8194: "大笔卖出",
    8: "封跌停板",
    16: "打开涨停板",
    128: "有大卖盘",
    8208: "竞价下跌",
    8210: "低开5日线",
    8212: "向下缺口",
    8214: "60日新低",
    8216: "60日大幅下跌",
}

ALL_CHANGE_TYPES: dict[int, str] = {**BULLISH_CHANGE_TYPES, **BEARISH_CHANGE_TYPES}


# ── 数据模型 ────────────────────────────────────────────────────────────


@dataclass
class StockChangeItem:
    """单条异动记录。"""
    time: str = ""              # 异动时间 HH:MM
    code: str = ""              # 股票代码
    name: str = ""              # 股票名称
    change_type: int = 0        # 异动类型编号
    type_name: str = ""         # 异动类型中文名
    price: float = 0.0          # 异动时价格
    change_pct: float = 0.0     # 涨跌幅%
    volume: int = 0             # 数量（手）
    amount: float = 0.0         # 金额（元）
    industry: str = ""          # 所属行业
    concept: str = ""           # 所属概念
    is_bullish: bool = True     # 是否看多异动


@dataclass
class StockChangesSnapshot:
    """盘中异动完整快照。"""
    changes: list[StockChangeItem] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    bullish_ratio: float = 0.5  # bullish / total
    total_count: int = 0
    source: str = ""
    error: Optional[str] = None
    # 异动分布
    top_bullish_stocks: list[str] = field(default_factory=list)   # 异动最多的看多标的
    top_bearish_stocks: list[str] = field(default_factory=list)   # 异动最多的看空标的
    # 用于情绪信号
    signal: str = "normal"      # bullish_bias / bearish_bias / normal
    description: str = ""


# ── 数据获取器 ──────────────────────────────────────────────────────────


class StockChangesFetcher:
    """东财盘中异动数据获取器。

    默认拉取所有 22 种异动类型，每页 80 条。
    在非交易时段 API 可能返回空数据（标记 [DATA_GAP]）。
    """

    _DEFAULT_PAGE_SIZE = 80
    _REQUEST_TIMEOUT = 10.0

    @staticmethod
    def fetch(
        change_types: Optional[list[int]] = None,
        page_index: int = 0,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> StockChangesSnapshot:
        """拉取盘中异动数据。

        Args:
            change_types: 异动类型列表，None=全部 22 种
            page_index: 页码（0-based）
            page_size: 每页条数

        Returns:
            StockChangesSnapshot，包含异动明细和汇总统计
        """
        if change_types is None:
            change_types = list(ALL_CHANGE_TYPES.keys())

        if not change_types:
            return StockChangesSnapshot(
                error="未指定异动类型", source="N/A"
            )

        type_str = ",".join(str(t) for t in change_types)
        url = (
            f"{_EM_CHANGES_URL}?type={type_str}"
            f"&ut=7eea3edcaed734bea9cbfc24409ed989"
            f"&pageindex={page_index}&pagesize={page_size}"
            f"&dpt=wzchanges&_={int(time.time() * 1000)}"
        )

        try:
            resp = _EM_SESSION.get(
                url,
                timeout=StockChangesFetcher._REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"获取异动数据失败: {e}")
            return StockChangesSnapshot(
                error=str(e), source="东财 push2ex"
            )

        try:
            payload = resp.json()
        except ValueError:
            return StockChangesSnapshot(
                error="API 返回非 JSON 数据", source="东财 push2ex"
            )

        if not isinstance(payload, dict) or payload.get("success") is not True:
            return StockChangesSnapshot(
                error="API 返回失败或无数据（可能非交易时间）",
                source="东财 push2ex",
            )

        data_wrapper = payload.get("data", {})
        if not isinstance(data_wrapper, dict):
            return StockChangesSnapshot(
                error="API 数据结构异常", source="东财 push2ex"
            )

        allstock = data_wrapper.get("allstock", [])
        if not allstock:
            return StockChangesSnapshot(
                source="东财 push2ex",
                description="当前无盘中异动数据（非交易时间或盘前）",
            )

        changes: list[StockChangeItem] = []
        bullish_count = 0
        bearish_count = 0
        bull_stock_counter: dict[str, int] = {}
        bear_stock_counter: dict[str, int] = {}

        for item in allstock:
            if not isinstance(item, dict):
                continue
            ct = item.get("t", 0)
            is_bull = ct in BULLISH_CHANGE_TYPES
            type_name = ALL_CHANGE_TYPES.get(ct, f"未知({ct})")

            code = str(item.get("c", ""))
            name = str(item.get("n", ""))

            change_item = StockChangeItem(
                time=_format_change_time(item.get("tm", 0)),
                code=code,
                name=name,
                change_type=ct,
                type_name=type_name,
                price=float(item.get("p", item.get("price", 0))),
                change_pct=float(item.get("i", item.get("changeRate", 0))),
                volume=int(item.get("v", item.get("volume", 0))),
                amount=float(item.get("a", item.get("amount", 0))),
                industry=str(item.get("hy", item.get("industry", ""))),
                concept=str(item.get("gn", item.get("concept", ""))),
                is_bullish=is_bull,
            )
            changes.append(change_item)

            if is_bull:
                bullish_count += 1
                bull_stock_counter[name] = bull_stock_counter.get(name, 0) + 1
            else:
                bearish_count += 1
                bear_stock_counter[name] = bear_stock_counter.get(name, 0) + 1

        total = bullish_count + bearish_count

        # 异动比
        bullish_ratio = bullish_count / max(total, 1)

        # 信号判定 ↓
        signal = "normal"
        if total >= 10:
            if bullish_ratio >= 0.75:
                signal = "bullish_bias"
            elif bullish_ratio <= 0.25:
                signal = "bearish_bias"

        # Top N 异动标的
        top_bull = sorted(
            bull_stock_counter.items(), key=lambda x: x[1], reverse=True
        )[:5]
        top_bear = sorted(
            bear_stock_counter.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # 描述
        desc_parts = []
        if bullish_count:
            desc_parts.append(f"看多异动 {bullish_count} 条")
        if bearish_count:
            desc_parts.append(f"看空异动 {bearish_count} 条")
        desc = "，".join(desc_parts) if desc_parts else "暂无异动"

        return StockChangesSnapshot(
            changes=changes,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            bullish_ratio=round(bullish_ratio, 3),
            total_count=total,
            source="东财 push2ex",
            top_bullish_stocks=[n for n, _ in top_bull],
            top_bearish_stocks=[n for n, _ in top_bear],
            signal=signal,
            description=desc,
        )


def _format_change_time(tm: int) -> str:
    """将东财时间戳（秒）转为 HH:MM 格式。"""
    if tm <= 0:
        return ""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(tm).strftime("%H:%M")
    except (OSError, ValueError):
        return str(tm)
