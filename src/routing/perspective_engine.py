"""四大师多视角对抗引擎 — 借鉴 AI Berkshire 的多智能体辩论机制。

四个独立视角:
  1. 巴菲特 (Buffett):   护城河+安全边际+长期持有+ROE>15%+现金流
  2. 李录 (Li Lu):       管理层文化+复利思维+10年视角+能力圈
  3. 芒格 (Munger):      逆向思维+心理学+避免愚蠢+多学科模型
  4. 彼得·林奇 (Lynch):   PEG+成长性+草根调研+分类选股

每个视角独立打分(0-5)，暴露分歧，而非取平均。
分歧越大 → 认知张力越高 → 越需要深入理解自己的赌注。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class Perspective(str, Enum):
    BUFFETT = "buffett"  # 巴菲特
    LI_LU = "li_lu"  # 李录
    MUNGER = "munger"  # 芒格
    LYNCH = "lynch"  # 彼得·林奇


@dataclass
class PerspectiveScore:
    """单个大师视角的评分."""

    perspective: Perspective
    score: float = 0.0  # 0.0-5.0
    confidence: float = 0.5

    # 核心判断
    verdict: str = ""  # "买入" / "观望" / "回避"
    one_line_thesis: str = ""  # 一句话核心论点
    key_concern: str = ""  # 最大担忧

    # 评分明细
    sub_scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    # 独特视角
    unique_insight: str = ""  # 这个视角独有的发现
    questions_to_ask: list[str] = field(default_factory=list)


@dataclass
class DebateResult:
    """四视角对抗结果."""

    symbol: str = ""
    name: str = ""

    # Individual scores
    buffett: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.BUFFETT))
    li_lu: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.LI_LU))
    munger: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.MUNGER))
    lynch: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.LYNCH))

    # Aggregate
    avg_score: float = 0.0
    score_range: float = 0.0  # max - min = 分歧度
    agreement_level: str = ""  # "consensus" / "divided" / "polarized"

    # Key tensions
    top_agreement: str = ""  # 四个视角都同意的点
    top_disagreement: str = ""  # 分歧最大的点
    tension_summary: str = ""  # 认知张力小结

    # Final recommendation
    recommendation: str = ""  # 基于辩论的综合建议
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Perspective Analyzer (rules-based, deterministic — NO LLM!)
# ---------------------------------------------------------------------------

class PerspectiveAnalyzer:
    """四大师视角评分引擎。

    基于规则而非 LLM，确保:
      - 确定性: 同样输入 → 同样输出
      - 可审计: 每项评分有明确公式
      - 低成本: 无 API 调用，纯计算
    """

    @classmethod
    def debate(
        cls,
        symbol: str,
        name: str,
        l1_report: Optional[object] = None,
        quote: Optional[dict] = None,
        financials: Optional[list] = None,
    ) -> DebateResult:
        """Run all 4 perspectives and synthesize tensions."""
        result = DebateResult(symbol=symbol, name=name)

        result.buffett = cls._score_buffett(l1_report, quote, financials)
        result.li_lu = cls._score_li_lu(l1_report, quote, financials)
        result.munger = cls._score_munger(l1_report, quote, financials)
        result.lynch = cls._score_lynch(l1_report, quote, financials)

        # Aggregate
        scores = [result.buffett.score, result.li_lu.score, result.munger.score, result.lynch.score]
        result.avg_score = sum(scores) / len(scores)
        result.score_range = max(scores) - min(scores)

        # Agreement level
        if result.score_range <= 1.0:
            result.agreement_level = "consensus"
        elif result.score_range <= 2.5:
            result.agreement_level = "divided"
        else:
            result.agreement_level = "polarized"

        # Tensions
        result.top_agreement = cls._find_agreement(result)
        result.top_disagreement = cls._find_disagreement(result)
        result.tension_summary = cls._synthesize_tension(result)
        result.recommendation = cls._synthesize_recommendation(result)

        return result

    # ------------------------------------------------------------------
    # Buffett: 护城河 + 安全边际 + ROE + FCF + 长期
    # ------------------------------------------------------------------

    @classmethod
    def _score_buffett(
        cls, l1: Optional[object], quote: Optional[dict], fin: Optional[list]
    ) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.BUFFETT)
        score = 2.5  # neutral
        evidence = []

        if l1:
            # ROE (quality proxy)
            q = getattr(l1, "quality_score", 50) or 50
            roe_score = q / 100 * 3  # 0-3
            score += roe_score - 1.5
            ps.sub_scores["quality_moat"] = round(roe_score, 2)
            if q >= 70:
                evidence.append(f"质量护城河评分 {q}/100 ≥ 70")
            elif q < 40:
                evidence.append(f"质量评分 {q}/100 < 40 — 护城河不足")

            # Value (margin of safety)
            v = getattr(l1, "value_score", 50) or 50
            val_score = v / 100 * 3
            score += val_score - 1.5
            ps.sub_scores["margin_of_safety"] = round(val_score, 2)
            if v >= 70:
                evidence.append(f"安全边际充足: 估值评分 {v}/100")

            # Macro adjustment (Buffett ignores macro, slight negative for too much macro weighting)
            m = getattr(l1, "macro_score", 50) or 50
            ps.sub_scores["predictability"] = 0.5  # Buffett: business must be predictable

        if quote:
            pe = quote.get("pe_ttm", quote.get("pe", 0)) or 0
            if 0 < pe < 20:
                score += 0.5
                evidence.append(f"PE {pe:.1f} < 20 — 估值合理 (Buffett 标准)")
            elif pe > 50:
                score -= 0.5
                evidence.append(f"PE {pe:.1f} > 50 — 巴菲特不会碰")

        ps.score = round(max(0, min(5, score)), 1)
        ps.evidence = evidence

        # Verdict
        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "护城河深+安全边际足+业务可预测 — 可以在合理价格买入"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "部分条件满足，但安全边际不够 — 等更好价格"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "不符合巴菲特投资框架 — 护城河或估值不达标"

        ps.key_concern = "估值是否足够便宜？商业模式能否持续20年？" if ps.score < 3.5 else "注意不要为质量支付过高溢价"
        ps.unique_insight = f"巴菲特视角: ROE+护城河+安全边际三维度综合 {ps.score:.1f}/5"
        ps.questions_to_ask = [
            "如果股市关闭5年，还愿意持有吗？",
            "这家公司的竞争对手能否轻易复制它的商业模式？",
        ]
        return ps

    # ------------------------------------------------------------------
    # 李录: 管理层 + 复利 + 10年 + 能力圈 + 文化
    # ------------------------------------------------------------------

    @classmethod
    def _score_li_lu(
        cls, l1: Optional[object], quote: Optional[dict], fin: Optional[list]
    ) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.LI_LU)
        score = 2.5
        evidence = []

        if l1:
            # Quality (management proxy)
            q = getattr(l1, "quality_score", 50) or 50
            ps.sub_scores["management_culture"] = round(q / 100 * 3, 2)
            score += (q / 100 * 3) - 1.5
            if q >= 65:
                evidence.append("管理层代理指标良好 (质量评分 ≥ 65)")
            else:
                evidence.append("⚠️ 质量评分偏低 — 管理层文化可能有问题")

            # Earnings revision (growth sustainability proxy)
            er = getattr(l1, "earnings_revision_score", 50) or 50
            ps.sub_scores["compounding_power"] = round(er / 100 * 2, 2)
            score += (er / 100 * 2) - 1.0

            # Alpha Lens
            alpha = getattr(l1, "alpha_profile", None)
            if alpha:
                narrative = getattr(alpha, "narrative_stage", None)
                if narrative and str(narrative) in ("emerging", "growing"):
                    score += 0.5
                    evidence.append("Alpha 叙事处于早期阶段 — 复利空间大")
                elif narrative and str(narrative) in ("crowded", "declining"):
                    score -= 0.5
                    evidence.append("叙事拥挤或衰退 — 复利空间收窄")

        # Executive risk
        if l1:
            exec_score = getattr(l1, "executive_score", 50) or 50
            exec_risks = getattr(l1, "executive_risks", []) or []
            if exec_score < 40:
                score -= 1.0
                evidence.append(f"高管风险: {len(exec_risks)} 个红旗信号")
            elif exec_score >= 70:
                score += 0.5
                evidence.append("高管评分良好")

        ps.score = round(max(0, min(5, score)), 1)
        ps.evidence = evidence

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "管理层可信+复利轨道清晰 — 愿意持有10年以上"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "复利逻辑可行但管理层有不确性 — 需深入了解"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "管理层文化有隐患 — 10年后公司存在不确定性"

        ps.key_concern = "管理层是否值得信任？10年后公司还存在吗？" if ps.score < 3.5 else "复利是否会中断？"
        ps.unique_insight = f"李录视角: 管理层+复利+10年视角综合 {ps.score:.1f}/5"
        ps.questions_to_ask = [
            "创始人还在吗？他/她的核心价值观是什么？",
            "如果核心管理层明天全部离职，公司会怎样？",
        ]
        return ps

    # ------------------------------------------------------------------
    # 芒格: 逆向思维 + 心理学 + 避免愚蠢 + 多学科
    # ------------------------------------------------------------------

    @classmethod
    def _score_munger(
        cls, l1: Optional[object], quote: Optional[dict], fin: Optional[list]
    ) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.MUNGER)
        score = 2.5
        evidence = []

        if l1:
            # Check for risks and bottlenecks (Munger: "invert, always invert")
            risks = getattr(l1, "upstream_risks", []) or []
            exec_risks = getattr(l1, "executive_risks", []) or []
            bottlenecks = getattr(l1, "bottlenecks", []) or []

            total_risks = len(risks) + len(exec_risks) + len(bottlenecks)
            if total_risks == 0:
                score += 0.5
                evidence.append("未发现显著风险信号")
            elif total_risks <= 3:
                score -= 0.5
                evidence.append(f"检测到 {total_risks} 个风险点 — 需要验证")
            else:
                score -= 1.5
                evidence.append(f"⚠️ {total_risks} 个风险点 — 芒格会说'先证明这不是个错误'")

            # Reverse the thesis: why would this FAIL?
            bear = getattr(l1, "bear_case", "") or ""
            if len(bear) > 50:
                score += 0.5
                evidence.append("空头案例充分 — 逆向思考到位")
            else:
                score -= 1.0
                evidence.append("空头案例薄弱 — 逆向思考不足，可能确认偏误")
                ps.unique_insight = "⚠️ 芒格会问: 你花了多少时间研究'为什么这个投资会失败'？空头案例太弱。"

            # Bottleneck analysis
            bottleneck = getattr(l1, "bottleneck_analysis", None)
            if bottleneck:
                bt = getattr(bottleneck, "bottleneck_type", None)
                if bt and str(bt) == "OWNER":
                    score += 1.0
                    evidence.append("瓶颈类型: OWNER — 掌握稀缺资源，有定价权")

            # Sentiment as contrarian signal
            sentiment = getattr(l1, "sentiment_signal", "NEUTRAL")
            if sentiment == "EXTREME":
                score += 1.0  # extreme fear = buying opportunity
                evidence.append("情绪极度悲观 — 逆向买入信号")
            elif sentiment == "GREED":
                score -= 1.0
                evidence.append("情绪贪婪 — 逆向卖出信号")

        ps.score = round(max(0, min(5, score)), 1)
        ps.evidence = evidence

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "逆向验证通过 — 风险可控, 没有发现致命错误"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "有些风险需要验证 — 先证明这不是个错误再考虑"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "太多红旗 — 芒格会说'避免愚蠢比追求聪明更重要'"

        ps.key_concern = "反着看：这个投资最可能的失败原因是什么？" if ps.score < 3.5 else "是否遗漏了任何可能导致永久性损失的风险？"
        ps.questions_to_ask = [
            "如果这个投资归零，最可能的原因是什么？",
            "有哪些风险是'未知的未知'？",
        ]
        return ps

    # ------------------------------------------------------------------
    # 彼得·林奇: PEG + 成长 + 分类 + 草根调研
    # ------------------------------------------------------------------

    @classmethod
    def _score_lynch(
        cls, l1: Optional[object], quote: Optional[dict], fin: Optional[list]
    ) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.LYNCH)
        score = 2.5
        evidence = []

        if l1:
            # Momentum (growth trajectory)
            mom = getattr(l1, "momentum_score", 50) or 50
            ps.sub_scores["growth_trajectory"] = round(mom / 100 * 3, 2)
            score += (mom / 100 * 3) - 1.5
            if mom >= 70:
                evidence.append("成长轨迹清晰 — 动量评分 ≥ 70")

            # Quality + Growth balance (PEG-like)
            q = getattr(l1, "quality_score", 50) or 50
            v = getattr(l1, "value_score", 50) or 50
            ps.sub_scores["peg_proxy"] = round((q * 0.6 + v * 0.4) / 100 * 3, 2)
            score += (q * 0.6 + v * 0.4) / 100 * 3 - 1.5
            if q >= 60 and v >= 60:
                evidence.append("质量+估值双优 — PEG 类指标良好")

            # Earnings revision
            er = getattr(l1, "earnings_revision_score", 50) or 50
            if er >= 70:
                score += 0.5
                evidence.append("盈利上调趋势 — 成长加速信号")

        # PE growth check
        if quote:
            pe = quote.get("pe_ttm", quote.get("pe", 0)) or 0
            if l1:
                er = getattr(l1, "earnings_revision_score", 50) or 50
                # PEG proxy: PE / earnings_growth_proxy
                if pe > 0 and er > 0:
                    peg_proxy = pe / er
                    if peg_proxy < 1:
                        score += 1.0
                        evidence.append(f"PEG 代理 {peg_proxy:.1f} < 1 — Lynch 最喜欢的估值")
                    elif peg_proxy < 2:
                        score += 0.3
                    else:
                        score -= 0.5

        ps.score = round(max(0, min(5, score)), 1)
        ps.evidence = evidence

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "PEG合理+成长确定 — 典型 Lynch 式成长股"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "成长性可接受但 PEG 不够吸引 — 等更好的入场点"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "成长性不足或估值过高 — 不属于 Lynch 六类股中任何一类"

        ps.key_concern = "成长是否可持续？PEG是否合理？" if ps.score < 3.5 else "注意'增长放缓+估值压缩'的双杀风险"
        ps.unique_insight = f"Lynch 视角: PEG+成长+分类综合 {ps.score:.1f}/5"
        ps.questions_to_ask = [
            "这家公司属于 Lynch 六类股中的哪一类？",
            "你能用三句话向一个12岁的孩子解释这家公司是做什么的吗？",
        ]
        return ps

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    @classmethod
    def _find_agreement(cls, r: DebateResult) -> str:
        """Find what all 4 perspectives agree on."""
        verdicts = [r.buffett.verdict, r.li_lu.verdict, r.munger.verdict, r.lynch.verdict]
        if all(v == "买入" for v in verdicts):
            return "四个视角一致看多 — 强烈共识"
        if all(v == "回避" for v in verdicts):
            return "四个视角一致看空 — 强烈共识回避"
        if all(v == "观望" for v in verdicts):
            return "四个视角一致认为需要观望"
        return f"无一致观点 — 分歧度 {r.score_range:.1f}/5"

    @classmethod
    def _find_disagreement(cls, r: DebateResult) -> str:
        """Find the biggest tension between perspectives."""
        high = max(r.buffett.score, r.li_lu.score, r.munger.score, r.lynch.score)
        low = min(r.buffett.score, r.li_lu.score, r.munger.score, r.lynch.score)
        high_name = [n for n, s in [("Buffett", r.buffett.score), ("李录", r.li_lu.score),
                                     ("芒格", r.munger.score), ("Lynch", r.lynch.score)] if s == high][0]
        low_name = [n for n, s in [("Buffett", r.buffett.score), ("李录", r.li_lu.score),
                                    ("芒格", r.munger.score), ("Lynch", r.lynch.score)] if s == low][0]
        return f"最大分歧: {high_name}({high:.1f}) vs {low_name}({low:.1f}) — 差 {r.score_range:.1f} 分"

    @classmethod
    def _synthesize_tension(cls, r: DebateResult) -> str:
        """Summarize cognitive tension."""
        if r.agreement_level == "consensus":
            return "四个视角高度一致 — 风险在于'所有人都看到的机会可能已被定价'"
        elif r.agreement_level == "divided":
            return f"存在 {r.score_range:.1f} 分的分歧 — 你需要决定押注哪个视角"
        else:
            return f"严重分歧 ({r.score_range:.1f} 分) — 高不确定性，需要小仓位或放弃"

    @classmethod
    def _synthesize_recommendation(cls, r: DebateResult) -> str:
        if r.agreement_level == "consensus" and r.avg_score >= 3.5:
            return "四大师一致看多 — 这是罕见的强共识机会，但注意拥挤风险"
        if r.agreement_level == "consensus" and r.avg_score <= 1.5:
            return "四大师一致看空 — 强烈建议回避"

        # Divided → look at the dissenter
        scores = [(r.buffett, "Buffett"), (r.li_lu, "李录"), (r.munger, "芒格"), (r.lynch, "Lynch")]
        highest = max(scores, key=lambda x: x[0].score)
        lowest = min(scores, key=lambda x: x[0].score)
        return (
            f"{highest[1]}视角最乐观({highest[0].score:.1f})，{lowest[1]}视角最悲观({lowest[0].score:.1f})。"
            f"建议: 理解 {lowest[1]} 的担忧后，小仓位试探或等待更好的安全边际。"
            f"\n核心张力: {highest[0].one_line_thesis[:80]} vs {lowest[0].key_concern[:80]}"
        )
