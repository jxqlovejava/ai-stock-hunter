# -*- coding: utf-8 -*-
"""回测引擎抽象基类。

借鉴 Vibe-Trading agent/backtest/engines/base.py，但适配 A 股长单逻辑。
Phase 8: 借鉴 VectorBT generic/drawdowns.py — 五阶段回撤生命周期 + Active/Recovered 分离。
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


# ------------------------------------------------------------------
# Phase 8: 五阶段回撤生命周期 (借鉴 VectorBT generic/drawdowns.py)
# ------------------------------------------------------------------

@dataclass
class DrawdownRecord:
    """单次回撤的完整生命周期。

    借鉴 VectorBT: Peak→Start→Valley→End→Status 五个时间点。
    """
    peak_date: str
    peak_value: float
    start_date: str
    valley_date: str
    valley_value: float
    end_date: str | None = None
    end_value: float | None = None
    status: str = "Active"  # "Recovered" or "Active"
    duration_days: int = 0       # Peak → Valley 下跌天数
    recovery_days: int | None = None  # Valley → End 恢复天数 (Active 时为 None)
    max_dd_pct: float = 0.0      # (valley - peak) / peak
    recovery_return_pct: float | None = None  # 恢复期收益率

    def to_dict(self) -> dict:
        return {
            "peak_date": self.peak_date,
            "peak_value": self.peak_value,
            "start_date": self.start_date,
            "valley_date": self.valley_date,
            "valley_value": self.valley_value,
            "end_date": self.end_date,
            "end_value": self.end_value,
            "status": self.status,
            "duration_days": self.duration_days,
            "recovery_days": self.recovery_days,
            "max_dd_pct": round(self.max_dd_pct, 4),
            "recovery_return_pct": (
                round(self.recovery_return_pct, 4)
                if self.recovery_return_pct is not None
                else None
            ),
        }


@dataclass
class DrawdownStats:
    """回撤统计汇总。

    借鉴 VectorBT: 默认排除 Active 回撤 (max_dd 仅 recovered)。
    ``incl_active=True`` 纳入全部。
    """
    max_dd: float = 0.0              # RECOVERED only (VectorBT convention)
    max_dd_active: float = 0.0       # including ACTIVE
    avg_dd: float = 0.0
    avg_dd_duration_days: float = 0.0
    avg_recovery_days: float = 0.0
    total_drawdowns: int = 0
    active_drawdowns: int = 0
    recovered_drawdowns: int = 0
    current_drawdown: float = 0.0
    records: list[DrawdownRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "max_dd": round(self.max_dd, 4),
            "max_dd_active": round(self.max_dd_active, 4),
            "avg_dd": round(self.avg_dd, 4),
            "avg_dd_duration_days": round(self.avg_dd_duration_days, 1),
            "avg_recovery_days": round(self.avg_recovery_days, 1),
            "total_drawdowns": self.total_drawdowns,
            "active_drawdowns": self.active_drawdowns,
            "recovered_drawdowns": self.recovered_drawdowns,
            "current_drawdown": round(self.current_drawdown, 4),
            "records": [r.to_dict() for r in self.records],
        }


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
    # Phase 8: 完整回撤生命周期
    drawdown_stats: Optional[DrawdownStats] = None


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
        # Phase 8: 五阶段回撤生命周期统计
        dd_stats = self.calculate_drawdown_stats(returns)

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
            drawdown_stats=dd_stats,  # Phase 8
        )

    @staticmethod
    def _calc_max_drawdown(equity: pd.Series) -> float:
        peak = equity.cummax()
        dd = (equity - peak) / peak
        return float(dd.min()) if len(dd) else 0.0

    @staticmethod
    def calculate_drawdown_stats(
        equity: pd.Series,
        incl_active: bool = False,
    ) -> DrawdownStats:
        """计算五阶段回撤生命周期统计。

        借鉴 VectorBT generic/drawdowns.py:
          - 每次回撤记录 Peak→Start→Valley→End→Status 五个时间点
          - 默认排除 Active 回撤 (VectorBT 惯例)，避免未恢复回撤污染指标
          - ``incl_active=True`` 纳入全部回撤

        Args:
            equity: 权益曲线 (pd.Series, index 为日期)
            incl_active: 是否在 avg 指标中包含活跃回撤

        Returns:
            DrawdownStats with full lifecycle records
        """
        if len(equity) < 2:
            return DrawdownStats()

        records: list[DrawdownRecord] = []
        peak_val = equity.iloc[0]
        peak_idx = equity.index[0]
        in_dd = False
        dd_start_idx = equity.index[0]
        valley_val = equity.iloc[0]
        valley_idx = equity.index[0]

        for i in range(1, len(equity)):
            cur_val = equity.iloc[i]
            cur_idx = equity.index[i]

            if cur_val > peak_val:
                # 新高: 如果之前在回撤中，回撤结束
                if in_dd:
                    end_val = cur_val
                    end_idx = cur_idx
                    # 找到回撤期间的最低点
                    dd_slice = equity.loc[dd_start_idx:cur_idx]
                    valley_val = dd_slice.min()
                    valley_idx = dd_slice.idxmin()
                    recovery_return = (end_val - valley_val) / valley_val

                    records.append(DrawdownRecord(
                        peak_date=str(peak_idx.date()) if hasattr(peak_idx, 'date') else str(peak_idx),
                        peak_value=float(peak_val),
                        start_date=str(dd_start_idx.date()) if hasattr(dd_start_idx, 'date') else str(dd_start_idx),
                        valley_date=str(valley_idx.date()) if hasattr(valley_idx, 'date') else str(valley_idx),
                        valley_value=float(valley_val),
                        end_date=str(end_idx.date()) if hasattr(end_idx, 'date') else str(end_idx),
                        end_value=float(end_val),
                        status="Recovered",
                        duration_days=(valley_idx - dd_start_idx).days if hasattr(valley_idx - dd_start_idx, 'days') else int((valley_idx - dd_start_idx) / np.timedelta64(1, 'D')),
                        recovery_days=(end_idx - valley_idx).days if hasattr(end_idx - valley_idx, 'days') else int((end_idx - valley_idx) / np.timedelta64(1, 'D')),
                        max_dd_pct=float((valley_val - peak_val) / peak_val),
                        recovery_return_pct=float(recovery_return),
                    ))
                    in_dd = False
                peak_val = cur_val
                peak_idx = cur_idx
            elif cur_val < peak_val:
                if not in_dd:
                    in_dd = True
                    dd_start_idx = cur_idx

        # 未恢复的活跃回撤
        if in_dd:
            dd_slice = equity.loc[dd_start_idx:]
            valley_val = dd_slice.min()
            valley_idx = dd_slice.idxmin()
            end_val = equity.iloc[-1]

            records.append(DrawdownRecord(
                peak_date=str(peak_idx.date()) if hasattr(peak_idx, 'date') else str(peak_idx),
                peak_value=float(peak_val),
                start_date=str(dd_start_idx.date()) if hasattr(dd_start_idx, 'date') else str(dd_start_idx),
                valley_date=str(valley_idx.date()) if hasattr(valley_idx, 'date') else str(valley_idx),
                valley_value=float(valley_val),
                end_date=None,
                end_value=None,
                status="Active",
                duration_days=(valley_idx - dd_start_idx).days if hasattr(valley_idx - dd_start_idx, 'days') else int((valley_idx - dd_start_idx) / np.timedelta64(1, 'D')),
                recovery_days=None,
                max_dd_pct=float((valley_val - peak_val) / peak_val),
                recovery_return_pct=None,
            ))

        # 汇总统计
        recovered = [r for r in records if r.status == "Recovered"]
        active = [r for r in records if r.status == "Active"]
        all_dd = recovered + active

        # max_dd: VectorBT 惯例 — 默认仅 recovered
        dd_pcts = [r.max_dd_pct for r in (recovered if recovered else all_dd)]
        dd_pcts_active = [r.max_dd_pct for r in (all_dd if recovered else all_dd)]

        # avg 指标的数据集
        dd_for_avg = all_dd if incl_active else recovered

        current_dd = 0.0
        if len(equity) > 0:
            cur_val = equity.iloc[-1]
            cur_peak = equity.cummax().iloc[-1]
            if cur_peak > 0:
                current_dd = float((cur_val - cur_peak) / cur_peak)

        return DrawdownStats(
            max_dd=abs(min(dd_pcts)) if dd_pcts else 0.0,
            max_dd_active=abs(min(dd_pcts_active)) if dd_pcts_active else 0.0,
            avg_dd=abs(sum(r.max_dd_pct for r in dd_for_avg) / len(dd_for_avg)) if dd_for_avg else 0.0,
            avg_dd_duration_days=(
                sum(r.duration_days for r in dd_for_avg) / len(dd_for_avg)
                if dd_for_avg else 0.0
            ),
            avg_recovery_days=(
                sum(r.recovery_days for r in recovered if r.recovery_days is not None) / len(recovered)
                if recovered else 0.0
            ),
            total_drawdowns=len(records),
            active_drawdowns=len(active),
            recovered_drawdowns=len(recovered),
            current_drawdown=current_dd,
            records=records,
        )

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
