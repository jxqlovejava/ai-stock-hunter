# -*- coding: utf-8 -*-
"""内部策略竞技场 (Internal Strategy Arena)。

提供多策略在同一数据源/时间段上的横向对比回测，生成排行榜和逐指标最佳策略。

用法:
    from src.arena import ArenaOrchestrator

    orchestrator = ArenaOrchestrator()
    config = orchestrator.prepare(strategies=["mvp1", "mvp2", "mvp3"])
    session = orchestrator.run(config)
    print(orchestrator.report(session))

CLI:
    python -m src arena run --strategies mvp1,mvp2,mvp3
    python -m src arena benchmark
    python -m src arena list
    python -m src arena show <session_id>
"""

from .models import (
    ArenaConfig,
    ArenaLeaderboardEntry,
    ArenaSession,
    ArenaStrategyEntry,
    ArenaStrategyResult,
)
from .orchestrator import ArenaOrchestrator
from .report import ArenaReport
from .session import ArenaSessionStore

__all__ = [
    "ArenaOrchestrator",
    "ArenaReport",
    "ArenaSessionStore",
    "ArenaConfig",
    "ArenaSession",
    "ArenaStrategyEntry",
    "ArenaStrategyResult",
    "ArenaLeaderboardEntry",
]
