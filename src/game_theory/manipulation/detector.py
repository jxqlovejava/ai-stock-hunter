# -*- coding: utf-8 -*-
"""庄家操盘手法检测器 (ManipulationDetector)。

基于分钟级行情数据，实时识别 7 种经典庄家操纵模式。
输入: 分钟级 OHLCV DataFrame (来自 mootdx/T+0 数据管道)
输出: ManipulationResult (风险评分 + 匹配的操盘手法 + 建议)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd


def _safe_float(val) -> float:
    """安全转换为 float，处理 Series/ndarray/None。"""
    if val is None:
        return 0.0
    if isinstance(val, (pd.Series, np.ndarray)):
        if len(val) == 0:
            return 0.0
        return float(val.iloc[0]) if hasattr(val, "iloc") else float(val.flat[0])
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ── 检测阈值常量 ──

# 诱多出货
LURE_BULL_BREAKOUT_PCT = 0.02       # 突破前高幅度
LURE_BULL_VOL_RATIO = 2.0           # 突破时量比
LURE_BULL_DROPDOWN_PCT = 0.015      # 突破后回落幅度
LURE_BULL_WINDOW_MINUTES = 30       # 检测窗口 (分钟)

# 诱空吸筹
LURE_BEAR_DROP_PCT = 0.03           # 急跌幅度
LURE_BEAR_VOL_RATIO = 1.5           # 急跌时量比
LURE_BEAR_REBOUND_PCT = 0.02        # V 型反弹幅度
LURE_BEAR_WINDOW_MINUTES = 60       # 检测窗口

# 对倒拉升
WASH_TRADE_VOL_RATIO = 3.0          # 量比
WASH_TRADE_PRICE_CHANGE_MAX = 0.005 # 价格变动上限
WASH_TRADE_DURATION_MINUTES = 30    # 最少持续时间

# 洗盘震仓
SHAKEOUT_DROP_PCT = 0.05            # 急跌幅度
SHAKEOUT_REBOUND_PCT = 0.03         # V 型反弹幅度

# 分时钓鱼线
FISHING_LINE_RISE_PCT = 0.05        # 快速拉升幅度
FISHING_LINE_RISE_MINUTES = 15      # 拉升时间窗口
FISHING_LINE_DECLINE_PCT = 0.5      # 阴跌吃掉拉升幅度的比例
FISHING_LINE_DECLINE_MINUTES = 60   # 阴跌时间窗口

# 尾盘偷袭
CLOSING_TIME_START = "14:50"        # 尾盘开始时间
CLOSING_MOVE_PCT = 0.02             # 尾盘异动幅度
CLOSING_VOLUME_RATIO = 0.15         # 尾盘成交量占比

# 大单阈值
LARGE_ORDER_SHARES = 500_000        # 大单定义 (> 50万股/分钟)


@dataclass
class ManipulationSignal:
    """单个操纵信号。"""

    playbook_id: str          # 匹配的操盘手法 ID
    playbook_name: str        # 中文名
    confidence: float         # 匹配置信度 0.0-1.0
    risk_level: str           # "high" / "medium" / "low"
    detected_at: str          # 检测时间 HH:MM
    evidence: list[str] = field(default_factory=list)  # 匹配的证据点
    suggestion: str = ""      # 建议操作


@dataclass
class ManipulationResult:
    """庄家操纵检测完整结果。"""

    symbol: str = ""
    name: str = ""
    date: str = ""
    risk_score: float = 0.0          # 0-100 综合操纵风险评分
    signals: list[ManipulationSignal] = field(default_factory=list)
    risk_level: str = "low"          # "high" / "medium" / "low"
    summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)


class ManipulationDetector:
    """庄家操盘手法实时检测器。

    用法:
        detector = ManipulationDetector()
        result = detector.detect("600089", minute_df)
    """

    def detect(
        self, symbol: str, minute_data: pd.DataFrame, name: str = ""
    ) -> ManipulationResult:
        """执行全部 7 种操纵模式检测。

        Args:
            symbol: 6 位股票代码
            minute_data: 分钟级 OHLCV DataFrame
                (columns: open, close, high, low, volume, amount, datetime)
            name: 股票名称

        Returns:
            ManipulationResult with risk_score, signals, summary
        """
        if minute_data.empty or len(minute_data) < 30:
            return ManipulationResult(
                symbol=symbol,
                name=name,
                risk_score=0,
                signals=[],
                risk_level="low",
                summary="数据不足 (< 30 分钟)，无法进行操纵检测",
            )

        # 确保有 datetime 列
        if "datetime" not in minute_data.columns and hasattr(minute_data.index, "strftime"):
            minute_data = minute_data.copy()
            minute_data["datetime"] = minute_data.index.astype(str)

        date_str = str(minute_data.iloc[0].get("datetime", ""))[:10] or datetime.now().strftime("%Y-%m-%d")

        signals: list[ManipulationSignal] = []

        # 执行 7 种检测
        signals.append(self._detect_lure_bull(minute_data))
        signals.append(self._detect_lure_bear(minute_data))
        signals.append(self._detect_wash_trade(minute_data))
        signals.append(self._detect_shakeout(minute_data))
        signals.append(self._detect_fishing_line(minute_data))
        signals.append(self._detect_closing_pump(minute_data))
        signals.append(self._detect_closing_dump(minute_data))

        # 过滤空信号
        signals = [s for s in signals if s is not None]

        # 计算综合风险评分
        risk_score = self._calc_risk_score(signals)

        # 风险等级
        if risk_score >= 70:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        # 生成摘要
        summary = self._generate_summary(signals, risk_score, risk_level)

        return ManipulationResult(
            symbol=symbol,
            name=name,
            date=date_str,
            risk_score=round(risk_score, 1),
            signals=signals,
            risk_level=risk_level,
            summary=summary,
        )

    # ────────────────────────────────────────────────────
    # 检测 1: 诱多出货
    # ────────────────────────────────────────────────────

    def _detect_lure_bull(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测诱多出货模式: 虚假突破→放量滞涨→跳水。

        检测逻辑:
        1. 盘中突破前 3 日高点 (或日内前高) > 2%
        2. 突破时量比 > 2.0
        3. 突破后 30 分钟内价格回落 > 1.5%
        4. 回落时量能萎缩
        """
        if "close" not in df.columns:
            return None

        close = df["close"].values
        volume = df["volume"].values if "volume" in df.columns else None
        n = len(close)

        # 找盘中最高点
        high_idx = int(np.argmax(close))

        # 最高点必须在数据前半段之后
        if high_idx < n * 0.2 or high_idx > n * 0.8:
            return None

        # 最高点之前的价格
        pre_high = close[:high_idx]
        if len(pre_high) == 0:
            return None
        pre_max = _safe_float(np.max(pre_high))

        # 最高点之后的价格
        post_high = close[high_idx:]
        if len(post_high) < 5:
            return None
        post_last = _safe_float(post_high[-1])

        # 条件 1: 突破幅度 > 2%
        peak_price = _safe_float(close[high_idx])
        if pre_max > 0 and (peak_price - pre_max) / pre_max < LURE_BULL_BREAKOUT_PCT:
            return None

        # 条件 2: 突破时量比 > 2.0
        if volume is not None:
            peak_vol = _safe_float(volume[high_idx])
            avg_vol = _safe_float(volume[:high_idx].mean()) if len(volume[:high_idx]) > 0 else 1
            if avg_vol > 0 and peak_vol / avg_vol < LURE_BULL_VOL_RATIO:
                return None

        # 条件 3: 突破后回落 > 1.5%
        if post_last < peak_price:
            dropdown = (peak_price - post_last) / peak_price
            if dropdown < LURE_BULL_DROPDOWN_PCT:
                return None
        else:
            return None  # 没回落, 不是诱多

        # 条件 4: 回落时量能萎缩
        vol_decaying = False
        if volume is not None and len(post_high) >= 10:
            first_half_vol = _safe_float(volume[high_idx:high_idx + len(post_high) // 2].mean())
            second_half_vol = _safe_float(volume[high_idx + len(post_high) // 2:].mean())
            vol_decaying = second_half_vol < first_half_vol * 0.8

        confidence = 0.75 if vol_decaying else 0.55
        evidence = [
            f"盘中高点 {peak_price:.2f} 突破前高 {pre_max:.2f} ({(peak_price-pre_max)/pre_max*100:.1f}%)",
            f"突破后回落至 {post_last:.2f} (跌幅 {(peak_price-post_last)/peak_price*100:.1f}%)",
        ]
        if vol_decaying:
            evidence.append("回落时量能逐步萎缩 (庄家出货完成)")

        return ManipulationSignal(
            playbook_id="lure_bull_dump",
            playbook_name="诱多出货 (虚假突破→高位放量→跳水)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=df.iloc[high_idx].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=evidence,
            suggestion="⚠️ 疑似诱多出货，追高风险极大。建议等待回落确认后再考虑入场。",
        )

    # ────────────────────────────────────────────────────
    # 检测 2: 诱空吸筹
    # ────────────────────────────────────────────────────

    def _detect_lure_bear(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测诱空吸筹模式: 砸盘破位→散户割肉→快速拉回。"""
        if "close" not in df.columns:
            return None

        close = df["close"].values
        volume = df["volume"].values if "volume" in df.columns else None
        n = len(close)

        low_idx = int(np.argmin(close))

        if low_idx < n * 0.1 or low_idx > n * 0.7:
            return None

        # 最低点之前
        pre_low = close[:low_idx]
        # 最低点之后
        post_low = close[low_idx:]

        if len(pre_low) < 5 or len(post_low) < 5:
            return None

        pre_open = _safe_float(pre_low[0])
        low_price = _safe_float(close[low_idx])
        post_last = _safe_float(post_low[-1])

        # 条件 1: 急跌 > 3%
        if pre_open > 0 and (pre_open - low_price) / pre_open < LURE_BEAR_DROP_PCT:
            return None

        # 条件 2: V 型反弹 > 2%
        if low_price > 0 and (post_last - low_price) / low_price < LURE_BEAR_REBOUND_PCT:
            return None

        # 条件 3: 下跌放量
        vol_confirmed = False
        if volume is not None:
            drop_vol = _safe_float(volume[:low_idx].mean())
            rebound_vol = _safe_float(volume[low_idx:].mean())
            if drop_vol > rebound_vol * 1.2:
                vol_confirmed = True

        confidence = 0.70 if vol_confirmed else 0.50
        evidence = [
            f"盘中急跌 {(pre_open-low_price)/pre_open*100:.1f}% 破位",
            f"V 型反弹 {(post_last-low_price)/low_price*100:.1f}%",
        ]
        if vol_confirmed:
            evidence.append("下跌放量 (散户出逃) → 反弹缩量 (庄家锁仓)")

        return ManipulationSignal(
            playbook_id="lure_bear_accumulate",
            playbook_name="诱空吸筹 (砸盘破位→散户割肉→快速拉回)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=df.iloc[low_idx].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=evidence,
            suggestion="⚠️ 疑似诱空吸筹，恐慌割肉可能卖在最低点。已有持仓建议观察反弹力度再决定。",
        )

    # ────────────────────────────────────────────────────
    # 检测 3: 对倒拉升
    # ────────────────────────────────────────────────────

    def _detect_wash_trade(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测对倒拉升: 量比极高但价格几乎不动。"""
        if "close" not in df.columns or "volume" not in df.columns:
            return None

        # 取最近 60 分钟
        if len(df) < 60:
            return None
        recent = df.tail(60)

        close = recent["close"].values
        volume = recent["volume"].values

        # 计算量比
        if len(df) > 120:
            baseline_vol = _safe_float(df["volume"].iloc[-120:-60].mean())
        else:
            baseline_vol = _safe_float(volume[:30].mean())

        recent_vol = _safe_float(volume[-30:].mean())

        if baseline_vol <= 0:
            return None

        vol_ratio = recent_vol / baseline_vol

        if vol_ratio < WASH_TRADE_VOL_RATIO:
            return None

        # 价格变动
        price_start = _safe_float(close[0])
        price_end = _safe_float(close[-1])
        if price_start <= 0:
            return None
        price_change = abs(price_end - price_start) / price_start

        if price_change > WASH_TRADE_PRICE_CHANGE_MAX:
            return None

        confidence = 0.65 if vol_ratio > 4.0 else 0.50

        return ManipulationSignal(
            playbook_id="wash_trade_pump",
            playbook_name="对倒拉升 (自买自卖→量价齐升假象)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=recent.iloc[-1].get("datetime", "")[-8:] if "datetime" in recent.columns else "",
            evidence=[
                f"量比 {vol_ratio:.1f}x (异常放量)",
                f"价格变动仅 {price_change*100:.2f}% (几乎不动)",
                "疑似庄家利用拖拉机账户对倒制造虚假成交量",
            ],
            suggestion="⚠️ 疑似对倒交易，量价背离。不建议跟风追入，等待真实方向确认。",
        )

    # ────────────────────────────────────────────────────
    # 检测 4: 洗盘震仓
    # ────────────────────────────────────────────────────

    def _detect_shakeout(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测洗盘震仓: 急跌 5-8%→V 型反弹。"""
        if "close" not in df.columns:
            return None

        close = df["close"].values
        volume = df["volume"].values if "volume" in df.columns else None
        n = len(close)

        low_idx = int(np.argmin(close))

        if low_idx < n * 0.1 or low_idx > n * 0.6:
            return None

        pre_low = close[:low_idx]
        post_low = close[low_idx:]

        if len(pre_low) < 5 or len(post_low) < 10:
            return None

        open_price = _safe_float(pre_low[0])
        low_price = _safe_float(close[low_idx])
        close_price = _safe_float(post_low[-1])

        # 跌幅需 > 5%
        if open_price > 0 and (open_price - low_price) / open_price < SHAKEOUT_DROP_PCT:
            return None

        # 反弹需 > 3%
        if low_price > 0 and (close_price - low_price) / low_price < SHAKEOUT_REBOUND_PCT:
            return None

        # 检查 V 型: 反弹过程中未再次破新低
        post_low_min = _safe_float(np.min(post_low))
        if post_low_min < low_price * 0.99:
            return None  # 二次探底, 不是 V 型反弹

        # 检查成交量: 下跌放量 → 反弹缩量
        vol_pattern = False
        if volume is not None:
            drop_vol = _safe_float(volume[:low_idx].mean())
            rebound_vol = _safe_float(volume[low_idx:].mean())
            vol_pattern = drop_vol > rebound_vol

        confidence = 0.70 if vol_pattern else 0.55

        return ManipulationSignal(
            playbook_id="shakeout",
            playbook_name="洗盘震仓 (急跌→制造恐慌→低位吸筹)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=df.iloc[low_idx].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=[
                f"盘中急跌 {(open_price-low_price)/open_price*100:.1f}%",
                f"V 型反弹至 {close_price:.2f} ({(close_price-low_price)/low_price*100:.1f}%)",
            ],
            suggestion="⚠️ 疑似洗盘震仓，急跌可能是庄家制造恐慌。已有持仓不建议在急跌时割肉。",
        )

    # ────────────────────────────────────────────────────
    # 检测 5: 分时钓鱼线
    # ────────────────────────────────────────────────────

    def _detect_fishing_line(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测分时钓鱼线: 15 分钟内直线拉升 5%→60 分钟持续阴跌。"""
        if "close" not in df.columns:
            return None

        close = df["close"].values
        volume = df["volume"].values if "volume" in df.columns else None
        n = len(close)

        if n < 90:
            return None

        # 滑动窗口检测快速拉升
        best_rise = 0.0
        best_start = 0
        best_end = 0

        window = min(FISHING_LINE_RISE_MINUTES, n // 3)
        for i in range(n - window * 2):
            start_p = _safe_float(close[i])
            # 找窗口内最高点
            segment = close[i:i + window]
            peak_p = _safe_float(np.max(segment))
            rise = (peak_p - start_p) / start_p if start_p > 0 else 0
            if rise > best_rise:
                best_rise = rise
                best_start = i
                best_end = i + int(np.argmax(segment))

        if best_rise < FISHING_LINE_RISE_PCT:
            return None

        # 拉升后的走势
        post_rise = close[best_end:]
        if len(post_rise) < 10:
            return None

        peak_price = _safe_float(close[best_end])
        post_end = _safe_float(post_rise[-1])

        # 阴跌吃掉拉升幅度的 50%+
        if peak_price > 0:
            decline = (peak_price - post_end) / peak_price
            rise_amount = peak_price - _safe_float(close[best_start])
            decline_amount = peak_price - post_end

            if rise_amount <= 0 or decline_amount / rise_amount < FISHING_LINE_DECLINE_PCT:
                return None

        else:
            return None

        # 阴跌中量能萎缩
        vol_confirmed = False
        if volume is not None and len(post_rise) >= 20:
            first_half = _safe_float(volume[best_end:best_end + len(post_rise) // 2].mean())
            second_half = _safe_float(volume[best_end + len(post_rise) // 2:].mean())
            vol_confirmed = second_half < first_half * 0.7

        confidence = 0.80 if vol_confirmed and decline_amount / rise_amount > 0.7 else 0.60

        return ManipulationSignal(
            playbook_id="fishing_line",
            playbook_name="分时钓鱼线 (直线拉升→缓慢阴跌出货)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=df.iloc[best_end].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=[
                f"快速拉升 {best_rise*100:.1f}% (约 {best_end-best_start} 分钟)",
                f"随后阴跌 {decline_amount/peak_price*100:.1f}% (吃掉涨幅 {decline_amount/rise_amount*100:.0f}%)",
            ],
            suggestion="🔴 经典钓鱼线出货形态！拉升时追入风险极高，建议立即回避。已持仓应考虑减仓。",
        )

    # ────────────────────────────────────────────────────
    # 检测 6: 尾盘拉升
    # ────────────────────────────────────────────────────

    def _detect_closing_pump(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测尾盘拉升: 14:50 后异常拉升 > 2%。"""
        if "datetime" not in df.columns:
            return None

        # 找尾盘数据 (14:50 之后)
        closing_rows = df[df["datetime"].astype(str).str.contains("14:5|15:0")]
        if len(closing_rows) < 3:
            return None

        close = closing_rows["close"].values
        volume = closing_rows["volume"].values if "volume" in closing_rows.columns else None

        start_p = _safe_float(close[0])
        end_p = _safe_float(close[-1])

        if start_p <= 0:
            return None

        change = (end_p - start_p) / start_p

        if change < CLOSING_MOVE_PCT:
            return None

        # 检查尾盘成交量占比
        vol_ratio_ok = True
        if volume is not None and "volume" in df.columns:
            closing_vol = _safe_float(closing_rows["volume"].sum())
            total_vol = _safe_float(df["volume"].sum())
            if total_vol > 0:
                vol_ratio_ok = closing_vol / total_vol > CLOSING_VOLUME_RATIO

        confidence = 0.75 if vol_ratio_ok else 0.55

        return ManipulationSignal(
            playbook_id="closing_manipulation",
            playbook_name="尾盘偷袭拉升 (操纵收盘价→次日高开出货)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at="14:50-15:00",
            evidence=[
                f"尾盘 10 分钟涨幅 {change*100:.1f}%",
                f"尾盘成交量占比 {'> ' if vol_ratio_ok else '< '}{int(CLOSING_VOLUME_RATIO*100)}%",
            ],
            suggestion="⚠️ 尾盘异常拉升，可能是庄家操纵收盘价。次日大概率低开，不建议尾盘追涨。",
        )

    # ────────────────────────────────────────────────────
    # 检测 7: 尾盘砸盘
    # ────────────────────────────────────────────────────

    def _detect_closing_dump(self, df: pd.DataFrame) -> ManipulationSignal | None:
        """检测尾盘砸盘: 14:50 后异常下跌 > 2%。"""
        if "datetime" not in df.columns:
            return None

        closing_rows = df[df["datetime"].astype(str).str.contains("14:5|15:0")]
        if len(closing_rows) < 3:
            return None

        close = closing_rows["close"].values
        volume = closing_rows["volume"].values if "volume" in closing_rows.columns else None

        start_p = _safe_float(close[0])
        end_p = _safe_float(close[-1])

        if start_p <= 0:
            return None

        change = (end_p - start_p) / start_p

        if change > -CLOSING_MOVE_PCT:
            return None

        vol_ratio_ok = True
        if volume is not None and "volume" in df.columns:
            closing_vol = _safe_float(closing_rows["volume"].sum())
            total_vol = _safe_float(df["volume"].sum())
            if total_vol > 0:
                vol_ratio_ok = closing_vol / total_vol > CLOSING_VOLUME_RATIO

        confidence = 0.75 if vol_ratio_ok else 0.55

        return ManipulationSignal(
            playbook_id="closing_manipulation",
            playbook_name="尾盘偷袭砸盘 (打压收盘价→次日低价吸筹)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at="14:50-15:00",
            evidence=[
                f"尾盘 10 分钟跌幅 {abs(change)*100:.1f}%",
                f"尾盘成交量占比 {'> ' if vol_ratio_ok else '< '}{int(CLOSING_VOLUME_RATIO*100)}%",
            ],
            suggestion="⚠️ 尾盘异常砸盘，可能是庄家打压股价以便次日低价吸筹。已有持仓不建议尾盘恐慌卖出。",
        )

    # ────────────────────────────────────────────────────
    # 风险评分 + 摘要
    # ────────────────────────────────────────────────────

    def _calc_risk_score(self, signals: list[ManipulationSignal]) -> float:
        """加权计算综合操纵风险评分。

        权重分配:
          诱多出货: 0.25 | 诱空吸筹: 0.15 | 对倒拉升: 0.20
          洗盘震仓: 0.15 | 钓鱼线: 0.15 | 尾盘异动: 0.10
        """
        if not signals:
            return 0.0

        weights = {
            "lure_bull_dump": 0.25,
            "lure_bear_accumulate": 0.15,
            "wash_trade_pump": 0.20,
            "shakeout": 0.15,
            "fishing_line": 0.15,
            "closing_manipulation": 0.10,
        }

        score = 0.0
        total_weight = 0.0
        for s in signals:
            w = weights.get(s.playbook_id, 0.10)
            score += s.confidence * 100 * w
            total_weight += w

        return min(100, score / max(total_weight, 0.01))

    def _generate_summary(
        self, signals: list[ManipulationSignal], risk_score: float, risk_level: str
    ) -> str:
        """生成操纵风险评估摘要。"""
        if not signals:
            return "🟢 未检测到明显的庄家操纵迹象。"

        level_emoji = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(risk_level, "🟢")
        lines = [
            f"{level_emoji} 庄家操纵风险: {risk_level.upper()} (评分 {risk_score:.0f}/100)",
            f"检测到 {len(signals)} 个可疑信号:",
        ]
        for s in signals:
            lines.append(
                f"  • {s.playbook_name} (置信度 {s.confidence:.0%}, 风险 {s.risk_level})"
            )

        # 最高风险信号
        high_signals = [s for s in signals if s.risk_level == "high"]
        if high_signals:
            lines.append(f"\n🔴 高风险信号: {high_signals[0].suggestion}")

        return "\n".join(lines)
