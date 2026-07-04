# -*- coding: utf-8 -*-
"""批量下载 A 股 K 线数据 — 用新浪接口 (stock_zh_a_daily)。"""

import time
from pathlib import Path

import akshare as ak
import pandas as pd

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
CACHE.mkdir(parents=True, exist_ok=True)
START = "20150101"
END = "20251231"


def to_sina_code(code: str) -> str:
    """将 6 位代码转为新浪格式 (sh600519, sz000001)。"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "3", "2")):
        return f"sz{code}"
    return f"sh{code}"  # fallback


def download_batch(target: int = 200):
    cached = set()
    for f in CACHE.glob("*.csv"):
        parts = f.stem.split("_")
        if not parts[0].startswith("IDX"):
            cached.add(parts[0])

    print(f"已有: {len(cached)} 只, 目标: {target}")

    # 获取全市场代码
    df = ak.stock_zh_a_spot()
    all_codes = df["代码"].astype(str).tolist()
    names = dict(zip(df["代码"].astype(str), df["名称"].astype(str)))

    # 过滤: 排除北交所、ST、低价
    candidates = []
    for c in all_codes:
        if c in cached:
            continue
        name = names.get(c, "")
        if c.startswith("8"):
            continue
        if "ST" in name.upper():
            continue
        try:
            price = float(df[df["代码"] == c]["最新价"].iloc[0])
            if price < 3:
                continue
        except:
            pass
        candidates.append(c)

    need = min(target - len(cached), len(candidates))
    to_dl = candidates[:need]
    print(f"  候选: {len(candidates)}, 需下载: {len(to_dl)}")

    success = 0
    for i, code in enumerate(to_dl):
        sina = to_sina_code(code)
        for attempt in range(2):
            try:
                df2 = ak.stock_zh_a_daily(
                    symbol=sina,
                    start_date=START, end_date=END,
                    adjust="qfq",
                )
                if df2 is not None and len(df2) > 500:
                    df2 = df2.rename(columns={
                        "date": "date", "open": "open", "close": "close",
                        "high": "high", "low": "low", "volume": "volume",
                    })
                    if "date" in df2.columns:
                        df2["date"] = pd.to_datetime(df2["date"])
                        df2 = df2.set_index("date")
                    df2.to_csv(CACHE / f"{code}_{START}_{END}_daily.csv")
                    success += 1
                    break
                time.sleep(1)
            except Exception:
                if attempt == 0:
                    time.sleep(3)

        if (i + 1) % 30 == 0:
            new_total = len(set(f.stem.split("_")[0] for f in CACHE.glob("*.csv") if not f.stem.startswith("IDX")))
            print(f"  [{i+1}/{len(to_dl)}] 成功:{success} 总计:{new_total}")

    new_total = len(set(f.stem.split("_")[0] for f in CACHE.glob("*.csv") if not f.stem.startswith("IDX")))
    print(f"完成: 新增 {success}, 总计 {new_total} 只")


if __name__ == "__main__":
    download_batch(target=200)
