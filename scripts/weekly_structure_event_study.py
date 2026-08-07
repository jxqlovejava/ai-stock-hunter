#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周线结构事件研究 · 验证「周线规律」是否有历史边际。

数据来源: data/kline_cache 全部 *_{period}_daily.csv → 日线重采样周线(W-FRI)。
测试信号（来自 WealthClub10x 周线规律帖，可量化部分）:

  S1 周线多头排列+发散  : MA5w > MA10w > MA20w 且 MA5w/MA10w 均向上
  S2 周线放量突破       : 收盘突破前26周平台高 + 周量 > 1.5×前13周均量
  S3 突破回踩再启动(二波): 近52周内出现过S2 → 回踩至MA10w附近(低点≤MA10w×1.02且收回收复) + 缩量(周量≤前13周均量)

约束（与 event_study_macd_kdj.py 对齐）:
  - 入场: 信号周次周开盘（T+1 可交易），涨停无法买入顺延最多 2 周
  - 出场: 固定持有 H 周，按持有到期周开盘价
  - 成本: AShareCostCalculator（佣金+印花税+过户+滑点）
  - 涨跌停: 主板 10% / 创业板科创板 20% / 北交所 30% / ST 5%
  - 对照: 无条件基准 = 全样本所有周的下 H 周收益（随机买入 A 股的期望）

用法:
  .venv/bin/python scripts/weekly_structure_event_study.py
  .venv/bin/python scripts/weekly_structure_event_study.py --max-symbols 50 --workers 2
  .venv/bin/python scripts/weekly_structure_event_study.py --horizons 4,8,13,26 --cooldown 4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.cost_model import AShareCostCalculator  # noqa: E402

KLINE_DIR = ROOT / "data" / "kline_cache"
OUT_DIR = ROOT / "output"

WEEKLY_MIN_BARS = 60          # 需要 MA20(20) + 平台(26) + 回溯(52) 的预热
S2_PLATFORM_W = 26            # 平台高点回看周数（半年）
S2_VOL_RATIO = 1.5            # 突破量能阈值：周量 > N × 前13周均量
S3_LOOKBACK_W = 52            # "近一年内有过突破"回看周数
S3_RETRACE_BAND = 0.02        # 回踩触线带：低点 ≤ MA10w × (1+2%)
ENTRY_DEFER_MAX_W = 2         # 涨停入场顺延最大周数


def limit_pct(symbol: str, name: str = "") -> float:
    """涨跌停幅度。"""
    s = symbol.split(".")[0]
    nm = name or ""
    if "ST" in nm.upper() or nm.startswith("*"):
        return 0.05
    if s.startswith(("300", "301", "688", "689")):
        return 0.20
    if s.startswith(("8", "4")):  # 北交所
        return 0.30
    return 0.10


def board_of(symbol: str) -> str:
    s = symbol.split(".")[0]
    if s.startswith(("300", "301")):
        return "gem_创业板"
    if s.startswith(("688", "689")):
        return "star_科创板"
    if s.startswith(("8", "4")):
        return "bj_北交所"
    if s.startswith("6"):
        return "main_sh_主板沪"
    if s.startswith(("0", "3")):
        return "main_sz_主板深"
    return "other"


def round_price(p: float) -> float:
    return round(p + 1e-10, 2)


def mean_dollar_volume(df: pd.DataFrame, lookback: int = 120) -> float:
    if df.empty or "close" not in df.columns or "volume" not in df.columns:
        return 0.0
    c = df["close"].astype(float).tail(lookback)
    v = df["volume"].astype(float).tail(lookback)
    m = (c * v).replace([np.inf, -np.inf], np.nan).dropna()
    if m.empty:
        return 0.0
    return float(m.mean())


def is_limit_up(high: float, close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0 or not math.isfinite(prev_close):
        return False
    lim = round_price(prev_close * (1.0 + pct))
    return high >= lim * 0.999 and close >= lim * 0.997


def resample_weekly(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """日线 → 周线(W-FRI)。返回带完整周标签的 DataFrame 或 None。

    - open=周首日开盘, high=周最高, low=周最低, close=周末日收盘, volume=周量合计
    - 丢弃最后一根未完整周（末周交易日不足 5 天视为进行中/跨年残缺周）
    """
    if df.empty or len(df) < 10:
        return None
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").set_index("date")
    for col in ("open", "high", "low", "close", "volume"):
        if col not in d.columns:
            return None
    # 末周完整性检查：最后一根日线的星期是否等于其所在周的最后交易日
    last_day = d.index[-1]
    last_week = d.resample("W-FRI").last().index[-1]
    partial = last_day < last_week  # 数据止于周中 → 末周残缺
    wk = d.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    if partial:
        wk = wk.iloc[:-1]
    return wk.dropna()


def compute_signals(wk: pd.DataFrame) -> dict[str, pd.Series]:
    """基于周线的三个布尔信号 Series（index=周标签）。"""
    close = wk["close"]
    vol = wk["volume"]

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()

    # S1 多头排列 + 发散
    s1 = (
        (ma5 > ma10)
        & (ma10 > ma20)
        & (ma5.diff() > 0)
        & (ma10.diff() > 0)
    )

    # S2 放量突破前26周平台高
    platform_high = close.rolling(S2_PLATFORM_W).max().shift(1)
    vol_ma = vol.rolling(13).mean().shift(1)
    s2 = (close > platform_high) & (vol > S2_VOL_RATIO * vol_ma)

    # S3 突破后回踩缩量企稳（第二波）
    # "近52周内出现过突破" → 用 S2 布尔做过去窗口 any
    breakout_any_52 = (
        s2.fillna(False).rolling(S3_LOOKBACK_W, min_periods=1).max().shift(1) > 0
    )
    retrace_touch = wk["low"] <= ma10 * (1 + S3_RETRACE_BAND)   # 低点触及 MA10 附近
    reclaim = close >= ma10                                       # 收盘收回 MA10 上方
    shrink = vol <= vol_ma                                        # 缩量
    s3 = breakout_any_52 & retrace_touch & reclaim & shrink

    return {"S1": s1, "S2": s2, "S3": s3}


@dataclass
class TradeResult:
    symbol: str
    signal: str
    signal_date: str
    entry_date: str
    exit_date: str
    hold_weeks: int
    entry_px: float
    exit_px: float
    gross_ret: float
    net_ret: float
    cost_pct: float
    board: str = ""
    size_bucket: str = ""
    dollar_vol: float = 0.0
    skipped: bool = False
    skip_reason: str = ""


def _process_one(args: tuple) -> dict:
    path_str, horizons, qty, size_bucket, cooldown = args
    path = Path(path_str)
    symbol = path.name.split("_")[0]
    board = board_of(symbol)
    try:
        raw = pd.read_csv(path)
        if "date" not in raw.columns:
            return {"symbol": symbol, "error": "no_date", "trades": [], "baseline": []}
        raw["date"] = pd.to_datetime(raw["date"])
        wk = resample_weekly(raw)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "trades": [], "baseline": []}

    if wk is None or len(wk) < WEEKLY_MIN_BARS:
        return {"symbol": symbol, "error": "insufficient", "trades": [], "baseline": []}

    dvol = mean_dollar_volume(raw)
    signals = compute_signals(wk)

    opens = wk["open"].astype(float).to_numpy()
    highs = wk["high"].astype(float).to_numpy()
    closes = wk["close"].astype(float).to_numpy()
    dates = wk.index.strftime("%Y-%m-%d").to_numpy()
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]
    lp = limit_pct(symbol)
    cost = AShareCostCalculator()

    n = len(wk)
    max_h = max(horizons)
    trades: list[dict] = []
    baselines: list[dict] = []

    # 无条件基准：任意参考周 → 次周开盘买入（与信号入场时点同构），持有 H 周
    for h in horizons:
        for i in range(0, n - h - 1):
            entry_px = float(opens[i + 1])
            exit_px = float(opens[i + 1 + h])
            if entry_px <= 0 or exit_px <= 0:
                continue
            gross = exit_px / entry_px - 1.0
            roundtrip = cost.calc_roundtrip_cost(symbol, entry_px, exit_px, qty)
            baselines.append(
                {
                    "symbol": symbol,
                    "hold_weeks": h,
                    "net_ret": gross - roundtrip["roundtrip_pct"],
                    "board": board,
                    "size_bucket": size_bucket,
                }
            )

    # 信号事件（带冷却，降低连续同趋势周重复计数）
    last_signal_week: dict[str, int] = {}
    for sig_name, sig in signals.items():
        idx = np.flatnonzero(sig.fillna(False).to_numpy())
        for i in idx:
            i = int(i)
            if i >= n - 1:
                continue
            # 冷却：同信号 4 周内不重复入场
            if cooldown > 0 and i - last_signal_week.get(sig_name, -10 ** 6) < cooldown:
                continue

            # 找可入场周：信号次周起，顺延最多 ENTRY_DEFER_MAX_W 周
            entry_i = None
            for j in range(i + 1, min(i + 1 + ENTRY_DEFER_MAX_W, n)):
                if is_limit_up(highs[j], closes[j], prev_closes[j], lp):
                    continue
                if opens[j] <= 0 or not math.isfinite(opens[j]):
                    continue
                entry_i = j
                break
            if entry_i is None:
                trades.append(
                    asdict(
                        TradeResult(
                            symbol=symbol,
                            signal=sig_name,
                            signal_date=str(dates[i]),
                            entry_date="",
                            exit_date="",
                            hold_weeks=0,
                            entry_px=0,
                            exit_px=0,
                            gross_ret=0,
                            net_ret=0,
                            cost_pct=0,
                            board=board,
                            size_bucket=size_bucket,
                            dollar_vol=dvol,
                            skipped=True,
                            skip_reason="limit_up_or_no_entry",
                        )
                    )
                )
                continue

            last_signal_week[sig_name] = i
            entry_px = float(opens[entry_i])

            for h in horizons:
                exit_i = entry_i + h
                if exit_i >= n:
                    continue
                exit_px = float(opens[exit_i])
                if exit_px <= 0:
                    continue
                gross = exit_px / entry_px - 1.0
                roundtrip = cost.calc_roundtrip_cost(symbol, entry_px, exit_px, qty)
                trades.append(
                    asdict(
                        TradeResult(
                            symbol=symbol,
                            signal=sig_name,
                            signal_date=str(dates[i]),
                            entry_date=str(dates[entry_i]),
                            exit_date=str(dates[exit_i]),
                            hold_weeks=h,
                            entry_px=round(entry_px, 4),
                            exit_px=round(exit_px, 4),
                            gross_ret=round(gross, 6),
                            net_ret=round(gross - roundtrip["roundtrip_pct"], 6),
                            cost_pct=round(roundtrip["roundtrip_pct"], 6),
                            board=board,
                            size_bucket=size_bucket,
                            dollar_vol=dvol,
                        )
                    )
                )

    return {"symbol": symbol, "error": "", "trades": trades, "baseline": baselines}


def stats(xs: list[dict], key: str = "net_ret") -> dict:
    vals = [float(x.get(key)) for x in xs if x.get(key) is not None]
    if not vals:
        return {"n": 0}
    a = np.array(vals)
    return {
        "n": int(len(a)),
        "mean": float(np.mean(a)),
        "median": float(np.median(a)),
        "win_rate": float(np.mean(a > 0)),
        "p25": float(np.percentile(a, 25)),
        "p75": float(np.percentile(a, 75)),
        "std": float(np.std(a)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=str, default="4,8,13,26")
    ap.add_argument("--cooldown", type=int, default=4, help="同信号最小间隔周数")
    ap.add_argument("--max-symbols", type=int, default=0, help="0=全部")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--qty", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "weekly_structure_event_study.md")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    files = sorted(KLINE_DIR.glob("*_daily.csv"))
    if args.max_symbols > 0:
        files = files[: args.max_symbols]

    print(f"标的文件: {len(files)} | horizons={horizons} | cooldown={args.cooldown}w | workers={args.workers}")
    if not files:
        print("无 kline_cache，退出")
        return 1

    # Pass-1: 成交额规模分位
    print("Pass-1: 计算日均成交额分位…")
    dvol_map: dict[str, float] = {}
    for f in files:
        sym = f.name.split("_")[0]
        try:
            raw = pd.read_csv(f, usecols=lambda c: c.lower() in ("date", "close", "volume"))
            dvol_map[sym] = mean_dollar_volume(raw)
        except Exception:
            dvol_map[sym] = 0.0
    vals = np.array([v for v in dvol_map.values() if v > 0])
    if len(vals) >= 4:
        q1, q2, q3 = np.percentile(vals, [25, 50, 75])
    else:
        q1 = q2 = q3 = 0.0

    def size_label(v: float) -> str:
        if v <= 0:
            return "Q?_unknown"
        if v <= q1:
            return "Q1_低活跃/小微"
        if v <= q2:
            return "Q2_中低"
        if v <= q3:
            return "Q3_中高"
        return "Q4_高活跃/大盘代理"

    size_map = {s: size_label(v) for s, v in dvol_map.items()}
    print(f"  成交额分位阈值: Q1={q1:.0f} Q2={q2:.0f} Q3={q3:.0f}")

    tasks = [
        (
            str(f),
            horizons,
            args.qty,
            size_map.get(f.name.split("_")[0], "Q?_unknown"),
            args.cooldown,
        )
        for f in files
    ]
    results = []
    if args.workers <= 1:
        for t in tasks:
            results.append(_process_one(t))
            if len(results) % 100 == 0:
                print(f"  progress {len(results)}/{len(tasks)}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_process_one, t): t[0] for t in tasks}
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 100 == 0:
                    print(f"  progress {done}/{len(tasks)}")

    all_trades: list[dict] = []
    all_baseline: list[dict] = []
    n_symbols_used = 0
    errors = 0
    for r in results:
        if r.get("error") and r["error"] not in ("", "insufficient", "no_date"):
            errors += 1
        if r.get("trades") or r.get("baseline"):
            n_symbols_used += 1
        all_trades.extend(r.get("trades") or [])
        all_baseline.extend(r.get("baseline") or [])

    # 统计汇总
    active = [t for t in all_trades if not t.get("skipped")]
    by_sig = {s: [t for t in active if t["signal"] == s] for s in ("S1", "S2", "S3")}
    base_by_h = {h: [b for b in all_baseline if b["hold_weeks"] == h] for h in horizons}

    # 分层基准：同规模/板块的随机买入期望（信号分层对比的公平基准）
    base_by_size = {str(h): _stratum(all_baseline, "size_bucket", h) for h in horizons}
    base_by_board = {str(h): _stratum(all_baseline, "board", h) for h in horizons}

    summary = {
        "n_files": len(files),
        "n_symbols_used": n_symbols_used,
        "n_errors": errors,
        "horizons": horizons,
        "cooldown": args.cooldown,
        "n_trades_active": len(active),
        "n_skipped": len(all_trades) - len(active),
        "skip_rate": (len(all_trades) - len(active)) / max(len(all_trades), 1),
        "baseline_by_horizon": {str(h): stats(base_by_h[h]) for h in horizons},
        "baseline_by_size": base_by_size,
        "baseline_by_board": base_by_board,
        "by_signal": {},
    }
    for s in ("S1", "S2", "S3"):
        ts = by_sig[s]
        summary["by_signal"][s] = {
            "n_signals": len(ts),
            "by_horizon": {str(h): stats([t for t in ts if t["hold_weeks"] == h]) for h in horizons},
            "by_board_h13": _stratum(ts, "board", 13),
            "by_size_h13": _stratum(ts, "size_bucket", 13),
        }

    # 写 JSON + MD
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    json_path.write_text(
        json.dumps({"summary": summary, "sample_trades": all_trades[:200]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def pct(x):
        if x is None or np.isnan(x):
            return "n/a"
        return f"{x*100:+.2f}%"

    lines = [
        "# 周线结构事件研究 · 验证「周线规律」历史边际",
        "",
        f"- 样本: {n_symbols_used} 只有效标的 / {len(files)} 缓存文件 · 日线重采样周线(W-FRI)",
        f"- 入场: 信号次周开盘（涨停顺延≤{ENTRY_DEFER_MAX_W}周）· T+1",
        f"- 成本: 佣金万2.5+最低5 + 印花税千0.5卖 + 过户 + 滑点千1（往返）",
        f"- 持有: {horizons} 周 · 同信号冷却 {args.cooldown} 周",
        f"- 有效交易: {summary['n_trades_active']} · 跳过(涨停等): {summary['n_skipped']} "
        f"({pct(summary['skip_rate'])})",
        "",
        "## 信号定义",
        "",
        "| 信号 | 定义 |",
        "|------|------|",
        f"| S1 多头排列+发散 | MA5w>MA10w>MA20w 且 MA5w/MA10w 均向上 |",
        f"| S2 放量突破 | 收盘突破前{S2_PLATFORM_W}周平台高 + 周量>{S2_VOL_RATIO}×前13周均量 |",
        f"| S3 突破回踩二波 | 近{S3_LOOKBACK_W}周内有过S2 → 回踩至MA10w(低点≤MA10w×{1+S3_RETRACE_BAND:.2f})且收回 + 缩量 |",
        "",
        "## 无条件基准（随机买入 A 股的期望 · 扣成本）",
        "",
        "| 持有周 | N | 净均值 | 净中位 | 胜率 |",
        "|--------|---|--------|--------|------|",
    ]
    for h in horizons:
        st = summary["baseline_by_horizon"][str(h)]
        if not st.get("n"):
            continue
        lines.append(
            f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |"
        )

    # 分层基准（13周）：信号分层对比的公平基准
    lines += [
        "",
        "## 分层基准（持有13周 · 扣成本 · 同规模/板块随机买入）",
        "",
        "> 信号分层超额应以同段基准衡量，而非全体基准。",
        "",
        "**按规模/活跃度**",
        "",
        "| 分位 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary["baseline_by_size"].get("13") or {}).items():
        if not st.get("n"):
            continue
        lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")
    lines += [
        "",
        "**按板块**",
        "",
        "| 板块 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary["baseline_by_board"].get("13") or {}).items():
        if not st.get("n"):
            continue
        lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    for s, sname in (("S1", "多头排列+发散"), ("S2", "放量突破"), ("S3", "突破回踩二波")):
        lines += [
            "",
            f"## {s} {sname} · 扣成本净收益 vs 基准",
            "",
            "| 持有周 | N | 净均值 | 净中位 | 胜率 | 基准均值 | 超额 |",
            "|--------|---|--------|--------|------|----------|------|",
        ]
        sig = summary["by_signal"][s]
        for h in horizons:
            st = sig["by_horizon"][str(h)]
            if not st.get("n"):
                continue
            base = summary["baseline_by_horizon"][str(h)]
            bmean = base.get("mean", 0.0) or 0.0
            excess = (st["mean"] or 0.0) - bmean
            lines.append(
                f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | "
                f"{pct(st['win_rate'])} | {pct(bmean)} | {pct(excess)} |"
            )
        lines += [
            "",
            f"### {s} 分层（持有13周 · 扣成本）",
            "",
            "**板块**",
            "",
            "| 板块 | N | 净均值 | 净中位 | 胜率 |",
            "|------|---|--------|--------|------|",
        ]
        for k, st in (sig.get("by_board_h13") or {}).items():
            if not st.get("n"):
                continue
            lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")
        lines += [
            "",
            "**规模/活跃度（日均成交额四分位）**",
            "",
            "| 分位 | N | 净均值 | 净中位 | 胜率 |",
            "|------|---|--------|--------|------|",
        ]
        for k, st in (sig.get("by_size_h13") or {}).items():
            if not st.get("n"):
                continue
            lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    lines += [
        "",
        "## 结论边界",
        "",
        "- 教学规则 confidence 上限 0.5；本结果为历史事件统计，**非实盘期望**。",
        "- 未建模：停牌、财报真空、指数/大盘过滤、突破后已透支涨幅的时序重复（冷却降低但未消除）。",
        "- 重采样丢弃残缺末周；缓存股票池为已覆盖标的，存在幸存者偏差。",
        f"- 原始 JSON: `{json_path.name}`",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))
    print(f"\n报告: {args.out}")
    print(f"JSON: {json_path}")
    return 0


def _stratum(ts: list[dict], key: str, hold: int) -> dict:
    """按 key 分层（固定持有 hold 周）。"""
    buckets: dict[str, list] = {}
    for t in ts:
        if t.get("hold_weeks") != hold:
            continue
        b = str(t.get(key) or "unknown")
        buckets.setdefault(b, []).append(t)
    return {k: stats(v) for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))}


if __name__ == "__main__":
    raise SystemExit(main())
