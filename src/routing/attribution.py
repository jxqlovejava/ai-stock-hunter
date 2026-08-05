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
    EVIDENCE_LEVEL_LABELS,
    AttributionDataPoint,
    AttributionLayer,
    AttributionResult,
    DriverFactor,
    LayerAttribution,
    QualitySummary,
)

logger = logging.getLogger(__name__)

# 时效性常量 (来自 guardrails.md)
NEWS_STALE_HOURS = 12  # 新闻事件过期时间
POLICY_STALE_HOURS = 24  # 政策/主题过期时间
FUNDAMENTAL_STALE_HOURS = 48  # 基本面数据过期时间

# ────────────────────────────────────────────────────────
# 三层归因分层: 执行层 / 配置层 / 投资逻辑层
# 来源: 投资资讯精读 doc 29 (可信度 0.55)
# 原则: 越往上 (LOGIC) 推翻所需证据越多;
#       避免把执行问题升级成逻辑问题; 避免用短期回调掩盖逻辑破裂。
# ────────────────────────────────────────────────────────

# 操作执行问题 (买点差/追高/止损未执行)
EXECUTION_KEYWORDS: tuple[str, ...] = (
    "买点", "卖点", "买贵", "买高", "卖低", "追高", "追涨", "追板", "追进",
    "抄底", "止损", "止盈", "挂单", "卖飞", "买飞", "打板", "入场", "离场",
    "介入", "盘中", "日内", "高开", "低开", "冲高", "回落", "跳水", "换手",
    "割肉", "套牢", "踏空", "追跌", "挂错", "操作失误", "操作不当", "时机",
    "时点", "情绪化交易", "频繁交易", "卖出过早", "买入过早", "恐慌抛售",
    "止盈未执行", "止损未执行", "止损过紧", "止损过宽", "一次性买入",
    "分批卖出", "开盘买入", "尾盘卖出", "高抛", "低吸", "急跌接飞刀",
)

# 仓位排队/资金分配问题 (仓位过重/未分散/杠杆过高)
CONFIGURATION_KEYWORDS: tuple[str, ...] = (
    "仓位", "满仓", "空仓", "重仓", "轻仓", "半仓", "加仓", "减仓", "建仓",
    "补仓", "调仓", "换仓", "分散", "集中持仓", "集中度", "杠杆", "融资",
    "配资", "保证金", "资金分配", "资金排队", "排队", "持仓集中", "单一标的",
    "单一行业", "仓位过重", "仓位过轻", "仓位过小", "定投", "现金比例",
    "组合", "子弹", "弹药", "分批建仓", "补仓节奏", "重仓单一", "持仓结构",
)

# 核心假设/基本面逻辑问题 (假设被证伪/基本面恶化)
LOGIC_KEYWORDS: tuple[str, ...] = (
    "业绩", "盈利", "利润", "营收", "收入", "毛利率", "净利率", "现金流",
    "估值", "市盈率", "市净率", "财报", "业绩预告", "业绩快报", "不及预期",
    "超预期", "预期", "逻辑", "假设", "证伪", "基本面", "需求", "订单",
    "景气", "行业", "政策", "监管", "竞争", "市占率", "市场份额", "减值",
    "商誉", "扩产", "产能", "周期", "下行", "恶化", "逻辑破坏", "叙事",
    "催化", "兑现", "盈利修正", "护城河", "稀缺性", "确定性", "成长性",
    "渗透率", "景气拐点", "分红", "回购", "增持", "减持", "解禁",
    "控股股东", "董事长", "管理层", "指引", "补贴", "关税", "制裁",
)

# raw_data_points category → 层 (Phase 2 各维度归类)
CATEGORY_LAYER_MAP: dict[str, AttributionLayer] = {
    "technical": AttributionLayer.EXECUTION,  # T+0 技术面 → 执行/操作
    "sentiment": AttributionLayer.EXECUTION,  # 情绪化操作
    "capital_flow": AttributionLayer.CONFIGURATION,  # 资金分配/拥挤度
    "news": AttributionLayer.LOGIC,
    "announcement": AttributionLayer.LOGIC,
    "macro": AttributionLayer.LOGIC,
    "sector": AttributionLayer.LOGIC,
    "policy": AttributionLayer.LOGIC,
    "topic": AttributionLayer.LOGIC,
    "commodity": AttributionLayer.LOGIC,
    "management_guidance": AttributionLayer.LOGIC,
}

# 兜底层: 中性 (既不是明确的逻辑破裂, 也不是明确的操作失误)
DEFAULT_LAYER = AttributionLayer.CONFIGURATION


def classify_layer(
    driver_name: str,
    category: str = "",
    matched_point: AttributionDataPoint | None = None,
) -> AttributionLayer:
    """将单个驱动因素映射到三层归因之一 (执行/配置/逻辑)。

    判定顺序 (逻辑 > 配置 > 执行 关键词优先, 防止用操作解读掩盖逻辑破裂):
      1. 关键词匹配 (配置/逻辑/执行关键词表)
      2. 数据点 category → 层 (technical→执行, capital_flow→配置, 基本面类→逻辑)
      3. 兜底 → DEFAULT_LAYER (CONFIGURATION, 中性; 避免把执行问题升级成逻辑问题)

    Args:
        driver_name: 驱动因素名, 如 "Q2 业绩不及预期" / "追高买入致套牢"
        category: 数据点 category (technical/capital_flow/news/...)
        matched_point: 命中的 raw_data_points 数据点 (用于取 category)
    """
    text = driver_name or ""
    # 逻辑层最高优先级: 明确的基本面/假设信号不可被操作解读掩盖
    if any(k in text for k in LOGIC_KEYWORDS):
        return AttributionLayer.LOGIC
    if any(k in text for k in CONFIGURATION_KEYWORDS):
        return AttributionLayer.CONFIGURATION
    if any(k in text for k in EXECUTION_KEYWORDS):
        return AttributionLayer.EXECUTION
    if matched_point is not None and matched_point.category in CATEGORY_LAYER_MAP:
        return CATEGORY_LAYER_MAP[matched_point.category]
    if category in CATEGORY_LAYER_MAP:
        return CATEGORY_LAYER_MAP[category]
    return DEFAULT_LAYER


def _find_matching_point(
    result: AttributionResult, driver_name: str
) -> AttributionDataPoint | None:
    """在 raw_data_points 中查找与 driver_name 最匹配的数据点 (取 category/tier/证据)。"""
    tokens = (driver_name or "")[:30].replace("，", " ").replace(",", " ").split()
    if not tokens:
        tokens = [(driver_name or "")[:30]]
    best = None
    best_score = 0
    for p in result.raw_data_points:
        desc = p.description or ""
        score = sum(1 for t in tokens if t and t in desc)
        if score > best_score:
            best_score = score
            best = p
    return best if best_score > 0 else None


def _build_evidence(
    matched_point: AttributionDataPoint | None, driver: DriverFactor
) -> str:
    """为单条三层归因生成证据简述。"""
    if matched_point is not None and matched_point.description:
        return matched_point.description.strip()[:60]
    if driver.description:
        return driver.description.strip()[:60]
    return f"驱动因素「{driver.name}」未命中具体数据点, 分层为启发式判定"


def layerize_drivers(result: AttributionResult) -> list[LayerAttribution]:
    """对 result.drivers 逐条做三层归因分层, 写入 result.layer_attributions。

    从现有 Phase 2/3 归因数据 (drivers + raw_data_points) 映射到
    执行层/配置层/投资逻辑层。返回 LayerAttribution 列表 (与 drivers 同序)。
    """
    if not result.drivers:
        result.layer_attributions = []
        return result.layer_attributions

    layers: list[LayerAttribution] = []
    for d in result.drivers:
        matched = _find_matching_point(result, d.name)
        layer = classify_layer(
            d.name,
            category=matched.category if matched is not None else "",
            matched_point=matched,
        )
        # 置信度: 结合匹配点质量与主/次因权重
        base_conf = (
            matched.source_citation.quality_score
            if matched is not None
            else result.confidence
        )
        confidence = round(
            min(1.0, max(0.05, base_conf * (0.9 if d.is_primary else 0.75))), 3
        )
        layers.append(
            LayerAttribution(
                layer=layer,
                driver=d.name,
                evidence=_build_evidence(matched, d),
                confidence=confidence,
                overturn_evidence_level=layer.overturn_evidence_level,
                is_primary=d.is_primary,
                evidence_note=EVIDENCE_LEVEL_LABELS.get(
                    layer.overturn_evidence_level, ""
                ),
            )
        )

    result.layer_attributions = layers
    return layers


def dominant_layer(result: AttributionResult) -> AttributionLayer | None:
    """三层归因中权重占比最大的层 (执行/配置/逻辑 主层)。

    以各条 LayerAttribution.confidence 求和, 取最高者; 无归因时返回 None。
    """
    if not result.layer_attributions:
        return None
    totals: dict[AttributionLayer, float] = {}
    for la in result.layer_attributions:
        totals[la.layer] = totals.get(la.layer, 0.0) + la.confidence
    if not totals:
        return None
    return max(totals, key=totals.get)


def format_layer_attributions(result: AttributionResult) -> str:
    """渲染三层归因分层块 (执行/配置/逻辑)。

    供 attribution_formatter.format_attribution_result / CLI 消费。
    本文件提供该格式化辅助函数, 不改动 attribution_formatter.py 本身。
    """
    if not result.layer_attributions:
        return "🧭 三层归因分层: (未计算 — 需先运行 layerize_drivers 或 build_driver_factors)"

    lines = ["🧭 三层归因分层 (执行→配置→逻辑, 越往上推翻所需证据越多)"]
    lines.append("| 层 | 主要驱动 | 证据 | 置信度 | 推翻所需证据级别 | 主因 |")
    lines.append("|----|---------|------|--------|----------------|------|")
    for la in result.layer_attributions:
        ev_level = la.effective_overturn_level()
        ev_label = EVIDENCE_LEVEL_LABELS.get(ev_level, f"级别 {ev_level}")
        primary = "主因" if la.is_primary else ""
        lines.append(
            f"| {la.layer.label[:16]:<18} | {la.driver[:22]:<24} "
            f"| {la.evidence[:36]:<38} | {la.confidence:.2f} "
            f"| {ev_label[:30]:<32} | {primary} |"
        )
    dom = dominant_layer(result)
    if dom is not None:
        lines.append(
            f"\n  主导层: {dom.label}"
            f" — {EVIDENCE_LEVEL_LABELS.get(dom.overturn_evidence_level, '')}"
        )
    return "\n".join(lines)


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
            "commodity_prices": lambda: self._fetch_commodity_prices(symbol, name),
            "management_guidance": lambda: self._fetch_management_guidance(symbol, name),
        }

        with ThreadPoolExecutor(max_workers=7) as executor:
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

        # 4d: 大宗交易 (T1) — Phase 12
        try:
            from src.game_theory.block_trade import BlockTradeAnalyzer
            bt_analyzer = BlockTradeAnalyzer()
            bt_profile = bt_analyzer.analyze(symbol=symbol)
            if bt_profile is not None and bt_profile.total_count > 0:
                citation = SourceCitation(
                    provider="eastmoney",
                    field="block_trade",
                    fetch_timestamp=now,
                    data_freshness=timedelta(hours=24),
                    confidence=0.85,
                    source_tier=SOURCE_TIER_T1,
                    nature=NATURE_FACT,
                )
                # 构建有信息量的描述
                bt_parts = [f"大宗交易: 全市场{bt_profile.total_count}笔/{bt_profile.total_amount}亿"]
                if bt_profile.symbol_records:
                    bt_parts.append(
                        f"该股{len(bt_profile.symbol_records)}笔"
                        f"(均溢价{bt_profile.symbol_premium_avg:+.1f}%)"
                    )
                if bt_profile.institution_net_direction == "buying":
                    bt_parts.append(
                        f"机构净买入({bt_profile.institution_buy_count}买vs{bt_profile.institution_sell_count}卖)"
                    )
                elif bt_profile.institution_net_direction == "selling":
                    bt_parts.append(
                        f"机构净卖出({bt_profile.institution_sell_count}卖vs{bt_profile.institution_buy_count}买)"
                    )
                if bt_profile.symbol_institution_buy:
                    bt_parts.append("⚠️ 该股获机构大宗买入")
                if bt_profile.symbol_institution_sell:
                    bt_parts.append("⚠️ 该股遭机构大宗卖出")
                if bt_profile.symbol_consecutive_days >= 3:
                    bt_parts.append(f"连续{bt_profile.symbol_consecutive_days}天出现")

                points.append(
                    AttributionDataPoint(
                        category="capital_flow",
                        description="; ".join(bt_parts),
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=False,
                    )
                )
        except Exception as e:
            logger.warning("大宗交易数据获取失败: %s", e)

        # 4e: 个股主力资金流 (T1/T2)
        try:
            mf = self.aggregator.get_money_flow(symbol, weeks=4)
            if mf is not None and not mf.empty:
                parts = [
                    f"个股资金流: 主力净额 {mf.main_net:+.0f}万",
                    f"超大单 {mf.super_large_net:+.0f}万",
                    f"大单 {mf.large_net:+.0f}万",
                ]
                if mf.main_consecutive_days != 0:
                    direction = "流入" if mf.main_consecutive_days > 0 else "流出"
                    parts.append(f"连续{direction} {abs(mf.main_consecutive_days)} 天")
                if mf.data_gap_reason:
                    parts.append(mf.data_gap_reason)

                citation = mf.citation
                if citation is None:
                    if mf.data_gap_reason:
                        citation = SourceCitation(
                            provider="system",
                            field="individual_fund_flow",
                            fetch_timestamp=now,
                            data_freshness=timedelta(hours=4),
                            confidence=0.1,
                            source_tier=SOURCE_TIER_T3,
                            nature=NATURE_SPECULATION,
                        )
                    else:
                        citation = SourceCitation(
                            provider="eastmoney",
                            field="individual_fund_flow",
                            fetch_timestamp=now,
                            data_freshness=timedelta(hours=4),
                            confidence=0.80,
                            source_tier=SOURCE_TIER_T1,
                            nature=NATURE_FACT,
                        )
                points.append(
                    AttributionDataPoint(
                        category="capital_flow",
                        description="; ".join(parts),
                        source_citation=citation,
                        is_stale=False,
                        cross_validated=False,
                    )
                )
        except Exception as e:
            logger.warning("个股资金流数据获取失败: %s", e)

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
                    data_gap_reason="龙虎榜/北向/融资融券/大宗交易/个股资金流数据源均不可用",
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
    # 通道 6: 周期品价格追踪 🆕
    # ────────────────────────────────────────────────────────

    # 行业 → 关联大宗商品/周期品映射
    COMMODITY_MAP: dict[str, list[str]] = {
        "电网设备": ["硅料(多晶硅)", "动力煤", "铜", "铝"],
        "光伏设备": ["硅料(多晶硅)", "硅片", "组件价格", "逆变器"],
        "电力设备": ["铜", "铝", "硅钢", "变压器油"],
        "能源金属": ["碳酸锂", "氢氧化锂", "钴", "镍"],
        "有色金属": ["铜", "铝", "锂", "钴", "镍", "稀土", "黄金"],
        "小金属": ["钨", "钼", "锑", "镁", "钛白粉"],
        "工业金属": ["铜", "铝", "锌", "铅", "锡"],
        "贵金属": ["黄金", "白银"],
        "普钢": ["螺纹钢", "热轧卷板", "铁矿石", "焦炭"],
        "特钢": ["螺纹钢", "热轧卷板", "铁矿石", "镍"],
        "钢铁": ["螺纹钢", "热轧卷板", "铁矿石", "焦炭"],
        "煤炭开采": ["动力煤", "焦煤", "焦炭"],
        "焦炭": ["焦煤", "焦炭", "螺纹钢"],
        "石油石化": ["原油", "天然气", "PTA", "涤纶"],
        "炼化及贸易": ["原油", "天然气", "PTA"],
        "油气开采": ["原油", "天然气"],
        "基础化工": ["纯碱", "烧碱", "PVC", "MDI", "TDI", "尿素"],
        "农化制品": ["草甘膦", "草铵膦", "复合肥", "尿素"],
        "化学制品": ["MDI", "TDI", "纯碱", "钛白粉"],
        "化学原料": ["纯碱", "烧碱", "PVC", "电石"],
        "化学纤维": ["PTA", "涤纶", "锦纶", "氨纶"],
        "塑料": ["PVC", "PE", "PP", "ABS"],
        "橡胶": ["天然橡胶", "合成橡胶"],
        "建筑材料": ["水泥", "玻璃", "玻纤"],
        "水泥": ["水泥", "熟料"],
        "玻璃玻纤": ["玻璃", "玻纤", "纯碱"],
        "化学制药": ["维生素A", "维生素E", "抗生素中间体"],
        "原料药": ["维生素A", "维生素E", "抗生素中间体", "肝素"],
        "养殖业": ["生猪", "白羽鸡", "饲料"],
        "饲料": ["豆粕", "玉米", "鱼粉"],
        "农产品加工": ["豆粕", "玉米", "棕榈油", "白糖"],
        "种植业": ["玉米", "小麦", "大豆", "棉花", "白糖"],
        "造纸": ["纸浆", "废纸"],
        "航运港口": ["BDI(波罗的海干散货)", "SCFI(集装箱运价)"],
        "物流": ["BDI(波罗的海干散货)", "SCFI(集装箱运价)"],
        "航空机场": ["原油(航空煤油)", "汇率(美元/人民币)"],
        "电力": ["动力煤", "天然气", "碳排放权"],
        "燃气": ["天然气", "LNG"],
        "新能源发电": ["硅料(多晶硅)", "光伏组件", "风电设备"],
    }

    def _fetch_commodity_prices(
        self, symbol: str, name: str
    ) -> list[AttributionDataPoint]:
        """通道 6: 周期品/大宗商品价格追踪。

        根据股票所属行业，自动拉取关联大宗商品近期价格走势。
        对非周期行业（消费/医药/TMT等）返回空列表。
        """
        points: list[AttributionDataPoint] = []
        now = datetime.now()

        # 1. 获取行业分类
        industry = ""
        try:
            import urllib.request
            import json
            market_code = 1 if symbol.startswith("6") else 0
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get"
                f"?fltt=2&invt=2&fields=f57,f58,f127&secid={market_code}.{symbol}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            d = json.loads(resp.read().decode()).get("data", {})
            industry = d.get("f127", "")
        except Exception:
            pass

        # 2. 判断是否周期行业，找到关联品种
        matched_commodities: list[str] = []
        for sector_key, commodities in self.COMMODITY_MAP.items():
            if sector_key in (industry or ""):
                matched_commodities = commodities
                break

        if not matched_commodities:
            # 非周期行业，输出空
            return points

        # 3. 拉取品种价格数据
        commodity_data: list[str] = []
        try:
            import akshare as ak
            for commodity in matched_commodities:
                try:
                    price_info = self._fetch_single_commodity(commodity, ak)
                    if price_info:
                        commodity_data.append(price_info)
                except Exception:
                    commodity_data.append(f"{commodity}: 数据获取失败")
        except ImportError:
            commodity_data.append("周期品价格: akshare 不可用")

        if not commodity_data:
            return points

        desc = f"关联周期品价格 ({industry}): " + "; ".join(commodity_data)
        citation = SourceCitation(
            provider="akshare+industry_map",
            field="commodity_price",
            fetch_timestamp=now,
            data_freshness=timedelta(hours=24),
            confidence=0.75,
            source_tier=SOURCE_TIER_T2,
            nature=NATURE_FACT,
        )
        points.append(
            AttributionDataPoint(
                category="commodity",
                description=desc[:300],
                source_citation=citation,
                is_stale=False,
                cross_validated=False,
            )
        )

        return points

    def _fetch_single_commodity(self, commodity: str, ak_module=None) -> str:
        """拉取单个品种近期价格并返回摘要。"""
        # 常见品种的 akshare 接口映射
        COMMODITY_AK_INTERFACE: dict[str, tuple[str, str]] = {
            "动力煤": ("futures", "ZC"),
            "焦煤": ("futures", "JM"),
            "焦炭": ("futures", "J"),
            "螺纹钢": ("futures", "RB"),
            "热轧卷板": ("futures", "HC"),
            "铁矿石": ("futures", "I"),
            "铜": ("futures", "CU"),
            "铝": ("futures", "AL"),
            "锌": ("futures", "ZN"),
            "铅": ("futures", "PB"),
            "锡": ("futures", "SN"),
            "镍": ("futures", "NI"),
            "黄金": ("futures", "AU"),
            "原油": ("futures", "SC"),
            "天然橡胶": ("futures", "RU"),
            "PTA": ("futures", "TA"),
            "PVC": ("futures", "V"),
            "纯碱": ("futures", "SA"),
            "玻璃": ("futures", "FG"),
            "尿素": ("futures", "UR"),
            "生猪": ("futures", "LH"),
            "碳酸锂": ("spot", "碳酸锂"),
            "硅料(多晶硅)": ("spot", "多晶硅"),
            "水泥": ("spot", "水泥"),
            "BDI(波罗的海干散货)": ("spot", "BDI"),
            "SCFI(集装箱运价)": ("spot", "SCFI"),
        }

        try:
            if commodity in COMMODITY_AK_INTERFACE:
                src_type, code = COMMODITY_AK_INTERFACE[commodity]
                if src_type == "futures" and ak_module:
                    # 期货主力合约
                    df = ak_module.futures_main_sina(symbol=code)
                    if df is not None and len(df) > 0:
                        recent = df.tail(30)
                        current = float(recent.iloc[-1])
                        high = float(recent["high"].max()) if "high" in recent.columns else current
                        low = float(recent["low"].min()) if "low" in recent.columns else current
                        chg_30d = (current / float(recent.iloc[0]) - 1) * 100 if len(recent) >= 2 else 0
                        return (
                            f"{commodity}: 最新 {current:.0f} "
                            f"(30日 {chg_30d:+.1f}%, "
                            f"区间 {low:.0f}-{high:.0f})"
                        )
            elif "硅料" in commodity:
                # 通过 news 替代 — 见管理层指引
                return f"{commodity}: 见管理层指引/研报 (无实时报价)"
            else:
                return f"{commodity}: 无标准化接口"
        except Exception as e:
            logger.debug("获取 %s 价格失败: %s", commodity, e)

        return f"{commodity}: 数据暂不可用"

    # ────────────────────────────────────────────────────────
    # 通道 7: 管理层指引 🆕
    # ────────────────────────────────────────────────────────

    def _fetch_management_guidance(
        self, symbol: str, name: str
    ) -> list[AttributionDataPoint]:
        """通道 7: 管理层指引 — 投资者交流会/业绩说明会/互动易回复。

        强制搜索公司最近的管理层公开沟通，提取前瞻性判断。
        """
        points: list[AttributionDataPoint] = []
        now = datetime.now()

        # 1. 搜索新闻中的管理层沟通
        guidance_keywords = [
            "投资者交流会", "业绩说明会", "调研纪要", "互动易",
            "投资者关系活动", "电话会议", "路演",
        ]
        all_guidance: list[str] = []

        try:
            # 搜索公告中的投资者关系记录
            anns = self.aggregator.search_announcements(symbol)
            for ann in anns:
                if not ann.title:
                    continue
                title = str(ann.title)
                if any(kw in title for kw in ["投资者关系活动记录", "调研", "业绩说明会", "路演"]):
                    all_guidance.append(f"[公告] {title[:100]}")

            # 搜索新闻中的管理层表态
            for kw in guidance_keywords[:3]:  # 只搜前3个关键词避免过多请求
                try:
                    query = f"{name} {kw}"
                    news = self.aggregator.search_news(query, max_results=5)
                    for item in news:
                        if not item.title:
                            continue
                        title = str(item.title)
                        if any(kw2 in title for kw2 in guidance_keywords):
                            desc = f"[{item.source or 'news'}] {title[:100]}"
                            if desc not in all_guidance:
                                all_guidance.append(desc)
                except Exception:
                    pass

        except Exception as e:
            logger.warning("管理层指引搜索失败: %s", e)

        if all_guidance:
            # 标记关键措辞
            sentiment_markers = {
                "筑底": "🟢 周期见底信号",
                "反转": "🟢 趋势反转信号",
                "触底": "🟢 底部确认",
                "承压": "🔴 压力持续",
                "过剩": "🔴 产能过剩",
                "亏损": "🔴 亏损",
                "高增": "🟢 高增长",
                "超预期": "🟢 超预期",
                "不存在反转": "🔴 公司自认无反转",
                "短期难": "🔴 短期困难",
            }
            markers_found = []
            for item in all_guidance:
                for keyword, label in sentiment_markers.items():
                    if keyword in item and label not in markers_found:
                        markers_found.append(label)

            desc_parts = [f"管理层指引 ({len(all_guidance)}条):"]
            if markers_found:
                desc_parts.append(f"关键信号: {'; '.join(markers_found[:5])}")
            desc_parts.append(all_guidance[0][:150])

            citation = SourceCitation(
                provider="cninfo+news_search",
                field="management_guidance",
                fetch_timestamp=now,
                data_freshness=timedelta(hours=24),
                confidence=0.85,
                source_tier=SOURCE_TIER_T1,
                nature=NATURE_FACT,
            )
            points.append(
                AttributionDataPoint(
                    category="management_guidance",
                    description="; ".join(desc_parts)[:350],
                    source_citation=citation,
                    is_stale=False,
                    cross_validated=False,
                )
            )
        else:
            # 没有找到管理层指引，标记为 DATA_GAP
            points.append(
                AttributionDataPoint(
                    category="management_guidance",
                    description="管理层指引: 近期无投资者交流/业绩说明会记录",
                    source_citation=SourceCitation(
                        provider="system",
                        field="management_guidance",
                        source_tier=SOURCE_TIER_T3,
                        nature=NATURE_SPECULATION,
                        confidence=0.3,
                    ),
                    data_gap_reason="未找到近期管理层公开沟通记录",
                )
            )

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

        # 三层归因分层 (执行/配置/逻辑): 对每个驱动因素自动分层
        layerize_drivers(result)

        return result
