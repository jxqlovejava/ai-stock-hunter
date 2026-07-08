# -*- coding: utf-8 -*-
"""护城河分析框架 — 5 维度评估。

品牌 / 转换成本 / 网络效应 / 规模经济 / 无形资产（专利/牌照）
综合评分 0-100，对应 MoatWidth 四级分类。

使用模式:
    analyzer = MoatAnalyzer()
    profile = analyzer.analyze("600519", name="贵州茅台")
    print(f"护城河: {profile.overall_width.value}, 评分 {profile.moat_score:.0f}")
"""

from __future__ import annotations

import logging

from src.fundamental.schema import MoatProfile, MoatSource, MoatWidth

logger = logging.getLogger(__name__)

# 已知标的的护城河评估（专家经验 + 可用于覆盖/补充数据源分析）
_KNOWN_MOATS: dict[str, dict] = {
    # 食品饮料
    "600519": {"width": MoatWidth.DOMINANT, "score": 95,
               "brand": 95, "switching_cost": 80, "network_effect": 60,
               "scale_economy": 85, "intangible": 90,
               "trend": "stable",
               "evidence": ["国酒品牌不可复制", "经销商体系巩固护城河", "定价权极强"],
               "threats": ["消费习惯变迁", "政策限酒"]},
    "000858": {"width": MoatWidth.WIDE, "score": 85,
               "brand": 90, "switching_cost": 60, "network_effect": 55,
               "scale_economy": 80, "intangible": 75,
               "trend": "stable",
               "evidence": ["五粮液品牌力仅次于茅台", "浓香型龙头地位"],
               "threats": ["高端白酒竞争加剧"]},
    # 互联网/科技
    "00700": {"width": MoatWidth.WIDE, "score": 90,
              "brand": 75, "switching_cost": 95, "network_effect": 95,
              "scale_economy": 90, "intangible": 80,
              "trend": "stable",
              "evidence": ["微信社交网络不可替代", "支付+小程序生态"],
              "threats": ["监管风险", "字节竞争"]},
    # 银行
    "600036": {"width": MoatWidth.WIDE, "score": 80,
               "brand": 70, "switching_cost": 85, "network_effect": 70,
               "scale_economy": 85, "intangible": 75,
               "trend": "stable",
               "evidence": ["零售银行龙头", "AUM 规模优势", "财富管理领先"],
               "threats": ["利率市场化", "互联网金融分流"]},
    # 医药
    "600276": {"width": MoatWidth.WIDE, "score": 80,
               "brand": 65, "switching_cost": 60, "network_effect": 55,
               "scale_economy": 80, "intangible": 90,
               "trend": "stable",
               "evidence": ["创新药管线深厚", "销售网络覆盖广"],
               "threats": ["集采降价", "创新药竞争"]},
    # 家电
    "000333": {"width": MoatWidth.WIDE, "score": 85,
               "brand": 85, "switching_cost": 50, "network_effect": 45,
               "scale_economy": 90, "intangible": 80,
               "trend": "stable",
               "evidence": ["全球家电龙头", "制造+渠道双壁垒", "品牌矩阵完整"],
               "threats": ["地产周期", "原材料涨价"]},
    # 新能源
    "300750": {"width": MoatWidth.NARROW, "score": 65,
               "brand": 55, "switching_cost": 60, "network_effect": 40,
               "scale_economy": 85, "intangible": 75,
               "trend": "improving",
               "evidence": ["动力电池全球第一", "规模+技术双领先"],
               "threats": ["技术路线变化", "二线厂商追赶", "海外政策风险"]},
}


class MoatAnalyzer:
    """护城河分析器。

    五维度评估:
      1. 品牌溢价 — 消费者是否愿意支付溢价
      2. 转换成本 — 客户迁移成本多高
      3. 网络效应 — 用户越多价值越大
      4. 规模经济 — 规模优势是否可持续
      5. 无形资产 — 专利/牌照/特许经营权
    """

    def analyze(self, symbol: str, name: str = "") -> MoatProfile:
        """分析公司护城河。

        Args:
            symbol: 股票代码
            name: 公司名称（可选）

        Returns:
            MoatProfile
        """
        known = _KNOWN_MOATS.get(symbol)
        if known:
            return MoatProfile(
                symbol=symbol,
                name=name or known.get("name", symbol),
                overall_width=known["width"],
                moat_score=known["score"],
                dimensions={
                    "brand": known["brand"],
                    "switching_cost": known["switching_cost"],
                    "network_effect": known["network_effect"],
                    "scale_economy": known["scale_economy"],
                    "intangible": known["intangible"],
                },
                moat_trend=known["trend"],
                key_evidence=known["evidence"],
                threats=known["threats"],
                confidence=0.75,
            )

        # 未知标的 → 中性评分
        return MoatProfile(
            symbol=symbol,
            name=name,
            overall_width=MoatWidth.NONE,
            moat_score=50.0,
            confidence=0.3,
            key_evidence=["[DATA_GAP] 缺乏护城河评估数据"],
        )

    def classify_width(self, moat_score: float) -> MoatWidth:
        """根据评分确定护城河宽度。"""
        if moat_score >= 85:
            return MoatWidth.DOMINANT
        elif moat_score >= 70:
            return MoatWidth.WIDE
        elif moat_score >= 50:
            return MoatWidth.NARROW
        return MoatWidth.NONE
