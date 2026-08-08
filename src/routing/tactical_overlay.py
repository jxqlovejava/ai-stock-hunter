# -*- coding: utf-8 -*-
"""P1-8 短线战术叠加 — 把 5 项文章共识信号注入全链路决策 (diagnose/analyze/paper-trade)。

tactics 管道已完整使用这些信号；本模块让它们在 orchestrator.run 全链路里也生效，
使模拟交易 / diagnose 的买入卖出决策吃到同一批短线战法信号：
  - F1 涨停次日低开位置解读 (r044)      高位=出货预警/底部=吸筹观察
  - F3 突破三分类强度 (r045)            弱势突破不追 / 强势可进
  - F5 急涨缓跌/急跌缓涨形态           洗盘偏多 / 出货偏空
  - F2 封板时点 + 尾盘跳水/急拉         弱封次日易低开 / 尾盘异动次日反向
  - F4 高管增减持                       净增持加分 / 净减持红旗

输出: {
  "doctrine_flags": {limit_up_next_day_gap_down, breakout_weak, ...},
  "score_delta": int,      # 应用到 verdict.score (0-100)
  "signals": [ {"name", "impact", "note"} ],
  "note": str,
}
纯函数 + 全 try/except 静默降级：任一信号数据缺失/失败不阻断主流程。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def compute_tactical_overlay(
    symbol: str,
    daily_df=None,
    minute_bars=None,
    executive_trades=None,
) -> dict:
    """计算战术叠加 — 聚合 5 项共识信号。

    Args:
        symbol: 股票代码
        daily_df: 日线 DataFrame (需 open/high/low/close/volume, 与 tactics 一致)
        minute_bars: 当日分钟线 Bar 列表 (可选, 缺失则 F2 跳过)
        executive_trades: aggregator.get_executive_trades 输出 (可选, 缺失则 F4 跳过)

    Returns: {"doctrine_flags", "score_delta", "signals", "note"}
    """
    out = {"doctrine_flags": {}, "score_delta": 0, "signals": [], "note": ""}
    parts: list[str] = []
    prev_close = _prev_close(daily_df)

    # ── F1 涨停次日低开 (r044) ──
    _apply_f1_limit_up_next_day(out, symbol, daily_df, parts)

    # ── F3 突破三分类强度 (r045) ──
    _apply_f3_breakout_strength(out, symbol, daily_df, parts)

    # ── F5 急涨缓跌/急跌缓涨形态 ──
    _apply_f5_rush_slump(out, symbol, daily_df, parts)

    # ── F2 封板时点 + 尾盘 ──
    _apply_f2_seal_tail(out, symbol, minute_bars, prev_close, parts)

    # ── F4 高管增减持 ──
    _apply_f4_insider(out, executive_trades, parts)

    out["score_delta"] = max(-30, min(30, out["score_delta"]))
    out["note"] = "; ".join(parts)
    return out


def _prev_close(daily_df) -> float:
    if daily_df is None or getattr(daily_df, "empty", True):
        return 0.0
    try:
        closes = daily_df["close"].astype(float)
        return float(closes.iloc[-2]) if len(closes) >= 2 else 0.0
    except Exception:
        return 0.0


def _build_panel(daily_df, symbol: str):
    """从日线 DataFrame 构造单列宽面板 (close/high/volume) — 与 tactics/_inject 一致。"""
    import pandas as pd
    if daily_df is None or getattr(daily_df, "empty", True):
        return None
    try:
        c = pd.DataFrame({symbol: daily_df["close"].astype(float).values}, index=daily_df.index)
        h = pd.DataFrame({symbol: daily_df["high"].astype(float).values}, index=daily_df.index)
        v = pd.DataFrame({symbol: daily_df["volume"].astype(float).values}, index=daily_df.index)
        return c, h, v
    except Exception:
        return None


def _apply_f1_limit_up_next_day(out, symbol, daily_df, parts) -> None:
    """F1 涨停次日低开: 高位=出货(-10) / 底部=吸筹(+5); gap_down 注入 r044。"""
    try:
        from src.routing.tactics import _limit_up_next_day_signal
        lud = _limit_up_next_day_signal(daily_df, symbol)
        if not lud.get("prev_limit_up"):
            return
        if lud.get("gap_direction") == "down":
            out["doctrine_flags"]["limit_up_next_day_gap_down"] = True
        sig = lud.get("signal", "")
        if sig == "distribute_warning":
            out["score_delta"] -= 10
            out["signals"].append({"name": "涨停次日出货预警", "impact": -10, "note": lud.get("note", "")})
        elif sig == "accumulate_watch":
            out["score_delta"] += 5
            out["signals"].append({"name": "底部涨停次日低开", "impact": 5, "note": lud.get("note", "")})
        if lud.get("note"):
            parts.append(f"涨停次日: {lud['note']}")
    except Exception as e:
        logger.debug("overlay F1: %s", e)


def _apply_f3_breakout_strength(out, symbol, daily_df, parts) -> None:
    """F3 突破三分类: WEAK 不追(-5, 注入 r045) / STRONG(+3)。"""
    panel = _build_panel(daily_df, symbol)
    if panel is None:
        return
    try:
        from src.routing.entry_exit_engine import EntryExitEngine
        sig = EntryExitEngine()._detect_breakout(panel[0], panel[1], panel[2])
        if sig is None or sig.type != "BREAKOUT":
            return
        if sig.strength == "WEAK":
            out["doctrine_flags"]["breakout_weak"] = True
            out["score_delta"] -= 5
            out["signals"].append({"name": "弱势突破", "impact": -5, "note": "突破量能勉强/幅度不足, 假突破概率高, 不追"})
            parts.append("突破: 弱势不追")
        elif sig.strength == "STRONG":
            out["score_delta"] += 3
            out["signals"].append({"name": "强势突破", "impact": 3, "note": "大实体+显著放量, 突破质量高"})
            parts.append("突破: 强势")
    except Exception as e:
        logger.debug("overlay F3: %s", e)


def _apply_f5_rush_slump(out, symbol, daily_df, parts) -> None:
    """F5 急涨缓跌/急跌缓涨: 洗盘(≥70, +3) / 出货(≤30, -5)。"""
    panel = _build_panel(daily_df, symbol)
    if panel is None:
        return
    try:
        from src.factors.zoo.ashare.technical.rush_slump_shape import compute as rs_compute
        frame = rs_compute({"close": panel[0]})
        score = float(frame.iloc[-1, 0])
        if score >= 70:
            out["score_delta"] += 3
            out["signals"].append({"name": "急跌缓涨(洗盘)", "impact": 3, "note": "洗盘特征, 偏多"})
            parts.append("量价: 洗盘")
        elif score <= 30:
            out["score_delta"] -= 5
            out["signals"].append({"name": "急涨缓跌(出货)", "impact": -5, "note": "出货特征, 偏空"})
            parts.append("量价: 出货")
    except Exception as e:
        logger.debug("overlay F5: %s", e)


def _apply_f2_seal_tail(out, symbol, minute_bars, prev_close, parts) -> None:
    """F2 封板时点 + 尾盘: 弱封次日易低开(-5) / 强封(+3); 尾盘跳水次日高开(+3) / 急拉诱多(-3)。"""
    if not minute_bars or prev_close <= 0:
        return
    try:
        from src.routing.tactics import _seal_time_signal, _tail_market_signal
        seal = _seal_time_signal(minute_bars, prev_close, symbol)
        if seal.get("sealed"):
            label = seal.get("seal_label", "")
            if label == "weak":
                out["score_delta"] -= 5
                out["signals"].append({"name": "弱势封板", "impact": -5, "note": seal.get("note", "")})
                parts.append(f"封板: {seal.get('note', '')}")
            elif label == "strong":
                out["score_delta"] += 3
                out["signals"].append({"name": "强势封板", "impact": 3, "note": seal.get("note", "")})
                parts.append(f"封板: {seal.get('note', '')}")
        tail = _tail_market_signal(minute_bars)
        event = tail.get("event", "")
        if event == "dump":
            out["score_delta"] += 3
            out["signals"].append({"name": "尾盘跳水", "impact": 3, "note": tail.get("note", "")})
            parts.append(f"尾盘: {tail.get('note', '')}")
        elif event == "pump":
            out["score_delta"] -= 3
            out["signals"].append({"name": "尾盘急拉诱多", "impact": -3, "note": tail.get("note", "")})
            parts.append(f"尾盘: {tail.get('note', '')}")
    except Exception as e:
        logger.debug("overlay F2: %s", e)


def _apply_f4_insider(out, executive_trades, parts) -> None:
    """F4 高管增减持: 净增持(+3) / 净减持(-3)。"""
    if not executive_trades:
        return
    try:
        from src.fundamental.insider import aggregate_insider_trades
        agg = aggregate_insider_trades(executive_trades)
        state = agg["recent_insider_trades"]
        if state == "buying":
            out["score_delta"] += 3
            out["signals"].append({"name": "高管净增持", "impact": 3, "note": agg.get("note", "")})
            parts.append(f"增减持: {agg.get('note', '')}")
        elif state == "selling":
            out["score_delta"] -= 3
            out["signals"].append({"name": "高管净减持", "impact": -3, "note": agg.get("note", "")})
            parts.append(f"增减持: {agg.get('note', '')}")
    except Exception as e:
        logger.debug("overlay F4: %s", e)
