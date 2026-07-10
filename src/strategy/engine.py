# -*- coding: utf-8 -*-
"""StrategyEngine orchestrator — wires PositionSizer, ExitRuleEngine, AddRuleEngine.

Flow: entry_rules (watchlist→ENTER) → exit_engine (EXIT/REDUCE) → add_engine (ADD)
→ sizing → dedup → sort.
"""

from __future__ import annotations

import logging
from typing import Callable

from .types import (
    AddCheckResult,
    ExitCheckResult,
    PortfolioSnapshot,
    PositionSize,
    StrategySignal,
)

logger = logging.getLogger(__name__)

_URGENCY_RANK = {"HIGH": 0, "NORMAL": 1, "LOW": 2}


class StrategyEngine:
    """Central orchestrator managing the full strategy pipeline.

    Usage::

        engine = StrategyEngine()
        engine.register_entry_rule(my_rule)  # optional — user fills later
        signals = engine.run_daily(watchlist, portfolio, market_data)
    """

    def __init__(self, config: dict | None = None, auto_activate: bool = True):
        from .sizing import PositionSizer as _PS
        from .exit_rules import ExitRuleEngine as _ER
        from .add_rules import AddRuleEngine as _AR
        from .signal_filter import SignalQualityFilter as _SF

        self.config = config or {}
        self.sizer = _PS()
        self.exit_engine = _ER()
        self.add_engine = _AR()
        self.filter = _SF()
        self.entry_rules: list[Callable] = []
        self._adapter = None  # lazy-init

        if auto_activate:
            self.use_templates()  # 默认激活全部 7 个入场模板

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    @property
    def adapter(self):
        """Lazy-init MarketDataAdapter for A-share data enrichment."""
        if self._adapter is None:
            from .data_adapter import MarketDataAdapter
            self._adapter = MarketDataAdapter()
        return self._adapter

    def enrich_market_data(self, symbols: list[str], market_data: dict) -> dict:
        """Enrich market_data with northbound/sector/LHB fields from live data sources.

        Call before run_daily() to connect entry templates to real data.
        """
        return self.adapter.enrich(symbols, market_data)

    def register_entry_rule(self, rule: Callable) -> None:
        """Register an entry-rule callable.

        Signature: ``rule(watchlist, portfolio, market_data) → list[StrategySignal]``

        This is where you plug in your own entry logic after learning.
        """
        self.entry_rules.append(rule)

    def use_templates(self, names: list[str] | None = None) -> None:
        """Register entry templates by name.

        Args:
            names: template names to activate. None → all 7 templates.

        Example:
            engine.use_templates(["trend_following", "capital_inflow"])
        """
        from .entry_templates import ALL_TEMPLATES

        if names is None:
            names = list(ALL_TEMPLATES.keys())
        for name in names:
            tmpl = ALL_TEMPLATES.get(name)
            if tmpl:
                self.register_entry_rule(tmpl)
                logger.info("Entry template registered: %s", name)

    def run_daily(
        self,
        watchlist: list[str],
        portfolio: PortfolioSnapshot,
        market_data: dict,
    ) -> list[StrategySignal]:
        """Run full daily strategy pipeline.

        Returns signals sorted by urgency (HIGH first). Entry rules are skipped
        until user registers them.
        """
        signals: list[StrategySignal] = []

        try:
            # 1. Entry rules
            if self.entry_rules:
                self._run_entry_rules(watchlist, portfolio, market_data, signals)

            # 1.5. Signal quality filter — 交叉验证，拦截操纵/诱多信号
            filtered: list[StrategySignal] = []
            for sig in signals:
                if sig.is_entry:
                    mkt = market_data.get(sig.symbol, {})
                    fr = self.filter.check(sig, mkt)
                    if fr.is_blocked:
                        logger.info("信号拦截: %s — %s", sig.symbol, fr.blocked_by)
                        continue
                    if fr.warnings:
                        sig.reason += f" ⚠️ {'; '.join(fr.warnings)}"
                    sig.strength = fr.adjusted_strength
                filtered.append(sig)
            signals = filtered

            # 2. Exit check — 对每个持仓跑退出规则
            for symbol, pos_data in portfolio.positions.items():
                try:
                    # exit_engine.check(position, market_data)
                    # position dict already contains symbol
                    mkt = market_data.get(symbol, {})
                    exit_result = self.exit_engine.check(pos_data, mkt)
                    if exit_result.should_exit:
                        signals.append(_exit_result_to_signal(exit_result))
                except Exception:
                    logger.exception("Exit check failed for %s", symbol)

            # 3. Add check — 对未退出的持仓跑加仓规则
            exiting_symbols = {s.symbol for s in signals if s.is_exit}
            for symbol, pos_data in portfolio.positions.items():
                if symbol in exiting_symbols:
                    continue
                try:
                    # add_engine.check(position, new_signal_strength, days_since_last_add)
                    add_result = self.add_engine.check(pos_data)
                    if add_result.should_add:
                        signals.append(_add_result_to_signal(add_result))
                except Exception:
                    logger.exception("Add check failed for %s", symbol)

            # 4. Sizing — 对 ENTER/ADD 信号计算仓位
            for sig in signals:
                if sig.is_entry or sig.is_add:
                    try:
                        mkt = market_data.get(sig.symbol, {})
                        atr = mkt.get("atr", 0.01)
                        price = mkt.get("current_price", 0.0)
                        size = self.sizer.calculate(sig, portfolio, atr=atr, entry_price=price)
                        sig.quantity = size.quantity
                        sig.weight_pct = size.weight_pct
                    except Exception:
                        logger.exception("Sizing failed for %s", sig.symbol)

            return _sort_by_urgency(_dedup(signals))
        except Exception:
            logger.exception("StrategyEngine.run_daily failed")
            return []

    def run_on_position(
        self, position: dict, market_data: dict | None = None
    ) -> StrategySignal:
        """Evaluate a single position: check exit → add → return signal."""
        mkt = market_data or {}
        symbol = position.get("symbol", "")
        try:
            exit_result = self.exit_engine.check(position, mkt)
            if exit_result.should_exit:
                return _exit_result_to_signal(exit_result)
        except Exception:
            logger.exception("Exit check failed for %s", symbol)
        try:
            add_result = self.add_engine.check(position)
            if add_result.should_add:
                return _add_result_to_signal(add_result)
        except Exception:
            logger.exception("Add check failed for %s", symbol)
        return StrategySignal(symbol=symbol, action="HOLD", reason="No rule triggered")

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _run_entry_rules(
        self,
        watchlist: list[str],
        portfolio: PortfolioSnapshot,
        market_data: dict,
        signals: list[StrategySignal],
    ) -> None:
        for rule in self.entry_rules:
            try:
                signals.extend(rule(watchlist, portfolio, market_data))
            except Exception:
                logger.exception("Entry rule '%s' failed", getattr(rule, "__name__", "unknown"))


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------


def _exit_result_to_signal(result: ExitCheckResult) -> StrategySignal:
    return StrategySignal(
        symbol=result.symbol,
        action="EXIT" if result.exit_pct >= 100 else "REDUCE",
        reason=result.reason,
        urgency=result.urgency,
    )


def _add_result_to_signal(result: AddCheckResult) -> StrategySignal:
    return StrategySignal(symbol=result.symbol, action="ADD", reason=result.reason)


def _dedup(signals: list[StrategySignal]) -> list[StrategySignal]:
    """If both EXIT and ADD exist for same symbol, EXIT wins."""
    exit_symbols = {s.symbol for s in signals if s.is_exit}
    return [s for s in signals if not (s.is_add and s.symbol in exit_symbols)]


def _sort_by_urgency(signals: list[StrategySignal]) -> list[StrategySignal]:
    return sorted(signals, key=lambda s: _URGENCY_RANK.get(s.urgency, 99))
