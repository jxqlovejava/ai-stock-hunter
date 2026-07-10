# -*- coding: utf-8 -*-
"""国信证券数据适配器。

封装国信证券 REST API：
  - gs-stock-market-query: 实时行情、历史K线、资金流向、涨跌幅排名
  - gs-stock-financial-query: 财务三表（利润表/资产负债表/现金流量表）
  - gs-economy-query: 宏观经济数据

认证: GS_API_KEY 环境变量 (支持多 Key 逗号分隔，日限额耗尽自动 fallback)
"""

from __future__ import annotations

import logging
import os
import re
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from .base import DataProvider

logger = logging.getLogger(__name__)


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
    """国信证券数据适配器。

    Key 耗尽状态为类级别，跨实例共享，避免每次新建实例时
    已耗尽的 Key 被反复重试浪费配额。
    """

    source_name = "guosen"

    BASE_URL = "https://dgzt.guosen.com.cn/skills"
    TIMEOUT = 15

    QUOTA_EXCEEDED_CODE = 197006  # 日限额耗尽

    # 类级别 Key 耗尽状态 (按 Key 字符串索引，跨实例共享)
    _class_exhausted: set[str] = set()
    _class_last_reset_date: datetime | None = None

    @staticmethod
    def _load_dotenv_gs_key() -> str | None:
        """从项目 .env 文件加载 GS_API_KEY。"""
        from pathlib import Path
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        if not env_file.is_file():
            return None
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "GS_API_KEY":
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            pass
        return None

    def __init__(self, api_key: str | None = None):
        # 支持多 Key: 逗号分隔 或 GS_API_KEY_2/3
        # 优先级: 显式传入 > .env 文件 > 环境变量
        raw = api_key or self._load_dotenv_gs_key() or os.environ.get("GS_API_KEY", "")
        self._api_keys: list[str] = []
        for part in raw.split(","):
            k = part.strip()
            if k:
                self._api_keys.append(k)
        for i in range(2, 10):
            extra = os.environ.get(f"GS_API_KEY_{i}", "")
            if extra.strip():
                self._api_keys.append(extra.strip())

        if not self._api_keys:
            raise RuntimeError(
                "GS_API_KEY 未配置。请设置环境变量 GS_API_KEY 或传入 api_key 参数。"
                " 支持多 Key 逗号分隔: GS_API_KEY=key1,key2"
            )

        self._session = requests.Session()
        self._session.trust_env = False  # 禁止读取系统代理，避免代理工具干扰国信 API 连接
        self._session.mount("https://", _LegacySSLAdapter())
        # 首个可用 Key 作为初始 active
        self._active_idx = self._first_available_idx()
        logger.info("国信: %d 个 Key 已加载，当前 Key #%d", len(self._api_keys), self._active_idx + 1)

    # ── Key 管理 (类级别状态) ─────────────────────────────────

    @classmethod
    def _maybe_reset_quota(cls):
        """跨日自动重置 Key 耗尽状态（类级别）。"""
        today = datetime.now().date()
        if cls._class_last_reset_date != today:
            cls._class_exhausted.clear()
            cls._class_last_reset_date = today
            logger.info("国信: 新的一天，Key 配额已重置")

    @property
    def _active_key(self) -> str:
        return self._api_keys[self._active_idx]

    @property
    def _params(self) -> dict:
        return {"softName": "agent_skills", "apiKey": self._active_key}

    def _first_available_idx(self) -> int:
        """找到第一个未被类级别标记为耗尽的 Key 索引。"""
        self._maybe_reset_quota()
        for i, k in enumerate(self._api_keys):
            if k not in self._class_exhausted:
                return i
        # 全部耗尽也返回 0，后续 _switch_key 会处理
        return 0

    def _is_quota_exceeded(self, response_data: dict) -> bool:
        """检查响应是否为日限额耗尽。"""
        result = response_data.get("result", {})
        if isinstance(result, list) and len(result) > 0:
            return result[0].get("code", 0) == self.QUOTA_EXCEEDED_CODE
        if isinstance(result, dict):
            return result.get("code", 0) == self.QUOTA_EXCEEDED_CODE
        return False

    def _switch_key(self) -> bool:
        """日限额耗尽时切换 Key。返回 False=全部耗尽。"""
        self._maybe_reset_quota()
        # 标记当前 Key 为耗尽 (类级别，跨实例生效)
        self._class_exhausted.add(self._active_key)
        logger.warning("国信 Key #%d 日限额耗尽，切换", self._active_idx + 1)
        for i, k in enumerate(self._api_keys):
            if k not in self._class_exhausted:
                self._active_idx = i
                logger.info("国信 → Key #%d", i + 1)
                return True
        logger.error("国信: 全部 %d 个 Key 日限额已耗尽", len(self._api_keys))
        return False

    def _try_request(self, url: str, params: dict, timeout: int = 0) -> tuple[Optional[dict], bool]:
        """发起请求，返回 (响应 dict, 是否全部 Key 耗尽)。

        若响应为 197006 日限额耗尽，自动切换 Key 并重试。
        调用方根据返回值决定是否继续。
        """
        timeout = timeout or self.TIMEOUT
        while True:
            try:
                r = self._session.get(
                    url,
                    params={**self._params, **params},
                    timeout=timeout,
                    proxies={"http": None, "https": None},
                )
                d = r.json()
                if self._is_quota_exceeded(d):
                    if not self._switch_key():
                        return None, True  # 全部耗尽
                    continue  # 切换成功，用新 Key 重试
                return d, False
            except Exception:
                return None, False

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情。"""
        set_code = self._market_to_set_code(market)
        url = f"{self.BASE_URL}/gsnews/market/agentbot/queryHQInfo/1.0"
        d, exhausted = self._try_request(url, {
            "code": symbol, "setCode": set_code, "target": 0,
        })
        if exhausted or d is None:
            return None
        try:
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
        d, exhausted = self._try_request(url, {
            "code": ",".join(symbols),
            "setCode": ",".join(set_codes),
            "target": 0,
        })
        if exhausted or d is None:
            return []
        try:
            data_list = d.get("data", [])
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
        d, exhausted = self._try_request(url, {
            "code": symbol, "market": market, "count": str(count),
        })
        if exhausted or d is None:
            return []
        try:
            result = d.get("result", [{}])
            first_code = result[0].get("code") if isinstance(result, list) else result.get("code")
            if first_code != 0:
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
        d, exhausted = self._try_request(url, {
            "code": symbol, "setCode": str(set_code), "wantNums": days,
        })
        if exhausted or d is None:
            return []
        try:
            data = d.get("data", {})
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
        d, exhausted = self._try_request(url, {"query": query}, timeout=30)
        if exhausted or d is None:
            return None
        try:
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
        """测试 API 连通性（自动 fallback 到可用 Key）。"""
        url = f"{self.BASE_URL}/gsnews/market/agentbot/queryHQInfo/1.0"
        d, exhausted = self._try_request(url, {
            "code": "600519", "setCode": 1, "target": 0,
        }, timeout=10)
        if exhausted or d is None:
            return False
        result = d.get("result", {})
        if isinstance(result, list) and len(result) > 0:
            return result[0].get("code", -1) == 0
        if isinstance(result, dict):
            return result.get("code", -1) == 0
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
