# -*- coding: utf-8 -*-
"""BaizeStrategy — 回测策略抽象基类。

借鉴 Backtrader Strategy 的设计:
  - __init__(): 设置指标
  - next(): 每 bar 调用，生成信号
  - buy() / sell() / close(): 下单接口
  - notify_order() / notify_trade(): 事件钩子

关键差异 vs Backtrader:
  - 不依赖 bt.LineIterator，直接操作 pandas DataFrame
  - 通过 self.datas[i].close[-1] 访问当前 bar 价格
  - Sizer 通过 cerebro.add_sizer() 注入，strategy 无需关心仓位计算
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from src.backtest.cerebro import BaizeDataFeed


class BaizeStrategy(ABC):
    """回测策略抽象基类。

    子类只需实现 next()，每 bar 判断是否买卖。

    用法:
        class MomentumStrategy(BaizeStrategy):
            def __init__(self, cerebro, lookback=20):
                super().__init__(cerebro, lookback=lookback)
                self.lookback = lookback

            def next(self):
                for data in self.datas:
                    if len(data.close) < self.lookback:
                        continue
                    if data.close[-1] > data.close[-self.lookback]:
                        if self.getposition(data) == 0:
                            self.buy(data)
                    elif self.getposition(data) > 0 and data.close[-1] < data.close[-10]:
                        self.close(data)
    """

    def __init__(self, cerebro: "BaizeCerebro", **params):
        self.cerebro = cerebro
        self.params: dict = params
        self.datas: list[BaizeDataFeed] = []
        self.data: BaizeDataFeed | None = None     # 主数据源 (datas[0])
        self.broker: "BaizeBroker" | None = None
        self.sizer = None                           # 由 cerebro 注入
        self.analyzers: dict[str, "AnalyzerBase"] = {}

        # 设置 params 为属性访问
        for k, v in params.items():
            setattr(self, k, v)

    # ------------------------------------------------------------------
    # 核心回调 (子类覆盖)
    # ------------------------------------------------------------------

    @abstractmethod
    def next(self):
        """每 bar 调用一次。子类必须实现。

        访问数据:
          - self.data.close[-1]  → 当前 bar 收盘价
          - self.data.close[-2]  → 上一 bar 收盘价
          - self.data.open[-1]   → 当前 bar 开盘价
          - self.data.high[-1]   → 当前 bar 最高价
          - self.data.low[-1]    → 当前 bar 最低价
          - self.data.volume[-1] → 当前 bar 成交量

        下单:
          - self.buy(data, size)   → 买入
          - self.sell(data, size)  → 卖出
          - self.close(data)       → 平仓
        """
        ...

    def notify_order(self, order: "Order"):
        """订单状态变更通知。子类可覆盖。"""
        pass

    def notify_trade(self, trade: "TradeRecord"):
        """交易完成通知。子类可覆盖。"""
        pass

    def start(self):
        """回测开始前调用一次。子类可覆盖。"""
        pass

    def stop(self):
        """回测结束后调用一次。子类可覆盖。"""
        pass

    # ------------------------------------------------------------------
    # 下单接口
    # ------------------------------------------------------------------

    def buy(
        self,
        data: "BaizeDataFeed | None" = None,
        size: int | None = None,
        price: float | None = None,
        **kwargs,
    ) -> int:
        """买入下单。返回 order_id，-1 表示失败。

        Args:
            data: 数据源 (默认 self.data)
            size: 股数 (None 则由 sizer 决定)
            price: 限价 (None 则市价)
        """
        if data is None:
            data = self.data
        if data is None or self.broker is None:
            return -1
        return self.broker.buy(
            symbol=data.symbol,
            price=price if price is not None else data.close[-1],
            size=size,
            timestamp=data.datetime[-1] if data.datetime is not None else None,
        )

    def sell(
        self,
        data: "BaizeDataFeed | None" = None,
        size: int | None = None,
        price: float | None = None,
        **kwargs,
    ) -> int:
        """卖出下单。"""
        if data is None:
            data = self.data
        if data is None or self.broker is None:
            return -1
        return self.broker.sell(
            symbol=data.symbol,
            price=price if price is not None else data.close[-1],
            size=size,
            timestamp=data.datetime[-1] if data.datetime is not None else None,
        )

    def close(self, data: "BaizeDataFeed | None" = None) -> int:
        """平仓 (卖出全部持仓)。"""
        if data is None:
            data = self.data
        if data is None or self.broker is None:
            return -1
        pos = self.broker.getposition(data.symbol)
        if pos is None or pos.size == 0:
            return -1
        return self.broker.sell(
            symbol=data.symbol,
            price=data.close[-1],
            size=pos.size,
            timestamp=data.datetime[-1] if data.datetime is not None else None,
        )

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def getposition(self, data: "BaizeDataFeed") -> int:
        """返回当前持仓股数。"""
        if self.broker is None:
            return 0
        pos = self.broker.getposition(data.symbol)
        return pos.size if pos else 0

    def getposition_pnl(self, data: "BaizeDataFeed") -> float:
        """返回当前持仓浮动盈亏。"""
        if self.broker is None:
            return 0.0
        pos = self.broker.getposition(data.symbol)
        if pos is None or pos.size == 0:
            return 0.0
        return (data.close[-1] - pos.entry_price) * pos.size

    def getcash(self) -> float:
        """返回可用现金。"""
        return self.broker.cash if self.broker else 0.0

    def getvalue(self) -> float:
        """返回组合总价值。"""
        return self.broker.value if self.broker else 0.0

    # ------------------------------------------------------------------
    # 内部方法 (由 Cerebro 调用)
    # ------------------------------------------------------------------

    def _next(self):
        """Cerebro 调用的包装器，执行 next() + analyzers。"""
        self.next()
        # 通知 analyzers
        for analyzer in self.analyzers.values():
            analyzer.next()

    def _set_datas(self, datas: list["BaizeDataFeed"]):
        """Cerebro 注入数据源。"""
        self.datas = datas
        if datas:
            self.data = datas[0]

    def _set_broker(self, broker: "BaizeBroker"):
        self.broker = broker
