"""反偏见机制 — 借鉴 AI Berkshire 的内置防护。

1. Decimal 精度: 财务计算使用 decimal.Decimal，杜绝 LLM 浮点心算出错
2. 8 条红线一票否决: 硬性门槛，任何一条触发 → 直接 FAIL
3. 信息丰富度评级: 来源数量 × 多样性 × 独立性 → 0-100 评分
4. 认知偏差检测: 锚定/近因/确认/过度自信/框架/叙事谬误 6 维自检
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 8 Red Lines — 一票否决
# ---------------------------------------------------------------------------

class RedLine(Enum):
    RL1 = "ST_or_Delisting"  # ST/*ST 或退市风险
    RL2 = "Audit_NonStandard"  # 审计意见非标
    RL3 = "Fraud_Or_Violation"  # 近12月违规/财务造假
    RL4 = "Pledge_Crisis"  # 大股东质押 >80%
    RL5 = "Goodwill_Bomb"  # 商誉/净资产 >50%
    RL6 = "Cashflow_Fake"  # OCF连续3年为负 且 NI>0 (纸面利润)
    RL7 = "Debt_Death_Spiral"  # 有息负债/EBITDA >10 且 利息保障<1
    RL8 = "Insider_Dumping"  # 高管连续6个月净减持 >1%总股本


@dataclass
class RedLineCheck:
    """单条红线检查结果."""

    line: RedLine
    triggered: bool = False
    detail: str = ""
    severity: str = "CRITICAL"  # all red lines are CRITICAL


@dataclass
class RedLineReport:
    """8 条红线综合报告."""

    checks: list[RedLineCheck] = field(default_factory=list)
    any_triggered: bool = False
    triggered_lines: list[str] = field(default_factory=list)
    verdict: str = ""  # "CLEAN" / "BLOCKED"


# ---------------------------------------------------------------------------
# Info Richness
# ---------------------------------------------------------------------------

@dataclass
class InfoRichnessScore:
    """信息丰富度评级."""

    score: int = 0  # 0-100
    source_count: int = 0
    source_diversity: int = 0  # 独立来源类型数
    data_freshness_score: int = 0  # 0-100
    completeness: float = 0.0  # 0.0-1.0 覆盖度
    gaps: list[str] = field(default_factory=list)
    rating: str = ""  # "RICH" / "ADEQUATE" / "THIN" / "INSUFFICIENT"


# ---------------------------------------------------------------------------
# Cognitive Bias Detection
# ---------------------------------------------------------------------------

@dataclass
class BiasReport:
    """认知偏差检测报告."""

    symbol: str = ""

    # 6 biases
    anchoring_detected: bool = False  # 锚定效应
    anchoring_detail: str = ""
    recency_detected: bool = False  # 近因偏差
    recency_detail: str = ""
    confirmation_detected: bool = False  # 确认偏误
    confirmation_detail: str = ""
    overconfidence_detected: bool = False  # 过度自信
    overconfidence_detail: str = ""
    framing_detected: bool = False  # 框架效应
    framing_detail: str = ""
    narrative_fallacy: bool = False  # 叙事谬误
    narrative_detail: str = ""

    # Summary
    total_biases: int = 0
    severity: str = ""  # "clean" / "mild" / "significant" / "severe"


# ---------------------------------------------------------------------------
# Anti-Bias Engine
# ---------------------------------------------------------------------------

class AntiBiasEngine:
    """综合反偏见引擎."""

    @classmethod
    def check_red_lines(
        cls,
        quote: Optional[dict] = None,
        financials: Optional[list] = None,
        executive: Optional[dict] = None,
    ) -> RedLineReport:
        """执行 8 条红线检查."""
        report = RedLineReport()
        checks = []

        # RL1: ST/Delisting
        if quote:
            name = quote.get("name", "")
            is_st = quote.get("is_st", False) or "ST" in str(name).upper()
            is_delist = quote.get("is_delisting_risk", False)
            rl1 = RedLineCheck(
                line=RedLine.RL1,
                triggered=is_st or is_delist,
                detail=f"ST={is_st}, 退市风险={is_delist}",
            )
            checks.append(rl1)

            # RL3: Recent violation (12 months)
            violation = quote.get("recent_violation", False)
            rl3 = RedLineCheck(
                line=RedLine.RL3,
                triggered=bool(violation),
                detail=f"近12月违规={violation}" if violation else "无违规记录",
            )
            checks.append(rl3)

            # RL4: Pledge crisis
            pledge = quote.get("pledge_ratio", 0) or 0
            rl4 = RedLineCheck(
                line=RedLine.RL4,
                triggered=pledge > 0.80,
                detail=f"大股东质押率 {pledge:.1%} {'> 80% 红线!' if pledge > 0.8 else ''}",
            )
            checks.append(rl4)

            # RL5: Goodwill bomb
            goodwill = quote.get("goodwill_to_equity", 0) or 0
            rl5 = RedLineCheck(
                line=RedLine.RL5,
                triggered=goodwill > 0.5,
                detail=f"商誉/净资产 {goodwill:.1%} {'> 50% 红线!' if goodwill > 0.5 else ''}",
            )
            checks.append(rl5)

        # RL2: Audit opinion
        if quote:
            audit = quote.get("audit_opinion", "standard")
            rl2 = RedLineCheck(
                line=RedLine.RL2,
                triggered=audit != "standard",
                detail=f"审计意见: {audit}",
            )
            checks.append(rl2)

        # RL6: OCF < 0 for 3 consecutive years while NI > 0
        if financials and len(financials) >= 3:
            ocf_neg_count = sum(
                1 for f in financials[-3:]
                if (f.get("operating_cashflow", 0) or 0) < 0
            )
            ni_positive = all(
                (f.get("net_profit", 0) or 0) > 0
                for f in financials[-3:]
            )
            rl6 = RedLineCheck(
                line=RedLine.RL6,
                triggered=(ocf_neg_count >= 3 and ni_positive),
                detail=f"OCF连续{ocf_neg_count}季为负，NI却为正 — 纸面利润风险",
            )
            checks.append(rl6)

            # RL7: Debt death spiral
            ebitda = sum((f.get("ebit", 0) or 0) + (f.get("depreciation", 0) or 0) for f in financials[-4:])
            debt = sum(f.get("total_debt", f.get("total_assets", 1) or 1) - (f.get("total_equity", 1) or 1) for f in financials[-4:])
            interest = sum(f.get("interest_expense", 0) or 0 for f in financials[-4:])
            debt_ebitda = safe_divide(debt, ebitda, Decimal("999"))
            int_cov = safe_divide(ebitda, interest, Decimal("999"))
            rl7 = RedLineCheck(
                line=RedLine.RL7,
                triggered=(float(debt_ebitda) > 10 and float(int_cov) < 1),
                detail=f"有息负债/EBITDA={float(debt_ebitda):.1f}, 利息保障={float(int_cov):.1f}",
            )
            checks.append(rl7)

        # RL8: Insider dumping
        if executive:
            trades = executive.get("trades", [])
            if trades:
                recent_sells = [
                    t for t in trades
                    if t.get("trade_type") == "sell"
                    and t.get("volume", 0) > 0
                ]
                total_sold = sum(t.get("volume", 0) for t in recent_sells)
                rl8 = RedLineCheck(
                    line=RedLine.RL8,
                    triggered=(len(recent_sells) >= 6 and total_sold > 100000),
                    detail=f"高管连续{len(recent_sells)}月净减持 {total_sold:,}股",
                )
                checks.append(rl8)

        report.checks = checks
        report.triggered_lines = [c.line.value for c in checks if c.triggered]
        report.any_triggered = len(report.triggered_lines) > 0
        report.verdict = "BLOCKED" if report.any_triggered else "CLEAN"

        return report

    # ------------------------------------------------------------------
    # Info Richness
    # ------------------------------------------------------------------

    @classmethod
    def rate_info_richness(
        cls,
        source_citations: Optional[list] = None,
        data_points: Optional[dict[str, bool]] = None,
        data_freshness: Optional[datetime] = None,
    ) -> InfoRichnessScore:
        """Rate information richness: sources × diversity × freshness.

        Args:
            source_citations: List of SourceCitation objects.
            data_points: Dict of {category: available?} e.g. {"quote": True, "financials": True}.
            data_freshness: Most recent data fetch timestamp.
        """
        score = InfoRichnessScore()

        # Source count (max 30 points)
        citations = source_citations or []
        score.source_count = len(citations)
        if score.source_count >= 6:
            score.score += 30
        elif score.source_count >= 4:
            score.score += 20
        elif score.source_count >= 2:
            score.score += 10
        else:
            score.gaps.append("数据来源不足 (需 ≥2)")

        # Source diversity (max 30 points)
        if citations:
            providers = set()
            for c in citations:
                p = getattr(c, "provider", "unknown")
                providers.add(p)
            score.source_diversity = len(providers)
            if score.source_diversity >= 4:
                score.score += 30
            elif score.source_diversity >= 2:
                score.score += 20
            elif score.source_diversity >= 1:
                score.score += 10
            if score.source_diversity < 2:
                score.gaps.append("来源类型单一 (需 ≥2 独立来源)")
        else:
            score.gaps.append("无来源引用")

        # Completeness (max 20 points)
        dp = data_points or {}
        categories = ["quote", "financials", "macro", "sentiment", "northbound", "earnings"]
        available = sum(1 for c in categories if dp.get(c))
        score.completeness = available / len(categories)
        score.score += int(score.completeness * 20)
        for c in categories:
            if not dp.get(c):
                score.gaps.append(f"缺失: {c}")

        # Freshness (max 20 points)
        if data_freshness:
            age_hours = (datetime.now() - data_freshness).total_seconds() / 3600
            if age_hours < 1:
                score.data_freshness_score = 20
            elif age_hours < 6:
                score.data_freshness_score = 15
            elif age_hours < 24:
                score.data_freshness_score = 10
            elif age_hours < 72:
                score.data_freshness_score = 5
            else:
                score.data_freshness_score = 0
                score.gaps.append(f"数据过期 ({age_hours:.0f}h)")
            score.score += score.data_freshness_score
        else:
            score.gaps.append("无数据新鲜度信息")

        # Rating
        if score.score >= 80:
            score.rating = "RICH"
        elif score.score >= 50:
            score.rating = "ADEQUATE"
        elif score.score >= 30:
            score.rating = "THIN"
        else:
            score.rating = "INSUFFICIENT"

        return score

    # ------------------------------------------------------------------
    # Cognitive Bias Detection
    # ------------------------------------------------------------------

    @classmethod
    def detect_biases(
        cls,
        l1_report: Optional[object] = None,
        l2_verdict: Optional[object] = None,
        price_history: Optional[list[float]] = None,
    ) -> BiasReport:
        """6 维认知偏差检测."""
        report = BiasReport()
        if l1_report:
            report.symbol = getattr(l1_report, "symbol", "")

        scores = []
        if l1_report:
            scores = [
                getattr(l1_report, "macro_score", 50) or 50,
                getattr(l1_report, "value_score", 50) or 50,
                getattr(l1_report, "quality_score", 50) or 50,
                getattr(l1_report, "momentum_score", 50) or 50,
            ]

        # 1. Anchoring: all scores clustered tightly (no differentiation = anchored to a single narrative)
        if scores and len(scores) >= 4:
            score_range = max(scores) - min(scores)
            if score_range < 8:
                report.anchoring_detected = True
                report.anchoring_detail = f"评分范围仅 {score_range:.0f} 分 — 锚定在单一叙事，缺乏维度区分"
                report.total_biases += 1

        # 2. Recency: momentum dominates all other dimensions
        if l1_report and len(scores) >= 4:
            mom = getattr(l1_report, "momentum_score", 50) or 50
            others = [s for s in scores if s != mom]
            if others:
                avg_other = sum(others) / len(others)
                if mom > avg_other + 25:
                    report.recency_detected = True
                    report.recency_detail = f"动量({mom:.0f})远高于其他维度均({avg_other:.0f}) — 过度外推近期趋势"
                    report.total_biases += 1

        # 3. Confirmation: bull case exists but bear case is thin
        if l1_report:
            bull = getattr(l1_report, "bull_case", "") or ""
            bear = getattr(l1_report, "bear_case", "") or ""
            if bull and (not bear or len(bear) < 30):
                report.confirmation_detected = True
                report.confirmation_detail = "多头案例详尽但空头案例薄弱 (<30字) — 确认偏误"
                report.total_biases += 1

        # 4. Overconfidence: high confidence with few data sources
        if l1_report:
            conf = getattr(l1_report, "confidence", 0.5) or 0.5
            citations = getattr(l1_report, "source_citations", []) or []
            if conf > 0.85 and len(citations) < 4:
                report.overconfidence_detected = True
                report.overconfidence_detail = f"置信度 {conf:.0%} 但仅 {len(citations)} 个数据源 — 过度自信"
                report.total_biases += 1

        # 5. Framing: positive sentiment all around
        if l1_report:
            sentiment = getattr(l1_report, "sentiment_signal", "NEUTRAL")
            if sentiment in ("GREED", "EXTREME"):
                report.framing_detected = True
                report.framing_detail = f"情绪框架为 {sentiment} — 可能被市场情绪带偏"
                report.total_biases += 1

        # 6. Narrative fallacy: composite score too high = "too good to be true"
        if l2_verdict:
            composite = getattr(l2_verdict, "composite_score", 50) or 50
            if composite > 88:
                report.narrative_fallacy = True
                report.narrative_detail = f"综合评分 {composite:.0f}/100 — 接近满分，故事过于完美"
                report.total_biases += 1

        # Severity
        if report.total_biases == 0:
            report.severity = "clean"
        elif report.total_biases <= 1:
            report.severity = "mild"
        elif report.total_biases <= 3:
            report.severity = "significant"
        else:
            report.severity = "severe"

        return report

    # ------------------------------------------------------------------
    # Composite check
    # ------------------------------------------------------------------

    @classmethod
    def full_check(
        cls,
        symbol: str = "",
        name: str = "",
        quote: Optional[dict] = None,
        financials: Optional[list] = None,
        executive: Optional[dict] = None,
        l1_report: Optional[object] = None,
        l2_verdict: Optional[object] = None,
        source_citations: Optional[list] = None,
        price_history: Optional[list[float]] = None,
    ) -> dict:
        """Run all anti-bias checks and return combined result."""
        red_lines = cls.check_red_lines(quote, financials, executive)
        biases = cls.detect_biases(l1_report, l2_verdict, price_history)
        data_points = {
            "quote": quote is not None,
            "financials": financials is not None and len(financials) > 0,
            "macro": l1_report is not None,
            "sentiment": l1_report is not None,
            "northbound": l1_report is not None,
            "earnings": l1_report is not None,
        }
        data_freshness = getattr(l1_report, "data_freshness", None) if l1_report else None
        info = cls.rate_info_richness(source_citations, data_points, data_freshness)

        return {
            "symbol": symbol,
            "name": name,
            "red_lines": {
                "blocked": red_lines.any_triggered,
                "triggered": red_lines.triggered_lines,
                "verdict": red_lines.verdict,
            },
            "info_richness": {
                "score": info.score,
                "rating": info.rating,
                "gaps": info.gaps,
            },
            "cognitive_biases": {
                "total": biases.total_biases,
                "severity": biases.severity,
                "details": {
                    "anchoring": biases.anchoring_detail if biases.anchoring_detected else None,
                    "recency": biases.recency_detail if biases.recency_detected else None,
                    "confirmation": biases.confirmation_detail if biases.confirmation_detected else None,
                    "overconfidence": biases.overconfidence_detail if biases.overconfidence_detected else None,
                    "framing": biases.framing_detail if biases.framing_detected else None,
                    "narrative": biases.narrative_detail if biases.narrative_fallacy else None,
                },
            },
            "overall_clean": (
                not red_lines.any_triggered
                and biases.total_biases == 0
                and info.rating in ("RICH", "ADEQUATE")
            ),
        }
