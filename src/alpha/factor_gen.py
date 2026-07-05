# -*- coding: utf-8 -*-
"""LLM 驱动 Alpha 因子生成管线 — 借鉴 CogAlpha 论文的核心创新。

将 CogAlpha 的「7 级 Agent 层级 + 进化搜索 + 金融反馈」适配到本项目：

  1. FactorGenerator    — 从数据 schema 生成新因子代码
  2. FactorMutator      — 对现有因子进行变异
  3. FactorCrossover    — 交叉两个因子产生新因子
  4. FactorPipeline     — 编排完整的生成→审查→筛选周期

用法:
    from src.alpha.factor_gen import FactorPipeline, LLMBackend

    backend = LLMBackend(api_key="...")  # 可插拔 LLM 后端
    pipeline = FactorPipeline(backend)
    factors = pipeline.generate(
        data_columns=["open", "high", "low", "close", "volume", "turnover"],
        target="10d_forward_return",
        n_candidates=5,
    )
    for f in factors:
        print(f"{f.name}: {f.code}")
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# LLM 后端接口（可插拔）
# ------------------------------------------------------------------


class LLMBackend:
    """可插拔 LLM 后端。

    默认使用环境变量 ANTHROPIC_API_KEY / OPENAI_API_KEY。
    可替换为任何兼容的 LLM 调用接口。
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str = "",
        custom_call: Optional[Callable[[str], str]] = None,
    ):
        self.model = model
        self.api_key = api_key
        self._custom_call = custom_call

    def complete(self, prompt: str, system: str = "") -> str:
        """调用 LLM 获取回复。"""
        if self._custom_call:
            return self._custom_call(prompt)

        # 尝试 Anthropic API
        try:
            import os
            key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            if key:
                return self._call_anthropic(prompt, system, key)
        except Exception as e:
            logger.debug("Anthropic API failed: %s", e)

        # 尝试 OpenAI API
        try:
            import os
            key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
            if key:
                return self._call_openai(prompt, system, key)
        except Exception as e:
            logger.debug("OpenAI API failed: %s", e)

        raise RuntimeError(
            "No LLM backend available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
            "or provide a custom_call function."
        )

    def _call_anthropic(self, prompt: str, system: str, api_key: str) -> str:
        import json
        import urllib.request

        body = json.dumps({
            "model": self.model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"]

    def _call_openai(self, prompt: str, system: str, api_key: str) -> str:
        import json
        import urllib.request

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = json.dumps({
            "model": self.model,
            "max_tokens": 2048,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


# ------------------------------------------------------------------
# DTO
# ------------------------------------------------------------------


@dataclass
class FactorCandidate:
    """因子候选项。"""
    name: str                          # factor_<logic>_<transforms>_<window>_<field>
    code: str                          # Python 函数源代码
    description: str = ""              # 逻辑解释（docstring）
    formula: str = ""                  # 数学公式
    generation: int = 0                # 第几代
    parent_ids: list[str] = field(default_factory=list)  # 变异/交叉来源
    quality_score: float = 0.0         # 质量审查评分 0-100
    ic_value: float = 0.0             # Information Coefficient
    passed_quality: bool = False


# ------------------------------------------------------------------
# CogAlpha 提示词模板（改编自论文 Appendix C）
# ------------------------------------------------------------------


class CogAlphaPrompts:
    """改编自 CogAlpha 论文的提示词模板。

    论文原文使用 7 级 Agent 层级（基础/趋势/反转/量价/周期/模式/几何融合），
    每层有针对性的提示。此处适配为通用的因子生成提示。
    """

    # 基础生成提示 — 改编自 CogAlpha 7-level agent hierarchy
    GENERATE_SYSTEM = textwrap.dedent("""\
    You are an expert quantitative researcher specializing in alpha factor discovery.
    Your task is to generate novel, economically interpretable alpha factor functions
    that predict forward stock returns.

    CRITICAL RULES:
    1. Each factor must be a single, well-defined Python function
    2. The function takes a pandas DataFrame with columns: {columns}
    3. Input has MultiIndex (date, ticker), grouped by ticker (time series per stock)
    4. Output is a pd.Series indexed by (date, ticker), same name as the function
    5. NEVER use future data — only past and present information per row
    6. NEVER use nested loops (for inside for, while inside while)
    7. NEVER use while True or infinite loops
    8. Use only vectorized operations (numpy/pandas)
    9. Each factor must be expressible in ≤5 logical steps
    10. Include a clear docstring explaining the economic logic and formula

    Factor Design Principles (from CogAlpha):
    - Focus on capturing ONE clear economic intuition
    - Prefer clean, generalizable formulas over highly engineered constructs
    - Balance simplicity with predictive potential
    - Each factor should have a descriptive name: factor_<logic>_<window>_<field>
    """)

    GENERATE_USER = textwrap.dedent("""\
    Available data columns: {columns}
    Target: predict {target}

    Generate {n} new, original alpha factor functions. For each factor:

    1. NAME: factor_<logic>_<window>_<field>
    2. DOCSTRING: explain the economic intuition and formula
    3. FORMULA: mathematical expression
    4. CODE: clean, vectorized Python function

    Avoid common factors (simple moving average crosses, RSI, etc.).
    Seek novel economic relationships and hidden patterns.

    Economic themes to explore:
    {themes}

    Output format (repeat for each factor):
    ---FACTOR---
    NAME: <factor_name>
    DESCRIPTION: <economic intuition>
    FORMULA: <mathematical formula>
    CODE:
    ```python
    <function code>
    ```
    ---END---
    """)

    # 变异提示 — 改编自 CogAlpha Thinking Evolution Mutation Agent
    MUTATE_SYSTEM = textwrap.dedent("""\
    You are an expert quantitative researcher. Your task is to mutate an existing
    alpha factor to create an improved variant. The mutation should:
    1. Preserve the core economic intuition
    2. Modify ONE aspect: window length, transformation, normalization, combination
    3. Introduce meaningful variation without breaking interpretability
    4. Never introduce future information leakage
    """)

    MUTATE_USER = textwrap.dedent("""\
    Original factor:
    Name: {name}
    Description: {description}
    Code:
    ```python
    {code}
    ```

    Mutation strategy: {strategy}

    Generate an improved variant. Keep the original structure but apply the mutation.
    Output in the same ---FACTOR--- format.
    """)

    # 交叉提示 — 改编自 CogAlpha Thinking Evolution Crossover Agent
    CROSSOVER_SYSTEM = textwrap.dedent("""\
    You are an expert quantitative researcher. Your task is to combine two
    existing alpha factors to create a novel hybrid factor that captures
    both economic intuitions synergistically.
    """)

    CROSSOVER_USER = textwrap.dedent("""\
    Factor A:
    Name: {name_a}
    Description: {desc_a}
    Code:
    ```python
    {code_a}
    ```

    Factor B:
    Name: {name_b}
    Description: {desc_b}
    Code:
    ```python
    {code_b}
    ```

    Create a hybrid factor combining the best of both.
    Output in the same ---FACTOR--- format.
    """)

    # 金融反馈优化提示 — 改编自 CogAlpha Financial Feedback Loop
    FEEDBACK_SYSTEM = textwrap.dedent("""\
    You are an expert quantitative researcher reviewing factor performance.
    Your task is to analyze why a factor underperformed and suggest specific,
    actionable improvements to its code.
    """)

    FEEDBACK_USER = textwrap.dedent("""\
    Factor: {name}
    Description: {description}
    Performance:
      - IC (Information Coefficient): {ic_value:.4f}
      - IC Rank Correlation: {rank_ic:.4f}
      - Sharpe Ratio: {sharpe:.2f}
      - Max Drawdown: {max_dd:.1%}
      - Turnover: {turnover:.1%}

    Current code:
    ```python
    {code}
    ```

    Issues identified:
    {issues}

    Suggest 3 specific improvements to the factor code.
    For each improvement, explain WHY it would help and HOW to implement it.

    Output format:
    ---IMPROVEMENT---
    REASON: <why this helps>
    CHANGE: <what to change>
    NEW_CODE:
    ```python
    <updated function>
    ```
    ---END---
    """)

    # 经济可解释性深度检查 — Item 1: LLM-powered deep check
    DEEP_CHECK_SYSTEM = textwrap.dedent("""\
    You are an expert quantitative researcher and alpha factor reviewer.
    You are asked to deeply evaluate an analysis report for:

    1. FUTURE INFORMATION LEAKAGE: Does any metric use data that wouldn't be
       available at the analysis time? Pay special attention to:
       - Financial report release lag (quarterly reports available ~30-45 days after period end)
       - Using annual data before fiscal year ends
       - Forward-looking indicators that embed future prices

    2. LOGICAL CONTRADICTIONS: Are there internal inconsistencies?
       - High value score + low quality score → possible value trap
       - High momentum + extreme sentiment → crowded trade risk
       - Strong macro + weak sector → sector-specific headwinds

    3. ECONOMIC INTERPRETABILITY: Can each conclusion be traced to an economic
       mechanism? Flag any assertion that lacks economic grounding.
       - "The stock will go up because it's cheap" → insufficient
       - "PE compression due to cyclical earnings peak" → sufficient

    Be specific and actionable. Flag severity: CRITICAL / HIGH / MEDIUM / LOW.
    """)

    DEEP_CHECK_USER = textwrap.dedent("""\
    Analysis Report for {symbol}:

    Scores:
    - Macro: {macro_score:.0f}/100
    - Value: {value_score:.0f}/100
    - Quality: {quality_score:.0f}/100
    - Momentum: {momentum_score:.0f}/100
    - Executive: {executive_score:.0f}/100
    - Valuation: {valuation_score:.0f}/100
    - Sentiment: {sentiment_signal}

    Bull Case: {bull_case}
    Bear Case: {bear_case}

    Alpha Rationale: {alpha_rationale}

    Data Freshness: {data_freshness}

    Please perform a deep quality review. Output in this format:

    ---LEAKAGE---
    [Findings about future information leakage, or "None detected"]

    ---CONTRADICTIONS---
    [Findings about logical contradictions, or "None detected"]

    ---INTERPRETABILITY---
    [Findings about economic interpretability, or "All scores economically grounded"]

    ---OVERALL---
    PASS/FAIL
    Score: X/100
    Key Issues: [...]
    """)

    MUTATION_STRATEGIES = [
        "Change the lookback window (shorter for faster signals, longer for stability)",
        "Apply a different normalization (z-score, rank, min-max)",
        "Add a volatility adjustment (divide by rolling std)",
        "Combine with a volume confirmation filter",
        "Replace simple MA with EMA or weighted MA",
        "Introduce a non-linear transformation (log, sqrt, sigmoid)",
        "Add a turnover/delay penalty to reduce trading frequency",
        "Cross-sectional rank instead of raw values",
    ]

    GENERATION_THEMES = [
        "Liquidity impact: how price moves per unit volume",
        "Information arrival: volatility pattern before/after price jumps",
        "Market microstructure: bid-ask bounce, overnight vs intraday",
        "Investor behavior: momentum with volume confirmation",
        "Risk premium: volatility-scaled returns",
        "Mean reversion: short-term reversal with volume filter",
        "Trend quality: distinguish persistent trends from noise",
        "Regime awareness: adaptive windows based on volatility state",
        "Supply-demand imbalance: order flow proxy from OHLCV",
    ]


# ------------------------------------------------------------------
# 因子生成管线
# ------------------------------------------------------------------


class FactorPipeline:
    """Alpha 因子生成管线 — 改编自 CogAlpha Framework。

    完整周期:
      1. Generate: LLM 从数据 schema 生成 N 个新因子
      2. Validate: 质量审查（语法/泄露/效率/解释性）
      3. Test: 计算 IC / Rank IC（可选回测）
      4. Select: 保留 Top-K
      5. Mutate: 对低分因子变异
      6. Crossover: 交叉高分因子
      7. 回到 Step 2，迭代 G 代

    用法:
        backend = LLMBackend()
        pipeline = FactorPipeline(backend)
        factors = pipeline.run_cycle(
            data_columns=["open", "high", "low", "close", "volume"],
            target="10d_forward_return",
            n_generations=3,
            n_candidates=5,
        )
    """

    def __init__(self, backend: Optional[LLMBackend] = None):
        self._backend = backend or LLMBackend()
        self._prompts = CogAlphaPrompts()
        self._generation = 0

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def generate(
        self,
        data_columns: list[str],
        target: str = "10d_forward_return",
        n_candidates: int = 5,
        themes: Optional[list[str]] = None,
    ) -> list[FactorCandidate]:
        """生成新因子候选项。"""
        if themes is None:
            themes = self._prompts.GENERATION_THEMES[:5]

        prompt = self._prompts.GENERATE_USER.format(
            columns=", ".join(data_columns),
            target=target,
            n=n_candidates,
            themes="\n".join(f"- {t}" for t in themes),
        )
        system = self._prompts.GENERATE_SYSTEM.format(
            columns=", ".join(data_columns),
        )

        try:
            response = self._backend.complete(prompt, system)
            candidates = self._parse_factors(response, generation=self._generation)
            logger.info("Generated %d factor candidates", len(candidates))
            return candidates
        except Exception as e:
            logger.error("Factor generation failed: %s", e)
            return []

    def mutate(
        self,
        factor: FactorCandidate,
        strategy: str = "",
    ) -> list[FactorCandidate]:
        """变异因子。"""
        import random
        if not strategy:
            strategy = random.choice(self._prompts.MUTATION_STRATEGIES)

        prompt = self._prompts.MUTATE_USER.format(
            name=factor.name,
            description=factor.description,
            code=factor.code,
            strategy=strategy,
        )

        try:
            response = self._backend.complete(prompt, self._prompts.MUTATE_SYSTEM)
            candidates = self._parse_factors(
                response,
                generation=factor.generation + 1,
                parent_ids=[factor.name],
            )
            logger.info("Mutated %s → %d variants", factor.name, len(candidates))
            return candidates
        except Exception as e:
            logger.error("Mutation failed for %s: %s", factor.name, e)
            return []

    def crossover(
        self,
        factor_a: FactorCandidate,
        factor_b: FactorCandidate,
    ) -> list[FactorCandidate]:
        """交叉两个因子。"""
        prompt = self._prompts.CROSSOVER_USER.format(
            name_a=factor_a.name, desc_a=factor_a.description, code_a=factor_a.code,
            name_b=factor_b.name, desc_b=factor_b.description, code_b=factor_b.code,
        )

        try:
            response = self._backend.complete(prompt, self._prompts.CROSSOVER_SYSTEM)
            gen = max(factor_a.generation, factor_b.generation) + 1
            candidates = self._parse_factors(
                response,
                generation=gen,
                parent_ids=[factor_a.name, factor_b.name],
            )
            logger.info(
                "Crossed %s × %s → %d candidates",
                factor_a.name, factor_b.name, len(candidates),
            )
            return candidates
        except Exception as e:
            logger.error("Crossover failed: %s", e)
            return []

    def run_cycle(
        self,
        data_columns: list[str],
        target: str = "10d_forward_return",
        n_generations: int = 3,
        n_candidates: int = 5,
        top_k: int = 3,
    ) -> list[FactorCandidate]:
        """运行完整的生成→变异→交叉周期。

        Args:
            data_columns: 可用数据列
            target: 预测目标
            n_generations: 进化代数
            n_candidates: 每代生成候选项数
            top_k: 每代保留最优数量

        Returns:
            最终筛选后的因子列表
        """
        all_factors: list[FactorCandidate] = []

        for gen in range(n_generations):
            self._generation = gen
            logger.info("=== Generation %d/%d ===", gen + 1, n_generations)

            if gen == 0:
                # 第一代：从零生成
                new_factors = self.generate(
                    data_columns, target, n_candidates,
                )
            else:
                # 后续代：变异 + 交叉
                new_factors = []

                # 变异低分因子
                bottom = sorted(all_factors, key=lambda f: f.quality_score)[:2]
                for f in bottom:
                    mutated = self.mutate(f)
                    new_factors.extend(mutated)

                # 交叉高分因子
                top = sorted(all_factors, key=lambda f: f.quality_score, reverse=True)[:3]
                if len(top) >= 2:
                    crossed = self.crossover(top[0], top[1])
                    new_factors.extend(crossed)

            all_factors.extend(new_factors)

        # 去重 + 按质量排序
        seen_names: set[str] = set()
        unique: list[FactorCandidate] = []
        for f in sorted(all_factors, key=lambda f: f.quality_score, reverse=True):
            if f.name not in seen_names:
                seen_names.add(f.name)
                unique.append(f)

        return unique[:top_k]

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    def _parse_factors(
        self,
        response: str,
        generation: int = 0,
        parent_ids: Optional[list[str]] = None,
    ) -> list[FactorCandidate]:
        """从 LLM 回复中解析因子候选项。"""
        candidates: list[FactorCandidate] = []

        # 按 ---FACTOR--- 分割
        blocks = re.split(r'---FACTOR---', response)
        if len(blocks) <= 1:
            # 尝试 ---IMPROVEMENT--- 格式
            blocks = re.split(r'---IMPROVEMENT---', response)
            if len(blocks) <= 1:
                # 尝试直接找 code block
                code_blocks = re.findall(r'```python\n(.*?)```', response, re.DOTALL)
                for i, code in enumerate(code_blocks):
                    candidates.append(FactorCandidate(
                        name=f"factor_gen_{generation}_{i}",
                        code=code.strip(),
                        description="Extracted from LLM response",
                        generation=generation,
                        parent_ids=parent_ids or [],
                    ))
                return candidates

        for block in blocks[1:]:  # 跳过第一个空块
            if not block.strip():
                continue

            name = self._extract_field(block, "NAME")
            desc = self._extract_field(block, "DESCRIPTION")
            formula = self._extract_field(block, "FORMULA")

            # 提取代码
            code_match = re.search(r'```python\n(.*?)```', block, re.DOTALL)
            if not code_match:
                code_match = re.search(r'```\n(.*?)```', block, re.DOTALL)
            code = code_match.group(1).strip() if code_match else ""

            if not name:
                name = f"factor_gen_{generation}_{len(candidates)}"
            if not desc:
                # 从代码 docstring 提取
                doc_match = re.search(r'"""(.*?)"""', code, re.DOTALL)
                desc = doc_match.group(1).strip() if doc_match else ""

            candidates.append(FactorCandidate(
                name=name.strip(),
                code=code,
                description=desc.strip(),
                formula=formula.strip() if formula else "",
                generation=generation,
                parent_ids=parent_ids or [],
            ))

        return candidates

    @staticmethod
    def _extract_field(text: str, field: str) -> str:
        """从文本中提取 NAME: / DESCRIPTION: 等字段。"""
        # 匹配 FIELD: value (直到下一行为止)
        pattern = rf'{field}:\s*(.+?)(?:\n\w+:|\n\n|\n```|---|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""


# ------------------------------------------------------------------
# 生成结果导出（供回测使用）
# ------------------------------------------------------------------


def factor_to_module(factors: list[FactorCandidate], module_name: str = "generated_factors") -> str:
    """将因子列表导出为可导入的 Python 模块代码。"""
    lines = [
        '# -*- coding: utf-8 -*-',
        f'"""Auto-generated alpha factors — {len(factors)} factors. """',
        '',
        'import numpy as np',
        'import pandas as pd',
        '',
        '',
    ]
    for f in factors:
        lines.append(f"# {f.description[:80]}")
        lines.append(f"# Formula: {f.formula}" if f.formula else "# (no formula)")
        lines.append(f.code)
        lines.append("")

    lines.append("")
    lines.append("# Factor registry")
    lines.append("ALL_FACTORS = [")
    for f in factors:
        lines.append(f"    {f.name},")
    lines.append("]")

    return "\n".join(lines)
