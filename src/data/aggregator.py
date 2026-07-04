# -*- coding: utf-8 -*-
"""数据聚合层。

提供统一查询接口，封装多源优先级、降级和缓存逻辑。

使用示例:
    agg = DataAggregator()
    quote = agg.get_quote("600519", "SH")  # 国信优先 → AKShare 降级
    batch = agg.get_quotes_batch([("600519", "SH"), ("000001", "SZ")])
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .akshare import AKShareProvider
from .base import DataProvider
from .guosen import GuosenProvider
from .schema import Financials, FundamentalMetrics, Quote


class DataAggregator:
    """多源数据聚合器。

    优先级规则:
      - 实时行情: 国信 > AKShare
      - 全市场扫描: AKShare > 国信
      - 财务数据: 国信 > AKShare
      - 独有数据: 各自专属源
    """

    def __init__(self):
        self._guosen: GuosenProvider | None = None
        self._akshare: AKShareProvider | None = None
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=5)

    @property
    def guosen(self) -> GuosenProvider | None:
        """懒加载国信适配器。无 API Key 时返回 None。"""
        if self._guosen is None:
            try:
                self._guosen = GuosenProvider()
            except RuntimeError:
                pass
        return self._guosen

    @property
    def akshare(self) -> AKShareProvider:
        """懒加载 AKShare 适配器。"""
        if self._akshare is None:
            self._akshare = AKShareProvider()
        return self._akshare

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票行情。国信优先，AKShare 降级。"""
        cache_key = f"quote:{symbol}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        # 国信优先
        gs = self.guosen
        if gs is not None:
            q = gs.get_quote(symbol, market)
            if q is not None:
                self._cache_set(cache_key, q)
                return q

        # AKShare 降级
        q = self.akshare.get_quote(symbol, market)
        if q is not None:
            self._cache_set(cache_key, q)
        return q

    def get_quotes_batch(
        self, stocks: list[tuple[str, str]]
    ) -> list[Quote]:
        """批量获取行情。一次调用最多 10 只（国信限制）。"""
        results = []
        gs = self.guosen

        # 国信批量（最多 10/批）
        if gs is not None:
            for i in range(0, len(stocks), 10):
                batch = stocks[i : i + 10]
                symbols = [s[0] for s in batch]
                markets = [s[1] for s in batch]
                batch_results = gs.get_quotes_batch(symbols, markets)
                results.extend(batch_results)

        # AKShare 补漏
        if len(results) < len(stocks):
            got = {r.symbol for r in results}
            for sym, mkt in stocks:
                if sym not in got:
                    q = self.akshare.get_quote(sym, mkt)
                    if q is not None:
                        results.append(q)

        return results

    # ------------------------------------------------------------------
    # Financials
    # ------------------------------------------------------------------

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取财务报表。国信优先。"""
        cache_key = f"fin:{symbol}:{count}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        gs = self.guosen
        if gs is not None:
            fin = gs.get_financials(symbol, market, count)
            if fin:
                self._cache_set(cache_key, fin)
                return fin

        fin = self.akshare.get_financials(symbol, market, count)
        if fin:
            self._cache_set(cache_key, fin)
        return fin

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan_all_stocks(self) -> list[Quote]:
        """全市场扫描。AKShare 优先（无限制+免费）。"""
        return self.akshare.get_all_quotes()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def source_status(self) -> dict:
        """检查各数据源状态。"""
        status = {}
        gs = self.guosen
        status["guosen"] = "✅" if (gs is not None and gs.health_check()) else "❌ (无 key 或不可用)"
        status["akshare"] = "✅" if self.akshare.health_check() else "❌"
        return status

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str):
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return val

    def _cache_set(self, key: str, val):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()
