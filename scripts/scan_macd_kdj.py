#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描自选股/持仓的 MACD+KDJ 五法状态，并用本地 K 线做简易历史统计。

用法:
  .venv/bin/python scripts/scan_macd_kdj.py
  .venv/bin/python scripts/scan_macd_kdj.py --symbol 002460
  .venv/bin/python scripts/scan_macd_kdj.py --backtest-years 3
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.alphas.macd_kdj import (  # noqa: E402
    MacdKdjAction,
    MacdKdjMethod,
    analyze_ohlc,
    latest_state,
)

DATA = ROOT / "data"
KLINE_DIR = DATA / "kline_cache"
WATCHLIST = DATA / "watchlist.json"
POSITIONS = DATA / "positions.json"


def load_universe() -> list[tuple[str, str]]:
    """返回 [(symbol, name), ...]。"""
    items: dict[str, str] = {}
    if WATCHLIST.exists():
        wl = json.loads(WATCHLIST.read_text(encoding="utf-8"))
        for s in wl.get("stocks", []):
            items[s["symbol"]] = s.get("name") or s["symbol"]
    if POSITIONS.exists():
        pos = json.loads(POSITIONS.read_text(encoding="utf-8"))
        for sym, p in pos.items():
            items[sym] = p.get("name") or items.get(sym, sym)
    return sorted(items.items())


def find_kline(symbol: str) -> Path | None:
    matches = sorted(KLINE_DIR.glob(f"{symbol}_*_daily.csv"))
    return matches[-1] if matches else None


def load_kline(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # 统一列名
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("date", "open", "high", "low", "close", "volume"):
        if need in df.columns:
            continue
        for c in df.columns:
            if c.lower() == need:
                rename[c] = need
    if rename:
        df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def simple_backtest(df: pd.DataFrame, years: float = 3.0) -> dict:
    """极简事件研究：ENTER 后 5/10/20 日收益；EXIT 后 5/10 日收益。

    非完整交易模拟，仅统计信号后向表现（教学规则验证用）。
    """
    if df.empty:
        return {"n_enter": 0, "n_exit": 0}
    cutoff = df["date"].max() - pd.Timedelta(days=int(365 * years))
    sub = df[df["date"] >= cutoff].reset_index(drop=True)
    series = analyze_ohlc(sub)
    closes = sub["close"].astype(float).to_numpy()
    n = len(closes)

    def fwd(i: int, h: int) -> float | None:
        j = i + h
        if j >= n or closes[i] <= 0:
            return None
        return float(closes[j] / closes[i] - 1.0)

    enter_rets = {5: [], 10: [], 20: []}
    exit_rets = {5: [], 10: []}
    n_enter = n_exit = n_avoid = 0
    method_counts: dict[str, int] = {}

    for i, st in enumerate(series.states):
        for m in st.methods:
            method_counts[m.value] = method_counts.get(m.value, 0) + 1
        if st.action == MacdKdjAction.ENTER:
            n_enter += 1
            for h in enter_rets:
                r = fwd(i, h)
                if r is not None:
                    enter_rets[h].append(r)
        elif st.action == MacdKdjAction.EXIT:
            n_exit += 1
            for h in exit_rets:
                r = fwd(i, h)
                if r is not None:
                    exit_rets[h].append(r)
        elif st.action == MacdKdjAction.AVOID_ENTRY:
            n_avoid += 1

    def avg(xs: list[float]) -> float | None:
        return float(np.mean(xs)) if xs else None

    def win_rate(xs: list[float]) -> float | None:
        return float(np.mean([x > 0 for x in xs])) if xs else None

    return {
        "bars": n,
        "n_enter": n_enter,
        "n_exit": n_exit,
        "n_avoid": n_avoid,
        "method_counts": method_counts,
        "enter_avg_5d": avg(enter_rets[5]),
        "enter_avg_10d": avg(enter_rets[10]),
        "enter_avg_20d": avg(enter_rets[20]),
        "enter_wr_10d": win_rate(enter_rets[10]),
        "exit_avg_5d": avg(exit_rets[5]),
        "exit_avg_10d": avg(exit_rets[10]),
        "exit_wr_10d_down": (
            float(np.mean([x < 0 for x in exit_rets[10]])) if exit_rets[10] else None
        ),
    }


def fmt_pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="MACD+KDJ 五法扫描")
    ap.add_argument("--symbol", action="append", default=[], help="指定代码，可多次")
    ap.add_argument("--backtest-years", type=float, default=3.0)
    ap.add_argument(
        "--live",
        action="store_true",
        help="用 DataAggregator 拉新鲜日线（忽略过期 kline_cache）",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "output" / "macd_kdj_scan.md",
        help="输出 markdown 路径",
    )
    args = ap.parse_args()

    if args.symbol:
        names = {s: s for s in args.symbol}
        # 尝试从 watchlist 补名
        for s, n in load_universe():
            if s in names:
                names[s] = n
        universe = sorted(names.items())
    else:
        universe = load_universe()

    rows_latest = []
    rows_bt = []
    missing = []

    print(f"扫描 {len(universe)} 只标的 | 回看 {args.backtest_years} 年\n")
    print(
        f"{'代码':<8} {'名称':<10} {'动作':<12} {'方法':<28} "
        f"{'DIF':>8} {'DEA':>8} {'K':>6} {'D':>6} conf"
    )
    print("-" * 100)

    live_agg = None
    if args.live:
        from datetime import datetime, timedelta

        from src.data.aggregator import DataAggregator

        live_agg = DataAggregator()
        live_end = datetime.now().strftime("%Y-%m-%d")
        live_start = (datetime.now() - timedelta(days=int(365 * max(args.backtest_years, 1) + 60))).strftime(
            "%Y-%m-%d"
        )
        print(f"[live] {live_start} → {live_end}\n")

    for sym, name in universe:
        path = find_kline(sym)
        df = None
        source_tag = ""
        if args.live and live_agg is not None:
            try:
                raw = live_agg.get_history(sym, live_start, live_end, period="daily")
                if raw is not None and len(raw) >= 50:
                    df = raw.copy()
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)
                    source_tag = "live"
            except Exception as exc:  # noqa: BLE001
                print(f"{sym:<8} {name:<10} [live失败] {exc} → 尝试缓存")
        if df is None:
            if path is None:
                missing.append(sym)
                print(f"{sym:<8} {name:<10} [DATA_GAP] 无本地K线缓存")
                continue
            df = load_kline(path)
            source_tag = path.name
            # 缓存过期提示（最后 bar 超过 5 个交易日）
            last_d = pd.to_datetime(df["date"].iloc[-1])
            if (pd.Timestamp.now().normalize() - last_d).days > 7:
                print(
                    f"{sym:<8} {name:<10} [STALE] 缓存截止 {last_d.date()} "
                    f"（建议 --live）"
                )
        if len(df) < 50:
            missing.append(sym)
            print(f"{sym:<8} {name:<10} [DATA_GAP] K线不足 ({len(df)})")
            continue

        st = latest_state(df)
        methods = ",".join(m.value for m in st.methods) if st and st.methods else "-"
        action = st.action.value if st else "NONE"
        print(
            f"{sym:<8} {name:<10} {action:<12} {methods[:28]:<28} "
            f"{st.dif:8.3f} {st.dea:8.3f} {st.k:6.1f} {st.d:6.1f} "
            f"{st.confidence:.2f}"
        )
        if st.notes:
            for n in st.notes:
                print(f"         · {n}")

        rows_latest.append(
            {
                "symbol": sym,
                "name": name,
                "date": st.date,
                "action": action,
                "methods": methods,
                "dif": round(st.dif, 4),
                "dea": round(st.dea, 4),
                "k": round(st.k, 2),
                "d": round(st.d, 2),
                "j": round(st.j, 2),
                "confidence": st.confidence,
                "notes": " | ".join(st.notes),
                "kline": source_tag,
            }
        )

        bt = simple_backtest(df, years=args.backtest_years)
        bt["symbol"] = sym
        bt["name"] = name
        rows_bt.append(bt)
        print(
            f"         BT{args.backtest_years:.0f}y: ENTER={bt['n_enter']} "
            f"EXIT={bt['n_exit']} AVOID={bt['n_avoid']} | "
            f"E10d={fmt_pct(bt['enter_avg_10d'])} wr={fmt_pct(bt['enter_wr_10d'])} | "
            f"X10d={fmt_pct(bt['exit_avg_10d'])} down_wr={fmt_pct(bt['exit_wr_10d_down'])}"
        )

    # 汇总
    print("\n" + "=" * 100)
    if rows_bt:
        total_enter = sum(r["n_enter"] for r in rows_bt)
        total_exit = sum(r["n_exit"] for r in rows_bt)
        # 合并 enter 10d 等权平均（按事件数加权）
        e10, e10n = 0.0, 0
        for r in rows_bt:
            if r["enter_avg_10d"] is not None and r["n_enter"]:
                e10 += r["enter_avg_10d"] * r["n_enter"]
                e10n += r["n_enter"]
        print(
            f"汇总: ENTER事件={total_enter} EXIT事件={total_exit} | "
            f"ENTER后10日加权均收益={fmt_pct(e10 / e10n if e10n else None)}"
        )
    if missing:
        print(f"[DATA_GAP] 无K线: {', '.join(missing)}")

    # 写 markdown
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MACD+KDJ 五法扫描报告",
        "",
        f"- 回看年数: {args.backtest_years}",
        f"- 标的数: {len(universe)}（缺失K线 {len(missing)}）",
        "- 性质: `interpretation` / tertiary；confidence ≤ 0.5",
        "- **不构成交易建议**；正式决策须过完整管道",
        "",
        "## 最新状态",
        "",
        "| 代码 | 名称 | 日期 | 动作 | 方法 | DIF | DEA | K | D | conf | 备注 |",
        "|------|------|------|------|------|-----|-----|---|---|------|------|",
    ]
    for r in rows_latest:
        lines.append(
            f"| {r['symbol']} | {r['name']} | {r['date']} | {r['action']} | "
            f"`{r['methods']}` | {r['dif']} | {r['dea']} | {r['k']} | {r['d']} | "
            f"{r['confidence']} | {r['notes'][:40]} |"
        )
    lines += [
        "",
        "## 简易事件统计（信号后向收益，非完整回测）",
        "",
        "| 代码 | 名称 | ENTER | EXIT | AVOID | E10d均 | E10d胜率 | X10d均 | X后下跌率 |",
        "|------|------|-------|------|-------|--------|----------|--------|-----------|",
    ]
    for r in rows_bt:
        lines.append(
            f"| {r['symbol']} | {r['name']} | {r['n_enter']} | {r['n_exit']} | "
            f"{r['n_avoid']} | {fmt_pct(r['enter_avg_10d'])} | "
            f"{fmt_pct(r['enter_wr_10d'])} | {fmt_pct(r['exit_avg_10d'])} | "
            f"{fmt_pct(r['exit_wr_10d_down'])} |"
        )
    lines += [
        "",
        "## 方法说明",
        "",
        "| 方法 | 含义 | 动作 |",
        "|------|------|------|",
        "| M1_resonance_golden | 0轴下 MACD+KDJ 共振金叉 | ENTER |",
        "| M2_resonance_death | 共振死叉或0轴下KDJ死叉 | EXIT |",
        "| M3_below_zero_avoid | 0轴下未拐头+KDJ金叉 | AVOID_ENTRY |",
        "| M4_above_zero_enter | 0轴上+KDJ金叉(无死叉/顶背离) | ENTER |",
        "| M5_wash_hold | 双死叉后小幅洗盘再双金叉 | HOLD |",
        "",
    ]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
