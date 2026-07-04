# -*- coding: utf-8 -*-
"""A 股核心规则库 — 博弈论基础。

原则 1-3 合并为单个文件（Phase 1 只保留这一个 game_theory 文件）。

每条规则标注：
  - 精确描述 (formal_def)
  - 制度设计意图 (design_intent)
  - 受益方 (who_benefits)
  - 实际行为激励 (behavioral_incentive)
  - 大资金 vs 小资金不对等 (large_vs_small_asymmetry)

⚠️ 标注规范:
  - VERIFIED: 经过回测或统计检验
  - HYPOTHESIS: 逻辑推演但未经数据验证
  - HEURISTIC: 经验法则，来自投资者社区/书籍
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RuleCategory(str, Enum):
    TRADING = "trading"           # 交易制度
    PRICE_LIMIT = "price_limit"   # 涨跌幅
    DELISTING = "delisting"       # 退市
    MARGIN = "margin"             # 融资融券
    IPO = "ipo"                   # 发行上市
    TAX = "tax"                   # 税费
    DISCLOSURE = "disclosure"     # 信息披露
    GOVERNANCE = "governance"     # 减持/再融资


class EvidenceLevel(str, Enum):
    VERIFIED = "VERIFIED"         # 经过数据验证
    HYPOTHESIS = "HYPOTHESIS"     # 逻辑推演，待验证
    HEURISTIC = "HEURISTIC"       # 经验法则


# ---------------------------------------------------------------------------
# MarketRule dataclass
# ---------------------------------------------------------------------------

@dataclass
class MarketRule:
    """单条 A 股规则的完整描述。"""

    id: str                                     # 规则 ID
    name: str                                   # 规则名称
    category: RuleCategory                      # 分类
    formal_def: str                             # 精确规则描述
    design_intent: str                          # 制度设计意图
    who_benefits: list[str]                     # 受益方
    behavioral_incentive: str                   # 实际行为激励
    large_vs_small_asymmetry: str               # 大资金 vs 小资金不对等
    evidence: EvidenceLevel = EvidenceLevel.HEURISTIC


# ---------------------------------------------------------------------------
# 15 core A-share rules
# ---------------------------------------------------------------------------

A_SHARE_RULES: list[MarketRule] = [
    # ── 交易制度 ──
    MarketRule(
        id="T1",
        name="T+1 交割制度",
        category=RuleCategory.TRADING,
        formal_def="当日买入的股票，最早 T+1 日才能卖出（A 股），或 T+0（可转债/ETF/港股通部分标的）",
        design_intent="抑制过度投机，降低日内波动，保护散户不被高频交易收割",
        who_benefits=["大资金", "监管层"],
        behavioral_incentive="催生「打板」策略——今日拉涨停锁定流动性，明日高开出货。散户追涨停后 T+1 被锁，次日无法及时离场。也催生「尾盘拉升」——临近收盘推高股价，次日竞价出货",
        large_vs_small_asymmetry="大资金可利用 T+1 制造流动性陷阱：今日拉涨停 → 散户追入被锁 → 次日大资金集合竞价出货 → 散户 T+1 才能卖但已低开。散户在 T+1 下的止损能力被系统性削弱",
        evidence=EvidenceLevel.VERIFIED,
    ),
    MarketRule(
        id="T0_ETF",
        name="ETF/可转债 T+0 回转",
        category=RuleCategory.TRADING,
        formal_def="部分 ETF（跨境 ETF/债券 ETF/货币 ETF）和可转债支持 T+0 回转交易，当日买入当日可卖出",
        design_intent="为机构提供套利和对冲工具，提高 ETF 定价效率",
        who_benefits=["大资金", "量化基金"],
        behavioral_incentive="量化基金利用 ETF T+0 做日内套利；散户因资金量小和信息劣势无法参与。同一市场内 T+1 和 T+0 并存，创造不对等博弈环境",
        large_vs_small_asymmetry="大资金在 T+0 品种上可以做日内风控，散户在 T+1 品种上不行。这导致散户在市场恐慌时无法及时减仓",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 涨跌幅限制 ──
    MarketRule(
        id="PRICE_LIMIT_10",
        name="±10% 涨跌停板（主板）",
        category=RuleCategory.PRICE_LIMIT,
        formal_def="沪深主板股票当日涨跌幅不超过前收盘价的 ±10%（ST/*ST 为 ±5%）",
        design_intent="防止股价单日暴涨暴跌，给市场冷静期，保护中小投资者",
        who_benefits=["监管层", "游资"],
        behavioral_incentive="涨停板封死后买盘无法成交 → 资金溢出到同板块其他标的 → 板块联动效应。连续涨停制造赚钱效应 → 吸引场外资金 → 板块泡沫化。涨停打开后获利了结 → 资金踩踏撤离",
        large_vs_small_asymmetry="游资利用涨停板制度「造板」：小盘股易封板 → 大资金封板锁死流动性 → 次日高开出货。散户在涨停板排队无法买入（通道优势在机构），能在涨停板买到的往往是即将开板的「烂板」",
        evidence=EvidenceLevel.VERIFIED,
    ),
    MarketRule(
        id="PRICE_LIMIT_20",
        name="±20% 涨跌停板（科创/创业板）",
        category=RuleCategory.PRICE_LIMIT,
        formal_def="科创板和创业板股票当日涨跌幅不超过前收盘价的 ±20%（上市前 5 日无限制）",
        design_intent="提高定价效率，与注册制改革配套，减少行政干预",
        who_benefits=["大资金", "量化基金"],
        behavioral_incentive="20% 涨跌幅下「打板」成本更高 → 游资偏好主板的 10% 制度。科创板/创业板波动更大 → 散户追涨杀跌的亏损速度更快。±20% + T+1 = 单日最大亏损可达 40%（地天板+次日大幅低开）",
        large_vs_small_asymmetry="±20% 放大了 T+1 的不对等——散户买入后当日可能亏损 20% 而无法止损，次日再低开 10%，两日亏损 30%。机构可通过股指期货/期权对冲",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── ST 与退市 ──
    MarketRule(
        id="ST",
        name="ST / *ST 特别处理制度",
        category=RuleCategory.DELISTING,
        formal_def="连续亏损/净资产为负/审计否定意见等触发 ST 警示（涨跌幅缩至 5%），*ST 有退市风险。连续 20 交易日收盘价 < 1 元或市值 < 3 亿元触发面值退市",
        design_intent="风险警示，督促上市公司改善经营，保护投资者知情权",
        who_benefits=["监管层"],
        behavioral_incentive="ST 后机构强制清仓（风控要求）→ 股价进一步下跌 → 散户接盘博弈「摘帽」。面值退市制度催生「保壳」行为——大股东增持/资产注入/政府补贴",
        large_vs_small_asymmetry="机构在 ST 前有信息优势（提前调研/数据分析）可以先撤。散户通常等到公告才知道 → 已经跌了 30-50%",
        evidence=EvidenceLevel.VERIFIED,
    ),
    MarketRule(
        id="DELIST",
        name="退市整理期制度",
        category=RuleCategory.DELISTING,
        formal_def="强制退市股票进入 15 个交易日的退市整理期（涨跌幅 10%），之后转至老三板（涨跌幅 5%，流动性极差）",
        design_intent="给投资者最后的退出窗口",
        who_benefits=["监管层"],
        behavioral_incentive="退市整理期首日通常无量跌停 → 散户无法卖出 → 在老三板再亏 50-90%。「退市整理期」是散户最后逃命机会，但通道优势在机构",
        large_vs_small_asymmetry="机构通过大宗交易/协议转让提前退出；散户只能在退市整理期跌停板上排队，实际成交概率极低",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── IPO 与融资 ──
    MarketRule(
        id="IPO",
        name="IPO 发行定价限制",
        category=RuleCategory.IPO,
        formal_def="A 股 IPO 实行注册制（科创/创业/主板），但发行市盈率仍受窗口指导（通常不超过 23 倍）。上市首日无涨跌幅限制（注册制下前 5 日无限制）",
        design_intent="防止高价发行损害二级市场投资者，同时通过注册制提高融资效率",
        who_benefits=["打新者", "上市公司"],
        behavioral_incentive="23 倍 PE 隐形天花板 → 几乎所有新股都被低估发行 → 上市后连续涨停 → 「打新稳赚不赔」的社会共识 → 冻结万亿打新资金。注册制下首日涨幅更极端（无涨跌幅限制）",
        large_vs_small_asymmetry="机构网下配售比例远高于散户网上申购中签率（约 0.01-0.05%）。散户打新中签如中彩票",
        evidence=EvidenceLevel.VERIFIED,
    ),
    MarketRule(
        id="MARGIN",
        name="融资融券限制",
        category=RuleCategory.MARGIN,
        formal_def="50 万资产门槛 + 6 个月交易经验才能开通两融。融资标的约 1600 只（有市值/流动性要求），融券券源极少。融资利率约 6-8%，融券成本更高",
        design_intent="控制杠杆风险，防止过度投机",
        who_benefits=["券商"],
        behavioral_incentive="融券券源稀缺 → A 股做空成本极高 → 市场天然偏向多头。融资余额高企时 → 杠杆资金拥挤 → 一旦下跌触发强平 → 踩踏加剧。散户融资买入被强平的阈值是维持担保比例 < 130%",
        large_vs_small_asymmetry="机构可通过收益互换/场外期权变相加杠杆，不受两融限制。散户只能通过两融加杠杆（且融券基本不可用）→ 只能做多不能做空",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 信息披露 ──
    MarketRule(
        id="DISCLOSE",
        name="信息披露制度",
        category=RuleCategory.DISCLOSURE,
        formal_def="上市公司须定期披露年报（4/30 前）、半年报（8/31 前）、季报（季后 1 月内）。重大事项 2 日内披露。信披违规将面临证监会处罚（罚款 + 市场禁入）和投资者索赔",
        design_intent="提高市场透明度，保护投资者知情权，为注册制提供基础",
        who_benefits=["监管层", "散户"],
        behavioral_incentive="财报季前后股价波动加剧。业绩预告和实际报告的市场反应不同——部分已在预告中定价。信息披露违规的处罚力度弱于美股——罚款上限较低、刑事责任罕见",
        large_vs_small_asymmetry="机构有卖方分析师提前调研和草根数据，可以在财报公布前 1-2 周形成较准确的盈利预测。散户只能等公告",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 分红与除权 ──
    MarketRule(
        id="DIVIDEND",
        name="分红与除权除息制度",
        category=RuleCategory.TAX,
        formal_def="现金分红需除息（股价 - 每股分红），送转股需除权。持股 > 1 年免征红利税，1 月-1 年征 10%，< 1 月征 20%。再融资与分红挂钩——近 3 年累计分红 < 年均利润 30% 不得再融资",
        design_intent="鼓励长期持股和现金分红，通过税收激励引导价值投资",
        who_benefits=["长线投资者"],
        behavioral_incentive="除权除息日股价自动下调 → 短线持有者分红收益被税侵蚀。再融资与分红挂钩 → 有融资需求的公司必须分红 → 「被迫分红」信号可能误导投资者。高分红不一定是好公司——可能是没有更好的投资机会",
        large_vs_small_asymmetry="大股东持股 > 1 年免税，分红是真实的现金回报。散户短线交易被征 20% 红利税，分红可能反而亏损",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 印花税 ──
    MarketRule(
        id="STAMP_DUTY",
        name="证券交易印花税",
        category=RuleCategory.TAX,
        formal_def="A 股卖出时单边征收 0.1%（2023 年 8 月 28 日起减半）。印花税作为调控工具——历史上多次通过调税影响市场",
        design_intent="调控交易频率和市场热度，也作为财政收入",
        who_benefits=["财政"],
        behavioral_incentive="印花税减半 → 市场短期提振（2023/8/28 历史案例）但长期趋势不受影响。买入免费卖出收费 → 鼓励持有不鼓励交易",
        large_vs_small_asymmetry="对机构量化高频策略来说，印花税 + 佣金 = 主要交易成本来源。对散户来说，印花税通常远小于选股错误造成的损失——散户关注交易成本是本末倒置",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 国家队 ──
    MarketRule(
        id="NATIONAL_TEAM",
        name="国家队干预机制",
        category=RuleCategory.GOVERNANCE,
        formal_def="汇金公司、证金公司、社保基金、养老金作为「国家队」在市场异常波动时通过增持 ETF/蓝筹股稳定市场。持股市值约 3-4 万亿，占总市值约 3-5%",
        design_intent="维护金融市场稳定，防范系统性风险，作为「最后买家」提供流动性",
        who_benefits=["监管层", "大盘蓝筹股"],
        behavioral_incentive="HEURISTIC",
        large_vs_small_asymmetry="国家队只买大盘蓝筹/ETF → 中小盘股在危机中没有国家队托底。国家队增持信号 → 北向跟风 + 游资借势 → 估值短期偏离基本面",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 减持 ──
    MarketRule(
        id="REDUCTION",
        name="大股东/董监高减持新规",
        category=RuleCategory.GOVERNANCE,
        formal_def="大股东/董监高减持受限：IPO 后锁定期 12-36 月；减持前需预披露；连续 90 日竞价减持 ≤1%/大宗减持 ≤2%；破发/破净/分红不达标不得减持",
        design_intent="防止大股东上市套现，保护二级市场投资者，与分红挂钩鼓励价值创造",
        who_benefits=["散户"],
        behavioral_incentive="接近解禁日的股票存在减持压力——机构提前减仓规避。大股东通过大宗交易/协议转让规避竞价减持限制。破发/破净限制下，大股东有动力维护股价和分红",
        large_vs_small_asymmetry="大股东可通过复杂的持股结构调整（如通过多个主体分散持股）规避减持限制。散户无此能力",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 北向资金 ──
    MarketRule(
        id="NORTHBOUND",
        name="沪深股通（北向资金）",
        category=RuleCategory.TRADING,
        formal_def="外资通过沪港通/深港通买入 A 股，每日额度 520 亿元（沪）+ 520 亿元（深），总额度已取消。2024 年日均净买卖约 10-50 亿元",
        design_intent="引入外资提高定价效率，推动 A 股国际化（MSCI 纳入等）",
        who_benefits=["外资", "蓝筹股"],
        behavioral_incentive="北向资金连续净流入/流出 → A 股大盘方向的重要领先指标。北向偏好消费/金融/新能源龙头 → 这些行业的估值受外资影响最大。北向流出 + 内资不接 = 大盘承压",
        large_vs_small_asymmetry="北向资金本身是大资金，它的买卖行为影响散户持仓的股价方向。散户追踪北向是合理策略，但数据有 1 日延迟",
        evidence=EvidenceLevel.VERIFIED,
    ),

    # ── 盘中临停 ──
    MarketRule(
        id="HALT",
        name="盘中临时停牌机制",
        category=RuleCategory.TRADING,
        formal_def="无价格涨跌幅限制的股票（如新股首日）盘中交易价格较开盘价涨跌 ≥30% 或 ≥60% 时，分别临时停牌 10 分钟。异常波动可被交易所强制停牌核查",
        design_intent="防止新股/复牌股价格过度波动，给市场冷静期",
        who_benefits=["监管层"],
        behavioral_incentive="新股首日涨幅触及 30% 停牌 → 复盘后可能继续拉升或反转 → 散户在停牌期间无法操作。异常波动停牌核查 → 复牌后可能补跌",
        large_vs_small_asymmetry="机构可提前评估停牌风险并调整策略。散户在停牌时被锁仓，无法应对",
        evidence=EvidenceLevel.VERIFIED,
    ),
]


# ---------------------------------------------------------------------------
# 核心规则→资金流因果链 (原则 3)
# ---------------------------------------------------------------------------

@dataclass
class RuleCapitalFlowModel:
    """单条核心规则→资金流向的因果模型。"""

    rule_id: str
    rule_name: str
    causal_chain: list[str]             # 因果链
    leading_indicators: list[str]       # 先行指标
    data_source: str                    # 数据源


TOP_3_RULES: list[RuleCapitalFlowModel] = [
    RuleCapitalFlowModel(
        rule_id="PRICE_LIMIT_10",
        rule_name="±10% 涨跌停板（主板）",
        causal_chain=[
            "涨停板封死 → 买盘无法成交 → 资金溢出到同板块其他标的",
            "连续涨停 → 赚钱效应 → 吸引场外资金涌入该板块 → 板块整体估值抬升",
            "涨停打开 → 获利了结 → 资金快速撤离 → 板块踩踏下跌",
        ],
        leading_indicators=[
            "封单量 / 流通市值比（> 5% = 强封板）",
            "涨停家数趋势（连续 3 日 > 50 家 = 情绪过热）",
            "连板高度（最高连板数，> 7 板 = 投机极端）",
        ],
        data_source="AKShare 龙虎榜 + 涨停板数据",
    ),
    RuleCapitalFlowModel(
        rule_id="T1",
        rule_name="T+1 交割制度",
        causal_chain=[
            "T+1 锁仓 → 当日买入被锁定无法止损 → 次日开盘必须承受全部隔夜风险",
            "跌停日抄底 → 当日无法卖出锁定利润 → 次日若继续跌停则扩大亏损",
            "大资金利用 T+1 做「流动性陷阱」→ 今日拉涨停吸引散户追入 → 次日集合竞价出货",
        ],
        leading_indicators=[
            "尾盘拉升幅度（> 3% 且放量 = 可能的 T+1 陷阱）",
            "次日集合竞价量价（高开低走 = 主力出货）",
            "早盘涨停封板速度（< 5 分钟封板 = 强控盘）",
        ],
        data_source="AKShare 分钟级行情",
    ),
    RuleCapitalFlowModel(
        rule_id="NATIONAL_TEAM",
        rule_name="国家队干预机制",
        causal_chain=[
            "大盘暴跌 → 汇金/证金增持银行/蓝筹 ETF → 指数止跌企稳",
            "国家队买入信号 → 北向资金跟风流入 → 市场信心恢复 → 场外资金入场",
            "国家队逐步退出 → 市场需要找到新的买盘支撑 → 若没有则二次探底",
        ],
        leading_indicators=[
            "沪深 300 ETF (510300) 成交量异常放大（> 日均 3 倍）",
            "银行板块逆势上涨（大盘跌但银行涨 = 国家队在买）",
            "中央汇金公告增持（事后信号，但可跟踪公告频率）",
        ],
        data_source="AKShare 资金流向 + 国信宏观",
    ),
]
