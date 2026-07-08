# -*- coding: utf-8 -*-
"""行业估值框架 — 不同行业匹配不同估值方法。

使用模式:
    framework = SectorValuationFramework()
    result = framework.valuate("食品饮料")
    print(f"主要方法: {result.primary_method.value}, 估值吸引力: {result.valuation_score:.0f}")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.industry.schema import SectorValuation, ValuationMethod

logger = logging.getLogger(__name__)

# 行业 → 估值方法映射
_SECTOR_VALUATION_MAP: dict[str, list[ValuationMethod]] = {
    "食品饮料": [ValuationMethod.DCF, ValuationMethod.PE],
    "银行": [ValuationMethod.PB_ROE, ValuationMethod.PB],
    "医药生物": [ValuationMethod.PEG, ValuationMethod.DCF],
    "电子": [ValuationMethod.PEG, ValuationMethod.PE],
    "电力设备": [ValuationMethod.PEG, ValuationMethod.EV_EBITDA],
    "汽车": [ValuationMethod.PE, ValuationMethod.EV_EBITDA],
    "计算机": [ValuationMethod.PEG, ValuationMethod.PE],
    "家用电器": [ValuationMethod.DCF, ValuationMethod.PE],
    "非银金融": [ValuationMethod.PB, ValuationMethod.PB_ROE],
    "煤炭": [ValuationMethod.PB, ValuationMethod.DIVIDEND],
    "有色金属": [ValuationMethod.PB, ValuationMethod.EV_EBITDA],
    "钢铁": [ValuationMethod.PB, ValuationMethod.DIVIDEND],
    "基础化工": [ValuationMethod.PE, ValuationMethod.EV_EBITDA],
    "房地产": [ValuationMethod.PB, ValuationMethod.DCF],
    "农林牧渔": [ValuationMethod.PE, ValuationMethod.PB],
    "公用事业": [ValuationMethod.DIVIDEND, ValuationMethod.PB],
    "交通运输": [ValuationMethod.DIVIDEND, ValuationMethod.PE],
    "通信": [ValuationMethod.DCF, ValuationMethod.PE],
    "国防军工": [ValuationMethod.PEG, ValuationMethod.PE],
    "建筑装饰": [ValuationMethod.PE, ValuationMethod.PB],
    "建筑材料": [ValuationMethod.PE, ValuationMethod.PB],
    "商贸零售": [ValuationMethod.PE, ValuationMethod.PB],
    "传媒": [ValuationMethod.PEG, ValuationMethod.PE],
    "社会服务": [ValuationMethod.PE, ValuationMethod.PB],
    "环保": [ValuationMethod.PB, ValuationMethod.PE],
    "轻工制造": [ValuationMethod.PE, ValuationMethod.PB],
    "纺织服饰": [ValuationMethod.PE, ValuationMethod.PB],
    "石油石化": [ValuationMethod.PB, ValuationMethod.EV_EBITDA],
    "综合": [ValuationMethod.PB, ValuationMethod.PE],
}

# 行业历史 PE 中枢（百分位参考）
_SECTOR_PE_HISTORY: dict[str, dict] = {
    "食品饮料": {"median": 30, "p25": 22, "p75": 38},
    "银行": {"median": 6, "p25": 5, "p75": 8},
    "医药生物": {"median": 35, "p25": 28, "p75": 45},
    "电子": {"median": 40, "p25": 28, "p75": 55},
    "电力设备": {"median": 35, "p25": 22, "p75": 50},
    "汽车": {"median": 25, "p25": 15, "p75": 35},
    "计算机": {"median": 50, "p25": 35, "p75": 70},
    "家用电器": {"median": 18, "p25": 12, "p75": 25},
    "非银金融": {"median": 15, "p25": 10, "p75": 22},
    "煤炭": {"median": 10, "p25": 6, "p75": 15},
    "有色金属": {"median": 30, "p25": 20, "p75": 45},
    "通信": {"median": 25, "p25": 18, "p75": 35},
    "国防军工": {"median": 55, "p25": 40, "p75": 75},
}


class SectorValuationFramework:
    """行业估值方法框架。

    原则:
      - 周期股 → PB (资产定价)
      - 成长股 → PEG (成长调整)
      - 金融股 → PB-ROE (资产回报)
      - 消费/现金流 → DCF (现金流折现)
      - 公用事业 → 股息率
    """

    def valuate(
        self,
        sector_name: str,
        current_pe: Optional[float] = None,
    ) -> SectorValuation:
        """获取行业估值框架。

        Args:
            sector_name: 申万一级行业名称
            current_pe: 当前行业 PE（TTM），用于分位数计算

        Returns:
            SectorValuation
        """
        methods = _SECTOR_VALUATION_MAP.get(sector_name, [ValuationMethod.PE, ValuationMethod.PB])
        primary = methods[0]
        secondary = methods[1:] if len(methods) > 1 else []

        history = _SECTOR_PE_HISTORY.get(sector_name, {"median": 20, "p25": 12, "p75": 30})

        pe_percentile = 50.0
        valuation_score = 50.0
        fair_low = history["p25"]
        fair_high = history["p75"]

        if current_pe is not None and current_pe > 0:
            # 线性插值估算 PE 分位数
            if current_pe <= history["p25"]:
                pe_percentile = max(1.0, 25 * current_pe / history["p25"])
            elif current_pe >= history["p75"]:
                pe_percentile = min(99.0, 75 + 25 * (current_pe - history["p75"]) / (history["p75"] * 0.5))
            else:
                range_size = history["p75"] - history["p25"]
                if range_size > 0:
                    pe_percentile = 25 + 50 * (current_pe - history["p25"]) / range_size

            # 估值吸引力 = 100 - PE 分位数（低 PE = 高吸引力）
            valuation_score = max(5, min(95, 100 - pe_percentile))

        return SectorValuation(
            sector_name=sector_name,
            primary_method=primary,
            secondary_methods=secondary,
            historical_pe_median=history["median"],
            historical_pe_p25=history["p25"],
            historical_pe_p75=history["p75"],
            current_pe_percentile=pe_percentile,
            fair_value_range=(fair_low, fair_high),
            valuation_score=valuation_score,
        )
