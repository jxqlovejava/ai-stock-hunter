# -*- coding: utf-8 -*-
"""偏好适配器 — 将 InvestorPreference 映射为管道可用的值。

纯函数，无状态。将用户声明的风险偏好、投资目标、层级等
转换为 L2 权重、L3 仓位乘数、L4 风控参数、军规过滤器。
"""

from __future__ import annotations

from .model import (
    CircleOfCompetence,
    InvestorPreference,
    InvestorTier,
    InvestmentGoal,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
)

# ------------------------------------------------------------------
# 权重预设: (risk_profile, investment_goal) → 覆盖默认 L2Judge.WEIGHTS
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

    # 平衡 + 绝对收益 → 系统默认 (与 L2Judge.WEIGHTS 一致)
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
    """解析 L2 评分权重。

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
    """解析仓位/风控约束，供 L4RiskOfficer 使用。"""
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

    conservative=0.7 → L3 macro_cap 打 7 折
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
