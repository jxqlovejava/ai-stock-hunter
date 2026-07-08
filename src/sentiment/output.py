# -*- coding: utf-8 -*-
"""情绪信号格式化输出 — Rich 表格和颜色编码。"""

from __future__ import annotations

from src.sentiment.signals import MarketSentiment, SentimentLevel


def format_sentiment_report(sentiment: MarketSentiment) -> str:
    """格式化情绪分析报告为 Rich 终端输出。

    调用方需要先安装 rich: from rich.console import Console; console = Console()
    然后传入 sentiment 对象，此函数返回可被 console.print() 渲染的内容。
    """
    level_emoji, level_color = _level_style(sentiment.level)

    lines: list[str] = []
    lines.append("")
    lines.append(f"  {level_emoji}  市场情绪: {sentiment.level.value}   |   评分: {sentiment.score}/100   |   置信度: {sentiment.confidence:.0%}")
    lines.append(f"  {'─' * 60}")
    lines.append(f"  {sentiment.summary}")
    lines.append("")

    # ---- 指标明细表 ----
    if sentiment.indicators:
        lines.append("  📊 情绪指标明细")
        lines.append(f"  {'─' * 70}")
        lines.append(f"  {'指标':<12} {'当前值':>10} {'单位':<6} {'信号':<14} {'说明'}")
        lines.append(f"  {'─' * 70}")
        for ind in sentiment.indicators:
            signal_icon = _signal_icon(ind.signal)
            val_str = _fmt_value(ind.current_value)
            lines.append(
                f"  {ind.name:<12} {val_str:>10} {ind.unit:<6} {signal_icon:<14} {ind.description}"
            )
        lines.append(f"  {'─' * 70}")

    # ---- 触发信号 ----
    if sentiment.extreme_signals:
        lines.append("")
        lines.append("  🔴 极端信号:")
        for s in sentiment.extreme_signals:
            lines.append(f"     • {s}")

    if sentiment.panic_signals:
        lines.append("")
        lines.append("  🟠 恐慌信号:")
        for s in sentiment.panic_signals:
            lines.append(f"     • {s}")

    if sentiment.greed_signals:
        lines.append("")
        lines.append("  🟢 贪婪信号:")
        for s in sentiment.greed_signals:
            lines.append(f"     • {s}")

    # ---- 恐慌套利建议 ----
    if sentiment.panic_arb_advice:
        lines.append("")
        lines.append("  🎯 恐慌套利建议")
        lines.append(f"  {'─' * 60}")
        for line in sentiment.panic_arb_advice.split("\n"):
            lines.append(f"  {line}")

    # ---- 数据质量 ----
    if sentiment.data_errors:
        lines.append("")
        lines.append(f"  ⚠️ 数据获取问题 ({len(sentiment.data_errors)} 项):")
        for err in sentiment.data_errors:
            lines.append(f"     • [DATA_GAP] {err}")

    # ---- 时间戳 ----
    lines.append("")
    lines.append(f"  🕐 {sentiment.timestamp[:19]}")

    return "\n".join(lines)


def format_sentiment_plain(sentiment: MarketSentiment) -> str:
    """纯文本版本 — 不依赖 Rich 库。"""
    level_emoji, _ = _level_style(sentiment.level)

    lines: list[str] = []
    lines.append("")
    lines.append(f"  {level_emoji} 市场情绪: {sentiment.level.value}  |  评分: {sentiment.score}/100  |  置信度: {sentiment.confidence:.0%}")
    lines.append(f"  {'─' * 60}")
    lines.append(f"  {sentiment.summary}")
    lines.append("")

    if sentiment.indicators:
        lines.append("  📊 情绪指标明细:")
        for ind in sentiment.indicators:
            sig = _signal_icon(ind.signal)
            lines.append(f"    {ind.name}: {_fmt_value(ind.current_value)}{ind.unit} {sig} — {ind.description}")

    if sentiment.extreme_signals:
        lines.append("")
        lines.append("  🔴 极端信号:")
        for s in sentiment.extreme_signals:
            lines.append(f"    • {s}")

    if sentiment.panic_signals:
        lines.append("")
        lines.append("  🟠 恐慌信号:")
        for s in sentiment.panic_signals:
            lines.append(f"    • {s}")

    if sentiment.greed_signals:
        lines.append("")
        lines.append("  🟢 贪婪信号:")
        for s in sentiment.greed_signals:
            lines.append(f"    • {s}")

    if sentiment.panic_arb_advice:
        lines.append("")
        lines.append("  🎯 恐慌套利建议:")
        for line in sentiment.panic_arb_advice.split("\n"):
            lines.append(f"  {line}")

    if sentiment.data_errors:
        lines.append("")
        lines.append(f"  ⚠️ 数据获取问题 ({len(sentiment.data_errors)} 项) — 结果可能不完整")

    lines.append("")
    lines.append(f"  🕐 {sentiment.timestamp[:19]}")
    return "\n".join(lines)


def format_sentiment_json(sentiment: MarketSentiment) -> dict:
    """JSON 格式 — 供 API / 程序化消费。"""
    return {
        "level": sentiment.level.value,
        "score": sentiment.score,
        "confidence": sentiment.confidence,
        "summary": sentiment.summary,
        "indicators": [
            {
                "name": ind.name,
                "en_name": ind.en_name,
                "value": ind.current_value,
                "unit": ind.unit,
                "signal": ind.signal,
                "description": ind.description,
                "source": ind.data_source,
            }
            for ind in sentiment.indicators
        ],
        "panic_signals": sentiment.panic_signals,
        "greed_signals": sentiment.greed_signals,
        "extreme_signals": sentiment.extreme_signals,
        "panic_arb_advice": sentiment.panic_arb_advice,
        "data_errors": sentiment.data_errors,
        "timestamp": sentiment.timestamp,
    }


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _level_style(level: SentimentLevel) -> tuple[str, str]:
    """情绪等级 → (emoji, 颜色名)。"""
    mapping = {
        SentimentLevel.EXTREME_PANIC: ("🔴", "red"),
        SentimentLevel.PANIC: ("🟠", "yellow"),
        SentimentLevel.NORMAL: ("⚪", "white"),
        SentimentLevel.GREED: ("🟡", "green"),
        SentimentLevel.EXTREME_GREED: ("🟢", "bright_green"),
    }
    return mapping.get(level, ("⚪", "white"))


def _signal_icon(signal: str) -> str:
    """信号字符串 → emoji 图标。"""
    icons = {
        "extreme_panic": "🔴🔴",
        "panic": "🔴",
        "normal": "⚪",
        "greed": "🟢",
        "extreme_greed": "🟢🟢",
    }
    return icons.get(signal, "⚪")


def _fmt_value(v: float) -> str:
    """格式化为人类可读的字符串。"""
    if abs(v) >= 1e8:
        return f"{v/1e8:.1f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.1f}万"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"
