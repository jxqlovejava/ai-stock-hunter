# -*- coding: utf-8 -*-
"""数据源 Loader 抽象基类。

Loader 是 DataProvider 之上的薄封装，用于 registry + fallback chain。
每个 Loader 返回的数据必须附带 SourceCitation（通过 df.attrs 或 DTO）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from src.data.schema import Financials, Quote


class NoAvailableSourceError(RuntimeError):
    """没有可用数据源时抛出。"""


class DataLoader(ABC):
    """数据源 Loader 抽象基类。

    子类必须提供:
      - name: str  唯一标识
      - markets: list[str]  支持的市场列表，如 ["a_share"]
      - is_available(): 是否可用
      - get_quote/get_quotes_batch/get_history/get_financials 按需实现
    """

    name: str = "base"
    markets: list[str] = []

    def is_available(self) -> bool:
        """默认可用；需要鉴权/网络的子类应覆盖。"""
        return True

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情。不支持时返回 None。"""
        return None

    def get_quotes_batch(
        self, symbols: list[str], markets: list[str] | None = None
    ) -> list[Quote]:
        """批量获取行情。默认退化为逐个 get_quote。"""
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
        """获取历史 K 线。不支持时返回空 DataFrame。"""
        return pd.DataFrame()

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取财务报表。不支持时返回空列表。"""
        return []

    def __repr__(self) -> str:
        return f"<{self.name}>"
