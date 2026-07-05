# -*- coding: utf-8 -*-
"""策略进化引擎 — LLM 驱动的变异 + 交叉。

借鉴 CogAlpha 论文的「Thinking Evolution」：
  变异 (Mutation):  保持核心逻辑，修改一个维度（参数/条件/窗口）
  交叉 (Crossover):  合并两个策略的优势，产生混合策略

与现有 LifecycleManager 集成：
  提取的策略 → 变异生成变体 → 交叉合并 → 回测验证 → 推进生命周期

用法:
    from src.evolution.mutator import StrategyMutator
    from src.alpha.factor_gen import LLMBackend

    mutator = StrategyMutator(LLMBackend())
    variants = mutator.mutate(strategy, n_variants=3)
    hybrid = mutator.crossover(strategy_a, strategy_b)
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 延迟导入避免循环
try:
    from src.alpha.factor_gen import LLMBackend
except ImportError:
    LLMBackend = None  # type: ignore


@dataclass
class StrategyVariant:
    """策略变体。"""
    name: str                              # 变体名称
    description: str = ""
    strategy_type: str = ""
    entry_conditions: list[str] = field(default_factory=list)
    exit_conditions: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    parent_id: str = ""                    # 来源策略 ID
    generation: int = 0                    # 代数
    mutation_type: str = ""                # "mutation" | "crossover" | "original"
    mutation_detail: str = ""              # 具体变异内容
    confidence: float = 0.5


# ------------------------------------------------------------------
# 提示词模板 — 改编自 CogAlpha Thinking Evolution
# ------------------------------------------------------------------


EVOLVE_PROMPTS = {
    "mutate_system": textwrap.dedent("""\
    You are an expert quantitative strategy researcher. Your task is to create
    improved variants of an existing trading strategy through controlled mutation.

    MUTATION RULES:
    1. Preserve the CORE economic logic of the original strategy
    2. Modify exactly ONE dimension per variant:
       - Parameters: adjust thresholds, windows, multipliers (±20-50%)
       - Conditions: add/remove/modify ONE entry or exit condition
       - Timing: change holding period, rebalancing frequency
       - Risk: adjust position sizing, stop-loss levels
    3. The variant must remain economically interpretable
    4. Document what changed and why

    Output 3 variants, each as a complete strategy specification.
    """),

    "mutate_user": textwrap.dedent("""\
    Original Strategy: {name}
    Type: {strategy_type}
    Description: {description}

    Entry Conditions:
    {entry_conditions}

    Exit Conditions:
    {exit_conditions}

    Parameters: {parameters}

    Backtest Context (if available):
    {backtest_context}

    Generate {n_variants} variants, each mutating a different dimension.
    For each variant, output:

    ---VARIANT---
    NAME: <variant_name> (descriptive, include the changed dimension in the name)
    MUTATION: <what was changed and why>
    TYPE: <strategy_type>
    DESCRIPTION: <updated description>
    ENTRY:
    - <condition 1>
    - <condition 2>
    EXIT:
    - <condition 1>
    PARAMETERS: {{"param": value, ...}}
    ---END---
    """),

    "crossover_system": textwrap.dedent("""\
    You are an expert quantitative strategy researcher. Your task is to combine
    two trading strategies into a superior hybrid.

    CROSSOVER RULES:
    1. Take the BEST entry conditions from each parent
    2. Take the MORE conservative exit conditions (risk-first)
    3. Merge parameters using the more robust values
    4. The hybrid must be logically coherent — no contradictory rules
    5. Name should reflect the hybrid nature: "StrategyA_x_StrategyB"
    """),

    "crossover_user": textwrap.dedent("""\
    Strategy A:
    Name: {name_a}
    Type: {type_a}
    Description: {desc_a}
    Entry: {entry_a}
    Exit: {exit_a}
    Params: {params_a}

    Strategy B:
    Name: {name_b}
    Type: {type_b}
    Description: {desc_b}
    Entry: {entry_b}
    Exit: {exit_b}
    Params: {params_b}

    Create a HYBRID strategy combining the best of both. Output in the same
    ---VARIANT--- format with MUTATION: "crossover of {name_a} × {name_b}".
    """),
}


class StrategyMutator:
    """策略进化引擎 — LLM 驱动变异 + 交叉。

    借鉴 CogAlpha 的 Thinking Evolution:
      - Mutation Agent: 修改一个维度产生变体
      - Crossover Agent: 合并两个策略的基因

    用法:
        mutator = StrategyMutator()
        variants = mutator.mutate(strategy, n_variants=3)
        hybrid = mutator.crossover(strategy_a, strategy_b)
    """

    # 变异维度
    MUTATION_DIMENSIONS = [
        ("parameter_tuning", "Adjust thresholds/windows by ±30%"),
        ("entry_tightening", "Add one stricter entry condition"),
        ("entry_relaxing", "Remove one restrictive entry condition"),
        ("exit_earlier", "Add an earlier exit signal to reduce drawdown"),
        ("exit_trailing", "Add trailing stop instead of fixed stop-loss"),
        ("position_sizing", "Adjust position sizing rules"),
        ("sector_filter", "Add/remove sector constraints"),
        ("volume_filter", "Add volume/liquidity confirmation"),
    ]

    def __init__(self, backend=None):
        """初始化。

        Args:
            backend: LLMBackend 实例。None 时尝试 auto-detect。
        """
        if backend is None and LLMBackend is not None:
            try:
                backend = LLMBackend()
            except Exception:
                pass
        self._backend = backend

    @property
    def has_llm(self) -> bool:
        return self._backend is not None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def mutate(
        self,
        strategy,    # ExtractedStrategy
        n_variants: int = 3,
        backtest_context: str = "",
    ) -> list[StrategyVariant]:
        """对策略进行变异，产生 n 个变体。

        Args:
            strategy: ExtractedStrategy 实例
            n_variants: 变体数量
            backtest_context: 回测上下文（Sharpe/收益/回撤等），用于定向变异

        Returns:
            StrategyVariant 列表
        """
        if self._backend:
            return self._llm_mutate(strategy, n_variants, backtest_context)
        else:
            return self._rule_mutate(strategy, n_variants)

    def crossover(
        self,
        strategy_a,    # ExtractedStrategy
        strategy_b,    # ExtractedStrategy
    ) -> list[StrategyVariant]:
        """交叉两个策略，产生混合策略。

        Args:
            strategy_a, strategy_b: ExtractedStrategy 实例

        Returns:
            StrategyVariant 列表（通常 1 个混合策略）
        """
        if self._backend:
            return self._llm_crossover(strategy_a, strategy_b)
        else:
            return self._rule_crossover(strategy_a, strategy_b)

    def evolve_generation(
        self,
        strategies: list,    # list[ExtractedStrategy]
        n_variants_per: int = 2,
        n_crossovers: int = 2,
        backtest_contexts: dict[str, str] | None = None,
    ) -> dict[str, list[StrategyVariant]]:
        """对一组策略运行一代进化。

        Returns:
            {strategy_id: [variants]}
        """
        results: dict[str, list[StrategyVariant]] = {}
        ctx = backtest_contexts or {}

        # 变异
        for s in strategies:
            sid = getattr(s, "paper_id", "") or getattr(s, "strategy_name", "")
            bc = ctx.get(sid, "")
            results[sid] = self.mutate(s, n_variants_per, bc)

        # 交叉 top 2 (按 extraction_confidence)
        sorted_strategies = sorted(
            strategies,
            key=lambda s: getattr(s, "extraction_confidence", 0),
            reverse=True,
        )
        for i in range(0, min(len(sorted_strategies) - 1, n_crossovers * 2), 2):
            a = sorted_strategies[i]
            b = sorted_strategies[i + 1]
            crossed = self.crossover(a, b)
            sid_a = getattr(a, "paper_id", "") or getattr(a, "strategy_name", "")
            if sid_a in results:
                results[sid_a].extend(crossed)
            else:
                results[sid_a] = crossed

        return results

    # ------------------------------------------------------------------
    # LLM 驱动变异
    # ------------------------------------------------------------------

    def _llm_mutate(
        self, strategy, n_variants: int, backtest_context: str,
    ) -> list[StrategyVariant]:
        """通过 LLM 生成策略变体。"""
        entry_text = "\n".join(f"- {c}" for c in (strategy.entry_conditions or ["(none)"]))
        exit_text = "\n".join(f"- {c}" for c in (strategy.exit_conditions or ["(none)"]))
        params_text = str(strategy.parameters) if strategy.parameters else "{}"

        prompt = EVOLVE_PROMPTS["mutate_user"].format(
            name=strategy.strategy_name,
            strategy_type=strategy.strategy_type,
            description=strategy.description,
            entry_conditions=entry_text,
            exit_conditions=exit_text,
            parameters=params_text,
            n_variants=n_variants,
            backtest_context=backtest_context or "No backtest data available",
        )

        try:
            response = self._backend.complete(
                prompt, EVOLVE_PROMPTS["mutate_system"],
            )
            return self._parse_variants(
                response, parent_id=strategy.paper_id or strategy.strategy_name,
                mutation_type="mutation", generation=1,
            )
        except Exception as e:
            logger.error("LLM mutation failed: %s", e)
            return self._rule_mutate(strategy, n_variants)

    def _llm_crossover(self, strategy_a, strategy_b) -> list[StrategyVariant]:
        """通过 LLM 交叉两个策略。"""
        prompt = EVOLVE_PROMPTS["crossover_user"].format(
            name_a=strategy_a.strategy_name,
            type_a=strategy_a.strategy_type,
            desc_a=strategy_a.description,
            entry_a="; ".join(strategy_a.entry_conditions or ["none"]),
            exit_a="; ".join(strategy_a.exit_conditions or ["none"]),
            params_a=str(strategy_a.parameters),
            name_b=strategy_b.strategy_name,
            type_b=strategy_b.strategy_type,
            desc_b=strategy_b.description,
            entry_b="; ".join(strategy_b.entry_conditions or ["none"]),
            exit_b="; ".join(strategy_b.exit_conditions or ["none"]),
            params_b=str(strategy_b.parameters),
        )

        try:
            response = self._backend.complete(
                prompt, EVOLVE_PROMPTS["crossover_system"],
            )
            return self._parse_variants(
                response,
                parent_id=f"{strategy_a.strategy_name}×{strategy_b.strategy_name}",
                mutation_type="crossover", generation=1,
            )
        except Exception as e:
            logger.error("LLM crossover failed: %s", e)
            return self._rule_crossover(strategy_a, strategy_b)

    # ------------------------------------------------------------------
    # 规则驱动变异（无 LLM 回退）
    # ------------------------------------------------------------------

    def _rule_mutate(
        self, strategy, n_variants: int,
    ) -> list[StrategyVariant]:
        """无 LLM 时的规则驱动变异。"""
        variants: list[StrategyVariant] = []
        import random

        for i in range(min(n_variants, len(self.MUTATION_DIMENSIONS))):
            dim_name, dim_desc = self.MUTATION_DIMENSIONS[i % len(self.MUTATION_DIMENSIONS)]

            variant = StrategyVariant(
                name=f"{strategy.strategy_name}_v{i+1}_{dim_name}",
                description=f"{strategy.description} (变异: {dim_desc})",
                strategy_type=strategy.strategy_type,
                entry_conditions=list(strategy.entry_conditions),
                exit_conditions=list(strategy.exit_conditions),
                parameters=dict(strategy.parameters) if strategy.parameters else {},
                parent_id=strategy.paper_id or strategy.strategy_name,
                generation=1,
                mutation_type="mutation",
                mutation_detail=dim_desc,
                confidence=max(0.3, strategy.extraction_confidence - 0.1),
            )

            # 应用变异
            params = variant.parameters
            if dim_name == "parameter_tuning" and params:
                for k in list(params.keys())[:3]:
                    if isinstance(params[k], (int, float)):
                        params[k] = round(params[k] * random.uniform(0.7, 1.3), 2)
            elif dim_name == "entry_tightening":
                variant.entry_conditions.append("[MUTATED] 成交量 > 20日均量的1.2倍")
            elif dim_name == "exit_trailing":
                variant.exit_conditions.append("[MUTATED] 追踪止损: 最高点回撤8%")
            elif dim_name == "volume_filter":
                variant.entry_conditions.append("[MUTATED] 日成交额 > 5000万")

            variants.append(variant)

        return variants

    def _rule_crossover(
        self, strategy_a, strategy_b,
    ) -> list[StrategyVariant]:
        """无 LLM 时的规则驱动交叉。"""
        # 取 A 的买入条件 + B 的卖出条件 + 合并参数
        entry = list(strategy_a.entry_conditions) + [
            c for c in strategy_b.entry_conditions
            if c not in strategy_a.entry_conditions
        ]
        exit_cond = list(strategy_b.exit_conditions) + [
            c for c in strategy_a.exit_conditions
            if c not in strategy_b.exit_conditions
        ]
        params = dict(strategy_a.parameters) if strategy_a.parameters else {}
        params_b = dict(strategy_b.parameters) if strategy_b.parameters else {}
        for k, v in params_b.items():
            if k in params:
                params[k] = (params[k] + v) / 2  # 取平均
            else:
                params[k] = v

        return [StrategyVariant(
            name=f"{strategy_a.strategy_name}_x_{strategy_b.strategy_name}",
            description=f"Hybrid: A({strategy_a.description[:50]}) + B({strategy_b.description[:50]})",
            strategy_type="composite",
            entry_conditions=entry,
            exit_conditions=exit_cond,
            parameters=params,
            parent_id=f"{strategy_a.paper_id}×{strategy_b.paper_id}",
            generation=1,
            mutation_type="crossover",
            confidence=min(
                strategy_a.extraction_confidence,
                strategy_b.extraction_confidence,
            ) * 0.9,
        )]

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    def _parse_variants(
        self, response: str, parent_id: str = "",
        mutation_type: str = "mutation", generation: int = 1,
    ) -> list[StrategyVariant]:
        """从 LLM 回复中解析策略变体。"""
        variants: list[StrategyVariant] = []

        blocks = re.split(r'---VARIANT---', response)
        for block in blocks[1:]:
            if not block.strip():
                continue

            name = self._extract(block, "NAME")
            mutation = self._extract(block, "MUTATION")
            stype = self._extract(block, "TYPE")
            desc = self._extract(block, "DESCRIPTION")

            # 解析 ENTRY/EXIT 列表
            entry_block = self._extract_section(block, "ENTRY")
            exit_block = self._extract_section(block, "EXIT")
            entry_conds = [l.strip("- ").strip() for l in entry_block.split("\n") if l.strip().startswith("-")]
            exit_conds = [l.strip("- ").strip() for l in exit_block.split("\n") if l.strip().startswith("-")]

            # 解析 PARAMETERS
            params_str = self._extract(block, "PARAMETERS")
            params = {}
            if params_str:
                try:
                    import json
                    params = json.loads(params_str.replace("'", '"'))
                except (json.JSONDecodeError, ValueError):
                    pass

            variants.append(StrategyVariant(
                name=name or f"variant_{len(variants)}",
                description=desc or mutation or "",
                strategy_type=stype or "",
                entry_conditions=entry_conds,
                exit_conditions=exit_conds,
                parameters=params,
                parent_id=parent_id,
                generation=generation,
                mutation_type=mutation_type,
                mutation_detail=mutation or "",
                confidence=0.6 if mutation_type == "crossover" else 0.5,
            ))

        return variants

    @staticmethod
    def _extract(text: str, field: str) -> str:
        """从文本提取 FIELD: value。"""
        pattern = rf'{field}:\s*(.+?)(?:\n\w+:|\n```|\n\n|---|$)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_section(text: str, field: str) -> str:
        """提取 ENTRY:/EXIT: 后的内容块（直到下一个大写字段名）。"""
        pattern = rf'{field}:\s*\n(.*?)(?:\n\w+:\s*\n|\n```|---|\Z)'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""


# ------------------------------------------------------------------
# 进化 CLI 集成帮助函数
# ------------------------------------------------------------------


def to_extracted_strategy(variant: StrategyVariant) -> dict:
    """将 StrategyVariant 转换回 ExtractedStrategy 兼容的 dict。

    用于将 LLM 变异结果写回 LifecycleManager。
    """
    return {
        "strategy_name": variant.name,
        "description": variant.description,
        "strategy_type": variant.strategy_type,
        "entry_conditions": variant.entry_conditions,
        "exit_conditions": variant.exit_conditions,
        "parameters": variant.parameters,
        "extraction_confidence": variant.confidence,
        "paper_id": variant.parent_id,
    }
