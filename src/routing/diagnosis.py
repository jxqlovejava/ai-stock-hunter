# -*- coding: utf-8 -*-
"""多维诊断 — 多维度扫描（量化为主，AI 为辅）。

诊断维度:
  1. 宏观环境打分 (PMI/ERP/M1-M2/社融/LPR/DR007/货币信用象限)
  2. 量化因子扫描 (价值/质量/动量/盈利修正)
  3. 物理瓶颈分析 (供应链定位 + 瓶颈分类)
  4. 情绪信号检测
  5. 多空双视角
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation, make_data_gap_citation
from src.industry.bottleneck import BottleneckAnalysis, BottleneckType
from src.industry.supply_chain import classify_stock
from src.alpha.schema import AlphaProfile
from src.routing.game_theory_analyzer import GameTheoryProfile
from src.routing.investor_mental_model import InvestorMentalModelFit


@dataclass
class DiagnosisReport:
    """多维诊断报告。"""
    symbol: str
    name: str
    macro_score: float = 50.0
    value_score: float = 50.0
    quality_score: float = 50.0
    momentum_score: float = 50.0
    earnings_revision_score: float = 50.0  # Phase 3: 盈利修正因子
    bottleneck_analysis: Optional[BottleneckAnalysis] = None  # cyberagent 瓶颈分析
    sentiment_signal: str = "NEUTRAL"
    alpha_profile: Optional[AlphaProfile] = None  # Phase 4: Alpha Lens 视角
    executive_score: float = 50.0     # V4: 高管因子评分
    executive_risks: list[str] = field(default_factory=list)  # V4: 高管风险提示
    # Phase 5: 估值 + 周期
    valuation_score: float = 50.0        # 多维估值综合评分
    valuation_analysis: Optional[object] = None  # ValuationResult DTO
    cycle_score: float = 50.0            # 经济周期友好度 0-100
    cycle_phase: str = ""                # 周期阶段名称
    cycle_analysis: Optional[object] = None  # CycleAnalysis DTO
    bull_case: str = ""
    bear_case: str = ""
    bottlenecks: list[str] = field(default_factory=list)
    upstream_risks: list[str] = field(default_factory=list)
    source_citations: list[SourceCitation] = field(default_factory=list)  # Phase 1: 数据溯源
    data_gaps: list[str] = field(default_factory=list)  # Phase 1: 数据缺口标记
    confidence: float = 0.7  # Phase 1: 综合信心度 0.0-1.0
    data_freshness: datetime = field(default_factory=datetime.now)  # Phase 1: 数据新鲜度
    created_at: datetime = field(default_factory=datetime.now)
    # Phase 6: 博弈论 + 投资思维模型
    game_theory_profile: Optional[GameTheoryProfile] = None
    investor_mental_model: Optional[InvestorMentalModelFit] = None
    # Phase 6+: AI Berkshire 四视角辩论
    debate_result: Optional[object] = None
    # Phase 6+: Munger 思维模型匹配
    mental_models: list[dict] = field(default_factory=list)


class DiagnosisEngine:
    """多维诊断引擎: 宏观/价值/质量/动量/估值/周期/情绪/高管 8+ 维度。"""

    def analyze(
        self,
        symbol: str,
        name: str,
        quote: Optional[dict] = None,
        financials: Optional[list] = None,
        macro: Optional[dict] = None,
        sentiment: Optional[dict] = None,
        macro_regime: Optional[object] = None,  # MacroRegime from src.macro
        northbound_profile: Optional[object] = None,  # NorthboundProfile
        earnings_factor: Optional[object] = None,  # EarningsRevisionFactor
        fiscal_regime: Optional[object] = None,  # FiscalRegime from src.macro
        alpha_profile: Optional[AlphaProfile] = None,  # Phase 4: Alpha Lens 视角
        executive: Optional[dict] = None,              # V4: 高管数据
        valuation_result: Optional[object] = None,     # Phase 5: ValuationResult
        cycle_analysis: Optional[object] = None,       # Phase 5: CycleAnalysis
    ) -> DiagnosisReport:
        report = DiagnosisReport(symbol=symbol, name=name)

        if macro:
            report.macro_score = self._score_macro(macro, macro_regime, fiscal_regime)

        if quote and financials:
            report.value_score = self._score_value(quote, valuation_result)
            report.quality_score = self._score_quality(financials, earnings_factor)
            report.momentum_score = self._score_momentum(quote, northbound_profile)
        else:
            # 财务数据不可用 — 标记 DATA_GAP，使用中性默认值
            if not financials:
                report.data_gaps = getattr(report, 'data_gaps', []) or []
                report.data_gaps.append("[DATA_GAP] 财务数据不可用 — 价值/质量/动量评分使用中性值 50，置信度大幅下调")
            if quote and not financials:
                # 仅有行情无财务：只能算动量
                report.momentum_score = self._score_momentum(quote, northbound_profile)

        # Phase 5: 估值评分（独立于 value_score）
        report.valuation_score = self._score_valuation(valuation_result)
        if valuation_result is not None:
            report.valuation_analysis = valuation_result

        # Phase 5: 周期评分
        report.cycle_score = self._score_cycle(cycle_analysis)
        if cycle_analysis is not None:
            report.cycle_phase = getattr(cycle_analysis, "phase", None)
            if hasattr(report.cycle_phase, "value"):
                report.cycle_phase = report.cycle_phase.value
            report.cycle_analysis = cycle_analysis

        if earnings_factor is not None:
            report.earnings_revision_score = self._get_revision_score(earnings_factor)

        # 🆕 物理瓶颈分析 (借鉴 cyberagent)
        report.bottleneck_analysis = self._analyze_bottleneck(symbol, name)

        if sentiment:
            report.sentiment_signal = sentiment.get("level", "NEUTRAL")

        # Phase 4: Alpha Lens 注入
        report.alpha_profile = alpha_profile

        # V4: 高管因子评分
        exec_result = self._score_executive(executive)
        report.executive_score = exec_result["score"]
        report.executive_risks = exec_result["risks"]
        if report.executive_risks:
            report.confidence = max(0.3, report.confidence - 0.05)

        report.bull_case = self._bull_case(name, quote, financials)
        report.bear_case = self._bear_case(name, quote, financials)

        # Phase 1: 填充数据溯源和信心度
        report.source_citations = self._collect_citations(quote, financials, macro, executive)
        report.confidence = self._calc_confidence(report, quote, financials)
        report.data_freshness = datetime.now()
        return report

    def _collect_citations(
        self,
        quote: dict | None,
        financials: list | None,
        macro: dict | None,
        executive: dict | None = None,
    ) -> list[SourceCitation]:
        """收集所有数据点的来源引用（T0-T3 分级），含 fact/interpretation/speculation 分类。"""
        citations: list[SourceCitation] = []
        if quote:
            provider = quote.get("_source", "mootdx")
            citations.append(make_citation(
                provider=provider, field="quote", data_type="realtime_quote",
                source_tier="T1" if provider in ("mootdx", "guosen") else "T2",
                nature="fact",
            ))
            # 记录交叉验证状态
            if quote.get("cross_validated"):
                citations.append(make_citation(
                    provider="miaoxiang" if quote.get("miaoxiang_source") else "mootdx",
                    field="cross_validated_quote", data_type="realtime_quote",
                    source_tier="T2", nature="fact",
                ))
            if quote.get("dispute"):
                citations.append(make_data_gap_citation(
                    provider="aggregator", field="quote_dispute",
                    reason="双源行情价格分歧 >5%",
                ))
        if financials:
            citations.append(make_citation(
                provider="mootdx", field="financials", data_type="financials",
                source_tier="T1", nature="fact",
            ))
        if macro:
            provider = macro.get("_source", "akshare")
            citations.append(make_citation(
                provider=provider, field="macro", data_type="macro_indicator",
                source_tier="T1" if provider in ("pboc", "mootdx") else "T2",
                nature="fact",
            ))
        if executive:
            citations.append(make_citation(
                provider="miaoxiang-data-executive", field="executive",
                data_type="executive", source_tier="T2", nature="fact",
            ))

        # 评分维度 — 基于原始数据的分析解释
        citations.append(make_citation(
            provider="l1_analyzer", field="l1_multi_dimension_scores",
            data_type="factor",
            source_tier="T2", nature="interpretation",
            confidence=0.75,
        ))

        # 多空观点 — 推测性前瞻分析
        citations.append(make_citation(
            provider="l1_analyzer", field="bull_case",
            data_type="analyst_report",
            source_tier="T3", nature="speculation",
            confidence=0.40,
        ))
        citations.append(make_citation(
            provider="l1_analyzer", field="bear_case",
            data_type="analyst_report",
            source_tier="T3", nature="speculation",
            confidence=0.40,
        ))

        # 瓶颈分析 — 基于供应链模型的解释
        citations.append(make_citation(
            provider="l1_analyzer", field="bottleneck_analysis",
            data_type="analyst_report",
            source_tier="T3", nature="speculation",
            confidence=0.45,
        ))

        return citations

    @staticmethod
    def _calc_confidence(
        report: DiagnosisReport,
        quote: dict | None,
        financials: list | None,
    ) -> float:
        """计算综合信心度, 基于数据完整性和评分分布。

        公式: 数据覆盖率 (0-1) * 0.4 + 评分稳定性 * 0.6
        """
        data_points = sum(1 for x in [quote, financials] if x)
        coverage = data_points / 2.0  # 最多 2 个数据源
        # 评分稳定性: 各维度评分离散度越小越稳定
        scores = [
            report.macro_score, report.value_score,
            report.quality_score, report.momentum_score,
            report.valuation_score, report.cycle_score,
        ]
        if len(scores) > 1:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            stability = max(0, 1.0 - variance / 2000)  # 方差越大稳定性越低
        else:
            stability = 0.5
        return round(coverage * 0.4 + stability * 0.6, 2)

    def _analyze_bottleneck(self, symbol: str, name: str) -> Optional[BottleneckAnalysis]:
        node = classify_stock(symbol)
        if node is None:
            return None
        analysis = BottleneckAnalysis(
            symbol=symbol, name=name,
            core_business=node.description,
            supply_chain_layer=node.layer,
            bottleneck_type=node.bottleneck_type,
            constraint_description=node.constraint or "",
        )
        score_map = {
            BottleneckType.OWNER: 100, BottleneckType.ADJACENT: 65,
            BottleneckType.DERIVATIVE: 35, BottleneckType.NONE: 10,
        }
        analysis.bottleneck_score = score_map.get(node.bottleneck_type, 0)
        return analysis

    def _score_macro(
        self, macro: dict, macro_regime: Optional[object] = None,
        fiscal_regime: Optional[object] = None,
    ) -> float:
        """宏观环境打分 v3 — 货币信用 + 财政政策双重视角。"""
        score = 50.0

        # ---- v1 基础信号 ----
        pmi = macro.get("pmi", 50)
        score += (pmi - 50) * 1.0
        erp = macro.get("erp", 4.0)
        score += (erp - 4.0) * 2.5

        # ---- v2 流动性信号 ----
        m1_m2_gap = macro.get("m1_m2_gap")
        if m1_m2_gap is not None:
            if m1_m2_gap > 3.0:
                score += 10
            elif m1_m2_gap > 0:
                score += 5
            elif m1_m2_gap < -2.0:
                score -= 10
            else:
                score -= 3

        sf_growth = macro.get("social_financing_growth")
        if sf_growth is not None:
            sf_trend = macro.get("sf_trend", "stable")
            if sf_trend == "accelerating":
                score += 8
            elif sf_trend == "decelerating":
                score -= 8

        lpr_direction = macro.get("lpr_direction", "stable")
        if lpr_direction == "falling":
            score += 5
        elif lpr_direction == "rising":
            score -= 5

        dr007_position = macro.get("dr007_position", "neutral")
        if dr007_position == "below_policy":
            score += 5
        elif dr007_position == "above_policy":
            score -= 5

        # ---- v2 货币信用象限修正 ----
        if macro_regime is not None:
            from src.macro.monetary_credit import Quadrant
            quadrant = getattr(macro_regime, "quadrant", None)
            if quadrant == Quadrant.EASY_MONEY_EASY_CREDIT:
                score += 15
            elif quadrant == Quadrant.EASY_MONEY_TIGHT_CREDIT:
                score += 5
            elif quadrant == Quadrant.TIGHT_MONEY_EASY_CREDIT:
                score -= 5
            elif quadrant == Quadrant.TIGHT_MONEY_TIGHT_CREDIT:
                score -= 15

        # ---- v3 财政政策修正 ----
        if fiscal_regime is not None:
            fiscal_score = getattr(fiscal_regime, "fiscal_score", 50)
            fiscal_stance = getattr(fiscal_regime, "fiscal_stance", "neutral")
            score = score * 0.85 + fiscal_score * 0.15
            if fiscal_stance == "expansionary":
                score += 3
            elif fiscal_stance == "tightening":
                score -= 3

        return max(0, min(100, score))

    def _score_value(self, quote: dict, valuation_result: Optional[object] = None) -> float:
        """价值评分：优先使用 ValuationAnalyzer 的 composite_score。

        当 valuation_result 可用时，使用其综合评分。
        回退到简单 PE 分位逻辑。
        """
        if valuation_result is not None:
            composite = getattr(valuation_result, "composite_score", None)
            if composite is not None:
                return float(composite)
        pe_pct = quote.get("pe_percentile", 50)
        return max(0, min(100, 100 - pe_pct))

    def _score_valuation(self, valuation_result: Optional[object] = None) -> float:
        """估值评分 = ValuationAnalyzer composite_score。"""
        if valuation_result is None:
            return 50.0
        return float(getattr(valuation_result, "composite_score", 50.0))

    def _score_cycle(self, cycle_analysis: Optional[object] = None) -> float:
        """周期评分 = CycleAnalyzer cycle_score。"""
        if cycle_analysis is None:
            return 50.0
        return float(getattr(cycle_analysis, "cycle_score", 50.0))

    @staticmethod
    def _score_executive(executive: Optional[dict] = None) -> dict:
        """V4: 高管因子评分（stub）。"""
        if not executive:
            return {"score": 50.0, "risks": []}
        return {"score": executive.get("average_score", 50.0), "risks": executive.get("red_flags", [])}

    def _score_quality(self, financials: list, earnings_factor: Optional[object] = None) -> float:
        """质量评分（增强版）：ROE + 盈利修正因子。"""
        if not financials:
            return 50.0
        roe = financials[-1].get("roe", 10) if isinstance(financials[-1], dict) else 10
        roe_score = max(0, min(100, roe * 4))

        # Blend with earnings revision if available
        if earnings_factor is not None:
            revision_score = self._get_revision_score(earnings_factor)
            return roe_score * 0.6 + revision_score * 0.4

        return roe_score

    def _score_momentum(self, quote: dict, northbound_profile: Optional[object] = None) -> float:
        """动量评分：北向资金(市场级) + 个股涨跌幅(个股级) 混合。"""
        nb_score = 50.0
        if northbound_profile is not None:
            nb_score = float(getattr(northbound_profile, "score", 50.0))

        # 个股自身动量：用当日涨跌幅作为短期动量代理
        change_pct = quote.get("change_pct", 0) or 0.0
        stock_momentum = 50.0 + min(max(change_pct * 5, -30), 30)

        # 50% 市场北向 + 50% 个股涨跌 — 确保个股间有区分度
        return nb_score * 0.5 + stock_momentum * 0.5

    @staticmethod
    def _get_revision_score(earnings_factor: object) -> float:
        """Extract revision score from EarningsRevisionFactor object."""
        score = getattr(earnings_factor, "revision_score", None)
        if score is not None:
            return float(score)
        return 50.0

    @staticmethod
    def _score_executive(executive: Optional[dict]) -> dict:
        """高管因子评分 (0-100)，基准 50 分。

        三个子维度:
          1. 增减持信号 (±25) — 高管买卖方向与力度
          2. 董监高稳定性 (0 ~ -20) — 非正常变动扣分
          3. 高管背景质量 (-5 ~ +10) — 履历数据可得性

        Returns:
            {"score": float, "risks": list[str]}
        """
        if not executive:
            return {"score": 50.0, "risks": ["高管数据不可用"]}

        risks: list[str] = []
        score = 50.0
        trades: list = executive.get("trades", [])
        changes: list = executive.get("changes", [])
        profiles: list = executive.get("profiles", [])

        # 1. 增减持信号 (±25)
        net_buy = sum(t.get("volume", 0) or 0 for t in trades if t.get("trade_type") == "buy")
        net_sell = sum(t.get("volume", 0) or 0 for t in trades if t.get("trade_type") == "sell")
        if net_sell > net_buy and net_sell > 0:
            delta = min(25, (net_sell - net_buy) / 10000)
            score -= delta
            risks.append(f"高管近期净减持 {net_sell - net_buy:,} 股")
        elif net_buy > net_sell and net_buy > 0:
            delta = min(25, (net_buy - net_sell) / 10000)
            score += delta

        # 2. 董监高稳定性 (0 ~ -20)
        abnormal = [c for c in changes if "任期届满" not in c.get("reason", "")]
        if abnormal:
            penalty = min(20, len(abnormal) * 10)
            score -= penalty
            for c in abnormal:
                name = c.get("person_name", "")
                reason = c.get("reason", "原因未知")
                risks.append(f"董监高变动: {name} {reason}")

        # 3. 高管背景质量 (-5 ~ +10)
        if profiles:
            score += 5
            # 检查是否有长期任职高管(≥5年)
            long_tenure = any(
                p.get("tenure_start", "") and "201" in str(p.get("tenure_start", ""))
                or "2020" in str(p.get("tenure_start", ""))
                or "2021" in str(p.get("tenure_start", ""))
                for p in profiles
            )
            if long_tenure:
                score += 5
        else:
            score -= 5
            risks.append("高管背景信息缺失")

        return {"score": max(0.0, min(100.0, score)), "risks": risks}

    def _bull_case(self, name: str, quote: dict | None, fin: list | None) -> str:
        return f"{name}: 估值合理 + ROE稳定 + 北向资金关注"

    def _bear_case(self, name: str, quote: dict | None, fin: list | None) -> str:
        return f"{name}: 宏观不确定性 + 行业竞争加剧 + 流动性风险"

    # ------------------------------------------------------------------
    # Phase 2: 选股筛选预设
    # ------------------------------------------------------------------

    def screen_by_preset(
        self,
        preset_name: str,
        candidates: list[dict],
        limit: int = 20,
    ) -> list[tuple[str, DiagnosisReport, float]]:
        """按预设方法论筛选股票。

        Args:
            preset_name: 预设名 (value/growth/quality/short/special-situation)
            candidates: 候选股票列表, 每项至少含 symbol/name/quote/financials
            limit: 返回数量上限

        Returns:
            [(symbol, report, composite_score), ...] 按得分降序排列
        """
        preset = SCREENING_PRESETS.get(preset_name)
        if preset is None:
            raise ValueError(f"未知预设 '{preset_name}', 可选: {list(SCREENING_PRESETS.keys())}")

        results: list[tuple[str, DiagnosisReport, float]] = []
        for c in candidates[:100]:  # 最多扫描 100 只
            symbol = c.get("symbol", "")
            name = c.get("name", "")
            quote = c.get("quote") or {}
            financials = c.get("financials") or []

            # 快速排除
            if not self._passes_quick_filter(quote, preset):
                continue

            # 深度分析
            report = self.analyze(symbol, name, quote, financials)
            composite = self._calc_preset_score(report, preset)
            if composite > 0:
                results.append((symbol, report, composite))

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:limit]

    @staticmethod
    def _passes_quick_filter(quote: dict, preset: ScreeningPreset) -> bool:
        """快速排除不符合预设的股票。"""
        if not quote:
            return False
        th = preset.thresholds

        # 排除 ST
        if quote.get("is_st") or quote.get("is_star_st"):
            return False

        # 市值门槛
        market_cap = quote.get("market_cap", 0)
        min_cap = th.get("min_market_cap", 0)
        if market_cap < min_cap:
            return False

        # PE 上限 (价值型和质量型)
        if "max_pe" in th:
            pe = quote.get("pe_ttm") or quote.get("pe", 999)
            if pe > th["max_pe"]:
                return False

        # PE 下限 (成长型, 排除负 PE)
        if th.get("require_positive_pe") and (quote.get("pe_ttm") or 0) <= 0:
            return False

        return True

    @staticmethod
    def _calc_preset_score(report: DiagnosisReport, preset: ScreeningPreset) -> float:
        """按预设权重计算综合得分。"""
        w = preset.weight_overrides
        val_score = report.valuation_score if report.valuation_score != 50.0 else report.value_score
        return (
            val_score * w.get("value_score", 0.2)
            + report.quality_score * w.get("quality_score", 0.2)
            + report.momentum_score * w.get("momentum_score", 0.2)
            + report.macro_score * w.get("macro_score", 0.15)
            + report.executive_score * w.get("executive_score", 0.05)
            + report.cycle_score * w.get("cycle_score", 0.05)
            + (50.0 if report.sentiment_signal == "NEUTRAL" else 30.0) * w.get("sentiment", 0.05)
        )


# ------------------------------------------------------------------
# Phase 2: 选股筛选预设定义
# ------------------------------------------------------------------

@dataclass
class ScreeningPreset:
    """选股方法论预设。"""
    name: str
    description: str
    weight_overrides: dict  # 评分权重重写
    thresholds: dict  # A 股特定阈值
    adapters: list = field(default_factory=list)  # A 股特定调整规则


SCREENING_PRESETS: dict[str, ScreeningPreset] = {
    "value": ScreeningPreset(
        name="价值投资",
        description="低估值 + 高股息 + 低负债率 — 寻找被市场低估的优质资产",
        weight_overrides={
            "value_score": 0.45, "quality_score": 0.25,
            "macro_score": 0.10, "momentum_score": 0.10, "sentiment": 0.10,
        },
        thresholds={
            "max_pe": 15, "min_pb": 0.0, "max_pb": 1.5,
            "min_div_yield": 0.02, "max_debt_equity": 1.0,
            "min_market_cap": 2e9,  # 市值 > 20 亿
        },
        adapters=[
            "排除 ST/*ST 股票",
            "排除上市不满 60 天新股",
            "股息率以最近财年为准, 非 TTM",
            "扣非净利润优先于归母净利润",
            "PB 为负 (净资产为负) 时排除",
        ],
    ),
    "growth": ScreeningPreset(
        name="成长投资",
        description="高营收增速 + 高盈利增速 + 高 ROIC — 寻找高速成长的公司",
        weight_overrides={
            "quality_score": 0.40, "momentum_score": 0.30,
            "value_score": 0.10, "macro_score": 0.10, "sentiment": 0.10,
        },
        thresholds={
            "min_revenue_growth": 0.15, "min_earnings_growth": 0.20,
            "min_roic": 0.15, "max_debt_equity": 1.5,
            "min_market_cap": 5e9, "require_positive_pe": True,
        },
        adapters=[
            "营收增速以扣非口径为准",
            "排除一次性投资收益对利润的影响",
            "连续 3 年营收增速下滑的排除",
            "商誉/净资产 > 0.3 的标记风险",
            "研发费用资本化比例异常的标记风险",
        ],
    ),
    "quality": ScreeningPreset(
        name="质量投资",
        description="高 ROE + 稳定盈利 + 低杠杆 — 寻找具有持久竞争优势的公司",
        weight_overrides={
            "quality_score": 0.50, "value_score": 0.25,
            "macro_score": 0.10, "momentum_score": 0.10, "sentiment": 0.05,
        },
        thresholds={
            "min_roe": 0.15, "min_gross_margin": 0.30,
            "max_debt_equity": 0.5, "min_market_cap": 10e9,
            "min_consecutive_profit_years": 5,
        },
        adapters=[
            "ROE 连续 5 年 > 15% 的优先",
            "关注扣非 ROE, 非归母 ROE",
            "商誉/净资产 > 0.3 的降权",
            "关联交易占比高的标记风险",
            "应收账款/营收 > 行业均值 2 倍的排除",
        ],
    ),
    "short": ScreeningPreset(
        name="风险识别 (A 股不做空)",
        description="识别基本面恶化的股票 — A 股仅用于规避风险, 不直接做空",
        weight_overrides={
            "quality_score": 0.35, "momentum_score": 0.30,
            "value_score": 0.15, "macro_score": 0.10, "sentiment": 0.10,
        },
        thresholds={
            "max_revenue_growth": 0.05, "max_earnings_growth": 0.0,
            "min_debt_equity": 0.5, "min_receivable_growth": 0.30,
        },
        adapters=[
            "仅识别风险, 不直接做空 (A 股限制)",
            "高管大额减持的提示风险",
            "审计意见非标的一律排除",
            "近 12 个月有违规记录的排除",
            "大股东股权质押 > 80% 的提示风险",
        ],
    ),
    "special-situation": ScreeningPreset(
        name="事件驱动",
        description="IPO 锁定期/重组/增发/股权激励/回购 — 寻找事件催化机会",
        weight_overrides={
            "momentum_score": 0.35, "quality_score": 0.25,
            "value_score": 0.15, "macro_score": 0.10, "sentiment": 0.15,
        },
        thresholds={
            "min_market_cap": 3e9,
        },
        adapters=[
            "IPO 锁定期到期前 30 天关注",
            "重大资产重组复牌后跟踪 20 日",
            "员工持股/股权激励解锁期关注",
            "大额回购 (占总股本 > 1%) 加分",
            "定增解禁前 15 天提示风险",
        ],
    ),
}

