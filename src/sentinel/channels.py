# -*- coding: utf-8 -*-
"""微信推送频道 — 持仓告警加厚 / 两融 / 自选扫雷 / 开收盘简报 / 情绪极端。

Hermes 约定：返回空字符串 = 静默；非空 = 投递微信。
全部人话，无 P0 机读码。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .context import MarketBackdrop, build_backdrop_for_symbols, sector_label_for
from .engine import SentinelConfig, SentinelEngine, is_trading_time
from .formatter import append_context_footer
from .quotes import fetch_quotes
from .state import SentinelStateStore

logger = logging.getLogger(__name__)
BEIJING = timezone(timedelta(hours=8))

DEFAULT_WATCHLIST = Path("data/watchlist.json")


@dataclass
class ChannelConfig:
    """推送频道路径与开关。"""

    positions_path: Path = Path("data/positions.json")
    state_path: Path = Path("data/sentinel_state.json")
    portfolio_path: Path = Path("data/portfolio.yaml")
    watchlist_path: Path = DEFAULT_WATCHLIST
    force: bool = False
    # 冷却（分钟）
    cool_margin: int = 180  # 两融 3h
    cool_watchlist: int = 60
    cool_briefing: int = 12 * 60  # 同日同档只一次（cron 用日 key 更稳）
    cool_sentiment: int = 120
    enable_margin: bool = True
    enable_watchlist: bool = True
    enable_context: bool = True
    kline_cache_dir: Path = Path("data/kline_cache")


def _now_bj() -> datetime:
    return datetime.now(BEIJING)


def _load_watchlist(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("stocks") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _load_position_symbols(path: Path) -> list[tuple[str, str]]:
    """[(symbol, name), ...]"""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        items = raw.items()
        for sym, d in items:
            if isinstance(d, dict):
                out.append((str(d.get("symbol") or sym), str(d.get("name") or "")))
    elif isinstance(raw, list):
        for d in raw:
            if isinstance(d, dict) and d.get("symbol"):
                out.append((str(d["symbol"]), str(d.get("name") or "")))
    return out


# ── 包1：持仓告警 + 背景 ─────────────────────────────────────────


def run_position_channel(cfg: ChannelConfig) -> str:
    """盘中持仓硬规则 + 大盘/板块/两融一句背景。"""
    sc = SentinelConfig(
        positions_path=cfg.positions_path,
        state_path=cfg.state_path,
        portfolio_path=cfg.portfolio_path,
        force_trading_hours=cfg.force,
    )
    eng = SentinelEngine(sc)
    result = eng.run()
    if result.silent or not result.message.strip():
        return ""

    text = result.message
    pos_syms = [s for s, _ in _load_position_symbols(cfg.positions_path)]

    if cfg.enable_context and pos_syms:
        try:
            bd = build_backdrop_for_symbols(pos_syms)
            text = append_context_footer(text, bd)
        except Exception as e:
            logger.debug("context enrich failed: %s", e)

    # 两融短句：仅 high 级别附在末尾（不另开冷却，跟告警同频）
    if cfg.enable_margin and pos_syms:
        try:
            margin_lines = collect_margin_lines(
                pos_syms,
                only_high=True,
                max_items=2,
            )
            if margin_lines:
                text += (
                    "\n两融（借钱炒股的资金统计）："
                    + "；".join(margin_lines)
                )
        except Exception as e:
            logger.debug("margin footnote failed: %s", e)

    return text.strip()


# ── 包2：两融 + 自选扫雷 ─────────────────────────────────────────


def collect_margin_lines(
    symbols_names: list[tuple[str, str]] | list[str],
    *,
    only_high: bool = False,
    max_items: int = 5,
) -> list[str]:
    """融资融券人话短句列表。"""
    try:
        from src.game_theory.margin import get_margin_analyzer
    except Exception:
        return []

    ma = get_margin_analyzer()
    lines: list[str] = []
    pairs: list[tuple[str, str]] = []
    for item in symbols_names:
        if isinstance(item, tuple):
            pairs.append((item[0], item[1]))
        else:
            pairs.append((str(item), ""))

    for sym, name in pairs:
        try:
            alerts = ma.get_alerts(sym, name or sym)
        except Exception:
            continue
        for a in alerts:
            if only_high and a.severity != "high":
                continue
            if a.severity == "info":
                continue
            line = _margin_human(sym, name, a)
            if line:
                lines.append(line)
            if len(lines) >= max_items:
                return lines
    return lines


def run_margin_channel(cfg: ChannelConfig) -> str:
    """持仓+自选两融异动（medium+），独立推送。"""
    if not cfg.enable_margin:
        return ""
    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")
    cool_key = f"ch:margin:{day}"
    # 日内按 cool_margin 节流
    if not cfg.force and store.is_cooling(cool_key, now):
        # 允许 high 单独 key
        pass

    pos = _load_position_symbols(cfg.positions_path)
    wl = _load_watchlist(cfg.watchlist_path)
    pairs = list(pos)
    seen = {s for s, _ in pairs}
    for s in wl:
        sym = str(s.get("symbol") or "")
        if sym and sym not in seen:
            pairs.append((sym, str(s.get("name") or "")))
            seen.add(sym)

    # 分 high / medium
    high_lines: list[str] = []
    med_lines: list[str] = []
    try:
        from src.game_theory.margin import get_margin_analyzer

        ma = get_margin_analyzer()
        for sym, name in pairs:
            try:
                for a in ma.get_alerts(sym, name or sym):
                    if a.severity == "info":
                        continue
                    ck = f"margin:{sym}:{a.alert_type}:{day}"
                    if not cfg.force and store.is_cooling(ck, now):
                        continue
                    line = _margin_human(sym, name, a)
                    if a.severity == "high":
                        high_lines.append(line)
                        store.set_cooling(ck, cfg.cool_margin, now)
                    else:
                        med_lines.append(line)
                        store.set_cooling(ck, cfg.cool_margin, now)
            except Exception:
                continue
    except Exception as e:
        logger.debug("margin channel failed: %s", e)
        return ""

    store.prune_cooling(now)
    store.save()

    if not high_lines and not med_lines:
        return ""

    parts = ["【两融异动】（两融=借钱炒股的资金统计，日更，仅作旁证）"]
    if high_lines:
        parts.append("要紧：")
        parts.extend(f"· {x}" for x in high_lines[:5])
    if med_lines:
        parts.append("留意：")
        parts.extend(f"· {x}" for x in med_lines[:5])
    return "\n".join(parts)


def _margin_human(sym: str, name: str, a) -> str:
    nm = name or sym
    msg = a.message or ""
    if "接飞刀" in msg:
        return f"{nm}：价跌但两融余额升（接飞刀=下跌时借钱买的人还在接，慎补仓）"
    if "借反弹" in msg or "出货" in msg:
        return f"{nm}：价涨但两融余额降（借反弹出货=涨的时候借钱盘在减仓，慎追）"
    if a.alert_type == "balance_drop":
        return f"{nm}：两融余额骤降（借钱盘在撤）"
    if a.alert_type == "balance_spike":
        return f"{nm}：两融余额暴增（借钱盘加速入场，防过热）"
    if a.alert_type == "consecutive_outflow":
        return f"{nm}：两融连续净流出（借钱盘多日在撤）"
    if a.alert_type == "leverage_extreme":
        return f"{nm}：两融连续净流入（借钱盘偏热）"
    return f"{nm}：{(msg or '')[:70]}"


def run_watchlist_channel(cfg: ChannelConfig) -> str:
    """自选扫雷：大跌/止损/异常放量。"""
    if not cfg.enable_watchlist:
        return ""
    stocks = _load_watchlist(cfg.watchlist_path)
    if not stocks:
        return ""

    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")

    symbols = [str(s["symbol"]) for s in stocks if s.get("symbol")]
    names = {str(s["symbol"]): str(s.get("name") or "") for s in stocks}
    stops = {
        str(s["symbol"]): s.get("stop_price")
        for s in stocks
        if s.get("stop_price")
    }

    quotes, _ = fetch_quotes(symbols, names=names)
    hits: list[str] = []

    for s in stocks:
        sym = str(s.get("symbol") or "")
        if not sym:
            continue
        q = quotes.get(sym)
        if not q or q.price <= 0:
            continue
        name = names.get(sym) or sym
        chg = q.change_pct or 0.0
        reasons: list[str] = []

        stop = stops.get(sym)
        if stop and float(stop) > 0 and q.price <= float(stop):
            reasons.append(f"触及止损 {float(stop):.2f}")
        if chg <= -5.0:
            reasons.append(f"今日大跌 {chg:+.1f}%")
        elif chg <= -3.0:
            reasons.append(f"今日偏弱 {chg:+.1f}%")
        if q.high and q.low and q.prev_close and q.prev_close > 0:
            amp = (q.high - q.low) / q.prev_close * 100
            if amp >= 8 and chg < 0:
                reasons.append(f"振幅{amp:.0f}%且收绿")

        if not reasons:
            continue
        ck = f"wl:{sym}:{day}:{reasons[0][:8]}"
        if not cfg.force and store.is_cooling(ck, now):
            continue
        store.set_cooling(ck, cfg.cool_watchlist, now)
        hits.append(f"{name}({sym}) 现价{q.price:.2f} — " + "，".join(reasons))

    store.prune_cooling(now)
    store.save()

    if not hits:
        return ""

    footer = ""
    try:
        bd = build_backdrop_for_symbols(symbols[:3])
        m = bd.market_line()
        if m:
            footer = f"\n大盘：{m}"
    except Exception:
        pass

    body = "\n".join(f"· {h}" for h in hits[:8])
    return f"【自选扫雷】\n{body}{footer}\n建议：先对持仓与止损，勿盲目抄底补仓。"


def run_funds_and_watchlist(cfg: ChannelConfig) -> str:
    """包2 合并：两融 + 自选（有则拼一张，都无则静默）。"""
    parts: list[str] = []
    m = run_margin_channel(cfg)
    if m:
        parts.append(m)
    w = run_watchlist_channel(cfg)
    if w:
        parts.append(w)
    return "\n\n".join(parts)


# ── 包3：开收盘简报 ─────────────────────────────────────────────


def run_briefing(cfg: ChannelConfig, kind: str = "close") -> str:
    """开盘前 / 收盘后固定简报。kind=open|close"""
    kind = "open" if kind == "open" else "close"
    store = SentinelStateStore(cfg.state_path)
    now_dt = _now_bj()
    day = now_dt.strftime("%Y-%m-%d")
    cool_key = f"briefing:{kind}:{day}"
    now = now_dt.timestamp()
    if not cfg.force and store.is_cooling(cool_key, now):
        return ""

    pos = _load_position_symbols(cfg.positions_path)
    symbols = [s for s, _ in pos]
    names = {s: n for s, n in pos}

    quotes: dict = {}
    if symbols:
        quotes, _ = fetch_quotes(symbols, names=names)

    bd = build_backdrop_for_symbols(symbols or ["002460"])

    title = "【开盘前简报】" if kind == "open" else "【收盘简报】"
    lines = [title, f"{day} {now_dt.strftime('%H:%M')}"]

    m = bd.market_line()
    if m:
        lines.append(f"大盘：{m}")
    if bd.sentiment_summary and "未获取" not in bd.sentiment_summary:
        lines.append(f"情绪：{bd.sentiment_summary[:80]}")
    elif bd.sentiment_level and bd.sentiment_level != "NORMAL":
        lines.append(f"情绪：{bd._sentiment_zh()}")
    if bd.northbound_note and "未获取" not in bd.northbound_note:
        lines.append(f"北向：{bd.northbound_note}")

    if kind == "open":
        us_line = _us_overnight_line()
        if us_line:
            lines.append(f"美股隔夜：{us_line}")

    if pos:
        lines.append("持仓：")
        for sym, name in pos:
            q = quotes.get(sym)
            entry, stop = _pos_cost_stop(cfg.positions_path, sym)
            if q:
                pnl = ((q.price - entry) / entry * 100) if entry and entry > 0 else None
                stop_dist = (
                    (q.price - stop) / q.price * 100
                    if stop and stop > 0 and q.price > 0
                    else None
                )
                bit = (
                    f"· {name or sym}({sym}) {q.price:.2f}"
                    f"（今日{q.change_pct:+.1f}%"
                )
                if pnl is not None:
                    bit += f"，浮盈{pnl:+.1f}%"
                bit += "）"
                if stop_dist is not None:
                    if stop_dist <= 0:
                        bit += " ⚠️已破止损"
                    elif stop_dist < 2:
                        bit += f" 距止损仅{stop_dist:.1f}%"
                sec = sector_label_for(sym)
                if sec:
                    sp = bd.sector_pct if bd.sector_name == sec else None
                    if sp is not None:
                        bit += f" | {sec}{sp:+.1f}%"
                    else:
                        bit += f" | {sec}"
                lines.append(bit)
            else:
                lines.append(f"· {name or sym}({sym}) 行情暂缺")
    else:
        lines.append("持仓：空仓")

    wl_hits = _watchlist_quick_hits(cfg)
    if wl_hits:
        lines.append("自选留意：")
        lines.extend(f"· {h}" for h in wl_hits[:5])

    if symbols:
        try:
            ml = collect_margin_lines(pos, only_high=False, max_items=2)
            if ml:
                lines.append(
                    "两融（借钱炒股资金）：" + "；".join(ml)
                )
        except Exception:
            pass

    if kind == "open":
        lines.append("建议：先定今日纪律（止损/是否允许加仓），勿被集合竞价情绪带节奏。")
    else:
        lines.append("建议：复盘是否触发纪律；有破位先执行，再谈故事。")

    store.set_cooling(cool_key, cfg.cool_briefing, now)
    # 日 key 再锁到次日 6 点左右
    store.set_cooling(cool_key, 20 * 60, now)
    store.save()
    return "\n".join(lines)


def _pos_cost_stop(path: Path, symbol: str) -> tuple[float, Optional[float]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0, None
    d = None
    if isinstance(raw, dict):
        d = raw.get(symbol) or next(
            (v for k, v in raw.items() if isinstance(v, dict) and v.get("symbol") == symbol),
            None,
        )
    if not isinstance(d, dict):
        return 0.0, None
    entry = float(d.get("entry_price") or 0)
    stop = d.get("stop_price")
    return entry, float(stop) if stop not in (None, "") else None


def _us_overnight_line() -> str:
    try:
        from src.data.aggregator import DataAggregator

        us = DataAggregator().get_us_overnight()
        if us is None:
            return ""
        return (us.summary or "")[:100]
    except Exception:
        return ""


def _watchlist_quick_hits(cfg: ChannelConfig) -> list[str]:
    stocks = _load_watchlist(cfg.watchlist_path)
    if not stocks:
        return []
    symbols = [str(s["symbol"]) for s in stocks if s.get("symbol")]
    names = {str(s["symbol"]): str(s.get("name") or "") for s in stocks}
    quotes, _ = fetch_quotes(symbols, names=names)
    hits = []
    for s in stocks:
        sym = str(s.get("symbol") or "")
        q = quotes.get(sym)
        if not q:
            continue
        chg = q.change_pct or 0
        if chg <= -3 or chg >= 5:
            hits.append(
                f"{names.get(sym, sym)} {chg:+.1f}% @ {q.price:.2f}"
            )
    return hits


# ── 包4：情绪/北向极端 ───────────────────────────────────────────


def run_sentiment_extreme(cfg: ChannelConfig) -> str:
    """仅极端情绪/炸板潮/北向大流出时推送。"""
    store = SentinelStateStore(cfg.state_path)
    now_dt = _now_bj()
    day = now_dt.strftime("%Y-%m-%d")
    now = now_dt.timestamp()

    try:
        import contextlib
        import io

        from src.sentiment.signals import SentimentDetector, SentimentLevel

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            s = SentimentDetector().detect_market()
    except Exception as e:
        logger.debug("sentiment extreme failed: %s", e)
        return ""

    level = s.level
    extreme_ok = level in (
        SentimentLevel.EXTREME_PANIC,
        SentimentLevel.EXTREME_GREED,
        SentimentLevel.PANIC,
    )
    # 额外：炸板/跌停潮
    hard = False
    reasons: list[str] = []
    for sig in list(s.extreme_signals or []) + list(s.panic_signals or []):
        reasons.append(sig)
        if "炸板" in sig or "跌停" in sig or "恐慌" in sig:
            hard = True
    for sig in s.greed_signals or []:
        if "极端" in sig or level == SentimentLevel.EXTREME_GREED:
            reasons.append(sig)
            hard = True

    # 北向
    nb_note = ""
    for ind in s.indicators or []:
        if "北向" in (ind.name or ""):
            if ind.current_value <= -50:  # 亿级大幅流出
                nb_note = f"北向大幅流出约 {ind.current_value:.0f}{ind.unit or '亿'}"
                hard = True
                reasons.append(nb_note)
            break

    if not extreme_ok and not hard:
        return ""

    cool_key = f"sentiment:{level.value}:{day}"
    if not cfg.force and store.is_cooling(cool_key, now):
        return ""
    store.set_cooling(cool_key, cfg.cool_sentiment, now)
    store.save()

    zh = {
        SentimentLevel.EXTREME_PANIC: "极度恐慌",
        SentimentLevel.PANIC: "恐慌",
        SentimentLevel.EXTREME_GREED: "极度贪婪",
        SentimentLevel.GREED: "贪婪",
        SentimentLevel.NORMAL: "中性",
    }.get(level, level.value)

    pos = _load_position_symbols(cfg.positions_path)
    pos_hint = ""
    if pos:
        names = "、".join((n or s) for s, n in pos[:3])
        if level in (SentimentLevel.EXTREME_PANIC, SentimentLevel.PANIC):
            pos_hint = f"对持仓（{names}）：优先守止损，禁止恐慌补仓。"
        elif level in (SentimentLevel.EXTREME_GREED, SentimentLevel.GREED):
            pos_hint = f"对持仓（{names}）：警惕追高，可评估止盈/上移止损。"
        else:
            pos_hint = f"持仓关注：{names}"

    lines = [
        f"【情绪警报·{zh}】",
        f"评分约 {s.score}/100（0 恐慌 ←→ 100 贪婪）",
    ]
    if s.summary and "未获取" not in s.summary:
        lines.append(f"概览：{s.summary[:100]}")
    if reasons:
        lines.append("触发：")
        for r in reasons[:5]:
            rr = str(r)
            if "炸板" in rr and "（" not in rr:
                rr = rr + "（炸板=涨停后又打开）"
            lines.append(f"· {rr}")
    if pos_hint:
        lines.append(pos_hint)
    if s.panic_arb_advice and level in (
        SentimentLevel.EXTREME_PANIC,
        SentimentLevel.PANIC,
    ):
        lines.append(f"备注：{s.panic_arb_advice[:80]}")
    lines.append("说明：情绪只定环境，不替代个股止损纪律。")
    return "\n".join(lines)


# ── 包5：入场信号监控（自选股融资止跌回升 + 下影线缩量）───────────


def run_entry_signal_channel(cfg: ChannelConfig) -> str:
    """监控自选股入场信号：①融资余额止跌回升 ②日线下影线+缩量。"""
    stocks = _load_watchlist(cfg.watchlist_path)
    if not stocks:
        return ""

    # 只盯配置了 entry_signals 的标的
    monitored: list[dict] = []
    for s in stocks:
        es = s.get("entry_signals")
        if isinstance(es, dict) and es:
            monitored.append(s)

    if not monitored:
        return ""

    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")

    hits: list[str] = []
    for s in monitored:
        sym = str(s.get("symbol") or "")
        name = str(s.get("name") or sym)
        es = s.get("entry_signals") or {}
        reasons: list[str] = []

        # ① 融资余额止跌回升
        if es.get("margin_reversal"):
            mr = _check_margin_reversal(sym, name)
            if mr:
                reasons.append(mr)

        # ② 日线下影线 + 缩量
        if es.get("hammer_volume_contract"):
            hv = _check_hammer_volume(sym, name, cfg)
            if hv:
                reasons.append(hv)

        if not reasons:
            continue

        ck = f"entry_signal:{sym}:{day}"
        if not cfg.force and store.is_cooling(ck, now):
            continue
        store.set_cooling(ck, cfg.cool_watchlist, now)

        quotes, _ = fetch_quotes([sym], names={sym: name})
        q = quotes.get(sym)
        price_str = f" @ {q.price:.2f}" if q and q.price > 0 else ""
        hits.append(
            f"{name}({sym}){price_str}\n" + "\n".join(f"  ✓ {r}" for r in reasons)
        )

    store.prune_cooling(now)
    store.save()

    if not hits:
        return ""

    body = "\n\n".join(hits)
    return (
        f"【入场信号监测】{day}\n\n{body}\n\n"
        "⚠️ 信号仅为条件触发，不构成买入建议。入场前请确认：\n"
        "① 管道完整诊断通过 ② 止损位已设定 ③ 仓位不超限"
    )


def _check_margin_reversal(sym: str, name: str) -> str | None:
    """检测融资余额是否从连续下降转为回升。返回人话描述或 None。"""
    try:
        from src.game_theory.margin import get_margin_analyzer

        ma = get_margin_analyzer()
        hist = ma.load_history(sym)
        if not hist or len(hist) < 5:
            return None

        # 取最近 5 个交易日的融资余额
        recent = hist[-5:]
        balances = [h.margin_balance for h in recent]
        dates = [h.date for h in recent]

        # 需要前 3-4 天中有 ≥2 天下降 AND 最新一天上升
        if len(balances) < 4:
            return None

        prev_diffs = [
            balances[i] - balances[i - 1] for i in range(1, len(balances) - 1)
        ]
        latest_diff = balances[-1] - balances[-2]

        # 条件：此前 ≥2 天连续下降 + 最新一天回升 > 0.3%
        down_count = sum(1 for d in prev_diffs if d < -0.01)  # 下降超 100 万
        if down_count >= 2 and latest_diff > 0.005:  # 回升超 500 万
            pct = (latest_diff / balances[-2]) * 100
            return (
                f"💰 融资余额止跌回升：连续下降后 {dates[-1]} 回升 {latest_diff:.2f}亿（+{pct:.2f}%）\n"
                f"   近5日：{' → '.join(f'{b:.1f}亿' for b in balances)}"
            )

        # 备用信号：余额在低位企稳（2 天不降）
        if down_count >= 2 and abs(latest_diff) <= 0.003:
            return (
                f"💰 融资余额初步企稳：{dates[-1]} 变化 {latest_diff:+.3f}亿（不再下降）\n"
                f"   近5日：{' → '.join(f'{b:.1f}亿' for b in balances)}"
            )

        return None
    except Exception:
        return None


def _check_hammer_volume(sym: str, name: str, cfg: ChannelConfig) -> str | None:
    """检测日线是否出现长下影线+缩量。返回人话描述或 None。"""
    try:
        from src.alphas.macd_kdj import load_kline_cache

        # 先尝试 cfg 缓存目录
        cache_dir = getattr(cfg, "kline_cache_dir", Path("data/kline_cache"))
        if isinstance(cache_dir, str):
            cache_dir = Path(cache_dir)
        df = load_kline_cache(sym, cache_dir)

        # 回退 Hermes 路径
        if df is None or len(df) < 5:
            alt = Path.home() / "ai-stock-hunter" / "data" / "kline_cache"
            if alt.exists():
                df = load_kline_cache(sym, alt)

        if df is None or len(df) < 5:
            return None

        # 取最近 5 根日线
        recent = df.tail(5)
        if len(recent) < 5:
            return None

        latest = recent.iloc[-1]
        o, h, l, c, v = (
            float(latest["open"]),
            float(latest["high"]),
            float(latest["low"]),
            float(latest["close"]),
            float(latest["volume"]),
        )

        # 计算下影线和上影线
        body_bottom = min(o, c)
        body_top = max(o, c)
        lower_shadow = body_bottom - l
        upper_shadow = h - body_top
        body = abs(c - o)
        real_body = max(body, 0.001)  # 避免除零

        # 条件1：下影线显著长（≥ 2× 上影线 OR ≥ 1.5× 实体）
        hammer_ok = (lower_shadow >= 2.0 * max(upper_shadow, 0.001)) or (
            lower_shadow >= 1.5 * real_body
        )

        # 条件2：缩量（成交量 < 近5日均量的 60%）
        avg_vol = float(recent.iloc[:-1]["volume"].mean())
        vol_contract = v < avg_vol * 0.6

        if not (hammer_ok and vol_contract):
            return None

        vol_pct = (v / avg_vol) * 100 if avg_vol > 0 else 100
        lower_pct = (lower_shadow / real_body * 100) if real_body > 0 else 0
        return (
            f"📊 下影线+缩量：下影线/实体={lower_pct:.0f}% "
            f"| 量能={vol_pct:.0f}%（仅为近5日均量{vol_pct:.0f}%）\n"
            f"   O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} "
            f"| 下影={lower_shadow:.2f} 实体={body:.2f}"
        )

    except Exception:
        return None


# ── 包6：产业链监控组（核心标的+下游+设备商联动扫描）───────────

DEFAULT_MONITOR_GROUPS = Path("data/monitoring_groups.json")


def _load_monitor_groups(path: Path) -> list[dict]:
    """加载监控组配置。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("groups") or [])
    except (OSError, json.JSONDecodeError):
        return []


def run_monitor_group_channel(
    cfg: ChannelConfig,
    group_id: str | None = None,
) -> str:
    """产业链监控组：扫描核心标的入场/α验证信号 + 下游/设备商异动。

    输出格式为人话卡片，适合 Hermes → 微信推送。
    空字符串 = 静默（无变化或冷却中）。
    """
    groups = _load_monitor_groups(DEFAULT_MONITOR_GROUPS)
    if not groups:
        return ""

    # 选组：指定 group_id 或取第一个
    if group_id:
        groups = [g for g in groups if g.get("id") == group_id]
    if not groups:
        return ""

    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")

    all_sections: list[str] = []

    for group in groups:
        sections: list[str] = []
        group_name = group.get("name", "监控组")
        core = group.get("core") or {}
        core_sym = str(core.get("symbol") or "")
        core_name = str(core.get("name") or core_sym)

        # ── 1. 核心标的入场信号 ──
        entry_hits = _check_core_entry_signals(core, cfg, store, now, day)
        if entry_hits:
            sections.append(f"🎯 {core_name}({core_sym}) 入场信号：\n" + entry_hits)

        # ── 2. 核心标的 α 验证信号（手动跟踪项提醒） ──
        alpha_reminders = _check_alpha_verification(core, store, now, day)
        if alpha_reminders:
            sections.append(f"🔬 {core_name} α验证提醒：\n" + alpha_reminders)

        # ── 3. 下游客户异动 ──
        downstream = group.get("downstream") or []
        ds_hits = _check_downstream_moves(downstream, core_name, store, now, day)
        if ds_hits:
            sections.append("📈 下游客户异动：\n" + ds_hits)

        # ── 4. 设备商风险指标 ──
        equip = group.get("equipment_risk") or []
        eq_hits = _check_equipment_risk(equip, core_name, store, now, day)
        if eq_hits:
            sections.append("⚠️ 设备商风险信号：\n" + eq_hits)

        if not sections:
            continue

        header = f"【{group_name}】{day}"
        all_sections.append(header + "\n\n" + "\n\n".join(sections))

    if not all_sections:
        return ""

    # 冷却：同一天同组只推送一次（除非 force）
    for group in groups:
        gid = group.get("id", "unknown")
        cool_key = f"monitor_group:{gid}:{day}"
        if not cfg.force and store.is_cooling(cool_key, now):
            return ""
        store.set_cooling(cool_key, cfg.cool_watchlist, now)

    store.prune_cooling(now)
    store.save()

    body = "\n\n---\n\n".join(all_sections)
    return (
        body
        + "\n\n💡 信号说明：入场信号=技术面/资金面触发；α验证=基本面里程碑；"
        "下游异动=需求端先行指标；设备商=供给端风险。"
        "\n⚠️ 信号仅作参考，不构成买卖建议。入场前请确认管道诊断通过+止损已设。"
    )


def _check_core_entry_signals(
    core: dict,
    cfg: ChannelConfig,
    store: SentinelStateStore,
    now: float,
    day: str,
) -> str:
    """复用现有入场信号检测逻辑，为监控组核心标的生成摘要。"""
    sym = str(core.get("symbol") or "")
    name = str(core.get("name") or sym)
    alpha_signals = core.get("alpha_signals") or []
    sig_map = {s.get("id"): s for s in alpha_signals}

    reasons: list[str] = []

    # 融资余额止跌回升
    if sig_map.get("margin_reversal", {}).get("trigger"):
        mr = _check_margin_reversal(sym, name)
        if mr:
            reasons.append(mr)

    # 下影线+缩量
    if sig_map.get("hammer_volume_contract", {}).get("trigger"):
        hv = _check_hammer_volume(sym, name, cfg)
        if hv:
            reasons.append(hv)

    if not reasons:
        return ""

    quotes, _ = fetch_quotes([sym], names={sym: name})
    q = quotes.get(sym)
    price_str = f" @ {q.price:.2f}" if q and q.price > 0 else ""
    return f"{name}({sym}){price_str}\n" + "\n".join(f"  ✓ {r}" for r in reasons)


def _check_alpha_verification(
    core: dict,
    store: SentinelStateStore,
    now: float,
    day: str,
) -> str:
    """α验证信号提醒：Q布产量里程碑 / Low-CTE独占性。

    这些是事件驱动信号，无法自动从行情数据检测。
    此处生成定期提醒，敦促人工核查。
    """
    sym = str(core.get("symbol") or "")
    name = str(core.get("name") or sym)
    alpha_signals = core.get("alpha_signals") or []
    sig_map = {s.get("id"): s for s in alpha_signals}

    lines: list[str] = []

    # Q布产量追踪
    q_sig = sig_map.get("q_cloth_output")
    if q_sig:
        ck = f"alpha:q_cloth:{sym}:{day}"
        if not store.is_cooling(ck, now):
            lines.append(
                f"📐 Q布产量：{q_sig.get('description', '')}\n"
                f"   核查方式：{q_sig.get('check_method', '公司公告/调研纪要')}"
            )
            store.set_cooling(ck, 24 * 60, now)  # 每日最多提醒一次

    # Low-CTE独占性
    ct_sig = sig_map.get("low_cte_status")
    if ct_sig:
        ck = f"alpha:low_cte:{sym}:{day}"
        if not store.is_cooling(ck, now):
            lines.append(
                f"🔒 Low-CTE布：{ct_sig.get('description', '')}\n"
                f"   核查方式：{ct_sig.get('check_method', '竞对公告/英伟达认证名单')}"
            )
            store.set_cooling(ck, 24 * 60, now)

    if not lines:
        return ""

    return "\n".join(lines)


def _check_downstream_moves(
    downstream: list[dict],
    core_name: str,
    store: SentinelStateStore,
    now: float,
    day: str,
) -> str:
    """扫描下游客户股价异动（±5%），作为需求端先行指标。"""
    if not downstream:
        return ""

    symbols = [str(d["symbol"]) for d in downstream]
    names = {str(d["symbol"]): str(d.get("name") or "") for d in downstream}
    role_map = {str(d["symbol"]): str(d.get("role") or "") for d in downstream}
    impact_map = {}
    for d in downstream:
        for sig in d.get("monitor_signals") or []:
            impact_map.setdefault(str(d["symbol"]), {})[sig.get("id")] = sig.get(
                "impact_on_core", ""
            )

    quotes, _ = fetch_quotes(symbols, names=names)
    hits: list[str] = []

    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            continue
        chg = q.change_pct or 0
        nm = names.get(sym, sym)
        role = role_map.get(sym, "")
        if abs(chg) >= 5:
            direction = "↑" if chg > 0 else "↓"
            hits.append(
                f"{direction} {nm}({sym}) {chg:+.1f}% | {role}\n"
                f"   对{core_name}影响：{'需求旺盛→利好' if chg > 0 else '需求走弱→警惕'}"
            )
        # 跌超3%也提示
        elif chg <= -3:
            hits.append(
                f"🔻 {nm}({sym}) {chg:+.1f}% | {role}\n"
                f"   关注是否趋势性走弱"
            )

    if not hits:
        return ""

    return "\n".join(hits)


def _check_equipment_risk(
    equipment: list[dict],
    core_name: str,
    store: SentinelStateStore,
    now: float,
    day: str,
) -> str:
    """扫描设备商股价异动（大涨=市场预期技术突破/批量订单）。"""
    if not equipment:
        return ""

    symbols = [str(d["symbol"]) for d in equipment]
    names = {str(d["symbol"]): str(d.get("name") or "") for d in equipment}
    role_map = {str(d["symbol"]): str(d.get("role") or "") for d in equipment}

    quotes, _ = fetch_quotes(symbols, names=names)
    hits: list[str] = []

    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            continue
        chg = q.change_pct or 0
        nm = names.get(sym, sym)
        role = role_map.get(sym, "")
        # 设备商大涨=市场可能在定价技术突破→对中材是风险信号
        if chg >= 5:
            hits.append(
                f"🔴 {nm}({sym}) {chg:+.1f}% | {role}\n"
                f"   设备商大涨→市场可能在定价技术突破→{core_name}供给瓶颈逻辑承压"
            )

    if not hits:
        return ""

    return "\n".join(hits)


# ── 包7：突发资讯推送（监控组标的+行业关键词）─────────────────────

# 监控组关联的行业关键词（用于从7×24快讯中过滤相关资讯）
_NEWS_INDUSTRY_KEYWORDS = [
    # 电子布 / 玻纤
    "电子布", "玻纤布", "玻璃纤维", "低介电", "Low-Dk", "Low-CTE", "Q布", "石英布",
    "电子纱", "覆铜板", "CCL", "M9", "M8", "M10",
    # PCB / 载板
    "PCB", "正交背板", "mSAP", "FC-BGA", "ABF", "IC载板", "封装基板",
    "高多层板", "HDI",
    # AI 算力 / 英伟达
    "Rubin", "英伟达", "NVIDIA", "GPU", "AI服务器", "算力", "HBM",
    "CoWoS", "先进封装",
    # 设备
    "织布机", "喷气织机", "织机", "丰田",
    # 竞对 / 行业事件
    "日东纺", "台耀", "生益科技", "胜宏科技", "沪电股份", "深南电路",
    "宏和科技", "中国巨石", "国际复材", "中材科技", "菲利华",
    "卓郎智能", "泰坦股份",
    # 供需信号（注意：通用词"突破"仅在高优先级触发中使用，此处放更具体的信号词）
    "涨价", "提价", "缺货", "停产", "扩产", "验证通过", "通过认证",
]

# 高优先级标题关键词（命中即为 P0，必须推送）
_NEWS_HIGH_PRIORITY = [
    "扩产", "涨价", "提价", "突破", "认证通过", "首次", "独家",
    "停产", "减产", "缺货", "供不应求", "订单排", "加单",
    "减持", "增持", "回购",
    "跌停", "涨停",
    "量产", "交付",
    "英伟达", "Rubin",
]


def _build_news_monitor_symbols() -> list[dict]:
    """从监控组配置中提取需要关注资讯的标的列表。"""
    groups = _load_monitor_groups(DEFAULT_MONITOR_GROUPS)
    symbols: list[dict] = []
    seen: set[str] = set()
    for g in groups:
        core = g.get("core") or {}
        cs = str(core.get("symbol") or "")
        cn = str(core.get("name") or "")
        if cs and cs not in seen:
            symbols.append({"symbol": cs, "name": cn, "role": "核心标的"})
            seen.add(cs)
        for ds in g.get("downstream") or []:
            dsym = str(ds.get("symbol") or "")
            if dsym and dsym not in seen:
                symbols.append({
                    "symbol": dsym,
                    "name": str(ds.get("name") or ""),
                    "role": str(ds.get("role") or "下游"),
                })
                seen.add(dsym)
        for eq in g.get("equipment_risk") or []:
            esym = str(eq.get("symbol") or "")
            if esym and esym not in seen:
                symbols.append({
                    "symbol": esym,
                    "name": str(eq.get("name") or ""),
                    "role": str(eq.get("role") or "设备商"),
                })
                seen.add(esym)
    return symbols


def _news_title_hash(title: str) -> str:
    """生成新闻标题的短哈希，用于去重冷却。"""
    import hashlib
    return hashlib.md5(title.strip().encode("utf-8")).hexdigest()[:12]


def _is_news_fresh(time_str: str, max_days: int = 7) -> bool:
    """判断新闻时间是否在 max_days 内。无法解析的返回 True（保留）。"""
    if not time_str or not time_str.strip():
        return True
    import re
    from datetime import timedelta
    # 常见格式: "2026-07-20 15:43:34" 或 "2026-07-20"
    match = re.search(r"(\d{4}-\d{2}-\d{2})", time_str)
    if not match:
        return True  # 无法解析，保留
    try:
        news_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=BEIJING)
        cutoff = _now_bj() - timedelta(days=max_days)
        return news_date >= cutoff
    except ValueError:
        return True


def run_news_flash_channel(cfg: ChannelConfig) -> str:
    """突发资讯频道：扫描监控组标的+行业关键词的最新资讯。

    数据源：东财7×24快讯（零鉴权）+ 东财个股新闻搜索。
    过滤：命中监控组标的名称/代码或行业关键词。
    优先级：高优先级关键词 → P0 即时推送；常规 → 汇总推送。
    """
    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")
    now_str = _now_bj().strftime("%H:%M")

    # ── 加载监控标的 ──
    monitored = _build_news_monitor_symbols()
    if not monitored:
        return ""

    # 构建标的查找表
    sym_to_info: dict[str, dict] = {}
    all_names: set[str] = set()
    for m in monitored:
        sym_to_info[m["symbol"]] = m
        all_names.add(m["name"])
        all_names.add(m["symbol"])
        # 也加入简称（如 "中材"、"胜宏"、"生益"）
        name = m["name"]
        if len(name) >= 2:
            all_names.add(name[:2])

    # ── 1. 东财 7×24 全球快讯 ──
    p0_items: list[dict] = []  # 高优先级
    p1_items: list[dict] = []  # 常规

    try:
        from src.data.eastmoney_fallback import fetch_em_global_news

        flash_news = fetch_em_global_news(page_size=60)
        for entry in flash_news:
            title = str(entry.get("title") or "")
            summary = str(entry.get("summary") or "")
            text = title + " " + summary

            # 关键词匹配
            matched_names = [kw for kw in all_names if kw in text]
            matched_industry = [kw for kw in _NEWS_INDUSTRY_KEYWORDS if kw in text]
            if not matched_names and not matched_industry:
                continue

            # 去重冷却（同一条新闻一天只推一次）
            tid = _news_title_hash(title)
            ck = f"news:{tid}:{day}"
            if not cfg.force and store.is_cooling(ck, now):
                continue

            # 快讯当日有效
            if not _is_news_fresh(entry.get("time", ""), max_days=1):
                continue

            store.set_cooling(ck, cfg.cool_watchlist, now)

            is_high = (
                matched_names
                and any(kw in text for kw in _NEWS_HIGH_PRIORITY)
            )

            item = {
                "title": title,
                "time": entry.get("time", now_str),
                "source": "东财快讯",
                "matched": list(set(matched_names + matched_industry[:3])),
                "is_high": is_high,
            }
            if is_high:
                p0_items.append(item)
            else:
                p1_items.append(item)
    except Exception as e:
        logger.debug("7×24快讯获取失败: %s", e)

    # ── 2. 个股新闻搜索（核心标的+重点下游） ──
    try:
        from src.data.eastmoney_fallback import fetch_em_stock_news

        for m in monitored[:5]:  # 限制数量避免请求过多
            sym = m["symbol"]
            name = m["name"]
            try:
                news_list = fetch_em_stock_news(sym, max_results=5)
                for entry in news_list:
                    title = str(entry.get("title") or "")
                    tid = _news_title_hash(title)
                    ck = f"news:{tid}:{day}"
                    if not cfg.force and store.is_cooling(ck, now):
                        continue

                    # 个股新闻 3 日内有效
                    if not _is_news_fresh(entry.get("time", ""), max_days=3):
                        continue

                    store.set_cooling(ck, cfg.cool_watchlist, now)

                    is_high = any(kw in title for kw in _NEWS_HIGH_PRIORITY)
                    item = {
                        "title": title,
                        "time": entry.get("time", now_str),
                        "source": f"{name}({sym})",
                        "matched": [name],
                        "is_high": is_high,
                    }
                    if is_high:
                        p0_items.append(item)
                    else:
                        p1_items.append(item)
            except Exception:
                continue
    except Exception as e:
        logger.debug("个股新闻获取失败: %s", e)

    store.prune_cooling(now)
    store.save()

    if not p0_items and not p1_items:
        return ""

    # ── 格式化输出 ──
    lines = [f"【突发资讯监测】{day} {now_str}"]
    total = len(p0_items) + len(p1_items)

    if p0_items:
        lines.append(f"\n🔴 高优先级（{len(p0_items)}条）：")
        for item in p0_items[:8]:
            tags = "、".join(item["matched"][:3])
            lines.append(f"· {item['title']}")
            lines.append(f"  [{item['source']} | {item['time']} | 关联：{tags}]")

    if p1_items:
        lines.append(f"\n🟡 常规关注（{len(p1_items)}条）：")
        for item in p1_items[:5]:
            tags = "、".join(item["matched"][:2])
            lines.append(f"· {item['title']}")
            lines.append(f"  [{item['source']} | {item['time']} | {tags}]")

    lines.append(f"\n📊 本次扫描共 {total} 条相关资讯")
    lines.append("💡 资讯仅作信号参考，不构成买卖建议。")
    return "\n".join(lines)


# ── 包8：股吧情绪异动（热度飙升 / 多空极端 / 帖量暴增）───────────


def run_guba_hotspot_channel(cfg: ChannelConfig) -> str:
    """股吧情绪异动监测：检测自选+持仓标的热度飙升/多空极端/帖量暴增。

    空字符串 = 静默（无异常或冷却中）。
    """
    store = SentinelStateStore(cfg.state_path)
    now = _now_bj().timestamp()
    day = _now_bj().strftime("%Y-%m-%d")

    # 收集标的：自选 + 持仓
    watch_stocks = {s.get("symbol"): s.get("name") or s.get("symbol")
                    for s in _load_watchlist(cfg.watchlist_path)}
    for sym, name in _load_position_symbols(cfg.positions_path):
        if sym not in watch_stocks:
            watch_stocks[sym] = name
    if not watch_stocks:
        return ""

    symbols = list(watch_stocks.keys())

    try:
        from src.data.guba_provider import GubaProvider
        provider = GubaProvider()
        results = provider.fetch_sentiments_batch(symbols, max_workers=6)
    except Exception as e:
        logger.debug("guba hotspot fetch failed: %s", e)
        return ""

    # ── 异动检测 ──
    alerts: list[dict] = []
    for sym, sentiment in results.items():
        if sentiment is None:
            continue
        name = watch_stocks.get(sym, sym)
        signals: list[str] = []
        severity = "low"

        # 热度飙升：heat_score >= 75
        if sentiment.heat_score >= 75:
            signals.append(f"🔥热度飙升 heat={sentiment.heat_score}")
            severity = "high"

        # 帖量暴增：24h 帖量 >= 60
        if sentiment.posts_last_24h >= 60:
            signals.append(f"📈帖量暴增 24h={sentiment.posts_last_24h}帖")
            if severity != "high":
                severity = "mid"

        # 多空极端：多空比 >= 2.0 or <= 0.5
        ratio = sentiment.bull_bear_ratio
        if ratio is not None:
            if ratio >= 2.0:
                signals.append(f"🐂 极端看多 多空比={ratio:.1f}")
                severity = "high"
            elif ratio <= 0.5:
                signals.append(f"🐻 极端看空 多空比={ratio:.1f}")
                severity = "high"

        # 互动暴增：帖均互动 >= 8000
        if sentiment.engagement_per_post >= 8000:
            signals.append(f"💬帖均互动={sentiment.engagement_per_post:.0f}")
            if severity == "low":
                severity = "mid"

        if not signals:
            continue

        alerts.append({
            "symbol": sym,
            "name": name,
            "severity": severity,
            "signals": signals,
            "heat_score": sentiment.heat_score,
            "hot_titles": sentiment.hot_titles[:3],
            "post_count": sentiment.post_count,
            "posts_last_hour": sentiment.posts_last_hour,
            "bullish": sentiment.bullish_count,
            "bearish": sentiment.bearish_count,
        })

    if not alerts:
        return ""

    # ── 冷却 ──
    cool_key = f"guba:{day}"
    if not cfg.force and store.is_cooling(cool_key, now):
        return ""
    store.set_cooling(cool_key, cfg.cool_sentiment, now)
    store.prune_cooling(now)
    store.save()

    # ── 按严重度排序 ──
    sev_order = {"high": 0, "mid": 1, "low": 2}
    alerts.sort(key=lambda a: (sev_order.get(a["severity"], 9), -a["heat_score"]))

    # ── 格式化人话卡片 ──
    high_alerts = [a for a in alerts if a["severity"] == "high"]
    mid_alerts = [a for a in alerts if a["severity"] == "mid"]
    low_alerts = [a for a in alerts if a["severity"] == "low"]

    lines = [f"【股吧情绪异动】{day}"]

    if high_alerts:
        lines.append(f"\n🔴 高优先级（{len(high_alerts)}只）：")
        for a in high_alerts:
            lines.append(f"· {a['name']}({a['symbol']})")
            for sig in a["signals"]:
                lines.append(f"  {sig}")
            hot_preview = " / ".join(
                t[:30] for t in a["hot_titles"][:2]
            )
            if hot_preview:
                lines.append(f"  热议: {hot_preview}")

    if mid_alerts:
        lines.append(f"\n🟡 关注（{len(mid_alerts)}只）：")
        for a in mid_alerts:
            lines.append(f"· {a['name']}({a['symbol']}) {' '.join(a['signals'])}")

    if low_alerts:
        lines.append(f"\n🟢 轻度异动（{len(low_alerts)}只）：")
        for a in low_alerts:
            lines.append(f"· {a['name']}({a['symbol']}) {a['signals'][0]}")

    lines.append("\n💡 股吧情绪仅作市场热度参考，不构成买卖建议。")
    return "\n".join(lines)


# ── 统一入口 ─────────────────────────────────────────────────────


def run_channel(mode: str, cfg: ChannelConfig) -> str:
    """
    mode:
      alert|position — 持仓告警+背景（包1）
      margin — 两融
      watchlist — 自选扫雷
      funds — 两融+自选（包2）
      open — 开盘前简报（包3）
      close — 收盘简报（包3）
      sentiment — 情绪极端（包4）
      entry_signal — 入场信号监测（包5）
      monitor_group — 产业链监控组（包6）
      news_flash — 突发资讯推送（包7）
      guba — 股吧情绪异动（包8）
      auto — 按时段选择（见下）
    """
    mode = (mode or "alert").strip().lower()
    if mode == "auto":
        mode = _auto_mode(cfg)

    if mode in ("alert", "position", "intraday"):
        return run_position_channel(cfg)
    if mode == "margin":
        return run_margin_channel(cfg)
    if mode in ("watchlist", "sweep"):
        return run_watchlist_channel(cfg)
    if mode in ("funds", "fund", "package2"):
        return run_funds_and_watchlist(cfg)
    if mode in ("open", "preopen", "briefing_open"):
        return run_briefing(cfg, "open")
    if mode in ("close", "postclose", "briefing_close"):
        return run_briefing(cfg, "close")
    if mode in ("sentiment", "extreme"):
        return run_sentiment_extreme(cfg)
    if mode in ("entry_signal", "entry", "signal"):
        return run_entry_signal_channel(cfg)
    if mode in ("monitor_group", "group", "monitor", "mg"):
        return run_monitor_group_channel(cfg)
    if mode in ("news_flash", "news", "flash", "breaking"):
        return run_news_flash_channel(cfg)
    if mode in ("guba", "guba_hotspot", "guba_heat"):
        return run_guba_hotspot_channel(cfg)
    # 未知 → 持仓
    return run_position_channel(cfg)


def _auto_mode(cfg: ChannelConfig) -> str:
    """根据北京时间猜频道（方便单 cron 调试；生产建议分 job）。"""
    now = _now_bj()
    t = now.hour * 100 + now.minute
    # 开盘前简报窗
    if 900 <= t <= 925:
        return "open"
    # 收盘后
    if 1505 <= t <= 1530:
        return "close"
    # 盘中
    if is_trading_time(now) or cfg.force:
        # 整点附近附带 funds 可由独立 cron；auto 仍以持仓为主
        return "alert"
    return "alert"
