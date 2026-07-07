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


class AlertChannel(str, Enum):
    """预警通知渠道。"""
    CLI = "cli"            # 终端输出（默认）
    LOG = "log"            # 日志文件
    # Phase 5: WEBHOOK / EMAIL / SMS 预留


class MonitorFrequency(str, Enum):
    """盯盘扫描频率。"""
    HIGH = "high"          # 30s（短线专用）
    MEDIUM = "medium"      # 5min（波段）
    LOW = "low"            # 1h（长线）


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
class AlertPreferences:
    """盯盘预警偏好 — 控制实时预警的行为与粒度。

    短线投资者通常需要高频/多类型预警；长线投资者可关闭或仅保留风险预警。
    """
    enable_realtime: bool = False          # 是否启用实时盯盘
    monitor_frequency: MonitorFrequency = MonitorFrequency.MEDIUM
    channels: list[AlertChannel] = field(default_factory=lambda: [AlertChannel.CLI])
    # 预警类型开关
    watch_breakout: bool = True            # 技术突破（放量突破关键位）
    watch_volume: bool = True              # 量价异动（放量/缩量异常）
    watch_limit_up: bool = True            # 涨停/炸板/连板动态
    watch_ma_cross: bool = True            # 均线金叉/死叉
    watch_northbound: bool = True          # 北向资金突变
    watch_risk_flash: bool = True          # 风险速报（天地板/黑天鹅）
    # 静默与节流
    quiet_hours_start: str = ""            # 静默开始 HH:MM（如 "22:00"）
    quiet_hours_end: str = ""              # 静默结束 HH:MM（如 "08:00"）
    min_interval_seconds: int = 60         # 同一标的同类型预警最小间隔

    def to_dict(self) -> dict:
        return {
            "enable_realtime": self.enable_realtime,
            "monitor_frequency": self.monitor_frequency.value,
            "channels": [ch.value for ch in self.channels],
            "watch_breakout": self.watch_breakout,
            "watch_volume": self.watch_volume,
            "watch_limit_up": self.watch_limit_up,
            "watch_ma_cross": self.watch_ma_cross,
            "watch_northbound": self.watch_northbound,
            "watch_risk_flash": self.watch_risk_flash,
            "quiet_hours_start": self.quiet_hours_start,
            "quiet_hours_end": self.quiet_hours_end,
            "min_interval_seconds": self.min_interval_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> AlertPreferences:
        if d is None:
            return cls()
        freq_raw = d.get("monitor_frequency", "medium")
        try:
            freq = MonitorFrequency(freq_raw)
        except ValueError:
            freq = MonitorFrequency.MEDIUM
        channels_raw = d.get("channels", ["cli"])
        channels = []
        for ch in channels_raw:
            try:
                channels.append(AlertChannel(ch))
            except ValueError:
                pass
        if not channels:
            channels = [AlertChannel.CLI]
        return cls(
            enable_realtime=d.get("enable_realtime", False),
            monitor_frequency=freq,
            channels=channels,
            watch_breakout=d.get("watch_breakout", True),
            watch_volume=d.get("watch_volume", True),
            watch_limit_up=d.get("watch_limit_up", True),
            watch_ma_cross=d.get("watch_ma_cross", True),
            watch_northbound=d.get("watch_northbound", True),
            watch_risk_flash=d.get("watch_risk_flash", True),
            quiet_hours_start=d.get("quiet_hours_start", ""),
            quiet_hours_end=d.get("quiet_hours_end", ""),
            min_interval_seconds=d.get("min_interval_seconds", 60),
        )


@dataclass
class TimeHorizonConfig:
    """时间维度配置 — 由 trading_style + holding_period 解析。

    用于驱动 L1/L2/L3/L4 的参数差异化：
      - 短线：技术因子为主，ATR 止损，高频盯盘
      - 长线：基本面因子为主，固定止损，低频或无盯盘
    """
    is_short_term: bool = False            # 是否为短线/波段模式
    l2_technical_weight: float = 0.20      # L2 技术权重建议
    l2_fundamental_weight: float = 0.40    # L2 基本面权重建议
    stop_loss_pct: float = -0.02           # 单笔止损比例
    atr_stop_multiplier: float = 2.0       # ATR 止损倍率（短线用）
    time_stop_days: int = 60               # 时间止损天数（短线 3-7）
    trailing_stop_pct: float = -0.03       # 移动止损回撤比例
    enable_intraday: bool = False          # 是否启用日内/分钟级分析
    enable_monitor: bool = False           # 是否启用实时盯盘
    monitor_frequency: MonitorFrequency = MonitorFrequency.LOW
    factor_set: str = "fundamental"        # 因子集: "fundamental" / "technical" / "hybrid"


# 时间维度 → 参数预设
TIMING_PRESETS: dict[tuple[TradingStyle, HoldingPeriod], TimeHorizonConfig] = {
    # 长线 + 超长持有
    (TradingStyle.LONG_TERM, HoldingPeriod.ULTRA_LONG): TimeHorizonConfig(
        is_short_term=False, l2_technical_weight=0.10, l2_fundamental_weight=0.55,
        stop_loss_pct=-0.03, atr_stop_multiplier=3.0, time_stop_days=180,
        trailing_stop_pct=-0.05, enable_intraday=False, enable_monitor=False,
        monitor_frequency=MonitorFrequency.LOW, factor_set="fundamental",
    ),
    (TradingStyle.LONG_TERM, HoldingPeriod.LONG): TimeHorizonConfig(
        is_short_term=False, l2_technical_weight=0.15, l2_fundamental_weight=0.50,
        stop_loss_pct=-0.02, atr_stop_multiplier=2.5, time_stop_days=90,
        trailing_stop_pct=-0.04, enable_intraday=False, enable_monitor=False,
        monitor_frequency=MonitorFrequency.LOW, factor_set="fundamental",
    ),
    # 混合 / 中线
    (TradingStyle.MIXED, HoldingPeriod.MEDIUM): TimeHorizonConfig(
        is_short_term=False, l2_technical_weight=0.20, l2_fundamental_weight=0.40,
        stop_loss_pct=-0.02, atr_stop_multiplier=2.0, time_stop_days=60,
        trailing_stop_pct=-0.03, enable_intraday=False, enable_monitor=False,
        monitor_frequency=MonitorFrequency.LOW, factor_set="hybrid",
    ),
    # 波段 + 中线持有
    (TradingStyle.SWING, HoldingPeriod.MEDIUM): TimeHorizonConfig(
        is_short_term=True, l2_technical_weight=0.30, l2_fundamental_weight=0.30,
        stop_loss_pct=-0.02, atr_stop_multiplier=2.0, time_stop_days=20,
        trailing_stop_pct=-0.03, enable_intraday=True, enable_monitor=True,
        monitor_frequency=MonitorFrequency.MEDIUM, factor_set="technical",
    ),
    (TradingStyle.SWING, HoldingPeriod.SHORT): TimeHorizonConfig(
        is_short_term=True, l2_technical_weight=0.35, l2_fundamental_weight=0.25,
        stop_loss_pct=-0.015, atr_stop_multiplier=1.5, time_stop_days=10,
        trailing_stop_pct=-0.02, enable_intraday=True, enable_monitor=True,
        monitor_frequency=MonitorFrequency.HIGH, factor_set="technical",
    ),
    # 短线 + 短持有
    (TradingStyle.SHORT_TERM, HoldingPeriod.SHORT): TimeHorizonConfig(
        is_short_term=True, l2_technical_weight=0.45, l2_fundamental_weight=0.15,
        stop_loss_pct=-0.01, atr_stop_multiplier=1.5, time_stop_days=5,
        trailing_stop_pct=-0.02, enable_intraday=True, enable_monitor=True,
        monitor_frequency=MonitorFrequency.HIGH, factor_set="technical",
    ),
    (TradingStyle.SHORT_TERM, HoldingPeriod.MEDIUM): TimeHorizonConfig(
        is_short_term=True, l2_technical_weight=0.35, l2_fundamental_weight=0.25,
        stop_loss_pct=-0.015, atr_stop_multiplier=1.5, time_stop_days=10,
        trailing_stop_pct=-0.02, enable_intraday=True, enable_monitor=True,
        monitor_frequency=MonitorFrequency.MEDIUM, factor_set="technical",
    ),
}


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
    alert_preferences: AlertPreferences = field(default_factory=AlertPreferences)
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
            "alert_preferences": self.alert_preferences.to_dict(),
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
            alert_preferences=AlertPreferences.from_dict(d.get("alert_preferences")),
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
