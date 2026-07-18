# -*- coding: utf-8 -*-
"""盘面/板块轻量背景 — 给推送加「为什么现在要动」。

优先纯 HTTP（腾讯指数），情绪/板块失败则降级，不拖垮哨兵。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .quotes import fetch_tencent_batch

logger = logging.getLogger(__name__)

# 持仓/自选常见票 → 板块人话名（无远程行业库时兜底）
_SECTOR_HINTS: dict[str, str] = {
    "002460": "锂电/有色",
    "600089": "电力设备",
    "002463": "PCB/算力硬件",
    "000938": "IT设备",
    "603986": "半导体",
    "600845": "软件",
    "002415": "安防/AI",
    "600765": "军工",
    "600862": "军工",
}

# 板块名关键词 → 东财/申万模糊匹配用
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "锂电/有色": ["锂", "有色", "电池", "新能源"],
    "PCB/算力硬件": ["印制电路", "PCB", "电子"],
    "半导体": ["半导体", "芯片"],
    "软件": ["软件", "计算机"],
    "军工": ["军工", "航天"],
    "电力设备": ["电力设备", "电网"],
    "IT设备": ["计算机", "通信设备"],
    "安防/AI": ["安防", "计算机"],
}


@dataclass
class MarketBackdrop:
    """大盘 + 可选板块一行背景。"""

    hs300_pct: Optional[float] = None
    sh_pct: Optional[float] = None
    zt_count: Optional[int] = None
    dt_count: Optional[int] = None
    break_rate: Optional[float] = None
    sentiment_level: str = ""
    sentiment_score: Optional[int] = None
    sentiment_summary: str = ""
    northbound_note: str = ""
    sector_name: str = ""
    sector_pct: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    def market_line(self) -> str:
        """大盘一行：常用术语直写，少见术语加括号说明。"""
        parts: list[str] = []
        if self.hs300_pct is not None:
            parts.append(f"沪深300 {self.hs300_pct:+.1f}%")
        elif self.sh_pct is not None:
            parts.append(f"上证 {self.sh_pct:+.1f}%")
        if self.zt_count is not None and self.dt_count is not None:
            if self.zt_count > 0 or self.dt_count > 0:
                parts.append(f"涨停{self.zt_count}/跌停{self.dt_count}")
        if self.break_rate is not None and self.break_rate > 0:
            parts.append(
                f"炸板率{self.break_rate*100:.0f}%"
                f"（涨停后又打开的比例，偏高=短线情绪弱）"
            )
        if self.sentiment_level and self.sentiment_level != "NORMAL":
            parts.append(f"情绪{self._sentiment_zh()}")
        if self.northbound_note and "未获取" not in self.northbound_note:
            parts.append(self.northbound_note)
        return " · ".join(parts) if parts else ""

    def sector_line(self) -> str:
        if not self.sector_name:
            return ""
        if self.sector_pct is not None:
            return f"{self.sector_name} {self.sector_pct:+.1f}%"
        return self.sector_name

    def background_block(self) -> str:
        lines: list[str] = []
        m = self.market_line()
        if m:
            lines.append(f"大盘：{m}")
        s = self.sector_line()
        if s:
            lines.append(f"板块：{s}")
        if self.sentiment_summary:
            sm = self.sentiment_summary.strip()
            if len(sm) > 80:
                sm = sm[:77] + "…"
            if "未获取" not in sm and "失败" not in sm:
                lines.append(f"情绪：{sm}")
        return "\n".join(lines)

    def _sentiment_zh(self) -> str:
        mapping = {
            "EXTREME_PANIC": "极度恐慌",
            "PANIC": "恐慌",
            "NORMAL": "中性",
            "GREED": "贪婪",
            "EXTREME_GREED": "极度贪婪",
        }
        return mapping.get(self.sentiment_level, self.sentiment_level or "未知")


def fetch_index_moves() -> tuple[Optional[float], Optional[float]]:
    """腾讯：沪深300 / 上证指数涨跌幅。

    注意：000300/000001 都是上海指数，不能走默认 sz 前缀。
    """
    import urllib.request

    from .quotes import UA

    url = "https://qt.gtimg.cn/q=sh000300,sh000001"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        logger.debug("index fetch failed: %s", e)
        return None, None

    def _parse_pct(blob: str, code_key: str) -> Optional[float]:
        for line in blob.strip().split(";"):
            if code_key not in line or "=" not in line or '"' not in line:
                continue
            raw = line.split('"', 1)[1].rsplit('"', 1)[0]
            vals = raw.split("~")
            if len(vals) < 33:
                continue
            try:
                return float(vals[32] or 0)
            except ValueError:
                return None
        return None

    return _parse_pct(data, "sh000300"), _parse_pct(data, "sh000001")


def fetch_sentiment_backdrop() -> dict:
    """可选：情绪检测（依赖 akshare 等，失败返回空）。

    屏蔽模块内 print，避免污染 Hermes stdout 推送。
    """
    import contextlib
    import io

    try:
        from src.sentiment.signals import SentimentDetector

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            det = SentimentDetector()
            s = det.detect_market()
        nb = ""
        if getattr(s, "northbound_insight", None):
            raw_nb = str(s.northbound_insight).strip()
            if raw_nb and "未获取" not in raw_nb and "无法判断" not in raw_nb:
                nb = raw_nb[:40]
        # 从 indicators 里抠北向净流入数字（若有）
        for ind in getattr(s, "indicators", []) or []:
            if "北向" in (ind.name or "") or "north" in (ind.en_name or "").lower():
                try:
                    nb = f"北向约{float(ind.current_value):.0f}{ind.unit or ''}"
                except (TypeError, ValueError):
                    pass
                break
        summary = (s.summary or "").strip()
        # 太平淡的摘要可保留；错误腔调丢掉
        if "失败" in summary or "DATA_GAP" in summary:
            summary = ""
        return {
            "level": s.level.value if s.level else "",
            "score": s.score,
            "summary": summary,
            "northbound": nb,
            "zt": _ind_int(s, "涨停"),
            "dt": _ind_int(s, "跌停"),
            "break_rate": _ind_break(s),
            "extreme": list(s.extreme_signals or []),
            "panic": list(s.panic_signals or []),
            "greed": list(s.greed_signals or []),
            "is_extreme": s.level.value in ("EXTREME_PANIC", "EXTREME_GREED", "PANIC")
            if s.level
            else False,
        }
    except Exception as e:
        logger.debug("sentiment backdrop failed: %s", e)
        return {}


def _ind_int(sentiment, name_kw: str) -> Optional[int]:
    for ind in getattr(sentiment, "indicators", []) or []:
        if name_kw in (ind.name or ""):
            try:
                return int(ind.current_value)
            except (TypeError, ValueError):
                return None
    return None


def _ind_break(sentiment) -> Optional[float]:
    for ind in getattr(sentiment, "indicators", []) or []:
        if "炸板" in (ind.name or "") or ind.en_name == "break_rate":
            v = float(ind.current_value or 0)
            # 有的源是 0-100，有的是 0-1
            return v / 100.0 if v > 1.0 else v
    return None


def fetch_sector_pct(sector_label: str) -> Optional[float]:
    """尝试从板块排名拿涨跌幅。"""
    if not sector_label:
        return None
    kws = _SECTOR_KEYWORDS.get(sector_label, [sector_label])
    try:
        from src.industry.daily_ranking import SectorRanking, fetch_sector_quotes_from_mootdx

        quotes = fetch_sector_quotes_from_mootdx()
        if not quotes:
            return None
        result = SectorRanking().rank(quotes)
        best = None
        best_score = -1
        for item in list(result.top_gainers or []) + list(result.top_losers or []):
            name = getattr(item, "name", "") or ""
            score = sum(1 for k in kws if k in name)
            if score > best_score:
                best_score = score
                best = item
        # 也扫全列表
        for item in getattr(result, "rankings", None) or []:
            name = getattr(item, "name", "") or ""
            score = sum(1 for k in kws if k in name)
            if score > best_score:
                best_score = score
                best = item
        if best is not None and best_score > 0:
            return float(getattr(best, "change_pct", 0) or 0)
    except Exception as e:
        logger.debug("sector pct failed: %s", e)
    return None


def build_backdrop_for_symbols(symbols: list[str]) -> MarketBackdrop:
    """为持仓/自选构建背景。"""
    bd = MarketBackdrop()
    hs, sh = fetch_index_moves()
    bd.hs300_pct = hs
    bd.sh_pct = sh

    sent = fetch_sentiment_backdrop()
    if sent:
        bd.sentiment_level = sent.get("level") or ""
        bd.sentiment_score = sent.get("score")
        bd.sentiment_summary = sent.get("summary") or ""
        bd.northbound_note = sent.get("northbound") or ""
        bd.zt_count = sent.get("zt")
        bd.dt_count = sent.get("dt")
        bd.break_rate = sent.get("break_rate")

    # 板块：优先第一只持仓提示
    for sym in symbols:
        label = _SECTOR_HINTS.get(sym, "")
        if label:
            bd.sector_name = label
            bd.sector_pct = fetch_sector_pct(label)
            break

    return bd


def sector_label_for(symbol: str) -> str:
    return _SECTOR_HINTS.get(symbol, "")
