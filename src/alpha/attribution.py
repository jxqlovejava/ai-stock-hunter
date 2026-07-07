# -*- coding: utf-8 -*-
"""Alpha 归因引擎 — 分解收益来源，评估 Alpha 质量。

回答：「赚钱是因为 Alpha（理解正确）还是 Beta（大盘涨）？」

核心理念：
  大多数时候市场是有效的，赚钱可能只是 Beta。
  真正的 Alpha 来自：理解差 > 信息差，冷静 > 情绪，前瞻 > 跟风。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .schema import (
    AlphaProfile,
    NarrativeLifecycle,
    SourceTier,
)

logger = logging.getLogger(__name__)


@dataclass
class AttributionReport:
    """Alpha 归因报告。"""
    symbol: str
    period_start: datetime
    period_end: datetime

    # 收益分解
    total_return_pct: float = 0.0
    market_beta_return_pct: float = 0.0      # 大盘涨跌贡献
    sector_beta_return_pct: float = 0.0       # 行业涨跌贡献
    alpha_return_pct: float = 0.0             # 纯 Alpha 贡献
    residual_return_pct: float = 0.0          # 不可解释部分（运气/噪音）

    # Alpha 质量评估
    alpha_quality_score: float = 50.0         # Alpha 来源质量 0-100
    source_quality_score: float = 50.0         # 信息来源质量
    timing_quality_score: float = 50.0         # 时机把握质量
    sizing_quality_score: float = 50.0         # 仓位管理质量

    # 归因详情
    alpha_sources: list[str] = field(default_factory=list)        # Alpha 来源列表
    key_insights: list[str] = field(default_factory=list)          # 关键洞察
    mistakes: list[str] = field(default_factory=list)              # 错误复盘
    improvement_suggestions: list[str] = field(default_factory=list)  # 改进建议

    # 衰减追踪
    alpha_half_life_days: Optional[float] = None   # Alpha 半衰期
    exit_timing_quality: float = 50.0              # 退出时机质量

    confidence: float = 0.7

    @property
    def is_alpha_driven(self) -> bool:
        """是否以 Alpha 驱动为主（而非 Beta 驱动）。"""
        return self.alpha_return_pct > abs(self.market_beta_return_pct)

    @property
    def alpha_efficiency(self) -> float:
        """Alpha 效率 = Alpha 收益 / 总收益。"""
        if abs(self.total_return_pct) < 0.01:
            return 0.0
        return max(0, min(1.0, self.alpha_return_pct / abs(self.total_return_pct)))


class AlphaAttribution:
    """Alpha 归因引擎。

    用法:
        attr = AlphaAttribution()
        report = attr.attribute(
            symbol="600519",
            total_return=15.0,
            market_return=5.0,
            sector_return=8.0,
            entry_profile=entry_alpha,
            exit_profile=exit_alpha,
        )
        print(f"Alpha 贡献: {report.alpha_return_pct:.1f}%")
        print(f"Alpha 效率: {report.alpha_efficiency:.1%}")
    """

    # ------------------------------------------------------------------
    # 收益分解
    # ------------------------------------------------------------------

    @staticmethod
    def decompose_return(
        total_return_pct: float,
        market_return_pct: float = 0.0,
        sector_return_pct: float = 0.0,
        stock_beta: float = 1.0,
    ) -> tuple[float, float, float, float]:
        """分解收益来源：Beta（大盘+行业）+ Alpha + 残差。

        Args:
            total_return_pct: 总收益 %
            market_return_pct: 大盘同期收益 %
            sector_return_pct: 行业同期收益 %
            stock_beta: 股票 Beta 系数

        Returns:
            (market_beta_return, sector_beta_return, alpha_return, residual)
        """
        # 市场 Beta 贡献
        market_contrib = market_return_pct * stock_beta

        # 行业 Beta 贡献（扣除市场重叠部分）
        sector_contrib = sector_return_pct * 0.7  # 行业 beta 通常 < 1

        # Alpha = 总收益 - 所有 Beta 贡献
        beta_total = market_contrib + sector_contrib
        alpha = total_return_pct - beta_total

        # 残差（无法归因的部分）
        residual = 0.0
        if abs(total_return_pct) > 0.01 and abs(alpha) > abs(total_return_pct) * 2:
            # Alpha 过大不合理，标记为残差
            residual = alpha
            alpha = 0.0

        return (
            round(market_contrib, 2),
            round(sector_contrib, 2),
            round(alpha, 2),
            round(residual, 2),
        )

    # ------------------------------------------------------------------
    # Alpha 质量评估
    # ------------------------------------------------------------------

    @staticmethod
    def evaluate_alpha_quality(
        entry_profile: Optional[AlphaProfile] = None,
        exit_profile: Optional[AlphaProfile] = None,
        position_sizing: str = "standard",
        holding_period_days: int = 0,
    ) -> tuple[float, float, float, float]:
        """评估 Alpha 来源质量。

        四个维度：
          1. 信息来源质量：是否一手材料、理解深度
          2. 时机把握质量：叙事阶段是否在 EMERGING 买入、CONSENSUS+ 卖出
          3. 仓位管理质量：仓位是否匹配 Alpha 阶段
          4. 综合质量：三维加权

        Returns:
            (source_quality, timing_quality, sizing_quality, overall_quality)
        """
        # 1. 信息来源质量
        source_quality = 50.0
        if entry_profile:
            src = entry_profile.source
            source_quality = (
                src.originality_score * 0.4
                + src.interpretation_depth * 0.4
                + (1 - src.noise_ratio) * 20
            )
            source_quality = max(0, min(100, source_quality))

        # 2. 时机把握质量
        timing_quality = 50.0
        if entry_profile:
            narrative = entry_profile.narrative
            # EMERGING 买入 = 最佳时机
            if narrative.stage == NarrativeLifecycle.EMERGING:
                timing_quality = 85.0
            elif narrative.stage == NarrativeLifecycle.DORMANT:
                timing_quality = 65.0  # 可能太早但方向对
            elif narrative.stage == NarrativeLifecycle.SPREADING:
                timing_quality = 60.0  # Alpha 在减少中
            elif narrative.stage == NarrativeLifecycle.CONSENSUS:
                timing_quality = 30.0  # 太晚
            else:
                timing_quality = 20.0

            # 早期信号加分
            if narrative.early_signal_score > 60:
                timing_quality += 10

        # 退出时机追加
        if exit_profile:
            exit_narrative = exit_profile.narrative
            if exit_narrative.stage in (
                NarrativeLifecycle.CONSENSUS,
                NarrativeLifecycle.CROWDED,
            ):
                timing_quality += 10  # 在拥挤时卖出 = 好时机
            elif exit_narrative.stage == NarrativeLifecycle.EMERGING:
                timing_quality -= 20  # 在 Alpha 早期就卖了 = 时机差

        timing_quality = max(0, min(100, timing_quality))

        # 3. 仓位管理质量
        position_mult = {
            "underweight": 0.7,
            "standard": 1.0,
            "overweight": 1.3,
            "max": 0.8,  # 满仓不是最优
        }
        sizing_quality = 50.0 * position_mult.get(position_sizing, 1.0)
        # 持仓时间越短、越依赖时机 → 仓位管理越重要
        if holding_period_days < 30:
            sizing_quality += 10  # 短线：仓位管理重要
        elif holding_period_days > 180:
            sizing_quality -= 10  # 长线：仓位管理次要

        sizing_quality = max(0, min(100, sizing_quality))

        # 4. 综合质量
        overall = source_quality * 0.35 + timing_quality * 0.40 + sizing_quality * 0.25
        overall = max(0, min(100, overall))

        return (
            round(source_quality, 1),
            round(timing_quality, 1),
            round(sizing_quality, 1),
            round(overall, 1),
        )

    # ------------------------------------------------------------------
    # 主入口: 归因分析
    # ------------------------------------------------------------------

    def attribute(
        self,
        symbol: str,
        total_return_pct: float,
        market_return_pct: float = 0.0,
        sector_return_pct: float = 0.0,
        stock_beta: float = 1.0,
        entry_profile: Optional[AlphaProfile] = None,
        exit_profile: Optional[AlphaProfile] = None,
        position_sizing: str = "standard",
        holding_period_days: int = 0,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> AttributionReport:
        """执行完整 Alpha 归因分析。

        Args:
            symbol: 股票代码
            total_return_pct: 总收益率 %
            market_return_pct: 大盘同期收益率 %
            sector_return_pct: 行业同期收益率 %
            stock_beta: 股票 Beta
            entry_profile: 买入时的 AlphaProfile
            exit_profile: 卖出时的 AlphaProfile
            position_sizing: 仓位规模描述
            holding_period_days: 持仓天数
            period_start: 分析起始时间
            period_end: 分析结束时间

        Returns:
            AttributionReport with full analysis
        """
        now = datetime.now()

        # 1. 收益分解
        market_beta, sector_beta, alpha, residual = self.decompose_return(
            total_return_pct, market_return_pct, sector_return_pct, stock_beta
        )

        # 2. Alpha 质量评估
        source_q, timing_q, sizing_q, overall_q = self.evaluate_alpha_quality(
            entry_profile, exit_profile, position_sizing, holding_period_days
        )

        # 3. 生成洞察
        key_insights, mistakes, suggestions = self._generate_insights(
            symbol=symbol,
            alpha_return=alpha,
            total_return=total_return_pct,
            market_beta=market_beta,
            entry_profile=entry_profile,
            exit_profile=exit_profile,
            holding_days=holding_period_days,
        )

        # 4. Alpha 来源标记
        alpha_sources = self._identify_alpha_sources(entry_profile)

        # 5. Alpha 半衰期
        half_life = self._estimate_half_life(entry_profile)

        # 6. 退出时机
        exit_timing = 50.0
        if exit_profile:
            if exit_profile.narrative.stage in (
                NarrativeLifecycle.CONSENSUS,
                NarrativeLifecycle.CROWDED,
            ):
                exit_timing = 85.0
            elif exit_profile.narrative.crowded_signal_score > 60:
                exit_timing = 75.0
            elif exit_profile.narrative.stage == NarrativeLifecycle.FADING:
                exit_timing = 60.0
            else:
                exit_timing = 40.0  # 退出过早

        return AttributionReport(
            symbol=symbol,
            period_start=period_start or now,
            period_end=period_end or now,
            total_return_pct=round(total_return_pct, 2),
            market_beta_return_pct=market_beta,
            sector_beta_return_pct=sector_beta,
            alpha_return_pct=alpha,
            residual_return_pct=residual,
            alpha_quality_score=overall_q,
            source_quality_score=source_q,
            timing_quality_score=timing_q,
            sizing_quality_score=sizing_q,
            alpha_sources=alpha_sources,
            key_insights=key_insights,
            mistakes=mistakes,
            improvement_suggestions=suggestions,
            alpha_half_life_days=half_life,
            exit_timing_quality=exit_timing,
            confidence=round(
                0.5 + (0.3 if entry_profile else 0) + (0.2 if exit_profile else 0), 2
            ),
        )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _identify_alpha_sources(profile: Optional[AlphaProfile]) -> list[str]:
        """识别 Alpha 来源维度。"""
        if profile is None:
            return ["未追踪 Alpha 来源"]

        sources: list[str] = []

        src = profile.source
        if src.source_tier == SourceTier.PRIMARY:
            sources.append("一手信息优势")
        if src.interpretation_depth > 60:
            sources.append("深度理解差")
        if src.originality_score > 70:
            sources.append("信息时效优势")

        gap = profile.consensus_gap
        if gap.is_market_wrong:
            sources.append(f"共识偏差套利 ({gap.mispricing_direction})")
        if gap.gap_score > 50:
            sources.append("情绪极值反向")

        narrative = profile.narrative
        if narrative.stage in (NarrativeLifecycle.DORMANT, NarrativeLifecycle.EMERGING):
            sources.append("叙事早期布局")
        if narrative.early_signal_score > 60:
            sources.append("前瞻性研究")

        if not sources:
            sources.append("因素驱动（非典型 Alpha）")

        return sources

    @staticmethod
    def _generate_insights(
        symbol: str,
        alpha_return: float,
        total_return: float,
        market_beta: float,
        entry_profile: Optional[AlphaProfile],
        exit_profile: Optional[AlphaProfile],
        holding_days: int,
    ) -> tuple[list[str], list[str], list[str]]:
        """生成归因洞察、错误和改进建议。"""
        insights: list[str] = []
        mistakes: list[str] = []
        suggestions: list[str] = []

        # Alpha vs Beta 洞察
        if alpha_return > 0 and alpha_return > abs(market_beta):
            insights.append(
                f"Alpha 驱动型收益：{alpha_return:+.1f}% vs Beta {market_beta:+.1f}%，"
                "超额收益来自认知差异"
            )
        elif alpha_return > 0:
            insights.append(
                f"Alpha+Beta 共同贡献：Alpha {alpha_return:+.1f}% + Beta {market_beta:+.1f}%"
            )
        elif alpha_return < 0 and total_return > 0:
            insights.append(
                f"Beta 驱动型收益：Alpha {alpha_return:+.1f}%，"
                "收益主要来自大盘上涨，非选股能力"
            )
            mistakes.append("正收益但 Alpha 为负 — 可能是运气而非能力")

        # 来源质量洞察
        if entry_profile:
            if entry_profile.source.source_tier == SourceTier.PRIMARY:
                insights.append("信息来源于一手材料，Alpha 质量较高")
            elif entry_profile.source.source_tier == SourceTier.CONSENSUS_NOISE:
                mistakes.append("信息来源为共识噪音 — 应减少二手信息依赖")
                suggestions.append("多读财报原文、电话会记录，少看自媒体解读")

        # 叙事定位洞察
        if entry_profile:
            stage = entry_profile.narrative.stage
            if stage == NarrativeLifecycle.EMERGING:
                insights.append("在叙事逻辑成型期介入，时机优秀")
            elif stage in (NarrativeLifecycle.CONSENSUS, NarrativeLifecycle.CROWDED):
                mistakes.append(f"在叙事 {stage.value} 阶段买入 — 已错过 Alpha 窗口")
                suggestions.append("下次在讨论量低、机构先动时介入")

        # 退出洞察
        if exit_profile:
            if exit_profile.narrative.crowded_signal_score > 60:
                insights.append("在拥挤信号出现时退出，纪律性好")
            else:
                suggestions.append("关注拥挤信号，在共识形成时分批退出")

        # 持仓周期洞察
        if holding_days > 0 and holding_days < 7:
            insights.append(f"短期交易 ({holding_days}天) — Alpha 衰减快，需快速反应")
        elif holding_days > 90:
            insights.append(f"长期持有 ({holding_days}天) — Alpha 需持续跟踪衰减")

        return insights, mistakes, suggestions

    @staticmethod
    def _estimate_half_life(profile: Optional[AlphaProfile]) -> Optional[float]:
        """估算 Alpha 半衰期（天）。

        Alpha 来源越一手、叙事越早期 → 半衰期越长。
        """
        if profile is None:
            return None

        base_half_life = 30.0  # 默认 30 天

        # 一手材料 → 更长
        if profile.source.source_tier == SourceTier.PRIMARY:
            base_half_life *= 1.5
        elif profile.source.source_tier == SourceTier.CONSENSUS_NOISE:
            base_half_life *= 0.3

        # 理解深度 → 更长
        if profile.source.interpretation_depth > 70:
            base_half_life *= 1.3

        # 叙事阶段 → 早期更长
        if profile.narrative.stage == NarrativeLifecycle.DORMANT:
            base_half_life *= 1.5
        elif profile.narrative.stage == NarrativeLifecycle.EMERGING:
            base_half_life *= 1.2
        elif profile.narrative.stage in (
            NarrativeLifecycle.CONSENSUS,
            NarrativeLifecycle.CROWDED,
        ):
            base_half_life *= 0.4

        return round(base_half_life, 1)
