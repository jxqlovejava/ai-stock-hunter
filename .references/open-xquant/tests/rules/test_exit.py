"""Tests for ExitRule."""

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, Position, Rule, RuleResult
from oxq.rules.exit import ExitRule


def test_exit_rule_satisfies_rule_protocol() -> None:
    assert isinstance(ExitRule(fast="sma_10", slow="sma_50"), Rule)


def test_exit_rule_returns_rule_result() -> None:
    rule = ExitRule(fast="sma_10", slow="sma_50")
    row = pd.Series({"close": 140.0, "sma_10": 105.0, "sma_50": 100.0})
    portfolio = Portfolio(cash=Decimal("100000"))
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)


def test_exit_rule_targets_zero_when_fast_below_slow() -> None:
    rule = ExitRule(fast="sma_10", slow="sma_50")
    row = pd.Series({"close": 140.0, "sma_10": 95.0, "sma_50": 100.0})
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )

    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}
    assert result.reason != ""


def test_exit_rule_no_action_when_fast_above_slow() -> None:
    rule = ExitRule(fast="sma_10", slow="sma_50")
    row = pd.Series({"close": 160.0, "sma_10": 105.0, "sma_50": 100.0})
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )

    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None
    assert result.hold is False


def test_exit_rule_no_action_without_position() -> None:
    rule = ExitRule(fast="sma_10", slow="sma_50")
    row = pd.Series({"close": 140.0, "sma_10": 95.0, "sma_50": 100.0})
    portfolio = Portfolio(cash=Decimal("100000"))

    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.target_positions is None


def test_exit_rule_accepts_prices_parameter() -> None:
    rule = ExitRule(fast="sma_10", slow="sma_50")
    row = pd.Series({"close": 140.0, "sma_10": 95.0, "sma_50": 100.0})
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    prices = {"AAPL": Decimal("140")}

    result = rule.evaluate("AAPL", row, portfolio, prices=prices)
    assert isinstance(result, RuleResult)
    assert result.target_positions == {"AAPL": 0.0}
