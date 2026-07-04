# -*- coding: utf-8 -*-
"""操盘手法模式库（原则 4b）。

⚠️ 标注: HYPOTHESIS — 基于逻辑推演，Phase 2 需用龙虎榜数据做统计验证。

Evidence grade lifecycle:
  HYPOTHESIS → PRELIMINARY (≥5 samples) → CONFIRMED (≥20, p<0.05) → CALIBRATED (≥100, p<0.01)
  HYPOTHESIS → REFUTED (证伪)

Validation pipeline: playbook_validator.py
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field

from .players import PlayerType


@dataclass
class Playbook:
    """操盘手法模式定义。"""
    id: str
    name: str
    player_type: PlayerType
    trigger_conditions: list[str]
    execution_pattern: list[str]
    exit_conditions: list[str]
    price_impact_profile: str
    risk_to_follower: str
    evidence_level: str = "HYPOTHESIS"  # HYPOTHESIS 直到被龙虎榜数据验证
    evidence_upgraded_at: str = ""      # 证据升级时间戳
    validation_summary: str = ""        # 最近一次验证的摘要


TOP_3_PLAYBOOKS: list[Playbook] = [
    Playbook(
        id="limit_up_relay",
        name="涨停板接力/连板战法",
        player_type=PlayerType.HOT_MONEY,
        trigger_conditions=[
            "前一日有 ≥ 2 只同概念股涨停",
            "板块有政策利好催化",
            "标的流通市值 < 50 亿（便于控盘）",
            "标的无机构大幅持仓（避开对手盘）",
        ],
        execution_pattern=[
            "T日: 早盘快速封板 → 封单量逐步加大 → 锁死流动性",
            "T+1日: 高开 3-5% → 观察跟风盘 → 跟风弱则出货，强则继续封板",
            "T+2-3日: 连板 3-5 板 → 开始分批出货 → 散户接盘",
        ],
        exit_conditions=[
            "连板中断（开板）",
            "成交量异常放大（换手率 > 30%）",
            "监管问询函/停牌核查",
        ],
        price_impact_profile="快速拉升 3-5 板 → 高位放量 → 断崖下跌",
        risk_to_follower="散户在 T+2-3 追入，T+4-5 遭遇跌停出货，损失 15-30%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="institutional_clustering",
        name="机构抱团拉升",
        player_type=PlayerType.INSTITUTIONAL,
        trigger_conditions=[
            "卖方一致推荐某板块",
            "公募持仓集中度上升",
            "板块有长期增长叙事（新能源/消费升级/AI）",
            "新发基金大量建仓",
        ],
        execution_pattern=[
            "季度初: 公募按统一逻辑配置重仓股",
            "季度中: 净值上涨→基民申购→被动加仓→推升股价→净值再涨（正反馈）",
            "抱团瓦解: 业绩不及预期/政策转向/流动性收紧→集中减仓→相互踩踏",
        ],
        exit_conditions=[
            "龙头股业绩不及预期",
            "行业政策转向",
            "新发基金规模骤降（增量资金枯竭）",
        ],
        price_impact_profile="稳步推升（季度级）→ 加速冲顶 → 快速下跌（周级）",
        risk_to_follower="散户在抱团加速期追入，瓦解期无法及时离场，损失 20-40%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="national_team_bailout",
        name="国家队托底",
        player_type=PlayerType.NATIONAL_TEAM,
        trigger_conditions=[
            "沪深 300 连续大跌 > 10%",
            "北向资金持续大幅流出",
            "政策面释放维稳信号",
        ],
        execution_pattern=[
            "T日: 大盘暴跌 → 汇金/证金增持银行/蓝筹 ETF",
            "T+1-3日: 沪深300 ETF 成交量暴涨 3-5 倍",
            "T+1周: 指数止跌企稳 → 北向跟风回流",
            "T+1月: 国家队逐步退出 → 市场自行寻底",
        ],
        exit_conditions=[
            "沪深300 回到 60 日均线上方",
            "北向连续 5 日净流入",
            "汇金公告停止增持",
        ],
        price_impact_profile="急速止跌 → 缓慢反弹 → 二次探底（国家队退出后）",
        risk_to_follower="散户跟风国家队买入小盘股——国家队只买蓝筹，小盘股仍可能继续下跌",
        evidence_level="HYPOTHESIS",
    ),
]


def get_playbook_evidence_summary() -> str:
    """生成所有 playbook 的证据等级摘要。"""
    from collections import Counter
    counts = Counter(pb.evidence_level for pb in TOP_3_PLAYBOOKS)
    lines = [
        "# Playbook 证据等级",
        "",
        f"| Playbook | 类型 | 证据等级 |",
        f"|----------|------|---------|",
    ]
    for pb in TOP_3_PLAYBOOKS:
        icon = {"HYPOTHESIS": "🔬", "PRELIMINARY": "⚠️", "CONFIRMED": "✅",
                "CALIBRATED": "🎯", "REFUTED": "❌"}.get(pb.evidence_level, "❓")
        lines.append(f"| {icon} {pb.name} | {pb.player_type.value} | {pb.evidence_level} |")
    lines += [
        "",
        f"| 等级 | 数量 |",
        f"|------|------|",
    ]
    for grade in ["CALIBRATED", "CONFIRMED", "PRELIMINARY", "HYPOTHESIS", "REFUTED"]:
        if counts.get(grade, 0) > 0:
            lines.append(f"| {grade} | {counts[grade]} |")
    return "\n".join(lines)
