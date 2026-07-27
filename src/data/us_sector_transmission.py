# -*- coding: utf-8 -*-
"""US sector → A-share sector 传导修正器。

对跨境联动强的板块，根据美股标的隔夜表现在A股诊断管道中
做对应板块的评分降权/加权修正。

用法:
    from src.data.us_sector_transmission import UsSectorTransmissionAdjuster
    adj = UsSectorTransmissionAdjuster()
    adjustments = adj.compute(global_market_data)
    # adjustments = [{"sector": "存储", "adjust": -5, "reason": "美光-5.4%→系数0.45"}, ...]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 映射表 — US信号 → A股板块 × 传导系数
# ═══════════════════════════════════════════════════════════════════
#
# 每条映射定义:
#   us_key:     在 global_market 数据中查找的 key（取自 USIndexSnapshot.symbol）
#               SOX = 费城半导体指数，MU = 美光科技（个股）
#   us_label:   显示名称
#   sectors:    影响的A股板块列表（与诊断管道的板块名对应）
#   coefficient: 传导系数 0~1。
#               0.50 表示美股波动中的 50% 映射到A股评分修正
#   threshold:  最小触发涨跌幅（%），低于此阈值的波动忽略
#               避免日常噪音触发修正
#   weight:     该映射在综合修正中的权重（多映射指向同板块时的汇总权重）
#
# 系数估算逻辑:
#   美股存储跌 10% → A股存储板块一般低开 3-5%，跌幅映射比约 30-50%
#   取中位数 40% 做基准系数，然后微调:
#   - 产业链直接映射（美光→存储）系数偏高 0.45
#   - 情绪型映射（特斯拉→新能源车）系数偏低 0.35
#   - 行业指数级别（SOX→半导体）系数 0.50
#   以上系数待后续校准。

SECTOR_MAP: list[dict] = [
    # ── 存储/半导体（最强跨境联动） ──
    {
        "us_key": "SOX", "us_label": "费城半导体指数",
        "sectors": ["半导体", "芯片", "存储"],
        "coefficient": 0.50, "threshold": 2.0, "weight": 1.0,
    },
    {
        "us_key": "MU", "us_label": "美光科技",
        "sectors": ["存储", "芯片"],
        "coefficient": 0.45, "threshold": 3.0, "weight": 0.8,
    },
    {
        "us_key": "NVDA", "us_label": "英伟达",
        "sectors": ["AI算力", "光通信"],
        "coefficient": 0.50, "threshold": 2.0, "weight": 1.0,
    },
    {
        "us_key": "AMD", "us_label": "AMD",
        "sectors": ["芯片设计", "AI算力"],
        "coefficient": 0.40, "threshold": 2.5, "weight": 0.7,
    },
    # ── 消费电子 ──
    {
        "us_key": "AAPL", "us_label": "苹果",
        "sectors": ["消费电子", "果链"],
        "coefficient": 0.45, "threshold": 2.0, "weight": 1.0,
    },
    # ── 新能源车 ──
    {
        "us_key": "TSLA", "us_label": "特斯拉",
        "sectors": ["新能源车"],
        "coefficient": 0.35, "threshold": 3.0, "weight": 0.8,
    },
    # ── 中概/互联网（情绪传导为主） ──
    {
        "us_key": "BABA", "us_label": "阿里巴巴",
        "sectors": ["互联网"],
        "coefficient": 0.25, "threshold": 3.0, "weight": 0.6,
    },
    {
        "us_key": "KWEB", "us_label": "中概互联ETF",
        "sectors": ["互联网", "恒生科技"],
        "coefficient": 0.30, "threshold": 2.0, "weight": 0.7,
    },
]

# 需要从东财API额外拉取的美股标的secid列表
# (已有的SPX/NDX/DJIA之外需要补充的)
EXTRA_US_SECIDS: dict[str, str] = {
    "SOX": "100.SOX",
    "MU": "100.MU",
    "NVDA": "100.NVDA",
    "AMD": "100.AMD",
    "AAPL": "100.AAPL",
    "TSLA": "100.TSLA",
    "BABA": "100.BABA",
    "KWEB": "100.KWEB",
}


# 股票名称关键词 → 板块名映射（兜底分类，不依赖外部API）
# 当 SectorClassifier 不可用时使用
STOCK_KEYWORD_SECTOR_MAP: dict[str, list[str]] = {
    # ── 存储/半导体 ──
    "存储": ["存储", "芯片", "半导体"],
    "芯片": ["芯片", "半导体"],
    "半导体": ["半导体", "芯片"],
    "光刻": ["半导体", "设备材料"],
    "封测": ["芯片", "半导体"],
    "硅片": ["半导体"],
    "中芯": ["芯片", "半导体"],
    "华虹": ["芯片", "半导体"],
    "长电": ["芯片", "半导体"],
    "通富": ["芯片", "半导体"],
    "华天": ["芯片", "半导体"],
    "兆易": ["存储", "芯片"],
    "北京君正": ["存储", "芯片"],
    "澜起": ["芯片"],
    "江波龙": ["存储"],
    "佰维": ["存储"],
    "德明利": ["存储"],
    "普冉": ["存储", "芯片"],
    # ── AI算力/光通信 ──
    "AI": ["AI算力"],
    "算力": ["AI算力"],
    "光通信": ["光通信"],
    "光模块": ["光通信"],
    "中际": ["光通信"],
    "旭创": ["光通信"],
    "新易盛": ["光通信"],
    "天孚": ["光通信"],
    "服务器": ["AI算力"],
    "浪潮": ["AI算力"],
    "中科曙光": ["AI算力"],
    # ── PCB/电路板（AI服务器/通信设备的上游） ──
    "电路": ["消费电子", "AI算力"],
    "PCB": ["消费电子", "AI算力"],
    "覆铜板": ["消费电子"],
    "电子布": ["消费电子"],
    "深南电路": ["消费电子", "AI算力"],
    "生益科技": ["消费电子"],
    "宏和": ["消费电子"],
    "沪电": ["消费电子", "AI算力"],
    "景旺": ["消费电子"],
    # ── 消费电子/果链 ──
    "消费电子": ["消费电子"],
    "果链": ["果链", "消费电子"],
    "苹果": ["果链"],
    "立讯": ["果链", "消费电子"],
    "歌尔": ["果链", "消费电子"],
    "蓝思": ["果链", "消费电子"],
    "鹏鼎": ["消费电子"],
    "东山精密": ["消费电子"],
    # ── 新能源车 ──
    "新能源": ["新能源车"],
    "电动": ["新能源车"],
    "锂电": ["新能源车"],
    "电池": ["新能源车"],
    "宁德": ["新能源车"],
    "比亚迪": ["新能源车"],
    "蔚来": ["新能源车"],
    "小鹏": ["新能源车"],
    "理想": ["新能源车"],
    # ── 新能源（风电/光伏等） ──
    "风电": ["新能源"],
    "叶片": ["新能源"],
    "玻纤": ["新能源"],
    "光伏": ["新能源"],
    "隆基": ["新能源"],
    "阳光电源": ["新能源"],
    "金风": ["新能源"],
    "明阳": ["新能源"],
    "中材": ["新能源", "新能源车"],
    # ── 互联网 ──
    "互联": ["互联网"],
    "软件": ["互联网"],
    "传媒": ["互联网"],
    "腾讯": ["互联网"],
    "阿里": ["互联网"],
    "百度": ["互联网"],
    "网易": ["互联网"],
    "哔哩": ["互联网"],
    "拼多多": ["互联网"],
    "京东": ["互联网"],
    # ── 食品饮料 ──
    "茅台": ["食品饮料"],
    "五粮液": ["食品饮料"],
    "白酒": ["食品饮料"],
    "食品": ["食品饮料"],
}


def guess_sector_from_name(stock_name: str) -> list[str]:
    """根据股票名称关键词猜测所属板块。

    Args:
        stock_name: 股票名称，如 "中芯国际"、"北方华创"

    Returns:
        匹配的板块列表，如 ["芯片", "半导体"]
    """
    matched: list[str] = []
    for keyword, sectors in STOCK_KEYWORD_SECTOR_MAP.items():
        if keyword in stock_name:
            matched.extend(sectors)
    return list(set(matched))  # 去重


@dataclass
class SectorAdjustment:
    """单条板块修正建议。"""

    sector: str                      # A股板块名
    adjust: int                      # 评分修正值（-100 ~ +100）
    reason: str                      # 修正原因（供输出展示）
    us_change_pct: float             # 触发修正的美股涨跌幅
    coefficient: float               # 使用的传导系数
    source: str = "us_sector_transmission"


@dataclass
class TransmissionResult:
    """传导修正结果。"""

    adjustments: list[SectorAdjustment] = field(default_factory=list)
    active_signals: list[dict] = field(default_factory=list)  # 触发的信号摘要
    summary: str = ""                 # 一行总结: "存储-5, AI-3, 消费电子-2"
    data_available: bool = False      # 是否有足够数据支撑修正


class UsSectorTransmissionAdjuster:
    """US 板块→A股板块 传导修正器。

    独立于数据源的纯逻辑层。只要传入 {us_key: change_pct} 的映射即可工作。
    """

    def compute(
        self,
        us_changes: dict[str, float],
    ) -> TransmissionResult:
        """根据美股标的涨跌幅计算A股板块修正。

        Args:
            us_changes: {us_key: change_pct} — e.g. {"MU": -5.38, "SOX": -3.33}

        Returns:
            TransmissionResult
        """
        if not us_changes:
            return TransmissionResult()

        # 按A股板块汇总修正值（加权求和）
        sector_adj: dict[str, float] = {}
        sector_reasons: dict[str, list[str]] = {}
        active_signals: list[dict] = []

        for mapping in SECTOR_MAP:
            key = mapping["us_key"]
            chg = us_changes.get(key)
            if chg is None:
                continue

            abs_chg = abs(chg)
            threshold = mapping["threshold"]
            if abs_chg < threshold:
                continue  # 日常波动，忽略

            coeff = mapping["coefficient"]
            weight = mapping["weight"]

            # 修正值 = 涨跌幅 × 系数 × 权重
            # 美股跌(-)→A股承压(-)，美股涨(+)→A股提振(+)
            adj_val = chg * coeff * weight

            reason = (
                f"{mapping['us_label']}{chg:+.1f}%→系数{coeff}"
            )

            active_signals.append({
                "us_key": key,
                "us_label": mapping["us_label"],
                "change_pct": round(chg, 2),
                "threshold": threshold,
                "coefficient": coeff,
                "weight": weight,
                "raw_adjust": round(adj_val, 2),
            })

            for sector in mapping["sectors"]:
                sector_adj[sector] = sector_adj.get(sector, 0.0) + adj_val
                if sector not in sector_reasons:
                    sector_reasons[sector] = []
                sector_reasons[sector].append(reason)

        if not sector_adj:
            return TransmissionResult(active_signals=active_signals)

        # 将连续修正值量化为整数评分偏移
        adjustments: list[SectorAdjustment] = []
        parts: list[str] = []
        for sector, raw_adj in sorted(sector_adj.items()):
            # 映射到评分偏移: 每 1% 美股波动 ≈ 2-3 分偏移
            # 用 min/max 限制偏移量
            adj_int = max(-15, min(15, int(round(raw_adj * 2.5))))
            if abs(adj_int) < 1:
                continue
            reasons = sector_reasons.get(sector, [])
            adjustments.append(SectorAdjustment(
                sector=sector,
                adjust=adj_int,
                reason="; ".join(reasons),
                us_change_pct=round(raw_adj, 2),
                coefficient=0.0,  # 汇总值，无单一系数
            ))
            sign = "+" if adj_int > 0 else ""
            parts.append(f"{sector}{sign}{adj_int}")

        return TransmissionResult(
            adjustments=adjustments,
            active_signals=active_signals,
            summary=" | ".join(parts),
            data_available=True,
        )

    @staticmethod
    def fetch_us_sector_data(
        global_market_snapshot=None,
    ) -> dict[str, float]:
        """获取关键美股标的隔夜涨跌幅。

        优先从已加载的 global_market_snapshot 读取，
        缺失的标的尝试通过东财API补充。

        Args:
            global_market_snapshot: 已有的 GlobalMarketSnapshot（可选）

        Returns:
            {us_key: change_pct} — 有数据的标的
        """
        result: dict[str, float] = {}

        # 1. 从已加载的快照中提取
        if global_market_snapshot is not None:
            # USIndexSnapshot 对象映射
            index_map = {
                "SPX": getattr(global_market_snapshot, "sp500", None),
                "NDX": getattr(global_market_snapshot, "nasdaq", None),
                "^GSPC": getattr(global_market_snapshot, "sp500", None),
                "^IXIC": getattr(global_market_snapshot, "nasdaq", None),
            }
            for key, idx in index_map.items():
                if idx is not None:
                    chg = getattr(idx, "change_pct", None)
                    if chg is not None:
                        result[key] = chg

        # 2. 东财API补充缺失标的
        missing = [k for k in EXTRA_US_SECIDS if k not in result]
        if missing:
            try:
                extra = _fetch_extra_us_tickers(missing)
                result.update(extra)
            except Exception as e:
                logger.debug("fetch_us_sector_data extra failed: %s", e)

        return result


def _fetch_extra_us_tickers(
    tickers: list[str],
    max_retries: int = 2,
) -> dict[str, float]:
    """通过东财push2 API拉取额外美股标的涨跌幅。

    Args:
        tickers: 需要拉取的标的key列表（如 ["SOX", "MU", "NVDA"]）

    Returns:
        成功获取的 {key: change_pct}
    """
    import time as _time

    # 构建 secids 列表
    valid_secids = []
    key_map: dict[str, str] = {}
    for key in tickers:
        secid = EXTRA_US_SECIDS.get(key)
        if secid:
            valid_secids.append(secid)
            key_map[secid] = key

    if not valid_secids:
        return {}

    # 分批拉取（每次最多10个，避免URL过长）
    batch_size = 10
    all_data: dict[str, dict] = {}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }

    for i in range(0, len(valid_secids), batch_size):
        batch = valid_secids[i:i + batch_size]
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            f"?fltt=2&invt=2&fields=f12,f14,f2,f3,f4"
            f"&secids={','.join(batch)}"
        )

        for attempt in range(max_retries):
            try:
                # 使用 curl_cffi（可用时），回退到 requests
                try:
                    from curl_cffi import requests as _req
                except ImportError:
                    import requests as _req  # type: ignore[no-redef]

                # 绕过系统代理
                import os as _os
                _os.environ["NO_PROXY"] = (
                    _os.environ.get("NO_PROXY", "")
                    + ",eastmoney.com,push2.eastmoney.com"
                )

                resp = _req.get(url, headers=headers, timeout=12, impersonate="chrome120")
                payload = resp.json()
                items = (payload.get("data") or {}).get("diff", [])
                for item in items:
                    secid = str(item.get("f12", ""))
                    chg = item.get("f3")
                    name = item.get("f14", "")
                    if secid in key_map and chg is not None and name:
                        all_data[secid] = {"change_pct": float(chg), "name": name}
                break  # 成功则跳出重试
            except Exception as exc:
                logger.debug(
                    "fetch_extra tickers batch %d attempt %d: %s",
                    i // batch_size, attempt + 1, exc,
                )
                if attempt < max_retries - 1:
                    _time.sleep(1.5 ** attempt)

    result: dict[str, float] = {}
    for secid, data in all_data.items():
        key = key_map.get(secid, "")
        if key:
            result[key] = data["change_pct"]
    return result
