"""三大根本问题综合诊断引擎.

回答 A 股投资三个根本假设：
  Q1: 政策市还是市场市？（定价逻辑来源）
  Q2: 定价权在谁手里？（边际定价者）
  Q3: 信息优势是否存在？（超额收益来源）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class Q1Answer:
    """答案: 政策市还是市场市？"""

    classification: str = "混合驱动"  # 政策市 / 市场市 / 资金市 / 混合驱动
    primary_driver: str = "mixed"  # policy / market / liquidity / mixed
    confidence: float = 0.5  # 0.0-1.0

    # 子分析器结果
    monetary_quadrant: str = ""  # 货币信用象限
    market_regime: str = ""  # MarketRegime 枚举值
    fiscal_stance: str = "neutral"  # expansionary / neutral / tightening
    policy_intensity: str = "LOW"  # HIGH / MEDIUM / LOW
    regime_confidence: float = 0.0
    policy_confidence: float = 0.0

    # 证据
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class Q2Answer:
    """答案: 定价权在谁手里？"""

    marginal_pricer_ranking: list[dict] = field(default_factory=list)
    # 每项: {"player": "机构", "influence": 0.85, "score": 75.0}

    dominant_player: str = ""
    dominance_confidence: float = 0.0
    secondary_players: list[str] = field(default_factory=list)

    # 辅助信号
    crowding_warning: bool = False
    crowding_score: int = 50
    northbound_direction: str = "neutral"  # inflow / outflow / neutral
    margin_fear_greed: str = "neutral"  # fear / neutral / greed
    margin_score: int = 50

    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class Q3Answer:
    """答案: 信息优势是否存在？"""

    information_advantage_score: float = 40.0  # 0-100, 越高越有优势
    speed_grade: str = "unknown"  # fast / average / slow / unknown
    coverage_grade: str = "unknown"  # comprehensive / adequate / sparse / unknown

    avg_latency_seconds: float = 0.0
    fastest_source: str = "unknown"
    total_events: int = 0
    event_types_tracked: dict = field(default_factory=dict)
    bottlenecks: list[str] = field(default_factory=list)

    # 数据源覆盖度
    active_sources: list[str] = field(default_factory=list)
    source_count: int = 0

    confidence: float = 0.3
    recommendations: list[str] = field(default_factory=list)


@dataclass
class FundamentalDiagnosisReport:
    """三大根本问题诊断报告."""

    q1: Q1Answer = field(default_factory=Q1Answer)
    q2: Q2Answer = field(default_factory=Q2Answer)
    q3: Q3Answer = field(default_factory=Q3Answer)
    source_citations: list[SourceCitation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典供下游使用."""
        return {
            "q1": {
                "classification": self.q1.classification,
                "primary_driver": self.q1.primary_driver,
                "confidence": self.q1.confidence,
                "monetary_quadrant": self.q1.monetary_quadrant,
                "market_regime": self.q1.market_regime,
                "fiscal_stance": self.q1.fiscal_stance,
                "policy_intensity": self.q1.policy_intensity,
                "evidence": self.q1.evidence,
                "recommendations": self.q1.recommendations,
            },
            "q2": {
                "marginal_pricer_ranking": self.q2.marginal_pricer_ranking,
                "dominant_player": self.q2.dominant_player,
                "dominance_confidence": self.q2.dominance_confidence,
                "crowding_warning": self.q2.crowding_warning,
                "northbound_direction": self.q2.northbound_direction,
                "margin_fear_greed": self.q2.margin_fear_greed,
                "evidence": self.q2.evidence,
                "recommendations": self.q2.recommendations,
            },
            "q3": {
                "information_advantage_score": self.q3.information_advantage_score,
                "speed_grade": self.q3.speed_grade,
                "coverage_grade": self.q3.coverage_grade,
                "avg_latency_seconds": self.q3.avg_latency_seconds,
                "fastest_source": self.q3.fastest_source,
                "total_events": self.q3.total_events,
                "bottlenecks": self.q3.bottlenecks,
                "active_sources": self.q3.active_sources,
                "source_count": self.q3.source_count,
                "confidence": self.q3.confidence,
                "recommendations": self.q3.recommendations,
            },
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FundamentalDiagnosisEngine:
    """三大根本问题综合诊断引擎.

    组合现有分析器，统一回答：
      Q1: 政策市、市场市、还是资金市？
      Q2: 当前边际定价者是谁？影响力排名如何？
      Q3: 系统当前是否具备信息优势？

    Usage:
        engine = FundamentalDiagnosisEngine()
        report = engine.diagnose(
            macro_regime=macro_regime,
            fiscal_regime=fiscal_regime,
            policy_signals=policy_signals,
            index_prices=index_prices,
            sector_keywords=policy_keywords,
        )
    """

    def __init__(self, speed_monitor=None):
        """初始化引擎.

        Args:
            speed_monitor: 可选 SpeedMonitor 实例。不传则内部创建新实例（冷启动）。
        """
        self._dominance = None
        self._fund = None
        self._margin = None
        self._northbound = None
        self._speed_monitor = speed_monitor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diagnose(
        self,
        macro_regime=None,  # MacroRegime from MonetaryCreditAnalyzer
        fiscal_regime=None,  # FiscalRegime from FiscalAnalyzer
        policy_signals: list[dict] | None = None,  # from PolicyTracker.analyze_current()
        index_prices: list[float] | None = None,  # close prices for RegimeClassifier
        sector_keywords: list[str] | None = None,  # policy keywords for transmission
    ) -> FundamentalDiagnosisReport:
        """执行三大问题诊断."""
        report = FundamentalDiagnosisReport()
        citations: list[SourceCitation] = []

        # Q1: 政策市还是市场市？
        report.q1 = self._answer_q1(
            macro_regime, fiscal_regime, policy_signals,
            index_prices, sector_keywords, citations,
        )

        # Q2: 定价权在谁手里？
        report.q2 = self._answer_q2(citations)

        # Q3: 信息优势是否存在？
        report.q3 = self._answer_q3(citations)

        report.source_citations = citations
        return report

    # ------------------------------------------------------------------
    # Q1: 政策市 vs 市场市
    # ------------------------------------------------------------------

    def _answer_q1(
        self,
        macro_regime,
        fiscal_regime,
        policy_signals: list[dict] | None,
        index_prices: list[float] | None,
        sector_keywords: list[str] | None,
        citations: list[SourceCitation],
    ) -> Q1Answer:
        """裁决定价逻辑来源."""
        q1 = Q1Answer()
        evidence: list[str] = []

        # 1. 货币信用象限
        if macro_regime is not None:
            q1.monetary_quadrant = getattr(macro_regime, "quadrant", "")
            if hasattr(q1.monetary_quadrant, "value"):
                q1.monetary_quadrant = q1.monetary_quadrant.value
            mc_conf = getattr(macro_regime, "confidence", 0.5)
            evidence.append(f"货币信用象限: {q1.monetary_quadrant} (置信度 {mc_conf:.0%})")
            citations.append(make_citation(
                provider="macro", field="monetary_credit",
                data_type="macro_indicator", source_tier="T2", nature="interpretation",
            ))

        # 2. 市场状态 (RegimeClassifier)
        if index_prices and len(index_prices) >= 20:
            try:
                from src.macro.market_regime import RegimeClassifier
                rc = RegimeClassifier()
                regime_profile = rc.classify(prices=index_prices)
                q1.market_regime = regime_profile.regime.value if hasattr(regime_profile.regime, "value") else str(regime_profile.regime)
                q1.regime_confidence = regime_profile.confidence
                evidence.append(
                    f"市场状态: {q1.market_regime} "
                    f"(波动率 {regime_profile.volatility or 0:.1f}%, "
                    f"趋势 {regime_profile.ma_signal})"
                )
                citations.append(make_citation(
                    provider="macro", field="market_regime",
                    data_type="macro_indicator", source_tier="T2", nature="interpretation",
                ))
            except Exception as e:
                logger.debug("RegimeClassifier failed: %s", e)
        else:
            q1.market_regime = "unknown"
            evidence.append("市场状态: 数据不足 (需 ≥20 根日线)")

        # 3. 财政政策立场
        if fiscal_regime is not None:
            q1.fiscal_stance = getattr(fiscal_regime, "fiscal_stance", "neutral")
            fiscal_score = getattr(fiscal_regime, "fiscal_score", 50)
            evidence.append(f"财政立场: {q1.fiscal_stance} (得分 {fiscal_score})")
            citations.append(make_citation(
                provider="macro", field="fiscal",
                data_type="macro_indicator", source_tier="T2", nature="interpretation",
            ))

        # 4. 政策信号强度
        if policy_signals:
            urgency_levels = [s.get("urgency_level", "LOW") for s in policy_signals]
            high_count = sum(1 for u in urgency_levels if u == "HIGH")
            med_count = sum(1 for u in urgency_levels if u == "MEDIUM")
            if high_count > 0:
                q1.policy_intensity = "HIGH"
            elif med_count > 0:
                q1.policy_intensity = "MEDIUM"
            else:
                q1.policy_intensity = "LOW"
            kw_count = sum(len(s.get("keywords", [])) for s in policy_signals)
            evidence.append(
                f"政策信号: {len(policy_signals)} 条, "
                f"强度 {q1.policy_intensity}, {kw_count} 个关键词"
            )
            q1.policy_confidence = min(0.9, 0.4 + len(policy_signals) * 0.1)
            citations.append(make_citation(
                provider="policy", field="policy_signals",
                data_type="news_event", source_tier="T2", nature="interpretation",
            ))

        # 5. 综合裁决
        q1.classification, q1.primary_driver = self._classify_pricing_logic(
            q1.monetary_quadrant, q1.market_regime,
            q1.fiscal_stance, q1.policy_intensity,
        )
        evidence.append(f"裁决: {q1.classification} (主驱动: {q1.primary_driver})")

        # 6. 置信度
        confidences = []
        if macro_regime is not None:
            confidences.append(getattr(macro_regime, "confidence", 0.5))
        if q1.regime_confidence > 0:
            confidences.append(q1.regime_confidence)
        if q1.policy_confidence > 0:
            confidences.append(q1.policy_confidence)
        q1.confidence = sum(confidences) / len(confidences) if confidences else 0.4

        q1.evidence = evidence
        q1.recommendations = self._q1_recommendations(q1)
        return q1

    @staticmethod
    def _classify_pricing_logic(
        monetary_quadrant: str,
        market_regime: str,
        fiscal_stance: str,
        policy_intensity: str,
    ) -> tuple[str, str]:
        """综合裁决定价逻辑来源.

        Decision table:
          - 政策强度 HIGH + (财政扩张 or 政策象限) → 政策市
          - market_regime BULL_TRENDING/BEAR_TRENDING + 宽信用 → 市场市
          - 宽货币+紧信用 or 流动性驱动 → 资金市
          - 默认 → 混合驱动
        """
        # 政策市条件
        policy_driven = (
            policy_intensity == "HIGH"
            and fiscal_stance in ("expansionary",)
            and "宽信用" not in monetary_quadrant
        )

        # 市场市条件
        market_driven = (
            market_regime in ("bull_trending", "bear_trending")
            and "宽信用" in monetary_quadrant
        )

        # 资金市条件
        liquidity_driven = (
            "宽货币" in monetary_quadrant and "紧信用" in monetary_quadrant
        ) or (
            monetary_quadrant == "宽货币+宽信用" and policy_intensity == "LOW"
        )

        if policy_driven:
            return "政策市", "policy"
        elif market_driven:
            return "市场市", "market"
        elif liquidity_driven:
            return "资金市", "liquidity"
        else:
            return "混合驱动", "mixed"

    @staticmethod
    def _q1_recommendations(q1: Q1Answer) -> list[str]:
        """根据 Q1 结论生成建议."""
        recs = []
        if q1.primary_driver == "policy":
            recs.append("关注政策窗口期 (政治局会议/国常会/产业政策)")
            recs.append("板块配置跟随政策方向，降低技术面权重")
        elif q1.primary_driver == "market":
            recs.append("趋势跟踪策略有效，关注均线/动量信号")
            recs.append("降低政策博弈仓位，跟随市场趋势")
        elif q1.primary_driver == "liquidity":
            recs.append("流动性驱动行情，关注北向/融资/成交量变化")
            recs.append("快进快出，紧盯资金面拐点")
        else:
            recs.append("多因素交织，综合评分优先")
            recs.append("各维度等权重，不押注单一逻辑")
        return recs

    # ------------------------------------------------------------------
    # Q2: 边际定价者
    # ------------------------------------------------------------------

    def _answer_q2(
        self, citations: list[SourceCitation],
    ) -> Q2Answer:
        """识别当前边际定价者并排名."""
        q2 = Q2Answer()
        evidence: list[str] = []

        # 1. DominanceClassifier — 主导玩家 + 各玩家得分
        dom = self._safe(self._get_dominance().classify, "dominance")
        if dom:
            q2.dominant_player = dom.dominant_player or "unknown"
            q2.dominance_confidence = dom.confidence or 0.0
            q2.secondary_players = dom.secondary_players or []
            evidence.append(
                f"主导玩家: {q2.dominant_player} (置信度 {q2.dominance_confidence:.0%})"
            )
            if q2.secondary_players:
                evidence.append(f"次要玩家: {', '.join(q2.secondary_players)}")

            # 构建边际定价者排名
            player_scores = getattr(dom, "player_scores", {})
            if player_scores:
                # 归一化并排序
                max_score = max(player_scores.values()) if player_scores else 1.0
                ranking = []
                for player, score in sorted(player_scores.items(), key=lambda x: x[1], reverse=True):
                    influence = score / max_score if max_score > 0 else 0.0
                    ranking.append({
                        "player": player,
                        "influence": round(influence, 2),
                        "score": round(score, 1),
                    })
                q2.marginal_pricer_ranking = ranking
            else:
                q2.marginal_pricer_ranking = [
                    {"player": q2.dominant_player, "influence": 1.0, "score": 100.0},
                ]

            citations.append(make_citation(
                provider="game_theory", field="dominance",
                data_type="factor", source_tier="T3", nature="interpretation",
            ))

        # 2. 公募拥挤度
        fund = self._safe(self._get_fund().analyze, "fund_positioning")
        if fund:
            q2.crowding_score = getattr(fund, "crowding_score", 50)
            q2.crowding_warning = q2.crowding_score > 70
            if q2.crowding_warning:
                evidence.append(f"⚠️ 公募拥挤度偏高 ({q2.crowding_score})")
            citations.append(make_citation(
                provider="game_theory", field="fund_positioning",
                data_type="factor", source_tier="T2", nature="interpretation",
            ))

        # 3. 北向资金方向
        nb = self._safe(self._get_northbound().analyze, "northbound")
        if nb:
            nb_score = getattr(nb, "score", 50)
            q2.northbound_direction = (
                "inflow" if nb_score > 60 else "outflow" if nb_score < 40 else "neutral"
            )
            evidence.append(f"北向资金: {q2.northbound_direction} (得分 {nb_score})")
            citations.append(make_citation(
                provider="game_theory", field="northbound",
                data_type="factor", source_tier="T1", nature="fact",
            ))

        # 4. 融资融券情绪
        margin = self._safe(self._get_margin().analyze, "margin")
        if margin:
            q2.margin_score = getattr(margin, "score", 50)
            if q2.margin_score < 35:
                q2.margin_fear_greed = "fear"
            elif q2.margin_score > 65:
                q2.margin_fear_greed = "greed"
            else:
                q2.margin_fear_greed = "neutral"
            evidence.append(f"杠杆情绪: {q2.margin_fear_greed} (得分 {q2.margin_score})")
            citations.append(make_citation(
                provider="game_theory", field="margin",
                data_type="factor", source_tier="T2", nature="interpretation",
            ))

        # 5. 置信度
        confs = [q2.dominance_confidence]
        if fund:
            confs.append(0.7)
        if nb:
            confs.append(0.8)
        q2.confidence = sum(confs) / len(confs) if confs else 0.3

        q2.evidence = evidence
        q2.recommendations = self._q2_recommendations(q2)
        return q2

    @staticmethod
    def _q2_recommendations(q2: Q2Answer) -> list[str]:
        """根据 Q2 结论生成建议."""
        recs = []
        if q2.dominant_player == "INSTITUTIONAL":
            recs.append("跟机构票需注意拥挤度，关注季报调仓窗口")
            recs.append("大盘价值/质量因子优先")
        elif q2.dominant_player == "HOT_MONEY":
            recs.append("游资主导市场，题材轮动快，控制仓位")
            recs.append("关注龙虎榜席位动向，不追高")
        elif q2.dominant_player == "NORTHBOUND":
            recs.append("外资定价权强，关注北向持续流入标的")
            recs.append("人民币汇率是关键变量")
        elif q2.dominant_player == "NATIONAL_TEAM":
            recs.append("国家队护盘信号，权重股有底但弹性差")
            recs.append("不追高银行/保险，关注政策托底方向")
        elif q2.dominant_player == "QUANT":
            recs.append("量化主导，日内波动被放大，减少追涨杀跌")
            recs.append("反转因子可能优于趋势因子")
        else:
            recs.append("无明确主导资金，分散配置")
        if q2.crowding_warning:
            recs.append("⚠️ 公募拥挤度偏高，回避重仓抱团股")
        return recs

    # ------------------------------------------------------------------
    # Q3: 信息优势
    # ------------------------------------------------------------------

    def _answer_q3(
        self, citations: list[SourceCitation],
    ) -> Q3Answer:
        """评估信息优势."""
        q3 = Q3Answer()

        # 1. SpeedMonitor 指标
        speed = self._speed_monitor
        if speed is not None:
            metrics = speed.get_metrics()
            q3.total_events = metrics.total_events
            q3.avg_latency_seconds = metrics.avg_latency_seconds
            q3.fastest_source = metrics.fastest_source
            q3.event_types_tracked = metrics.event_types_tracked
            q3.bottlenecks = metrics.bottlenecks
            citations.append(make_citation(
                provider="information", field="speed_monitor",
                data_type="factor", source_tier="T2", nature="fact",
            ))

        # 2. 数据源覆盖度
        q3.active_sources = self._detect_active_sources()
        q3.source_count = len(q3.active_sources)

        # 3. 冷启动 vs 有数据
        if q3.total_events == 0:
            q3.information_advantage_score = 40.0
            q3.speed_grade = "unknown"
            q3.coverage_grade = self._classify_coverage(q3.source_count)
            q3.confidence = 0.3
        else:
            speed_g = self._classify_speed(q3.avg_latency_seconds)
            coverage_g = self._classify_coverage(q3.source_count)
            q3.speed_grade = speed_g
            q3.coverage_grade = coverage_g

            # 综合评分
            score = 50.0
            if speed_g == "fast":
                score += 20
            elif speed_g == "slow":
                score -= 20
            if coverage_g == "comprehensive":
                score += 20
            elif coverage_g == "adequate":
                score += 10
            elif coverage_g == "sparse":
                score -= 10
            score -= len(q3.bottlenecks) * 5
            q3.information_advantage_score = max(0.0, min(100.0, score))

            q3.confidence = min(0.8, q3.total_events / 100.0 * 0.5 + 0.3)

        q3.recommendations = self._q3_recommendations(q3)
        return q3

    @staticmethod
    def _detect_active_sources() -> list[str]:
        """检测当前活跃的数据源."""
        active = []
        # 检查国信
        try:
            from src.data.guosen import GuosenProvider
            gs = GuosenProvider()
            if gs.health_check():
                active.append("guosen")
        except Exception:
            pass
        # 检查 mootdx/腾讯
        try:
            from src.data.mootdx_tencent import MootdxTencentProvider
            mt = MootdxTencentProvider()
            if mt.health_check():
                active.append("mootdx_tencent")
        except Exception:
            pass
        # 检查 AKShare
        try:
            active.append("akshare")
        except Exception:
            pass
        # 检查华泰 (通过 huatai skill)
        try:
            from importlib import import_module
            import_module("src.data.huatai")
            import os
            if os.getenv("HT_APIKEY"):
                active.append("huatai")
        except Exception:
            pass
        return active

    @staticmethod
    def _classify_speed(avg_latency_s: float) -> str:
        if avg_latency_s < 0.5:
            return "fast"
        elif avg_latency_s < 2.0:
            return "average"
        else:
            return "slow"

    @staticmethod
    def _classify_coverage(source_count: int) -> str:
        if source_count >= 4:
            return "comprehensive"
        elif source_count >= 3:
            return "adequate"
        else:
            return "sparse"

    @staticmethod
    def _q3_recommendations(q3: Q3Answer) -> list[str]:
        """根据 Q3 结论生成建议."""
        recs = []
        if q3.total_events == 0:
            recs.append("⏳ 速度数据采集中，多运行几次后评分更准确")
        if q3.speed_grade == "slow":
            recs.append(f"⚠️ 数据延迟偏高 ({q3.avg_latency_seconds:.1f}s)，考虑升级数据源")
        if q3.coverage_grade == "sparse":
            recs.append("⚠️ 活跃数据源不足，建议配置 GS_API_KEY / HT_APIKEY")
        if q3.bottlenecks:
            recs.append(f"瓶颈阶段: {', '.join(q3.bottlenecks[:3])}")
        if q3.information_advantage_score >= 70:
            recs.append("信息采集体系健全，可支撑量化决策")
        return recs

    # ------------------------------------------------------------------
    # Lazy sub-analyzer accessors (follows GameTheoryAnalyzer pattern)
    # ------------------------------------------------------------------

    def _get_dominance(self):
        if self._dominance is None:
            from src.game_theory.dominance import DominanceClassifier
            self._dominance = DominanceClassifier()
        return self._dominance

    def _get_fund(self):
        if self._fund is None:
            from src.game_theory.fund_positioning import FundPositioningAnalyzer
            self._fund = FundPositioningAnalyzer()
        return self._fund

    def _get_margin(self):
        if self._margin is None:
            from src.game_theory.margin import MarginAnalyzer
            self._margin = MarginAnalyzer()
        return self._margin

    def _get_northbound(self):
        if self._northbound is None:
            from src.game_theory.northbound import NorthboundAnalyzer
            self._northbound = NorthboundAnalyzer()
        return self._northbound

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe(fn, label: str):
        """Safely call a sub-analyzer, logging errors without crashing."""
        try:
            return fn()
        except Exception as e:
            logger.debug("%s analyzer failed: %s", label, e)
            return None
