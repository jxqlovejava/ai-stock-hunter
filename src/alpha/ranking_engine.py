# -*- coding: utf-8 -*-
"""全市场 Alpha 排名引擎 — 批量计算因子暴露 → 综合排名 → Top N。

扫描全市场股票，对每只计算多因子暴露值，用 FactorSynthesizer
合成为综合评分，输出排名列表。

使用模式:
    engine = RankingEngine()
    result = engine.rank_all(["pb_factor", "roe_factor", "momentum_20d"], limit=50)
    for stock in result.stocks:
        print(f"{stock.rank}. {stock.symbol} {stock.name}: {stock.composite_score:.1f}")
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.alpha.factor_synthesizer import FactorSynthesizer
from src.alpha.schema import (
    AlphaSynthesis,
    RankedStock,
    RankingResult,
    SynthesisMethod,
)

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_MIN_MARKET_CAP = 2e9    # 最低市值 20 亿
DEFAULT_MAX_STOCKS = 5000
DEFAULT_RANK_LIMIT = 50


class RankingEngine:
    """全市场 Alpha 排名引擎。

    流程:
      1. 获取全市场股票列表（aggregator.scan_all_stocks）
      2. 对每只股票获取 spot 数据（行情+基本面）
      3. 批量计算因子暴露
      4. FactorSynthesizer 合成综合评分
      5. 排名 → Top N
    """

    def __init__(
        self,
        registry=None,  # lazy: Registry or None
        min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
        max_stocks: int = DEFAULT_MAX_STOCKS,
    ):
        self._registry = registry
        self._synthesizer = FactorSynthesizer(registry=registry)
        self._aggregator = None  # lazy: DataAggregator
        self._min_market_cap = min_market_cap
        self._max_stocks = max_stocks

    def _get_aggregator(self):
        """懒加载 DataAggregator，避免循环导入。"""
        if self._aggregator is None:
            from src.data.aggregator import DataAggregator
            self._aggregator = DataAggregator()
        return self._aggregator

    def _get_registry(self):
        """懒加载 registry，避免循环导入。"""
        if self._registry is None:
            from src.factors.registry import get_default_registry
            self._registry = get_default_registry()
            self._synthesizer._registry = self._registry
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank_all(
        self,
        alpha_ids: list[str],
        limit: int = DEFAULT_RANK_LIMIT,
        method: SynthesisMethod | str = SynthesisMethod.ICIR_WEIGHT,
        ic_stats: Optional[dict[str, dict[str, float]]] = None,
        spot_data: Optional[pd.DataFrame] = None,
    ) -> RankingResult:
        """全市场 Alpha 排名。

        Args:
            alpha_ids: 参与排名的因子列表
            limit: 返回 Top N
            method: 合成方法
            ic_stats: 因子 IC 统计（用于权重计算）
            spot_data: 预提供的 spot DataFrame；None 则从 aggregator 获取

        Returns:
            RankingResult
        """
        # 1. 合成配置
        synthesis = self._synthesizer.synthesize(
            alpha_ids, method=method, ic_stats=ic_stats
        )

        # 2. 获取股票数据
        if spot_data is None:
            spot_data = self._fetch_spot_data()
        if spot_data is None or len(spot_data) == 0:
            return RankingResult(
                synthesis=synthesis,
                data_gaps=["[DATA_GAP] 无可用股票数据"],
            )

        total_scanned = len(spot_data)

        # 3. 过滤（市值等）
        spot_data = self._prefilter(spot_data)
        if len(spot_data) == 0:
            return RankingResult(
                synthesis=synthesis,
                total_scanned=total_scanned,
                data_gaps=["全部股票被预过滤器排除"],
            )

        # 4. 计算复合评分
        scored = self._synthesizer.compute_composite_score(
            spot_data, alpha_ids, weights=synthesis.weights
        )

        # 5. 排名
        stocks = self._rank_stocks(scored, limit)

        return RankingResult(
            synthesis=synthesis,
            stocks=stocks,
            total_scanned=total_scanned,
            total_passed=len(stocks),
        )

    def rank_by_synthesis(
        self,
        synthesis: AlphaSynthesis,
        limit: int = DEFAULT_RANK_LIMIT,
        spot_data: Optional[pd.DataFrame] = None,
    ) -> RankingResult:
        """使用已有的合成配置运行排名。"""
        return self.rank_all(
            alpha_ids=synthesis.alpha_ids,
            limit=limit,
            method=synthesis.method,
            spot_data=spot_data,
        )

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_spot_data(self) -> Optional[pd.DataFrame]:
        """从 aggregator 获取全市场 spot 数据。"""
        try:
            stocks = self._get_aggregator().scan_all_stocks()
        except Exception as exc:
            logger.warning("scan_all_stocks failed: %s", exc)
            return None

        if not stocks:
            return None

        rows = []
        count = 0
        for stock in stocks:
            if count >= self._max_stocks:
                break
            try:
                symbol = stock.symbol if hasattr(stock, 'symbol') else str(stock)
                name = stock.name if hasattr(stock, 'name') else ""
                quote = self._get_aggregator().get_quote(symbol)
                if quote is None:
                    continue

                row = {"code": symbol, "name": name}
                if hasattr(quote, 'close') and quote.close:
                    row["close"] = float(quote.close)
                if hasattr(quote, 'pb') and quote.pb:
                    row["pb"] = float(quote.pb)
                if hasattr(quote, 'pe') and quote.pe:
                    row["pe"] = float(quote.pe)
                if hasattr(quote, 'market_cap') and quote.market_cap:
                    row["market_cap"] = float(quote.market_cap)
                if hasattr(quote, 'volume') and quote.volume:
                    row["volume"] = float(quote.volume)
                if hasattr(quote, 'change_pct') and quote.change_pct is not None:
                    row["change_pct"] = float(quote.change_pct)

                rows.append(row)
                count += 1
            except Exception as exc:
                logger.debug("fetch %s: %s", getattr(stock, 'symbol', stock), exc)
                continue

        if not rows:
            return None
        return pd.DataFrame(rows)

    def _prefilter(self, df: pd.DataFrame) -> pd.DataFrame:
        """预过滤：市值、ST、流动性。"""
        result = df.copy()

        # 市值过滤
        if "market_cap" in result.columns:
            result = result[result["market_cap"] >= self._min_market_cap]

        # ST 过滤
        if "name" in result.columns:
            result = result[~result["name"].str.contains("ST|\\*ST", na=False, regex=True)]

        # 去除 NaN close
        if "close" in result.columns:
            result = result[result["close"].notna() & (result["close"] > 0)]

        return result

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_stocks(self, df: pd.DataFrame, limit: int) -> list[RankedStock]:
        """从评分 DataFrame 生成排名列表。"""
        if "composite_score" not in df.columns:
            return []

        ranked = df.sort_values("composite_score", ascending=False).head(limit)

        stocks = []
        for rank, (_, row) in enumerate(ranked.iterrows(), 1):
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            score = float(row.get("composite_score", 50.0))
            mcap = float(row.get("market_cap", 0.0))

            # 提取各因子得分
            factor_scores = {}
            for col in row.index:
                if col not in ("code", "name", "composite_score", "market_cap",
                               "close", "pb", "pe", "volume", "change_pct"):
                    try:
                        factor_scores[col] = float(row[col])
                    except (ValueError, TypeError):
                        pass

            stocks.append(RankedStock(
                symbol=code,
                name=name,
                rank=rank,
                composite_score=score,
                factor_scores=factor_scores,
                market_cap=mcap,
            ))

        return stocks
