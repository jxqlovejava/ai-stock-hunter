# -*- coding: utf-8 -*-
r"""详细分析输出格式化器

Profile-Aware 备注:
  - 本模块当前使用统一的终端风格输出。
  - 要适配不同渠道 (微信/邮件/API)，使用 src/output/profiles.py 中的
    OutputProfile 来决定 table_style、markdown_allowed、max_length、
    language、tone 等参数。
  - 示例:
        from src.output.profiles import get_profile
        profile = get_profile("wechat")
        if not profile.markdown_allowed:
            # 剥离 emoji / Markdown 标记
            pass
        if profile.is_truncated:
            # 截断到 profile.max_length
            pass
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.routing.orchestrator import OrchestratorResult
    from src.routing.diagnosis import DiagnosisReport
    from src.routing.verdict import Verdict
    from src.data.source_citation import SourceCitation

HR = "─" * 60
HR_THICK = "━" * 60

NATURE_ICON = {"fact": "📊", "interpretation": "🧠", "speculation": "🔮", "data_gap": "⚠️"}
NATURE_LABEL = {"fact": "事实", "interpretation": "解释", "speculation": "推测", "data_gap": "缺口"}

PERSPECTIVE_EMOJI = {"buffett": "🏰", "li_lu": "🎓", "munger": "🧠", "lynch": "🔍"}
PERSPECTIVE_NAME = {"buffett": "巴菲特", "li_lu": "李录", "munger": "芒格", "lynch": "林奇"}
PERSPECTIVE_TAG = {
    "buffett": "护城河+安全边际+长期持有",
    "li_lu": "管理层文化+能力圈+复利思维",
    "munger": "逆向思维+心理学+避免愚蠢",
    "lynch": "PEG+成长性+草根调研",
}

REC_EMOJI = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴", "CLOSE": "🔴"}
REC_LABEL = {"BUY": "建议买入", "ADD": "可加仓", "HOLD": "继续持有", "REDUCE": "建议减仓", "SELL": "建议卖出", "CLOSE": "建议清仓"}
REC_EXPLAIN = {
    "BUY": "综合评分≥75，多维度支持建仓",
    "ADD": "综合评分60-74，可小幅加仓",
    "HOLD": "综合评分40-59，信号混杂，观望为宜",
    "REDUCE": "综合评分25-39，风险大于机会",
    "SELL": "综合评分<25，多重风险叠加",
    "CLOSE": "触发硬性风控，建议清仓",
}

# 集中式英→中标签映射（只改渲染层，不改内部存储）
CN = {
    # 生命周期阶段
    "emerging": "萌芽期", "spreading": "扩散期", "consensus": "共识期",
    "crowded": "拥挤期", "fading": "消退期", "dormant": "休眠期",
    # 经济周期
    "expansion": "扩张期", "contraction": "收缩期", "trough": "谷底期", "peak": "顶峰期",
    # 四大师协议等级
    "polarized": "🔴严重对立", "divided": "⚠️存在分歧", "consensus": "高度一致",
    # 市场情绪
    "PANIC": "😱恐慌", "EXTREME": "🥶极度恐慌", "NORMAL": "😐正常", "GREED": "😈贪婪",
    "NEUTRAL": "中性",
    # VMA 区域
    "LOW_BASE": "低位启动", "HIGH_ACCEL": "高位加速", "NEUTRAL": "中性区",
    # 仓位算法
    "kelly": "凯利公式", "linear_fallback": "线性回退", "negative_expectation": "负期望（不下注）",
    # T+0 操作
    "add": "可以加仓", "hold": "观望等待", "reduce": "建议减仓", "cut": "坚决减仓", "no_position": "不建议建仓",
    # 操纵模式 (risk_control.py 违规消息中出现的英文术语)
    "fishing_line": "钓鱼线出货",
    "lure_bull_dump": "诱多出货",
    "closing_pump": "尾盘拉升",
    "closing_dump": "尾盘砸盘",
    "wash_trade_pump": "对倒拉升",
    "shakeout": "洗盘震仓",
    "news_distribution": "消息配合出货",
}

import logging
_logger = logging.getLogger(__name__)

# ── 标准化分段输出 ────────────────────────────────────────────────

# 输出分段注册表：定义每个 Step 的序号、图标、名称，保证每次输出格式统一
SECTION = [
    (1,  "🏥", "军规审查"),
    (2,  "🚪", "准入检查 & 市场全景"),
    (3,  "📊", "多维诊断"),
    (4,  "🎭", "四大师辩论"),
    (5,  "🧠", "Munger 思维模型"),
    (6,  "🔬", "辅助指标 (Alpha + 博弈论)"),
    (7,  "⚖️", "综合裁决"),
    (8,  "💰", "仓位调度"),
    (9,  "🛡️", "风控执行"),
    (10, "📊", "数据溯源"),
    (11, "⏱️", "T+0 日内时机分析"),
]
SECTION_BY_NUM = {s[0]: s for s in SECTION}


def _section(lines: list[str], step_num: int, *, extra_name: str = ""):
    """追加标准化分段标题。每个分段格式统一:

      Step N  [icon] [name]
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    info = SECTION_BY_NUM.get(step_num)
    if info is None:
        lines.append(f"\n  Step {step_num}")
        lines.append(f"  {HR_THICK}")
        return
    _, emoji, name = info
    title = f"Step {step_num}  {emoji} {name}"
    if extra_name:
        title += f" — {extra_name}"
    lines.append(f"\n  {title}")
    lines.append(f"  {HR_THICK}")


def _ensure_cn(text: str) -> str:
    """确保文本中的英文术语被翻译为中文。

    先查 CN 字典完整匹配，再对已知英文术语做子串替换。
    兜底：若文本仍含已知英文键，记录警告。
    """
    # 1) 完整匹配
    if text in CN:
        return CN[text]
    # 2) 子串替换 — 操纵模式等可能嵌在长句中
    result = text
    for en_term, cn_term in CN.items():
        if en_term in result:
            result = result.replace(en_term, cn_term)
    # 3) 残存英文检测（仅警告，不阻断输出）
    if result != text:
        import re
        # 检查是否还有未翻译的已知英文键
        remaining = [k for k in CN if k in result and k not in ("NEUTRAL",)]
        # NEUTRAL 是正常的中性词，忽略
    return result
T0_EMOJI = {"add": "🟢", "hold": "🟡", "reduce": "🟠", "cut": "🔴", "no_position": "⚪"}


def format_info_availability(stock_info: dict) -> str:
    """信息可得性分级 (A/B/C) — 基于信息环境给出策略重点。

    Args:
        stock_info: 包含 market_cap, data_sources_count 等字段的 dict

    Returns:
        格式化字符串，包含等级、说明和策略建议
    """
    market_cap = stock_info.get("market_cap") or 0
    data_src_count = stock_info.get("data_sources_count", 0)
    citation_count = stock_info.get("source_citations_count", 0)

    if market_cap > 200e8:
        grade = "A级"
        desc = "大盘股，信息供给充足"
        advice = "降噪优先 — 区分 T0-T1 一手源与 T2-T3 二手转述，过滤标题党"
    elif data_src_count >= 4 or citation_count >= 15:
        grade = "A级"
        desc = "数据覆盖广，信息丰富"
        advice = "降噪优先 — 区分 T0-T1 一手源与 T2-T3 二手转述，过滤标题党"
    elif market_cap > 20e8:
        grade = "B级"
        desc = "中小盘，覆盖一般"
        advice = "每条关键事件附 1-2 个独立信源"
    elif data_src_count >= 2 or citation_count >= 5:
        grade = "B级"
        desc = "覆盖一般"
        advice = "每条关键事件附 1-2 个独立信源"
    else:
        grade = "C级"
        desc = "冷门标的，信息稀缺"
        advice = "'查不到解释'本身有价值 — 可能是技术面/资金面驱动而非基本面"

    lines = [
        f"  📡 信息可得性: {grade} {desc}",
        f"     策略: {advice}",
    ]
    return "\n".join(lines)


def format_analysis_result(result: OrchestratorResult) -> str:
    verdict = result.verdict
    report = result.report
    lines: list[str] = []

    # ── 头部 ──────────────────────────────────────────────────────────
    lines.append(f"\n  {result.name}({result.symbol}) 全链路分析")
    lines.append(f"  {HR}")

    # 元信息
    meta = []
    p = result.investor_prefs_applied or {}
    meta.append(f"风险:{p.get('risk_profile','?')}  目标:{p.get('investment_goal','?')}  级别:{p.get('tier','?')}")
    meta.append(f"行情:{'✅双源一致' if result.cross_validated else '⚠️单源'}")
    lines.append("  " + "  │  ".join(meta))

    if getattr(result, "profile_completeness", 50) < 50:
        lines.append(f"\n  ⚠️ 画像完整度{getattr(result,'profile_completeness',0)}% "
                     f"— python -m src.cli preference setup 设置专属画像")

    # ── 📌 核心结论 ──────────────────────────────────────────────────
    lines.append(f"\n  📌 核心结论")
    lines.append(f"  {HR}")

    enforced = result.enforced_verdict
    if verdict and enforced:
        rec = verdict.recommendation
        lines.append(f"  {REC_EMOJI.get(rec,'⚪')} {REC_LABEL.get(rec,rec)}  "
                     f"评分 {verdict.score}/100  置信度 {verdict.confidence:.0%}")
        lines.append(f"  {REC_EXPLAIN.get(rec,'')}")
        lines.append(f"  💡 {enforced.get('one_line_conclusion','')}")
        pr = enforced.get("price_range", {})
        if pr:
            lines.append(f"  当前 {pr.get('current_price')}  "
                         f"买入≤{pr.get('buy_below')}  "
                         f"卖出≥{pr.get('sell_above')}  [🔮推测]")

    # 信息可得性分级
    cit = result.report.source_citations if result.report else []
    unique_providers = set(c.provider for c in cit)
    info = {
        "data_sources_count": len(unique_providers),
        "source_citations_count": len(cit),
    }
    lines.append("")
    lines.append(format_info_availability(info))

    # ── Step 1 军规审查 ──────────────────────────────────────────────
    doctrine = result.doctrine_result
    if doctrine and doctrine.get("rules"):
        rules = doctrine["rules"]
        bc = doctrine.get("blocked_count", 0)
        wc = doctrine.get("warn_count", 0)
        lines.append(f"\n  Step 1  🏥 军规审查")
        lines.append(f"  {HR}")
        ok = "✅" if doctrine.get("passed") else "⛔"
        lines.append(f"  {ok} {doctrine.get('total',31)}条规则: "
                     f"🔴阻断{bc}  🟠警告{wc}  ℹ️信息{doctrine.get('info_count',0)}")

        CAT_LABEL = {
            "position": "💰 仓位管理", "selection": "🔍 选股估值",
            "trading": "📈 买卖纪律", "emotion": "🧘 情绪纪律",
            "information": "📰 信息纪律", "risk": "🛡️ 风控止损",
            "review": "📝 复盘进化", "meta": "⚙️ 元风控",
        }
        SI = {"passed": "✅", "warn": "🟠", "blocked": "🔴", "info": "ℹ️"}

        by_cat: dict[str, list] = {}
        for r in rules:
            by_cat.setdefault(r.get("category", ""), []).append(r)

        for cat in ["position", "selection", "trading", "emotion", "information", "risk", "review", "meta"]:
            cr = by_cat.get(cat, [])
            if not cr:
                continue
            lines.append(f"\n  {CAT_LABEL.get(cat, cat)}")
            for r in cr:
                icon = SI.get(r["status"], "❓")
                lines.append(f"    {icon} [{r['id']}] {r['name']:10s} [{r['severity'].upper():5s}] {r['description']}")

    # ── Step 2 准入检查 & 市场全景 ──────────────────────────────────
    gs = result.gate_status or "UNKNOWN"
    ge = {"ACCEPTED": "✅", "REJECTED": "⛔", "FLAGGED": "⚠️"}.get(gs, "❓")
    gl = {"ACCEPTED": "通过", "REJECTED": "被拦截", "FLAGGED": "标记风险"}.get(gs, gs)
    lines.append(f"\n  Step 2  🚪 准入检查 & 市场全景")
    lines.append(f"  {HR}")
    lines.append(f"  {ge} {gl} — ST排除 | 次新60天 | 日成交≥5000万 | 涨跌停 | 停牌")
    if result.data_gaps:
        lines.append(f"  📭 {', '.join(result.data_gaps)}")
    if result.red_lines:
        lines.append(f"  🚨 {', '.join(result.red_lines)}")

    # ── 市场全景 ──
    sent = getattr(result, "market_sentiment", None)
    if not sent or not isinstance(sent, dict):
        sent = {"level": getattr(result.report, "sentiment_signal", "NORMAL") if result.report else "NORMAL"}
    lines.append("")
    sl = sent.get("level", "NORMAL")
    level_cn = CN.get(sl, sl)
    lines.append(f"  📡 市场情绪: {level_cn} (评分 {sent.get('score','?')}/100)")
    if sent.get("market_breadth_insight"):
        lines.append(f"  📐 市场宽度: {sent['market_breadth_insight']}")
    if sent.get("volume_insight"):
        lines.append(f"  📊 成交量: {sent['volume_insight']}")
    if sent.get("northbound_insight"):
        lines.append(f"  🧭 北向资金: {sent['northbound_insight']}")
    if sent.get("limit_pool_insight"):
        lines.append(f"  🚦 涨跌停: {sent['limit_pool_insight']}")
    if sent.get("vix_insight"):
        lines.append(f"  🌊 波动率: {sent['vix_insight']}")
    if sent.get("panic_arb_advice"):
        lines.append(f"  🎯 恐慌套利: {sent['panic_arb_advice']}")

    # ── Step 3 多维诊断 ──────────────────────────────────────────────
    lines.append(f"\n  Step 3  📊 多维诊断")
    lines.append(f"  {HR}")

    if report:
        # 画像
        mm = result.mental_model_info
        if mm:
            fi = "✅" if mm.get("fit_score", 0) >= 60 else ("⚠️" if mm.get("fit_score", 0) >= 40 else "❌")
            comp = mm.get("competence_match", "")
            cl = {
                "in_circle": "✅ 能力圈内",
                "edge": "⚠️ 边缘",
                "out_of_circle": "❌ 能力圈外",
                "not_configured": "⚪ 能力圈未设",
            }.get(comp, comp)
            lines.append(f"  👤 匹配度 {fi} {mm.get('fit_score',0)}/100  {cl}")
            for b in mm.get("bias_flags", [])[:2]:
                lines.append(f"     ⚠️ {b}")
            for w in mm.get("warnings", [])[:2]:
                lines.append(f"     📋 {w}")

        # 八维评分
        lines.append("")
        rows = [
            ("宏观环境", report.macro_score), ("价值因子", report.value_score),
            ("质量因子", report.quality_score), ("动量因子", report.momentum_score),
            ("盈利修正", report.earnings_revision_score), ("估值综合", report.valuation_score),
            ("周期适配", report.cycle_score), ("高管因子", report.executive_score),
        ]
        for label, score in rows:
            bar = "▓" * int(score / 5) + "░" * (20 - int(score / 5))
            lines.append(f"  {label:6s} {score:5.0f} {bar} [🧠解释]")
        lines.append(f"  情绪     {CN.get(report.sentiment_signal, report.sentiment_signal)} [📊事实]")

        if report.executive_risks:
            for r in report.executive_risks[:2]:
                lines.append(f"  ⚠️ 高管风险: {r}")
        lines.append(f"  置信度 {report.confidence:.0%}  数据 {report.data_freshness.strftime('%m-%d %H:%M')}")
        if report.cycle_phase:
            lines.append(f"  周期 {CN.get(report.cycle_phase, report.cycle_phase)}  适配 {report.cycle_score:.0f}/100")

        # 多空
        # 多维诊断综述
        if report.dimension_synthesis:
            lines.append(f"\n  📝 多维诊断综述")
            for synth_line in report.dimension_synthesis.split("\n"):
                lines.append(f"  {synth_line}")

        if report.bull_case:
            lines.append(f"\n  🟢 看多: {report.bull_case}")
        if report.bear_case:
            lines.append(f"  🔴 看空: {report.bear_case}")

        # 瓶颈
        ba = report.bottleneck_analysis
        if ba:
            lines.append(f"\n  🏭 供应链瓶颈: {ba.core_business}")
            lines.append(f"  定位:{ba.supply_chain_layer}  类型:{ba.bottleneck_type}  评分:{ba.bottleneck_score}/100")

        # 三情景
        sv = result.scenario_valuation
        if sv:
            lines.append(f"\n  📐 三情景估值 [🔮推测]")
            inp = sv.get("inputs", {})
            inp_s = ", ".join(f"{k}={v}" for k, v in inp.items() if v is not None)
            lines.append(f"  方法:{sv.get('method','?')}  参数:{inp_s}")
            u = sv.get("implied_upside", 0) or 0
            d = sv.get("implied_downside", 0) or 0
            rr = "有利" if u > abs(d) * 2 else ("较有利" if u > abs(d) else "一般")
            lines.append(f"  🟢{sv.get('bull_target')}  🟡{sv.get('base_target')}  🔴{sv.get('bear_target')}")
            lines.append(f"  上涨{u:+.1f}%  下跌{d:+.1f}%  风险收益比:{rr}")

    # ── Step 4 四大师辩论 ────────────────────────────────────────────
    pp = result.debate_perspectives
    dr = result.debate_result
    lines.append(f"\n  Step 4  🎭 四大师辩论")
    lines.append(f"  {HR}")

    if pp and dr:
        lines.append(f"  均分 {dr.get('avg_score',0):.2f}/5  "
                     f"分歧度 {dr.get('score_range',0):.2f}  "
                     f"{CN.get(dr.get('agreement_level',''), dr.get('agreement_level','?'))}")
        if dr.get("tension_summary"):
            lines.append(f"  📋 综述: {dr['tension_summary']}")
        if dr.get("top_disagreement"):
            lines.append(f"  ⚡ 最大分歧: {dr.get('top_disagreement')}")
        if dr.get("recommendation"):
            lines.append(f"  🎯 综合建议: {dr['recommendation']}")
        lines.append("")

        for key in ["buffett", "li_lu", "munger", "lynch"]:
            p = pp.get(key)
            if not p:
                continue
            score = p.get("score", 0)
            stars = "★" * max(1, int(score)) + "☆" * max(0, 5 - int(score))
            vi = {"买入": "🟢", "观望": "🟡", "回避": "🔴"}.get(p.get("verdict", ""), "⚪")

            lines.append(f"  {PERSPECTIVE_EMOJI[key]} {PERSPECTIVE_NAME[key]} "
                         f"({PERSPECTIVE_TAG[key]})")
            lines.append(f"  {stars} {score:.1f}/5  {vi} {p.get('verdict','')}")
            if p.get("methodology"):
                lines.append(f"  📐 {p['methodology']}")
            if p.get("one_line_thesis"):
                lines.append(f"  💡 {p['one_line_thesis']}")
            # 独特洞察
            if p.get("unique_insight"):
                lines.append(f"  🔬 {p['unique_insight']}")
            # 看多/看空依据 (全部展示)
            for b in p.get("bull_points", [])[:4]:
                lines.append(f"  🟢 {b}")
            for b in p.get("bear_points", [])[:4]:
                lines.append(f"  🔴 {b}")
            if p.get("key_concern"):
                lines.append(f"  ⚠️ {p['key_concern']}")
            # 该大师提出的问题
            for q in p.get("questions_to_ask", [])[:2]:
                lines.append(f"  ❓ {q}")

    # ── Step 5 Munger 思维模型 ───────────────────────────────────────
    mm_models = result.mental_models
    lines.append(f"\n  Step 5  🧠 Munger 思维模型")
    lines.append(f"  {HR}")

    if mm_models:
        lines.append(f"  从232个模型中匹配{len(mm_models)}个:")
        by_d: dict[str, list] = {}
        for m in mm_models:
            by_d.setdefault(m.get("discipline", "其他"), []).append(m)
        for disc, models in by_d.items():
            lines.append(f"\n  {disc} ({len(models)})")
            for m in models:
                desc = m.get("description", "")
                reason = m.get("reason_for_match", "")
                lines.append(f"  · {m['name_cn']}")
                if desc:
                    lines.append(f"    {desc}")
                # 应用洞察：展示该模型如何具体应用于当前股票
                if reason:
                    lines.append(f"    → {reason}")
                # 股票特定分析
                app = m.get("application_to_stock", "")
                if app:
                    lines.append(f"    📌 应用于{result.name}: {app}")

    # ── Step 5½ 行业深度研究 ──────────────────────────────────────────
    sector = result.sector_research
    if sector and sector.get("sector_name") != "未分类":
        lines.append(f"\n  🏭 行业深度研究")
        lines.append(f"  {HR}")
        lines.append(f"  行业: {sector.get('sector_name','')}  "
                     f"基准指数 {sector.get('benchmark_index','N/A')}")
        comp = sector.get("competition", {})
        if comp:
            lines.append(f"  竞争: CR5={comp.get('cr5',0):.0f}% HHI={comp.get('hhi',0):.0f} "
                         f"{comp.get('concentration','')} "
                         f"壁垒={comp.get('barrier','?')} "
                         f"烈度={comp.get('intensity',50):.0f}")
        val_fw = sector.get("valuation", {})
        if val_fw:
            lines.append(f"  估值: {val_fw.get('primary_method','?')} "
                         f"PE中枢={val_fw.get('pe_median',0):.0f} "
                         f"分位={val_fw.get('pe_percentile',50):.0f}% "
                         f"吸引力={val_fw.get('attractiveness',50):.0f}/100")
        sc = sector.get("supply_chain", {})
        if sc and sc.get("in_chain"):
            lines.append(f"  供应链: {sc.get('node_name','?')} "
                         f"层级={sc.get('layer','?')} "
                         f"瓶颈={sc.get('bottleneck_score',0):.0f}/100 "
                         f"传导={sc.get('cost_pass_through',0.5):.1f}")

    # ── Step 5¾ 公司深度研究 ──────────────────────────────────────────
    company = result.company_deep_research
    if company:
        lines.append(f"\n  🔬 公司深度研究")
        lines.append(f"  {HR}")
        moat_data = company.get("moat", {})
        if moat_data:
            dims = moat_data.get("dimensions", {})
            lines.append(f"  🏰 护城河: {moat_data.get('width','?')} "
                         f"{moat_data.get('score',50):.0f}/100 "
                         f"趋势={moat_data.get('trend','stable')}")
            if dims:
                lines.append(f"     品牌{dims.get('brand',50):.0f} "
                             f"转换成本{dims.get('switching_cost',50):.0f} "
                             f"网络效应{dims.get('network_effect',50):.0f} "
                             f"规模{dims.get('scale_economy',50):.0f} "
                             f"无形{dims.get('intangible',50):.0f}")
            for ev in moat_data.get("evidence", [])[:2]:
                lines.append(f"     ✓ {ev}")
            for th in moat_data.get("threats", [])[:2]:
                lines.append(f"     ⚠ {th}")

        rf_data = company.get("red_flags")
        if rf_data:
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
            lines.append(f"  🚩 财务红旗: {risk_emoji.get(rf_data.get('risk','unknown'),'?')} "
                         f"{rf_data.get('risk','?').upper()} "
                         f"({rf_data.get('total_flags',0)}个)")
            if rf_data.get("m_score") is not None:
                lines.append(f"     M-Score={rf_data['m_score']:.2f}({rf_data.get('m_score_label','?')}) "
                             f"F-Score={rf_data.get('f_score',0):.0f}/9({rf_data.get('f_score_label','?')})")

        dcf_data = company.get("dcf")
        if dcf_data:
            lines.append(f"  💎 DCF: 公允价 ¥{dcf_data.get('fair_value',0):.2f} "
                         f"安全边际={dcf_data.get('margin_of_safety',0):.1f}% "
                         f"上行={dcf_data.get('upside_pct',0):+.1f}%")
            lines.append(f"     熊¥{dcf_data.get('bear_case',0):.1f} "
                         f"基¥{dcf_data.get('base_case',0):.1f} "
                         f"牛¥{dcf_data.get('bull_case',0):.1f} "
                         f"WACC={dcf_data.get('wacc',0.1):.1%}")

        mgmt_data = company.get("management", {})
        if mgmt_data:
            lines.append(f"  👔 管理层: {mgmt_data.get('overall',50):.0f}/100 "
                         f"配置{mgmt_data.get('capital_allocation',50):.0f} "
                         f"诚信{mgmt_data.get('integrity',50):.0f} "
                         f"能力{mgmt_data.get('competency',50):.0f} "
                         f"激励{mgmt_data.get('incentive',50):.0f}")

        cons_data = company.get("consensus")
        if cons_data:
            lines.append(f"  📋 一致预期({cons_data.get('n_analysts',0)}位): "
                         f"{cons_data.get('rating','?')} "
                         f"目标¥{cons_data.get('target_mean',0):.1f} "
                         f"买{cons_data.get('buy',0)}/持{cons_data.get('hold',0)}/卖{cons_data.get('sell',0)}")

        overall = company.get("overall_score", 50)
        lines.append(f"  🏆 深度研究综合: {overall:.0f}/100")

    # ── Step 5½ 辅助指标 ─────────────────────────────────────────────
    alpha = result.alpha_profile
    gt = result.game_theory_info
    if alpha or gt:
        lines.append(f"\n  🔬 辅助指标")
        lines.append(f"  {HR}")
    if alpha:
        lines.append(f"  📈 Alpha {alpha.alpha_score:.0f}/100  "
                     f"一手性{alpha.source.originality_score:.0f}/100  "
                     f"叙事{CN.get(alpha.narrative.stage.value, alpha.narrative.stage.value)}")
        if alpha.summary:
            lines.append(f"  💡 {alpha.summary}")
    if gt:
        lines.append(f"  🎲 博弈论 {gt.get('score',0)}/100  主导{gt.get('dominant_player','?')}  "
                     f"拥挤{gt.get('crowding_score',0)}  杠杆{gt.get('margin_score',0)}")

    # ── Step 6 综合裁决 ──────────────────────────────────────────────
    lines.append(f"\n  Step 6  ⚖️ 综合裁决")
    lines.append(f"  {HR}")

    if verdict:
        lines.append(f"  评分 {verdict.score:.0f}/100  置信度 {verdict.confidence:.0%}  "
                     f"{REC_EMOJI.get(verdict.recommendation,'')} {REC_LABEL.get(verdict.recommendation, verdict.recommendation)}")

        # 评分构成分解
        dc = getattr(verdict, "dimension_contributions", None)
        if dc and isinstance(dc, dict) and dc:
            dim_order = ["基本面", "估值", "技术面", "宏观", "周期", "行业", "情绪", "高管"]
            row1 = "  ".join(f"{k} {dc.get(k,0):.1f}" for k in dim_order[:4])
            row2 = "  ".join(f"{k} {dc.get(k,0):.1f}" for k in dim_order[4:])
            lines.append(f"\n  评分构成:")
            lines.append(f"    {row1}")
            if row2.strip():
                lines.append(f"    {row2}")

        # Alpha Lens
        if verdict.alpha_rationale:
            lines.append(f"\n  📈 Alpha Lens: {verdict.alpha_rationale}")
        if verdict.alpha_multiplier != 1.0:
            lines.append(f"  📐 Alpha乘数 {verdict.alpha_multiplier:.2f}x")

        # 风险分级展示
        if verdict.risks:
            severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
            severity_label = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}
            lines.append(f"\n  风险 ({len(verdict.risks)}):")
            for r in verdict.risks[:8]:
                if isinstance(r, dict):
                    icon = severity_icon.get(r.get("severity", ""), "⚪")
                    sev = severity_label.get(r.get("severity", ""), "")
                    lines.append(f"    {icon} {sev}: {r['text']}")
                else:
                    lines.append(f"    · {r}")

        # 可证伪条件
        if verdict.falsifiable:
            lines.append(f"\n  🔬 可证伪条件 (建议失效触发点):")
            for f in verdict.falsifiable:
                lines.append(f"    · {f}")

        # 下一步行动建议
        next_steps_default = {
            "BUY": "可以开始建仓，分3批入场，每批间隔2-3%跌幅。入场后设置5%止损",
            "ADD": "现有仓位可小幅加仓，不宜超过目标仓位的60%。盈利后立即上移止损",
            "HOLD": "继续持有，密切关注止损线。同时关注矛盾维度的演化方向",
            "REDUCE": "建议分批减仓，每次反弹减1/3。跌破止损线无条件清仓",
            "SELL": "尽快清仓，优先卖出亏损仓位。保住本金是第一要务",
            "CLOSE": "触发硬性风控，立即执行清仓。复盘后再考虑是否重新入场",
        }
        rec = verdict.recommendation
        lines.append(f"\n  🎯 下一步: {next_steps_default.get(rec, '按正常策略执行')}")

    # ── Step 7 仓位调度 ──────────────────────────────────────────────
    lines.append(f"\n  Step 7  💰 仓位调度")
    lines.append(f"  {HR}")

    pls = result.position_limits_summary
    if pls:
        lines.append(f"  本金{pls.get('total_capital',0)/1e4:.0f}万  "
                     f"单票≤{pls.get('max_single_pct',0):.0%}  行业≤{pls.get('max_sector_pct',0):.0%}  "
                     f"总仓位≤{pls.get('max_total_exposure',0):.0%}")

    if result.signal:
        s = result.signal
        sd = result.sizing_detail
        lines.append(f"  {REC_EMOJI.get(s.action,'')} {REC_LABEL.get(s.action, s.action)}  目标仓位 {s.target_weight:.1%}")
        if sd:
            m = CN.get(sd.get("method", ""), sd.get("method", ""))
            lines.append(f"  方法:{m}  上限:{sd.get('macro_cap',0):.0%}×{sd.get('risk_multiplier',1.0):.2f}")
            if sd.get("params_source"):
                lines.append(f"  📋 {sd['params_source']}")

    # ── Step 8 风控执行 ──────────────────────────────────────────────
    lines.append(f"\n  Step 8  🛡️ 风控执行")
    lines.append(f"  {HR}")

    if result.risk:
        r = result.risk
        lines.append(f"  {'✅通过' if r.passed else '⚠️不通过'}  调整后仓位 {r.adjusted_weight:.1%}")
        if pls:
            lines.append(f"  止损{pls.get('single_stop_loss_pct',0):.0%}  回撤熔断{pls.get('portfolio_drawdown_pct',0):.0%}")
        if r.violations:
            lines.append(f"  🚫 违规({len(r.violations)}):")
            for v in r.violations[:6]:
                v = _ensure_cn(v)
                if "低流动性" in v:
                    lines.append(f"     ⚠️ {v} → 日成交不足5000万")
                elif "ALPHA" in v:
                    lines.append(f"     ⚠️ {v} → Alpha衰减")
                else:
                    lines.append(f"     ⚠️ {v}")

    # ── Step 9 数据溯源 ──────────────────────────────────────────────
    all_cit: list[SourceCitation] = []
    if report and report.source_citations:
        all_cit = report.source_citations
    if verdict and verdict.source_citations:
        seen = {(c.provider, c.field) for c in all_cit}
        for c in verdict.source_citations:
            if (c.provider, c.field) not in seen:
                all_cit.append(c)

    if all_cit:
        lines.append(f"\n  📊 数据溯源")
        lines.append(f"  {HR}")
        tc = Counter(c.source_tier for c in all_cit)
        nc = Counter(c.nature for c in all_cit)
        lines.append(f"  分级: " + "  ".join(f"{t}:{tc.get(t,0)}" for t in ["T0", "T1", "T2", "T3"]))
        parts = []
        for n in ["fact", "interpretation", "speculation", "data_gap"]:
            cnt = nc.get(n, 0)
            if cnt:
                parts.append(f"{NATURE_ICON.get(n,'?')}{NATURE_LABEL.get(n,n)}:{cnt}")
        lines.append(f"  性质: {'  '.join(parts)}")
        qs = [c.quality_score for c in all_cit if not c.is_data_gap]
        avg = sum(qs) / len(qs) if qs else 0
        lines.append(f"  质量: {avg:.2f}/1.0")
        if nc.get("speculation", 0):
            lines.append(f"  ⚠️ 含{nc['speculation']}处推测数据，仅供参考不参与评分")

    # ── Step 10 T+0 日内时机分析 ──────────────────────────────────
    t0 = getattr(result, "t0_result", None)
    lines.append(f"\n  ⏱️  T+0 日内时机分析")
    lines.append(f"  {HR}")

    if t0 and isinstance(t0, dict):
        has_data = t0.get("ma5", 0) > 0 or t0.get("vwap", 0) > 0

        # 多日趋势上下文
        if t0.get("multi_day_summary"):
            lines.append(f"  📈 {t0['multi_day_summary']}")
        if t0.get("volume_trend"):
            lines.append(f"     量能: {t0['volume_trend']}")
        # 隔夜风险
        if t0.get("overnight_risk"):
            lines.append(f"  🌙 隔夜风险: {t0['overnight_risk']}")
        if t0.get("gap_analysis"):
            lines.append(f"  🔽 缺口分析: {t0['gap_analysis']}")

        # 操作建议
        emoji = T0_EMOJI.get(t0.get("action", ""), "❓")
        text = CN.get(t0.get("action", ""), "未知")
        score_str = f"得分: {t0.get('score', 0)}" if has_data else "得分: N/A (非交易时段，日线数据未拉取)"
        lines.append(f"  {emoji} {text}  {score_str}")

        # 日内细节
        if t0.get("vwap", 0) > 0:
            lines.append(f"  日内: VWAP={t0['vwap']:.2f} 振幅{t0.get('amplitude',0)}% 反弹{t0.get('rebound_from_low',0):+.1f}%")
        if t0.get("ma5", 0) > 0:
            lines.append(f"  日线: MA5={t0['ma5']:.2f} MA10={t0.get('ma10',0):.2f} 支撑={t0.get('support_1',0)}")
        if not has_data:
            lines.append(f"  💡 提示: 当前非交易时段，T+0日内数据不可用。请在 9:30-15:00 盘中运行以获取日内时机分析。")

        # 反弹质量
        if t0.get("rebound_quality"):
            lines.append(f"  {t0['rebound_quality']}")

        # 信号分类展示
        bear_signals = t0.get("signals_bear", [])
        bull_signals = t0.get("signals_bull", [])
        if bear_signals:
            lines.append(f"  🔴 空头信号 ({len(bear_signals)}):")
            for s in bear_signals[:3]:
                lines.append(f"     · {s}")
        if bull_signals:
            lines.append(f"  🟢 多头信号 ({len(bull_signals)}):")
            for s in bull_signals[:2]:
                lines.append(f"     · {s}")

        # 触发条件
        if t0.get("trigger_condition"):
            lines.append(f"  📋 {t0['trigger_condition']}")
    else:
        lines.append(f"  ⚪ 日内数据暂不可用 — 请确保数据源(mootdx/akshare)连接正常，并在交易时段运行")

    # ── 宏观事件分析 ────────────────────────────────────────────
    evt = getattr(result, "macro_event", None)
    if evt and isinstance(evt, dict) and evt.get("summary"):
        lines.append(f"\n  🌍 宏观事件影响")
        lines.append(f"  {HR}")
        lines.append(f"  {evt['summary']}")
        if evt.get("channels"):
            for ch in evt["channels"][:3]:
                d_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "➖"}.get(ch.get("direction",""), "➖")
                lines.append(f"  {d_emoji} {ch.get('channel','')}: {ch.get('description','')[:50]}...")
        if evt.get("strategy", {}).get("action"):
            lines.append(f"  策略: {evt['strategy']['action']}")

    lines.append(f"\n  ⚠️ AI分析结果，不构成投资建议。投资有风险，入市需谨慎。\n")
    return "\n".join(lines)


# ── 多票横向排名 ──


def _safe_get(obj, key: str, default=None):
    """从 OrchestratorResult 或 dict 中安全取值。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_field(report, field: str, default: float = 50.0) -> float:
    """从 DiagnosisReport 或 dict 中获取评分字段。"""
    if report is None:
        return default
    val = report.get(field, default) if isinstance(report, dict) else getattr(report, field, default)
    return val if val is not None else default


def _risk_summary(result) -> str:
    """提取单条结果中最突出的关键风险摘要。"""
    verdict = _safe_get(result, "verdict")
    if verdict:
        v_risks = _safe_get(verdict, "risks", [])
        if v_risks:
            r0 = v_risks[0]
            if isinstance(r0, dict):
                return r0.get("text", "")[:30]
            return str(r0)[:30]
    gaps = _safe_get(result, "data_gaps", [])
    if gaps:
        return gaps[0][:20]
    gt = _safe_get(result, "game_theory_info") or {}
    if _safe_get(gt, "crowding_score", 0) > 60:
        return "拥挤度偏高"
    return "—"


_RANK_EMOJI = {75: "🟢", 60: "🔵", 40: "🟡", 25: "🟠", 0: "🔴"}


def _rank_emoji(score: float) -> str:
    for threshold, emoji in sorted(_RANK_EMOJI.items(), reverse=True):
        if score >= threshold:
            return emoji
    return "⚪"


def format_stock_ranking(results: list) -> str:
    """🏆 多票横向排名

    接受 OrchestratorResult 或 dict 列表，输出比较表格。
    按综合评分降序排列，附排名 emoji 与综合解读。
    """
    if not results:
        return "\n  🏆 多票横向排名\n  ────────────────────────────────────────────\n  (无结果)\n"

    # 标准化为统一 dict
    rows: list[dict] = []
    for r in results:
        symbol = _safe_get(r, "symbol", "?")
        name = _safe_get(r, "name", "?")
        verdict = _safe_get(r, "verdict") or {}
        report = _safe_get(r, "report")

        score = _safe_get(verdict, "score", 50.0) or 50.0
        rec = _safe_get(verdict, "recommendation", "HOLD")

        alpha = _get_field(report, "macro_score", 50.0)
        value = _get_field(report, "value_score", 50.0)
        quality = _get_field(report, "quality_score", 50.0)
        momentum = _get_field(report, "momentum_score", 50.0)

        risk = _risk_summary(r)
        emoji = _rank_emoji(score)

        rows.append(dict(
            symbol=symbol, name=name, score=score, rec=rec,
            emoji=emoji, alpha=alpha, value=value,
            quality=quality, momentum=momentum, risk=risk,
        ))

    # 按评分降序
    rows.sort(key=lambda x: x["score"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    # 表头
    header = (
        "  {:>4}  {:>8}  {:<10}  {:>6}  {:>8}  {:>6}  {:>6}  {:>6}  {:>6}  {:>24}"
    ).format("排名", "代码", "名称", "评分", "裁决", "Alpha", "价值", "质量", "动量", "关键风险")

    sep = "  " + "─" * 98

    lines = ["\n  🏆 多票横向排名", "  " + "═" * 100, header, sep]

    for row in rows:
        rec_label = CN.get(row["rec"], REC_LABEL.get(row["rec"], row["rec"]))
        lines.append(
            "  {:>4}  {}{:>7}  {:<10}  {:>6.0f}  {:>8}  {:>6.0f}  {:>6.0f}  {:>6.0f}  {:>6.0f}  {:>24}".format(
                row["rank"], row["emoji"], row["symbol"], row["name"],
                row["score"], rec_label, row["alpha"], row["value"],
                row["quality"], row["momentum"], row["risk"],
            )
        )

    # 合成摘要
    top = rows[0]
    avg_score = sum(r["score"] for r in rows) / len(rows)
    rec_dist = Counter(r["rec"] for r in rows)
    rec_parts = [f"{REC_EMOJI.get(k, '⚪')} {REC_LABEL.get(k, k)}: {v}"
                 for k, v in sorted(rec_dist.items())]

    lines.append("")
    lines.append("  📋 排名逻辑说明")
    lines.append("  " + "─" * 60)
    lines.append(f"  均值: {avg_score:.0f}/100  |  {'  '.join(rec_parts)}")
    lines.append(f"  🥇 最优: {top['emoji']} {top['name']}({top['symbol']}) "
                 f"评分{top['score']:.0f}  动量{top['momentum']:.0f}")
    lines.append(f"  📈 排名基于综合评分(加权各维度)，"
                 f"仅供参考，不构成投资建议。")
    lines.append("")

    return "\n".join(lines)
