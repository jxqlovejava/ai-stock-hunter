# -*- coding: utf-8 -*-
"""回测引擎抽象基类。

借鉴 Vibe-Trading agent/backtest/engines/base.py，但适配 A 股长单逻辑。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.data.source_citation import SourceCitation


@dataclass
class Position:
    """持仓记录。"""

    symbol: str
    direction: int  # 1 long, -1 short
    size: float
    entry_price: float
    entry_time: pd.Timestamp
    entry_notional: float


@dataclass
class EngineResult:
    """回测结果。"""

    strategy_name: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_cash: float = 0.0
    final_value: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    yearly_returns: dict[str, float] = field(default_factory=dict)
    data_citation: Optional[SourceCitation] = None
    signal_citation: Optional[SourceCitation] = None
    trading_blocked: bool = False
    block_reason: str = ""
    trades: list[dict] = field(default_factory=list)


class BaseEngine(ABC):
    """市场规则引擎基类。子类实现具体市场规则。"""

    def __init__(self, config: dict):
        self.config = config
        self.initial_cash: float = config.get("initial_cash", 1_000_000.0)
        self.cash: float = self.initial_cash
        self.positions: dict[str, Position] = {}
        self.equity_curve: list[tuple[pd.Timestamp, float]] = []
        self.trades: list[dict] = []
        self._trade_count: int = 0

    @abstractmethod
    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """判断该 bar 是否可以执行方向为 direction 的交易。"""
        ...

    @abstractmethod
    def round_size(self, raw_size: float, price: float) -> float:
        """按市场规则 rounding 股数。"""
        ...

    @abstractmethod
    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool
    ) -> float:
        """计算交易成本。"""
        ...

    @abstractmethod
    def apply_slippage(self, price: float, direction: int) -> float:
        """应用滑点。"""
        ...

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """每 bar 钩子，子类可覆盖（如期货资金费）。"""
        pass

    def run_backtest(
        self,
        data_map: dict[str, pd.DataFrame],
        target_weights: pd.DataFrame,
    ) -> EngineResult:
        """运行 bar-by-bar 回测。

        Args:
            data_map: {symbol: DataFrame(index=date, columns=open/high/low/close/volume)}
            target_weights: DataFrame(index=date, columns=symbol), 目标权重 [-1, 1]

        Returns:
            EngineResult
        """
        dates, close, weights, returns = self._align(data_map, target_weights)
        if len(dates) == 0:
            return self._build_result(dates, close)

        self.equity_curve = [(dates[0], self.initial_cash)]
        for t_idx, ts in enumerate(dates[1:], start=1):
            self._execute_bars(ts, close, weights, returns, t_idx)
            equity = self._calc_equity(close, ts)
            self.equity_curve.append((ts, equity))

        return self._build_result(dates, close)

    def _align(
        self,
        data_map: dict[str, pd.DataFrame],
        target_weights: pd.DataFrame,
    ) -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """对齐日期、收盘价、目标权重、收益率。"""
        all_dates = sorted(set().union(*(df.index for df in data_map.values())))
        dates = pd.DatetimeIndex(all_dates)
        codes = sorted(data_map.keys())

        close = pd.DataFrame(index=dates, columns=codes, dtype=float)
        for code in codes:
            close[code] = data_map[code]["close"].reindex(dates)
        close = close.ffill(limit=5)

        weights = pd.DataFrame(0.0, index=dates, columns=codes)
        for code in codes:
            if code in target_weights.columns:
                raw = target_weights[code].reindex(data_map[code].index).fillna(0.0).clip(-1.0, 1.0)
                weights[code] = raw.shift(1).reindex(dates).ffill(limit=5).fillna(0.0)

        # 归一化权重
        scale = weights.abs().sum(axis=1).clip(lower=1.0)
        weights = weights.div(scale, axis=0)

        returns = close.pct_change().fillna(0.0)
        return dates, close, weights, returns

    def _execute_bars(
        self,
        ts: pd.Timestamp,
        close: pd.DataFrame,
        weights: pd.DataFrame,
        returns: pd.DataFrame,
        t_idx: int,
    ) -> None:
        """执行单个交易日的再平衡。"""
        equity = self._calc_equity(close, ts)
        for code in close.columns:
            bar = self._make_bar(close, code, ts, t_idx)
            if bar is None:
                continue
            self.on_bar(code, bar, ts)

            target_w = weights.loc[ts, code]
            self._rebalance(code, target_w, bar, ts, equity)

    def _make_bar(
        self, close: pd.DataFrame, code: str, ts: pd.Timestamp, t_idx: int
    ) -> Optional[pd.Series]:
        """构造单个 bar 的 Series。"""
        price = close.loc[ts, code]
        if pd.isna(price):
            return None
        prev = close.iloc[t_idx - 1][code] if t_idx > 0 else price
        bar = pd.Series({"close": price, "prev_close": prev, "open": price})
        return bar

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        bar: pd.Series,
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        target_dir = 1 if target_weight > 1e-9 else 0
        current = self.positions.get(symbol)

        # 平仓：目标空仓或方向改变
        if current is not None and target_dir == 0:
            self._close_position(symbol, current, bar, ts, "signal")
            return

        # 开新仓
        if target_dir == 1 and current is None:
            if not self.can_execute(symbol, target_dir, bar):
                return
            target_notional = equity * target_weight
            slipped = self.apply_slippage(bar["open"], target_dir)
            raw_size = target_notional / slipped
            size = self.round_size(raw_size, slipped)
            if size <= 0:
                return
            notional = size * slipped
            comm = self.calc_commission(size, slipped, target_dir, is_open=True)
            cost = notional + comm
            if cost > self.cash:
                return
            self.cash -= cost
            self.positions[symbol] = Position(
                symbol=symbol,
                direction=target_dir,
                size=size,
                entry_price=slipped,
                entry_time=ts,
                entry_notional=notional,
            )
            self._record_trade(symbol, target_dir, size, slipped, ts, comm)

    def _close_position(
        self,
        symbol: str,
        pos: Position,
        bar: pd.Series,
        ts: pd.Timestamp,
        reason: str,
    ) -> None:
        close_dir = -pos.direction
        if not self.can_execute(symbol, 0, bar):
            return
        slipped = self.apply_slippage(bar["open"], close_dir)
        notional = pos.size * slipped
        comm = self.calc_commission(pos.size, slipped, close_dir, is_open=False)
        self.cash += notional - comm
        pnl = (slipped - pos.entry_price) * pos.size * pos.direction - comm
        self._record_trade(symbol, close_dir, pos.size, slipped, ts, comm, pnl=pnl)
        del self.positions[symbol]

    def _record_trade(
        self,
        symbol: str,
        direction: int,
        size: float,
        price: float,
        ts: pd.Timestamp,
        commission: float,
        pnl: Optional[float] = None,
    ) -> None:
        self._trade_count += 1
        self.trades.append(
            {
                "symbol": symbol,
                "direction": direction,
                "size": size,
                "price": price,
                "timestamp": ts,
                "commission": commission,
                "pnl": pnl,
            }
        )

    def _calc_equity(self, close: pd.DataFrame, ts: pd.Timestamp) -> float:
        equity = self.cash
        for symbol, pos in self.positions.items():
            price = close.loc[ts, symbol]
            if not pd.isna(price):
                equity += pos.size * price * pos.direction
        return equity

    def _build_result(
        self, dates: pd.DatetimeIndex, close: pd.DataFrame
    ) -> EngineResult:
        if len(self.equity_curve) == 0:
            final_value = self.initial_cash
        else:
            final_value = self.equity_curve[-1][1]

        returns = pd.Series(
            [e for _, e in self.equity_curve],
            index=[d for d, _ in self.equity_curve],
        )
        total_return = (final_value / self.initial_cash) - 1.0
        max_dd = self._calc_max_drawdown(returns)
        sharpe = self._calc_sharpe(returns)
        annual = self._calc_annual_return(returns)
        win_rate = self._calc_win_rate()

        return EngineResult(
            strategy_name=self.config.get("strategy_name", "vibe_engine"),
            start_date=str(dates[0].date()) if len(dates) else "",
            end_date=str(dates[-1].date()) if len(dates) else "",
            initial_cash=self.initial_cash,
            final_value=final_value,
            total_return=total_return,
            annual_return=annual,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=self._trade_count,
            trades=self.trades,
        )

    @staticmethod
    def _calc_max_drawdown(equity: pd.Series) -> float:
        peak = equity.cummax()
        dd = (equity - peak) / peak
        return float(dd.min()) if len(dd) else 0.0

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

    def _calc_win_rate(self) -> float:
        closed = [t for t in self.trades if t.get("pnl") is not None]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t["pnl"] > 0)
        return wins / len(closed)
