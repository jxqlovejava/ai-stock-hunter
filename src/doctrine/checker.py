# -*- coding: utf-8 -*-
"""军规核查引擎。

在准入检查之前运行，逐条审查 30 条军规，输出:
  - blocked: 被 block 级军规拦截，不允许继续分析
  - warnings: warn 级军规触发，标注风险
  - infos: info 级军规触发，仅记录
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import MILITARY_RULES, Rule, Severity


@dataclass
class DoctrineResult:
    """军规审查结果。"""
    passed: bool = True                      # 是否通过（无 block 触发）
    blocked_by: list[Rule] = field(default_factory=list)
    warnings: list[Rule] = field(default_factory=list)
    infos: list[Rule] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.passed:
            parts = []
            if self.warnings:
                parts.append(f"⚠️ {len(self.warnings)} warnings")
            if self.infos:
                parts.append(f"ℹ️ {len(self.infos)} infos")
            return "✅ 军规通过" + (f" ({', '.join(parts)})" if parts else "")
        return f"⛔ 被 {len(self.blocked_by)} 条 block 规则拦截"


class DoctrineChecker:
    """30 条军规核查器。

    用法:
        checker = DoctrineChecker()
        result = checker.check(symbol="600519", context={...})
        if not result.passed:
            print(result.summary)  # ⛔ 被 r006 (ST/*ST 一票否决) 拦截
    """

    # Block 级军规检查函数（按类别）
    _BLOCK_CHECKS: dict[str, callable] = {}
    _WARN_CHECKS: dict[str, callable] = {}

    def check(
        self,
        symbol: str = "",
        context: dict | None = None,
        enabled_rules: set[str] | None = None,
    ) -> DoctrineResult:
        """执行军规审查。

        Args:
            symbol: 股票代码
            context: 包含持仓/市场/用户画像等信息的字典
            enabled_rules: 启用的规则 ID 集合。None = 全部启用。
                           可用于按投资者层级过滤规则。

        Returns:
            DoctrineResult with pass/fail status
        """
        ctx = context or {}
        result = DoctrineResult()

        for rule in MILITARY_RULES:
            if enabled_rules is not None and rule.id not in enabled_rules:
                continue
            triggered = self._evaluate(rule, symbol, ctx)
            if not triggered:
                continue

            if rule.severity == Severity.BLOCK:
                result.blocked_by.append(rule)
                result.passed = False
            elif rule.severity == Severity.WARN:
                result.warnings.append(rule)
            else:
                result.infos.append(rule)

        return result

    def _evaluate(self, rule: Rule, symbol: str, ctx: dict) -> bool:
        """判断单条军规是否被触发。

        基础实现检查 context 中的对应字段。子类可覆盖。
        """
        # ST 检查
        if rule.id == "r006":
            name = ctx.get("stock_name", "")
            return "ST" in name.upper() or "*ST" in name.upper()

        # 涨停检查
        if rule.id == "r012":
            return ctx.get("is_limit_up", False)

        # 不接飞刀：急跌无基本面改善，或 A/B 段空头仍强
        if rule.id == "r013":
            drop_3 = ctx.get("drop_3day_pct", 0.0) or 0.0
            fund_ok = ctx.get("fundamental_improving", False)
            if drop_3 <= -15.0 and not fund_ok:
                return True
            phase = str(ctx.get("bottom_phase", "") or "")
            ab = ctx.get("bottom_ab_ratio", None)
            if phase == "CATCHING_KNIFE":
                return True
            if ab is not None and float(ab) >= 1.0 and phase not in (
                "LIGHT_LONG_SETUP", "COUNTER_CONFIRMED", "NOT_IN_DOWNTREND", ""
            ):
                return True
            return False

        # 大底须走出：禁止「感觉抄底」；未走完结构不得试多
        if rule.id == "r013b":
            phase = str(ctx.get("bottom_phase", "") or "")
            # 明确接飞刀 / 顺势未衰竭
            if phase == "CATCHING_KNIFE":
                return True
            # 下跌中但仅顺势衰竭、逆势未确认 — 提醒不得动手
            if phase == "TREND_EXHAUSTED":
                return True
            # 外部显式标记：想抄底但结构未允许
            if ctx.get("wants_bottom_fish", False) and not ctx.get(
                "bottom_entry_allowed", False
            ):
                return True
            return False

        # 利好出尽是利空：重大利好 + 5 日涨幅 > 15%
        if rule.id == "r014":
            has_news = ctx.get("has_major_positive_news", False)
            rise_5 = ctx.get("rise_5day_pct", 0.0) or 0.0
            return has_news and rise_5 > 15.0

        # 追涨熔断：5 日涨幅 > 20%（不论消息面）
        if rule.id == "r014b":
            rise_5 = ctx.get("rise_5day_pct", 0.0) or 0.0
            return rise_5 > 20.0

        # 财报窗口检查
        if rule.id == "r015":
            return ctx.get("is_earnings_window", False)

        # 连续止损检查
        if rule.id == "r017":
            return ctx.get("consecutive_stops", 0) >= 3

        # 大盘暴跌检查
        if rule.id == "r018":
            return ctx.get("market_drop_pct", 0) < -3.0

        # 盈利上移止损
        if rule.id == "r019":
            return ctx.get("unrealized_profit_pct", 0) > 20.0

        # 小作文检查
        if rule.id == "r024":
            return ctx.get("source_is_rumor", False)

        # 单笔止损
        if rule.id == "r025":
            return ctx.get("position_loss_pct", 0) <= -2.0

        # 组合回撤熔断
        if rule.id == "r026":
            return ctx.get("portfolio_drawdown_pct", 0) <= -15.0

        # 元风控: 系统熔断
        if rule.id == "r031":
            return ctx.get("rolling_3m_winrate", 1.0) < 0.4

        # ── 财务质量军规 ──
        # ROE 连续性: 近 3 年 ROE 均 > 10% 且无年度亏损
        if rule.id == "r032":
            roe_history = ctx.get("roe_history", [])  # [year-2, year-1, year-0]
            if not roe_history or len(roe_history) < 3:
                return True  # 数据不足，触发警告
            return any(r < 10.0 for r in roe_history) or any(r < 0 for r in roe_history)

        # 现金流质量: 近 3 年累计 OCF/累计 NP > 0.8
        if rule.id == "r033":
            ocf = ctx.get("operating_cash_flow_3y", 0.0)   # 近 3 年累计经营现金流
            np_ = ctx.get("net_profit_3y", 0.0)             # 近 3 年累计净利润
            if np_ <= 0:
                return True  # 净利润为负或为零，触发警告
            return (ocf / np_) < 0.8

        # 分红门槛: 近 3 年累计分红/净利润 > 30%
        if rule.id == "r034":
            dividend = ctx.get("dividend_3y", 0.0)
            np_ = ctx.get("net_profit_3y", 0.0)
            if np_ <= 0:
                return False  # 亏损公司不触发分红警告（属于更严重的 r032 范畴）
            return (dividend / np_) <= 0.30

        # 默认不触发
        return False

    def block_rules(self) -> list[Rule]:
        """返回所有 block 级军规。"""
        return [r for r in MILITARY_RULES if r.severity == Severity.BLOCK]

    def warn_rules(self) -> list[Rule]:
        """返回所有 warn 级军规。"""
        return [r for r in MILITARY_RULES if r.severity == Severity.WARN]

    def info_rules(self) -> list[Rule]:
        """返回所有 info 级军规。"""
        return [r for r in MILITARY_RULES if r.severity == Severity.INFO]
