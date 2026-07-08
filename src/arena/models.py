# -*- coding: utf-8 -*-
"""内部策略竞技场 — 数据模型。

定义竞技场配置、策略条目、回测结果、排行榜、会话等核心 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# 策略条目
# ---------------------------------------------------------------------------

@dataclass
class ArenaStrategyEntry:
    """竞技场中参战的一条策略配置。"""

    name: str  # 显示名称，如 "MVP1 v2.0"
    strategy_cls_path: str  # 策略类路径，如 "src.backtest.mvp1_strategy.MVP1Strategy"
    params: dict = field(default_factory=dict)  # 策略初始化参数
    version: str = "1.0.0"
    registry_name: str = ""  # 可选：StrategyRegistry 中的 key
    description: str = ""


# ---------------------------------------------------------------------------
# 竞技场配置
# ---------------------------------------------------------------------------

@dataclass
class ArenaConfig:
    """一次竞技场会话的完整配置。"""

    universe: list[str] = field(default_factory=list)  # 股票代码列表
    universe_name: str = "custom"  # "csi300" | "custom"
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    initial_cash: float = 1_000_000
    strategies: list[ArenaStrategyEntry] = field(default_factory=list)
    engine_type: str = "legacy"  # "legacy" (backtrader) | "v2" (ChinaAEngine)
    use_walkforward: bool = False  # 启用 Walk-Forward 过拟合检测
    save_session: bool = True  # 持久化到磁盘


# ---------------------------------------------------------------------------
# 排行榜条目
# ---------------------------------------------------------------------------

@dataclass
class ArenaLeaderboardEntry:
    """排行榜中的一行。"""

    rank: int
    name: str
    version: str
    composite_score: float  # 0-100 加权综合评分
    sharpe_ratio: float
    annual_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    calmar_ratio: float
    sortino_ratio: float
    total_trades: int
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 单策略完整结果
# ---------------------------------------------------------------------------

@dataclass
class ArenaStrategyResult:
    """一个策略在竞技场中的完整回测结果。"""

    name: str
    version: str
    annual_return_pct: float = 0.0
    cumulative_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    annual_volatility_pct: float = 0.0
    total_trades: int = 0
    avg_holding_days: float = 0.0
    monthly_returns: dict[str, float] = field(default_factory=dict)
    yearly_returns: dict[str, float] = field(default_factory=dict)
    equity_curve: list[float] = field(default_factory=list)
    equity_dates: list[str] = field(default_factory=list)
    error: str = ""  # 非空表示该策略运行失败
    leaderboard_entry: Optional[ArenaLeaderboardEntry] = None


# ---------------------------------------------------------------------------
# 竞技场会话（持久化单元）
# ---------------------------------------------------------------------------

@dataclass
class ArenaSession:
    """一次竞技场运行的完整记录，可序列化到 JSON。"""

    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    config: Optional[ArenaConfig] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    results: list[ArenaStrategyResult] = field(default_factory=list)
    leaderboard: list[ArenaLeaderboardEntry] = field(default_factory=list)
    winner_per_metric: dict[str, str] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict。"""
        import dataclasses

        def _convert(obj):
            if dataclasses.is_dataclass(obj):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, list):
                return [_convert(v) for v in obj]
            return obj

        return _convert(self)

    @classmethod
    def from_dict(cls, d: dict) -> ArenaSession:
        """从 dict 反序列化。"""
        config = None
        if d.get("config"):
            cfg = d["config"]
            strategies = [
                ArenaStrategyEntry(**s) for s in cfg.get("strategies", [])
            ]
            config = ArenaConfig(
                universe=cfg.get("universe", []),
                universe_name=cfg.get("universe_name", "custom"),
                start_date=cfg.get("start_date", ""),
                end_date=cfg.get("end_date", ""),
                initial_cash=cfg.get("initial_cash", 1_000_000),
                strategies=strategies,
                engine_type=cfg.get("engine_type", "legacy"),
                use_walkforward=cfg.get("use_walkforward", False),
                save_session=cfg.get("save_session", True),
            )

        results = []
        for r in d.get("results", []):
            results.append(ArenaStrategyResult(
                name=r.get("name", ""),
                version=r.get("version", ""),
                annual_return_pct=r.get("annual_return_pct", 0.0),
                cumulative_return_pct=r.get("cumulative_return_pct", 0.0),
                max_drawdown_pct=r.get("max_drawdown_pct", 0.0),
                sharpe_ratio=r.get("sharpe_ratio", 0.0),
                sortino_ratio=r.get("sortino_ratio", 0.0),
                calmar_ratio=r.get("calmar_ratio", 0.0),
                win_rate_pct=r.get("win_rate_pct", 0.0),
                profit_factor=r.get("profit_factor", 0.0),
                annual_volatility_pct=r.get("annual_volatility_pct", 0.0),
                total_trades=r.get("total_trades", 0),
                avg_holding_days=r.get("avg_holding_days", 0.0),
                monthly_returns=r.get("monthly_returns", {}),
                yearly_returns=r.get("yearly_returns", {}),
                equity_curve=r.get("equity_curve", []),
                equity_dates=r.get("equity_dates", []),
                error=r.get("error", ""),
            ))

        leaderboard = [
            ArenaLeaderboardEntry(**lb) for lb in d.get("leaderboard", [])
        ]

        return cls(
            session_id=d.get("session_id", ""),
            config=config,
            created_at=d.get("created_at", ""),
            results=results,
            leaderboard=leaderboard,
            winner_per_metric=d.get("winner_per_metric", {}),
            insights=d.get("insights", []),
            tags=d.get("tags", []),
        )
