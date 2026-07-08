# -*- coding: utf-8 -*-
"""庄家操盘历史数据库。

ManipulationHistoryStore 负责操纵检测结果的持久化与查询：
  - JSON 文件 per stock: data/manipulation_history/{symbol}.json
  - 线程安全读写 (threading.Lock)
  - 使用 uuid.uuid4() 生成 record_id

参考 ArenaSessionStore (src/arena/session.py) 的存储模式。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Dataclasses ──


@dataclass
class ManipulationRecord:
    """单次操纵检测记录。"""

    record_id: str = ""
    symbol: str = ""
    name: str = ""
    date: str = ""
    manipulation_type: str = ""        # playbook_id 或 daily pattern 名
    source: str = "intraday"           # "intraday" / "daily" / "manual"
    confidence: float = 0.0            # 0.0-1.0
    risk_score: float = 0.0            # 0-100
    price_at_detection: float = 0.0
    outcome: str = "pending"           # "pending" / "confirmed" / "false_positive" / "missed"
    price_after_1d: Optional[float] = None
    price_after_3d: Optional[float] = None
    price_after_5d: Optional[float] = None
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ManipulationRecord:
        created_at = data.get("created_at", "")
        if isinstance(created_at, str) and created_at:
            try:
                data["created_at"] = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                data["created_at"] = datetime.now()
        else:
            data["created_at"] = datetime.now()
        return cls(**data)


@dataclass
class StockManipulationProfile:
    """某只股票的整体操纵画像。"""

    symbol: str = ""
    name: str = ""
    total_incidents: int = 0
    first_incident_date: str = ""
    last_incident_date: str = ""
    avg_risk_score: float = 0.0
    repeat_offender: bool = False      # >= 3 incidents
    manipulation_types: dict[str, int] = field(default_factory=dict)
    most_common_type: str = ""
    risk_rating: str = "low"           # "low" / "medium" / "high" / "extreme"
    last_updated: datetime = field(default_factory=datetime.now)


# ── Store ──


class ManipulationHistoryStore:
    """操纵检测历史持久化存储。

    每支股票独立 JSON 文件：
        data/manipulation_history/{symbol}.json

    线程安全：写操作通过 threading.Lock 保护。
    """

    DEFAULT_DIR = Path("data/manipulation_history")

    def __init__(self, storage_dir: Optional[Path] = None):
        self._dir = Path(storage_dir) if storage_dir else self.DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 内部 IO
    # ------------------------------------------------------------------

    def _filepath(self, symbol: str) -> Path:
        """返回 symbol 对应的 JSON 文件路径。"""
        return self._dir / f"{symbol}.json"

    def _load_records(self, symbol: str) -> list[dict]:
        """从 JSON 加载某股票的记录列表。

        文件不存在或损坏时返回空列表。
        """
        filepath = self._filepath(symbol)
        if not filepath.exists():
            return []
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            logger.warning("Unexpected JSON structure in %s (expected list)", filepath)
            return []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load manipulation records for %s: %s", symbol, e)
            return []

    def _save_records(self, symbol: str, records: list[dict]) -> None:
        """将记录列表写入 symbol 的 JSON 文件。"""
        filepath = self._filepath(symbol)
        try:
            filepath.write_text(
                json.dumps(records, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except (TypeError, OSError) as e:
            logger.warning("Failed to save manipulation records for %s: %s", symbol, e)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save_record(self, record: ManipulationRecord) -> str:
        """新增一条操纵检测记录到对应股票的 JSON 文件。

        Args:
            record: 待保存的记录（record_id 为空则自动生成）

        Returns:
            record_id
        """
        if not record.record_id:
            record.record_id = uuid.uuid4().hex
        if not record.symbol:
            logger.warning("save_record called with empty symbol")
            return record.record_id

        with self._lock:
            records = self._load_records(record.symbol)
            records.append(record.to_dict())
            self._save_records(record.symbol, records)

        logger.info(
            "Manipulation record saved: %s | %s | %s | score=%.1f",
            record.record_id, record.symbol, record.manipulation_type, record.risk_score,
        )
        return record.record_id

    def get_stock_profile(self, symbol: str) -> StockManipulationProfile:
        """分析某股票的全部历史记录，计算操纵画像。

        画像包含：总次数、首次/末次日期、平均风险分、
        是否为惯犯 (>=3 次)、操纵类型分布、风险评级。
        """
        records = self._load_records(symbol)
        if not records:
            return StockManipulationProfile(symbol=symbol)

        # 解析为 ManipulationRecord 以便访问字段
        parsed = []
        for d in records:
            try:
                parsed.append(ManipulationRecord.from_dict(d))
            except (TypeError, KeyError):
                continue

        if not parsed:
            return StockManipulationProfile(symbol=symbol)

        # 基础统计
        total = len(parsed)
        dates = [r.date for r in parsed if r.date]
        risk_scores = [r.risk_score for r in parsed]

        first_date = min(dates) if dates else ""
        last_date = max(dates) if dates else ""
        avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

        # 操纵类型分布
        type_counter: Counter = Counter()
        name = parsed[0].name if parsed else symbol
        for r in parsed:
            if r.manipulation_type:
                type_counter[r.manipulation_type] += 1

        most_common = type_counter.most_common(1)
        most_common_type = most_common[0][0] if most_common else ""

        # 风险评级
        risk_rating = self._compute_risk_rating(total, avg_risk)

        return StockManipulationProfile(
            symbol=symbol,
            name=name,
            total_incidents=total,
            first_incident_date=first_date,
            last_incident_date=last_date,
            avg_risk_score=round(avg_risk, 1),
            repeat_offender=total >= 3,
            manipulation_types=dict(type_counter),
            most_common_type=most_common_type,
            risk_rating=risk_rating,
            last_updated=datetime.now(),
        )

    def get_repeat_offenders(self, min_incidents: int = 3) -> list[StockManipulationProfile]:
        """扫描全部 JSON 文件，返回达到最低操纵次数的惯犯名单。

        Args:
            min_incidents: 最低操纵次数阈值（默认 3）

        Returns:
            StockManipulationProfile 列表，按 incidents 降序排列
        """
        offenders: list[StockManipulationProfile] = []
        for filepath in sorted(self._dir.glob("*.json")):
            symbol = filepath.stem
            profile = self.get_stock_profile(symbol)
            if profile.total_incidents >= min_incidents:
                offenders.append(profile)

        offenders.sort(key=lambda p: p.total_incidents, reverse=True)
        return offenders

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def query(
        self,
        symbol: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        manipulation_type: Optional[str] = None,
    ) -> list[ManipulationRecord]:
        """按条件筛选操纵检测记录。

        Args:
            symbol: 股票代码（None = 全部股票）
            date_from: 起始日期 "YYYY-MM-DD"（含）
            date_to: 截止日期 "YYYY-MM-DD"（含）
            manipulation_type: 操纵类型过滤

        Returns:
            符合条件的 ManipulationRecord 列表，按 created_at 降序
        """
        results: list[ManipulationRecord] = []

        if symbol:
            candidates = [(symbol, self._load_records(symbol))]
        else:
            candidates = [
                (fp.stem, json.loads(fp.read_text(encoding="utf-8")))
                for fp in sorted(self._dir.glob("*.json"))
                if fp.stat().st_size > 0
            ]

        for sym, raw_list in candidates:
            for d in raw_list:
                try:
                    rec = ManipulationRecord.from_dict(d)
                except (TypeError, KeyError):
                    continue

                if manipulation_type and rec.manipulation_type != manipulation_type:
                    continue
                if date_from and rec.date < date_from:
                    continue
                if date_to and rec.date > date_to:
                    continue

                results.append(rec)

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def update_outcome(
        self,
        record_id: str,
        symbol: str,
        outcome: str,
        price_after_1d: Optional[float] = None,
        price_after_3d: Optional[float] = None,
        price_after_5d: Optional[float] = None,
    ) -> bool:
        """更新指定记录的结果和后续价格。

        Args:
            record_id: 待更新的 record_id
            symbol: 股票代码
            outcome: 新结果
            price_after_1d: 1 日后价格
            price_after_3d: 3 日后价格
            price_after_5d: 5 日后价格

        Returns:
            是否成功找到并更新
        """
        if not symbol:
            return False

        with self._lock:
            records = self._load_records(symbol)
            found = False
            for d in records:
                if d.get("record_id") == record_id:
                    d["outcome"] = outcome
                    if price_after_1d is not None:
                        d["price_after_1d"] = price_after_1d
                    if price_after_3d is not None:
                        d["price_after_3d"] = price_after_3d
                    if price_after_5d is not None:
                        d["price_after_5d"] = price_after_5d
                    found = True
                    break
            if found:
                self._save_records(symbol, records)
                logger.info("Manipulation record %s for %s updated: %s", record_id, symbol, outcome)
            else:
                logger.warning("Record %s not found for symbol %s", record_id, symbol)
            return found

    def get_recent_incidents(
        self,
        symbol: Optional[str] = None,
        days: int = 30,
    ) -> list[ManipulationRecord]:
        """获取最近 N 天的操纵检测记录。

        Args:
            symbol: 股票代码（None = 全部）
            days: 回溯天数（默认 30）

        Returns:
            符合条件的 ManipulationRecord 列表，按 created_at 降序
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        sym: Optional[str] = null_to_none(symbol) if isinstance(symbol, str) and not symbol else symbol
        results = self.query(symbol=sym, date_from=cutoff_str)
        return results

    def rebuild_all_profiles(self) -> list[StockManipulationProfile]:
        """扫描整个存储目录，重建所有股票的操纵画像。

        返回所有已分析的 StockManipulationProfile 列表。
        """
        profiles: list[StockManipulationProfile] = []
        for filepath in sorted(self._dir.glob("*.json")):
            symbol = filepath.stem
            try:
                profile = self.get_stock_profile(symbol)
                profiles.append(profile)
            except Exception as e:
                logger.warning("Failed to rebuild profile for %s: %s", symbol, e)
        return profiles

    def is_repeat_offender(self, symbol: str) -> bool:
        """快速检查某股票是否属于操纵惯犯（>= 3 次记录）。"""
        profile = self.get_stock_profile(symbol)
        return profile.repeat_offender

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk_rating(incidents: int, avg_risk: float) -> str:
        """根据操纵次数计算风险评级。

        评级规则：0-1 次→low, 2 次→medium, 3-5 次→high, >=6 次→extreme
        avg_risk 保留作为扩展信号传入但不改变评级（供后续加权使用）。
        """
        if incidents >= 6:
            return "extreme"
        if incidents >= 3:
            return "high"
        if incidents >= 2:
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # 输入验证
    # ------------------------------------------------------------------

    @staticmethod
    def validate_record(record: ManipulationRecord) -> list[str]:
        """校验记录字段合法性，返回错误消息列表（空=合法）。"""
        errors: list[str] = []
        if not record.symbol:
            errors.append("symbol is required")
        if record.manipulation_type and len(record.manipulation_type) > 64:
            errors.append("manipulation_type too long (max 64)")
        if not (0.0 <= record.confidence <= 1.0):
            errors.append("confidence must be in [0.0, 1.0]")
        if not (0.0 <= record.risk_score <= 100.0):
            errors.append("risk_score must be in [0, 100]")
        if record.outcome not in ("pending", "confirmed", "false_positive", "missed"):
            errors.append(f"invalid outcome: {record.outcome}")
        if record.source not in ("intraday", "daily", "manual"):
            errors.append(f"invalid source: {record.source}")
        return errors


# ── 辅助函数 ──


def log_manipulation_event(
    store: ManipulationHistoryStore,
    symbol: str,
    name: str,
    manipulation_type: str,
    source: str,
    confidence: float,
    risk_score: float,
    price: float,
) -> str:
    """便捷函数：一行代码记录操纵检测事件。

    Args:
        store: ManipulationHistoryStore 实例
        symbol: 股票代码
        name: 股票名称
        manipulation_type: 操纵类型 ID
        source: 数据来源
        confidence: 置信度 0.0-1.0
        risk_score: 风险评分 0-100
        price: 检测时的价格

    Returns:
        新记录的 record_id
    """
    record = ManipulationRecord(
        symbol=symbol,
        name=name,
        date=datetime.now().strftime("%Y-%m-%d"),
        manipulation_type=manipulation_type,
        source=source,
        confidence=confidence,
        risk_score=risk_score,
        price_at_detection=price,
        outcome="pending",
    )
    return store.save_record(record)


def get_manipulation_risk_rating(
    store: ManipulationHistoryStore,
    symbol: str,
) -> str:
    """快速查询某股票的操纵风险评级（不依赖 profile 对象）。"""
    profile = store.get_stock_profile(symbol)
    return profile.risk_rating


def null_to_none(val: Optional[str]) -> Optional[str]:
    """将空字符串转换为 None，用于无值传递。"""
    return val if val else None
