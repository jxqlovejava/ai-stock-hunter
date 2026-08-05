# -*- coding: utf-8 -*-
"""策略权重校准器。

基于用户反馈数据和回测结果，动态校准:
  1. 军规权重 — 根据误报/漏报率调整各规则的 block/warn 级别
  2. 因子权重 — 根据实际表现调整 PE/ROE/北向资金等因子在评分中的权重
  3. 风险参数 — 根据用户反馈调整止损线、仓位上限等
  4. 置信度校准 — 根据预测 vs 实际结果校准系统置信度

校准原则:
  - 渐进式: 每次调整幅度 ≤ ±10%，防止单次反馈过度影响
  - 证据门槛: 至少 5 条反馈才触发校准
  - 可回滚: 校准记录保存，支持撤销

用法:
    calibrator = RuleCalibrator()
    calibrator.record_false_positive("r001", "正常交易被误拦")
    result = calibrator.calibrate()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 聚合运气评估复用 Alpha 归因模块的实现（learner→alpha 既有依赖方向）。
# 避免反向依赖形成循环导入。
from src.alpha.attribution import LuckAssessment, LuckBiasDetector


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CalibrationRecord:
    """校准记录。"""

    target: str
    dimension: str  # "rule_weight" | "factor_weight" | "risk_param" | "confidence"
    old_value: float
    new_value: float
    reason: str
    evidence_count: int
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CalibrationResult:
    """校准结果。"""

    adjustments: list[CalibrationRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_rules: int = 0
    total_factors: int = 0

    @property
    def changed_count(self) -> int:
        return len(self.adjustments)

    @property
    def summary(self) -> str:
        lines = [
            f"# 校准结果: {self.changed_count} 项调整, {len(self.skipped)} 项跳过",
        ]
        for adj in self.adjustments:
            direction = "↑" if adj.new_value > adj.old_value else "↓"
            lines.append(
                f"  {direction} {adj.target}: {adj.old_value:.2f} → {adj.new_value:.2f} "
                f"({adj.reason})"
            )
        return "\n".join(lines)


@dataclass
class CalibrationReport:
    """置信度校准报告（兼容旧 API）。"""

    period: str = ""
    total_predictions: int = 0
    sample_sufficient: bool = False
    accuracy_by_band: Optional[dict] = None
    system_return: float = 0.0
    user_return: float = 0.0
    behavior_gap: float = 0.0


# ---------------------------------------------------------------------------
# Rule Calibrator
# ---------------------------------------------------------------------------


class RuleCalibrator:
    """军规/博弈论规则权重校准器。

    统计每条规则的误报（false positive）和漏报（false negative），
    动态调整其严重级别权重。

    公式:
      - 误报率 = FP / (FP + 正确拦截)
      - 漏报率 = FN / (FN + 正确拦截)
      - 权重调整 = clip(原权重 × (1 + 漏报率 - 误报率), 原权重×0.5, 原权重×1.5)
    """

    MIN_EVIDENCE = 5
    MAX_ADJUSTMENT = 0.10

    def __init__(self):
        self._rules: dict[str, dict] = {}
        self._history: list[CalibrationRecord] = []

    def register_rule(self, rule_id: str, initial_weight: float = 1.0):
        """注册一条规则。"""
        self._rules[rule_id] = {
            "fp": 0,
            "fn": 0,
            "correct": 0,
            "weight": initial_weight,
        }

    def register_rules(self, rule_ids: list[str], initial_weight: float = 1.0):
        """批量注册规则。"""
        for rid in rule_ids:
            self.register_rule(rid, initial_weight)

    def record_false_positive(self, rule_id: str, detail: str = ""):
        """记录误报：规则拦截了正常交易。"""
        if rule_id not in self._rules:
            self.register_rule(rule_id)
        self._rules[rule_id]["fp"] += 1

    def record_false_negative(self, rule_id: str, detail: str = ""):
        """记录漏报：应拦截但未拦截。"""
        if rule_id not in self._rules:
            self.register_rule(rule_id)
        self._rules[rule_id]["fn"] += 1

    def record_correct(self, rule_id: str):
        """记录正确拦截。"""
        if rule_id not in self._rules:
            self.register_rule(rule_id)
        self._rules[rule_id]["correct"] += 1

    def get_rule_stats(self, rule_id: str) -> Optional[dict]:
        """获取某规则的统计信息。"""
        return self._rules.get(rule_id)

    def calibrate(self) -> CalibrationResult:
        """执行校准，返回调整结果。"""
        result = CalibrationResult(total_rules=len(self._rules))

        for rule_id, stats in self._rules.items():
            total_events = stats["fp"] + stats["fn"] + stats["correct"]
            if total_events < self.MIN_EVIDENCE:
                result.skipped.append(
                    f"{rule_id}: 证据不足 ({total_events} < {self.MIN_EVIDENCE})"
                )
                continue

            fp_rate = stats["fp"] / total_events if total_events > 0 else 0
            fn_rate = stats["fn"] / total_events if total_events > 0 else 0
            old_weight = stats["weight"]

            adjustment_factor = 1.0 + fn_rate * 0.5 - fp_rate * 0.3
            adjustment_factor = max(0.5, min(1.5, adjustment_factor))
            new_weight = round(old_weight * adjustment_factor, 4)

            if abs(new_weight - old_weight) > self.MAX_ADJUSTMENT * old_weight:
                direction = 1 if new_weight > old_weight else -1
                new_weight = round(
                    old_weight * (1 + direction * self.MAX_ADJUSTMENT), 4
                )

            if abs(new_weight - old_weight) < 0.001:
                result.skipped.append(
                    f"{rule_id}: 权重几乎不变 ({old_weight:.4f})"
                )
                continue

            stats["weight"] = new_weight
            record = CalibrationRecord(
                target=rule_id,
                dimension="rule_weight",
                old_value=old_weight,
                new_value=new_weight,
                reason=f"FP率={fp_rate:.2%}, FN率={fn_rate:.2%}, 事件数={total_events}",
                evidence_count=total_events,
            )
            result.adjustments.append(record)
            self._history.append(record)

        return result

    def rollback_last(self) -> Optional[CalibrationRecord]:
        """撤销最近一次校准。"""
        if not self._history:
            return None
        last = self._history.pop()
        if last.target in self._rules:
            self._rules[last.target]["weight"] = last.old_value
        return last

    def get_weights(self) -> dict[str, float]:
        """获取当前所有权重。"""
        return {rid: s["weight"] for rid, s in self._rules.items()}


# ---------------------------------------------------------------------------
# Factor Calibrator
# ---------------------------------------------------------------------------


class FactorCalibrator:
    """因子权重校准器。

    基于回测结果和用户反馈，用贝叶斯更新调整因子权重。

    公式:
      - 后验权重 ∝ 先验权重 × 因子夏普信号 × (0.5 + 0.5 × 用户赞同率)
    """

    MIN_EVIDENCE = 5

    def __init__(self):
        self._factors: dict[str, dict] = {}
        self._history: list[CalibrationRecord] = []

    def register_factor(
        self, name: str, initial_weight: float = 0.33, sharpe: float = 0.0
    ):
        """注册一个因子。"""
        self._factors[name] = {
            "weight": initial_weight,
            "agree": 0,
            "disagree": 0,
            "sharpe": sharpe,
        }

    def record_feedback(self, factor_name: str, agreed: bool):
        """记录用户对某因子信号的反馈。"""
        if factor_name not in self._factors:
            self.register_factor(factor_name)
        if agreed:
            self._factors[factor_name]["agree"] += 1
        else:
            self._factors[factor_name]["disagree"] += 1

    def update_sharpe(self, factor_name: str, sharpe: float):
        """更新因子的夏普比率（来自回测）。"""
        if factor_name not in self._factors:
            self.register_factor(factor_name, sharpe=sharpe)
        else:
            self._factors[factor_name]["sharpe"] = sharpe

    def calibrate(self) -> CalibrationResult:
        """基于反馈和回测数据校准因子权重。"""
        result = CalibrationResult(total_factors=len(self._factors))

        if not self._factors:
            return result

        posteriors: dict[str, float] = {}
        total_raw = 0.0

        for name, stats in self._factors.items():
            total_feedback = stats["agree"] + stats["disagree"]
            agreement_rate = (
                stats["agree"] / total_feedback if total_feedback > 0 else 0.5
            )
            sharpe_signal = max(0.1, stats["sharpe"] + 1.0)
            raw = stats["weight"] * sharpe_signal * (0.5 + 0.5 * agreement_rate)
            posteriors[name] = raw
            total_raw += raw

        if total_raw > 0:
            for name in posteriors:
                posteriors[name] /= total_raw

        for name, stats in self._factors.items():
            total_feedback = stats["agree"] + stats["disagree"]
            if total_feedback < self.MIN_EVIDENCE:
                result.skipped.append(
                    f"{name}: 反馈不足 ({total_feedback} < {self.MIN_EVIDENCE})"
                )
                continue

            old_weight = stats["weight"]
            new_weight = round(posteriors[name], 4)

            if abs(new_weight - old_weight) < 0.001:
                continue

            stats["weight"] = new_weight
            agree_rate = (
                stats["agree"] / total_feedback if total_feedback > 0 else 0
            )
            record = CalibrationRecord(
                target=name,
                dimension="factor_weight",
                old_value=old_weight,
                new_value=new_weight,
                reason=f"反馈={total_feedback}, 赞同率={agree_rate:.0%}, 夏普={stats['sharpe']:.2f}",
                evidence_count=total_feedback,
            )
            result.adjustments.append(record)
            self._history.append(record)

        # 重新归一化所有权重，确保总和为 1.0
        total_weight = sum(s["weight"] for s in self._factors.values())
        if total_weight > 0:
            for s in self._factors.values():
                s["weight"] = round(s["weight"] / total_weight, 4)

        return result

    def get_weights(self) -> dict[str, float]:
        """获取当前因子权重。"""
        return {name: s["weight"] for name, s in self._factors.items()}


# ---------------------------------------------------------------------------
# Risk Param Calibrator
# ---------------------------------------------------------------------------


class RiskParamCalibrator:
    """风险参数校准器。

    基于用户反馈和实盘表现，微调止损线、仓位上限等风险参数。
    """

    MIN_EVIDENCE = 3

    def __init__(self):
        self._params: dict[str, dict] = {}
        self._history: list[CalibrationRecord] = []

    def register_param(self, name: str, initial_value: float):
        """注册一个风险参数。"""
        self._params[name] = {"value": initial_value, "events": []}

    def record_event(
        self, param_name: str, set_value: float, actual_value: float, reason: str = ""
    ):
        """记录风险参数相关事件。"""
        if param_name not in self._params:
            self.register_param(param_name, set_value)
        self._params[param_name]["events"].append({
            "set": set_value,
            "actual": actual_value,
            "reason": reason,
        })

    def calibrate(self) -> CalibrationResult:
        """校准风险参数。"""
        result = CalibrationResult()

        for name, stats in self._params.items():
            events = stats["events"]
            if len(events) < self.MIN_EVIDENCE:
                result.skipped.append(
                    f"{name}: 事件不足 ({len(events)} < {self.MIN_EVIDENCE})"
                )
                continue

            old_value = stats["value"]
            deviations = [e["actual"] - e["set"] for e in events]
            avg_deviation = sum(deviations) / len(deviations)

            new_value = old_value + avg_deviation * 0.5
            # 正确处理正负值的边界: lower=min(×0.8, ×1.2), upper=max(×0.8, ×1.2)
            lower = min(old_value * 0.8, old_value * 1.2)
            upper = max(old_value * 0.8, old_value * 1.2)
            new_value = max(lower, min(upper, new_value))
            new_value = round(new_value, 4)

            if abs(new_value - old_value) < 0.001:
                result.skipped.append(f"{name}: 无需调整 ({old_value:.4f})")
                continue

            stats["value"] = new_value
            record = CalibrationRecord(
                target=name,
                dimension="risk_param",
                old_value=old_value,
                new_value=new_value,
                reason=f"平均偏差={avg_deviation:.4f}, 事件数={len(events)}",
                evidence_count=len(events),
            )
            result.adjustments.append(record)
            self._history.append(record)

        return result

    def get_values(self) -> dict[str, float]:
        """获取当前参数值。"""
        return {name: s["value"] for name, s in self._params.items()}


# ---------------------------------------------------------------------------
# Confidence Calibrator (compatible with old API)
# ---------------------------------------------------------------------------


class Calibrator:
    """置信度校准器（兼容 Phase 4 旧 API）。

    P2-4 闭环: 校准结果反哺信号 confidence ——
    当样本充足时按 0.6-1.0 分桶实测准确率校正 confidence（过度自信 → 下调），
    样本不足或桶内证据不足时原样返回（向后兼容）。
    """

    MIN_SAMPLES = 20
    MIN_BAND_SAMPLES = 5

    # (band_label, low, high, midpoint_predicted)
    BANDS = [
        ("0.6-0.7", 0.6, 0.7, 0.65),
        ("0.7-0.8", 0.7, 0.8, 0.75),
        ("0.8-0.9", 0.8, 0.9, 0.85),
        ("0.9-1.0", 0.9, 1.0, 0.95),
    ]

    def __init__(self):
        self._predictions: list[dict] = []

    def record(self, confidence: float, actual_outcome: bool):
        """记录一次预测结果。"""
        self._predictions.append({
            "confidence": confidence,
            "correct": actual_outcome,
        })

    # ------------------------------------------------------------------
    # 分桶准确率（共享逻辑）
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(confidence: float) -> str:
        """将 confidence 归入桶标签。"""
        if confidence < 0.7:
            return "0.6-0.7"
        elif confidence < 0.8:
            return "0.7-0.8"
        elif confidence < 0.9:
            return "0.8-0.9"
        return "0.9-1.0"

    def _band_of(self, confidence: float) -> tuple[str, float]:
        """返回 (band_label, midpoint_predicted)。"""
        label = self._classify(confidence)
        for name, _, _, mid in self.BANDS:
            if name == label:
                return name, mid
        return label, 0.75

    def _compute_band_accuracy(self) -> dict[str, float]:
        """按桶计算实测准确率 {band_label: accuracy}。样本不足返回空 dict。"""
        if len(self._predictions) < self.MIN_SAMPLES:
            return {}
        bands: dict[str, list[dict]] = {name: [] for name, _, _, _ in self.BANDS}
        for p in self._predictions:
            bands[self._classify(p["confidence"])].append(p)
        result: dict[str, float] = {}
        for name, _, _, _ in self.BANDS:
            preds = bands[name]
            if preds:
                result[name] = sum(1 for p in preds if p["correct"]) / len(preds)
        return result

    def band_accuracy(self, band: str) -> Optional[float]:
        """某桶的实测准确率；无数据返回 None。"""
        return self._compute_band_accuracy().get(band)

    def band_lookup(self) -> dict[str, float]:
        """完整分桶准确率（样本不足返回空 dict）。"""
        return self._compute_band_accuracy()

    @property
    def adjustments_available(self) -> bool:
        """是否有足够样本支持校正。"""
        return len(self._predictions) >= self.MIN_SAMPLES

    def apply(self, confidence: float) -> float:
        """对单个 confidence 做分桶校正（P2-4 闭环入口）。

        规则（保守，只下调不上调）:
          - 样本 < MIN_SAMPLES → 原样返回
          - 桶内样本 < MIN_BAND_SAMPLES → 原样返回（证据不足不调整）
          - 实测准确率 < 桶预测中值（过度自信）→ 按 实际/预测 比例下调
          - 否则 → 原样返回

        Args:
            confidence: 原始置信度 0.0-1.0

        Returns:
            校正后 confidence（0.0-1.0）；数据不足时返回原始值。
        """
        confidence = float(confidence)
        if not self._predictions or not self.adjustments_available:
            return confidence

        band, pred_mid = self._band_of(confidence)
        acc = self.band_accuracy(band)
        if acc is None:
            return confidence

        band_count = sum(
            1 for p in self._predictions if self._classify(p["confidence"]) == band
        )
        if band_count < self.MIN_BAND_SAMPLES:
            return confidence

        if acc < pred_mid:  # 过度自信 → 下调
            adjusted = confidence * (acc / pred_mid)
        else:
            adjusted = confidence
        return round(min(1.0, max(0.0, adjusted)), 4)

    def generate_report(self, period: str = "") -> CalibrationReport:
        """生成校准报告。仅当 N ≥ 20 时有意义。"""
        report = CalibrationReport(period=period)
        report.total_predictions = len(self._predictions)
        report.sample_sufficient = report.total_predictions >= self.MIN_SAMPLES

        if not report.sample_sufficient:
            return report

        report.accuracy_by_band = self._compute_band_accuracy()
        return report


# ---------------------------------------------------------------------------
# P2-5: 聚合运气 / 幸存者偏差校准
# ---------------------------------------------------------------------------


def survivorship_adjustment(
    observed_avg_return: float,
    observed_strategies: int,
    total_strategies: int,
    hidden_default_return: float = 0.0,
) -> float:
    """幸存者偏差校正。

    观察样本只覆盖"幸存/存活"的策略（失败策略已从注册表移除或被回测门禁拦下），
    直接使用观察均值会高估真实期望收益。校正公式（保守假设缺失策略收益为
    ``hidden_default_return``）:

        corrected = (observed_avg_return × observed + hidden_default × missing) / total

    Args:
        observed_avg_return: 幸存样本平均收益
        observed_strategies: 幸存样本数
        total_strategies: 全部策略数（含被淘汰者）
        hidden_default_return: 缺失策略的保守收益假设（默认 0.0）

    Returns:
        校正后的期望收益。无缺失样本时原样返回。
    """
    missing = total_strategies - observed_strategies
    if total_strategies <= 0 or missing <= 0:
        return observed_avg_return
    corrected = (
        observed_avg_return * observed_strategies
        + hidden_default_return * missing
    ) / total_strategies
    return corrected


# 聚合运气识别（实现位于 src.alpha.attribution.LuckBiasDetector，
# 此处 re-export，供 learner 校准层统一入口）。
# 用法:
#     detector = LuckBiasDetector()
#     assessment = detector.assess(returns, strategy="MVP1")
#     if assessment.flagged:
#         # 收益集中少数几笔 → 高收益可能含运气成分，合入前需降权/验证
#         ...
__all__ = ["LuckAssessment", "LuckBiasDetector", "survivorship_adjustment"]
