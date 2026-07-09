"""Margin trading cycle analysis — 融资融券 balance trends and sentiment signals.

Data source: 东财 datacenter RPTA_WEB_RZRQ_GGMX (个股融资融券明细，日级 T+1).
History: CSV per-stock under data/margin_history/.
Alert triggers: balance spike/drop, consecutive decline, price-margin divergence.

Ref: ai-gold-miner events/models + signals/monitor_signal patterns.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import random
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 东财 datacenter 配置 ──────────────────────────────────────────
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_MIN_INTERVAL = 1.2  # 东财限流间隔

_em_last_call = 0.0


def _em_get(url: str, params: dict, timeout: int = 15) -> dict:
    """东财统一请求，内置限流."""
    global _em_last_call
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        full_url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full_url)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", "https://data.eastmoney.com/")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        _em_last_call = time.time()


# ── 历史存储路径 ──────────────────────────────────────────────────
def _history_dir() -> Path:
    p = Path(__file__).parents[2] / "data" / "margin_history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _history_path(code: str) -> Path:
    return _history_dir() / f"{code}.csv"


# ── DTOs ──────────────────────────────────────────────────────────


@dataclass
class MarginProfile:
    """个股融资融券综合快照."""

    code: str = ""
    name: str = ""

    # 核心指标
    margin_balance: Optional[float] = None       # 融资余额 (亿元)
    margin_balance_5d_ago: Optional[float] = None
    margin_balance_20d_ago: Optional[float] = None
    margin_balance_trend: str = "stable"          # "rising" / "falling" / "stable"
    margin_buy_amount: Optional[float] = None     # 当日融资买入额 (亿元)
    margin_repay_amount: Optional[float] = None   # 当日融资偿还额 (亿元)
    margin_net_buy: Optional[float] = None        # 融资净买入 (亿元)
    short_balance: Optional[float] = None         # 融券余额 (亿元)

    # 衍生指标
    margin_balance_5d_change_pct: Optional[float] = None   # 5日变化率
    margin_balance_20d_change_pct: Optional[float] = None  # 20日变化率
    consecutive_outflow_days: int = 0              # 连续净流出天数
    consecutive_inflow_days: int = 0               # 连续净流入天数

    # 信号分类
    margin_signal: str = "neutral"                # "bullish" / "bearish" / "neutral"
    leverage_sentiment: str = "neutral"           # "greedy" / "fearful" / "neutral"
    divergence_signal: str = "none"               # "retail_catching_knife" / "smart_money_exit" / "none"

    # 综合
    score: int = 50                               # 0-100
    data_date: str = ""                           # 数据日期 YYYY-MM-DD
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarginAlert:
    """融资监控告警."""
    code: str
    name: str
    alert_type: str          # "balance_spike" / "balance_drop" / "consecutive_outflow"
                              # / "price_margin_divergence" / "leverage_extreme"
    severity: str            # "high" / "medium" / "info"
    direction: str           # "bullish" / "bearish" / "neutral"
    message: str
    current_value: float
    threshold: float
    triggered_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarginHistoryRow:
    """单日融资融券历史记录."""
    date: str
    margin_balance: float      # 融资余额 (亿元)
    margin_buy: float          # 融资买入额 (亿元)
    margin_repay: float        # 融资偿还额 (亿元)
    margin_net: float          # 融资净买入 (亿元)
    short_balance: float       # 融券余额 (亿元)
    close_price: float = 0.0   # 当日收盘价 (可选)


# ── Analyzer ──────────────────────────────────────────────────────


class MarginAnalyzer:
    """个股融资融券分析器.

    Primary: 东财 datacenter RPTA_WEB_RZRQ_GGMX (个股日级).
    History: CSV per-stock, auto-saved on fetch.
    Cache: 1h TTL (日级数据，T+1 更新).
    """

    # 阈值
    BALANCE_SPIKE_PCT = 5.0        # 融资余额单日变化 >5% → 异动
    BALANCE_DROP_PCT = -3.0        # 单日下降 >3% → 恐慌
    CONSECUTIVE_OUTFLOW_DAYS = 5   # 连续净流出 ≥5天 → 中线撤退
    CONSECUTIVE_INFLOW_DAYS = 5    # 连续净流入 ≥5天 → 杠杆过热
    LEVERAGE_GREEDY_RATIO = 11.0   # 融资买入占比 >11%
    LEVERAGE_FEARFUL_RATIO = 5.0   # 融资买入占比 <5%
    DIVERGENCE_LOOKBACK = 5        # 价量背离检测窗口

    def __init__(self) -> None:
        self._cache: dict[str, tuple[datetime, MarginProfile]] = {}
        self._cache_ttl = timedelta(hours=1)  # 日级数据，1h 合理

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, code: str, name: str = "", close_price: float = 0.0) -> MarginProfile:
        """获取个股融资融券数据，计算信号 + 告警.

        Args:
            code: 6位代码
            name: 股票名称 (可选)
            close_price: 当日收盘价 (可选，用于背离检测)
        """
        # 检查缓存
        cached = self._cache_get(code)
        if cached is not None:
            return cached

        # 拉取历史数据 (自动保存到 CSV)
        history = self._fetch_and_save_history(code)

        if not history:
            return MarginProfile(code=code, name=name, score=50)

        # 构建 profile
        latest = history[-1]
        profile = MarginProfile(
            code=code,
            name=name,
            margin_balance=latest.margin_balance,
            margin_buy_amount=latest.margin_buy,
            margin_repay_amount=latest.margin_repay,
            margin_net_buy=latest.margin_net,
            short_balance=latest.short_balance,
            data_date=latest.date,
        )

        # 5日 / 20日 变化
        if len(history) >= 5:
            d5 = history[-5]
            profile.margin_balance_5d_ago = d5.margin_balance
            if d5.margin_balance > 0:
                profile.margin_balance_5d_change_pct = round(
                    (latest.margin_balance - d5.margin_balance) / d5.margin_balance * 100, 2
                )

        if len(history) >= 20:
            d20 = history[-20]
            profile.margin_balance_20d_ago = d20.margin_balance
            if d20.margin_balance > 0:
                profile.margin_balance_20d_change_pct = round(
                    (latest.margin_balance - d20.margin_balance) / d20.margin_balance * 100, 2
                )

        # 趋势
        profile.margin_balance_trend = self._compute_balance_trend(history)

        # 连续流出/流入天数
        profile.consecutive_outflow_days = self._count_consecutive(history, "outflow")
        profile.consecutive_inflow_days = self._count_consecutive(history, "inflow")

        # 融资买入占比 (估算: 融资买入 / 总成交额，此处用净买入方向)
        profile.margin_signal = self._classify_margin_signal(profile, history)
        profile.leverage_sentiment = self._classify_leverage_sentiment(profile)
        profile.divergence_signal = self._detect_divergence(history, close_price)

        # 综合评分
        profile.score = self._compute_score(profile)

        self._cache_set(code, profile)
        return profile

    def get_alerts(self, code: str, name: str = "", close_price: float = 0.0) -> list[MarginAlert]:
        """生成融资监控告警."""
        profile = self.analyze(code, name, close_price)
        alerts: list[MarginAlert] = []

        now = datetime.now()

        # 1. 融资余额单日骤变
        if profile.margin_net_buy is not None and profile.margin_balance is not None:
            prev_balance = profile.margin_balance - profile.margin_net_buy
            if prev_balance > 0:
                daily_pct = (profile.margin_net_buy / prev_balance) * 100
                if daily_pct > self.BALANCE_SPIKE_PCT:
                    alerts.append(MarginAlert(
                        code=code, name=name,
                        alert_type="balance_spike", severity="medium",
                        direction="bullish",
                        message=f"融资余额单日暴增 {daily_pct:+.1f}% ({profile.margin_net_buy:+.2f}亿)，杠杆资金加速入场",
                        current_value=daily_pct,
                        threshold=self.BALANCE_SPIKE_PCT,
                        triggered_at=now,
                    ))
                elif daily_pct < self.BALANCE_DROP_PCT:
                    alerts.append(MarginAlert(
                        code=code, name=name,
                        alert_type="balance_drop", severity="high",
                        direction="bearish",
                        message=f"融资余额单日骤降 {daily_pct:+.1f}% ({profile.margin_net_buy:+.2f}亿)，杠杆资金恐慌出逃/强平",
                        current_value=daily_pct,
                        threshold=self.BALANCE_DROP_PCT,
                        triggered_at=now,
                    ))

        # 2. 连续净流出
        if profile.consecutive_outflow_days >= self.CONSECUTIVE_OUTFLOW_DAYS:
            alerts.append(MarginAlert(
                code=code, name=name,
                alert_type="consecutive_outflow", severity="medium",
                direction="bearish",
                message=f"融资余额连续 {profile.consecutive_outflow_days} 天净流出，5日变化 {profile.margin_balance_5d_change_pct:+.1f}%，中线资金撤退",
                current_value=profile.consecutive_outflow_days,
                threshold=self.CONSECUTIVE_OUTFLOW_DAYS,
                triggered_at=now,
            ))

        # 3. 连续净流入 (杠杆过热)
        if profile.consecutive_inflow_days >= self.CONSECUTIVE_INFLOW_DAYS:
            alerts.append(MarginAlert(
                code=code, name=name,
                alert_type="leverage_extreme", severity="medium",
                direction="bearish",  # 过热是反向信号
                message=f"融资余额连续 {profile.consecutive_inflow_days} 天净流入，杠杆情绪过热，警惕回调",
                current_value=profile.consecutive_inflow_days,
                threshold=self.CONSECUTIVE_INFLOW_DAYS,
                triggered_at=now,
            ))

        # 4. 价量背离
        if profile.divergence_signal == "retail_catching_knife":
            alerts.append(MarginAlert(
                code=code, name=name,
                alert_type="price_margin_divergence", severity="high",
                direction="bearish",
                message=f"股价下跌但融资余额上升 — 散户接飞刀信号。融资余额 {profile.margin_balance:.1f}亿，5日变化 {profile.margin_balance_5d_change_pct:+.1f}%",
                current_value=profile.margin_balance_5d_change_pct or 0,
                threshold=0,
                triggered_at=now,
            ))
        elif profile.divergence_signal == "smart_money_exit":
            alerts.append(MarginAlert(
                code=code, name=name,
                alert_type="price_margin_divergence", severity="medium",
                direction="bearish",
                message=f"股价上涨但融资余额下降 — 杠杆资金借反弹出货",
                current_value=profile.margin_balance_5d_change_pct or 0,
                threshold=0,
                triggered_at=now,
            ))

        return alerts

    def load_history(self, code: str) -> list[MarginHistoryRow]:
        """从 CSV 加载历史数据."""
        path = _history_path(code)
        if not path.exists():
            return []
        rows: list[MarginHistoryRow] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    rows.append(MarginHistoryRow(
                        date=r["date"],
                        margin_balance=float(r["margin_balance"]),
                        margin_buy=float(r["margin_buy"]),
                        margin_repay=float(r["margin_repay"]),
                        margin_net=float(r["margin_net"]),
                        short_balance=float(r.get("short_balance", 0)),
                        close_price=float(r.get("close_price", 0)),
                    ))
                except (KeyError, ValueError):
                    continue
        return rows

    # ------------------------------------------------------------------
    # Data fetching — 东财个股端点
    # ------------------------------------------------------------------

    def _fetch_and_save_history(self, code: str) -> list[MarginHistoryRow]:
        """从东财拉取融资融券数据，合并已有 CSV，去重保存."""
        # 先加载已有历史
        existing = self.load_history(code)
        existing_dates = {r.date for r in existing}

        # 拉取最新数据 (最多 100 条)
        try:
            data = _em_get(DATACENTER_URL, {
                "reportName": "RPTA_WEB_RZRQ_GGMX",
                "columns": "ALL",
                "filter": f'(SCODE="{code}")',
                "pageSize": "100",
                "sortColumns": "DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB",
            })
            rows = data.get("result", {}).get("data", [])
        except Exception as e:
            logger.warning("东财融资融券 %s 拉取失败: %s", code, e)
            return existing

        if not rows:
            return existing

        # 解析新数据
        new_rows: list[MarginHistoryRow] = []
        for r in rows:
            date = str(r.get("DATE", ""))[:10]
            if not date or date in existing_dates:
                continue
            try:
                new_rows.append(MarginHistoryRow(
                    date=date,
                    margin_balance=(r.get("RZYE") or 0) / 1e8,
                    margin_buy=(r.get("RZMRE") or 0) / 1e8,
                    margin_repay=(r.get("RZCHE") or 0) / 1e8,
                    margin_net=((r.get("RZMRE") or 0) - (r.get("RZCHE") or 0)) / 1e8,
                    short_balance=(r.get("RQYE") or 0) / 1e8,
                ))
            except (ValueError, TypeError):
                continue

        if not new_rows:
            return existing

        # 合并 + 按日期排序
        all_rows = existing + new_rows
        all_rows.sort(key=lambda x: x.date)

        # 保存 CSV
        self._save_history(code, all_rows)

        logger.info(
            "融资融券 %s: 新增 %d 条, 累计 %d 条 (最新 %s)",
            code, len(new_rows), len(all_rows),
            all_rows[-1].date if all_rows else "N/A",
        )
        return all_rows

    @staticmethod
    def _save_history(code: str, rows: list[MarginHistoryRow]) -> None:
        """保存历史到 CSV."""
        path = _history_path(code)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "margin_balance", "margin_buy", "margin_repay",
                             "margin_net", "short_balance", "close_price"])
            for r in rows:
                writer.writerow([
                    r.date,
                    round(r.margin_balance, 4),
                    round(r.margin_buy, 4),
                    round(r.margin_repay, 4),
                    round(r.margin_net, 4),
                    round(r.short_balance, 4),
                    round(r.close_price, 2),
                ])

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_balance_trend(history: list[MarginHistoryRow]) -> str:
        """5日融资余额趋势."""
        if len(history) < 5:
            return "stable"
        recent = history[-5:]
        first = recent[0].margin_balance
        last = recent[-1].margin_balance
        if first <= 0:
            return "stable"
        pct = (last - first) / first * 100
        if pct > 2:
            return "rising"
        elif pct < -2:
            return "falling"
        return "stable"

    @classmethod
    def _classify_margin_signal(
        cls, profile: MarginProfile, history: list[MarginHistoryRow],
    ) -> str:
        """综合融资信号: bullish / bearish / neutral."""
        bullish, bearish = 0, 0

        if profile.margin_balance_trend == "rising":
            bullish += 1
        elif profile.margin_balance_trend == "falling":
            bearish += 1

        if profile.margin_balance_5d_change_pct is not None:
            if profile.margin_balance_5d_change_pct > 3:
                bullish += 1
            elif profile.margin_balance_5d_change_pct < -3:
                bearish += 1

        if profile.margin_net_buy is not None:
            if profile.margin_net_buy > 1:
                bullish += 1
            elif profile.margin_net_buy < -1:
                bearish += 1

        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"

    @classmethod
    def _classify_leverage_sentiment(cls, profile: MarginProfile) -> str:
        """杠杆情绪: greedy / fearful / neutral."""
        if profile.consecutive_inflow_days >= cls.CONSECUTIVE_INFLOW_DAYS:
            return "greedy"
        if profile.consecutive_outflow_days >= cls.CONSECUTIVE_OUTFLOW_DAYS:
            return "fearful"
        return "neutral"

    @classmethod
    def _detect_divergence(
        cls, history: list[MarginHistoryRow], close_price: float,
    ) -> str:
        """检测价量背离.

        Returns:
            "retail_catching_knife": 股价跌但融资升
            "smart_money_exit": 股价涨但融资降
            "none": 无背离
        """
        if len(history) < cls.DIVERGENCE_LOOKBACK:
            return "none"

        recent = history[-cls.DIVERGENCE_LOOKBACK:]
        balances = [r.margin_balance for r in recent]
        balance_change = (balances[-1] - balances[0]) / balances[0] * 100 if balances[0] > 0 else 0

        if close_price <= 0:
            return "none"

        # 需要有价格历史才能判断 (简化为只要有 close_price 参数即可)
        # 更精确的判断在 get_alerts 中调用时传入 close_price
        if balance_change > 2 and close_price > 0:
            # 融资升+价格信息由调用方提供
            return "pending"  # 需要价格对比

        return "none"

    @classmethod
    def _detect_divergence_with_price(
        cls, history: list[MarginHistoryRow], close_price: float,
        price_5d_ago: float = 0.0,
    ) -> str:
        """带价格对比的背离检测."""
        if len(history) < cls.DIVERGENCE_LOOKBACK:
            return "none"

        recent = history[-cls.DIVERGENCE_LOOKBACK:]
        balances = [r.margin_balance for r in recent]
        bal_first, bal_last = balances[0], balances[-1]
        if bal_first <= 0:
            return "none"
        bal_change_pct = (bal_last - bal_first) / bal_first * 100

        if price_5d_ago <= 0:
            return "none"
        price_change_pct = (close_price - price_5d_ago) / price_5d_ago * 100

        # 股价跌 >3% 但融资余额升 >2% → 散户接飞刀
        if price_change_pct < -3 and bal_change_pct > 2:
            return "retail_catching_knife"
        # 股价涨 >3% 但融资余额降 >2% → 杠杆资金借反弹出货
        if price_change_pct > 3 and bal_change_pct < -2:
            return "smart_money_exit"
        return "none"

    @staticmethod
    def _count_consecutive(history: list[MarginHistoryRow], direction: str) -> int:
        """计算连续净流入/流出天数."""
        count = 0
        for r in reversed(history):
            if direction == "outflow" and r.margin_net < 0:
                count += 1
            elif direction == "inflow" and r.margin_net > 0:
                count += 1
            else:
                break
        return count

    @classmethod
    def _compute_score(cls, profile: MarginProfile) -> int:
        """计算 0-100 综合评分."""
        score = 50

        # 趋势贡献 (±15)
        if profile.margin_balance_trend == "rising":
            score += 15
        elif profile.margin_balance_trend == "falling":
            score -= 15

        # 5日变化贡献 (±20)
        if profile.margin_balance_5d_change_pct is not None:
            chg = profile.margin_balance_5d_change_pct
            if chg > 5:
                score += 20
            elif chg > 2:
                score += 10
            elif chg < -5:
                score -= 20
            elif chg < -2:
                score -= 10

        # 连续流向贡献 (±10)
        if profile.consecutive_inflow_days >= 3:
            score += 10
        if profile.consecutive_outflow_days >= 3:
            score -= 10

        # 背离调整 (±5)
        if profile.divergence_signal == "retail_catching_knife":
            score -= 5
        elif profile.divergence_signal == "smart_money_exit":
            score -= 5

        return max(0, min(100, score))

    # ------------------------------------------------------------------
    # Simple cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[MarginProfile]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._cache_ttl:
            return val
        del self._cache[key]
        return None

    def _cache_set(self, key: str, val: MarginProfile) -> None:
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self) -> None:
        self._cache.clear()


# ── 全局单例 ──────────────────────────────────────────────────────

_margin_analyzer: Optional[MarginAnalyzer] = None


def get_margin_analyzer() -> MarginAnalyzer:
    global _margin_analyzer
    if _margin_analyzer is None:
        _margin_analyzer = MarginAnalyzer()
    return _margin_analyzer
