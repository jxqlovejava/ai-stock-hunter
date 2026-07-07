# -*- coding: utf-8 -*-
r"""详细分析输出格式化器 — 全链路分析结果 → 人类可读的丰富文本。

设计参考:
  - ai-gold-miner (daily_stock_analysis) 的分区 dashboard 结构
  - cmd_alpha 的详细逐行输出风格
  - guardrails.md 要求的 tier/nature 标注

每条数据点标注 [tier/nature] 标签:
  - [📊T0/fact]  一手事实数据 (交易所/央行/公告)
  - [📊T1/fact]  权威数据商原始数据 (券商/国信/通达信)
  - [📊T2/fact]  聚合/爬虫原始数据 (腾讯/东财/AKShare)
  - [🧠T2/interpretation]  基于事实的分析解释
  - [🔮T3/speculation]  推测/前瞻/不可验证
  - [⚠️/data_gap]  数据缺口
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.routing.orchestrator import OrchestratorResult
    from src.routing.l1_analyze import AnalysisReport
    from src.routing.l2_judge import Verdict
    from src.data.source_citation import SourceCitation

# ── 可视化标签映射 ──────────────────────────────────────────────────────────

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

TIER_LABEL: dict[str, str] = {
    "T0": "一手官方",
    "T1": "权威数据商",
    "T2": "聚合/爬虫",
    "T3": "推测/未验证",
}

SEP = "─" * 70
SEP_HALF = "─" * 40


# ── 公共 API ────────────────────────────────────────────────────────────────


def format_analysis_result(result: OrchestratorResult) -> str:
    """全链路分析 → 详细文本报告。

    分区:
      1. 门禁 & 数据溯源
      2. L1 多维评分面板
      3. 多空双视角
      4. 瓶颈分析 & 供应链风险
      5. 博弈论 & 投资思维模型
      6. AI Berkshire 四视角辩论
      7. Munger 思维模型匹配
      8. 三情景估值
      9. L2 裁决 & 强制结论
      10. L3 仓位 & L4 风控
      11. 可证伪条件 & 风险列表
      12. 📊 数据溯源总览
    """
    lines: list[str] = []

    # ── 0. 门禁状态 + 预警 ──────────────────────────────────────────────
    lines.append(f"\n{'=' * 70}")
    lines.append(f"  📊 {result.name}({result.symbol}) 全链路分析报告")
    lines.append(f"{'=' * 70}")

    # 版本信息
    version_info = []
    if result.strategy_version:
        version_info.append(f"策略版本: {result.strategy_version}")
    if result.investor_prefs_applied:
        prefs = result.investor_prefs_applied
        version_info.append(
            f"投资者: {prefs.get('risk_profile', 'N/A')} "
            f"目标: {prefs.get('investment_goal', 'N/A')} "
            f"级别: {prefs.get('tier', 'N/A')}"
        )
    if version_info:
        lines.append("  " + " | ".join(version_info))

    # 交叉验证
    cv_icon = "✅" if result.cross_validated else "⚠️"
    lines.append(f"  {cv_icon} 行情交叉验证: {'通过' if result.cross_validated else '未通过'}")

    # 门禁状态
    gate_icon = "✅" if result.passed else "⛔"
    lines.append(f"  {gate_icon} 门禁状态: {'通过' if result.passed else '不通过'}")
    if result.blocked_by:
        lines.append(f"  🚫 阻断原因: {', '.join(result.blocked_by)}")

    # 警告 & 数据缺口
    if result.warnings:
        lines.append(f"  ⚠️  警告: {', '.join(result.warnings[:5])}")
        if len(result.warnings) > 5:
            lines.append(f"       ...还有 {len(result.warnings) - 5} 条警告")
    if result.data_gaps:
        lines.append(f"  📭 数据缺口: {', '.join(result.data_gaps)}")

    # 红线
    if result.red_lines:
        lines.append(f"  🚨 红线触发: {', '.join(result.red_lines)}")

    # ── 1. L1 多维评分面板 ────────────────────────────────────────────
    report = result.report
    if report is not None:
        lines.append(f"\n{SEP}")
        lines.append("  📊 L1 多维评分面板")
        lines.append(SEP)
        lines.append(format_l1_score_panel(report))

        # ── 2. 多空双视角 ────────────────────────────────────────────
        lines.append(f"\n{SEP_HALF}")
        if report.bull_case:
            lines.append(f"  🐂 多头论点 [🔮T3/speculation]:")
            lines.append(f"    {report.bull_case}")
        if report.bear_case:
            lines.append(f"  🐻 空头论点 [🔮T3/speculation]:")
            lines.append(f"    {report.bear_case}")

        # ── 3. 瓶颈分析 ──────────────────────────────────────────────
        if report.bottleneck_analysis is not None:
            ba = report.bottleneck_analysis
            lines.append(f"\n{SEP_HALF}")
            lines.append("  🏭 物理瓶颈分析 (cyberagent 方法)")
            lines.append(SEP_HALF)
            lines.append(f"    核心业务: {ba.core_business}")
            lines.append(f"    供应链层级: {ba.supply_chain_layer}")
            lines.append(f"    瓶颈类型: {ba.bottleneck_type}")
            lines.append(f"    约束描述: {ba.constraint_description}")
            lines.append(f"    瓶颈评分: {ba.bottleneck_score}/100 [🧠T2/interpretation]")
        if report.bottlenecks:
            for b in report.bottlenecks:
                lines.append(f"    ⚡ {b}")
        if report.upstream_risks:
            lines.append("  ⛓️ 上游风险:")
            for r in report.upstream_risks:
                lines.append(f"    ⚠️  {r}")

    # ── 4. Alpha Profile ─────────────────────────────────────────────
    alpha = result.alpha_profile
    if alpha is not None:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  📈 Alpha Lens 三维评估")
        lines.append(SEP_HALF)
        lines.append(f"    Alpha 评分: {alpha.alpha_score:.0f}/100  置信度: {alpha.alpha_confidence:.0%}")
        lines.append(f"    衰减状态: {alpha.decay_status.value}")
        lines.append(f"    核心差异点: {alpha.key_differentiator}")
        lines.append(f"    信源层级: {alpha.source.source_tier.value}")
        lines.append(f"    一手性: {alpha.source.originality_score:.0f}/100  理解深度: {alpha.source.interpretation_depth:.0f}/100")
        lines.append(f"    噪音比例: {alpha.source.noise_ratio:.0%}")
        if alpha.source.primary_sources:
            lines.append(f"    一手来源: {', '.join(alpha.source.primary_sources[:3])}")
        if alpha.source.tertiary_sources:
            lines.append(f"    噪音来源: {', '.join(alpha.source.tertiary_sources[:3])}")
        lines.append(f"\n    叙事阶段: {alpha.narrative.stage.value}")
        lines.append(f"    早期信号: {alpha.narrative.early_signal_score:.0f}/100  拥挤信号: {alpha.narrative.crowded_signal_score:.0f}/100")
        lines.append(f"    仓位上限: {alpha.narrative.position_cap_pct:.0f}%  操作提示: {alpha.narrative.action_hint}")
        if alpha.consensus_gap.contrarian_evidence:
            for ev in alpha.consensus_gap.contrarian_evidence:
                lines.append(f"    🔄 {ev}")
        if alpha.summary:
            lines.append(f"\n    💡 {alpha.summary}")

    # ── 5. 博弈论 ─────────────────────────────────────────────────────
    if result.game_theory_info:
        gt = result.game_theory_info
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🎲 博弈论分析")
        lines.append(SEP_HALF)
        lines.append(f"    评分: {gt.get('score', 0)}/100  主导玩家: {gt.get('dominant_player', 'unknown')}")
        lines.append(f"    市场状态: {gt.get('market_regime', 'unknown')}  席位信号: {gt.get('seat_signal', 'unknown')}")
        lines.append(f"    拥挤度: {gt.get('crowding_score', 0)}  杠杆: {gt.get('margin_score', 0)}  冲击: {gt.get('impact_score', 0)}")
        for r_val in gt.get("risks", [])[:3]:
            lines.append(f"    ⚠️  {r_val}")

    # ── 6. 投资思维模型 ──────────────────────────────────────────────
    if result.mental_model_info:
        mm = result.mental_model_info
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🧠 投资思维模型匹配")
        lines.append(SEP_HALF)
        lines.append(f"    契合度: {mm.get('fit_score', 0)}/100  能力圈: {mm.get('competence_match', 'unknown')}")
        lines.append(f"    风险匹配: {mm.get('risk_profile_match', False)}")
        for f in mm.get("bias_flags", [])[:3]:
            lines.append(f"    ⚠️  {f}")

    # ── 7. Munger 思维模型 ───────────────────────────────────────────
    if result.mental_models:
        lines.append(f"\n{SEP_HALF}")
        lines.append(f"  🧩 Munger 思维模型推荐 ({len(result.mental_models)}):")
        for m in result.mental_models[:5]:
            lines.append(f"    • {m.get('name_cn', '')} [{m.get('discipline', '')}]: {m.get('reason_for_match', '')}")

    # ── 8. 四视角辩论 ─────────────────────────────────────────────────
    if result.debate_result:
        dr = result.debate_result
        lines.append(f"\n{SEP_HALF}")
        lines.append("  🎭 AI Berkshire 四视角辩论")
        lines.append(SEP_HALF)
        lines.append(f"    平均分: {dr.get('avg_score', 0):.2f}/5  分歧度: {dr.get('score_range', 0):.2f}")
        lines.append(f"    一致度: {dr.get('agreement_level', '')}")
        lines.append(f"    综合建议: {dr.get('recommendation', '')}")
        if dr.get("top_disagreement"):
            lines.append(f"    最大分歧: {dr.get('top_disagreement')}")

    # ── 9. 三情景估值 ─────────────────────────────────────────────────
    if result.scenario_valuation:
        sv = result.scenario_valuation
        lines.append(f"\n{SEP_HALF}")
        lines.append("  📐 三情景估值")
        lines.append(SEP_HALF)
        lines.append(f"    乐观目标: {sv.get('bull_target')}  基准: {sv.get('base_target')}  悲观: {sv.get('bear_target')}")
        upside = sv.get("implied_upside", 0)
        downside = sv.get("implied_downside", 0)
        lines.append(f"    隐含上涨: {upside:+.1f}%  隐含下跌: {downside:+.1f}%  "
                     f"风险收益比: {'有利' if (upside or 0) > abs(downside or 0) * 2 else '一般'}")

    # ── 10. 强制结论 ──────────────────────────────────────────────────
    if result.enforced_verdict:
        ev = result.enforced_verdict
        lines.append(f"\n{SEP_HALF}")
        lines.append("  ⚖️  强制结论 (VerdictEnforcer)")
        lines.append(SEP_HALF)
        lines.append(f"    级别: {ev.get('level')}  |  {ev.get('one_line_conclusion')}")
        if ev.get("is_abstain"):
            lines.append(f"    弃权原因: {', '.join(ev.get('abstain_reasons', []))}")
        pr = ev.get("price_range", {})
        if pr:
            lines.append(f"    当前价格: {pr.get('current_price')}")
            lines.append(f"    买入≤{pr.get('buy_below')} / 目标 {pr.get('buy_target')} / 卖出≥{pr.get('sell_above')}")
            lines.append(f"    仓位: {pr.get('position_pct', 0):.1%}")

    # ── 11. L2 裁决 ───────────────────────────────────────────────────
    if result.verdict:
        lines.append(f"\n{SEP}")
        lines.append("  ⚖️  L2 法官裁决")
        lines.append(SEP)
        lines.append(format_l2_verdict_detail(result.verdict))

    # ── 12. L3 仓位 & L4 风控 ─────────────────────────────────────────
    if result.signal and result.risk:
        lines.append(f"\n{SEP_HALF}")
        lines.append("  💰 L3 仓位 & L4 风控")
        lines.append(SEP_HALF)
        s = result.signal
        action_emoji = {"OPEN": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "CLOSE": "🔴"}.get(s.action, "⚪")
        lines.append(f"    信号: {action_emoji} {s.action}  "
                     f"目标仓位: {s.target_weight:.1%}  调整后: {result.risk.adjusted_weight:.1%}")
        lines.append(f"    信号置信度: {s.confidence:.0%}  "
                     f"风控: {'✅ 通过' if result.risk.passed else '⚠️  不通过'}")
        if result.risk.violations:
            for v in result.risk.violations[:5]:
                lines.append(f"    🚫 {v}")

    # ── 13. 数据溯源总览 ──────────────────────────────────────────────
    all_citations: list[SourceCitation] = []
    if report is not None and report.source_citations:
        all_citations = report.source_citations
    if result.verdict is not None and result.verdict.source_citations:
        # 合并，去重
        existing = {(sc.provider, sc.field) for sc in all_citations}
        for sc in result.verdict.source_citations:
            if (sc.provider, sc.field) not in existing:
                all_citations.append(sc)

    if all_citations:
        lines.append(f"\n{SEP}")
        lines.append(format_citations_summary(all_citations))

    lines.append(f"\n{'=' * 70}")
    lines.append("  ⚠️  以上为 AI 分析结果，不构成投资建议。投资有风险，入市需谨慎。")

    return "\n".join(lines)


# ── 组件格式化函数 ──────────────────────────────────────────────────────────


def format_nature_tag(tier: str, nature: str) -> str:
    """将 T0-T3 + nature 转为可视化标签。

    >>> format_nature_tag("T1", "fact")
    '[📊T1/fact]'
    >>> format_nature_tag("T2", "interpretation")
    '[🧠T2/interpretation]'
    """
    icon = NATURE_ICON.get(nature, "❓")
    return f"[{icon}{tier}/{nature}]"


def format_citations_summary(citations: list[SourceCitation]) -> str:
    """信源分级 & 性质分类汇总表。

    输出样例:
      📊 数据溯源总览
      ──────────────────────────────────────────────────────────────────
        分级统计: T0:2  T1:5  T2:8  T3:3
        性质统计: 📊事实:12  🧠解释:4  🔮推测:2  ⚠️缺口:1
        综合质量: 0.78/1.0
        数据新鲜度: 2026-07-07 14:30
      ──────────────────────────────────────────────────────────────────
        明细:
          [📊T1/fact] mootdx:quote (置信度:0.85 新鲜:5min)
          [📊T2/fact] miaoxiang:quote (置信度:0.75 新鲜:5min)
          ...
    """
    lines = ["  📊 数据溯源总览", SEP]

    # 分级统计
    tier_counts = Counter(sc.source_tier for sc in citations)
    tier_str = "  ".join(f"{t}:{tier_counts.get(t, 0)}" for t in ["T0", "T1", "T2", "T3"] if tier_counts.get(t, 0) > 0)
    lines.append(f"    分级统计: {tier_str or '(无)'}")

    # 性质统计
    nature_counts = Counter(sc.nature for sc in citations)
    nature_parts = []
    for n in ["fact", "interpretation", "speculation", "data_gap"]:
        cnt = nature_counts.get(n, 0)
        if cnt > 0:
            icon = NATURE_ICON.get(n, "❓")
            label = NATURE_LABEL.get(n, n)
            nature_parts.append(f"{icon}{label}:{cnt}")
    lines.append(f"    性质统计: {'  '.join(nature_parts) or '(无)'}")

    # 综合质量
    quality_scores = [sc.quality_score for sc in citations if not sc.is_data_gap]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    lines.append(f"    综合质量: {avg_quality:.2f}/1.0")

    # 未溯源标记
    unsourced_count = sum(1 for sc in citations if sc.provider == "unsourced")
    if unsourced_count > 0:
        lines.append(f"    ⚠️  [UNSOURCED] 未溯源标记: {unsourced_count} 处")

    # 数据缺口
    gap_citations = [sc for sc in citations if sc.is_data_gap]
    if gap_citations:
        lines.append(f"    ⚠️  [DATA_GAP] 数据缺口: {len(gap_citations)} 处")
        for gap in gap_citations:
            lines.append(f"       • {gap.provider}:{gap.field} — {gap.url_or_endpoint}")

    # 明细 (最多显示 15 条，避免过长)
    lines.append("")
    lines.append("    明细:")
    for sc in citations[:15]:
        tag = format_nature_tag(sc.source_tier, sc.nature)
        fresh = f"{sc.data_freshness}" if not sc.is_data_gap else "已过期"
        cached_note = " (缓存)" if sc.is_cached else ""
        lines.append(f"      {tag} {sc.provider}:{sc.field} (置信度:{sc.confidence:.2f} 新鲜度:{fresh}){cached_note}")

    if len(citations) > 15:
        lines.append(f"      ...还有 {len(citations) - 15} 条引用来源")

    return "\n".join(lines)


def format_l1_score_panel(report: AnalysisReport) -> str:
    """L1 8 维评分面板 — 每条评分附 nature 标注。"""
    lines: list[str] = []

    # 评分行: 字段名 + 分数 + 可视化进度条 + nature 标签
    def _score_row(label: str, score: float, tier: str, nature: str, width: int = 40) -> str:
        bar_fill = int(min(score, 100) / 100 * width)
        bar = "█" * bar_fill + "░" * (width - bar_fill)
        tag = format_nature_tag(tier, nature)
        return f"    {label:12s} {score:5.0f}/100 {bar} {tag}"

    lines.append(f"    宏观环境:    {_score_row('', report.macro_score, 'T2', 'interpretation')}")
    lines.append(_score_row("价值因子", report.value_score, "T2", "interpretation"))
    lines.append(_score_row("质量因子", report.quality_score, "T2", "interpretation"))
    lines.append(_score_row("动量因子", report.momentum_score, "T1", "fact"))
    lines.append(_score_row("盈利修正", report.earnings_revision_score, "T2", "interpretation"))
    lines.append(_score_row("估值综合", report.valuation_score, "T2", "interpretation"))
    lines.append(_score_row("周期适配", report.cycle_score, "T2", "interpretation"))
    lines.append(_score_row("高管因子", report.executive_score, "T2", "interpretation"))

    # 情绪信号
    sentiment_emoji = {"PANIC": "😱", "EXTREME": "🥶", "NORMAL": "😐", "GREED": "😈"}.get(report.sentiment_signal, "❓")
    lines.append(f"    情绪信号:    {sentiment_emoji} {report.sentiment_signal} [📊T2/fact]")

    # 高管风险
    if report.executive_risks:
        for r in report.executive_risks[:3]:
            lines.append(f"    ⚠️  高管风险: {r}")

    # L1 综合置信度
    lines.append(f"\n    L1 综合置信度: {report.confidence:.0%}  数据新鲜度: {report.data_freshness.strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


def format_l2_verdict_detail(verdict: Verdict) -> str:
    """L2 裁决详情 — 含权重分解、风险列表、可证伪条件。"""
    lines: list[str] = []

    # 裁决总览
    rec_emoji = {"BUY": "🟢", "ADD": "🔵", "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴"}.get(verdict.recommendation, "⚪")
    lines.append(f"    评分: {verdict.score}/100  置信度: {verdict.confidence:.0%}  "
                 f"建议: {rec_emoji} {verdict.recommendation}")
    lines.append(f"    生成时间: {verdict.created_at.strftime('%Y-%m-%d %H:%M')}")

    # Alpha 理由
    if verdict.alpha_rationale:
        lines.append(f"\n    💡 Alpha 理由: {verdict.alpha_rationale[:200]}")
    if verdict.consensus_challenge:
        lines.append(f"    🔍 共识挑战: {verdict.consensus_challenge}")
    if verdict.alpha_multiplier != 1.0:
        multiplier_note = "放大" if verdict.alpha_multiplier > 1.0 else "缩小"
        lines.append(f"    📐 Alpha 乘数: {verdict.alpha_multiplier:.2f}x ({multiplier_note})")

    # 主题调整
    if verdict.topic_adjustments:
        ta = verdict.topic_adjustments
        if ta.get("emerging_topics"):
            lines.append(f"    🌱 新兴主题: {', '.join(ta['emerging_topics'])}")
        if ta.get("crowded_topics"):
            lines.append(f"    ⚠️  拥挤主题: {', '.join(ta['crowded_topics'])}")
        if ta.get("fading_topics"):
            lines.append(f"    📉 消退主题: {', '.join(ta['fading_topics'])}")

    # 博弈论调整
    if verdict.game_theory_adjustment:
        gta = verdict.game_theory_adjustment
        lines.append(f"\n    🎲 博弈论调整: 乘数 {gta.get('gt_multiplier', 1.0):.2f}x  评分 {gta.get('gt_score', 50)}/100")

    # 思维模型调整
    if verdict.mental_model_fit_score > 0:
        lines.append(f"    🧠 思维模型契合: {verdict.mental_model_fit_score}/100")
        if verdict.mental_model_warnings:
            for w in verdict.mental_model_warnings[:3]:
                lines.append(f"       ⚠️  {w}")

    # 风险列表
    if verdict.risks:
        lines.append(f"\n    ⚠️  风险提示 ({len(verdict.risks)}):")
        for r in verdict.risks[:10]:
            lines.append(f"       • {r}")
        if len(verdict.risks) > 10:
            lines.append(f"       ...还有 {len(verdict.risks) - 10} 条风险")

    # 可证伪条件
    if verdict.falsifiable:
        lines.append(f"\n    🔬 可证伪条件 ({len(verdict.falsifiable)}):")
        for f in verdict.falsifiable:
            lines.append(f"       • {f}")

    # 引用来源 (简要)
    if verdict.source_citations:
        sources = list(dict.fromkeys(
            f"{sc.provider}" for sc in verdict.source_citations
            if sc.provider and not sc.is_data_gap
        ))
        if sources:
            lines.append(f"\n    📚 数据来源: {', '.join(sources[:8])}")
            if len(sources) > 8:
                lines.append(f"       ...还有 {len(sources) - 8} 个来源")

    return "\n".join(lines)
