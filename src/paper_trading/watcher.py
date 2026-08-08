# -*- coding: utf-8 -*-
"""Hermes 模拟交易监视器 — 盘前/盘中/强信号/盘后/复盘 五模式 (2026-08-08).

三条独立触发路径 + 定期复盘:
  --mode premarket  09:20 盘前简报 (隔夜美股/自选信号/当日计划) → 微信
  --mode intraday   盘中每30分钟快检 → 有交易信号才全量执行 → 成交才推送
  --mode strong     2分钟轮询强信号 (日线买点/周线破位/r035) → 触发即推送+执行
  --mode close      15:05 盘后复盘 (当日交易/持仓盈亏/明日计划) → 微信
  --mode review     周/月/季盈亏复盘 → 微信

Hermes 约定: stdout 非空 = 投递微信; 空 = 静默。本模块只 print 要推送的内容。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 强信号去重文件 (Hermes 与本地共用)
DEDUP_PATH = Path(
    os.environ.get("BAIZE_PT_DEDUP", "data/paper_trading/strong_signals.json")
)

# 强信号定义阈值
STRONG_BUY_RECS = ("STRONG_BUY", "BUY", "ADD")
STRONG_SELL_RECS = ("SELL", "STRONG_SELL")
WEEKLY_BREAK_DAYS = 5  # 周线破位: 收盘跌破 MA20 连续 N 日

# 盘中急动触发器 (2026-08-08): 相对昨收
FAST_DROP_PCT = -2.0    # 急跌阈值: 盘中跌超 2% 立即触发
FAST_RALLY_PCT = 5.0    # 急拉阈值: 盘中涨超 5% 立即触发
FAST_MOVE_COOLDOWN_H = 1  # 急动冷却: 同标的同方向 1 小时内只提醒一次


# ══════════════════════════════════════════════════════════════════
# 数据/工具
# ══════════════════════════════════════════════════════════════════

def _load_watchlist() -> list[dict]:
    from src.paper_trading.config import PaperTradingConfigManager
    return PaperTradingConfigManager.load_watchlist()


def _market_of(symbol: str) -> str:
    return "SH" if symbol.startswith(("6", "68")) else "SZ"


def _quiet_light_check(symbol: str, name: str):
    """轻量快检: 复用 light_run 产出售价/动作。捕获其 stdout 避免污染微信消息。

    Returns: dict {symbol, name, recommendation, score, action} 或 None(异常)
    """
    from src.routing.light_run import run_light
    from src.routing.orchestrator import Orchestrator

    buf = io.StringIO()
    try:
        orch = Orchestrator()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            result = run_light(
                orch, symbol=symbol, market=_market_of(symbol), name=name,
            )
    except Exception as e:
        logger.debug("light check %s 异常: %s", symbol, e)
        return None

    rec = result.verdict.recommendation if result.verdict else "HOLD"
    score = result.verdict.score if result.verdict else 0.0
    conf = result.verdict.confidence if result.verdict else 0.0
    action = getattr(result.signal, "action", "HOLD") if result.signal else "HOLD"
    return {
        "symbol": symbol, "name": name,
        "recommendation": rec, "score": score, "confidence": conf,
        "action": action,
    }


CHANLUN_MAX_AGE_DAYS = 10  # 缠论买点时效: 超过 N 天视为过期信号(避免旧买点误触发)


def _chanlun_recent(msg: str, max_age_days: int = CHANLUN_MAX_AGE_DAYS) -> bool:
    """判断缠论买点消息里的信号日期是否在时效内。"""
    import re
    m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", msg or "")
    if not m:
        return False
    try:
        sig_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        return (datetime.now().date() - sig_date).days <= max_age_days
    except ValueError:
        return False


def _check_chanlun(symbol: str, name: str) -> str | None:
    """缠论买点检测 (一买/二买/三买), 仅返回时效内信号。"""
    from src.sentinel.channels import _check_chanlun_buy_signal
    try:
        msg = _check_chanlun_buy_signal(symbol, name)
        if msg and _chanlun_recent(msg):
            return msg
        return None
    except Exception:
        return None


def _buy_point_hint(symbol: str) -> str | None:
    """买点可达性简化: 现价 vs MA20 支撑距离 (大白话)。"""
    try:
        from src.data.aggregator import DataAggregator
        agg = DataAggregator()
        bars = agg.get_history(symbol)
        if bars is None or getattr(bars, "empty", True):
            return None
        closes = bars["close"].astype(float)
        if len(closes) < 20:
            return None
        ma20 = float(closes.rolling(20).mean().iloc[-1])
        cur = float(closes.iloc[-1])
        if cur <= 0 or ma20 <= 0:
            return None
        dist = (cur / ma20 - 1) * 100
        if dist <= 0:
            return f"现价已跌破 MA20 (低 {abs(dist):.1f}%) — 支撑下方，留意趋势"
        if dist <= 3:
            return f"现价贴近 MA20 支撑 (高出 {dist:.1f}%) — 买点区附近"
        return f"现价高出 MA20 支撑 {dist:.1f}% — 等回踩"
    except Exception:
        return None


def _fast_check(symbol: str, name: str) -> dict:
    """快速预筛 (秒级, 盘中/强信号用): 缠论买点 + MA20 支撑/破位。

    只做轻量计算 (单次 bars 拉取), 不跑全量管道。有候选才由上层跑全量确认。

    Returns: {symbol, name, chanlun, hint, below_ma20, buy_candidate, sell_candidate}
    """
    out = {
        "symbol": symbol, "name": name,
        "chanlun": None, "hint": None,
        "below_ma20": False, "buy_candidate": False, "sell_candidate": False,
    }
    cl = _check_chanlun(symbol, name)
    if cl:
        out["chanlun"] = cl
        out["buy_candidate"] = True
    try:
        from src.data.aggregator import DataAggregator
        agg = DataAggregator()
        bars = agg.get_history(symbol)
        if bars is None or getattr(bars, "empty", True):
            return out
        closes = bars["close"].astype(float)
        if len(closes) < 20:
            return out
        ma20 = float(closes.rolling(20).mean().iloc[-1])
        cur = float(closes.iloc[-1])
        if cur > 0 and ma20 > 0:
            dist = (cur / ma20 - 1) * 100
            if dist <= 0:
                out["hint"] = f"现价已跌破 MA20 (低 {abs(dist):.1f}%) — 支撑下方"
            elif dist <= 3:
                out["hint"] = f"现价贴近 MA20 支撑 (高出 {dist:.1f}%) — 买点区附近"
                out["buy_candidate"] = True
            else:
                out["hint"] = f"现价高出 MA20 支撑 {dist:.1f}% — 等回踩"
        # 破位: 连续 N 日收盘跌破 MA20
        below = (closes < ma20).tail(WEEKLY_BREAK_DAYS)
        if len(below) == WEEKLY_BREAK_DAYS and bool(below.all()):
            out["below_ma20"] = True
            out["sell_candidate"] = True
    except Exception:
        pass
    return out


# ══════════════════════════════════════════════════════════════════
# 强信号检测 + 去重
# ══════════════════════════════════════════════════════════════════

def _check_strong_signal(symbol: str, name: str) -> dict | None:
    """检测强信号: 日线买点(裁决BUY+置信)/周线破位/r035跌破。

    Returns: {"signal": "buy"|"sell", "reason": str, "score": float} 或 None
    """
    sig = _quiet_light_check(symbol, name)
    if not sig:
        return None

    rec = sig["recommendation"]
    score = sig["score"]
    conf = sig["confidence"]

    # 买入强信号: 裁决 STRONG_BUY/BUY/ADD 且置信度 ≥ 0.6
    if rec in STRONG_BUY_RECS and conf >= 0.6:
        return {
            "signal": "buy", "score": score,
            "reason": f"日线买点触发: 裁决 {rec} 评分{score:.0f} 置信{conf:.0%}",
        }

    # 卖出/风险强信号: 裁决 SELL 或 周线破位
    if rec in STRONG_SELL_RECS:
        return {
            "signal": "sell", "score": score,
            "reason": f"日线卖点触发: 裁决 {rec} 评分{score:.0f}",
        }

    # 周线破位: 收盘连续跌破 MA20
    try:
        from src.data.aggregator import DataAggregator
        agg = DataAggregator()
        bars = agg.get_history(symbol)
        if bars is not None and not getattr(bars, "empty", True):
            closes = bars["close"].astype(float)
            if len(closes) >= 30:
                ma20 = closes.rolling(20).mean()
                below = (closes < ma20).tail(WEEKLY_BREAK_DAYS)
                if bool(below.all()) and len(below) == WEEKLY_BREAK_DAYS:
                    return {
                        "signal": "sell", "score": score,
                        "reason": f"周线破位: 连续{WEEKLY_BREAK_DAYS}日收盘跌破MA20",
                    }
    except Exception:
        pass

    return None


def _realtime_quote(symbol: str):
    """实时行情快照。"""
    from src.data.aggregator import DataAggregator
    agg = DataAggregator()
    return agg.get_realtime_quote(symbol, _market_of(symbol))


def _check_fast_move(symbol: str, name: str) -> dict | None:
    """盘中急动检测 (实时价相对昨收): 急跌≤-2% / 急拉≥+5%。

    Returns: {"signal": "buy"|"sell", "reason": str, "price": float, "pct": float} 或 None
    """
    try:
        q = _realtime_quote(symbol)
        if q is None:
            return None
        pct = getattr(q, "change_pct", 0) or 0
        price = getattr(q, "price", 0) or 0
        if pct <= FAST_DROP_PCT:
            return {"signal": "sell", "price": price, "pct": pct,
                    "reason": f"盘中急跌 {pct:.1f}% (现价{price:.2f})"}
        if pct >= FAST_RALLY_PCT:
            return {"signal": "buy", "price": price, "pct": pct,
                    "reason": f"盘中急拉 {pct:+.1f}% (现价{price:.2f})"}
        return None
    except Exception:
        return None


def _check_stop_breach(symbol: str, name: str, stop_price: float) -> bool:
    """持仓止损实时检测: 现价 ≤ 止损价 → 触发。"""
    if stop_price <= 0:
        return False
    try:
        q = _realtime_quote(symbol)
        if q is None:
            return False
        price = getattr(q, "price", 0) or 0
        return price > 0 and price <= stop_price
    except Exception:
        return False


def _load_dedup() -> dict:
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _dedup_ok(symbol: str, signal_type: str, hours: int = 24) -> bool:
    """同信号 24h 内只提醒一次。触发成功返回 True 并记录。"""
    key = f"{symbol}:{signal_type}"
    data = _load_dedup()
    last = data.get(key)
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.now() - last_dt < timedelta(hours=hours):
                return False
        except ValueError:
            pass
    data[key] = datetime.now().isoformat()
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return True


# ══════════════════════════════════════════════════════════════════
# 微信消息格式化
# ══════════════════════════════════════════════════════════════════

def _fmt_trade(t) -> str:
    action_zh = "买入" if t.action == "buy" else "卖出"
    pnl = f" 盈亏 {t.pnl_pct * 100:+.2f}%" if t.action == "sell" else ""
    return (
        f"🟢 {t.symbol} {t.name} {action_zh} {t.quantity}股 @{t.price:.2f}"
        f" 成本{t.commission + t.stamp_tax + t.transfer_fee:.2f}元{pnl}"
    )


# ══════════════════════════════════════════════════════════════════
# 各模式
# ══════════════════════════════════════════════════════════════════

def _parallel_fast_check(watchlist: list[dict], workers: int = 6) -> list[dict]:
    """并行快速预筛 12 支 (秒级)。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    items = [s for s in watchlist if s.get("symbol")]
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_fast_check, s["symbol"], s.get("name", "")): s
            for s in items
        }
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception:
                pass
    return results


def mode_intraday(force: bool = False) -> str:
    """盘中每30分钟: 快筛(秒级)→有候选才全量执行→成交才推送。"""
    from src.paper_trading.engine import PaperTradingEngine
    watchlist = _load_watchlist()
    checks = _parallel_fast_check(watchlist)
    msgs: list[str] = []
    now = datetime.now().strftime("%H:%M")
    engine = PaperTradingEngine()

    for c in checks:
        sym, name = c["symbol"], c["name"]
        # 有候选 → 全量执行 (引擎只在有信号时成交)
        if c["buy_candidate"] or c["sell_candidate"]:
            trades = engine.execute_symbol(sym, name, force=force)
            for t in trades:
                msgs.append(_fmt_trade(t))
        # 缠论买点 + 支撑提示
        if c["chanlun"] or c["hint"]:
            parts = [f"{sym} {name}"]
            if c["chanlun"]:
                parts.append(c["chanlun"])
            if c["hint"]:
                parts.append(c["hint"])
            if not any(sym in m for m in msgs):
                msgs.append(" | ".join(parts))

    if msgs:
        return f"📊 盘中快检 {now}:\n" + "\n".join(msgs)
    return ""


def mode_strong(force: bool = False) -> str:
    """事件驱动强信号: 快筛→触发即推送+执行 (独立于半小时盯盘)。

    三类触发: 缠论买点 / 连续跌破MA20(24h去重) + 盘中急动/止损(1h冷却)。
    """
    from src.paper_trading.engine import PaperTradingEngine
    watchlist = _load_watchlist()
    checks = _parallel_fast_check(watchlist)
    msgs: list[str] = []
    engine = PaperTradingEngine()
    state = engine.state

    def _trigger(sym, name, title, trades_lines):
        nonlocal msgs
        trades = engine.execute_symbol(sym, name, force=force)
        lines = [f"{title} {sym} {name}"]
        if trades:
            lines.extend(_fmt_trade(t) for t in trades)
        else:
            lines.append("  执行后无成交 (仓位/资金/风控限制)")
        msgs.append("\n".join(lines))

    # ① 缠论买点 / 连续跌破MA20 (24h 去重)
    for c in checks:
        sym, name = c["symbol"], c["name"]
        if c["chanlun"]:
            if _dedup_ok(sym, "buy"):
                _trigger(sym, name, "🚨 强买入信号", None)
        elif c["sell_candidate"] and c["below_ma20"]:
            if _dedup_ok(sym, "sell"):
                _trigger(sym, name, f"🚨 强风险信号 连续{WEEKLY_BREAK_DAYS}日跌破MA20", None)

    # ② 盘中急动 (实时价, 1h 冷却) — 独立于半小时盯盘
    for item in watchlist:
        sym, name = item.get("symbol", ""), item.get("name", "")
        if not sym:
            continue
        fm = _check_fast_move(sym, name)
        if not fm:
            continue
        if not _dedup_ok(sym, f"fast_{fm['signal']}", hours=FAST_MOVE_COOLDOWN_H):
            continue
        title = "⚡ 盘中急跌" if fm["signal"] == "sell" else "⚡ 盘中急拉"
        _trigger(sym, name, f"{title}({fm['pct']:+.1f}%)", None)

    # ③ 持仓止损实时破位 (现价 ≤ 止损价, 1h 冷却)
    for sym, pos in (state.positions or {}).items():
        stop = float(getattr(pos, "stop_price", 0) or 0)
        name = getattr(pos, "name", "") or sym
        if stop <= 0:
            continue
        if _check_stop_breach(sym, name, stop) and _dedup_ok(sym, "stop", hours=1):
            _trigger(sym, name, f"🛑 触发止损 现价≤止损{stop:.2f}", None)

    if msgs:
        return "\n\n".join(msgs)
    return ""


def mode_premarket(force: bool = False) -> str:
    """09:20 盘前简报。"""
    from src.sentinel.channels import ChannelConfig, run_channel
    try:
        msg = run_channel("open", ChannelConfig(force=force))
    except Exception:
        msg = ""
    lines = ["☀️ 盘前分析 09:20"]
    if msg:
        lines.append(msg)
    # 附加 12 支盘前信号快检
    watchlist = _load_watchlist()
    for item in watchlist[:6]:  # 简报只列前 6 支避免过长
        sym, name = item.get("symbol", ""), item.get("name", "")
        if not sym:
            continue
        cl = _check_chanlun(sym, name)
        hint = _buy_point_hint(sym)
        if cl or hint:
            parts = [f"{sym} {name}"]
            if cl:
                parts.append(cl)
            if hint:
                parts.append(hint)
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _today_trades(engine) -> list:
    """今日成交明细 (从 trades.jsonl 按今日过滤)。"""
    from src.paper_trading.scheduler import today_str
    today = today_str()
    try:
        trades = engine.get_recent_trades(limit=50)
        return [t for t in trades if str(getattr(t, "timestamp", ""))[:10] == today]
    except Exception:
        return []


def mode_close(force: bool = False) -> str:
    """15:05 盘后复盘 (每日复盘: 当日成交明细 + 持仓盈亏 + 明日关注)。"""
    from src.sentinel.channels import ChannelConfig, run_channel
    from src.paper_trading.engine import PaperTradingEngine

    engine = PaperTradingEngine()
    state = engine.state
    lines = ["🌆 每日复盘 15:05"]

    # ① 今日成交明细 + 当日已实现盈亏
    today_trades = _today_trades(engine)
    realized = 0.0
    if today_trades:
        lines.append("📋 今日成交:")
        for t in today_trades:
            action_zh = "买入" if t.action == "buy" else "卖出"
            costs = t.commission + t.stamp_tax + t.transfer_fee
            if t.action == "sell" and t.pnl_pct > -1:
                # 已实现盈亏 = 卖出净得 - 持仓成本
                entry_est = t.price / (1.0 + t.pnl_pct)
                realized += t.notional - costs - entry_est * t.quantity
                lines.append(
                    f"  · {t.symbol} {t.name} 卖出 {t.quantity}股 @{t.price:.2f}"
                    f" 成本{costs:.2f}元 盈亏{t.pnl_pct * 100:+.2f}%"
                )
            else:
                lines.append(
                    f"  · {t.symbol} {t.name} 买入 {t.quantity}股 @{t.price:.2f}"
                    f" 成本{costs:.2f}元"
                )
        lines.append(f"  → 当日已实现盈亏 {realized:+,.2f} 元")
    else:
        lines.append("📋 今日无成交")

    # ② 账户状态 (权益/收益/持仓)
    pnl_total = state.total_equity - state.initial_capital
    lines.append(
        f"💰 权益 ¥{state.total_equity:,.2f} "
        f"(累计{pnl_total:+,.2f} {state.total_return_pct:+.2%}) "
        f"| 现金 ¥{state.cash:,.2f} | 持仓 {state.position_count}只"
    )
    if state.positions:
        for sym, pos in state.positions.items():
            entry = getattr(pos, "entry_price", 0)
            last = getattr(pos, "last_price", entry)
            p = (last - entry) / entry * 100 if entry > 0 else 0
            lines.append(f"  · {sym} {getattr(pos,'name','')}: {pos.quantity}股 成本{entry:.2f} 现价{last:.2f} {p:+.2f}%")

    # ③ 大盘背景
    try:
        msg = run_channel("close", ChannelConfig(force=force))
        if msg:
            lines.append(msg)
    except Exception:
        pass

    return "\n".join(lines)


def _is_review_day(period: str, today=None) -> bool:
    """周/月/季复盘边界检查: 是否到了复盘日。

    weekly: 周五(当周最后交易日); monthly: 当月最后交易日;
    quarterly: 当季最后交易日。非边界日返回 False (静默)。
    """
    from src.paper_trading.scheduler import is_trading_day, trading_days_in_range
    today = today or datetime.now().date()
    if not is_trading_day(today):
        return False
    if period == "weekly":
        # 本周最后一个交易日
        import calendar
        weekdays = [d for d in range(today.day - today.weekday(), today.day + (7 - today.weekday()))
                    if d <= calendar.monthrange(today.year, today.month)[1]]
        last_of_week = max(
            (today.replace(day=d) for d in weekdays if is_trading_day(today.replace(day=d))),
            default=today,
        )
        return today == last_of_week
    if period == "monthly":
        days = trading_days_in_range(
            today.replace(day=1),
            today.replace(day=28),  # 28 以后逐步接近月末
        ) if False else None
        # 直接用月末最后交易日判断
        import calendar
        last_day = calendar.monthrange(today.year, today.month)[1]
        candidates = [
            today.replace(day=d)
            for d in range(max(1, last_day - 6), last_day + 1)
            if is_trading_day(today.replace(day=d))
        ]
        return today == max(candidates) if candidates else False
    if period == "quarterly":
        q_end_month = {"1": 3, "2": 6, "3": 9, "4": 12}[str((today.month - 1) // 3 + 1)]
        if today.month != q_end_month:
            return False
        import calendar
        last_day = calendar.monthrange(today.year, q_end_month)[1]
        candidates = [
            today.replace(day=d)
            for d in range(max(1, last_day - 6), last_day + 1)
            if is_trading_day(today.replace(day=d))
        ]
        return today == max(candidates) if candidates else False
    return True


def mode_review(period: str = "weekly", force: bool = False) -> str:
    """周/月/季盈亏复盘 (非复盘日静默)。"""
    from src.paper_trading.engine import PaperTradingEngine
    if not force and not _is_review_day(period):
        return ""
    engine = PaperTradingEngine()
    state = engine.state
    trades = engine.get_recent_trades(limit=200)

    period_zh = {"weekly": "周", "monthly": "月", "quarterly": "季"}.get(period, "周")
    pnl = state.total_equity - state.initial_capital
    lines = [
        f"📈 {period_zh}度盈亏复盘",
        f"  初始资金 ¥{state.initial_capital:,.0f} → 当前权益 ¥{state.total_equity:,.2f}",
        f"  累计盈亏 ¥{pnl:+,.2f} ({state.total_return_pct:+.2%})",
        f"  交易 {state.total_trades} 笔 | 胜率 {state.win_rate:.1%} "
        f"({state.winning_trades}W/{state.losing_trades}L)",
        f"  当前回撤 {state.drawdown_pct:.2%} | 持仓 {state.position_count} 只",
    ]
    if state.positions:
        lines.append("  持仓:")
        for sym, pos in state.positions.items():
            entry = getattr(pos, "entry_price", 0)
            last = getattr(pos, "last_price", entry)
            pnl_pct = (last - entry) / entry * 100 if entry > 0 else 0
            lines.append(
                f"    {sym} {getattr(pos,'name','')}: {pos.quantity}股 "
                f"成本{entry:.2f} 现价{last:.2f} {pnl_pct:+.2f}%"
            )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

MODES = ("premarket", "intraday", "strong", "close", "review")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes 模拟交易监视器")
    parser.add_argument("--mode", choices=MODES, default="intraday")
    parser.add_argument("--period", choices=("weekly", "monthly", "quarterly"), default="weekly")
    parser.add_argument("--force", action="store_true", help="忽略交易时段")
    args = parser.parse_args(argv)

    # 交易日门禁: 非交易日 (周末/节假日) 的盘前/盘中/盘后/强信号一律静默,
    # 即使 cron 在周中节假日误触发也不推送陈旧简报。复盘模式自含边界判断。
    if not args.force and args.mode in ("premarket", "intraday", "strong", "close"):
        from src.paper_trading.scheduler import is_trading_day
        if not is_trading_day():
            return 0  # 静默

    try:
        if args.mode == "intraday":
            msg = mode_intraday(force=args.force)
        elif args.mode == "strong":
            msg = mode_strong(force=args.force)
        elif args.mode == "premarket":
            msg = mode_premarket(force=args.force)
        elif args.mode == "close":
            msg = mode_close(force=args.force)
        else:
            msg = mode_review(period=args.period, force=args.force)
    except Exception as e:
        print(f"❌ 监视器异常: {e}", file=sys.stderr)
        return 1

    if msg and msg.strip():
        print(msg, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
