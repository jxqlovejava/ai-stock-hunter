# -*- coding: utf-8 -*-
"""L3 交易员 — 信号→仓位映射。"""

from __future__ import annotations

from dataclasses import dataclass

from .l2_judge import Verdict


@dataclass
class TradeSignal:
    """交易信号。"""
    symbol: str
    action: str            # OPEN / ADD / HOLD / REDUCE / CLOSE
    target_weight: float   # 目标仓位占比 (0.0 - 1.0)
    is_core: bool = False  # 是否核心仓操作
    limit: float = 0.0     # L4 施加的仓位上限


class L3Trader:
    """L3 交易员。

    信号映射:
      - score ≥ 75 → 建仓/加仓
      - score 50-74 → 持有/观望
      - score 35-49 → 减仓
      - score < 35  → 清仓/回避

    仓位公式:
      base = (score - 50) / 50 × macro_cap
      final = min(base, L4_caps...)
    """

    def generate_signal(
        self,
        verdict: Verdict,
        macro_cap: float = 0.80,
        is_core: bool = False,
        is_gem: bool = False,
    ) -> TradeSignal:
        """生成交易信号。"""
        score = verdict.score
        action = self._score_to_action(score)

        # 基础仓位
        base = max(0, (score - 50) / 50 * macro_cap)

        # 双创折扣
        if is_gem:
            base *= 0.8

        # 核心仓/交易仓区分
        if is_core:
            action = "HOLD" if action in ("REDUCE", "CLOSE") else action

        return TradeSignal(
            symbol=verdict.symbol,
            action=action,
            target_weight=round(base, 4),
            is_core=is_core,
        )

    def _score_to_action(self, score: int) -> str:
        if score >= 75:
            return "OPEN" if score >= 80 else "ADD"
        elif score >= 50:
            return "HOLD"
        elif score >= 35:
            return "REDUCE"
        else:
            return "CLOSE"
