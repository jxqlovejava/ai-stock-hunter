# -*- coding: utf-8 -*-
"""风控配置 — 借鉴 RiskGuard config.py 设计。

把所有风控阈值参数落在一个不可变 dataclass 里，构造时校验、启动即生效。
提供三档预设（保守/均衡/激进），每项参数单调不减。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional


class RiskPreset(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class RiskConfig:
    """不可变的风控参数集合，构造时即做区间校验。

    借鉴 RiskGuard RiskConfig: 每个参数都有明确区间，非法即抛。
    三档预设每项风险维度单调不减（越激进越松），且激进档仍收敛在稳健范围内。
    """

    # -- 单票仓位上限 --
    max_position_pct: float = 0.10
    """任一标的的名义敞口占总权益的上限 (0.10 = 10%)。"""

    # -- 回撤熔断线 --
    max_drawdown_pct: float = 0.15
    """相对历史权益高点的最大回撤，触及即熔断停新仓。"""

    # -- 行业上限 --
    max_sector_pct: float = 0.40
    """单行业总仓位上限。"""

    # -- 单笔止损 --
    single_stop_loss_pct: float = 0.02
    """单笔交易最大亏损比例。"""

    # -- 黑天鹅阈值 --
    black_swan_threshold_pct: float = 0.05
    """市场单日跌幅超过此值 → 黑天鹅熔断。"""

    # -- 新策略隔离 --
    quarantine_days: int = 90
    """新策略的隔离观察期（自然日）。期内仓位受更严格约束。"""

    quarantine_position_pct: float = 0.01
    """隔离期内单策略单标的的仓位上限 (1%)。"""

    # -- 组合层敞口 --
    max_gross_exposure_pct: float = 1.0
    """全组合总名义敞口上限。1.0 = 不加杠杆。"""

    max_net_exposure_pct: Optional[float] = None
    """全组合净敞口上限。None = 不限制。"""

    # -- 动态仓位 --
    kelly_fraction: float = 0.5
    """分数 Kelly 系数。1.0 为满 Kelly，实务常用 0.25~0.5。"""

    vol_target_annual: float = 0.15
    """波动率目标法的年化目标波动率 (0.15 = 15%)。"""

    max_sizing_leverage: float = 1.0
    """动态仓位算法允许的单标的最大权重。"""

    # -- 移动止损 --
    trailing_stop_pct: float = 0.03
    """移动止损的从最高点回撤比例 (3%)。"""

    # -- 元信息 --
    trading_days_per_year: int = 252

    def __post_init__(self) -> None:
        self._check_fraction("max_position_pct", self.max_position_pct)
        self._check_fraction("max_drawdown_pct", self.max_drawdown_pct)
        self._check_fraction("single_stop_loss_pct", self.single_stop_loss_pct)
        self._check_fraction("quarantine_position_pct", self.quarantine_position_pct)
        self._check_fraction("max_sector_pct", self.max_sector_pct)
        self._check_positive("max_gross_exposure_pct", self.max_gross_exposure_pct)
        if self.max_net_exposure_pct is not None:
            self._check_positive("max_net_exposure_pct", self.max_net_exposure_pct)
        self._check_positive("max_sizing_leverage", self.max_sizing_leverage)
        self._check_positive("vol_target_annual", self.vol_target_annual)

        if not (0.0 < self.kelly_fraction <= 1.0):
            raise ValueError(
                f"kelly_fraction must be in (0, 1], got {self.kelly_fraction}"
            )
        if self.quarantine_days < 0:
            raise ValueError(
                f"quarantine_days must be >= 0, got {self.quarantine_days}"
            )
        if self.trading_days_per_year <= 0:
            raise ValueError(
                f"trading_days_per_year must be > 0, got {self.trading_days_per_year}"
            )
        if self.quarantine_position_pct > self.max_position_pct:
            raise ValueError(
                "quarantine_position_pct should not exceed max_position_pct "
                f"({self.quarantine_position_pct} > {self.max_position_pct})"
            )
        if self.trailing_stop_pct <= 0 or self.trailing_stop_pct >= 1.0:
            raise ValueError(
                f"trailing_stop_pct must be in (0, 1), got {self.trailing_stop_pct}"
            )

    @staticmethod
    def _check_fraction(name: str, value: float) -> None:
        if not (0.0 < value <= 1.0):
            raise ValueError(f"{name} must be in (0, 1], got {value}")

    @staticmethod
    def _check_positive(name: str, value: float) -> None:
        if value <= 0.0:
            raise ValueError(f"{name} must be > 0, got {value}")

    def replace(self, **changes) -> "RiskConfig":
        """返回一个应用了变更的新配置（不可变模式）。"""
        return replace(self, **changes)

    @classmethod
    def preset(cls, preset: RiskPreset) -> "RiskConfig":
        """三档预设。每项参数单调不减: CONSERVATIVE ≤ BALANCED ≤ AGGRESSIVE。

        | 维度 | conservative | balanced | aggressive |
        | --- | --- | --- | --- |
        | 单票仓位上限 | 5% | 10% | 20% |
        | 回撤熔断线 | 10% | 15% | 25% |
        | 行业上限 | 25% | 40% | 50% |
        | 单笔止损 | 1.5% | 2% | 3% |
        | 组合敞口上限 | 0.8× | 1.0× | 1.5× |
        | Kelly 系数 | 0.25 | 0.50 | 0.50 |
        | 隔离天数 | 120 | 90 | 30 |
        """
        presets = {
            RiskPreset.CONSERVATIVE: cls(
                max_position_pct=0.05,
                max_drawdown_pct=0.10,
                max_sector_pct=0.25,
                single_stop_loss_pct=0.015,
                black_swan_threshold_pct=0.03,
                quarantine_days=120,
                quarantine_position_pct=0.005,
                max_gross_exposure_pct=0.8,
                max_net_exposure_pct=0.8,
                kelly_fraction=0.25,
                vol_target_annual=0.10,
                max_sizing_leverage=0.8,
                trailing_stop_pct=0.02,
            ),
            RiskPreset.BALANCED: cls(
                max_position_pct=0.10,
                max_drawdown_pct=0.15,
                max_sector_pct=0.40,
                single_stop_loss_pct=0.02,
                black_swan_threshold_pct=0.05,
                quarantine_days=90,
                quarantine_position_pct=0.01,
                max_gross_exposure_pct=1.0,
                max_net_exposure_pct=1.0,
                kelly_fraction=0.50,
                vol_target_annual=0.15,
                max_sizing_leverage=1.0,
                trailing_stop_pct=0.03,
            ),
            RiskPreset.AGGRESSIVE: cls(
                max_position_pct=0.20,
                max_drawdown_pct=0.25,
                max_sector_pct=0.50,
                single_stop_loss_pct=0.03,
                black_swan_threshold_pct=0.07,
                quarantine_days=30,
                quarantine_position_pct=0.02,
                max_gross_exposure_pct=1.5,
                max_net_exposure_pct=1.5,
                kelly_fraction=0.50,
                vol_target_annual=0.25,
                max_sizing_leverage=1.2,
                trailing_stop_pct=0.05,
            ),
        }
        return presets[preset]

    @classmethod
    def from_preferences(cls, prefs) -> "RiskConfig":
        """从投资者偏好映射到风控配置。

        根据 ``RiskProfile`` enum 选择预设，然后用 ``PositionLimits`` 覆盖差异项。
        """
        from src.learner.preference.model import RiskProfile as RP

        profile_map = {
            RP.CONSERVATIVE: RiskPreset.CONSERVATIVE,
            RP.BALANCED: RiskPreset.BALANCED,
            RP.AGGRESSIVE: RiskPreset.AGGRESSIVE,
        }
        rp = getattr(prefs, "risk_profile", None)
        preset = profile_map.get(rp, RiskPreset.BALANCED)
        config = cls.preset(preset)

        # 用 PositionLimits 覆盖
        if hasattr(prefs, "position_limits") and prefs.position_limits is not None:
            pl = prefs.position_limits
            overrides = {}
            if pl.max_single_pct is not None:
                overrides["max_position_pct"] = pl.max_single_pct
            if pl.max_sector_pct is not None:
                overrides["max_sector_pct"] = pl.max_sector_pct
            if pl.single_stop_loss_pct is not None:
                overrides["single_stop_loss_pct"] = pl.single_stop_loss_pct
            if pl.portfolio_drawdown_pct is not None:
                overrides["max_drawdown_pct"] = pl.portfolio_drawdown_pct
            if pl.kelly_fraction is not None:
                overrides["kelly_fraction"] = pl.kelly_fraction
            if overrides:
                config = config.replace(**overrides)

        return config

    def to_dict(self) -> dict:
        return {
            "max_position_pct": self.max_position_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_sector_pct": self.max_sector_pct,
            "single_stop_loss_pct": self.single_stop_loss_pct,
            "black_swan_threshold_pct": self.black_swan_threshold_pct,
            "quarantine_days": self.quarantine_days,
            "quarantine_position_pct": self.quarantine_position_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_net_exposure_pct": self.max_net_exposure_pct,
            "kelly_fraction": self.kelly_fraction,
            "vol_target_annual": self.vol_target_annual,
            "max_sizing_leverage": self.max_sizing_leverage,
            "trailing_stop_pct": self.trailing_stop_pct,
        }
