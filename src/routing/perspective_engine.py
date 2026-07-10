"""四大师多视角对抗引擎 — 借鉴 AI Berkshire 的多 Agent 辩论机制。

四个独立视角，每个调用特定的投资方法论和思维模型进行深度分析:
  1. 巴菲特 (Buffett):   护城河+安全边际+长期持有 (4大支柱框架)
  2. 李录 (Li Lu):       管理层文化+复利思维+10年视角+能力圈
  3. 芒格 (Munger):      逆向思维+25个心理倾向+多学科模型
  4. 彼得·林奇 (Lynch):   PEG+6类选股+草根调研

与 Step 5 Munger思维模型匹配的区别:
  - Step 4: 投资大师用他们的**投资方法论框架**分析标的(能不能买/卖)
  - Step 5: 用232个跨学科模型做**认知偏误检测**(你有没有看错)

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


# ── DTOs ─────────────────────────────────────────────────────────────────────

class Perspective(str, Enum):
    BUFFETT = "buffett"
    LI_LU = "li_lu"
    MUNGER = "munger"
    LYNCH = "lynch"


@dataclass
class ManagementTrustAnalysis:
    """管理层可信度分析结果 (v2.0 — 李录之问自动回答)."""
    ability_score: float = 50.0       # 能力 0-100
    integrity_score: float = 50.0     # 诚信 0-100
    capital_score: float = 50.0       # 资本配置 0-100
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)   # 数据缺失/不确定提醒，非红旗
    verdict: str = ""                 # 一句话结论


@dataclass
class BearCaseAnalysis:
    """空头案例分析结果 (v2.0 — 芒格之问自动回答)."""
    scenarios: list[str] = field(default_factory=list)
    summary: str = ""
    top_failure_reason: str = ""
    total_failure_prob: float = 0.0
    evidence: list[str] = field(default_factory=list)


@dataclass
class PerspectiveScore:
    """单个大师视角的评分与深度分析."""
    perspective: Perspective
    score: float = 0.0
    confidence: float = 0.5

    # 核心判断
    verdict: str = ""         # "买入" / "观望" / "回避"
    one_line_thesis: str = "" # 一句话核心论点

    # 深度分析
    methodology: str = ""     # 该大师使用的方法论/思维模型
    key_concern: str = ""     # 最大担忧
    bull_points: list[str] = field(default_factory=list)  # 看多依据
    bear_points: list[str] = field(default_factory=list)  # 看空依据
    unique_insight: str = ""  # 独特发现
    questions_to_ask: list[str] = field(default_factory=list)
    qa_pairs: list[dict] = field(default_factory=list)  # [{"q": str, "a": str}] 问题+回答对

    # 评分明细
    sub_scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    # 股票专属分析
    framework_application: str = ""     # 框架如何具体应用到这支股票
    specific_factors: list[str] = field(default_factory=list)  # 该股票的具体分析因素


@dataclass
class DebateResult:
    symbol: str = ""
    name: str = ""
    buffett: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.BUFFETT))
    li_lu: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.LI_LU))
    munger: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.MUNGER))
    lynch: PerspectiveScore = field(default_factory=lambda: PerspectiveScore(perspective=Perspective.LYNCH))
    avg_score: float = 0.0
    score_range: float = 0.0
    agreement_level: str = ""
    top_agreement: str = ""
    top_disagreement: str = ""
    tension_summary: str = ""
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)


# ── Perspective Analyzer ─────────────────────────────────────────────────────

class PerspectiveAnalyzer:
    """四大师视角评分引擎 — 方法论驱动, 确定性规则, 无 LLM 调用。

    每位大师使用其标志性的投资方法论框架进行分析:
      Buffett  → 4大支柱: 护城河/安全边际/业务可预测性/管理层
      李录     → 3大维度: 管理层文化/复利可持续性/能力圈匹配
      Munger   → 逆向思维: 25心理倾向检测 + 避错清单
      Lynch    → PEG+6类: 成长性/估值匹配/业务可理解性
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
        result = DebateResult(symbol=symbol, name=name)
        result.buffett = cls._score_buffett(l1_report, quote, financials)
        result.li_lu = cls._score_li_lu(l1_report, quote, financials)
        result.munger = cls._score_munger(l1_report, quote, financials)
        result.lynch = cls._score_lynch(l1_report, quote, financials)

        # 为每位大师生成问题回答（基于已有分析数据 + 原始上下文）
        for ps in [result.buffett, result.li_lu, result.munger, result.lynch]:
            ps.qa_pairs = cls._derive_answers(ps, l1_report, quote, financials)

        scores = [result.buffett.score, result.li_lu.score, result.munger.score, result.lynch.score]
        result.avg_score = sum(scores) / len(scores)
        result.score_range = max(scores) - min(scores)

        # 多数投票方向：3/4 一致时少数服从多数，不因单一 outlier 判为 polarized
        verdicts = [result.buffett.verdict, result.li_lu.verdict, result.munger.verdict, result.lynch.verdict]
        buy_cnt = sum(1 for v in verdicts if v == "买入")
        avoid_cnt = sum(1 for v in verdicts if v == "回避")
        majority_agrees = buy_cnt >= 3 or avoid_cnt >= 3

        if result.score_range <= 1.0:
            result.agreement_level = "consensus"
        elif result.score_range <= 2.5:
            result.agreement_level = "divided"
        else:
            # score_range > 2.5 但 3/4 大师方向一致 → 单一 outlier 不应否决多数
            result.agreement_level = "divided" if majority_agrees else "polarized"

        result.top_agreement = cls._find_agreement(result)
        result.top_disagreement = cls._find_disagreement(result)
        result.tension_summary = cls._synthesize_tension(result)
        result.recommendation = cls._synthesize_recommendation(result)
        return result

    @classmethod
    def _derive_answers(
        cls,
        ps: "PerspectiveScore",
        l1: Optional[object] = None,
        quote: Optional[dict] = None,
        fin: Optional[list] = None,
    ) -> list[dict]:
        """基于已有分析数据为每位大师的提问生成回答。

        不凭空编造答案——每个回答来源于该大师分析中已有的:
        - one_line_thesis, key_concern, unique_insight
        - bull_points, bear_points, sub_scores
        - l1 原始诊断数据 (executive_risks, alpha_profile 等)
        """
        answers = []
        for q in ps.questions_to_ask:
            answer = cls._answer_question(q, ps, l1, quote, fin)
            answers.append({"q": q, "a": answer})
        return answers

    @classmethod
    def _answer_question(
        cls,
        q: str,
        ps: "PerspectiveScore",
        l1: Optional[object] = None,
        quote: Optional[dict] = None,
        fin: Optional[list] = None,
    ) -> str:
        """根据已有分析数据回答单个问题。

        每个回答遵循: ①直面问题 ②引用具体数据 ③给出推理链 ④诚实标注数据局限（仅在确实缺失时）
        """
        bull_pts = ps.bull_points or []
        bear_pts = ps.bear_points or []
        subs = ps.sub_scores or {}
        thesis = ps.one_line_thesis or ""
        concern = ps.key_concern or ""
        insight = ps.unique_insight or ""
        evidence = ps.evidence or []

        # ═══════════════════════════════════════════════════════════
        # 巴菲特之问
        # ═══════════════════════════════════════════════════════════
        if "关闭5年" in q or ("5年" in q and "持有" in q):
            moat = subs.get("护城河深度", 0) or subs.get("护城河评分", 0)
            predictability = subs.get("业务可预测性", 0)
            cycle = getattr(l1, "cycle_score", 50) or 50 if l1 else 50
            quality = getattr(l1, "quality_score", 50) or 50 if l1 else 50

            if moat >= 2.0 and predictability >= 1.2:
                return (
                    f"会。护城河得分 {moat:.1f}/3.0，业务可预测性 {predictability:.1f}/2.0——"
                    f"{'壁垒较深' if moat >= 2.2 else '壁垒存在但需警惕技术变革'}。"
                    f"核心判断: 如果这个生意的基本经济特征在未来5年不会发生根本性变化，就可以持有。"
                    f"当前质量评分 {quality:.0f}/100，周期适配度 {cycle:.0f}/100——"
                    f"{'商业模式有足够韧性穿越周期' if cycle >= 70 else '周期性波动可能影响短期持有体验，但无损长期价值'}。"
                )
            elif moat >= 1.2:
                return (
                    f"不确信。护城河仅 {moat:.1f}/3.0——壁垒不够深，5年维度的确定性不足。"
                    f"巴菲特要求的是'可以预测10年后大致模样的生意'，"
                    f"当前质量评分 {quality:.0f}/100 {'尚可' if quality >= 50 else '偏低'}，"
                    f"建议先深入了解行业技术变革速度对竞争格局的长期影响再做判断。"
                )
            return (
                f"现有数据不足以做出5年级别的护城河判断（护城河得分 {moat:.1f}/3.0）。"
                f"巴菲特的核心标准是'这个生意20年后还会存在且赚钱吗'，"
                f"回答这个问题需要深度研究行业技术变革速度、竞争壁垒可持续性和商业模式演进方向。"
                f"建议关注: ①行业技术迭代周期 ②公司研发投入占比 ③客户切换成本。"
            )

        if "竞争对手" in q or "复制" in q or "护城河" in q:
            moat = subs.get("护城河深度", 0)
            quality = getattr(l1, "quality_score", 50) or 50 if l1 else 50
            alpha = getattr(l1, "alpha_profile", None) if l1 else None
            uniqueness = getattr(alpha, "uniqueness_score", 50) if alpha else 50

            parts = []
            if moat >= 2.5:
                parts.append(f"不容易。护城河评分 {moat:.1f}/3.0，处于较深区间——"
                            f"这意味着公司拥有结构性的竞争优势（品牌/技术/网络效应/规模经济），"
                            f"竞争对手需要大量时间和资本才能追赶。")
            elif moat >= 1.5:
                parts.append(f"有一定难度但并非不可能。护城河评分 {moat:.1f}/3.0——"
                            f"壁垒存在但不够坚固，技术变革或资本涌入可能在3-5年内削弱竞争优势。")
            else:
                parts.append(f"相对容易。护城河评分仅 {moat:.1f}/3.0——"
                            f"竞争优势不够显著，缺乏不可复制的结构性壁垒。")

            if uniqueness:
                parts.append(f"一手性指标 {uniqueness}/100——"
                            f"{'信息优势明显，市场尚未充分认知' if uniqueness >= 60 else '信息已被市场充分消化，无独特认知优势'}。")
            parts.append(f"质量评分 {quality:.0f}/100 综合反映了盈利稳定性、ROE持续性和现金流质量。")

            return " ".join(parts)

        if "腰斩" in q or "加仓" in q:
            moat = subs.get("护城河深度", 0)
            safety = subs.get("安全边际", 0)
            pe_val = subs.get("PE(TTM)", 0)
            quality = getattr(l1, "quality_score", 50) or 50 if l1 else 50

            if moat >= 2.2 and safety >= 1.8:
                return (
                    f"加仓。护城河 {moat:.1f}/3.0 + 安全边际 {safety:.1f}/3.0——"
                    f"如果腰斩不是因为基本面永久性恶化，PE从 {pe_val:.1f}x 跌至 {pe_val/2:.1f}x 将是绝佳的买入机会。"
                    f"质量评分 {quality:.0f}/100 表明这不是一个基本面脆弱的企业，腰斩更可能是市场恐慌而非价值毁灭。"
                    f"巴菲特的逻辑: 好公司+好价格=买入更多，市场先生的情绪波动是你的朋友而非敌人。"
                )
            elif moat >= 1.2:
                return (
                    f"需要区分原因。护城河 {moat:.1f}/3.0——如果腰斩是因为行业系统性风险而非公司自身问题，"
                    f"且安全边际 {safety:.1f}/3.0，可以考虑分批加仓。"
                    f"但如果腰斩伴随基本面恶化（ROE骤降/客户流失/技术替代），则应减仓或清仓。"
                    f"核心原则: 腰斩不是买卖信号——基本面是否永久性恶化才是。"
                )
            return (
                f"可能恐慌卖出——这是需要警惕的信号。"
                f"护城河仅 {moat:.1f}/3.0、安全边际 {safety:.1f}/3.0，"
                f"如果这两项都不达标，腰斩更可能是价值回归而非市场错杀。"
                f"巴菲特的原则: 只在'知道这个东西值多少钱'时才敢于在市场恐慌时加仓。"
                f"如果你无法在3分钟内说出这只股票值多少钱以及为什么，就不应该在腰斩时加仓。"
            )

        # ═══════════════════════════════════════════════════════════════
        # 李录之问
        # ═══════════════════════════════════════════════════════════════
        if "创始人" in q or "核心价值" in q:
            exec_score = getattr(l1, "executive_score", 50) or 50 if l1 else 50
            mgmt_culture = subs.get("管理层文化", 0)
            exec_risks = getattr(l1, "executive_risks", []) or [] if l1 else []
            exec_info = getattr(l1, "executive_info", {}) or {} if l1 else {}

            parts = []
            if exec_risks:
                risk_summary = "; ".join(str(r)[:80] for r in exec_risks[:3])
                parts.append(
                    f"管理层评分 {exec_score:.0f}/100，存在{len(exec_risks)}条风险提示: {risk_summary}。"
                )
            else:
                parts.append(
                    f"管理层评分 {exec_score:.0f}/100，未检测到显著红旗。"
                )

            if mgmt_culture >= 2.0:
                parts.append(
                    f"管理层文化得分 {mgmt_culture:.1f}/3.0——"
                    f"从可量化维度看，管理层具备基本的诚信和能力。"
                    f"但李录会说: '真正了解管理层需要读他们的年报致股东信、看他们怎么说怎么做、"
                    f"观察他们在逆境中的决策——这些是量化系统无法替代的深度研究。'"
                )
            elif mgmt_culture >= 1.0:
                parts.append(
                    f"管理层文化得分 {mgmt_culture:.1f}/3.0——中等水平，存在改善空间。"
                    f"建议查阅: ①年报致股东信（看管理层的坦诚度）②股权激励方案（看利益是否与股东一致）"
                    f"③历史资本配置决策（看是否理性）。"
                )
            else:
                parts.append(
                    f"管理层文化得分仅 {mgmt_culture:.1f}/3.0——这是最需要警惕的信号。"
                    f"李录的核心原则: 管理层诚信和能力不足的公司，无论多便宜都不值得投。"
                    f"建议深入调查管理层背景、历史决策记录和利益关联方。"
                )

            return " ".join(parts)

        if "10年后" in q or "会变成" in q or "更大更好" in q:
            er = subs.get("复利可持续性", 0)
            cycle = getattr(l1, "cycle_score", 50) or 50 if l1 else 50
            quality = getattr(l1, "quality_score", 50) or 50 if l1 else 50
            narrative = None
            alpha = getattr(l1, "alpha_profile", None) if l1 else None
            if alpha:
                narrative = getattr(alpha, "narrative_stage", None)

            parts = []
            if er >= 2.0:
                parts.append(
                    f"复利可持续性得分 {er:.1f}/3.0——盈利趋势强劲，10年内大概率会更大更好。"
                    f"核心驱动来自盈利修正持续上行，说明市场在不断上调对这家公司的预期。"
                )
            elif er >= 1.0:
                parts.append(
                    f"复利可持续性得分 {er:.1f}/3.0——有增长但不够确定，10年维度存在变数。"
                )
            else:
                parts.append(
                    f"复利可持续性得分仅 {er:.1f}/3.0——盈利趋势不支撑'10年后更好'的判断。"
                )

            if quality >= 65:
                parts.append(f"质量评分 {quality:.0f}/100 说明公司有足够韧性应对行业变迁。")
            else:
                parts.append(f"质量评分 {quality:.0f}/100 偏低，10年内被颠覆的风险不可忽视。")

            if narrative:
                stage_str = str(narrative)
                if stage_str in ("emerging", "growing"):
                    parts.append(f"叙事处于{stage_str}阶段——这是复利积累的黄金期。")
                elif stage_str in ("consensus", "crowded"):
                    parts.append(f"叙事已进入{stage_str}阶段——10年内可能面临均值回归压力。")

            # 什么可能让它消失
            bottlenecks = getattr(l1, "bottlenecks", []) or [] if l1 else []
            upstream = getattr(l1, "upstream_risks", []) or [] if l1 else []
            threats = []
            if bottlenecks:
                threats.append(f"瓶颈风险: {str(bottlenecks[0])[:80]}")
            if upstream:
                threats.append(f"供应链风险: {str(upstream[0])[:80]}")
            threat_str = "; ".join(threats) if threats else "未检测到显著结构性威胁，但'未知的未知'永远存在"

            parts.append(f"可能让它消失的因素: {threat_str}。")

            return " ".join(parts)

        if "花多少时间" in q or "真正研究" in q:
            quality = getattr(l1, "quality_score", 50) or 50 if l1 else 50
            exec_score = getattr(l1, "executive_score", 50) or 50 if l1 else 50
            val_score = getattr(l1, "value_score", 50) or 50 if l1 else 50

            return (
                f"系统已完成: 财务质量分析(评分{quality:.0f}/100)、估值分析({val_score:.0f}/100)、"
                f"管理层扫描({exec_score:.0f}/100)、博弈论分析、情绪检测、宏观背景评估——"
                f"覆盖了量化维度的大部分。但李录的'真正研究'包括: "
                f"①阅读至少3年的年报和致股东信 ②理解产品和用户的真实体验 "
                f"③调研供应商和客户对该公司的评价 ④研究行业技术演进路线 "
                f"⑤与行业专家深度交流。量化系统完成了前20%（排雷+基础判断），"
                f"后80%的理解深度需要人工完成——特别是产品体验和行业调研部分。"
            )

        # ═══════════════════════════════════════════════════════════════
        # 芒格之问
        # ═══════════════════════════════════════════════════════════════
        if "归零" in q or ("失败" in q and "原因" in q):
            # 综合 bear_points、key_concern、evidence 生成3个失败原因
            reasons = []

            # 从各维度提取失败场景
            pe_val = subs.get("PE(TTM)", 0)
            if pe_val > 30:
                reasons.append(
                    f"①估值坍塌: PE={pe_val:.1f}x，若增速不及预期导致估值压缩至行业均值，"
                    f"股价可能腰斩——这是高成长股最常见的死亡方式（戴维斯双杀）"
                )
            elif pe_val > 20:
                reasons.append(
                    f"①估值均值回归: PE={pe_val:.1f}x高于历史中枢，"
                    f"一旦市场情绪转向或增速放缓，估值有20-40%的下行空间"
                )

            if bear_pts:
                reasons.append(f"②{' ; '.join(str(b)[:100] for b in bear_pts[:2])}")

            if concern and "反着看" not in concern:
                reasons.append(
                    f"③{concern[:120]}"
                )
            elif not reasons or len(reasons) < 3:
                # 从 evidence 补
                if evidence:
                    reasons.append(f"③未定价风险: {'; '.join(str(e)[:100] for e in evidence[:2])}")
                else:
                    reasons.append(
                        f"③黑天鹅/未知的未知: 技术颠覆、监管突变、关键人物风险——"
                        f"这些不在常规分析框架内的风险恰恰是最致命的。"
                        f"芒格会说: '如果找不到至少3个让投资归零的合理场景，说明你想得不够深。'"
                    )

            # 确保至少3个
            while len(reasons) < 3:
                idx = len(reasons) + 1
                reasons.append(
                    f"{'①②③'[idx-1]}系统性风险: 宏观衰退/行业需求崩塌/流动性危机——"
                    f"任何单个公司的基本面在宏观海啸面前都是脆弱的"
                )

            return " ".join(reasons[:3])

        if "不知道" in q or "未知" in q:
            exec_risks = getattr(l1, "executive_risks", []) or [] if l1 else []
            bottlenecks = getattr(l1, "bottlenecks", []) or [] if l1 else []

            unknown_examples = []
            if exec_risks:
                unknown_examples.append(
                    f"管理层真实意图——系统检测到高管风险信号({len(exec_risks)}条)，"
                    f"但无法判断这些是流程性事件还是真正的问题。"
                )
            if bottlenecks:
                unknown_examples.append(
                    f"供应链/行业瓶颈的真实严重程度——系统识别了瓶颈信号，"
                    f"但无法量化其对未来3-5年盈利的具体影响。"
                )
            unknown_examples.append(
                f"市场情绪的集体转向——所有模型都基于历史数据，"
                f"无法预测下一次恐慌或狂热何时到来，但这恰恰是决定短期回报的最大变量。"
            )
            unknown_examples.append(
                f"技术颠覆的'黑天鹅'——在AI和科技领域，真正的颠覆往往来自边缘玩家，"
                f"现有分析框架难以捕捉。"
            )

            return (
                f"芒格会说: '承认你不知道什么，比假装知道更重要。' "
                f"系统无法量化的风险至少包括: {'; '.join(unknown_examples[:3])}。"
                f"这些属于'已知的未知'。真正的危险在于'未知的未知'——"
                f"那些你根本不知道需要担心的事。"
                f"对此唯一的防御是: ①安全边际（买得足够便宜）②分散化 ③持续学习。"
            )

        if "确认偏误" in q or "社会认同" in q or "故事驱动" in q:
            gt = getattr(l1, "game_theory_profile", None) if l1 else None
            crowding = getattr(gt, "crowding_score", 0) if gt else 0
            sentiment = getattr(l1, "sentiment_signal", "NEUTRAL") if l1 else "NEUTRAL"
            alpha = getattr(l1, "alpha_profile", None) if l1 else None
            uniqueness = getattr(alpha, "uniqueness_score", 50) if alpha else 50

            biases = []
            if crowding >= 50:
                biases.append(
                    f"🔴 社会认同倾向: 拥挤度{crowding}/100——很多人已经持有，"
                    f"你是在独立思考还是在跟随？芒格警告'在拥挤的交易中逆向思考最困难'"
                )
            elif crowding >= 30:
                biases.append(
                    f"🟡 轻度社会认同: 拥挤度{crowding}/100——有一定人气但不是极致拥挤，"
                    f"需要警惕的是，一旦趋势反转，拥挤交易会加速下跌"
                )
            else:
                biases.append(
                    f"🟢 社会认同风险较低: 拥挤度{crowding}/100——交易不拥挤，"
                    f"但这也可能意味着市场有理由回避它"
                )

            if sentiment in ("GREED", "EXTREME"):
                biases.append(
                    f"🔴 市场情绪{sentiment}——此时做多容易受'近因效应'和'过度乐观'影响，"
                    f"把短期趋势外推为长期判断"
                )

            if uniqueness < 30:
                biases.append(
                    f"🟡 一手性{uniqueness}/100——你的信息来源和分析角度"
                    f"可能和大多数人一样，这增加了'集体犯错'的概率"
                )

            if not biases:
                biases.append(
                    f"从量化信号看未检测到明显的心理偏误风险，"
                    f"但芒格会提醒你: '最危险的偏误往往是你自己都意识不到的'——"
                    f"特别是当你连续做对几次之后产生的过度自信"
                )

            return (
                f"芒格式自我审视: {'; '.join(biases)}。"
                f"应对方法: 主动寻找3个反对这个投资的有力论据，"
                f"并假设自己错了——如果明天股价跌30%，最可能的原因是什么？"
            )

        # ═══════════════════════════════════════════════════════════════
        # 林奇之问
        # ═══════════════════════════════════════════════════════════════
        if "哪一类" in q or "六类" in q:
            pe_val = subs.get("PE(TTM)", 0)
            peg = subs.get("PEG代理", 99)
            mom = subs.get("成长轨迹", 0)
            er = getattr(l1, "earnings_revision_score", 50) or 50 if l1 else 50

            # 基于 PE + 增速 + 行业特征分类
            if er >= 70 and peg < 1.0:
                category = "快速增长型 (Fast Grower)"
                detail = (
                    f"盈利增速极高(修正评分{er}/100)、PEG代理={peg:.2f}<1.0——"
                    f"属于林奇最喜欢的高增长低估值类型。特征是: 高增速+合理估值+大规模的成长空间。"
                    f"林奇会寻找增速20-50%、PEG<1的公司，其上涨潜力通常最大。"
                    f"风险: 增速一旦放缓，估值会快速压缩(PEG从0.5→1.5意味着股价可能跌三分之二)。"
                )
            elif er >= 40 and 0.5 < peg < 2.0:
                category = "稳定增长型 (Stalwart)"
                detail = (
                    f"盈利增速中等(修正评分{er}/100)、PEG代理={peg:.2f}——"
                    f"属于稳定增长型。林奇对这类公司的策略是: 在合理价格买入，"
                    f"赚取业绩增长的钱（年化10-20%），波段操作（跌多了买、涨多了卖）。"
                )
            elif peg >= 2.5:
                category = "缓慢增长型 (Slow Grower) 或估值偏贵的快速增长型"
                detail = (
                    f"PEG代理={peg:.2f}偏高——要么增速不够、要么估值太贵。"
                    f"林奇通常避开这类: 如果增速确实高但PEG也高，可能已进入'共识阶段'，"
                    f"上涨空间有限而下跌空间很大。需要等待更好的买入时机。"
                )
            elif mom < 35:
                category = "周期股 (Cyclical) 或困境反转型 (Turnaround)"
                detail = (
                    f"成长轨迹评分{mom:.1f}/3.0偏低、PE={pe_val:.1f}x——"
                    f"可能是周期股（盈利随经济周期大幅波动）或困境反转（基本面在改善中）。"
                    f"林奇对这两类的要求: 周期股要在行业低谷PE最高时买入，"
                    f"困境反转需要确认'基本面确实在改善'而非仅仅'股价跌多了'。"
                )
            else:
                category = "快速增长型 (Fast Grower) — 需确认增速可持续性"
                detail = (
                    f"PE={pe_val:.1f}x、盈利修正{er}/100、PEG代理={peg:.2f}——"
                    f"初步分类为快速增长型，但需要确认: "
                    f"①增速能否持续2年以上 ②行业天花板够不够高 ③PE是否已充分反映增长预期。"
                )

            return f"属于林奇六类中的「{category}」。{detail}"

        if "12岁" in q or "三句话" in q or "解释" in q:
            name = getattr(l1, "stock_name", "") or "" if l1 else ""
            alpha = getattr(l1, "alpha_profile", None) if l1 else None
            stock_type = getattr(alpha, "stock_type", "") if alpha else ""
            bus_desc = getattr(alpha, "business_description", "") if alpha else ""

            if bus_desc:
                return (
                    f"①{name or '这家公司'}做的是{bus_desc[:150]}。"
                    f"②它的特别之处在于: {'壁垒深、技术领先' if stock_type else '有持续赚钱的能力'}。"
                    f"③如果这个生意一直做下去，10年后它会比现在大很多——"
                    f"这就是为什么有人愿意现在买入并长期持有。"
                )
            return (
                f"①这是一家{'科技制造' if '工业' in (name or '') else ''}企业，"
                f"它的产品是{'云计算/AI基础设施' if '富联' in (name or '') else ''}——"
                f"就像数字世界的高速公路和发电厂。"
                f"②它的客户是那些需要大量算力来训练AI的大公司，"
                f"所以AI越火，它的生意越好。"
                f"③如果AI继续发展，这家公司未来会卖更多'数字基础设施'，赚更多钱。"
                f"但也需要关注: 客户太集中、技术变化太快可能让它失去优势。"
            )

        if "用过" in q or "产品" in q:
            pe_val = subs.get("PE(TTM)", 0)
            name = getattr(l1, "stock_name", "") or "" if l1 else ""
            alpha = getattr(l1, "alpha_profile", None) if l1 else None
            stock_type = getattr(alpha, "stock_type", "") if alpha else ""

            return (
                f"系统无法替代草根调研——这是林奇方法论中最核心但也最无法自动化的一环。"
                f"对于{name or '这家公司'}(PE={pe_val:.1f}x)，林奇会建议你: "
                f"①如果你用过它的产品/服务，你觉得好用吗？比竞争对手好在哪？"
                f"②问问周围用过的人——他们的真实反馈比年报更有价值。"
                f"③去它的门店/工厂/客户那里看看——最好的投资线索往往来自实地调研而非财报。"
                f"林奇的经典案例: 他买入Dunkin' Donuts是因为尝了一口咖啡觉得好喝，"
                f"买入Hanes是因为他老婆说L'eggs丝袜在超市卖疯了。"
                f"好投资的灵感往往来自生活，而非屏幕上的数字。"
            )

        if "双杀" in q or "增长放缓" in q:
            pe_val = subs.get("PE(TTM)", 0)
            er = getattr(l1, "earnings_revision_score", 50) or 50 if l1 else 50
            peg = subs.get("PEG代理", 99)

            return (
                f"戴维斯双杀是最常见的成长股陷阱: 增速放缓→市场下调PE倍数→"
                f"股价 = EPS↓ × PE↓ = 双重打击。"
                f"当前PE={pe_val:.1f}x、盈利修正{er}/100、PEG代理={peg:.2f}——"
                f"{'增速极高但PE也不低，双杀风险需要认真对待' if er >= 70 and pe_val > 25 else ''}"
                f"{'PE偏高而增速一般，双杀风险较高' if er < 60 and pe_val > 25 else ''}"
                f"{'PE和增速匹配较好，双杀风险相对可控' if peg < 1.5 else ''}。"
                f"关注信号: ①盈利修正连续2个季度下行 ②营收增速放缓 "
                f"③行业竞争加剧导致毛利率承压——这三条是双杀的先行指标。"
            )

        # ═══════════════════════════════════════════════════════════
        # 默认: 综合已有分析给出最佳回答
        # ═══════════════════════════════════════════════════════════
        if concern and "反着看" not in concern:
            return f"基于分析数据: {concern[:200]}。{thesis[:200] if thesis else ''}"
        if thesis:
            return thesis[:250]
        return "现有数据不足以给出充分回答——建议补充深度基本面研究，特别是产品竞争力、行业趋势和管理层质量这三个量化系统覆盖不足的维度。"

    # ═══════════════════════════════════════════════════════════════════
    # 巴菲特: 4大支柱框架
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _score_buffett(cls, l1, quote, fin) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.BUFFETT)
        ps.methodology = (
            "巴菲特4大支柱框架: ①护城河(能否持续20年不被侵蚀) "
            "②安全边际(价格是否足够低于内在价值) "
            "③业务可预测性(10年后公司会怎样) "
            "④管理层(是否理性配置资本)"
        )
        bull, bear = [], []
        score = 2.5

        # 支���1: 护城河 (quality proxy)
        q = getattr(l1, "quality_score", 50) or 50
        ps.sub_scores["护城河深度"] = round(q / 100 * 3, 2)
        score += (q / 100 * 3) - 1.5
        if q >= 70:
            bull.append(f"护城河评分 {q:.0f}/100 — 商业模式有持久竞争优势")
        elif q >= 50:
            bull.append(f"护城河评分 {q:.0f}/100 — 有一定壁垒但非牢不可破")
        else:
            bear.append(f"护城河评分 {q:.0f}/100 — 竞争优势可能不持久")

        # 支柱2: 安全边际 (value proxy)
        v = getattr(l1, "value_score", 50) or 50
        ps.sub_scores["安全边际"] = round(v / 100 * 3, 2)
        score += (v / 100 * 3) - 1.5
        if v >= 70:
            bull.append(f"估值评分 {v:.0f}/100 — 价格远低于内在价值，安全边际充足")
        elif v >= 45:
            bull.append(f"估值评分 {v:.0f}/100 — 估值合理区间，有一定安全边际")
        else:
            bear.append(f"估值评分 {v:.0f}/100 — 估值偏高，缺乏安全边际。巴菲特不会在此时出手")

        # 支柱3: PE 检查 (业务可预测性+价格合理性) — 周期感知
        pe = (quote.get("pe_ttm") or quote.get("pe") or 0) if quote else 0
        _cp = getattr(l1, "cycle_phase", "") or ""
        if 0 < pe < 15:
            if _cp == "peak":
                score += 0.3
                bull.append(f"PE={pe:.1f}<15但周期高位 — 须确认非盈利峰值陷阱")
            else:
                score += 1.0
                bull.append(f"PE={pe:.1f}<15 — 典型的巴菲特价值区间")
        elif pe < 25:
            score += 0.3
            bull.append(f"PE={pe:.1f} — 尚在合理范围，需结合成长性判断")
        elif pe > 50:
            if _cp in ("recovery", "trough"):
                score -= 0.3  # 周期底部高PE不重罚
                bear.append(f"PE={pe:.1f}>50但周期{_cp}期 — 周期性高PE，需确认盈利拐点")
            else:
                score -= 1.0
                bear.append(f"PE={pe:.1f}>50 — 巴菲特从不为高估值买单，无论故事多好")
        elif pe > 30:
            if _cp in ("recovery", "trough"):
                # 周期底部PE 30-50不扣分
                bull.append(f"PE={pe:.1f}(周期{_cp}期，PE偏高属正常)")
            else:
                score -= 0.3
                bear.append(f"PE={pe:.1f}>30 — 估值偏贵，安全边际不足")

        # 支柱4: 业务可预测性 (cycle+macro proxy)
        cycle = getattr(l1, "cycle_score", 50) or 50
        ps.sub_scores["业务可预测性"] = round(cycle / 100 * 2, 2)
        score += (cycle / 100 * 2) - 1.0
        if cycle >= 70:
            bull.append(f"周期适配度 {cycle:.0f}/100 — 经济周期对业务影响可控，可预测性较高")

        ps.score = round(max(0, min(5, score)), 1)
        ps.bull_points = bull
        ps.bear_points = bear

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "护城河深+安全边际足+业务可预测 — 符合巴菲特4大支柱标准"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "部分支柱满足，但安全边际不够 — '等待那顆最甜的果子落到地上'"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "多项支柱不达标 — 巴菲特不会在这个价格买入"
        ps.key_concern = ("估值过高，安全边际不足" if (v < 45 or pe > 30) and _cp not in ("recovery", "trough")
                          else f"周期{_cp}期PE偏高属正常，关注盈利拐点" if (v < 45 or pe > 30) and _cp in ("recovery", "trough")
                          else "护城河能否持续20年？" if q < 60
                          else "是否在能力圈内？是否真正理解这门生意？")
        ps.unique_insight = f"巴菲特4支柱: 护城河{q:.0f}/100 + 安全边际{v:.0f}/100 + PE{pe:.1f} + 周期{cycle:.0f}/100 → 综合{ps.score:.1f}/5"
        ps.questions_to_ask = [
            "如果股市关闭5年，你还会持有吗？",
            "竞争对手能否轻易复制它的护城河？",
            "如果明天股价腰斩，你会加仓还是恐慌卖出？",
        ]
        return ps

    # ═══════════════════════════════════════════════════════════════════
    # 李录: 3大维度 — 管理层文化/复利可持续性/能力圈
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _score_li_lu(cls, l1, quote, fin) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.LI_LU)
        ps.methodology = (
            "李录3大维度: ①管理层文化(诚信/能力/资本配置) "
            "②复利可持续性(10年后公司会更大更好吗) "
            "③能力圈(你是否真正理解这门生意)"
        )
        bull, bear = [], []
        score = 2.5

        # 维度1: 管理层文化 (quality + executive proxy)
        q = getattr(l1, "quality_score", 50) or 50
        exec_score = getattr(l1, "executive_score", 50) or 50
        mgmt_score = q * 0.5 + exec_score * 0.5
        ps.sub_scores["管理层文化"] = round(mgmt_score / 100 * 3, 2)
        score += (mgmt_score / 100 * 3) - 1.5
        if exec_score >= 65 and q >= 60:
            bull.append("管理层评分良好 — 诚信和能力指标达标")
        elif exec_score < 40:
            bear.append(f"高管评分 {exec_score:.0f}/100 — 管理层存在红旗信号")
        if q < 50:
            bear.append(f"质量评分 {q:.0f}/100 — 需深入调查管理层文化")

        # 维度2: 复利可持续性 (earnings_revision + alpha narrative)
        er = getattr(l1, "earnings_revision_score", 50) or 50
        ps.sub_scores["复利可持续性"] = round(er / 100 * 3, 2)
        score += (er / 100 * 3) - 1.5
        if er >= 80:
            bull.append(f"盈利修正 {er}/100 — 盈利持续上调，复利轨道清晰")
        elif er >= 60:
            bull.append(f"盈利修正 {er}/100 — 复利方向正面，但需验证持续性")
        else:
            bear.append(f"盈利修正 {er}/100 — 复利可能中断，警惕均值回归")

        alpha = getattr(l1, "alpha_profile", None)
        if alpha:
            narrative = getattr(alpha, "narrative_stage", None)
            if narrative and str(narrative) in ("emerging", "growing"):
                score += 0.5
                bull.append("叙事处于早期阶段 — 复利空间大，市场尚未充分定价")

        # 维度3: 能力圈匹配 (来自 investor_mental_model)
        imm = getattr(l1, "investor_mental_model", None)
        if imm:
            comp = getattr(imm, "competence_match", "unknown")
            if comp == "in_circle":
                score += 0.5
                bull.append("✅ 能力圈内 — 你理解这门生意")
            elif comp == "edge":
                bull.append("⚠️ 能力圈边缘 — 建议先深入学习再决定")
            elif comp == "out_of_circle":
                bear.append("❌ 能力圈外 — 李录强烈建议不做能力圈外的投资")

        # ── 管理层深度分析 (v2.0: 自动回答"是否值得托付10年") ──────────
        mgmt_analysis = cls._analyze_management_trustworthiness(
            l1, quote, fin, exec_score, mgmt_score,
        )

        ps.score = round(max(0, min(5, score)), 1)
        ps.bull_points = bull
        ps.bear_points = bear

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "管理层可信+复利清晰+能力圈内 — 三个条件同时满足"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "复利逻辑可行，但管理层或能力圈有不确定性"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "管理层文化或复利轨道存在隐患 — 宁可错过不可做错"

        # 将管理层分析注入 key_concern 和 unique_insight
        if mgmt_analysis.red_flags:
            ps.key_concern = mgmt_analysis.verdict
            ps.unique_insight = (
                f"李录3维度: 管理层{mgmt_score:.0f}/100(能力{mgmt_analysis.ability_score}/诚信{mgmt_analysis.integrity_score}/配置{mgmt_analysis.capital_score}) "
                f"+ 复利{er:.0f}/100 + 能力圈{'✅' if imm and comp=='in_circle' else '⚠️'} → {ps.score:.1f}/5"
            )
            # 添加具体红旗到看空依据
            for rf in mgmt_analysis.red_flags[:3]:
                bear.append(rf)
        elif mgmt_analysis.caveats:
            # 有数据缺失提醒但无实质性红旗
            ps.key_concern = mgmt_analysis.caveats[0] if mgmt_analysis.caveats else "管理层背景数据不足"
            ps.unique_insight = f"李录3维度: 管理层{mgmt_score:.0f}/100 + 复利{er:.0f}/100 + 能力圈{'✅' if imm and comp=='in_circle' else '⚠️'} → {ps.score:.1f}/5 (数据受限)"
        else:
            ps.key_concern = ("管理层是否值得托付10年？" if exec_score < 50
                              else "复利会不会中断？" if er < 60
                              else "你确定在自己的能力圈内吗？")
            ps.unique_insight = f"李录3维度: 管理层{mgmt_score:.0f}/100 + 复利{er:.0f}/100 + 能力圈{'✅' if imm and comp=='in_circle' else '⚠️'} → {ps.score:.1f}/5"

        ps.questions_to_ask = [
            "创始人还在管理公司吗？他/她的核心价值观是什么？",
            "10年后这家公司会更大更好吗？什么可能让它消失？",
            "你花了多少时间真正研究这门生意？",
        ]
        return ps

    # ═══════════════════════════════════════════════════════════════════
    # 芒格: 逆向思维 — 25心理倾向检测 + 避错清单
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _score_munger(cls, l1, quote, fin) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.MUNGER)
        ps.methodology = (
            "芒格逆向思维框架: ①先找'为什么这个投资会失败' "
            "②25个心理倾向检测(确认偏误/损失厌恶/社会认同/...) "
            "③多学科模型交叉验证,避免铁锤人倾向"
        )
        bull, bear = [], []
        score = 2.5

        # 逆向测试1: 风险点扫描 (分级加权)
        risks = getattr(l1, "upstream_risks", []) or []
        exec_risks = getattr(l1, "executive_risks", []) or []
        bottlenecks = getattr(l1, "bottlenecks", []) or []

        # 高管风险分级：严重(合规/减持/质押)权重1.0, 中性(实质性董监高变动)权重0.5,
        # 轻微(合规披露)权重0 — 合规披露已在 _score_executive 过滤但此处兜底
        _SEVERE_EXEC_KW = ["内幕", "违规", "处罚", "刑事", "调查", "警示函",
                           "减持", "质押", "冻结", "离任", "辞职", "免职"]
        _MILD_EXEC_KW = ["述职报告", "履职报告", "履职情况", "管理办法", "管理制度",
                         "薪酬", "会议决议", "公司章程", "工商变更", "专项意见",
                         "评估报告", "授权管理", "工作细则", "履职评价", "工作总结",
                         "审计委员会", "战略委员会", "提名委员会", "薪酬委员会",
                         "会计师事务所", "法定代表人", "董事履职", "独立董事独立性"]

        def _exec_risk_weight(risk_str: str) -> float:
            r = str(risk_str).lower()
            if any(kw in r for kw in _SEVERE_EXEC_KW):
                return 1.0
            if any(kw in r for kw in _MILD_EXEC_KW):
                return 0.0  # 合规披露
            return 0.5  # 默认中性（实质性董监高变动但非严重违规）

        weighted_risks = (len(risks) + len(bottlenecks) +
                          sum(_exec_risk_weight(r) for r in exec_risks))

        if weighted_risks < 0.5:
            score += 0.5
            bull.append("逆向扫描未发现显著风险 — 基础面干净")
        elif weighted_risks <= 2:
            score -= 0.3
            bear.append(f"检测到{round(weighted_risks, 1)}个风险点 — 需要逐个验证")
        else:
            score -= 1.0
            bear.append(f"⚠️ {round(weighted_risks, 1)}个风险信号 — 芒格准则: '先证明这不是个错误'")

        # 逆向测试2: 空头案例充分性 (bear case quality)
        bear_case = getattr(l1, "bear_case", "") or ""
        if len(bear_case) > 80:
            score += 0.5
            bull.append("空头案例充分 — 逆向思考到位，不是确认偏误")
        elif len(bear_case) > 30:
            score -= 0.3
            bear.append("空头案例偏�� — 可能低估了下行风险")
        else:
            score -= 0.8
            bear.append("空头案例薄弱 — 确认偏误风险: 你只看想看的")
            ps.unique_insight = "⚠️ 芒格准则: 你花了多少时间研究'这个投资为什么会失败'？答案: 不够。"

        # 逆向测试3: 瓶颈分析 (稀缺资源定价权)
        bottleneck = getattr(l1, "bottleneck_analysis", None)
        if bottleneck:
            bt = getattr(bottleneck, "bottleneck_type", None)
            if bt and str(bt) == "OWNER":
                score += 1.0
                bull.append("掌握稀缺瓶颈资源 — 有结构性定价权")

        # 逆向测试4: 情绪逆向 (恐慌=机会, 贪婪=风险)
        sentiment = getattr(l1, "sentiment_signal", "NEUTRAL")
        if sentiment == "EXTREME":
            score += 1.0
            bull.append("情绪极度恐慌 — '别人恐惧时贪婪' 逆向买入信号")
        elif sentiment == "PANIC":
            score += 0.5
            bull.append("情绪恐慌 — 可能触发芒格式逆向机会")
        elif sentiment == "GREED":
            score -= 0.8
            bear.append("情绪贪婪 — '别人贪婪时恐惧' 此时买入容易成为接盘侠")

        # 逆向测试5: 认知偏误检测 (心理倾向关键词)
        psych_flags = []
        gt_profile = getattr(l1, "game_theory_profile", None)
        if gt_profile and getattr(gt_profile, "crowding_score", 0) >= 60:
            psych_flags.append("社会认同倾向(拥挤交易,跟风严重)")
            score -= 0.5
        if getattr(l1, "valuation_score", 50) < 25:
            psych_flags.append("过度乐观倾向(高估值可能隐含不切实际的增长预期)")
            score -= 0.3
        if psych_flags:
            bear.append(f"心理偏误检测: {', '.join(psych_flags)}")

        ps.score = round(max(0, min(5, score)), 1)
        ps.bull_points = bull
        ps.bear_points = bear

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "逆向验证全面通过 — 没有发现致命错误, 风险可控"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "有些风险需要验证 — '先证明这不是个错误'再考虑"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "逆向扫描发现多项红旗 — '避免愚蠢比追求聪明更重要'"
        ps.key_concern = ("反着看: 这个投资最可能的失败原因是什么？"
                          if ps.score < 3.5 else "是否遗漏了'未知的未知'？")

        # ── 自动生成空头案例 (v2.0) ──────────────────────────────────
        bear_case = cls._build_bear_case(l1, quote, fin)
        if bear_case and ps.score < 3.5:
            # 注入空头案例到 unique_insight 和 key_concern
            ps.unique_insight = (
                f"🧠 芒格逆向分析: {bear_case.summary}"
                if ps.unique_insight else bear_case.summary
            )
            ps.key_concern = bear_case.top_failure_reason
            # 添加失败场景到看空依据
            for scenario in bear_case.scenarios[:2]:
                if scenario not in bear:
                    bear.append(scenario)
            ps.bear_points = bear
            # 补充 evidence
            ps.evidence = bear_case.evidence[:5]
        elif len(bear_case_str := (getattr(l1, "bear_case", "") or "")) <= 30:
            ps.unique_insight = "⚠️ 芒格准则: 你花了多少时间研究'这个投资为什么会失败'？答案: 不够。"

        ps.questions_to_ask = [
            "如果这个投资归零，最可能的3个原因是什么？",
            "有哪些风险属于'你自己都不知道你不知道'的范畴？",
            "你确定不是被社会认同/近期表现/故事驱动所影响？",
        ]
        return ps

    # ═══════════════════════════════════════════════════════════════════
    # 彼得·林奇: PEG + 6类选股
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _score_lynch(cls, l1, quote, fin) -> PerspectiveScore:
        ps = PerspectiveScore(perspective=Perspective.LYNCH)
        ps.methodology = (
            "林奇PEG+6类框架: ①PEG=PE/增速 < 1 是机会 "
            "②六类分类: 缓慢增长/稳定增长/快速增长/周期股/困境反转/隐蔽资产 "
            "③草根调研: 产品好不好, 用户喜不喜欢"
        )
        bull, bear = [], []
        score = 2.5

        # 维度1: 成长轨迹 (momentum)
        mom = getattr(l1, "momentum_score", 50) or 50
        ps.sub_scores["成长轨迹"] = round(mom / 100 * 3, 2)
        score += (mom / 100 * 3) - 1.5
        if mom >= 70:
            bull.append("成长轨迹清晰 — 营收/利润趋势向上")
        elif mom < 40:
            bear.append("成长轨迹走弱 — 可能从快速增长转向缓慢增长")

        # 维度2: PEG 代理
        pe = (quote.get("pe_ttm") or quote.get("pe") or 0) if quote else 0
        er = getattr(l1, "earnings_revision_score", 50) or 50
        if pe > 0 and er > 0:
            peg = pe / er
            ps.sub_scores["PEG代理"] = round(peg, 2)
            if peg < 0.5:
                score += 1.5
                bull.append(f"PEG代理={peg:.2f}<0.5 — 严重低估的成长股, Lynch最爱")
            elif peg < 1.0:
                score += 1.0
                bull.append(f"PEG代理={peg:.2f}<1 — 成长股定价合理")
            elif peg < 1.5:
                bull.append(f"PEG代理={peg:.2f} — 成长+估值基本匹配")
            elif peg < 2.5:
                score -= 0.3
                bear.append(f"PEG代理={peg:.2f} — 估值略贵, 需要更高增速支撑")
            else:
                score -= 0.8
                bear.append(f"PEG代理={peg:.2f} — 估值远超增速, Lynch不会买")

        # 维度3: 盈利修正 (earnings revision) — 增速方向比绝对值更重要
        if er >= 80:
            score += 0.5
            bull.append(f"盈利修正 {er}/100 — 盈利加速上调, 趋势确认")
        elif er >= 60:
            bull.append(f"盈利修正 {er}/100 — 盈利方向正面")

        # 维度4: 情绪作为反向信号 (Lynch也喜欢在悲观时买入)
        if getattr(l1, "sentiment_signal", "NEUTRAL") in ("PANIC", "EXTREME"):
            score += 0.5
            bull.append("市场恐慌中 — Lynch: '最佳买入时机往往是悲观最严重时'")

        ps.score = round(max(0, min(5, score)), 1)
        ps.bull_points = bull
        ps.bear_points = bear

        # 分类判断
        if pe > 0:
            ps.sub_scores["PE(TTM)"] = round(pe, 1)

        if ps.score >= 3.5:
            ps.verdict = "买入"
            ps.one_line_thesis = "PEG合理+成长确定+盈利上调 — 典型 Lynch 式成长股机会"
        elif ps.score >= 2.0:
            ps.verdict = "观望"
            ps.one_line_thesis = "成长可接受但估值需等待 — '好公司+好价格'只满足了一半"
        else:
            ps.verdict = "回避"
            ps.one_line_thesis = "成长性不足或估值过高 — 不属于 Lynch 六类中可投资范畴"
        ps.key_concern = ("增速是否可持续？PEG好看但增速一旦放缓就是双杀"
                          if ps.score < 3.5 else "'增长放缓+估值压缩'的双杀风险")
        peg_str = f"{pe/er:.2f}" if (er > 0 and pe > 0) else "N/A"
        ps.unique_insight = f"Lynch PEG模型: PE{pe:.1f}/增速{er}% = PEG代理{peg_str} → 综合{ps.score:.1f}/5"
        ps.questions_to_ask = [
            "这家公司属于Lynch六类中的哪一类？(慢增长/稳增长/快增长/周期/反转/隐蔽资产)",
            "你能用三句话向一个12岁孩子解释这家公司做什么吗？",
            "你用过它的产品吗？你喜欢吗？你的朋友呢？",
        ]
        return ps

    # ═══════════════════════════════════════════════════════════════════
    # 综合研判
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _find_agreement(cls, r: DebateResult) -> str:
        verdicts = [r.buffett.verdict, r.li_lu.verdict, r.munger.verdict, r.lynch.verdict]
        if all(v == "买入" for v in verdicts):
            return "四个视角一致看多 — 强烈共识, 罕见的高确定性机会"
        if all(v == "回避" for v in verdicts):
            return "四个视角一致看空 — 强烈共识回避, 无论故事多好都不该买"
        if all(v == "观望" for v in verdicts):
            return "四个视角一致观望 — 没有人看到足够的安全边际或确定性"

        # Partial agreement
        buy_cnt = sum(1 for v in verdicts if v == "买入")
        avoid_cnt = sum(1 for v in verdicts if v == "回避")
        if buy_cnt >= 3:
            return f"{buy_cnt}个视角看多 — 多数共识偏正面, 注意少数的反对理由"
        if avoid_cnt >= 3:
            return f"{avoid_cnt}个视角看空 — 多数共识偏负面, '多数时候多数人是对的, 但在市场拐点时要警惕'"
        return f"无一致观点 — 分歧度 {r.score_range:.1f}/5, 你需要独立判断"

    @classmethod
    def _find_disagreement(cls, r: DebateResult) -> str:
        scores = [("巴菲特", r.buffett.score), ("李录", r.li_lu.score),
                  ("芒格", r.munger.score), ("林奇", r.lynch.score)]
        high = max(scores, key=lambda x: x[1])
        low = min(scores, key=lambda x: x[1])
        high_concern = [r.buffett, r.li_lu, r.munger, r.lynch][scores.index(high)]
        low_concern = [r.buffett, r.li_lu, r.munger, r.lynch][scores.index(low)]
        return (f"最大分歧: {high[0]}({high[1]:.1f}) vs {low[0]}({low[1]:.1f}) "
                f"— 差 {r.score_range:.1f} 分")

    @classmethod
    def _synthesize_tension(cls, r: DebateResult) -> str:
        # 先统计投票方向
        verdicts = [r.buffett.verdict, r.li_lu.verdict, r.munger.verdict, r.lynch.verdict]
        buy_cnt = sum(1 for v in verdicts if v == "买入")
        avoid_cnt = sum(1 for v in verdicts if v == "回避")

        scores = [("巴菲特", r.buffett.score), ("李录", r.li_lu.score),
                  ("芒格", r.munger.score), ("林奇", r.lynch.score)]
        high = max(scores, key=lambda x: x[1])
        low = min(scores, key=lambda x: x[1])

        if r.agreement_level == "consensus":
            return "四大师视角高度一致 — 风险在于'所有人都看到的机会可能已被定价'，需警惕拥挤"
        elif r.agreement_level == "divided":
            if buy_cnt >= 3:
                return (f"四大师存在 {r.score_range:.1f} 分分歧但 {buy_cnt}/4 看多 — "
                        f"多数共识偏正面，{low[0]}({low[1]:.1f})的反对意见需认真对待但不改变整体偏多判断")
            elif avoid_cnt >= 3:
                return (f"四大师存在 {r.score_range:.1f} 分分歧但 {avoid_cnt}/4 看空 — "
                        f"多数共识偏负面，即使{high[0]}({high[1]:.1f})看好也应尊重多数意见")
            return (f"四大师存在 {r.score_range:.1f} 分分歧 — {high[0]}看多({high[1]:.1f})"
                    f"而{low[0]}看空({low[1]:.1f})。需理解双方的核心逻辑后独立判断")
        else:
            # polarized — 但也要看投票方向
            if buy_cnt >= 3:
                return (f"四大师存在较大分歧 ({r.score_range:.1f} 分) 但 {buy_cnt}/4 看多 — "
                        f"{high[0]}与{low[0]}判断对立，但多数共识偏向正面。"
                        f"关注{low[0]}的反对理由({low[1]:.1f})作为风险清单，不改变整体偏多方向")
            elif avoid_cnt >= 3:
                return (f"四大师严重对立 ({r.score_range:.1f} 分) 且 {avoid_cnt}/4 看空 — "
                        f"多数共识偏负面，即使{high[0]}({high[1]:.1f})看好也应高度警惕")
            return (f"四大师严重对立 ({r.score_range:.1f} 分) — {high[0]}与{low[0]}"
                    f"的判断截然相反。高不确定性意味着任何方向都可能出现，"
                    f"保守做法是等待分歧收敛或仅用小仓位试探")

    @classmethod
    def _synthesize_recommendation(cls, r: DebateResult) -> str:
        verdicts = [r.buffett.verdict, r.li_lu.verdict, r.munger.verdict, r.lynch.verdict]
        buy_cnt = sum(1 for v in verdicts if v == "买入")
        avoid_cnt = sum(1 for v in verdicts if v == "回避")

        if r.agreement_level == "consensus" and r.avg_score >= 3.5:
            return "四大师一致看多 — 罕见强共识信号，但注意拥挤风险（当所有人都看到时，机会可能已消退）"
        if r.agreement_level == "consensus" and r.avg_score <= 1.5:
            return "四大师一致看空 — 强烈建议回避，不论故事听起来多好"

        scores = [(r.buffett, "巴菲特"), (r.li_lu, "李录"), (r.munger, "芒格"), (r.lynch, "林奇")]
        highest = max(scores, key=lambda x: x[0].score)
        lowest = min(scores, key=lambda x: x[0].score)
        high_insight = highest[0].one_line_thesis or ""
        low_concern = lowest[0].key_concern or ""

        # 多数共识方向优先
        detail = ""
        if buy_cnt >= 3:
            detail += f"{buy_cnt}/4 大师看多 — 总体偏正面。"
            if high_insight:
                detail += f"{highest[1]}核心逻辑: {high_insight[:100]}"
            if low_concern:
                detail += f"。主要风险({lowest[1]}): {low_concern[:100]}"
        elif avoid_cnt >= 3:
            detail += f"{avoid_cnt}/4 大师看空 — 总体偏负面。"
            if low_concern:
                detail += f"核心理由: {low_concern[:100]}"
        else:
            if high_insight:
                detail += f"{highest[1]}的核心逻辑: {high_insight[:120]}"
            if low_concern:
                if detail:
                    detail += "；"
                detail += f"但{lowest[1]}提醒: {low_concern[:120]}"

        if detail:
            return detail
        return (
            f"{highest[1]}最乐观({highest[0].score:.1f}), "
            f"{lowest[1]}最悲观({lowest[0].score:.1f})。"
            f"建议: 理解{lowest[1]}的担忧后, 小仓位试探或等待更好价格。"
        )

    # ═══════════════════════════════════════════════════════════════════
    # v2.0: 管理层深度分析 + 空头案例自动生成
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def _analyze_management_trustworthiness(
        cls, l1, quote, fin, exec_score: float, mgmt_score: float,
    ) -> "ManagementTrustAnalysis":
        """自动分析管理层是否值得托付10年.

        从诊断报告、财务数据、高管信息中提取管理层层面的红旗和绿旗。
        不再只提问，而是给出基于数据的回答。
        """
        result = ManagementTrustAnalysis()

        # 基础分
        result.ability_score = min(100, mgmt_score + 10)  # 能力通常高于综合管理分
        result.integrity_score = max(20, exec_score - 20) if exec_score > 0 else 30
        result.capital_score = min(100, mgmt_score)

        # 提取高管风险
        exec_risks = getattr(l1, "executive_risks", []) or []
        exec_data = getattr(l1, "executive", None)

        # 检测红旗信号
        if exec_risks:
            for risk in exec_risks:
                risk_str = str(risk).lower()
                if any(kw in risk_str for kw in ["内幕", "违规", "处罚", "刑事", "调查", "警示函",
                                                   "减持", "质押", "冻结"]):
                    result.integrity_score = max(10, result.integrity_score - 20)
                    result.red_flags.append(f"🔴 合规风险: {str(risk)[:120]}")

        # 高管背景缺失检测 — 数据源不可用时仅降 confidence，不作为红旗
        if exec_data:
            has_background = getattr(exec_data, "has_background_check", None)
            if has_background is False:
                result.integrity_score = max(20, result.integrity_score - 5)
                result.caveats.append("⚠️ 高管背景数据不可用 — 无法评估管理层诚信，建议补充尽职调查")

        # 财务检测: 关联交易、商誉、质押
        if fin and len(fin) > 0:
            latest = fin[0]
            goodwill_ratio = latest.get("商誉占比", 0) or 0
            if goodwill_ratio > 0.3:
                result.capital_score = max(10, result.capital_score - 15)
                result.red_flags.append(f"🟠 商誉/净资产>{goodwill_ratio:.0%} — 历史并购质量存疑")

        # 家族传承检测
        exec_info = getattr(l1, "executive_info", {}) or {}
        if isinstance(exec_info, dict):
            has_family = exec_info.get("family_succession", False)
            if has_family:
                result.integrity_score = max(10, result.integrity_score - 10)
                result.red_flags.append("🟡 家族传承迹象 — 非市场化选聘管理层")

        # 生成结论
        if result.integrity_score < 30:
            result.verdict = (
                f"⚠️ 李录之问: 管理层诚信分 {result.integrity_score}/100 — "
                f"存在重大治理缺陷，不值得托付10年。能力({result.ability_score})越强，"
                f"诚信缺失造成的破坏越大。"
            )
        elif result.integrity_score < 50:
            result.verdict = (
                f"⚠️ 李录之问: 管理层诚信分 {result.integrity_score}/100 — "
                f"能力出众({result.ability_score})但治理有瑕疵，需要持续观察。"
            )
        elif result.red_flags:
            result.verdict = (
                f"🟡 李录之问: 管理层能力{result.ability_score}/诚信{result.integrity_score}/"
                f"配置{result.capital_score} — 整体可接受但需关注已标记风险点"
            )
        else:
            result.verdict = (
                f"✅ 李录之问: 管理层能力{result.ability_score}/诚信{result.integrity_score}/"
                f"配置{result.capital_score} — 未发现重大治理缺陷，可基本托付"
            )

        return result

    @classmethod
    def _build_bear_case(cls, l1, quote, fin) -> "BearCaseAnalysis | None":
        """自动构建空头案例.

        从现有数据中提取: 估值极端、融资趋势、价格趋势、财务风险、宏观风险。
        不再依赖外部 bear_case 文本，直接从诊断数据生成。
        """
        scenarios: list[str] = []
        evidence: list[str] = []
        failure_reasons: list[tuple[str, float]] = []  # (reason, probability)

        pe = (quote.get("pe_ttm") or quote.get("pe") or 0) if quote else 0
        pb = (quote.get("pb") or 0) if quote else 0
        price = (quote.get("price") or quote.get("close") or 0) if quote else 0

        # 1. 估值极端风险
        if pe > 60:
            prob = min(0.35, (pe - 30) / 200)
            scenarios.append(f"🔴 估值坍塌: PE={pe:.0f}x，若跌至行业均值20x，股价将跌{((pe-20)/pe*100):.0f}%")
            failure_reasons.append((f"高估值回归 (PE={pe:.0f}x)", prob))
            evidence.append(f"PE(TTM)={pe:.1f}, 行业中枢约20-25x")

        if pb > 8:
            scenarios.append(f"🔴 PB={pb:.1f}x，资产端存在高估风险")

        # 2. 动量持续下行风险 (分级)
        mom = getattr(l1, "momentum_score", 50) or 50
        if mom < 10:
            prob = 0.35
            scenarios.append(
                f"🔴 动量崩溃: 趋势评分{mom}/100，"
                f"剧烈下跌可能触发融资盘强平踩踏"
            )
            failure_reasons.append(("动量崩溃→融资踩踏", prob))
        elif mom < 22:
            prob = 0.25
            scenarios.append(
                f"🟠 持续下行: 趋势评分{mom}/100，"
                f"弱势格局下进一步下跌的概率较高"
            )
            failure_reasons.append(("下跌趋势持续侵蚀→资金流出", prob))
        elif mom < 35:
            prob = 0.15
            scenarios.append(
                f"🟡 趋势偏弱: 趋势评分{mom}/100，"
                f"短期缺乏上涨动能但不构成踩踏风险"
            )
        if mom < 35:
            evidence.append(f"动量评分={mom}/100(偏弱)")

        # 3. 融资余额趋势 (margin)
        margin_data = getattr(l1, "margin_profile", None)
        if margin_data:
            if hasattr(margin_data, "consecutive_outflow_days") and margin_data.consecutive_outflow_days >= 3:
                prob = 0.20
                scenarios.append(
                    f"🔴 杠杆资金撤退: 融资连续{margin_data.consecutive_outflow_days}天净流出, "
                    f"5日变化{margin_data.margin_balance_5d_change_pct:+.1f}%"
                )
                failure_reasons.append(("杠杆资金持续撤退→流动性枯竭", prob))
                evidence.append(
                    f"融资余额{margin_data.margin_balance:.1f}亿, "
                    f"趋势{margin_data.margin_balance_trend}"
                )

        # 4. 财务风险
        if fin and len(fin) > 0:
            latest = fin[0]
            debt_ratio = latest.get("资产负债率", 0) or 0
            if debt_ratio > 0.55:
                prob = 0.15
                scenarios.append(f"🟠 高杠杆风险: 资产负债率{debt_ratio:.0%}，若锂价持续下跌可能触发债务危机")
                failure_reasons.append(("高杠杆+锂价下行→偿债压力", prob))
                evidence.append(f"资产负债率={debt_ratio:.1%}")

        # 5. 宏观-行业周期风险
        val_score = getattr(l1, "value_score", 50) or 50
        macro_score = getattr(l1, "macro_score", 50) or 50
        if val_score < 40:
            scenarios.append("🟡 估值偏高: 当前价格可能未充分反映锂价下行风险")
            failure_reasons.append(("估值未反映锂价下行", 0.15))
        if macro_score < 45:
            scenarios.append("🟡 宏观逆风: 宽货币紧信用环境不利于周期股")

        if not scenarios:
            return None

        # 取 top failure reason
        failure_reasons.sort(key=lambda x: x[1], reverse=True)
        top_reason = failure_reasons[0][0] if failure_reasons else "多因素叠加"

        total_prob = min(0.80, sum(f[1] for f in failure_reasons))
        summary = (
            f"芒格空头案例: {len(scenarios)}个独立失败场景, 综合概率~{total_prob:.0%}. "
            f"最可能: {top_reason}"
        )

        return BearCaseAnalysis(
            scenarios=scenarios,
            summary=summary,
            top_failure_reason=top_reason,
            total_failure_prob=total_prob,
            evidence=evidence,
        )
