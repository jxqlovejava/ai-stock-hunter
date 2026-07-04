# -*- coding: utf-8 -*-
"""策略进化编排器。

实现完整的「回测→分析→校准→验证→部署」进化飞轮。

流程:
  1. collect_evidence() — 汇总回测结果 + 用户反馈 + 信号质量
  2. analyze_gaps() — 识别策略弱点（哪些市场环境表现差）
  3. propose_changes() — 生成参数调整建议
  4. backtest_validate() — 回测验证新参数
  5. deploy() — 更新策略版本到注册中心

用法:
    pipeline = EvolutionPipeline(
        engine_factory=make_engine,
        registry=StrategyRegistry(),
        feedback=FeedbackCollector(),
        calibrator=RuleCalibrator(),
    )
    record = pipeline.evolve("MVP1", start="2015-01-01", end="2024-12-31")
    print(f"进化完成: {record.new_version}, Sharpe: {record.validated_sharpe:.2f}")
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .calibrator import (
    CalibrationResult,
    FactorCalibrator,
    RiskParamCalibrator,
    RuleCalibrator,
)


class EvolutionStatus(Enum):
    PENDING = "pending"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    PROPOSING = "proposing"
    VALIDATING = "validating"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class GapAnalysis:
    """策略弱点分析结果。"""

    strategy_name: str = ""
    weak_markets: list[str] = field(default_factory=list)  # 表现差的市场环境
    weak_factors: list[str] = field(default_factory=list)   # 失效的因子
    risk_issues: list[str] = field(default_factory=list)    # 风险问题
    performance_gap: float = 0.0       # 与基准的收益差
    max_drawdown_period: str = ""      # 最大回撤发生时段
    summary: str = ""


@dataclass
class ProposedChange:
    """参数调整建议。"""

    param_name: str
    old_value: float
    new_value: float
    reason: str
    confidence: float = 0.5  # 0-1, 基于证据强度
    source: str = ""         # "backtest" | "feedback" | "calibrator"


@dataclass
class EvolutionRecord:
    """一次进化记录。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    strategy_name: str = ""
    old_version: str = ""
    new_version: str = ""
    status: EvolutionStatus = EvolutionStatus.PENDING

    # 各阶段输出
    calibration: Optional[CalibrationResult] = None
    gaps: Optional[GapAnalysis] = None
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    applied_params: dict[str, Any] = field(default_factory=dict)

    # 验证结果
    validated_sharpe: Optional[float] = None
    validated_return: Optional[float] = None
    validated_max_dd: Optional[float] = None
    validation_passed: bool = False

    # 元数据
    feedback_count: int = 0
    signal_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error_message: str = ""


class EvolutionPipeline:
    """策略进化编排器。

    协调回测引擎、反馈系统、校准器和注册中心，
    执行完整的策略进化流程。

    用法:
        pipeline = EvolutionPipeline(engine_factory, registry)
        record = pipeline.evolve("MVP1", "2015-01-01", "2024-12-31")
    """

    # 进化触发条件
    MIN_FEEDBACK_TO_EVOLVE = 5
    MIN_TRADES_TO_EVOLVE = 10
    MIN_SHARPE_IMPROVEMENT = 0.05  # 新策略需比旧策略 Sharpe 高 0.05 以上

    def __init__(
        self,
        engine_factory: Callable[[], Any],
        registry: Any = None,
        feedback: Any = None,
        rule_calibrator: Optional[RuleCalibrator] = None,
        factor_calibrator: Optional[FactorCalibrator] = None,
        risk_calibrator: Optional[RiskParamCalibrator] = None,
    ):
        """初始化进化管线。

        Args:
            engine_factory: 创建回测引擎的工厂函数
            registry: StrategyRegistry 实例
            feedback: FeedbackCollector 实例
            rule_calibrator: RuleCalibrator 实例
            factor_calibrator: FactorCalibrator 实例
            risk_calibrator: RiskParamCalibrator 实例
        """
        self._engine_factory = engine_factory
        self._registry = registry
        self._feedback = feedback
        self._rule_cal = rule_calibrator or RuleCalibrator()
        self._factor_cal = factor_calibrator or FactorCalibrator()
        self._risk_cal = risk_calibrator or RiskParamCalibrator()

    def evolve(
        self,
        strategy_name: str,
        start: str,
        end: str,
        strategy_cls: Optional[type] = None,
        validate_start: Optional[str] = None,
        validate_end: Optional[str] = None,
        force: bool = False,
    ) -> EvolutionRecord:
        """执行策略进化。

        Args:
            strategy_name: 策略名称
            start: 训练期起始日
            end: 训练期结束日
            strategy_cls: 策略类
            validate_start: 验证期起始（默认 = end + 1 天到 end + 2 年）
            validate_end: 验证期结束
            force: 强制进化，即使证据不足

        Returns:
            EvolutionRecord 完整进化记录
        """
        record = EvolutionRecord(strategy_name=strategy_name)

        # Step 0: 检查进化条件
        record.status = EvolutionStatus.COLLECTING
        if not force:
            fb_count = self._feedback.count() if self._feedback else 0
            record.feedback_count = fb_count
            if fb_count < self.MIN_FEEDBACK_TO_EVOLVE:
                record.status = EvolutionStatus.REJECTED
                record.error_message = (
                    f"反馈不足 ({fb_count} < {self.MIN_FEEDBACK_TO_EVOLVE})，"
                    "无法触发进化。使用 force=True 强制进化。"
                )
                return record

        # Step 1: 收集证据 & 校准
        try:
            calibration = self._run_calibration()
            record.calibration = calibration
        except Exception as e:
            record.status = EvolutionStatus.ERROR
            record.error_message = f"校准失败: {e}"
            return record

        # Step 2: 分析策略弱点
        record.status = EvolutionStatus.ANALYZING
        try:
            gaps = self._analyze_gaps(strategy_name)
            record.gaps = gaps
        except Exception as e:
            record.status = EvolutionStatus.ERROR
            record.error_message = f"弱点分析失败: {e}"
            return record

        # Step 3: 生成参数调整建议
        record.status = EvolutionStatus.PROPOSING
        changes = self._propose_changes(calibration, gaps)
        record.proposed_changes = changes

        if not changes:
            record.status = EvolutionStatus.REJECTED
            record.error_message = "未发现需要调整的参数，策略已是最优。"
            return record

        # Step 4: 回测验证
        record.status = EvolutionStatus.VALIDATING
        applied = self._apply_changes_to_params(
            strategy_name, changes, strategy_cls
        )
        record.applied_params = applied

        # 读取旧版本参数
        old_params = {}
        old_sharpe = 0.0
        if self._registry:
            latest = self._registry.get_latest(strategy_name)
            if latest:
                record.old_version = latest.version
                old_params = latest.params
                old_sharpe = latest.metrics.get("sharpe_ratio", 0) or 0

        try:
            engine = self._engine_factory()
            if strategy_cls is not None:
                engine.add_strategy(strategy_cls, **applied)

            result = engine.run(start, end)
            record.validated_sharpe = result.sharpe_ratio
            record.validated_return = result.total_return
            record.validated_max_dd = result.max_drawdown
            record.validation_passed = (
                result.sharpe_ratio > old_sharpe + self.MIN_SHARPE_IMPROVEMENT
            )

            if validate_start and validate_end:
                engine2 = self._engine_factory()
                if strategy_cls is not None:
                    engine2.add_strategy(strategy_cls, **applied)
                engine2.run(validate_start, validate_end)

        except Exception as e:
            record.status = EvolutionStatus.ERROR
            record.error_message = f"回测验证失败: {e}"
            return record

        # Step 5: 部署
        if record.validation_passed or force:
            record.status = EvolutionStatus.DEPLOYED
            if self._registry:
                # 生成新版本号
                old_ver = record.old_version or "0.0.0"
                new_ver = self._bump_version(old_ver)
                record.new_version = new_ver

                self._registry.register(
                    name=strategy_name,
                    version=new_ver,
                    params=applied,
                    description=f"进化: {len(changes)} 项参数调整",
                    parent_version=record.old_version or None,
                    metrics={
                        "sharpe_ratio": record.validated_sharpe or 0,
                        "total_return": record.validated_return or 0,
                        "max_drawdown": record.validated_max_dd or 0,
                    },
                )
        else:
            record.status = EvolutionStatus.REJECTED
            record.error_message = (
                f"验证未通过: Sharpe ({record.validated_sharpe:.2f}) "
                f"未显著优于旧版 ({old_sharpe:.2f})"
            )

        return record

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _run_calibration(self) -> CalibrationResult:
        """运行所有校准器。"""
        rule_result = self._rule_cal.calibrate()
        factor_result = self._factor_cal.calibrate()
        risk_result = self._risk_cal.calibrate()

        # 合并校准结果
        merged = CalibrationResult(
            total_rules=rule_result.total_rules,
            total_factors=factor_result.total_factors,
        )
        merged.adjustments = (
            rule_result.adjustments
            + factor_result.adjustments
            + risk_result.adjustments
        )
        merged.skipped = (
            rule_result.skipped
            + factor_result.skipped
            + risk_result.skipped
        )
        return merged

    def _analyze_gaps(self, strategy_name: str) -> GapAnalysis:
        """分析策略弱点。"""
        gaps = GapAnalysis(strategy_name=strategy_name)

        # 从反馈中提取弱点信号
        if self._feedback:
            disagreements = self._feedback.get_disagreements(strategy_name)
            if disagreements:
                reasons = [d.reason for d in disagreements if d.reason]
                gaps.summary = f"用户主要分歧: {'; '.join(reasons[:3])}"
                gaps.weak_factors = list(set(
                    d.reason for d in disagreements if d.reason
                ))[:5]

            # 检查是否在市场极端时产生分歧
            # （简化版：从反馈理由中提取关键词）
            extreme_keywords = ["暴跌", "暴涨", "恐慌", "过热", "极端"]
            for d in disagreements:
                for kw in extreme_keywords:
                    if kw in d.reason:
                        gaps.weak_markets.append(f"极端市场 ({kw})")
                        break

        # 从校准结果中提取风险问题
        if self._rule_cal:
            for rule_id, stats in self._rule_cal._rules.items():
                total = stats["fp"] + stats["fn"] + stats["correct"]
                if total >= 5 and stats["fn"] > 0:
                    gaps.risk_issues.append(
                        f"规则 {rule_id} 存在漏报 (FN={stats['fn']})"
                    )

        return gaps

    def _propose_changes(
        self,
        calibration: CalibrationResult,
        gaps: GapAnalysis,
    ) -> list[ProposedChange]:
        """基于校准结果和弱点分析生成参数调整建议。"""
        changes: list[ProposedChange] = []

        # 从校准结果生成建议
        for adj in calibration.adjustments:
            changes.append(ProposedChange(
                param_name=adj.target,
                old_value=adj.old_value,
                new_value=adj.new_value,
                reason=adj.reason,
                confidence=min(1.0, adj.evidence_count / 20),
                source="calibrator",
            ))

        # 从风险问题生成建议
        for issue in gaps.risk_issues:
            if "漏报" in issue:
                # 建议收紧相关风控参数
                changes.append(ProposedChange(
                    param_name="risk_margin",
                    old_value=1.0,
                    new_value=1.15,
                    reason=issue,
                    confidence=0.6,
                    source="feedback",
                ))

        return changes

    def _apply_changes_to_params(
        self,
        strategy_name: str,
        changes: list[ProposedChange],
        strategy_cls: Optional[type] = None,
    ) -> dict[str, Any]:
        """将调整建议应用到策略参数。"""
        # 从旧版本参数开始
        params: dict[str, Any] = {}
        if self._registry:
            latest = self._registry.get_latest(strategy_name)
            if latest:
                params = dict(latest.params)

        # 如果有 strategy_cls，获取默认参数
        if strategy_cls and hasattr(strategy_cls, "params"):
            for k, v in strategy_cls.params.__dict__.items():
                if k not in params:
                    params[k] = v

        # 应用变更
        for change in changes:
            if change.confidence >= 0.4:  # 只应用高置信度变更
                params[change.param_name] = change.new_value

        return params

    @staticmethod
    def _bump_version(version: str) -> str:
        """版本号递增（patch +1）。"""
        try:
            parts = version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        except (ValueError, IndexError):
            return "1.0.0"
