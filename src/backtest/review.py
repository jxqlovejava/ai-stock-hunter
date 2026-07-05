"""Trade review & post-mortem analysis module.

Records trades with entry/exit rationale, computes deviation analysis,
generates optimization feedback for strategy parameters and doctrine rules.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_DIR = Path.home() / ".ai-stock-hunter" / "reviews"


@dataclass
class TradeReview:
    """Single trade post-mortem record."""

    review_id: str = ""
    symbol: str = ""
    name: str = ""
    entry_date: str = ""
    exit_date: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    position_pct: float = 0.0  # % of portfolio
    return_pct: float = 0.0
    holding_days: int = 0

    # Rationale
    entry_reason: str = ""
    exit_reason: str = ""
    strategy: str = ""  # which strategy/playbook
    doctrine_rules_applied: list[str] = field(default_factory=list)

    # Deviation analysis
    expected_return_pct: Optional[float] = None  # what we expected
    deviation_reason: str = ""  # why actual ≠ expected
    was_exit_forced: bool = False  # hit stop-loss or time stop

    # Improvement
    lessons: str = ""
    suggested_param_changes: list[dict] = field(default_factory=list)
    severity: str = "info"  # "critical" / "warning" / "info"

    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReviewStats:
    """Aggregated review statistics."""

    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0  # gross profit / gross loss
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_holding_days: float = 0.0

    # Error categories
    error_categories: dict[str, int] = field(default_factory=dict)  # reason → count
    doctrine_violations: dict[str, int] = field(default_factory=dict)  # rule → count

    # Top lessons
    top_lessons: list[str] = field(default_factory=list)


class TradeReviewer:
    """Record, analyze, and learn from trade outcomes."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self._storage_dir = storage_dir or DEFAULT_REVIEW_DIR
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, review: TradeReview) -> str:
        """Save a trade review."""
        import uuid
        if not review.review_id:
            review.review_id = str(uuid.uuid4())[:8]

        filepath = self._storage_dir / f"{review.review_id}.json"
        filepath.write_text(json.dumps(self._serialize(review), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Review saved: %s (%s %+.2f%%)", review.review_id, review.symbol, review.return_pct)
        return review.review_id

    def load_all(self, symbol: Optional[str] = None) -> list[TradeReview]:
        """Load all reviews, optionally filtered by symbol."""
        reviews = []
        for f in sorted(self._storage_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                r = self._deserialize(data)
                if symbol is None or r.symbol == symbol:
                    reviews.append(r)
            except Exception:
                continue
        return reviews

    def stats(self, symbol: Optional[str] = None) -> ReviewStats:
        """Compute aggregated review statistics."""
        reviews = self.load_all(symbol)
        stats = ReviewStats(total_trades=len(reviews))

        if not reviews:
            return stats

        wins = [r for r in reviews if r.return_pct > 0]
        losses = [r for r in reviews if r.return_pct <= 0]
        stats.win_count = len(wins)
        stats.loss_count = len(losses)
        stats.win_rate = len(wins) / len(reviews) if reviews else 0
        stats.avg_return_pct = sum(r.return_pct for r in reviews) / len(reviews)
        stats.avg_win_pct = sum(r.return_pct for r in wins) / len(wins) if wins else 0
        stats.avg_loss_pct = sum(r.return_pct for r in losses) / len(losses) if losses else 0

        gross_profit = sum(r.return_pct for r in wins)
        gross_loss = abs(sum(r.return_pct for r in losses))
        stats.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Consecutive streaks
        max_cw = cur_cw = 0
        max_cl = cur_cl = 0
        for r in sorted(reviews, key=lambda x: x.entry_date):
            if r.return_pct > 0:
                cur_cw += 1
                cur_cl = 0
                max_cw = max(max_cw, cur_cw)
            else:
                cur_cl += 1
                cur_cw = 0
                max_cl = max(max_cl, cur_cl)
        stats.max_consecutive_wins = max_cw
        stats.max_consecutive_losses = max_cl

        stats.avg_holding_days = sum(r.holding_days for r in reviews) / len(reviews)

        # Error categories
        for r in reviews:
            reason = r.deviation_reason or "unspecified"
            stats.error_categories[reason] = stats.error_categories.get(reason, 0) + 1
            for rule in r.doctrine_rules_applied:
                stats.doctrine_violations[rule] = stats.doctrine_violations.get(rule, 0) + 1

        # Top lessons
        lessons = [r.lessons for r in reviews if r.lessons]
        if lessons:
            stats.top_lessons = lessons[-5:]  # most recent 5

        return stats

    def generate_feedback(self) -> list[dict]:
        """Generate optimization feedback from review patterns.

        Returns list of suggested parameter changes for strategies and doctrine rules.
        """
        stats = self.stats()
        feedback = []

        # Win rate feedback
        if stats.win_rate < 0.4 and stats.total_trades >= 10:
            feedback.append({
                "target": "strategy_entry_filter",
                "suggestion": "tighten_entry_criteria",
                "reason": f"Win rate {stats.win_rate:.0%} < 40% — add confirmation signals or increase required confidence threshold",
                "severity": "high",
            })

        # Profit factor feedback
        if stats.profit_factor < 1.0 and stats.total_trades >= 10:
            feedback.append({
                "target": "position_sizing",
                "suggestion": "reduce_max_position",
                "reason": f"Profit factor {stats.profit_factor:.1f} < 1.0 — reduce single-position cap or increase stop-loss tightness",
                "severity": "high",
            })

        # Holding period feedback
        if stats.avg_holding_days < 3 and stats.total_trades >= 5:
            feedback.append({
                "target": "strategy_holding_period",
                "suggestion": "extend_holding_or_skip_short_term",
                "reason": f"Avg holding {stats.avg_holding_days:.1f} days — consider T+1 friction cost; may be overtrading",
                "severity": "medium",
            })

        # Loss size feedback
        if stats.avg_loss_pct < -8 and stats.total_trades >= 5:
            feedback.append({
                "target": "risk_management",
                "suggestion": "tighten_stop_loss",
                "reason": f"Avg loss {stats.avg_loss_pct:.1f}% — tighten stop-loss from current to {abs(stats.avg_loss_pct) * 0.6:.0f}%",
                "severity": "high",
            })

        # Streak feedback
        if stats.max_consecutive_losses >= 5:
            feedback.append({
                "target": "strategy_pause_rule",
                "suggestion": "add_consecutive_loss_circuit_breaker",
                "reason": f"Max {stats.max_consecutive_losses} consecutive losses — pause strategy after 3 consecutive losses for review",
                "severity": "medium",
            })

        # Top doctrine violations
        for rule, count in stats.doctrine_violations.items():
            if count >= 3:
                feedback.append({
                    "target": f"doctrine_rule_{rule}",
                    "suggestion": "tighten_rule_or_add_auto_block",
                    "reason": f"Rule '{rule}' violated {count} times — consider auto-reject or increase severity level",
                    "severity": "medium",
                })

        return feedback

    def dashboard(self) -> str:
        """Generate text-based review dashboard."""
        stats = self.stats()
        lines = [
            "=" * 50,
            "  交易复盘看板",
            "=" * 50,
            f"  总交易: {stats.total_trades} | 胜: {stats.win_count} | 负: {stats.loss_count}",
            f"  胜率: {stats.win_rate:.1%} | 平均收益: {stats.avg_return_pct:+.2f}%",
            f"  盈亏比: {stats.profit_factor:.2f} | 平均持仓: {stats.avg_holding_days:.0f}天",
            f"  最大连胜: {stats.max_consecutive_wins} | 最大连亏: {stats.max_consecutive_losses}",
            "",
            "  --- 错误分类 ---",
        ]
        for cat, count in sorted(stats.error_categories.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {cat}: {count}次")
        if stats.top_lessons:
            lines.append("")
            lines.append("  --- 最近教训 ---")
            for lesson in stats.top_lessons:
                lines.append(f"  • {lesson[:100]}")
        lines.append("=" * 50)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _serialize(self, r: TradeReview) -> dict:
        return {
            "review_id": r.review_id,
            "symbol": r.symbol,
            "name": r.name,
            "entry_date": r.entry_date,
            "exit_date": r.exit_date,
            "entry_price": r.entry_price,
            "exit_price": r.exit_price,
            "position_pct": r.position_pct,
            "return_pct": r.return_pct,
            "holding_days": r.holding_days,
            "entry_reason": r.entry_reason,
            "exit_reason": r.exit_reason,
            "strategy": r.strategy,
            "doctrine_rules_applied": r.doctrine_rules_applied,
            "expected_return_pct": r.expected_return_pct,
            "deviation_reason": r.deviation_reason,
            "was_exit_forced": r.was_exit_forced,
            "lessons": r.lessons,
            "suggested_param_changes": r.suggested_param_changes,
            "severity": r.severity,
            "created_at": r.created_at.isoformat(),
        }

    def _deserialize(self, data: dict) -> TradeReview:
        return TradeReview(
            review_id=data.get("review_id", ""),
            symbol=data.get("symbol", ""),
            name=data.get("name", ""),
            entry_date=data.get("entry_date", ""),
            exit_date=data.get("exit_date", ""),
            entry_price=data.get("entry_price", 0),
            exit_price=data.get("exit_price", 0),
            position_pct=data.get("position_pct", 0),
            return_pct=data.get("return_pct", 0),
            holding_days=data.get("holding_days", 0),
            entry_reason=data.get("entry_reason", ""),
            exit_reason=data.get("exit_reason", ""),
            strategy=data.get("strategy", ""),
            doctrine_rules_applied=data.get("doctrine_rules_applied", []),
            expected_return_pct=data.get("expected_return_pct"),
            deviation_reason=data.get("deviation_reason", ""),
            was_exit_forced=data.get("was_exit_forced", False),
            lessons=data.get("lessons", ""),
            suggested_param_changes=data.get("suggested_param_changes", []),
            severity=data.get("severity", "info"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )
