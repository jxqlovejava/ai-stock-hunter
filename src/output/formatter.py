# -*- coding: utf-8 -*-
r"""详细分析输出格式化器"""

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

    # ── Step 2 准入检查 ──────────────────────────────────────────────
    gs = result.gate_status or "UNKNOWN"
    ge = {"ACCEPTED": "✅", "REJECTED": "⛔", "FLAGGED": "⚠️"}.get(gs, "❓")
    gl = {"ACCEPTED": "通过", "REJECTED": "被拦截", "FLAGGED": "标记风险"}.get(gs, gs)
    lines.append(f"\n  Step 2  🚪 准入检查")
    lines.append(f"  {HR}")
    lines.append(f"  {ge} {gl} — ST排除 | 次新60天 | 日成交≥5000万 | 涨跌停 | 停牌")
    if result.data_gaps:
        lines.append(f"  📭 {', '.join(result.data_gaps)}")
    if result.red_lines:
        lines.append(f"  🚨 {', '.join(result.red_lines)}")

    # ── Step 3 多维诊断 ──────────────────────────────────────────────
    lines.append(f"\n  Step 3  📊 多维诊断")
    lines.append(f"  {HR}")

    if report:
        # 画像
        mm = result.mental_model_info
        if mm:
            fi = "✅" if mm.get("fit_score", 0) >= 60 else ("⚠️" if mm.get("fit_score", 0) >= 40 else "❌")
            comp = mm.get("competence_match", "")
            cl = {"in_circle": "✅ 能力圈内", "edge": "⚠️ 边缘", "out_of_circle": "❌ 能力圈外"}.get(comp, comp)
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
        se = {"PANIC": "😱恐慌", "EXTREME": "🥶极度恐慌", "NORMAL": "😐正常", "GREED": "😈贪婪"}
        for label, score in rows:
            bar = "▓" * int(score / 5) + "░" * (20 - int(score / 5))
            lines.append(f"  {label:6s} {score:5.0f} {bar} [🧠解释]")
        lines.append(f"  情绪     {se.get(report.sentiment_signal, report.sentiment_signal)} [📊事实]")

        if report.executive_risks:
            for r in report.executive_risks[:2]:
                lines.append(f"  ⚠️ 高管风险: {r}")
        lines.append(f"  置信度 {report.confidence:.0%}  数据 {report.data_freshness.strftime('%m-%d %H:%M')}")
        if report.cycle_phase:
            lines.append(f"  周期 {report.cycle_phase}  适配 {report.cycle_score:.0f}/100")

        # 多空
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
        am = {"consensus": "✅一致", "divided": "⚠️分歧", "polarized": "🔴对立"}
        lines.append(f"  均分 {dr.get('avg_score',0):.2f}/5  分歧 {dr.get('score_range',0):.2f}  "
                     f"{am.get(dr.get('agreement_level',''),'')}")
        if dr.get("top_disagreement"):
            lines.append(f"  ⚡ {dr.get('top_disagreement')}")

        for key in ["buffett", "li_lu", "munger", "lynch"]:
            p = pp.get(key)
            if not p:
                continue
            score = p.get("score", 0)
            stars = "★" * max(1, int(score)) + "☆" * max(0, 5 - int(score))
            vi = {"买入": "🟢", "观望": "🟡", "回避": "🔴"}.get(p.get("verdict", ""), "⚪")

            lines.append(f"\n  {PERSPECTIVE_EMOJI[key]} {PERSPECTIVE_NAME[key]} "
                         f"({PERSPECTIVE_TAG[key]})")
            lines.append(f"  {stars} {score:.1f}/5  {vi} {p.get('verdict','')}")
            if p.get("methodology"):
                lines.append(f"  📐 {p['methodology'][:130]}")
            if p.get("one_line_thesis"):
                lines.append(f"  💡 {p['one_line_thesis']}")
            for b in p.get("bull_points", [])[:2]:
                lines.append(f"  🟢 {b}")
            for b in p.get("bear_points", [])[:2]:
                lines.append(f"  🔴 {b}")
            if p.get("key_concern"):
                lines.append(f"  ⚠️ {p['key_concern']}")

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
                    lines.append(f"    {desc[:140]}")
                lines.append(f"    → {reason}")

    # ── 辅助指标 ─────────────────────────────────────────────────────
    alpha = result.alpha_profile
    gt = result.game_theory_info
    if alpha or gt:
        lines.append(f"\n  🔬 辅助指标")
        lines.append(f"  {HR}")
    if alpha:
        lines.append(f"  📈 Alpha {alpha.alpha_score:.0f}/100  "
                     f"一手性{alpha.source.originality_score:.0f}/100  叙事{alpha.narrative.stage.value}")
        if alpha.summary:
            lines.append(f"  💡 {alpha.summary}")
    if gt:
        lines.append(f"  🎲 博弈论 {gt.get('score',0)}/100  主导{gt.get('dominant_player','?')}  "
                     f"拥挤{gt.get('crowding_score',0)}  杠杆{gt.get('margin_score',0)}")

    # ── Step 6 综合裁决 ──────────────────────────────────────────────
    lines.append(f"\n  Step 6  ⚖️ 综合裁决")
    lines.append(f"  {HR}")

    if verdict:
        lines.append(f"  评分 {verdict.score}/100  置信度 {verdict.confidence:.0%}  "
                     f"{REC_EMOJI.get(verdict.recommendation,'')} {verdict.recommendation}")
        if verdict.alpha_rationale:
            lines.append(f"  💡 {verdict.alpha_rationale[:160]}")
        if verdict.alpha_multiplier != 1.0:
            lines.append(f"  📐 Alpha乘数 {verdict.alpha_multiplier:.2f}x")
        if verdict.risks:
            lines.append(f"  ⚠️ 风险({len(verdict.risks)}):")
            for r in verdict.risks[:6]:
                lines.append(f"     · {r}")
        if verdict.falsifiable:
            lines.append(f"  🔬 可证伪条件:")
            for f in verdict.falsifiable:
                lines.append(f"     · {f}")

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
        lines.append(f"  {REC_EMOJI.get(s.action,'')} {s.action}  目标仓位 {s.target_weight:.1%}")
        if sd:
            m = {"kelly": "凯利公式", "linear_fallback": "线性回退", "negative_expectation": "负期望"}.get(
                sd.get("method", ""), sd.get("method", ""))
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
                if "低流动性" in v:
                    lines.append(f"     ⚠️ {v} → 日成交不足5000万")
                elif "ALPHA" in v:
                    lines.append(f"     ⚠️ {v} → Alpha衰减")
                else:
                    lines.append(f"     ⚠️ {v}")

    # ── 数据溯源 ─────────────────────────────────────────────────────
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

    lines.append(f"\n  ⚠️ AI分析结果，不构成投资建议。投资有风险，入市需谨慎。\n")
    return "\n".join(lines)
