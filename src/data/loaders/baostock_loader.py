# -*- coding: utf-8 -*-
"""Baostock 财务数据 Loader。

Baostock 提供免费、无需注册、无调用次数限制的 A 股历史财务数据
（盈利/成长/现金流/分红），作为国信/akshare 日限额耗尽时的财务兜底。

注意：
- 只提供财务与历史数据，无实时行情（get_quote 不支持）。
- 现金流接口返回比率（CFOToNP=经营现金流/净利润），绝对值由 netProfit×比率推算。
- ROE/EPS 为小数（0.162539），统一转换为百分比数字（16.25），与 akshare 对齐。
- 财务查询秒回，但 K 线接口在网络环境下可能长时间无响应，故不接入 get_history。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.schema import Financials
from src.data.source_citation import (
    NATURE_FACT,
    SOURCE_TIER_T1,
    SourceCitation,
)

logger = logging.getLogger(__name__)

# baostock 全局会话非线程安全，需加锁串行化 login/query/logout
_BAOSTOCK_LOCK = threading.Lock()


@register
class BaostockLoader(DataLoader):
    """Baostock 免费财务 Loader（A 股历史财务兜底）。"""

    name = "baostock"
    markets = ["a_share"]

    def __init__(self):
        self._baostock = None

    def is_available(self) -> bool:
        try:
            import baostock  # noqa: F401
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------
    # 财务数据
    # ------------------------------------------------------------------

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取最近 N 期财务数据（跨年回溯）。

        Baostock 按 (year, quarter) 查询，quarter 取 4（年报，含全年累计指标），
        往前回溯 count 个年度，保证能凑齐 r032/r033 需要的近 3 年数据。
        """
        if market != "SH" and market != "SZ":
            return []
        try:
            import baostock as bs
        except ImportError:
            return []

        code = self._to_baostock_code(symbol, market)
        if code is None:
            return []

        results: list[Financials] = []
        try:
            with _BAOSTOCK_LOCK:
                lg = bs.login()
                if lg.error_code != "0":
                    logger.warning("baostock login failed: %s", lg.error_msg)
                    return []
                try:
                    year = _current_year()
                    fetched = 0
                    while fetched < count and year > 2010:
                        fin = self._query_year_financials(bs, code, year)
                        if fin is not None:
                            results.append(fin)
                            fetched += 1
                        year -= 1
                finally:
                    bs.logout()
        except Exception as e:
            logger.warning("baostock get_financials(%s) failed: %s", symbol, e)
            return []

        return results

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    @staticmethod
    def _to_baostock_code(symbol: str, market: str) -> Optional[str]:
        """标准数字代码 → baostock 格式 (sh.600406 / sz.000001)。

        baostock 按代码前缀区分市场，与传入 market 参数共同兜底：
        6/9 开头 → sh，0/3 开头 → sz，其余按 market 参数。
        """
        code = symbol.strip()[-6:]
        if len(code) != 6 or not code.isdigit():
            return None
        if code[0] in ("6", "9"):
            return f"sh.{code}"
        if code[0] in ("0", "3"):
            return f"sz.{code}"
        prefix = "sh" if market == "SH" else "sz"
        return f"{prefix}.{code}"

    @staticmethod
    def _query_year_financials(bs, code: str, year: int) -> Optional[Financials]:
        """查询指定年度年报财务数据，拼装 Financials。"""
        try:
            # 1. 盈利数据（ROE / 净利润 / EPS / 营收）
            rs = bs.query_profit_data(code=code, year=year, quarter=4)
            if rs.error_code != "0":
                return None
            profit = None
            while rs.next():
                profit = dict(zip(rs.fields, rs.get_row_data()))
                break
            if profit is None or not profit.get("statDate"):
                return None

            net_profit = _safe_float(profit.get("netProfit"))
            roe = _safe_float(profit.get("roeAvg"))
            eps = _safe_float(profit.get("epsTTM"))
            revenue = _safe_float(profit.get("MBRevenue"))
            stat_date = str(profit.get("statDate", ""))

            # 2. 现金流比率（经营现金流/净利润），用于推算 OCF 绝对值
            ocf = None
            try:
                rs_cf = bs.query_cash_flow_data(code=code, year=year, quarter=4)
                if rs_cf.error_code == "0":
                    while rs_cf.next():
                        cf = dict(zip(rs_cf.fields, rs_cf.get_row_data()))
                        cfo_to_np = _safe_float(cf.get("CFOToNP"))
                        if cfo_to_np > 0 and net_profit is not None:
                            ocf = net_profit * cfo_to_np
                        break
            except Exception:
                pass

            if roe is not None:
                roe = round(roe * 100.0, 4)  # 0.162539 → 16.2539，与 akshare 对齐

            citation = SourceCitation(
                provider="baostock",
                field="financials",
                fetch_timestamp=None,
                data_freshness=None,
                confidence=0.85,
                source_tier=SOURCE_TIER_T1,
                nature=NATURE_FACT,
            )
            return Financials(
                symbol=str(profit.get("code", "")),
                report_period=stat_date,
                revenue=revenue,
                net_profit=net_profit,
                operating_cash_flow=ocf,
                roe=roe,
                eps=eps,
                source="baostock",
                citation=citation,
            )
        except Exception as e:
            logger.debug("baostock query %s %s failed: %s", code, year, e)
            return None


def _safe_float(val) -> Optional[float]:
    """安全转 float，空/非法值返回 None。"""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _current_year() -> int:
    """当前年份。"""
    from datetime import datetime
    return datetime.now().year
