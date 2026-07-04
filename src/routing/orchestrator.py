# -*- coding: utf-8 -*-
"""编排器 — 画像→军规→L0→L1→L2→L3→L4 全链路。"""

from __future__ import annotations

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
    created_at: datetime = field(default_factory=datetime.now)


class Orchestrator:
    """5 层路由编排器。

    流程: 军规 → L0 → L1 → L2 → L3 → L4

    用法:
        orch = Orchestrator()
        result = orch.run("600519", "SH")
        if result.passed:
            print(f"建议: {result.signal.action} {result.risk.adjusted_weight:.1%}")
    """

    def __init__(self):
        self.data = DataAggregator()
        self.doctrine = DoctrineChecker()
        self.l0 = L0Gate()
        self.l1 = L1Analyzer()
        self.l2 = L2Judge()
        self.l3 = L3Trader()
        self.l4 = L4RiskOfficer()

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

        # Step 1: 军规门禁
        ctx = {"stock_name": name, **(portfolio or {})}
        doctrine_result = self.doctrine.check(symbol, ctx)
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

        # Step 3: L1 分析师
        quote_dict = {
            "pe_percentile": 40,  # placeholder
            "northbound": 1,
        }
        fin_list = [{"roe": 15}]  # placeholder
        sentiment_dict = {"level": "NORMAL"}
        report = self.l1.analyze(symbol, name, quote_dict, fin_list, macro, sentiment_dict)
        result.report = report

        # Step 4: L2 法官
        verdict = self.l2.judge(report)
        result.verdict = verdict
        if verdict.confidence < L2Judge.MIN_CONFIDENCE:
            result.passed = False
            result.blocked_by.append(f"置信度不足 ({verdict.confidence:.2f} < {L2Judge.MIN_CONFIDENCE})")
            return result

        # Step 5: L3 交易员
        signal = self.l3.generate_signal(verdict)
        result.signal = signal

        # Step 6: L4 风控官
        risk = self.l4.check(signal, portfolio)
        result.risk = risk

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
