"""大宗交易 (Block Trade) 分析 — 机构大额场外交易信号检测。

大宗交易指单笔交易 ≥30 万股 / ≥200 万元，通过场外协议成交，不影响盘中价格。
核心信号: 溢价/折价方向、机构接盘识别、连续大宗跟踪、成交额占比评估。

数据源: AKShare stock_dzjy_mrmx (东财 datacenter RPT_DATA_BLOCKTRADE)。
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BlockTradeRecord:
    """单笔大宗交易记录。"""

    trade_date: str = ""  # YYYY-MM-DD
    symbol: str = ""  # 证券代码
    name: str = ""  # 证券简称
    close_price: float = 0.0  # 当日收盘价
    deal_price: float = 0.0  # 大宗成交价
    premium_ratio: float = 0.0  # 折溢率 (正=溢价, 负=折价)
    volume: int = 0  # 成交量 (股)
    amount: float = 0.0  # 成交额 (元)
    turnover_ratio: float = 0.0  # 成交额/流通市值
    buyer: str = ""  # 买方营业部
    seller: str = ""  # 卖方营业部
    is_institution_buy: bool = False  # 买方是否为机构专用
    is_institution_sell: bool = False  # 卖方是否为机构专用


@dataclass
class BlockTradeProfile:
    """大宗交易综合画像。"""

    # 市场级统计
    total_count: int = 0  # 当日大宗交易总笔数
    total_amount: float = 0.0  # 当日大宗交易总成交额 (亿元)
    premium_count: int = 0  # 溢价成交笔数
    discount_count: int = 0  # 折价成交笔数
    avg_premium_ratio: float = 0.0  # 平均折溢率 (%)

    # 机构行为
    institution_buy_count: int = 0  # 机构买入笔数
    institution_sell_count: int = 0  # 机构卖出笔数
    institution_net_direction: str = "neutral"  # "buying" / "selling" / "neutral"

    # 折溢价分布
    deep_discount_count: int = 0  # 深度折价 (≤-10%) 笔数 — 可能是减持出逃
    high_premium_count: int = 0  # 高溢价 (≥5%) 笔数 — 机构抢筹信号

    # 个股级 — 目标股票
    symbol_records: list[BlockTradeRecord] = field(default_factory=list)
    symbol_total_amount: float = 0.0  # 目标股票大宗成交额
    symbol_premium_avg: float = 0.0  # 目标股票平均折溢率
    symbol_consecutive_days: int = 0  # 连续出现大宗交易天数
    symbol_institution_buy: bool = False  # 目标股票是否有机构买入
    symbol_institution_sell: bool = False  # 目标股票是否有机构卖出

    # Composite signals
    signal: str = "neutral"  # "bullish" / "bearish" / "neutral"
    signal_detail: str = ""  # 一句话解读
    score: int = 50  # 0-100, higher = bullish block trade signal
    confidence: float = 0.5  # 0.0-1.0
    updated_at: datetime = field(default_factory=datetime.now)


class BlockTradeAnalyzer:
    """大宗交易分析器 — 检测机构大额场外资金动向。

    Primary: AKShare stock_dzjy_mrmx (东财 datacenter).
    Supports both market-level scan and single-symbol analysis.
    """

    # Thresholds
    PREMIUM_BULLISH = 3.0  # 溢价 ≥3% → bullish
    DISCOUNT_BEARISH = -7.0  # 折价 ≤-7% → bearish (大股东减持常用折价出货)
    DEEP_DISCOUNT_THRESHOLD = -10.0  # 深度折价 — 警惕减持
    HIGH_PREMIUM_THRESHOLD = 5.0  # 高溢价 — 机构抢筹
    INSTITUTION_KEYWORDS = ("机构专用", "机构", "QFII", "社保", "保险", "年金")
    CONSECUTIVE_DAYS_THRESHOLD = 3  # 连续 ≥3 天出现 → 持续建仓/出货
    TURNOVER_HIGH = 1.0  # 成交额/流通市值 ≥1% → 显著
    LOOKBACK_DAYS = 5  # 历史回溯天数

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=30)  # 大宗数据 T+0 盘后更新，30min 合理

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, symbol: Optional[str] = None) -> BlockTradeProfile:
        """获取大宗交易数据并计算综合信号。

        Args:
            symbol: 可选，指定股票代码（如 "000066"）时额外输出个股级分析。
        """
        records = self._fetch_daily_records()
        if not records:
            return BlockTradeProfile(confidence=0.0)

        profile = self._build_market_profile(records)

        # 个股级分析
        if symbol:
            self._attach_symbol_analysis(profile, records, symbol)

        # 分类信号
        profile.signal, profile.signal_detail = self._classify_signal(profile)
        profile.score = self._compute_score(profile)
        profile.confidence = self._compute_confidence(profile)

        return profile

    def analyze_symbol(self, symbol: str) -> BlockTradeProfile:
        """仅分析单只股票的大宗交易信号。"""
        return self.analyze(symbol=symbol)

    def get_institution_flow_direction(self) -> dict:
        """快速获取当日机构大宗交易净方向（供 Phase 3 快速注入）。"""
        cache_key = "institution_flow"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        records = self._fetch_daily_records()
        if not records:
            return {"direction": "neutral", "net_count": 0, "premium_buy_pct": 0.0}

        inst_buy = sum(1 for r in records if r.is_institution_buy)
        inst_sell = sum(1 for r in records if r.is_institution_sell)
        net = inst_buy - inst_sell

        # 机构溢价买入占比
        inst_premium_buys = sum(
            1 for r in records
            if r.is_institution_buy and r.premium_ratio > 0
        )

        result = {
            "direction": "buying" if net > 3 else ("selling" if net < -3 else "neutral"),
            "net_count": net,
            "institution_buy_count": inst_buy,
            "institution_sell_count": inst_sell,
            "premium_buy_pct": round(inst_premium_buys / max(inst_buy, 1), 2),
        }
        self._cache_set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Market profile builder
    # ------------------------------------------------------------------

    def _build_market_profile(self, records: list[BlockTradeRecord]) -> BlockTradeProfile:
        """从原始记录构建市场级画像。"""
        profile = BlockTradeProfile()
        profile.total_count = len(records)
        profile.total_amount = round(sum(r.amount for r in records) / 1e8, 2)  # 转亿元

        premiums = []
        for r in records:
            premiums.append(r.premium_ratio)
            if r.premium_ratio > 0:
                profile.premium_count += 1
            elif r.premium_ratio < 0:
                profile.discount_count += 1
            if r.premium_ratio <= self.DEEP_DISCOUNT_THRESHOLD:
                profile.deep_discount_count += 1
            if r.premium_ratio >= self.HIGH_PREMIUM_THRESHOLD:
                profile.high_premium_count += 1
            if r.is_institution_buy:
                profile.institution_buy_count += 1
            if r.is_institution_sell:
                profile.institution_sell_count += 1

        profile.avg_premium_ratio = (
            round(sum(premiums) / len(premiums), 2) if premiums else 0.0
        )

        # 机构净方向
        net_inst = profile.institution_buy_count - profile.institution_sell_count
        if net_inst > 3:
            profile.institution_net_direction = "buying"
        elif net_inst < -3:
            profile.institution_net_direction = "selling"

        return profile

    # ------------------------------------------------------------------
    # Symbol-level analysis
    # ------------------------------------------------------------------

    def _attach_symbol_analysis(
        self,
        profile: BlockTradeProfile,
        records: list[BlockTradeRecord],
        symbol: str,
    ) -> None:
        """附加单只股票的大宗交易分析。"""
        symbol_clean = symbol.replace(".SZ", "").replace(".SH", "").zfill(6)
        matched = [r for r in records if r.symbol == symbol_clean]

        if not matched:
            return

        profile.symbol_records = matched
        profile.symbol_total_amount = round(sum(r.amount for r in matched), 2)
        premiums = [r.premium_ratio for r in matched]
        profile.symbol_premium_avg = round(sum(premiums) / len(premiums), 2) if premiums else 0.0
        profile.symbol_institution_buy = any(r.is_institution_buy for r in matched)
        profile.symbol_institution_sell = any(r.is_institution_sell for r in matched)

        # 连续天数
        profile.symbol_consecutive_days = self._count_consecutive_days(
            matched, symbol_clean
        )

    def _count_consecutive_days(
        self, current: list[BlockTradeRecord], symbol: str
    ) -> int:
        """计算该标的连续出现大宗交易的天数。"""
        try:
            # 回溯几天查历史
            import akshare as ak
            from datetime import date

            today = date.today()
            start = (today - timedelta(days=self.LOOKBACK_DAYS)).strftime("%Y%m%d")
            end = today.strftime("%Y%m%d")

            df = ak.stock_dzjy_mrmx(symbol="A股", start_date=start, end_date=end)
            if df is None or len(df) == 0:
                return len({r.trade_date for r in current}) if current else 0

            # 筛选该标的的记录
            symbol_col = None
            for col in df.columns:
                if "代码" in str(col) or "CODE" in str(col).upper():
                    symbol_col = col
                    break

            if symbol_col is None:
                return 1

            symbol_dates = set()
            for _, row in df.iterrows():
                code = str(row[symbol_col]).zfill(6)
                if code == symbol:
                    date_col = None
                    for col in df.columns:
                        if "日期" in str(col) or "DATE" in str(col).upper():
                            date_col = col
                            break
                    if date_col:
                        symbol_dates.add(str(row[date_col])[:10])

            return len(symbol_dates)
        except Exception as e:
            logger.warning("Consecutive days calculation failed for %s: %s", symbol, e)
            return len({r.trade_date for r in current}) if current else 0

    # ------------------------------------------------------------------
    # Signal classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_signal(profile: BlockTradeProfile) -> tuple[str, str]:
        """Classify overall block trade signal: bullish / bearish / neutral."""
        bullish_score = 0
        bearish_score = 0
        reasons: list[str] = []

        # 1. 机构净方向
        if profile.institution_net_direction == "buying":
            bullish_score += 2
            reasons.append(f"机构净买入({profile.institution_buy_count}笔买入 vs {profile.institution_sell_count}笔卖出)")
        elif profile.institution_net_direction == "selling":
            bearish_score += 2
            reasons.append(f"机构净卖出({profile.institution_sell_count}笔卖出 vs {profile.institution_buy_count}笔买入)")

        # 2. 高溢价笔数
        if profile.high_premium_count >= 3:
            bullish_score += 2
            reasons.append(f"{profile.high_premium_count}笔高溢价(≥5%)成交")
        elif profile.high_premium_count >= 1:
            bullish_score += 1

        # 3. 深度折价笔数
        if profile.deep_discount_count >= 5:
            bearish_score += 2
            reasons.append(f"{profile.deep_discount_count}笔深度折价(≤-10%)成交")
        elif profile.deep_discount_count >= 2:
            bearish_score += 1

        # 4. 个股级 — 机构买入目标标的
        if profile.symbol_institution_buy and not profile.symbol_institution_sell:
            bullish_score += 2
            reasons.append("目标标的获机构大宗买入")
        if profile.symbol_institution_sell:
            bearish_score += 1
            reasons.append("目标标的遭机构大宗卖出")

        # 5. 个股级 — 连续大宗
        if profile.symbol_consecutive_days >= BlockTradeAnalyzer.CONSECUTIVE_DAYS_THRESHOLD:
            if profile.symbol_institution_buy:
                bullish_score += 1
                reasons.append(f"连续{profile.symbol_consecutive_days}天大宗成交(机构买入)")
            elif profile.symbol_premium_avg > 0:
                bullish_score += 1
                reasons.append(f"连续{profile.symbol_consecutive_days}天溢价大宗")

        # 6. 平均折溢率
        if profile.avg_premium_ratio > 2:
            bullish_score += 1
        elif profile.avg_premium_ratio < -5:
            bearish_score += 1

        if bullish_score > bearish_score:
            return "bullish", "; ".join(reasons[:3]) if reasons else "大宗资金偏积极"
        elif bearish_score > bullish_score:
            return "bearish", "; ".join(reasons[:3]) if reasons else "大宗资金偏消极"
        return "neutral", "大宗交易信号中性"

    @staticmethod
    def _compute_score(profile: BlockTradeProfile) -> int:
        """Compute 0-100 composite block trade score."""
        score = 50

        # 机构净方向 (±15)
        if profile.institution_net_direction == "buying":
            score += 15
        elif profile.institution_net_direction == "selling":
            score -= 15

        # 溢价/折价比 (±10)
        premium_pct = (
            profile.premium_count / max(profile.total_count, 1) * 100
            if profile.total_count > 0
            else 50
        )
        if premium_pct > 60:
            score += 10
        elif premium_pct < 30:
            score -= 10

        # 高溢价 (±10)
        if profile.high_premium_count >= 3:
            score += 10
        elif profile.high_premium_count >= 1:
            score += 5

        # 深度折价 (-10)
        if profile.deep_discount_count >= 5:
            score -= 10
        elif profile.deep_discount_count >= 2:
            score -= 5

        # 个股级 adjust
        if profile.symbol_institution_buy and not profile.symbol_institution_sell:
            score += 10
        if profile.symbol_institution_sell:
            score -= 5
        if profile.symbol_consecutive_days >= BlockTradeAnalyzer.CONSECUTIVE_DAYS_THRESHOLD:
            if profile.symbol_premium_avg > 0:
                score += 5
            else:
                score -= 5

        return max(0, min(100, score))

    @staticmethod
    def _compute_confidence(profile: BlockTradeProfile) -> float:
        """Compute confidence based on data availability and signal clarity."""
        if profile.total_count == 0:
            return 0.0

        confidence = 0.5

        # More records → higher confidence
        if profile.total_count >= 50:
            confidence += 0.15
        elif profile.total_count >= 20:
            confidence += 0.10
        elif profile.total_count >= 10:
            confidence += 0.05

        # Institutional participation → stronger signal
        inst_total = profile.institution_buy_count + profile.institution_sell_count
        if inst_total >= 10:
            confidence += 0.15
        elif inst_total >= 5:
            confidence += 0.10

        # Clear direction → higher confidence
        if profile.institution_net_direction != "neutral":
            confidence += 0.10

        # Symbol-level data → more specific
        if profile.symbol_records:
            confidence += 0.10

        return min(1.0, confidence)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_daily_records(self) -> list[BlockTradeRecord]:
        """Fetch today's block trade records from AKShare/东财."""
        cache_key = "daily_records"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            today_str = datetime.now().strftime("%Y%m%d")
            # Look back up to 3 days in case today has no data yet (weekend/holiday)
            from datetime import date as date_cls
            start_str = (date_cls.today() - timedelta(days=3)).strftime("%Y%m%d")

            df = ak.stock_dzjy_mrmx(symbol="A股", start_date=start_str, end_date=today_str)
            if df is None or len(df) == 0:
                logger.info("No block trade records found for %s–%s", start_str, today_str)
                self._cache_set(cache_key, [])
                return []

            records = []
            for _, row in df.iterrows():
                record = self._parse_row(row)
                if record:
                    records.append(record)

            # Only keep latest trading day
            if records:
                latest_date = max(r.trade_date for r in records)
                records = [r for r in records if r.trade_date == latest_date]

            self._cache_set(cache_key, records)
            logger.info("Fetched %d block trade records for %s", len(records),
                         records[0].trade_date if records else "N/A")
            return records

        except Exception as e:
            logger.warning("AKShare block trade fetch failed: %s", e)
            self._cache_set(cache_key, [])
            return []

    @staticmethod
    def _parse_row(row) -> Optional[BlockTradeRecord]:
        """Parse a single row from AKShare output into BlockTradeRecord."""
        try:
            row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)

            # Map column names (AKShare uses Chinese column names)
            def _get(keywords: list[str], default=None):
                for kw in keywords:
                    for k, v in row_dict.items():
                        if kw in str(k):
                            return v
                return default

            trade_date = str(_get(["交易日期", "TRADE_DATE"], ""))[:10]
            symbol = str(_get(["证券代码", "SECURITY_CODE"], ""))
            name = str(_get(["证券简称", "SECURITY_NAME_ABBR"], ""))
            close_price = float(_get(["收盘价", "CLOSE_PRICE"], 0) or 0)
            deal_price = float(_get(["成交价", "DEAL_PRICE"], 0) or 0)
            premium_ratio = float(_get(["折溢率", "PREMIUM_RATIO"], 0) or 0)
            volume = int(float(_get(["成交量", "DEAL_VOLUME"], 0) or 0))
            amount = float(_get(["成交额", "DEAL_AMT"], 0) or 0)
            turnover_ratio = float(_get(["成交额/流通市值", "TURNOVER_RATE"], 0) or 0)
            buyer = str(_get(["买方营业部", "BUYER_NAME"], ""))
            seller = str(_get(["卖方营业部", "SELLER_NAME"], ""))

            # Detect institution participation
            is_inst_buy = any(
                kw in buyer for kw in BlockTradeAnalyzer.INSTITUTION_KEYWORDS
            )
            is_inst_sell = any(
                kw in seller for kw in BlockTradeAnalyzer.INSTITUTION_KEYWORDS
            )

            return BlockTradeRecord(
                trade_date=trade_date,
                symbol=symbol,
                name=name,
                close_price=close_price,
                deal_price=deal_price,
                premium_ratio=premium_ratio,
                volume=volume,
                amount=amount,
                turnover_ratio=turnover_ratio,
                buyer=buyer,
                seller=seller,
                is_institution_buy=is_inst_buy,
                is_institution_sell=is_inst_sell,
            )
        except Exception as e:
            logger.debug("Failed to parse block trade row: %s", e)
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
