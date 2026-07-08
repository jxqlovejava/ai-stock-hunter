# -*- coding: utf-8 -*-
"""行业综合研究报告生成器 — 聚合分类/竞争/估值/催化剂/供应链。

使用模式:
    reporter = SectorResearchReporter()
    report = reporter.generate("食品饮料")
    print(f"行业评分: {report.overall_score:.0f}/100")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.industry.classifier import SectorClassifier
from src.industry.competition import CompetitionAnalyzer
from src.industry.schema import SectorReport
from src.industry.valuation import SectorValuationFramework

logger = logging.getLogger(__name__)


class SectorResearchReporter:
    """行业综合研究报告生成器。

    聚合:
      1. 行业分类
      2. 竞争格局
      3. 估值框架
      4. 催化剂分析
      5. 政策影响
      → 综合评分 0-100
    """

    def __init__(self):
        self._classifier = SectorClassifier()
        self._competition = CompetitionAnalyzer()
        self._valuation_fw = SectorValuationFramework()

    def generate(
        self,
        sector_name: str,
        current_pe: Optional[float] = None,
    ) -> SectorReport:
        """生成行业综合研究报告。

        Args:
            sector_name: 申万一级行业名称
            current_pe: 当前行业 PE（可选）

        Returns:
            SectorReport
        """
        # 1. 行业分类
        sector = self._classifier.classify(sector_name)
        if not sector.sw1_name or sector.sw1_name == "未分类":
            sector.sw1_name = sector_name

        # 2. 竞争格局
        competition = self._competition.analyze(sector_name)

        # 3. 估值框架
        valuation = self._valuation_fw.valuate(sector_name, current_pe)

        # 4. 催化剂 + 政策（简化：基于行业特征推断）
        catalysts, catalyst_score = self._assess_catalysts(sector_name)
        policy_impact, policy_notes = self._assess_policy(sector_name)

        # 5. 代表标的
        representatives = self._classifier.get_sector_stocks(sector_name)[:5]

        # 6. 综合评分
        overall = self._calc_overall_score(
            competition.moat_potential if competition else 50.0,
            valuation.valuation_score if valuation else 50.0,
            catalyst_score,
            policy_impact,
        )

        return SectorReport(
            sector=sector,
            competition=competition,
            valuation=valuation,
            catalysts=catalysts,
            catalyst_score=catalyst_score,
            prosperity_score=self._prosperity_score(sector_name),
            prosperity_trend=self._prosperity_trend(sector_name),
            policy_impact=policy_impact,
            policy_notes=policy_notes,
            representative_stocks=representatives,
            overall_score=overall,
        )

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _assess_catalysts(sector_name: str) -> tuple[list[str], float]:
        """评估行业催化剂。"""
        catalyst_map = {
            "电子": (["AI 需求爆发", "国产替代加速", "消费电子复苏"], 75),
            "电力设备": (["新能源装机超预期", "海外电网更新周期", "储能政策加码"], 70),
            "医药生物": (["创新药审批加速", "老龄化需求", "集采边际放松"], 55),
            "食品饮料": (["消费复苏", "提价周期", "渠道变革"], 50),
            "汽车": (["智能驾驶渗透", "出海加速", "换车周期"], 65),
            "银行": (["利率见顶", "资产质量改善", "分红提升"], 45),
            "计算机": (["AI 应用落地", "信创加速", "数据要素政策"], 70),
            "国防军工": (["订单兑现", "地缘紧张", "装备升级"], 60),
            "通信": (["5G-A/6G", "算力网络", "运营商资本开支"], 55),
            "有色金属": (["新能源金属需求", "供给约束", "全球通胀交易"], 55),
            "煤炭": (["供给收缩", "火电调峰需求", "高股息"], 40),
            "家用电器": (["出海", "智能家居", "以旧换新政策"], 55),
            "非银金融": (["资本市场改革", "市场活跃度提升", "利差扩大"], 50),
        }
        return catalyst_map.get(sector_name, (["行业自身发展逻辑"], 50))

    @staticmethod
    def _assess_policy(sector_name: str) -> tuple[float, list[str]]:
        """评估政策影响 -100..+100。"""
        policy_map = {
            "电力设备": (60, ["双碳政策持续加码", "新能源补贴", "电网投资加大"]),
            "电子": (50, ["大基金三期", "国产替代政策", "税收优惠"]),
            "国防军工": (50, ["国防预算增长", "军民融合"]),
            "医药生物": (-10, ["集采压力", "医保控费", "创新药支持分化"]),
            "房地产": (-30, ["房住不炒", "三道红线余压"]),
            "计算机": (40, ["信创政策", "数据二十条", "AI 监管框架"]),
            "银行": (-10, ["让利实体", "净息差压力"]),
            "食品饮料": (0, ["消费刺激政策", "暂无重大政策影响"]),
            "汽车": (30, ["新能源车购置税减免", "智能网联政策"]),
            "煤炭": (-15, ["双碳约束", "煤矿安全监管趋严"]),
            "环保": (40, ["碳中和政策", "环保投资加大"]),
            "通信": (30, ["新基建投资", "5G 覆盖"]),
        }
        return policy_map.get(sector_name, (0, ["暂无重大政策影响"]))

    @staticmethod
    def _calc_overall_score(
        moat_potential: float,
        valuation_attractiveness: float,
        catalyst_score: float,
        policy_impact: float,
    ) -> float:
        """综合评分：护城河 30% + 估值 30% + 催化剂 25% + 政策 15%。"""
        policy_normalized = 50 + policy_impact * 0.5  # 映射到 0-100
        return (
            moat_potential * 0.30
            + valuation_attractiveness * 0.30
            + catalyst_score * 0.25
            + policy_normalized * 0.15
        )

    @staticmethod
    def _prosperity_score(sector_name: str) -> float:
        """行业景气度估算。"""
        scores = {
            "电子": 65, "电力设备": 60, "医药生物": 45, "食品饮料": 55,
            "汽车": 60, "银行": 50, "计算机": 65, "国防军工": 55,
            "通信": 60, "有色金属": 50, "煤炭": 55, "家用电器": 55,
            "非银金融": 50, "房地产": 25, "建筑装饰": 30,
        }
        return scores.get(sector_name, 50.0)

    @staticmethod
    def _prosperity_trend(sector_name: str) -> str:
        trends = {
            "电子": "improving", "电力设备": "improving", "计算机": "improving",
            "医药生物": "declining", "房地产": "declining", "建筑装饰": "declining",
        }
        return trends.get(sector_name, "stable")
