# -*- coding: utf-8 -*-
"""信号质量追踪器。

追踪信号全生命周期：生成→成交→结果，产出质量报告。

用法:
    tracker = SignalTracker()
    tracker.signal_emitted("SIG_001", "MVP1", "BUY", "600519")
    tracker.signal_executed("SIG_001", execution_price=1200.0)
    tracker.signal_outcome("SIG_001", return_pct=0.08, holding_days=20)
    report = tracker.quality_report()
    print(f"信号胜率: {report.win_rate:.1%}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalStatus(Enum):
    EMITTED = "emitted"
    EXECUTED = "executed"
    CLOSED = "closed"
    EXPIRED = "expired"
    IGNORED = "ignored"


@dataclass
class Signal:
    """单条信号记录。"""

    signal_id: str
    strategy_name: str
    action: str  # BUY / SELL / HOLD
    symbol: str
    status: SignalStatus = SignalStatus.EMITTED
    target_weight: float = 0.0
    confidence: float = 0.0

    # 执行信息
    execution_price: Optional[float] = None
    execution_time: Optional[str] = None

    # 结果信息
    return_pct: Optional[float] = None
    holding_days: Optional[int] = None
    max_drawdown_pct: Optional[float] = None
    exit_reason: str = ""
    # 相对基准超额收益 (alpha = return_pct - benchmark_return_pct)
    alpha_return_pct: Optional[float] = None
    benchmark_name: str = "hs300"
    benchmark_return_pct: Optional[float] = None

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 市场环境
    market_sentiment: str = "NORMAL"
    hs300_change_pct: float = 0.0


@dataclass
class SignalQualityReport:
    """信号质量报告。"""

    total_signals: int = 0
    executed: int = 0
    ignored: int = 0
    closed: int = 0

    win_rate: float = 0.0
    avg_return: float = 0.0
    avg_alpha_return: float = 0.0  # 相对基准超额收益均值
    alpha_win_rate: float = 0.0  # 跑赢基准的胜率
    avg_holding_days: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0  # 总盈利 / |总亏损|

    # 按市场环境分组
    by_sentiment: dict[str, dict] = field(default_factory=dict)

    # 按策略分组
    by_strategy: dict[str, dict] = field(default_factory=dict)

    # 按操作类型分组
    by_action: dict[str, dict] = field(default_factory=dict)

    period_start: str = ""
    period_end: str = ""


class SignalTracker:
    """信号质量追踪器。

    追踪信号全生命周期并提供多维度质量分析。
    支持按策略、市场环境、操作类型分组统计。
    """

    def __init__(self):
        self._signals: dict[str, Signal] = {}
        self._counter = 0

    # ------------------------------------------------------------------
    # 信号生命周期
    # ------------------------------------------------------------------

    def signal_emitted(
        self,
        strategy_name: str,
        action: str,
        symbol: str,
        target_weight: float = 0.0,
        confidence: float = 0.0,
        market_sentiment: str = "NORMAL",
        hs300_change_pct: float = 0.0,
    ) -> Signal:
        """记录信号生成。"""
        sid = self._next_id()
        signal = Signal(
            signal_id=sid,
            strategy_name=strategy_name,
            action=action,
            symbol=symbol,
            target_weight=target_weight,
            confidence=confidence,
            market_sentiment=market_sentiment,
            hs300_change_pct=hs300_change_pct,
        )
        self._signals[sid] = signal
        return signal

    def signal_executed(
        self,
        signal_id: str,
        execution_price: float,
        execution_time: Optional[str] = None,
    ):
        """记录信号执行。"""
        if signal_id not in self._signals:
            raise KeyError(f"信号 {signal_id} 不存在")
        s = self._signals[signal_id]
        s.status = SignalStatus.EXECUTED
        s.execution_price = execution_price
        s.execution_time = execution_time or datetime.now().isoformat()

    def signal_outcome(
        self,
        signal_id: str,
        return_pct: float,
        holding_days: int = 0,
        max_drawdown_pct: Optional[float] = None,
        exit_reason: str = "",
        benchmark_return_pct: Optional[float] = None,
    ):
        """记录信号结果。

        Args:
            benchmark_return_pct: 持仓期内基准(如沪深300)收益率。
                提供时计算 alpha_return_pct = return_pct - benchmark_return_pct;
                未提供则回退用 signal_emitted 时的 hs300_change_pct (尽力而为)。
        """
        if signal_id not in self._signals:
            raise KeyError(f"信号 {signal_id} 不存在")
        s = self._signals[signal_id]
        s.status = SignalStatus.CLOSED
        s.return_pct = return_pct
        s.holding_days = holding_days
        s.max_drawdown_pct = max_drawdown_pct
        s.exit_reason = exit_reason
        # 相对基准 alpha 复盘
        bench = benchmark_return_pct if benchmark_return_pct is not None else s.hs300_change_pct
        if bench is not None:
            s.benchmark_return_pct = round(float(bench), 4)
            s.alpha_return_pct = round(return_pct - float(bench), 4)

    def signal_ignored(self, signal_id: str):
        """标记信号被忽略。"""
        if signal_id in self._signals:
            self._signals[signal_id].status = SignalStatus.IGNORED

    def signal_expired(self, signal_id: str):
        """标记信号过期。"""
        if signal_id in self._signals:
            self._signals[signal_id].status = SignalStatus.EXPIRED

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """获取信号详情。"""
        return self._signals.get(signal_id)

    def get_by_strategy(self, strategy_name: str) -> list[Signal]:
        """按策略获取信号列表。"""
        return [s for s in self._signals.values() if s.strategy_name == strategy_name]

    def get_closed(self) -> list[Signal]:
        """获取已平仓信号。"""
        return [s for s in self._signals.values() if s.status == SignalStatus.CLOSED]

    def get_pending(self) -> list[Signal]:
        """获取待处理信号（已发出但未成交）。"""
        return [s for s in self._signals.values() if s.status == SignalStatus.EMITTED]

    def count(self) -> int:
        return len(self._signals)

    # ------------------------------------------------------------------
    # 跨标的教训注入 (相对基准 alpha 复盘)
    # ------------------------------------------------------------------

    def get_lessons(
        self,
        symbol: Optional[str] = None,
        n_same: int = 5,
        n_cross: int = 3,
    ) -> str:
        """生成可注入分析 prompt 的复盘教训 (借鉴 TradingAgents get_past_context)。

        同标的历史信号优先 (最近 n_same 条), 再补跨标的最远教训 (n_cross 条)。
        只包含已平仓且有实际回报的信号; 返回 Markdown 字符串, 无数据时为空串。

        Args:
            symbol: 目标股票代码; 为 None 时只取跨标的教训。
            n_same: 同标的最多条数。
            n_cross: 跨标的最多教训条数。
        """
        closed = [s for s in self.get_closed() if s.return_pct is not None]
        closed.sort(key=lambda s: s.created_at or "")
        if not closed:
            return ""

        same = [s for s in closed if symbol and s.symbol == symbol][-n_same:]
        cross = [s for s in closed if not symbol or s.symbol != symbol][-n_cross:]

        def _line(s: Signal) -> str:
            alpha = (
                f"{s.alpha_return_pct:+.2%} (vs {s.benchmark_name})"
                if s.alpha_return_pct is not None
                else "—"
            )
            return (
                f"- {s.symbol} {s.action} 收益 {s.return_pct:+.2%} "
                f"alpha {alpha} 持仓{s.holding_days or '?'}天 "
                f"{s.exit_reason or ''}"
            )

        lines: list[str] = []
        if same:
            lines.append(f"### 同标的历史信号 ({symbol})")
            lines.extend(_line(s) for s in same)
        if cross:
            lines.append("### 跨标的教训 (其他股票)")
            lines.extend(_line(s) for s in cross)
        lines.append("> 教训仅供参考, 复盘用, 不自动回填策略参数。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 质量报告
    # ------------------------------------------------------------------

    def quality_report(self, strategy_name: str = "") -> SignalQualityReport:
        """生成信号质量报告。"""
        signals = list(self._signals.values())
        if strategy_name:
            signals = [s for s in signals if s.strategy_name == strategy_name]

        closed = [s for s in signals if s.status == SignalStatus.CLOSED]
        executed = [s for s in signals if s.status in (SignalStatus.EXECUTED, SignalStatus.CLOSED)]

        report = SignalQualityReport(
            total_signals=len(signals),
            executed=len(executed),
            ignored=sum(1 for s in signals if s.status == SignalStatus.IGNORED),
            closed=len(closed),
        )

        if not closed:
            return report

        # 胜率
        returns = [s.return_pct for s in closed if s.return_pct is not None]
        if returns:
            wins = [r for r in returns if r > 0]
            report.win_rate = len(wins) / len(returns)
            report.avg_return = sum(returns) / len(returns)

            gains = sum(r for r in returns if r > 0)
            losses = abs(sum(r for r in returns if r < 0))
            report.profit_factor = gains / losses if losses > 0 else float("inf")

        # 相对基准 alpha 复盘
        alphas = [s.alpha_return_pct for s in closed if s.alpha_return_pct is not None]
        if alphas:
            report.avg_alpha_return = sum(alphas) / len(alphas)
            report.alpha_win_rate = sum(1 for a in alphas if a > 0) / len(alphas)

        # 平均持仓天数
        days = [s.holding_days for s in closed if s.holding_days is not None]
        if days:
            report.avg_holding_days = sum(days) / len(days)

        # 最大回撤
        dds = [s.max_drawdown_pct for s in closed if s.max_drawdown_pct is not None]
        if dds:
            report.max_drawdown = min(dds)

        # 按市场情绪分组
        for s in closed:
            sentiment = s.market_sentiment or "NORMAL"
            if sentiment not in report.by_sentiment:
                report.by_sentiment[sentiment] = {"total": 0, "wins": 0}
            report.by_sentiment[sentiment]["total"] += 1
            if s.return_pct is not None and s.return_pct > 0:
                report.by_sentiment[sentiment]["wins"] += 1

        # 按策略分组
        for s in closed:
            sn = s.strategy_name or "(未知)"
            if sn not in report.by_strategy:
                report.by_strategy[sn] = {"total": 0, "wins": 0, "sum_return": 0.0}
            report.by_strategy[sn]["total"] += 1
            if s.return_pct is not None:
                if s.return_pct > 0:
                    report.by_strategy[sn]["wins"] += 1
                report.by_strategy[sn]["sum_return"] += s.return_pct

        # 按操作类型分组
        for s in closed:
            action = s.action
            if action not in report.by_action:
                report.by_action[action] = {"total": 0, "wins": 0}
            report.by_action[action]["total"] += 1
            if s.return_pct is not None and s.return_pct > 0:
                report.by_action[action]["wins"] += 1

        # 时间范围
        dates = sorted([s.created_at for s in closed if s.created_at])
        if dates:
            report.period_start = dates[0]
            report.period_end = dates[-1]

        return report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._counter += 1
        return f"SIG_{self._counter:06d}"
