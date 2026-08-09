# -*- coding: utf-8 -*-
"""52 条 A 股专属投资军规。

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
    Rule(
        "r013", RuleCategory.TRADING, "不接飞刀", Severity.WARN,
        "连续 3 日跌幅 > 15% 且无基本面改善 → 等止跌确认；"
        "或底部结构 A/B 段显示空头仍强（B≥A）→ 禁止抄底",
    ),
    Rule(
        "r013b", RuleCategory.TRADING, "大底须走出", Severity.WARN,
        "顺势力量未衰竭（B≥A）禁止抄底；"
        "顺势衰竭但逆势未确认禁止试多；"
        "仅当「顺势不足 + 逆势确认 + 回踩不破」才允许轻仓试多",
    ),
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

    # ── 周线均线军规 ──
    Rule(
        "r035", RuleCategory.SELECTION, "200周均线跌破",
        Severity.BLOCK,
        "价格跌破200周均线（约4年市场平均成本）→ "
        "无条件排除，不等基本面分析。A股历史数据显示此信号出现后仍有35-60%下行空间。",
    ),
    Rule(
        "r036", RuleCategory.TRADING, "200周均线趋势未确认",
        Severity.WARN,
        "价格站回200周均线不足4周 → 趋势反转未确认，"
        "建议等待周线级别右侧确认后再考虑建仓。",
    ),

    # ── 缠论结构军规 ──
    Rule(
        "r037", RuleCategory.TRADING, "缠论中枢破位/三卖",
        Severity.WARN,
        "缠论结构转弱(出现一卖/二卖/三卖或现价跌破中枢下沿) → 追高/抄底需谨慎",
    ),
    Rule(
        "r038", RuleCategory.TRADING, "缠论背驰未确认",
        Severity.WARN,
        "中枢破位且无底背驰/买点确认 → 跌势未止，避免左侧抄底",
    ),

    # ── 反操纵军规 (原 R032/R033/R034，重编号消除大小写冲突) ──
    Rule(
        "r039", RuleCategory.RISK, "筹码集中度风险",
        Severity.WARN,
        "前十大流通股东持股>60%或股东户数连续下降>15%→筹码高度集中，操纵风险升高，仓位上限降低30%",
        check_field="top10_holding_pct",
        threshold=">60 or holder_decline_pct>15",
    ),
    Rule(
        "r040", RuleCategory.RISK, "操纵历史警戒",
        Severity.WARN,
        "个股12个月内出现≥3次操纵嫌疑→标记为惯犯，永久提高操纵检测敏感度，仓位上限降低50%",
        check_field="manipulation_history_count",
        threshold=">=3",
    ),
    Rule(
        "r041", RuleCategory.RISK, "资金背离预警",
        Severity.WARN,
        "主力资金连续5日流出但价格不跌或上涨→诱多出货嫌疑，延迟入场1-2日",
        check_field="main_capital_outflow_days",
        threshold=">=5 and price not down",
    ),

    # ── P0-2 新增军规 ──
    Rule(
        "r042", RuleCategory.TRADING, "亏损后禁止报复性加仓",
        Severity.BLOCK,
        "单笔止损后当日禁止追加仓位/摊平，避免报复性加仓放大亏损",
        check_field="recent_stops",
        threshold="今日已有止损记录且意图加仓",
    ),
    Rule(
        "r043", RuleCategory.INFORMATION, "信息面冲突即禁止开仓",
        Severity.BLOCK,
        "技术信号方向与基本面/政策/新闻信息方向冲突 → 强制 hold/close，禁止开仓",
        check_field="signal_action",
        threshold="技术买/加与基本面或政策或新闻负面冲突",
    ),
    Rule(
        "r044", RuleCategory.TRADING, "涨停次日低开位置解读",
        Severity.WARN,
        "昨日涨停且今日低开 → 位置决定含义：高位涨停次日低开=主力出货嫌疑(追高谨慎/减仓)；"
        "底部涨停次日低开=洗盘吸筹(可观察反包)。避免把出货误当洗盘、把吸筹误当利空。",
        check_field="limit_up_next_day_gap_down",
        threshold="前日涨停 且 今日开盘价<昨收",
    ),
    Rule(
        "r045", RuleCategory.TRADING, "弱势突破不追",
        Severity.WARN,
        "突破强度为弱(量能勉强/幅度不足) → 假突破概率高，不追入，等回踩企稳或二次确认",
        check_field="breakout_weak",
        threshold="突破信号 strength=WEAK",
    ),

    # ── 技术面铁律军规（借鉴《17年炒股心得》10 铁律，技术性借鉴非业绩背书）──
    Rule(
        "r046", RuleCategory.TRADING, "换手率极端",
        Severity.WARN,
        "单日换手率 > 40%(非启动首日) → 主力散户剧烈对打，评分上限 HOLD(55)",
        check_field="turnover_rate_pct",
        threshold="> 40",
    ),
    Rule(
        "r047", RuleCategory.TRADING, "乖离过大等回调",
        Severity.WARN,
        "收盘价偏离 MA20 > 15% → 乖离过大，追入即抬轿，等回调再进",
        check_field="bias_vs_ma20_pct",
        threshold="> 15",
    ),
    Rule(
        "r048", RuleCategory.SELECTION, "低价股价值陷阱",
        Severity.WARN,
        "股价 < 6 元 → 价值陷阱警示(面值退市/壳股风险)。软标记，非硬排除",
        check_field="current_price",
        threshold="< 6",
    ),
    Rule(
        "r049", RuleCategory.TRADING, "跳空三连阳出货形态",
        Severity.WARN,
        "连续 3 日跳空高开收阳 → 主力拉高出货的典型加速形态，禁追",
        check_field="gap_up_three_yang",
        threshold="连续3日开盘>昨收 且 收>开",
    ),
    Rule(
        "r050", RuleCategory.TRADING, "高位量减价平派发",
        Severity.WARN,
        "高位(近60日高点3%内)量缩价平 → 主力派发征兆，减仓离场，别等跌了才反应",
        check_field="high_vol_price_flat",
        threshold="近3日均量<60日均量*0.7 且 3日波动<±2%",
    ),

    # ── 季节性风险窗口军规（借鉴自媒体《A股每年都有4个危险的时间窗口》T3 断言）──
    # 软性落地：全部 WARN，不硬阻断；配合 positioning 的 seasonal_discount 折扣。
    # 数据源：src/calendar/seasonal_windows.py 纯日期逻辑，经 orchestrator 注入 ctx flag。
    Rule(
        "r051", RuleCategory.RISK, "年末流动性枯竭窗口",
        Severity.WARN,
        "12月中下旬-1月初: 银行年终结算+公募锁定排名+私募赎回+游资休息 → 只有卖盘没有买盘，"
        "非核心主线清仓，阳线多为诱多陷阱",
        check_field="seasonal_year_end_window",
        threshold="当前处于 12/15-1/10",
    ),
    Rule(
        "r052", RuleCategory.RISK, "财报业绩双杀窗口",
        Severity.WARN,
        "4月底: 年报+一季报披露截止，拖到最后披露的非雷即坑，可能戴维斯双杀；"
        "回避尚未披露业绩的题材股",
        check_field="seasonal_april_window",
        threshold="当前处于 4/15-4/30",
    ),
    Rule(
        "r053", RuleCategory.RISK, "中报证伪窗口",
        Severity.WARN,
        "8月底: 中报落地检验上半年故事，逻辑证伪 → 机构杀估值；去弱留强，只做业绩超预期真龙头",
        check_field="seasonal_august_window",
        threshold="当前处于 8/20-8/31",
    ),
    Rule(
        "r054", RuleCategory.RISK, "季末获利了结窗口",
        Severity.WARN,
        "10月底: 三季报后全年业绩大局已定，机构保年终奖调仓兑现 → 主力主动撤退，不赌反弹",
        check_field="seasonal_october_window",
        threshold="当前处于 10/20-10/31",
    ),
]
