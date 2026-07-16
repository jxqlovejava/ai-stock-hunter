# -*- coding: utf-8 -*-
"""Serenity 式瓶颈研究优先级打分卡。

移植自 https://github.com/muxuuu/serenity-skill `scripts/serenity_scorecard.py`（MIT）。
与 cyberagent 物理瓶颈身份分（OWNER/ADJACENT…）正交：
  - bottleneck_score = 是否控制物理卡点
  - research_priority_score = 是否值得优先研究

Usage:
  from src.industry.serenity_scorecard import score_card, score_from_ratings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

FACTOR_WEIGHTS: Dict[str, float] = {
    "demand_inflection": 15.0,
    "architecture_coupling": 10.0,
    "chokepoint_severity": 15.0,
    "supplier_concentration": 12.0,
    "expansion_difficulty": 12.0,
    "evidence_quality": 15.0,
    "valuation_disconnect": 11.0,
    "catalyst_timing": 10.0,
}

PENALTY_KEYS: Tuple[str, ...] = (
    "dilution_financing",
    "governance",
    "geopolitics",
    "liquidity",
    "hype_risk",
    "accounting_quality",
    "cyclicality",
    "alternative_design_risk",
)

PENALTY_MULTIPLIER = 2.0

# 裁决档（研究优先级，非买卖）
VERDICT_TOP = "Top research priority"
VERDICT_HIGH = "High research priority"
VERDICT_TRACK = "Worth tracking"
VERDICT_LOW = "Early lead or low priority"

VERDICT_CN = {
    VERDICT_TOP: "顶级研究优先",
    VERDICT_HIGH: "高研究优先",
    VERDICT_TRACK: "值得跟踪",
    VERDICT_LOW: "早期线索/低优先",
}


def _num_0_to_5(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number from 0 to 5") from exc
    if number < 0 or number > 5:
        raise ValueError(f"{label} must be from 0 to 5; got {number}")
    return number


@dataclass(frozen=True)
class SerenityScorecardResult:
    """研究优先级打分结果（0–100）。"""

    ticker: str = ""
    company: str = ""
    market: str = ""
    raw_factor_points: float = 0.0
    penalty_points: float = 0.0
    final_score: float = 0.0
    verdict: str = VERDICT_LOW
    factor_details: Dict[str, Dict[str, float]] = field(default_factory=dict)
    penalty_details: Dict[str, Dict[str, float]] = field(default_factory=dict)
    kill_switches: List[str] = field(default_factory=list)
    evidence: List[Dict[str, str]] = field(default_factory=list)

    @property
    def verdict_cn(self) -> str:
        return VERDICT_CN.get(self.verdict, self.verdict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "company": self.company,
            "market": self.market,
            "raw_factor_points": self.raw_factor_points,
            "penalty_points": self.penalty_points,
            "final_score": self.final_score,
            "verdict": self.verdict,
            "verdict_cn": self.verdict_cn,
            "factor_details": self.factor_details,
            "penalty_details": self.penalty_details,
            "kill_switches": list(self.kill_switches),
            "evidence": list(self.evidence),
        }


def score_to_verdict(final_score: float) -> str:
    if final_score >= 85:
        return VERDICT_TOP
    if final_score >= 70:
        return VERDICT_HIGH
    if final_score >= 55:
        return VERDICT_TRACK
    return VERDICT_LOW


def score_card(data: Mapping[str, Any]) -> SerenityScorecardResult:
    """对完整 scorecard JSON 对象打分。"""
    factors = data.get("factors", {}) or {}
    penalties = data.get("penalties", {}) or {}
    factor_details: Dict[str, Dict[str, float]] = {}
    total = 0.0

    for key, weight in FACTOR_WEIGHTS.items():
        rating = _num_0_to_5(factors.get(key, 0), f"factors.{key}")
        points = rating / 5.0 * weight
        factor_details[key] = {
            "rating": rating,
            "weight": weight,
            "points": round(points, 2),
        }
        total += points

    penalty_details: Dict[str, Dict[str, float]] = {}
    penalty_total = 0.0
    # 允许额外 penalty key，也确保标准 key 可缺省为 0
    all_penalty_keys = list(dict.fromkeys([*PENALTY_KEYS, *penalties.keys()]))
    for key in all_penalty_keys:
        rating = _num_0_to_5(penalties.get(key, 0), f"penalties.{key}")
        points = rating * PENALTY_MULTIPLIER
        penalty_details[key] = {"rating": rating, "points": round(points, 2)}
        penalty_total += points

    final_score = max(0.0, min(100.0, total - penalty_total))
    kill = data.get("what_could_weaken_view", data.get("kill_switches", [])) or []
    evidence = data.get("evidence", []) or []

    return SerenityScorecardResult(
        ticker=str(data.get("ticker", "") or ""),
        company=str(data.get("company", "") or ""),
        market=str(data.get("market", "") or ""),
        raw_factor_points=round(total, 2),
        penalty_points=round(penalty_total, 2),
        final_score=round(final_score, 2),
        verdict=score_to_verdict(final_score),
        factor_details=factor_details,
        penalty_details=penalty_details,
        kill_switches=[str(x).strip() for x in kill if str(x).strip()],
        evidence=[e for e in evidence if isinstance(e, dict)],
    )


def score_from_ratings(
    *,
    ticker: str = "",
    company: str = "",
    market: str = "A-share",
    factors: Optional[Mapping[str, float]] = None,
    penalties: Optional[Mapping[str, float]] = None,
    kill_switches: Optional[Sequence[str]] = None,
    evidence: Optional[Sequence[Mapping[str, str]]] = None,
) -> SerenityScorecardResult:
    """从分数字典构造并打分。"""
    payload: Dict[str, Any] = {
        "ticker": ticker,
        "company": company,
        "market": market,
        "factors": dict(factors or {}),
        "penalties": dict(penalties or {}),
        "what_could_weaken_view": list(kill_switches or []),
        "evidence": [dict(e) for e in (evidence or [])],
    }
    return score_card(payload)


def template_dict(
    ticker: str = "EXAMPLE",
    company: str = "Example Co",
    market: str = "A-share",
) -> Dict[str, Any]:
    """空模板，供 CLI/agent 填充。"""
    return {
        "ticker": ticker,
        "company": company,
        "market": market,
        "notes": "Replace ratings with 0-5 scores. 0 = absent, 5 = very strong.",
        "factors": {key: 0 for key in FACTOR_WEIGHTS},
        "penalties": {key: 0 for key in PENALTY_KEYS},
        "evidence": [
            {"claim": "", "source": "", "strength": "primary/media/analysis/social/rumor"}
        ],
        "what_could_weaken_view": ["", "", ""],
    }


def to_markdown(result: SerenityScorecardResult) -> str:
    title_bits = [result.ticker or "Unknown"]
    if result.company:
        title_bits.append(f"({result.company})")
    title = " ".join(title_bits)

    lines = [
        f"# Bottleneck scorecard: {title}",
        "",
        f"Market: {result.market}",
        f"Final score: **{result.final_score} / 100**",
        f"Verdict: **{result.verdict}** ({result.verdict_cn})",
        f"Raw factor points: {result.raw_factor_points}",
        f"Penalty points: {result.penalty_points}",
        "",
        "## Factors",
        "| Factor | Rating | Weight | Points |",
        "|---|---:|---:|---:|",
    ]
    for key, detail in result.factor_details.items():
        lines.append(
            f"| {key} | {detail['rating']} | {detail['weight']} | {detail['points']} |"
        )

    lines.extend(
        ["", "## Penalties", "| Penalty | Rating | Points |", "|---|---:|---:|"]
    )
    for key, detail in result.penalty_details.items():
        lines.append(f"| {key} | {detail['rating']} | {detail['points']} |")

    if result.kill_switches:
        lines.extend(["", "## What could weaken the view"])
        for item in result.kill_switches:
            lines.append(f"- {item}")

    if result.evidence:
        lines.extend(["", "## Evidence notes"])
        for ev in result.evidence:
            claim = (ev.get("claim") or "").strip()
            source = (ev.get("source") or "").strip()
            strength = (ev.get("strength") or "").strip()
            if claim or source:
                lines.append(f"- [{strength}] {claim} — {source}")

    lines.append("")
    return "\n".join(lines)


def estimate_from_bottleneck_type(
    bottleneck_type_value: str,
    *,
    evidence_quality: float = 3.0,
    hype_risk: float = 0.0,
) -> SerenityScorecardResult:
    """从 cyberagent 瓶颈类型启发式估算研究优先级（无完整因子时用）。"""
    presets: Dict[str, Dict[str, float]] = {
        "owner": {
            "demand_inflection": 4.0,
            "architecture_coupling": 4.0,
            "chokepoint_severity": 5.0,
            "supplier_concentration": 4.5,
            "expansion_difficulty": 4.5,
            "evidence_quality": evidence_quality,
            "valuation_disconnect": 3.0,
            "catalyst_timing": 3.0,
        },
        "adjacent": {
            "demand_inflection": 3.5,
            "architecture_coupling": 3.0,
            "chokepoint_severity": 3.5,
            "supplier_concentration": 3.0,
            "expansion_difficulty": 3.0,
            "evidence_quality": evidence_quality,
            "valuation_disconnect": 2.5,
            "catalyst_timing": 3.0,
        },
        "derivative": {
            "demand_inflection": 3.0,
            "architecture_coupling": 2.0,
            "chokepoint_severity": 2.0,
            "supplier_concentration": 2.0,
            "expansion_difficulty": 2.0,
            "evidence_quality": evidence_quality,
            "valuation_disconnect": 2.0,
            "catalyst_timing": 2.5,
        },
        "none": {
            "demand_inflection": 1.0,
            "architecture_coupling": 1.0,
            "chokepoint_severity": 1.0,
            "supplier_concentration": 1.0,
            "expansion_difficulty": 1.0,
            "evidence_quality": evidence_quality,
            "valuation_disconnect": 1.0,
            "catalyst_timing": 1.0,
        },
    }
    key = (bottleneck_type_value or "none").lower()
    factors = presets.get(key, presets["none"])
    penalties = {"hype_risk": hype_risk} if hype_risk else {}
    return score_from_ratings(factors=factors, penalties=penalties)
