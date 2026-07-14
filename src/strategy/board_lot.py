# -*- coding: utf-8 -*-
"""A 股整手工具 — 买入/卖出数量按 100 股一手约束。

规则（简化实操）:
  - 买入数量必须为 100 的整数倍；不足一手 → 0。
  - 卖出数量优先向下取整到 100 的整数倍。
  - 若持仓恰好 1 手（100 股），无法「半仓」→ 只能全卖或全留。
  - 若向下取整后卖出量为 0，但目标减仓比例 > 0 且持仓 ≥ 1 手，
    调用方应升级为全平（见 ``resolve_sell_quantity``）。
"""

from __future__ import annotations

BOARD_LOT: int = 100


def floor_to_lot(shares: int, lot: int = BOARD_LOT) -> int:
    """向下取整到整手。负数归零。"""
    if shares <= 0 or lot <= 0:
        return 0
    return (shares // lot) * lot


def ceil_to_lot(shares: int, lot: int = BOARD_LOT) -> int:
    """向上取整到整手（用于预算上限内尽量满手买）。"""
    if shares <= 0 or lot <= 0:
        return 0
    return ((shares + lot - 1) // lot) * lot


def can_partial_reduce(total_shares: int, lot: int = BOARD_LOT) -> bool:
    """是否存在可执行的「非整仓」减仓（至少保留 1 手且至少卖 1 手）。"""
    return total_shares >= 2 * lot


def resolve_sell_quantity(
    total_shares: int,
    target_exit_pct: float,
    *,
    lot: int = BOARD_LOT,
    force_full_if_sub_lot: bool = True,
) -> tuple[int, str]:
    """将目标减仓比例映射为可下单股数。

    Args:
        total_shares: 当前持仓股数
        target_exit_pct: 目标卖出比例 0–100（100=清仓）
        force_full_if_sub_lot: 若按比例取整后 < 1 手但必须减仓，是否升级为全平

    Returns:
        (quantity, note) — quantity 为 0 表示无法/不必卖
    """
    if total_shares <= 0:
        return 0, "empty_position"
    if target_exit_pct <= 0:
        return 0, "no_exit"

    if target_exit_pct >= 100:
        return total_shares, "full_exit"

    raw = int(round(total_shares * (target_exit_pct / 100.0)))
    qty = floor_to_lot(raw, lot)

    if qty <= 0:
        if force_full_if_sub_lot and total_shares >= lot:
            # 1 手持仓无法半仓 → 只能全平才能「减仓」
            return total_shares, "lot_constraint_full_exit"
        return 0, "lot_constraint_infeasible"

    # 卖完后剩余若不足 1 手且不为 0，A 股可持零股，但本系统偏好整手：
    remaining = total_shares - qty
    if 0 < remaining < lot and force_full_if_sub_lot:
        # 例如 150 股卖 100 剩 50：允许；若目标接近半仓且仅 100 股，已在上面处理
        pass

    if qty >= total_shares:
        return total_shares, "full_exit"

    return qty, "partial_lot_exit"


def resolve_buy_quantity(
    max_shares_budget: int,
    *,
    lot: int = BOARD_LOT,
) -> tuple[int, str]:
    """预算内最大可买整手数。"""
    qty = floor_to_lot(max_shares_budget, lot)
    if qty <= 0:
        return 0, "budget_below_one_lot"
    return qty, "ok"
