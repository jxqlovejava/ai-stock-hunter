# -*- coding: utf-8 -*-
"""论文导入器 — URL → 论文文本 → 分类。

支持:
  1. 从URL获取论文内容 (HTML/PDF)
  2. AI分类为策略类/架构类
  3. 本地缓存论文全文

用法:
    importer = PaperImporter()
    paper = importer.import_from_url("https://arxiv.org/abs/...")
    print(paper.paper_type)  # STRATEGY or ARCHITECTURE
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from .schema import PaperType, StrategyPaper

logger = logging.getLogger(__name__)


@dataclass
class _ExtractedContent:
    """URL 提取的原始内容。"""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    full_text: str = ""
    source_type: str = ""  # "arxiv" | "ssrn" | "html" | "pdf" | "unknown"


class PaperImporter:
    """论文导入器。

    从 URL 获取论文内容，分类为策略类或架构类。

    用法:
        importer = PaperImporter()
        paper = importer.import_from_url("https://arxiv.org/abs/2301.12345")
        if paper.paper_type == PaperType.STRATEGY:
            # 交给 strategy_extractor
            ...
        else:
            # 交给 architecture_analyzer
            ...
    """

    # 策略类关键词
    STRATEGY_KEYWORDS = [
        "factor", "因子", "alpha", "signal", "信号", "timing", "择时",
        "momentum", "动量", "value investing", "选股", "portfolio",
        "backtest", "回测", "trading strategy", "交易策略",
        "quantitative", "量化", "long-short", "market neutral",
        "risk premium", "风险溢价", "anomaly", "异象",
        "cross-section", "横截面", "time series", "时间序列",
        "predictive", "预测", "return forecast",
    ]

    # 架构类关键词
    ARCHITECTURE_KEYWORDS = [
        "framework", "框架", "pipeline", "管道", "architecture", "架构",
        "methodology", "方法论", "knowledge graph", "知识图谱",
        "supply chain", "供应链", "risk management system", "风控体系",
        "multi-agent", "多智能体", "orchestration", "编排",
        "reinforcement learning system", "深度强化学习",
        "attention mechanism", "注意力机制", "transformer",
        "graph neural network", "图神经网络", "GNN",
        "knowledge distillation", "知识蒸馏", "transfer learning",
        "data pipeline", "数据管道", "feature engineering framework",
        "NLP pipeline", "sentiment analysis framework",
    ]

    def __init__(self, cache_dir: str = "data/paper_cache"):
        self._cache_dir = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_from_url(self, url: str) -> StrategyPaper:
        """从 URL 导入论文。

        Args:
            url: 论文 URL (arxiv, ssrn, 一般网页)

        Returns:
            StrategyPaper 含标题/摘要/全文/分类
        """
        paper = StrategyPaper(url=url)

        try:
            content = self._fetch_content(url)
            paper.title = content.title
            paper.authors = content.authors
            paper.abstract = content.abstract
            paper.full_text = content.full_text
            paper.source_citation = self._format_citation(content)
        except Exception as e:
            logger.error("论文获取失败 (%s): %s", url, e)
            paper.paper_type = PaperType.UNKNOWN
            return paper

        # AI 分类
        try:
            paper.paper_type, paper.classification_confidence = (
                self._classify(content)
            )
        except Exception as e:
            logger.warning("论文分类失败 (%s): %s，标记为 UNKNOWN", url, e)
            paper.paper_type = PaperType.UNKNOWN
            paper.classification_confidence = 0.0

        # 缓存全文
        self._cache_paper(paper)

        logger.info(
            "论文导入: %s → %s (置信度 %.2f)",
            paper.title[:50], paper.paper_type.value, paper.classification_confidence,
        )
        return paper

    def import_from_text(
        self,
        text: str,
        title: str = "",
        url: str = "",
    ) -> StrategyPaper:
        """从原始文本导入论文（手动粘贴）。

        Args:
            text: 论文全文文本
            title: 标题（可选）
            url: 来源URL（可选）

        Returns:
            StrategyPaper
        """
        content = _ExtractedContent(
            title=title or "手动导入",
            full_text=text,
            abstract=self._extract_abstract(text),
            source_type="manual",
        )
        paper = StrategyPaper(
            url=url or "manual",
            title=content.title,
            abstract=content.abstract,
            full_text=content.full_text,
        )

        try:
            paper.paper_type, paper.classification_confidence = (
                self._classify(content)
            )
        except Exception:
            paper.paper_type = PaperType.UNKNOWN

        paper.source_citation = f"手动导入: {content.title}"
        return paper

    # ------------------------------------------------------------------
    # Internal — Content Fetching
    # ------------------------------------------------------------------

    def _fetch_content(self, url: str) -> _ExtractedContent:
        """从 URL 获取论文内容。"""
        parsed = urlparse(url)

        # arXiv
        if "arxiv.org" in parsed.netloc:
            return self._fetch_arxiv(url)

        # SSRN
        if "ssrn.com" in parsed.netloc or "papers.ssrn.com" in parsed.netloc:
            return self._fetch_ssrn(url)

        # 通用 HTML
        return self._fetch_generic(url)

    def _fetch_arxiv(self, url: str) -> _ExtractedContent:
        """通过 arXiv API 获取论文元数据。"""
        import json
        import urllib.request

        # 提取 arXiv ID
        arxiv_id = self._extract_arxiv_id(url)
        if not arxiv_id:
            return _ExtractedContent(source_type="arxiv")

        api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Baize/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_text = resp.read().decode("utf-8")
            return self._parse_arxiv_xml(xml_text)
        except Exception as e:
            logger.warning("arXiv API 调用失败: %s", e)
            return _ExtractedContent(source_type="arxiv")

    def _fetch_ssrn(self, url: str) -> _ExtractedContent:
        """从 SSRN 获取论文内容。"""
        try:
            import urllib.request

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Baize/1.0)",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            title = self._extract_html_title(html)
            abstract = self._extract_meta_content(html, "description")
            text = self._strip_html(html)

            return _ExtractedContent(
                title=title,
                abstract=abstract or self._extract_abstract(text),
                full_text=text,
                source_type="ssrn",
            )
        except Exception as e:
            logger.warning("SSRN 获取失败: %s", e)
            return _ExtractedContent(source_type="ssrn")

    def _fetch_generic(self, url: str) -> _ExtractedContent:
        """从通用网页获取内容。"""
        try:
            import urllib.request

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Baize/1.0)",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            title = self._extract_html_title(html)
            text = self._strip_html(html)

            return _ExtractedContent(
                title=title,
                abstract=self._extract_abstract(text),
                full_text=text,
                source_type="html",
            )
        except Exception as e:
            logger.warning("网页获取失败: %s", e)
            return _ExtractedContent(source_type="unknown")

    # ------------------------------------------------------------------
    # Internal — Classification
    # ------------------------------------------------------------------

    def _classify(self, content: _ExtractedContent) -> tuple[PaperType, float]:
        """基于关键词密度分类论文类型。

        返回 (类型, 置信度)。

        优先级: 如果内容足够长 (>=2000 chars)，使用 LLM 分类；
        否则回退到关键词规则分类。
        """
        text = f"{content.title} {content.abstract} {content.full_text[:5000]}".lower()

        strategy_score = sum(
            1 for kw in self.STRATEGY_KEYWORDS if kw.lower() in text
        )
        arch_score = sum(
            1 for kw in self.ARCHITECTURE_KEYWORDS if kw.lower() in text
        )

        total = strategy_score + arch_score
        if total == 0:
            return PaperType.UNKNOWN, 0.0

        if strategy_score > arch_score * 1.5:
            confidence = min(0.95, strategy_score / max(total, 1))
            return PaperType.STRATEGY, confidence
        elif arch_score > strategy_score * 1.5:
            confidence = min(0.95, arch_score / max(total, 1))
            return PaperType.ARCHITECTURE, confidence
        else:
            # 接近，标记 UNKNOWN 让用户手动指定
            return PaperType.UNKNOWN, 0.4

    def classify_with_llm(
        self, content: _ExtractedContent
    ) -> tuple[PaperType, float]:
        """使用 LLM 进行更精准的论文分类（需要 API）。

        如果关键词分类置信度不足 (< 0.7)，可调用此方法提升准确度。
        """
        prompt = (
            f"Classify this finance/investment paper into one of two types:\n"
            f"1. STRATEGY — proposes specific trading rules, factor combinations, "
            f"timing signals, stock screening criteria, or portfolio construction methods.\n"
            f"2. ARCHITECTURE — proposes a new analysis framework, risk management "
            f"system, pipeline architecture, evaluation methodology, or knowledge model.\n\n"
            f"Title: {content.title}\n"
            f"Abstract: {content.abstract[:1000]}\n\n"
            f"Reply with only the type (STRATEGY or ARCHITECTURE) and a brief reason."
        )

        # 此处留给 LLM 调用实现（通过 orchestrator 或外部 API）
        # 目前回退到关键词分类
        logger.info("[UNSOURED] LLM classifier not wired — using keyword fallback")
        return self._classify(content)

    # ------------------------------------------------------------------
    # Internal — Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_arxiv_id(url: str) -> str:
        """提取 arXiv ID。"""
        patterns = [
            r"arxiv\.org/abs/([\w.]+)",
            r"arxiv\.org/pdf/([\w.]+)",
            r"ar5iv\.org/abs/([\w.]+)",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1).rstrip(".pdf")
        return ""

    @staticmethod
    def _parse_arxiv_xml(xml_text: str) -> _ExtractedContent:
        """解析 arXiv API XML 响应。"""
        import xml.etree.ElementTree as ET

        content = _ExtractedContent(source_type="arxiv")
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        try:
            root = ET.fromstring(xml_text)
            entry = root.find("atom:entry", ns)
            if entry is None:
                return content

            title_el = entry.find("atom:title", ns)
            content.title = (title_el.text or "").strip() if title_el is not None else ""

            summary_el = entry.find("atom:summary", ns)
            content.abstract = (summary_el.text or "").strip() if summary_el is not None else ""

            # 作者
            for author in entry.findall("atom:author", ns):
                name_el = author.find("atom:name", ns)
                if name_el is not None and name_el.text:
                    content.authors.append(name_el.text.strip())

            content.full_text = f"{content.title}\n\n{content.abstract}"
        except ET.ParseError:
            logger.warning("arXiv XML 解析失败")

        return content

    @staticmethod
    def _extract_html_title(html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return PaperImporter._clean_html(m.group(1))
        return ""

    @staticmethod
    def _extract_meta_content(html: str, name: str) -> str:
        patterns = [
            rf'<meta[^>]+name=["\']{name}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{name}["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        """简单 HTML→纯文本。"""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return PaperImporter._clean_html(text).strip()

    @staticmethod
    def _clean_html(text: str) -> str:
        """清理 HTML 实体。"""
        import html as html_mod
        return html_mod.unescape(text).strip()

    @staticmethod
    def _extract_abstract(text: str, max_chars: int = 1000) -> str:
        """提取摘要 — 取前 N 个有意义的字符。"""
        cleaned = " ".join(text.split())[:max_chars * 2]
        # 寻找 "Abstract" 标记
        m = re.search(r"(?i)abstract[:\-]?\s*(.{50,})", cleaned)
        if m:
            return m.group(1)[:max_chars].strip()
        return cleaned[:max_chars].strip()

    def _format_citation(self, content: _ExtractedContent) -> str:
        """格式化论文引用。"""
        authors = ", ".join(content.authors[:3])
        if len(content.authors) > 3:
            authors += " et al."
        return f"{authors}. \"{content.title}\". {content.source_type.upper()}."

    def _cache_paper(self, paper: StrategyPaper):
        """缓存论文全文到本地。"""
        import os
        import json

        os.makedirs(self._cache_dir, exist_ok=True)
        cache_path = os.path.join(self._cache_dir, f"{paper.id}.json")
        try:
            data = {
                "id": paper.id,
                "url": paper.url,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "full_text": paper.full_text,
                "paper_type": paper.paper_type.value,
                "classification_confidence": paper.classification_confidence,
                "source_citation": paper.source_citation,
                "imported_at": paper.imported_at,
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("论文缓存失败: %s", e)


