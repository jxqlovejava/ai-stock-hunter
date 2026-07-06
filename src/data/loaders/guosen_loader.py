# -*- coding: utf-8 -*-
"""国信证券 Loader。"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from datetime import datetime

from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.guosen import GuosenProvider
from src.data.schema import Financials, Quote


@register
class GuosenLoader(DataLoader):
    """国信证券官方 API Loader。需要 GS_API_KEY。"""

    name = "guosen"
    markets = ["a_share"]

    def __init__(self):
        self._provider: Optional[GuosenProvider] = None
        self._available: Optional[bool] = None

    def _provider_instance(self) -> Optional[GuosenProvider]:
        if self._available is False:
            return None
        if self._provider is None:
            try:
                self._provider = GuosenProvider()
                self._available = True
            except Exception:
                self._available = False
        return self._provider

    def is_available(self) -> bool:
        prov = self._provider_instance()
        if prov is None:
            return False
        try:
            return prov.health_check()
        except Exception:
            return False

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
        markets = markets or ["SH"] * len(symbols)
        return prov.get_quotes_batch(symbols, markets)

    def get_history(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        period: str = "daily",
    ) -> pd.DataFrame:
        prov = self._provider_instance()
        if prov is None:
            return pd.DataFrame()
        # 国信只支持日线与 wantNums；按请求范围估算交易日数
        days = 250
        if start_date:
            try:
                end_dt = datetime.strptime(
                    end_date.replace("-", ""), "%Y%m%d"
                ) if end_date else datetime.now()
                start_dt = datetime.strptime(start_date.replace("-", ""), "%Y%m%d")
                days = max(5, (end_dt - start_dt).days)
            except ValueError:
                pass
        records = prov.get_history(symbol, market="SH", days=days)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # 统一列名（国信字段名可能不同，做最小兼容）
        rename_map = {
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        prov = self._provider_instance()
        if prov is None:
            return []
        return prov.get_financials(symbol, market, count)
