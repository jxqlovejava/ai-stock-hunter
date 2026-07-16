#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MACD+KDJ 五法 · 全量 A 股缓存严格事件研究。

约束:
  - 入场: 信号次日开盘（T+1 可交易），涨停无法买入则顺延最多 3 日
  - 出场: 固定持有 H 日 或 持有期内 EXIT 信号次日开盘
  - 成本: AShareCostCalculator（佣金+印花税+过户费+滑点）
  - 涨跌停: 主板 10% / 创业板科创板 20% / ST 5%

用法:
  .venv/bin/python scripts/event_study_macd_kdj.py
  .venv/bin/python scripts/event_study_macd_kdj.py --years 5 --max-symbols 500
  .venv/bin/python scripts/event_study_macd_kdj.py --horizons 5,10,20
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

from src.alphas.macd_kdj import (  # noqa: E402
    MacdKdjAction,
    analyze_ohlc,
    normalize_ohlc_df,
)
from src.backtest.cost_model import AShareCostCalculator  # noqa: E402

KLINE_DIR = ROOT / "data" / "kline_cache"
OUT_DIR = ROOT / "output"


def limit_pct(symbol: str, name: str = "") -> float:
    """涨跌停幅度。"""
    s = symbol.split(".")[0]
    nm = name or ""
    if "ST" in nm.upper() or nm.startswith("*"):
        return 0.05
    if s.startswith(("300", "301", "688", "689")):
        return 0.20
    if s.startswith(("8", "4")):  # 北交所粗略
        return 0.30
    return 0.10


def board_of(symbol: str) -> str:
    """板块分层（代码前缀，无外部行业表时的稳健代理）。"""
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
    """近 lookback 日均成交额（close×volume）— 无流通股本时的规模/活跃度代理。"""
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
    # 触及涨停且收在涨停附近
    return high >= lim * 0.999 and close >= lim * 0.997


def is_limit_down(low: float, close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0 or not math.isfinite(prev_close):
        return False
    lim = round_price(prev_close * (1.0 - pct))
    return low <= lim * 1.001 and close <= lim * 1.003


@dataclass
class TradeResult:
    symbol: str
    signal_date: str
    entry_date: str
    exit_date: str
    action: str
    methods: str
    entry_px: float
    exit_px: float
    hold_days: int
    gross_ret: float
    net_ret: float
    cost_pct: float
    exit_reason: str
    board: str = ""
    industry: str = ""
    size_bucket: str = ""
    dollar_vol: float = 0.0
    skipped: bool = False
    skip_reason: str = ""


def load_industry_map(path: Path | None = None) -> dict[str, str]:
    """加载 sector_map.csv → {code6: industry}。"""
    p = path or (KLINE_DIR / "sector_map.csv")
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row.get("code") or "")
        # sh.600000 / sz.000001 → 600000
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) >= 6:
            digits = digits[-6:]
        ind = str(row.get("industry") or "").strip()
        if digits and ind and ind.lower() != "nan":
            # 取门类字母后名称，过长则截到 12 字
            out[digits] = ind[:16]
    return out


def _process_one(args: tuple) -> dict:
    """单标的事件研究（子进程）。"""
    path_str, years, horizons, qty, size_bucket, industry = args
    path = Path(path_str)
    symbol = path.name.split("_")[0]
    board = board_of(symbol)
    industry = industry or "unknown"
    try:
        raw = pd.read_csv(path)
        df = normalize_ohlc_df(raw)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "trades": [], "board": board}

    if len(df) < 80 or not all(c in df.columns for c in ("open", "high", "low", "close")):
        return {"symbol": symbol, "error": "insufficient", "trades": [], "board": board}

    # 时间窗
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    end = df["date"].max()
    start = end - pd.Timedelta(days=int(365 * years + 30))
    df = df[df["date"] >= start].reset_index(drop=True)
    if len(df) < 80:
        return {"symbol": symbol, "error": "short_window", "trades": [], "board": board}

    dvol = mean_dollar_volume(df)
    series = analyze_ohlc(df)
    states = series.states
    n = len(df)
    opens = df["open"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    dates = df["date"].dt.strftime("%Y-%m-%d").to_numpy()
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]
    lp = limit_pct(symbol)
    cost = AShareCostCalculator()

    trades: list[dict] = []
    max_h = max(horizons)

    for i, st in enumerate(states):
        if st.action != MacdKdjAction.ENTER:
            continue
        if i >= n - 2:
            continue

        # 找可买入日：信号次日起，最多顺延 3 日
        entry_i = None
        for j in range(i + 1, min(i + 4, n)):
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
                        signal_date=str(dates[i]),
                        entry_date="",
                        exit_date="",
                        action="ENTER",
                        methods=",".join(m.value for m in st.methods),
                        entry_px=0,
                        exit_px=0,
                        hold_days=0,
                        gross_ret=0,
                        net_ret=0,
                        cost_pct=0,
                        exit_reason="",
                        board=board,
                        industry=industry,
                        size_bucket=size_bucket,
                        dollar_vol=dvol,
                        skipped=True,
                        skip_reason="limit_up_or_no_entry",
                    )
                )
            )
            continue

        entry_px_raw = float(opens[entry_i])
        # 买入滑点体现在成本模型；成交价用 open
        buy = cost.calc_buy_cost(symbol, entry_px_raw, qty)
        # 有效成本价（含滑点上浮近似）
        entry_eff = entry_px_raw * (1 + cost.slippage_rate)

        for H in horizons:
            # 默认持有 H 个交易日
            exit_i = min(entry_i + H, n - 1)
            exit_reason = f"horizon_{H}"

            # 持有期内若出现 EXIT，次日开盘走
            for k in range(entry_i, min(entry_i + H, n)):
                if states[k].action == MacdKdjAction.EXIT:
                    # 次日开盘
                    if k + 1 < n and not is_limit_down(
                        lows[k + 1], closes[k + 1], prev_closes[k + 1], lp
                    ):
                        exit_i = k + 1
                        exit_reason = "signal_exit"
                    else:
                        # 跌停无法卖，继续找
                        for m in range(k + 1, min(entry_i + H + 3, n)):
                            if not is_limit_down(
                                lows[m], closes[m], prev_closes[m], lp
                            ):
                                exit_i = m
                                exit_reason = "signal_exit_deferred"
                                break
                    break

            exit_px_raw = float(opens[exit_i]) if exit_i > entry_i else float(closes[exit_i])
            if exit_px_raw <= 0:
                continue
            sell = cost.calc_sell_cost(symbol, exit_px_raw, qty)
            exit_eff = exit_px_raw * (1 - cost.slippage_rate)

            gross = exit_px_raw / entry_px_raw - 1.0
            # 净收益：用有效价 + 费用
            buy_notional = entry_px_raw * qty
            sell_notional = exit_px_raw * qty
            net_pnl = (sell_notional - sell.total_cost) - (buy_notional + buy.total_cost)
            # 更准确：滑点已在 total_cost 的 slippage 字段
            # estimate_cost 把 slippage 算进 total_cost
            net_ret = net_pnl / buy_notional if buy_notional > 0 else 0.0
            # 上面 double-count 滑点如果又用 exit_eff；改用 cost 模型即可
            roundtrip = cost.calc_roundtrip_cost(symbol, entry_px_raw, exit_px_raw, qty)
            net_ret = gross - roundtrip["roundtrip_pct"]

            trades.append(
                asdict(
                    TradeResult(
                        symbol=symbol,
                        signal_date=str(dates[i]),
                        entry_date=str(dates[entry_i]),
                        exit_date=str(dates[exit_i]),
                        action="ENTER",
                        methods=",".join(m.value for m in st.methods),
                        entry_px=round(entry_px_raw, 4),
                        exit_px=round(exit_px_raw, 4),
                        hold_days=int(exit_i - entry_i),
                        gross_ret=round(gross, 6),
                        net_ret=round(net_ret, 6),
                        cost_pct=round(roundtrip["roundtrip_pct"], 6),
                        exit_reason=exit_reason,
                        board=board,
                        industry=industry,
                        size_bucket=size_bucket,
                        dollar_vol=dvol,
                    )
                )
            )

    # AVOID 验证：信号后 5 日收益是否为负（避免进场正确）
    avoid_hits = 0
    avoid_n = 0
    for i, st in enumerate(states):
        if st.action != MacdKdjAction.AVOID_ENTRY:
            continue
        if i + 5 >= n:
            continue
        avoid_n += 1
        r = closes[i + 5] / closes[i] - 1.0 if closes[i] > 0 else 0
        if r < 0:
            avoid_hits += 1

    return {
        "symbol": symbol,
        "error": "",
        "trades": trades,
        "avoid_n": avoid_n,
        "avoid_hits": avoid_hits,
        "n_bars": n,
        "board": board,
        "industry": industry,
        "size_bucket": size_bucket,
        "dollar_vol": dvol,
    }


def summarize(all_trades: list[dict], avoid_n: int, avoid_hits: int) -> dict:
    active = [t for t in all_trades if not t.get("skipped")]
    skipped = [t for t in all_trades if t.get("skipped")]
    by_h: dict[int, list] = {}
    pure_h: dict[int, list] = {}  # 仅固定持有到期（非提前 EXIT）
    for t in active:
        h = t.get("hold_days") or 0
        reason = t.get("exit_reason") or ""
        if reason.startswith("horizon_"):
            try:
                h = int(reason.split("_")[1])
            except Exception:
                pass
            pure_h.setdefault(h, []).append(t)
        by_h.setdefault(h, []).append(t)

    def stats(xs: list[dict], key: str = "net_ret") -> dict:
        vals = [float(t[key]) for t in xs if t.get(key) is not None]
        if not vals:
            return {"n": 0}
        a = np.array(vals)
        return {
            "n": len(a),
            "mean": float(np.mean(a)),
            "median": float(np.median(a)),
            "win_rate": float(np.mean(a > 0)),
            "p25": float(np.percentile(a, 25)),
            "p75": float(np.percentile(a, 75)),
            "std": float(np.std(a)),
        }

    def stratum(key: str) -> dict:
        buckets: dict[str, list] = {}
        for t in active:
            # 分层主看固定 10 日持有（有 horizon_10）
            if not str(t.get("exit_reason", "")).startswith("horizon_10"):
                # 也纳入 signal_exit 但 hold≈10 的？仅 pure horizon_10 更干净
                continue
            b = str(t.get(key) or "unknown")
            buckets.setdefault(b, []).append(t)
        return {k: stats(v) for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))}

    out = {
        "n_trades_active": len(active),
        "n_skipped": len(skipped),
        "skip_rate": len(skipped) / max(len(all_trades), 1),
        "overall_net": stats(active, "net_ret"),
        "overall_gross": stats(active, "gross_ret"),
        "by_horizon": {str(h): stats(ts) for h, ts in sorted(by_h.items())},
        "by_horizon_pure": {str(h): stats(ts) for h, ts in sorted(pure_h.items())},
        "by_board_h10": stratum("board"),
        "by_size_h10": stratum("size_bucket"),
        "by_industry_h10": {
            k: v
            for k, v in list(stratum("industry").items())[:25]  # top 25 by n
        },
        "avoid_n": avoid_n,
        "avoid_hit_rate": avoid_hits / avoid_n if avoid_n else None,
        "mean_cost_pct": float(np.mean([t["cost_pct"] for t in active])) if active else None,
        "exit_signal_share": (
            float(np.mean([str(t.get("exit_reason", "")).startswith("signal") for t in active]))
            if active
            else None
        ),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--horizons", type=str, default="5,10,20")
    ap.add_argument("--max-symbols", type=int, default=0, help="0=全部")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--qty", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "macd_kdj_event_study.md")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    files = sorted(KLINE_DIR.glob("*_daily.csv"))
    if args.max_symbols > 0:
        files = files[: args.max_symbols]

    print(f"标的文件: {len(files)} | 年数={args.years} | horizons={horizons} | workers={args.workers}")
    if not files:
        print("无 kline_cache，退出")
        return 1

    # Pass-1: 成交额规模分位（全样本四分位，作市值/流动性代理）
    print("Pass-1: 计算日均成交额分位…")
    dvol_map: dict[str, float] = {}
    for f in files:
        sym = f.name.split("_")[0]
        try:
            raw = pd.read_csv(f, usecols=lambda c: c.lower() in ("date", "close", "volume", "收盘", "成交量"))
            df = normalize_ohlc_df(raw)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                end = df["date"].max()
                start = end - pd.Timedelta(days=int(365 * args.years + 30))
                df = df[df["date"] >= start]
            dvol_map[sym] = mean_dollar_volume(df)
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

    ind_map = load_industry_map()
    print(f"  行业映射: {len(ind_map)} 条 (sector_map.csv)")

    tasks = [
        (
            str(f),
            args.years,
            horizons,
            args.qty,
            size_map.get(f.name.split("_")[0], "Q?_unknown"),
            ind_map.get(f.name.split("_")[0], "unknown"),
        )
        for f in files
    ]
    results = []
    # 进程池对 macOS 需在 main 内
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
    avoid_n = avoid_hits = 0
    errors = 0
    for r in results:
        if r.get("error") and r["error"] not in ("", "insufficient", "short_window"):
            errors += 1
        all_trades.extend(r.get("trades") or [])
        avoid_n += int(r.get("avoid_n") or 0)
        avoid_hits += int(r.get("avoid_hits") or 0)

    summary = summarize(all_trades, avoid_n, avoid_hits)
    summary["n_symbols"] = len(files)
    summary["n_errors"] = errors
    summary["years"] = args.years
    summary["horizons"] = horizons

    # 写 JSON + MD
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = args.out.with_suffix(".json")
    json_path.write_text(
        json.dumps({"summary": summary, "sample_trades": all_trades[:200]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def pct(x):
        if x is None:
            return "n/a"
        return f"{x*100:+.2f}%"

    lines = [
        "# MACD+KDJ 五法 · 严格事件研究",
        "",
        f"- 样本: {summary['n_symbols']} 只缓存标的 · 近 {args.years} 年",
        f"- 入场: 信号次日开盘（涨停顺延≤3日）· T+1",
        f"- 成本: 佣金万2.5+最低5 + 印花税千0.5卖 + 过户 + 滑点千1",
        f"- 持有: {horizons} 日；期内 EXIT 可提前平",
        f"- 有效交易: {summary['n_trades_active']} · 跳过(涨停等): {summary['n_skipped']} "
        f"({pct(summary['skip_rate'])})",
        "",
        "## 总体（扣成本净收益）",
        "",
    ]
    og = summary["overall_net"]
    if og.get("n"):
        lines += [
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| N | {og['n']} |",
            f"| 均值 | {pct(og['mean'])} |",
            f"| 中位 | {pct(og['median'])} |",
            f"| 胜率 | {pct(og['win_rate'])} |",
            f"| P25/P75 | {pct(og['p25'])} / {pct(og['p75'])} |",
            f"| 毛收益均值 | {pct(summary['overall_gross'].get('mean'))} |",
            f"| 往返成本均值 | {pct(summary.get('mean_cost_pct'))} |",
            f"| 信号提前EXIT占比 | {pct(summary.get('exit_signal_share'))} |",
            f"| AVOID后5日下跌率 | {pct(summary.get('avoid_hit_rate'))} (n={avoid_n}) |",
            "",
            "## 分持有期",
            "",
            "| 持有日 | N | 净均值 | 净中位 | 胜率 |",
            "|--------|---|--------|--------|------|",
        ]
        for h, st in summary["by_horizon"].items():
            if not st.get("n"):
                continue
            lines.append(
                f"| {h} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |"
            )
    else:
        lines.append("_无有效交易_")

    # 分层：固定 10 日持有
    lines += [
        "",
        "## 板块分层（固定持有 10 日 · 扣成本）",
        "",
        "> 行业无全市场静态映射表时，用代码前缀板块作风格分层。",
        "",
        "| 板块 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary.get("by_board_h10") or {}).items():
        if not st.get("n"):
            continue
        lines.append(
            f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |"
        )

    lines += [
        "",
        "## 规模/活跃度分层（日均成交额四分位 · 市值代理 · H=10）",
        "",
        "> 缓存无流通股本；用近窗 `close×volume` 日均成交额作规模代理。",
        "",
        "| 分位 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary.get("by_size_h10") or {}).items():
        if not st.get("n"):
            continue
        lines.append(
            f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |"
        )

    lines += [
        "",
        "## 证监会行业分层（Top 行业 by N · H=10）",
        "",
        "> 来源: `data/kline_cache/sector_map.csv`",
        "",
        "| 行业 | N | 净均值 | 净中位 | 胜率 |",
        "|------|---|--------|--------|------|",
    ]
    for k, st in (summary.get("by_industry_h10") or {}).items():
        if not st.get("n") or k in ("unknown", ""):
            continue
        lines.append(
            f"| {k} | {st['n']} | {pct(st['mean'])} | {pct(st['median'])} | {pct(st['win_rate'])} |"
        )

    lines += [
        "",
        "## 结论边界",
        "",
        "- 教学规则 confidence 上限 0.5；本结果为历史事件统计，**非实盘期望**。",
        "- 未建模：涨停打开后的流动性冲击、停牌、财报真空、指数过滤。",
        "- 分层: 板块 + 成交额规模代理 + 证监会行业（sector_map）。",
        "",
        f"原始 JSON: `{json_path.name}`",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:55]))
    print(f"\n报告: {args.out}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
