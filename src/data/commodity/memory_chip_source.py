# -*- coding: utf-8 -*-
"""存储芯片（DRAM / NAND Flash）现货价格领先信号源。

理念对应 doc 04 核心场景（可信度 0.3，仅作 [SPECULATION] 弱信号）:
  "华强北 MLCC 囤货 → 村田 → A股对标（风华高科）滞后约 2 周"
此处先落地其中**已有免费数据源**的存储颗粒分支:
  DRAM/NAND 现货异动（DRAMeXchange 日度报价）→ A股存储对标滞后 2-4 周。

数据源: DRAMeXchange（集邦咨询 TrendForce 旗下现货交易平台，dramexchange.com）。
  - 首页服务端直出日度现货报价表（DRAM 颗粒 / DRAM 模组 / NAND Wafer），无需鉴权/JS。
  - 每行: [产品名, high, low, high, low, 均价(USD), 当日涨跌幅(%)]。
  - 免费可读（仅历史深度数据/合约价需 Gold 会员），现货均价与涨跌幅公开。
  - 实测 2026-08-05 拉取: DDR4 8Gb≈42.1 美元、DDR5 16Gb≈51.3、512Gb TLC≈19.3，
    当日涨跌幅 +0.85% / +1.69% / +3.09% 等。

设计原则（对齐 LeadSignalSource 可插拔接口）:
  - ``fetch()`` 返回 ``list[LeadSourceSignal]``；任何网络/解析失败返回 ``[]``（优雅降级），
    绝不抛异常阻塞 lead-lag 管道。
  - 数据不可用时调用方自动回退到 ``SECTOR_MAP`` 配置驱动路径（现状行为不变）。
  - category 命名空间用 ``commodity.XXX``，复用 lead-lag 管道中 commodity → 14-28 天
    上游现货窗口（与 futures_spot_source 一致，无需改动 us_sector_transmission.py）。
  - 结果带 6h TTL 缓存（现货价日度更新）。
  - 现货异动一律标 ``[SPECULATION]`` 弱信号。

═══════════════════════════════════════════════════════════════════
MLCC / 被动元件 — 数据缺口（DATA_GAP）说明
═══════════════════════════════════════════════════════════════════
DRAMeXchange 不覆盖 MLCC。经调查，MLCC 现货价**无稳定免费 API**:

已探测（免费，不可作为稳定程序化源）:
  - 与非网 16rd.com "半导体每日价格表|MLCC" —— 华强北主流参考价（村田/三星/TDK/
    国巨/风华高科/三环 全梯度料号，1206 47μF 等），但为每日文章、URL 随 writing-id 变化，
    无稳定接口，仅适合人工/半自动阅读。
  - 华强北现货市场本身（渠道商口头报价，"半小时报一次价"，无公开标准化接口）。

未来接入建议（商业数据供应商 + 所需字段）:
  - 集邦 TrendForce MLCC 报价 / DRAMeXchange 扩展
  - 富昌电子(Future Electronics) / 得捷(DigiKey) / 贸泽(Mouser) 分销商挂牌价（部分有 API）
  - 华强北报价系统（第三方数据服务商）
  建议字段: product_part_no（如 1206 47uF 10V X7R）、brand（村田/三星/国巨/风华/三环）、
    unit_price_cny、prev_unit_price_cny、change_pct、quote_date、source。
  接入后映射: 风华高科(000636)/三环集团(300408)/洁美科技(002859) → sector "被动元件"。
  当前 MLCC 分支保持 is_available 判定为 True 但 fetch() 在无 MLCC 数据时返回 []，
  不会产生错误信号。

使用:
    from src.data.commodity.memory_chip_source import MemoryChipLeadSource
    src = MemoryChipLeadSource(threshold_pct=1.0)
    signals = src.fetch()  # [LeadSourceSignal(category="commodity.NAND", change_pct=3.09, ...)]

接入 lead-lag 管道（us_sector_transmission.py 由其他 Agent 维护，勿直接改）:
    from src.data.us_sector_transmission import build_lead_signals, register_lead_signal_source
    register_lead_signal_source(MemoryChipLeadSource())
    # 或在调用处显式传入:
    # build_lead_signals(tx_result, lead_sources=[MemoryChipLeadSource()])
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

from src.data.us_sector_transmission import LeadSignalSource, LeadSourceSignal

logger = logging.getLogger(__name__)

# DRAMeXchange 首页（服务端直出日度现货报价表，免费可读）
DRAMEXCHANGE_URL = "https://www.dramexchange.com/"

# ── 品种元数据: DRAMeXchange 产品名 → 显示名 + 类别key + 影响的A股板块 + A股对标 ──
# key 用于 category="commodity.{key}"，复用 lead-lag 管道 commodity → 14-28 天窗口。
# sectors 列表用于 LeadSignal.target_sectors，供 lead_signal_weak_adjust 匹配。
CHIP_PRODUCT_META: dict[str, dict] = {
    # ── DRAM 颗粒 ──
    "DDR4 8Gb (1Gx8) 3200": {
        "name": "DDR4 8Gb 现货", "key": "DRAM4",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/北京君正/江波龙",
    },
    "DDR4 16Gb (2Gx8) 3200": {
        "name": "DDR4 16Gb 现货", "key": "DRAM4",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/北京君正/江波龙",
    },
    "DDR5 16Gb (2Gx8) 4800/5600": {
        "name": "DDR5 16Gb 现货", "key": "DRAM5",
        "sectors": ("存储", "芯片"),
        "companies": "澜起科技/兆易创新",
    },
    "DDR5 RDIMM 32GB 4800/5600": {
        "name": "DDR5 RDIMM 现货", "key": "DRAM5",
        "sectors": ("存储", "芯片", "AI算力"),
        "companies": "澜起科技",
    },
    # ── NAND Flash Wafer ──
    "512Gb TLC": {
        "name": "NAND 512Gb TLC 现货", "key": "NAND",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/东芯股份/江波龙",
    },
    "256Gb TLC": {
        "name": "NAND 256Gb TLC 现货", "key": "NAND",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/东芯股份/江波龙",
    },
    "128Gb TLC": {
        "name": "NAND 128Gb TLC 现货", "key": "NAND",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/东芯股份/江波龙",
    },
    "SLC 1Gb 128MBx8": {
        "name": "NAND SLC 1Gb 现货", "key": "NAND",
        "sectors": ("存储", "芯片"),
        "companies": "兆易创新/东芯股份",
    },
    "MLC 64Gb 8GBx8": {
        "name": "NAND MLC 64Gb 现货", "key": "NAND",
        "sectors": ("存储", "芯片"),
        "companies": "江波龙/德明利",
    },
}

# 类别显示名（category="commodity.XXX" 的 XXX → 中文）
CHIP_KEY_LABEL: dict[str, str] = {
    "DRAM4": "DDR4 颗粒",
    "DRAM5": "DDR5 颗粒",
    "NAND": "NAND Flash",
}

# 默认现货涨跌幅阈值(%) — 低于此值的日常波动忽略，避免噪音信号。
# 存储现货单日波动通常 0.5%-3%，阈值取 1.0% 较期货(2.0%)更低以捕获温和异动。
DEFAULT_THRESHOLD_PCT = 1.0

# 结果缓存 TTL — 现货价格日度更新，缓存 6 小时足够（与 futures_spot_source 一致）
_CACHE_TTL = timedelta(hours=6)

# 请求头 — 模拟浏览器，降低被拒概率
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class MemoryChipLeadSource(LeadSignalSource):
    """存储芯片（DRAM/NAND Flash）现货价格异动信号源（DRAMeXchange，免费）。

    用法:
        src = MemoryChipLeadSource()
        signals = src.fetch()          # 全部已映射类别（DRAM4/DRAM5/NAND）
        signals = src.fetch("NAND")    # 只看 NAND（支持 "commodity.NAND" 或 "NAND"）

    任何网络/解析失败返回 ``[]``，不抛异常。
    """

    name: str = "memory_chip"

    def __init__(
        self,
        threshold_pct: float = DEFAULT_THRESHOLD_PCT,
        url: str = DRAMEXCHANGE_URL,
        timeout: float = 15.0,
    ):
        self.threshold_pct = threshold_pct
        self.url = url
        self.timeout = timeout
        self._cache: Optional[tuple[datetime, list[LeadSourceSignal]]] = None

    # ── 公开 API ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """检测底层数据源是否可用（requests 可导入即视为可用，网络失败走降级）。"""
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def fetch(self, category: str = "") -> list[LeadSourceSignal]:
        """获取 DRAM/NAND 现货价格异动信号。

        Args:
            category: 空=全部已映射类别；"NAND" 或 "commodity.NAND"=单类别。

        Returns:
            list[LeadSourceSignal]；失败/无可用数据返回 []。
        """
        want_key = self._parse_category(category)
        try:
            signals = self._fetch_all()
        except Exception as exc:
            logger.debug("MemoryChipLeadSource.fetch failed (degrade): %s", exc)
            return []
        if want_key:
            return [s for s in signals if s.category == f"commodity.{want_key}"]
        return signals

    # ── 内部实现 ──────────────────────────────────────────────────────

    def _fetch_all(self) -> list[LeadSourceSignal]:
        """拉取并计算所有已映射类别的现货涨跌幅（带 TTL 缓存）。"""
        now = datetime.now()
        if self._cache is not None and (now - self._cache[0]) < _CACHE_TTL:
            return self._cache[1]

        signals = self._scrape_signals()
        self._cache = (now, signals)
        return signals

    @staticmethod
    def _parse_category(category: str) -> str:
        """把 category 参数解析为类别 key；空返回 ""。"""
        c = (category or "").strip()
        if not c:
            return ""
        if c.startswith("commodity."):
            c = c.split(".", 1)[1]
        return c.upper()

    # ── 抓取与解析 ────────────────────────────────────────────────────

    def _scrape_signals(self) -> list[LeadSourceSignal]:
        """抓取 DRAMeXchange 首页并解析现货报价表 → 信号列表。失败抛异常由 fetch 兜底。"""
        html = self._get_html()
        if not html:
            return []

        rows = self._parse_spot_rows(html)
        if not rows:
            logger.debug("DRAMeXchange 首页未解析到现货报价行")
            return []

        # 按 product key 收集：只保留与元数据精确匹配的产品行
        matched: dict[str, dict] = {}
        for row in rows:
            name = row.get("name", "")
            meta = CHIP_PRODUCT_META.get(name)
            if meta is None:
                continue
            # 同 key 多产品聚合：取 |change_pct| 最大者（最显著的异动）
            cur = matched.get(meta["key"])
            if cur is None or abs(row["change_pct"]) > abs(cur["row"]["change_pct"]):
                matched[meta["key"]] = {"row": row, "meta": meta}

        if not matched:
            logger.debug("DRAMeXchange 现货表无匹配产品")
            return []

        as_of = self._parse_last_update(html)
        out: list[LeadSourceSignal] = []
        for key, entry in sorted(matched.items()):
            row = entry["row"]
            meta = entry["meta"]
            change_pct = row["change_pct"]
            if abs(change_pct) < self.threshold_pct:
                continue  # 日常波动，忽略
            out.append(LeadSourceSignal(
                category=f"commodity.{key}",
                name=CHIP_KEY_LABEL.get(key, meta["name"]),
                change_pct=change_pct,
                as_of=as_of,
                source="dramexchange_spot",
                target_sectors=meta["sectors"],
                confidence=0.6,
            ))
        return out

    def _get_html(self) -> str:
        """GET 首页 HTML；网络失败抛异常。"""
        import requests

        try:
            from curl_cffi import requests as _req  # type: ignore[no-redef]
        except ImportError:
            _req = requests  # type: ignore[no-redef]
        resp = _req.get(
            self.url, headers=_HEADERS, timeout=self.timeout,
            impersonate="chrome120",
        )
        if resp.status_code != 200:
            logger.debug("DRAMeXchange HTTP %s", resp.status_code)
            return ""
        return resp.text

    @staticmethod
    def _parse_spot_rows(html: str) -> list[dict]:
        """解析首页现货报价表行。

        每行结构: [产品名, high, low, high, low, 均价(USD), 涨跌幅(%)]。
        仅保留: 首列为纯产品名、末列为 "x.xx %" 的 <tr> 行（跳过 SSD 行/JS 模板行）。
        """
        if not html:
            return []
        out: list[dict] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            ]
            cells = [c for c in cells if c]
            if len(cells) < 7:
                continue
            if not re.search(r"%$", cells[-1]):
                continue
            name = cells[0]
            if re.search(r"[<>&'\"]", name) or "append" in name.lower():
                continue  # 过滤 JS 模板行 / 非纯文本
            try:
                avg = float(cells[-2])
                change_pct = float(cells[-1].replace("%", "").strip())
            except (TypeError, ValueError):
                continue
            out.append({
                "name": name,
                "avg_price": avg,
                "change_pct": change_pct,
            })
        return out

    @staticmethod
    def _parse_last_update(html: str) -> Optional[date]:
        """从页面 "Last Update: Aug.5 2026 18:10 (GMT+8)" 提取最新更新日期。"""
        if not html:
            return None
        seen: list[date] = []
        for m in re.finditer(
            r"Last Update:?\s*([A-Za-z]{3}\.\s*\d{1,2}\s*\d{4})", html
        ):
            try:
                seen.append(datetime.strptime(m.group(1).replace(" ", ""), "%b.%d%Y").date())
            except ValueError:
                continue
        return max(seen) if seen else None
