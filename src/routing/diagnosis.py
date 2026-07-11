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
    manipulation_risk_score: float = 0.0  # Phase 10: 庄家操纵风险评分 0-100
    cycle_phase: str = ""                # 周期阶段名称
    cycle_analysis: Optional[object] = None  # CycleAnalysis DTO
    bull_case: str = ""
    bear_case: str = ""
    # 事实性价格数据（非投资论点，供输出渲染器展示）
    change_pct_1d: float = 0.0           # 当日涨跌幅 %
    change_pct_5d: Optional[float] = None # 5日涨跌幅 %（数据不足时为 None）
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
    # 反追高因子（低位启动 vs 高位加速）
    ma_deviation_pct: float = 0.0           # (price - MA60)/MA60 * 100
    price_ma_zone: str = "NEUTRAL"           # LOW_BASE / NEUTRAL / HIGH_ACCEL
    momentum_direction_discount: float = 1.0  # 方向质量折扣 0.5-1.0
    surge_risk: bool = False                 # 短期飙升熔断标记
    surge_5day_pct: float = 0.0              # 5 日涨跌幅 %
    # Phase 12: 回调入场
    pullback_score: float = 50.0             # 回调质量分 0-100
    pullback_state: Optional[object] = None  # PullbackState (lazy import)
    pullback_authentic: bool = True          # 回调是否通过反操纵验证
    # Phase 12: 大宗交易机构资金
    block_trade_score: float = 50.0          # 大宗交易信号评分 0-100
    block_trade_signal: str = "neutral"      # "bullish" / "bearish" / "neutral"
    dimension_synthesis: str = ""            # 多维诊断综述
    # 主题驱动检测
    sector_warnings: list[str] = field(default_factory=list)  # 行业级风险提示
    is_theme_driven: bool = False            # 是否处于主题驱动阶段


class DiagnosisEngine:
    """多维诊断引擎: 宏观/价值/质量/动量/估值/周期/情绪/高管 8+ 维度。"""

    @staticmethod
    def _apply_weight(score: float, weight: float) -> float:
        """将权重系数应用到评分，输出保持在 0-100 范围。

        公式: new_score = score * weight，钳制在 [0, 100]。
        weight < 1.0 降权，weight > 1.0 加权。
        """
        return max(0.0, min(100.0, score * weight))

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
        regime_adjustments: Optional[object] = None,   # Phase 11: RegimeAdjustments
        manipulation_scan: Optional[object] = None,    # Phase 11: ManipulationScan
        block_trade_profile: Optional[object] = None,  # Phase 12: BlockTradeProfile
    ) -> DiagnosisReport:
        report = DiagnosisReport(symbol=symbol, name=name)

        if macro:
            report.macro_score = self._score_macro(macro, macro_regime, fiscal_regime)

        # 提前提取 cycle_phase 供 PE 评分使用
        _cycle_phase = ""
        if cycle_analysis is not None:
            _cp = getattr(cycle_analysis, "phase", None)
            if hasattr(_cp, "value"):
                _cycle_phase = _cp.value
            else:
                _cycle_phase = str(_cp) if _cp else ""

        if quote and financials:
            report.value_score = self._score_value(quote, valuation_result, _cycle_phase)
            report.quality_score = self._score_quality(financials, earnings_factor)
            mom = self._score_momentum(quote, northbound_profile)
            report.momentum_score = mom["score"]
            report.price_ma_zone = mom["zone"]
            report.momentum_direction_discount = mom["discount"]
            report.ma_deviation_pct = mom["deviation"]
        else:
            # 财务数据不可用 — 标记 DATA_GAP，使用中性默认值
            if not financials:
                report.data_gaps = getattr(report, 'data_gaps', []) or []
                report.data_gaps.append("[DATA_GAP] 财务数据不可用 — 价值/质量/动量评分使用中性值 50，置信度大幅下调")
            if quote and not financials:
                # 仅有行情无财务：只能算动量
                mom = self._score_momentum(quote, northbound_profile)
                report.momentum_score = mom["score"]
                report.price_ma_zone = mom["zone"]
                report.momentum_direction_discount = mom["discount"]
                report.ma_deviation_pct = mom["deviation"]

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

        report.bull_case = self._bull_case(name, quote, financials, _cycle_phase,
                                            momentum_score=report.momentum_score,
                                            price_ma_zone=report.price_ma_zone)
        report.bear_case = self._bear_case(name, quote, financials, _cycle_phase,
                                            momentum_score=report.momentum_score,
                                            price_ma_zone=report.price_ma_zone,
                                            surge_risk=report.surge_risk,
                                            surge_5day_pct=report.surge_5day_pct)

        # Phase 10: 庄家操纵风险检测（日内分钟级）
        try:
            from src.game_theory.manipulation import ManipulationDetector
            detector = ManipulationDetector()
            manip_result = detector.detect(symbol, quote if quote else {}, name=name)
            report.manipulation_risk_score = manip_result.risk_score
        except Exception:
            report.manipulation_risk_score = 0.0

        # Phase 11: 宏观象限权重前置 + 反操纵扫描降权
        if regime_adjustments is not None:
            report.macro_score = self._apply_weight(
                report.macro_score, getattr(regime_adjustments, "macro_weight", 1.0)
            )
            report.value_score = self._apply_weight(
                report.value_score, getattr(regime_adjustments, "value_weight", 1.0)
            )
            report.quality_score = self._apply_weight(
                report.quality_score, getattr(regime_adjustments, "quality_weight", 1.0)
            )
            report.momentum_score = self._apply_weight(
                report.momentum_score, getattr(regime_adjustments, "momentum_weight", 1.0)
            )

        # 反操纵扫描降权
        if manipulation_scan is not None:
            manip_overall = getattr(manipulation_scan, "overall_risk", 0.0)
            if manip_overall > 60:
                report.manipulation_risk_score = max(
                    report.manipulation_risk_score, manip_overall
                )
                manip_discount = 1.0 - (manip_overall / 200)  # 最大降权 50%
                report.value_score = self._apply_weight(report.value_score, manip_discount)
                report.quality_score = self._apply_weight(report.quality_score, manip_discount)
                report.momentum_score = self._apply_weight(report.momentum_score, manip_discount)
                report.confidence = max(0.3, report.confidence - 0.1)
            elif manip_overall > 30:
                report.manipulation_risk_score = max(
                    report.manipulation_risk_score, manip_overall
                )
                manip_discount = 1.0 - (manip_overall / 300)
                report.momentum_score = self._apply_weight(report.momentum_score, manip_discount)

        # ── 反追高：MA 绝对偏离折扣 ──
        # 方向感知折扣已通过 _score_momentum → _calc_price_ma_zone 应用。
        # 此处对绝对偏离做二次惩罚：即使不在 HIGH_ACCEL 区域，偏离过大本身也是风险。
        if quote and quote.get("ma60") is not None:
            dev = report.ma_deviation_pct
            if dev > 50.0:
                report.momentum_score = self._apply_weight(report.momentum_score, 0.4)
                report.value_score = self._apply_weight(report.value_score, 0.8)
                report.confidence = max(0.3, report.confidence - 0.1)
                report.data_gaps.append(
                    f"[WARN] 价格偏离 MA60 {dev:.0f}% > 50% — 技术性超买，动量-60%，价值-20%"
                )
            elif dev > 30.0:
                report.momentum_score = self._apply_weight(report.momentum_score, 0.6)
                report.value_score = self._apply_weight(report.value_score, 0.8)
                report.confidence = max(0.3, report.confidence - 0.05)
                report.data_gaps.append(
                    f"[WARN] 价格偏离 MA60 {dev:.0f}% > 30% — 动量-40%，价值-20%"
                )

        # ── 反追高：短期飙升熔断 ──
        close_series = quote.get("close_series", []) if quote else []
        if len(close_series) >= 6:
            latest = close_series[-1]
            five_days_ago = close_series[-6]
            if five_days_ago and five_days_ago > 0:
                report.surge_5day_pct = round(
                    (latest - five_days_ago) / five_days_ago * 100.0, 2
                )
                if report.surge_5day_pct > 20.0:
                    report.surge_risk = True
                    report.data_gaps.append(
                        f"[WARN] 短期飙升 {report.surge_5day_pct:.0f}%/5日 — 追涨熔断触发"
                    )

        # ── 事实性价格数据（供输出渲染器展示，非投资论点）──
        report.change_pct_1d = (quote or {}).get("change_pct", 0) or 0.0
        if report.surge_5day_pct != 0.0 or (close_series and len(close_series) >= 6):
            report.change_pct_5d = report.surge_5day_pct

        # Phase 12: 回调入场检测
        report.pullback_score, report.pullback_state, report.pullback_authentic = (
            self._detect_pullback(symbol, name, quote)
        )
        # 回调质量影响动量评分: momentum(0.6) + pullback(0.4)
        report.momentum_score = self._apply_weight(
            report.momentum_score,
            0.6 + 0.4 * (report.pullback_score / 100.0),
        )

        # Phase 12: 大宗交易机构资金信号
        report.block_trade_score, report.block_trade_signal = (
            self._score_block_trade(block_trade_profile)
        )

        # Phase 1: 填充数据溯源和信心度
        report.source_citations = self._collect_citations(quote, financials, macro, executive)
        report.confidence = self._calc_confidence(report, quote, financials)
        report.data_freshness = datetime.now()
        # 主题驱动检测 (传入行业PE中位数等上下文)
        sector_pe_median = quote.get("sector_pe_median") if quote else None
        sector_q1_ratio = quote.get("sector_q1_ratio") if quote else None
        sector_name = quote.get("sector_name", "") if quote else ""
        report.sector_warnings = self.detect_theme_driven(
            report,
            sector_pe_median=sector_pe_median,
            sector_q1_ratio=sector_q1_ratio,
            sector_name=sector_name,
        )
        if report.sector_warnings:
            report.is_theme_driven = any("主题驱动" in w for w in report.sector_warnings)
        report.dimension_synthesis = self._synthesize_dimensions(report)
        return report

    @staticmethod
    def _detect_pullback(
        symbol: str, name: str, quote: dict | None,
    ) -> tuple[float, object, bool]:
        """Phase 12: 回调入场检测。

        Returns:
            (pullback_score, pullback_state, authentic)
        """
        if not quote:
            return 50.0, None, True

        try:
            from src.analysis.pullback import PullbackDetector, AntiManipulationGate
            from src.data.schema import Bar

            daily_bars = quote.get("daily_bars", [])
            if not daily_bars or len(daily_bars) < 30:
                return 50.0, None, True

            minute_data = quote.get("minute_data") if isinstance(quote, dict) else None

            gate = AntiManipulationGate()
            detector = PullbackDetector(anti_manipulation_gate=gate)
            state = detector.detect(
                symbol, daily_bars, name=name, minute_data=minute_data,
            )
            return state.pullback_score, state, state.authentic_pullback
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "回调检测跳过 [%s]: 依赖模块不可用或数据不足", symbol
            )
            return 50.0, None, True

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

    @staticmethod
    def detect_theme_driven(
        report: DiagnosisReport,
        sector_pe_median: float | None = None,
        sector_abnormal_pe_ratio: float | None = None,
        sector_q1_ratio: float | None = None,
        sector_name: str = "",
    ) -> list[str]:
        """检测行业是否处于主题驱动阶段，基本面评分参考价值有限。

        触发条件:
          行业级: PE>100或亏损占比 > 40% 且 Q1利润占比 < 20%
          单票级: PE > 200 且 ROE < 3%

        Returns:
            警告信息列表
        """
        warnings = []
        pe_score = getattr(report, 'value_score', 50.0)

        # 单票极端PE+微利
        if pe_score < 30:
            roe = getattr(report, 'quality_score', 50.0)
            if roe < 25:
                warnings.append(
                    "⚠️ 主题驱动: PE极端+ROE极低，"
                    "该标的可能处于主题炒作阶段，基本面评分参考价值有限"
                )

        # 行业级: PE异常占比 > 40% + Q1季节性
        if (sector_abnormal_pe_ratio is not None
                and sector_abnormal_pe_ratio > 0.4):
            if sector_q1_ratio is not None and sector_q1_ratio < 0.20:
                warnings.append(
                    f"⚠️ 主题驱动行业({sector_name}): "
                    f"PE>100或亏损占比={sector_abnormal_pe_ratio:.0%}, "
                    f"Q1利润仅占全年={sector_q1_ratio:.0%}. "
                    "行业处于主题炒作阶段，常规基本面框架不适用，"
                    "评分仅做同行业相对排序参考"
                )
            else:
                warnings.append(
                    f"⚠️ 高估值行业({sector_name}): "
                    f"PE>100或亏损占比={sector_abnormal_pe_ratio:.0%}, "
                    "行业整体估值偏高，关注催化剂而非PE"
                )

        return warnings

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

        # ---- v4 美股隔夜修正 ----
        us = macro.get("us_overnight") if macro else None
        if us:
            sp = (us.get("sp500") or {}).get("change_pct")
            ns = (us.get("nasdaq") or {}).get("change_pct")

            if sp is not None:
                if sp <= -2.0:
                    score -= 5
                elif sp <= -1.0:
                    score -= 2
                elif sp >= 2.0:
                    score += 3

            if ns is not None and ns <= -2.5:
                score -= 3

        return max(0, min(100, score))

    def _score_value(self, quote: dict, valuation_result: Optional[object] = None,
                     cycle_phase: str = "") -> float:
        """价值评分：优先使用 ValuationAnalyzer 的 composite_score。

        当 valuation_result 可用时，使用其综合评分（含周期调整）。
        回退到简单 PE 分位逻辑，RECOVERY/TROUGH 阶段高PE不惩罚。
        """
        if valuation_result is not None:
            composite = getattr(valuation_result, "composite_score", None)
            if composite is not None:
                return float(composite)
        pe_pct = quote.get("pe_percentile", 50)
        pe_ttm = quote.get("pe_ttm") or quote.get("pe") or 0
        score = max(0, min(100, 100 - pe_pct))

        # 回退路径也加入周期感知：RECOVERY/TROUGH阶段高PE(>30)给予部分恢复
        if cycle_phase in ("recovery", "trough") and pe_ttm > 30:
            boost = min(25.0, (pe_ttm - 30) * 0.35)
            score = min(100.0, score + boost)

        return score

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

    def _score_momentum(self, quote: dict, northbound_profile: Optional[object] = None) -> dict:
        """动量评分：北向资金(市场级) + 方向感知个股动量 + MA 偏离折扣。

        返回 dict:
          - score: 最终动量评分 0-100
          - zone: 价格-MA 区域 (LOW_BASE / NEUTRAL / HIGH_ACCEL)
          - discount: 方向质量折扣 0.5-1.0
          - deviation: MA60 偏离百分比
        """
        nb_score = 50.0
        if northbound_profile is not None:
            nb_score = float(getattr(northbound_profile, "score", 50.0))

        # 个股自身动量：用当日涨跌幅作为短期动量代理
        change_pct = quote.get("change_pct", 0) or 0.0
        stock_momentum = 50.0 + min(max(change_pct * 5, -30), 30)

        # 方向感知：区分低位启动 vs 高位加速
        ma20 = quote.get("ma20")
        ma60 = quote.get("ma60")
        current_price = quote.get("price", 0) or quote.get("close", 0) or 0.0
        zone, discount, deviation = self._calc_price_ma_zone(current_price, ma20, ma60)

        # 方向折扣：将动量向 50 中性拉回
        adjusted_stock = 50.0 + (stock_momentum - 50.0) * discount
        final_score = nb_score * 0.5 + adjusted_stock * 0.5

        return {
            "score": round(final_score, 1),
            "zone": zone,
            "discount": round(discount, 2),
            "deviation": round(deviation, 1),
        }

    @staticmethod
    def _calc_price_ma_zone(
        current_price: float,
        ma20: Optional[float],
        ma60: Optional[float],
    ) -> tuple[str, float, float]:
        """确定价格-MA 区域和动量质量折扣。

        区域:
          LOW_BASE   — 价格接近或低于 MA（MA20+10% 内 或 低于 MA60）→ 真实突破，不惩罚
          NEUTRAL    — 中等偏离
          HIGH_ACCEL — 价格远高于 MA（偏离 MA20>20% 且 MA60>30%）→ 追高嫌疑，打折

        Returns:
          (zone, discount, deviation_pct)
          其中 discount 应用于动量评分以惩罚追高行为（LOW_BASE=1.0, HIGH_ACCEL=0.5-0.7）
        """
        if current_price <= 0 or ma20 is None or ma60 is None or ma60 <= 0:
            return "NEUTRAL", 1.0, 0.0

        dev_ma20 = (current_price - ma20) / ma20 * 100.0
        dev_ma60 = (current_price - ma60) / ma60 * 100.0

        # 低位启动：价格在 MA20 附近 10% 内或低于 MA60 → 真实动量，不惩罚
        if current_price <= ma20 * 1.10 or current_price <= ma60:
            return "LOW_BASE", 1.0, round(dev_ma60, 1)

        # 高位加速：偏离 MA20>20% 且 MA60>30% → 追高嫌疑
        if dev_ma20 > 20.0 and dev_ma60 > 30.0:
            # 偏离越大折扣越狠，下限 0.50
            excess = min(dev_ma60, 100.0)
            discount = max(0.50, 1.0 - (excess - 30.0) / 150.0)
            return "HIGH_ACCEL", round(discount, 2), round(dev_ma60, 1)

        return "NEUTRAL", 1.0, round(dev_ma60, 1)

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
        # 合规披露关键词 — 这些是定期/常规的制度文件，不是实质性高管变动
        _COMPLIANCE_KEYWORDS = [
            "述职报告", "履职报告", "履职情况", "管理办法", "管理制度",
            "薪酬方案", "薪酬制度", "薪酬管理", "会议决议", "公司章程",
            "工商变更", "专项意见", "评估报告", "授权管理", "工作细则",
            "履职评价", "工作总结", "审计委员会", "战略委员会",
            "提名委员会", "薪酬委员会", "考核委员会", "董事会工作报告",
            "独立董事独立性", "董事会审计委员会", "会计师事务所",
            "法定代表人", "董事履职", "高级管理人员薪酬",
        ]

        def _is_compliance_disclosure(change: dict) -> bool:
            """判断一条高管变动记录是否为例行合规披露而非实质性变动."""
            reason = change.get("reason", "")
            title = change.get("title", "")
            text = f"{reason} {title}".lower()
            return any(kw in text for kw in _COMPLIANCE_KEYWORDS)

        non_compliance = [c for c in changes if not _is_compliance_disclosure(c)]
        compliance_count = len(changes) - len(non_compliance)

        # 实质性非正常变动（排除任期届满）
        abnormal = [c for c in non_compliance
                    if "任期届满" not in c.get("reason", "")]

        if abnormal:
            penalty = min(20, len(abnormal) * 10)
            score -= penalty
            for c in abnormal:
                name = c.get("person_name", "")
                reason = c.get("reason", "原因未知")
                risks.append(f"董监高变动: {name} {reason}")

        # 合规披露不扣分，仅记录数量供调试
        if compliance_count > 0:
            pass  # 例行合规披露，不视为风险

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
            # 数据源不可用时仅记录提醒，不作为主要风险
            # 真正的风险是"有数据但发现有问题的内容"

        return {"score": max(0.0, min(100.0, score)), "risks": risks}

    def _bull_case(self, name: str, quote: dict | None, fin: list | None,
                   cycle_phase: str = "",
                   momentum_score: float = 50.0,
                   price_ma_zone: str = "NEUTRAL") -> str:
        """基于实际数据生成股票特定的看多理由，周期感知 PE 标签。"""
        parts = []
        pe = (quote or {}).get("pe_ttm") or (quote or {}).get("pe") or 0
        pb = (quote or {}).get("pb") or 0
        if fin:
            latest = fin[0] if fin else {}
            roe = latest.get("roe")
            rev_growth = latest.get("revenue_growth_pct")
            profit_growth = latest.get("net_profit_growth_pct")
            if roe is not None and roe > 15:
                parts.append(f"ROE={roe:.1f}%盈利能力突出")
            elif roe is not None and roe > 8:
                parts.append(f"ROE={roe:.1f}%盈利能力稳健")
            if rev_growth is not None and rev_growth > 20:
                parts.append(f"营收增速{rev_growth:+.1f}%高成长")
            if profit_growth is not None and profit_growth > 20:
                parts.append(f"利润增速{profit_growth:+.1f}%")
        # 周期感知 PE 标签
        if pe > 0 and pe < 15:
            parts.insert(0, f"PE={pe:.1f}x估值偏低")
        elif pe > 0 and pe < 30:
            parts.insert(0, f"PE={pe:.1f}x估值合理")
        elif pe > 0 and pe > 30 and cycle_phase in ("recovery", "trough"):
            parts.insert(0, f"PE={pe:.1f}x(盈利周期底部，关注拐点确认)")
        # 动量维度叙事（基于多时间框架动量评分，非单日涨跌）
        if momentum_score >= 70:
            parts.append(f"动量趋势偏强(评分{momentum_score:.0f})，价格动能向上")
        elif momentum_score >= 55:
            parts.append(f"动量中性偏多(评分{momentum_score:.0f})，趋势温和向好")
        elif price_ma_zone == "LOW_BASE":
            parts.append("价格处于低位区域，关注拐点确认")
        return "；".join(parts) if parts else f"{name}: 各维度信号中性，无显著亮点"

    def _bear_case(self, name: str, quote: dict | None, fin: list | None,
                   cycle_phase: str = "",
                   momentum_score: float = 50.0,
                   price_ma_zone: str = "NEUTRAL",
                   surge_risk: bool = False,
                   surge_5day_pct: float = 0.0) -> str:
        """基于实际数据生成股票特定的看空理由，周期感知 PE 标签。"""
        parts = []
        pe = (quote or {}).get("pe_ttm") or (quote or {}).get("pe") or 0
        pb = (quote or {}).get("pb") or 0
        if fin:
            latest = fin[0] if fin else {}
            roe = latest.get("roe")
            rev_growth = latest.get("revenue_growth_pct")
            debt_ratio = latest.get("debt_ratio") or latest.get("asset_liability_ratio")
            if roe is not None and roe < 5:
                parts.append(f"ROE={roe:.1f}%盈利能力薄弱")
            if rev_growth is not None and rev_growth < 0:
                parts.append(f"营收增速{rev_growth:+.1f}%下滑")
            if debt_ratio is not None and debt_ratio > 70:
                parts.append(f"资产负债率{debt_ratio:.0f}%偏高")
        # 周期感知 PE 标签
        if pe > 60 and cycle_phase in ("recovery", "trough"):
            parts.insert(0, f"PE={pe:.1f}x(周期底部盈利压低PE，关注扭亏拐点)")
        elif pe > 60:
            parts.insert(0, f"PE={pe:.1f}x估值偏高(周期高位注意风险)")
        elif pe < 0 and cycle_phase in ("recovery", "trough"):
            parts.insert(0, "PE为负(周期底部亏损，关注扭亏拐点)")
        elif pe < 0:
            parts.insert(0, "PE为负，当前处于亏损状态")
        # 动量维度叙事（基于多时间框架动量评分，非单日涨跌）
        if momentum_score <= 30:
            parts.append(f"动量趋势偏弱(评分{momentum_score:.0f})，价格动能向下")
        elif momentum_score <= 45:
            parts.append(f"动量中性偏空(评分{momentum_score:.0f})，趋势疲软")
        if price_ma_zone == "HIGH_ACCEL":
            parts.append("价格处于高位加速区域，追高风险较大")
        if surge_risk:
            parts.append(f"短期飙升{surge_5day_pct:.0f}%/5日，注意回调风险")
        return "；".join(parts) if parts else f"{name}: 各维度信号中性，无显著风险"

    @staticmethod
    def _score_block_trade(profile: Optional[object] = None) -> tuple[float, str]:
        """大宗交易机构资金评分 0-100 + 信号方向。

        评分逻辑:
          - 机构净买入 → +15~25
          - 高溢价成交 (≥5%) → +10~15
          - 目标标的机构买入 → +10
          - 连续大宗建仓 → +5~10
          - 深度折价 (≤-10%) → -10~20
          - 机构净卖出 → -15~25

        返回 (score, signal): score 0-100, signal ∈ {bullish, bearish, neutral}
        """
        if profile is None:
            return 50.0, "neutral"

        score = float(getattr(profile, "score", 50))
        signal = str(getattr(profile, "signal", "neutral"))
        return score, signal

    @staticmethod
    def _synthesize_dimensions(report: DiagnosisReport) -> str:
        """生成多维诊断综述——解释维度间交互、主导维度、矛盾点。

        分析 8 个维度的得分模式，识别：
        - 主导信号（得分 ≥70 或 ≤30）及其含义
        - 矛盾对（分差 >40 的两维度）及其市场含义
        - 整体叙事方向 + 关注点
        """
        dims = [
            ("宏观环境", report.macro_score), ("价值因子", report.value_score),
            ("质量因子", report.quality_score), ("动量因子", report.momentum_score),
            ("盈利修正", report.earnings_revision_score), ("估值综合", report.valuation_score),
            ("周期适配", report.cycle_score), ("高管因子", report.executive_score),
        ]
        strong_bull = [(n, s) for n, s in dims if s >= 70]
        strong_bear = [(n, s) for n, s in dims if s <= 30]
        avg = sum(s for _, s in dims) / len(dims)

        lines = []

        # ── 1. 多头亮点 ──
        if strong_bull:
            names = "、".join(f"{n}({s:.0f})" for n, s in strong_bull[:3])
            bull_detail = []
            for n, s in strong_bull[:3]:
                if n == "盈利修正":
                    bull_detail.append("分析师持续上调盈利预期，基本面改善趋势确认")
                elif n == "周期适配":
                    bull_detail.append("当前经济周期对该行业友好，历史胜率偏高")
                elif n == "宏观环境":
                    bull_detail.append("宏观流动性宽松，风险偏好环境有利")
                elif n == "质量因子":
                    bull_detail.append("盈利能力与现金流质量过硬，下行保护充分")
                elif n == "动量因子":
                    bull_detail.append("价格趋势向上，资金持续流入")
            detail_text = "；".join(bull_detail) if bull_detail else ""
            lines.append(f"多头亮点: {names}")
            if detail_text:
                lines.append(f"  ↳ {detail_text}")

        # ── 2. 空头拖累 ──
        if strong_bear:
            names = "、".join(f"{n}({s:.0f})" for n, s in strong_bear[:3])
            bear_detail = []
            for n, s in strong_bear[:3]:
                if n == "动量因子":
                    bear_detail.append("价格趋势疲弱，资金持续流出或观望，短期难有起色")
                elif n == "质量因子":
                    bear_detail.append("盈利质量或现金流存在隐患，需警惕纸面利润")
                elif n == "宏观环境":
                    bear_detail.append("宏观环境收紧，系统性风险上升")
                elif n == "高管因子":
                    bear_detail.append("管理层变动或背景不明，治理风险需关注")
                elif n == "价值因子":
                    bear_detail.append("估值虽低但可能隐含基本面恶化，警惕价值陷阱")
            detail_text = "；".join(bear_detail) if bear_detail else ""
            lines.append(f"空头拖累: {names}")
            if detail_text:
                lines.append(f"  ↳ {detail_text}")

        # ── 3. 矛盾检测 ──
        contradictions = []
        for i in range(len(dims)):
            for j in range(i + 1, len(dims)):
                diff = abs(dims[i][1] - dims[j][1])
                if diff > 40:
                    contradictions.append((dims[i][0], dims[j][0], diff))
        if contradictions:
            ct = contradictions[:2]
            ct_text = "、".join(f"{a}↔{b}(差{d:.0f}分)" for a, b, d in ct)
            ct_meaning = []
            for a, b, d in ct:
                if ("盈利修正" in (a, b) and "动量" in (a, b)):
                    ct_meaning.append("基本面改善但价格未跟进——可能是信息滞后（买入机会）或市场已预判风险（价值陷阱）")
                elif ("质量" in (a, b) and "盈利修正" in (a, b)):
                    ct_meaning.append("盈利上调但质量分偏低——关注是否来自一次性收益而非主业改善")
                elif ("周期适配" in (a, b) and "动量" in (a, b)):
                    ct_meaning.append("周期有利但价格不动——可能是板块轮动前的蓄力或市场结构性回避")
            ct_detail = "；".join(ct_meaning) if ct_meaning else "分差过大说明市场定价存在分歧，需要更多信息来验证方向"
            lines.append(f"维度矛盾: {ct_text}")
            lines.append(f"  ↳ {ct_detail}")

        # ── 4. 整体判断 + 关注点 ──
        if avg >= 65:
            overall = "整体偏多，多数维度发出积极信号"
            focus = "关注动量能否跟上基本面改善，若动量持续低迷则需重新评估"
        elif avg >= 50:
            overall = "整体中性，多空信号交织，需更多催化剂判断方向"
            focus = "关注矛盾维度的演化方向——任一矛盾解决都可能触发方向性行情"
        elif avg >= 35:
            overall = "整体偏空，多数维度承压，但仍有局部亮点可关注"
            focus = "关注亮点维度能否扩散至其他维度，若出现共振改善则是入场信号"
        else:
            overall = "整体显著偏空，多维度发出警戒信号"
            focus = "除非出现基本面拐点（盈利修正转正、宏观改善），否则不宜逆势抄底"

        lines.append(overall)
        lines.append(f"🔍 关注点: {focus}")

        return "\n".join(lines)

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
        import random

        preset = SCREENING_PRESETS.get(preset_name)
        if preset is None:
            raise ValueError(f"未知预设 '{preset_name}', 可选: {list(SCREENING_PRESETS.keys())}")

        # 随机打乱候选顺序，避免字母序偏差导致同一板块垄断。
        # 实际扫描数量 = min(100, len(candidates))，从打乱后的列表中取前 N 只。
        MAX_SCAN = 100
        shuffled = list(candidates)
        random.shuffle(shuffled)
        scan_pool = shuffled[:MAX_SCAN]

        results: list[tuple[str, DiagnosisReport, float]] = []
        for c in scan_pool:
            # 兼容 dict 和 Pydantic BaseModel (Quote)
            if hasattr(c, "model_dump"):
                c = c.model_dump()
            symbol = c.get("symbol", "")
            name = c.get("name", "")
            # Quote.model_dump() 是扁平行情 dict，直接作为 quote 使用；
            # 不再尝试提取嵌套 "quote" 子字段（Quote 模型无此字段）。
            quote = c
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
    def _passes_quick_filter(quote: dict, preset: ScreeningPreset,
                             cycle_phase: str = "") -> bool:
        """快速排除不符合预设的股票，周期感知 PE 上限。

        RECOVERY/TROUGH 阶段有效 PE 上限提高至 40，避免过滤周期底部高 PE 标的。

        数据缺失安全策略：pe_ttm / market_cap 为 None 时跳过对应检查，
        不因数据不可用而误杀候选标的。全市场扫描数据可能缺少这些字段。
        """
        if not quote:
            return False
        th = preset.thresholds

        # 排除 ST
        if quote.get("is_st") or quote.get("is_star_st"):
            return False

        # 市值门槛 — 仅在有数据时过滤
        market_cap = quote.get("market_cap")
        if market_cap is not None and market_cap > 0:
            min_cap = th.get("min_market_cap", 0)
            if market_cap < min_cap:
                return False

        # PE 上限 (价值型和质量型) — 周期感知
        if "max_pe" in th:
            pe = quote.get("pe_ttm") or quote.get("pe")
            if pe is not None and pe > 0:
                effective_max_pe = th["max_pe"]
                # RECOVERY/TROUGH 阶段放宽 PE 上限至 40
                if cycle_phase in ("recovery", "trough"):
                    effective_max_pe = max(effective_max_pe, 40)
                if pe > effective_max_pe:
                    return False

        # PE 下限 (成长型, 排除负 PE) — 仅在有数据时过滤
        if th.get("require_positive_pe"):
            pe = quote.get("pe_ttm") or quote.get("pe")
            if pe is not None and pe <= 0:
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
            "max_pe": 30, "min_pb": 0.0, "max_pb": 1.5,
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

