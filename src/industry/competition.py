# -*- coding: utf-8 -*-
"""竞争格局分析 — 行业集中度/壁垒/五力模型。

使用模式:
    analyzer = CompetitionAnalyzer()
    profile = analyzer.analyze("食品饮料")
    print(f"竞争烈度: {profile.competition_intensity:.0f}/100")
"""

from __future__ import annotations

import logging

from src.industry.schema import BarrierLevel, CompetitionProfile

logger = logging.getLogger(__name__)

# 各行业竞争格局特征（专家经验 + 可被数据更新）
_SECTOR_COMPETITION: dict[str, dict] = {
    "食品饮料": {"cr5": 65, "hhi": 1800, "barrier": BarrierLevel.HIGH,
                 "barriers": ["品牌", "渠道", "规模"], "rivalry": 35,
                 "substitution": 20, "supplier": 30, "buyer": 25, "moat_potential": 85},
    "银行": {"cr5": 55, "hhi": 1200, "barrier": BarrierLevel.EXTREME,
             "barriers": ["牌照", "资本", "规模"], "rivalry": 40,
             "substitution": 15, "supplier": 20, "buyer": 20, "moat_potential": 90},
    "医药生物": {"cr5": 20, "hhi": 300, "barrier": BarrierLevel.HIGH,
                 "barriers": ["专利", "审批", "技术"], "rivalry": 50,
                 "substitution": 25, "supplier": 35, "buyer": 40, "moat_potential": 75},
    "电子": {"cr5": 15, "hhi": 250, "barrier": BarrierLevel.MEDIUM,
             "barriers": ["技术", "资本", "客户粘性"], "rivalry": 65,
             "substitution": 50, "supplier": 55, "buyer": 60, "moat_potential": 40},
    "电力设备": {"cr5": 30, "hhi": 500, "barrier": BarrierLevel.MEDIUM,
                 "barriers": ["技术", "规模", "认证"], "rivalry": 55,
                 "substitution": 35, "supplier": 40, "buyer": 45, "moat_potential": 50},
    "汽车": {"cr5": 50, "hhi": 800, "barrier": BarrierLevel.HIGH,
             "barriers": ["资本", "品牌", "供应链", "技术"], "rivalry": 55,
             "substitution": 40, "supplier": 45, "buyer": 50, "moat_potential": 55},
    "计算机": {"cr5": 10, "hhi": 150, "barrier": BarrierLevel.LOW,
               "barriers": ["技术", "客户粘性"], "rivalry": 75,
               "substitution": 60, "supplier": 30, "buyer": 35, "moat_potential": 35},
    "家用电器": {"cr5": 70, "hhi": 2000, "barrier": BarrierLevel.HIGH,
                 "barriers": ["品牌", "渠道", "规模", "技术"], "rivalry": 45,
                 "substitution": 20, "supplier": 30, "buyer": 35, "moat_potential": 70},
    "非银金融": {"cr5": 30, "hhi": 400, "barrier": BarrierLevel.MEDIUM,
                 "barriers": ["牌照", "资本", "品牌"], "rivalry": 55,
                 "substitution": 40, "supplier": 25, "buyer": 30, "moat_potential": 60},
    "有色金属": {"cr5": 25, "hhi": 350, "barrier": BarrierLevel.MEDIUM,
                 "barriers": ["资源", "资本", "环保"], "rivalry": 50,
                 "substitution": 30, "supplier": 60, "buyer": 55, "moat_potential": 45},
    "煤炭": {"cr5": 40, "hhi": 600, "barrier": BarrierLevel.HIGH,
             "barriers": ["资源", "牌照", "资本"], "rivalry": 35,
             "substitution": 45, "supplier": 40, "buyer": 50, "moat_potential": 55},
    "通信": {"cr5": 50, "hhi": 1500, "barrier": BarrierLevel.EXTREME,
             "barriers": ["牌照", "资本", "技术"], "rivalry": 30,
             "substitution": 15, "supplier": 25, "buyer": 25, "moat_potential": 80},
    "国防军工": {"cr5": 35, "hhi": 500, "barrier": BarrierLevel.EXTREME,
                 "barriers": ["资质", "技术", "保密"], "rivalry": 25,
                 "substitution": 10, "supplier": 20, "buyer": 15, "moat_potential": 70},
}


class CompetitionAnalyzer:
    """行业竞争格局分析器。

    分析维度:
      - 集中度 (CR5 / HHI)
      - 进入壁垒 (资本/技术/牌照/品牌/规模)
      - 五力模型简化版
      - 竞争烈度 0-100
    """

    def analyze(self, sector_name: str) -> CompetitionProfile:
        """分析行业竞争格局。

        Args:
            sector_name: 申万一级行业名称

        Returns:
            CompetitionProfile
        """
        data = _SECTOR_COMPETITION.get(sector_name)
        if data is None:
            return CompetitionProfile(
                sector_name=sector_name,
                competition_intensity=50.0,
                moat_potential=50.0,
            )

        # 集中度标签
        cr5 = data["cr5"]
        if cr5 >= 60:
            concentration_label = "高度集中"
        elif cr5 >= 30:
            concentration_label = "中度集中"
        else:
            concentration_label = "分散"

        return CompetitionProfile(
            sector_name=sector_name,
            cr5=cr5,
            hhi=data["hhi"],
            concentration_label=concentration_label,
            entry_barrier=data["barrier"],
            barrier_factors=data["barriers"],
            rivalry_score=data["rivalry"],
            substitution_threat=data["substitution"],
            supplier_power=data["supplier"],
            buyer_power=data["buyer"],
            # 竞争烈度 = 综合五力（0=完全垄断友好, 100=红海）
            competition_intensity=(data["rivalry"] + data["substitution"] * 0.5
                                   + data["supplier"] * 0.3 + data["buyer"] * 0.3) / 2.1,
            moat_potential=data["moat_potential"],
        )
