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

        scores = [result.buffett.score, result.li_lu.score, result.munger.score, result.lynch.score]
        result.avg_score = sum(scores) / len(scores)
        result.score_range = max(scores) - min(scores)

        if result.score_range <= 1.0:
            result.agreement_level = "consensus"
        elif result.score_range <= 2.5:
            result.agreement_level = "divided"
        else:
            result.agreement_level = "polarized"

        result.top_agreement = cls._find_agreement(result)
        result.top_disagreement = cls._find_disagreement(result)
        result.tension_summary = cls._synthesize_tension(result)
        result.recommendation = cls._synthesize_recommendation(result)
        return result

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

        # 支柱3: PE 检查 (业务可预测性+价格合理性)
        pe = (quote.get("pe_ttm") or quote.get("pe") or 0) if quote else 0
        if 0 < pe < 15:
            score += 1.0
            bull.append(f"PE={pe:.1f}<15 — 典型的巴菲特价值区间")
        elif pe < 25:
            score += 0.3
            bull.append(f"PE={pe:.1f} — 尚在合理范围，需结合成长性判断")
        elif pe > 50:
            score -= 1.0
            bear.append(f"PE={pe:.1f}>50 — 巴菲特从不为高估值买单，无论故事多好")
        elif pe > 30:
            score -= 0.3
            bear.append(f"PE={pe:.1f}>30 — 估值偏贵，安全边际不足")

        # 支柱4: 业务可预测性 (cycle+macro proxy)
        cycle = getattr(l1, "cycle_score", 50) or 50
        ps.sub_scores["业务可预测性"] = round(cycle / 100 * 2, 2)
        score += (cycle / 100 * 2) - 1.0
        if cycle >= 70:
            bull.append(f"周期适配度 {cycle}/100 — 经济周期对业务影响可控，可预测性较高")

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
        ps.key_concern = ("估值过高，安全边际不足" if v < 45 or pe > 30
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
            bear.append(f"高管评分 {exec_score}/100 — 管理层存在红旗信号")
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

        # 逆向测试1: 风险点扫描
        risks = getattr(l1, "upstream_risks", []) or []
        exec_risks = getattr(l1, "executive_risks", []) or []
        bottlenecks = getattr(l1, "bottlenecks", []) or []
        total_risks = len(risks) + len(exec_risks) + len(bottlenecks)

        if total_risks == 0:
            score += 0.5
            bull.append("逆向扫描未发现显著风险 — 基础面干净")
        elif total_risks <= 2:
            score -= 0.3
            bear.append(f"检测到{total_risks}个风险点 — 需要逐个验证")
        else:
            score -= 1.0
            bear.append(f"⚠️ {total_risks}个风险信号 — 芒格准则: '先证明这不是个错误'")

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
        if r.agreement_level == "consensus":
            return "四大师视角高度一致 — 风险在于'所有人都看到的机会可能已被定价'，需警惕拥挤"
        elif r.agreement_level == "divided":
            scores = [("巴菲特", r.buffett.score), ("李录", r.li_lu.score),
                      ("芒格", r.munger.score), ("林奇", r.lynch.score)]
            high = max(scores, key=lambda x: x[1])
            low = min(scores, key=lambda x: x[1])
            return (f"四大师存在 {r.score_range:.1f} 分分歧 — {high[0]}看多({high[1]:.1f})"
                    f"而{low[0]}看空({low[1]:.1f})。需理解双方的核心逻辑后独立判断")
        else:
            scores = [("巴菲特", r.buffett.score), ("李录", r.li_lu.score),
                      ("芒格", r.munger.score), ("林奇", r.lynch.score)]
            high = max(scores, key=lambda x: x[1])
            low = min(scores, key=lambda x: x[1])
            return (f"四大师严重对立 ({r.score_range:.1f} 分) — {high[0]}与{low[0]}"
                    f"的判断截然相反。高不确定性意味着任何方向都可能出现，"
                    f"保守做法是等待分歧收敛或仅用小仓位试探")

    @classmethod
    def _synthesize_recommendation(cls, r: DebateResult) -> str:
        if r.agreement_level == "consensus" and r.avg_score >= 3.5:
            return "四大师一致看多 — 罕见强共识信号，但注意拥挤风险（当所有人都看到时，机会可能已消退）"
        if r.agreement_level == "consensus" and r.avg_score <= 1.5:
            return "四大师一致看空 — 强烈建议回避，不论故事听起来多好"
        scores = [(r.buffett, "巴菲特"), (r.li_lu, "李录"), (r.munger, "芒格"), (r.lynch, "林奇")]
        highest = max(scores, key=lambda x: x[0].score)
        lowest = min(scores, key=lambda x: x[0].score)
        # 引用具体洞察而非仅说名字
        high_insight = highest[0].one_line_thesis or ""
        low_concern = lowest[0].key_concern or ""
        detail = ""
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
