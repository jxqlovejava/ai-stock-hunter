#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多周期合流事件研究 · 验证 @OtherSideBJ「周线选股，日线定买卖」规则。

文章可量化规则（15 分钟金叉部分缓存无数据 → [DATA_GAP]，只测前两条+锁利）:

  C1      : 日线收盘 > 最近已完成周的周线 MA5（无前视: 周 MA5 取上周五为基准）
  C2      : 日线收盘 > 日线 MA20
  CONF2   : C1 且 C2（文章"买入三条件"中的①②）
  LOCK    : 近60交易日累计涨幅 ≥ +20% 且 当日 MA5 死叉 MA10（验证"涨20%后死叉要锁利"）

约束（与 event_study_macd_kdj.py 对齐）:
  - 入场: 信号次日开盘（T+1），涨停顺延 ≤3 日
  - 出场: 固定持有 H 交易日，按到期日开盘
  - 成本: AShareCostCalculator（按个股末价计往返成本，常量扣减）
  - 对照: 无条件基准 = 全样本所有交易日的同构前视收益

用法:
  .venv/bin/python scripts/multitimeframe_confluence_study.py
  .venv/bin/python scripts/multitimeframe_confluence_study.py --max-symbols 300 --workers 4
  .venv/bin/python scripts/multitimeframe_confluence_study.py --horizons 5,10,20,40,60
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.cost_model import AShareCostCalculator  # noqa: E402

KLINE_DIR = ROOT / "data" / "kline_cache"
OUT_DIR = ROOT / "output"

DAILY_MIN_BARS = 250        # 需要周线MA5(≥25周) + 日线MA20 + 60日前视
ENTRY_DEFER_MAX_D = 3       # 涨停入场顺延最大日数
LOCK_RUN_UP = 0.20          # 锁利规则: 近60日累计涨幅阈值
LOCK_WINDOW = 60


def limit_pct(symbol: str, name: str = "") -> float:
    s = symbol.split(".")[0]
    nm = name or ""
    if "ST" in nm.upper() or nm.startswith("*"):
        return 0.05
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
    if m.empty:
        return 0.0
    return float(m.mean())


def is_limit_up(high: float, close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0 or not math.isfinite(prev_close):
        return False
    lim = round_price(prev_close * (1.0 + pct))
    return high >= lim * 0.999 and close >= lim * 0.997


def weekly_ma5_asof(df: pd.DataFrame) -> pd.Series:
    """最近已完成周的周线 MA5（无前视），按日线 index 返回 as-of 值。

    周线 MA5 只在每周五收盘后才"已知"。asof 到任意日 t 取最近一个 ≤t 的
    周五所对应的 MA5 → 交易日处于周中时拿到的是上一完整周的值。
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").set_index("date")
    wk = d.resample("W-FRI")["close"].last().dropna()
    ma5w = wk.rolling(5).mean().dropna()
    daily_idx = d.index
    comb = daily_idx.union(ma5w.index)
    s = ma5w.reindex(comb).ffill().reindex(daily_idx)
    return s


def _process_one(args: tuple) -> dict:
    path_str, horizons, size_bucket = args
    path = Path(path_str)
    symbol = path.name.split("_")[0]
    board = board_of(symbol)
    try:
        raw = pd.read_csv(path)
        if "date" not in raw.columns:
            return {"symbol": symbol, "error": "no_date", "trades": [], "baseline": []}
        raw["date"] = pd.to_datetime(raw["date"])
        df = raw.sort_values("date").reset_index(drop=True)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "trades": [], "baseline": []}

    n = len(df)
    if n < DAILY_MIN_BARS or not all(c in df.columns for c in ("open", "high", "low", "close")):
        return {"symbol": symbol, "error": "insufficient", "trades": [], "baseline": []}

    opens = df["open"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]
    lp = limit_pct(symbol)
    dates = df["date"].dt.strftime("%Y-%m-%d").to_numpy()

    # 信号布尔（无前视）
    ma5w_asof = weekly_ma5_asof(df).to_numpy()
    c1 = (closes > ma5w_asof) & np.isfinite(ma5w_asof)

    ma20 = pd.Series(closes).rolling(20).mean().to_numpy()
    c2 = (closes > ma20) & np.isfinite(ma20)

    conf2 = c1 & c2

    # LOCK: 近60日涨≥20% 且 MA5 死叉 MA10（当日 ma5<ma10, 前一日 ma5>=ma10）
    run_up = pd.Series(closes).pct_change(LOCK_WINDOW)
    ma5 = pd.Series(closes).rolling(5).mean()
    ma10 = pd.Series(closes).rolling(10).mean()
    death_cross = (ma5 < ma10) & (ma5.shift(1) >= ma10.shift(1))
    lock = (run_up >= LOCK_RUN_UP) & death_cross.fillna(False)

    signals = {"C1": c1, "C2": c2, "CONF2": conf2, "LOCK": lock.to_numpy()}

    # 可入场日索引：信号日 i → 次日起顺延最多 ENTRY_DEFER_MAX_D 日（涨停跳过）
    entry_idx = np.full(n, -1, dtype=int)
    for i in range(n - 1):
        j = i + 1
        while j < min(i + 1 + ENTRY_DEFER_MAX_D, n):
            if not is_limit_up(highs[j], closes[j], prev_closes[j], lp):
                break
            j += 1
        if j < n and not is_limit_up(highs[j], closes[j], prev_closes[j], lp):
            entry_idx[i] = j

    # 代表往返成本（按个股末价，近似常量）
    cost = AShareCostCalculator()
    last_px = float(closes[-1]) if closes[-1] > 0 else 10.0
    rt = cost.calc_roundtrip_cost(symbol, last_px, last_px, 1000)
    cost_pct = float(rt["roundtrip_pct"])

    max_h = max(horizons)
    # 前视收益（向量化）：entry_idx[i] 入场 → +H 开盘出场
    fwd: dict[int, np.ndarray] = {}
    for h in horizons:
        arr = np.full(n, np.nan)
        for i in range(n - 1):
            e = entry_idx[i]
            if e < 0 or e + h >= n:
                continue
            x = float(opens[e + h])
            o = float(opens[e])
            if o > 0 and x > 0:
                arr[i] = x / o - 1.0
        fwd[h] = arr

    trades: list[dict] = []
    baselines: list[dict] = []

    # 基准：全部交易日同构前视收益
    for h in horizons:
        a = fwd[h]
        for i in range(n - 1):
            v = a[i]
            if not np.isfinite(v):
                continue
            baselines.append({"hold_days": h, "net_ret": v - cost_pct, "board": board, "size_bucket": size_bucket})

    # 信号事件
    for sig_name, sig in signals.items():
        idx = np.flatnonzero(sig)
        for i in idx:
            i = int(i)
            e = entry_idx[i]
            if e < 0:
                trades.append(
                    {
                        "symbol": symbol, "signal": sig_name, "signal_date": str(dates[i]),
                        "entry_date": "", "hold_days": 0, "net_ret": 0.0, "cost_pct": 0.0,
                        "board": board, "size_bucket": size_bucket, "skipped": True,
                        "skip_reason": "limit_up_or_no_entry",
                    }
                )
                continue
            for h in horizons:
                v = fwd[h][i]
                if not np.isfinite(v):
                    continue
                trades.append(
                    {
                        "symbol": symbol, "signal": sig_name, "signal_date": str(dates[i]),
                        "entry_date": str(dates[e]), "hold_days": h,
                        "net_ret": round(v - cost_pct, 6), "cost_pct": round(cost_pct, 6),
                        "board": board, "size_bucket": size_bucket,
                    }
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


def stratum(ts: list[dict], key: str, hold: int) -> dict:
    buckets: dict[str, list] = {}
    for t in ts:
        if t.get("hold_days") != hold:
            continue
        b = str(t.get(key) or "unknown")
        buckets.setdefault(b, []).append(t)
    return {k: stats(v) for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=str, default="5,10,20,40,60")
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "multitimeframe_confluence_study.md")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    files = sorted(KLINE_DIR.glob("*_daily.csv"))
    if args.max_symbols > 0:
        files = files[: args.max_symbols]

    print(f"标的文件: {len(files)} | horizons={horizons} | workers={args.workers}")
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

    tasks = [(str(f), horizons, size_map.get(f.name.split("_")[0], "Q?_unknown")) for f in files]
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

    active = [t for t in all_trades if not t.get("skipped")]
    base_by_h = {h: [b for b in all_baseline if b["hold_days"] == h] for h in horizons}
    base_by_size = {str(h): stratum(all_baseline, "size_bucket", h) for h in horizons}

    summary = {
        "n_files": len(files),
        "n_symbols_used": n_symbols_used,
        "n_errors": errors,
        "horizons": horizons,
        "n_trades_active": len(active),
        "n_skipped": len(all_trades) - len(active),
        "skip_rate": (len(all_trades) - len(active)) / max(len(all_trades), 1),
        "baseline_by_horizon": {str(h): stats(base_by_h[h]) for h in horizons},
        "baseline_by_size": base_by_size,
        "by_signal": {},
    }
    for s in ("C1", "C2", "CONF2", "LOCK"):
        ts = [t for t in active if t["signal"] == s]
        summary["by_signal"][s] = {
            "n_signals": len(ts),
            "by_horizon": {str(h): stats([t for t in ts if t["hold_days"] == h]) for h in horizons},
            "by_board_h20": stratum(ts, "board", 20),
            "by_size_h20": stratum(ts, "size_bucket", 20),
        }

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
        "# 多周期合流事件研究 · 验证 @OtherSideBJ 周线/日线规则",
        "",
        f"- 样本: {n_symbols_used} 只有效标的 / {len(files)} 缓存文件 · 日线级",
        f"- 入场: 信号次日开盘（涨停顺延≤{ENTRY_DEFER_MAX_D}日）· T+1",
        f"- 成本: 往返佣金+印花税+过户+滑点（按个股末价近似常量扣减）",
        f"- 持有: {horizons} 交易日",
        f"- 有效交易: {summary['n_trades_active']} · 跳过(涨停等): {summary['n_skipped']} ({pct(summary['skip_rate'])})",
        "",
        "## 信号定义",
        "",
        "| 信号 | 定义 |",
        "|------|------|",
        "| C1 | 日线收盘 > 最近已完成周线 MA5（无前视） |",
        "| C2 | 日线收盘 > 日线 MA20 |",
        "| CONF2 | C1 且 C2（文章买入条件①②） |",
        f"| LOCK | 近{LOCK_WINDOW}日涨≥{LOCK_RUN_UP:.0%} 且 MA5 死叉 MA10（验证锁利规则） |",
        "",
        "> ⚠️ [DATA_GAP] 文章买入条件③（15分钟 20上穿60）日线缓存无数据，未测。",
        "",
        "## 无条件基准（随机买入 A 股期望 · 扣成本）",
        "",
        "| 持有日 | N | 净均值 | 净中位 | 胜率 |",
        "|--------|---|--------|--------|------|",
    ]
    for h in horizons:
        st = summary["baseline_by_horizon"][str(h)]
        if not st.get("n"):
            continue
        lines.append(f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    lines += [
        "",
        "## 分层基准（持有20日 · 扣成本 · 同规模随机买入）",
        "",
        "| 分位 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary["baseline_by_size"].get("20") or {}).items():
        if not st.get("n"):
            continue
        lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    for s, sname in (("C1", "周线站上MA5"), ("C2", "日线站上MA20"), ("CONF2", "双周期合流①②"), ("LOCK", "涨20%后死叉锁利")):
        lines += [
            "",
            f"## {s} {sname} · 扣成本净收益 vs 基准",
            "",
            "| 持有日 | N | 净均值 | 净中位 | 胜率 | 基准均值 | 超额 |",
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
            f"### {s} 分层（持有20日 · 扣成本）",
            "",
            "**板块**",
            "",
            "| 板块 | N | 净均值 | 净中位 | 胜率 |",
            "|------|---|--------|--------|------|",
        ]
        for k, st in (sig.get("by_board_h20") or {}).items():
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
        for k, st in (sig.get("by_size_h20") or {}).items():
            if not st.get("n"):
                continue
            lines.append(f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |")

    lines += [
        "",
        "## 结论边界",
        "",
        "- 教学规则 confidence 上限 0.5；历史事件统计，非实盘期望。",
        "- 未建模：15分钟条件（DATA_GAP）、停牌、财报真空、指数过滤、幸存者偏差。",
        "- 成本为近似常量扣减（个股末价往返），非逐笔精确计算。",
        f"- 原始 JSON: `{json_path.name}`",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))
    print(f"\n报告: {args.out}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
