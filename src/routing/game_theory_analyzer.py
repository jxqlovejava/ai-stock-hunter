# -*- coding: utf-8 -*-
"""博弈论分析层 — 市场主导玩家 / 拥挤度 / 杠杆 / 席位 / 价格冲击。

Phase: 作为 Orchestrator 中诊断 → 裁决之间的必经阶段。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation
from src.game_theory.dominance import DominanceClassifier, DominanceProfile
from src.game_theory.fund_positioning import FundPositioningAnalyzer, FundCrowdingSignal
from src.game_theory.margin import MarginAnalyzer, MarginProfile
from src.game_theory.northbound import NorthboundAnalyzer, NorthboundProfile
from src.game_theory.players import PLAYER_PROFILES, PlayerType
from src.game_theory.price_impact import PRICE_IMPACT_PROFILES
from src.game_theory.seats import SeatActivity, SeatTracker

logger = logging.getLogger(__name__)


@dataclass
class GameTheoryProfile:
    """博弈论综合分析结果。"""

    symbol: str = ""
    name: str = ""
    score: int = 50  # 0-100, 越高越有利于多头
    dominant_player: str = ""
    market_regime: str = "mixed"
    dominance_confidence: float = 0.0
    crowding_score: int = 50
    margin_score: int = 50
    northbound_score: int = 50
    seat_signal: str = "neutral"  # bullish / bearish / neutral / unknown
    seat_net_amount: float = 0.0  # 万元
    price_impact_risks: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source_citations: list[SourceCitation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "score": self.score,
            "dominant_player": self.dominant_player,
            "market_regime": self.market_regime,
            "dominance_confidence": self.dominance_confidence,
            "crowding_score": self.crowding_score,
            "margin_score": self.margin_score,
            "northbound_score": self.northbound_score,
            "seat_signal": self.seat_signal,
            "seat_net_amount": self.seat_net_amount,
            "price_impact_risks": self.price_impact_risks,
            "risks": self.risks,
            "created_at": self.created_at.isoformat(),
        }


class GameTheoryAnalyzer:
    """多 Agent 博弈分析器。

    组合：
      - DominanceClassifier（市场主导玩家）
      - FundPositioningAnalyzer（公募拥挤度）
      - MarginAnalyzer（杠杆情绪）
      - NorthboundAnalyzer（北向资金）
      - SeatTracker（龙虎榜/游资席位）
      - PriceImpact 静态知识库
    """

    def __init__(self, data_aggregator=None):
        self._data = data_aggregator
        self._dominance = DominanceClassifier()
        self._fund = FundPositioningAnalyzer()
        self._margin = MarginAnalyzer()
        self._northbound = NorthboundAnalyzer()
        self._seats = SeatTracker()

    def analyze(
        self,
        symbol: str,
        name: str = "",
        market_cap: Optional[float] = None,
        sector: str = "",
    ) -> GameTheoryProfile:
        """对单只股票执行博弈论分析。"""
        profile = GameTheoryProfile(symbol=symbol, name=name)
        citations: list[SourceCitation] = []

        # 1. 主导玩家
        dom = self._safe(self._dominance.classify, "dominance")
        if dom:
            profile.dominant_player = dom.dominant_player or ""
            profile.market_regime = dom.market_regime or "mixed"
            profile.dominance_confidence = dom.confidence or 0.0
            citations.append(
                make_citation(
                    provider="game_theory",
                    field="dominance",
                    data_type="factor",
                    source_tier="T3",
                    nature="interpretation",
                )
            )

        # 2. 公募拥挤度
        fund = self._safe(self._fund.analyze, "fund_positioning")
        if fund:
            profile.crowding_score = max(0, min(100, fund.crowding_score))
            citations.append(
                make_citation(
                    provider="game_theory",
                    field="fund_crowding",
                    data_type="factor",
                    source_tier="T3",
                    nature="interpretation",
                )
            )

        # 3. 融资融券
        margin = self._safe(self._margin.analyze, "margin")
        if margin:
            profile.margin_score = max(0, min(100, margin.score))
            citations.append(
                make_citation(
                    provider="akshare",
                    field="margin",
                    data_type="factor",
                    source_tier="T2",
                    nature="interpretation",
                )
            )

        # 4. 北向（已在 orchestrator 有，但这里独立取一份做博弈评分）
        nb = self._safe(self._northbound.analyze, "northbound")
        if nb:
            profile.northbound_score = max(0, min(100, nb.score))
            citations.append(
                make_citation(
                    provider="tonghuashun",
                    field="northbound",
                    data_type="factor",
                    source_tier="T2",
                    nature="interpretation",
                )
            )

        # 5. 龙虎榜席位
        seat_activities = self._safe(lambda: self._seats.analyze_daily(symbol=symbol), "seats")
        if seat_activities:
            profile.seat_signal, profile.seat_net_amount, seat_risks = self._evaluate_seats(seat_activities)
            profile.risks.extend(seat_risks)
            citations.append(
                make_citation(
                    provider="eastmoney",
                    field="dragon_tiger_seats",
                    data_type="factor",
                    source_tier="T2",
                    nature="fact",
                )
            )
        else:
            profile.seat_signal = "unknown"

        # 6. 价格冲击风险（静态知识）
        if profile.dominant_player:
            impact_risks = self._price_impact_risks(profile.dominant_player, market_cap)
            profile.price_impact_risks.extend(impact_risks)
            if impact_risks:
                citations.append(
                    make_citation(
                        provider="manual",
                        field="price_impact_profile",
                        data_type="analyst_report",
                        source_tier="T2",
                        nature="interpretation",
                    )
                )

        # 7. 综合评分
        profile.score = self._composite_score(profile, market_cap)

        # 8. 生成风险项
        profile.risks.extend(self._derive_risks(profile, sector))

        profile.source_citations = citations
        return profile

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe(func, label: str):
        try:
            return func()
        except Exception as e:
            logger.debug("GameTheory %s failed: %s", label, e)
            return None

    @staticmethod
    def _evaluate_seats(activities: list[SeatActivity]) -> tuple[str, float, list[str]]:
        """评估龙虎榜席位信号。"""
        if not activities:
            return "unknown", 0.0, []

        total_buy = sum(a.buy_amount for a in activities)
        total_sell = sum(a.sell_amount for a in activities)
        net = total_buy - total_sell
        risks: list[str] = []

        if net > 0:
            signal = "bullish"
        elif net < 0:
            signal = "bearish"
            # 知名游资大量卖出
            sell_amount = sum(a.sell_amount for a in activities if a.sell_amount > 0)
            if sell_amount > 5000:
                risks.append("seat_distribution_sell: 龙虎榜席位净卖出显著")
        else:
            signal = "neutral"

        return signal, net, risks

    @staticmethod
    def _price_impact_risks(dominant_player: str, market_cap: Optional[float]) -> list[str]:
        """根据主导玩家类型匹配价格冲击风险。"""
        risks: list[str] = []
        player_type = None
        try:
            player_type = PlayerType(dominant_player)
        except ValueError:
            pass

        if player_type is None:
            return risks

        for impact in PRICE_IMPACT_PROFILES:
            if impact.player_type == player_type:
                if impact.reversal_probability >= 0.9:
                    risks.append(
                        f"{dominant_player}_high_reversal: "
                        f"{impact.player_type.value} 主导时反转概率 {impact.reversal_probability:.0%}，"
                        f"典型持续 {impact.duration}"
                    )
                break

        # 市值与玩家风格不匹配
        if player_type == PlayerType.HOT_MONEY and market_cap and market_cap > 100_000_000_000:
            risks.append("hot_money_dominant_large_cap_mismatch: 游资主导但标的市值过大")

        return risks

    @staticmethod
    def _composite_score(profile: GameTheoryProfile, market_cap: Optional[float]) -> int:
        """综合博弈评分。

        高分 = 主导玩家匹配、拥挤度低、杠杆中性、席位买入、无高风险价格冲击。
        """
        # 基础分：北向与杠杆的平均
        base = (profile.northbound_score + profile.margin_score) / 2

        # 拥挤度惩罚
        crowding_penalty = 0
        if profile.crowding_score >= 70:
            crowding_penalty = 20
        elif profile.crowding_score >= 50:
            crowding_penalty = 8

        # 席位调整
        seat_adj = {"bullish": 8, "bearish": -12, "neutral": 0, "unknown": 0}.get(profile.seat_signal, 0)

        # 主导玩家风格匹配
        player_adj = 0
        if profile.dominant_player == PlayerType.INSTITUTIONAL.value and market_cap and market_cap > 50_000_000_000:
            player_adj = 5
        elif profile.dominant_player == PlayerType.HOT_MONEY.value and market_cap and market_cap < 50_000_000_000:
            player_adj = 5
        elif profile.dominant_player == PlayerType.HOT_MONEY.value and market_cap and market_cap > 100_000_000_000:
            player_adj = -10

        score = base - crowding_penalty + seat_adj + player_adj
        return int(max(0, min(100, score)))

    @staticmethod
    def _derive_risks(profile: GameTheoryProfile, sector: str) -> list[str]:
        """生成博弈层面风险项。"""
        risks: list[str] = []

        if profile.crowding_score >= 70:
            risks.append("sector_crowded: 公募拥挤度≥70，警惕踩踏")
        elif profile.crowding_score >= 50:
            risks.append("sector_crowding_elevated: 公募拥挤度偏高")

        if profile.margin_score <= 35:
            risks.append("leverage_fear: 融资情绪偏空/去杠杆")
        elif profile.margin_score >= 75:
            risks.append("leverage_greedy: 融资情绪过热，波动可能放大")

        if profile.dominant_player == PlayerType.HOT_MONEY.value:
            risks.append("hot_money_regime: 当前为游资主导市场，注意高换手与反转")

        if sector and sector in (profile.crowded_sectors if hasattr(profile, "crowded_sectors") else []):
            risks.append(f"{sector}_crowded: 标的所在行业处于公募拥挤区")

        risks.extend(profile.price_impact_risks)
        return risks
