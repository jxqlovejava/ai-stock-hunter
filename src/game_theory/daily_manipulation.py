# -*- coding: utf-8 -*-
"""日级操纵模式检测器 (DailyManipulationDetector)。

补充现有 ManipulationDetector 的日内分钟级检测，
识别跨日运作的庄家操纵模式。

检测模式:
  1. 横盘吸筹 — 窄幅震荡 + 缩量 + 股东户数下降 (2-8周)
  2. 连阳出货 — N连阳 + 量递增 → 突然放量长阴 (3-7天)
  3. 涨停诱多链 — 连续涨停 → 开板放量 → 次日闷杀 (2-4天)
  4. 对倒操纵链 — 量价背离 + 锯齿走势 + 无基本面支撑 (5-15天)
  5. 消息配合出货 — 利好消息 + 高开低走 (1-5天)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class DailyManipulationPattern(str, Enum):
    SIDEWAYS_ACCUMULATION = "sideways_accumulation"     # 横盘吸筹
    CONSECUTIVE_YANG_DUMP = "consecutive_yang_dump"     # 连阳出货
    LIMIT_UP_LURE_CHAIN = "limit_up_lure_chain"         # 涨停诱多链
    WASH_TRADE_CHAIN = "wash_trade_chain"               # 对倒操纵链
    NEWS_DISTRIBUTION = "news_distribution"             # 消息配合出货
    NONE = "none"


PATTERN_LABELS: dict[DailyManipulationPattern, str] = {
    DailyManipulationPattern.SIDEWAYS_ACCUMULATION: "横盘吸筹",
    DailyManipulationPattern.CONSECUTIVE_YANG_DUMP: "连阳出货",
    DailyManipulationPattern.LIMIT_UP_LURE_CHAIN: "涨停诱多链",
    DailyManipulationPattern.WASH_TRADE_CHAIN: "对倒操纵链",
    DailyManipulationPattern.NEWS_DISTRIBUTION: "消息配合出货",
    DailyManipulationPattern.NONE: "未检测到跨日操纵模式",
}


@dataclass
class DailyManipulationResult:
    """日级操纵检测结果。"""

    symbol: str
    detected_pattern: DailyManipulationPattern = DailyManipulationPattern.NONE
    pattern_label: str = ""
    confidence: float = 0.0              # 模式匹配置信度 0.0-1.0
    risk_score: float = 0.0              # 操纵风险评分 0-100

    # 模式细节
    pattern_details: dict = field(default_factory=dict)
    pattern_days: int = 0                # 模式持续天数
    signals: list[str] = field(default_factory=list)

    # 预期后续走势
    expected_next_move: str = ""         # "likely_down" / "likely_up" / "uncertain"
    expected_confidence: float = 0.0

    # 建议
    recommendations: list[str] = field(default_factory=list)
    data_quality: float = 0.0


class DailyManipulationDetector:
    """日级操纵模式检测器。

    用法:
        detector = DailyManipulationDetector()
        result = detector.detect(
            symbol="600519",
            daily_bars=[...],  # list of {open, high, low, close, volume, date}
            shareholder_change_pct=-0.18,
            recent_news=[...],
        )
    """

    # ── 阈值常量 ──

    # 横盘吸筹
    SIDEWAYS_MAX_RANGE = 0.08           # 最大振幅 < 8%
    SIDEWAYS_MIN_DAYS = 10              # 最少持续 10 个交易日
    SIDEWAYS_VOL_DECLINE = 0.20         # 成交量相对前期下降 > 20%

    # 连阳出货
    CONSECUTIVE_YANG_MIN = 4            # 最少 4 连阳
    CONSECUTIVE_VOL_INCREASE = 0.30     # 成交量递增 > 30%
    DUMP_VOL_RATIO = 2.0                # 放量阴线量比 > 2x
    DUMP_DROP_PCT = 0.05                # 单日跌幅 > 5%

    # 涨停诱多链
    LIMIT_UP_CHAIN_MIN = 2              # 最少连续 2 个涨停
    OPEN_BOARD_VOL_MULT = 3.0           # 开板日成交量放大 > 3x 前日均
    NEXT_DAY_DROP = 0.03                # 次日跌幅 > 3%

    # 消息配合出货
    NEWS_HIGH_OPEN_PCT = 0.03           # 高开 > 3%
    NEWS_CLOSE_DOWN_PCT = 0.02          # 收盘跌 > 2%（高开低走）

    def detect(
        self,
        symbol: str,
        daily_bars: list[dict] | None = None,
        shareholder_change_pct: float = 0.0,
        recent_news: list[dict] | None = None,
        sector_trend: str = "neutral",  # "up" / "down" / "neutral"
    ) -> DailyManipulationResult:
        """执行日级操纵模式检测。

        Args:
            symbol: 股票代码
            daily_bars: 日线数据 [{open,high,low,close,volume,date}, ...]
            shareholder_change_pct: 股东户数变化率（来自 ChipConcentrationAnalyzer）
            recent_news: 近期新闻 [{title,date,sentiment}, ...]
            sector_trend: 所属板块趋势
        """
        result = DailyManipulationResult(symbol=symbol)
        daily_bars = daily_bars or []
        recent_news = recent_news or []
        data_points = 0
        total_points = 3

        if daily_bars:
            data_points += 1
        if shareholder_change_pct != 0:
            data_points += 1
        if recent_news:
            data_points += 1
        result.data_quality = data_points / max(total_points, 1)

        if not daily_bars or len(daily_bars) < 10:
            result.detected_pattern = DailyManipulationPattern.NONE
            result.pattern_label = PATTERN_LABELS[DailyManipulationPattern.NONE]
            result.recommendations.append("日线数据不足，无法执行日级操纵检测")
            return result

        # ── 逐模式检测，取最高置信度 ──
        candidates: list[tuple[DailyManipulationPattern, float, float, dict, list[str]]] = []

        # 1. 横盘吸筹检测
        pat, conf, risk, details, sigs = self._detect_sideways_accumulation(
            daily_bars, shareholder_change_pct
        )
        if pat != DailyManipulationPattern.NONE:
            candidates.append((pat, conf, risk, details, sigs))

        # 2. 连阳出货检测
        pat, conf, risk, details, sigs = self._detect_consecutive_yang_dump(daily_bars)
        if pat != DailyManipulationPattern.NONE:
            candidates.append((pat, conf, risk, details, sigs))

        # 3. 涨停诱多链检测
        pat, conf, risk, details, sigs = self._detect_limit_up_lure_chain(daily_bars)
        if pat != DailyManipulationPattern.NONE:
            candidates.append((pat, conf, risk, details, sigs))

        # 4. 消息配合出货检测
        if recent_news:
            pat, conf, risk, details, sigs = self._detect_news_distribution(
                daily_bars, recent_news
            )
            if pat != DailyManipulationPattern.NONE:
                candidates.append((pat, conf, risk, details, sigs))

        # ── 选择最高风险的模式 ──
        if candidates:
            candidates.sort(key=lambda x: x[2], reverse=True)
            best = candidates[0]
            result.detected_pattern = best[0]
            result.pattern_label = PATTERN_LABELS.get(best[0], str(best[0]))
            result.confidence = best[1]
            result.risk_score = best[2]
            result.pattern_details = best[3]
            result.signals = best[4]

            # 预期后续走势
            if best[0] in (
                DailyManipulationPattern.CONSECUTIVE_YANG_DUMP,
                DailyManipulationPattern.LIMIT_UP_LURE_CHAIN,
                DailyManipulationPattern.NEWS_DISTRIBUTION,
            ):
                result.expected_next_move = "likely_down"
                result.expected_confidence = best[1]
            elif best[0] == DailyManipulationPattern.SIDEWAYS_ACCUMULATION:
                result.expected_next_move = "likely_up"
                result.expected_confidence = best[1] * 0.7  # 吸筹后拉升不确定
            else:
                result.expected_next_move = "uncertain"
        else:
            result.detected_pattern = DailyManipulationPattern.NONE
            result.pattern_label = PATTERN_LABELS[DailyManipulationPattern.NONE]

        # ── 生成建议 ──
        if result.risk_score >= 60:
            result.recommendations.append(f"检测到 {result.pattern_label}（风险 {result.risk_score:.0f}/100），建议暂不新建仓")
            result.recommendations.append("如已持仓，提高警惕，设置紧密止损")
        elif result.risk_score >= 30:
            result.recommendations.append(f"检测到 {result.pattern_label} 迹象（风险 {result.risk_score:.0f}/100），建议降低仓位")
        else:
            result.recommendations.append("未检测到显著日级操纵模式")

        return result

    # ── 各模式检测方法 ──

    def _detect_sideways_accumulation(
        self, bars: list[dict], shareholder_change: float
    ) -> tuple[DailyManipulationPattern, float, float, dict, list[str]]:
        """横盘吸筹检测。

        特征: 窄幅震荡 + 缩量 + 股东户数下降
        """
        if len(bars) < self.SIDEWAYS_MIN_DAYS:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        recent = bars[-self.SIDEWAYS_MIN_DAYS:]
        highs = [b.get("high", 0) for b in recent]
        lows = [b.get("low", 0) for b in recent]
        closes = [b.get("close", 0) for b in recent]
        volumes = [b.get("volume", 0) for b in recent]

        if not all(h > 0 and l > 0 for h, l in zip(highs, lows)):
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 振幅检查
        max_high = max(highs)
        min_low = min(lows)
        range_pct = (max_high - min_low) / min_low if min_low > 0 else 1.0

        if range_pct > self.SIDEWAYS_MAX_RANGE:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 缩量检查 — 最近 5 日均量 vs 前 5 日均量
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else sum(volumes) / len(volumes)
        prior_vol = sum(volumes[:5]) / 5 if len(volumes) >= 10 else recent_vol

        vol_decline = (prior_vol - recent_vol) / prior_vol if prior_vol > 0 else 0

        signals = []
        confidence = 0.0

        # 震荡幅度越小，置信度越高
        if range_pct < 0.05:
            confidence += 0.4
            signals.append(f"近 {self.SIDEWAYS_MIN_DAYS} 日振幅仅 {range_pct:.1%}，极度窄幅震荡")
        else:
            confidence += 0.2
            signals.append(f"近 {self.SIDEWAYS_MIN_DAYS} 日振幅 {range_pct:.1%}，窄幅震荡")

        if vol_decline > self.SIDEWAYS_VOL_DECLINE:
            confidence += 0.3
            signals.append(f"成交量较前期萎缩 {vol_decline:.0%}，缩量明显")
        else:
            confidence += 0.1

        # 股东户数下降 = 吸筹确认信号
        if shareholder_change < -0.10:
            confidence += 0.3
            signals.append(f"股东户数下降 {abs(shareholder_change):.1%}，筹码在集中")

        if confidence < 0.4:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        risk = confidence * 60  # 横盘吸筹本身风险中等
        details = {
            "range_pct": range_pct,
            "vol_decline": vol_decline,
            "days": self.SIDEWAYS_MIN_DAYS,
            "shareholder_change": shareholder_change,
        }

        return DailyManipulationPattern.SIDEWAYS_ACCUMULATION, confidence, risk, details, signals

    def _detect_consecutive_yang_dump(
        self, bars: list[dict]
    ) -> tuple[DailyManipulationPattern, float, float, dict, list[str]]:
        """连阳出货检测。

        特征: N连阳 + 成交量递增 → 突然放量长阴
        """
        if len(bars) < self.CONSECUTIVE_YANG_MIN + 1:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        closes = [b.get("close", 0) for b in bars]
        opens = [b.get("open", 0) for b in bars]
        volumes = [b.get("volume", 0) for b in bars]

        # 从最新一根往前找连阳
        # 最新一根如果是阴线（close < open），检查前面是否连阳
        latest = bars[-1]
        latest_close = latest.get("close", 0)
        latest_open = latest.get("open", 0)
        latest_volume = latest.get("volume", 0)

        is_latest_yin = latest_close < latest_open
        if not is_latest_yin:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 检查前 N 天是否连阳
        yang_count = 0
        yang_volumes = []
        for i in range(len(bars) - 2, -1, -1):
            b = bars[i]
            if b.get("close", 0) > b.get("open", 0):
                yang_count += 1
                yang_volumes.append(b.get("volume", 0))
            else:
                break

        if yang_count < self.CONSECUTIVE_YANG_MIN:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        signals = []
        confidence = 0.0

        # 成交量递增检查
        if len(yang_volumes) >= 3:
            vol_increasing = all(
                yang_volumes[i] > yang_volumes[i + 1]
                for i in range(len(yang_volumes) - 1)
            )
            if vol_increasing:
                confidence += 0.3
                signals.append(f"{yang_count} 连阳 + 成交量递增")
            else:
                confidence += 0.15
                signals.append(f"{yang_count} 连阳")

        # 阴线放量检查
        avg_yang_vol = sum(yang_volumes) / len(yang_volumes) if yang_volumes else 1
        vol_ratio = latest_volume / avg_yang_vol if avg_yang_vol > 0 else 0
        if vol_ratio > self.DUMP_VOL_RATIO:
            confidence += 0.35
            signals.append(f"放量阴线（量比 {vol_ratio:.1f}x）")
        else:
            confidence += 0.1

        # 跌幅检查
        drop_pct = abs(latest_close - latest_open) / latest_open if latest_open > 0 else 0
        if drop_pct > self.DUMP_DROP_PCT:
            confidence += 0.35
            signals.append(f"单日跌幅 {drop_pct:.1%}")

        if confidence < 0.4:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        risk = confidence * 85  # 连阳出货风险高
        details = {
            "yang_count": yang_count,
            "vol_ratio": vol_ratio,
            "drop_pct": drop_pct,
        }

        return DailyManipulationPattern.CONSECUTIVE_YANG_DUMP, confidence, risk, details, signals

    def _detect_limit_up_lure_chain(
        self, bars: list[dict]
    ) -> tuple[DailyManipulationPattern, float, float, dict, list[str]]:
        """涨停诱多链检测。

        特征: 连续涨停 → 开板放量 → 次日低开/闷杀
        """
        if len(bars) < self.LIMIT_UP_CHAIN_MIN + 2:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 简化检测：找连续涨停（涨幅 > 9.5%）+ 开板 + 次日下跌
        limit_up_pct = 0.095
        limit_up_days = []

        for i, b in enumerate(bars):
            if i == 0:
                continue
            prev_close = bars[i - 1].get("close", 0)
            cur_close = b.get("close", 0)
            if prev_close > 0 and (cur_close - prev_close) / prev_close > limit_up_pct:
                limit_up_days.append(i)

        if len(limit_up_days) < self.LIMIT_UP_CHAIN_MIN:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 检查涨停序列中是否有连续 2 个以上
        consecutive = 1
        max_consecutive = 1
        for j in range(1, len(limit_up_days)):
            if limit_up_days[j] == limit_up_days[j - 1] + 1:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 1

        if max_consecutive < self.LIMIT_UP_CHAIN_MIN:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        signals = [f"检测到 {max_consecutive} 连板"]
        confidence = 0.3 + min(0.3, (max_consecutive - 2) * 0.15)

        # 检查最后一根涨停后的走势
        last_lu_day = limit_up_days[-1]
        if last_lu_day < len(bars) - 1:
            next_day = bars[last_lu_day + 1]
            next_open = next_day.get("open", 0)
            next_close = next_day.get("close", 0)
            prev_close = bars[last_lu_day].get("close", 0)

            if prev_close > 0:
                next_day_change = (next_close - prev_close) / prev_close
                if next_day_change < -0.03:
                    confidence += 0.4
                    signals.append(f"涨停次日跌 {abs(next_day_change):.1%}，闷杀确认")

        risk = confidence * 90  # 涨停诱多链风险极高
        details = {"max_consecutive": max_consecutive, "total_limit_days": len(limit_up_days)}

        return DailyManipulationPattern.LIMIT_UP_LURE_CHAIN, confidence, risk, details, signals

    def _detect_news_distribution(
        self, bars: list[dict], news: list[dict]
    ) -> tuple[DailyManipulationPattern, float, float, dict, list[str]]:
        """消息配合出货检测。

        特征: 利好消息 + 高开低走
        """
        if not news or not bars:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 检查最近 3 天是否有正面消息
        positive_news = [
            n for n in news
            if n.get("sentiment", "") in ("positive", "利好", "正面")
        ]
        if not positive_news:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        latest = bars[-1]
        latest_open = latest.get("open", 0)
        latest_close = latest.get("close", 0)
        prev_close = bars[-2].get("close", 0) if len(bars) > 1 else 0

        if prev_close <= 0:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        open_change = (latest_open - prev_close) / prev_close
        close_change = (latest_close - prev_close) / prev_close

        signals = []
        confidence = 0.0

        # 高开
        if open_change > self.NEWS_HIGH_OPEN_PCT:
            confidence += 0.35
            signals.append(f"利好消息后高开 {open_change:.1%}")
        else:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        # 低走（收盘回落）
        if close_change < open_change - self.NEWS_CLOSE_DOWN_PCT:
            confidence += 0.45
            signals.append(f"高开低走，收盘仅涨 {close_change:.1%}（高开 {open_change:.1%}）")
        elif close_change < 0:
            confidence += 0.55
            signals.append(f"利好高开低走收阴，典型出货信号")

        if confidence < 0.4:
            return DailyManipulationPattern.NONE, 0, 0, {}, []

        news_titles = [n.get("title", "") for n in positive_news[:3]]
        signals.append(f"配合消息: {'; '.join(news_titles)}")

        risk = confidence * 80
        details = {
            "open_change": open_change,
            "close_change": close_change,
            "news_count": len(positive_news),
        }

        return DailyManipulationPattern.NEWS_DISTRIBUTION, confidence, risk, details, signals
