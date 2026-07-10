# -*- coding: utf-8 -*-
"""数据聚合层。

提供统一查询接口，封装多源优先级、降级和缓存逻辑。

使用示例:
    agg = DataAggregator()
    quote = agg.get_quote("600519", "SH")  # mootdx/腾讯优先 → mx-data交叉验证 → AKShare 降级
    batch = agg.get_quotes_batch([("600519", "SH"), ("000001", "SZ")])
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.information.speed_monitor import SpeedMonitor
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
        self._cninfo: "CninfoProvider | None" = None  # type: ignore[name-defined]
        self._kuaicha: "KuaichaClient | None" = None  # type: ignore[name-defined]
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=5)
        self.speed_monitor = SpeedMonitor()  # 信息速度优势度量（共享实例）

    @property
    def mootdx(self) -> MootdxTencentProvider:
        """懒加载 mootdx+腾讯适配器。"""
        if self._mootdx is None:
            self._mootdx = MootdxTencentProvider()
        return self._mootdx

    @property
    def guosen(self) -> GuosenProvider | None:
        """懒加载国信适配器。无 API Key 时返回 None。

        缓存实例以避免每次访问重新创建（导致 _exhausted 状态丢失，
        已耗尽的 Key 被反复重试）。用户后续设置 GS_API_KEY 后需
        重启进程或调用 reset() 恢复。
        """
        if self._guosen is None:
            try:
                self._guosen = GuosenProvider()
            except RuntimeError:
                return None
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

    @property
    def cninfo(self) -> "CninfoProvider | None":  # type: ignore[name-defined]
        """懒加载 cninfo 适配器。零鉴权，永远可用。"""
        if self._cninfo is None:
            try:
                from .cninfo import CninfoProvider
                provider = CninfoProvider()
                if provider.health_check():
                    self._cninfo = provider
                else:
                    self._cninfo = provider  # orgId 加载失败也可用（有硬编码回退）
            except Exception:
                self._cninfo = None
        return self._cninfo

    @property
    def kuaicha(self) -> "KuaichaClient | None":  # type: ignore[name-defined]
        """懒加载快查适配器。需要 `kuaicha` CLI 已安装并配置 API key。"""
        if self._kuaicha is None:
            try:
                from .kuaicha import KuaichaClient
                client = KuaichaClient()
                self._kuaicha = client if client.health_check() else None
            except Exception:
                self._kuaicha = None
        return self._kuaicha

    # ------------------------------------------------------------------
    # Loader helpers
    # ------------------------------------------------------------------

    def _walk_quote_chain(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """按 a_share fallback 链获取单只股票行情，并附加 citation。"""
        from src.data.loaders.registry import _ensure_registered
        _ensure_registered()
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
        as_of: str = "",
    ) -> pd.DataFrame:
        """按 a_share fallback 链获取历史 K 线，并附加 citation。
        as_of: 历史回测日期 (YYYY-MM-DD)
        """
        from src.data.loaders.registry import _ensure_registered
        _ensure_registered()
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
            # 传递 as_of 给支持历史回测的 loader
            kwargs = {}
            if as_of:
                kwargs["as_of"] = as_of
            df = loader.get_history(symbol, start_date, end_date, period, **kwargs)
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
        self, symbol: str, market: str = "SH", count: int = 4,
        report_period: str = "",
    ) -> list[Financials]:
        """按 a_share fallback 链获取财务报表。

        主源返回完整数据后短路，不再调用后续付费源。
        仅当关键字段缺失时才尝试后续源补充。
        report_period: 历史回测报告期 (YYYY-MM-DD)
        """
        from src.data.loaders.registry import _ensure_registered
        _ensure_registered()
        primary: list[Financials] = []
        primary_name = ""
        chain = FALLBACK_CHAINS.get("a_share_financials", FALLBACK_CHAINS.get("a_share", []))
        for name in chain:
            loader_cls = LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception:
                continue
            if not loader.is_available():
                continue
            kwargs = {"symbol": symbol, "market": market, "count": count}
            if report_period:
                kwargs["report_period"] = report_period
            fins = loader.get_financials(**kwargs)
            if not fins:
                continue
            citation = make_citation(
                provider=loader.name, field="financials", data_type="financials",
            )
            for fin in fins:
                if fin.citation is None:
                    fin.citation = citation
            if not primary:
                primary = fins
                primary_name = name
            else:
                # 补充源: 仅当主源关键字段缺失时才调用后续源
                if not self._financials_are_complete(primary):
                    self._enrich_financials(primary, fins, primary_name, loader.name)
                else:
                    break  # 主源数据完整，短路后续付费源

            # 短路: 如果当前已是免费源且数据完整，不再尝试付费源
            if self._financials_are_complete(primary) and name in ("akshare", "tencent", "mootdx"):
                break

        return primary

    @staticmethod
    def _financials_are_complete(fins: list[Financials]) -> bool:
        """检查财务报表是否包含所有关键字段。"""
        if not fins:
            return False
        # 检查第一个报告期是否有关键字段
        fin = fins[0]
        key_fields = [fin.revenue, fin.net_profit, fin.roe, fin.eps]
        return all(f is not None for f in key_fields)

    @staticmethod
    def _enrich_financials(
        primary: list[Financials],
        supplement: list[Financials],
        primary_src: str,
        supp_src: str,
    ):
        """用补充源的字段填充/覆盖主源中缺失或可改进的字段。

        akshare (同花顺) 的 ROE/EPS 等来自官方财报，优先于 mootdx 的手工计算值。
        """
        # 报告期格式可能不一致 (2026Q3 vs 2026-09-30)，按季度标准化后匹配
        def _quarter_key(period: str) -> str:
            """标准化报告期为 YYYYQN 格式。"""
            p = str(period).strip()
            if "Q" in p:
                return p  # already YYYYQN
            # date format: 2025-12-31 → 2025Q4
            parts = p.split("-")
            if len(parts) >= 2:
                month = int(parts[1])
                return f"{parts[0]}Q{(month - 1) // 3 + 1}"
            return p

        # 按标准化季度匹配
        supp_by_period = {}
        for f in supplement:
            supp_by_period[_quarter_key(f.report_period)] = f

        enriched_fields = []
        # 取补充源的最新数据作为权威 ROE/EPS（不同源报告期格式可能不一致）
        latest_supp = supplement[0] if supplement else None
        for p in primary:
            # 尝试精确匹配
            key = _quarter_key(p.report_period)
            s = supp_by_period.get(key) or latest_supp

            # akshare 同花顺的 ROE 是官方数据，优先使用
            if s and s.roe is not None:
                if p.roe is None or supp_src in ("akshare", "huatai"):
                    if p.roe is None or abs((p.roe or 0) - (s.roe or 0)) > 0.5:
                        p.roe = s.roe
                        enriched_fields.append("roe")
            if p.eps is None and s and s.eps is not None:
                p.eps = s.eps
                enriched_fields.append("eps")
            if p.operating_cash_flow is None and s and s.operating_cash_flow is not None:
                p.operating_cash_flow = s.operating_cash_flow
                enriched_fields.append("operating_cash_flow")

        if enriched_fields:
            logger.info(
                "财务数据补充: %s → %s 补充了 %s",
                supp_src, primary_src, ", ".join(dict.fromkeys(enriched_fields)),
            )

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票行情。按 registry fallback 链：verified_cache > guosen > mootdx > akshare > tencent。"""
        t0 = self.speed_monitor.time_event("quote_fetch")
        try:
            cache_key = f"quote:{symbol}"
            cached = self._cache_get(cache_key)
            if cached:
                self.speed_monitor.end_event("quote_fetch", t0, source="cache")
                return cached

            q = self._walk_quote_chain(symbol, market)
            if q is not None:
                self._cache_set(cache_key, q)
                self.speed_monitor.end_event("quote_fetch", t0, source=q.source if hasattr(q, 'source') else "aggregator")
                return q
            self.speed_monitor.end_event("quote_fetch", t0, source="none")
            return None
        except Exception:
            self.speed_monitor.end_event("quote_fetch", t0, source="error")
            raise

    def get_quotes_batch(
        self, stocks: list[tuple[str, str]], max_workers: int = 1
    ) -> list[Quote]:
        """批量获取行情。按 registry fallback 链逐源补全，并附加 citation。

        max_workers > 1 时，将剩余标的拆分到多个线程并行查询同一 loader。"""
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

            if max_workers > 1 and len(batch_symbols) > 1:
                chunk_size = max(1, len(batch_symbols) // max_workers)
                chunks = [
                    (
                        batch_symbols[i : i + chunk_size],
                        batch_markets[i : i + chunk_size],
                    )
                    for i in range(0, len(batch_symbols), chunk_size)
                ]
                batch_results: list[Quote] = []
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(loader.get_quotes_batch, c_syms, c_mkts): i
                        for i, (c_syms, c_mkts) in enumerate(chunks)
                    }
                    for fut in as_completed(futures):
                        try:
                            batch_results.extend(fut.result())
                        except Exception:
                            pass
            else:
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
        self, symbol: str, market: str = "SH", count: int = 4,
        report_period: str = "",
    ) -> list[Financials]:
        """获取财务报表。按 registry fallback 链。
        report_period: 历史回测报告期 (YYYY-MM-DD)，只返回 ≤ 该日期的数据
        """
        cache_key = f"fin:{symbol}:{count}:{report_period}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        fins = self._walk_financials_chain(symbol, market, count, report_period=report_period)
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

    # 免费源 (tencent/mootdx) 用频率数字 9=daily, akshare 用 "daily"
    _PERIOD_MAP: dict[str, str] = {"daily": "day", "weekly": "week", "monthly": "month"}

    def get_history(
        self,
        symbol: str,
        start_date: str = "2015-01-01",
        end_date: str = "",
        period: str = "day",
        as_of: str = "",
    ):
        """获取历史K线数据（用于回测）。按 registry fallback 链。
        as_of: 历史回测日期 (YYYY-MM-DD)
        """
        t0 = self.speed_monitor.time_event("history_fetch")
        try:
            if not end_date:
                now = datetime.now()
                if as_of:
                    try:
                        now = datetime.strptime(as_of, "%Y-%m-%d")
                    except ValueError:
                        pass
                end_date = now.strftime("%Y%m%d")
            # 标准化 period: "daily"→"day" 适配免费源 (mootdx/tencent)
            normalized_period = self._PERIOD_MAP.get(period, period)
            result = self._walk_history_chain(symbol, start_date, end_date, normalized_period, as_of=as_of)
            source = result.attrs.get("source_citation", {}).provider if hasattr(result, 'attrs') and not result.empty else "aggregator"
            self.speed_monitor.end_event("history_fetch", t0, source=str(source))
            return result
        except Exception:
            self.speed_monitor.end_event("history_fetch", t0, source="error")
            raise

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
        status["guosen"] = (
            "✅" if (gs is not None and gs.health_check())
            else "❌ (API不可达)" if gs is not None
            else "❌ (无 GS_API_KEY)"
        )
        status["tencent"] = "✅" if self.mootdx.health_check() else "❌ (腾讯 HTTP 不可达)"
        status["mootdx"] = "✅" if self.mootdx.health_check() else "❌ (mootdx TCP 不可达)"
        status["akshare"] = "✅" if self.akshare.health_check() else "❌"
        mx = self.miaoxiang
        status["miaoxiang"] = "✅" if (mx is not None and mx.health_check()) else "❌ (无 MX_APIKEY 或不可用)"
        kc = self.kuaicha
        status["kuaicha"] = "✅" if (kc is not None and kc.health_check()) else "❌ (kuaicha CLI 未安装或无 API key)"
        return status

    # ------------------------------------------------------------------
    # V5: 妙想 Skill 代理方法（带降级链）
    # ------------------------------------------------------------------

    def search_news(self, query: str, max_results: int = 10) -> list[NewsItem]:
        """搜索金融资讯。

        降级链: mx-search → 东财个股新闻 → 东财 7×24 快讯 → []
        """
        # 1. mx-search (主源)
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.search_news(query, max_results)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-search 失败: %s", e)

        # 2. 东财个股新闻 (降级)
        try:
            from .eastmoney_fallback import fetch_em_stock_news
            raw = fetch_em_stock_news(query, max_results)
            if raw:
                items = []
                for entry in raw:
                    items.append(NewsItem(
                        title=entry.get("title", ""),
                        source=entry.get("source", "eastmoney-news"),
                        date=entry.get("time", ""),
                        content=entry.get("content", ""),
                        url=entry.get("url", ""),
                        provider="eastmoney-news",
                    ))
                if items:
                    return items
        except Exception as e:
            logger.debug("东财个股新闻降级失败: %s", e)

        # 3. 东财 7×24 快讯 (更深降级)
        try:
            from .eastmoney_fallback import fetch_em_global_news
            raw = fetch_em_global_news(max_results * 2)
            if raw:
                filtered = self._filter_news_by_keyword(raw, query)
                items = []
                for entry in filtered[:max_results]:
                    items.append(NewsItem(
                        title=entry.get("title", ""),
                        source=entry.get("source", "eastmoney-global"),
                        date=entry.get("time", ""),
                        content=entry.get("summary", ""),
                        url=entry.get("url", ""),
                        provider="eastmoney-global",
                    ))
                if items:
                    return items
        except Exception as e:
            logger.debug("东财全球资讯降级失败: %s", e)

        return []

    def search_announcements(self, symbol: str) -> list[NewsItem]:
        """搜索个股公告。

        降级链: mx-search → 巨潮 cninfo → []
        """
        # 1. mx-search
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.search_announcements(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-search 公告失败: %s", e)

        # 2. 巨潮 cninfo (降级)
        cninfo = self.cninfo
        if cninfo is not None:
            try:
                raw = cninfo.search_announcements(symbol)
                if raw:
                    items = []
                    for entry in raw:
                        items.append(NewsItem(
                            title=entry.get("title", ""),
                            source="cninfo",
                            date=entry.get("date", ""),
                            content=entry.get("type", ""),
                            url=entry.get("url", ""),
                            provider="cninfo",
                        ))
                    if items:
                        return items
            except Exception as e:
                logger.debug("巨潮公告降级失败 (%s): %s", symbol, e)

        return []

    def search_research_reports(self, symbol: str) -> list[NewsItem]:
        """搜索个股研报。

        降级链: mx-search → 东财 reportapi → []
        """
        # 1. mx-search
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.search_research_reports(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-search 研报失败: %s", e)

        # 2. 东财 reportapi (降级)
        try:
            from .eastmoney_fallback import fetch_em_research_reports
            raw = fetch_em_research_reports(symbol)
            if raw:
                items = []
                for entry in raw:
                    content_parts = []
                    if entry.get("org"):
                        content_parts.append(f"机构: {entry['org']}")
                    if entry.get("rating"):
                        content_parts.append(f"评级: {entry['rating']}")
                    if entry.get("eps_cur"):
                        content_parts.append(f"今年EPS: {entry['eps_cur']}")
                    if entry.get("eps_next"):
                        content_parts.append(f"明年EPS: {entry['eps_next']}")
                    items.append(NewsItem(
                        title=entry.get("title", ""),
                        source=entry.get("org", "eastmoney-report"),
                        date=entry.get("date", ""),
                        content="; ".join(content_parts),
                        url=f"https://pdf.dfcfw.com/pdf/H3_{entry.get('info_code', '')}_1.pdf",
                        provider="eastmoney-report",
                    ))
                if items:
                    return items
        except Exception as e:
            logger.debug("东财研报降级失败 (%s): %s", symbol, e)

        return []

    def get_related_parties(self, symbol: str) -> list[RelatedParty]:
        """获取个股关联方。

        降级链: mx-data → cninfo 关联交易公告提取 → [DATA_GAP]
        """
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.get_related_parties(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-data 关联方失败: %s", e)

        # 降级: cninfo 关联交易公告提取
        items = self._extract_related_parties_from_cninfo(symbol)
        if items:
            return items

        logger.info("[DATA_GAP] get_related_parties(%s): 妙想不可用，cninfo 也未提取到关联方", symbol)
        return []

    def get_executive_trades(self, symbol: str) -> list[ExecutiveTrade]:
        """获取高管增减持。

        降级链: mx-data → 东财 datacenter RPT_EXECUTIVE_TRADE → []
        """
        # 1. mx-data
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.get_executive_trades(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-data 高管交易失败: %s", e)

        # 2. 东财 datacenter (降级)
        try:
            from .eastmoney_fallback import fetch_em_executive_trades
            raw = fetch_em_executive_trades(symbol)
            if raw:
                items = []
                for entry in raw:
                    items.append(ExecutiveTrade(
                        executive_name=entry.get("name", ""),
                        position=entry.get("position", ""),
                        trade_type=entry.get("trade_type", "buy"),
                        trade_date=entry.get("date", ""),
                        volume=entry.get("volume"),
                        price=entry.get("price"),
                        total_value=entry.get("total_value"),
                        change_after_trade_pct=entry.get("change_pct"),
                        provider="eastmoney",
                    ))
                if items:
                    return items
        except Exception as e:
            logger.debug("东财高管交易降级失败 (%s): %s", symbol, e)

        return []

    def get_executive_profiles(self, symbol: str) -> list[ExecutiveProfile]:
        """获取高管背景履历。

        降级链: mx-data → cninfo 高管公告提取 → [DATA_GAP]
        """
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.get_executive_profiles(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-data 高管履历失败: %s", e)

        # 2. 快查 (iwencai 董监高 + listed 结构数据)
        kc = self.kuaicha
        if kc is not None:
            try:
                execs = kc.get_executives(creditcode=symbol)
                if execs:
                    items = []
                    for entry in execs:
                        items.append(ExecutiveProfile(
                            name=entry.get("姓名", entry.get("name", "")),
                            position=entry.get("职务", entry.get("position", "")),
                            age=None,
                            education=str(entry.get("学历", "")),
                            background=f"快查企业数据引擎 — {entry.get('任职起始日期', '')}",
                            tenure_start=entry.get("任职起始日期", ""),
                            provider="kuaicha",
                        ))
                    if items:
                        return items
            except Exception as e:
                logger.debug("kuaicha 高管查询失败 (%s): %s", symbol, e)

        # 降级: cninfo 高管/董事公告提取
        items = self._extract_executive_profiles_from_cninfo(symbol)
        if items:
            return items

        logger.info("[DATA_GAP] get_executive_profiles(%s): 妙想不可用，cninfo 也未提取到高管信息", symbol)
        return []

    def get_board_changes(self, symbol: str) -> list[BoardChange]:
        """获取董监高变动。

        降级链: mx-data → 巨潮 cninfo 公告搜索 → []
        """
        # 1. mx-data
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.get_board_changes(symbol)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-data 董事会变更失败: %s", e)

        # 2. 巨潮 cninfo (降级) — 搜索董监高相关公告
        cninfo = self.cninfo
        if cninfo is not None:
            try:
                # 搜索董事/监事/高管变动公告
                raw = cninfo.search_announcements(symbol)
                if raw:
                    items = []
                    board_keywords = ["董事", "监事", "高管", "总裁", "副总裁", "总经理",
                                      "董秘", "辞职", "聘任", "选举", "任命", "变更"]
                    for entry in raw:
                        title = entry.get("title", "")
                        if any(kw in title for kw in board_keywords):
                            items.append(BoardChange(
                                person_name="",  # 公告标题通常不包含具体人名
                                old_position="",
                                new_position="",
                                change_date=entry.get("date", ""),
                                reason=title[:200],
                                provider="cninfo",
                            ))
                    if items:
                        return items
            except Exception as e:
                logger.debug("巨潮董事会变更降级失败 (%s): %s", symbol, e)

        return []

    def screen_stocks(self, conditions: str) -> list[ScreeningResult]:
        """条件选股。

        降级链: mx-xuangu → AKShare 全扫描 + 客户端字段过滤 → []
        """
        # 1. mx-xuangu
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                results = mx.screen_stocks(conditions)
                if results:
                    return results
            except Exception as e:
                logger.debug("mx-xuangu 失败: %s", e)

        # 2. AKShare 全市场扫描 + 客户端条件过滤
        try:
            from .akshare import AKShareProvider
            ak = AKShareProvider()
            if ak.health_check():
                all_quotes = ak.get_all_quotes()
                if all_quotes:
                    filtered = self._apply_client_filter(all_quotes, conditions)
                    if filtered:
                        return filtered
        except Exception as e:
            logger.debug("AKShare 选股降级失败: %s", e)

        return []

    def screen_by_industry(self, industry: str) -> list[ScreeningResult]:
        """按行业筛选。

        降级链: mx-xuangu → 东财 push2 行业成分股 → []
        """
        # 1. mx-xuangu
        mx = self.miaoxiang
        if mx is not None and not mx.is_exhausted():
            try:
                result = mx.screen_by_industry(industry)
                if result:
                    return result
            except Exception as e:
                logger.debug("mx-xuangu 行业筛选失败: %s", e)

        # 2. 东财 push2 行业成分股 (降级)
        try:
            from .eastmoney_fallback import fetch_em_industry_stocks
            raw = fetch_em_industry_stocks(industry)
            if raw:
                items = []
                for entry in raw:
                    items.append(ScreeningResult(
                        symbol=entry.get("code", ""),
                        name=entry.get("name", ""),
                        market="A股",
                        price=_safe_float_single(entry.get("price")),
                        change_pct=_safe_float_single(entry.get("change_pct")),
                        pe_ttm=_safe_float_single(entry.get("pe")),
                    ))
                if items:
                    return items
        except Exception as e:
            logger.debug("东财行业成分股降级失败 (%s): %s", industry, e)

        return []

    def get_cross_validated_quote(self, symbol: str, market: str = "SH") -> tuple[Optional[Quote], bool, bool]:
        """双源交叉验证行情。

        Returns:
            (quote, cross_validated, dispute)
            - cross_validated: ≥2 源成功返回
            - dispute: 两源价格差异 > 5%

        mx (妙想) 仅在不耗尽时用于交叉验证；已耗尽则跳过避免浪费配额。
        """
        q1 = self.get_quote(symbol, market)  # 免费源优先 (主力)

        # mx 交叉验证：仅在未耗尽时尝试
        mx = self.miaoxiang
        q2: Optional[Quote] = None
        if mx is not None and not mx.is_exhausted():
            try:
                q2 = mx.get_quote(symbol, market)
            except Exception:
                pass

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
            logger.debug("Industry PE/PB (AKShare) fetch failed for %s", symbol, exc_info=True)
            # 降级: 东财 push2
            try:
                from .eastmoney_fallback import fetch_em_industry_pe_pb
                em_result = fetch_em_industry_pe_pb()
                if em_result[0] is not None or em_result[1] is not None:
                    self._cache_set(cache_key, em_result)
                    return em_result
            except Exception as e2:
                logger.debug("Industry PE/PB (EastMoney) fallback failed: %s", e2)
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
            logger.debug("Dividend data (AKShare) fetch failed for %s", symbol, exc_info=True)
            # 降级: 东财 datacenter 分红
            try:
                from .eastmoney_fallback import fetch_em_dividend
                raw = fetch_em_dividend(symbol)
                if raw:
                    # 取最近一期每股派息作为股息率估算
                    latest = raw[0]
                    bonus = latest.get("bonus_rmb", 0)
                    if bonus and bonus > 0:
                        # 需要配合当前股价算股息率
                        quote = self.get_quote(symbol)
                        if quote and quote.price:
                            result = round(float(bonus) / float(quote.price) * 100, 2)
                            self._cache_set(cache_key, result)
                            return result
            except Exception as e2:
                logger.debug("Dividend (EastMoney) fallback failed: %s", e2)
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
    # cninfo 高管 / 关联方提取 (mx-data 降级)
    # ------------------------------------------------------------------

    def _extract_executive_profiles_from_cninfo(self, symbol: str) -> list[ExecutiveProfile]:
        """从 cninfo 公告中提取高管姓名和职务。

        搜索董监高相关公告标题，用正则提取中文姓名 + 职务关键词。
        """
        import re
        cninfo = self.cninfo
        if cninfo is None:
            return []
        try:
            raw = cninfo.search_announcements(symbol, page_size=50)
            if not raw:
                return []
        except Exception as e:
            logger.debug("cninfo 高管搜索失败 (%s): %s", symbol, e)
            return []

        # 职务关键词 → 标准化职位名
        POSITION_MAP: dict[str, str] = {
            "董事长": "董事长", "副董事长": "副董事长",
            "总裁": "总裁", "副总裁": "副总裁",
            "总经理": "总经理", "副总经理": "副总经理",
            "独立董事": "独立董事", "非独立董事": "董事",
            "职工代表董事": "职工董事", "执行董事": "执行董事",
            "董事会秘书": "董秘", "董秘": "董秘",
            "财务总监": "财务总监", "财务负责人": "财务负责人",
            "技术总监": "技术总监", "运营总监": "运营总监",
            "监事": "监事", "监事会主席": "监事会主席",
            "首席": "高管",  # 首席XX官
        }

        seen: set[str] = set()
        profiles: list[ExecutiveProfile] = []

        board_keywords = ["董事", "监事", "高管", "总裁", "副总裁", "总经理",
                          "副总经理", "董秘", "首席", "总监", "选举", "聘任",
                          "任命", "辞职", "述职"]

        # 非人名词汇 (会被正则误匹配)
        NON_NAME: set[str] = {
            "有限公司", "股份有限", "集团", "科技", "控股", "实业",
            "合伙企业", "投资基金", "本公司", "年度", "公告", "关于",
            "及其子", "预计", "日常", "新增", "提供担保", "资金占用",
            "董事会", "监事会", "第一次", "第二次", "第三次", "第四届",
            "第五届", "第六届", "第七届", "第八届", "第九届", "第十届",
            "管理制度", "报告", "业务的", "披露的", "的公告", "候选人",
            "提名人", "事项的", "信息的", "于选举", "司部分", "于完成",
            "于授权", "选举并", "事关鑫",
        }

        for entry in raw:
            title = entry.get("title", "")
            if not any(kw in title for kw in board_keywords):
                continue

            names: list[tuple[str, str]] = []  # [(name, position_hint)]

            # 模式1: 职务前缀 + 姓名 (如 "独立董事王爱国")
            for prefix, pos_hint in POSITION_MAP.items():
                prefix_matches = re.finditer(
                    rf"{prefix}([一-鿿]{{2,3}})(?:女士|先生|(?:\d{{4}}年度))",
                    title
                )
                for m in prefix_matches:
                    names.append((m.group(1), pos_hint))

            # 模式2: "姓名+年度述职/工作报告" (如 "王爱国2025年度述职报告")
            # 需要先找，避免被模式1错误匹配
            report_matches = re.finditer(
                r"([一-鿿]{2,3})\d{4}年度(?:述职|工作)报告",
                title
            )
            for m in report_matches:
                pos = "独立董事" if "独立董事" in title else "高管"
                names.append((m.group(1), pos))

            # 模式3: 姓名在括号中 (如 "候选人声明与承诺（张敏）")
            paren_matches = re.finditer(r"[（(]([一-鿿]{2,3})[）)]", title)
            for m in paren_matches:
                name = m.group(1)
                pos = "高管"
                for kw, std_pos in sorted(POSITION_MAP.items(), key=lambda x: -len(x[0])):
                    if kw in title:
                        pos = std_pos
                        break
                # 排除重复：忽略跟在"候选人""提名人"后面立即出现的括号内名字
                # （这些会在模式1/2中通过职务+姓名捕获）
                prefix = title[max(0, m.start()-10):m.start()]
                if "候选人" in prefix or "提名人" in prefix:
                    # 检查是否已被模式1/2捕获
                    already = any(n == name for n, _ in names)
                    if not already:
                        names.append((name, pos))
                else:
                    names.append((name, pos))

            for name, pos_hint in names:
                if name in NON_NAME:
                    continue
                # 简单的姓氏校验: 至少第一个字符应该是常见姓氏
                if len(name) >= 2 and name[0] in ("有限", "股份", "关于", "及其", "第一",
                                                   "第二", "第三", "第四", "第五", "第六",
                                                   "第七", "第八", "第九", "第十", "董事",
                                                   "监事", "高管", "首席", "信息", "技术",
                                                   "提供", "预计", "新增", "管理", "业务",
                                                   "披露", "事项", "候选", "提名", "选举"):
                    continue
                if name in seen:
                    continue

                # 确定最终职务
                position = pos_hint if pos_hint != "高管" else "高管"
                for kw, std_pos in sorted(POSITION_MAP.items(), key=lambda x: -len(x[0])):
                    if kw in title:
                        position = std_pos
                        break

                seen.add(name)
                profiles.append(ExecutiveProfile(
                    name=name,
                    position=position,
                    age=None,
                    education="",
                    background=f"来源: cninfo 公告 — {title[:80]}",
                    tenure_start=entry.get("date", ""),
                    provider="cninfo",
                ))

        return profiles

    def _extract_related_parties_from_cninfo(self, symbol: str) -> list[RelatedParty]:
        """从 cninfo 关联交易公告中提取关联方名称。

        搜索「关联交易」「关联方」公告，从标题中提取关联实体名称。
        """
        import re
        cninfo = self.cninfo
        if cninfo is None:
            return []
        try:
            raw = cninfo.search_announcements(symbol, keyword="关联")
            if not raw:
                return []
        except Exception as e:
            logger.debug("cninfo 关联方搜索失败 (%s): %s", symbol, e)
            return []

        seen: set[str] = set()
        parties: list[RelatedParty] = []

        # 匹配「为XXX提供担保」「与XXX的关联交易」「向XXX转让」等模式
        entity_patterns: list[str] = [
            r"为([一-鿿（）()\w]{4,40}?(?:公司|企业|集团|中心|合伙|基金|科技))(?:及其子(?:公司)?)?提供",
            r"与([一-鿿（）()\w]{4,40}?(?:公司|企业|集团|中心|合伙|基金|科技))(?:及其子公司)?[的之]?(?:关联|日常)",
            r"向([一-鿿（）()\w]{4,40}?(?:公司|企业|集团|中心|合伙|基金|科技))(?:及其子(?:公司)?)?(?:转让|出售|购买|收购|增资|投资)",
            r"受让[方自]*?([一-鿿（）()\w]{4,20}公司)",
            r"转让[给至].*?([一-鿿（）()\w]{4,20}(?:公司|企业))",
        ]

        SKIP_ENTITIES: set[str] = {
            "本公司", "上市公司", "标的公司", "目标公司", "控股子公司",
            "全资子公司", "参股公司",
        }

        for entry in raw:
            # 去除 cninfo HTML 标签 (如 <em>)
            title = re.sub(r"<[^>]+>", "", entry.get("title", ""))
            if "关联" not in title:
                continue

            for pattern in entity_patterns:
                for m in re.finditer(pattern, title):
                    entity = m.group(1).strip("（）()")
                    if len(entity) < 4 or entity in seen or entity in SKIP_ENTITIES:
                        continue

                    seen.add(entity)
                    parties.append(RelatedParty(
                        entity_name=entity,
                        relation_type="关联交易",
                        stake_pct=None,
                        position="",
                        description=f"来源: cninfo 公告 — {title[:120]}",
                        provider="cninfo",
                    ))

        return parties

    # ------------------------------------------------------------------
    # 降级辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float_single(v) -> Optional[float]:
        """安全转换单个值为 float。"""
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _filter_news_by_keyword(raw_news: list[dict], query: str) -> list[dict]:
        """从快讯列表中按关键词过滤匹配条目。"""
        keywords = [w.strip() for w in query.split() if len(w.strip()) >= 2]
        if not keywords:
            return raw_news[:10]
        filtered = []
        for entry in raw_news:
            text = entry.get("title", "") + " " + entry.get("summary", "")
            if any(kw in text for kw in keywords):
                filtered.append(entry)
        return filtered[:20] if filtered else raw_news[:5]

    @staticmethod
    def _apply_client_filter(
        quotes: list, conditions: str
    ) -> list:
        """客户端条件过滤（AKShare 全扫描降级）。

        支持的条件格式:
          - pe<30, pe_ttm<15, 市盈率<20
          - 市值>100亿, mcap>10000000000
          - 涨跌幅>3, change_pct>5
          - pb<2, 市净率<3
        """
        from .schema import ScreeningResult

        conds = conditions.lower().replace(" ", "")
        filtered = []

        for q in quotes:
            # 提取字段值 (Quote 是 dataclass 或 dict)
            if isinstance(q, dict):
                name = q.get("name", "")
                code = q.get("symbol", "")
                price = q.get("price")
                pe = q.get("pe_ttm")
                pb = q.get("pb")
                mcap = q.get("mcap_yi")
                change_pct = q.get("change_pct")
            else:
                name = getattr(q, "name", "")
                code = getattr(q, "symbol", "")
                price = getattr(q, "price", None)
                pe = getattr(q, "pe_ttm", None)
                pb = getattr(q, "pb", None)
                mcap_val = getattr(q, "mcap_yi", None)
                # mcap_yi 单位是亿，转换为元的数量级进行比较
                mcap = mcap_val
                change_pct = getattr(q, "change_pct", None)

            # 简单条件匹配
            match = True

            # PE 条件
            import re as _re
            pe_match = _re.search(r"pe[_a-z]*?<(\d+\.?\d*)", conds)
            if pe_match and pe is not None:
                try:
                    if float(pe) >= float(pe_match.group(1)):
                        match = False
                except (ValueError, TypeError):
                    pass

            pe_gt = _re.search(r"pe[_a-z]*?>(\d+\.?\d*)", conds)
            if pe_gt and pe is not None:
                try:
                    if float(pe) <= float(pe_gt.group(1)):
                        match = False
                except (ValueError, TypeError):
                    pass

            # PB 条件
            pb_match = _re.search(r"pb[_a-z]*?<(\d+\.?\d*)", conds)
            if pb_match and pb is not None:
                try:
                    if float(pb) >= float(pb_match.group(1)):
                        match = False
                except (ValueError, TypeError):
                    pass

            # 市值条件 (亿)
            mcap_gt = _re.search(r"(?:市值|mcap)[_a-z]*?>(\d+\.?\d*)", conds)
            if mcap_gt and mcap is not None:
                try:
                    target = float(mcap_gt.group(1))
                    # mcap 单位是亿
                    if float(mcap) <= target:
                        match = False
                except (ValueError, TypeError):
                    pass

            # 涨跌幅条件
            chg_match = _re.search(r"(?:涨跌幅|change_pct|涨幅)[_a-z]*?>(\d+\.?\d*)", conds)
            if chg_match and change_pct is not None:
                try:
                    if float(change_pct) <= float(chg_match.group(1)):
                        match = False
                except (ValueError, TypeError):
                    pass

            if match:
                filtered.append(ScreeningResult(
                    symbol=code,
                    name=name,
                    market="A股",
                    price=float(price) if price else None,
                    change_pct=float(change_pct) if change_pct is not None else None,
                    pe_ttm=float(pe) if pe else None,
                    provider="akshare-screen",
                ))

            if len(filtered) >= 50:
                break

        return filtered

    # ------------------------------------------------------------------
    # V6: 快查 (Kuaicha) 数据补充方法
    # ------------------------------------------------------------------

    def get_kuaicha_top_holders(
        self, symbol: str, orgid: str = ""
    ) -> list[dict]:
        """获取十大股东（快查 listed 源）。

        优先用 orgid，否则用 symbol 模糊匹配。
        """
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_holders:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_top_holders(orgid=orgid, creditcode=symbol if not orgid else "")
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_executives(
        self, symbol: str, orgid: str = ""
    ) -> list[dict]:
        """获取董监高信息（快查 listed 源）。"""
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_exec:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_executives(
            orgid=orgid, creditcode=symbol if not orgid else ""
        )
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_audit_opinion(
        self, symbol: str, orgid: str = ""
    ) -> list[dict]:
        """获取审计意见（快查 listed 源）。"""
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_audit:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_audit_opinion(
            orgid=orgid, creditcode=symbol if not orgid else ""
        )
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_income_statement(
        self, symbol: str, orgid: str = ""
    ) -> list:
        """获取利润表（快查 listed 源，标准化 DTO）。"""
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_is:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_income_statement(
            orgid=orgid, creditcode=symbol if not orgid else "",
            page_size=4,
        )
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_balance_sheet(
        self, symbol: str, orgid: str = ""
    ) -> list:
        """获取资产负债表（快查 listed 源，标准化 DTO）。"""
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_bs:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_balance_sheet(
            orgid=orgid, creditcode=symbol if not orgid else "",
            page_size=4,
        )
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_cash_flow(
        self, symbol: str, orgid: str = ""
    ) -> list:
        """获取现金流量表（快查 listed 源，标准化 DTO）。"""
        kc = self.kuaicha
        if kc is None:
            return []
        cache_key = f"kc_cf:{symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=24))
        if cached is not None:
            return cached

        result = kc.get_cash_flow(
            orgid=orgid, creditcode=symbol if not orgid else "",
            page_size=4,
        )
        self._cache_set(cache_key, result)
        return result

    def get_kuaicha_institution_research(
        self, name_or_symbol: str,
    ) -> dict | None:
        """获取机构调研与评级（快查 iwencai 源）。

        Note: iwencai 工具当前有 CLI bug，可能返回空。
        降级后可改用 listed 的研报相关工具。
        """
        kc = self.kuaicha
        if kc is None:
            return None
        cache_key = f"kc_ir:{name_or_symbol}"
        cached = self._cache_get(cache_key, ttl=timedelta(hours=6))
        if cached is not None:
            return cached

        result = kc.institution_research(name_or_symbol)
        data = result.raw_data if result else []
        self._cache_set(cache_key, data)
        return data

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
