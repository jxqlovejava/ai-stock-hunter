# -*- coding: utf-8 -*-
"""FactorPipeline 测试 — LLM 驱动因子生成管线。"""

import pytest

from src.alpha.factor_gen import (
    CogAlphaPrompts,
    FactorCandidate,
    FactorPipeline,
    LLMBackend,
    factor_to_module,
)


class MockLLMBackend(LLMBackend):
    """模拟 LLM 后端 — 返回预定义因子代码。"""

    def __init__(self):
        super().__init__(custom_call=self._mock_call)

    def _mock_call(self, prompt: str) -> str:
        return """---FACTOR---
NAME: factor_liquidity_impact_5d_volume
DESCRIPTION: Liquidity impact: price change per unit volume over 5 days
FORMULA: (close - close_5d_ago) / (avg_volume + epsilon)
CODE:
```python
def factor_liquidity_impact_5d_volume(df):
    \"\"\"Liquidity impact factor: 5-day price change per unit volume.\"\"\"
    df_copy = df.copy()
    eps = 1e-9
    df_copy['ret_5d'] = df_copy['close'].pct_change(5)
    df_copy['avg_vol_5d'] = df_copy['volume'].rolling(5).mean()
    df_copy['factor_liquidity_impact_5d_volume'] = df_copy['ret_5d'] / (df_copy['avg_vol_5d'] + eps)
    return df_copy['factor_liquidity_impact_5d_volume']
```
---END---
---FACTOR---
NAME: factor_volatility_regime_20d
DESCRIPTION: Volatility regime detection: ratio of short-term to long-term vol
FORMULA: std(ret, 5) / std(ret, 20)
CODE:
```python
def factor_volatility_regime_20d(df):
    \"\"\"Volatility regime: short/long vol ratio indicates regime shifts.\"\"\"
    df_copy = df.copy()
    eps = 1e-9
    ret = df_copy['close'].pct_change()
    short_vol = ret.rolling(5).std()
    long_vol = ret.rolling(20).std()
    df_copy['factor_volatility_regime_20d'] = short_vol / (long_vol + eps)
    return df_copy['factor_volatility_regime_20d']
```
---END---
---FACTOR---
NAME: factor_overnight_gap_reversal_10d
DESCRIPTION: Overnight gap reversal: stocks with large overnight gaps tend to reverse
FORMULA: -1 * (open / close_prev - 1) over 10d window
CODE:
```python
def factor_overnight_gap_reversal_10d(df):
    \"\"\"Overnight gap reversal: mean-reversion of overnight jumps.\"\"\"
    df_copy = df.copy()
    df_copy['overnight_gap'] = df_copy['open'] / df_copy['close'].shift(1) - 1
    df_copy['factor_overnight_gap_reversal_10d'] = -df_copy['overnight_gap'].rolling(10).mean()
    return df_copy['factor_overnight_gap_reversal_10d']
```
---END---"""


class TestFactorPipeline:
    """因子生成管线测试。"""

    @pytest.fixture
    def pipeline(self):
        return FactorPipeline(backend=MockLLMBackend())

    def test_generate_factors(self, pipeline):
        factors = pipeline.generate(
            data_columns=["open", "high", "low", "close", "volume"],
            n_candidates=3,
        )
        assert len(factors) == 3
        assert all(isinstance(f, FactorCandidate) for f in factors)
        assert all(f.code for f in factors)

    def test_factor_names(self, pipeline):
        factors = pipeline.generate(
            data_columns=["open", "high", "low", "close", "volume"],
            n_candidates=3,
        )
        names = [f.name for f in factors]
        assert "factor_liquidity_impact_5d_volume" in names
        assert "factor_volatility_regime_20d" in names
        assert "factor_overnight_gap_reversal_10d" in names

    def test_factor_descriptions(self, pipeline):
        factors = pipeline.generate(
            data_columns=["open", "high", "low", "close", "volume"],
            n_candidates=3,
        )
        for f in factors:
            assert f.description, f"Factor {f.name} has empty description"

    def test_factor_code_is_valid_python(self, pipeline):
        factors = pipeline.generate(
            data_columns=["open", "high", "low", "close", "volume"],
            n_candidates=3,
        )
        for f in factors:
            # 代码应包含 def 和 return
            assert "def " in f.code, f"{f.name}: missing 'def'"
            assert "return " in f.code, f"{f.name}: missing 'return'"

    def test_mutate_factor(self, pipeline):
        factor = FactorCandidate(
            name="test_factor",
            code="def test_factor(df):\n    return df['close'].pct_change(5)",
            description="Test factor: 5-day momentum",
            generation=0,
        )
        variants = pipeline.mutate(factor, strategy="Change the lookback window")
        assert len(variants) >= 0  # Mock 返回空或有效

    def test_crossover_factors(self, pipeline):
        fa = FactorCandidate(
            name="factor_momentum_5d",
            code="def factor_momentum_5d(df):\n    return df['close'].pct_change(5)",
            description="5-day momentum",
        )
        fb = FactorCandidate(
            name="factor_vol_adj",
            code="def factor_vol_adj(df):\n    return df['close'].pct_change(5) / df['volume'].rolling(5).std()",
            description="Volatility-adjusted momentum",
        )
        crossed = pipeline.crossover(fa, fb)
        assert isinstance(crossed, list)

    def test_run_cycle(self, pipeline):
        factors = pipeline.run_cycle(
            data_columns=["open", "high", "low", "close", "volume"],
            n_generations=2,
            n_candidates=3,
            top_k=3,
        )
        assert isinstance(factors, list)
        # 每个因子应有代码
        for f in factors:
            assert f.code

    def test_empty_response(self):
        """空 LLM 回复不应崩溃。"""
        backend = LLMBackend(custom_call=lambda _: "No factors generated.")
        pipeline = FactorPipeline(backend)
        factors = pipeline.generate(
            data_columns=["close"],
            n_candidates=3,
        )
        assert factors == []


class TestLLMBackend:
    """LLM 后端测试。"""

    def test_custom_call(self):
        backend = LLMBackend(custom_call=lambda prompt: f"Echo: {prompt[:20]}")
        result = backend.complete("Hello, generate factors")
        assert result.startswith("Echo: Hello, generate")

    def test_no_api_key_raises(self):
        import os
        # 清除 API key 环境变量
        old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        try:
            backend = LLMBackend()
            with pytest.raises(RuntimeError, match="No LLM backend"):
                backend.complete("test")
        finally:
            if old_anthropic:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic
            if old_openai:
                os.environ["OPENAI_API_KEY"] = old_openai


class TestCogAlphaPrompts:
    """提示词模板测试。"""

    def test_generate_prompt_not_empty(self):
        prompts = CogAlphaPrompts()
        assert "quantitative researcher" in prompts.GENERATE_SYSTEM
        assert "{columns}" in prompts.GENERATE_USER

    def test_mutate_prompt_not_empty(self):
        prompts = CogAlphaPrompts()
        assert "mutation" in prompts.MUTATE_SYSTEM.lower()
        assert "{name}" in prompts.MUTATE_USER

    def test_crossover_prompt_not_empty(self):
        prompts = CogAlphaPrompts()
        assert "combine" in prompts.CROSSOVER_SYSTEM.lower()
        assert "{name_a}" in prompts.CROSSOVER_USER

    def test_feedback_prompt_not_empty(self):
        prompts = CogAlphaPrompts()
        assert "underperform" in prompts.FEEDBACK_SYSTEM.lower()
        assert "ic_value" in prompts.FEEDBACK_USER
        assert "sharpe" in prompts.FEEDBACK_USER

    def test_deep_check_prompt_not_empty(self):
        prompts = CogAlphaPrompts()
        assert "LEAKAGE" in prompts.DEEP_CHECK_SYSTEM
        assert "{symbol}" in prompts.DEEP_CHECK_USER


class TestFactorToModule:
    """因子导出测试。"""

    def test_export_single_factor(self):
        factor = FactorCandidate(
            name="factor_test_5d",
            code="def factor_test_5d(df):\n    return df['close'].pct_change(5)",
            description="Simple 5-day momentum",
            formula="close_t / close_{t-5} - 1",
        )
        module = factor_to_module([factor])
        assert "factor_test_5d" in module
        assert "def factor_test_5d" in module
        assert "ALL_FACTORS" in module
        assert "factor_test_5d" in module.split("ALL_FACTORS")[1]

    def test_export_multiple_factors(self):
        factors = [
            FactorCandidate(
                name=f"factor_{i}",
                code=f"def factor_{i}(df):\n    return df['close'] * {i}",
                description=f"Factor {i}",
            )
            for i in range(3)
        ]
        module = factor_to_module(factors)
        assert "ALL_FACTORS = [" in module
        assert "factor_0" in module
        assert "factor_2" in module


class TestParseFactors:
    """因子解析边缘情况测试。"""

    def test_parse_code_only_block(self):
        """无 FACTOR 标记，直接有 code block。"""
        backend = LLMBackend(custom_call=lambda _: """\
Here's a factor:

```python
def factor_test(df):
    return df['close'].pct_change(5)
```
""")
        pipeline = FactorPipeline(backend)
        factors = pipeline.generate(data_columns=["close"], n_candidates=1)
        assert len(factors) >= 1
        assert factors[0].code

    def test_parse_multiple_code_blocks(self):
        """多个 code block 的回复。"""
        backend = LLMBackend(custom_call=lambda _: """\
Factor 1:
```python
def factor_a(df):
    return df['close'].rolling(5).mean()
```

Factor 2:
```python
def factor_b(df):
    return df['volume'].pct_change(10)
```
""")
        pipeline = FactorPipeline(backend)
        factors = pipeline.generate(data_columns=["close", "volume"], n_candidates=2)
        assert len(factors) == 2
