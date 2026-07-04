# -*- coding: utf-8 -*-
"""恐慌套利决策引擎。

6 步决策树:
  1. 事件定性（基本面变化 vs 情绪冲击）
  2. 冲击范围识别（直接/间接/误杀）
  3. 基本面冲击量化
  4. 过度反应判定
  5. 抄底时机判断
  6. 仓位与风控

⚠️ A 股特有约束:
  - T+1: 当日买入无法止损 → 仓位上限 25%（非正常 50%）
  - 跌停板: 跌停标的无法买入 → 排除
  - 流动性: 恐慌日流动性枯竭 → 需等次日确认
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PanicLevel(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"     # 中度恐慌，可关注
    OVERREACTION = "OVERREACTION"  # 过度恐慌，可抄底
    CRASH = "CRASH"           # 崩盘，不宜操作


@dataclass
class PanicSignal:
    """恐慌套利信号。"""
    level: PanicLevel = PanicLevel.NONE
    event_type: str = ""                     # 基本面/情绪冲击
    affected_stocks: list[str] = field(default_factory=list)
    estimated_eps_impact_pct: float = 0.0    # EPS 冲击估算
    actual_drop_pct: float = 0.0             # 实际跌幅
    overreaction_ratio: float = 0.0          # 实际跌幅 / 合理跌幅
    suggested_position_pct: float = 0.0      # 建议仓位
    entry_timing: str = ""                   # 入场时机建议
    risks: list[str] = field(default_factory=list)


class PanicArbEngine:
    """恐慌套利引擎。

    ⚠️ 重要约束:
      - 恐慌抄底仓位上限 25%（非正常 50%），因 T+1 无法当日止损
      - 跌停标的不可买入——你买不到
      - 需等北向资金确认——聪明钱先进场
      - 3-5 交易日内不涨就撤——套利不是投资
    """

    OVERREACTION_THRESHOLD = 1.5   # 实际跌幅 > 合理跌幅 1.5x
    MAX_PANIC_POSITION = 0.25      # T+1 下恐慌仓位上限 25%（非正常 50%）
    MAX_HOLD_DAYS = 5              # 最多持有 5 个交易日
    STOP_LOSS_PCT = -0.01          # 恐慌交易止损 1%（非正常 2%）

    def analyze(
        self,
        event: dict,
        affected_sector: str = "",
        market_sentiment: str = "NORMAL",
    ) -> PanicSignal:
        """分析恐慌事件，生成套利信号。"""
        signal = PanicSignal()

        # Step 1: 事件定性
        is_fundamental = event.get("is_fundamental", False)
        if is_fundamental:
            signal.level = PanicLevel.NONE
            signal.event_type = "基本面永久变化，非套利机会"
            return signal

        event_type = event.get("type", "")
        if event_type not in ("policy", "sentiment", "external_shock"):
            signal.level = PanicLevel.NONE
            return signal
        signal.event_type = f"情绪冲击: {event.get('description', '')}"

        # Step 2: 冲击范围识别
        signal.affected_stocks = event.get("affected_stocks", [])

        # Step 3: 基本面冲击量化
        eps_impact = event.get("eps_impact_pct", 0)
        signal.estimated_eps_impact_pct = eps_impact
        # EPS 冲击 × PE 倍数 = 合理价格跌幅
        # 通常 1% EPS 影响 ≈ 1-3% 股价波动，取中值 2x
        reasonable_drop = abs(eps_impact) * 2

        # Step 4: 过度反应判定
        actual_drop = event.get("actual_drop_pct", 0)
        signal.actual_drop_pct = actual_drop
        if reasonable_drop > 0:
            signal.overreaction_ratio = abs(actual_drop) / reasonable_drop
            if signal.overreaction_ratio > self.OVERREACTION_THRESHOLD:
                signal.level = PanicLevel.OVERREACTION
            else:
                signal.level = PanicLevel.MODERATE

        # Step 5: 抄底时机
        if signal.level == PanicLevel.OVERREACTION:
            if event.get("institution_clarified") and event.get("northbound_inflow"):
                signal.entry_timing = "机构澄清 + 北向逆势流入 → 可考虑抄底"
                signal.suggested_position_pct = self.MAX_PANIC_POSITION
            else:
                signal.entry_timing = "等机构澄清和北向确认后再入场"
                signal.suggested_position_pct = 0.0

        # Step 6: 风控
        signal.risks = [
            f"T+1 风险: 当日无法止损",
            "建议分 2-3 批建仓",
            f"最多持有 {self.MAX_HOLD_DAYS} 交易日",
            f"止损 {-self.STOP_LOSS_PCT:.1%}",
        ]

        # 跌停标的不可买入
        if event.get("is_limit_down"):
            signal.level = PanicLevel.NONE
            signal.risks.append("🔴 标的已跌停，无法买入")

        return signal
