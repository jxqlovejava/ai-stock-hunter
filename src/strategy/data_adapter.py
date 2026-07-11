# -*- coding: utf-8 -*-
"""MarketDataAdapter — 将现有系统数据源注入入场模板所需字段。

将 game_theory (北向/龙虎榜/资金流) + industry (板块分类) 的产出
翻译为 entry_templates 能直接消费的 market_data dict。

用法::

    adapter = MarketDataAdapter()
    enriched = adapter.enrich(["002460", "600519"], existing_market_data)
    engine.run_daily(watchlist, portfolio, enriched)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MarketDataAdapter:
    """Fetch A-share specific data and enrich market_data for entry templates.

    All data fetches are best-effort — single-source failure does not block others.
    """

    def __init__(self):
        self._northbound_cache: dict | None = None
        self._lhb_cache: dict | None = None
        self._sector_cache: dict | None = None
        self._capital_flow_cache: dict | None = None

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def enrich(
        self,
        symbols: list[str],
        market_data: dict,
        *,
        include_northbound: bool = True,
        include_sector: bool = True,
        include_lhb: bool = True,
        include_capital_flow: bool = True,
    ) -> dict:
        """Add A-share-specific fields to market_data for each symbol.

        Returns a new dict (does not mutate input).
        """
        import copy
        enriched = copy.deepcopy(market_data)

        for symbol in symbols:
            if symbol not in enriched:
                enriched[symbol] = {}
            entry = enriched[symbol]

            if include_northbound:
                self._enrich_northbound(symbol, entry)
            if include_capital_flow:
                self._enrich_capital_flow(symbol, entry)
            if include_sector:
                self._enrich_sector(symbol, entry)
            if include_lhb:
                self._enrich_lhb(symbol, entry)

        return enriched

    # ------------------------------------------------------------------
    # northbound — 北向资金
    # ------------------------------------------------------------------

    def _enrich_northbound(self, symbol: str, entry: dict) -> None:
        """Add northbound_inflow_Nd, northbound_holding_pct fields."""
        try:
            profile = self._get_northbound_profile()
            if profile is None:
                return
            cd = getattr(profile, "consecutive_days", 0) or 0
            if cd >= 3:
                entry[f"northbound_inflow_3d"] = 1
            if abs(cd) >= 5:
                entry[f"northbound_inflow_5d"] = 1 if cd > 0 else 0
            # northbound_holding_pct — try from profile or game_theory
            holding = getattr(profile, "large_cap_ratio", 0) or 0
            if holding > 0:
                entry["northbound_holding_pct"] = holding
        except Exception:
            logger.debug("Northbound enrich skipped for %s", symbol, exc_info=True)

    def _get_northbound_profile(self):
        if self._northbound_cache is not None:
            return self._northbound_cache
        try:
            from src.game_theory.northbound import NorthboundAnalyzer
            analyzer = NorthboundAnalyzer()
            self._northbound_cache = analyzer.analyze()
        except Exception:
            logger.debug("NorthboundAnalyzer unavailable", exc_info=True)
            self._northbound_cache = None
        return self._northbound_cache

    # ------------------------------------------------------------------
    # capital flow — 主力资金流
    # ------------------------------------------------------------------

    def _enrich_capital_flow(self, symbol: str, entry: dict) -> None:
        """Add main_capital_inflow_Nd fields."""
        try:
            cf = self._get_capital_flow(symbol)
            if cf is None:
                return
            cd = getattr(cf, "main_consecutive_days", 0) or 0
            if cd >= 3:
                entry["main_capital_inflow_3d"] = 1
            if cd >= 5:
                entry["main_capital_inflow_5d"] = 1
            # also add main_net for reference
            mn = getattr(cf, "main_net", 0) or 0
            if mn != 0:
                entry["main_net_wan"] = mn
        except Exception:
            logger.debug("Capital flow enrich skipped for %s", symbol, exc_info=True)

    def _get_capital_flow(self, symbol: str):
        if self._capital_flow_cache is None:
            self._capital_flow_cache = {}
        if symbol in self._capital_flow_cache:
            return self._capital_flow_cache[symbol]
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            flow_data = agg.get_money_flow(symbol)
            if flow_data is not None and not getattr(flow_data, "empty", True):
                from src.game_theory.capital_flow import CapitalFlowAnalyzer
                analyzer = CapitalFlowAnalyzer()
                result = analyzer.analyze(
                    symbol=symbol,
                    super_large_net=getattr(flow_data, "super_large_net", 0) or 0,
                    large_net=getattr(flow_data, "large_net", 0) or 0,
                    medium_net=getattr(flow_data, "medium_net", 0) or 0,
                    small_net=getattr(flow_data, "small_net", 0) or 0,
                    total_turnover=getattr(flow_data, "total_turnover", 0) or 0,
                    price_change_pct=(getattr(flow_data, "price_change_pct", 0) or 0) / 100.0,
                    main_consecutive_days=getattr(flow_data, "main_consecutive_days", 0) or 0,
                    recent_price_trend=getattr(flow_data, "recent_price_trend", "neutral") or "neutral",
                )
                self._capital_flow_cache[symbol] = result
                return result
        except Exception:
            logger.debug("CapitalFlowAnalyzer unavailable for %s", symbol, exc_info=True)
        self._capital_flow_cache[symbol] = None
        return None

    # ------------------------------------------------------------------
    # sector — 板块共振
    # ------------------------------------------------------------------

    def _enrich_sector(self, symbol: str, entry: dict) -> None:
        """Add sector_code, sector_name, sector_*_count fields."""
        try:
            sc = self._get_sector_classification(symbol)
            if sc is None:
                return
            entry["sector_code"] = getattr(sc, "sw1_code", "")
            entry["sector_name"] = getattr(sc, "sw1_name", "")

            # Try to get sector activity counts
            sector_name = entry.get("sector_name", "")
            if sector_name:
                counts = self._get_sector_activity(sector_name)
                if counts:
                    entry["sector_rising_count"] = counts.get("rising", 0)
                    entry["sector_volume_surge_count"] = counts.get("volume_surge", 0)
        except Exception:
            logger.debug("Sector enrich skipped for %s", symbol, exc_info=True)

    def _get_sector_classification(self, symbol: str):
        if self._sector_cache is None:
            self._sector_cache = {}
        if symbol in self._sector_cache:
            return self._sector_cache[symbol]
        try:
            from src.industry.classifier import SectorClassifier
            sc = SectorClassifier()
            result = sc.classify(symbol)
            self._sector_cache[symbol] = result
            return result
        except Exception:
            logger.debug("SectorClassifier unavailable for %s", symbol, exc_info=True)
            self._sector_cache[symbol] = None
            return None

    def _get_sector_activity(self, sector_name: str) -> dict | None:
        """Get rough sector activity: how many stocks rising / volume surging."""
        try:
            from src.industry.classifier import SectorClassifier
            sc = SectorClassifier()
            stocks = sc.get_sector_stocks(sector_name)
            if not stocks:
                return None
            # For now, return placeholder — full sector scan is expensive.
            # Real implementation should batch-fetch quotes for all sector stocks.
            return {"rising": 0, "volume_surge": 0}
        except Exception:
            return None

    # ------------------------------------------------------------------
    # dragon-tiger — 龙虎榜
    # ------------------------------------------------------------------

    def _enrich_lhb(self, symbol: str, entry: dict) -> None:
        """Add lhb_is_on_list, lhb_net_buy, lhb_top_seats, lhb_seal_strength."""
        try:
            activities = self._get_lhb_data()
            if not activities:
                return
            symbol_activities = [
                a for a in activities
                if getattr(a, "stock_symbol", "") == symbol
            ]
            if not symbol_activities:
                return
            entry["lhb_is_on_list"] = 1
            total_net = sum(getattr(a, "net_amount", 0) or 0 for a in symbol_activities)
            entry["lhb_net_buy"] = total_net  # 万元

            top_seats = [
                getattr(a, "seat_name", "")
                for a in symbol_activities
                if getattr(a, "identified", False) and (getattr(a, "net_amount", 0) or 0) > 0
            ]
            entry["lhb_top_seats"] = top_seats
            entry["lhb_seal_strength"] = 0.0  # 需要从涨停池额外获取，占位
        except Exception:
            logger.debug("LHB enrich skipped for %s", symbol, exc_info=True)

    def _get_lhb_data(self) -> list | None:
        if self._lhb_cache is not None:
            return self._lhb_cache
        try:
            from src.game_theory.seats import SeatTracker
            tracker = SeatTracker()
            self._lhb_cache = tracker.analyze_daily()
        except Exception:
            logger.debug("SeatTracker unavailable", exc_info=True)
            self._lhb_cache = None
        return self._lhb_cache
