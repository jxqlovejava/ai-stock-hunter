# -*- coding: utf-8 -*-
"""30 条 A 股专属投资军规。

严重度:
  - block: 触发时硬阻断交易，不可覆盖
  - warn:  触发时标注风险，降低置信度
  - info:  触发时仅记录，不影响决策

类别:
  - position: 仓位与资金管理
  - selection: 选股与估值纪律
  - trading: 买卖纪律
  - emotion: 情绪纪律
  - information: 信息纪律
  - risk: 风控与止盈止损
  - review: 复盘与进化
  - meta: 元风控
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


class RuleCategory(str, Enum):
    POSITION = "position"
    SELECTION = "selection"
    TRADING = "trading"
    EMOTION = "emotion"
    INFORMATION = "information"
    RISK = "risk"
    REVIEW = "review"
    META = "meta"


@dataclass
class Rule:
    """单条军规。"""
    id: str
    category: RuleCategory
    name: str
    severity: Severity
    description: str
    check_field: str = ""  # 检查的画像/持仓字段
    threshold: str = ""     # 触发阈值表达式


MILITARY_RULES: list[Rule] = [
    # ── 仓位与资金管理 ──
    Rule("r001", RuleCategory.POSITION, "单票仓位上限", Severity.BLOCK, "单票仓位 ≤ 总资产 20%"),
    Rule("r002", RuleCategory.POSITION, "总仓位上限", Severity.BLOCK, "股票头寸 ≤ 80%，保留 ≥ 20% 现金"),
    Rule("r003", RuleCategory.POSITION, "行业集中度", Severity.BLOCK, "单行业仓位 ≤ 40%"),
    Rule("r004", RuleCategory.POSITION, "创业板/科创板折扣", Severity.WARN, "双创板股票仓位自动 ×0.8"),
    Rule("r005", RuleCategory.POSITION, "永不满仓", Severity.WARN, "任何时候保留 ≥ 10% 现金"),

    # ── 选股与估值纪律 ──
    Rule("r006", RuleCategory.SELECTION, "ST/*ST 一票否决", Severity.BLOCK, "ST/*ST 股不进任何分析管道"),
    Rule("r007", RuleCategory.SELECTION, "次新股冷静期", Severity.WARN, "上市 < 60 交易日不进交易仓"),
    Rule("r008", RuleCategory.SELECTION, "不懂不投", Severity.WARN, "超出能力圈的标的标注，降置信度"),
    Rule("r009", RuleCategory.SELECTION, "PE 极端值预警", Severity.WARN, "PE > 行业均值 3 倍或为负时，基本面得分降档"),
    Rule("r010", RuleCategory.SELECTION, "商誉雷预警", Severity.WARN, "商誉/净资产 > 30% → 强制标注减值风险"),
    Rule("r011", RuleCategory.SELECTION, "股权质押预警", Severity.WARN, "大股东质押 > 50% → 强制标注平仓风险"),

    # ── 买卖纪律 ──
    Rule("r012", RuleCategory.TRADING, "不追涨停", Severity.BLOCK, "当日涨停板不挂买单"),
    Rule("r013", RuleCategory.TRADING, "不接飞刀", Severity.WARN, "连续 3 日跌幅 > 15% 且无基本面改善 → 等止跌确认"),
    Rule("r014", RuleCategory.TRADING, "利好出尽是利空", Severity.WARN, "重大利好+股价 5 日内已涨 > 15% → 置信度 -0.15"),
    Rule("r014b", RuleCategory.TRADING, "追涨熔断", Severity.WARN, "5 日涨幅 > 20%（不论消息面）→ 评分上限 HOLD（55），强制标注追涨风险"),
    Rule("r015", RuleCategory.TRADING, "不赌财报", Severity.BLOCK, "财报公布前 2 个交易日不新建仓"),
    Rule("r016", RuleCategory.TRADING, "分批建仓", Severity.WARN, "新建仓分 ≥ 2 批，间隔 ≥ 5 个交易日"),

    # ── 情绪纪律 ──
    Rule("r017", RuleCategory.EMOTION, "连续止损休整", Severity.BLOCK, "连续 3 次止损后强制休整 ≥ 3 个交易日"),
    Rule("r018", RuleCategory.EMOTION, "恐慌不决策", Severity.WARN, "大盘暴跌 (>3%) 当日不操作"),
    Rule("r019", RuleCategory.EMOTION, "盈利上移止损", Severity.BLOCK, "浮盈 > 20% → 止损上移至成本价"),
    Rule("r020", RuleCategory.EMOTION, "空仓视角检验", Severity.WARN, "每笔操作前：空仓会在现价买入吗？不会就减"),
    Rule("r021", RuleCategory.EMOTION, "拒绝爱上持仓", Severity.WARN, "连续 3 次拒绝卖出建议 → 推送确认偏误报告"),

    # ── 信息纪律 ──
    Rule("r022", RuleCategory.INFORMATION, "信源交叉验证", Severity.BLOCK, "交易决策数据 ≥ 2 个 T1+ 来源"),
    Rule("r023", RuleCategory.INFORMATION, "机构研报≠事实", Severity.WARN, "机构目标价仅作参考"),
    Rule("r024", RuleCategory.INFORMATION, "小作文零信任", Severity.BLOCK, "微信/论坛/自媒体未经核实的消息不作分析输入"),

    # ── 风控与止盈止损 ──
    Rule("r025", RuleCategory.RISK, "单笔止损", Severity.BLOCK, "单笔亏损 ≥ 本金 2% → 无条件平仓"),
    Rule("r026", RuleCategory.RISK, "组合回撤熔断", Severity.BLOCK, "组合回撤 ≥ 15% → 强制减仓至 50%"),
    Rule("r027", RuleCategory.RISK, "流动性熔断", Severity.WARN, "持仓市值 > 日均成交额 5% → 禁止加仓"),
    Rule("r028", RuleCategory.RISK, "移动止盈", Severity.WARN, "浮盈 > 30% → 启动 ATR 移动止盈"),

    # ── 复盘与进化 ──
    Rule("r029", RuleCategory.REVIEW, "决策书面记录", Severity.INFO, "每次交易留书面记录"),
    Rule("r030", RuleCategory.REVIEW, "错题本更新", Severity.INFO, "止损/亏损交易 → 72h 内写教训"),

    # ── 元风控 ──
    Rule("r031", RuleCategory.META, "系统级熔断", Severity.BLOCK, "系统整体建议滚动 3 月胜率 < 40% → 全局静默"),

    # ── 财务质量军规（A股本土化强化）──
    Rule(
        "r032", RuleCategory.SELECTION, "ROE 连续性",
        Severity.WARN,
        "近 3 年 ROE 均 > 10% 且无年度亏损，否则标注盈利质量风险",
    ),
    Rule(
        "r033", RuleCategory.SELECTION, "现金流质量",
        Severity.WARN,
        "近 3 年累计经营现金流/净利润 > 0.8，否则标注纸面利润风险",
    ),
    Rule(
        "r034", RuleCategory.SELECTION, "分红门槛",
        Severity.INFO,
        "近 3 年累计分红/净利润 > 30%，否则标注铁公鸡风险（不分红/少分红）",
    ),

    # ── 反操纵军规 ──
    Rule(
        "R032", RuleCategory.RISK, "筹码集中度风险",
        Severity.WARN,
        "前十大流通股东持股>60%或股东户数连续下降>15%→筹码高度集中，操纵风险升高，仓位上限降低30%",
    ),
    Rule(
        "R033", RuleCategory.RISK, "操纵历史警戒",
        Severity.WARN,
        "个股12个月内出现≥3次操纵嫌疑→标记为惯犯，永久提高操纵检测敏感度，仓位上限降低50%",
    ),
    Rule(
        "R034", RuleCategory.RISK, "资金背离预警",
        Severity.WARN,
        "主力资金连续5日流出但价格不跌或上涨→诱多出货嫌疑，延迟入场1-2日",
    ),
]
