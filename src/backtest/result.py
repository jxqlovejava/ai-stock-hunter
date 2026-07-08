# -*- coding: utf-8 -*-
"""回测结果类型定义 — BaizeResult, TradeRecord, Order.

借鉴 Backtrader Cerebro 的结果模型 + VectorBT 三层交易视角。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd

from src.backtest.engines.base import DrawdownStats
from src.data.source_citation import SourceCitation


# ------------------------------------------------------------------
# Order
# ------------------------------------------------------------------

class OrderStatus(str, Enum):
    CREATED = "Created"
    SUBMITTED = "Submitted"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    PARTIAL = "Partial"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"
    STOP = "Stop"
    STOP_LIMIT = "StopLimit"


@dataclass
class Order:
    """订单记录 — 借鉴 Backtrader Order 模型。"""
    order_id: int
    symbol: str
    order_type: OrderType = OrderType.MARKET
    action: str = "BUY"          # "BUY" | "SELL"
    size: int = 0                # 股数
    price: float = 0.0           # 限价/止损价
    status: OrderStatus = OrderStatus.CREATED
    created_at: pd.Timestamp | None = None
    executed_at: pd.Timestamp | None = None
    executed_price: float | None = None
    executed_size: int = 0
    commission: float = 0.0
    reject_reason: str = ""

    @property
    def is_buy(self) -> bool:
        return self.action == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.action == "SELL"

    @property
    def is_completed(self) -> bool:
        return self.status == OrderStatus.COMPLETED

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "order_type": self.order_type.value,
            "action": self.action,
            "size": self.size,
            "price": self.price,
            "status": self.status.value,
            "executed_price": self.executed_price,
            "executed_size": self.executed_size,
            "commission": round(self.commission, 4),
            "reject_reason": self.reject_reason,
        }


# ------------------------------------------------------------------
# TradeRecord — 借鉴 VectorBT Entry/Exit Trade 三层模型
# ------------------------------------------------------------------

@dataclass
class TradeRecord:
    """单笔交易记录。

    借鉴 VectorBT portfolio/trades.py:
      Entry Trade: 每笔买入 + 分摊卖出的份额
      Exit Trade:  每笔卖出 + 分摊买入的成本
      Position:    时序上连续的 entry/exit 聚合
    """
    trade_id: int
    symbol: str
    direction: int             # 1=long, -1=short
    entry_date: str = ""
    entry_price: float = 0.0
    entry_size: int = 0
    entry_notional: float = 0.0
    exit_date: str = ""
    exit_price: float = 0.0
    exit_size: int = 0
    exit_notional: float = 0.0
    pnl: float = 0.0           # 绝对盈亏
    pnl_pct: float = 0.0       # 百分比盈亏
    commission: float = 0.0
    holding_days: int = 0
    is_open: bool = True       # True=仍持仓, False=已平仓
    tags: list[str] = field(default_factory=list)  # 标签: "stop_loss", "take_profit", "signal"

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "entry_size": self.entry_size,
            "entry_notional": round(self.entry_notional, 2),
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "exit_size": self.exit_size,
            "exit_notional": round(self.exit_notional, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "commission": round(self.commission, 4),
            "holding_days": self.holding_days,
            "is_open": self.is_open,
            "tags": self.tags,
        }


# ------------------------------------------------------------------
# BaizeResult — 统一回测结果
# ------------------------------------------------------------------

@dataclass
class BaizeResult:
    """统一回测结果 — 借鉴 Backtrader Cerebro.run() 返回格式。

    包含:
      - 核心指标 (total_return, annual_return, sharpe_ratio, max_drawdown, win_rate)
      - 回撤5阶段生命周期 (DrawdownStats)
      - 交易记录 (TradeRecord[])
      - 分析器输出 (analyzers)
      - 权益曲线 (equity_curve, pd.Series)
      - 年度收益 (yearly_returns)
      - 数据溯源 (data_citation, signal_citation)
    """
    strategy_name: str = ""
    strategy_params: dict = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    initial_cash: float = 0.0
    final_value: float = 0.0

    # 核心指标
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0

    # 扩展指标
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0

    # 交易记录
    trades: list[TradeRecord] = field(default_factory=list)
    open_trades: list[TradeRecord] = field(default_factory=list)

    # 权益曲线
    equity_curve: Optional[pd.Series] = None

    # 年度收益
    yearly_returns: dict[str, float] = field(default_factory=dict)

    # 回撤统计 (借鉴 VectorBT 五阶段生命周期)
    drawdown_stats: Optional[DrawdownStats] = None

    # 分析器输出 {analyzer_name: analysis_dict}
    analyzers: dict[str, dict] = field(default_factory=dict)

    # 数据溯源
    data_citation: Optional[SourceCitation] = None
    signal_citation: Optional[SourceCitation] = None

    # 风控状态
    trading_blocked: bool = False
    block_reason: str = ""
    breaker_tripped: bool = False

    # 元数据
    benchmark_return: float = 0.0
    benchmark_symbol: str = "000300.SH"

    def to_dict(self) -> dict:
        result = {
            "strategy_name": self.strategy_name,
            "strategy_params": self.strategy_params,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_cash": self.initial_cash,
            "final_value": round(self.final_value, 2),
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "profit_factor": round(self.profit_factor, 4),
            "trades": [t.to_dict() for t in self.trades],
            "open_trades": len(self.open_trades),
            "yearly_returns": self.yearly_returns,
            "drawdown_stats": self.drawdown_stats.to_dict() if self.drawdown_stats else None,
            "analyzers": self.analyzers,
            "trading_blocked": self.trading_blocked,
            "block_reason": self.block_reason,
            "breaker_tripped": self.breaker_tripped,
            "benchmark_return": round(self.benchmark_return, 4),
            "benchmark_symbol": self.benchmark_symbol,
        }
        return result

    def summary(self) -> str:
        """单行摘要。"""
        return (
            f"[{self.strategy_name}] "
            f"Return={self.total_return:.2%} "
            f"Sharpe={self.sharpe_ratio:.2f} "
            f"MaxDD={self.max_drawdown:.2%} "
            f"WinRate={self.win_rate:.1%} "
            f"Trades={self.total_trades}"
        )
