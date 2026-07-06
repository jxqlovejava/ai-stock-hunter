# -*- coding: utf-8 -*-
"""A 股市场规则引擎。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.backtest.engines.base import BaseEngine


class ChinaAEngine(BaseEngine):
    """A 股规则：T+1、无做空、涨跌停、100 股手、印花税+过户费+佣金。"""

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}
        super().__init__(config)
        self.commission_rate = config.get("commission_rate", 0.0003)
        self.commission_min = config.get("commission_min", 5.0)
        self.stamp_tax = config.get("stamp_tax", 0.0005)
        self.transfer_fee = config.get("transfer_fee", 0.00001)
        self.slippage_rate = config.get("slippage", 0.001)

    @staticmethod
    def _price_limit(symbol: str) -> float:
        code = symbol.split(".")[0] if "." in symbol else symbol
        if code.startswith(("300", "688")):
            return 0.20
        if code.startswith("8") and len(code) == 6:
            return 0.30
        return 0.10

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        # 1. 无做空
        if direction == -1:
            return False

        # 2. T+1: 当日买入不可卖出
        if direction == 0:
            pos = self.positions.get(symbol)
            if pos is not None:
                bar_date = self._bar_date(bar)
                entry_date = pos.entry_time.date()
                if bar_date is not None and entry_date is not None and bar_date == entry_date:
                    return False

        # 3. 涨跌停价格限制
        pct_chg = self._bar_pct_change(bar)
        if pct_chg is not None:
            limit = self._price_limit(symbol)
            if direction == 1 and pct_chg >= limit - 0.001:
                return False  # 涨停买不进
            if direction == 0 and pct_chg <= -limit + 0.001:
                return False  # 跌停卖不出
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return max(int(raw_size / 100) * 100, 0)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool
    ) -> float:
        notional = size * price
        comm = max(notional * self.commission_rate, self.commission_min)
        comm += notional * self.transfer_fee
        if not is_open:
            comm += notional * self.stamp_tax
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        return price * (1 + direction * self.slippage_rate)

    @staticmethod
    def _bar_date(bar: pd.Series) -> date | None:
        ts = bar.get("timestamp")
        if isinstance(ts, pd.Timestamp):
            return ts.date()
        if isinstance(ts, date):
            return ts
        return None

    @staticmethod
    def _bar_pct_change(bar: pd.Series) -> float | None:
        prev = bar.get("prev_close")
        close = bar.get("close")
        if prev is None or close is None or prev == 0:
            return None
        return (close - prev) / prev


def listing_days(listing_date: date | None) -> int:
    """上市自然日数。"""
    if listing_date is None:
        return 9999
    return (date.today() - listing_date).days
