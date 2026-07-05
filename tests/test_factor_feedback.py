# -*- coding: utf-8 -*-
"""FactorFeedbackLoop + StrategyMutator 测试。"""

import pytest

from src.alpha.factor_gen import FactorCandidate, LLMBackend, FactorPipeline
from src.alpha.factor_feedback import (
    BacktestFeedback,
    FactorFeedbackLoop,
    ImprovementSuggestion,
    OptimizationReport,
)
from src.evolution.mutator import StrategyMutator, StrategyVariant


# ------------------------------------------------------------------
# BacktestFeedback 测试
# ------------------------------------------------------------------


class TestBacktestFeedback:
    def test_weak_factors_detection(self):
        fb = BacktestFeedback(
            factor_ics={"factor_a": 0.05, "factor_b": 0.005, "factor_c": -0.01},
            factor_contributions={"factor_a": 0.03, "factor_b": 0.01, "factor_c": -0.02},
        )
        weak = fb.weak_factors
        assert "factor_b" in weak    # IC < 0.01
        assert "factor_c" in weak    # 负贡献
        assert "factor_a" not in weak

    def test_strong_factors_detection(self):
        fb = BacktestFeedback(
            factor_ics={"factor_a": 0.05, "factor_b": 0.02, "factor_c": -0.01},
        )
        strong = fb.strong_factors
        assert strong[0] == "factor_a"  # 最高 |IC|
        assert len(strong) == 3

    def test_no_factors(self):
        fb = BacktestFeedback()
        assert fb.weak_factors == []
        assert fb.strong_factors == []


# ------------------------------------------------------------------
# FeedbackLoop 测试
# ------------------------------------------------------------------


class MockFeedbackLLM(LLMBackend):
    def __init__(self):
        super().__init__(custom_call=self._call)

    def _call(self, prompt: str):
        if "underperform" in prompt.lower() or "FEEDBACK" in prompt:
            return """---IMPROVEMENT---
REASON: The factor uses too short a window for the signal to be stable
CHANGE: Increase lookback from 5 to 20 days and add volume confirmation
NEW_CODE:
```python
def improved_factor(df):
    df_copy = df.copy()
    ret = df_copy['close'].pct_change(20)
    vol = df_copy['volume'].rolling(20).mean()
    df_copy['improved_factor'] = ret / (vol + 1e-9)
    return df_copy['improved_factor']
```
---END---"""
        if "mutation" in prompt.lower():
            return """---VARIANT---
NAME: test_variant_v1_param_tuning
MUTATION: Adjusted window from 5 to 15 days
TYPE: factor
DESCRIPTION: Momentum factor with longer window
ENTRY:
- Price above 20-day MA
- Volume above 1M
EXIT:
- Stop loss at 5%
PARAMETERS: {"window": 15, "threshold": 0.6}
---END---"""
        return "test response"


class TestFactorFeedbackLoop:
    @pytest.fixture
    def loop(self):
        backend = MockFeedbackLLM()
        pipeline = FactorPipeline(backend)
        return FactorFeedbackLoop(pipeline, backend)

    def test_optimize_with_feedback(self, loop):
        factors = [
            FactorCandidate(
                name="factor_momentum_5d",
                code="def factor_momentum_5d(df):\n    return df['close'].pct_change(5)",
                description="5-day momentum",
            ),
            FactorCandidate(
                name="factor_vol_adj",
                code="def factor_vol_adj(df):\n    return df['close'].pct_change(5) / df['volume'].rolling(5).std()",
                description="Vol-adjusted momentum",
            ),
        ]
        feedback = BacktestFeedback(
            sharpe=0.8,
            max_drawdown=-0.15,
            ic_mean=0.03,
            rank_ic=0.04,
            factor_ics={"factor_momentum_5d": 0.005, "factor_vol_adj": 0.04},
            factor_contributions={"factor_momentum_5d": -0.01, "factor_vol_adj": 0.05},
            factor_turnovers={"factor_momentum_5d": 1.5},
        )

        improved, reports = loop.optimize(factors, feedback, n_iterations=2, top_n_weak=2)
        assert isinstance(improved, list)
        assert len(reports) == 2

    def test_summary(self, loop):
        factors = [
            FactorCandidate(name="f1", code="def f1(df):\n    return df['close']", description="test"),
        ]
        feedback = BacktestFeedback(
            sharpe=0.5,
            factor_ics={"f1": 0.03},
            factor_contributions={"f1": 0.02},
        )
        _, reports = loop.optimize(factors, feedback, n_iterations=1)
        summary = FactorFeedbackLoop.summary(reports)
        assert "因子反馈优化" in summary


class TestImprovementSuggestion:
    def test_default_priority(self):
        s = ImprovementSuggestion(
            factor_name="test",
            reason="Low IC",
            issue="No predictive power",
            suggested_change="Increase window",
        )
        assert s.priority == 1


# ------------------------------------------------------------------
# StrategyMutator 测试
# ------------------------------------------------------------------


class MockStrategy:
    """模拟 ExtractedStrategy。"""
    def __init__(self, name="test_strategy", paper_id="test_paper_001"):
        self.strategy_name = name
        self.paper_id = paper_id
        self.description = "A momentum-based strategy with mean-reversion filter"
        self.strategy_type = "factor"
        self.entry_conditions = [
            "Price above 20-day MA",
            "RSI(14) < 70",
            "Volume > 500,000 shares",
        ]
        self.exit_conditions = [
            "Price below 10-day MA",
            "Stop loss at 5%",
        ]
        self.parameters = {"lookback": 20, "rsi_threshold": 70, "stop_loss": 0.05}
        self.extraction_confidence = 0.75
        self.unsourced_fields = []
        self.sourced_fields = ["entry_conditions", "parameters"]


class TestStrategyMutator:
    @pytest.fixture
    def strategy(self):
        return MockStrategy()

    @pytest.fixture
    def mutator(self):
        return StrategyMutator(backend=MockFeedbackLLM())

    def test_mutate_rule_based(self, strategy):
        """无 LLM 回退 → 规则驱动变异。"""
        mutator = StrategyMutator(backend=None)
        variants = mutator.mutate(strategy, n_variants=3)
        assert len(variants) == 3
        for v in variants:
            assert isinstance(v, StrategyVariant)
            assert v.mutation_type == "mutation"
            assert v.generation == 1
            assert v.parent_id == "test_paper_001"

    def test_mutate_with_llm(self, mutator, strategy):
        variants = mutator.mutate(strategy, n_variants=3)
        assert len(variants) >= 1

    def test_crossover_rule_based(self, strategy):
        strategy_b = MockStrategy(name="value_strategy", paper_id="test_paper_002")
        strategy_b.strategy_type = "screening"
        strategy_b.entry_conditions = ["PE < 15", "ROE > 15%"]
        strategy_b.exit_conditions = ["PE > 25"]

        mutator = StrategyMutator(backend=None)
        crossed = mutator.crossover(strategy, strategy_b)
        assert len(crossed) == 1
        hybrid = crossed[0]
        assert hybrid.mutation_type == "crossover"
        # 合并了 entry conditions
        assert len(hybrid.entry_conditions) >= 3
        # 合并了 exit conditions
        assert len(hybrid.exit_conditions) >= 2

    def test_evolve_generation(self, strategy):
        strategy_b = MockStrategy(name="value_strategy", paper_id="test_paper_002")
        strategy_b.extraction_confidence = 0.60

        mutator = StrategyMutator(backend=None)
        results = mutator.evolve_generation(
            [strategy, strategy_b],
            n_variants_per=2,
            n_crossovers=1,
        )
        assert len(results) >= 1
        for sid, variants in results.items():
            assert all(isinstance(v, StrategyVariant) for v in variants)

    def test_to_extracted_strategy(self):
        from src.evolution.mutator import to_extracted_strategy

        variant = StrategyVariant(
            name="test_v1",
            description="Improved momentum",
            strategy_type="factor",
            entry_conditions=["Price > MA20"],
            exit_conditions=["Stop 5%"],
            parameters={"window": 15},
            parent_id="paper_001",
            confidence=0.6,
        )
        d = to_extracted_strategy(variant)
        assert d["strategy_name"] == "test_v1"
        assert d["strategy_type"] == "factor"
        assert len(d["entry_conditions"]) == 1
        assert d["extraction_confidence"] == 0.6

    def test_parse_variants(self):
        response = """---VARIANT---
NAME: factor_momentum_v1
MUTATION: Increased window to 30 days
TYPE: factor
DESCRIPTION: Long-window momentum strategy
ENTRY:
- Close > MA(30)
- Volume > 20d avg
EXIT:
- Close < MA(10)
- Stop at 3%
PARAMETERS: {"window": 30, "stop": 0.03}
---END---
---VARIANT---
NAME: factor_momentum_v2
MUTATION: Added volume filter
TYPE: factor
DESCRIPTION: Volume-filtered momentum
ENTRY:
- Close > MA(20)
- Volume > 1.5x 20d avg
EXIT:
- Close < MA(10)
PARAMETERS: {"window": 20, "volume_mult": 1.5}
---END---"""
        mutator = StrategyMutator(backend=None)
        variants = mutator._parse_variants(response, parent_id="test")
        assert len(variants) == 2
        assert variants[0].name == "factor_momentum_v1"
        assert variants[0].parameters == {"window": 30, "stop": 0.03}
        assert "Close > MA(30)" in variants[0].entry_conditions
        assert variants[1].mutation_type == "mutation"
