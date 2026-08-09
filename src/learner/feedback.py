# -*- coding: utf-8 -*-
"""用户反馈收集系统。

提供结构化反馈收集，支持 4 种反馈类型:
  - agree: 赞同系统信号
  - disagree: 反对系统信号并记录实际决策
  - adjust: 调整策略参数
  - annotate: 标注交易结果与教训

反馈数据用于后续策略权重校准和进化。

用法:
    collector = FeedbackCollector()
    collector.agree("SIG_001", "看好基本面，认同买入")
    collector.disagree("SIG_002", "估值过高，暂不买入", user_action="HOLD")
    collector.adjust("SIG_003", "stop_loss_pct", -0.15, -0.20, "波动大需更宽止损")
    collector.annotate_outcome("SIG_001", 0.08, "持有 20 天获利 8%")
    summary = collector.summary()
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FeedbackType(Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    ADJUST = "adjust"
    ANNOTATE = "annotate"


class MistakeType(Enum):
    """结构化错误分类 — 复盘教训去空话的枚举化基础。

    交易后复盘必须落到具体错误类别，禁止用"操作失误/行情不好"空话。
    """
    NONE = "none"                          # 无错误 / 未分类
    CHASED_MOVE = "chased_move"            # 追涨杀跌
    IGNORED_NEWS_CONFLICT = "ignored_news_conflict"  # 忽视信息冲突
    STOP_TOO_TIGHT = "stop_too_tight"      # 止损过紧
    STOP_TOO_WIDE = "stop_too_wide"        # 止损过宽
    OVERLEVERAGED = "overleveraged"        # 过度杠杆
    HELD_TOO_LONG = "held_too_long"        # 持仓过久

    @classmethod
    def _missing_(cls, value):
        """未知值回退到 NONE，保证旧数据向后兼容。"""
        return cls.NONE


class AttributionType(Enum):
    """盈亏归因分类 — 技术 vs 运气 / 行情 vs 操作（借鉴自媒体《复盘6步法》）。

    复盘必须区分"盈利是技术还是运气"、"亏损是行情还是操作"，
    杜绝把运气当技术、把操作失误赖给行情（避免重复犯同样的错）。
    """
    SYSTEM_EXECUTED = "system_executed"  # 严格执行计划 = 技术
    LUCKY_MARKET = "lucky_market"        # 赌对行情 = 运气
    SYSTEMIC_LOSS = "systemic_loss"      # 行情系统性杀跌（非操作问题）
    EXECUTION_ERROR = "execution_error"  # 操作失误（追高 / 不设止损 / 心存侥幸）
    MIXED = "mixed"                      # 技术 + 运气兼有
    UNKNOWN = "unknown"                  # 未分类

    @classmethod
    def _missing_(cls, value):
        """未知值回退到 UNKNOWN，保证旧数据向后兼容。"""
        return cls.UNKNOWN


# 自由文本 → MistakeType 的关键词映射（用于 deviation_reason / 卖出原因 分类）
_MISTAKE_KEYWORDS: dict[MistakeType, tuple[str, ...]] = {
    MistakeType.CHASED_MOVE: (
        "追涨", "追高", "打板", "高位买入", "追进去", "追涨杀跌", "chase", "高位接力",
    ),
    MistakeType.IGNORED_NEWS_CONFLICT: (
        "忽视", "忽略", "无视", "利空", "公告", "消息", "逆势", "ignored", "冲突",
        "利好兑现", "信息不对称",
    ),
    MistakeType.STOP_TOO_TIGHT: (
        "止损过紧", "止损太紧", "被洗", "洗盘", "过早止损", "止损被打", "stop too tight",
        "震动出局", "止损位太低",
    ),
    MistakeType.STOP_TOO_WIDE: (
        "止损过宽", "止损太宽", "不止损", "扛单", "亏损扩大", "止损太慢", "没有止损",
        "stop too wide", "止损设置过高", "没及时止损",
    ),
    MistakeType.OVERLEVERAGED: (
        "杠杆", "满仓", "重仓", "融资", "梭哈", "overleveraged", "仓位过重", "加杠杆",
        "过度仓位", "透支",
    ),
    MistakeType.HELD_TOO_LONG: (
        "持仓过久", "拿太久", "持有太久", "利润回吐", "坐过山车", "held too long",
        "止盈不及时", "拿不住利润", "该走没走",
    ),
}


def mistake_type_from_text(text: str) -> MistakeType:
    """把自由文本错误描述映射到结构化 MistakeType。

    Args:
        text: 复盘文本（如 deviation_reason / 卖出原因 / 教训）

    Returns:
        匹配的 MistakeType；无匹配返回 NONE。
    """
    if not text:
        return MistakeType.NONE
    lowered = text.lower()
    for mt, kws in _MISTAKE_KEYWORDS.items():
        for kw in kws:
            if kw in lowered:
                return mt
    return MistakeType.NONE


# 复盘教训空话黑名单 — 命中即拒绝，强制具体化
VAGUE_LESSON_KEYWORDS: tuple[str, ...] = (
    "操作失误", "行情不好", "没拿住", "心态不好", "运气不好", "没操作好",
    "说不清", "忘了", "大盘不好", "市场不好", "随缘", "没办法",
)


def validate_lesson_specificity(lesson: str) -> tuple[bool, str]:
    """校验复盘教训是否具体（禁止"操作失误/行情不好"空话）。

    Args:
        lesson: 复盘教训文本

    Returns:
        (ok, message) — ok=False 时 message 说明拒绝原因。
    """
    if not lesson or not lesson.strip():
        return False, "教训不能为空"
    text = lesson.strip()
    if len(text) < 4:
        return False, "教训太短，请描述具体过程（如: 突破假信号追高被套，未等回踩确认）"
    for kw in VAGUE_LESSON_KEYWORDS:
        if kw in text:
            return False, (
                f"教训过于空泛（含'{kw}'），请具体说明哪里做错了、当时缺了什么信息、下次如何改进"
            )
    return True, ""


@dataclass
class Feedback:
    """单条反馈记录。"""

    feedback_id: str
    signal_id: str
    type: FeedbackType
    reason: str = ""
    user_action: str = ""
    param_name: str = ""
    old_value: Optional[float] = None
    new_value: Optional[float] = None
    actual_return: Optional[float] = None
    holding_days: Optional[int] = None
    lesson: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    strategy_name: str = ""
    strategy_version: str = ""
    # Phase 4: Alpha 归因
    alpha_contribution_pct: Optional[float] = None  # Alpha 贡献占比
    alpha_quality_score: Optional[float] = None     # Alpha 来源质量 0-100
    # P2-1: 结构化错误分类（向后兼容，默认 NONE）
    mistake_type: MistakeType = MistakeType.NONE    # 错误类型
    symbol: str = ""                                # 标的代码（交易反馈用）
    result: str = ""                                # 结果: win / loss / flat
    # P2-2: 盈亏归因（技术 vs 运气 / 行情 vs 操作，向后兼容默认 UNKNOWN）
    attribution: AttributionType = AttributionType.UNKNOWN


@dataclass
class FeedbackSummary:
    """反馈汇总统计。"""

    total: int = 0
    agree_count: int = 0
    disagree_count: int = 0
    adjust_count: int = 0
    annotate_count: int = 0
    agreement_rate: float = 0.0  # 用户与系统一致率
    avg_actual_return: Optional[float] = None
    total_adjustments: dict[str, list[dict]] = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)
    by_strategy: dict[str, dict] = field(default_factory=dict)
    period_start: str = ""
    period_end: str = ""
    # P2-1: 错误类型分布 (mistake_type.value → count)
    mistake_types: dict[str, int] = field(default_factory=dict)
    # P2-2: 盈亏归因分布 (attribution.value → count)
    attribution_counts: dict[str, int] = field(default_factory=dict)


class FeedbackCollector:
    """用户反馈收集器。

    收集用户对系统信号的结构化反馈，支持持久化到 JSON 文件。

    用法:
        collector = FeedbackCollector()
        collector.agree("SIG_001", "认同系统判断")
        summary = collector.summary(strategy_name="MVP1")
    """

    def __init__(self, db_path: str = "data/feedback.json"):
        self._path = db_path
        self._feedbacks: list[Feedback] = []
        self._counter = 0
        self._memory_store = None  # lazy init: src.memory.MemoryStore
        self._memory_only = db_path == ":memory:"
        if not self._memory_only:
            self._load()

    # ------------------------------------------------------------------
    # 反馈类型
    # ------------------------------------------------------------------

    def agree(
        self,
        signal_id: str,
        reason: str = "",
        strategy_name: str = "",
        strategy_version: str = "",
    ) -> Feedback:
        """赞同系统信号。"""
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=signal_id,
            type=FeedbackType.AGREE,
            reason=reason,
            user_action="FOLLOW",
            strategy_name=strategy_name,
            strategy_version=strategy_version,
        ))

    def disagree(
        self,
        signal_id: str,
        reason: str,
        user_action: str = "",
        strategy_name: str = "",
        strategy_version: str = "",
    ) -> Feedback:
        """反对系统信号。

        Args:
            signal_id: 信号 ID
            reason: 反对原因
            user_action: 用户实际操作 (HOLD / SELL / BUY_LESS / BUY_MORE)
        """
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=signal_id,
            type=FeedbackType.DISAGREE,
            reason=reason,
            user_action=user_action,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
        ))

    def adjust(
        self,
        signal_id: str,
        param_name: str,
        old_value: float,
        new_value: float,
        reason: str = "",
        strategy_name: str = "",
        strategy_version: str = "",
    ) -> Feedback:
        """调整策略参数。

        Args:
            signal_id: 信号 ID
            param_name: 参数名 (如 "stop_loss_pct")
            old_value: 旧值
            new_value: 新值
            reason: 调整原因
        """
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=signal_id,
            type=FeedbackType.ADJUST,
            param_name=param_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
        ))

    def annotate_outcome(
        self,
        signal_id: str,
        actual_return: float,
        lesson: str = "",
        holding_days: Optional[int] = None,
        strategy_name: str = "",
        strategy_version: str = "",
        mistake_type: MistakeType = MistakeType.NONE,
    ) -> Feedback:
        """标注交易结果。

        Args:
            signal_id: 信号 ID
            actual_return: 实际收益率（小数，如 0.08 = 8%）
            lesson: 经验教训
            holding_days: 持仓天数
            mistake_type: 结构化错误分类（默认无）
        """
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=signal_id,
            type=FeedbackType.ANNOTATE,
            actual_return=actual_return,
            holding_days=holding_days,
            lesson=lesson,
            mistake_type=mistake_type,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
        ))

    def record_trade_result(
        self,
        symbol: str,
        direction: str,
        result: str,
        mistake_type: MistakeType = MistakeType.NONE,
        attribution: AttributionType = AttributionType.UNKNOWN,
        lesson: str = "",
        actual_return: Optional[float] = None,
        holding_days: Optional[int] = None,
        strategy_name: str = "",
        signal_id: str = "",
    ) -> Feedback:
        """记录一笔交易结果反馈（供 feedback add CLI 与事件驱动复盘使用）。

        Args:
            symbol: 标的代码
            direction: 交易方向 (BUY / SELL / HOLD)
            result: 结果 (win / loss / flat)
            mistake_type: 结构化错误分类
            attribution: 盈亏归因（技术 vs 运气 / 行情 vs 操作）
            lesson: 具体教训（须通过 validate_lesson_specificity）
            actual_return: 实际收益率（小数）
            holding_days: 持仓天数
            strategy_name: 策略名
            signal_id: 关联信号 ID（默认用 TRADE_{symbol}）
        """
        sid = signal_id or f"TRADE_{symbol}"
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=sid,
            type=FeedbackType.ANNOTATE,
            reason=lesson,          # 兼容旧字段，保证 reason 有内容
            user_action=direction,  # 方向存入 user_action
            actual_return=actual_return,
            holding_days=holding_days,
            lesson=lesson,
            symbol=symbol,
            result=result,
            mistake_type=mistake_type,
            attribution=attribution,
            strategy_name=strategy_name,
        ))

    # ------------------------------------------------------------------
    # 查询与统计
    # ------------------------------------------------------------------

    def summary(
        self,
        strategy_name: str = "",
        since: Optional[str] = None,
    ) -> FeedbackSummary:
        """生成反馈汇总。

        Args:
            strategy_name: 按策略过滤（空 = 全部）
            since: 起始日期过滤 (ISO format)
        """
        items = self._feedbacks
        if strategy_name:
            items = [f for f in items if f.strategy_name == strategy_name]
        if since:
            items = [f for f in items if f.created_at >= since]

        if not items:
            return FeedbackSummary()

        types = [f.type for f in items]
        agree = sum(1 for t in types if t == FeedbackType.AGREE)
        disagree = sum(1 for t in types if t == FeedbackType.DISAGREE)
        total_decisions = agree + disagree

        # 一致率
        agreement_rate = agree / total_decisions if total_decisions > 0 else 0.0

        # 平均实际收益
        returns = [f.actual_return for f in items if f.actual_return is not None]
        avg_return = sum(returns) / len(returns) if returns else None

        # 参数调整汇总
        adjustments: dict[str, list[dict]] = {}
        for f in items:
            if f.type == FeedbackType.ADJUST and f.param_name:
                if f.param_name not in adjustments:
                    adjustments[f.param_name] = []
                adjustments[f.param_name].append({
                    "signal_id": f.signal_id,
                    "old_value": f.old_value,
                    "new_value": f.new_value,
                    "reason": f.reason,
                })

        # 教训汇总
        lessons = [f.lesson for f in items if f.lesson]

        # P2-1: 错误类型分布
        mistake_counts: dict[str, int] = {}
        for f in items:
            mt = f.mistake_type.value if f.mistake_type else "none"
            mistake_counts[mt] = mistake_counts.get(mt, 0) + 1

        # P2-2: 盈亏归因分布（技术 vs 运气 / 行情 vs 操作）
        attribution_counts: dict[str, int] = {}
        for f in items:
            at = f.attribution.value if f.attribution else "unknown"
            attribution_counts[at] = attribution_counts.get(at, 0) + 1

        # 按策略分组
        by_strategy: dict[str, dict] = {}
        for f in items:
            key = f.strategy_name or "(未分类)"
            if key not in by_strategy:
                by_strategy[key] = {"total": 0, "agree": 0, "disagree": 0}
            by_strategy[key]["total"] += 1
            if f.type == FeedbackType.AGREE:
                by_strategy[key]["agree"] += 1
            elif f.type == FeedbackType.DISAGREE:
                by_strategy[key]["disagree"] += 1

        dates = sorted([f.created_at for f in items])
        return FeedbackSummary(
            total=len(items),
            agree_count=agree,
            disagree_count=disagree,
            adjust_count=sum(1 for t in types if t == FeedbackType.ADJUST),
            annotate_count=sum(1 for t in types if t == FeedbackType.ANNOTATE),
            agreement_rate=agreement_rate,
            avg_actual_return=avg_return,
            total_adjustments=adjustments,
            lessons=lessons,
            by_strategy=by_strategy,
            period_start=dates[0] if dates else "",
            period_end=dates[-1] if dates else "",
            mistake_types=mistake_counts,
            attribution_counts=attribution_counts,
        )

    def get_by_signal(self, signal_id: str) -> list[Feedback]:
        """获取某信号的所有反馈。"""
        return [f for f in self._feedbacks if f.signal_id == signal_id]

    def get_disagreements(self, strategy_name: str = "") -> list[Feedback]:
        """获取所有反对记录，用于分析策略弱点。"""
        items = self._feedbacks
        if strategy_name:
            items = [f for f in items if f.strategy_name == strategy_name]
        return [f for f in items if f.type == FeedbackType.DISAGREE]

    def get_adjustments(self, param_name: str = "") -> list[Feedback]:
        """获取参数调整记录。"""
        items = self._feedbacks
        if param_name:
            items = [f for f in items if f.param_name == param_name]
        return [f for f in items if f.type == FeedbackType.ADJUST]

    def recent(self, days: int = 7) -> list[Feedback]:
        """获取最近 N 天的反馈。"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [f for f in self._feedbacks if f.created_at >= cutoff]

    def count(self) -> int:
        return len(self._feedbacks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._counter += 1
        return f"FB_{self._counter:06d}"

    def _add(self, feedback: Feedback) -> Feedback:
        self._feedbacks.append(feedback)
        self._save()
        return feedback

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self):
        if self._memory_only:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        data = []
        for f in self._feedbacks:
            data.append({
                "feedback_id": f.feedback_id,
                "signal_id": f.signal_id,
                "type": f.type.value,
                "reason": f.reason,
                "user_action": f.user_action,
                "param_name": f.param_name,
                "old_value": f.old_value,
                "new_value": f.new_value,
                "actual_return": f.actual_return,
                "holding_days": f.holding_days,
                "lesson": f.lesson,
                "created_at": f.created_at,
                "strategy_name": f.strategy_name,
                "strategy_version": f.strategy_version,
                "mistake_type": f.mistake_type.value if f.mistake_type else "none",
                "symbol": f.symbol,
                "result": f.result,
                "attribution": f.attribution.value if f.attribution else "unknown",
            })
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        max_id = 0
        for item in data:
            fb = Feedback(
                feedback_id=item["feedback_id"],
                signal_id=item["signal_id"],
                type=FeedbackType(item["type"]),
                reason=item.get("reason", ""),
                user_action=item.get("user_action", ""),
                param_name=item.get("param_name", ""),
                old_value=item.get("old_value"),
                new_value=item.get("new_value"),
                actual_return=item.get("actual_return"),
                holding_days=item.get("holding_days"),
                lesson=item.get("lesson", ""),
                created_at=item.get("created_at", ""),
                strategy_name=item.get("strategy_name", ""),
                strategy_version=item.get("strategy_version", ""),
                mistake_type=MistakeType(item.get("mistake_type", "none")),
                symbol=item.get("symbol", ""),
                result=item.get("result", ""),
                attribution=AttributionType(item.get("attribution", "unknown")),
            )
            self._feedbacks.append(fb)
            # Restore counter from ID
            try:
                num = int(item["feedback_id"].split("_")[-1])
                if num > max_id:
                    max_id = num
            except (ValueError, IndexError):
                pass
        self._counter = max_id
