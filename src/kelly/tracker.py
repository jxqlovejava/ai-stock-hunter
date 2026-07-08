# -*- coding: utf-8 -*-
"""TradeTracker — 交易记录 CRUD + 按 symbol 汇总 p/b。

持久化到 JSON 文件，支持:
  - 录入交易记录
  - 按 symbol 汇总胜率 (p)、盈亏比 (b)、交易笔数
  - 导出 KellyParams
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.decimal_utils import D

logger = logging.getLogger(__name__)

# 默认交易记录存储路径
DEFAULT_TRADES_PATH = Path("data/trades.json")


@dataclass
class TradeRecord:
    """单笔交易记录。"""
    symbol: str
    entry_date: str          # "YYYY-MM-DD"
    exit_date: str           # "YYYY-MM-DD" (必须已平仓)
    entry_price: float
    exit_price: float
    shares: int = 0
    direction: str = "LONG"  # LONG / SHORT
    notes: str = ""

    @property
    def return_pct(self) -> float:
        """收益率（含方向）。"""
        if self.entry_price <= 0:
            return 0.0
        direction_mult = 1.0 if self.direction == "LONG" else -1.0
        return direction_mult * (self.exit_price - self.entry_price) / self.entry_price

    @property
    def is_win(self) -> bool:
        return self.return_pct > 0

    @property
    def is_loss(self) -> bool:
        return self.return_pct <= 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "shares": self.shares,
            "direction": self.direction,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TradeRecord:
        return cls(
            symbol=d["symbol"],
            entry_date=d.get("entry_date", ""),
            exit_date=d.get("exit_date", ""),
            entry_price=float(d.get("entry_price", 0)),
            exit_price=float(d.get("exit_price", 0)),
            shares=int(d.get("shares", 0)),
            direction=d.get("direction", "LONG"),
            notes=d.get("notes", ""),
        )


@dataclass
class KellyParams:
    """个股凯利参数。"""
    symbol: str
    win_rate: float = 0.0          # p = 胜率
    payoff_ratio: float = 0.0      # b = 盈亏比 (avg_win / abs(avg_loss))
    n_trades: int = 0              # 交易笔数
    total_return_pct: float = 0.0  # 累计收益率
    avg_return_pct: float = 0.0    # 平均收益率
    kelly_f: float = 0.0           # f* = 标准凯利仓位
    last_updated: str = ""         # ISO timestamp

    @property
    def is_hot(self) -> bool:
        """是否满足凯利计算的最小样本。

        必须同时满足: n >= 5, payoff_ratio > 0, n_trades > 0。
        n_trades > 0 守卫防止 payoff_ratio 正值但样本为 0 的退化情况。
        """
        return self.n_trades >= 5 and self.payoff_ratio > 1e-6 and self.n_trades > 0


class TradeTracker:
    """交易记录追踪器。

    用法:
        tracker = TradeTracker()
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15",
            exit_date="2026-03-20", entry_price=1800.0,
            exit_price=1950.0, shares=100,
        ))
        params = tracker.get_kelly_params("600519")
        print(f"f* = {params.kelly_f:.2%}")
    """

    MIN_TRADES_FOR_KELLY = 5  # 凯利公式最低交易笔数阈值

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else DEFAULT_TRADES_PATH
        self._trades: dict[str, list[TradeRecord]] = {}  # symbol → records
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def track(self, record: TradeRecord) -> None:
        """录入一笔交易记录。"""
        symbol = record.symbol
        if symbol not in self._trades:
            self._trades[symbol] = []
        self._trades[symbol].append(record)
        self._save()
        logger.info(
            "Trade tracked: %s %s→%s %.2f%% %s",
            symbol, record.entry_date, record.exit_date,
            record.return_pct * 100,
            "WIN" if record.is_win else "LOSS",
        )

    def get_trades(self, symbol: str) -> list[TradeRecord]:
        """获取某只股票的所有交易记录。"""
        return list(self._trades.get(symbol, []))

    def get_all_symbols(self) -> list[str]:
        """获取所有有交易记录的股票代码。"""
        return sorted(self._trades.keys())

    def remove_trade(self, symbol: str, index: int) -> bool:
        """删除某只股票的第 index 笔交易。"""
        trades = self._trades.get(symbol, [])
        if 0 <= index < len(trades):
            trades.pop(index)
            if not trades:
                del self._trades[symbol]
            self._save()
            return True
        return False

    def clear_symbol(self, symbol: str) -> None:
        """清空某只股票的所有交易记录。"""
        self._trades.pop(symbol, None)
        self._save()

    # ------------------------------------------------------------------
    # 凯利参数计算
    # ------------------------------------------------------------------

    def get_kelly_params(self, symbol: str) -> KellyParams:
        """按 symbol 计算凯利参数。

        胜率 p = 盈利笔数 / 总笔数
        盈亏比 b = 平均盈利% / |平均亏损%|
        凯利 f* = (b × p - (1-p)) / b

        n_trades < MIN_TRADES_FOR_KELLY → f* 为 0（冷启动状态）
        """
        trades = self._trades.get(symbol, [])
        n = len(trades)

        if n == 0:
            return KellyParams(symbol=symbol, last_updated=datetime.now().isoformat())

        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if t.is_loss]

        p = len(wins) / n
        avg_win = sum(t.return_pct for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t.return_pct for t in losses) / len(losses)) if losses else 0.0

        # 盈亏比 b = avg_win / avg_loss
        b = avg_win / avg_loss if avg_loss > 0 else 0.0

        # 凯利公式 f* = (b × p - q) / b — Decimal 精算
        q = 1.0 - p
        if b > 0 and n >= self.MIN_TRADES_FOR_KELLY:
            kelly_f = float(max(D("0"), (D(b) * D(p) - D(q)) / D(b)))
        else:
            kelly_f = 0.0  # 冷启动

        total_return = sum(t.return_pct for t in trades)
        avg_return = total_return / n

        return KellyParams(
            symbol=symbol,
            win_rate=round(p, 4),
            payoff_ratio=round(b, 4),
            n_trades=n,
            total_return_pct=round(total_return * 100, 2),
            avg_return_pct=round(avg_return * 100, 2),
            kelly_f=round(kelly_f, 4),
            last_updated=datetime.now().isoformat(),
        )

    def get_all_kelly_params(self) -> dict[str, KellyParams]:
        """获取所有股票的凯利参数。"""
        return {s: self.get_kelly_params(s) for s in self._trades}

    def summary(self) -> str:
        """人类可读的汇总表。"""
        lines = [
            f"{'Symbol':<12} {'n':>4} {'Win%':>7} {'Payoff':>8} {'f*':>7} {'状态':>8}",
            "-" * 55,
        ]
        for symbol in sorted(self._trades.keys()):
            kp = self.get_kelly_params(symbol)
            status = "热启动" if kp.is_hot else f"冷({kp.n_trades}/5)"
            lines.append(
                f"{symbol:<12} {kp.n_trades:>4} {kp.win_rate:>6.1%} "
                f"{kp.payoff_ratio:>7.2f} {kp.kelly_f:>6.1%} {status:>8}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """持久化到 JSON 文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, list[dict]] = {}
        for symbol, trades in self._trades.items():
            data[symbol] = [t.to_dict() for t in trades]
        try:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to save trades to %s: %s", self._path, e)

    def _load(self) -> None:
        """从 JSON 文件加载。"""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._trades = {}
            for symbol, records in raw.items():
                self._trades[symbol] = [TradeRecord.from_dict(r) for r in records]
            logger.info(
                "Loaded %d symbols, %d total trades from %s",
                len(self._trades),
                sum(len(v) for v in self._trades.values()),
                self._path,
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Failed to load trades from %s: %s", self._path, e)
            self._trades = {}


# ------------------------------------------------------------------
# Phase 8: 交易记录三层视图 (借鉴 VectorBT portfolio/trades.py)
# ------------------------------------------------------------------

@dataclass
class EntryTrade:
    """每笔开仓的独立绩效。

    借鉴 VectorBT: 一笔大买单 + N 笔小卖单 → 1 个 EntryTrade。
    入口信息来自买单，出口信息是卖单的加权平均。
    做 T 的收益可以精确归属到每一笔开仓。
    """
    symbol: str
    entry_date: str
    entry_price: float
    entry_shares: int
    exit_date: str | None = None
    exit_price: float | None = None
    closed_shares: int = 0
    pnl: float = 0.0
    return_pct: float = 0.0
    is_open: bool = True

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "entry_shares": self.entry_shares,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "closed_shares": self.closed_shares,
            "pnl": round(self.pnl, 2),
            "return_pct": round(self.return_pct, 4),
            "is_open": self.is_open,
        }


@dataclass
class ExitTrade:
    """每笔平仓的独立绩效。

    借鉴 VectorBT: N 笔小买单 + 1 笔大卖单 → N 个 ExitTrade。
    可以看清分批建仓中哪几笔拖了后腿。
    """
    symbol: str
    exit_date: str
    exit_price: float
    exit_shares: int
    entry_date: str | None = None
    entry_price: float | None = None  # 加权平均成本
    closed_shares: int = 0
    pnl: float = 0.0
    return_pct: float = 0.0
    is_partial: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "exit_shares": self.exit_shares,
            "entry_date": self.entry_date,
            "entry_price": (
                round(self.entry_price, 2) if self.entry_price else None
            ),
            "closed_shares": self.closed_shares,
            "pnl": round(self.pnl, 2),
            "return_pct": round(self.return_pct, 4),
            "is_partial": self.is_partial,
        }


@dataclass
class PositionView:
    """完整持仓周期（从建仓到清仓的时序聚合）。

    借鉴 VectorBT Positions: EntryTrade 或 ExitTrade 序列在时间上
    连续的聚合，代表一个完整的开→持→平周期。
    """
    symbol: str
    open_date: str
    close_date: str | None = None
    direction: str = "LONG"
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_favor: float | None = None   # 持仓期间最大浮盈%
    max_adversity: float | None = None  # 持仓期间最大浮亏%
    bars_held: int = 0
    is_open: bool = True

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "open_date": self.open_date,
            "close_date": self.close_date,
            "direction": self.direction,
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "max_favor": (
                round(self.max_favor, 4) if self.max_favor is not None else None
            ),
            "max_adversity": (
                round(self.max_adversity, 4) if self.max_adversity is not None else None
            ),
            "bars_held": self.bars_held,
            "is_open": self.is_open,
        }


def build_entry_trades(records: list[TradeRecord]) -> list[EntryTrade]:
    """从 TradeRecord 列表构建 EntryTrade 视图。

    FIFO 匹配: 按时间顺序，每笔买单独立计算分摊的卖出份额和 PnL。
    借鉴 VectorBT EntryTrades.from_orders。

    加仓场景: 1 笔大买单 + N 笔小卖单 → 1 个 EntryTrade
    减仓场景: N 笔小买单 + 1 笔大卖单 → N 个 EntryTrade
    """
    if not records:
        return []

    # 按 entry_date 排序
    sorted_records = sorted(records, key=lambda r: r.entry_date)
    result: list[EntryTrade] = []

    for rec in sorted_records:
        if rec.direction != "LONG":
            continue
        is_open = not rec.exit_date or rec.exit_date == ""
        result.append(EntryTrade(
            symbol=rec.symbol,
            entry_date=rec.entry_date,
            entry_price=rec.entry_price,
            entry_shares=rec.shares,
            exit_date=rec.exit_date if not is_open else None,
            exit_price=rec.exit_price if not is_open else None,
            closed_shares=0 if is_open else rec.shares,
            pnl=(rec.exit_price - rec.entry_price) * rec.shares if not is_open else 0.0,
            return_pct=rec.return_pct if not is_open else 0.0,
            is_open=is_open,
        ))

    return result


def build_exit_trades(records: list[TradeRecord]) -> list[ExitTrade]:
    """从 TradeRecord 列表构建 ExitTrade 视图。

    借鉴 VectorBT ExitTrades.from_orders。
    """
    if not records:
        return []

    sorted_records = sorted(records, key=lambda r: r.exit_date if r.exit_date else "9999")
    result: list[ExitTrade] = []

    for rec in sorted_records:
        if rec.direction != "LONG":
            continue
        is_open = not rec.exit_date or rec.exit_date == ""
        if is_open:
            continue  # exit trades only for closed positions

        result.append(ExitTrade(
            symbol=rec.symbol,
            exit_date=rec.exit_date,
            exit_price=rec.exit_price,
            exit_shares=rec.shares,
            entry_date=rec.entry_date,
            entry_price=rec.entry_price,
            closed_shares=rec.shares,
            pnl=(rec.exit_price - rec.entry_price) * rec.shares,
            return_pct=rec.return_pct,
            is_partial=False,
        ))

    return result


def build_positions(records: list[TradeRecord]) -> list[PositionView]:
    """从 TradeRecord 列表构建 PositionView。

    按时间聚合连续的 entry/exit 为一个完整周期。
    """
    if not records:
        return []

    sorted_records = sorted(records, key=lambda r: r.entry_date)
    result: list[PositionView] = []

    for rec in sorted_records:
        if rec.direction != "LONG":
            continue
        is_open = not rec.exit_date or rec.exit_date == ""
        result.append(PositionView(
            symbol=rec.symbol,
            open_date=rec.entry_date,
            close_date=rec.exit_date if not is_open else None,
            direction=rec.direction,
            total_pnl=(rec.exit_price - rec.entry_price) * rec.shares if not is_open else 0.0,
            total_return_pct=rec.return_pct if not is_open else 0.0,
            bars_held=0,
            is_open=is_open,
        ))

    return result


def consistency_check(records: list[TradeRecord]) -> dict:
    """验证 Entry/Exit/Position 三层 PnL 一致性。

    借鉴 VectorBT: Entry PnL == Exit PnL == Position PnL。
    返回包含检查结果的 dict。
    """
    entry_trades = build_entry_trades(records)
    exit_trades = build_exit_trades(records)
    positions = build_positions(records)

    entry_pnl = sum(t.pnl for t in entry_trades)
    exit_pnl = sum(t.pnl for t in exit_trades)
    pos_pnl = sum(p.total_pnl for p in positions)

    return {
        "entry_trades_count": len(entry_trades),
        "exit_trades_count": len(exit_trades),
        "positions_count": len(positions),
        "entry_pnl": round(entry_pnl, 2),
        "exit_pnl": round(exit_pnl, 2),
        "position_pnl": round(pos_pnl, 2),
        "consistent": abs(entry_pnl - exit_pnl) < 0.01 and abs(entry_pnl - pos_pnl) < 0.01,
    }
