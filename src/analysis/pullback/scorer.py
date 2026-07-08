# -*- coding: utf-8 -*-
"""回调质量评分器 (PullbackQualityScorer)。

独立评分模块，可脱离 PullbackDetector 单独使用。
对 PullbackState 做多维度评分，输出 0-100 综合分。

评分维度:
  1. 深度合理性 (0-25): 5-10% 最优
  2. 缩量质量 (0-25): 缩量比越低越好
  3. 支撑强度 (0-25): 支撑位越强越好
  4. 止跌确认 (0-25): 连续止跌天数越多越好
  5. 操纵风险折扣: × (1 - risk/200)
"""

from __future__ import annotations

from .schemas import PullbackState


class PullbackQualityScorer:
    """回调质量评分器。

    用法:
        scorer = PullbackQualityScorer()
        score = scorer.score(state)
    """

    # 深度合理性
    DEPTH_OPTIMAL_MIN = 5.0   # 最优深度下限 (%)
    DEPTH_OPTIMAL_MAX = 10.0  # 最优深度上限 (%)
    DEPTH_MAX = 15.0          # 最大允许深度 (%)
    DEPTH_WEIGHT = 25.0

    # 缩量质量
    VOLUME_IDEAL = 0.5        # 理想缩量比
    VOLUME_GOOD = 0.8         # 良好缩量比
    VOLUME_WEIGHT = 25.0

    # 支撑强度
    SUPPORT_WEIGHT = 25.0

    # 止跌确认
    LOW_STOP_IDEAL = 3        # 理想连续不创新低天数
    LOW_STOP_WEIGHT = 25.0

    # 操纵折扣
    MANIPULATION_MAX_DISCOUNT = 0.5  # 最大折扣（风险 100 → 分数 × 0.5）

    def score(self, state: PullbackState, *, debug: bool = False) -> float:
        """计算回调质量分 0-100。

        Args:
            state: PullbackState from PullbackDetector
            debug: 若 True，打印各维度得分

        Returns:
            float: 0-100 综合分
        """
        depth_score = self._score_depth(state)
        volume_score = self._score_volume(state)
        support_score = self._score_support(state)
        stop_score = self._score_stop(state)

        raw_score = depth_score + volume_score + support_score + stop_score

        # 操纵风险折扣
        manip_discount = self._calc_manipulation_discount(state)
        final_score = raw_score * manip_discount

        if debug:
            import logging
            log = logging.getLogger(__name__)
            log.info(
                "PullbackScore [%s]: depth=%.1f vol=%.1f support=%.1f stop=%.1f "
                "raw=%.1f manip_disc=%.2f final=%.1f",
                state.symbol, depth_score, volume_score,
                support_score, stop_score, raw_score, manip_discount, final_score,
            )

        return round(min(100.0, max(0.0, final_score)), 1)

    def _score_depth(self, state: PullbackState) -> float:
        """深度合理性评分。"""
        depth = abs(state.from_high_pct)
        if self.DEPTH_OPTIMAL_MIN <= depth <= self.DEPTH_OPTIMAL_MAX:
            return self.DEPTH_WEIGHT
        if depth < self.DEPTH_OPTIMAL_MIN:
            # 太浅，线性递减到 0 (depth=0 → 0)
            return self.DEPTH_WEIGHT * (depth / self.DEPTH_OPTIMAL_MIN)
        if depth <= self.DEPTH_MAX:
            # 5% → 25, 15% → 0
            ratio = 1.0 - (depth - self.DEPTH_OPTIMAL_MAX) / (
                self.DEPTH_MAX - self.DEPTH_OPTIMAL_MAX
            )
            return self.DEPTH_WEIGHT * max(0.0, ratio)
        return 0.0

    def _score_volume(self, state: PullbackState) -> float:
        """缩量质量评分。"""
        vr = state.volume_shrink_ratio
        if vr <= self.VOLUME_IDEAL:
            return self.VOLUME_WEIGHT
        if vr <= self.VOLUME_GOOD:
            ratio = 1.0 - (vr - self.VOLUME_IDEAL) / (
                self.VOLUME_GOOD - self.VOLUME_IDEAL
            )
            return self.VOLUME_WEIGHT * (self.VOLUME_IDEAL / self.VOLUME_GOOD + ratio * 0.3)
        if vr <= 1.0:
            ratio = 1.0 - (vr - self.VOLUME_GOOD) / (1.0 - self.VOLUME_GOOD)
            return self.VOLUME_WEIGHT * 0.3 * max(0.0, ratio)
        return 0.0

    def _score_support(self, state: PullbackState) -> float:
        """支撑强度评分。"""
        if not state.supports:
            return 0.0
        max_strength = max((s.strength for s in state.supports), default=0.5)
        # 距支撑越近分越高
        dist_pct = state.support_distance_pct
        if dist_pct <= 1.0:
            dist_factor = 1.0
        elif dist_pct <= 3.0:
            dist_factor = 1.0 - (dist_pct - 1.0) / 2.0 * 0.4  # 1-3% → 1.0→0.6
        else:
            dist_factor = 0.4
        return self.SUPPORT_WEIGHT * max_strength * dist_factor

    def _score_stop(self, state: PullbackState) -> float:
        """止跌确认评分。"""
        cnt = state.consecutive_low_stop
        if cnt >= self.LOW_STOP_IDEAL:
            return self.LOW_STOP_WEIGHT
        return self.LOW_STOP_WEIGHT * (cnt / self.LOW_STOP_IDEAL)

    def _calc_manipulation_discount(self, state: PullbackState) -> float:
        """计算操纵风险折扣系数。"""
        if not state.manipulation or state.manipulation.risk_score <= 0:
            return 1.0
        risk = state.manipulation.risk_score
        discount = 1.0 - risk / 200.0
        return max(self.MANIPULATION_MAX_DISCOUNT, discount)
