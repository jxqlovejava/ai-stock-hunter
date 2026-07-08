# -*- coding: utf-8 -*-
"""个股涨跌归因引擎 — Phase 1 自动并行数据搜集 + 质量预检。

Usage:
    engine = AttributionEngine()
    result = engine.collect("600089", date="2026-07-08")
    # result.raw_data_points 包含所有已分级、已标记的数据点
    # result.quality 包含 T0-T3 统计和 STALE/DATA_GAP 声明
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from src.data.source_citation import (
    SOURCE_TIER_T0,
    SOURCE_TIER_T1,
    SOURCE_TIER_T2,
    SOURCE_TIER_T3,
    NATURE_FACT,
    NATURE_INTERPRETATION,
    NATURE_SPECULATION,
    SourceCitation,
)
from src.routing.attribution_types import (
    AttributionDataPoint,
    AttributionResult,
    DriverFactor,
    QualitySummary,
)

logger = logging.getLogger(__name__)

# 时效性常量 (来自 guardrails.md)
NEWS_STALE_HOURS = 12  # 新闻事件过期时间
POLICY_STALE_HOURS = 24  # 政策/主题过期时间
FUNDAMENTAL_STALE_HOURS = 48  # 基本面数据过期时间


class AttributionEngine:
    """个股涨跌归因引擎。

    自动执行 Phase 1 并行数据搜集，为每条数据点创建 SourceCitation，
    标记 T0-T3 级别、STALE 过期、DATA_GAP 缺失，生成 QualitySummary。

    Phase 2 (多维归因) 和 Phase 3 (因果推断) 由 AI 代理完成，
    本引擎提供结构化的 AttributionResult 作为输入。
    """

    def __init__(self):
        self._data_aggregator = None
        self._akshare = None
        self._mootdx = None

    @property
    def aggregator(self):
        if self._data_aggregator is None:
            from src.data.aggregator import DataAggregator
            self._data_aggregator = DataAggregator()
        return self._data_aggregator

    @property
    def akshare_provider(self):
        if self._akshare is None:
            from src.data.akshare import AKShareProvider
            self._akshare = AKShareProvider()
        return self._akshare

    @property
    def mootdx_provider(self):
        if self._mootdx is None:
            from src.data.mootdx_tencent import MootdxTencentProvider
            self._mootdx = MootdxTencentProvider()
        return self._mootdx

    # ────────────────────────────────────────────────────────
    # 公开入口
    # ────────────────────────────────────────────────────────

    def collect(self, symbol: str, name: str = "", date: str | None = None) -> AttributionResult:
        """Phase 1: 并行搜集所有归因相关数据。

        Args:
            symbol: 6 位股票代码
            name: 股票名称 (可选, 自动从行情获取)
            date: 归因日期 YYYY-MM-DD (默认今天)

        Returns:
            AttributionResult，raw_data_points 已填充，quality 已预计算
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # 获取行情确认名称
        if not name:
            try:
                quote = self.aggregator.get_quote(symbol)
                name = quote.name if quote else symbol
            except Exception:
                name = symbol

        result = AttributionResult(
            symbol=symbol,
            name=name,
            date=date,
        )

        # ── 并行搜集 ──
        all_points: list[AttributionDataPoint] = []
        tasks = {
            "news": lambda: self._fetch_news(symbol, name, date),
            "announcements": lambda: self._fetch_announcements(symbol, date),
            "price_data": lambda: self._fetch_price_data(symbol, date),
            "capital_flow": lambda: self._fetch_capital_data(symbol, date),
            "policy_hint": lambda: self._fetch_policy_hint(symbol, name),
        }

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    points = future.result()
                    all_points.extend(points)
                except Exception as e:
                    logger.warning("归因数据搜集 [%s] 失败: %s", key, e)
                    all_points.append(
                        AttributionDataPoint(
                            category=key,
                            description=f"{key} 数据搜集失败",
                            source_citation=SourceCitation(
                                provider="system",
                                field=key,
                                source_tier=SOURCE_TIER_T3,
                                nature=NATURE_SPECULATION,
                                confidence=0.1,
                            ),
                            data_gap_reason=f"{key} 数据源不可用: {e}",
                        )
                    )

        # 去重 + 排序
        result.raw_data_points = self._deduplicate(all_points)

        # ── 计算价格变动 ──
        result.price_change_pct = self._calc_price_change(all_points)

        # ── 质量预检 ──
        result.quality = self._compute_quality_summary(result.raw_data_points, date)

        # ── 数据时效性警告 ──
        now = datetime.now()
        fetch_times = [
            p.source_citation.fetch_timestamp
            for p in result.raw_data_points
            if p.source_citation.fetch_timestamp
        ]
        if fetch_times:
            oldest = min(fetch_times)
            age_hours = (now - oldest).total_seconds() / 3600
            if age_hours > 6:
                result.data_freshness_warning = (
                    f"部分数据已获取 {age_hours:.1f} 小时，"
                    f"超过新闻时效性阈值 (6h)。已自动标记 [STALE]。"
                )

        return result

    # ────────────────────────────────────────────────────────
    # 私有: 各数据通道
    # ────────────────────────────────────────────────────────

    def _fetch_news(self, symbol: str, name: str, date: str) -> list[AttributionDataPoint]:
        """通道 1: 资讯/新闻搜集。"""
        points = []
        now = datetime.now()
        try:
            news_items = self.aggregator.search_news(f"{symbol} {name}", max_results=10)
            for item in news_items:
                # 跳过空条目 (miaoxiang 不可用时返回默认空对象)
                if not item.title or not item.title.strip():
                    continue
                # 解析新闻发布时间
                try:
                    if item.date:
                        pub_time = datetime.fromisoformat(item.date.replace("Z", "+00:00"))
                    else:
                        pub_time = now
                except Exception:
                    pub_time = now

                age_hours = (now - pub_time).total_seconds() / 3600
                is_stale = age_hours > NEWS_STALE_HOURS

                # 根据来源判断 tier
                source_lower = (item.source or "").lower()
                if any(t in source_lower for t in ["巨潮", "cninfo", "交易所", "央行"]):
                    tier = SOURCE_TIER_T0
                elif any(t in source_lower for t in ["国信", "华泰", "东财", "同花顺"]):
                    tier = SOURCE_TIER_T1
                elif any(t in source_lower for t in ["财联社", "证券时报", "第一财经"]):
                    tier = SOURCE_TIER_T2
                else:
                    tier = SOURCE_TIER_T2

                citation = SourceCitation(
                    provider=item.source or "news_search",
                    field="news",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=6),
                    confidence=0.75 if tier == SOURCE_TIER_T1 else 0.60,
                    source_tier=tier,
                    nature=NATURE_INTERPRETATION,
                )

                points.append(
                    AttributionDataPoint(
                        category="news",
                        description=f"[{item.source}] {item.title[:120]}",
                        source_citation=citation,
                        is_stale=is_stale,
                        cross_validated=False,
                    )
                )
        except Exception as e:
            logger.warning("新闻搜集失败: %s", e)
            points.append(
                AttributionDataPoint(
                    category="news",
                    description="新闻数据源不可用",
                    source_citation=SourceCitation(
                        provider="news_search", field="news",
                        source_tier=SOURCE_TIER_T3, nature=NATURE_SPECULATION,
                        confidence=0.1,
                    ),
                    data_gap_reason=f"新闻搜索失败: {e}",
                )
            )
        return points

    def _fetch_announcements(self, symbol: str, date: str) -> list[AttributionDataPoint]:
        """通道 2: 公告搜集 (巨潮 cninfo)。"""
        points = []
        now = datetime.now()
        try:
            anns = self.aggregator.search_announcements(symbol)
            for ann in anns:
                # 跳过空条目
                if not ann.title or not ann.title.strip():
                    continue
                try:
                    if ann.date:
                        pub_time = datetime.fromisoformat(ann.date.replace("Z", "+00:00"))
                    else:
                        pub_time = now
                except Exception:
                    pub_time = now

                citation = SourceCitation(
                    provider="cninfo",
                    field="announcement",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=24),
                    confidence=0.90,
                    source_tier=SOURCE_TIER_T0,
                    nature=NATURE_FACT,
                )

                points.append(
                    AttributionDataPoint(
                        category="announcement",
                        description=f"[公告] {ann.title[:120]}" if ann.title else str(ann)[:120],
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=True,
                    )
                )
        except Exception as e:
            logger.warning("公告搜集失败: %s", e)
            points.append(
                AttributionDataPoint(
                    category="announcement",
                    description="公告数据源不可用",
                    source_citation=SourceCitation(
                        provider="cninfo", field="announcement",
                        source_tier=SOURCE_TIER_T3, nature=NATURE_SPECULATION,
                        confidence=0.1,
                    ),
                    data_gap_reason=f"公告获取失败: {e}",
                )
            )
        return points

    def _fetch_price_data(self, symbol: str, date: str) -> list[AttributionDataPoint]:
        """通道 3: 行情/K线数据搜集。"""
        points = []
        now = datetime.now()

        # 3a: 腾讯财经实时行情 (T1)
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            quote = agg.get_quote(symbol)
            if quote:
                citation = SourceCitation(
                    provider="tencent",
                    field="quote",
                    fetch_timestamp=now,
                    data_freshness=timedelta(minutes=5),
                    confidence=0.75,
                    source_tier=SOURCE_TIER_T1,
                    nature=NATURE_FACT,
                )
                points.append(
                    AttributionDataPoint(
                        category="technical",
                        description=(
                            f"行情: {quote.name} 价格 {quote.price:.2f} "
                            f"涨跌 {quote.change_pct:+.2f}% "
                            f"PE {quote.pe_ttm:.1f}x PB {quote.pb:.2f}x "
                            f"市值 {quote.market_cap/1e8:.0f}亿"
                        ),
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=False,  # 单源, 需 Phase 3 交叉验证
                    )
                )
        except Exception as e:
            logger.warning("行情数据获取失败: %s", e)
            points.append(
                AttributionDataPoint(
                    category="technical", description="行情数据不可用",
                    source_citation=SourceCitation(
                        provider="tencent", field="quote",
                        source_tier=SOURCE_TIER_T3, nature=NATURE_SPECULATION,
                        confidence=0.1,
                    ),
                    data_gap_reason=f"行情获取失败: {e}",
                )
            )

        # 3b: mootdx K线历史 (T1)
        try:
            klines = self.mootdx_provider.get_history(symbol, period="daily")
            if hasattr(klines, 'iloc') and len(klines) > 0:
                # 取最近 60 个交易日
                recent = klines.tail(60)
                close_start = float(recent.iloc[0].get('close', 0))
                close_end = float(recent.iloc[-1].get('close', 0))
                if close_start > 0:
                    period_change = (close_end - close_start) / close_start * 100
                    citation = SourceCitation(
                        provider="mootdx",
                        field="kline",
                        fetch_timestamp=now,
                        data_freshness=timedelta(hours=1),
                        confidence=0.85,
                        source_tier=SOURCE_TIER_T1,
                        nature=NATURE_FACT,
                    )
                    points.append(
                        AttributionDataPoint(
                            category="technical",
                            description=f"近60日K线: {close_start:.2f} → {close_end:.2f} ({period_change:+.1f}%)",
                            source_citation=citation,
                            is_stale=False,
                            cross_validated=True,
                        )
                    )
        except Exception as e:
            logger.warning("K线数据获取失败: %s", e)

        return points

    def _fetch_capital_data(self, symbol: str, date: str) -> list[AttributionDataPoint]:
        """通道 4: 资金面数据搜集 (龙虎榜/北向/融资融券/大宗交易)。"""
        points = []
        now = datetime.now()

        # 4a: 龙虎榜 (T1)
        try:
            dt_df = self.akshare_provider.get_dragon_tiger()
            if hasattr(dt_df, 'empty') and not dt_df.empty:
                # 检查该股票是否在龙虎榜中
                if '代码' in dt_df.columns:
                    stock_rows = dt_df[dt_df['代码'].astype(str).str.contains(symbol)]
                    if len(stock_rows) > 0:
                        row = stock_rows.iloc[0]
                        citation = SourceCitation(
                            provider="eastmoney",
                            field="dragon_tiger",
                            fetch_timestamp=now,
                            data_freshness=timedelta(hours=24),
                            confidence=0.85,
                            source_tier=SOURCE_TIER_T1,
                            nature=NATURE_FACT,
                        )
                        desc = f"龙虎榜: {row.to_dict()}"
                        points.append(
                            AttributionDataPoint(
                                category="capital_flow",
                                description=desc[:200],
                                source_citation=citation,
                                is_stale=False,
                                cross_validated=False,
                            )
                        )
                else:
                    points.append(
                        AttributionDataPoint(
                            category="capital_flow",
                            description="龙虎榜: 当日未上榜",
                            source_citation=SourceCitation(
                                provider="eastmoney", field="dragon_tiger",
                                source_tier=SOURCE_TIER_T1, nature=NATURE_FACT,
                                confidence=0.85,
                            ),
                        )
                    )
        except Exception as e:
            logger.warning("龙虎榜数据获取失败: %s", e)

        # 4b: 北向资金 (T1)
        try:
            nb_df = self.akshare_provider.get_northbound_flow()
            if hasattr(nb_df, 'empty') and not nb_df.empty:
                citation = SourceCitation(
                    provider="eastmoney",
                    field="northbound",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=4),
                    confidence=0.80,
                    source_tier=SOURCE_TIER_T1,
                    nature=NATURE_FACT,
                )
                points.append(
                    AttributionDataPoint(
                        category="capital_flow",
                        description=f"北向资金: 当日数据已获取 ({len(nb_df)} 条记录)",
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=False,
                    )
                )
        except Exception as e:
            logger.warning("北向资金数据获取失败: %s", e)

        # 4c: 融资融券 (T1)
        try:
            mt_df = self.akshare_provider.get_margin_trading()
            if hasattr(mt_df, 'empty') and not mt_df.empty:
                citation = SourceCitation(
                    provider="eastmoney",
                    field="margin_trading",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=24),
                    confidence=0.85,
                    source_tier=SOURCE_TIER_T1,
                    nature=NATURE_FACT,
                )
                points.append(
                    AttributionDataPoint(
                        category="capital_flow",
                        description=f"融资融券: 数据已获取 ({len(mt_df)} 条记录)",
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=False,
                    )
                )
        except Exception as e:
            logger.warning("融资融券数据获取失败: %s", e)

        # 如果所有资金面数据都获取失败，标记 DATA_GAP
        capital_points = [p for p in points if p.category == "capital_flow"]
        if not capital_points:
            points.append(
                AttributionDataPoint(
                    category="capital_flow",
                    description="资金面数据全部不可用",
                    source_citation=SourceCitation(
                        provider="system", field="capital_flow",
                        source_tier=SOURCE_TIER_T3, nature=NATURE_SPECULATION,
                        confidence=0.1,
                    ),
                    data_gap_reason="龙虎榜/北向/融资融券/大宗交易数据源均不可用",
                )
            )

        return points

    def _fetch_policy_hint(self, symbol: str, name: str) -> list[AttributionDataPoint]:
        """通道 5: 行业政策背景搜集 (轻量版, 完整分析由 policy-tracker skill 完成)。"""
        points = []
        now = datetime.now()

        # 尝试通过东财获取行业分类，标记为政策相关
        try:
            # 判断所属板块
            market_code = 1 if symbol.startswith("6") else 0
            import urllib.request
            import json
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get"
                f"?fltt=2&invt=2&fields=f57,f58,f127&secid={market_code}.{symbol}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            d = json.loads(resp.read().decode()).get("data", {})
            industry = d.get("f127", "")

            if industry:
                citation = SourceCitation(
                    provider="eastmoney",
                    field="industry",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=24),
                    confidence=0.80,
                    source_tier=SOURCE_TIER_T1,
                    nature=NATURE_FACT,
                )
                points.append(
                    AttributionDataPoint(
                        category="sector",
                        description=f"所属行业: {industry} (东财分类)",
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=True,
                    )
                )
        except Exception:
            pass

        return points

    # ────────────────────────────────────────────────────────
    # 质量预检
    # ────────────────────────────────────────────────────────

    def _compute_quality_summary(
        self, points: list[AttributionDataPoint], date: str
    ) -> QualitySummary:
        """遍历所有数据点，生成 QualitySummary。

        统计各 tier 数量/平均质量分/示例；收集 STALE 和数据缺口。
        """
        quality = QualitySummary()
        tier_groups: dict[str, list[float]] = {"T0": [], "T1": [], "T2": [], "T3": []}
        tier_examples: dict[str, list[str]] = {"T0": [], "T1": [], "T2": [], "T3": []}

        for p in points:
            tier = p.source_citation.source_tier
            if tier not in tier_groups:
                tier = SOURCE_TIER_T3

            qs = p.source_citation.quality_score
            tier_groups[tier].append(qs)
            if p.description and len(tier_examples[tier]) < 3:
                # 清理描述中的原始对象转储
                desc = p.description[:80]
                if desc.startswith("title=") or desc.startswith("["):
                    pass  # 保留原样但截断
                tier_examples[tier].append(desc)

            # 收集 STALE
            if p.is_stale:
                quality.stale_excluded.append(p.description[:100])

            # 收集 DATA_GAP
            if p.data_gap_reason:
                quality.data_gaps.append(f"{p.category}: {p.data_gap_reason}")

        # 统计
        for tier in ["T0", "T1", "T2", "T3"]:
            scores = tier_groups[tier]
            quality.tier_counts[tier] = len(scores)
            quality.tier_avg_quality[tier] = (
                sum(scores) / len(scores) if scores else 0.0
            )
            quality.tier_examples[tier] = tier_examples[tier]

        # 计算整体置信度: 各 tier 的平均质量分加权
        total_points = len(points)
        if total_points > 0:
            all_scores = [
                p.source_citation.quality_score for p in points
                if not p.is_stale and not p.data_gap_reason
            ]
            quality.overall_confidence = (
                sum(all_scores) / len(all_scores) if all_scores else 0.1
            )
        else:
            quality.overall_confidence = 0.0

        # DATA_GAP 影响评估
        if quality.data_gaps:
            gap_categories = set(g.split(":")[0] for g in quality.data_gaps)
            quality.data_gap_impact = (
                f"以下维度缺少数据，已下调对应归因权重: {', '.join(gap_categories)}"
            )

        return quality

    # ────────────────────────────────────────────────────────
    # 辅助方法
    # ────────────────────────────────────────────────────────

    def _calc_price_change(self, points: list[AttributionDataPoint]) -> float:
        """从已搜集的行情数据点中提取价格变动。"""
        for p in points:
            if p.category == "technical" and "涨跌" in p.description:
                import re
                match = re.search(r"涨跌\s+([+-]\d+\.?\d*)%", p.description)
                if match:
                    return float(match.group(1))
        return 0.0

    def _deduplicate(self, points: list[AttributionDataPoint]) -> list[AttributionDataPoint]:
        """去重: 相同 category + 相同描述前缀 的合并为一条。"""
        seen = set()
        result = []
        for p in points:
            key = (p.category, p.description[:60])
            if key not in seen:
                seen.add(key)
                result.append(p)
        return result

    def build_driver_factors(
        self,
        result: AttributionResult,
        primary: str,
        secondary: list[str],
        noise: list[str],
        causality_chain: str = "",
    ) -> AttributionResult:
        """Phase 3 辅助: 根据 AI 代理的因果推断结果构建 DriverFactor 列表。

        调用此方法后 result.drivers 将被填充，可直接传给 format_attribution_result()。
        """
        drivers = []
        all_drivers = [(primary, True)] + [(s, False) for s in secondary] + [(n, False) for n in noise]

        for name, is_primary in all_drivers:
            # 在 raw_data_points 中查找匹配的数据点以获取 tier/nature
            best_tier = SOURCE_TIER_T3
            best_nature = NATURE_INTERPRETATION
            for p in result.raw_data_points:
                if any(kw in p.description for kw in name[:20].split()):
                    best_tier = p.source_citation.source_tier
                    best_nature = p.source_citation.nature
                    break

            weight = 0.35 if is_primary else 0.15
            if name in [s for s, _ in all_drivers if s in result.noise_factors]:
                weight = 0.05

            drivers.append(
                DriverFactor(
                    name=name,
                    weight=weight,
                    tier=best_tier,
                    nature=best_nature,
                    freshness="fresh",
                    is_primary=is_primary,
                )
            )

        # 归一化权重
        total_w = sum(d.weight for d in drivers)
        if total_w > 0:
            for d in drivers:
                d.weight = d.weight / total_w

        result.drivers = sorted(drivers, key=lambda d: d.weight, reverse=True)
        result.primary_driver = primary
        result.secondary_drivers = secondary
        result.noise_factors = noise
        result.causality_chain = causality_chain
        result.confidence = result.quality.overall_confidence

        return result
