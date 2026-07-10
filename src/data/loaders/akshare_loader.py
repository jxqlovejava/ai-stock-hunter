# -*- coding: utf-8 -*-
"""AKShare Loader。"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data.akshare import AKShareProvider
from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.schema import Financials, Quote


@register
class AKShareLoader(DataLoader):
    """AKShare 爬虫聚合 Loader。"""

    name = "akshare"
    markets = ["a_share", "us_equity", "hk_equity"]

    def __init__(self):
        self._provider: Optional[AKShareProvider] = None

    def _provider_instance(self) -> AKShareProvider:
        if self._provider is None:
            self._provider = AKShareProvider()
        return self._provider

    def is_available(self) -> bool:
        """检测 AKShare 是否实际可用。

        先检查 import，再通过 health_check 验证底层数据源连通性
        （push2 不可达时仍可提供财务/龙虎榜/融资融券等非行情数据）。
        """
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        try:
            return self._provider_instance().health_check()
        except Exception:
            return False

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        return self._provider_instance().get_quote(symbol, market)

    def get_quotes_batch(
        self, symbols: list[str], markets: list[str] | None = None
    ) -> list[Quote]:
        # AKShare 目前只有全市场扫描；退化为逐个 get_quote
        markets = markets or ["SH"] * len(symbols)
        results = []
        for sym, mkt in zip(symbols, markets):
            q = self.get_quote(sym, mkt)
            if q is not None:
                results.append(q)
        return results

    def get_history(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        period: str = "daily",
    ) -> pd.DataFrame:
        return self._provider_instance().get_history(symbol, period, start_date, end_date)

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        return self._provider_instance().get_financials(symbol, market, count)

    def get_all_quotes(self) -> list[Quote]:
        return self._provider_instance().get_all_quotes()
