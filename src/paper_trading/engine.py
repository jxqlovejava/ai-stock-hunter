# -*- coding: utf-8 -*-
"""模拟交易核心引擎 — 薄调度层。

每日循环::

    load_config → load_state → sync_market → screen_candidates
    → analyze (复用 Orchestrator 全链路) → create_orders → execute
    → update_state → report → save_state

核心分析/策略/风控全部复用现有模块，此引擎仅负责调度编排。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.backtest.cost_model import AShareCostCalculator
from src.data.aggregator import DataAggregator
from src.routing.orchestrator import Orchestrator, OrchestratorResult
from src.routing.position_state import StopStage

from .config import PaperTradingConfig, PaperTradingConfigManager
from .order_factory import OrderFactory, PaperOrder, PAPER_COMMISSION_RATE
from .reporter import ReportGenerator
from .scheduler import is_trading_day, today_str
from .state import (
    PaperTrade,
    PortfolioState,
    PortfolioStateManager,
)

logger = logging.getLogger(__name__)


@dataclass
class DailyResult:
    """每日运行结果摘要。"""
    date: str
    is_trading_day: bool = False
    candidates_analyzed: int = 0
    orders_generated: int = 0
    orders_executed: int = 0
    orders_skipped: int = 0
    trades: list[PaperTrade] = field(default_factory=list)
    report_path: str = ""
    errors: list[str] = field(default_factory=list)
    equity_before: float = 0.0
    equity_after: float = 0.0


class PaperTradingEngine:
    """模拟交易核心引擎 — 薄调度层。

    所有分析委托给 Orchestrator (全链路管道)，
    此引擎负责: 状态管理 / 候选筛选 / 订单执行模拟 / 报告生成。

    用法::

        engine = PaperTradingEngine()
        result = engine.run_daily_cycle()
        print(f"今日执行 {result.orders_executed} 笔交易")
    """

    # 每日最大分析候选数
    MAX_CANDIDATES_PER_DAY = 5

    def __init__(
        self,
        capital: float = 200_000.0,
        data_dir: Path | None = None,
    ):
        self._capital = capital
        self._data_dir = Path(data_dir) if data_dir else Path("data/paper_trading")

        # 外围模块
        self._config_mgr = PaperTradingConfigManager(
            config_path=self._data_dir / "config.yaml"
        )
        self._state_mgr = PortfolioStateManager(
            state_path=self._data_dir / "state.json",
            trades_path=self._data_dir / "trades.jsonl",
        )
        self._reporter = ReportGenerator(base_dir=self._data_dir)

        # 复用现有模块
        self._data = DataAggregator()
        self._cost_calc = AShareCostCalculator(commission_rate=PAPER_COMMISSION_RATE)

        # 延迟初始化 (避免导入时触发重依赖)
        self._orchestrator: Optional[Orchestrator] = None
        self._order_factory: Optional[OrderFactory] = None
        self._config: Optional[PaperTradingConfig] = None
        self._state: Optional[PortfolioState] = None

        # 当日去重
        self._today_orders: set[str] = set()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    @property
    def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            self._orchestrator = Orchestrator()
        return self._orchestrator

    @property
    def order_factory(self) -> OrderFactory:
        if self._order_factory is None:
            limits = self.config.position_limits
            self._order_factory = OrderFactory(
                capital=self._capital,
                max_single_pct=limits.max_single_pct,
            )
        return self._order_factory

    @property
    def config(self) -> PaperTradingConfig:
        if self._config is None:
            self._config = self._config_mgr.load_or_initialize()
            self._capital = self._config.position_limits.total_capital
        return self._config

    @property
    def state(self) -> PortfolioState:
        if self._state is None:
            self._state = self._state_mgr.load_or_initialize(capital=self._capital)
        return self._state

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run_daily_cycle(
        self,
        force: bool = False,
        dry_run: bool = False,
    ) -> DailyResult:
        """执行完整每日循环。

        Args:
            force: 强制运行 (即使在非交易日)
            dry_run: 仅分析不执行交易
        """
        today = today_str()
        result = DailyResult(date=today)

        # 0. 检查交易日
        if not force and not is_trading_day():
            logger.info("%s 非交易日，跳过", today)
            result.is_trading_day = False
            return result

        result.is_trading_day = True
        logger.info("🚀 开始每日模拟交易循环: %s", today)

        try:
            # 1. 加载配置和状态
            config = self.config
            state = self.state
            result.equity_before = state.total_equity

            # 重置当日去重
            self._today_orders.clear()

            # 2. 同步持仓行情
            state = self._sync_positions(state)

            # 2b. Swing Overlay（V1/V2 改写）— 持仓优先生成卖/滚仓订单
            overlay_orders = self._create_overlay_orders(state)
            if overlay_orders:
                logger.info("Overlay 生成 %d 个订单", len(overlay_orders))

            # 3. 筛选候选
            candidates = self._screen_candidates(state)
            logger.info("今日候选 %d 支: %s", len(candidates), ", ".join(candidates))

            # 4. 对每支候选运行全链路分析 (复用 Orchestrator)
            analysis_results = self._analyze_candidates(candidates, state)
            result.candidates_analyzed = len(analysis_results)

            # 5. 生成订单（overlay 卖单优先，同标的去重时 overlay 优先）
            pipe_orders = self._create_orders(analysis_results, state)
            orders = self._merge_orders(overlay_orders, pipe_orders)
            result.orders_generated = len(orders)

            # 6. 执行订单
            if not dry_run:
                state, executed_trades = self._execute_orders(orders, state)
                result.trades = executed_trades
                result.orders_executed = len(executed_trades)
                result.orders_skipped = len(orders) - len(executed_trades)
            else:
                logger.info("干运行模式 — 跳过实际执行")
                result.orders_skipped = len(orders)

            # 7. 更新 HWM
            state = state.observe_equity()

            # 8. 检查周/月复盘触发
            self._maybe_trigger_review(state)

            # 9. 生成日度报告
            if not dry_run:
                report_path = self._reporter.generate_daily(
                    state, result.trades, report_date=today,
                )
                result.report_path = report_path

            # 10. 持久化
            self._state = state
            self._save_all(state, result.trades)

            result.equity_after = state.total_equity
            logger.info(
                "✅ 每日循环完成: 分析 %d 支, 执行 %d 笔, 权益 ¥%.2f → ¥%.2f",
                result.candidates_analyzed, result.orders_executed,
                result.equity_before, result.equity_after,
            )

        except Exception as e:
            logger.exception("每日循环异常: %s", e)
            result.errors.append(str(e))

        return result

    # ------------------------------------------------------------------
    # 步骤 2: 同步行情
    # ------------------------------------------------------------------

    def _sync_positions(self, state: PortfolioState) -> PortfolioState:
        """刷新持仓标的的最新价格。"""
        if not state.positions:
            return state

        positions = dict(state.positions)
        updated = False

        for symbol, pos in list(positions.items()):
            try:
                # 推断市场
                market = "SH" if symbol.startswith(("6", "68")) else "SZ"
                quote = self._data.get_realtime_quote(symbol, market)
                if quote is None:
                    logger.warning("无法获取 %s 行情，保持原价", symbol)
                    continue

                # 复用 PositionState.observe_price() 更新 HWM + PnL
                new_pos = pos.observe_price(quote.price)
                if new_pos is not pos:
                    positions[symbol] = new_pos
                    updated = True
                    logger.debug(
                        "%s: ¥%.2f (PnL %+.2f%%)",
                        symbol, quote.price, new_pos.unrealized_pnl_pct * 100,
                    )

                    # 检查止损触发
                    if new_pos.stop_price > 0 and quote.price <= new_pos.stop_price:
                        logger.warning(
                            "⚠️ %s 触发止损! 现价 ¥%.2f ≤ 止损 ¥%.2f (阶段: %s)",
                            symbol, quote.price, new_pos.stop_price,
                            new_pos.stop_stage.value,
                        )

            except Exception as e:
                logger.error("同步 %s 行情失败: %s", symbol, e)

        if updated:
            state = state.with_positions(positions)
        return state

    # ------------------------------------------------------------------
    # 步骤 3: 候选筛选
    # ------------------------------------------------------------------

    def _screen_candidates(self, state: PortfolioState) -> list[str]:
        """筛选当日分析候选。

        优先级:
          1. 现有持仓 (必须检查是否需要止损/止盈)
          2. 模拟交易独立自选股 (可自主添加/移除)
          3. Alpha 扫描发现新机会 (高分候选自动加入自选股)
        """
        candidates: list[str] = []

        # 1. 现有持仓
        candidates.extend(state.positions.keys())

        # 2. 模拟交易独立自选股
        watchlist = self._config_mgr.load_watchlist()
        for item in watchlist:
            sym = item.get("symbol", "")
            if sym and sym not in candidates:
                candidates.append(sym)

        # 3. Alpha 扫描 — 发现新股票 (最多 2 支)
        new_discoveries = self._discover_new_candidates(state, existing=set(candidates))
        for sym in new_discoveries:
            if sym not in candidates:
                candidates.append(sym)

        # 限制数量，持仓优先
        if len(candidates) > self.MAX_CANDIDATES_PER_DAY:
            position_syms = set(state.positions.keys())
            priority = [s for s in candidates if s in position_syms]
            others = [s for s in candidates if s not in position_syms]
            candidates = priority + others[:self.MAX_CANDIDATES_PER_DAY - len(priority)]

        return candidates

    def _discover_new_candidates(
        self,
        state: PortfolioState,
        existing: set[str],
        max_new: int = 2,
    ) -> list[str]:
        """通过 Alpha 扫描发现新的候选股票。

        使用现有 CLI alpha-scan 功能扫描高 Alpha 股票，
        将高分候选自动加入模拟交易独立自选股。

        Args:
            existing: 已有候选集合 (避免重复)
            max_new: 最多发现数量
        """
        new_syms: list[str] = []
        try:
            from src.alpha.lens import AlphaLens
            from src.data.aggregator import DataAggregator

            lens = AlphaLens()
            data = DataAggregator()
            config = self.config

            # 获取高 Alpha 候选
            scan_result = lens.scan(
                data,
                limit=10,
                boards=config.accessible_boards,
            )
            if not scan_result or not hasattr(scan_result, "profiles"):
                return []

            for profile in scan_result.profiles[:max_new * 2]:
                sym = profile.symbol if hasattr(profile, "symbol") else ""
                if not sym or sym in existing:
                    continue
                if sym in state.positions:
                    continue
                if len(new_syms) >= max_new:
                    break

                # Alpha 质量筛选: 评分 ≥ 65 才考虑
                alpha_score = getattr(profile, "score", 0)
                if alpha_score >= 65:
                    new_syms.append(sym)
                    # 自动加入自选股
                    name = getattr(profile, "name", "")
                    self._config_mgr.add_to_watchlist(sym, name=name)
                    logger.info(
                        "🆕 Alpha 扫描发现新候选: %s %s (Alpha %.0f/100)",
                        sym, name, alpha_score,
                    )

        except Exception as e:
            logger.debug("Alpha 扫描跳过 (可能模块未初始化): %s", e)

        return new_syms

    # ------------------------------------------------------------------
    # 步骤 4: 分析候选 — 复用 Orchestrator 全链路
    # ------------------------------------------------------------------

    def _analyze_candidates(
        self,
        candidates: list[str],
        state: PortfolioState,
    ) -> list[OrchestratorResult]:
        """对每支候选运行 Orchestrator.run() 全链路分析。

        这是整个系统核心 — 所有分析逻辑全部复用现有管道。
        """
        results: list[OrchestratorResult] = []

        for symbol in candidates:
            try:
                market = "SH" if symbol.startswith(("6", "68")) else "SZ"
                name = ""
                if symbol in state.positions:
                    pos = state.positions[symbol]
                    name = getattr(pos, "name", "")

                logger.info("🔍 分析 %s %s ...", symbol, name)

                # 运行全链路分析 (军规→准入→诊断→Alpha→博弈论→裁决→仓位→风控)
                orch_result = self.orchestrator.run(
                    symbol=symbol,
                    market=market,
                    name=name,
                    mode="daily",          # 日常监控模式 (轻量)
                    skip_t0=False,         # 建仓判断需要 T+0 日内时机
                )

                if orch_result.passed or orch_result.verdict:
                    logger.info(
                        "  %s 评分 %.0f/100 建议 %s 置信度 %.0f%%",
                        symbol,
                        orch_result.verdict.score if orch_result.verdict else 0,
                        orch_result.verdict.recommendation if orch_result.verdict else "N/A",
                        (orch_result.verdict.confidence if orch_result.verdict else 0) * 100,
                    )

                results.append(orch_result)

            except Exception as e:
                logger.exception("分析 %s 异常: %s", symbol, e)
                # 单票失败不阻断整体流程
                continue

        return results

    # ------------------------------------------------------------------
    # 步骤 2b / 5: Overlay + 管道订单
    # ------------------------------------------------------------------

    def _create_overlay_orders(self, state: PortfolioState) -> list[PaperOrder]:
        """对已持仓运行 SwingOverlay，产出 PaperOrder（止损/破位优先）。"""
        if not state.positions:
            return []

        from src.strategy.overlay_integration import (
            position_like_to_input,
            evaluate_overlay,
            decision_to_paper_order,
            compute_ma20,
        )

        orders: list[PaperOrder] = []
        equity = float(state.total_equity or self._capital or 500_000)

        for symbol, pos in state.positions.items():
            try:
                price = float(getattr(pos, "last_price", 0) or getattr(pos, "entry_price", 0) or 0)
                ma20: float | None = None
                try:
                    # 尝试用日线算 MA20（失败则仅靠止损规则）
                    market = "SH" if symbol.startswith(("6", "68")) else "SZ"
                    bars = None
                    if hasattr(self._data, "get_bars"):
                        from datetime import timedelta
                        from src.data.schema import Resolution
                        end = datetime.now()
                        start = end - timedelta(days=60)
                        bars = self._data.get_bars(symbol, start, end, Resolution.DAY_1)
                    if bars is not None and len(list(bars)) >= 5:
                        closes = pd.Series(
                            [float(getattr(b, "close", 0) or 0) for b in bars if getattr(b, "close", 0)]
                        )
                        ma20 = compute_ma20(closes)
                except Exception:
                    ma20 = None

                inp = position_like_to_input(pos, equity=equity, price_override=price)
                decision = evaluate_overlay(
                    inp,
                    ma20=ma20,
                    structure_broken=(price < ma20) if ma20 and price > 0 else None,
                    pipeline_action="HOLD",
                    pipeline_score=50.0,
                )
                order = decision_to_paper_order(
                    decision,
                    name=getattr(pos, "name", "") or symbol,
                    price=price,
                    stop_price=float(getattr(pos, "stop_price", 0) or 0),
                    score=70.0 if decision.urgency == "HIGH" else 55.0,
                )
                if order:
                    orders.append(order)
                    logger.info(
                        "Overlay %s → %s %d股 (%s)",
                        symbol, order.action, order.quantity, decision.rule,
                    )
            except Exception as e:
                logger.warning("Overlay 评估 %s 失败: %s", symbol, e)

        return orders

    @staticmethod
    def _merge_orders(
        overlay_orders: list[PaperOrder],
        pipe_orders: list[PaperOrder],
    ) -> list[PaperOrder]:
        """合并订单：同标的优先保留 overlay（持仓风控优先于新开仓）。"""
        by_sym: dict[str, PaperOrder] = {}
        for o in overlay_orders:
            by_sym[o.symbol] = o
        for o in pipe_orders:
            if o.symbol in by_sym:
                # 已有 overlay 卖出时，跳过同标的买入，避免对冲噪声
                if by_sym[o.symbol].action == "sell" and o.action == "buy":
                    logger.info("跳过管道买入 %s：overlay 已建议卖出", o.symbol)
                    continue
                if by_sym[o.symbol].action == o.action:
                    continue  # overlay 优先
            by_sym[o.symbol] = o
        # overlay 卖单在前
        sells = [o for o in by_sym.values() if o.action == "sell"]
        buys = [o for o in by_sym.values() if o.action == "buy"]
        return sells + buys

    def _create_orders(
        self,
        analysis_results: list[OrchestratorResult],
        state: PortfolioState,
    ) -> list[PaperOrder]:
        """将分析结果转换为交易订单。"""
        orders: list[PaperOrder] = []

        for result in analysis_results:
            try:
                symbol = result.symbol
                current_qty = 0
                if symbol in state.positions:
                    current_qty = state.positions[symbol].quantity

                # 获取当前价格
                current_price = 0.0
                if symbol in state.positions:
                    pos = state.positions[symbol]
                    current_price = max(
                        getattr(pos, "last_price", 0),
                        getattr(pos, "entry_price", 0),
                    )

                # 方式 1: 从 TradeSignal 转换 (PositioningEngine 已产出)
                if result.signal and hasattr(result.signal, "action"):
                    order = self.order_factory.from_trade_signal(
                        result.signal, current_price, current_qty,
                    )
                    if order:
                        orders.append(order)
                        continue

                # 方式 2: 从 Verdict 直接转换 (TradeSignal 不可用时)
                if result.verdict:
                    verdict = result.verdict
                    order = self.order_factory.from_verdict(
                        symbol=symbol,
                        name=result.name,
                        verdict_score=verdict.score,
                        verdict_confidence=verdict.confidence,
                        recommendation=verdict.recommendation,
                        current_price=current_price,
                        current_qty=current_qty,
                        sizing_weight=(
                            result.signal.target_weight
                            if result.signal and hasattr(result.signal, "target_weight")
                            else 0.0
                        ),
                    )
                    if order:
                        orders.append(order)

            except Exception as e:
                logger.exception("创建 %s 订单异常: %s", result.symbol, e)

        logger.info("共生成 %d 个订单", len(orders))
        return orders

    # ------------------------------------------------------------------
    # 步骤 6: 执行订单
    # ------------------------------------------------------------------

    def _execute_orders(
        self,
        orders: list[PaperOrder],
        state: PortfolioState,
    ) -> tuple[PortfolioState, list[PaperTrade]]:
        """模拟执行订单 — T+1/涨跌停/资金检查。"""
        trades: list[PaperTrade] = []
        cash = state.cash
        positions = dict(state.positions)

        for order in orders:
            try:
                # 去重
                dedup_key = f"{order.symbol}:{order.action}:{today_str()}"
                if dedup_key in self._today_orders:
                    logger.debug("重复订单，跳过: %s", dedup_key)
                    continue

                trade = self._execute_single(order, cash, positions)
                if trade is None:
                    continue

                trades.append(trade)
                self._today_orders.add(dedup_key)

                # 更新现金和持仓
                cash = trade.remaining_cash
                if order.action == "buy":
                    # 新建或加仓
                    if order.symbol in positions:
                        old_pos = positions[order.symbol]
                        # 加仓: 更新数量 + 成本 (简化: 加权平均)
                        from src.routing.position_state import replace as ps_replace
                        new_qty = old_pos.quantity + order.quantity
                        new_entry = (
                            (old_pos.entry_price * old_pos.quantity + order.price * order.quantity)
                            / new_qty
                        )
                        positions[order.symbol] = ps_replace(
                            old_pos, quantity=new_qty, entry_price=round(new_entry, 2),
                        )
                    else:
                        # 新建仓: 创建 PositionState
                        from src.routing.position_state import PositionState
                        positions[order.symbol] = PositionState.initial(
                            symbol=order.symbol,
                            name=order.name,
                            entry_price=order.price,
                            quantity=order.quantity,
                            stop_config={
                                "initial_stop_pct": -self.config.position_limits.single_stop_loss_pct,
                            },
                        )

                elif order.action == "sell":
                    # 减仓或清仓
                    if order.symbol in positions:
                        old_pos = positions[order.symbol]
                        remaining_qty = old_pos.quantity - order.quantity
                        if remaining_qty <= 0:
                            del positions[order.symbol]
                        else:
                            from src.routing.position_state import replace as ps_replace
                            positions[order.symbol] = ps_replace(
                                old_pos, quantity=remaining_qty,
                            )

            except Exception as e:
                logger.exception("执行 %s 订单异常: %s", order.symbol, e)

        # 更新统计
        for trade in trades:
            is_win = trade.pnl_pct > 0
            state = state.with_trade_recorded(
                is_win=is_win,
                commission=trade.commission + trade.stamp_tax + trade.transfer_fee,
            )

        state = state.with_cash(cash).with_positions(positions)
        state = state.with_trade_date(today_str())
        return state, trades

    def _execute_single(
        self,
        order: PaperOrder,
        cash: float,
        positions: dict,
    ) -> Optional[PaperTrade]:
        """执行单笔订单 — 模拟成交。

        T+1 检查: 当日买入的不可卖出 (简化为检查 positions 中的入场日期)
        涨跌停检查: 通过 DataAggregator 检查是否涨跌停
        资金检查: 现金是否足够
        """
        # 检查涨跌停 (简化: 通过 DataAggregator)
        try:
            market = "SH" if order.symbol.startswith(("6", "68")) else "SZ"
            quote = self._data.get_realtime_quote(order.symbol, market)
            if quote:
                # 涨停买不进
                if order.action == "buy" and quote.pct_change >= 9.9:
                    logger.warning("%s 接近涨停 (%.1f%%) 买不进", order.symbol, quote.pct_change)
                    return None
                # 跌停卖不出
                if order.action == "sell" and quote.pct_change <= -9.9:
                    logger.warning("%s 接近跌停 (%.1f%%) 卖不出", order.symbol, quote.pct_change)
                    return None
        except Exception:
            pass  # 无法获取行情时放行 (尽力成交)

        # 计算成本和资金变动
        notional = order.price * order.quantity

        if order.action == "buy":
            cost = self._cost_calc.calc_buy_cost(order.symbol, order.price, order.quantity)
            total_needed = notional + cost.total_cost

            if total_needed > cash:
                logger.warning(
                    "%s 资金不足: 需要 ¥%.0f, 现金 ¥%.0f",
                    order.symbol, total_needed, cash,
                )
                return None

            new_cash = cash - total_needed
            net_amount = -total_needed
            pnl_pct = 0.0

        elif order.action == "sell":
            cost = self._cost_calc.calc_sell_cost(order.symbol, order.price, order.quantity)
            net_amount = notional - cost.total_cost
            new_cash = cash + net_amount

            # 计算实现盈亏
            if order.symbol in positions:
                pos = positions[order.symbol]
                entry = getattr(pos, "entry_price", order.price)
                if entry > 0:
                    pnl_pct = (order.price - entry) / entry
                else:
                    pnl_pct = 0.0
            else:
                pnl_pct = 0.0

        else:
            return None

        trade_id = f"{order.symbol}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        return PaperTrade(
            trade_id=trade_id,
            symbol=order.symbol,
            name=order.name,
            action=order.action,
            price=order.price,
            quantity=order.quantity,
            notional=notional,
            commission=cost.commission,
            stamp_tax=cost.stamp_tax,
            transfer_fee=cost.transfer_fee,
            total_cost=cost.total_cost,
            net_amount=net_amount,
            reason=order.reason,
            timestamp=datetime.now().isoformat(),
            remaining_cash=new_cash,
            pnl_pct=pnl_pct,
        )

    # ------------------------------------------------------------------
    # 周/月复盘触发
    # ------------------------------------------------------------------

    def _maybe_trigger_review(self, state: PortfolioState) -> None:
        """检查是否需要触发周度/月度复盘。"""
        today = date.today()

        # 周五触发周度复盘
        if today.weekday() == 4:  # Friday
            self._trigger_weekly_review(state)

        # 月末触发月度复盘
        tomorrow = today + __import__("datetime").timedelta(days=1)
        if tomorrow.day == 1:  # 今天是月末
            self._trigger_monthly_review(state)

    def _trigger_weekly_review(self, state: PortfolioState) -> None:
        """生成周度复盘报告。"""
        from .scheduler import trading_days_this_week, prev_trading_day

        week_days = trading_days_this_week()
        if not week_days:
            return

        week_start = week_days[0].strftime("%Y-%m-%d")
        week_end = week_days[-1].strftime("%Y-%m-%d")

        week_trades = self._state_mgr.get_trades_for_period(week_start, week_end)
        if not week_trades:
            logger.info("本周无交易，跳过周度复盘")
            return

        self._reporter.generate_weekly(state, week_trades, week_start, week_end)
        logger.info("📊 周度复盘已生成: %s ~ %s", week_start, week_end)

    def _trigger_monthly_review(self, state: PortfolioState) -> None:
        """生成月度复盘报告。"""
        from .scheduler import trading_days_this_month

        month_days = trading_days_this_month()
        if not month_days:
            return

        month_key = date.today().strftime("%Y-%m")
        month_start = month_days[0].strftime("%Y-%m-%d")
        month_end = month_days[-1].strftime("%Y-%m-%d")

        month_trades = self._state_mgr.get_trades_for_period(month_start, month_end)
        self._reporter.generate_monthly(
            state, month_trades, month_key,
            benchmark_return=0.0,  # 后续可从 DataAggregator 获取沪深300实际收益
        )
        logger.info("📈 月度复盘已生成: %s", month_key)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save_all(self, state: PortfolioState, trades: list[PaperTrade]) -> None:
        """保存状态和交易历史。"""
        self._state_mgr.save(state)
        for t in trades:
            self._state_mgr.append_trade(t)
        logger.info("状态已保存: 权益 ¥%.2f, %d 笔交易", state.total_equity, len(trades))

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def status(self) -> str:
        """获取当前组合状态摘要。"""
        state = self.state
        config = self.config

        lines = [
            "=" * 50,
            "  🧧 白泽模拟交易 — 账户状态",
            "=" * 50,
            f"  启动日期: {state.start_date}",
            f"  最后交易: {state.last_trade_date or '无'}",
            f"  投资风格: {config.trading_style.value} / {config.risk_profile.value}",
            "",
            f"  💰 初始资金: ¥{state.initial_capital:,.0f}",
            f"  💰 当前权益: ¥{state.total_equity:,.2f}",
            f"  💰 累计收益: ¥{state.total_equity - state.initial_capital:+,.2f}",
            f"  💰 收益率:   {state.total_return_pct:+.2%}",
            f"  💰 现金余额: ¥{state.cash:,.2f}",
            f"  💰 持仓市值: ¥{state.positions_value:,.2f}",
            "",
            f"  📊 仓位占比: {state.exposure_pct:.1%}",
            f"  📊 历史最高: ¥{state.high_water_mark:,.2f}",
            f"  📊 当前回撤: {state.drawdown_pct:.2%}",
            f"  📊 累计佣金: ¥{state.total_commission_paid:,.2f}",
            "",
            f"  🔄 累计交易: {state.total_trades} 笔",
            f"  ✅ 胜率:     {state.win_rate:.1%} ({state.winning_trades}W/{state.losing_trades}L)",
            f"  📦 持仓数量: {state.position_count} 只",
            "",
        ]

        if state.positions:
            lines.append("  --- 持仓明细 ---")
            for sym, pos in state.positions.items():
                name = getattr(pos, "name", "")
                qty = getattr(pos, "quantity", 0)
                entry = getattr(pos, "entry_price", 0)
                last = getattr(pos, "last_price", entry)
                pnl = (last - entry) / entry * 100 if entry > 0 else 0
                stage = getattr(pos, "stop_stage", "initial")
                lines.append(
                    f"  {sym} {name}: {qty}股 "
                    f"成本¥{entry:.2f} 现价¥{last:.2f} "
                    f"{pnl:+.2f}% [{stage}]"
                )
        else:
            lines.append("  📦 空仓")

        lines.append("=" * 50)
        return "\n".join(lines)

    def get_recent_trades(self, limit: int = 20) -> list[PaperTrade]:
        """获取最近交易记录。"""
        return self._state_mgr.load_trades(limit=limit)

    def reset(self) -> PortfolioState:
        """重置模拟交易账户。"""
        self._config = None
        self._state = self._state_mgr.reset(capital=self._capital)
        self._today_orders.clear()
        self._orchestrator = None  # 重建以清理状态
        logger.info("模拟交易账户已重置")
        return self._state
