# -*- coding: utf-8 -*-
"""订单工厂 — 将 Orchestrator 全链路分析结果转换为模拟交易订单。

薄适配层，不包含任何独立的分析/策略/评分逻辑:
  - 信号来源: Orchestrator.run() → TradeSignal (PositioningEngine 产出)
  - 风控检查: 复用 RiskControlEngine
  - 仓位计算: 复用 KellyPositionSizer (热启动) / 线性公式 (冷启动)
  - 成本计算: 复用 AShareCostCalculator (佣金率 万1.3)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.backtest.cost_model import AShareCostCalculator
from src.routing.positioning import TradeSignal

logger = logging.getLogger(__name__)

# 用户指定的佣金费率: 万1.3
PAPER_COMMISSION_RATE = 0.00013


@dataclass
class PaperOrder:
    """模拟交易订单 — 信号→执行的中间表示。"""
    symbol: str
    name: str
    action: str                      # "buy" | "sell"
    price: float                     # 参考价格 (市价)
    quantity: int                    # 交易股数 (整手)
    target_weight: float             # 目标仓位权重
    reason: str                      # 决策原因
    signal_score: float = 0.0        # 裁决评分
    signal_confidence: float = 0.0   # 信号置信度
    stop_price: float = 0.0          # 建议止损价
    cost_estimate: float = 0.0       # 预估交易成本
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class OrderFactory:
    """信号→订单转换器 (薄适配层)。

    用法::

        factory = OrderFactory(capital=200_000)
        result = orchestrator.run("600519")
        order = factory.from_trade_signal(result.signal, current_price=1500.0)
        if order:
            print(f"{order.action} {order.symbol} {order.quantity}股")
    """

    LOT_SIZE = 100  # A 股最小交易单位

    def __init__(
        self,
        capital: float = 200_000.0,
        max_single_pct: float = 0.20,
        min_order_value: float = 2000.0,
    ):
        self._capital = capital
        self._max_single_pct = max_single_pct
        self._min_order_value = min_order_value

        # 复用现有成本计算器，覆盖佣金率为万 1.3
        self._cost_calc = AShareCostCalculator(
            commission_rate=PAPER_COMMISSION_RATE,
        )

    # ------------------------------------------------------------------
    # 主入口: TradeSignal → PaperOrder
    # ------------------------------------------------------------------

    def from_trade_signal(
        self,
        signal: TradeSignal,
        current_price: float = 0.0,
        current_position_qty: int = 0,
    ) -> Optional[PaperOrder]:
        """将 TradeSignal 转换为模拟交易订单。

        Args:
            signal: Orchestrator 管道产出的交易信号
            current_price: 当前市价
            current_position_qty: 当前持仓数量 (用于判断买卖方向)

        Returns:
            PaperOrder 或 None (信号不足以触发交易)
        """
        action = getattr(signal, "action", "HOLD")
        target_weight = getattr(signal, "target_weight", 0.0)
        score = getattr(signal, "confidence", 0.5) * 100  # 粗略转换

        # 从 signal.extra 中提取裁决评分
        extra = getattr(signal, "extra", {}) or {}
        verdict_score = extra.get("verdict_score", score)

        if action in ("HOLD",):
            return None

        if action in ("CLOSE", "REDUCE"):
            return self._sell_order(signal, current_price, current_position_qty)

        if action in ("OPEN", "ADD"):
            return self._buy_order(signal, current_price, verdict_score)

        return None

    # ------------------------------------------------------------------
    # 买入订单
    # ------------------------------------------------------------------

    def _buy_order(
        self,
        signal: TradeSignal,
        price: float,
        score: float,
    ) -> Optional[PaperOrder]:
        """生成买入订单。"""
        if price <= 0:
            logger.warning("%s 价格无效: %.2f", signal.symbol, price)
            return None

        target_weight = getattr(signal, "target_weight", 0.05)
        if target_weight <= 0:
            return None

        # 仓位上限裁剪
        weight = min(target_weight, self._max_single_pct)

        # 计算购买数量
        quantity = self._weight_to_qty(weight, price)
        if quantity <= 0:
            return None

        # 预估成本
        cost = self._cost_calc.calc_buy_cost(signal.symbol, price, quantity)

        # 检查现金是否足够
        needed = price * quantity + cost.total_cost
        if needed > self._capital * 0.95:  # 预留 5% 缓冲
            # 缩量到可承受范围
            affordable_qty = self._weight_to_qty(
                weight * 0.8, price
            )
            if affordable_qty <= 0:
                logger.warning("%s 资金不足，跳过买入", signal.symbol)
                return None
            quantity = affordable_qty
            cost = self._cost_calc.calc_buy_cost(signal.symbol, price, quantity)

        reason_parts = [f"裁决评分 {score:.0f}/100", f"目标仓位 {weight:.1%}"]
        if hasattr(signal, "sizing_method") and signal.sizing_method:
            reason_parts.append(f"仓位法: {signal.sizing_method}")

        stop_price = getattr(signal, "suggested_stop", 0.0)

        return PaperOrder(
            symbol=signal.symbol,
            name=getattr(signal, "name", ""),
            action="buy",
            price=price,
            quantity=quantity,
            target_weight=weight,
            reason=" | ".join(reason_parts),
            signal_score=score,
            signal_confidence=getattr(signal, "confidence", 0.5),
            stop_price=stop_price,
            cost_estimate=cost.total_cost,
        )

    # ------------------------------------------------------------------
    # 卖出订单
    # ------------------------------------------------------------------

    def _sell_order(
        self,
        signal: TradeSignal,
        price: float,
        current_qty: int,
    ) -> Optional[PaperOrder]:
        """生成卖出订单。"""
        if current_qty <= 0:
            logger.debug("%s 无持仓，跳过卖出", signal.symbol)
            return None
        if price <= 0:
            logger.warning("%s 价格无效: %.2f", signal.symbol, price)
            return None

        action = getattr(signal, "action", "REDUCE")
        if action == "CLOSE":
            sell_qty = current_qty
            reason = "清仓信号 (裁决建议清仓)"
        else:
            # REDUCE: 卖出当前持仓的 50%
            sell_qty = max(self.LOT_SIZE, (current_qty // 2 // self.LOT_SIZE) * self.LOT_SIZE)
            reason = "减仓信号 (裁决建议减仓)"

        # 成本预估
        cost = self._cost_calc.calc_sell_cost(signal.symbol, price, sell_qty)

        return PaperOrder(
            symbol=signal.symbol,
            name=getattr(signal, "name", ""),
            action="sell",
            price=price,
            quantity=sell_qty,
            target_weight=0.0,
            reason=reason,
            signal_score=getattr(signal, "confidence", 0.5) * 100,
            signal_confidence=getattr(signal, "confidence", 0.5),
            cost_estimate=cost.total_cost,
        )

    # ------------------------------------------------------------------
    # 数量计算
    # ------------------------------------------------------------------

    def _weight_to_qty(self, weight: float, price: float) -> int:
        """仓位权重 → 股数 (整手取整)。"""
        order_value = self._capital * weight
        if order_value < self._min_order_value:
            return 0
        raw_qty = int(order_value / price)
        lots = max(raw_qty // self.LOT_SIZE, 0) * self.LOT_SIZE
        if lots == 0 and order_value >= self._min_order_value:
            lots = self.LOT_SIZE  # 至少 1 手
        return lots

    # ------------------------------------------------------------------
    # 直接从前裁决结果创建订单 (引擎直接调用)
    # ------------------------------------------------------------------

    def from_verdict(
        self,
        symbol: str,
        name: str,
        verdict_score: float,
        verdict_confidence: float,
        recommendation: str,
        current_price: float,
        current_qty: int = 0,
        stop_price: float = 0.0,
        sizing_weight: float = 0.0,
    ) -> Optional[PaperOrder]:
        """从裁决结果直接创建订单 (不依赖 TradeSignal)。

        当 Orchestrator 产出裁决但 TradeSignal 不可用时使用。
        """
        if recommendation in ("STRONG_BUY", "BUY", "ADD"):
            weight = sizing_weight if sizing_weight > 0 else 0.10
            qty = self._weight_to_qty(min(weight, self._max_single_pct), current_price)
            if qty <= 0:
                return None
            cost = self._cost_calc.calc_buy_cost(symbol, current_price, qty)

            return PaperOrder(
                symbol=symbol, name=name, action="buy",
                price=current_price, quantity=qty,
                target_weight=weight,
                reason=f"裁决: {recommendation} (评分 {verdict_score:.0f})",
                signal_score=verdict_score,
                signal_confidence=verdict_confidence,
                stop_price=stop_price,
                cost_estimate=cost.total_cost,
            )

        elif recommendation in ("REDUCE", "SELL", "STRONG_SELL"):
            if current_qty <= 0:
                return None
            sell_qty = current_qty if recommendation in ("SELL", "STRONG_SELL") else max(
                self.LOT_SIZE, (current_qty // 2 // self.LOT_SIZE) * self.LOT_SIZE
            )
            cost = self._cost_calc.calc_sell_cost(symbol, current_price, sell_qty)

            return PaperOrder(
                symbol=symbol, name=name, action="sell",
                price=current_price, quantity=sell_qty,
                target_weight=0.0,
                reason=f"裁决: {recommendation} (评分 {verdict_score:.0f})",
                signal_score=verdict_score,
                signal_confidence=verdict_confidence,
                cost_estimate=cost.total_cost,
            )

        return None  # HOLD
