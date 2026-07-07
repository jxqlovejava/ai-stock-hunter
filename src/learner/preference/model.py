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
    SHORT_TERM = "short_term"  # 短线交易
    MIXED = "mixed"            # 混合风格


class HoldingPeriod(str, Enum):
    """投资持有时间。"""
    SHORT = "short"        # 短线 (<1个月)
    MEDIUM = "medium"      # 中线 (1-12个月)
    LONG = "long"          # 长线 (1-3年)
    ULTRA_LONG = "ultra"   # 超长线 (3年以上)


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
    max_total_loss_pct: float = 0.25   # 能忍受的总最大亏损比例
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
            "max_total_loss_pct": self.max_total_loss_pct,
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
            max_total_loss_pct=d.get("max_total_loss_pct", 0.25),
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

    包含基本信息（风格/目标/亏损容忍/持有期）、仓位管理、能力圈、
    自选股、评分权重等，通过 PreferenceAdapter 注入路由管道。

    与 `UserProfile`（历史计算的、回顾性的能力雷达图）不同，
    此类代表用户的自我声明偏好（风险容忍度、目标、约束）。
    """
    risk_profile: RiskProfile = RiskProfile.BALANCED
    investment_goal: InvestmentGoal = InvestmentGoal.ABSOLUTE_RETURN
    trading_style: TradingStyle = TradingStyle.MIXED
    holding_period: HoldingPeriod = HoldingPeriod.MEDIUM  # 投资持有时间
    tier: InvestorTier = InvestorTier.BEGINNER
    position_limits: PositionLimits = field(default_factory=PositionLimits)
    circle_of_competence: CircleOfCompetence = field(default_factory=CircleOfCompetence)
    score_weights: ScoreWeights = field(default_factory=ScoreWeights)
    enabled_rules: list[str] | None = None  # None = 基于 tier 自动决定
    benchmark: str = "沪深300"
    investment_horizon: str = "3-5年"
    # 自选股关注列表 (symbol → name)，与 data/watchlist.json 联动
    watchlist: dict[str, str] = field(default_factory=dict)
    # 画像完整度追踪
    last_updated: str = ""           # 上次更新时间 ISO
    setup_step: int = 0              # 完成到第几步 (0=未设置, 用于渐进式引导)

    def to_dict(self) -> dict:
        return {
            "risk_profile": self.risk_profile.value,
            "investment_goal": self.investment_goal.value,
            "trading_style": self.trading_style.value,
            "holding_period": self.holding_period.value,
            "tier": self.tier.value,
            "position_limits": self.position_limits.to_dict(),
            "circle_of_competence": self.circle_of_competence.to_dict(),
            "score_weights": self.score_weights.to_dict(),
            "enabled_rules": self.enabled_rules,
            "benchmark": self.benchmark,
            "investment_horizon": self.investment_horizon,
            "watchlist": self.watchlist,
            "last_updated": self.last_updated,
            "setup_step": self.setup_step,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> InvestorPreference:
        if d is None:
            return cls()
        limits_raw = d.get("position_limits") or d.get("limits") or {}
        coc_raw = d.get("circle_of_competence", {})
        weights_raw = d.get("score_weights", {})
        watchlist_raw = d.get("watchlist", {})
        hp_raw = d.get("holding_period", "medium")
        try:
            hp = HoldingPeriod(hp_raw)
        except ValueError:
            hp = HoldingPeriod.MEDIUM
        return cls(
            risk_profile=RiskProfile(d.get("risk_profile", "balanced")),
            investment_goal=InvestmentGoal(d.get("investment_goal", "absolute_return")),
            trading_style=TradingStyle(d.get("trading_style", "mixed")),
            holding_period=hp,
            tier=InvestorTier(d.get("tier", "beginner")),
            position_limits=PositionLimits.from_dict(limits_raw),
            circle_of_competence=CircleOfCompetence.from_dict(coc_raw),
            score_weights=ScoreWeights.from_dict(weights_raw),
            enabled_rules=d.get("enabled_rules"),
            benchmark=d.get("benchmark", "沪深300"),
            investment_horizon=d.get("investment_horizon", "3-5年"),
            watchlist=watchlist_raw if isinstance(watchlist_raw, dict) else {},
            last_updated=d.get("last_updated", ""),
            setup_step=d.get("setup_step", 0),
        )

    def completeness(self) -> dict:
        """计算画像完整度 (0-100)，返回分数 + 缺失项列表。"""
        score = 0
        missing: list[str] = []
        max_score = 10

        checks = [
            (self.risk_profile != RiskProfile.BALANCED or self.setup_step > 0, 1, "风险偏好"),
            (self.trading_style != TradingStyle.MIXED or self.setup_step > 0, 1, "交易风格"),
            (self.holding_period != HoldingPeriod.MEDIUM or self.setup_step > 1, 1, "持有时间"),
            (self.position_limits.total_capital != 500000.0, 1, "投资本金"),
            (self.position_limits.single_stop_loss_pct != 0.02, 1, "止损线"),
            (self.position_limits.max_total_loss_pct != 0.25, 1, "最大亏损容忍"),
            (bool(self.watchlist), 1, "自选股"),
            (len(self.circle_of_competence.industries) > 3, 1, "能力圈 (3+行业)"),
            (bool(self.last_updated), 1, "已完成初始设置"),
            (self.setup_step >= 8, 1, "完整设置向导"),
        ]
        for condition, weight, label in checks:
            if condition:
                score += weight
            else:
                missing.append(label)

        return {
            "score": int(score / max_score * 100),
            "missing": missing,
            "is_default": score <= 2,
        }
