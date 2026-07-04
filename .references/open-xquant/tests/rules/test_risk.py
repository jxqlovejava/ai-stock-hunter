"""Tests for Risk Rules."""

from decimal import Decimal

import pandas as pd

from oxq.core.types import Portfolio, Position, RuleResult
from oxq.rules.risk import DailyLossLimitRisk, MaxDrawdownRisk


# ---------------------------------------------------------------------------
# MaxDrawdownRisk
# ---------------------------------------------------------------------------


def test_max_drawdown_returns_rule_result() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    row = pd.Series({"close": 150.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)


def test_max_drawdown_no_trigger() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    row = pd.Series({"close": 150.0})
    result = rule.evaluate("AAPL", row, portfolio)
    assert result.target_positions is None
    assert result.hold is False


def test_max_drawdown_triggers_with_position() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # First call establishes peak at 100*200 = 20000
    row_high = pd.Series({"close": 200.0})
    rule.evaluate("AAPL", row_high, portfolio)

    # Now price drops: value = 100*160 = 16000, dd = 4000/20000 = 20% > 15%
    row_low = pd.Series({"close": 160.0})
    result = rule.evaluate("AAPL", row_low, portfolio)
    assert isinstance(result, RuleResult)
    assert result.hold is True
    assert result.target_positions == {"AAPL": 0.0}
    assert result.reason != ""


def test_max_drawdown_no_position_still_holds() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(cash=Decimal("20000"))
    # Peak = 20000
    row = pd.Series({"close": 100.0})
    rule.evaluate("AAPL", row, portfolio)

    # Cash dropped to 16000 (simulating loss), dd = 20%
    portfolio.cash = Decimal("16000")
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)
    assert result.hold is True
    assert result.target_positions is None  # No position to liquidate


def test_max_drawdown_at_exact_boundary() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.20)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # First eval: peak = 100 * 200 = 20000
    row1 = pd.Series({"close": 200.0})
    rule.evaluate("AAPL", row1, portfolio)

    # Second eval: value = 100 * 160 = 16000, dd = 4000/20000 = 0.20 exactly
    row2 = pd.Series({"close": 160.0})
    result = rule.evaluate("AAPL", row2, portfolio)
    assert result.hold is True


def test_max_drawdown_new_high_resets_peak() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.20)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # Eval at close=200 -> peak=20000
    row1 = pd.Series({"close": 200.0})
    rule.evaluate("AAPL", row1, portfolio)

    # Eval at close=190 -> dd=5% -> no trigger
    row2 = pd.Series({"close": 190.0})
    result = rule.evaluate("AAPL", row2, portfolio)
    assert result.hold is False

    # Eval at close=210 -> new peak=21000
    row3 = pd.Series({"close": 210.0})
    rule.evaluate("AAPL", row3, portfolio)

    # Eval at close=175 -> dd=(21000-17500)/21000~16.7% -> no trigger (< 20%)
    row4 = pd.Series({"close": 175.0})
    result = rule.evaluate("AAPL", row4, portfolio)
    assert result.hold is False

    # Eval at close=168 -> dd=(21000-16800)/21000=20% -> trigger
    row5 = pd.Series({"close": 168.0})
    result = rule.evaluate("AAPL", row5, portfolio)
    assert result.hold is True


def test_max_drawdown_multiple_symbols() -> None:
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # Eval("AAPL", close=200) -> establishes peak
    row_aapl = pd.Series({"close": 200.0})
    rule.evaluate("AAPL", row_aapl, portfolio)

    # Eval("MSFT", close=300) with no MSFT position -> no liquidation
    row_msft = pd.Series({"close": 300.0})
    result = rule.evaluate("MSFT", row_msft, portfolio)
    # Risk is portfolio-level; no drawdown occurred so no trigger
    assert result.target_positions is None


# ---------------------------------------------------------------------------
# DailyLossLimitRisk
# ---------------------------------------------------------------------------


def test_daily_loss_limit_returns_rule_result() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.03)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    row = pd.Series({"close": 150.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row, portfolio)
    assert isinstance(result, RuleResult)


def test_daily_loss_limit_no_trigger() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.03)
    portfolio = Portfolio(
        cash=Decimal("50000"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    row = pd.Series({"close": 150.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row, portfolio)
    assert result.target_positions is None
    assert result.hold is False


def test_daily_loss_limit_triggers() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.03)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # First eval on Day 1 establishes day_start_value = 100*200 = 20000
    row1 = pd.Series({"close": 200.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio)

    # Second eval same day, price dropped: value = 100*190 = 19000
    # daily loss = 1000/20000 = 5% > 3%
    row2 = pd.Series({"close": 190.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio)
    assert isinstance(result, RuleResult)
    assert result.hold is True
    assert result.target_positions is None  # Only freeze, no liquidation
    assert result.reason != ""


def test_daily_loss_limit_at_exact_boundary() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.05)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # First eval day1 close=200 -> day_start=20000
    row1 = pd.Series({"close": 200.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio)

    # Second eval day1 close=190 -> loss=1000/20000=5% exactly
    row2 = pd.Series({"close": 190.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio)
    assert result.hold is True


def test_daily_loss_limit_resets_next_day() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.05)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # Day 1 close=200 -> establishes start value=20000
    row1 = pd.Series({"close": 200.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio)

    # Day 1 close=190 -> loss=5% -> triggers hold=True
    row2 = pd.Series({"close": 190.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio)
    assert result.hold is True

    # Day 2 (new date) close=190 -> new day_start=19000
    row3 = pd.Series({"close": 190.0}, name=pd.Timestamp("2024-01-03"))
    rule.evaluate("AAPL", row3, portfolio)

    # Day 2 close=185 -> loss=500/19000~2.6% -> should NOT trigger
    row4 = pd.Series({"close": 185.0}, name=pd.Timestamp("2024-01-03"))
    result = rule.evaluate("AAPL", row4, portfolio)
    assert result.hold is False


def test_daily_loss_limit_no_trigger_with_gain() -> None:
    rule = DailyLossLimitRisk(max_daily_loss=0.03)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={"AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("150"))},
    )
    # Day 1 close=200 -> start=20000
    row1 = pd.Series({"close": 200.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio)

    # Day 1 close=210 -> gain, not loss -> hold=False
    row2 = pd.Series({"close": 210.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio)
    assert result.hold is False


# ---------------------------------------------------------------------------
# Multi-asset prices tests (Bug 1 regression)
# ---------------------------------------------------------------------------


def test_max_drawdown_uses_all_prices() -> None:
    """With prices dict, other positions are valued correctly."""
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={
            "AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100")),
            "MSFT": Position(symbol="MSFT", shares=100, avg_cost=Decimal("200")),
        },
    )
    all_prices = {
        "AAPL": Decimal("100"),
        "MSFT": Decimal("200"),
    }
    # Peak = 100*100 + 100*200 = 30000
    row = pd.Series({"close": 100.0})
    rule.evaluate("AAPL", row, portfolio, prices=all_prices)

    # AAPL drops to 80, MSFT stays at 200
    # total = 8000 + 20000 = 28000, dd = 2000/30000 = 6.7% -> no trigger
    all_prices_drop = {"AAPL": Decimal("80"), "MSFT": Decimal("200")}
    row_drop = pd.Series({"close": 80.0})
    result = rule.evaluate("AAPL", row_drop, portfolio, prices=all_prices_drop)
    assert result.hold is False


def test_max_drawdown_false_trigger_without_prices() -> None:
    """Without prices dict (old behavior), MSFT valued at 0 -> false trigger."""
    rule = MaxDrawdownRisk(max_drawdown=0.15)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={
            "AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100")),
            "MSFT": Position(symbol="MSFT", shares=100, avg_cost=Decimal("200")),
        },
    )
    # Without prices: peak = cash(0) + AAPL(100*100) + MSFT(0) = 10000
    row = pd.Series({"close": 100.0})
    rule.evaluate("AAPL", row, portfolio)  # no prices -> only AAPL counted

    # AAPL drops to 80: value = 0 + 8000 + 0 = 8000, dd = 2000/10000 = 20% -> trigger!
    row_drop = pd.Series({"close": 80.0})
    result = rule.evaluate("AAPL", row_drop, portfolio)
    # This IS a false trigger -- with correct prices dd would be only 6.7%
    assert result.hold is True


def test_daily_loss_uses_all_prices() -> None:
    """With prices dict, daily loss is computed on full portfolio."""
    rule = DailyLossLimitRisk(max_daily_loss=0.05)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={
            "AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100")),
            "MSFT": Position(symbol="MSFT", shares=100, avg_cost=Decimal("300")),
        },
    )
    # Day start: AAPL=100, MSFT=300 -> total = 10000 + 30000 = 40000
    all_prices = {"AAPL": Decimal("100"), "MSFT": Decimal("300")}
    row1 = pd.Series({"close": 100.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio, prices=all_prices)

    # AAPL drops to 90, MSFT stays -> total = 9000 + 30000 = 39000
    # daily loss = 1000/40000 = 2.5% -> no trigger (< 5%)
    prices_drop = {"AAPL": Decimal("90"), "MSFT": Decimal("300")}
    row2 = pd.Series({"close": 90.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio, prices=prices_drop)
    assert result.hold is False


def test_daily_loss_false_trigger_without_prices() -> None:
    """Without prices dict, MSFT valued at 0 -> false trigger."""
    rule = DailyLossLimitRisk(max_daily_loss=0.05)
    portfolio = Portfolio(
        cash=Decimal("0"),
        positions={
            "AAPL": Position(symbol="AAPL", shares=100, avg_cost=Decimal("100")),
            "MSFT": Position(symbol="MSFT", shares=100, avg_cost=Decimal("300")),
        },
    )
    # Without prices: day start = 0 + 10000 + 0 = 10000
    row1 = pd.Series({"close": 100.0}, name=pd.Timestamp("2024-01-02"))
    rule.evaluate("AAPL", row1, portfolio)

    # AAPL drops to 90: value = 9000, loss = 1000/10000 = 10% -> trigger!
    row2 = pd.Series({"close": 90.0}, name=pd.Timestamp("2024-01-02"))
    result = rule.evaluate("AAPL", row2, portfolio)
    # False trigger -- with correct prices loss would be only 2.5%
    assert result.hold is True
