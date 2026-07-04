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
        pe_percentile: float = 50,
        roe: float = 0,
        northbound: float = 0,
    ):
        """添加股票数据。

        df 需包含: open, high, low, close, volume
        额外列通过 kwargs 注入为 data 属性。
        """
        feed = bt.feeds.PandasData(
            dataname=df,
            name=code,
        )
        # 注入因子数据
        feed.pe_percentile = pe_percentile
        feed.roe = roe
        feed.northbound = northbound
        self._data_feeds.append(feed)

    def load_data(
        self,
        symbols: list[str],
        start: str = "2015-01-01",
        end: str = "2024-12-31",
    ):
        """自动加载历史K线数据并计算代理因子。

        通过 AKShare 拉取数据并注入到回测引擎。
        日期格式自动转换 "YYYY-MM-DD" ↔ "YYYYMMDD"。

        因子计算:
          - pe_percentile: 价格在过去 252 日区间中的位置（越低越便宜）
          - roe: 过去 252 日涨跌幅
          - northbound: 简化处理，默认 1.0

        Args:
            symbols: 股票代码列表，如 ["600519", "000001"]
            start: 起始日期 "YYYY-MM-DD"
            end: 结束日期 "YYYY-MM-DD"
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
                if df is None or df.empty:
                    continue

                # 标准化列名
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                    "成交额": "amount", "涨跌幅": "pct_change",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")

                # 计算代理因子
                close = df["close"]
                roll_max = close.rolling(252).max()
                roll_min = close.rolling(252).min()
                pe_proxy = ((close - roll_min) / (roll_max - roll_min + 0.01)).fillna(50)
                pe_proxy = (1 - pe_proxy) * 100
                pe_pct = float(pe_proxy.median())

                roe_val = float(((close / close.shift(252) - 1) * 100).median())

                self.add_data(
                    code=code, df=df,
                    pe_percentile=pe_pct if pe_pct > 0 else 50,
                    roe=roe_val if abs(roe_val) < 200 else 10,
                    northbound=1.0,
                )
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

        # 提取最大回撤（Backtrader 返回小数形式，如 -0.15 = -15%）
        dd_info = drawdown.get("max", {}) if isinstance(drawdown, dict) else {}
        max_dd = dd_info.get("drawdown", 0) if dd_info else 0
        if isinstance(max_dd, (int, float)):
            max_dd = max_dd * 100 if abs(max_dd) < 10 else max_dd  # 小数→百分比

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
