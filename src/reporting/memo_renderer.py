# -*- coding: utf-8 -*-
"""MemoRenderer — 投资备忘录渲染器。

8-step workflow:
  1. build_framework()    — 初始化模板上下文骨架
  2. collect_data()       — 从 stock_info / analysis / scenarios / dcf 填充数据
  3. build_scenarios()    — 处理三情景数据
  4. dcf_anchor()         — 处理 DCF 估值数据
  5. draft_memo()         — 撰写各叙事段落
  6. self_critique()      — 自评检查，追加说明和 caveats
  7. render_html()        — 使用 Jinja2 渲染 HTML
  8. final_report()       — 返回最终 HTML / 保存到文件
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE = "memo.html"


@dataclass
class MemoContext:
    """模板上下文数据容器。"""

    # ── 头信息 ─────────────────────────────────────────────
    title: str = ""
    subtitle: str = ""
    symbol: str = ""
    report_date: str = ""
    risk_profile: str = ""
    investment_goal: str = ""
    current_price: str = ""
    recommendation: str = ""

    # ── 公司概况 ───────────────────────────────────────────
    company_overview: str = ""
    business_summary: str = ""
    market_cap: str = ""
    pe_ttm: str = ""
    pb: str = ""
    roe: str = ""
    dividend_yield: str = ""
    sector: str = ""

    # ── 投资逻辑 ───────────────────────────────────────────
    thesis_bull: str = ""
    thesis_bear: str = ""
    alpha_rationale: str = ""

    # ── 财务分析 ───────────────────────────────────────────
    diagnosis_scores: list[dict] = field(default_factory=list)
    financial_highlights: list[dict] = field(default_factory=list)

    # ── DCF ────────────────────────────────────────────────
    dcf: dict = field(default_factory=dict)

    # ── 情景分析 ───────────────────────────────────────────
    scenarios: dict = field(default_factory=dict)

    # ── 风险 & 催化剂 ──────────────────────────────────────
    risks: list[str] = field(default_factory=list)
    risk_details: str = ""
    catalysts: list[str] = field(default_factory=list)

    # ── 仓位 ───────────────────────────────────────────────
    position: dict = field(default_factory=dict)

    # ── 监控 KPI ───────────────────────────────────────────
    monitoring_kpis: list[dict] = field(default_factory=list)

    # ── 附录 ───────────────────────────────────────────────
    self_critique_notes: str = ""
    data_caveats: list[str] = field(default_factory=list)
    generated_by: str = ""

    # ── 国际化 ─────────────────────────────────────────────
    i18n: dict = field(default_factory=dict)

    # ── 扩展数据 ───────────────────────────────────────────
    extras: dict = field(default_factory=dict)


class MemoRenderer:
    """投资备忘录渲染器。

    使用示例::

        renderer = MemoRenderer()
        renderer.build_framework(stock_info=info, analysis=analysis)
        renderer.collect_data()
        renderer.build_scenarios(scenarios)
        renderer.dcf_anchor(dcf)
        renderer.draft_memo()
        renderer.self_critique()
        html = renderer.render_html()
        renderer.save_memo(html, "/tmp/memo.html")
    """

    def __init__(
        self,
        template_name: str = DEFAULT_TEMPLATE,
        template_dir: str | Path = TEMPLATE_DIR,
    ):
        self.template_name = template_name
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.ctx: MemoContext = MemoContext()

    # ──────────────── 1. build_framework ────────────────

    def build_framework(
        self,
        stock_info: dict | None = None,
        analysis: dict | None = None,
    ) -> MemoRenderer:
        """初始化模板上下文骨架，填充基本头信息和容器结构。"""
        info = stock_info or {}
        anl = analysis or {}

        self.ctx.title = info.get("name", "投资备忘录")
        self.ctx.symbol = info.get("symbol", "")
        self.ctx.subtitle = info.get("exchange", "A 股") + " · 投资备忘录"
        self.ctx.report_date = self._fmt_date(anl.get("report_date"))
        self.ctx.risk_profile = anl.get("risk_profile", info.get("risk_profile", ""))
        self.ctx.investment_goal = anl.get("investment_goal", info.get("investment_goal", ""))
        self.ctx.current_price = self._fmt_price(info.get("current_price"))
        self.ctx.recommendation = anl.get("recommendation", info.get("recommendation", ""))
        self.ctx.generated_by = "白泽 (Baize) AI 投资决策系统"

        # 公司基础信息
        self.ctx.sector = info.get("sector", info.get("industry", ""))
        self.ctx.market_cap = self._fmt_market_cap(info.get("market_cap"))
        self.ctx.pe_ttm = self._fmt_num(info.get("pe_ttm"), 2)
        self.ctx.pb = self._fmt_num(info.get("pb"), 2)
        self.ctx.roe = self._fmt_pct(info.get("roe"))
        self.ctx.dividend_yield = self._fmt_pct(info.get("dividend_yield"))

        # 国际化占位
        self.ctx.i18n = {
            "company_overview": "公司概况",
            "investment_thesis": "投资逻辑",
            "financial_analysis": "财务分析",
            "dcf_valuation": "DCF 估值",
            "dcf_not_available": "暂无可用的 DCF 数据",
            "scenario_analysis": "情景分析",
            "scenario_not_available": "暂无可用的情景数据",
            "risk_factors": "风险因素",
            "risk_not_available": "暂无风险数据",
            "risk_disclaimer": "风险提示：以上为分析识别的关键风险因素，实际投资中可能存在未预见的风险。",
            "catalysts": "催化剂",
            "catalyst_not_available": "暂未识别出近期催化剂",
            "position_sizing": "仓位建议",
            "position_not_available": "暂未生成仓位建议",
            "monitoring_kpis": "监控指标",
            "kpi_not_available": "暂未设置监控指标",
            "appendix": "附录",
            "disclaimer": "免责声明：本报告由 AI 自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。",
        }

        return self

    # ──────────────── 2. collect_data ────────────────

    def collect_data(
        self,
        stock_info: dict | None = None,
        analysis: dict | None = None,
    ) -> MemoRenderer:
        """从传入数据字典填充上下文中的事实数据字段。"""
        if stock_info:
            self._merge_info(stock_info)
        if analysis:
            self._merge_analysis(analysis)
        return self

    # ──────────────── 3. build_scenarios ────────────────

    def build_scenarios(self, scenarios: dict | None = None) -> MemoRenderer:
        """处理三情景估值数据，格式化为展示结构。"""
        if not scenarios:
            return self

        current = scenarios.get("current_price") or self.ctx.current_price
        current_f = self._parse_float(current)

        def _make_scenario(key: str, label: str) -> dict | None:
            raw = scenarios.get(key) or scenarios.get(f"{key}_target")
            if raw is None:
                return None
            target = self._parse_float(raw)
            ret = ((target / current_f) - 1) * 100 if current_f else 0
            return {
                "target": self._fmt_price(target),
                "return_str": f"+{ret:.1f}%" if ret >= 0 else f"{ret:.1f}%",
                "probability_str": "",
                "raw_return": ret,
            }

        bull = _make_scenario("bull", "乐观")
        base = _make_scenario("base", "基准")
        bear = _make_scenario("bear", "悲观")

        # 概率
        prob_key = "probabilities"
        probs = scenarios.get(prob_key, {})
        if bull and probs.get("bull") is not None:
            bull["probability_str"] = f"概率 {probs['bull']:.0%}"
        if base and probs.get("base") is not None:
            base["probability_str"] = f"概率 {probs['base']:.0%}"
        if bear and probs.get("bear") is not None:
            bear["probability_str"] = f"概率 {probs['bear']:.0%}"

        scenario_data = {"bull": bull, "base": base, "bear": bear}
        scenario_data["narrative"] = scenarios.get("narrative", "")
        self.ctx.scenarios = scenario_data
        return self

    # ──────────────── 4. dcf_anchor ────────────────

    def dcf_anchor(self, dcf: dict | None = None) -> MemoRenderer:
        """处理 DCF 估值数据。"""
        if not dcf:
            return self

        projections = dcf.get("projections") or dcf.get("fcf_projections", [])
        formatted_projections: list[dict] = []
        for row in projections:
            formatted_projections.append(
                {k: self._fmt_num(v, 2) if isinstance(v, (int, float)) else v for k, v in row.items()}
            )

        current_price_f = self._parse_float(dcf.get("current_price") or self.ctx.current_price)
        fair_value_f = self._parse_float(dcf.get("fair_value"))
        margin = ((fair_value_f / current_price_f) - 1) * 100 if current_price_f and fair_value_f else None

        self.ctx.dcf = {
            "fair_value": self._fmt_price(fair_value_f),
            "margin_of_safety": round(margin, 1) if margin is not None else None,
            "wacc": self._fmt_num(dcf.get("wacc"), 2),
            "terminal_growth": self._fmt_num(dcf.get("terminal_growth"), 2),
            "fcf_growth_rate": self._fmt_num(dcf.get("fcf_growth_rate"), 2),
            "project_years": dcf.get("project_years", 10),
            "fcf_projections": formatted_projections,
            "methodology": dcf.get("methodology", ""),
        }
        return self

    # ──────────────── 5. draft_memo ────────────────

    def draft_memo(
        self,
        stock_info: dict | None = None,
        analysis: dict | None = None,
    ) -> MemoRenderer:
        """撰写投资备忘录核心叙事段落。"""
        info = stock_info or {}
        anl = analysis or {}

        # 公司概况 / 业务描述
        self.ctx.company_overview = (
            anl.get("company_overview")
            or info.get("company_overview")
            or info.get("description", "")
        )
        self.ctx.business_summary = (
            anl.get("business_summary")
            or info.get("business_summary", "")
        )

        # 多空逻辑
        self.ctx.thesis_bull = anl.get("bull_case") or info.get("bull_case", "")
        self.ctx.thesis_bear = anl.get("bear_case") or info.get("bear_case", "")
        self.ctx.alpha_rationale = anl.get("alpha_rationale") or info.get("alpha_rationale", "")

        # 多维评分
        raw_scores: list[tuple[str, float]] = [
            ("宏观环境", self._parse_float(anl.get("macro_score"))),
            ("价值因子", self._parse_float(anl.get("value_score"))),
            ("质量因子", self._parse_float(anl.get("quality_score"))),
            ("动量因子", self._parse_float(anl.get("momentum_score"))),
            ("盈利修正", self._parse_float(anl.get("earnings_revision_score"))),
            ("估值综合", self._parse_float(anl.get("valuation_score"))),
            ("周期适配", self._parse_float(anl.get("cycle_score"))),
            ("高管因子", self._parse_float(anl.get("executive_score"))),
        ]
        score_items = [
            {"label": label, "score": min(max(round(s), 0), 100)}
            for label, s in raw_scores
            if s is not None and not (label == "盈利修正" and s == 0 and anl.get("earnings_revision_score") is None)
        ]
        self.ctx.diagnosis_scores = score_items

        # 财务亮点（从 financial_highlights 或 analysis 中提取）
        fin_h = anl.get("financial_highlights") or info.get("financial_highlights", [])
        if fin_h:
            self.ctx.financial_highlights = fin_h

        # 风险 & 催化剂
        self.ctx.risks = anl.get("risks") or info.get("risks", [])
        if not self.ctx.risks:
            self.ctx.risks = anl.get("risk_factors") or info.get("risk_factors", [])
        self.ctx.risk_details = anl.get("risk_details") or info.get("risk_details", "")
        self.ctx.catalysts = anl.get("catalysts") or info.get("catalysts", [])

        # 仓位
        pos = anl.get("position") or info.get("position_sizing", {})
        if pos:
            self.ctx.position = {
                "suggested_weight": self._fmt_pct(pos.get("suggested_weight") or pos.get("target_weight")),
                "kelly_fraction": self._fmt_pct(pos.get("kelly_fraction") or pos.get("kelly")),
                "stop_loss": self._fmt_price(pos.get("stop_loss")),
                "target_price": self._fmt_price(pos.get("target_price")),
                "max_position_pct": self._fmt_pct(pos.get("max_position_pct") or pos.get("max_single")),
                "confidence": self._fmt_pct(pos.get("confidence")),
                "rationale": pos.get("rationale") or pos.get("reason", ""),
            }

        # 监控 KPI
        kpis = anl.get("monitoring_kpis") or info.get("monitoring_kpis", [])
        if kpis:
            self.ctx.monitoring_kpis = kpis
        else:
            # 默认 KPI
            self.ctx.monitoring_kpis = [
                {"label": "PE (TTM)", "value": self.ctx.pe_ttm},
                {"label": "PB", "value": self.ctx.pb},
                {"label": "ROE", "value": self.ctx.roe},
                {"label": "股息率", "value": self.ctx.dividend_yield},
            ]
            if self.ctx.dcf.get("margin_of_safety") is not None:
                self.ctx.monitoring_kpis.append(
                    {"label": "安全边际", "value": f"{self.ctx.dcf['margin_of_safety']}%"}
                )

        return self

    # ──────────────── 6. self_critique ────────────────

    def self_critique(
        self,
        stock_info: dict | None = None,
        analysis: dict | None = None,
    ) -> MemoRenderer:
        """自评检查：补充数据质量说明、缺失标记和限制。"""
        anl = analysis or {}

        notes: list[str] = []
        caveats: list[str] = []

        # 置信度
        confidence = anl.get("confidence") or anl.get("report_confidence")
        if confidence is not None:
            c = float(confidence)
            if c < 0.5:
                notes.append(f"整体置信度偏低 ({c:.0%})，建议结合更多来源交叉验证。")
            elif c < 0.7:
                notes.append(f"中等置信度 ({c:.0%})，部分维度数据可能需要进一步验证。")
            else:
                notes.append(f"置信度 {c:.0%}，数据质量良好。")

        # 数据缺口
        data_gaps = anl.get("data_gaps") or []
        if data_gaps:
            caveats.append(f"存在 {len(data_gaps)} 个数据缺口: {', '.join(data_gaps[:5])}")
            if len(data_gaps) > 5:
                caveats[-1] += f" 等 {len(data_gaps)} 项"

        # 溯源信息
        source_tiers = anl.get("source_tier_counts") or {}
        if source_tiers:
            parts = [f"{t}:{c}" for t, c in sorted(source_tiers.items()) if c > 0]
            caveats.append(f"数据来源分级: {'  '.join(parts)}")

        # 推测标记
        spec_count = anl.get("speculation_count", 0)
        if spec_count and spec_count > 0:
            caveats.append(f"含 {spec_count} 处推测数据，仅供参考不纳入评分。")

        # 过期数据
        staleness = anl.get("data_staleness")
        if staleness:
            caveats.append(f"部分数据新鲜度不足 ({staleness})，已下调对应维度权重。")

        # 限制声明
        if not data_gaps and not source_tiers and not staleness:
            caveats.insert(0, "数据新鲜度在有效期内，来源可信度良好。")

        self.ctx.self_critique_notes = "\n".join(notes) if notes else ""
        self.ctx.data_caveats = caveats

        return self

    # ──────────────── 7. render_html ────────────────

    def render_html(self) -> str:
        """使用 Jinja2 渲染完整 HTML 备忘录。"""
        template = self.env.get_template(self.template_name)
        return template.render(context=self.ctx)

    # ──────────────── 8. final_report ────────────────

    def final_report(self, output_path: str | Path | None = None) -> str:
        """生成最终报告，可选保存到文件。"""
        html = self.render_html()
        if output_path:
            self.save_memo(html, output_path)
        return html

    # ──────────────── 全链路快捷方法 ────────────────

    def run(
        self,
        stock_info: dict,
        analysis: dict,
        scenarios: dict | None = None,
        dcf: dict | None = None,
        output_path: str | Path | None = None,
    ) -> str:
        """全链路执行：framework → collect → scenarios → dcf → draft → critique → render → save。"""
        self.build_framework(stock_info, analysis)
        self.collect_data(stock_info, analysis)
        self.build_scenarios(scenarios)
        self.dcf_anchor(dcf)
        self.draft_memo(stock_info, analysis)
        self.self_critique(stock_info, analysis)
        return self.final_report(output_path)

    # ──────────────── 持久化 ────────────────

    @staticmethod
    def save_memo(html: str, output_path: str | Path) -> Path:
        """将 HTML 保存到文件。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        logger.info("Memo saved to %s", path.resolve())
        return path.resolve()

    # ──────────────── 内部辅助 ────────────────

    def _merge_info(self, info: dict) -> None:
        """合并 stock_info 中的已知字段。"""
        for key, dest in [
            ("company_overview", "company_overview"),
            ("business_summary", "business_summary"),
            ("description", "company_overview"),
            ("bull_case", "thesis_bull"),
            ("bear_case", "thesis_bear"),
        ]:
            val = info.get(key)
            if val and not getattr(self.ctx, dest):
                setattr(self.ctx, dest, val)

    def _merge_analysis(self, anl: dict) -> None:
        """合并 analysis 中的已知字段。"""
        for key, dest in [
            ("company_overview", "company_overview"),
            ("business_summary", "business_summary"),
            ("bull_case", "thesis_bull"),
            ("bear_case", "thesis_bear"),
            ("alpha_rationale", "alpha_rationale"),
            ("risk_details", "risk_details"),
        ]:
            val = anl.get(key)
            if val and not getattr(self.ctx, dest):
                setattr(self.ctx, dest, val)

    # ──────────────── 格式化辅助 ────────────────

    @staticmethod
    def _fmt_date(val: Any) -> str:
        if not val:
            return datetime.now().strftime("%Y-%m-%d")
        if isinstance(val, (datetime, date)):
            return val.strftime("%Y-%m-%d")
        return str(val)[:10]

    @staticmethod
    def _fmt_price(val: Any) -> str:
        if val is None or val == "":
            return ""
        try:
            f = float(val)
            if f >= 1000:
                return f"{f:,.2f}"
            if f >= 1:
                return f"{f:.2f}"
            return f"{f:.4f}"
        except (ValueError, TypeError):
            return str(val)

    @staticmethod
    def _fmt_num(val: Any, decimals: int = 2) -> str:
        if val is None or val == "":
            return ""
        try:
            f = float(val)
            return f"{f:.{decimals}f}"
        except (ValueError, TypeError):
            return str(val)

    @staticmethod
    def _fmt_pct(val: Any) -> str:
        if val is None or val == "":
            return ""
        try:
            f = float(val)
            if abs(f) < 10:
                return f"{f * 100:.1f}%" if f < 1 else f"{f:.1f}%"
            return f"{f:.1f}%"
        except (ValueError, TypeError):
            s = str(val)
            return s if s.endswith("%") else f"{s}%"

    @staticmethod
    def _fmt_market_cap(val: Any) -> str:
        if val is None or val == "":
            return ""
        try:
            f = float(val)
            if f >= 1e12:
                return f"{f / 1e12:.2f} 万亿"
            if f >= 1e8:
                return f"{f / 1e8:.2f} 亿"
            if f >= 1e4:
                return f"{f / 1e4:.2f} 万"
            return f"{f:.2f}"
        except (ValueError, TypeError):
            return str(val)

    @staticmethod
    def _parse_float(val: Any) -> float | None:
        if val is None or val == "":
            return None
        try:
            if isinstance(val, str):
                val = val.replace(",", "").replace(" ", "")
            return float(val)
        except (ValueError, TypeError):
            return None
