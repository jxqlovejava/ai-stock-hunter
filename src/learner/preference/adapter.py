# -*- coding: utf-8 -*-
"""偏好适配器 — 将 InvestorPreference 映射为管道可用的值。

纯函数，无状态。将用户声明的风险偏好、投资目标、层级等
转换为 裁决权重、仓位调度乘数、风控参数、军规过滤器。
"""

from __future__ import annotations

from .model import (
    AlertPreferences,
    BoardAccess,
    CircleOfCompetence,
    HoldingPeriod,
    InvestorPreference,
    InvestorTier,
    InvestmentGoal,
    MonitorFrequency,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TIMING_PRESETS,
    TimeHorizonConfig,
    TradingStyle,
    get_board_from_symbol,
)

# ------------------------------------------------------------------
# 权重预设: (risk_profile, investment_goal) → 覆盖默认 VerdictEngine.WEIGHTS
# ------------------------------------------------------------------

WEIGHT_PRESETS: dict[tuple[RiskProfile, InvestmentGoal], dict[str, float]] = {
    # 保守 + 绝对收益 → 重基本面、轻动量
    (RiskProfile.CONSERVATIVE, InvestmentGoal.ABSOLUTE_RETURN): {
        "fundamental": 0.50, "technical": 0.15, "macro": 0.15,
        "sector": 0.10, "sentiment": 0.10,
    },
    # 保守 + 相对收益 → 基本面为主、略增行业
    (RiskProfile.CONSERVATIVE, InvestmentGoal.RELATIVE_RETURN): {
        "fundamental": 0.45, "technical": 0.15, "macro": 0.15,
        "sector": 0.15, "sentiment": 0.10,
    },
    # 保守 + 现金流 → 极致基本面
    (RiskProfile.CONSERVATIVE, InvestmentGoal.CASH_FLOW): {
        "fundamental": 0.60, "technical": 0.10, "macro": 0.10,
        "sector": 0.15, "sentiment": 0.05,
    },

    # 平衡 + 绝对收益 → 系统默认 (与 VerdictEngine.WEIGHTS 一致)
    (RiskProfile.BALANCED, InvestmentGoal.ABSOLUTE_RETURN): {
        "fundamental": 0.40, "technical": 0.20, "macro": 0.15,
        "sector": 0.10, "sentiment": 0.15,
    },
    # 平衡 + 相对收益 → 略增技术/行业
    (RiskProfile.BALANCED, InvestmentGoal.RELATIVE_RETURN): {
        "fundamental": 0.35, "technical": 0.25, "macro": 0.15,
        "sector": 0.15, "sentiment": 0.10,
    },
    # 平衡 + 现金流 → 重基本面
    (RiskProfile.BALANCED, InvestmentGoal.CASH_FLOW): {
        "fundamental": 0.55, "technical": 0.10, "macro": 0.10,
        "sector": 0.15, "sentiment": 0.10,
    },

    # 激进 + 绝对收益 → 偏动量/情绪
    (RiskProfile.AGGRESSIVE, InvestmentGoal.ABSOLUTE_RETURN): {
        "fundamental": 0.30, "technical": 0.30, "macro": 0.15,
        "sector": 0.10, "sentiment": 0.15,
    },
    # 激进 + 相对收益 → 偏技术/行业
    (RiskProfile.AGGRESSIVE, InvestmentGoal.RELATIVE_RETURN): {
        "fundamental": 0.25, "technical": 0.35, "macro": 0.10,
        "sector": 0.15, "sentiment": 0.15,
    },
    # 激进 + 现金流 → 基本面+行业，不极端
    (RiskProfile.AGGRESSIVE, InvestmentGoal.CASH_FLOW): {
        "fundamental": 0.40, "technical": 0.15, "macro": 0.10,
        "sector": 0.20, "sentiment": 0.15,
    },
}

# ------------------------------------------------------------------
# 层级 → 规则过滤器
# ------------------------------------------------------------------

# 所有 block 级规则 ID
BLOCK_RULE_IDS = {
    "r001", "r002", "r003", "r004", "r005",    # 仓位与资金管理
    "r006",                                      # ST 一票否决
    "r012", "r013", "r014",                      # 买卖纪律
    "r017", "r018",                              # 情绪纪律
    "r022", "r023",                              # 信息纪律
    "r025", "r026",                              # 风控与止盈止损
    "r031",                                      # 元风控
}

# 核心下行保护（PRO 保留的）
PRO_CORE_RULES = {"r001", "r002", "r025", "r026"}

# 进阶规则 (block + 部分 warn)
INTERMEDIATE_RULES = BLOCK_RULE_IDS | {
    "r007", "r008",                              # 选股估值 warn
    "r015",                                       # 财报窗口
    "r019",                                       # 盈利上移止损
    "r024",                                       # 小作文
    "r028",                                       # 额外风控
}

TIER_RULE_FILTERS: dict[InvestorTier, set[str]] = {
    InvestorTier.BEGINNER: None,           # None → 全部规则启用
    InvestorTier.INTERMEDIATE: INTERMEDIATE_RULES,
    InvestorTier.PRO: PRO_CORE_RULES,
}

# ------------------------------------------------------------------
# 风险配置 → 仓位乘数
# ------------------------------------------------------------------

POSITION_RISK_MULTIPLIERS: dict[RiskProfile, float] = {
    RiskProfile.CONSERVATIVE: 0.7,
    RiskProfile.BALANCED: 1.0,
    RiskProfile.AGGRESSIVE: 1.2,
}

# ------------------------------------------------------------------
# 公共 API
# ------------------------------------------------------------------


def resolve_weights(prefs: InvestorPreference) -> dict[str, float]:
    """解析裁决评分权重。

    优先级:
      1. prefs.score_weights 中的显式覆盖值
      2. WEIGHT_PRESETS 中的 (risk_profile, goal) 预设
      3. 部分覆盖时，剩余权重按预设比例分配
      4. 归一化确保总和为 1.0
    """
    key = (prefs.risk_profile, prefs.investment_goal)
    preset = WEIGHT_PRESETS.get(
        key,
        WEIGHT_PRESETS[(RiskProfile.BALANCED, InvestmentGoal.ABSOLUTE_RETURN)],
    )

    overrides = prefs.score_weights
    if overrides is None:
        return preset.copy()

    # 收集显式覆盖
    explicit: dict[str, float] = {}
    for k in preset:
        val = getattr(overrides, k, None)
        if val is not None:
            explicit[k] = float(val)

    if not explicit:
        return preset.copy()

    # 部分覆盖：剩余权重按预设比例分配给未覆盖的 key
    explicit_sum = sum(explicit.values())
    remaining_weight = max(0, 1.0 - explicit_sum)
    preset_remaining = {
        k: v for k, v in preset.items() if k not in explicit
    }
    preset_remaining_sum = sum(preset_remaining.values()) or 1.0

    result = dict(explicit)
    for k, v in preset_remaining.items():
        result[k] = remaining_weight * (v / preset_remaining_sum)

    # 最终归一化
    total = sum(result.values())
    if abs(total - 1.0) > 0.01:
        result = {k: v / total for k, v in result.items()}

    return result


def resolve_rule_filter(prefs: InvestorPreference) -> set[str] | None:
    """解析启用的军规 ID 集合。

    None = 全部启用（用于 beginner / 未配置）。
    如果 enabled_rules 显式设置，优先于 tier。
    """
    if prefs.enabled_rules is not None:
        return set(prefs.enabled_rules)
    return TIER_RULE_FILTERS.get(prefs.tier, None)


def resolve_position_limits(prefs: InvestorPreference) -> dict:
    """解析仓位/风控约束，供 RiskControlEngine 使用。"""
    limits = prefs.position_limits
    return {
        "single_stock_cap": limits.max_single_pct,
        "sector_cap": limits.max_sector_pct,
        "max_drawdown": -abs(limits.portfolio_drawdown_pct),
        "stop_loss": -abs(limits.single_stop_loss_pct),
        "gem_discount": limits.gem_discount,
        "kelly_fraction": limits.kelly_fraction,
    }


def resolve_macro_cap_multiplier(prefs: InvestorPreference) -> float:
    """解析宏观仓位上限乘数。

    conservative=0.7 → 仓位调度 macro_cap 打 7 折
    balanced=1.0   → 不变
    aggressive=1.2 → 上浮 20%
    """
    return POSITION_RISK_MULTIPLIERS.get(prefs.risk_profile, 1.0)


def resolve_competence_penalty(
    prefs: InvestorPreference, stock_industry: str
) -> float:
    """计算能力圈惩罚乘数。

    - 熟悉度 >= 3 且在能力圈中 → 1.0 (无惩罚)
    - 能力圈外 → 0.85
    - 熟悉度 1 → 0.70
    """
    industries = prefs.circle_of_competence.industries
    if not industries:
        return 1.0

    familiarity = industries.get(stock_industry)
    if familiarity is None:
        return 0.85   # 不在能力圈
    if familiarity >= 3:
        return 1.0    # 高熟悉度
    if familiarity == 2:
        return 0.90
    return 0.70        # 熟悉度 1


# ------------------------------------------------------------------
# 时间维度解析 — trading_style + holding_period → TimeHorizonConfig
# ------------------------------------------------------------------

def resolve_time_horizon(prefs: InvestorPreference) -> TimeHorizonConfig:
    """解析时间维度配置。

    优先级:
      1. (trading_style, holding_period) 精确匹配 TIMING_PRESETS
      2. 同一 trading_style 的默认 holding_period
      3. 全局默认 (MIXED, MEDIUM)
    """
    # 精确匹配
    key = (prefs.trading_style, prefs.holding_period)
    if key in TIMING_PRESETS:
        return TIMING_PRESETS[key]

    # 同一 trading_style 的 fallback
    for period in (HoldingPeriod.MEDIUM, HoldingPeriod.LONG, HoldingPeriod.SHORT):
        fallback_key = (prefs.trading_style, period)
        if fallback_key in TIMING_PRESETS:
            return TIMING_PRESETS[fallback_key]

    # 全局默认
    default_key = (TradingStyle.MIXED, HoldingPeriod.MEDIUM)
    return TIMING_PRESETS.get(
        default_key,
        TimeHorizonConfig(),
    )


def resolve_stop_loss(prefs: InvestorPreference) -> dict:
    """解析止损参数，供 RiskControlEngine 使用。

    短线/波段模式返回 ATR+时间+移动止损；长线模式返回固定止损。
    """
    time_config = resolve_time_horizon(prefs)
    limits = prefs.position_limits

    base = {
        "stop_loss_pct": limits.single_stop_loss_pct,
        "max_drawdown": -abs(limits.portfolio_drawdown_pct),
        "max_total_loss_pct": limits.max_total_loss_pct,
    }

    if time_config.is_short_term:
        # 短线模式：ATR + 时间 + 移动止损
        base.update({
            "use_atr_stop": True,
            "atr_stop_multiplier": time_config.atr_stop_multiplier,
            "time_stop_days": time_config.time_stop_days,
            "trailing_stop_pct": time_config.trailing_stop_pct,
        })
    else:
        # 长线模式：仅固定止损
        base.update({
            "use_atr_stop": False,
            "atr_stop_multiplier": 0,
            "time_stop_days": time_config.time_stop_days,
            "trailing_stop_pct": time_config.trailing_stop_pct,
        })

    return base


def resolve_alert_config(prefs: InvestorPreference) -> dict:
    """解析盯盘预警配置。

    短线/波段模式强制启用实时盯盘；长线可手动开启但默认关闭。
    """
    time_config = resolve_time_horizon(prefs)
    alert = prefs.alert_preferences

    # 短线/波段自动启用实时盯盘，除非用户显式关闭
    auto_enable = time_config.is_short_term and not _user_explicitly_disabled_monitor(prefs)

    return {
        "enable_realtime": alert.enable_realtime or auto_enable,
        "monitor_frequency": time_config.monitor_frequency.value,
        "channels": [ch.value for ch in alert.channels],
        "watch_breakout": alert.watch_breakout,
        "watch_volume": alert.watch_volume,
        "watch_limit_up": alert.watch_limit_up,
        "watch_ma_cross": alert.watch_ma_cross,
        "watch_northbound": alert.watch_northbound,
        "watch_risk_flash": alert.watch_risk_flash,
        "quiet_hours_start": alert.quiet_hours_start,
        "quiet_hours_end": alert.quiet_hours_end,
        "min_interval_seconds": alert.min_interval_seconds,
    }


def _user_explicitly_disabled_monitor(prefs: InvestorPreference) -> bool:
    """检测用户是否显式关闭了盯盘。

    如果用户在 alert_preferences 中设置了 enable_realtime=False
    且 setup_step > 0（已完成设置向导），视为显式关闭。
    """
    return (
        not prefs.alert_preferences.enable_realtime
        and prefs.setup_step > 0
    )


def resolve_board_filter(prefs: InvestorPreference):
    """返回一个板块过滤谓词，用于选股/推荐时提前过滤不可交易板块。

    Returns:
        callable: 接收 symbol (str)，返回 True 表示该股票可交易

    >>> from src.learner.preference.model import BoardAccess
    >>> prefs = InvestorPreference(accessible_boards=[BoardAccess.MAIN_SH, BoardAccess.MAIN_SZ])
    >>> is_accessible = resolve_board_filter(prefs)
    >>> is_accessible("600519")   # 上海主板
    True
    >>> is_accessible("300750")   # 创业板 → 不在列表中
    False
    """
    accessible = set(prefs.accessible_boards)

    def _filter(symbol: str) -> bool:
        board = get_board_from_symbol(symbol)
        if board is None:
            # 无法识别板块的代码（如 ETF、可转债等），放行由下游处理
            return True
        return board in accessible

    return _filter


def is_board_accessible(prefs: InvestorPreference, symbol: str) -> bool:
    """检查单只股票是否在投资者可交易的板块内。

    便捷函数，等价于 resolve_board_filter(prefs)(symbol)。
    """
    return resolve_board_filter(prefs)(symbol)


def resolve_trading_style_weights(prefs: InvestorPreference) -> dict[str, float]:
    """根据 trading_style 调整裁决权重，覆盖 risk_profile 的预设。

    短线/波段：技术+情绪权重↑，基本面↓
    长线：基本面权重↑，技术↓
    """
    time_config = resolve_time_horizon(prefs)

    if time_config.is_short_term:
        # 短线/波段：技术+情绪为主
        return {
            "fundamental": time_config.l2_fundamental_weight,
            "technical": time_config.l2_technical_weight,
            "macro": 0.10,
            "sector": 0.10,
            "sentiment": round(
                1.0 - time_config.l2_fundamental_weight
                - time_config.l2_technical_weight - 0.20, 2
            ),
        }

    # 长线/混合：不做额外调整，依赖原有 risk_profile 预设
    return resolve_weights(prefs)


def resolve_risk_config(prefs: InvestorPreference) -> "RiskConfig":  # noqa: F821
    """从投资者偏好映射到不可变风控配置。

    借鉴 RiskGuard presets.py: 根据 RiskProfile 选择三档预设，
    再用 PositionLimits 覆盖差异项。返回 frozen RiskConfig 实例。
    """
    from src.routing.risk_config import RiskConfig

    return RiskConfig.from_preferences(prefs)
