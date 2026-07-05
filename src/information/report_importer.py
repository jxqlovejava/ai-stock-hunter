"""Research report importer — PDF/Text upload, structured parsing, NLP summary.

Supports: PDF upload (via PyMuPDF/pdfplumber), plain text paste.
Auto-extracts: title, stock codes, rating, target price, analyst, brokerage.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_DIR = Path.home() / ".ai-stock-hunter" / "reports"


@dataclass
class ImportedReport:
    """Structured research report from import."""

    report_id: str = ""  # UUID
    title: str = ""
    abstract: str = ""
    stock_codes: list[str] = field(default_factory=list)
    stock_names: list[str] = field(default_factory=list)
    rating: str = ""  # "买入" / "增持" / "中性" / "减持" / "卖出"
    target_price: Optional[float] = None
    current_price: Optional[float] = None
    analyst: str = ""
    brokerage: str = ""
    report_date: str = ""
    source: str = "manual"  # "pdf_upload" / "text_paste" / "api"
    raw_text: str = ""
    nlp_summary: str = ""
    confidence: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)


class ReportImporter:
    """Import and parse research reports from PDF or plain text.

    Extracts structured metadata via regex patterns:
    - Stock codes: (000001) / (600519.SH)
    - Ratings: 买入/增持/中性/减持/卖出
    - Target prices: 目标价 XX元 / TP XX
    - Brokerage/analyst names
    """

    # Stock code patterns
    STOCK_CODE_PATTERNS = [
        re.compile(r"[（(](\d{6})[)）]"),  # (000001) or （000001）
        re.compile(r"(\d{6})\.[A-Z]{2}"),  # 600519.SH
    ]

    # Rating keyword mapping
    RATING_KEYWORDS: dict[str, list[str]] = {
        "买入": ["买入", "强烈推荐", "推荐", "buy", "overweight"],
        "增持": ["增持", "跑赢行业", "跑赢大市", "outperform", "accumulate"],
        "中性": ["中性", "持有", "观望", "neutral", "hold", "equal-weight"],
        "减持": ["减持", "跑输行业", "跑输大市", "underperform", "reduce"],
        "卖出": ["卖出", "sell", "underweight"],
    }

    # Target price patterns
    TARGET_PRICE_PATTERNS = [
        re.compile(r"目标价[格]?[：:]\s*([\d.]+)\s*元"),
        re.compile(r"目标价[格]?\s*([\d.]+)\s*元"),
        re.compile(r"TP[：:]\s*([\d.]+)"),
        re.compile(r"目标\s*([\d.]+)\s*元"),
    ]

    # Current price patterns
    CURRENT_PRICE_PATTERNS = [
        re.compile(r"现价[：:]\s*([\d.]+)\s*元"),
        re.compile(r"当前价[格]?[：:]\s*([\d.]+)\s*元"),
        re.compile(r"收盘价[：:]\s*([\d.]+)\s*元"),
    ]

    # Brokerage patterns
    BROKERAGE_PATTERNS = [
        re.compile(r"([一-龥]{2,6}证券(?:股份)?(?:有限公司)?)"),
        re.compile(r"([一-龥]{2,6}(?:研究|金融|资本))"),
    ]

    def __init__(self, storage_dir: Optional[Path] = None):
        self._storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_pdf(self, filepath: Path) -> Optional[ImportedReport]:
        """Parse a PDF research report file.

        Requires PyMuPDF (fitz) or pdfplumber for text extraction.
        Falls back to plain text read if neither is available.
        """
        text = self._extract_pdf_text(filepath)
        if not text:
            logger.warning("Could not extract text from PDF: %s", filepath)
            return None

        report = self.import_text(text, source="pdf_upload")
        report.title = filepath.stem[:100] or report.title
        return report

    def import_text(self, text: str, source: str = "manual") -> ImportedReport:
        """Parse pasted/uploaded text content into structured report."""
        import uuid

        report = ImportedReport(
            report_id=str(uuid.uuid4())[:8],
            source=source,
            raw_text=text[:10000],  # truncate for storage
            created_at=datetime.now(),
        )

        # Extract metadata
        report.title = self._extract_title(text)
        report.stock_codes = self._extract_stock_codes(text)
        report.rating = self._extract_rating(text)
        report.target_price = self._extract_target_price(text)
        report.current_price = self._extract_current_price(text)
        report.brokerage = self._extract_brokerage(text)
        report.report_date = self._extract_date(text)

        # Generate summary
        report.nlp_summary = self._generate_summary(report.raw_text)

        # Save
        self.save(report)

        return report

    def save(self, report: ImportedReport) -> str:
        """Save report as JSON. Returns report_id."""
        if not report.report_id:
            import uuid
            report.report_id = str(uuid.uuid4())[:8]

        filepath = self._storage_dir / f"{report.report_id}.json"
        data = {
            "report_id": report.report_id,
            "title": report.title,
            "abstract": report.abstract,
            "stock_codes": report.stock_codes,
            "stock_names": report.stock_names,
            "rating": report.rating,
            "target_price": report.target_price,
            "current_price": report.current_price,
            "analyst": report.analyst,
            "brokerage": report.brokerage,
            "report_date": report.report_date,
            "source": report.source,
            "raw_text": report.raw_text,
            "nlp_summary": report.nlp_summary,
            "confidence": report.confidence,
            "created_at": report.created_at.isoformat(),
        }
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Report saved: %s → %s", report.report_id, filepath)
        return report.report_id

    def load(self, report_id: str) -> Optional[ImportedReport]:
        """Load a saved report by ID."""
        filepath = self._storage_dir / f"{report_id}.json"
        if not filepath.exists():
            return None
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return ImportedReport(
            report_id=data.get("report_id", ""),
            title=data.get("title", ""),
            abstract=data.get("abstract", ""),
            stock_codes=data.get("stock_codes", []),
            stock_names=data.get("stock_names", []),
            rating=data.get("rating", ""),
            target_price=data.get("target_price"),
            current_price=data.get("current_price"),
            analyst=data.get("analyst", ""),
            brokerage=data.get("brokerage", ""),
            report_date=data.get("report_date", ""),
            source=data.get("source", ""),
            raw_text=data.get("raw_text", ""),
            nlp_summary=data.get("nlp_summary", ""),
            confidence=data.get("confidence", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )

    def list_reports(self) -> list[dict]:
        """List all saved reports with metadata summaries."""
        results = []
        for f in sorted(self._storage_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "report_id": data.get("report_id", f.stem),
                    "title": data.get("title", "")[:80],
                    "stock_codes": data.get("stock_codes", []),
                    "rating": data.get("rating", ""),
                    "brokerage": data.get("brokerage", ""),
                    "report_date": data.get("report_date", ""),
                    "created_at": data.get("created_at", ""),
                })
            except Exception:
                continue
        return results

    def search_by_stock(self, code: str) -> list[ImportedReport]:
        """Find all reports mentioning a specific stock code."""
        results = []
        for f in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if code in data.get("stock_codes", []):
                    results.append(self.load(data.get("report_id", f.stem)) or ImportedReport())
            except Exception:
                continue
        return [r for r in results if r.report_id]

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_title(self, text: str) -> str:
        """Extract report title from first non-empty line."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return ""
        # First meaningful line is usually the title
        for line in lines[:5]:
            if len(line) > 5 and not line.startswith(("免责", "声明", "重要", "本报告")):
                return line[:200]
        return lines[0][:200] if lines else ""

    def _extract_stock_codes(self, text: str) -> list[str]:
        """Extract A-share stock codes from text."""
        codes: set[str] = set()
        for pattern in self.STOCK_CODE_PATTERNS:
            for match in pattern.finditer(text):
                code = match.group(1)
                # Validate A-share code range
                if code.startswith(("6", "0", "3", "8", "4")):
                    codes.add(code)
        return sorted(codes)

    def _extract_rating(self, text: str) -> str:
        """Extract investment rating from text."""
        text_upper = text.upper()
        for rating, keywords in self.RATING_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_upper.lower():
                    return rating
        return ""

    def _extract_target_price(self, text: str) -> Optional[float]:
        """Extract target price from text."""
        for pattern in self.TARGET_PRICE_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 10000:  # reasonable range
                        return price
                except ValueError:
                    continue
        return None

    def _extract_current_price(self, text: str) -> Optional[float]:
        """Extract current market price from text."""
        for pattern in self.CURRENT_PRICE_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 10000:
                        return price
                except ValueError:
                    continue
        return None

    def _extract_brokerage(self, text: str) -> str:
        """Extract brokerage name from text."""
        for pattern in self.BROKERAGE_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return ""

    def _extract_date(self, text: str) -> str:
        """Extract report date from text."""
        date_patterns = [
            re.compile(r"(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2})\s*日?"),
            re.compile(r"(\d{4}\.\d{1,2}\.\d{1,2})"),
        ]
        for pattern in date_patterns:
            match = pattern.search(text)
            if match:
                # Normalize to YYYY-MM-DD
                raw = match.group(1)
                raw = re.sub(r"[年月]", "-", raw)
                raw = re.sub(r"[日/.]", "", raw)
                raw = re.sub(r"\s+", "", raw)
                parts = [p for p in re.split(r"[-/]", raw) if p]
                if len(parts) == 3:
                    return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        return ""

    @staticmethod
    def _generate_summary(text: str) -> str:
        """Generate a simple extractive summary from report text.

        For full NLP summarization, use the KeywordNLPProcessor pipeline.
        """
        text = text[:5000]  # limit input
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return ""

        summary_parts: list[str] = []

        # First sentence of first paragraph as lead
        for line in lines[:10]:
            if len(line) > 10 and not line.startswith(("免责", "声明", "本报告", "证券分析师")):
                sentences = re.split(r"[。！？!?]", line)
                for s in sentences:
                    s = s.strip()
                    if len(s) > 10:
                        summary_parts.append(s)
                        break
                if summary_parts:
                    break

        # Key data points
        data_patterns = [
            (r"EPS[：:]\s*([\d.]+)", "EPS预测"),
            (r"PE[：:]\s*([\d.]+)倍", "PE估值"),
            (r"营收[增长增速]*[：:]\s*([\d.]+)%?", "营收增长"),
            (r"净利润[增长增速]*[：:]\s*([\d.]+)%?", "净利润增长"),
        ]
        for pattern, label in data_patterns:
            m = re.search(pattern, text)
            if m:
                summary_parts.append(f"[{label}: {m.group(0)}]")

        return "；".join(summary_parts[:5]) if summary_parts else text[:200]

    # ------------------------------------------------------------------
    # PDF text extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pdf_text(filepath: Path) -> str:
        """Extract text from a PDF file."""
        # Try PyMuPDF (fitz) first
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(filepath))
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("PyMuPDF extraction failed: %s", e)

        # Try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(str(filepath)) as pdf:
                text = ""
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            return text.strip()
        except ImportError:
            pass
        except Exception as e:
            logger.warning("pdfplumber extraction failed: %s", e)

        # Fallback: try reading as plain text
        try:
            return filepath.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass

        return ""
