"""Tests for ParameterSet — parameter space definition and grid generation."""

import pytest

from oxq.optimize.paramset import (
    ParamConstraint,
    ParamDistribution,
    ParameterSet,
    _check_constraint,
    _resolve_operand,
)


# ---------------------------------------------------------------------------
# ParamDistribution
# ---------------------------------------------------------------------------


def test_param_distribution_is_frozen() -> None:
    pd = ParamDistribution(component="sma", param="period", values=(10, 20))
    with pytest.raises(AttributeError):
        pd.component = "ema"  # type: ignore[misc]


def test_param_distribution_stores_values_as_tuple() -> None:
    pd = ParamDistribution(component="sma", param="period", values=(5, 10, 15))
    assert pd.values == (5, 10, 15)


# ---------------------------------------------------------------------------
# ParamConstraint
# ---------------------------------------------------------------------------


def test_param_constraint_is_frozen() -> None:
    pc = ParamConstraint(expr="a.x < b.y")
    with pytest.raises(AttributeError):
        pc.expr = "a.x > b.y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _resolve_operand
# ---------------------------------------------------------------------------


def test_resolve_operand_param_ref() -> None:
    combo = {"sma_fast": {"period": 10}, "sma_slow": {"period": 50}}
    assert _resolve_operand("sma_fast.period", combo) == 10.0
    assert _resolve_operand("sma_slow.period", combo) == 50.0


def test_resolve_operand_numeric_literal() -> None:
    combo = {"sma": {"period": 10}}
    assert _resolve_operand("42", combo) == 42.0
    assert _resolve_operand("3.14", combo) == 3.14


# ---------------------------------------------------------------------------
# _check_constraint
# ---------------------------------------------------------------------------


def test_check_constraint_less_than() -> None:
    combo = {"a": {"x": 10}, "b": {"y": 20}}
    assert _check_constraint("a.x < b.y", combo) is True
    assert _check_constraint("b.y < a.x", combo) is False


def test_check_constraint_greater_than() -> None:
    combo = {"a": {"x": 50}, "b": {"y": 20}}
    assert _check_constraint("a.x > b.y", combo) is True


def test_check_constraint_less_equal() -> None:
    combo = {"a": {"x": 10}, "b": {"y": 10}}
    assert _check_constraint("a.x <= b.y", combo) is True
    assert _check_constraint("a.x < b.y", combo) is False


def test_check_constraint_greater_equal() -> None:
    combo = {"a": {"x": 10}, "b": {"y": 10}}
    assert _check_constraint("a.x >= b.y", combo) is True


def test_check_constraint_equal() -> None:
    combo = {"a": {"x": 10}, "b": {"y": 10}}
    assert _check_constraint("a.x == b.y", combo) is True


def test_check_constraint_not_equal() -> None:
    combo = {"a": {"x": 10}, "b": {"y": 20}}
    assert _check_constraint("a.x != b.y", combo) is True
    combo2 = {"a": {"x": 10}, "b": {"y": 10}}
    assert _check_constraint("a.x != b.y", combo2) is False


def test_check_constraint_with_numeric_literal() -> None:
    combo = {"sma": {"period": 10}}
    assert _check_constraint("sma.period > 5", combo) is True
    assert _check_constraint("sma.period > 15", combo) is False


def test_check_constraint_invalid_expr() -> None:
    with pytest.raises(ValueError, match="Invalid constraint"):
        _check_constraint("not a valid expression", {})


# ---------------------------------------------------------------------------
# ParameterSet — add / grid
# ---------------------------------------------------------------------------


def test_empty_paramset_returns_single_empty_combo() -> None:
    ps = ParameterSet("empty")
    assert ps.grid() == [{}]


def test_single_param_grid() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10, 20, 30])
    grid = ps.grid()
    assert len(grid) == 3
    assert grid[0] == {"sma": {"period": 10}}
    assert grid[1] == {"sma": {"period": 20}}
    assert grid[2] == {"sma": {"period": 30}}


def test_multi_param_same_component() -> None:
    """Two params on the same component produce cartesian product."""
    ps = ParameterSet("test")
    ps.add("bb", "period", values=[10, 20])
    ps.add("bb", "std_dev", values=[1.5, 2.0])
    grid = ps.grid()
    # 2 × 2 = 4 combos
    assert len(grid) == 4
    # Check one expected combo
    assert {"bb": {"period": 10, "std_dev": 1.5}} in grid
    assert {"bb": {"period": 20, "std_dev": 2.0}} in grid


def test_multi_component_grid() -> None:
    """Two components produce cartesian product across components."""
    ps = ParameterSet("test")
    ps.add("sma_fast", "period", values=[5, 10])
    ps.add("sma_slow", "period", values=[20, 50])
    grid = ps.grid()
    # 2 × 2 = 4 combos
    assert len(grid) == 4
    assert {"sma_fast": {"period": 5}, "sma_slow": {"period": 20}} in grid
    assert {"sma_fast": {"period": 10}, "sma_slow": {"period": 50}} in grid


def test_constraint_filters_invalid_combos() -> None:
    """sma_fast.period < sma_slow.period eliminates invalid pairs."""
    ps = ParameterSet("test")
    ps.add("sma_fast", "period", values=[5, 10, 20])
    ps.add("sma_slow", "period", values=[10, 20, 30])
    ps.add_constraint("sma_fast.period < sma_slow.period")
    grid = ps.grid()

    # Total = 3 × 3 = 9
    # Valid: (5,10), (5,20), (5,30), (10,20), (10,30), (20,30) = 6
    assert len(grid) == 6

    # Verify constraint holds for all combos
    for combo in grid:
        assert combo["sma_fast"]["period"] < combo["sma_slow"]["period"]


def test_multiple_constraints() -> None:
    ps = ParameterSet("test")
    ps.add("sma_fast", "period", values=[5, 10, 15, 20])
    ps.add("sma_slow", "period", values=[10, 20, 30, 40])
    ps.add_constraint("sma_fast.period < sma_slow.period")
    ps.add_constraint("sma_slow.period <= 30")
    grid = ps.grid()

    for combo in grid:
        assert combo["sma_fast"]["period"] < combo["sma_slow"]["period"]
        assert combo["sma_slow"]["period"] <= 30


def test_constraint_with_numeric_literal() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[5, 10, 15, 20, 25])
    ps.add_constraint("sma.period >= 10")
    ps.add_constraint("sma.period <= 20")
    grid = ps.grid()
    assert len(grid) == 3  # 10, 15, 20
    for combo in grid:
        assert 10 <= combo["sma"]["period"] <= 20


def test_constraint_eliminates_all_combos() -> None:
    """If all combos violate the constraint, grid is empty."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10, 20])
    ps.add_constraint("sma.period > 100")
    assert ps.grid() == []


def test_add_constraint_validates_format() -> None:
    ps = ParameterSet("test")
    with pytest.raises(ValueError, match="Invalid constraint"):
        ps.add_constraint("this is not valid")


# ---------------------------------------------------------------------------
# ParameterSet — properties
# ---------------------------------------------------------------------------


def test_total_combinations_no_constraints() -> None:
    ps = ParameterSet("test")
    ps.add("a", "x", values=[1, 2, 3])
    ps.add("b", "y", values=[10, 20])
    # 3 × 2 = 6
    assert ps.total_combinations == 6


def test_total_combinations_empty() -> None:
    ps = ParameterSet("empty")
    assert ps.total_combinations == 1


def test_total_combinations_same_component() -> None:
    ps = ParameterSet("test")
    ps.add("bb", "period", values=[10, 20])
    ps.add("bb", "std_dev", values=[1.5, 2.0, 2.5])
    # 2 × 3 = 6 (within same component)
    assert ps.total_combinations == 6


def test_distributions_property() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10, 20])
    dists = ps.distributions
    assert len(dists) == 1
    assert dists[0].component == "sma"
    assert dists[0].param == "period"


def test_constraints_property() -> None:
    ps = ParameterSet("test")
    ps.add("a", "x", values=[1])
    ps.add_constraint("a.x > 0")
    constraints = ps.constraints
    assert len(constraints) == 1
    assert constraints[0].expr == "a.x > 0"


def test_repr() -> None:
    ps = ParameterSet("my_set")
    ps.add("sma", "period", values=[10, 20])
    r = repr(ps)
    assert "my_set" in r
    assert "distributions=1" in r


# ---------------------------------------------------------------------------
# ParameterSet — add converts values to tuple
# ---------------------------------------------------------------------------


def test_add_converts_range_to_tuple() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=range(10, 30, 5))
    dist = ps.distributions[0]
    assert dist.values == (10, 15, 20, 25)
    assert isinstance(dist.values, tuple)


# ---------------------------------------------------------------------------
# ParameterSet — Rule-named components
# ---------------------------------------------------------------------------


def test_rule_named_component_grid() -> None:
    """ParameterSet works with Rule class names as component names."""
    ps = ParameterSet("rule_tuning")
    ps.add("StopLossRule", "threshold", values=[0.03, 0.05, 0.10])
    ps.add("TakeProfitRule", "threshold", values=[0.10, 0.20])
    grid = ps.grid()
    # 3 × 2 = 6
    assert len(grid) == 6
    assert {"StopLossRule": {"threshold": 0.03}, "TakeProfitRule": {"threshold": 0.10}} in grid


def test_mixed_indicator_and_rule_grid() -> None:
    """Grid supports indicator and rule params together with constraints."""
    ps = ParameterSet("mixed")
    ps.add("sma_fast", "period", values=[5, 10, 20])
    ps.add("sma_slow", "period", values=[20, 50])
    ps.add("StopLossRule", "threshold", values=[0.05, 0.10])
    ps.add_constraint("sma_fast.period < sma_slow.period")
    grid = ps.grid()

    # Without constraint: 3 × 2 × 2 = 12
    # Invalid: (20, 20) — 2 combos removed → (3×2 - 1) × 2 = 10
    assert len(grid) == 10
    for combo in grid:
        assert combo["sma_fast"]["period"] < combo["sma_slow"]["period"]


def test_rule_param_single_value() -> None:
    """Single-value grid (just fix a rule param) produces one combo."""
    ps = ParameterSet("fixed")
    ps.add("StopLossRule", "threshold", values=[0.05])
    grid = ps.grid()
    assert len(grid) == 1
    assert grid[0] == {"StopLossRule": {"threshold": 0.05}}


def test_rule_float_values_preserved() -> None:
    """Float precision in rule param values is preserved through grid()."""
    ps = ParameterSet("test")
    ps.add("StopLossRule", "threshold", values=[0.03, 0.05, 0.08])
    grid = ps.grid()
    thresholds = [c["StopLossRule"]["threshold"] for c in grid]
    assert thresholds == [0.03, 0.05, 0.08]


# ---------------------------------------------------------------------------
# ParameterSet — grid ordering
# ---------------------------------------------------------------------------


def test_grid_preserves_value_order() -> None:
    """Grid combinations maintain the order of values as added."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[30, 10, 20])
    grid = ps.grid()
    periods = [c["sma"]["period"] for c in grid]
    assert periods == [30, 10, 20]


def test_grid_three_components_cartesian() -> None:
    """Three components produce correct cartesian product size."""
    ps = ParameterSet("test")
    ps.add("a", "x", values=[1, 2])
    ps.add("b", "y", values=[10, 20, 30])
    ps.add("c", "z", values=[100, 200])
    grid = ps.grid()
    # 2 × 3 × 2 = 12
    assert len(grid) == 12


# ---------------------------------------------------------------------------
# Constraint edge cases
# ---------------------------------------------------------------------------


def test_constraint_both_numeric_literals() -> None:
    """Constraint with two numeric literals (degenerate but valid)."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    ps.add_constraint("5 < 10")
    grid = ps.grid()
    assert len(grid) == 1  # constraint always true


def test_constraint_both_numeric_literals_false() -> None:
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    ps.add_constraint("10 < 5")
    grid = ps.grid()
    assert len(grid) == 0  # constraint always false


def test_distributions_returns_copy() -> None:
    """distributions property returns a copy, not internal list."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    dists = ps.distributions
    dists.clear()
    assert len(ps.distributions) == 1  # internal list unchanged


def test_constraints_returns_copy() -> None:
    """constraints property returns a copy, not internal list."""
    ps = ParameterSet("test")
    ps.add("sma", "period", values=[10])
    ps.add_constraint("sma.period > 0")
    constraints = ps.constraints
    constraints.clear()
    assert len(ps.constraints) == 1
