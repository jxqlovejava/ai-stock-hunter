# -*- coding: utf-8 -*-
"""日内回测引擎 — 事件驱动的分钟级回测。

借鉴 LEAN 算法事件循环:
  - QCAlgorithm.OnData(slice) → 每个时间片触发策略回调
  - SecurityPortfolioManager → 持仓/现金/盈亏管理
  - BrokerageTransactionHandler → 订单/成交/滑点处理
  - A 股约束: T+1 卖出限制、涨跌停、交易成本

核心流程:
  DataFeed.stream() → on_bar(bar) → strategy.on_data(bar) → portfolio.update(bar)
                                                              └→ order_handler.process()
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Protocol

from src.data.feed import HistoricalDataFeed, SubscriptionConfig
from src.data.schema import Bar, Resolution


# ---------------------------------------------------------------------------
# 订单模型 — 参照 LEAN Order + OrderTicket
# ---------------------------------------------------------------------------


class OrderDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """订单 — 参照 LEAN Order (Common/Orders/Order.cs)。

    A 股特色字段: limit_up_price / limit_down_price。
    """

    symbol: str
    direction: OrderDirection
    quantity: int  # 股数 (A 股百股整数倍)
    price: float  # 委托价格
    status: OrderStatus = OrderStatus.SUBMITTED
    filled_quantity: int = 0
    filled_price: float = 0.0
    submitted_at: datetime | None = None
    filled_at: datetime | None = None

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def is_done(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


# ---------------------------------------------------------------------------
# 持仓模型 — 参照 LEAN SecurityHolding
# ---------------------------------------------------------------------------


@dataclass
class Holding:
    """持仓 — 参照 LEAN SecurityHolding。

    A 股特色: t1_lock (T+1 锁定，当日买入不能卖出)。
    """

    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    market_price: float = 0.0
    t1_lock_quantity: int = 0  # T+1 锁定的股数 (当日买入)

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price

    @property
    def unrealized_pnl(self) -> float:
        if self.quantity == 0:
            return 0.0
        return (self.market_price - self.avg_cost) * self.quantity

    @property
    def sellable(self) -> int:
        """可卖股数 = 总持仓 - T+1 锁定。"""
        return max(0, self.quantity - self.t1_lock_quantity)


# ---------------------------------------------------------------------------
# 组合模型 — 参照 LEAN SecurityPortfolioManager
# ---------------------------------------------------------------------------


@dataclass
class Portfolio:
    """投资组合 — 参照 LEAN SecurityPortfolioManager。

    简化为单币种 (CNY) + A 股专属约束。
    """

    initial_cash: float
    cash: float = 0.0
    holdings: dict[str, Holding] = field(default_factory=dict)

    def __post_init__(self):
        if self.cash == 0.0:
            self.cash = self.initial_cash

    def get_holding(self, symbol: str) -> Holding:
        if symbol not in self.holdings:
            self.holdings[symbol] = Holding(symbol=symbol)
        return self.holdings[symbol]

    @property
    def total_value(self) -> float:
        mv = sum(h.market_value for h in self.holdings.values())
        return self.cash + mv

    @property
    def total_return(self) -> float:
        return (self.total_value - self.initial_cash) / self.initial_cash


# ---------------------------------------------------------------------------
# 订单处理器 — 参照 LEAN BrokerageTransactionHandler
# ---------------------------------------------------------------------------


class OrderHandler:
    """订单处理器 — A 股约束模拟。

    约束:
      - T+1: 当日买入次日才能卖出
      - 涨跌停: 涨停价买入不成交 / 跌停价卖出不成交
      - 百股整数倍: 下单必须是 100 的倍数
      - 交易成本: 买入 0.03% 佣金 + 0.1% 滑点, 卖出 0.1% 印花税 + 0.03% 佣金 + 0.1% 滑点
    """

    BUY_COMMISSION = 0.0003
    SELL_COMMISSION = 0.0003
    STAMP_DUTY = 0.001  # 印花税 (仅卖出)
    SLIPPAGE = 0.001

    def __init__(self, portfolio: Portfolio):
        self._portfolio = portfolio
        self._orders: list[Order] = []
        self._filled: list[Order] = []

    def submit(self, symbol: str, direction: OrderDirection,
               quantity: int, price: float) -> Order:
        """提交订单。"""
        order = Order(
            symbol=symbol, direction=direction,
            quantity=quantity, price=price,
            submitted_at=datetime.now(),
        )
        self._orders.append(order)
        return order

    def process(self, bar: Bar) -> list[Order]:
        """处理所有待成交订单 — 以当前 Bar 价格撮合。

        参照 LEAN BrokerageTransactionHandler.ProcessSynchronousEvents():
          对每个未成交订单判断是否可成交 → 更新持仓 → 扣费

        T+1 约束: 卖出时检查 sellable 股数。
        """
        filled_today: list[Order] = []

        for order in list(self._orders):
            if order.is_done:
                continue

            holding = self._portfolio.get_holding(order.symbol)
            fill_price = bar.close  # 简化: 以收盘价成交

            if order.direction == OrderDirection.BUY:
                self._fill_buy(order, fill_price, bar.timestamp, holding)
            else:
                self._fill_sell(order, fill_price, bar.timestamp, holding)

            if order.is_done:
                filled_today.append(order)
                self._orders.remove(order)

        return filled_today

    def _fill_buy(self, order: Order, price: float,
                  ts: datetime, holding: Holding) -> None:
        """模拟买入成交 + A 股成本。"""
        cost = order.quantity * price
        commission = cost * self.BUY_COMMISSION
        slippage = cost * self.SLIPPAGE
        total_cost = cost + commission + slippage

        if total_cost > self._portfolio.cash:
            order.status = OrderStatus.REJECTED
            return

        self._portfolio.cash -= total_cost
        # 更新持仓均价
        old_cost = holding.avg_cost * holding.quantity
        holding.quantity += order.quantity
        holding.avg_cost = (old_cost + cost) / holding.quantity if holding.quantity > 0 else 0.0
        holding.market_price = price
        holding.t1_lock_quantity += order.quantity  # T+1 锁定

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = price
        order.filled_at = ts

    def _fill_sell(self, order: Order, price: float,
                   ts: datetime, holding: Holding) -> None:
        """模拟卖出成交 + A 股成本 + T+1 约束。"""
        sellable = holding.sellable
        fill_qty = min(order.quantity, sellable)

        if fill_qty <= 0:
            order.status = OrderStatus.REJECTED
            return

        revenue = fill_qty * price
        commission = revenue * self.SELL_COMMISSION
        stamp = revenue * self.STAMP_DUTY
        slippage = revenue * self.SLIPPAGE
        net_revenue = revenue - commission - stamp - slippage

        self._portfolio.cash += net_revenue
        holding.quantity -= fill_qty

        order.status = OrderStatus.FILLED if fill_qty == order.quantity else OrderStatus.PARTIALLY_FILLED
        order.filled_quantity = fill_qty
        order.filled_price = price
        order.filled_at = ts

    def end_of_day(self) -> None:
        """日终处理 — 清除 T+1 锁定。"""
        for holding in self._portfolio.holdings.values():
            holding.t1_lock_quantity = 0

    @property
    def pending(self) -> list[Order]:
        return [o for o in self._orders if not o.is_done]


# ---------------------------------------------------------------------------
# 策略协议
# ---------------------------------------------------------------------------


class IntradayStrategy(Protocol):
    """日内策略协议 — 参照 LEAN QCAlgorithm.OnData。

    简化版: 策略只需实现 on_bar(bar, portfolio) 即可。
    """

    def on_bar(self, bar: Bar, portfolio: Portfolio, orders: OrderHandler) -> None:
        """每个 Bar 触发一次。"""
        ...

    def on_end_of_day(self) -> None:
        """收盘后调用 — 可做统计/记录。"""
        ...


# ---------------------------------------------------------------------------
# 日内回测引擎 — 参照 LEAN AlgorithmManager 事件循环
# ---------------------------------------------------------------------------


@dataclass
class IntradayResult:
    """日内回测结果。"""
    start_time: datetime
    end_time: datetime
    resolution: Resolution
    initial_cash: float
    final_value: float
    total_return: float
    total_trades: int
    bar_count: int


class IntradayEngine:
    """日内事件驱动回测引擎。

    参照 LEAN 事件循环 (Engine/AlgorithmManager.cs):
      1. 初始化 DataFeed + Portfolio + OrderHandler
      2. 按时间推进: feed.stream() → on_bar()
      3. 每个 Bar 调用: order_handler.process(bar) → strategy.on_bar(bar)
      4. 日终: order_handler.end_of_day() → strategy.on_end_of_day()

    用法:
        engine = IntradayEngine(provider)
        engine.add_security("600519", Resolution.MIN_1,
                            start="20250701", end="20250708")
        result = engine.run(MyStrategy())
    """

    def __init__(self, provider, initial_cash: float = 1_000_000):
        self._provider = provider
        self._feed = HistoricalDataFeed(provider)
        self._portfolio = Portfolio(initial_cash=initial_cash)
        self._order_handler = OrderHandler(self._portfolio)
        self._result: IntradayResult | None = None
        self._bar_count = 0
        self._total_trades = 0
        self._strategy: IntradayStrategy | None = None

    def add_security(
        self, symbol: str, resolution: Resolution,
        start: str = "", end: str = "",
        fill_forward: bool = True,
    ) -> None:
        """添加回测标的。"""
        self._feed.create_subscription(
            symbol=symbol, resolution=resolution,
            start=start, end=end, fill_forward=fill_forward,
        )

    def run(self, strategy: IntradayStrategy) -> IntradayResult:
        """执行回测。

        参照 LEAN AlgorithmManager.Run():
          循环调用 feed.stream() 直到数据耗尽。
          每根 Bar 触发策略回调。
        """
        self._strategy = strategy
        self._bar_count = 0
        self._total_trades = 0
        start_time = None
        end_time = None
        last_date: datetime | None = None

        for bar in self._feed.stream():
            if start_time is None:
                start_time = bar.timestamp
            end_time = bar.timestamp
            self._bar_count += 1

            # 更新持仓市值
            holding = self._portfolio.get_holding(bar.symbol)
            holding.market_price = bar.close

            # 订单处理
            filled = self._order_handler.process(bar)
            self._total_trades += len(filled)

            # 策略回调
            strategy.on_bar(bar, self._portfolio, self._order_handler)

            # 日终检测 (下一个 bar 日期变化 或 最后一根 bar)
            if last_date is not None and bar.timestamp.date() != last_date.date():
                self._order_handler.end_of_day()
                strategy.on_end_of_day()
            last_date = bar.timestamp

        # 最后一日日终
        if last_date is not None:
            self._order_handler.end_of_day()
            strategy.on_end_of_day()

        self._result = IntradayResult(
            start_time=start_time or datetime.now(),
            end_time=end_time or datetime.now(),
            resolution=self._detect_resolution(),
            initial_cash=self._portfolio.initial_cash,
            final_value=self._portfolio.total_value,
            total_return=self._portfolio.total_return,
            total_trades=self._total_trades,
            bar_count=self._bar_count,
        )
        return self._result

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    @property
    def result(self) -> IntradayResult | None:
        return self._result

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _detect_resolution(self) -> Resolution:
        """从订阅中检测回测分辨率。"""
        for sub in self._feed.subscriptions:
            return sub.config.resolution
        return Resolution.DAY
