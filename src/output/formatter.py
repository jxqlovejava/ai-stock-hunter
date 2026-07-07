# -*- coding: utf-8 -*-
r"""详细分析输出格式化器 — 全链路分析结果 → 人类可读的丰富文本。

设计参考:
  - ai-gold-miner 的"结论优先"分区结构:
    核心结论 → 重要信息 → 数据透视 → 作战计划 → 风险与制衡
  - guardrails.md 要求的 tier/nature 标注
  - 小白友好: emoji 导航 + 显式事实/解释/推测标签 + 清晰分步

每条数据点标注 [tier/nature] 标签:
  - [📊T0/fact 事实]  一手原始数据 (交易所/央行/公告)
  - [📊T1/fact 事实]  权威数据商原始数据 (券商/国信/通达信)
  - [📊T2/fact 事实]  聚合/爬虫原始数据 (腾讯/东财/AKShare)
  - [🧠T2/解释]       基于事实的分析计算/评分
  - [🔮T3/推测]       前瞻/推演/不可验证
  - [⚠️/缺口]         数据缺失
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.routing.orchestrator import OrchestratorResult
    from src.routing.l1_analyze import AnalysisReport
    from src.routing.l2_judge import Verdict
    from src.data.source_citation import SourceCitation

# ── 常量 ────────────────────────────────────────────────────────────────────

SEP = "─" * 70
SEP_HALF = "─" * 40
DOUBLE_LINE = "=" * 70

PERSPECTIVE_LABELS = {
    "buffett": "巴菲特 (护城河+安全边际+长期持有)",
    "li_lu": "李录 (管理层文化+能力圈+复利思维)",
    "munger": "芒格 (逆向思维+心理学+避免愚蠢)",
    "lynch": "彼得·林奇 (PEG+成长性+草根调研)",
}

PERSPECTIVE_EMOJI = {
    "buffett": "🏰", "li_lu": "🎓", "munger": "🧠", "lynch": "🔍",
}

NATURE_ICON: dict[str, str] = {
    "fact": "📊",
    "interpretation": "🧠",
    "speculation": "🔮",
    "data_gap": "⚠️",
}

NATURE_LABEL: dict[str, str] = {
    "fact": "事实",
    "interpretation": "解释",
    "speculation": "推测",
    "data_gap": "缺口",
}


# ── 公共 API ────────────────────────────────────────────────────────────────


def format_analysis_result(result: OrchestratorResult) -> str:
    """全链路分析 → 小白友好的详细文本报告。

    分区 (结论优先 → 数据支撑 → 风险制衡):
      1. 📌 核心结论 — L2裁决 + 强制结论 (先回答"能不能买")
      2. 🏥 军规审查 — 30条军规触发详情
      3. 👤 投资者画像匹配 — 画像+能力圈+行为偏差
      4. 📊 数据透视 — L1多维评分 + 三情景估值
      5. 🎭 四视角辩论详情 — 巴菲特/李录/芒格/林奇各自观点
      6. 📈 Alpha Lens — 信息优势评估
      7. 🎲 博弈论 & 🧩 思维模型 — 市场博弈+心理模型
      8. ⚖️  L2 裁决详情 — 权重分解+风险+可证伪条件
      9. 💰 仓位 & 风控 — L3/L4最终决策
      10. 📊 数据溯源总览 — 信源分级+性质分类
    """
    lines: list[str] = []

    # ── 报告头部 ───────────────────────────────────────────────────────
    lines.append(f"\n{DOUBLE_LINE}")
    lines.append(f"  📊 {result.name}({result.symbol}) 全链路分析报告")
    lines.append(DOUBLE_LINE)

    # 元信息
    meta_parts = []
    if result.investor_prefs_applied:
        prefs = result.investor_prefs_applied
        meta_parts.append(
            f"风险偏好: {prefs.get('risk_profile', 'N/A')}"
        )
        meta_parts.append(
            f"投资目标: {prefs.get('investment_goal', 'N/A')}"
        )
        meta_parts.append(
            f"投资者级别: {prefs.get('tier', 'N/A')}"
        )
    meta_parts.append(
        f"行情验证: {'✅ 双源一致' if result.cross_validated else '⚠️ 单源/不一致'}"
    )
    lines.append("  " + " | ".join(meta_parts))

    # 门禁 + 阻断
    if not result.passed:
        lines.append(f"  🚫 阻断原因: {', '.join(result.blocked_by)}")
    if result.data_gaps:
        lines.append(f"  📭 数据缺口: {', '.join(result.data_gaps)}")

    # ── 1. 📌 核心结论 (先回答"能不能买") ────────────────────────────
    lines.append(f"\n{DOUBLE_LINE}")
    lines.append("  📌 核心结论")
    lines.append(DOUBLE_LINE)

    verdict = result.verdict
    enforced = result.enforced_verdict

    if verdict and enforced:
        rec_emoji = {"BUY": "🟢 建议买入", "ADD": "🔵 可加仓", "HOLD": "🟡 继续持有",
                      "REDUCE": "🟠 建议减仓", "SELL": "🔴 建议卖出"}.get(verdict.recommendation, "⚪")
        rec_explain = {
            "BUY": "综合评分≥75，多维度支持建仓",
            "ADD": "综合评分60-74，可在现有仓位基础上小幅加仓",
            "HOLD": "综合评分40-59，信号混杂或估值合理，观望为宜",
            "REDUCE": "综合评分25-39，风险大于机会，建议降低仓位",
            "SELL": "综合评分<25，多重风险叠加，建议清仓",
        }.get(verdict.recommendation, "")

        lines.append(f"  {rec_emoji}")
        lines.append(f"    综合评分: {verdict.score}/100  置信度: {verdict.confidence:.0%}")
        lines.append(f"    解读: {rec_explain}")
        lines.append(f"    💡 {enforced.get('one_line_conclusion', '')}")

        pr = enforced.get("price_range", {})
        if pr:
            lines.append(f"\n  💰 参考价格区间 [🔮T3/推测]:")
            lines.append(f"    当前价: {pr.get('current_price')}")
            lines.append(f"    建议买入价 ≤ {pr.get('buy_below')}  "
                         f"目标价 {pr.get('buy_target')}  "
                         f"建议卖出价 ≥ {pr.get('sell_above')}")

    elif verdict:
        rec_emoji = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴"}.get(verdict.recommendation, "⚪")
        lines.append(f"  {rec_emoji} {verdict.recommendation} — 评分: {verdict.score}/100  置信度: {verdict.confidence:.0%}")

    # ── 2. 🏥 军规审查 ────────────────────────────────────────────────
    doctrine = result.doctrine_result
    if doctrine:
        lines.append(f"\n{DOUBLE_LINE}")
        lines.append("  🏥 军规审查 — 30条硬规则逐条核查")
        lines.append(DOUBLE_LINE)

        blocked = doctrine.get("blocked", [])
        warns = doctrine.get("warnings", [])
        infos = doctrine.get("infos", [])

        lines.append(f"    审查结果: {'❌ 被拦截' if blocked else '✅ 通过 (无硬阻断)'}")
        lines.append(f"    触发规则: BLOCK={len(blocked)}  WARN={len(warns)}  INFO={len(infos)}")

        if blocked:
            lines.append(f"\n    🔴 阻断级 (BLOCK):")
            for r in blocked:
                lines.append(f"       • [{r['id']}] {r['name']} — {r['description'][:100]}")

        if warns:
            lines.append(f"\n    🟠 警告级 (WARN):")
            for r in warns[:8]:
                lines.append(f"       • [{r['id']}] {r['name']} — {r['description'][:100]}")
            if len(warns) > 8:
                lines.append(f"       ...还有 {len(warns) - 8} 条警告")

        if infos:
            lines.append(f"\n    ℹ️  信息级 (INFO):")
            for r in infos[:5]:
                lines.append(f"       • [{r['id']}] {r['name']} — {r['description'][:100]}")
            if len(infos) > 5:
                lines.append(f"       ...还有 {len(infos) - 5} 条信息")

    elif result.blocked_by:
        # 军规被block但无详情（旧版兼容）
        lines.append(f"\n    🏥 军规审查: ⛔ 被拦截 — {', '.join(result.blocked_by)}")

    # ── 3. 👤 投资者画像匹配 ──────────────────────────────────────────
    lines.append(f"\n{DOUBLE_LINE}")
    lines.append("  👤 投资者画像匹配")
    lines.append(DOUBLE_LINE)

    if result.investor_prefs_applied:
        prefs = result.investor_prefs_applied
        lines.append(f"    风险画像: {prefs.get('risk_profile', 'N/A')}  "
                     f"目标: {prefs.get('investment_goal', 'N/A')}  "
                     f"乘数: {prefs.get('risk_multiplier', 1.0):.2f}x")

    if result.mental_model_info:
        mm = result.mental_model_info
        fit_emoji = "✅" if mm.get("fit_score", 0) >= 60 else ("⚠️" if mm.get("fit_score", 0) >= 40 else "❌")
        lines.append(f"    匹配度: {fit_emoji} {mm.get('fit_score', 0)}/100")

        competence = mm.get("competence_match", "unknown")
        comp_label = {"in_circle": "✅ 能力圈内", "edge": "⚠️ 能力圈边缘", "out_of_circle": "❌ 能力圈外"}.get(competence, competence)
        lines.append(f"    能力圈: {comp_label}")

        if mm.get("risk_profile_match"):
            lines.append(f"    风险匹配: ✅ 标的波动与投资者风险偏好一致")
        else:
            lines.append(f"    风险匹配: ⚠️ 标的波动可能超出投资者风险承受范围")

        if mm.get("horizon_match"):
            lines.append(f"    期限匹配: ✅ 投资期限与策略匹配")
        else:
            lines.append(f"    期限匹配: ⚠️ 投资期限与策略可能不匹配")

        # 行为偏差
        bias_flags = mm.get("bias_flags", [])
        if bias_flags:
            lines.append(f"\n    ⚠️  行为偏差预警:")
            bias_explain = {
                "处置效应": "倾向于过早卖出盈利股、过久持有亏损股",
                "损失厌恶": "对亏损的恐惧超过对盈利的渴望，可能错失机会",
                "低系统遵从率": "历史记录显示不按系统规则操作，需注意纪律性",
            }
            for b in bias_flags[:5]:
                explanation = bias_explain.get(b, "")
                lines.append(f"       • {b}{' — ' + explanation if explanation else ''}")

        warnings_list = mm.get("warnings", [])
        if warnings_list:
            lines.append(f"\n    📋 投资提醒:")
            for w in warnings_list[:5]:
                lines.append(f"       • {w}")

    # ── 4. 📊 数据透视 ────────────────────────────────────────────────
    lines.append(f"\n{DOUBLE_LINE}")
    lines.append("  📊 数据透视 — L1 多维评分 + 估值分析")
    lines.append(DOUBLE_LINE)
    lines.append(format_l1_score_panel(result.report))

    # 多空双视角
    if result.report:
        report = result.report
        if report.bull_case or report.bear_case:
            lines.append(f"\n{SEP_HALF}")
            lines.append("  🐂🐻 多空双视角")
            lines.append(SEP_HALF)
        if report.bull_case:
            lines.append(f"  🟢 看多理由 [🔮推测]: {report.bull_case}")
        if report.bear_case:
            lines.append(f"  🔴 看空理由 [🔮推测]: {report.bear_case}")

        # 瓶颈分析
        if report.bottleneck_analysis is not None:
            ba = report.bottleneck_analysis
            lines.append(f"\n{SEP_HALF}")
            lines.append("  🏭 供应链瓶颈分析 [🧠解释]")
            lines.append(SEP_HALF)
            lines.append(f"    核心业务: {ba.core_business}")
            lines.append(f"    供应链定位: {ba.supply_chain_layer}  瓶颈类型: {ba.bottleneck_type}")
            lines.append(f"    瓶颈评分: {ba.bottleneck_score}/100 — {ba.constraint_description}")
        if report.bottlenecks:
            for b in report.bottlenecks:
                lines.append(f"    ⚡ {b}")
        if report.upstream_risks:
            lines.append("  ⛓️ 上游风险:")
            for r in report.upstream_risks:
                lines.append(f"    ⚠️  {r}")

    # 三情景估值
    sv = result.scenario_valuation
    if sv:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  📐 三情景估值 [🔮推测]")
        lines.append(SEP_HALF)

        method_label = sv.get("method", "未知")
        inputs = sv.get("inputs", {})
        lines.append(f"    计算方法: {method_label}")
        if inputs:
            inp_parts = []
            for k, v in inputs.items():
                if v is not None:
                    inp_parts.append(f"{k}={v}")
            if inp_parts:
                lines.append(f"    输入参数 [📊fact]: {', '.join(inp_parts)}")
        lines.append(f"    乐观公式: {sv.get('bull_formula', '基准×1.20')}")
        lines.append(f"    悲观公式: {sv.get('bear_formula', '基准×0.75')}")
        lines.append(f"\n    🟢 乐观目标: {sv.get('bull_target')}   "
                     f"🟡 基准估值: {sv.get('base_target')}   "
                     f"🔴 悲观目标: {sv.get('bear_target')}")
        upside = sv.get("implied_upside", 0) or 0
        downside = sv.get("implied_downside", 0) or 0
        rr_ratio = "有利" if upside > abs(downside) * 2 else ("较有利" if upside > abs(downside) else "一般")
        lines.append(f"    隐含上涨: {upside:+.1f}%  隐含下跌: {downside:+.1f}%  风险收益比: {rr_ratio}")
        lines.append(f"    ⚠️ 以上为基于PEG/PB-ROE模型的推测性计算 [🔮T3/推测]，仅供参考，不构成投资建议")

    # ── 5. 🎭 四视角辩论详情 ──────────────────────────────────────────
    perspectives = result.debate_perspectives
    if perspectives and result.debate_result:
        dr = result.debate_result
        lines.append(f"\n{DOUBLE_LINE}")
        lines.append("  🎭 四大师视角辩论 — 多角度审视同一标的")
        lines.append(DOUBLE_LINE)

        lines.append(f"    综合平均分: {dr.get('avg_score', 0):.2f}/5  "
                     f"分歧度: {dr.get('score_range', 0):.2f}")
        agree_level = dr.get("agreement_level", "")
        agree_emoji = {"consensus": "✅ 一致", "divided": "⚠️ 分歧", "polarized": "🔴 严重对立"}.get(agree_level, agree_level)
        lines.append(f"    一致度: {agree_emoji}")
        if dr.get("top_agreement"):
            lines.append(f"    ✅ 共识: {dr.get('top_agreement')}")
        if dr.get("top_disagreement"):
            lines.append(f"    ⚡ 最大分歧: {dr.get('top_disagreement')}")
        if dr.get("tension_summary"):
            lines.append(f"    💡 认知张力: {dr.get('tension_summary')}")

        # 逐个大师详情
        for key in ["buffett", "li_lu", "munger", "lynch"]:
            p = perspectives.get(key)
            if not p:
                continue
            emoji = PERSPECTIVE_EMOJI.get(key, "❓")
            label = PERSPECTIVE_LABELS.get(key, key)
            score = p.get("score", 0)
            verdict_str = p.get("verdict", "")
            verdict_icon = {"买入": "🟢", "观望": "🟡", "回避": "🔴"}.get(verdict_str, "⚪")

            lines.append(f"\n    {emoji} {label}")
            lines.append(f"       评分: {'⭐' * max(1, int(score))} {score:.1f}/5  "
                         f"判断: {verdict_icon} {verdict_str}  "
                         f"信心: {p.get('confidence', 0):.0%}")

            thesis = p.get("one_line_thesis", "")
            if thesis:
                lines.append(f"       💡 核心论点: {thesis}")
            concern = p.get("key_concern", "")
            if concern:
                lines.append(f"       ⚠️  最大担忧: {concern}")

            sub = p.get("sub_scores", {})
            if sub:
                sub_str = "  ".join(f"{k}:{v:.1f}" for k, v in sorted(sub.items())[:5])
                lines.append(f"       📊 子维度: {sub_str}")

            evidence = p.get("evidence", [])
            if evidence:
                for ev in evidence[:3]:
                    lines.append(f"       📋 {ev}")

            insight = p.get("unique_insight", "")
            if insight:
                lines.append(f"       🔍 独特发现: {insight}")

    elif result.debate_result:
        # 兼容旧版（无 perspectives 详情）
        dr = result.debate_result
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🎭 四视角辩论")
        lines.append(SEP_HALF)
        lines.append(f"    平均分: {dr.get('avg_score', 0):.2f}/5  分歧度: {dr.get('score_range', 0):.2f}")
        lines.append(f"    一致度: {dr.get('agreement_level', '')}")
        if dr.get("recommendation"):
            lines.append(f"    综合建议: {dr.get('recommendation')}")

    # ── 6. 📈 Alpha Lens ──────────────────────────────────────────────
    alpha = result.alpha_profile
    if alpha is not None:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  📈 Alpha Lens — 信息优势评估")
        lines.append(SEP_HALF)
        lines.append(f"    Alpha 评分: {alpha.alpha_score:.0f}/100  "
                     f"置信度: {alpha.alpha_confidence:.0%}  "
                     f"状态: {alpha.decay_status.value}")
        lines.append(f"    信源质量: {alpha.source.source_tier.value}  "
                     f"一手性: {alpha.source.originality_score:.0f}/100  "
                     f"噪音: {alpha.source.noise_ratio:.0%}")
        lines.append(f"    叙事阶段: {alpha.narrative.stage.value}  "
                     f"仓位上限: {alpha.narrative.position_cap_pct:.0f}%  "
                     f"提示: {alpha.narrative.action_hint}")
        if alpha.summary:
            lines.append(f"    💡 {alpha.summary}")

    # ── 7. 🎲 博弈论 & 🧩 思维模型 ────────────────────────────────────
    gt = result.game_theory_info
    mm_models = result.mental_models
    if gt or mm_models:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🎲 博弈论 & 🧩 思维模型")
        lines.append(SEP_HALF)

    if gt:
        lines.append(f"    🎲 博弈论: {gt.get('score', 0)}/100  "
                     f"主导: {gt.get('dominant_player', 'N/A')}  "
                     f"状态: {gt.get('market_regime', 'N/A')}")
        lines.append(f"       拥挤度: {gt.get('crowding_score', 0)}  "
                     f"杠杆: {gt.get('margin_score', 0)}  "
                     f"席位: {gt.get('seat_signal', 'N/A')}")
        for r in gt.get("risks", [])[:3]:
            lines.append(f"       ⚠️  {r}")

    if mm_models:
        lines.append(f"    🧩 Munger 思维模型 ({len(mm_models)}):")
        for m in mm_models[:5]:
            lines.append(f"       • {m.get('name_cn', '')} [{m.get('discipline', '')}]: {m.get('reason_for_match', '')}")

    # ── 8. ⚖️  L2 裁决详情 ────────────────────────────────────────────
    if verdict:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  ⚖️  L2 法官裁决详情")
        lines.append(SEP_HALF)
        lines.append(format_l2_verdict_detail(verdict))

    # ── 9. 💰 仓位 & 风控 ─────────────────────────────────────────────
    if result.signal and result.risk:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  💰 最终仓位决策 (L3+L4)")
        lines.append(SEP_HALF)
        s = result.signal
        action_emoji = {"OPEN": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "CLOSE": "🔴"}.get(s.action, "⚪")
        lines.append(f"    信号: {action_emoji} {s.action}  目标仓位: {s.target_weight:.1%}")
        lines.append(f"    调整后仓位: {result.risk.adjusted_weight:.1%}  "
                     f"风控: {'✅ 通过' if result.risk.passed else '⚠️ 不通过'}")
        if result.risk.violations:
            for v in result.risk.violations[:5]:
                lines.append(f"    🚫 {v}")

    # 红线
    if result.red_lines:
        lines.append(f"\n    🚨 红线触发: {', '.join(result.red_lines)}")

    # ── 10. 📊 数据溯源总览 ────────────────────────────────────────────
    all_citations: list[SourceCitation] = []
    if result.report is not None and result.report.source_citations:
        all_citations = result.report.source_citations
    if verdict is not None and verdict.source_citations:
        existing = {(sc.provider, sc.field) for sc in all_citations}
        for sc in verdict.source_citations:
            if (sc.provider, sc.field) not in existing:
                all_citations.append(sc)

    if all_citations:
        lines.append(f"\n{DOUBLE_LINE}")
        lines.append(format_citations_summary(all_citations))

    lines.append(f"\n{DOUBLE_LINE}")
    lines.append("  ⚠️  以上为 AI 分析结果，不构成投资建议。投资有风险，入市需谨慎。")
    lines.append(DOUBLE_LINE)

    return "\n".join(lines)


# ── 组件格式化函数 ──────────────────────────────────────────────────────────


def format_nature_tag(tier: str, nature: str) -> str:
    """T0-T3 + nature → 可视化标签。"""
    icon = NATURE_ICON.get(nature, "❓")
    label = NATURE_LABEL.get(nature, nature)
    return f"[{icon}{tier}/{label}]"


def format_citations_summary(citations: list[SourceCitation]) -> str:
    """信源分级 & 性质分类汇总表。"""
    lines = ["  📊 数据溯源总览", SEP]

    # 分级统计
    tier_counts = Counter(sc.source_tier for sc in citations)
    tier_str = "  ".join(
        f"{t}:{tier_counts.get(t, 0)}"
        for t in ["T0", "T1", "T2", "T3"]
        if tier_counts.get(t, 0) > 0
    )
    lines.append(f"    信源分级: {tier_str or '(无)'}")

    # 性质统计
    nature_counts = Counter(sc.nature for sc in citations)
    nature_parts = []
    for n in ["fact", "interpretation", "speculation", "data_gap"]:
        cnt = nature_counts.get(n, 0)
        if cnt > 0:
            icon = NATURE_ICON.get(n, "❓")
            label = NATURE_LABEL.get(n, n)
            nature_parts.append(f"{icon}{label}:{cnt}")
    lines.append(f"    数据性质: {'  '.join(nature_parts) or '(无)'}")

    # 综合质量
    quality_scores = [sc.quality_score for sc in citations if not sc.is_data_gap]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    quality_emoji = "✅" if avg_quality >= 0.7 else ("⚠️" if avg_quality >= 0.5 else "❌")
    lines.append(f"    综合质量: {quality_emoji} {avg_quality:.2f}/1.0")

    # 关键说明
    lines.append(f"\n    💡 数据性质说明:")
    lines.append(f"       📊 事实 = 可直接验证的原始数据（行情/财报/公告）")
    lines.append(f"       🧠 解释 = 基于事实的分析计算（评分/估值/模型匹配）")
    lines.append(f"       🔮 推测 = 前瞻性推演/不可验证（多空观点/博弈推演/情景估值）")
    lines.append(f"       ⚠️  缺口 = 数据缺失或获取失败")

    # 推测性数据提示
    spec_count = nature_counts.get("speculation", 0)
    if spec_count > 0:
        lines.append(f"\n    ⚠️  本报告含 {spec_count} 处推测性数据 [🔮推测]，仅供参考，不直接参与评分")

    # 缺口
    gap_citations = [sc for sc in citations if sc.is_data_gap]
    if gap_citations:
        lines.append(f"\n    ⚠️  [DATA_GAP] 数据缺口 ({len(gap_citations)}):")
        for gap in gap_citations:
            lines.append(f"       • {gap.provider}:{gap.field} — {gap.url_or_endpoint}")

    # 明细 (最多 10 条)
    lines.append(f"\n    引用明细 (前10条):")
    for sc in citations[:10]:
        tag = format_nature_tag(sc.source_tier, sc.nature)
        lines.append(f"      {tag} {sc.provider}:{sc.field} (置信度:{sc.confidence:.2f})")

    if len(citations) > 10:
        lines.append(f"      ...还有 {len(citations) - 10} 条引用")

    return "\n".join(lines)


def format_l1_score_panel(report: AnalysisReport | None) -> str:
    """L1 多维评分面板。"""
    if report is None:
        return "    ⚠️ L1 分析报告不可用"

    lines: list[str] = []

    def _bar(score: float, width: int = 30) -> str:
        fill = int(min(score, 100) / 100 * width)
        return "█" * fill + "░" * (width - fill)

    lines.append(f"    宏观环境:  {report.macro_score:5.0f}/100 {_bar(report.macro_score)} [🧠解释]")
    lines.append(f"    价值因子:  {report.value_score:5.0f}/100 {_bar(report.value_score)} [🧠解释]")
    lines.append(f"    质量因子:  {report.quality_score:5.0f}/100 {_bar(report.quality_score)} [🧠解释]")
    lines.append(f"    动量因子:  {report.momentum_score:5.0f}/100 {_bar(report.momentum_score)} [📊事实]")
    lines.append(f"    盈利修正:  {report.earnings_revision_score:5.0f}/100 {_bar(report.earnings_revision_score)} [🧠解释]")
    lines.append(f"    估值综合:  {report.valuation_score:5.0f}/100 {_bar(report.valuation_score)} [🧠解释]")
    lines.append(f"    周期适配:  {report.cycle_score:5.0f}/100 {_bar(report.cycle_score)} [🧠解释]")
    lines.append(f"    高管因子:  {report.executive_score:5.0f}/100 {_bar(report.executive_score)} [🧠解释]")

    sent_emoji = {"PANIC": "😱恐慌", "EXTREME": "🥶极度恐慌", "NORMAL": "😐正常", "GREED": "😈贪婪"}.get(report.sentiment_signal, report.sentiment_signal)
    lines.append(f"    情绪信号:  {sent_emoji} [📊事实]")

    if report.executive_risks:
        for r in report.executive_risks[:3]:
            lines.append(f"    ⚠️  高管风险: {r}")

    lines.append(f"\n    L1 综合置信度: {report.confidence:.0%}  "
                 f"数据时间: {report.data_freshness.strftime('%Y-%m-%d %H:%M')}")

    # 周期阶段
    if report.cycle_phase:
        cycle_str = str(report.cycle_phase)
        lines.append(f"    经济周期: {cycle_str} (适配度: {report.cycle_score:.0f}/100)")

    return "\n".join(lines)


def format_l2_verdict_detail(verdict: Verdict) -> str:
    """L2 裁决详情。"""
    lines: list[str] = []

    # Alpha 调整
    if verdict.alpha_rationale:
        lines.append(f"    💡 Alpha 理由: {verdict.alpha_rationale[:200]}")
    if verdict.consensus_challenge:
        lines.append(f"    🔍 共识挑战: {verdict.consensus_challenge}")
    if verdict.alpha_multiplier != 1.0:
        effect = "放大" if verdict.alpha_multiplier > 1.0 else "缩小"
        lines.append(f"    📐 Alpha 乘数: {verdict.alpha_multiplier:.2f}x ({effect}评分)")

    # 主题调整
    ta = verdict.topic_adjustments
    if ta:
        if ta.get("emerging_topics"):
            lines.append(f"    🌱 新兴主题: {', '.join(ta['emerging_topics'])}")
        if ta.get("crowded_topics"):
            lines.append(f"    ⚠️  拥挤主题: {', '.join(ta['crowded_topics'])}")
        if ta.get("fading_topics"):
            lines.append(f"    📉 消退主题: {', '.join(ta['fading_topics'])}")

    # 博弈论/思维模型调整
    gta = verdict.game_theory_adjustment
    if gta:
        lines.append(f"    🎲 博弈论调整: 乘数 {gta.get('gt_multiplier', 1.0):.2f}x")
    if verdict.mental_model_fit_score > 0:
        lines.append(f"    🧠 思维模型契合: {verdict.mental_model_fit_score}/100")

    # 风险列表
    if verdict.risks:
        lines.append(f"\n    ⚠️  风险提示 ({len(verdict.risks)}):")
        for r in verdict.risks[:10]:
            lines.append(f"       • {r}")
        if len(verdict.risks) > 10:
            lines.append(f"       ...还有 {len(verdict.risks) - 10} 条")

    # 可证伪条件
    if verdict.falsifiable:
        lines.append(f"\n    🔬 可证伪条件 — 以下任一触发则建议失效:")
        for f in verdict.falsifiable:
            lines.append(f"       • {f}")

    return "\n".join(lines)
