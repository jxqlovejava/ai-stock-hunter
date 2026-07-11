# -*- coding: utf-8 -*-
"""快查 CLI 子进程封装。

调用全局安装的 `kuaicha` CLI 工具。
前置条件: `npm install -g kuaicha-agent-cli && kuaicha init --authorization <key>`
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Optional

from .schemas import (
    IWencaiResult,
    KuaichaBalanceSheet,
    KuaichaCashFlow,
    KuaichaIncomeStatement,
    ListedResult,
)

logger = logging.getLogger(__name__)

# iwencai 工具名 → 用途速查
IWENCAI_TOOLS: dict[str, str] = {
    "astock_selector": "A股条件选股",
    "astock_tech_analysis": "A股技术分析",
    "astock_finance": "A股财务分析",
    "dragon_tiger": "龙虎榜分析",
    "northbound_capital": "北向资金分析",
    "institution_research": "机构调研与评级",
    "astock_special": "A股特色市场",
    "fund_query": "基金查询",
    "bond_query": "债券与可转债查询",
    "futures_options": "期货与期权查询",
    "hkstock_quote": "港股行情查询",
    "us_global_market": "美股及海外市场",
    "neeq_market": "新三板行情",
    "index_etf": "指数与ETF查询",
    "forex_crypto": "外汇与数字货币",
    "macro_economy": "宏观经济分析",
    "asset_allocation": "资产配置策略",
    "industry_deep_analysis": "行业深度分析",
    "universal_finance": "金融数据通用查询",
}

LISTED_TOOLS: dict[str, str] = {
    "get_income_statement": "利润表",
    "get_balance_sheet": "资产负债表",
    "get_cash_flow": "现金流量表",
    "get_stock_ten_hold": "十大股东",
    "get_stock_ten_hold_float": "十大流通股东",
    "get_report_period": "十大股东报告期",
    "get_report_period_float": "十大流通股东报告期",
    "get_main_person_djg": "董监高信息",
    "get_audit_opinion": "审计意见",
}


class KuaichaClient:
    """快查 CLI 封装。

    Usage:
        client = KuaichaClient()
        fin = client.iwencai("astock_finance", "同花顺 最新 ROE 净利润")
        holders = client.listed("get_stock_ten_hold", orgid="T000025753")
    """

    _CLI: str = "kuaicha"

    def __init__(self) -> None:
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """检查 kuaicha CLI 是否可用。缓存结果。"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                [self._CLI, "check"],
                capture_output=True, text=True, timeout=15,
            )
            ok = "已配置" in result.stdout or "已配置" in result.stderr
            self._available = ok
            return ok
        except Exception:
            self._available = False
            return False

    # ------------------------------------------------------------------
    # iwencai — 自然语言查询
    # ------------------------------------------------------------------

    def iwencai(
        self,
        tool: str,
        query: str,
        domain: str = "stock",
        page: int = 1,
        limit: int = 10,
    ) -> Optional[IWencaiResult]:
        """调用 iwencai 工具。

        Args:
            tool: 工具后缀，如 "astock_finance", "dragon_tiger"
            query: 自然语言查询
            domain: 领域参数 (stock/fund/macro 等)
            page: 页码
            limit: 每页条数
        """
        if not self.health_check():
            logger.warning("Kuaicha CLI 不可用")
            return None

        full_tool = f"iwencai_{tool}"
        params = f"query={_shell_quote(query)}&domain={domain}&page={page}&limit={limit}"
        result = self._call(full_tool, params)
        if result is None:
            return None

        data = result.get("data", {})
        raw = data.get("list", data if isinstance(data, list) else [])
        if not isinstance(raw, list):
            raw = [raw]

        return IWencaiResult(
            tool_name=tool,
            query=query,
            raw_data=raw,
            total_count=len(raw),
        )

    # ------------------------------------------------------------------
    # listed — 结构化查询
    # ------------------------------------------------------------------

    def listed(
        self,
        tool: str,
        *,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        **extra,
    ) -> Optional[ListedResult]:
        """调用 listed 工具。

        Args:
            tool: 工具后缀，如 "get_income_statement"
            orgid/corp_name/creditcode: 企业标识 (三选一)
            **extra: 额外参数 (page, page_size, end_date, type 等)
        """
        if not self.health_check():
            logger.warning("Kuaicha CLI 不可用")
            return None

        full_tool = f"listed_{tool}"
        params_parts = []
        if orgid:
            params_parts.append(f"orgid={orgid}")
        if corp_name:
            params_parts.append(f"corp_name={_shell_quote(corp_name)}")
        if creditcode:
            params_parts.append(f"creditcode={creditcode}")
        for k, v in extra.items():
            params_parts.append(f"{k}={v}")
        params = "&".join(params_parts)

        result = self._call(full_tool, params)
        if result is None:
            return None

        data = result.get("data", {})
        if not isinstance(data, dict):
            data = {}
        raw = data.get("list", data if isinstance(data, list) else [])
        if not isinstance(raw, list):
            raw = [raw] if raw else []

        # 防御: 过滤掉非 dict 条目（Pydantic list[dict[str, Any]] 校验）
        safe_raw = [item for item in raw if isinstance(item, dict)]

        return ListedResult(
            tool_name=tool,
            params={"orgid": orgid, "corp_name": corp_name, "creditcode": creditcode, **extra},
            raw_data=safe_raw,
            total_count=len(safe_raw),
        )

    # ------------------------------------------------------------------
    # 便捷方法 — 财务三表
    # ------------------------------------------------------------------

    def get_income_statement(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        end_date: str = "",
        is_audited: str = "1",
        report_type: str = "HB",
        page: int = 1,
        page_size: int = 10,
    ) -> list[KuaichaIncomeStatement]:
        """获取利润表（标准化）。"""
        result = self.listed(
            "get_income_statement",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            end_date=end_date, is_audited=is_audited,
            type=report_type, page=page, page_size=page_size,
        )
        if not result or not result.raw_data:
            return []
        return [_parse_income_statement(row) for row in result.raw_data]

    def get_balance_sheet(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        end_date: str = "",
        is_audited: str = "1",
        report_type: str = "HB",
        page: int = 1,
        page_size: int = 10,
    ) -> list[KuaichaBalanceSheet]:
        """获取资产负债表（标准化）。"""
        result = self.listed(
            "get_balance_sheet",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            end_date=end_date, is_audited=is_audited,
            type=report_type, page=page, page_size=page_size,
        )
        if not result or not result.raw_data:
            return []
        return [_parse_balance_sheet(row) for row in result.raw_data]

    def get_cash_flow(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        end_date: str = "",
        is_audited: str = "1",
        report_type: str = "HB",
        page: int = 1,
        page_size: int = 10,
    ) -> list[KuaichaCashFlow]:
        """获取现金流量表（标准化）。"""
        result = self.listed(
            "get_cash_flow",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            end_date=end_date, is_audited=is_audited,
            type=report_type, page=page, page_size=page_size,
        )
        if not result or not result.raw_data:
            return []
        return [_parse_cash_flow(row) for row in result.raw_data]

    # ------------------------------------------------------------------
    # 便捷方法 — 股东/高管
    # ------------------------------------------------------------------

    def get_top_holders(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        enddate: str = "",
    ) -> list[dict[str, Any]]:
        """获取十大股东。"""
        result = self.listed(
            "get_stock_ten_hold",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            enddate=enddate,
        )
        return result.raw_data if result else []

    def get_top_float_holders(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        enddate: str = "",
    ) -> list[dict[str, Any]]:
        """获取十大流通股东。"""
        result = self.listed(
            "get_stock_ten_hold_float",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            enddate=enddate,
        )
        return result.raw_data if result else []

    def get_executives(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
        exec_type: str = "",
    ) -> list[dict[str, Any]]:
        """获取董监高信息。"""
        result = self.listed(
            "get_main_person_djg",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
            type=exec_type,
        )
        return result.raw_data if result else []

    def get_audit_opinion(
        self,
        orgid: str = "",
        corp_name: str = "",
        creditcode: str = "",
    ) -> list[dict[str, Any]]:
        """获取审计意见。"""
        result = self.listed(
            "get_audit_opinion",
            orgid=orgid, corp_name=corp_name, creditcode=creditcode,
        )
        return result.raw_data if result else []

    # ------------------------------------------------------------------
    # 便捷方法 — 选股/技术/机构
    # ------------------------------------------------------------------

    def stock_screener(self, query: str, limit: int = 20) -> Optional[IWencaiResult]:
        """A股条件选股。支持技术面+基本面多条件组合。"""
        return self.iwencai("astock_selector", query, limit=limit)

    def tech_analysis(self, symbol_or_name: str) -> Optional[IWencaiResult]:
        """A股技术面深度分析。"""
        return self.iwencai("astock_tech_analysis", symbol_or_name)

    def financial_analysis(self, symbol_or_name: str) -> Optional[IWencaiResult]:
        """A股财务数据深度查询。"""
        return self.iwencai("astock_finance", symbol_or_name)

    def dragon_tiger(self, query: str = "今日龙虎榜") -> Optional[IWencaiResult]:
        """龙虎榜查询。"""
        return self.iwencai("dragon_tiger", query)

    def northbound_flow(self, query: str = "北向资金动向") -> Optional[IWencaiResult]:
        """北向资金动向。"""
        return self.iwencai("northbound_capital", query)

    def institution_research(self, symbol_or_name: str) -> Optional[IWencaiResult]:
        """机构调研与评级。"""
        return self.iwencai("institution_research", symbol_or_name)

    def macro_indicators(self, query: str = "最新宏观数据") -> Optional[IWencaiResult]:
        """宏观经济指标查询。"""
        return self.iwencai("macro_economy", query, domain="macro")

    def industry_analysis(self, industry: str) -> Optional[IWencaiResult]:
        """行业深度分析。"""
        return self.iwencai("industry_deep_analysis", industry, domain="kuaicha")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call(self, tool_full: str, params: str) -> dict | None:
        """执行 kuaicha CLI 调用，自动解析表格/JSON 输出。"""
        cmd = [self._CLI, "tool", "call", tool_full, params]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "kuaicha call failed: tool=%s stderr=%s",
                    tool_full, result.stderr[:200],
                )
                return None
            return _parse_cli_output(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("kuaicha call timeout: tool=%s", tool_full)
            return None
        except Exception as e:
            logger.warning("kuaicha call error: tool=%s err=%s", tool_full, e)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shell_quote(s: str) -> str:
    """Shell 安全包装（简单实现）。"""
    return s.replace("'", "'\\''")


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码。"""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _parse_cli_output(text: str) -> dict | None:
    """解析 kuaicha CLI 输出：优先 JSON → 管道表格 → key-value 记录。"""
    clean = _strip_ansi(text)
    # 1. 尝试 JSON
    json_result = _try_extract_json(clean)
    if json_result is not None:
        return json_result
    # 2. 管道表格解析
    table_result = _parse_pipe_table(clean)
    if table_result is not None:
        return table_result
    # 3. key-value 记录解析
    kv_result = _parse_key_value_records(clean)
    if kv_result is not None:
        return kv_result
    return None


def _try_extract_json(text: str) -> dict | None:
    """从文本中提取 JSON 对象。"""
    import re
    # 尝试匹配 { ... }
    brace_count = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if brace_count == 0:
                start = i
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0 and start >= 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    start = -1
                    continue
    return None


def _parse_pipe_table(text: str) -> dict | None:
    """解析管道分隔表格 (| col1 | col2 | ... |)。

    CLI 输出格式:
        ...
        总条数: N
        | header1 | header2 | ... |
        | --- | --- | ... |
        | val1 | val2 | ... |

    Returns {"data": {"list": [...], "total": N}} or None.
    """
    lines = text.strip().split("\n")
    # 找总条数
    total = 0
    import re
    for line in lines:
        m = re.search(r"总条数[：:]\s*(\d+)", line)
        if m:
            total = int(m.group(1))
            break

    # 找表格: 连续的 | 行
    table_rows: list[list[str]] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows.append([
                c.strip() for c in stripped[1:-1].split("|")
            ])
            in_table = True
        elif in_table:
            break  # 表格结束

    if len(table_rows) < 3:
        return None  # 至少需要 header + separator + 1 data row

    # table_rows[0] = header, table_rows[1] = --- separators
    headers = table_rows[0]
    data_rows = table_rows[2:]

    # 去除首列 ID 列（如公司ID T000025753）
    if headers and headers[0] in ("公司ID", "ID", "工具ID"):
        headers = headers[1:]
        data_rows = [
            row[1:] if len(row) > 1 else row
            for row in data_rows
        ]

    records = []
    for row in data_rows:
        record: dict[str, str] = {}
        for i, header in enumerate(headers):
            val = row[i] if i < len(row) else ""
            record[header] = val
        records.append(record)

    return {"data": {"list": records, "total": total}}


def _parse_key_value_records(text: str) -> dict | None:
    """解析 key-value 格式输出。

    格式:
        总条数: N
        公司ID: T000025753
        字段1: 值1
        字段2: 值2
        ---
        公司ID: T000025754
        ...

    Returns {"data": {"list": [...], "total": N}} or None.
    """
    import re
    lines = text.strip().split("\n")

    total = 0
    for line in lines:
        m = re.search(r"总条数[：:]\s*(\d+)", line)
        if m:
            total = int(m.group(1))
            break

    # 跳过提示行和元信息（工具名/描述）
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("公司ID:") or stripped.startswith("公司ID："):
            data_start = i
            break

    if data_start == 0:
        return None  # 不是 key-value 格式

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "---" or stripped.startswith("---"):
            if current:
                records.append(current)
                current = {}
            continue
        # 检测新记录开始：以 "公司ID:" 开头且当前已有数据
        if (stripped.startswith("公司ID:") or stripped.startswith("公司ID：")) and current:
            records.append(current)
            current = {}
        # 解析 key: value
        if ":" in stripped or "：" in stripped:
            sep = ":" if ":" in stripped else "："
            key, _, val = stripped.partition(sep)
            key = key.strip()
            val = val.strip().strip('"')
            current[key] = val

    if current:
        records.append(current)

    if not records:
        return None

    return {"data": {"list": records, "total": total}}


# ---------------------------------------------------------------------------
# 字段解析 — 中文字段名映射
# ---------------------------------------------------------------------------


def _safe_float(val: str | None) -> Optional[float]:
    """安全转换为 float，空值返回 None。"""
    if val is None or val == "" or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_income_statement(row: dict) -> KuaichaIncomeStatement:
    """解析利润表。字段名同时支持中英文。"""
    f = _safe_float
    # report period: 截止时间 or 起始时间-截止时间
    period = str(row.get("截止时间", row.get("end_date", "")))
    start = str(row.get("起始时间", ""))
    if start and not period:
        period = start

    return KuaichaIncomeStatement(
        report_period=period,
        report_type=str(row.get("报表类型编码", row.get("report_type", row.get("type", "")))),
        revenue=(f(row.get("一、营业总收入")) or f(row.get("营业收入"))
                 or f("revenue") or f("total_revenue")),
        operating_cost=(f(row.get("二、营业总成本"))
                        or f(row.get("operating_cost")) or f("total_cost")),
        operating_profit=(f(row.get("三、营业利润"))
                          or f(row.get("operating_profit"))),
        net_profit=(f(row.get("五、净利润"))
                    or f(row.get("净利润")) or f("net_profit") or f("net_income")),
        net_profit_parent=(f(row.get("归属于母公司股东的净利润"))
                           or f(row.get("net_profit_parent"))),
        eps_basic=(f(row.get("基本每股收益"))
                   or f(row.get("eps_basic")) or f("eps")),
        is_audited=str(row.get("是否审计(1为已审计，0为未审计)",
                              row.get("is_audited", "0"))) == "1",
    )


def _parse_balance_sheet(row: dict) -> KuaichaBalanceSheet:
    """解析资产负债表。"""
    f = _safe_float
    period = str(row.get("截止时间", row.get("end_date", "")))

    return KuaichaBalanceSheet(
        report_period=period,
        report_type=str(row.get("报表类型编码", row.get("report_type", row.get("type", "")))),
        total_assets=(f(row.get("资产总计")) or f("total_assets")),
        total_liabilities=(f(row.get("负债合计")) or f("total_liabilities")),
        equity_parent=(f(row.get("归属于母公司股东权益合计"))
                       or f(row.get("股东权益合计"))
                       or f(row.get("所有者权益合计"))
                       or f("equity_parent")),
        goodwill=(f(row.get("商誉")) or f("goodwill")),
        current_assets=(f(row.get("流动资产合计")) or f("current_assets")),
        current_liabilities=(f(row.get("流动负债合计")) or f("current_liabilities")),
        is_audited=str(row.get("是否审计(1为已审计，0为未审计)",
                              row.get("is_audited", "0"))) == "1",
    )


def _parse_cash_flow(row: dict) -> KuaichaCashFlow:
    """解析现金流量表。"""
    f = _safe_float
    period = str(row.get("截止时间", row.get("end_date", "")))

    return KuaichaCashFlow(
        report_period=period,
        report_type=str(row.get("报表类型编码", row.get("report_type", row.get("type", "")))),
        operating_cf=(f(row.get("经营活动产生的现金流量净额"))
                      or f(row.get("operating_cf")) or f("operating_cash_flow")),
        investing_cf=(f(row.get("投资活动产生的现金流量净额"))
                      or f(row.get("investing_cf")) or f("investing_cash_flow")),
        financing_cf=(f(row.get("筹资活动产生的现金流量净额"))
                      or f(row.get("financing_cf")) or f("financing_cash_flow")),
        is_audited=str(row.get("是否审计(1为已审计，0为未审计)",
                              row.get("is_audited", "0"))) == "1",
    )
