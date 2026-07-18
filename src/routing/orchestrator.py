# -*- coding: utf-8 -*-
"""编排器 — 画像→宏观象限前置→军规→准入检查→反操纵扫描→多维诊断→综合裁决→仓位调度→风控执行→持仓监控 全链路。

Phase 3: 注入 MacroRegime, NorthboundProfile, DominanceProfile,
         EarningsRevisionFactor, Topic 生命周期调整。
Phase 11: 宏观象限前置 + 反操纵全链路联动 + 持仓持续跟踪。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.data.aggregator import DataAggregator
from src.data.source_citation import make_citation, make_data_gap_citation
from src.doctrine.checker import DoctrineChecker
from src.alpha.schema import AlphaProfile
from src.alpha.lens import AlphaLens
from src.kelly.tracker import TradeTracker
from src.kelly.sizer import KellyPositionSizer
from src.quality.checker import MultiAgentQualityChecker
from src.game_theory.manipulation.history import ManipulationHistoryStore, log_manipulation_event
from src.game_theory.manipulation.sizing import ManipulationSizingEngine
from src.game_theory.manipulation.sentiment_nexus import SentimentManipulationNexus

from .admission import AdmissionCheck
from .diagnosis import DiagnosisReport, DiagnosisEngine
from .verdict import VerdictEngine, Verdict
from .positioning import PositioningEngine, TradeSignal
from .risk_control import RiskControlEngine, RiskCheck
from .risk_state import RiskState  # Phase 8: 风控状态机
from .guardrails import GuardrailEnforcer, GuardrailViolation
from .game_theory_analyzer import GameTheoryAnalyzer, GameTheoryProfile
from .investor_mental_model import InvestorMentalModelAnalyzer, InvestorMentalModelFit
from .perspective_engine import PerspectiveAnalyzer
from .anti_bias import AntiBiasEngine
from .verdict_enforcer import VerdictEnforcer
from .mental_model_matcher import MentalModelMatcher
from .position_monitor import PositionMonitor, PositionSnapshot, MonitorResult  # Phase 11
from .position_state import PositionStateManager  # Phase 12: 实时持仓 HWM + 动态止盈止损
from src.output.progress import step_start, step_done, info, warn, section as prog_section, header as prog_header
from src.output.step_output import (
    print_doctrine, print_admission, print_diagnosis,
    print_debate, print_munger_models, print_alpha_game_theory,
    print_verdict, print_positioning, print_risk_control,
    print_source_citations, print_t0, print_deep_research,
    print_sector_impact_summary, print_news_context,
)
from src.output.markdown_report import save_markdown_report

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """全链路分析结果。"""
    symbol: str
    name: str
    strategy_version: str = ""
    strategy_params: dict = field(default_factory=dict)
    passed: bool = False
    gate_status: str = ""
    report: Optional[DiagnosisReport] = None
    verdict: Optional[Verdict] = None
    signal: Optional[TradeSignal] = None
    risk: Optional[RiskCheck] = None
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Phase 3: optional context from enhanced modules
    macro_regime_info: Optional[dict] = None
    dominance_info: Optional[dict] = None
    # Phase 5: 估值 + 周期
    cycle_info: Optional[dict] = None
    valuation_info: Optional[dict] = None
    # Phase 1: guardrail violations
    violations: list[GuardrailViolation] = field(default_factory=list)
    # 投资者偏好
    investor_prefs_applied: dict = field(default_factory=dict)
    # Phase 4: Alpha Lens 视角
    alpha_profile: Optional[AlphaProfile] = None
    # Phase 6: 博弈论 + 投资思维模型
    game_theory_info: Optional[dict] = None
    mental_model_info: Optional[dict] = None
    # 买点/卖点（技术 × 博弈论融合）
    timing_advice: Optional[dict] = None
    # MACD+KDJ 五法辅助（interpretation，confidence≤0.5）
    macd_kdj_signal: Optional[dict] = None
    # Phase 6+: AI Berkshire 四视角辩论
    debate_result: Optional[dict] = None
    # Phase 6+: 四视角详细观点 (含各大师独立评分/论点/担忧)
    debate_perspectives: Optional[dict] = None
    # Phase 6+: Munger 思维模型匹配
    mental_models: list[dict] = field(default_factory=list)
    # Phase 6+: 强制结论
    enforced_verdict: Optional[dict] = None
    # Phase 6+: 三情景估值
    scenario_valuation: Optional[dict] = None
    # Phase 6+: 数据缺口与红线
    data_gaps: list[str] = field(default_factory=list)
    red_lines: list[str] = field(default_factory=list)
    # Phase 3+: 三大根本问题诊断
    fundamental_diagnosis: Optional[dict] = None
    cross_validated: bool = False
    # CogAlpha: 多 Agent 质量审查报告
    quality_report: Optional[dict] = None
    # Phase 7: 行业深度研究 (mode="full")
    sector_research: Optional[dict] = None
    # Phase 8: 公司深度研究 (mode="full")
    company_deep_research: Optional[dict] = None
    # 军规审查结果 (Phase 0)
    doctrine_result: Optional[dict] = None
    # 投资者画像状态
    using_default_profile: bool = False  # 是否使用系统默认画像（未自定义）
    profile_completeness: int = 0         # 画像完整度 0-100
    profile_missing: list[str] = field(default_factory=list)  # 画像缺失项
    # 仓位调度/风控执行 详情
    sizing_detail: Optional[dict] = None  # 仓位计算方法 + 凯利参数
    # Phase 11: 反操纵扫描结果
    manipulation_info: Optional[dict] = None
    # Phase 11: 宏观象限调整
    regime_adjustments_info: Optional[dict] = None
    position_limits_summary: Optional[dict] = None  # 仓位约束摘要
    # T+0 日内时机分析
    t0_result: Optional[dict] = None
    # 宏观事件因果链分析
    macro_event: Optional[dict] = None
    # 多通道资讯上下文
    news_context: Optional[dict] = None
    # 市场情绪完整对象
    market_sentiment: Optional[object] = None
    # 融资融券监控 (v2.0)
    margin_profile: Optional[object] = None
    margin_alerts: list = field(default_factory=list)
    monitor_signals: list = field(default_factory=list)
    # 美股隔夜大盘快照
    us_overnight: Optional[dict] = None
    created_at: datetime = field(default_factory=datetime.now)


class Orchestrator:
    """多层路由编排器。

    流程: 军规 → 准入检查 → 多维诊断 → 质量审查 → 博弈论 → 投资思维模型 → 综合裁决 → 仓位调度 → 风控执行

    用法:
        orch = Orchestrator()
        result = orch.run("600519", "SH")
        if result.passed:
            print(f"建议: {result.signal.action} {result.risk.adjusted_weight:.1%}")

    Phase 3 增强: 自动注入 MacroRegime / NorthboundProfile / Topic 生命周期。
    Phase 6 增强: 接入 GameTheoryAnalyzer / InvestorMentalModelAnalyzer。
    """

    def __init__(self):
        self.data = DataAggregator()
        self.doctrine = DoctrineChecker()
        self.admission = AdmissionCheck()
        self.diagnosis = DiagnosisEngine()
        self.verdict_engine = VerdictEngine()
        # Phase 5: 注入 KellyPositionSizer（默认 half-Kelly=0.5）
        self.trade_tracker = TradeTracker()
        self.kelly_sizer = KellyPositionSizer(
            self.trade_tracker, default_kelly_fraction=0.5,
        )
        self.positioning = PositioningEngine(kelly_sizer=self.kelly_sizer)
        # Phase 8: 风控状态机 (HWM 追踪 / 自动熔断 / NaN 防御)
        self._risk_state = RiskState.initial()
        self.risk_ctrl = RiskControlEngine(state=self._risk_state)
        self.enforcer = GuardrailEnforcer()  # Phase 1: 护栏执行器
        self.alpha_lens = AlphaLens()        # Phase 4: Alpha Lens 引擎
        self.quality_checker = MultiAgentQualityChecker()  # CogAlpha: 多 Agent 质量审查
        # Phase 6: 博弈论 + 投资思维模型
        self.gt_analyzer = GameTheoryAnalyzer(self.data)
        self.imm_analyzer = InvestorMentalModelAnalyzer()
        # Phase 6+: AI Berkshire 层
        self.perspective_analyzer = PerspectiveAnalyzer()
        self.anti_bias_engine = AntiBiasEngine()
        self.verdict_enforcer = VerdictEnforcer()
        self.mental_model_matcher = MentalModelMatcher()
        # Phase 11: 持仓持续跟踪
        self.position_monitor = PositionMonitor()
        # Phase 12: 实时持仓 HWM + 动态止盈止损
        self.position_state_mgr = PositionStateManager()
        # P4/P5/P6: 反操纵增强
        self._manip_history = ManipulationHistoryStore()
        self._manipulation_sizer = ManipulationSizingEngine()
        self._sentiment_nexus = SentimentManipulationNexus()
        # Phase 7: 行业深度研究 (mode="full") — 懒初始化
        self._sector_classifier = None
        self._competition_analyzer = None
        self._sector_valuation = None
        self._supply_chain_mapper = None
        self._sector_validator = None
        self._global_commodity_analyzer = None
        self._moat_analyzer = None
        self._red_flag_detector = None
        self._dcf_valuator = None
        self._management_evaluator = None
        self._report_aggregator = None

    def _init_deep_research_engines(self):
        """懒初始化深度研究引擎，避免导入失败阻断主流程。"""
        try:
            from src.industry.classifier import SectorClassifier
            from src.industry.competition import CompetitionAnalyzer
            from src.industry.valuation import SectorValuationFramework
            from src.industry.supply_chain import SupplyChainDeepMapper
            from src.industry.workflow_validator import SectorWorkflowValidator
            from src.industry.global_commodity import GlobalCommodityAnalyzer
            from src.fundamental.moat import MoatAnalyzer
            from src.fundamental.red_flags import RedFlagDetector
            from src.fundamental.dcf import DCFValuator
            from src.fundamental.management import ManagementEvaluator
            from src.fundamental.report_aggregator import ReportAggregator
            self._sector_classifier = SectorClassifier()
            self._competition_analyzer = CompetitionAnalyzer()
            self._sector_valuation = SectorValuationFramework()
            self._supply_chain_mapper = SupplyChainDeepMapper()
            self._sector_validator = SectorWorkflowValidator()
            self._global_commodity_analyzer = GlobalCommodityAnalyzer()
            self._moat_analyzer = MoatAnalyzer()
            self._red_flag_detector = RedFlagDetector()
            self._dcf_valuator = DCFValuator()
            self._management_evaluator = ManagementEvaluator()
            self._report_aggregator = ReportAggregator()
        except Exception as exc:
            logger.warning("Deep research engines unavailable: %s", exc)

    def run(
        self,
        symbol: str,
        market: str = "SH",
        name: str = "",
        macro: Optional[dict] = None,
        portfolio: Optional[dict] = None,
        strategy_version: str = "",
        strategy_params: Optional[dict] = None,
        mode: str = "daily",
        macro_event_desc: str = "",
        macro_event_category: str = "",
        skip_t0: bool = False,
        as_of_date: str = "",
        selection_mode: bool = False,
    ) -> OrchestratorResult:
        """执行分析管道。

        Args:
            mode:
              - "light"=持仓轻体检（跳过辩论/T+0/深度研究，十秒级）
              - "daily"=标准全链路（无行业公司深度）
              - "full"/"deep"/"selection"=深度（含行业+公司研究）
            macro_event_desc: 当日重大宏观事件描述（如有），触发因果链分析
            macro_event_category: 事件类型 hint (monetary/geopolitical/trade_policy/...)
            skip_t0: True=跳过 T+0 日内时机分析（Alpha/中长期机会搜索时建议禁用）
            as_of_date: 历史回测日期 (YYYY-MM-DD)，替代当前日期。
            selection_mode: True=选股模式，Alpha使用压缩版(保留相对排名,不因赛道无差全体打折)
        """
        # ── light: 持仓轻体检（与 Hermes 哨兵形成三档：sentinel / light / full）──
        if mode == "light":
            from src.routing.light_run import run_light
            return run_light(
                self,
                symbol=symbol,
                market=market,
                name=name,
                portfolio=portfolio,
                strategy_version=strategy_version,
                strategy_params=strategy_params,
            )

        result = OrchestratorResult(
            symbol=symbol, name=name,
            strategy_version=strategy_version,
            strategy_params=strategy_params or {},
        )

        # ── P2: 历史回测模式 ──
        is_backtest = bool(as_of_date)
        if is_backtest:
            logger.info(
                "历史回测模式: as_of=%s — K线/财务/北向/融资使用历史真实数据",
                as_of_date,
            )

        print()  # 空行分隔
        # Step 0: 获取行情数据（双源交叉验证）
        step_start(1, "行情获取 (双源交叉验证)")
        quote, cross_validated, dispute = self.data.get_cross_validated_quote(symbol, market)
        if quote is None:
            # 离线 fallback：尝试从本地 K 线缓存构造 quote
            quote = self._quote_from_cache(symbol, market)
            if quote is None:
                result.passed = False
                result.blocked_by.append("数据不可用")
                return result
            cross_validated = False
            dispute = False
        result.cross_validated = cross_validated

        if not name:
            name = quote.name
            result.name = name

        # 行情 dict 携带交叉验证标记
        quote_dict = quote.model_dump()
        quote_dict["_source"] = quote.source
        quote_dict["cross_validated"] = cross_validated
        quote_dict["dispute"] = dispute

        # 计算 MA20/MA60 + close_series 用于反追高检查
        self._inject_ma_data(symbol, quote_dict)

        cv_label = "✅ 双源一致" if cross_validated else "⚠️ 单源"
        step_done("✅", f"价格 {quote.price:.2f}  {cv_label}")

        # 加载投资者偏好
        investor, result.using_default_profile, result.profile_completeness, result.profile_missing = self._get_investor_prefs()

        # ── 板块可交易性检查 (P0) ──
        # 在进入军规/准入/诊断等昂贵管道之前，先检查投资者是否开通了该标的所属板块。
        # 若板块不可交易，立即拦截，避免浪费 API 配额和分析成本。
        if investor is not None:
            from src.learner.preference.adapter import is_board_accessible
            from src.learner.preference.model import get_board_from_symbol
            if not is_board_accessible(investor, symbol):
                board = get_board_from_symbol(symbol)
                board_name = board.value if board else "未知板块"
                accessible_names = [b.value for b in investor.accessible_boards]
                result.passed = False
                result.blocked_by.append(
                    f"板块限制: {symbol} 属于 {board_name}，"
                    f"不在可交易板块 {accessible_names} 内"
                )
                step_done("⛔", f"板块 {board_name} 未开通交易权限")
                return result

        position_limits = None
        weights = None
        risk_mult = 1.0
        enabled_rules = None
        if investor is not None:
            try:
                from src.learner.preference.adapter import (
                    resolve_weights,
                    resolve_rule_filter,
                    resolve_position_limits,
                    resolve_macro_cap_multiplier,
                )
                position_limits = resolve_position_limits(investor)
                weights = resolve_weights(investor)
                risk_mult = resolve_macro_cap_multiplier(investor)
                enabled_rules = resolve_rule_filter(investor)
                result.investor_prefs_applied = {
                    "risk_profile": investor.risk_profile.value,
                    "investment_goal": investor.investment_goal.value,
                    "tier": investor.tier.value,
                    "weights_applied": weights,
                    "risk_multiplier": risk_mult,
                }
                # 保存仓位约束摘要
                limits = investor.position_limits
                result.position_limits_summary = {
                    "total_capital": limits.total_capital,
                    "_capital_is_default": limits.total_capital == 500000.0,
                    "max_single_pct": limits.max_single_pct,
                    "max_sector_pct": limits.max_sector_pct,
                    "max_total_exposure": limits.max_total_exposure,
                    "min_cash_pct": limits.min_cash_pct,
                    "single_stop_loss_pct": limits.single_stop_loss_pct,
                    "portfolio_drawdown_pct": limits.portfolio_drawdown_pct,
                    "kelly_fraction": getattr(limits, "kelly_fraction", 0.5),
                }
            except Exception as e:
                logger.debug("Failed to resolve investor preferences: %s", e)

        # Step 1: 军规门禁
        step_start(2, "军规门禁 (31条规则)")
        ctx = {"stock_name": name, **(portfolio or {})}
        if investor is not None:
            ctx["tier"] = investor.tier.value
            ctx["max_single_pct"] = investor.position_limits.max_single_pct
            ctx["portfolio_drawdown_pct"] = investor.position_limits.portfolio_drawdown_pct

        # 注入 r014/r014b 军规检查所需上下文
        close_series = quote_dict.get("close_series", [])
        rise_5day = 0.0
        if len(close_series) >= 6:
            latest = close_series[-1]
            ago5 = close_series[-6]
            if ago5 and ago5 > 0:
                rise_5day = (latest - ago5) / ago5 * 100.0
        ctx["rise_5day_pct"] = round(rise_5day, 2)
        # 新闻上下文在更晚阶段获取，此处先安全默认为 False。
        # r014b 不受影响（不依赖新闻）；r014 由后续 diagnosis.surge_risk 兜底。
        ctx["has_major_positive_news"] = False

        # 注入 r013/r013b：3 日急跌 + 底部结构 A/B 段
        if len(close_series) >= 4:
            c0, c3 = close_series[-1], close_series[-4]
            if c3 and c3 > 0:
                ctx["drop_3day_pct"] = round((c0 - c3) / c3 * 100.0, 2)
        ctx["fundamental_improving"] = bool(
            quote_dict.get("fundamental_improving", False)
        )
        self._inject_bottom_structure_ctx(symbol, market, quote_dict, ctx)

        # 注入 r032/r033/r034 财务质量军规所需上下文
        self._inject_financial_doctrine_ctx(symbol, market, ctx)

        doctrine_result = self.doctrine.check(symbol, ctx, enabled_rules=enabled_rules)
        if not doctrine_result.passed:
            result.passed = False
            result.blocked_by = [r.name for r in doctrine_result.blocked_by]
            result.warnings = [r.name for r in doctrine_result.warnings]
            return result
        result.warnings = [r.name for r in doctrine_result.warnings]
        # 保存完整军规结果供格式化器使用 — 含全部 31 条规则的逐条状态
        triggered_ids = {r.id for r in doctrine_result.blocked_by + doctrine_result.warnings + doctrine_result.infos}
        from src.doctrine.rules import MILITARY_RULES
        all_rules = []
        for rule in MILITARY_RULES:
            if enabled_rules is not None and rule.id not in enabled_rules:
                continue
            status = "blocked" if rule in doctrine_result.blocked_by else (
                "warn" if rule in doctrine_result.warnings else (
                "info" if rule in doctrine_result.infos else "passed"))
            all_rules.append({
                "id": rule.id, "name": rule.name,
                "category": rule.category.value,
                "severity": rule.severity.value,
                "description": rule.description,
                "status": status,
            })
        result.doctrine_result = {
            "passed": doctrine_result.passed,
            "total": len(all_rules),
            "blocked_count": len(doctrine_result.blocked_by),
            "warn_count": len(doctrine_result.warnings),
            "info_count": len(doctrine_result.infos),
            "rules": all_rules,
            # 携带实际财务数据供显示
            "financial_data": _build_financial_display_data(ctx),
        }
        bc = len(doctrine_result.blocked_by)
        wc = len(doctrine_result.warnings)
        step_done("✅", f"通过 {len(all_rules)}/{len(all_rules)}  阻断:{bc} 警告:{wc}")
        print_doctrine(result.doctrine_result)
        # 初始化终端 Workflow 清单
        _wf = ["🏥军规✅", "🚪准入", "🌐增强上下文", "📊多维诊断", "🎭辩论/Munger", "⏱️T+0", "⚖️裁决", "💰调度/🛡️风控", "📊溯源"]
        print(f"\n  📋 分析管道: {' → '.join(_wf)}")

        # Step 2: 准入检查 — 尝试从数据源获取实际上市日期
        step_start(3, "准入检查 (ST/次新/流动性/停牌)")
        gate_ctx = {
            "is_limit_up": False,
            "is_limit_down": False,
            "is_suspended": False,
        }
        try:
            q = self.data.get_quote(symbol, market)
            if q:
                if q.listing_date:
                    gate_ctx["listing_date"] = q.listing_date
                if q.turnover and q.turnover > 0:
                    gate_ctx["avg_daily_volume"] = float(q.turnover)
        except Exception:
            pass  # 数据不可用时使用 admission 的默认值
        gate_result = self.admission.check(symbol, name, gate_ctx)
        result.gate_status = gate_result.status.value
        if gate_result.status.value == "REJECTED":
            result.passed = False
            result.blocked_by = gate_result.flags
            step_done("⛔", "被拦截: " + ", ".join(gate_result.flags[:3]))
            return result
        step_done("✅", "通过")
        _wf[1] = "🚪准入✅"

        # ---- Phase 2.5: 宏观事件因果链分析 ----
        step_start(4, "增强上下文 (宏观/北向/盈利修正/反操纵)")
        # 美股隔夜大盘快照提前获取，供宏观事件传导链使用
        us_overnight = self.data.get_us_overnight()
        if macro_event_desc:
            try:
                current_macro = {"us_overnight": us_overnight.to_dict()} if us_overnight else {}
                event_result = self.run_macro_event(
                    event_description=macro_event_desc,
                    category=macro_event_category,
                    stock_symbol=symbol,
                    stock_sector="",  # 由 diagnosis 阶段补充
                    current_macro=current_macro,
                )
                if event_result is not None:
                    result.macro_event = event_result
            except Exception as e:
                logger.debug("Macro event analysis failed: %s", e)

        # ---- Phase 3: 增强上下文 ----
        macro_regime = self._get_macro_regime()
        nb_profile = self._get_northbound_profile()
        bt_profile = self._get_block_trade_profile(symbol)
        earnings_factor = self._get_earnings_revision(symbol)
        topic_adj = self._get_topic_adjustments()

        # Phase 11: 宏观象限前置 — 计算各维度权重调整
        regime_adjustments = None
        if macro_regime is not None:
            try:
                from src.macro.monetary_credit import MonetaryCreditAnalyzer
                mca = MonetaryCreditAnalyzer()
                regime_adjustments = mca.get_regime_adjustments()
            except Exception as e:
                logger.debug("Regime adjustments computation failed: %s", e)

        if macro_regime is None:
            result.data_gaps.append("宏观数据不可用（如 AKShare 社融 SSL 失败）")
            report_source_citations_gap = make_data_gap_citation(
                provider="akshare", field="macro_regime",
                reason="AKShare 社融/货币数据获取失败",
            )
        else:
            report_source_citations_gap = None

        # ---- Phase 5: 估值 + 周期上下文 ----
        fundamental_metrics = self.data.get_fundamental_metrics(symbol, market)
        industry_pe, industry_pb = self.data.get_industry_pe_pb(symbol, market)
        earnings_growth = self.data.get_earnings_growth(symbol, market)
        dividend_yield = self.data.get_dividend_data(symbol)
        cycle_analysis = self._get_cycle_phase(macro_regime)
        valuation_result = self._get_valuation(
            symbol, name,
            fundamental_metrics=fundamental_metrics,
            industry_pe=industry_pe,
            industry_pb=industry_pb,
            earnings_growth=earnings_growth,
            dividend_yield=dividend_yield,
            roe=getattr(fundamental_metrics, "roe", None) if fundamental_metrics else None,
            cycle_analysis=cycle_analysis,
        )

        # ---- V4 妙想增强: 资讯上下文 + 关联关系 ----
        news_context = self._get_news_context(symbol, name)
        related_parties = self._get_related_parties(symbol)
        executive = self._get_executive_context(symbol)

        # 补充 r014 新闻检查 — 新闻数据在此处才可用
        if _detect_major_positive_news(news_context) and ctx.get("rise_5day_pct", 0.0) > 15.0:
            from src.doctrine.rules import MILITARY_RULES
            r014 = next((r for r in MILITARY_RULES if r.id == "r014"), None)
            if r014 is not None and r014.name not in result.warnings:
                result.warnings.append(r014.name)
                logger.info("r014 触发: %s 重大利好 + 5日涨 %.1f%%", symbol, ctx["rise_5day_pct"])

        # 存储多通道资讯上下文到结果
        result.news_context = news_context

        # Phase: 财政政策 + 政策跟踪信号
        fiscal_regime = self._get_fiscal_regime()
        policy_signals = self._get_policy_signals()

        # Phase 3+: 市场状态分类 (RegimeClassifier, 原死代码)
        market_regime_profile = self._get_market_regime(self.data)

        # Phase 3+: 政策→板块传导链 (SectorTransmissionAnalyzer, 原死代码)
        policy_transmission = self._get_policy_transmission(policy_signals)

        # 增强宏观 dict
        enriched_macro = macro or {}
        if fiscal_regime is not None:
            enriched_macro.update({
                "fiscal_deficit_ratio": getattr(fiscal_regime, "deficit_ratio", None),
                "special_bond_quota": getattr(fiscal_regime, "special_bond_quota", None),
                "infra_growth": getattr(fiscal_regime, "infra_growth", None),
            })
        if policy_signals:
            enriched_macro["policy_signals"] = policy_signals
        if macro_regime is not None:
            enriched_macro.update({
                "m1_m2_gap": macro_regime.m1_m2_gap,
                "social_financing_growth": macro_regime.social_financing_growth,
                "dr007": macro_regime.dr007,
                "dr007_position": self._dr007_position(macro_regime.dr007),
                "lpr_direction": self._lpr_direction(macro_regime),
                "sf_trend": "accelerating" if (macro_regime.social_financing_growth or 0) > 6 else "stable",
            })
            result.macro_regime_info = {
                "quadrant": macro_regime.quadrant.value,
                "confidence": macro_regime.confidence,
            }

        # ---- 注入市场状态 + 政策传导 ----
        if market_regime_profile is not None:
            enriched_macro["market_regime"] = getattr(market_regime_profile, "regime", None)
            if hasattr(enriched_macro["market_regime"], "value"):
                enriched_macro["market_regime"] = enriched_macro["market_regime"].value
            enriched_macro["market_regime_confidence"] = getattr(market_regime_profile, "confidence", 0.5)
            enriched_macro["market_volatility"] = getattr(market_regime_profile, "volatility", None)
            enriched_macro["market_trend"] = getattr(market_regime_profile, "ma_signal", "neutral")
            enriched_macro["recommended_exposure"] = getattr(market_regime_profile, "recommended_exposure", 0.6)
        if policy_transmission:
            enriched_macro["policy_transmission"] = policy_transmission

        # ---- 注入美股隔夜大盘快照 ----
        if us_overnight is not None:
            enriched_macro["us_overnight"] = us_overnight.to_dict()
            result.us_overnight = us_overnight.to_dict()
        else:
            result.data_gaps.append("[DATA_GAP] 美股隔夜数据不可用")

        # ---- Phase 3+: 三大根本问题诊断 ----
        try:
            from src.routing.fundamental_diagnosis import FundamentalDiagnosisEngine
            fd_engine = FundamentalDiagnosisEngine(speed_monitor=getattr(self.data, "speed_monitor", None))
            # 构建 index_prices
            index_prices = None
            try:
                idx_df = self.data.get_history("000001", "SH", period="daily")
                if idx_df is not None and not idx_df.empty and "close" in idx_df.columns:
                    index_prices = idx_df["close"].tolist()
            except Exception:
                pass
            # 提取关键词
            policy_keywords: list[str] = []
            if policy_signals:
                for sig in policy_signals:
                    policy_keywords.extend(sig.get("keywords", []))
            fd_report = fd_engine.diagnose(
                macro_regime=macro_regime,
                fiscal_regime=fiscal_regime,
                policy_signals=policy_signals,
                index_prices=index_prices,
                sector_keywords=policy_keywords if policy_keywords else None,
            )
            result.fundamental_diagnosis = fd_report.to_dict()
            # 注入关键字段到 enriched_macro 供下游 diagnosis/verdict 使用
            enriched_macro["q1_classification"] = fd_report.q1.classification
            enriched_macro["q1_primary_driver"] = fd_report.q1.primary_driver
            enriched_macro["q2_dominant_player"] = fd_report.q2.dominant_player
            enriched_macro["q2_marginal_ranking"] = fd_report.q2.marginal_pricer_ranking
            enriched_macro["q3_info_advantage"] = fd_report.q3.information_advantage_score
        except Exception as e:
            logger.debug("Fundamental diagnosis unavailable: %s", e)

        # Phase 5: 周期 + 估值信息
        if cycle_analysis is not None:
            result.cycle_info = {
                "phase": getattr(cycle_analysis, "phase", None),
                "phase_str": getattr(cycle_analysis.phase, "value", str(getattr(cycle_analysis, "phase", ""))) if hasattr(cycle_analysis, "phase") else "",
                "confidence": getattr(cycle_analysis, "confidence", 0.7),
                "cycle_score": getattr(cycle_analysis, "cycle_score", 50.0),
            }
        if valuation_result is not None:
            result.valuation_info = {
                "composite_score": getattr(valuation_result, "composite_score", 50.0),
                "phase": getattr(valuation_result, "phase", None),
                "phase_str": getattr(getattr(valuation_result, "phase", None), "value", "") if getattr(valuation_result, "phase", None) else "",
            }

        # Phase 4: Alpha Lens — 计算 Alpha Profile
        alpha_profile = self._get_alpha_profile(symbol, name, news_context, as_of_date=as_of_date)
        result.alpha_profile = alpha_profile

        # Phase 11: 存储宏观象限调整信息
        if regime_adjustments is not None:
            result.regime_adjustments_info = {
                "quadrant": getattr(regime_adjustments, "quadrant", None),
                "style_preference": getattr(regime_adjustments, "style_preference", ""),
                "aggressiveness": getattr(regime_adjustments, "aggressiveness", 0.5),
                "position_cap": getattr(regime_adjustments, "position_cap", 0.20),
            }

        # Phase 11: 反操纵扫描 — 筹码 + 日级操纵 + 资金背离 + 多波洗盘生命周期
        manipulation_scan = None
        _wash_daily_bars: list | None = None
        try:
            from src.game_theory.chip_concentration import ChipConcentrationAnalyzer
            from src.game_theory.daily_manipulation import DailyManipulationDetector
            from src.game_theory.capital_flow import CapitalFlowAnalyzer
            from src.game_theory.manipulation import WashoutDetector

            # 筹码集中度
            chip_analyzer = ChipConcentrationAnalyzer()
            chip_result = chip_analyzer.analyze_from_context(symbol, {
                "shareholder_count": getattr(fundamental_metrics, "shareholder_count", None) if fundamental_metrics else None,
                "top10_holding_pct": getattr(fundamental_metrics, "top10_holding_pct", 0.0) if fundamental_metrics else 0.0,
                "top10_float_holding_pct": getattr(fundamental_metrics, "top10_float_holding_pct", 0.0) if fundamental_metrics else 0.0,
            })

            # 资金流分析
            flow_data = self.data.get_money_flow(symbol)
            flow_analyzer = CapitalFlowAnalyzer()
            flow_result = flow_analyzer.analyze(
                symbol=symbol,
                super_large_net=getattr(flow_data, "super_large_net", 0.0) or 0.0,
                large_net=getattr(flow_data, "large_net", 0.0) or 0.0,
                medium_net=getattr(flow_data, "medium_net", 0.0) or 0.0,
                small_net=getattr(flow_data, "small_net", 0.0) or 0.0,
                total_turnover=getattr(flow_data, "total_turnover", 0.0) or 0.0,
                main_consecutive_days=getattr(flow_data, "main_consecutive_days", 0) or 0,
                recent_price_trend=getattr(flow_data, "recent_price_trend", "neutral") or "neutral",
                price_change_pct=(quote.change_pct if quote else 0.0) / 100.0,
            )

            # 日级操纵检测
            daily_detector = DailyManipulationDetector()
            daily_bars = self.data.get_daily_bars(symbol, market, count=40) if hasattr(self.data, 'get_daily_bars') else None
            _wash_daily_bars = daily_bars
            daily_result = daily_detector.detect(
                symbol=symbol,
                daily_bars=daily_bars,
                shareholder_change_pct=getattr(chip_result, "shareholder_change_pct", 0.0),
            )

            # 多波洗盘生命周期（强制；融券压力稍后注入）
            washout_result = None
            if daily_bars and len(daily_bars) >= 8:
                washout_result = WashoutDetector().detect_daily(
                    symbol, daily_bars, name=name, include_wash_cycle=True,
                )

            # 综合操纵扫描结果
            from dataclasses import dataclass
            @dataclass
            class _ManipulationScan:
                chip_risk: float = 0.0
                daily_pattern: str = ""
                pattern_confidence: float = 0.0
                capital_divergence: float = 0.0
                overall_risk: float = 0.0
                recommendations: list = field(default_factory=list)
                is_repeat_offender: bool = False
                sentiment_nexus: list = field(default_factory=list)
                washout_risk: float = 0.0
                wash_cycle: object = None

            # 综合风险 = max(筹码, 日级操纵, 资金背离, 洗盘形态)
            washout_risk = float(getattr(washout_result, "washout_risk_score", 0) or 0)
            overall = max(
                chip_result.manipulation_risk_score,
                daily_result.risk_score,
                flow_result.manipulation_risk_score,
                washout_risk,
            )
            all_recs = (
                chip_result.recommendations
                + daily_result.recommendations
                + flow_result.recommendations
            )
            wc = getattr(washout_result, "wash_cycle", None) if washout_result else None
            if wc is not None and getattr(wc, "retail_action_hint", ""):
                all_recs = list(all_recs) + [wc.retail_action_hint]
            manipulation_scan = _ManipulationScan(
                chip_risk=chip_result.manipulation_risk_score,
                daily_pattern=daily_result.pattern_label,
                pattern_confidence=daily_result.confidence,
                capital_divergence=flow_result.divergence_score,
                overall_risk=overall,
                recommendations=all_recs,
                washout_risk=washout_risk,
                wash_cycle=wc,
            )
        except Exception as e:
            logger.debug("Anti-manipulation scan failed: %s", e)

        # P5: 记录操纵事件到历史数据库
        if manipulation_scan is not None and manipulation_scan.overall_risk > 20:
            try:
                log_manipulation_event(
                    self._manip_history, symbol, name,
                    manipulation_type=manipulation_scan.daily_pattern or "unknown",
                    source="daily" if manipulation_scan.daily_pattern else "unknown",
                    confidence=manipulation_scan.pattern_confidence,
                    risk_score=manipulation_scan.overall_risk,
                    price=quote.price if quote else 0.0,
                )
            except Exception:
                pass

        # P5: 查询是否为惯犯
        is_repeat = False
        try:
            is_repeat = self._manip_history.is_repeat_offender(symbol)
        except Exception:
            pass

        # P6: 情绪-操纵联动 — 调整操纵信号置信度
        sentiment_adjusted = None
        try:
            from src.sentiment.signals import SentimentDetector
            sent = SentimentDetector()
            market_sent = sent.get_snapshot()
            if market_sent and manipulation_scan and manipulation_scan.pattern_confidence > 0:
                nexus_ctx = self._sentiment_nexus.analyze(
                    sentiment_level=market_sent.level.value if hasattr(market_sent.level, 'value') else str(market_sent.level),
                    sentiment_score=market_sent.score,
                    manipulation_signals=[{
                        "playbook_id": manipulation_scan.daily_pattern,
                        "playbook_name": manipulation_scan.daily_pattern,
                        "confidence": manipulation_scan.pattern_confidence,
                        "risk_level": "medium" if manipulation_scan.overall_risk > 30 else "low",
                    }],
                    panic_signals=market_sent.panic_signals,
                    greed_signals=market_sent.greed_signals,
                )
                sentiment_adjusted = nexus_ctx
        except Exception:
            pass

        # 更新 manipulation_scan 附加字段
        if manipulation_scan is not None:
            manipulation_scan.is_repeat_offender = is_repeat
            manipulation_scan.sentiment_nexus = (sentiment_adjusted.nexus_patterns if sentiment_adjusted else [])

        # 存储操纵扫描结果（wash_cycle 将在融资数据就绪后二次注入融券压力）
        if manipulation_scan is not None:
            result.manipulation_info = {
                "overall_risk": manipulation_scan.overall_risk,
                "chip_risk": manipulation_scan.chip_risk,
                "daily_pattern": manipulation_scan.daily_pattern,
                "pattern_confidence": manipulation_scan.pattern_confidence,
                "capital_divergence": manipulation_scan.capital_divergence,
                "recommendations": manipulation_scan.recommendations,
                "washout_risk": getattr(manipulation_scan, "washout_risk", 0.0),
            }
            wc0 = getattr(manipulation_scan, "wash_cycle", None)
            if wc0 is not None and hasattr(wc0, "to_info_dict"):
                result.manipulation_info["wash_cycle"] = wc0.to_info_dict()
        ctx_detail = f"宏观{macro_regime.quadrant.value if macro_regime else '?'}  "
        if manipulation_scan and manipulation_scan.overall_risk > 20:
            ctx_detail += f"操纵⚠️{manipulation_scan.overall_risk:.0f}"
        else:
            ctx_detail += "操纵✅"
        wc0 = getattr(manipulation_scan, "wash_cycle", None) if manipulation_scan else None
        if wc0 is not None and getattr(wc0, "phase", None) is not None:
            from src.game_theory.manipulation.wash_cycle import WashCyclePhase
            if wc0.phase != WashCyclePhase.QUIET:
                ctx_detail += f" 洗盘:{wc0.phase.value}"
        step_done("✅", ctx_detail.strip())
        _wf[2] = "🌐增强上下文✅"

        # ── 融资融券 + Monitor Event 检查 (v2.0) ─────────────────
        margin_profile = None
        margin_alerts = []
        monitor_signals = []
        try:
            from src.game_theory.margin import get_margin_analyzer
            from src.monitor import MonitorStore, MonitorSignalGenerator

            margin_analyzer = get_margin_analyzer()
            margin_profile = margin_analyzer.analyze(
                symbol, name, close_price=quote.price,
            )
            margin_alerts = margin_analyzer.get_alerts(
                symbol, name, close_price=quote.price,
            )

            # 检查已有 Monitor Events
            monitor_store = MonitorStore()
            monitor_gen = MonitorSignalGenerator(monitor_store)
            monitor_signals = monitor_gen.generate(symbol)

            if margin_alerts:
                alert_msgs = [a.message[:60] for a in margin_alerts]
                info(f"💰 融资: {margin_profile.margin_balance:.1f}亿 | "
                     f"趋势: {margin_profile.margin_balance_trend} | "
                     f"5日: {margin_profile.margin_balance_5d_change_pct:+.1f}% | "
                     f"连续流出: {margin_profile.consecutive_outflow_days}天")
                short_chg = getattr(margin_profile, "short_balance_5d_change_pct", None)
                if short_chg is not None:
                    info(
                        f"📉 融券余额: {margin_profile.short_balance or 0:.3f}亿 | "
                        f"5日: {short_chg:+.1f}%"
                    )
                for a in margin_alerts:
                    icon = "🔴" if a.severity == "high" else "🟡"
                    warn(f"{icon} {a.alert_type}: {a.message[:80]}")

            if monitor_signals:
                triggered = [s for s in monitor_signals if s.direction != "neutral"]
                active = [s for s in monitor_signals if s.direction == "neutral"]
                if triggered:
                    info(f"📡 Monitor Events: {len(triggered)}个已触发 | {len(active)}个观测中")
            else:
                info("📡 Monitor Events: 无活跃监控")
        except Exception as e:
            logger.debug("Margin/Monitor check skipped: %s", e)

        # 融券→洗盘生命周期二次注入（视频：借券砸盘提升置信度）
        if _wash_daily_bars and len(_wash_daily_bars) >= 8:
            try:
                from src.game_theory.manipulation import WashoutDetector
                short_chg = (
                    getattr(margin_profile, "short_balance_5d_change_pct", None)
                    if margin_profile is not None else None
                )
                short_bal = (
                    getattr(margin_profile, "short_balance", None)
                    if margin_profile is not None else None
                )
                wo = WashoutDetector().detect_daily(
                    symbol,
                    _wash_daily_bars,
                    name=name,
                    include_wash_cycle=True,
                    short_balance_5d_change_pct=short_chg,
                    short_balance=short_bal,
                )
                if result.manipulation_info is None:
                    result.manipulation_info = {}
                result.manipulation_info["washout_risk"] = wo.washout_risk_score
                if wo.wash_cycle is not None and hasattr(wo.wash_cycle, "to_info_dict"):
                    result.manipulation_info["wash_cycle"] = wo.wash_cycle.to_info_dict()
                    # 抬升 overall_risk：活跃多波洗盘
                    from src.game_theory.manipulation.wash_cycle import WashCyclePhase
                    if wo.wash_cycle.phase != WashCyclePhase.QUIET:
                        prev = float(result.manipulation_info.get("overall_risk", 0) or 0)
                        cycle_score = wo.wash_cycle.confidence * 100
                        result.manipulation_info["overall_risk"] = max(prev, cycle_score * 0.85)
                        if wo.wash_cycle.short_pressure_flag:
                            info(
                                f"🌊 洗盘生命周期: {wo.wash_cycle.phase.value} | "
                                f"融券砸盘压力 | conf={wo.wash_cycle.confidence:.0%}"
                            )
                        else:
                            info(
                                f"🌊 洗盘生命周期: {wo.wash_cycle.phase.value} | "
                                f"波次≈{wo.wash_cycle.wave_count} | conf={wo.wash_cycle.confidence:.0%}"
                            )
            except Exception as e:
                logger.debug("Wash cycle short-pressure inject failed: %s", e)

        # Step 3: 多维诊断
        step_start(5, "多维诊断 (宏观/价值/质量/动量/盈利修正/瓶颈/情绪)")
        # 使用真实行情 + 财务数据（8 期以计算同比增速）
        fin_list = [f.model_dump() for f in self.data.get_financials(symbol, market, count=8)]
        # 计算同比增速并注入 financial dict
        fin_list = self._attach_yoy_growth(fin_list)
        sentiment_dict = self._get_sentiment(nb_profile)

        # 注入融资融券 + Monitor 信号到增强上下文
        if margin_profile is not None:
            enriched_macro["margin_profile"] = {
                "balance": margin_profile.margin_balance,
                "trend": margin_profile.margin_balance_trend,
                "change_5d_pct": margin_profile.margin_balance_5d_change_pct,
                "change_20d_pct": margin_profile.margin_balance_20d_change_pct,
                "net_buy": margin_profile.margin_net_buy,
                "short_balance": margin_profile.short_balance,
                "short_balance_5d_change_pct": getattr(
                    margin_profile, "short_balance_5d_change_pct", None
                ),
                "consecutive_outflow_days": margin_profile.consecutive_outflow_days,
                "consecutive_inflow_days": margin_profile.consecutive_inflow_days,
                "signal": margin_profile.margin_signal,
                "sentiment": margin_profile.leverage_sentiment,
                "divergence": margin_profile.divergence_signal,
                "score": margin_profile.score,
                "data_date": margin_profile.data_date,
            }
            enriched_macro["margin_alerts"] = [
                {"type": a.alert_type, "severity": a.severity,
                 "direction": a.direction, "message": a.message}
                for a in margin_alerts
            ]
            enriched_macro["monitor_signals"] = [
                {"name": s.name, "direction": s.direction,
                 "strength": s.strength, "score": s.score,
                 "description": s.description, "metadata": s.metadata}
                for s in monitor_signals
            ]
            result.margin_profile = margin_profile
            result.margin_alerts = margin_alerts
            result.monitor_signals = monitor_signals

        report = self.diagnosis.analyze(
            symbol, name,
            quote_dict, fin_list,
            enriched_macro,
            sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            block_trade_profile=bt_profile,
            earnings_factor=earnings_factor,
            alpha_profile=alpha_profile,  # Phase 4: Alpha Lens 注入
            executive=executive,         # V4: 高管数据注入
            valuation_result=valuation_result,  # Phase 5: 估值结果
            cycle_analysis=cycle_analysis,      # Phase 5: 周期分析
            regime_adjustments=regime_adjustments,     # Phase 11: 宏观象限权重
            manipulation_scan=manipulation_scan,        # Phase 11: 反操纵扫描
        )
        result.report = report
        result.market_sentiment = sentiment_dict
        scores = f"宏观{report.macro_score:.0f} 价值{report.value_score:.0f} 质量{report.quality_score:.0f} 动量{report.momentum_score:.0f}"
        step_done("✅", scores)
        _wf[3] = "📊多维诊断✅"
        if us_overnight is not None:
            print(f"\n  🌙 美股隔夜: {us_overnight.summary}")
        print_diagnosis(report, result.mental_model_info)
        print_admission(result.gate_status, market_sentiment=sentiment_dict, data_gaps=result.data_gaps, red_lines=result.red_lines)
        if report_source_citations_gap:
            report.source_citations.append(report_source_citations_gap)

        # 添加行情双源 citation（mootdx/Tencent + miaoxiang）
        report.source_citations.append(make_citation(
            provider="mootdx", field="quote", data_type="realtime_quote",
            source_tier="T1", nature="fact",
        ))
        if self.data.miaoxiang is not None:
            report.source_citations.append(make_citation(
                provider="miaoxiang", field="quote", data_type="realtime_quote",
                source_tier="T2", nature="fact",
            ))

        # Phase 1: 诊断护栏检查 + Phase 6: 博弈论 + 思维模型
        step_start(6, "博弈论 + 四大师辩论 + Munger模型")
        l1_violations = self.enforcer.enforce(
            stage="diagnosis",
            source_citations=report.source_citations,
            confidence=report.confidence,
        )
        result.violations.extend(l1_violations)

        # Phase 6: 博弈论 + 投资思维模型
        gt_profile = self.gt_analyzer.analyze(
            symbol, name,
            market_cap=quote.market_cap if quote else None,
            sector="",
        )
        imm_fit = self.imm_analyzer.analyze(
            symbol, name,
            investor=investor,
            portfolio=portfolio,
            sector="",
            market_cap=quote.market_cap if quote else None,
            change_pct=quote.change_pct if quote else None,
        )
        report.game_theory_profile = gt_profile
        report.investor_mental_model = imm_fit
        report.source_citations.extend(gt_profile.source_citations + imm_fit.source_citations)
        # 博弈论分析 — 基于模型的博弈推演，属于推测
        report.source_citations.append(make_citation(
            provider="game_theory", field="game_theory_profile",
            data_type="analyst_report",
            source_tier="T3", nature="speculation",
            confidence=0.50,
        ))
        # 投资思维模型 — 基于投资者画像的匹配分析，属于解释
        report.source_citations.append(make_citation(
            provider="imm_analyzer", field="mental_model_fit",
            data_type="analyst_report",
            source_tier="T2", nature="interpretation",
            confidence=0.70,
        ))
        result.game_theory_info = gt_profile.to_dict()
        result.mental_model_info = imm_fit.to_dict()

        # Phase 6+: AI Berkshire — 四视角辩论
        debate = self.perspective_analyzer.debate(
            symbol, name, l1_report=report,
            quote=quote_dict, financials=fin_list,
        )
        report.debate_result = debate
        result.debate_result = {
            "avg_score": debate.avg_score,
            "score_range": debate.score_range,
            "agreement_level": debate.agreement_level,
            "recommendation": debate.recommendation,
            "top_disagreement": debate.top_disagreement,
            "top_agreement": debate.top_agreement,
            "tension_summary": debate.tension_summary,
        }
        # 保存四个视角的详细观点
        result.debate_perspectives = {
            "buffett": _perspective_to_dict(debate.buffett),
            "li_lu": _perspective_to_dict(debate.li_lu),
            "munger": _perspective_to_dict(debate.munger),
            "lynch": _perspective_to_dict(debate.lynch),
        }
        # 四视角辩论 — LLM 多角色推演，属于推测
        report.source_citations.append(make_citation(
            provider="perspective_analyzer", field="four_perspective_debate",
            data_type="analyst_report",
            source_tier="T3", nature="speculation",
            confidence=0.45,
        ))

        # Phase 6+: Munger 思维模型匹配 — 动态上下文驱动
        # 从报告提取行业信息（诊断阶段已注入）
        _sector = getattr(report, "sector", "") or ""
        matched_models = self.mental_model_matcher.match_models(
            symbol, name, sector=_sector, report=report,
            question=macro_event_desc,
            macro_context={"desc": macro_event_desc, "category": macro_event_category} if macro_event_desc else None,
        )
        report.mental_models = matched_models
        result.mental_models = matched_models
        debate_detail = f"分歧{debate.agreement_level}  模型{len(matched_models)}个"
        step_done("✅", debate_detail)
        _wf[4] = "🎭辩论/Munger✅"
        print_debate(result.debate_perspectives, result.debate_result)
        print_munger_models(result.mental_models, name)
        print_alpha_game_theory(result.alpha_profile, result.game_theory_info)
        # Munger 思维模型匹配 — 分析解释
        if matched_models:
            report.source_citations.append(make_citation(
                provider="mental_model_matcher", field="munger_mental_models",
                data_type="analyst_report",
                source_tier="T2", nature="interpretation",
                confidence=0.65,
            ))

        # Phase 9: T+0 日内时机分析（中长期 Alpha 搜索可跳过，不阻塞主流程）
        # 放在综合裁决之前，使日内时机信号能影响裁决判断
        if not skip_t0:
            step_start(7, "T+0 日内时机分析")
            try:
                t0 = self.run_t0(symbol, market, name)
                if t0 is not None:
                    result.t0_result = t0
                    result.t0_available = True
                    t0_score = t0.get("score", 0)
                    t0_action = t0.get("action", "hold")
                    step_done("✅", f"得分{t0_score}  建议{t0_action}")
                    print_t0(t0)
                else:
                    step_done("⚠️", "数据不可用")
            except Exception as e:
                logger.debug("T+0 analysis failed for %s: %s", symbol, e)
                step_done("⚠️", f"失败: {e}")
        else:
            step_start(7, "T+0 日内时机分析")
            step_done("⏭️", "跳过 (Alpha搜索模式)")

        _wf[5] = "⏱️T+0✅"

        # ---- Phase 7 & 8: 行业+公司深度研究 (仅 mode="full") ----
        if mode in ("full", "selection", "deep"):
            self._run_deep_research(symbol, name, result, report, quote_dict, fin_list)

        # CogAlpha: 多 Agent 质量审查 (数据新鲜度/一致性/泄露/可解释性/安全)
        step_start(8, "质量审查 + 综合裁决 + 情景估值")
        quality_report = self.quality_checker.check(report)
        if not quality_report.passed:
            result.warnings.extend(quality_report.blocking_flags)
            logger.warning(
                "Quality check blocked for %s: %s",
                symbol, "; ".join(quality_report.blocking_flags[:3]),
            )
        else:
            logger.info(
                "Quality check passed for %s: %.0f/100", symbol, quality_report.overall_score,
            )
        result.warnings.extend(quality_report.warnings[:5])
        result.quality_report = quality_report.to_dict()

        # Phase 6+: 反偏见 — 红线检查（综合裁决前）
        red_line_report = self.anti_bias_engine.check_red_lines(
            quote=quote_dict, financials=fin_list, executive=executive,
        )
        result.red_lines = red_line_report.triggered_lines
        if red_line_report.any_triggered:
            result.warnings.extend(
                [f"红线 {line}: 触发" for line in red_line_report.triggered_lines]
            )

        # Phase 1+: 信源交叉验证 guard — T1+ 来源不足则阻止进入综合裁决
        t1_plus_count = sum(1 for sc in report.source_citations if getattr(sc, "is_t1_or_above", False))
        if t1_plus_count < 2:
            result.passed = False
            result.blocked_by.append(
                f"信源交叉验证不足：T1+ 来源 < 2 (当前 {t1_plus_count})"
            )
            return result

        # Step 4: 综合裁决
        alpha_mode = "selection" if selection_mode else "trading"
        verdict = self.verdict_engine.judge(
            report, topic_adj=topic_adj, weights_override=weights, mode=alpha_mode,
        )
        result.verdict = verdict
        if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
            result.passed = False
            result.blocked_by.append(f"置信度不足 ({verdict.confidence:.2f} < {VerdictEngine.MIN_CONFIDENCE})")
            return result

        # Phase 1: 裁决护栏检查
        l2_violations = self.enforcer.enforce(
            stage="verdict",
            source_citations=verdict.source_citations,
            confidence=verdict.confidence,
        )
        result.violations.extend(l2_violations)

        # Phase 6+: 强制结论（VerdictEnforcer）
        enforced = self.verdict_enforcer.enforce(
            symbol=symbol, name=name,
            l1_report=report, l2_verdict=verdict, quote=quote_dict,
            data_points=sum(1 for x in [quote, fin_list, enriched_macro, sentiment_dict, nb_profile, earnings_factor] if x),
        )
        result.enforced_verdict = {
            "level": enforced.level.value,
            "one_line_conclusion": enforced.one_line_conclusion,
            "is_abstain": enforced.is_abstain,
            "abstain_reasons": enforced.abstain_reasons,
            "price_range": {
                "current_price": enforced.price_range.current_price,
                "buy_below": enforced.price_range.buy_below,
                "buy_target": enforced.price_range.buy_target,
                "sell_above": enforced.price_range.sell_above,
                "position_pct": enforced.price_range.position_pct,
            },
        }
        if enforced.level.value == "FAIL" or enforced.is_abstain:
            result.passed = False
            result.blocked_by.append(enforced.one_line_conclusion)

        # Phase 6+: 三情景估值
        try:
            from src.valuation.scenario import ScenarioValuation
            pe_ttm_val = quote_dict.get("pe_ttm")
            pb_val = quote_dict.get("pb")
            roe_val = quote_dict.get("roe")
            earnings_growth_val = self.data.get_earnings_growth(symbol, market)
            scenario = ScenarioValuation.from_fundamentals(
                symbol=symbol, name=name,
                current_price=quote.price if quote else quote_dict.get("price", 0),
                pe_ttm=pe_ttm_val,
                pb=pb_val,
                roe=roe_val,
                earnings_growth=earnings_growth_val,
            )
            # 附计算方法说明和输入参数
            scenario_method = "PEG启发式 (合理PE≈盈利增速%)" if (pe_ttm_val and earnings_growth_val and pe_ttm_val > 0 and earnings_growth_val > 0) else (
                "PB-ROE粗略估算 (合理PB≈ROE/10)" if (pb_val and roe_val and pb_val > 0 and roe_val > 0) else "回退: 当前价格=基准")
            result.scenario_valuation = {
                "bull_target": scenario.bull_target,
                "base_target": scenario.base_target,
                "bear_target": scenario.bear_target,
                "implied_upside": scenario.implied_upside,
                "implied_downside": scenario.implied_downside,
                "method": scenario_method,
                "inputs": {
                    "current_price": float(quote.price) if quote else float(quote_dict.get("price", 0)),
                    "pe_ttm": pe_ttm_val,
                    "pb": pb_val,
                    "roe": roe_val,
                    "earnings_growth": earnings_growth_val,
                },
                "bull_formula": "基准 × 1.20 (乐观溢价20%)",
                "bear_formula": "基准 × 0.75 (悲观折价25%)",
                # 注明这是推测性计算
                "nature": "speculation",
                "source_tier": "T3",
            }
            # 三情景估值 citation
            report.source_citations.append(make_citation(
                provider="valuation_scenario", field="scenario_valuation",
                data_type="analyst_report",
                source_tier="T3", nature="speculation",
                confidence=0.40,
            ))
        except Exception as e:
            logger.debug("Scenario valuation failed for %s: %s", symbol, e)

        # Step 5: 置信门控 (pipeline.ConfidenceGate)
        try:
            from src.pipeline import ConfidenceGate
            for citation in getattr(verdict, "source_citations", []) or []:
                ConfidenceGate.check(citation, context=f"verdict:{symbol}")
        except Exception:
            pass  # 门控失败不阻塞管道
        verdict_detail = f"评分{verdict.score:.0f}/100  置信度{verdict.confidence:.0%}  {verdict.recommendation}"
        if quality_report and not quality_report.passed:
            verdict_detail += f"  ⚠️质量{quality_report.overall_score:.0f}"
        step_done("✅", verdict_detail)
        _wf[6] = "⚖️裁决✅"
        print_verdict(verdict, result.enforced_verdict, result.scenario_valuation)

        # Step 6: 仓位调度
        step_start(9, "仓位调度 + 风控执行")
        effective_macro_cap = 0.80 * risk_mult
        # Phase 11: 使用宏观象限调整后的仓位上限
        if regime_adjustments is not None:
            effective_macro_cap = getattr(regime_adjustments, "max_total_position", effective_macro_cap)
        # P4: 使用 ManipulationSizingEngine 计算精细化仓位调整
        sizing_result = None
        try:
            sizing_result = self._manipulation_sizer.calc(
                manipulation_risk=manipulation_scan.overall_risk if manipulation_scan else 0.0,
                manipulation_pattern=manipulation_scan.daily_pattern if manipulation_scan else "",
                chip_concentration=manipulation_scan.chip_risk if manipulation_scan else 0.0,
                fund_divergence=manipulation_scan.capital_divergence if manipulation_scan else 0.0,
                is_repeat_offender=is_repeat,
                base_kelly_f=0.0,
                base_position_cap=effective_macro_cap,
            )
        except Exception:
            sizing_result = None

        # P4: 使用 ManipulationSizingEngine 调整后的仓位上限
        _adj_manip_cap = getattr(manipulation_scan, "overall_risk", 0.0) if manipulation_scan else 0.0
        if sizing_result is not None:
            _adj_manip_cap = sizing_result.position_cap or (effective_macro_cap * sizing_result.kelly_discount)

        signal = self.positioning.generate_signal(
            verdict,
            macro_cap=effective_macro_cap,
            position_limits=position_limits,
            risk_multiplier=risk_mult,
            name=name,
            extra=quote.dict() if quote else {},
            manipulation_risk=_adj_manip_cap,
        )
        result.signal = signal
        # 保存仓位计算详情供格式化器使用
        result.sizing_detail = {
            "method": getattr(signal, "sizing_method", "unknown"),
            "kelly_f": getattr(signal, "kelly_f", 0.0),
            "params_source": getattr(signal, "kelly_params_source", ""),
            "macro_cap": effective_macro_cap,
            "risk_multiplier": risk_mult,
        }

        # Phase 1: 仓位调度护栏检查
        l3_violations = self.enforcer.enforce(
            stage="positioning",
            source_citations=signal.source_citations,
            confidence=signal.confidence,
        )
        result.violations.extend(l3_violations)
        if self.enforcer.is_blocked(l3_violations):
            result.passed = False
            result.blocked_by.extend(self.enforcer.get_warnings(l3_violations))

        # Step 6: 风控执行
        enriched_portfolio = (portfolio or {}).copy()
        if related_parties:
            enriched_portfolio["related_parties"] = related_parties  # V4: 关联关系风险
        # Phase 4: Alpha 衰减追踪注入
        if alpha_profile:
            enriched_portfolio["alpha_tracker"] = {
                "decay_velocity": alpha_profile.decay_rate,
                "days_since_detection": alpha_profile.days_since_detection,
                "is_crowded": (
                    alpha_profile.decay_status.value == "crowded"
                    or alpha_profile.narrative.crowded_signal_score >= 60
                ),
                "narrative_stage": alpha_profile.narrative.stage.value,
            }
        # Phase 6: 博弈论风险注入风控执行
        if gt_profile:
            enriched_portfolio["game_theory_risks"] = gt_profile.risks
            enriched_portfolio["dominant_player"] = gt_profile.dominant_player
            enriched_portfolio["market_regime"] = gt_profile.market_regime
        if imm_fit:
            enriched_portfolio["mental_model_bias_flags"] = imm_fit.bias_flags
            enriched_portfolio["mental_model_warnings"] = imm_fit.warnings
        # Phase 11: 操纵信号注入风控 — 用于操纵感知止损
        if manipulation_scan is not None:
            enriched_portfolio["manipulation_risk_score"] = manipulation_scan.overall_risk
            enriched_portfolio["manipulation_pattern"] = manipulation_scan.daily_pattern
        if sizing_result is not None:
            enriched_portfolio["manipulation_stop_strategy"] = {
                "type": sizing_result.stop_strategy.stop_type if sizing_result.stop_strategy else "normal",
                "stop_loss_pct": sizing_result.stop_strategy.stop_loss_pct if sizing_result.stop_strategy else -0.02,
                "urgency": sizing_result.stop_strategy.urgency if sizing_result.stop_strategy else "normal",
            }
            enriched_portfolio["manipulation_entry_rec"] = sizing_result.entry_recommendation

        # Phase 12: 注入持仓 HWM → 风控移动止损获得真实峰值
        existing_pos = self.position_state_mgr.get(symbol)
        if existing_pos is not None:
            if "peak_price" not in enriched_portfolio or enriched_portfolio.get("peak_price", 0) == 0:
                enriched_portfolio["peak_price"] = existing_pos.high_price
            else:
                enriched_portfolio["peak_price"] = max(
                    enriched_portfolio.get("peak_price", 0),
                    existing_pos.high_price,
                )
            if "current_price" not in enriched_portfolio:
                enriched_portfolio["current_price"] = existing_pos.last_price
            enriched_portfolio["holding_days"] = max(
                enriched_portfolio.get("holding_days", 0) or 0,
                (datetime.now() - existing_pos.entry_date).days if existing_pos.entry_date else 0,
            )
            enriched_portfolio["position_state"] = existing_pos  # 完整状态供下游使用

        # Phase 8: 观测权益更新 HWM / 自动熔断
        eq = (enriched_portfolio or {}).get("total_equity", 0)
        if eq > 0:
            self.risk_ctrl.update_equity(float(eq))

        risk = self.risk_ctrl.check(signal, enriched_portfolio, position_limits=position_limits)
        result.risk = risk

        # Phase 1: 风控护栏检查
        l4_violations = self.enforcer.enforce(
            stage="risk_control",
            source_citations=risk.source_citations,
        )
        result.violations.extend(l4_violations)

        result.passed = True
        sizing_detail = f"目标{signal.target_weight:.1%}  调整后{risk.adjusted_weight:.1%}"
        if risk.violations:
            sizing_detail += f"  ⚠️违规{len(risk.violations)}"
        step_done("✅" if risk.passed else "⚠️", sizing_detail)
        _wf[7] = "💰调度/🛡️风控✅"
        print_positioning(signal, result.sizing_detail, result.position_limits_summary)
        print_risk_control(risk, result.position_limits_summary)

        # Phase 12: 持仓价格追踪（仅更新已有持仓的 HWM/止损预警，不自动开仓/平仓）
        # 实际交易由用户执行，之后通过场景五同步到系统。分析信号仅作参考建议。
        if signal is not None and result.passed:
            current_px = float(quote_dict.get("price", 0) or quote_dict.get("close", 0) or 0)
            try:
                if self.position_state_mgr.is_open(symbol):
                    # 已有持仓 → 更新价格追踪（HWM / 止损预警）
                    if current_px > 0:
                        _atr = None
                        if signal.atr_stop > 0 and current_px > 0:
                            _atr = (current_px - signal.atr_stop) / 2.0
                        _, alerts = self.position_state_mgr.update_price(symbol, current_px, atr_value=_atr)
                        for alert in alerts:
                            logger.info(
                                "持仓预警 [%s] %s: %s", alert.severity, alert.symbol, alert.message,
                            )
                # 注意: 不再根据分析信号自动 open()/close() 持仓。
                # 开仓/平仓由用户在真实交易后通过场景五同步到 data/positions.json。
            except Exception as e:
                logger.debug("Phase 12 position state update failed for %s: %s", symbol, e)
        step_start(10, "数据溯源 + 最终输出")
        step_done("✅", f"来源{len(report.source_citations)}条")
        _wf[8] = "📊溯源✅"

        # ── Monitor Event 创建/更新 (v2.0) ──────────────────────
        if margin_alerts:
            try:
                from src.monitor import MonitorStore, MonitorEvent as MEvent
                ms = MonitorStore()
                created = 0
                for a in margin_alerts:
                    # 检查是否已有同名 active monitor，避免重复创建
                    existing_active = ms.get_active_for_symbol(symbol)
                    dup = any(
                        e.metadata.get("alert_type") == a.alert_type
                        for e in existing_active
                    )
                    if not dup:
                        me = MEvent.from_margin_alert(
                            code=symbol, name=name,
                            alert_type=a.alert_type,
                            message=a.message,
                            direction=a.direction,
                            severity=a.severity,
                            parent_analysis=f"analyze_{symbol}_{datetime.now().strftime('%Y%m%d')}",
                        )
                        # 设置合理的过期时间 (根据类型)
                        if a.alert_type in ("balance_drop", "price_margin_divergence"):
                            me.expires_at = (datetime.now() + timedelta(days=5)).isoformat()
                        else:
                            me.expires_at = (datetime.now() + timedelta(days=10)).isoformat()
                        ms.append(me)
                        created += 1
                if created:
                    info(f"📡 创建 {created} 条 Monitor Event (融资监控)")
                # 检查并关闭已触发的
                for e in ms.get_active_for_symbol(symbol):
                    # 检查是否应触发: 例如连续流出天数达到条件
                    if e.metadata.get("alert_type") == "consecutive_outflow":
                        if margin_profile and margin_profile.consecutive_outflow_days >= 5:
                            ms.close_monitor(
                                e.event_id,
                                result=f"已触发: 融资连续{margin_profile.consecutive_outflow_days}天净流出, "
                                       f"5日变化{margin_profile.margin_balance_5d_change_pct:+.1f}%",
                                direction="bearish", severity="medium",
                            )
                    elif e.metadata.get("alert_type") == "price_margin_divergence":
                        if margin_profile and margin_profile.divergence_signal != "none":
                            ms.close_monitor(
                                e.event_id,
                                result=f"已触发: {margin_profile.divergence_signal}",
                                direction="bearish", severity="high",
                            )
            except Exception as e:
                logger.debug("Monitor Event creation failed: %s", e)

        print_source_citations(report, result.verdict)
        # 🔔 多通道资讯输出
        if result.news_context:
            print_news_context(result.news_context)
        # 深度研究输出 (仅 mode="full")
        if mode in ("full", "selection", "deep"):
            print_deep_research(result.sector_research, result.company_deep_research, name)

        # 保存完整 Markdown 报告
        try:
            report_path = save_markdown_report(result)
            print(f"\n  📝 完整报告: {report_path}")
        except Exception:
            pass

        msg_parts = []
        for m in (result.mental_models or [])[:3]:
            msg_parts.append(m.get('name_cn', '')[:12])
        model_tags = ", ".join(msg_parts) if msg_parts else "-"
        print(f"\n  📊 {'='*56}")
        print(f"  📊 分析完成: {name}({symbol})")
        if result.verdict:
            rec_emoji = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴"}.get(result.verdict.recommendation, "⚪")
            print(f"  📊 {rec_emoji} {result.verdict.recommendation}  评分{result.verdict.score:.0f}/100  置信度{result.verdict.confidence:.0%}")
        print(f"  📊 Munger: {model_tags}")
        print(f"  📊 {'='*56}")

        return result

    # ------------------------------------------------------------------
    # Phase 7 & 8: Deep Research (mode="full")
    # ------------------------------------------------------------------

    def _run_deep_research(
        self,
        symbol: str,
        name: str,
        result: OrchestratorResult,
        report,
        quote_dict: dict,
        fin_list: list,
    ) -> None:
        """运行行业深度研究 + 公司深度研究。

        所有异常静默处理，不阻断主流程。
        """
        self._init_deep_research_engines()

        # 提取上下文数据
        current_pe = quote_dict.get("pe") if quote_dict else None
        current_price = quote_dict.get("price", 0) or quote_dict.get("close", 0) if quote_dict else 0

        # ---- Phase 7: 行业深度研究 ----
        sector_data = {}
        try:
            sector_data = self._run_sector_research(symbol, name, current_pe)
            result.sector_research = sector_data
            report.source_citations.append(make_citation(
                provider="sector_research", field="industry_deep",
                data_type="analyst_report",
                source_tier="T2", nature="interpretation", confidence=0.65,
            ))
        except Exception as exc:
            logger.debug("Sector research failed for %s: %s", symbol, exc)
            result.data_gaps.append("[DATA_GAP] 行业深度研究不可用")

        # ---- Phase 8: 公司深度研究 ----
        company_data = {}
        try:
            company_data = self._run_company_deep_research(
                symbol, name, current_price, fin_list
            )
            result.company_deep_research = company_data
            report.source_citations.append(make_citation(
                provider="company_deep_research", field="company_deep",
                data_type="analyst_report",
                source_tier="T2", nature="interpretation", confidence=0.60,
            ))
        except Exception as exc:
            logger.debug("Company deep research failed for %s: %s", symbol, exc)
            result.data_gaps.append("[DATA_GAP] 公司深度研究不可用")

    def _run_sector_research(self, symbol: str, name: str, current_pe=None) -> dict:
        """Phase 7: 行业深度研究 (6+1 步 Workflow)。"""
        if not self._sector_classifier:
            return {}

        validator = self._sector_validator
        data_gaps: list[str] = []
        sector_class = self._sector_classifier.classify(symbol, name)
        sector_name = sector_class.sw1_name
        if sector_name == "未分类":
            return {"sector_name": "未分类", "message": "行业分类数据不可用"}

        # Step 1: 行业定位 ✅
        # Step 2: 市场规模 (TAM/CAGR/CR5)
        tam = self._estimate_tam_for_sector(sector_name)

        # Step 3: 竞争格局
        competition = self._competition_analyzer.analyze(sector_name)

        # Step 4: 估值背景
        valuation_fw = self._sector_valuation.valuate(sector_name, current_pe)

        # Step 5: 催化剂 — 从 research.py 复用（避免重复定义）
        catalysts, catalyst_score = self._get_catalysts_for_sector(sector_name)
        policy_impact, policy_notes = self._get_policy_for_sector(sector_name)

        # Step 6: 供应链瓶颈
        supply_chain = self._supply_chain_mapper.analyze(symbol)
        upstream = self._supply_chain_mapper.find_upstream(symbol)
        downstream = self._supply_chain_mapper.find_downstream(symbol)
        supply_chain["upstream_tickers"] = upstream[:10]
        supply_chain["downstream_tickers"] = downstream[:10]

        # Step 7: 全球供需平衡 (门控)
        from src.industry.global_commodity import is_global_commodity_industry
        global_data = {}
        is_global = is_global_commodity_industry(sector_name)
        if is_global and self._global_commodity_analyzer:
            try:
                global_data = self._global_commodity_analyzer.analyze(sector_name)
            except Exception as exc:
                logger.debug("Global commodity analysis failed: %s", exc)
                data_gaps.append("[DATA_GAP] 全球供需分析失败")

        # Workflow 验证
        if validator:
            step_args = (
                ("step1", "行业定位", "T1", 24, 0.85),
                ("step2", "市场规模", tam.get("source_tier", "T2"), 24, tam.get("confidence", 0.55)),
                ("step3", "竞争格局", "T2", 168, 0.65),
                ("step4", "估值背景", "T1" if current_pe else "T2", 1 if current_pe else 24, 0.75 if current_pe else 0.65),
                ("step5", "催化剂", "T2", 12, 0.60),
                ("step6", "供应链瓶颈", "T2", 168, 0.70),
            )
            for step_id, step_name, tier, freshness, conf in step_args:
                # 构造临时 report-like 对象用于标记
                pass  # 这里用 validate_dict 更合适
            # 用 validate_dict 检查
            result_dict = {
                "sector_name": sector_name,
                "tam_estimate": tam,
                "competition": competition,
                "valuation": valuation_fw,
                "supply_chain": supply_chain,
                "catalysts": catalysts,
                "catalyst_score": catalyst_score,
                "policy_impact": policy_impact,
                "policy_notes": policy_notes,
                "data_gaps": data_gaps,
                "confidence": 0.65,
            }
            if is_global and global_data:
                result_dict["global_commodity"] = global_data
            passed, missing = validator.validate_dict(result_dict, is_global=is_global)
            if missing:
                result_dict.setdefault("data_gaps", []).extend(
                    [f"[WORKFLOW_GAP] 步骤未完成: {m}" for m in missing]
                )
        else:
            result_dict = {
                "sector_name": sector_name,
                "confidence": 0.65,
                "data_gaps": data_gaps,
            }

        return {
            "sector_name": sector_name,
            "sw2_name": sector_class.sw2_name,
            "benchmark_index": sector_class.benchmark_index,
            "tam_estimate": tam,
            "competition": {
                "cr5": competition.cr5,
                "hhi": competition.hhi,
                "concentration": competition.concentration_label,
                "barrier": competition.entry_barrier.value,
                "barrier_factors": competition.barrier_factors[:3],
                "intensity": round(competition.competition_intensity, 1),
                "moat_potential": round(competition.moat_potential, 1),
            },
            "valuation": {
                "primary_method": valuation_fw.primary_method.value,
                "secondary_methods": [m.value for m in valuation_fw.secondary_methods],
                "pe_median": valuation_fw.historical_pe_median,
                "pe_p25": valuation_fw.historical_pe_p25,
                "pe_p75": valuation_fw.historical_pe_p75,
                "pe_percentile": round(valuation_fw.current_pe_percentile, 1),
                "attractiveness": round(valuation_fw.valuation_score, 1),
            },
            "supply_chain": supply_chain,
            "catalysts": catalysts,
            "catalyst_score": catalyst_score,
            "policy_impact": policy_impact,
            "policy_notes": policy_notes,
            "global_commodity": global_data if is_global else {"enabled": False},
            "confidence": result_dict.get("confidence", 0.65),
            "data_gaps": result_dict.get("data_gaps", data_gaps),
        }

        # ── 自动因子提取 + stock_impact 注入 ──
        try:
            from src.industry.factor_extractor import FactorExtractor
            fe = FactorExtractor()
            # 组装 market_data (从上下文获取)
            mkt = {}
            # 将 news/market 数据补充到 extraction
            impact = fe.analyze(
                sector_name=sector_name,
                stock_name=name,
                sector_data=sector_data,
                market_data=mkt if mkt else None,
            )
            if sector_data.get("global_commodity") and isinstance(sector_data["global_commodity"], dict):
                sector_data["global_commodity"]["_stock_impact"] = impact
            else:
                sector_data["global_commodity"] = {"enabled": False, "_stock_impact": impact}
        except Exception as exc:
            logger.debug("Factor extraction failed for %s: %s", symbol, exc)

    @staticmethod
    def _estimate_tam_for_sector(sector_name: str) -> dict:
        """估算行业市场规模 (T2 级别)。"""
        tam_map = {
            "有色金属": {"tam_yi": 28000, "cagr_3y": 15.0, "cr5": 22.0, "cr10": 38.0},
            "食品饮料": {"tam_yi": 52000, "cagr_3y": 8.0, "cr5": 35.0, "cr10": 55.0},
            "电子": {"tam_yi": 65000, "cagr_3y": 18.0, "cr5": 15.0, "cr10": 28.0},
            "电力设备": {"tam_yi": 45000, "cagr_3y": 22.0, "cr5": 18.0, "cr10": 32.0},
            "医药生物": {"tam_yi": 38000, "cagr_3y": 5.0, "cr5": 8.0, "cr10": 15.0},
            "汽车": {"tam_yi": 35000, "cagr_3y": 15.0, "cr5": 35.0, "cr10": 55.0},
            "银行": {"tam_yi": 100000, "cagr_3y": 3.0, "cr5": 42.0, "cr10": 68.0},
            "计算机": {"tam_yi": 28000, "cagr_3y": 12.0, "cr5": 10.0, "cr10": 20.0},
            "国防军工": {"tam_yi": 22000, "cagr_3y": 10.0, "cr5": 25.0, "cr10": 42.0},
            "煤炭": {"tam_yi": 15000, "cagr_3y": -2.0, "cr5": 28.0, "cr10": 50.0},
            "基础化工": {"tam_yi": 32000, "cagr_3y": 8.0, "cr5": 12.0, "cr10": 25.0},
            "石油石化": {"tam_yi": 28000, "cagr_3y": 5.0, "cr5": 55.0, "cr10": 78.0},
            "钢铁": {"tam_yi": 12000, "cagr_3y": -3.0, "cr5": 25.0, "cr10": 42.0},
        }
        data = tam_map.get(sector_name, {"tam_yi": 20000, "cagr_3y": 5.0, "cr5": 15.0, "cr10": 30.0})
        data["source_tier"] = "T2"
        data["confidence"] = 0.55
        return data

    @staticmethod
    def _get_catalysts_for_sector(sector_name: str) -> tuple[list[str], float]:
        """行业催化剂评估。"""
        catalyst_map = {
            "电子": (["AI 需求爆发", "国产替代加速", "消费电子复苏"], 75),
            "电力设备": (["新能源装机超预期", "海外电网更新周期", "储能政策加码"], 70),
            "有色金属": (["新能源金属需求", "供给约束", "全球通胀交易"], 55),
            "煤炭": (["供给收缩", "火电调峰需求", "高股息"], 40),
            "汽车": (["智能驾驶渗透", "出海加速", "换车周期"], 65),
            "计算机": (["AI 应用落地", "信创加速", "数据要素政策"], 70),
        }
        return catalyst_map.get(sector_name, (["行业自身发展逻辑"], 50))

    @staticmethod
    def _get_policy_for_sector(sector_name: str) -> tuple[float, list[str]]:
        """行业政策影响评估。"""
        policy_map = {
            "电力设备": (60, ["双碳政策持续加码", "新能源补贴", "电网投资加大"]),
            "电子": (50, ["大基金三期", "国产替代政策", "税收优惠"]),
            "有色金属": (10, ["新能源金属战略支持", "矿业权审批趋严"]),
            "煤炭": (-15, ["双碳约束", "煤矿安全监管趋严"]),
            "医药生物": (-10, ["集采压力", "医保控费"]),
        }
        return policy_map.get(sector_name, (0, ["暂无重大政策影响"]))

    def _run_company_deep_research(
        self, symbol: str, name: str, current_price: float = 0, fin_list: list = None
    ) -> dict:
        """Phase 8: 公司深度研究。"""
        if not self._moat_analyzer:
            return {}

        moat = self._moat_analyzer.analyze(symbol, name)

        # 财务红旗 — 需要财务数据
        red_flags_result = None
        if fin_list and self._red_flag_detector:
            try:
                fin_dict = self._financials_to_dict(fin_list)
                red_flags_result = self._red_flag_detector.detect(symbol, name, fin_dict)
            except Exception:
                pass

        # 管理层
        management = self._management_evaluator.evaluate(symbol, name)

        # 一致预期
        consensus = self._report_aggregator.aggregate(symbol, name)

        # DCF — 尝试从财务数据提取 FCF
        dcf_result = None
        if self._dcf_valuator and fin_list:
            try:
                fcf = self._extract_fcf(fin_list)
                if fcf > 0 and current_price > 0:
                    dcf_result = self._dcf_valuator.valuate(
                        symbol, name, free_cashflow=fcf, current_price=current_price,
                    )
            except Exception:
                pass

        # 综合评分
        overall = self._calc_deep_overall(moat, red_flags_result, dcf_result, management)

        result = {
            "moat": {
                "width": moat.overall_width.value,
                "score": round(moat.moat_score, 1),
                "dimensions": moat.dimensions,
                "trend": moat.moat_trend,
                "evidence": moat.key_evidence[:3],
                "threats": moat.threats[:3],
            },
            "management": {
                "overall": round(management.overall_score, 1),
                "capital_allocation": management.capital_allocation,
                "integrity": management.integrity_score,
                "competency": management.competency_score,
                "incentive": management.incentive_alignment,
                "insider_ownership": management.insider_ownership_pct,
            },
            "overall_score": round(overall, 1),
        }

        if red_flags_result:
            result["red_flags"] = {
                "risk": red_flags_result.overall_risk,
                "total_flags": red_flags_result.total_flags,
                "critical_flags": red_flags_result.critical_flags,
                "m_score": red_flags_result.m_score,
                "m_score_label": red_flags_result.m_score_risk,
                "f_score": red_flags_result.f_score,
                "f_score_label": red_flags_result.f_score_quality,
            }

        if dcf_result and dcf_result.fair_value > 0:
            result["dcf"] = {
                "fair_value": round(dcf_result.fair_value, 2),
                "upside_pct": round(dcf_result.upside_pct * 100, 1),
                "margin_of_safety": round(dcf_result.margin_of_safety * 100, 1),
                "bear_case": round(dcf_result.bear_case, 2),
                "base_case": round(dcf_result.base_case, 2),
                "bull_case": round(dcf_result.bull_case, 2),
                "wacc": dcf_result.wacc,
                "terminal_growth": dcf_result.terminal_growth,
            }

        if consensus.n_analysts > 0:
            result["consensus"] = {
                "n_analysts": consensus.n_analysts,
                "rating": consensus.consensus_rating,
                "buy": consensus.buy_count, "hold": consensus.hold_count, "sell": consensus.sell_count,
                "target_mean": consensus.target_price_mean,
                "target_high": consensus.target_price_high,
                "target_low": consensus.target_price_low,
                "trend": consensus.rating_trend,
                "eps_trend": consensus.eps_revision_trend,
            }

        return result

    @staticmethod
    def _attach_yoy_growth(fin_list: list[dict]) -> list[dict]:
        """为财务数据附加同比增速（revenue_yoy, profit_yoy）。

        从最近两个同期报告期（如 2025Q4 vs 2024Q4）计算同比增速。
        结果直接注入每个 dict 的 revenue_yoy / profit_yoy 字段。
        """
        if len(fin_list) < 2:
            return fin_list
        # 按报告期倒序排列（已在 get_financials 中保证）
        # 找最近一期的同比对应期（report_period 格式如 '2025Q4'）
        latest = fin_list[0]
        latest_period = latest.get("report_period", "")
        # 解析报告期获取年份和季度
        import re
        m = re.match(r"(\d{4})Q(\d)", str(latest_period))
        if not m:
            return fin_list
        year, quarter = int(m.group(1)), int(m.group(2))
        target_period = f"{year - 1}Q{quarter}"
        # 在历史数据中找对应期
        yoy_fin = None
        for f in fin_list[1:]:
            if str(f.get("report_period", "")) == target_period:
                yoy_fin = f
                break
        if yoy_fin is None:
            return fin_list
        # 计算同比增速
        rev_latest = latest.get("revenue")
        rev_yoy = yoy_fin.get("revenue")
        if rev_latest and rev_yoy and rev_yoy != 0:
            latest["revenue_yoy"] = round((rev_latest - rev_yoy) / abs(rev_yoy) * 100, 1)
        np_latest = latest.get("net_profit")
        np_yoy = yoy_fin.get("net_profit")
        if np_latest and np_yoy and np_yoy != 0:
            latest["profit_yoy"] = round((np_latest - np_yoy) / abs(np_yoy) * 100, 1)
        return fin_list

    @staticmethod
    def _financials_to_dict(fin_list: list) -> dict:
        """将财务数据列表转为 dict。"""
        if not fin_list:
            return {}
        latest = fin_list[0] if isinstance(fin_list[0], dict) else {}
        if hasattr(latest, '__dict__'):
            latest = latest.__dict__
        return {
            "net_profit": latest.get("net_profit") or latest.get("净利润"),
            "operating_cashflow": latest.get("operating_cashflow") or latest.get("经营现金流"),
            "total_assets": latest.get("total_assets") or latest.get("总资产"),
            "revenue_growth": latest.get("revenue_growth") or latest.get("revenue_yoy"),
            "gross_margin": latest.get("gross_margin") or latest.get("毛利率"),
            "debt_to_asset": latest.get("debt_to_asset") or latest.get("资产负债率"),
            "roe": latest.get("roe"),
        }

    @staticmethod
    def _extract_fcf(fin_list: list) -> float:
        """从财务数据提取自由现金流。"""
        fin = Orchestrator._financials_to_dict(fin_list)
        ocf = fin.get("operating_cashflow", 0) or 0
        # 简化：FCF ≈ OCF（缺少 CAPEX 数据）
        return float(ocf)

    @staticmethod
    def _calc_deep_overall(moat, red_flags, dcf, management) -> float:
        """公司深度研究综合评分。"""
        scores = []
        if moat:
            scores.append((moat.moat_score, 0.35))
        if red_flags:
            penalty = min(100, red_flags.total_flags * 15)
            scores.append((100 - penalty, 0.20))
        else:
            scores.append((50, 0.20))
        if dcf and dcf.margin_of_safety is not None:
            val_score = min(100, 50 + dcf.margin_of_safety * 100)
            scores.append((val_score, 0.25))
        else:
            scores.append((50, 0.25))
        if management:
            scores.append((management.overall_score, 0.20))
        else:
            scores.append((50, 0.20))

        total_w = sum(w for _, w in scores)
        return sum(s * w for s, w in scores) / total_w if total_w > 0 else 50.0

    def quick_check(self, symbol: str, name: str = "") -> OrchestratorResult:
        """快速检查（仅军规 + 准入检查，不做完整分析）。"""
        result = OrchestratorResult(symbol=symbol, name=name)
        doctrine_result = self.doctrine.check(symbol, {"stock_name": name})
        if not doctrine_result.passed:
            result.passed = False
            result.blocked_by = [r.name for r in doctrine_result.blocked_by]
            return result
        gate_ctx = {}
        try:
            market = "SH" if symbol.startswith(("6", "5", "9")) else "SZ"
            q = self.data.get_quote(symbol, market)
            if q and q.turnover and q.turnover > 0:
                gate_ctx["avg_daily_volume"] = float(q.turnover)
        except Exception:
            pass
        gate_result = self.admission.check(symbol, name, gate_ctx)
        result.gate_status = gate_result.status.value
        result.passed = gate_result.status.value != "REJECTED"
        if not result.passed:
            result.blocked_by = gate_result.flags
        return result

    def _inject_ma_data(self, symbol: str, quote_dict: dict) -> None:
        """从历史 K 线计算 MA20/MA60 + close_series，注入 quote_dict 用于反追高检查。"""
        try:
            bars = self.data.get_history(symbol, start_date="", end_date="", period="daily")
            if bars is not None and not bars.empty:
                close_col = bars["close"] if "close" in bars.columns else None
                if close_col is None and "收盘" in bars.columns:
                    close_col = bars["收盘"]
                if close_col is None:
                    quote_dict["ma20"] = quote_dict["ma60"] = None
                    quote_dict["close_series"] = []
                    return
                if len(close_col) >= 60:
                    quote_dict["ma20"] = float(close_col.rolling(20).mean().iloc[-1])
                    quote_dict["ma60"] = float(close_col.rolling(60).mean().iloc[-1])
                    quote_dict["close_series"] = close_col.tail(10).tolist()
                elif len(close_col) >= 20:
                    quote_dict["ma20"] = float(close_col.rolling(20).mean().iloc[-1])
                    quote_dict["ma60"] = None
                    quote_dict["close_series"] = close_col.tail(10).tolist()
                else:
                    quote_dict["ma20"] = quote_dict["ma60"] = None
                    quote_dict["close_series"] = close_col.tail(len(close_col)).tolist()
            else:
                quote_dict["ma20"] = quote_dict["ma60"] = None
                quote_dict["close_series"] = []
        except Exception:
            logger.debug("MA calculation skipped for %s", symbol)
            quote_dict["ma20"] = quote_dict["ma60"] = None
            quote_dict["close_series"] = []

    @staticmethod
    def _quote_from_cache(symbol: str, market: str = "SH") -> Optional[Quote]:
        """离线 fallback：从本地 K 线缓存最后一行构造 Quote。"""
        import glob
        import pandas as pd
        from src.data.schema import Quote

        base_dir = Path(__file__).resolve().parents[2] / "data" / "kline_cache"
        pattern = f"{symbol}_*_daily.csv"
        files = glob.glob(str(base_dir / pattern))
        if not files:
            return None
        try:
            df = pd.read_csv(files[0])
            if df.empty:
                return None
            row = df.iloc[-1]
            return Quote(
                symbol=symbol,
                name=symbol,
                price=float(row.get("close", 0)),
                change_pct=0.0,
                volume=int(row.get("volume", 0)),
                turnover=0.0,
                high=float(row.get("high")) if pd.notna(row.get("high")) else None,
                low=float(row.get("low")) if pd.notna(row.get("low")) else None,
                open=float(row.get("open")) if pd.notna(row.get("open")) else None,
                prev_close=None,
                pe_ttm=float(row.get("pe_ttm")) if pd.notna(row.get("pe_ttm")) else None,
                pb=float(row.get("pb")) if pd.notna(row.get("pb")) else None,
                market_cap=None,
                source="kline_cache",
            )
        except Exception as e:
            logger.debug("Failed to load quote from cache for %s: %s", symbol, e)
        return None

    # ------------------------------------------------------------------
    # Phase 7: Agent-Worker 模式 — 管道阶段映射到 Agent 边界
    # ------------------------------------------------------------------

    def _data_worker_fetch(self, symbol: str, market: str = "SH") -> dict:
        """Data Worker: 获取行情和财务数据 (只读)。

        映射到 data-worker Agent 的职责边界。
        """
        quote = self.data.get_quote(symbol, market)
        if quote is None:
            return {"error": "数据不可用"}
        return {
            "symbol": symbol,
            "name": quote.name,
            "quote": quote,
            "market": market,
        }

    def _analysis_worker_score(
        self,
        symbol: str,
        name: str,
        data: dict,
        macro: dict | None = None,
        topic_adj: dict | None = None,
    ) -> dict:
        """Analysis Worker: 军规→准入检查→多维诊断→综合裁决 (只读)。

        映射到 analysis-worker Agent 的职责边界。
        返回 verdict 或 blocked 信息。
        """
        quote = data.get("quote")
        portfolio = data.get("portfolio", {})

        # 投资者偏好
        investor, result.using_default_profile, result.profile_completeness, result.profile_missing = self._get_investor_prefs()
        enabled_rules = None
        if investor is not None:
            try:
                from src.learner.preference.adapter import resolve_rule_filter
                enabled_rules = resolve_rule_filter(investor)
            except Exception as e:
                logger.debug("Rule filter unavailable: %s", e)

        # 军规
        ctx = {"stock_name": name, **portfolio}
        if investor is not None:
            ctx["tier"] = investor.tier.value
        doctrine_result = self.doctrine.check(symbol, ctx, enabled_rules=enabled_rules)
        if not doctrine_result.passed:
            return {
                "blocked": True,
                "blocked_by": [r.name for r in doctrine_result.blocked_by],
                "warnings": [r.name for r in doctrine_result.warnings],
            }

        # 准入检查
        gate_ctx = {
            "is_limit_up": False, "is_limit_down": False,
            "is_suspended": False, "listing_days": 365,
        }
        if quote and quote.turnover and quote.turnover > 0:
            gate_ctx["avg_daily_volume"] = float(quote.turnover)
        gate_result = self.admission.check(symbol, name, gate_ctx)
        if gate_result.status.value == "REJECTED":
            return {"blocked": True, "blocked_by": gate_result.flags}

        # Phase 3 上下文注入
        macro_regime = self._get_macro_regime()
        nb_profile = self._get_northbound_profile()
        earnings_factor = self._get_earnings_revision(symbol)
        topic_adj = topic_adj or self._get_topic_adjustments()

        # V4 高管数据
        executive = self._get_executive_context(symbol)

        enriched_macro = macro or {}
        if macro_regime is not None:
            enriched_macro.update({
                "m1_m2_gap": macro_regime.m1_m2_gap,
                "social_financing_growth": macro_regime.social_financing_growth,
                "dr007": macro_regime.dr007,
                "dr007_position": self._dr007_position(macro_regime.dr007),
                "lpr_direction": self._lpr_direction(macro_regime),
                "sf_trend": "accelerating" if (macro_regime.social_financing_growth or 0) > 6 else "stable",
            })

        # 多维诊断
        quote_dict = {"pe_percentile": 40, "northbound": 1}
        fin_list = [{"roe": 15}]
        sentiment_dict = self._get_sentiment(nb_profile)
        report = self.diagnosis.analyze(
            symbol, name, quote_dict, fin_list,
            enriched_macro, sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            earnings_factor=earnings_factor,
            executive=executive,
        )

        # 诊断护栏
        l1_violations = self.enforcer.enforce(
            stage="diagnosis",
            source_citations=report.source_citations,
            confidence=report.confidence,
        )

        # Phase 6: 博弈论 + 投资思维模型 (analysis-worker 同步)
        gt_profile = self.gt_analyzer.analyze(
            symbol, name,
            market_cap=quote.market_cap if quote else None,
            sector="",
        )
        imm_fit = self.imm_analyzer.analyze(
            symbol, name,
            investor=investor,
            portfolio=portfolio,
            sector="",
            market_cap=quote.market_cap if quote else None,
            change_pct=quote.change_pct if quote else None,
        )
        report.game_theory_profile = gt_profile
        report.investor_mental_model = imm_fit
        report.source_citations.extend(gt_profile.source_citations + imm_fit.source_citations)

        # 综合裁决 (with investor preference weights)
        weights = None
        if investor is not None:
            try:
                from src.learner.preference.adapter import resolve_weights
                weights = resolve_weights(investor)
            except Exception:
                pass
        verdict = self.verdict_engine.judge(report, topic_adj=topic_adj, weights_override=weights)

        # 裁决护栏
        l2_violations = self.enforcer.enforce(
            stage="verdict",
            source_citations=verdict.source_citations,
            confidence=verdict.confidence,
        )

        if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
            return {
                "blocked": True,
                "blocked_by": [f"置信度不足 ({verdict.confidence:.2f} < {VerdictEngine.MIN_CONFIDENCE})"],
            }

        return {
            "blocked": False,
            "report": report,
            "verdict": verdict,
            "violations": l1_violations + l2_violations,
            "macro_regime_info": (
                {"quadrant": macro_regime.quadrant.value, "confidence": macro_regime.confidence}
                if macro_regime else None
            ),
        }

    def _signal_writer_produce(
        self,
        symbol: str,
        name: str,
        analysis_result: dict,
        portfolio: dict | None = None,
    ) -> dict:
        """Signal Writer: 仓位调度→风控→护栏审查 (唯一写权限)。

        映射到 signal-writer Agent 的职责边界。
        """
        verdict = analysis_result.get("verdict")
        if verdict is None:
            return {"blocked": True, "blocked_by": ["无裁决结果"]}

        # 仓位调度 (with investor preference limits)
        position_limits = None
        risk_mult = 1.0
        if investor is not None:
            try:
                from src.learner.preference.adapter import (
                    resolve_macro_cap_multiplier,
                    resolve_position_limits,
                )
                position_limits = resolve_position_limits(investor)
                risk_mult = resolve_macro_cap_multiplier(investor)
            except Exception:
                pass
        signal = self.positioning.generate_signal(
            verdict,
            macro_cap=0.80 * risk_mult,
            position_limits=position_limits,
            risk_multiplier=risk_mult,
        )
        l3_violations = self.enforcer.enforce(
            stage="positioning",
            source_citations=signal.source_citations,
            confidence=signal.confidence,
        )

        # 风控 (with investor preference limits)
        eq2 = (portfolio or {}).get("total_equity", 0)
        if eq2 > 0:
            self.risk_ctrl.update_equity(float(eq2))
        risk = self.risk_ctrl.check(signal, portfolio, position_limits=position_limits)
        l4_violations = self.enforcer.enforce(
            stage="risk_control",
            source_citations=risk.source_citations,
        )

        all_violations = (
            analysis_result.get("violations", [])
            + l3_violations + l4_violations
        )

        return {
            "symbol": symbol,
            "name": name,
            "passed": not self.enforcer.is_blocked(all_violations),
            "report": analysis_result.get("report"),
            "verdict": verdict,
            "signal": signal,
            "risk": risk,
            "violations": all_violations,
        }

    def run_t0(
        self, symbol: str, market: str = "SH", name: str = "",
    ) -> Optional[dict]:
        """执行 T+0 日内时机分析（日线+分钟线双维度）。

        独立于主工作流，聚焦"何时操作"的时机判断。
        在主工作流的战略方向确定后，调用此方法获取战术时机。

        Returns:
            dict 含 action / score / signals / suggested_price 等字段，
            数据不足时返回 None。
        """
        try:
            from src.analysis.t0_decision import T0DecisionEngine
            from src.data.schema import Resolution
        except ImportError:
            return None

        # 拉取日线数据 (腾讯 K 线 API，不封 IP)
        try:
            from datetime import datetime, timedelta
            import urllib.request, json
            prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
            url = (
                f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                f"?param={prefix}{symbol},day,,,60,qfq"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            raw = json.loads(resp.read().decode("utf-8"))
            kline_key = f"{prefix}{symbol}"
            kline_data = (
                (raw.get("data") or {}).get(kline_key, {}).get("qfqday")
                or (raw.get("data") or {}).get(kline_key, {}).get("day")
                or []
            )
            # 腾讯格式: ["YYYY-MM-DD", "开盘", "收盘", "最高", "最低", "成交量(手)"]
            from src.data.schema import Bar, Resolution as Res
            daily_bars = []
            for row in kline_data[-60:]:
                try:
                    ts = datetime.strptime(row[0], "%Y-%m-%d")
                    daily_bars.append(Bar(
                        symbol=symbol, resolution=Res.DAY,
                        open=float(row[1]), close=float(row[2]),
                        high=float(row[3]), low=float(row[4]),
                        volume=int(float(row[5])), amount=0,
                        timestamp=ts,
                    ))
                except (ValueError, IndexError):
                    continue
            if len(daily_bars) < 5:
                logger.warning("T+0: 腾讯日线数据不足 (%d 根)", len(daily_bars))
            daily_bars = daily_bars[-20:]  # 取最近 20 根
        except Exception as e:
            logger.warning("T+0: 腾讯日线获取失败: %s", e)
            return None

        # 拉取今日分钟数据
        try:
            from datetime import datetime
            today_str = datetime.now().strftime("%Y%m%d")
            minute_bars = self.data.mootdx.get_bars(
                symbol, Resolution.MIN_1, start=today_str, end=today_str,
            )
            # 过滤到今天+截止当前时间
            now = datetime.now()
            today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            minute_bars = [
                b for b in minute_bars
                if b is not None and b.timestamp.date() == today_dt.date()
                and b.timestamp <= now
            ]
        except Exception as e:
            logger.debug("T+0: 分钟数据获取失败: %s", e)
            minute_bars = []

        # 获取昨日收盘
        prev_close = 0.0
        if len(daily_bars) >= 2:
            prev_close = daily_bars[-2].close

        engine = T0DecisionEngine()
        result = engine.analyze(
            symbol=symbol,
            daily_bars=daily_bars,
            minute_bars=minute_bars,
            prev_close=prev_close,
            name=name,
        )

        # 转为 dict 返回
        return {
            "action": result.action.value,
            "score": result.score,
            "ma5": result.ma5,
            "ma10": result.ma10,
            "ma20": result.ma20,
            "resistance": result.resistance,
            "support_1": result.support_1,
            "vwap": result.vwap,
            "day_high": result.day_high,
            "day_low": result.day_low,
            "day_low_time": result.day_low_time,
            "amplitude": result.amplitude,
            "rebound_from_low": result.rebound_from_low,
            "total_vol": result.total_vol,
            "total_amount": result.total_amount,
            "rebound_quality": result.rebound_quality,
            "large_sell_count": result.large_sell_count,
            "large_buy_count": result.large_buy_count,
            "daily_patterns": result.daily_patterns,
            "intraday_pattern": result.intraday_pattern,
            "signals_bull": [s.description for s in result.signals_bull],
            "signals_bear": [s.description for s in result.signals_bear],
            "suggested_price": result.suggested_price,
            "stop_loss": result.stop_loss,
            "trigger_condition": result.trigger_condition,
            "summary": result.to_summary(),
            "multi_day_summary": result.multi_day_summary,
            "volume_trend": result.volume_trend,
            "trend_5d": result.trend_5d,
            "gap_analysis": result.gap_analysis,
            "overnight_risk": result.overnight_risk,
        }

    def run_macro_event(
        self,
        event_description: str,
        *,
        category: str = "",
        title: str = "",
        source: str = "",
        stock_symbol: str = "",
        stock_sector: str = "",
        current_macro: dict | None = None,
    ) -> Optional[dict]:
        """分析宏观事件对A股的因果链影响。

        在股票分析前先搞清楚"发生了什么大事"→"怎么传导到A股/个股"。
        参考 AI Gold Miner ScenarioAnalyzer 的因果链推演模式。

        Returns:
            dict 含 summary / channels / impact / strategy 等字段
        """
        try:
            from src.macro.event_analyzer import EventAnalyzer
        except ImportError:
            return None

        analyzer = EventAnalyzer()
        report = analyzer.analyze(
            event_description=event_description,
            category_hint=category,
            title=title,
            source=source,
            stock_symbol=stock_symbol,
            stock_sector=stock_sector,
            current_macro=current_macro,
        )

        return {
            "title": report.event.title,
            "category": report.event.category.value,
            "summary": report.summary,
            "net_bullish_score": report.net_bullish_score,
            "channels": [
                {
                    "channel": ch.channel,
                    "direction": ch.direction.value,
                    "magnitude": ch.magnitude.value,
                    "description": ch.description,
                    "timeframe": ch.timeframe.value,
                    "affected_sectors": ch.affected_sectors,
                }
                for ch in report.transmission_channels
            ],
            "impact": {
                "direction": report.impact.direction.value if report.impact else "neutral",
                "base_case": report.impact.base_case_change_pct if report.impact else 0.0,
                "bullish_case": report.impact.bullish_case_change_pct if report.impact else 0.0,
                "bearish_case": report.impact.bearish_case_change_pct if report.impact else 0.0,
                "peak_days": report.impact.peak_impact_days if report.impact else 0,
                "confidence": report.impact.confidence if report.impact else 0.5,
                "reasoning": report.impact.reasoning if report.impact else "",
            },
            "analogs": [
                {"name": a.event_name, "period": a.period, "similarity": a.similarity_score}
                for a in report.historical_analogs
            ],
            "strategy": {
                "position": report.strategy.overall_position,
                "action": report.strategy.suggested_action,
                "hedging": report.strategy.hedging_suggestions,
                "indicators": report.strategy.monitoring_indicators,
                "sizing": report.strategy.position_sizing,
            },
            "risk_factors": report.risk_factors,
            "stock_impact": report.stock_impact_summary,
        }

    def _run_pipeline_parallel(
        self,
        symbol: str,
        market: str = "SH",
        name: str = "",
        macro: Optional[dict] = None,
        portfolio: Optional[dict] = None,
    ) -> OrchestratorResult:
        """并行版分析管道：独立数据获取/分析器并发，裁决/仓位调度/风控 顺序执行。"""
        result = OrchestratorResult(symbol=symbol, name=name)

        # ---- Phase 1: 并行独立数据获取 ----
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(self.data.get_cross_validated_quote, symbol, market): "quote",
                pool.submit(self.data.get_financials, symbol, market, 4): "financials",
                pool.submit(self._get_macro_regime): "macro_regime",
                pool.submit(self._get_northbound_profile): "northbound",
                pool.submit(self._get_earnings_revision, symbol): "earnings",
                pool.submit(self._get_executive_context, symbol): "executive",
                pool.submit(self._get_block_trade_profile, symbol): "block_trade",
            }
            gathered: dict = {}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    gathered[key] = future.result()
                except Exception as e:
                    logger.debug("Parallel fetch %s failed: %s", key, e)
                    gathered[key] = None

        quote_cv = gathered.get("quote")
        quote = quote_cv[0] if isinstance(quote_cv, tuple) else quote_cv
        cross_validated = quote_cv[1] if isinstance(quote_cv, tuple) else False
        dispute = quote_cv[2] if isinstance(quote_cv, tuple) else False
        if quote is None:
            result.passed = False
            result.blocked_by.append("数据不可用")
            return result
        result.cross_validated = cross_validated
        if not name:
            name = quote.name
            result.name = name

        quote_dict = quote.model_dump()
        quote_dict["_source"] = quote.source
        quote_dict["cross_validated"] = cross_validated
        quote_dict["dispute"] = dispute
        fin_list = [f.model_dump() for f in (gathered.get("financials") or [])]
        macro_regime = gathered.get("macro_regime")
        nb_profile = gathered.get("northbound")
        bt_profile = gathered.get("block_trade")
        earnings_factor = gathered.get("earnings")
        executive = gathered.get("executive")

        # ---- Phase 2: 并行分析器（无写操作） ----
        investor, result.using_default_profile, result.profile_completeness, result.profile_missing = self._get_investor_prefs()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self.gt_analyzer.analyze, symbol, name, quote.market_cap if quote else None, ""): "game_theory",
                pool.submit(self.imm_analyzer.analyze, symbol, name, investor, portfolio, "", quote.market_cap if quote else None, quote.change_pct if quote else None): "mental_model",
                pool.submit(self.perspective_analyzer.debate, symbol, name, None, quote_dict, fin_list): "debate",
                pool.submit(
                    self.mental_model_matcher.match_models, symbol, name, "",
                    None,  # report 尚未生成，诊断阶段后会用 report 版本覆盖
                    "",     # question
                    {"macro_regime": macro_regime, "nb_profile": nb_profile, "earnings": earnings_factor},
                ): "munger_models",
            }
            analyses: dict = {}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    analyses[key] = future.result()
                except Exception as e:
                    logger.debug("Parallel analysis %s failed: %s", key, e)
                    analyses[key] = None

        # ---- Phase 3: 顺序 诊断→质量→裁决→仓位调度→风控 ----
        # 为简化，复用 run() 的剩余逻辑；这里仅演示边界划分
        enriched_macro = macro or {}
        if macro_regime is not None:
            enriched_macro.update({
                "m1_m2_gap": macro_regime.m1_m2_gap,
                "social_financing_growth": macro_regime.social_financing_growth,
                "dr007": macro_regime.dr007,
                "dr007_position": self._dr007_position(macro_regime.dr007),
                "lpr_direction": self._lpr_direction(macro_regime),
                "sf_trend": "accelerating" if (macro_regime.social_financing_growth or 0) > 6 else "stable",
            })

        report = self.diagnosis.analyze(
            symbol, name, quote_dict, fin_list, enriched_macro, {"level": "NORMAL"},
            macro_regime=macro_regime, northbound_profile=nb_profile,
            block_trade_profile=bt_profile,
            earnings_factor=earnings_factor, executive=executive,
        )
        report.game_theory_profile = analyses.get("game_theory")
        report.investor_mental_model = analyses.get("mental_model")
        report.debate_result = analyses.get("debate")
        report.mental_models = analyses.get("munger_models") or []
        result.report = report
        result.game_theory_info = (
            analyses["game_theory"].to_dict() if analyses.get("game_theory") else None
        )
        result.mental_model_info = (
            analyses["mental_model"].to_dict() if analyses.get("mental_model") else None
        )
        result.debate_result = {
            "avg_score": analyses["debate"].avg_score,
            "score_range": analyses["debate"].score_range,
            "agreement_level": analyses["debate"].agreement_level,
            "recommendation": analyses["debate"].recommendation,
        } if analyses.get("debate") else None
        result.mental_models = report.mental_models

        verdict = self.verdict_engine.judge(report)
        result.verdict = verdict
        if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
            result.passed = False
            result.blocked_by.append(f"置信度不足 ({verdict.confidence:.2f} < {VerdictEngine.MIN_CONFIDENCE})")
            return result

        signal = self.positioning.generate_signal(verdict, macro_cap=0.80, name=name, extra=quote_dict)
        result.signal = signal
        eq3 = (portfolio or {}).get("total_equity", 0)
        if eq3 > 0:
            self.risk_ctrl.update_equity(float(eq3))
        risk = self.risk_ctrl.check(signal, portfolio or {})
        result.risk = risk
        result.passed = True
        return result

    # ------------------------------------------------------------------
    # Phase 4: Alpha Lens 上下文注入
    # ------------------------------------------------------------------

    def _get_alpha_profile(
        self,
        symbol: str,
        name: str,
        news_context: list[dict] | dict,
        as_of_date: str = "",
    ) -> AlphaProfile:
        """Phase 4: 计算 Alpha Profile。

        综合四维:
          1. 信息来源层级
          2. 共识-现实缺口
          3. 叙事生命周期
          4. 供应链深度 Alpha（紫苏叶理论）🆕

        回答「我比别人多知道什么？」

        as_of_date: 历史回测日期 (YYYY-MM-DD)，启用时使用历史真实数据
        """
        # 从资讯上下文中提取来源信息 (兼容新旧格式)
        flat_news = _flatten_news_context(news_context)
        news_sources: list[str] = []
        market_narrative_parts: list[str] = []
        narrative_intensity = 0.0
        sentiment = "NEUTRAL"

        for item in flat_news:
            title = item.get("title", "")
            source = item.get("source", "")
            content = item.get("content", "")[:200] if item.get("content") else ""

            news_sources.append(f"{source}: {title}")
            market_narrative_parts.append(title)

            # 估算叙事强度：资讯数量越多 → 叙事越强
            narrative_intensity = min(1.0, len(flat_news) / 10)

        # 从 symbol 和 name 推断基本信息
        market_narrative = (
            f"关于 {name}({symbol}) 的市场讨论: "
            + ("; ".join(market_narrative_parts[:3]))
            if market_narrative_parts else ""
        )

        # 🆕 获取供应链深度数据（紫苏叶理论）
        supply_chain_data: dict = {}
        bottleneck_data: dict = {}
        try:
            from src.industry.supply_chain import SupplyChainDeepMapper
            mapper = SupplyChainDeepMapper()
            supply_chain_data = mapper.analyze(symbol)
            logger.debug(
                "Supply chain data for %s: layer=%s bottleneck=%s",
                symbol,
                supply_chain_data.get("layer", "unknown"),
                supply_chain_data.get("bottleneck_type", "NONE"),
            )
        except Exception as e:
            logger.debug("Supply chain data unavailable for %s: %s", symbol, e)

        # ── P0: 接入真实数据源，填充 AlphaLens 缺失的5个参数 ──

        # 1. institutional_attention — 北向资金市场级机构关注度 (T1, 东财/同花顺)
        institutional_attention = 50.0  # 默认中性
        try:
            nb = self._get_northbound_profile(as_of_date=as_of_date)
            if nb is not None:
                nb_score = getattr(nb, "score", 50.0) or 50.0
                consecutive = getattr(nb, "consecutive_days", 0) or 0
                is_sustained = getattr(nb, "is_inflow_sustained", False)
                bonus = min(15, abs(consecutive) * 3) * (1 if is_sustained else -0.5)
                institutional_attention = min(100, max(20, nb_score + bonus))
                logger.debug(
                    "AlphaLens institutional_attention=%s (nb_score=%s)",
                    institutional_attention, nb_score,
                )
        except Exception as e:
            logger.debug("Northbound data unavailable for AlphaLens: %s", e)

        # 2. retail_attention — 融资融券散户关注度 (T1, 东财 datacenter)
        retail_attention = 50.0
        try:
            mp = self._get_margin_profile(symbol, as_of_date=as_of_date)
            if mp is not None:
                mp_score = getattr(mp, "score", 50.0) or 50.0
                chg_5d = abs(getattr(mp, "margin_balance_5d_change_pct", 0.0) or 0.0)
                divergence = getattr(mp, "divergence_signal", "none") or "none"
                bonus = min(15, chg_5d * 0.5)
                if divergence != "none":
                    bonus += 10
                retail_attention = min(100, max(20, mp_score + bonus))
                logger.debug(
                    "AlphaLens retail_attention=%s (margin_score=%s)",
                    retail_attention, mp_score,
                )
        except Exception as e:
            logger.debug("Margin data unavailable for AlphaLens: %s", e)

        # 3. valuation_reflected — PE估值反映度 (T1, 基于历史价格÷历史EPS)
        valuation_reflected = 0.5
        try:
            # --as-of 模式: 用历史价格÷历史EPS计算PE
            if as_of_date:
                from datetime import datetime as _dt
                as_of_dt = _dt.strptime(as_of_date, "%Y-%m-%d")
                # 获取 as_of 日期的行情
                from src.data.mootdx_tencent import MootdxTencentProvider
                mt = MootdxTencentProvider()
                from src.data.schema import Resolution
                bars = mt.get_bars(symbol, resolution=Resolution.DAY, start=as_of_date, end=as_of_date)
                hist_price = float(bars[-1].close) if bars else 0.0
                # 获取 as_of 日期的财务数据
                fin_data = self.data.get_financials(symbol=symbol, count=1, report_period=as_of_date)
                hist_eps = 0.0
                if fin_data:
                    hist_eps = float(getattr(fin_data[0], "eps", 0) or 0) * 4  # Q1年化
                if hist_price > 0 and hist_eps > 0:
                    hist_pe = hist_price / hist_eps
                    if hist_pe > 100: valuation_reflected = 0.85
                    elif hist_pe > 50: valuation_reflected = 0.70
                    elif hist_pe > 30: valuation_reflected = 0.55
                    elif hist_pe > 15: valuation_reflected = 0.40
                    else: valuation_reflected = 0.30
            else:
                metrics = self.data.get_fundamental_metrics(symbol)
                pe = metrics.get("pe_ttm", 0) or metrics.get("pe", 0) or 0
                if pe > 0:
                    if pe > 100: valuation_reflected = 0.85
                    elif pe > 50: valuation_reflected = 0.70
                    elif pe > 30: valuation_reflected = 0.55
                    elif pe > 15: valuation_reflected = 0.40
                    else: valuation_reflected = 0.30
            logger.debug("AlphaLens valuation_reflected=%s", valuation_reflected)
        except Exception as e:
            logger.debug("PE data unavailable for AlphaLens: %s", e)

        # 4. discussion_volume — 互动易问答量 (T0, 巨潮 cninfo)
        #    支持 as_of 历史日期过滤（翻页全量拉取 + 客户端按 pubDate 过滤）
        discussion_volume = 50.0
        try:
            from src.information.irm import IrmAnalyzer
            irma = IrmAnalyzer()
            irm_result = irma.analyze(symbol, as_of_date=as_of_date)
            if irm_result is not None:
                total_q = getattr(irm_result, "total_questions", 0) or 0
                discussion_volume = min(100, max(20, total_q * 0.8 + 20))
                logger.debug(
                    "AlphaLens discussion_volume=%s (irm_questions=%s)",
                    discussion_volume, total_q,
                )
        except Exception as e:
            logger.debug("IRM data unavailable for AlphaLens discussion_volume: %s", e)

        # 5. discussion_growth_rate — 互动易问答增长趋势
        discussion_growth_rate = 0.0
        try:
            from src.information.irm import IrmAnalyzer
            irma2 = IrmAnalyzer()
            irm_result2 = irma2.analyze(symbol, as_of_date=as_of_date)
            if irm_result2 is not None:
                recent = getattr(irm_result2, "recent_questions", None) or []
                if len(recent) > 10: discussion_growth_rate = 15.0
                elif len(recent) > 5: discussion_growth_rate = 5.0
                elif len(recent) == 0: discussion_growth_rate = -10.0
                logger.debug(
                    "AlphaLens discussion_growth_rate=%s (recent_q=%s)",
                    discussion_growth_rate, len(recent),
                )
        except Exception as e:
            logger.debug("IRM growth rate unavailable for AlphaLens: %s", e)

        return self.alpha_lens.analyze(
            symbol=symbol,
            news_sources=news_sources,
            market_narrative=market_narrative,
            narrative_intensity=narrative_intensity,
            sentiment_extreme=sentiment,
            supply_chain_data=supply_chain_data if supply_chain_data else None,
            bottleneck_data=bottleneck_data if bottleneck_data else None,
            discussion_volume=discussion_volume,
            discussion_growth_rate=discussion_growth_rate,
            institutional_attention=institutional_attention,
            retail_attention=retail_attention,
            valuation_reflected=valuation_reflected,
        )

    # ------------------------------------------------------------------
    # Phase 3: 增强上下文注入
    # ------------------------------------------------------------------

    @staticmethod
    def _get_macro_regime():
        """获取当前宏观货币信用象限。"""
        try:
            from src.macro.monetary_credit import MonetaryCreditAnalyzer
            analyzer = MonetaryCreditAnalyzer()
            return analyzer.analyze()
        except Exception as e:
            logger.debug("Macro regime unavailable: %s", e)
        return None

    @staticmethod
    def _get_northbound_profile(as_of_date: str = ""):
        """获取多维北向资金画像。
        as_of_date: 历史回测日期 (YYYY-MM-DD)，使用 AKShare stock_hsgt_hist_em 历史数据
        """
        try:
            from src.game_theory.northbound import NorthboundAnalyzer
            analyzer = NorthboundAnalyzer()
            if as_of_date:
                return analyzer.analyze(as_of_date=as_of_date)
            return analyzer.analyze()
        except Exception as e:
            logger.debug("Northbound profile unavailable: %s", e)
        return None

    @staticmethod
    def _get_margin_profile(symbol: str, as_of_date: str = ""):
        """获取个股融资融券画像 (T1, 东财 datacenter)。
        as_of_date: 历史回测日期 (YYYYMMDD)，使用 AKShare stock_margin_detail_sse
        """
        try:
            import akshare as ak
            from datetime import datetime as _dt
            # 确定查询日期
            if as_of_date:
                query_date = _dt.strptime(as_of_date, "%Y-%m-%d").strftime("%Y%m%d")
            else:
                query_date = _dt.now().strftime("%Y%m%d")

            # 尝试SSE，失败则尝试SZSE
            df = None
            for exchange in ["sse", "szse"]:
                try:
                    if exchange == "sse":
                        df = ak.stock_margin_detail_sse(date=query_date)
                    else:
                        df = ak.stock_margin_detail_szse(date=query_date)
                    if df is not None and not df.empty:
                        row = df[df['标的证券代码'] == symbol]
                        if not row.empty:
                            r = row.iloc[0]
                            # 构建简化 profile
                            from collections import namedtuple
                            MarginProfile = namedtuple("MarginProfile", [
                                "score", "margin_balance", "margin_balance_5d_change_pct",
                                "margin_balance_20d_change_pct", "margin_net_buy",
                                "consecutive_outflow_days", "consecutive_inflow_days",
                                "margin_signal", "leverage_sentiment", "divergence_signal",
                                "data_date",
                            ])
                            balance = float(r.get('融资余额', 0))
                            buy = float(r.get('融资买入额', 0))
                            repay = float(r.get('融资偿还额', 0))
                            net_buy = buy - repay
                            # 归一化 score: 融资余额越大+净买入→散户关注度越高
                            score = min(100, max(20, 50 + (net_buy / max(balance, 1e8)) * 5000))
                            return MarginProfile(
                                score=score, margin_balance=balance,
                                margin_balance_5d_change_pct=0.0,
                                margin_balance_20d_change_pct=0.0,
                                margin_net_buy=net_buy,
                                consecutive_outflow_days=0, consecutive_inflow_days=0,
                                margin_signal="neutral", leverage_sentiment="neutral",
                                divergence_signal="none", data_date=query_date,
                            )
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Margin profile unavailable for %s: %s", symbol, e)
        return None

    @staticmethod
    def _get_block_trade_profile(symbol: str = ""):
        """获取大宗交易资金画像（含机构接盘信号）。"""
        try:
            from src.game_theory.block_trade import BlockTradeAnalyzer
            analyzer = BlockTradeAnalyzer()
            if symbol:
                return analyzer.analyze(symbol=symbol)
            return analyzer.analyze()
        except Exception as e:
            logger.debug("Block trade profile unavailable: %s", e)
        return None

    @staticmethod
    def _get_earnings_revision(symbol: str):
        """获取盈利修正因子。"""
        try:
            from src.data.earnings_revision import EarningsRevisionAnalyzer
            analyzer = EarningsRevisionAnalyzer()
            return analyzer.analyze(symbol)
        except Exception as e:
            logger.debug("Earnings revision unavailable for %s: %s", symbol, e)
        return None

    @staticmethod
    def _get_topic_adjustments() -> dict:
        """从 TopicManager 获取主题生命周期权重调整。"""
        try:
            from src.information.topic_manager import TopicManager
            mgr = TopicManager()
            return mgr.get_lifecycle_adjustments()
        except Exception as e:
            logger.debug("Topic adjustments unavailable: %s", e)
        return {}

    @staticmethod
    def _get_cycle_phase(macro_regime: Optional[object] = None):
        """获取当前经济周期阶段。"""
        try:
            from src.cycle.analyzer import CycleAnalyzer
            analyzer = CycleAnalyzer()
            return analyzer.analyze(macro_regime=macro_regime)
        except Exception as e:
            logger.debug("Cycle analysis unavailable: %s", e)
        return None

    @staticmethod
    def _get_valuation(
        symbol: str,
        name: str,
        fundamental_metrics=None,
        pe_percentile: Optional[float] = None,
        industry_pe: Optional[float] = None,
        industry_pb: Optional[float] = None,
        earnings_growth: Optional[float] = None,
        dividend_yield: Optional[float] = None,
        roe: Optional[float] = None,
        cycle_analysis: Optional[object] = None,
    ):
        """执行多维估值分析，可选注入周期上下文进行PE周期调整。"""
        try:
            from src.valuation.analyzer import ValuationAnalyzer
            analyzer = ValuationAnalyzer()
            pe_ttm = getattr(fundamental_metrics, "pe_ttm", None) if fundamental_metrics else None
            pb = getattr(fundamental_metrics, "pb", None) if fundamental_metrics else None
            return analyzer.analyze(
                symbol=symbol,
                name=name,
                pe_ttm=pe_ttm,
                pb=pb,
                pe_percentile=pe_percentile,
                roe=roe or (getattr(fundamental_metrics, "roe", None) if fundamental_metrics else None),
                earnings_growth=earnings_growth,
                dividend_yield=dividend_yield,
                industry_pe_median=industry_pe,
                industry_pb_median=industry_pb,
                cycle_analysis=cycle_analysis,
            )
        except Exception as e:
            logger.debug("Valuation analysis unavailable for %s: %s", symbol, e)
        return None

    @staticmethod
    def _get_investor_prefs():
        """加载投资者偏好画像，同时返回完整度信息。"""
        try:
            from src.learner.preference.loader import InvestorPreferenceLoader
            loader = InvestorPreferenceLoader()
            prefs = loader.load()
            comp = prefs.completeness()
            is_default = comp["is_default"]
            return prefs, is_default, comp["score"], comp["missing"]
        except Exception as e:
            logger.debug("Investor preferences unavailable: %s", e)
        return None, True, 0, ["投资者画像未能加载"]

    @staticmethod
    def _get_sentiment(nb_profile: Optional[dict] = None) -> dict:
        """
        获取大盘情绪信号，替换硬编码的 {"level": "NORMAL"}。
        优先使用北向资金数据提供上下文，回退到默认值。
        """
        try:
            from src.sentiment.signals import SentimentDetector
            detector = SentimentDetector()
            kwargs = {}
            if nb_profile:
                kwargs["northbound"] = nb_profile.get("net_flow", 0.0)
            sentiment = detector.detect_market(**kwargs)
            return {
                "level": sentiment.level.value,
                "score": sentiment.score,
                "advance_decline_ratio": sentiment.advance_decline_ratio,
                "northbound_net": sentiment.northbound_net,
                "limit_up_count": sentiment.limit_up_count,
                "limit_down_count": sentiment.limit_down_count,
                # 深度解读字段
                "market_breadth_insight": sentiment.market_breadth_insight,
                "volume_insight": sentiment.volume_insight,
                "northbound_insight": sentiment.northbound_insight,
                "limit_pool_insight": sentiment.limit_pool_insight,
                "vix_insight": sentiment.vix_insight,
                "sector_signal_insight": sentiment.sector_signal_insight,
                "panic_arb_advice": sentiment.panic_arb_advice,
            }
        except Exception as e:
            logger.debug("Sentiment detection unavailable: %s", e)
        return {"level": "NORMAL", "score": 50}

    @staticmethod
    def _get_fiscal_regime():
        """获取财政政策状态。"""
        try:
            from src.macro.fiscal import FiscalAnalyzer
            analyzer = FiscalAnalyzer()
            return analyzer.analyze()
        except Exception as e:
            logger.debug("Fiscal analysis unavailable: %s", e)
        return None

    @staticmethod
    def _get_policy_signals():
        """获取政策跟踪信号。"""
        try:
            from src.policy.tracker import PolicyTracker
            tracker = PolicyTracker()
            return tracker.analyze_current()
        except Exception as e:
            logger.debug("Policy tracker unavailable: %s", e)
        return None

    @staticmethod
    def _get_market_regime(agg) -> Optional[object]:
        """获取市场状态分类 (RegimeClassifier).

        从 DataAggregator 拉取上证指数日线，
        调用 RegimeClassifier 做 6 状态技术分类。
        """
        try:
            from src.macro.market_regime import RegimeClassifier
            index_df = agg.get_history("000001", "SH", period="daily")
            if index_df is None or index_df.empty:
                logger.debug("Market regime: no index data available")
                return None
            prices = index_df["close"].tolist() if "close" in index_df.columns else None
            if not prices or len(prices) < 20:
                logger.debug("Market regime: insufficient data points (%d)", len(prices or []))
                return None
            classifier = RegimeClassifier()
            return classifier.classify(prices=prices)
        except Exception as e:
            logger.debug("Market regime classification unavailable: %s", e)
        return None

    @staticmethod
    def _get_policy_transmission(policy_signals: list[dict] | None) -> dict | None:
        """政策关键词→板块传导链分析 (SectorTransmissionAnalyzer)."""
        if not policy_signals:
            return None
        try:
            from src.policy.transmission import SectorTransmissionAnalyzer
            all_keywords: list[str] = []
            all_sectors_raw: list[tuple[str, float]] = []
            for signal in policy_signals:
                all_keywords.extend(signal.get("keywords", []))
                for s in signal.get("affected_sectors", []):
                    all_sectors_raw.append((s, 1.0))
                for s in signal.get("affected_sectors_neg", []):
                    all_sectors_raw.append((s, -1.0))
            if not all_keywords:
                return None
            analyzer = SectorTransmissionAnalyzer()
            impacts = analyzer.analyze_policy(all_keywords, all_sectors_raw)
            if not impacts:
                return None
            # 序列化为纯 dict
            return {
                sector: {
                    "net_strength": impact.net_strength,
                    "avg_time_lag": impact.avg_time_lag,
                    "confidence": impact.confidence,
                }
                for sector, impact in impacts.items()
            }
        except Exception as e:
            logger.debug("Policy transmission analysis unavailable: %s", e)
        return None

    @staticmethod
    def _dr007_position(dr007: Optional[float]) -> str:
        """判断 DR007 相对政策利率的位置。"""
        if dr007 is None:
            return "neutral"
        policy_rate = 1.50  # 7-day reverse repo rate
        if dr007 < policy_rate - 0.05:
            return "below_policy"
        elif dr007 > policy_rate + 0.15:
            return "above_policy"
        return "neutral"

    @staticmethod
    def _lpr_direction(macro_regime) -> str:
        """判断 LPR 变动方向（简化版）。"""
        if macro_regime is None:
            return "stable"
        lpr_1y = getattr(macro_regime, "lpr_1y", None)
        # Default to stable - actual trend needs historical comparison
        return "stable"

    # ------------------------------------------------------------------
    # V4 妙想增强: 资讯上下文 + 关联关系
    # ------------------------------------------------------------------

    @staticmethod
    def _get_news_context(symbol: str, name: str) -> dict:
        """获取个股多通道资讯上下文（新闻+公告+研报+7×24快讯+快查+30日）。

        返回 dict 结构:
            {
                "news": [...],           # 个股新闻
                "announcements": [...],  # 公告
                "research_reports": [...],  # 研报
                "flash_24x7": [...],     # 7×24 快讯
                "kuaicha_news": [...],   # 快查问财
                "last30days": [...],     # 最近 30 日
                "summary": "...",        # 单行摘要
                "errors": [...],         # 错误列表
                "total_items": N,        # 总条数
            }
        """
        try:
            from src.information.news_context import fetch_news_context
            ctx = fetch_news_context(symbol, name)
            result = {
                "news": [_ni_to_dict(item) for item in ctx.news],
                "announcements": [_ni_to_dict(item) for item in ctx.announcements],
                "research_reports": [_ni_to_dict(item) for item in ctx.research_reports],
                "flash_24x7": [_ni_to_dict(item) for item in ctx.flash_24x7],
                "kuaicha_news": [_ni_to_dict(item) for item in ctx.kuaicha_news],
                "last30days": [_ni_to_dict(item) for item in ctx.last30days],
                "summary": ctx.summary,
                "errors": ctx.errors,
                "total_items": ctx.total_items,
            }
            return result
        except Exception as e:
            logger.debug("News context unavailable for %s: %s", symbol, e)
        return {
            "news": [], "announcements": [], "research_reports": [],
            "flash_24x7": [], "kuaicha_news": [], "last30days": [],
            "summary": "不可用", "errors": [str(e) if 'e' in dir() else "unknown"],
            "total_items": 0,
        }

    def _inject_bottom_structure_ctx(
        self,
        symbol: str,
        market: str,
        quote_dict: dict,
        ctx: dict,
    ) -> None:
        """注入 r013/r013b 所需的底部结构上下文（A/B 段相位）。

        优先 quote_dict 内 daily_bars / OHLC series；不足时尝试拉日线。
        失败时静默，不阻断军规主流程。
        """
        try:
            from src.analysis.bottom_structure import analyze_bottom_structure
            from src.routing.diagnosis import DiagnosisEngine

            # 复用诊断侧抽取逻辑：构造最小 quote
            q = dict(quote_dict or {})
            if not q.get("daily_bars") and hasattr(self, "data") and self.data is not None:
                try:
                    bars = None
                    if hasattr(self.data, "get_daily_bars"):
                        bars = self.data.get_daily_bars(symbol, market, count=90)
                    if bars:
                        q["daily_bars"] = bars
                except Exception:
                    pass

            bs = DiagnosisEngine._detect_bottom_structure(q)
            if bs is None:
                return
            phase = getattr(bs, "phase", None)
            phase_val = getattr(phase, "value", None) or str(phase or "")
            ctx["bottom_phase"] = phase_val
            ctx["bottom_ab_ratio"] = float(getattr(bs, "ab_ratio", 0.0) or 0.0)
            ctx["bottom_entry_allowed"] = bool(getattr(bs, "entry_allowed", False))
            ctx["bottom_structure_summary"] = str(getattr(bs, "summary", "") or "")
        except Exception as e:
            logger.debug("Failed to inject bottom structure ctx for %s: %s", symbol, e)

    @staticmethod
    def _inject_financial_doctrine_ctx(symbol: str, market: str, ctx: dict) -> None:
        """注入 r032/r033/r034 财务质量军规所需上下文。

        从财务数据中提取近 3 年 ROE、累计经营现金流/净利润/分红。
        数据不足时保留空列表/0.0，由 checker 按"数据不足触发警告"处理。
        """
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            fins = agg.get_financials(symbol, market, count=12)
            if not fins:
                return

            # 按年份分组，取每年最新一期年报数据
            from collections import defaultdict
            by_year: dict[int, dict] = defaultdict(lambda: {"roe": None, "ocf": 0.0, "np": 0.0})

            for f in fins:
                period = getattr(f, "report_period", "")
                if not period or len(period) < 4:
                    continue
                try:
                    year = int(period[:4])
                except ValueError:
                    continue
                # Q4 年报优先覆盖任意期数据
                is_q4 = "Q4" in period or "12-31" in str(getattr(f, "report_date", ""))
                if is_q4 or by_year[year]["roe"] is None:
                    if getattr(f, "roe", None) is not None:
                        by_year[year]["roe"] = f.roe
                # 累计经营现金流和净利润（各期加总）
                if getattr(f, "operating_cash_flow", None) is not None:
                    by_year[year]["ocf"] += f.operating_cash_flow
                if getattr(f, "net_profit", None) is not None:
                    by_year[year]["np"] += f.net_profit

            # 按年份排序，取最近 3 年
            sorted_years = sorted(by_year.keys())[-3:]
            roe_history = [by_year[y]["roe"] for y in sorted_years if by_year[y]["roe"] is not None]
            ocf_3y = sum(by_year[y]["ocf"] for y in sorted_years)
            np_3y = sum(by_year[y]["np"] for y in sorted_years)

            ctx["roe_history"] = roe_history
            ctx["operating_cash_flow_3y"] = ocf_3y
            ctx["net_profit_3y"] = np_3y

            # 尝试获取分红数据（妙想不可用时跳过）
            try:
                mx = agg.miaoxiang
                if mx is not None and not mx.is_exhausted():
                    dividend_3y = mx.get_dividend_3y(symbol)
                    if dividend_3y is not None:
                        ctx["dividend_3y"] = dividend_3y
            except Exception:
                pass

        except Exception as e:
            logger.debug("Failed to inject financial doctrine ctx for %s: %s", symbol, e)

    @staticmethod
    def _get_related_parties(symbol: str) -> list[dict]:
        """从 mx-data 获取个股关联方信息。"""
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            parties = agg.get_related_parties(symbol)
            return [p.model_dump() if hasattr(p, "model_dump") else p for p in parties]
        except Exception as e:
            logger.debug("Related parties unavailable for %s: %s", symbol, e)
        return []

    @staticmethod
    def _get_executive_context(symbol: str) -> dict:
        """获取个股高管数据上下文（增减持/履历/变动）。

        通过 DataAggregator 聚合器获取，走完整降级链：
        - trades:  mx-data → 东财 datacenter
        - profiles: mx-data → [DATA_GAP]（暂无免费降级源）
        - changes:  mx-data → 巨潮 cninfo 公告搜索
        """
        ctx = {"trades": [], "profiles": [], "changes": []}
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            ctx["trades"] = [t.model_dump() for t in agg.get_executive_trades(symbol)]
            ctx["profiles"] = [p.model_dump() for p in agg.get_executive_profiles(symbol)]
            ctx["changes"] = [c.model_dump() for c in agg.get_board_changes(symbol)]
        except Exception as e:
            logger.debug("Executive context unavailable for %s: %s", symbol, e)
        return ctx


    # ── P1: 批量诊断 ──────────────────────────────────────────────────

    def run_batch(
        self,
        symbols: list[str],
        names: list[str] | None = None,
        sectors: list[str] | None = None,
        skip_t0: bool = False,
        as_of_date: str = "",
    ) -> list[dict]:
        """批量运行全链路诊断，返回横向对比数据。

        Args:
            symbols: 股票代码列表
            names: 股票名称列表（可选）
            sectors: 赛道标签列表（可选）
            skip_t0: 跳过 T+0 日内分析
            as_of_date: 历史回测日期 (YYYY-MM-DD)

        Returns:
            [{"symbol", "name", "sector", "price", "pe", "roe_ann",
              "gross_margin", "val_score", "qual_score", "mom_score",
              "val_estimate", "cycle_score", "bottleneck_score",
              "raw_score", "alpha_score", "final_score", "rec",
              "doctrine_warns", "data_gaps"}, ...]
        """
        import time as _time
        results = []
        shared_macro = None
        shared_sentiment = None

        # ── 板块过滤 (P0) ──
        # 批量诊断前预加载投资者画像，过滤不可交易板块的标的。
        # 避免对 300xxx/688xxx 等未开通板块浪费 API 配额。
        board_ok = None
        board_name_lookup = {}
        try:
            from src.learner.preference.loader import InvestorPreferenceLoader
            from src.learner.preference.adapter import resolve_board_filter
            from src.learner.preference.model import get_board_from_symbol as _gbfs
            loader = InvestorPreferenceLoader()
            prefs = loader.load()
            board_ok = resolve_board_filter(prefs)
            accessible_names = [b.value for b in prefs.accessible_boards]
            logger.info(
                "批量诊断板块过滤: 可交易板块=%s, 候选标的=%d",
                accessible_names, len(symbols),
            )
        except Exception as e:
            logger.debug("板块过滤加载失败，放行全部标的: %s", e)

        # 共享上下文只获取一次
        try:
            shared_macro = self._get_macro_context()
        except Exception as e:
            logger.warning("共享宏观上下文获取失败: %s", e)

        try:
            from src.sentiment.engine import SentimentEngine
            se = SentimentEngine()
            shared_sentiment = se.detect()
        except Exception as e:
            logger.debug("共享情绪上下文获取失败: %s", e)

        for i, symbol in enumerate(symbols):
            name = names[i] if names and i < len(names) else ""
            sector = sectors[i] if sectors and i < len(sectors) else ""

            # 板块过滤
            if board_ok is not None and not board_ok(symbol):
                board = _gbfs(symbol) if _gbfs else None
                board_name = board.value if board else "未知板块"
                logger.info(
                    "⛔ 跳过 [%s/%s] %s %s: 板块 %s 不可交易",
                    i + 1, len(symbols), symbol, name, board_name,
                )
                results.append({
                    "symbol": symbol, "name": name or symbol, "sector": sector,
                    "final_score": 0, "rec": "BOARD_BLOCKED",
                    "blocked_by": [f"板块 {board_name} 未开通交易权限"],
                    "data_gaps": [],
                })
                continue

            logger.info("批量诊断 [%s/%s]: %s %s", i + 1, len(symbols), symbol, name)

            try:
                result = self.run(
                    symbol=symbol,
                    name=name,
                    market="SH" if symbol.startswith(("6", "9")) else "SZ",
                    macro=shared_macro,
                    skip_t0=skip_t0,
                    as_of_date=as_of_date,
                    selection_mode=True,
                )
            except Exception as e:
                logger.error("批量诊断 %s 失败: %s", symbol, e)
                results.append({
                    "symbol": symbol, "name": name or symbol, "sector": sector,
                    "final_score": 0, "rec": "ERROR",
                    "doctrine_warns": [f"管道异常: {str(e)[:60]}"],
                    "data_gaps": [],
                })
                continue

            # 提取关键维度评分
            verdict = result.verdict
            report = result.report

            val_score = getattr(report, "value_score", 50.0) if report else 50.0
            qual_score = getattr(report, "quality_score", 50.0) if report else 50.0
            mom_score = getattr(report, "momentum_score", 50.0) if report else 50.0
            val_estimate = getattr(report, "valuation_score", 50.0) if report else 50.0
            cycle_score = getattr(report, "cycle_score", 50.0) if report else 50.0

            # 瓶颈分
            bottleneck_score = 50.0
            if report and getattr(report, "bottleneck_analysis", None):
                bottleneck_score = float(
                    getattr(report.bottleneck_analysis, "bottleneck_score", 50.0) or 50.0
                )

            # 价格 & PE
            price = 0.0
            pe = 50.0
            try:
                quote = self.data.get_quote(symbol=symbol)
                if quote:
                    price = float(getattr(quote, "price", 0) or getattr(quote, "close", 0) or 0)
                    pe = float(getattr(quote, "pe_ttm", 0) or getattr(quote, "pe", 0) or 50)
            except Exception:
                pass

            # 财务
            roe_ann = 0.0
            gross_margin = 0.0
            try:
                fin = self.data.get_financials(symbol=symbol, count=1)
                if fin:
                    f0 = fin[0] if isinstance(fin, list) else fin
                    roe_raw = getattr(f0, "roe", 0) or 0
                    # 年化假设
                    roe_ann = float(roe_raw) * 4 if fin and len(fin) == 1 else float(roe_raw) * 2
                    gross_margin = float(getattr(f0, "gross_margin", 0) or 0)
            except Exception:
                pass

            # 军规触发
            doctrine_warns = []
            if result.blocked_by:
                doctrine_warns.extend(result.blocked_by)
            if result.warnings:
                doctrine_warns.extend(result.warnings[:3])

            # 数据缺口
            data_gaps = []
            if report and getattr(report, "data_gaps", None):
                data_gaps = report.data_gaps[:5]

            results.append({
                "symbol": symbol,
                "name": name or result.name or symbol,
                "sector": sector,
                "price": price,
                "pe": pe,
                "roe_ann": round(roe_ann, 1),
                "gross_margin": round(gross_margin, 1),
                "val_score": round(val_score, 1),
                "qual_score": round(qual_score, 1),
                "mom_score": round(mom_score, 1),
                "val_estimate": round(val_estimate, 1),
                "cycle_score": round(cycle_score, 1),
                "bottleneck_score": round(bottleneck_score, 1),
                "raw_score": round(getattr(verdict, "score", 50.0) if verdict else 50.0, 1),
                "alpha_score": round(
                    getattr(result, "alpha_profile", None).alpha_score
                    if getattr(result, "alpha_profile", None) else 50.0, 1
                ),
                "final_score": round(
                    getattr(verdict, "score", 50.0) if verdict else 50.0, 1
                ),
                "rec": getattr(verdict, "recommendation", "HOLD") if verdict else "HOLD",
                "doctrine_warns": doctrine_warns,
                "data_gaps": data_gaps,
            })

            # 批量模式下不逐支刷屏，只打一行摘要
            logger.info(
                "  → %s: %.0f分 %s",
                symbol,
                getattr(verdict, "score", 0) if verdict else 0,
                getattr(verdict, "recommendation", "?") if verdict else "?",
            )

        return results


def _build_financial_display_data(ctx: dict) -> dict:
    """从 doctrine ctx 中提取财务数据用于军规输出展示。"""
    data: dict = {}
    roe_history = ctx.get("roe_history", [])
    if roe_history and len(roe_history) >= 3:
        data["roe_history"] = roe_history
    ocf = ctx.get("operating_cash_flow_3y", 0.0)
    np_ = ctx.get("net_profit_3y", 0.0)
    if np_ > 0:
        data["ocf_np_ratio"] = ocf / np_
    dividend = ctx.get("dividend_3y", 0.0) if ctx.get("dividend_3y") else None
    if np_ > 0 and dividend is not None:
        data["dividend_payout_ratio"] = dividend / np_ if np_ > 0 else None
    # 标记财务数据是否全部缺失
    if (not roe_history or len(roe_history) < 3) and np_ <= 0:
        data["_financial_data_missing"] = True
    return data


def _ni_to_dict(item) -> dict:
    """将 NewsItem 或 dict 转为 dict。"""
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "__dict__"):
        return {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
    return {"title": str(item), "content": "", "source": "", "date": ""}


def _flatten_news_context(news_ctx: dict | list | None) -> list[dict]:
    """将新的 dict 格式 news_context 展平为 list[dict]，兼容旧代码。

    新的 dict 格式包含多个通道：news, announcements, research_reports,
    flash_24x7, kuaicha_news, last30days。
    """
    if news_ctx is None:
        return []
    if isinstance(news_ctx, list):
        return news_ctx
    # dict 格式：合并所有通道
    all_items = []
    for channel in ("news", "announcements", "research_reports",
                     "flash_24x7", "kuaicha_news", "last30days"):
        all_items.extend(news_ctx.get(channel, []))
    return all_items


def _detect_major_positive_news(news_context: list | dict | None) -> bool:
    """检测新闻上下文中是否包含重大利好关键词（供 r014 军规使用）。

    支持旧 list 格式和新 dict 格式。
    """
    items = _flatten_news_context(news_context)
    POSITIVE_KW = [
        "重大合同", "中标", "业绩预增", "利润大增",
        "资产注入", "重组", "借壳", "收购",
        "重大突破", "获批", "政策利好",
    ]
    for item in items:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        if any(kw in text for kw in POSITIVE_KW):
            return True
    return False


def _perspective_to_dict(ps) -> dict:
    """将 PerspectiveScore 转为可序列化 dict。"""
    return {
        "perspective": ps.perspective.value if hasattr(ps.perspective, "value") else str(ps.perspective),
        "score": ps.score,
        "confidence": ps.confidence,
        "verdict": ps.verdict,
        "one_line_thesis": ps.one_line_thesis,
        "methodology": getattr(ps, "methodology", ""),
        "key_concern": ps.key_concern,
        "bull_points": getattr(ps, "bull_points", [])[:4],
        "bear_points": getattr(ps, "bear_points", [])[:4],
        "sub_scores": ps.sub_scores,
        "evidence": ps.evidence[:5],
        "unique_insight": ps.unique_insight,
        "questions": ps.questions_to_ask[:3],
        "qa_pairs": getattr(ps, "qa_pairs", [])[:3],  # 问题+回答对
    }


# ── 精简终端输出函数 (每段必出，但只出关键信息) ──────────────────

CN_COMPACT = {
    "emerging": "萌芽期", "spreading": "扩散期", "consensus": "共识期",
    "crowded": "拥挤期", "fading": "消退期", "dormant": "休眠期",
    "polarized": "严重对立", "divided": "存在分歧",
    "PANIC": "恐慌", "EXTREME": "极度恐慌", "NORMAL": "正常", "GREED": "贪婪",
    "kelly": "凯利", "linear_fallback": "线性回退", "negative_expectation": "负期望",
}


