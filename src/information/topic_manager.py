"""主题管理器 — Topic CRUD + 生命周期状态机 + YAML 文件存储。

Ref: AI Berkshire thesis-tracker.md — 假设健康度评分模型
每个主题存储为 data/topics/{topic_id}.yaml。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from src.information.schema import (
    LIFECYCLE_THRESHOLDS,
    ConsensusMetrics,
    LifecycleStage,
    Topic,
)

# 主题文件存储目录（相对于项目根目录）
DEFAULT_TOPICS_DIR = Path("data/topics")


def _sanitize_id(name: str) -> str:
    """从主题名称生成 kebab-case ID。"""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "untitled"


class TopicManager:
    """主题 CRUD 管理器。

    使用方式：
        mgr = TopicManager()
        topic = mgr.create(
            name="国产AI算力扩容",
            keywords=["国产GPU","华为昇腾","寒武纪"],
            related_stocks=["688256","688041"],
        )
        topics = mgr.list_active()
        mgr.update_lifecycle("domestic-ai-computing", LifecycleStage.SPREADING)
    """

    def __init__(self, topics_dir: Path | str | None = None) -> None:
        self._dir = Path(topics_dir) if topics_dir else DEFAULT_TOPICS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── CRUD ───────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        *,
        topic_id: str | None = None,
        description: str = "",
        keywords: list[str] | None = None,
        related_stocks: list[str] | None = None,
        related_sectors: list[str] | None = None,
        core_hypothesis: str = "",
        verifiable_conditions: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Topic:
        """创建新主题。"""
        tid = topic_id or _sanitize_id(name)
        path = self._path(tid)
        if path.exists():
            raise FileExistsError(f"主题 '{tid}' 已存在: {path}")

        topic = Topic(
            id=tid,
            name=name,
            description=description,
            keywords=keywords or [],
            related_stocks=related_stocks or [],
            related_sectors=related_sectors or [],
            core_hypothesis=core_hypothesis,
            verifiable_conditions=verifiable_conditions or [],
            tags=tags or [],
        )
        self._save(topic)
        return topic

    def get(self, topic_id: str) -> Topic | None:
        """按 ID 获取主题。"""
        path = self._path(topic_id)
        if not path.exists():
            return None
        return self._load(path)

    def update(self, topic_id: str, **kwargs) -> Topic:
        """更新主题字段。自动递增版本号并更新 updated_at。"""
        topic = self._must_get(topic_id)
        allowed = {
            "name",
            "description",
            "keywords",
            "related_stocks",
            "related_sectors",
            "core_hypothesis",
            "verifiable_conditions",
            "tags",
            "is_active",
            "lifecycle_stage",
        }
        for k, v in kwargs.items():
            if k in allowed and hasattr(topic, k):
                setattr(topic, k, v)
        topic.updated_at = datetime.now()
        topic.version += 1
        self._save(topic)
        return topic

    def delete(self, topic_id: str) -> bool:
        """删除主题。"""
        path = self._path(topic_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_all(self) -> list[Topic]:
        """列出所有主题。"""
        topics = []
        for path in sorted(self._dir.glob("*.yaml")):
            topic = self._load(path)
            if topic:
                topics.append(topic)
        return topics

    def list_active(self) -> list[Topic]:
        """列出活跃（仍在追踪）的主题。"""
        return [t for t in self.list_all() if t.is_active]

    def deactivate(self, topic_id: str) -> Topic:
        """停用主题（不再追踪，但不删除）。"""
        return self.update(topic_id, is_active=False)

    # ── 生命周期状态机 ─────────────────────────────────────────────────────

    def update_lifecycle(
        self, topic_id: str, stage: LifecycleStage, reason: str = ""
    ) -> Topic:
        """手动设置生命周期阶段。"""
        topic = self._must_get(topic_id)
        old_stage = topic.lifecycle_stage
        topic.lifecycle_stage = stage
        topic.updated_at = datetime.now()
        topic.version += 1
        self._save(topic)
        # 记录转换日志（简单 print，Phase 3 升级为结构化日志）
        print(f"[lifecycle] {topic_id}: {old_stage.value} → {stage.value}" + (f" ({reason})" if reason else ""))
        return topic

    def auto_transition(
        self, topic_id: str, metrics: ConsensusMetrics
    ) -> tuple[LifecycleStage, bool]:
        """基于共识指标自动判定是否需要生命周期转换。

        Returns:
            (当前阶段, 是否发生了转换)
        """
        topic = self._must_get(topic_id)
        current = topic.lifecycle_stage
        thresholds = LIFECYCLE_THRESHOLDS

        if current == LifecycleStage.EMERGING:
            t = thresholds["emerging_to_spreading"]
            # 讨论量 30 日增长 > 200% 或 ≥ 2 家媒体跟进
            if (metrics.volume_trend == "rising" and metrics.source_count >= t.get("min_media_sources", 2)):
                self.update_lifecycle(
                    topic_id, LifecycleStage.SPREADING, "讨论量上升 + 多源覆盖"
                )
                return (LifecycleStage.SPREADING, True)

        elif current == LifecycleStage.SPREADING:
            t = thresholds["spreading_to_consensus"]
            # source_count proxied for research report coverage (Phase 3 升级为精确计数)
            has_enough_sources = metrics.source_count >= t.get("min_research_reports", 3)
            sentiment_ok = (
                metrics.sentiment_dispersion is not None
                and (1.0 - metrics.sentiment_dispersion)
                >= t.get("min_sentiment_alignment", 0.6)
            )
            if has_enough_sources and sentiment_ok:
                self.update_lifecycle(
                    topic_id, LifecycleStage.CONSENSUS, "机构覆盖 + 情感趋同"
                )
                return (LifecycleStage.CONSENSUS, True)

        elif current == LifecycleStage.CONSENSUS:
            t = thresholds["consensus_to_crowded"]
            if metrics.volume_score >= 0.9:  # 简化版：讨论量极高
                self.update_lifecycle(
                    topic_id, LifecycleStage.CROWDED, "讨论量达到极端水平"
                )
                return (LifecycleStage.CROWDED, True)

        # 任意阶段 → FADING
        t = thresholds["any_to_fading"]
        if metrics.volume_trend == "falling" and metrics.volume_score < 0.2:
            self.update_lifecycle(topic_id, LifecycleStage.FADING, "持续低迷")
            return (LifecycleStage.FADING, True)

        return (current, False)

    def estimate_transition_probability(
        self, topic_id: str, metrics: ConsensusMetrics
    ) -> float:
        """估算向下一阶段转换的概率（0-1）。

        Ref: AI Berkshire thesis-tracker 健康度评分模型
        """
        topic = self._must_get(topic_id)
        current = topic.lifecycle_stage

        if current == LifecycleStage.FADING:
            return 0.0
        if current == LifecycleStage.CROWDED:
            return 0.3  # 拥挤后大概率消退

        # 基于共识度指标估算转换概率
        score = 0.0
        if metrics.volume_trend == "rising":
            score += 0.3
        elif metrics.volume_trend == "falling":
            score -= 0.2
        if metrics.source_count >= 3:
            score += 0.2
        if metrics.sentiment_dispersion < 0.3:  # 情感一致性高
            score += 0.2
        if metrics.consensus_level > 0.7:
            score += 0.1

        return max(0.0, min(1.0, score))

    # ── 内部方法 ───────────────────────────────────────────────────────────

    def _path(self, topic_id: str) -> Path:
        return self._dir / f"{topic_id}.yaml"

    def _must_get(self, topic_id: str) -> Topic:
        topic = self.get(topic_id)
        if topic is None:
            raise KeyError(f"主题 '{topic_id}' 不存在")
        return topic

    def _save(self, topic: Topic) -> None:
        """序列化为 YAML 写入磁盘。"""
        data = topic.model_dump(mode="json")
        with open(self._path(topic.id), "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    @staticmethod
    def _load(path: Path) -> Topic | None:
        """从 YAML 反序列化。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return Topic(**data)
        except Exception:
            return None
