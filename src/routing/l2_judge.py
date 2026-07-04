# -*- coding: utf-8 -*-
"""L2 法官 — 加权评分 + 置信度 + 反共识检查 + 主题生命周期调整。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .l1_analyze import AnalysisReport


@dataclass
class Verdict:
    """L2 裁决结果。"""
    symbol: str
    score: int = 50                          # 0-100
    confidence: float = 0.5                  # 0.0-1.0
    recommendation: str = "HOLD"             # BUY / ADD / HOLD / REDUCE / SELL
    falsifiable: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    topic_adjustments: dict = field(default_factory=dict)  # Phase 3: topic lifecycle adjustments
    source_citations: list = field(default_factory=list)  # Phase 1: 继承自 L1 的引用
    created_at: datetime = field(default_factory=datetime.now)


class L2Judge:
    """L2 法官。

    评分权重:
      - 基本面 (L1 价值 + 质量): 40%
      - 技术面 (L1 动量): 20%
      - 宏观适配: 15%
      - 行业景气: 10%
      - 情绪溢价: 15%

    置信度 < 0.6 不进入 L3。
    Phase 3: 主题生命周期调整 (topic_adj) 影响行业权重。
    """

    WEIGHTS = {
        "fundamental": 0.40,
        "technical": 0.20,
        "macro": 0.15,
        "sector": 0.10,
        "sentiment": 0.15,
    }

    MIN_CONFIDENCE = 0.6

    def judge(
        self,
        report: AnalysisReport,
        sector_score: float = 50.0,
        topic_adj: Optional[dict] = None,
    ) -> Verdict:
        """综合评分，生成裁决。

        Args:
            report: L1 分析报告
            sector_score: 行业景气评分 (0-100)
            topic_adj: 主题生命周期权重调整 {topic_id: bonus}, bonus in [-0.2, +0.1]
        """
        fundamental = (report.value_score + report.quality_score) / 2
        technical = report.momentum_score
        macro = report.macro_score
        sentiment = self._sentiment_adj(report.sentiment_signal)

        # Phase 3: 主题生命周期调整
        adjusted_sector = sector_score
        topic_info: dict = {}
        if topic_adj:
            adjusted_sector, topic_info = self._apply_topic_adjustment(sector_score, topic_adj)

        score = (
            fundamental * self.WEIGHTS["fundamental"]
            + technical * self.WEIGHTS["technical"]
            + macro * self.WEIGHTS["macro"]
            + adjusted_sector * self.WEIGHTS["sector"]
            + sentiment * self.WEIGHTS["sentiment"]
        )

        # 置信度 = 信息完整度的函数
        confidence = 0.5 + 0.3 * (min(fundamental, macro, adjusted_sector) / 50.0)
        confidence = min(confidence, 0.95)

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
        ]

        # 风险提示
        risks = []
        if report.macro_score < 40:
            risks.append("宏观环境偏空")
        if report.sentiment_signal == "PANIC":
            risks.append("市场恐慌中，注意流动性")
        # Phase 3: 主题拥挤风险
        if topic_info.get("crowded_topics"):
            risks.append(f"主题拥挤: {', '.join(topic_info['crowded_topics'])}")
        if topic_info.get("fading_topics"):
            risks.append(f"主题消退: {', '.join(topic_info['fading_topics'])}")

        return Verdict(
            symbol=report.symbol,
            score=int(score),
            confidence=round(confidence, 2),
            recommendation=rec,
            falsifiable=falsifiable,
            risks=risks,
            topic_adjustments=topic_info,
            source_citations=report.source_citations,  # Phase 1: 继承 L1 的引用
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
