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

from src.alpha.schema import AlphaProfile

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

# Phase 4: Alpha 归因引擎
from src.alpha.attribution import AlphaAttribution, AttributionReport


class DecisionJournal:
    """决策日志 — 记录每笔系统建议与用户实际操作。Phase 4: Alpha 归因。"""

    def __init__(self, db_path: str = "data/journal.db"):
        self._path = db_path
        self._entries: list[dict] = []
        self._attribution = AlphaAttribution()

    def log(
        self,
        symbol: str,
        system_action: str,
        user_action: str,
        user_reason: str = "",
        market_sentiment: str = "NORMAL",
        entry_alpha: Optional[AlphaProfile] = None,
        exit_alpha: Optional[AlphaProfile] = None,
        total_return_pct: float = 0.0,
        market_return_pct: float = 0.0,
        sector_return_pct: float = 0.0,
        holding_days: int = 0,
    ):
        """记录一条决策（含 Alpha 归因）。"""
        # Alpha 归因
        attribution_report = None
        if entry_alpha and abs(total_return_pct) > 0.01:
            try:
                attribution_report = self._attribution.attribute(
                    symbol=symbol,
                    total_return_pct=total_return_pct,
                    market_return_pct=market_return_pct,
                    sector_return_pct=sector_return_pct,
                    entry_profile=entry_alpha,
                    exit_profile=exit_alpha,
                    holding_period_days=holding_days,
                )
            except Exception:
                pass

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
            "total_return_pct": total_return_pct,
            "alpha_report": attribution_report,
        })

    def weekly_review(self) -> str:
        """生成周度复盘报告（含 Alpha 归因）。"""
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
            # Phase 4: Alpha 归因
            ar = e.get("alpha_report")
            if ar:
                driver = "Alpha 驱动" if ar.is_alpha_driven else "Beta 驱动"
                lines.append(
                    f"   📊 收益 {ar.total_return_pct:+.1f}%: "
                    f"Alpha {ar.alpha_return_pct:+.1f}% / "
                    f"Beta {ar.market_beta_return_pct:+.1f}% [{driver}] "
                    f"质量 {ar.alpha_quality_score:.0f}/100"
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
    # Phase 4: Alpha 归因
    "AlphaAttribution",
    "AttributionReport",
]
