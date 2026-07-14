# -*- coding: utf-8 -*-
"""Swing Overlay 集成适配 — paper-trade / 回测 / position-monitor 共用。

把 ``SwingOverlayEngine`` 的只读决策接到可执行层：
  - PaperOrder（模拟盘）
  - 目标权重调整（回测）
  - 监控文案（position-monitor）

不绕过 L4；paper 路径仍走引擎资金/T+1/涨跌停检查。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd

from src.strategy.swing_overlay import (
    OverlayAction,
    OverlayDecision,
    OverlayMarketContext,
    PositionBucketView,
    SwingOverlayConfig,
    SwingOverlayEngine,
    format_decision,
)

logger = logging.getLogger(__name__)

# 会转化为卖出/买入动作的规则
_SELL_ACTIONS = {
    OverlayAction.EXIT,
    OverlayAction.REDUCE,
    OverlayAction.SWING_SELL,
}
_BUY_ACTIONS = {OverlayAction.SWING_BUY}


@dataclass(frozen=True)
class OverlayEvalInput:
    """通用持仓输入（兼容 PositionState / dict）。"""

    symbol: str
    quantity: int
    entry_price: float
    current_price: float
    stop_price: float = 0.0
    name: str = ""
    equity: float = 500_000.0
    core_shares: int = -1  # <0 表示自动拆分
    swing_shares: int = -1
    entry_date: Optional[Any] = None


def position_like_to_input(
    pos: Any,
    *,
    equity: float,
    price_override: Optional[float] = None,
) -> OverlayEvalInput:
    """从 PositionState / 类 dict 持仓构造输入。"""
    if isinstance(pos, dict):
        symbol = str(pos.get("symbol", ""))
        qty = int(pos.get("quantity", 0) or 0)
        entry = float(pos.get("entry_price", 0) or 0)
        last = float(pos.get("last_price", 0) or entry)
        stop = float(pos.get("stop_price", 0) or 0)
        name = str(pos.get("name", "") or "")
        entry_date = pos.get("entry_date")
    else:
        symbol = str(getattr(pos, "symbol", ""))
        qty = int(getattr(pos, "quantity", 0) or 0)
        entry = float(getattr(pos, "entry_price", 0) or 0)
        last = float(getattr(pos, "last_price", 0) or entry)
        stop = float(getattr(pos, "stop_price", 0) or 0)
        name = str(getattr(pos, "name", "") or "")
        entry_date = getattr(pos, "entry_date", None)

    price = float(price_override) if price_override and price_override > 0 else last
    return OverlayEvalInput(
        symbol=symbol,
        quantity=qty,
        entry_price=entry,
        current_price=price,
        stop_price=stop,
        name=name,
        equity=equity,
        entry_date=entry_date,
    )


def evaluate_overlay(
    inp: OverlayEvalInput,
    *,
    ma20: Optional[float] = None,
    near_support: bool = False,
    near_resistance: bool = False,
    pipeline_score: float = 50.0,
    pipeline_action: str = "HOLD",
    structure_broken: Optional[bool] = None,
    swing_trades_today: int = 0,
    swing_shares_sellable: Optional[int] = None,
    engine: Optional[SwingOverlayEngine] = None,
) -> OverlayDecision:
    """统一评估入口。"""
    eng = engine or SwingOverlayEngine()
    core, swing = inp.core_shares, inp.swing_shares
    if core < 0 or swing < 0:
        core, swing = eng.split_existing(inp.quantity)

    view = PositionBucketView(
        symbol=inp.symbol,
        name=inp.name,
        total_shares=inp.quantity,
        core_shares=core,
        swing_shares=swing,
        entry_price=inp.entry_price,
        current_price=inp.current_price,
        stop_price=inp.stop_price,
        equity=inp.equity,
    )
    sellable = swing if swing_shares_sellable is None else int(swing_shares_sellable)
    ctx = OverlayMarketContext(
        price=inp.current_price,
        ma20=ma20,
        stop_price=inp.stop_price if inp.stop_price > 0 else None,
        near_support=near_support,
        near_resistance=near_resistance,
        pipeline_score=pipeline_score,
        pipeline_action=pipeline_action,
        structure_broken=structure_broken,
        swing_trades_today=swing_trades_today,
        swing_shares_sellable=sellable,
    )
    return eng.evaluate(view, ctx)


def decision_to_paper_order(
    decision: OverlayDecision,
    *,
    name: str = "",
    price: float,
    stop_price: float = 0.0,
    score: float = 0.0,
) -> Optional[Any]:
    """OverlayDecision → PaperOrder（延迟导入避免环依赖）。"""
    if decision.quantity <= 0 and decision.action not in _SELL_ACTIONS:
        return None
    if decision.action in (OverlayAction.HOLD, OverlayAction.BLOCKED, OverlayAction.INFEASIBLE):
        return None
    if decision.action not in _SELL_ACTIONS | _BUY_ACTIONS:
        return None
    if price <= 0:
        return None

    from src.paper_trading.order_factory import PaperOrder

    if decision.action in _SELL_ACTIONS:
        if decision.quantity <= 0:
            return None
        return PaperOrder(
            symbol=decision.symbol,
            name=name or decision.symbol,
            action="sell",
            price=price,
            quantity=int(decision.quantity),
            target_weight=0.0,
            reason=f"[overlay:{decision.rule}] {decision.reason}",
            signal_score=score,
            signal_confidence=0.7 if decision.urgency == "HIGH" else 0.55,
            stop_price=stop_price,
        )

    # SWING_BUY
    return PaperOrder(
        symbol=decision.symbol,
        name=name or decision.symbol,
        action="buy",
        price=price,
        quantity=int(decision.quantity),
        target_weight=0.0,
        reason=f"[overlay:{decision.rule}] {decision.reason}",
        signal_score=score,
        signal_confidence=0.55,
        stop_price=stop_price,
    )


def compute_ma20(closes: pd.Series) -> Optional[float]:
    if closes is None or len(closes) < 20:
        if closes is not None and len(closes) >= 5:
            return float(closes.iloc[-5:].mean())
        return None
    return float(closes.iloc[-20:].mean())


def adjust_target_weights_with_overlay(
    data_map: dict[str, pd.DataFrame],
    base_weights: pd.DataFrame,
    *,
    config: Optional[SwingOverlayConfig] = None,
    initial_stop_pct: float = 0.08,
) -> pd.DataFrame:
    """回测用：在基础目标权重上叠加 overlay 强制减仓/清仓。

    逻辑（按日推进）:
      - 若前一日目标权重 > 0 视为持仓
      - 用 entry≈首次持仓日收盘；止损 = entry * (1 - initial_stop_pct)
      - 若现价跌破止损或 < MA20 → 当日目标权重置 0（清仓）
      - 不在此做 SWING_BUY（回测侧避免无管道加仓）
    """
    if base_weights.empty or not data_map:
        return base_weights

    eng = SwingOverlayEngine(config or SwingOverlayConfig())
    weights = base_weights.copy().astype(float)
    dates = list(weights.index)
    codes = list(weights.columns)

    # 追踪简化持仓：entry_price / shares proxy via weight
    entries: dict[str, float] = {}

    for i, ts in enumerate(dates):
        for code in codes:
            w = float(weights.loc[ts, code] or 0.0)
            df = data_map.get(code)
            if df is None or df.empty:
                continue
            # align close
            if ts not in df.index:
                # try nearest previous
                sub = df.loc[:ts]
                if sub.empty:
                    continue
                close = float(sub["close"].iloc[-1])
                hist = sub["close"]
            else:
                close = float(df.loc[ts, "close"])
                hist = df.loc[:ts, "close"]

            prev_w = float(weights.iloc[i - 1][code] or 0.0) if i > 0 else 0.0

            # 开仓记录成本
            if prev_w <= 1e-9 and w > 1e-9:
                entries[code] = close
            if w <= 1e-9 and prev_w <= 1e-9:
                entries.pop(code, None)
                continue

            # 持仓中（今日目标本想持有，或昨日持有）
            holding = prev_w > 1e-9 or w > 1e-9
            if not holding:
                continue

            entry = entries.get(code, close)
            stop = entry * (1.0 - abs(initial_stop_pct))
            ma20 = compute_ma20(hist)

            # 用名义 1 手以上的代理股数，保证可触发减仓规则
            qty = 200 if prev_w > 1e-9 else 0
            if qty <= 0:
                continue

            inp = OverlayEvalInput(
                symbol=code,
                quantity=qty,
                entry_price=entry,
                current_price=close,
                stop_price=stop,
                equity=1_000_000.0,
            )
            decision = evaluate_overlay(
                inp,
                ma20=ma20,
                structure_broken=(close < ma20) if ma20 else None,
                pipeline_action="HOLD",
                pipeline_score=55.0,
                engine=eng,
            )
            if decision.action in (OverlayAction.EXIT, OverlayAction.REDUCE) and decision.quantity > 0:
                if decision.action == OverlayAction.EXIT or decision.quantity >= qty:
                    weights.loc[ts, code] = 0.0
                    entries.pop(code, None)
                else:
                    # 半仓：权重砍半
                    weights.loc[ts, code] = max(w, prev_w) * 0.5

    # 重新归一化
    scale = weights.abs().sum(axis=1).clip(lower=1.0)
    return weights.div(scale, axis=0).fillna(0.0)


def wrap_signal_engine_with_overlay(
    base_signal_engine: Callable[[dict[str, pd.DataFrame]], pd.DataFrame],
    *,
    config: Optional[SwingOverlayConfig] = None,
    initial_stop_pct: float = 0.08,
) -> Callable[[dict[str, pd.DataFrame]], pd.DataFrame]:
    """包装 signal_engine：基础权重 → overlay 调整。"""

    def _wrapped(data_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
        base = base_signal_engine(data_map)
        return adjust_target_weights_with_overlay(
            data_map,
            base,
            config=config,
            initial_stop_pct=initial_stop_pct,
        )

    return _wrapped


def format_overlay_monitor_lines(decision: OverlayDecision) -> list[str]:
    """position-monitor 用输出行。"""
    icon = {
        OverlayAction.EXIT: "🔴",
        OverlayAction.REDUCE: "🟠",
        OverlayAction.SWING_SELL: "🟡",
        OverlayAction.SWING_BUY: "🟢",
        OverlayAction.BLOCKED: "⛔",
        OverlayAction.HOLD: "⚪",
        OverlayAction.INFEASIBLE: "⚠️",
    }.get(decision.action, "📌")
    lines = [
        f"  {icon} [OVERLAY/{decision.urgency}] {format_decision(decision).replace(chr(10), ' | ')}"
    ]
    return lines
