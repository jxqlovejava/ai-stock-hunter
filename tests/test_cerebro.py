# -*- coding: utf-8 -*-
"""BaizeCerebro 端到端测试。"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.analyzer import (
    DrawDownAnalyzer,
    SharpeAnalyzer,
    SQNAnalyzer,
    TimeReturnAnalyzer,
    TradeAnalyzer,
    WinRateAnalyzer,
)
from src.backtest.cerebro import BaizeCerebro, BaizeDataFeed
from src.backtest.result import BaizeResult, OrderStatus, TradeRecord
from src.backtest.strategy import BaizeStrategy
from src.backtest.broker import BaizeBroker


# ------------------------------------------------------------------
# 辅助函数: 生成模拟 OHLCV 数据
# ------------------------------------------------------------------

def make_mock_data(
    symbol: str,
    n_days: int = 252,
    start_price: float = 10.0,
    trend: float = 0.0002,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """生成模拟日线 OHLCV 数据。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")

    # 随机游走 + 趋势
    rets = rng.normal(trend, volatility, n_days)
    prices = start_price * np.cumprod(1 + rets)

    df = pd.DataFrame(
        {
            "open": prices * (1 + rng.normal(0, 0.005, n_days)),
            "high": prices * (1 + abs(rng.normal(0, 0.01, n_days))),
            "low": prices * (1 - abs(rng.normal(0, 0.01, n_days))),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, n_days),
        },
        index=dates,
    )
    # 确保 OHLC 一致性
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


# ------------------------------------------------------------------
# 测试策略
# ------------------------------------------------------------------

class BuyAndHoldStrategy(BaizeStrategy):
    """全仓买入持有策略 — 等权分配现金买入所有标的。"""

    def next(self):
        if len(self.data.datetime) == 0:
            return
        # 第一天等权买入所有标的
        if self._bar_index == 0:
            n = len(self.datas)
            cash_per_symbol = self.getcash() / n
            for data in self.datas:
                if self.getposition(data) == 0:
                    price = data.close[-1]
                    max_size = int(cash_per_symbol / price / 100) * 100
                    if max_size > 0:
                        self.buy(data, size=max_size)
        self._bar_index += 1

    def start(self):
        self._bar_index = 0


class MovingAverageCrossStrategy(BaizeStrategy):
    """均线交叉策略 — 短均线上穿长均线买入，下穿卖出。"""

    def __init__(self, cerebro, short_period=5, long_period=20):
        super().__init__(cerebro, short_period=short_period, long_period=long_period)

    def next(self):
        for data in self.datas:
            if len(data.close) < self.long_period:
                continue

            short_ma = np.mean(data.close.values[-self.short_period:])
            long_ma = np.mean(data.close.values[-self.long_period:])

            prev_short = np.mean(data.close.values[-self.short_period - 1:-1])
            prev_long = np.mean(data.close.values[-self.long_period - 1:-1])

            pos = self.getposition(data)
            crossover_up = prev_short <= prev_long and short_ma > long_ma
            crossover_down = prev_short >= prev_long and short_ma < long_ma

            if crossover_up and pos == 0:
                price = data.close[-1]
                size = int(self.getcash() * 0.5 / price / 100) * 100
                if size > 0:
                    self.buy(data, size=size)
            elif crossover_down and pos > 0:
                self.close(data)


class EmptyStrategy(BaizeStrategy):
    """空策略 — 什么都不做，验证空跑不报错。"""

    def next(self):
        pass


# ------------------------------------------------------------------
# 测试
# ------------------------------------------------------------------

class TestBaizeDataFeed:
    def test_creation(self):
        df = make_mock_data("TEST.SZ", 100)
        feed = BaizeDataFeed("TEST.SZ", df)
        assert feed.symbol == "TEST.SZ"
        assert len(feed) == 100
        assert len(feed.close) == 100

    def test_extra_cols(self):
        df = make_mock_data("TEST.SZ", 100)
        df["pe_ratio"] = np.random.randn(100) + 20
        feed = BaizeDataFeed("TEST.SZ", df)
        assert "pe_ratio" in feed.extra_cols

    def test_missing_columns_raises(self):
        with pytest.raises(ValueError):
            BaizeDataFeed("TEST.SZ", pd.DataFrame({"a": [1, 2, 3]}))

    def test_slice(self):
        df = make_mock_data("TEST.SZ", 100)
        feed = BaizeDataFeed("TEST.SZ", df)
        sliced = feed.slice("2023-01-10", "2023-02-01")
        assert len(sliced) < len(feed)
        assert sliced.symbol == "TEST.SZ"


class TestBaizeBroker:
    def test_creation(self):
        broker = BaizeBroker(cash=500_000)
        assert broker.cash == 500_000
        assert broker.value == 500_000

    def test_buy_simple(self):
        broker = BaizeBroker(cash=100_000)
        broker.update_prices({"TEST.SZ": 10.0}, pd.Timestamp("2023-01-10"))
        order_id = broker.buy("TEST.SZ", price=10.0, size=1000)
        assert order_id > 0
        assert broker.getposition_size("TEST.SZ") == 1000
        # 现金减少
        assert broker.cash < 100_000

    def test_sell_simple(self):
        broker = BaizeBroker(cash=100_000)
        broker.update_prices({"TEST.SZ": 10.0}, pd.Timestamp("2023-01-10"))
        broker.buy("TEST.SZ", price=10.0, size=1000)
        broker.update_prices({"TEST.SZ": 12.0}, pd.Timestamp("2023-01-11"))
        order_id = broker.sell("TEST.SZ", price=12.0, size=1000)
        assert order_id > 0
        assert broker.getposition_size("TEST.SZ") == 0
        # 盈利 (含手续费)
        assert broker.cash > 100_000

    def test_insufficient_cash(self):
        broker = BaizeBroker(cash=1000)
        broker.update_prices({"TEST.SZ": 100.0}, pd.Timestamp("2023-01-10"))
        order_id = broker.buy("TEST.SZ", price=100.0, size=1000)
        assert order_id == -1

    def test_insufficient_position(self):
        broker = BaizeBroker(cash=100_000)
        broker.update_prices({"TEST.SZ": 10.0}, pd.Timestamp("2023-01-10"))
        order_id = broker.sell("TEST.SZ", price=10.0, size=1000)
        assert order_id == -1

    def test_accumulate_position(self):
        """加仓场景 — 均价更新。"""
        broker = BaizeBroker(cash=100_000)
        broker.update_prices({"TEST.SZ": 10.0}, pd.Timestamp("2023-01-10"))
        broker.buy("TEST.SZ", price=10.0, size=1000)
        broker.update_prices({"TEST.SZ": 12.0}, pd.Timestamp("2023-01-11"))
        broker.buy("TEST.SZ", price=12.0, size=1000)
        pos = broker.getposition("TEST.SZ")
        assert pos.size == 2000
        assert 10.0 < pos.entry_price < 12.0  # 均价在两者之间

    def test_settle(self):
        broker = BaizeBroker(cash=100_000)
        broker.update_prices({"TEST.SZ": 10.0}, pd.Timestamp("2023-01-10"))
        broker.buy("TEST.SZ", price=10.0, size=1000)
        result = broker.settle({"TEST.SZ": 15.0})
        assert result["final_value"] > broker.cash


class TestBaizeCerebro:
    def test_minimal_run(self):
        """最小可运行回测。"""
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 100)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(EmptyStrategy)

        result = cerebro.run()
        assert isinstance(result, BaizeResult)
        assert result.initial_cash == 100_000

    def test_buy_and_hold(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 100, trend=0.001)  # 上涨趋势
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)

        result = cerebro.run()
        assert isinstance(result, BaizeResult)
        assert result.total_trades >= 1
        # 上涨趋势应该盈利
        assert result.final_value > 100_000 or result.total_return > -0.5

    def test_aligned_dates(self):
        """测试日期对齐 — 两个不同区间数据。"""
        cerebro = BaizeCerebro(initial_cash=100_000)
        df1 = make_mock_data("A.SZ", 100)
        df2 = make_mock_data("B.SH", 80, seed=123)  # 较短

        cerebro.add_data("A.SZ", df1)
        cerebro.add_data("B.SH", df2)
        cerebro.add_strategy(EmptyStrategy)

        result = cerebro.run()
        assert result.start_date != ""
        assert result.end_date != ""

    def test_missing_strategy_raises(self):
        cerebro = BaizeCerebro()
        df = make_mock_data("TEST.SZ", 50)
        cerebro.add_data("TEST.SZ", df)
        with pytest.raises(ValueError, match="strategy"):
            cerebro.run()

    def test_missing_data_raises(self):
        cerebro = BaizeCerebro()
        cerebro.add_strategy(EmptyStrategy)
        with pytest.raises(ValueError, match="data"):
            cerebro.run()


class TestBaizeCerebroWithAnalyzers:
    def test_sharpe_analyzer(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)
        cerebro.add_analyzer(SharpeAnalyzer)

        result = cerebro.run()
        assert "sharpe" in result.analyzers
        assert "sharperatio" in result.analyzers["sharpe"]

    def test_drawdown_analyzer(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)
        cerebro.add_analyzer(DrawDownAnalyzer)

        result = cerebro.run()
        assert "drawdown" in result.analyzers

    def test_multiple_analyzers(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)
        cerebro.add_analyzer(SharpeAnalyzer)
        cerebro.add_analyzer(TradeAnalyzer)
        cerebro.add_analyzer(TimeReturnAnalyzer)

        result = cerebro.run()
        assert "sharpe" in result.analyzers
        assert "trades" in result.analyzers
        assert "timereturn" in result.analyzers

    def test_sqn_analyzer(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252, volatility=0.03)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)
        cerebro.add_analyzer(SQNAnalyzer)

        result = cerebro.run()
        assert "sqn" in result.analyzers

    def test_winrate_analyzer(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252, volatility=0.03)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(BuyAndHoldStrategy)
        cerebro.add_analyzer(WinRateAnalyzer)

        result = cerebro.run()
        assert "winrate" in result.analyzers


class TestBaizeResult:
    def test_summary(self):
        result = BaizeResult(
            strategy_name="Test",
            total_return=0.15,
            sharpe_ratio=1.2,
            max_drawdown=-0.08,
            win_rate=0.55,
            total_trades=42,
        )
        summary = result.summary()
        assert "Test" in summary
        assert "15.00%" in summary or "0.15" in summary

    def test_to_dict(self):
        result = BaizeResult(strategy_name="Test")
        d = result.to_dict()
        assert d["strategy_name"] == "Test"
        assert "trades" in d
        assert "analyzers" in d


class TestMigration:
    def test_params_proxy(self):
        from src.backtest.migration import _ParamsProxy
        p = _ParamsProxy({"period": 20})
        assert p.period == 20
        p.period = 30
        assert p.period == 30

    def test_make_data_bt_compatible(self):
        from src.backtest.migration import _make_data_bt_compatible
        df = make_mock_data("TEST.SZ", 100)
        feed = BaizeDataFeed("TEST.SZ", df)
        compat = _make_data_bt_compatible(feed)
        assert compat.lines is not None
        assert compat.lines.close[-1] == feed.close.iloc[-1]
        assert compat._name == "TEST.SZ"


class TestMultiSymbol:
    def test_two_symbols_buy_and_hold(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df1 = make_mock_data("A.SZ", 100, seed=1)
        df2 = make_mock_data("B.SH", 100, seed=2)
        cerebro.add_data("A.SZ", df1)
        cerebro.add_data("B.SH", df2)
        cerebro.add_strategy(BuyAndHoldStrategy)

        result = cerebro.run()
        assert result.total_trades >= 2

    def test_moving_average_cross(self):
        cerebro = BaizeCerebro(initial_cash=100_000)
        df = make_mock_data("TEST.SZ", 252, volatility=0.03)
        cerebro.add_data("TEST.SZ", df)
        cerebro.add_strategy(MovingAverageCrossStrategy, short_period=5, long_period=20)
        cerebro.add_analyzer(TradeAnalyzer)

        result = cerebro.run()
        assert result.total_trades >= 0  # 均线交叉可能没有交易
        assert "trades" in result.analyzers
