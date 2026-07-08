# -*- coding: utf-8 -*-
"""归因输出格式器 — 强制渲染 guardrails.md 规定的输出格式。

输出模板对应 `.claude/rules/guardrails.md` 第 124-143 行的强制格式：
  - 📋 信息源质量总览 (T0-T3 分级统计表)
  - 🚫 过期信息（已排除）
  - ⚠️ [DATA_GAP] 声明
  - 归因权重（按质量分加权）表
  - 主因/次因/噪音排序
"""

from __future__ import annotations

from src.routing.attribution_types import AttributionResult, QualitySummary


def format_quality_table(quality: QualitySummary) -> str:
    """渲染信息源质量总览表格。

    对应 guardrails.md 强制格式：
      | Tier | 数量 | 平均质量分 | 示例 |
    """
    if not quality.tier_counts:
        return "📋 信息源质量总览: (无数据)"

    lines = ["📋 信息源质量总览"]
    lines.append("| Tier | 数量 | 平均质量分 | 示例 |")
    lines.append("|------|------|-----------|------|")

    for tier in ["T0", "T1", "T2", "T3"]:
        count = quality.tier_counts.get(tier, 0)
        avg_q = quality.tier_avg_quality.get(tier, 0.0)
        examples = quality.tier_examples.get(tier, ["—"])
        # 清理示例中的原始对象转储
        cleaned = []
        for e in examples:
            if e.startswith("title=") or e.startswith("[]"):
                continue  # 跳过空/原始对象转储
            cleaned.append(e[:60])
        if not cleaned:
            cleaned = ["(无有效数据)"]
        example_str = ", ".join(cleaned[:3])
        if count > 0:
            lines.append(f"| {tier:<4} | {count:>4} | {avg_q:>9.4f} | {example_str[:60]:<60} |")
        else:
            lines.append(f"| {tier:<4} | {count:>4} | {avg_q:>9.4f} | {'(无)':<60} |")

    return "\n".join(lines)


def format_stale_section(stale_excluded: list[str]) -> str:
    """渲染过期信息排除列表。"""
    if not stale_excluded:
        return "🚫 过期信息（已排除）: 无"
    lines = ["🚫 过期信息（已排除）:"]
    for i, item in enumerate(stale_excluded, 1):
        lines.append(f"  {i}. [STALE] {item}")
    return "\n".join(lines)


def format_data_gaps(data_gaps: list[str], impact: str = "") -> str:
    """渲染数据缺口声明。"""
    if not data_gaps:
        return "⚠️ [DATA_GAP]: 无"
    lines = ["⚠️ [DATA_GAP]:"]
    for i, gap in enumerate(data_gaps, 1):
        lines.append(f"  {i}. {gap}")
    if impact:
        lines.append(f"  影响: {impact}")
    return "\n".join(lines)


def format_driver_table(drivers: list) -> str:
    """渲染归因权重表。

    对应 guardrails.md 强制格式：
      | 驱动因素 | 权重 | Tier | 性质 | 时效 |
    """
    if not drivers:
        return "归因权重: (未计算)"

    lines = ["归因权重（按质量分加权）:"]
    lines.append("| 驱动因素 | 权重 | Tier | 性质 | 时效 |")
    lines.append("|---------|------|------|------|------|")

    for d in drivers:
        weight_pct = f"{d.weight * 100:.0f}%"
        lines.append(
            f"| {d.name:<30} | {weight_pct:>4} | {d.tier:<4} | {d.nature:<14} | {d.freshness:<6} |"
        )

    return "\n".join(lines)


def format_attribution_result(result: AttributionResult) -> str:
    """生成完整的归因分析输出。

    严格遵循 guardrails.md 第 124-143 行的强制输出格式，
    包含信息源质量总览 → 过期排除 → 数据缺口 → 归因权重 → 因果排序。
    """
    sections = []

    # ── 标题 ──
    direction = "上涨" if result.price_change_pct > 0 else "下跌"
    sections.append(f"🔍 个股涨跌归因: {result.symbol} {result.name}")
    sections.append(f"   日期: {result.date} | 涨跌幅: {result.price_change_pct:+.2f}%")
    sections.append("=" * 60)

    # ── Phase 1 摘要 ──
    total_points = len(result.raw_data_points)
    active_points = [p for p in result.raw_data_points if not p.is_stale and not p.data_gap_reason]
    sections.append(f"\n📡 Phase 1 — 信息搜集: {total_points} 条数据点 (有效 {len(active_points)} 条)")

    # ── 信息源质量总览 (强制) ──
    sections.append("")
    sections.append(format_quality_table(result.quality))

    # ── 过期排除 (强制) ──
    sections.append("")
    sections.append(format_stale_section(result.quality.stale_excluded))

    # ── DATA_GAP (强制) ──
    sections.append("")
    sections.append(format_data_gaps(result.quality.data_gaps, result.quality.data_gap_impact))

    # ── 整体置信度 ──
    sections.append(f"\n整体 confidence: {result.quality.overall_confidence:.2f}")

    # ── Phase 2 多维归因 ──
    sections.append(f"\n📊 Phase 2 — 多维归因")
    sections.append("-" * 40)
    if result.macro_assessment:
        sections.append(f"  宏观背景: {result.macro_assessment[:200]}")
    if result.sector_assessment:
        sections.append(f"  板块联动: {result.sector_assessment[:200]}")
    if result.sentiment_assessment:
        sections.append(f"  情绪状态: {result.sentiment_assessment[:200]}")
    if result.topic_assessment:
        sections.append(f"  主题周期: {result.topic_assessment[:200]}")
    if result.capital_flow_assessment:
        sections.append(f"  资金面:   {result.capital_flow_assessment[:200]}")
    if result.technical_assessment:
        sections.append(f"  技术面:   {result.technical_assessment[:200]}")

    # ── 归因权重 (强制) ──
    sections.append("")
    sections.append(format_driver_table(result.drivers))

    # ── Phase 3 因果推断 ──
    sections.append(f"\n🧠 Phase 3 — 因果推断")
    sections.append("-" * 40)

    if result.primary_driver:
        sections.append(f"\n  🥇 主因: {result.primary_driver}")

    if result.secondary_drivers:
        sections.append(f"\n  🥈 次因:")
        for d in result.secondary_drivers:
            sections.append(f"     • {d}")

    if result.noise_factors:
        sections.append(f"\n  🔊 噪音:")
        for n in result.noise_factors:
            sections.append(f"     • {n}")

    if result.causality_chain:
        sections.append(f"\n  🔗 因果链:")
        sections.append(f"     {result.causality_chain}")

    # ── 置信度 ──
    sections.append(f"\n  📐 归因置信度: {result.confidence:.0%}")

    # ── 数据溯源声明 ──
    if result.data_freshness_warning:
        sections.append(f"\n⚠️ {result.data_freshness_warning}")

    return "\n".join(sections)
