# -*- coding: utf-8 -*-
"""Token 计数器 (TokenCounter)。

跟踪 LLM 调用的输入/输出 token 数和成本。
支持多提供商定价查询。

Usage:
    from src.utils.token_counter import TokenCounter

    counter = TokenCounter()
    counter.add(input_tokens=500, output_tokens=200, provider_id="deepseek")
    counter.add(input_tokens=1200, output_tokens=400, provider_id="anthropic")
    usage = counter.get_usage()
    # TokenUsage(total_input=1700, total_output=600, total_cost=0.0033)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from src.llm.providers import get_provider_by_id


@dataclass
class TokenUsage:
    """Token 用量快照。"""

    total_input: int = 0
    total_output: int = 0
    total_cost: float = 0.0
    elapsed_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.total_output

    @property
    def cost_per_1k_input(self) -> float:
        """每千输入 token 成本 (USD)。"""
        if self.total_input == 0:
            return 0.0
        return self.total_cost / self.total_input * 1000

    def __str__(self) -> str:
        return (
            f"TokenUsage(input={self.total_input}, output={self.total_output}, "
            f"total={self.total_tokens}, cost=${self.total_cost:.4f})"
        )


@dataclass
class _Entry:
    """单次 LLM 调用记录。"""
    input_tokens: int
    output_tokens: int
    cost: float
    provider_id: str
    timestamp: float


class TokenCounter:
    """轻量级 Token 用量与成本追踪器。

    线程安全注意事项: 当前实现非线程安全。在多线程场景中，
    应在外层加锁或每个线程使用独立的 TokenCounter 实例。
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._start_time: float = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        provider_id: Optional[str] = None,
    ) -> None:
        """记录一次 LLM 调用的 token 用量。

        Args:
            input_tokens:  输入 token 数
            output_tokens: 输出 token 数
            provider_id:   提供商 ID (slug)，用于计算成本。
                           如果为 None，成本计为 0。
        """
        cost = 0.0
        if provider_id:
            provider = get_provider_by_id(provider_id)
            if provider:
                cost = (
                    input_tokens * provider.input_price_per_1m
                    + output_tokens * provider.output_price_per_1m
                ) / 1_000_000

        self._entries.append(
            _Entry(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                provider_id=provider_id or "unknown",
                timestamp=time.time(),
            )
        )

    def get_usage(self) -> TokenUsage:
        """获取累计用量快照。"""
        total_in = sum(e.input_tokens for e in self._entries)
        total_out = sum(e.output_tokens for e in self._entries)
        total_cost = sum(e.cost for e in self._entries)
        elapsed = time.time() - self._start_time
        return TokenUsage(
            total_input=total_in,
            total_output=total_out,
            total_cost=total_cost,
            elapsed_seconds=elapsed,
        )

    def get_tokens_per_second(self) -> float:
        """计算平均 token/s (仅计数，含输入和输出)。"""
        usage = self.get_usage()
        if usage.elapsed_seconds <= 0:
            return 0.0
        return usage.total_tokens / usage.elapsed_seconds

    def reset(self) -> None:
        """重置所有记录。"""
        self._entries.clear()
        self._start_time = time.time()

    @property
    def call_count(self) -> int:
        """累计调用次数。"""
        return len(self._entries)

    def last_n_calls(self, n: int = 5) -> list[dict]:
        """最近 N 次调用的摘要列表。"""
        recent = self._entries[-n:]
        return [
            {
                "provider": e.provider_id,
                "input": e.input_tokens,
                "output": e.output_tokens,
                "cost": round(e.cost, 6),
                "timestamp": e.timestamp,
            }
            for e in recent
        ]
