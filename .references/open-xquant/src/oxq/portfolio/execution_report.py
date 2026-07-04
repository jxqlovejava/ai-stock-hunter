"""ExecutionReport — compare simulated vs live fills."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from oxq.core.types import Fill


@dataclass(frozen=True)
class SymbolDateFill:
    """Aggregated fill for one symbol on one date."""

    symbol: str
    date: str
    side: str
    total_shares: int
    avg_price: Decimal
    total_fee: Decimal


@dataclass(frozen=True)
class FillComparison:
    """Side-by-side comparison of sim vs live fill."""

    symbol: str
    date: str
    side: str
    sim_shares: int
    sim_avg_price: Decimal
    sim_fee: Decimal
    live_shares: int
    live_avg_price: Decimal
    live_fee: Decimal
    shares_diff: int
    price_slippage: Decimal
    fee_diff: Decimal


class ExecutionReport:
    """Compare simulated fills against live fills.

    Aggregates by (symbol, date, side) and computes per-trade
    slippage and summary statistics.

    Parameters
    ----------
    sim_fills : list[Fill]
        Fills from backtesting (e.g. RunResult.trades).
    live_fills : list[Fill]
        Fills from live trading (e.g. LiveBroker).
    """

    def __init__(
        self,
        sim_fills: list[Fill],
        live_fills: list[Fill],
    ) -> None:
        sim_agg = _aggregate(sim_fills)
        live_agg = _aggregate(live_fills)
        self._comparisons = _compare(sim_agg, live_agg)

    @property
    def comparisons(self) -> list[FillComparison]:
        """Per-trade comparison details."""
        return self._comparisons

    def summary(self) -> dict[str, Decimal | int]:
        """Aggregate statistics."""
        matched = 0
        sim_only = 0
        live_only = 0
        total_slippage = Decimal("0")
        slippage_count = 0

        for c in self._comparisons:
            if c.sim_shares > 0 and c.live_shares > 0:
                matched += 1
                total_slippage += c.price_slippage
                slippage_count += 1
            elif c.sim_shares > 0:
                sim_only += 1
            else:
                live_only += 1

        return {
            "total_trades": len(self._comparisons),
            "matched_trades": matched,
            "sim_only_trades": sim_only,
            "live_only_trades": live_only,
            "avg_price_slippage": (
                total_slippage / slippage_count
                if slippage_count > 0
                else Decimal("0")
            ),
            "total_fee_diff": sum(
                (c.fee_diff for c in self._comparisons), Decimal("0")
            ),
        }


_Key = tuple[str, str, str]  # (symbol, date, side)


def _aggregate(fills: list[Fill]) -> dict[_Key, SymbolDateFill]:
    """Aggregate fills by (symbol, date, side)."""
    groups: dict[_Key, list[Fill]] = defaultdict(list)
    for f in fills:
        # Normalize date to just the date part
        date = f.filled_at[:10] if len(f.filled_at) >= 10 else f.filled_at
        key = (f.order.symbol, date, f.order.side)
        groups[key].append(f)

    result: dict[_Key, SymbolDateFill] = {}
    for key, group in groups.items():
        total_shares = sum(f.order.shares for f in group)
        total_cost = sum(f.filled_price * f.order.shares for f in group)
        avg_price = total_cost / total_shares if total_shares > 0 else Decimal("0")
        total_fee = sum(f.fee for f in group)
        result[key] = SymbolDateFill(
            symbol=key[0],
            date=key[1],
            side=key[2],
            total_shares=total_shares,
            avg_price=avg_price,
            total_fee=total_fee,
        )
    return result


def _compare(
    sim: dict[_Key, SymbolDateFill],
    live: dict[_Key, SymbolDateFill],
) -> list[FillComparison]:
    """Full outer join on (symbol, date, side)."""
    all_keys = sorted(set(sim.keys()) | set(live.keys()))
    comparisons: list[FillComparison] = []

    zero = SymbolDateFill(
        symbol="",
        date="",
        side="",
        total_shares=0,
        avg_price=Decimal("0"),
        total_fee=Decimal("0"),
    )

    for key in all_keys:
        s = sim.get(key, zero)
        lv = live.get(key, zero)
        price_slippage = (
            (lv.avg_price - s.avg_price) / s.avg_price
            if s.avg_price > 0 and lv.avg_price > 0
            else Decimal("0")
        )
        comparisons.append(
            FillComparison(
                symbol=key[0],
                date=key[1],
                side=key[2],
                sim_shares=s.total_shares,
                sim_avg_price=s.avg_price,
                sim_fee=s.total_fee,
                live_shares=lv.total_shares,
                live_avg_price=lv.avg_price,
                live_fee=lv.total_fee,
                shares_diff=lv.total_shares - s.total_shares,
                price_slippage=price_slippage,
                fee_diff=lv.total_fee - s.total_fee,
            )
        )

    return comparisons
