# -*- coding: utf-8 -*-
"""组合状态 — 模拟交易账户级不可变状态 + 持久化管理器。

设计原则:
  - PortfolioState: frozen dataclass，所有变更通过 replace() 返回新实例
  - 每笔持仓的止损追踪复用 ``PositionStateManager`` (三阶段止损)
  - HWM 追踪借鉴 RiskState (NaN 防御 + 回撤熔断)
  - JSON 持久化到 data/paper_trading/state.json
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.routing.position_state import PositionState, PositionStateManager

logger = logging.getLogger(__name__)

# 默认持久化路径
DEFAULT_STATE_DIR = Path("data/paper_trading")
DEFAULT_STATE_PATH = DEFAULT_STATE_DIR / "state.json"
DEFAULT_TRADES_PATH = DEFAULT_STATE_DIR / "trades.jsonl"


# ══════════════════════════════════════════════════════════════════════
# 交易记录 DTO
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PaperTrade:
    """单笔模拟交易记录 (不可变)。"""
    trade_id: str                    # 唯一 ID: "{symbol}_{timestamp}"
    symbol: str
    name: str
    action: str                      # "buy" | "sell"
    price: float
    quantity: int
    notional: float                  # 名义成交金额
    commission: float                # 佣金
    stamp_tax: float                 # 印花税
    transfer_fee: float              # 过户费
    total_cost: float                # 总交易成本
    net_amount: float                # 扣除成本后净额 (买入为负, 卖出为正)
    reason: str                      # 决策原因
    timestamp: str                   # ISO 格式时间戳
    remaining_cash: float            # 交易后剩余现金
    pnl_pct: float = 0.0             # 卖出时实现盈亏%

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "name": self.name,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "notional": round(self.notional, 2),
            "commission": round(self.commission, 4),
            "stamp_tax": round(self.stamp_tax, 4),
            "transfer_fee": round(self.transfer_fee, 4),
            "total_cost": round(self.total_cost, 4),
            "net_amount": round(self.net_amount, 2),
            "reason": self.reason,
            "timestamp": self.timestamp,
            "remaining_cash": round(self.remaining_cash, 2),
            "pnl_pct": round(self.pnl_pct, 6),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PaperTrade:
        return cls(
            trade_id=str(d.get("trade_id", "")),
            symbol=str(d.get("symbol", "")),
            name=str(d.get("name", "")),
            action=str(d.get("action", "buy")),
            price=float(d.get("price", 0)),
            quantity=int(d.get("quantity", 0)),
            notional=float(d.get("notional", 0)),
            commission=float(d.get("commission", 0)),
            stamp_tax=float(d.get("stamp_tax", 0)),
            transfer_fee=float(d.get("transfer_fee", 0)),
            total_cost=float(d.get("total_cost", 0)),
            net_amount=float(d.get("net_amount", 0)),
            reason=str(d.get("reason", "")),
            timestamp=str(d.get("timestamp", "")),
            remaining_cash=float(d.get("remaining_cash", 0)),
            pnl_pct=float(d.get("pnl_pct", 0)),
        )


# ══════════════════════════════════════════════════════════════════════
# 组合状态 (不可变)
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PortfolioState:
    """模拟交易组合不可变状态。

    所有变更通过 ``replace()`` 返回新实例。
    NaN 防御: observe_price / observe_equity 的坏读数直接返回 self。
    """

    # -- 账户 --
    initial_capital: float = 200_000.0
    cash: float = 200_000.0
    total_commission_paid: float = 0.0

    # -- HWM 追踪 (借鉴 RiskState) --
    high_water_mark: float = 200_000.0   # 历史最高权益
    last_equity: float = 200_000.0       # 最近一次观测权益

    # -- 持仓 (symbol → PositionState) --
    positions: dict = field(default_factory=dict)

    # -- 元数据 --
    start_date: str = ""                 # 模拟交易启动日期
    last_trade_date: str = ""            # 最近交易日
    total_trades: int = 0                # 累计交易笔数
    winning_trades: int = 0              # 盈利交易笔数
    losing_trades: int = 0               # 亏损交易笔数

    def __post_init__(self):
        """确保 positions 作为 dict 存储（frozen dataclass 兼容）。"""
        if self.positions is None:
            object.__setattr__(self, "positions", {})

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def positions_value(self) -> float:
        """持仓总市值 (按最近价格)。"""
        total = 0.0
        for pos in self.positions.values():
            if hasattr(pos, "last_price") and pos.last_price > 0:
                total += pos.quantity * pos.last_price
            elif hasattr(pos, "entry_price") and pos.entry_price > 0:
                total += pos.quantity * pos.entry_price
        return total

    @property
    def total_equity(self) -> float:
        """总权益 = 现金 + 持仓市值。"""
        return self.cash + self.positions_value

    @property
    def total_return_pct(self) -> float:
        """累计收益率 (相对于初始资金)。"""
        if self.initial_capital <= 0:
            return 0.0
        return (self.total_equity - self.initial_capital) / self.initial_capital

    @property
    def drawdown_pct(self) -> float:
        """当前回撤 (从 HWM)。借鉴 RiskState: 1 - equity/HWM。"""
        if self.high_water_mark <= 0:
            return 0.0
        return 1.0 - self.total_equity / self.high_water_mark

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def win_rate(self) -> float:
        if self.total_trades <= 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def exposure_pct(self) -> float:
        """当前仓位占比。"""
        if self.initial_capital <= 0:
            return 0.0
        return self.positions_value / self.initial_capital

    # ------------------------------------------------------------------
    # 不可变更新方法
    # ------------------------------------------------------------------

    def observe_equity(self) -> PortfolioState:
        """更新 HWM (每次市值变动后调用)。NaN 防御。"""
        equity = self.total_equity
        if not math.isfinite(equity) or equity <= 0:
            return self
        return replace(
            self,
            high_water_mark=max(self.high_water_mark, equity),
            last_equity=equity,
        )

    def with_cash(self, new_cash: float) -> PortfolioState:
        """更新现金余额。"""
        if not math.isfinite(new_cash):
            return self
        return replace(self, cash=round(new_cash, 2))

    def with_positions(self, positions: dict) -> PortfolioState:
        """替换持仓快照。"""
        return replace(self, positions=positions)

    def with_trade_recorded(
        self,
        is_win: bool,
        commission: float,
    ) -> PortfolioState:
        """记录一笔交易完成后的统计更新。"""
        return replace(
            self,
            total_trades=self.total_trades + 1,
            winning_trades=self.winning_trades + (1 if is_win else 0),
            losing_trades=self.losing_trades + (0 if is_win else 1),
            total_commission_paid=round(self.total_commission_paid + commission, 4),
        )

    def with_start_date(self, date_str: str) -> PortfolioState:
        return replace(self, start_date=date_str)

    def with_trade_date(self, date_str: str) -> PortfolioState:
        return replace(self, last_trade_date=date_str)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "total_commission_paid": self.total_commission_paid,
            "high_water_mark": self.high_water_mark,
            "last_equity": self.last_equity,
            "positions": {
                sym: pos.to_dict() for sym, pos in self.positions.items()
            },
            "start_date": self.start_date,
            "last_trade_date": self.last_trade_date,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PortfolioState:
        positions_raw = d.get("positions", {})
        positions = {}
        for sym, pd in positions_raw.items():
            try:
                positions[sym] = PositionState.from_dict(pd)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("跳过损坏的持仓记录 %s: %s", sym, e)

        return cls(
            initial_capital=float(d.get("initial_capital", 200_000)),
            cash=float(d.get("cash", 200_000)),
            total_commission_paid=float(d.get("total_commission_paid", 0)),
            high_water_mark=float(d.get("high_water_mark", 200_000)),
            last_equity=float(d.get("last_equity", 200_000)),
            positions=positions,
            start_date=str(d.get("start_date", "")),
            last_trade_date=str(d.get("last_trade_date", "")),
            total_trades=int(d.get("total_trades", 0)),
            winning_trades=int(d.get("winning_trades", 0)),
            losing_trades=int(d.get("losing_trades", 0)),
        )

    @classmethod
    def initial(cls, capital: float = 200_000.0, start_date: str = "") -> PortfolioState:
        """创建初始状态。"""
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        return cls(
            initial_capital=capital,
            cash=capital,
            high_water_mark=capital,
            last_equity=capital,
            start_date=start_date,
        )


# ══════════════════════════════════════════════════════════════════════
# 组合状态管理器
# ══════════════════════════════════════════════════════════════════════


class PortfolioStateManager:
    """模拟交易组合状态管理器。

    职责:
      - 管理 PortfolioState 的加载/保存
      - 每笔持仓的止损追踪委托给 PositionStateManager
      - 交易历史追加写入 JSONL

    用法::

        mgr = PortfolioStateManager()
        state = mgr.load_or_initialize(capital=200_000)
        # ... 执行交易 ...
        mgr.save(state)
        mgr.append_trade(trade_record)
    """

    def __init__(
        self,
        state_path: Path | None = None,
        trades_path: Path | None = None,
    ):
        self._state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self._trades_path = Path(trades_path) if trades_path else DEFAULT_TRADES_PATH

        # 每笔持仓的止损追踪复用现有 PositionStateManager
        self._position_mgr = PositionStateManager(
            path=DEFAULT_STATE_DIR / "paper_positions.json"
        )

    # ------------------------------------------------------------------
    # 加载 / 初始化
    # ------------------------------------------------------------------

    def load_or_initialize(self, capital: float = 200_000.0) -> PortfolioState:
        """加载状态；首次运行创建初始状态。"""
        if self._state_path.exists():
            state = self._load()
            if state is not None:
                logger.info("模拟交易状态已加载: 权益 %.2f, 持仓 %d 只",
                           state.total_equity, state.position_count)
                return state

        state = PortfolioState.initial(capital=capital)
        self.save(state)
        logger.info("模拟交易初始状态已创建: 本金 %.0f", capital)
        return state

    def _load(self) -> Optional[PortfolioState]:
        """从 JSON 加载状态。"""
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if raw is None:
                return None
            return PortfolioState.from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("无法加载模拟交易状态: %s", e)
            return None
        except FileNotFoundError:
            return None

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def save(self, state: PortfolioState) -> None:
        """持久化组合状态到 JSON。"""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._state_path.write_text(
                json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("无法保存模拟交易状态: %s", e)

    # ------------------------------------------------------------------
    # 交易历史
    # ------------------------------------------------------------------

    def append_trade(self, trade: PaperTrade) -> None:
        """追加一笔交易记录到 JSONL 文件。"""
        self._trades_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._trades_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(trade.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("无法写入交易历史: %s", e)

    def load_trades(self, limit: int = 500) -> list[PaperTrade]:
        """加载最近的交易记录。"""
        trades: list[PaperTrade] = []
        if not self._trades_path.exists():
            return trades
        try:
            with open(self._trades_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(PaperTrade.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning("跳过损坏的交易记录: %s", e)
        except OSError as e:
            logger.error("无法读取交易历史: %s", e)
        return trades

    def get_trades_for_period(
        self, start_date: str, end_date: str,
    ) -> list[PaperTrade]:
        """获取指定日期范围内的交易记录。

        Args:
            start_date: 开始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"
        """
        all_trades = self.load_trades()
        return [
            t for t in all_trades
            if start_date <= t.timestamp[:10] <= end_date
        ]

    # ------------------------------------------------------------------
    # 持仓管理 (委托给 PositionStateManager)
    # ------------------------------------------------------------------

    @property
    def position_manager(self) -> PositionStateManager:
        """获取底层的持仓止损追踪管理器。"""
        return self._position_mgr

    def sync_positions_from_state(self, state: PortfolioState) -> None:
        """从 PortfolioState.positions 同步到底层 PositionStateManager。"""
        for sym, pos in state.positions.items():
            if not self._position_mgr.is_open(sym):
                # 恢复已存在的持仓追踪
                self._position_mgr._positions[sym] = pos
        self._position_mgr._save()

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------

    def reset(self, capital: float = 200_000.0) -> PortfolioState:
        """重置模拟交易账户。"""
        self._position_mgr.clear()
        state = PortfolioState.initial(capital=capital)
        self.save(state)
        # 清空交易历史
        if self._trades_path.exists():
            self._trades_path.rename(
                self._trades_path.with_suffix(".jsonl.bak")
            )
        logger.info("模拟交易账户已重置: 本金 %.0f", capital)
        return state
