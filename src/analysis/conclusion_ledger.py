# -*- coding: utf-8 -*-
"""结论时间线 (Conclusion Ledger) — 记录每次分析的结论，供长期追踪与复盘。

设计原则（重要）:
- 本模块是「观测/验证层」：只把每次分析的结论落账为可证伪、带时间戳、
  带 regime 标签的结构化记录，供事后核对「上次结论对了没」。
- 它**绝不**把结论自动回填到策略参数。任何策略参数改动必须走
  learner/evolution 的回测验证门禁 + 人工确认。未验证的经验一律视为假设。
- 每条结论携带 {ts, score, verdict, confidence, falsifiable, price,
  regime} —— 缺失的字段留 None，由显示层标注，不脑补。

存储:
- data/conclusions/<symbol>.jsonl  每标的一条结论时间线（按日期追加）
- data/market_timeline.jsonl       大盘结论时间线
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.output.formatter import REC_LABEL

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parents[2] / "data"
STOCK_DIR = BASE_DIR / "conclusions"
MARKET_LEDGER = BASE_DIR / "market_timeline.jsonl"

# 裁决强度排序（用于显示"方向演进"）；CLOSE 为最强卖
_REC_RANK = {"CLOSE": -1, "SELL": 0, "REDUCE": 1, "HOLD": 2, "ADD": 3, "BUY": 4}
_LABEL_TO_REC = {v: k for k, v in REC_LABEL.items()}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _valid_symbol(symbol: str) -> bool:
    """校验 A 股 6 位代码，防止路径注入。"""
    return bool(re.fullmatch(r"\d{6}", str(symbol or "")))


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------

def append_stock_conclusion(
    symbol: str,
    name: str,
    source: str,
    score: Optional[float] = None,
    verdict: str = "",
    confidence: Optional[float] = None,
    falsifiable: Optional[list[str]] = None,
    price: Optional[float] = None,
    one_line: str = "",
    regime: str = "",
    date: Optional[str] = None,
) -> None:
    """追加一条个股结论。调用方从 AnalysisResult 提取字段，缺省置 None。

    date 供回填历史结论时指定；实时落账时缺省为当天。
    """
    if not _valid_symbol(symbol):
        logger.warning("结论落账跳过：非法代码 %r", symbol)
        return
    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now_iso(),
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "symbol": str(symbol),
        "name": name or "",
        "source": source or "",
        "score": round(float(score), 1) if score is not None else None,
        "verdict": verdict or "",
        "confidence": round(float(confidence), 3) if confidence is not None else None,
        "falsifiable": falsifiable or [],
        "price": round(float(price), 2) if price is not None else None,
        "one_line": one_line or "",
        "regime": regime or "",
    }
    with open(STOCK_DIR / f"{symbol}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_market_conclusion(
    sentiment_score: Optional[float] = None,
    level: str = "",
    percentile: Optional[float] = None,
    confidence: Optional[float] = None,
    quadrant: str = "",
    position_advice: str = "",
    breadth: Optional[float] = None,
    limit_up: Optional[int] = None,
    action: str = "",
    date: Optional[str] = None,
) -> None:
    """追加一条大盘结论。date 供回填历史时指定，实时落账缺省为当天。

    大盘是"每日快照"语义：同一日期已存在时替换旧条目，保持每日一条。
    """
    MARKET_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now_iso(),
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "sentiment_score": round(float(sentiment_score), 1) if sentiment_score is not None else None,
        "level": level or "",
        "percentile": round(float(percentile), 1) if percentile is not None else None,
        "confidence": round(float(confidence), 3) if confidence is not None else None,
        "quadrant": quadrant or "",
        "position_advice": position_advice or "",
        "breadth": round(float(breadth), 3) if breadth is not None else None,
        "limit_up": limit_up,
        "action": action or "",
    }
    _d = entry["date"]
    kept = [e for e in load_market_timeline() if e.get("date") != _d]
    kept.append(entry)
    with open(MARKET_LEDGER, "w", encoding="utf-8") as f:
        for e in kept:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def load_stock_timeline(symbol: str) -> list[dict]:
    if not _valid_symbol(symbol):
        return []
    path = STOCK_DIR / f"{symbol}.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_market_timeline() -> list[dict]:
    """读取大盘时间线。按日期去重，同一日期只保留最后一条（每日快照语义）。"""
    if not MARKET_LEDGER.exists():
        return []
    entries = [
        json.loads(line)
        for line in MARKET_LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_day: dict[str, dict] = {}
    for e in entries:
        by_day[e.get("date") or ""] = e
    return [by_day[d] for d in sorted(by_day) if d]


def list_timeline_stocks() -> list[str]:
    if not STOCK_DIR.exists():
        return []
    return sorted(p.stem for p in STOCK_DIR.glob("*.jsonl"))


# ---------------------------------------------------------------------------
# 显示
# ---------------------------------------------------------------------------

def format_stock_timeline(symbol: str, entries: list[dict]) -> str:
    """格式化某标的结论演进：日期 / 来源 / 裁决 / 评分 / 置信度 / 价格 / 一句结论。"""
    if not entries:
        return f"⏳ {symbol} 暂无结论记录。"
    lines = [f"📈 结论时间线 — {entries[0].get('name') or symbol} ({symbol})  共 {len(entries)} 条"]
    lines.append("")
    lines.append("| 日期 | 来源 | 裁决 | 评分 | 置信度 | 价格 | 一句结论 |")
    lines.append("|------|------|------|:---:|:---:|------:|----------|")
    prev_rank: Optional[int] = None
    for e in entries:
        d = (e.get("date") or e.get("ts") or "")[:10]
        src = e.get("source") or "?"
        v = e.get("verdict") or ""
        score = e.get("score")
        conf = e.get("confidence")
        price = e.get("price")
        one = (e.get("one_line") or "")[:24]
        arrow = ""
        if prev_rank is not None and v in _REC_RANK and prev_rank in _REC_RANK:
            r = _REC_RANK[v]
            arrow = " ↗" if r > prev_rank else (" ↘" if r < prev_rank else " →")
        if v in _REC_RANK:
            prev_rank = _REC_RANK[v]
        lines.append(
            f"| {d} | {src} | {v}{arrow} | "
            f"{score if score is not None else '—'} | "
            f"{f'{conf:.0%}' if conf is not None else '—'} | "
            f"{price if price is not None else '—'} | {one} |"
        )
    lines.append("")
    # 最新一条的可证伪条件
    latest = entries[-1]
    fals = latest.get("falsifiable") or []
    if fals:
        lines.append(f"🔬 最新证伪条件（{latest.get('date')}）:")
        for f in fals[:5]:
            lines.append(f"  - {f}")
    lines.append("")
    lines.append("> ⚠️ 本表为观测记录，不含自动策略调整。裁决演进仅供复盘，是否调仓需人工判断。")
    return "\n".join(lines)


def format_market_timeline(entries: list[dict]) -> str:
    if not entries:
        return "⏳ 大盘暂无结论记录。"
    lines = [f"📈 大盘结论时间线  共 {len(entries)} 条"]
    lines.append("")
    lines.append("| 日期 | 情绪 | 评分 | 分位 | 置信度 | 货币信用象限 | 仓位建议 |")
    lines.append("|------|------|:---:|:---:|:---:|------------|----------|")
    for e in entries:
        d = (e.get("date") or e.get("ts") or "")[:10]
        lv = e.get("level") or ""
        sc = e.get("sentiment_score")
        pc = e.get("percentile")
        cf = e.get("confidence")
        qd = e.get("quadrant") or ""
        pa = e.get("position_advice") or ""
        lines.append(
            f"| {d} | {lv} | {sc if sc is not None else '—'} | "
            f"{pc if pc is not None else '—'} | {cf if cf is not None else '—'} | {qd} | {pa} |"
        )
    lines.append("")
    lines.append("> ⚠️ 观测记录，不含自动策略调整。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 回填（尽力而为，从存量数据）
# ---------------------------------------------------------------------------

def backfill_market_from_sentiment_history() -> int:
    """从 data/sentiment_history.json 回填大盘情绪时间线。返回新增条数。"""
    src = BASE_DIR / "sentiment_history.json"
    if not src.exists():
        return 0
    try:
        history = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("大盘回填失败: sentiment_history.json 解析错误: %s", e)
        return 0
    # 按日去重：每天只保留当日最后一次读数作为"当日结论"
    existing_dates = {e.get("date") for e in load_market_timeline()}
    by_day: dict[str, dict] = {}
    for h in history:
        ts = h.get("timestamp", "")
        if not ts:
            continue
        date = ts[:10]
        by_day[date] = h  # 后者覆盖 → 保留当日最后一条
    added = 0
    for date, h in sorted(by_day.items()):
        if date in existing_dates:
            continue
        append_market_conclusion(
            sentiment_score=h.get("score"),
            level=h.get("level", ""),
            percentile=h.get("percentile"),
            confidence=h.get("confidence"),
            quadrant="",
            position_advice="",
            date=date,
        )
        existing_dates.add(date)
        added += 1
    return added


def backfill_stock_from_reports(symbol: Optional[str] = None) -> int:
    """从 data/reports/<code>_<name>_<ts>.md 回填存量个股结论。返回新增条数。

    只回填文件名时间戳 + 报告内「综合裁决/核心结论」字段，解析失败跳过。
    """
    reports_dir = BASE_DIR / "reports"
    if not reports_dir.exists():
        return 0
    pattern = re.compile(r"^(\d{6})_(.+?)_(\d{8})_(\d{6})\.md$")
    existing: dict[str, set] = {}
    added = 0
    for path in sorted(reports_dir.glob("*.md")):
        m = pattern.match(path.name)
        if not m:
            continue
        code, name, d8, t6 = m.group(1), m.group(2), m.group(3), m.group(4)
        if symbol and code != symbol:
            continue
        date = f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"
        if code not in existing:
            existing[code] = {e.get("date") for e in load_stock_timeline(code)}
        if date in existing[code]:
            continue
        entry = _extract_conclusion_from_report(path, code, name, date)
        if entry is None:
            continue
        append_stock_conclusion(**entry)
        existing[code].add(date)
        added += 1
    return added


def _extract_conclusion_from_report(path: Path, code: str, name: str, date: str) -> Optional[dict]:
    """从一份报告 MD 里尽力提取结论字段。解析失败返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("报告解析跳过 %s: %s", path.name, e)
        return None

    # 裁决/评分/置信度：优先综合裁决段，其次核心结论段
    verdict, score, conf = "", None, None
    for section in ("综合裁决", "核心结论"):
        m = re.search(
            rf"## ⚖?️? ?{section}.*?\*\*(.+?)\*\* \| 评分 (\d+(?:\.\d+)?)/100 \| 置信度 ([\d.]+)%",
            text, re.S,
        )
        if m:
            label = re.sub(r"[^一-鿿A-Z]+", "", m.group(1)) if m.group(1) else ""
            verdict = _LABEL_TO_REC.get(label, "")
            if not verdict:
                # 标签可能带 emoji，尝试直接匹配 建议买入/可加仓/继续持有/建议减仓/建议卖出/建议清仓
                for lab, rec in REC_LABEL.items():
                    if lab in m.group(1):
                        verdict = rec
                        break
            score = float(m.group(2))
            # 报告里置信度以百分比展示（如 "76%"），统一存 0.0-1.0 比率
            conf = float(m.group(3)) / 100
            break

    # 一句结论
    one_line = ""
    m = re.search(r"💡\s*(.+)", text)
    if m:
        one_line = m.group(1).strip()

    # 当前价格
    price = None
    m = re.search(r"当前\s*([\d.]+)\s*\|\s*买入≤", text)
    if m:
        price = float(m.group(1))
    if price is None:
        m = re.search(r"当前\s*([\d.]+)", text)
        if m:
            price = float(m.group(1))

    # 可证伪条件
    falsifiable: list[str] = []
    m = re.search(r"### 可证伪条件(.*?)(?:\n###|\n##|\Z)", text, re.S)
    if m:
        falsifiable = [ln.strip().lstrip("- ").strip()
                       for ln in m.group(1).splitlines()
                       if ln.strip().startswith("-")]

    if not verdict and score is None:
        return None
    return {
        "symbol": code, "name": name, "source": "report-backfill",
        "score": score, "verdict": verdict, "confidence": conf,
        "falsifiable": falsifiable[:5], "price": price,
        "one_line": one_line, "regime": "", "date": date,
    }
