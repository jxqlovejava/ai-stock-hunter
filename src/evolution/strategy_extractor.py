# -*- coding: utf-8 -*-
"""策略提取器 — 从策略类论文中提取结构化策略定义。

输入: 分类为 STRATEGY 的 StrategyPaper
输出: ExtractedStrategy (含策略名称、买卖条件、参数等)

用法:
    extractor = StrategyExtractor()
    strategy = extractor.extract(paper)
    print(strategy.strategy_name, strategy.parameters)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .schema import (
    ExtractedStrategy,
    PaperType,
    StrategyPaper,
)

logger = logging.getLogger(__name__)


class StrategyExtractor:
    """从论文中提取结构化策略定义。

    支持关键词规则提取 + LLM 辅助提取两种模式。

    用法:
        extractor = StrategyExtractor()
        strategy = extractor.extract(paper)
        if strategy.extraction_confidence >= 0.6:
            # 可用于回测
            ...
    """

    # 量化指标关键词 → 标准化参数名
    METRIC_PATTERNS: dict[str, re.Pattern] = {
        "pe_ratio": re.compile(r"(?:市盈率|P/?E\s*ratio|PE)\s*[<≤]\s*([\d.]+)", re.IGNORECASE),
        "pb_ratio": re.compile(r"(?:市净率|P/?B\s*ratio|PB)\s*[<≤]\s*([\d.]+)", re.IGNORECASE),
        "roe": re.compile(r"(?:ROE|净资产收益率)\s*[>≥]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "roa": re.compile(r"(?:ROA|总资产收益率)\s*[>≥]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "debt_ratio": re.compile(r"(?:资产负债率|debt\s*ratio)\s*[<≤]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "revenue_growth": re.compile(r"(?:营收增速|revenue\s*growth)\s*[>≥]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "profit_growth": re.compile(r"(?:净利润增速|profit\s*growth)\s*[>≥]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "dividend_yield": re.compile(r"(?:股息率|dividend\s*yield)\s*[>≥]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "market_cap": re.compile(r"(?:市值|market\s*cap)\s*[>≥]\s*([\d.]+)\s*(?:亿|B)?", re.IGNORECASE),
        "volume": re.compile(r"(?:成交量|volume|成交额)\s*[>≥]\s*([\d.]+)\s*(?:万|亿|M)?", re.IGNORECASE),
        "max_drawdown": re.compile(r"(?:最大回撤|max\s*drawdown)\s*[<≤]\s*([\d.]+)\s*%?", re.IGNORECASE),
        "stop_loss": re.compile(r"(?:止损|stop\s*loss)\s*[<≤\-]?\s*([\d.]+)\s*%?", re.IGNORECASE),
        "take_profit": re.compile(r"(?:止盈|take\s*profit)\s*[>≥]?\s*([\d.]+)\s*%?", re.IGNORECASE),
    }

    # 买入条件关键词
    BUY_TRIGGERS = [
        r"(?:buy|买入|long|做多|建仓).*?(?:when|当|若|条件)",
        r"(?:entry|入场).*?(?:condition|条件|signal|信号)",
        r"(?:position.*?(?:open|enter|initiate))",
        r"(?:开仓|进场|建仓).*?(?:条件|信号|时机)",
    ]

    # 卖出条件关键词
    SELL_TRIGGERS = [
        r"(?:sell|卖出|short|做空|平仓).*?(?:when|当|若|条件)",
        r"(?:exit|出场).*?(?:condition|条件|signal|信号)",
        r"(?:position.*?(?:close|exit|liquidate))",
        r"(?:平仓|出场|止损|止盈).*?(?:条件|信号|时机)",
    ]

    # 策略类型关键词
    TYPE_KEYWORDS = {
        "factor": ["因子", "factor", "多因子", "multi-factor", "Fama-French", "alpha factor"],
        "timing": ["择时", "timing", "market timing", "大盘择时", "仓位择时"],
        "screening": ["选股", "screening", "筛选", "stock selection", "stock picking"],
        "risk": ["风控", "risk management", "风险控制", "risk model", "VaR", "CVaR"],
        "composite": ["综合", "composite", "ensemble", "多策略", "multi-strategy"],
    }

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, paper: StrategyPaper) -> ExtractedStrategy:
        """从论文中提取策略定义。

        Args:
            paper: 已分类为 STRATEGY 的 StrategyPaper

        Returns:
            ExtractedStrategy
        """
        if paper.paper_type != PaperType.STRATEGY:
            logger.warning(
                "论文 %s 类型为 %s 而非 Strategy，提取可能不准确",
                paper.id, paper.paper_type.value,
            )

        strategy = ExtractedStrategy(paper_id=paper.id)

        text = f"{paper.title}\n{paper.abstract}\n{paper.full_text[:10000]}"

        # 提取策略名
        strategy.strategy_name = self._extract_name(paper.title, text)

        # 提取买卖条件
        strategy.entry_conditions = self._extract_conditions(text, self.BUY_TRIGGERS)
        strategy.exit_conditions = self._extract_conditions(text, self.SELL_TRIGGERS)

        # 提取参数
        strategy.parameters = self._extract_parameters(text)

        # 判断策略类型
        strategy.strategy_type = self._classify_strategy_type(text)

        # 来源标记
        strategy.sourced_fields = list(strategy.parameters.keys())
        strategy.sourced_fields.extend(["entry_conditions", "exit_conditions"])

        # 标记未溯源字段
        if not strategy.entry_conditions:
            strategy.unsourced_fields.append("entry_conditions")
        if not strategy.exit_conditions:
            strategy.unsourced_fields.append("exit_conditions")
        if not strategy.parameters:
            strategy.unsourced_fields.append("parameters")

        # 计算提取置信度
        strategy.extraction_confidence = self._calculate_confidence(strategy)

        # 描述
        strategy.description = self._generate_description(strategy)

        logger.info(
            "策略提取: %s → %s (置信度 %.2f, %d 参数)",
            paper.title[:40], strategy.strategy_name,
            strategy.extraction_confidence, len(strategy.parameters),
        )
        return strategy

    def extract_with_llm(self, paper: StrategyPaper) -> ExtractedStrategy:
        """使用 LLM 辅助提取（更高精度，需要 API）。

        当关键词提取置信度不足 (< 0.6) 时调用。
        """
        strategy = self.extract(paper)

        prompt = (
            f"Extract a structured trading strategy from this paper:\n\n"
            f"Title: {paper.title}\n"
            f"Abstract: {paper.abstract[:2000]}\n\n"
            f"Please output:\n"
            f"1. Strategy Name (short, descriptive)\n"
            f"2. Strategy Type (factor/timing/screening/risk/composite)\n"
            f"3. Entry Conditions (list natural language rules)\n"
            f"4. Exit Conditions (list natural language rules)\n"
            f"5. Parameters (name: value pairs)\n"
            f"6. Key Assumptions\n"
            f"Mark any uncertain items with [UNSOURCED]."
        )

        # 留给 LLM 调用实现
        logger.info("[UNSOURCED] LLM strategy extractor not wired — using keyword result")
        return strategy

    # ------------------------------------------------------------------
    # Internal — Name Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_name(title: str, _text: str) -> str:
        """从标题提取简洁策略名。"""
        # 清理常见前缀
        cleaned = re.sub(
            r"(?i)^(a\s+|the\s+|an\s+)?(novel\s+|new\s+|improved\s+)?(approach\s+(to|for)\s+)?",
            "", title
        )
        cleaned = re.sub(r"(?i)(in\s+)?(the\s+)?(chinese\s+)?(a-?share|stock)\s+market", "", cleaned)
        cleaned = re.sub(r"\s*[-–:]\s*.*$", "", cleaned)  # 去掉冒号后的副标题
        cleaned = re.sub(r"[^a-zA-Z0-9一-鿿\s\-_]", "", cleaned)  # 只保留中英文/数字
        cleaned = " ".join(cleaned.split()[:8])  # 最多 8 个词
        return cleaned or "UnnamedStrategy"

    # ------------------------------------------------------------------
    # Internal — Condition Extraction
    # ------------------------------------------------------------------

    def _extract_conditions(self, text: str, trigger_patterns: list[str]) -> list[str]:
        """从文本中提取买卖条件。"""
        conditions: list[str] = []

        # 按触发词搜索周围句子
        for trigger in trigger_patterns:
            for m in re.finditer(trigger, text, re.IGNORECASE):
                start = max(0, m.start() - 100)
                end = min(len(text), m.end() + 500)
                context = text[start:end]

                # 提取条件句子
                sentences = re.split(r"(?<=[。.!！?\n])\s*", context)
                for sent in sentences[:3]:
                    sent = sent.strip()
                    if len(sent) > 10 and sent not in conditions:
                        conditions.append(sent)

        # 如果没有触发词，搜索数值条件
        if not conditions:
            conditions = self._extract_numeric_conditions(text)

        return conditions[:10]  # 限制数量

    def _extract_numeric_conditions(self, text: str) -> list[str]:
        """从文本中提取含数值的条件句。"""
        conditions = []
        sentences = re.split(r"(?<=[。.!！?\n])\s*", text)
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 10:
                continue
            # 包含阈值关键词 + 数字
            has_metric = any(
                kw in sent.lower()
                for kw in ["大于", "小于", "超过", "低于", "≥", "≤", ">", "<",
                           "percentile", "threshold", "quantile"]
            )
            has_number = bool(re.search(r"[\d.]+", sent))
            if has_metric and has_number:
                conditions.append(sent)
        return conditions[:10]

    # ------------------------------------------------------------------
    # Internal — Parameter Extraction
    # ------------------------------------------------------------------

    def _extract_parameters(self, text: str) -> dict[str, float]:
        """从文本中提取数值参数。"""
        params: dict[str, float] = {}
        for param_name, pattern in self.METRIC_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                try:
                    params[param_name] = float(matches[0])
                except ValueError:
                    pass
        return params

    # ------------------------------------------------------------------
    # Internal — Classification
    # ------------------------------------------------------------------

    def _classify_strategy_type(self, text: str) -> str:
        """判断策略类型。"""
        scores = {}
        text_lower = text.lower()
        for stype, keywords in self.TYPE_KEYWORDS.items():
            scores[stype] = sum(1 for kw in keywords if kw.lower() in text_lower)
        if not scores or max(scores.values()) == 0:
            return "composite"
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Internal — Confidence
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_confidence(strategy: ExtractedStrategy) -> float:
        """基于提取结果的完整度计算置信度。"""
        score = 0.0
        if strategy.strategy_name:
            score += 0.1
        if strategy.entry_conditions and strategy.exit_conditions:
            score += 0.3
        elif strategy.entry_conditions or strategy.exit_conditions:
            score += 0.15
        if strategy.parameters:
            param_score = min(0.4, len(strategy.parameters) * 0.08)
            score += param_score
        if strategy.strategy_type:
            score += 0.1
        # 未溯源惩罚
        score -= len(strategy.unsourced_fields) * 0.05
        return max(0.1, min(0.95, score))

    @staticmethod
    def _generate_description(strategy: ExtractedStrategy) -> str:
        """生成策略描述。"""
        parts = [f"{strategy.strategy_name}"]
        if strategy.strategy_type:
            parts.append(f"类型: {strategy.strategy_type}")
        if strategy.entry_conditions:
            parts.append(f"买入条件 ({len(strategy.entry_conditions)} 条)")
        if strategy.exit_conditions:
            parts.append(f"卖出条件 ({len(strategy.exit_conditions)} 条)")
        if strategy.parameters:
            parts.append(f"参数: {len(strategy.parameters)} 个")
        if strategy.unsourced_fields:
            parts.append(f"[UNSOURCED]: {', '.join(strategy.unsourced_fields)}")
        return " | ".join(parts)
