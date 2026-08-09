# -*- coding: utf-8 -*-
"""军规核查引擎。

在准入检查之前运行，逐条审查 52 条军规，输出:
  - blocked: 被 block 级军规拦截，不允许继续分析
  - warnings: warn 级军规触发，标注风险
  - infos: info 级军规触发，仅记录

判定原则:
  - 有明确数据依据的规则读取 ctx 字段做判定
  - 无数据 / 字段缺失时一律不触发（防御性，避免误报）
  - 纯信息/提示类规则在代码注释中标注说明，通常仅当 ctx 显式置位才触发
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pattern_features import is_low_price, turnover_rate_extreme
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
    """52 条军规核查器。

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

        # 连续止损检查 (r017): 连续 ≥3 次止损后强制休整 ≥3 个交易日
        # 读取 ctx.consecutive_stops（由 risk 模块注入）；缺键/None/非数字 → 无数据不触发
        if rule.id == "r017":
            stops = ctx.get("consecutive_stops")
            if stops is None:
                return False
            try:
                return int(stops) >= 3
            except (TypeError, ValueError):
                return False

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

        # 200 周均线跌破 — 无条件红牌
        if rule.id == "r035":
            return ctx.get("price_below_wma200_week", False)

        # 200 周均线站回不足 N 周 — 趋势未确认
        # 使用替代 MA 时阈值提高至 8 周（替代 MA 信号更弱，需更多确认）
        if rule.id == "r036":
            weeks = ctx.get("weeks_above_wma200", 999)
            if weeks is None:
                return False
            penalty = ctx.get("wma_confidence_penalty", 1.0)
            threshold = 8 if penalty < 1.0 else 4
            return weeks < threshold

        # ── 缠论结构军规 ──
        # 中枢破位/三卖 — 结构转弱
        if rule.id == "r037":
            return bool(ctx.get("chanlun_sell_signal")) or bool(ctx.get("chanlun_zs_break"))

        # 背驰未确认不进场 — 中枢破位且无买点/底背驰确认
        if rule.id == "r038":
            if not ctx.get("chanlun_zs_break"):
                return False
            if ctx.get("chanlun_buy_confirmed"):
                return False
            if ctx.get("chanlun_bihuang_down"):
                return False
            return True

        # ── P0-4 补全：仓位与资金管理 ──
        # r001 单票仓位上限: 单票仓位 > max_single_pct（默认 20）→ BLOCK
        if rule.id == "r001":
            pct = ctx.get("single_stock_pct")
            if pct is None:
                return False
            cap = ctx.get("max_single_pct", 20.0)
            try:
                return float(pct) > float(cap)
            except (TypeError, ValueError):
                return False

        # r002 总仓位上限: 股票头寸 > max_total_exposure（默认 80）→ BLOCK
        if rule.id == "r002":
            pct = ctx.get("total_stock_pct")
            if pct is None:
                return False
            cap = ctx.get("max_total_exposure", 80.0)
            try:
                return float(pct) > float(cap)
            except (TypeError, ValueError):
                return False

        # r003 行业集中度: 单行业仓位 > max_sector_pct（默认 40）→ BLOCK
        if rule.id == "r003":
            pct = ctx.get("sector_stock_pct")
            if pct is None:
                return False
            cap = ctx.get("max_sector_pct", 40.0)
            try:
                return float(pct) > float(cap)
            except (TypeError, ValueError):
                return False

        # r004 创业板/科创板折扣: 双创标的仓位需 ×0.8 → WARN
        if rule.id == "r004":
            return bool(ctx.get("is_chinext") or ctx.get("is_star_market"))

        # r005 永不满仓: 保留现金 ≥10%（现金比例 < 10 即触发）→ WARN
        if rule.id == "r005":
            cash = ctx.get("cash_pct")
            if cash is None:
                return False
            try:
                return float(cash) < 10.0
            except (TypeError, ValueError):
                return False

        # ── P0-4 补全：选股与估值纪律 ──
        # r007 次新股冷静期: 上市 < 60 交易日 → WARN
        if rule.id == "r007":
            days = ctx.get("listing_days")
            if days is None:
                return False
            try:
                return float(days) < 60.0
            except (TypeError, ValueError):
                return False

        # r008 不懂不投: 超出能力圈 → WARN
        if rule.id == "r008":
            return bool(ctx.get("out_of_circle_of_competence"))

        # r009 PE 极端值: PE 为负 或 > 行业均值 3 倍 → WARN
        if rule.id == "r009":
            pe = ctx.get("pe_ratio")
            if pe is None:
                return False
            try:
                pe = float(pe)
            except (TypeError, ValueError):
                return False
            if pe < 0:
                return True
            ind_mean = ctx.get("industry_pe_mean")
            if ind_mean is not None:
                try:
                    return pe > float(ind_mean) * 3.0
                except (TypeError, ValueError):
                    return False
            return False

        # r010 商誉雷: 商誉/净资产 > 30% → WARN
        if rule.id == "r010":
            ratio = ctx.get("goodwill_ratio")
            if ratio is None:
                return False
            try:
                return float(ratio) > 0.30
            except (TypeError, ValueError):
                return False

        # r011 股权质押: 大股东质押 > 50% → WARN
        if rule.id == "r011":
            ratio = ctx.get("pledge_ratio")
            if ratio is None:
                return False
            try:
                return float(ratio) > 0.50
            except (TypeError, ValueError):
                return False

        # ── P0-4 补全：买卖纪律 ──
        # r016 分批建仓: 新建仓分 < 2 批 → WARN
        if rule.id == "r016":
            batches = ctx.get("entry_batch_count")
            if batches is None:
                return False
            try:
                return int(batches) < 2
            except (TypeError, ValueError):
                return False

        # ── P0-4 补全：情绪纪律 ──
        # r020 空仓视角检验: 空仓会在现价买入吗？(外部显式置位才触发)
        if rule.id == "r020":
            return bool(ctx.get("empty_position_test_fail"))

        # r021 拒绝爱上持仓: 连续 3 次拒绝卖出建议 → WARN
        if rule.id == "r021":
            cnt = ctx.get("refused_sell_count")
            if cnt is None:
                return False
            try:
                return int(cnt) >= 3
            except (TypeError, ValueError):
                return False

        # ── P0-4 补全：信息纪律 ──
        # r022 信源交叉验证: 关键决策数据 < 2 个 T1+ 来源 → BLOCK
        if rule.id == "r022":
            src = ctx.get("source_tier1_count")
            if src is None:
                return False
            try:
                return int(src) < 2
            except (TypeError, ValueError):
                return False

        # r023 机构研报≠事实: 机构目标价仅作参考 (外部显式置位才触发)
        if rule.id == "r023":
            return bool(ctx.get("analyst_only_target"))

        # ── P0-4 补全：风控与止盈止损 ──
        # r027 流动性熔断: 持仓市值 > 日均成交额 5% → 禁止加仓 → WARN
        if rule.id == "r027":
            mv = ctx.get("position_market_value")
            turnover = ctx.get("daily_turnover")
            if mv is None or turnover is None:
                return False
            try:
                mv = float(mv)
                turnover = float(turnover)
            except (TypeError, ValueError):
                return False
            if turnover <= 0:
                return False
            return mv > turnover * 0.05

        # r028 移动止盈: 浮盈 > 30% → 启动 ATR 移动止盈 → WARN
        if rule.id == "r028":
            profit = ctx.get("unrealized_profit_pct")
            if profit is None:
                return False
            try:
                return float(profit) > 30.0
            except (TypeError, ValueError):
                return False

        # ── P0-4 补全：复盘与进化（信息/提示类，需外部置位）──
        # r029 决策书面记录: 每次交易留书面记录 (外部置位 trade_journal_missing)
        if rule.id == "r029":
            return bool(ctx.get("trade_journal_missing"))

        # r030 错题本更新: 止损/亏损交易 72h 内写教训 (外部置位 lesson_not_logged)
        if rule.id == "r030":
            return bool(ctx.get("lesson_not_logged"))

        # ── P0-4 补全：反操纵军规 (原 R032-R034，重编号 r039-r041) ──
        # r039 筹码集中度: 前十大流通股东 >60% 或 股东户数连续降 >15% → WARN
        if rule.id == "r039":
            top10 = ctx.get("top10_holding_pct")
            if top10 is not None:
                try:
                    if float(top10) > 60.0:
                        return True
                except (TypeError, ValueError):
                    pass
            decline = ctx.get("holder_decline_pct")
            if decline is not None:
                try:
                    return float(decline) > 15.0
                except (TypeError, ValueError):
                    return False
            return False

        # r040 操纵历史: 12 个月内 ≥3 次操纵嫌疑 → WARN
        if rule.id == "r040":
            cnt = ctx.get("manipulation_history_count")
            if cnt is None:
                return False
            try:
                return int(cnt) >= 3
            except (TypeError, ValueError):
                return False

        # r041 资金背离: 主力连续 5 日流出但价格不跌/涨 → WARN
        if rule.id == "r041":
            outflow = ctx.get("main_capital_outflow_days")
            if outflow is None:
                return False
            try:
                outflow = int(outflow)
            except (TypeError, ValueError):
                return False
            if outflow < 5:
                return False
            chg = ctx.get("price_change_pct")
            if chg is None:
                return False
            try:
                return float(chg) >= 0.0
            except (TypeError, ValueError):
                return False

        # ── P0-2 新增军规 ──
        # r042 亏损后禁止报复性加仓: 单笔止损后当日禁止追加仓位/摊平 → BLOCK
        # ctx 字段: recent_stops (当日已止损记录) + intended_action / averaging_down
        if rule.id == "r042":
            recent_stops = ctx.get("recent_stops")
            stop_today = ctx.get("stop_occurred_today", False)
            if recent_stops is None and stop_today is False:
                return False  # 无止损数据 → 不触发
            # 归一化 recent_stops: 可接受 list / int 计数
            if isinstance(recent_stops, (list, tuple)):
                stop_today = stop_today or len(recent_stops) > 0
            elif isinstance(recent_stops, (int, float)):
                stop_today = stop_today or int(recent_stops) > 0
            elif isinstance(recent_stops, dict):
                stop_today = stop_today or bool(recent_stops.get("count", 0))
            if not stop_today:
                return False
            # 当日存在加仓/摊平意图才触发（防御：意图未知不误报）
            intended = str(ctx.get("intended_action", "") or "").upper()
            sig = str(ctx.get("signal_action", "") or "").upper()
            avg_down = ctx.get("averaging_down", False)
            if avg_down:
                return True
            return intended in ("ADD", "OPEN", "BUY", "INCREASE", "加仓", "补仓") or \
                sig in ("ADD", "OPEN", "BUY")

        # r043 信息面冲突即禁止开仓: 技术买/加 与 基本面/政策/新闻负面冲突 → BLOCK
        # ctx 字段: signal_action / technical_direction 为买; fundamental_direction /
        #   news_polarity / news_sentiment / policy_direction 为负面; 或显式 info_conflict
        # 注意: 不使用 fundamental_improving（orchestrator 默认注入 False，会误报）。
        if rule.id == "r043":
            sig = str(ctx.get("signal_action", "") or "").upper()
            if not sig:
                sig = str(ctx.get("technical_direction", "") or "").upper()
            buy_sig = sig in ("BUY", "ADD", "OPEN", "INCREASE", "LONG", "看多", "买入", "加仓")
            if not buy_sig:
                return False  # 无买入信号 → 不触发
            if ctx.get("info_conflict", False):
                return True
            # 信息面负面方向（任一命中即冲突）
            fund_dir = str(ctx.get("fundamental_direction", "") or "").upper()
            if fund_dir in ("NEGATIVE", "BEARISH", "DOWN", "WEAK", "利空", "看空"):
                return True
            pol_dir = str(ctx.get("policy_direction", "") or "").upper()
            if pol_dir in ("NEGATIVE", "RESTRICTIVE", "TIGHTEN", "利空", "收紧"):
                return True
            news = ctx.get("news_polarity")
            if news is None:
                news = ctx.get("news_sentiment")
            if isinstance(news, (int, float)):
                return news < 0
            if isinstance(news, str):
                return news.upper() in ("NEGATIVE", "BEARISH", "DOWN", "利空", "看空")
            return False

        # r044 涨停次日低开位置解读: 前日涨停且今日低开 → 按位置提示（出货/洗盘）
        # ctx 字段: limit_up_next_day_gap_down (bool, 由 tactics 注入)
        if rule.id == "r044":
            return bool(ctx.get("limit_up_next_day_gap_down", False))

        # r045 弱势突破不追: 突破信号强度 WEAK → 不追入
        # ctx 字段: breakout_weak (bool, 由 tactics 注入)
        if rule.id == "r045":
            return bool(ctx.get("breakout_weak", False))

        # ── 技术面铁律军规 (r046-r050) ──
        # r046 换手率极端: 单日换手率 > 40%（非启动/涨停日）→ WARN
        # ctx 字段: turnover_rate_pct (float, 由 tactics 从日线 df 提取) + is_limit_up
        if rule.id == "r046":
            tr = ctx.get("turnover_rate_pct")
            if turnover_rate_extreme(tr):
                # 启动首日/涨停日换手放大属正常，不算"主力散户对打"
                return not bool(ctx.get("is_limit_up", False))
            return False

        # r047 乖离过大等回调: 收盘 vs MA20 乖离 > 15% → WARN
        # ctx 字段: bias_vs_ma20_pct (float, 由 tactics/orchestrator 注入)
        if rule.id == "r047":
            bias = ctx.get("bias_vs_ma20_pct")
            if bias is None:
                return False
            try:
                return float(bias) > 15.0
            except (TypeError, ValueError):
                return False

        # r048 低价股价值陷阱: 股价 < 6 元 → WARN（软标记）
        # ctx 字段: current_price (float)
        if rule.id == "r048":
            return is_low_price(ctx.get("current_price"))

        # r049 跳空三连阳出货形态 → WARN
        # ctx 字段: gap_up_three_yang (bool, 由 tactics 从 open/close 序列计算)
        if rule.id == "r049":
            return bool(ctx.get("gap_up_three_yang", False))

        # r050 高位量减价平派发 → WARN
        # ctx 字段: high_vol_price_flat (bool, 由 tactics 从 close/volume 序列计算)
        if rule.id == "r050":
            return bool(ctx.get("high_vol_price_flat", False))

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
