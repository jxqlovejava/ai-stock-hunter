# -*- coding: utf-8 -*-
"""决策日志、复盘与学习模块。

导出:
  - DecisionJournal: 决策日志
  - ProfileTracker / UserProfile: 用户能力画像
  - FeedbackCollector / FeedbackSummary: 用户反馈收集
  - RuleCalibrator / FactorCalibrator / RiskParamCalibrator: 策略权重校准
  - EvolutionPipeline / EvolutionRecord: 策略进化编排
  - SignalTracker / SignalQualityReport: 信号质量追踪
  - ReportGenerator / LearningReport: 学习报告
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sqlite3

from datetime import datetime
from typing import Optional

from src.alpha.schema import AlphaProfile

logger = logging.getLogger(__name__)

from .calibrator import (
    Calibrator,
    CalibrationRecord,
    CalibrationResult,
    CalibrationReport,
    FactorCalibrator,
    RiskParamCalibrator,
    RuleCalibrator,
)
from .evolution import (
    EvolutionPipeline,
    EvolutionRecord,
    EvolutionStatus,
    GapAnalysis,
    ProposedChange,
)
from .feedback import (
    Feedback,
    FeedbackCollector,
    FeedbackSummary,
    FeedbackType,
    MistakeType,
    mistake_type_from_text,
    validate_lesson_specificity,
)
from .preference.adapter import (
    resolve_competence_penalty,
    resolve_macro_cap_multiplier,
    resolve_position_limits,
    resolve_rule_filter,
    resolve_weights,
)
from .preference.loader import InvestorPreferenceLoader
from .preference.model import (
    CircleOfCompetence,
    InvestmentGoal,
    InvestorPreference,
    InvestorTier,
    PositionLimits,
    RiskProfile,
    ScoreWeights,
    TradingStyle,
)
from .profile import ProfileTracker, UserProfile
from .report import LearningReport, ReportGenerator
from .signal_tracker import (
    Signal,
    SignalQualityReport,
    SignalStatus,
    SignalTracker,
)

# Phase 4: Alpha 归因引擎
from src.alpha.attribution import AlphaAttribution, AttributionReport


class DecisionJournal:
    """决策日志 — 记录每笔系统建议与用户实际操作。Phase 4: Alpha 归因。

    持久化到 SQLite（默认 ``data/journal.db``，可用 ``$BAIZE_JOURNAL_PATH`` 覆盖，
    测试用 ``db_path`` 注入 tmp_path 隔离）。初始化时从 SQLite 加载历史到内存。
    无 SQLite 可用 / 写入失败时自动降级为纯内存态，不崩溃。
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.environ.get("BAIZE_JOURNAL_PATH", "data/journal.db")
        self._path = db_path
        self._entries: list[dict] = []
        self._attribution = AlphaAttribution()
        self._conn: Optional[sqlite3.Connection] = None
        self._persist = False
        self._init_db()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _init_db(self):
        """建立 SQLite 连接并建表；失败降级为纯内存态。"""
        conn = None
        try:
            if self._path != ":memory:":
                os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            conn = sqlite3.connect(self._path)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    system_action TEXT NOT NULL,
                    user_action TEXT NOT NULL,
                    user_reason TEXT DEFAULT '',
                    market_sentiment TEXT DEFAULT 'NORMAL',
                    outcome_1w REAL,
                    outcome_1m REAL,
                    lessons TEXT DEFAULT '[]',
                    mistake_type TEXT DEFAULT '',
                    total_return_pct REAL DEFAULT 0.0,
                    alpha_report TEXT
                )
                """
            )
            conn.commit()
        except Exception as e:  # noqa: BLE001 — 降级路径，不向外抛
            logger.warning("DecisionJournal SQLite 不可用，降级为纯内存态: %s", e)
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            self._conn = None
            self._persist = False
            return
        self._conn = conn
        self._persist = True
        self._load()

    def _load(self):
        """从 SQLite 加载历史到 _entries。单条损坏记录跳过，不影响其余。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY id ASC"
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("决策日志加载失败，保持空内存态: %s", e)
            self._entries = []
            return
        loaded = 0
        for row in rows:
            try:
                self._entries.append(self._row_to_entry(row))
                loaded += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("跳过损坏的决策记录 id=%s: %s", row["id"], e)
        if loaded and loaded != len(rows):
            logger.warning("决策日志部分加载 %d/%d", loaded, len(rows))

    def _save_entry(self, entry: dict):
        """写入一行到 SQLite；失败降级为内存态（该条仍在 _entries）。"""
        try:
            self._conn.execute(
                "INSERT INTO decisions (timestamp, symbol, system_action, user_action, "
                "user_reason, market_sentiment, outcome_1w, outcome_1m, lessons, "
                "mistake_type, total_return_pct, alpha_report) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry["timestamp"],
                    entry["symbol"],
                    entry["system_action"],
                    entry["user_action"],
                    entry.get("user_reason", ""),
                    entry.get("market_sentiment", "NORMAL"),
                    entry.get("outcome_1w"),
                    entry.get("outcome_1m"),
                    json.dumps(entry.get("lessons", []), ensure_ascii=False),
                    entry.get("mistake_type", ""),
                    entry.get("total_return_pct", 0.0),
                    self._serialize_alpha(entry.get("alpha_report")),
                ),
            )
            self._conn.commit()
        except Exception as e:  # noqa: BLE001 — 降级路径，不向外抛
            logger.warning("决策日志写入失败，降级为内存态: %s", e)
            self._persist = False

    def _row_to_entry(self, row: sqlite3.Row) -> dict:
        return {
            "timestamp": row["timestamp"],
            "symbol": row["symbol"],
            "system_action": row["system_action"],
            "user_action": row["user_action"],
            "user_reason": row["user_reason"] or "",
            "market_sentiment": row["market_sentiment"] or "NORMAL",
            "outcome_1w": row["outcome_1w"],
            "outcome_1m": row["outcome_1m"],
            "lessons": json.loads(row["lessons"] or "[]"),
            "mistake_type": row["mistake_type"] or "",
            "total_return_pct": row["total_return_pct"] or 0.0,
            "alpha_report": self._deserialize_alpha(row["alpha_report"]),
        }

    @staticmethod
    def _serialize_alpha(report) -> Optional[str]:
        """AttributionReport → JSON 字符串（None → None）。"""
        if report is None:
            return None
        try:
            if dataclasses.is_dataclass(report):
                data = dataclasses.asdict(report)
                # datetime 字段转 ISO 字符串，保证 fromisoformat 往返一致
                for key in ("period_start", "period_end"):
                    value = data.get(key)
                    if isinstance(value, datetime):
                        data[key] = value.isoformat()
            elif isinstance(report, dict):
                data = report
            else:
                return None
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    def _deserialize_alpha(cls, text: Optional[str]) -> Optional[AttributionReport]:
        """JSON 字符串 → AttributionReport（失败返回 None）。"""
        if not text:
            return None
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or "symbol" not in data:
                return None
            for key in ("period_start", "period_end"):
                value = data.get(key)
                if isinstance(value, str):
                    try:
                        data[key] = datetime.fromisoformat(value)
                    except ValueError:
                        pass
            return AttributionReport(**data)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def log(
        self,
        symbol: str,
        system_action: str,
        user_action: str,
        user_reason: str = "",
        market_sentiment: str = "NORMAL",
        entry_alpha: Optional[AlphaProfile] = None,
        exit_alpha: Optional[AlphaProfile] = None,
        total_return_pct: float = 0.0,
        market_return_pct: float = 0.0,
        sector_return_pct: float = 0.0,
        holding_days: int = 0,
        outcome_1w: Optional[float] = None,
        outcome_1m: Optional[float] = None,
        lessons: Optional[list[str]] = None,
        mistake_type: str = "",
    ):
        """记录一条决策（含 Alpha 归因），并持久化到 SQLite。"""
        # Alpha 归因
        attribution_report = None
        if entry_alpha and abs(total_return_pct) > 0.01:
            try:
                attribution_report = self._attribution.attribute(
                    symbol=symbol,
                    total_return_pct=total_return_pct,
                    market_return_pct=market_return_pct,
                    sector_return_pct=sector_return_pct,
                    entry_profile=entry_alpha,
                    exit_profile=exit_alpha,
                    holding_period_days=holding_days,
                )
            except Exception:
                pass

        entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "system_action": system_action,
            "user_action": user_action,
            "user_reason": user_reason,
            "market_sentiment": market_sentiment,
            "outcome_1w": outcome_1w,
            "outcome_1m": outcome_1m,
            "lessons": lessons or [],
            "mistake_type": mistake_type or "",
            "total_return_pct": total_return_pct,
            "alpha_report": attribution_report,
        }
        self._entries.append(entry)
        if self._persist:
            try:
                self._save_entry(entry)
            except Exception as e:  # noqa: BLE001 — 写入失败降级，不崩溃
                logger.warning("决策日志写入失败，降级为内存态: %s", e)
                self._persist = False

    @property
    def entries(self) -> list[dict]:
        """最近记录（新 → 旧），便于外部访问。"""
        return list(reversed(self._entries))

    def weekly_review(self) -> str:
        """生成周度复盘报告（含 Alpha 归因）。"""
        if not self._entries:
            return "本周无交易记录。"
        recent = [e for e in self._entries
                  if (datetime.now() - datetime.fromisoformat(e["timestamp"])).days <= 7]
        if not recent:
            return "本周无交易记录。"
        agreed = sum(1 for e in recent if e["system_action"] == e["user_action"])
        total = len(recent)
        agreement_rate = agreed / total if total > 0 else 0
        lines = [
            "# 周度复盘报告",
            f"期间: 最近 7 天",
            f"交易数: {total}",
            f"系统-用户一致率: {agreement_rate:.0%}",
            "",
            "## 本周操作",
        ]
        for e in recent:
            icon = "✅" if e["system_action"] == e["user_action"] else "⚠️"
            lines.append(
                f"{icon} {e['symbol']}: 系统建议 {e['system_action']}, "
                f"你做了 {e['user_action']} ({e['user_reason']})"
            )
            # Phase 4: Alpha 归因
            ar = e.get("alpha_report")
            if ar:
                driver = "Alpha 驱动" if ar.is_alpha_driven else "Beta 驱动"
                lines.append(
                    f"   📊 收益 {ar.total_return_pct:+.1f}%: "
                    f"Alpha {ar.alpha_return_pct:+.1f}% / "
                    f"Beta {ar.market_beta_return_pct:+.1f}% [{driver}] "
                    f"质量 {ar.alpha_quality_score:.0f}/100"
                )
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._entries)


__all__ = [
    "DecisionJournal",
    "InvestorPreference",
    "RiskProfile",
    "InvestmentGoal",
    "TradingStyle",
    "InvestorTier",
    "PositionLimits",
    "CircleOfCompetence",
    "ScoreWeights",
    "InvestorPreferenceLoader",
    "resolve_weights",
    "resolve_rule_filter",
    "resolve_position_limits",
    "resolve_macro_cap_multiplier",
    "resolve_competence_penalty",
    "ProfileTracker",
    "UserProfile",
    "FeedbackCollector",
    "FeedbackSummary",
    "Feedback",
    "FeedbackType",
    "MistakeType",
    "mistake_type_from_text",
    "validate_lesson_specificity",
    "RuleCalibrator",
    "FactorCalibrator",
    "RiskParamCalibrator",
    "Calibrator",
    "CalibrationRecord",
    "CalibrationResult",
    "CalibrationReport",
    "EvolutionPipeline",
    "EvolutionRecord",
    "EvolutionStatus",
    "GapAnalysis",
    "ProposedChange",
    "SignalTracker",
    "SignalQualityReport",
    "Signal",
    "SignalStatus",
    "ReportGenerator",
    "LearningReport",
    # Phase 4: Alpha 归因
    "AlphaAttribution",
    "AttributionReport",
]
