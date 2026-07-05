"""Financial statement analysis — DuPont ROE, earnings quality, growth, health scores.

Covers:
  - 财务报表拉取: AKShare profit/balance sheet/cashflow
  - ROE 杜邦拆解: NetMargin × AssetTurnover × EquityMultiplier
  - 盈利质量评分: OCF/NI ratio, receivables/revenue ratio, inventory turnover
  - 成长性指标: Revenue/Earnings/Deduction-adjusted growth YoY
  - 财务健康度评分: Z-score, interest coverage, current ratio, debt ratio
  - 财报事件日历: Earnings schedule, pre-announcement dates
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class DuPontResult:
    """ROE 杜邦拆解结果."""

    roe: float = 0.0  # 净资产收益率 (%)
    net_margin: float = 0.0  # 净利润率 (%)
    asset_turnover: float = 0.0  # 资产周转率 (倍)
    equity_multiplier: float = 0.0  # 权益乘数
    roe_driver: str = ""  # "margin_driven" / "turnover_driven" / "leverage_driven"
    tax_burden: Optional[float] = None  # 税收负担 (5-factor model)
    interest_burden: Optional[float] = None  # 利息负担
    period: str = ""


@dataclass
class EarningsQuality:
    """盈利质量评分."""

    ocf_to_ni: float = 1.0  # 经营现金流/净利润 (>1 = 高质量)
    receivables_to_revenue: float = 0.0  # 应收账款/营收
    inventory_turnover: float = 0.0  # 存货周转率
    revenue_quality: str = "normal"  # "high" / "normal" / "low"
    accruals_pct: float = 0.0  # 应计利润占比
    quality_score: int = 50  # 0-100


@dataclass
class GrowthMetrics:
    """成长性指标."""

    revenue_growth_yoy: Optional[float] = None  # 营收同比增速 (%)
    net_profit_growth_yoy: Optional[float] = None  # 净利润同比增速 (%)
    deducted_profit_growth_yoy: Optional[float] = None  # 扣非净利润同比 (%)
    eps_growth_yoy: Optional[float] = None  # EPS 同比增速 (%)
    revenue_cagr_3y: Optional[float] = None  # 3 年营收 CAGR
    earnings_cagr_3y: Optional[float] = None  # 3 年净利润 CAGR
    growth_score: int = 50  # 0-100


@dataclass
class FinancialHealth:
    """财务健康度评分."""

    z_score: Optional[float] = None  # Altman Z-score
    z_score_zone: str = ""  # "safe" / "grey" / "distress"
    interest_coverage: Optional[float] = None  # 利息保障倍数
    current_ratio: Optional[float] = None  # 流动比率
    debt_to_equity: Optional[float] = None  # 有息负债/净资产
    debt_to_assets: Optional[float] = None  # 资产负债率
    goodwill_to_equity: Optional[float] = None  # 商誉/净资产
    health_score: int = 50  # 0-100


@dataclass
class FinancialReport:
    """综合财务分析报告."""

    symbol: str = ""
    name: str = ""
    period: str = ""
    dupont: DuPontResult = field(default_factory=DuPontResult)
    earnings_quality: EarningsQuality = field(default_factory=EarningsQuality)
    growth: GrowthMetrics = field(default_factory=GrowthMetrics)
    health: FinancialHealth = field(default_factory=FinancialHealth)
    events: list[dict] = field(default_factory=list)  # 财报事件
    updated_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class FinancialStatementAnalyzer:
    """Fetch and analyze A-share financial statements via AKShare."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=6)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, symbol: str, name: str = "") -> FinancialReport:
        """Run full financial analysis for a stock."""
        report = FinancialReport(symbol=symbol, name=name)

        statements = self._fetch_statements(symbol)
        if not statements:
            return report

        latest = statements[-1] if statements else {}
        report.period = latest.get("period", "")

        report.dupont = self._compute_dupont(latest)
        report.earnings_quality = self._compute_earnings_quality(statements)
        report.growth = self._compute_growth(statements)
        report.health = self._compute_health(latest)
        report.events = self._get_earnings_events(symbol)

        return report

    def analyze_batch(self, symbols: list[str]) -> dict[str, FinancialReport]:
        """Batch analyze multiple stocks."""
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.analyze(sym)
            except Exception as e:
                logger.warning("Financial analysis failed for %s: %s", sym, e)
        return results

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_statements(self, symbol: str) -> list[dict]:
        """Fetch financial statements from AKShare."""
        cache_key = f"statements_{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        statements: list[dict] = []

        try:
            import akshare as ak

            # Try financial analysis indicator (most comprehensive)
            df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
            if df is not None and len(df) > 0:
                for _, row in df.tail(8).iterrows():  # last 8 quarters
                    stmt = {
                        "period": str(row.get("日期", row.get("报告期", "")))[:10],
                        "roe": self._safe_float(row, ["净资产收益率", "ROE", "加权净资产收益率"]),
                        "net_margin": self._safe_float(row, ["销售净利率", "净利润率"]),
                        "gross_margin": self._safe_float(row, ["销售毛利率", "毛利率"]),
                        "asset_turnover": self._safe_float(row, ["总资产周转率"]),
                        "equity_multiplier": self._safe_float(row, ["权益乘数"]),
                        "current_ratio": self._safe_float(row, ["流动比率"]),
                        "debt_to_assets": self._safe_float(row, ["资产负债率"]),
                        "revenue": self._safe_float(row, ["营业总收入", "营业收入"]),
                        "net_profit": self._safe_float(row, ["净利润", "归属母公司净利润"]),
                        "deducted_profit": self._safe_float(row, ["扣非净利润"]),
                        "total_assets": self._safe_float(row, ["总资产", "资产总计"]),
                        "total_equity": self._safe_float(row, ["归属于母公司股东权益", "股东权益"]),
                        "operating_cashflow": self._safe_float(row, ["经营活动现金流量净额"]),
                        "receivables": self._safe_float(row, ["应收账款", "应收票据及应收账款"]),
                        "inventory": self._safe_float(row, ["存货"]),
                        "interest_expense": self._safe_float(row, ["利息费用", "财务费用"]),
                        "goodwill": self._safe_float(row, ["商誉"]),
                        "ebit": self._safe_float(row, ["息税前利润", "利润总额"]),
                    }
                    statements.append(stmt)
        except Exception as e:
            logger.warning("AKShare financial indicator fetch failed for %s: %s", symbol, e)

        # Fallback: try abstract
        if not statements:
            try:
                import akshare as ak
                df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
                if df is not None and len(df) > 0:
                    for _, row in df.tail(8).iterrows():
                        statements.append({
                            "period": str(row.get("报告期", ""))[:10],
                            "revenue": self._safe_float(row, ["营业总收入"]),
                            "net_profit": self._safe_float(row, ["净利润"]),
                            "total_assets": self._safe_float(row, ["资产总计"]),
                            "total_equity": self._safe_float(row, ["股东权益合计"]),
                            "operating_cashflow": self._safe_float(row, ["经营活动现金流量净额"]),
                        })
            except Exception as e:
                logger.warning("AKShare abstract fetch failed for %s: %s", symbol, e)

        self._cache_set(cache_key, statements)
        return statements

    # ------------------------------------------------------------------
    # DuPont decomposition
    # ------------------------------------------------------------------

    def _compute_dupont(self, stmt: dict) -> DuPontResult:
        """ROE = NetMargin × AssetTurnover × EquityMultiplier."""
        result = DuPontResult()

        roe = stmt.get("roe")
        if roe and roe > 0:
            result.roe = roe
        else:
            # Reconstruct from components
            nm = stmt.get("net_margin", 0) or 0
            revenue = stmt.get("revenue", 0) or 0
            assets = stmt.get("total_assets", 1) or 1
            equity = stmt.get("total_equity", 1) or 1
            np = stmt.get("net_profit", 0) or 0

            if revenue > 0:
                nm = (np / revenue) * 100
            at = revenue / assets if assets > 0 else 0
            em = assets / equity if equity > 0 else 1

            result.net_margin = round(nm, 2)
            result.asset_turnover = round(at, 2)
            result.equity_multiplier = round(em, 2)
            result.roe = round(nm * at * em / 100, 2)  # nm is %, at × em is ratio
            result.roe_driver = self._identify_roe_driver(nm, at, em)
            return result

        result.net_margin = stmt.get("net_margin", 0) or 0
        result.asset_turnover = stmt.get("asset_turnover", 0) or 0
        result.equity_multiplier = stmt.get("equity_multiplier", 0) or 0
        result.roe_driver = self._identify_roe_driver(
            result.net_margin, result.asset_turnover, result.equity_multiplier
        )
        return result

    @staticmethod
    def _identify_roe_driver(nm: float, at: float, em: float) -> str:
        """Identify primary ROE driver."""
        if em > 3.0:
            return "leverage_driven"
        if at > 1.5:
            return "turnover_driven"
        if nm > 15:
            return "margin_driven"
        return "balanced"

    # ------------------------------------------------------------------
    # Earnings quality
    # ------------------------------------------------------------------

    def _compute_earnings_quality(self, statements: list[dict]) -> EarningsQuality:
        """Compute earnings quality from multiple quarters."""
        result = EarningsQuality()
        if not statements:
            return result

        latest = statements[-1]
        ocf = latest.get("operating_cashflow", 0) or 0
        ni = latest.get("net_profit", 1) or 1
        rev = latest.get("revenue", 1) or 1
        recv = latest.get("receivables", 0) or 0
        inv = latest.get("inventory", 0) or 0

        # OCF/NI
        result.ocf_to_ni = round(ocf / max(abs(ni), 0.01), 2)
        result.receivables_to_revenue = round(recv / max(rev, 0.01), 2)
        result.inventory_turnover = round(rev / max(inv, 0.01), 2)

        # Accruals estimate
        avg_assets = sum(s.get("total_assets", 0) or 0 for s in statements[-4:]) / max(len(statements[-4:]), 1)
        if avg_assets > 0:
            result.accruals_pct = round(abs(ni - ocf) / avg_assets * 100, 2)

        # Quality rating
        score = 50
        if result.ocf_to_ni > 0.8:
            score += 20
        elif result.ocf_to_ni > 0.5:
            score += 10
        elif result.ocf_to_ni < 0.3:
            score -= 20

        if result.receivables_to_revenue < 0.3:
            score += 10
        elif result.receivables_to_revenue > 0.6:
            score -= 15

        if result.accruals_pct < 5:
            score += 10
        elif result.accruals_pct > 15:
            score -= 10

        if result.ocf_to_ni >= 1.0:
            result.revenue_quality = "high"
        elif result.ocf_to_ni >= 0.5:
            result.revenue_quality = "normal"
        else:
            result.revenue_quality = "low"

        result.quality_score = max(0, min(100, score))
        return result

    # ------------------------------------------------------------------
    # Growth metrics
    # ------------------------------------------------------------------

    def _compute_growth(self, statements: list[dict]) -> GrowthMetrics:
        """Compute YoY growth rates."""
        result = GrowthMetrics()
        if len(statements) < 5:  # need at least 5 quarters for YoY
            return result

        latest = statements[-1]
        same_q_last_year = statements[-5]  # 4 quarters back = YoY

        # Revenue growth
        rev_cur = latest.get("revenue", 0) or 0
        rev_prev = same_q_last_year.get("revenue", 0) or 0
        if rev_prev > 0:
            result.revenue_growth_yoy = round((rev_cur / rev_prev - 1) * 100, 2)

        # Net profit growth
        np_cur = latest.get("net_profit", 0) or 0
        np_prev = same_q_last_year.get("net_profit", 0) or 0
        if abs(np_prev) > 0.01:
            result.net_profit_growth_yoy = round((np_cur / np_prev - 1) * 100, 2)

        # Deducted profit growth
        dp_cur = latest.get("deducted_profit", 0) or 0
        dp_prev = same_q_last_year.get("deducted_profit", 0) or 0
        if abs(dp_prev) > 0.01:
            result.deducted_profit_growth_yoy = round((dp_cur / dp_prev - 1) * 100, 2)

        # EPS growth (proxy via net profit)
        result.eps_growth_yoy = result.net_profit_growth_yoy

        # 3-year CAGR (from oldest to latest available)
        if len(statements) >= 13:  # ~3 years
            oldest = statements[0]
            rev_old = oldest.get("revenue", 0) or 0
            np_old = oldest.get("net_profit", 0) or 0
            if rev_old > 0:
                result.revenue_cagr_3y = round(((rev_cur / rev_old) ** (1/3) - 1) * 100, 2)
            if np_old > 0:
                result.earnings_cagr_3y = round(((np_cur / np_old) ** (1/3) - 1) * 100, 2)

        # Growth score
        score = 50
        if result.revenue_growth_yoy is not None:
            if result.revenue_growth_yoy > 30:
                score += 20
            elif result.revenue_growth_yoy > 15:
                score += 10
            elif result.revenue_growth_yoy < 0:
                score -= 15
        if result.net_profit_growth_yoy is not None:
            if result.net_profit_growth_yoy > 30:
                score += 15
            elif result.net_profit_growth_yoy > 15:
                score += 8
            elif result.net_profit_growth_yoy < 0:
                score -= 15

        result.growth_score = max(0, min(100, score))
        return result

    # ------------------------------------------------------------------
    # Financial health (Z-score, etc.)
    # ------------------------------------------------------------------

    def _compute_health(self, stmt: dict) -> FinancialHealth:
        """Compute financial health including Z-score."""
        result = FinancialHealth()

        assets = stmt.get("total_assets", 0) or 0
        equity = stmt.get("total_equity", 1) or 1
        current_ratio = stmt.get("current_ratio", 0) or 0
        debt_to_assets = stmt.get("debt_to_assets", 0) or 0
        ebit = stmt.get("ebit", 0) or 0
        interest = stmt.get("interest_expense", 1) or 1
        revenue = stmt.get("revenue", 0) or 0
        goodwill = stmt.get("goodwill", 0) or 0
        net_profit = stmt.get("net_profit", 0) or 0

        # Altman Z-score (manufacturing version, adapted)
        if assets > 0:
            wc = (current_ratio / 100) * assets  # rough working capital
            retained = net_profit  # proxy for retained earnings
            x1 = wc / assets
            x2 = retained / assets
            x3 = ebit / assets
            x4 = equity / assets  # market cap proxy
            x5 = revenue / assets

            result.z_score = round(1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5, 2)

            if result.z_score > 2.99:
                result.z_score_zone = "safe"
            elif result.z_score > 1.81:
                result.z_score_zone = "grey"
            else:
                result.z_score_zone = "distress"

        # Interest coverage
        if abs(interest) > 0.01:
            result.interest_coverage = round(ebit / abs(interest), 2)

        # Current ratio (already in %)
        result.current_ratio = current_ratio

        # Debt ratios
        result.debt_to_assets = debt_to_assets
        if equity > 0:
            total_debt = assets - equity
            result.debt_to_equity = round(total_debt / equity, 2)

        # Goodwill risk
        if equity > 0 and goodwill > 0:
            result.goodwill_to_equity = round(goodwill / equity, 2)

        # Health score
        score = 50
        if result.z_score is not None:
            if result.z_score > 3.0:
                score += 20
            elif result.z_score > 2.0:
                score += 10
            elif result.z_score < 1.5:
                score -= 20
        if result.interest_coverage is not None:
            if result.interest_coverage > 10:
                score += 10
            elif result.interest_coverage < 1.5:
                score -= 15
        if result.debt_to_equity is not None:
            if result.debt_to_equity < 0.5:
                score += 10
            elif result.debt_to_equity > 2:
                score -= 15
        if result.goodwill_to_equity is not None and result.goodwill_to_equity > 0.3:
            score -= 15

        result.health_score = max(0, min(100, score))
        return result

    # ------------------------------------------------------------------
    # Earnings event calendar
    # ------------------------------------------------------------------

    def _get_earnings_events(self, symbol: str) -> list[dict]:
        """Fetch upcoming earnings events."""
        cache_key = f"events_{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        events: list[dict] = []

        try:
            import akshare as ak

            # Earnings forecast
            df_yjyg = ak.stock_yjyg_em(date="")  # 业绩预告
            if df_yjyg is not None and len(df_yjyg) > 0:
                stock_rows = df_yjyg[df_yjyg["股票代码"].astype(str).str.contains(symbol)]
                for _, row in stock_rows.iterrows():
                    events.append({
                        "type": "业绩预告",
                        "date": str(row.get("公告日期", "")),
                        "period": str(row.get("报告期", "")),
                        "forecast": str(row.get("业绩变动", "")),
                        "change_min": self._safe_float(row, ["业绩变动幅度下限"]),
                        "change_max": self._safe_float(row, ["业绩变动幅度上限"]),
                    })

            # Earnings express
            df_yjkb = ak.stock_yjkb_em(date="")  # 业绩快报
            if df_yjkb is not None and len(df_yjkb) > 0:
                stock_rows = df_yjkb[df_yjkb["股票代码"].astype(str).str.contains(symbol)]
                for _, row in stock_rows.iterrows():
                    events.append({
                        "type": "业绩快报",
                        "date": str(row.get("公告日期", "")),
                        "revenue": self._safe_float(row, ["营业总收入"]),
                        "net_profit": self._safe_float(row, ["净利润"]),
                        "eps": self._safe_float(row, ["每股收益"]),
                    })
        except Exception as e:
            logger.debug("Earnings events fetch failed for %s: %s", symbol, e)

        self._cache_set(cache_key, events)
        return events

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(row: pd.Series, candidates: list[str]) -> Optional[float]:
        """Safely extract float from row with multiple column name candidates."""
        for col in candidates:
            if col in row.index:
                try:
                    return float(row[col])
                except (ValueError, TypeError):
                    continue
        return None

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
