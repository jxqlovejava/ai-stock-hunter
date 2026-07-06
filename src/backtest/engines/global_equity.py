# -*- coding: utf-8 -*-
"""全球股票市场规则引擎（美股/港股）。"""

from __future__ import annotations

import pandas as pd

from src.backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """T+0、可多空、按市场区分手数/小数。"""

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market
        self.slippage_us = config.get("slippage_us", 0.0005)
        self.slippage_hk = config.get("slippage_hk", 0.001)
        self.hk_stamp_tax = config.get("hk_stamp_tax", 0.001)
        self.hk_commission = config.get("hk_commission", 0.00015)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return True  # T+0, long/short allowed

    def round_size(self, raw_size: float, price: float) -> float:
        if self.market == "hk":
            return max(int(raw_size / 100) * 100, 0)
        return round(max(raw_size, 0.0), 2)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool
    ) -> float:
        if self.market == "hk":
            notional = size * price
            return notional * (self.hk_commission + self.hk_stamp_tax)
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        rate = self.slippage_hk if self.market == "hk" else self.slippage_us
        return price * (1 + direction * rate)
