# -*- coding: utf-8 -*-
"""退出规则引擎 — 四条独立规则按序检查，先触发的胜出。

规则优先级:
  1. ATR Trailing Stop (HIGH 紧急退出)
  2. Time Stop (NORMAL 超期未达预期)
  3. Partial Take-Profit (NORMAL 分批止盈)
  4. Break-Even Stop (HIGH 回吐全部利润)

用法::

    engine = ExitRuleEngine(atr_multiplier=2.5)
    result = engine.check(position, market_data)
    if result.should_exit:
        logger.warning("%s: %s", result.symbol, result.reason)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime

from src.strategy.types import ExitCheckResult

logger = logging.getLogger(__name__)


@dataclass
class ExitRuleEngine:
    """退出规则引擎 — 按优先级检查四条规则。

    Attributes:
        atr_multiplier: ATR 追踪止损倍率 (default 2.5)
        max_hold_days: 最长持有天数 (default 60)
        min_return: 时间止损最低期望收益 (default 0.02 = 2%)
        first_target: 第一目标位触发部分止盈 (default 0.20 = 20%)
        second_target: 第二目标位触发全部止盈 (default 0.40 = 40%)
        take_profit_first_pct: 第一目标出场比例 (default 50%)
        breakeven_trigger: 触发保本止损所需最低浮盈 (default 0.10 = 10%)
    """

    atr_multiplier: float = 2.5
    max_hold_days: int = 60
    min_return: float = 0.02
    first_target: float = 0.20
    second_target: float = 0.40
    take_profit_first_pct: float = 50.0
    breakeven_trigger: float = 0.10
    _trailing_stops: dict[str, float] = field(default_factory=dict)

    def check(self, position: dict, market_data: dict) -> ExitCheckResult:
        """按优先级检查四条退出规则。第一条触发的胜出。"""
        symbol = position.get("symbol", "")
        pnl_pct = position.get("pnl_pct", 0.0) or 0.0
        current_price = position.get("current_price", 0.0) or 0.0
        atr = market_data.get("atr", 0.0) or 0.0

        # NaN 防御: 坏价格不触发规则
        if not math.isfinite(current_price) or current_price <= 0:
            logger.debug("ExitRuleEngine 跳过 %s: 无效价格 %.4f", symbol, current_price)
            return ExitCheckResult(
                symbol=symbol, should_exit=False, reason="",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        result = self._check_atr_trail(position, market_data)
        if result.should_exit:
            return result

        result = self._check_time_stop(position, market_data)
        if result.should_exit:
            return result

        result = self._check_take_profit(position, market_data)
        if result.should_exit:
            return result

        result = self._check_breakeven(position, market_data)
        if result.should_exit:
            return result

        return ExitCheckResult(
            symbol=symbol, should_exit=False, reason="",
            current_pnl_pct=pnl_pct, atr=atr,
        )

    # ------------------------------------------------------------------
    # 规则 1: ATR Trailing Stop
    # ------------------------------------------------------------------

    def _check_atr_trail(self, position: dict, market_data: dict) -> ExitCheckResult:
        """ATR 追踪止损 — 借鉴 RiskGuard drawdown HWM 单向不回落逻辑。

        trailing_stop = highest_high - atr * multiplier，只上移不下移。
        当前价跌破止损 → HIGH 紧急退出。
        """
        symbol = position.get("symbol", "")
        current_price = position.get("current_price", 0.0) or 0.0
        pnl_pct = position.get("pnl_pct", 0.0) or 0.0
        atr = market_data.get("atr", 0.0) or 0.0
        atr_pct = market_data.get("atr_pct", 0.0) or 0.0
        high_20d = market_data.get("20d_high", 0.0) or 0.0

        if atr <= 0 or atr_pct <= 0:
            return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                                   current_pnl_pct=pnl_pct, atr=atr)

        entry_price = position.get("entry_price", 0.0) or 0.0
        hwm = max(high_20d, current_price, entry_price)

        trail_price = hwm - atr * self.atr_multiplier
        if trail_price <= 0:
            trail_price = hwm * 0.5

        # 止损失只上移不下移
        prev_stop = self._trailing_stops.get(symbol, 0.0)
        new_stop = max(trail_price, prev_stop) if prev_stop > 0 else trail_price
        self._trailing_stops[symbol] = new_stop

        if current_price <= new_stop:
            reason = (
                f"ATR追踪止损: 现价{current_price:.2f} ≤ 止损价{new_stop:.2f}"
                f" (HWM={hwm:.2f}, ATR×{self.atr_multiplier}={atr * self.atr_multiplier:.2f})"
            )
            logger.warning("%s %s", symbol, reason)
            return ExitCheckResult(
                symbol=symbol, should_exit=True, reason=reason,
                urgency="HIGH", exit_pct=100.0,
                rule_triggered="atr_trailing_stop",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                               current_pnl_pct=pnl_pct, atr=atr)

    # ------------------------------------------------------------------
    # 规则 2: Time Stop
    # ------------------------------------------------------------------

    @staticmethod
    def _check_time_stop(position: dict, market_data: dict) -> ExitCheckResult:
        """时间止损: 持有超期且未达最低预期收益 → 退出。"""
        symbol = position.get("symbol", "")
        pnl_pct = position.get("pnl_pct", 0.0) or 0.0
        atr = market_data.get("atr", 0.0) or 0.0
        entry_date = position.get("entry_date")

        if not entry_date:
            return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                                   current_pnl_pct=pnl_pct, atr=atr)

        if isinstance(entry_date, str):
            try:
                entry_dt = datetime.fromisoformat(entry_date).date()
            except (ValueError, TypeError):
                return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                                       current_pnl_pct=pnl_pct, atr=atr)
        elif isinstance(entry_date, datetime):
            entry_dt = entry_date.date()
        elif isinstance(entry_date, date):
            entry_dt = entry_date
        else:
            return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                                   current_pnl_pct=pnl_pct, atr=atr)

        holding_days = (date.today() - entry_dt).days
        max_days = int(position.get("max_hold_days", 60) or 60)
        min_ret = float(position.get("min_return", 0.02) or 0.02)

        if holding_days > max_days and pnl_pct < min_ret:
            reason = f"时间止损: 持有{holding_days}天 > 上限且收益{pnl_pct:.1%} < {min_ret:.0%}"
            logger.warning("%s %s", symbol, reason)
            return ExitCheckResult(
                symbol=symbol, should_exit=True, reason=reason,
                urgency="NORMAL", exit_pct=100.0,
                rule_triggered="time_stop",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                               current_pnl_pct=pnl_pct, atr=atr)

    # ------------------------------------------------------------------
    # 规则 3: Partial Take-Profit
    # ------------------------------------------------------------------

    def _check_take_profit(self, position: dict, market_data: dict) -> ExitCheckResult:
        """分批止盈: 达到第一目标位出一半，达到第二目标位全出。"""
        symbol = position.get("symbol", "")
        pnl_pct = position.get("pnl_pct", 0.0) or 0.0
        atr = market_data.get("atr", 0.0) or 0.0

        if pnl_pct >= self.second_target:
            reason = f"全部止盈: 达到第二目标位 ({pnl_pct:.1%} ≥ {self.second_target:.0%})"
            logger.info("%s %s", symbol, reason)
            return ExitCheckResult(
                symbol=symbol, should_exit=True, reason=reason,
                urgency="NORMAL", exit_pct=100.0,
                rule_triggered="partial_take_profit_second",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        if pnl_pct >= self.first_target:
            reason = f"分批止盈: 达到第一目标位 ({pnl_pct:.1%} ≥ {self.first_target:.0%})"
            logger.info("%s %s", symbol, reason)
            return ExitCheckResult(
                symbol=symbol, should_exit=True, reason=reason,
                urgency="NORMAL", exit_pct=self.take_profit_first_pct,
                rule_triggered="partial_take_profit_first",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                               current_pnl_pct=pnl_pct, atr=atr)

    # ------------------------------------------------------------------
    # 规则 4: Break-Even Stop
    # ------------------------------------------------------------------

    @staticmethod
    def _check_breakeven(position: dict, market_data: dict) -> ExitCheckResult:
        """保本止损: 浮盈曾达到 breakeven_trigger 但现在已回吐全部利润。"""
        symbol = position.get("symbol", "")
        pnl_pct = position.get("pnl_pct", 0.0) or 0.0
        atr = market_data.get("atr", 0.0) or 0.0
        max_favor = position.get("max_favor_pct")

        if max_favor is None or pnl_pct >= 0:
            return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                                   current_pnl_pct=pnl_pct, atr=atr)

        trigger = float(position.get("breakeven_trigger", 0.10))
        if float(max_favor) >= trigger and pnl_pct < 0:
            reason = (
                f"保本止损: 回吐全部利润 (曾浮盈{float(max_favor):.1%} ≥ "
                f"{trigger:.0%}，现亏损{pnl_pct:.1%})"
            )
            logger.warning("%s %s", symbol, reason)
            return ExitCheckResult(
                symbol=symbol, should_exit=True, reason=reason,
                urgency="HIGH", exit_pct=100.0,
                rule_triggered="breakeven_stop",
                current_pnl_pct=pnl_pct, atr=atr,
            )

        return ExitCheckResult(symbol=symbol, should_exit=False, reason="",
                               current_pnl_pct=pnl_pct, atr=atr)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def reset_trail(self, symbol: str) -> None:
        """重置某标的追踪止损缓存 (平仓时调用)。"""
        self._trailing_stops.pop(symbol, None)
