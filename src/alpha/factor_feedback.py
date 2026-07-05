# -*- coding: utf-8 -*-
"""因子反馈优化循环 — 回测结果驱动因子迭代。

借鉴 CogAlpha 论文的「金融反馈循环」(Financial Feedback Loop)：
  回测结果 → 识别弱因子 → LLM 分析失败原因 → 代码改进建议 → 重新生成

用法:
    from src.alpha.factor_gen import FactorPipeline, LLMBackend
    from src.alpha.factor_feedback import FactorFeedbackLoop

    pipeline = FactorPipeline(LLMBackend())
    loop = FactorFeedbackLoop(pipeline)
    improved = loop.optimize(
        factors=current_factors,
        backtest_results={
            "sharpe": 0.8, "max_dd": -0.15, "ic": 0.03,
            "factor_contributions": {"factor_a": 0.05, "factor_b": -0.01},
        },
        n_iterations=3,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .factor_gen import CogAlphaPrompts, FactorCandidate, FactorPipeline, LLMBackend

logger = logging.getLogger(__name__)


@dataclass
class BacktestFeedback:
    """回测反馈数据。"""
    # 总体指标
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    annual_volatility: float = 0.0

    # 因子级指标
    ic_mean: float = 0.0             # 平均 IC
    ic_std: float = 0.0              # IC 标准差
    rank_ic: float = 0.0             # Rank IC
    ic_decay: list[float] = field(default_factory=list)  # IC 衰减序列

    # 逐因子贡献
    factor_contributions: dict[str, float] = field(default_factory=dict)
    factor_ics: dict[str, float] = field(default_factory=dict)    # 每个因子的 IC
    factor_turnovers: dict[str, float] = field(default_factory=dict)

    # 风险指标
    factor_correlations: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def weak_factors(self) -> list[str]:
        """IC 低于阈值或贡献为负的因子。"""
        weak: list[str] = []
        for name, ic in self.factor_ics.items():
            if abs(ic) < 0.01:
                weak.append(name)
        for name, contrib in self.factor_contributions.items():
            if contrib < 0 and name not in weak:
                weak.append(name)
        return weak

    @property
    def strong_factors(self) -> list[str]:
        """IC 最高或贡献最大的因子。"""
        strong: list[str] = []
        if self.factor_ics:
            sorted_ics = sorted(self.factor_ics.items(), key=lambda x: abs(x[1]), reverse=True)
            strong = [name for name, _ in sorted_ics[:3]]
        return strong


@dataclass
class ImprovementSuggestion:
    """因子改进建议。"""
    factor_name: str
    reason: str                # 为什么需要改进
    issue: str                 # 具体问题
    suggested_change: str      # 建议的修改
    updated_code: str = ""     # 改进后的代码
    expected_impact: str = ""  # 预期效果
    priority: int = 1          # 1=最高, 3=最低


@dataclass
class OptimizationReport:
    """一次优化周期的报告。"""
    iteration: int
    weak_factors_before: list[str] = field(default_factory=list)
    suggestions: list[ImprovementSuggestion] = field(default_factory=list)
    improved_factors: list[FactorCandidate] = field(default_factory=list)
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    improvement_pct: float = 0.0


class FactorFeedbackLoop:
    """因子反馈优化循环。

    借鉴 CogAlpha 的 金融反馈 (Financial Feedback) 机制：
      1. 分析回测结果，识别弱因子
      2. 用 LLM 分析每个弱因子的失败原因
      3. 生成代码级改进建议
      4. 应用改进（变异/重生成）
      5. 验证改进效果
      6. 循环迭代直到收敛

    用法:
        loop = FactorFeedbackLoop(pipeline)
        report = loop.optimize(factors, backtest_results, n_iterations=3)
    """

    def __init__(
        self,
        pipeline: Optional[FactorPipeline] = None,
        backend: Optional[LLMBackend] = None,
    ):
        self._pipeline = pipeline or FactorPipeline(backend)
        self._backend = backend or self._pipeline._backend
        self._prompts = CogAlphaPrompts()

    def optimize(
        self,
        factors: list[FactorCandidate],
        feedback: BacktestFeedback,
        n_iterations: int = 3,
        top_n_weak: int = 3,
    ) -> tuple[list[FactorCandidate], list[OptimizationReport]]:
        """运行反馈优化循环。

        Args:
            factors: 当前因子列表
            feedback: 回测反馈数据
            n_iterations: 优化迭代次数
            top_n_weak: 每轮最多优化几个弱因子

        Returns:
            (improved_factors, optimization_reports)
        """
        current = list(factors)
        reports: list[OptimizationReport] = []

        for i in range(n_iterations):
            logger.info("=== Feedback Loop Iteration %d/%d ===", i + 1, n_iterations)

            report = OptimizationReport(
                iteration=i + 1,
                weak_factors_before=feedback.weak_factors,
                metrics_before={
                    "sharpe": feedback.sharpe,
                    "ic": feedback.ic_mean,
                    "n_factors": len(current),
                    "n_weak": len(feedback.weak_factors),
                },
            )

            # 1. 分析每个弱因子
            weak_to_fix = feedback.weak_factors[:top_n_weak]
            for weak_name in weak_to_fix:
                factor = next((f for f in current if f.name == weak_name), None)
                if factor is None:
                    continue

                suggestion = self._analyze_factor(factor, feedback)
                if suggestion:
                    report.suggestions.append(suggestion)

                    # 2. 应用改进
                    improved = self._apply_improvement(factor, suggestion)
                    if improved:
                        # 替换原因子
                        current = [f for f in current if f.name != weak_name]
                        current.extend(improved)
                        report.improved_factors.extend(improved)

            # 3. 交叉最强因子
            strong = feedback.strong_factors
            if len(strong) >= 2:
                f_a = next((f for f in current if f.name == strong[0]), None)
                f_b = next((f for f in current if f.name == strong[1]), None)
                if f_a and f_b:
                    crossed = self._pipeline.crossover(f_a, f_b)
                    current.extend(crossed)
                    report.improved_factors.extend(crossed)

            report.metrics_after = {
                "n_factors": len(current),
                "n_improved": len(report.improved_factors),
                "n_suggestions": len(report.suggestions),
            }
            reports.append(report)

        return current, reports

    def _analyze_factor(
        self, factor: FactorCandidate, feedback: BacktestFeedback,
    ) -> Optional[ImprovementSuggestion]:
        """用 LLM 分析因子失败原因，生成改进建议。"""
        ic_val = feedback.factor_ics.get(factor.name, 0.0)
        turnover = feedback.factor_turnovers.get(factor.name, 0.0)

        # 识别问题类型
        issues: list[str] = []
        if abs(ic_val) < 0.01:
            issues.append("IC 接近零，因子无预测能力")
        elif ic_val < 0:
            issues.append(f"IC 为负 ({ic_val:.4f})，因子方向可能反了")
        if turnover > 2.0:
            issues.append(f"换手率过高 ({turnover:.1f})，信号不稳定")
        if not issues:
            issues.append("综合贡献不足，需要增强")

        prompt = self._prompts.FEEDBACK_USER.format(
            name=factor.name,
            description=factor.description,
            ic_value=ic_val,
            rank_ic=feedback.rank_ic,
            sharpe=feedback.sharpe,
            max_dd=feedback.max_drawdown,
            turnover=turnover,
            code=factor.code,
            issues="\n".join(f"- {iss}" for iss in issues),
        )

        try:
            response = self._backend.complete(prompt, self._prompts.FEEDBACK_SYSTEM)
            return self._parse_suggestion(response, factor.name)
        except Exception as e:
            logger.error("Failed to analyze factor %s: %s", factor.name, e)
            return None

    def _apply_improvement(
        self, factor: FactorCandidate, suggestion: ImprovementSuggestion,
    ) -> list[FactorCandidate]:
        """应用改进建议 — 通过变异生成改进版。"""
        if suggestion.updated_code:
            # 直接使用 LLM 改进后的代码
            improved = FactorCandidate(
                name=f"{factor.name}_v2",
                code=suggestion.updated_code,
                description=f"Improved: {suggestion.reason[:100]}",
                generation=factor.generation + 1,
                parent_ids=[factor.name],
            )
            return [improved]
        else:
            # 通过变异生成
            return self._pipeline.mutate(
                factor, strategy=suggestion.suggested_change,
            )

    def _parse_suggestion(
        self, response: str, factor_name: str,
    ) -> Optional[ImprovementSuggestion]:
        """从 LLM 回复中解析改进建议。"""
        import re

        reason = ""
        change = ""
        code = ""

        reason_match = re.search(r'REASON:\s*(.+?)(?:\n\w+:|\n```|$)', response, re.DOTALL)
        if reason_match:
            reason = reason_match.group(1).strip()

        change_match = re.search(r'CHANGE:\s*(.+?)(?:\n\w+:|\n```|$)', response, re.DOTALL)
        if change_match:
            change = change_match.group(1).strip()

        code_match = re.search(r'```python\n(.*?)```', response, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()

        if not reason and not change:
            return None

        return ImprovementSuggestion(
            factor_name=factor_name,
            reason=reason,
            issue="Factor underperformance",
            suggested_change=change,
            updated_code=code,
        )

    @staticmethod
    def summary(reports: list[OptimizationReport]) -> str:
        """生成优化周期摘要。"""
        lines = ["因子反馈优化摘要", "=" * 40]
        for r in reports:
            before = r.metrics_before
            after = r.metrics_after
            lines.append(
                f"\n迭代 {r.iteration}: "
                f"弱因子 {before.get('n_weak', '?')}→{after.get('n_improved', 0)} 改进, "
                f"{len(r.suggestions)} 条建议"
            )
            for s in r.suggestions:
                lines.append(f"  💡 {s.factor_name}: {s.reason[:80]}")
        return "\n".join(lines)
