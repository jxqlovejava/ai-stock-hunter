# -*- coding: utf-8 -*-
"""国信证券数据适配器。

封装国信证券 REST API：
  - gs-stock-market-query: 实时行情、历史K线、资金流向、涨跌幅排名
  - gs-stock-financial-query: 财务三表（利润表/资产负债表/现金流量表）
  - gs-economy-query: 宏观经济数据

认证: GS_API_KEY 环境变量
"""

from __future__ import annotations

import os
import ssl
from datetime import datetime, timedelta
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from .base import DataProvider


class _LegacySSLAdapter(HTTPAdapter):
    """允许与使用旧版 SSL 的服务器（如国信 API）进行 TLS 重新协商。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        # 允许旧版不安全的 TLS 重新协商
        ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)
from .schema import Financials, Quote


class GuosenProvider(DataProvider):
    """国信证券数据适配器。"""

    source_name = "guosen"

    BASE_URL = "https://dgzt.guosen.com.cn/skills"
    TIMEOUT = 15

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("GS_API_KEY", "")
        if not self._api_key:
            raise RuntimeError(
                "GS_API_KEY 未配置。请设置环境变量 GS_API_KEY 或传入 api_key 参数。"
            )
        # 创建带旧版 SSL 支持的 session（国信 API 服务器使用旧 TLS）
        self._session = requests.Session()
        self._session.mount("https://", _LegacySSLAdapter())

    @property
    def _params(self) -> dict:
        return {"softName": "agent_skills", "apiKey": self._api_key}

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情。"""
        set_code = self._market_to_set_code(market)
        url = f"{self.BASE_URL}/gsnews/market/agentbot/queryHQInfo/1.0"
        try:
            r = self._session.get(
                url,
                params={
                    **self._params,
                    "code": symbol,
                    "setCode": set_code,
                    "target": 0,
                },
                timeout=self.TIMEOUT,
                proxies={"http": None, "https": None},
            )
            d = r.json()
            # 单个查询返回 {"result":..., "object":{...}}
            # 批量查询返回 {"result":..., "data":[...]} 或 {"result":..., "object":{...}}
            data = d.get("object") or d.get("data", {})
            if not data or not isinstance(data, dict):
                return None
            return Quote(
                symbol=symbol,
                name=data.get("name", ""),
                price=self._safe_float(data.get("now", 0)),
                change_pct=self._safe_float(data.get("priceChangePct", 0)),
                volume=self._parse_volume(data.get("vol", 0)),
                turnover=self._parse_amount(data.get("amount")),
                high=self._safe_float(data.get("max")) if data.get("max") else None,
                low=self._safe_float(data.get("min")) if data.get("min") else None,
                open=self._safe_float(data.get("open")) if data.get("open") else None,
                prev_close=self._safe_float(data.get("close")) if data.get("close") else None,
                source=self.source_name,
            )
        except Exception:
            return None

    def get_quotes_batch(
        self, symbols: list[str], markets: list[str]
    ) -> list[Quote]:
        """批量获取实时行情（最多 10 只/次）。"""
        url = f"{self.BASE_URL}/gsnews/market/agentbot/queryCombHQ/1.0"
        set_codes = [str(self._market_to_set_code(m)) for m in markets]
        try:
            r = self._session.get(
                url,
                params={
                    **self._params,
                    "code": ",".join(symbols),
                    "setCode": ",".join(set_codes),
                    "target": 0,
                },
                timeout=self.TIMEOUT,
                proxies={"http": None, "https": None},
            )
            data_list = r.json().get("data", [])
            if not isinstance(data_list, list):
                return []
            results = []
            for item in data_list:
                results.append(
                    Quote(
                        symbol=item.get("code", ""),
                        name=item.get("name", ""),
                        price=float(item.get("now", 0)) if item.get("now") else 0.0,
                        change_pct=float(item.get("priceChangePct", 0)),
                        volume=int(float(item.get("vol", 0)) * 100)
                        if item.get("vol")
                        else 0,
                        turnover=self._parse_amount(item.get("amount")),
                        high=float(item.get("max", 0)) if item.get("max") else None,
                        low=float(item.get("min", 0)) if item.get("min") else None,
                        open=float(item.get("open", 0)) if item.get("open") else None,
                        prev_close=float(item.get("close", 0))
                        if item.get("close")
                        else None,
                        source=self.source_name,
                    )
                )
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Financials
    # ------------------------------------------------------------------

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取最近 N 期利润表数据。"""
        url = f"{self.BASE_URL}/gsnews/gsf10/financial/incomeStatement/1.0"
        try:
            r = self._session.get(
                url,
                params={
                    **self._params,
                    "code": symbol,
                    "market": market,
                    "count": str(count),
                },
                timeout=self.TIMEOUT,
                proxies={"http": None, "https": None},
            )
            d = r.json()
            if d.get("result", [{}])[0].get("code") != 0 if isinstance(d.get("result"), list) else True:
                return []
            # API 返回 income (利润表) / balance (资产负债表) / cashflow (现金流量表)
            income_data = d.get("income") or d.get("data", {})
            return self._parse_financials(symbol, income_data)
        except Exception:
            return []

    def _parse_financials(self, symbol: str, data) -> list[Financials]:
        """解析国信财务数据为 Financials 列表。

        支持两种格式:
          1. list: income[] 直接包含各期数据 (利润表 API)
          2. dict: {"records": [...]} (旧格式/其他报表)
        """
        results = []
        # 统一转为记录列表
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("records", [])
        else:
            return results
        if not records:
            return results
        for rec in records:
            if not isinstance(rec, dict):
                continue
            try:
                results.append(
                    Financials(
                        symbol=symbol,
                        report_period=rec.get("reportDate", ""),
                        revenue=self._safe_float(rec.get("totalRevenue")),
                        net_profit=self._safe_float(rec.get("netProfit")),
                        total_assets=self._safe_float(rec.get("totalAssets")),
                        total_liabilities=self._safe_float(rec.get("totalLiabilities")),
                        operating_cash_flow=self._safe_float(
                            rec.get("operatingCashFlow")
                        ),
                        source=self.source_name,
                    )
                )
            except Exception:
                continue
        return results

    # ------------------------------------------------------------------
    # Historical K-line
    # ------------------------------------------------------------------

    def get_history(
        self, symbol: str, market: str = "SH", days: int = 20
    ) -> list[dict]:
        """获取历史 K 线数据。"""
        url = f"{self.BASE_URL}/gsnews/market/agentbot/queryPastHQInfo/1.0"
        set_code = self._market_to_set_code(market)
        try:
            r = self._session.get(
                url,
                params={
                    **self._params,
                    "code": symbol,
                    "setCode": str(set_code),
                    "wantNums": days,
                },
                timeout=self.TIMEOUT,
                proxies={"http": None, "https": None},
            )
            data = r.json().get("data", {})
            if isinstance(data, dict):
                return data.get("kLines", data.get("records", []))
            return []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Macro
    # ------------------------------------------------------------------

    def get_macro(self, query: str) -> str | None:
        """查询宏观经济数据。返回 Markdown 文本。"""
        url = f"{self.BASE_URL}/gsnews/macro/queryMacro/1.0"
        try:
            r = self._session.get(
                url,
                params={**self._params, "query": query},
                timeout=30,
                proxies={"http": None, "https": None},
            )
            d = r.json()
            return d.get("data", {}).get("content", "") if d.get("data") else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(val) -> float:
        """安全转换为 float，支持 "1.49万" 等中文格式。"""
        if val is None or val == "":
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace(",", "").replace("%", "").strip()
        # 中文单位转换
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        if "亿" in s:
            return float(s.replace("亿", "")) * 100000000
        try:
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_volume(val) -> int:
        """解析成交量，支持 "1.49万手" / "14900" 等格式，返回股数。"""
        if val is None or val == "":
            return 0
        if isinstance(val, (int, float)):
            return int(val) if val > 1000 else int(val * 100)
        s = str(val).replace(",", "").strip()
        multiplier = 100  # 默认手→股
        if "万" in s:
            s = s.replace("万", "")
            multiplier = 10000 * 100  # 万手→股
        elif "亿" in s:
            s = s.replace("亿", "")
            multiplier = 100000000 * 100
        try:
            return int(float(s) * multiplier)
        except ValueError:
            return 0

    def health_check(self) -> bool:
        """测试 API 连通性。"""
        try:
            r = self._session.get(
                f"{self.BASE_URL}/gsnews/market/agentbot/queryHQInfo/1.0",
                params={**self._params, "code": "600519", "setCode": 1, "target": 0},
                timeout=10,
                proxies={"http": None, "https": None},
            )
            d = r.json()
            code = (
                d.get("result", [{}])[0].get("code", -1)
                if isinstance(d.get("result"), list)
                else d.get("result", {}).get("code", -1)
            )
            return code == 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _market_to_set_code(market: str) -> int:
        """市场代码 → setCode。"""
        mapping = {"SH": 1, "SZ": 0, "BJ": 2, "HK": -1, "US": 74}
        return mapping.get(market, 0)

    @staticmethod
    def _safe_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_amount(val) -> float | None:
        """解析金额字符串（如 '40.99亿'）。"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            s = str(val).strip()
            if s.endswith("亿"):
                return float(s[:-1]) * 1e8
            if s.endswith("万"):
                return float(s[:-1]) * 1e4
            return float(s)
        except (ValueError, TypeError):
            return None
