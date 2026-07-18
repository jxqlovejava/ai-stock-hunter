"""分歧/一致状态检测器。

基于"买在分歧转一致，卖在一致转分歧"的交易框架，检测四种市场状态：
  - DIVERGENCE: 放量横盘/分歧 — 多空肉搏，价格不动，方向不明
  - FORMING_CONSENSUS: 分歧转一致 — 放量突破后缩量续涨，多头胜出
  - CONSENSUS: 缩量上涨/一致 — 卖盘枯竭，上涨轻松
  - CONSENSUS_BREAKING: 一致转分歧 — 放量冲高回落，空头反扑

参考来源:
  - 比特迪克 @owudjca1t (2026/07/16-17)
  - 白泽 Phase 13 分歧/一致增强
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Union

import numpy as np

logger = logging.getLogger(__name__)

ArrayLike = Union[Sequence[float], np.ndarray]


class DivergenceConsensusPhase(str, Enum):
    """分歧/一致状态枚举。"""

    DIVERGENCE = "DIVERGENCE"  # 分歧：放量横盘
    FORMING_CONSENSUS = "FORMING_CONSENSUS"  # 分歧转一致
    CONSENSUS = "CONSENSUS"  # 一致：缩量上涨
    CONSENSUS_BREAKING = "CONSENSUS_BREAKING"  # 一致转分歧
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"  # 数据不足


# 相位→中文标签
_PHASE_LABELS: dict[DivergenceConsensusPhase, str] = {
    DivergenceConsensusPhase.DIVERGENCE: "分歧",
    DivergenceConsensusPhase.FORMING_CONSENSUS: "分歧转一致",
    DivergenceConsensusPhase.CONSENSUS: "一致",
    DivergenceConsensusPhase.CONSENSUS_BREAKING: "一致转分歧",
    DivergenceConsensusPhase.DATA_INSUFFICIENT: "数据不足",
}

# 相位→分数映射（0-100）
_PHASE_SCORES: dict[DivergenceConsensusPhase, float] = {
    DivergenceConsensusPhase.DIVERGENCE: 40.0,
    DivergenceConsensusPhase.FORMING_CONSENSUS: 65.0,
    DivergenceConsensusPhase.CONSENSUS: 75.0,
    DivergenceConsensusPhase.CONSENSUS_BREAKING: 30.0,
    DivergenceConsensusPhase.DATA_INSUFFICIENT: 50.0,
}


@dataclass
class DivergenceConsensusResult:
    """分歧/一致分析结果 DTO。

    遵循项目 DTO 优先原则，跨层使用 dataclass。
    """

    phase: DivergenceConsensusPhase = DivergenceConsensusPhase.DATA_INSUFFICIENT
    score: float = 50.0  # 0-100
    confidence: float = 0.0  # 0.0-1.0
    signals: list[str] = field(default_factory=list)

    # 关键度量
    volume_ratio: float = 0.0  # 当前均量 / 回溯均量
    price_change_net: float = 0.0  # 检测窗口净涨跌幅 %
    consecutive_shrinking: int = 0  # 连续缩量 bar 数
    detection_window: int = 0  # 检测使用的 bar 数
    summary: str = ""

    @property
    def state(self) -> str:
        """中文状态标签，供诊断报告使用。"""
        return _PHASE_LABELS.get(self.phase, "未知")

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value if isinstance(self.phase, DivergenceConsensusPhase) else str(self.phase),
            "state": self.state,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
            "volume_ratio": round(self.volume_ratio, 2),
            "price_change_net": round(self.price_change_net, 2),
            "consecutive_shrinking": self.consecutive_shrinking,
            "detection_window": self.detection_window,
            "summary": self.summary,
        }


class DivergenceConsensusAnalyzer:
    """分歧/一致状态检测器。

    对 OHLCV 日线序列检测四种分歧/一致状态。

    使用方式::

        analyzer = DivergenceConsensusAnalyzer()
        result = analyzer.analyze(close, volume, high, low)
        print(result.state, result.score)
    """

    # ---- 可调参数 ----
    DIVERGENCE_MIN_BARS: int = 5  # 分歧至少 5 根 bar
    DIVERGENCE_MAX_PRICE_CHANGE: float = 2.0  # 分歧最大净涨跌 %
    DIVERGENCE_VOL_THRESHOLD: float = 1.3  # 分歧均量/回溯均量 > 1.3

    CONSENSUS_MIN_SHRINKING: int = 3  # 一致至少连续 3 根缩量
    CONSENSUS_MIN_PRICE_RISE: float = 0.5  # 一致最低总涨幅 %

    CONSENSUS_BREAKING_VOL_MULT: float = 2.0  # 打破一致的量 > 2x 均量

    FORMING_CONSENSUS_BREAKOUT_VOL: float = 1.5  # 突破量 > 1.5x 均量
    FORMING_VOL_SHRINK_AFTER: float = 0.9  # 突破后 bar 量 < 0.9x 突破量

    LOOKBACK_BARS: int = 20  # 均量回溯窗口

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    # ----------------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------------
    def analyze(
        self,
        close: ArrayLike,
        volume: ArrayLike,
        high: Optional[ArrayLike] = None,
        low: Optional[ArrayLike] = None,
    ) -> DivergenceConsensusResult:
        """对 OHLCV 日线数据做分歧/一致分析。"""
        c = np.asarray(close, dtype=float)
        v = np.asarray(volume, dtype=float)
        h = np.asarray(high, dtype=float) if high is not None else c.copy()
        l = np.asarray(low, dtype=float) if low is not None else c.copy()

        n = min(len(c), len(v), len(h), len(l))
        if n < self.LOOKBACK_BARS:
            return DivergenceConsensusResult(
                phase=DivergenceConsensusPhase.DATA_INSUFFICIENT,
                summary=f"数据不足：需要至少 {self.LOOKBACK_BARS} 根K线，当前 {n} 根",
                confidence=0.0,
            )

        c, v, h, l = c[-n:], v[-n:], h[-n:], l[-n:]

        # 按优先级检测：先近端（一致/一致转分歧）再到远端（分歧/分歧转一致）
        # 1. 一致 → 2. 一致转分歧 → 3. 分歧转一致 → 4. 分歧

        consensus = self._detect_consensus(c, v)
        if consensus is not None:
            return consensus

        breaking = self._detect_consensus_breaking(c, v, h, l)
        if breaking is not None:
            return breaking

        forming = self._detect_forming_consensus(c, v, h)
        if forming is not None:
            return forming

        divergence = self._detect_divergence(c, v, h, l)
        if divergence is not None:
            return divergence

        return DivergenceConsensusResult(
            phase=DivergenceConsensusPhase.DATA_INSUFFICIENT,
            summary="未检测到明确的分歧/一致模式",
            confidence=0.0,
        )

    # ----------------------------------------------------------------
    # 一致检测：缩量连涨
    # ----------------------------------------------------------------
    def _detect_consensus(
        self, c: np.ndarray, v: np.ndarray
    ) -> Optional[DivergenceConsensusResult]:
        """检测缩量上涨（一致）状态。

        条件：
          1. 连续 >= CONSENSUS_MIN_SHRINKING bar 收涨且量缩
          2. 总涨幅 > CONSENSUS_MIN_PRICE_RISE%
          3. 一致 stretch 必须延伸到最近 2 根 bar 内（否则可能已被打破）
        """
        n = len(c)
        # 从最近一根 bar 向前找
        end_idx = n - 1
        # 从倒数第 CONSENSUS_MIN_SHRINKING 根开始往回扫描
        for start in range(n - self.CONSENSUS_MIN_SHRINKING, max(0, n - self.LOOKBACK_BARS) - 1, -1):
            stretch = end_idx - start + 1
            if stretch < self.CONSENSUS_MIN_SHRINKING:
                continue
            # 检查是否连续收涨+量缩
            ok = True
            for j in range(start, end_idx):
                if c[j + 1] <= c[j]:  # 价格未上涨
                    ok = False
                    break
                if v[j + 1] >= v[j]:  # 成交量未缩小
                    ok = False
                    break
            if not ok:
                continue

            # 一致 stretch 必须延伸到最近 1 根 bar（即 end_idx == n-1）
            # 否则说明一致已被打破，交给 _detect_consensus_breaking 处理
            if end_idx < n - 2:
                continue

            # 总涨幅检查
            total_rise = (c[end_idx] / c[start] - 1.0) * 100.0
            if total_rise < self.CONSENSUS_MIN_PRICE_RISE:
                continue

            # 均量比较
            avg_vol = float(np.mean(v[max(0, start - self.LOOKBACK_BARS):start]))
            recent_vol = float(np.mean(v[start:end_idx + 1]))
            vol_ratio = (recent_vol / avg_vol) if avg_vol > 1e-9 else 1.0

            return DivergenceConsensusResult(
                phase=DivergenceConsensusPhase.CONSENSUS,
                score=_PHASE_SCORES[DivergenceConsensusPhase.CONSENSUS],
                confidence=min(0.85, 0.5 + stretch * 0.1),
                volume_ratio=round(vol_ratio, 2),
                price_change_net=round(total_rise, 2),
                consecutive_shrinking=stretch,
                detection_window=stretch,
                signals=[f"缩量连涨{stretch}日，卖盘枯竭，一致状态"],
                summary=(
                    f"连续{stretch}日缩量上涨，总涨幅{total_rise:.1f}%，"
                    f"成交量萎缩至均量的{vol_ratio:.1%}。"
                    f"卖盘极度枯竭，多头不费吹灰之力，一致状态。"
                ),
            )

        return None

    # ----------------------------------------------------------------
    # 一致转分歧检测：放量冲高回落
    # ----------------------------------------------------------------
    def _detect_consensus_breaking(
        self, c: np.ndarray, v: np.ndarray, h: np.ndarray, l: np.ndarray
    ) -> Optional[DivergenceConsensusResult]:
        """检测一致转分歧。

        条件：
          1. 之前存在一致状态（缩量连涨 >= 2 bar）
          2. 一致 stretch 后紧跟一根放量 bar（量 > CONSENSUS_BREAKING_VOL_MULT x 均量）
          3. 该 bar 收跌或冲高回落（收盘靠近低点）
        """
        n = len(c)
        if n < 5:
            return None

        # 先找之前的一致 stretch（至少 2 天缩量上涨）
        consensus_end = -1
        for end in range(n - 2, max(0, n - 12), -1):
            stretch = 0
            for j in range(end, 0, -1):
                if c[j] > c[j - 1] and v[j] < v[j - 1]:
                    stretch += 1
                else:
                    break
            if stretch >= 2:
                consensus_end = end
                break

        if consensus_end < 0:
            return None

        # 一致 stretch 后紧跟的那根 bar（breaking bar）
        break_idx = consensus_end + 1
        if break_idx >= n:
            return None

        break_c = c[break_idx]
        break_v = v[break_idx]
        break_h = h[break_idx]
        break_l = l[break_idx]
        break_range = break_h - break_l

        # 均量（排除 breaking bar 自身）
        before_mask = list(range(max(0, break_idx - self.LOOKBACK_BARS), break_idx))
        if len(before_mask) < 5:
            return None
        avg_vol = float(np.mean(v[before_mask]))
        vol_ratio = (break_v / avg_vol) if avg_vol > 1e-9 else 1.0

        if vol_ratio < self.CONSENSUS_BREAKING_VOL_MULT:
            return None

        # 收盘乏力：收跌 或 收于下半部（冲高回落）
        is_bearish = break_c < c[consensus_end]
        closes_low = break_range > 0 and (break_c - break_l) / break_range < 0.4

        if not is_bearish and not closes_low:
            return None

        net_change = (break_c / c[consensus_end] - 1.0) * 100.0

        return DivergenceConsensusResult(
            phase=DivergenceConsensusPhase.CONSENSUS_BREAKING,
            score=_PHASE_SCORES[DivergenceConsensusPhase.CONSENSUS_BREAKING],
            confidence=0.75,
            volume_ratio=round(vol_ratio, 2),
            price_change_net=round(net_change, 2),
            consecutive_shrinking=0,
            detection_window=1,
            signals=[
                f"一致转分歧：量增{vol_ratio:.1f}x，"
                f"{'收跌' if is_bearish else '冲高回落'}，短线风险加大"
            ],
            summary=(
                f"此前缩量上涨（一致）被打破：紧跟 bar 成交量达均量的{vol_ratio:.1f}倍，"
                f"{'收跌' if is_bearish else '冲高回落收盘在低位'}。"
                f"空头重新集结，一致转为分歧，短线最佳卖点。"
            ),
        )

    # ----------------------------------------------------------------
    # 分歧转一致检测：放量突破 + 缩量续涨
    # ----------------------------------------------------------------
    def _detect_forming_consensus(
        self, c: np.ndarray, v: np.ndarray, h: np.ndarray
    ) -> Optional[DivergenceConsensusResult]:
        """检测分歧转一致。

        条件：
          1. 此前存在分歧（横盘缩量/放量不涨 >= 5 bar）
          2. 突破 bar：量 > FORMING_CONSENSUS_BREAKOUT_VOL x 均量，收于高位
          3. 突破后至少 1 bar 缩量续涨
        """
        n = len(c)
        if n < 8:
            return None

        avg_vol_trail = float(np.mean(v[max(0, n - self.LOOKBACK_BARS - 5):-3]))
        if avg_vol_trail <= 1e-9:
            return None

        # 找可能的突破 bar（倒数第 2-5 根）
        for breakout_idx in range(n - 3, max(0, n - 8), -1):
            break_v = v[breakout_idx]
            break_c = c[breakout_idx]
            break_h = h[breakout_idx]
            break_range = break_h - c[max(0, breakout_idx - 1)]  # approximate

            vol_ratio = break_v / avg_vol_trail
            if vol_ratio < self.FORMING_CONSENSUS_BREAKOUT_VOL:
                continue

            # 收于高位（close 在当日上半部）
            day_range = break_h - c[breakout_idx - 1]  # rough
            if day_range > 0:
                pct_high = (break_c - c[breakout_idx - 1]) / day_range
                if pct_high < 0.5:
                    continue

            # 突破后：至少 1 bar 缩量续涨
            after_ok = False
            for j in range(breakout_idx + 1, n):
                if v[j] < break_v * self.FORMING_VOL_SHRINK_AFTER and c[j] > break_c:
                    after_ok = True
                    break
            if not after_ok:
                continue

            # 确认了分歧转一致
            net_change = (c[-1] / c[breakout_idx - 5] - 1.0) * 100.0 if breakout_idx >= 5 else 0.0

            return DivergenceConsensusResult(
                phase=DivergenceConsensusPhase.FORMING_CONSENSUS,
                score=_PHASE_SCORES[DivergenceConsensusPhase.FORMING_CONSENSUS],
                confidence=0.7,
                volume_ratio=round(vol_ratio, 2),
                price_change_net=round(net_change, 2),
                consecutive_shrinking=0,
                detection_window=n - max(0, breakout_idx - 5),
                signals=[
                    f"分歧转一致：放量突破后缩量续涨，多头胜出，短线入场窗口"
                ],
                summary=(
                    f"此前横盘分歧后，出现放量突破 bar（量{vol_ratio:.1f}x均量），"
                    f"突破后缩量续涨，分歧转一致，多头确立。跟随多头。"
                ),
            )

        return None

    # ----------------------------------------------------------------
    # 分歧检测：放量横盘
    # ----------------------------------------------------------------
    def _detect_divergence(
        self, c: np.ndarray, v: np.ndarray, h: np.ndarray, l: np.ndarray
    ) -> Optional[DivergenceConsensusResult]:
        """检测放量横盘（分歧）状态。

        条件：
          1. 最近 DIVERGENCE_MIN_BARS bar 净涨跌 < DIVERGENCE_MAX_PRICE_CHANGE%
          2. 这期间均量 > DIVERGENCE_VOL_THRESHOLD x 回溯均量
        """
        n = len(c)
        window = min(self.DIVERGENCE_MIN_BARS, n)
        start = n - window

        c_seg = c[start:]
        v_seg = v[start:]

        # 净涨跌
        net_change = (c_seg[-1] / c_seg[0] - 1.0) * 100.0
        if abs(net_change) >= self.DIVERGENCE_MAX_PRICE_CHANGE:
            return None

        # 均量对比
        avg_vol_window = float(np.mean(v_seg))
        avg_vol_trail = float(np.mean(v[max(0, start - self.LOOKBACK_BARS):start]))
        if avg_vol_trail <= 1e-9:
            return None

        vol_ratio = avg_vol_window / avg_vol_trail
        if vol_ratio < self.DIVERGENCE_VOL_THRESHOLD:
            return None

        return DivergenceConsensusResult(
            phase=DivergenceConsensusPhase.DIVERGENCE,
            score=_PHASE_SCORES[DivergenceConsensusPhase.DIVERGENCE],
            confidence=0.6,
            volume_ratio=round(vol_ratio, 2),
            price_change_net=round(net_change, 2),
            consecutive_shrinking=0,
            detection_window=window,
            signals=["放量横盘分歧：多空肉搏，方向不明，建议观望等胜负分出"],
            summary=(
                f"近{window}日价格几乎不动（净涨跌{net_change:.1f}%），"
                f"但成交量是均量的{vol_ratio:.1f}倍。"
                f"多空在天量资金肉搏，消耗巨大但战线纹丝不动。"
                f"坚决不参与，等胜负分出。"
            ),
        )


def analyze_divergence_consensus(
    close: ArrayLike,
    volume: ArrayLike,
    high: Optional[ArrayLike] = None,
    low: Optional[ArrayLike] = None,
    **kwargs,
) -> DivergenceConsensusResult:
    """模块级便捷入口：对 OHLCV 序列做分歧/一致分析。

    Args:
        close: 收盘价序列
        volume: 成交量序列
        high: 最高价序列（可选，提升冲高回落检测精度）
        low: 最低价序列（可选）
        **kwargs: 透传给 DivergenceConsensusAnalyzer 的参数

    Returns:
        DivergenceConsensusResult
    """
    return DivergenceConsensusAnalyzer(**kwargs).analyze(close, volume, high, low)
