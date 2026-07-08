# -*- coding: utf-8 -*-
"""金融数据子工具函数 — 包装 DataAggregator + AKShare 提供统一查询接口。

每个函数都是独立可调用的，接收简单参数，返回 Python dict/list 结构。
调用者根据需要自行格式化。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from src.data.aggregator import DataAggregator

logger = logging.getLogger(__name__)

_agg: DataAggregator | None = None


def _get_agg() -> DataAggregator:
    """全局懒加载 DataAggregator 单例。"""
    global _agg
    if _agg is None:
        _agg = DataAggregator()
    return _agg


# ---------------------------------------------------------------------------
# 工具: 股票代码标准化
# ---------------------------------------------------------------------------

def normalize_symbol(symbol: str) -> str:
    """标准化股票代码: 去除前缀后缀，返回 6 位数字。

    '600519'    -> '600519'
    'SH600519'  -> '600519'
    '600519.SH' -> '600519'
    'sz000001'  -> '000001'
    """
    raw = symbol.strip().upper().replace(".", "").replace(" ", "")
    for prefix in ("SH", "SZ", "BJ", "SHSE.", "SZSE."):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw[:6]


def detect_market(symbol: str) -> str:
    """根据股票代码推断市场。

    600xxx/601xxx/603xxx/688xxx -> SH
    000xxx/001xxx/002xxx/003xxx/300xxx/301xxx/200xxx -> SZ
    8xxxxx/4xxxxx -> BJ
    """
    code = normalize_symbol(symbol)
    if not code or len(code) < 6:
        return "SH"
    # SH 市场
    if code.startswith(("6", "9")):
        return "SH"
    # SZ 市场
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    # BJ 市场
    if code.startswith(("4", "8")):
        return "BJ"
    return "SH"


# ---------------------------------------------------------------------------
# 财务三表
# ---------------------------------------------------------------------------

def get_income_statements(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """获取利润表摘要。

    Args:
        symbol: 股票代码 (600519 / SH600519)
        period: annual / quarter
        limit:  期数

    Returns:
        list[dict]: [{报告期, 营业总收入, 营业总成本, 营业利润, 利润总额, 净利润,
                       归母净利润, 扣非净利润, 基本每股收益, ...}, ...]
    """
    code = normalize_symbol(symbol)
    market = detect_market(symbol)

    agg = _get_agg()

    # 尝试用 aggregator 获取基本财务摘要
    fins = agg.get_financials(code, market, count=max(limit, 2))
    results: list[dict[str, Any]] = []
    for f in fins:
        results.append({
            "报告期": f.report_period,
            "营业总收入": f.revenue,
            "净利润": f.net_profit,
            "净利润_归母": f.net_profit,
            "基本每股收益": f.eps,
            "净资产收益率": f.roe,
            "经营活动现金流": f.operating_cash_flow,
        })

    # 如果 aggregator 返回不足，尝试 AKShare 的详细利润表
    if len(results) < limit:
        try:
            df = _fetch_profit_detail(code, period, limit)
            if df is not None and not df.empty:
                rows = _df_to_income_rows(df, code)
                results = rows if len(rows) >= len(results) else results
        except Exception as exc:
            logger.debug("get_income_statements detail fallback failed: %s", exc)

    return results


def get_balance_sheets(
    symbol: str,
    period: str = "annual",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """获取资产负债表摘要。

    Args:
        symbol: 股票代码
        period: annual / quarter
        limit:  期数

    Returns:
        list[dict]: [{报告期, 资产总计, 流动资产合计, 货币资金, 应收账款,
                       存货, 固定资产, 负债合计, 流动负债合计, 所有者权益合计}, ...]
    """
    code = normalize_symbol(symbol)
    try:
        import akshare as ak
        df = ak.stock_balance_sheet_by_report_ths(symbol=code)
        if df is None or df.empty:
            return []
        return _df_to_balance_rows(df, limit)
    except Exception as exc:
        logger.debug("get_balance_sheets failed for %s: %s", code, exc)
        return []


def get_cash_flows(
    symbol: str,
    period: str = "annual",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """获取现金流量表摘要。

    Args:
        symbol: 股票代码
        period: annual / quarter
        limit:  期数

    Returns:
        list[dict]: [{报告期, 经营活动现金流净额, 投资活动现金流净额,
                       筹资活动现金流净额, 现金及等价物净增加额}, ...]
    """
    code = normalize_symbol(symbol)
    try:
        import akshare as ak
        df = ak.stock_cash_flow_by_report_ths(symbol=code)
        if df is None or df.empty:
            return []
        return _df_to_cashflow_rows(df, limit)
    except Exception as exc:
        logger.debug("get_cash_flows failed for %s: %s", code, exc)
        return []


# ---------------------------------------------------------------------------
# 关键比率
# ---------------------------------------------------------------------------

def get_key_ratios(symbol: str) -> dict[str, Any]:
    """获取关键财务比率。

    Args:
        symbol: 股票代码

    Returns:
        dict: {pe_ttm, pb, roe, roa, gross_margin, net_margin,
               debt_to_equity, current_ratio, eps, bvps,
               revenue_growth, profit_growth}
    """
    code = normalize_symbol(symbol)
    market = detect_market(symbol)
    agg = _get_agg()

    ratios: dict[str, Any] = {}

    # 1. 估值指标: 从 Quote 获取
    try:
        quote = agg.get_quote(code, market)
        if quote:
            ratios["pe_ttm"] = quote.pe_ttm
            ratios["pb"] = quote.pb
            ratios["market_cap"] = quote.market_cap
            ratios["dividend_yield"] = quote.dividend_yield
            ratios["price"] = quote.price
            ratios["change_pct"] = quote.change_pct
    except Exception:
        pass

    # 2. 财务指标: 从 Financials 计算
    fins = agg.get_financials(code, market, count=2)
    if fins:
        latest = fins[0]
        ratios["roe"] = latest.roe
        ratios["eps"] = latest.eps
        # ROA = 净利润 / 总资产
        if latest.net_profit and latest.total_assets and latest.total_assets > 0:
            ratios["roa"] = round(latest.net_profit / latest.total_assets * 100, 2)
        # 资产负债率
        if latest.total_liabilities is not None and latest.total_assets and latest.total_assets > 0:
            ratios["debt_to_equity"] = round(latest.total_liabilities / latest.total_assets * 100, 2)
        ratios["revenue"] = latest.revenue
        ratios["net_profit"] = latest.net_profit
        ratios["operating_cash_flow"] = latest.operating_cash_flow

        # 增长率 (YoY)
        if len(fins) >= 2:
            prev = fins[1]
            if latest.revenue and prev.revenue and prev.revenue > 0:
                ratios["revenue_growth"] = round(
                    (latest.revenue - prev.revenue) / abs(prev.revenue) * 100, 2
                )
            if latest.net_profit and prev.net_profit and prev.net_profit > 0:
                ratios["profit_growth"] = round(
                    (latest.net_profit - prev.net_profit) / abs(prev.net_profit) * 100, 2
                )

    # 3. 补充: 从 AKShare 获取毛利率
    try:
        import akshare as ak
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if df is not None and not df.empty:
            latest_row = df.iloc[-1]
            if "毛利率" in df.columns:
                ratios["gross_margin"] = _safe_float(latest_row.get("毛利率"))
            if "净利率" in df.columns:
                ratios["net_margin"] = _safe_float(latest_row.get("净利率"))
            if "每股净资产" in df.columns:
                ratios["bvps"] = _safe_float(latest_row.get("每股净资产"))
            if "流动比率" in df.columns:
                ratios["current_ratio"] = _safe_float(latest_row.get("流动比率"))
    except Exception:
        pass

    return ratios


# ---------------------------------------------------------------------------
# 行情 & K 线
# ---------------------------------------------------------------------------

def get_stock_price(symbol: str) -> dict[str, Any]:
    """获取实时行情。

    Args:
        symbol: 股票代码

    Returns:
        dict: {symbol, name, price, change_pct, volume, turnover,
               high, low, open, prev_close, pe_ttm, pb, market_cap}
    """
    code = normalize_symbol(symbol)
    market = detect_market(symbol)
    agg = _get_agg()

    quote = agg.get_quote(code, market)
    if quote is None:
        return {"symbol": code, "error": "未获取到行情数据"}

    return {
        "symbol": quote.symbol,
        "name": quote.name,
        "price": quote.price,
        "change_pct": quote.change_pct,
        "volume": quote.volume,
        "turnover": quote.turnover,
        "high": quote.high,
        "low": quote.low,
        "open": quote.open,
        "prev_close": quote.prev_close,
        "pe_ttm": quote.pe_ttm,
        "pb": quote.pb,
        "market_cap": quote.market_cap,
    }


def get_kline(
    symbol: str,
    period: str = "daily",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """获取历史 K 线。

    Args:
        symbol: 股票代码
        period: daily / weekly / monthly
        limit:  条数

    Returns:
        list[dict]: [{日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 涨跌幅}, ...]
    """
    code = normalize_symbol(symbol)
    market = detect_market(symbol)
    agg = _get_agg()

    # 计算起止日期
    end_date = datetime.now()
    if period == "daily":
        start_date = end_date - timedelta(days=limit * 2)  # 多取一点因非交易日
    elif period == "weekly":
        start_date = end_date - timedelta(weeks=limit * 2)
    elif period == "monthly":
        start_date = end_date - timedelta(days=limit * 60)
    else:
        start_date = end_date - timedelta(days=limit * 2)

    df = agg.get_history(
        code,
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        period=period,
    )
    if df is None or df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, r in df.tail(limit).iterrows():
        rows.append({
            "日期": str(r.get("日期", r.get("date", ""))),
            "开盘": _safe_float(r.get("开盘", r.get("open"))),
            "收盘": _safe_float(r.get("收盘", r.get("close"))),
            "最高": _safe_float(r.get("最高", r.get("high"))),
            "最低": _safe_float(r.get("最低", r.get("low"))),
            "成交量": _safe_float(r.get("成交量", r.get("volume"))),
            "成交额": _safe_float(r.get("成交额", r.get("amount"))),
            "涨跌幅": _safe_float(r.get("涨跌幅", r.get("pct_change"))),
        })
    return rows


# ---------------------------------------------------------------------------
# 资讯
# ---------------------------------------------------------------------------

def get_company_news(symbol: str, limit: int = 10) -> list[dict[str, Any]]:
    """获取个股相关新闻/资讯。

    Args:
        symbol: 股票代码
        limit:  条数

    Returns:
        list[dict]: [{title, source, date, content, url}, ...]
    """
    code = normalize_symbol(symbol)
    agg = _get_agg()

    query = f"{code} 公告"
    try:
        items = agg.search_news(query, max_results=limit)
        if not items:
            # 用公司名再搜一次
            quote = agg.get_quote(code, detect_market(symbol))
            if quote and quote.name:
                items = agg.search_news(quote.name, max_results=limit)

        return [
            {
                "title": item.title,
                "source": item.source,
                "date": item.date,
                "content": item.content[:200] if item.content else "",
                "url": item.url,
            }
            for item in (items or [])
        ]
    except Exception as exc:
        logger.debug("get_company_news failed for %s: %s", code, exc)
        return []


# ---------------------------------------------------------------------------
# A 股特有数据
# ---------------------------------------------------------------------------

def get_northbound_flow(symbol: str) -> dict[str, Any]:
    """获取北向资金数据（个股维度）。

    Args:
        symbol: 股票代码

    Returns:
        dict: {hold_vol, hold_value, hold_pct, daily_change, ...}
        或 {"error": "..."}
    """
    code = normalize_symbol(symbol)
    try:
        import akshare as ak
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        # 个股北向持股查询
        hold = ak.stock_hsgt_individual_em(market="沪股通")
        if hold is None or hold.empty:
            hold = ak.stock_hsgt_individual_em(market="深股通")
        if hold is not None and not hold.empty:
            row = hold[hold["股票代码"].astype(str).str.contains(code)]
            if not row.empty:
                r = row.iloc[0]
                return {
                    "hold_vol": _safe_float(r.get("持股数量")),
                    "hold_value": _safe_float(r.get("持股市值")),
                    "hold_pct": _safe_float(r.get("持股比例")),
                    "daily_change": _safe_float(r.get("较上日变动")),
                    "market": "沪股通" if "沪" in str(hold.columns) else "深股通",
                }
        return {"hold_vol": None, "info": "未查到个股北向数据"}
    except Exception as exc:
        logger.debug("get_northbound_flow failed for %s: %s", code, exc)
        return {"error": f"北向资金查询失败: {exc}"}


def get_margin_data(symbol: str) -> dict[str, Any]:
    """获取融资融券数据。

    Args:
        symbol: 股票代码

    Returns:
        dict: {margin_balance, margin_buy, short_sell_balance, short_sell_vol, ...}
    """
    code = normalize_symbol(symbol)
    try:
        import akshare as ak
        # 个股融资融券数据
        df = ak.stock_margin_detail_sse(date=datetime.now().strftime("%Y%m%d"))
        if df is None or df.empty:
            return {"error": "当日融资融券数据未出"}
        if "证券代码" in df.columns:
            row = df[df["证券代码"].astype(str).str.contains(code)]
        elif "代码" in df.columns:
            row = df[df["代码"].astype(str).str.contains(code)]
        else:
            return {"error": "无法识别的融资融券数据格式"}

        if not row.empty:
            r = row.iloc[0]
            result: dict[str, Any] = {}
            for col in r.index:
                try:
                    result[col] = _safe_float(r[col]) if _is_numeric_col(col) else str(r[col])
                except Exception:
                    result[col] = str(r[col])
            return result
        return {"info": "该股当日无融资融券记录"}
    except Exception as exc:
        logger.debug("get_margin_data failed for %s: %s", code, exc)
        return {"error": f"融资融券查询失败: {exc}"}


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _fetch_profit_detail(code: str, period: str, limit: int) -> pd.DataFrame | None:
    """用 AKShare 同花顺获取详细利润表。"""
    try:
        import akshare as ak
        df = ak.stock_profit_by_report_ths(symbol=code)
        if df is not None and not df.empty:
            df = df.tail(limit)
        return df
    except Exception:
        return None


def _df_to_income_rows(df: pd.DataFrame, code: str) -> list[dict[str, Any]]:
    """解析利润表 DataFrame 为 dict 列表。"""
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append({
            "报告期": str(r.get("报告期", "")),
            "营业总收入": _safe_float(r.get("营业总收入")),
            "营业总成本": _safe_float(r.get("营业总成本")),
            "营业利润": _safe_float(r.get("营业利润")),
            "利润总额": _safe_float(r.get("利润总额")),
            "净利润": _safe_float(r.get("净利润")),
            "归母净利润": _safe_float(r.get("归母净利润")),
            "扣非净利润": _safe_float(r.get("扣非净利润")),
            "基本每股收益": _safe_float(r.get("基本每股收益")),
        })
    return rows


def _df_to_balance_rows(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    """解析资产负债表 DataFrame 为 dict 列表。"""
    rows: list[dict[str, Any]] = []
    for _, r in df.tail(limit).iterrows():
        rows.append({
            "报告期": str(r.get("报告期", "")),
            "资产总计": _safe_float(r.get("资产总计")),
            "流动资产合计": _safe_float(r.get("流动资产合计")),
            "货币资金": _safe_float(r.get("货币资金")),
            "应收账款": _safe_float(r.get("应收账款")),
            "存货": _safe_float(r.get("存货")),
            "固定资产": _safe_float(r.get("固定资产")),
            "负债合计": _safe_float(r.get("负债合计")),
            "流动负债合计": _safe_float(r.get("流动负债合计")),
            "所有者权益合计": _safe_float(r.get("所有者权益合计")),
        })
    return rows


def _df_to_cashflow_rows(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    """解析现金流量表 DataFrame 为 dict 列表。"""
    rows: list[dict[str, Any]] = []
    for _, r in df.tail(limit).iterrows():
        rows.append({
            "报告期": str(r.get("报告期", "")),
            "经营活动现金流净额": _safe_float(r.get("经营活动产生的现金流量净额")),
            "投资活动现金流净额": _safe_float(r.get("投资活动产生的现金流量净额")),
            "筹资活动现金流净额": _safe_float(r.get("筹资活动产生的现金流量净额")),
            "现金及等价物净增加额": _safe_float(r.get("现金及现金等价物净增加额")),
        })
    return rows


def _safe_float(val) -> float | None:
    """安全转 float。"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if val != val:  # NaN
            return None
        return round(float(val), 4)
    s = str(val).replace(",", "").replace("%", "").replace("亿", "").replace("万", "").strip()
    if not s or s in ("-", "--", "nan", "None", ""):
        return None
    try:
        return round(float(s), 4)
    except (ValueError, TypeError):
        return None


def _is_numeric_col(col_name: str) -> bool:
    """判断列名是否为数值型数据列。"""
    numeric_keywords = ("金额", "余额", "数量", "比例", "比率", "市值", "价格", "变动", "比例")
    return any(kw in str(col_name) for kw in numeric_keywords)
