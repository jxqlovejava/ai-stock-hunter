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

    # ── Phase 3: 生命周期 → 权重调整 ──────────────────────────────────────

    # 生命周期阶段 → 裁决行业权重调整值
    LIFECYCLE_WEIGHT_ADJ: dict[LifecycleStage, float] = {
        LifecycleStage.EMERGING: +0.10,
        LifecycleStage.SPREADING: 0.0,
        LifecycleStage.CONSENSUS: -0.10,
        LifecycleStage.CROWDED: -0.20,
        LifecycleStage.FADING: -1.0,
    }

    def get_lifecycle_adjustments(self) -> dict[str, float]:
        """获取所有活跃主题的生命周期权重调整。

        Returns:
            {topic_id: weight_bonus} dict
            bonus ∈ [-1.0, +0.1]
            -1.0 = FADING (应完全中性化)
            -0.2 = CROWDED
            -0.1 = CONSENSUS
            0.0 = SPREADING
            +0.1 = EMERGING
        """
        active_topics = self.list_active()
        adjustments: dict[str, float] = {}
        for topic in active_topics:
            bonus = self.LIFECYCLE_WEIGHT_ADJ.get(topic.lifecycle_stage, 0.0)
            adjustments[topic.id] = bonus
        return adjustments

    def get_topic_summary_for_routing(self) -> dict:
        """获取主题概要，供路由层使用。

        Returns:
            dict with:
                adjustments: {topic_id: bonus}
                crowded: list of crowded topic names
                fading: list of fading topic names
                emerging: list of emerging topic names
        """
        active = self.list_active()
        result: dict = {
            "adjustments": {},
            "crowded": [],
            "fading": [],
            "emerging": [],
        }
        for t in active:
            bonus = self.LIFECYCLE_WEIGHT_ADJ.get(t.lifecycle_stage, 0.0)
            result["adjustments"][t.id] = bonus
            if t.lifecycle_stage == LifecycleStage.EMERGING:
                result["emerging"].append(t.name)
            elif t.lifecycle_stage == LifecycleStage.CROWDED:
                result["crowded"].append(t.name)
            elif t.lifecycle_stage == LifecycleStage.FADING:
                result["fading"].append(t.name)
        return result

    # ── Phase 3: 同花顺热点 reason tags → 自动主题发现 ───────────────────

    def discover_hot_topics(self, date: str = "") -> list[Topic]:
        """从同花顺热点 reason tags 自动发现新兴主题。

        流程:
          1. 拉取当日同花顺强势股 reason tags
          2. 词频统计 reason 中的题材关键词
          3. 对高频新词自动创建 EMERGING 主题
          4. 对已有主题更新热度

        Args:
            date: YYYY-MM-DD 格式，空=今天

        Returns:
            新创建或更新的主题列表
        """
        try:
            import requests
            from collections import Counter

            if not date:
                from datetime import date as _date
                date = _date.today().strftime("%Y-%m-%d")

            # Fetch hot stock reason tags
            url = (
                f"http://zx.10jqka.com.cn/event/api/getharden/"
                f"date/{date}/orderby/date/orderway/desc/charset/GBK/"
            )
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
            }
            r = requests.get(url, headers=headers, timeout=10,
                             proxies={"http": None, "https": None})
            data = r.json()
            if data.get("errocode", 0) != 0:
                return []

            rows = data.get("data") or []
            if not rows:
                return []

            # Extract and count reason tags
            all_tags: list[str] = []
            for row in rows:
                reason = row.get("reason", "")
                if reason:
                    tags = [t.strip() for t in str(reason).split("+") if t.strip()]
                    all_tags.extend(tags)

            if not all_tags:
                return []

            counter = Counter(all_tags)
            hot_threshold = max(3, len(rows) // 30)  # Appears in ≥3 stocks or top 3%

            # Get existing topic keywords for dedup
            existing = {t.id for t in self.list_all()}
            existing_names = {t.name for t in self.list_all()}

            created_or_updated: list[Topic] = []
            for tag, count in counter.most_common(30):
                if count < hot_threshold:
                    continue

                tag_id = _sanitize_id(tag)

                # Update existing topic
                if tag_id in existing or tag in existing_names:
                    topic = self.get(tag_id) or self.get(_sanitize_id(tag))
                    if topic is not None:
                        # Boost: if high frequency, move EMERGING→SPREADING
                        if topic.lifecycle_stage == LifecycleStage.EMERGING and count >= hot_threshold * 2:
                            self.update_lifecycle(topic.id, LifecycleStage.SPREADING,
                                                  f"同花顺热点频率{count}次")
                        created_or_updated.append(topic)
                    continue

                # Create new EMERGING topic
                try:
                    topic = self.create(
                        name=tag,
                        topic_id=tag_id,
                        description=f"同花顺热点自动发现 ({date}, {count}只强势股)",
                        keywords=[tag],
                        tags=["auto-discovered", "tonghuashun"],
                    )
                    created_or_updated.append(topic)
                except FileExistsError:
                    pass

            return created_or_updated
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug("Hot topic discovery failed: %s", e)
            return []

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
