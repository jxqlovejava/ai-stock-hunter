# -*- coding: utf-8 -*-
"""金融数据格式化器 — 将 sub_tools 返回的 dict/list 渲染为可读文本。

支持两种输出模式:
  - rich.table:  终端彩色表格 (默认)
  - markdown:    纯文本 Markdown 表格 (用于消息/日志)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

try:
    from rich.console import Console
    from rich.table import Table as RichTable

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# ---------------------------------------------------------------------------
# 通用表格渲染
# ---------------------------------------------------------------------------


def format_to_table(
    data: list[dict[str, Any]],
    headers: list[str] | None = None,
    title: str = "",
    use_rich: bool = True,
) -> str:
    """通用表格格式化器。

    自动从 data[0] 的键推断列名，支持 rich 和 markdown 两种模式。

    Args:
        data:    dict 列表，每个 dict 为一行
        headers: 指定列名和顺序，None 时用 data[0].keys()
        title:   表格标题
        use_rich: 是否用 rich 渲染 (否则 markdown)

    Returns:
        格式化后的字符串
    """
    if not data:
        return f"**{title}**\n\n*(无数据)*" if title else "*(无数据)*"

    cols = headers or list(data[0].keys())
    if use_rich and _HAS_RICH:
        return _render_rich_table(data, cols, title)
    return _render_markdown_table(data, cols, title)


# ---------------------------------------------------------------------------
# 财务三表格式化
# ---------------------------------------------------------------------------


def format_income_statement(data: list[dict[str, Any]]) -> str:
    """利润表格式化。"""
    headers = [
        "报告期", "营业总收入", "营业总成本", "营业利润",
        "净利润", "归母净利润", "扣非净利润", "基本每股收益",
    ]
    return format_to_table(data, headers, title="利润表")


def format_balance_sheet(data: list[dict[str, Any]]) -> str:
    """资产负债表格式化。"""
    headers = [
        "报告期", "资产总计", "流动资产合计", "货币资金", "应收账款",
        "存货", "固定资产", "负债合计", "流动负债合计", "所有者权益合计",
    ]
    return format_to_table(data, headers, title="资产负债表")


def format_cash_flow(data: list[dict[str, Any]]) -> str:
    """现金流量表格式化。"""
    headers = [
        "报告期",
        "经营活动现金流净额",
        "投资活动现金流净额",
        "筹资活动现金流净额",
        "现金及等价物净增加额",
    ]
    return format_to_table(data, headers, title="现金流量表")


def format_key_ratios(data: dict[str, Any]) -> str:
    """关键比率格式化。返回 key: value 对齐文本。"""
    if not data:
        return "*(无数据)*"

    # 分类展示
    lines: list[str] = []
    lines.append("## 关键比率")
    lines.append("")

    sections = {
        "估值指标": ["pe_ttm", "pb", "market_cap", "dividend_yield"],
        "行情": ["price", "change_pct"],
        "盈利能力": ["roe", "roa", "gross_margin", "net_margin"],
        "成长能力": ["revenue", "net_profit", "revenue_growth", "profit_growth"],
        "财务健康": ["debt_to_equity", "current_ratio", "operating_cash_flow"],
        "每股指标": ["eps", "bvps"],
    }

    labels = {
        "pe_ttm": "市盈率 (PE TTM)",
        "pb": "市净率 (PB)",
        "market_cap": "总市值",
        "dividend_yield": "股息率",
        "price": "最新价",
        "change_pct": "涨跌幅",
        "roe": "净资产收益率 (ROE)",
        "roa": "总资产收益率 (ROA)",
        "gross_margin": "毛利率",
        "net_margin": "净利率",
        "revenue": "营业收入",
        "net_profit": "归母净利润",
        "revenue_growth": "营收增长率 (YoY)",
        "profit_growth": "净利润增长率 (YoY)",
        "debt_to_equity": "资产负债率",
        "current_ratio": "流动比率",
        "operating_cash_flow": "经营活动现金流",
        "eps": "每股收益 (EPS)",
        "bvps": "每股净资产 (BVPS)",
    }

    _fmt_val = _format_value
    for section_name, keys in sections.items():
        section_lines: list[str] = []
        for k in keys:
            v = data.get(k)
            if v is not None and v != "":
                label = labels.get(k, k)
                section_lines.append(f"  **{label}**: {_fmt_val(k, v)}")

        if section_lines:
            lines.append(f"### {section_name}")
            lines.extend(section_lines)
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 对比格式化
# ---------------------------------------------------------------------------


def format_comparison(
    data_a: dict[str, Any],
    data_b: dict[str, Any],
    metric: str = "",
) -> str:
    """双股票关键指标侧栏对比。

    Args:
        data_a: 股票 A 的 dict (含 name 字段)
        data_b: 股票 B 的 dict
        metric: 限定对比指标 (空则对比全部)

    Returns:
        markdown 对比表格
    """
    name_a = data_a.get("name", data_a.get("symbol", "A"))
    name_b = data_b.get("name", data_b.get("symbol", "B"))

    # 收集所有共有指标
    all_keys = sorted(set(data_a.keys()) & set(data_b.keys()))
    # 排除非数值字段
    skip_keys = {"symbol", "name", "error"}
    compare_keys = [k for k in all_keys if k not in skip_keys]

    # 可读标签
    labels = {
        "pe_ttm": "市盈率 (PE TTM)",
        "pb": "市净率 (PB)",
        "market_cap": "总市值 (亿)",
        "roe": "ROE (%)",
        "eps": "EPS (元)",
        "revenue": "营业收入 (亿)",
        "net_profit": "净利润 (亿)",
        "revenue_growth": "营收增长 (%)",
        "profit_growth": "净利润增长 (%)",
        "debt_to_equity": "资产负债率 (%)",
        "gross_margin": "毛利率 (%)",
        "price": "最新价",
        "change_pct": "涨跌幅",
        "dividend_yield": "股息率",
        "operating_cash_flow": "经营现金流 (亿)",
    }

    if metric:
        metric_lower = metric.lower().replace(" ", "_")
        # 尝试匹配
        matched = [k for k in compare_keys if metric_lower in k.lower()]
        if matched:
            compare_keys = matched
        else:
            return f"指标 '{metric}' 未找到。可选指标: {', '.join(compare_keys[:15])}"

    lines: list[str] = []
    lines.append(f"## 对比: {name_a} vs {name_b}")
    lines.append("")
    lines.append(f"| 指标 | {name_a} | {name_b} | 差异 |")
    lines.append("|------|----------|----------|------|")

    for k in compare_keys:
        va = data_a.get(k)
        vb = data_b.get(k)
        label = labels.get(k, k)
        fva = _fmt_val(k, va) if va is not None else "-"
        fvb = _fmt_val(k, vb) if vb is not None else "-"

        # 差异计算 (数值型)
        diff = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and vb != 0:
            if va != 0 and vb != 0:
                diff_pct = abs((va - vb) / max(abs(va), abs(vb)) * 100)
                direction = "A 高" if va > vb else "B 高"
                diff = f"{diff_pct:.1f}% ({direction})"

        lines.append(f"| {label} | {fva} | {fvb} | {diff} |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 通用 Markdown 表格渲染 (fallback)
# ---------------------------------------------------------------------------


def _render_markdown_table(
    data: list[dict[str, Any]],
    cols: list[str],
    title: str = "",
) -> str:
    """渲染 Markdown 表格。"""
    lines: list[str] = []
    if title:
        lines.append(f"## {title}")
        lines.append("")

    # 表头
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines.append(header)
    lines.append(sep)

    for row in data:
        vals = []
        for c in cols:
            v = row.get(c)
            vals.append(_fmt_val(c, v) if v is not None else "-")
        lines.append("| " + " | ".join(vals) + " |")

    lines.append("")
    return "\n".join(lines)


def _render_rich_table(
    data: list[dict[str, Any]],
    cols: list[str],
    title: str = "",
) -> str:
    """渲染 Rich 彩色表格 (终端)。"""
    table = RichTable(title=title, title_style="bold", border_style="blue")
    for c in cols:
        table.add_column(c, overflow="fold")

    for row in data:
        vals = [_fmt_val(c, row.get(c)) if row.get(c) is not None else "-" for c in cols]
        table.add_row(*vals)

    console = Console(width=120, record=True)
    console.print(table)
    return console.export_text(styles=False)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _fmt_val(key: str, v: Any) -> str:
    """格式化单个值为可读字符串。"""
    if v is None:
        return "-"

    # 金额类: 转亿
    money_keys = {
        "营业总收入", "营业总成本", "营业利润", "利润总额", "净利润",
        "归母净利润", "扣非净利润",
        "资产总计", "流动资产合计", "货币资金", "应收账款", "存货",
        "固定资产", "负债合计", "流动负债合计", "所有者权益合计",
        "经营活动现金流净额", "投资活动现金流净额", "筹资活动现金流净额",
        "现金及等价物净增加额",
        "revenue", "net_profit", "operating_cash_flow",
        "market_cap", "turnover", "total_assets", "total_liabilities",
    }
    if key in money_keys and isinstance(v, (int, float)):
        if abs(v) >= 1e8:
            return f"{v / 1e8:.2f}亿"
        if abs(v) >= 1e4:
            return f"{v / 1e4:.2f}万"
        return f"{v:.2f}"

    # 百分比类
    pct_keys = {
        "涨跌幅", "change_pct",
        "净资产收益率", "毛利率", "净利率",
        "roe", "roa", "gross_margin", "net_margin",
        "revenue_growth", "profit_growth",
        "dividend_yield",
        "debt_to_equity",
    }
    if key in pct_keys and isinstance(v, (int, float)):
        return f"{v:.2f}%"

    # 每股收益
    if key in ("eps", "基本每股收益", "bvps") and isinstance(v, (int, float)):
        return f"{v:.4f}"

    # 市盈率/市净率等纯数字
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, int) and v > 10000:
        return f"{v:,}"

    return str(v)


def _format_value(key: str, v: Any) -> str:
    """format_comparison 等函数使用的格式化器 (与 _fmt_val 同逻辑，暴露为别名)。"""
    return _fmt_val(key, v)
