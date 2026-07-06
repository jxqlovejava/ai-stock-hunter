# -*- coding: utf-8 -*-
"""投资思维模型分析层 — 投资者偏好、能力圈、行为偏差校验。

Phase: 作为 Orchestrator 中 L1 → L2 之间的必经阶段。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation
from src.learner.preference.adapter import resolve_competence_penalty
from src.learner.preference.model import InvestorPreference, RiskProfile, TradingStyle
from src.learner.profile import ProfileTracker, UserProfile

logger = logging.getLogger(__name__)


@dataclass
class InvestorMentalModelFit:
    """投资者思维模型匹配结果。"""

    symbol: str = ""
    name: str = ""
    fit_score: int = 50  # 0-100
    competence_match: str = "unknown"  # in_circle / edge / out_of_circle
    competence_multiplier: float = 1.0
    risk_profile_match: bool = True
    horizon_match: bool = True
    bias_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_citations: list[SourceCitation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "fit_score": self.fit_score,
            "competence_match": self.competence_match,
            "competence_multiplier": self.competence_multiplier,
            "risk_profile_match": self.risk_profile_match,
            "horizon_match": self.horizon_match,
            "bias_flags": self.bias_flags,
            "warnings": self.warnings,
            "created_at": self.created_at.isoformat(),
        }


class InvestorMentalModelAnalyzer:
    """投资者思维模型分析器。

    输入：
      - InvestorPreference（风险偏好/目标/能力圈/层级）
      - 可选 UserProfile（历史行为画像）
      - 可选 portfolio（当前持仓/成本/浮亏）

    输出：
      - 能力圈匹配度
      - 风险偏好与标的匹配度
      - 投资周期与标的匹配度
      - 行为偏差警示（处置效应、损失厌恶等）
    """

    def __init__(self):
        self._profile_tracker = ProfileTracker()

    def analyze(
        self,
        symbol: str,
        name: str = "",
        investor: Optional[InvestorPreference] = None,
        portfolio: Optional[dict] = None,
        sector: str = "",
        market_cap: Optional[float] = None,
        change_pct: Optional[float] = None,
    ) -> InvestorMentalModelFit:
        """分析投资者与标的的匹配度。"""
        fit = InvestorMentalModelFit(symbol=symbol, name=name)
        citations: list[SourceCitation] = []
        warnings: list[str] = []
        bias_flags: list[str] = []

        if investor is None:
            investor = InvestorPreference()
            warnings.append("未加载投资者偏好，使用默认配置")

        # 1. 能力圈
        competence_mult = resolve_competence_penalty(investor, sector) if sector else 0.85
        fit.competence_multiplier = competence_mult
        if sector:
            familiarity = investor.circle_of_competence.industries.get(sector)
            if familiarity is None:
                fit.competence_match = "out_of_circle"
                warnings.append(f"{sector} 不在能力圈，建议降低仓位或深入研究")
            elif familiarity >= 3:
                fit.competence_match = "in_circle"
            else:
                fit.competence_match = "edge"
                warnings.append(f"{sector} 熟悉度仅 {familiarity}/5，处于能力圈边缘")
            citations.append(
                make_citation(
                    provider="investor_preference",
                    field="circle_of_competence",
                    data_type="fundamental",
                    source_tier="T1",
                    nature="fact",
                )
            )
        else:
            fit.competence_match = "out_of_circle"
            warnings.append("未获取标的行业，按能力圈外处理")

        # 2. 风险偏好匹配
        fit.risk_profile_match, risk_warning = self._match_risk_profile(
            investor, symbol, market_cap, change_pct
        )
        if risk_warning:
            warnings.append(risk_warning)
        citations.append(
            make_citation(
                provider="investor_preference",
                field="risk_profile",
                data_type="fundamental",
                source_tier="T1",
                nature="fact",
            )
        )

        # 3. 投资周期匹配
        fit.horizon_match, horizon_warning = self._match_horizon(investor, market_cap)
        if horizon_warning:
            warnings.append(horizon_warning)
        citations.append(
            make_citation(
                provider="investor_preference",
                field="investment_horizon",
                data_type="fundamental",
                source_tier="T1",
                nature="fact",
            )
        )

        # 4. 行为偏差（基于 portfolio）
        portfolio = portfolio or {}
        position_loss = portfolio.get("position_loss_pct") or portfolio.get("unrealized_pnl_pct")
        if position_loss is not None and position_loss < -0.05:
            bias_flags.append(
                f"disposition_effect_risk: 当前浮亏 {position_loss:.1%}，"
                "容易触发‘亏损死扛、盈利早卖’的处置效应"
            )
            bias_flags.append(
                "loss_aversion: 浮亏超过 5%，决策可能被损失厌恶主导"
            )
        elif position_loss is not None and position_loss < -0.02:
            bias_flags.append(
                f"loss_aversion: 当前浮亏 {position_loss:.1%}，需警惕损失厌恶"
            )

        # 5. 历史行为画像（如有记录）
        try:
            user_profile = self._profile_tracker.evaluate()
            if user_profile.risk_discipline < 40:
                bias_flags.append(
                    f"poor_stop_loss_history: 历史止损执行率 {user_profile.risk_discipline:.0f}/100"
                )
            if user_profile.emotion_control < 40:
                bias_flags.append(
                    f"low_system_adherence: 历史系统遵从率 {user_profile.emotion_control:.0f}/100"
                )
            citations.append(
                make_citation(
                    provider="learner",
                    field="user_profile",
                    data_type="fundamental",
                    source_tier="T3",
                    nature="interpretation",
                )
            )
        except Exception as e:
            logger.debug("UserProfile evaluation failed: %s", e)

        # 6. 综合 fit_score
        base = 70
        if fit.risk_profile_match:
            base += 10
        if fit.horizon_match:
            base += 10
        base = int(base * competence_mult)
        # 每个行为偏差扣 5 分
        base -= len(bias_flags) * 5
        fit.fit_score = max(0, min(100, base))

        fit.bias_flags = bias_flags
        fit.warnings = warnings
        fit.source_citations = citations
        return fit

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_risk_profile(
        investor: InvestorPreference,
        symbol: str,
        market_cap: Optional[float],
        change_pct: Optional[float],
    ) -> tuple[bool, str]:
        """判断风险偏好与标的匹配度。"""
        # 保守投资者 + 双创/小盘/高波动 → 不匹配
        if investor.risk_profile == RiskProfile.CONSERVATIVE:
            is_gem = symbol.startswith(("300", "688"))
            high_volatility = change_pct is not None and abs(change_pct) >= 5
            small_cap = market_cap is not None and market_cap < 10_000_000_000
            if is_gem or high_volatility or small_cap:
                return False, "保守风险偏好与当前标的波动特征不匹配"

        # 激进投资者 + 超大盘蓝筹 → 略提示
        if investor.risk_profile == RiskProfile.AGGRESSIVE:
            mega_cap = market_cap is not None and market_cap > 500_000_000_000
            if mega_cap:
                return False, "激进风险偏好与超大盘蓝筹的弹性可能不匹配"

        return True, ""

    @staticmethod
    def _match_horizon(
        investor: InvestorPreference,
        market_cap: Optional[float],
    ) -> tuple[bool, str]:
        """判断投资周期与标的匹配度。"""
        horizon = investor.investment_horizon
        # 短线/波段 + 超大蓝筹 → 周期可能不匹配（蓝筹弹性小）
        if horizon in ("短线", "波段", "swing") and market_cap and market_cap > 500_000_000_000:
            return False, "短线/波段风格与超大盘蓝筹的波动周期可能不匹配"
        # 长线 + 小盘高波 → 提示
        if horizon in ("长线", "长期", "3-5年", "5年以上") and market_cap and market_cap < 10_000_000_000:
            return False, "长期投资偏好但标的为小盘股，稳定性存疑"
        return True, ""
