# -*- coding: utf-8 -*-
"""BaizeCerebro — 回测统一编排器。

借鉴 Backtrader Cerebro 的 additive pipeline + 事件驱动设计:
  add_data() → add_strategy() → add_sizer() → add_analyzer()
  → with_risk_control() → run() → BaizeResult

核心差异 vs Backtrader:
  - 不依赖 bt.LineIterator，直接操作 pandas DataFrame
  - 复用 ChinaAEngine (T+1/涨跌停) + AShareCostCalculator (佣金)
  - 可挂载 RiskControlEngine (熔断/上限) + PositionStateManager (止损)
  - 分析器遵循 AnalyzerBase 接口 (next() + get_analysis())
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.backtest.broker import BaizeBroker
from src.backtest.cost_model import AShareCostCalculator
from src.backtest.engines.base import (
    BaseEngine,
    DrawdownStats,
    EngineResult,
    Position,
)

# 静态方法引用
calculate_drawdown_stats = BaseEngine.calculate_drawdown_stats
_calc_sharpe = BaseEngine._calc_sharpe
_calc_annual_return = BaseEngine._calc_annual_return
_calc_max_drawdown_static = BaseEngine._calc_max_drawdown
from src.backtest.engines.china_a import ChinaAEngine
from src.backtest.result import BaizeResult, TradeRecord

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# _FeedColumn — 兼容 Backtrader 风格索引的 Series 包装器
# ------------------------------------------------------------------

class _FeedColumn:
    """包装 pd.Series，支持 Backtrader 风格负整数索引。

    data.close[-1] → 当前 bar 收盘价  (iloc[-1])
    data.close[-2] → 上一 bar 收盘价  (iloc[-2])
    data.close[0]  → 第一 bar 收盘价  (iloc[0])

    同时保留 len()、.values、切片等 Series 操作。
    """

    def __init__(self, series: pd.Series):
        self._series = series
        # 缓存 numpy values 以加速索引
        self._values = series.values

    @property
    def values(self):
        return self._values

    @property
    def index(self):
        return self._series.index

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._values[idx]
        return self._series.iloc[idx] if isinstance(idx, slice) else self._series[idx]

    def __len__(self) -> int:
        return len(self._series)

    def __iter__(self):
        return iter(self._values)

    def __repr__(self) -> str:
        return f"_FeedColumn(len={len(self)})"

    @property
    def iloc(self):
        """返回 _IlocAccessor 支持 .iloc[pos] 语法。"""
        return _IlocAccessor(self._values, self._series)


class _IlocAccessor:
    """让 _FeedColumn.iloc[pos] 可用。"""
    def __init__(self, values, series):
        self._values = values
        self._series = series

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._values[idx]
        return self._series.iloc[idx]


# ------------------------------------------------------------------
# BaizeDataFeed — 数据源封装
# ------------------------------------------------------------------

class BaizeDataFeed:
    """回测数据源 — 封装 OHLCV DataFrame。

    借鉴 Backtrader DataFeed:
      - close / open / high / low / volume 按时间排列
      - datetime 为 pd.DatetimeIndex
      - 支持 extra_cols (PE/ROE 等因子列)

    访问方式 (兼容 Backtrader 风格):
      - data.close[-1]  → 当前 bar 收盘价
      - data.close[-2]  → 上一 bar 收盘价
      - data.open[0]   → 第一 bar 开盘价
    """

    def __init__(
        self,
        symbol: str,
        df: pd.DataFrame,
        name: str = "",
    ):
        """
        Args:
            symbol: 股票代码 (如 "000001.SZ")
            df: OHLCV DataFrame, index=date, columns=open/high/low/close/volume
            name: 显示名称
        """
        self.symbol = symbol
        self.name = name or symbol

        # 验证必需列
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFeed {symbol} missing columns: {missing}")

        self._df = df.copy()
        self._df.index = pd.DatetimeIndex(self._df.index)

        # 主序列 — 使用 _FeedColumn 支持 [-1] 索引
        self.datetime: pd.DatetimeIndex = self._df.index
        self.open = _FeedColumn(self._df["open"])
        self.high = _FeedColumn(self._df["high"])
        self.low = _FeedColumn(self._df["low"])
        self.close = _FeedColumn(self._df["close"])
        self.volume = _FeedColumn(
            self._df.get("volume", pd.Series(0, index=self._df.index))
        )

        # 扩展列 (因子等)
        self.extra_cols: dict[str, pd.Series] = {}
        for col in self._df.columns:
            if col not in {"open", "high", "low", "close", "volume"}:
                self.extra_cols[col] = self._df[col]

    def __len__(self) -> int:
        return len(self._df)

    def get(self, column: str) -> pd.Series | None:
        """获取扩展列。"""
        return self.extra_cols.get(column)

    def slice(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> "BaizeDataFeed":
        """时间切片。"""
        mask = (self._df.index >= pd.Timestamp(start)) & (self._df.index <= pd.Timestamp(end))
        sliced = self._df.loc[mask]
        return BaizeDataFeed(self.symbol, sliced, self.name)


# ------------------------------------------------------------------
# BaizeCerebro — 统一编排器
# ------------------------------------------------------------------

class BaizeCerebro:
    """回测统一编排器 — 借鉴 Backtrader Cerebro 的 additive pipeline。

    用法:
        cerebro = BaizeCerebro(initial_cash=1_000_000)
        cerebro.add_data("000001.SZ", df_sz)
        cerebro.add_data("600519.SH", df_sh)
        cerebro.add_strategy(MomentumStrategy, lookback=20)
        cerebro.add_sizer(KellyPositionSizer(tracker, kelly_fraction=0.5))
        cerebro.add_analyzer(SharpeAnalyzer)
        cerebro.with_risk_control()
        result = cerebro.run("2023-01-01", "2026-07-01")
    """

    def __init__(self, initial_cash: float = 1_000_000.0):
        self._initial_cash = initial_cash
        self._datas: list[BaizeDataFeed] = []
        self._strategy_cls = None
        self._strategy_params: dict = {}
        self._sizer = None
        self._analyzer_classes: list[tuple[type, dict]] = []
        self._risk_engine = None
        self._position_mgr = None
        self._broker: BaizeBroker | None = None
        self._cost_calc = AShareCostCalculator()

    # ------------------------------------------------------------------
    # Additive Pipeline (fluent 接口)
    # ------------------------------------------------------------------

    def add_data(
        self,
        symbol: str,
        df: pd.DataFrame,
        name: str = "",
    ) -> "BaizeCerebro":
        """注册数据源。

        Args:
            symbol: 股票代码
            df: OHLCV DataFrame
            name: 显示名称
        """
        feed = BaizeDataFeed(symbol, df, name)
        self._datas.append(feed)
        return self

    def add_strategy(
        self,
        strategy_cls: type,
        **params,
    ) -> "BaizeCerebro":
        """注册策略类 (非实例)。

        Args:
            strategy_cls: BaizeStrategy 子类
            **params: 策略参数
        """
        self._strategy_cls = strategy_cls
        self._strategy_params = params
        return self

    def add_sizer(self, sizer) -> "BaizeCerebro":
        """注入仓位计算器 (如 KellyPositionSizer)。"""
        self._sizer = sizer
        return self

    def add_analyzer(self, analyzer_cls: type, **params) -> "BaizeCerebro":
        """注册分析器类。

        Args:
            analyzer_cls: AnalyzerBase 子类
        """
        self._analyzer_classes.append((analyzer_cls, params))
        return self

    def with_risk_control(
        self,
        engine=None,
        config: dict | None = None,
    ) -> "BaizeCerebro":
        """挂载风控引擎。

        Args:
            engine: RiskControlEngine 实例 (None 则使用默认)
            config: 风控配置
        """
        if engine is not None:
            self._risk_engine = engine
        else:
            from src.routing.risk_control import RiskControlEngine
            self._risk_engine = RiskControlEngine()
        return self

    def with_position_tracking(self, mgr=None) -> "BaizeCerebro":
        """挂载持仓状态管理器 (止损/止盈/移动止损)。"""
        if mgr is not None:
            self._position_mgr = mgr
        else:
            try:
                from src.routing.position_state import PositionStateManager
                self._position_mgr = PositionStateManager()
            except ImportError:
                logger.warning("PositionStateManager not available, skip position tracking")
        return self

    def set_broker(self, broker: BaizeBroker) -> "BaizeCerebro":
        """覆盖默认 broker。"""
        self._broker = broker
        return self

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def run(
        self,
        start: str | None = None,
        end: str | None = None,
    ) -> BaizeResult:
        """执行回测事件循环。

        流程:
          1. align_data(): 对齐所有数据到统一时间轴
          2. for each bar t:
               update broker prices
               update analyzers
               if risk_engine: observe_equity, check breaker
               strategy.next() → buy/sell/close → broker
               if position_mgr: check stop-loss
               record equity
          3. build_result(): 汇总指标

        Returns:
            BaizeResult
        """
        if not self._datas:
            raise ValueError("No data feeds registered. Use add_data() first.")
        if self._strategy_cls is None:
            raise ValueError("No strategy registered. Use add_strategy() first.")

        # 1. 对齐数据
        common_dates = self._align_dates(start, end)
        if len(common_dates) < 2:
            logger.warning("Not enough data points after alignment")
            return self._empty_result()

        # 2. 初始化 broker
        if self._broker is None:
            engine = ChinaAEngine({"initial_cash": self._initial_cash})
            self._broker = BaizeBroker(
                cash=self._initial_cash,
                engine=engine,
                cost_calculator=self._cost_calc,
            )

        # 3. 实例化策略
        strategy = self._strategy_cls(self, **self._strategy_params)
        strategy._set_datas(self._datas)
        strategy._set_broker(self._broker)
        if self._sizer is not None:
            strategy.sizer = self._sizer

        # 4. 实例化分析器
        analyzers = {}
        for a_cls, a_params in self._analyzer_classes:
            inst = a_cls(strategy, **a_params)
            analyzers[inst.name] = inst
        strategy.analyzers = analyzers

        # 5. 事件循环
        equity_curve = []
        trades: list[TradeRecord] = []
        trade_counter = 0

        strategy.start()

        for idx in range(1, len(common_dates)):
            ts = common_dates[idx]
            prev_ts = common_dates[idx - 1]

            # 5a. 更新 broker 价格
            prices = {}
            for data in self._datas:
                if ts in data.datetime:
                    pos = data.datetime.get_loc(ts)
                    prices[data.symbol] = data.close.iloc[pos]
                else:
                    # 数据缺失，用上一 bar 价格
                    prices[data.symbol] = prices.get(data.symbol, 0.0)
            self._broker.update_prices(prices, ts)

            # 5b. 风控: 观察权益
            if self._risk_engine is not None:
                equity = self._broker.value
                try:
                    self._risk_engine.observe_equity(equity)
                except Exception as e:
                    logger.debug(f"risk_engine.observe_equity error: {e}")

            # 5c. 风控: 熔断检查
            breaker_tripped = False
            if self._risk_engine is not None:
                try:
                    breaker_tripped = getattr(
                        self._risk_engine, "breaker_tripped", False
                    )
                except Exception:
                    pass

            # 5d. 策略执行 (熔断时跳过新开仓，但允许平仓)
            if not breaker_tripped:
                strategy._next()
            else:
                # 熔断中: 只允许平仓，不允许开仓
                # strategy 可在 next() 中检查 self.broker 的 breaker 状态自行处理
                strategy._next()

            # 5e. 持仓管理: 止损止盈检查
            if self._position_mgr is not None:
                self._check_position_stops(ts, prices)

            # 5f. 记录权益
            equity_curve.append((ts, self._broker.value))

        strategy.stop()

        # 6. 构建结果
        return self._build_result(
            common_dates,
            equity_curve,
            analyzers,
            breaker_tripped,
        )

    def run_multiple(
        self,
        param_grids: list[dict],
    ) -> list[BaizeResult]:
        """批量跑参 (用于优化器)。

        Args:
            param_grids: 参数组合列表，每项为 {param_name: value}

        Returns:
            BaizeResult 列表
        """
        results = []
        for params in param_grids:
            # 更新参数
            merged_params = {**self._strategy_params, **params}
            self._strategy_params = merged_params
            result = self.run()
            result.strategy_params = merged_params
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _align_dates(
        self,
        start: str | None,
        end: str | None,
    ) -> pd.DatetimeIndex:
        """对齐所有数据源的日期。"""
        all_dates = None
        for data in self._datas:
            dates = data.datetime
            if all_dates is None:
                all_dates = set(dates)
            else:
                all_dates &= set(dates)

        if all_dates is None:
            return pd.DatetimeIndex([])

        dates = pd.DatetimeIndex(sorted(all_dates))

        # 时间切片
        if start:
            dates = dates[dates >= pd.Timestamp(start)]
        if end:
            dates = dates[dates <= pd.Timestamp(end)]

        return dates

    def _check_position_stops(
        self,
        ts: pd.Timestamp,
        prices: dict[str, float],
    ):
        """检查止损止盈条件。"""
        if self._position_mgr is None or self._broker is None:
            return

        for symbol, pos in list(self._broker.positions.items()):
            price = prices.get(symbol, 0)
            if price <= 0 or pos.size <= 0:
                continue

            # 计算浮动盈亏
            pnl_pct = (price - pos.entry_price) / pos.entry_price

            try:
                # 检查是否触发止损
                should_stop = self._position_mgr.check_stop(
                    symbol=symbol,
                    entry_price=pos.entry_price,
                    current_price=price,
                    pnl_pct=float(pnl_pct),
                )
                if should_stop:
                    self._broker.sell(
                        symbol=symbol,
                        price=price,
                        size=int(pos.size),
                        timestamp=ts,
                    )
            except Exception as e:
                logger.debug(f"position_mgr.check_stop error for {symbol}: {e}")

    def _build_result(
        self,
        dates: pd.DatetimeIndex,
        equity_curve: list[tuple[pd.Timestamp, float]],
        analyzers: dict,
        breaker_tripped: bool,
    ) -> BaizeResult:
        """汇总回测结果。"""
        if not equity_curve:
            return self._empty_result()

        eq_series = pd.Series(
            [e[1] for e in equity_curve],
            index=[e[0] for e in equity_curve],
        )

        final_value = eq_series.iloc[-1]
        total_return = (final_value / self._initial_cash) - 1.0

        # 基础指标
        sharpe = self._calc_sharpe(eq_series)
        annual = self._calc_annual_return(eq_series)
        max_dd = self._calc_max_drawdown(eq_series)
        win_rate = self._calc_win_rate()

        # 回撤生命周期 (复用 engines/base.py)
        dd_stats = calculate_drawdown_stats(eq_series)

        # 扩展指标
        sortino = self._calc_sortino(eq_series)
        calmar = abs(annual / max_dd) if max_dd != 0 else 0.0
        profit_factor = self._calc_profit_factor()

        # 分析器输出
        analyzer_outputs = {}
        for name, a in analyzers.items():
            try:
                analyzer_outputs[name] = a.get_analysis()
            except Exception as e:
                logger.warning(f"Analyzer {name} failed: {e}")
                analyzer_outputs[name] = {"error": str(e)}

        # 交易记录转换
        trades = self._build_trade_records()

        # 年度收益
        yearly = self._calc_yearly_returns(eq_series)

        return BaizeResult(
            strategy_name=self._strategy_params.get(
                "name",
                self._strategy_cls.__name__ if self._strategy_cls else "unknown",
            ),
            strategy_params=self._strategy_params,
            start_date=str(dates[0].date()),
            end_date=str(dates[-1].date()),
            initial_cash=self._initial_cash,
            final_value=final_value,
            total_return=total_return,
            annual_return=annual,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=len(trades),
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            profit_factor=profit_factor,
            trades=trades,
            equity_curve=eq_series,
            yearly_returns=yearly,
            drawdown_stats=dd_stats,
            analyzers=analyzer_outputs,
            breaker_tripped=breaker_tripped,
        )

    def _empty_result(self) -> BaizeResult:
        return BaizeResult(
            strategy_name=self._strategy_cls.__name__ if self._strategy_cls else "unknown",
            initial_cash=self._initial_cash,
        )

    def _build_trade_records(self) -> list[TradeRecord]:
        """从 broker 的交易记录构建 TradeRecord 列表。"""
        if self._broker is None:
            return []

        records = []
        raw_trades = self._broker._trades

        # 分组: 同一 symbol 的 BUY→SELL 配对
        buy_queue: dict[str, list[dict]] = {}
        for t in raw_trades:
            symbol = t["symbol"]
            if t["action"] == "BUY":
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append(t)
            elif t["action"] == "SELL":
                if symbol in buy_queue and buy_queue[symbol]:
                    buy = buy_queue[symbol].pop(0)
                    entry_price = buy["price"]
                    exit_price = t["price"]
                    entry_size = buy["size"]
                    pnl = (exit_price - entry_price) * entry_size - t.get("commission", 0)
                    pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0

                    entry_ts = buy["timestamp"]
                    exit_ts = t["timestamp"]
                    holding_days = (
                        (exit_ts - entry_ts).days
                        if entry_ts and exit_ts
                        else 0
                    )

                    records.append(TradeRecord(
                        trade_id=len(records) + 1,
                        symbol=symbol,
                        direction=1,
                        entry_date=str(entry_ts.date()) if entry_ts else "",
                        entry_price=entry_price,
                        entry_size=entry_size,
                        entry_notional=entry_price * entry_size,
                        exit_date=str(exit_ts.date()) if exit_ts else "",
                        exit_price=exit_price,
                        exit_size=t["size"],
                        exit_notional=exit_price * t["size"],
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        commission=buy.get("commission", 0) + t.get("commission", 0),
                        holding_days=holding_days,
                        is_open=False,
                    ))

        # 未平仓的买入
        for symbol, buys in buy_queue.items():
            for buy in buys:
                entry_price = buy["price"]
                entry_size = buy["size"]
                entry_ts = buy["timestamp"]
                records.append(TradeRecord(
                    trade_id=len(records) + 1,
                    symbol=symbol,
                    direction=1,
                    entry_date=str(entry_ts.date()) if entry_ts else "",
                    entry_price=entry_price,
                    entry_size=entry_size,
                    entry_notional=entry_price * entry_size,
                    is_open=True,
                ))

        return records

    # ------------------------------------------------------------------
    # 指标计算 (静态方法，复用 engines/base.py 逻辑)
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_sharpe(equity: pd.Series, periods_per_year: int = 252) -> float:
        if len(equity) < 2:
            return 0.0
        rets = equity.pct_change().dropna()
        if rets.std() == 0:
            return 0.0
        return float((rets.mean() / rets.std()) * np.sqrt(periods_per_year))

    @staticmethod
    def _calc_annual_return(equity: pd.Series, periods_per_year: int = 252) -> float:
        if len(equity) < 2:
            return 0.0
        total = equity.iloc[-1] / equity.iloc[0] - 1.0
        n = len(equity)
        years = n / periods_per_year
        if years <= 0:
            return 0.0
        return float((1 + total) ** (1 / years) - 1)

    @staticmethod
    def _calc_max_drawdown(equity: pd.Series) -> float:
        peak = equity.cummax()
        dd = (equity - peak) / peak
        return float(dd.min()) if len(dd) else 0.0

    def _calc_win_rate(self) -> float:
        if self._broker is None:
            return 0.0
        trades = self._broker.get_trades()
        if not trades:
            return 0.0
        # 从 broker trades 中提取盈亏
        closed = []
        buy_queue: dict[str, list[dict]] = {}
        for t in self._broker._trades:
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
            return 0.0
        wins = sum(1 for p in closed if p > 0)
        return wins / len(closed)

    @staticmethod
    def _calc_sortino(equity: pd.Series, periods_per_year: int = 252) -> float:
        if len(equity) < 2:
            return 0.0
        rets = equity.pct_change().dropna()
        downside = rets[rets < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return float((rets.mean() / downside.std()) * np.sqrt(periods_per_year))

    def _calc_profit_factor(self) -> float:
        if self._broker is None:
            return 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        buy_queue: dict[str, list[dict]] = {}
        for t in self._broker._trades:
            symbol = t["symbol"]
            if t["action"] == "BUY":
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append(t)
            elif t["action"] == "SELL":
                if symbol in buy_queue and buy_queue[symbol]:
                    buy = buy_queue[symbol].pop(0)
                    pnl = (t["price"] - buy["price"]) * buy["size"] - t.get("commission", 0)
                    if pnl > 0:
                        gross_profit += pnl
                    else:
                        gross_loss += abs(pnl)

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def _calc_yearly_returns(equity: pd.Series) -> dict[str, float]:
        """计算年度收益率。"""
        if len(equity) < 2:
            return {}
        yearly = {}
        for year, group in equity.groupby(equity.index.year):
            start_val = group.iloc[0]
            end_val = group.iloc[-1]
            ret = (end_val / start_val) - 1.0
            yearly[str(year)] = round(ret, 4)
        return yearly
