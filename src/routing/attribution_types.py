# -*- coding: utf-8 -*-
"""个股涨跌归因 — 数据模型定义。

AttributionEngine 使用这些 DTO 作为 Phase 1-3 的结构化输入/输出。
所有字段遵循 guardrails.md 的 T0-T3/STALE/DATA_GAP 规范。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.data.source_citation import SourceCitation


@dataclass
class AttributionDataPoint:
    """归因中的单条证据/数据点。

    每条数据点携带完整的 source_citation，包含 T0-T3 分级、
    数据性质 (fact/interpretation/speculation) 和时效性标记。
    """

    category: str  # 驱动维度: "news" / "policy" / "capital_flow" / "sector" / "macro" / "sentiment" / "technical" / "topic" / "announcement"
    description: str  # 人类可读描述
    source_citation: SourceCitation  # 溯源信息 (tier/nature/freshness/confidence)
    weight: float = 0.0  # 归因权重 (质量加权后，Phase 3 填入)
    driver_rank: int = 0  # 主因=1, 次因=2, 噪音=3 (Phase 3 填入)
    is_stale: bool = False  # 新闻 > 12h 过期标记
    cross_validated: bool = False  # 多源交叉验证通过
    data_gap_reason: str = ""  # 非空时标记为 [DATA_GAP]


@dataclass
class QualitySummary:
    """信息源质量总览 (Phase 3 强制输出)。

    对应 guardrails.md 第 124-143 行的强制输出格式。
    """

    tier_counts: dict[str, int] = field(default_factory=dict)  # {"T0": 3, "T1": 5, ...}
    tier_avg_quality: dict[str, float] = field(default_factory=dict)  # {"T0": 0.92, ...}
    tier_examples: dict[str, list[str]] = field(default_factory=dict)  # {"T0": ["巨潮公告..."]}
    stale_excluded: list[str] = field(default_factory=list)  # 已排除的 [STALE] 条目
    data_gaps: list[str] = field(default_factory=list)  # [DATA_GAP] 声明
    data_gap_impact: str = ""  # 缺口对分析可信度的影响描述
    overall_confidence: float = 0.0  # 综合 confidence


@dataclass
class DriverFactor:
    """归因驱动因子 (Phase 3 排序输出)。

    对应 guardrails.md 归因权重表。
    """

    name: str  # 驱动因素名，如"可转债发行稀释预期"
    weight: float  # 质量加权后的归因权重 (0.0-1.0)
    tier: str  # T0/T1/T2/T3
    nature: str  # fact / interpretation / speculation
    freshness: str  # "fresh" / "stale (<12h)" / "过期已排除"
    is_primary: bool = False  # 是否为主因
    description: str = ""  # 传导逻辑简述


@dataclass
class AttributionResult:
    """完整的个股涨跌归因分析结果。

    Phase 1 (信息搜集): 由 AttributionEngine.collect() 自动填充。
    Phase 2 (多维归因): 由 AI 代理调用各分析 skill 后填充。
    Phase 3 (因果推断): 由 AI 代理完成质量检查+因果链推导后填充。
    """

    # ── 基本信息 ──
    symbol: str = ""
    name: str = ""
    date: str = ""  # YYYY-MM-DD
    price_change_pct: float = 0.0  # 涨跌幅

    # ── Phase 1: 信息搜集 (AttributionEngine 自动填充) ──
    raw_data_points: list[AttributionDataPoint] = field(default_factory=list)
    quality: QualitySummary = field(default_factory=QualitySummary)

    # ── Phase 2: 多维归因 (AI 代理填充) ──
    macro_assessment: str = ""  # 宏观背景摘要
    sector_assessment: str = ""  # 板块联动摘要
    sentiment_assessment: str = ""  # 情绪状态摘要
    topic_assessment: str = ""  # 主题生命周期摘要
    capital_flow_assessment: str = ""  # 资金面 (北向/龙虎榜/融资融券) 摘要
    technical_assessment: str = ""  # T+0 技术面摘要

    # ── Phase 3: 因果推断 (AI 代理填充) ──
    drivers: list[DriverFactor] = field(default_factory=list)  # 按 weight 降序
    primary_driver: str = ""  # 主因
    secondary_drivers: list[str] = field(default_factory=list)  # 次因
    noise_factors: list[str] = field(default_factory=list)  # 噪音
    causality_chain: str = ""  # 因果链推导过程
    confidence: float = 0.0  # 整体置信度

    # ── 元数据 ──
    created_at: datetime = field(default_factory=datetime.now)
    data_freshness_warning: str = ""  # 数据获取时间与归因日期间隔警告
