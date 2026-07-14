# -*- coding: utf-8 -*-
"""读取 portfolio.yaml 仓位上限（无依赖重管道）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .models import PortfolioLimits


def load_portfolio_limits(path: Path | str | None) -> PortfolioLimits:
    """从 portfolio.yaml 提取 position_limits；失败则返回默认。"""
    if path is None:
        return PortfolioLimits()
    p = Path(path)
    if not p.exists():
        return PortfolioLimits()
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return PortfolioLimits()

    if not isinstance(raw, dict):
        return PortfolioLimits()
    lim = raw.get("position_limits") or {}
    if not isinstance(lim, dict):
        lim = {}

    def _f(key: str, default: float) -> float:
        v = lim.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    # single_stop_loss_pct 在画像里常是 0.02（相对本金单笔）；
    # 哨兵单票浮亏用持仓 initial_stop 更合理，这里作兜底默认 0.08
    single_stop = _f("single_stop_loss_pct", 0.08)
    if single_stop < 0.03:
        # 2% 对本金单笔过紧，告警层抬到 8% 浮亏（可被 config 覆盖）
        single_stop = 0.08

    return PortfolioLimits(
        total_capital=max(1.0, _f("total_capital", 500_000.0)),
        max_single_pct=_clamp01(_f("max_single_pct", 0.20)),
        max_total_exposure=_clamp01(_f("max_total_exposure", 0.80)),
        min_cash_pct=_clamp01(_f("min_cash_pct", 0.20)),
        single_stop_loss_pct=abs(single_stop),
        portfolio_drawdown_pct=abs(_f("portfolio_drawdown_pct", 0.05)),
        peak_drawdown_pct=abs(_f("peak_drawdown_pct", 0.08))
        if "peak_drawdown_pct" in lim
        else 0.08,
    )


def merge_limits(
    base: PortfolioLimits,
    overrides: Optional[dict[str, Any]] = None,
) -> PortfolioLimits:
    """用 sentinel config 数字覆盖 portfolio 默认。"""
    if not overrides:
        return base
    data = {
        "total_capital": base.total_capital,
        "max_single_pct": base.max_single_pct,
        "max_total_exposure": base.max_total_exposure,
        "min_cash_pct": base.min_cash_pct,
        "single_stop_loss_pct": base.single_stop_loss_pct,
        "portfolio_drawdown_pct": base.portfolio_drawdown_pct,
        "peak_drawdown_pct": base.peak_drawdown_pct,
    }
    for k in data:
        if k in overrides and overrides[k] is not None:
            try:
                data[k] = float(overrides[k])
            except (TypeError, ValueError):
                pass
    return PortfolioLimits(**data)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))
