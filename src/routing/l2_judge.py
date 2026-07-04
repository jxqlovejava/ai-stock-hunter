# -*- coding: utf-8 -*-
"""L2 法官 — 加权评分 + 置信度 + 反共识检查。"""

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
    ) -> Verdict:
        """综合评分，生成裁决。"""
        fundamental = (report.value_score + report.quality_score) / 2
        technical = report.momentum_score
        macro = report.macro_score
        sentiment = self._sentiment_adj(report.sentiment_signal)

        score = (
            fundamental * self.WEIGHTS["fundamental"]
            + technical * self.WEIGHTS["technical"]
            + macro * self.WEIGHTS["macro"]
            + sector_score * self.WEIGHTS["sector"]
            + sentiment * self.WEIGHTS["sentiment"]
        )

        # 置信度 = 信息完整度的函数
        confidence = 0.5 + 0.3 * (min(fundamental, macro, sector_score) / 50.0)
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
            f"如果宏观 PMI < 48，建议失效",
            f"如果标的 PE 超过历史 70% 分位，建议失效",
        ]

        # 风险提示
        risks = []
        if report.macro_score < 40:
            risks.append("宏观环境偏空")
        if report.sentiment_signal == "PANIC":
            risks.append("市场恐慌中，注意流动性")

        return Verdict(
            symbol=report.symbol,
            score=int(score),
            confidence=round(confidence, 2),
            recommendation=rec,
            falsifiable=falsifiable,
            risks=risks,
        )

    def _sentiment_adj(self, level: str) -> float:
        """情绪信号 → 情绪评分调整。"""
        mapping = {
            "EXTREME": 90,  # 极度恐慌=抄底机会（反向指标）
            "PANIC": 30,     # 恐慌中不追跌
            "NORMAL": 50,    # 正常
            "GREED": 40,     # 贪婪中谨慎
        }
        return mapping.get(level, 50.0)
