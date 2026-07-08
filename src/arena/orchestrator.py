# -*- coding: utf-8 -*-
"""内部策略竞技场 — 核心编排器。

ArenaOrchestrator 负责：
  1. 加载共享价格数据
  2. 逐策略运行回测（BacktestEngine）
  3. 计算排行榜（StrategyComparator + CompetitorAnalyzer）
  4. 保存 ArenaSession
  5. 委托 ArenaReport 生成报告
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .models import (
    ArenaConfig,
    ArenaLeaderboardEntry,
    ArenaSession,
    ArenaStrategyEntry,
    ArenaStrategyResult,
)
from .session import ArenaSessionStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 默认股票池
# ---------------------------------------------------------------------------

CSI300_SAMPLE = [
    "600519", "000858", "601318", "600036", "000333",
    "600276", "601166", "000651", "600887", "601398",
    "000002", "600030", "601888", "000725", "600900",
    "002415", "601012", "300750", "002594", "601899",
]

# 预置策略：不需要传全路径，通过缩写名解析
PRESET_STRATEGIES: dict[str, ArenaStrategyEntry] = {
    "mvp1": ArenaStrategyEntry(
        name="MVP1 三因子",
        strategy_cls_path="src.backtest.mvp1_strategy.MVP1Strategy",
        params={"max_positions": 20, "rebalance_days": 21, "pe_pct_threshold": 70},
        version="1.0.0",
        description="PE分位 + 动量 双因子选股，月调仓",
    ),
    "mvp2": ArenaStrategyEntry(
        name="MVP2 增强",
        strategy_cls_path="src.backtest.mvp2_strategy.MVP2Strategy",
        params={"max_positions": 10, "rebalance_days": 10, "pe_pct_threshold": 70,
                "use_market_timing": True, "bear_reduce": 0.5},
        version="1.0.0",
        description="MVP1 + 市场择时，熊市减半仓",
    ),
    "mvp2_plus": ArenaStrategyEntry(
        name="MVP2+ 动量增强",
        strategy_cls_path="src.backtest.mvp2_plus.MVP2Plus",
        params={"max_positions": 10, "rebalance_days": 10, "pe_pct_threshold": 70,
                "min_momentum_pct": 60, "use_market_timing": True},
        version="1.0.0",
        description="MVP2 + 动量强度阈值 + 动态仓位",
    ),
    "mvp3": ArenaStrategyEntry(
        name="MVP3 多时间框架",
        strategy_cls_path="src.backtest.mvp3_strategy.MVP3Strategy",
        params={"max_positions": 15, "rebalance_days": 10, "pe_pct_threshold": 70,
                "min_daily_amount": 5e7, "use_market_timing": True},
        version="1.0.0",
        description="多时间框架PE + 行业相对排名 + 流动性过滤",
    ),
    "mvp_alpha": ArenaStrategyEntry(
        name="MVP AlphaEvo",
        strategy_cls_path="src.backtest.mvp_alpha_evo.MVPAlphaEvo",
        params={"max_positions": 8, "rebalance_days": 10,
                "min_volume_ratio": 1.2, "max_rsi": 70},
        version="1.0.0",
        description="RSI/布林带/成交量/MA20 四维增强",
    ),
    "mvp_multi": ArenaStrategyEntry(
        name="MVP 多因子",
        strategy_cls_path="src.backtest.mvp_multi_factor.MVPMultiFactor",
        params={"max_positions": 8, "rebalance_days": 10,
                "score_threshold": 50, "use_market_timing": True},
        version="1.0.0",
        description="12因子等权复合评分",
    ),
    "mvp_sector": ArenaStrategyEntry(
        name="MVP 行业轮动",
        strategy_cls_path="src.backtest.mvp_sector.MVPSector",
        params={"max_positions": 8, "rebalance_days": 10,
                "use_sector_rotation": True, "top_sectors": 2},
        version="1.0.0",
        description="行业轮动 + 三档市场择时",
    ),
}


# ---------------------------------------------------------------------------
# 桥接：BacktestResult → 统一结果
# ---------------------------------------------------------------------------

def _compute_sortino(equity_curve: list[float], risk_free: float = 0.03) -> float:
    """从权益曲线估算 Sortino ratio。"""
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / max(equity_curve[i - 1], 1)
        for i in range(1, len(equity_curve))
    ]
    if not returns:
        return 0.0
    downside = [r - risk_free / 252 for r in returns if r < risk_free / 252]
    if not downside or len(downside) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    annual_ret = mean_ret * 252
    downside_std = (sum((d - sum(downside) / len(downside)) ** 2
                       for d in downside) / (len(downside) - 1)) ** 0.5
    annual_downside = downside_std * (252 ** 0.5)
    return (annual_ret - risk_free) / annual_downside if annual_downside > 0 else 0.0


def _compute_calmar(annual_return: float, max_drawdown_pct: float) -> float:
    """Calmar ratio = 年化收益 / |最大回撤|。"""
    dd = abs(max_drawdown_pct) / 100
    return annual_return / dd if dd > 0.001 else 0.0


def _backtest_result_to_arena(
    name: str,
    version: str,
    result,  # BacktestResult
) -> ArenaStrategyResult:
    """将 BacktestResult 转为 ArenaStrategyResult。"""
    dd_pct = result.max_drawdown if abs(result.max_drawdown) < 1 else result.max_drawdown / 100
    dd_pct_display = dd_pct * 100  # 转为百分比显示

    annual_ret = result.annual_return
    annual_ret_pct = annual_ret * 100

    calmar = _compute_calmar(annual_ret, dd_pct_display)
    sortino = 0.0  # BacktestResult 不含权益曲线，无法计算 Sortino

    return ArenaStrategyResult(
        name=name,
        version=version,
        annual_return_pct=round(annual_ret_pct, 2),
        cumulative_return_pct=round(result.total_return * 100, 2),
        max_drawdown_pct=round(dd_pct_display, 2),
        sharpe_ratio=round(result.sharpe_ratio, 2),
        sortino_ratio=round(sortino, 2),
        calmar_ratio=round(calmar, 2),
        win_rate_pct=round(result.win_rate * 100, 2),
        profit_factor=0.0,
        annual_volatility_pct=0.0,
        total_trades=result.total_trades,
        avg_holding_days=0.0,
        yearly_returns={
            str(k): round(v * 100, 2) if abs(v) < 1 else round(v, 2)
            for k, v in (result.yearly_returns or {}).items()
        },
    )


# ---------------------------------------------------------------------------
# ArenaOrchestrator
# ---------------------------------------------------------------------------

class ArenaOrchestrator:
    """内部策略竞技场编排器。

    用法:
        orchestrator = ArenaOrchestrator()
        config = orchestrator.prepare(strategies=["mvp1", "mvp2"])
        session = orchestrator.run(config)
        print(orchestrator.report(session))
    """

    def __init__(self):
        self._store = ArenaSessionStore()

    # ------------------------------------------------------------------
    # prepare
    # ------------------------------------------------------------------

    def prepare(
        self,
        strategies: Optional[list[str]] = None,
        universe: Optional[list[str]] = None,
        universe_name: str = "csi300",
        start_date: str = "2020-01-01",
        end_date: str = "2024-12-31",
        initial_cash: float = 1_000_000,
        engine_type: str = "legacy",
        use_walkforward: bool = False,
    ) -> ArenaConfig:
        """构建竞技场配置。

        Args:
            strategies: 策略缩写名列表，如 ["mvp1", "mvp2", "mvp3"]。
                        None 表示使用全部预置策略。
            universe: 股票代码列表。None 表示使用 CSI300 样本。
            universe_name: 股票池名称。
        """
        # 解析策略
        if strategies is None:
            entries = list(PRESET_STRATEGIES.values())
        else:
            entries = []
            for s in strategies:
                if s in PRESET_STRATEGIES:
                    entries.append(PRESET_STRATEGIES[s])
                else:
                    logger.warning("Unknown strategy preset: %s", s)

        # 解析股票池
        if universe is None:
            universe = CSI300_SAMPLE[:]
            universe_name = "csi300_sample"

        return ArenaConfig(
            universe=universe,
            universe_name=universe_name,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            strategies=entries,
            engine_type=engine_type,
            use_walkforward=use_walkforward,
            save_session=True,
        )

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, config: ArenaConfig) -> ArenaSession:
        """执行竞技场完整流程。"""
        session = ArenaSession(
            config=config,
            created_at=datetime.now().isoformat(),
            tags=[config.universe_name, config.engine_type],
        )

        if not config.strategies:
            session.insights.append("⚠️ 无策略可供对比 — 请通过 prepare() 或 --strategies 指定策略")
            self._save(session, config)
            return session

        logger.info(
            "🏟️ Arena: %d strategies on %d stocks, %s → %s",
            len(config.strategies), len(config.universe),
            config.start_date, config.end_date,
        )

        # Step 1: 加载共享价格数据
        price_cache = self._load_shared_prices(config)
        if not price_cache:
            session.insights.append("⚠️ 无法加载价格数据 — 请检查网络连接或 AKShare 可用性")
            self._save(session, config)
            return session

        logger.info("Loaded %d stocks into price cache", len(price_cache))

        # Step 2: 逐策略运行回测
        results: list[ArenaStrategyResult] = []
        for entry in config.strategies:
            logger.info("Running: %s (%s)", entry.name, entry.version)
            try:
                ar = self._run_single_strategy(config, entry, price_cache)
            except Exception as e:
                logger.warning("Strategy %s failed: %s", entry.name, e)
                ar = ArenaStrategyResult(
                    name=entry.name, version=entry.version,
                    error=str(e),
                )
            results.append(ar)

        session.results = results

        # Step 3: 过滤失败策略
        valid = [r for r in results if not r.error]
        if not valid:
            session.insights.append("❌ 所有策略均运行失败，无法生成排行榜")
            self._save(session, config)
            return session

        failed = [r for r in results if r.error]
        if failed:
            session.insights.append(
                f"⚠️ {len(failed)} 个策略运行失败: "
                + ", ".join(f"{r.name}({r.error[:60]})" for r in failed)
            )

        # Step 4: 计算排行榜
        session.leaderboard = self._compute_leaderboard(valid)
        session.winner_per_metric = self._compute_winners(valid)

        # Step 5: 生成洞察
        session.insights.extend(self._generate_insights(valid, session.leaderboard))

        # Step 6: 持久化
        self._save(session, config)

        # Step 7: 通知 evolution 管道 (竞技场优胜者可自动进入进化流水线)
        try:
            from src.evolution.lifecycle import LifecycleManager
            lm = LifecycleManager()
            for entry in (session.leaderboard or [])[:1]:  # 仅第一名
                if hasattr(lm, "promote_from_arena"):
                    lm.promote_from_arena(entry.strategy_name, entry.composite_score)
        except Exception:
            pass

        return session

    # ------------------------------------------------------------------
    # 单策略回测
    # ------------------------------------------------------------------

    def _run_single_strategy(
        self,
        config: ArenaConfig,
        entry: ArenaStrategyEntry,
        price_cache: dict[str, pd.DataFrame],
    ) -> ArenaStrategyResult:
        """运行单个策略的回测。"""
        from src.backtest.engine import BacktestEngine

        # 解析策略类
        strategy_cls = _resolve_class(entry.strategy_cls_path)

        engine = BacktestEngine(initial_cash=config.initial_cash)
        engine.add_strategy(strategy_cls, **entry.params)

        # 添加数据
        for code, df in price_cache.items():
            engine.add_data(code, df)

        result = engine.run(start=config.start_date, end=config.end_date)

        return _backtest_result_to_arena(entry.name, entry.version, result)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_shared_prices(
        self, config: ArenaConfig
    ) -> dict[str, pd.DataFrame]:
        """加载所有股票的价格数据（带本地缓存）。"""
        import akshare as ak

        cache_dir = Path("data/kline_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)

        price_cache: dict[str, pd.DataFrame] = {}

        for symbol in config.universe:
            try:
                # 尝试本地缓存
                cached = sorted(cache_dir.glob(f"{symbol}_*.csv"))
                if cached:
                    df = pd.read_csv(cached[0], index_col=0, parse_dates=True)
                else:
                    df = ak.stock_zh_a_hist(
                        symbol=symbol, period="daily",
                        start_date="20150101", end_date="20251231",
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
                    # 缓存
                    df.to_csv(cache_dir / f"{symbol}_daily.csv")

                # 截取回测区间
                ts_s = pd.Timestamp(config.start_date)
                ts_e = pd.Timestamp(config.end_date)
                df = df[(df.index >= ts_s) & (df.index <= ts_e)]

                if len(df) >= 252:
                    price_cache[symbol] = df
            except Exception as e:
                logger.debug("Skip %s: %s", symbol, e)

        return price_cache

    # ------------------------------------------------------------------
    # 排行榜计算
    # ------------------------------------------------------------------

    def _compute_leaderboard(
        self,
        results: list[ArenaStrategyResult],
    ) -> list[ArenaLeaderboardEntry]:
        """使用 StrategyComparator 风格计算排行榜。"""
        if not results:
            return []

        # 提取指标列表
        sharpe_vals = [r.sharpe_ratio for r in results]
        dd_vals = [abs(r.max_drawdown_pct) or 0.01 for r in results]
        win_vals = [r.win_rate_pct for r in results]
        ret_vals = [r.annual_return_pct for r in results]

        entries = []
        for r in results:
            s_norm = _minmax(r.sharpe_ratio, sharpe_vals)
            d_norm = _minmax(1.0 / dd_vals[results.index(r)],
                             [1.0 / d for d in dd_vals])
            w_norm = _minmax(r.win_rate_pct, win_vals)
            a_norm = _minmax(r.annual_return_pct, ret_vals)

            # 权重：Sharpe 40%, MaxDD 25%, WinRate 20%, AnnRet 15%
            composite = (s_norm * 0.40 + d_norm * 0.25 + w_norm * 0.20 + a_norm * 0.15) * 100

            entries.append(ArenaLeaderboardEntry(
                rank=0,
                name=r.name,
                version=r.version,
                composite_score=round(composite, 1),
                sharpe_ratio=r.sharpe_ratio,
                annual_return_pct=r.annual_return_pct,
                max_drawdown_pct=r.max_drawdown_pct,
                win_rate_pct=r.win_rate_pct,
                calmar_ratio=r.calmar_ratio,
                sortino_ratio=r.sortino_ratio,
                total_trades=r.total_trades,
                details={},
            ))

        # 排序并分配排名
        entries.sort(key=lambda x: x.composite_score, reverse=True)
        for i, e in enumerate(entries):
            e.rank = i + 1

        return entries

    def _compute_winners(
        self,
        results: list[ArenaStrategyResult],
    ) -> dict[str, str]:
        """逐指标最佳策略。"""
        if len(results) <= 1:
            return {}

        metrics = {
            "年化收益率": ("annual_return_pct", True),
            "夏普比率": ("sharpe_ratio", True),
            "卡玛比率": ("calmar_ratio", True),
            "索提诺比率": ("sortino_ratio", True),
            "最大回撤(最小)": ("max_drawdown_pct", True),  # 负值，-15 > -22
            "胜率": ("win_rate_pct", True),
        }

        winners = {}
        for label, (field, higher) in metrics.items():
            best = max(results, key=lambda r: getattr(r, field) if higher
                       else -getattr(r, field))
            val = getattr(best, field)
            winners[label] = f"{best.name} ({val:+.1f})"

        return winners

    def _generate_insights(
        self,
        results: list[ArenaStrategyResult],
        leaderboard: list[ArenaLeaderboardEntry],
    ) -> list[str]:
        """生成分析洞察。"""
        insights = []
        if not leaderboard:
            return insights

        best = leaderboard[0]
        insights.append(
            f"🏆 {best.name} 综合排名第 1 (评分 {best.composite_score:.1f})，"
            f"Sharpe {best.sharpe_ratio:.2f} / 回撤 {best.max_drawdown_pct:.1f}%"
        )

        if len(leaderboard) >= 2:
            gap = best.composite_score - leaderboard[1].composite_score
            if gap > 10:
                insights.append(f"📈 {best.name} 显著领先第 2 名 {gap:.1f} 分")
            elif gap < 3:
                insights.append(f"⚖️ 前两名差距仅 {gap:.1f} 分，表现接近")

        # 最大回撤预警
        worst_dd = max(results, key=lambda r: abs(r.max_drawdown_pct))
        if abs(worst_dd.max_drawdown_pct) > 40:
            insights.append(f"⚠️ {worst_dd.name} 最大回撤 {worst_dd.max_drawdown_pct:.1f}%，风控需关注")

        # 单策略提示
        if len(results) == 1:
            insights.append("💡 仅 1 个策略参战 — 添加更多策略以获得有意义的对比")

        return insights

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _save(self, session: ArenaSession, config: ArenaConfig) -> None:
        if config.save_session:
            self._store.save(session)

    # ------------------------------------------------------------------
    # report
    # ------------------------------------------------------------------

    def report(self, session: ArenaSession) -> str:
        """生成 Markdown 报告。"""
        from .report import ArenaReport
        return ArenaReport().markdown(session)

    # ------------------------------------------------------------------
    # query
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        """列出历史竞技场会话。"""
        return self._store.list_sessions()

    def load_session(self, session_id: str) -> Optional[ArenaSession]:
        """加载历史会话。"""
        return self._store.load(session_id)

    def compare_sessions(self, id1: str, id2: str) -> list[dict]:
        """跨会话对比。"""
        return self._store.compare_sessions([id1, id2])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_class(cls_path: str) -> type:
    """通过路径字符串解析策略类。"""
    parts = cls_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid class path: {cls_path}")
    module = importlib.import_module(parts[0])
    return getattr(module, parts[1])


def _minmax(value: float, all_values: list[float]) -> float:
    """Min-max 归一化到 [0, 1]。"""
    if not all_values:
        return 0.0
    mn = min(all_values)
    mx = max(all_values)
    if mx == mn:
        return 0.5
    return max(0.0, min(1.0, (value - mn) / (mx - mn)))
