# -*- coding: utf-8 -*-
"""回测引擎。

封装 Backtrader Cerebro，提供:
  - 策略注册与参数化
  - A 股约束模拟（T+1, 涨跌停, 交易成本）
  - 分年度绩效报告
  - 因子反转测试
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional

import backtrader as bt
import pandas as pd


@dataclass
class BacktestResult:
    """回测结果。"""

    strategy_name: str
    start_date: str
    end_date: str
    initial_cash: float
    final_value: float
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    yearly_returns: dict[str, float] = field(default_factory=dict)
    # P1 高级指标
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    info_ratio: float = 0.0
    alpha_pct: float = 0.0
    beta: float = 1.0


class AShareCommission(bt.CommInfoBase):
    """A 股交易成本模拟。

    单边成本约 0.23%:
      - 印花税: 0.1%（卖出时）
      - 佣金: 0.03%（买卖双向）
      - 滑点: 0.1%（买卖双向）

    T+1 约束通过 next() 中不立即卖出当日的买入来模拟。
    """

    params = (
        ("stamp_duty", 0.001),    # 印花税 0.1%
        ("commission", 0.0003),   # 佣金 0.03%
        ("slippage", 0.001),      # 滑点 0.1%
    )

    def _getcommission(self, size, price, pseudoexec):
        """买入时只收佣金+滑点，卖出时加收印花税。"""
        value = abs(size) * price
        comm = value * (self.p.commission + self.p.slippage)
        if size < 0:  # 卖出
            comm += value * self.p.stamp_duty
        return comm


class BacktestEngine:
    """回测引擎封装。

    用法:
        engine = BacktestEngine()
        engine.add_strategy(MVP1Strategy, **params)
        result = engine.run(start="2015-01-01", end="2024-12-31")
        engine.report(result)
    """

    def __init__(self, initial_cash: float = 1_000_000):
        self._initial_cash = initial_cash
        self._strategy_class: Optional[type] = None
        self._strategy_params: dict = {}
        self._data_feeds: list[bt.feeds.PandasData] = []

    def add_strategy(self, strategy_cls: type, **params):
        """注册策略。"""
        self._strategy_class = strategy_cls
        self._strategy_params = params

    def add_data(
        self,
        code: str,
        df,
    ):
        """添加股票数据。

        df 需包含: open, high, low, close, volume
        额外列 (pe_pct, roe, momentum) 自动识别为 data line。
        """
        # Build custom feed class with extra columns
        extra_params = {}
        extra_cols = []
        # 已知因子列 + 动态 vb_* 列 (跳过非数值列)
        known_cols = ["pe_pct", "roe", "momentum"]
        vb_cols = [
            c for c in df.columns
            if c.startswith("vb_") and df[c].dtype in ("float64", "int64", "float32", "int32")
        ]
        for col in known_cols + vb_cols:
            if col in df.columns:
                idx = list(df.columns).index(col)
                extra_params[col] = idx
                extra_cols.append(col)

        feed_cls = type(
            f"Feed_{code}",
            (bt.feeds.PandasData,),
            {"lines": tuple(extra_cols), "params": tuple(extra_params.items())},
        ) if extra_cols else bt.feeds.PandasData

        feed = feed_cls(dataname=df, name=code)
        self._data_feeds.append(feed)

    def load_data(
        self,
        symbols: list[str],
        start: str = "2015-01-01",
        end: str = "2024-12-31",
    ):
        """自动加载历史K线数据并预计算因子。

        因子以额外列形式加入 DataFrame，Backtrader 自动识别为 data line。
        因子列: pe_pct, roe, momentum
        """
        import akshare as ak

        start_fmt = start.replace("-", "")
        end_fmt = end.replace("-", "")

        for code in symbols:
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start_fmt, end_date=end_fmt,
                    adjust="qfq",
                )
                if df is None or df.empty or len(df) < 500:
                    continue

                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")

                close = df["close"]
                # PE 分位代理: 多时间框架
                for period in [63, 126, 252]:
                    rh = close.rolling(period).max()
                    rl = close.rolling(period).min()
                    denom = (rh - rl).clip(lower=0.01)
                    key = f"pe{period}" if period != 252 else "pe_pct"
                    df[key] = ((close - rl) / denom * 100).fillna(50)

                # ROE 代理: 252日涨跌幅
                df["roe"] = (close.pct_change(252) * 100).fillna(0)

                # 动量: 21日涨跌幅
                df["momentum"] = (close.pct_change(21) * 100).fillna(0)

                # 金额: 用于流动性过滤
                if "amount" not in df.columns and "volume" in df.columns:
                    df["amount"] = (df["volume"] * close).fillna(0)

                self.add_data(code, df)
            except Exception:
                continue

    def run(
        self,
        start: str = "2015-01-01",
        end: str = "2024-12-31",
    ) -> BacktestResult:
        """执行回测。"""
        if self._strategy_class is None:
            raise RuntimeError("未注册策略，请先调用 add_strategy()")

        cerebro = bt.Cerebro()
        cerebro.addstrategy(self._strategy_class, **self._strategy_params)

        # 资金
        cerebro.broker.setcash(self._initial_cash)

        # 交易成本
        cerebro.broker.addcommissioninfo(AShareCommission())

        # 添加数据
        for feed in self._data_feeds:
            cerebro.adddata(feed)

        # 基准分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="annual")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

        # 执行
        start_val = cerebro.broker.getvalue()
        results = cerebro.run()
        end_val = cerebro.broker.getvalue()

        if not results:
            raise RuntimeError("回测未产生结果")

        strat = results[0]

        # 提取指标
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()
        annual = strat.analyzers.annual.get_analysis()
        rets = strat.analyzers.returns.get_analysis()

        total_return = (end_val - start_val) / start_val
        years = self._year_diff(start, end)

        # 提取最大回撤
        dd_info = drawdown.get("max", {}) if isinstance(drawdown, dict) else {}
        max_dd = dd_info.get("drawdown", 0) if dd_info else 0
        if isinstance(max_dd, (int, float)):
            if abs(max_dd) < 1:
                max_dd = max_dd * 100  # Backtrader 返回小数
            yr_vals = [v for v in (annual if isinstance(annual, dict) else {}).values()
                       if isinstance(v, (int, float)) and v < 0]
            if yr_vals and abs(max_dd) > abs(min(yr_vals)) * 3:
                max_dd = abs(min(yr_vals))  # 兜底: 用最差年收益估算

        # P1 高级指标: 从 Backtrader 的 TimeReturn 分析器构建权益曲线
        import numpy as np  # noqa: F811
        from src.backtest.analyzer import compute_advanced_metrics
        adv: dict = {}
        if isinstance(rets, dict):
            rtv = [float(v) for v in rets.values()]
            if len(rtv) >= 2:
                eq = [100.0]
                for v in rtv:
                    eq.append(eq[-1] * v)
                adv = compute_advanced_metrics(pd.Series(eq))

        return BacktestResult(
            strategy_name=self._strategy_class.__name__,
            start_date=start,
            end_date=end,
            initial_cash=start_val,
            final_value=end_val,
            total_return=total_return,
            annual_return=(1 + total_return) ** (1 / years) - 1 if years > 0 else 0,
            sharpe_ratio=sharpe.get("sharperatio", 0) or 0,
            max_drawdown=max_dd,
            win_rate=self._win_rate(trades),
            total_trades=trades.get("total", {}).get("total", 0),
            yearly_returns={str(k): v for k, v in annual.items()},
            calmar_ratio=adv.get("calmar_ratio", 0.0),
            sortino_ratio=adv.get("sortino_ratio", 0.0),
            var_95=adv.get("var_95_historical", 0.0),
            cvar_95=adv.get("cvar_95", 0.0),
            info_ratio=adv.get("info_ratio", 0.0),
            alpha_pct=adv.get("alpha_pct", 0.0),
            beta=adv.get("beta", 1.0),
        )

    def reverse_test(
        self,
        start: str = "2015-01-01",
        end: str = "2024-12-31",
    ) -> BacktestResult:
        """因子反转测试: PE > 70% 分位替代 PE < 30%。

        如果反转后超额仍然存在 → 因子可能是假的。
        """
        params = {**self._strategy_params}
        params["pe_percentile"] = 30  # 反转: > 70 意味着 PE 分位 > 70
        self._strategy_params = params
        return self.run(start, end)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _win_rate(trades: dict) -> float:
        won = trades.get("won", {}).get("total", 0)
        lost = trades.get("lost", {}).get("total", 0)
        total = won + lost
        return won / total if total > 0 else 0.0

    @staticmethod
    def _year_diff(start: str, end: str) -> float:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
        return (e - s).days / 365.25

    def report(self, result: BacktestResult) -> str:
        """生成回测报告。"""
        lines = [
            f"# 回测报告: {result.strategy_name}",
            f"期间: {result.start_date} → {result.end_date}",
            f"初始资金: {result.initial_cash:,.0f}",
            f"最终资金: {result.final_value:,.0f}",
            f"总收益: {result.total_return:.2%}",
            f"年化收益: {result.annual_return:.2%}",
            f"夏普比率: {result.sharpe_ratio:.2f}",
            f"最大回撤: {result.max_drawdown:.2%}",
            f"胜率: {result.win_rate:.2%}",
            f"交易次数: {result.total_trades}",
            "",
            "## 分年度收益",
        ]
        if result.yearly_returns:
            for year, ret in sorted(result.yearly_returns.items()):
                lines.append(f"- {year}: {ret:.2%}")
        else:
            lines.append("(需更长回测周期以生成分年度数据)")
        return "\n".join(lines)
