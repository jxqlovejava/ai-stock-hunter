#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""突破质量事件研究 · 验证 0xToni「四假突破形态」是否可回避追突破损失。

数据来源: data/kline_cache → 日线重采样周线(W-FRI)。
在周线放量突破(S2: 收盘>前26周平台高 且 周量>1.5×前13周均量)发生的**当周**，
仅用当周数据(无前视)把突破分类为:

  low_quality  假突破①②: 当周涨幅<3% (放量滞涨) 或 上影/振幅>50% (长上影)
                         或 收盘位置(close-low)/(high-low) < 0.70 (盘中突破收盘跌回)
  high_quality 其余       : 收盘站稳+涨幅健康 (真突破的"收盘站稳"条件)

对比两组的前视收益。若 high 组显著优于 low 组，则"识别假突破后回避"被数据验证。

另加事后描述性验证: failed_breakout = 突破后13周内收盘跌破平台高(假突破③④结果)，
显示"回避失败突破"能避免多大的下行（此分类用未来信息，仅作确认，不作入场信号）。

约束: 入场=信号次周开盘(T+1, 涨停顺延≤2周), 出场=持有H周到期开盘,
成本=AShareCostCalculator 往返。对照=无条件基准(任一周次周开盘买入持H周)。

用法:
  .venv/bin/python scripts/breakout_quality_study.py
  .venv/bin/python scripts/breakout_quality_study.py --max-symbols 300 --workers 4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.cost_model import AShareCostCalculator  # noqa: E402

KLINE_DIR = ROOT / "data" / "kline_cache"
OUT_DIR = ROOT / "output"

WEEKLY_MIN_BARS = 60
PLATFORM_W = 26
VOL_RATIO = 1.5
FAILED_LOOKBACK_W = 13
LOW_GAIN = 0.03
LOW_SHADOW = 0.50
LOW_CLOSE_POS = 0.70


def limit_pct(symbol: str) -> float:
    s = symbol.split(".")[0]
    if s.startswith(("300", "301", "688", "689")):
        return 0.20
    if s.startswith(("8", "4")):
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
    return float(m.mean()) if not m.empty else 0.0


def is_limit_up(high: float, close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0 or not math.isfinite(prev_close):
        return False
    lim = round_price(prev_close * (1.0 + pct))
    return high >= lim * 0.999 and close >= lim * 0.997


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame | None:
    if df.empty or len(df) < 10:
        return None
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").set_index("date")
    if not all(c in d.columns for c in ("open", "high", "low", "close", "volume")):
        return None
    last_day = d.index[-1]
    last_week = d.resample("W-FRI").last().index[-1]
    partial = last_day < last_week
    wk = d.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    if partial:
        wk = wk.iloc[:-1]
    return wk.dropna()


def _process_one(args: tuple) -> dict:
    path_str, horizons, size_bucket = args
    path = Path(path_str)
    symbol = path.name.split("_")[0]
    board = board_of(symbol)
    try:
        raw = pd.read_csv(path)
        raw["date"] = pd.to_datetime(raw["date"])
        wk = resample_weekly(raw)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "trades": [], "baseline": []}

    if wk is None or len(wk) < WEEKLY_MIN_BARS:
        return {"symbol": symbol, "error": "insufficient", "trades": [], "baseline": []}

    dvol = mean_dollar_volume(raw)
    opens = wk["open"].astype(float).to_numpy()
    highs = wk["high"].astype(float).to_numpy()
    lows = wk["low"].astype(float).to_numpy()
    closes = wk["close"].astype(float).to_numpy()
    vols = wk["volume"].astype(float).to_numpy()
    dates = wk.index.strftime("%Y-%m-%d").to_numpy()
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]
    lp = limit_pct(symbol)
    cost = AShareCostCalculator()
    n = len(wk)

    close_s = pd.Series(closes)
    platform_high_s = close_s.rolling(PLATFORM_W).max().shift(1)
    vol_ma_s = pd.Series(vols).rolling(13).mean().shift(1)
    s2 = (
        (close_s > platform_high_s)
        & (pd.Series(vols) > VOL_RATIO * vol_ma_s)
        & (vol_ma_s > 0)
    ).to_numpy()

    trades: list[dict] = []
    baselines: list[dict] = []
    last_px = float(closes[-1]) if closes[-1] > 0 else 10.0
    rt = cost.calc_roundtrip_cost(symbol, last_px, last_px, 1000)
    cost_pct = float(rt["roundtrip_pct"])

    # 无条件基准: 任一周 → 次周开盘买入持 H 周
    for h in horizons:
        for i in range(n - h - 1):
            e, x = float(opens[i + 1]), float(opens[i + 1 + h])
            if e > 0 and x > 0:
                baselines.append({"hold_weeks": h, "net_ret": x / e - 1.0 - cost_pct,
                                  "board": board, "size_bucket": size_bucket})

    for i in range(n - 1):
        if not bool(s2[i]):
            continue
        # 入场: 次周开盘, 涨停顺延≤2周
        entry_i = None
        for j in range(i + 1, min(i + 1 + 2, n)):
            if is_limit_up(highs[j], closes[j], prev_closes[j], lp):
                continue
            if opens[j] <= 0 or not math.isfinite(opens[j]):
                continue
            entry_i = j
            break
        if entry_i is None:
            continue
        entry_px = float(opens[entry_i])

        # ── 突破当周质量分类 (无前视, 仅用当周数据) ──
        rng = highs[i] - lows[i]
        close_pos = (closes[i] - lows[i]) / rng if rng > 0 else 1.0
        gain = (closes[i] - opens[i]) / opens[i] if opens[i] > 0 else 0.0
        upper_shadow = (highs[i] - closes[i]) / rng if rng > 0 else 0.0
        low_q = gain < LOW_GAIN or upper_shadow > LOW_SHADOW or close_pos < LOW_CLOSE_POS

        # ── 事后失败判定 (用未来信息, 仅描述性) ──
        level = float(platform_high_s.iloc[i])
        failed = False
        for k in range(i + 1, min(i + 1 + FAILED_LOOKBACK_W, n)):
            if closes[k] < level:
                failed = True
                break

        qkey = "low" if low_q else "high"
        for h in horizons:
            exit_i = entry_i + h
            if exit_i >= n:
                continue
            x = float(opens[exit_i])
            if x <= 0:
                continue
            trades.append({
                "symbol": symbol, "signal_date": str(dates[i]),
                "entry_date": str(dates[entry_i]), "hold_weeks": h,
                "net_ret": round(x / entry_px - 1.0 - cost_pct, 6),
                "quality": qkey, "failed": failed,
                "close_pos": round(close_pos, 3), "gain": round(gain, 4),
                "upper_shadow": round(upper_shadow, 3),
                "board": board, "size_bucket": size_bucket,
            })

    return {"symbol": symbol, "error": "", "trades": trades, "baseline": baselines}


def stats(xs: list[dict], key: str = "net_ret") -> dict:
    vals = [float(x.get(key)) for x in xs if x.get(key) is not None]
    if not vals:
        return {"n": 0}
    a = np.array(vals)
    return {
        "n": int(len(a)), "mean": float(np.mean(a)), "median": float(np.median(a)),
        "win_rate": float(np.mean(a > 0)),
        "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75)),
        "std": float(np.std(a)),
    }


def stratum(ts: list[dict], key: str, hold: int) -> dict:
    buckets: dict[str, list] = {}
    for t in ts:
        if t.get("hold_weeks") != hold:
            continue
        b = str(t.get(key) or "unknown")
        buckets.setdefault(b, []).append(t)
    return {k: stats(v) for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=str, default="4,8,13,26")
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "breakout_quality_study.md")
    args = ap.parse_args()
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    files = sorted(KLINE_DIR.glob("*_daily.csv"))
    if args.max_symbols > 0:
        files = files[: args.max_symbols]
    print(f"标的: {len(files)} | horizons={horizons} | workers={args.workers}")
    if not files:
        print("无 kline_cache")
        return 1

    # Pass-1: 成交额规模分位
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
    print(f"  规模分位: Q1={q1:.0f} Q2={q2:.0f} Q3={q3:.0f}")

    tasks = [(str(f), horizons, size_map.get(f.name.split("_")[0], "Q?_unknown")) for f in files]
    results = []
    if args.workers <= 1:
        for t in tasks:
            results.append(_process_one(t))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_process_one, t): t[0] for t in tasks}
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 300 == 0:
                    print(f"  progress {done}/{len(tasks)}")

    all_trades: list[dict] = []
    all_baseline: list[dict] = []
    n_used = 0
    errors = 0
    for r in results:
        if r.get("error") and r["error"] not in ("", "insufficient"):
            errors += 1
        if r.get("trades") or r.get("baseline"):
            n_used += 1
        all_trades.extend(r.get("trades") or [])
        all_baseline.extend(r.get("baseline") or [])

    base_by_h = {h: stats([b for b in all_baseline if b["hold_weeks"] == h]) for h in horizons}
    base_by_size = {str(h): stratum(all_baseline, "size_bucket", h) for h in horizons}

    by_q = {"low": [t for t in all_trades if t["quality"] == "low"],
            "high": [t for t in all_trades if t["quality"] == "high"]}
    by_fail = {"failed": [t for t in all_trades if t["failed"]],
               "held": [t for t in all_trades if not t["failed"]]}

    summary = {
        "n_files": len(files), "n_symbols_used": n_used, "n_errors": errors,
        "horizons": horizons, "n_trades": len(all_trades),
        "low_share": len(by_q["low"]) / max(len(all_trades), 1),
        "baseline_by_horizon": {str(h): base_by_h[h] for h in horizons},
        "baseline_by_size": base_by_size,
        "by_quality": {q: {"by_horizon": {str(h): stats([t for t in ts if t["hold_weeks"] == h]) for h in horizons},
                           "by_size_h13": stratum(ts, "size_bucket", 13),
                           "by_board_h13": stratum(ts, "board", 13)} for q, ts in by_q.items()},
        "by_failed": {q: {"by_horizon": {str(h): stats([t for t in ts if t["hold_weeks"] == h]) for h in horizons}} for q, ts in by_fail.items()},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    json_path.write_text(json.dumps({"summary": summary, "sample_trades": all_trades[:200]}, ensure_ascii=False, indent=2), encoding="utf-8")

    def pct(x):
        if x is None or np.isnan(x):
            return "n/a"
        return f"{x*100:+.2f}%"

    lines = [
        "# 突破质量事件研究 · 验证「四假突破形态」能否回避追突破损失",
        "",
        f"- 样本: {n_used} 只有效标的 / {len(files)} 缓存 · 周线重采样",
        "- 信号: 周线放量突破 S2 (收盘>前26周平台高 + 周量>1.5×前13周均量)",
        "- 分类(突破当周, 无前视): low_quality = 涨幅<3% 或 长上影>50% 或 收盘位置<0.70",
        f"- 入场: 次周开盘(T+1, 涨停顺延≤2周) · 成本往返 · 持有 {horizons} 周",
        f"- 有效交易: {summary['n_trades']} · 低质量占比 {pct(summary['low_share'])}",
        "",
        "## 信号定义",
        "",
        "| 分组 | 定义 | 对应假突破形态 |",
        "|------|------|--------------|",
        "| low_quality | 突破周涨幅<3% 或 上影/振幅>50% 或 收盘位置<0.70 | ②放量滞涨/长上影 + ①盘中突破收盘跌回 |",
        "| high_quality | 突破周收盘站稳+涨幅健康 | 真突破的\"收盘站稳\"条件 |",
        "| failed(事后) | 突破后13周内收盘跌破平台高 | ③④ 突破失败 |",
        "",
        "## 无条件基准（随机买入 · 扣成本）",
        "",
        "| 持有周 | N | 净均值 | 净中位 | 胜率 |",
        "|--------|---|--------|--------|------|",
    ]
    for h in horizons:
        st = base_by_h[h]
        if st.get("n"):
            lines.append(f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    for q, qname in (("low", "低质量突破"), ("high", "高质量突破")):
        lines += [
            "",
            f"## {qname} · 扣成本净收益 vs 基准",
            "",
            "| 持有周 | N | 净均值 | 净中位 | 胜率 | 基准均值 | 超额 |",
            "|--------|---|--------|--------|------|----------|------|",
        ]
        for h in horizons:
            st = summary["by_quality"][q]["by_horizon"][str(h)]
            if not st.get("n"):
                continue
            bmean = base_by_h[h].get("mean", 0.0) or 0.0
            excess = (st["mean"] or 0.0) - bmean
            lines.append(f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} | {pct(bmean)} | {pct(excess)} |")
        lines += [
            "",
            f"### {qname} 分层（持有13周）",
            "",
            "**规模/活跃度**",
            "",
            "| 分位 | N | 净均值 | 净中位 | 胜率 |",
            "|------|---|--------|--------|------|",
        ]
        for k, st in (summary["by_quality"][q]["by_size_h13"] or {}).items():
            if st.get("n"):
                lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    lines += [
        "",
        "## 事后失败突破（描述性 · 用未来信息）",
        "",
        "| 分组 | 持有13周净均值 | N | 胜率 |",
        "|------|--------------|---|------|",
    ]
    for q, qname in (("failed", "突破后失败"), ("held", "突破后未失败")):
        st = summary["by_failed"][q]["by_horizon"]["13"]
        if st.get("n"):
            lines.append(f"| {qname} | {pct(st['mean'])} | {st['n']} | {pct(st['win_rate'])} |")

    lines += [
        "",
        "## 结论边界",
        "",
        "- 教学规则 confidence 上限 0.5；历史事件统计，非实盘期望。",
        "- low/high 分类仅用突破当周数据（无前视）；failed 分类用未来信息，仅作确认。",
        "- 幸存者偏差、停牌、指数过滤未建模。",
        f"- 原始 JSON: `{json_path.name}`",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:45]))
    print(f"\n报告: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
