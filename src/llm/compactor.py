# -*- coding: utf-8 -*-
"""上下文压缩器 (Compactor)。

将累计的分析结果压缩为紧凑的 5 段式 Markdown 摘要，
供后续阶段的 LLM 调用使用，而不必携带完整历史。

基于 Dexter 的 context-management 模式：
  1. Stock & Market Context
  2. Technical Data Retrieved
  3. Fundamental Data Retrieved
  4. Analysis Progress & Scores
  5. Pending Questions & Data Gaps

Usage:
    from src.llm.compactor import Compactor

    compactor = Compactor()
    summary = compactor.compact_results(results, query="600036")
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Compactor:
    """分析结果压缩器。

    使用快速模型（或内置模板）将密集的分析结果压缩为结构化 Markdown。
    """

    def __init__(self, fast_model_name: Optional[str] = None):
        self._fast_model = fast_model_name or "deepseek-chat"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compact_results(self, results: list[dict], query: str) -> str:
        """将累计的分析结果压缩为紧凑的 5 段式 Markdown。

        Args:
            results: 分析阶段累积的结果列表，每个元素是 dict，
                     至少应包含 "stage"、"content"、"score" 等字段。
            query:   原始查询，通常是股票代码或名称。

        Returns:
            压缩后的 Markdown 摘要字符串。
        """
        if not results:
            return self._empty_summary(query)

        prompt = self.build_compaction_prompt(results, query)

        # --------------------------------------------------------------
        # TODO: 接入实际的 LLM 调用 (fast model) 以执行压缩。
        #
        # 当前实现使用基于规则的内置压缩，适用于原型阶段。
        # 生产环境应替换为:
        #
        #   from src.llm.client import call_llm
        #   response = call_llm(
        #       model=self._fast_model,
        #       messages=[{"role": "user", "content": prompt}],
        #       max_tokens=2048,
        #   )
        #   return response.choices[0].message.content
        # --------------------------------------------------------------
        return self._compact_internal(results, query)

    def build_compaction_prompt(self, results: list[dict], query: str) -> str:
        """构造 LLM 压缩提示词。

        Args:
            results: 分析结果列表
            query:   原始查询

        Returns:
            完整的提示词字符串
        """
        sections = []
        for r in results:
            stage = r.get("stage", "unknown")
            content = r.get("content", "")
            score = r.get("score")
            confidence = r.get("confidence")
            header = f"[{stage}]"
            if score is not None:
                header += f" score={score}"
            if confidence is not None:
                header += f" confidence={confidence}"
            sections.append(f"{header}\n{content}")

        body = "\n\n---\n\n".join(sections) if sections else "(no results)"

        return f"""你是一个分析结果压缩器。请将以下关于 "{query}" 的分析结果压缩为
精确的 5 段式 Markdown 摘要。保留所有数字、评分、置信度；省略冗余描述。

要求:
- 每段用 `###` 三级标题开头
- 保留关键数值，移除填充文字
- 标记 [DATA_GAP] 表示缺失数据
- 标记 [SPECULATION] 表示推测信息
- 总长度不超过 1500 tokens

## 输入结果

{body}

## 输出格式

### 1) Stock & Market Context
(股票标识、行业、当前价格、市场状态等)

### 2) Technical Data Retrieved
(获取到的行情数据、K线形态、技术指标等)

### 3) Fundamental Data Retrieved
(获取到的财务数据、估值指标、盈利修正等)

### 4) Analysis Progress & Scores
(各阶段评分、置信度、Alpha评分等)

### 5) Pending Questions & Data Gaps
(未回答问题、缺失数据、需进一步分析之处)
"""

    # ------------------------------------------------------------------
    # Internal (fallback 压缩，无 LLM 调用时使用)
    # ------------------------------------------------------------------

    def _compact_internal(self, results: list[dict], query: str) -> str:
        """基于规则的内部压缩实现。"""
        lines: list[str] = []

        lines.append(f"# Compaction: {query}\n")

        # --- header 统计 ---
        stages = [r.get("stage", "?") for r in results]
        unique_stages = list(dict.fromkeys(stages))
        scores = [
            r["score"]
            for r in results
            if r.get("score") is not None
        ]
        lines.append(f"**Stages**: {len(results)} results across "
                      f"{len(unique_stages)} stages  |  "
                      f"**Scores**: {len(scores)} scored "
                      f"({' / '.join(f'{s:.0f}' for s in scores)})")
        lines.append("")

        # --- 5 段式摘要 ---
        lines.append("### 1) Stock & Market Context")
        market_entries = self._filter_stage(results, {"market", "context", "macro", "regime"})
        for e in market_entries:
            lines.append(e.get("content", "")[:300])
        if not market_entries:
            lines.append("(no market context captured yet)")
        lines.append("")

        lines.append("### 2) Technical Data Retrieved")
        tech_entries = self._filter_stage(results, {"technical", "tech", "kline", "price"})
        for e in tech_entries:
            lines.append(e.get("content", "")[:300])
        if not tech_entries:
            lines.append("(no technical data retrieved yet)")
        lines.append("")

        lines.append("### 3) Fundamental Data Retrieved")
        fund_entries = self._filter_stage(results, {"fundamental", "financial", "value", "quality"})
        for e in fund_entries:
            lines.append(e.get("content", "")[:300])
        if not fund_entries:
            lines.append("(no fundamental data retrieved yet)")
        lines.append("")

        lines.append("### 4) Analysis Progress & Scores")
        scored = [r for r in results if r.get("score") is not None]
        for r in scored:
            stage = r.get("stage", "?")
            score = r.get("score", 0)
            conf = r.get("confidence", "N/A")
            lines.append(f"- **{stage}**: score={score}" + (f", confidence={conf}" if conf != "N/A" else ""))
        if not scored:
            lines.append("(no scores computed yet)")
        # 列出所有已完成阶段
        completed = [r.get("stage") for r in results if r.get("status") == "completed"]
        if completed:
            lines.append(f"- Completed: {', '.join(completed)}")
        lines.append("")

        lines.append("### 5) Pending Questions & Data Gaps")
        gaps = [r for r in results if r.get("content", "").find("[DATA_GAP]") >= 0]
        if gaps:
            for g in gaps:
                lines.append(f"- {g.get('stage','?')}: {g.get('content','')[:200]}")
        else:
            lines.append("(no data gaps flagged)")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_stage(results: list[dict], keywords: set) -> list[dict]:
        """按阶段关键词过滤结果。"""
        return [
            r
            for r in results
            if any(kw in r.get("stage", "").lower() for kw in keywords)
        ]

    @staticmethod
    def _empty_summary(query: str) -> str:
        return (
            f"# Compaction: {query}\n\n"
            f"### 1) Stock & Market Context\n(empty)\n\n"
            f"### 2) Technical Data Retrieved\n(empty)\n\n"
            f"### 3) Fundamental Data Retrieved\n(empty)\n\n"
            f"### 4) Analysis Progress & Scores\n(empty)\n\n"
            f"### 5) Pending Questions & Data Gaps\n(empty)\n"
        )
