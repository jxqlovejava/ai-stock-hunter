# -*- coding: utf-8 -*-
"""准入检查 — 硬过滤层（纯规则，0% AI）。

过滤规则:
  1. ST/*ST → REJECT
  2. 上市 < 60 交易日 → REJECT
  3. 日均成交额 < 5000万 → REJECT
  4. 当日涨跌停 → REJECT
  5. 停牌中 → REJECT
  6. 近 12 个月有财务造假/违规记录 → FLAG
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


@dataclass
class AdmissionResult:
    """准入检查结果。"""
    symbol: str
    name: str
    status: GateStatus
    flags: list[str] = field(default_factory=list)


class AdmissionCheck:
    """准入检查: 股票资质过滤。

    纯规则引擎，不依赖 AI。在军规之后、多维诊断之前运行。
    """

    MIN_DAILY_VOLUME = 50_000_000    # 5000万
    MIN_LISTING_DAYS = 60

    def check(self, symbol: str, name: str = "", context: dict | None = None) -> AdmissionResult:
        """审查单只股票。

        Args:
            symbol: 6 位股票代码
            name: 股票名称
            context: 包含上市天数/停牌状态/违规记录等

        Returns:
            AdmissionResult with status
        """
        ctx = context or {}
        flags = []

        # 1. ST/*ST
        if "ST" in name.upper():
            return AdmissionResult(symbol=symbol, name=name, status=GateStatus.REJECTED, flags=["ST/*ST"])

        # 2. 次新股
        listing_days = ctx.get("listing_days", 365)
        if listing_days < self.MIN_LISTING_DAYS:
            return AdmissionResult(symbol=symbol, name=name, status=GateStatus.REJECTED, flags=[f"次新股 ({listing_days}d)"])

        # 3. 流动性
        avg_volume = ctx.get("avg_daily_volume", 1e9)
        if avg_volume < self.MIN_DAILY_VOLUME:
            return AdmissionResult(symbol=symbol, name=name, status=GateStatus.REJECTED, flags=["流动性不足"])

        # 4. 涨跌停
        if ctx.get("is_limit_up") or ctx.get("is_limit_down"):
            return AdmissionResult(symbol=symbol, name=name, status=GateStatus.REJECTED, flags=["涨跌停板"])

        # 5. 停牌
        if ctx.get("is_suspended"):
            return AdmissionResult(symbol=symbol, name=name, status=GateStatus.REJECTED, flags=["停牌中"])

        # 6. 违规记录
        if ctx.get("has_violation"):
            flags.append("近12月有违规记录")

        status = GateStatus.FLAGGED if flags else GateStatus.ACCEPTED
        return AdmissionResult(symbol=symbol, name=name, status=status, flags=flags)

    def filter_batch(self, candidates: list[dict]) -> tuple[list[dict], list[AdmissionResult]]:
        """批量过滤。返回 (通过, 被拒)。"""
        accepted, rejected = [], []
        for c in candidates:
            result = self.check(c.get("symbol", ""), c.get("name", ""), c.get("context"))
            if result.status == GateStatus.REJECTED:
                rejected.append(result)
            else:
                accepted.append(c)
        return accepted, rejected

