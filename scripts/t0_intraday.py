#!/usr/bin/env python3
"""
T+0 日内时机深度分析工具
用法: .venv/bin/python scripts/t0_intraday.py <code> [--date YYYY-MM-DD]
示例: .venv/bin/python scripts/t0_intraday.py 002460
      .venv/bin/python scripts/t0_intraday.py 600089 --date 2026-07-14
"""

import sys
import argparse
from datetime import datetime
import numpy as np
import pandas as pd
from mootdx.quotes import Quotes


def safe_float(val, default=0.0):
    """Guard against None/NaN in format strings."""
    if val is None:
        return default
    if isinstance(val, (int, float)) and not np.isfinite(val):
        return default
    return float(val)


def get_intraday_bars(code, freq=1, count=240):
    """Fetch intraday bars. freq: 1=15min, 3=5min."""
    client = Quotes.factory(market="std")
    bars = client.bars(symbol=code, frequency=freq, start=0, offset=count)
    if bars is None or len(bars) == 0:
        raise ValueError(f"无法获取 {code} 分时数据")
    if "datetime" in bars.columns:
        bars = bars.drop(columns=["datetime"])
    bars = bars.sort_index()
    return bars


def analyze(code, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    target_date = pd.Timestamp(date_str).date()

    bars = get_intraday_bars(code)
    today = bars[bars.index.date == target_date]
    if len(today) == 0:
        # fallback: latest available trading day
        dates = sorted(set(bars.index.date))
        today = bars[bars.index.date == dates[-1]]
        target_date = dates[-1]
        print(f"[WARN] {date_str} 无数据，使用最近交易日 {target_date}")

    o = today["open"].values.astype(float)
    c = today["close"].values.astype(float)
    h = today["high"].values.astype(float)
    l = today["low"].values.astype(float)
    v = today["volume"].values.astype(float)
    amt = today["amount"].values.astype(float)

    # ---- Previous day reference ----
    prev_dates = sorted(set(bars.index.date))
    prev_idx = prev_dates.index(target_date) - 1 if target_date in prev_dates else -2
    prev_close = 0.0
    prev_low = 0.0
    if prev_idx >= 0:
        prev_day = bars[bars.index.date == prev_dates[prev_idx]]
        if len(prev_day) > 0:
            prev_close = float(prev_day["close"].iloc[-1])
            prev_low = float(prev_day["low"].min())

    # ---- VWAP ----
    typical = (h + l + c) / 3.0
    vwap_val = np.sum(amt * typical) / np.sum(amt) if np.sum(amt) > 0 else c[-1]
    vwap_val = safe_float(vwap_val)

    # ---- POC (Volume Profile) ----
    n_bins = 20
    price_bins = np.linspace(float(l.min()), float(h.max()), n_bins)
    vol_profile = np.zeros(n_bins - 1)
    for i in range(n_bins - 1):
        mask = (h >= price_bins[i]) & (l <= price_bins[i + 1])
        vol_profile[i] = float(v[mask].sum())
    poc = safe_float((price_bins[np.argmax(vol_profile)] + price_bins[np.argmax(vol_profile) + 1]) / 2.0)

    # ---- Buy/Sell Pressure ----
    buy_p, sell_p = 0.0, 0.0
    for i in range(len(c)):
        body = c[i] - o[i]
        denom = float(h[i] - l[i]) if h[i] != l[i] else 1.0
        if body > 0:
            buy_p += v[i] * body / denom
        elif body < 0:
            sell_p += v[i] * abs(body) / denom
    total_pressure = buy_p + sell_p
    buy_pct = safe_float(buy_p / total_pressure * 100.0 if total_pressure > 0 else 50.0)

    # ---- Multi-day daily bars ----
    daily = bars.resample("D").agg(
        {"open": "first", "close": "last", "high": "max", "low": "min", "volume": "sum"}
    ).dropna().tail(15)
    d_closes = daily["close"].values.astype(float)
    n = len(d_closes)
    ma5 = safe_float(float(np.mean(d_closes[-5:])), None) if n >= 5 else None
    ma10 = safe_float(float(np.mean(d_closes[-10:])), None) if n >= 10 else None

    # ---- Score ----
    score = 0
    signals = []

    score += 15
    signals.append(("+15", "日内收阳，低开高走" if c[-1] > o[0] else "日内收阳"))
    score += 10
    signals.append(("+10", "收盘{:.2f}>VWAP{:.2f}".format(c[-1], vwap_val)))

    if buy_pct > 55:
        score += 10
        signals.append(("+10", "买方主导{:.0f}%".format(buy_pct)))
    elif buy_pct < 45:
        score -= 10
        signals.append(("-10", "卖方主导{:.0f}%".format(100 - buy_pct)))

    if prev_low > 0 and l.min() < prev_low:
        score -= 20
        signals.append(("-20", "创新低{:.2f}<前低{:.2f}".format(l.min(), prev_low)))
    elif prev_low > 0:
        score += 10
        signals.append(("+10", "守住前低{:.2f}".format(prev_low)))

    amp = (h.max() / l.min() - 1) * 100
    if amp > 5:
        score -= 5
        signals.append(("-5", "振幅{:.1f}%偏高".format(amp)))
    else:
        score += 5
        signals.append(("+5", "振幅正常"))

    if ma5 is not None and c[-1] < ma5:
        score -= 15
        signals.append(("-15", "收盘低于MA5({:.2f})".format(ma5)))
    if ma5 is not None and ma10 is not None and ma5 < ma10:
        score -= 10
        signals.append(("-10", "MA5({:.2f})<MA10({:.2f})死叉".format(ma5, ma10)))

    # -- Tail session check --
    tail = today[today.index.hour >= 14]
    if len(tail) >= 2:
        tc = tail["close"].values
        tchg = (tc[-1] / tc[-2] - 1) * 100
        if tchg > 0.3:
            score += 10
            signals.append(("+10", "尾盘资金流入{:+.2f}%".format(tchg)))
        elif tchg < -0.3:
            score -= 10
            signals.append(("-10", "尾盘资金流出{:+.2f}%".format(tchg)))

    # -- Volume trend --
    if prev_idx >= 0:
        yest = bars[bars.index.date == prev_dates[prev_idx]]
        if len(yest) > 0:
            today_vol = float(v.sum())
            yest_vol = float(yest["volume"].sum())
            if yest_vol > 0 and today_vol < yest_vol * 0.8:
                score -= 10
                signals.append(("-10", "缩量反弹(今日{:.0f}万<昨日{:.0f}万)".format(today_vol / 1e4, yest_vol / 1e4)))

    # -- Consecutive down streak --
    down_streak = 0
    for i in range(len(d_closes) - 1, 0, -1):
        if d_closes[i] < d_closes[i - 1]:
            down_streak += 1
        else:
            break
    if down_streak >= 5 and c[-1] > o[0]:
        score -= 5
        signals.append(("-5", "{}连阴后首阳，追高风险".format(down_streak)))

    # ---- Output ----
    print("=" * 70)
    print("  T+0 日内深度分析 — {} ({})".format(code, target_date))
    print("=" * 70)
    print()
    print("关键价位")
    print("  开盘: {:.2f}  收盘: {:.2f}".format(o[0], c[-1]))
    if prev_close > 0:
        print("  前收: {:.2f}  涨跌: {:+.2f}%".format(prev_close, (c[-1] / prev_close - 1) * 100))
    print("  最高: {:.2f}  最低: {:.2f}  振幅: {:.2f}%".format(h.max(), l.min(), amp))
    print("  VWAP: {:.2f}  POC: {:.2f}".format(vwap_val, poc))
    if prev_low > 0:
        print("  前低: {:.2f}".format(prev_low))
    print("  成交额: {:.2f}亿  成交量: {:.0f}万手".format(amt.sum() / 1e8, v.sum() / 1e4))
    print()

    print("日内四段结构")
    slots = [
        ("早盘(09:30-10:30)", today.between_time("09:30", "10:30")),
        ("午前(10:30-11:30)", today.between_time("10:30", "11:30")),
        ("午后(13:00-14:00)", today.between_time("13:00", "14:00")),
        ("尾盘(14:00-15:00)", today.between_time("14:00", "15:00")),
    ]
    for name, slot in slots:
        if len(slot) > 0:
            sc, sa = slot["close"], slot["amount"].sum()
            chg = (sc.iloc[-1] / sc.iloc[0] - 1) * 100
            print("  {}: {:.2f}->{:.2f} {:+.2f}% | 额:{:.2f}亿".format(
                name, sc.iloc[0], sc.iloc[-1], chg, sa / 1e8))
    print()

    buy_bar = "#" * max(1, int(buy_pct / 3))
    sell_bar = "#" * max(1, int((100 - buy_pct) / 3))
    print("买卖力量")
    print("  买方: {:.1f}M ({:.1f}%) {}".format(buy_p / 1e6, buy_pct, buy_bar))
    print("  卖方: {:.1f}M ({:.1f}%) {}".format(sell_p / 1e6, 100 - buy_pct, sell_bar))
    print()

    print("多日趋势 (近{}日)".format(min(7, n)))
    for idx, row in daily.tail(7).iterrows():
        chg = (row["close"] / row["open"] - 1) * 100
        print("  {} | O:{:6.2f} C:{:6.2f} | {:+.2f}% | 量:{:5.0f}万手".format(
            str(idx)[:10], row["open"], row["close"], chg, row["volume"] / 1e4))
    ma_parts = []
    if ma5 is not None:
        ma_parts.append("MA5={:.2f}".format(ma5))
    if ma10 is not None:
        ma_parts.append("MA10={:.2f}".format(ma10))
    if ma_parts:
        print("  " + " | ".join(ma_parts))
    vs_parts = []
    if ma5 is not None:
        vs_parts.append("vs MA5: {:+.1f}%".format((c[-1] / ma5 - 1) * 100))
    if ma10 is not None:
        vs_parts.append("vs MA10: {:+.1f}%".format((c[-1] / ma10 - 1) * 100))
    if vs_parts:
        print("  收盘 " + " | ".join(vs_parts))
    print()

    print("T+0 评分卡")
    for sig, desc in signals:
        print("  {:>5}  {}".format(sig, desc))
    print("  " + "-" * 40)
    print("  总分: {}".format(score))
    if score >= 50:
        print("  建议: [可操作] 日内偏多，逢低可做T")
    elif score >= 20:
        print("  建议: [谨慎] 有反弹信号但趋势未确认，等次日验证")
    elif score >= -10:
        print("  建议: [偏空] 反弹是减仓窗口，不宜加仓")
    else:
        print("  建议: [强烈偏空] 止损优先，不参与反弹")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T+0 日内时机深度分析")
    parser.add_argument("code", help="股票代码 (如 002460)")
    parser.add_argument("--date", default=None, help="分析日期 YYYY-MM-DD (默认今日)")
    args = parser.parse_args()
    analyze(args.code, args.date)
