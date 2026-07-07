"""mootdx + 腾讯财经 DataProvider — 不封IP，零鉴权，a-stock-data 模式。

mootdx (TCP 7709): K线 + 五档盘口 + 逐笔成交 + 财务快照 + F10
腾讯财经 (HTTP):   PE/PB/市值/换手率/涨跌停/指数/ETF

优先级: mootdx/腾讯 > AKShare (保留为降级)
"""

from __future__ import annotations

import logging
import socket
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import DataProvider
from .schema import Financials, Quote

logger = logging.getLogger(__name__)

# ── mootdx server list (2026-06 verified) ────────────────────────────
_TDX_SERVERS = [
    ("119.97.185.59", 7709), ("124.70.133.119", 7709), ("116.205.183.150", 7709),
    ("123.60.73.44", 7709), ("116.205.163.254", 7709), ("121.36.225.169", 7709),
    ("123.60.70.228", 7709), ("124.71.9.153", 7709), ("110.41.147.114", 7709),
    ("124.71.187.122", 7709),
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class MootdxTencentProvider(DataProvider):
    """mootdx (行情+K线+财务) + 腾讯财经 (估值+市值) 混合适配器。

    source_name = "mootdx+tencent"
    """

    source_name = "mootdx+tencent"

    def __init__(self):
        self._tdx_client = None
        self._tdx_available: Optional[bool] = None  # None = not probed
        self._tencent_cache: dict[str, tuple[datetime, dict]] = {}
        self._tencent_ttl = timedelta(seconds=30)  # 腾讯行情 30s 缓存
        self._quote_cache: dict[str, tuple[datetime, Quote]] = {}
        self._quote_ttl = timedelta(seconds=15)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        return self._probe_tdx() or self._probe_tencent()

    # ------------------------------------------------------------------
    # Quote — 腾讯财经 primary, mootdx supplement
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        cache_key = f"{symbol}:{market}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Primary: 腾讯财经 (PE/PB/市值/换手率/涨跌停)
        tq = self._fetch_tencent_quote(symbol, market)
        if tq is None:
            return None

        # Supplement: mootdx 五档盘口 (optional, best-effort)
        tdx_data = self._fetch_tdx_quote(symbol, market)

        quote = Quote(
            symbol=symbol,
            name=tq.get("name", ""),
            price=tq.get("price", 0.0),
            change_pct=tq.get("change_pct", 0.0),
            volume=int(tq.get("volume", 0)),
            turnover=tq.get("turnover", 0.0),
            high=tq.get("high"),
            low=tq.get("low"),
            open=tq.get("open"),
            prev_close=tq.get("prev_close"),
            limit_up=tq.get("limit_up"),
            limit_down=tq.get("limit_down"),
            pe_ttm=tq.get("pe_ttm"),
            pe_static=tq.get("pe_static"),
            pb=tq.get("pb"),
            market_cap=(tq.get("mcap_yi") or 0) * 1e8 if tq.get("mcap_yi") else None,
            source=self.source_name,
        )
        self._cache_set(cache_key, quote)
        return quote

    def get_quotes_batch(self, symbols: list[str], markets: list[str] | None = None) -> list[Quote]:
        """Batch: 腾讯财经一次请求支持多只股票。"""
        quotes = []
        prefixed = []
        for s in symbols:
            p = self._tencent_prefix(s)
            prefixed.append(p)

        if not prefixed:
            return []

        try:
            url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("gbk")

            for line in data.strip().split(";"):
                if not line.strip() or "=" not in line or '"' not in line:
                    continue
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                if len(vals) < 53:
                    continue
                code = key[2:]
                quote = Quote(
                    symbol=code,
                    name=vals[1],
                    price=float(vals[3]) if vals[3] else 0,
                    change_pct=float(vals[32]) if vals[32] else 0,
                    volume=int(float(vals[6] or 0)),
                    turnover=float(vals[37]) * 10000 if vals[37] else 0,  # 万→元
                    high=float(vals[33]) if vals[33] else None,
                    low=float(vals[34]) if vals[34] else None,
                    open=float(vals[5]) if vals[5] else None,
                    prev_close=float(vals[4]) if vals[4] else None,
                    limit_up=float(vals[47]) if vals[47] else None,
                    limit_down=float(vals[48]) if vals[48] else None,
                    pe_ttm=float(vals[39]) if vals[39] else None,
                    pe_static=float(vals[52]) if vals[52] else None,
                    pb=float(vals[46]) if vals[46] else None,
                    market_cap=float(vals[44]) * 1e8 if vals[44] else None,  # 亿→元
                    source=self.source_name,
                )
                quotes.append(quote)
        except Exception as e:
            logger.debug("Tencent batch quote failed: %s", e)

        return quotes

    # ------------------------------------------------------------------
    # Financials — mootdx finance (37 fields quarterly)
    # ------------------------------------------------------------------

    def get_financials(self, symbol: str, market: str = "SH", count: int = 4) -> list[Financials]:
        results = []
        try:
            client = self._get_tdx_client()
            if client is None:
                return results

            fin = client.finance(symbol=symbol)
            # mootdx finance returns 37 fields
            if fin is None or len(fin) == 0:
                return results

            # Map mootdx fields to Financials model
            eps = self._safe_float(fin.get("eps", 0))
            bvps = self._safe_float(fin.get("bvps", 0))
            # Report period from mootdx is current quarter
            now = datetime.now()
            period = f"{now.year}Q{(now.month - 1) // 3 + 1}"

            results.append(Financials(
                symbol=symbol,
                report_period=period,
                revenue=self._safe_float(fin.get("income", 0)),
                net_profit=self._safe_float(fin.get("profit", 0)),
                total_assets=self._safe_float(fin.get("total_assets", fin.get("zongzichan", 0))),
                total_liabilities=self._safe_float(fin.get("total_liabilities", fin.get("zongfuzhai", 0))),
                operating_cash_flow=None,  # mootdx finance doesn't have cash flow
                source=self.source_name,
            ))

            # For older quarters, use F10 if available (best effort)
            if count > 1 and len(results) < count:
                try:
                    f10_text = client.F10(symbol=symbol, name="财务分析")
                    if f10_text:
                        # F10 has text blocks per quarter — extract what we can
                        pass
                except Exception:
                    pass
        except Exception as e:
            logger.debug("mootdx financials failed for %s: %s", symbol, e)

        return results

    # ------------------------------------------------------------------
    # History K-line — mootdx bars
    # ------------------------------------------------------------------

    def get_history(
        self, symbol: str, period: str = "daily",
        start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        """获取历史K线。

        频率映射: daily=9, weekly=5, monthly=6
        ⚠️ mootdx bars 返回不复权原始价
        """
        freq_map = {"daily": 9, "weekly": 5, "monthly": 6, "1min": 8, "5min": 0}
        frequency = freq_map.get(period, 9)

        # Determine offset
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                days_diff = (datetime.now() - start_dt).days
                if period in ("1min", "5min"):
                    offset = min(days_diff * 48, 800)  # Cap for minute data
                else:
                    offset = min(days_diff + 50, 2000)
            except ValueError:
                offset = 200
        else:
            offset = 200

        try:
            client = self._get_tdx_client()
            if client is None:
                return pd.DataFrame()

            bars = client.bars(symbol=symbol, frequency=frequency, offset=offset)
            if bars is None or len(bars) == 0:
                return pd.DataFrame()

            df = pd.DataFrame(bars)
            df = df.rename(columns={
                "datetime": "日期", "open": "开盘", "close": "收盘",
                "high": "最高", "low": "最低", "vol": "成交量", "amount": "成交额",
            })
            # Filter date range
            if "日期" in df.columns and start_date:
                start = datetime.strptime(start_date, "%Y%m%d")
                df = df[df["日期"] >= start]
            return df
        except Exception as e:
            logger.debug("mootdx history failed for %s: %s", symbol, e)
            return pd.DataFrame()

    def get_all_quotes(self) -> list[Quote]:
        """全市场扫描 — mootdx 不支持，返回空列表（走 AKShare 降级）。"""
        return []

    # ------------------------------------------------------------------
    # Internal: 腾讯财经
    # ------------------------------------------------------------------

    @staticmethod
    def _tencent_prefix(symbol: str) -> str:
        if symbol.startswith(("6", "9")):
            return f"sh{symbol}"
        elif symbol.startswith("8"):
            return f"bj{symbol}"
        return f"sz{symbol}"

    def _fetch_tencent_quote(self, symbol: str, market: str) -> Optional[dict]:
        prefix = self._tencent_prefix(symbol)
        try:
            url = f"https://qt.gtimg.cn/q={prefix}"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("gbk")
            vals = data.split('"')[1].split("~") if '"' in data else []
            if len(vals) < 53:
                return None
            return {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "prev_close": float(vals[4]) if vals[4] else None,
                "open": float(vals[5]) if vals[5] else None,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "high": float(vals[33]) if vals[33] else None,
                "low": float(vals[34]) if vals[34] else None,
                "volume": int(float(vals[6] or 0)),
                "turnover": float(vals[37]) * 10000 if vals[37] else 0,  # 万→元
                "limit_up": float(vals[47]) if vals[47] else None,
                "limit_down": float(vals[48]) if vals[48] else None,
                # Additional fields for FundamentalMetrics
                "pe_ttm": float(vals[39]) if vals[39] else None,
                "pb": float(vals[46]) if vals[46] else None,
                "mcap_yi": float(vals[44]) if vals[44] else None,  # 总市值(亿)
                "float_mcap_yi": float(vals[45]) if vals[45] else None,  # 流通市值(亿)
                "turnover_pct": float(vals[38]) if vals[38] else None,
                "pe_static": float(vals[52]) if vals[52] else None,
            }
        except Exception as e:
            logger.debug("Tencent quote failed for %s: %s", symbol, e)
        return None

    # ------------------------------------------------------------------
    # Internal: mootdx
    # ------------------------------------------------------------------

    @staticmethod
    def _probe(ip: str, port: int, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _probe_tdx(self) -> bool:
        if self._tdx_available is True:
            return True
        for ip, port in _TDX_SERVERS:
            if self._probe(ip, port):
                self._tdx_available = True
                return True
        self._tdx_available = False
        return False

    def _probe_tencent(self) -> bool:
        try:
            url = "https://qt.gtimg.cn/q=sh600519"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            resp = urllib.request.urlopen(req, timeout=5)
            data = resp.read().decode("gbk")
            return "600519" in data
        except Exception:
            return False

    def _get_tdx_client(self):
        if self._tdx_client is not None:
            return self._tdx_client
        if not self._probe_tdx():
            return None
        try:
            from mootdx.quotes import Quotes
            for ip, port in _TDX_SERVERS:
                if self._probe(ip, port, timeout=1.0):
                    self._tdx_client = Quotes.factory(market="std", server=(ip, port))
                    return self._tdx_client
            self._tdx_client = Quotes.factory(market="std", bestip=True)
            return self._tdx_client
        except Exception as e:
            logger.debug("mootdx client creation failed: %s", e)
            self._tdx_available = False
            return None

    def _fetch_tdx_quote(self, symbol: str, market: str) -> Optional[dict]:
        """Fetch mootdx real-time quote (46 fields, best-effort)."""
        try:
            client = self._get_tdx_client()
            if client is None:
                return None
            quotes = client.quotes(symbol=[symbol])
            if quotes is None or len(quotes) == 0:
                return None
            return quotes.iloc[0].to_dict() if hasattr(quotes, "iloc") else quotes[0]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(val, default=None):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _cache_get(self, key: str) -> Optional[Quote]:
        entry = self._quote_cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > self._quote_ttl:
            del self._quote_cache[key]
            return None
        return val

    def _cache_set(self, key: str, val: Quote):
        self._quote_cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._quote_cache.clear()
        self._tencent_cache.clear()
