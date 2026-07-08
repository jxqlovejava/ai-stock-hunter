# -*- coding: utf-8 -*-
"""敞口投影工具 — 规则内部共用的仓位计算。

借鉴 RiskGuard ``_projection.py`` 设计。多条风控规则都要回答同一个问题：
"这笔单成交后，该标的的持仓会变成多少？它是在加仓（放大风险）还是减仓？"
以及"要把结果控制在某个数量上限内，这笔单最多能下多少？"
把这些算清楚一次，规则实现就能保持一致且简短。
"""

from __future__ import annotations

from typing import Optional

_REL_TOL = 1e-9
_ABS_TOL = 1e-12


def project_position(
    current_qty: float,
    order_qty: float,
    order_side_sign: int,
) -> tuple[float, float, bool]:
    """返回 ``(当前带符号持仓, 成交后带符号持仓, 是否在放大敞口)``。

    "放大敞口"有两种情形，都算 ``increasing=True``:

    1. **同向加仓**: 成交后 |持仓| 变大。
    2. **反手**: 持仓符号翻转（多变空或空变多）。反手会平掉旧仓、**开出一个全新的
       反向仓位**，即使新仓 |幅度| 不大于旧仓，它也是不折不扣的新增方向性风险。

    **关键教训 (来自 RiskGuard bug 修复)**: 早期版本只用
    ``abs(projected) > abs(current)`` 判断，导致"反手到等量或更小幅度"
    的单被当成减仓而绕过所有仓位上限规则**和熔断**——这是一个致命漏洞。
    只有"同向减仓（朝零收敛、不翻转）"才是 ``increasing=False``。

    Args:
        current_qty: 当前持仓数量（带符号：正=多，负=空）
        order_qty: 订单数量幅度（恒为正）
        order_side_sign: 订单方向符号（+1=买，-1=卖）

    Returns:
        (current_qty, projected_qty, increasing)
    """
    projected = current_qty + order_side_sign * order_qty
    flipped = (
        current_qty != 0.0
        and projected != 0.0
        and (current_qty > 0.0) != (projected > 0.0)
    )
    increasing = flipped or abs(projected) > abs(current_qty) + _ABS_TOL
    return current_qty, projected, increasing


def is_reducing_risk(
    current_qty: float,
    target_qty: float,
) -> bool:
    """判断从 current_qty → target_qty 是否为减仓/平仓方向。

    朝零收敛（同向减小或清仓）→ True。反手或同向扩大 → False。

    注意：target_qty=0（完全平仓）一定是减仓。
    """
    if abs(target_qty) < _ABS_TOL:
        return True  # 清仓
    if current_qty == 0.0:
        return False  # 空仓开仓 → 放大风险
    # 同向减小：|target| < |current| 且符号一致
    same_sign = (target_qty > 0) == (current_qty > 0)
    return same_sign and abs(target_qty) < abs(current_qty)


def within(magnitude: float, cap: float) -> bool:
    """带浮点容差地判断 ``magnitude <= cap``。"""
    return magnitude <= cap * (1.0 + _REL_TOL) + _ABS_TOL


def allowed_quantity(
    current_qty: float,
    side_sign: int,
    cap_qty: float,
) -> float:
    """在"成交后 |持仓| ≤ cap_qty"约束下，这笔单在其方向上最多允许的数量幅度。

    对减仓单不设限（调用方应先判定 ``increasing`` 再决定是否调用本函数）。
    """
    return max(0.0, cap_qty - side_sign * current_qty)


def projected_weight(
    current_qty: float,
    order_qty: float,
    side_sign: int,
    price: float,
    equity: float,
) -> float:
    """计算成交后的名义敞口权重 = |projected_qty| × price / equity。

    权益 ≤ 0 时返回 0.0。
    """
    if equity <= 0.0 or price <= 0.0:
        return 0.0
    _, projected, _ = project_position(current_qty, order_qty, side_sign)
    return abs(projected) * price / equity


def resolve_price(
    mark: Optional[float] = None,
    limit_price: Optional[float] = None,
    avg_price: Optional[float] = None,
) -> Optional[float]:
    """解析用于风险计价的价格。

    优先级: 标记价 > 限价 > 持仓均价。全都没有则返回 None——
    风控宁可显式失败，也绝不用猜测价放行 (fail-closed)。
    """
    if mark is not None and mark > 0:
        return mark
    if limit_price is not None and limit_price > 0:
        return limit_price
    if avg_price is not None and avg_price > 0:
        return avg_price
    return None
