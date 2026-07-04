# -*- coding: utf-8 -*-
"""回测参数优化器。

提供两种优化策略:
  - GridSearchOptimizer: 参数网格搜索，适合粗粒度探索
  - BayesianOptimizer: 基于高斯过程的贝叶斯优化，适合精细调优

优化目标默认为 Sharpe 比率，可自定义为 max_drawdown / win_rate 等。

用法:
    optimizer = GridSearchOptimizer(engine_factory)
    result = optimizer.optimize(param_grid, train_start, train_end)
    print(f"最优参数: {result.best_params}, Sharpe: {result.best_score:.2f}")
"""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .engine import BacktestEngine, BacktestResult


@dataclass
class OptimizationResult:
    """单次优化结果。"""

    best_params: dict[str, Any]
    best_score: float
    best_result: Optional[BacktestResult] = None
    all_results: list[dict] = field(default_factory=list)
    search_space: dict[str, list] = field(default_factory=dict)
    search_method: str = "grid"
    target_metric: str = "sharpe_ratio"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "best_params": self.best_params,
            "best_score": self.best_score,
            "best_result": self._result_to_dict(self.best_result),
            "all_results": self.all_results,
            "search_method": self.search_method,
            "target_metric": self.target_metric,
            "created_at": self.created_at,
        }

    @staticmethod
    def _result_to_dict(r: Optional[BacktestResult]) -> Optional[dict]:
        if r is None:
            return None
        return {
            "strategy_name": r.strategy_name,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "total_return": r.total_return,
            "annual_return": r.annual_return,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "total_trades": r.total_trades,
        }


class GridSearchOptimizer:
    """网格搜索参数优化器。

    遍历所有参数组合，返回使目标指标最优的参数。

    用法:
        def make_engine():
            engine = BacktestEngine(initial_cash=1_000_000)
            engine.add_data("600519", df)
            return engine

        opt = GridSearchOptimizer(make_engine)
        grid = {
            "pe_percentile": [20, 30, 40],
            "roe_threshold": [10.0, 12.0, 15.0],
            "stop_loss_pct": [-0.10, -0.15, -0.20],
        }
        result = opt.optimize(grid, "2015-01-01", "2022-12-31")
    """

    # 指标越大越好 → True；越小越好 → False
    DIRECTION: dict[str, bool] = {
        "sharpe_ratio": True,
        "total_return": True,
        "annual_return": True,
        "win_rate": True,
        "final_value": True,
        "max_drawdown": False,
    }

    def __init__(
        self,
        engine_factory: Callable[[], BacktestEngine],
        strategy_cls: Optional[type] = None,
    ):
        """初始化优化器。

        Args:
            engine_factory: 无参可调用对象，每次调用返回一个新的 BacktestEngine。
                            engine 应已完成 add_data()。
            strategy_cls: 策略类。如果 engine_factory 未注册策略，则在此注册。
        """
        self._engine_factory = engine_factory
        self._strategy_cls = strategy_cls

    def optimize(
        self,
        param_grid: dict[str, list],
        start: str,
        end: str,
        target_metric: str = "sharpe_ratio",
        validate_start: Optional[str] = None,
        validate_end: Optional[str] = None,
    ) -> OptimizationResult:
        """执行网格搜索优化。

        Args:
            param_grid: 参数名 → 候选值列表，如 {"pe_percentile": [20, 30, 40]}
            start: 训练期起始日
            end: 训练期结束日
            target_metric: 优化目标指标，默认 sharpe_ratio
            validate_start: 验证期起始日（可选），用于检测过拟合
            validate_end: 验证期结束日（可选）

        Returns:
            OptimizationResult 含最优参数和完整搜索记录
        """
        if target_metric not in self.DIRECTION:
            raise ValueError(f"不支持的优化指标: {target_metric}，可选: {list(self.DIRECTION)}")

        maximize = self.DIRECTION[target_metric]
        keys = list(param_grid.keys())
        value_lists = [param_grid[k] for k in keys]

        all_results: list[dict] = []
        best_score = float("-inf") if maximize else float("inf")
        best_params: dict[str, Any] = {}
        best_result: Optional[BacktestResult] = None

        total_combos = 1
        for vl in value_lists:
            total_combos *= len(vl)

        for idx, values in enumerate(itertools.product(*value_lists)):
            params = dict(zip(keys, values))

            # 构建引擎并回测
            engine = self._engine_factory()
            if self._strategy_cls is not None:
                engine.add_strategy(self._strategy_cls, **params)

            try:
                result = engine.run(start, end)
            except Exception as e:
                all_results.append({
                    "params": params,
                    "error": str(e),
                    "score": None,
                    "combo": idx + 1,
                    "total": total_combos,
                })
                continue

            score = getattr(result, target_metric, 0) or 0
            all_results.append({
                "params": params,
                "score": score,
                "result": OptimizationResult._result_to_dict(result),
                "combo": idx + 1,
                "total": total_combos,
            })

            improved = (maximize and score > best_score) or (not maximize and score < best_score)
            if improved:
                best_score = score
                best_params = params
                best_result = result

        # 验证期回测（如果指定了验证期）
        if validate_start and validate_end and best_params:
            engine = self._engine_factory()
            if self._strategy_cls is not None:
                engine.add_strategy(self._strategy_cls, **best_params)
            try:
                validate_result = engine.run(validate_start, validate_end)
                all_results.append({
                    "phase": "validation",
                    "params": best_params,
                    "score": getattr(validate_result, target_metric, 0) or 0,
                    "result": OptimizationResult._result_to_dict(validate_result),
                })
            except Exception:
                pass

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            best_result=best_result,
            all_results=all_results,
            search_space={k: list(v) for k, v in param_grid.items()},
            search_method="grid",
            target_metric=target_metric,
        )

    def save(self, result: OptimizationResult, path: str):
        """保存优化结果到 JSON 文件。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load(path: str) -> dict:
        """从 JSON 文件加载优化结果。"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


class BayesianOptimizer:
    """贝叶斯参数优化器。

    使用高斯过程（Gaussian Process）在连续参数空间中搜索。
    适合参数空间较大时，比网格搜索更高效。

    依赖: scikit-optimize (pip install scikit-optimize)

    用法:
        opt = BayesianOptimizer(make_engine, n_calls=30)
        result = opt.optimize(param_space, "2015-01-01", "2022-12-31")
    """

    def __init__(
        self,
        engine_factory: Callable[[], BacktestEngine],
        strategy_cls: Optional[type] = None,
        n_calls: int = 25,
        n_initial_points: int = 5,
        random_state: int = 42,
    ):
        self._engine_factory = engine_factory
        self._strategy_cls = strategy_cls
        self._n_calls = n_calls
        self._n_initial_points = n_initial_points
        self._random_state = random_state
        self._target_metric = "sharpe_ratio"

    def optimize(
        self,
        param_space: list,
        start: str,
        end: str,
        target_metric: str = "sharpe_ratio",
    ) -> OptimizationResult:
        """执行贝叶斯优化。

        Args:
            param_space: skopt 参数空间列表，如:
                [Real(10, 50, name="pe_percentile"),
                 Real(5.0, 20.0, name="roe_threshold"),
                 Real(-0.25, -0.05, name="stop_loss_pct")]
            start: 训练期起始日
            end: 训练期结束日
            target_metric: 优化目标指标

        Returns:
            OptimizationResult
        """
        try:
            from skopt import Optimizer as SkOptimizer
            from skopt.space import Real, Integer, Categorical
        except ImportError:
            raise ImportError(
                "贝叶斯优化需要 scikit-optimize。请运行: pip install scikit-optimize"
            )

        if target_metric not in GridSearchOptimizer.DIRECTION:
            raise ValueError(f"不支持的优化指标: {target_metric}")

        self._target_metric = target_metric
        maximize = GridSearchOptimizer.DIRECTION[target_metric]
        sign = 1 if maximize else -1

        opt = SkOptimizer(
            dimensions=param_space,
            random_state=self._random_state,
            n_initial_points=self._n_initial_points,
        )

        all_results: list[dict] = []
        best_score = float("-inf")
        best_params: dict[str, Any] = {}
        best_result: Optional[BacktestResult] = None

        for i in range(self._n_calls):
            try:
                suggested = opt.ask()
            except Exception:
                break

            params = {}
            for dim, val in zip(param_space, suggested):
                params[dim.name] = val

            engine = self._engine_factory()
            if self._strategy_cls is not None:
                engine.add_strategy(self._strategy_cls, **params)

            try:
                result = engine.run(start, end)
            except Exception as e:
                all_results.append({
                    "iteration": i + 1,
                    "params": params,
                    "error": str(e),
                    "score": None,
                })
                opt.tell(suggested, float("-inf"))
                continue

            score = getattr(result, target_metric, 0) or 0
            objective = sign * score
            opt.tell(suggested, objective)

            all_results.append({
                "iteration": i + 1,
                "params": params,
                "score": score,
                "result": OptimizationResult._result_to_dict(result),
                "total": self._n_calls,
            })

            if score > best_score:
                best_score = score
                best_params = params
                best_result = result

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            best_result=best_result,
            all_results=all_results,
            search_space={
                d.name: f"{type(d).__name__}({getattr(d, 'low', '?')}, {getattr(d, 'high', '?')})"
                for d in param_space
            },
            search_method="bayesian",
            target_metric=target_metric,
        )
