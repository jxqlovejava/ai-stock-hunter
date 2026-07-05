# -*- coding: utf-8 -*-
"""信号适配器 — 将 L3 TradeSignal 转换为 mx-moni 可执行的交易指令。

处理:
  - 仓位计算 → 模拟资金分配
  - 限价/市价决策
  - 信号去重（避免重复下单）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MoniOrder:
    """模拟交易订单。"""
    symbol: str
    name: str = ""
    action: str = "buy"  # "buy" | "sell"
    price: float = 0.0
    quantity: int = 0
    use_market_price: bool = True
    signal_score: float = 0.0
    reason: str = ""
    created_at: datetime = field(default_factory=datetime.now)


class SignalAdapter:
    """L3 TradeSignal → MoniOrder 转换器。"""

    # 默认配置
    DEFAULT_CAPITAL = 100_000.0  # 初始模拟资金（元）
    MAX_POSITION_PCT = 0.20     # 单票最大仓位
    MIN_ORDER_VALUE = 2000.0    # 最低下单金额（元）
    LOT_SIZE = 100              # A股最小交易单位

    def __init__(
        self,
        initial_capital: float = DEFAULT_CAPITAL,
        max_position_pct: float = MAX_POSITION_PCT,
    ):
        self._capital = initial_capital
        self._max_position_pct = max_position_pct
        self._sent_orders: set[str] = set()  # 去重

    # ------------------------------------------------------------------
    # 核心转换
    # ------------------------------------------------------------------

    def to_moni_order(
        self,
        signal,  # TradeSignal
        current_price: float = 0.0,
    ) -> Optional[MoniOrder]:
        """将 TradeSignal 转换为模拟交易订单。

        Args:
            signal: L3 产出的交易信号
            current_price: 当前市价（用于计算数量）

        Returns:
            MoniOrder 或 None（信号已处理或无效）
        """
        # 去重
        dedup_key = f"{signal.symbol}:{signal.action}:{datetime.now().strftime('%Y%m%d')}"
        if dedup_key in self._sent_orders:
            logger.debug("信号已处理，跳过: %s", dedup_key)
            return None

        # 计算数量
        quantity = self._calc_quantity(signal, current_price)
        if quantity <= 0:
            logger.warning("计算数量为0: %s weight=%.2f", signal.symbol, signal.weight)
            return None

        # 确定价格模式
        use_market = True
        price = 0.0
        if hasattr(signal, "limit_price") and signal.limit_price:
            use_market = False
            price = signal.limit_price

        order = MoniOrder(
            symbol=signal.symbol,
            name=getattr(signal, "name", ""),
            action=signal.action if hasattr(signal, "action") else "buy",
            price=price,
            quantity=quantity,
            use_market_price=use_market,
            signal_score=getattr(signal, "score", 0.0),
            reason=getattr(signal, "reason", ""),
        )

        self._sent_orders.add(dedup_key)
        return order

    def to_moni_orders(
        self,
        signals: list,  # list[TradeSignal]
        quotes: dict[str, float] | None = None,
    ) -> list[MoniOrder]:
        """批量信号转换。按优先级排序。"""
        quotes = quotes or {}
        orders = []
        for sig in sorted(signals, key=lambda s: getattr(s, "weight", 0), reverse=True):
            price = quotes.get(sig.symbol, 0.0)
            order = self.to_moni_order(sig, price)
            if order:
                orders.append(order)
        return orders

    # ------------------------------------------------------------------
    # 数量计算
    # ------------------------------------------------------------------

    def _calc_quantity(self, signal, price: float) -> int:
        """根据仓位权重计算交易数量。"""
        weight = getattr(signal, "weight", 0.05)
        if weight <= 0:
            return 0

        # 单票资金上限
        max_order_value = self._capital * min(weight, self._max_position_pct)
        if max_order_value < self.MIN_ORDER_VALUE:
            return 0

        # 按价格算股数
        ref_price = price if price > 0 else 10.0  # fallback 10元
        raw_qty = int(max_order_value / ref_price)

        # 取整到 100 的倍数
        lots = max(raw_qty // self.LOT_SIZE, 0) * self.LOT_SIZE
        if lots == 0 and max_order_value >= self.MIN_ORDER_VALUE:
            lots = self.LOT_SIZE  # 至少 1 手

        return lots

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def clear_history(self):
        """清除已发送记录（新交易日调用）。"""
        self._sent_orders.clear()

    @property
    def pending_count(self) -> int:
        return len(self._sent_orders)
