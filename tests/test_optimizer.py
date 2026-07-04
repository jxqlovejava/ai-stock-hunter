# -*- coding: utf-8 -*-
"""回测优化器、策略注册与对比模块测试。"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.backtest.engine import BacktestEngine, BacktestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_result(**overrides) -> BacktestResult:
    defaults = {
        "strategy_name": "MVP1",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_cash": 1_000_000,
        "final_value": 1_500_000,
        "total_return": 0.50,
        "annual_return": 0.085,
        "sharpe_ratio": 0.80,
        "max_drawdown": -0.25,
        "win_rate": 0.55,
        "total_trades": 200,
    }
    defaults.update(overrides)
    return BacktestResult(**defaults)


def _make_engine_with_dummy_data():
    """创建带假数据的 BacktestEngine。"""
    import pandas as pd
    import numpy as np
    import backtrader as bt

    dates = pd.date_range("2020-01-01", "2024-12-31", freq="B")
    n = len(dates)
    np.random.seed(42)
    close = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.015, n))

    df = pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    }, index=dates)

    engine = BacktestEngine(initial_cash=1_000_000)
    engine.add_data("TEST001", df, pe_percentile=25, roe=15.0, northbound=1)
    return engine


# ---------------------------------------------------------------------------
# GridSearchOptimizer
# ---------------------------------------------------------------------------


class TestGridSearchOptimizer:
    def test_create_optimizer(self):
        from src.backtest.optimizer import GridSearchOptimizer
        opt = GridSearchOptimizer(_make_engine_with_dummy_data)
        assert opt is not None

    def test_optimize_small_grid(self):
        from src.backtest.optimizer import GridSearchOptimizer
        from src.backtest.mvp1_strategy import MVP1Strategy

        opt = GridSearchOptimizer(_make_engine_with_dummy_data, MVP1Strategy)
        grid = {
            "pe_percentile": [30, 40],
            "roe_threshold": [10.0, 15.0],
        }
        result = opt.optimize(grid, "2020-01-01", "2024-12-31")
        assert result.search_method == "grid"
        assert result.target_metric == "sharpe_ratio"
        assert len(result.best_params) == 2
        assert "pe_percentile" in result.best_params
        assert len(result.all_results) >= 1

    def test_optimize_targets_max_drawdown(self):
        from src.backtest.optimizer import GridSearchOptimizer
        from src.backtest.mvp1_strategy import MVP1Strategy

        opt = GridSearchOptimizer(_make_engine_with_dummy_data, MVP1Strategy)
        grid = {"pe_percentile": [30], "stop_loss_pct": [-0.10]}
        result = opt.optimize(grid, "2020-01-01", "2024-12-31", target_metric="max_drawdown")
        assert result.target_metric == "max_drawdown"
        assert len(result.best_params) >= 1

    def test_invalid_metric_raises(self):
        from src.backtest.optimizer import GridSearchOptimizer
        opt = GridSearchOptimizer(_make_engine_with_dummy_data)
        with pytest.raises(ValueError, match="不支持的优化指标"):
            opt.optimize({"pe_percentile": [30]}, "2020-01-01", "2024-12-31", target_metric="invalid")

    def test_save_and_load(self):
        from src.backtest.optimizer import GridSearchOptimizer, OptimizationResult
        result = OptimizationResult(
            best_params={"pe_percentile": 30},
            best_score=0.8,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "opt_result.json")
            GridSearchOptimizer(_make_engine_with_dummy_data).save(result, path)
            loaded = GridSearchOptimizer.load(path)
            assert loaded["best_params"] == {"pe_percentile": 30}
            assert loaded["best_score"] == 0.8

    def test_optimization_result_to_dict(self):
        from src.backtest.optimizer import OptimizationResult
        r = OptimizationResult(
            best_params={"a": 1},
            best_score=0.9,
            best_result=_dummy_result(),
            target_metric="sharpe_ratio",
        )
        d = r.to_dict()
        assert d["best_params"] == {"a": 1}
        assert d["best_result"] is not None
        assert d["best_result"]["sharpe_ratio"] == 0.80


# ---------------------------------------------------------------------------
# BayesianOptimizer
# ---------------------------------------------------------------------------


class TestBayesianOptimizer:
    def test_create_optimizer(self):
        from src.backtest.optimizer import BayesianOptimizer
        opt = BayesianOptimizer(_make_engine_with_dummy_data, n_calls=5)
        assert opt._n_calls == 5

    def test_optimize_basic(self):
        pytest.importorskip("skopt")
        from src.backtest.optimizer import BayesianOptimizer
        from src.backtest.mvp1_strategy import MVP1Strategy
        from skopt.space import Real, Integer

        opt = BayesianOptimizer(
            _make_engine_with_dummy_data, MVP1Strategy, n_calls=5, n_initial_points=3
        )
        space = [
            Integer(20, 50, name="pe_percentile"),
            Real(5.0, 20.0, name="roe_threshold"),
            Real(-0.25, -0.05, name="stop_loss_pct"),
        ]
        result = opt.optimize(space, "2020-01-01", "2024-12-31")
        assert result.search_method == "bayesian"
        assert len(result.best_params) == 3

    def test_optimize_errors_handled(self):
        pytest.importorskip("skopt")
        from src.backtest.optimizer import BayesianOptimizer
        from src.backtest.mvp1_strategy import MVP1Strategy
        from skopt.space import Real

        opt = BayesianOptimizer(
            _make_engine_with_dummy_data, MVP1Strategy, n_calls=5
        )
        space = [Real(5.0, 20.0, name="roe_threshold")]
        result = opt.optimize(space, "2020-01-01", "2024-12-31")
        assert result.search_method == "bayesian"


# ---------------------------------------------------------------------------
# StrategyRegistry
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_register_and_get(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")  # won't persist
        sv = reg.register("MVP1", "1.0.0", {"pe_percentile": 30})
        assert sv.name == "MVP1"
        assert sv.params["pe_percentile"] == 30

        retrieved = reg.get_latest("MVP1")
        assert retrieved is not None
        assert retrieved.version == "1.0.0"

    def test_multiple_versions(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "1.0.0", {"pe": 30}, metrics={"sharpe": 0.8})
        reg.register("MVP1", "1.1.0", {"pe": 25}, metrics={"sharpe": 1.0})
        reg.register("MVP1", "1.0.1", {"pe": 28}, metrics={"sharpe": 0.9})

        latest = reg.get_latest("MVP1")
        assert latest.version == "1.0.1"

        history = reg.history("MVP1")
        assert len(history) == 3

    def test_compare_versions(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "v1", {"pe": 30}, metrics={"sharpe_ratio": 0.8})
        reg.register("MVP1", "v2", {"pe": 25}, metrics={"sharpe_ratio": 1.2})
        reg.register("MVP1", "v3", {"pe": 20}, metrics={"sharpe_ratio": 0.6})

        compared = reg.compare_versions("MVP1", "sharpe_ratio")
        assert compared[0]["version"] == "v2"  # highest sharpe
        assert compared[0]["value"] == 1.2

    def test_best_version(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "v1", {}, metrics={"sharpe_ratio": 0.5})
        reg.register("MVP1", "v2", {}, metrics={"sharpe_ratio": 1.5})

        best = reg.best_version("MVP1", "sharpe_ratio")
        assert best is not None
        assert best.version == "v2"

    def test_list_strategies(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "1.0.0", {})
        reg.register("MVP2", "1.0.0", {})
        assert "MVP1" in reg.list_strategies()
        assert "MVP2" in reg.list_strategies()

    def test_remove_version(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "v1", {})
        reg.register("MVP1", "v2", {})
        reg.remove_version("MVP1", "v1")
        assert len(reg.history("MVP1")) == 1
        assert reg.history("MVP1")[0].version == "v2"

    def test_export(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        reg.register("MVP1", "1.0.0", {"pe": 30}, description="初始版本")
        data = reg.export("MVP1")
        assert data["name"] == "MVP1"
        assert len(data["versions"]) == 1
        assert data["versions"][0]["params"] == {"pe": 30}

    def test_count(self):
        from src.backtest.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(db_path=":memory:")
        assert reg.count() == 0
        reg.register("A", "1", {})
        reg.register("B", "1", {})
        reg.register("A", "2", {})
        assert reg.count() == 3

    def test_persistence(self):
        from src.backtest.strategy_registry import StrategyRegistry
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            reg1 = StrategyRegistry(db_path=path)
            reg1.register("MVP1", "1.0.0", {"pe": 30}, metrics={"sharpe": 0.8})

            reg2 = StrategyRegistry(db_path=path)
            latest = reg2.get_latest("MVP1")
            assert latest is not None
            assert latest.params["pe"] == 30
            assert latest.metrics["sharpe"] == 0.8


# ---------------------------------------------------------------------------
# StrategyComparator
# ---------------------------------------------------------------------------


class TestStrategyComparator:
    def test_compare_basic(self):
        from src.backtest.comparator import StrategyComparator
        results = {
            "MVP1_v1.0": _dummy_result(strategy_name="MVP1_v1.0", sharpe_ratio=0.8),
            "MVP1_v1.1": _dummy_result(strategy_name="MVP1_v1.1", sharpe_ratio=1.2),
            "MVP2_v1.0": _dummy_result(strategy_name="MVP2_v1.0", sharpe_ratio=0.6),
        }
        comparator = StrategyComparator()
        rankings = comparator.compare(results)
        assert len(rankings) == 3
        assert rankings[0].name == "MVP1_v1.1"  # highest sharpe → rank 1
        assert rankings[0].rank == 1

    def test_compare_empty(self):
        from src.backtest.comparator import StrategyComparator
        assert StrategyComparator().compare({}) == []

    def test_report(self):
        from src.backtest.comparator import StrategyComparator
        results = {
            "MVP1": _dummy_result(sharpe_ratio=1.0),
        }
        report = StrategyComparator().report(StrategyComparator().compare(results))
        assert "策略横向对比报告" in report
        assert "MVP1" in report
        assert "🏆" in report

    def test_find_best(self):
        from src.backtest.comparator import StrategyComparator
        results = {
            "A": _dummy_result(sharpe_ratio=0.5, strategy_name="A"),
            "B": _dummy_result(sharpe_ratio=1.5, strategy_name="B"),
        }
        best = StrategyComparator().find_best(results)
        assert best is not None
        assert best.name == "B"

    def test_compare_metric(self):
        from src.backtest.comparator import StrategyComparator
        results = {
            "A": _dummy_result(max_drawdown=-0.10, strategy_name="A"),
            "B": _dummy_result(max_drawdown=-0.40, strategy_name="B"),
            "C": _dummy_result(max_drawdown=-0.25, strategy_name="C"),
        }
        ranked = StrategyComparator().compare_metric(results, "max_drawdown")
        # 回撤越小越好 → A (-0.10) 最好
        assert ranked[0][0] == "A"
        assert ranked[-1][0] == "B"

    def test_composite_score_weights(self):
        from src.backtest.comparator import StrategyComparator
        total_weight = sum(StrategyComparator.WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.01, "权重之和应为 1.0"
