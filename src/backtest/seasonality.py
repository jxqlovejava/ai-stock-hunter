"""季节性风险窗口回测验证。

验证自媒体断言《A股每年都有4个危险的时间窗口》(来源: 0x鸣人, T3 三级信源):
  1. YEAR_END_LIQUIDITY  12月中下旬-1月初 流动性枯竭
  2. APRIL_EARNINGS      4月底 财报业绩双杀
  3. AUGUST_INTERIM      8月底 中报证伪
  4. OCTOBER_RETAIL      10月底 季末获利了结

方法: 取沪深300 近 10 年日线，对每个交易日标记"处于哪个窗口"，统计
      窗口内 vs 窗口外 未来 HORIZON 日收益率（均值/胜率/年化），输出对比表。

结论判定:
  - 窗口内远期收益显著为负 或 明显跑输基线 → 支持该断言（可考虑调强折扣）
  - 不显著 → 保持软提示（默认 WARN + 轻折扣）
  - 数据不足 → 不采纳
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.calendar.seasonal_windows import (
    SeasonalWindow,
    _WINDOW_META,
    detect_seasonal_windows,
)

logger = logging.getLogger(__name__)

HORIZON = 5  # 前瞻持有天数
MIN_DAYS = 252  # 最少数据天数


def _load_index_data(
    start_date: str = "20150101", end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """加载沪深300 日线（复用 backtest.runner 的缓存下载，失败用 akshare 直连指数）。"""
    end_date = end_date or date.today().strftime("%Y%m%d")
    try:
        from src.backtest.runner import download_kline

        df = download_kline("000300", start_date, end_date, force=False)
        if df is not None and len(df) >= MIN_DAYS:
            return df
    except Exception as exc:  # noqa: BLE001
        logger.debug("download_kline(000300) failed: %s", exc)

    # 降级: 指数专用接口
    try:
        import akshare as ak

        raw = ak.stock_zh_index_daily(symbol="sh000300")
        if raw is not None and len(raw):
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.set_index("date")
            return raw
    except Exception as exc:  # noqa: BLE001
        logger.debug("stock_zh_index_daily(sh000300) failed: %s", exc)
    return None


def _forward_return(closes, i: int, horizon: int = HORIZON) -> Optional[float]:
    """第 i 日起未来 horizon 个交易日的收益率。"""
    j = i + horizon
    if j >= len(closes) or closes[i] is None or closes[i] == 0:
        return None
    return (closes[j] / closes[i]) - 1.0


def _windows_of(date_obj: date) -> set[SeasonalWindow]:
    """某日历日处于哪些窗口。"""
    return {w.window for w in detect_seasonal_windows(date_obj)}


def _window_max_drawdown(dates, closes, window: SeasonalWindow) -> float:
    """窗口内最大回撤：把落入窗口的连续交易日分段，取段内(段首→段内最低)最差回撤。"""
    in_run = False
    seg_start = 0.0
    worst = 0.0
    for d, c in zip(dates, closes):
        dd = d.date() if hasattr(d, "date") else d
        active = window in _windows_of(dd)
        if active and not in_run:
            in_run = True
            seg_start = c
        elif active and in_run:
            if seg_start and seg_start > 0:
                worst = max(worst, (seg_start - c) / seg_start)
        elif not active and in_run:
            in_run = False
    return worst


def run_seasonality_backtest(
    start_date: str = "20150101",
    end_date: Optional[str] = None,
    horizon: int = HORIZON,
) -> dict:
    """运行季节性窗口回测，返回各窗口统计 dict 并打印对比表。"""
    df = _load_index_data(start_date, end_date)
    if df is None or len(df) < MIN_DAYS:
        print(f"[SEASONALITY] 数据不足（<{MIN_DAYS} 个交易日），无法验证。")
        return {}

    closes = df["close"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    # 每日前视收益率
    daily_fwd: list[tuple[set[SeasonalWindow], float]] = []
    for i in range(n - horizon):
        fwd = _forward_return(closes, i, horizon)
        if fwd is None:
            continue
        d = dates[i]
        if hasattr(d, "date"):
            d = d.date()
        daily_fwd.append((_windows_of(d), fwd))

    all_fwd = [f for _, f in daily_fwd]
    baseline_mean = sum(all_fwd) / len(all_fwd) if all_fwd else 0.0
    baseline_win = sum(1 for f in all_fwd if f > 0) / len(all_fwd) if all_fwd else 0.0

    print("=" * 86)
    print(f"季节性风险窗口回测  |  沪深300  {dates[0].date()} ~ {dates[-1].date()}  |  前视 {horizon} 交易日")
    print("=" * 86)
    print(f"基线(全年)      : 均值 {baseline_mean*100:+.2f}%   胜率 {baseline_win*100:.1f}%   (n={len(all_fwd)})")
    print("-" * 86)
    print(f"{'窗口':<12}{'窗口均值':>10}{'窗口胜率':>9}{'窗口最大回撤':>12}{'基线均值':>10}{'跑输':>8}{'n':>5}  结论")
    print("-" * 86)

    results: dict[str, dict] = {}
    for window in SeasonalWindow:
        meta = _WINDOW_META[window]
        in_ret = [f for ws, f in daily_fwd if window in ws]
        max_dd = _window_max_drawdown(dates, closes, window)
        if len(in_ret) < 5:
            verdict = "样本不足"
            line = "—"
        else:
            in_mean = sum(in_ret) / len(in_ret)
            in_win = sum(1 for f in in_ret if f > 0) / len(in_ret)
            under = (in_mean - baseline_mean) * 100
            if under < -0.5 and in_mean < 0:
                verdict = "✅ 支持"
            elif under < 0:
                verdict = "⚠️ 弱支持"
            elif under < 0.5:
                verdict = "❌ 不显著"
            else:
                verdict = "❌ 反向"
            line = f"{in_mean*100:+.2f}%"
            results[window.value] = {
                "window_mean": round(in_mean, 5),
                "window_win_rate": round(in_win, 4),
                "window_max_drawdown": round(max_dd, 4),
                "baseline_mean": round(baseline_mean, 5),
                "underperformance_bps": round(under * 100, 1),
                "n": len(in_ret),
                "verdict": verdict,
            }
        print(
            f"{meta.name:<12}{line:>10}"
            f"{results.get(window.value, {}).get('window_win_rate', 0)*100:>8.1f}%"
            f"{max_dd*100:>11.1f}%"
            f"{baseline_mean*100:>10.2f}%"
            f"{results.get(window.value, {}).get('underperformance_bps', 0):>7.0f}"
            f"{len(in_ret):>5}  {verdict}"
        )

    # 任意窗口内 vs 全年基线
    any_in = [f for ws, f in daily_fwd if ws]
    if any_in:
        any_mean = sum(any_in) / len(any_in)
        any_win = sum(1 for f in any_in if f > 0) / len(any_in)
        print("-" * 78)
        print(
            f"任一窗口内     : 均值 {any_mean*100:+.2f}%   胜率 {any_win*100:.1f}%"
            f"   (跑输基线 {(any_mean-baseline_mean)*100:+.2f}pct, n={len(any_in)})"
        )
    today_active = _windows_of(date.today())
    if today_active:
        names = "、".join(_WINDOW_META[w].name for w in today_active)
        print(f"⚠️  今天处于: {names}")
    else:
        print("今天不处于任何季节性危险窗口。")
    print("=" * 78)
    return results


if __name__ == "__main__":
    run_seasonality_backtest()
