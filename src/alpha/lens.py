# -*- coding: utf-8 -*-
"""Alpha Lens 核心引擎 — 信息来源层级判定、共识-现实缺口检测、叙事生命周期定位。

每个方法回答一个 Alpha 追问：
  - classify_source_tier()  → 「这条信息还有 Alpha 空间吗？」
  - detect_consensus_gap()  → 「市场理解对了吗？还是夸大了？」
  - locate_narrative_stage() → 「我们处于故事的哪个阶段？」
  - compute_alpha_score()   → 「综合 Alpha 有多少？」
"""

from __future__ import annotations

import logging
from typing import Optional

from .schema import (
    AlphaDecayStatus,
    AlphaProfile,
    AlphaSource,
    ConsensusGap,
    NarrativeLifecycle,
    NarrativeStage,
    SourceTier,
)

logger = logging.getLogger(__name__)


class AlphaLens:
    """Alpha Lens 核心引擎。

    用法:
        lens = AlphaLens()
        profile = lens.analyze(
            symbol="600519",
            news_sources=[...],
            market_sentiment="PANIC",
            discussion_data={...},
        )
        print(profile.summary)  # Alpha 72/100: 理解差在供应链映射 ...
    """

    # ------------------------------------------------------------------
    # 信息来源层级判定
    # ------------------------------------------------------------------

    @staticmethod
    def classify_source_tier(
        sources: list[str],
        primary_keywords: Optional[list[str]] = None,
        tertiary_keywords: Optional[list[str]] = None,
    ) -> AlphaSource:
        """根据来源类型判定 SourceTier。

        Args:
            sources: 信息来源列表
            primary_keywords: 自定义一手材料关键词
            tertiary_keywords: 自定义噪音关键词

        Returns:
            AlphaSource with tier classification
        """
        if primary_keywords is None:
            primary_keywords = [
                "财报", "年报", "季报", "半年报", "招股书", "公告", "电话会",
                "earning call", "annual report", "10-K", "10-Q", "SEC filing",
                "互动易", "e互动", "上证e互动", "深交所互动易",
                "巨潮", "cninfo", "证监会", "交易所",
            ]
        if tertiary_keywords is None:
            tertiary_keywords = [
                "自媒体", "公众号", "微博", "小红书", "twitter", "reddit",
                "论坛", "股吧", "雪球", "抖音", "快手",
                "博主", "大V", "网红", "up主",
            ]

        tier_scores: dict[SourceTier, int] = {t: 0 for t in SourceTier}
        primary_list: list[str] = []
        tertiary_list: list[str] = []
        analysis_chain: list[str] = []

        for source in sources:
            source_lower = source.lower()

            # Check primary
            if any(kw in source_lower for kw in [k.lower() for k in primary_keywords]):
                tier_scores[SourceTier.PRIMARY] += 1
                primary_list.append(source)
                analysis_chain.append(f"[一手] {source}")
                continue

            # Check noise
            if any(kw in source_lower for kw in [k.lower() for k in tertiary_keywords]):
                tier_scores[SourceTier.CONSENSUS_NOISE] += 1
                tertiary_list.append(source)
                analysis_chain.append(f"[噪音] {source}")
                continue

            # Default: secondary (券商研报等有一定深度的来源)
            tier_scores[SourceTier.SECONDARY] += 1
            analysis_chain.append(f"[二手] {source}")

        # Determine dominant tier
        total = len(sources)
        if total == 0:
            return AlphaSource(
                source_tier=SourceTier.TERTIARY,
                originality_score=30.0,
                interpretation_depth=30.0,
                confidence=0.3,
            )

        primary_ratio = tier_scores[SourceTier.PRIMARY] / total
        noise_ratio = tier_scores[SourceTier.CONSENSUS_NOISE] / total

        if primary_ratio >= 0.5:
            tier = SourceTier.PRIMARY
        elif primary_ratio >= 0.2:
            tier = SourceTier.SECONDARY
        elif noise_ratio >= 0.5:
            tier = SourceTier.CONSENSUS_NOISE
        elif noise_ratio >= 0.3:
            tier = SourceTier.TERTIARY
        else:
            tier = SourceTier.SECONDARY

        # Calculate scores
        originality = max(0, min(100, primary_ratio * 80 + (1 - noise_ratio) * 20))
        interpretation = max(0, min(100, primary_ratio * 60 + 30))  # baseline 30

        return AlphaSource(
            source_tier=tier,
            originality_score=round(originality, 1),
            interpretation_depth=round(interpretation, 1),
            noise_ratio=round(noise_ratio, 2),
            primary_sources=primary_list,
            tertiary_sources=tertiary_list,
            analysis_chain=analysis_chain,
            confidence=round(0.5 + (primary_ratio * 0.4), 2),
        )

    # ------------------------------------------------------------------
    # 共识-现实缺口检测
    # ------------------------------------------------------------------

    @staticmethod
    def detect_consensus_gap(
        market_narrative: str = "",
        narrative_intensity: float = 0.0,
        logical_flaws: Optional[list[str]] = None,
        contrarian_evidence: Optional[list[str]] = None,
        sentiment_extreme: str = "NEUTRAL",
        expected_reaction: Optional[str] = None,
        actual_reaction: Optional[str] = None,
    ) -> ConsensusGap:
        """检测市场共识与现实之间的缺口。

        Args:
            market_narrative: 市场当前在讲的故事
            narrative_intensity: 故事传播强度 0-1
            logical_flaws: 识别到的逻辑漏洞
            contrarian_evidence: 与共识相反的证据
            sentiment_extreme: 情绪极端程度 (NEUTRAL/GREED/PANIC/EXTREME)
            expected_reaction: 基于事实应有的市场反应
            actual_reaction: 市场实际反应

        Returns:
            ConsensusGap with gap analysis
        """
        flaws = logical_flaws or []
        evidence = contrarian_evidence or []

        # 1. 量化夸大程度: 情绪越极端 + 传播越广 → 越可能被夸大
        sentiment_multiplier = {
            "EXTREME": 1.0,
            "PANIC": 0.8,
            "GREED": 0.8,
            "NEUTRAL": 0.2,
        }
        sentiment_factor = sentiment_multiplier.get(sentiment_extreme, 0.2)
        exaggeration = narrative_intensity * 60 + sentiment_factor * 40
        exaggeration = max(0, min(100, exaggeration))

        # 2. 缺口大小: 逻辑漏洞数 + 反向证据数 + 情绪极端程度
        flaw_score = min(len(flaws) * 15, 40)
        evidence_score = min(len(evidence) * 20, 40)
        sentiment_score = sentiment_factor * 20
        gap = flaw_score + evidence_score + sentiment_score
        gap = max(0, min(100, gap))

        # 3. 错误定价方向
        if sentiment_extreme in ("PANIC", "EXTREME"):
            if narrative_intensity > 0.5:
                direction = "undervalued"  # 恐慌过度 → 可能被低估
            else:
                direction = "neutral"
        elif sentiment_extreme == "GREED" and narrative_intensity > 0.5:
            direction = "overvalued"  # 贪婪过度 → 可能被高估
        else:
            direction = "neutral"

        # 4. 错误定价幅度
        magnitude = gap * 0.7 if direction != "neutral" else gap * 0.2

        # 5. 预期 vs 实际反应偏差
        if expected_reaction and actual_reaction:
            if expected_reaction != actual_reaction:
                gap = min(100, gap + 15)
                flaws.append(
                    f"预期市场反应: {expected_reaction}, 实际: {actual_reaction}"
                )

        confidence = min(0.9, 0.4 + len(flaws) * 0.1 + len(evidence) * 0.1)

        return ConsensusGap(
            market_narrative=market_narrative,
            narrative_intensity=round(narrative_intensity, 2),
            logical_flaws=flaws,
            exaggeration_score=round(exaggeration, 1),
            contrarian_evidence=evidence,
            gap_score=round(gap, 1),
            mispricing_direction=direction,
            mispricing_magnitude=round(magnitude, 1),
            confidence=round(confidence, 2),
        )

    # ------------------------------------------------------------------
    # 叙事生命周期定位
    # ------------------------------------------------------------------

    @staticmethod
    def locate_narrative_stage(
        discussion_volume: float = 0.0,
        discussion_growth_rate: float = 0.0,
        institutional_attention: float = 0.0,
        retail_attention: float = 0.0,
        valuation_reflected: float = 0.0,
        days_since_first_discussion: int = 0,
        large_position_changes: Optional[dict] = None,
    ) -> NarrativeStage:
        """定位叙事生命周期阶段。

        判断逻辑（层次递进）:
          1. 讨论量极低 + 估值未反映      → DORMANT（无人问津）
          2. 讨论量低但开始增长 + 机构先动  → EMERGING（逻辑成型）
          3. 讨论量增长中 + 估值部分反映    → SPREADING（扩散中）
          4. 讨论量高 + 散户主导 + 估值充分  → CONSENSUS（全网狂欢）
          5. 讨论量极高但增长停滞            → CROWDED（过度拥挤）
          6. 讨论量下降 + 无新增逻辑          → FADING（落幕）

        Args:
            discussion_volume: 讨论量（标准化 0-100）
            discussion_growth_rate: 讨论量周环比增速（-100 到 +∞）
            institutional_attention: 机构关注度 0-100
            retail_attention: 散户关注度 0-100
            valuation_reflected: 估值已反映程度 0-1
            days_since_first_discussion: 首次讨论距今多少天
            large_position_changes: 大资金动向 {'institutional': +10%, 'retail': -5%}

        Returns:
            NarrativeStage with lifecycle classification
        """
        # 归一化输入
        vol = max(0, min(100, discussion_volume))
        growth = discussion_growth_rate
        inst = max(0, min(100, institutional_attention))
        retail = max(0, min(100, retail_attention))
        val_ref = max(0, min(1.0, valuation_reflected))

        # 阶段判定
        stage: NarrativeLifecycle
        confidence: float

        if vol < 10 and val_ref < 0.3:
            # 几乎没人讨论 + 估值没反映 → 无人问津
            stage = NarrativeLifecycle.DORMANT
            confidence = 0.85

        elif vol < 25 and growth > 0 and inst > retail and val_ref < 0.5:
            # 讨论量低但开始增长 + 机构先于散户 → 逻辑成型
            stage = NarrativeLifecycle.EMERGING
            confidence = 0.75

        elif vol >= 25 and growth > 0 and val_ref < 0.7:
            # 讨论量持续增长 + 估值尚未完全反映 → 扩散中
            stage = NarrativeLifecycle.SPREADING
            confidence = 0.70

        elif vol >= 60 and growth <= 5 and val_ref >= 0.8:
            # 讨论量极高但增长停滞 + 估值充分 → 过度拥挤 (先于 CONSENSUS)
            stage = NarrativeLifecycle.CROWDED
            confidence = 0.80

        elif vol >= 50 and retail > inst and val_ref >= 0.6:
            # 讨论量大 + 散户主导 + 估值较充分 → 全网狂欢
            stage = NarrativeLifecycle.CONSENSUS
            confidence = 0.80

        elif growth < -10 and vol > 20:
            # 讨论量下降 + 无新增 → 落幕
            stage = NarrativeLifecycle.FADING
            confidence = 0.75

        else:
            # 默认：根据讨论量和估值反映程度粗判
            if vol < 20:
                stage = NarrativeLifecycle.DORMANT
                confidence = 0.5
            elif vol < 50:
                stage = NarrativeLifecycle.SPREADING
                confidence = 0.5
            elif val_ref >= 0.8:
                stage = NarrativeLifecycle.CROWDED
                confidence = 0.6
            else:
                stage = NarrativeLifecycle.CONSENSUS
                confidence = 0.5

        # 大资金动向修正
        if large_position_changes:
            inst_change = large_position_changes.get("institutional", 0)
            retail_change = large_position_changes.get("retail", 0)
            # 机构增持 + 散户减持 → 可能仍在早期
            if inst_change > 0 and retail_change < 0 and stage in (
                NarrativeLifecycle.SPREADING,
                NarrativeLifecycle.CONSENSUS,
            ):
                stage = NarrativeLifecycle.EMERGING
                confidence = max(confidence, 0.65)
            # 机构减持 + 散户增持 → 可能已拥挤
            if inst_change < 0 and retail_change > 0 and stage == NarrativeLifecycle.SPREADING:
                stage = NarrativeLifecycle.CONSENSUS
                confidence = max(confidence, 0.70)

        # 计算辅助信号
        early_signal = _calc_early_signal(vol, growth, inst, retail, val_ref)
        crowded_signal = _calc_crowded_signal(vol, growth, inst, retail, val_ref)

        return NarrativeStage(
            stage=stage,
            discussion_volume=round(vol, 1),
            discussion_growth_rate=round(growth, 1),
            institutional_attention=round(inst, 1),
            retail_attention=round(retail, 1),
            valuation_reflected=round(val_ref, 2),
            early_signal_score=round(early_signal, 1),
            crowded_signal_score=round(crowded_signal, 1),
            stage_confidence=round(confidence, 2),
            days_in_current_stage=days_since_first_discussion,
        )

    # ------------------------------------------------------------------
    # 综合 Alpha 评分
    # ------------------------------------------------------------------

    @staticmethod
    def compute_alpha_score(
        source: AlphaSource,
        consensus_gap: ConsensusGap,
        narrative: NarrativeStage,
    ) -> float:
        """综合三个维度计算 Alpha 评分。

        公式:
          alpha_score = source.alpha_potential * 0.3
                      + consensus_gap.gap_score * 0.35
                      + narrative_stage_bonus * 0.35

        叙事阶段 Alpha 乘数:
          DORMANT:    0.6 (可能太早)
          EMERGING:   0.9 (最佳 Alpha 窗口)
          SPREADING:  0.7 (Alpha 在减少)
          CONSENSUS:  0.3 (Alpha 基本消失)
          CROWDED:    0.1 (几乎无 Alpha)
          FADING:     0.0 (无 Alpha)

        Returns:
            Alpha 综合评分 0-100
        """
        stage_multipliers = {
            NarrativeLifecycle.DORMANT: 0.6,
            NarrativeLifecycle.EMERGING: 0.9,
            NarrativeLifecycle.SPREADING: 0.7,
            NarrativeLifecycle.CONSENSUS: 0.3,
            NarrativeLifecycle.CROWDED: 0.1,
            NarrativeLifecycle.FADING: 0.0,
        }
        stage_mult = stage_multipliers.get(narrative.stage, 0.5)

        source_score = source.alpha_potential
        gap_score = consensus_gap.gap_score
        narrative_score = narrative.early_signal_score * stage_mult

        alpha = source_score * 0.3 + gap_score * 0.35 + narrative_score * 0.35
        return round(max(0, min(100, alpha)), 1)

    # ------------------------------------------------------------------
    # 主入口: 综合分析
    # ------------------------------------------------------------------

    def analyze(
        self,
        symbol: str = "",
        news_sources: Optional[list[str]] = None,
        market_narrative: str = "",
        narrative_intensity: float = 0.0,
        logical_flaws: Optional[list[str]] = None,
        contrarian_evidence: Optional[list[str]] = None,
        sentiment_extreme: str = "NEUTRAL",
        discussion_volume: float = 0.0,
        discussion_growth_rate: float = 0.0,
        institutional_attention: float = 0.0,
        retail_attention: float = 0.0,
        valuation_reflected: float = 0.0,
        days_since_first_discussion: int = 0,
        large_position_changes: Optional[dict] = None,
        existing_profile: Optional[AlphaProfile] = None,
    ) -> AlphaProfile:
        """综合分析 — 一次调用完成三维 Alpha 评估。

        Args:
            symbol: 股票代码
            news_sources: 信息来源列表
            market_narrative: 市场叙事
            narrative_intensity: 叙事强度 0-1
            logical_flaws: 逻辑漏洞
            contrarian_evidence: 反向证据
            sentiment_extreme: 情绪极端程度
            discussion_volume: 讨论量 0-100
            discussion_growth_rate: 讨论增速
            institutional_attention: 机构关注度
            retail_attention: 散户关注度
            valuation_reflected: 估值反映度 0-1
            days_since_first_discussion: 首次讨论距今
            large_position_changes: 大资金动向
            existing_profile: 已有 profile（用于衰减追踪）

        Returns:
            AlphaProfile with complete analysis
        """
        # 1. 信息来源层级
        source = self.classify_source_tier(news_sources or [])

        # 2. 共识-现实缺口
        consensus_gap = self.detect_consensus_gap(
            market_narrative=market_narrative,
            narrative_intensity=narrative_intensity,
            logical_flaws=logical_flaws,
            contrarian_evidence=contrarian_evidence,
            sentiment_extreme=sentiment_extreme,
        )

        # 3. 叙事生命周期
        narrative = self.locate_narrative_stage(
            discussion_volume=discussion_volume,
            discussion_growth_rate=discussion_growth_rate,
            institutional_attention=institutional_attention,
            retail_attention=retail_attention,
            valuation_reflected=valuation_reflected,
            days_since_first_discussion=days_since_first_discussion,
            large_position_changes=large_position_changes,
        )

        # 4. 综合评分
        alpha_score = self.compute_alpha_score(source, consensus_gap, narrative)

        # 5. 衰减追踪
        decay = self._compute_decay(existing_profile, alpha_score)

        # 6. 生成 rationale
        rationale, differentiator = self._generate_rationale(
            source, consensus_gap, narrative, alpha_score, decay[0]
        )

        return AlphaProfile(
            source=source,
            consensus_gap=consensus_gap,
            narrative=narrative,
            alpha_score=alpha_score,
            alpha_confidence=self._calc_confidence(source, consensus_gap, narrative),
            decay_status=decay[0],
            first_detected=(
                existing_profile.first_detected if existing_profile else None
            ),
            days_since_detection=decay[1],
            decay_rate=decay[2],
            alpha_rationale=rationale,
            key_differentiator=differentiator,
        )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _compute_decay(
        self,
        existing: Optional[AlphaProfile],
        current_alpha_score: float,
    ) -> tuple[AlphaDecayStatus, int, float]:
        """计算 Alpha 衰减状态。

        Returns:
            (decay_status, days_since_detection, decay_rate)
        """
        from datetime import datetime, timedelta

        if existing and existing.first_detected:
            days = (datetime.now() - existing.first_detected).days
            if existing.alpha_score > 0:
                decay_rate = max(0, min(1, (existing.alpha_score - current_alpha_score)
                                        / existing.alpha_score))
            else:
                decay_rate = 0.5

            if current_alpha_score >= 60:
                status = AlphaDecayStatus.FRESH
            elif current_alpha_score >= 40:
                status = AlphaDecayStatus.AGING
            elif current_alpha_score >= 20:
                status = AlphaDecayStatus.DECAYED
            else:
                status = AlphaDecayStatus.GONE
            return status, days, round(decay_rate, 2)

        # New detection
        if current_alpha_score >= 50:
            return AlphaDecayStatus.FRESH, 0, 0.0
        return AlphaDecayStatus.AGING, 0, 0.0

    @staticmethod
    def _calc_confidence(
        source: AlphaSource,
        gap: ConsensusGap,
        narrative: NarrativeStage,
    ) -> float:
        """计算 Alpha 判定总置信度。"""
        conf = (
            source.confidence * 0.3
            + gap.confidence * 0.35
            + narrative.stage_confidence * 0.35
        )
        return round(max(0, min(1.0, conf)), 2)

    @staticmethod
    def _generate_rationale(
        source: AlphaSource,
        gap: ConsensusGap,
        narrative: NarrativeStage,
        alpha_score: float,
        decay_status: AlphaDecayStatus,
    ) -> tuple[str, str]:
        """生成 Alpha 判定理由和核心差异点。"""
        parts: list[str] = []

        # 信息来源维度
        tier_desc = {
            SourceTier.PRIMARY: "信息来源一手性强",
            SourceTier.SECONDARY: "信息来源有一定加工",
            SourceTier.TERTIARY: "信息已被多次传播",
            SourceTier.CONSENSUS_NOISE: "信息已成共识噪音",
        }
        parts.append(tier_desc.get(source.source_tier, ""))

        # 共识缺口维度
        if gap.is_market_wrong:
            parts.append(
                f"市场共识可能存在偏差 (gap={gap.gap_score:.0f})"
            )
        elif gap.gap_score >= 30:
            parts.append(f"市场共识部分存疑 (gap={gap.gap_score:.0f})")
        else:
            parts.append("市场共识基本有效")

        # 叙事维度
        stage_desc = {
            NarrativeLifecycle.DORMANT: "叙事处于无人问津期",
            NarrativeLifecycle.EMERGING: "叙事处于逻辑成型期（最佳Alpha窗口）",
            NarrativeLifecycle.SPREADING: "叙事正在扩散中",
            NarrativeLifecycle.CONSENSUS: "叙事已形成全网共识",
            NarrativeLifecycle.CROWDED: "叙事已过度拥挤",
            NarrativeLifecycle.FADING: "叙事正在落幕",
        }
        parts.append(stage_desc.get(narrative.stage, ""))

        rationale = "；".join(parts)

        # 核心差异点
        if gap.is_market_wrong:
            differentiator = f"市场可能{'低估' if gap.mispricing_direction == 'undervalued' else '高估'}了该标的价值"
        elif narrative.stage in (NarrativeLifecycle.DORMANT, NarrativeLifecycle.EMERGING):
            differentiator = "叙事尚未被市场充分定价，存在提前布局窗口"
        elif narrative.stage in (NarrativeLifecycle.CONSENSUS, NarrativeLifecycle.CROWDED):
            differentiator = "市场共识已充分定价，Alpha 空间有限"
        else:
            differentiator = "暂无明显认知差异"

        return rationale, differentiator


# ---------------------------------------------------------------------------
# 辅助计算函数
# ---------------------------------------------------------------------------


def _calc_early_signal(
    vol: float,
    growth: float,
    inst: float,
    retail: float,
    val_ref: float,
) -> float:
    """计算早期信号强度（买入参考）。

    高早期信号 = 讨论量低但开始增长 + 机构先于散户 + 估值未充分反映
    """
    signal = 0.0

    # 讨论量低（未被发现）→ 加分
    if vol < 15:
        signal += 30
    elif vol < 30:
        signal += 15

    # 讨论量开始增长 → 加分
    if 5 < growth <= 30:
        signal += 25
    elif growth > 30:
        signal += 15  # 增长过快可能已经是扩散期

    # 机构先于散户 → 加分
    if inst > retail and inst > 20:
        signal += 25

    # 估值未充分反映 → 加分
    if val_ref < 0.3:
        signal += 20
    elif val_ref < 0.5:
        signal += 10

    return max(0, min(100, signal))


def _calc_crowded_signal(
    vol: float,
    growth: float,
    inst: float,
    retail: float,
    val_ref: float,
) -> float:
    """计算拥挤信号强度（卖出参考）。

    高拥挤信号 = 讨论量极高 + 增长停滞 + 散户主导 + 估值充分反映
    """
    signal = 0.0

    # 讨论量极高 → 加分
    if vol > 75:
        signal += 30
    elif vol > 50:
        signal += 15

    # 增长停滞甚至下降 → 加分
    if -5 <= growth <= 5 and vol > 40:
        signal += 25
    elif growth < -5:
        signal += 15

    # 散户主导、机构撤退 → 加分
    if retail > inst and retail > 50:
        signal += 25

    # 估值充分反映 → 加分
    if val_ref > 0.8:
        signal += 20
    elif val_ref > 0.6:
        signal += 10

    return max(0, min(100, signal))
