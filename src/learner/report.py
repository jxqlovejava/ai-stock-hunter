# -*- coding: utf-8 -*-
"""学习报告生成器。

生成周度/月度学习报告，汇总:
  - 策略优化历史（版本演进 + 指标变化）
  - 用户能力成长曲线（选股/择时/风控/情绪 4 维趋势）
  - 反馈统计（赞同率、主要分歧点、参数调整）
  - 下一步建议

用法:
    reporter = LearningReport()
    report = reporter.generate(
        profile=user_profile,
        feedback_summary=feedback_summary,
        strategy_history=strategy_registry.history("MVP1"),
        period="weekly",
    )
    print(report)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LearningReport:
    """学习报告。"""

    title: str = ""
    period: str = "weekly"
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 用户画像
    profile_snapshot: dict[str, float] = field(default_factory=dict)
    profile_trend: str = ""  # "improving" | "stable" | "declining"

    # 策略演进
    strategy_versions: list[dict] = field(default_factory=list)
    best_strategy: str = ""
    best_sharpe: float = 0.0
    total_optimizations: int = 0

    # 反馈统计
    total_feedback: int = 0
    agreement_rate: float = 0.0
    top_disagreement_reasons: list[str] = field(default_factory=list)
    param_adjustments: list[dict] = field(default_factory=list)

    # 风险与建议
    risk_alerts: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def render(self) -> str:
        """渲染为 Markdown 报告。"""
        lines = [
            f"# {self.title}",
            f"生成时间: {self.generated_at}",
            "",
            "---",
            "",
            "## 📊 用户能力画像",
            "",
        ]

        # 画像
        if self.profile_snapshot:
            lines.append("| 维度 | 评分 | 趋势 |")
            lines.append("|------|------|------|")
            trend_icon = {"improving": "📈", "stable": "➡️", "declining": "📉"}.get(
                self.profile_trend, "➡️"
            )
            for dim, score in self.profile_snapshot.items():
                bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
                lines.append(f"| {dim} | {bar} {score:.0f}/100 | {trend_icon} |")
        else:
            lines.append("暂无画像数据，完成 5 笔以上交易后生成。")

        lines.append("")
        lines.append("## 🔄 策略演进")
        lines.append("")

        if self.strategy_versions:
            lines.append(f"共 {self.total_optimizations} 次策略优化，当前最优: **{self.best_strategy}** (Sharpe: {self.best_sharpe:.2f})")
            lines.append("")
            lines.append("| 版本 | 参数 | Sharpe | 最大回撤 | 胜率 | 日期 |")
            lines.append("|------|------|--------|---------|------|------|")
            for v in self.strategy_versions[-5:]:  # 最近 5 个版本
                params_str = ", ".join(f"{k}={v}" for k, v in v.get("params", {}).items())
                lines.append(
                    f"| {v.get('version', '?')} | {params_str} | "
                    f"{v.get('sharpe', 0):.2f} | {v.get('max_drawdown', 0):.1%} | "
                    f"{v.get('win_rate', 0):.1%} | {v.get('created_at', '?')[:10]} |"
                )
        else:
            lines.append("暂无策略优化记录。运行 `backtest-optimize` 开始优化。")

        lines.append("")
        lines.append("## 💬 用户反馈")
        lines.append("")

        lines.append(f"- 总反馈数: {self.total_feedback}")
        lines.append(f"- 系统-用户一致率: {self.agreement_rate:.1%}")

        if self.top_disagreement_reasons:
            lines.append("- 主要分歧点:")
            for reason in self.top_disagreement_reasons[:3]:
                lines.append(f"  - {reason}")

        if self.param_adjustments:
            lines.append("- 参数调整记录:")
            for adj in self.param_adjustments[-5:]:
                lines.append(
                    f"  - {adj.get('param', '?')}: {adj.get('old', 0)} → {adj.get('new', 0)} "
                    f"({adj.get('reason', '')})"
                )

        lines.append("")
        lines.append("## ⚠️ 风险提示")
        lines.append("")

        if self.risk_alerts:
            for alert in self.risk_alerts:
                lines.append(f"- 🔴 {alert}")
        else:
            lines.append("✅ 当前无风险告警。")

        lines.append("")
        lines.append("## 💡 建议")
        lines.append("")

        if self.recommendations:
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
        else:
            lines.append("继续保持现有策略，积累更多数据后再优化。")

        lines.append("")
        lines.append("---")
        lines.append(f"*报告由 AI Stock Hunter 学习引擎自动生成*")

        return "\n".join(lines)


class ReportGenerator:
    """学习报告生成器。

    汇总多个数据源生成结构化的学习报告。
    """

    def generate(
        self,
        profile: Optional[object] = None,
        feedback_summary: Optional[object] = None,
        strategy_versions: Optional[list] = None,
        signal_quality: Optional[object] = None,
        period: str = "weekly",
    ) -> LearningReport:
        """生成学习报告。

        Args:
            profile: UserProfile 对象
            feedback_summary: FeedbackSummary 对象
            strategy_versions: StrategyVersion 列表
            signal_quality: SignalQualityReport 对象
            period: 报告周期 "weekly" | "monthly"
        """
        title = {"weekly": "周度学习报告", "monthly": "月度学习报告"}.get(period, "学习报告")

        report = LearningReport(title=title, period=period)

        # 用户画像
        if profile is not None:
            report.profile_snapshot = {
                "选股能力": getattr(profile, "stock_selection", 50),
                "择时能力": getattr(profile, "timing", 50),
                "风控纪律": getattr(profile, "risk_discipline", 50),
                "情绪控制": getattr(profile, "emotion_control", 50),
            }
            # 判断趋势
            avg_score = sum(report.profile_snapshot.values()) / 4
            if avg_score > 70:
                report.profile_trend = "improving"
            elif avg_score > 40:
                report.profile_trend = "stable"
            else:
                report.profile_trend = "declining"

        # 策略演进
        if strategy_versions:
            for v in strategy_versions:
                entry = {
                    "version": getattr(v, "version", "?"),
                    "params": getattr(v, "params", {}),
                    "sharpe": getattr(v, "metrics", {}).get("sharpe_ratio", 0),
                    "max_drawdown": getattr(v, "metrics", {}).get("max_drawdown", 0),
                    "win_rate": getattr(v, "metrics", {}).get("win_rate", 0),
                    "created_at": getattr(v, "created_at", ""),
                }
                report.strategy_versions.append(entry)

            # 找最优版本
            best = max(
                report.strategy_versions,
                key=lambda x: x.get("sharpe", 0) or 0,
                default=None,
            )
            if best:
                report.best_strategy = f"{best['version']}"
                report.best_sharpe = best.get("sharpe", 0) or 0

            report.total_optimizations = len(strategy_versions)

        # 反馈统计
        if feedback_summary is not None:
            report.total_feedback = getattr(feedback_summary, "total", 0)
            report.agreement_rate = getattr(feedback_summary, "agreement_rate", 0.0)
            report.top_disagreement_reasons = getattr(feedback_summary, "lessons", []) or []

            for param, changes in (getattr(feedback_summary, "total_adjustments", {}) or {}).items():
                for c in changes:
                    report.param_adjustments.append({
                        "param": param,
                        "old": c.get("old_value"),
                        "new": c.get("new_value"),
                        "reason": c.get("reason", ""),
                    })

        # 信号质量
        if signal_quality is not None:
            win_rate = getattr(signal_quality, "win_rate", 0) or 0
            if win_rate < 0.4:
                report.risk_alerts.append(f"信号胜率偏低 ({win_rate:.1%})，建议暂停实盘，回测排查")
            avg_return = getattr(signal_quality, "avg_return", 0) or 0
            if avg_return < -0.05:
                report.risk_alerts.append(f"平均信号收益为负 ({avg_return:.2%})，策略可能失效")
            max_dd = getattr(signal_quality, "max_drawdown", 0) or 0
            if max_dd < -0.20:
                report.risk_alerts.append(f"信号最大回撤过大 ({max_dd:.2%})，需调整仓位或止损")

        # 建议
        report.recommendations = self._generate_recommendations(report)

        return report

    def _generate_recommendations(self, report: LearningReport) -> list[str]:
        """基于报告数据生成建议。"""
        recs = []

        if report.profile_snapshot:
            lowest_dim = min(report.profile_snapshot, key=report.profile_snapshot.get)
            lowest_score = report.profile_snapshot[lowest_dim]
            if lowest_score < 50:
                recs.append(f"重点关注「{lowest_dim}」(当前 {lowest_score:.0f}/100)，建议针对性复盘提升")

        if report.agreement_rate < 0.6 and report.total_feedback >= 5:
            recs.append(
                f"系统-用户一致率偏低 ({report.agreement_rate:.0%})，"
                "建议梳理主要分歧原因并考虑调整策略参数"
            )

        if report.total_optimizations == 0:
            recs.append("尚未进行策略优化，建议运行 `backtest-optimize` 探索最优参数")

        if report.total_optimizations > 3:
            recs.append("已进行多次优化，注意留出验证期避免过拟合")

        if not recs:
            recs.append("当前状态良好，继续保持现有节奏")

        return recs
