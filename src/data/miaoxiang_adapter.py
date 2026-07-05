# -*- coding: utf-8 -*-
"""妙想 Skill CLI 适配器。

封装对 mx-data / mx-search / mx-xuangu / mx-moni / mx-poster
Python 脚本的 subprocess 调用。处理超时、重试、JSON 解析和错误降级。

所有公开方法失败时返回 None（与 DataProvider 降级语义一致）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 脚本路径 ──────────────────────────────────────────────
_SKILLS_DIR = Path.home() / ".claude" / "skills"

_SCRIPT_PATHS = {
    "mx-data": _SKILLS_DIR / "mx-data" / "mx_data.py",
    "mx-search": _SKILLS_DIR / "mx-search" / "mx_search.py",
    "mx-xuangu": _SKILLS_DIR / "mx-xuangu" / "mx_xuangu.py",
    "mx-moni": _SKILLS_DIR / "mx-moni" / "mx_moni.py",
    "mx-poster": _SKILLS_DIR / "mx-poster" / "mx_poster.py",
}

TIMEOUT = 30  # 秒
MAX_RETRIES = 2


class MiaoXiangAdapter:
    """妙想 Skill CLI 调用适配器。

    用法:
        adapter = MiaoXiangAdapter()
        data = adapter.query_data("贵州茅台最新价 涨跌幅")
        news = adapter.search_news("贵州茅台最新研报")
    """

    def __init__(self, api_key: str | None = None, output_dir: str | None = None):
        # 显式传入 None 时从环境变量读取；显式传入空字符串 "" 视为无 key
        if api_key is None:
            self._api_key = os.environ.get("MX_APIKEY", "")
        else:
            self._api_key = api_key
        self._output_dir = output_dir or tempfile.mkdtemp(prefix="mx_output_")
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=5)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """快速连通性检查：检查脚本是否存在 + API key 是否配置。"""
        if not self._api_key:
            logger.warning("MX_APIKEY 未配置")
            return False
        data_script = _SCRIPT_PATHS.get("mx-data")
        if data_script and data_script.exists():
            return True
        logger.warning("mx-data 脚本未找到: %s", data_script)
        return False

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # mx-data: 金融数据 NL 查询
    # ------------------------------------------------------------------

    def query_data(self, query: str) -> Optional[dict]:
        """调用 mx-data 查询金融数据。返回解析后的 JSON dict，失败返回 None。"""
        return self._run_skill("mx-data", query)

    def query_financials(self, symbol: str, metrics: str = "净利润 营业收入 ROE") -> Optional[dict]:
        """查询个股财务数据。"""
        query = f"{symbol} {metrics} 近三年"
        return self.query_data(query)

    def query_related_parties(self, symbol: str) -> Optional[list[dict]]:
        """查询个股关联关系（股东/高管/子公司）。"""
        result = self.query_data(f"{symbol} 十大股东 关联公司")
        if result is None:
            return None
        # 提取 entityTagDTOList
        try:
            entity_list = result.get("data", {}).get("entityTagDTOList", [])
            return entity_list if entity_list else None
        except Exception:
            return None

    def query_main_force_flow(self, symbol: str) -> Optional[dict]:
        """查询个股主力资金流向。"""
        return self.query_data(f"{symbol} 主力资金流向")

    # ------------------------------------------------------------------
    # mx-search: 金融资讯搜索
    # ------------------------------------------------------------------

    def search_news(self, query: str) -> Optional[list[dict]]:
        """调用 mx-search 搜索金融资讯。返回资讯条目列表。"""
        result = self._run_skill("mx-search", query)
        if result is None:
            return None
        # mx-search 返回格式：顶层含 title / trunk / secuList
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            items = result.get("data", result.get("items", [result]))
            return items if isinstance(items, list) else [items]
        return None

    def search_announcements(self, symbol: str) -> Optional[list[dict]]:
        """搜索个股最新公告。"""
        return self.search_news(f"{symbol} 最新公告")

    def search_research_reports(self, symbol: str) -> Optional[list[dict]]:
        """搜索个股最新研报。"""
        return self.search_news(f"{symbol} 最新研报")

    # ------------------------------------------------------------------
    # mx-xuangu: 智能选股
    # ------------------------------------------------------------------

    def screen_stocks(self, conditions: str) -> Optional[list[dict]]:
        """调用 mx-xuangu 条件选股。返回股票列表。"""
        result = self._run_skill("mx-xuangu", conditions)
        if result is None:
            return None
        # 提取 dataList
        try:
            data_list = result.get("data", {}).get("data", {}).get("result", {}).get("dataList", [])
            return data_list if data_list else None
        except Exception:
            return None

    def screen_by_industry(self, industry: str, extra_conditions: str = "") -> Optional[list[dict]]:
        """按行业/板块选股。"""
        cond = f"{industry}板块" + (f" {extra_conditions}" if extra_conditions else "")
        return self.screen_stocks(cond)

    # ------------------------------------------------------------------
    # mx-moni: 模拟交易 (通过 REST API, 非 CLI)
    # ------------------------------------------------------------------

    def moni_request(self, endpoint: str, payload: dict) -> Optional[dict]:
        """调用 mx-moni REST API。"""
        if not self._api_key:
            logger.warning("MX_APIKEY 未配置，跳过 moni_request(%s)", endpoint)
            return None

        import urllib.request

        base_url = os.environ.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
        url = f"{base_url}/api/claw/mockTrading/{endpoint}"

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "apikey": self._api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("mx-moni %s 失败: %s", endpoint, e)
            return None

    def moni_positions(self) -> Optional[dict]:
        """查询模拟持仓。"""
        return self.moni_request("positions", {"moneyUnit": 1})

    def moni_balance(self) -> Optional[dict]:
        """查询模拟资金。"""
        return self.moni_request("balance", {"moneyUnit": 1})

    def moni_orders(self, flt_order_drt: int = 0, flt_order_status: int = 0) -> Optional[dict]:
        """查询模拟委托。"""
        return self.moni_request("orders", {"fltOrderDrt": flt_order_drt, "fltOrderStatus": flt_order_status})

    def moni_trade(
        self,
        stock_code: str,
        trade_type: str,  # "buy" | "sell"
        price: float,
        quantity: int,
        use_market_price: bool = False,
    ) -> Optional[dict]:
        """执行模拟买卖。"""
        payload = {
            "type": trade_type,
            "stockCode": stock_code,
            "price": price,
            "quantity": quantity,
            "useMarketPrice": use_market_price,
        }
        return self.moni_request("trade", payload)

    def moni_cancel(self, order_id: str = "", stock_code: str = "", cancel_all: bool = False) -> Optional[dict]:
        """撤单。"""
        if cancel_all:
            return self.moni_request("cancel", {"type": "all"})
        return self.moni_request("cancel", {"type": "order", "orderId": order_id, "stockCode": stock_code})

    # ------------------------------------------------------------------
    # mx-poster: AI 社区发帖
    # ------------------------------------------------------------------

    def poster_post_article(self, title: str, text_html: str) -> Optional[dict]:
        """发布社区文章。"""
        if not self._api_key:
            logger.warning("MX_APIKEY 未配置，跳过 poster_post_article")
            return None

        import urllib.request

        base_url = os.environ.get("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")
        url = f"{base_url}/api/aifinancecommunity/postArticle"

        try:
            data = json.dumps({"title": title, "text": text_html}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "apikey": self._api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("mx-poster postArticle 失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_skill(self, skill_name: str, query: str) -> Optional[dict]:
        """执行妙想 Skill CLI 脚本，解析 JSON 输出。

        Args:
            skill_name: "mx-data" | "mx-search" | "mx-xuangu"
            query: 自然语言查询字符串

        Returns:
            解析后的 JSON dict；失败返回 None
        """
        script_path = _SCRIPT_PATHS.get(skill_name)
        if script_path is None:
            logger.error("未知 skill: %s", skill_name)
            return None
        if not script_path.exists():
            logger.error("脚本不存在: %s", script_path)
            return None
        if not self._api_key:
            logger.warning("MX_APIKEY 未配置，跳过 %s", skill_name)
            return None

        # 缓存检查
        cache_key = f"{skill_name}:{query}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # 为每个 skill 创建独立输出目录，避免不同查询互相覆盖
        skill_output_dir = os.path.join(self._output_dir, skill_name)
        os.makedirs(skill_output_dir, exist_ok=True)

        for attempt in range(MAX_RETRIES + 1):
            try:
                env = os.environ.copy()
                env["MX_APIKEY"] = self._api_key

                result = subprocess.run(
                    ["python3", str(script_path), query, skill_output_dir],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT,
                    env=env,
                    cwd=str(script_path.parent),
                )

                if result.returncode != 0:
                    logger.warning(
                        "%s 脚本返回非零 (attempt %d): %s\nstderr: %s",
                        skill_name, attempt + 1, result.returncode, result.stderr[:500],
                    )
                    if attempt < MAX_RETRIES:
                        continue
                    return None

                # 解析输出 JSON 文件
                parsed = self._parse_output(skill_output_dir, skill_name, query)
                if parsed is not None:
                    self._cache_set(cache_key, parsed)
                    return parsed

                # JSON 解析失败时重试
                if attempt < MAX_RETRIES:
                    logger.debug("JSON 解析失败，重试 %s (attempt %d)", skill_name, attempt + 1)
                    continue

            except subprocess.TimeoutExpired:
                logger.warning("%s 超时 (attempt %d/%d)", skill_name, attempt + 1, MAX_RETRIES + 1)
                if attempt >= MAX_RETRIES:
                    return None
            except Exception as e:
                logger.error("%s 执行异常: %s", skill_name, e)
                return None

        return None

    def _parse_output(self, output_dir: str, skill_name: str, query: str) -> Optional[dict]:
        """从 skill 输出目录解析 JSON 结果文件。"""
        prefix_map = {
            "mx-data": "mx_data_",
            "mx-search": "mx_search_",
            "mx-xuangu": "mx_xuangu_",
        }
        prefix = prefix_map.get(skill_name, f"mx_{skill_name.split('-')[-1]}_")

        try:
            # 查找最新的 raw.json 文件
            raw_files = sorted(
                Path(output_dir).glob(f"{prefix}*_raw.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if raw_files:
                with open(raw_files[0], "r", encoding="utf-8") as f:
                    return json.load(f)

            # fallback：查找任意 json 文件
            json_files = sorted(
                Path(output_dir).glob(f"{prefix}*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if json_files:
                with open(json_files[0], "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("解析 %s 输出失败: %s", skill_name, e)

        return None

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str):
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return val

    def _cache_set(self, key: str, val):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()
