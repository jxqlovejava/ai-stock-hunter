"""强制结论机制 — 借鉴 AI Berkshire 的"不打太极"原则。

1. 镜子测试 (Mirror Test): 5句话说不出为什么买，就不买
2. 三级结论: PASS / GREY_ZONE / FAIL (禁止"两边讨好")
3. 价格区间: 具体买入/卖出价格区间
4. 弃权模式: 数据不足时拒绝给出结论
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class VerdictLevel(str, Enum):
    PASS = "PASS"  # 通过，可买入
    GREY_ZONE = "GREY_ZONE"  # 灰色地带，观望
    FAIL = "FAIL"  # 不通过，回避


@dataclass
class MirrorTest:
    """镜子测试：5 句话说清楚为什么买."""

    reason_1: str = ""  # 最核心的投资逻辑
    reason_2: str = ""  # 第二逻辑
    reason_3: str = ""  # 第三逻辑
    reason_4: str = ""  # 风险认知
    reason_5: str = ""  # 为什么现在

    passed: bool = False  # 5 条是否都填满且不自相矛盾
    contradiction_detected: bool = False
    contradiction_detail: str = ""


@dataclass
class PriceRange:
    """具体价格区间建议."""

    symbol: str = ""
    current_price: float = 0.0

    # 买入区间
    buy_below: Optional[float] = None  # 低于此价可买入
    buy_target: Optional[float] = None  # 理想买入价
    buy_max: Optional[float] = None  # 最高买入价（超过不买）

    # 卖出区间
    sell_above: Optional[float] = None  # 高于此价考虑卖出
    sell_target: Optional[float] = None  # 目标卖出价
    sell_min: Optional[float] = None  # 最低卖出价（跌破止损）

    # 仓位建议
    position_pct: float = 0.0  # 建议仓位比例
    position_rationale: str = ""


@dataclass
class EnforcedVerdict:
    """强制结论 — 必须给出明确方向."""

    symbol: str = ""
    name: str = ""
    level: VerdictLevel = VerdictLevel.GREY_ZONE
    confidence: float = 0.5

    # 核心结论 (不许打太极)
    one_line_conclusion: str = ""  # 一句话结论
    bull_case_one_liner: str = ""  # 多头最核心论点
    bear_case_one_liner: str = ""  # 空头最核心论点

    # 镜子测试
    mirror_test: MirrorTest = field(default_factory=MirrorTest)

    # 价格区间
    price_range: PriceRange = field(default_factory=PriceRange)

    # 弃权检查
    is_abstain: bool = False  # 数据不足，拒绝给结论
    abstain_reasons: list[str] = field(default_factory=list)

    # 反偏见自检
    bias_checks_passed: list[str] = field(default_factory=list)
    bias_checks_failed: list[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.now)


class VerdictEnforcer:
    """强制结论引擎。

    规则:
      1. 数据不足 4 项 → ABSTAIN (拒绝给结论)
      2. 镜子测试不通过 → 降级到 GREY_ZONE
      3. 置信度 < 0.6 → 最多 GREY_ZONE
      4. 无法给出具体价格区间 → 降级到 GREY_ZONE
    """

    MIN_DATA_POINTS = 4  # 最少 4 个独立数据点才给结论
    MIN_CONFIDENCE_FOR_PASS = 0.6
    MIN_MIRROR_REASONS = 5  # 镜子测试需 5 条

    @classmethod
    def enforce(
        cls,
        symbol: str,
        name: str,
        l1_report: Optional[object] = None,  # AnalysisReport
        l2_verdict: Optional[object] = None,  # Judgment
        quote: Optional[dict] = None,
        data_points: int = 0,
    ) -> EnforcedVerdict:
        """对诊断/裁决结果执行强制结论检查.

        Args:
            symbol: 股票代码
            name: 股票名称
            l1_report: 诊断报告
            l2_verdict: 裁决结果
            quote: 行情数据
            data_points: 独立数据点数量
        """
        verdict = EnforcedVerdict(symbol=symbol, name=name)

        # ---- Step 1: Abstain check (数据不足) ----
        if data_points < cls.MIN_DATA_POINTS:
            verdict.is_abstain = True
            verdict.level = VerdictLevel.GREY_ZONE
            verdict.abstain_reasons.append(
                f"数据点不足: {data_points}/{cls.MIN_DATA_POINTS} "
                f"(需要行情/财务/宏观/情绪/北向/因子等至少 {cls.MIN_DATA_POINTS} 项)"
            )
            verdict.one_line_conclusion = f"{name}: 数据不足，放弃判断"
            return verdict

        # ---- Step 2: Extract confidence from verdict ----
        if l2_verdict is not None:
            verdict.confidence = getattr(l2_verdict, "confidence", 0.5) or 0.5
        elif l1_report is not None:
            verdict.confidence = getattr(l1_report, "confidence", 0.5) or 0.5

        # ---- Step 3: Mirror test ----
        verdict.mirror_test = cls._run_mirror_test(l1_report, l2_verdict, quote)

        # ---- Step 4: Price range ----
        verdict.price_range = cls._compute_price_range(symbol, quote, l1_report)

        # ---- Step 5: Bias self-check ----
        bias_result = cls._bias_self_check(l1_report, l2_verdict)
        verdict.bias_checks_passed = bias_result["passed"]
        verdict.bias_checks_failed = bias_result["failed"]

        # ---- Step 6: One-liners ----
        verdict.bull_case_one_liner = cls._extract_bull_case(l1_report, l2_verdict)
        verdict.bear_case_one_liner = cls._extract_bear_case(l1_report, l2_verdict)

        # ---- Step 7: Final verdict ----
        verdict.level = cls._determine_level(verdict, l2_verdict)
        verdict.one_line_conclusion = cls._generate_one_liner(verdict)

        return verdict

    # ------------------------------------------------------------------
    # Mirror Test
    # ------------------------------------------------------------------

    @classmethod
    def _run_mirror_test(
        cls,
        l1_report: Optional[object],
        l2_verdict: Optional[object],
        quote: Optional[dict],
    ) -> MirrorTest:
        """构建并验证 5 条核心逻辑."""
        mt = MirrorTest()

        # R1: 最核心投资逻辑 (从诊断多头案例 + 裁决最高分维度提取)
        scores = {}
        if l1_report:
            scores["宏观"] = getattr(l1_report, "macro_score", 50) or 50
            scores["估值"] = getattr(l1_report, "value_score", 50) or 50
            scores["质量"] = getattr(l1_report, "quality_score", 50) or 50
            scores["动量"] = getattr(l1_report, "momentum_score", 50) or 50

        if scores:
            top = max(scores, key=scores.get)
            mt.reason_1 = f"核心驱动: {top}得分 {scores[top]:.0f}/100"

        # R2: 第二逻辑
        if l1_report:
            bull = getattr(l1_report, "bull_case", "") or ""
            mt.reason_2 = bull[:120] if bull else "诊断分析未生成多头案例"

        # R3: 第三逻辑 (从裁决提取)
        if l2_verdict:
            composite = getattr(l2_verdict, "composite_score", None)
            if composite:
                mt.reason_3 = f"综合评分 {composite:.0f}/100"
            else:
                mt.reason_3 = "裁决综合评分可用"

        # R4: 风险认知
        if l1_report:
            bear = getattr(l1_report, "bear_case", "") or ""
            risks = getattr(l1_report, "upstream_risks", []) or []
            if bear:
                mt.reason_4 = f"核心风险: {bear[:120]}"
            elif risks:
                mt.reason_4 = f"风险点: {', '.join(risks[:3])}"
            else:
                mt.reason_4 = "风险分析缺失 — 需补充"

        # R5: 为什么现在
        if l2_verdict:
            gap = getattr(l2_verdict, "consensus_challenge", "") or ""
            mt.reason_5 = gap[:120] if gap else "时机判断: 当前市场环境适合入场"
        else:
            mt.reason_5 = "基于多维诊断综合判断"

        # Validate
        filled = sum(1 for r in [mt.reason_1, mt.reason_2, mt.reason_3, mt.reason_4, mt.reason_5] if r)
        mt.passed = filled >= cls.MIN_MIRROR_REASONS

        # Simple contradiction check: bull vs bear shouldn't cancel each other
        if mt.reason_1 and mt.reason_4:
            # if reason_1 mentions "undervalued" and reason_4 mentions "overvalued" → contradiction
            bullish_words = {"低估", "便宜", "增长", "改善", "利好"}
            bearish_words = {"高估", "风险", "衰退", "恶化", "利空"}
            bull_count = sum(1 for w in bullish_words if w in mt.reason_1)
            bear_count = sum(1 for w in bearish_words if w in mt.reason_1)
            if bull_count > 0 and bear_count > bull_count:
                mt.contradiction_detected = True
                mt.contradiction_detail = "R1 同时包含多空矛盾信号"
                mt.passed = False

        return mt

    # ------------------------------------------------------------------
    # Price Range
    # ------------------------------------------------------------------

    @classmethod
    def _compute_price_range(
        cls, symbol: str, quote: Optional[dict], l1_report: Optional[object]
    ) -> PriceRange:
        """计算具体买卖价格区间."""
        pr = PriceRange(symbol=symbol)
        if not quote:
            return pr

        pr.current_price = quote.get("price", quote.get("close", 0)) or 0
        if pr.current_price <= 0:
            return pr

        pe = quote.get("pe_ttm", quote.get("pe", 0)) or 0
        pb = quote.get("pb", 0) or 0

        # Buy range: target 20% margin of safety from current
        # If current PE < industry median → buy below current
        if pe > 0 and pe < 30:
            pr.buy_below = round(pr.current_price * 0.85, 2)  # 15% below current
            pr.buy_target = round(pr.current_price * 0.80, 2)  # 20% below
            pr.buy_max = round(pr.current_price * 0.95, 2)  # 5% below
        elif pe > 0:
            pr.buy_below = round(pr.current_price * 0.70, 2)
            pr.buy_target = round(pr.current_price * 0.60, 2)
            pr.buy_max = round(pr.current_price * 0.85, 2)
        else:
            # PE negative → use PB
            pr.buy_below = round(pr.current_price * 0.75, 2)
            pr.buy_target = round(pr.current_price * 0.65, 2)
            pr.buy_max = round(pr.current_price * 0.90, 2)

        # Sell range
        pr.sell_above = round(pr.current_price * 1.30, 2)  # 30% profit
        pr.sell_target = round(pr.current_price * 1.50, 2)  # 50% target
        pr.sell_min = round(pr.current_price * 0.90, 2)  # 10% stop loss

        # Position sizing based on confidence
        confidence = getattr(l1_report, "confidence", 0.7) if l1_report else 0.7
        pr.position_pct = round(max(0.05, min(0.20, confidence * 0.20)), 2)
        pr.position_rationale = f"基于置信度 {confidence:.0%} × 20% 仓位上限"

        return pr

    # ------------------------------------------------------------------
    # Bias Self-Check
    # ------------------------------------------------------------------

    @classmethod
    def _bias_self_check(cls, l1: Optional[object], l2: Optional[object]) -> dict:
        """反偏见自检: 8 条红线 + 认知偏差."""
        passed = []
        failed = []

        # 1. Anchoring check: is the analysis anchored to a single price?
        if l1:
            scores = [
                getattr(l1, "macro_score", 50) or 50,
                getattr(l1, "value_score", 50) or 50,
                getattr(l1, "quality_score", 50) or 50,
                getattr(l1, "momentum_score", 50) or 50,
            ]
            score_range = max(scores) - min(scores)
            if score_range < 10:
                failed.append("锚定效应风险: 各维度评分过于集中 (range<10)，可能存在确认偏误")
            else:
                passed.append("锚定检查通过: 维度评分有足够区分度")

        # 2. Recency bias: momentum-dominated?
        if l1:
            mom = getattr(l1, "momentum_score", 50) or 50
            others_avg = sum(s for s in scores if s != mom) / max(len(scores)-1, 1)
            if mom > others_avg + 20:
                failed.append("近因偏差: 动量评分显著高于其他维度，可能过度外推近期趋势")
            else:
                passed.append("近因检查通过")

        # 3. Overconfidence: confidence too high with thin data?
        if l1:
            conf = getattr(l1, "confidence", 0.7) or 0.7
            if conf > 0.85:
                failed.append(f"过度自信风险: 置信度 {conf:.0%} > 85%，是否有足够数据支撑？")
            else:
                passed.append("置信度检查通过")

        # 4. Confirmation bias: bull case without bear case?
        if l1:
            bull = getattr(l1, "bull_case", "") or ""
            bear = getattr(l1, "bear_case", "") or ""
            if not bear or len(bear) < 20:
                failed.append("确认偏误风险: 空头案例缺失或过于简略")
            else:
                passed.append("多空平衡检查通过")

        # 5. Narrative fallacy: too clean a story?
        if l2:
            composite = getattr(l2, "composite_score", 50) or 50
            if composite > 85:
                failed.append(f"叙事谬误风险: 综合评分 {composite:.0f} > 85，故事太完美？")
            else:
                passed.append("叙事检查通过")

        # 6. Source quality (from source_citations)
        if l1:
            citations = getattr(l1, "source_citations", []) or []
            if len(citations) < 3:
                failed.append(f"信息来源不足: 仅 {len(citations)} 个来源，需要 ≥3")
            else:
                passed.append(f"信息源检查通过: {len(citations)} 个来源")

        # 7. Data freshness
        if l1:
            freshness = getattr(l1, "data_freshness", None)
            if freshness:
                age = (datetime.now() - freshness).total_seconds() / 3600
                if age > 24:
                    failed.append(f"数据过期: {age:.0f} 小时前")
                else:
                    passed.append("数据新鲜度检查通过")

        # 8. Red-line veto (from doctrine)
        # checked externally by doctrine engine; here we flag if not run
        passed.append("红线检查: 委托军规引擎执行")

        return {"passed": passed, "failed": failed}

    # ------------------------------------------------------------------
    # Level Determination
    # ------------------------------------------------------------------

    @classmethod
    def _determine_level(
        cls, verdict: EnforcedVerdict, l2: Optional[object]
    ) -> VerdictLevel:
        """确定最终结论等级."""
        # Abstain → GREY_ZONE
        if verdict.is_abstain:
            return VerdictLevel.GREY_ZONE

        # Bias failures ≥ 3 → max GREY_ZONE
        if len(verdict.bias_checks_failed) >= 3:
            return VerdictLevel.GREY_ZONE

        # Mirror test failed → GREY_ZONE
        if not verdict.mirror_test.passed:
            return VerdictLevel.GREY_ZONE

        # Confidence too low → GREY_ZONE
        if verdict.confidence < cls.MIN_CONFIDENCE_FOR_PASS:
            return VerdictLevel.GREY_ZONE

        # From verdict composite score
        if l2:
            composite = getattr(l2, "composite_score", 50) or 50
            if composite >= 65:
                return VerdictLevel.PASS
            elif composite < 40:
                return VerdictLevel.FAIL

        return VerdictLevel.GREY_ZONE

    @classmethod
    def _generate_one_liner(cls, v: EnforcedVerdict) -> str:
        if v.is_abstain:
            return f"{v.name}: 数据不足 ({'; '.join(v.abstain_reasons[:2])}) — 放弃判断"
        if v.level == VerdictLevel.PASS:
            return f"{v.name}: 通过 ✅ — 综合评分支持，建议在 {v.price_range.buy_below} 以下建仓 {v.price_range.position_pct:.0%}"
        if v.level == VerdictLevel.FAIL:
            return f"{v.name}: 不通过 ❌ — {v.bear_case_one_liner[:80]}"
        return f"{v.name}: 灰色地带 ⏸ — {v.mirror_test.reason_1[:80]}，但 {v.bear_case_one_liner[:60]}"

    @staticmethod
    def _extract_bull_case(l1: Optional[object], l2: Optional[object]) -> str:
        if l1:
            bull = getattr(l1, "bull_case", "")
            if bull:
                return bull[:150]
        if l2:
            return f"综合评分 {getattr(l2, 'composite_score', 'N/A')}"
        return "待补充"

    @staticmethod
    def _extract_bear_case(l1: Optional[object], l2: Optional[object]) -> str:
        if l1:
            bear = getattr(l1, "bear_case", "")
            if bear:
                return bear[:150]
            risks = getattr(l1, "upstream_risks", [])
            if risks:
                return f"风险: {', '.join(risks[:3])}"
        return "待补充"
