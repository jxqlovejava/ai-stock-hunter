# -*- coding: utf-8 -*-
"""回调检测器 (PullbackDetector)。

基于日线数据，执行 5 步回调检测流程:
  1. 找 20 日最高点 → 计算回落幅度
  2. 找最近支撑 (MA20/MA60/前低)
  3. 止跌确认 (连续 2 日缩量 + 不创新低)
  4. 反操纵验证 (委托 AntiManipulationGate)
  5. 输出 PullbackState

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
    PullbackState,
    PullbackStatus,
    PullbackTier,
    SupportLevel,
)

logger = logging.getLogger(__name__)


# ── 保守参数 (选项 A) ──
LOOKBACK_DAYS = 20             # 高点回溯窗口
MIN_PULLBACK_DEPTH = 0.05      # 最小回调深度 5%
MAX_PULLBACK_DEPTH = 0.15      # 最大回调深度 15%（超过=破位风险）
SUPPORT_DISTANCE_THRESHOLD = 0.03  # 距支撑 ≤ 3% = 进入 setup 区
VOLUME_SHRINK_DAYS = 2         # 连续缩量天数（止跌确认）
VOLUME_SHRINK_RATIO = 0.8      # 缩量比 < 0.8 = 显著缩量
CONSECUTIVE_NO_NEW_LOW = 2     # 连续不创新低天数
MIN_DAILY_BARS = 30            # 最少日线数据


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

        # 回调过深: 超过 15%，可能是趋势逆转
        if abs(state.from_high_pct) > MAX_PULLBACK_DEPTH * 100:
            state.status = PullbackStatus.BREAK
            state.pullback_score = 15.0
            state.entry_condition = f"回调过深 ({state.from_high_pct:.1f}%) — 可能趋势逆转，不建议入场"
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
    # 辅助计算
    # ------------------------------------------------------------------

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
        if state.status == PullbackStatus.SETUP and state.authentic_pullback:
            return PullbackTier.READY
        if state.status == PullbackStatus.ACTIVE:
            return PullbackTier.WATCH
        return PullbackTier.BLOCKED
