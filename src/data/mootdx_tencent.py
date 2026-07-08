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
from .schema import Bar, Financials, Quote, Resolution

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

            # mootdx 返回 pandas DataFrame，字段名为拼音
            # 需要先提取标量再计算，避免 Series 布尔判断报错
            revenue_val = self._safe_float(fin.get("zhuyingshouru", 0)) or 0.0
            net_profit_val = self._safe_float(fin.get("jinglirun", 0)) or 0.0
            total_assets_val = self._safe_float(fin.get("total_assets", fin.get("zongzichan", 0))) or 0.0
            liudong = self._safe_float(fin.get("liudongfuzhai", 0)) or 0.0
            changqi = self._safe_float(fin.get("changqifuzhai", 0)) or 0.0
            total_liab = self._safe_float(fin.get("total_liabilities", liudong + changqi)) or 0.0

            # 计算 ROE = 净利润 / (总资产 - 总负债) × 100%
            equity = total_assets_val - total_liab
            roe = round(net_profit_val / equity * 100, 2) if equity > 0 else None

            # 计算 EPS = 净利润 / 总股本
            total_shares = self._safe_float(fin.get("zongguben", 0)) or 0.0
            eps = round(net_profit_val / total_shares, 4) if total_shares > 0 else None

            results.append(Financials(
                symbol=symbol,
                report_period=period,
                revenue=revenue_val,
                net_profit=net_profit_val,
                total_assets=total_assets_val,
                total_liabilities=total_liab,
                operating_cash_flow=self._safe_float(fin.get("jingyingxianjinliu", None)),
                roe=roe,
                eps=eps,
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
    # Bars — 日线 + 分钟线 (Resolution→Bar 结构化输出)
    # ------------------------------------------------------------------

    # mootdx frequency codes: 0=5min, 2=15min, 4=30min, 5=60min, 8=1min, 9=daily
    _RESOLUTION_TO_TDX_FREQ: dict[Resolution, int] = {
        Resolution.MIN_1: 8,
        Resolution.MIN_5: 0,
        Resolution.DAY: 9,
        Resolution.WEEK: 5,
        Resolution.MONTH: 6,
    }

    # 分钟数据日系数 ≈ 每日交易分钟数
    _INTRADAY_BARS_PER_DAY: dict[Resolution, int] = {
        Resolution.MIN_1: 240,
        Resolution.MIN_5: 48,
    }

    def get_bars(
        self, symbol: str, resolution: Resolution,
        start: str = "", end: str = "", market: str = "SH",
    ) -> list[Bar]:
        """获取历史 Bar 列表（结构化输出）。

        Args:
            symbol: 6 位股票代码
            resolution: 时间分辨率
            start: 起始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD
            market: 市场 SH/SZ

        Returns:
            Bar 列表，按 timestamp 升序排列
        """
        freq = self._RESOLUTION_TO_TDX_FREQ.get(resolution)
        if freq is None:
            logger.warning("mootdx 不支持分辨率 %s", resolution)
            return []

        client = self._get_tdx_client()
        if client is None:
            return []

        # 计算 offset
        offset = self._calc_offset(resolution, start)

        try:
            raw = client.bars(symbol=symbol, frequency=freq, offset=offset)
            if raw is None or len(raw) == 0:
                return []
        except Exception as e:
            logger.debug("mootdx bars failed for %s (%s): %s", symbol, resolution.value, e)
            return []

        return self._parse_bars(raw, symbol, resolution, start, end)

    def _calc_offset(self, resolution: Resolution, start_date: str) -> int:
        """计算 mootdx bars 需要的 offset 参数。

        分钟数据 offset 基于日数 × 每日 bar 数（避免拉不够），
        日线 offset 基于日数 + buffer。
        """
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                days_diff = max((datetime.now() - start_dt).days, 1)
            except ValueError:
                days_diff = 30
        else:
            days_diff = 30

        if resolution.is_intraday:
            bars_per_day = self._INTRADAY_BARS_PER_DAY.get(resolution, 240)
            # 最少拉一天的分钟数据，且不超过 mootdx 单次上限 800
            return max(min(days_diff * bars_per_day, 800), bars_per_day)
        return min(days_diff + 50, 2000)

    def _parse_bars(
        self, raw, symbol: str, resolution: Resolution,
        start_date: str, end_date: str,
    ) -> list[Bar]:
        """mootdx 原始 DataFrame → Bar 列表。"""
        import pandas as _pd
        import numpy as _np
        df = _pd.DataFrame(raw)

        # 列名映射: mootdx 返回列名因 frequency 而异
        col_map = {
            "datetime": "timestamp", "open": "open", "close": "close",
            "high": "high", "low": "low", "vol": "volume",
            "amount": "amount",
        }
        df = df.rename(columns={
            k: v for k, v in col_map.items() if k in df.columns
        })

        # 过滤日期范围
        if "timestamp" in df.columns:
            df["timestamp"] = _pd.to_datetime(df["timestamp"])
            if start_date:
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                df = df[df["timestamp"] >= start_dt]
            if end_date:
                end_dt = datetime.strptime(end_date, "%Y%m%d") + _pd.Timedelta(days=1)
                df = df[df["timestamp"] < end_dt]
            df = df.sort_values("timestamp")

        # 安全读取列的函数 — 处理 pandas Series 和缺失列
        cols = set(df.columns)
        def _val(row, col_name, default=0.0):
            if col_name not in cols:
                return default
            v = row[col_name]
            try:
                return float(v) if not _np.isnan(float(v)) else default
            except (ValueError, TypeError):
                return default

        bars = []
        for _, row in df.iterrows():
            bars.append(Bar(
                symbol=symbol,
                timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                resolution=resolution,
                open=_val(row, "open", 0.0),
                high=_val(row, "high", 0.0),
                low=_val(row, "low", 0.0),
                close=_val(row, "close", 0.0),
                volume=int(_val(row, "volume", 0.0)),
                amount=_val(row, "amount", 0.0),
                source=self.source_name,
            ))
        return bars

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
