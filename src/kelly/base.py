# -*- coding: utf-8 -*-
"""Sizer Protocol — 仓位计算器形式化接口。

借鉴 RiskGuard ``sizing/base.py`` 设计：Sizer 只管"下多大注"，
Rule 只管"能不能下"。两层严格分离，让仓位算法可替换、可测试。

所有 sizer 实现（KellyPositionSizer、VolatilityTargetSizer 等）
自动满足此 Protocol，无需显式继承。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .sizer import SizingResult


@runtime_checkable
class Sizer(Protocol):
    """仓位计算器协议。

    ``PositioningEngine`` 依赖此接口而非具体实现，
    允许在 Kelly、波动率目标、固定比例等算法之间切换。

    实现要求:
      - ``calc()`` 必须返回 ``SizingResult``
      - ``calc()`` 必须接受 symbol, score, macro_cap 三个位置参数
      - kelly_fraction 和 position_limits 为可选关键字参数
    """

    def calc(
        self,
        symbol: str,
        score: int,
        macro_cap: float = 0.80,
        kelly_fraction: float | None = None,
        position_limits: dict | None = None,
    ) -> SizingResult:
        """计算目标仓位。

        Args:
            symbol: 股票代码
            score: 裁决评分 (0-100)
            macro_cap: 宏观仓位上限 (0.0-1.0)
            kelly_fraction: 凯利系数 (None=使用默认值)
            position_limits: 用户偏好仓位约束

        Returns:
            SizingResult with target_weight and method
        """
        ...
