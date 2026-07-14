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
            # 与 wash_then_markup 生命周期互补：本 playbook 偏「单日急跌 V 反」
            "若出现弱反弹后再杀第二波，升级对照 wash_then_markup 多波状态",
        ],
        execution_pattern=[
            "T 日开盘: 庄家集中砸盘，制造技术破位形态",
            "T 日 10:00-11:00: 散户止损盘涌出→庄家在低位接货",
            "T 日 13:00-15:00: 缓慢回升→做短线的被迫追回",
            "T+1-3 日: 股价回到洗盘前水平→被洗出的散户后悔",
            "加强: 弱反弹后的第二波急跌更易洗掉回补盘（非当日 V 反收工）",
        ],
        exit_conditions=[
            "日线收长下影线 (锤子线形态)",
            "急跌后 2 小时内未破新低",
            "北向资金当日净流入 (庄家 + 北向合力)",
            "若第二波再破前低且放量长跌，改按真出货/风控处理（勿硬扛）",
        ],
        price_impact_profile="急跌 5-8%→当日 V 型反弹→3 日内回到洗盘前价格；多波场景见 wash_then_markup",
        risk_to_follower="被震仓吓出→在最低点附近割肉→踏空反弹 8-15%；第二波再洗更易二次割肉",
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
    # ── 洗盘阶段操盘手法 (Phase 11: Washout Detection) ──
    Playbook(
        id="washout_sharp_drop",
        name="洗盘-股价异常急跌 (平稳走势→突然急跌→制造空头恐慌)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "前期股价走势平稳（振幅 < 2%，持续 ≥ 30 分钟）",
            "突然在 15 分钟内急速下跌 ≥ 4%",
            "急跌时成交量明显放大（量比 ≥ 2.0）",
            "非外因（无利空消息）驱使的急跌",
        ],
        execution_pattern=[
            "T 日前期: 股价平稳运行，给散户安全感",
            "T 日某时刻: 庄家突然集中抛售，15 分钟内急跌 4-7%",
            "T 日急跌后: 散户恐慌跟风卖出→庄家低位接筹",
            "T 日尾盘: 可能部分回升或低位横盘吸筹",
        ],
        exit_conditions=[
            "急跌后 30 分钟内继续创新低（真崩盘）",
            "急跌当日有利空消息公告（外因驱动而非庄家操纵）",
        ],
        price_impact_profile="急跌 4-7%→当日可能部分回升→3-5 日内回到急跌前价格",
        risk_to_follower="急跌中恐慌割肉→卖在最低点→踏空回升 5-10%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_high_open_low",
        name="洗盘-高开低走 (大幅高开→一路走低→制造出货假象)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "高开 ≥ 3%（甚至涨停价开盘）",
            "一路走低，收盘在当日振幅底部 20%",
            "开盘时段成交量放大（恐慌盘出逃）",
            "当日 K 线为大阴线",
        ],
        execution_pattern=[
            "T 日 09:25: 集合竞价大幅高开 3-7%，甚至涨停价开盘",
            "T 日 09:30-10:30: 庄家分批出货+散户跟风卖出→价格走低",
            "T 日 10:30-15:00: 价格持续下行，收盘接近最低价",
            "T+1 日: 低开后企稳或回升，昨日被吓出的散户踏空",
        ],
        exit_conditions=[
            "高开后 30 分钟内未回补缺口（真出货信号）",
            "北向/机构资金同步流出（排除洗盘可能）",
        ],
        price_impact_profile="高开 3-7%→当日收最低→次日企稳→3 日内回到开盘价",
        risk_to_follower="开盘追入被套/恐慌卖出踏空，1-3 日内反向运行",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_low_open_high",
        name="洗盘-低开高走 (大幅低开→恐慌割肉→低位吸筹后拉升)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "低开 ≥ 3%（甚至跌停价开盘）",
            "一路走高，收盘在当日振幅顶部 20%",
            "开盘时段放量（散户恐慌割肉）",
            "当日 K 线为大阳线",
        ],
        execution_pattern=[
            "T 日 09:25: 集合竞价大幅低开 3-7%，甚至跌停价开盘",
            "T 日 09:30-10:00: 散户恐慌割肉→庄家低位大量接筹",
            "T 日 10:00-15:00: 价格逐步回升，收盘接近最高价",
            "T+1 日: 继续走高，昨日割肉的散户踏空后悔",
        ],
        exit_conditions=[
            "低开后 30 分钟内继续创新低（真崩盘）",
            "反弹至前收盘价附近后再次回落（骗线确认）",
        ],
        price_impact_profile="低开 3-7%→当日收最高→次日继续涨→3 日内涨幅 5-10%",
        risk_to_follower="开盘恐慌割肉在最低点→当日/次日踏空反弹 5-15%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_one_sided_decline",
        name="洗盘-分时单边下跌 (逐波下跌→反弹无力→跳水制造恐慌)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "分时图出现 ≥ 3 波逐级下跌浪",
            "每次反弹高度不及前收盘价",
            "下跌以「跳水」式完成（单分钟 > 0.5%）",
            "全天大部分时间（> 80%）运行在前收盘价下方",
        ],
        execution_pattern=[
            "T 日 09:30-10:00: 开盘后开始第一波下跌",
            "T 日 10:00-11:30: 反弹无力→第二波跳水→散户开始恐慌",
            "T 日 13:00-14:30: 第三波跳水→更多散户止损",
            "T 日 14:30-15:00: 尾盘可能有微弱反弹，但力度极小",
        ],
        exit_conditions=[
            "尾盘反弹站上前收盘价（洗盘结束信号）",
            "连续3日出现单边下跌（可能是真出货）",
        ],
        price_impact_profile="当日单边下跌 3-6%→次日可能继续小幅下跌→3-5 日后回升",
        risk_to_follower="在单边下跌中被逐步吓出→分多次割肉→累计损失 8-12%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_continuous_suppression",
        name="洗盘-持续压低 (持续下压→卖盘沉重→制造出货假象)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "价格持续下压 ≥ 60 分钟",
            "任何反弹 < 0.2%（几乎没有反弹）",
            "阴线占比 > 65%（卖盘沉重假象）",
            "持续压盘期间总跌幅明显",
        ],
        execution_pattern=[
            "T 日: 每下跌 1-2 个价位→卖盘挂出大单压盘",
            "T 日: 散户看到卖盘沉重→跟风卖出→价格进一步下跌",
            "T 日: 庄家在低位挂买单接回散户抛出的筹码",
            "T 日尾盘: 可能突然拉升收回部分跌幅（庄家完成吸筹）",
        ],
        exit_conditions=[
            "尾盘突然放量拉升（吸筹完成→洗盘结束）",
            "持续压低超过 3 小时无反弹（可能是真出货）",
        ],
        price_impact_profile="持续下压 2-5%→尾盘可能回升 1-2%→次日企稳回升",
        risk_to_follower="被沉重卖盘吓出→在持续下压中割肉→错失后续反弹",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_consecutive_yin",
        name="洗盘-连续阴线 (6-9连阴→逐日走低→制造恐慌)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "日K线连续 6-9 根阴线",
            "每天收低（≥ 70% 的天数）",
            "量能从前期到后期递减（卖压衰竭）",
            "累计跌幅 5-15%（跌幅适中，过大则是真出货）",
            # 加强（视频「后半段割肉」）: 形态层仍只报连阴；生命周期由 wash_then_markup 判波次
            "连阴进入后半段（约第 5-9 根）时割肉盘最集中",
        ],
        execution_pattern=[
            "T-8→T-1 日: 每天小幅收阴，量能逐步萎缩",
            "散户心理演变: 第一根阴线不怕→第二根能扛→第三根硬撑",
            "第四根开始恐慌→第五六根不得不出局",
            "加强: 后半段是「等散户割完」的关键窗口，非前半段就结束",
            "T 日: 洗盘结束，可能收阳或十字星→新一轮拉升开始",
        ],
        exit_conditions=[
            "连阴超过 15 根（排除洗盘，可能是真崩盘）",
            "累计跌幅超过 20%（排除洗盘，可能是出货）",
            "出现放量阳线（洗盘结束信号）",
            "近 3 日均量较下跌前显著萎缩（砸不动）→对照 wash_then_markup 洗尽信号",
        ],
        price_impact_profile="6-9 天累计跌 5-15%→缩量→止跌→3-5 日回升到洗盘前",
        risk_to_follower="在连续阴线中逐步被吓出→第 5-6 天（后半段）割肉→错失后续反弹",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_support_breakdown",
        name="洗盘-击穿支撑 (破位制造技术性恐慌→低位吸筹)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "股价跌破关键支撑（MA20/MA60/前 N 日低点）",
            "前一日收盘在支撑位之上，今日首次跌破",
            "破位日成交量放大（恐慌盘+庄家接筹）",
            "破位后 2-3 日企稳不继续下跌",
        ],
        execution_pattern=[
            "T 日: 庄家集中抛售砸盘→股价跌破关键技术支撑",
            "T 日: 技术派止损单触发→散户恐慌盘涌出",
            "T 日: 庄家在支撑位下方挂买单→低位大量接筹",
            "T+1-3 日: 股价企稳→逐步收复支撑位→技术派后悔卖早",
        ],
        exit_conditions=[
            "破位后 3 日无法收复支撑（真破位）",
            "破位日无放量（可能是阴跌而非操纵）",
        ],
        price_impact_profile="跌破支撑 2-5%→2-3 日内收复→5 日内回到破位前价格",
        risk_to_follower="技术破位止损→卖在最低点附近→踏空收复行情 5-8%",
        evidence_level="HYPOTHESIS",
    ),
    Playbook(
        id="washout_small_rise_big_drop",
        name="洗盘-小涨大跌 (小阳伴大阴→温水煮蛙式洗盘)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "K线形态: 小阳(涨 < 2%)伴大阴(跌 > 4%)",
            "或 二阴夹一阳 / 三阴夹一阳",
            "窗口内累计跌幅明显",
            "每次小反弹后即大跌",
            # 加强: 小涨=假反弹波，大跌=再洗；多波计数见 wash_then_markup
            "弱反弹幅度约 1.5%-6% 后继续下探，构成第二波再洗",
        ],
        execution_pattern=[
            "T-3→T 日: 小阳反弹（散户以为见底）→次日大阴（打回原形）",
            "循环 1-2 次: 散户形成「反弹就是逃命机会」心理",
            "加强: 第一次反弹后的再杀最易洗掉回补盘与抄底盘",
            "最终阶段: 散户在最后一次小反弹中全部出局",
            "洗盘结束后: 真正的拉升开始，散户已不在车上",
        ],
        exit_conditions=[
            "出现放量大阳线（洗盘结束→真拉升开始）",
            "连续2次小涨大跌后出现第三次（可能是真出货）",
            "缩量企稳后放量阳线 → 升级对照 wash_then_markup 拉升候选",
        ],
        price_impact_profile="每次循环跌 3-6%→反复 1-2 次→累计跌 8-12%→洗盘结束后拉升",
        risk_to_follower="在反弹中被骗入→大跌中被吓出→反复被收割→最终踏空主升浪",
        evidence_level="HYPOTHESIS",
    ),
    # ── 多波洗盘生命周期（视频提炼；不重复单日形态，只补状态机）──
    Playbook(
        id="wash_then_markup",
        name="多波洗盘后拉升 (连杀→后半段割肉→再洗→砸不动才拉)",
        player_type=PlayerType.MANIPULATOR,
        trigger_conditions=[
            "日线连续偏弱 ≥4 日，累计回撤约 5%-22%（过大改按出货）",
            "下跌中出现弱反弹（约 1.5%-6%）后继续下探 → 第二波再洗",
            "连跌后半段（约过半/第 6 日以后）散户割肉最集中",
            "近 3 日均量较下跌前显著萎缩 → 「砸不走」/洗尽候选",
            "可选: 财报/中报窗口叙事掩护（由调用方注入 earnings_window）",
            "可选: 止跌后缩量企稳 + 放量阳线 → 拉升候选",
        ],
        execution_pattern=[
            "波1: 连续下杀制造恐慌，前半段多数散户仍硬扛",
            "后半段: 割肉盘最猛 — 主力常等到此处才考虑结束洗盘",
            "假反弹: 弱反弹诱回补/抄底 → 再杀第二波洗掉回补盘",
            "掩护: 可能借中报/业绩叙事强化空头氛围（需公告核验）",
            "洗尽: 量能枯竭、砸不动 → 进入主升；未持仓勿裸追",
        ],
        exit_conditions=[
            "累计跌幅 >22% 或持续放量长跌 → FAILED_WASHOUT，执行止损纪律",
            "出现 washout_consecutive_yin / small_rise 形态信号可交叉确认，但不重复计分逻辑",
            "拉升候选出现后管道评分仍 REDUCE/破硬止损 → 不因「叙事」扛单",
        ],
        price_impact_profile=(
            "多日连弱 5-15%→弱反弹再杀→缩量→止跌放量阳→数日回补洗盘段"
            "（单日急跌 V 反仍归 shakeout；单形态仍归 washout_*）"
        ),
        risk_to_follower=(
            "后半段恐慌清仓 / 弱反弹满仓回补再被洗 / 洗尽时已下车踏空主升；"
            "或把真出货误判为洗盘硬扛"
        ),
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
