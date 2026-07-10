# -*- coding: utf-8 -*-
r"""Markdown 报告生成器 — 保存完整的全链路分析报告到 data/reports/ 目录。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.output.formatter import (
    REC_EMOJI, REC_LABEL, PERSPECTIVE_EMOJI, PERSPECTIVE_NAME, PERSPECTIVE_TAG,
    CN, HR,
)

REPORTS_DIR = Path(__file__).parents[2] / "data" / "reports"


def save_markdown_report(result: Any) -> str:
    """保存完整 Markdown 报告，返回文件路径。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{result.symbol}_{result.name}_{ts}.md"
    filepath = REPORTS_DIR / filename

    lines = _build_report(result)
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return str(filepath)


def _build_report(result: Any) -> list[str]:
    """构建完整 Markdown 报告内容。"""
    verdict = getattr(result, "verdict", None)
    report = getattr(result, "report", None)
    lines: list[str] = []

    # 标题
    lines.append(f"# {result.name} ({result.symbol}) 全链路分析报告")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("> ⚠️ AI 分析结果，不构成投资建议。投资有风险，入市需谨慎。")
    lines.append("")

    # 核心结论
    lines.append("## 📌 核心结论")
    if verdict:
        rec = getattr(verdict, "recommendation", "HOLD")
        lines.append(f"- **{REC_EMOJI.get(rec, '⚪')} {REC_LABEL.get(rec, rec)}** | 评分 {verdict.score:.0f}/100 | 置信度 {verdict.confidence:.0%}")
    enforced = getattr(result, "enforced_verdict", None)
    if enforced:
        lines.append(f"- 💡 {enforced.get('one_line_conclusion', '')}")
        pr = enforced.get("price_range", {})
        if pr:
            lines.append(f"- 当前 {pr.get('current_price')} | 买入≤{pr.get('buy_below')} | 卖出≥{pr.get('sell_above')}")
    lines.append("")

    # 多维诊断
    lines.append("## 📊 多维诊断")
    if report:
        lines.append("| 维度 | 得分 | 性质 |")
        lines.append("|------|:---:|------|")
        rows = [
            ("宏观环境", getattr(report, "macro_score", 0), "事实"),
            ("价值因子", getattr(report, "value_score", 0), "解释"),
            ("质量因子", getattr(report, "quality_score", 0), "解释"),
            ("动量因子", getattr(report, "momentum_score", 0), "事实"),
            ("盈利修正", getattr(report, "earnings_revision_score", 0), "解释"),
            ("估值综合", getattr(report, "valuation_score", 0), "解释"),
            ("周期适配", getattr(report, "cycle_score", 0), "解释"),
            ("高管因子", getattr(report, "executive_score", 0), "解释"),
        ]
        for label, score, nature in rows:
            lines.append(f"| {label} | {score:.0f} | [{nature}] |")
        lines.append("")
        # 价格数据（事实性数据，非投资论点）
        _daily = getattr(report, "change_pct_1d", 0.0)
        _5day = getattr(report, "change_pct_5d", None)
        _ma_dev = getattr(report, "ma_deviation_pct", 0.0)
        _price_parts = [f"当日{_daily:+.1f}%"]
        if _5day is not None:
            _price_parts.append(f"5日{_5day:+.1f}%")
        _price_parts.append(f"MA60偏离{_ma_dev:+.1f}%")
        lines.append(f"- 📊 价格数据: {' | '.join(_price_parts)}")

        if getattr(report, "bull_case", ""):
            lines.append(f"- 🟢 看多: {report.bull_case}")
        if getattr(report, "bear_case", ""):
            lines.append(f"- 🔴 看空: {report.bear_case}")
        synthesis = getattr(report, "dimension_synthesis", "")
        if synthesis:
            lines.append(f"\n{synthesis}")
    lines.append("")

    # 军规审查
    doctrine = getattr(result, "doctrine_result", None)
    if doctrine and doctrine.get("rules"):
        lines.append("## 🏥 军规审查")
        lines.append(f"- 状态: {'✅ 通过' if doctrine.get('passed') else '⛔ 不通过'}")
        lines.append(f"- 阻断: {doctrine.get('blocked_count',0)} | 警告: {doctrine.get('warn_count',0)} | 信息: {doctrine.get('info_count',0)}")
        # 只列有问题的规则
        problem_rules = [r for r in doctrine["rules"] if r.get("status") in ("blocked", "warn")]
        if problem_rules:
            lines.append("\n**需关注**:")
            for r in problem_rules:
                lines.append(f"- [{r['id']}] {r['name']}: {r['description']}")
        lines.append("")

    # 准入 & 市场全景
    lines.append("## 🚪 准入检查 & 市场全景")
    gs = getattr(result, "gate_status", "UNKNOWN")
    lines.append(f"- 准入: {gs}")
    sent = getattr(result, "market_sentiment", None)
    if sent and isinstance(sent, dict):
        sl = str(sent.get("level", "NORMAL"))
        lines.append(f"- 市场情绪: {CN.get(sl, sl)} (评分 {sent.get('score','?')}/100)")
        if sent.get("northbound_insight"):
            lines.append(f"- 北向: {sent['northbound_insight']}")
        if sent.get("panic_arb_advice"):
            lines.append(f"- 恐慌套利: {sent['panic_arb_advice']}")
    lines.append("")

    # 四大师辩论
    pp = getattr(result, "debate_perspectives", None)
    dr = getattr(result, "debate_result", None)
    if pp and dr:
        lines.append("## 🎭 四大师辩论")
        lines.append(f"- 均分 {dr.get('avg_score',0):.2f}/5 | 分歧度 {dr.get('score_range',0):.2f} | {CN.get(str(dr.get('agreement_level','')), '?')}")
        if dr.get("tension_summary"):
            lines.append(f"- {dr['tension_summary']}")
        lines.append("")
        for key in ["buffett", "li_lu", "munger", "lynch"]:
            p = pp.get(key)
            if not p:
                continue
            score = p.get("score", 0)
            vi = p.get("verdict", "")
            lines.append(f"### {PERSPECTIVE_EMOJI[key]} {PERSPECTIVE_NAME[key]} ({PERSPECTIVE_TAG[key]})")
            lines.append(f"- 评分: {score:.1f}/5 | {vi}")
            if p.get("one_line_thesis"):
                lines.append(f"- 💡 {p['one_line_thesis']}")
            if p.get("methodology"):
                lines.append(f"- 📐 {p['methodology']}")
            for b in p.get("bull_points", [])[:3]:
                lines.append(f"- 🟢 {b}")
            for b in p.get("bear_points", [])[:3]:
                lines.append(f"- 🔴 {b}")
            if p.get("key_concern"):
                lines.append(f"- ⚠️ {p['key_concern']}")
            lines.append("")

    # Munger 思维模型
    mm_models = getattr(result, "mental_models", None)
    if mm_models:
        lines.append("## 🧠 Munger 思维模型")
        lines.append(f"匹配 {len(mm_models)} 个模型:")
        by_d: dict[str, list] = {}
        for m in mm_models:
            by_d.setdefault(m.get("discipline", "其他"), []).append(m)
        for disc, models in by_d.items():
            lines.append(f"\n### {disc} ({len(models)})")
            for m in models:
                lines.append(f"- **{m.get('name_cn', '?')}**: {m.get('description', '')[:100]}")
                reason = m.get("reason_for_match", "")
                if reason:
                    lines.append(f"  → {reason}")
                app = m.get("application_to_stock", "")
                if app:
                    lines.append(f"  📌 {app}")
        lines.append("")

    # Alpha + 博弈论
    alpha = getattr(result, "alpha_profile", None)
    gt = getattr(result, "game_theory_info", None)
    if alpha or gt:
        lines.append("## 🔬 辅助指标")
        if alpha:
            lines.append(f"- Alpha {getattr(alpha, 'alpha_score', 0):.0f}/100 | 一手性 {getattr(alpha, 'source', None).originality_score if getattr(alpha, 'source', None) else 0:.0f}/100")
            if getattr(alpha, "summary", ""):
                lines.append(f"- {alpha.summary}")
        if gt:
            lines.append(f"- 博弈论 {gt.get('score',0)}/100 | 拥挤 {gt.get('crowding_score',0)} | 杠杆 {gt.get('margin_score',0)}")
        lines.append("")

    # 综合裁决
    if verdict:
        lines.append("## ⚖️ 综合裁决")
        rec = getattr(verdict, "recommendation", "HOLD")
        lines.append(f"- **{REC_EMOJI.get(rec, '⚪')} {REC_LABEL.get(rec, rec)}** | 评分 {verdict.score:.0f}/100 | 置信度 {verdict.confidence:.0%}")
        dc = getattr(verdict, "dimension_contributions", None)
        if dc and isinstance(dc, dict):
            parts = [f"{k} {v:.1f}" for k, v in dc.items()]
            lines.append(f"- 构成: {' | '.join(parts)}")
        risks = getattr(verdict, "risks", []) or []
        if risks:
            lines.append("\n### 风险")
            for r in risks[:8]:
                if isinstance(r, dict):
                    lines.append(f"- {r.get('severity','?').upper()}: {r['text']}")
                else:
                    lines.append(f"- {r}")
        falsifiable = getattr(verdict, "falsifiable", []) or []
        if falsifiable:
            lines.append("\n### 可证伪条件")
            for f in falsifiable:
                lines.append(f"- {f}")
        lines.append("")

    # 仓位调度
    signal = getattr(result, "signal", None)
    pls = getattr(result, "position_limits_summary", None)
    lines.append("## 💰 仓位调度")
    if pls:
        cap = pls.get('total_capital', 0)
        if cap == 500000.0 and pls.get('_capital_is_default', True):
            cap_str = "⚠️未设置"
        elif cap >= 1e8:
            cap_str = f"{cap/1e8:.1f}亿"
        else:
            cap_str = f"{cap/1e4:.0f}万"
        lines.append(f"- 本金 {cap_str} | 单票≤{pls.get('max_single_pct',0):.0%} | 总仓位≤{pls.get('max_total_exposure',0):.0%}")
    if signal:
        lines.append(f"- 目标仓位 {getattr(signal, 'target_weight', 0):.1%}")
    sd = getattr(result, "sizing_detail", None)
    if sd:
        lines.append(f"- 方法: {CN.get(str(sd.get('method','')), str(sd.get('method','?')))}")
    lines.append("")

    # 风控执行
    risk = getattr(result, "risk", None)
    if risk:
        lines.append("## 🛡️ 风控执行")
        lines.append(f"- {'✅ 通过' if getattr(risk, 'passed', False) else '⚠️ 不通过'} | 调整后仓位 {getattr(risk, 'adjusted_weight', 0):.1%}")
        violations = getattr(risk, "violations", []) or []
        if violations:
            lines.append("\n**违规**:")
            for v in violations[:6]:
                lines.append(f"- {v}")
        lines.append("")

    # T+0
    t0 = getattr(result, "t0_result", None)
    if t0 and isinstance(t0, dict):
        lines.append("## ⏱️ T+0 日内时机")
        lines.append(f"- 建议: {t0.get('action', '?')} | 得分: {t0.get('score', 'N/A')}")
        if t0.get("multi_day_summary"):
            lines.append(f"- 多日趋势: {t0['multi_day_summary']}")
        if t0.get("gap_analysis"):
            lines.append(f"- 缺口: {t0['gap_analysis']}")
        if t0.get("overnight_risk"):
            lines.append(f"- 隔夜: {t0['overnight_risk']}")
        lines.append("")

    # 🔔 多通道资讯
    news_ctx = getattr(result, "news_context", None)
    if news_ctx and isinstance(news_ctx, dict) and news_ctx.get("total_items", 0) > 0:
        lines.append("## 🔔 多通道资讯")
        lines.append(f"- {news_ctx.get('summary', '')}")
        lines.append("")

        announcements = news_ctx.get("announcements", [])
        if announcements:
            lines.append("### 📋 公告")
            for item in announcements[:5]:
                title = item.get("title", "")[:80]
                date = item.get("date", "")[:10]
                lines.append(f"- [{date}] {title}")
            lines.append("")

        reports = news_ctx.get("research_reports", [])
        if reports:
            lines.append("### 📈 研报")
            for item in reports[:3]:
                title = item.get("title", "")[:80]
                content = item.get("content", "")[:120]
                lines.append(f"- **{title}**")
                if content:
                    lines.append(f"  {content}")
            lines.append("")

        news = news_ctx.get("news", [])
        if news:
            lines.append("### 📰 个股新闻")
            for item in news[:8]:
                title = item.get("title", "")[:80]
                date = item.get("date", "")[:10]
                source = item.get("source", "")
                lines.append(f"- [{date}] {title}  *({source})*")
            lines.append("")

        flash = news_ctx.get("flash_24x7", [])
        if flash:
            lines.append("### ⚡ 7×24 快讯")
            for item in flash[:5]:
                title = item.get("title", "")[:80]
                date = item.get("date", "")[:16]
                lines.append(f"- [{date}] {title}")
            lines.append("")

        l30 = news_ctx.get("last30days", [])
        if l30:
            lines.append("### 🗓️ 近30日资讯")
            for item in l30[:5]:
                title = item.get("title", "")[:80]
                date = item.get("date", "")[:10]
                lines.append(f"- [{date}] {title}")
            lines.append("")

    # 数据溯源
    all_cit = list(getattr(report, "source_citations", []) or [])
    if verdict:
        seen = {(c.provider, c.field) for c in all_cit}
        for c in (getattr(verdict, "source_citations", []) or []):
            if (c.provider, c.field) not in seen:
                all_cit.append(c)
    if all_cit:
        from collections import Counter
        tc = Counter(getattr(c, "source_tier", "?") for c in all_cit)
        nc = Counter(getattr(c, "nature", "?") for c in all_cit)
        lines.append("## 📊 数据溯源")
        lines.append(f"- 分级: T0:{tc.get('T0',0)} T1:{tc.get('T1',0)} T2:{tc.get('T2',0)} T3:{tc.get('T3',0)}")
        lines.append(f"- 性质: 事实:{nc.get('fact',0)} 解释:{nc.get('interpretation',0)} 推测:{nc.get('speculation',0)}")
        qs = [getattr(c, "quality_score", 0) for c in all_cit if not getattr(c, "is_data_gap", False)]
        avg = sum(qs) / len(qs) if qs else 0
        lines.append(f"- 质量: {avg:.2f}/1.0")
        lines.append("")

    lines.append("---")
    lines.append("*报告由白泽 (Baize) AI 投资决策系统自动生成*")
    return lines
