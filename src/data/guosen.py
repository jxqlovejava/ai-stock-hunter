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
from datetime import datetime, timedelta
from typing import Optional

import requests

from .base import DataProvider
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
            r = requests.get(
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
            data = d.get("data", {})
            if not data or not isinstance(data, dict):
                return None
            return Quote(
                symbol=symbol,
                name=data.get("name", ""),
                price=float(data.get("now", 0)),
                change_pct=float(data.get("priceChangePct", 0)),
                volume=int(float(data.get("vol", 0)) * 100) if data.get("vol") else 0,
                turnover=self._parse_amount(data.get("amount")),
                high=float(data.get("max", 0)) if data.get("max") else None,
                low=float(data.get("min", 0)) if data.get("min") else None,
                open=float(data.get("open", 0)) if data.get("open") else None,
                prev_close=float(data.get("close", 0)) if data.get("close") else None,
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
            r = requests.get(
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
            r = requests.get(
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
            return self._parse_financials(symbol, d.get("data", {}))
        except Exception:
            return []

    def _parse_financials(self, symbol: str, data: dict) -> list[Financials]:
        """解析国信财务数据为 Financials 列表。"""
        results = []
        if not data or not isinstance(data, dict):
            return results
        # 国信返回结构: data.info[] 含字段元数据，data.records[] 含数据行
        records = data.get("records", [])
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
            r = requests.get(
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
            r = requests.get(
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

    def health_check(self) -> bool:
        """测试 API 连通性。"""
        try:
            r = requests.get(
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
