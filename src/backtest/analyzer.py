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


# ------------------------------------------------------------------
# CalmarAnalyzer — Calmar 比率
#
# Adapted from DojoAgents portfolio_performance.py:compute_risk_stats()
# Calmar = 年化收益率 / |最大回撤|
# ------------------------------------------------------------------

class CalmarAnalyzer(AnalyzerBase):
    """Calmar 比率分析器。

    输出:
      - calmar_ratio: 年化收益率 / |最大回撤|
      - annual_return: 年化收益率
      - max_drawdown: 最大回撤 %
    """

    name = "calmar"

    def __init__(self, strategy, periods_per_year: int = 252):
        super().__init__(strategy, periods_per_year=periods_per_year)
        self._values: list[float] = []

    def next(self):
        self._values.append(self.strategy.getvalue())

    def get_analysis(self) -> dict:
        periods = self.params.get("periods_per_year", 252)
        if len(self._values) < 2:
            return {"calmar_ratio": 0.0, "annual_return": 0.0, "max_drawdown_pct": 0.0}

        values = [v for v in self._values if v > 0]
        if len(values) < 2:
            return {"calmar_ratio": 0.0, "annual_return": 0.0, "max_drawdown_pct": 0.0}

        # 年化收益
        total_return = values[-1] / values[0]
        n_days = len(values)
        annualized = (total_return ** (periods / n_days) - 1) * 100

        # 最大回撤 (参考 DojoAgents 的线性扫描)
        peak = values[0]
        max_dd = 0.0
        for v in values:
            peak = max(peak, v)
            dd = (v / peak - 1) * 100
            max_dd = min(max_dd, dd)

        calmar = round(annualized / abs(max_dd), 4) if max_dd < 0 else 0.0

        return {
            "calmar_ratio": calmar,
            "annual_return_pct": round(annualized, 2),
            "max_drawdown_pct": round(max_dd, 2),
        }


# ------------------------------------------------------------------
# SortinoAnalyzer — Sortino 比率
#
# Sortino = (年化收益 - 无风险利率) / 下行标准差
# 比 Sharpe 更合理，只惩罚下行波动
# ------------------------------------------------------------------

class SortinoAnalyzer(AnalyzerBase):
    """Sortino 比率分析器。

    输出:
      - sortino_ratio: Sortino 比率（年化）
      - downside_deviation: 下行标准差（年化）
      - annual_return: 年化收益率
    """

    name = "sortino"

    def __init__(self, strategy, periods_per_year: int = 252, risk_free: float = 0.02):
        super().__init__(strategy, periods_per_year=periods_per_year, risk_free=risk_free)
        self._returns: list[float] = []
        self._prev_value: float | None = None

    def next(self):
        val = self.strategy.getvalue()
        if self._prev_value is not None and self._prev_value > 0:
            ret = (val - self._prev_value) / self._prev_value
            self._returns.append(ret)
        self._prev_value = val

    def get_analysis(self) -> dict:
        periods = self.params.get("periods_per_year", 252)
        rf = self.params.get("risk_free", 0.02)

        if len(self._returns) < 2:
            return {"sortino_ratio": 0.0, "downside_deviation": 0.0, "annual_return": 0.0}

        rets = np.array(self._returns)
        avg_daily = float(np.mean(rets))
        annual_ret = float((1 + avg_daily) ** periods - 1)

        # 下行标准差：只计入负收益
        downside_rets = rets[rets < 0]
        if len(downside_rets) < 1:
            return {"sortino_ratio": float("inf") if annual_ret > rf else 0.0,
                    "downside_deviation": 0.0,
                    "annual_return": round(annual_ret, 4)}

        daily_rf = (1 + rf) ** (1 / periods) - 1
        downside_var = float(np.mean((downside_rets - daily_rf) ** 2))
        downside_vol = float(np.sqrt(downside_var) * np.sqrt(periods))
        sortino = round((annual_ret - rf) / downside_vol, 4) if downside_vol > 0 else 0.0

        return {
            "sortino_ratio": sortino,
            "downside_deviation": round(downside_vol, 4),
            "annual_return": round(annual_ret, 4),
        }


# ------------------------------------------------------------------
# VaRAnalyzer — Value at Risk
#
# 历史模拟法 + 参数法 (假设正态分布)
# ------------------------------------------------------------------

class VaRAnalyzer(AnalyzerBase):
    """VaR (Value at Risk) 分析器。

    输出:
      - var_95_historical: 历史模拟法 VaR (置信度 95%)
      - var_95_parametric: 参数法 VaR (置信度 95%)
      - var_99_historical: VaR (99%)
      - cvar_95: 条件 VaR / 期望尾部损失 (95%)
    """

    name = "var"

    def __init__(self, strategy, confidence: float = 0.95):
        super().__init__(strategy, confidence=confidence)
        self._returns: list[float] = []
        self._prev_value: float | None = None

    def next(self):
        val = self.strategy.getvalue()
        if self._prev_value is not None and self._prev_value > 0:
            ret = (val - self._prev_value) / self._prev_value
            self._returns.append(ret)
        self._prev_value = val

    def get_analysis(self) -> dict:
        if len(self._returns) < 10:
            return {
                "var_95_historical": 0.0, "var_95_parametric": 0.0,
                "var_99_historical": 0.0, "cvar_95": 0.0,
            }

        rets = np.array(self._returns)
        mean = float(np.mean(rets))
        std = float(np.std(rets, ddof=1))

        # 历史模拟法
        var_95_hist = float(np.percentile(rets, 5))
        var_99_hist = float(np.percentile(rets, 1))

        # 参数法 (正态分布)
        from scipy import stats as sp_stats  # ponytail: scipy needed only here
        try:
            z_95 = sp_stats.norm.ppf(0.05)
            z_99 = sp_stats.norm.ppf(0.01)
            var_95_param = float(mean + z_95 * std)
            var_99_param = float(mean + z_99 * std)
        except ImportError:
            var_95_param = var_95_hist
            var_99_param = var_99_hist

        # CVaR (历史模拟法) — 低于 VaR 的所有收益的均值
        below_var = rets[rets <= var_95_hist]
        cvar_95 = float(np.mean(below_var)) if len(below_var) > 0 else var_95_hist

        return {
            "var_95_historical": round(var_95_hist, 6),
            "var_95_parametric": round(var_95_param, 6),
            "var_99_historical": round(var_99_hist, 6),
            "cvar_95": round(cvar_95, 6),
        }


# ------------------------------------------------------------------
# InfoRatioAnalyzer — 信息比率
#
# 信息比率 = 超额收益 / 跟踪误差
# 衡量策略相对于基准的风险调整后超额收益
# ------------------------------------------------------------------

class InfoRatioAnalyzer(AnalyzerBase):
    """信息比率分析器。

    输出:
      - info_ratio: 信息比率（年化）
      - excess_return: 年化超额收益
      - tracking_error: 年化跟踪误差
      - alpha: CAPM Alpha（简化版）
    """

    name = "info_ratio"

    def __init__(self, strategy, periods_per_year: int = 252,
                 benchmark_returns: list[float] | None = None):
        super().__init__(strategy, periods_per_year=periods_per_year, benchmark_returns=benchmark_returns)
        self._returns: list[float] = []
        self._prev_value: float | None = None

    def next(self):
        val = self.strategy.getvalue()
        if self._prev_value is not None and self._prev_value > 0:
            ret = (val - self._prev_value) / self._prev_value
            self._returns.append(ret)
        self._prev_value = val

    def get_analysis(self) -> dict:
        periods = self.params.get("periods_per_year", 252)
        bm_returns = self.params.get("benchmark_returns")

        if not bm_returns or len(self._returns) < 2:
            return {
                "info_ratio": 0.0, "excess_return": 0.0,
                "tracking_error": 0.0, "alpha": 0.0,
            }

        n = min(len(self._returns), len(bm_returns))
        rets = np.array(self._returns[-n:])
        bm = np.array(bm_returns[-n:])

        excess = rets - bm
        avg_excess_daily = float(np.mean(excess))
        std_excess_daily = float(np.std(excess, ddof=1))

        excess_annual = float((1 + avg_excess_daily) ** periods - 1)
        te_annual = float(std_excess_daily * np.sqrt(periods))
        info_ratio = round(excess_annual / te_annual, 4) if te_annual > 0 else 0.0

        # 简化 Alpha: 超额收益 - Beta × 基准超额
        avg_bm_daily = float(np.mean(bm))
        cov = float(np.cov(rets, bm)[0, 1]) if len(rets) > 1 else 0.0
        bm_var = float(np.var(bm, ddof=1)) if len(bm) > 1 else 1.0
        beta = cov / bm_var if bm_var > 0 else 1.0
        alpha_daily = avg_excess_daily - beta * avg_bm_daily
        alpha_annual = float((1 + alpha_daily) ** periods - 1)

        return {
            "info_ratio": info_ratio,
            "excess_return_pct": round(excess_annual * 100, 2),
            "tracking_error_pct": round(te_annual * 100, 2),
            "alpha_pct": round(alpha_annual * 100, 2),
            "beta": round(beta, 4),
        }


# ------------------------------------------------------------------
# 独立工具函数 — 不依赖 Strategy，可直接用于任何权益曲线
# ------------------------------------------------------------------

def compute_advanced_metrics(
    equity_curve: "pd.Series",
    benchmark_returns: "pd.Series | None" = None,
    periods_per_year: int = 252,
    risk_free: float = 0.02,
) -> dict:
    """从权益曲线计算所有高级绩效指标。

    Args:
        equity_curve: 权益时间序列 (pd.Series, index=datetime)
        benchmark_returns: 基准日收益率序列 (可选, 用于信息比率)
        periods_per_year: 年化周期数 (股票=252, 加密货币=365)
        risk_free: 无风险利率 (默认 2%)

    Returns:
        dict 包含 calmar/sortino/var/info_ratio 全部指标
    """
    import numpy as np

    values = equity_curve.values
    if len(values) < 2:
        return {
            "calmar_ratio": 0.0, "sortino_ratio": 0.0,
            "var_95_historical": 0.0, "var_95_parametric": 0.0,
            "cvar_95": 0.0, "info_ratio": 0.0, "alpha": 0.0, "beta": 1.0,
        }

    # 日收益率
    returns = np.diff(values) / values[:-1]

    # --- Calmar ---
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (v / peak - 1) * 100
        max_dd = min(max_dd, dd)

    total_return = values[-1] / values[0]
    n_days = len(values)
    annualized = (total_return ** (periods_per_year / n_days) - 1) * 100
    calmar = round(annualized / abs(max_dd), 4) if max_dd < 0 else 0.0

    # --- Sortino ---
    avg_daily = float(np.mean(returns))
    annual_ret = float((1 + avg_daily) ** periods_per_year - 1)
    downside_rets = returns[returns < 0]
    if len(downside_rets) >= 2:
        daily_rf = (1 + risk_free) ** (1 / periods_per_year) - 1
        downside_var = float(np.mean((downside_rets - daily_rf) ** 2))
        downside_vol = float(np.sqrt(downside_var) * np.sqrt(periods_per_year))
        sortino = round((annual_ret - risk_free) / downside_vol, 4) if downside_vol > 0 else 0.0
    else:
        sortino = float("inf") if annual_ret > risk_free else 0.0
        downside_vol = 0.0

    # --- VaR / CVaR ---
    if len(returns) >= 10:
        var_95 = float(np.percentile(returns, 5))
        var_99 = float(np.percentile(returns, 1))
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))
        # 参数法
        try:
            from scipy import stats as sp_stats
            var_95_param = float(mean_ret + sp_stats.norm.ppf(0.05) * std_ret)
        except ImportError:
            var_95_param = var_95
        below_var = returns[returns <= var_95]
        cvar_95 = float(np.mean(below_var)) if len(below_var) > 0 else var_95
    else:
        var_95 = var_99 = var_95_param = cvar_95 = 0.0

    # --- Info Ratio / Alpha / Beta ---
    info_ratio = alpha = beta = 0.0
    excess_pct = te_pct = 0.0
    if benchmark_returns is not None and len(returns) >= 2:
        n = min(len(returns), len(benchmark_returns))
        rets = returns[-n:]
        bm = np.array(benchmark_returns[-n:])
        excess = rets - bm
        avg_excess_daily = float(np.mean(excess))
        std_excess_daily = float(np.std(excess, ddof=1))
        excess_annual = float((1 + avg_excess_daily) ** periods_per_year - 1)
        te_annual = float(std_excess_daily * np.sqrt(periods_per_year))
        info_ratio = round(excess_annual / te_annual, 4) if te_annual > 0 else 0.0
        excess_pct = round(excess_annual * 100, 2)
        te_pct = round(te_annual * 100, 2)

        # Alpha / Beta
        if len(rets) > 1 and len(bm) > 1:
            cov = float(np.cov(rets, bm)[0, 1])
            bm_var = float(np.var(bm, ddof=1))
            beta = round(cov / bm_var, 4) if bm_var > 0 else 1.0
            alpha_daily = avg_excess_daily - beta * float(np.mean(bm))
            alpha = round(float((1 + alpha_daily) ** periods_per_year - 1) * 100, 2)

    return {
        "calmar_ratio": calmar,
        "sortino_ratio": sortino,
        "downside_deviation_pct": round(downside_vol * 100, 2),
        "var_95_historical": round(var_95, 6),
        "var_95_parametric": round(var_95_param, 6),
        "var_99_historical": round(var_99, 6),
        "cvar_95": round(cvar_95, 6),
        "info_ratio": info_ratio,
        "excess_return_pct": excess_pct,
        "tracking_error_pct": te_pct,
        "alpha_pct": alpha,
        "beta": beta,
    }
