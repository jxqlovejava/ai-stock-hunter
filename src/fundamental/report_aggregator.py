# -*- coding: utf-8 -*-
"""多券商研报聚合 — 一致预期/评级/目标价。

使用模式:
    aggregator = ReportAggregator()
    consensus = aggregator.aggregate("600519")
    print(f"一致预期评级: {consensus.consensus_rating}, 目标均价: {consensus.target_price_mean}")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.fundamental.schema import AnalystConsensus

logger = logging.getLogger(__name__)

# 已知标的的分析师一致预期（示例数据，实际应从数据源获取）
_CONSENSUS_CACHE: dict[str, dict] = {
    "600519": {
        "n_analysts": 35, "eps_consensus": 62.5, "eps_high": 68.0, "eps_low": 58.0,
        "buy": 30, "hold": 5, "sell": 0,
        "target_mean": 2100, "target_high": 2500, "target_low": 1800,
        "rating_trend": "stable", "eps_trend": "stable",
    },
    "000858": {
        "n_analysts": 30, "eps_consensus": 30.0, "eps_high": 33.0, "eps_low": 27.0,
        "buy": 25, "hold": 5, "sell": 0,
        "target_mean": 180, "target_high": 210, "target_low": 150,
        "rating_trend": "stable", "eps_trend": "stable",
    },
    "300750": {
        "n_analysts": 40, "eps_consensus": 15.0, "eps_high": 18.0, "eps_low": 12.0,
        "buy": 32, "hold": 7, "sell": 1,
        "target_mean": 280, "target_high": 350, "target_low": 200,
        "rating_trend": "improving", "eps_trend": "upward",
    },
    "000333": {
        "n_analysts": 25, "eps_consensus": 6.5, "eps_high": 7.2, "eps_low": 5.8,
        "buy": 20, "hold": 4, "sell": 1,
        "target_mean": 75, "target_high": 85, "target_low": 60,
        "rating_trend": "stable", "eps_trend": "stable",
    },
    "600036": {
        "n_analysts": 20, "eps_consensus": 5.8, "eps_high": 6.5, "eps_low": 5.2,
        "buy": 15, "hold": 5, "sell": 0,
        "target_mean": 45, "target_high": 52, "target_low": 38,
        "rating_trend": "downgrading", "eps_trend": "downward",
    },
}


class ReportAggregator:
    """研报聚合器。

    聚合多券商一致预期:
      - EPS 一致预期
      - 评级分布（买入/持有/卖出）
      - 目标价区间
      - 趋势变化
    """

    def aggregate(self, symbol: str, name: str = "") -> AnalystConsensus:
        """聚合分析师一致预期。

        Args:
            symbol: 股票代码
            name: 公司名称

        Returns:
            AnalystConsensus
        """
        data = _CONSENSUS_CACHE.get(symbol)
        if data is None:
            return AnalystConsensus(
                symbol=symbol, name=name,
                consensus_rating="N/A",
                target_price_mean=0.0,
            )

        return AnalystConsensus(
            symbol=symbol, name=name,
            n_analysts=data["n_analysts"],
            eps_consensus=data["eps_consensus"],
            eps_high=data["eps_high"],
            eps_low=data["eps_low"],
            buy_count=data["buy"],
            hold_count=data["hold"],
            sell_count=data["sell"],
            consensus_rating=self._rating_label(data["buy"], data["hold"], data["sell"]),
            target_price_mean=data["target_mean"],
            target_price_high=data["target_high"],
            target_price_low=data["target_low"],
            rating_trend=data["rating_trend"],
            eps_revision_trend=data["eps_trend"],
        )

    @staticmethod
    def _rating_label(buy: int, hold: int, sell: int) -> str:
        total = buy + hold + sell
        if total == 0:
            return "N/A"
        buy_pct = buy / total
        sell_pct = sell / total
        if buy_pct >= 0.8:
            return "Strong Buy"
        elif buy_pct >= 0.6:
            return "Buy"
        elif sell_pct >= 0.4:
            return "Sell"
        elif sell_pct >= 0.2:
            return "Hold"
        return "Hold"
