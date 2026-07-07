# -*- coding: utf-8 -*-
r"""详细分析输出格式化器 — 全链路分析结果 → 人类可读的分步报告。

设计参考:
  - ai-gold-miner 的"结论优先→数据透视→作战计划"分区结构
  - guardrails.md 要求的 tier/nature 标注
  - 小白友好: 编号分步 + emoji 导航 + 事实/解释/推测标签

每条分析数据点标注 [tier/nature] 标签:
  - [📊T0/fact]   一手原始数据 (交易所/央行/公告)
  - [📊T1/fact]   权威数据商原始数据 (券商/通达信)
  - [📊T2/fact]   聚合/爬虫原始数据 (腾讯/AKShare)
  - [🧠T2/解释]   基于事实的分析计算/评分
  - [🔮T3/推测]   前瞻/推演/不可验证
  - [⚠️/缺口]     数据缺失
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.routing.orchestrator import OrchestratorResult
    from src.routing.diagnosis import DiagnosisReport
    from src.routing.verdict import Verdict
    from src.data.source_citation import SourceCitation

SEP = "─" * 70
SEP_HALF = "─" * 40
SEP_EQ = "=" * 70

PERSPECTIVE_LABELS = {
    "buffett": "巴菲特", "li_lu": "李录",
    "munger": "芒格", "lynch": "彼得·林奇",
}
PERSPECTIVE_EMOJI = {"buffett": "🏰", "li_lu": "🎓", "munger": "🧠", "lynch": "🔍"}
PERSPECTIVE_TAG = {
    "buffett": "护城河+安全边际+长期持有",
    "li_lu": "管理层文化+能力圈+复利思维",
    "munger": "逆向思维+心理学+避免愚蠢",
    "lynch": "PEG+成长性+草根调研",
}

NATURE_ICON = {"fact": "📊", "interpretation": "🧠", "speculation": "🔮", "data_gap": "⚠️"}
NATURE_LABEL = {"fact": "事实", "interpretation": "解释", "speculation": "推测", "data_gap": "缺口"}


def format_analysis_result(result: OrchestratorResult) -> str:
    """全链路分析 → 分步详细报告。

    流程 (8 步):
      Step 1 🏥 军规审查        — 31条硬规则逐条核查
      Step 2 🚪 准入检查        — ST/次新/流动性/涨跌停
      Step 3 📊 多维诊断        — 宏观/价值/质量/动量/估值/周期/情绪/高管 8维度
      Step 4 🎭 四大师辩论      — 巴菲特/李录/芒格/林奇 多角度审视
      Step 5 🧠 Munger思维模型  — 从232个跨学科模型中匹配最相关的
      Step 6 ⚖️  综合裁决        — 加权评分+置信度+可证伪条件
      Step 7 💰 仓位调度        — 凯利公式/线性回退→目标仓位
      Step 8 🛡️ 风控执行        — 单票上限/止损/回撤/流动性 硬约束
    """
    lines: list[str] = []
    verdict = result.verdict
    report = result.report

    # ═══════════════════════════════════════════════════════════════
    # 报告头部
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append(f"  📊 {result.name}({result.symbol}) 全链路分析报告")
    lines.append(SEP_EQ)

    meta = []
    if result.investor_prefs_applied:
        p = result.investor_prefs_applied
        meta.append(f"风险偏好: {p.get('risk_profile','?')}")
        meta.append(f"投资目标: {p.get('investment_goal','?')}")
        meta.append(f"投资者级别: {p.get('tier','?')}")
    meta.append(f"行情: {'✅双源一致' if result.cross_validated else '⚠️单源'}")
    lines.append("  " + " | ".join(meta))

    # 默认画像提醒
    if result.using_default_profile or getattr(result, "profile_completeness", 50) < 50:
        missing = getattr(result, "profile_missing", [])
        lines.append(f"\n  ⚠️  投资者画像完整度 {getattr(result,'profile_completeness',0)}% — "
                     f"运行 python -m src.cli preference setup 设置专属画像")
        if missing:
            lines.append(f"      还缺少: {', '.join(missing[:5])}")

    # ═══════════════════════════════════════════════════════════════
    # 📌 核心结论 (先回答"能不能买/卖")
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  📌 核心结论")
    lines.append(SEP_EQ)

    enforced = result.enforced_verdict
    if verdict and enforced:
        rec_map = {"BUY": "🟢 建议买入", "ADD": "🔵 可加仓", "HOLD": "🟡 继续持有",
                   "REDUCE": "🟠 建议减仓", "SELL": "🔴 建议卖出", "CLOSE": "🔴 建议清仓"}
        explain = {
            "BUY": "综合评分≥75，多维度支持建仓",
            "ADD": "综合评分60-74，可在现有仓位基础上小幅加仓",
            "HOLD": "综合评分40-59，信号混杂或估值合理，观望为宜",
            "REDUCE": "综合评分25-39，风险大于机会，建议降低仓位",
            "SELL": "综合评分<25，多重风险叠加，建议清仓",
            "CLOSE": "综合评分<25 或触发硬性风控，建议清仓离场",
        }
        lines.append(f"  {rec_map.get(verdict.recommendation, '⚪')}")
        lines.append(f"  综合评分: {verdict.score}/100  置信度: {verdict.confidence:.0%}")
        lines.append(f"  解读: {explain.get(verdict.recommendation, '')}")
        lines.append(f"  💡 {enforced.get('one_line_conclusion', '')}")
        pr = enforced.get("price_range", {})
        if pr:
            lines.append(f"\n  💰 参考价格区间 [🔮推测]:")
            lines.append(f"    当前价 {pr.get('current_price')}  "
                         f"| 买入≤{pr.get('buy_below')}  "
                         f"| 目标 {pr.get('buy_target')}  "
                         f"| 卖出≥{pr.get('sell_above')}")
    elif verdict:
        e = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴", "CLOSE": "🔴"}
        lines.append(f"  {e.get(verdict.recommendation,'⚪')} {verdict.recommendation} "
                     f"— 评分:{verdict.score}/100 置信度:{verdict.confidence:.0%}")

    # ═══════════════════════════════════════════════════════════════
    # Step 1 🏥 军规审查
    # ═══════════════════════════════════════════════════════════════
    doctrine = result.doctrine_result
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 1 🏥 军规审查 — 31条硬规则逐条核查")
    lines.append(SEP_EQ)

    if doctrine and doctrine.get("rules"):
        rules = doctrine["rules"]
        total = doctrine.get("total", len(rules))
        blocked_c = doctrine.get("blocked_count", 0)
        warn_c = doctrine.get("warn_count", 0)
        info_c = doctrine.get("info_count", 0)
        passed_c = total - blocked_c - warn_c - info_c

        passed_icon = "✅" if doctrine.get("passed") else "⛔"
        lines.append(f"  {passed_icon} 审查结果: {passed_c}通过 | "
                     f"🔴阻断{blocked_c} | 🟠警告{warn_c} | ℹ️信息{info_c} | 共{total}条")

        # 按类别分组展示
        CATEGORY_LABELS = {
            "position": "💰 仓位与资金管理",
            "selection": "🔍 选股与估值纪律",
            "trading": "📈 买卖纪律",
            "emotion": "🧘 情绪纪律",
            "information": "📰 信息纪律",
            "risk": "🛡️ 风控与止盈止损",
            "review": "📝 复盘与进化",
            "meta": "⚙️ 元风控",
        }
        STATUS_ICON = {"passed": "✅", "warn": "🟠", "blocked": "🔴", "info": "ℹ️"}

        by_category: dict[str, list[dict]] = {}
        for r in rules:
            cat = r.get("category", "other")
            by_category.setdefault(cat, []).append(r)

        for cat_key in ["position", "selection", "trading", "emotion", "information", "risk", "review", "meta"]:
            cat_rules = by_category.get(cat_key, [])
            if not cat_rules:
                continue
            label = CATEGORY_LABELS.get(cat_key, cat_key)
            lines.append(f"\n  {label}")
            for r in cat_rules:
                icon = STATUS_ICON.get(r["status"], "❓")
                sev = r["severity"].upper()
                lines.append(f"    {icon} [{r['id']}] {r['name']:12s} [{sev}] {r['description']}")
    elif doctrine:
        # 旧版兼容
        b = doctrine.get("blocked", [])
        w = doctrine.get("warnings", [])
        inf = doctrine.get("infos", [])
        lines.append(f"  审查: {'❌ 被拦截' if b else '✅ 通过'}  "
                     f"| 阻断 {len(b)} | 警告 {len(w)} | 信息 {len(inf)}")
        for r in b:
            lines.append(f"    🔴 [{r['id']}] {r['name']} — {r['description'][:120]}")
        for r in w[:5]:
            lines.append(f"    🟠 [{r['id']}] {r['name']} — {r['description'][:120]}")
    else:
        lines.append("  ⚠️ 军规审查数据不可用")

    # ═══════════════════════════════════════════════════════════════
    # Step 2 🚪 准入检查 (原 L0 Gate)
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 2 🚪 准入检查 — 硬性过滤规则")
    lines.append(SEP_EQ)

    gate_status = result.gate_status or "UNKNOWN"
    gate_emoji = {"ACCEPTED": "✅", "REJECTED": "⛔", "FLAGGED": "⚠️"}.get(gate_status, "❓")
    gate_label = {"ACCEPTED": "通过", "REJECTED": "被拦截", "FLAGGED": "标记风险"}.get(gate_status, gate_status)
    gate_rules = "ST/*ST排除 | 次新股<60天排除 | 日成交<5000万排除 | 涨跌停排除 | 停牌排除"
    lines.append(f"  {gate_emoji} {gate_label} — 检查项: {gate_rules}")

    if result.data_gaps:
        lines.append(f"  📭 数据缺口: {', '.join(result.data_gaps)}")
    if result.red_lines:
        lines.append(f"  🚨 红线: {', '.join(result.red_lines)}")

    # ═══════════════════════════════════════════════════════════════
    # Step 3 📊 多维诊断 (原 L1 Analyze)
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 3 📊 多维诊断 — 8维度综合扫描")
    lines.append(SEP_EQ)

    if report:
        # 👤 投资者画像匹配 (内嵌在诊断中)
        lines.append("  👤 投资者画像匹配")
        if result.investor_prefs_applied:
            p = result.investor_prefs_applied
            lines.append(f"    风险画像: {p.get('risk_profile','?')}  "
                         f"目标: {p.get('investment_goal','?')}  "
                         f"乘数: {p.get('risk_multiplier',1.0):.2f}x")
        if result.mental_model_info:
            mm = result.mental_model_info
            fit_icon = "✅" if mm.get("fit_score",0)>=60 else ("⚠️" if mm.get("fit_score",0)>=40 else "❌")
            lines.append(f"    匹配度: {fit_icon} {mm.get('fit_score',0)}/100")
            comp = mm.get("competence_match","unknown")
            comp_label = {"in_circle":"✅能力圈内","edge":"⚠️能力圈边缘","out_of_circle":"❌能力圈外"}.get(comp,comp)
            lines.append(f"    能力圈: {comp_label}")
            for b in mm.get("bias_flags",[])[:3]:
                lines.append(f"    ⚠️ {b}")
            for w in mm.get("warnings",[])[:3]:
                lines.append(f"    📋 {w}")

        # 8 维度评分面板
        lines.append(f"\n  📊 八维评分")
        lines.append(format_l1_score_panel(report))

        # 多空双视角
        if report.bull_case:
            lines.append(f"  🟢 看多 [🔮推测]: {report.bull_case}")
        if report.bear_case:
            lines.append(f"  🔴 看空 [🔮推测]: {report.bear_case}")

        # 供应链瓶颈
        if report.bottleneck_analysis is not None:
            ba = report.bottleneck_analysis
            lines.append(f"\n  🏭 供应链瓶颈 [🧠解释]: {ba.core_business}")
            lines.append(f"    定位: {ba.supply_chain_layer} | 瓶颈类型: {ba.bottleneck_type} | 评分: {ba.bottleneck_score}/100")
        if report.bottlenecks:
            for b in report.bottlenecks:
                lines.append(f"    ⚡ {b}")
        if report.upstream_risks:
            for r in report.upstream_risks:
                lines.append(f"    ⛓️ {r}")

        # 三情景估值
        sv = result.scenario_valuation
        if sv:
            lines.append(f"\n  📐 三情景估值 [🔮推测]")
            lines.append(f"    方法: {sv.get('method','?')}")
            inp = sv.get("inputs", {})
            inp_parts = [f"{k}={v}" for k,v in inp.items() if v is not None]
            if inp_parts:
                lines.append(f"    参数 [📊fact]: {', '.join(inp_parts)}")
            lines.append(f"    公式: {sv.get('bull_formula','')} / {sv.get('bear_formula','')}")
            lines.append(f"    🟢 乐观 {sv.get('bull_target')}  "
                         f"🟡 基准 {sv.get('base_target')}  "
                         f"🔴 悲观 {sv.get('bear_target')}")
            u = sv.get("implied_upside",0) or 0
            d = sv.get("implied_downside",0) or 0
            rr = "有利" if u > abs(d)*2 else ("较有利" if u > abs(d) else "一般")
            lines.append(f"    上涨 {u:+.1f}% / 下跌 {d:+.1f}% / 风险收益比: {rr}")
    else:
        lines.append("  ⚠️ 多维诊断数据不可用")

    # ═══════════════════════════════════════════════════════════════
    # Step 4 🎭 四大师辩论
    # ═══════════════════════════════════════════════════════════════
    perspectives = result.debate_perspectives
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 4 🎭 四大师视角辩论 — 多角度审视同一标的")
    lines.append(SEP_EQ)

    if perspectives and result.debate_result:
        dr = result.debate_result
        agree_map = {"consensus": "✅一致", "divided": "⚠️分歧", "polarized": "🔴严重对立"}
        lines.append(f"  综合均分: {dr.get('avg_score',0):.2f}/5  "
                     f"分歧度: {dr.get('score_range',0):.2f}  "
                     f"{agree_map.get(dr.get('agreement_level',''), dr.get('agreement_level',''))}")
        if dr.get("top_agreement"):
            lines.append(f"  ✅ 共识: {dr.get('top_agreement')}")
        if dr.get("top_disagreement"):
            lines.append(f"  ⚡ 最大分歧: {dr.get('top_disagreement')}")

        for key in ["buffett", "li_lu", "munger", "lynch"]:
            p = perspectives.get(key)
            if not p:
                continue
            icon = {"买入":"🟢","观望":"🟡","回避":"🔴"}.get(p.get("verdict",""),"⚪")
            lines.append(f"\n    {PERSPECTIVE_EMOJI[key]} {PERSPECTIVE_LABELS[key]} "
                         f"({PERSPECTIVE_TAG[key]})")
            lines.append(f"       {'⭐'*max(1,int(p.get('score',0)))} {p.get('score',0):.1f}/5  "
                         f"{icon} {p.get('verdict','')}  (信心{p.get('confidence',0):.0%})")
            if p.get("one_line_thesis"):
                lines.append(f"       💡 {p['one_line_thesis']}")
            if p.get("key_concern"):
                lines.append(f"       ⚠️  {p['key_concern']}")
            for ev in p.get("evidence", [])[:2]:
                lines.append(f"       📋 {ev}")
            if p.get("unique_insight"):
                lines.append(f"       🔍 {p['unique_insight']}")
    elif result.debate_result:
        dr = result.debate_result
        lines.append(f"  均分: {dr.get('avg_score',0):.2f}/5  分歧: {dr.get('score_range',0):.2f}")
        if dr.get("recommendation"):
            lines.append(f"  {dr['recommendation']}")

    # ═══════════════════════════════════════════════════════════════
    # Step 5 🧠 Munger 思维模型匹配 — 从232个模型中匹配最相关的
    # ═══════════════════════════════════════════════════════════════
    mm_models = result.mental_models
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 5 🧠 Munger 思维模型匹配 — 多学科交叉验证")
    lines.append(SEP_EQ)

    if mm_models:
        lines.append(f"  从 232 个跨学���模型中匹配到 {len(mm_models)} 个相关模型:")
        by_disc: dict[str, list[dict]] = {}
        for m in mm_models:
            d = m.get("discipline", "其他")
            by_disc.setdefault(d, []).append(m)
        for disc, models in by_disc.items():
            lines.append(f"\n  📚 {disc} ({len(models)}):")
            for m in models:
                desc = m.get("description", "")
                reason = m.get("reason_for_match", "")
                lines.append(f"    🧩 {m['name_cn']}")
                if desc:
                    lines.append(f"       {desc[:120]}")
                lines.append(f"       💡 匹配原因: {reason}")
    else:
        lines.append("  ⚠️ 思维模型数据不可用")

    # ── 📈 Alpha Lens + 🎲 博弈论 (紧凑附注) ─────────────────────────
    alpha = result.alpha_profile
    gt = result.game_theory_info
    if alpha is not None or gt:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🔬 辅助指标")
        lines.append(SEP_HALF)
    if alpha is not None:
        lines.append(f"  📈 Alpha: {alpha.alpha_score:.0f}/100  "
                     f"一手性:{alpha.source.originality_score:.0f}/100  "
                     f"叙事:{alpha.narrative.stage.value}  "
                     f"提示:{alpha.narrative.action_hint}")
    if gt:
        lines.append(f"  🎲 博弈论: {gt.get('score',0)}/100  "
                     f"主导:{gt.get('dominant_player','?')}  "
                     f"拥挤:{gt.get('crowding_score',0)}")
        for r in gt.get("risks", [])[:2]:
            lines.append(f"     ⚠️ {r}")

    # ═══════════════════════════════════════════════════════════════
    # Step 5 ⚖️ 综合裁决 (原 L2 Judge)
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 6 ⚖️  综合裁决 — 加权评分+风险+可证伪条件")
    lines.append(SEP_EQ)

    if verdict:
        lines.append(f"  评分: {verdict.score}/100  置信度: {verdict.confidence:.0%}  "
                     f"建议: {verdict.recommendation}")
        if verdict.alpha_rationale:
            lines.append(f"  💡 Alpha: {verdict.alpha_rationale[:180]}")
        if verdict.consensus_challenge:
            lines.append(f"  🔍 反共识: {verdict.consensus_challenge}")
        if verdict.alpha_multiplier != 1.0:
            e = "放大" if verdict.alpha_multiplier > 1.0 else "缩小"
            lines.append(f"  📐 Alpha乘数: {verdict.alpha_multiplier:.2f}x ({e})")

        # 主题调整
        ta = verdict.topic_adjustments
        if ta:
            for k, label in [("emerging_topics","🌱新兴"), ("crowded_topics","⚠️拥挤"), ("fading_topics","📉消退")]:
                if ta.get(k):
                    lines.append(f"  {label}: {', '.join(ta[k])}")

        # 风险列表
        if verdict.risks:
            lines.append(f"\n  ⚠️ 风险 ({len(verdict.risks)}):")
            for r in verdict.risks[:8]:
                lines.append(f"     • {r}")
            if len(verdict.risks) > 8:
                lines.append(f"     ... 还有 {len(verdict.risks)-8} 条")

        # 可证伪条件
        if verdict.falsifiable:
            lines.append(f"\n  🔬 可证伪条件 (触发任一条则建议失效):")
            for f in verdict.falsifiable:
                lines.append(f"     • {f}")
    else:
        lines.append("  ⚠️ 综合裁决数据不可用")

    # ═══════════════════════════════════════════════════════════════
    # Step 6 💰 仓位调度 (原 L3 Trade)
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 7 💰 仓位调度 — 信号→目标仓位")
    lines.append(SEP_EQ)

    pls = result.position_limits_summary
    if pls:
        lines.append(f"  📋 仓位约束: 本金{pls.get('total_capital',0)/1e4:.0f}万  "
                     f"单票≤{pls.get('max_single_pct',0):.0%}  行业≤{pls.get('max_sector_pct',0):.0%}  "
                     f"总仓位≤{pls.get('max_total_exposure',0):.0%}")

    if result.signal:
        s = result.signal
        sd = result.sizing_detail
        a_emoji = {"OPEN":"🟢","ADD":"🔵","HOLD":"🟡","REDUCE":"🟠","CLOSE":"🔴"}.get(s.action,"⚪")
        lines.append(f"\n  🎯 {a_emoji} {s.action} | 目标仓位: {s.target_weight:.1%}")

        if sd:
            m = {"kelly":"凯利公式(统计显著)","linear_fallback":"线性回退(样本不足)",
                 "negative_expectation":"负期望值(不下注)"}.get(sd.get("method",""),sd.get("method",""))
            lines.append(f"  方法: {m}")
            lines.append(f"  宏观上限: {sd.get('macro_cap',0):.0%} × 风险乘数: {sd.get('risk_multiplier',1.0):.2f}")
            if sd.get("kelly_f", 0) > 0:
                lines.append(f"  凯利 f*: {sd['kelly_f']:.1%} × {pls.get('kelly_fraction',0.5) if pls else 0.5:.0%} = "
                             f"{sd['kelly_f']*(pls.get('kelly_fraction',0.5) if pls else 0.5):.1%}")
            if sd.get("params_source"):
                lines.append(f"  📋 {sd['params_source']}")
    else:
        lines.append("  ⚠️ 仓位调度数据不可用")

    # ═══════════════════════════════════════════════════════════════
    # Step 7 🛡️ 风控执行 (原 L4 Risk)
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"\n{SEP_EQ}")
    lines.append("  Step 8 🛡️ 风控执行 — 硬约束裁剪")
    lines.append(SEP_EQ)

    if result.risk:
        r = result.risk
        lines.append(f"  风控: {'✅通过' if r.passed else '⚠️不通过'}  "
                     f"| 调整后仓位: {r.adjusted_weight:.1%}")
        if pls:
            lines.append(f"  约束: 单票≤{pls.get('max_single_pct',0):.0%}  "
                         f"行业≤{pls.get('max_sector_pct',0):.0%}  "
                         f"止损{pls.get('single_stop_loss_pct',0):.0%}  "
                         f"回撤熔断{pls.get('portfolio_drawdown_pct',0):.0%}")
        if r.violations:
            lines.append(f"\n  🚫 违规 ({len(r.violations)}):")
            for v in r.violations[:8]:
                if "低流动性" in v:
                    lines.append(f"     ⚠️ {v} → 日成交不足5000万，大单难成交")
                elif "ALPHA" in v:
                    lines.append(f"     ⚠️ {v} → Alpha衰减/失效，建议降仓")
                elif "止损" in v or "回撤" in v:
                    lines.append(f"     🚫 {v} → 触发硬约束，仓位强制调整")
                else:
                    lines.append(f"     ⚠️ {v}")
    else:
        lines.append("  ⚠️ 风控执行数据不可用")

    # ═══════════════════════════════════════════════════════════════
    # 📊 数据溯源总览
    # ═══════════════════════════════════════════════════════════════
    all_citations: list[SourceCitation] = []
    if report is not None and report.source_citations:
        all_citations = report.source_citations
    if verdict is not None and verdict.source_citations:
        existing = {(sc.provider, sc.field) for sc in all_citations}
        for sc in verdict.source_citations:
            if (sc.provider, sc.field) not in existing:
                all_citations.append(sc)

    if all_citations:
        lines.append(f"\n{SEP_EQ}")
        lines.append(format_citations_summary(all_citations))

    lines.append(f"\n{SEP_EQ}")
    lines.append("  ⚠️ 以上为AI分析结果，不构成投资建议。投资有风险，入市需谨慎。")
    lines.append(SEP_EQ)
    return "\n".join(lines)


# ── 组件格式化 ──────────────────────────────────────────────────────────────

def format_nature_tag(tier: str, nature: str) -> str:
    icon = NATURE_ICON.get(nature, "❓")
    label = NATURE_LABEL.get(nature, nature)
    return f"[{icon}{tier}/{label}]"


def format_citations_summary(citations: list[SourceCitation]) -> str:
    lines = ["  📊 数据溯源", SEP]
    tc = Counter(sc.source_tier for sc in citations)
    lines.append(f"  信源分级: " + "  ".join(f"{t}:{tc.get(t,0)}" for t in ["T0","T1","T2","T3"] if tc.get(t,0)))
    nc = Counter(sc.nature for sc in citations)
    parts = []
    for n in ["fact","interpretation","speculation","data_gap"]:
        c = nc.get(n, 0)
        if c:
            parts.append(f"{NATURE_ICON.get(n,'?')}{NATURE_LABEL.get(n,n)}:{c}")
    lines.append(f"  数据性质: {'  '.join(parts)}")
    qs = [sc.quality_score for sc in citations if not sc.is_data_gap]
    avg = sum(qs)/len(qs) if qs else 0
    qe = "✅" if avg>=0.7 else ("⚠️" if avg>=0.5 else "❌")
    lines.append(f"  综合质量: {qe} {avg:.2f}/1.0")
    sc = nc.get("speculation", 0)
    if sc:
        lines.append(f"  ⚠️ 含{sc}处推测数据[🔮]，不参与评分，仅供参考")
    gc = [sc for sc in citations if sc.is_data_gap]
    if gc:
        for g in gc:
            lines.append(f"  ⚠️ 缺口: {g.provider}:{g.field} — {g.url_or_endpoint}")
    return "\n".join(lines)


def format_l1_score_panel(report: DiagnosisReport | None) -> str:
    if report is None:
        return "    ⚠️ 不可用"
    lines = []
    def _bar(s: float, w: int = 25) -> str:
        f = int(min(s, 100) / 100 * w)
        return "█" * f + "░" * (w - f)
    rows = [
        ("宏观环境", report.macro_score, "解释"),
        ("价值因子", report.value_score, "解释"),
        ("质量因子", report.quality_score, "解释"),
        ("动量因子", report.momentum_score, "事实"),
        ("盈利修正", report.earnings_revision_score, "解释"),
        ("估值综合", report.valuation_score, "解释"),
        ("周期适配", report.cycle_score, "解释"),
        ("高管因子", report.executive_score, "解释"),
    ]
    for label, score, nature in rows:
        lines.append(f"    {label:8s} {score:5.0f}/100 {_bar(score)} [🧠{nature}]" if nature == "解释" else f"    {label:8s} {score:5.0f}/100 {_bar(score)} [📊{nature}]")
    s_map = {"PANIC":"😱恐慌","EXTREME":"🥶极度恐慌","NORMAL":"😐正常","GREED":"😈贪婪"}
    lines.append(f"    情绪信号: {s_map.get(report.sentiment_signal, report.sentiment_signal)} [📊事实]")
    if report.executive_risks:
        for r in report.executive_risks[:2]:
            lines.append(f"    ⚠️ 高管风险: {r}")
    lines.append(f"    置信度: {report.confidence:.0%} | 数据时间: {report.data_freshness.strftime('%Y-%m-%d %H:%M')}")
    if report.cycle_phase:
        lines.append(f"    经济周期: {report.cycle_phase} (适配度:{report.cycle_score:.0f}/100)")
    return "\n".join(lines)


def format_l2_verdict_detail(verdict: Verdict) -> str:
    """保留供外部调用，format_analysis_result 已内联裁决详情。"""
    lines = []
    if verdict.alpha_rationale:
        lines.append(f"    💡 Alpha: {verdict.alpha_rationale[:200]}")
    if verdict.consensus_challenge:
        lines.append(f"    🔍 反共识: {verdict.consensus_challenge}")
    if verdict.risks:
        lines.append(f"\n    ⚠️ 风险 ({len(verdict.risks)}):")
        for r in verdict.risks[:10]:
            lines.append(f"       • {r}")
    if verdict.falsifiable:
        lines.append(f"\n    🔬 可证伪条件:")
        for f in verdict.falsifiable:
            lines.append(f"       • {f}")
    return "\n".join(lines)
