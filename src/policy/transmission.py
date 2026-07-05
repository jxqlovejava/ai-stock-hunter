"""Policy-to-sector transmission chain quantification.

Quantifies the strength and time-lag of policy keyword → sector impact.
Replaces the flat 1.0 strength in PolicyAnalysis.affected_sectors with
calibrated scores based on historical sector response patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TransmissionLink:
    """A single keyword-to-sector transmission edge."""

    keyword: str
    sector: str
    impact_strength: float  # 0.0-1.0, calibrated
    impact_direction: str = "positive"  # "positive" / "negative"
    time_lag_days: int = 5  # policy announcement → sector response (days)
    confidence: float = 0.6  # confidence in this link
    last_calibrated: datetime = field(default_factory=datetime.now)


@dataclass
class SectorImpact:
    """Aggregated sector impact from policy analysis."""

    sector: str
    net_strength: float  # -1.0 to 1.0 (positive = bullish, negative = bearish)
    positive_keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    avg_time_lag: float = 5.0  # weighted average time lag
    confidence: float = 0.5


class SectorTransmissionAnalyzer:
    """Quantified keyword → sector impact matrix.

    Maps policy keywords to sector impacts with calibrated strength scores,
    replacing the flat 1.0 defaults in PolicyAnalysis.affected_sectors.
    """

    # Pre-calibrated sector → keyword mapping with impact strength and time lag.
    # Strength: 0.9 = certain/historical pattern, 0.5 = moderate, 0.2 = weak
    # Time lag: days from policy announcement to sector price response
    SECTOR_KEYWORD_MAP: dict[str, list[tuple[str, float, int, str]]] = {
        "基建": [
            ("基建投资", 0.9, 5, "positive"),
            ("专项债", 0.8, 10, "positive"),
            ("重大项目", 0.7, 15, "positive"),
            ("新型城镇化", 0.6, 20, "positive"),
            ("PPP", 0.5, 15, "positive"),
            ("地方债化解", 0.4, 30, "positive"),
        ],
        "新能源": [
            ("碳中和", 0.6, 20, "positive"),
            ("光伏补贴", 0.8, 3, "positive"),
            ("风电", 0.7, 5, "positive"),
            ("储能", 0.7, 10, "positive"),
            ("新能源汽车", 0.8, 3, "positive"),
            ("碳交易", 0.5, 15, "positive"),
            ("补贴退坡", 0.7, 3, "negative"),
        ],
        "券商": [
            ("注册制", 0.7, 10, "positive"),
            ("资本市场改革", 0.6, 15, "positive"),
            ("交易印花税", 0.9, 1, "positive"),
            ("T+0", 0.5, 5, "positive"),
            ("科创板", 0.6, 10, "positive"),
            ("北交所", 0.5, 10, "positive"),
            ("减持新规", 0.4, 5, "negative"),
        ],
        "地产": [
            ("房住不炒", 0.5, 3, "negative"),
            ("因城施策", 0.6, 10, "positive"),
            ("保交楼", 0.7, 5, "positive"),
            ("限购放松", 0.8, 3, "positive"),
            ("首付比例", 0.8, 3, "positive"),
            ("房贷利率", 0.9, 2, "positive"),
            ("房地产税", 0.7, 15, "negative"),
            ("三道红线", 0.8, 5, "negative"),
            ("白名单", 0.7, 5, "positive"),
        ],
        "消费": [
            ("促消费", 0.7, 5, "positive"),
            ("以旧换新", 0.8, 3, "positive"),
            ("消费券", 0.8, 3, "positive"),
            ("内需", 0.6, 10, "positive"),
            ("消费税", 0.7, 15, "negative"),
        ],
        "科技": [
            ("科技自立", 0.6, 10, "positive"),
            ("人工智能", 0.5, 15, "positive"),
            ("半导体", 0.7, 5, "positive"),
            ("国产替代", 0.7, 10, "positive"),
            ("信创", 0.6, 10, "positive"),
            ("数字经济", 0.5, 15, "positive"),
            ("反垄断", 0.6, 5, "negative"),
        ],
        "军工": [
            ("国防预算", 0.8, 3, "positive"),
            ("军民融合", 0.5, 20, "positive"),
            ("装备采购", 0.7, 10, "positive"),
        ],
        "银行": [
            ("降准", 0.7, 2, "positive"),
            ("LPR下调", 0.8, 2, "positive"),
            ("存款利率", 0.6, 3, "positive"),
            ("资本充足率", 0.5, 15, "positive"),
            ("加息", 0.9, 2, "negative"),
            ("LPR上调", 0.8, 2, "negative"),
            ("金融监管", 0.5, 10, "negative"),
        ],
        "医药": [
            ("集采", 0.8, 5, "negative"),
            ("创新药", 0.7, 10, "positive"),
            ("医保目录", 0.6, 10, "positive"),
            ("医疗新基建", 0.6, 10, "positive"),
            ("DRG支付", 0.5, 20, "negative"),
        ],
        "农业": [
            ("种业振兴", 0.7, 10, "positive"),
            ("粮食安全", 0.6, 10, "positive"),
            ("乡村振兴", 0.5, 20, "positive"),
            ("生猪调控", 0.7, 5, "positive"),
        ],
        "教育": [
            ("双减", 0.8, 3, "negative"),
            ("职业教育", 0.6, 15, "positive"),
        ],
    }

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_policy(
        self, keywords: list[str], affected_sectors_raw: list[tuple[str, float]]
    ) -> dict[str, SectorImpact]:
        """Compute calibrated sector impacts from policy keywords.

        Args:
            keywords: Extracted policy keywords.
            affected_sectors_raw: List of (sector_name, strength) from PolicyAnalysis.

        Returns:
            Dict of sector_name → SectorImpact with calibrated strengths.
        """
        impacts: dict[str, SectorImpact] = {}

        # Process through keyword matrix
        all_keywords_lower = {k.lower() for k in keywords}

        for sector, links in self.SECTOR_KEYWORD_MAP.items():
            pos_kw: list[str] = []
            neg_kw: list[str] = []
            total_strength = 0.0
            total_weight = 0.0
            total_lag = 0.0

            for kw, strength, lag, direction in links:
                if kw.lower() in all_keywords_lower:
                    if direction == "positive":
                        pos_kw.append(kw)
                        total_strength += strength
                    else:
                        neg_kw.append(kw)
                        total_strength -= strength * 0.8  # negative slightly discounted
                    total_weight += strength
                    total_lag += lag * strength

            if total_weight > 0:
                net = total_strength / total_weight  # normalize to [-1, 1]
                avg_lag = total_lag / total_weight
                conf = min(0.9, 0.4 + total_weight * 0.3)

                # Clamp
                net = max(-1.0, min(1.0, net))

                impacts[sector] = SectorImpact(
                    sector=sector,
                    net_strength=round(net, 3),
                    positive_keywords=pos_kw,
                    negative_keywords=neg_kw,
                    avg_time_lag=round(avg_lag, 1),
                    confidence=round(conf, 2),
                )

        # Merge in raw affected_sectors for any sectors not covered by matrix
        for sector_name, raw_strength in affected_sectors_raw:
            if sector_name not in impacts and raw_strength > 0:
                impacts[sector_name] = SectorImpact(
                    sector=sector_name,
                    net_strength=min(1.0, raw_strength),
                    confidence=0.3,  # low confidence for unmatched sectors
                )

        return impacts

    def get_transmission(self, keyword: str) -> list[TransmissionLink]:
        """Get all sector transmission links for a keyword."""
        results: list[TransmissionLink] = []
        kw_lower = keyword.lower()

        for sector, links in self.SECTOR_KEYWORD_MAP.items():
            for kw, strength, lag, direction in links:
                if kw.lower() == kw_lower:
                    results.append(
                        TransmissionLink(
                            keyword=kw,
                            sector=sector,
                            impact_strength=strength,
                            impact_direction=direction,
                            time_lag_days=lag,
                        )
                    )

        return results

    def calibrate_sectors(
        self, policy_analysis_result: dict
    ) -> list[tuple[str, float]]:
        """Replace flat 1.0 strengths in PolicyAnalysis.affected_sectors.

        Takes a policy analysis result dict with 'keywords' and 'affected_sectors',
        returns calibrated list of (sector, strength) tuples.
        """
        keywords = policy_analysis_result.get("keywords", [])
        raw_sectors = policy_analysis_result.get("affected_sectors", [])

        impacts = self.analyze_policy(keywords, raw_sectors)

        calibrated: list[tuple[str, float]] = []
        for impact in impacts.values():
            # Convert net_strength [-1,1] to absolute impact [0, 1]
            strength = abs(impact.net_strength)
            if strength > 0.1:  # filter noise
                calibrated.append((impact.sector, round(strength, 3)))

        # Sort by strength descending
        calibrated.sort(key=lambda x: x[1], reverse=True)
        return calibrated

    def get_sector_score_modifier(
        self, sector: str, impacts: dict[str, SectorImpact]
    ) -> float:
        """Get L1 score modifier for a sector based on policy transmission.

        Returns a modifier in [-15, +15] for sector-level macro score adjustment.
        """
        impact = impacts.get(sector)
        if impact is None:
            return 0.0

        modifier = impact.net_strength * 15.0 * impact.confidence
        return round(modifier, 1)

    def cache_clear(self) -> None:
        self._cache.clear()
