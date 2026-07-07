# -*- coding: utf-8 -*-
"""编排器 — 画像→军规→L0→L1→L2→L3→L4 全链路。

Phase 3: 注入 MacroRegime, NorthboundProfile, DominanceProfile,
         EarningsRevisionFactor, Topic 生命周期调整。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
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

from .l0_gate import L0Gate
from .l1_analyze import AnalysisReport, L1Analyzer
from .l2_judge import L2Judge, Verdict
from .l3_trade import L3Trader, TradeSignal
from .l4_risk import L4RiskOfficer, RiskCheck
from .guardrails import GuardrailEnforcer, GuardrailViolation
from .game_theory_analyzer import GameTheoryAnalyzer, GameTheoryProfile
from .investor_mental_model import InvestorMentalModelAnalyzer, InvestorMentalModelFit
from .perspective_engine import PerspectiveAnalyzer
from .anti_bias import AntiBiasEngine
from .verdict_enforcer import VerdictEnforcer
from .mental_model_matcher import MentalModelMatcher

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
    report: Optional[AnalysisReport] = None
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
    cross_validated: bool = False
    # CogAlpha: 多 Agent 质量审查报告
    quality_report: Optional[dict] = None
    # 军规审查结果 (Phase 0)
    doctrine_result: Optional[dict] = None
    # 投资者画像状态
    using_default_profile: bool = False  # 是否使用系统默认画像（未自定义）
    created_at: datetime = field(default_factory=datetime.now)


class Orchestrator:
    """多层路由编排器。

    流程: 军规 → L0 → L1 → 质量审查 → 博弈论 → 投资思维模型 → L2 → L3 → L4

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
        self.l0 = L0Gate()
        self.l1 = L1Analyzer()
        self.l2 = L2Judge()
        # Phase 5: 注入 KellyPositionSizer（默认 half-Kelly=0.5）
        self.trade_tracker = TradeTracker()
        self.kelly_sizer = KellyPositionSizer(
            self.trade_tracker, default_kelly_fraction=0.5,
        )
        self.l3 = L3Trader(kelly_sizer=self.kelly_sizer)
        self.l4 = L4RiskOfficer()
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

    def run(
        self,
        symbol: str,
        market: str = "SH",
        name: str = "",
        macro: Optional[dict] = None,
        portfolio: Optional[dict] = None,
        strategy_version: str = "",
        strategy_params: Optional[dict] = None,
    ) -> OrchestratorResult:
        """执行全链路分析。"""
        result = OrchestratorResult(
            symbol=symbol, name=name,
            strategy_version=strategy_version,
            strategy_params=strategy_params or {},
        )

        # Step 0: 获取行情数据（双源交叉验证）
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

        # 加载投资者偏好
        investor, result.using_default_profile = self._get_investor_prefs()
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
            except Exception as e:
                logger.debug("Failed to resolve investor preferences: %s", e)

        # Step 1: 军规门禁
        ctx = {"stock_name": name, **(portfolio or {})}
        if investor is not None:
            ctx["tier"] = investor.tier.value
            ctx["max_single_pct"] = investor.position_limits.max_single_pct
            ctx["portfolio_drawdown_pct"] = investor.position_limits.portfolio_drawdown_pct
        doctrine_result = self.doctrine.check(symbol, ctx, enabled_rules=enabled_rules)
        if not doctrine_result.passed:
            result.passed = False
            result.blocked_by = [r.name for r in doctrine_result.blocked_by]
            result.warnings = [r.name for r in doctrine_result.warnings]
            return result
        result.warnings = [r.name for r in doctrine_result.warnings]
        # 保存完整军规结果供格式化器使用
        result.doctrine_result = {
            "passed": doctrine_result.passed,
            "total_rules": len(doctrine_result.blocked_by) + len(doctrine_result.warnings) + len(doctrine_result.infos),
            "blocked": [{"id": r.id, "name": r.name, "severity": r.severity.value, "description": r.description} for r in doctrine_result.blocked_by],
            "warnings": [{"id": r.id, "name": r.name, "severity": r.severity.value, "description": r.description} for r in doctrine_result.warnings],
            "infos": [{"id": r.id, "name": r.name, "severity": r.severity.value, "description": r.description} for r in doctrine_result.infos],
        }

        # Step 2: L0 保安
        gate_ctx = {
            "is_limit_up": False,
            "is_limit_down": False,
            "is_suspended": False,
            "listing_days": 365,
        }
        gate_result = self.l0.check(symbol, name, gate_ctx)
        result.gate_status = gate_result.status.value
        if gate_result.status.value == "REJECTED":
            result.passed = False
            result.blocked_by = gate_result.flags
            return result

        # ---- Phase 3: 增强上下文 ----
        macro_regime = self._get_macro_regime()
        nb_profile = self._get_northbound_profile()
        earnings_factor = self._get_earnings_revision(symbol)
        topic_adj = self._get_topic_adjustments()

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
        )

        # ---- V4 妙想增强: 资讯上下文 + 关联关系 ----
        news_context = self._get_news_context(symbol, name)
        related_parties = self._get_related_parties(symbol)
        executive = self._get_executive_context(symbol)

        # Phase: 财政政策 + 政策跟踪信号
        fiscal_regime = self._get_fiscal_regime()
        policy_signals = self._get_policy_signals()

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
        alpha_profile = self._get_alpha_profile(symbol, name, news_context)
        result.alpha_profile = alpha_profile

        # Step 3: L1 分析师
        # 使用真实行情 + 财务数据（转换为 dict 以兼容 L1）
        fin_list = [f.model_dump() for f in self.data.get_financials(symbol, market, count=4)]
        sentiment_dict = self._get_sentiment(nb_profile)
        report = self.l1.analyze(
            symbol, name,
            quote_dict, fin_list,
            enriched_macro,
            sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            earnings_factor=earnings_factor,
            alpha_profile=alpha_profile,  # Phase 4: Alpha Lens 注入
            executive=executive,         # V4: 高管数据注入
            valuation_result=valuation_result,  # Phase 5: 估值结果
            cycle_analysis=cycle_analysis,      # Phase 5: 周期分析
        )
        result.report = report
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

        # Phase 1: L1 护栏检查
        l1_violations = self.enforcer.enforce(
            stage="L1",
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

        # Phase 6+: Munger 思维模型匹配
        matched_models = self.mental_model_matcher.match_models(
            symbol, name, sector="", report=report,
        )
        report.mental_models = matched_models
        result.mental_models = matched_models
        # Munger 思维模型匹配 — 分析解释
        if matched_models:
            report.source_citations.append(make_citation(
                provider="mental_model_matcher", field="munger_mental_models",
                data_type="analyst_report",
                source_tier="T2", nature="interpretation",
                confidence=0.65,
            ))

        # CogAlpha: 多 Agent 质量审查 (数据新鲜度/一致性/泄露/可解释性/安全)
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

        # Phase 6+: 反偏见 — 红线检查（L2 前）
        red_line_report = self.anti_bias_engine.check_red_lines(
            quote=quote_dict, financials=fin_list, executive=executive,
        )
        result.red_lines = red_line_report.triggered_lines
        if red_line_report.any_triggered:
            result.warnings.extend(
                [f"红线 {line}: 触发" for line in red_line_report.triggered_lines]
            )

        # Phase 1+: 信源交叉验证 guard — T1+ 来源不足则阻止进入 L2
        t1_plus_count = sum(1 for sc in report.source_citations if getattr(sc, "is_t1_or_above", False))
        if t1_plus_count < 2:
            result.passed = False
            result.blocked_by.append(
                f"信源交叉验证不足：T1+ 来源 < 2 (当前 {t1_plus_count})"
            )
            return result

        # Step 4: L2 法官
        verdict = self.l2.judge(report, topic_adj=topic_adj, weights_override=weights)
        result.verdict = verdict
        if verdict.confidence < L2Judge.MIN_CONFIDENCE:
            result.passed = False
            result.blocked_by.append(f"置信度不足 ({verdict.confidence:.2f} < {L2Judge.MIN_CONFIDENCE})")
            return result

        # Phase 1: L2 护栏检查
        l2_violations = self.enforcer.enforce(
            stage="L2",
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

        # Step 5: L3 交易员
        effective_macro_cap = 0.80 * risk_mult
        signal = self.l3.generate_signal(
            verdict,
            macro_cap=effective_macro_cap,
            position_limits=position_limits,
            risk_multiplier=risk_mult,
            name=name,
            extra=quote.dict() if quote else {},
        )
        result.signal = signal

        # Phase 1: L3 护栏检查
        l3_violations = self.enforcer.enforce(
            stage="L3",
            source_citations=signal.source_citations,
            confidence=signal.confidence,
        )
        result.violations.extend(l3_violations)
        if self.enforcer.is_blocked(l3_violations):
            result.passed = False
            result.blocked_by.extend(self.enforcer.get_warnings(l3_violations))

        # Step 6: L4 风控官
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
        # Phase 6: 博弈论风险注入 L4
        if gt_profile:
            enriched_portfolio["game_theory_risks"] = gt_profile.risks
            enriched_portfolio["dominant_player"] = gt_profile.dominant_player
            enriched_portfolio["market_regime"] = gt_profile.market_regime
        if imm_fit:
            enriched_portfolio["mental_model_bias_flags"] = imm_fit.bias_flags
            enriched_portfolio["mental_model_warnings"] = imm_fit.warnings

        risk = self.l4.check(signal, enriched_portfolio, position_limits=position_limits)
        result.risk = risk

        # Phase 1: L4 护栏检查
        l4_violations = self.enforcer.enforce(
            stage="L4",
            source_citations=risk.source_citations,
        )
        result.violations.extend(l4_violations)

        result.passed = True
        return result

    def quick_check(self, symbol: str, name: str = "") -> OrchestratorResult:
        """快速检查（仅军规 + L0，不做完整分析）。"""
        result = OrchestratorResult(symbol=symbol, name=name)
        doctrine_result = self.doctrine.check(symbol, {"stock_name": name})
        if not doctrine_result.passed:
            result.passed = False
            result.blocked_by = [r.name for r in doctrine_result.blocked_by]
            return result
        gate_result = self.l0.check(symbol, name)
        result.gate_status = gate_result.status.value
        result.passed = gate_result.status.value != "REJECTED"
        if not result.passed:
            result.blocked_by = gate_result.flags
        return result

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
        """Analysis Worker: 军规→L0→L1→L2 (只读)。

        映射到 analysis-worker Agent 的职责边界。
        返回 verdict 或 blocked 信息。
        """
        quote = data.get("quote")
        portfolio = data.get("portfolio", {})

        # 投资者偏好
        investor, result.using_default_profile = self._get_investor_prefs()
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

        # L0 门禁
        gate_ctx = {
            "is_limit_up": False, "is_limit_down": False,
            "is_suspended": False, "listing_days": 365,
        }
        gate_result = self.l0.check(symbol, name, gate_ctx)
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

        # L1
        quote_dict = {"pe_percentile": 40, "northbound": 1}
        fin_list = [{"roe": 15}]
        sentiment_dict = self._get_sentiment(nb_profile)
        report = self.l1.analyze(
            symbol, name, quote_dict, fin_list,
            enriched_macro, sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            earnings_factor=earnings_factor,
            executive=executive,
        )

        # L1 护栏
        l1_violations = self.enforcer.enforce(
            stage="L1",
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

        # L2 (with investor preference weights)
        weights = None
        if investor is not None:
            try:
                from src.learner.preference.adapter import resolve_weights
                weights = resolve_weights(investor)
            except Exception:
                pass
        verdict = self.l2.judge(report, topic_adj=topic_adj, weights_override=weights)

        # L2 护栏
        l2_violations = self.enforcer.enforce(
            stage="L2",
            source_citations=verdict.source_citations,
            confidence=verdict.confidence,
        )

        if verdict.confidence < L2Judge.MIN_CONFIDENCE:
            return {
                "blocked": True,
                "blocked_by": [f"置信度不足 ({verdict.confidence:.2f} < {L2Judge.MIN_CONFIDENCE})"],
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
        """Signal Writer: L3→L4→护栏审查 (唯一写权限)。

        映射到 signal-writer Agent 的职责边界。
        """
        verdict = analysis_result.get("verdict")
        if verdict is None:
            return {"blocked": True, "blocked_by": ["无裁决结果"]}

        # L3 (with investor preference limits)
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
        signal = self.l3.generate_signal(
            verdict,
            macro_cap=0.80 * risk_mult,
            position_limits=position_limits,
            risk_multiplier=risk_mult,
        )
        l3_violations = self.enforcer.enforce(
            stage="L3",
            source_citations=signal.source_citations,
            confidence=signal.confidence,
        )

        # L4 (with investor preference limits)
        risk = self.l4.check(signal, portfolio, position_limits=position_limits)
        l4_violations = self.enforcer.enforce(
            stage="L4",
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

    def _run_pipeline_parallel(
        self,
        symbol: str,
        market: str = "SH",
        name: str = "",
        macro: Optional[dict] = None,
        portfolio: Optional[dict] = None,
    ) -> OrchestratorResult:
        """并行版分析管道：独立数据获取/分析器并发，L2/L3/L4 顺序执行。"""
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
        earnings_factor = gathered.get("earnings")
        executive = gathered.get("executive")

        # ---- Phase 2: 并行分析器（无写操作） ----
        investor, result.using_default_profile = self._get_investor_prefs()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self.gt_analyzer.analyze, symbol, name, quote.market_cap if quote else None, ""): "game_theory",
                pool.submit(self.imm_analyzer.analyze, symbol, name, investor, portfolio, "", quote.market_cap if quote else None, quote.change_pct if quote else None): "mental_model",
                pool.submit(self.perspective_analyzer.debate, symbol, name, None, quote_dict, fin_list): "debate",
                pool.submit(self.mental_model_matcher.match_models, symbol, name, "", None): "munger_models",
            }
            analyses: dict = {}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    analyses[key] = future.result()
                except Exception as e:
                    logger.debug("Parallel analysis %s failed: %s", key, e)
                    analyses[key] = None

        # ---- Phase 3: 顺序 L1→质量→L2→L3→L4 ----
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

        report = self.l1.analyze(
            symbol, name, quote_dict, fin_list, enriched_macro, {"level": "NORMAL"},
            macro_regime=macro_regime, northbound_profile=nb_profile,
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

        verdict = self.l2.judge(report)
        result.verdict = verdict
        if verdict.confidence < L2Judge.MIN_CONFIDENCE:
            result.passed = False
            result.blocked_by.append(f"置信度不足 ({verdict.confidence:.2f} < {L2Judge.MIN_CONFIDENCE})")
            return result

        signal = self.l3.generate_signal(verdict, macro_cap=0.80, name=name, extra=quote_dict)
        result.signal = signal
        risk = self.l4.check(signal, portfolio or {})
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
        news_context: list[dict],
    ) -> AlphaProfile:
        """Phase 4: 计算 Alpha Profile。

        综合信息来源层级、共识-现实缺口、叙事生命周期三个维度，
        回答「我比别人多知道什么？」
        """
        # 从资讯上下文中提取来源信息
        news_sources: list[str] = []
        market_narrative_parts: list[str] = []
        narrative_intensity = 0.0
        sentiment = "NEUTRAL"

        for item in (news_context or []):
            title = item.get("title", "")
            source = item.get("source", "")
            content = item.get("content", "")[:200] if item.get("content") else ""

            news_sources.append(f"{source}: {title}")
            market_narrative_parts.append(title)

            # 估算叙事强度：资讯数量越多 → 叙事越强
            narrative_intensity = min(1.0, len(news_context) / 10)

        # 从 symbol 和 name 推断基本信息
        market_narrative = (
            f"关于 {name}({symbol}) 的市场讨论: "
            + ("; ".join(market_narrative_parts[:3]))
            if market_narrative_parts else ""
        )

        return self.alpha_lens.analyze(
            symbol=symbol,
            news_sources=news_sources,
            market_narrative=market_narrative,
            narrative_intensity=narrative_intensity,
            sentiment_extreme=sentiment,
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
    def _get_northbound_profile():
        """获取多维北向资金画像。"""
        try:
            from src.game_theory.northbound import NorthboundAnalyzer
            analyzer = NorthboundAnalyzer()
            return analyzer.analyze()
        except Exception as e:
            logger.debug("Northbound profile unavailable: %s", e)
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
    ):
        """执行多维估值分析。"""
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
            )
        except Exception as e:
            logger.debug("Valuation analysis unavailable for %s: %s", symbol, e)
        return None

    @staticmethod
    def _get_investor_prefs():
        """加载投资者偏好画像，同时检测是否为默认配置。"""
        try:
            from src.learner.preference.loader import InvestorPreferenceLoader
            loader = InvestorPreferenceLoader()
            prefs = loader.load()
            # 检测是否为默认配置（能力圈为空或只有示例条目）
            coc = prefs.circle_of_competence.industries
            is_default = (not coc or len(coc) <= 3) and prefs.tier.value == "beginner"
            return prefs, is_default
        except Exception as e:
            logger.debug("Investor preferences unavailable: %s", e)
        return None, True

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
            }
        except Exception as e:
            logger.debug("Sentiment detection unavailable: %s", e)
        return {"level": "NORMAL"}

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
            return tracker.get_recent_signals()
        except Exception as e:
            logger.debug("Policy tracker unavailable: %s", e)
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
    def _get_news_context(symbol: str, name: str) -> list[dict]:
        """从 mx-search 获取个股最新资讯上下文。"""
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            mx = agg.miaoxiang
            if mx is None:
                return []
            # 合并公告 + 研报 + 新闻
            items = mx.search_news(f"{name} {symbol} 最新公告 研报 新闻", max_results=5)
            return [item.model_dump() if hasattr(item, "model_dump") else item for item in items]
        except Exception as e:
            logger.debug("News context unavailable for %s: %s", symbol, e)
        return []

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
        """从 mx-data 获取个股高管数据上下文（增减持/履历/变动）。"""
        ctx = {"trades": [], "profiles": [], "changes": []}
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            mx = agg.miaoxiang
            if mx is None:
                return ctx
            ctx["trades"] = [t.model_dump() for t in mx.get_executive_trades(symbol)]
            ctx["profiles"] = [p.model_dump() for p in mx.get_executive_profiles(symbol)]
            ctx["changes"] = [c.model_dump() for c in mx.get_board_changes(symbol)]
        except Exception as e:
            logger.debug("Executive context unavailable for %s: %s", symbol, e)
        return ctx


def _perspective_to_dict(ps) -> dict:
    """将 PerspectiveScore 转为可序列化 dict。"""
    return {
        "perspective": ps.perspective.value if hasattr(ps.perspective, "value") else str(ps.perspective),
        "score": ps.score,
        "confidence": ps.confidence,
        "verdict": ps.verdict,
        "one_line_thesis": ps.one_line_thesis,
        "key_concern": ps.key_concern,
        "sub_scores": ps.sub_scores,
        "evidence": ps.evidence[:5],
        "unique_insight": ps.unique_insight,
        "questions": ps.questions_to_ask[:3],
    }
