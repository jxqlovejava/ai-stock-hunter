"""Shared pytest fixtures for the open-xquant test suite.

Plan 027: an autouse fixture snapshots the four core registries before
each test and restores them after. Without this, any test that calls
register_indicator/register_signal/register_rule/register_portfolio_optimizer
leaks state into subsequent tests. That latent pollution was hidden as
long as oxq.tools.strategy used a module-level snapshot of each
registry (taken at import time, before any test ran). Plan 027 made
strategy.py read live state per call, surfacing the pollution. Cleaning
it up at the source is the right fix.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restore_oxq_registries():
    """Snapshot the four core registries before the test, restore after."""
    from oxq.core import registry as _r

    snapshots = {
        "_INDICATOR_REGISTRY": dict(_r._INDICATOR_REGISTRY),
        "_SIGNAL_REGISTRY": dict(_r._SIGNAL_REGISTRY),
        "_PORTFOLIO_OPTIMIZER_REGISTRY": dict(_r._PORTFOLIO_OPTIMIZER_REGISTRY),
        "_RULE_REGISTRY": dict(_r._RULE_REGISTRY),
    }
    try:
        yield
    finally:
        _r._INDICATOR_REGISTRY.clear()
        _r._INDICATOR_REGISTRY.update(snapshots["_INDICATOR_REGISTRY"])
        _r._SIGNAL_REGISTRY.clear()
        _r._SIGNAL_REGISTRY.update(snapshots["_SIGNAL_REGISTRY"])
        _r._PORTFOLIO_OPTIMIZER_REGISTRY.clear()
        _r._PORTFOLIO_OPTIMIZER_REGISTRY.update(snapshots["_PORTFOLIO_OPTIMIZER_REGISTRY"])
        _r._RULE_REGISTRY.clear()
        _r._RULE_REGISTRY.update(snapshots["_RULE_REGISTRY"])
