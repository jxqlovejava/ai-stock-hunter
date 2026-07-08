# -*- coding: utf-8 -*-
"""因子回测引擎 — 单因子 IC/IR/分层回测。

对注册表中的任意 alpha 因子跑历史回测，输出：
  - Rank IC 序列（均值/标准差/ICIR/t 统计量）
  - 5 分位分层收益（Top-Bottom 多空）
  - 换手率
  - IC 衰减

使用模式:
    engine = FactorBacktestEngine()
    result = engine.run("pb_factor", "2024-01-01", "2024-12-31")
    print(result.summary)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from src.alpha.schema import FactorBacktestResult

logger = logging.getLogger(__name__)

# 默认回测参数
DEFAULT_N_QUINTILES = 5
DEFAULT_REBALANCE_FREQ = "ME"  # 月末换仓
DEFAULT_MIN_STOCKS = 30
ANNUAL_FACTOR = 252


@dataclass
class _PeriodResult:
    """单期回测快照（内部使用）。"""
    date: pd.Timestamp
    ic: float
    ic_rank: float  # Spearman rank IC
    top_quintile_ret: float
    bottom_quintile_ret: float
    n_stocks: int
    turnover: float = 0.0


class FactorBacktestEngine:
    """单因子回测引擎。

    流程:
      1. 加载历史 OHLCV 数据
      2. 每期末计算因子暴露值
      3. 计算前向收益 → Rank IC
      4. 分层（quintile）→ 多空收益
      5. 聚合统计 → FactorBacktestResult
    """

    def __init__(
        self,
        registry=None,  # lazy: Registry or None
        n_quintiles: int = DEFAULT_N_QUINTILES,
        rebalance_freq: str = DEFAULT_REBALANCE_FREQ,
        min_stocks: int = DEFAULT_MIN_STOCKS,
    ):
        self._registry = registry  # lazy
        self._n_quintiles = n_quintiles
        self._rebalance_freq = rebalance_freq
        self._min_stocks = min_stocks
        self._aggregator = None  # lazy: DataAggregator

    def _get_aggregator(self):
        """懒加载 DataAggregator，避免循环导入。"""
        if self._aggregator is None:
            from src.data.aggregator import DataAggregator
            self._aggregator = DataAggregator()
        return self._aggregator

    def _get_registry(self):
        """懒加载 registry，避免循环导入。"""
        if self._registry is None:
            from src.factors.registry import get_default_registry
            self._registry = get_default_registry()
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        alpha_id: str,
        start_date: str,
        end_date: str,
        symbols: Optional[list[str]] = None,
        data_map: Optional[dict[str, pd.DataFrame]] = None,
    ) -> FactorBacktestResult:
        """运行单因子回测。

        Args:
            alpha_id: 因子 ID（registry 中的 key）
            start_date: 起始日 "YYYY-MM-DD"
            end_date: 终止日 "YYYY-MM-DD"
            symbols: 股票池；None 则使用 aggregator 全市场扫描
            data_map: 预下载的 {symbol: OHLCV DataFrame}；None 则通过 loader 获取

        Returns:
            FactorBacktestResult
        """
        alpha = self._get_registry().get(alpha_id)
        meta = alpha.meta

        # 1. 加载数据
        if data_map is None:
            data_map = self._load_data(symbols or [], start_date, end_date)
        if len(data_map) < self._min_stocks:
            return self._empty_result(alpha_id, start_date, end_date, meta.category,
                                      f"股票数 {len(data_map)} < 最低 {self._min_stocks}")

        # 2. 确定调仓日期
        all_dates = self._all_dates(data_map)
        rebalance_dates = self._rebalance_schedule(all_dates, start_date, end_date)
        if len(rebalance_dates) < 3:
            return self._empty_result(alpha_id, start_date, end_date, meta.category,
                                      f"调仓期数 {len(rebalance_dates)} < 3")

        # 3. 逐期回测
        period_results: list[_PeriodResult] = []
        prev_quintile_map: dict[str, int] = {}

        for i, dt in enumerate(rebalance_dates[:-1]):
            next_dt = rebalance_dates[i + 1]
            try:
                pr = self._evaluate_period(
                    alpha_id, data_map, dt, next_dt, prev_quintile_map
                )
                if pr is not None:
                    period_results.append(pr)
                    # 更新上期分位映射以计算换手率
                    prev_quintile_map = getattr(pr, "_quintile_map", {})
            except Exception as exc:
                logger.debug("period %s: %s", dt.date(), exc)

        if len(period_results) < 3:
            return self._empty_result(alpha_id, start_date, end_date, meta.category,
                                      f"有效回测期数 {len(period_results)} < 3")

        # 4. 聚合统计
        return self._aggregate(alpha_id, start_date, end_date, meta.category, period_results)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(
        self, symbols: list[str], start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        """加载历史 K 线数据。"""
        if symbols:
            pool = symbols
        else:
            # 全市场扫描
            try:
                stocks = self._get_aggregator().scan_all_stocks()
                pool = [s.symbol if hasattr(s, 'symbol') else str(s) for s in (stocks or [])]
            except Exception:
                pool = []

        if not pool:
            return {}

        from src.data.loaders import resolve_loader as _resolve_loader
        loader = _resolve_loader("a_share")
        data_map: dict[str, pd.DataFrame] = {}
        for sym in pool:
            try:
                df = loader.get_history(sym, start.replace("-", ""), end.replace("-", ""))
                if df is not None and not df.empty:
                    df = self._normalize_ohlcv(df)
                    if not df.empty:
                        data_map[sym] = df
            except Exception:
                continue
        return data_map

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """统一 OHLCV 列名。"""
        rename = {
            "开盘": "open", "open": "open",
            "收盘": "close", "close": "close",
            "最高": "high", "high": "high",
            "最低": "low", "low": "low",
            "成交量": "volume", "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return pd.DataFrame()
        return df[list(required)]

    @staticmethod
    def _all_dates(data_map: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
        all_idx = sorted(set().union(*(df.index for df in data_map.values())))
        return pd.DatetimeIndex(all_idx).sort_values()

    def _rebalance_schedule(
        self, all_dates: pd.DatetimeIndex, start: str, end: str
    ) -> list[pd.Timestamp]:
        """生成调仓日期序列。"""
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        dates = all_dates[(all_dates >= start_ts) & (all_dates <= end_ts)]
        if len(dates) == 0:
            return []

        series = pd.Series(0, index=dates)
        if self._rebalance_freq == "ME":
            grouped = series.resample("ME")
        elif self._rebalance_freq == "W":
            grouped = series.resample("W-FRI")
        else:
            # fallback: monthly
            grouped = series.resample("ME")

        rebalance = [ts for ts, _ in grouped]
        if not rebalance:
            # 至少用第一个日期
            return [dates[0], dates[-1]]
        # 确保起始日不早于数据
        rebalance = [d for d in rebalance if d >= start_ts]
        if rebalance and rebalance[0] > dates[0]:
            rebalance.insert(0, dates[0])
        return rebalance

    # ------------------------------------------------------------------
    # Single-period evaluation
    # ------------------------------------------------------------------

    def _evaluate_period(
        self,
        alpha_id: str,
        data_map: dict[str, pd.DataFrame],
        rebalance_dt: pd.Timestamp,
        next_dt: pd.Timestamp,
        prev_quintile_map: dict[str, int],
    ) -> Optional[_PeriodResult]:
        """评估单个调仓周期。"""
        # 获取当期快照数据 (close, pb, etc.)
        spot_data = self._build_spot_snapshot(data_map, rebalance_dt)
        if spot_data is None or len(spot_data) < self._min_stocks:
            return None

        # 计算因子值
        from src.factors.adapter import build_spot_panel as _build_spot_panel
        try:
            panel = _build_spot_panel(spot_data)
            factor_df = self._get_registry().compute(alpha_id, panel)
        except (KeyError, ValueError) as exc:
            logger.debug("factor compute skipped at %s: %s", rebalance_dt.date(), exc)
            return None

        if factor_df.empty:
            return None

        # 因子值转 Series（取第一行，因为是单期快照）
        if factor_df.shape[0] == 1:
            factor_series = factor_df.iloc[0]
        else:
            factor_series = factor_df.iloc[-1]

        # 映射回股票代码
        codes = list(factor_series.index)
        factor_values = factor_series.values.astype(float)

        # 计算前向收益
        fwd_returns = self._forward_returns(data_map, codes, rebalance_dt, next_dt)
        if len(fwd_returns) < self._min_stocks:
            return None

        # 对齐 factor 和 forward return
        common_codes = [c for c in codes if c in fwd_returns.index]
        if len(common_codes) < self._min_stocks:
            return None

        aligned_factor = factor_series[common_codes].values
        aligned_fwd = fwd_returns[common_codes].values

        # 去除 NaN
        valid = ~(np.isnan(aligned_factor) | np.isnan(aligned_fwd))
        if valid.sum() < self._min_stocks:
            return None
        aligned_factor = aligned_factor[valid]
        aligned_fwd = aligned_fwd[valid]
        valid_codes = [common_codes[i] for i in range(len(common_codes)) if valid[i]]

        # Rank IC (Spearman)
        ic = np.corrcoef(aligned_factor, aligned_fwd)[0, 1] if len(aligned_factor) > 2 else 0.0
        ic_rank, _ = stats.spearmanr(aligned_factor, aligned_fwd) if len(aligned_factor) > 3 else (ic, 0.0)
        if np.isnan(ic_rank):
            ic_rank = ic

        # 分层收益
        quintile_labels = self._assign_quintiles(aligned_factor)
        quintile_map: dict[str, int] = {c: q for c, q in zip(valid_codes, quintile_labels)}

        top_idx = quintile_labels == self._n_quintiles - 1
        bottom_idx = quintile_labels == 0
        top_ret = np.mean(aligned_fwd[top_idx]) if top_idx.any() else 0.0
        bottom_ret = np.mean(aligned_fwd[bottom_idx]) if bottom_idx.any() else 0.0

        # 换手率（与上期分位对比）
        turnover = self._calc_turnover(quintile_map, prev_quintile_map)

        result = _PeriodResult(
            date=rebalance_dt,
            ic=ic,
            ic_rank=float(ic_rank),
            top_quintile_ret=float(top_ret),
            bottom_quintile_ret=float(bottom_ret),
            n_stocks=len(valid_codes),
            turnover=turnover,
        )
        # 把 quintile_map 挂在 result 上供下期使用
        object.__setattr__(result, "_quintile_map", quintile_map)
        return result

    def _build_spot_snapshot(
        self, data_map: dict[str, pd.DataFrame], dt: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        """从历史数据构建单期快照 DataFrame。"""
        rows = []
        for code, df in data_map.items():
            # 找最接近 dt 的交易日（不晚于 dt）
            before = df.index[df.index <= dt]
            if len(before) == 0:
                continue
            row_date = before[-1]
            row = df.loc[row_date].to_dict()
            row["code"] = code
            # 尝试获取更多基本面数据
            try:
                quote = self._get_aggregator().get_quote(code)
                if quote is not None:
                    if hasattr(quote, 'pb') and quote.pb:
                        row["pb"] = float(quote.pb)
                    if hasattr(quote, 'pe') and quote.pe:
                        row["pe"] = float(quote.pe)
                    if hasattr(quote, 'market_cap') and quote.market_cap:
                        row["market_cap"] = float(quote.market_cap)
            except Exception:
                pass
            rows.append(row)

        if len(rows) < self._min_stocks:
            return None
        return pd.DataFrame(rows)

    def _forward_returns(
        self,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
        from_dt: pd.Timestamp,
        to_dt: pd.Timestamp,
    ) -> pd.Series:
        """计算前向收益（close 变化率）。"""
        returns = {}
        for code in codes:
            df = data_map.get(code)
            if df is None:
                continue
            before = df.index[df.index <= from_dt]
            after = df.index[(df.index > from_dt) & (df.index <= to_dt)]
            if len(before) == 0 or len(after) == 0:
                continue
            price_from = df.loc[before[-1], "close"]
            price_to = df.loc[after[-1], "close"]
            if price_from > 0:
                returns[code] = (price_to / price_from) - 1.0
        return pd.Series(returns)

    def _assign_quintiles(self, values: np.ndarray) -> np.ndarray:
        """将因子值分为 quintile，返回 0..n-1 标签。"""
        n = self._n_quintiles
        # 处理 ties
        ranked = stats.rankdata(values, method="average")
        n_valid = len(values)
        boundaries = np.linspace(0, n_valid, n + 1)[1:-1]
        labels = np.digitize(ranked, boundaries)
        return labels  # 0..n-1

    @staticmethod
    def _calc_turnover(
        curr_quintile: dict[str, int],
        prev_quintile: dict[str, int],
    ) -> float:
        """计算分位变动比例。"""
        if not prev_quintile:
            return 0.0
        common = set(curr_quintile) & set(prev_quintile)
        if not common:
            return 1.0
        changed = sum(1 for c in common if curr_quintile[c] != prev_quintile[c])
        return changed / len(common)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        alpha_id: str,
        start: str,
        end: str,
        category: str,
        periods: list[_PeriodResult],
    ) -> FactorBacktestResult:
        """聚合周期结果 → FactorBacktestResult。"""
        n = len(periods)
        ic_ranks = np.array([p.ic_rank for p in periods])
        ics = np.array([p.ic for p in periods])
        turnovers = np.array([p.turnover for p in periods])
        top_rets = np.array([p.top_quintile_ret for p in periods])
        bottom_rets = np.array([p.bottom_quintile_ret for p in periods])
        long_short = top_rets - bottom_rets

        ic_mean = float(np.mean(ic_ranks))
        ic_std = float(np.std(ic_ranks, ddof=1)) if n > 1 else 0.0
        icir = ic_mean / ic_std if ic_std > 0 else 0.0
        ic_positive_ratio = float((ic_ranks > 0).mean())
        ic_t = float(ic_mean / (ic_std / np.sqrt(n))) if ic_std > 0 else 0.0

        # 年化多空收益
        periods_per_year = ANNUAL_FACTOR / max(1, self._avg_period_days(periods))
        ls_return = float(np.mean(long_short)) * periods_per_year
        ls_sharpe = float(np.mean(long_short) / np.std(long_short, ddof=1) * np.sqrt(periods_per_year)) \
            if np.std(long_short, ddof=1) > 0 else 0.0

        top_ret = float(np.mean(top_rets)) * periods_per_year
        bottom_ret = float(np.mean(bottom_rets)) * periods_per_year

        avg_turnover = float(np.mean(turnovers))
        max_turnover = float(np.max(turnovers)) if len(turnovers) > 0 else 0.0

        # IC 衰减（20 日近似：用后 20% 的 IC vs 前 20%）
        split = max(1, n // 5)
        early_ic = np.mean(ic_ranks[:split])
        late_ic = np.mean(ic_ranks[-split:])
        ic_decay = early_ic - late_ic if early_ic != 0 else 0.0

        # 稳定性评分
        stability = self._stability_score(ic_ranks, ls_return, turnovers)

        warnings = []
        if icir < 0.3:
            warnings.append(f"ICIR={icir:.2f} < 0.3 — 因子区分力不足")
        if avg_turnover > 0.8:
            warnings.append(f"换手率={avg_turnover:.1%} 过高 — 实际交易成本可能侵蚀 Alpha")
        if n < 12:
            warnings.append(f"仅 {n} 期数据 — 统计显著性不足")

        from src.data.source_citation import make_citation as _make_citation
        # source citation
        citation = _make_citation(
            provider="factor_backtest",
            field=alpha_id,
            data_type="backtest",
        )

        return FactorBacktestResult(
            alpha_id=alpha_id,
            start_date=start,
            end_date=end,
            n_periods=n,
            n_stocks_avg=float(np.mean([p.n_stocks for p in periods])),
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            ic_positive_ratio=ic_positive_ratio,
            ic_t_stat=ic_t,
            top_quintile_return=top_ret,
            bottom_quintile_return=bottom_ret,
            long_short_return=ls_return,
            long_short_sharpe=ls_sharpe,
            avg_turnover=avg_turnover,
            max_turnover=max_turnover,
            ic_decay_20d=ic_decay,
            stability_score=stability,
            category=category,
            warnings=warnings,
            source_citations=[citation],
        )

    @staticmethod
    def _stability_score(
        ic_ranks: np.ndarray,
        long_short_return: float,
        turnovers: np.ndarray,
    ) -> float:
        """综合稳定性评分 0-100。"""
        n = len(ic_ranks)
        if n < 3:
            return 0.0

        ic_consistency = 1.0 - min(1.0, np.std(ic_ranks, ddof=1) / (abs(np.mean(ic_ranks)) + 1e-9))
        # 收益稳定性
        ret_consistency = 0.5 if long_short_return > 0 else 0.0
        # 低换手加分
        turnover_score = max(0.0, 1.0 - np.mean(turnovers))
        # IC 趋势
        half = n // 2
        trend_score = 0.5 if np.mean(ic_ranks[half:]) >= np.mean(ic_ranks[:half]) else 0.0

        raw = (ic_consistency * 40 + ret_consistency * 30 + turnover_score * 20 + trend_score * 10)
        return max(0.0, min(100.0, raw))

    @staticmethod
    def _avg_period_days(periods: list[_PeriodResult]) -> float:
        if len(periods) < 2:
            return 21.0  # default month
        diffs = [(periods[i + 1].date - periods[i].date).days for i in range(len(periods) - 1)]
        return float(np.mean(diffs)) if diffs else 21.0

    @staticmethod
    def _empty_result(
        alpha_id: str, start: str, end: str, category: str, reason: str
    ) -> FactorBacktestResult:
        """生成空结果。"""
        return FactorBacktestResult(
            alpha_id=alpha_id,
            start_date=start,
            end_date=end,
            category=category,
            warnings=[reason],
        )
