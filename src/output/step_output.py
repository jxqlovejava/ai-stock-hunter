# -*- coding: utf-8 -*-
r"""按步骤输出详细分析结果 — 借鉴 ai-gold-miner 的 print_all_dimensions + _print_* 模式。

每个函数在管道步骤完成后立即调用，将详细结果直接 print 到终端。
format_analysis_result() 可继续用于最终完整输出（不冲突）。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.routing.orchestrator import OrchestratorResult
    from src.routing.diagnosis import DiagnosisReport
    from src.routing.verdict import Verdict
    from src.data.source_citation import SourceCitation

HR = "─" * 60
HR_THICK = "━" * 60

REC_EMOJI = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴", "CLOSE": "🔴"}
REC_LABEL = {"BUY": "建议买入", "ADD": "可加仓", "HOLD": "继续持有", "REDUCE": "建议减仓", "SELL": "建议卖出", "CLOSE": "建议清仓"}

PERSPECTIVE_EMOJI = {"buffett": "🏰", "li_lu": "🎓", "munger": "🧠", "lynch": "🔍"}
PERSPECTIVE_NAME = {"buffett": "巴菲特", "li_lu": "李录", "munger": "芒格", "lynch": "林奇"}
PERSPECTIVE_TAG = {
    "buffett": "护城河+安全边际+长期持有",
    "li_lu": "管理层文化+能力圈+复利思维",
    "munger": "逆向思维+心理学+避免愚蠢",
    "lynch": "PEG+成长性+草根调研",
}

CN = {
    "emerging": "萌芽期", "spreading": "扩散期", "consensus": "共识期",
    "crowded": "拥挤期", "fading": "消退期", "dormant": "休眠期",
    "expansion": "扩张期", "contraction": "收缩期", "trough": "谷底期", "peak": "顶峰期",
    "polarized": "🔴严重对立", "divided": "⚠️存在分歧", "consensus": "高度一致",
    "PANIC": "😱恐慌", "EXTREME": "🥶极度恐慌", "NORMAL": "😐正常", "GREED": "😈贪婪",
    "NEUTRAL": "中性",
    "LOW_BASE": "低位启动", "HIGH_ACCEL": "高位加速",
    "kelly": "凯利公式", "linear_fallback": "线性回退", "negative_expectation": "负期望（不下注）",
    "add": "可以加仓", "hold": "观望等待", "reduce": "建议减仓", "cut": "坚决减仓", "no_position": "不建议建仓",
    "fishing_line": "钓鱼线出货", "lure_bull_dump": "诱多出货",
    "closing_pump": "尾盘拉升", "closing_dump": "尾盘砸盘",
    "wash_trade_pump": "对倒拉升", "shakeout": "洗盘震仓",
    "news_distribution": "消息配合出货",
}
T0_EMOJI = {"add": "🟢", "hold": "🟡", "reduce": "🟠", "cut": "🔴", "no_position": "⚪"}


# ── Step 1: 军规审查 ─────────────────────────────────────────────────

def print_doctrine(doctrine_result: dict | None) -> None:
    """输出军规审查详细结果。"""
    if not doctrine_result or not doctrine_result.get("rules"):
        return

    rules = doctrine_result["rules"]
    bc = doctrine_result.get("blocked_count", 0)
    wc = doctrine_result.get("warn_count", 0)
    ic = doctrine_result.get("info_count", 0)
    ok = "✅" if doctrine_result.get("passed") else "⛔"

    print(f"\n{'='*60}")
    print(f"  🏥 军规审查")
    print(f"{'='*60}")
    print(f"  {ok} {doctrine_result.get('total',31)}条规则: 🔴阻断{bc}  🟠警告{wc}  ℹ️信息{ic}")

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
        print(f"  {CAT_LABEL.get(cat, cat)}")
        for r in cr:
            icon = SI.get(r["status"], "❓")
            print(f"    {icon} [{r['id']}] {r['name']:10s} [{r['severity'].upper():5s}] {r['description']}")

    # 仅输出有问题的规则详情
    problem_rules = [r for r in rules if r.get("status") in ("blocked", "warn")]
    if problem_rules:
        fin_data = doctrine_result.get("financial_data", {})
        print(f"\n  ⚠️ 需关注 ({len(problem_rules)}条):")
        for r in problem_rules:
            detail = r['description']
            rid = r['id']
            # 注入实际财务数据
            if rid == "r032" and fin_data.get("roe_history"):
                roes = fin_data["roe_history"]
                roe_str = " / ".join(f"{v:.1f}%" for v in roes)
                detail = f"{detail} (近3年ROE: {roe_str})"
            elif rid == "r033" and fin_data.get("ocf_np_ratio") is not None:
                ratio = fin_data["ocf_np_ratio"]
                detail = f"{detail} (累计OCF/NP={ratio:.2f})"
            elif rid == "r034" and fin_data.get("dividend_payout_ratio") is not None:
                ratio = fin_data["dividend_payout_ratio"]
                detail = f"{detail} (累计分红/NP={ratio:.1%})"
            elif rid in ("r032", "r033", "r034") and fin_data.get("_financial_data_missing"):
                detail = f"{detail} [DATA_GAP: 财务数据不足]"
            print(f"    [{rid}] {r['name']}: {detail}")


# ── Step 2: 准入检查 & 市场全景 ──────────────────────────────────────

def print_admission(
    gate_status: str,
    market_sentiment: dict | None = None,
    data_gaps: list[str] | None = None,
    red_lines: list[str] | None = None,
) -> None:
    """输出准入检查 + 市场全景。"""
    ge = {"ACCEPTED": "✅", "REJECTED": "⛔", "FLAGGED": "⚠️"}.get(gate_status, "❓")
    gl = {"ACCEPTED": "通过", "REJECTED": "被拦截", "FLAGGED": "标记风险"}.get(gate_status, gate_status)

    print(f"\n{'='*60}")
    print(f"  🚪 准入检查 & 市场全景")
    print(f"{'='*60}")
    print(f"  {ge} {gl} — ST排除 | 次新60天 | 日成交≥5000万 | 涨跌停 | 停牌")
    if data_gaps:
        print(f"  📭 数据缺口: {', '.join(data_gaps)}")
    if red_lines:
        print(f"  🚨 红线: {', '.join(red_lines)}")

    # 市场情绪
    sent = market_sentiment or {}
    sl = sent.get("level", "NORMAL") if isinstance(sent, dict) else "NORMAL"
    print(f"\n  📡 市场情绪: {CN.get(str(sl), str(sl))} (评分 {sent.get('score','?')}/100)")
    if isinstance(sent, dict):
        if sent.get("market_breadth_insight"):
            print(f"  📐 市场宽度: {sent['market_breadth_insight']}")
        if sent.get("volume_insight"):
            print(f"  📊 成交量: {sent['volume_insight']}")
        if sent.get("northbound_insight"):
            print(f"  🧭 北向资金: {sent['northbound_insight']}")
        if sent.get("limit_pool_insight"):
            print(f"  🚦 涨跌停: {sent['limit_pool_insight']}")
        if sent.get("panic_arb_advice"):
            print(f"  🎯 恐慌套利: {sent['panic_arb_advice']}")


# ── Step 3: 多维诊断 ─────────────────────────────────────────────────

def print_diagnosis(report: Any, mental_model_info: dict | None = None) -> None:
    """输出多维诊断 8 维度评分 + 画像匹配 + 瓶颈分析。"""
    if report is None:
        return

    print(f"\n{'='*60}")
    print(f"  📊 多维诊断")
    print(f"{'='*60}")

    # 画像匹配
    mm = mental_model_info or {}
    if mm:
        fi = "✅" if mm.get("fit_score", 0) >= 60 else ("⚠️" if mm.get("fit_score", 0) >= 40 else "❌")
        comp = mm.get("competence_match", "")
        cl = {"in_circle": "✅ 能力圈内", "edge": "⚠️ 边缘", "out_of_circle": "❌ 能力圈外", "not_configured": "⚪ 能力圈未设"}.get(comp, comp)
        print(f"  👤 匹配度 {fi} {mm.get('fit_score',0)}/100  {cl}")
        for b in mm.get("bias_flags", [])[:2]:
            print(f"     ⚠️ {b}")

    # 八维评分 — 进度条风格
    print()
    rows = [
        ("宏观环境", getattr(report, "macro_score", 0)),
        ("价值因子", getattr(report, "value_score", 0)),
        ("质量因子", getattr(report, "quality_score", 0)),
        ("动量因子", getattr(report, "momentum_score", 0)),
        ("盈利修正", getattr(report, "earnings_revision_score", 0)),
        ("估值综合", getattr(report, "valuation_score", 0)),
        ("周期适配", getattr(report, "cycle_score", 0)),
        ("高管因子", getattr(report, "executive_score", 0)),
        ("大宗交易", getattr(report, "block_trade_score", 50)),
    ]
    for label, score in rows:
        bar = "▓" * int(score / 5) + "░" * (20 - int(score / 5))
        nature = "[🧠解释]" if label not in ("宏观环境", "动量因子") else "[📊事实]"
        print(f"  {label:6s} {score:5.0f} {bar} {nature}")
    sentiment = getattr(report, "sentiment_signal", "NORMAL")
    print(f"  情绪     {CN.get(str(sentiment), str(sentiment))} [📊事实]")

    print(f"  置信度 {getattr(report, 'confidence', 0):.0%}  数据 {getattr(report, 'data_freshness', '?')}")

    # 底部结构 A/B 段（大底须走出）
    bottom_phase = getattr(report, "bottom_phase", "") or ""
    if bottom_phase:
        bs_score = getattr(report, "bottom_structure_score", 50.0)
        bs = getattr(report, "bottom_structure", None)
        ab = getattr(bs, "ab_ratio", None) if bs is not None else None
        entry_ok = getattr(report, "bottom_entry_allowed", False)
        phase_cn = {
            "CATCHING_KNIFE": "🔴 接飞刀(B≥A)",
            "TREND_EXHAUSTED": "🟡 顺势衰竭(B<A)",
            "COUNTER_CONFIRMED": "🟡 逆势已确认",
            "LIGHT_LONG_SETUP": "🟢 轻仓试多窗口",
            "NOT_IN_DOWNTREND": "⚪ 非下跌环境",
            "NO_PIVOT": "⚪ 无有效中枢",
            "DATA_INSUFFICIENT": "⚪ 数据不足",
        }.get(bottom_phase, bottom_phase)
        ab_txt = f" B/A={ab:.2f}" if isinstance(ab, (int, float)) and ab > 0 else ""
        entry_txt = " | 允许轻仓试多" if entry_ok else " | 禁止抄底/试多"
        print(f"  📐 底部结构 {phase_cn}{ab_txt}  分{bs_score:.0f}{entry_txt}")
        if bs is not None and getattr(bs, "summary", ""):
            print(f"     {bs.summary}")

    # 诊断综述
    synthesis = getattr(report, "dimension_synthesis", "")
    if synthesis:
        print(f"\n  📝 多维诊断综述")
        for line in str(synthesis).split("\n"):
            print(f"  {line}")

    # 价格数据（事实性数据，非投资论点）
    _daily = getattr(report, "change_pct_1d", 0.0)
    _5day = getattr(report, "change_pct_5d", None)
    _ma_dev = getattr(report, "ma_deviation_pct", 0.0)
    _price_parts = [f"当日{_daily:+.1f}%"]
    if _5day is not None:
        _price_parts.append(f"5日{_5day:+.1f}%")
    _price_parts.append(f"MA60偏离{_ma_dev:+.1f}%")
    print(f"  📊 价格数据: {' | '.join(_price_parts)}")

    # 多空
    bull = getattr(report, "bull_case", "")
    bear = getattr(report, "bear_case", "")
    if bull:
        print(f"  🟢 看多: {bull}")
    if bear:
        print(f"  🔴 看空: {bear}")

    # 高管风险
    exec_risks = getattr(report, "executive_risks", []) or []
    for r in exec_risks[:2]:
        print(f"  ⚠️ 高管风险: {r}")

    # 瓶颈
    ba = getattr(report, "bottleneck_analysis", None)
    if ba:
        _enum_cn = {"MATERIAL": "原材料", "ADJACENT": "相邻行业", "COMPONENT": "零部件",
                    "MANUFACTURING": "制造", "DISTRIBUTION": "分销", "RETAIL": "零售",
                    "CRITICAL": "关键瓶颈", "MODERATE": "中等瓶颈", "MILD": "轻度瓶颈"}
        layer = str(getattr(ba, "supply_chain_layer", "?")).replace("SupplyChainLayer.", "")
        btype = str(getattr(ba, "bottleneck_type", "?")).replace("BottleneckType.", "")
        layer = _enum_cn.get(layer, layer)
        btype = _enum_cn.get(btype, btype)
        print(f"  🏭 供应链: {ba.core_business} | 定位:{layer} 类型:{btype} 评分:{ba.bottleneck_score}/100")


# ── Step 4: 四大师辩论 ───────────────────────────────────────────────

def print_debate(debate_perspectives: dict | None, debate_result: dict | None) -> None:
    """输出四大师辩论详细结果。"""
    pp = debate_perspectives
    dr = debate_result
    if not pp or not dr:
        return

    print(f"\n{'='*60}")
    print(f"  🎭 四大师辩论")
    print(f"{'='*60}")

    print(f"  均分 {dr.get('avg_score',0):.2f}/5  分歧度 {dr.get('score_range',0):.2f}  {CN.get(str(dr.get('agreement_level','')), str(dr.get('agreement_level','?')))}")
    if dr.get("tension_summary"):
        print(f"  📋 综述: {dr['tension_summary']}")
    if dr.get("top_disagreement"):
        print(f"  ⚡ 最大分歧: {dr.get('top_disagreement')}")
    if dr.get("recommendation"):
        print(f"  🎯 综合建议: {dr['recommendation']}")
    print()

    for key in ["buffett", "li_lu", "munger", "lynch"]:
        p = pp.get(key)
        if not p:
            continue
        score = p.get("score", 0)
        stars = "★" * max(1, int(score)) + "☆" * max(0, 5 - int(score))
        vi = {"买入": "🟢", "观望": "🟡", "回避": "🔴"}.get(p.get("verdict", ""), "⚪")

        print(f"  {PERSPECTIVE_EMOJI[key]} {PERSPECTIVE_NAME[key]} ({PERSPECTIVE_TAG[key]})")
        print(f"  {stars} {score:.1f}/5  {vi} {p.get('verdict','')}")
        if p.get("methodology"):
            print(f"  📐 {p['methodology']}")
        if p.get("one_line_thesis"):
            print(f"  💡 {p['one_line_thesis']}")
        if p.get("unique_insight"):
            print(f"  🔬 {p['unique_insight']}")
        for b in p.get("bull_points", [])[:4]:
            print(f"  🟢 {b}")
        for b in p.get("bear_points", [])[:4]:
            print(f"  🔴 {b}")
        if p.get("key_concern"):
            print(f"  ⚠️ {p['key_concern']}")
        # 显示问题+回答（优先使用 qa_pairs）
        qa_pairs = p.get("qa_pairs", [])
        if qa_pairs:
            for qa in qa_pairs[:3]:
                print(f"  ❓ {qa['q']}")
                print(f"  💬 ↳ {qa['a']}")
        else:
            for q in p.get("questions_to_ask", [])[:2]:
                print(f"  ❓ {q}")
        print()


# ── Step 5: Munger 思维模型 ──────────────────────────────────────────

def print_munger_models(mental_models: list | None, stock_name: str = "") -> None:
    """输出 Munger 思维模型匹配结果。"""
    if not mental_models:
        return

    print(f"\n{'='*60}")
    print(f"  🧠 Munger 思维模型")
    print(f"{'='*60}")
    print(f"  从232个模型中匹配{len(mental_models)}个:")

    by_d: dict[str, list] = {}
    for m in mental_models:
        by_d.setdefault(m.get("discipline", "其他"), []).append(m)
    for disc, models in by_d.items():
        print(f"\n  {disc} ({len(models)})")
        for m in models:
            desc = m.get("description", "")
            reason = m.get("reason_for_match", "")
            print(f"  · {m.get('name_cn', '?')}")
            if desc:
                print(f"    {desc}")
            if reason:
                print(f"    → {reason}")
            app = m.get("application_to_stock", "")
            if app:
                print(f"    📌 应用于{stock_name}: {app}")


# ── Step 6: 辅助指标 (Alpha + 博弈论) ─────────────────────────────────

def print_alpha_game_theory(alpha_profile: Any | None, game_theory_info: dict | None) -> None:
    """输出 Alpha Lens + 博弈论辅助指标。"""
    alpha = alpha_profile
    gt = game_theory_info

    has_alpha = alpha is not None and getattr(alpha, "alpha_score", 0) > 0
    has_gt = gt is not None and gt

    if not has_alpha and not has_gt:
        return

    print(f"\n{'='*60}")
    print(f"  🔬 辅助指标 (Alpha + 博弈论)")
    print(f"{'='*60}")

    if has_alpha:
        narrative_stage = getattr(getattr(alpha, "narrative", None), "stage", None)
        stage_str = str(narrative_stage.value) if hasattr(narrative_stage, "value") else str(narrative_stage) if narrative_stage else "?"
        print(f"  📈 Alpha {alpha.alpha_score:.0f}/100  一手性{alpha.source.originality_score:.0f}/100  叙事{CN.get(stage_str, stage_str)}")
        if getattr(alpha, "summary", ""):
            print(f"  💡 {alpha.summary}")

    if has_gt:
        print(f"  🎲 博弈论 {gt.get('score',0)}/100  主导{gt.get('dominant_player','?')}  拥挤{gt.get('crowding_score',0)}  杠杆{gt.get('margin_score',0)}")


# ── Step 7: 综合裁决 ─────────────────────────────────────────────────

def print_verdict(verdict: Any | None, enforced_verdict: dict | None = None, scenario_valuation: dict | None = None) -> None:
    """输出综合裁决 + 情景估值。"""
    if verdict is None:
        return

    print(f"\n{'='*60}")
    print(f"  ⚖️ 综合裁决")
    print(f"{'='*60}")

    rec = getattr(verdict, "recommendation", "HOLD")
    print(f"  评分 {verdict.score:.0f}/100  置信度 {verdict.confidence:.0%}  {REC_EMOJI.get(rec,'⚪')} {REC_LABEL.get(rec, rec)}")

    # 评分构成分解
    dc = getattr(verdict, "dimension_contributions", None)
    if dc and isinstance(dc, dict) and dc:
        dim_order = ["基本面", "估值", "技术面", "宏观", "周期", "行业", "情绪", "高管"]
        row1 = "  ".join(f"{k} {dc.get(k,0):.1f}" for k in dim_order[:4])
        row2 = "  ".join(f"{k} {dc.get(k,0):.1f}" for k in dim_order[4:])
        print(f"\n  评分构成:")
        print(f"    {row1}")
        if row2.strip():
            print(f"    {row2}")

    # Alpha
    if getattr(verdict, "alpha_rationale", ""):
        print(f"\n  📈 Alpha Lens: {verdict.alpha_rationale}")
    if getattr(verdict, "alpha_multiplier", 1.0) != 1.0:
        print(f"  📐 Alpha乘数 {verdict.alpha_multiplier:.2f}x")

    # 风险
    risks = getattr(verdict, "risks", []) or []
    if risks:
        severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        severity_label = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}
        print(f"\n  风险 ({len(risks)}):")
        for r in risks[:8]:
            if isinstance(r, dict):
                icon = severity_icon.get(r.get("severity", ""), "⚪")
                sev = severity_label.get(r.get("severity", ""), "")
                print(f"    {icon} {sev}: {r['text']}")
            else:
                print(f"    · {r}")

    # 可证伪条件
    falsifiable = getattr(verdict, "falsifiable", []) or []
    if falsifiable:
        print(f"\n  🔬 可证伪条件:")
        for f in falsifiable:
            print(f"    · {_ensure_cn(f)}")

    # 强制结论
    if enforced_verdict:
        print(f"\n  💡 {enforced_verdict.get('one_line_conclusion','')}")
        pr = enforced_verdict.get("price_range", {})
        if pr:
            print(f"  当前 {pr.get('current_price')}  买入≤{pr.get('buy_below')}  卖出≥{pr.get('sell_above')}  [🔮推测]")

    # 三情景估值
    sv = scenario_valuation
    if sv:
        print(f"\n  📐 三情景估值 [🔮推测]")
        inp = sv.get("inputs", {})
        inp_s = ", ".join(f"{k}={v}" for k, v in inp.items() if v is not None)
        print(f"  方法:{sv.get('method','?')}  参数:{inp_s}")
        print(f"  🟢{sv.get('bull_target')}  🟡{sv.get('base_target')}  🔴{sv.get('bear_target')}")
        u = sv.get("implied_upside", 0) or 0
        d = sv.get("implied_downside", 0) or 0
        rr = "有利" if u > abs(d) * 2 else ("较有利" if u > abs(d) else "一般")
        print(f"  上涨{u:+.1f}%  下跌{d:+.1f}%  风险收益比:{rr}")


# ── Step 8: 仓位调度 ─────────────────────────────────────────────────

def print_positioning(
    signal: Any | None,
    sizing_detail: dict | None = None,
    position_limits_summary: dict | None = None,
) -> None:
    """输出仓位调度详细结果。"""
    print(f"\n{'='*60}")
    print(f"  💰 仓位调度")
    print(f"{'='*60}")

    pls = position_limits_summary
    if pls:
        cap = pls.get('total_capital', 0)
        if cap == 500000.0 and pls.get('_capital_is_default', True):
            cap_str = "⚠️未设置"
        elif cap >= 1e8:
            cap_str = f"{cap/1e8:.1f}亿"
        else:
            cap_str = f"{cap/1e4:.0f}万"
        print(f"  本金{cap_str}  单票≤{pls.get('max_single_pct',0):.0%}  行业≤{pls.get('max_sector_pct',0):.0%}  总仓位≤{pls.get('max_total_exposure',0):.0%}")

    if signal:
        s = signal
        rec = getattr(s, "action", "HOLD")
        print(f"  {REC_EMOJI.get(rec,'⚪')} {REC_LABEL.get(rec, rec)}  目标仓位 {getattr(s, 'target_weight', 0):.1%}")
        sd = sizing_detail or {}
        if sd:
            m = CN.get(sd.get("method", ""), sd.get("method", ""))
            print(f"  方法:{m}  上限:{sd.get('macro_cap',0):.0%}×{sd.get('risk_multiplier',1.0):.2f}")
            if sd.get("kelly_f"):
                print(f"  Kelly f*={sd['kelly_f']:.3f}")
            if sd.get("params_source"):
                src = str(sd["params_source"])
                src = src.replace("linear:base=", "公式: ")
                src = src.replace("_fallback", "").replace("linear", "线性回退")
                print(f"  📋 {src}")
    else:
        print(f"  ⚪ 无信号生成")


# ── Step 9: 风控执行 ──────────────────────────────────────────────────

def print_risk_control(risk: Any | None, position_limits_summary: dict | None = None) -> None:
    """输出风控执行详细结果。"""
    if risk is None:
        return

    print(f"\n{'='*60}")
    print(f"  🛡️ 风控执行")
    print(f"{'='*60}")

    print(f"  {'✅通过' if getattr(risk, 'passed', False) else '⚠️不通过'}  调整后仓位 {getattr(risk, 'adjusted_weight', 0):.1%}")
    pls = position_limits_summary
    if pls:
        print(f"  止损{pls.get('single_stop_loss_pct',0):.0%}  回撤熔断{pls.get('portfolio_drawdown_pct',0):.0%}")

    violations = getattr(risk, "violations", []) or []
    if violations:
        print(f"  🚫 违规 ({len(violations)}):")
        for v in violations[:6]:
            v = _ensure_cn(str(v))
            if "低流动性" in v:
                print(f"     ⚠️ {v} → 日成交不足5000万")
            elif "ALPHA" in v:
                print(f"     ⚠️ {v} → Alpha衰减")
            else:
                print(f"     ⚠️ {v}")


# ── Step 10: 数据溯源 ─────────────────────────────────────────────────

def print_source_citations(report: Any, verdict: Any = None) -> None:
    """输出数据溯源总览。"""
    all_cit: list = list(getattr(report, "source_citations", []) or [])
    if verdict:
        seen = {(c.provider, c.field) for c in all_cit}
        for c in (getattr(verdict, "source_citations", []) or []):
            if (c.provider, c.field) not in seen:
                all_cit.append(c)

    if not all_cit:
        return

    print(f"\n{'='*60}")
    print(f"  📊 数据溯源")
    print(f"{'='*60}")

    tc = Counter(getattr(c, "source_tier", "?") for c in all_cit)
    nc = Counter(getattr(c, "nature", "?") for c in all_cit)
    print(f"  分级: " + "  ".join(f"{t}:{tc.get(t,0)}" for t in ["T0", "T1", "T2", "T3"]))
    parts = []
    for n in ["fact", "interpretation", "speculation"]:
        cnt = nc.get(n, 0)
        if cnt:
            NATURE_ICON = {"fact": "📊", "interpretation": "🧠", "speculation": "🔮"}
            NATURE_LABEL = {"fact": "事实", "interpretation": "解释", "speculation": "推测"}
            parts.append(f"{NATURE_ICON.get(n,'?')}{NATURE_LABEL.get(n,n)}:{cnt}")
    print(f"  性质: {'  '.join(parts)}")
    qs = [getattr(c, "quality_score", 0) for c in all_cit if not getattr(c, "is_data_gap", False)]
    avg = sum(qs) / len(qs) if qs else 0
    print(f"  质量: {avg:.2f}/1.0")
    if nc.get("speculation", 0):
        print(f"  ⚠️ 含{nc['speculation']}处推测数据，仅供参考不参与评分")


# ── 多通道资讯输出 ────────────────────────────────────────────────────

def print_news_context(nc: dict) -> None:
    """输出多通道资讯上下文。"""
    if not nc or not isinstance(nc, dict):
        return

    total = nc.get("total_items", 0)
    if total == 0:
        print(f"\n  🔔 资讯: 暂无数据")
        return

    print(f"\n{'='*60}")
    print(f"  🔔 多通道资讯 · {nc.get('summary', '')}")
    print(f"{'='*60}")

    # 公告优先显示 (最重要)
    announcements = nc.get("announcements", [])
    if announcements:
        print(f"\n  📋 公告 ({len(announcements)}条)")
        for item in announcements[:5]:
            title = item.get("title", "")[:60]
            date = item.get("date", "")[:10]
            print(f"    · [{date}] {title}")

    # 研报
    reports = nc.get("research_reports", [])
    if reports:
        print(f"\n  📈 研报 ({len(reports)}条)")
        for item in reports[:3]:
            title = item.get("title", "")[:60]
            content = item.get("content", "")[:80]
            print(f"    · {title}")
            if content:
                print(f"      {content}")

    # 个股新闻
    news = nc.get("news", [])
    if news:
        print(f"\n  📰 个股新闻 ({len(news)}条)")
        for item in news[:8]:
            title = item.get("title", "")[:70]
            date = item.get("date", "")[:10]
            source = item.get("source", "")
            print(f"    · [{date}] {title}  ({source})")

    # 7×24 快讯 (经关键词过滤)
    flash = nc.get("flash_24x7", [])
    if flash:
        print(f"\n  ⚡ 7×24 快讯 ({len(flash)}条)")
        for item in flash[:5]:
            title = item.get("title", "")[:70]
            date = item.get("date", "")[:16]
            print(f"    · [{date}] {title}")

    # 最近 30 日
    l30 = nc.get("last30days", [])
    if l30:
        print(f"\n  🗓️ 近30日资讯 ({len(l30)}条)")
        for item in l30[:5]:
            title = item.get("title", "")[:60]
            date = item.get("date", "")[:10]
            print(f"    · [{date}] {title}")

    # 错误
    errors = nc.get("errors", [])
    if errors:
        print(f"\n  ⚠️ 部分通道失败: {', '.join(errors[:3])}")


# ── Step 11: T+0 日内时机分析 ────────────────────────────────────────

def print_t0(t0_result: dict | None) -> None:
    """输出 T+0 日内时机分析。"""
    if not t0_result or not isinstance(t0_result, dict):
        print(f"  ⚪ 日内数据暂不可用 — 请确保数据源连接正常，并在交易时段运行")
        return

    print(f"\n{'='*60}")
    print(f"  ⏱️ T+0 日内时机分析")
    print(f"{'='*60}")

    has_intraday = t0_result.get("vwap", 0) > 0
    has_daily = t0_result.get("ma5", 0) > 0

    # 多日趋势
    if t0_result.get("multi_day_summary"):
        print(f"  📈 多日趋势: {t0_result['multi_day_summary']}")
    if t0_result.get("volume_trend"):
        print(f"     量能: {t0_result['volume_trend']}")
    if t0_result.get("gap_analysis"):
        print(f"  🔽 缺口分析: {t0_result['gap_analysis']}")
    if t0_result.get("overnight_risk"):
        print(f"  🌙 隔夜 & 布局检测: {t0_result['overnight_risk']}")

    # 操作建议
    emoji = T0_EMOJI.get(str(t0_result.get("action", "")), "❓")
    text = CN.get(str(t0_result.get("action", "")), str(t0_result.get("action", "未知")))
    if has_intraday:
        score_str = f"得分: {t0_result.get('score', 0)}"
    elif has_daily:
        score_str = f"得分: {t0_result.get('score', 0)} (基于最近收盘数据)"
    else:
        score_str = "得分: N/A (数据不足)"
    print(f"  {emoji} {text}  {score_str}")

    # 日线技术位
    if has_daily:
        print(f"  日线: MA5={t0_result.get('ma5',0):.2f} MA10={t0_result.get('ma10',0):.2f} MA20={t0_result.get('ma20',0):.2f} 支撑={t0_result.get('support_1',0)} 阻力={t0_result.get('resistance',0)}")

    # 日内细节
    if has_intraday:
        print(f"  日内: VWAP={t0_result.get('vwap',0):.2f} 振幅{t0_result.get('amplitude',0)}% 反弹{t0_result.get('rebound_from_low',0):+.1f}%")
        if t0_result.get("rebound_quality"):
            print(f"  {t0_result['rebound_quality']}")
        bear_signals = t0_result.get("signals_bear", [])
        bull_signals = t0_result.get("signals_bull", [])
        if bear_signals:
            print(f"  🔴 空头信号 ({len(bear_signals)}):")
            for s in bear_signals[:3]:
                print(f"     · {s}")
        if bull_signals:
            print(f"  🟢 多头信号 ({len(bull_signals)}):")
            for s in bull_signals[:2]:
                print(f"     · {s}")

    if t0_result.get("trigger_condition"):
        print(f"  📋 {t0_result['trigger_condition']}")


# ── 行业+公司深度研究 ───────────────────────────────────────────────

def print_sector_impact_summary(impact: dict | None) -> None:
    """输出行业→个股影响综述 (短期情绪 vs 中长期基本面双层分析)。

    impact 结构:
        {"stock": "赣锋锂业",
         "short_term": [{"factor": "...", "reason": "...", "impact": "negative"}],
         "long_term": [{"factor": "...", "reason": "...", "impact": "negative"}],
         "summary": "一句话总结"}
    """
    if not impact:
        return
    stock = impact.get("stock", "")
    short = impact.get("short_term", [])
    long_term_item = impact.get("long_term", [])
    if not short and not long_term_item:
        return

    print(f"\n  {'─' * 56}")
    print(f"  🎯 {stock} 行业环境影响综述")
    print(f"  {'─' * 56}")

    if short:
        print(f"\n  🔴 短期情绪利空 (会消退):")
        for item in short:
            factor = item.get("factor", "")
            reason = item.get("reason", "")
            print(f"     · {factor}")
            if reason:
                print(f"       └ {reason}")

    if long_term_item:
        print(f"\n  🟠 中长期基本面利空 (不会自动消失):")
        for item in long_term_item:
            factor = item.get("factor", "")
            reason = item.get("reason", "")
            print(f"     · {factor}")
            if reason:
                print(f"       └ {reason}")

    summary = impact.get("summary", "")
    if summary:
        print(f"\n  💡 {summary}")


def print_deep_research(sector_research: dict | None, company_deep_research: dict | None, stock_name: str = "") -> None:
    """输出行业深度研究 + 公司深度研究 (含 Workflow Checklist)。"""
    sector = sector_research
    if sector and sector.get("sector_name") != "未分类":
        print(f"\n{'='*60}")
        print(f"  🏭 行业深度研究")
        print(f"{'='*60}")

        # ── 行业→个股影响综述 (优先展示) ──
        impact = sector.get("stock_impact") or (
            sector.get("global_commodity", {}) or {}
        ).get("_stock_impact")
        print_sector_impact_summary(impact)

        # Workflow Checklist
        data_gaps = sector.get("data_gaps", [])
        gap_count = len(data_gaps)
        conf = sector.get("confidence", 0.65)
        print(f"  📋 Workflow: 行业定位✅ → 市场规模✅ → 竞争格局✅ → 估值✅ → 催化剂✅ → 供应链✅", end="")
        global_data = sector.get("global_commodity", {})
        if global_data and global_data.get("enabled"):
            print(" → 全球供需✅")
        else:
            print("")
        if gap_count > 0:
            print(f"     ⚠️ 数据缺口: {gap_count} 项  conf={conf:.2f}")
        else:
            print(f"     conf={conf:.2f}")

        print(f"  行业: {sector.get('sector_name','')}  {sector.get('sw2_name','')}  基准指数 {sector.get('benchmark_index','N/A')}")

        # Step 2: TAM
        tam = sector.get("tam_estimate")
        if tam:
            print(f"  市场规模: TAM≈{tam.get('tam_yi',0):.0f}亿 CAGR(3y)={tam.get('cagr_3y',0):+.1f}% CR5={tam.get('cr5',0):.0f}% CR10={tam.get('cr10',0):.0f}% [{tam.get('source_tier','T2')}]")

        comp = sector.get("competition", {})
        if comp:
            print(f"  竞争: CR5={comp.get('cr5',0):.0f}% HHI={comp.get('hhi',0):.0f} {comp.get('concentration','')} 壁垒={comp.get('barrier','?')} 烈度={comp.get('intensity',50):.0f}")

        val_fw = sector.get("valuation", {})
        if val_fw:
            print(f"  估值: {val_fw.get('primary_method','?')} PE中枢={val_fw.get('pe_median',0):.0f} 分位={val_fw.get('pe_percentile',50):.0f}% 吸引力={val_fw.get('attractiveness',50):.0f}/100")

        # Step 5: Catalysts
        catalysts = sector.get("catalysts", [])
        if catalysts:
            print(f"  催化剂: {', '.join(catalysts[:4])}  强度={sector.get('catalyst_score',50):.0f}/100")
        policy_notes = sector.get("policy_notes", [])
        if policy_notes:
            print(f"  政策: {', '.join(policy_notes[:3])}  影响={sector.get('policy_impact',0):+.0f}")

        sc = sector.get("supply_chain", {})
        if sc and sc.get("in_chain"):
            upstream = sc.get("upstream_tickers", [])
            downstream = sc.get("downstream_tickers", [])
            print(f"  供应链: {sc.get('node_name','?')} 层级={sc.get('layer','?')} 瓶颈={sc.get('bottleneck_score',0):.0f}/100 传导={sc.get('cost_pass_through',0.5):.1f}")
            if upstream:
                print(f"    上游: {', '.join(upstream[:6])}")
            if downstream:
                print(f"    下游: {', '.join(downstream[:6])}")

        # Step 7: Global Commodity
        if global_data and global_data.get("enabled"):
            print(f"\n  🌍 全球供需平衡 (Step 7)")
            print(f"  {'─'*50}")
            dq = global_data.get("data_quality", {})
            print(f"  商品类型: {global_data.get('commodity_type','')}  conf={dq.get('confidence',0.6):.2f} [{dq.get('source_tier','T2')}]")
            detailed = global_data.get("detailed_commodities", {})
            for sub_name, sub_data in detailed.items():
                display = sub_data.get("display_name", sub_name)
                assets = sub_data.get("overseas_assets", [])
                peers = sub_data.get("overseas_peers", [])
                risks = sub_data.get("geopolitical_risks", [])
                demand = sub_data.get("demand_drivers", {})
                print(f"  {display}:")
                if assets:
                    print(f"    海外产能 ({len(assets)} 个主要矿山/盐湖):")
                    for a in assets[:5]:
                        print(f"      • {a['name']} ({a['country']}) — {a.get('capacity','?')} — {a.get('cost_position','?')}")
                if peers:
                    peer_prices = global_data.get("peer_prices", {})
                    print(f"    对标 ({len(peers)} 家):")
                    for p in peers:
                        t = p['ticker']
                        pp = peer_prices.get(t, {})
                        price_str = f"${pp['price']}" if pp.get("price") else "N/A"
                        pe_str = f"PE={pp['pe_ttm']:.1f}" if pp.get("pe_ttm") else ""
                        print(f"      • {t} {p['name']} ({p['country']}) {price_str} {pe_str} [{p['role'][:30]}]")
                if risks:
                    high_risks = [r for r in risks if r.get("level") == "HIGH"]
                    if high_risks:
                        print(f"    🚨 高风险: {', '.join(r['risk'] for r in high_risks)}")
                if demand:
                    demand_str = " | ".join(f"{k}:{v*100:.0f}%" for k, v in demand.items())
                    print(f"    需求端: {demand_str}")
            yf_errors = global_data.get("yf_errors", [])
            if yf_errors:
                print(f"    ⚠️ yfinance 拉取失败: {len(yf_errors)} 项 [DATA_GAP]")
            skeleton = global_data.get("skeleton_commodities", [])
            if skeleton:
                print(f"    ⚠️ 骨架阶段 (待完善): {', '.join(skeleton)}")

    company = company_deep_research
    if company:
        print(f"\n{'='*60}")
        print(f"  🔬 公司深度研究")
        print(f"{'='*60}")
        moat_data = company.get("moat", {})
        if moat_data:
            dims = moat_data.get("dimensions", {})
            print(f"  🏰 护城河: {moat_data.get('width','?')} {moat_data.get('score',50):.0f}/100 趋势={moat_data.get('trend','stable')}")
            if dims:
                print(f"     品牌{dims.get('brand',50):.0f} 转换成本{dims.get('switching_cost',50):.0f} 网络效应{dims.get('network_effect',50):.0f} 规模{dims.get('scale_economy',50):.0f}")
        rf_data = company.get("red_flags")
        if rf_data:
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
            print(f"  🚩 财务红旗: {risk_emoji.get(rf_data.get('risk','unknown'),'?')} {rf_data.get('risk','?').upper()} ({rf_data.get('total_flags',0)}个)")
        dcf_data = company.get("dcf")
        if dcf_data:
            print(f"  💎 DCF: 公允价 ¥{dcf_data.get('fair_value',0):.2f} 安全边际={dcf_data.get('margin_of_safety',0):.1f}% 上行={dcf_data.get('upside_pct',0):+.1f}%")
        mgmt_data = company.get("management", {})
        if mgmt_data:
            print(f"  👔 管理层: {mgmt_data.get('overall',50):.0f}/100 配置{mgmt_data.get('capital_allocation',50):.0f} 诚信{mgmt_data.get('integrity',50):.0f}")
        overall = company.get("overall_score", 50)
        print(f"  🏆 深度研究综合: {overall:.0f}/100")


# ── P3: 批量对比 ─────────────────────────────────────────────────────

def print_batch_comparison(results: list[dict]) -> None:
    """输出多票横向诊断对比表。

    Args:
        results: [{
            "symbol": str, "name": str, "sector": str,
            "price": float, "pe": float, "roe_ann": float,
            "gross_margin": float, "val_score": float,
            "qual_score": float, "mom_score": float,
            "val_estimate": float, "cycle_score": float,
            "bottleneck_score": float, "raw_score": float,
            "alpha_score": float, "final_score": float,
            "rec": str, "doctrine_warns": list[str],
            "data_gaps": list[str],
        }]
    """
    if not results:
        print("(无诊断结果)")
        return

    # 按终分排序
    results = sorted(results, key=lambda r: r.get("final_score", 0), reverse=True)

    print(f"\n{'=' * 130}")
    print("📊 批量诊断对比")
    print(f"{'=' * 130}")

    # 表头
    header = (
        f"{'#':<3} {'代码':<8} {'名称':<8} {'赛道':<10} "
        f"{'价':>7} {'PE':>6} {'ROE':>5} {'毛利':>5} "
        f"{'值':>4} {'质':>4} {'动':>4} {'估':>4} {'周':>4} {'瓶':>4} "
        f"{'raw':>5} {'α':>4} {'终':>6} {'信号':<7} {'触发'}"
    )
    print(header)
    print("-" * 130)

    # 逐行
    for i, r in enumerate(results):
        pe_str = str(r.get("pe", "?"))
        if isinstance(r.get("pe"), float) and r["pe"] < 0:
            pe_str = "亏损"
        warns = r.get("doctrine_warns", [])
        warns_str = ",".join(warns[:2]) if warns else "-"
        print(
            f"{i+1:<3} {r['symbol']:<8} {r['name']:<8} {r.get('sector',''):<10} "
            f"{r.get('price',0):>7.1f} {pe_str:>6} {r.get('roe_ann',0):>4.0f}% {r.get('gross_margin',0):>4.0f}% "
            f"{r.get('val_score',0):>4.0f} {r.get('qual_score',0):>4.0f} {r.get('mom_score',0):>4.0f} "
            f"{r.get('val_estimate',0):>4.0f} {r.get('cycle_score',0):>4.0f} {r.get('bottleneck_score',0):>4.0f} "
            f"{r.get('raw_score',0):>5.1f} {r.get('alpha_score',0):>4.0f} "
            f"{r.get('final_score',0):>6.1f} {r.get('rec','?'):<7} {warns_str}"
        )

    print("-" * 130)

    # 分组汇总
    groups = {"BUY": [], "ADD": [], "HOLD": [], "REDUCE": [], "SELL": []}
    for r in results:
        rec = r.get("rec", "SELL")
        groups[rec].append(r)

    for label, recs, emoji in [
        ("推荐关注 (BUY/ADD)", ["BUY", "ADD"], "🟢"),
        ("观望 (HOLD)", ["HOLD"], "🟡"),
        ("建议回避 (SELL/REDUCE)", ["SELL", "REDUCE"], "🔴"),
    ]:
        items = []
        for rec in recs:
            items.extend(groups.get(rec, []))
        if items:
            names = ", ".join(
                f"{r['name']}({r['final_score']:.0f})" for r in items
            )
            print(f"{emoji} {label}: {names}")

    # 数据缺口汇总
    all_gaps = []
    for r in results:
        for g in r.get("data_gaps", []):
            if g not in all_gaps:
                all_gaps.append(g)
    if all_gaps:
        print(f"\n⚠️ 数据缺口:")
        for g in all_gaps:
            print(f"   {g}")

    print(f"{'=' * 130}\n")


# ── 辅助 ──────────────────────────────────────────────────────────────

def _ensure_cn(text: str) -> str:
    """翻译已知英文术语。"""
    result = text
    for en_term, cn_term in CN.items():
        if en_term in result:
            result = result.replace(en_term, cn_term)
    return result
