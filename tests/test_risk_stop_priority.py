# -*- coding: utf-8 -*-
"""风控止损优先级：positions.json 持仓止损 > timing ATR 建议止损。"""

from __future__ import annotations

from src.routing.positioning import TradeSignal
from src.routing.risk_control import RiskControlEngine


def _sig(suggested_stop: float = 50.47, action: str = "HOLD", weight: float = 0.1) -> TradeSignal:
    return TradeSignal(
        symbol="002460",
        action=action,
        target_weight=weight,
        suggested_stop=suggested_stop,
        atr_stop=suggested_stop,
        name="赣锋锂业",
    )


def test_position_stop_preferred_over_atr():
    """现价在 ATR 止损下、持仓止损上 → 不因 ATR 误触发。"""
    eng = RiskControlEngine()
    # 现价 49.85：ATR 建议 50.47 会触发；持仓止损 49.78 不触发
    result = eng.check(
        _sig(suggested_stop=50.47),
        portfolio={
            "current_price": 49.85,
            "stop_price": 49.78,
            "position_loss_pct": -0.08,
            "held": True,
        },
        position_limits={"stop_loss": -0.20},  # 放宽百分比止损，只测价格止损
    )
    atr_msgs = [v for v in result.violations if "ATR止损" in v]
    pos_msgs = [v for v in result.violations if "持仓止损" in v]
    assert not atr_msgs, f"不应再报 ATR 止损: {result.violations}"
    assert not pos_msgs, f"现价高于持仓止损，不应触发: {result.violations}"


def test_position_stop_triggers_with_label():
    eng = RiskControlEngine()
    result = eng.check(
        _sig(suggested_stop=50.47),
        portfolio={
            "current_price": 49.50,
            "stop_price": 49.78,
            "position_loss_pct": -0.09,
            "held": True,
        },
        position_limits={"stop_loss": -0.20},
    )
    assert result.passed is False
    assert any("持仓止损触发" in v for v in result.violations)
    assert not any("ATR止损触发" in v for v in result.violations)


def test_fallback_atr_when_no_position_stop():
    eng = RiskControlEngine()
    result = eng.check(
        _sig(suggested_stop=50.47),
        portfolio={
            "current_price": 49.50,
            "stop_price": 0,  # 无持仓止损
            "position_loss_pct": 0.0,
        },
        position_limits={"stop_loss": -0.20},
    )
    assert result.passed is False
    assert any("ATR止损触发" in v for v in result.violations)
