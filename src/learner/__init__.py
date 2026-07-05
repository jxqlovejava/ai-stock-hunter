# -*- coding: utf-8 -*-
"""决策日志、复盘与学习模块。

导出:
  - DecisionJournal: 决策日志
  - ProfileTracker / UserProfile: 用户能力画像
  - FeedbackCollector / FeedbackSummary: 用户反馈收集
  - RuleCalibrator / FactorCalibrator / RiskParamCalibrator: 策略权重校准
  - EvolutionPipeline / EvolutionRecord: 策略进化编排
  - SignalTracker / SignalQualityReport: 信号质量追踪
  - ReportGenerator / LearningReport: 学习报告
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .calibrator import (
    Calibrator,
    CalibrationRecord,
    CalibrationResult,
    CalibrationReport,
    FactorCalibrator,
    RiskParamCalibrator,
    RuleCalibrator,
)
from .evolution import (
    EvolutionPipeline,
    EvolutionRecord,
    EvolutionStatus,
    GapAnalysis,
    ProposedChange,
)
from .feedback import (
    Feedback,
    FeedbackCollector,
    FeedbackSummary,
    FeedbackType,
)
from .preference.adapter import (
    resolve_competence_penalty,
    resolve_macro_cap_multiplier,
    resolve_position_limits,
    resolve_rule_filter,
    resolve_weights,
)
from .preference.loader import InvestorPreferenceLoader
from .preference.model import (
    CircleOfCompetence,
    InvestmentGoal,
    InvestorPreference,
    InvestorTier,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TradingStyle,
)
from .profile import ProfileTracker, UserProfile
from .report import LearningReport, ReportGenerator
from .signal_tracker import (
    Signal,
    SignalQualityReport,
    SignalStatus,
    SignalTracker,
)


class DecisionJournal:
    """决策日志 — 记录每笔系统建议与用户实际操作。"""

    def __init__(self, db_path: str = "data/journal.db"):
        self._path = db_path
        self._entries: list[dict] = []

    def log(
        self,
        symbol: str,
        system_action: str,
        user_action: str,
        user_reason: str = "",
        market_sentiment: str = "NORMAL",
    ):
        """记录一条决策。"""
        self._entries.append({
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "system_action": system_action,
            "user_action": user_action,
            "user_reason": user_reason,
            "market_sentiment": market_sentiment,
            "outcome_1w": None,
            "outcome_1m": None,
            "lessons": [],
        })

    def weekly_review(self) -> str:
        """生成周度复盘报告。"""
        if not self._entries:
            return "本周无交易记录。"
        recent = [e for e in self._entries
                  if (datetime.now() - datetime.fromisoformat(e["timestamp"])).days <= 7]
        if not recent:
            return "本周无交易记录。"
        agreed = sum(1 for e in recent if e["system_action"] == e["user_action"])
        total = len(recent)
        agreement_rate = agreed / total if total > 0 else 0
        lines = [
            "# 周度复盘报告",
            f"期间: 最近 7 天",
            f"交易数: {total}",
            f"系统-用户一致率: {agreement_rate:.0%}",
            "",
            "## 本周操作",
        ]
        for e in recent:
            icon = "✅" if e["system_action"] == e["user_action"] else "⚠️"
            lines.append(
                f"{icon} {e['symbol']}: 系统建议 {e['system_action']}, "
                f"你做了 {e['user_action']} ({e['user_reason']})"
            )
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._entries)


__all__ = [
    "DecisionJournal",
    "InvestorPreference",
    "RiskProfile",
    "InvestmentGoal",
    "TradingStyle",
    "InvestorTier",
    "PositionLimits",
    "CircleOfCompetence",
    "ScoreWeights",
    "InvestorPreferenceLoader",
    "resolve_weights",
    "resolve_rule_filter",
    "resolve_position_limits",
    "resolve_macro_cap_multiplier",
    "resolve_competence_penalty",
    "ProfileTracker",
    "UserProfile",
    "FeedbackCollector",
    "FeedbackSummary",
    "Feedback",
    "FeedbackType",
    "RuleCalibrator",
    "FactorCalibrator",
    "RiskParamCalibrator",
    "Calibrator",
    "CalibrationRecord",
    "CalibrationResult",
    "CalibrationReport",
    "EvolutionPipeline",
    "EvolutionRecord",
    "EvolutionStatus",
    "GapAnalysis",
    "ProposedChange",
    "SignalTracker",
    "SignalQualityReport",
    "Signal",
    "SignalStatus",
    "ReportGenerator",
    "LearningReport",
]
