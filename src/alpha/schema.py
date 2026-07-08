# -*- coding: utf-8 -*-
"""Alpha Lens DTO — 市场失效 Alpha 的检测与追踪数据结构。

核心理念：敬畏市场有效性，寻找市场失效的 Alpha。
三个维度对应三种 Alpha 来源：
  1. 信息来源层级 (AlphaSource)      — 逃出信息茧房
  2. 共识-现实缺口 (ConsensusGap)    — 耐心撑过情绪周期
  3. 叙事生命周期   (NarrativeStage)  — 提前挖掘未交易的东西
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Alpha Source — 信息来源层级
# ---------------------------------------------------------------------------


class SourceTier(Enum):
    """信息来源层级。

    核心理念：理解差 > 信息差。一手材料 > 二手解读。
    """
    PRIMARY = "primary"              # 财报/电话会/公司公告/产业链原始数据
    SECONDARY = "secondary"          # 券商研报/行业分析（有加工但有深度）
    TERTIARY = "tertiary"            # 媒体/自媒体/论坛（已多次消化）
    CONSENSUS_NOISE = "noise"        # 全网刷屏的共识噪音


@dataclass
class AlphaSource:
    """信息来源的 Alpha 价值评估。

    回答：「这条信息还有 Alpha 空间吗？」

    当一条消息已在 Twitter/小红书/Reddit/财经自媒体刷屏时，
    它大概率已被市场反复咀嚼过 — 此时 originality_score 极低。
    """
    source_tier: SourceTier = SourceTier.TERTIARY
    originality_score: float = 50.0         # 0-100, 信息一手性
    interpretation_depth: float = 50.0      # 0-100, 理解深度（是否拆了逻辑链）
    noise_ratio: float = 0.5                # 0-1, 噪音比例（越高越像二手解读）
    primary_sources: list[str] = field(default_factory=list)  # 引用的一手材料列表
    tertiary_sources: list[str] = field(default_factory=list)  # 二手/噪音来源
    analysis_chain: list[str] = field(default_factory=list)    # 逻辑链拆解记录
    confidence: float = 0.7                 # 来源判定置信度 0.0-1.0

    @property
    def alpha_potential(self) -> float:
        """综合 Alpha 潜力评分 0-100。

        一手性高 + 理解深 + 噪音低 = Alpha 潜力高。
        全网刷屏的共识噪音 → Alpha 潜力接近 0。
        """
        tier_bonus = {
            SourceTier.PRIMARY: 1.0,
            SourceTier.SECONDARY: 0.7,
            SourceTier.TERTIARY: 0.3,
            SourceTier.CONSENSUS_NOISE: 0.05,
        }
        base = self.originality_score * 0.4 + self.interpretation_depth * 0.4
        noise_penalty = (1.0 - self.noise_ratio) * 20
        tier_multiplier = tier_bonus.get(self.source_tier, 0.5)
        return max(0, min(100, (base + noise_penalty) * tier_multiplier))


# ---------------------------------------------------------------------------
# Consensus Gap — 共识-现实缺口
# ---------------------------------------------------------------------------


@dataclass
class ConsensusGap:
    """市场共识 vs 事实逻辑的偏差检测。

    回答：「市场理解对了吗？还是夸大了？」

    核心理念：
      - 市场知道了这个消息，但理解错了
      - 市场看到了这个风险，但夸大了
      - 市场看到了这个机会，但还没意识到它会变成主线
    """
    market_narrative: str = ""               # 市场当前在讲的故事
    narrative_intensity: float = 0.0         # 0-1, 故事传播强度
    logical_flaws: list[str] = field(default_factory=list)       # 故事中的逻辑漏洞
    exaggeration_score: float = 0.0          # 0-100, 夸大程度（越高越被夸大）
    contrarian_evidence: list[str] = field(default_factory=list) # 反向证据
    gap_score: float = 0.0                   # 0-100, 共识-现实缺口大小
    mispricing_direction: str = "neutral"    # 错误定价方向: "undervalued" / "overvalued" / "neutral"
    mispricing_magnitude: float = 0.0        # 0-100, 错误定价幅度
    confidence: float = 0.7

    @property
    def is_market_wrong(self) -> bool:
        """市场是否可能错了。"""
        return self.gap_score >= 60 and self.confidence >= 0.6

    @property
    def alpha_opportunity(self) -> str:
        """Alpha 机会描述。"""
        if self.gap_score >= 70 and self.mispricing_direction == "undervalued":
            return "市场恐慌过度，可能是买入机会"
        elif self.gap_score >= 70 and self.mispricing_direction == "overvalued":
            return "市场过度乐观，可能是卖出/做空机会"
        elif self.gap_score >= 40:
            return "存在认知偏差，需进一步验证"
        return "市场定价基本有效"


# ---------------------------------------------------------------------------
# Narrative Stage — 叙事生命周期
# ---------------------------------------------------------------------------


class NarrativeLifecycle(Enum):
    """叙事生命周期阶段。

    核心理念：
      无人问津时，研究它。
      逻辑成型时，买入它。
      全网狂欢时，开始卖给相信故事的人。
    """
    DORMANT = "dormant"              # 无人问津 — 研究阶段
    EMERGING = "emerging"            # 逻辑成型 — 买入阶段 ⭐
    SPREADING = "spreading"          # 扩散中 — 持有阶段
    CONSENSUS = "consensus"          # 全网狂欢 — 减仓阶段 ⚠️
    CROWDED = "crowded"              # 过度拥挤 — 卖出阶段 🚨
    FADING = "fading"                # 落幕 — 远离


@dataclass
class NarrativeStage:
    """主题叙事的生命周期定位。

    回答：「我们处于故事的哪个阶段？」

    买点出现在：没人讨论 + 估值没反映 + 逻辑刚出现苗头的时候。
    卖点出现在：全网狂欢 + 所有人都说「确定性太强」的时候。
    """
    stage: NarrativeLifecycle = NarrativeLifecycle.DORMANT
    discussion_volume: float = 0.0           # 讨论量（标准化 0-100）
    discussion_growth_rate: float = 0.0      # 讨论量增速（周环比 %）
    institutional_attention: float = 0.0     # 机构关注度 0-100
    retail_attention: float = 0.0            # 散户关注度 0-100
    valuation_reflected: float = 0.0         # 0-1, 估值已反映程度
    early_signal_score: float = 0.0          # 0-100, 早期信号强度（买入参考）
    crowded_signal_score: float = 0.0        # 0-100, 拥挤信号强度（卖出参考）
    stage_confidence: float = 0.7            # 阶段判定置信度
    last_stage_change: Optional[datetime] = None
    days_in_current_stage: int = 0

    @property
    def is_entry_zone(self) -> bool:
        """是否在买入区域。"""
        return (
            self.stage in (NarrativeLifecycle.DORMANT, NarrativeLifecycle.EMERGING)
            and self.early_signal_score >= 50
            and self.valuation_reflected < 0.6
        )

    @property
    def is_exit_zone(self) -> bool:
        """是否在卖出区域。"""
        return (
            self.stage in (NarrativeLifecycle.CONSENSUS, NarrativeLifecycle.CROWDED)
            and self.crowded_signal_score >= 60
        )

    @property
    def position_cap_pct(self) -> float:
        """叙事阶段决定的仓位上限。"""
        caps = {
            NarrativeLifecycle.DORMANT: 5.0,
            NarrativeLifecycle.EMERGING: 15.0,
            NarrativeLifecycle.SPREADING: 10.0,
            NarrativeLifecycle.CONSENSUS: 5.0,
            NarrativeLifecycle.CROWDED: 0.0,
            NarrativeLifecycle.FADING: 0.0,
        }
        return caps.get(self.stage, 5.0)

    @property
    def action_hint(self) -> str:
        """基于叙事阶段的操作提示。"""
        hints = {
            NarrativeLifecycle.DORMANT: "研究跟踪，可试探性建仓（≤5%）",
            NarrativeLifecycle.EMERGING: "核心建仓窗口，逻辑成型但市场尚未共识",
            NarrativeLifecycle.SPREADING: "持有为主，逢高减仓",
            NarrativeLifecycle.CONSENSUS: "只减不增，分批止盈",
            NarrativeLifecycle.CROWDED: "清仓离场，全网狂欢时卖出",
            NarrativeLifecycle.FADING: "远离，等待下一轮逻辑成型",
        }
        return hints.get(self.stage, "")


# ---------------------------------------------------------------------------
# Alpha Profile — 汇总 DTO
# ---------------------------------------------------------------------------


class AlphaDecayStatus(Enum):
    """Alpha 衰减状态。"""
    FRESH = "fresh"          # 新发现，Alpha 有效
    AGING = "aging"          # 正在衰减
    DECAYED = "decayed"      # 已衰减，Alpha 接近消失
    GONE = "gone"            # Alpha 完全消失，已定价
    CROWDED_OUT = "crowded"  # 被拥挤挤出的 Alpha


@dataclass
class AlphaProfile:
    """Alpha 视角综合分析结果。

    汇总 AlphaSource、ConsensusGap、NarrativeStage 三个维度的结论，
    作为 AnalysisReport.alpha_profile 注入 L1 分析报告。
    """
    # 三维 Alpha 评估
    source: AlphaSource = field(default_factory=AlphaSource)
    consensus_gap: ConsensusGap = field(default_factory=ConsensusGap)
    narrative: NarrativeStage = field(default_factory=NarrativeStage)

    # 综合评分
    alpha_score: float = 50.0                # 综合 Alpha 评分 0-100
    alpha_confidence: float = 0.7             # Alpha 判定总置信度

    # Alpha 衰减追踪
    decay_status: AlphaDecayStatus = AlphaDecayStatus.FRESH
    first_detected: Optional[datetime] = None
    days_since_detection: int = 0
    decay_rate: float = 0.0                  # 0-1, 衰减速度（1=最快）

    # 元信息
    alpha_rationale: str = ""                 # Alpha 判定理由
    key_differentiator: str = ""              # 核心差异点：「我比别人多知道什么？」
    source_citations: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def has_alpha(self) -> bool:
        """是否存在可操作的 Alpha。"""
        return (
            self.alpha_score >= 60
            and self.alpha_confidence >= 0.6
            and self.decay_status in (AlphaDecayStatus.FRESH, AlphaDecayStatus.AGING)
        )

    @property
    def is_priced_in(self) -> bool:
        """Alpha 是否已被市场定价。"""
        return self.decay_status in (AlphaDecayStatus.DECAYED, AlphaDecayStatus.GONE)

    @property
    def summary(self) -> str:
        """Alpha 视角一句话总结。"""
        if not self.has_alpha:
            return "无显著 Alpha — 信息已定价或理解无差异"
        return (
            f"Alpha {self.alpha_score:.0f}/100: "
            f"{self.key_differentiator} "
            f"[叙事: {self.narrative.stage.value}] "
            f"[衰减: {self.decay_status.value}]"
        )


# ---------------------------------------------------------------------------
# Factor Backtest DTOs — 因子回测结果
# ---------------------------------------------------------------------------


@dataclass
class FactorBacktestResult:
    """单因子回测结果。

    包含 IC 分析、分层收益、换手率等核心指标。
    """
    alpha_id: str
    start_date: str
    end_date: str
    n_periods: int = 0
    n_stocks_avg: float = 0.0

    # IC 分析
    ic_mean: float = 0.0                # Rank IC 均值
    ic_std: float = 0.0                 # Rank IC 标准差
    icir: float = 0.0                   # IC / IC_std (信息比率)
    ic_positive_ratio: float = 0.0      # IC > 0 的比例
    ic_t_stat: float = 0.0             # IC t 统计量

    # 分层收益（5 分位）
    top_quintile_return: float = 0.0    # Top 20% 年化收益
    bottom_quintile_return: float = 0.0 # Bottom 20% 年化收益
    long_short_return: float = 0.0      # Top - Bottom 年化收益
    long_short_sharpe: float = 0.0      # 多空夏普

    # 换手率
    avg_turnover: float = 0.0           # 平均月度换手率
    max_turnover: float = 0.0           # 最大月度换手率

    # 稳定性
    ic_decay_20d: float = 0.0           # 20 日 IC 衰减率
    stability_score: float = 0.0        # 综合稳定性 0-100

    # 元信息
    category: str = ""
    warnings: list[str] = field(default_factory=list)
    source_citations: list = field(default_factory=list)

    @property
    def is_effective(self) -> bool:
        """因子是否有效（ICIR ≥ 0.3 且 IC 均值 > 0）。"""
        return self.icir >= 0.3 and self.ic_mean > 0

    @property
    def summary(self) -> str:
        if self.n_periods < 3:
            return f"{self.alpha_id}: 数据不足 ({self.n_periods} 期)"
        return (
            f"{self.alpha_id}: IC={self.ic_mean:+.3f}±{self.ic_std:.3f} "
            f"ICIR={self.icir:.2f} LS={self.long_short_return:+.1%} "
            f"Turnover={self.avg_turnover:.1%} "
            f"[{'✓' if self.is_effective else '✗'}]"
        )


@dataclass
class FactorScanResult:
    """多因子扫描汇总。"""
    results: list[FactorBacktestResult] = field(default_factory=list)
    top_by_icir: list[str] = field(default_factory=list)
    top_by_sharpe: list[str] = field(default_factory=list)
    scan_timestamp: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Alpha Synthesis DTO — 多因子合成
# ---------------------------------------------------------------------------


class SynthesisMethod(Enum):
    """多因子合成方法。"""
    EQUAL_WEIGHT = "equal_weight"
    ICIR_WEIGHT = "icir_weight"
    OPTIMIZED = "optimized"       # 协方差约束最优化


@dataclass
class AlphaSynthesis:
    """多因子合成结果。"""
    method: SynthesisMethod = SynthesisMethod.ICIR_WEIGHT
    alpha_ids: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    combined_score_mean: float = 0.0
    combined_score_std: float = 0.0
    expected_icir: float = 0.0
    factor_contributions: dict[str, float] = field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_valid(self) -> bool:
        return len(self.weights) >= 2 and self.expected_icir > 0


# ---------------------------------------------------------------------------
# Ranking DTO — 全市场排名
# ---------------------------------------------------------------------------


@dataclass
class RankedStock:
    """排名结果中的单只股票。"""
    symbol: str
    name: str = ""
    rank: int = 0
    composite_score: float = 50.0
    factor_scores: dict[str, float] = field(default_factory=dict)
    market_cap: float = 0.0
    sector: str = ""


@dataclass
class RankingResult:
    """全市场 Alpha 排名结果。"""
    synthesis: Optional[AlphaSynthesis] = None
    stocks: list[RankedStock] = field(default_factory=list)
    total_scanned: int = 0
    total_passed: int = 0
    data_gaps: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
