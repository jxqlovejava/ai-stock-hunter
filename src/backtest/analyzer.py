# -*- coding: utf-8 -*-
"""分析器系统 — AnalyzerBase + 内置分析器。

借鉴 Backtrader Analyzer 设计:
  - AnalyzerBase: next() 每 bar 累积 + get_analysis() 输出 dict
  - 内置分析器: Sharpe, DrawDown, TradeAnalyzer, WinRate, SQN, TimeReturn

所有分析器共享 strategy 引用，被动观察不修改策略状态。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from src.backtest.strategy import BaizeStrategy


class AnalyzerBase(ABC):
    """分析器基类。

    子类实现:
      - next(): 每 bar 调用，累积数据
      - get_analysis(): 返回计算结果 dict

    用法:
        class MyAnalyzer(AnalyzerBase):
            name = "my_analyzer"

            def next(self):
                self._returns.append(self.strategy.broker.value / self._prev - 1)

            def get_analysis(self) -> dict:
                return {"total_return": sum(self._returns)}
    """

    name: str = "base"

    def __init__(self, strategy: "BaizeStrategy", **params):
        self.strategy = strategy
        self.params = params
        self._started = False

    @abstractmethod
    def next(self):
        """每 bar 调用一次。"""
        ...

    @abstractmethod
    def get_analysis(self) -> dict:
        """返回分析结果。"""
        ...

    @classmethod
    def create(cls, strategy: "BaizeStrategy", **params) -> "AnalyzerBase":
        """工厂方法。"""
        return cls(strategy, **params)


# ------------------------------------------------------------------
# SharpeAnalyzer
# ------------------------------------------------------------------

class SharpeAnalyzer(AnalyzerBase):
    """夏普比率分析器。

    输出:
      - sharperatio: 年化夏普比率 (252 交易日)
      - annual_return: 年化收益率
      - annual_volatility: 年化波动率
      - avg_daily_return: 平均日收益
    """

    name = "sharpe"

    def __init__(self, strategy, periods_per_year: int = 252):
        super().__init__(strategy, periods_per_year=periods_per_year)
        self._returns: list[float] = []
        self._values: list[float] = []

    def next(self):
        val = self.strategy.getvalue()
        self._values.append(val)
        if len(self._values) >= 2:
            ret = (val - self._values[-2]) / self._values[-2]
            self._returns.append(ret)

    def get_analysis(self) -> dict:
        if len(self._returns) < 2:
            return {
                "sharperatio": 0.0,
                "annual_return": 0.0,
                "annual_volatility": 0.0,
                "avg_daily_return": 0.0,
            }
        periods = self.params.get("periods_per_year", 252)
        rets = np.array(self._returns)
        avg_daily = float(np.mean(rets))
        std_daily = float(np.std(rets, ddof=1))
        sharpe = float((avg_daily / std_daily) * np.sqrt(periods)) if std_daily > 0 else 0.0
        annual_ret = float((1 + avg_daily) ** periods - 1)
        annual_vol = float(std_daily * np.sqrt(periods))

        return {
            "sharperatio": round(sharpe, 4),
            "annual_return": round(annual_ret, 4),
            "annual_volatility": round(annual_vol, 4),
            "avg_daily_return": round(avg_daily, 6),
        }


# ------------------------------------------------------------------
# DrawDownAnalyzer
# ------------------------------------------------------------------

class DrawDownAnalyzer(AnalyzerBase):
    """回撤分析器 — 复用 BaseEngine.calculate_drawdown_stats()。

    输出:
      - max_drawdown: 最大回撤 (仅 recovered)
      - max_drawdown_active: 最大回撤 (含 active)
      - avg_drawdown: 平均回撤
      - drawdown_stats: 完整五阶段生命周期 dict
    """

    name = "drawdown"

    def __init__(self, strategy, incl_active: bool = False):
        super().__init__(strategy, incl_active=incl_active)
        self._values: list[float] = []

    def next(self):
        self._values.append(self.strategy.getvalue())

    def get_analysis(self) -> dict:
        from src.backtest.engines.base import BaseEngine

        if len(self._values) < 2:
            return {"max_drawdown": 0.0, "max_drawdown_active": 0.0, "avg_drawdown": 0.0}

        equity = pd.Series(self._values)
        dd_stats = BaseEngine.calculate_drawdown_stats(
            equity, incl_active=self.params.get("incl_active", False)
        )

        return dd_stats.to_dict()


# ------------------------------------------------------------------
# TradeAnalyzer
# ------------------------------------------------------------------

class TradeAnalyzer(AnalyzerBase):
    """交易分析器。

    输出:
      - total_trades: 总交易数
      - won: 盈利笔数
      - lost: 亏损笔数
      - win_rate: 胜率
      - avg_win: 平均盈利
      - avg_loss: 平均亏损
      - profit_factor: 盈亏比
      - max_win_streak: 最大连赢
      - max_loss_streak: 最大连亏
    """

    name = "trades"

    def __init__(self, strategy):
        super().__init__(strategy)
        self._trade_pnls: list[float] = []
        self._prev_trade_count = 0

    def next(self):
        if self.strategy.broker is None:
            return
        current = self.strategy.broker.trade_count
        if current > self._prev_trade_count:
            # 有新交易,记录最后一笔 (简化处理)
            self._prev_trade_count = current

    def get_analysis(self) -> dict:
        # 从 broker 交易记录计算
        if self.strategy.broker is None:
            return {
                "total_trades": 0, "won": 0, "lost": 0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_win_streak": 0, "max_loss_streak": 0,
            }

        # 从 broker 内部交易记录提取 PnL
        closed_trades = []
        buy_queue: dict[str, list[dict]] = {}
        for t in self.strategy.broker._trades:
            symbol = t["symbol"]
            if t["action"] == "BUY":
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append(t)
            elif t["action"] == "SELL":
                if symbol in buy_queue and buy_queue[symbol]:
                    buy = buy_queue[symbol].pop(0)
                    pnl = (t["price"] - buy["price"]) * buy["size"] - t.get("commission", 0)
                    closed_trades.append(pnl)

        if not closed_trades:
            return {
                "total_trades": 0, "won": 0, "lost": 0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_win_streak": 0, "max_loss_streak": 0,
            }

        wins = [p for p in closed_trades if p > 0]
        losses = [p for p in closed_trades if p < 0]

        # 连赢/连亏
        max_win_streak = 0
        max_loss_streak = 0
        current_win = 0
        current_loss = 0
        for p in closed_trades:
            if p > 0:
                current_win += 1
                current_loss = 0
                max_win_streak = max(max_win_streak, current_win)
            else:
                current_loss += 1
                current_win = 0
                max_loss_streak = max(max_loss_streak, current_loss)

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0

        return {
            "total_trades": len(closed_trades),
            "won": len(wins),
            "lost": len(losses),
            "win_rate": round(len(wins) / len(closed_trades), 4) if closed_trades else 0.0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else float("inf"),
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
        }


# ------------------------------------------------------------------
# WinRateAnalyzer
# ------------------------------------------------------------------

class WinRateAnalyzer(AnalyzerBase):
    """胜率分析器 — 简化版。"""

    name = "winrate"

    def __init__(self, strategy):
        super().__init__(strategy)
        self._trade_count = 0

    def next(self):
        if self.strategy.broker is None:
            return
        self._trade_count = self.strategy.broker.trade_count

    def get_analysis(self) -> dict:
        if self.strategy.broker is None or self._trade_count == 0:
            return {"win_rate": 0.0, "total_trades": 0}

        closed = []
        buy_queue: dict[str, list[dict]] = {}
        for t in self.strategy.broker._trades:
            symbol = t["symbol"]
            if t["action"] == "BUY":
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append(t)
            elif t["action"] == "SELL":
                if symbol in buy_queue and buy_queue[symbol]:
                    buy = buy_queue[symbol].pop(0)
                    pnl = (t["price"] - buy["price"]) * buy["size"]
                    closed.append(pnl)

        if not closed:
            return {"win_rate": 0.0, "total_trades": 0}

        return {
            "win_rate": round(sum(1 for p in closed if p > 0) / len(closed), 4),
            "total_trades": len(closed),
        }


# ------------------------------------------------------------------
# SQNAnalyzer — System Quality Number
# ------------------------------------------------------------------

class SQNAnalyzer(AnalyzerBase):
    """System Quality Number (SQN) 分析器。

    SQN = (avg_return / std_return) × sqrt(n_trades)
    用于评估策略质量:
      < 1.0: Poor
      1.0-2.0: Average
      2.0-3.0: Good
      3.0-5.0: Excellent
      > 5.0: Superb

    借鉴 Van Tharp 的 SQN 指标。
    """

    name = "sqn"

    def __init__(self, strategy):
        super().__init__(strategy)
        self._trade_pnls: list[float] = []

    def next(self):
        pass  # 在 get_analysis() 中统计

    def get_analysis(self) -> dict:
        if self.strategy.broker is None:
            return {"sqn": 0.0, "quality": "N/A", "n_trades": 0}

        closed = []
        buy_queue: dict[str, list[dict]] = {}
        for t in self.strategy.broker._trades:
            symbol = t["symbol"]
            if t["action"] == "BUY":
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append(t)
            elif t["action"] == "SELL":
                if symbol in buy_queue and buy_queue[symbol]:
                    buy = buy_queue[symbol].pop(0)
                    # 使用百分比盈亏
                    pnl_pct = (t["price"] - buy["price"]) / buy["price"] if buy["price"] > 0 else 0.0
                    closed.append(pnl_pct)

        if len(closed) < 2:
            return {"sqn": 0.0, "quality": "N/A", "n_trades": len(closed)}

        arr = np.array(closed)
        avg = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        sqn = float((avg / std) * np.sqrt(len(closed))) if std > 0 else 0.0

        if sqn < 1.0:
            quality = "Poor"
        elif sqn < 2.0:
            quality = "Average"
        elif sqn < 3.0:
            quality = "Good"
        elif sqn < 5.0:
            quality = "Excellent"
        else:
            quality = "Superb"

        return {"sqn": round(sqn, 4), "quality": quality, "n_trades": len(closed)}


# ------------------------------------------------------------------
# TimeReturnAnalyzer
# ------------------------------------------------------------------

class TimeReturnAnalyzer(AnalyzerBase):
    """时间序列收益分析器。

    输出:
      - returns: 每 bar 收益率列表
      - cumulative_return: 累计收益率
      - positive_days: 正收益天数
      - negative_days: 负收益天数
    """

    name = "timereturn"

    def __init__(self, strategy):
        super().__init__(strategy)
        self._returns: list[float] = []
        self._prev_value: float | None = None

    def next(self):
        val = self.strategy.getvalue()
        if self._prev_value is not None and self._prev_value > 0:
            ret = (val - self._prev_value) / self._prev_value
            self._returns.append(ret)
        self._prev_value = val

    def get_analysis(self) -> dict:
        if not self._returns:
            return {
                "cumulative_return": 0.0,
                "positive_days": 0,
                "negative_days": 0,
                "total_days": 0,
            }

        cumulative = float(np.prod([1 + r for r in self._returns]) - 1)
        positive = sum(1 for r in self._returns if r > 0)
        negative = sum(1 for r in self._returns if r < 0)

        return {
            "cumulative_return": round(cumulative, 4),
            "positive_days": positive,
            "negative_days": negative,
            "total_days": len(self._returns),
        }
