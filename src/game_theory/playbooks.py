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


TOP_PLAYBOOKS: list[Playbook] = [
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
    # ── 庄家操盘手法 (Phase 10: Manipulation Detection) ──
    Playbook(
        id="lure_bull_dump",
        name="诱多出货 (虚假突破→高位放量→跳水)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "盘中突破前 3 日高点 +2%",
            "突破时量比 > 2.0 (放量假突破)",
            "突破后 30 分钟内价格回落 > 1.5%",
            "回落时成交量逐步萎缩 (跟风盘衰竭)",
        ],
        execution_pattern=[
            "T 日 10:00-11:00: 快速拉升突破关键阻力位，制造突破假象",
            "T 日 11:00-13:30: 高位横盘，散户追入→庄家分批出货",
            "T 日 13:30-15:00: 量能不济→价格跳水→收盘接近日内低点",
            "T+1 日: 低开 1-2%，昨日追高散户全部被套",
        ],
        exit_conditions=[
            "分时量价背离 (价格新高但量能递减)",
            "大单卖出 > 大单买入 × 2",
            "收盘价跌破日内均价",
        ],
        price_impact_profile="假突破后 3 日内跌幅 5-10%，追高者亏损 15-20%",
        risk_to_follower="突破追入→被高位套牢→次日低开无法 T+0 止损→亏损 15-30%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="lure_bear_accumulate",
        name="诱空吸筹 (砸盘破位→散户割肉→快速拉回)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "盘中快速下跌 > 3%，跌破近期支撑位",
            "下跌时量比 > 1.5 (放量砸盘制造恐慌)",
            "30 分钟内价格 V 型反弹 > 2%",
            "反弹时成交量放大 (庄家低位吸货)",
        ],
        execution_pattern=[
            "T 日 10:00-10:30: 集中抛售砸盘，跌破关键支撑位",
            "T 日 10:30-11:00: 散户恐慌割肉→庄家在低位接货",
            "T 日 11:00-14:00: 缓慢拉回→做 T+0 的散户被迫追回",
            "T 日 14:00-15:00: 回到开盘价附近或小幅收涨",
        ],
        exit_conditions=[
            "V 型低点成交量 > 前 5 日均量的 1.5 倍 (吸筹完成)",
            "反弹时北向/机构资金未跟进 (仅庄家行为)",
        ],
        price_impact_profile="砸盘当日 V 型反转，3-5 日后开始拉升",
        risk_to_follower="恐慌割肉在最低点→错失后续反弹→踏空损失 10-15%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="wash_trade_pump",
        name="对倒拉升 (自买自卖→量价齐升假象)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "量比 > 3.0 (异常放量)",
            "价格变动幅度 < 0.5% (放量但价格基本不动)",
            "买卖盘口均衡，无明确方向",
            "持续 > 30 分钟",
        ],
        execution_pattern=[
            "T 日: 庄家控制多个账户，A 账户卖→B 账户买，制造虚假成交量",
            "T 日: 分时图呈现「锯齿状」窄幅震荡，量能忽大忽小",
            "T 日尾盘: 突然出现方向性拉升，吸引技术派跟风",
            "T+1-3 日: 散户跟风进场→庄家反向出货",
        ],
        exit_conditions=[
            "盘中突然出现大单卖出 (> 50 万股/分钟) 打破对倒平衡",
            "尾盘拉升 > 3% (诱多信号)",
        ],
        price_impact_profile="对倒期间价格窄幅震荡→拉升 3-5%→出货后跌回起点",
        risk_to_follower="被虚假量价信号欺骗→跟风追入→庄家出货后损失 10-20%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="shakeout",
        name="洗盘震仓 (急跌→制造恐慌→低位吸筹)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "盘中急跌 5-8% (远超正常波动)",
            "急跌发生在 10:00-11:00 (早盘恐慌时段)",
            "急跌后 V 型反弹 > 3%",
            "下跌时放量 (散户出逃)，反弹时缩量 (庄家锁仓)",
        ],
        execution_pattern=[
            "T 日开盘: 庄家集中砸盘，制造技术破位形态",
            "T 日 10:00-11:00: 散户止损盘涌出→庄家在低位接货",
            "T 日 13:00-15:00: 缓慢回升→做短线的被迫追回",
            "T+1-3 日: 股价回到洗盘前水平→被洗出的散户后悔",
        ],
        exit_conditions=[
            "日线收长下影线 (锤子线形态)",
            "急跌后 2 小时内未破新低",
            "北向资金当日净流入 (庄家 + 北向合力)",
        ],
        price_impact_profile="急跌 5-8%→当日 V 型反弹→3 日内回到洗盘前价格",
        risk_to_follower="被震仓吓出→在最低点附近割肉→踏空反弹 8-15%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="fishing_line",
        name="分时钓鱼线 (直线拉升→缓慢阴跌出货)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "15 分钟内拉升 > 5% (几乎直线拉升)",
            "拉升后 60 分钟内持续阴跌，跌幅 > 拉升幅度的 50%",
            "阴跌过程中成交量逐步萎缩",
            "全天收长上影线",
        ],
        execution_pattern=[
            "T 日 10:00-10:15: 快速直线拉升 5-8%，吸引跟风盘",
            "T 日 10:15-11:30: 庄家开始慢慢出货，价格逐步阴跌",
            "T 日 13:00-15:00: 继续阴跌，收盘接近日内均价以下",
            "T+1 日: 低开 2-3%，昨日追高者无机会止损",
        ],
        exit_conditions=[
            "拉升后 15 分钟内未创新高 (出货确认)",
            "阴跌过程中反弹无力 (< 拉升幅度的 20%)",
            "收盘价 < 日内均价",
        ],
        price_impact_profile="日内高点→收盘跌 3-5%→次日低开 2-3%→追高者 2 日亏损 8-12%",
        risk_to_follower="拉升时追入→当日被套→次日低开无法 T+0 止损→累计亏损 10-15%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="closing_manipulation",
        name="尾盘偷袭 (14:50 后异常拉升/砸盘)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "14:50-15:00 区间涨幅 > 2% 或跌幅 > 2%",
            "尾盘 10 分钟成交量 > 全日成交量的 15%",
            "尾盘方向与全天主要趋势相反",
            "次日开盘方向与尾盘相反 (操纵确认)",
        ],
        execution_pattern=[
            "T 日 14:50-15:00: 庄家集中资金拉升/砸盘，操纵收盘价",
            "拉升目的: 美化 K 线形态，次日高开出货",
            "砸盘目的: 打压股价以便次日低价吸筹",
            "T+1 日: 股价反向运行→庄家反向操作",
        ],
        exit_conditions=[
            "尾盘异动后次日反向跳空 > 1%",
            "尾盘拉升时大单买入集中度 > 80% (单一账户操纵)",
        ],
        price_impact_profile="尾盘异动 2-3%→次日反向 1.5-2.5%→异动方向不可持续",
        risk_to_follower="尾盘追涨→次日低开被套 / 尾盘恐慌卖出→次日高开踏空",
        evidence_level="HYPOTHESIS",
    ),
]


# 前 3 个核心操盘手法（涨停板接力、机构抱团拉升、国家队托底）
TOP_3_PLAYBOOKS: list[Playbook] = TOP_PLAYBOOKS[:3]


def get_playbook_evidence_summary() -> str:
    """生成所有 playbook 的证据等级摘要。"""
    from collections import Counter
    counts = Counter(pb.evidence_level for pb in TOP_PLAYBOOKS)
    lines = [
        "# Playbook 证据等级",
        "",
        f"| Playbook | 类型 | 证据等级 |",
        f"|----------|------|---------|",
    ]
    for pb in TOP_PLAYBOOKS:
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
