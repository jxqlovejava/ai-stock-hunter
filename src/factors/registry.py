# -*- coding: utf-8 -*-
"""Alpha 注册表。

借鉴 Vibe-Trading agent/src/factors/registry.py：扫描 src/factors/zoo，
懒加载 alpha 模块，校验 __alpha_meta__，计算时附加 SourceCitation。
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.data.source_citation import NATURE_INTERPRETATION, make_citation
from src.factors.base import AlphaCompute

logger = logging.getLogger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_ZOO_PATH = _PACKAGE_ROOT / "zoo"


class AlphaMeta(BaseModel):
    """Alpha 元数据，每个 alpha 模块顶部必须定义 __alpha_meta__。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    nickname: str = ""
    category: str = ""
    description: str = ""
    columns_required: list[str] = Field(default_factory=list)
    extras_required: list[str] = Field(default_factory=list)
    frequency: list[str] = Field(default_factory=lambda: ["daily"])
    min_warmup_bars: int = Field(default=1, ge=0)
    provider_confidence: float = Field(default=0.75, ge=0.0, le=1.0)


@dataclass(frozen=True)
class Alpha:
    """Alpha 句柄。"""

    id: str
    meta: AlphaMeta
    module_path: str
    compute_fn: Optional[Callable[[dict[str, pd.DataFrame]], pd.DataFrame]] = None


class SkipAlpha(Exception):
    """缺少必要输入时跳过该 alpha。"""


class Registry:
    """Alpha 注册表。扫描 zoo 目录，按需加载计算函数。"""

    def __init__(self, zoo_path: Path | str | None = None):
        self._zoo_path = Path(zoo_path) if zoo_path else _ZOO_PATH
        self._alphas: dict[str, Alpha] = {}
        self._scan()

    def _scan(self) -> None:
        if not self._zoo_path.exists():
            return
        for py_file in self._zoo_path.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self._try_register(py_file)

    def _try_register(self, py_file: Path) -> None:
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            return
        # 通过 AST 提取 __alpha_meta__，避免导入副作用
        meta_dict = self._extract_meta(text)
        if meta_dict is None:
            return
        try:
            meta = AlphaMeta(**meta_dict)
        except ValidationError as exc:
            logger.debug("invalid alpha meta in %s: %s", py_file, exc)
            return

        module_path = self._path_to_module(py_file)
        self._alphas[meta.id] = Alpha(
            id=meta.id,
            meta=meta,
            module_path=module_path,
        )

    @staticmethod
    def _extract_meta(text: str) -> Optional[dict[str, Any]]:
        import ast

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__alpha_meta__":
                        try:
                            return ast.literal_eval(node.value)
                        except Exception:
                            return None
        return None

    def _path_to_module(self, py_file: Path) -> str:
        repo_root = _PACKAGE_ROOT.parent.parent
        rel = py_file.relative_to(repo_root)
        return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")

    def list(self) -> list[str]:
        return sorted(self._alphas.keys())

    def get(self, alpha_id: str) -> Alpha:
        if alpha_id not in self._alphas:
            raise KeyError(f"Alpha not found: {alpha_id}")
        return self._alphas[alpha_id]

    def _load_compute(self, alpha: Alpha) -> Callable[[dict[str, pd.DataFrame]], pd.DataFrame]:
        if alpha.compute_fn is not None:
            return alpha.compute_fn
        module = importlib.import_module(alpha.module_path)
        fn = getattr(module, "compute", None)
        if fn is None or not callable(fn):
            raise RuntimeError(f"Alpha {alpha.id} has no compute() function")
        # 回填句柄，避免重复导入
        object.__setattr__(alpha, "compute_fn", fn)
        return fn

    def compute(self, alpha_id: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """运行指定 alpha，返回宽面板结果并附加 citation。"""
        alpha = self.get(alpha_id)
        meta = alpha.meta

        missing = [c for c in meta.columns_required if c not in panel]
        if missing:
            raise SkipAlpha(
                f"Alpha {alpha_id} missing required columns: {missing}"
            )

        fn = self._load_compute(alpha)
        result = fn(panel)
        result = self._validate_output(alpha_id, result, panel)

        # 附加来源引用：因子是解释性质，confidence 受数据质量和 meta 影响
        input_citations = [
            panel[c].attrs.get("source_citation")
            for c in meta.columns_required
            if "source_citation" in panel[c].attrs
        ]
        base_confidence = meta.provider_confidence
        if input_citations:
            base_confidence = min(base_confidence, min(c.confidence for c in input_citations))

        citation = make_citation(
            provider="factor_registry",
            field=alpha_id,
            data_type="factor",
            confidence=base_confidence,
            nature=NATURE_INTERPRETATION,
        )
        result.attrs["source_citation"] = citation
        return result

    @staticmethod
    def _validate_output(
        alpha_id: str,
        result: pd.DataFrame,
        panel: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        if not isinstance(result, pd.DataFrame):
            raise ValueError(f"Alpha {alpha_id} must return a DataFrame")
        # NaN 比例不超过 95%
        nan_ratio = result.isna().to_numpy().mean()
        if nan_ratio > 0.95:
            raise ValueError(f"Alpha {alpha_id} output is >95% NaN")
        # 拒绝 inf
        if np.isinf(result.to_numpy()).any():
            raise ValueError(f"Alpha {alpha_id} output contains inf")
        # 拒绝全 NaN
        if pd.isna(result).all().all():
            raise ValueError(f"Alpha {alpha_id} output is all NaN")
        return result


@dataclass
class RegistryState:
    """允许测试时保存/恢复注册表状态。"""

    alphas: dict[str, Alpha] = field(default_factory=dict)

    @classmethod
    def capture(cls, registry: Registry) -> "RegistryState":
        return cls(alphas=dict(registry._alphas))

    def restore(self, registry: Registry) -> None:
        registry._alphas = dict(self.alphas)


def get_default_registry() -> Registry:
    """进程级单例，避免重复扫描。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = Registry()
    return _default_registry


_default_registry: Optional[Registry] = None
