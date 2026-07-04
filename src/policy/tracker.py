# -*- coding: utf-8 -*-
"""政策关键词追踪器。

⚠️ 风险预警工具，非 Alpha 来源。

追踪五大信息源的政策关键词，映射到受益/受损板块。
Phase 2: 基础框架。Phase 3: 接入 last30days-cn 实时监控。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PolicySignal:
    """政策信号。"""
    source: str              # 国务院/发改委/央行/证监会/工信部
    keywords: list[str]      # 检测到的关键词
    timestamp: datetime = field(default_factory=datetime.now)
    affected_sectors: list[str] = field(default_factory=list)  # 受益板块
    affected_sectors_neg: list[str] = field(default_factory=list)  # 受损板块
    impact_level: str = "LOW"  # LOW / MEDIUM / HIGH / CRITICAL


class PolicyTracker:
    """政策关键词追踪器。

    Phase 2: 手动维护 30 条映射规则。
    Phase 3: 接入 last30days-cn 自动抓取。
    """

    # 关键词 → 受益板块映射（手动维护）
    KEYWORD_MAP: dict[str, list[str]] = {
        "降准": ["银行", "地产"],
        "降息": ["地产", "券商", "消费"],
        "LPR下调": ["地产", "银行"],
        "专项债": ["基建", "建材"],
        "新基建": ["5G", "数据中心", "新能源"],
        "碳中和": ["新能源", "光伏", "风电"],
        "碳达峰": ["新能源", "环保"],
        "芯片": ["半导体", "集成电路"],
        "半导体": ["半导体", "电子"],
        "人工智能": ["AI", "信创", "软件"],
        "数字经济": ["信创", "软件", "数据中心"],
        "新能源汽车": ["新能源", "锂电", "汽车零部件"],
        "光伏": ["光伏", "新能源"],
        "储能": ["储能", "锂电"],
        "医药集采": ["医药", "医疗器械"],
        "房地产": ["地产", "建材"],
        "消费刺激": ["消费", "家电", "汽车"],
        "央企改革": ["央企", "军工"],
        "一带一路": ["基建", "港口", "工程机械"],
        "注册制": ["券商", "创投"],
        "退市新规": ["ST板块(负)", "壳资源(负)"],
        "减持新规": ["中小盘(负)"],
        "印花税": ["券商"],
        "国家队增持": ["银行", "蓝筹", "沪深300ETF"],
        "证金": ["银行", "券商"],
        "汇金": ["银行", "保险"],
        "美联储加息": ["外资重仓(负)", "北向流出"],
        "美联储降息": ["外资重仓", "北向流入"],
        "人民币升值": ["航空", "造纸"],
        "人民币贬值": ["出口", "纺织"],
    }

    def scan(self, text: str, source: str = "") -> list[PolicySignal]:
        """扫描文本中的政策关键词。

        Args:
            text: 政策文本
            source: 来源 (国务院/央行/证监会/发改委/工信部)

        Returns:
            检测到的政策信号列表
        """
        signals = []
        found_kw = []
        pos_sectors = []
        neg_sectors = []

        for kw, sectors in self.KEYWORD_MAP.items():
            if kw in text:
                found_kw.append(kw)
                for s in sectors:
                    if "(负)" in s:
                        neg_sectors.append(s.replace("(负)", ""))
                    else:
                        pos_sectors.append(s)

        if found_kw:
            signals.append(PolicySignal(
                source=source,
                keywords=found_kw,
                affected_sectors=list(set(pos_sectors)),
                affected_sectors_neg=list(set(neg_sectors)),
                impact_level=self._assess_impact(found_kw),
            ))

        return signals

    def _assess_impact(self, keywords: list[str]) -> str:
        """评估政策影响级别。"""
        high_impact = {"降准", "降息", "印花税", "国家队增持", "注册制"}
        medium_impact = {"LPR下调", "专项债", "碳中和", "碳达峰"}
        for kw in keywords:
            if kw in high_impact:
                return "HIGH"
        for kw in keywords:
            if kw in medium_impact:
                return "MEDIUM"
        return "LOW"
