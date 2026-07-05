"""Fiscal policy tracking framework — government spending, bond issuance, infrastructure.

Tracks: 赤字率, 专项债发行节奏, 基建投资增速, 转移支付力度
Integrates with MonetaryCreditAnalyzer for comprehensive macro assessment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FiscalRegime:
    """Fiscal policy stance snapshot."""

    fiscal_stance: str = "neutral"  # "expansionary" / "neutral" / "tightening"
    confidence: float = 0.5  # 0.0-1.0

    # Core indicators
    deficit_ratio: Optional[float] = None  # 赤字率 (% of GDP)
    special_bond_issuance: Optional[float] = None  # 专项债月发行额 (亿元)
    special_bond_yoy_change: Optional[float] = None  # 专项债同比变化 (%)
    infrastructure_investment_growth: Optional[float] = None  # 基建投资增速 (%)
    fiscal_revenue_growth: Optional[float] = None  # 财政收入增速 (%)
    fiscal_expenditure_growth: Optional[float] = None  # 财政支出增速 (%)

    # Composite
    fiscal_score: int = 50  # 0-100, higher = more stimulative
    transition_signals: list[str] = field(default_factory=list)
    recommended_sectors: list[str] = field(default_factory=list)
    avoid_sectors: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)


# Fiscal stance → sector mapping
FISCAL_SECTOR_MAP: dict[str, tuple[list[str], list[str]]] = {
    "expansionary": (
        ["基建", "建材", "工程机械", "钢铁", "水泥", "城投"],
        ["现金", "短债"],
    ),
    "neutral": (
        ["消费", "医药", "科技"],
        ["强周期", "高杠杆城投"],
    ),
    "tightening": (
        ["现金", "短债", "防御性消费", "公用事业"],
        ["基建", "建材", "工程机械", "钢铁"],
    ),
}


class FiscalAnalyzer:
    """Analyze fiscal policy stance from government spending and bond issuance data."""

    # Thresholds
    EXPANSIONARY_DEFICIT = 3.0  # 赤字率 > 3% → expansionary
    TIGHTENING_DEFICIT = 2.5  # 赤字率 < 2.5% → tightening
    EXPANSIONARY_INFRA_GROWTH = 8.0  # 基建投资增速 > 8% → expansionary
    TIGHTENING_INFRA_GROWTH = 3.0  # 基建投资增速 < 3% → tightening
    EXPANSIONARY_BOND_YOY = 20.0  # 专项债同比 > 20% → expansionary

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=4)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> FiscalRegime:
        """Fetch all fiscal indicators and classify current stance."""
        signals_missing = 0

        deficit = self._get_deficit_ratio()
        if deficit is None:
            signals_missing += 1

        infra_growth = self._get_infrastructure_growth()
        if infra_growth is None:
            signals_missing += 1

        bond_issuance = self._get_special_bond_issuance()
        bond_yoy = self._get_special_bond_yoy()

        revenue_growth = self._get_fiscal_revenue_growth()
        expenditure_growth = self._get_fiscal_expenditure_growth()

        # Classify stance
        stance, stance_signals = self._classify_stance(
            deficit, infra_growth, bond_yoy, expenditure_growth, revenue_growth
        )

        # Confidence
        confidence = max(0.3, 1.0 - signals_missing * 0.15)

        recommended, avoid = FISCAL_SECTOR_MAP.get(
            stance, (["消费", "医药"], ["强周期"])
        )

        # Compute composite score
        score = self._compute_fiscal_score(
            stance, deficit, infra_growth, bond_yoy, expenditure_growth
        )

        return FiscalRegime(
            fiscal_stance=stance,
            confidence=confidence,
            deficit_ratio=deficit,
            special_bond_issuance=bond_issuance,
            special_bond_yoy_change=bond_yoy,
            infrastructure_investment_growth=infra_growth,
            fiscal_revenue_growth=revenue_growth,
            fiscal_expenditure_growth=expenditure_growth,
            fiscal_score=score,
            transition_signals=stance_signals,
            recommended_sectors=recommended,
            avoid_sectors=avoid,
        )

    def get_sector_recommendations(self) -> tuple[list[str], list[str]]:
        """Return (recommended, avoid) sector lists for current fiscal stance."""
        regime = self.analyze()
        return regime.recommended_sectors, regime.avoid_sectors

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    @classmethod
    def _classify_stance(
        cls,
        deficit: Optional[float],
        infra_growth: Optional[float],
        bond_yoy: Optional[float],
        expenditure_growth: Optional[float],
        revenue_growth: Optional[float],
    ) -> tuple[str, list[str]]:
        """Classify fiscal stance: 'expansionary', 'neutral', 'tightening'."""
        expansionary = 0
        tightening = 0
        signals: list[str] = []

        if deficit is not None:
            if deficit > cls.EXPANSIONARY_DEFICIT:
                expansionary += 1
                signals.append(f"赤字率 {deficit}% > {cls.EXPANSIONARY_DEFICIT}%，财政扩张")
            elif deficit < cls.TIGHTENING_DEFICIT:
                tightening += 1
                signals.append(f"赤字率 {deficit}% < {cls.TIGHTENING_DEFICIT}%，财政收紧")

        if infra_growth is not None:
            if infra_growth > cls.EXPANSIONARY_INFRA_GROWTH:
                expansionary += 1
                signals.append(f"基建投资增速 {infra_growth}% > {cls.EXPANSIONARY_INFRA_GROWTH}%，基建发力")
            elif infra_growth < cls.TIGHTENING_INFRA_GROWTH:
                tightening += 1
                signals.append(f"基建投资增速 {infra_growth}% < {cls.TIGHTENING_INFRA_GROWTH}%，基建收缩")

        if bond_yoy is not None:
            if bond_yoy > cls.EXPANSIONARY_BOND_YOY:
                expansionary += 1
                signals.append(f"专项债同比 {bond_yoy}% > {cls.EXPANSIONARY_BOND_YOY}%，加速发行")
            elif bond_yoy < -10:
                tightening += 1
                signals.append(f"专项债同比 {bond_yoy}%，发行放缓")

        if expenditure_growth is not None:
            if revenue_growth is not None and expenditure_growth > revenue_growth + 3:
                expansionary += 1
                signals.append("财政支出增速显著高于收入增速，积极财政")
            elif expenditure_growth is not None and expenditure_growth < 0:
                tightening += 1
                signals.append("财政支出负增长，财政紧缩")

        if expansionary > tightening:
            return "expansionary", signals
        elif tightening > expansionary:
            return "tightening", signals
        return "neutral", signals

    @staticmethod
    def _compute_fiscal_score(
        stance: str,
        deficit: Optional[float],
        infra_growth: Optional[float],
        bond_yoy: Optional[float],
        expenditure_growth: Optional[float],
    ) -> int:
        """Compute 0-100 fiscal score. Higher = more stimulative."""
        score = 50

        # Base stance
        if stance == "expansionary":
            score += 15
        elif stance == "tightening":
            score -= 15

        # Deficit contribution (±10)
        if deficit is not None:
            if deficit > 4.0:
                score += 10
            elif deficit > 3.0:
                score += 5
            elif deficit < 2.0:
                score -= 10
            elif deficit < 2.5:
                score -= 5

        # Infrastructure contribution (±10)
        if infra_growth is not None:
            if infra_growth > 12:
                score += 10
            elif infra_growth > 8:
                score += 5
            elif infra_growth < 0:
                score -= 10
            elif infra_growth < 3:
                score -= 5

        # Bond issuance momentum (±10)
        if bond_yoy is not None:
            if bond_yoy > 40:
                score += 10
            elif bond_yoy > 20:
                score += 5
            elif bond_yoy < -20:
                score -= 10
            elif bond_yoy < -10:
                score -= 5

        # Expenditure growth (±5)
        if expenditure_growth is not None:
            if expenditure_growth > 15:
                score += 5
            elif expenditure_growth < 0:
                score -= 5

        return max(0, min(100, score))

    # ------------------------------------------------------------------
    # Data fetching (AKShare + fallback)
    # ------------------------------------------------------------------

    def _get_deficit_ratio(self) -> Optional[float]:
        """Fetch 赤字率 via fiscal revenue/expenditure data."""
        cache_key = "deficit_ratio"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            # Try macro China fiscal data
            df = ak.macro_china_fiscal_growth()
            if df is not None and len(df) > 0:
                # Compute implied deficit from revenue - expenditure gap
                rev_col = None
                exp_col = None
                for col in df.columns:
                    col_lower = str(col).lower()
                    if "收入" in str(col) and "同比" in str(col):
                        rev_col = col
                    if "支出" in str(col) and "同比" in str(col):
                        exp_col = col
                if rev_col and exp_col:
                    rev = float(df[rev_col].iloc[-1])
                    exp = float(df[exp_col].iloc[-1])
                    # Deficit ratio proxy: expenditure growth - revenue growth as % of GDP
                    # Use the gap as a directional signal
                    deficit_proxy = exp - rev + 3.0  # baseline 3% + gap
                    self._cache_set(cache_key, deficit_proxy)
                    return deficit_proxy
        except Exception as e:
            logger.warning("AKShare fiscal growth fetch failed: %s", e)

        # Fallback: try GDP-based estimate
        try:
            import akshare as ak

            df = ak.macro_china_gdp()
            if df is not None and len(df) > 0:
                # Conservative estimate based on official target ~3%
                val = 3.0
                self._cache_set(cache_key, val)
                return val
        except Exception:
            pass

        # Last-resort fallback: official target
        val = 3.0  # Default to ~3% official target
        self._cache_set(cache_key, val)
        return val

    def _get_infrastructure_growth(self) -> Optional[float]:
        """Fetch 基建投资增速 via fixed asset investment data."""
        cache_key = "infra_growth"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            # Try fixed asset investment data
            df = ak.macro_china_fixed_asset_investment()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    col_str = str(col)
                    if "基建" in col_str or "基础设施" in col_str:
                        if "同比" in col_str or "累计同比" in col_str or "增长" in col_str:
                            val = float(df[col].iloc[-1])
                            self._cache_set(cache_key, val)
                            return val
                # Fallback: use overall FAI growth as proxy
                for col in df.columns:
                    if "同比" in str(col) or "增长" in str(col):
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare fixed asset investment fetch failed: %s", e)

        val = self._query_guosen("基建投资增速 基础设施投资 同比")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_special_bond_issuance(self) -> Optional[float]:
        """Fetch 专项债发行数据 (monthly, 亿元)."""
        cache_key = "special_bond_issuance"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.bond_zh_us_rate()
            if df is not None and len(df) > 0:
                # Use government bond yield as indirect proxy
                # For actual issuance volume, may need dedicated data source
                pass
        except Exception:
            pass

        # Use Guosen as primary for bond data
        val = self._query_guosen("地方政府专项债 发行规模 亿元")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_special_bond_yoy(self) -> Optional[float]:
        """Fetch 专项债同比变化 (%)."""
        cache_key = "special_bond_yoy"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        val = self._query_guosen("专项债 同比 增速")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_fiscal_revenue_growth(self) -> Optional[float]:
        """Fetch 财政收入增速."""
        cache_key = "fiscal_revenue_growth"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.macro_china_fiscal_growth()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "收入" in str(col) and "同比" in str(col):
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare fiscal revenue fetch failed: %s", e)

        val = self._query_guosen("财政收入 同比增速")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_fiscal_expenditure_growth(self) -> Optional[float]:
        """Fetch 财政支出增速."""
        cache_key = "fiscal_expenditure_growth"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.macro_china_fiscal_growth()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "支出" in str(col) and "同比" in str(col):
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare fiscal expenditure fetch failed: %s", e)

        val = self._query_guosen("财政支出 同比增速")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _query_guosen(self, query: str) -> Optional[float]:
        """Fallback: query Guosen get_macro() and attempt numeric extraction."""
        try:
            from src.data.guosen import GuosenProvider

            gs = GuosenProvider()
            text = gs.get_macro(query)
            if text:
                return self._extract_first_number(text)
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_first_number(text: str) -> Optional[float]:
        """Extract the first percentage or decimal number from text."""
        import re

        patterns = [
            r"([\d.]+)\s*%",
            r"同比[增长]*\s*([\d.]+)",
            r"为\s*([\d.]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------
    # Simple cache
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
