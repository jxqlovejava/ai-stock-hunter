# -*- coding: utf-8 -*-
"""操纵感知仓位管理与止损引擎 (ManipulationSizingEngine)。

封装所有与庄家操纵相关的仓位调整和止损逻辑。
原先分散在 positioning.py (简单风险折扣) 和 risk_control.py (模式止损) 中，
此模块提供单一、可测试的计算入口。

用法:
    engine = ManipulationSizingEngine()
    result = engine.calc(
        symbol="600089",
        manipulation_risk=65.0,
        manipulation_pattern="lure_bull_dump",
        chip_concentration=55.0,
    )
    # CLI 快捷查询:
    quick_sizing(manipulation_risk=45.0, pattern="shakeout", chip=30.0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ManipulationStopStrategy:
    """操纵模式对应的止损策略配置。"""

    pattern_type: str               # 对应 playbook_id
    stop_type: str                  # "tight" / "normal" / "wide" / "immediate"
    stop_loss_pct: float            # 止损百分比 (负值, 如 -0.02 = 2% 止损)
    time_stop_days: int = 0         # 时间止损天数 (0 = 无时间止损)
    trailing_stop_pct: float = 0.0  # 移动止损百分比
    description: str = ""           # 策略描述
    urgency: str = "normal"         # "immediate" / "high" / "normal" / "low"


@dataclass
class ManipulationSizingResult:
    """操纵感知仓位调整完整结果。"""

    symbol: str
    manipulation_risk_score: float             # 操纵风险评分 0-100
    kelly_discount: float                      # 凯利折扣系数 0-1 (越小越保守)
    position_cap: float                        # 调整后仓位上限 0-1
    stop_strategy: Optional[ManipulationStopStrategy] = None
    entry_recommendation: str = "proceed"      # "proceed" / "delay_1d" / "delay_2d" / "skip"
    chip_concentration_risk: float = 0.0       # 筹码集中度 0-100
    fund_divergence_risk: float = 0.0          # 资金背离 0-100
    history_repeat_offender: bool = False      # 是否有操纵历史
    signals_summary: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)


class ManipulationSizingEngine:
    """操纵感知仓位管理与止损引擎。

    整合操纵风险评分、筹码集中度、资金背离、历史记录等信息，
    为仓位调度和止损配置提供单一决策入口。

    核心逻辑:
      1. 操纵风险折扣 → 降低仓位
      2. 筹码集中 + 资金背离 + 惯犯 → 额外叠加折扣
      3. 根据操盘手法匹配止损策略
      4. 入场建议 (延迟 / 跳过)
    """

    # ── 止损策略映射表 ──
    STOP_STRATEGIES: dict[str, ManipulationStopStrategy] = {
        "lure_bull_dump": ManipulationStopStrategy(
            pattern_type="lure_bull_dump",
            stop_type="tight",
            stop_loss_pct=-0.015,
            time_stop_days=1,
            urgency="high",
            description="诱多出货快速止损",
        ),
        "lure_bear_accumulate": ManipulationStopStrategy(
            pattern_type="lure_bear_accumulate",
            stop_type="wide",
            stop_loss_pct=-0.04,
            time_stop_days=3,
            urgency="low",
            description="诱空吸筹别被洗出",
        ),
        "wash_trade_pump": ManipulationStopStrategy(
            pattern_type="wash_trade_pump",
            stop_type="tight",
            stop_loss_pct=-0.02,
            time_stop_days=1,
            urgency="high",
            description="对倒拉升缩量即逃",
        ),
        "shakeout": ManipulationStopStrategy(
            pattern_type="shakeout",
            stop_type="wide",
            stop_loss_pct=-0.04,
            time_stop_days=3,
            urgency="low",
            description="洗盘震仓放宽止损避免被洗",
        ),
        "fishing_line": ManipulationStopStrategy(
            pattern_type="fishing_line",
            stop_type="immediate",
            stop_loss_pct=-0.01,
            time_stop_days=0,
            urgency="immediate",
            description="钓鱼线立即止损",
        ),
        "closing_manipulation": ManipulationStopStrategy(
            pattern_type="closing_manipulation",
            stop_type="normal",
            stop_loss_pct=-0.02,
            time_stop_days=1,
            urgency="normal",
            description="尾盘异动次日确认",
        ),
        "sideways_accumulation": ManipulationStopStrategy(
            pattern_type="sideways_accumulation",
            stop_type="wide",
            stop_loss_pct=-0.03,
            time_stop_days=5,
            urgency="low",
            description="横盘吸筹等待突破",
        ),
        "consecutive_yang_dump": ManipulationStopStrategy(
            pattern_type="consecutive_yang_dump",
            stop_type="tight",
            stop_loss_pct=-0.02,
            time_stop_days=1,
            urgency="high",
            description="连阳出货警惕反转",
        ),
        "limit_up_lure_chain": ManipulationStopStrategy(
            pattern_type="limit_up_lure_chain",
            stop_type="tight",
            stop_loss_pct=-0.02,
            time_stop_days=1,
            urgency="high",
            description="涨停诱多链开板即逃",
        ),
        "news_distribution": ManipulationStopStrategy(
            pattern_type="news_distribution",
            stop_type="tight",
            stop_loss_pct=-0.015,
            time_stop_days=1,
            urgency="high",
            description="消息配合出货快速止损",
        ),
        "default": ManipulationStopStrategy(
            pattern_type="default",
            stop_type="normal",
            stop_loss_pct=-0.02,
            time_stop_days=0,
            urgency="normal",
            description="默认止损 -2%, 无时间止损",
        ),
    }

    def calc(
        self,
        symbol: str,
        manipulation_risk: float = 0.0,
        manipulation_pattern: str = "",
        chip_concentration: float = 0.0,
        fund_divergence: float = 0.0,
        is_repeat_offender: bool = False,
        base_kelly_f: float = 0.0,
        base_position_cap: float = 0.20,
    ) -> ManipulationSizingResult:
        """计算操纵感知仓位调整。

        Args:
            symbol: 股票代码
            manipulation_risk: 操纵风险评分 0-100
            manipulation_pattern: 检测到的操盘手法 playbook_id
            chip_concentration: 筹码集中度评分 0-100
            fund_divergence: 资金背离风险 0-100
            is_repeat_offender: 是否有操纵历史
            base_kelly_f: 原始凯利 f* (预留, 当前未使用)
            base_position_cap: 基础仓位上限 (默认 20%)

        Returns:
            ManipulationSizingResult
        """
        reasoning: list[str] = []
        signals: list[str] = []

        # ── Step 1: 计算凯利折扣系数 ──
        kelly_discount = 1.0

        # 操纵风险折扣 (按最高档位单层, 不叠加)
        risk_discount = self._risk_level_discount(manipulation_risk)
        kelly_discount *= risk_discount
        if risk_discount < 1.0:
            reasoning.append(
                f"操纵风险 {manipulation_risk:.0f}/100 → 折扣乘数 ×{risk_discount}"
            )
            signals.append(
                f"风险折扣: ×{risk_discount} "
                f"(风险 {manipulation_risk:.0f}/100)"
            )

        # 筹码集中附加折扣
        if chip_concentration > 70:
            kelly_discount *= 0.80
            reasoning.append(
                f"筹码集中度 {chip_concentration:.0f} > 70 → 附加折扣 ×0.80"
            )
            signals.append(
                f"筹码折扣: ×0.80 (集中度 {chip_concentration:.0f}/100)"
            )

        # 资金背离附加折扣
        if fund_divergence > 60:
            kelly_discount *= 0.85
            reasoning.append(
                f"资金背离 {fund_divergence:.0f} > 60 → 附加折扣 ×0.85"
            )
            signals.append(
                f"资金折扣: ×0.85 (背离 {fund_divergence:.0f}/100)"
            )

        # 惯犯附加折扣
        if is_repeat_offender:
            kelly_discount *= 0.75
            reasoning.append("历史操纵惯犯 → 附加折扣 ×0.75")
            signals.append("惯犯折扣: ×0.75")

        # 钳位到 [0.1, 1.0]
        kelly_discount = max(0.1, min(1.0, kelly_discount))
        reasoning.append(
            f"最终凯利折扣系数: {kelly_discount:.2%}"
        )

        # ── Step 2: 计算仓位上限 ──
        position_cap = base_position_cap * kelly_discount
        reasoning.append(
            f"仓位上限: {base_position_cap:.0%} × {kelly_discount:.2%} = {position_cap:.1%}"
        )

        # ── Step 3: 选择止损策略 ──
        stop_strategy = self.get_stop_strategy(manipulation_pattern)
        if stop_strategy.pattern_type != "default":
            reasoning.append(
                f"止损策略: {stop_strategy.description} "
                f"(止损 {stop_strategy.stop_loss_pct:.1%}, "
                f"类型 {stop_strategy.stop_type})"
            )
        else:
            reasoning.append("未匹配手法止损策略, 使用默认 -2% 止损")

        # ── Step 4: 入场建议 ──
        entry_recommendation = self._entry_recommendation(
            manipulation_risk, is_repeat_offender
        )
        reasoning.append(f"入场建议: {entry_recommendation}")

        return ManipulationSizingResult(
            symbol=symbol,
            manipulation_risk_score=round(manipulation_risk, 1),
            kelly_discount=round(kelly_discount, 4),
            position_cap=round(position_cap, 4),
            stop_strategy=stop_strategy,
            entry_recommendation=entry_recommendation,
            chip_concentration_risk=round(chip_concentration, 1),
            fund_divergence_risk=round(fund_divergence, 1),
            history_repeat_offender=is_repeat_offender,
            signals_summary=signals,
            reasoning=reasoning,
        )

    def get_stop_strategy(self, pattern: str) -> ManipulationStopStrategy:
        """根据操盘手法 playbook_id 获取对应止损策略。

        Args:
            pattern: 操盘手法 playbook_id

        Returns:
            匹配的 ManipulationStopStrategy, 未匹配时返回 default
        """
        return self.STOP_STRATEGIES.get(
            pattern, self.STOP_STRATEGIES["default"]
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _risk_level_discount(manipulation_risk: float) -> float:
        """根据操纵风险等级返回折扣系数 (按最高档位, 不叠加)。"""
        if manipulation_risk > 80:
            return 0.20
        if manipulation_risk > 60:
            return 0.30
        if manipulation_risk > 30:
            return 0.70
        return 1.0

    @staticmethod
    def _entry_recommendation(
        manipulation_risk: float, is_repeat_offender: bool
    ) -> str:
        """根据操纵风险和惯犯记录确定入场建议。"""
        if manipulation_risk >= 70:
            return "skip"
        if manipulation_risk >= 50:
            return "delay_2d" if is_repeat_offender else "delay_1d"
        if manipulation_risk >= 30:
            return "delay_2d" if is_repeat_offender else "delay_1d"
        return "proceed"


def quick_sizing(
    manipulation_risk: float,
    pattern: str = "",
    chip: float = 0.0,
    divergence: float = 0.0,
) -> dict:
    """快捷估算函数, 用于 CLI 快速查询。

    Args:
        manipulation_risk: 操纵风险评分 0-100
        pattern: 操盘手法 playbook_id
        chip: 筹码集中度评分 0-100
        divergence: 资金背离风险 0-100

    Returns:
        {kelly_discount, position_cap, stop_loss_pct, entry_action}
    """
    engine = ManipulationSizingEngine()
    result = engine.calc(
        symbol="",
        manipulation_risk=manipulation_risk,
        manipulation_pattern=pattern,
        chip_concentration=chip,
        fund_divergence=divergence,
        base_position_cap=0.20,
    )
    stop_pct = (
        result.stop_strategy.stop_loss_pct
        if result.stop_strategy
        else -0.02
    )
    return {
        "kelly_discount": result.kelly_discount,
        "position_cap": result.position_cap,
        "stop_loss_pct": stop_pct,
        "entry_action": result.entry_recommendation,
    }
