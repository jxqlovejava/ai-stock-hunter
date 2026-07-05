# -*- coding: utf-8 -*-
"""投资者偏好数据模型。

与 `UserProfile`（回顾型能力评估）不同，`InvestorPreference` 是用户自我声明的、
前向约束与偏好，用于注入路由管道以定制 L2 权重、L3 仓位、L4 风控及军规启用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskProfile(str, Enum):
    """风险偏好。"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class InvestmentGoal(str, Enum):
    """投资目标。"""
    ABSOLUTE_RETURN = "absolute_return"    # 绝对收益（跑赢大盘）
    RELATIVE_RETURN = "relative_return"    # 相对收益（跟踪指数）
    CASH_FLOW = "cash_flow"                # 现金流（股息）


class TradingStyle(str, Enum):
    """交易风格。"""
    LONG_TERM = "long_term"    # 中长线配置
    SWING = "swing"            # 波段交易
    MIXED = "mixed"            # 混合风格


class InvestorTier(str, Enum):
    """投资者层级（成长路径）。

    BEGINNER (小白/依赖期): 全部军规启用，简化输出
    INTERMEDIATE (进阶/理解期): block 级 + 部分 warn 级规则
    PRO (专业/协作期): 仅核心下行保护规则
    """
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PRO = "pro"


@dataclass
class PositionLimits:
    """仓位约束。"""
    total_capital: float = 500000.0
    max_single_pct: float = 0.20       # 单票最大仓位
    max_sector_pct: float = 0.40       # 单行业最大仓位
    max_total_exposure: float = 0.80   # 总仓位上限
    min_cash_pct: float = 0.20         # 最低现金保留
    single_stop_loss_pct: float = 0.02 # 单笔最大亏损
    portfolio_drawdown_pct: float = 0.15  # 组合最大回撤
    gem_discount: float = 0.80          # 创业板/科创板折扣
    kelly_fraction: float = 0.50        # 凯利分数 (0.1-1.0, 默认 half-Kelly)

    def to_dict(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "max_single_pct": self.max_single_pct,
            "max_sector_pct": self.max_sector_pct,
            "max_total_exposure": self.max_total_exposure,
            "min_cash_pct": self.min_cash_pct,
            "single_stop_loss_pct": self.single_stop_loss_pct,
            "portfolio_drawdown_pct": self.portfolio_drawdown_pct,
            "gem_discount": self.gem_discount,
            "kelly_fraction": self.kelly_fraction,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PositionLimits:
        return cls(
            total_capital=d.get("total_capital", 500000.0),
            max_single_pct=d.get("max_single_pct", 0.20),
            max_sector_pct=d.get("max_sector_pct", 0.40),
            max_total_exposure=d.get("max_total_exposure", 0.80),
            min_cash_pct=d.get("min_cash_pct", 0.20),
            single_stop_loss_pct=d.get("single_stop_loss_pct", 0.02),
            portfolio_drawdown_pct=d.get("portfolio_drawdown_pct", 0.15),
            gem_discount=d.get("gem_discount", 0.80),
            kelly_fraction=d.get("kelly_fraction", 0.50),
        )


@dataclass
class CircleOfCompetence:
    """能力圈 — 行业 → 熟悉度 (1-5)。"""
    industries: dict[str, int] = field(default_factory=lambda: {
        "消费": 3,
        "新能源": 2,
        "科技": 2,
    })

    def to_dict(self) -> dict:
        return dict(self.industries)

    @classmethod
    def from_dict(cls, d: dict | None) -> CircleOfCompetence:
        if d is None:
            return cls()
        return cls(industries={k: int(v) for k, v in d.items()})


@dataclass
class ScoreWeights:
    """L2 评分权重覆盖。None = 使用系统默认值。"""
    fundamental: float | None = None
    technical: float | None = None
    macro: float | None = None
    sector: float | None = None
    sentiment: float | None = None

    def to_dict(self) -> dict:
        return {
            "fundamental": self.fundamental,
            "technical": self.technical,
            "macro": self.macro,
            "sector": self.sector,
            "sentiment": self.sentiment,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> ScoreWeights:
        if d is None:
            return cls()
        return cls(
            fundamental=d.get("fundamental"),
            technical=d.get("technical"),
            macro=d.get("macro"),
            sector=d.get("sector"),
            sentiment=d.get("sentiment"),
        )


@dataclass
class InvestorPreference:
    """投资者偏好画像 — 前向约束与偏好。

    与 `UserProfile`（历史计算的、回顾性的能力雷达图）不同，
    此类代表用户的自我声明偏好（风险容忍度、目标、约束）。
    通过 PreferenceAdapter 注入路由管道。
    """
    risk_profile: RiskProfile = RiskProfile.BALANCED
    investment_goal: InvestmentGoal = InvestmentGoal.ABSOLUTE_RETURN
    trading_style: TradingStyle = TradingStyle.MIXED
    tier: InvestorTier = InvestorTier.BEGINNER
    position_limits: PositionLimits = field(default_factory=PositionLimits)
    circle_of_competence: CircleOfCompetence = field(default_factory=CircleOfCompetence)
    score_weights: ScoreWeights = field(default_factory=ScoreWeights)
    enabled_rules: list[str] | None = None  # None = 基于 tier 自动决定
    benchmark: str = "沪深300"
    investment_horizon: str = "3-5年"

    def to_dict(self) -> dict:
        return {
            "risk_profile": self.risk_profile.value,
            "investment_goal": self.investment_goal.value,
            "trading_style": self.trading_style.value,
            "tier": self.tier.value,
            "position_limits": self.position_limits.to_dict(),
            "circle_of_competence": self.circle_of_competence.to_dict(),
            "score_weights": self.score_weights.to_dict(),
            "enabled_rules": self.enabled_rules,
            "benchmark": self.benchmark,
            "investment_horizon": self.investment_horizon,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> InvestorPreference:
        if d is None:
            return cls()
        limits_raw = d.get("position_limits") or d.get("limits") or {}
        coc_raw = d.get("circle_of_competence", {})
        weights_raw = d.get("score_weights", {})
        return cls(
            risk_profile=RiskProfile(d.get("risk_profile", "balanced")),
            investment_goal=InvestmentGoal(d.get("investment_goal", "absolute_return")),
            trading_style=TradingStyle(d.get("trading_style", "mixed")),
            tier=InvestorTier(d.get("tier", "beginner")),
            position_limits=PositionLimits.from_dict(limits_raw),
            circle_of_competence=CircleOfCompetence.from_dict(coc_raw),
            score_weights=ScoreWeights.from_dict(weights_raw),
            enabled_rules=d.get("enabled_rules"),
            benchmark=d.get("benchmark", "沪深300"),
            investment_horizon=d.get("investment_horizon", "3-5年"),
        )
