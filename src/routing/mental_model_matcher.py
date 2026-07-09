# -*- coding: utf-8 -*-
"""Munger 232 思维模型匹配器 — 动态上下文驱动。

根据诊断报告/市场环境/投资者画像，从 232 个模型中动态匹配最相关的模型。
不再是固定的 5 个模型——不同市场、不同股票、不同问题匹配不同模型。
匹配规则基于概念-描述全文匹配，不调用 LLM。
"""

from __future__ import annotations

import json
import os
import re
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
    """Munger 思维模型匹配器 — 动态上下文驱动。"""

    _JSON_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "munger_232_models.json",
    )

    # ── 上下文概念 → 搜索关键词映射 ──
    # 每个上下文信号展开为多个中文关键词，用于扫描模型描述
    # 注意：各组关键词保持区分度，避免跨组重叠导致评分偏向某一信号
    _CONTEXT_SIGNAL_MAP: dict[str, list[str]] = {
        # 动量/趋势 — 聚焦价格运动本身
        "momentum_strong": ["动量", "趋势延续", "惯性", "正反馈", "飞轮效应", "加速增长", "顺风"],
        "momentum_weak": ["下跌趋势", "止损纪律", "价格反转", "崩盘", "均值回归", "回撤", "底部"],
        # 质量/护城河 — 聚焦企业质地
        "quality_strong": ["护城河", "竞争优势", "网络效应", "规模经济", "转换成本", "定价权", "品牌壁垒", "复利机器"],
        "quality_weak": ["竞争侵蚀", "替代威胁", "商品化", "利润挤压", "护城河变窄", "竞争性毁灭"],
        # 价值/估值 — 聚焦价格与价值关系
        "value_deep": ["安全边际", "低估", "内在价值", "逆向投资", "市场先生", "恐惧时贪婪", "烟蒂股"],
        "value_expensive": ["高估", "泡沫", "投机狂热", "博傻理论", "非理性繁荣", "估值回归"],
        # 盈利/基本面 — 聚焦财务实绩
        "earnings_strong": ["盈利增长", "利润扩张", "现金流充裕", "ROE提升", "基本面改善", "业绩超预期"],
        "earnings_weak": ["盈利下滑", "利润减值", "应收账款激增", "存货积压", "现金流恶化", "业绩变脸"],
        # 情绪/行为偏差 — 聚焦心理因素
        "sentiment_extreme": ["羊群行为", "从众心理", "贪婪情绪", "确认偏误", "过度自信", "锚定偏差", "社会认同", "过度反应偏差"],
        "sentiment_neutral": ["理性决策", "独立思考", "耐心等待", "纪律执行", "冷静分析"],
        # 拥挤/主题 — 聚焦市场结构
        "regime_crowded": ["拥挤交易", "幸存者偏差", "自然选择", "适者生存", "生态位竞争", "进化淘汰", "趋同"],
        "regime_emerging": ["新兴市场", "创新萌芽", "颠覆性创新", "先发优势", "蓝海战略", "探索性"],
        # 风险/红旗 — 聚焦危险信号
        "has_red_flags": ["财务欺诈", "会计造假", "操纵市场", "红旗信号", "审计异常", "内控失效", "否证思维", "证伪"],
        "has_exec_risks": ["代理问题", "激励机制", "管理层风险", "信托责任", "利益冲突", "薪酬扭曲", "公司治理"],
        # 竞争/瓶颈 — 聚焦行业结构
        "has_competition": ["供需关系", "稀缺性", "定价权", "产业链", "进入壁垒", "比较优势", "替代品威胁", "波特五力"],
        "has_bottleneck": ["供应链瓶颈", "产能短缺", "供给过剩", "上游集中", "下游依赖", "资源约束"],
        # 组合状态 — 聚焦持仓心理
        "portfolio_has_loss": ["沉没成本谬误", "损失厌恶", "被剥夺感", "承认错误", "舍不得割肉", "回本就卖", "拒绝止损"],
        "portfolio_concentrated": ["集中投资", "分散化", "组合配置", "相关性风险", "对冲策略"],
        # 宏观/周期 — 聚焦大环境
        "macro_tight": ["货币紧缩", "加息周期", "去杠杆", "信用收缩", "流动性危机", "债务压力"],
        "macro_loose": ["货币宽松", "降息周期", "信用扩张", "流动性泛滥", "热钱涌入"],
        "cycle_peak": ["周期顶点", "经济过热", "产能过剩", "拐点", "盛极而衰"],
        "cycle_trough": ["周期底部", "困境反转", "复苏萌芽", "否极泰来"],
    }

    def __init__(self):
        self._models = self._load_models()
        # 为每个模型预计算可搜索文本
        self._model_texts: dict[str, str] = {}
        for m in self._models:
            slug = m.get("slug", "")
            self._model_texts[slug] = (
                f"{m.get('name_cn', '')} {m.get('name_en', '')} "
                f"{m.get('discipline', '')} {m.get('description', '')}"
            ).lower()

    @classmethod
    def _load_models(cls) -> list[dict]:
        try:
            with open(cls._JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("models", [])
        except Exception:
            return []

    # ── 公共 API ──

    def match_models(
        self,
        symbol: str,
        name: str,
        sector: str = "",
        report: Optional[object] = None,
        question: str = "",
        macro_context: Optional[dict] = None,
    ) -> list[dict]:
        """返回与当前上下文最相关的 Munger 模型（动态数量，不固定 5 个）。

        参数:
            symbol: 股票代码
            name: 股票名称
            sector: 行业板块
            report: 诊断报告（可为 None——此时基于其它参数匹配）
            question: 用户问题（如"值得建仓吗"/"为什么大跌"等场景关键词）
            macro_context: 宏观环境描述
        """
        if not self._models:
            return []

        # 1. 构建上下文信号
        signals = self._build_signals(report, sector, question, macro_context)

        # 2. 展开信号为加权搜索词
        weighted_terms = self._signals_to_weighted_terms(signals)

        # 3. 对所有模型全文匹配打分
        candidates: list[_MatchedModel] = []
        for m in self._models:
            slug = m.get("slug", "")
            search_text = self._model_texts.get(slug, "")
            score, matched_terms = self._compute_relevance(
                search_text, weighted_terms, m, signals
            )
            if score >= 5:  # 最低相关度阈值
                reason = self._build_reason(matched_terms, signals, m)
                candidates.append(_MatchedModel(
                    slug=slug,
                    name_cn=m.get("name_cn", ""),
                    discipline=m.get("discipline", ""),
                    reason_for_match=reason,
                    relevance=score,
                ))

        # 4. 排序，返回所有超过阈值的（动态数量）
        candidates.sort(key=lambda x: x.relevance, reverse=True)
        # 返回 3-8 个（太少不够全面，太多信息过载）
        top = candidates[:8]
        # 如果不足 3 个，降低阈值补充
        if len(top) < 3:
            extra = [c for c in candidates if c not in top and c.relevance >= 3][:3 - len(top)]
            top.extend(extra)

        # 5. 构建输出
        result = []
        for m in top:
            desc = ""
            for raw in self._models:
                if raw.get("slug") == m.slug:
                    desc = raw.get("description", "")
                    break
            result.append({
                "slug": m.slug,
                "name_cn": m.name_cn,
                "discipline": m.discipline,
                "reason_for_match": m.reason_for_match,
                "description": desc,
                "relevance": m.relevance,
            })
        return result

    # ── 上下文信号提取 ──

    def _build_signals(
        self,
        report: Optional[object],
        sector: str,
        question: str,
        macro_context: Optional[dict],
    ) -> dict[str, float]:
        """从所有可用信息源构建加权信号字典。"""
        signals: dict[str, float] = {}

        # 从 report 提取分数
        scores: dict[str, float] = {}
        if report is not None:
            for attr in ("macro_score", "value_score", "quality_score", "momentum_score",
                         "earnings_revision_score", "valuation_score", "cycle_score",
                         "executive_score", "manipulation_risk_score"):
                v = getattr(report, attr, None)
                if v is not None:
                    scores[attr] = float(v)
            scores["sentiment"] = getattr(report, "sentiment_signal", "NEUTRAL") or "NEUTRAL"

        # ── 动量 ──
        momentum = scores.get("momentum_score", 50)
        if momentum >= 70:
            signals["momentum_strong"] = (momentum - 50) / 50
        elif momentum <= 35:
            signals["momentum_weak"] = (35 - momentum) / 35

        # ── 质量 ──
        quality = scores.get("quality_score", 50)
        if quality >= 70:
            signals["quality_strong"] = (quality - 50) / 50
        elif quality <= 40:
            signals["quality_weak"] = (40 - quality) / 40

        # ── 价值 ──
        value = scores.get("value_score", 50)
        if value >= 75:
            signals["value_deep"] = (value - 50) / 50
        elif value <= 30:
            signals["value_expensive"] = (30 - value) / 30

        # ── 盈利修正 ──
        earnings = scores.get("earnings_revision_score", 50)
        if earnings >= 70:
            signals["earnings_strong"] = (earnings - 50) / 50
        elif earnings <= 35:
            signals["earnings_weak"] = (35 - earnings) / 35

        # ── 情绪 ──
        sentiment_str = str(scores.get("sentiment", "NEUTRAL")).upper()
        if sentiment_str in ("EXTREME", "PANIC", "GREED"):
            signals["sentiment_extreme"] = 1.0
        elif sentiment_str == "NEUTRAL":
            signals["sentiment_neutral"] = 0.3  # 低权重

        # ── 拥挤/主题 ──
        if self._is_regime_crowded(report):
            signals["regime_crowded"] = 1.0
        elif self._is_regime_emerging(report):
            signals["regime_emerging"] = 0.8

        # ── 风险 ──
        if self._has_red_flags(report):
            signals["has_red_flags"] = 1.0
        if self._has_exec_risks(report):
            signals["has_exec_risks"] = 0.9

        # ── 竞争/瓶颈 ──
        # 仅知行业名称 → 低权重（行业背景信息，不应主导匹配）
        # 有实际竞争分析结果 → 高权重
        has_comp = self._has_competition(report)
        if has_comp:
            signals["has_competition"] = 0.7
        elif sector:
            signals["has_competition"] = 0.25  # 低权重：仅知行业，无具体竞争数据
        if self._has_bottleneck(report):
            signals["has_bottleneck"] = 0.9

        # ── 组合状态 ──
        portfolio = self._extract_portfolio(report)
        if portfolio.get("has_loss"):
            signals["portfolio_has_loss"] = 0.85
        if portfolio.get("concentrated"):
            signals["portfolio_concentrated"] = 0.6

        # ── 宏观 ──
        if macro_context:
            regime = macro_context.get("regime", "")
            if "tight" in str(regime).lower() or "紧缩" in str(regime):
                signals["macro_tight"] = 0.8
            elif "loose" in str(regime).lower() or "宽松" in str(regime):
                signals["macro_loose"] = 0.8

        # ── 周期 ──
        cycle = scores.get("cycle_score", 50)
        if cycle >= 75:
            signals["cycle_peak"] = (cycle - 50) / 50
        elif cycle <= 30:
            signals["cycle_trough"] = (30 - cycle) / 30

        # ── 问题关键词注入 ──
        if question:
            signals[f"question:{question}"] = 0.6  # 问题自带的关键词权重

        return signals

    # ── 信号 → 加权搜索词 ──

    def _signals_to_weighted_terms(self, signals: dict[str, float]) -> dict[str, float]:
        """将信号字典展开为带权重的搜索词表。"""
        weighted: dict[str, float] = {}

        for signal_key, weight in signals.items():
            # 检查是否是 question: 前缀
            if signal_key.startswith("question:"):
                question_text = signal_key[len("question:"):]
                # 直接使用问题中的关键词
                for term in self._tokenize_chinese(question_text):
                    if len(term) >= 2:
                        weighted[term] = max(weighted.get(term, 0), weight)
                continue

            # 从映射表获取关键词
            terms = self._CONTEXT_SIGNAL_MAP.get(signal_key, [])
            for term in terms:
                current = weighted.get(term, 0)
                weighted[term] = max(current, weight)

        return weighted

    @staticmethod
    def _tokenize_chinese(text: str) -> list[str]:
        """简单的中文分词（基于字符 n-gram）。"""
        text = re.sub(r'[^一-鿿\w]', ' ', text)
        words = text.split()
        # 对中文部分做 2-gram 和 3-gram
        result = list(words)
        for w in words:
            if len(w) >= 4 and re.search(r'[一-鿿]', w):
                for n in (2, 3):
                    for i in range(len(w) - n + 1):
                        result.append(w[i:i + n])
        return result

    # ── 动态相关性计算 ──

    def _compute_relevance(
        self,
        search_text: str,
        weighted_terms: dict[str, float],
        model: dict,
        signals: dict[str, float],
    ) -> tuple[int, list[str]]:
        """计算模型与当前上下文的相关性分数。

        核心原则:
        1. 每个信号的贡献独立计算并设上限（防止某一信号垄断评分）
        2. 长关键词（更具体）匹配权重更高
        3. 多信号交叉命中 → 额外加成（信号收敛 = 高相关）
        """
        model_name = model.get("name_cn", "")
        model_discipline = model.get("discipline", "")

        # 第一步：按信号分组匹配，每信号独立评分
        signal_scores: dict[str, float] = {}
        signal_matched_terms: dict[str, list[str]] = {}
        all_matched: list[str] = []

        for sig_key, sig_weight in signals.items():
            if sig_key.startswith("question:"):
                continue
            terms = self._CONTEXT_SIGNAL_MAP.get(sig_key, [])
            sig_total = 0.0
            sig_terms: list[str] = []
            for term in terms:
                if term.lower() in search_text:
                    # 长关键词加分：2字=1x, 3字=1.5x, 4字+=2x
                    length_bonus = min(len(term) / 3, 2.0)
                    term_score = sig_weight * 12 * length_bonus
                    sig_total += term_score
                    sig_terms.append(term)
                    all_matched.append(term)
            if sig_terms:
                # 每信号得分上限 = signal_weight * 35（防止一个信号垄断）
                signal_scores[sig_key] = min(sig_total, sig_weight * 35)
                signal_matched_terms[sig_key] = sig_terms

        # 第二步：模型名称精确匹配加分（模型名直接包含信号概念）
        name_bonus = 0
        model_name_lower = model_name.lower()
        for sig_key in signal_scores:
            terms = self._CONTEXT_SIGNAL_MAP.get(sig_key, [])
            for term in terms:
                if term.lower() in model_name_lower and len(term) >= 2:
                    name_bonus += 4
                    break  # 每个信号最多一次名称加分

        # 第三步：学科加分（适度，防止心理学/经济学通吃）
        disc_bonus = self._discipline_bonus(model_discipline, signals)

        # 第四步：多信号交叉收敛奖励
        active_signal_count = len(signal_scores)
        convergence_bonus = 0
        if active_signal_count >= 3:
            convergence_bonus = (active_signal_count - 2) * 5  # 3信号=+5, 4信号=+10, 5信号=+15

        # 第五步：计算总分
        base_score = sum(signal_scores.values())
        total = base_score + name_bonus + disc_bonus + convergence_bonus

        return min(int(total), 100), all_matched[:5]

    def _discipline_bonus(self, discipline: str, signals: dict[str, float]) -> int:
        """基于上下文信号给相关学科额外加分。"""
        bonus = 0
        disc_lower = discipline.lower() if discipline else ""

        signal_to_disc: dict[str, list[str]] = {
            "sentiment_extreme": ["心理学"],
            "portfolio_has_loss": ["心理学"],
            "has_red_flags": ["会计学", "法学与政治学"],
            "has_exec_risks": ["管理学与商业", "法学与政治学"],
            "has_competition": ["微观经济学", "管理学与商业"],
            "has_bottleneck": ["微观经济学", "工程学"],
            "value_deep": ["投资学与金融学", "投资原则与品格"],
            "value_expensive": ["投资学与金融学", "历史学与哲学"],
            "momentum_strong": ["物理学与化学", "生物学与进化论"],
            "momentum_weak": ["心理学", "投资原则与品格"],
            "quality_strong": ["管理学与商业", "微观经济学"],
            "regime_crowded": ["生物学与进化论", "复杂系统"],
            "regime_emerging": ["生物学与进化论", "微观经济学"],
            "macro_tight": ["微观经济学", "历史学与哲学"],
            "macro_loose": ["微观经济学", "历史学与哲学"],
            "cycle_peak": ["历史学与哲学", "复杂系统"],
            "cycle_trough": ["历史学与哲学", "投资学与金融学"],
            "earnings_strong": ["会计学", "投资学与金融学"],
            "earnings_weak": ["会计学", "管理学与商业"],
        }

        for sig, discs in signal_to_disc.items():
            if sig in signals:
                for d in discs:
                    if d in discipline:
                        bonus += 3
                        break

        return min(bonus, 15)

    # ── 匹配原因生成 ──

    @staticmethod
    def _build_reason(
        matched_terms: list[str],
        signals: dict[str, float],
        model: dict,
    ) -> str:
        """生成人类可读的匹配原因 — 基于该模型实际命中的信号。"""
        name_cn = model.get("name_cn", model.get("slug", ""))

        if not signals:
            return f"「{name_cn}」— 通用思维框架，适用于当前分析场景"

        signal_labels: dict[str, str] = {
            "momentum_weak": "动量偏弱",
            "momentum_strong": "动量强劲",
            "quality_weak": "质量偏弱",
            "quality_strong": "质量扎实",
            "value_deep": "深度价值",
            "value_expensive": "估值偏高",
            "earnings_strong": "盈利强劲",
            "earnings_weak": "盈利承压",
            "sentiment_extreme": "情绪极端",
            "sentiment_neutral": "情绪平稳",
            "regime_crowded": "主题拥挤",
            "regime_emerging": "主题萌芽",
            "has_red_flags": "红旗信号",
            "has_exec_risks": "高管风险",
            "has_competition": "行业竞争",
            "has_bottleneck": "供需瓶颈",
            "portfolio_has_loss": "持仓浮亏",
            "portfolio_concentrated": "持仓集中",
            "macro_tight": "宏观紧缩",
            "macro_loose": "宏观宽松",
            "cycle_peak": "周期高位",
            "cycle_trough": "周期底部",
        }

        # 找到该模型实际匹配的关键词来源（按信号分组）
        # 取权重最高的 2 个不同信号
        top_signals = sorted(signals.items(), key=lambda x: -x[1])
        # 过滤掉 question: 前缀
        top_signals = [(k, v) for k, v in top_signals if not k.startswith("question:")]
        top2 = top_signals[:2]

        labels = []
        for sig_key, _ in top2:
            lbl = signal_labels.get(sig_key, "")
            if lbl:
                labels.append(lbl)

        if labels and matched_terms:
            # 取最具体的 2 个匹配词
            best_terms = sorted(matched_terms, key=len, reverse=True)[:2]
            term_str = "、".join(best_terms)
            return f"「{name_cn}」— {term_str} → {','.join(labels)}"
        elif labels:
            return f"「{name_cn}」— {','.join(labels)}背景下关键思维框架"
        elif matched_terms:
            return f"「{name_cn}」— 与({matched_terms[0]})相关的思维模型"
        return f"「{name_cn}」— 当前分析场景下的核心框架"

    # ── 辅助方法 ──

    @staticmethod
    def _is_regime_crowded(report: Optional[object]) -> bool:
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

    @staticmethod
    def _is_regime_emerging(report: Optional[object]) -> bool:
        if report is None:
            return False
        alpha = getattr(report, "alpha_profile", None)
        if alpha is not None:
            narrative = getattr(alpha, "narrative", None)
            if narrative:
                stage = getattr(narrative, "stage", None)
                if stage is not None and str(stage).lower() in ("emerging", "spreading"):
                    return True
        return False

    @staticmethod
    def _has_red_flags(report: Optional[object]) -> bool:
        if report is None:
            return False
        gt = getattr(report, "game_theory_profile", None)
        if gt and getattr(gt, "risks", None):
            return True
        if getattr(report, "upstream_risks", None):
            return True
        manip = getattr(report, "manipulation_risk_score", 0) or 0
        if manip > 30:
            return True
        return False

    @staticmethod
    def _has_exec_risks(report: Optional[object]) -> bool:
        if report is None:
            return False
        if getattr(report, "executive_risks", None):
            return True
        exec_score = getattr(report, "executive_score", 50) or 50
        return exec_score < 35

    @staticmethod
    def _has_competition(report: Optional[object]) -> bool:
        if report is None:
            return False
        bn = getattr(report, "bottleneck_analysis", None)
        if bn and getattr(bn, "bottleneck_type", None):
            return True
        return bool(getattr(report, "bottlenecks", None))

    @staticmethod
    def _has_bottleneck(report: Optional[object]) -> bool:
        if report is None:
            return False
        bn = getattr(report, "bottleneck_analysis", None)
        if bn and getattr(bn, "bottleneck_type", None):
            return True
        return False

    @staticmethod
    def _extract_portfolio(report: Optional[object]) -> dict:
        portfolio: dict = {}
        if report is None:
            return portfolio
        imm = getattr(report, "investor_mental_model", None)
        if imm is not None:
            flags = getattr(imm, "bias_flags", []) or []
            portfolio["has_loss"] = any("浮亏" in f or "loss" in f for f in flags)
        if not portfolio.get("has_loss"):
            portfolio["has_loss"] = bool(
                getattr(report, "red_lines", None) or getattr(report, "warnings", None)
            )
        return portfolio
