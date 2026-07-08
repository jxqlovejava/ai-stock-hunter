# -*- coding: utf-8 -*-
"""数据源抽象基类。

所有数据源适配器必须实现 DataProvider 接口。
参考: daily_stock_analysis data_provider/base.py 的 BaseFetcher 模式。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .schema import Bar, Financials, FundamentalMetrics, Quote, Resolution


class DataProvider(ABC):
    """数据源适配器抽象基类。

    每个具体实现（GuosenProvider / AKShareProvider）必须实现
    所有抽象方法。方法失败时返回 None，不抛异常——由聚合层处理降级。
    """

    source_name: str = "base"

    @abstractmethod
    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情。"""
        ...

    @abstractmethod
    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取财务报表（最近 N 期）。"""
        ...

    def get_bars(
        self, symbol: str, resolution: Resolution,
        start: str = "", end: str = "", market: str = "SH",
    ) -> list[Bar]:
        """获取历史 K 线（日线/分钟线）。

        默认实现返回空列表，子类按需覆盖。
        分钟级数据需子类主动支持（如 mootdx 已支持 1min/5min）。
        """
        return []

    def health_check(self) -> bool:
        """快速连通性检查。默认返回 True，子类可覆盖。"""
        return True

    def __repr__(self) -> str:
        return f"<{self.source_name}>"
