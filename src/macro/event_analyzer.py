# -*- coding: utf-8 -*-
"""宏观事件因果链分析引擎。

参考 AI Gold Miner:
  - scenarios/analyzer.py: LLM 驱动的因果链推演
  - intelligence/analyzer.py: 规则引擎情感分析 + 操纵话术检测
  - intelligence/forecaster.py: 混合预测 (规则+LLM+交叉验证)

核心流程:
  1. 事件识别 — 规则匹配 + LLM 提取
  2. 因果推演 — 触发条件 → 传导路径 → 历史类比 → 影响估计
  3. 策略生成 — 基于影响估计 + 风险因子 → 策略建议
  4. 个股映射 — 事件影响 → 行业 → 特定股票

A 股传导路径 (7 条):
  北向资金 / 汇率 / 风险偏好 / 出口预期 / 国内政策 / 行业制裁 / 全球流动性
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from .event_models import (
    A_SHARE_CHANNELS,
    ChannelDirection,
    ChannelMagnitude,
    ChannelTimeframe,
    EventAnalysisReport,
    EventCategory,
    EventStrategy,
    HistoricalAnalog,
    ImpactEstimate,
    MacroEvent,
    TransmissionChannel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 规则引擎: 事件关键词 → 分类 + 初步方向
# ---------------------------------------------------------------------------

EVENT_KEYWORDS: dict[EventCategory, list[str]] = {
    EventCategory.MONETARY: [
        "美联储", "FOMC", "加息", "降息", "利率决议", "央行", "缩表", "QE",
        "联邦基金利率", "点阵图", "鲍威尔", "ECB", "欧央行", "日本央行",
    ],
    EventCategory.GEOPOLITICAL: [
        "战争", "冲突", "制裁", "地缘", "台海", "南海", "朝鲜", "中东",
        "乌克兰", "俄罗斯", "北约", "军事",
    ],
    EventCategory.TRADE_POLICY: [
        "关税", "贸易战", "WTO", "出口限制", "进口限制", "301条款",
        "供应链", "脱钩", "去风险",
    ],
    EventCategory.TECH_SANCTION: [
        "芯片", "半导体", "实体清单", "出口管制", "AI芯片", "光刻机",
        "ASML", "台积电", "华为", "中芯国际", "英伟达", "HBM",
    ],
    EventCategory.ECONOMIC_DATA: [
        "CPI", "PPI", "非农", "GDP", "PMI", "社融", "M2",
        "失业率", "消费者信心", "零售销售",
    ],
    EventCategory.FINANCIAL_CRISIS: [
        "暴跌", "熔断", "流动性危机", "信贷危机", "银行", "违约",
        "爆仓", "崩盘",
        # 美股事件
        "美股", "纳斯达克", "标普", "S&P", "道琼斯", "VIX",
        "科技股暴跌", "美股熔断", "中概股",
        "苹果", "微软", "英伟达", "特斯拉", "Meta", "Google",
    ],
    EventCategory.COMMODITY: [
        "原油", "油价", "黄金", "铜", "锂", "稀土", "碳酸锂",
        "OPEC", "大宗商品",
    ],
    EventCategory.REGULATORY: [
        "监管", "约谈", "反垄断", "数据安全", "网络安全", "游戏版号",
        "集采", "医疗反腐", "教培",
    ],
}


# ---------------------------------------------------------------------------
# 事件分析器
# ---------------------------------------------------------------------------


class EventAnalyzer:
    """宏观事件因果链分析引擎。

    用法:
        analyzer = EventAnalyzer()
        report = analyzer.analyze(
            event_description="美联储意外加息50bp，暗示年内还有两次加息",
            category_hint="monetary",
        )
        print(report.summary)
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def analyze(
        self,
        event_description: str,
        *,
        category_hint: str = "",
        title: str = "",
        source: str = "",
        source_url: str = "",
        key_numbers: dict[str, float] | None = None,
        stock_symbol: str = "",
        stock_sector: str = "",
        current_macro: dict[str, Any] | None = None,
    ) -> EventAnalysisReport:
        """分析宏观事件对 A 股的因果链影响。

        Args:
            event_description: 事件描述文本
            category_hint: 事件类型提示
            title: 事件标题
            source: 信息来源
            source_url: 来源 URL
            key_numbers: 关键数值
            stock_symbol: 关注的个股代码
            stock_sector: 个股所属行业
            current_macro: 当前宏观背景

        Returns:
            EventAnalysisReport
        """
        import uuid

        # 1. 事件识别
        category = self._classify(event_description, category_hint)
        event = MacroEvent(
            event_id=uuid.uuid4().hex[:12],
            title=title or self._extract_title(event_description),
            category=category,
            source=source,
            source_url=source_url,
            description=event_description,
            key_numbers=key_numbers or {},
        )

        # 2. 规则引擎: 预判传导路径
        rule_channels = self._rule_based_channels(
            event_description, category, stock_sector,
        )

        # 3. 历史类比
        analogs = self._find_analogs(category, event_description)

        # 4. LLM 深度分析 (如有)
        llm_channels = []
        llm_impact = None
        llm_strategy = None
        if self._llm is not None:
            try:
                llm_result = self._llm_analyze(
                    event_description, category, rule_channels,
                    analogs, stock_symbol, stock_sector,
                    current_macro or {},
                )
                if llm_result:
                    llm_channels = llm_result.get("channels", [])
                    llm_impact = llm_result.get("impact")
                    llm_strategy = llm_result.get("strategy")
            except Exception as e:
                logger.debug("LLM event analysis failed: %s", e)

        # 5. 合并规则+LLM结果 (LLM优先，规则兜底)
        channels = llm_channels if llm_channels else rule_channels
        impact = llm_impact or self._estimate_impact(channels)
        strategy = llm_strategy or self._generate_strategy(impact, channels)

        report = EventAnalysisReport(
            report_id=uuid.uuid4().hex[:12],
            event=event,
            transmission_channels=channels,
            historical_analogs=analogs,
            impact=impact,
            strategy=strategy,
            risk_factors=self._extract_risks(channels, category),
            trigger_conditions=self._extract_triggers(event_description, category),
            stock_symbol=stock_symbol,
            stock_impact_summary=self._build_stock_summary(
                impact, channels, stock_symbol, stock_sector,
            ),
        )
        return report

    # ------------------------------------------------------------------
    # 事件分类
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(text: str, hint: str = "") -> EventCategory:
        """基于关键词规则分类。"""
        scores: dict[EventCategory, int] = {}
        for cat, keywords in EVENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[cat] = score

        if not scores:
            return EventCategory.OTHER

        # 提示词加权
        if hint:
            for cat in EventCategory:
                if cat.value == hint or cat.value in hint:
                    scores[cat] = scores.get(cat, 0) + 2

        return max(scores, key=lambda k: scores[k])

    @staticmethod
    def _extract_title(text: str) -> str:
        """提取事件标题。"""
        # 取第一句或前60字
        first_sentence = re.split(r"[。！？\n]", text)[0].strip()
        return first_sentence[:80]

    # ------------------------------------------------------------------
    # 规则引擎: 传导路径预判
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_based_channels(
        text: str, category: EventCategory, stock_sector: str = "",
    ) -> list[TransmissionChannel]:
        """基于规则预判传导路径。

        不依赖 LLM，快速给出初步判断。
        """
        channels: list[TransmissionChannel] = []

        # 货币政策 → 全球流动性 + 汇率 + 北向
        if category == EventCategory.MONETARY:
            if "美联储" in text or "Fed" in text or "FOMC" in text:
                if "加息" in text or "鹰" in text:
                    channels.append(TransmissionChannel(
                        channel="全球流动性", direction=ChannelDirection.BEARISH,
                        magnitude=ChannelMagnitude.STRONG,
                        description="美联储加息→美元走强→全球流动性收紧→新兴市场资金外流",
                        timeframe=ChannelTimeframe.IMMEDIATE,
                    ))
                    channels.append(TransmissionChannel(
                        channel="北向资金", direction=ChannelDirection.BEARISH,
                        magnitude=ChannelMagnitude.STRONG,
                        description="美债收益率上升→北向资金流出A股",
                        timeframe=ChannelTimeframe.IMMEDIATE,
                    ))
                    channels.append(TransmissionChannel(
                        channel="汇率", direction=ChannelDirection.BEARISH,
                        magnitude=ChannelMagnitude.MODERATE,
                        description="美元走强→人民币贬值压力→A股承压",
                        timeframe=ChannelTimeframe.SHORT_TERM,
                    ))
                elif "降息" in text or "鸽" in text:
                    channels.append(TransmissionChannel(
                        channel="全球流动性", direction=ChannelDirection.BULLISH,
                        magnitude=ChannelMagnitude.STRONG,
                        description="美联储降息→全球流动性宽松→资金回流新兴市场",
                        timeframe=ChannelTimeframe.IMMEDIATE,
                    ))
                    channels.append(TransmissionChannel(
                        channel="北向资金", direction=ChannelDirection.BULLISH,
                        magnitude=ChannelMagnitude.STRONG,
                        description="降息→北向资金加速流入A股",
                        timeframe=ChannelTimeframe.IMMEDIATE,
                    ))

        # 美股事件 → 美股映射 + 风险偏好 + 北向资金
        is_us_market = any(kw in text for kw in [
            "美股", "纳斯达克", "标普", "S&P", "道琼斯", "VIX",
            "科技股暴跌", "美股熔断", "中概股",
            "苹果", "微软", "英伟达", "特斯拉", "Meta", "Google",
        ])
        if is_us_market or category == EventCategory.FINANCIAL_CRISIS:
            # 判断方向
            us_bearish = any(kw in text for kw in [
                "跌", "暴跌", "熔断", "崩盘", "跳水", "重挫",
                "VIX飙升", "恐慌",
            ])
            direction = ChannelDirection.BEARISH if us_bearish else ChannelDirection.BEARISH

            # 美股映射 — 最直接的板块联动
            if any(kw in text for kw in ["纳斯达克", "科技股", "芯片", "AI", "英伟达", "半导体"]):
                channels.append(TransmissionChannel(
                    channel="美股映射", direction=direction,
                    magnitude=ChannelMagnitude.STRONG,
                    description="美股科技股暴跌→A股创业板/科创板/半导体板块次日跟跌",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                    affected_sectors=["半导体", "AI", "消费电子", "创业板"],
                ))
            else:
                channels.append(TransmissionChannel(
                    channel="美股映射", direction=direction,
                    magnitude=ChannelMagnitude.STRONG,
                    description="美股大跌→全球风险资产联动→A股次日低开概率极高",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                ))

            # 风险偏好 — VIX 量化
            if "VIX" in text or "恐慌" in text:
                channels.append(TransmissionChannel(
                    channel="风险偏好", direction=ChannelDirection.BEARISH,
                    magnitude=ChannelMagnitude.STRONG,
                    description="VIX飙升→全球避险情绪急剧升温→风险资产全面承压",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                ))
            else:
                channels.append(TransmissionChannel(
                    channel="风险偏好", direction=direction,
                    magnitude=ChannelMagnitude.MODERATE,
                    description="美股波动→全球风险偏好变化→A股情绪面承压",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                ))

            # 北向资金
            channels.append(TransmissionChannel(
                channel="北向资金", direction=ChannelDirection.BEARISH,
                magnitude=ChannelMagnitude.MODERATE,
                description="美股大跌→外资风险敞口收缩→北向资金次日净流出",
                timeframe=ChannelTimeframe.IMMEDIATE,
            ))

            # 中概股 → 港股 → A股
            if any(kw in text for kw in ["中概股", "中概", "阿里巴巴", "拼多多", "京东", "B站", "港股"]):
                channels.append(TransmissionChannel(
                    channel="汇率", direction=ChannelDirection.BEARISH,
                    magnitude=ChannelMagnitude.MODERATE,
                    description="中概股暴跌→港股跟跌→A股情绪传导（AH溢价联动）",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                ))

        # 地缘政治 → 风险偏好 + 行业制裁
        if category == EventCategory.GEOPOLITICAL:
            channels.append(TransmissionChannel(
                channel="风险偏好", direction=ChannelDirection.BEARISH,
                magnitude=ChannelMagnitude.MODERATE,
                description="地缘冲突→全球避险情绪升温→风险资产承压",
                timeframe=ChannelTimeframe.IMMEDIATE,
            ))

        # 科技制裁 → 行业制裁 (利好国产替代)
        if category == EventCategory.TECH_SANCTION:
            channels.append(TransmissionChannel(
                channel="行业制裁", direction=ChannelDirection.BEARISH,
                magnitude=ChannelMagnitude.STRONG,
                description="科技制裁升级→半导体供应链受阻",
                timeframe=ChannelTimeframe.SHORT_TERM,
                affected_sectors=["半导体", "芯片", "AI"],
            ))
            # 国产替代逻辑 (利好)
            if any(kw in text for kw in ["国产", "自主", "替代"]):
                channels.append(TransmissionChannel(
                    channel="国内政策", direction=ChannelDirection.BULLISH,
                    magnitude=ChannelMagnitude.MODERATE,
                    description="制裁加速国产替代→利好国内半导体设备和材料",
                    timeframe=ChannelTimeframe.MEDIUM_TERM,
                    affected_sectors=["半导体设备", "半导体材料", "EDA"],
                ))

        # 大宗商品 → 行业影响
        if category == EventCategory.COMMODITY:
            if any(kw in text for kw in ["锂", "碳酸锂"]):
                direction = ChannelDirection.BULLISH if any(kw in text for kw in ["涨", "反弹", "回升"]) else ChannelDirection.BEARISH
                channels.append(TransmissionChannel(
                    channel="国内政策", direction=direction,
                    magnitude=ChannelMagnitude.STRONG,
                    description=f"碳酸锂价格变动→直接影响锂矿/锂盐企业盈利",
                    timeframe=ChannelTimeframe.IMMEDIATE,
                    affected_sectors=["锂矿", "锂电池", "新能源"],
                ))

        return channels

    # ------------------------------------------------------------------
    # 历史类比
    # ------------------------------------------------------------------

    @staticmethod
    def _find_analogs(
        category: EventCategory, text: str,
    ) -> list[HistoricalAnalog]:
        """基于事件类型匹配历史类比。"""
        analogs: list[HistoricalAnalog] = []

        analog_db = {
            EventCategory.MONETARY: [
                HistoricalAnalog(
                    event_name="2022年美联储激进加息", period="2022-03~2022-10",
                    market_reaction="上证从3500跌至2900，北向持续流出",
                    shanghai_change_pct=-17.0, similarity_score=0.7,
                    key_parallels=["加息周期", "美元走强", "北向流出"],
                    key_differences=["当时A股估值更高", "当前国内政策更积极"],
                ),
                HistoricalAnalog(
                    event_name="2019年美联储转向降息", period="2019-07~2020-01",
                    market_reaction="全球股市反弹，A股春季躁动",
                    shanghai_change_pct=+8.0, similarity_score=0.5,
                    key_parallels=["降息预期", "流动性改善"],
                    key_differences=["当时无通胀压力"],
                ),
            ],
            EventCategory.GEOPOLITICAL: [
                HistoricalAnalog(
                    event_name="2022年俄乌冲突爆发", period="2022-02",
                    market_reaction="A股短期下跌后快速修复",
                    shanghai_change_pct=-3.0, similarity_score=0.6,
                    key_parallels=["地缘冲击", "避险情绪", "能源价格波动"],
                    key_differences=["冲突地域不同", "对华直接影响程度不同"],
                ),
            ],
            EventCategory.TECH_SANCTION: [
                HistoricalAnalog(
                    event_name="2022年10月美国芯片禁令", period="2022-10",
                    market_reaction="半导体板块先跌后涨，国产替代逻辑发酵",
                    shanghai_change_pct=-2.0, similarity_score=0.8,
                    key_parallels=["芯片出口管制", "半导体设备禁运"],
                    key_differences=["制裁范围可能不同"],
                ),
                HistoricalAnalog(
                    event_name="2023年AI芯片禁令升级", period="2023-10",
                    market_reaction="算力相关股票短期承压，国产GPU概念大涨",
                    shanghai_change_pct=-1.5, similarity_score=0.7,
                    key_parallels=["AI芯片限制", "国产替代加速"],
                    key_differences=[],
                ),
            ],
            EventCategory.COMMODITY: [
                HistoricalAnalog(
                    event_name="2021-2022碳酸锂暴涨", period="2021-07~2022-11",
                    market_reaction="锂矿股暴涨300%后暴跌80%",
                    shanghai_change_pct=0.0, similarity_score=0.6,
                    key_parallels=["锂价周期", "供需错配"],
                    key_differences=["当前处于周期底部区域"],
                ),
            ],
            EventCategory.FINANCIAL_CRISIS: [
                HistoricalAnalog(
                    event_name="2020年3月美股熔断", period="2020-03",
                    market_reaction="美股4次熔断，A股上证从3000跌至2646，随后V型反弹",
                    shanghai_change_pct=-12.0, similarity_score=0.7,
                    key_parallels=["美股暴跌", "流动性恐慌", "全球联动下跌"],
                    key_differences=["2020有美联储无限QE兜底", "当前宏观环境不同"],
                ),
                HistoricalAnalog(
                    event_name="2024年8月全球闪崩", period="2024-08",
                    market_reaction="日经暴跌12%，美股科技股重挫，A股相对抗跌",
                    shanghai_change_pct=-3.0, similarity_score=0.8,
                    key_parallels=["科技股领跌", "VIX飙升", "套息交易平仓"],
                    key_differences=["A股当时估值更低更具韧性"],
                ),
            ],
        }

        # 匹配
        for cat, examples in analog_db.items():
            if cat == category:
                for ex in examples:
                    # 提高匹配度：检查关键词重叠
                    keyword_hits = sum(
                        1 for kw in ex.key_parallels
                        if any(t in text for t in [kw, kw[:2]])
                    )
                    adjusted = min(1.0, ex.similarity_score + keyword_hits * 0.1)
                    analogs.append(HistoricalAnalog(
                        event_name=ex.event_name, period=ex.period,
                        market_reaction=ex.market_reaction,
                        shanghai_change_pct=ex.shanghai_change_pct,
                        similarity_score=round(adjusted, 2),
                        key_parallels=list(ex.key_parallels),
                        key_differences=list(ex.key_differences),
                    ))

        return sorted(analogs, key=lambda a: a.similarity_score, reverse=True)[:3]

    # ------------------------------------------------------------------
    # 影响估计 (规则兜底)
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_impact(
        channels: list[TransmissionChannel],
    ) -> ImpactEstimate:
        """基于传导路径规则估计影响。"""
        if not channels:
            return ImpactEstimate(direction=ChannelDirection.NEUTRAL)

        # 加权汇总
        bullish_score = 0.0
        bearish_score = 0.0
        for ch in channels:
            weight = {"strong": 0.4, "moderate": 0.25, "weak": 0.1}.get(
                ch.magnitude.value, 0.15,
            )
            if ch.direction == ChannelDirection.BULLISH:
                bullish_score += weight * ch.confidence
            elif ch.direction == ChannelDirection.BEARISH:
                bearish_score += weight * ch.confidence

        net = bullish_score - bearish_score
        direction = (
            ChannelDirection.BULLISH if net > 0.1
            else ChannelDirection.BEARISH if net < -0.1
            else ChannelDirection.NEUTRAL
        )

        # 量级估算 (上证)
        base = net * 5  # 每 0.1 净得分 ≈ 0.5% 指数变动
        bullish = base + 3 if base >= 0 else 3
        bearish = base - 3 if base < 0 else -3

        return ImpactEstimate(
            direction=direction,
            base_case_change_pct=round(base, 1),
            bullish_case_change_pct=round(bullish, 1),
            bearish_case_change_pct=round(bearish, 1),
            peak_impact_days=3 if abs(net) > 0.3 else 7,
            confidence=round(min(abs(net) + 0.3, 0.9), 2),
            reasoning=f"基于{len(channels)}条传导路径加权: 看多{bullish_score:.2f} 看空{bearish_score:.2f}",
        )

    # ------------------------------------------------------------------
    # 策略生成
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_strategy(
        impact: ImpactEstimate,
        channels: list[TransmissionChannel],
    ) -> EventStrategy:
        """基于影响估计生成策略建议。"""
        if impact.direction == ChannelDirection.BEARISH:
            if abs(impact.base_case_change_pct) > 5:
                return EventStrategy(
                    overall_position="防御",
                    suggested_action="减仓至50%以下，增配防御板块",
                    hedging_suggestions=["做多国债ETF", "增持高股息红利股"],
                    monitoring_indicators=["北向资金流向", "离岸人民币汇率", "VIX"],
                    position_sizing="总仓位不超过50%，现金为王",
                )
            return EventStrategy(
                overall_position="谨慎",
                suggested_action="降低风险暴露，观望为主",
                hedging_suggestions=["减仓高beta标的"],
                monitoring_indicators=["北向资金流向", "A50期货"],
                position_sizing="总仓位不超过70%",
            )
        elif impact.direction == ChannelDirection.BULLISH:
            return EventStrategy(
                overall_position="积极",
                suggested_action="逢低加仓，关注受益行业",
                monitoring_indicators=["成交量放大", "北向资金持续流入"],
                position_sizing="可适度加仓至80%",
            )
        return EventStrategy(
            overall_position="观望",
            suggested_action="维持现有仓位，等待方向明确",
            monitoring_indicators=["关注事件后续发展"],
        )

    # ------------------------------------------------------------------
    # 风险 & 触发条件
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_risks(
        channels: list[TransmissionChannel], category: EventCategory,
    ) -> list[str]:
        risks = []
        for ch in channels:
            if ch.direction == ChannelDirection.BEARISH and ch.magnitude == ChannelMagnitude.STRONG:
                risks.append(f"主要风险: {ch.channel} — {ch.description}")
        # 二阶效应
        if category == EventCategory.MONETARY:
            risks.append("二阶效应: 若加息引发信用风险事件，影响可能非线性放大")
        elif category == EventCategory.FINANCIAL_CRISIS:
            risks.append("二阶效应: 美股若连续暴跌可能触发全球流动性危机")
            risks.append("关键变量: 美联储是否紧急干预（降息/QE）将决定A股调整深度")
        elif category == EventCategory.GEOPOLITICAL:
            risks.append("二阶效应: 冲突升级可能导致供应链中断，影响远超预期")
        elif category == EventCategory.TECH_SANCTION:
            risks.append("二阶效应: 制裁范围扩大可能波及其他科技领域")
        return risks[:5]

    @staticmethod
    def _extract_triggers(text: str, category: EventCategory) -> list[str]:
        triggers = []
        if category == EventCategory.MONETARY:
            triggers = ["FOMC声明措辞变化", "点阵图调整", "鲍威尔记者会"]
        elif category == EventCategory.GEOPOLITICAL:
            triggers = ["官方声明/表态", "军事部署变化", "国际社会反应"]
        triggers.append("市场反应: 首日量价表现")
        return triggers

    # ------------------------------------------------------------------
    # 个股映射
    # ------------------------------------------------------------------

    @staticmethod
    def _build_stock_summary(
        impact: ImpactEstimate,
        channels: list[TransmissionChannel],
        symbol: str,
        sector: str,
    ) -> str:
        if not symbol:
            return ""
        parts = [f"{symbol}受到以下影响:"]
        for ch in channels:
            if ch.affected_sectors and sector in ch.affected_sectors:
                parts.append(
                    f"  · {ch.channel}({ch.direction.value}): {ch.description}"
                )
        if len(parts) == 1:
            parts.append(f"  · 整体市场影响: {impact.direction.value}")
            parts.append(f"  · 预估超额影响: {impact.stock_adjustment:+.1f}%")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # LLM 深度分析
    # ------------------------------------------------------------------

    def _llm_analyze(
        self,
        description: str,
        category: EventCategory,
        rule_channels: list[TransmissionChannel],
        analogs: list[HistoricalAnalog],
        stock_symbol: str,
        stock_sector: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """LLM 驱动的因果链深度推演。

        参考 AI Gold Miner ScenarioAnalyzer._build_prompt()
        """
        if self._llm is None:
            return None

        # 构建规则分析摘要
        rule_summary = "\n".join(
            f"- {ch.channel}: {ch.direction.value} ({ch.magnitude.value}) — {ch.description}"
            for ch in rule_channels[:5]
        ) if rule_channels else "(规则引擎未命中)"

        analog_summary = "\n".join(
            f"- {a.event_name} ({a.period}): 上证{a.shanghai_change_pct:+.0f}%, 相似度{a.similarity_score:.0%}"
            for a in analogs[:3]
        ) if analogs else "(无匹配)"

        prompt = f"""你是一位A股宏观策略师。请分析以下宏观事件对A股市场的因果链影响。

## 当前事件
分类: {category.value}
描述: {description}

## 规则引擎预判
{rule_summary}

## 历史类比
{analog_summary}

{'## 关注个股' if stock_symbol else ''}
{f'{stock_symbol} ({stock_sector})' if stock_symbol else ''}

## 分析要求
请按JSON格式输出（不要其他文字）:

```json
{{
  "channels": [
    {{
      "channel": "{'/'.join(A_SHARE_CHANNELS)}",
      "direction": "bullish/bearish/neutral",
      "magnitude": "strong/moderate/weak",
      "description": "传导逻辑，80字以内",
      "timeframe": "immediate/short_term/medium_term/long_term",
      "affected_sectors": ["行业1"],
      "confidence": 0.0-1.0
    }}
  ],
  "impact": {{
    "direction": "bullish/bearish/neutral",
    "base_case_change_pct": 数字,
    "bullish_case_change_pct": 数字,
    "bearish_case_change_pct": 数字,
    "peak_impact_days": 整数,
    "confidence": 0.0-1.0,
    "reasoning": "核心推理，150字以内",
    "stock_adjustment": 数字(相对大盘的超额影响),
    "stock_adjustment_reason": "个股层面调整理由"
  }},
  "strategy": {{
    "overall_position": "激进/谨慎/防御/观望",
    "suggested_action": "具体操作建议，100字以内",
    "hedging_suggestions": ["对冲建议"],
    "monitoring_indicators": ["先行指标"],
    "position_sizing": "仓位建议"
  }}
}}
```

重要原则:
1. 区分直接影响与二阶效应
2. 考虑时间动态演化（初期→中期→长期）
3. 考虑政策响应（中国央行/财政如何应对？）
4. 传导路径需有经济学逻辑支撑
5. 数字要有逻辑依据，参考历史类比的量级"""

        try:
            messages = [{"role": "user", "content": prompt}]
            raw = self._llm.chat(messages, max_tokens=4096, temperature=0.3)
            if not raw:
                return None

            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            json_str = json_match.group(1).strip() if json_match else raw.strip()
            result = json.loads(json_str)

            # 解析 channels
            parsed_channels = []
            for c in result.get("channels", []):
                ch = c.get("channel", "")
                if ch not in A_SHARE_CHANNELS:
                    continue
                parsed_channels.append(TransmissionChannel(
                    channel=ch,
                    direction=ChannelDirection(c.get("direction", "neutral")),
                    magnitude=ChannelMagnitude(c.get("magnitude", "moderate")),
                    description=c.get("description", ""),
                    timeframe=ChannelTimeframe(c.get("timeframe", "short_term")),
                    affected_sectors=c.get("affected_sectors", []),
                    confidence=float(c.get("confidence", 0.7)),
                ))

            # 解析 impact
            imp_raw = result.get("impact", {})
            impact = ImpactEstimate(
                direction=ChannelDirection(imp_raw.get("direction", "neutral")),
                base_case_change_pct=float(imp_raw.get("base_case_change_pct", 0)),
                bullish_case_change_pct=float(imp_raw.get("bullish_case_change_pct", 0)),
                bearish_case_change_pct=float(imp_raw.get("bearish_case_change_pct", 0)),
                peak_impact_days=int(imp_raw.get("peak_impact_days", 3)),
                confidence=float(imp_raw.get("confidence", 0.5)),
                reasoning=imp_raw.get("reasoning", ""),
                stock_adjustment=float(imp_raw.get("stock_adjustment", 0)),
                stock_adjustment_reason=imp_raw.get("stock_adjustment_reason", ""),
            )

            # 解析 strategy
            strat_raw = result.get("strategy", {})
            strategy = EventStrategy(
                overall_position=strat_raw.get("overall_position", "观望"),
                suggested_action=strat_raw.get("suggested_action", ""),
                hedging_suggestions=strat_raw.get("hedging_suggestions", []),
                monitoring_indicators=strat_raw.get("monitoring_indicators", []),
                position_sizing=strat_raw.get("position_sizing", ""),
            )

            return {"channels": parsed_channels, "impact": impact, "strategy": strategy}

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug("LLM event analysis parse error: %s", e)
            return None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def analyze_event(
    description: str,
    *,
    category: str = "",
    title: str = "",
    source: str = "",
    stock_symbol: str = "",
    stock_sector: str = "",
    llm_client=None,
) -> EventAnalysisReport:
    """快速分析一个宏观事件。

    用法:
        report = analyze_event(
            "美联储意外加息50bp，暗示年内还有两次加息",
            category="monetary",
            stock_symbol="002460",
            stock_sector="锂矿",
        )
    """
    analyzer = EventAnalyzer(llm_client=llm_client)
    return analyzer.analyze(
        event_description=description,
        category_hint=category,
        title=title,
        source=source,
        stock_symbol=stock_symbol,
        stock_sector=stock_sector,
    )
