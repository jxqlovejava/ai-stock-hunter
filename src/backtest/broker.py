# -*- coding: utf-8 -*-
"""BaizeBroker — 回测券商模拟。

封装 ChinaAEngine (T+1/涨跌停/整手) + AShareCostCalculator (佣金/印花税/滑点)。
借鉴 Backtrader BackBroker 设计:
  - 订单队列管理 (Created→Submitted→Accepted→Rejected→Completed)
  - 现金/持仓追踪
  - 委托成交模拟 (Market/Close/Limit/Stop/StopLimit)
  - 佣金+滑点自动计算
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.backtest.cost_model import AShareCostCalculator, CostBreakdown
from src.backtest.engines.base import Position
from src.backtest.engines.china_a import ChinaAEngine
from src.backtest.result import Order, OrderStatus, OrderType

logger = logging.getLogger(__name__)


class BaizeBroker:
    """回测券商模拟 — 封装 A 股市场规则 + 成本模型。

    用法:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        cost_calc = AShareCostCalculator()
        broker = BaizeBroker(cash=1_000_000, engine=engine, cost_calculator=cost_calc)

        order_id = broker.buy("000001.SZ", price=10.5, size=1000, timestamp=...)
        # → 自动检查 T+1 / 涨跌停 / 现金充足 / 佣金+滑点
    """

    def __init__(
        self,
        cash: float = 1_000_000.0,
        engine: ChinaAEngine | None = None,
        cost_calculator: AShareCostCalculator | None = None,
    ):
        self._initial_cash = cash
        self.cash = cash
        self._positions: dict[str, Position] = {}
        self._engine = engine or ChinaAEngine({"initial_cash": cash})
        self._cost_calc = cost_calculator or AShareCostCalculator()
        self._orders: list[Order] = []
        self._order_counter: int = 0
        self._trades: list = []  # TradeRecord 列表

        # 收盘价缓存 (由 cerebro 每 bar 更新)
        self._last_prices: dict[str, float] = {}
        # 当前 bar 时间戳
        self._current_ts: pd.Timestamp | None = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    @property
    def value(self) -> float:
        """组合总价值 = 现金 + 持仓市值。"""
        total = self.cash
        for symbol, pos in self._positions.items():
            price = self._last_prices.get(symbol, pos.entry_price)
            total += pos.size * price * pos.direction
        return total

    @property
    def positions_value(self) -> float:
        """持仓总市值。"""
        total = 0.0
        for symbol, pos in self._positions.items():
            price = self._last_prices.get(symbol, pos.entry_price)
            total += pos.size * price * pos.direction
        return total

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def order_count(self) -> int:
        return len(self._orders)

    @property
    def trade_count(self) -> int:
        return len(self._trades)

    # ------------------------------------------------------------------
    # 价格更新
    # ------------------------------------------------------------------

    def update_prices(self, prices: dict[str, float], timestamp: pd.Timestamp):
        """每 bar 更新收盘价缓存。"""
        self._last_prices.update(prices)
        self._current_ts = timestamp

    def get_price(self, symbol: str) -> float | None:
        return self._last_prices.get(symbol)

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------

    def buy(
        self,
        symbol: str,
        price: float,
        size: int | None = None,
        timestamp: pd.Timestamp | None = None,
        order_type: OrderType = OrderType.MARKET,
    ) -> int:
        """买入下单。

        Returns:
            order_id (>= 0 成功, -1 失败)
        """
        return self._submit_order(symbol, "BUY", price, size, timestamp, order_type)

    def sell(
        self,
        symbol: str,
        price: float,
        size: int | None = None,
        timestamp: pd.Timestamp | None = None,
        order_type: OrderType = OrderType.MARKET,
    ) -> int:
        """卖出下单。"""
        return self._submit_order(symbol, "SELL", price, size, timestamp, order_type)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def getposition(self, symbol: str) -> Position | None:
        """返回持仓记录。"""
        return self._positions.get(symbol)

    def getposition_size(self, symbol: str) -> int:
        """返回持仓股数。"""
        pos = self._positions.get(symbol)
        return int(pos.size) if pos else 0

    def get_trades(self) -> list:
        """返回所有已完成交易 (已平仓)。"""
        return [t for t in self._trades if not t.get("is_open", True)]

    def get_open_trades(self) -> list:
        """返回所有未平仓交易。"""
        return [t for t in self._trades if t.get("is_open", True)]

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _submit_order(
        self,
        symbol: str,
        action: str,
        price: float,
        size: int | None,
        timestamp: pd.Timestamp | None,
        order_type: OrderType,
    ) -> int:
        """提交订单 → 执行检查 → 成交或拒单。"""
        self._order_counter += 1
        order_id = self._order_counter
        ts = timestamp or self._current_ts or pd.Timestamp.now()

        order = Order(
            order_id=order_id,
            symbol=symbol,
            order_type=order_type,
            action=action,
            size=size or 0,
            price=price,
            status=OrderStatus.CREATED,
            created_at=ts,
        )

        # 1. 构造 bar (供 ChinaAEngine 检查)
        bar = self._make_bar(symbol, price)

        # 2. 检查执行条件
        direction = 1 if action == "BUY" else 0  # 0=卖出 (平仓)

        if not self._engine.can_execute(symbol, direction, bar):
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"can_execute failed: T+1/price limit"
            self._orders.append(order)
            return -1

        # 3. 确定成交价 (滑点)
        exec_dir = 1 if action == "BUY" else -1
        exec_price = self._engine.apply_slippage(price, exec_dir)

        # 4. 确定股数
        if size is None or size <= 0:
            order.reject_reason = "size must be > 0"
            order.status = OrderStatus.REJECTED
            self._orders.append(order)
            return -1

        rounded_size = int(self._engine.round_size(size, exec_price))
        if rounded_size <= 0:
            order.reject_reason = "rounded size <= 0"
            order.status = OrderStatus.REJECTED
            self._orders.append(order)
            return -1

        # 5. 计算成本和现金检查
        is_open = action == "BUY"
        notional = rounded_size * exec_price
        cost: CostBreakdown = self._cost_calc.estimate_cost(
            symbol=symbol,
            price=exec_price,
            quantity=rounded_size,
            direction=exec_dir,
            is_open=is_open,
        )

        if action == "BUY":
            if cost.net_proceeds > self.cash:
                order.reject_reason = (
                    f"insufficient cash: need {cost.net_proceeds:.2f}, have {self.cash:.2f}"
                )
                order.status = OrderStatus.REJECTED
                self._orders.append(order)
                return -1
            self.cash -= cost.net_proceeds
        else:
            # 卖出: 检查持仓
            pos = self._positions.get(symbol)
            if pos is None or pos.size < rounded_size:
                order.reject_reason = (
                    f"insufficient position: have {pos.size if pos else 0}, need {rounded_size}"
                )
                order.status = OrderStatus.REJECTED
                self._orders.append(order)
                return -1
            self.cash += cost.net_proceeds

        # 6. 更新持仓
        if action == "BUY":
            existing = self._positions.get(symbol)
            if existing and existing.direction == 1:
                # 加仓: 更新均价和总股数
                total_notional = existing.entry_notional + notional
                total_size = existing.size + rounded_size
                new_entry_price = total_notional / total_size if total_size > 0 else exec_price
                self._positions[symbol] = Position(
                    symbol=symbol,
                    direction=1,
                    size=float(total_size),
                    entry_price=new_entry_price,
                    entry_time=ts,
                    entry_notional=total_notional,
                )
            else:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    direction=1,
                    size=float(rounded_size),
                    entry_price=exec_price,
                    entry_time=ts,
                    entry_notional=notional,
                )
        else:
            # 卖出: 减仓
            pos = self._positions[symbol]
            remaining = pos.size - rounded_size
            if remaining <= 0:
                del self._positions[symbol]
            else:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    direction=pos.direction,
                    size=float(remaining),
                    entry_price=pos.entry_price,
                    entry_time=pos.entry_time,
                    entry_notional=pos.entry_notional * (remaining / pos.size),
                )

        # 7. 记录
        order.status = OrderStatus.COMPLETED
        order.executed_price = exec_price
        order.executed_size = rounded_size
        order.executed_at = ts
        order.commission = cost.total_cost
        self._orders.append(order)

        self._record_trade(symbol, action, rounded_size, exec_price, ts, cost)

        return order_id

    def _make_bar(self, symbol: str, price: float) -> pd.Series:
        """构造 ChinaAEngine 所需的 bar Series。"""
        prev = self._last_prices.get(symbol, price)
        bar = pd.Series({
            "close": price,
            "prev_close": prev,
            "open": price,
            "timestamp": self._current_ts,
        })
        return bar

    def _record_trade(
        self,
        symbol: str,
        action: str,
        size: int,
        price: float,
        ts: pd.Timestamp,
        cost: CostBreakdown,
    ):
        """记录交易到 trade 列表。"""
        trade = {
            "trade_id": len(self._trades) + 1,
            "symbol": symbol,
            "action": action,
            "size": size,
            "price": price,
            "notional": round(size * price, 2),
            "commission": cost.total_cost,
            "timestamp": ts,
            "is_open": action == "BUY",  # 买入标记为开仓
        }
        self._trades.append(trade)

    # ------------------------------------------------------------------
    # 结算 (回测结束时调用)
    # ------------------------------------------------------------------

    def settle(self, final_prices: dict[str, float]) -> dict:
        """回测结束结算 — 以最后价格平仓所有持仓。

        Returns:
            {"final_cash": float, "final_value": float, "total_pnl": float}
        """
        self.update_prices(final_prices, self._current_ts or pd.Timestamp.now())
        final_value = self.value
        return {
            "initial_cash": self._initial_cash,
            "final_cash": self.cash,
            "positions_value": self.positions_value,
            "final_value": final_value,
            "total_return": (final_value / self._initial_cash) - 1.0,
            "total_orders": len(self._orders),
            "total_trades": len(self._trades),
        }
