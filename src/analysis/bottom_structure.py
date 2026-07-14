# -*- coding: utf-8 -*-
"""底部结构分析 — 小资金做大纪律框架（A/B 段 + 中枢 + 逆势确认）。

源自交易纪律视频「小资金如何做大？一定要有方法有纪律」的可执行化:

  1. 标中枢（打架区）— 价格横盘、阴阳互吞、上不去下不来
  2. 比 A/B 段 — 最大中枢之前的下跌 A vs 破位后下跌 B
     - B ≥ A → 空头仍有劲，禁止抄底（接飞刀）
     - B < A → 顺势力量衰竭，可关注，不可动手
  3. 逆势力量确认 — 看涨吞没/底部分形 + 突破造低点高点
  4. 回踩不破前低 → 轻仓试多

两句总规则:
  顺势力量不足 + 逆势力量加强
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Union

import numpy as np


class BottomPhase(str, Enum):
    """底部结构所处阶段。"""

    NOT_IN_DOWNTREND = "NOT_IN_DOWNTREND"      # 非下跌环境，框架不适用
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"    # K 线不足
    NO_PIVOT = "NO_PIVOT"                      # 找不到有效中枢
    CATCHING_KNIFE = "CATCHING_KNIFE"          # B≥A，禁止抄底
    TREND_EXHAUSTED = "TREND_EXHAUSTED"        # B<A，顺势衰竭，仅观察
    COUNTER_CONFIRMED = "COUNTER_CONFIRMED"    # 逆势确认，等回踩
    LIGHT_LONG_SETUP = "LIGHT_LONG_SETUP"      # 回踩不破，轻仓试多


@dataclass
class PivotZone:
    """中枢 / 打架区。"""

    start_idx: int
    end_idx: int
    high: float
    low: float

    @property
    def width(self) -> int:
        return max(0, self.end_idx - self.start_idx + 1)

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def range_pct(self) -> float:
        if self.mid <= 0:
            return 0.0
        return (self.high - self.low) / self.mid


@dataclass
class BottomStructureResult:
    """底部结构分析结果。"""

    phase: BottomPhase = BottomPhase.DATA_INSUFFICIENT
    a_decline_pct: float = 0.0          # A 段跌幅 %（正值=下跌）
    b_decline_pct: float = 0.0          # B 段跌幅 %
    ab_ratio: float = 0.0               # B/A（≥1 空头仍强）
    largest_pivot: Optional[PivotZone] = None
    trend_exhausted: bool = False       # 顺势力量不足
    counter_confirmed: bool = False     # 逆势力量加强
    pullback_holds_low: bool = False    # 回踩不破前低
    entry_allowed: bool = False         # 仅 LIGHT_LONG_SETUP
    light_position_only: bool = True    # 即使允许，也只轻仓
    swing_low: float = 0.0              # 参考前低
    structure_break_level: float = 0.0  # 造低点高点（突破位）
    score: float = 50.0                 # 0-100 供诊断加权
    confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        p = self.largest_pivot
        return {
            "phase": self.phase.value,
            "a_decline_pct": round(self.a_decline_pct, 2),
            "b_decline_pct": round(self.b_decline_pct, 2),
            "ab_ratio": round(self.ab_ratio, 3),
            "trend_exhausted": self.trend_exhausted,
            "counter_confirmed": self.counter_confirmed,
            "pullback_holds_low": self.pullback_holds_low,
            "entry_allowed": self.entry_allowed,
            "light_position_only": self.light_position_only,
            "swing_low": self.swing_low,
            "structure_break_level": self.structure_break_level,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 2),
            "signals": list(self.signals),
            "summary": self.summary,
            "pivot": (
                {
                    "start_idx": p.start_idx,
                    "end_idx": p.end_idx,
                    "high": p.high,
                    "low": p.low,
                    "width": p.width,
                    "range_pct": round(p.range_pct, 4),
                }
                if p
                else None
            ),
        }


# ── 默认参数（可调，偏保守）────────────────────────────────────────
MIN_BARS = 40
LOOKBACK = 80
DOWNTREND_PCT = 8.0              # 近 N 日至少跌 8% 才进入框架
PIVOT_MIN_BARS = 5
PIVOT_MAX_BARS = 18
PIVOT_MAX_NET_FRAC = 0.35        # 区间净位移 / 区间振幅 上限 → 横盘
PIVOT_MIN_RANGE_PCT = 0.02       # 中枢最小振幅
AB_EXHAUST_RATIO = 1.0           # B/A < 1 → 衰竭
ENGULF_BODY_RATIO = 0.55         # 阳线实体占当日振幅
FRACTAL_LOOKBACK = 2


ArrayLike = Union[Sequence[float], np.ndarray]


class BottomStructureAnalyzer:
    """A/B 段底部结构分析器。

    用法:
        analyzer = BottomStructureAnalyzer()
        result = analyzer.analyze(open_, high, low, close)
        if result.entry_allowed:
            ...  # 轻仓试多
    """

    def __init__(
        self,
        lookback: int = LOOKBACK,
        downtrend_pct: float = DOWNTREND_PCT,
        ab_exhaust_ratio: float = AB_EXHAUST_RATIO,
    ) -> None:
        self.lookback = lookback
        self.downtrend_pct = downtrend_pct
        self.ab_exhaust_ratio = ab_exhaust_ratio

    def analyze(
        self,
        high: ArrayLike,
        low: ArrayLike,
        close: ArrayLike,
        open_: Optional[ArrayLike] = None,
    ) -> BottomStructureResult:
        """对单票 OHLCV 序列做底部结构分析（至少 40 根日线）。"""
        h = np.asarray(high, dtype=float)
        l = np.asarray(low, dtype=float)
        c = np.asarray(close, dtype=float)
        o = np.asarray(open_, dtype=float) if open_ is not None else c.copy()

        n = len(c)
        if n < MIN_BARS or len(h) != n or len(l) != n:
            return BottomStructureResult(
                phase=BottomPhase.DATA_INSUFFICIENT,
                summary="K 线不足，无法做 A/B 段底部结构分析",
                confidence=0.0,
                score=50.0,
            )

        # 截取 lookback
        start = max(0, n - self.lookback)
        h, l, c, o = h[start:], l[start:], c[start:], o[start:]
        n = len(c)

        # 1) 下跌环境
        peak = float(np.max(h))
        last = float(c[-1])
        if peak <= 0:
            return BottomStructureResult(
                phase=BottomPhase.DATA_INSUFFICIENT,
                summary="价格数据异常",
                score=50.0,
            )
        drawdown_pct = (peak - last) / peak * 100.0
        if drawdown_pct < self.downtrend_pct:
            return BottomStructureResult(
                phase=BottomPhase.NOT_IN_DOWNTREND,
                signals=[f"近端回撤仅 {drawdown_pct:.1f}% < {self.downtrend_pct}% 门槛"],
                summary="非显著下跌环境，A/B 段抄底框架不适用",
                score=55.0,
                confidence=0.5,
            )

        # 2) 找中枢
        pivots = self._find_pivots(h, l, c)
        if not pivots:
            return BottomStructureResult(
                phase=BottomPhase.NO_PIVOT,
                signals=[f"回撤 {drawdown_pct:.1f}% 但未识别有效中枢"],
                summary="下跌中未找到有效打架区/中枢，暂不抄底",
                score=35.0,
                confidence=0.4,
            )

        # 取「级别最大」中枢：优先宽度，其次振幅
        pivot = max(pivots, key=lambda p: (p.width, p.range_pct))

        # 3) A/B 段
        a_pct, b_pct, a_ok, b_ok = self._measure_ab(h, l, c, pivot)
        if not a_ok or a_pct <= 0:
            return BottomStructureResult(
                phase=BottomPhase.NO_PIVOT,
                largest_pivot=pivot,
                signals=["中枢前无清晰 A 段下跌"],
                summary="中枢前下跌段不清晰，框架暂不适用",
                score=40.0,
                confidence=0.35,
            )

        ab_ratio = (b_pct / a_pct) if a_pct > 1e-9 else 0.0
        trend_exhausted = b_ok and ab_ratio < self.ab_exhaust_ratio
        catching_knife = (not b_ok) or ab_ratio >= self.ab_exhaust_ratio

        signals: list[str] = [
            f"最大中枢 [{pivot.start_idx}:{pivot.end_idx}] "
            f"宽{pivot.width}日 振幅{pivot.range_pct * 100:.1f}%",
            f"A段跌幅 {a_pct:.1f}% / B段跌幅 {b_pct:.1f}% → B/A={ab_ratio:.2f}",
        ]

        if catching_knife:
            phase = BottomPhase.CATCHING_KNIFE
            signals.append("B≥A 或 B 段未充分展开：空头仍有劲 → 禁止接飞刀")
            return BottomStructureResult(
                phase=phase,
                a_decline_pct=a_pct,
                b_decline_pct=b_pct,
                ab_ratio=ab_ratio,
                largest_pivot=pivot,
                trend_exhausted=False,
                counter_confirmed=False,
                entry_allowed=False,
                score=self._score_phase(phase, False, False),
                confidence=0.7,
                signals=signals,
                summary=(
                    f"接飞刀风险：B/A={ab_ratio:.2f}≥1，"
                    f"顺势力量未衰竭，禁止抄底"
                ),
            )

        # B < A：顺势衰竭
        signals.append("B<A：顺势力量不足，可关注，不可动手")
        swing_low, break_level, counter, holds = self._counter_trend(
            o, h, l, c, pivot
        )
        trend_exhausted = True

        if not counter:
            phase = BottomPhase.TREND_EXHAUSTED
            signals.append("逆势力量尚未确认（缺看涨吞没/底部分形/结构突破）")
            return BottomStructureResult(
                phase=phase,
                a_decline_pct=a_pct,
                b_decline_pct=b_pct,
                ab_ratio=ab_ratio,
                largest_pivot=pivot,
                trend_exhausted=True,
                counter_confirmed=False,
                pullback_holds_low=holds,
                entry_allowed=False,
                swing_low=swing_low,
                structure_break_level=break_level,
                score=self._score_phase(phase, False, holds),
                confidence=0.65,
                signals=signals,
                summary=(
                    f"顺势衰竭（B/A={ab_ratio:.2f}<1），"
                    f"等待逆势确认后再试多"
                ),
            )

        signals.append("逆势力量已确认（K 线 + 结构突破）")
        if holds:
            phase = BottomPhase.LIGHT_LONG_SETUP
            signals.append("回踩不破前低 → 轻仓试多窗口")
            summary = (
                f"底部结构成立：顺势衰竭 + 逆势确认 + 回踩不破，"
                f"仅轻仓试多（前低 {swing_low:.2f}）"
            )
            entry = True
        else:
            phase = BottomPhase.COUNTER_CONFIRMED
            signals.append("已逆势确认，等待回踩不破前低")
            summary = (
                f"逆势已确认（突破位 {break_level:.2f}），"
                f"等回踩不破前低 {swing_low:.2f} 再轻仓试多"
            )
            entry = False

        return BottomStructureResult(
            phase=phase,
            a_decline_pct=a_pct,
            b_decline_pct=b_pct,
            ab_ratio=ab_ratio,
            largest_pivot=pivot,
            trend_exhausted=True,
            counter_confirmed=True,
            pullback_holds_low=holds,
            entry_allowed=entry,
            light_position_only=True,
            swing_low=swing_low,
            structure_break_level=break_level,
            score=self._score_phase(phase, True, holds),
            confidence=0.75 if entry else 0.7,
            signals=signals,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # 内部算法
    # ------------------------------------------------------------------

    def _find_pivots(
        self, h: np.ndarray, l: np.ndarray, c: np.ndarray
    ) -> list[PivotZone]:
        """扫描横盘中枢：区间净位移小、振幅足够、持续 ≥ 5 日。"""
        n = len(c)
        pivots: list[PivotZone] = []
        # 不扫最后 3 根，给 B 段留空间；也不从太靠前开始
        end_limit = max(PIVOT_MIN_BARS + 5, n - 3)

        for i in range(0, end_limit - PIVOT_MIN_BARS + 1):
            max_w = min(PIVOT_MAX_BARS, end_limit - i)
            best: Optional[PivotZone] = None
            for w in range(PIVOT_MIN_BARS, max_w + 1):
                seg_h = float(np.max(h[i : i + w]))
                seg_l = float(np.min(l[i : i + w]))
                if seg_h <= seg_l:
                    continue
                span = seg_h - seg_l
                mid = (seg_h + seg_l) / 2.0
                if mid <= 0:
                    continue
                range_pct = span / mid
                if range_pct < PIVOT_MIN_RANGE_PCT:
                    continue
                net = abs(float(c[i + w - 1]) - float(c[i]))
                if net / span > PIVOT_MAX_NET_FRAC:
                    continue
                # 方向性：中枢应出现在下跌后半段（中枢前有下跌）
                pre = c[max(0, i - 15) : i]
                if len(pre) >= 3 and float(pre[0]) <= float(pre[-1]) * 1.01:
                    # 进入中枢前没有明显下跌，跳过
                    if i > 10:
                        continue
                cand = PivotZone(start_idx=i, end_idx=i + w - 1, high=seg_h, low=seg_l)
                if best is None or cand.width >= best.width:
                    best = cand
            if best is not None:
                pivots.append(best)

        # 合并重叠，保留更宽者
        if not pivots:
            return []
        pivots.sort(key=lambda p: p.start_idx)
        merged: list[PivotZone] = [pivots[0]]
        for p in pivots[1:]:
            last = merged[-1]
            if p.start_idx <= last.end_idx + 1:
                if p.width > last.width:
                    merged[-1] = p
            else:
                merged.append(p)
        return merged

    def _measure_ab(
        self,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
        pivot: PivotZone,
    ) -> tuple[float, float, bool, bool]:
        """计算 A/B 段跌幅 %。返回 (a_pct, b_pct, a_ok, b_ok)。"""
        # A：中枢之前的高点 → 进入中枢时的相对低点
        pre_start = max(0, pivot.start_idx - 40)
        pre_slice = h[pre_start : pivot.start_idx + 1]
        if len(pre_slice) < 2:
            return 0.0, 0.0, False, False
        a_high = float(np.max(pre_slice))
        # 进入中枢附近低点
        a_low = float(np.min(l[pre_start : pivot.end_idx + 1]))
        if a_high <= 0 or a_low >= a_high:
            return 0.0, 0.0, False, False
        a_pct = (a_high - a_low) / a_high * 100.0

        # B：破中枢下沿后到新低
        post_start = pivot.end_idx + 1
        if post_start >= len(c):
            return a_pct, 0.0, True, False
        post_low = float(np.min(l[post_start:]))
        # 必须创中枢下沿新低才算 B 段
        if post_low >= pivot.low * 0.999:
            return a_pct, 0.0, True, False
        b_high = pivot.low  # 从中枢下沿算破位跌幅
        b_pct = (b_high - post_low) / b_high * 100.0 if b_high > 0 else 0.0
        return a_pct, max(0.0, b_pct), True, True

    def _counter_trend(
        self,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
        pivot: PivotZone,
    ) -> tuple[float, float, bool, bool]:
        """逆势确认 + 回踩不破。

        Returns:
            (swing_low, structure_break_level, counter_confirmed, pullback_holds)
        """
        post = slice(pivot.end_idx, None)
        if pivot.end_idx >= len(c) - 2:
            return 0.0, 0.0, False, False

        # 波段低点：中枢结束后最低
        region_l = l[post]
        region_h = h[post]
        region_o = o[post]
        region_c = c[post]
        if len(region_l) < 3:
            return 0.0, 0.0, False, False

        low_rel = int(np.argmin(region_l))
        swing_low = float(region_l[low_rel])
        # 造低点的那根 K 线高点
        break_level = float(region_h[low_rel])

        # 看涨吞没（近 5 根内）
        engulf = False
        for i in range(max(1, len(region_c) - 5), len(region_c)):
            prev_o, prev_c = float(region_o[i - 1]), float(region_c[i - 1])
            cur_o, cur_c = float(region_o[i]), float(region_c[i])
            prev_bear = prev_c < prev_o
            cur_bull = cur_c > cur_o
            body = abs(cur_c - cur_o)
            rng = float(region_h[i]) - float(region_l[i])
            if (
                prev_bear
                and cur_bull
                and cur_c >= prev_o
                and cur_o <= prev_c
                and rng > 0
                and body / rng >= ENGULF_BODY_RATIO
            ):
                engulf = True
                break_level = max(break_level, float(region_h[i]))
                break

        # 底部分形：局部最低后至少 1 根收阳
        fractal = False
        if 1 <= low_rel < len(region_l) - 1:
            if (
                region_l[low_rel] <= region_l[low_rel - 1]
                and region_l[low_rel] <= region_l[low_rel + 1]
            ):
                # 低点后出现阳线
                after = region_c[low_rel + 1 :]
                after_o = region_o[low_rel + 1 :]
                if len(after) > 0 and any(
                    float(after[j]) > float(after_o[j]) for j in range(len(after))
                ):
                    fractal = True

        # 结构突破：收盘站上造低点高点
        structure_break = False
        if low_rel < len(region_c) - 1:
            after_c = region_c[low_rel + 1 :]
            if len(after_c) > 0 and float(np.max(after_c)) > break_level:
                structure_break = True

        counter = (engulf or fractal) and structure_break

        # 回踩不破：突破后最低仍 ≥ swing_low * (1 - 0.3%)
        holds = False
        if structure_break:
            # 找首次收盘突破
            break_i = None
            for j in range(low_rel + 1, len(region_c)):
                if float(region_c[j]) > break_level:
                    break_i = j
                    break
            if break_i is not None and break_i < len(region_l) - 1:
                pb_low = float(np.min(region_l[break_i:]))
                holds = pb_low >= swing_low * 0.997
            elif break_i is not None:
                # 刚突破尚未回踩，视为结构确认但未完成回踩验证
                holds = False
            # 若当前仍在突破后的强势中且未破前低
            if break_i is not None:
                min_after = float(np.min(region_l[break_i:]))
                if min_after >= swing_low * 0.997 and float(region_c[-1]) > break_level:
                    # 仍在突破位上方且未破前低，可视为 setup（偏积极）
                    holds = True

        return swing_low, break_level, counter, holds

    @staticmethod
    def _score_phase(
        phase: BottomPhase, counter: bool, holds: bool
    ) -> float:
        """把阶段映射到 0-100 诊断分（越高越偏多/可关注）。"""
        mapping = {
            BottomPhase.CATCHING_KNIFE: 20.0,
            BottomPhase.NO_PIVOT: 35.0,
            BottomPhase.DATA_INSUFFICIENT: 50.0,
            BottomPhase.NOT_IN_DOWNTREND: 55.0,
            BottomPhase.TREND_EXHAUSTED: 55.0,
            BottomPhase.COUNTER_CONFIRMED: 72.0,
            BottomPhase.LIGHT_LONG_SETUP: 85.0,
        }
        return mapping.get(phase, 50.0)


def analyze_bottom_structure(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    open_: Optional[ArrayLike] = None,
    **kwargs,
) -> BottomStructureResult:
    """模块级便捷入口。"""
    return BottomStructureAnalyzer(**kwargs).analyze(high, low, close, open_)
