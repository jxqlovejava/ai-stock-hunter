# -*- coding: utf-8 -*-
"""巨潮资讯网 (cninfo.com.cn) 数据源适配器。

cninfo 是证监会指定的 A 股官方信息披露平台，提供：
  - 公告/披露检索（标题、全文、PDF）
  - 定期报告（年报/半年报/季报）
  - 公司基本信息（orgId 映射）

所有接口零鉴权（HTTP POST/GET），无需 API Key。
数据级别：T0（一手官方），置信度 0.90。

设计原则：
  - 独立类（不继承 DataProvider，cninfo 不提供行情/财务数据）
  - 实例级 Session + 自动节流（1.0s min interval + jitter）
  - 所有公开方法失败返回 []/None，不抛异常
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MIN_INTERVAL = 1.0  # 最小请求间隔（秒）
TIMEOUT = 15  # 默认请求超时（秒）

# cninfo API 端点
ANNOUNCE_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
ORGID_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
DETAIL_URL = "https://www.cninfo.com.cn/new/disclosure/detail"

# 定期报告 category 映射
REPORT_CATEGORIES: dict[str, str] = {
    "annual": "category_ndbg_szsh",       # 年报
    "semi_annual": "category_bndbg_szsh",  # 半年报
    "quarterly": "category_yjdbg_szsh",    # 季报
    "ipo": "category_zgzssh_szsh",         # 招股说明书
    "company": "category_gszl_szsh",        # 公司资料
}


class CninfoProvider:
    """巨潮资讯网数据源适配器。

    用法:
        provider = CninfoProvider()
        announcements = provider.search_announcements("000001", keyword="分红")
        reports = provider.get_periodic_reports("000001", "annual")
        detail = provider.get_announcement_detail("1234567890")
    """

    source_name = "cninfo"

    def __init__(self):
        self._session: Optional[requests.Session] = None
        self._last_call: float = 0.0
        self._orgid_map: dict[str, str] = {}
        self._orgid_loaded: bool = False

    # ── 会话管理 ──────────────────────────────────────────────────────

    @property
    def session(self) -> requests.Session:
        """懒初始化 HTTP Session（挂载重试适配器）。"""
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False  # 禁止读取系统代理，避免代理工具干扰巨潮 API 连接
            self._session.headers.update({"User-Agent": UA})
            try:
                retry_strategy = Retry(
                    total=3,
                    connect=3,
                    backoff_factor=0.6,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST"],
                )
                adapter = HTTPAdapter(max_retries=retry_strategy)
                self._session.mount("https://", adapter)
                self._session.mount("http://", adapter)
            except Exception:
                pass
        return self._session

    def _rate_limit(self):
        """请求节流：保证最小间隔 + 随机 jitter（0.1-0.5s）。"""
        wait = MIN_INTERVAL - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))

    def _mark_call(self):
        """记录最近一次请求时间。"""
        self._last_call = time.time()

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: int = TIMEOUT) -> requests.Response:
        """统一 GET 入口：节流 + 复用 session + 默认 UA。"""
        self._rate_limit()
        try:
            return self.session.get(url, params=params, headers=headers or {}, timeout=timeout)
        finally:
            self._mark_call()

    def _post(self, url: str, data: dict | None = None, headers: dict | None = None, timeout: int = TIMEOUT) -> requests.Response:
        """统一 POST 入口：节流 + 复用 session。"""
        self._rate_limit()
        try:
            return self.session.post(url, data=data, headers=headers or {}, timeout=timeout)
        finally:
            self._mark_call()

    # ── orgId 映射 ────────────────────────────────────────────────────

    def _load_orgid_map(self):
        """从巨潮官方 JSON 加载 股票代码 → orgId 映射（约 6200 只，懒加载一次）。"""
        if self._orgid_loaded:
            return
        self._orgid_loaded = True
        try:
            r = self._get(ORGID_URL, timeout=15)
            stock_list = r.json().get("stockList", [])
            self._orgid_map = {s["code"]: s["orgId"] for s in stock_list}
            logger.info("cninfo orgId 映射表加载完成: %d 只股票", len(self._orgid_map))
        except Exception as e:
            logger.warning("cninfo orgId 映射表加载失败，回退硬编码规则: %s", e)

    def _get_orgid(self, code: str) -> str:
        """查股票真实 orgId。优先查官方映射表，查不到回退硬编码。

        规则:
          - 6xxxxx → gssh0{code}（上交所）
          - 8xxxxx / 4xxxxx → gsbj0{code}（北交所）
          - 其他 → gssz0{code}（深交所）
        """
        self._load_orgid_map()
        org = self._orgid_map.get(code)
        if org:
            return org
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith("8") or code.startswith("4"):
            return f"gsbj0{code}"
        return f"gssz0{code}"

    @staticmethod
    def _ts_to_date(ts) -> str:
        """cninfo announcementTime: Unix 毫秒 → YYYY-MM-DD。"""
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass
        return str(ts)[:10] if ts else ""

    # ── 公告检索 ──────────────────────────────────────────────────────

    def search_announcements(
        self,
        symbol: str,
        page_size: int = 30,
        page_num: int = 1,
        keyword: str = "",
        category: str = "",
        start_date: str = "",
        end_date: str = "",
        plate: str = "",
    ) -> list[dict]:
        """搜索个股公告（POST hisAnnouncement/query，零鉴权）。

        Args:
            symbol: 6 位股票代码
            page_size: 每页条数（默认 30）
            page_num: 页码（默认 1）
            keyword: 标题关键词搜索（可选）
            category: cninfo category 代码（可选），如 category_ndbg_szsh（年报）
            start_date: 起始日期 YYYY-MM-DD（可选）
            end_date: 截止日期 YYYY-MM-DD（可选）
            plate: 交易所板块 szse/sse/bjse（可选）

        Returns:
            [{title, type, date, url, announcement_id, sec_name, org_id}, ...]
            失败返回 []
        """
        org_id = self._get_orgid(symbol)
        se_date = f"{start_date}~{end_date}" if (start_date or end_date) else ""

        payload = {
            "stock": f"{symbol},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "column": plate,
            "category": category,
            "plate": plate,
            "seDate": se_date,
            "searchkey": keyword,
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }

        try:
            r = self._post(ANNOUNCE_URL, data=payload, headers=headers)
            d = r.json()
            rows: list[dict] = []
            for item in d.get("announcements", []) or []:
                aid = item.get("announcementId", "")
                rows.append({
                    "title": item.get("announcementTitle", ""),
                    "type": item.get("announcementTypeName", ""),
                    "date": self._ts_to_date(item.get("announcementTime")),
                    "url": f"{DETAIL_URL}?annoId={aid}",
                    "announcement_id": aid,
                    "sec_name": item.get("secName", ""),
                    "org_id": item.get("orgId", org_id),
                })
            return rows
        except Exception as e:
            logger.debug("cninfo 公告检索失败 (%s): %s", symbol, e)
            return []

    # ── 定期报告 ──────────────────────────────────────────────────────

    def get_periodic_reports(
        self,
        symbol: str,
        report_type: str = "annual",
        page_size: int = 20,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict]:
        """获取个股定期报告（年报/半年报/季报）。

        Args:
            symbol: 6 位股票代码
            report_type: "annual"（年报）/ "semi_annual"（半年报）/ "quarterly"（季报）
            page_size: 每页条数
            start_date: 起始日期（可选）
            end_date: 截止日期（可选）

        Returns:
            公告列表，与 search_announcements 格式一致
        """
        category = REPORT_CATEGORIES.get(report_type, "")
        if not category:
            logger.warning("cninfo: 未知报告类型 '%s'，回退到全类型搜索", report_type)
        return self.search_announcements(
            symbol=symbol,
            page_size=page_size,
            category=category,
            start_date=start_date,
            end_date=end_date,
        )

    # ── 公告详情 ──────────────────────────────────────────────────────

    def get_announcement_detail(self, announcement_id: str) -> dict | None:
        """获取公告详情页 HTML 并提取正文文本。

        访问 cninfo 公告详情页，解析 HTML 提取：
          - 公告标题
          - 发布时间
          - 正文文本（去除 HTML 标签）
          - PDF 下载链接（如有）

        Args:
            announcement_id: 公告 ID（来自 search_announcements 的 announcement_id 字段）

        Returns:
            {title, date, content_text, pdf_url, url} 或 None
        """
        url = f"{DETAIL_URL}?annoId={announcement_id}"
        headers = {"Referer": "https://www.cninfo.com.cn/new/disclosure"}

        try:
            r = self._get(url, headers=headers)
            html = r.text

            # 提取公告标题
            title = ""
            title_match = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()

            # 提取发布时间
            date = ""
            date_match = re.search(r'公告日期[：:]\s*(\d{4}-\d{2}-\d{2})', html)
            if not date_match:
                date_match = re.search(r'"announcementTime"[:\s]*"?(\d+)"?', html)
                if date_match:
                    date = self._ts_to_date(int(date_match.group(1)))
            if not date and date_match:
                date = date_match.group(1)

            # 提取正文 — 尝试定位主要内容区域
            content_text = ""
            # cninfo 详情页通常把公告正文放在 .content / #content / .detail-content 中
            content_match = re.search(
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL | re.IGNORECASE,
            )
            if content_match:
                raw = content_match.group(1)
            else:
                # fallback: 取 <body> 内所有文本
                body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL)
                raw = body_match.group(1) if body_match else html

            # 去除 HTML 标签和多余空白
            content_text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
            content_text = re.sub(r'<style[^>]*>.*?</style>', '', content_text, flags=re.DOTALL)
            content_text = re.sub(r'<[^>]+>', '\n', content_text)
            content_text = re.sub(r'&nbsp;', ' ', content_text)
            content_text = re.sub(r'&lt;', '<', content_text)
            content_text = re.sub(r'&gt;', '>', content_text)
            content_text = re.sub(r'&amp;', '&', content_text)
            content_text = re.sub(r'\n{3,}', '\n\n', content_text)
            content_text = content_text.strip()

            # 提取 PDF 链接
            pdf_url = ""
            pdf_match = re.search(
                r'href="([^"]*\.pdf)"',
                html, re.IGNORECASE,
            )
            if pdf_match:
                pdf_url = pdf_match.group(1)
                if pdf_url.startswith("/"):
                    pdf_url = f"https://www.cninfo.com.cn{pdf_url}"

            return {
                "title": title,
                "date": date,
                "content_text": content_text[:10000],  # 截断到 10000 字符
                "pdf_url": pdf_url,
                "url": url,
            }
        except Exception as e:
            logger.debug("cninfo 公告详情获取失败 (%s): %s", announcement_id, e)
            return None

    def get_pdf_url(self, announcement_id: str) -> str | None:
        """获取公告 PDF 下载链接。

        优先从详情页提取 PDF URL，失败则尝试构造常见 URL 模式。

        Args:
            announcement_id: 公告 ID

        Returns:
            PDF URL 字符串或 None
        """
        # 先尝试从详情页提取
        detail = self.get_announcement_detail(announcement_id)
        if detail and detail.get("pdf_url"):
            return detail["pdf_url"]
        return None

    # ── 健康检查 ──────────────────────────────────────────────────────

    def get_stock_list(self) -> list[dict]:
        """获取全市场股票代码+名称列表（~6200 只，T0 一手官方源）。

        优先级：付费/免费数据源全市场扫描的最终降级路径。
        """
        self._load_orgid_map()
        results: list[dict] = []
        for code, org_id in self._orgid_map.items():
            results.append({"code": code, "orgId": org_id})
        return results

    def health_check(self) -> bool:
        """连通性检查：尝试加载 orgId 映射表。"""
        try:
            self._load_orgid_map()
            return len(self._orgid_map) > 0
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"<CninfoProvider loaded={self._orgid_loaded} orgids={len(self._orgid_map)}>"


# ── 模块级单例（供 eastmoney_fallback 向后兼容） ──────────────────────
_default_provider: Optional[CninfoProvider] = None


def _get_default_provider() -> CninfoProvider:
    """获取模块级默认 CninfoProvider 单例。"""
    global _default_provider
    if _default_provider is None:
        _default_provider = CninfoProvider()
    return _default_provider
