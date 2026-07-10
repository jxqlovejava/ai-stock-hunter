# -*- coding: utf-8 -*-
"""报告生成器 — 日/周/月 Markdown 报告。

复用 ``src/output/markdown_report.py`` 的模板风格。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.paper_trading.state import PaperTrade, PortfolioState

logger = logging.getLogger(__name__)

DEFAULT_REPORT_DIR = Path("data/paper_trading")
DAILY_DIR = DEFAULT_REPORT_DIR / "daily_reports"
WEEKLY_DIR = DEFAULT_REPORT_DIR / "weekly_reports"
MONTHLY_DIR = DEFAULT_REPORT_DIR / "monthly_reports"


class ReportGenerator:
    """模拟交易报告生成器。

    用法::

        gen = ReportGenerator()
        gen.generate_daily(state, trades, notes="...")
        gen.generate_weekly(state, all_trades, week_start, week_end)
        gen.generate_monthly(state, all_trades, month_key)
    """

    def __init__(self, base_dir: Path | None = None):
        if base_dir:
            self._base = base_dir
        else:
            self._base = DEFAULT_REPORT_DIR
        self._daily = self._base / "daily_reports"
        self._weekly = self._base / "weekly_reports"
        self._monthly = self._base / "monthly_reports"

        for d in [self._daily, self._weekly, self._monthly]:
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 日度报告
    # ------------------------------------------------------------------

    def generate_daily(
        self,
        state: PortfolioState,
        trades: list[PaperTrade],
        notes: str = "",
        report_date: str = "",
    ) -> str:
        """生成日度盈亏报告。"""
        if not report_date:
            report_date = date.today().strftime("%Y-%m-%d")

        today_trades = [t for t in trades if t.timestamp[:10] == report_date]
        lines = self._daily_header(state, report_date)

        # 当日盈亏
        lines.extend(self._daily_pnl_section(state, today_trades))

        # 持仓明细
        lines.extend(self._positions_section(state))

        # 当日交易
        lines.extend(self._trades_section(today_trades, "当日交易记录"))

        # 风控状态
        lines.extend(self._risk_section(state))

        # 备注
        if notes:
            lines.append("")
            lines.append("## 📝 备注")
            lines.append(notes)

        lines.extend(self._footer())
        content = "\n".join(lines)
        filepath = self._daily / f"{report_date}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("日度报告已保存: %s", filepath)
        return str(filepath)

    # ------------------------------------------------------------------
    # 周度复盘
    # ------------------------------------------------------------------

    def generate_weekly(
        self,
        state: PortfolioState,
        week_trades: list[PaperTrade],
        week_start: str,
        week_end: str,
        notes: str = "",
    ) -> str:
        """生成周度复盘报告。"""
        lines = [
            f"# 📊 模拟交易周度复盘",
            f"**周期**: {week_start} ~ {week_end}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        # 周度统计
        lines.extend(self._period_stats(state, week_trades, "本周"))

        # 最佳/最差交易
        lines.extend(self._best_worst_trades(week_trades))

        # 持仓明细
        lines.extend(self._positions_section(state))

        # 庄家行为观察
        lines.extend(self._manipulation_observations(week_trades))

        # 策略偏差
        lines.extend(self._strategy_deviation(week_trades))

        # 下周关注
        lines.append("")
        lines.append("## 🔭 下周关注")
        lines.append("- [ ] 持仓股关键支撑/压力位")
        lines.append("- [ ] 宏观事件日历")
        lines.append("- [ ] 自选股潜在入场机会")
        lines.append(f"- [ ] 能力圈匹配度回顾")

        if notes:
            lines.append("")
            lines.append("## 📝 复盘笔记")
            lines.append(notes)

        lines.extend(self._footer())
        content = "\n".join(lines)
        filepath = self._weekly / f"week_{week_start}_{week_end}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("周度复盘已保存: %s", filepath)
        return str(filepath)

    # ------------------------------------------------------------------
    # 月度复盘
    # ------------------------------------------------------------------

    def generate_monthly(
        self,
        state: PortfolioState,
        month_trades: list[PaperTrade],
        month_key: str,
        benchmark_return: float = 0.0,
        notes: str = "",
    ) -> str:
        """生成月度复盘报告。"""
        lines = [
            f"# 📈 模拟交易月度复盘",
            f"**月份**: {month_key}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        # 月度统计 vs 基准
        lines.extend(self._monthly_overview(state, month_trades, benchmark_return))

        # 月度统计
        lines.extend(self._period_stats(state, month_trades, "本月"))

        # 最佳/最差交易
        lines.extend(self._best_worst_trades(month_trades))

        # 行业分布
        lines.extend(self._sector_distribution(state))

        # 持仓明细
        lines.extend(self._positions_section(state))

        # 能力圈匹配
        lines.extend(self._competence_fit(state))

        # 策略迭代建议
        lines.extend(self._iteration_suggestions(month_trades))

        if notes:
            lines.append("")
            lines.append("## 📝 复盘笔记")
            lines.append(notes)

        lines.extend(self._footer())
        content = "\n".join(lines)
        filepath = self._monthly / f"month_{month_key}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("月度复盘已保存: %s", filepath)
        return str(filepath)

    # ------------------------------------------------------------------
    # 报告板块
    # ------------------------------------------------------------------

    def _daily_header(self, state: PortfolioState, report_date: str) -> list[str]:
        """日度报告头部。"""
        equity = state.total_equity
        pnl = equity - state.initial_capital
        pnl_pct = state.total_return_pct

        emoji = "🟢" if pnl >= 0 else "🔴"
        return [
            f"# 📋 模拟交易日度报告",
            f"**日期**: {report_date}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 💰 账户概览",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 初始资金 | ¥{state.initial_capital:,.0f} |",
            f"| 当前权益 | ¥{equity:,.2f} |",
            f"| 累计盈亏 | {emoji} ¥{pnl:+,.2f} ({pnl_pct:+.2%}) |",
            f"| 现金余额 | ¥{state.cash:,.2f} |",
            f"| 持仓市值 | ¥{state.positions_value:,.2f} |",
            f"| 仓位占比 | {state.exposure_pct:.1%} |",
            f"| 累计佣金 | ¥{state.total_commission_paid:,.2f} |",
            f"| 历史最高 | ¥{state.high_water_mark:,.2f} |",
            f"| 当前回撤 | {state.drawdown_pct:.2%} |",
            f"| 累计交易 | {state.total_trades} 笔 (胜率 {state.win_rate:.1%}) |",
            "",
        ]

    def _daily_pnl_section(
        self, state: PortfolioState, today_trades: list[PaperTrade],
    ) -> list[str]:
        """当日盈亏。"""
        lines = ["## 📊 当日盈亏"]
        # 简化: 从交易记录推算当日变动
        buy_total = sum(t.net_amount for t in today_trades if t.action == "buy")
        sell_total = sum(t.net_amount for t in today_trades if t.action == "sell")
        cost_total = sum(t.total_cost for t in today_trades)

        if today_trades:
            lines.append(f"| 类型 | 金额 |")
            lines.append(f"|------|------|")
            lines.append(f"| 买入支出 | ¥{abs(buy_total):,.2f} |")
            lines.append(f"| 卖出收入 | ¥{sell_total:,.2f} |")
            lines.append(f"| 交易成本 | ¥{cost_total:,.2f} |")
        else:
            lines.append("今日无交易。")
        lines.append("")
        return lines

    def _positions_section(self, state: PortfolioState) -> list[str]:
        """持仓明细。"""
        lines = [
            "## 📦 当前持仓",
        ]
        if not state.positions:
            lines.append("空仓。")
            lines.append("")
            return lines

        lines.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 盈亏% | 止损 | 阶段 |")
        lines.append("|------|------|------|------|------|------|-------|------|------|")
        for sym, pos in state.positions.items():
            name = getattr(pos, "name", "")
            qty = getattr(pos, "quantity", 0)
            entry = getattr(pos, "entry_price", 0.0)
            last = getattr(pos, "last_price", entry)
            mkt_val = qty * last
            pnl = (last - entry) / entry * 100 if entry > 0 else 0
            stop = getattr(pos, "stop_price", 0.0)
            stage = getattr(pos, "stop_stage", "initial")
            lines.append(
                f"| {sym} | {name} | {qty} | ¥{entry:.2f} | ¥{last:.2f} | "
                f"¥{mkt_val:,.0f} | {pnl:+.2f}% | ¥{stop:.2f} | {stage} |"
            )
        lines.append("")
        return lines

    def _trades_section(
        self, trades: list[PaperTrade], title: str = "交易记录",
    ) -> list[str]:
        """交易记录表格。"""
        lines = [f"## 🔄 {title}"]
        if not trades:
            lines.append("无交易记录。")
            lines.append("")
            return lines

        lines.append("| 时间 | 代码 | 方向 | 价格 | 数量 | 金额 | 成本 | 原因 |")
        lines.append("|------|------|------|------|------|------|------|------|")
        for t in trades:
            direction = "🟢买入" if t.action == "buy" else "🔴卖出"
            lines.append(
                f"| {t.timestamp[:16]} | {t.symbol} | {direction} | "
                f"¥{t.price:.2f} | {t.quantity} | ¥{t.notional:,.0f} | "
                f"¥{t.total_cost:.2f} | {t.reason[:30]} |"
            )
        lines.append("")
        return lines

    def _risk_section(self, state: PortfolioState) -> list[str]:
        """风控状态。"""
        dd = state.drawdown_pct
        level = "🟢 正常" if dd < 0.10 else ("🟡 关注" if dd < 0.15 else "🔴 预警")
        return [
            "## 🛡️ 风控状态",
            f"| 指标 | 数值 | 状态 |",
            f"|------|------|------|",
            f"| 回撤 (从 HWM) | {dd:.2%} | {level} |",
            f"| 仓位占比 | {state.exposure_pct:.1%} | {'正常' if state.exposure_pct <= 0.8 else '超限'} |",
            f"| 现金占比 | {state.cash / state.initial_capital:.1%} | {'正常' if state.cash >= state.initial_capital * 0.2 else '偏低'} |",
            "",
        ]

    def _best_worst_trades(self, trades: list[PaperTrade]) -> list[str]:
        """最佳/最差交易。"""
        lines = ["## 🏆 最佳 / 最差交易"]
        sells = [t for t in trades if t.action == "sell" and t.pnl_pct != 0]
        if not sells:
            lines.append("本周无卖出交易，无已实现盈亏。")
            lines.append("")
            return lines

        sells_sorted = sorted(sells, key=lambda t: t.pnl_pct, reverse=True)
        best = sells_sorted[:3]
        worst = sells_sorted[-3:]

        lines.append("### 最佳")
        for t in best:
            lines.append(f"- {t.symbol} {t.name}: {t.pnl_pct:+.2%} @ ¥{t.price:.2f}")
        lines.append("### 最差")
        for t in reversed(worst):
            lines.append(f"- {t.symbol} {t.name}: {t.pnl_pct:+.2%} @ ¥{t.price:.2f}")
        lines.append("")
        return lines

    def _period_stats(
        self, state: PortfolioState, trades: list[PaperTrade], label: str,
    ) -> list[str]:
        """周期统计。"""
        buys = [t for t in trades if t.action == "buy"]
        sells = [t for t in trades if t.action == "sell"]
        total_cost = sum(t.total_cost for t in trades)
        win_sells = [t for t in sells if t.pnl_pct > 0]

        return [
            f"## 📈 {label}统计",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 交易笔数 | {len(trades)} (买 {len(buys)} / 卖 {len(sells)}) |",
            f"| 已实现盈利笔数 | {len(win_sells)}/{len(sells)} |",
            f"| 交易成本合计 | ¥{total_cost:,.2f} |",
            f"| 当前权益 | ¥{state.total_equity:,.2f} |",
            f"| 累计收益率 | {state.total_return_pct:+.2%} |",
            "",
        ]

    def _manipulation_observations(self, trades: list[PaperTrade]) -> list[str]:
        """庄家行为观察 — 供复盘参考。"""
        lines = [
            "## 🦈 庄家行为观察",
            "",
            "> ⚠️ 以下为 AI 对本周盘面异常行为的观察，仅供参考。",
            "",
        ]

        # 检查异常模式
        sells = [t for t in trades if t.action == "sell"]
        stop_losses = [t for t in sells if "止损" in t.reason or "清仓" in t.reason]

        if stop_losses:
            lines.append("### 止损事件")
            for t in stop_losses:
                lines.append(f"- {t.symbol} {t.name}: {t.reason}")
            lines.append("")
            lines.append("**反思**: 是否被洗盘？止损位设置是否过紧？")
            lines.append("")

        # 检查是否有高位买入后快速下跌
        buys = [t for t in trades if t.action == "buy"]
        if buys and sells:
            lines.append("### 买卖节奏")
            lines.append(f"- 买入 {len(buys)} 笔，卖出 {len(sells)} 笔")
            lines.append("- 检查是否存在追涨杀跌的倾向")
            lines.append("")

        if not stop_losses and not sells:
            lines.append("本周无异常庄家行为信号。")

        lines.append("")
        return lines

    def _strategy_deviation(self, trades: list[PaperTrade]) -> list[str]:
        """策略偏差分析。"""
        return [
            "## 📐 策略偏差检查",
            "",
            "- [ ] 是否严格遵守了单票≤20%的仓位上限？",
            "- [ ] 是否在能力圈范围内交易？",
            "- [ ] 是否有冲动交易 (未经完整管道分析)？",
            "- [ ] 卖出是否基于裁决信号而非情绪？",
            "- [ ] 止损执行是否及时？",
            "",
        ]

    def _monthly_overview(
        self, state: PortfolioState, trades: list[PaperTrade],
        benchmark_return: float,
    ) -> list[str]:
        """月度总览 vs 基准。"""
        alpha = state.total_return_pct - benchmark_return
        return [
            "## 📊 月度总览",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 模拟交易月收益 | {state.total_return_pct:+.2%} |",
            f"| 基准 (沪深300) | {benchmark_return:+.2%} |",
            f"| Alpha (超额收益) | {alpha:+.2%} |",
            f"| 当前权益 | ¥{state.total_equity:,.2f} |",
            f"| 最大回撤 | {state.drawdown_pct:.2%} |",
            f"| 交易笔数 | {len(trades)} |",
            f"| 累计佣金 | ¥{state.total_commission_paid:,.2f} |",
            "",
        ]

    def _sector_distribution(self, state: PortfolioState) -> list[str]:
        """行业分布 (简化版，基于股票名称前缀)。"""
        lines = [
            "## 🏭 行业分布",
        ]
        if not state.positions:
            lines.append("空仓。")
            lines.append("")
            return lines
        # 简化的行业分组
        sectors: dict[str, float] = {}
        for sym, pos in state.positions.items():
            # 根据代码前缀粗略判断行业 (后续可接入行业分类)
            name = getattr(pos, "name", sym)
            last = getattr(pos, "last_price", getattr(pos, "entry_price", 0))
            mkt_val = getattr(pos, "quantity", 0) * last
            sector = "其他"
            code = str(sym)
            if code.startswith("600") or code.startswith("601"):
                sector = "上海主板"
            elif code.startswith("000") or code.startswith("002"):
                sector = "深圳主板"
            elif code.startswith("300"):
                sector = "创业板"
            elif code.startswith("688"):
                sector = "科创板"
            sectors[sector] = sectors.get(sector, 0) + mkt_val

        total_val = sum(sectors.values()) or 1
        for s, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {s}: ¥{v:,.0f} ({v/total_val:.1%})")
        lines.append("")
        return lines

    def _competence_fit(self, state: PortfolioState) -> list[str]:
        """能力圈匹配度 (简化版)。"""
        return [
            "## 🎯 能力圈匹配",
            "",
            "> 检查当前持仓是否在已知能力圈范围内 (新能源/科技/半导体/AI/航天)。",
            "> 周/月复盘时更新此部分。",
            "",
        ]

    def _iteration_suggestions(self, trades: list[PaperTrade]) -> list[str]:
        """策略迭代建议。"""
        lines = [
            "## 💡 策略迭代建议",
            "",
            "基于本月交易表现，考虑以下调整：",
            "",
        ]
        sells = [t for t in trades if t.action == "sell"]
        win_rate = (
            len([t for t in sells if t.pnl_pct > 0]) / len(sells)
            if sells else 0
        )
        if sells and win_rate < 0.4:
            lines.append("- ⚠️ 胜率偏低，考虑提高入场标准 (verdict.score 阈值从 70 → 75)")
        if sells and win_rate > 0.6:
            lines.append("- ✅ 胜率良好，可考虑适度提高单票仓位上限")
        # 成本分析
        total_cost = sum(t.total_cost for t in trades)
        if total_cost > 100:
            lines.append(f"- 💸 月度交易成本 ¥{total_cost:,.0f}，注意控制换手率")
        if len(trades) > 20:
            lines.append("- ⚠️ 交易频率偏高，检查是否存在过度交易")

        if not sells:
            lines.append("- 本月无卖出记录，继续持有观察")

        lines.append("")
        return lines

    def _footer(self) -> list[str]:
        return [
            "---",
            f"*报告由白泽模拟交易引擎自动生成 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "> ⚠️ AI 模拟交易结果，不构成投资建议。投资有风险，入市需谨慎。",
        ]
