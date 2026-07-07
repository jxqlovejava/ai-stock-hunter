# -*- coding: utf-8 -*-
"""Overnight download v2 — 新浪财经 API (已验证可行，不封IP)。

用法:
  .venv/bin/python src/backtest/overnight_download.py

新浪 API:
  sh600519 → 上海主板/科创板
  sz000001 → 深圳主板/创业板
  scale=240  → 日K线
  datalen=3000 → 最多3000条 (~12年)
"""

import json
import os
import ssl
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

for k in list(os.environ.keys()):
    if "proxy" in k.lower():
        del os.environ[k]

ctx = ssl.create_default_context()
ph = urllib.request.ProxyHandler({})
urllib.request.install_opener(urllib.request.build_opener(ph, urllib.request.HTTPSHandler(context=ctx)))

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
CACHE.mkdir(parents=True, exist_ok=True)
LOG = CACHE / "download_log.txt"
TARGET = 500

SINA_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def to_sina_code(code: str) -> str:
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def download_one(code: str) -> bool:
    f = CACHE / f"{code}_20150101_20251231_daily.csv"
    if f.exists():
        return True

    symbol = to_sina_code(code)
    url = f"{SINA_URL}?symbol={symbol}&scale=240&ma=no&datalen=3000"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        if not data or len(data) < 500:
            return False

        rows = [
            {
                "date": d["day"],
                "open": float(d["open"]),
                "close": float(d["close"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "volume": float(d["volume"]),
            }
            for d in data
        ]
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df.sort_index()
        # Filter to 2015-2025 range
        df = df["2015-01-01":"2025-12-31"]
        if len(df) < 500:
            return False
        df.to_csv(f)
        return True
    except Exception:
        return False


def main():
    log(f"新浪API下载器启动")

    spot = ak.stock_zh_a_spot()
    codes = spot["代码"].astype(str).tolist()
    names = dict(zip(spot["代码"].astype(str), spot["名称"].astype(str)))

    existing = set(
        f.stem.split("_")[0]
        for f in CACHE.glob("*_20150101_20251231_daily.csv")
        if not f.stem.startswith("IDX")
    )
    to_dl = [
        c
        for c in codes
        if c not in existing
        and not c.startswith("8")
        and "ST" not in names.get(c, "").upper()
    ]
    log(f"已有: {len(existing)}, 需下载: {len(to_dl)}, 目标: {TARGET}")

    added = 0
    errors = 0
    start = time.time()

    for i, code in enumerate(to_dl):
        if len(existing) + added >= TARGET:
            break

        if download_one(code):
            added += 1
            if added % 50 == 0:
                elapsed = (time.time() - start) / 60
                log(f"  +{added} 总计:{len(existing)+added} ({elapsed:.0f}min)")
        else:
            errors += 1

        # Adaptive delay
        if errors >= 5:
            time.sleep(3)
            errors = 0
        else:
            time.sleep(0.3)  # Sina is generous with rate limits

    total = len(existing) + added
    elapsed = (time.time() - start) / 60
    log(f"✅ 完成! 新增:{added} 总计:{total} ({elapsed:.0f}min)")


if __name__ == "__main__":
    main()
