"""Market dominant player classifier — identifies which player type currently has pricing power.

Based on: volatility regime, turnover rate, small-cap vs large-cap strength,
ETF volume anomalies, northbound flow patterns, and hot-money seat activity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DominanceProfile:
    dominant_player: Optional[str] = None  # PlayerType enum value name
    confidence: float = 0.0  # 0.0-1.0
    evidence: list[str] = field(default_factory=list)
    secondary_players: list[str] = field(default_factory=list)
    market_regime: str = "mixed"  # "hot_money_market" / "institutional_market" / "quant_market" / "national_team_active" / "northbound_driven" / "mixed"
    turnover_rate: Optional[float] = None  # 全市场换手率%
    small_cap_strength: Optional[float] = None  # 小盘 vs 大盘相对强度
    volatility_regime: str = "medium"  # "high" / "medium" / "low"
    recommended_strategy: str = ""
    updated_at: datetime = field(default_factory=datetime.now)


class DominanceClassifier:
    """Classify which player type currently dominates market pricing."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=30)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self) -> DominanceProfile:
        """Run all classifiers and return dominance assessment."""
        profile = DominanceProfile()

        # Gather evidence
        evidence_all: dict[str, tuple[float, list[str]]] = {}

        # 1. Hot money evidence
        hm_score, hm_evidence = self._assess_hot_money()
        evidence_all["HOT_MONEY"] = (hm_score, hm_evidence)

        # 2. Institutional evidence
        inst_score, inst_evidence = self._assess_institutional()
        evidence_all["INSTITUTIONAL"] = (inst_score, inst_evidence)

        # 3. Quant evidence
        quant_score, quant_evidence = self._assess_quant()
        evidence_all["QUANT"] = (quant_score, quant_evidence)

        # 4. National team evidence
        nt_score, nt_evidence = self._assess_national_team()
        evidence_all["NATIONAL_TEAM"] = (nt_score, nt_evidence)

        # 5. Northbound evidence
        nb_score, nb_evidence = self._assess_northbound()
        evidence_all["NORTHBOUND"] = (nb_score, nb_evidence)

        # 6. Margin trading evidence
        margin_score, margin_evidence = self._assess_margin()
        if margin_evidence:
            evidence_all["HOT_MONEY"] = (
                evidence_all["HOT_MONEY"][0] + margin_score * 0.3,
                evidence_all["HOT_MONEY"][1] + margin_evidence,
            )

        # Pick dominant player
        if not evidence_all:
            profile.dominant_player = None
            profile.confidence = 0.0
            return profile

        best_player = max(evidence_all, key=lambda k: evidence_all[k][0])
        best_score = evidence_all[best_player][0]

        profile.dominant_player = best_player
        profile.confidence = min(best_score / 100.0, 0.95)
        profile.evidence = evidence_all[best_player][1]

        # Secondary players
        profile.secondary_players = [
            p for p, (score, _) in evidence_all.items()
            if p != best_player and score > best_score * 0.6
        ]

        # Map to market regime
        profile.market_regime = self._to_market_regime(best_player)

        # Get market stats
        stats = self._get_market_stats()
        if stats:
            profile.turnover_rate = stats.get("turnover_rate")
            profile.small_cap_strength = stats.get("small_cap_strength")
            profile.volatility_regime = stats.get("volatility_regime", "medium")

        # Strategy recommendation
        profile.recommended_strategy = self._recommend_strategy(profile)

        return profile

    # ------------------------------------------------------------------
    # Player-specific assessments
    # ------------------------------------------------------------------

    def _assess_hot_money(self) -> tuple[float, list[str]]:
        """Assess hot-money dominance via small-cap strength, limit-ups, seat activity."""
        score = 0.0
        evidence: list[str] = []

        stats = self._get_market_stats()
        if stats:
            # Small-cap significantly outperforming large-cap
            small_strength = stats.get("small_cap_strength", 1.0)
            if small_strength > 1.2:
                score += 30
                evidence.append(f"小盘相对强度 {small_strength:.2f} (>1.2)")
            elif small_strength > 1.05:
                score += 15

            turnover = stats.get("turnover_rate", 0)
            if turnover > 5.0:
                score += 25
                evidence.append(f"换手率 {turnover:.1f}% (>5%，高投机)")
            elif turnover > 3.0:
                score += 10

            if stats.get("limit_up_count", 0) > 50:
                score += 25
                evidence.append(f"涨停家数 {stats.get('limit_up_count')} (>50)")

        # Seat activity check
        try:
            from src.game_theory.seats import SeatTracker
            tracker = SeatTracker()
            summary = tracker.get_market_seat_summary()
            if summary.get("hot_money_active"):
                score += 20
                evidence.append(f"游资席位活跃: {summary.get('active_count')} 席")
        except Exception as e:
            logger.debug("Seat tracker unavailable: %s", e)

        return min(score, 100.0), evidence

    def _assess_institutional(self) -> tuple[float, list[str]]:
        """Assess institutional dominance via large-cap strength, sector rotation."""
        score = 0.0
        evidence: list[str] = []

        stats = self._get_market_stats()
        if stats:
            # Large-cap outperforming
            small_strength = stats.get("small_cap_strength", 1.0)
            if small_strength < 0.9:
                score += 25
                evidence.append(f"大盘跑赢小盘 (小盘/大盘={small_strength:.2f})")

            turnover = stats.get("turnover_rate", 0)
            if turnover < 2.5:
                score += 15
                evidence.append(f"低换手 {turnover:.1f}%，机构市特征")
            elif turnover < 4.0:
                score += 5

            # Low volatility = institutional
            vol_regime = stats.get("volatility_regime", "medium")
            if vol_regime == "low":
                score += 20
                evidence.append("低波动率环境")
            elif vol_regime == "high":
                score -= 10

        return min(score, 100.0), evidence

    def _assess_quant(self) -> tuple[float, list[str]]:
        """Assess quant dominance via reversal patterns, low net exposure clues."""
        score = 0.0
        evidence: list[str] = []

        stats = self._get_market_stats()
        if stats:
            # Quants thrive in mid-high volatility and high turnover
            vol_regime = stats.get("volatility_regime", "medium")
            turnover = stats.get("turnover_rate", 0)

            if vol_regime == "medium" and 2.5 <= turnover <= 5.0:
                score += 20
                evidence.append("中等波动+适中换手率，量化活跃")
            elif vol_regime == "high" and turnover > 4.0:
                score += 25
                evidence.append("高波动+高换手，量化高频套利")

        # Quant is hard to detect reliably with daily data; keep confidence moderate
        return min(score, 100.0), evidence

    def _assess_national_team(self) -> tuple[float, list[str]]:
        """Assess national team activity via ETF volume anomalies."""
        score = 0.0
        evidence: list[str] = []

        try:
            import akshare as ak
            # Check CSI 300 ETF (510300) volume
            df = ak.stock_zh_a_hist(symbol="510300", period="daily", start_date="2026-01-01", end_date="")
            if df is not None and len(df) >= 20:
                import pandas as pd
                volumes = pd.to_numeric(df["成交量"], errors="coerce")
                if len(volumes) >= 20:
                    avg_vol = volumes.iloc[-20:].mean()
                    recent_vol = volumes.iloc[-1]
                    if avg_vol > 0 and recent_vol > avg_vol * 3:
                        score += 40
                        evidence.append(f"沪深300ETF量暴增 {recent_vol/avg_vol:.1f}x")
                    elif recent_vol > avg_vol * 2:
                        score += 20
                        evidence.append(f"沪深300ETF量放大 {recent_vol/avg_vol:.1f}x")
        except Exception as e:
            logger.debug("National team assessment failed: %s", e)

        # Also check if defensive sectors are strong (national team preference)
        stats = self._get_market_stats()
        if stats and stats.get("volatility_regime") == "high":
            score += 10  # High vol is when NT typically intervenes

        return min(score, 100.0), evidence

    def _assess_northbound(self) -> tuple[float, list[str]]:
        """Assess northbound dominance via sustained flow patterns."""
        score = 0.0
        evidence: list[str] = []

        try:
            from src.game_theory.northbound import NorthboundAnalyzer
            nb = NorthboundAnalyzer()
            profile = nb.analyze()

            if profile.is_inflow_sustained and profile.total_net_flow > 50:
                score += 35
                evidence.append(f"北向持续流入 {profile.total_net_flow:.0f}亿")
            elif profile.total_net_flow > 50:
                score += 20
                evidence.append(f"北向单日大幅流入 {profile.total_net_flow:.0f}亿")

            if profile.momentum_signal == "accelerating":
                score += 15
                evidence.append("北向流入加速")
            elif profile.momentum_signal == "decelerating" and profile.total_net_flow < 0:
                score -= 10

        except Exception as e:
            logger.debug("Northbound assessment failed: %s", e)

        return min(score, 100.0), evidence

    def _assess_margin(self) -> tuple[float, list[str]]:
        """Assess margin trading sentiment as supplementary hot-money / risk signal."""
        score = 0.0
        evidence: list[str] = []

        try:
            from src.game_theory.margin import MarginAnalyzer

            ma = MarginAnalyzer()
            profile = ma.analyze()

            # High margin buy ratio → hot money active
            if profile.margin_buy_ratio is not None:
                if profile.margin_buy_ratio > 11:
                    score += 30
                    evidence.append(f"融资买入占比 {profile.margin_buy_ratio:.1f}% (>11%，游资活跃)")
                elif profile.margin_buy_ratio > 9:
                    score += 15
                    evidence.append(f"融资买入占比 {profile.margin_buy_ratio:.1f}% (>9%)")

            # Rising balance trend → bullish leverage sentiment
            if profile.margin_balance_trend == "rising":
                score += 10
                evidence.append("融资余额上升趋势")
            elif profile.margin_balance_trend == "falling":
                score -= 10
                evidence.append("融资余额下降趋势")

            # Greedy leverage → hot money signal
            if profile.leverage_sentiment == "greedy":
                score += 15
                evidence.append("杠杆情绪贪婪")

            # High short pressure → institutional hedging / bearish
            if profile.short_pressure == "high":
                score -= 10
                evidence.append("融券压力高")

        except Exception as e:
            logger.debug("Margin assessment failed: %s", e)

        return min(score, 100.0), evidence

    # ------------------------------------------------------------------
    # Market statistics
    # ------------------------------------------------------------------

    def _get_market_stats(self) -> dict:
        """Fetch current market-wide statistics."""
        cache_key = "market_stats"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        stats: dict = {
            "turnover_rate": None,
            "small_cap_strength": None,
            "volatility_regime": "medium",
            "limit_up_count": 0,
        }

        try:
            import akshare as ak
            import pandas as pd

            # Full market snapshot
            df = ak.stock_zh_a_spot()
            if df is not None and len(df) > 0:
                # Turnover rate (全市场换手率)
                if "换手率" in df.columns:
                    turnover_series = pd.to_numeric(df["换手率"], errors="coerce").dropna()
                    if len(turnover_series) > 0:
                        stats["turnover_rate"] = float(turnover_series.median())

                # Limit up count
                if "涨跌幅" in df.columns:
                    pct_series = pd.to_numeric(df["涨跌幅"], errors="coerce")
                    stats["limit_up_count"] = int((pct_series > 9.5).sum())

                # Small-cap vs large-cap relative strength
                if "总市值" in df.columns:
                    mcap = pd.to_numeric(df["总市值"], errors="coerce")
                    pct_chg = pd.to_numeric(df["涨跌幅"], errors="coerce")
                    valid = mcap.notna() & pct_chg.notna()
                    if valid.sum() > 100:
                        median_mcap = mcap[valid].median()
                        small_cap_ret = pct_chg[valid & (mcap < median_mcap * 0.3)].mean()
                        large_cap_ret = pct_chg[valid & (mcap > median_mcap * 3)].mean()
                        if pd.notna(small_cap_ret) and pd.notna(large_cap_ret) and large_cap_ret != 0:
                            stats["small_cap_strength"] = float(
                                (100 + small_cap_ret) / (100 + large_cap_ret)
                            )

                # Volatility regime
                if "涨跌幅" in df.columns:
                    pct_series = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
                    vol = pct_series.std()
                    if vol > 4.0:
                        stats["volatility_regime"] = "high"
                    elif vol < 1.5:
                        stats["volatility_regime"] = "low"
        except Exception as e:
            logger.warning("Market stats fetch failed: %s", e)

        self._cache_set(cache_key, stats)
        return stats

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _to_market_regime(dominant_player: Optional[str]) -> str:
        mapping = {
            "HOT_MONEY": "hot_money_market",
            "INSTITUTIONAL": "institutional_market",
            "QUANT": "quant_market",
            "NATIONAL_TEAM": "national_team_active",
            "NORTHBOUND": "northbound_driven",
        }
        return mapping.get(dominant_player or "", "mixed")

    @staticmethod
    def _recommend_strategy(profile: DominanceProfile) -> str:
        strategies = {
            "HOT_MONEY": "跟随游资：关注连板股、龙虎榜知名席位，快进快出，严格止损",
            "INSTITUTIONAL": "跟随机构：配置重仓股、关注季报调仓方向，中线持有",
            "QUANT": "谨慎追涨：量化主导下趋势策略失效概率高，降低仓位或转向套利",
            "NATIONAL_TEAM": "关注托底：蓝筹ETF和金融股有机会，但警惕国家队退出后的二次探底",
            "NORTHBOUND": "关注外资偏好：消费、金融、新能源龙头，北向流入持续性为关键指标",
        }
        return strategies.get(profile.dominant_player or "", "保持观望，等待市场主导力量明确")

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[object]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._cache_ttl:
            return val
        del self._cache[key]
        return None

    def _cache_set(self, key: str, val: object) -> None:
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self) -> None:
        self._cache.clear()
