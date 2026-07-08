# -*- coding: utf-8 -*-
"""管道上下文 — 承载全链路分析的运行时状态。

AnalysisContext 作为单一真理源 (SSOT)，在管道各阶段传递共享状态：
数据获取结果、阶段结果、警告、数据缺口、草稿本、token 计数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.routing.scratchpad import AnalysisScratchpad


# ---------------------------------------------------------------------------
# TokenCounter — 轻量 token 计数器
# ---------------------------------------------------------------------------

class TokenCounter:
    """轻量 Token 计数跟踪器。

    基于字符数的粗略估计 (约 4 chars / token)，适合跟踪分析管道的
    上下文消耗。不做实际 LLM tokenize。
    """

    ENCODING_RATIO: float = 4.0  # 每个 token 约 4 个字符

    def __init__(self) -> None:
        self._count: int = 0
        self._peak: int = 0
        self._snapshots: dict[str, int] = {}

    @property
    def count(self) -> int:
        """当前累计 token 数。"""
        return self._count

    @property
    def peak(self) -> int:
        """历史峰值 token 数。"""
        return self._peak

    def add(self, text: str) -> int:
        """添加文本并返回其估计 token 数。

        Args:
            text: 要计数的文本

        Returns:
            估计 token 数
        """
        tokens = max(1, round(len(text) / self.ENCODING_RATIO))
        self._count += tokens
        if self._count > self._peak:
            self._peak = self._count
        return tokens

    def snapshot(self, label: str) -> int:
        """记录当前计数的快照。

        Args:
            label: 快照标签，如 "L0" / "L1" / "L2"

        Returns:
            快照时的 token 数
        """
        self._snapshots[label] = self._count
        return self._count

    def delta(self, label_a: str, label_b: str) -> Optional[int]:
        """计算两个快照之间的 token 增量。

        Args:
            label_a: 较早快照标签
            label_b: 较晚快照标签

        Returns:
            token 增量, 如果任一快照不存在则返回 None
        """
        a = self._snapshots.get(label_a)
        b = self._snapshots.get(label_b)
        if a is None or b is None:
            return None
        return b - a

    def reset(self) -> None:
        """重置计数。"""
        self._count = 0
        self._peak = 0
        self._snapshots.clear()

    def to_dict(self) -> dict[str, Any]:
        """序列化摘要。"""
        return {
            "count": self._count,
            "peak": self._peak,
            "snapshots": dict(self._snapshots),
        }


# ---------------------------------------------------------------------------
# AnalysisContext
# ---------------------------------------------------------------------------

@dataclass
class AnalysisContext:
    """全链路分析上下文 — 管道中各阶段的共享运行时状态。

    属性均为 mutable，允许管道阶段按需写入。
    """

    # --- 查询标识 ---
    symbol: str = ""
    market: str = "SH"
    query: str = ""

    # --- 运行时组件 ---
    scratchpad: AnalysisScratchpad = field(
        default_factory=lambda: AnalysisScratchpad(""),  # type: ignore[arg-type]
    )
    token_counter: TokenCounter = field(default_factory=TokenCounter)

    # --- 时间 ---
    start_time: datetime = field(default_factory=datetime.now)

    # --- 阶段控制 ---
    current_stage: str = ""

    # --- 结果存储 (按阶段名索引) ---
    stage_results: dict[str, Any] = field(default_factory=dict)

    # --- 警告 & 数据缺口 ---
    warnings: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)

    def add_warning(self, warning: str) -> None:
        """添加一条警告。"""
        if warning not in self.warnings:
            self.warnings.append(warning)

    def add_data_gap(self, gap: str) -> None:
        """添加一条数据缺口。"""
        if gap not in self.data_gaps:
            self.data_gaps.append(gap)

    def set_stage_result(self, stage_name: str, result: Any) -> None:
        """设置指定阶段的分析结果。"""
        self.stage_results[stage_name] = result
        self.current_stage = stage_name

    def get_stage_result(self, stage_name: str) -> Any:
        """获取指定阶段的已有结果, 不存在时返回 None。"""
        return self.stage_results.get(stage_name)

    def elapsed_ms(self) -> float:
        """从 start_time 到现在的毫秒数。"""
        return (datetime.now() - self.start_time).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 序列化的 dict。"""
        return {
            "symbol": self.symbol,
            "market": self.market,
            "query": self.query,
            "current_stage": self.current_stage,
            "elapsed_ms": self.elapsed_ms(),
            "stage_results_keys": list(self.stage_results.keys()),
            "warnings": self.warnings,
            "data_gaps": self.data_gaps,
            "token_counter": self.token_counter.to_dict(),
            "scratchpad": self.scratchpad.file_path,
        }


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_context(
    symbol: str,
    market: str = "SH",
    query: str = "",
    output_dir: str = "output/scratchpad/",
) -> AnalysisContext:
    """创建标准 AnalysisContext 实例的工厂函数。

    Args:
        symbol: 股票代码
        market: 市场标识 (SH / SZ / BJ)
        query: 用户原始查询
        output_dir: 草稿本输出目录

    Returns:
        初始化的 AnalysisContext 实例
    """
    scratchpad = AnalysisScratchpad(symbol, output_dir=output_dir)
    token_counter = TokenCounter()
    return AnalysisContext(
        symbol=symbol,
        market=market,
        query=query,
        scratchpad=scratchpad,
        token_counter=token_counter,
        start_time=datetime.now(),
    )
