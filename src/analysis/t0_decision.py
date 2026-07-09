# -*- coding: utf-8 -*-
"""T+0 日内交易时机决策引擎。

结合日线趋势分析与分钟级盘中数据，为 A 股 T+1 制度下的
建仓/加仓/减仓决策提供时机判断。

双维度分析:
  日线层 — 均线系统 / 支撑阻力 / K线形态 / 趋势判断
  日内层 — VWAP / 成交量结构 / 大单方向 / 斐波那契回撤 / 分时形态

输出:
  T0Result: 综合得分 + 操作建议 + 具体价位 + 触发条件
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from src.data.schema import Bar, Resolution

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 输出类型
# ---------------------------------------------------------------------------


class T0Action(str, Enum):
    """T+0 操作建议类型。"""
    ADD = "add"           # 加仓
    HOLD = "hold"         # 观望
    REDUCE = "reduce"     # 减仓
    CUT = "cut"           # 坚决减仓
    NO_POSITION = "no_position"  # 不建仓


@dataclass
class T0Signal:
    """单个 T+0 信号。"""
    direction: str        # "bull" | "bear"
    weight: int           # 对分数的影响（正=加分，负=减分）
    category: str         # daily | intraday
    description: str


@dataclass
class T0Result:
    """T+0 决策结果。"""

    symbol: str
    name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # 日线技术位
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    resistance: float = 0.0
    support_1: float = 0.0

    # 日内数据
    vwap: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    day_low_time: str = ""
    amplitude: float = 0.0
    rebound_from_low: float = 0.0

    # 量价
    total_vol: int = 0
    total_amount: float = 0.0
    vol_panic_pct: float = 0.0
    vol_rebound_pct: float = 0.0
    rebound_quality: str = ""
    large_sell_count: int = 0
    large_buy_count: int = 0

    # 形态
    daily_patterns: list[str] = field(default_factory=list)
    intraday_pattern: str = ""

    # 综合
    score: int = 0
    action: T0Action = T0Action.HOLD
    signals_bull: list[T0Signal] = field(default_factory=list)
    signals_bear: list[T0Signal] = field(default_factory=list)
    suggested_price: float = 0.0
    stop_loss: float = 0.0
    trigger_condition: str = ""

    # 多日趋势上下文
    trend_5d: str = ""           # "上升" / "下降" / "震荡"
    trend_10d: str = ""          # 同上
    volume_trend: str = ""       # "放量" / "缩量" / "平量"
    multi_day_summary: str = ""  # 综合多日趋势描述
    # 跨天分析
    gap_analysis: str = ""       # 近10日跳空缺口及回补状态
    overnight_risk: str = ""     # 隔夜波动风险

    def to_summary(self) -> str:
        """生成决策摘要。"""
        action_emoji = {
            T0Action.ADD: "🟢",
            T0Action.HOLD: "🟡",
            T0Action.REDUCE: "🟠",
            T0Action.CUT: "🔴",
            T0Action.NO_POSITION: "⚪",
        }
        action_text = {
            T0Action.ADD: "可以加仓",
            T0Action.HOLD: "观望等待",
            T0Action.REDUCE: "建议减仓",
            T0Action.CUT: "坚决减仓",
            T0Action.NO_POSITION: "不建议建仓",
        }
        emoji = action_emoji.get(self.action, "❓")
        text = action_text.get(self.action, "未知")
        lines = [
            f"{emoji} {text}  得分 {self.score}",
            f"当前 {self.symbol}  日线: MA5={self.ma5:.2f} MA10={self.ma10:.2f}",
            f"日内: VWAP={self.vwap:.2f} 振幅{self.amplitude:.1f}% 反弹{self.rebound_from_low:+.1f}%",
        ]
        if self.suggested_price > 0:
            lines.append(f"操作价: {self.suggested_price:.2f}  止损: {self.stop_loss:.2f}")
        if self.trigger_condition:
            lines.append(f"触发条件: {self.trigger_condition}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# T+0 决策引擎
# ---------------------------------------------------------------------------


class T0DecisionEngine:
    """T+0 日内交易时机决策引擎。

    输入: 日线 Bar 列表 + 分钟线 Bar 列表（当前交易日）
    输出: T0Result（含评分 + 建议 + 价位）

    用法:
        engine = T0DecisionEngine()
        result = engine.analyze(
            symbol="002460",
            daily_bars=daily_bars,
            minute_bars=today_minute_bars,
            prev_close=61.44,
        )
        print(result.to_summary())
    """

    # 大单阈值（单分钟 > 50万股）
    LARGE_ORDER_THRESHOLD = 500_000
    # 最小分钟数据要求
    MIN_MINUTE_BARS = 10

    def analyze(
        self,
        symbol: str,
        daily_bars: list[Bar],
        minute_bars: list[Bar],
        *,
        prev_close: float = 0.0,
        name: str = "",
    ) -> T0Result:
        """执行 T+0 双维度分析。

        Args:
            symbol: 股票代码
            daily_bars: 近 15-20 根日线 Bar
            minute_bars: 当日分钟线 Bar（仅当前交易日 + 截止当前时间）
            prev_close: 昨日收盘价
            name: 股票名称
        """
        if len(daily_bars) < 5:
            logger.warning("T+0: 日线数据不足 (%d 根)，切换为快照模式", len(daily_bars))
            result = T0Result(
                symbol=symbol, name=name, action=T0Action.HOLD,
                trigger_condition=(
                    "日线K线数据不足（仅{}根），已切换为价格快照模式。"
                    "建议盘中实时运行以获得更精确的均线和支撑阻力位。".format(len(daily_bars))
                ),
            )
            if len(daily_bars) > 0:
                closes = np.array([b.close for b in daily_bars])
                result.ma5 = float(np.mean(closes))
                result.support_1 = float(min(closes))
                result.resistance = float(max(closes))
                # 多日趋势 — 至少标出价格位置
                if n := len(closes) >= 2:
                    chg = (closes[-1] / closes[0] - 1) * 100
                    result.trend_5d = "上升" if chg > 3 else ("下降" if chg < -3 else "震荡")
                    result.multi_day_summary = f"近{n}日: {result.trend_5d} ({chg:+.1f}%)"
            return result

        if len(minute_bars) < 10:
            logger.warning("T+0: 分钟数据不足 (%d 根)，仅做日线分析", len(minute_bars))

        result = T0Result(symbol=symbol, name=name)

        # ── 日线分析 ──
        closes = np.array([b.close for b in daily_bars])
        highs = np.array([b.high for b in daily_bars])
        lows = np.array([b.low for b in daily_bars])
        volumes = np.array([b.volume for b in daily_bars])

        n = len(daily_bars)
        today_bar = daily_bars[-1]
        today_open = today_bar.open
        today_close = closes[-1]

        # 均线
        result.ma5 = float(np.mean(closes[-5:]))
        result.ma10 = float(np.mean(closes[-10:])) if n >= 10 else result.ma5
        result.ma20 = float(np.mean(closes))

        # 支撑阻力
        result.resistance = round(float(max(highs[-10:])), 2)
        result.support_1 = round(float(min(lows[-10:])), 2)

        # K线形态
        result.daily_patterns = self._detect_daily_patterns(daily_bars[-5:])

        # 趋势判断
        chg_5d = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
        chg_3d = (closes[-1] / closes[-4] - 1) * 100 if n >= 4 else 0

        # ── 日内分析 ──
        if len(minute_bars) >= 10:
            self._analyze_intraday(result, minute_bars, prev_close)

        # ── 跨天分析 ──
        self._analyze_gaps(result, daily_bars)
        self._analyze_overnight_risk(result, daily_bars)

        # ── 多日趋势 (需在 overnight_risk 之后，追加庄家布局信号) ──
        self._analyze_multi_day_trend(result, daily_bars)

        # ── 综合评分 ──
        self._score(result, chg_3d, chg_5d)

        return result

    # ------------------------------------------------------------------
    # 日内分析
    # ------------------------------------------------------------------

    def _analyze_intraday(
        self, result: T0Result, bars: list[Bar], prev_close: float,
    ) -> None:
        """分钟级日内分析。"""
        prices = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        vols = np.array([b.volume for b in bars])
        amts = np.array([b.amount for b in bars])
        opens = np.array([b.open for b in bars])

        result.day_high = round(float(max(highs)), 2)
        result.day_low = round(float(min(lows)), 2)
        result.amplitude = round((result.day_high / result.day_low - 1) * 100, 1)

        low_idx = int(np.argmin(lows))
        result.day_low_time = bars[low_idx].timestamp.strftime("%H:%M")
        result.rebound_from_low = round((prices[-1] / result.day_low - 1) * 100, 1)

        # VWAP
        cum_vol = np.cumsum(vols)
        cum_amt = np.cumsum(amts)
        result.vwap = round(float(cum_amt[-1] / cum_vol[-1]) if cum_vol[-1] > 0 else prices[-1], 2)

        # 总成交
        result.total_vol = int(sum(vols))
        result.total_amount = float(sum(amts))

        # 成交量分段 (基于时间)
        n_total = len(bars)
        # 开盘区: 前 1/6
        seg1 = min(max(n_total // 6, 3), n_total)
        # 恐慌区: 1/6 到 1/2
        seg2_start = seg1
        seg2_end = min(max(n_total // 2, seg2_start + 2), n_total)
        # 反弹区: 后半段
        seg3_start = seg2_end

        vol_open_period = float(sum(vols[:seg1]))
        vol_panic_period = float(sum(vols[seg2_start:seg2_end]))
        vol_rebound_period = float(sum(vols[seg3_start:]))
        vol_total = float(sum(vols))

        result.vol_panic_pct = round(vol_panic_period / vol_total * 100, 1) if vol_total > 0 else 0
        result.vol_rebound_pct = round(vol_rebound_period / vol_total * 100, 1) if vol_total > 0 else 0

        # 反弹质量
        fall_vol = vol_open_period + vol_panic_period
        ratio = vol_rebound_period / fall_vol * 100 if fall_vol > 0 else 0
        if ratio < 30:
            result.rebound_quality = "缩量反弹=弱，无有效承接"
        elif ratio > 60:
            result.rebound_quality = "放量反弹=有资金进场"
        else:
            result.rebound_quality = "中性"

        # 大单方向
        result.large_sell_count = sum(
            1 for i in range(len(bars))
            if vols[i] > self.LARGE_ORDER_THRESHOLD and prices[i] < opens[i]
        )
        result.large_buy_count = sum(
            1 for i in range(len(bars))
            if vols[i] > self.LARGE_ORDER_THRESHOLD and prices[i] > opens[i]
        )

        # 分时形态
        result.intraday_pattern = self._detect_intraday_pattern(
            result.day_low, opens[0], result.rebound_from_low,
            prices[-1], result.vwap, result.large_sell_count, result.large_buy_count,
        )

    # ------------------------------------------------------------------
    # 形态识别
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_multi_day_trend(result: T0Result, daily_bars: list[Bar]) -> None:
        """多日趋势分析 — 3日/5日/10日/15日 + 庄家布局检测。"""
        closes = np.array([b.close for b in daily_bars])
        highs = np.array([b.high for b in daily_bars])
        lows = np.array([b.low for b in daily_bars])
        volumes_arr = np.array([b.volume for b in daily_bars])
        n = len(closes)

        # ── 各周期涨跌幅 ──
        def _pct(bars_back: int) -> float:
            if n > bars_back and closes[-1 - bars_back] > 0:
                return (closes[-1] / closes[-1 - bars_back] - 1) * 100
            return 0.0

        def _trend_label(chg: float, threshold: float = 3.0) -> str:
            return "上升" if chg > threshold else ("下降" if chg < -threshold else "震荡")

        if n >= 3:
            c3 = _pct(2)
            result.trend_5d = _trend_label(c3, 3)  # 复用 trend_5d 字段存 3 日趋势
        if n >= 5:
            c5 = _pct(4)
            result.trend_5d = _trend_label(c5, 3)
        if n >= 10:
            c10 = _pct(9)
            result.trend_10d = _trend_label(c10, 5)
        # 15 日趋势 (2~3 周)
        trend_15d = ""
        if n >= 15:
            c15 = _pct(14)
            trend_15d = _trend_label(c15, 7)

        # ── 量能分析 ──
        if len(volumes_arr) >= 15:
            vol_3d = float(np.mean(volumes_arr[-3:]))
            vol_5d = float(np.mean(volumes_arr[-5:]))
            vol_10_15d = float(np.mean(volumes_arr[-15:-5]))
            if vol_10_15d > 0:
                ratio = vol_5d / vol_10_15d
                result.volume_trend = "放量" if ratio > 1.3 else ("缩量" if ratio < 0.7 else "平量")

        # ── 庄家布局检测信号 ──
        manip_signals = []
        if n >= 10:
            # 1. 价量背离：价格下跌但放量 → 可能吸筹；价格上涨但缩量 → 诱多
            price_dir = 1 if closes[-1] > closes[-5] else -1
            vol_dir = 1 if vol_5d > vol_10_15d else -1
            if price_dir < 0 and vol_dir > 0:
                manip_signals.append("⚠️ 近期价跌量增 — 可能有资金在低位吸筹")
            elif price_dir > 0 and vol_dir < 0:
                manip_signals.append("⚠️ 近期价涨量缩 — 上涨动力不足，警惕诱多")
            # 2. 连续缩量阴跌 → 洗盘嫌疑
            if n >= 5:
                down_days = sum(1 for i in range(-5, 0) if closes[i] < closes[i-1])
                vol_shrink = all(volumes_arr[i] < volumes_arr[i-1] for i in range(-5, -1))
                if down_days >= 4 and vol_shrink:
                    manip_signals.append("🔍 连续缩量阴跌 — 洗盘震仓特征，关注是否出现放量阳线确认")
            # 3. 尾盘/集合竞价异常 (简化为收盘价 vs 日内振幅)
            if n >= 3:
                daily_ranges = [(highs[i] - lows[i]) / closes[i] * 100 for i in range(-3, 0)]
                avg_range = np.mean(daily_ranges)
                if avg_range > 5:
                    manip_signals.append(f"📊 近3日日均振幅{avg_range:.1f}% — 高波动需警惕短线资金博弈")
            # 4. 长下影线频率
            if n >= 5:
                lower_shadow_count = 0
                for i in range(-5, 0):
                    body_high = max(closes[i], closes[i-1] if i > -5 else closes[i])
                    body_low = min(closes[i], closes[i-1] if i > -5 else closes[i])
                    lower_shadow = (body_low - lows[i]) / closes[i] * 100 if closes[i] > 0 else 0
                    if lower_shadow > 3:
                        lower_shadow_count += 1
                if lower_shadow_count >= 3:
                    manip_signals.append("🔍 近5日多根长下影线 — 有资金在低位护盘，需确认是支撑还是诱多")

        # ── 综合摘要 ──
        parts = []
        trend_icons = {"上升": "📈", "下降": "📉", "震荡": "➡️"}
        if result.trend_5d:
            parts.append(f"近5日{trend_icons.get(result.trend_5d, '')}{result.trend_5d}({_pct(4):+.1f}%)")
        if result.trend_10d:
            parts.append(f"近10日{result.trend_10d}({_pct(9):+.1f}%)")
        if trend_15d:
            parts.append(f"近15日{trend_15d}({_pct(14):+.1f}%)")
        if result.volume_trend:
            parts.append(f"量能{result.volume_trend}")
        result.multi_day_summary = "，".join(parts)

        # 庄家布局信号追加到 overnight_risk
        if manip_signals:
            extra = "；".join(manip_signals)
            result.overnight_risk = f"{result.overnight_risk}；{extra}" if result.overnight_risk else extra

    @staticmethod
    def _analyze_gaps(result: T0Result, daily_bars: list[Bar]) -> None:
        """跨天缺口分析: 近10日向上/向下跳空缺口及回补状态。"""
        bars = daily_bars[-11:]  # 最多看10个间隔
        if len(bars) < 2:
            return
        gaps = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            curr_open = bars[i].open
            if prev_close <= 0:
                continue
            gap_pct = (curr_open / prev_close - 1) * 100
            bar_date = getattr(bars[i], "timestamp", None) or getattr(bars[i], "date", "")
            if hasattr(bar_date, "strftime"):
                bar_date = bar_date.strftime("%m-%d")
            if gap_pct > 1.5:
                # 向上跳空: 回补条件 = 当日最低价 ≤ 前日收盘价
                filled = bars[i].low <= prev_close if bars[i].low > 0 else False
                status = "已补" if filled else "未补"
                gaps.append(f"{bar_date} ↑{gap_pct:+.1f}%{status}")
            elif gap_pct < -1.5:
                # 向下跳空: 回补条件 = 当日最高价 ≥ 前日收盘价
                filled = bars[i].high >= prev_close if bars[i].high > 0 else False
                status = "已补" if filled else "未补"
                gaps.append(f"{bar_date} ↓{gap_pct:+.1f}%{status}")
        if gaps:
            result.gap_analysis = "；".join(gaps[-5:])  # 最多5个
            # 添加上下文解读
            unfilled = [g for g in gaps if "未补" in g]
            if unfilled:
                result.gap_analysis += f" — {len(unfilled)}个未补缺口构成潜在支撑/阻力"

    @staticmethod
    def _analyze_overnight_risk(result: T0Result, daily_bars: list[Bar]) -> None:
        """隔夜风险: 统计近10日隔夜涨跌幅的标准差。"""
        bars = daily_bars[-11:]
        if len(bars) < 3:
            return
        overnight_changes = []
        for i in range(1, min(len(bars), 11)):
            prev_close = bars[i - 1].close
            curr_open = bars[i].open
            if prev_close > 0:
                overnight = (curr_open / prev_close - 1) * 100
                overnight_changes.append(overnight)
        if overnight_changes:
            import numpy as np
            std = float(np.std(overnight_changes))
            mean = float(np.mean(overnight_changes))
            if std > 2:
                risk_level = f"偏高({std:.1f}%)"
            elif std > 1:
                risk_level = f"正常({std:.1f}%)"
            else:
                risk_level = f"偏低({std:.1f}%)"
            direction = "偏多" if mean > 0.3 else ("偏空" if mean < -0.3 else "中性")
            result.overnight_risk = f"隔夜波动{risk_level} 方向{direction}(均值{mean:+.1f}%)"

    @staticmethod
    def _detect_daily_patterns(bars: list[Bar]) -> list[str]:
        """检测近5日K线形态。"""
        patterns = []
        for bar in bars[-5:]:
            body = abs(bar.close - bar.open)
            upper = bar.high - max(bar.open, bar.close)
            lower = min(bar.open, bar.close) - bar.low
            total_range = bar.high - bar.low
            body_pct = body / total_range * 100 if total_range > 0 else 0

            if lower > body * 2 and upper < body * 0.3 and bar.close > bar.open:
                patterns.append(f"{bar.timestamp.strftime('%m-%d')} 锤子线(底反)")
            elif upper > body * 2 and lower < body * 0.3 and bar.close < bar.open:
                patterns.append(f"{bar.timestamp.strftime('%m-%d')} 射击之星(顶反)")
            elif body_pct < 20:
                patterns.append(f"{bar.timestamp.strftime('%m-%d')} 十字星")
            elif body_pct > 60:
                kind = "大阳线" if bar.close > bar.open else "大阴线"
                patterns.append(f"{bar.timestamp.strftime('%m-%d')} {kind}")
        return patterns

    @staticmethod
    def _detect_intraday_pattern(
        day_low: float, today_open: float, rebound_pct: float,
        curr_price: float, vwap: float,
        large_sell: int, large_buy: int,
    ) -> str:
        """识别分时形态。"""
        parts = []
        if day_low < today_open * 0.95:
            if rebound_pct < 1.5:
                parts.append("单边下跌型 — 无反弹，空头完全控盘")
            elif rebound_pct < 3:
                parts.append("急跌弱反弹 — 反弹量能不足，可能二次探底")
            else:
                parts.append("V型反弹 — 关注能否站上VWAP确认反转")

        if curr_price < vwap and curr_price > day_low * 1.02:
            parts.append(f"二次探底风险 — 当前在VWAP下方，若回落将测试前低{day_low:.2f}")

        if large_sell > large_buy * 2:
            parts.append("机构出货 — 大单卖出碾压买入")

        return " | ".join(parts) if parts else "无特殊形态"

    # ------------------------------------------------------------------
    # 综合评分
    # ------------------------------------------------------------------

    def _score(self, result: T0Result, chg_3d: float, chg_5d: float) -> None:
        """综合日线+日内信号打分。"""
        score = 0
        curr = result.vwap if result.vwap > 0 else 0
        # fallback: use daily close if no intraday
        if curr == 0:
            curr = result.ma5  # rough fallback

        # ── 日线信号 ──
        # 均线
        if curr < result.ma5:
            score -= 15
            result.signals_bear.append(T0Signal("bear", -15, "daily",
                f"跌破MA5({result.ma5:.2f})，短线空头趋势"))
        if result.ma10 > 0 and curr < result.ma10:
            score -= 10
            result.signals_bear.append(T0Signal("bear", -10, "daily",
                f"跌破MA10({result.ma10:.2f})，中期走弱"))

        # 距支撑位
        if result.support_1 > 0:
            dist_s1 = (curr / result.support_1 - 1) * 100
            if dist_s1 < 2:
                score += 10
                result.signals_bull.append(T0Signal("bull", 10, "daily",
                    f"距支撑S1({result.support_1})仅{dist_s1:.1f}%，下跌空间有限"))
            elif dist_s1 > 8:
                score -= 10
                result.signals_bear.append(T0Signal("bear", -10, "daily",
                    f"距支撑S1({result.support_1})还有{dist_s1:.1f}%，下行风险大"))

        # 超卖
        if chg_3d < -10:
            score += 5
            result.signals_bull.append(T0Signal("bull", 5, "daily",
                f"3日跌{chg_3d:.1f}%，短线超卖有反弹需求"))

        # Phase 13: 超跌反弹信号增强
        # 5日跌幅（比3日更强的信号）
        if chg_5d < -15:
            score += 10
            result.signals_bull.append(T0Signal("bull", 10, "daily",
                f"5日跌{chg_5d:.1f}%，深度超卖，反弹动能积累"))
        elif chg_5d < -10:
            score += 5
            result.signals_bull.append(T0Signal("bull", 5, "daily",
                f"5日跌{chg_5d:.1f}%，短线超卖"))

        # 阶段跌幅：从 30 日最高点计算
        if hasattr(self, '_daily_bars') and self._daily_bars:
            try:
                import numpy as np
                bars_sorted = sorted(self._daily_bars, key=lambda b: b.timestamp)
                closes_arr = np.array([b.close for b in bars_sorted])
                if len(closes_arr) >= 10:
                    high_30d = float(np.max(closes_arr[-30:]))
                    phase_decline = (high_30d - closes_arr[-1]) / high_30d * 100
                    if phase_decline >= 25:
                        score += 15
                        result.signals_bull.append(T0Signal("bull", 15, "daily",
                            f"阶段跌幅{phase_decline:.1f}% — 超跌反弹候选（25%规则触发）"))
                    elif phase_decline >= 20:
                        score += 8
                        result.signals_bull.append(T0Signal("bull", 8, "daily",
                            f"阶段跌幅{phase_decline:.1f}% — 接近超跌阈值"))
            except Exception:
                pass

        # ── 日内信号 ──
        if result.vwap > 0:
            vwap_dist = (curr / result.vwap - 1) * 100
            if vwap_dist < -2:
                score -= 15
                result.signals_bear.append(T0Signal("bear", -15, "intraday",
                    f"低于VWAP {vwap_dist:.1f}%，日内套牢盘重"))
            elif vwap_dist > 1:
                score += 10
                result.signals_bull.append(T0Signal("bull", 10, "intraday",
                    "站上VWAP，日内趋势偏多"))

        # 大单
        if result.large_sell_count > result.large_buy_count * 2:
            score -= 15
            result.signals_bear.append(T0Signal("bear", -15, "intraday",
                f"大单卖出碾压 ({result.large_sell_count}:{result.large_buy_count})，机构出货"))
        elif result.large_buy_count > result.large_sell_count:
            score += 10
            result.signals_bull.append(T0Signal("bull", 10, "intraday",
                f"大单买入占优 ({result.large_buy_count}:{result.large_sell_count})"))

        # 反弹质量
        if result.rebound_quality.startswith("缩量"):
            score -= 10
            result.signals_bear.append(T0Signal("bear", -10, "intraday",
                "反弹缩量，无有效承接"))
        elif result.rebound_quality.startswith("放量"):
            score += 10
            result.signals_bull.append(T0Signal("bull", 10, "intraday",
                "放量反弹，有资金进场"))

        # 振幅风险
        if result.amplitude > 8:
            score -= 5
            result.signals_bear.append(T0Signal("bear", -5, "intraday",
                f"日内振幅{result.amplitude:.1f}%，极端波动"))

        # 反弹幅度
        if result.rebound_from_low > 3:
            score += 5
            result.signals_bull.append(T0Signal("bull", 5, "intraday",
                f"从低点反弹{result.rebound_from_low:.1f}%，有抄底盘"))

        # ── 庄家操纵检测 (Phase 10) ──
        try:
            from src.game_theory.manipulation import ManipulationDetector
            detector = ManipulationDetector()
            # 使用当前可用的分钟数据
            if hasattr(self, '_minute_data') and self._minute_data is not None:
                manip_result = detector.detect("", self._minute_data)
                if manip_result.signals:
                    for sig in manip_result.signals:
                        if sig.playbook_id == "lure_bull_dump" and sig.confidence >= 0.6:
                            score -= 20
                            result.signals_bear.append(T0Signal(
                                "bear", -20, "manipulation",
                                f"⚠️ 疑似诱多出货 (置信度 {sig.confidence:.0%}): {sig.suggestion[:60]}"
                            ))
                        elif sig.playbook_id == "fishing_line" and sig.confidence >= 0.6:
                            score -= 25
                            result.signals_bear.append(T0Signal(
                                "bear", -25, "manipulation",
                                f"🔴 疑似钓鱼线出货 (置信度 {sig.confidence:.0%}): {sig.suggestion[:60]}"
                            ))
                        elif sig.playbook_id == "lure_bear_accumulate" and sig.confidence >= 0.5:
                            score -= 10
                            result.signals_bear.append(T0Signal(
                                "bear", -10, "manipulation",
                                f"⚠️ 疑似诱空吸筹 (置信度 {sig.confidence:.0%})，谨慎操作"
                            ))
                        elif sig.playbook_id == "closing_manipulation" and sig.confidence >= 0.5:
                            score -= 5
                            result.signals_bear.append(T0Signal(
                                "bear", -5, "manipulation",
                                f"⚠️ 尾盘异动 (置信度 {sig.confidence:.0%})，次日可能反向"
                            ))
        except Exception:
            pass  # 操纵检测失败不影响主流程

        result.score = score

        # ── 决策映射 ──
        vwap_val = result.vwap if result.vwap > 0 else curr
        day_low_val = result.day_low if result.day_low > 0 else result.support_1

        if score >= 20:
            result.action = T0Action.ADD
            result.suggested_price = round(vwap_val, 2)
            result.stop_loss = round(day_low_val * 0.99, 2)
            result.trigger_condition = f"分2批在VWAP({vwap_val:.2f})附近加仓"
        elif score >= 0:
            result.action = T0Action.HOLD
            result.suggested_price = 0.0
            result.stop_loss = 0.0
            result.trigger_condition = f"放量站上VWAP({vwap_val:.2f})可轻仓试探"
        elif score >= -25:
            result.action = T0Action.REDUCE
            result.suggested_price = round(vwap_val, 2)
            result.stop_loss = 0.0
            fib_382 = round(
                result.day_low + (result.day_high - result.day_low) * 0.382, 2
            ) if result.day_high > result.day_low else vwap_val
            result.trigger_condition = f"反弹至VWAP({vwap_val:.2f})或Fib0.382({fib_382})附近减仓"
        else:
            result.action = T0Action.CUT
            result.suggested_price = round(vwap_val, 2)
            result.stop_loss = 0.0
            result.trigger_condition = (
                f"反弹至VWAP({vwap_val:.2f})附近减仓；"
                f"重新进场需日线止跌+日内放量站VWAP+大单买入占优"
            )
