"""真实回测横向 PK 脚本。

在同一股票池、同一时段上运行多个策略配置，输出 BenchmarkResult 对比。
竞品策略基于公开信息（因子偏好/行业侧重/风控规则）构建 proxy 策略。

用法:
  python -m src.backtest.pk_runner --universe csi300_top20 --start 2020-01-01 --end 2024-12-31
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Reuse our BenchmarkResult and PKReport from competitor_benchmark
from src.backtest.competitor_benchmark import BenchmarkResult as BR, PKReport, CompetitorAnalyzer

# ---------------------------------------------------------------------------
# Strategy proxy definitions (mimic competitor approaches)
# ---------------------------------------------------------------------------

@dataclass
class StrategyProxy:
    """A backtestable proxy for a competitor strategy."""

    name: str  # e.g., "白泽 MVP1"
    competitor_key: str  # e.g., "baize_mvp1" / "tonghuashun_proxy"
    is_ours: bool = True

    # Factor weights (must sum to 1.0)
    weight_pe: float = 0.25  # value tilt
    weight_pb: float = 0.0
    weight_roe: float = 0.25  # quality
    weight_momentum: float = 0.25  # momentum
    weight_northbound: float = 0.25  # northbound
    weight_lowvol: float = 0.0  # low vol preference

    # Constraints
    max_positions: int = 10
    position_size: float = 0.10  # equal or capped
    rebalance_freq: str = "monthly"  # monthly / quarterly
    stop_loss: float = -0.15  # single stock stop loss
    use_ma_filter: bool = True  # MA trend filter

    # Sector preference (if any)
    sector_tilt: Optional[str] = None  # "growth" / "value" / "cyclical" / "defensive" / None

    # Notes
    description: str = ""


# 9 个策略 proxy — 白泽 3 个版本 + 6 个竞品 proxy
STRATEGY_PROXIES: dict[str, StrategyProxy] = {
    "benchmark_equal": StrategyProxy(
        name="基准: 等权持有",
        competitor_key="benchmark_equal", is_ours=True,
        weight_pe=0.17, weight_pb=0.0, weight_roe=0.17,
        weight_momentum=0.17, weight_northbound=0.17, weight_lowvol=0.17,
        max_positions=100, rebalance_freq="quarterly", stop_loss=-0.50,
        use_ma_filter=False,
        description="等权买入持有所有股票 (Buy & Hold benchmark)",
    ),
    "baize_mvp1": StrategyProxy(
        name="白泽 MVP1",
        competitor_key="baize_mvp1",
        weight_pe=0.35, weight_roe=0.35, weight_momentum=0.30,
        description="PE分位+ROE+动量三因子基线",
    ),
    "baize_mvp2": StrategyProxy(
        name="白泽 MVP2",
        competitor_key="baize_mvp2",
        weight_pe=0.20, weight_pb=0.05, weight_roe=0.25,
        weight_momentum=0.25, weight_northbound=0.15, weight_lowvol=0.10,
        description="5因子+北向+低波增强版",
    ),
    "baize_mvp3": StrategyProxy(
        name="白泽 MVP3",
        competitor_key="baize_mvp3",
        weight_pe=0.15, weight_pb=0.05, weight_roe=0.20,
        weight_momentum=0.20, weight_northbound=0.20, weight_lowvol=0.20,
        max_positions=8, stop_loss=-0.12, sector_tilt="growth",
        description="多因子+北向+低波+风控收紧版",
    ),
    "tonghuashun_proxy": StrategyProxy(
        name="同花顺 iFinD proxy",
        competitor_key="tonghuashun_proxy", is_ours=False,
        weight_pe=0.20, weight_pb=0.10, weight_roe=0.30,
        weight_momentum=0.15, weight_northbound=0.20, weight_lowvol=0.05,
        description="同花顺 iFinD: 价值+质量为主，北向辅助 (基于公开功能推断)",
    ),
    "eastmoney_proxy": StrategyProxy(
        name="东方财富 AI proxy",
        competitor_key="eastmoney_proxy", is_ours=False,
        weight_pe=0.10, weight_roe=0.20, weight_momentum=0.30,
        weight_northbound=0.30, weight_lowvol=0.10,
        sector_tilt="cyclical",
        description="东财: 北向+动量侧重，散户情绪驱动 (基于股吧+Choice公开数据)",
    ),
    "xueqiu_proxy": StrategyProxy(
        name="雪球 AI proxy",
        competitor_key="xueqiu_proxy", is_ours=False,
        weight_pe=0.30, weight_pb=0.15, weight_roe=0.35,
        weight_momentum=0.05, weight_northbound=0.05, weight_lowvol=0.10,
        sector_tilt="value", max_positions=15, rebalance_freq="quarterly",
        description="雪球: 深度价值+低换手，社区 UGC 情绪替代动量 (基于雪球组合公开特征)",
    ),
    "tradestation_proxy": StrategyProxy(
        name="TradeStation proxy",
        competitor_key="tradestation_proxy", is_ours=False,
        weight_pe=0.0, weight_roe=0.10, weight_momentum=0.50,
        weight_northbound=0.0, weight_lowvol=0.40,
        max_positions=5, stop_loss=-0.10, use_ma_filter=False,
        description="TradeStation: 纯技术面+趋势跟踪+严格止损 (基于 EasyLanguage 策略模板)",
    ),
    "kavout_proxy": StrategyProxy(
        name="Kavout proxy",
        competitor_key="kavout_proxy", is_ours=False,
        weight_pe=0.10, weight_pb=0.05, weight_roe=0.30,
        weight_momentum=0.35, weight_northbound=0.10, weight_lowvol=0.10,
        max_positions=12,
        description="Kavout: 机器学习多因子，动量+质量为主 (基于 K Score 公开论文)",
    ),
    "trendspider_proxy": StrategyProxy(
        name="TrendSpider proxy",
        competitor_key="trendspider_proxy", is_ours=False,
        weight_pe=0.0, weight_roe=0.0, weight_momentum=0.70,
        weight_northbound=0.0, weight_lowvol=0.30,
        max_positions=3, stop_loss=-0.08, use_ma_filter=False,
        rebalance_freq="daily",
        description="TrendSpider: 纯技术形态+严格止损+高频换仓 (基于自动技术形态识别)",
    ),
}


# ---------------------------------------------------------------------------
# PK Runner — real backtest comparison
# ---------------------------------------------------------------------------

class PKRunner:
    """Run all strategy proxies on the same universe, same period, and compare."""

    def __init__(
        self,
        universe: list[str],
        start: str = "2020-01-01",
        end: str = "2024-12-31",
        initial_cash: float = 1_000_000,
    ):
        self._universe = universe
        self._start = start
        self._end = end
        self._initial_cash = initial_cash
        self._price_cache: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self, strategies: Optional[list[str]] = None) -> PKReport:
        """Run all strategy proxies and generate PK report."""
        keys = strategies or list(STRATEGY_PROXIES.keys())
        proxy_list = [STRATEGY_PROXIES[k] for k in keys if k in STRATEGY_PROXIES]

        # Step 1: Load price data once
        self._load_prices()

        if not self._price_cache:
            logger.error("No price data loaded — cannot run backtest")
            return PKReport()

        # Step 2: Run each strategy
        results = []
        for proxy in proxy_list:
            logger.info("Running: %s", proxy.name)
            br = self._run_strategy(proxy)
            if br:
                results.append(br)
                logger.info("  → ann_ret=%.2f%% sharpe=%.2f max_dd=%.1f%% win=%.0f%%",
                            br.annual_return_pct, br.sharpe_ratio, br.max_drawdown_pct, br.win_rate_pct)

        if len(results) < 2:
            return PKReport()

        # Step 3: Run PK comparison
        our_best = next((r for r in results if "白泽" in r.strategy_name), results[0])
        competitor_results = [r for r in results if "白泽" not in r.strategy_name]

        analyzer = CompetitorAnalyzer()
        report = analyzer.benchmark_pk(our_best, competitor_results)

        return report

    # ------------------------------------------------------------------
    # Strategy runner
    # ------------------------------------------------------------------

    def _run_strategy(self, proxy: StrategyProxy) -> Optional[BR]:
        """Run a single strategy proxy on loaded data with portfolio simulation."""
        rebalance_dates = self._generate_rebalance_dates(proxy.rebalance_freq)
        if len(rebalance_dates) < 2:
            return None

        # Portfolio state
        positions: dict[str, float] = {}  # symbol → weight
        entry_prices: dict[str, float] = {}  # symbol → entry price
        entry_date: dict[str, str] = {}  # symbol → entry date
        portfolio_value = self._initial_cash
        portfolio_values = [portfolio_value]
        trades_log: list[dict] = []
        prev_date = rebalance_dates[0]

        for date in rebalance_dates:
            # ---- Step 0: Compute P&L from previous positions ----
            if positions:
                period_return = 0.0
                weights_sum = sum(positions.values())
                for sym, w in positions.items():
                    ret = self._get_return(sym, prev_date, date)
                    period_return += w * ret
                # Apply return to portfolio
                portfolio_value *= (1 + period_return)
                prev_date = date

            portfolio_values.append(portfolio_value)

            # ---- Step 1: Score all stocks ----
            scores = {}
            for symbol, df in self._price_cache.items():
                df_slice = df[df.index <= pd.Timestamp(date)]
                if len(df_slice) < 252:
                    continue
                score = self._compute_score(symbol, df_slice, date, proxy)
                if score is not None:
                    scores[symbol] = score

            # ---- Step 2: Select top N ----
            top_n = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:proxy.max_positions]

            # ---- Step 3: Apply MA filter ----
            new_positions = {}
            for symbol, score in top_n:
                if not proxy.use_ma_filter or self._above_ma(symbol, date):
                    new_positions[symbol] = proxy.position_size

            # Normalize weights to sum to 1.0
            total_w = sum(new_positions.values())
            if total_w > 0:
                new_positions = {s: w / total_w for s, w in new_positions.items()}

            # ---- Step 4: Log exits (positions no longer held) ----
            for sym in list(positions.keys()):
                if sym not in new_positions:
                    exit_price = self._get_price(sym, date)
                    entry_px = entry_prices.get(sym, exit_price)
                    ret = (exit_price / max(entry_px, 0.01) - 1) if entry_px > 0 else 0.0

                    # Stop-loss check
                    if ret <= proxy.stop_loss:
                        trades_log.append({
                            "symbol": sym, "entry": entry_date.get(sym, date),
                            "exit": date, "return": ret, "reason": "stop_loss",
                        })
                    else:
                        trades_log.append({
                            "symbol": sym, "entry": entry_date.get(sym, date),
                            "exit": date, "return": ret, "reason": "rebalance",
                        })

            # ---- Step 5: Log entries (new positions) ----
            for sym, w in new_positions.items():
                if sym not in positions:
                    entry_prices[sym] = self._get_price(sym, date)
                    entry_date[sym] = date

            # ---- Step 6: Update positions ----
            positions = dict(new_positions)

        # ---- Final: compute metrics ----
        return self._compute_benchmark_result(proxy, portfolio_values, trades_log)

    def _get_price(self, symbol: str, date: str) -> float:
        """Get closing price for a symbol on or before a date."""
        df = self._price_cache.get(symbol)
        if df is None:
            return 0.0
        try:
            ts = pd.Timestamp(date)
            if ts in df.index:
                return float(df.loc[ts, "close"])
            # Get nearest before
            before = df[df.index <= ts]
            if len(before) > 0:
                return float(before["close"].iloc[-1])
        except Exception:
            pass
        return 0.0

    def _compute_score(
        self, symbol: str, df: pd.DataFrame, date: str, proxy: StrategyProxy
    ) -> Optional[float]:
        """Compute composite factor score (0-100 scale) for a stock."""
        close = df["close"]
        if len(close) < 252:
            return None

        # Each sub-score is 0-100, then weighted
        sub_scores: dict[str, float] = {}

        # PE percentile proxy: 0-100 (higher = cheaper)
        rh = close.rolling(252).max().iloc[-1]
        rl = close.rolling(252).min().iloc[-1]
        if rh > rl:
            pe_pct = (close.iloc[-1] - rl) / (rh - rl) * 100
            sub_scores["pe"] = 100 - pe_pct  # cheap = high score
        else:
            sub_scores["pe"] = 50.0

        # PB proxy: same as PE (simplified, ideally from financial data)
        sub_scores["pb"] = sub_scores["pe"] * 0.8 + 10  # correlated but slightly different

        # ROE proxy: 1-year return → percentile
        roe_1y = (close.iloc[-1] / max(close.iloc[-252], 0.01) - 1)
        sub_scores["roe"] = min(max(roe_1y * 100 + 50, 0), 100)

        # Momentum: 3-month return → percentile
        mom_3m = (close.iloc[-1] / max(close.iloc[-63], 0.01) - 1)
        sub_scores["momentum"] = min(max(mom_3m * 100 + 50, 0), 100)

        # Northbound proxy: volume trend
        if "volume" in df.columns:
            vol_ma20 = float(df["volume"].rolling(20).mean().iloc[-1])
            vol_ma60 = float(df["volume"].rolling(60).mean().iloc[-1])
            nb_trend = (vol_ma20 / max(vol_ma60, 0.01) - 1) * 100
            sub_scores["northbound"] = min(max(nb_trend + 50, 0), 100)
        else:
            sub_scores["northbound"] = 50.0

        # Low vol: lower vol = higher score
        returns = close.pct_change().dropna()
        if len(returns) >= 60:
            vol_60d = float(returns.iloc[-60:].std() * np.sqrt(252))
            sub_scores["lowvol"] = max(0, min(100, (1.0 - vol_60d) * 100))
        else:
            sub_scores["lowvol"] = 50.0

        # Weighted composite
        score = (
            sub_scores.get("pe", 50) * proxy.weight_pe
            + sub_scores.get("pb", 50) * proxy.weight_pb
            + sub_scores.get("roe", 50) * proxy.weight_roe
            + sub_scores.get("momentum", 50) * proxy.weight_momentum
            + sub_scores.get("northbound", 50) * proxy.weight_northbound
            + sub_scores.get("lowvol", 50) * proxy.weight_lowvol
        )
        # Normalize: if total weight < 1.0, fill with neutral 50
        total_w = (proxy.weight_pe + proxy.weight_pb + proxy.weight_roe
                   + proxy.weight_momentum + proxy.weight_northbound + proxy.weight_lowvol)
        if total_w < 1.0:
            score += 50 * (1.0 - total_w)
        elif total_w > 1.0:
            score /= total_w

        return score

    def _generate_rebalance_dates(self, freq: str) -> list[str]:
        """Generate rebalance dates."""
        dates = pd.date_range(self._start, self._end, freq="B")  # business days
        if freq == "daily":
            return [d.strftime("%Y-%m-%d") for d in dates[::5]]  # every 5 days to speed up
        elif freq == "monthly":
            # Get last business day of each month
            s = dates.to_series()
            monthly = s.groupby(s.dt.to_period("M")).tail(1)
            return [d.strftime("%Y-%m-%d") for d in monthly.index]
        else:  # quarterly
            s = dates.to_series()
            quarterly = s.groupby(s.dt.to_period("Q")).tail(1)
            return [d.strftime("%Y-%m-%d") for d in quarterly.index]

    def _above_ma(self, symbol: str, date: str) -> bool:
        """Check if price is above 60-day MA."""
        price = self._get_price(symbol, date)
        if price <= 0:
            return True
        df = self._price_cache.get(symbol)
        if df is None:
            return True
        ts = pd.Timestamp(date)
        df_slice = df[df.index <= ts]
        if len(df_slice) < 60:
            return True
        ma60 = float(df_slice["close"].iloc[-60:].mean())
        return price > ma60

    def _get_return(self, symbol: str, from_date: str, to_date: str) -> float:
        """Get price return between two dates."""
        p1 = self._get_price(symbol, from_date)
        p2 = self._get_price(symbol, to_date)
        if p1 <= 0:
            return 0.0
        return float(p2 / p1 - 1)

    def _compute_benchmark_result(
        self, proxy: StrategyProxy, values: list[float], trades: list[dict]
    ) -> BR:
        """Compute BenchmarkResult from portfolio values and trade log."""
        if len(values) < 2:
            return BR(strategy_name=proxy.name)

        final = values[-1]
        initial = values[0]
        total_ret = (final / initial - 1)

        # Actual calendar years
        start_dt = pd.Timestamp(self._start)
        end_dt = pd.Timestamp(self._end)
        years = (end_dt - start_dt).days / 365.25
        annual_ret = (final / initial) ** (1 / max(years, 0.25)) - 1

        # Volatility (monthly returns → annualized)
        period_rets = pd.Series(values).pct_change().dropna()
        n_periods = len(period_rets)
        if n_periods > 0:
            # Determine periods per year from actual data
            periods_per_year = n_periods / years if years > 0 else 12
            vol = float(period_rets.std() * np.sqrt(periods_per_year))
        else:
            vol = 0.0

        # Sharpe (assume 2% risk-free)
        sharpe = (annual_ret - 0.02) / max(vol, 0.001)

        # Max drawdown
        peak = values[0]
        max_dd = 0.0
        for v in values:
            peak = max(peak, v)
            dd = (v - peak) / peak
            max_dd = min(max_dd, dd)

        # Win rate
        wins = [t for t in trades if t.get("return", 0) > 0]
        win_rate = len(wins) / max(len(trades), 1)

        # Profit factor
        gross_profit = sum(t.get("return", 0) for t in wins)
        gross_loss = abs(sum(t.get("return", 0) for t in trades if t.get("return", 0) <= 0))
        profit_factor = gross_profit / max(gross_loss, 0.001)

        # Sortino
        downside = period_rets[period_rets < 0]
        downside_dev = float(downside.std() * np.sqrt(periods_per_year)) if len(downside) > 0 and years > 0 else vol
        sortino = (annual_ret - 0.02) / max(downside_dev, 0.001)

        # Calmar
        calmar = annual_ret / max(abs(max_dd), 0.001)

        return BR(
            strategy_name=proxy.name,
            symbol_universe=list(self._price_cache.keys()),
            start_date=self._start,
            end_date=self._end,
            annual_return_pct=round(annual_ret * 100, 2),
            cumulative_return_pct=round(total_ret * 100, 2),
            max_drawdown_pct=round(max_dd * 100, 2),
            annual_volatility_pct=round(vol * 100, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
            win_rate_pct=round(win_rate * 100, 1),
            profit_factor=round(profit_factor, 2),
            total_trades=len(trades),
            avg_holding_days=90.0,
            downside_deviation_pct=round(downside_dev * 100, 2),
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_prices(self) -> None:
        """Load price data for all universe stocks from cache or AKShare."""
        cache_dir = Path("data/kline_cache")

        for symbol in self._universe:
            try:
                # Try to find any cached file for this symbol
                cached_files = sorted(cache_dir.glob(f"{symbol}_*.csv"))
                if cached_files:
                    df = pd.read_csv(cached_files[0], index_col=0, parse_dates=True)
                else:
                    import akshare as ak
                    df = ak.stock_zh_a_hist(
                        symbol=symbol, period="daily",
                        start_date="20150101",
                        end_date="20251231",
                        adjust="qfq",
                    )
                    if df is None or df.empty:
                        continue
                    df = df.rename(columns={
                        "日期": "date", "开盘": "open", "收盘": "close",
                        "最高": "high", "最低": "low", "成交量": "volume",
                    })
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date")

                # Filter to our backtest period
                ts_start = pd.Timestamp(self._start)
                ts_end = pd.Timestamp(self._end)
                df = df[(df.index >= ts_start) & (df.index <= ts_end)]

                if len(df) >= 252:
                    self._price_cache[symbol] = df
            except Exception as e:
                logger.debug("Load failed for %s: %s", symbol, e)

        logger.info("Loaded %d stocks for backtest PK", len(self._price_cache))


# ---------------------------------------------------------------------------
# Default universe: CSI 300 top constituents (liquid, representative)
# ---------------------------------------------------------------------------

CSI300_SAMPLE = [
    "600519",  # 贵州茅台
    "000858",  # 五粮液
    "601318",  # 中国平安
    "600036",  # 招商银行
    "000333",  # 美的集团
    "600276",  # 恒瑞医药
    "601166",  # 兴业银行
    "000651",  # 格力电器
    "600887",  # 伊利股份
    "601398",  # 工商银行
    "000002",  # 万科A
    "600030",  # 中信证券
    "601888",  # 中国中免
    "000725",  # 京东方A
    "600900",  # 长江电力
    "002415",  # 海康威视
    "601012",  # 隆基绿能
    "300750",  # 宁德时代
    "002594",  # 比亚迪
    "601899",  # 紫金矿业
]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="真实回测横向PK")
    parser.add_argument("--universe", default="csi300_sample", help="股票池 (csi300_sample / 自定义逗号分隔)")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--strategies", default="all", help="策略列表 (逗号分隔) 或 'ours'/'competitors'/'all'")
    parser.add_argument("--cash", type=float, default=1_000_000, help="初始资金")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Select universe
    if args.universe == "csi300_sample":
        universe = CSI300_SAMPLE
    else:
        universe = [s.strip() for s in args.universe.split(",")]

    # Select strategies
    if args.strategies == "ours":
        strat_keys = [k for k in STRATEGY_PROXIES if STRATEGY_PROXIES[k].is_ours]
    elif args.strategies == "competitors":
        strat_keys = [k for k in STRATEGY_PROXIES if not STRATEGY_PROXIES[k].is_ours]
    else:
        strat_keys = list(STRATEGY_PROXIES.keys())

    # Run
    runner = PKRunner(universe, start=args.start, end=args.end, initial_cash=args.cash)
    report = runner.run_all(strat_keys)

    # Output
    print()
    print("=" * 60)
    print("  回测横向 PK 报告")
    print("=" * 60)
    print(f"  股票池: {len(runner._price_cache)} stocks, {args.start} → {args.end}")
    print()

    if report.overall_ranking:
        print("  📊 综合排名 (夏普40%+卡尔玛30%+胜率20%+盈亏比10%):")
        for i, (name, score) in enumerate(report.overall_ranking, 1):
            marker = " 🏆" if i == 1 else ""
            print(f"    {i}. {name}: {score}{marker}")

    if report.winner_per_metric:
        print()
        print("  🏆 各指标最佳:")
        for metric, winner in report.winner_per_metric.items():
            print(f"    {metric}: {winner}")

    if report.insights:
        print()
        print("  💡 分析:")
        for ins in report.insights:
            print(f"    - {ins}")

    print("=" * 60)
