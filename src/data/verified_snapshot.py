# -*- coding: utf-8 -*-
"""确定性盘面快照 (Verified Market Snapshot) — 关键数字的事实锚点。

借鉴 TradingAgents `get_verified_market_snapshot` 的反幻觉设计:
  - 任何涉及"当前价/涨跌幅/量额"的分析文本, 必须能锚定到这份确定性快照
  - 快照来自交叉验证行情 (≥2 源) 或单源行情, 状态显式标注
  - 文本中与快照冲突的价格声明会被标记, 而不是被静默接受

Tier: 行情本身 primary (交易所); 交叉验证状态 = 数据质量信息。

Usage:
    snap = get_verified_market_snapshot("600519")
    if snap:
        conflicts = check_price_claims("当前价 1680 元...", snap)
        # → [Conflict(text="当前价 1680", snapshot_price=1712.5, ...)]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .aggregator import DataAggregator

_PRICE_PATTERNS = [
    r"当前价[约为]?\s*([\d.]+)",
    r"最新价[约为]?\s*([\d.]+)",
    r"现价[约为]?\s*([\d.]+)",
]


@dataclass
class VerifiedSnapshot:
    """确定性盘面快照。"""

    symbol: str
    name: str = ""
    price: float = 0.0  # 最新价
    change_pct: float = 0.0  # 涨跌幅 %
    volume: int = 0
    turnover: float = 0.0
    prev_close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    # 交叉验证状态
    cross_validated: bool = False  # ≥2 源
    dispute: bool = False  # 两源价格差异 > 5%
    source: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)

    def anchor_block(self) -> str:
        """渲染成可附加到分析报告的盘面锚定块。"""
        status = "✅ 双源交叉验证" if self.cross_validated else "⚠️ 单源未验证"
        if self.dispute:
            status += " · 🔴 双源差异>5% [DISPUTED]"
        return (
            f"📌 盘面数据锚定 ({self.symbol} {self.name or ''})\n"
            f"- 最新价 {self.price} · 涨跌幅 {self.change_pct}% · "
            f"成交额 {self.turnover / 1e8:.1f} 亿\n"
            f"- 状态: {status} · 来源 {self.source or '?'} · 抓取 {self.fetched_at:%H:%M}"
        )


@dataclass
class SnapshotConflict:
    """文本中与快照冲突的价格声明。"""

    matched_text: str
    claimed_price: float
    snapshot_price: float
    deviation_pct: float


def get_verified_market_snapshot(
    symbol: str, market: str = "SH", aggregator: Optional[DataAggregator] = None
) -> Optional[VerifiedSnapshot]:
    """获取确定性盘面快照 (交叉验证行情)。

    Args:
        symbol: 6 位股票代码。
        market: 市场 (SH/SZ)。
        aggregator: 可注入的聚合器 (测试用); 默认新建。

    Returns:
        VerifiedSnapshot; 无行情时返回 None (不抛异常)。
    """
    agg = aggregator or DataAggregator()
    try:
        quote, cross_validated, dispute = agg.get_cross_validated_quote(symbol, market)
    except Exception:
        return None
    if quote is None:
        return None
    return VerifiedSnapshot(
        symbol=symbol,
        name=quote.name or "",
        price=quote.price,
        change_pct=quote.change_pct,
        volume=quote.volume,
        turnover=quote.turnover,
        prev_close=quote.prev_close,
        high=quote.high,
        low=quote.low,
        open=quote.open,
        cross_validated=cross_validated,
        dispute=dispute,
        source=quote.source or "",
    )


def check_price_claims(
    text: str, snapshot: VerifiedSnapshot, tolerance: float = 0.015
) -> list[SnapshotConflict]:
    """检查文本中的价格声明是否与快照冲突。

    识别 "当前价/最新价/现价 X" 形式的声明; 与快照最新价偏差超过 tolerance
    (默认 1.5%) 记为冲突。返回冲突列表, 空 = 无冲突。

    Args:
        text: 待检查文本 (如 LLM 生成的分析叙述)。
        snapshot: 确定性快照。
        tolerance: 相对偏差容忍度。
    """
    if not text or snapshot.price <= 0:
        return []
    conflicts: list[SnapshotConflict] = []
    for pattern in _PRICE_PATTERNS:
        for m in re.finditer(pattern, text):
            try:
                claimed = float(m.group(1))
            except (ValueError, TypeError):
                continue
            if claimed <= 0:
                continue
            dev = abs(claimed - snapshot.price) / snapshot.price
            if dev > tolerance:
                conflicts.append(
                    SnapshotConflict(
                        matched_text=m.group(0),
                        claimed_price=claimed,
                        snapshot_price=snapshot.price,
                        deviation_pct=round(dev * 100, 2),
                    )
                )
    # 去重 (同一数字被多个 pattern 命中)
    seen: set[tuple] = set()
    unique: list[SnapshotConflict] = []
    for c in conflicts:
        key = (round(c.claimed_price, 2), round(c.snapshot_price, 2))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique
