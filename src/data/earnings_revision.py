"""Earnings revision factor — 同花顺一致预期EPS primary, AKShare fallback.

V2: Primary source switched from AKShare → 同花顺 basic.10jqka.com.cn consensus EPS.
    同花顺 provides: 年度, 预测机构数, 最小值, 均值, 最大值 — cleaner than AKShare.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import StringIO
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EarningsRevisionFactor:
    symbol: str
    revision_score: int = 50
    upgrade_count: int = 0
    downgrade_count: int = 0
    upgrade_downgrade_ratio: float = 1.0
    consensus_trend: str = "stable"
    surprise_last_q: Optional[float] = None
    earnings_momentum: str = "neutral"
    analyst_count: int = 0
    dispersion: Optional[float] = None
    # V2: 同花顺 specific fields
    eps_current: Optional[float] = None     # 当年一致预期EPS
    eps_next: Optional[float] = None        # 明年一致预期EPS
    consensus_source: str = "unknown"       # "tonghuashun" / "akshare" / "none"
    updated_at: datetime = field(default_factory=datetime.now)


class EarningsRevisionAnalyzer:
    """Analyze earnings revisions — 同花顺 primary, AKShare fallback."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, EarningsRevisionFactor]] = {}
        self._cache_ttl = timedelta(hours=6)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, symbol: str) -> EarningsRevisionFactor:
        cache_key = f"revision:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        factor = EarningsRevisionFactor(symbol=symbol)

        # Primary: 同花顺一致预期
        ths_data = self._fetch_ths_forecast(symbol)
        if ths_data and len(ths_data) >= 1:
            factor.consensus_source = "tonghuashun"
            self._parse_ths_data(factor, ths_data)
        else:
            # Fallback: AKShare
            factor.consensus_source = "akshare"
            ratings = self._fetch_akshare_ratings(symbol)
            if ratings is not None and len(ratings) > 0:
                up, down = self._count_upgrades_downgrades(ratings)
                factor.upgrade_count = up
                factor.downgrade_count = down
                factor.analyst_count = len(ratings)
                if up + down > 0:
                    factor.upgrade_downgrade_ratio = up / max(down, 1)

            forecasts = self._fetch_akshare_forecasts(symbol)
            if forecasts is not None and len(forecasts) > 0:
                factor.consensus_trend = self._compute_consensus_trend(forecasts)
                factor.dispersion = self._compute_dispersion(forecasts)

        # Compute revision score
        factor.revision_score = self._compute_revision_score(factor)
        factor.earnings_momentum = self._compute_earnings_momentum(factor)

        self._cache_set(cache_key, factor)
        return factor

    def analyze_batch(self, symbols: list[str]) -> dict[str, EarningsRevisionFactor]:
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.analyze(symbol)
            except Exception as e:
                logger.warning("Earnings revision failed for %s: %s", symbol, e)
                results[symbol] = EarningsRevisionFactor(symbol=symbol)
        return results

    # ------------------------------------------------------------------
    # 同花顺 data parsing (V2 primary)
    # ------------------------------------------------------------------

    def _parse_ths_data(self, factor: EarningsRevisionFactor, data: list) -> None:
        """Parse 同花顺一致预期 EPS table.
        Table columns: 年度, 预测机构数, 最小值, 均值, 最大值
        """
        import pandas as pd

        try:
            # Find the EPS forecast table
            for df_like in data:
                if not isinstance(df_like, pd.DataFrame):
                    continue
                cols = [str(c) for c in df_like.columns]
                if not any("每股收益" in c or "均值" in c for c in cols):
                    continue

                df = df_like
                # Extract current year (first row)
                if len(df) >= 1:
                    row0 = df.iloc[0]
                    factor.eps_current = self._ths_pick(row0, "均值")
                    factor.analyst_count = self._ths_pick_int(row0, "预测机构数")

                # Extract next year (second row)
                if len(df) >= 2:
                    row1 = df.iloc[1]
                    factor.eps_next = self._ths_pick(row1, "均值")

                # Upgrade/downgrade: compare current vs next EPS trend
                if factor.eps_current and factor.eps_next and factor.eps_current > 0:
                    growth = (factor.eps_next - factor.eps_current) / factor.eps_current
                    if growth > 0.15:
                        factor.consensus_trend = "rising"
                        factor.upgrade_count = factor.analyst_count
                        factor.upgrade_downgrade_ratio = 2.0
                    elif growth < -0.05:
                        factor.consensus_trend = "falling"
                        factor.downgrade_count = factor.analyst_count
                        factor.upgrade_downgrade_ratio = 0.3
                    else:
                        factor.consensus_trend = "stable"
                        factor.upgrade_downgrade_ratio = 1.0

                # Dispersion: (max - min) / mean
                eps_min = self._ths_pick(row0, "最小值") if len(df) >= 1 else None
                eps_max = self._ths_pick(row0, "最大值") if len(df) >= 1 else None
                if eps_min and eps_max and factor.eps_current and factor.eps_current > 0:
                    factor.dispersion = (eps_max - eps_min) / factor.eps_current
                return  # Successfully parsed
        except Exception as e:
            logger.debug("THS data parse failed for %s: %s", factor.symbol, e)

    @staticmethod
    def _ths_pick(row, col_name: str) -> Optional[float]:
        """Pick a value from a DataFrame row by column name substring match."""
        import pandas as pd
        for c in row.index:
            if col_name in str(c):
                v = row[c]
                if pd.notna(v):
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        continue
        return None

    @staticmethod
    def _ths_pick_int(row, col_name: str) -> int:
        """Pick an integer value from a DataFrame row."""
        import pandas as pd
        for c in row.index:
            if col_name in str(c):
                v = row[c]
                if pd.notna(v):
                    try:
                        return int(v)
                    except (ValueError, TypeError):
                        continue
        return 0

    # ------------------------------------------------------------------
    # 同花顺 data fetching
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_ths_forecast(symbol: str) -> list:
        """Fetch 同花顺一致预期EPS from basic.10jqka.com.cn."""
        try:
            import requests
            import pandas as pd

            url = f"https://basic.10jqka.com.cn/new/{symbol}/worth.html"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://basic.10jqka.com.cn/",
            }
            r = requests.get(url, headers=headers, timeout=15,
                             proxies={"http": None, "https": None})
            r.encoding = "gbk"
            dfs = pd.read_html(StringIO(r.text))
            return list(dfs)
        except Exception as e:
            logger.debug("THS forecast fetch failed for %s: %s", symbol, e)
            return []

    # ------------------------------------------------------------------
    # AKShare fallback (unchanged from V1)
    # ------------------------------------------------------------------

    def _fetch_akshare_ratings(self, symbol: str):
        cache_key = f"ak_ratings:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            import akshare as ak
            df = ak.stock_report_analyst(symbol=symbol)
            if df is not None and len(df) > 0:
                self._cache_set(cache_key, df)
                return df
        except Exception:
            pass
        return None

    def _fetch_akshare_forecasts(self, symbol: str):
        cache_key = f"ak_forecasts:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            import akshare as ak
            code = symbol.lstrip("SH").lstrip("SZ").lstrip("BJ")
            df = ak.stock_profit_forecast(symbol=code)
            if df is not None and len(df) > 0:
                self._cache_set(cache_key, df)
                return df
        except Exception as e:
            logger.debug("AKShare profit forecast failed for %s: %s", symbol, e)
        return None

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_revision_score(self, factor: EarningsRevisionFactor) -> int:
        score = 50.0

        # THS-based scoring
        if factor.consensus_source == "tonghuashun":
            if factor.eps_current and factor.eps_next and factor.eps_current > 0:
                growth = (factor.eps_next - factor.eps_current) / factor.eps_current
                score += min(max(growth * 100, -30), 30)
            if factor.consensus_trend == "rising":
                score += 10
            elif factor.consensus_trend == "falling":
                score -= 10
            if factor.analyst_count >= 10:
                score += 5
            elif factor.analyst_count < 3:
                score -= 5
            if factor.dispersion is not None and factor.dispersion > 0.3:
                score -= 5
        else:
            # AKShare-based scoring (V1 logic)
            if factor.upgrade_downgrade_ratio > 1.0:
                score += min((factor.upgrade_downgrade_ratio - 1.0) * 20, 20)
            else:
                score += max((factor.upgrade_downgrade_ratio - 1.0) * 30, -20)
            if factor.upgrade_count >= 5:
                score += 10
            elif factor.upgrade_count >= 3:
                score += 5
            if factor.consensus_trend == "rising":
                score += 5
            elif factor.consensus_trend == "falling":
                score -= 5
            if factor.dispersion is not None and factor.dispersion > 0.3:
                score -= 5

        if factor.earnings_momentum == "accelerating":
            score += 5
        elif factor.earnings_momentum == "decelerating":
            score -= 5

        return max(0, min(100, int(score)))

    # ------------------------------------------------------------------
    # Sub-computations
    # ------------------------------------------------------------------

    @staticmethod
    def _count_upgrades_downgrades(ratings) -> tuple[int, int]:
        up, down = 0, 0
        try:
            import pandas as pd
            if isinstance(ratings, pd.DataFrame):
                for _, row in ratings.iterrows():
                    rating_str = ""
                    for col in ratings.columns:
                        val = str(row[col]).lower()
                        if any(kw in val for kw in ["上调", "买入", "增持", "推荐", "upgrade", "buy"]):
                            rating_str = val
                            break
                    if any(kw in rating_str for kw in ["上调", "upgrade"]):
                        up += 1
                    elif any(kw in rating_str for kw in ["下调", "downgrade", "减持", "卖出"]):
                        down += 1
        except Exception:
            pass
        return up, down

    @staticmethod
    def _compute_consensus_trend(forecasts) -> str:
        try:
            import pandas as pd
            if isinstance(forecasts, pd.DataFrame) and len(forecasts) > 1:
                for col in forecasts.columns:
                    if any(kw in str(col).lower() for kw in ["profit", "eps", "净利润", "forecast"]):
                        vals = pd.to_numeric(forecasts[col], errors="coerce").dropna()
                        if len(vals) >= 3:
                            recent = vals.iloc[-3:].mean()
                            earlier = vals.iloc[:3].mean() if len(vals) >= 6 else vals.iloc[0]
                            if earlier > 0:
                                change_pct = (recent - earlier) / earlier
                                if change_pct > 0.05:
                                    return "rising"
                                elif change_pct < -0.05:
                                    return "falling"
        except Exception:
            pass
        return "stable"

    @staticmethod
    def _compute_dispersion(forecasts) -> Optional[float]:
        try:
            import pandas as pd
            if isinstance(forecasts, pd.DataFrame) and len(forecasts) > 2:
                for col in forecasts.columns:
                    if any(kw in str(col).lower() for kw in ["profit", "eps", "forecast"]):
                        vals = pd.to_numeric(forecasts[col], errors="coerce").dropna()
                        if len(vals) >= 3 and vals.mean() > 0:
                            return float(vals.std() / vals.mean())
        except Exception:
            pass
        return None

    @staticmethod
    def _compute_earnings_momentum(f: EarningsRevisionFactor) -> str:
        score_up = 0
        if f.upgrade_downgrade_ratio > 1.5:
            score_up += 1
        if f.consensus_trend == "rising":
            score_up += 1
        if f.upgrade_count >= 5:
            score_up += 1
        if score_up >= 2:
            return "accelerating"
        if score_up == 0:
            return "decelerating"
        return "neutral"

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

    def _cache_set(self, key: str, val: object):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()
