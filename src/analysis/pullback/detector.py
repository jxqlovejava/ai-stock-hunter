# -*- coding: utf-8 -*-
"""回调检测器 (PullbackDetector)。

基于日线数据，执行 5 步回调检测流程:
  1. 找 20 日最高点 → 计算回落幅度
  2. 找最近支撑 (MA20/MA60/前低)
  3. 止跌确认 (连续 2 日缩量 + 不创新低)
  4. 反操纵验证 (委托 AntiManipulationGate)
  5. 输出 PullbackState

Phase 13: 超跌反弹检测 (Oversold Bounce)
  经验规则: 15-30 日最低价，差价 ≥ 25%
  当回调深度 15-40% 时，不再直接判定 BREAK，进入超跌 6 步确认:
    0. 阶段跌幅 ≥ 25% 筛选门
    1. 跌速分析 (天数 + 日均跌幅)
    2. 恐慌量识别 (单日量 > 5日均量 2.5x)
    3. 止跌确认 (≥3 日不创新低 + 缩量 ≤ 0.7，比普通回调更严格)
    4. RSI(14) + 大单方向
    5. 反操纵验证 (重点查 lure_bear_accumulate 诱空吸筹)

保守参数 (选项 A):
  - 回调起点: 20 日高点
  - 回调深度: 5-15%
  - 支撑参考: 20/60 日均线 + 前低
  - 止跌确认: 连续 2 日缩量 + 不创新低
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np

from src.data.schema import Bar
from .schemas import (
    ManipulationCheck,
    OversoldProfile,
    PullbackState,
    PullbackStatus,
    PullbackTier,
    SupportLevel,
)

logger = logging.getLogger(__name__)


# ── 保守参数 (选项 A) ──
LOOKBACK_DAYS = 20             # 高点回溯窗口
MIN_PULLBACK_DEPTH = 0.05      # 最小回调深度 5%
MAX_PULLBACK_DEPTH = 0.15      # 最大回调深度 15%（超过=进入超跌检测）
SUPPORT_DISTANCE_THRESHOLD = 0.03  # 距支撑 ≤ 3% = 进入 setup 区
VOLUME_SHRINK_DAYS = 2         # 连续缩量天数（止跌确认）
VOLUME_SHRINK_RATIO = 0.8      # 缩量比 < 0.8 = 显著缩量
CONSECUTIVE_NO_NEW_LOW = 2     # 连续不创新低天数
MIN_DAILY_BARS = 30            # 最少日线数据

# ── Phase 13: 超跌反弹参数 ──
MAX_OVERSOLD_DEPTH = 0.40       # 超跌上限 40%（超过=极端，基本面料出问题）
OVERSOLD_LOOKBACK_30D = 30      # 30 日窗口（计算阶段跌幅）
OVERSOLD_DECLINE_THRESHOLD = 0.25  # 阶段跌幅 ≥ 25% 经验规则（筛选门）
PANIC_VOLUME_RATIO = 2.3        # 恐慌量 = 单日量 > 5日均量 × 2.3
OVERSOLD_VOLUME_SHRINK_RATIO = 0.7  # 超跌缩量比（比普通 0.8 更严格）
OVERSOLD_CONSECUTIVE_NO_LOW = 3     # 超跌止跌天数（比普通 2 天更严格）
RSI_OVERSOLD_THRESHOLD = 25      # RSI < 25 = 极度超卖
RSI_PERIOD = 14                  # RSI 计算周期


class PullbackDetector:
    """回调检测器。

    用法:
        detector = PullbackDetector()
        state = detector.detect("002460", daily_bars, name="赣锋锂业")
    """

    def __init__(self, anti_manipulation_gate=None):
        """初始化检测器。

        Args:
            anti_manipulation_gate: AntiManipulationGate 实例，
                若为 None 则跳过反操纵验证（仅做技术检测）。
        """
        self._anti_gate = anti_manipulation_gate

    def detect(
        self,
        symbol: str,
        daily_bars: list[Bar],
        *,
        name: str = "",
        minute_data=None,  # 分钟数据，传给反操纵门
    ) -> PullbackState:
        """执行回调检测全流程。

        Args:
            symbol: 6 位股票代码
            daily_bars: 近 60 根日线 Bar（至少 30 根）
            name: 股票名称
            minute_data: pd.DataFrame 分钟级数据（用于操纵检测）

        Returns:
            PullbackState with status, score, trigger_price, etc.
        """
        if len(daily_bars) < MIN_DAILY_BARS:
            logger.warning("Pullback: 日线数据不足 (%d < %d)", len(daily_bars), MIN_DAILY_BARS)
            return PullbackState(
                symbol=symbol, name=name,
                status=PullbackStatus.NONE,
                data_freshness="数据不足",
            )

        # 按时间排序
        bars = sorted(daily_bars, key=lambda b: b.timestamp)
        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        volumes = np.array([b.volume for b in bars], dtype=np.float64)
        n = len(bars)

        current_price = float(closes[-1])
        state = PullbackState(
            symbol=symbol,
            name=name,
            current_price=round(current_price, 2),
            timestamp=datetime.now(),
        )

        # ── Step 1: 找 20 日最高点 ──
        lookback = min(LOOKBACK_DAYS, n - 1)
        high_idx = int(np.argmax(highs[-lookback:]))
        high_idx_abs = n - lookback + high_idx
        high_20d = float(highs[high_idx_abs])
        high_date = bars[high_idx_abs].timestamp.strftime("%Y-%m-%d")

        state.high_20d = round(high_20d, 2)
        state.high_20d_date = high_date
        state.from_high_pct = round((current_price / high_20d - 1) * 100, 1)

        # 未回调: 价格还在高点附近（回落 < 5%）
        if state.from_high_pct > -MIN_PULLBACK_DEPTH * 100:
            state.status = PullbackStatus.NONE
            state.pullback_score = 80.0  # 趋势良好，不是回调场景
            state.entry_condition = "未回调 — 价格接近 20 日高点，可关注突破回踩"
            return state

        # 回调过深: 15-40% → 进入超跌反弹检测
        if abs(state.from_high_pct) > MAX_PULLBACK_DEPTH * 100:
            if abs(state.from_high_pct) <= MAX_OVERSOLD_DEPTH * 100:
                # Phase 13: 超跌反弹检测
                return self._detect_oversold(
                    symbol=symbol, name=name, state=state,
                    bars=bars, closes=closes, highs=highs,
                    lows=lows, volumes=volumes, n=n,
                    minute_data=minute_data,
                )
            # 跌幅 > 40%: 极端情况，大概率基本面出问题
            state.status = PullbackStatus.BREAK
            state.pullback_score = 10.0
            state.entry_condition = (
                f"极端跌幅 ({state.from_high_pct:.1f}%) — "
                "可能暴雷或基本面恶化，不建议入场"
            )
            return state

        # ── Step 2: 计算均线 ──
        state.ma5 = round(float(np.mean(closes[-5:])), 2)
        state.ma10 = round(float(np.mean(closes[-10:])), 2)
        state.ma20 = round(float(np.mean(closes[-min(20, n):])), 2)
        if n >= 60:
            state.ma60 = round(float(np.mean(closes[-60:])), 2)
        else:
            state.ma60 = round(float(np.mean(closes)), 2)

        # 找支撑位
        supports: list[SupportLevel] = []
        # MA20 支撑
        if current_price > state.ma20:
            supports.append(SupportLevel(price=state.ma20, label="MA20", strength=0.7))
        # MA60 支撑
        if current_price > state.ma60:
            supports.append(SupportLevel(price=state.ma60, label="MA60", strength=0.8))
        # 前低支撑 (20 日内最低点)
        recent_low = float(np.min(lows[-min(30, n):]))
        if current_price > recent_low and (not supports or recent_low < supports[-1].price):
            supports.append(SupportLevel(price=round(recent_low, 2), label="前低", strength=0.6))

        state.supports = supports

        # 找最近支撑位（价格上方最近的有效支撑）
        valid_supports = [s for s in supports if current_price > s.price]
        if valid_supports:
            nearest = max(valid_supports, key=lambda s: s.price)
            state.nearest_support = nearest.price
            state.support_distance_pct = round(
                (current_price / nearest.price - 1) * 100, 1
            )
        else:
            # 所有支撑都跌破了 → 破位
            state.status = PullbackStatus.BREAK
            state.pullback_score = 10.0
            state.entry_condition = "已跌破全部支撑位 — 破位风险，不建议入场"
            return state

        # ── Step 3: 止跌确认 ──
        state.consecutive_low_stop = self._count_low_stop(lows, n)
        state.volume_shrink_ratio = self._calc_volume_shrink(volumes, n)
        state.days_in_pullback = n - 1 - high_idx_abs

        stopped = (
            state.consecutive_low_stop >= CONSECUTIVE_NO_NEW_LOW
            and state.volume_shrink_ratio <= VOLUME_SHRINK_RATIO
        )

        # 距支撑 > 3% → 还没到位
        if state.support_distance_pct > SUPPORT_DISTANCE_THRESHOLD * 100:
            state.status = PullbackStatus.ACTIVE
            state.entry_condition = (
                f"距支撑 {state.nearest_support} 还有 "
                f"{state.support_distance_pct:.1f}%，等待回调到位"
            )
            state.pullback_score = 35.0
            return state

        # 距支撑 ≤ 3% 但未止跌
        if not stopped:
            state.status = PullbackStatus.ACTIVE
            cnt_low = state.consecutive_low_stop
            cnt_vol = "缩量" if state.volume_shrink_ratio <= VOLUME_SHRINK_RATIO else "未缩量"
            state.entry_condition = (
                f"已接近支撑 {state.nearest_support}，但止跌未确认 "
                f"(连低={cnt_low}/{CONSECUTIVE_NO_NEW_LOW}, {cnt_vol})"
            )
            state.pullback_score = 45.0
            return state

        # ── Step 4: 初步判定为 SETUP（反操纵验证前）──
        state.status = PullbackStatus.SETUP

        # ── Step 5: 反操纵验证 ──
        if self._anti_gate is not None and minute_data is not None:
            try:
                manip = self._anti_gate.verify(
                    symbol=symbol,
                    daily_bars=bars,
                    minute_data=minute_data,
                    pullback_state=state,
                )
                state.manipulation = manip
                state.authentic_pullback = not manip.is_trap

                if manip.is_trap:
                    state.status = PullbackStatus.TRAP
                    state.pullback_score = max(10.0, 50.0 - manip.risk_score * 0.5)
                    state.entry_condition = (
                        f"🚫 操纵陷阱 — {', '.join(manip.signals_matched[:3])}"
                    )
                elif manip.is_shakeout:
                    # 洗盘震仓: 存量持仓可扛，空仓需确认
                    state.authentic_pullback = True
                    state.status = PullbackStatus.SETUP
                    state.entry_condition = (
                        "⚠️ 疑似洗盘震仓 — 存量持仓可持有，新建仓建议再等 1 日确认"
                    )
                else:
                    state.authentic_pullback = True
            except Exception:
                logger.exception("反操纵验证失败，跳过操纵检测")
                state.authentic_pullback = True
        else:
            # 无分钟数据，仅做日线技术判断
            state.authentic_pullback = True
            state.manipulation = ManipulationCheck(
                risk_score=0,
                risk_level="unknown",
                suggestion="无分钟数据，未做操纵检测",
            )

        # ── 计算回调质量分 ──
        state.pullback_score = self._calc_quality_score(state)
        state.tier = self._assign_tier(state)

        # ── 设置入场触发价和止损 ──
        if state.status == PullbackStatus.SETUP and state.authentic_pullback:
            state.trigger_price = round(state.nearest_support * 1.005, 2)  # 支撑上方 0.5%
            state.stop_loss = round(state.nearest_support * 0.97, 2)       # 支撑下方 3%
            state.entry_condition = (
                f"回调到位 — 距 {state.nearest_support} "
                f"仅 {state.support_distance_pct:.1f}%，"
                f"连续 {state.consecutive_low_stop} 日止跌，缩量确认"
            )

        state.data_freshness = bars[-1].timestamp.strftime("%Y-%m-%d %H:%M")
        return state

    # ------------------------------------------------------------------
    # Phase 13: 超跌反弹检测
    # ------------------------------------------------------------------

    def _detect_oversold(
        self,
        symbol: str,
        name: str,
        state: PullbackState,
        bars: list[Bar],
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
        n: int,
        minute_data=None,
    ) -> PullbackState:
        """超跌反弹 6 步检测流程。

        只在 15-40% 跌幅范围内调用。
        经验规则: (30日最高 - 30日最低) / 30日最高 ≥ 25%
        """
        current_price = state.current_price

        # ── 计算均线 (超跌也需要) ──
        state.ma5 = round(float(np.mean(closes[-5:])), 2)
        state.ma10 = round(float(np.mean(closes[-10:])), 2)
        state.ma20 = round(float(np.mean(closes[-min(20, n):])), 2)
        if n >= 60:
            state.ma60 = round(float(np.mean(closes[-60:])), 2)
        else:
            state.ma60 = round(float(np.mean(closes)), 2)

        # ── Step 0: 阶段跌幅筛选 (经验规则) ──
        lookback_30 = min(OVERSOLD_LOOKBACK_30D, n - 1)
        high_30d = float(np.max(highs[-lookback_30:]))
        low_30d = float(np.min(lows[-lookback_30:]))

        phase_decline = (high_30d - low_30d) / high_30d if high_30d > 0 else 0.0
        high_30d_idx = int(np.argmax(highs[-lookback_30:]))
        low_30d_idx = int(np.argmin(lows[-lookback_30:]))
        high_30d_idx_abs = n - lookback_30 + high_30d_idx
        low_30d_idx_abs = n - lookback_30 + low_30d_idx
        decline_days = abs(low_30d_idx_abs - high_30d_idx_abs) + 1
        decline_speed = (phase_decline * 100) / decline_days if decline_days > 0 else 0.0

        profile = OversoldProfile(
            high_30d=round(high_30d, 2),
            low_30d=round(low_30d, 2),
            phase_decline_pct=round(phase_decline * 100, 1),
            meets_25pct_rule=phase_decline >= OVERSOLD_DECLINE_THRESHOLD,
            decline_days=decline_days,
            decline_speed_pct_day=round(decline_speed, 2),
        )
        state.oversold = profile

        # 不满足 25% 经验规则 → 不属于超跌反弹候选，退回 BREAK
        if not profile.meets_25pct_rule:
            state.status = PullbackStatus.BREAK
            state.pullback_score = 15.0
            state.entry_condition = (
                f"回调 {abs(state.from_high_pct):.1f}% 但阶段跌幅仅 "
                f"{profile.phase_decline_pct:.1f}% — 不满足 25% 超跌标准，按破位处理"
            )
            return state

        # ── Step 2: 恐慌量识别 ──
        self._detect_panic_volume(profile, volumes, bars, n)

        # ── Step 3: 止跌确认 (超跌更严格标准) ──
        state.consecutive_low_stop = self._count_low_stop(lows, n)
        state.volume_shrink_ratio = self._calc_volume_shrink(volumes, n)
        state.days_in_pullback = decline_days

        oversold_stopped = (
            state.consecutive_low_stop >= OVERSOLD_CONSECUTIVE_NO_LOW
            and state.volume_shrink_ratio <= OVERSOLD_VOLUME_SHRINK_RATIO
        )

        # ── Step 4: RSI(14) ──
        profile.rsi_14 = round(self._calc_rsi(closes, RSI_PERIOD), 1)

        # ── 反弹确认: 收盘站在 MA5 上方 ──
        profile.above_ma5 = current_price > state.ma5

        # ── 反弹确认质量 ──
        if profile.above_ma5 and state.volume_shrink_ratio <= 1.0:
            # 放量阳线站上 MA5 是最强确认
            recent_change = float(closes[-1]) - float(closes[-2]) if n >= 2 else 0
            vol_recent = float(volumes[-1])
            vol_avg_5 = float(np.mean(volumes[-5:]))
            profile.bounce_confirmed = (
                recent_change > 0 and vol_recent > vol_avg_5
            )
        else:
            profile.bounce_confirmed = False

        # ── 支撑位计算 ──
        supports: list[SupportLevel] = []
        if current_price > state.ma20:
            supports.append(SupportLevel(price=state.ma20, label="MA20", strength=0.6))
        if current_price > state.ma60:
            supports.append(SupportLevel(price=state.ma60, label="MA60", strength=0.8))
        recent_low_30 = float(np.min(lows[-min(30, n):]))
        if current_price > recent_low_30:
            supports.append(SupportLevel(
                price=round(recent_low_30, 2), label="前低(30日)", strength=0.5
            ))
        state.supports = supports

        valid_supports = [s for s in supports if current_price > s.price]
        if valid_supports:
            nearest = max(valid_supports, key=lambda s: s.price)
            state.nearest_support = nearest.price
            state.support_distance_pct = round(
                (current_price / nearest.price - 1) * 100, 1
            )
        else:
            # 超跌场景: 可能已跌破所有均线支撑
            # 以前低(30日)作为最后的支撑参考
            state.nearest_support = round(recent_low_30, 2)
            if current_price > recent_low_30:
                state.support_distance_pct = round(
                    (current_price / recent_low_30 - 1) * 100, 1
                )
            else:
                state.support_distance_pct = round(
                    (current_price / recent_low_30 - 1) * 100, 1
                )

        # ── 综合判定 ──
        # 1. 先判断是否真破位
        is_true_break = self._is_true_oversold_break(
            profile, state, oversold_stopped, volumes, n
        )

        if is_true_break:
            state.status = PullbackStatus.OVERSOLD_BREAK
            state.pullback_score = 10.0
            state.entry_condition = self._build_break_reason(profile, state)
            state.tier = PullbackTier.BLOCKED
            return state

        # 2. 判断是否 SETUP
        if oversold_stopped and profile.rsi_14 <= RSI_OVERSOLD_THRESHOLD + 15:
            # 止跌确认 + RSI 仍在低位区 → 超跌反弹候选
            state.status = PullbackStatus.OVERSOLD_SETUP
            state.pullback_score = self._calc_oversold_quality_score(profile, state)
            state.authentic_pullback = True

            # ── Step 5: 反操纵验证 ──
            if self._anti_gate is not None and minute_data is not None:
                try:
                    manip = self._anti_gate.verify(
                        symbol=symbol,
                        daily_bars=bars,
                        minute_data=minute_data,
                        pullback_state=state,
                    )
                    state.manipulation = manip

                    if manip.is_trap:
                        state.status = PullbackStatus.OVERSOLD_BREAK
                        state.authentic_pullback = False
                        state.pullback_score = max(10.0, 50.0 - manip.risk_score * 0.5)
                        state.entry_condition = (
                            f"超跌到位但检测到操纵陷阱 — {', '.join(manip.signals_matched[:3])}"
                        )
                        state.tier = PullbackTier.BLOCKED
                        return state
                    if manip.is_shakeout:
                        state.entry_condition = (
                            "超跌到位，疑似洗盘震仓 — 存量持仓可持有，新建仓建议再等 1 日确认"
                        )
                except Exception:
                    logger.exception("反操纵验证失败，跳过操纵检测")

            state.trigger_price = round(state.nearest_support * 1.005, 2)
            # 超跌止损更紧: 支撑下方 2% (普通回调 3%)
            state.stop_loss = round(state.nearest_support * 0.98, 2)

            if not state.entry_condition:
                parts = [
                    f"超跌反弹候选 — 阶段跌幅 {profile.phase_decline_pct:.1f}%",
                    f"距支撑 {state.nearest_support} 仅 {state.support_distance_pct:.1f}%",
                    f"连续 {state.consecutive_low_stop} 日止跌 + 缩量确认",
                    f"RSI({RSI_PERIOD})={profile.rsi_14:.0f}",
                ]
                if profile.panic_date:
                    parts.append(f"恐慌日 {profile.panic_date} 后缩量")
                if profile.bounce_confirmed:
                    parts.append("放量阳线站上 MA5 — 反弹确认")
                state.entry_condition = " | ".join(parts)
        else:
            # 3. 止跌未确认 → ACTIVE（监控中）
            state.status = PullbackStatus.OVERSOLD_ACTIVE
            state.pullback_score = max(25.0, self._calc_oversold_quality_score(profile, state))
            missing = []
            if state.consecutive_low_stop < OVERSOLD_CONSECUTIVE_NO_LOW:
                missing.append(
                    f"止跌不足 ({state.consecutive_low_stop}/{OVERSOLD_CONSECUTIVE_NO_LOW}日)"
                )
            if state.volume_shrink_ratio > OVERSOLD_VOLUME_SHRINK_RATIO:
                missing.append(f"缩量不足 (缩量比 {state.volume_shrink_ratio:.2f} > {OVERSOLD_VOLUME_SHRINK_RATIO})")
            state.entry_condition = (
                f"超跌进行中 (跌幅 {profile.phase_decline_pct:.1f}%) — "
                + "、".join(missing)
                + f" — 继续监控，等待止跌确认"
            )

        state.tier = self._assign_tier(state)
        state.data_freshness = bars[-1].timestamp.strftime("%Y-%m-%d %H:%M")
        return state

    # ------------------------------------------------------------------
    # 超跌反弹辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_panic_volume(
        profile: OversoldProfile,
        volumes: np.ndarray,
        bars: list[Bar],
        n: int,
    ) -> None:
        """检测恐慌量: 单日量 > 5日均量 × 2.5。

        找到最近一次恐慌日后，检查恐慌后 2-3 日是否显著缩量（恐慌耗尽）。
        搜索范围覆盖整个日线数据。
        """
        if n < 10:
            return

        # 计算每根 bar 的局部 5 日均量
        for i in range(n - 4, 4, -1):  # 从近到远扫描
            vol_5_sliding = float(np.mean(volumes[i - 4:i + 1]))
            if vol_5_sliding <= 0:
                continue
            ratio = float(volumes[i]) / vol_5_sliding
            if ratio >= PANIC_VOLUME_RATIO:
                profile.panic_volume_ratio = round(ratio, 1)
                profile.panic_date = bars[i].timestamp.strftime("%Y-%m-%d")

                # 恐慌后缩量: 恐慌日后 2-3 日均量 / 恐慌日前 5 日均量
                post_start = i + 1
                if post_start < n:
                    post_bars = min(3, n - post_start)
                    post_vol = float(np.mean(volumes[post_start:post_start + post_bars]))
                    pre_vol = vol_5_sliding
                    if pre_vol > 0:
                        profile.post_panic_volume_shrink = round(post_vol / pre_vol, 2)
                return  # 找到最近一次就停止

    @staticmethod
    def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
        """计算 RSI(14)。

        使用 Wilder's smoothing 方法。
        """
        if len(closes) < period + 1:
            return 50.0

        deltas = np.diff(closes[-period - 1:])
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)

        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))

        if avg_loss == 0:
            return 100.0
        if avg_gain == 0:
            return 0.0

        rs = avg_gain / avg_loss
        return round(100.0 - 100.0 / (1.0 + rs), 1)

    @staticmethod
    def _is_true_oversold_break(
        profile: OversoldProfile,
        state: PullbackState,
        stopped: bool,
        volumes: np.ndarray,
        n: int,
    ) -> bool:
        """判断超跌是否为真破位（而非反弹前的恐慌低点）。

        真破位信号:
          - 恐慌后继续放量下跌 (恐慌日之后没有缩量)
          - RSI 持续 < 20 且无回升迹象
          - 跌破所有支撑（均线 + 前低）
        """
        # 信号 1: 恐慌后继续放量 (post_panic_volume_shrink >= 1.0 = 没缩量)
        if profile.panic_date and profile.post_panic_volume_shrink >= 1.0:
            return True

        # 信号 2: RSI 极度低位 (< 20) 且收盘仍在 MA5 下方 → 反弹无望
        # RSI < 20 需要配合继续下跌才判定为真破位
        if profile.rsi_14 < 20 and not profile.above_ma5:
            if n >= 2 and not stopped:
                # 止跌未确认 + RSI 极低 + MA5下方 → 大概率继续跌
                return True
            # RSI 极低但止跌已确认 → 可能是底部蓄力，不判定破位

        # 信号 3: 跌破所有支撑且仍在放量下跌
        if state.support_distance_pct < -3.0:  # 低于支撑 3%+
            if n >= 2:
                vol_recent = float(volumes[-1])
                vol_avg_5 = float(np.mean(volumes[-5:]))
                if vol_recent > vol_avg_5:  # 还在放量
                    return True

        return False

    @staticmethod
    def _build_break_reason(profile: OversoldProfile, state: PullbackState) -> str:
        """构建破位原因描述。"""
        reasons = []
        if profile.panic_date and profile.post_panic_volume_shrink >= 1.0:
            reasons.append(f"恐慌日({profile.panic_date})后未缩量，出货持续")
        if profile.rsi_14 < 20:
            reasons.append(f"RSI(14)={profile.rsi_14:.0f} 极度超卖且无反弹")
        if state.support_distance_pct < -3.0:
            reasons.append("已跌破全部支撑位且放量")
        reasons.append(f"阶段跌幅 {profile.phase_decline_pct:.1f}%")
        return "超跌破位: " + "；".join(reasons) + " — 不建议入场"

    @staticmethod
    def _calc_oversold_quality_score(
        profile: OversoldProfile, state: PullbackState
    ) -> float:
        """计算超跌反弹质量分 0-100。

        评分因子:
          - 跌幅合理性 (0-20): 25-35% 满分，35-40% 递减
          - 缩量质量 (0-20): 恐慌后缩量比越低越好
          - 止跌确认 (0-20): 连续止跌天数越多越好
          - RSI 超卖程度 (0-20): 20-35 区间最优（超卖但未绝望）
          - 反弹确认 (0-20): 放量阳线站 MA5 满分
          - 操纵风险折扣: × (1 - risk/200)
        """
        score = 0.0

        # 跌幅合理性: 25-35% 最优
        d = profile.phase_decline_pct
        if 25 <= d <= 35:
            score += 20.0
        elif 35 < d <= 40:
            score += 20.0 * (1 - (d - 35) / 5)
        elif d > 40:
            score += 5.0  # 勉强给点分

        # 缩量质量: 恐慌后缩量 ≤ 0.5 → 20, ≤ 0.7 → 15, ≤ 1.0 → 8
        ps = profile.post_panic_volume_shrink
        if ps <= 0.5:
            score += 20.0
        elif ps <= 0.7:
            score += 15.0
        elif ps <= 1.0:
            score += 8.0

        # 止跌确认: 连续 3 → 15, ≥4 → 20
        score += min(20.0, state.consecutive_low_stop * 5.0)

        # RSI 超卖程度: 20-35 区间最优（超卖后有反弹空间）
        rsi = profile.rsi_14
        if 20 <= rsi <= 35:
            score += 20.0
        elif 15 <= rsi < 20:
            score += 15.0  # 太低了，可能还有一跌
        elif 35 < rsi <= 45:
            score += 10.0  # 反弹可能已经走了

        # 反弹确认: 放量阳线站 MA5
        if profile.bounce_confirmed:
            score += 20.0
        elif profile.above_ma5:
            score += 10.0

        # 操纵风险折扣
        if state.manipulation and state.manipulation.risk_score > 0:
            discount = 1.0 - state.manipulation.risk_score / 200.0
            score *= max(0.5, discount)

        return round(min(100.0, max(0.0, score)), 1)

    @staticmethod
    def _count_low_stop(lows: np.ndarray, n: int) -> int:
        """统计连续不创新低天数。"""
        count = 0
        current_min = float(lows[-1])
        for i in range(n - 2, -1, -1):
            if float(lows[i]) >= current_min:
                count += 1
            else:
                break
            current_min = min(current_min, float(lows[i]))
        return count

    @staticmethod
    def _calc_volume_shrink(volumes: np.ndarray, n: int) -> float:
        """计算缩量比 = 近 2 日均量 / 5 日均量。

        Returns:
            float: < 1.0 表示缩量，< 0.8 显著缩量。
        """
        if n < 5:
            return 1.0
        vol_5 = float(np.mean(volumes[-5:]))
        vol_2 = float(np.mean(volumes[-2:]))
        if vol_5 <= 0:
            return 1.0
        return round(vol_2 / vol_5, 2)

    @staticmethod
    def _calc_quality_score(state: PullbackState) -> float:
        """计算回调质量分 0-100。

        评分因子:
          - 深度合理性 (0-25): 5-10%=满分, 10-15%=递减
          - 缩量质量 (0-25): 缩量比越低越好
          - 支撑强度 (0-25): 支撑位越强越好
          - 止跌确认 (0-25): 连续止跌天数越多越好
          - 操纵风险折扣: × (1 - risk/200)
        """
        score = 0.0

        # 深度合理性: 5-10% 最优
        depth = abs(state.from_high_pct)
        if 5 <= depth <= 10:
            score += 25.0
        elif 10 < depth <= 15:
            score += 25.0 * (1 - (depth - 10) / 5)  # 递减到 0
        elif depth < 5:
            score += 25.0 * (depth / 5)  # 太浅，线性递减

        # 缩量质量: 缩量比 ≤ 0.6 → 25, ≤ 0.8 → 20, ≤ 1.0 → 10
        vr = state.volume_shrink_ratio
        if vr <= 0.6:
            score += 25.0
        elif vr <= 0.8:
            score += 20.0
        elif vr <= 1.0:
            score += 10.0

        # 支撑强度: 取最强支撑
        max_strength = max(
            (s.strength for s in state.supports), default=0.5
        )
        score += 25.0 * max_strength

        # 止跌确认: 连续 1→10, 2→20, ≥3→25
        score += min(25.0, state.consecutive_low_stop * 10.0)

        # 操纵风险折扣
        if state.manipulation and state.manipulation.risk_score > 0:
            discount = 1.0 - state.manipulation.risk_score / 200.0
            score *= max(0.5, discount)

        return round(min(100.0, max(0.0, score)), 1)

    @staticmethod
    def _assign_tier(state: PullbackState) -> PullbackTier:
        """根据状态和分数分配扫描等级。"""
        if state.status == PullbackStatus.TRAP:
            return PullbackTier.BLOCKED
        if state.status == PullbackStatus.BREAK:
            return PullbackTier.BLOCKED
        # Phase 13: 超跌反弹等级
        if state.status == PullbackStatus.OVERSOLD_BREAK:
            return PullbackTier.BLOCKED
        if state.status == PullbackStatus.OVERSOLD_SETUP and state.authentic_pullback:
            return PullbackTier.READY
        if state.status == PullbackStatus.OVERSOLD_ACTIVE:
            return PullbackTier.WATCH
        if state.status == PullbackStatus.SETUP and state.authentic_pullback:
            return PullbackTier.READY
        if state.status == PullbackStatus.ACTIVE:
            return PullbackTier.WATCH
        return PullbackTier.BLOCKED
