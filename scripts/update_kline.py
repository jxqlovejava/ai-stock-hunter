#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新 data/kline_cache 日线缓存 — 根因修复（600089 双死叉误报事件）。

背景：
  哨兵/light 五法/离线 Quote 兜底都直接读 data/kline_cache，但仓库内没有任何
  刷新机制 → 缓存停留在一次性历史快照（曾全量停在 2025-12-31），MACD/KDJ 在
  过期数据上算信号，造成 600089「共振死叉」误报（实为 7 个多月前的死叉）。

本脚本从腾讯 newfqkline 接口按年分页拉全历史（仿 akshare stock_zh_a_hist_tx），
重建为单一来源一致的日线。**纯 stdlib**（urllib/json/csv/datetime），不依赖
akshare / src 包，本机与 Hermes 服务器同源可跑。

默认清单 = positions.json + watchlist.json 覆盖的标的；--symbols 可覆盖。
默认不复权(raw)，与 Hermes 服务器缓存一致（600089 修复后 DIF -0.06 > DEA -0.34、
K 78 > D 76 均为 raw 计算结果）。

用法:
  python3 scripts/update_kline.py                        # positions + watchlist
  python3 scripts/update_kline.py --symbols 600089,002463
  python3 scripts/update_kline.py --all                  # 全量缓存标的（慢）
  python3 scripts/update_kline.py --adjust qfq           # 默认 raw
  python3 scripts/update_kline.py --dry-run              # 只打印将刷新清单

环境变量:
  BAIZE_ROOT         仓库根目录（默认脚本上级目录）
  BAIZE_POSITIONS    positions.json 路径
  BAIZE_WATCHLIST    watchlist.json 路径
  BAIZE_KLINE_DIR    kline_cache 目录
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

# 默认起始日：与既有缓存文件名一致（20150101）
DEFAULT_START = "20150101"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_EPOCH = dt.date(1970, 1, 1)


# ---------------------------------------------------------------------------
# 腾讯日线拉取（纯 stdlib，仿 akshare stock_zh_a_hist_tx 按年分页 + 去重）
# ---------------------------------------------------------------------------


def _tx_symbol(code: str) -> str:
    """6 位代码 → 腾讯格式（sz/sh/bj 前缀）。"""
    c = (code or "").split(".")[0].strip()
    if not c:
        return code
    if len(c) > 6:
        c = c[-6:]
    first = c[0]
    if first in ("0", "2", "3"):
        return f"sz{c}"
    if first in ("6", "9"):
        return f"sh{c}"
    if first in ("4", "8"):
        return f"bj{c}"
    return f"sz{c}"


def _beijing_now() -> dt.datetime:
    """北京时区当前时间（utc + 8h，不依赖 tz 数据库）。"""
    return dt.datetime.utcnow() + dt.timedelta(hours=8)


def _fetch_tencent_daily(
    symbol: str,
    start: str = DEFAULT_START,
    end: str = "",
    adjust: str = "",
) -> list[dict]:
    """按年分页拉腾讯日线，返回 [ {date, open, high, low, close, volume}, ... ] 升序。

    接口每个请求最多返回 640 行（≈2.5 年），需按年滑动分页后按日期去重。
    adjust: ""=不复权, "qfq"=前复权, "hfq"=后复权（默认 raw，与 Hermes 对齐）。
    """
    sym = _tx_symbol(symbol)
    end = end or _beijing_now().strftime("%Y%m%d")
    start_year = max(int(start[:4]), 1990)
    end_year = min(int(end[:4]) + 1, _beijing_now().year + 1)

    key = {"qfq": "qfqday", "hfq": "hfqday"}.get(adjust, "day")
    by_date: dict[str, list[str]] = {}

    for year in range(start_year, end_year):
        url = (
            "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
            f"?param={sym},day,{year}-01-01,{year + 1}-12-31,640,{adjust}"
        )
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"腾讯接口请求失败 ({year}): {exc}") from exc

        node = data.get("data", {}).get(sym, {})
        if not isinstance(node, dict):
            continue
        chunk = node.get(key) or node.get("day") or node.get("qfqday") or node.get("hfqday") or []
        # 行格式: [date, open, close, high, low, volume, ...]
        for r in chunk:
            if not isinstance(r, (list, tuple)) or len(r) < 6:
                continue
            by_date[str(r[0])[:10]] = [
                str(r[1]),  # open
                str(r[2]),  # close
                str(r[3]),  # high
                str(r[4]),  # low
                str(r[5]),  # volume
            ]

    if not by_date:
        raise RuntimeError(f"{symbol} 腾讯接口无数据")

    rows = []
    for d, (o, c, h, l, v) in by_date.items():
        d_norm = d.replace("-", "")
        if start <= d_norm <= end:
            rows.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v})
    rows.sort(key=lambda r: r["date"])
    return rows


def _drop_partial_today(rows: list[dict]) -> list[dict]:
    """盘前/盘中（北京 < 15:00）去掉今天未收盘的半截 bar，止于上一完整交易日。

    与 Hermes 手动修复一致（600089 止于 2026-08-10 完整日）。收盘后保留当日 bar。
    """
    if not rows:
        return rows
    now = _beijing_now()
    today = now.strftime("%Y-%m-%d")
    if rows[-1]["date"] == today and now.hour < 15:
        return rows[:-1]
    return rows


# ---------------------------------------------------------------------------
# 缓存写入（原子：tmp → rename，成功后删除旧文件）
# ---------------------------------------------------------------------------


def _write_cache(symbol: str, rows: list[dict], kline_dir: Path, start: str) -> Path:
    """写入 {symbol}_{start}_{last}_daily.csv，删除旧的 {symbol}_*_daily.csv。"""
    kline_dir.mkdir(parents=True, exist_ok=True)
    last_date = rows[-1]["date"].replace("-", "")
    new_path = kline_dir / f"{symbol}_{start}_{last_date}_daily.csv"
    tmp_path = kline_dir / f".{symbol}_new.csv.tmp"

    with tmp_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for r in rows:
            writer.writerow([r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]])
    tmp_path.replace(new_path)

    # 清理旧文件（同 symbol 的所有 *_daily.csv，避免 loader 模糊匹配歧义）
    for old in sorted(kline_dir.glob(f"{symbol}_*_daily.csv")):
        if old.name != new_path.name:
            try:
                old.unlink()
            except OSError:
                pass
    return new_path


# ---------------------------------------------------------------------------
# 清单
# ---------------------------------------------------------------------------


def _load_symbols(positions_path: Path, watchlist_path: Path) -> list[str]:
    """默认清单 = positions.json keys ∪ watchlist.json stocks[].symbol。"""
    syms: set[str] = set()

    if positions_path.exists():
        try:
            pos = json.loads(positions_path.read_text(encoding="utf-8"))
            if isinstance(pos, dict):
                syms.update(str(k).split(".")[0] for k in pos.keys())
            elif isinstance(pos, list):
                for p in pos:
                    if isinstance(p, dict) and p.get("symbol"):
                        syms.add(str(p["symbol"]).split(".")[0])
        except (OSError, json.JSONDecodeError):
            pass

    if watchlist_path.exists():
        try:
            wl = json.loads(watchlist_path.read_text(encoding="utf-8"))
            for s in (wl.get("stocks", []) if isinstance(wl, dict) else wl):
                if isinstance(s, dict) and s.get("symbol"):
                    syms.add(str(s["symbol"]).split(".")[0])
        except (OSError, json.JSONDecodeError):
            pass

    return sorted(syms)


def _existing_symbols(kline_dir: Path) -> list[str]:
    """--all：从现有缓存文件名提取全部 symbol。"""
    syms = set()
    for f in kline_dir.glob("*_daily.csv"):
        syms.add(f.name.split("_")[0])
    return sorted(syms)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刷新 data/kline_cache 日线缓存")
    parser.add_argument("--symbols", help="逗号分隔代码覆盖默认清单")
    parser.add_argument("--all", action="store_true", help="刷新全部现有缓存标的（慢）")
    parser.add_argument("--adjust", default="", choices=["", "qfq", "hfq"], help="复权（默认 raw 不复权）")
    parser.add_argument("--start", default=DEFAULT_START, help="起始日期 YYYYMMDD（默认 20150101）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将刷新清单，不写盘")
    parser.add_argument("--limit", type=int, default=0, help="--all 时最多刷新 N 只（0=不限）")
    args = parser.parse_args(argv)

    root = Path(os.environ.get("BAIZE_ROOT", Path(__file__).resolve().parents[1]))
    kline_dir = Path(os.environ.get("BAIZE_KLINE_DIR", root / "data" / "kline_cache"))
    positions_path = Path(os.environ.get("BAIZE_POSITIONS", root / "data" / "positions.json"))
    watchlist_path = Path(os.environ.get("BAIZE_WATCHLIST", root / "data" / "watchlist.json"))

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.all:
        symbols = _existing_symbols(kline_dir)
        if args.limit > 0:
            symbols = symbols[: args.limit]
    else:
        symbols = _load_symbols(positions_path, watchlist_path)

    if not symbols:
        print("无待刷新标的（positions/watchlist 为空且未指定 --symbols）")
        return 0

    print(f"==> 刷新 {len(symbols)} 只标的 → {kline_dir} | adjust={args.adjust or 'raw'}")
    if args.dry_run:
        for s in symbols:
            print(f"  [dry-run] {s}")
        return 0

    failed: list[str] = []
    for i, sym in enumerate(symbols, 1):
        try:
            rows = _fetch_tencent_daily(sym, start=args.start, adjust=args.adjust)
            rows = _drop_partial_today(rows)
            if len(rows) < 40:
                raise RuntimeError(f"仅 {len(rows)} 行（<40），疑似数据异常")
            path = _write_cache(sym, rows, kline_dir, args.start)
            rng = f"{rows[0]['date']} → {rows[-1]['date']}"
            print(f"  [{i}/{len(symbols)}] {sym}   {len(rows)} 行  {rng}  → {path.name}")
        except Exception as exc:
            failed.append(sym)
            print(f"  [{i}/{len(symbols)}] {sym}   FAIL: {exc}（保留原缓存）", file=sys.stderr)

    if failed:
        print(f"❌ {len(failed)} 只失败: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("✅ 全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
