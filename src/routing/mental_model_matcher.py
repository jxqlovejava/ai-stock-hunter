# -*- coding: utf-8 -*-
"""Munger 232 思维模型匹配器。

根据诊断报告/组合/情绪等上下文，从 232 个模型中挑选最相关的 3-5 个。
匹配规则完全确定性，不调用 LLM。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class _MatchedModel:
    slug: str
    name_cn: str
    discipline: str
    reason_for_match: str
    relevance: int = 0


class MentalModelMatcher:
    """Munger 思维模型匹配器。"""

    _JSON_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "munger_232_models.json",
    )

    def __init__(self):
        self._models = self._load_models()

    @classmethod
    def _load_models(cls) -> list[dict]:
        try:
            with open(cls._JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("models", [])
        except Exception:
            return []

    def match_models(
        self,
        symbol: str,
        name: str,
        sector: str,
        report: Optional[object] = None,
    ) -> list[dict]:
        """返回与当前上下文最相关的 3-5 个 Munger 模型。"""
        if not self._models:
            return []

        # 从 report 提取关键分数，用于生成股票特定分析
        _scores = {}
        if report is not None:
            for attr in ("macro_score", "value_score", "quality_score", "momentum_score",
                         "earnings_revision_score", "valuation_score", "cycle_score",
                         "executive_score", "manipulation_risk_score"):
                v = getattr(report, attr, None)
                if v is not None:
                    _scores[attr] = float(v)
            # 情绪
            _scores["sentiment"] = getattr(report, "sentiment_signal", "NEUTRAL") or "NEUTRAL"

        candidates: list[_MatchedModel] = []
        portfolio = self._portfolio(report)
        sentiment = self._sentiment(report)
        has_exec_risks = self._has_exec_risks(report)
        has_red_flags = self._has_red_flags(report)
        has_competition = self._has_competition(sector, report)
        regime_crowded = self._regime_crowded(report)

        for m in self._models:
            slug = m.get("slug", "")
            name_cn = m.get("name_cn", "")
            discipline = m.get("discipline", "")
            desc = (m.get("description", "") + " " + m.get("name_en", "")).lower()

            matched, reason, relevance = self._score_model(
                slug=slug,
                name_cn=name_cn,
                discipline=discipline,
                desc=desc,
                portfolio=portfolio,
                sentiment=sentiment,
                has_exec_risks=has_exec_risks,
                has_red_flags=has_red_flags,
                has_competition=has_competition,
                regime_crowded=regime_crowded,
            )
            if matched:
                candidates.append(_MatchedModel(
                    slug=slug,
                    name_cn=name_cn,
                    discipline=discipline,
                    reason_for_match=reason,
                    relevance=relevance,
                ))

        # 按相关度降序，返回前 15（含完整描述 + 股票特定应用）
        candidates.sort(key=lambda x: x.relevance, reverse=True)
        top = candidates[:15]
        result = []
        for m in top:
            # 从原始模型数据中获取完整描述
            desc = ""
            for raw in self._models:
                if raw.get("slug") == m.slug:
                    desc = raw.get("description", "")
                    break
            # 生成股票特定应用分析
            app = self._stock_application(m.slug, _scores)
            result.append({
                "slug": m.slug,
                "name_cn": m.name_cn,
                "discipline": m.discipline,
                "reason_for_match": m.reason_for_match,
                "description": desc,
                "relevance": m.relevance,
                "application_to_stock": app,
            })
        return result

    @staticmethod
    def _stock_application(slug: str, scores: dict) -> str:
        """基于股票实际分数，生成该思维模型对当前股票的具体应用洞察。"""
        momentum = scores.get("momentum_score", 50)
        quality = scores.get("quality_score", 50)
        earnings = scores.get("earnings_revision_score", 50)
        macro = scores.get("macro_score", 50)
        cycle = scores.get("cycle_score", 50)
        value = scores.get("value_score", 50)
        executive = scores.get("executive_score", 50)
        manip_risk = scores.get("manipulation_risk_score", 0)
        sentiment = scores.get("sentiment", "NEUTRAL")

        # 损失厌恶相关模型
        if slug in ("loss-aversion", "deprival-superreaction", "sunk-cost"):
            if momentum < 35:
                return (
                    f"当前动量因子仅{momentum:.0f}分，持仓可能已浮亏。"
                    "切忌因厌恶损失而拒绝止损——承认错误是投资中最被低估的能力"
                )
            return "警惕持有浮亏仓位时产生的'回本就卖'心理——这往往导致卖在最低点"

        # 社会认同 / 从众
        if slug in ("social-proof", "herding", "authority-misinfluence"):
            if sentiment in ("GREED", "EXTREME"):
                return f"当前市场情绪{sentiment}，从众风险极高——多数人在极端情绪中的判断往往错误"
            return "反思: 你的持仓决策是基于独立研究还是市场热度？"

        # 确认偏误
        if slug in ("confirmation-bias", "narrative-fallacy"):
            if earnings > 70 and momentum < 35:
                return (
                    f"盈利修正{earnings:.0f}分但动量仅{momentum:.0f}分——"
                    "你可能在选择性接受看多信息而忽略价格发出的警告信号"
                )
            return "主动寻找与你持仓逻辑相反的证据，列出3个可能推翻你判断的风险因素"

        # 激励机制
        if slug in ("incentives", "agency-problem"):
            if executive < 40:
                return (
                    f"高管因子{executive:.0f}分偏低——管理层激励可能与股东利益不一致，"
                    "关注高管薪酬结构是否与长期价值创造挂钩"
                )
            return "关注高管薪酬是否与股东回报绑定，而非仅与规模/收入挂钩"

        # 网络效应 / 竞争优势
        if slug in ("network-effect", "competitive-advantage", "moat"):
            if quality < 40:
                return (
                    f"质量因子{quality:.0f}分偏弱——护城河可能不如想象中坚固，"
                    "竞争格局恶化是长期持有最大的敌人"
                )
            return "定期审视护城河的宽度变化——没有永远的竞争优势"

        # 供需
        if slug in ("supply-demand", "scarcity"):
            if cycle > 70:
                return f"周期适配{cycle:.0f}分——当前处于供需有利阶段，但需警惕产能过剩拐点"
            return "分析该行业供给端新增产能节奏，供给过剩是周期股最大的风险"

        # 边际分析
        if slug in ("marginal-analysis", "diminishing-returns"):
            return f"增量视角: 关注ROE趋势而非绝对水平——边际改善比静态数字更有信息量"

        # 机会成本
        if slug in ("opportunity-cost", "capital-allocation"):
            return "空仓视角自检: 如果现在持有现金，还会买这支股票吗？如果不会，为什么不卖？"

        # 逆向思维
        if slug in ("inversion", "avoid-stupidity"):
            if earnings > 80:
                return (
                    "逆向自问: 这个投资最可能的失败原因是什么？"
                    "即使盈利修正很强，也要想清楚什么情况下会亏钱"
                )
            return "先想清楚'为什么这个投资会失败'，再思考'为什么它会成功'"

        # 奥卡姆剃刀
        if slug in ("occams-razor", "simplicity"):
            return "如果一个投资需要复杂的故事才能自圆其说，那可能不是一个好投资"

        # 操纵/欺诈相关
        if slug in ("falsification", "accounting-red-flags") and manip_risk > 30:
            return f"操纵风险{manip_risk:.0f}分——建议用否证思维复核近期交易量和分时图"

        # 心理学/废话倾向
        if slug in ("twaddle-tendency",):
            return "警惕公司IR和管理层在电话会中的空洞话术——看他们做了什么而非说了什么"

        # 通用
        return f"结合当前评分（动量{momentum:.0f}/质量{quality:.0f}/盈利{earnings:.0f}）审视该模型的启示"

    @staticmethod
    def _score_model(
        *,
        slug: str,
        name_cn: str,
        discipline: str,
        desc: str,
        portfolio: dict,
        sentiment: str,
        has_exec_risks: bool,
        has_red_flags: bool,
        has_competition: bool,
        regime_crowded: bool,
    ) -> tuple[bool, str, int]:
        """对单个模型打分。返回 (是否匹配, reason, relevance)。"""
        # 心理学：组合浮亏或情绪极端
        psych_keywords = {
            "loss": "损失厌恶 / 被剥夺超级反应",
            "deprival": "损失厌恶 / 被剥夺超级反应",
            "social-proof": "情绪极端时容易受社会认同驱动",
            "herding": "情绪极端时容易出现羊群行为",
            "overoptimism": "过度乐观可能放大风险",
            "disliking": "避免被厌恶情绪左右卖出决策",
            "liking": "避免因为喜欢公司而高估",
            "availability": "易得性偏差影响概率判断",
            "anchoring": "锚定偏差影响估值判断",
            "inconsistency": "避免不一致性导致错失纠错时机",
            "narrative": "叙事谬误可能掩盖真实因果",
            "confirmation": "确认偏误需要主动寻找反证",
        }
        if portfolio.get("has_loss") or sentiment in ("EXTREME", "PANIC", "GREED"):
            for kw, reason in psych_keywords.items():
                if kw in slug or kw in desc:
                    return True, f"心理学模型：{reason}", 10

        # 经济学/竞争：行业或竞争关键词
        econ_keywords = {
            "incentives": "激励机制决定行为",
            "supply": "供需关系影响定价权",
            "demand": "供需关系影响定价权",
            "network": "网络效应决定护城河",
            "competitive advantage": "竞争优势决定长期回报",
            "marginal": "边际分析评估扩张决策",
            "comparative advantage": "比较优势分析产业链位置",
            "scarcity": "稀缺性决定价值",
            "opportunity cost": "机会成本决定配置效率",
        }
        if has_competition:
            for kw, reason in econ_keywords.items():
                if kw in desc:
                    return True, f"经济学模型：{reason}", 9

        # 会计/欺诈：高管风险或红旗
        accounting_keywords = {
            "falsification": "用否证思维检验财务假设",
            "inversion": "逆向思维先找失败原因",
            "checklist": "用检查清单核对财报风险",
            "occams": "奥卡姆剃刀排除过度复杂解释",
            "twaddle": "警惕管理层废话与空洞表述",
        }
        if has_exec_risks or has_red_flags:
            for kw, reason in accounting_keywords.items():
                if kw in slug or kw in desc:
                    return True, f"会计/反欺诈模型：{reason}", 10

        # 生物学/进化：市场拥挤/衰退
        biology_keywords = {
            "darwin": "达尔文式客观适应变化",
            "evolution": "进化思维看待竞争淘汰",
            "survivorship": "幸存者偏差在拥挤阶段尤为危险",
            "adaptation": "适应能力决定能否穿越周期",
            "redundancy": "冗余是应对不确定性的进化策略",
            "ecosystem": "生态系统思维理解产业链",
        }
        if regime_crowded:
            for kw, reason in biology_keywords.items():
                if kw in slug or kw in desc:
                    return True, f"生物学/进化模型：{reason}", 9

        # 通用高相关模型兜底
        universal = {
            "circle-of-competence": ("能力圈：确认自己是否真正理解该标的", 8),
            "latticework": ("多元思维模型框架：避免铁锤人倾向", 7),
            "man-with-a-hammer": ("铁锤人倾向：警惕用单一框架硬套", 7),
            "second-order": ("二阶效应：关注政策的后果的后果", 7),
            "avoiding-stupidity": ("避蠢优于求智：先避免明显错误", 7),
        }
        for kw, (reason, rel) in universal.items():
            if kw in slug:
                return True, reason, rel

        return False, "", 0

    @staticmethod
    def _portfolio(report: Optional[object]) -> dict:
        """从 report 或 investor_mental_model 提取组合状态。"""
        portfolio: dict = {}
        if report is None:
            return portfolio
        imm = getattr(report, "investor_mental_model", None)
        if imm is not None:
            flags = getattr(imm, "bias_flags", []) or []
            portfolio["has_loss"] = any("浮亏" in f or "loss" in f for f in flags)
        # 兼容 report 本身携带的 portfolio 摘要
        if not portfolio.get("has_loss"):
            portfolio["has_loss"] = bool(
                getattr(report, "red_lines", None) or getattr(report, "warnings", None)
            )
        return portfolio

    @staticmethod
    def _sentiment(report: Optional[object]) -> str:
        if report is None:
            return "NEUTRAL"
        return getattr(report, "sentiment_signal", "NEUTRAL")

    @staticmethod
    def _has_exec_risks(report: Optional[object]) -> bool:
        if report is None:
            return False
        return bool(getattr(report, "executive_risks", None))

    @staticmethod
    def _has_red_flags(report: Optional[object]) -> bool:
        if report is None:
            return False
        # 博弈论风险或诊断上游风险均视为红旗
        gt = getattr(report, "game_theory_profile", None)
        if gt and getattr(gt, "risks", None):
            return True
        return bool(getattr(report, "upstream_risks", None))

    @staticmethod
    def _has_competition(sector: str, report: Optional[object]) -> bool:
        if sector:
            return True
        if report is None:
            return False
        bn = getattr(report, "bottleneck_analysis", None)
        if bn and getattr(bn, "bottleneck_type", None):
            return True
        return bool(getattr(report, "bottlenecks", None))

    @staticmethod
    def _regime_crowded(report: Optional[object]) -> bool:
        if report is None:
            return False
        gt = getattr(report, "game_theory_profile", None)
        if gt is not None:
            crowding = getattr(gt, "crowding_score", 0) or 0
            if crowding >= 60:
                return True
            regime = getattr(gt, "market_regime", "")
            if "crowded" in str(regime).lower():
                return True
        alpha = getattr(report, "alpha_profile", None)
        if alpha is not None:
            narrative = getattr(alpha, "narrative", None)
            if narrative:
                stage = getattr(narrative, "stage", None)
                if stage is not None and str(stage).lower() in ("crowded", "fading"):
                    return True
        return False
