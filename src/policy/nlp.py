"""Dynamic policy NLP engine — Huatai market_insight() primary, keyword fallback.

Huatai returns structured JSON with pre-analyzed policy sections —
we parse it directly. KeywordNLPProcessor is fallback only.

Guosen get_macro() was tested 2026-07-04 and confirmed dead (all queries return None).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PolicyAnalysis:
    source: str = ""  # "政治局会议" / "国常会" / "央行货币政策报告"
    raw_text: str = ""
    sentiment_score: float = 0.0  # -1.0 to 1.0
    urgency_level: str = "LOW"  # LOW / MEDIUM / HIGH / CRITICAL
    affected_sectors: list[tuple[str, float]] = field(default_factory=list)
    affected_sectors_neg: list[tuple[str, float]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    policy_cycle_phase: str = "中性"  # "宽松" / "收紧" / "中性" / "结构性"
    # Huatai-specific structured fields
    sections: dict[str, str] = field(default_factory=dict)  # e.g. {"宏观影响": "...", "微观影响": "..."}
    huatai_raw_json: str = ""  # cached original JSON for debugging
    created_at: datetime = field(default_factory=datetime.now)


# Pre-built policy queries tuned for Huatai market_insight()
POLICY_QUERIES = {
    "政治局会议": "最近政治局会议关于经济的最新部署",
    "国常会": "最近国务院常务会议关于经济和产业政策的决定",
    "央行货币政策报告": "央行最新货币政策方向",
    "中央经济工作会议": "中央经济工作会议最新精神",
    "产业政策": "近期重大产业政策",
}


class PolicyNlpEngine:
    """Fetches policy text from HuataiProvider.market_insight() and parses structured output.

    Primary path: Huatai JSON → parse sections → extract sectors/keywords/sentiment
    Fallback path: raw text → KeywordNLPProcessor (only if Huatai unavailable)
    """

    def __init__(self):
        self._cache: dict[str, tuple[datetime, PolicyAnalysis]] = {}
        self._cache_ttl = timedelta(hours=4)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, query: str, source: str = "custom") -> Optional[PolicyAnalysis]:
        """Fetch and analyze policy text for a given query."""
        cache_key = f"policy:{source}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Primary: Huatai structured JSON
        analysis = self._fetch_and_parse_huatai(query, source)
        if analysis is not None:
            self._cache_set(cache_key, analysis)
            return analysis

        # Fallback: raw text → KeywordNLPProcessor
        raw_text = self._fetch_policy_text_raw(query)
        if raw_text:
            analysis = self._analyze_text_fallback(raw_text, source)
            if analysis:
                self._cache_set(cache_key, analysis)
            return analysis

        logger.debug("No policy text returned for query: %s", query)
        return None

    def analyze_policy_meeting(self) -> Optional[PolicyAnalysis]:
        return self.analyze(POLICY_QUERIES.get("政治局会议", "最近政治局会议关于经济的最新部署"),
                            source="政治局会议")

    def analyze_state_council(self) -> Optional[PolicyAnalysis]:
        return self.analyze(POLICY_QUERIES.get("国常会", "最近国务院常务会议关于经济和产业政策的决定"),
                            source="国常会")

    def analyze_pbo_report(self) -> Optional[PolicyAnalysis]:
        return self.analyze(POLICY_QUERIES.get("央行货币政策报告", "央行最新货币政策方向"),
                            source="央行货币政策报告")

    def analyze_industrial_policy(self) -> Optional[PolicyAnalysis]:
        return self.analyze(POLICY_QUERIES.get("产业政策", "近期重大产业政策"),
                            source="产业政策")

    def analyze_all(self) -> list[PolicyAnalysis]:
        results = []
        methods = [
            self.analyze_policy_meeting,
            self.analyze_state_council,
            self.analyze_pbo_report,
            self.analyze_industrial_policy,
        ]
        for method in methods:
            try:
                result = method()
                if result is not None:
                    results.append(result)
            except Exception as e:
                logger.warning("Policy analysis method failed: %s", e)
        return results

    # ------------------------------------------------------------------
    # Primary path: Huatai structured JSON → PolicyAnalysis
    # ------------------------------------------------------------------

    def _fetch_and_parse_huatai(self, query: str, source: str) -> Optional[PolicyAnalysis]:
        """Fetch from Huatai market_insight() and parse structured JSON answer."""
        raw_json = self._fetch_huatai_raw(query)
        if not raw_json:
            return None

        try:
            data = json.loads(raw_json)
            if not data.get("ok"):
                logger.debug("Huatai returned ok=false for query: %s", query)
                return None
            answer = data.get("data", {}).get("answer", "")
            if not answer:
                return None
        except json.JSONDecodeError:
            # Not JSON, treat as raw text fallback
            return None

        analysis = PolicyAnalysis(source=source, raw_text=answer, huatai_raw_json=raw_json)

        # Parse sections from structured markdown
        analysis.sections = self._parse_sections(answer)

        # Extract keywords from the full answer text
        analysis.keywords = self._extract_policy_keywords(answer)

        # Sentiment: based on policy language in answer
        analysis.sentiment_score = self._basic_sentiment(answer)

        # Urgency
        analysis.urgency_level = self._to_urgency(analysis.sentiment_score)

        # Sector mapping: scan answer against KEYWORD_MAP
        analysis.affected_sectors, analysis.affected_sectors_neg = self._map_sectors(
            answer, analysis.keywords
        )

        # Policy cycle phase
        analysis.policy_cycle_phase = self._detect_cycle_phase(answer)

        return analysis

    @staticmethod
    def _parse_sections(text: str) -> dict[str, str]:
        """Parse Huatai-style markdown sections into dict.

        Huatai output uses patterns like:
          # 一、经济形势研判
          content...
          # 二、具体政策部署
          content...
        """
        sections: dict[str, str] = {}
        # Match headings like "# 一、..." or "## 1. ..."
        pattern = r"(?:^|\n)(#{1,3}\s*(?:[一二三四五六七八九十\d]+[、.]?\s*)?[^\n]+)\n"
        matches = list(re.finditer(pattern, text))

        for i, m in enumerate(matches):
            title = m.group(1).lstrip("#").strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections[title] = text[start:end].strip()

        # If no structured headings found, store entire text under "全文"
        if not sections:
            sections["全文"] = text

        return sections

    # ------------------------------------------------------------------
    # Fallback path: raw unstructured text → KeywordNLPProcessor
    # ------------------------------------------------------------------

    def _analyze_text_fallback(self, raw_text: str, source: str) -> PolicyAnalysis:
        """Run KeywordNLPProcessor on raw text (only when Huatai is unavailable)."""
        analysis = PolicyAnalysis(source=source, raw_text=raw_text)

        try:
            from src.information.nlp import KeywordNLPProcessor
            from src.information.schema import RawItem, SourceType

            processor = KeywordNLPProcessor()
            item = RawItem(
                source_type=SourceType.POLICY,
                platform=source,
                title=source,
                content=raw_text[:2000],
                url="",
                author="",
                published_at=datetime.now(),
            )
            processed = processor.analyze_item(item, topic_context={})
            analysis.sentiment_score = processed.sentiment_score
            analysis.keywords = processed.keywords
        except Exception as e:
            logger.warning("KeywordNLPProcessor fallback failed: %s, using basic analysis", e)
            analysis.sentiment_score = self._basic_sentiment(raw_text)
            analysis.keywords = self._extract_policy_keywords(raw_text)

        analysis.urgency_level = self._to_urgency(analysis.sentiment_score)
        analysis.affected_sectors, analysis.affected_sectors_neg = self._map_sectors(
            raw_text, analysis.keywords
        )
        analysis.policy_cycle_phase = self._detect_cycle_phase(raw_text)
        return analysis

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_huatai_raw(query: str) -> Optional[str]:
        """Fetch raw JSON from Huatai market_insight()."""
        try:
            from src.data.huatai import HuataiProvider
            ht = HuataiProvider()
            if not ht.available:
                logger.debug("Huatai not available")
                return None
            return ht.market_insight(query)
        except Exception as e:
            logger.debug("Huatai fetch failed for '%s': %s", query, e)
        return None

    @staticmethod
    def _fetch_policy_text_raw(query: str) -> str:
        """Fallback: try alternative sources for raw policy text.

        Guosen get_macro() was tested dead 2026-07-04 — removed.
        Only Huatai and potentially last30days-cn remain as sources.
        """
        texts: list[str] = []

        # Huatai (retry even if JSON parse failed earlier — might return non-JSON)
        try:
            from src.data.huatai import HuataiProvider
            ht = HuataiProvider()
            if ht.available:
                insight = ht.market_insight(query)
                if insight:
                    texts.append(insight)
        except Exception:
            pass

        return "\n\n".join(texts) if texts else ""

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _basic_sentiment(text: str) -> float:
        """Simple sentiment based on policy language presence."""
        easing_kw = ["降准", "降息", "宽松", "稳健偏松", "适度宽松", "积极", "加大力度",
                      "减税降费", "扩内需", "促消费", "稳增长", "逆周期调节", "更加积极有为",
                      "精准落实", "加力", "兜牢", "净投放"]
        tightening_kw = ["收紧", "去杠杆", "防风险", "抑制", "调控", "紧缩",
                          "稳健偏紧", "从严", "监管加强", "规范", "缩量", "回笼"]
        score = 0.0
        for kw in easing_kw:
            if kw in text:
                score += 0.08
        for kw in tightening_kw:
            if kw in text:
                score -= 0.10
        return max(-1.0, min(1.0, score))

    @staticmethod
    def _extract_policy_keywords(text: str) -> list[str]:
        """Extract policy-relevant keywords from text."""
        all_kw = [
            "降准", "降息", "LPR", "社融", "M2", "信贷", "利率", "汇率",
            "财政赤字", "专项债", "特别国债", "超长期特别国债", "减税", "基建", "新基建",
            "房地产", "房住不炒", "保交楼", "数字经济", "人工智能", "工业互联网",
            "碳中和", "碳达峰", "新能源", "芯片", "半导体", "国产替代",
            "注册制", "退市", "上市公司质量", "分红", "回购",
            "适度宽松", "积极财政", "逆周期", "稳就业", "稳市场",
            "买断式逆回购", "MLF", "PSL", "SLF", "DR007",
            "循环经济", "美丽中国", "城市更新",
        ]
        return [kw for kw in all_kw if kw in text]

    @staticmethod
    def _to_urgency(score: float) -> str:
        if abs(score) > 0.6:
            return "HIGH"
        elif abs(score) > 0.3:
            return "MEDIUM"
        return "LOW"

    def _map_sectors(
        self, text: str, keywords: list[str]
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        """Map policy keywords to affected sectors using PolicyTracker.KEYWORD_MAP."""
        try:
            from src.policy.tracker import PolicyTracker
            tracker = PolicyTracker()
            signals = tracker.scan(text, source="policy_nlp")

            pos_sectors: list[tuple[str, float]] = []
            neg_sectors: list[tuple[str, float]] = []
            for signal in signals:
                for s in signal.affected_sectors:
                    weight = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.3}.get(
                        signal.impact_level, 0.3
                    )
                    pos_sectors.append((s, weight))
                for s in signal.affected_sectors_neg:
                    weight = {"CRITICAL": 0.9, "HIGH": 0.7, "MEDIUM": 0.5, "LOW": 0.3}.get(
                        signal.impact_level, 0.3
                    )
                    neg_sectors.append((s, weight))
            return pos_sectors, neg_sectors
        except Exception as e:
            logger.debug("Sector mapping failed: %s", e)

        # Fallback: basic keyword-to-sector mapping
        pos: list[tuple[str, float]] = []
        neg: list[tuple[str, float]] = []
        sector_map = {
            "降准": (["银行", "地产"], []),
            "降息": (["地产", "券商"], []),
            "专项债": (["基建", "建材"], []),
            "新基建": (["5G", "数据中心", "新能源"], []),
            "碳中和": (["新能源", "光伏"], []),
            "芯片": (["半导体", "集成电路"], []),
            "人工智能": (["AI", "信创"], []),
            "工业互联网": (["工业互联网", "智能制造"], []),
            "循环经济": (["环保", "再生资源"], []),
            "美丽中国": (["环保", "新能源", "绿色工厂"], []),
            "医药集采": ([], ["医药", "医疗器械"]),
            "退市新规": ([], ["ST板块"]),
            "房地产调控": ([], ["地产"]),
        }
        for kw, (pos_sec, neg_sec) in sector_map.items():
            if kw in text:
                pos.extend((s, 0.5) for s in pos_sec)
                neg.extend((s, 0.5) for s in neg_sec)
        return pos, neg

    @staticmethod
    def _detect_cycle_phase(text: str) -> str:
        """Detect policy cycle phase from text."""
        has_structural = any(kw in text for kw in ["结构性", "精准滴灌", "定向降准", "定向支持"])
        has_easing = any(kw in text for kw in ["降准", "降息", "适度宽松", "积极财政",
                                                 "加大逆周期调节", "更加积极有为", "净投放"])
        has_tightening = any(kw in text for kw in ["去杠杆", "防风险", "收紧", "抑制过热",
                                                     "缩量", "回笼"])

        if has_structural and has_easing:
            return "结构性"
        if has_tightening:
            return "收紧"
        if has_easing:
            return "宽松"
        if has_structural:
            return "结构性"
        return "中性"

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[PolicyAnalysis]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._cache_ttl:
            return val
        del self._cache[key]
        return None

    def _cache_set(self, key: str, val: PolicyAnalysis) -> None:
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self) -> None:
        self._cache.clear()
