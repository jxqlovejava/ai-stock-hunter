# -*- coding: utf-8 -*-
"""洗盘阶段操纵手法检测器 (WashoutDetector)。

基于分钟级和日线行情数据，识别洗盘阶段经典庄家操纵模式:
  日内: 急跌 / 高开低走 / 低开高走 / 分时单边下跌 / 持续压低
  日级: 连续阴线 / 击穿支撑 / 小涨大跌
  生命周期（互补，不重复形态）: 多波洗盘→后半段割肉→砸不动→拉升候选
    见 ``wash_cycle.WashCycleAnalyzer`` / playbook ``wash_then_markup``

设计原则:
  - 复用现有 ManipulationSignal / ManipulationResult 输出格式
  - 阈值常量集中定义，便于调参
  - 检测方法独立，可单独调用或批量运行
  - 多波生命周期只做状态机，不重复单日形态检测
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

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

# 股价异常 — 价格急跌
WASHOUT_SHARP_DROP_PCT = 0.04           # 急跌幅度 ≥ 4%
WASHOUT_SHARP_DROP_MINUTES = 15         # 急跌发生在 15 分钟内
WASHOUT_SHARP_DROP_VOL_RATIO = 2.0      # 急跌时量比 ≥ 2.0
WASHOUT_SHARP_DROP_PRE_STABLE = 30      # 急跌前至少平稳运行 30 分钟

# 开盘异常 — 高开低走
WASHOUT_HIGH_OPEN_PCT = 0.03           # 高开 ≥ 3%
WASHOUT_HIGH_OPEN_CLOSE_NEAR_LOW = 0.20  # 收盘在日振幅底部 20% 内
WASHOUT_HIGH_OPEN_VOL_RATIO = 1.5      # 量比 > 1.5x
WASHOUT_HIGH_OPEN_MIN_MINUTES = 60     # 最少交易分钟数

# 开盘异常 — 低开高走
WASHOUT_LOW_OPEN_PCT = 0.03            # 低开 ≥ 3%
WASHOUT_LOW_OPEN_CLOSE_NEAR_HIGH = 0.20  # 收盘在日振幅顶部 20% 内
WASHOUT_LOW_OPEN_VOL_RATIO = 1.5       # 量比 > 1.5x

# 分时单边下跌
WASHOUT_DECLINE_WAVES_MIN = 3          # 至少 3 波下跌
WASHOUT_DECLINE_BOUNCE_MAX = 0.30      # 反弹不超过跌幅的 30%
WASHOUT_DECLINE_DIVE_PCT = 0.005       # 单分钟跳水 > 0.5%
WASHOUT_DECLINE_MIN_MINUTES = 120      # 至少覆盖 2 小时交易

# 持续压低
WASHOUT_SUPPRESSION_MIN_MINUTES = 60   # 至少持续 60 分钟
WASHOUT_SUPPRESSION_MAX_REBOUND = 0.002  # 任何反弹 < 0.2%
WASHOUT_SUPPRESSION_NEG_PCT = 0.65     # 至少 65% 的K线收阴

# 连续阴线洗盘
WASHOUT_YIN_MIN_DAYS = 6               # 最少连续 6 根阴线
WASHOUT_YIN_MAX_DAYS = 15              # 超过此数可能是出货而非洗盘
WASHOUT_YIN_VOL_DECLINE_PCT = 0.30     # 量能递减 > 30%
WASHOUT_YIN_PRICE_DROP_MAX = 0.20      # 累计跌幅 < 20%（跌幅过大→出货）

# 击穿支撑
WASHOUT_SUPPORT_MA_PERIODS = (20, 60)  # 关键均线周期
WASHOUT_SUPPORT_VOL_SPIKE = 1.5        # 破位日放量 ≥ 1.5x 前5日均量
WASHOUT_SUPPORT_BREAK_PCT = 0.02       # 跌破幅度 > 2%

# 小涨大跌
WASHOUT_SMALL_RISE_MAX = 0.02          # 小阳涨幅 < 2%
WASHOUT_BIG_DROP_MIN = 0.04            # 大阴跌幅 > 4%
WASHOUT_SRD_WINDOW = 3                 # 检测窗口 (天, 最小需3天检测二阴夹一阳)

# 二次洗 + 长下影（视频：再砸后长下影收针洗掉最后一批）
WASHOUT_LLS_LOWER_SHADOW_RATIO = 0.55  # 下影线 / 全振幅 ≥ 55%
WASHOUT_LLS_BODY_MAX_RATIO = 0.35      # 实体 / 振幅 ≤ 35%
WASHOUT_LLS_PRIOR_DROP_MIN = 0.03      # 前 3 日累计跌 ≥ 3%
WASHOUT_LLS_RANGE_MIN = 0.02           # 当日振幅 ≥ 2%


# ── 复用现有数据模型 ──

@dataclass
class ManipulationSignal:
    """单个操纵信号（与 detector.py 保持一致）。"""

    playbook_id: str
    playbook_name: str
    confidence: float
    risk_level: str           # "high" / "medium" / "low"
    detected_at: str          # 检测时间 HH:MM 或 YYYY-MM-DD
    evidence: list[str] = field(default_factory=list)
    suggestion: str = ""

    # 场景标签: "intraday" / "daily"
    scene: str = "intraday"


@dataclass
class WashoutResult:
    """洗盘阶段检测完整结果。"""

    symbol: str = ""
    name: str = ""
    date: str = ""
    washout_risk_score: float = 0.0       # 0-100 洗盘风险评分
    signals: list[ManipulationSignal] = field(default_factory=list)
    risk_level: str = "low"               # "high" / "medium" / "low"
    summary: str = ""
    # 多波生命周期（可选；形态信号之外的状态机层）
    wash_cycle: Any = None
    created_at: datetime = field(default_factory=datetime.now)


class WashoutDetector:
    """洗盘阶段庄家操纵手法实时检测器。

    覆盖洗盘阶段的 7 种特征模式，分日内和日级两个检测入口。

    用法:
        detector = WashoutDetector()

        # 日内检测
        intraday_result = detector.detect_intraday("600089", minute_df)

        # 日级检测
        daily_result = detector.detect_daily("600089", daily_bars, ma_data)

        # 全量检测
        full_result = detector.detect_full("600089", minute_df, daily_bars, ma_data)
    """

    # ────────────────────────────────────────────────────
    # 公共入口
    # ────────────────────────────────────────────────────

    def detect_intraday(
        self,
        symbol: str,
        minute_data: pd.DataFrame,
        name: str = "",
        prev_close: float | None = None,
    ) -> WashoutResult:
        """执行日内洗盘模式检测。

        Args:
            symbol: 6 位股票代码
            minute_data: 分钟级 OHLCV DataFrame
                (columns: open, close, high, low, volume, datetime)
            name: 股票名称
            prev_close: 前一日收盘价（用于开盘异常检测）

        Returns:
            WashoutResult
        """
        if minute_data.empty or len(minute_data) < 30:
            return WashoutResult(
                symbol=symbol,
                name=name,
                washout_risk_score=0,
                signals=[],
                risk_level="low",
                summary="分钟数据不足 (< 30 分钟)，无法进行洗盘检测",
            )

        if "datetime" not in minute_data.columns and hasattr(minute_data.index, "strftime"):
            minute_data = minute_data.copy()
            minute_data["datetime"] = minute_data.index.astype(str)

        date_str = (
            str(minute_data.iloc[0].get("datetime", ""))[:10]
            or datetime.now().strftime("%Y-%m-%d")
        )

        signals: list[ManipulationSignal] = []

        # 日内 5 种检测
        signals.append(self._detect_sharp_drop(minute_data))
        signals.append(self._detect_high_open_low(minute_data, prev_close))
        signals.append(self._detect_low_open_high(minute_data, prev_close))
        signals.append(self._detect_one_sided_decline(minute_data, prev_close))
        signals.append(self._detect_continuous_suppression(minute_data))

        signals = [s for s in signals if s is not None]

        risk_score = self._calc_risk_score(signals)
        risk_level = self._classify_risk(risk_score)
        summary = self._generate_summary(signals, risk_score, risk_level)

        return WashoutResult(
            symbol=symbol,
            name=name,
            date=date_str,
            washout_risk_score=round(risk_score, 1),
            signals=signals,
            risk_level=risk_level,
            summary=summary,
        )

    def detect_daily(
        self,
        symbol: str,
        daily_bars: list[dict],
        name: str = "",
        ma_data: dict[int, float] | None = None,
        *,
        earnings_window: bool = False,
        include_wash_cycle: bool = True,
        short_balance_5d_change_pct: float | None = None,
        short_balance: float | None = None,
    ) -> WashoutResult:
        """执行日级洗盘模式检测。

        Args:
            symbol: 6 位股票代码
            daily_bars: 日线数据 [{open, high, low, close, volume, date}, ...]
            name: 股票名称
            ma_data: 均线数据 {20: 1.23, 60: 1.15, ...} 或 None（自动计算）
            earnings_window: 是否财报窗口（注入多波生命周期）
            include_wash_cycle: 是否附加 WashCycleAnalyzer（默认开）
            short_balance_5d_change_pct: 融券余额 5 日变化率（%），注入洗盘置信度
            short_balance: 当前融券余额（亿元）

        Returns:
            WashoutResult
        """
        if not daily_bars or len(daily_bars) < 3:
            return WashoutResult(
                symbol=symbol,
                name=name,
                washout_risk_score=0,
                signals=[],
                risk_level="low",
                summary="日线数据不足 (< 3 天)，无法进行日级洗盘检测",
            )

        date_str = daily_bars[-1].get("date", datetime.now().strftime("%Y-%m-%d"))
        signals: list[ManipulationSignal] = []

        # 日级形态检测（不重复生命周期）
        signals.append(self._detect_consecutive_yin_washout(daily_bars))
        signals.append(self._detect_support_breakdown(daily_bars, ma_data))
        signals.append(self._detect_small_rise_big_drop(daily_bars))
        signals.append(self._detect_long_lower_shadow_wash(daily_bars))

        signals = [s for s in signals if s is not None]

        # 多波生命周期状态机（与形态互补；quiet 不注入信号）
        wash_cycle = None
        if include_wash_cycle and len(daily_bars) >= 8:
            from .wash_cycle import WashCycleAnalyzer, WashCyclePhase

            wash_cycle = WashCycleAnalyzer().analyze(
                symbol,
                daily_bars,
                name=name,
                earnings_window=earnings_window,
                short_balance_5d_change_pct=short_balance_5d_change_pct,
                short_balance=short_balance,
            )
            cycle_sig = self._wash_cycle_to_signal(wash_cycle)
            if cycle_sig is not None:
                # 避免与已有形态 playbook 完全同名重复堆叠：只追加 meta 信号
                signals.append(cycle_sig)
            # 形态信号文案加强：后半段/第二波
            signals = self._enrich_daily_signals_with_cycle(signals, wash_cycle)

        risk_score = self._calc_risk_score(signals)
        risk_level = self._classify_risk(risk_score)
        summary = self._generate_summary(signals, risk_score, risk_level)
        if wash_cycle is not None and getattr(wash_cycle, "phase", None) is not None:
            from .wash_cycle import WashCyclePhase

            if wash_cycle.phase != WashCyclePhase.QUIET:
                summary = f"{summary}\n  【生命周期】{wash_cycle.summary}"
                if wash_cycle.dual_hard_hint:
                    summary = f"{summary}\n  【双硬】{wash_cycle.dual_hard_hint}"

        return WashoutResult(
            symbol=symbol,
            name=name,
            date=date_str,
            washout_risk_score=round(risk_score, 1),
            signals=signals,
            risk_level=risk_level,
            summary=summary,
            wash_cycle=wash_cycle,
        )

    def detect_full(
        self,
        symbol: str,
        minute_data: pd.DataFrame | None = None,
        daily_bars: list[dict] | None = None,
        name: str = "",
        prev_close: float | None = None,
        ma_data: dict[int, float] | None = None,
        *,
        earnings_window: bool = False,
        include_wash_cycle: bool = True,
        short_balance_5d_change_pct: float | None = None,
        short_balance: float | None = None,
    ) -> WashoutResult:
        """组合日内和日级检测，返回综合结果。"""
        intraday_signals: list[ManipulationSignal] = []
        daily_signals: list[ManipulationSignal] = []
        wash_cycle = None
        date_str = datetime.now().strftime("%Y-%m-%d")

        if minute_data is not None and not minute_data.empty:
            result = self.detect_intraday(symbol, minute_data, name, prev_close)
            intraday_signals = result.signals
            date_str = result.date

        if daily_bars:
            result = self.detect_daily(
                symbol,
                daily_bars,
                name,
                ma_data,
                earnings_window=earnings_window,
                include_wash_cycle=include_wash_cycle,
                short_balance_5d_change_pct=short_balance_5d_change_pct,
                short_balance=short_balance,
            )
            daily_signals = result.signals
            wash_cycle = result.wash_cycle
            if result.date:
                date_str = result.date

        all_signals = intraday_signals + daily_signals
        risk_score = self._calc_risk_score(all_signals)
        risk_level = self._classify_risk(risk_score)
        summary = self._generate_summary(all_signals, risk_score, risk_level)
        if wash_cycle is not None:
            from .wash_cycle import WashCyclePhase

            if wash_cycle.phase != WashCyclePhase.QUIET:
                summary = f"{summary}\n  【生命周期】{wash_cycle.summary}"

        return WashoutResult(
            symbol=symbol,
            name=name,
            date=date_str,
            washout_risk_score=round(risk_score, 1),
            signals=all_signals,
            risk_level=risk_level,
            summary=summary,
            wash_cycle=wash_cycle,
        )

    @staticmethod
    def _wash_cycle_to_signal(cycle) -> Optional[ManipulationSignal]:
        """将多波生命周期转为 ManipulationSignal；QUIET 返回 None。"""
        from .wash_cycle import WashCyclePhase

        if cycle is None or cycle.phase == WashCyclePhase.QUIET:
            return None
        if cycle.confidence < 0.45 and cycle.phase not in (
            WashCyclePhase.LATTER_HALF_CAPITULATION,
            WashCyclePhase.WASH_EXHAUSTION,
            WashCyclePhase.MARKUP_CANDIDATE,
            WashCyclePhase.FAILED_WASHOUT,
        ):
            return None

        risk = "medium"
        if cycle.phase in (
            WashCyclePhase.LATTER_HALF_CAPITULATION,
            WashCyclePhase.WAVE2_DECLINE,
            WashCyclePhase.FAILED_WASHOUT,
        ):
            risk = "high"
        elif cycle.phase in (
            WashCyclePhase.WASH_EXHAUSTION,
            WashCyclePhase.MARKUP_CANDIDATE,
        ):
            risk = "medium"

        return ManipulationSignal(
            playbook_id="wash_then_markup",
            playbook_name="多波洗盘后拉升 (连杀→后半段割肉→再洗→砸不动才拉)",
            confidence=float(cycle.confidence),
            risk_level=risk,
            detected_at=str(cycle.phase.value),
            evidence=list(cycle.evidence),
            suggestion=cycle.retail_action_hint or cycle.summary,
            scene="daily",
        )

    @staticmethod
    def _enrich_daily_signals_with_cycle(
        signals: list[ManipulationSignal],
        cycle,
    ) -> list[ManipulationSignal]:
        """对已有形态信号追加后半段/第二波提示（加强，不新建重复检测）。"""
        if cycle is None:
            return signals
        from .wash_cycle import WashCyclePhase

        extras: list[str] = []
        if cycle.latter_half_cut_risk or cycle.phase == WashCyclePhase.LATTER_HALF_CAPITULATION:
            extras.append("生命周期: 处于连跌后半段，割肉高峰窗口")
        if cycle.second_wave_active or cycle.phase == WashCyclePhase.WAVE2_DECLINE:
            extras.append("生命周期: 第二波再洗活跃，弱反弹勿当反转")
        if cycle.phase == WashCyclePhase.WASH_EXHAUSTION:
            extras.append("生命周期: 量能枯竭/砸不动，洗盘或近尾声")
        if cycle.phase == WashCyclePhase.FAILED_WASHOUT:
            extras.append("生命周期: 跌幅过大，更像真出货，勿按洗盘硬扛")
        if not extras:
            return signals

        enriched: list[ManipulationSignal] = []
        for s in signals:
            if s.playbook_id in (
                "washout_consecutive_yin",
                "washout_small_rise_big_drop",
                "washout_support_breakdown",
                "washout_long_lower_shadow",
            ):
                new_ev = list(s.evidence) + extras
                tip = " | ".join(extras)
                new_sug = f"{s.suggestion}（{tip}）"
                enriched.append(
                    ManipulationSignal(
                        playbook_id=s.playbook_id,
                        playbook_name=s.playbook_name,
                        confidence=s.confidence,
                        risk_level=s.risk_level,
                        detected_at=s.detected_at,
                        evidence=new_ev,
                        suggestion=new_sug,
                        scene=s.scene,
                    )
                )
            else:
                enriched.append(s)
        return enriched

    # ────────────────────────────────────────────────────
    # 检测 1: 股价异常-价格急跌
    # ────────────────────────────────────────────────────

    def _detect_sharp_drop(
        self, df: pd.DataFrame
    ) -> ManipulationSignal | None:
        """检测股价异常急跌洗盘模式。

        特征: 股价原本平稳运行 → 突然在某个时段急速向下大幅打压
              → 击穿所有支撑并创新低，但非外因所致
        目的: 制造空头行情恐慌，逼迫散户在急跌中割肉。

        检测逻辑:
        1. 前期股价走势平稳（振幅 < 2%，持续 ≥ 30 分钟）
        2. 突然在 15 分钟内急速下跌 ≥ 4%
        3. 急跌时成交量明显放大（量比 ≥ 2.0）
        4. 非外因驱动（这里仅从价格形态判断，外因排除需结合 news）
        """
        if "close" not in df.columns or "volume" not in df.columns:
            return None

        close = df["close"].values
        volume = df["volume"].values
        n = len(close)

        if n < WASHOUT_SHARP_DROP_PRE_STABLE + WASHOUT_SHARP_DROP_MINUTES:
            return None

        # 滑动窗口检测急跌：找 n 分钟内跌幅最大的区间
        best_drop = 0.0
        best_start = 0
        best_end = 0

        window = WASHOUT_SHARP_DROP_MINUTES
        for i in range(WASHOUT_SHARP_DROP_PRE_STABLE, n - window):
            start_p = close[i]
            end_p = close[i + window]
            if start_p > 0:
                drop = (start_p - end_p) / start_p
                if drop > best_drop:
                    best_drop = drop
                    best_start = i
                    best_end = i + window

        if best_drop < WASHOUT_SHARP_DROP_PCT:
            return None

        # 急跌前至少平稳运行 30 分钟
        pre_drop_start = max(0, best_start - WASHOUT_SHARP_DROP_PRE_STABLE)
        pre_prices = close[pre_drop_start:best_start]
        if len(pre_prices) < 10:
            return None

        pre_high = _safe_float(np.max(pre_prices))
        pre_low = _safe_float(np.min(pre_prices))
        if pre_low > 0:
            pre_range = (pre_high - pre_low) / pre_low
            if pre_range > 0.02:  # 前期振幅 > 2%，不算平稳
                return None
        else:
            return None

        # 急跌时放量检查
        vol_confirmed = False
        drop_vol = _safe_float(volume[best_start:best_end + 1].mean()) if best_end >= best_start else 0
        pre_vol = _safe_float(volume[pre_drop_start:best_start].mean()) if best_start > pre_drop_start else drop_vol
        if pre_vol > 0 and drop_vol / pre_vol >= WASHOUT_SHARP_DROP_VOL_RATIO:
            vol_confirmed = True

        evidence = [
            f"前期平稳运行 {WASHOUT_SHARP_DROP_PRE_STABLE} 分钟（振幅 {pre_range*100:.1f}%）",
            f"突然在 {best_end - best_start} 分钟内急跌 {best_drop*100:.1f}%",
        ]
        if vol_confirmed:
            evidence.append(f"急跌时量比 {drop_vol/pre_vol:.1f}x（恐慌盘+庄家打压）")

        confidence = 0.65 if vol_confirmed else 0.50
        if best_drop > 0.07:
            confidence += 0.10  # 跌幅 > 7%，更确定
        if pre_range < 0.01:
            confidence += 0.10  # 前期极其平稳
        confidence = min(0.85, confidence)

        return ManipulationSignal(
            playbook_id="washout_sharp_drop",
            playbook_name="洗盘-股价异常急跌 (平稳走势→突然急跌→制造空头恐慌)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=f"{best_start}-{best_end} 分钟区间",
            evidence=evidence,
            scene="intraday",
            suggestion="🔴 疑似洗盘式急跌。股价前期平稳后突然无量急跌，很可能是庄家打压洗盘。不建议在急跌中割肉。",
        )

    # ────────────────────────────────────────────────────
    # 检测 2: 高开低走洗盘
    # ────────────────────────────────────────────────────

    def _detect_high_open_low(
        self, df: pd.DataFrame, prev_close: float | None = None
    ) -> ManipulationSignal | None:
        """检测高开低走洗盘模式。

        特征: 大幅高开 (≥3%) → 一路走低 → 收于最低价附近或收阴
        目的: 制造"庄家正在出货"的假象，恐吓散户离场。

        检测逻辑:
        1. 开盘价相对前收盘高开 ≥ 3%
        2. 收盘价在当日振幅底部 20% 内（或收阴线）
        3. 成交量放大 (恐慌盘出逃)
        """
        if "open" not in df.columns or "close" not in df.columns:
            return None

        open_price = _safe_float(df["open"].iloc[0])
        close_price = _safe_float(df["close"].iloc[-1])
        high_price = _safe_float(df["high"].max())
        low_price = _safe_float(df["low"].min())

        if open_price <= 0 or close_price <= 0:
            return None

        # 前收盘：优先用传入值，否则用第一分钟开盘作为近似
        if prev_close is None or prev_close <= 0:
            # 尝试从前一天数据推断 — 这里用当日第一分钟开盘近似
            # 无法准确判断高开幅度时跳过
            return None

        gap_pct = (open_price - prev_close) / prev_close
        if gap_pct < WASHOUT_HIGH_OPEN_PCT:
            return None

        # 收盘在当日振幅底部 20% 内
        day_range = high_price - low_price
        if day_range <= 0:
            return None
        close_position = (close_price - low_price) / day_range
        if close_position > WASHOUT_HIGH_OPEN_CLOSE_NEAR_LOW:
            return None

        evidence = [
            f"高开 {gap_pct*100:.1f}%（前收 {prev_close:.2f}→开盘 {open_price:.2f}）",
            f"收盘 {close_price:.2f} 在当日振幅底部 ({close_position*100:.0f}%)",
        ]

        # 成交量放大确认
        vol_confirmed = False
        if "volume" in df.columns:
            today_vol = _safe_float(df["volume"].sum())
            # 用前 30 分钟均量估算全日量（粗糙但可用）
            first_30_vol = _safe_float(df["volume"].iloc[:30].sum()) if len(df) >= 30 else today_vol
            if first_30_vol > 0:
                # 如果前 30 分钟量占今日总量 > 40%，说明开盘放量
                if first_30_vol / max(today_vol, 1) > 0.4:
                    vol_confirmed = True
                    evidence.append("开盘放量明显 (前30分钟占全日 > 40%)")

        confidence = 0.70 if vol_confirmed else 0.55

        return ManipulationSignal(
            playbook_id="washout_high_open_low",
            playbook_name="洗盘-高开低走 (大幅高开→一路走低→制造出货假象)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=df.iloc[0].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=evidence,
            scene="intraday",
            suggestion="⚠️ 疑似洗盘高开低走，庄家制造出货假象恐吓散户。已有持仓不必恐慌，观察后续走势。",
        )

    # ────────────────────────────────────────────────────
    # 检测 2: 低开高走洗盘
    # ────────────────────────────────────────────────────

    def _detect_low_open_high(
        self, df: pd.DataFrame, prev_close: float | None = None
    ) -> ManipulationSignal | None:
        """检测低开高走洗盘模式。

        特征: 大幅低开 (≥3%) → 一路走高 → 收于最高价附近
        目的: 开盘制造恐慌 → 散户低价割肉 → 庄家低位接筹后拉升。

        检测逻辑:
        1. 开盘价相对前收盘低开 ≥ 3%
        2. 收盘价在当日振幅顶部 20% 内（或收阳线）
        3. 开盘时段成交量放大 (恐慌盘涌出)
        """
        if "open" not in df.columns or "close" not in df.columns:
            return None

        if prev_close is None or prev_close <= 0:
            return None

        open_price = _safe_float(df["open"].iloc[0])
        close_price = _safe_float(df["close"].iloc[-1])
        high_price = _safe_float(df["high"].max())
        low_price = _safe_float(df["low"].min())

        if open_price <= 0 or close_price <= 0:
            return None

        gap_pct = (open_price - prev_close) / prev_close
        if gap_pct > -WASHOUT_LOW_OPEN_PCT:
            return None  # 低开幅度不够

        # 收盘在当日振幅顶部 20% 内
        day_range = high_price - low_price
        if day_range <= 0:
            return None
        close_position = (close_price - low_price) / day_range
        if close_position < (1.0 - WASHOUT_LOW_OPEN_CLOSE_NEAR_HIGH):
            return None

        evidence = [
            f"低开 {abs(gap_pct)*100:.1f}%（前收 {prev_close:.2f}→开盘 {open_price:.2f}）",
            f"收盘 {close_price:.2f} 在当日振幅顶部 ({close_position*100:.0f}%)",
        ]

        # 开盘放量确认（恐慌盘出逃）
        vol_confirmed = False
        if "volume" in df.columns:
            today_vol = _safe_float(df["volume"].sum())
            first_30_vol = _safe_float(df["volume"].iloc[:30].sum()) if len(df) >= 30 else today_vol
            if first_30_vol > 0 and first_30_vol / max(today_vol, 1) > 0.35:
                vol_confirmed = True
                evidence.append("开盘放量 (恐慌盘低位出逃)")

        # 价格走势确认：开盘后价格持续上行
        if len(df) >= 30:
            mid_price = _safe_float(df["close"].iloc[len(df) // 2])
            if mid_price > open_price:
                evidence.append("开盘后持续走高 (庄家低位吸筹)")

        confidence = 0.75 if vol_confirmed else 0.60

        return ManipulationSignal(
            playbook_id="washout_low_open_high",
            playbook_name="洗盘-低开高走 (大幅低开→恐慌割肉→低位吸筹后拉升)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=df.iloc[0].get("datetime", "")[-8:] if "datetime" in df.columns else "",
            evidence=evidence,
            scene="intraday",
            suggestion="⚠️ 疑似洗盘低开高走，开盘制造恐慌后拉升。不建议在低位割肉，观察反弹持续性。",
        )

    # ────────────────────────────────────────────────────
    # 检测 3: 分时单边下跌
    # ────────────────────────────────────────────────────

    def _detect_one_sided_decline(
        self, df: pd.DataFrame, prev_close: float | None = None
    ) -> ManipulationSignal | None:
        """检测分时单边下跌洗盘。

        特征: 逐波下跌，每次反弹不及前收盘价，"跳水"式急跌
        目的: 全天持续制造恐慌气氛，逼迫散户逐步割肉。

        检测逻辑:
        1. 识别至少 3 波下跌浪
        2. 每波反弹幅度不超过前一波跌幅的 30%
        3. 存在"跳水"式下跌 (单分钟跌幅 > 0.5%)
        4. 全天大部分时间运行在前收盘价下方
        """
        if "close" not in df.columns:
            return None

        close = df["close"].values
        n = len(close)

        if n < WASHOUT_DECLINE_MIN_MINUTES:
            return None

        # 找局部极值点 (波峰、波谷)
        peaks, troughs = self._find_waves(close)

        # 需要至少 3 个波谷 (即 3 波下跌)
        if len(troughs) < WASHOUT_DECLINE_WAVES_MIN:
            return None

        # 检查下降趋势：波谷一波比一波低
        declining = all(
            close[troughs[i]] <= close[troughs[i - 1]] * 1.005  # 允许 0.5% 的误差
            for i in range(1, len(troughs))
        )
        if not declining:
            return None

        # 检查反弹力度：每波反弹不超过跌幅的 30%
        weak_bounces = 0
        for i in range(min(len(peaks), len(troughs))):
            if i == 0:
                continue
            # 上一波谷到这一波峰的反弹幅度
            prev_trough_price = close[troughs[i - 1]]
            peak_price = close[peaks[min(i, len(peaks) - 1)]]
            next_trough_price = close[troughs[min(i, len(troughs) - 1)]]

            drop_amount = prev_trough_price - next_trough_price
            bounce_amount = peak_price - prev_trough_price

            if drop_amount > 0 and bounce_amount / drop_amount < WASHOUT_DECLINE_BOUNCE_MAX:
                weak_bounces += 1

        if weak_bounces < WASHOUT_DECLINE_WAVES_MIN - 1:
            return None

        # 检测"跳水"式下跌 (单分钟跌幅 > 0.5%)
        dive_count = 0
        for i in range(1, n):
            if close[i] > 0 and (close[i - 1] - close[i]) / close[i - 1] > WASHOUT_DECLINE_DIVE_PCT:
                dive_count += 1

        # 全天运行在前收盘价下方的比例
        below_prev = 0
        if prev_close is not None and prev_close > 0:
            below_prev = sum(1 for c in close if c < prev_close)
            below_prev_ratio = below_prev / n
        else:
            below_prev_ratio = 0.5  # 默认一半

        evidence = [
            f"分时 {len(troughs)} 波逐级下跌",
            f"{weak_bounces} 次反弹无力 (反弹 < 跌幅 30%)",
            f"{dive_count} 次跳水式急跌 (单分钟 > 0.5%)",
        ]

        confidence = 0.50
        if below_prev_ratio > 0.80:
            confidence += 0.15
            evidence.append(f"全天 {below_prev_ratio:.0%} 时间运行在昨收下方")
        if dive_count >= 3:
            confidence += 0.15
        if len(troughs) >= 5:
            confidence += 0.10

        confidence = min(0.85, confidence)

        return ManipulationSignal(
            playbook_id="washout_one_sided_decline",
            playbook_name="洗盘-分时单边下跌 (逐波下跌→反弹无力→跳水制造恐慌)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at="全天" if below_prev_ratio > 0.7 else "部分时段",
            evidence=evidence,
            scene="intraday",
            suggestion="🔴 全天单边下跌洗盘形态明显，恐慌盘正在被清洗。不建议在下跌中割肉。",
        )

    # ────────────────────────────────────────────────────
    # 检测 4: 持续压低
    # ────────────────────────────────────────────────────

    def _detect_continuous_suppression(
        self, df: pd.DataFrame
    ) -> ManipulationSignal | None:
        """检测持续压低洗盘。

        特征: 每下跌几个价位后卖盘挂出大单持续压盘，股价整天单边下跌
        目的: 制造"卖盘沉重、庄家出货"的假象。

        检测逻辑 (价格-量近似):
        1. 价格呈单调递减趋势（或几乎单调）
        2. 任何反弹极其微弱 (< 0.2%)
        3. 至少持续 60 分钟
        4. K线以阴线为主 (> 65%)
        """
        if "close" not in df.columns or "open" not in df.columns:
            return None

        n = len(df)

        if n < WASHOUT_SUPPRESSION_MIN_MINUTES:
            return None

        close = df["close"].values
        open_vals = df["open"].values

        # 找持续最长的单调递减段
        best_start = 0
        best_len = 0
        current_start = 0

        for i in range(1, n):
            if close[i] <= close[i - 1] * 1.0005:  # 允许 0.05% 微涨
                continue
            # 中断了
            seg_len = i - current_start
            if seg_len > best_len:
                best_len = seg_len
                best_start = current_start
            current_start = i

        # 检查最后一段
        seg_len = n - current_start
        if seg_len > best_len:
            best_len = seg_len
            best_start = current_start

        if best_len < WASHOUT_SUPPRESSION_MIN_MINUTES:
            return None

        segment = close[best_start:best_start + best_len]
        seg_open = open_vals[best_start:best_start + best_len]

        # 检查反弹幅度
        max_bounce = 0.0
        seg_min = _safe_float(np.min(segment))
        for i in range(1, len(segment)):
            if segment[i] > segment[i - 1] and seg_min > 0:
                bounce = (segment[i] - segment[i - 1]) / segment[i - 1]
                max_bounce = max(max_bounce, bounce)

        if max_bounce > WASHOUT_SUPPRESSION_MAX_REBOUND:
            return None

        # 阴线比例
        yin_count = sum(1 for i in range(len(segment)) if segment[i] < seg_open[i])
        yin_ratio = yin_count / len(segment) if len(segment) > 0 else 0

        if yin_ratio < WASHOUT_SUPPRESSION_NEG_PCT:
            return None

        # 总跌幅
        total_drop = (
            (segment[0] - segment[-1]) / segment[0] if segment[0] > 0 else 0
        )

        evidence = [
            f"持续压低 {best_len} 分钟",
            f"期间最大反弹仅 {max_bounce*100:.2f}%",
            f"阴线占比 {yin_ratio:.0%}（卖盘沉重假象）",
            f"总跌幅 {total_drop*100:.1f}%",
        ]

        confidence = 0.55
        if best_len >= 120:
            confidence += 0.15
            evidence.append("持续时间 > 2 小时（强化洗盘信号）")
        if yin_ratio > 0.80:
            confidence += 0.10
        if total_drop > 0.03:
            confidence += 0.10
        confidence = min(0.85, confidence)

        return ManipulationSignal(
            playbook_id="washout_continuous_suppression",
            playbook_name="洗盘-持续压低 (持续下压→卖盘沉重→制造出货假象)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=f"{best_start}-{best_start + best_len} 分钟区间",
            evidence=evidence,
            scene="intraday",
            suggestion="🔴 疑似持续压低洗盘，卖盘沉重为庄家刻意制造的假象。持仓者勿恐慌抛售。",
        )

    # ────────────────────────────────────────────────────
    # 检测 5: 连续阴线洗盘（日级）
    # ────────────────────────────────────────────────────

    def _detect_consecutive_yin_washout(
        self, bars: list[dict]
    ) -> ManipulationSignal | None:
        """检测连续阴线洗盘。

        特征: 日K线连续 6-9 根（或更多）阴线，每天收低，量能递减
        目的: "再不卖亏更多"的心理压迫，逼迫散户离场。

        注意: 连续阴线 > 15 天或累计跌幅 > 20% → 可能是出货而非洗盘
        """
        if len(bars) < WASHOUT_YIN_MIN_DAYS:
            return None

        closes = [b.get("close", 0) for b in bars]
        opens = [b.get("open", 0) for b in bars]
        volumes = [b.get("volume", 0) for b in bars]

        # 从最新一根往前数连续阴线
        yin_count = 0
        for i in range(len(bars) - 1, -1, -1):
            if closes[i] > 0 and opens[i] > 0 and closes[i] < opens[i]:
                yin_count += 1
            else:
                break

        if yin_count < WASHOUT_YIN_MIN_DAYS:
            return None

        if yin_count > WASHOUT_YIN_MAX_DAYS:
            # 阴线太多，可能是出货
            return None

        start_idx = len(bars) - yin_count
        yin_bars = bars[start_idx:]

        yin_closes = [b.get("close", 0) for b in yin_bars]
        yin_volumes = [b.get("volume", 0) for b in yin_bars]

        # 每天收低检查（至少 80% 的天数）
        lower_days = sum(
            1 for i in range(1, len(yin_closes))
            if yin_closes[i] < yin_closes[i - 1]
        )
        lower_ratio = lower_days / max(yin_count - 1, 1)

        # 累计跌幅
        total_drop = (
            (yin_closes[0] - yin_closes[-1]) / yin_closes[0]
            if yin_closes[0] > 0
            else 0
        )

        if total_drop > WASHOUT_YIN_PRICE_DROP_MAX:
            return None  # 跌幅过大，可能是真出货

        # 量能递减检查：前 1/3 vs 后 1/3
        third = max(yin_count // 3, 1)
        first_vol = sum(yin_volumes[:third]) / third if third > 0 else 0
        last_vol = sum(yin_volumes[-third:]) / third if third > 0 else 0
        vol_decline = (
            (first_vol - last_vol) / first_vol if first_vol > 0 else 0
        )

        evidence = [
            f"连续 {yin_count} 根阴线",
            f"{lower_ratio:.0%} 的天数收低",
            f"累计跌幅 {total_drop*100:.1f}%",
        ]

        confidence = 0.45
        if lower_ratio > 0.70:
            confidence += 0.15
            evidence.append('逐日走低，制造"早卖少亏"紧迫感')
        if vol_decline > WASHOUT_YIN_VOL_DECLINE_PCT:
            confidence += 0.15
            evidence.append(f"量能递减 {vol_decline:.0%}（卖压衰竭→洗盘信号）")
        if yin_count >= 8:
            confidence += 0.10
        if 0.05 < total_drop < 0.15:
            confidence += 0.10
            evidence.append("跌幅适中 (5-15%)，洗盘特征明显")

        confidence = min(0.85, confidence)

        if confidence < 0.50:
            return None

        return ManipulationSignal(
            playbook_id="washout_consecutive_yin",
            playbook_name="洗盘-连续阴线 (6-9连阴→逐日走低→制造恐慌)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=yin_bars[-1].get("date", ""),
            evidence=evidence,
            scene="daily",
            suggestion=(
                f"🔴 连续 {yin_count} 根阴线洗盘形态。量能递减表明卖压在衰竭，非真出货。"
                f"不建议在此阶段割肉。"
                + (
                    " 注意：连阴后半段是散户割肉高峰（对照 wash_then_markup）。"
                    if yin_count >= 6
                    else ""
                )
            ),
        )

    # ────────────────────────────────────────────────────
    # 检测 6: 击穿支撑位洗盘（日级）
    # ────────────────────────────────────────────────────

    def _detect_support_breakdown(
        self,
        bars: list[dict],
        ma_data: dict[int, float] | None = None,
    ) -> ManipulationSignal | None:
        """检测击穿支撑位洗盘。

        特征: 股价跌破关键支撑（MA20/MA60/前低/成交密集区）
        目的: 制造技术性破位，触发技术派止损盘，庄家在低位接筹。

        检测逻辑:
        1. 股价在近期首次跌破 MA20 或 MA60
        2. 或跌破前 N 日最低价
        3. 破位日成交量放大
        """
        if len(bars) < 20:
            return None

        closes = [b.get("close", 0) for b in bars]
        highs = [b.get("high", 0) for b in bars]
        lows = [b.get("low", 0) for b in bars]
        volumes = [b.get("volume", 0) for b in bars]

        latest_close = closes[-1]
        if latest_close <= 0:
            return None

        evidence = []
        confidence = 0.0
        broken_supports = []

        # 检查 MA 支撑
        for period in WASHOUT_SUPPORT_MA_PERIODS:
            if len(closes) < period:
                continue
            ma_val = ma_data.get(period) if ma_data else None
            if ma_val is None:
                # 自动计算 MA
                ma_val = sum(closes[-period:]) / period

            if ma_val <= 0:
                continue

            # 前一日在 MA 之上，今日跌破
            prev_above = closes[-2] > ma_val if len(closes) >= 2 else False
            today_below = latest_close < ma_val * (1 - WASHOUT_SUPPORT_BREAK_PCT)

            if prev_above and today_below:
                broken_supports.append(f"MA{period} ({ma_val:.2f})")
                evidence.append(f"跌破 MA{period}（{ma_val:.2f}），前收 {closes[-2]:.2f}")

        # 检查前低支撑
        if len(lows) >= 20:
            prev_20_low = min(lows[-21:-1])  # 前 20 日最低（不含今日）
            if prev_20_low > 0 and latest_close < prev_20_low:
                broken_supports.append(f"前 20 日低点 ({prev_20_low:.2f})")
                evidence.append(f"击穿前 20 日低点 {prev_20_low:.2f}")

        if not broken_supports:
            return None

        # 破位放量确认
        vol_confirmed = False
        if len(volumes) >= 6:
            avg_prev_5_vol = sum(volumes[-6:-1]) / 5
            today_vol = volumes[-1]
            if avg_prev_5_vol > 0 and today_vol / avg_prev_5_vol > WASHOUT_SUPPORT_VOL_SPIKE:
                vol_confirmed = True
                evidence.append(f"破位日放量 {today_vol / avg_prev_5_vol:.1f}x（恐慌盘+庄家接筹）")

        confidence = 0.50 + 0.15 * len(broken_supports) + (0.15 if vol_confirmed else 0)
        confidence = min(0.85, confidence)

        supports_str = "、".join(broken_supports)

        return ManipulationSignal(
            playbook_id="washout_support_breakdown",
            playbook_name="洗盘-击穿支撑 (破位制造技术性恐慌→低位吸筹)",
            confidence=round(confidence, 2),
            risk_level="high",
            detected_at=bars[-1].get("date", ""),
            evidence=evidence,
            scene="daily",
            suggestion=f"🔴 疑似击穿支撑位洗盘（{supports_str}）。技术破位触发止损盘，庄家可能在低位接筹。关注后续能否收复支撑。",
        )

    # ────────────────────────────────────────────────────
    # 检测 7: 小涨大跌K线形态（日级）
    # ────────────────────────────────────────────────────

    def _detect_small_rise_big_drop(
        self, bars: list[dict]
    ) -> ManipulationSignal | None:
        """检测小涨大跌洗盘K线形态。

        特征: 小阳伴大阴 / 二阴夹一阳 / 三阴夹一阳
        目的: "每次反弹都是出货机会"的心理暗示，温水煮青蛙式洗盘。

        检测窗口: 最近 4 个交易日
        """
        if len(bars) < WASHOUT_SRD_WINDOW:
            return None

        recent = bars[-WASHOUT_SRD_WINDOW:]

        # 计算每根K线的涨跌幅（相对前一日收盘）
        changes = []
        for i, b in enumerate(recent):
            close = b.get("close", 0)
            open_p = b.get("open", 0)
            # 前一日的收盘价：优先用 bars 中对应的前一根，其次用 recent 中的前一根
            if i > 0:
                prev_close = recent[i - 1].get("close", 0)
            else:
                # 第一根用 bars 中位于 recent 之前的那一根
                recent_start_idx = len(bars) - len(recent)
                if recent_start_idx > 0:
                    prev_close = bars[recent_start_idx - 1].get("close", 0)
                else:
                    prev_close = close

            if prev_close > 0:
                day_change = (close - prev_close) / prev_close
            elif open_p > 0:
                day_change = (close - open_p) / open_p
            else:
                day_change = 0.0

            is_yang = close > open_p  # 收阳
            is_yin = close < open_p   # 收阴
            changes.append({
                "change": day_change,
                "is_yang": is_yang,
                "is_yin": is_yin,
                "body_pct": abs(close - open_p) / open_p if open_p > 0 else 0,
            })

        # 模式 1: 小阳 + 大阴 (最后2天)
        if len(changes) >= 2:
            prev_day = changes[-2]
            last_day = changes[-1]
            if (
                prev_day["is_yang"]
                and prev_day["change"] < WASHOUT_SMALL_RISE_MAX
                and prev_day["change"] > 0
                and last_day["is_yin"]
                and last_day["change"] < -WASHOUT_BIG_DROP_MIN
            ):
                return self._build_small_rise_big_drop_signal(
                    "小阳伴大阴", changes, bars,
                    f"小阳涨 {prev_day['change']*100:.1f}%→大阴跌 {abs(last_day['change'])*100:.1f}%"
                )

        # 模式 2: 二阴夹一阳 (最后3天)
        if len(changes) >= 3:
            day1 = changes[-3]
            day2 = changes[-2]
            day3 = changes[-1]
            if (
                day1["is_yin"]
                and day2["is_yang"] and 0 < day2["change"] < WASHOUT_SMALL_RISE_MAX
                and day3["is_yin"] and day3["change"] < -WASHOUT_BIG_DROP_MIN
            ):
                return self._build_small_rise_big_drop_signal(
                    "二阴夹一阳", changes, bars,
                    f"阴→小阳涨{day2['change']*100:.1f}%→大阴跌{abs(day3['change'])*100:.1f}%"
                )

        # 模式 3: 三阴夹一阳 (最后4天中 3阴1阳)
        if len(changes) >= 4:
            yin_count = sum(1 for c in changes if c["is_yin"])
            yang_count = sum(1 for c in changes if c["is_yang"])
            big_yin = sum(1 for c in changes if c["is_yin"] and c["change"] < -WASHOUT_BIG_DROP_MIN)
            small_yang = sum(
                1 for c in changes
                if c["is_yang"] and 0 < c["change"] < WASHOUT_SMALL_RISE_MAX
            )
            if yin_count >= 3 and yang_count == 1 and big_yin >= 2 and small_yang == 1:
                return self._build_small_rise_big_drop_signal(
                    "三阴夹一阳", changes, bars,
                    f"4天中 3阴{big_yin}大阴 + 1小阳，持续制造压力"
                )

        return None

    def _build_small_rise_big_drop_signal(
        self,
        pattern_name: str,
        changes: list[dict],
        bars: list[dict],
        detail: str,
    ) -> ManipulationSignal:
        """构建小涨大跌信号。"""
        total_change = sum(c["change"] for c in changes)
        evidence = [
            f"K线形态: {pattern_name}",
            detail,
            f"窗口 {len(changes)} 天累计涨跌 {total_change*100:.1f}%",
        ]

        confidence = 0.55
        if total_change < -0.05:
            confidence += 0.15
            evidence.append("累计跌幅较大，洗盘压力充分")
        if pattern_name in ("二阴夹一阳", "三阴夹一阳"):
            confidence += 0.10
        confidence = min(0.80, confidence)

        return ManipulationSignal(
            playbook_id="washout_small_rise_big_drop",
            playbook_name=f"洗盘-{pattern_name} (小涨大跌→温水煮蛙式洗盘)",
            confidence=round(confidence, 2),
            risk_level="medium",
            detected_at=bars[-1].get("date", ""),
            evidence=evidence,
            scene="daily",
            suggestion=(
                f'⚠️ {pattern_name} 洗盘形态，每次小反弹后即大跌，'
                f'制造"反弹就是逃命机会"的心理暗示。不建议在恐慌中出局。'
                f" 弱反弹后再杀=第二波再洗，勿把小阳当反转满仓回补（对照 wash_then_markup）。"
            ),
        )

    def _detect_long_lower_shadow_wash(
        self, daily_bars: list[dict]
    ) -> Optional[ManipulationSignal]:
        """二次洗后长下影收针：前段下跌 + 当日长下影，洗掉最后一批恐慌盘。"""
        if not daily_bars or len(daily_bars) < 4:
            return None

        last = daily_bars[-1]
        o = _safe_float(last.get("open"))
        h = _safe_float(last.get("high"))
        l = _safe_float(last.get("low"))
        c = _safe_float(last.get("close"))
        if min(o, h, l, c) <= 0 or h <= l:
            return None

        rng = h - l
        if rng / c < WASHOUT_LLS_RANGE_MIN:
            return None

        body = abs(c - o)
        lower_shadow = min(o, c) - l
        if lower_shadow <= 0:
            return None

        lower_ratio = lower_shadow / rng
        body_ratio = body / rng
        if lower_ratio < WASHOUT_LLS_LOWER_SHADOW_RATIO:
            return None
        if body_ratio > WASHOUT_LLS_BODY_MAX_RATIO:
            return None

        # 前 3 日累计下跌
        closes = [_safe_float(b.get("close")) for b in daily_bars[-4:-1]]
        if len(closes) < 3 or any(x <= 0 for x in closes):
            return None
        prior_drop = (closes[0] - closes[-1]) / closes[0]
        if prior_drop < WASHOUT_LLS_PRIOR_DROP_MIN:
            return None

        conf = 0.58
        conf += min(0.12, (lower_ratio - 0.55) * 0.5)
        conf += min(0.10, prior_drop)
        conf = min(0.82, conf)

        date_str = str(last.get("date", ""))
        return ManipulationSignal(
            playbook_id="washout_long_lower_shadow",
            playbook_name="洗盘-长下影收针 (再砸后下影洗掉最后一批)",
            confidence=round(conf, 2),
            risk_level="medium",
            detected_at=date_str,
            evidence=[
                f"下影线占振幅 {lower_ratio:.0%}（阈值≥{WASHOUT_LLS_LOWER_SHADOW_RATIO:.0%}）",
                f"实体仅占振幅 {body_ratio:.0%}，收盘收回大部分跌幅",
                f"前 3 日累计跌 {prior_drop:.1%}，符合二次洗后收针",
            ],
            scene="daily",
            suggestion=(
                "⚠️ 长下影收针：常见于二次砸盘后洗掉最后恐慌盘。"
                "勿在下影最低点割肉；亦勿认定立刻反转满仓。"
                " 对照 wash_then_markup 生命周期与双硬条件。"
            ),
        )

    # ────────────────────────────────────────────────────
    # 辅助方法
    # ────────────────────────────────────────────────────

    @staticmethod
    def _find_waves(prices: np.ndarray) -> tuple[list[int], list[int]]:
        """识别价格序列中的波峰和波谷。

        使用简化拐点检测: 局部极值 = 前后各 2 个点的最大/最小值。

        Returns:
            (peaks: list[int], troughs: list[int]) 索引位置
        """
        n = len(prices)
        if n < 5:
            return [], []

        peaks = []
        troughs = []
        lookback = min(3, n // 4)

        for i in range(lookback, n - lookback):
            # 波峰
            if all(prices[i] >= prices[i - j] for j in range(1, lookback + 1)) and \
               all(prices[i] >= prices[i + j] for j in range(1, lookback + 1)):
                peaks.append(i)
            # 波谷
            elif all(prices[i] <= prices[i - j] for j in range(1, lookback + 1)) and \
                 all(prices[i] <= prices[i + j] for j in range(1, lookback + 1)):
                troughs.append(i)

        return peaks, troughs

    @staticmethod
    def _calc_risk_score(signals: list[ManipulationSignal]) -> float:
        """加权计算综合洗盘风险评分。

        洗盘信号权重（洗盘对散户的主要伤害是"被洗出→踏空"）:
          连续阴线: 0.25 | 持续压低: 0.20 | 单边下跌: 0.20
          击穿支撑: 0.15 | 小涨大跌: 0.10
          高开低走: 0.05 | 低开高走: 0.05
        """
        if not signals:
            return 0.0

        weights = {
            "washout_sharp_drop": 0.16,
            "washout_consecutive_yin": 0.16,
            "washout_continuous_suppression": 0.12,
            "washout_one_sided_decline": 0.12,
            "washout_support_breakdown": 0.09,
            "washout_small_rise_big_drop": 0.07,
            "washout_long_lower_shadow": 0.08,
            "washout_high_open_low": 0.04,
            "washout_low_open_high": 0.04,
            # 多波生命周期 meta（与形态互补，权重中等避免双计放大）
            "wash_then_markup": 0.12,
        }

        score = 0.0
        total_weight = 0.0
        for s in signals:
            w = weights.get(s.playbook_id, 0.10)
            score += s.confidence * 100 * w
            total_weight += w

        return min(100.0, score / max(total_weight, 0.01))

    @staticmethod
    def _classify_risk(score: float) -> str:
        """风险评分 → 等级。"""
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    @staticmethod
    def _generate_summary(
        signals: list[ManipulationSignal], risk_score: float, risk_level: str
    ) -> str:
        """生成洗盘风险评估摘要。"""
        if not signals:
            return "🟢 未检测到明显的洗盘操纵迹象。"

        level_emoji = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(risk_level, "🟢")
        lines = [
            f"{level_emoji} 洗盘操纵风险: {risk_level.upper()} (评分 {risk_score:.0f}/100)",
            f"检测到 {len(signals)} 个洗盘信号:",
        ]

        # 按场景分组显示
        intraday = [s for s in signals if getattr(s, "scene", "intraday") == "intraday"]
        daily = [s for s in signals if getattr(s, "scene", "intraday") == "daily"]

        if intraday:
            lines.append("  【日内】")
            for s in intraday:
                lines.append(f"    • {s.playbook_name} (置信度 {s.confidence:.0%})")
        if daily:
            lines.append("  【日级】")
            for s in daily:
                lines.append(f"    • {s.playbook_name} (置信度 {s.confidence:.0%})")

        high_signals = [s for s in signals if s.risk_level == "high"]
        if high_signals:
            lines.append(f"\n🔴 重点关注: {high_signals[0].suggestion}")

        return "\n".join(lines)
