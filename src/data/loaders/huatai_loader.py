# -*- coding: utf-8 -*-
"""华泰证券 Loader — 行情/财务数据首选源。

华泰 queryIndicator 接口通过 AI 解析返回结构化行情数据。
不可用时自动降级到国信 → 腾讯 → mootdx → AKShare。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.huatai import HuataiProvider
from src.data.schema import Financials, Quote


@register
class HuataiLoader(DataLoader):
    """华泰证券行情 Loader。需要 HT_APIKEY + query-indicator skill。

    行情获取: 通过 queryIndicator 接口解析 AI 返回的结构化数据。
    超时 8s，失败返回 None 自动降级到下一源。
    """

    name = "huatai"
    markets = ["a_share"]

    def __init__(self):
        self._provider: Optional[HuataiProvider] = None
        self._available: Optional[bool] = None

    def _provider_instance(self) -> Optional[HuataiProvider]:
        if self._available is False:
            return None
        if self._provider is None:
            try:
                self._provider = HuataiProvider()
                self._available = self._provider.health_check()
            except Exception:
                self._available = False
        return self._provider

    def is_available(self) -> bool:
        return self._provider_instance() is not None

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        prov = self._provider_instance()
        if prov is None:
            return None
        return prov.get_quote(symbol, market)

    def get_quotes_batch(
        self, symbols: list[str], markets: list[str] | None = None
    ) -> list[Quote]:
        prov = self._provider_instance()
        if prov is None:
            return []
        results = []
        for sym in symbols:
            q = prov.get_quote(sym, "SH" if sym.startswith(("6", "68")) else "SZ")
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
        # 华泰不支持历史K线，降级到下一源
        return pd.DataFrame()

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        # 华泰通过 diagnosisStock 获取财报解读（非结构化），不适合管道
        return []
