"""Parameter space definition for optimization."""

from __future__ import annotations

import itertools
import operator
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParamDistribution:
    """Single parameter's search space.

    Attributes
    ----------
    component : str
        Indicator or signal name (e.g. ``"sma_fast"``).
    param : str
        Parameter name (e.g. ``"period"``).
    values : tuple
        Allowed values for grid search.
    """

    component: str
    param: str
    values: tuple


@dataclass(frozen=True)
class ParamConstraint:
    """Constraint between parameters.

    Attributes
    ----------
    expr : str
        Constraint expression, e.g. ``"sma_fast.period < sma_slow.period"``.
        Supported operators: ``<``, ``>``, ``<=``, ``>=``, ``==``, ``!=``.
        Operands are ``component.param`` references or numeric literals.
    """

    expr: str


# Supported comparison operators
_OPS = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

# Pattern: operand  operator  operand
# operand is either component.param or a numeric literal
_CONSTRAINT_RE = re.compile(
    r"^\s*(\w+\.\w+|\d+(?:\.\d+)?)\s*"
    r"([<>!=]=?)\s*"
    r"(\w+\.\w+|\d+(?:\.\d+)?)\s*$"
)


def _resolve_operand(token: str, combo: dict[str, dict[str, Any]]) -> float:
    """Resolve a constraint operand to a numeric value."""
    if "." in token and not token.replace(".", "").isdigit():
        component, param = token.split(".", 1)
        return float(combo[component][param])
    return float(token)


def _check_constraint(expr: str, combo: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a constraint expression against a parameter combination."""
    m = _CONSTRAINT_RE.match(expr)
    if m is None:
        msg = (
            f"Invalid constraint expression: {expr!r}. "
            "Expected format: 'component.param op component.param' "
            "where op is one of <, >, <=, >=, ==, !="
        )
        raise ValueError(msg)
    left_token, op_str, right_token = m.groups()
    left = _resolve_operand(left_token, combo)
    right = _resolve_operand(right_token, combo)
    return _OPS[op_str](left, right)


class ParameterSet:
    """Defines the parameter search space for optimization.

    Example::

        paramset = ParameterSet("sma_tuning")
        paramset.add("sma_fast", "period", values=range(5, 30, 5))
        paramset.add("sma_slow", "period", values=range(20, 100, 10))
        paramset.add_constraint("sma_fast.period < sma_slow.period")

        for combo in paramset.grid():
            print(combo)
            # {"sma_fast": {"period": 5}, "sma_slow": {"period": 20}}
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._distributions: list[ParamDistribution] = []
        self._constraints: list[ParamConstraint] = []

    def add(
        self,
        component: str,
        param: str,
        values: Sequence,
    ) -> None:
        """Add a parameter distribution.

        Parameters
        ----------
        component : str
            Indicator or signal name in the strategy (e.g. ``"sma_fast"``).
        param : str
            The parameter name (e.g. ``"period"``).
        values : Sequence
            Allowed values to search over.
        """
        self._distributions.append(
            ParamDistribution(
                component=component,
                param=param,
                values=tuple(values),
            )
        )

    def add_constraint(self, expr: str) -> None:
        """Add a constraint between parameters.

        Parameters
        ----------
        expr : str
            Constraint expression.
            Supported operators: ``<``, ``>``, ``<=``, ``>=``, ``==``, ``!=``.

            Example: ``"sma_fast.period < sma_slow.period"``
        """
        # Validate expression format eagerly
        if _CONSTRAINT_RE.match(expr) is None:
            msg = (
                f"Invalid constraint expression: {expr!r}. "
                "Expected format: 'component.param op component.param'"
            )
            raise ValueError(msg)
        self._constraints.append(ParamConstraint(expr=expr))

    def grid(self) -> list[dict[str, dict[str, Any]]]:
        """Generate all valid parameter combinations.

        Returns a list of dicts, each mapping component name to a dict
        of param values. Constraints are applied to filter out invalid
        combinations.

        Returns
        -------
        list[dict[str, dict[str, Any]]]
            Each element: ``{"sma_fast": {"period": 10}, "sma_slow": {"period": 50}}``.
        """
        if not self._distributions:
            return [{}]

        # Group distributions by component
        by_component: dict[str, list[ParamDistribution]] = {}
        for dist in self._distributions:
            by_component.setdefault(dist.component, []).append(dist)

        # Build per-component param grids
        component_grids: dict[str, list[dict[str, Any]]] = {}
        for comp, dists in by_component.items():
            param_names = [d.param for d in dists]
            param_values = [d.values for d in dists]
            component_grids[comp] = [
                dict(zip(param_names, vals))
                for vals in itertools.product(*param_values)
            ]

        # Cartesian product across components
        comp_names = list(component_grids.keys())
        comp_value_lists = [component_grids[c] for c in comp_names]

        result = []
        for combo_tuple in itertools.product(*comp_value_lists):
            combo = dict(zip(comp_names, combo_tuple))
            # Apply constraints
            if all(
                _check_constraint(c.expr, combo) for c in self._constraints
            ):
                result.append(combo)

        return result

    @property
    def total_combinations(self) -> int:
        """Total combinations before constraint filtering."""
        if not self._distributions:
            return 1
        by_component: dict[str, list[ParamDistribution]] = {}
        for dist in self._distributions:
            by_component.setdefault(dist.component, []).append(dist)
        total = 1
        for dists in by_component.values():
            comp_size = 1
            for d in dists:
                comp_size *= len(d.values)
            total *= comp_size
        return total

    @property
    def distributions(self) -> list[ParamDistribution]:
        """All registered parameter distributions."""
        return list(self._distributions)

    @property
    def constraints(self) -> list[ParamConstraint]:
        """All registered constraints."""
        return list(self._constraints)

    def __repr__(self) -> str:
        n_valid = len(self.grid())
        return (
            f"ParameterSet({self.name!r}, "
            f"distributions={len(self._distributions)}, "
            f"constraints={len(self._constraints)}, "
            f"valid_combinations={n_valid})"
        )
