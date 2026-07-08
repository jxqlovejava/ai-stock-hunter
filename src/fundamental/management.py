# -*- coding: utf-8 -*-
"""管理层深度评估 — 资本配置/诚信/能力/激励对齐。

使用模式:
    evaluator = ManagementEvaluator()
    profile = evaluator.evaluate("600519", name="贵州茅台")
    print(f"管理层评分: {profile.overall_score:.0f}/100")
"""

from __future__ import annotations

import logging

from src.fundamental.schema import ManagementProfile

logger = logging.getLogger(__name__)

# 已知公司的管理层评估
_KNOWN_MANAGEMENT: dict[str, dict] = {
    "600519": {
        "capital_allocation": 85, "integrity": 90, "competency": 85,
        "incentive_alignment": 75, "insider_ownership": 0.5,
        "insider_trades": "neutral",
        "notes": ["国企背景，管理稳健", "品牌管理能力卓越"],
    },
    "000858": {
        "capital_allocation": 75, "integrity": 80, "competency": 80,
        "incentive_alignment": 70, "insider_ownership": 0.3,
        "insider_trades": "neutral",
    },
    "600036": {
        "capital_allocation": 80, "integrity": 85, "competency": 85,
        "incentive_alignment": 75, "insider_ownership": 0.2,
        "insider_trades": "neutral",
        "notes": ["零售银行战略清晰", "科技投入领先"],
    },
    "300750": {
        "capital_allocation": 75, "integrity": 80, "competency": 90,
        "incentive_alignment": 80, "insider_ownership": 23.0,
        "insider_trades": "neutral",
        "notes": ["技术型创始人", "全球化布局能力强"],
    },
    "000333": {
        "capital_allocation": 80, "integrity": 85, "competency": 85,
        "incentive_alignment": 80, "insider_ownership": 0.8,
        "insider_trades": "buying",
        "notes": ["事业部制管理成熟", "职业经理人体系完善"],
    },
}


class ManagementEvaluator:
    """管理层质量评估器。

    四维度:
      1. 资本配置能力 — ROIC vs WACC, 并购质量, 回购时机
      2. 诚信度 — 历史承诺兑现, 信息披露透明度, 违规记录
      3. 专业能力 — 行业经验, 战略执行力
      4. 激励对齐 — 持股比例, 薪酬结构, 利益一致性
    """

    def evaluate(
        self, symbol: str, name: str = ""
    ) -> ManagementProfile:
        """评估管理层质量。

        Args:
            symbol: 股票代码
            name: 公司名称

        Returns:
            ManagementProfile
        """
        known = _KNOWN_MANAGEMENT.get(symbol)
        if known:
            return ManagementProfile(
                symbol=symbol, name=name,
                capital_allocation=known["capital_allocation"],
                integrity_score=known["integrity"],
                competency_score=known["competency"],
                incentive_alignment=known["incentive_alignment"],
                insider_ownership_pct=known["insider_ownership"],
                recent_insider_trades=known.get("insider_trades", "neutral"),
                overall_score=self._weighted_score(
                    known["capital_allocation"],
                    known["integrity"],
                    known["competency"],
                    known["incentive_alignment"],
                ),
                confidence=0.6,
            )

        return ManagementProfile(
            symbol=symbol, name=name,
            overall_score=50.0,
            confidence=0.3,
        )

    @staticmethod
    def _weighted_score(
        capital: float, integrity: float, competency: float, incentive: float
    ) -> float:
        """加权综合：资本配置 30% + 诚信 25% + 能力 25% + 激励 20%。"""
        return capital * 0.30 + integrity * 0.25 + competency * 0.25 + incentive * 0.20
