# -*- coding: utf-8 -*-
"""行业因子自动提取与分类引擎。

从催化剂/全球供需/新闻/行情数据中自动提取影响因子，
按 horizon (短期/中长期) × category (情绪/基本面) 双层分类，
直接输出 print_sector_impact_summary() 所需的数据结构。

Phase 1: 因子提取 — 从各数据源提取结构化 Factor
Phase 2: 分类规则 — 规则驱动 horizon + category 判定
Phase 3: 组装输出 — 生成 stock_impact dict
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Factor DTO
# ---------------------------------------------------------------------------

@dataclass
class Factor:
    """单个影响因子。"""
    source: str                  # 因子来源 (e.g. "碳酸锂期货", "天齐连续跌停")
    value: str = ""              # 当前值 (e.g. "-5%", "两日跌停")
    direction: str = "negative"  # positive / negative / neutral
    category: str = "基本面"     # 情绪 / 基本面
    subcategory: str = ""       # 价格信号 / 产能变化 / 板块传染 / 政策变动 / ...
    horizon: str = "中长期"      # 短期 / 中长期
    reason: str = ""             # 一句解释
    confidence: float = 0.70     # 0-1
    source_tier: str = "T2"      # T0-T3
    persistence: str = ""        # 会消退 / 不会自动消失


# ---------------------------------------------------------------------------
# Classification Rules Engine
# ---------------------------------------------------------------------------

class FactorClassifier:
    """规则驱动的因子分类器。

    判定逻辑：
      horizon: 新闻事件/单日异动/考核周期 → 短期
               产能变化/政策/技术路线/成本位移 → 中长期
      category: 恐慌/传染/事件冲击 → 情绪
                供给/需求/成本/政策结构 → 基本面
      persistence: 短期情绪 → "会消退"
                   中长期基本面 → "不会自动消失"
    """

    # 关键词 → (category, horizon, persistence)
    KEYWORD_RULES: dict[str, tuple[str, str, str]] = {
        # ── 基本面/中长期 ──
        "复产": ("基本面", "中长期", "不会自动消失"),
        "产能": ("基本面", "中长期", "不会自动消失"),
        "扩产": ("基本面", "中长期", "不会自动消失"),
        "满产": ("基本面", "中长期", "不会自动消失"),
        "供给": ("基本面", "中长期", "不会自动消失"),
        "需求": ("基本面", "中长期", "不会自动消失"),
        "成本": ("基本面", "中长期", "不会自动消失"),
        "成本曲线": ("基本面", "中长期", "不会自动消失"),
        "产能过剩": ("基本面", "中长期", "不会自动消失"),
        "矿山": ("基本面", "中长期", "不会自动消失"),
        "盐湖": ("基本面", "中长期", "不会自动消失"),
        "锂矿": ("基本面", "中长期", "不会自动消失"),
        "矿企": ("基本面", "中长期", "不会自动消失"),
        "出口配额": ("基本面", "中长期", "不会自动消失"),
        "期货": ("基本面", "中长期", "不会自动消失"),
        "趋势向下": ("基本面", "中长期", "不会自动消失"),
        "趋势向上": ("基本面", "中长期", "不会自动消失"),
        "价格下行": ("基本面", "中长期", "不会自动消失"),
        "价格上行": ("基本面", "中长期", "不会自动消失"),
        "增产": ("基本面", "中长期", "不会自动消失"),
        "减产": ("基本面", "中长期", "不会自动消失"),
        "政策": ("基本面", "中长期", "不会自动消失"),
        "监管": ("基本面", "中长期", "不会自动消失"),
        "国储": ("基本面", "中长期", "不会自动消失"),
        "收储": ("基本面", "中长期", "不会自动消失"),
        "放储": ("基本面", "中长期", "不会自动消失"),
        "技术路线": ("基本面", "中长期", "不会自动消失"),
        "固态电池": ("基本面", "中长期", "不会自动消失"),
        "钠电池": ("基本面", "中长期", "不会自动消失"),
        "替代": ("基本面", "中长期", "不会自动消失"),
        "利润": ("基本面", "中长期", "不会自动消失"),
        "营收": ("基本面", "中长期", "不会自动消失"),
        "主业": ("基本面", "中长期", "不会自动消失"),
        "增速放缓": ("基本面", "中长期", "不会自动消失"),
        "国资": ("基本面", "中长期", "不会自动消失"),
        "国有化": ("基本面", "中长期", "不会自动消失"),
        "制裁": ("基本面", "中长期", "不会自动消失"),
        "特许权": ("基本面", "中长期", "不会自动消失"),
        "FEOC": ("基本面", "中长期", "不会自动消失"),
        "IRA": ("基本面", "中长期", "不会自动消失"),
        "限制": ("基本面", "中长期", "不会自动消失"),

        # ── 情绪/短期 ──
        "恐慌": ("情绪", "短期", "会消退"),
        "冲突": ("情绪", "短期", "会消退"),
        "战争": ("情绪", "短期", "会消退"),
        "地缘": ("情绪", "短期", "会消退"),
        "美伊": ("情绪", "短期", "会消退"),
        "考核": ("情绪", "短期", "会消退"),
        "公募": ("情绪", "短期", "会消退"),
        "基金": ("情绪", "短期", "会消退"),
        "赎回": ("情绪", "短期", "会消退"),
        "兑现": ("情绪", "短期", "会消退"),
        "结算": ("情绪", "短期", "会消退"),
        "美元": ("情绪", "短期", "会消退"),
        "汇率": ("情绪", "短期", "会消退"),
        "央行": ("情绪", "短期", "会消退"),
        "加息": ("情绪", "短期", "会消退"),
        "降息": ("情绪", "短期", "会消退"),
        "利率": ("情绪", "短期", "会消退"),
        "跌停": ("情绪", "短期", "会消退"),
        "涨停": ("情绪", "短期", "会消退"),
        "连板": ("情绪", "短期", "会消退"),
        "板块联动": ("情绪", "短期", "会消退"),
        "情绪": ("情绪", "短期", "会消退"),
        "传染": ("情绪", "短期", "会消退"),
        "抛售": ("情绪", "短期", "会消退"),
        "踩踏": ("情绪", "短期", "会消退"),
        "外资": ("情绪", "短期", "会消退"),
        "北向": ("情绪", "短期", "会消退"),
        "流出": ("情绪", "短期", "会消退"),
        "流入": ("情绪", "短期", "会消退"),
        "做空": ("情绪", "短期", "会消退"),
        "爆仓": ("情绪", "短期", "会消退"),
        "传闻": ("情绪", "短期", "会消退"),
        "谣言": ("情绪", "短期", "会消退"),
        "辟谣": ("情绪", "短期", "会消退"),

        # ── 中性/需上下文判断 ──
        "数据": ("基本面", "中长期", "不会自动消失"),
        "报告": ("基本面", "中长期", "不会自动消失"),
        "财报": ("基本面", "中长期", "不会自动消失"),
        "Q1": ("基本面", "中长期", "不会自动消失"),
        "Q2": ("基本面", "中长期", "不会自动消失"),
        "H1": ("基本面", "中长期", "不会自动消失"),
        "业绩": ("基本面", "中长期", "不会自动消失"),
    }

    @classmethod
    def classify(cls, text: str) -> tuple[str, str, str]:
        """根据文本关键词判定 category, horizon, persistence。

        Returns:
            (category, horizon, persistence)
        """
        for keyword, (cat, hor, per) in cls.KEYWORD_RULES.items():
            if keyword in text:
                return cat, hor, per
        # 默认：基本面/中长期
        return ("基本面", "中长期", "不会自动消失")

    @classmethod
    def infer_direction(cls, text: str) -> str:
        """从文本推断方向 (neutral 作为无信号默认)。"""
        negative_kw = ["跌", "跌停", "下行", "下降", "走弱", "过剩", "压力",
                       "放缓", "减少", "亏损", "风险", "冲突", "恐慌", "抛售",
                       "制裁", "限制", "产能过剩", "破位", "萎缩", "退出"]
        positive_kw = ["涨", "涨停", "上行", "上升", "走强", "突破", "改善",
                       "复苏", "增长", "盈利", "利好", "企稳", "反弹", "扩产",
                       "需求", "支持", "加码", "战略", "驱动", "加速"]

        neg_score = sum(1 for kw in negative_kw if kw in text)
        pos_score = sum(1 for kw in positive_kw if kw in text)

        if neg_score > pos_score:
            return "negative"
        elif pos_score > neg_score:
            return "positive"
        return "neutral"


# ---------------------------------------------------------------------------
# Factor Extractor
# ---------------------------------------------------------------------------


class FactorExtractor:
    """行业因子自动提取器。

    从多个数据源提取结构化因子:
      - 催化剂 + 政策 (sector_research Step 5)
      - 全球供需 (sector_research Step 7)
      - 供应链瓶颈 (sector_research Step 6)
      - 实时行情 + 板块数据
      - 新闻快讯

    用法:
        extractor = FactorExtractor()
        impact = extractor.analyze(
            sector_name="有色金属",
            stock_name="赣锋锂业",
            sector_data=sector_research_dict,
            news=news_list,
            market_data={"期货": {...}, "板块": {...}, "龙头": {...}},
        )
        # impact 可直接喂给 print_sector_impact_summary()
    """

    def analyze(
        self,
        sector_name: str = "",
        stock_name: str = "",
        sector_data: dict | None = None,
        news: list[str] | None = None,
        market_data: dict | None = None,
    ) -> dict:
        """主入口：提取所有因子并组装 stock_impact dict。

        Args:
            sector_name: 申万一级行业
            stock_name: 个股名称
            sector_data: sector_research dict (含 catalysts/global_commodity/supply_chain)
            news: 新闻标题列表
            market_data: {"期货": {...}, "板块": {...}, "龙头": [...]}

        Returns:
            {"stock": stock_name,
             "short_term": [Factor...],
             "long_term": [Factor...],
             "summary": "..."}
        """
        all_factors: list[Factor] = []

        # 1. 从催化剂提取
        if sector_data:
            all_factors.extend(self._from_catalysts(sector_data))

        # 2. 从全球供需提取
        if sector_data:
            all_factors.extend(self._from_global_commodity(sector_data))

        # 3. 从供应链瓶颈提取
        if sector_data:
            all_factors.extend(self._from_supply_chain(sector_data, stock_name))

        # 4. 从实时行情提取
        if market_data:
            all_factors.extend(self._from_market_data(market_data, stock_name))

        # 5. 从新闻提取
        if news:
            all_factors.extend(self._from_news(news))

        # 去重 — 同 source 保留置信度最高的
        seen: dict[str, Factor] = {}
        for f in all_factors:
            key = f.source
            if key not in seen or f.confidence > seen[key].confidence:
                seen[key] = f

        factors = list(seen.values())

        # 按 horizon 分组
        short_term = [f for f in factors if f.horizon == "短期"]
        long_term = [f for f in factors if f.horizon == "中长期"]

        # 生成综述
        summary = self._generate_summary(short_term, long_term, stock_name, sector_name)

        return {
            "stock": stock_name,
            "short_term": [
                {"factor": f"{f.source}: {f.value}" if f.value else f.source,
                 "reason": f.reason,
                 "impact": f.direction}
                for f in short_term
            ],
            "long_term": [
                {"factor": f"{f.source}: {f.value}" if f.value else f.source,
                 "reason": f.reason,
                 "impact": f.direction}
                for f in long_term
            ],
            "summary": summary,
            "_raw_factors": factors,  # 调试用
        }

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def _from_catalysts(self, sector_data: dict) -> list[Factor]:
        """从催化剂/政策数据提取因子。"""
        factors: list[Factor] = []
        catalysts = sector_data.get("catalysts", [])
        policy_notes = sector_data.get("policy_notes", [])
        policy_impact = sector_data.get("policy_impact", 0)

        for c in catalysts:
            cat, hor, per = FactorClassifier.classify(str(c))
            direction = FactorClassifier.infer_direction(str(c))
            # 跳过中性因子 — 无方向不输入影响综述
            if direction == "neutral":
                continue
            factors.append(Factor(
                source=f"{c}",
                value="",
                direction=direction,
                category=cat,
                subcategory="产业趋势" if cat == "基本面" else "市场预期",
                horizon=hor,
                persistence=per,
                reason=f"行业催化剂: {c}",
                confidence=0.55,
                source_tier="T2",
            ))

        if policy_impact != 0 and policy_notes:
            direction = "positive" if policy_impact > 0 else "negative"
            for pn in policy_notes[:2]:
                factors.append(Factor(
                    source=f"政策: {pn}",
                    direction=direction,
                    category="基本面",
                    subcategory="政策变动",
                    horizon="中长期",
                    persistence="不会自动消失",
                    reason=f"政策影响 {policy_impact:+d}",
                    confidence=0.65,
                    source_tier="T2",
                ))

        return factors

    def _from_global_commodity(self, sector_data: dict) -> list[Factor]:
        """从全球供需数据提取因子。"""
        factors: list[Factor] = []
        gc = sector_data.get("global_commodity", {})
        if not gc or not gc.get("enabled"):
            return factors

        detailed = gc.get("detailed_commodities", {})
        for sub_name, sub_data in detailed.items():
            display = sub_data.get("display_name", sub_name)

            # 海外产能 → 供给因子
            assets = sub_data.get("overseas_assets", [])
            for asset in assets[:4]:
                expansion = asset.get("expansion", "")
                cost = asset.get("cost_position", "")
                name = asset.get("name", "")
                country = asset.get("country", "")
                capacity = asset.get("capacity", "")

                # 扩产中的产能 → 供给增量风险
                if "扩产" in expansion or "规划" in expansion or "爬坡" in expansion:
                    factors.append(Factor(
                        source=f"{name} ({country})",
                        value=f"{capacity}, {expansion}",
                        direction="negative",
                        category="基本面",
                        subcategory="供给增量",
                        horizon="中长期",
                        persistence="不会自动消失",
                        reason=f"海外产能扩张: {expansion}",
                        confidence=0.65,
                        source_tier="T2",
                    ))
                # Tier 3 高成本产能 → 价格支撑
                elif "Tier 3" in cost or "高成本" in cost:
                    factors.append(Factor(
                        source=f"{name} 高成本产能 ({country})",
                        value=cost,
                        direction="positive",
                        category="基本面",
                        subcategory="成本支撑",
                        horizon="中长期",
                        persistence="不会自动消失",
                        reason="高成本产能构成价格底部支撑",
                        confidence=0.55,
                        source_tier="T2",
                    ))

            # 地缘政治风险
            risks = sub_data.get("geopolitical_risks", [])
            for risk in risks:
                if risk.get("level") == "HIGH":
                    affected = risk.get("affected", "")
                    factors.append(Factor(
                        source=f"地缘: {risk.get('risk', '')}",
                        value=f"HIGH, 影响{affected}" if affected else "HIGH",
                        direction="negative",
                        category="基本面",
                        subcategory="地缘风险",
                        horizon="中长期",
                        persistence="不会自动消失",
                        reason=risk.get("detail", "")[:80],
                        confidence=0.60,
                        source_tier="T2",
                    ))

        return factors

    def _from_supply_chain(self, sector_data: dict, stock_name: str) -> list[Factor]:
        """从供应链瓶颈数据提取因子。"""
        factors: list[Factor] = []
        sc = sector_data.get("supply_chain", {})
        if not sc or not sc.get("in_chain"):
            return factors

        bottleneck = sc.get("bottleneck_score", 0)
        node_name = sc.get("node_name", "")

        if bottleneck >= 70:
            factors.append(Factor(
                source=f"{stock_name}在{node_name}节点",
                value=f"瓶颈分{bottleneck}/100",
                direction="positive",
                category="基本面",
                subcategory="竞争优势",
                horizon="中长期",
                persistence="不会自动消失",
                reason="掌握上游瓶颈，价格传导能力强",
                confidence=0.70,
                source_tier="T2",
            ))
        elif bottleneck <= 40:
            factors.append(Factor(
                source=f"{stock_name}在{node_name}节点",
                value=f"瓶颈分{bottleneck}/100",
                direction="negative",
                category="基本面",
                subcategory="竞争劣势",
                horizon="中长期",
                persistence="不会自动消失",
                reason="非瓶颈节点，缺乏议价权",
                confidence=0.65,
                source_tier="T2",
            ))

        # 成本传导
        pass_through = sc.get("cost_pass_through", 0.5)
        if pass_through >= 0.7:
            factors.append(Factor(
                source=f"{stock_name}成本传导系数 {pass_through:.1f}",
                direction="positive",
                category="基本面",
                subcategory="成本传导",
                horizon="中长期",
                persistence="不会自动消失",
                reason="上游涨价可有效传导至下游",
                confidence=0.60,
                source_tier="T2",
            ))

        return factors

    def _from_market_data(self, market_data: dict, stock_name: str) -> list[Factor]:
        """从实时行情数据提取因子。"""
        factors: list[Factor] = []

        # 期货数据
        futures = market_data.get("期货", {})
        if futures:
            price = futures.get("price")
            change_pct = futures.get("change_pct")
            if change_pct is not None and abs(float(change_pct)) > 3.0:
                direction = "negative" if float(change_pct) < 0 else "positive"
                factors.append(Factor(
                    source=f"{futures.get('name', '期货')}",
                    value=f"日内{change_pct:+.1f}%",
                    direction=direction,
                    category="基本面",
                    subcategory="价格信号",
                    horizon="中长期",
                    persistence="不会自动消失",
                    reason=f"期货 {'破位下行' if direction == 'negative' else '大幅反弹'}，趋势信号",
                    confidence=0.75,
                    source_tier="T1",
                ))

        # 板块数据
        sector_market = market_data.get("板块", {})
        if sector_market:
            sector_pct = sector_market.get("change_pct", 0)
            if isinstance(sector_pct, (int, float)) and abs(sector_pct) > 5.0:
                factors.append(Factor(
                    source=f"{sector_market.get('name', '板块')}板块",
                    value=f"{sector_pct:+.1f}%",
                    direction="negative" if sector_pct < 0 else "positive",
                    category="情绪",
                    subcategory="板块联动",
                    horizon="短期",
                    persistence="会消退",
                    reason=f"板块整体{'暴跌' if sector_pct < 0 else '暴涨'}，情绪驱动",
                    confidence=0.70,
                    source_tier="T1",
                ))

        # 同业龙头对标
        peers = market_data.get("龙头", [])
        for peer in peers:
            pct = peer.get("change_pct", 0)
            name = peer.get("name", "")
            if isinstance(pct, (int, float)) and abs(pct) > 8.0:
                factors.append(Factor(
                    source=f"{name}异动",
                    value=f"{pct:+.1f}%",
                    direction="negative" if pct < 0 else "positive",
                    category="情绪",
                    subcategory="板块传染",
                    horizon="短期",
                    persistence="会消退",
                    reason=f"同业{'暴跌' if pct < 0 else '暴涨'}，情绪传染",
                    confidence=0.65,
                    source_tier="T1",
                ))

        return factors

    def _from_news(self, news: list[str]) -> list[Factor]:
        """从新闻标题列表提取因子。"""
        factors: list[Factor] = []
        if not news:
            return factors

        for title in news:
            if not isinstance(title, str) or len(title) < 6:
                continue

            cat, hor, per = FactorClassifier.classify(title)
            direction = FactorClassifier.infer_direction(title)

            # 只保留有明确方向的因子
            if direction == "neutral":
                continue

            # 短标题直接作为因子
            source = title[:60]
            factors.append(Factor(
                source=source,
                direction=direction,
                category=cat,
                subcategory="新闻驱动" if cat == "情绪" else "信息更新",
                horizon=hor,
                persistence=per,
                reason=title[:100],
                confidence=0.55,
                source_tier="T2",
            ))

        return factors

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_summary(
        short_term: list[Factor],
        long_term: list[Factor],
        stock_name: str,
        sector_name: str,
    ) -> str:
        """生成一句话综述。"""
        if not short_term and not long_term:
            return f"{stock_name}暂无明显行业因子驱动，走势由个股逻辑主导。"

        parts = []
        short_neg = [f for f in short_term if f.direction == "negative"]
        long_neg = [f for f in long_term if f.direction == "negative"]
        long_pos = [f for f in long_term if f.direction == "positive"]

        if short_neg:
            parts.append(f"{len(short_neg)}个短期情绪利空(会消退)")
        if long_neg:
            parts.append(f"{len(long_neg)}个中长期基本面利空")
        if long_pos:
            parts.append(f"{len(long_pos)}个中长期基本面利好")

        if long_neg and not long_pos:
            return (f"情绪面利空会过，基本面供给过剩才是真正的压力——"
                    f"在核心变量企稳前，{stock_name}主业利润承压。")
        elif long_pos and not long_neg:
            return (f"基本面改善趋势明确({', '.join(f.source[:25] for f in long_pos[:2])})，"
                    f"短期情绪波动不改变中长期价值。")
        elif long_neg and long_pos:
            return (f"基本面多空交织——利好: {'/'.join(f.source[:25] for f in long_pos[:2])}；"
                    f"利空: {'/'.join(f.source[:25] for f in long_neg[:2])}。"
                    f"关键看哪个因子先兑现。")
        return f"行业因子驱动中性，{stock_name}走势更多取决于个股逻辑。"
