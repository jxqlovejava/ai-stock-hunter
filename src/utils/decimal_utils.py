# -*- coding: utf-8 -*-
"""Decimal 精度工具 — 被 routing/data/valuation 共享，避免循环导入。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def D(val, precision: int = 4) -> Decimal:
    """Create Decimal with controlled precision."""
    if isinstance(val, Decimal):
        return val.quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)
    return Decimal(str(val)).quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)


def safe_divide(a, b, default: Decimal = Decimal("0"), precision: int = 4) -> Decimal:
    """Safe division with Decimal — never divide by zero or near-zero."""
    a_d = D(a) if not isinstance(a, Decimal) else a
    b_d = D(b) if not isinstance(b, Decimal) else b
    if abs(b_d) < Decimal("0.0001"):
        return default
    return (a_d / b_d).quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)
