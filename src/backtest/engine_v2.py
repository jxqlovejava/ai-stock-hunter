# -*- coding: utf-8 -*-
"""Vibe-Trading 风格 V2 回测引擎。

使用 loader registry 取数，ChinaAEngine 执行，AShareHardGuard 过滤。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from src.backtest.engines import ChinaAEngine, EngineResult
from src.backtest.guards import AShareHardGuard
from src.data.aggregator import DataAggregator
from src.data.loaders import resolve_loader
from src.data.schema import Quote
from src.data.source_citation import SourceCitation, make_citation


class VibeBacktestEngine:
    """V2 回测引擎入口。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        signal_engine: Optional[Callable[[dict[str, pd.DataFrame]], pd.DataFrame]] = None,
        use_swing_overlay: bool = True,
        overlay_stop_pct: float = 0.08,
    ):
        self.initial_cash = initial_cash
        base = signal_engine or self._default_signal
        self.use_swing_overlay = use_swing_overlay
        self.overlay_stop_pct = overlay_stop_pct
        if use_swing_overlay:
            from src.strategy.overlay_integration import wrap_signal_engine_with_overlay
            self.signal_engine = wrap_signal_engine_with_overlay(
                base, initial_stop_pct=overlay_stop_pct,
            )
        else:
            self.signal_engine = base
        self.guard = AShareHardGuard()
        self.aggregator = DataAggregator()

    def run(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        config: Optional[dict] = None,
        data_map: Optional[dict[str, pd.DataFrame]] = None,
        quotes: Optional[dict[str, Quote]] = None,
    ) -> EngineResult:
        """运行回测。

        Args:
            symbols: 股票代码列表
            start_date/end_date: YYYYMMDD
            config: 引擎配置，如 commission_rate, slippage 等
            data_map: 可选预下载的 K 线数据；未提供时从 registry loader 拉取
            quotes: 可选预提供的 Quote 快照；未提供时从 DataAggregator 拉取
        """
        config = config or {}
        config["initial_cash"] = self.initial_cash

        # 1. 获取历史 K 线
        if data_map is None:
            loader = resolve_loader("a_share")
            data_map = {}
            for sym in symbols:
                df = loader.get_history(sym, start_date, end_date)
                if df is None or df.empty:
                    continue
                df = self._normalize_ohlcv(df)
                if not df.empty:
                    data_map[sym] = df
            citations: list[SourceCitation] = [
                df.attrs["source_citation"]
                for df in data_map.values()
                if "source_citation" in df.attrs
            ]
        else:
            normalized = {sym: self._normalize_ohlcv(df) for sym, df in data_map.items()}
            data_map = {sym: df for sym, df in normalized.items() if not df.empty}
            citations = []

        if len(data_map) < 1:
            result = EngineResult(trading_blocked=True, block_reason="无可用历史数据")
            result.data_citation = make_data_gap_citation("loader", "ohlcv")
            return result

        data_citation = self._aggregate_citation(citations)

        # 2. 获取 guard 所需的 quote 快照
        if quotes is None:
            quotes = {}
            for sym in symbols:
                q = self.aggregator.get_quote(sym)
                if q is not None:
                    quotes[sym] = q

        # 3. 过滤不符合硬性规则的标的
        eligible = {
            sym: df for sym, df in data_map.items()
            if self.guard.is_eligible(sym, quotes.get(sym))
        }
        if not eligible:
            result = EngineResult(
                trading_blocked=True,
                block_reason="; ".join(self.guard.last_flags()) or "全部标的被硬性规则拦截",
            )
            result.data_citation = data_citation
            return result

        # 4. 生成目标权重
        weights = self.signal_engine(eligible)

        # 5. 运行 ChinaAEngine
        engine = ChinaAEngine(config)
        result = engine.run_backtest(eligible, weights)
        result.data_citation = data_citation

        # 6. 信号 citation：取 signal_engine 使用数据的最低 confidence
        signal_citation = self._signal_citation(weights, eligible)
        result.signal_citation = signal_citation

        # 7. 护栏：confidence < 0.6 阻止交易
        min_conf = min(
            (c.confidence for c in [data_citation, signal_citation] if c is not None),
            default=1.0,
        )
        if min_conf < 0.6:
            result.trading_blocked = True
            result.block_reason = f"综合 confidence {min_conf:.2f} < 0.6"

        return result

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """把不同来源的 K 线列名统一为 open/high/low/close/volume。"""
        rename_map = {
            "开盘": "open",
            "open": "open",
            "收盘": "close",
            "close": "close",
            "最高": "high",
            "high": "high",
            "最低": "low",
            "low": "low",
            "成交量": "volume",
            "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return pd.DataFrame()
        return df[list(required)]

    @staticmethod
    def _default_signal(data_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """默认信号：等权持有。"""
        all_dates = sorted(set().union(*(df.index for df in data_map.values())))
        weights = pd.DataFrame(0.0, index=all_dates, columns=sorted(data_map.keys()))
        for code in data_map:
            weights.loc[data_map[code].index, code] = 1.0
        scale = weights.abs().sum(axis=1).clip(lower=1.0)
        return weights.div(scale, axis=0)

    @staticmethod
    def _aggregate_citation(citations: list[SourceCitation]) -> SourceCitation:
        if not citations:
            return make_citation(provider="loader", field="ohlcv", data_type="daily_bar")
        # 保守：取最低 confidence
        min_conf = min(c.confidence for c in citations)
        representative = next(c for c in citations if c.confidence == min_conf)
        return SourceCitation(
            provider=representative.provider,
            field="ohlcv_agg",
            confidence=min_conf,
            data_freshness=representative.data_freshness,
            fetch_timestamp=representative.fetch_timestamp,
            source_tier=representative.source_tier,
            nature=representative.nature,
        )

    @staticmethod
    def _signal_citation(weights: pd.DataFrame, data_map: dict[str, pd.DataFrame]) -> SourceCitation:
        """根据 signal 使用的数据生成 citation。默认interpretation。"""
        return make_citation(
            provider="factor_registry",
            field="signal_weights",
            data_type="factor",
            nature="interpretation",
        )


def make_data_gap_citation(provider: str, field: str, reason: str = "") -> SourceCitation:
    """数据缺口 citation 快捷函数。"""
    return SourceCitation(
        provider=provider,
        field=field,
        confidence=0.0,
        data_freshness=__import__("datetime").timedelta(seconds=0),
        source_tier="T3",
        nature="data_gap",
        url_or_endpoint=reason,
    )
