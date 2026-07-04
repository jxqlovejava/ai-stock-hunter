"""Plan 027 (xquant-studio): the consumers in oxq/tools/strategy.py must
read from the live registry on every call, not from a module-level
snapshot taken at import time. A snapshot would hide any indicator,
signal, optimizer, or rule registered after import — which is exactly
what xquant-studio's component_create does at runtime.

These tests pin the invariant for indicators (the path where the bug
was first observed in xquant-studio session 2d5e93eb). The patch in
strategy.py replaces every snapshot reference with a live `list_*()`
call uniformly across all four slots, so the indicator coverage here
is sufficient evidence that the pattern is right.

Ref: xquant-studio/docs/plans/2026-04-07-027-impl-component-create-registration-visibility.md
"""

from __future__ import annotations

import pandas as pd
import pytest

from oxq.core.registry import register_indicator
from oxq.tools import session
from oxq.tools.strategy import (
    indicator_describe,
    indicator_list,
    strategy_add_signal,
    strategy_create,
)


@pytest.fixture(autouse=True)
def _reset_session():
    session.clear()


class _MockBetaInd:
    """A minimal Indicator-shape class registered AFTER strategy.py import."""

    name = "Plan027MockBeta"
    formula = "beta"

    def compute(self, mktdata, period: int = 60, **p):  # noqa: D401
        return pd.Series([0.0] * len(mktdata))


def test_indicator_list_reflects_post_import_registration():
    """A post-import register_indicator() must be visible to indicator_list()."""
    register_indicator(_MockBetaInd)
    names = {ind["name"] for ind in indicator_list()["indicators"]}
    assert "Plan027MockBeta" in names, sorted(names)


def test_indicator_describe_reflects_post_import_registration():
    """indicator_describe() must resolve a post-import indicator."""
    register_indicator(_MockBetaInd)
    out = indicator_describe(type="Plan027MockBeta")
    assert "error" not in out, out
    assert out["name"] == "Plan027MockBeta"
    assert "period" in out["params"]


def test_strategy_add_signal_resolves_post_import_indicator():
    """The composition path: _build_required_indicators must accept a
    post-import indicator type. This is the exact code path that produced
    "Unknown indicator type 'RollingBeta'" in xquant-studio session 2d5e93eb,
    row 392."""
    register_indicator(_MockBetaInd)

    create_result = strategy_create(
        name="t027",
        hypothesis="post-import indicator must resolve",
        objectives={"sharpe": {"min": 0.0}},
    )
    assert "error" not in create_result, create_result

    result = strategy_add_signal(
        strategy="t027",
        name="probe",
        type="Threshold",
        params={"column": "beta_col", "threshold": 0, "direction": "above"},
        indicators={
            "beta_col": {"type": "Plan027MockBeta", "params": {"period": 60}},
        },
    )
    assert "error" not in result, result
    assert result["signal"] == "probe"


def test_strategy_inspect_output_is_json_safe():
    """Plan 035 (xquant-studio wall #8): strategy_inspect must NEVER
    return live Indicator instances or raw `(instance, params)` tuples
    in any nested params dict. The cleaned shape is already surfaced
    under the separate `indicators` key; the raw shape under
    `params.required_indicators` was leaking into JSON consumers and
    crashing SQLAlchemy autoflush."""
    import json
    from oxq.tools.strategy import (
        strategy_add_rule,
        strategy_add_signal,
        strategy_create,
        strategy_inspect,
        strategy_set_portfolio,
        strategy_set_universe,
    )

    register_indicator(_MockBetaInd)

    strategy_create(
        name="ji_strat",
        hypothesis="json safety",
        objectives={"sharpe": {"min": 0.0}},
    )
    strategy_set_universe(
        strategy="ji_strat", type="static", symbols=["AAA", "BBB"]
    )
    strategy_add_signal(
        strategy="ji_strat",
        name="sig",
        type="Threshold",
        params={"column": "x", "threshold": 0, "direction": "above"},
        indicators={"x": {"type": "Plan027MockBeta", "params": {"period": 60}}},
    )
    # TopNRanking with indicators — the wall #8 path.
    strategy_set_portfolio(
        strategy="ji_strat",
        type="TopNRanking",
        params={"score_col": "x", "n": 1},
        indicators={"x": {"type": "Plan027MockBeta", "params": {"period": 60}}},
    )
    strategy_add_rule(
        strategy="ji_strat",
        name="rebal",
        type="RebalanceFrequencyRule",
        params={"interval_days": 5},
    )

    out = strategy_inspect(strategy="ji_strat")
    assert "error" not in out, out

    # Must round-trip through JSON without raising.
    blob = json.dumps(out, default=str)
    parsed = json.loads(blob)

    # And no raw object addresses anywhere.
    assert "object at 0x" not in blob, blob

    # The portfolio's params dict must NOT contain required_indicators
    # (the cleaned version lives under portfolio.indicators).
    portfolio = parsed.get("portfolio", {})
    portfolio_params = portfolio.get("params", {})
    assert "required_indicators" not in portfolio_params, (
        f"portfolio.params still leaks required_indicators: {portfolio_params}"
    )

    # Same for any rule.
    for rule in parsed.get("rules", []):
        rule_params = rule.get("params", {})
        assert "required_indicators" not in rule_params, (
            f"rule.params still leaks required_indicators: {rule_params}"
        )
