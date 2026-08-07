# -*- coding: utf-8 -*-
"""短线战术管道 (Tactics Pipeline) — 4-Phase 架构。

聚焦买卖时机判断。按交易员思维模型组织:
  Phase 0: 数据预拉 (6路并行IO)
  Phase 1: 盘面全景 (TacticalSnapshot, 4维并行本地计算)
  Phase 2: 过筛+深思 (军规 → 辩论‖芒格‖T+0)
  Phase 3: 裁决+执行

与选股管道(diagnose/analyze)的本质区别:
  - 跳过: 准入/宏观象限/北向/盈利修正/Alpha Lens/多维诊断6维/
         反操纵深扫/质量审查/情景估值/行业公司深度
  - 保留: 军规/四大师辩论/芒格模型/综合裁决/仓位调度/风控执行
  - 新增: 技术6维全量/入场出场信号/融资融券/板块资金/市场情绪/博弈融合

预估耗时: 10-12s (瓶颈在LLM调用); --no-debate 可降至 2-3s
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.data.source_citation import make_citation

logger = logging.getLogger(__name__)

# perf 计数器 (仅 debug 模式)
_perf = __debug__


def _chanlun_score(points, position: str | None = None) -> float:
    """缠论独立维度评分（0-100）：买点加分/卖点减分 + 中枢位置微调。

    独立于技术 6 维 composite，供 tactics 报告展示与军规 ctx 参考。
    """
    score = 50.0
    for p in points:
        if p.kind in ("一买", "二买", "三买"):
            score = max(score, 55.0 + 15.0 * p.confidence)
        elif p.kind in ("一卖", "二卖", "三卖"):
            score = min(score, 45.0 - 10.0 * p.confidence)
    if position == "中枢下方":
        score -= 8.0
    elif position == "中枢上方":
        score += 6.0
    return round(max(0.0, min(100.0, score)), 1)


def _apply_chanlun_snapshot(snapshot: "TacticalSnapshot", chanlun_res) -> dict:
    """把缠论结果写入 snapshot：评分 + 买卖点信号 + 返回 doctrine_ctx 字段。

    M4 决策A：缠论为独立维度，不改技术 6 维 composite，仅并表信号。
    返回 dict 供 doctrine_ctx 注入（Task 13 军规消费）。
    """
    snapshot.chanlun_result = chanlun_res.to_summary_dict()
    cs = chanlun_res.current_state
    snapshot.chanlun_score = _chanlun_score(chanlun_res.points, cs.get("position"))
    for p in chanlun_res.points:
        if p.kind in ("一买", "二买", "三买"):
            snapshot.entry_signals.append({
                "type": f"CHANLUN_{p.kind}", "description": p.rationale,
                "zone_low": round(p.price * 0.99, 2),
                "zone_high": round(p.price * 1.01, 2),
                "confidence": p.confidence,
            })
        else:
            snapshot.exit_signals.append({
                "type": f"CHANLUN_{p.kind}", "description": p.rationale,
                "zone_low": round(p.price * 0.99, 2),
                "zone_high": round(p.price * 1.01, 2),
                "confidence": p.confidence, "urgency": "NORMAL",
            })
    last_kind = cs.get("last_point", {}).get("kind", "")
    return {
        "chanlun_sell_signal": "sell" if last_kind in ("一卖", "二卖", "三卖") else "",
        "chanlun_zs_break": cs.get("position") == "中枢下方",
        "chanlun_buy_confirmed": any(
            p.kind in ("一买", "二买", "三买") for p in chanlun_res.points),
        "chanlun_bihuang_down": any("底背驰" in p.rationale for p in chanlun_res.points),
    }


# ═══════════════════════════════════════════════════════════════════
# 市场状态前置判定 / 跨周期过滤 / MM等距投影 (P1-1/P1-5/P1-6)
# ═══════════════════════════════════════════════════════════════════

# 趋势跟随类信号：RANGE 态 / 周线方向相反时降权。
# 缠论买卖点信号(CHANLUN_*)、博弈/风控动作(REDUCE/CLOSE)不在此列 → 不受影响。
_TREND_FOLLOW_SIGNALS = frozenset({
    "MA_GOLDEN_CROSS", "BREAKOUT",
    "MA_BREAKDOWN",
})

# 均值回归类信号：周线 BEAR 时降权（防接飞刀）。PULLBACK_SUPPORT 曾属
# _TREND_FOLLOW_SIGNALS，2026-08 移入此处统一归为均值回归 —— RANGE 态不再降权
# （回踩支撑/超卖反弹在震荡市是合理均值回归策略），仅周线 BEAR 降权。
_MEAN_REVERSION_SIGNALS = frozenset({
    "PULLBACK_SUPPORT", "OVERSOLD_BOUNCE",
})

# 海龟启发 (P2): 已持仓浮盈 ≥ 2×ATR 允许金字塔加仓。
PYRAMID_ADD_ATR_MULT = 2.0

# P1-7 周线突破结构阈值（回测校准 2026-08-07）
_BREAKOUT_PLATFORM_W = 26        # 平台高点回看周数（半年）
_BREAKOUT_VOL_RATIO = 1.5        # 突破量能: 周量 > 1.5×前13周均量
_BREAKOUT_FRESH_W = 2            # 突破后 N 周内视为"刚突破"（抑制追入）
_PULLBACK_LOOKBACK_W = 52        # "近一年内有过突破"回看周数
_PULLBACK_TOUCH_BAND = 0.02      # 回踩触线带: 低点 ≤ MA10w×(1+2%)
_LOCK_RUN_UP = 0.20              # 锁利: 近60日累计涨幅阈值
_LOCK_WINDOW_D = 60              # 锁利: 涨幅回看窗口（交易日）


def _map_regime_to_state(regime_value: str) -> str:
    """MarketRegime 6 态 → 三态 (BULL_TRENDING/BEAR_TRENDING/RANGE)。

    RISK_ON/RISK_OFF 是「宽度/风险偏好」驱动、无 MA 趋势强度确认的弱信号,
    映射为 RANGE (保守降权) — 仅 BULL/BEAR_TRENDING 这类 MA 对齐+强度确认的
    趋势态才启用金叉/均线突破等趋势跟随信号。
    HIGH_VOL_CRISIS / LOW_VOL_DRIFT 同样 → RANGE。
    """
    if regime_value == "bull_trending":
        return "BULL_TRENDING"
    if regime_value == "bear_trending":
        return "BEAR_TRENDING"
    return "RANGE"  # risk_on / risk_off / low_vol_drift / high_vol_crisis / unknown


def _trend_chop_signal(
    prices: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Hurst + Choppiness 判定「趋势 vs 震荡」投票 (P1-1 第二票)。

    Returns:
        (h, choppiness, vote)  vote ∈ {BULL_TRENDING, BEAR_TRENDING, RANGE, None=弃权}
    方向由 MA5 vs MA20 给出; 仅当 H/CI 给出强信号才投票, 否则弃权。
    """
    h: Optional[float] = None
    chop: Optional[float] = None
    try:
        if prices and len(prices) >= 20:
            from src.indicators.structure import HurstExponent
            # max_window = 滑动窗口长度; 必须 ≤ 数据点数才会 ready
            hwin = max(20, min(len(prices), 128))
            hurst = HurstExponent(min_window=8, max_window=hwin)
            for p in prices:
                hurst.update(float(p))
            h = float(hurst.current_value) if hurst.current_value is not None else None
    except Exception:
        h = None
    try:
        if (prices and len(prices) >= 16 and highs and lows
                and len(highs) == len(prices) == len(lows)):
            from src.indicators.volatility import ChoppinessIndex
            ci = ChoppinessIndex(period=14)
            for i in range(len(prices)):
                o = float(prices[i - 1]) if i > 0 else float(prices[i])
                ci.update((o, float(highs[i]), float(lows[i]), float(prices[i])))
            chop = float(ci.current_value) if ci.current_value is not None else None
    except Exception:
        chop = None

    range_like = (h is not None and h < 0.45) or (chop is not None and chop > 61.8)
    trend_like = (h is not None and h > 0.55) and (chop is None or chop < 38.2)
    if trend_like:
        try:
            ma5 = sum(prices[-5:]) / 5.0
            ma20 = sum(prices[-20:]) / 20.0
            return h, chop, ("BULL_TRENDING" if ma5 > ma20 else "BEAR_TRENDING")
        except Exception:
            return h, chop, None
    if range_like:
        return h, chop, "RANGE"
    return h, chop, None


def _classify_market_state(
    index_closes: list[float] | None,
    index_highs: list[float] | None,
    index_lows: list[float] | None,
    breadth: Optional[float],
    stock_close_series: list[float],
    chanlun_summary: Optional[dict],
) -> dict:
    """P1-1 市场状态前置判定 — 三态 BULL_TRENDING / BEAR_TRENDING / RANGE。

    复用 RegimeClassifier 喂指数日线 (index_closes) → 三票:
      A. RegimeClassifier 6 态 → 三态
      B. Hurst + Choppiness 趋势/震荡 (方向由 MA5/MA20 给出)
      C. 缠论日线中枢方向 (position / zhongshu_state)
    指数数据缺失时降级用标的自身日线 (basis=stock)；两者皆缺 → RANGE。

    Returns:
        {state, confidence, regime, h, choppiness, zhongshu_state, basis, rationale}

    判定规则 (RegimeClassifier 为主锚, Hurst/Choppiness 与缠论为辅助票):
      - 主锚 BULL/BEAR_TRENDING → 保持, 仅当两个辅助票同时投 RANGE 才降级;
      - 主锚 RANGE → 保持 RANGE (保守降权), 仅当两个辅助票一致指向同一
        趋势方向才提升为趋势态;
      - 辅助票仅调整 confidence (同向加分, 矛盾减分), 避免单一噪声信号推翻趋势。
    """
    prices = index_closes if index_closes else (stock_close_series or None)
    basis = "index" if index_closes else ("stock" if stock_close_series else "none")

    rationale: list[str] = []
    regime = ""
    h = chop = None
    zs_state = ""
    pos = "未知"

    if not prices or len(prices) < 20:
        return {
            "state": "RANGE", "confidence": 0.3, "regime": "",
            "h": None, "choppiness": None, "zhongshu_state": "",
            "basis": basis, "rationale": ["[DATA_GAP] 日线不足20根 → 默认RANGE"],
        }

    # A. RegimeClassifier → 主锚
    anchor = "RANGE"
    try:
        from src.macro.market_regime import RegimeClassifier
        profile = RegimeClassifier().classify(
            prices=prices, highs=index_highs, lows=index_lows, breadth=breadth,
        )
        regime = profile.regime.value
        anchor = _map_regime_to_state(regime)
        rationale.append(f"Regime:{regime}→{anchor} (conf {profile.confidence:.2f})")
    except Exception as e:
        rationale.append(f"Regime不可用:{e}")

    # B. Hurst + Choppiness
    h, chop, hv = _trend_chop_signal(prices, index_highs, index_lows)
    if hv:
        rationale.append(f"Hurst={h} Choppiness={chop} → {hv}")

    # C. 缠论日线方向
    cv: Optional[str] = None
    if chanlun_summary:
        cs = chanlun_summary.get("current_state", {})
        zs_state = cs.get("zhongshu_state", "")
        pos = cs.get("position", "未知")
        if pos == "中枢上方" or zs_state == "上移":
            cv = "BULL_TRENDING"
        elif pos == "中枢下方" or zs_state == "下移":
            cv = "BEAR_TRENDING"
        elif pos == "中枢内" or zs_state in ("形成", "延伸"):
            cv = "RANGE"
        rationale.append(f"缠论:位置{pos} → {cv or '弃权'}")

    votes_bull = sum(1 for v in (hv, cv) if v == "BULL_TRENDING")
    votes_bear = sum(1 for v in (hv, cv) if v == "BEAR_TRENDING")
    votes_range = sum(1 for v in (hv, cv) if v == "RANGE")

    if anchor in ("BULL_TRENDING", "BEAR_TRENDING"):
        state = anchor
        if votes_range >= 2:
            state = "RANGE"
            rationale.append("两个辅助信号同时指向RANGE → 趋势存疑降级")
    else:
        if votes_bull >= 2 and votes_bear == 0:
            state = "BULL_TRENDING"
            rationale.append("辅助信号一致向上 → 自RANGE提升")
        elif votes_bear >= 2 and votes_bull == 0:
            state = "BEAR_TRENDING"
            rationale.append("辅助信号一致向下 → 自RANGE提升")
        else:
            state = "RANGE"

    agree = sum(1 for v in (hv, cv) if v == state)
    contradict = sum(1 for v in (hv, cv)
                     if v != state and v in ("RANGE", "BULL_TRENDING", "BEAR_TRENDING"))
    confidence = round(max(0.3, min(0.9, 0.4 + 0.2 * agree - 0.15 * contradict)), 2)

    return {
        "state": state, "confidence": confidence, "regime": regime,
        "h": h, "choppiness": chop, "zhongshu_state": zs_state,
        "basis": basis, "rationale": rationale,
    }


def _apply_market_state_gate(snapshot: "TacticalSnapshot", market_state: str) -> None:
    """P1-1 门控 — RANGE 态下趋势跟随信号降权(×0.5)并标注, 保留信号供展示。

    BULL/BEAR_TRENDING 态不改变任何信号。REDUCE/CLOSE 等风控类动作由
    _resolve_final_action / gt_advice 决定, 此处不动 → 不被破坏。
    """
    if market_state != "RANGE":
        return
    for sig in snapshot.entry_signals:
        if sig.get("type") in _TREND_FOLLOW_SIGNALS:
            sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
            sig["market_gate"] = "RANGE"
    for sig in snapshot.exit_signals:
        if sig.get("type") in _TREND_FOLLOW_SIGNALS:
            sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
            sig["market_gate"] = "RANGE"
    if snapshot.best_entry and snapshot.best_entry.get("type") in _TREND_FOLLOW_SIGNALS:
        snapshot.best_entry["confidence"] = round(
            float(snapshot.best_entry.get("confidence", 0.5)) * 0.5, 3)
        snapshot.best_entry["market_gate"] = "RANGE"
    snapshot.notes.append("[P1-1] RANGE 态: 金叉/均线突破等趋势信号已降权（均值回归信号不受 RANGE 门控）")


def _to_datetime_index(df) -> object:
    """把 RangeIndex + 日期列归一为 DatetimeIndex (与缠论 analyzer 同一约定)。"""
    import pandas as pd
    if df is None or isinstance(getattr(df, "index", None), pd.DatetimeIndex):
        return df
    for col in ("date", "datetime", "日期", "trade_date", "Date", "time"):
        if col in df.columns:
            try:
                parsed = pd.to_datetime(df[col], errors="coerce")
                if parsed.notna().sum() < len(df) * 0.9:
                    continue
                out = df.copy()
                out["_dt"] = parsed
                return out.set_index("_dt").drop(columns=[col])
            except Exception:
                continue
    return df


def _weekly_direction(df) -> str:
    """P1-5 周线方向过滤级信号 — ChanlunAnalyzer(freq='W') 优先, 周线均线兜底。

    Returns: "BULL" / "BEAR" / "neutral"
    """
    if df is None or getattr(df, "empty", True) or len(df) < 40:
        return "neutral"
    import pandas as pd
    d = _to_datetime_index(df)
    if not isinstance(getattr(d, "index", None), pd.DatetimeIndex):
        return "neutral"
    try:
        w = d.resample("W").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"})
        w = w.dropna(subset=["close"])
    except Exception:
        return "neutral"
    if len(w) < 30:
        return "neutral"
    try:
        from src.indicators.chanlun.analyzer import ChanlunAnalyzer
        res = ChanlunAnalyzer(freq="W").analyze(w, "", "")
        cs = res.current_state
        if cs.get("position") == "中枢上方" or cs.get("zhongshu_state") == "上移":
            return "BULL"
        if cs.get("position") == "中枢下方" or cs.get("zhongshu_state") == "下移":
            return "BEAR"
    except Exception:
        pass
    # 兜底: 周线 MA8 vs MA26
    try:
        closes = w["close"].astype(float)
        if len(closes) < 26:
            return "neutral"
        ma8 = float(closes.rolling(8).mean().iloc[-1])
        ma26 = float(closes.rolling(26).mean().iloc[-1])
        if ma8 > ma26 * 1.01:
            return "BULL"
        if ma8 < ma26 * 0.99:
            return "BEAR"
    except Exception:
        pass
    return "neutral"


def _apply_cross_period_filter(snapshot: "TacticalSnapshot", weekly_direction: str) -> None:
    """P1-5 跨周期过滤 — 日线信号与周线方向相反时降权(×0.5)。

    weekly BULL → 日线看空信号降权; weekly BEAR → 日线看多信号降权。
    覆盖趋势跟随(_TREND_FOLLOW_SIGNALS) + 均值回归(_MEAN_REVERSION_SIGNALS)，
    防周线 BEAR 下"接飞刀"(P4)。与 RANGE 门控独立, 叠加时置信度连乘(更保守)。
    """
    if weekly_direction not in ("BULL", "BEAR"):
        return
    tag = f"WEEKLY_{weekly_direction}_DIVERGE"
    if weekly_direction == "BEAR":
        downgrade_set = _TREND_FOLLOW_SIGNALS | _MEAN_REVERSION_SIGNALS
        for sig in snapshot.entry_signals:
            if sig.get("type") in downgrade_set:
                sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
                sig.setdefault("market_gate", tag)
        if snapshot.best_entry and snapshot.best_entry.get("type") in downgrade_set:
            snapshot.best_entry["confidence"] = round(
                float(snapshot.best_entry.get("confidence", 0.5)) * 0.5, 3)
            snapshot.best_entry.setdefault("market_gate", tag)
        snapshot.notes.append(f"[P1-5] 周线{weekly_direction}, 日线买点降权")
    else:  # BULL
        for sig in snapshot.exit_signals:
            if sig.get("type") in _TREND_FOLLOW_SIGNALS:
                sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
                sig.setdefault("market_gate", tag)
        snapshot.notes.append(f"[P1-5] 周线{weekly_direction}, 日线卖点降权")


def _weekly_breakout_structure(df) -> dict:
    """P1-7 周线突破结构判定 — 追突破抑制 / 回踩二波 / 锁利触发。

    回测依据（scripts/weekly_structure_event_study.py + multitimeframe_confluence_study.py）:
      - 周线放量突破当周/次周追入: 历史超额约 -5pp（三信号里最差）
      - 突破后回踩缩量企稳(二波): 13周净收益 +1.3% vs 追突破 -2.9%（文章"第二波"被验证）
      - 近60日涨≥20% + MA5死叉MA10: 后60日净收益 -3.3%, 超额 -5.6pp（锁利规则被验证）

    Returns: {"fresh_breakout", "pullback_reclaim", "lock_profit", "note"}
    """
    import pandas as pd
    out = {"fresh_breakout": False, "pullback_reclaim": False, "lock_profit": False, "note": ""}
    if df is None or getattr(df, "empty", True) or len(df) < 120:
        return out
    d = _to_datetime_index(df)
    if not isinstance(getattr(d, "index", None), pd.DatetimeIndex):
        return out
    try:
        w = d.resample("W-FRI").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna(subset=["close"])
    except Exception:
        return out
    if len(w) < 30:
        return out

    closes = w["close"].astype(float)
    vols = w["volume"].astype(float)
    ma10w = closes.rolling(10).mean()
    platform_high = closes.rolling(_BREAKOUT_PLATFORM_W).max().shift(1)
    vol_ma = vols.rolling(13).mean().shift(1)

    # 周线放量突破（无前视: 平台高与均量都取前值）
    s2 = (closes > platform_high) & (vols > _BREAKOUT_VOL_RATIO * vol_ma) & (vol_ma > 0)
    last_s2_pos = None
    for i in range(len(w) - 1, -1, -1):
        if bool(s2.iloc[i]):
            last_s2_pos = i
            break
    if last_s2_pos is not None and len(w) - 1 - last_s2_pos <= _BREAKOUT_FRESH_W:
        out["fresh_breakout"] = True

    # 回踩二波: 近52周有过突破 + 当前低点触及MA10w带内 + 收回MA10w + 缩量
    breakout_any_52 = (
        s2.fillna(False).rolling(_PULLBACK_LOOKBACK_W, min_periods=1).max().shift(1) > 0
    )
    touch = w["low"] <= ma10w * (1 + _PULLBACK_TOUCH_BAND)
    reclaim = closes >= ma10w
    shrink = vols <= vol_ma
    s3 = breakout_any_52 & touch & reclaim & shrink
    out["pullback_reclaim"] = bool(s3.iloc[-1]) if len(w) else False

    # 锁利: 近60日涨≥20% 且 日线 MA5 死叉 MA10（统一转 Python bool）
    if "close" in d.columns and len(d) >= _LOCK_WINDOW_D + 10:
        dc = d["close"].astype(float)
        base = dc.iloc[-_LOCK_WINDOW_D - 1]
        run_up = (dc.iloc[-1] / base - 1.0) if base > 0 else 0.0
        ma5 = dc.rolling(5).mean()
        ma10 = dc.rolling(10).mean()
        death = bool(ma5.iloc[-1] < ma10.iloc[-1] and ma5.iloc[-2] >= ma10.iloc[-2])
        out["lock_profit"] = bool(run_up >= _LOCK_RUN_UP) and death

    parts = []
    if out["fresh_breakout"] and not out["pullback_reclaim"]:
        parts.append("周线放量突破刚发生")
    if out["pullback_reclaim"]:
        parts.append("突破后回踩MA10周缩量企稳")
    if out["lock_profit"]:
        parts.append("近60日涨≥20%且MA5死叉MA10")
    out["note"] = "; ".join(parts)
    return out


def _apply_breakout_chase_suppressor(snapshot: "TacticalSnapshot", structure: dict) -> None:
    """P1-7 追突破抑制 + 锁利降权（回测依据见 _weekly_breakout_structure docstring）。

    与 _apply_cross_period_filter 同构: 命中条件时对入场信号降权并打 market_gate 标签,
    不清空信号（置信度由下游裁决继续处理）。
    """
    if not structure:
        return
    if structure.get("fresh_breakout") and not structure.get("pullback_reclaim"):
        tag = "WEEKLY_BREAKOUT_SUPPRESS"
        for sig in snapshot.entry_signals:
            if sig.get("type") in _TREND_FOLLOW_SIGNALS:
                sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
                sig.setdefault("market_gate", tag)
        if snapshot.best_entry and snapshot.best_entry.get("type") in _TREND_FOLLOW_SIGNALS:
            snapshot.best_entry["confidence"] = round(
                float(snapshot.best_entry.get("confidence", 0.5)) * 0.5, 3
            )
            snapshot.best_entry.setdefault("market_gate", tag)
        snapshot.notes.append(
            f"[P1-7] {structure['note']} — 周线追突破历史超额约-5pp, 等待回踩缩量企稳再评估"
        )
    if structure.get("lock_profit"):
        tag = "LOCK_PROFIT"
        for sig in snapshot.entry_signals:
            sig["confidence"] = round(float(sig.get("confidence", 0.5)) * 0.5, 3)
            sig.setdefault("market_gate", tag)
        if snapshot.best_entry:
            snapshot.best_entry["confidence"] = round(
                float(snapshot.best_entry.get("confidence", 0.5)) * 0.5, 3
            )
            snapshot.best_entry.setdefault("market_gate", tag)
        snapshot.notes.append(
            f"[P1-7] {structure['note']} — 回测: 该信号后60日净收益约-3.3%(超额-5.6pp), 锁利/不追入"
        )
    elif structure.get("pullback_reclaim") and not structure.get("fresh_breakout"):
        snapshot.notes.append(
            "[P1-7] 突破后回踩缩量企稳 — 回测优于追突破(13周+4.2pp), 可作二波入场确认"
        )


def _mm_projected_target(lo: float, hi: float, direction: str) -> Optional[float]:
    """MM 等距投影公式: 区间高度翻一倍投影到突破方向 (P1-6)。

    上破: target = hi + (hi - lo) = 2*hi - lo
    下破: target = lo - (hi - lo) = 2*lo - hi
    """
    if not (hi > lo > 0):
        return None
    h = hi - lo
    if direction == "up":
        return round(hi + h, 2)
    if direction == "down":
        return round(lo - h, 2)
    return None


def _compute_mm_projection(
    chanlun_summary: Optional[dict],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    current_price: float,
    suggested_stop: float = 0.0,
) -> Optional[dict]:
    """P1-6 MM 等距投影止盈位 — 用缠论中枢(zg/zd)或近期高低点。

    目标位 = 中枢/区间高度向上(或向下)翻一倍投影。含盈亏比≥1:1 校验。
    写入 projected_target (新字段), 不覆盖既有 ATR/时间止损。

    Returns:
        {"target", "direction", "consolidation_low", "consolidation_high",
         "height", "rr_ratio", "note", "source"} 或 None(无法计算)
    """
    lo = hi = None
    direction: Optional[str] = None
    source = ""
    # 优先: 缠论最后一个中枢 (zg/zd)
    if chanlun_summary:
        lz = chanlun_summary.get("last_zs")
        cs = chanlun_summary.get("current_state", {})
        pos = cs.get("position", "未知")
        if lz and lz.get("zd") and lz.get("zg") and float(lz["zg"]) > float(lz["zd"]) > 0:
            lo, hi = float(lz["zd"]), float(lz["zg"])
            source = "缠论中枢"
            if pos == "中枢上方":
                direction = "up"
            elif pos == "中枢下方":
                direction = "down"
            else:
                zz = float(lz.get("zz") or (lo + hi) / 2.0)
                direction = "up" if current_price > zz else "down"
    # 兜底: 近期 60 根高低点
    if lo is None and closes and highs and lows and len(closes) >= 20:
        look = min(len(closes), 60)
        seg_c = closes[-look:]
        seg_h = highs[-look:] if len(highs) >= look else highs
        seg_l = lows[-look:] if len(lows) >= look else lows
        hi = float(max(seg_h))
        lo = float(min(seg_l))
        if hi > lo > 0:
            source = "近60根高低点"
            ma5 = sum(seg_c[-5:]) / 5.0
            ma20 = sum(seg_c[-20:]) / 20.0 if len(seg_c) >= 20 else ma5
            direction = "up" if ma5 > ma20 else "down"
    if lo is None or hi is None or direction is None:
        return None

    target = _mm_projected_target(lo, hi, direction)
    if target is None:
        return None
    height = round(hi - lo, 2)

    note = ""
    rr_ratio: Optional[float] = None
    if suggested_stop and suggested_stop > 0:
        if direction == "up":
            risk = current_price - suggested_stop
            reward = target - current_price
        else:
            risk = suggested_stop - current_price
            reward = current_price - target
        if risk > 0 and reward > 0:
            rr_ratio = round(reward / risk, 2)
            if rr_ratio < 1.0:
                note = f"盈亏比 {rr_ratio} < 1:1, 慎追"
    return {
        "target": target, "direction": direction,
        "consolidation_low": round(lo, 2), "consolidation_high": round(hi, 2),
        "height": height, "rr_ratio": rr_ratio, "note": note, "source": source,
    }


def _apply_projected_target(
    snapshot: "TacticalSnapshot",
    projection: Optional[dict],
    current_price: float,
) -> None:
    """把 MM 投影写入 snapshot, 并触发「接近目标位不追单」标记。

    不覆盖既有 suggested_stop / atr_stop / target_prices (兼容现有止损)。
    """
    if not projection or not projection.get("target"):
        return
    snapshot.projected_target = projection["target"]
    if projection.get("note"):
        snapshot.notes.append(f"[P1-6] {projection['note']}")
    if current_price > 0:
        dist = (projection["target"] - current_price) / current_price
        if projection.get("direction") == "up" and dist <= 0.02:
            snapshot.chase_blocked = True
        elif projection.get("direction") == "down" and dist >= -0.02:
            snapshot.chase_blocked = True


def _annotate_t0_await_close(t0, minute_bars) -> None:
    """P1-5 T+0 收线确认 — 最新分时K线未收线时, 提示待收线后再决策, 不提前进场。

    doc 07: T+0 分时判断加「待分时 K 线收线后再决策」。
    """
    if not isinstance(t0, dict):
        return
    forming = False
    if minute_bars:
        try:
            last_ts = minute_bars[-1].timestamp
            now = datetime.now()
            forming = (last_ts.year, last_ts.month, last_ts.day,
                       last_ts.hour, last_ts.minute) == (
                now.year, now.month, now.day, now.hour, now.minute)
        except Exception:
            forming = False
    if forming:
        note = "⏳ 当前分时K线未收线 — 待K线收线确认后再决策, 不提前进场"
        notes = t0.setdefault("notes", [])
        if note not in notes:
            notes.append(note)
        if str(t0.get("action", "")).upper() in ("BUY", "ENTER", "ADD"):
            t0["advice"] = (t0.get("advice") or "") + "（待分时收线确认）"


def _enhance_market_state(
    snapshot: "TacticalSnapshot",
    index_bars,
    stock_close_series: list[float],
    sentiment,
    daily_df=None,
) -> None:
    """P1-1/P1-5/P1-7 串行增强 — 市场状态分类 + 门控 + 跨周期过滤 + 追突破抑制。

    必须在四个维度并行计算完成后调用 (依赖技术面缠论 / 资金面 / 市场背景)。
    """
    index_closes = index_highs = index_lows = None
    if index_bars is not None and not getattr(index_bars, "empty", True):
        if "close" in index_bars.columns:
            index_closes = [float(x) for x in index_bars["close"].tolist() if x is not None]
        if "high" in index_bars.columns:
            index_highs = [float(x) for x in index_bars["high"].tolist() if x is not None]
        if "low" in index_bars.columns:
            index_lows = [float(x) for x in index_bars["low"].tolist() if x is not None]

    breadth: Optional[float] = None
    if sentiment is not None:
        up = getattr(sentiment, "up_count", 0) or 0
        dn = getattr(sentiment, "down_count", 0) or 0
        if up + dn > 0:
            breadth = up / (up + dn) * 100.0

    detail = _classify_market_state(
        index_closes=index_closes, index_highs=index_highs, index_lows=index_lows,
        breadth=breadth, stock_close_series=stock_close_series,
        chanlun_summary=snapshot.chanlun_result,
    )
    snapshot.market_state = detail["state"]
    snapshot.market_state_confidence = detail["confidence"]
    snapshot.market_state_detail = detail

    # P1-1 门控: RANGE 态下趋势跟随信号降权
    _apply_market_state_gate(snapshot, detail["state"])

    # P1-5 跨周期过滤: 周线方向相反时降权 (weekly_direction 在 _dim_technical 计算)
    if snapshot.weekly_direction:
        _apply_cross_period_filter(snapshot, snapshot.weekly_direction)

    # P1-7 周线突破结构: 追突破抑制 + 回踩二波确认 + 锁利降权 (回测验证 2026-08-07)
    try:
        structure = _weekly_breakout_structure(daily_df) if daily_df is not None else {}
        _apply_breakout_chase_suppressor(snapshot, structure)
    except Exception as e:
        logger.debug("tactics breakout suppressor: %s", e)


# ═══════════════════════════════════════════════════════════════════
# DTO
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TacticalSnapshot:
    """盘面全景快照 — Phase 1 输出，Phase 2/3 的共享输入。"""

    symbol: str
    name: str
    current_price: float = 0.0
    change_pct: float = 0.0

    # ── 🌍 市场背景 ──
    sentiment_label: str = "normal"          # fear / greed / normal
    sentiment_score: float = 50.0            # 0=fear, 100=greed
    market_breadth: str = ""                 # "涨412/跌4785 (8.6%)"
    sentiment_advice: str = ""               # 对操作的提示
    global_market_summary: str = ""           # 全球市场一行总结

    # ── 📊 基本面 ──
    value_score: float = 50.0
    quality_score: float = 50.0
    momentum_score: float = 50.0
    pe_ttm: Optional[float] = None
    industry_pe: Optional[float] = None
    roe: Optional[float] = None
    fundamental_note: str = ""

    # ── 📈 技术面 ──
    trend_score: float = 50.0
    reversal_score: float = 50.0
    volume_score: float = 50.0
    volatility_score: float = 50.0
    ma_score: float = 50.0
    limit_up_score: float = 50.0
    technical_composite: float = 50.0
    entry_signals: list[dict] = field(default_factory=list)
    exit_signals: list[dict] = field(default_factory=list)
    best_entry: Optional[dict] = None
    suggested_stop: float = 0.0
    atr_stop: float = 0.0           # ATR 移动止损价
    atr: float = 0.0                # ATR 原始值 (供浮盈阶梯加仓)
    target_prices: list[float] = field(default_factory=list)   # ATR 参考目标位 (非强制离场, 主离场走 exit_signals)
    time_stop_days: int = 10
    macd_kdj: Optional[dict] = None
    technical_note: str = ""

    # ── 🌐 市场状态前置判定 + 跨周期过滤 + MM等距投影 (P1-1/P1-5/P1-6) ──
    market_state: str = "RANGE"            # BULL_TRENDING / BEAR_TRENDING / RANGE
    market_state_confidence: float = 0.0
    market_state_detail: Optional[dict] = None   # regime/h/choppiness/zhongshu/rationale
    weekly_direction: str = "neutral"      # BULL / BEAR / neutral (周线过滤级信号)
    projected_target: float = 0.0          # MM 等距投影止盈参考位 (不覆盖 target_prices)
    chase_blocked: bool = False            # 现价接近投影目标位 → 不追单
    notes: list[str] = field(default_factory=list)   # 门控/投影等辅助说明

    # ── 🥋 缠论结构（独立维度，不改 6 维 composite）──
    chanlun_score: float = 50.0
    chanlun_result: Optional[dict] = None

    # ── 💰 资金面 ──
    margin_balance: Optional[float] = None         # 融资余额(亿)
    margin_trend: str = "stable"                   # increasing/decreasing/stable
    margin_5d_pct: float = 0.0                     # 5日融资变化%
    short_balance: Optional[float] = None           # 融券余额(亿)
    short_5d_pct: float = 0.0                      # 5日融券变化%
    margin_alerts: list[str] = field(default_factory=list)
    sector_inflow: bool = False                     # 标的板块今日净流入?
    sector_top_inflow: list[str] = field(default_factory=list)   # 今日资金流入 top3 板块
    sector_top_outflow: list[str] = field(default_factory=list)  # 今日资金流出 top3 板块
    dominant_player: str = ""                       # 博弈论主导玩家
    crowding_score: int = 50                        # 拥挤度
    gt_entry_allowed: bool = False                  # 博弈是否允许入场
    gt_action: str = "WAIT"                         # 博弈建议动作
    gt_rationale: list[str] = field(default_factory=list)
    capital_note: str = ""

    # ── 持仓 ──
    held: bool = False
    position_entry: Optional[float] = None
    position_loss_pct: float = 0.0

    # ── 元数据 ──
    data_gaps: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        """转为 dict 供 Phase 2/3 消费。"""
        return {
            "symbol": self.symbol, "name": self.name,
            "current_price": self.current_price, "change_pct": self.change_pct,
            "sentiment": self.sentiment_label, "sentiment_score": self.sentiment_score,
            "value_score": self.value_score, "quality_score": self.quality_score,
            "momentum_score": self.momentum_score,
            "technical_composite": self.technical_composite,
            "entry_signals": self.entry_signals, "exit_signals": self.exit_signals,
            "best_entry": self.best_entry,
            "suggested_stop": self.suggested_stop,
            "target_prices": self.target_prices,
            "macd_kdj_action": self.macd_kdj.get("action") if self.macd_kdj else None,
            "margin_trend": self.margin_trend,
            "margin_5d_pct": self.margin_5d_pct,
            "short_5d_pct": self.short_5d_pct,
            "sector_inflow": self.sector_inflow,
            "dominant_player": self.dominant_player,
            "crowding_score": self.crowding_score,
            "gt_entry_allowed": self.gt_entry_allowed,
            "held": self.held, "position_loss_pct": self.position_loss_pct,
            "market_state": self.market_state,
            "market_state_confidence": self.market_state_confidence,
            "weekly_direction": self.weekly_direction,
            "projected_target": self.projected_target,
            "chase_blocked": self.chase_blocked,
            "data_gaps": self.data_gaps,
        }


@dataclass
class TacticsResult:
    """短线战术最终结论。"""

    symbol: str
    name: str = ""
    current_price: float = 0.0

    # Phase 1 快照
    snapshot: Optional[TacticalSnapshot] = None

    # Phase 2 输出
    doctrine_passed: bool = True
    doctrine_warnings: list[str] = field(default_factory=list)
    debate_result: Optional[dict] = None
    debate_perspectives: Optional[dict] = None
    mental_models: list[dict] = field(default_factory=list)
    t0_result: Optional[dict] = None

    # Phase 3 输出
    verdict_score: float = 0.0
    verdict_recommendation: str = ""
    verdict_confidence: float = 0.0
    signal_action: str = ""
    signal_weight: float = 0.0
    sizing_detail: Optional[dict] = None
    risk_passed: bool = True

    # 最终
    action: str = "WAIT"
    confidence: float = 0.5
    warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════


def run_tactics(
    orch: "Orchestrator",
    *,
    symbol: str,
    market: str = "SH",
    name: str = "",
    skip_t0: bool = False,
    skip_debate: bool = False,
) -> TacticsResult:
    """短线战术管道 — 4-Phase 架构，买卖时机判断。

    Args:
        orch: Orchestrator 实例（复用所有引擎）
        symbol: 6 位股票代码
        market: SH / SZ
        name: 股票名称
        skip_t0: True=跳过 T+0
        skip_debate: True=跳过辩论+芒格（极速模式，2-3s）
    """
    from src.output.progress import step_start, step_done, info as _info
    from src.output.step_output import (
        print_doctrine, print_diagnosis, print_debate, print_munger_models,
        print_positioning, print_risk_control,
    )

    result = TacticsResult(symbol=symbol, name=name)

    print()
    print("  ⚡ tactics — 短线战术（买卖时机）")
    mode_label = "极速模式" if skip_debate else "标准模式"
    print(f"  📡 {mode_label} | 8步流水线")

    # 步骤计数器 — 贯穿 Phase 1→2→3
    TOTAL = 8
    _step = 0  # Phase 1→2→3 numbered steps

    # ═══════════════════════════════════════════════════════════════
    # Phase 0: 并行预拉取 6 路数据 (~2s)
    # ═══════════════════════════════════════════════════════════════
    _info("Phase 0: 并行拉取 行情/K线/财务/融资/板块资金/市场情绪...")
    t0_tick = datetime.now()

    # 共享存储
    _quote = None
    _cross_validated = False
    _bars_df = None       # pd.DataFrame | None
    _chanlun_state: dict = {}   # 缠论状态 → doctrine_ctx 注入
    _close_series: list[float] = []
    _ma20 = None
    _ma60 = None
    _fin_list: list[dict] = []
    _margin_profile = None
    _margin_alerts: list = []
    _sector_flow = None
    _sentiment = None

    # --- 路 1: 行情 ---
    def _io_quote():
        nonlocal _quote, _cross_validated
        try:
            _quote, _cross_validated, _ = orch.data.get_cross_validated_quote(symbol, market)
        except Exception:
            try:
                _quote = orch.data.get_quote(symbol, market)
            except Exception:
                _quote = orch._quote_from_cache(symbol, market)

    # --- 路 2: 日线K线+MA+财务 ---
    def _io_bars_and_financials():
        nonlocal _bars_df, _close_series, _ma20, _ma60, _fin_list
        import pandas as pd
        end = datetime.now()
        try:
            _bars_df = orch.data.get_history(
                symbol,
                start_date=(end - __import__("datetime").timedelta(days=400)).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                period="daily",
            )
            if _bars_df is not None and not getattr(_bars_df, "empty", True):
                col_map = {
                    "open": "open", "high": "high", "low": "low",
                    "close": "close", "volume": "volume", "vol": "volume",
                    "开盘": "open", "最高": "high", "最低": "low",
                    "收盘": "close", "成交量": "volume",
                }
                if hasattr(_bars_df, "rename"):
                    _bars_df = _bars_df.rename(
                        columns={c: col_map[c] for c in _bars_df.columns if c in col_map}
                    )
        except Exception as e:
            logger.debug("tactics bars: %s", e)

        if _bars_df is not None and not _bars_df.empty:
            c_col = _bars_df["close"] if "close" in _bars_df.columns else None
            if c_col is not None and len(c_col) > 0:
                _close_series = c_col.tolist()
                if len(c_col) >= 60:
                    _ma20 = float(c_col.rolling(20).mean().iloc[-1])
                    _ma60 = float(c_col.rolling(60).mean().iloc[-1])
                elif len(c_col) >= 20:
                    _ma20 = float(c_col.rolling(20).mean().iloc[-1])

        # 财务
        try:
            fins = orch.data.get_financials(symbol, market, count=8)
            _fin_list = [
                f.model_dump() if hasattr(f, "model_dump") else dict(f)
                for f in (fins or [])
            ]
        except Exception as e:
            logger.debug("tactics financials: %s", e)

    # --- 路 3: 融资融券 ---
    def _io_margin():
        nonlocal _margin_profile, _margin_alerts
        try:
            from src.game_theory.margin import get_margin_analyzer
            analyzer = get_margin_analyzer()
            _margin_profile = analyzer.analyze(symbol, name, close_price=0)
            _margin_alerts = analyzer.get_alerts(symbol, name, close_price=0)
        except Exception as e:
            logger.debug("tactics margin: %s", e)

    # --- 路 4: 板块资金流向 ---
    def _io_sector_flow():
        nonlocal _sector_flow
        try:
            _sector_flow = orch.data.get_sector_capital_flow()
        except Exception as e:
            logger.debug("tactics sector flow: %s", e)

    # --- 路 5: 市场情绪 ---
    def _io_sentiment():
        nonlocal _sentiment
        try:
            from src.sentiment.signals import SentimentDetector
            _sentiment = SentimentDetector().detect_market()
        except Exception as e:
            logger.debug("tactics sentiment: %s", e)

    # --- 路 6: 全球市场 (US+日韩+恒生+A股大盘, 东财API批量) ---
    _global_market = None

    def _io_global_market():
        nonlocal _global_market
        try:
            _global_market = orch.data.get_global_market()
        except Exception as e:
            logger.debug("tactics global_market: %s", e)

    # --- 路 7: 日内K线 (如果 skip_t0, 跳过) ---
    _minute_bars = None

    def _io_minute():
        nonlocal _minute_bars
        if skip_t0:
            return
        try:
            from src.data.schema import Resolution
            today = datetime.now().strftime("%Y%m%d")
            _minute_bars = orch.data.mootdx.get_bars(
                symbol, Resolution.MIN_1, start=today, end=today,
            )
            if _minute_bars:
                now = datetime.now()
                today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                _minute_bars = [
                    b for b in _minute_bars
                    if b is not None and b.timestamp.date() == today_dt.date()
                    and b.timestamp <= now
                ]
        except Exception as e:
            logger.debug("tactics minute bars: %s", e)

    # --- 路 8: 上证指数日线 (市场状态前置判定 P1-1; 失败则用标的日线兜底) ---
    _index_bars = None

    def _io_index():
        nonlocal _index_bars
        try:
            import urllib.request
            url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   "?param=sh000001,day,,,120,qfq")
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            raw = json.loads(resp.read().decode("utf-8"))
            kdata = ((raw.get("data") or {}).get("sh000001", {}).get("qfqday")
                     or (raw.get("data") or {}).get("sh000001", {}).get("day")
                     or [])
            # 腾讯格式: ["YYYY-MM-DD", 开盘, 收盘, 最高, 最低, 成交量]
            rows = []
            for row in kdata[-120:]:
                try:
                    ts = datetime.strptime(row[0], "%Y-%m-%d")
                    rows.append((ts, float(row[2]), float(row[3]), float(row[4])))
                except (ValueError, IndexError, TypeError):
                    continue
            if len(rows) >= 20:
                import pandas as pd
                _index_bars = pd.DataFrame(
                    rows, columns=["date", "close", "high", "low"])
        except Exception as e:
            logger.debug("tactics index fetch: %s", e)

    # --- 并行执行 ---
    io_tasks = {
        "quote": _io_quote,
        "bars+fin": _io_bars_and_financials,
        "margin": _io_margin,
        "sector_flow": _io_sector_flow,
        "sentiment": _io_sentiment,
        "global_market": _io_global_market,
        "minute": _io_minute,
        "index": _io_index,
    }

    with ThreadPoolExecutor(max_workers=len(io_tasks)) as pool:
        futures = {pool.submit(fn): label for label, fn in io_tasks.items()}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.debug("tactics io %s: %s", futures[f], e)

    # 逐源状态 — 每路IO独立展示成功/失败
    _io_parts = []
    cv = "✅双源" if _cross_validated else "⚠️单源"
    _io_parts.append(f"行情{cv}" if _quote else "行情❌")
    if _bars_df is not None and not getattr(_bars_df, "empty", True):
        _io_parts.append(f"K线{len(_close_series)}根")
    else:
        _io_parts.append("K线❌")
    _io_parts.append(f"财务{len(_fin_list)}期" if _fin_list else "财务❌")
    _io_parts.append("融资✅" if _margin_profile is not None else "融资❌")
    _io_parts.append("板块✅" if _sector_flow is not None else "板块❌")
    _io_parts.append("情绪✅" if _sentiment is not None else "情绪❌")
    _io_parts.append("全球✅" if _global_market is not None else "全球❌")
    _io_parts.append("指数✅" if _index_bars is not None else "指数❌")
    if not skip_t0:
        _io_parts.append(f"日内{len(_minute_bars)}根" if _minute_bars else "日内❌")
    _info(f"  {' | '.join(_io_parts)}")

    phase0_elapsed = (datetime.now() - t0_tick).total_seconds()
    _info(f"  Phase 0 完成 ({phase0_elapsed:.1f}s)")

    # --- Phase 0 兜底检查 ---
    if _quote is None:
        result.warnings.append("行情数据不可用")
        print("  ⛔ 行情不可用")
        return result

    current_price = float(getattr(_quote, "price", 0) or 0)
    result.current_price = current_price
    if not name:
        name = _quote.name or ""
        result.name = name

    quote_dict = _quote.model_dump() if hasattr(_quote, "model_dump") else (
        _quote.dict() if hasattr(_quote, "dict") else {}
    )
    quote_dict["_source"] = getattr(_quote, "source", "unknown")
    quote_dict["cross_validated"] = _cross_validated
    quote_dict["ma20"] = _ma20
    quote_dict["ma60"] = _ma60
    quote_dict["close_series"] = (_close_series[-10:] if len(_close_series) >= 10
                                  else _close_series)

    # 投资者偏好
    investor, _, _, _ = orch._get_investor_prefs()
    position_limits = None
    weights = None
    risk_mult = 1.0
    enabled_rules = None
    if investor is not None:
        try:
            from src.learner.preference.adapter import (
                resolve_weights, resolve_rule_filter,
                resolve_position_limits, resolve_macro_cap_multiplier,
                is_board_accessible,
            )
            from src.learner.preference.model import get_board_from_symbol
            if not is_board_accessible(investor, symbol):
                result.warnings.append(f"板块限制: {get_board_from_symbol(symbol)}")
                return result
            position_limits = resolve_position_limits(investor)
            weights = resolve_weights(investor)
            risk_mult = resolve_macro_cap_multiplier(investor)
            enabled_rules = resolve_rule_filter(investor)
        except Exception as e:
            logger.debug("tactics prefs: %s", e)

    # 持仓
    pos_snap = _load_position_row(symbol)
    held = bool(pos_snap)
    loss_pct = 0.0
    if pos_snap:
        loss_pct = _pos_loss_pct(current_price, pos_snap.get("entry_price"))

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: 盘面全景 (~0.5s, 4维并行本地计算)
    # ═══════════════════════════════════════════════════════════════
    _info("Phase 1: 盘面全景 (基本面‖技术面‖资金面‖市场背景 并行)...")
    t1_tick = datetime.now()

    snapshot = TacticalSnapshot(
        symbol=symbol, name=name,
        current_price=current_price,
        change_pct=float(getattr(_quote, "change_pct", 0) or 0),
        held=held, position_loss_pct=loss_pct,
    )
    if pos_snap:
        snapshot.position_entry = pos_snap.get("entry_price")

    # 并行计算上下文
    _report = None          # diagnosis report
    _gt_profile = None      # game theory profile
    _gt_advice = None       # fused timing advice
    _timing_result = None   # entry/exit timing result

    # --- 维度 1: 市场背景 ---
    def _dim_market_bg():
        if _sentiment is not None:
            # ... existing sentiment code ...
            try:
                level = getattr(getattr(_sentiment, "level", None), "value", None)
                score = getattr(_sentiment, "score", 50)
                if level is None:
                    level = str(getattr(_sentiment, "level", "normal"))
                snapshot.sentiment_label = str(level)
                snapshot.sentiment_score = float(score) if score else 50.0
            except Exception:
                pass
            up = getattr(_sentiment, "up_count", 0) or 0
            dn = getattr(_sentiment, "down_count", 0) or 0
            total = up + dn
            if total > 0:
                snapshot.market_breadth = f"涨{up}/跌{dn} ({up / total * 100:.1f}%上涨)"
            else:
                snapshot.market_breadth = "数据暂缺"

        # 全球市场
        if _global_market and _global_market.summary:
            snapshot.global_market_summary = _global_market.summary
        elif _global_market and _global_market.us_summary:
            snapshot.global_market_summary = _global_market.us_summary

        # 情绪建议 (融入全球市场背景)
        s = snapshot.sentiment_score
        gm = snapshot.global_market_summary
        if s < 25:
            base = "恐慌 — 可稍激进"
            if gm and "-" in gm:
                snapshot.sentiment_advice = f"{base}, 但注意全球联动偏弱"
            else:
                snapshot.sentiment_advice = f"{base}, 注意流动性"
        elif s > 75:
            snapshot.sentiment_advice = "贪婪 — 谨慎追高, 止损必须更紧"
        else:
            snapshot.sentiment_advice = "正常 — 按个股自身判断"

    # --- 维度 2: 基本面 ---
    def _dim_fundamental():
        nonlocal _report
        try:
            _report = orch.diagnosis.analyze(
                symbol, name, quote_dict, _fin_list or None, {}, None,
            )
            if _report:
                snapshot.value_score = _report.value_score
                snapshot.quality_score = _report.quality_score
                snapshot.momentum_score = _report.momentum_score
                # 提取 PE / ROE
                if hasattr(_report, "__dict__"):
                    d = _report.__dict__
                    snapshot.pe_ttm = d.get("pe_ttm") or d.get("pe")
                    snapshot.roe = d.get("roe")
                if _fin_list:
                    latest = _fin_list[0]
                    if snapshot.pe_ttm is None:
                        snapshot.pe_ttm = quote_dict.get("pe_ttm") or quote_dict.get("pe")
                    if snapshot.roe is None:
                        snapshot.roe = latest.get("roe")
                # 行业PE
                if snapshot.pe_ttm:
                    snapshot.industry_pe = _estimate_industry_pe(symbol)
                snapshot.fundamental_note = (
                    f"价值{snapshot.value_score:.0f} 质量{snapshot.quality_score:.0f} "
                    f"动量{snapshot.momentum_score:.0f}"
                )
        except Exception as e:
            logger.debug("tactics fundamental: %s", e)
            snapshot.data_gaps.append("[DATA_GAP] 基本面诊断")

    # --- 维度 3: 技术面 (6维+入场出场+KDJ, 共享K线) ---
    def _dim_technical():
        nonlocal _timing_result
        if _bars_df is None or getattr(_bars_df, "empty", True):
            snapshot.data_gaps.append("[DATA_GAP] 技术面(日线不可用)")
            return

        import pandas as pd
        from src.routing.technical import TechnicalAnalyzer
        from src.routing.entry_exit_engine import EntryExitEngine
        from src.alphas.macd_kdj import evaluate_ohlc_latest, normalize_ohlc_df

        df = _bars_df
        if len(df) < 20:
            snapshot.data_gaps.append("[DATA_GAP] 技术面(日线不足20根)")
            return

        c_col = df["close"] if "close" in df.columns else None
        if c_col is None:
            return
        h_col = df["high"] if "high" in df.columns else c_col
        l_col = df["low"] if "low" in df.columns else c_col
        v_col = df["volume"] if "volume" in df.columns else pd.Series([1e6] * len(c_col))

        panel = {
            "close": pd.DataFrame({symbol: c_col.values}, index=c_col.index),
            "high": pd.DataFrame({symbol: h_col.values}, index=h_col.index),
            "low": pd.DataFrame({symbol: l_col.values}, index=l_col.index),
            "volume": pd.DataFrame({symbol: v_col.values}, index=v_col.index),
        }

        # 注入 17 个技术因子帧，使六维真实打分（修复 P0-1 空转：原 panel 仅 OHLCV）
        _inject_technical_factors(panel, df, symbol)

        # 6维评分
        try:
            tech = TechnicalAnalyzer().analyze(symbol, name, panel)
            snapshot.trend_score = tech.trend_score
            snapshot.reversal_score = tech.reversal_score
            snapshot.volume_score = tech.volume_score
            snapshot.volatility_score = tech.volatility_score
            snapshot.ma_score = tech.ma_score
            snapshot.limit_up_score = tech.limit_up_score
            snapshot.technical_composite = tech.composite_score
        except Exception:
            pass

        # 入场/出场信号
        try:
            _timing_result = EntryExitEngine().evaluate(symbol, name, panel)
            if _timing_result:
                snapshot.entry_signals = [
                    {"type": s.type, "description": s.description,
                     "zone_low": s.entry_zone_low, "zone_high": s.entry_zone_high,
                     "confidence": s.confidence}
                    for s in _timing_result.entry_signals
                ]
                snapshot.exit_signals = [
                    {"type": s.type, "description": s.description,
                     "zone_low": s.exit_zone_low, "zone_high": s.exit_zone_high,
                     "confidence": s.confidence, "urgency": s.urgency}
                    for s in _timing_result.exit_signals
                ]
                if _timing_result.best_entry:
                    be = _timing_result.best_entry
                    snapshot.best_entry = {
                        "type": be.type, "description": be.description,
                        "zone_low": be.entry_zone_low, "zone_high": be.entry_zone_high,
                        "confidence": be.confidence,
                    }
                snapshot.suggested_stop = _timing_result.suggested_stop
                snapshot.atr_stop = _timing_result.atr_stop
                snapshot.atr = _timing_result.atr
                snapshot.target_prices = [_timing_result.target_1, _timing_result.target_2]
                snapshot.time_stop_days = _timing_result.time_stop_days
        except Exception:
            pass

        # KDJ+MACD
        try:
            kdj_df = normalize_ohlc_df(df)
            if kdj_df is not None and len(kdj_df) >= 40:
                px = float(quote_dict.get("price") or quote_dict.get("close") or 0)
                if px > 0 and "close" in kdj_df.columns:
                    last = float(kdj_df["close"].iloc[-1])
                    if abs(last - px) / max(px, 1e-9) > 0.001:
                        kdj_df = kdj_df.copy()
                        kdj_df.loc[kdj_df.index[-1], "close"] = px
                snapshot.macd_kdj = evaluate_ohlc_latest(kdj_df)
        except Exception:
            pass

        # 缠论独立维度 (M4, 决策A: 独立报告不改 composite)
        try:
            from src.indicators.chanlun.analyzer import ChanlunAnalyzer
            chanlun_res = ChanlunAnalyzer(freq="D").analyze(df, symbol, name)
            _chanlun_state.update(_apply_chanlun_snapshot(snapshot, chanlun_res))
        except Exception:
            snapshot.data_gaps.append("[DATA_GAP] 缠论分析")

        # 周线方向过滤级信号 (P1-5 跨周期过滤, 日线信号与周线相反时降权)
        try:
            snapshot.weekly_direction = _weekly_direction(df)
        except Exception:
            snapshot.weekly_direction = "neutral"

        # MM 等距投影止盈位 (P1-6) — 缠论中枢/近期高低点等距投影, 不覆盖现有止损
        try:
            _apply_projected_target(
                snapshot,
                _compute_mm_projection(
                    snapshot.chanlun_result,
                    highs=[float(x) for x in h_col.tolist()],
                    lows=[float(x) for x in l_col.tolist()],
                    closes=[float(x) for x in c_col.tolist()],
                    current_price=current_price,
                    suggested_stop=snapshot.suggested_stop,
                ),
                current_price,
            )
        except Exception:
            pass

        snapshot.technical_note = (
            f"综合{snapshot.technical_composite:.0f} "
            f"趋势{snapshot.trend_score:.0f} 反转{snapshot.reversal_score:.0f} "
            f"量价{snapshot.volume_score:.0f} | "
            f"入场{len(snapshot.entry_signals)}个 出场{len(snapshot.exit_signals)}个"
        )

    # --- 维度 4: 资金面 (融资+板块+博弈融合) ---
    def _dim_capital():
        nonlocal _gt_profile, _gt_advice

        # 融资融券
        if _margin_profile is not None:
            mp = _margin_profile
            snapshot.margin_balance = getattr(mp, "margin_balance", None)
            snapshot.margin_trend = getattr(mp, "margin_balance_trend", "stable") or "stable"
            snapshot.margin_5d_pct = getattr(mp, "margin_balance_5d_change_pct", 0.0) or 0.0
            snapshot.short_balance = getattr(mp, "short_balance", None)
            snapshot.short_5d_pct = getattr(mp, "short_balance_5d_change_pct", 0.0) or 0.0
            if _margin_alerts:
                snapshot.margin_alerts = [
                    f"[{a.severity}] {a.message[:80]}" for a in _margin_alerts[:5]
                ]
        else:
            snapshot.data_gaps.append("[DATA_GAP] 融资融券")

        # 板块资金流向
        if _sector_flow is not None and hasattr(_sector_flow, "sectors") and _sector_flow.sectors:
            try:
                top_in = sorted(_sector_flow.sectors, key=lambda x: x.main_net, reverse=True)[:3]
                top_out = sorted(_sector_flow.sectors, key=lambda x: x.main_net)[:3]
                snapshot.sector_top_inflow = [
                    f"{s.sector_name}({s.main_net:+.1f}亿)" for s in top_in
                ]
                snapshot.sector_top_outflow = [
                    f"{s.sector_name}({s.main_net:+.1f}亿)" for s in top_out
                ]
                # 判断标的所在板块是否净流入 (先确定板块名)
                stock_sector = _infer_stock_sector(symbol, name)
                for s in _sector_flow.sectors:
                    if s.sector_name == stock_sector:
                        snapshot.sector_inflow = s.main_net > 0
                        break
            except Exception:
                pass
        elif _sector_flow is not None:
            snapshot.data_gaps.append(
                getattr(_sector_flow, "data_gap_reason", "[DATA_GAP] 板块资金流向")
            )

        # 博弈论分析
        try:
            mcap = getattr(_quote, "market_cap", None) or quote_dict.get("market_cap")
            _gt_profile = orch.gt_analyzer.analyze(symbol, name, mcap, "")
        except Exception as e:
            logger.debug("tactics gt: %s", e)

        if _gt_profile:
            snapshot.dominant_player = getattr(_gt_profile, "dominant_player", "") or ""
            snapshot.crowding_score = int(
                getattr(_gt_profile, "crowding_score", 50) or 50
            )

        # 博弈×技术融合
        if _timing_result and _gt_profile:
            try:
                from src.routing.gt_timing import fuse_timing_with_game_theory
                _gt_advice = fuse_timing_with_game_theory(
                    _timing_result, _gt_profile,
                    held=held, current_price=current_price,
                    position_loss_pct=loss_pct,
                    bottom_phase="",
                )
            except Exception:
                pass

        if _gt_advice:
            snapshot.gt_entry_allowed = getattr(_gt_advice, "entry_allowed", False)
            snapshot.gt_action = getattr(_gt_advice, "action", "WAIT") or "WAIT"
            snapshot.gt_rationale = list(
                getattr(_gt_advice, "rationale", []) or []
            )[:3]

        # 资金面备注
        parts = []
        if snapshot.margin_balance:
            parts.append(f"融资{snapshot.margin_balance:.1f}亿 {snapshot.margin_trend}")
        if snapshot.short_5d_pct and abs(snapshot.short_5d_pct) > 5:
            parts.append(f"融券5日{snapshot.short_5d_pct:+.0f}%")
        if snapshot.sector_top_inflow:
            parts.append(f"板块流入TOP: {snapshot.sector_top_inflow[0]}")
        parts.append(f"博弈: {snapshot.dominant_player or '?'} 拥挤{snapshot.crowding_score}")
        snapshot.capital_note = " | ".join(parts)

    # --- 并行执行 ---
    _dim_labels = {
        "market_bg": "市场背景", "fundamental": "基本面诊断",
        "technical": "技术面6维", "capital": "资金面",
    }
    dim_tasks = {
        "market_bg": _dim_market_bg,
        "fundamental": _dim_fundamental,
        "technical": _dim_technical,
        "capital": _dim_capital,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): label for label, fn in dim_tasks.items()}
        for f in as_completed(futures):
            label = futures[f]
            try:
                f.result()
                _info(f"    ✅ {_dim_labels.get(label, label)}")
            except Exception as e:
                _info(f"    ⚠️ {_dim_labels.get(label, label)}")
                logger.debug("tactics dim %s: %s", label, e)

    result.snapshot = snapshot

    # ── P1-1/P1-5: 市场状态前置判定 + 门控 + 跨周期过滤 (串行, 依赖各维度就绪) ──
    try:
        _enhance_market_state(snapshot, _index_bars, _close_series, _sentiment, _bars_df)
    except Exception as e:
        logger.debug("tactics market enhance: %s", e)

    phase1_elapsed = (datetime.now() - t1_tick).total_seconds()

    # Phase 1 step marker — after data computed, before detailed output
    _step += 1
    step_start(_step, "盘面全景", total=TOTAL)
    funds_parts = []
    if snapshot.margin_balance:
        funds_parts.append(f"融资{snapshot.margin_balance:.1f}亿")
    if snapshot.sector_top_inflow:
        funds_parts.append(f"板块流入{snapshot.sector_top_inflow[0]}")
    pe_label = f"PE{snapshot.pe_ttm:.0f}" if snapshot.pe_ttm else "PE暂无"
    detail_items = [
        f"情绪{snapshot.sentiment_label.upper()}",
        pe_label,
        f"技术{snapshot.technical_composite:.0f}",
    ] + funds_parts
    step_done("✅", " | ".join(detail_items))

    # --- 输出盘面全景 ---
    _print_snapshot(snapshot)

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: 军规 → 辩论 ‖ 芒格 ‖ T+0
    # ═══════════════════════════════════════════════════════════════
    t2_tick = datetime.now()

    # --- 2a: 军规 (串行, 纯规则, ~0.1s) ---
    _step += 1
    step_start(_step, "军规审查", total=TOTAL)
    _doctrine_warnings: list[str] = []
    _doctrine_full = None

    # 构建军规上下文 (从缓存提取, 零网络)
    doctrine_ctx = {"stock_name": name}
    if _chanlun_state:
        doctrine_ctx.update(_chanlun_state)
    cs = _close_series
    if len(cs) >= 6:
        try:
            doctrine_ctx["rise_5day_pct"] = round((cs[-1] - cs[-6]) / cs[-6] * 100, 2)
        except Exception:
            doctrine_ctx["rise_5day_pct"] = 0.0
    if len(cs) >= 4:
        try:
            doctrine_ctx["drop_3day_pct"] = round((cs[-1] - cs[-4]) / cs[-4] * 100, 2)
        except Exception:
            pass
    try:
        bottom_ctx = {}
        orch._inject_bottom_structure_ctx(symbol, market,
            {"close_series": cs}, bottom_ctx)
        doctrine_ctx.update(bottom_ctx)
    except Exception:
        pass
    try:
        _extract_financial_doctrine_ctx(_fin_list, doctrine_ctx)
    except Exception:
        pass

    dr = orch.doctrine.check(symbol, doctrine_ctx, enabled_rules=enabled_rules)
    # 短线模式: 所有规则降级为 warn, 不 block
    _doctrine_warnings = [r.name for r in dr.warnings + dr.blocked_by]

    # 构建 doctrine_full
    triggered = {r.id for r in dr.blocked_by + dr.warnings + dr.infos}
    from src.doctrine.rules import MILITARY_RULES
    all_rules = []
    for rule in MILITARY_RULES:
        if enabled_rules is not None and rule.id not in enabled_rules:
            continue
        status = (
            "warn" if (rule in dr.blocked_by or rule in dr.warnings)
            else ("info" if rule in dr.infos else "passed")
        )
        all_rules.append({
            "id": rule.id, "name": rule.name,
            "severity": rule.severity.value,
            "description": rule.description, "status": status,
        })
    _doctrine_full = {"passed": True, "warn_count": len(_doctrine_warnings), "rules": all_rules}

    result.doctrine_passed = True  # 短线模式不block
    result.doctrine_warnings = _doctrine_warnings

    step_done(
        ("⚠️" if _doctrine_warnings else "✅"),
        f"{len(MILITARY_RULES)}条: 阻断0 警告{len(_doctrine_warnings)}"
    )
    try:
        print_doctrine(_doctrine_full)
    except Exception:
        pass

    # --- 2b: 辩论 ‖ 芒格 ‖ T+0 (并行) ---
    _debate = None
    _matched_models: list = []
    _t0 = None

    def _run_debate():
        nonlocal _debate
        if skip_debate:
            return
        if _report is None:
            return
        try:
            _debate = orch.perspective_analyzer.debate(
                symbol, name, l1_report=_report,
                quote=quote_dict, financials=_fin_list or [],
            )
        except Exception as e:
            logger.debug("tactics debate: %s", e)

    def _run_mental_models():
        nonlocal _matched_models
        if skip_debate:
            return
        if _report is None:
            return
        try:
            _sector = getattr(_report, "sector", "") or ""
            # 注入时机上下文 — 让匹配器知道这是短线买卖时机判断而非选股
            timing_question = _build_timing_question(snapshot)
            _matched_models = orch.mental_model_matcher.match_models(
                symbol, name, sector=_sector, report=_report,
                question=timing_question,
            )
        except Exception as e:
            logger.debug("tactics munger: %s", e)

    def _run_t0():
        nonlocal _t0
        if skip_t0:
            return
        try:
            _t0 = orch.run_t0(symbol, market, name)
            # P1-5 T+0 收线确认: 最新分时K线未收线时, 提示待收线后再决策
            _annotate_t0_await_close(_t0, _minute_bars)
        except Exception as e:
            logger.debug("tactics t0: %s", e)

    phase2_tasks = {
        "debate": _run_debate,
        "mental_models": _run_mental_models,
        "t0": _run_t0,
    }

    # 先并行跑，再按顺序展示步骤进度
    _phase2_results: dict[str, Exception | None] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): label for label, fn in phase2_tasks.items()}
        for f in as_completed(futures):
            label = futures[f]
            try:
                f.result()
                _phase2_results[label] = None
            except Exception as e:
                _phase2_results[label] = e
                logger.debug("tactics phase2 %s: %s", label, e)

    # --- 2b-1: 四大师辩论 ---
    _step += 1
    step_start(_step, "四大师辩论", total=TOTAL)
    if _debate:
        step_done("✅", f"分歧度{_debate.score_range:.1f} 评分{_debate.avg_score:.1f}/5")
    elif skip_debate:
        step_done("⏭️", "极速模式跳过")
    else:
        step_done("⚠️", "辩论数据不可用")

    # --- 2b-2: Munger 思维模型 ---
    _step += 1
    step_start(_step, "Munger思维模型", total=TOTAL)
    if _matched_models:
        step_done("✅", f"匹配{len(_matched_models)}个模型")
    elif skip_debate:
        step_done("⏭️", "极速模式跳过")
    else:
        step_done("⚠️", "模型匹配不可用")

    # --- 2b-3: T+0 日内时机 ---
    _step += 1
    step_start(_step, "T+0日内时机", total=TOTAL)
    if _t0 is not None:
        score = _t0.get("score", 0) if isinstance(_t0, dict) else getattr(_t0, "score", 0)
        action = _t0.get("advice", "") if isinstance(_t0, dict) else getattr(_t0, "advice", "")
        step_done("✅", f"得分{score} {action}" if action else f"得分{score}")
    elif skip_t0:
        step_done("⏭️", "已跳过")
    else:
        step_done("⚠️", "T+0数据不可用")

    # --- 处理结果 ---
    if _debate:
        result.debate_result = {
            "avg_score": _debate.avg_score,
            "score_range": _debate.score_range,
            "agreement_level": _debate.agreement_level,
            "recommendation": _debate.recommendation,
            "top_disagreement": _debate.top_disagreement,
            "top_agreement": _debate.top_agreement,
            "tension_summary": _debate.tension_summary,
        }
        result.debate_perspectives = {
            "buffett": _perspective_to_dict(_debate.buffett),
            "li_lu": _perspective_to_dict(_debate.li_lu),
            "munger": _perspective_to_dict(_debate.munger),
            "lynch": _perspective_to_dict(_debate.lynch),
        }
        try:
            print_debate(result.debate_perspectives, result.debate_result)
        except Exception:
            pass

    # ── 博弈论×技术融合 (GT Timing) ──
    if _gt_advice:
        try:
            from src.routing.gt_timing import print_gt_timing
            print_gt_timing(_gt_advice)
        except Exception:
            pass

    if _matched_models:
        result.mental_models = _matched_models
        try:
            print_munger_models(_matched_models, name)
        except Exception:
            pass

    if _t0 is not None:
        result.t0_result = _t0
        try:
            from src.output.step_output import print_t0
            print_t0(_t0)
        except Exception:
            pass
    elif not skip_t0:
        snapshot.data_gaps.append("[DATA_GAP] T+0")

    phase2_elapsed = (datetime.now() - t2_tick).total_seconds()

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: 裁决+仓位+风控 (~1s)
    # ═══════════════════════════════════════════════════════════════
    t3_tick = datetime.now()

    if _report is None:
        result.warnings.append("诊断数据缺失，无法裁决")
        return result

    # --- 3a: 裁决 ---
    _step += 1
    step_start(_step, "综合裁决", total=TOTAL)
    from src.routing.verdict import VerdictEngine
    verdict = orch.verdict_engine.judge(_report, weights_override=weights, mode="trading")
    result.verdict_score = verdict.score
    result.verdict_recommendation = verdict.recommendation
    result.verdict_confidence = verdict.confidence

    if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
        result.warnings.append(f"置信度偏低 ({verdict.confidence:.2f})")

    # 补齐 citations
    if _gt_profile and getattr(_gt_profile, "source_citations", None):
        _report.source_citations.extend(_gt_profile.source_citations)
    if _debate:
        _report.source_citations.append(make_citation(
            provider="perspective_analyzer", field="four_perspective_debate_timing",
            data_type="analyst_report", source_tier="T3", nature="speculation",
            confidence=0.45,
        ))
    if _matched_models:
        _report.source_citations.append(make_citation(
            provider="mental_model_matcher", field="munger_mental_models_timing",
            data_type="analyst_report", source_tier="T2", nature="interpretation",
            confidence=0.65,
        ))

    # 交叉校验
    if _gt_advice:
        if (_gt_advice.action in ("EXIT", "REDUCE")
                and verdict.recommendation in ("ADD", "BUY", "STRONG_BUY")):
            result.warnings.append(
                f"博弈卖点({_gt_advice.action}) vs 裁决({verdict.recommendation}) — 卖点优先"
            )
        if (_gt_advice.action == "ENTER"
                and verdict.recommendation in ("REDUCE", "SELL", "AVOID")):
            result.warnings.append(
                f"技术买点 vs 裁决({verdict.recommendation}) — 勿逆裁决"
            )
            _gt_advice.entry_allowed = False
            _gt_advice.action = "WAIT"

    step_done(
        "✅" if verdict.score >= 60 else ("🟡" if verdict.score >= 40 else "🔴"),
        f"{verdict.score:.0f}/100 {verdict.recommendation} 置信{verdict.confidence:.0%}"
    )
    from src.output.step_output import print_verdict
    try:
        print_verdict(verdict, None, None)
    except Exception:
        pass

    # --- 仓位 ---
    effective_cap = 0.80 * risk_mult * float(
        getattr(_gt_advice, 'size_hint', 1.0) if _gt_advice else 1.0
    )
    signal = orch.positioning.generate_signal(
        verdict,
        macro_cap=effective_cap,
        position_limits=position_limits,
        risk_multiplier=risk_mult * float(
            getattr(_gt_advice, 'size_hint', 1.0) if _gt_advice else 1.0
        ),
        name=name,
        extra=quote_dict,
        timing_result=_timing_result,
    )

    # 持仓卖点覆盖
    if held and _gt_advice and _gt_advice.action in ("EXIT", "REDUCE"):
        try:
            signal.action = "CLOSE" if _gt_advice.action == "EXIT" else "REDUCE"  # type: ignore[attr-defined]
            if _gt_advice.action == "EXIT":
                if hasattr(signal, "weight"):
                    signal.weight = 0.0  # type: ignore[attr-defined]
        except Exception:
            pass

    pos_stop = None
    if pos_snap:
        try:
            pos_stop = float(pos_snap.get("stop_price") or 0) or None
        except (TypeError, ValueError):
            pass
    if held and pos_stop and pos_stop > 0 and hasattr(signal, "suggested_stop"):
        try:
            signal.suggested_stop = pos_stop  # type: ignore[attr-defined]
        except Exception:
            pass

    result.signal_action = getattr(signal, "action", "?")
    result.signal_weight = float(getattr(signal, "weight", 0) or 0)
    result.sizing_detail = {
        "method": getattr(signal, "sizing_method", "tactics"),
        "macro_cap": effective_cap,
        "risk_multiplier": risk_mult,
        "timing_action": getattr(_gt_advice, 'action', '?') if _gt_advice else '?',
        "mode": "tactics",
    }

    # --- 风控 ---
    enriched = {"current_price": current_price}
    if pos_snap:
        enriched.update({
            "held": True, "entry_price": pos_snap.get("entry_price"),
            "stop_price": pos_stop or pos_snap.get("stop_price"),
            "quantity": pos_snap.get("quantity"),
            "position_loss_pct": loss_pct,
        })
    else:
        enriched["held"] = False
    if _gt_profile:
        enriched["game_theory_risks"] = list(getattr(_gt_profile, "risks", []) or [])
        enriched["dominant_player"] = getattr(_gt_profile, "dominant_player", "")
    if _gt_advice:
        enriched["timing_action"] = _gt_advice.action
        enriched["exit_urgency"] = _gt_advice.exit_urgency

    risk = orch.risk_ctrl.check(
        signal,
        market={"change_pct": getattr(_quote, "change_pct", 0)},
        portfolio=enriched,
        position_limits=position_limits,
    )
    result.risk_passed = getattr(risk, "passed", True)

    # --- 3b: 仓位 ---
    _step += 1
    step_start(_step, "仓位调度", total=TOTAL)
    step_done(
        "✅" if result.signal_weight > 0 else "🟡",
        f"{result.signal_action} {result.signal_weight:.1%} | "
        f"方法:{result.sizing_detail.get('method','?')}"
    )

    # --- 3c: 风控 ---
    _step += 1
    step_start(_step, "风控执行", total=TOTAL)
    step_done("✅" if result.risk_passed else "🔴", "通过" if result.risk_passed else "拦截")
    try:
        print_positioning(signal, result.sizing_detail)
        print_risk_control(risk)
    except Exception:
        pass

    phase3_elapsed = (datetime.now() - t3_tick).total_seconds()
    total_elapsed = (datetime.now() - t0_tick).total_seconds()

    # ═══════════════════════════════════════════════════════════════
    # 最终结论
    # ═══════════════════════════════════════════════════════════════
    _resolve_final_action(result, snapshot, _gt_advice, held)

    # 投资者画像摘要
    investor_line = ""
    if investor is not None:
        try:
            style = getattr(investor, 'trading_style', None)
            risk = getattr(investor, 'risk_profile', None)
            parts = []
            if style:
                parts.append(f"风格={style.value}")
            if risk:
                parts.append(f"风险={risk.value}")
            parts.append(f"仓位系数={risk_mult:.0%}")
            investor_line = " | ".join(parts)
        except Exception:
            pass

    # 凯利公式信息
    kelly_info = ""
    if result.sizing_detail:
        method = result.sizing_detail.get("method", "")
        if method and method not in ("linear_fallback", "unknown"):
            kelly_info = f"凯利({method})"

    # ATR 止损额外展示
    atr_info = ""
    if snapshot.atr_stop > 0 and snapshot.atr_stop != snapshot.suggested_stop:
        atr_info = f" ATR止损{snapshot.atr_stop:.2f}"

    print("\n" + "=" * 56)
    print(f"  ⚡ tactics 完成 ({total_elapsed:.1f}s)"
          f"{' [极速]' if skip_debate else ''}")
    if investor_line:
        print(f"  👤 {investor_line}")
    print(f"  {name} {symbol}  {current_price:.2f}  "
          f"({snapshot.change_pct:+.2f}%)")
    print(f"  情绪: {snapshot.sentiment_label} "
          f"军规: {'✅' if not _doctrine_warnings else '⚠️'+str(len(_doctrine_warnings))} | "
          f"裁决: {result.verdict_score:.0f}/100 {result.verdict_recommendation}")
    print(f"  状态: {snapshot.market_state} (conf {snapshot.market_state_confidence:.0%})")
    print(f"  动作: {result.action} | 仓位: {result.signal_weight:.1%}"
          f"{' | '+kelly_info if kelly_info else ''}"
          f" | 风控: {'PASS' if result.risk_passed else '⚠️'}")
    if snapshot.best_entry:
        be = snapshot.best_entry
        print(f"  入场: {be['type']} [{be['zone_low']:.2f}-{be['zone_high']:.2f}] "
              f"c={be['confidence']:.0%}")
    if snapshot.suggested_stop > 0:
        print(f"  止损: {snapshot.suggested_stop:.2f}{atr_info}", end="")
        if snapshot.target_prices and snapshot.target_prices[0] > 0:
            print(f" | 参考目标: {snapshot.target_prices[0]:.2f}/{snapshot.target_prices[1]:.2f} (非强制离场)")
        else:
            print()
    if snapshot.projected_target > 0:
        print(f"  投影止盈: {snapshot.projected_target:.2f}"
              + (" (接近目标不追单)" if snapshot.chase_blocked else ""))
    if snapshot.macd_kdj:
        print(f"  KDJ: {snapshot.macd_kdj.get('action')} "
              f"c={snapshot.macd_kdj.get('confidence', 0):.2f}")
    if snapshot.margin_balance:
        print(f"  融资: {snapshot.margin_balance:.1f}亿 {snapshot.margin_trend}"
              f"{' | 融券5日'+f'{snapshot.short_5d_pct:+.0f}%' if snapshot.short_5d_pct else ''}")
    if snapshot.sector_top_inflow:
        print(f"  板块: 流入TOP {snapshot.sector_top_inflow[0]}")
    if result.debate_result:
        print(f"  辩论: {result.debate_result.get('agreement_level', '?')} "
              f"评分{result.debate_result.get('avg_score', 0):.0f}")
    if result.warnings:
        print(f"  ⚠️  {', '.join(result.warnings[:5])}")
    print("=" * 56)

    result.confidence = verdict.confidence
    return result


# ═══════════════════════════════════════════════════════════════════
# Phase 1 输出
# ═══════════════════════════════════════════════════════════════════


def _print_snapshot(s: TacticalSnapshot) -> None:
    """格式化输出盘面全景 — 每维度完整展示，像 diagnose 管道一样清晰。"""
    HR = "─" * 60

    # ── 🌍 市场背景 ──
    label_emoji = {"fear": "😱", "greed": "🤑"}.get(s.sentiment_label, "😐")
    print(f"\n{'='*60}")
    print(f"  🌍 市场背景")
    print(f"{'='*60}")
    print(f"  情绪: {label_emoji} {s.sentiment_label.upper()}  "
          f"评分 {s.sentiment_score:.0f}/100")
    if s.market_breadth:
        print(f"  宽度: {s.market_breadth}")
    if s.global_market_summary:
        print(f"  全球: 🌏 {s.global_market_summary}")
    if s.market_state:
        basis = "指数" if (s.market_state_detail or {}).get("basis") == "index" else "标的"
        print(f"  状态: {s.market_state} (conf {s.market_state_confidence:.0%} 基于{basis})")
    print(f"  建议: {s.sentiment_advice}")

    # ── 📊 基本面 ──
    print(f"\n  {HR}")
    print(f"  📊 基本面诊断")
    print(f"  {HR}")
    pe_str = (f"PE(TTM) {s.pe_ttm:.1f}" if s.pe_ttm else "PE(TTM) 暂无")
    ind_str = (f"(行业参考 {s.industry_pe:.0f})" if s.industry_pe else "")
    roe_str = (f"ROE {s.roe:.1f}%" if s.roe else "ROE 暂无")
    print(f"  估值: {pe_str} {ind_str}  {roe_str}")
    # 三维评分 + 解读
    _score_bar = lambda v: "█" * int(v / 10) + "░" * (10 - int(v / 10))
    print(f"  价值 {_score_bar(s.value_score)} {s.value_score:.0f}/100  "
          f"质量 {_score_bar(s.quality_score)} {s.quality_score:.0f}/100  "
          f"动量 {_score_bar(s.momentum_score)} {s.momentum_score:.0f}/100")
    _interpret_value(s.value_score, "价值")
    _interpret_quality(s.quality_score, s.roe)
    _interpret_momentum(s.momentum_score, s.change_pct)

    # ── 📈 技术面 ──
    print(f"\n  {HR}")
    print(f"  📈 技术面 (6维)")
    print(f"  {HR}")
    dims = [
        ("趋势", s.trend_score, _trend_interpret(s.trend_score)),
        ("反转", s.reversal_score, _reversal_interpret(s.reversal_score)),
        ("量价", s.volume_score, _volume_interpret(s.volume_score)),
        ("波动", s.volatility_score, _vol_interpret(s.volatility_score)),
        ("均线", s.ma_score, _ma_interpret(s.ma_score)),
        ("打板", s.limit_up_score, _limit_up_interpret(s.limit_up_score)),
    ]
    for name, score, interp in dims:
        bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
        print(f"  {name:4s} {bar} {score:3.0f}/100  → {interp}")
    print(f"  {'综合':4s} {'='*20} {s.technical_composite:.0f}/100")
    if s.weekly_direction in ("BULL", "BEAR"):
        print(f"  周线方向: {'📈 ' if s.weekly_direction == 'BULL' else '📉 '}"
              f"{s.weekly_direction} (跨周期过滤)")

    # 入场信号详情
    if s.entry_signals:
        print(f"\n  🟢 入场信号 ({len(s.entry_signals)}个):")
        for es in s.entry_signals:
            print(f"     · {es['type']}: {es['description']}")
            print(f"       入场区间 [{es['zone_low']:.2f} — {es['zone_high']:.2f}]  置信度 {es['confidence']:.0%}")
    else:
        print(f"\n  🟢 入场信号: 暂无 — 尚未触发技术买点")

    # 出场信号详情
    if s.exit_signals:
        print(f"\n  🔴 出场信号 ({len(s.exit_signals)}个):")
        for xs in s.exit_signals:
            u = " ⚠️紧急!" if xs.get("urgency") == "URGENT" else ""
            print(f"     · {xs['type']}: {xs['description']}{u}")
            print(f"       出场区间 [{xs['zone_low']:.2f} — {xs['zone_high']:.2f}]  置信度 {xs['confidence']:.0%}")
    else:
        print(f"\n  🔴 出场信号: 暂无")

    # 最佳入场/止损/目标
    if s.best_entry:
        be = s.best_entry
        print(f"\n  🎯 最佳入场: {be['type']} [{be['zone_low']:.2f}—{be['zone_high']:.2f}] "
              f"置信度 {be['confidence']:.0%}")
        print(f"     {be['description']}")
    if s.suggested_stop > 0:
        stops = [f"建议止损 {s.suggested_stop:.2f}"]
        if s.atr_stop > 0 and abs(s.atr_stop - s.suggested_stop) > 0.01:
            stops.append(f"ATR止损 {s.atr_stop:.2f}")
        print(f"  🛑 {' | '.join(stops)}")
    if s.target_prices and s.target_prices[0] > 0:
        print(f"  🎯 参考目标: T1={s.target_prices[0]:.2f}  T2={s.target_prices[1]:.2f} (非强制离场)")
    if s.projected_target > 0:
        tag = " (接近目标不追单)" if s.chase_blocked else ""
        print(f"  📐 MM投影止盈: {s.projected_target:.2f}{tag}")

    # MACD+KDJ 五法 详细
    if s.macd_kdj:
        mk = s.macd_kdj
        print(f"\n  📐 MACD+KDJ 五法:")
        print(f"     动作: {mk.get('action')}  置信度 {mk.get('confidence', 0):.2f}")
        methods = mk.get("methods", []) or []
        if methods:
            print(f"     触发方法: {', '.join(methods)}")
        notes = mk.get("notes", []) or []
        if notes:
            for note in notes[:5]:
                print(f"     · {note}")
        # 数值
        vals = []
        for k in ["dif", "dea", "hist", "k", "d", "j"]:
            v = mk.get(k)
            if v is not None:
                vals.append(f"{k.upper()}={v:+.4f}" if k == "hist" else f"{k.upper()}={v:.2f}")
        if vals:
            print(f"     数值: {' | '.join(vals)}")

    # ── 💰 资金面 ──
    print(f"\n  {HR}")
    print(f"  💰 资金面")
    print(f"  {HR}")

    # 融资融券
    if s.margin_balance:
        trend_icon = {"increasing": "📈 增加", "decreasing": "📉 减少"}.get(s.margin_trend, "➡️ 持平")
        print(f"  融资余额: {s.margin_balance:.1f}亿  {trend_icon}  5日变化 {s.margin_5d_pct:+.1f}%")
        if s.short_balance:
            print(f"  融券余额: {s.short_balance:.2f}亿  5日变化 {s.short_5d_pct:+.1f}%")
        # 解读融资信号
        if s.margin_5d_pct < -5:
            print(f"     ⚠️ 融资5日大幅流出 — 杠杆资金撤退信号")
        elif s.margin_5d_pct < -2:
            print(f"     ⚠️ 融资5日小幅流出 — 短线杠杆偏谨慎")
        elif s.margin_5d_pct > 5:
            print(f"     📈 融资5日大幅流入 — 杠杆资金积极做多")
        elif s.margin_5d_pct > 2:
            print(f"     📈 融资5日小幅流入 — 杠杆资金偏乐观")
    else:
        print(f"  融资融券: 数据暂缺")
    if s.margin_alerts:
        for a in s.margin_alerts[:3]:
            print(f"     {a}")

    # 板块资金流向
    if s.sector_top_inflow:
        print(f"\n  板块资金流向 (主力净额):")
        print(f"    🟢 流入 TOP3: {', '.join(s.sector_top_inflow)}")
    if s.sector_top_outflow:
        print(f"    🔴 流出 TOP3: {', '.join(s.sector_top_outflow)}")
    if s.sector_inflow is not None:
        status = "🟢 标的板块今日净流入" if s.sector_inflow else "🔴 标的板块今日净流出"
        print(f"    {status}")

    # 博弈论摘要
    print(f"\n  博弈论:")
    print(f"    主导玩家: {s.dominant_player or '(未知)'}  "
          f"拥挤度: {s.crowding_score}/100  "
          f"{'✅ 可入场' if s.gt_entry_allowed else '⛔ 不建议入场'}")
    _interpret_crowding(s.crowding_score)
    if s.gt_rationale:
        print(f"    博弈依据:")
        for r in s.gt_rationale[:5]:
            print(f"      · {r}")

    # 持仓
    if s.held and s.position_entry:
        loss_str = f"{s.position_loss_pct:+.1%}"
        loss_icon = "🔴" if s.position_loss_pct < -0.05 else ("🟢" if s.position_loss_pct > 0.05 else "🟡")
        print(f"\n  📦 持仓状态: {loss_icon} 浮盈{loss_str}  "
              f"成本价 {s.position_entry:.2f}")

    # 数据缺口
    if s.data_gaps:
        print(f"\n  {'─'*60}")
        print(f"  📋 数据缺口:")
        for g in s.data_gaps[:5]:
            print(f"     {g}")
    print()


# ═══════════════════════════════════════════════════════════════════
# 解读辅助函数 — 将裸分数翻译为可读中文信号
# ═══════════════════════════════════════════════════════════════════


def _interpret_value(score: float, label: str = "价值"):
    """价值维度解读。"""
    if score >= 70:
        print(f"     ✅ {label}优秀 — PE显著低于行业/历史中位，估值有安全边际")
    elif score >= 50:
        print(f"     🟡 {label}适中 — PE在合理区间，无显著高估或低估")
    else:
        print(f"     🔴 {label}偏低 — PE偏高或处于历史高分位，估值无安全边际")


def _interpret_quality(score: float, roe):
    """质量维度解读。"""
    roe_s = f"ROE {roe:.1f}%" if roe else ""
    if score >= 70:
        print(f"     ✅ 质量优秀 {roe_s}— 高ROE+现金流扎实+盈利可验证")
    elif score >= 50:
        print(f"     🟡 质量一般 {roe_s}— 盈利尚可但存在纸面利润/现金流风险")
    else:
        print(f"     🔴 质量偏弱 {roe_s}— ROE持续性存疑或现金流质量差")


def _interpret_momentum(score: float, change_pct: float):
    """动量维度解读。"""
    chg = f"当日{change_pct:+.1f}%" if change_pct else ""
    if score >= 60:
        print(f"     📈 动量偏强 {chg}— 短期趋势向上，机构/北向可能流入")
    elif score >= 40:
        print(f"     🟡 动量中性 {chg}— 短期无明确方向，横盘整理中")
    else:
        print(f"     📉 动量偏弱 {chg}— 短期趋势向下，资金可能在流出")


def _trend_interpret(score: float) -> str:
    if score >= 70: return "强势上升通道，均线多头排列"
    if score >= 55: return "温和上行，均线修复中"
    if score >= 45: return "横盘震荡，无明确趋势"
    if score >= 30: return "弱势下行，均线空头排列"
    return "急跌通道，趋势严重破位"


def _reversal_interpret(score: float) -> str:
    if score >= 70: return "超卖+底背离+锤子线等反转信号叠加"
    if score >= 55: return "初步出现超卖/底背离迹象"
    if score >= 45: return "中性，无明确反转信号"
    if score >= 30: return "超买迹象，可能回调"
    return "RSI/KDJ严重超买，大概率见顶回落"


def _volume_interpret(score: float) -> str:
    if score >= 70: return "放量突破，量价配合良好"
    if score >= 55: return "温和放量，量价配合尚可"
    if score >= 45: return "平量，无显著量价背离"
    if score >= 30: return "缩量下跌或放量滞涨，量价背离"
    return "严重缩量或放量暴跌，量价关系恶化"


def _vol_interpret(score: float) -> str:
    if score >= 70: return "波动率收缩至低位，变盘窗口临近"
    if score >= 55: return "波动率适中偏低，风险可控"
    if score >= 45: return "波动率中性"
    if score >= 30: return "波动率偏高，短线风险加大"
    return "极端高波动，警惕短线资金博弈剧烈"


def _ma_interpret(score: float) -> str:
    if score >= 70: return "均线多头排列，MA5>MA10>MA20"
    if score >= 55: return "股价站上MA5，但均线系统未完全多头"
    if score >= 45: return "股价围绕均线震荡，方向不明"
    if score >= 30: return "跌破MA20，均线空头排列雏形"
    return "跌破MA60，均线系统完全空头排列"


def _limit_up_interpret(score: float) -> str:
    if score >= 70: return "涨停基因活跃，封板率高"
    if score >= 55: return "有一定涨停基因，偶尔封板"
    if score >= 45: return "打板属性中性"
    if score >= 30: return "炸板率高，追高风险大"
    return "缺乏涨停基因，非打板标的"


def _interpret_crowding(score: int):
    """拥挤度解读。"""
    if score >= 80:
        print("     🔴 极度拥挤 — 持仓高度集中，踩踏风险极大")
    elif score >= 70:
        print("     🟠 高度拥挤 — 新开仓减半，止损必须更紧")
    elif score >= 50:
        print("     🟡 中度拥挤 — 尚可入场但需控制仓位")
    elif score >= 30:
        print("     🟢 轻度拥挤 — 筹码分散，适合建仓")
    else:
        print("     🟢 不拥挤 — 无人关注时正是好时机")


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

# TechnicalAnalyzer 六维消费的 17 个技术因子 ID（对应 src/routing/technical.py 各维度列表）
_TECH_FACTOR_IDS: list[str] = [
    # 趋势 (trend)
    "macd_histogram", "dmi_direction", "ma_bias",
    # 反转 (reversal)
    "rsi_signal", "kdj_signal", "williams_r", "short_term_reversal",
    # 量价 (volume)
    "obv_divergence", "mfi_signal", "volume_ratio", "turnover_anomaly",
    # 波动 (volatility)
    "atr_percentile", "bollinger_position", "hv_percentile",
    # 均线 (ma)
    "ma_alignment", "ma_cross", "ma_support",
]


def _inject_technical_factors(
    panel: dict[str, pd.DataFrame],
    df: pd.DataFrame,
    symbol: str,
) -> dict[str, pd.DataFrame]:
    """把技术六维所需的因子帧注入 panel，使 TechnicalAnalyzer 六维真实打分。

    与 factor Registry 的用法一致：每个因子在宽面板（index=date,
    columns=stock_code）上通过 registry.compute(fid, panel) 计算，
    输出帧再以 fid 为键并回 panel。Registry 校验 columns_required，
    缺失输入时抛 SkipAlpha → 单因子跳过，实现优雅降级
    （例如 turnover_anomaly 在无换手率数据时被跳过，不影响量价维度其余因子）。

    Args:
        panel: 基础 OHLCV 宽面板（close/high/low/volume）
        df: 原始 K 线 DataFrame，用于补充 turnover 等扩展列
        symbol: 股票代码（宽面板列名）

    Returns:
        追加了 17 个技术因子帧的 panel（原 dict 就地扩展）。
    """
    import pandas as pd

    # 扩展字段：换手率（部分数据源提供）
    if "turnover" not in panel and df is not None and not getattr(df, "empty", True):
        turn_col = next(
            (c for c in ("turnover", "turnover_rate", "换手率") if c in df.columns),
            None,
        )
        if turn_col is not None:
            s = pd.to_numeric(df[turn_col], errors="coerce")
            panel["turnover"] = pd.DataFrame({symbol: s.values}, index=df.index)

    from src.factors.registry import get_default_registry
    registry = get_default_registry()
    for fid in _TECH_FACTOR_IDS:
        try:
            frame = registry.compute(fid, panel)
        except Exception as e:
            logger.debug("tactics factor %s skipped: %s", fid, e)
            continue
        if frame is not None and not frame.empty:
            panel[fid] = frame
    return panel


def _load_position_row(symbol: str) -> Optional[dict]:
    for p in [
        Path("data/positions.json"),
        Path.home() / ".hermes" / "baize" / "positions.json",
    ]:
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and symbol in raw:
            return raw[symbol]
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict) and str(row.get("symbol")) == symbol:
                    return row
    return None


def _pos_loss_pct(price: float, entry) -> float:
    try:
        e = float(entry or 0)
    except (TypeError, ValueError):
        return 0.0
    if e <= 0 or price <= 0:
        return 0.0
    return (float(price) - e) / e


def _extract_financial_doctrine_ctx(fin_list: list[dict], ctx: dict) -> None:
    """从预拉取的财务数据中提取 r032/r033/r034 军规上下文。内联实现，零网络。"""
    if not fin_list:
        return
    by_year: dict[int, dict] = defaultdict(lambda: {"roe": None, "ocf": 0.0, "np": 0.0})
    for f in fin_list:
        period = f.get("report_period", "")
        if not period or len(period) < 4:
            continue
        try:
            year = int(period[:4])
        except ValueError:
            continue
        is_q4 = "Q4" in period
        if is_q4 or by_year[year]["roe"] is None:
            roe = f.get("roe")
            if roe is not None:
                by_year[year]["roe"] = roe
        ocf = f.get("operating_cash_flow")
        if ocf is not None:
            by_year[year]["ocf"] += ocf
        np_ = f.get("net_profit")
        if np_ is not None:
            by_year[year]["np"] += np_

    sorted_years = sorted(by_year.keys())[-3:]
    ctx["roe_history"] = [
        by_year[y]["roe"] for y in sorted_years
        if by_year[y]["roe"] is not None
    ]
    ctx["operating_cash_flow_3y"] = sum(by_year[y]["ocf"] for y in sorted_years)
    ctx["net_profit_3y"] = sum(by_year[y]["np"] for y in sorted_years)


def _estimate_industry_pe(symbol: str) -> Optional[float]:
    """根据股票代码快速估算行业PE。T2级别，仅作参考。"""
    if symbol.startswith(("600", "601", "603", "605")):
        return 18.0  # 沪主板
    elif symbol.startswith("000") or symbol.startswith("002"):
        return 25.0  # 深主板/中小板
    elif symbol.startswith("300"):
        return 35.0  # 创业板
    elif symbol.startswith("688"):
        return 45.0  # 科创板
    return None


def _infer_stock_sector(symbol: str, name: str) -> str:
    """基于代码+名称推断行业板块。简化版，用于匹配板块资金流向。"""
    try:
        from src.industry.classifier import SectorClassifier
        sc = SectorClassifier()
        result = sc.classify(symbol, name)
        if result and result.sw1_name:
            return result.sw1_name
    except Exception:
        pass
    return ""


def _build_timing_question(snapshot: TacticalSnapshot) -> str:
    """根据盘面快照构造时机上下文问题，注入 Munger 模型匹配器。

    让匹配器知道这是短线买卖时机判断（非选股），匹配偏向：
    - 止损纪律 / 趋势判断 / 逆向思维 / 机会成本 等时机相关模型
    - 而非 护城河 / 管理层 / 复利 等选股相关模型

    关键：输出文本必须包含 _build_signals 中 timing 检测关键词，
    否则 timing_entry/exit/discipline/risk 信号族不会被激活。
    """
    parts = [
        # 基础上下文 — 触发短线模式
        "短线买卖时机判断",
        # 下列关键词直接触发 timing 信号族检测：
        # timing_entry 触发词: 入场|买点|抄底|建仓|突破|回踩|金叉
        # timing_exit 触发词: 出场|卖点|止盈|止损|破位|死叉|减仓|清仓
        # timing_disc 触发词: 时机确认|耐心等待|机会成本|逆向思维|纪律执行
        # timing_risk 触发词: 追高|接刀|博弈|频繁交易|恐慌抛售|FOMO
    ]

    # 趋势状态 → timing_entry / timing_exit
    if snapshot.trend_score >= 60:
        parts.append("追高买入突破金叉入场点确认")
    elif snapshot.trend_score <= 35:
        parts.append("下跌趋势抄底建仓止损纪律死叉减仓")
    else:
        parts.append("方向不明耐心等待时机确认")

    # 反转信号
    if snapshot.reversal_score >= 60:
        parts.append("超卖反弹抄底买点")
    elif snapshot.reversal_score <= 35:
        parts.append("超买回调止盈卖点出场")

    # 拥挤度
    if snapshot.crowding_score >= 70:
        parts.append("拥挤交易避免追高博弈")
    elif snapshot.crowding_score <= 30:
        parts.append("逆向思维恐慌买入机会成本")

    # 持仓状态
    if snapshot.held and snapshot.position_loss_pct < -0.05:
        parts.append("持仓浮亏止损还是持有接刀沉没成本纪律执行")

    # 入场/出场信号
    if snapshot.entry_signals:
        parts.append("技术买点入场金叉确认")
    if snapshot.exit_signals:
        parts.append("技术卖点出场死叉破位减仓")

    # 融资趋势
    if snapshot.margin_5d_pct < -5:
        parts.append("杠杆资金撤退去杠杆止损清仓")
    elif snapshot.margin_5d_pct > 5:
        parts.append("杠杆资金涌入追高FOMO博弈")

    # 波动率
    if snapshot.volatility_score <= 35:
        parts.append("高波动短线博弈频繁交易风险控制")

    # T+0 信号
    if snapshot.macd_kdj:
        action = snapshot.macd_kdj.get("action", "")
        if action == "ENTER":
            parts.append("金叉入场确认")
        elif action == "EXIT":
            parts.append("死叉离场减仓")

    return " ".join(parts)


def _perspective_to_dict(p) -> dict:
    """完整提取大师视角所有字段 — 确保 print_debate 有足够数据展示。"""
    if p is None:
        return {}
    if hasattr(p, "to_dict"):
        d = p.to_dict()
    elif hasattr(p, "model_dump"):
        d = p.model_dump()
    elif isinstance(p, dict):
        d = dict(p)
    else:
        d = {}
    # 补全 print_debate 需要的所有字段（从属性兜底）
    for attr, key in [
        ("score", "score"), ("recommendation", "recommendation"), ("verdict", "verdict"),
        ("methodology", "methodology"), ("one_line_thesis", "one_line_thesis"),
        ("unique_insight", "unique_insight"), ("bull_points", "bull_points"),
        ("bear_points", "bear_points"), ("key_concern", "key_concern"),
        ("qa_pairs", "qa_pairs"), ("questions_to_ask", "questions_to_ask"),
    ]:
        if key not in d or not d[key]:
            val = getattr(p, key, None) if not isinstance(p, dict) else None
            if val:
                d[key] = val
    return d


def _resolve_final_action(
    result: TacticsResult,
    snapshot: TacticalSnapshot,
    advice,
    held: bool,
) -> None:
    """整合所有信号，确定最终 action。"""
    # 卖点优先
    if advice and advice.action in ("EXIT", "REDUCE") and held:
        result.action = advice.action
        return

    # P2: 盈利阶梯加仓 (海龟金字塔启发) — 已持仓浮盈 ≥ PYRAMID_ADD_ATR_MULT×ATR、
    # 周线非 BEAR、无 URGENT 离场信号、博弈/KJD 放行时允许加仓。
    # 金字塔是与评分驱动 ADD 并存的补充通道，仅在基础动作为 HOLD/ADD 时生效
    # (REDUCE/EXIT 已由卖点优先 + rec 映射提前处理)。
    pyramid_add = False
    pyramid_atr_mult = 0.0
    if held and snapshot.atr > 0 and snapshot.position_entry:
        entry = float(snapshot.position_entry)
        if entry > 0 and snapshot.current_price > entry:
            pyramid_atr_mult = (snapshot.current_price - entry) / snapshot.atr
            no_exit = not (advice and advice.action in ("EXIT", "REDUCE"))
            no_urgent = not any(
                s.get("urgency") == "URGENT" for s in snapshot.exit_signals
            )
            no_bear = snapshot.weekly_direction != "BEAR"
            gt_ok = not advice or getattr(advice, "entry_allowed", True)
            kdj_ok = not (
                snapshot.macd_kdj
                and snapshot.macd_kdj.get("action") == "AVOID_ENTRY"
            )
            if (
                pyramid_atr_mult >= PYRAMID_ADD_ATR_MULT
                and no_exit and no_urgent and no_bear and gt_ok and kdj_ok
            ):
                pyramid_add = True

    rec = result.verdict_recommendation
    if rec in ("STRONG_BUY", "BUY"):
        result.action = "ENTER" if not held else "HOLD"
    elif rec == "ADD":
        result.action = "ENTER" if not held else "ADD"
    elif rec == "REDUCE":
        result.action = "REDUCE"
    elif rec in ("SELL", "AVOID"):
        result.action = "EXIT" if held else "WAIT"
    else:
        result.action = (
            getattr(advice, 'action', 'HOLD') if advice
            else ("HOLD" if held else "WAIT")
        )

    # P2: 浮盈阶梯加仓 — 把评分驱动的 HOLD 升级为 ADD (趋势延续金字塔加仓)
    if pyramid_add and result.action == "HOLD":
        result.action = "ADD"
        result.warnings.append(
            f"浮盈阶梯加仓: 浮盈≥{pyramid_atr_mult:.1f}×ATR, 趋势延续金字塔加仓(海龟启发)"
        )

    # 博弈阻止
    if advice and not getattr(advice, 'entry_allowed', True) and result.action == "ENTER":
        result.action = "WAIT"
        result.warnings.append("博弈论阻止入场 → WAIT")

    # KDJ 交叉验证
    if snapshot.macd_kdj:
        mk = snapshot.macd_kdj
        if mk.get("action") == "AVOID_ENTRY" and result.action == "ENTER":
            result.action = "WAIT"
            result.warnings.append("KDJ: AVOID_ENTRY → WAIT")

    # MM 投影目标位不追单 (P1-6) — 金字塔加仓豁免 (加已有盈利仓 ≠ 追新仓)
    if snapshot.chase_blocked and result.action in ("ENTER", "ADD"):
        if pyramid_add:
            result.warnings.append("浮盈阶梯加仓不受追单限制(已有盈利仓加仓)")
        else:
            result.action = "WAIT"
            result.warnings.append(f"接近MM投影目标位 {snapshot.projected_target:.2f} → 不追单")
