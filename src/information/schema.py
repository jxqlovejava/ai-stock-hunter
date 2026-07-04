"""I-Layer 核心数据模型。

参考：
- OpenStock adanos.helpers.ts: SentimentSourceInsight / StockSentimentInsights 结构化类型
- AI Berkshire thesis-tracker.md: 假设健康度评分模型
- Cyberagent README.zh.md: 反共识方法论
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── 枚举 ──────────────────────────────────────────────────────────────────────


class LifecycleStage(str, Enum):
    """主题生命周期阶段。

    EMERGING  → 萌芽：少数人讨论，无主流媒体报道
    SPREADING → 扩散：KOL/媒体开始跟进
    CONSENSUS → 共识：成为主流叙事，机构覆盖
    CROWDED   → 拥挤：人人都在说，超额收益消失
    FADING     → 消退：讨论度下降，被新主题替代
    """

    EMERGING = "emerging"
    SPREADING = "spreading"
    CONSENSUS = "consensus"
    CROWDED = "crowded"
    FADING = "fading"


class SourceType(str, Enum):
    """信源类型。用于适配器分类和可信度加权。"""

    SOCIAL_MEDIA = "social_media"  # 微博/雪球/知乎/B站/小红书/抖音
    FINANCIAL_NEWS = "financial_news"  # 财联社/东方财富/新浪财经
    RESEARCH_REPORT = "research_report"  # 华泰/国信/券商研报
    POLICY = "policy"  # 国务院/证监会/央行/发改委
    OVERSEAS = "overseas"  # Reddit/X/Twitter/Polymarket


class SignalType(str, Enum):
    """信息面信号类型。"""

    CONSENSUS_BREACH = "consensus_breach"  # 共识度突破阈值
    LIFECYCLE_TRANSITION = "lifecycle_transition"  # 生命周期阶段转换
    DIVERGENCE = "divergence"  # 跨源分歧
    PRICING_GAP = "pricing_gap"  # 信息定价缺口
    NARRATIVE_SHIFT = "narrative_shift"  # 叙事方向转变


class SentimentDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SourceAlignment(str, Enum):
    """跨源对齐度。

    Ref: OpenStock getSourceAlignment() — spread 分类器
    spread ≤ 12 → aligned, spread ≥ 25 → divergent
    """

    ALIGNED = "aligned"  # 各源情感一致（spread ≤ 12）
    MIXED = "mixed"  # 中度分歧
    DIVERGENT = "divergent"  # 强烈分歧（spread ≥ 25）
    SINGLE_SOURCE = "single_source"  # 仅单一信源
    NO_DATA = "no_data"  # 无可用数据


class DivergenceType(str, Enum):
    """分歧维度。不同信源可能在多个维度上产生分歧。"""

    SENTIMENT = "sentiment"  # 情感方向分歧（看多 vs 看空）
    NARRATIVE = "narrative"  # 叙事框架分歧（讲不同故事）
    URGENCY = "urgency"  # 紧急程度分歧（短期 vs 长期）
    DIRECTION = "direction"  # 方向判断分歧（涨 vs 跌）


class EventCategory(str, Enum):
    """事件类别。"""

    POSITIVE_SHORT = "positive_short"  # 短期利好
    POSITIVE_MEDIUM = "positive_medium"  # 中期利好
    POSITIVE_LONG = "positive_long"  # 长期利好
    NEGATIVE_SHORT = "negative_short"  # 短期利空
    NEGATIVE_MEDIUM = "negative_medium"  # 中期利空
    NEGATIVE_LONG = "negative_long"  # 长期利空
    NEUTRAL = "neutral"  # 中性事件
    UNKNOWN = "unknown"  # 无法分类


# ── 信源相关模型 ──────────────────────────────────────────────────────────────


class RawItem(BaseModel):
    """从信源采集的原始条目（标准化前）。"""

    source_type: SourceType
    platform: str  # "weibo" / "zhihu" / "eastmoney" / "huatai"
    title: str
    content: str = ""
    url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    metadata: dict = Field(default_factory=dict)  # 平台特定字段
    credibility_score: float = Field(default=0.5, ge=0.0, le=1.0)


class ProcessedItem(BaseModel):
    """NLP 处理后的条目。"""

    source_item: RawItem
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)  # -1(强烈看空) ~ 1(强烈看多)
    sentiment_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    extracted_entities: list[str] = Field(default_factory=list)  # 股票代码/行业/关键人物
    event_category: EventCategory = EventCategory.UNKNOWN
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""  # LLM 生成的单句摘要
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)  # 与主题的相关度


class SentimentResult(BaseModel):
    """单源情感分析结果（批量）。"""

    source_type: SourceType
    platform: str
    items_count: int
    sentiment_mean: float = Field(default=0.0, ge=-1.0, le=1.0)
    sentiment_std: float = Field(default=0.0, ge=0.0)  # 情感标准差（分歧度）
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    processed_items: list[ProcessedItem] = Field(default_factory=list)


# ── 主题模型 ──────────────────────────────────────────────────────────────────


class Topic(BaseModel):
    """一个可追踪的主题/叙事。

    主题是 I-Layer 的核心追踪单元。用户可以定义任意主题，
    系统自动追踪其共识度、生命周期、定价进度。
    """

    id: str = Field(description="唯一标识符，kebab-case，如 'domestic-ai-computing'")
    name: str = Field(description="主题名称，如 '国产AI算力扩容'")
    description: str = Field(default="", description="主题描述（1-3 句话）")
    keywords: list[str] = Field(default_factory=list, description="搜索关键词")
    related_stocks: list[str] = Field(
        default_factory=list, description="关联 A 股代码，如 ['688256','688041']"
    )
    related_sectors: list[str] = Field(default_factory=list, description="关联行业")
    core_hypothesis: str = Field(default="", description="核心假设（1 句话）")
    verifiable_conditions: list[str] = Field(
        default_factory=list,
        description="可验证条件列表，如 ['华为昇腾出货量>X','国产GPU市占率>Y%']",
    )
    tags: list[str] = Field(default_factory=list, description="分类标签")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    lifecycle_stage: LifecycleStage = Field(default=LifecycleStage.EMERGING)
    is_active: bool = Field(default=True, description="是否仍在追踪")
    version: int = Field(default=1, description="主题定义版本号")


# ── 共识度模型 ────────────────────────────────────────────────────────────────


class ConsensusMetrics(BaseModel):
    """共识度量化指标。

    Ref: OpenStock getSourceAlignment() + BuildStockSentimentInsights()
    """

    topic_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    # 讨论量
    volume_score: float = Field(default=0.5, ge=0.0, le=1.0, description="归一化讨论量")
    volume_trend: Literal["rising", "stable", "falling"] = "stable"
    # 情感
    sentiment_mean: float = Field(default=0.0, ge=-1.0, le=1.0, description="平均情感")
    sentiment_dispersion: float = Field(
        default=0.5, ge=0.0, le=1.0, description="情感分歧度（标准差，越低越一致）"
    )
    # 跨源
    source_alignment: SourceAlignment = SourceAlignment.NO_DATA
    institution_retail_gap: float = Field(
        default=0.0, ge=0.0, le=2.0, description="机构 vs 散户看法差距（绝对值）"
    )
    # 综合
    consensus_level: float = Field(
        default=0.5, ge=0.0, le=1.0, description="综合共识度（高=人人同意，低=争议大）"
    )
    estimated_alpha_remaining: float = Field(
        default=0.5, ge=0.0, le=1.0, description="剩余 Alpha 估计（共识度↑→Alpha↓）"
    )
    # 辅助
    source_count: int = Field(default=0, description="参与分析的信源数量")
    total_items: int = Field(default=0, description="分析的条目总数")
    notes: str = ""


# ── 分歧信号模型 ──────────────────────────────────────────────────────────────


class DivergenceSignal(BaseModel):
    """跨源分歧信号——分歧本身就是交易信号。

    Ref: Cyberagent 反共识方法论
    """

    topic_id: str
    source_a: str  # 信源 A 平台名
    source_b: str  # 信源 B 平台名
    divergence_type: DivergenceType
    divergence_score: float = Field(default=0.5, ge=0.0, le=1.0, description="分歧强度")
    description: str = ""  # "B站散户极度看好 vs 机构研报谨慎"
    source_a_stance: str = ""  # A 的立场描述
    source_b_stance: str = ""  # B 的立场描述
    tradable: bool = Field(default=False, description="是否可交易的分歧")
    suggested_action: str | None = None  # "关注机构观点，散户情绪可能过度乐观"
    detected_at: datetime = Field(default_factory=datetime.now)


# ── 信息定价度模型 ────────────────────────────────────────────────────────────


class InfoPricingEstimate(BaseModel):
    """信息→价格映射估算。

    估算一条信息/一个主题已被市场定价的比例。
    方法论：事件研究法 + 前置异动检测 + 多轮定价模型。
    """

    topic_id: str
    symbol: str
    event: str = Field(description="事件描述，如 '华为发布昇腾910C'")
    event_date: datetime | None = None
    pre_event_price_move: float = Field(
        default=0.0, description="事件前价格异动%（内幕泄露检测）"
    )
    post_event_reaction: float = Field(default=0.0, description="事件后 N 日超额收益%")
    estimated_pricing_ratio: float = Field(
        default=0.5, ge=0.0, le=1.0, description="信息已被定价的比例"
    )
    pricing_round: int = Field(
        default=1, ge=1, le=3, description="定价轮次（1=直接关联,2=供应链,3=替代品/互补品）"
    )
    key_observation: str = ""  # "股价已涨15%，市场可能已定价70%的利好"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    estimated_at: datetime = Field(default_factory=datetime.now)


# ── 信号输出模型 ──────────────────────────────────────────────────────────────


class InformationSignal(BaseModel):
    """标准化输出——I-Layer 对 L1/L2 的输出格式。"""

    topic_id: str
    topic_name: str
    symbol: str | None = Field(default=None, description="None = 主题级别信号（非个股）")
    signal_type: SignalType
    direction: SentimentDirection = SentimentDirection.NEUTRAL
    strength: float = Field(default=0.5, ge=0.0, le=1.0, description="信号强度")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    reasoning: str = ""  # 信号生成理由
    suggested_weight: float = Field(
        default=0.1, ge=0.0, le=0.5, description="在 L2 评分中的建议权重"
    )
    related_stocks: list[str] = Field(default_factory=list)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now().replace(hour=23, minute=59, second=59)
    )
    generated_at: datetime = Field(default_factory=datetime.now)


# ── 聚合快照模型 ──────────────────────────────────────────────────────────────


class TopicSnapshot(BaseModel):
    """主题的完整分析快照（一次分析的综合输出）。"""

    topic: Topic
    consensus: ConsensusMetrics | None = None
    lifecycle_stage: LifecycleStage = LifecycleStage.EMERGING
    lifecycle_transition_probability: float = Field(
        default=0.0, ge=0.0, le=1.0, description="向下一阶段转换的概率"
    )
    divergence_signals: list[DivergenceSignal] = Field(default_factory=list)
    pricing_estimates: list[InfoPricingEstimate] = Field(default_factory=list)
    information_signals: list[InformationSignal] = Field(default_factory=list)
    source_summaries: list[SentimentResult] = Field(default_factory=list)
    snapshot_at: datetime = Field(default_factory=datetime.now)
    analysis_duration_ms: float = 0.0


class TopicAlert(BaseModel):
    """主题级别的告警。"""

    topic_id: str
    topic_name: str
    event: str  # "生命周期从 SPREADING 转换到 CONSENSUS"
    urgency: Literal["info", "watch", "action"] = "info"
    recommended_action: str | None = None
    alert_at: datetime = Field(default_factory=datetime.now)


# ── 源适配器配置 ──────────────────────────────────────────────────────────────

# 信源可信度权重（用于加权聚合）
SOURCE_CREDIBILITY: dict[SourceType, float] = {
    SourceType.SOCIAL_MEDIA: 0.3,
    SourceType.FINANCIAL_NEWS: 0.6,
    SourceType.RESEARCH_REPORT: 0.8,
    SourceType.POLICY: 0.9,
    SourceType.OVERSEAS: 0.5,
}

# 跨源对齐度阈值（Ref: OpenStock getSourceAlignment）
ALIGNMENT_SPREAD_THRESHOLD = 12.0  # ≤ 此值 → ALIGNED
DIVERGENCE_SPREAD_THRESHOLD = 25.0  # ≥ 此值 → DIVERGENT

# 生命周期状态转换阈值（可配置）
LIFECYCLE_THRESHOLDS: dict[str, dict] = {
    "emerging_to_spreading": {
        "volume_growth_pct_30d": 200,  # 讨论量 30 日增长 > 200%
        "min_media_sources": 2,  # 或 ≥ 2 家媒体跟进
    },
    "spreading_to_consensus": {
        "min_research_reports": 3,  # ≥ 3 家机构研报覆盖
        "min_sentiment_alignment": 0.6,  # 情感一致性 > 0.6
    },
    "consensus_to_crowded": {
        "retail_volume_percentile": 90,  # 散户讨论量 > 历史 90% 分位
        "search_volume_peaking": True,
    },
    "any_to_fading": {
        "volume_decline_days": 30,  # 讨论量连续 N 日下降
        "no_new_catalyst": True,
    },
}
