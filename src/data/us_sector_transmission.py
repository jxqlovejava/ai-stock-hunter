# -*- coding: utf-8 -*-
"""US sector → A-share sector 传导修正器。

对跨境联动强的板块，根据美股标的隔夜表现在A股诊断管道中
做对应板块的评分降权/加权修正。

用法:
    from src.data.us_sector_transmission import UsSectorTransmissionAdjuster
    adj = UsSectorTransmissionAdjuster()
    adjustments = adj.compute(global_market_data)
    # adjustments = [{"sector": "存储", "adjust": -5, "reason": "美光-5.4%→系数0.45"}, ...]
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 映射表 — US信号 → A股板块 × 传导系数
# ═══════════════════════════════════════════════════════════════════
#
# 每条映射定义:
#   us_key:     在 global_market 数据中查找的 key（取自 USIndexSnapshot.symbol）
#               SOX = 费城半导体指数，MU = 美光科技（个股）
#   us_label:   显示名称
#   sectors:    影响的A股板块列表（与诊断管道的板块名对应）
#   coefficient: 传导系数 0~1。
#               0.50 表示美股波动中的 50% 映射到A股评分修正
#   threshold:  最小触发涨跌幅（%），低于此阈值的波动忽略
#               避免日常噪音触发修正
#   weight:     该映射在综合修正中的权重（多映射指向同板块时的汇总权重）
#
# 系数估算逻辑:
#   美股存储跌 10% → A股存储板块一般低开 3-5%，跌幅映射比约 30-50%
#   取中位数 40% 做基准系数，然后微调:
#   - 产业链直接映射（美光→存储）系数偏高 0.45
#   - 情绪型映射（特斯拉→新能源车）系数偏低 0.35
#   - 行业指数级别（SOX→半导体）系数 0.50
#   以上系数待后续校准。

SECTOR_MAP: list[dict] = [
    # ── 存储/半导体（最强跨境联动） ──
    {
        "us_key": "SOX", "us_label": "费城半导体指数",
        "sectors": ["半导体", "芯片", "存储"],
        "coefficient": 0.50, "threshold": 2.0, "weight": 1.0,
    },
    {
        "us_key": "MU", "us_label": "美光科技",
        "sectors": ["存储", "芯片"],
        "coefficient": 0.45, "threshold": 3.0, "weight": 0.8,
        # 领先/滞后窗口（可选）: 存储周期"上游现货异动 → 海外龙头 → A股对标"约 2-4 周
        # 理念借鉴投资资讯 doc 04（可信度 0.3），仅作为 [SPECULATION] 弱信号
        "lead_lag": {
            "lag_days": [14, 28],
            "stages": [
                {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
                {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
                {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
            ],
            "decay_per_week": 0.30,
        },
    },
    {
        "us_key": "NVDA", "us_label": "英伟达",
        "sectors": ["AI算力", "光通信"],
        "coefficient": 0.50, "threshold": 2.0, "weight": 1.0,
        # AI 算力产业链传导更快: 海外龙头 → A股对标 约 1-2 周
        "lead_lag": {
            "lag_days": [7, 14],
            "stages": [
                {"name": "海外龙头", "lag_days": 5, "signal_strength": 0.85},
                {"name": "A股对标", "lag_days": 5, "signal_strength": 0.9},
            ],
            "decay_per_week": 0.25,
        },
    },
    {
        "us_key": "AMD", "us_label": "AMD",
        "sectors": ["芯片设计", "AI算力"],
        "coefficient": 0.40, "threshold": 2.5, "weight": 0.7,
    },
    # ── 消费电子 ──
    {
        "us_key": "AAPL", "us_label": "苹果",
        "sectors": ["消费电子", "果链"],
        "coefficient": 0.45, "threshold": 2.0, "weight": 1.0,
    },
    # ── 新能源车 ──
    {
        "us_key": "TSLA", "us_label": "特斯拉",
        "sectors": ["新能源车"],
        "coefficient": 0.35, "threshold": 3.0, "weight": 0.8,
    },
    # ── 中概/互联网（情绪传导为主） ──
    {
        "us_key": "BABA", "us_label": "阿里巴巴",
        "sectors": ["互联网"],
        "coefficient": 0.25, "threshold": 3.0, "weight": 0.6,
    },
    {
        "us_key": "KWEB", "us_label": "中概互联ETF",
        "sectors": ["互联网", "恒生科技"],
        "coefficient": 0.30, "threshold": 2.0, "weight": 0.7,
    },
]

# 需要从东财API额外拉取的美股标的secid列表
# (已有的SPX/NDX/DJIA之外需要补充的)
EXTRA_US_SECIDS: dict[str, str] = {
    "SOX": "100.SOX",
    "MU": "100.MU",
    "NVDA": "100.NVDA",
    "AMD": "100.AMD",
    "AAPL": "100.AAPL",
    "TSLA": "100.TSLA",
    "BABA": "100.BABA",
    "KWEB": "100.KWEB",
}


# 股票名称关键词 → 板块名映射（兜底分类，不依赖外部API）
# 当 SectorClassifier 不可用时使用
STOCK_KEYWORD_SECTOR_MAP: dict[str, list[str]] = {
    # ── 存储/半导体 ──
    "存储": ["存储", "芯片", "半导体"],
    "芯片": ["芯片", "半导体"],
    "半导体": ["半导体", "芯片"],
    "光刻": ["半导体", "设备材料"],
    "封测": ["芯片", "半导体"],
    "硅片": ["半导体"],
    "中芯": ["芯片", "半导体"],
    "华虹": ["芯片", "半导体"],
    "长电": ["芯片", "半导体"],
    "通富": ["芯片", "半导体"],
    "华天": ["芯片", "半导体"],
    "兆易": ["存储", "芯片"],
    "北京君正": ["存储", "芯片"],
    "澜起": ["芯片"],
    "江波龙": ["存储"],
    "佰维": ["存储"],
    "德明利": ["存储"],
    "普冉": ["存储", "芯片"],
    # ── AI算力/光通信 ──
    "AI": ["AI算力"],
    "算力": ["AI算力"],
    "光通信": ["光通信"],
    "光模块": ["光通信"],
    "中际": ["光通信"],
    "旭创": ["光通信"],
    "新易盛": ["光通信"],
    "天孚": ["光通信"],
    "服务器": ["AI算力"],
    "浪潮": ["AI算力"],
    "中科曙光": ["AI算力"],
    # ── PCB/电路板（AI服务器/通信设备的上游） ──
    "电路": ["消费电子", "AI算力"],
    "PCB": ["消费电子", "AI算力"],
    "覆铜板": ["消费电子"],
    "电子布": ["消费电子"],
    "深南电路": ["消费电子", "AI算力"],
    "生益科技": ["消费电子"],
    "宏和": ["消费电子"],
    "沪电": ["消费电子", "AI算力"],
    "景旺": ["消费电子"],
    # ── 消费电子/果链 ──
    "消费电子": ["消费电子"],
    "果链": ["果链", "消费电子"],
    "苹果": ["果链"],
    "立讯": ["果链", "消费电子"],
    "歌尔": ["果链", "消费电子"],
    "蓝思": ["果链", "消费电子"],
    "鹏鼎": ["消费电子"],
    "东山精密": ["消费电子"],
    # ── 新能源车 ──
    "新能源": ["新能源车"],
    "电动": ["新能源车"],
    "锂电": ["新能源车"],
    "电池": ["新能源车"],
    "宁德": ["新能源车"],
    "比亚迪": ["新能源车"],
    "蔚来": ["新能源车"],
    "小鹏": ["新能源车"],
    "理想": ["新能源车"],
    # ── 新能源（风电/光伏等） ──
    "风电": ["新能源"],
    "叶片": ["新能源"],
    "玻纤": ["新能源"],
    "光伏": ["新能源"],
    "隆基": ["新能源"],
    "阳光电源": ["新能源"],
    "金风": ["新能源"],
    "明阳": ["新能源"],
    "中材": ["新能源", "新能源车"],
    # ── 互联网 ──
    "互联": ["互联网"],
    "软件": ["互联网"],
    "传媒": ["互联网"],
    "腾讯": ["互联网"],
    "阿里": ["互联网"],
    "百度": ["互联网"],
    "网易": ["互联网"],
    "哔哩": ["互联网"],
    "拼多多": ["互联网"],
    "京东": ["互联网"],
    # ── 食品饮料 ──
    "茅台": ["食品饮料"],
    "五粮液": ["食品饮料"],
    "白酒": ["食品饮料"],
    "食品": ["食品饮料"],
}


def guess_sector_from_name(stock_name: str) -> list[str]:
    """根据股票名称关键词猜测所属板块。

    Args:
        stock_name: 股票名称，如 "中芯国际"、"北方华创"

    Returns:
        匹配的板块列表，如 ["芯片", "半导体"]
    """
    matched: list[str] = []
    for keyword, sectors in STOCK_KEYWORD_SECTOR_MAP.items():
        if keyword in stock_name:
            matched.extend(sectors)
    return list(set(matched))  # 去重


@dataclass
class SectorAdjustment:
    """单条板块修正建议。"""

    sector: str                      # A股板块名
    adjust: int                      # 评分修正值（-100 ~ +100）
    reason: str                      # 修正原因（供输出展示）
    us_change_pct: float             # 触发修正的美股涨跌幅
    coefficient: float               # 使用的传导系数
    source: str = "us_sector_transmission"


@dataclass
class TransmissionResult:
    """传导修正结果。"""

    adjustments: list[SectorAdjustment] = field(default_factory=list)
    active_signals: list[dict] = field(default_factory=list)  # 触发的信号摘要
    summary: str = ""                 # 一行总结: "存储-5, AI-3, 消费电子-2"
    data_available: bool = False      # 是否有足够数据支撑修正


# ═══════════════════════════════════════════════════════════════════
# 领先/滞后窗口建模 (P3-2)
# ═══════════════════════════════════════════════════════════════════
#
# 理念来源: 投资资讯精读 doc 04（可信度 0.3，仅借鉴）
#   - 产业链现货价格异动（华强北 MLCC 囤货）→ 海外龙头（村田）
#     → A股对标（风华高科）滞后约 2 周
#   - 中美联动时间差 2-4 周
#
# 设计要点:
#   - 每个 SECTOR_MAP 映射可携带可选 "lead_lag" 配置
#   - 无配置 → LeadLagWindow(0,0)，行为与现状一致（当日直接传导）
#   - 分段时滞 stages 描述"上游现货异动 → 海外龙头 → A股对标"的逐级延迟
#   - to_leading_signals() 把当日触发信号投影成"未来 N 日窗口的领先信号"
#   - 领先信号一律标注 [SPECULATION]，不作为强信号


@dataclass(frozen=True)
class LeadLagStage:
    """分段时滞的一环（上游现货异动 → 海外龙头 → A股对标）。"""

    name: str                          # 阶段名，如 "上游现货异动"、"海外龙头"
    lag_days: int                      # 本阶段名义滞后天数
    signal_strength: float = 1.0       # 通过该阶段的信号强度 0~1（信息逐级衰减）


@dataclass(frozen=True)
class LeadLagWindow:
    """领先/滞后窗口。

    lag_min_days == lag_max_days == 0 → 当日直接传导（默认，向后兼容）。
    """

    lag_min_days: int = 0
    lag_max_days: int = 0
    stages: tuple[LeadLagStage, ...] = field(default_factory=tuple)
    decay_per_week: float = 0.30       # 每滞后一周的强度衰减因子（分母衰减）

    @property
    def is_same_day(self) -> bool:
        return self.lag_min_days == 0 and self.lag_max_days == 0

    @property
    def mid_days(self) -> float:
        return (self.lag_min_days + self.lag_max_days) / 2.0

    @property
    def staged_decay(self) -> float:
        """分段信号强度乘积（无分段时为 1.0）。"""
        if not self.stages:
            return 1.0
        p = 1.0
        for s in self.stages:
            p *= max(0.0, min(1.0, s.signal_strength))
        return p

    def to_dict(self) -> dict:
        return {
            "lag_min_days": self.lag_min_days,
            "lag_max_days": self.lag_max_days,
            "stages": [
                {"name": s.name, "lag_days": s.lag_days,
                 "signal_strength": s.signal_strength}
                for s in self.stages
            ],
            "decay_per_week": self.decay_per_week,
            "is_same_day": self.is_same_day,
        }


@dataclass(frozen=True)
class LeadSignal:
    """把当日传导信号投影到未来 N 日窗口的领先信号。

    speculation 恒为 True —— 领先窗口来自 doc 04（可信度 0.3），
    只作弱信号参考，不得作为强信号进入交易决策。
    """

    us_key: str
    us_label: str
    sector: str                        # A股受影响板块
    direction: int                     # +1 利好 / -1 利空
    strength: float                    # 0~1，含分段衰减 + 周时间衰减
    window_start_days: int             # 从今日起的窗口起点（天）
    window_end_days: int               # 从今日起的窗口终点（天）
    raw_adjust: float                  # 原始修正值
    reason: str = ""
    window_start: Optional[date] = None   # 提供 as_of 时填充实际日期
    window_end: Optional[date] = None
    source: str = "us_sector_transmission_leadlag"
    speculation: bool = True


# ═══════════════════════════════════════════════════════════════════
# 可插拔真实数据源 (P3-2 遗留项) — 为 lead-lag 管道注入上游/海外领先信号
# ═══════════════════════════════════════════════════════════════════
#
# 理念来源: 投资资讯精读 doc 04（可信度 0.3）
#   "华强北 MLCC 囤货 → 村田(MU) → A股对标(风华高科) 滞后约 2 周"
#
# 现状（遗留）: to_leading_signals() 只由 SECTOR_MAP 配置驱动 —— 用当日美股
#   板块异动投影未来窗口。缺失的是更上游的"现货价格异动 / 海外龙头股价"真实数据。
#
# 本段引入 LeadSignalSource 可插拔接口:
#   - 任何实现 fetch() 的数据源均可被 lead-lag 管道消费
#   - 网络/解析失败必须返回 []（优雅降级），调用方回退到 SECTOR_MAP 配置驱动路径
#   - 无任何数据源配置时行为与现状完全一致（向后兼容）
#   - 数据源信号一律标 [SPECULATION]，幅度受限（弱信号）


@dataclass(frozen=True)
class LeadSourceSignal:
    """上游/海外领先信号 — 来自真实数据源的一次现货价/股价异动。

    category 采用命名空间形式: "commodity.CU" / "us_stock.MU"，
    命名空间前缀决定领先窗口（见 LEAD_NAMESPACE_WINDOW_MAP）。
    """

    category: str                       # 类别，如 "commodity.CU"
    name: str                           # 显示名称，如 "沪铜"
    change_pct: float                   # 异动幅度（%），正=涨 负=跌
    as_of: Optional[date] = None        # 信号对应日期
    source: str = ""                    # 数据源标识
    target_sectors: tuple[str, ...] = ()   # 影响的 A 股板块（空=按 name 兜底）
    confidence: float = 0.5             # 数据置信度 0~1


class LeadSignalSource(ABC):
    """可插拔领先信号数据源接口。

    实现要求:
      - name: 唯一标识
      - fetch(category): 返回 list[LeadSourceSignal]；**任何失败返回 []，
        绝不抛异常**（优雅降级到配置驱动路径）
    """

    name: str = "base"

    def is_available(self) -> bool:
        """默认可用；依赖网络/鉴权的子类应覆盖。"""
        return True

    @abstractmethod
    def fetch(self, category: str = "") -> list[LeadSourceSignal]:
        """获取领先信号。

        Args:
            category: 可选过滤（如 "commodity.CU"）；空=全部。

        Returns:
            list[LeadSourceSignal]；失败返回 []。
        """
        raise NotImplementedError


# 领先信号幅度上限 — 现货/股价异动被限幅后再进管道（[SPECULATION] 弱信号）
SOURCE_MAX_CHANGE = 8.0    # 单条信号原始幅度上限(%)，避免极端行情过度外推
SOURCE_CHANGE_TO_STRENGTH = 10.0   # 10% 异动 → strength 1.0

# 命名空间 → 领先窗口配置（上游现货 2-4 周 / 海外龙头 1-2 周，doc 04）
LEAD_NAMESPACE_WINDOW_MAP: dict[str, dict] = {
    "commodity": {
        "lag_days": [14, 28],
        "stages": [
            {"name": "上游现货异动", "lag_days": 4, "signal_strength": 0.9},
            {"name": "海外龙头", "lag_days": 10, "signal_strength": 0.8},
            {"name": "A股对标", "lag_days": 6, "signal_strength": 0.9},
        ],
        "decay_per_week": 0.30,
    },
    "us_stock": {
        "lag_days": [7, 14],
        "stages": [
            {"name": "海外龙头", "lag_days": 5, "signal_strength": 0.85},
            {"name": "A股对标", "lag_days": 5, "signal_strength": 0.9},
        ],
        "decay_per_week": 0.25,
    },
}


# 模块级数据源注册表（进程内显式注册）
_LEAD_SOURCE_REGISTRY: dict[str, LeadSignalSource] = {}


def register_lead_signal_source(source: LeadSignalSource) -> None:
    """显式注册一个领先信号数据源（进程内）。"""
    _LEAD_SOURCE_REGISTRY[source.name] = source


def clear_lead_signal_sources() -> None:
    """清空数据源注册表（测试用）。"""
    _LEAD_SOURCE_REGISTRY.clear()


def _env_enabled_sources() -> list[LeadSignalSource]:
    """按环境变量 AI_STOCK_LEAD_SOURCES 懒加载数据源。

    支持逗号分隔 token，如 "futures_spot"。未配置 → 空列表（向后兼容）。
    环境变量是"开关"：生产环境设 AI_STOCK_LEAD_SOURCES=futures_spot 即可启用，
    网络不可用时该源 fetch() 返回 []，自动回退到配置驱动路径。
    """
    import os

    raw = os.environ.get("AI_STOCK_LEAD_SOURCES", "").strip()
    if not raw:
        return []
    out: list[LeadSignalSource] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if token in ("futures_spot", "futures"):
            try:
                from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
                out.append(FuturesSpotLeadSource())
            except Exception as exc:
                logger.debug("env lead source '%s' init failed: %s", token, exc)
    return out


def get_lead_signal_sources() -> list[LeadSignalSource]:
    """返回当前生效的数据源列表（显式注册 + 环境变量配置）。

    默认（无注册、无环境变量）返回 [] → to_leading_signals 行为与现状一致。
    """
    return list(_LEAD_SOURCE_REGISTRY.values()) + _env_enabled_sources()


def source_signal_to_lead(
    src_sig: LeadSourceSignal,
    as_of: Optional[date] = None,
    horizon_days: int = 60,
) -> list[LeadSignal]:
    """把一条上游/海外数据源信号转换为 LeadSignal 列表（逐板块）。

    - 按 category 命名空间查领先窗口（未知命名空间 → 上游现货窗口兜底）
    - 幅度受限：change_pct 先限幅到 ±SOURCE_MAX_CHANGE，再计算 strength
    - 恒标 [SPECULATION]，置信度参与 strength 折算
    - 窗口起点超出 horizon_days → 丢弃
    """
    if src_sig is None:
        return []

    namespace = (src_sig.category or "commodity").split(".")[0]
    window_cfg = LEAD_NAMESPACE_WINDOW_MAP.get(
        namespace, LEAD_NAMESPACE_WINDOW_MAP["commodity"]
    )
    window = build_lead_lag_window(window_cfg)
    if window.lag_min_days > horizon_days:
        return []

    window_end = min(window.lag_max_days, horizon_days)
    if window_end < window.lag_min_days:
        return []

    raw = max(-SOURCE_MAX_CHANGE, min(SOURCE_MAX_CHANGE, float(src_sig.change_pct)))
    direction = 1 if raw >= 0 else -1
    base = min(1.0, abs(raw) / SOURCE_CHANGE_TO_STRENGTH)
    staged = window.staged_decay
    mid_weeks = window.mid_days / 7.0
    time_decay = 1.0 / (1.0 + window.decay_per_week * mid_weeks)
    strength = round(
        max(0.0, min(1.0, base * staged * time_decay * float(src_sig.confidence))), 4
    )

    start_date = end_date = None
    if as_of is not None:
        start_date = as_of + timedelta(days=window.lag_min_days)
        end_date = as_of + timedelta(days=window_end)

    sectors = list(src_sig.target_sectors) or [src_sig.name]
    out: list[LeadSignal] = []
    for sector in sectors:
        out.append(LeadSignal(
            us_key=src_sig.category,
            us_label=f"{src_sig.name} 现货",
            sector=sector,
            direction=direction,
            strength=strength,
            window_start_days=window.lag_min_days,
            window_end_days=window_end,
            raw_adjust=round(raw, 2),
            reason=(
                f"[{src_sig.source}] {src_sig.name}现货{raw:+.1f}% → {sector} 未来"
                f"{window.lag_min_days}-{window_end}天窗口（[SPECULATION] 上游现货异动）"
            ),
            window_start=start_date,
            window_end=end_date,
            source="lead_source",
        ))
    return out


def build_lead_lag_window(config: Optional[dict]) -> LeadLagWindow:
    """从配置构建领先/滞后窗口。

    兼容两种输入格式：
      1. 原始配置: {"lag_days": [14, 28], "stages": [...], "decay_per_week": 0.3}
      2. to_dict() 输出: {"lag_min_days": 14, "lag_max_days": 28, ...}
    无配置 / 空 dict → 当日窗口 (0,0)。
    """
    if not config:
        return LeadLagWindow()

    stages_raw = config.get("stages") or []
    stages = tuple(
        LeadLagStage(
            name=str(s.get("name", "stage")),
            lag_days=max(0, int(s.get("lag_days", 0))),
            signal_strength=float(s.get("signal_strength", 1.0)),
        )
        for s in stages_raw
    )

    lag_min: int = 0
    lag_max: int = 0
    lag_days = config.get("lag_days")
    if lag_days is not None and len(lag_days) == 2:
        lag_min = max(0, int(lag_days[0]))
        lag_max = max(lag_min, int(lag_days[1]))
    elif "lag_min_days" in config or "lag_max_days" in config:
        lag_min = max(0, int(config.get("lag_min_days", 0)))
        lag_max = max(lag_min, int(config.get("lag_max_days", 0)))
    elif stages:
        total = sum(s.lag_days for s in stages)
        lag_min = max(0, round(total * 0.85))
        lag_max = max(lag_min, round(total * 1.25))

    return LeadLagWindow(
        lag_min_days=lag_min,
        lag_max_days=lag_max,
        stages=stages,
        decay_per_week=float(config.get("decay_per_week", 0.30)),
    )


def resolve_lead_lag_window(mapping: dict) -> LeadLagWindow:
    """从单条 SECTOR_MAP 映射解析窗口（无 lead_lag → 当日窗口）。"""
    return build_lead_lag_window(mapping.get("lead_lag"))


def to_leading_signals(
    tx_result: TransmissionResult,
    as_of: Optional[date] = None,
    horizon_days: int = 60,
    lead_sources: Optional[Sequence[LeadSignalSource]] = None,
) -> list[LeadSignal]:
    """把当日传导信号 + 上游/海外数据源信号 转成"未来 N 日窗口的领先信号"。

    对每条触发的 active_signal：
      - 解析其 lead_lag_window（无配置 → 当日窗口 0,0）
      - 生效窗口 = [lag_min, lag_max] 未来天数（截断到 horizon_days）
      - strength = min(1, |raw_adjust|/10) × 分段衰减 × 周时间衰减
      - 窗口起点已超出 horizon_days → 跳过
      - 逐板块产出 LeadSignal

    附加: 当 lead_sources 提供（或经注册表/环境变量启用）时，把真实数据源的
      上游现货/海外龙头信号也转换为 LeadSignal（[SPECULATION]，幅度受限）追加到结果。
      lead_sources=None → 查 get_lead_signal_sources()；无任何数据源 → 行为与现状一致。

    Returns:
        领先信号列表（每条 speculation=True）
    """
    if tx_result is None:
        return []

    out: list[LeadSignal] = []
    for sig in tx_result.active_signals:
        window = build_lead_lag_window(sig.get("lead_lag_window"))
        if window.lag_min_days > horizon_days:
            continue
        window_end = min(window.lag_max_days, horizon_days)
        if window_end < window.lag_min_days:
            continue

        raw = float(sig.get("raw_adjust", 0.0) or 0.0)
        direction = 1 if raw >= 0 else -1
        base = min(1.0, abs(raw) / 10.0)
        staged = window.staged_decay
        mid_weeks = window.mid_days / 7.0
        time_decay = 1.0 / (1.0 + window.decay_per_week * mid_weeks)
        strength = round(max(0.0, min(1.0, base * staged * time_decay)), 4)

        start_date = end_date = None
        if as_of is not None:
            start_date = as_of + timedelta(days=window.lag_min_days)
            end_date = as_of + timedelta(days=window_end)

        us_label = sig.get("us_label", sig.get("us_key", ""))
        chg = sig.get("change_pct", raw)
        for sector in sig.get("sectors", []) or []:
            out.append(LeadSignal(
                us_key=sig.get("us_key", ""),
                us_label=us_label,
                sector=sector,
                direction=direction,
                strength=strength,
                window_start_days=window.lag_min_days,
                window_end_days=window_end,
                raw_adjust=raw,
                reason=(
                    f"{us_label}{chg:+.1f}% → {sector} 未来"
                    f"{window.lag_min_days}-{window_end}天窗口（[SPECULATION]）"
                ),
                window_start=start_date,
                window_end=end_date,
            ))

    # ---- 真实数据源注入（可插拔，[SPECULATION] 弱信号，幅度受限）----
    # 上游现货异动/海外龙头信号 → 生成/增强对应 A 股对标的领先信号。
    # 数据源 fetch 失败返回 [] 或抛异常 → 优雅降级，不影响配置驱动路径。
    sources = list(lead_sources) if lead_sources is not None else get_lead_signal_sources()
    for src in sources:
        if src is None:
            continue
        try:
            fetched = src.fetch()
        except Exception as exc:
            logger.debug(
                "lead source '%s' fetch failed (degrade): %s",
                getattr(src, "name", "?"), exc,
            )
            continue
        for s in fetched or []:
            out.extend(source_signal_to_lead(s, as_of=as_of, horizon_days=horizon_days))
    return out


def build_lead_signals(
    tx_result: TransmissionResult,
    lead_sources: Optional[Sequence[LeadSignalSource]] = None,
    as_of: Optional[date] = None,
    horizon_days: int = 60,
) -> list[LeadSignal]:
    """便捷入口: 配置驱动 + 显式数据源 组合生成领先信号。

    等价于 to_leading_signals(..., lead_sources=lead_sources)。
    """
    return to_leading_signals(
        tx_result, as_of=as_of, horizon_days=horizon_days, lead_sources=lead_sources
    )


def lead_signal_weak_adjust(
    lead_signals: list[LeadSignal],
    sector_candidates: list[str],
    cap: float = 3.0,
) -> float:
    """汇总领先信号为弱修正值（[SPECULATION]，doc 04 可信度 0.3）。

    仅对板块匹配的领先信号求和，每条约 direction×strength×2 分，
    总幅上限 ±cap —— 明显弱于当日直接传导的 macro_adjust。

    Args:
        lead_signals: to_leading_signals() 的输出
        sector_candidates: 该股所属板块候选（如 ["存储", "芯片"]）
        cap: 弱修正幅度上限

    Returns:
        弱修正值（[-cap, +cap]，可能为 0）
    """
    total = 0.0
    for ls in lead_signals:
        matched = any(
            ls.sector in sc or sc in ls.sector
            for sc in sector_candidates
        ) if sector_candidates else False
        if matched:
            total += ls.direction * ls.strength * 2.0
    return round(max(-cap, min(cap, total)), 2)


class UsSectorTransmissionAdjuster:
    """US 板块→A股板块 传导修正器。

    独立于数据源的纯逻辑层。只要传入 {us_key: change_pct} 的映射即可工作。
    """

    def compute(
        self,
        us_changes: dict[str, float],
    ) -> TransmissionResult:
        """根据美股标的涨跌幅计算A股板块修正。

        Args:
            us_changes: {us_key: change_pct} — e.g. {"MU": -5.38, "SOX": -3.33}

        Returns:
            TransmissionResult
        """
        if not us_changes:
            return TransmissionResult()

        # 按A股板块汇总修正值（加权求和）
        sector_adj: dict[str, float] = {}
        sector_reasons: dict[str, list[str]] = {}
        active_signals: list[dict] = []

        for mapping in SECTOR_MAP:
            key = mapping["us_key"]
            chg = us_changes.get(key)
            if chg is None:
                continue

            abs_chg = abs(chg)
            threshold = mapping["threshold"]
            if abs_chg < threshold:
                continue  # 日常波动，忽略

            coeff = mapping["coefficient"]
            weight = mapping["weight"]

            # 修正值 = 涨跌幅 × 系数 × 权重
            # 美股跌(-)→A股承压(-)，美股涨(+)→A股提振(+)
            adj_val = chg * coeff * weight

            reason = (
                f"{mapping['us_label']}{chg:+.1f}%→系数{coeff}"
            )

            active_signals.append({
                "us_key": key,
                "us_label": mapping["us_label"],
                "change_pct": round(chg, 2),
                "threshold": threshold,
                "coefficient": coeff,
                "weight": weight,
                "raw_adjust": round(adj_val, 2),
                "sectors": list(mapping["sectors"]),
                "lead_lag_window": resolve_lead_lag_window(mapping).to_dict(),
            })

            for sector in mapping["sectors"]:
                sector_adj[sector] = sector_adj.get(sector, 0.0) + adj_val
                if sector not in sector_reasons:
                    sector_reasons[sector] = []
                sector_reasons[sector].append(reason)

        if not sector_adj:
            return TransmissionResult(active_signals=active_signals)

        # 将连续修正值量化为整数评分偏移
        adjustments: list[SectorAdjustment] = []
        parts: list[str] = []
        for sector, raw_adj in sorted(sector_adj.items()):
            # 映射到评分偏移: 每 1% 美股波动 ≈ 2-3 分偏移
            # 用 min/max 限制偏移量
            adj_int = max(-15, min(15, int(round(raw_adj * 2.5))))
            if abs(adj_int) < 1:
                continue
            reasons = sector_reasons.get(sector, [])
            adjustments.append(SectorAdjustment(
                sector=sector,
                adjust=adj_int,
                reason="; ".join(reasons),
                us_change_pct=round(raw_adj, 2),
                coefficient=0.0,  # 汇总值，无单一系数
            ))
            sign = "+" if adj_int > 0 else ""
            parts.append(f"{sector}{sign}{adj_int}")

        return TransmissionResult(
            adjustments=adjustments,
            active_signals=active_signals,
            summary=" | ".join(parts),
            data_available=True,
        )

    @staticmethod
    def fetch_us_sector_data(
        global_market_snapshot=None,
    ) -> dict[str, float]:
        """获取关键美股标的隔夜涨跌幅。

        优先从已加载的 global_market_snapshot 读取，
        缺失的标的尝试通过东财API补充。

        Args:
            global_market_snapshot: 已有的 GlobalMarketSnapshot（可选）

        Returns:
            {us_key: change_pct} — 有数据的标的
        """
        result: dict[str, float] = {}

        # 1. 从已加载的快照中提取
        if global_market_snapshot is not None:
            # USIndexSnapshot 对象映射
            index_map = {
                "SPX": getattr(global_market_snapshot, "sp500", None),
                "NDX": getattr(global_market_snapshot, "nasdaq", None),
                "^GSPC": getattr(global_market_snapshot, "sp500", None),
                "^IXIC": getattr(global_market_snapshot, "nasdaq", None),
            }
            for key, idx in index_map.items():
                if idx is not None:
                    chg = getattr(idx, "change_pct", None)
                    if chg is not None:
                        result[key] = chg

        # 2. 东财API补充缺失标的
        missing = [k for k in EXTRA_US_SECIDS if k not in result]
        if missing:
            try:
                extra = _fetch_extra_us_tickers(missing)
                result.update(extra)
            except Exception as e:
                logger.debug("fetch_us_sector_data extra failed: %s", e)

        return result


def _fetch_extra_us_tickers(
    tickers: list[str],
    max_retries: int = 2,
) -> dict[str, float]:
    """通过东财push2 API拉取额外美股标的涨跌幅。

    Args:
        tickers: 需要拉取的标的key列表（如 ["SOX", "MU", "NVDA"]）

    Returns:
        成功获取的 {key: change_pct}
    """
    import time as _time

    # 构建 secids 列表
    valid_secids = []
    key_map: dict[str, str] = {}
    for key in tickers:
        secid = EXTRA_US_SECIDS.get(key)
        if secid:
            valid_secids.append(secid)
            key_map[secid] = key

    if not valid_secids:
        return {}

    # 分批拉取（每次最多10个，避免URL过长）
    batch_size = 10
    all_data: dict[str, dict] = {}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }

    for i in range(0, len(valid_secids), batch_size):
        batch = valid_secids[i:i + batch_size]
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            f"?fltt=2&invt=2&fields=f12,f14,f2,f3,f4"
            f"&secids={','.join(batch)}"
        )

        for attempt in range(max_retries):
            try:
                # 使用 curl_cffi（可用时），回退到 requests
                try:
                    from curl_cffi import requests as _req
                except ImportError:
                    import requests as _req  # type: ignore[no-redef]

                # 绕过系统代理
                import os as _os
                _os.environ["NO_PROXY"] = (
                    _os.environ.get("NO_PROXY", "")
                    + ",eastmoney.com,push2.eastmoney.com"
                )

                resp = _req.get(url, headers=headers, timeout=12, impersonate="chrome120")
                payload = resp.json()
                items = (payload.get("data") or {}).get("diff", [])
                for item in items:
                    secid = str(item.get("f12", ""))
                    chg = item.get("f3")
                    name = item.get("f14", "")
                    if secid in key_map and chg is not None and name:
                        all_data[secid] = {"change_pct": float(chg), "name": name}
                break  # 成功则跳出重试
            except Exception as exc:
                logger.debug(
                    "fetch_extra tickers batch %d attempt %d: %s",
                    i // batch_size, attempt + 1, exc,
                )
                if attempt < max_retries - 1:
                    _time.sleep(1.5 ** attempt)

    result: dict[str, float] = {}
    for secid, data in all_data.items():
        key = key_map.get(secid, "")
        if key:
            result[key] = data["change_pct"]
    return result
