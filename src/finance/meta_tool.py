# -*- coding: utf-8 -*-
"""MetaTool — 自然语言 → 数据查询 → 格式化输出的元工具路由器。

基于 Dexter 模式：parse → dispatch → format，全程无 LLM，仅靠关键词匹配 + 正则。

支持的 NL 模式:
  - "营收/利润/现金流 [股票名/代码] [年份数]"  → 财务数据查询
  - "对比 [A] vs [B] [指标]"                    → 双股对比
  - "关键比率 [股票名] [年份]"                   → 关键财务比率
  - "K线 [股票名] [周期]"                        → 历史 K 线
  - "新闻 [股票名] [条数]"                       → 公司新闻
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import formatters, sub_tools

# 周期映射
_PERIOD_MAP: dict[str, str] = {
    "日": "daily", "daily": "daily", "天": "daily",
    "周": "weekly", "week": "weekly", "weekly": "weekly",
    "月": "monthly", "month": "monthly", "monthly": "monthly",
}


class MetaTool:
    """NL 驱动的金融数据元工具。

    使用示例:
        mt = MetaTool()
        print(mt.execute("营收 600519 3"))
        print(mt.execute("对比 600519 vs 000858 营收"))
        print(mt.execute("关键比率 600519"))
        print(mt.execute("K线 600519 周"))
        print(mt.execute("新闻 600519 5"))
    """

    def parse_query(self, query: str) -> dict[str, Any]:
        """解析自然语言查询，返回结构化指令。

        Args:
            query: 自然语言查询字符串

        Returns:
            dict 含:
              - tool_name:  子工具名 (income/balance/cashflow/compare/ratios/kline/news)
              - params:     参数字典
              - raw_text:   原始查询 (调试用)
        """
        q = query.strip()

        # ── 模式 1: 对比 (compare / 对比 / vs) ──────────────────────────
        m = re.search(
            r"(?:对比|compare|vs)\s+"
            r"([\w.]+)\s*(?:vs|vs\.|与|和|/)?\s*([\w.]+)"
            r"(?:\s+(.+))?",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "compare",
                "params": {
                    "symbol_a": m.group(1),
                    "symbol_b": m.group(2),
                    "metric": (m.group(3) or "").strip(),
                },
                "raw_text": q,
            }

        # ── 模式 2: 营收/利润/现金流 (单项财务) ─────────────────────
        m = re.search(
            r"(?:营收|收入|利润|现金流|财务|income|revenue|profit|cash)\s*"
            r"([\w.]+)"
            r"(?:\s+(\d+))?",
            q,
            re.IGNORECASE,
        )
        if m:
            params: dict[str, Any] = {
                "symbol": m.group(1),
                "period": "annual",
                "limit": int(m.group(2)) if m.group(2) else 3,
            }
            # 细化财务表类型
            tool = "income"
            if re.search(r"现金|cash.?flow", q, re.IGNORECASE):
                tool = "cashflow"
            elif re.search(r"资产|负债|balance", q, re.IGNORECASE):
                tool = "balance"
            return {"tool_name": tool, "params": params, "raw_text": q}

        # ── 模式 3: 关键比率 / 财务比率 / key ratios ───────────────────
        m = re.search(
            r"(?:关键比率|财务比率|key.?ratios?|指标)\s*([\w.]+)",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "ratios",
                "params": {"symbol": m.group(1)},
                "raw_text": q,
            }

        # ── 模式 4: K线 / kline / 行情 ──────────────────────────────
        m = re.search(
            r"(?:K线|kline|k_line|行情|走势)\s*([\w.]+)"
            r"(?:\s+(日|周|月|daily|weekly|monthly|天))?",
            q,
            re.IGNORECASE,
        )
        if m:
            period_str = m.group(2) or "daily"
            period = _PERIOD_MAP.get(period_str.lower(), "daily")
            return {
                "tool_name": "kline",
                "params": {
                    "symbol": m.group(1),
                    "period": period,
                    "limit": 20,
                },
                "raw_text": q,
            }

        # ── 模式 5: 新闻 / news / 资讯 ──────────────────────────────
        m = re.search(
            r"(?:新闻|news|资讯|公告|消息)\s*([\w.]+)"
            r"(?:\s+(\d+))?",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "news",
                "params": {
                    "symbol": m.group(1),
                    "limit": int(m.group(2)) if m.group(2) else 5,
                },
                "raw_text": q,
            }

        # ── 模式 6: 价格 / price / 实时行情 ──────────────────────────
        m = re.search(
            r"(?:价格|price|行情|报价|实时)\s*([\w.]+)",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "price",
                "params": {"symbol": m.group(1)},
                "raw_text": q,
            }

        # ── 模式 7: 北向 / northbound / 北向资金 ─────────────────────
        m = re.search(
            r"(?:北向|northbound|外资)\s*([\w.]+)",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "northbound",
                "params": {"symbol": m.group(1)},
                "raw_text": q,
            }

        # ── 模式 8: 融资融券 / margin ───────────────────────────────
        m = re.search(
            r"(?:融资融券|两融|margin|杠杆)\s*([\w.]+)",
            q,
            re.IGNORECASE,
        )
        if m:
            return {
                "tool_name": "margin",
                "params": {"symbol": m.group(1)},
                "raw_text": q,
            }

        # ── 未匹配 ────────────────────────────────────────────────
        return {
            "tool_name": "unknown",
            "params": {"raw_query": q},
            "raw_text": q,
        }

    def execute(self, query: str) -> str:
        """执行自然语言查询，返回格式化结果。

        Args:
            query: 自然语言查询字符串

        Returns:
            格式化后的文本 (markdown 表格，终端就绪)
        """
        parsed = self.parse_query(query)
        tool = parsed["tool_name"]
        params = parsed["params"]

        dispatch = {
            "income": self._exec_income,
            "balance": self._exec_balance,
            "cashflow": self._exec_cashflow,
            "compare": self._exec_compare,
            "ratios": self._exec_ratios,
            "kline": self._exec_kline,
            "news": self._exec_news,
            "price": self._exec_price,
            "northbound": self._exec_northbound,
            "margin": self._exec_margin,
        }

        handler = dispatch.get(tool)
        if handler is None:
            return self._format_help(parsed["raw_text"])

        try:
            return handler(**params)
        except Exception as exc:
            return f"**查询出错**: {exc}\n\n请检查股票代码或查询格式。使用 `元工具 帮助` 查看支持的模式。"

    # ------------------------------------------------------------------
    # 执行器
    # ------------------------------------------------------------------

    def _exec_income(self, symbol: str, period: str = "annual", limit: int = 3) -> str:
        """利润表查询。"""
        data = sub_tools.get_income_statements(symbol, period, limit)
        if not data:
            return f"未获取到 {symbol} 的利润表数据。"
        return formatters.format_income_statement(data)

    def _exec_balance(self, symbol: str, period: str = "annual", limit: int = 3) -> str:
        """资产负债表查询。"""
        data = sub_tools.get_balance_sheets(symbol, period, limit)
        if not data:
            return f"未获取到 {symbol} 的资产负债表数据。"
        return formatters.format_balance_sheet(data)

    def _exec_cashflow(self, symbol: str, period: str = "annual", limit: int = 3) -> str:
        """现金流量表查询。"""
        data = sub_tools.get_cash_flows(symbol, period, limit)
        if not data:
            return f"未获取到 {symbol} 的现金流量表数据。"
        return formatters.format_cash_flow(data)

    def _exec_compare(
        self, symbol_a: str, symbol_b: str, metric: str = ""
    ) -> str:
        """双股对比。"""
        data_a = self._get_compare_dict(symbol_a)
        data_b = self._get_compare_dict(symbol_b)

        if "error" in data_a:
            return f"股票 {symbol_a} 数据获取失败: {data_a['error']}"
        if "error" in data_b:
            return f"股票 {symbol_b} 数据获取失败: {data_b['error']}"

        return formatters.format_comparison(data_a, data_b, metric)

    def _exec_ratios(self, symbol: str) -> str:
        """关键比率查询。"""
        data = sub_tools.get_key_ratios(symbol)
        if not data:
            return f"未获取到 {symbol} 的财务比率数据。"
        return formatters.format_key_ratios(data)

    def _exec_kline(self, symbol: str, period: str = "daily", limit: int = 20) -> str:
        """K 线查询。"""
        data = sub_tools.get_kline(symbol, period, limit)
        if not data:
            return f"未获取到 {symbol} 的 K 线数据。"
        headers = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]
        period_label = {"daily": "日", "weekly": "周", "monthly": "月"}.get(period, period)
        return formatters.format_to_table(data, headers, title=f"{symbol} {period_label}K线")

    def _exec_news(self, symbol: str, limit: int = 5) -> str:
        """新闻查询。"""
        data = sub_tools.get_company_news(symbol, limit)
        if not data:
            return f"未找到 {symbol} 的相关新闻。"
        lines: list[str] = [f"## {symbol} 最新资讯 ({len(data)} 条)", ""]
        for i, item in enumerate(data, 1):
            lines.append(f"### {i}. {item['title']}")
            lines.append(f"   来源: {item.get('source', '-')}  日期: {item.get('date', '-')}")
            if item.get("content"):
                lines.append(f"   {item['content'][:150]}...")
            if item.get("url"):
                lines.append(f"   [原文链接]({item['url']})")
            lines.append("")
        return "\n".join(lines)

    def _exec_price(self, symbol: str) -> str:
        """实时行情。"""
        data = sub_tools.get_stock_price(symbol)
        if "error" in data:
            return f"未获取到 {symbol} 的行情数据。"
        name = data.get("name", symbol)
        price = data.get("price", "-")
        change = data.get("change_pct")
        change_str = f"{change:+.2f}%" if change is not None else "-"
        pe = data.get("pe_ttm")
        pb = data.get("pb")
        mc = data.get("market_cap")
        mc_str = f"{mc / 1e8:.2f}亿" if mc else "-"

        lines = [
            f"## {name} ({symbol})",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 最新价 | {price} |",
            f"| 涨跌幅 | {change_str} |",
            f"| 市盈率 | {pe if pe is not None else '-'} |",
            f"| 市净率 | {pb if pb is not None else '-'} |",
            f"| 总市值 | {mc_str} |",
            "",
        ]
        return "\n".join(lines)

    def _exec_northbound(self, symbol: str) -> str:
        """北向资金。"""
        data = sub_tools.get_northbound_flow(symbol)
        if "error" in data:
            return f"**{data['error']}**"
        lines = [f"## {symbol} 北向资金数据", ""]
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        for k, v in data.items():
            if v is not None:
                lines.append(f"| {k} | {v} |")
        lines.append("")
        return "\n".join(lines)

    def _exec_margin(self, symbol: str) -> str:
        """融资融券。"""
        data = sub_tools.get_margin_data(symbol)
        if "error" in data:
            return f"**{data['error']}**"
        lines = [f"## {symbol} 融资融券数据", ""]
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        for k, v in data.items():
            if v is not None and str(v) not in ("", "nan"):
                lines.append(f"| {k} | {v} |")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _get_compare_dict(self, symbol: str) -> dict[str, Any]:
        """获取对比所用完整数据字典。"""
        code = sub_tools.normalize_symbol(symbol)
        result: dict[str, Any] = {"symbol": code}

        # 名称
        agg = sub_tools._get_agg()
        market = sub_tools.detect_market(symbol)
        quote = agg.get_quote(code, market)
        if quote:
            result["name"] = quote.name

        # 比率
        ratios = sub_tools.get_key_ratios(symbol)
        result.update(ratios)
        return result

    def _format_help(self, raw: str) -> str:
        """返回帮助信息。"""
        lines = [
            "## MetaTool 支持的自然语言模式",
            "",
            "| 模式 | 示例 |",
            "|------|------|",
            "| 财务查询 (营收/利润/现金流) | `营收 600519 3`, `现金流 000858` |",
            "| 对比 | `对比 600519 vs 000858`, `对比 600519 vs 000858 营收` |",
            "| 关键比率 | `关键比率 600519`, `财务比率 600519` |",
            "| K线查询 | `K线 600519 日`, `K线 600519 周` |",
            "| 新闻资讯 | `新闻 600519 5`, `资讯 600519` |",
            "| 实时行情 | `价格 600519`, `行情 600519` |",
            "| 北向资金 | `北向 600519`, `外资 600519` |",
            "| 融资融券 | `融资融券 600519`, `margin 600519` |",
            "",
            "*股票代码支持 6 位数字、带前缀 (SH600519) 或带后缀 (600519.SH)*",
        ]
        return "\n".join(lines)
