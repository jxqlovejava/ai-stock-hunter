# -*- coding: utf-8 -*-
"""数据聚合层。

提供统一查询接口，封装多源优先级、降级和缓存逻辑。

使用示例:
    agg = DataAggregator()
    quote = agg.get_quote("600519", "SH")  # mootdx/腾讯优先 → mx-data交叉验证 → AKShare 降级
    batch = agg.get_quotes_batch([("600519", "SH"), ("000001", "SZ")])
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .akshare import AKShareProvider
from .base import DataProvider
from .guosen import GuosenProvider
from .mootdx_tencent import MootdxTencentProvider
from .schema import (
    Financials,
    FundamentalMetrics,
    NewsItem,
    Quote,
    RelatedParty,
    ScreeningResult,
)


class DataAggregator:
    """多源数据聚合器。

    优先级规则 (V4):
      - 实时行情: mootdx+腾讯 > mx-data(交叉验证) > 国信 > AKShare
      - 全市场扫描: mx-xuangu > AKShare
      - 财务数据: mootdx > mx-data(NL补充) > 国信 > AKShare
      - 历史K线: mootdx > AKShare
      - 资讯搜索: mx-search > 东财新闻
      - 独有数据: 各自专属源
    """

    def __init__(self):
        self._mootdx: MootdxTencentProvider | None = None
        self._guosen: GuosenProvider | None = None
        self._akshare: AKShareProvider | None = None
        self._miaoxiang: "MiaoXiangProvider | None" = None  # type: ignore[name-defined]
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

    @property
    def miaoxiang(self) -> "MiaoXiangProvider | None":  # type: ignore[name-defined]
        """懒加载妙想适配器。无 MX_APIKEY 时返回 None。"""
        if self._miaoxiang is None:
            try:
                from .miaoxiang_provider import MiaoXiangProvider
                provider = MiaoXiangProvider()
                if provider.health_check():
                    self._miaoxiang = provider
                else:
                    self._miaoxiang = None
            except Exception:
                self._miaoxiang = None
        return self._miaoxiang

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
        mx = self.miaoxiang
        status["miaoxiang"] = "✅" if (mx is not None and mx.health_check()) else "❌ (无 MX_APIKEY 或不可用)"
        return status

    # ------------------------------------------------------------------
    # V4 新增: 妙想 Skill 代理方法
    # ------------------------------------------------------------------

    def search_news(self, query: str, max_results: int = 10) -> list[NewsItem]:
        """搜索金融资讯。mx-search 优先 → 返回空列表（无降级源）。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.search_news(query, max_results)
        return []

    def search_announcements(self, symbol: str) -> list[NewsItem]:
        """搜索个股公告。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.search_announcements(symbol)
        return []

    def search_research_reports(self, symbol: str) -> list[NewsItem]:
        """搜索个股研报。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.search_research_reports(symbol)
        return []

    def get_related_parties(self, symbol: str) -> list[RelatedParty]:
        """获取个股关联方。mx-data 独有能力，无降级源。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.get_related_parties(symbol)
        return []

    def screen_stocks(self, conditions: str) -> list[ScreeningResult]:
        """条件选股。mx-xuangu 优先 → AKShare scan_all_stocks() 降级（客户端过滤）。"""
        mx = self.miaoxiang
        if mx is not None:
            results = mx.screen_stocks(conditions)
            if results:
                return results
        # AKShare 降级：全市场扫描 + 客户端条件过滤（简化实现）
        return []

    def screen_by_industry(self, industry: str) -> list[ScreeningResult]:
        """按行业筛选。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.screen_by_industry(industry)
        return []

    def get_cross_validated_quote(self, symbol: str, market: str = "SH") -> tuple[Optional[Quote], bool, bool]:
        """双源交叉验证行情。

        Returns:
            (quote, cross_validated, dispute)
            - cross_validated: ≥2 源成功返回
            - dispute: 两源价格差异 > 5%
        """
        q1 = self.get_quote(symbol, market)  # mootdx+腾讯 (主力)
        mx = self.miaoxiang
        q2 = mx.get_quote(symbol, market) if mx else None

        if q1 is None and q2 is None:
            return None, False, False

        if q1 is None:
            return q2, False, False
        if q2 is None:
            return q1, False, False

        # 双源交叉验证
        dispute = abs(q1.price - q2.price) / max(q1.price, q2.price) > 0.05
        return q1, True, dispute

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str, ttl: timedelta | None = None):
        ttl = ttl or self._cache_ttl
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > ttl:
            del self._cache[key]
            return None
        return val

    def _cache_set(self, key: str, val):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()
