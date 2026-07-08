# -*- coding: utf-8 -*-
"""内部策略竞技场 — 报告生成。

ArenaReport 从 ArenaSession 生成：
  - Markdown 完整报告
  - 排行榜表格
  - 逐策略详情
  - 雷达图（可选，依赖 matplotlib）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import ArenaLeaderboardEntry, ArenaSession, ArenaStrategyResult


class ArenaReport:
    """竞技场报告生成器。"""

    def __init__(self, output_dir: Optional[Path] = None):
        self._output_dir = output_dir or Path("data/arena_reports")
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Markdown 完整报告
    # ------------------------------------------------------------------

    def markdown(self, session: ArenaSession) -> str:
        """生成完整 Markdown 报告。"""
        cfg = session.config
        lines = [
            "# 🏟️ 内部策略竞技场 — 回测对比报告",
            "",
            f"**会话 ID**: `{session.session_id}`",
            f"**时间**: {session.created_at[:19]}",
        ]

        if cfg:
            lines.extend([
                f"**股票池**: {cfg.universe_name} ({len(cfg.universe)} 只)",
                f"**回测区间**: {cfg.start_date} → {cfg.end_date}",
                f"**初始资金**: {cfg.initial_cash:,.0f}",
                f"**策略数**: {len(cfg.strategies)}",
            ])

        lines.append("")
        lines.append("---")
        lines.append("")

        # 排行榜
        if session.leaderboard:
            lines.append("## 📊 综合排行榜")
            lines.append("")
            lines.append(self.leaderboard_table(session))
            lines.append("")

        # 逐指标胜者
        if session.winner_per_metric:
            lines.append("## 🏆 各指标最佳策略")
            lines.append("")
            lines.append(self.per_metric_summary(session))
            lines.append("")

        # 逐策略详情
        valid = [r for r in session.results if not r.error]
        if valid:
            lines.append("## 📋 策略详情")
            lines.append("")
            for r in valid:
                lines.append(self.strategy_detail(r))
                lines.append("")

        # 失败策略
        failed = [r for r in session.results if r.error]
        if failed:
            lines.append("## ⚠️ 运行失败")
            lines.append("")
            for r in failed:
                lines.append(f"- **{r.name}**: {r.error}")
            lines.append("")

        # 洞察
        if session.insights:
            lines.append("## 💡 分析洞察")
            lines.append("")
            for ins in session.insights:
                lines.append(f"- {ins}")
            lines.append("")

        # 页脚
        lines.extend([
            "---",
            "",
            f"*报告由 白泽·策略竞技场 生成 · {session.created_at[:19]}*",
        ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 排行榜表格
    # ------------------------------------------------------------------

    def leaderboard_table(self, session: ArenaSession) -> str:
        """生成排行榜 Markdown 表格。"""
        if not session.leaderboard:
            return "暂无数据"

        lines = [
            "| 排名 | 策略 | 综合评分 | Sharpe | 年化收益 | 最大回撤 | 胜率 | 交易数 |",
            "|------|------|---------|--------|---------|---------|------|--------|",
        ]

        for e in session.leaderboard:
            crown = " 👑" if e.rank == 1 else ""
            lines.append(
                f"| {e.rank}{crown} | **{e.name}** | {e.composite_score:.1f} | "
                f"{e.sharpe_ratio:.2f} | {e.annual_return_pct:.1f}% | "
                f"{e.max_drawdown_pct:.1f}% | {e.win_rate_pct:.1f}% | {e.total_trades} |"
            )

        lines.append("")
        # 评分说明
        lines.append(
            "> 综合评分权重：Sharpe 40% + 最大回撤(倒数) 25% + 胜率 20% + 年化收益 15%"
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 逐指标胜者
    # ------------------------------------------------------------------

    def per_metric_summary(self, session: ArenaSession) -> str:
        """逐指标最佳表格。"""
        if not session.winner_per_metric:
            return "暂无数据"

        lines = [
            "| 指标 | 最佳策略 | 数值 |",
            "|------|---------|------|",
        ]

        for metric, winner_str in session.winner_per_metric.items():
            lines.append(f"| {metric} | {winner_str} |")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 单策略详情
    # ------------------------------------------------------------------

    def strategy_detail(self, result: ArenaStrategyResult) -> str:
        """生成单策略详情卡片。"""
        lines = [
            f"### {result.name} (v{result.version})",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 年化收益率 | {result.annual_return_pct:+.1f}% |",
            f"| 累计收益率 | {result.cumulative_return_pct:+.1f}% |",
            f"| Sharpe 比率 | {result.sharpe_ratio:.2f} |",
            f"| Sortino 比率 | {result.sortino_ratio:.2f} |",
            f"| Calmar 比率 | {result.calmar_ratio:.2f} |",
            f"| 最大回撤 | -{abs(result.max_drawdown_pct):.1f}% |",
            f"| 年化波动率 | {result.annual_volatility_pct:.1f}% |",
            f"| 胜率 | {result.win_rate_pct:.1f}% |",
            f"| 盈亏比 | {result.profit_factor:.2f} |",
            f"| 交易次数 | {result.total_trades} |",
            f"| 平均持仓天数 | {result.avg_holding_days:.0f} |",
        ]

        # 分年度收益
        if result.yearly_returns:
            lines.append("")
            lines.append("**分年度收益**:")
            for yr in sorted(result.yearly_returns):
                ret = result.yearly_returns[yr]
                emoji = "🟢" if ret > 0 else "🔴"
                lines.append(f"- {yr}: {emoji} {ret:+.1f}%")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 雷达图（可选）
    # ------------------------------------------------------------------

    def radar_chart(
        self, session: ArenaSession, output_path: Optional[str] = None
    ) -> Optional[str]:
        """生成 5 维雷达图（Sharpe / 年化收益 / 回撤(倒数) / 胜率 / Calmar）。

        Returns:
            输出文件路径，如果 matplotlib 不可用则返回 None。
        """
        if not session.leaderboard or len(session.leaderboard) < 1:
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        entries = session.leaderboard[:6]  # 最多 6 条
        labels = ["Sharpe", "年化收益", "回撤控制", "胜率", "Calmar"]
        n = len(labels)

        # 归一化所有指标到 [0, 1]
        all_sharpe = [e.sharpe_ratio for e in entries]
        all_ret = [e.annual_return_pct for e in entries]
        all_dd = [100 - abs(e.max_drawdown_pct) for e in entries]  # 回撤越小越好
        all_win = [e.win_rate_pct for e in entries]
        all_calmar = [e.calmar_ratio for e in entries]

        angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        colors = plt.cm.Set2(np.linspace(0, 1, len(entries)))

        for idx, e in enumerate(entries):
            values = [
                _safe_norm(e.sharpe_ratio, all_sharpe),
                _safe_norm(e.annual_return_pct, all_ret),
                _safe_norm(100 - abs(e.max_drawdown_pct), all_dd),
                _safe_norm(e.win_rate_pct, all_win),
                _safe_norm(e.calmar_ratio, all_calmar),
            ]
            values += values[:1]
            ax.fill(angles, values, alpha=0.1, color=colors[idx])
            ax.plot(angles, values, "o-", linewidth=2, label=e.name, color=colors[idx])

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontsize=11)
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)
        ax.set_title("策略多维对比雷达图", fontsize=14, pad=20)

        out = output_path or str(self._output_dir / f"arena_radar_{session.session_id}.png")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return out

    # ------------------------------------------------------------------
    # 控制台摘要（短输出）
    # ------------------------------------------------------------------

    def console_summary(self, session: ArenaSession) -> str:
        """终端友好的短摘要。"""
        lines = [
            "=" * 64,
            f"  🏟️ 策略竞技场 · {session.created_at[:19]}",
            f"  {session.config.universe_name} · {session.config.start_date} → {session.config.end_date}",
            "=" * 64,
        ]

        if not session.leaderboard:
            lines.append("  暂无排行数据")
            return "\n".join(lines)

        for e in session.leaderboard:
            crown = "👑" if e.rank == 1 else "  "
            bar = "█" * max(1, int(e.composite_score / 5))
            lines.append(
                f"  {crown} {e.rank}. {e.name:<20s} {bar} {e.composite_score:.0f}"
            )

        lines.append("=" * 64)

        if session.winner_per_metric:
            for metric, winner in session.winner_per_metric.items():
                lines.append(f"  🏆 {metric}: {winner}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_norm(value: float, all_values: list[float]) -> float:
    """安全 min-max 归一化。"""
    if not all_values:
        return 0.5
    mn = min(all_values)
    mx = max(all_values)
    if mx == mn:
        return 0.5
    return (value - mn) / (mx - mn)
