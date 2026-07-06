# -*- coding: utf-8 -*-
"""A 股硬性排除 Guard。

对应 .claude/rules/guardrails.md 中的 A 股特定排除规则。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.data.schema import Quote


class AShareHardGuard:
    """A 股硬性规则：ST、次新、低流动性、停牌、连续跌停。"""

    MIN_LISTING_DAYS = 60
    MIN_TURNOVER = 50_000_000

    def __init__(self):
        self.flags: list[str] = []

    def is_eligible(
        self,
        symbol: str,
        quote: Quote | None,
        bar: pd.Series | None = None,
    ) -> bool:
        """返回 True 表示可通过硬性门禁。"""
        self.flags = []

        if quote is None:
            self.flags.append("[DATA_GAP] 无行情数据")
            return False

        if quote.is_st:
            self.flags.append("ST/*ST 股票禁止交易")
            return False

        if quote.suspended:
            self.flags.append("停牌股票禁止交易")
            return False

        if quote.listing_date is not None:
            days = (date.today() - quote.listing_date.date()).days
            if days < self.MIN_LISTING_DAYS:
                self.flags.append(f"上市不满 {self.MIN_LISTING_DAYS} 天")
                return False

        if quote.turnover is not None and quote.turnover < self.MIN_TURNOVER:
            self.flags.append(f"成交额低于 {self.MIN_TURNOVER / 1e4:.0f} 万")
            return False

        if bar is not None and self._is_limit_down(bar):
            self.flags.append("连续跌停")
            return False

        return True

    @staticmethod
    def _is_limit_down(bar: pd.Series) -> bool:
        prev = bar.get("prev_close")
        close = bar.get("close")
        if prev is None or close is None or prev == 0:
            return False
        pct = (close - prev) / prev
        # 主板跌停 -10%（粗略），精确值由 engine 按代码判断
        return pct <= -0.099

    def last_flags(self) -> list[str]:
        return list(self.flags)
