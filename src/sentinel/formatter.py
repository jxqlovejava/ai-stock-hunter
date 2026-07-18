# -*- coding: utf-8 -*-
"""哨兵推送文案 — 聚合 + 简洁人话 + 单票组合去重。

风格:
  - 常用术语保留：止损、浮盈/浮亏、成本、北向、主因/情况/建议
  - 少见术语保留词 + 括号一句解释（两融、炸板率等）
  - 不啰嗦，不写成「教小朋友」口吻
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .models import AlertLevel, SentinelAlert

_LEVEL_ZH: dict[AlertLevel, str] = {
    AlertLevel.P0: "紧急",
    AlertLevel.P1: "注意",
    AlertLevel.P2: "观察",
}

_RULE_LABEL: dict[str, str] = {
    "stop_hit": "触及止损",
    "stop_near": "止损逼近",
    "float_loss": "浮亏超限",
    "cost_break": "跌破成本",
    "peak_drawdown": "高点回撤",
    "day_drop": "日内急跌",
    "day_rise": "日内急涨",
    "jump": "分钟跳变",
    "accel": "连续同向",
    "single_overweight": "单票仓位过大",
    "total_exposure": "总仓位过高",
    "cash_low": "现金不足",
    "portfolio_loss": "组合浮亏超限",
    "macd_kdj_exit": "技术离场信号",
    "macd_kdj_avoid": "勿追假反弹",
    "macd_kdj_enter": "技术共振提示",
    "macd_kdj_hold": "洗盘持股提示",
}

_RULE_ADVICE: dict[str, str] = {
    "stop_hit": "按纪律减/平，勿补仓硬扛",
    "stop_near": "准备执行止损，勿幻想反弹硬扛",
    "float_loss": "风控优先，评估减仓；禁止补仓摊薄",
    "cost_break": "勿补仓；若同步逼近止损，优先风控",
    "peak_drawdown": "可考虑分批止盈或上移止损，勿因回撤情绪化加仓",
    "day_drop": "先核对止损线，勿恐慌乱补",
    "day_rise": "可评估分批止盈/上移止损，勿追高加仓",
    "jump": "波动加大，暂勿冲动加减仓",
    "accel": "连续同向加速，守住止损/止盈纪律",
    "single_overweight": "禁止加仓，计划降到仓位上限内",
    "total_exposure": "禁止新开仓，优先减超限单票",
    "cash_low": "停止加仓，保留现金缓冲",
    "portfolio_loss": "暂停新开；逐票检查止损，勿情绪化补仓",
    "macd_kdj_exit": "对照止损与卖点纪律；技术信号仅参考，非下单指令",
    "macd_kdj_avoid": "持仓勿加仓摊薄；空仓勿抄底",
    "macd_kdj_enter": "已持仓也勿仅凭此加仓",
    "macd_kdj_hold": "勿因短线抖动恐慌割肉；仍守止损",
}

_RULE_RANK: dict[str, int] = {
    "stop_hit": 0,
    "stop_near": 1,
    "float_loss": 2,
    "portfolio_loss": 3,
    "day_drop": 10,
    "cost_break": 11,
    "peak_drawdown": 12,
    "macd_kdj_exit": 13,
    "single_overweight": 14,
    "total_exposure": 15,
    "cash_low": 16,
    "day_rise": 20,
    "macd_kdj_avoid": 21,
    "jump": 30,
    "accel": 31,
    "macd_kdj_enter": 32,
    "macd_kdj_hold": 33,
}

_LEVEL_ORDER = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2}
_AMPLITUDE_PREFIX = "amplitude_"


def rule_label(rule_id: str) -> str:
    if rule_id.startswith(_AMPLITUDE_PREFIX):
        th = rule_id[len(_AMPLITUDE_PREFIX) :]
        return f"日内振幅≥{th}%"
    return _RULE_LABEL.get(rule_id, rule_id)


def rule_advice(rule_id: str) -> str:
    if rule_id.startswith(_AMPLITUDE_PREFIX):
        return "波动加大，核对止损与仓位，勿情绪化操作"
    return _RULE_ADVICE.get(rule_id, "留意盘面，按既定纪律操作")


def _rule_rank(rule_id: str) -> int:
    if rule_id.startswith(_AMPLITUDE_PREFIX):
        return 35
    return _RULE_RANK.get(rule_id, 50)


def _alert_sort_key(a: SentinelAlert) -> tuple:
    return (
        _LEVEL_ORDER.get(a.level, 9),
        _rule_rank(a.rule_id),
        a.symbol,
        a.rule_id,
    )


def dedupe_portfolio_when_single_name(
    alerts: list[SentinelAlert],
    scanned: int = 0,
) -> list[SentinelAlert]:
    stock_alerts = [a for a in alerts if a.symbol and a.symbol != "PORTFOLIO"]
    stock_symbols = {a.symbol for a in stock_alerts}
    n_stocks = scanned if scanned > 0 else len(stock_symbols)
    if n_stocks == 1 and stock_alerts:
        return [a for a in alerts if a.rule_id != "portfolio_loss"]
    return list(alerts)


def _num(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text or "")
    return m.group(1) if m else None


def _situation_lines(primary: SentinelAlert, others: list[SentinelAlert]) -> list[str]:
    """从 body 抽 1～2 行情况，保留常用术语。"""
    body = primary.body or ""
    lines: list[str] = []
    for raw in body.splitlines():
        s = raw.strip()
        if not s or s.startswith("动作") or s.startswith("性质"):
            continue
        lines.append(s)
        if len(lines) >= 2:
            break
    if not lines:
        lines = [rule_label(primary.rule_id)]
    return lines


def format_group_card(alerts: list[SentinelAlert], ts: str = "") -> str:
    if not alerts:
        return ""
    ordered = sorted(alerts, key=_alert_sort_key)
    primary = ordered[0]
    rest = ordered[1:]

    level_zh = _LEVEL_ZH.get(primary.level, primary.level.value)
    name = primary.name or primary.symbol
    symbol = primary.symbol

    if symbol == "PORTFOLIO":
        head = f"【{level_zh}·组合】"
    else:
        head = f"【{level_zh}·{name} {symbol}】"

    out: list[str] = [head]

    if primary.price and primary.price > 0:
        price_line = f"现价 {primary.price:.2f}"
        if ts:
            price_line += f" · {ts}"
        out.append(price_line)

    out.append(f"主因：{rule_label(primary.rule_id)}")

    sits = _situation_lines(primary, rest)
    if sits:
        out.append(f"情况：{sits[0]}")
        for extra in sits[1:]:
            out.append(f"　　{extra}")

    out.append(f"建议：{rule_advice(primary.rule_id)}")

    if rest:
        labels = [rule_label(a.rule_id) for a in rest]
        seen: set[str] = set()
        uniq: list[str] = []
        for lb in labels:
            if lb not in seen:
                seen.add(lb)
                uniq.append(lb)
        out.append(f"（同触发：{'、'.join(uniq)} — 已合并）")

    return "\n".join(out)


def _group_key(a: SentinelAlert) -> str:
    return a.symbol or "UNKNOWN"


def format_sentinel_message(
    alerts: Iterable[SentinelAlert],
    *,
    ts: str = "",
    scanned: int = 0,
    errors: list[str] | None = None,
) -> str:
    items = list(alerts)
    if not items:
        return ""

    items = dedupe_portfolio_when_single_name(items, scanned=scanned)
    if not items:
        return ""

    groups: dict[str, list[SentinelAlert]] = defaultdict(list)
    for a in items:
        groups[_group_key(a)].append(a)

    def group_order(sym: str) -> tuple:
        g = groups[sym]
        best = min((_LEVEL_ORDER.get(a.level, 9) for a in g), default=9)
        is_port = 1 if sym == "PORTFOLIO" else 0
        return (is_port, best, sym)

    cards: list[str] = []
    for sym in sorted(groups.keys(), key=group_order):
        card = format_group_card(groups[sym], ts=ts)
        if card:
            cards.append(card)

    message = "\n\n".join(cards)
    if errors:
        message += "\n\n⚠️ " + "; ".join(errors[:3])
    return message


def append_context_footer(message: str, backdrop) -> str:
    if not message or not message.strip():
        return message or ""
    try:
        block = backdrop.background_block() if backdrop else ""
    except Exception:
        block = ""
    if not block:
        try:
            m = backdrop.market_line() if backdrop else ""
            s = backdrop.sector_line() if backdrop else ""
            parts = []
            if m:
                parts.append(f"大盘：{m}")
            if s:
                parts.append(f"板块：{s}")
            block = "\n".join(parts)
        except Exception:
            block = ""
    if not block:
        return message
    return message.rstrip() + "\n" + block


def format_human_push(title: str, lines: list[str]) -> str:
    return "\n".join([title] + [ln for ln in lines if ln])
