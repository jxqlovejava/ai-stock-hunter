# -*- coding: utf-8 -*-
"""mootdx + 腾讯 Loader。"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.mootdx_tencent import MootdxTencentProvider
from src.data.schema import Financials, Quote


@register
class MootdxLoader(DataLoader):
    """mootdx+腾讯行情 Loader。"""

    name = "mootdx"
    markets = ["a_share"]

    def __init__(self):
        self._provider: Optional[MootdxTencentProvider] = None

    def _provider_instance(self) -> MootdxTencentProvider:
        if self._provider is None:
            self._provider = MootdxTencentProvider()
        return self._provider

    def is_available(self) -> bool:
        try:
            return self._provider_instance().health_check()
        except Exception:
            return False

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        return self._provider_instance().get_quote(symbol, market)

    def get_quotes_batch(
        self, symbols: list[str], markets: list[str] | None = None
    ) -> list[Quote]:
        return self._provider_instance().get_quotes_batch(symbols, markets)

    def get_history(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        period: str = "daily",
    ) -> pd.DataFrame:
        # mootdx 只接受 YYYYMMDD
        start_fmt = start_date.replace("-", "")[:8] if start_date else ""
        end_fmt = end_date.replace("-", "")[:8] if end_date else ""
        return self._provider_instance().get_history(
            symbol, period, start_fmt, end_fmt
        )

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        return self._provider_instance().get_financials(symbol, market, count)
