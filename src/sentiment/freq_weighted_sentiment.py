# -*- coding: utf-8 -*-
"""频率权重情感分析 — 中文金融 NLP 情感分析。

借鉴 go-stock stock_sentiment_analysis.go 的算法设计：
- 内置中文金融情感词典（~90 词 + 权重）
- 否定词翻转极性 / 程度副词调整强度 / 转折词后半段加权
- 频率权重：同一文本源多次出现的词，Score = 原始Score × log(1 + 频次)

纯词典匹配，零外部依赖（无 jieba）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
# 中文金融情感词典（来自 go-stock + A 股常用表达补全）
# ══════════════════════════════════════════════════════════════════════

POSITIVE_FINANCE_WORDS: dict[str, float] = {
    "涨": 1.0, "上涨": 2.0, "涨停": 3.0, "牛市": 3.0, "反弹": 2.0,
    "新高": 2.5, "利好": 2.5, "增持": 2.0, "买入": 2.0, "推荐": 1.5,
    "看多": 2.0, "盈利": 2.0, "增长": 2.0, "超预期": 2.5, "强劲": 1.5,
    "回升": 1.5, "复苏": 2.0, "突破": 2.0, "创新高": 3.0, "回暖": 1.5,
    "上扬": 1.5, "利好消息": 3.0, "收益增长": 2.5, "利润增长": 2.5,
    "业绩优异": 2.5, "潜力股": 2.0, "绩优股": 2.0, "强势": 1.5,
    "走高": 1.5, "攀升": 1.5, "大涨": 2.5, "飙升": 3.0, "井喷": 3.0,
    "暴涨": 3.0, "放量": 1.0, "金叉": 2.0, "多头": 1.5,
    "抄底": 1.5, "护盘": 1.5, "回购": 1.5, "分红": 1.0, "低估": 1.0,
}

NEGATIVE_FINANCE_WORDS: dict[str, float] = {
    "跌": 2.0, "下跌": 2.0, "跌停": 3.0, "熊市": 3.0, "回调": 2.5,
    "新低": 2.5, "利空": 2.5, "减持": 2.0, "卖出": 2.0, "看空": 2.0,
    "亏损": 2.5, "下滑": 2.0, "萎缩": 2.0, "不及预期": 2.5, "疲软": 1.5,
    "恶化": 2.0, "衰退": 2.0, "跌破": 2.0, "创新低": 3.0, "走弱": 2.5,
    "下挫": 2.5, "利空消息": 3.0, "收益下降": 2.5, "利润下滑": 2.5,
    "业绩不佳": 2.5, "垃圾股": 2.0, "风险股": 2.0, "弱势": 2.5,
    "走低": 2.5, "缩量": 2.5, "大跌": 2.5, "暴跌": 3.0, "崩盘": 3.0,
    "跳水": 3.0, "重挫": 3.0, "跌超": 2.5, "跌逾": 2.5, "跌近": 3.0,
    "被抓": 3.0, "被抓捕": 3.0, "回吐": 3.0, "转跌": 3.0,
    "死叉": 2.0, "空头": 1.5, "套牢": 2.0, "踩踏": 3.0, "爆仓": 3.0,
    "退市": 3.0, "ST": 2.0, "问询函": 2.0, "监管函": 2.0, "立案": 3.0,
}

NEGATION_WORDS: set[str] = {"不", "没", "无", "非", "未", "别", "勿", "否", "难以"}

DEGREE_WORDS: dict[str, float] = {
    "非常": 1.8, "极其": 2.2, "太": 1.8, "很": 1.5,
    "比较": 0.8, "稍微": 0.6, "有点": 0.7, "显著": 1.5,
    "大幅": 1.8, "急剧": 2.0, "轻微": 0.6, "小幅": 0.7,
    "逾": 1.8, "超": 1.8, "持续": 1.2, "连续": 1.3,
}

TRANSITION_WORDS: set[str] = {"但是", "然而", "不过", "却", "可是", "但", "可"}

# 标点/分隔符（用于分词切分）
_SEPARATORS: set[str] = {
    "，", "。", "！", "？", "；", "：", "、", "…", "～",
    " ", "\n", "\r", "\t", "（", "）", "(", ")", "【", "】",
    "《", "》", "\"", "'", "「", "」", ",", ".", "!", "?",
}


# ══════════════════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════════════════

class SentimentCategory(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


@dataclass
class SentimentWordHit:
    """单个情感词命中记录。"""
    word: str
    weight: float
    adjusted_weight: float   # 经过否定/程度调整后的权重
    is_positive: bool


@dataclass
class FreqWeightedSentiment:
    """频率权重情感分析结果。"""
    score: float = 0.0               # 原始情感得分
    freq_weighted_score: float = 0.0  # 频率加权后得分
    category: SentimentCategory = SentimentCategory.NEUTRAL
    positive_count: int = 0
    negative_count: int = 0
    word_hits: list[SentimentWordHit] = field(default_factory=list)
    top_keywords: list[tuple[str, float, int]] = field(default_factory=list)
    # (word, adjusted_weight, frequency)
    has_transition: bool = False     # 是否检测到转折词
    pre_transition_score: float = 0.0
    post_transition_score: float = 0.0
    description: str = ""


# ══════════════════════════════════════════════════════════════════════
# 分词器（纯词典 + 最长匹配，无外部依赖）
# ══════════════════════════════════════════════════════════════════════

def _build_term_dict() -> dict[str, float]:
    """将所有情感词构建为统一词典（value=权重，正=正面，负=负面）。"""
    terms: dict[str, float] = {}
    terms.update(POSITIVE_FINANCE_WORDS)
    for w, s in NEGATIVE_FINANCE_WORDS.items():
        terms[w] = -s  # 负面词用负值表示
    return terms


_ALL_TERMS = _build_term_dict()
# 按词长降序排列 → 最长匹配优先。包含情感词 + 否定词 + 程度副词 + 转折词
_ALL_SPECIAL_WORDS = set(NEGATION_WORDS) | set(DEGREE_WORDS.keys()) | set(TRANSITION_WORDS)
_ALL_TERMS_SORTED = sorted(
    set(_ALL_TERMS.keys()) | _ALL_SPECIAL_WORDS,
    key=len,
    reverse=True,
)


def _tokenize(text: str) -> list[str]:
    """中文分词：最长匹配 + 标点切分。

    优先匹配长词（如"超预期"不会被切分成"超"+"预期"），
    未命中的单字逐字输出。
    """
    if not text:
        return []

    tokens: list[str] = []
    pos = 0
    n = len(text)

    while pos < n:
        # 跳过标点和空白
        if text[pos] in _SEPARATORS or text[pos].isspace():
            pos += 1
            continue

        matched = False
        # 尝试最长匹配
        for term in _ALL_TERMS_SORTED:
            t_len = len(term)
            if pos + t_len <= n and text[pos:pos + t_len] == term:
                tokens.append(term)
                pos += t_len
                matched = True
                break

        if not matched:
            # 未匹配 → 单字输出
            tokens.append(text[pos])
            pos += 1

    return tokens


def _find_transition_index(tokens: list[str]) -> Optional[int]:
    """找到第一个转折词的位置。"""
    for i, t in enumerate(tokens):
        if t in TRANSITION_WORDS:
            return i
    return None


# ══════════════════════════════════════════════════════════════════════
# 情感分析器
# ══════════════════════════════════════════════════════════════════════

class FreqWeightedSentimentAnalyzer:
    """频率权重情感分析器。

    用法:
        analyzer = FreqWeightedSentimentAnalyzer()
        result = analyzer.analyze("主力大幅买入，但午后高台跳水暴跌")
        # result.category == SentimentCategory.NEGATIVE
        # result.has_transition == True
    """

    def analyze(self, text: str) -> FreqWeightedSentiment:
        """对单段文本执行情感分析。"""
        if not text or not text.strip():
            return FreqWeightedSentiment(description="空文本")

        tokens = _tokenize(text)
        if not tokens:
            return FreqWeightedSentiment(description="无有效分词")

        # 检测转折
        transition_idx = _find_transition_index(tokens)
        has_transition = transition_idx is not None

        if has_transition and transition_idx is not None:
            pre_tokens = tokens[:transition_idx]
            post_tokens = tokens[transition_idx + 1:]
            pre_score, pre_pos, pre_neg, pre_hits = _calculate_section(pre_tokens)
            post_score, post_pos, post_neg, post_hits = _calculate_section(post_tokens)
            # 转折后权重 × 1.5
            post_score *= 1.5
            score = pre_score + post_score
            positive_count = pre_pos + post_pos
            negative_count = pre_neg + post_neg
            all_hits = pre_hits + post_hits
        else:
            pre_score = 0.0
            post_score = 0.0
            score, positive_count, negative_count, all_hits = _calculate_section(tokens)

        # 分类
        if score > 1.0:
            category = SentimentCategory.POSITIVE
        elif score < -1.0:
            category = SentimentCategory.NEGATIVE
        else:
            category = SentimentCategory.NEUTRAL

        # Top keywords（按 |adjusted_weight| 排序，取前 10）
        sorted_hits = sorted(all_hits, key=lambda h: abs(h.adjusted_weight), reverse=True)
        top_kw: list[tuple[str, float, int]] = []
        seen: dict[str, int] = {}
        for h in sorted_hits[:15]:
            seen[h.word] = seen.get(h.word, 0) + 1
        for word, freq in sorted(seen.items(), key=lambda x: x[1], reverse=True)[:10]:
            orig_weight = _ALL_TERMS.get(word, 0)
            top_kw.append((word, orig_weight, freq))

        # 频率权重：对 hit 的词频加权
        word_freq: dict[str, int] = {}
        for h in all_hits:
            word_freq[h.word] = word_freq.get(h.word, 0) + 1

        # 频率加权得分 = Σ(adjusted_weight × log(1 + freq))
        import math
        freq_weighted_score = sum(
            h.adjusted_weight * math.log(1 + word_freq.get(h.word, 1))
            for h in all_hits
        )

        # 描述
        desc_parts = []
        if category == SentimentCategory.POSITIVE:
            desc_parts.append(f"看涨 (得分 {score:.1f})")
        elif category == SentimentCategory.NEGATIVE:
            desc_parts.append(f"看跌 (得分 {score:.1f})")
        else:
            desc_parts.append(f"中性 (得分 {score:.1f})")
        if has_transition:
            desc_parts.append(f"含转折 (前{pre_score:.1f}/后{post_score:.1f})")
        desc_parts.append(f"正面词{positive_count}个/负面词{negative_count}个")

        return FreqWeightedSentiment(
            score=round(score, 2),
            freq_weighted_score=round(freq_weighted_score, 2),
            category=category,
            positive_count=positive_count,
            negative_count=negative_count,
            word_hits=all_hits,
            top_keywords=top_kw,
            has_transition=has_transition,
            pre_transition_score=round(pre_score, 2),
            post_transition_score=round(post_score, 2),
            description="；".join(desc_parts),
        )

    def analyze_multi(self, texts: list[str]) -> FreqWeightedSentiment:
        """对多条文本（如同一新闻多来源）做聚合情感分析。

        多条文本的得分取平均，频率权重基于跨文本的词频。
        """
        if not texts:
            return FreqWeightedSentiment(description="无文本")

        # 对所有文本分别分析
        results = [self.analyze(t) for t in texts if t and t.strip()]
        if not results:
            return FreqWeightedSentiment(description="全部文本为空")

        # 跨文本词频
        global_word_freq: dict[str, int] = {}
        all_hits: list[SentimentWordHit] = []
        total_score = 0.0
        total_pos = 0
        total_neg = 0

        for r in results:
            total_score += r.score
            total_pos += r.positive_count
            total_neg += r.negative_count
            all_hits.extend(r.word_hits)
            for h in r.word_hits:
                global_word_freq[h.word] = global_word_freq.get(h.word, 0) + 1

        n = len(results)
        avg_score = total_score / n

        # 频率加权
        import math
        freq_weighted = sum(
            h.adjusted_weight * math.log(1 + global_word_freq.get(h.word, 1))
            for h in all_hits
        ) / n

        if avg_score > 0.5:
            category = SentimentCategory.POSITIVE
        elif avg_score < -0.5:
            category = SentimentCategory.NEGATIVE
        else:
            category = SentimentCategory.NEUTRAL

        sorted_hits = sorted(all_hits, key=lambda h: abs(h.adjusted_weight), reverse=True)
        seen: dict[str, int] = {}
        for h in sorted_hits[:20]:
            seen[h.word] = seen.get(h.word, 0) + 1
        top_kw = sorted(seen.items(), key=lambda x: x[1], reverse=True)[:10]
        top_keywords = [(w, _ALL_TERMS.get(w, 0), f) for w, f in top_kw]

        return FreqWeightedSentiment(
            score=round(avg_score, 2),
            freq_weighted_score=round(freq_weighted, 2),
            category=category,
            positive_count=total_pos,
            negative_count=total_neg,
            word_hits=all_hits,
            top_keywords=top_keywords,
            description=f"聚合{len(results)}条文本，{'看涨' if category == SentimentCategory.POSITIVE else '看跌' if category == SentimentCategory.NEGATIVE else '中性'}",
        )


# ══════════════════════════════════════════════════════════════════════
# 内部辅助
# ══════════════════════════════════════════════════════════════════════

def _calculate_section(
    tokens: list[str],
) -> tuple[float, int, int, list[SentimentWordHit]]:
    """计算一段文本的情感得分、正/负面词数、命中记录。"""
    score = 0.0
    positive_count = 0
    negative_count = 0
    hits: list[SentimentWordHit] = []

    n = len(tokens)
    i = 0
    while i < n:
        word = tokens[i]
        polarity = _ALL_TERMS.get(word)

        if polarity is not None:
            adjusted = polarity

            # 检查前一个词：否定词 → 翻转
            if i > 0 and tokens[i - 1] in NEGATION_WORDS:
                adjusted = -polarity

            # 检查前一个词：程度副词 → 乘系数
            if i > 0 and tokens[i - 1] in DEGREE_WORDS:
                adjusted *= DEGREE_WORDS[tokens[i - 1]]

            score += adjusted
            if polarity > 0:
                positive_count += 1
            else:
                negative_count += 1

            hits.append(SentimentWordHit(
                word=word,
                weight=polarity,
                adjusted_weight=round(adjusted, 2),
                is_positive=polarity > 0,
            ))
            i += 1
            continue

        # 检查程度副词+情感词组合（程度副词在前面）
        if word in DEGREE_WORDS and i + 1 < n:
            next_word = tokens[i + 1]
            next_polarity = _ALL_TERMS.get(next_word)
            if next_polarity is not None:
                adjusted = next_polarity * DEGREE_WORDS[word]
                # 再往前检查否定词
                if i > 0 and tokens[i - 1] in NEGATION_WORDS:
                    adjusted = -adjusted

                score += adjusted
                if next_polarity > 0:
                    positive_count += 1
                else:
                    negative_count += 1
                hits.append(SentimentWordHit(
                    word=next_word,
                    weight=next_polarity,
                    adjusted_weight=round(adjusted, 2),
                    is_positive=next_polarity > 0,
                ))
                i += 2
                continue

        # 检查否定词+情感词组合
        if word in NEGATION_WORDS and i + 1 < n:
            next_word = tokens[i + 1]
            next_polarity = _ALL_TERMS.get(next_word)
            if next_polarity is not None:
                adjusted = -next_polarity
                score += adjusted
                if next_polarity > 0:
                    negative_count += 1  # 正面词被否定 → 负面
                else:
                    positive_count += 1  # 负面词被否定 → 正面
                hits.append(SentimentWordHit(
                    word=next_word,
                    weight=next_polarity,
                    adjusted_weight=round(adjusted, 2),
                    is_positive=next_polarity < 0,
                ))
                i += 2
                continue

        i += 1

    return score, positive_count, negative_count, hits
