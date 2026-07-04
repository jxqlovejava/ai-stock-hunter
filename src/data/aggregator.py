# -*- coding: utf-8 -*-
"""数据聚合层。

提供统一查询接口，封装多源优先级、降级和缓存逻辑。

使用示例:
    agg = DataAggregator()
    quote = agg.get_quote("600519", "SH")  # mootdx/腾讯优先 → AKShare 降级
    batch = agg.get_quotes_batch([("600519", "SH"), ("000001", "SZ")])
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .akshare import AKShareProvider
from .base import DataProvider
from .guosen import GuosenProvider
from .mootdx_tencent import MootdxTencentProvider
from .schema import Financials, FundamentalMetrics, Quote


class DataAggregator:
    """多源数据聚合器。

    优先级规则 (V3):
      - 实时行情: mootdx+腾讯 > 国信 > AKShare
      - 全市场扫描: AKShare (mootdx 不支持全市场)
      - 财务数据: mootdx > 国信 > AKShare
      - 历史K线: mootdx > AKShare
      - 独有数据: 各自专属源
    """

    def __init__(self):
        self._mootdx: MootdxTencentProvider | None = None
        self._guosen: GuosenProvider | None = None
        self._akshare: AKShareProvider | None = None
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=5)

    @property
    def mootdx(self) -> MootdxTencentProvider:
        """懒加载 mootdx+腾讯适配器。"""
        if self._mootdx is None:
            self._mootdx = MootdxTencentProvider()
        return self._mootdx

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
        """获取单只股票行情。mootdx+腾讯优先 → 国信 → AKShare 降级。"""
        cache_key = f"quote:{symbol}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        # V3: mootdx+腾讯优先（不封IP）
        q = self.mootdx.get_quote(symbol, market)
        if q is not None:
            self._cache_set(cache_key, q)
            return q

        # 国信
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
        """批量获取行情。mootdx+腾讯优先。"""
        # V3: mootdx+腾讯批量优先
        symbols = [s[0] for s in stocks]
        results = self.mootdx.get_quotes_batch(symbols)
        if len(results) >= len(stocks):
            return results

        # 腾讯缺漏 → 国信补
        got = {r.symbol for r in results}
        gs = self.guosen
        if gs is not None:
            remaining = [(s, m) for s, m in stocks if s not in got]
            for i in range(0, len(remaining), 10):
                batch = remaining[i : i + 10]
                batch_syms = [s[0] for s in batch]
                batch_mkts = [s[1] for s in batch]
                batch_results = gs.get_quotes_batch(batch_syms, batch_mkts)
                results.extend(batch_results)

        # AKShare 最终补漏
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
        """获取财务报表。mootdx优先 → 国信 → AKShare。"""
        cache_key = f"fin:{symbol}:{count}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        # V3: mootdx 优先
        fin = self.mootdx.get_financials(symbol, market, count)
        if fin:
            self._cache_set(cache_key, fin)
            return fin

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
        """全市场扫描。AKShare 唯一支持（mootdx/腾讯不支持全市场扫描）。"""
        return self.akshare.get_all_quotes()

    # ------------------------------------------------------------------
    # Historical K-line (for backtest)
    # ------------------------------------------------------------------

    def get_history(
        self,
        symbol: str,
        start_date: str = "2015-01-01",
        end_date: str = "",
        period: str = "daily",
    ):
        """获取历史K线数据（用于回测）。mootdx优先 → AKShare。

        Args:
            symbol: 股票代码，如 "600519"
            start_date: 起始日期 "YYYYMMDD"
            end_date: 结束日期 "YYYYMMDD"，默认今天
            period: K线周期 "daily" | "weekly" | "monthly"

        Returns:
            pd.DataFrame，列含: 日期,开盘,收盘,最高,最低,成交量,成交额,涨跌幅
        """
        import pandas as pd

        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        # V3: mootdx 优先（不封IP，TCP直连）
        start_fmt = start_date.replace("-", "")[:8] if start_date else ""
        df = self.mootdx.get_history(
            symbol=symbol, period=period,
            start_date=start_fmt, end_date=end_date,
        )
        if df is not None and not df.empty:
            return df

        # AKShare 降级
        return self.akshare.get_history(
            symbol=symbol, period=period,
            start_date=start_date, end_date=end_date,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def source_status(self) -> dict:
        """检查各数据源状态。"""
        status = {}
        status["mootdx+tencent"] = "✅" if self.mootdx.health_check() else "❌ (mootdx TCP 或腾讯 HTTP 不可达)"
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
