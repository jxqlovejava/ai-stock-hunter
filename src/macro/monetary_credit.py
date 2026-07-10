"""Monetary-Credit dual-quadrant framework for A-share macro regime classification.

Tracks: 社融增速, M1-M2剪刀差, LPR(1Y/5Y), DR007, 信贷脉冲
Classifies into 4 quadrants with sector recommendations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Quadrant(str, Enum):
    EASY_MONEY_EASY_CREDIT = "宽货币+宽信用"
    EASY_MONEY_TIGHT_CREDIT = "宽货币+紧信用"
    TIGHT_MONEY_EASY_CREDIT = "紧货币+宽信用"
    TIGHT_MONEY_TIGHT_CREDIT = "紧货币+紧信用"


@dataclass
class RegimeAdjustments:
    """宏观象限对各诊断维度及仓位的动态调整系数。

    所有系数默认 1.0（无调整）。> 1.0 = 该维度在当前象限中应获得更高权重。
    """

    quadrant: Quadrant
    # 诊断维度权重调整
    value_weight: float = 1.0       # 价值维度
    quality_weight: float = 1.0     # 质量维度
    momentum_weight: float = 1.0    # 动量维度
    growth_weight: float = 1.0      # 成长维度
    macro_weight: float = 1.0       # 宏观维度自身
    sentiment_weight: float = 1.0   # 情绪维度
    # 仓位约束
    position_cap: float = 0.20      # 单票仓位上限（默认 20%）
    max_total_position: float = 0.80  # 总仓位上限
    # 板块方向
    sector_favor: list[str] = field(default_factory=list)
    sector_avoid: list[str] = field(default_factory=list)
    # 风格偏好
    style_preference: str = ""      # "value" / "growth" / "defensive" / "balanced"
    # 总体进取度 0.0-1.0
    aggressiveness: float = 0.5


# Quadrant → default adjustments mapping
_QUADRANT_ADJUSTMENTS: dict[Quadrant, dict] = {
    Quadrant.EASY_MONEY_EASY_CREDIT: {
        "value_weight": 0.8, "quality_weight": 0.9, "momentum_weight": 1.3,
        "growth_weight": 1.4, "macro_weight": 0.8, "sentiment_weight": 1.2,
        "position_cap": 0.25, "max_total_position": 0.90,
        "style_preference": "growth", "aggressiveness": 0.8,
    },
    Quadrant.EASY_MONEY_TIGHT_CREDIT: {
        "value_weight": 1.0, "quality_weight": 1.2, "momentum_weight": 0.9,
        "growth_weight": 1.2, "macro_weight": 0.9, "sentiment_weight": 1.0,
        "position_cap": 0.20, "max_total_position": 0.75,
        "style_preference": "growth", "aggressiveness": 0.6,
    },
    Quadrant.TIGHT_MONEY_EASY_CREDIT: {
        "value_weight": 1.3, "quality_weight": 1.2, "momentum_weight": 0.8,
        "growth_weight": 0.8, "macro_weight": 1.1, "sentiment_weight": 0.9,
        "position_cap": 0.15, "max_total_position": 0.70,
        "style_preference": "value", "aggressiveness": 0.5,
    },
    Quadrant.TIGHT_MONEY_TIGHT_CREDIT: {
        "value_weight": 1.1, "quality_weight": 1.4, "momentum_weight": 0.5,
        "growth_weight": 0.5, "macro_weight": 1.3, "sentiment_weight": 0.6,
        "position_cap": 0.10, "max_total_position": 0.50,
        "style_preference": "defensive", "aggressiveness": 0.2,
    },
}


@dataclass
class MacroRegime:
    quadrant: Quadrant
    confidence: float  # 0.0-1.0
    social_financing_growth: Optional[float] = None
    m1_m2_gap: Optional[float] = None
    lpr_1y: Optional[float] = None
    lpr_5y: Optional[float] = None
    dr007: Optional[float] = None
    credit_pulse: Optional[float] = None
    transition_signals: list[str] = field(default_factory=list)
    recommended_sectors: list[str] = field(default_factory=list)
    avoid_sectors: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)


# Quadrant → sector mapping
QUADRANT_SECTOR_MAP: dict[Quadrant, tuple[list[str], list[str]]] = {
    Quadrant.EASY_MONEY_EASY_CREDIT: (
        ["券商", "银行", "地产", "基建", "建材", "有色", "消费"],
        ["债券", "现金"],
    ),
    Quadrant.EASY_MONEY_TIGHT_CREDIT: (
        ["成长股", "医药", "科技", "新能源", "军工"],
        ["银行", "地产", "周期"],
    ),
    Quadrant.TIGHT_MONEY_EASY_CREDIT: (
        ["银行", "保险", "消费", "价值股"],
        ["高估值成长", "地产"],
    ),
    Quadrant.TIGHT_MONEY_TIGHT_CREDIT: (
        ["防御性消费", "公用事业", "现金", "债券"],
        ["券商", "地产", "有色", "成长股"],
    ),
}


class MonetaryCreditAnalyzer:
    """Analyze monetary and credit conditions to classify macro regime."""

    # Approximate policy rate for DR007 comparison (7-day reverse repo rate)
    POLICY_RATE = 1.50  # Latest 7-day reverse repo rate
    # Approximate nominal GDP growth for social financing comparison
    NOMINAL_GDP_GROWTH = 5.0  # Rough estimate, updated periodically

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> MacroRegime:
        """Fetch all indicators and classify current macro regime."""
        signals_missing = 0

        sf_growth = self._get_social_financing_growth()
        if sf_growth is None:
            signals_missing += 1

        m1_m2_gap = self._get_m1_m2_gap()
        if m1_m2_gap is None:
            signals_missing += 1

        lpr_1y = self._get_lpr_1y()
        lpr_5y = self._get_lpr_5y()

        dr007 = self._get_dr007()
        if dr007 is None:
            signals_missing += 1

        credit_pulse = self._compute_credit_pulse(sf_growth)

        # Classify
        money_direction = self._classify_money(m1_m2_gap, dr007)
        credit_direction = self._classify_credit(sf_growth, credit_pulse)
        quadrant = self._to_quadrant(money_direction, credit_direction)

        # Confidence: reduce by 0.15 per missing signal
        confidence = max(0.3, 1.0 - signals_missing * 0.15)

        recommended, avoid = QUADRANT_SECTOR_MAP.get(
            quadrant, (["防御性消费", "现金"], ["券商", "周期"])
        )

        # Transition signals
        signals: list[str] = []
        if dr007 is not None and dr007 < self.POLICY_RATE - 0.1:
            signals.append("DR007低于政策利率，货币偏宽松")
        if dr007 is not None and dr007 > self.POLICY_RATE + 0.2:
            signals.append("DR007高于政策利率，货币偏紧")
        if m1_m2_gap is not None and m1_m2_gap > 3.0:
            signals.append("M1-M2剪刀差走阔，资金活化程度高")
        if m1_m2_gap is not None and m1_m2_gap < -2.0:
            signals.append("M1-M2剪刀差倒挂，资金沉淀严重")
        if sf_growth is not None and sf_growth > self.NOMINAL_GDP_GROWTH + 2:
            signals.append("社融增速显著高于名义GDP，信用扩张")
        if sf_growth is not None and sf_growth < self.NOMINAL_GDP_GROWTH - 1:
            signals.append("社融增速低于名义GDP，信用收缩")

        return MacroRegime(
            quadrant=quadrant,
            confidence=confidence,
            social_financing_growth=sf_growth,
            m1_m2_gap=m1_m2_gap,
            lpr_1y=lpr_1y,
            lpr_5y=lpr_5y,
            dr007=dr007,
            credit_pulse=credit_pulse,
            transition_signals=signals,
            recommended_sectors=recommended,
            avoid_sectors=avoid,
        )

    def get_regime_adjustments(self) -> RegimeAdjustments:
        """返回当前宏观象限对各诊断维度的权重调整系数。

        这是重构管道的核心方法——宏观象限判定先于一切，
        其输出直接调整下游 diagnosis / verdict / positioning 的权重。
        """
        regime = self.analyze()
        defaults = _QUADRANT_ADJUSTMENTS.get(regime.quadrant, {})
        recommended, avoid = QUADRANT_SECTOR_MAP.get(
            regime.quadrant, (["防御性消费", "现金"], ["券商", "周期"])
        )
        return RegimeAdjustments(
            quadrant=regime.quadrant,
            value_weight=defaults.get("value_weight", 1.0),
            quality_weight=defaults.get("quality_weight", 1.0),
            momentum_weight=defaults.get("momentum_weight", 1.0),
            growth_weight=defaults.get("growth_weight", 1.0),
            macro_weight=defaults.get("macro_weight", 1.0),
            sentiment_weight=defaults.get("sentiment_weight", 1.0),
            position_cap=defaults.get("position_cap", 0.20),
            max_total_position=defaults.get("max_total_position", 0.80),
            sector_favor=recommended,
            sector_avoid=avoid,
            style_preference=defaults.get("style_preference", "balanced"),
            aggressiveness=defaults.get("aggressiveness", 0.5),
        )

    def get_sector_recommendations(self) -> tuple[list[str], list[str]]:
        """Return (recommended, avoid) sector lists for current regime."""
        regime = self.analyze()
        return regime.recommended_sectors, regime.avoid_sectors

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_money(
        m1_m2_gap: Optional[float], dr007: Optional[float]
    ) -> str:
        """Classify monetary policy direction: 'easy', 'tight', 'neutral'."""
        easy_signals = 0
        tight_signals = 0

        if m1_m2_gap is not None:
            if m1_m2_gap > 0:
                easy_signals += 1  # M1 faster than M2 → money circulating
            elif m1_m2_gap < -3.0:
                tight_signals += 1

        if dr007 is not None:
            policy_rate = MonetaryCreditAnalyzer.POLICY_RATE
            if dr007 < policy_rate - 0.05:
                easy_signals += 1
            elif dr007 > policy_rate + 0.15:
                tight_signals += 1

        if easy_signals > tight_signals:
            return "easy"
        elif tight_signals > easy_signals:
            return "tight"
        return "neutral"

    @staticmethod
    def _classify_credit(
        sf_growth: Optional[float], credit_pulse: Optional[float]
    ) -> str:
        """Classify credit policy direction: 'easy', 'tight', 'neutral'."""
        easy_signals = 0
        tight_signals = 0

        if sf_growth is not None:
            nominal_gdp = MonetaryCreditAnalyzer.NOMINAL_GDP_GROWTH
            if sf_growth > nominal_gdp + 1.5:
                easy_signals += 1
            elif sf_growth < nominal_gdp - 0.5:
                tight_signals += 1

        if credit_pulse is not None:
            if credit_pulse > 0.2:
                easy_signals += 1
            elif credit_pulse < -0.2:
                tight_signals += 1

        if easy_signals > tight_signals:
            return "easy"
        elif tight_signals > easy_signals:
            return "tight"
        return "neutral"

    @staticmethod
    def _to_quadrant(money: str, credit: str) -> Quadrant:
        if money == "easy" and credit == "easy":
            return Quadrant.EASY_MONEY_EASY_CREDIT
        elif money == "easy" and credit in ("tight", "neutral"):
            return Quadrant.EASY_MONEY_TIGHT_CREDIT
        elif money in ("tight", "neutral") and credit == "easy":
            return Quadrant.TIGHT_MONEY_EASY_CREDIT
        return Quadrant.TIGHT_MONEY_TIGHT_CREDIT

    @staticmethod
    def _compute_credit_pulse(sf_growth: Optional[float]) -> Optional[float]:
        """Credit pulse = (current SF growth - GDP growth) normalized."""
        if sf_growth is None:
            return None
        return sf_growth - MonetaryCreditAnalyzer.NOMINAL_GDP_GROWTH

    # ------------------------------------------------------------------
    # Data fetching (AKShare + Guosen fallback)
    # ------------------------------------------------------------------

    def _get_social_financing_growth(self) -> Optional[float]:
        """Fetch 社融同比增速 via AKShare → 东财直连 → 国信。

        三层降级：AKShare → 东方财富API → 国信券商API
        对 AKShare 的 SSL 错误做降级重试（商务部网站 TLS 过时）。
        """
        cache_key = "sf_growth"
        # 检查缓存（实例级 + 静态 fallback）
        cached = self._cache_get(cache_key)
        if cached is None:
            cached = MonetaryCreditAnalyzer._cache_get_static(cache_key)
        if cached is not None:
            return cached

        # 1. 尝试 AKShare（带 SSL 降级重试）
        val = self._try_akshare_sf(cache_key)
        if val is not None:
            return val

        # 2. 尝试东方财富直连
        val = self._try_eastmoney_sf(cache_key)
        if val is not None:
            return val

        # 3. Fallback: 国信券商 API
        val = self._query_guosen("社会融资规模增速")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    @staticmethod
    def _try_akshare_sf(cache_key: str) -> Optional[float]:
        """通过 AKShare 获取社融数据，SSL 错误时降级重试。"""
        try:
            import akshare as ak
            df = ak.macro_china_shrzgm()
            if df is not None and len(df) > 0:
                for col in ["社会融资规模存量同比增长", "社融存量同比", "同比增长"]:
                    if col in df.columns:
                        val = float(df[col].iloc[-1])
                        MonetaryCreditAnalyzer._cache_set_static(cache_key, val)
                        return val
        except Exception as e:
            err = str(e)
            # SSL 错误 → 降级重试（商务部服务器 TLS 1.0/1.1）
            if "SSL" in err or "Cipher" in err or "cipher" in err or "handshake" in err.lower():
                try:
                    return MonetaryCreditAnalyzer._try_akshare_sf_legacy_tls(cache_key)
                except Exception as e2:
                    logger.debug("AKShare SF legacy TLS retry also failed: %s", e2)
            else:
                logger.debug("AKShare SF fetch failed: %s", e)
        return None

    @staticmethod
    def _try_akshare_sf_legacy_tls(cache_key: str) -> Optional[float]:
        """绕过 AKShare 直连商务部 API 获取社融月度增量。

        data.mofcom.gov.cn 使用过时的 TLS / 密码套件，
        用 urllib + 宽松 SSL 上下文 + POST 直接获取 JSON。
        按月增量计算近 12 个月累计 → 同比增速。
        """
        import json
        import ssl
        import urllib.request

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        ctx.set_ciphers("ALL:COMPLEMENTOFALL")

        body = json.dumps({"pageSize": 24, "pageNumber": 1}).encode()
        req = urllib.request.Request(
            "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery",
            data=body,
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "User-Agent": "Mozilla/5.0",
            },
        )

        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, context=ctx, timeout=20) as resp:
                rows = json.loads(resp.read())
        except Exception as exc:
            logger.debug("Direct mofcom SF query failed: %s", exc)
            return None

        if not rows or not isinstance(rows, list):
            return None

        # rows 按 date (YYYYMM) 降序。tiosfs = 社会融资规模当月增量(亿元)
        # 计算近 12 个月累计同比增速
        # (最近12个月累计 / 去年同期12个月累计 - 1) × 100
        current_year_total = 0.0
        prev_year_total = 0.0
        latest_date = rows[0].get("date", "")

        for row in rows:
            d = row.get("date", "")
            val = row.get("tiosfs")
            if val is None:
                continue
            try:
                val_f = float(val)
            except (TypeError, ValueError):
                continue

            if not d or len(d) < 6:
                continue

            year = int(d[:4])
            month = int(d[4:6])
            latest_year = int(latest_date[:4]) if latest_date else 0
            latest_month = int(latest_date[4:6]) if latest_date else 0

            # 同月对比：当前年 vs 去年
            if year == latest_year and month <= latest_month:
                current_year_total += val_f
            elif year == latest_year - 1 and month <= latest_month:
                prev_year_total += val_f

        if prev_year_total > 0 and current_year_total > 0:
            yoy_growth = (current_year_total / prev_year_total - 1.0) * 100.0
            MonetaryCreditAnalyzer._cache_set_static(cache_key, yoy_growth)
            logger.info("社融增速 via mofcom 直连: %.2f%% (累计 %d月)", yoy_growth, latest_month)
            return yoy_growth

        # fallback: 如果累计对比不够，用最新月单月对比
        if len(rows) >= 13:
            try:
                current_month = float(rows[0].get("tiosfs", 0) or 0)
                prev_year_month = float(rows[12].get("tiosfs", 0) or 0)
                if prev_year_month > 0:
                    yoy = (current_month / prev_year_month - 1.0) * 100.0
                    MonetaryCreditAnalyzer._cache_set_static(cache_key, yoy)
                    logger.info("社融增速 via mofcom (单月同比): %.2f%%", yoy)
                    return yoy
            except (TypeError, ValueError, IndexError):
                pass

        return None

    @staticmethod
    def _try_eastmoney_sf(cache_key: str) -> Optional[float]:
        """通过东方财富 API 获取社融数据。"""
        try:
            import requests
            url = (
                "https://datacenter-web.eastmoney.com/api/data/v1/get"
                "?reportName=RPT_ECONOMY_SOCIAL_FINANCING"
                "&columns=REPORT_DATE,INDICATOR_NAME,ACTUAL"
                "&sortColumns=REPORT_DATE&sortTypes=-1"
                "&pageSize=10&pageNumber=1&source=WEB&client=WEB"
            )
            r = requests.get(url, timeout=15, proxies={"http": None, "https": None})
            if r.status_code == 200:
                data = r.json()
                if data.get("success") and data.get("result", {}).get("data"):
                    rows = data["result"]["data"]
                    # 找最新一条包含"同比"或"增速"的指标
                    for row in rows:
                        name = row.get("INDICATOR_NAME", "")
                        if "同比" in name or "增速" in name:
                            val = float(row["ACTUAL"])
                            MonetaryCreditAnalyzer._cache_set_static(cache_key, val)
                            logger.info("社融增速 via 东财: %.2f%%", val)
                            return val
        except Exception as e:
            logger.debug("Eastmoney SF fetch failed: %s", e)
        return None

    @staticmethod
    def _cache_set_static(cache_key: str, val: float) -> None:
        """静态缓存写入（供 static 方法使用）。"""
        # 通过 MonetaryCreditAnalyzer 实例的缓存机制
        # 这里简化：直接存类级别 dict
        if not hasattr(MonetaryCreditAnalyzer, "_static_cache"):
            MonetaryCreditAnalyzer._static_cache = {}
        MonetaryCreditAnalyzer._static_cache[cache_key] = val

    @staticmethod
    def _cache_get_static(cache_key: str) -> Optional[float]:
        if hasattr(MonetaryCreditAnalyzer, "_static_cache"):
            return MonetaryCreditAnalyzer._static_cache.get(cache_key)
        return None

    def _get_m1_m2_gap(self) -> Optional[float]:
        """Fetch M1-M2剪刀差 via AKShare."""
        cache_key = "m1_m2_gap"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.macro_china_money_supply()
            if df is not None and len(df) > 0:
                m1_col = None
                m2_col = None
                for col in df.columns:
                    if "m1" in col.lower() and "同比" in col:
                        m1_col = col
                    if "m2" in col.lower() and "同比" in col:
                        m2_col = col
                if m1_col and m2_col:
                    m1 = float(df[m1_col].iloc[-1])
                    m2 = float(df[m2_col].iloc[-1])
                    gap = m1 - m2
                    self._cache_set(cache_key, gap)
                    return gap
        except Exception as e:
            logger.warning("AKShare money supply fetch failed: %s", e)

        val = self._query_guosen("M1 M2 剪刀差")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_lpr_1y(self) -> Optional[float]:
        """Fetch 1Y LPR."""
        return self._get_lpr("1Y")

    def _get_lpr_5y(self) -> Optional[float]:
        """Fetch 5Y LPR."""
        return self._get_lpr("5Y")

    def _get_lpr(self, tenor: str) -> Optional[float]:
        cache_key = f"lpr_{tenor}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.macro_china_lpr()
            if df is not None and len(df) > 0:
                col_map = {"1Y": ["1年期", "一年期", "LPR1Y"], "5Y": ["5年期", "五年期", "LPR5Y"]}
                for col_hint in col_map.get(tenor, []):
                    for col in df.columns:
                        if col_hint in str(col):
                            val = float(df[col].iloc[-1])
                            self._cache_set(cache_key, val)
                            return val
        except Exception as e:
            logger.warning("AKShare LPR fetch failed: %s", e)

        val = self._query_guosen(f"LPR {tenor}")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_dr007(self) -> Optional[float]:
        """Fetch DR007 (存款类机构7天质押式回购利率)."""
        cache_key = "dr007"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            # Try bond repo rate
            df = ak.bond_repo_daily_report()
            if df is not None and len(df) > 0:
                # Look for DR007 weighted rate
                for col in df.columns:
                    if "DR007" in str(col) or "存款类机构" in str(col):
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception:
            pass

        # Try alternative: SHIBOR 7-day as proxy for DR007
        try:
            import akshare as ak
            df = ak.rate_interbank()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "7天" in str(col) or "7D" in str(col).upper():
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare DR007 fetch failed: %s", e)

        val = self._query_guosen("DR007 存款类机构7天质押式回购利率")
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
        # Match patterns like "8.5%", "同比增长 8.5", "为 8.5"
        patterns = [
            r"([\d.]+)\s*%",  # percentage
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
