# -*- coding: utf-8 -*-
"""策略注册中心。

管理策略版本、参数快照与优化历史。

用法:
    registry = StrategyRegistry()
    registry.register("MVP1", "1.0.0", params={"pe_percentile": 30})
    registry.register("MVP1", "1.1.0", params={"pe_percentile": 25})  # 优化后
    latest = registry.get_latest("MVP1")
    history = registry.history("MVP1")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class StrategyVersion:
    """策略版本记录。"""

    name: str
    version: str
    params: dict[str, Any]
    description: str = ""
    parent_version: Optional[str] = None
    optimization_run_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metrics: dict[str, float] = field(default_factory=dict)


class StrategyRegistry:
    """策略注册中心。

    管理所有策略版本，支持注册、查询、对比和持久化。
    """

    def __init__(self, db_path: str = "data/strategy_registry.json"):
        self._path = db_path
        self._memory_only = db_path == ":memory:"
        self._strategies: dict[str, list[StrategyVersion]] = {}
        if not self._memory_only:
            self._load()

    def register(
        self,
        name: str,
        version: str,
        params: dict[str, Any],
        description: str = "",
        parent_version: Optional[str] = None,
        optimization_run_id: Optional[str] = None,
        metrics: Optional[dict[str, float]] = None,
    ) -> StrategyVersion:
        """注册新策略版本。

        Args:
            name: 策略名称，如 "MVP1"
            version: 版本号，如 "1.0.0"
            params: 策略参数字典
            description: 版本描述
            parent_version: 父版本号（进化来源）
            optimization_run_id: 关联的优化运行 ID
            metrics: 回测绩效指标 (sharpe_ratio, max_drawdown 等)

        Returns:
            注册的策略版本对象
        """
        sv = StrategyVersion(
            name=name,
            version=version,
            params=params,
            description=description,
            parent_version=parent_version,
            optimization_run_id=optimization_run_id,
            metrics=metrics or {},
        )

        if name not in self._strategies:
            self._strategies[name] = []

        # 如果同版本已存在则替换
        existing = [i for i, v in enumerate(self._strategies[name]) if v.version == version]
        if existing:
            self._strategies[name][existing[0]] = sv
        else:
            self._strategies[name].append(sv)

        self._save()
        return sv

    def get_latest(self, name: str) -> Optional[StrategyVersion]:
        """获取某策略的最新版本。"""
        versions = self._strategies.get(name, [])
        if not versions:
            return None
        return versions[-1]

    def get_version(self, name: str, version: str) -> Optional[StrategyVersion]:
        """获取指定版本。"""
        for v in self._strategies.get(name, []):
            if v.version == version:
                return v
        return None

    def history(self, name: str) -> list[StrategyVersion]:
        """获取某策略的完整版本历史，按时间排序。"""
        return sorted(self._strategies.get(name, []), key=lambda v: v.created_at)

    def list_strategies(self) -> list[str]:
        """列出所有已注册的策略名称。"""
        return list(self._strategies.keys())

    def compare_versions(
        self, name: str, metric: str = "sharpe_ratio"
    ) -> list[dict]:
        """对比同一策略不同版本在某指标上的表现。

        Returns:
            [{version, params, metric_value}, ...] 按指标降序
        """
        versions = self.history(name)
        result = []
        for v in versions:
            result.append({
                "name": v.name,
                "version": v.version,
                "params": v.params,
                "metric": metric,
                "value": v.metrics.get(metric),
                "created_at": v.created_at,
            })
        result.sort(key=lambda x: x["value"] or float("-inf"), reverse=True)
        return result

    def best_version(self, name: str, metric: str = "sharpe_ratio") -> Optional[StrategyVersion]:
        """获取某指标下最优版本。"""
        compared = self.compare_versions(name, metric)
        if not compared or compared[0]["value"] is None:
            return None
        best = compared[0]
        return self.get_version(name, best["version"])

    def remove_version(self, name: str, version: str):
        """移除指定版本。"""
        if name in self._strategies:
            self._strategies[name] = [
                v for v in self._strategies[name] if v.version != version
            ]
            self._save()

    def export(self, name: str) -> dict:
        """导出某策略的完整数据。"""
        return {
            "name": name,
            "versions": [
                {
                    "version": v.version,
                    "params": v.params,
                    "description": v.description,
                    "parent_version": v.parent_version,
                    "metrics": v.metrics,
                    "created_at": v.created_at,
                }
                for v in self.history(name)
            ],
        }

    def count(self) -> int:
        """总注册版本数。"""
        return sum(len(vs) for vs in self._strategies.values())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        if self._memory_only:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        data = {}
        for name, versions in self._strategies.items():
            data[name] = [
                {
                    "version": v.version,
                    "params": v.params,
                    "description": v.description,
                    "parent_version": v.parent_version,
                    "optimization_run_id": v.optimization_run_id,
                    "metrics": v.metrics,
                    "created_at": v.created_at,
                }
                for v in versions
            ]
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for name, versions in data.items():
            self._strategies[name] = [
                StrategyVersion(
                    name=name,
                    version=v["version"],
                    params=v["params"],
                    description=v.get("description", ""),
                    parent_version=v.get("parent_version"),
                    optimization_run_id=v.get("optimization_run_id"),
                    metrics=v.get("metrics", {}),
                    created_at=v.get("created_at", ""),
                )
                for v in versions
            ]
