# -*- coding: utf-8 -*-
"""海外龙头股价领先信号源 — 为跨市场传导 lead-lag 管道注入"海外龙头异动"。

数据源: 东方财富 push2.eastmoney.com ``ulist`` 实时行情 API（curl_cffi，绕系统代理）。
  - L5 勘察确认: ``push2his.eastmoney.com``（历史K线，akshare stock_us_hist 依赖）被墙/报错，
    ``push2.eastmoney.com`` 的 ulist 接口可达（``us_overnight._fetch_extra_us_tickers`` 亦依赖）。
  - 返回美股/日股/韩股/费城半导体指数的当日涨跌幅（f3 字段），
    覆盖 ``SECTOR_MAP`` 中的海外标的（美光/英伟达/特斯拉/苹果/AMD/阿里/KWEB/SOX + 村田/三星）。
  - 计算当日异动，超过 threshold 才产出信号（避免日常噪音）。

设计原则（对齐 ``LeadSignalSource`` 可插拔接口）:
  - ``fetch()`` 返回 ``list[LeadSourceSignal]``；**任何网络/解析失败返回 ``[]``**（优雅降级），
    绝不抛异常阻塞 lead-lag 管道。
  - 结果带 6h TTL 缓存（对齐 ``FuturesSpotLeadSource``），避免重复请求东财。
  - 海外龙头异动一律标 ``[SPECULATION]`` 弱信号（海外龙头→A股对标 1-2 周，doc 04 可信度 0.3 理念）。

使用:
    from src.data.us_stock_lead_source import UsStockLeadSource
    src = UsStockLeadSource(threshold_pct=2.0)
    signals = src.fetch()   # [LeadSourceSignal(category="us_stock.MU", change_pct=...), ...]
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from src.data.us_sector_transmission import LeadSignalSource, LeadSourceSignal

logger = logging.getLogger(__name__)

# ── 海外龙头元数据: key → secid + 显示名 + 影响的 A 股板块 ──────────────
# secid 市场前缀（东财 push2 ulist）: 105=美股NASDAQ / 106=美股NYSE / 107=美股ARCA(ETF)
#    / 251=费城半导体指数 / 176=日股JPX / 177=韩股KRX。
# 板块列表用于 LeadSignal.target_sectors，供 lead_signal_weak_adjust 匹配。
US_STOCK_META: dict[str, dict] = {
    # ── 存储/半导体（最强跨境联动） ──
    "SOX": {"secid": "251.SOX", "name": "费城半导体指数", "sectors": ("半导体", "芯片", "存储")},
    "MU": {"secid": "105.MU", "name": "美光科技", "sectors": ("存储", "芯片")},
    "NVDA": {"secid": "105.NVDA", "name": "英伟达", "sectors": ("AI算力", "光通信")},
    "AMD": {"secid": "105.AMD", "name": "超威半导体", "sectors": ("芯片设计", "AI算力")},
    "SAMSUNG": {"secid": "177.005930", "name": "三星电子", "sectors": ("存储", "半导体", "消费电子")},
    # ── 消费电子 / 被动元件 ──
    "AAPL": {"secid": "105.AAPL", "name": "苹果", "sectors": ("消费电子", "果链")},
    "MURATA": {"secid": "176.6981", "name": "村田制作所", "sectors": ("消费电子",)},  # MLCC 被动元件
    # ── 新能源车 ──
    "TSLA": {"secid": "105.TSLA", "name": "特斯拉", "sectors": ("新能源车",)},
    # ── 中概/互联网（情绪传导为主） ──
    "BABA": {"secid": "106.BABA", "name": "阿里巴巴", "sectors": ("互联网",)},
    "KWEB": {"secid": "107.KWEB", "name": "中概互联ETF", "sectors": ("互联网", "恒生科技")},
}

# secid → meta key 反向索引（村田/三星的 f12 代码是 6981/005930，需用 f13.f12 重建 secid 匹配）
_SECID_TO_KEY: dict[str, str] = {
    meta["secid"]: key for key, meta in US_STOCK_META.items()
}

# 默认涨跌幅阈值(%) — 低于此值视为日常噪音，忽略
DEFAULT_THRESHOLD_PCT = 2.0

# 结果缓存 TTL — 行情日度更新，缓存 6 小时足够（对齐 futures_spot 模式）
_CACHE_TTL = timedelta(hours=6)


class UsStockLeadSource(LeadSignalSource):
    """海外龙头股价异动信号源（东财 push2 ulist 实时行情）。

    用法:
        src = UsStockLeadSource()
        signals = src.fetch()             # 全部已映射海外龙头
        signals = src.fetch("MU")         # 只看美光（支持 "us_stock.MU" 或 "MU"）

    任何网络/解析失败返回 ``[]``，不抛异常。
    """

    name: str = "us_stock"

    def __init__(self, threshold_pct: float = DEFAULT_THRESHOLD_PCT):
        self.threshold_pct = threshold_pct
        self._cache: Optional[tuple[datetime, list[LeadSourceSignal]]] = None

    # ── 公开 API ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """底层依赖 curl_cffi（或 requests）+ 东财 push2 网络可达性。

        网络是否真正可达由 fetch() 实测决定（失败返回 []）；此处只校验 HTTP 客户端存在。
        """
        try:
            from curl_cffi import requests  # noqa: F401
            return True
        except ImportError:
            try:
                import requests  # noqa: F401
                return True
            except ImportError:
                return False

    def fetch(self, category: str = "") -> list[LeadSourceSignal]:
        """获取当日海外龙头异动信号。

        Args:
            category: 空=全部已映射标的；"MU" 或 "us_stock.MU"=单标的。

        Returns:
            list[LeadSourceSignal]；失败/无可用数据返回 []。
        """
        want_key = self._parse_category(category)
        try:
            signals = self._fetch_all()
        except Exception as exc:
            logger.debug("UsStockLeadSource.fetch failed (degrade): %s", exc)
            return []
        if want_key:
            return [s for s in signals if s.category == f"us_stock.{want_key}"]
        return signals

    # ── 内部实现 ──────────────────────────────────────────────────────

    def _fetch_all(self) -> list[LeadSourceSignal]:
        """拉取并计算所有已映射海外龙头的当日异动（带 TTL 缓存）。"""
        now = datetime.now()
        if self._cache is not None and (now - self._cache[0]) < _CACHE_TTL:
            return self._cache[1]

        rows = self._fetch_ulist()
        if not rows:
            self._cache = (now, [])
            return []

        signals = self._build_signals(rows)
        self._cache = (now, signals)
        return signals

    def _fetch_ulist(self) -> list[dict]:
        """调用东财 push2 ulist 批量拉取海外龙头当日行情。失败返回 []。

        返回行: {"secid": "105.MU", "name": "美光科技", "change_pct": 2.97, "as_of": date}
        """
        try:
            from curl_cffi import requests as _req
        except ImportError:
            import requests as _req  # type: ignore[no-redef]

        # 绕过系统代理（对齐 us_sector_transmission._fetch_extra_us_tickers）
        import os as _os
        _os.environ["NO_PROXY"] = (
            _os.environ.get("NO_PROXY", "") + ",eastmoney.com,push2.eastmoney.com"
        )

        secids = [meta["secid"] for meta in US_STOCK_META.values()]
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            f"?fltt=2&invt=2&fields=f12,f13,f14,f2,f3,f124"
            f"&secids={','.join(secids)}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            resp = _req.get(url, headers=headers, timeout=12, impersonate="chrome120")
            payload = resp.json()
            items = (payload.get("data") or {}).get("diff", [])
        except Exception as exc:
            logger.debug("UsStockLeadSource ulist fetch failed (degrade): %s", exc)
            return []

        out: list[dict] = []
        for item in items:
            code = str(item.get("f12", ""))
            market = str(item.get("f13", ""))
            name = str(item.get("f14", ""))
            chg = item.get("f3")
            if not code or not market or not name or chg is None:
                continue
            secid = f"{market}.{code}"
            if secid not in _SECID_TO_KEY:
                continue
            try:
                chg_f = float(chg)
            except (TypeError, ValueError):
                continue
            as_of: Optional[date] = None
            ts = item.get("f124")
            if ts:
                try:
                    as_of = datetime.fromtimestamp(int(ts)).date()
                except (TypeError, ValueError, OSError):
                    as_of = None
            out.append({
                "secid": secid,
                "name": name,
                "change_pct": chg_f,
                "as_of": as_of,
            })
        return out

    def _build_signals(self, rows: list[dict]) -> list[LeadSourceSignal]:
        """把 ulist 行转换为 LeadSourceSignal，超过阈值才产出。"""
        out: list[LeadSourceSignal] = []
        for row in rows:
            key = _SECID_TO_KEY.get(row["secid"])
            if key is None:
                continue
            meta = US_STOCK_META[key]
            chg = row["change_pct"]
            if abs(chg) < self.threshold_pct:
                continue  # 日常波动，忽略
            out.append(LeadSourceSignal(
                category=f"us_stock.{key}",
                name=meta["name"],
                change_pct=round(chg, 2),
                as_of=row.get("as_of"),
                source="eastmoney_push2_us",
                target_sectors=meta["sectors"],
                confidence=0.7,
            ))
        return out

    @staticmethod
    def _parse_category(category: str) -> str:
        """把 category 参数解析为标的 key；空返回 ""。"""
        c = (category or "").strip()
        if not c:
            return ""
        if c.startswith("us_stock."):
            c = c.split(".", 1)[1]
        return c.upper()
