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
    ) -> Feedback:
        """标注交易结果。

        Args:
            signal_id: 信号 ID
            actual_return: 实际收益率（小数，如 0.08 = 8%）
            lesson: 经验教训
            holding_days: 持仓天数
        """
        return self._add(Feedback(
            feedback_id=self._next_id(),
            signal_id=signal_id,
            type=FeedbackType.ANNOTATE,
            actual_return=actual_return,
            holding_days=holding_days,
            lesson=lesson,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
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
