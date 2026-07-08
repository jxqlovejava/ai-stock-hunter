# -*- coding: utf-8 -*-
"""综合裁决 — 加权评分 + 置信度 + 反共识检查 + 主题生命周期调整。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .diagnosis import DiagnosisReport


@dataclass
class Verdict:
    """综合裁决结果。"""
    symbol: str
    score: float = 50.0                        # 0-100
    confidence: float = 0.5                  # 0.0-1.0
    recommendation: str = "HOLD"             # BUY / ADD / HOLD / REDUCE / SELL
    falsifiable: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    topic_adjustments: dict = field(default_factory=dict)  # Phase 3: topic lifecycle adjustments
    source_citations: list = field(default_factory=list)  # Phase 1: 继承自诊断阶段的引用
    # Phase 4: Alpha Lens 输出
    alpha_rationale: str = ""              # 为什么这个判断有 Alpha
    consensus_challenge: str = ""          # 市场可能错在哪
    alpha_multiplier: float = 1.0          # Alpha 权重乘数 (0.5-1.5)
    executive_risks: list[str] = field(default_factory=list)  # V4: 高管风险
    # Phase 6: 博弈论 + 投资思维模型
    game_theory_adjustment: dict = field(default_factory=dict)
    game_theory_risks: list[str] = field(default_factory=list)
    mental_model_fit_score: float = 0.0
    mental_model_warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


class VerdictEngine:
    """综合裁决引擎。

    评分权重:
      - 基本面 (诊断 价值 + 质量): 30%
      - 估值 (诊断 多维估值): 15%
      - 技术面 (诊断 动量): 15%
      - 宏观适配: 10%
      - 周期阶段: 10%
      - 行业景气: 10%
      - 情绪溢价: 5%
      - 高管: 5%

    置信度 < 0.6 不进入仓位调度。
    Phase 3: 主题生命周期调整 (topic_adj) 影响行业权重。
    """

    WEIGHTS = {
        "fundamental": 0.30,
        "valuation": 0.15,
        "technical": 0.15,
        "macro": 0.10,
        "cycle": 0.10,
        "sector": 0.10,
        "sentiment": 0.05,
        "executive": 0.05,
    }

    MIN_CONFIDENCE = 0.55  # 0.6→0.55: 四视角辩论+推测标记叠加后，中等置信度仍可通过

    def judge(
        self,
        report: DiagnosisReport,
        sector_score: float = 50.0,
        topic_adj: Optional[dict] = None,
        weights_override: Optional[dict] = None,
    ) -> Verdict:
        """综合评分，生成裁决。

        Args:
            report: 诊断报告
            sector_score: 行业景气评分 (0-100)
            topic_adj: 主题生命周期权重调整 {topic_id: bonus}, bonus in [-0.2, +0.1]
            weights_override: 自定义权重 dict，覆盖 class-level WEIGHTS。
                              None 时使用默认权重。非 None 时自动归一化。
        """
        fundamental = (report.value_score + report.quality_score) / 2
        valuation = report.valuation_score
        technical = report.momentum_score
        macro = report.macro_score
        cycle = report.cycle_score
        executive_score = report.executive_score
        sentiment = self._sentiment_adj(report.sentiment_signal)

        # Phase 4: Alpha Lens 乘数调整
        alpha_mult, alpha_rationale, consensus_challenge = self._alpha_multiplier(report)

        # Phase 3: 主题生命周期调整
        adjusted_sector = sector_score
        topic_info: dict = {}
        if topic_adj:
            adjusted_sector, topic_info = self._apply_topic_adjustment(sector_score, topic_adj)

        # 解析权重
        weights = self.WEIGHTS.copy()
        if weights_override:
            weights.update(weights_override)
            total = sum(weights.values())
            if abs(total - 1.0) > 0.01:
                weights = {k: v / total for k, v in weights.items()}

        raw_score = (
            fundamental * weights["fundamental"]
            + valuation * weights.get("valuation", 0.15)
            + technical * weights["technical"]
            + macro * weights["macro"]
            + cycle * weights.get("cycle", 0.10)
            + adjusted_sector * weights["sector"]
            + sentiment * weights["sentiment"]
            + executive_score * weights.get("executive", 0.05)
        )

        # Phase 4: Alpha Lens 乘数 — Alpha 放大/缩小总评分
        score = max(0, min(100, raw_score * alpha_mult))

        # Phase 6: 博弈论 + 投资思维模型乘数
        gt_profile = getattr(report, "game_theory_profile", None)
        imm_fit = getattr(report, "investor_mental_model", None)
        gt_mult = 1.0
        mm_mult = 1.0
        gt_score = 50
        mm_score = 50
        gt_risks: list[str] = []
        mm_warnings: list[str] = []
        mm_bias_flags: list[str] = []
        if gt_profile is not None:
            gt_score = gt_profile.score
            gt_mult = 0.9 + 0.2 * (gt_score - 50) / 50.0
            gt_risks = gt_profile.risks
        if imm_fit is not None:
            mm_score = imm_fit.fit_score
            mm_mult = 0.9 + 0.2 * (mm_score - 50) / 50.0
            mm_warnings = imm_fit.warnings
            mm_bias_flags = imm_fit.bias_flags
        score = max(0, min(100, score * gt_mult * mm_mult))

        # 置信度 = 信息完整度的函数
        confidence_inputs = [fundamental, valuation, macro, cycle, adjusted_sector]
        if gt_profile is not None:
            confidence_inputs.append(gt_score)
        if imm_fit is not None:
            confidence_inputs.append(mm_score)
        confidence = 0.5 + 0.3 * (min(confidence_inputs) / 50.0)
        confidence = min(confidence, 0.95)

        # Phase 6+: 四视角辩论分歧降低置信度
        debate = getattr(report, "debate_result", None)
        if debate is not None:
            agreement = getattr(debate, "agreement_level", "")
            score_range = getattr(debate, "score_range", 0.0) or 0.0
            if agreement == "polarized":
                confidence *= 0.85
            elif agreement == "divided":
                confidence *= 0.95
            if score_range > 2.5:
                confidence *= 0.90
        confidence = round(max(0.0, min(0.95, confidence)), 2)

        # 建议映射
        if score >= 75:
            rec = "BUY"
        elif score >= 60:
            rec = "ADD"
        elif score >= 40:
            rec = "HOLD"
        elif score >= 25:
            rec = "REDUCE"
        else:
            rec = "SELL"

        # 可证伪条件
        falsifiable = [
            "如果宏观 PMI < 48，建议失效",
            "如果标的 PE 超过历史 70% 分位，建议失效",
            f"如果经济周期为 CONTRACTION 或 TROUGH (当前: {report.cycle_phase})，建议效力减半",
        ]
        if gt_profile:
            falsifiable.append(f"如果主导玩家变更为 {gt_profile.dominant_player} 的对立方且持续 3 日，建议失效")

        # 风险提示
        risks = []
        if report.macro_score < 40:
            risks.append("宏观环境偏空")
        if report.cycle_score < 30:
            risks.append(f"经济周期偏空 ({report.cycle_phase})，注意系统性风险")
        if report.valuation_score > 80:
            risks.append("估值极低 — 可能存在基本面隐忧或价值陷阱")
        if report.valuation_score < 20:
            risks.append("估值过高 — 泡沫风险显著")
        if report.sentiment_signal == "PANIC":
            risks.append("市场恐慌中，注意流动性")
        # Phase 3: 主题拥挤风险
        if topic_info.get("crowded_topics"):
            risks.append(f"主题拥挤: {', '.join(topic_info['crowded_topics'])}")
        if topic_info.get("fading_topics"):
            risks.append(f"主题消退: {', '.join(topic_info['fading_topics'])}")
        # V4: 高管风险
        if report.executive_risks:
            risks.extend(report.executive_risks)
        # Phase 6: 博弈论 + 投资思维模型风险
        risks.extend(gt_risks)
        risks.extend(mm_bias_flags)
        risks.extend(mm_warnings)

        return Verdict(
            symbol=report.symbol,
            score=round(score, 1),
            confidence=round(confidence, 2),
            recommendation=rec,
            falsifiable=falsifiable,
            risks=risks,
            topic_adjustments=topic_info,
            source_citations=report.source_citations,  # Phase 1: 继承诊断阶段的引用
            alpha_rationale=alpha_rationale,            # Phase 4: Alpha 判定理由
            consensus_challenge=consensus_challenge,    # Phase 4: 挑战共识
            alpha_multiplier=round(alpha_mult, 2),      # Phase 4: Alpha 乘数
            executive_risks=report.executive_risks,     # V4: 高管风险
            game_theory_adjustment={"gt_multiplier": round(gt_mult, 2), "gt_score": gt_score},
            game_theory_risks=gt_risks,
            mental_model_fit_score=mm_score,
            mental_model_warnings=mm_warnings + mm_bias_flags,
        )

    def _alpha_multiplier(
        self,
        report: DiagnosisReport,
    ) -> tuple[float, str, str]:
        """Phase 4: Alpha Lens — 基于 AlphaProfile 计算评分乘数。

        Alpha 视角调整:
          - alpha_score >= 60: 乘数 1.2 (高 Alpha → 放大)
          - alpha_score >= 40: 乘数 1.0 (中等 Alpha)
          - alpha_score < 40:  乘数 0.7 (低 Alpha → 缩小)
          - 叙事 CROWDED:       乘数 0.5 (拥挤 → 强制降权)
          - 共识噪音源:          乘数 0.8

        Returns:
            (multiplier, rationale, consensus_challenge)
        """
        profile = report.alpha_profile
        if profile is None:
            return 1.0, "", ""

        multiplier = 1.0

        # Alpha 评分调整
        if profile.alpha_score >= 60:
            multiplier += 0.2
        elif profile.alpha_score < 40:
            multiplier -= 0.3

        # 叙事阶段调整
        from src.alpha.schema import NarrativeLifecycle
        if profile.narrative.stage == NarrativeLifecycle.CROWDED:
            multiplier = min(multiplier, 0.5)

        # 噪音来源惩罚
        from src.alpha.schema import SourceTier
        if profile.source.source_tier == SourceTier.CONSENSUS_NOISE:
            multiplier = min(multiplier, 0.8)

        # 共识-现实缺口大 → 加分（因为市场可能错了）
        if profile.consensus_gap.is_market_wrong:
            multiplier += 0.1

        multiplier = max(0.3, min(1.5, multiplier))

        return (
            round(multiplier, 2),
            profile.alpha_rationale,
            f"共识挑战: {profile.consensus_gap.alpha_opportunity}"
            if profile.consensus_gap.gap_score >= 30 else "",
        )

    def _apply_topic_adjustment(
        self, sector_score: float, topic_adj: dict
    ) -> tuple[float, dict]:
        """主题生命周期 -> 行业权重调整。

        调整逻辑:
          EMERGING (+0.1): 主题刚出现，有 alpha -> 加权 10%
          SPREADING (0.0): 正常权重
          CONSENSUS (-0.1): 共识形成，拥挤风险 -> 降权 10%
          CROWDED (-0.2): 过度拥挤 -> 降权 20%
          FADING (-1.0): 主题消退 -> 行业评分中性化

        Returns:
            (adjusted_sector_score, topic_info_dict)
        """
        info: dict = {"crowded_topics": [], "fading_topics": [], "emerging_topics": []}
        max_bonus = 0.0
        has_fading = False

        for topic_id, bonus in topic_adj.items():
            if bonus <= -1.0:  # FADING
                has_fading = True
                info["fading_topics"].append(topic_id)
            elif bonus <= -0.15:  # CROWDED
                max_bonus = min(max_bonus, bonus)
                info["crowded_topics"].append(topic_id)
            elif bonus <= -0.05:  # CONSENSUS
                max_bonus = min(max_bonus, bonus)
            elif bonus >= 0.05:  # EMERGING
                max_bonus = max(max_bonus, bonus)
                info["emerging_topics"].append(topic_id)

        if has_fading:
            # All topics fading -> neutralize sector to 50
            return 50.0, info

        # Apply cumulative adjustment (capped)
        adjusted = sector_score * (1.0 + max(-0.2, min(0.1, max_bonus)))
        return max(0, min(100, adjusted)), info

    def _sentiment_adj(self, level: str) -> float:
        """情绪信号 -> 情绪评分调整。"""
        mapping = {
            "EXTREME": 90,  # 极度恐慌=抄底机会（反向指标）
            "PANIC": 30,     # 恐慌中不追跌
            "NORMAL": 50,    # 正常
            "GREED": 40,     # 贪婪中谨慎
        }
        return mapping.get(level, 50.0)

