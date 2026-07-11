# -*- coding: utf-8 -*-
"""个股主力资金流数据提供者。

封装东财 push2his 日线资金流向接口，提供 AKShare 降级，
支持本地 CSV 缓存与增量更新。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from src.data.schema import MoneyFlowSnapshot
from src.data.source_citation import (
    SOURCE_TIER_T1,
    SOURCE_TIER_T2,
    NATURE_FACT,
    NATURE_INTERPRETATION,
    SourceCitation,
)

logger = logging.getLogger(__name__)

# 东财 push2his 个股资金流向日线接口
_EM_FFLOW_DAYKLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_EM_FFLOW_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
_EM_MIN_INTERVAL_S = 1.0

# 缓存目录（基于项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _PROJECT_ROOT / "data" / "kline_cache" / "money_flow"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 最近一次东财请求时间戳，用于简单节流
_last_em_request_at = 0.0
_em_request_lock = threading.Lock()


def _to_secid(symbol: str) -> str:
    """纯数字代码 → 东财 secid（1=沪，0=深）。"""
    code = symbol.strip()[-6:]
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无效股票代码: {symbol}")
    first = code[0]
    market = "1" if first in ("6", "9") else "0"
    return f"{market}.{code}"


def _symbol_to_market(symbol: str) -> str:
    """纯数字代码 → AKShare market（sh/sz/bj）。"""
    code = symbol.strip()[-6:]
    first = code[0]
    if first in ("6", "9"):
        # 900/909 为上海 B 股；920/920 为北京所兼容格式
        if code.startswith(("92", "93")):
            return "bj"
        return "sh"
    if first in ("0", "2", "3"):
        return "sz"
    if first in ("4", "8"):
        return "bj"
    return "sh"


def _throttle_em_request() -> None:
    """东财请求间隔控制（线程安全）。"""
    global _last_em_request_at
    with _em_request_lock:
        now = time.time()
        elapsed = now - _last_em_request_at
        if elapsed < _EM_MIN_INTERVAL_S:
            time.sleep(_EM_MIN_INTERVAL_S - elapsed)
        _last_em_request_at = time.time()


def _compute_main_consecutive_days(df: pd.DataFrame) -> int:
    """计算主力连续流入/流出天数。

    从最近一日向前统计，主力净额同号且非零的天数。
    正数表示连续流入，负数表示连续流出。
    """
    if df.empty or "main_net" not in df.columns:
        return 0
    # 按日期升序排列，取最后一条作为最新
    df = df.sort_values("date").reset_index(drop=True)
    latest_main = df["main_net"].iloc[-1]
    if latest_main == 0:
        return 0
    sign = 1 if latest_main > 0 else -1
    consecutive = 0
    for val in reversed(df["main_net"].tolist()):
        if val == 0:
            break
        if (val > 0 and sign == 1) or (val < 0 and sign == -1):
            consecutive += 1
        else:
            break
    return consecutive * sign


def _recent_price_trend(df: pd.DataFrame) -> str:
    """根据近 5 日收盘价判断趋势。"""
    if df.empty or "close" not in df.columns:
        return "neutral"
    recent = df.sort_values("date").tail(5)
    if len(recent) < 3:
        return "neutral"
    start = float(recent["close"].iloc[0])
    end = float(recent["close"].iloc[-1])
    if start <= 0:
        return "neutral"
    change = (end - start) / start
    if change > 0.03:
        return "up"
    if change < -0.03:
        return "down"
    return "neutral"


class CapitalFlowProvider:
    """个股主力资金流提供者。"""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
        )
        self._session.trust_env = False

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def get_money_flow(self, symbol: str, weeks: int = 4) -> Optional[MoneyFlowSnapshot]:
        """获取个股近 N 周主力资金流快照。

        优先东财 push2his 日线接口；失败或不可用时回退到 AKShare。
        """
        symbol = symbol.strip()[-6:]
        if len(symbol) != 6 or not symbol.isdigit():
            return MoneyFlowSnapshot(
                symbol=symbol,
                data_gap_reason=f"[DATA_GAP] 无效股票代码: {symbol}",
            )
        days = max(weeks * 7, 14)

        # 1. 尝试东财主源
        df, citation = self._fetch_em_daykline(symbol, days)
        data_gap_reason = ""

        # 2. 东财失败或数据为空 → AKShare 降级
        if df is None or df.empty:
            df, citation, data_gap_reason = self._fetch_akshare_fallback(symbol, days)

        # 3. 全部失败 → DATA_GAP
        if df is None or df.empty:
            return MoneyFlowSnapshot(
                symbol=symbol,
                data_gap_reason=data_gap_reason or "个股资金流数据源均不可用",
            )

        latest = df.sort_values("date").iloc[-1]
        consecutive = _compute_main_consecutive_days(df)
        trend = _recent_price_trend(df)

        return MoneyFlowSnapshot(
            symbol=symbol,
            super_large_net=float(latest.get("super_large_net", 0)),
            large_net=float(latest.get("large_net", 0)),
            medium_net=float(latest.get("medium_net", 0)),
            small_net=float(latest.get("small_net", 0)),
            main_net=float(latest.get("main_net", 0)),
            total_turnover=float(latest.get("total_turnover", 0)),
            main_consecutive_days=consecutive,
            price_change_pct=float(latest.get("change_pct", 0)),  # 比例
            recent_price_trend=trend,
            data_gap_reason=data_gap_reason,
            citation=citation,
        )

    def get_all_fund_flow_rank(self) -> pd.DataFrame:
        """获取 AKShare 全市场个股资金流排名（用于 scan/alpha-scan 批量场景）。

        返回 DataFrame 列: 股票代码, 净额(万元), 成交额(万元), 涨跌幅(比例)。
        若数据源不可用返回空 DataFrame。
        """
        import akshare as ak
        try:
            df = ak.stock_fund_flow_individual(symbol="即时")
            if df is None or df.empty or "股票代码" not in df.columns:
                return pd.DataFrame()
            df = df.copy()
            df["股票代码"] = df["股票代码"].astype(str).str.strip()
            df["main_net_wan"] = df["净额"].apply(self._parse_chinese_amount)
            df["turnover_wan"] = df["成交额"].apply(self._parse_chinese_amount)
            df["change_pct_ratio"] = df["涨跌幅"].apply(self._parse_change_pct)
            return df[["股票代码", "main_net_wan", "turnover_wan", "change_pct_ratio"]]
        except Exception as e:
            logger.warning("全市场资金流排名获取失败: %s", e)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # 东财主源
    # ------------------------------------------------------------------

    def _fetch_em_daykline(
        self, symbol: str, days: int
    ) -> tuple[Optional[pd.DataFrame], Optional[SourceCitation]]:
        """拉取东财个股资金流向日线数据。"""
        try:
            _throttle_em_request()
            secid = _to_secid(symbol)
            params = {
                "secid": secid,
                "klt": "101",  # 日线
                "lmt": str(days),
                "fields1": "f1,f2,f3,f7",
                "fields2": _EM_FFLOW_FIELDS,
            }
            r = self._session.get(_EM_FFLOW_DAYKLINE_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            klines = data.get("data", {}).get("klines", [])
            if not klines:
                return None, None
            df = self._parse_em_klines(klines)
            self._save_csv_cache(symbol, df)
            citation = SourceCitation(
                provider="eastmoney",
                field="individual_fund_flow",
                fetch_timestamp=datetime.now(),
                data_freshness=timedelta(hours=4),
                confidence=0.80,
                source_tier=SOURCE_TIER_T1,
                nature=NATURE_FACT,
                url_or_endpoint=_EM_FFLOW_DAYKLINE_URL,
            )
            return df, citation
        except Exception as e:
            logger.warning("东财个股资金流获取失败 %s: %s", symbol, e)
            return None, None

    @staticmethod
    def _parse_em_klines(klines: list[str]) -> pd.DataFrame:
        """解析东财 klines 字符串数组。

        字段顺序：
        0:日期, 1:主力净额, 2:小单净额, 3:中单净额, 4:大单净额, 5:超大单净额,
        6:主力占比, 7:小单占比, 8:中单占比, 9:大单占比, 10:超大单占比,
        11:收盘价, 12:涨跌幅(%), 13:成交量, 14:成交额
        """

        def _to_float(s: str) -> float:
            try:
                return float(s) if s and s != "-" else 0.0
            except ValueError:
                return 0.0

        def _to_int(s: str) -> int:
            try:
                return int(float(s)) if s and s != "-" else 0
            except ValueError:
                return 0

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 15:
                continue
            rows.append(
                {
                    "date": parts[0],
                    "main_net_yuan": _to_float(parts[1]),
                    "small_net_yuan": _to_float(parts[2]),
                    "medium_net_yuan": _to_float(parts[3]),
                    "large_net_yuan": _to_float(parts[4]),
                    "super_large_net_yuan": _to_float(parts[5]),
                    "close": _to_float(parts[11]),
                    "change_pct": _to_float(parts[12]) / 100.0,  # 百分比数字 → 比例
                    "volume": _to_int(parts[13]),
                    "turnover_yuan": _to_float(parts[14]),
                }
            )
        df = pd.DataFrame(rows)
        # 元 → 万元
        df["super_large_net"] = df["super_large_net_yuan"] / 10000.0
        df["large_net"] = df["large_net_yuan"] / 10000.0
        df["medium_net"] = df["medium_net_yuan"] / 10000.0
        df["small_net"] = df["small_net_yuan"] / 10000.0
        df["main_net"] = df["super_large_net"] + df["large_net"]
        df["total_turnover"] = df["turnover_yuan"] / 10000.0
        df["date"] = pd.to_datetime(df["date"])
        return df[[
            "date", "super_large_net", "large_net", "medium_net", "small_net",
            "main_net", "total_turnover", "close", "change_pct", "volume",
        ]]

    @staticmethod
    def _parse_chinese_amount(val) -> float:
        """解析带中文单位的金额字符串，统一返回万元。

        示例:
          "4779.03万" -> 4779.03
          "29.96亿"   -> 299600.0
          "1.5千"     -> 0.15
          "100"       -> 100.0
        """
        if val is None:
            return 0.0
        s = str(val).strip().replace(",", "")
        if not s:
            return 0.0
        try:
            # 尝试直接数字
            return float(s)
        except ValueError:
            pass
        # 去掉百分号等后缀，保留数字+单位
        num_part = ""
        unit = ""
        for ch in s:
            if ch.isdigit() or ch in ".-":
                num_part += ch
            else:
                unit += ch
        try:
            num = float(num_part)
        except ValueError:
            return 0.0
        unit = unit.strip()
        if unit == "万":
            return num
        if unit == "亿":
            return num * 10000.0
        if unit == "千":
            return num / 10.0
        if unit == "百万":
            return num * 100.0
        return num

    @staticmethod
    def _parse_change_pct(val) -> float:
        """解析涨跌幅字符串为比例（如 1.93% -> 0.0193）。"""
        if val is None:
            return 0.0
        s = str(val).strip().replace(",", "")
        if not s:
            return 0.0
        # 去掉 % 后缀
        s = s.replace("%", "")
        try:
            return float(s) / 100.0
        except ValueError:
            return 0.0

    # ------------------------------------------------------------------
    # AKShare 降级
    # ------------------------------------------------------------------

    def _fetch_akshare_fallback(
        self, symbol: str, days: int
    ) -> tuple[Optional[pd.DataFrame], Optional[SourceCitation], str]:
        """AKShare 降级：尝试个股历史资金流，否则用全市场排名查找。"""
        import akshare as ak

        data_gap_reason = ""
        df: Optional[pd.DataFrame] = None
        citation: Optional[SourceCitation] = None

        # 尝试 1: stock_individual_fund_flow（若存在且返回历史）
        try:
            market = _symbol_to_market(symbol)
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            if df is not None and not df.empty:
                df = self._normalize_akshare_df(df, symbol)
                if not df.empty:
                    self._save_csv_cache(symbol, df)
                    citation = SourceCitation(
                        provider="akshare",
                        field="individual_fund_flow",
                        fetch_timestamp=datetime.now(),
                        data_freshness=timedelta(hours=4),
                        confidence=0.70,
                        source_tier=SOURCE_TIER_T2,
                        nature=NATURE_FACT,
                    )
                    return df, citation, "[DATA_GAP] AKShare 个股资金流缺少拆单数据"
        except Exception as e:
            logger.debug("AKShare stock_individual_fund_flow 失败 %s: %s", symbol, e)

        # 尝试 2: stock_fund_flow_individual 全市场排名
        try:
            df = ak.stock_fund_flow_individual(symbol="即时")
            if df is not None and not df.empty and "股票代码" in df.columns:
                row = df[df["股票代码"].astype(str).str.strip() == symbol]
                if not row.empty:
                    r = row.iloc[0]
                    net = self._parse_chinese_amount(r.get("净额", 0))
                    turnover = self._parse_chinese_amount(r.get("成交额", 0))
                    today = datetime.now().strftime("%Y-%m-%d")
                    df = pd.DataFrame(
                        [
                            {
                                "date": today,
                                "super_large_net": 0.0,
                                "large_net": net,
                                "medium_net": 0.0,
                                "small_net": 0.0,
                                "main_net": net,
                                "total_turnover": turnover,
                                "close": self._parse_chinese_amount(r.get("最新价", 0)),
                                "change_pct": self._parse_change_pct(r.get("涨跌幅", 0)),
                                "volume": 0,
                            }
                        ]
                    )
                    df["date"] = pd.to_datetime(df["date"])
                    citation = SourceCitation(
                        provider="akshare",
                        field="individual_fund_flow",
                        fetch_timestamp=datetime.now(),
                        data_freshness=timedelta(hours=4),
                        confidence=0.65,
                        source_tier=SOURCE_TIER_T2,
                        nature=NATURE_INTERPRETATION,
                    )
                    return df, citation, "[DATA_GAP] AKShare 排名源仅提供主力净额，无拆单"
        except Exception as e:
            logger.debug("AKShare stock_fund_flow_individual 失败 %s: %s", symbol, e)

        return None, None, "[DATA_GAP] 东财与 AKShare 个股资金流均不可用"

    @staticmethod
    def _normalize_akshare_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """标准化 AKShare 个股资金流 DataFrame。

        AKShare stock_individual_fund_flow 返回的金额单位通常为"元"，
        这里统一转换为万元，与 Eastmoney 路径保持一致。
        涨跌幅列通常为百分比数字，转换为比例。
        """
        # 不同 AKShare 版本列名可能不同，做兼容性映射
        col_map = {}
        for col in df.columns:
            c = str(col).strip()
            if "日期" in c:
                col_map[col] = "date"
            elif "超大单" in c and "净额" in c:
                col_map[col] = "super_large_net_yuan"
            elif "大单" in c and "净额" in c:
                col_map[col] = "large_net_yuan"
            elif "中单" in c and "净额" in c:
                col_map[col] = "medium_net_yuan"
            elif "小单" in c and "净额" in c:
                col_map[col] = "small_net_yuan"
            elif "主力" in c and "净额" in c:
                col_map[col] = "main_net_yuan"
            elif "成交额" in c:
                col_map[col] = "total_turnover_yuan"
            elif "收盘价" in c or "最新价" in c:
                col_map[col] = "close"
            elif "涨跌幅" in c:
                col_map[col] = "change_pct"
        if not col_map:
            return pd.DataFrame()
        df = df.rename(columns=col_map)
        # 确保必要列存在
        for col in ["super_large_net_yuan", "large_net_yuan", "medium_net_yuan", "small_net_yuan"]:
            if col not in df.columns:
                df[col] = 0.0
        if "main_net_yuan" not in df.columns:
            df["main_net_yuan"] = df["super_large_net_yuan"] + df["large_net_yuan"]
        if "total_turnover_yuan" not in df.columns:
            df["total_turnover_yuan"] = 0.0
        if "close" not in df.columns:
            df["close"] = 0.0
        if "change_pct" not in df.columns:
            df["change_pct"] = 0.0
        if "volume" not in df.columns:
            df["volume"] = 0

        # 元 → 万元；百分比数字 → 比例
        df["super_large_net"] = pd.to_numeric(df["super_large_net_yuan"], errors="coerce").fillna(0) / 10000.0
        df["large_net"] = pd.to_numeric(df["large_net_yuan"], errors="coerce").fillna(0) / 10000.0
        df["medium_net"] = pd.to_numeric(df["medium_net_yuan"], errors="coerce").fillna(0) / 10000.0
        df["small_net"] = pd.to_numeric(df["small_net_yuan"], errors="coerce").fillna(0) / 10000.0
        df["main_net"] = pd.to_numeric(df["main_net_yuan"], errors="coerce").fillna(0) / 10000.0
        df["total_turnover"] = pd.to_numeric(df["total_turnover_yuan"], errors="coerce").fillna(0) / 10000.0
        df["close"] = pd.to_numeric(df["close"], errors="coerce").fillna(0)
        df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce").fillna(0) / 100.0
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

        df["date"] = pd.to_datetime(df["date"])
        return df[[
            "date", "super_large_net", "large_net", "medium_net", "small_net",
            "main_net", "total_turnover", "close", "change_pct", "volume",
        ]]

    # ------------------------------------------------------------------
    # CSV 缓存
    # ------------------------------------------------------------------

    def _cache_path(self, symbol: str) -> Path:
        return _CACHE_DIR / f"{symbol}.csv"

    def _load_csv_cache(self, symbol: str) -> pd.DataFrame:
        path = self._cache_path(symbol)
        if not path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:
            return pd.DataFrame()

    def _save_csv_cache(self, symbol: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        path = self._cache_path(symbol)
        try:
            existing = self._load_csv_cache(symbol)
            if not existing.empty:
                merged = pd.concat([existing, df], ignore_index=True)
                merged = merged.drop_duplicates(subset=["date"], keep="last")
                df = merged
            df = df.sort_values("date").reset_index(drop=True)
            df.to_csv(path, index=False)
        except Exception as e:
            logger.warning("个股资金流缓存写入失败 %s: %s", symbol, e)


# 模块级便捷函数
def get_money_flow(symbol: str, weeks: int = 4) -> Optional[MoneyFlowSnapshot]:
    return CapitalFlowProvider().get_money_flow(symbol, weeks=weeks)
