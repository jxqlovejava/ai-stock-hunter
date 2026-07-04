"""Multi-dimensional northbound (北向资金) profile — 同花顺 hsgtApi minute-level primary.

V2: Primary source switched from AKShare daily → 同花顺 hsgtApi minute-level.
    262 data points per day (09:10–15:00) + self-caching for historical accumulation.
    Falls back to AKShare if 同花顺 unavailable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 同花顺北向 API headers
HSGT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}

# Local cache path
DEFAULT_CACHE_DIR = Path.home() / ".ai-stock-hunter" / "cache"


@dataclass
class NorthboundProfile:
    total_net_flow: float = 0.0          # 当日净流入（亿元）
    cumulative_net_flow: float = 0.0     # 累计净流入（亿元）
    sector_flows: dict[str, float] = field(default_factory=dict)
    style_preference: str = "balanced"   # "value" / "growth" / "balanced"
    flow_acceleration: float = 0.0       # (5日均 - 前5日均) / std
    consecutive_days: int = 0
    large_cap_ratio: float = 0.0
    small_cap_ratio: float = 0.0
    is_inflow_sustained: bool = False
    momentum_signal: str = "neutral"     # "accelerating" / "decelerating" / "neutral"
    score: int = 50                      # 0-100 composite
    # V2: minute-level fields
    minute_data: list[dict] = field(default_factory=list)  # [{time, hgt_yi, sgt_yi}]
    intraday_trend: str = "neutral"      # "inflow_accel" / "outflow_accel" / "reversal" / "neutral"
    updated_at: datetime = field(default_factory=datetime.now)


class NorthboundAnalyzer:
    """Multi-dimensional northbound analyzer — 同花顺 minute-level primary, AKShare fallback."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem_cache: dict[str, tuple[datetime, object]] = {}
        self._mem_ttl = timedelta(minutes=15)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> NorthboundProfile:
        """Fetch data and compute full northbound profile (V2: minute-level)."""
        profile = NorthboundProfile()

        # Primary: 同花顺 minute-level
        minute_df = self._fetch_hsgt_minute()
        daily_flows = self._load_daily_history()

        if minute_df is not None and not minute_df.empty:
            # Extract daily totals from minute data
            last = minute_df.dropna(subset=["hgt_yi", "sgt_yi"]).iloc[-1] if not minute_df.empty else None
            if last is not None:
                hgt_close = float(last["hgt_yi"])
                sgt_close = float(last["sgt_yi"])
                profile.total_net_flow = hgt_close + sgt_close

                # Save today's snapshot to local cache
                self._save_daily_snapshot(datetime.now().strftime("%Y-%m-%d"), hgt_close, sgt_close)
                daily_flows = self._load_daily_history()  # Reload with today's data

            # Intraday trend
            profile.minute_data = minute_df.to_dict("records")
            profile.intraday_trend = self._compute_intraday_trend(minute_df)

        # Fallback: AKShare daily
        if profile.total_net_flow == 0.0:
            ak_flow = self._fetch_akshare_daily()
            if ak_flow is not None:
                profile.total_net_flow = ak_flow

        # Compute from daily history
        if daily_flows is not None and len(daily_flows) > 0:
            profile.cumulative_net_flow = float(daily_flows["total"].sum())
            profile.consecutive_days = self._count_consecutive(daily_flows["total"])

            if len(daily_flows) >= 10:
                recent_5 = daily_flows["total"].iloc[-5:].mean()
                prev_5 = daily_flows["total"].iloc[-10:-5].mean()
                std_val = daily_flows["total"].iloc[-20:].std() if len(daily_flows) >= 20 else daily_flows["total"].std()
                if std_val and std_val > 0:
                    profile.flow_acceleration = float((recent_5 - prev_5) / std_val)
                    if profile.flow_acceleration > 0.5:
                        profile.momentum_signal = "accelerating"
                    elif profile.flow_acceleration < -0.5:
                        profile.momentum_signal = "decelerating"

            profile.is_inflow_sustained = profile.consecutive_days >= 3 and profile.total_net_flow > 0

        # Style & size preferences
        profile.style_preference = self._compute_style_preference()
        size_data = self._fetch_size_preference()
        if size_data:
            profile.large_cap_ratio = size_data.get("large_cap", 0.0)
            profile.small_cap_ratio = size_data.get("small_cap", 0.0)

        # Composite score
        profile.score = self._compute_composite_score(profile)
        return profile

    # ------------------------------------------------------------------
    # Composite scoring
    # ------------------------------------------------------------------

    def _compute_composite_score(self, p: NorthboundProfile) -> int:
        score = 50.0
        flow_signal = min(max(p.total_net_flow / 10.0 * 2.0, -20), 20)
        score += flow_signal
        score += min(max(p.flow_acceleration * 5.0, -15), 15)

        if p.consecutive_days >= 5:
            score += 10
        elif p.consecutive_days >= 3:
            score += 5
        elif p.consecutive_days <= -5:
            score -= 10
        elif p.consecutive_days <= -3:
            score -= 5

        # Intraday trend bonus
        if p.intraday_trend == "inflow_accel":
            score += 5
        elif p.intraday_trend == "outflow_accel":
            score -= 5
        elif p.intraday_trend == "reversal":
            score += 3  # Positive reversal = dip-buying signal

        if p.style_preference == "growth":
            score += 3
        elif p.style_preference == "value":
            score += 2

        return max(0, min(100, int(score)))

    # ------------------------------------------------------------------
    # Intraday analysis (V2)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_intraday_trend(df: pd.DataFrame) -> str:
        """Detect intraday flow pattern: accelerating inflow, outflow, or reversal."""
        if df is None or df.empty:
            return "neutral"
        try:
            hgt = pd.to_numeric(df["hgt_yi"], errors="coerce").dropna()
            sgt = pd.to_numeric(df["sgt_yi"], errors="coerce").dropna()
            if len(hgt) < 20 or len(sgt) < 20:
                return "neutral"

            first_half = (hgt.iloc[: len(hgt) // 2].iloc[-1] if len(hgt) > 1 else 0) - (hgt.iloc[0] if len(hgt) > 0 else 0)
            second_half = (hgt.iloc[-1] if len(hgt) > 0 else 0) - (hgt.iloc[len(hgt) // 2].iloc[-1] if len(hgt) > 1 else 0)
            first_s = (sgt.iloc[: len(sgt) // 2].iloc[-1] if len(sgt) > 1 else 0) - (sgt.iloc[0] if len(sgt) > 0 else 0)
            second_s = (sgt.iloc[-1] if len(sgt) > 0 else 0) - (sgt.iloc[len(sgt) // 2].iloc[-1] if len(sgt) > 1 else 0)

            total_first = float(first_half + first_s)
            total_second = float(second_half + second_s)

            if total_first < -5 and total_second > 5:
                return "reversal"
            if total_second > total_first and total_second > 0:
                return "inflow_accel"
            if total_second < total_first and total_second < 0:
                return "outflow_accel"
            return "neutral"
        except Exception:
            return "neutral"

    # ------------------------------------------------------------------
    # Daily history & caching
    # ------------------------------------------------------------------

    def _daily_cache_path(self) -> Path:
        return self._cache_dir / "northbound_daily.csv"

    def _save_daily_snapshot(self, date: str, hgt: float, sgt: float):
        path = self._daily_cache_path()
        rows = {}
        if path.exists():
            for line in path.read_text().strip().split("\n")[1:]:
                parts = line.split(",")
                if len(parts) == 3:
                    rows[parts[0]] = line
        rows[date] = f"{date},{hgt},{sgt}"
        with open(path, "w") as f:
            f.write("date,hgt,sgt\n")
            for d in sorted(rows.keys()):
                f.write(rows[d] + "\n")

    def _load_daily_history(self, n: int = 60) -> Optional[pd.DataFrame]:
        path = self._daily_cache_path()
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            if len(df) == 0:
                return None
            df["total"] = df["hgt"] + df["sgt"]
            return df.tail(n)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_hsgt_minute(self) -> Optional[pd.DataFrame]:
        """Fetch minute-level northbound from 同花顺 hsgtApi."""
        cache_key = "hsgt_minute"
        cached = self._mem_get(cache_key)
        if cached is not None:
            return cached

        try:
            import requests
            r = requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                             headers=HSGT_HEADERS, timeout=10)
            if r.status_code != 200:
                return None
            d = r.json()
            times = d.get("time", [])
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])
            n = len(times)
            df = pd.DataFrame({
                "time": times,
                "hgt_yi": hgt[:n] + [None] * (n - len(hgt)),
                "sgt_yi": sgt[:n] + [None] * (n - len(sgt)),
            })
            self._mem_set(cache_key, df)
            return df
        except Exception as e:
            logger.debug("同花顺 hsgtApi failed: %s", e)
        return None

    def _fetch_akshare_daily(self) -> Optional[float]:
        """Fallback: AKShare daily northbound flow."""
        cache_key = "ak_nb_flow"
        cached = self._mem_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
            if df is not None and len(df) > 0:
                for col in ["净流入", "当日净流入", "资金流向"]:
                    if col in df.columns:
                        val = float(pd.to_numeric(df[col], errors="coerce").iloc[-1])
                        self._mem_set(cache_key, val)
                        return val
        except Exception as e:
            logger.debug("AKShare northbound fallback failed: %s", e)
        return None

    def _fetch_size_preference(self) -> Optional[dict]:
        return {"large_cap": 0.6, "small_cap": 0.4}  # Neutral estimate

    def _compute_style_preference(self) -> str:
        try:
            import akshare as ak
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流向")
            if df is None or len(df) == 0:
                return "balanced"
            value_sectors = {"银行", "保险", "消费", "食品饮料", "家用电器", "公用事业"}
            growth_sectors = {"电子", "计算机", "通信", "新能源", "医药生物", "传媒"}
            v_score, g_score = 0.0, 0.0
            for _, row in df.iterrows():
                sector = str(row.iloc[0]) if len(row) > 0 else ""
                flow_val = 0.0
                for col in df.columns:
                    if "净流入" in str(col) or "净额" in str(col):
                        try:
                            flow_val = float(row[col])
                            break
                        except (ValueError, TypeError):
                            continue
                if any(vs in sector for vs in value_sectors):
                    v_score += flow_val
                if any(gs in sector for gs in growth_sectors):
                    g_score += flow_val
            total = abs(v_score) + abs(g_score)
            if total == 0:
                return "balanced"
            if v_score > g_score * 1.5:
                return "value"
            elif g_score > v_score * 1.5:
                return "growth"
        except Exception:
            pass
        return "balanced"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_consecutive(series: pd.Series) -> int:
        if len(series) == 0:
            return 0
        recent = series.iloc[-1]
        if recent == 0:
            return 0
        direction = 1 if recent > 0 else -1
        count = 0
        for i in range(len(series) - 1, -1, -1):
            if (direction == 1 and series.iloc[i] > 0) or (direction == -1 and series.iloc[i] < 0):
                count += 1
            else:
                break
        return count * direction

    # Memory cache
    def _mem_get(self, key: str) -> Optional[object]:
        entry = self._mem_cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._mem_ttl:
            return val
        del self._mem_cache[key]
        return None

    def _mem_set(self, key: str, val: object):
        self._mem_cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._mem_cache.clear()
