# -*- coding: utf-8 -*-
"""业绩先行研判 — 格式化输出。

用法:
    from src.output.earnings_preview_fmt import print_earnings_preview
    print_earnings_preview(result, basket)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.data.commodity.schemas import LithiumBasket
from src.industry.earnings_preview import EarningsPreviewResult

HR = "─" * 60
HR_THICK = "━" * 60


def print_earnings_preview(
    result: EarningsPreviewResult,
    basket: Optional[LithiumBasket] = None,
    sensitivity_table: Optional[list[dict]] = None,
) -> None:
    """输出 Q2 业绩先行研判报告。"""
    b = basket or result.basket

    # ── 标题 ──
    print(f"\n{'='*60}")
    print(f"  📊 {result.name}({result.code}) Q2 业绩先行研判")
    print(f"  生成时间: {result.generated_at.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # ── 数据质量声明 ──
    _print_data_quality(result, b)

    # ── 先行指标概览 ──
    _print_leading_indicators(b)

    # ── 业绩测算 ──
    _print_earnings_estimate(result)

    # ── 敏感性分析 ──
    if sensitivity_table:
        _print_sensitivity(sensitivity_table)
    else:
        _print_sensitivity_summary(result)

    # ── 因果传导链 (借鉴 MiroFish PanoramaSearch) ──
    _print_causal_chain(result)

    # ── 一致预期对比 ──
    _print_consensus_comparison(result)

    # ── 结论 ──
    _print_conclusion(result)

    print(f"\n{'='*60}")
    print(f"  ⚠️ 免责声明: 以上测算基于公开数据+模型假设，仅供参考")
    print(f"     实际业绩可能因公司会计处理、非经常性损益等因素产生偏差")
    print(f"     不构成投资建议")
    print(f"{'='*60}\n")


# ── 子模块 ──────────────────────────────────────────────────────────────


def _print_data_quality(
    result: EarningsPreviewResult, basket: Optional[LithiumBasket]
) -> None:
    """输出数据质量部分。"""
    print(f"\n  📋 数据质量")
    print(f"  {HR}")
    print(f"  数据置信度: {result.confidence:.0%}")
    print(f"  主数据源:   {result.source_summary or '参考数据'}")

    if b := basket:
        print(f"  Q2数据点:   {b.data_points_q2}个")
        print(f"  Q2加权均价: {_fmt_price(b.q2_basket_price)} 元/吨")
        qoq = b.qoq_price_change_pct
        if qoq is not None:
            direction = "↑" if qoq > 0 else "↓"
            print(f"  Q2 vs Q1:   {direction} {abs(qoq):.1f}%")

    if result.data_warnings:
        print(f"\n  ⚠️ 数据警告:")
        for w in result.data_warnings:
            print(f"     {w}")


def _print_leading_indicators(basket: Optional[LithiumBasket]) -> None:
    """输出先行指标概览。"""
    if not basket:
        return

    print(f"\n  🔍 先行指标 (Q1 vs Q2)")
    print(f"  {HR}")

    print(
        f"  {'指标':<20} {'Q1均价':>12} {'Q2均价':>12} {'变化':>10}"
    )
    print(f"  {'-'*54}")

    _print_row(
        "电池级碳酸锂",
        basket.carbonate_q1_avg,
        basket.carbonate_q2_avg,
        "元/吨",
    )
    _print_row(
        "电池级氢氧化锂",
        basket.hydroxide_q1_avg,
        basket.hydroxide_q2_avg,
        "元/吨",
    )
    _print_row(
        "加权均价",
        basket.q1_basket_price,
        basket.q2_basket_price,
        "元/吨",
    )
    _print_row(
        "锂精矿CFR(6%Li₂O)",
        basket.spodumene_q1_avg,
        basket.spodumene_q2_avg,
        "USD/吨",
    )

    gm = basket.estimated_unit_gross_margin
    if gm is not None:
        print(f"  {'':20} {'':>12} {'估算单位毛利':>12} {gm:>10.0f} 元/吨")


def _print_row(
    label: str, q1: Optional[float], q2: Optional[float], unit: str
) -> None:
    """输出一行对比数据。"""
    q1_str = f"{q1:,.0f}" if q1 else "N/A"
    q2_str = f"{q2:,.0f}" if q2 else "N/A"
    if q1 and q2 and q1 > 0:
        chg = (q2 - q1) / q1 * 100
        chg_str = f"{chg:+.1f}%"
    else:
        chg_str = "N/A"
    print(f"  {label:<20} {q1_str:>12} {q2_str:>12} {chg_str:>10}")


def _print_earnings_estimate(result: EarningsPreviewResult) -> None:
    """输出Q2业绩测算。"""
    print(f"\n  💰 Q2 业绩测算")
    print(f"  {HR}")

    print(f"  Q1 归母净利 (已知):     {result.q1_net_profit:>8.1f} 亿")
    print(f"  {'-'*42}")
    print(
        f"  Q2 锂盐毛利 (测算):     {result.q2_lithium_gross_profit:>8.1f} 亿"
    )
    print(
        f"  Q2 电池利润 (测算):     {result.q2_battery_profit:>8.1f} 亿"
    )
    print(f"  {'-'*42}")
    print(
        f"  Q2 归母净利 (基准):     {result.q2_net_profit_estimate:>8.1f} 亿"
    )

    direction = "增长" if result.qoq_change_pct > 0 else "下降"
    emoji = "📈" if result.qoq_change_pct > 0 else "📉"
    print(
        f"  QoQ 环比:               {emoji} {direction} {abs(result.qoq_change_pct):.1f}%"
    )


def _print_sensitivity_summary(result: EarningsPreviewResult) -> None:
    """输出敏感性分析摘要。"""
    print(f"\n  🎯 敏感性分析")
    print(f"  {HR}")
    print(f"  🟢 乐观 (锂价+10%):      {result.bull_case:>8.1f} 亿")
    print(f"  🟡 基准:                  {result.base_case:>8.1f} 亿")
    print(f"  🔴 悲观 (锂价-10%):      {result.bear_case:>8.1f} 亿")
    print(f"  利润弹性区间:             [{result.bear_case:.1f} ~ {result.bull_case:.1f}] 亿")


def _print_sensitivity(table: list[dict]) -> None:
    """输出敏感性分析矩阵。"""
    if not table:
        return

    print(f"\n  🎯 敏感性分析矩阵 (Q2归母净利, 亿元)")
    print(f"  {HR}")

    price_labels = ["-15%", "-7%", "基准", "+7%", "+15%"]
    header = f"  {'出货量':>8}"
    for pl in price_labels:
        header += f" {'锂价'+pl:>10}"
    print(header)
    print(f"  {'-'*60}")

    for row in table:
        vol = row["volume_ratio"]
        line = f"  {vol:>8}"
        for pl in ["85%", "93%", "100%", "107%", "115%"]:
            key = f"price_{pl}"
            val = row.get(key, "N/A")
            line += f" {val:>10}"
        print(line)

    # 标注基准情形
    base = table[len(table) // 2]  # 中间行=基准出货量
    base_val = base.get("price_100%", "N/A")
    print(f"\n  基准情形 (出货量100%, 锂价100%): {base_val} 亿")


def _print_causal_chain(result: EarningsPreviewResult) -> None:
    """输出因果传导链 — 从碳酸锂价格到Q2归母净利的弹性传导。

    借鉴 MiroFish PanoramaSearch 的信息传播拓扑追踪思路。
    """
    chain = result.causal_chain
    if not chain:
        return

    print(f"\n  🔗 因果传导链 (借鉴 MiroFish PanoramaSearch)")
    print(f"  {HR}")
    print(f"  碳酸锂现货价每变动 ±1%，对下游各节点的弹性传导:")

    # 找最大弹性确定比例尺
    max_el = max((n.elasticity_to_price for n in chain), default=1.0)

    for i, node in enumerate(chain):
        indent = "  "
        # 弹性条 (最多40字符宽)
        bar_width = int(node.elasticity_to_price / max_el * 30) if max_el > 0 else 0
        bar = "█" * min(bar_width, 40)

        # 节点图标
        if node.is_root:
            icon = "⚡"
        elif node.is_leaf:
            icon = "🎯"
        else:
            icon = "  "

        # 格式化值
        if node.unit == "元/吨":
            val_str = f"{node.value:,.0f}"
        elif node.unit == "亿":
            val_str = f"{node.value:.1f}"
        else:
            val_str = f"{node.value:,.0f}"

        # 弹性系数
        if node.is_root:
            ela_str = "基准 (1.00x)"
        else:
            ela_str = f"{node.elasticity_to_price:.2f}x 杠杆"

        print(f"{indent}{icon} {node.step_name}")
        print(f"{indent}   ├─ 值: {val_str} {node.unit}")
        print(f"{indent}   ├─ 计算: {node.formula}")
        print(f"{indent}   └─ 弹性: {bar} {ela_str}")

        # 节点间连线
        if i < len(chain) - 1:
            print(f"{indent}   │")
            print(f"{indent}   ▼")

    # 总结
    leaf = chain[-1] if chain else None
    if leaf and leaf.elasticity_to_price > 1.0:
        amp = leaf.elasticity_to_price
        print(f"\n  💡 经营杠杆效应: 碳酸锂价格每变动 ±1%，")
        print(f"     Q2归母净利变动约 ±{amp:.1f}% (放大 {amp:.1f}x)")
        print(f"     原因: 固定成本不随价格变动，利润弹性天然大于收入弹性")


def _print_consensus_comparison(result: EarningsPreviewResult) -> None:
    """输出一致预期对比。"""
    if result.consensus_q2_profit is None:
        return

    print(f"\n  📈 vs 机构一致预期")
    print(f"  {HR}")
    print(f"  一致预期 Q2 净利:       {result.consensus_q2_profit:>8.1f} 亿")
    print(
        f"  模型测算 Q2 净利:       {result.q2_net_profit_estimate:>8.1f} 亿"
    )

    if result.beat_miss_pct is not None:
        if result.beat_miss_pct > 0:
            emoji = "🟢 Beat"
        else:
            emoji = "🔴 Miss"
        print(
            f"  偏差:                    {emoji} {result.beat_miss_pct:+.1f}%"
        )


def _print_conclusion(result: EarningsPreviewResult) -> None:
    """输出结论。"""
    print(f"\n  🧠 研判结论")
    print(f"  {HR_THICK}")
    print(f"  {result.summary}")

    # 置信度判定
    if result.confidence >= 0.85:
        conf_level = "高置信度 — 测算结果可作为仓位决策参考"
    elif result.confidence >= 0.65:
        conf_level = "中等置信度 — 需结合更多信息综合判断"
    else:
        conf_level = "低置信度 — 建议等待更多数据点后再决策"

    print(f"  置信度: {result.confidence:.0%} — {conf_level}")

    # 关键假设提示
    print(f"\n  ⚠️ 关键假设:")
    print(f"     • 赣锋Q2锂盐出货量约5.5万吨LCE (基于公司指引)")
    print(f"     • 资源自供率约70%，自有矿成本约3.5万/吨")
    print(f"     • 锂精矿CFR均价约1000-1100 USD/吨")
    print(f"     • 电池业务单Wh净利约0.025元")
    print(f"     • 以上假设变动5%，测算结果约变动±8-12%")


# ── 工具 ────────────────────────────────────────────────────────────────


def _fmt_price(price: Optional[float]) -> str:
    """格式化价格显示。"""
    if price is None:
        return "N/A"
    if price >= 10000:
        return f"{price/10000:.2f}万"
    return f"{price:,.0f}"
