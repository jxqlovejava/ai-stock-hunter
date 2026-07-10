"""互动易 (Investor Relationship Management) — investor Q&A analysis.

Unique alpha source: how companies respond to investor questions about policy,
rumors, and market events. No other quant tool has this data.

Feeds into diagnosis as investor_sentiment dimension.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass
class IrmQuestion:
    """Single investor Q&A item."""
    code: str = ""
    company: str = ""
    question: str = ""
    answer: Optional[str] = None   # None = 未回复
    answerer: str = ""
    ask_time: str = ""


@dataclass
class IrmAnalysis:
    """互动易分析结果 — feeds into diagnosis."""
    symbol: str
    total_questions: int = 0
    answered_count: int = 0
    reply_rate: float = 0.0
    # Sentiment
    investor_sentiment_score: float = 0.0       # -1.0 to 1.0 (bullish→bearish questions)
    company_tone_score: float = 0.0             # -1.0 to 1.0 (evasive→confident replies)
    # Topic detection
    hot_topics: list[str] = field(default_factory=list)  # Frequently asked topics
    policy_mentions: list[str] = field(default_factory=list)  # Policy-related questions
    # Alpha signals
    has_rumor_response: bool = False            # Company addressing market rumors
    has_policy_response: bool = False           # Company addressing policy impact
    recent_questions: list[dict] = field(default_factory=list)  # Last 5 Q&A for inspection
    updated_at: datetime = field(default_factory=datetime.now)


class IrmAnalyzer:
    """Fetch and analyze 互动易 investor Q&A for a stock."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, IrmAnalysis]] = {}
        self._cache_ttl = timedelta(hours=6)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, symbol: str, as_of_date: str = "") -> IrmAnalysis:
        """Fetch and analyze investor Q&A for a stock.

        as_of_date: 历史回测日期 (YYYY-MM-DD)，只统计该日期之前的提问。
                    巨潮仅保留约4个月数据，超过此范围可能返回空结果。
        """
        cache_key = f"irm:{symbol}:{as_of_date}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        analysis = IrmAnalysis(symbol=symbol)

        # Fetch questions (支持历史日期过滤)
        questions = self._fetch_questions(symbol, as_of_date=as_of_date)
        if not questions:
            if as_of_date:
                logger.info(
                    "互动易 %s as_of=%s: 无历史数据 (cninfo仅保留~4个月)",
                    symbol, as_of_date,
                )
            self._cache_set(cache_key, analysis)
            return analysis

        analysis.total_questions = len(questions)
        answered = [q for q in questions if q.answer]
        analysis.answered_count = len(answered)
        analysis.reply_rate = analysis.answered_count / max(analysis.total_questions, 1)

        # Sentiment analysis
        analysis.investor_sentiment_score = self._score_investor_sentiment(questions)
        analysis.company_tone_score = self._score_company_tone(answered)

        # Topic detection
        all_text = " ".join([q.question for q in questions])
        analysis.hot_topics = self._detect_topics(all_text)
        analysis.policy_mentions = self._detect_policy_mentions(all_text)

        # Alpha signals
        analysis.has_rumor_response = self._detect_rumor_response(answered)
        analysis.has_policy_response = len(analysis.policy_mentions) > 0 and analysis.answered_count > 0

        # Recent Q&A
        analysis.recent_questions = [
            {"q": q.question[:100], "a": (q.answer or "")[:100] if q.answer else "未回复",
             "time": q.ask_time}
            for q in questions[:5]
        ]

        self._cache_set(cache_key, analysis)
        return analysis

    def get_l1_score(self, symbol: str) -> dict:
        """Get diagnosis-relevant scores from 互动易 analysis.

        Returns dict suitable for injecting into DiagnosisEngine:
            investor_attention: 0-100 (higher = more investor engagement)
            transparency_score: 0-100 (higher = better reply rate + tone)
            policy_awareness: 0-100 (higher = company actively addressing policy)
            rumor_flag: bool (company responding to rumors = potential catalyst)
        """
        a = self.analyze(symbol)

        # Investor attention: more questions = more market interest
        attention = min(100, a.total_questions * 5)

        # Transparency: reply rate + confident tone
        transparency = int(
            a.reply_rate * 50 + (a.company_tone_score + 1.0) * 25
        )

        # Policy awareness
        policy_score = min(100, len(a.policy_mentions) * 20)

        return {
            "investor_attention": attention,
            "transparency_score": transparency,
            "policy_awareness": policy_score,
            "rumor_flag": a.has_rumor_response,
        }

    # ------------------------------------------------------------------
    # Sentiment & Topic analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _score_investor_sentiment(questions: list[IrmQuestion]) -> float:
        """Score investor sentiment from question language. Negative = bearish questions."""
        bearish_kw = ["下跌", "暴跌", "亏损", "减持", "风险", "担心", "担忧", "质疑",
                       "造假", "退市", "ST", "跌停", "利空", "怎么办"]
        bullish_kw = ["增长", "看好", "扩产", "订单", "突破", "利好", "分红", "回购"]
        score = 0.0
        for q in questions:
            text = q.question
            for kw in bearish_kw:
                if kw in text:
                    score -= 0.15
            for kw in bullish_kw:
                if kw in text:
                    score += 0.10
        return max(-1.0, min(1.0, score / max(len(questions), 1) * 5))

    @staticmethod
    def _score_company_tone(answered: list[IrmQuestion]) -> float:
        """Score company reply tone. Positive = confident, transparent."""
        confident_kw = ["正常", "稳中向好", "持续增长", "符合预期", "合规", "有序推进",
                         "感谢关注", "不存在", "未受到影响", "严格", "积极"]
        evasive_kw = ["不便透露", "以公告为准", "请关注公告", "无法回答", "暂不",
                       "涉及商业秘密", "后续关注", "尚在"]
        if not answered:
            return 0.0
        score = 0.0
        for q in answered:
            text = q.answer or ""
            for kw in confident_kw:
                if kw in text:
                    score += 0.12
            for kw in evasive_kw:
                if kw in text:
                    score -= 0.20
        return max(-1.0, min(1.0, score / max(len(answered), 1) * 3))

    @staticmethod
    def _detect_topics(text: str) -> list[str]:
        """Detect frequently discussed topics in investor questions."""
        topic_kw = {
            "业绩": ["业绩", "利润", "营收", "盈利"],
            "分红": ["分红", "派息", "送股"],
            "股价": ["股价", "涨", "跌", "市值"],
            "订单": ["订单", "产能", "扩产", "投产"],
            "研发": ["研发", "技术", "专利", "突破"],
            "政策": ["政策", "补贴", "监管", "审批"],
            "竞争": ["竞争", "对手", "市场份额"],
            "减持": ["减持", "套现", "解禁"],
            "并购": ["收购", "并购", "重组", "资产"],
            "AI": ["AI", "人工智能", "大模型", "算力"],
        }
        found = []
        for topic, keywords in topic_kw.items():
            if any(kw in text for kw in keywords):
                found.append(topic)
        return found

    @staticmethod
    def _detect_policy_mentions(text: str) -> list[str]:
        """Detect policy-related investor questions."""
        policy_kw = ["政策", "监管", "补贴", "关税", "制裁", "反垄断",
                      "碳中和", "国产替代", "信创", "安全审查"]
        return [kw for kw in policy_kw if kw in text]

    @staticmethod
    def _detect_rumor_response(answered: list[IrmQuestion]) -> bool:
        """Check if company is responding to market rumors."""
        rumor_kw = ["传闻", "传言", "谣言", "不实", "澄清", "说明", "声明"]
        for q in answered:
            text = (q.answer or "") + q.question
            if any(kw in text for kw in rumor_kw):
                return True
        return False

    # ------------------------------------------------------------------
    # Data fetching — 巨潮互动易
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_questions(
        symbol: str, page_size: int = 50, as_of_date: str = "",
    ) -> list[IrmQuestion]:
        """Fetch investor Q&A from 巨潮互动易 API。

        as_of_date: 历史回测日期 (YYYY-MM-DD)，翻页拉取全部数据后客户端按 pubDate 过滤。
                    巨潮仅保留约 4 个月数据，超过此范围的日期将返回空列表。
        """
        try:
            import requests
            from datetime import datetime as _dt

            as_of_dt = None
            if as_of_date:
                try:
                    as_of_dt = _dt.strptime(as_of_date, "%Y-%m-%d")
                except ValueError:
                    pass

            # Step 1: get orgId
            r1 = requests.post(
                "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
                data={"keyWord": symbol},
                headers={"User-Agent": UA},
                timeout=10,
            )
            d1 = r1.json().get("data") or []
            if not d1:
                return []
            org_id = d1[0].get("secid")

            # Step 2: 翻页拉取全部提问，支持 as_of 日期过滤
            all_rows = []
            page = 1
            total = 0
            while True:
                params = {
                    "_t": 1, "stockcode": symbol, "orgId": org_id,
                    "pageSize": page_size, "pageNum": page,
                    "keyWord": "", "startDay": "", "endDay": "",
                }
                r2 = requests.post(
                    "https://irm.cninfo.com.cn/newircs/company/question",
                    params=params,
                    headers={"User-Agent": UA},
                    timeout=10,
                )
                data = r2.json()
                rows = data.get("rows") or []
                if not rows:
                    break
                # 客户端日期过滤
                for it in rows:
                    pd_ts = it.get("pubDate")
                    if pd_ts and as_of_dt:
                        try:
                            q_dt = _dt.fromtimestamp(pd_ts / 1000)
                            if q_dt > as_of_dt:
                                continue  # 跳过 as_of 之后的提问
                        except Exception:
                            pass
                    all_rows.append(it)
                if total == 0:
                    total = data.get("total", len(rows))
                page += 1
                if len(all_rows) >= total:
                    break
                time.sleep(0.1)  # 翻页间隔，避免触发限流

            questions = []
            for it in all_rows:
                pd_ts = it.get("pubDate")
                ask_time = ""
                if pd_ts:
                    try:
                        ask_time = datetime.fromtimestamp(pd_ts / 1000).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        ask_time = str(pd_ts)[:10]

                questions.append(IrmQuestion(
                    code=it.get("stockCode", symbol),
                    company=it.get("companyShortName", ""),
                    question=it.get("mainContent", ""),
                    answer=it.get("attachedContent"),
                    answerer=it.get("attachedAuthor", ""),
                    ask_time=ask_time,
                ))
            return questions
        except Exception as e:
            logger.debug("互动易 fetch failed for %s: %s", symbol, e)
            return []

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[IrmAnalysis]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._cache_ttl:
            return val
        del self._cache[key]
        return None

    def _cache_set(self, key: str, val: IrmAnalysis):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()
