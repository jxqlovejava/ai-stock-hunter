# -*- coding: utf-8 -*-
"""行业分类体系 — 申万一级/二级分类 + 行业基准映射。

使用模式:
    classifier = SectorClassifier()
    result = classifier.classify("600519")
    print(result.sw1_name)  # "食品饮料"
"""

from __future__ import annotations

import logging
from typing import Optional

from src.industry.schema import SectorClass, SectorLevel

logger = logging.getLogger(__name__)

# 申万一级行业 → 基准指数映射
SW1_INDEX_MAP: dict[str, str] = {
    "食品饮料": "000807", "银行": "399986", "医药生物": "000808",
    "电子": "399996", "计算机": "399995", "电力设备": "000833",
    "汽车": "000820", "家用电器": "000821", "机械设备": "000812",
    "基础化工": "000811", "有色金属": "000819", "煤炭": "000815",
    "钢铁": "000810", "建筑材料": "000814", "建筑装饰": "000816",
    "房地产": "000006", "农林牧渔": "000809", "纺织服饰": "000832",
    "轻工制造": "000828", "商贸零售": "000824", "社会服务": "000826",
    "交通运输": "000829", "公用事业": "000830", "环保": "000831",
    "国防军工": "000825", "通信": "000818", "传媒": "000823",
    "非银金融": "000813", "石油石化": "000817", "综合": "000833",
}

# 申万一级行业 → 典型二级行业
SW1_TO_SW2: dict[str, list[str]] = {
    "食品饮料": ["白酒", "调味品", "乳制品", "啤酒", "休闲食品"],
    "医药生物": ["化学制药", "生物制品", "医疗器械", "中药", "医药商业"],
    "电子": ["半导体", "消费电子", "电子元器件", "面板", "PCB"],
    "电力设备": ["光伏", "风电", "锂电池", "电网设备", "储能"],
    "汽车": ["乘用车", "商用车", "汽车零部件", "汽车电子"],
    "银行": ["国有大行", "股份行", "城商行", "农商行"],
    "非银金融": ["证券", "保险", "多元金融"],
    "计算机": ["软件", "IT服务", "云计算", "网络安全"],
    "有色金属": ["黄金", "铜", "铝", "锂", "稀土"],
    "基础化工": ["化肥", "农药", "化纤", "塑料", "橡胶"],
}

# 股票代码 → 申万行业映射（常见股票，后续通过数据源动态更新）
_STOCK_SECTOR_CACHE: dict[str, SectorClass] = {}


class SectorClassifier:
    """申万行业分类器。

    支持从数据源动态获取分类 + 本地缓存 fallback。
    """

    def classify(self, symbol: str, name: str = "") -> SectorClass:
        """获取股票的申万行业分类。

        Args:
            symbol: 股票代码
            name: 股票名称（可选，辅助识别）

        Returns:
            SectorClass
        """
        # 1. 查缓存
        if symbol in _STOCK_SECTOR_CACHE:
            return _STOCK_SECTOR_CACHE[symbol]

        # 2. 尝试从数据源获取
        result = self._fetch_from_source(symbol)
        if result:
            _STOCK_SECTOR_CACHE[symbol] = result
            return result

        # 3. 返回未知分类
        return SectorClass(
            sw1_name="未分类",
            sw2_name="未分类",
            description="数据源暂不可用，请稍后重试",
        )

    def classify_batch(self, symbols: list[str]) -> dict[str, SectorClass]:
        """批量分类。"""
        return {s: self.classify(s) for s in symbols}

    def get_sector_stocks(self, sw1_name: str) -> list[str]:
        """获取某个申万一级行业下的代表股票。"""
        # 从已知映射中获取
        stocks = []
        for symbol, sc in _STOCK_SECTOR_CACHE.items():
            if sc.sw1_name == sw1_name:
                stocks.append(symbol)
        return stocks

    def list_sectors(self, level: SectorLevel = SectorLevel.SW1) -> list[str]:
        """列出所有行业分类。"""
        if level == SectorLevel.SW1:
            return sorted(SW1_INDEX_MAP.keys())
        # SW2: 展开所有二级分类
        result = []
        for sw2_list in SW1_TO_SW2.values():
            result.extend(sw2_list)
        return sorted(set(result))

    def get_benchmark_index(self, sw1_name: str) -> str:
        """获取行业基准指数代码。"""
        return SW1_INDEX_MAP.get(sw1_name, "")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_from_source(self, symbol: str) -> Optional[SectorClass]:
        """从数据源获取行业分类。"""

        # 尝试 AKShare
        try:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            quote = agg.get_quote(symbol)
            if quote is not None and hasattr(quote, 'sector') and quote.sector:
                sector_name = str(quote.sector)
                sw1 = self._match_sector(sector_name)
                if sw1:
                    return SectorClass(
                        sw1_name=sw1,
                        benchmark_index=self.get_benchmark_index(sw1),
                    )
        except Exception as exc:
            logger.debug("sector fetch for %s failed: %s", symbol, exc)

        return None

    @staticmethod
    def _match_sector(raw_sector: str) -> Optional[str]:
        """模糊匹配行业名称到申万一级。"""
        for sw1 in SW1_INDEX_MAP:
            if sw1 in raw_sector or raw_sector in sw1:
                return sw1
        # 二级匹配
        for sw1, sw2_list in SW1_TO_SW2.items():
            for sw2 in sw2_list:
                if sw2 in raw_sector:
                    return sw1
        return None
