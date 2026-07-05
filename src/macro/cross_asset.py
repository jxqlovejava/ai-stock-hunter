"""Cross-asset signal integration — bond yields, forex, commodities.

Tracks China 10Y bond yield, USD/CNY exchange rate, commodities (copper, oil)
and derives risk appetite signals for equity market timing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BondSignal:
    """Bond market signals."""

    yield_10y: Optional[float] = None  # 10Y government bond yield (%)
    yield_10y_change_20d: Optional[float] = None  # 20-day change (bps)
    yield_curve_slope: Optional[float] = None  # 10Y-2Y spread (bps)
    real_yield: Optional[float] = None  # 10Y - CPI
    credit_spread: Optional[float] = None  # AA corporate - government spread (bps)
    bond_signal: str = "neutral"  # "bullish_equity" / "bearish_equity" / "neutral"


@dataclass
class ForexSignal:
    """FX market signals."""

    usdcny: Optional[float] = None  # USD/CNY
    usdcny_change_20d: Optional[float] = None  # 20-day change (%)
    dxy: Optional[float] = None  # Dollar index
    cnh_cny_spread: Optional[float] = None  # CNH-CNY spread (bps)
    fx_signal: str = "neutral"  # "cny_strong" / "cny_weak" / "neutral"


@dataclass
class CommoditySignal:
    """Commodity market signals."""

    copper_price: Optional[float] = None  # LME copper or SHFE copper
    copper_change_20d: Optional[float] = None  # % change
    oil_price: Optional[float] = None  # Brent or WTI
    oil_change_20d: Optional[float] = None
    gold_price: Optional[float] = None  # Shanghai gold
    gold_change_20d: Optional[float] = None
    commodity_signal: str = "neutral"  # "reflation" / "stagflation" / "disinflation" / "neutral"


@dataclass
class CrossAssetProfile:
    """Cross-asset composite signal."""

    bond: BondSignal = field(default_factory=BondSignal)
    forex: ForexSignal = field(default_factory=ForexSignal)
    commodity: CommoditySignal = field(default_factory=CommoditySignal)
    composite_score: int = 50  # 0-100, higher = risk-on for equities
    risk_regime: str = "neutral"  # "risk_on" / "risk_off" / "neutral"
    equity_implication: str = ""  # 2-3 sentence interpretation
    updated_at: datetime = field(default_factory=datetime.now)


class CrossAssetAnalyzer:
    """Multi-asset signal aggregator for equity market timing."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> CrossAssetProfile:
        """Fetch all cross-asset signals and compute composite."""
        profile = CrossAssetProfile()

        profile.bond = self._analyze_bonds()
        profile.forex = self._analyze_forex()
        profile.commodity = self._analyze_commodities()

        profile.composite_score = self._compute_composite(profile)
        profile.risk_regime = self._classify_risk_regime(profile)
        profile.equity_implication = self._generate_implication(profile)

        return profile

    # ------------------------------------------------------------------
    # Bond analysis
    # ------------------------------------------------------------------

    def _analyze_bonds(self) -> BondSignal:
        """Analyze China bond market signals."""
        sig = BondSignal()

        try:
            import akshare as ak
            df = ak.bond_china_yield()
            if df is not None and len(df) >= 20:
                for col in df.columns:
                    col_str = str(col)
                    if "10年" in col_str or "10Y" in col_str:
                        sig.yield_10y = float(df[col].iloc[-1])
                        prev = float(df[col].iloc[-20]) if len(df) >= 20 else sig.yield_10y
                        sig.yield_10y_change_20d = round((sig.yield_10y - prev) * 100, 1)
                    if "2年" in col_str or "2Y" in col_str:
                        y2 = float(df[col].iloc[-1])
                        if sig.yield_10y:
                            sig.yield_curve_slope = round((sig.yield_10y - y2) * 100, 1)
        except Exception as e:
            logger.debug("Bond yield fetch failed: %s", e)

        # Signal interpretation
        if sig.yield_10y_change_20d is not None:
            if sig.yield_10y_change_20d < -10:
                sig.bond_signal = "bullish_equity"  # falling yields = bullish
            elif sig.yield_10y_change_20d > 15:
                sig.bond_signal = "bearish_equity"  # rising yields = bearish

        if sig.yield_curve_slope is not None and sig.yield_curve_slope < 0:
            sig.bond_signal = "bearish_equity"  # inversion = recession warning

        return sig

    # ------------------------------------------------------------------
    # Forex analysis
    # ------------------------------------------------------------------

    def _analyze_forex(self) -> ForexSignal:
        """Analyze USD/CNY and dollar index."""
        sig = ForexSignal()

        try:
            import akshare as ak
            df = ak.currency_boc_sina(symbol="美元兑人民币")
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "收盘" in str(col) or "价格" in str(col) or "close" in str(col).lower():
                        sig.usdcny = float(df[col].iloc[-1])
                        if len(df) >= 20:
                            prev = float(df[col].iloc[-20])
                            sig.usdcny_change_20d = round((sig.usdcny / prev - 1) * 100, 2)
                        break
        except Exception as e:
            logger.debug("Forex fetch failed: %s", e)

        # Signal: CNY appreciation = bullish for A-shares (foreign inflow)
        if sig.usdcny_change_20d is not None:
            if sig.usdcny_change_20d < -0.5:  # CNY strengthening
                sig.fx_signal = "cny_strong"
            elif sig.usdcny_change_20d > 0.5:  # CNY weakening
                sig.fx_signal = "cny_weak"

        return sig

    # ------------------------------------------------------------------
    # Commodity analysis
    # ------------------------------------------------------------------

    def _analyze_commodities(self) -> CommoditySignal:
        """Analyze commodity price signals (copper = Dr. Copper, gold = fear gauge)."""
        sig = CommoditySignal()

        # Copper (SHFE via AKShare)
        try:
            import akshare as ak
            df = ak.futures_zh_daily_sina(symbol="CU0")  # copper continuous
            if df is not None and len(df) >= 20:
                sig.copper_price = float(df["收盘价"].iloc[-1])
                prev = float(df["收盘价"].iloc[-20])
                sig.copper_change_20d = round((sig.copper_price / prev - 1) * 100, 2)
        except Exception as e:
            logger.debug("Copper fetch failed: %s", e)

        # Oil (Brent via AKShare)
        try:
            import akshare as ak
            df = ak.futures_zh_daily_sina(symbol="SC0")  # Shanghai crude
            if df is not None and len(df) >= 20:
                sig.oil_price = float(df["收盘价"].iloc[-1])
                prev = float(df["收盘价"].iloc[-20])
                sig.oil_change_20d = round((sig.oil_price / prev - 1) * 100, 2)
        except Exception as e:
            logger.debug("Oil fetch failed: %s", e)

        # Gold (Shanghai via AKShare)
        try:
            import akshare as ak
            df = ak.futures_zh_daily_sina(symbol="AU0")  # gold continuous
            if df is not None and len(df) >= 20:
                sig.gold_price = float(df["收盘价"].iloc[-1])
                prev = float(df["收盘价"].iloc[-20])
                sig.gold_change_20d = round((sig.gold_price / prev - 1) * 100, 2)
        except Exception as e:
            logger.debug("Gold fetch failed: %s", e)

        # Signal classification
        sig.commodity_signal = self._classify_commodity_signal(sig)

        return sig

    @staticmethod
    def _classify_commodity_signal(sig: CommoditySignal) -> str:
        """Classify commodity regime."""
        reflation = 0
        stagflation = 0
        disinflation = 0

        if sig.copper_change_20d is not None:
            if sig.copper_change_20d > 3:
                reflation += 1  # copper up = growth optimism
            elif sig.copper_change_20d < -3:
                disinflation += 1

        if sig.oil_change_20d is not None:
            if sig.oil_change_20d > 5:
                stagflation += 1  # oil spike = cost-push inflation
            elif sig.oil_change_20d < -5:
                disinflation += 1

        if sig.gold_change_20d is not None:
            if sig.gold_change_20d > 5:
                stagflation += 1  # gold spike = fear / inflation hedge

        if reflation > stagflation and reflation > disinflation:
            return "reflation"  # growth + moderate inflation = bullish
        elif stagflation > reflation and stagflation > disinflation:
            return "stagflation"  # cost-push = bearish
        elif disinflation > reflation and disinflation > stagflation:
            return "disinflation"  # falling prices = mixed
        return "neutral"

    # ------------------------------------------------------------------
    # Composite
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_composite(p: CrossAssetProfile) -> int:
        """Compute 0-100 composite cross-asset score."""
        score = 50

        # Bond contribution (±15)
        if p.bond.bond_signal == "bullish_equity":
            score += 15
        elif p.bond.bond_signal == "bearish_equity":
            score -= 15

        # Forex contribution (±15)
        if p.forex.fx_signal == "cny_strong":
            score += 15
        elif p.forex.fx_signal == "cny_weak":
            score -= 15

        # Commodity contribution (±20)
        if p.commodity.commodity_signal == "reflation":
            score += 20
        elif p.commodity.commodity_signal == "stagflation":
            score -= 20
        elif p.commodity.commodity_signal == "disinflation":
            score -= 5

        return max(0, min(100, score))

    @staticmethod
    def _classify_risk_regime(p: CrossAssetProfile) -> str:
        """Classify overall risk regime."""
        if p.composite_score >= 70:
            return "risk_on"
        elif p.composite_score <= 30:
            return "risk_off"
        return "neutral"

    @staticmethod
    def _generate_implication(p: CrossAssetProfile) -> str:
        """Generate equity market implication text."""
        parts = []

        if p.risk_regime == "risk_on":
            parts.append("跨资产信号偏向风险偏好，债券收益率下行+人民币走强，利好A股。")
            parts.append("建议: 仓位可偏高，关注成长+周期板块。")
        elif p.risk_regime == "risk_off":
            parts.append("跨资产信号偏向风险规避，债券避险+人民币走弱+商品承压，利空A股。")
            parts.append("建议: 降低仓位，转向防御板块(公用事业/消费)+现金。")
        else:
            parts.append("跨资产信号中性，各类资产无一致方向。")
            parts.append("建议: 维持中性仓位，关注资产间背离信号。")

        # Add specific warnings
        if p.bond.yield_curve_slope is not None and p.bond.yield_curve_slope < 0:
            parts.append("⚠️ 收益率曲线倒挂，历史衰退领先指标。")
        if p.commodity.commodity_signal == "stagflation":
            parts.append("⚠️ 滞胀信号：油价+金价同涨，铜价偏弱。")

        return " ".join(parts)

    def cache_clear(self) -> None:
        self._cache.clear()
