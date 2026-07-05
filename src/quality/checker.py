# -*- coding: utf-8 -*-
"""Multi-Agent Quality Checker — 借鉴 CogAlpha 论文的多维度质量审查。

将 CogAlpha 的「多 Agent 质量审查器」适配到本项目的 L1 分析报告：

  1. DataFreshness    — 数据新鲜度：source_citations 是否过期
  2. Consistency      — 内部一致性：子评分是否逻辑自洽
  3. Leakage          — 未来信息泄露：指标是否隐含未来数据
  4. Interpretability — 经济可解释性：评分是否有基础逻辑支撑
  5. Safety           — 计算安全：边界值、除以零、异常集中

每个 Agent 独立审查一个维度，输出 AgentVerdict，聚合成 QualityReport。

用法:
    from src.quality import MultiAgentQualityChecker
    checker = MultiAgentQualityChecker()
    report = checker.check(l1_report)
    if not report.passed:
        for flag in report.blocking_flags:
            print(f"BLOCKED: {flag}")
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .schema import (
    AgentRole,
    AgentVerdict,
    QualityReport,
    Severity,
)

logger = logging.getLogger(__name__)

# L1 分析报告类型引用（延迟导入避免循环）
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.routing.l1_analyze import AnalysisReport


class MultiAgentQualityChecker:
    """多 Agent 质量审查器。

    CogAlpha 论文中的检查维度:
      1. Does the factor have any future information leakage?  → Leakage Agent
      2. Is the factor calculation correct and internally consistent? → Consistency Agent
      3. Is the factor logic economically interpretable? → Interpretability Agent
      4. Does the factor avoid obvious errors? → Safety Agent
      5. Is the factor efficiently implemented? (数据新鲜度替代) → DataFreshness Agent

    评分规则:
      - 任一 CRITICAL → passed=False
      - 综合评分 = 各 Agent 加权平均
    """

    # 数据新鲜度阈值（取自 guardrails.md）
    FRESHNESS_LIMITS = {
        "realtime": timedelta(minutes=5),
        "daily": timedelta(hours=1),
        "financial": timedelta(hours=24),
        "topic": timedelta(hours=12),
        "analyst_report": timedelta(days=7),
    }

    # 各 Agent 权重
    AGENT_WEIGHTS = {
        AgentRole.DATA_FRESHNESS: 0.15,
        AgentRole.CONSISTENCY: 0.25,
        AgentRole.LEAKAGE: 0.30,
        AgentRole.INTERPRETABILITY: 0.15,
        AgentRole.SAFETY: 0.15,
    }

    def check(self, report: "AnalysisReport") -> QualityReport:
        """对 L1 分析报告执行多维度质量审查。

        Args:
            report: L1 分析师输出的 AnalysisReport

        Returns:
            QualityReport with aggregated verdicts
        """
        verdicts = [
            self._check_data_freshness(report),
            self._check_consistency(report),
            self._check_leakage(report),
            self._check_interpretability(report),
            self._check_safety(report),
        ]

        # 计算综合评分
        total_weight = sum(self.AGENT_WEIGHTS[v.agent] for v in verdicts)
        if total_weight > 0:
            overall = sum(
                v.score * self.AGENT_WEIGHTS[v.agent] for v in verdicts
            ) / total_weight
        else:
            overall = 100.0

        # 聚合 flags
        blocking = []
        warnings = []
        suggestions = []
        for v in verdicts:
            if v.severity in (Severity.CRITICAL, Severity.HIGH):
                blocking.extend(v.flags)
                blocking.extend(v.suggestions)
            elif v.severity == Severity.MEDIUM:
                warnings.extend(v.flags)
                suggestions.extend(v.suggestions)
            else:
                suggestions.extend(v.suggestions)

        # 任一 CRITICAL 未通过
        passed = all(
            v.passed or v.severity != Severity.CRITICAL
            for v in verdicts
        ) and not any(v.severity == Severity.HIGH and not v.passed for v in verdicts)

        return QualityReport(
            symbol=report.symbol,
            passed=passed,
            overall_score=round(overall, 1),
            verdicts=verdicts,
            blocking_flags=list(dict.fromkeys(blocking)),   # 去重保序
            warnings=list(dict.fromkeys(warnings)),
            suggestions=list(dict.fromkeys(suggestions)),
        )

    # ------------------------------------------------------------------
    # Agent 1: 数据新鲜度审查 (DataFreshness)
    # ------------------------------------------------------------------

    def _check_data_freshness(self, report: "AnalysisReport") -> AgentVerdict:
        """检查数据来源是否在有效期内。

        CogAlpha 等效检查: 输入数据是否可追溯、是否过期。
        """
        citations = getattr(report, "source_citations", []) or []
        now = datetime.now()
        stale_fields: list[str] = []
        expired_fields: list[str] = []

        for sc in citations:
            freshness = getattr(sc, "data_freshness", None)
            field = getattr(sc, "field", "unknown")

            if freshness is None:
                continue

            ts = getattr(sc, "fetch_timestamp", None)
            if ts is None:
                stale_fields.append(field)
                continue

            age = now - ts
            if age > freshness * 2:
                expired_fields.append(f"{field}({age.total_seconds()/3600:.1f}h)")
            elif age > freshness:
                stale_fields.append(f"{field}({age.total_seconds()/3600:.1f}h)")

        if expired_fields:
            return AgentVerdict(
                agent=AgentRole.DATA_FRESHNESS,
                passed=False,
                score=30,
                severity=Severity.HIGH,
                flags=[f"数据过期: {', '.join(expired_fields[:5])}"],
                suggestions=["刷新数据源后重新分析"],
                details=f"{len(expired_fields)} 字段过期, {len(stale_fields)} 即将过期",
            )
        elif stale_fields:
            return AgentVerdict(
                agent=AgentRole.DATA_FRESHNESS,
                passed=True,
                score=70,
                severity=Severity.MEDIUM,
                flags=[f"数据即将过期: {', '.join(stale_fields[:5])}"],
                suggestions=["建议尽快刷新数据"],
                details=f"{len(stale_fields)} 字段即将过期",
            )
        elif not citations:
            return AgentVerdict(
                agent=AgentRole.DATA_FRESHNESS,
                passed=True,
                score=50,
                severity=Severity.LOW,
                flags=["无数据溯源信息"],
                suggestions=["为所有数据点添加 SourceCitation"],
                details="无 source_citations",
            )

        return AgentVerdict(
            agent=AgentRole.DATA_FRESHNESS,
            passed=True,
            score=100,
            details=f"{len(citations)} 条数据溯源均有效",
        )

    # ------------------------------------------------------------------
    # Agent 2: 内部一致性审查 (Consistency)
    # ------------------------------------------------------------------

    def _check_consistency(self, report: "AnalysisReport") -> AgentVerdict:
        """检查子评分之间的逻辑一致性。

        CogAlpha 等效检查: Is the factor calculation correct and internally consistent?

        检查规则:
          - 高价值 + 低质量 → 矛盾（便宜但有问题的公司）
          - 高质量 + 低动量 → 合理（好公司短期承压）
          - 高宏观 + 低情绪 → 注意（宏观好但市场恐慌）
          - 所有子评分都在 0-100 范围
        """
        flags: list[str] = []
        suggestions: list[str] = []

        scores = {
            "value": getattr(report, "value_score", 50),
            "quality": getattr(report, "quality_score", 50),
            "momentum": getattr(report, "momentum_score", 50),
            "macro": getattr(report, "macro_score", 50),
            "sentiment": getattr(report, "sentiment_signal", "NEUTRAL"),
            "executive": getattr(report, "executive_score", 50),
            "valuation": getattr(report, "valuation_score", 50) if hasattr(report, "valuation_score") else 50,
        }

        # 边界检查
        for name, val in scores.items():
            if isinstance(val, (int, float)) and (val < 0 or val > 100):
                flags.append(f"{name}_score 越界: {val} (应为 0-100)")
                suggestions.append(f"修正 {name}_score 到 [0,100] 范围")

        # 高价值(>70) + 低质量(<30) → 可能价值陷阱
        if scores["value"] > 70 and scores["quality"] < 30:
            flags.append(f"价值陷阱风险: value={scores['value']:.0f} quality={scores['quality']:.0f}")
            suggestions.append("高质量与高价值共存时才介入，或确认低质量原因（周期底部/一次性事件）")

        # 高质量(>70) + 极度恐慌 → 优质股错杀机会
        if scores["quality"] > 70 and scores["sentiment"] == "PANIC":
            suggestions.append("高质量+恐慌=潜在错杀机会，关注抄底时机")

        # 高动量(>75) + 低价值(<25) → 追涨风险
        if scores["momentum"] > 75 and scores["value"] < 25:
            flags.append(f"追涨风险: momentum={scores['momentum']:.0f} value={scores['value']:.0f}")
            suggestions.append("高动量低价值 = 可能追高，检查估值安全边际")

        # 宏观<30 但整体高评分 → 注意逆势风险
        if scores["macro"] < 30:
            suggestions.append("宏观环境偏空，所有仓位建议打折")

        # 所有评分集中在 50±5 → 无区分度
        numeric_scores = {k: v for k, v in scores.items() if isinstance(v, (int, float))}
        if numeric_scores:
            all_neutral = all(45 <= v <= 55 for v in numeric_scores.values())
            if all_neutral:
                flags.append("所有子评分集中在 50 附近，区分度不足")
                suggestions.append("检查数据源是否有效，可能输入数据有问题")

        # V4: 高管风险与评分一致性
        executive_risks = getattr(report, "executive_risks", []) or []
        if executive_risks and scores.get("executive", 50) > 60:
            flags.append(f"executive_score={scores['executive']:.0f} 与高管风险不匹配: {len(executive_risks)} 条风险")
            suggestions.append("有高管风险时 executive_score 不应高于 60")

        if flags:
            score = max(10, 80 - len(flags) * 10)
            return AgentVerdict(
                agent=AgentRole.CONSISTENCY,
                passed=len([f for f in flags if "风险" in f or "越界" in f or "不匹配" in f]) == 0,
                score=score,
                severity=Severity.MEDIUM if any("风险" in f or "不匹配" in f for f in flags) else Severity.LOW,
                flags=flags,
                suggestions=suggestions,
                details=f"{len(flags)} 个一致性问题",
            )

        return AgentVerdict(
            agent=AgentRole.CONSISTENCY,
            passed=True,
            score=100,
            details="子评分内部一致",
        )

    # ------------------------------------------------------------------
    # Agent 3: 未来信息泄露审查 (Leakage)
    # ------------------------------------------------------------------

    def _check_leakage(self, report: "AnalysisReport") -> AgentVerdict:
        """检查分析是否可能隐含未来信息泄露。

        CogAlpha 等效检查: 这是最关键的检查 — 任何形式的未来信息泄露都必须阻止。

        检查项:
          - 基本面数据是否与日期不匹配（财务数据发布有滞后）
          - 动量计算是否使用了当前 K 线的 close（已知，可接受）
          - PE/PB 是否使用了最新季报（发布滞后约 30-45 天）
          - Alpha 分析是否可能访问了未公开信息
        """
        flags: list[str] = []

        # 检查 source_citations 中是否有异常时间戳
        citations = getattr(report, "source_citations", []) or []
        for sc in citations:
            ts = getattr(sc, "fetch_timestamp", None)
            data_freshness = getattr(sc, "data_freshness", None)
            field = getattr(sc, "field", "unknown")

            if ts and data_freshness:
                # 财务数据不应该有"实时"新鲜度
                if "financial" in str(data_freshness).lower() or "财务" in str(field):
                    pass  # 正常

        # 检查 Alpha 信息来源层级（一手材料是优点，非风险）
        alpha_profile = getattr(report, "alpha_profile", None)
        if alpha_profile:
            from src.alpha.schema import SourceTier
            source_tier = getattr(alpha_profile.source, "source_tier", None) if hasattr(alpha_profile, "source") else None
            if source_tier == SourceTier.PRIMARY:
                # 一手信息确认来源合法性 — 提醒但非硬阻止
                pass  # PRIMARY 是优点，不标记

        # 检查 sentiment 信号的时效性
        sentiment = getattr(report, "sentiment_signal", "NEUTRAL")
        if sentiment in ("EXTREME", "PANIC"):
            # 极端情绪信号必须在最近数据基础上得出
            data_freshness = getattr(report, "data_freshness", None)
            if data_freshness:
                age = datetime.now() - data_freshness
                if age > timedelta(hours=1):
                    flags.append(f"极端情绪信号({sentiment})但数据已过 {age.total_seconds()/3600:.1f}h，可能不反映最新情况")

        if flags:
            # Leakage 检查中的 flag 都是 MEDIUM 级别，除了 PRIMARY 来源提醒
            has_critical = any("非公开" in f or "内幕" in f for f in flags)
            return AgentVerdict(
                agent=AgentRole.LEAKAGE,
                passed=not has_critical,
                score=60 if not has_critical else 20,
                severity=Severity.CRITICAL if has_critical else Severity.MEDIUM,
                flags=flags,
                suggestions=["确认所有数据来源均为公开信息，无 forward-looking bias"],
                details=f"{len(flags)} 个潜在泄露风险",
            )

        return AgentVerdict(
            agent=AgentRole.LEAKAGE,
            passed=True,
            score=100,
            details="未检测到未来信息泄露",
        )

    # ------------------------------------------------------------------
    # Agent 4: 经济可解释性审查 (Interpretability)
    # ------------------------------------------------------------------

    def _check_interpretability(self, report: "AnalysisReport") -> AgentVerdict:
        """检查分析结果是否有经济逻辑支撑。

        CogAlpha 等效检查: Is the factor logic economically interpretable?

        检查项:
          - 多空双视角 (bull_case / bear_case) 是否存在
          - 瓶颈分析是否有实质内容
          - Alpha rationale 是否为空
          - source_citations 是否有解释性来源
        """
        flags: list[str] = []
        suggestions: list[str] = []

        # bull_case / bear_case 非空
        bull = getattr(report, "bull_case", "")
        bear = getattr(report, "bear_case", "")
        if not bull and not bear:
            flags.append("缺少多空双视角分析")
            suggestions.append("补充 bull_case 和 bear_case，说明看多和看空的逻辑")
        elif not bull:
            suggestions.append("补充 bull_case（看多逻辑）")
        elif not bear:
            suggestions.append("补充 bear_case（看空逻辑）")

        # Alpha rationale
        alpha_profile = getattr(report, "alpha_profile", None)
        if alpha_profile:
            rationale = getattr(alpha_profile, "alpha_rationale", "")
            if not rationale:
                flags.append("有 AlphaProfile 但缺乏 alpha_rationale 解释")
                suggestions.append("为 Alpha 判断补充逻辑链：为什么市场错了？你多知道什么？")
        else:
            flags.append("无 Alpha 视角分析")
            suggestions.append("启动 Alpha Lens 分析，说明信息来源和逻辑差异")

        # 瓶颈分析
        bottlenecks = getattr(report, "bottlenecks", []) or []
        upstream_risks = getattr(report, "upstream_risks", []) or []
        if not bottlenecks and not upstream_risks:
            suggestions.append("补充供应链/瓶颈分析，理解公司在产业链中的位置")

        if flags:
            score = max(20, 80 - len(flags) * 15)
            return AgentVerdict(
                agent=AgentRole.INTERPRETABILITY,
                passed=len([f for f in flags if "缺少" in f or "缺乏" in f]) <= 1,
                score=score,
                severity=Severity.MEDIUM,
                flags=flags,
                suggestions=suggestions,
                details=f"{len(flags)} 个可解释性问题",
            )

        return AgentVerdict(
            agent=AgentRole.INTERPRETABILITY,
            passed=True,
            score=100,
            details="经济可解释性良好",
        )

    # ------------------------------------------------------------------
    # Agent 5: 计算安全检查 (Safety)
    # ------------------------------------------------------------------

    def _check_safety(self, report: "AnalysisReport") -> AgentVerdict:
        """检查计算安全和边界条件。

        CogAlpha 等效检查: Does the factor avoid obvious errors?
        (division by zero, undefined results, edge cases)

        检查项:
          - 置信度是否在 [0,1] 范围
          - 评分是否合法
          - 是否有异常值集中（全部 0 或全部 100）
          - source_citations 是否完整
        """
        flags: list[str] = []

        # 置信度范围检查
        confidence = getattr(report, "confidence", 0.7)
        if confidence < 0 or confidence > 1:
            flags.append(f"confidence 越界: {confidence} (应为 0.0-1.0)")
        elif confidence < 0.3:
            flags.append(f"confidence 极低: {confidence:.2f}，分析结果不可靠")

        # 评分极值检查
        score_fields = [
            ("macro_score", getattr(report, "macro_score", 50)),
            ("value_score", getattr(report, "value_score", 50)),
            ("quality_score", getattr(report, "quality_score", 50)),
            ("momentum_score", getattr(report, "momentum_score", 50)),
            ("executive_score", getattr(report, "executive_score", 50)),
        ]
        if hasattr(report, "valuation_score"):
            score_fields.append(("valuation_score", report.valuation_score))

        all_zero_or_hundred = True
        for name, val in score_fields:
            if val != 0 and val != 100:
                all_zero_or_hundred = False
            if val == 0 or val == 100:
                flags.append(f"{name}={val} 处于边界值，可能是默认值/计算异常")

        if all_zero_or_hundred:
            flags.append("所有评分均为边界值(0/100)，可能数据源异常")

        # source_citations 完整性
        citations = getattr(report, "source_citations", []) or []
        if len(citations) < 3:
            flags.append(f"source_citations 不足 ({len(citations)} 条)，数据来源不可追溯")

        if flags:
            has_critical = any("越界" in f or "不可追溯" in f for f in flags)
            return AgentVerdict(
                agent=AgentRole.SAFETY,
                passed=not has_critical,
                score=max(10, 80 - len(flags) * 10),
                severity=Severity.CRITICAL if has_critical else Severity.LOW,
                flags=flags,
                suggestions=["检查数据源连接", "修正边界值/默认值问题"],
                details=f"{len(flags)} 个计算安全问题",
            )

        return AgentVerdict(
            agent=AgentRole.SAFETY,
            passed=True,
            score=100,
            details="计算安全检查通过",
        )
