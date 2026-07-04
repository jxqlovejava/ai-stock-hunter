"""Tests for Order Rules (stop-loss, take-profit, trailing stop)."""

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, Position, RuleResult
from oxq.rules.order import StopLossRule, TakeProfitRule, TrailingStopRule


# ---------------------------------------------------------------------------
# StopLossRule
# ---------------------------------------------------------------------------


def test_stop_loss_triggers_when_price_at_threshold() -> None:
    rule = StopLossRule(threshold=0.05)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # stop_price = 100 * (1 - 0.05) = 95. close=95 → triggers
    row = pd.Series({"close": 95.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}
    assert result.reason != ""


def test_stop_loss_triggers_when_price_below_threshold() -> None:
    rule = StopLossRule(threshold=0.05)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # stop_price = 95. close=90 → triggers
    row = pd.Series({"close": 90.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}


def test_stop_loss_no_trigger_when_price_above_threshold() -> None:
    rule = StopLossRule(threshold=0.05)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # stop_price = 95. close=96 → no trigger
    row = pd.Series({"close": 96.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_stop_loss_no_position() -> None:
    rule = StopLossRule(threshold=0.05)
    portfolio = Portfolio(cash=Decimal("100000"))
    row = pd.Series({"close": 90.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_stop_loss_threshold_calculation() -> None:
    rule = StopLossRule(threshold=0.10)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("200"))},
    )
    # stop_price = 200 * 0.90 = 180. close=180 → triggers
    row = pd.Series({"close": 180.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert result.target_positions == {"AAPL": 0.0}

    # close=181 → no trigger
    row2 = pd.Series({"close": 181.0})
    result2 = rule.evaluate("AAPL", row2, portfolio)
    assert result2.target_positions is None


def test_stop_loss_accepts_prices_parameter() -> None:
    rule = StopLossRule(threshold=0.05)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    row = pd.Series({"close": 90.0})
    result = rule.evaluate("AAPL", row, portfolio, prices={"AAPL": Decimal("90")})
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}


# ---------------------------------------------------------------------------
# TakeProfitRule
# ---------------------------------------------------------------------------


def test_take_profit_triggers_when_price_at_threshold() -> None:
    rule = TakeProfitRule(threshold=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # target = 100 * 1.15 = 115. close=115 → triggers
    row = pd.Series({"close": 115.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}
    assert result.reason != ""


def test_take_profit_triggers_when_price_above_threshold() -> None:
    rule = TakeProfitRule(threshold=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # target = 115. close=120 → triggers
    row = pd.Series({"close": 120.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert result.target_positions == {"AAPL": 0.0}


def test_take_profit_no_trigger_when_below_threshold() -> None:
    rule = TakeProfitRule(threshold=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # target = 115. close=114 → no trigger
    row = pd.Series({"close": 114.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_take_profit_no_position() -> None:
    rule = TakeProfitRule(threshold=0.15)
    portfolio = Portfolio(cash=Decimal("100000"))
    row = pd.Series({"close": 120.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_take_profit_threshold_calculation() -> None:
    rule = TakeProfitRule(threshold=0.20)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("200"))},
    )
    # target = 200 * 1.20 = 240. close=240 → triggers
    row = pd.Series({"close": 240.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert result.target_positions == {"AAPL": 0.0}

    # close=239 → no trigger
    row2 = pd.Series({"close": 239.0})
    result2 = rule.evaluate("AAPL", row2, portfolio)
    assert result2.target_positions is None


# ---------------------------------------------------------------------------
# TrailingStopRule
# ---------------------------------------------------------------------------


def test_trailing_stop_no_trigger_on_first_bar() -> None:
    rule = TrailingStopRule(trail_pct=0.05)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # First bar sets HWM to 110, stop_level = 110*0.95 = 104.5 → 110 > 104.5, no trigger
    row = pd.Series({"close": 110.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_trailing_stop_triggers_on_retrace() -> None:
    rule = TrailingStopRule(trail_pct=0.10)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # Bar 1: close=200 → HWM=200
    row1 = pd.Series({"close": 200.0})
    result1 = rule.evaluate("AAPL", row1, portfolio)
    assert result1.target_positions is None

    # Bar 2: close=180 → stop_level = 200*0.90 = 180 → triggers (<=)
    row2 = pd.Series({"close": 180.0})
    result2 = rule.evaluate("AAPL", row2, portfolio)
    assert isinstance(result2, RuleResult)
    assert result2.target_positions == {"AAPL": 0.0}
    assert result2.reason != ""


def test_trailing_stop_hwm_updates() -> None:
    rule = TrailingStopRule(trail_pct=0.10)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100"))},
    )
    # Bar 1: close=100 → HWM=100
    row1 = pd.Series({"close": 100.0})
    rule.evaluate("AAPL", row1, portfolio)

    # Bar 2: close=120 → HWM=120
    row2 = pd.Series({"close": 120.0})
    rule.evaluate("AAPL", row2, portfolio)

    # Bar 3: close=109 → stop_level = 120*0.90 = 108 → 109 > 108, no trigger
    row3 = pd.Series({"close": 109.0})
    result = rule.evaluate("AAPL", row3, portfolio)
    assert result.target_positions is None

    # Bar 4: close=108 → stop_level = 120*0.90 = 108 → triggers (<=)
    row4 = pd.Series({"close": 108.0})
    result = rule.evaluate("AAPL", row4, portfolio)
    assert result.target_positions == {"AAPL": 0.0}


def test_trailing_stop_no_position() -> None:
    rule = TrailingStopRule(trail_pct=0.05)
    portfolio = Portfolio(cash=Decimal("100000"))
    row = pd.Series({"close": 155.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_trailing_stop_tracks_per_symbol() -> None:
    rule = TrailingStopRule(trail_pct=0.10)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={
            "AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100")),
            "MSFT": Position(symbol="MSFT", shares=50, avg_cost=Decimal("200")),
        },
    )
    # AAPL HWM=100, MSFT HWM=300
    rule.evaluate("AAPL", pd.Series({"close": 100.0}), portfolio)
    rule.evaluate("MSFT", pd.Series({"close": 300.0}), portfolio)

    # AAPL at 91 → stop_level = 100*0.90 = 90, 91 > 90 → no trigger
    result_aapl = rule.evaluate("AAPL", pd.Series({"close": 91.0}), portfolio)
    assert result_aapl.target_positions is None

    # MSFT at 270 → stop_level = 300*0.90 = 270 → triggers (<=)
    result_msft = rule.evaluate("MSFT", pd.Series({"close": 270.0}), portfolio)
    assert result_msft.target_positions == {"MSFT": 0.0}
