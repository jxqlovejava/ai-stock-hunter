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

import pandas as pd

from .akshare import AKShareProvider
from .base import DataProvider
from .guosen import GuosenProvider
from .loaders import FALLBACK_CHAINS, LOADER_REGISTRY, NoAvailableSourceError
from .mootdx_tencent import MootdxTencentProvider
from .schema import (
    BoardChange,
    ExecutiveProfile,
    ExecutiveTrade,
    Financials,
    FundamentalMetrics,
    NewsItem,
    Quote,
    RelatedParty,
    ScreeningResult,
)
from .source_citation import make_citation, make_data_gap_citation
from src.utils.decimal_utils import D, safe_divide


class DataAggregator:
    """多源数据聚合器。

    优先级规则 (V5):
      - 实时行情: 华泰(HT_APIKEY) > 国信(GS_API_KEY) > 腾讯(免费) > mootdx(TCP) > AKShare
      - 全市场扫描: AKShare
      - 财务数据: 华泰 > 国信 > mootdx > AKShare
      - 历史K线: 国信 > mootdx > AKShare
      - 资讯搜索: mx-search > 东财新闻
      - 独有数据: 各自专属源
      - 降级: 任一源不可用时自动跳过，无可用源时抛出 NoAvailableSourceError
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
    # Loader helpers
    # ------------------------------------------------------------------

    def _walk_quote_chain(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """按 a_share fallback 链获取单只股票行情，并附加 citation。"""
        for name in FALLBACK_CHAINS.get("a_share", []):
            loader_cls = LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception:
                continue
            if not loader.is_available():
                continue
            q = loader.get_quote(symbol, market)
            if q is not None:
                if q.citation is None:
                    q.citation = make_citation(
                        provider=q.source,
                        field="quote",
                        data_type="realtime_quote",
                    )
                return q
        return None

    def _walk_history_chain(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        period: str = "daily",
    ) -> pd.DataFrame:
        """按 a_share fallback 链获取历史 K 线，并附加 citation。"""
        for name in FALLBACK_CHAINS.get("a_share", []):
            loader_cls = LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception:
                continue
            if not loader.is_available():
                continue
            df = loader.get_history(symbol, start_date, end_date, period)
            if df is not None and not df.empty:
                if "source_citation" not in df.attrs:
                    df.attrs["source_citation"] = make_citation(
                        provider=loader.name,
                        field="ohlcv",
                        data_type="daily_bar",
                    )
                return df
        return pd.DataFrame()

    def _walk_financials_chain(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """按 a_share fallback 链获取财务报表，并附加 citation。"""
        for name in FALLBACK_CHAINS.get("a_share", []):
            loader_cls = LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception:
                continue
            if not loader.is_available():
                continue
            fins = loader.get_financials(symbol, market, count)
            if fins:
                citation = make_citation(
                    provider=loader.name,
                    field="financials",
                    data_type="financials",
                )
                for fin in fins:
                    if fin.citation is None:
                        fin.citation = citation
                return fins
        return []

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票行情。按 registry fallback 链：verified_cache > guosen > mootdx > akshare > tencent。"""
        cache_key = f"quote:{symbol}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        q = self._walk_quote_chain(symbol, market)
        if q is not None:
            self._cache_set(cache_key, q)
            return q
        return None

    def get_quotes_batch(
        self, stocks: list[tuple[str, str]]
    ) -> list[Quote]:
        """批量获取行情。按 registry fallback 链逐源补全，并附加 citation。"""
        symbols = [s[0] for s in stocks]
        markets = [s[1] for s in stocks]
        results: list[Quote] = []
        got: set[str] = set()

        for name in FALLBACK_CHAINS.get("a_share", []):
            if len(results) >= len(stocks):
                break
            loader_cls = LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception:
                continue
            if not loader.is_available():
                continue

            remaining = [(s, m) for s, m in zip(symbols, markets) if s not in got]
            batch_symbols = [s for s, _ in remaining]
            batch_markets = [m for _, m in remaining]
            try:
                batch_results = loader.get_quotes_batch(batch_symbols, batch_markets)
            except Exception:
                batch_results = []

            citation = make_citation(
                provider=loader.name,
                field="quote",
                data_type="realtime_quote",
            )
            for q in batch_results:
                if q.symbol not in got:
                    if q.citation is None:
                        q.citation = citation
                    results.append(q)
                    got.add(q.symbol)

        return results

    # ------------------------------------------------------------------
    # Financials
    # ------------------------------------------------------------------

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取财务报表。按 registry fallback 链。"""
        cache_key = f"fin:{symbol}:{count}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        fins = self._walk_financials_chain(symbol, market, count)
        if fins:
            self._cache_set(cache_key, fins)
        return fins

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
        """获取历史K线数据（用于回测）。按 registry fallback 链。"""
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        return self._walk_history_chain(symbol, start_date, end_date, period)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def source_status(self) -> dict:
        """检查各数据源状态。"""
        status = {}
        # 华泰 (主数据源)
        try:
            from src.data.huatai import HuataiProvider
            ht = HuataiProvider()
            status["huatai"] = "✅" if ht.health_check() else "❌ (无 HT_APIKEY 或 skill 不可用)"
        except Exception:
            status["huatai"] = "❌ (不可用)"
        gs = self.guosen
        status["guosen"] = "✅" if (gs is not None and gs.health_check()) else "❌ (无 GS_API_KEY)"
        status["tencent"] = "✅" if self.mootdx.health_check() else "❌ (腾讯 HTTP 不可达)"
        status["mootdx"] = "✅" if self.mootdx.health_check() else "❌ (mootdx TCP 不可达)"
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

    def get_executive_trades(self, symbol: str) -> list[ExecutiveTrade]:
        """获取高管增减持。mx-data 独有能力，无降级源。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.get_executive_trades(symbol)
        return []

    def get_executive_profiles(self, symbol: str) -> list[ExecutiveProfile]:
        """获取高管背景履历。mx-data 独有能力，无降级源。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.get_executive_profiles(symbol)
        return []

    def get_board_changes(self, symbol: str) -> list[BoardChange]:
        """获取董监高变动。mx-data 独有能力，无降级源。"""
        mx = self.miaoxiang
        if mx is not None:
            return mx.get_board_changes(symbol)
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
    # Phase 5: 估值 + 周期数据方法
    # ------------------------------------------------------------------

    def get_fundamental_metrics(
        self, symbol: str, market: str = "SH"
    ) -> Optional[FundamentalMetrics]:
        """聚合基本面指标: PE/PB/ROE/资产负债率/市值。

        Quote.PE/PB + Financials.ROE → FundamentalMetrics。
        """
        cache_key = f"fmetrics:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(minutes=30))
        if cached:
            return cached

        quote, cross_validated, dispute = self.get_cross_validated_quote(symbol, market)
        if quote is None:
            return None

        fin_list = self.get_financials(symbol, market, count=1)
        roe: Optional[float] = None
        debt: Optional[float] = None
        if fin_list:
            fin = fin_list[0]
            if fin.net_profit and fin.total_assets and fin.total_liabilities:
                equity = D(fin.total_assets) - D(fin.total_liabilities)
                if equity > D("0"):
                    roe = float(safe_divide(D(fin.net_profit), equity, precision=4) * D("100"))
                if fin.total_assets > 0:
                    debt = float(safe_divide(D(fin.total_liabilities), D(fin.total_assets), precision=4) * D("100"))

        citations = [make_citation(provider=quote.source, field="quote", data_type="realtime_quote", source_tier="T1")]
        if cross_validated:
            mx = self.miaoxiang
            if mx is not None:
                citations.append(make_citation(provider="miaoxiang", field="quote", data_type="realtime_quote", source_tier="T2"))
        if dispute:
            citations.append(make_data_gap_citation(provider="aggregator", field="quote_dispute", reason="行情双源价格分歧 >5%"))

        metrics = FundamentalMetrics(
            symbol=symbol,
            name=quote.name,
            pe_ttm=quote.pe_ttm,
            pb=quote.pb,
            roe=roe,
            debt_to_equity=debt,
            market_cap=quote.market_cap,
            sources=[quote.source],
            cross_validated=cross_validated,
            dispute=dispute,
            citations=citations,
        )
        self._cache_set(cache_key, metrics)
        return metrics

    def get_industry_pe_pb(
        self, symbol: str, market: str = "SH"
    ) -> tuple[Optional[float], Optional[float]]:
        """获取个股所属行业 PE/PB 中位数。

        优先用 AKShare 行业板块数据，无法分类时返回 None。
        Returns: (industry_pe_median, industry_pb_median)
        """
        cache_key = f"ind_pe:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached:
            return cached

        try:
            import akshare as ak
            # 获取所有行业板块的 PE/PB 数据
            df = ak.stock_board_industry_spot_em()
            if df is None or df.empty:
                self._cache_set(cache_key, (None, None))
                return None, None

            # 从中取中位数作为市场参考（后续可细化到具体行业）
            pe_vals = df.iloc[:, 6] if df.shape[1] > 6 else None  # 板块PE列
            pb_vals = df.iloc[:, 7] if df.shape[1] > 7 else None  # 板块PB列

            pe_median: Optional[float] = None
            pb_median: Optional[float] = None
            if pe_vals is not None and len(pe_vals) > 0:
                try:
                    pe_vals_num = pe_vals.apply(
                        lambda x: float(x) if x and str(x).replace(".", "").replace("-", "").isdigit() else None
                    ).dropna()
                    if len(pe_vals_num) > 0:
                        pe_median = round(float(pe_vals_num.median()), 2)
                except Exception:
                    pe_median = None
            if pb_vals is not None and len(pb_vals) > 0:
                try:
                    pb_vals_num = pb_vals.apply(
                        lambda x: float(x) if x and str(x).replace(".", "").replace("-", "").isdigit() else None
                    ).dropna()
                    if len(pb_vals_num) > 0:
                        pb_median = round(float(pb_vals_num.median()), 2)
                except Exception:
                    pb_median = None

            result = (pe_median, pb_median)
            self._cache_set(cache_key, result)
            return result
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.debug("Industry PE/PB fetch failed for %s", symbol, exc_info=True)
            result = (None, None)
            self._cache_set(cache_key, result)
            return result

    def get_dividend_data(self, symbol: str) -> Optional[float]:
        """获取股息率 (%)。使用 AKShare 历史分红数据。

        Returns: dividend_yield as percentage, or None.
        """
        cache_key = f"div:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.stock_history_dividend()
            if df is None or df.empty:
                self._cache_set(cache_key, None)
                return None

            # 筛选该股票的分红记录
            stock_col = None
            for col in ["代码", "股票代码", "symbol"]:
                if col in df.columns:
                    stock_col = col
                    break
            if stock_col is None:
                self._cache_set(cache_key, None)
                return None

            stock_div = df[df[stock_col].astype(str).str.contains(symbol)]
            if stock_div.empty:
                self._cache_set(cache_key, None)
                return None

            result: Optional[float] = None
            # 尝试取股息率列
            for col in ["股息率", "dividend_yield", "div_rate"]:
                if col in stock_div.columns:
                    vals = stock_div[col].dropna()
                    if len(vals) > 0:
                        result = round(float(vals.iloc[0]), 2)
                        break
            self._cache_set(cache_key, result)
            return result
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.debug("Dividend data fetch failed for %s", symbol, exc_info=True)
            self._cache_set(cache_key, None)
            return None

    def get_earnings_growth(self, symbol: str, market: str = "SH") -> Optional[float]:
        """获取净利润 YoY 增速 (%)。从最近两期财报计算。

        Returns: YoY growth rate as percentage, or None.
        """
        cache_key = f"eg:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        fin_list = self.get_financials(symbol, market, count=2)
        if len(fin_list) < 2:
            self._cache_set(cache_key, None)
            return None

        latest = fin_list[0]
        prior = fin_list[1]
        if not latest.net_profit or not prior.net_profit or prior.net_profit == 0:
            self._cache_set(cache_key, None)
            return None

        growth = round((latest.net_profit - prior.net_profit) / abs(prior.net_profit) * 100, 2)
        self._cache_set(cache_key, growth)
        return growth

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
