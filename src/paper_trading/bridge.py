# -*- coding: utf-8 -*-
"""模拟交易桥接 — 连接仓位调度信号与 mx-moni 模拟账户。

职责:
  1. 接收 TradeSignal
  2. 通过 SignalAdapter 转换为 MoniOrder
  3. 调用 mx-moni API 执行模拟交易
  4. 跟踪订单状态、持仓盈亏
  5. 将执行结果喂入 learner 反馈系统
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PaperTradeResult:
    """单笔模拟交易执行结果。"""
    symbol: str
    action: str  # buy / sell
    order_id: str = ""
    status: str = "unknown"  # submitted / filled / rejected / error
    price: float = 0.0
    quantity: int = 0
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PaperTradingSession:
    """模拟交易会话状态。"""
    initial_capital: float = 100_000.0
    total_assets: float = 0.0
    avail_balance: float = 0.0
    total_pos_value: float = 0.0
    total_profit: float = 0.0
    pos_count: int = 0
    orders_today: int = 0
    last_sync: datetime = field(default_factory=datetime.now)


class PaperTradingBridge:
    """仓位调度 → mx-moni 桥接器。

    用法:
        bridge = PaperTradingBridge()
        session = bridge.sync()  # 同步账户状态
        result = bridge.execute_signal(signal)  # 执行单个信号
        results = bridge.execute_batch(signals)  # 批量执行
        bridge.report(results)  # 报告执行结果
    """

    def __init__(self, capital: float = 100_000.0):
        self._capital = capital
        self._results: list[PaperTradeResult] = []
        self._adapter = None  # 延迟导入

    @property
    def adapter(self):
        """懒加载 SignalAdapter。"""
        if self._adapter is None:
            from .signal_adapter import SignalAdapter
            self._adapter = SignalAdapter(initial_capital=self._capital)
        return self._adapter

    @property
    def _provider(self):
        """懒加载 MiaoXiangProvider。"""
        try:
            from src.data.miaoxiang_provider import MiaoXiangProvider
            return MiaoXiangProvider()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 账户同步
    # ------------------------------------------------------------------

    def sync(self) -> Optional[PaperTradingSession]:
        """同步 mx-moni 账户状态。"""
        mx = self._provider
        if mx is None:
            logger.warning("MiaoXiangProvider 不可用，无法同步账户")
            return None

        balance = mx.moni_get_balance()
        positions = mx.moni_get_positions()

        if balance is None:
            return None

        data = balance.get("data", balance)
        pos_data = positions.get("data", positions) if positions else {}

        session = PaperTradingSession(
            initial_capital=self._capital,
            total_assets=float(data.get("totalAssets", 0)),
            avail_balance=float(data.get("availBalance", 0)),
            total_pos_value=float(pos_data.get("totalPosValue", 0)) if pos_data else 0,
            total_profit=float(data.get("totalProfit", pos_data.get("totalProfit", 0))) if pos_data else 0,
            pos_count=int(pos_data.get("posCount", 0)) if pos_data else 0,
        )
        return session

    def sync_orders(self) -> Optional[dict]:
        """同步当日委托。"""
        mx = self._provider
        if mx is None:
            return None
        return mx.moni_get_orders()

    # ------------------------------------------------------------------
    # 信号执行
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        signal,  # TradeSignal
        current_price: float = 0.0,
        dry_run: bool = False,
    ) -> PaperTradeResult:
        """执行单个 TradeSignal → 模拟交易。

        Args:
            signal: 仓位调度产出的交易信号
            current_price: 当前市价
            dry_run: 仅转换不执行（用于回测）

        Returns:
            PaperTradeResult
        """
        order = self.adapter.to_moni_order(signal, current_price)
        if order is None:
            return PaperTradeResult(
                symbol=signal.symbol,
                action=getattr(signal, "action", "buy"),
                status="skipped",
                message="信号已处理或无效",
            )

        if dry_run:
            result = PaperTradeResult(
                symbol=order.symbol,
                action=order.action,
                order_id="DRY_RUN",
                status="submitted",
                price=order.price or current_price,
                quantity=order.quantity,
                message="干运行模式 — 未实际下单",
            )
            self._results.append(result)
            return result

        mx = self._provider
        if mx is None:
            return PaperTradeResult(
                symbol=order.symbol,
                action=order.action,
                status="error",
                message="MiaoXiangProvider 不可用",
            )

        resp = mx.moni_place_trade(
            stock_code=order.symbol,
            trade_type=order.action,
            price=order.price,
            quantity=order.quantity,
            use_market_price=order.use_market_price,
        )

        if resp is None:
            return PaperTradeResult(
                symbol=order.symbol,
                action=order.action,
                status="error",
                message="API 调用失败",
            )

        code = str(resp.get("code", resp.get("status", "")))
        message = str(resp.get("message", ""))
        is_success = code in ("200", "0", "ok")

        result = PaperTradeResult(
            symbol=order.symbol,
            action=order.action,
            order_id=str(resp.get("data", {}).get("orderId", resp.get("orderId", ""))),
            status="submitted" if is_success else "rejected",
            price=order.price,
            quantity=order.quantity,
            message=message,
        )
        self._results.append(result)
        return result

    def execute_batch(
        self,
        signals: list,  # list[TradeSignal]
        quotes: dict[str, float] | None = None,
        dry_run: bool = False,
    ) -> list[PaperTradeResult]:
        """批量执行信号。

        先同步账户资金，按信号权重排序，逐个执行。
        """
        # 先同步得到可用资金
        session = self.sync()
        if session and session.avail_balance > 0:
            self._adapter._capital = session.avail_balance

        results = []
        for signal in sorted(signals, key=lambda s: getattr(s, "weight", 0), reverse=True):
            price = (quotes or {}).get(signal.symbol, 0.0)
            result = self.execute_signal(signal, price, dry_run=dry_run)
            results.append(result)
            if result.status == "error":
                logger.warning("批量执行中断于 %s: %s", signal.symbol, result.message)
                break

        return results

    # ------------------------------------------------------------------
    # 反馈录入
    # ------------------------------------------------------------------

    def feed_to_learner(self) -> list[dict]:
        """将执行结果转换为 learner 可消费的反馈条目。"""
        feedbacks = []
        for r in self._results:
            if r.status == "skipped":
                continue
            feedbacks.append({
                "symbol": r.symbol,
                "action": r.action,
                "order_id": r.order_id,
                "status": r.status,
                "price": r.price,
                "quantity": r.quantity,
                "message": r.message,
                "timestamp": r.timestamp.isoformat(),
            })
        return feedbacks

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------

    def report(self, results: list[PaperTradeResult] | None = None) -> str:
        """生成执行报告。"""
        results = results or self._results
        if not results:
            return "📭 无模拟交易记录"

        submitted = [r for r in results if r.status == "submitted"]
        rejected = [r for r in results if r.status == "rejected"]
        errors = [r for r in results if r.status == "error"]
        skipped = [r for r in results if r.status == "skipped"]

        lines = [
            f"📊 模拟交易报告 ({len(results)} 笔)",
            f"  提交: {len(submitted)} | 拒绝: {len(rejected)} | 错误: {len(errors)} | 跳过: {len(skipped)}",
        ]
        for r in submitted:
            lines.append(f"  ✅ {r.action.upper()} {r.symbol} {r.quantity}股 @{r.price:.2f} [{r.order_id}]")
        for r in rejected:
            lines.append(f"  ❌ {r.action.upper()} {r.symbol} — {r.message}")
        for r in errors:
            lines.append(f"  ⚠️ {r.symbol} — {r.message}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def clear_results(self):
        self._results.clear()

    @property
    def total_orders(self) -> int:
        return len(self._results)
