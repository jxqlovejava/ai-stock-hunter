# -*- coding: utf-8 -*-
"""行业综合研究报告生成器 — 聚合分类/竞争/估值/催化剂/供应链。

使用模式:
    reporter = SectorResearchReporter()
    report = reporter.generate("有色金属", symbol="002460")
    print(reporter.to_checklist_string(report))
    print(f"行业评分: {report.overall_score:.0f}/100")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.industry.classifier import SectorClassifier
from src.industry.competition import CompetitionAnalyzer
from src.industry.global_commodity import GlobalCommodityAnalyzer, is_global_commodity_industry
from src.industry.schema import SectorReport
from src.industry.supply_chain import SupplyChainDeepMapper
from src.industry.valuation import SectorValuationFramework
from src.industry.workflow_validator import SectorWorkflowValidator

logger = logging.getLogger(__name__)


class SectorResearchReporter:
    """行业综合研究报告生成器。

    聚合完整 6+1 步行业研究框架:
      1. 行业定位 (分类 + 生命周期)
      2. 市场规模 (TAM / CAGR / CR5)
      3. 竞争格局 (波特五力 + 护城河)
      4. 估值背景 (PE/PB 分位 + 拥挤度)
      5. 催化剂 (政策 + 技术 + M&A)
      6. 供应链瓶颈 (映射 + 瓶颈身份 + 成本传导)
      7. 全球供需平衡 (仅全球定价大宗商品)
      → 综合评分 0-100 + Workflow Checklist
    """

    def __init__(self):
        self._classifier = SectorClassifier()
        self._competition = CompetitionAnalyzer()
        self._valuation_fw = SectorValuationFramework()
        self._supply_chain_mapper = SupplyChainDeepMapper()
        self._validator = SectorWorkflowValidator()
        self._global_analyzer = GlobalCommodityAnalyzer()

    def generate(
        self,
        sector_name: str,
        current_pe: Optional[float] = None,
        symbol: str = "",
        strict_workflow: bool = True,
    ) -> SectorReport:
        """生成行业综合研究报告。

        Args:
            sector_name: 申万一级行业名称
            current_pe: 当前行业 PE（可选）
            symbol: 个股代码，用于供应链分析 (可选)
            strict_workflow: True=缺失步骤计入 data_gaps

        Returns:
            SectorReport 含 step_status + checklist
        """
        report = SectorReport()

        # ---- Step 1: 行业定位 ----
        sector = self._classifier.classify(sector_name)
        if not sector.sw1_name or sector.sw1_name == "未分类":
            sector.sw1_name = sector_name
        report.sector = sector
        self._validator.mark_step(
            report, "step1", "行业定位",
            source_tier="T1", freshness_hours=24, confidence=0.85,
        )

        # ---- Step 2: 市场规模 (TAM/CAGR/CR5) ----
        tam = self._estimate_tam_cagr_cr5(sector_name)
        report.tam_estimate = tam
        self._validator.mark_step(
            report, "step2", "市场规模",
            source_tier=tam.get("source_tier", "T2"),
            freshness_hours=24,
            confidence=tam.get("confidence", 0.60),
        )

        # ---- Step 3: 竞争格局 ----
        competition = self._competition.analyze(sector_name)
        report.competition = competition
        self._validator.mark_step(
            report, "step3", "竞争格局",
            source_tier="T2", freshness_hours=168, confidence=0.65,
        )

        # ---- Step 4: 估值背景 ----
        valuation = self._valuation_fw.valuate(sector_name, current_pe)
        report.valuation = valuation
        self._validator.mark_step(
            report, "step4", "估值背景",
            source_tier="T1" if current_pe else "T2",
            freshness_hours=1 if current_pe else 24,
            confidence=0.75 if current_pe else 0.65,
        )

        # ---- Step 5: 催化剂 + 政策 ----
        catalysts, catalyst_score = self._assess_catalysts(sector_name)
        policy_impact, policy_notes = self._assess_policy(sector_name)
        report.catalysts = catalysts
        report.catalyst_score = catalyst_score
        report.policy_impact = policy_impact
        report.policy_notes = policy_notes
        self._validator.mark_step(
            report, "step5", "催化剂",
            source_tier="T2", freshness_hours=12, confidence=0.60,
        )

        # ---- Step 6: 供应链瓶颈 ----
        if symbol:
            sc_data = self._analyze_supply_chain(symbol)
        else:
            sc_data = {"in_chain": False, "message": "未提供个股代码，跳过供应链分析"}
        report.supply_chain_summary = sc_data.get("node_name", "")
        self._validator.mark_step(
            report, "step6", "供应链瓶颈",
            source_tier="T2", freshness_hours=168,
            confidence=0.70 if symbol else 0.50,
        )

        # ---- Step 7: 全球供需平衡 (门控) ----
        is_global = is_global_commodity_industry(sector_name)
        if is_global:
            global_data = self._global_analyzer.analyze(sector_name)
            report.global_commodity = global_data
            gq = global_data.get("data_quality", {})
            self._validator.mark_step(
                report, "step7", "全球供需平衡",
                source_tier=gq.get("source_tier", "T2"),
                freshness_hours=gq.get("freshness_hours", 168),
                confidence=gq.get("confidence", 0.60),
            )
        else:
            self._validator.mark_skipped(
                report, "step7", "全球供需平衡",
                f"{sector_name} 非全球定价大宗商品，跳过",
            )

        # ---- 代表标的 + 综合评分 ----
        report.representative_stocks = self._classifier.get_sector_stocks(sector_name)[:5]
        report.prosperity_score = self._prosperity_score(sector_name)
        report.prosperity_trend = self._prosperity_trend(sector_name)

        report.overall_score = self._calc_overall_score(
            competition.moat_potential if competition else 50.0,
            valuation.valuation_score if valuation else 50.0,
            catalyst_score,
            policy_impact,
        )

        # ---- Workflow 验证 ----
        self._validator.validate(report, is_global=is_global, strict=strict_workflow)

        return report

    def to_checklist_string(self, report: SectorReport) -> str:
        """生成 Workflow checklist 文本。"""
        is_global = report.global_commodity is not None and report.global_commodity.get("enabled", False)
        return self._validator.format_checklist(report, is_global=is_global)

    # ------------------------------------------------------------------
    # Step 2: TAM/CAGR/CR5 估算
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tam_cagr_cr5(sector_name: str) -> dict:
        """估算行业市场规模和集中度 (T2 级别估算)。"""
        # 行业总市值参考 + CAGR 估计 + CR5 来自 competition.py 的硬编码
        tam_map = {
            "有色金属": {
                "tam_yi": 28000, "cagr_3y": 15.0,
                "cr5": 22.0, "cr10": 38.0,
                "trend": "新能源金属拉动增长，传统工业金属稳定",
            },
            "食品饮料": {
                "tam_yi": 52000, "cagr_3y": 8.0,
                "cr5": 35.0, "cr10": 55.0,
                "trend": "消费升级放缓，龙头集中度提升",
            },
            "电子": {
                "tam_yi": 65000, "cagr_3y": 18.0,
                "cr5": 15.0, "cr10": 28.0,
                "trend": "AI+国产替代驱动高增长",
            },
            "电力设备": {
                "tam_yi": 45000, "cagr_3y": 22.0,
                "cr5": 18.0, "cr10": 32.0,
                "trend": "新能源装机+电网投资双轮驱动",
            },
            "医药生物": {
                "tam_yi": 38000, "cagr_3y": 5.0,
                "cr5": 8.0, "cr10": 15.0,
                "trend": "集采压制仿制药，创新药占比提升",
            },
            "汽车": {
                "tam_yi": 35000, "cagr_3y": 15.0,
                "cr5": 35.0, "cr10": 55.0,
                "trend": "新能源渗透率持续提升，出海加速",
            },
            "银行": {
                "tam_yi": 100000, "cagr_3y": 3.0,
                "cr5": 42.0, "cr10": 68.0,
                "trend": "净息差收窄，大行份额提升",
            },
            "计算机": {
                "tam_yi": 28000, "cagr_3y": 12.0,
                "cr5": 10.0, "cr10": 20.0,
                "trend": "信创+AI应用落地驱动增长",
            },
            "国防军工": {
                "tam_yi": 22000, "cagr_3y": 10.0,
                "cr5": 25.0, "cr10": 42.0,
                "trend": "订单驱动，十四五末期加速交付",
            },
            "煤炭": {
                "tam_yi": 15000, "cagr_3y": -2.0,
                "cr5": 28.0, "cr10": 50.0,
                "trend": "双碳约束下产量缓慢下降，高股息支撑估值",
            },
            "基础化工": {
                "tam_yi": 32000, "cagr_3y": 8.0,
                "cr5": 12.0, "cr10": 25.0,
                "trend": "周期波动，新材料方向增速更高",
            },
            "石油石化": {
                "tam_yi": 28000, "cagr_3y": 5.0,
                "cr5": 55.0, "cr10": 78.0,
                "trend": "三桶油主导，炼化环节竞争加剧",
            },
            "钢铁": {
                "tam_yi": 12000, "cagr_3y": -3.0,
                "cr5": 25.0, "cr10": 42.0,
                "trend": "地产拖累需求，制造业用钢增长",
            },
        }
        default = {
            "tam_yi": 20000, "cagr_3y": 5.0,
            "cr5": 15.0, "cr10": 30.0,
            "trend": "数据待补充",
        }
        data = tam_map.get(sector_name, default)
        data["source_tier"] = "T2"
        data["confidence"] = 0.55
        data["note"] = "估算是基于 A 股行业总市值 + 行业经验值，非精确统计"
        return data

    # ------------------------------------------------------------------
    # Step 6: 供应链瓶颈
    # ------------------------------------------------------------------

    def _analyze_supply_chain(self, symbol: str) -> dict:
        """对个股做供应链瓶颈分析。"""
        result = self._supply_chain_mapper.analyze(symbol)
        # 补充上下游
        upstream = self._supply_chain_mapper.find_upstream(symbol)
        downstream = self._supply_chain_mapper.find_downstream(symbol)
        result["upstream_tickers"] = upstream[:10]
        result["downstream_tickers"] = downstream[:10]
        return result

    # ------------------------------------------------------------------
    # Internal scoring (unchanged)
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
