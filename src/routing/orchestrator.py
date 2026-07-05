# -*- coding: utf-8 -*-
"""编排器 — 画像→军规→L0→L1→L2→L3→L4 全链路。

Phase 3: 注入 MacroRegime, NorthboundProfile, DominanceProfile,
         EarningsRevisionFactor, Topic 生命周期调整。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.aggregator import DataAggregator
from src.doctrine.checker import DoctrineChecker

from .l0_gate import L0Gate
from .l1_analyze import AnalysisReport, L1Analyzer
from .l2_judge import L2Judge, Verdict
from .l3_trade import L3Trader, TradeSignal
from .l4_risk import L4RiskOfficer, RiskCheck
from .guardrails import GuardrailEnforcer, GuardrailViolation

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
    # Phase 1: guardrail violations
    violations: list[GuardrailViolation] = field(default_factory=list)
    # 投资者偏好
    investor_prefs_applied: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class Orchestrator:
    """5 层路由编排器。

    流程: 军规 → L0 → L1 → L2 → L3 → L4

    用法:
        orch = Orchestrator()
        result = orch.run("600519", "SH")
        if result.passed:
            print(f"建议: {result.signal.action} {result.risk.adjusted_weight:.1%}")

    Phase 3 增强: 自动注入 MacroRegime / NorthboundProfile / Topic 生命周期。
    """

    def __init__(self):
        self.data = DataAggregator()
        self.doctrine = DoctrineChecker()
        self.l0 = L0Gate()
        self.l1 = L1Analyzer()
        self.l2 = L2Judge()
        self.l3 = L3Trader()
        self.l4 = L4RiskOfficer()
        self.enforcer = GuardrailEnforcer()  # Phase 1: 护栏执行器

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

        # Step 0: 获取行情数据
        quote = self.data.get_quote(symbol, market)
        if quote is None:
            result.passed = False
            result.blocked_by.append("数据不可用")
            return result

        if not name:
            name = quote.name
            result.name = name

        # 加载投资者偏好
        investor = self._get_investor_prefs()
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

        # ---- V4 妙想增强: 资讯上下文 + 关联关系 ----
        news_context = self._get_news_context(symbol, name)
        related_parties = self._get_related_parties(symbol)

        # 增强宏观 dict
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
            result.macro_regime_info = {
                "quadrant": macro_regime.quadrant.value,
                "confidence": macro_regime.confidence,
            }

        # Step 3: L1 分析师
        quote_dict = {
            "pe_percentile": 40,  # placeholder
            "northbound": 1,
        }
        fin_list = [{"roe": 15}]  # placeholder
        sentiment_dict = {"level": "NORMAL"}
        report = self.l1.analyze(
            symbol, name,
            quote_dict, fin_list,
            enriched_macro,
            sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            earnings_factor=earnings_factor,
            news_context=news_context,  # V4: 妙想资讯上下文
        )
        result.report = report

        # Phase 1: L1 护栏检查
        l1_violations = self.enforcer.enforce(
            stage="L1",
            source_citations=report.source_citations,
            confidence=report.confidence,
        )
        result.violations.extend(l1_violations)

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

        # Step 5: L3 交易员
        effective_macro_cap = 0.80 * risk_mult
        signal = self.l3.generate_signal(
            verdict,
            macro_cap=effective_macro_cap,
            position_limits=position_limits,
            risk_multiplier=risk_mult,
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
        investor = self._get_investor_prefs()
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
        sentiment_dict = {"level": "NORMAL"}
        report = self.l1.analyze(
            symbol, name, quote_dict, fin_list,
            enriched_macro, sentiment_dict,
            macro_regime=macro_regime,
            northbound_profile=nb_profile,
            earnings_factor=earnings_factor,
        )

        # L1 护栏
        l1_violations = self.enforcer.enforce(
            stage="L1",
            source_citations=report.source_citations,
            confidence=report.confidence,
        )

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
    def _get_investor_prefs():
        """加载投资者偏好画像。"""
        try:
            from src.learner.preference.loader import InvestorPreferenceLoader
            loader = InvestorPreferenceLoader()
            return loader.load()
        except Exception as e:
            logger.debug("Investor preferences unavailable: %s", e)
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
