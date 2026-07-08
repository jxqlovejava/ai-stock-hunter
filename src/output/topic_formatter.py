# -*- coding: utf-8 -*-
r"""主题分析输出格式化器

场景 4a 纯主题分析的格式化输出，供 CLI 和 API 使用。

Profile-Aware 备注:
  - 本模块当前使用统一终端风格输出。
  - 要适配不同渠道，使用 src/output/profiles.py 中的 OutputProfile。
"""

from __future__ import annotations

from typing import Any

from src.output.formatter import CN, HR, HR_THICK, NATURE_ICON, NATURE_LABEL

# 生命周期阶段对应的 emoji
LIFECYCLE_EMOJI: dict[str, str] = {
    "emerging": "🌱",
    "spreading": "📡",
    "consensus": "🤝",
    "crowded": "🚨",
    "fading": "📉",
    "dormant": "💤",
}

# 拥挤度解释表
# (下界, 上界) -> (emoji, 中文标签, 解释)
CROWDING_LEVELS: list[tuple[int, int, str, str, str]] = [
    (0, 30, "🟢", "低拥挤", "主题处于早期阶段，筹码尚未集中，空间充足"),
    (30, 60, "🟡", "中等拥挤", "已有资金入场，需关注持仓集中度变化"),
    (60, 80, "🟠", "高拥挤", "交易拥挤度偏高，波动风险加大"),
    (80, 101, "🔴", "极度拥挤", "筹码高度集中，警惕资金踩踏反转"),
]


def _get_crowding_level(score: int) -> tuple[str, str, str]:
    """根据拥挤度评分返回 (emoji, 标签, 解释)."""
    for lo, hi, emoji, label, explanation in CROWDING_LEVELS:
        if lo <= score < hi:
            return emoji, label, explanation
    return "⚪", "未知", "无法判断拥挤程度"


def _format_citation_summary(citations: list[dict[str, Any]]) -> list[str]:
    """格式化数据溯源摘要。

    从 source_citations 列表中提取分级/性质/质量统计。
    """
    lines: list[str] = []
    tier_counts: dict[str, int] = {}
    nature_counts: dict[str, int] = {}
    quality_scores: list[float] = []

    for c in citations:
        t = c.get("tier", "T2")
        tier_counts[t] = tier_counts.get(t, 0) + 1
        n = c.get("nature", "fact")
        nature_counts[n] = nature_counts.get(n, 0) + 1
        q = c.get("quality_score")
        if q is not None:
            quality_scores.append(float(q))

    if tier_counts:
        parts = "  ".join(
            f"{t}:{tier_counts.get(t, 0)}"
            for t in ["T0", "T1", "T2", "T3"]
            if tier_counts.get(t, 0)
        )
        lines.append(f"  分级: {parts}")

    if nature_counts:
        parts = []
        for n in ["fact", "interpretation", "speculation", "data_gap"]:
            cnt = nature_counts.get(n, 0)
            if cnt:
                parts.append(f"{NATURE_ICON.get(n, '?')}{NATURE_LABEL.get(n, n)}:{cnt}")
        if parts:
            lines.append(f"  性质: {'  '.join(parts)}")

    if quality_scores:
        avg = sum(quality_scores) / len(quality_scores)
        lines.append(f"  质量: {avg:.2f}/1.0")

    spec_count = nature_counts.get("speculation", 0)
    if spec_count:
        lines.append(f"  ⚠️ 含{spec_count}处推测数据，仅供参考不参与评分")

    return lines


def format_topic_analysis(topic_result: dict[str, Any]) -> str:
    """Format a pure topic analysis (场景 4a) result into a human-readable string.

    Args:
        topic_result: A dict with topic analysis data. Expected keys:

            - topic_name: str — 主题名称
            - lifecycle_stage: str — 生命周期阶段
              (emerging/spreading/consensus/crowded/fading)
            - crowding_score: int — 拥挤度 0-100
            - supply_chain_overview: str — 产业链全景描述
            - representative_stocks: list[dict] — 代表标的列表,
              每个含 symbol/name/pe/market_cap
            - key_catalysts: list[str] — 关键催化剂
            - attention_points: list[str] — 后续关注点
            - source_citations: list[dict] — 数据溯源列表,
              每个含 tier/nature/quality_score

    Returns:
        Formatted string ready for CLI output. 缺失的 key 会静默跳过对应段落。
    """
    lines: list[str] = []

    # ── 1. 头部 ──────────────────────────────────────────────────────────
    topic_name = topic_result.get("topic_name", "未知主题")
    lines.append(f"\n  🏭 主题深度分析: {topic_name}")
    lines.append(f"  {HR_THICK}")

    # ── 2. 生命周期阶段 ────────────────────────────────────────────────────
    lifecycle_stage = topic_result.get("lifecycle_stage")
    if lifecycle_stage:
        emoji = LIFECYCLE_EMOJI.get(lifecycle_stage, "❓")
        cn_label = CN.get(lifecycle_stage, lifecycle_stage)
        lines.append(f"\n  📈 生命周期阶段")
        lines.append(f"  {HR}")
        lines.append(f"  {emoji} {cn_label}")

    # ── 3. 拥挤度评分 ─────────────────────────────────────────────────────
    crowding_score = topic_result.get("crowding_score")
    if crowding_score is not None:
        emoji, label, explanation = _get_crowding_level(crowding_score)
        bar = "▓" * int(crowding_score / 5) + "░" * (20 - int(crowding_score / 5))
        lines.append(f"\n  🚦 拥挤度评分")
        lines.append(f"  {HR}")
        lines.append(f"  {emoji} {crowding_score}/100  {label}")
        lines.append(f"  {bar}")
        lines.append(f"  💡 {explanation}")

    # ── 4. 产业链全景 ─────────────────────────────────────────────────────
    supply_chain = topic_result.get("supply_chain_overview")
    if supply_chain:
        lines.append(f"\n  🔗 产业链全景")
        lines.append(f"  {HR}")
        lines.append(f"  {supply_chain}")

    # ── 5. 代表标的对比表 ─────────────────────────────────────────────────
    stocks = topic_result.get("representative_stocks")
    if stocks:
        lines.append(f"\n  📋 代表标的对比")
        lines.append(f"  {HR}")
        lines.append(f"  {'代码':<8} {'名称':<12} {'PE':>8} {'市值(亿)':>10}")
        lines.append(f"  {'──':<8} {'──':<12} {'──':>8} {'──────':>10}")
        for s in stocks:
            symbol = s.get("symbol", "?")
            name = (s.get("name") or "?")[:12]
            pe = s.get("pe")
            pe_str = f"{pe:.1f}" if pe is not None else "N/A"
            cap = s.get("market_cap")
            cap_str = f"{cap:.0f}" if cap is not None else "N/A"
            lines.append(f"  {symbol:<8} {name:<12} {pe_str:>8} {cap_str:>10}")

    # ── 6. 关键催化剂 ─────────────────────────────────────────────────────
    catalysts = topic_result.get("key_catalysts")
    if catalysts:
        lines.append(f"\n  ⚡ 关键催化剂")
        lines.append(f"  {HR}")
        for i, c in enumerate(catalysts, 1):
            lines.append(f"  {i}. {c}")

    # ── 7. 后续关注点 ─────────────────────────────────────────────────────
    attention = topic_result.get("attention_points")
    if attention:
        lines.append(f"\n  👀 后续关注点")
        lines.append(f"  {HR}")
        for i, a in enumerate(attention, 1):
            lines.append(f"  {i}. {a}")

    # ── 8. 数据溯源 ───────────────────────────────────────────────────────
    citations = topic_result.get("source_citations")
    if citations:
        lines.append(f"\n  📊 数据溯源")
        lines.append(f"  {HR}")
        lines.extend(_format_citation_summary(citations))

    lines.append(f"\n  ⚠️ AI分析结果，不构成投资建议。投资有风险，入市需谨慎。\n")
    return "\n".join(lines)
