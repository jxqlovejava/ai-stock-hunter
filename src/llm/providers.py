# -*- coding: utf-8 -*-
"""LLM 提供商注册表 (Provider Registry)。

基于 Dexter 的 provider-registry 模式:
  - ProviderDef 定义每个提供商的信息
  - resolve_provider(model_name) 通过模型名前缀匹配
  - get_provider_by_id(slug) 通过 ID 精确查找
  - get_fast_model(provider) 每个提供商有一个"快模型"用于廉价操作

Usage:
    from src.llm.providers import resolve_provider, get_fast_model

    provider = resolve_provider("claude-sonnet-4-20260514")
    fast = get_fast_model(provider)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProviderDef:
    """LLM 提供商定义。

    Attributes:
        id:             唯一 slug 标识 (e.g. "anthropic", "deepseek")
        display_name:   人类可读名称 (e.g. "Anthropic Claude", "DeepSeek")
        model_prefixes: 模型名前缀列表，用于 resolve_provider 匹配
                         (e.g. ["claude-"] → 匹配 "claude-sonnet-4-20260514")
        api_key_env:    环境变量名称，存 API Key (e.g. "ANTHROPIC_API_KEY")
        base_url:       API 地址
        context_window: 上下文窗口大小 (tokens)
        fast_model:     该供应商的快速/廉价模型名，用于压缩、预分析等
        input_price_per_1m:   每百万输入 token 价格 (USD)
        output_price_per_1m:  每百万输出 token 价格 (USD)
    """

    id: str
    display_name: str
    model_prefixes: list[str] = field(default_factory=list)
    api_key_env: str = ""
    base_url: str = ""
    context_window: int = 128_000
    fast_model: str = ""
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    def __str__(self) -> str:
        return f"{self.display_name} ({self.id})"


# ---------------------------------------------------------------------------
# 内置提供商列表
# ---------------------------------------------------------------------------

PROVIDERS: list[ProviderDef] = [
    ProviderDef(
        id="deepseek",
        display_name="DeepSeek",
        model_prefixes=["deepseek"],
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
        context_window=128_000,
        fast_model="deepseek-chat",
        input_price_per_1m=0.14,
        output_price_per_1m=0.28,
    ),
    ProviderDef(
        id="openai",
        display_name="OpenAI",
        model_prefixes=["gpt-", "o1", "o3"],
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        context_window=128_000,
        fast_model="gpt-4o-mini",
        input_price_per_1m=2.50,
        output_price_per_1m=10.00,
    ),
    ProviderDef(
        id="anthropic",
        display_name="Anthropic Claude",
        model_prefixes=["claude-"],
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com/v1",
        context_window=200_000,
        fast_model="claude-3-5-haiku-latest",
        input_price_per_1m=3.00,
        output_price_per_1m=15.00,
    ),
    ProviderDef(
        id="qwen",
        display_name="通义千问 (Qwen)",
        model_prefixes=["qwen"],
        api_key_env="QWEN_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        context_window=128_000,
        fast_model="qwen-turbo",
        input_price_per_1m=0.50,
        output_price_per_1m=2.00,
    ),
    ProviderDef(
        id="moonshot",
        display_name="Moonshot 月之暗面 (Kimi)",
        model_prefixes=["moonshot", "kimi"],
        api_key_env="MOONSHOT_API_KEY",
        base_url="https://api.moonshot.cn/v1",
        context_window=128_000,
        fast_model="moonshot-v1-8k",
        input_price_per_1m=1.00,
        output_price_per_1m=3.00,
    ),
]


# ---------------------------------------------------------------------------
# 快速构建哈希表
# ---------------------------------------------------------------------------

_PROVIDER_BY_ID: dict[str, ProviderDef] = {p.id: p for p in PROVIDERS}

# 前缀 → ProviderDef 映射表，前缀按长度降序排列以优先匹配最长前缀
# (e.g. "claude-sonnet-4" 应匹配 "claude-" 而非 "claude-sonnet-" 不存在的情况)
_PREFIX_INDEX: list[tuple[str, ProviderDef]] = sorted(
    [(prefix, p) for p in PROVIDERS for prefix in p.model_prefixes],
    key=lambda x: len(x[0]),
    reverse=True,
)


def resolve_provider(model_name: str) -> Optional[ProviderDef]:
    """通过模型名前缀匹配提供商。

    Args:
        model_name: 完整的模型名，如 "claude-sonnet-4-20260514"、"gpt-4o"

    Returns:
        匹配到的 ProviderDef；无匹配则返回 None
    """
    name_lower = model_name.lower()
    for prefix, provider in _PREFIX_INDEX:
        if name_lower.startswith(prefix.lower()):
            return provider
    return None


def get_provider_by_id(slug: str) -> Optional[ProviderDef]:
    """通过 ID (slug) 精确查找提供商。

    Args:
        slug: 如 "anthropic"、"deepseek"

    Returns:
        对应的 ProviderDef，未找到返回 None
    """
    return _PROVIDER_BY_ID.get(slug)


def get_fast_model(provider: ProviderDef) -> str:
    """获取指定提供商的快速/廉价模型名。

    用于压缩、预分析、初筛等低成本操作。

    Args:
        provider: ProviderDef 实例

    Returns:
        模型名字符串；如果未设置 fast_model 则返回首个 model_prefix + "-default"
    """
    return provider.fast_model or f"{provider.model_prefixes[0]}default"
