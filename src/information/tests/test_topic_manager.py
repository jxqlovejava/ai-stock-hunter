"""测试主题管理器和生命周期状态机。"""

import tempfile
from pathlib import Path

from src.information.schema import (
    ConsensusMetrics,
    LifecycleStage,
)
from src.information.topic_manager import TopicManager, _sanitize_id


def test_sanitize_id() -> None:
    """测试 ID 生成。"""
    assert _sanitize_id("国产AI算力扩容") == "国产ai算力扩容"
    assert _sanitize_id("Hello World") == "hello-world"
    assert _sanitize_id("Test!!!@@@") == "test"
    assert _sanitize_id("  spaces  ") == "spaces"


def test_create_and_get() -> None:
    """测试创建和获取主题。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(
            name="测试主题",
            keywords=["AI", "算力"],
            related_stocks=["688256"],
        )
        assert topic.id == "测试主题"
        assert topic.lifecycle_stage == LifecycleStage.EMERGING

        restored = mgr.get(topic.id)
        assert restored is not None
        assert restored.name == topic.name
        assert restored.keywords == topic.keywords


def test_list_topics() -> None:
    """测试列出主题。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        mgr.create(name="主题A", keywords=["AI"])
        mgr.create(name="主题B", keywords=["芯片"])

        all_topics = mgr.list_all()
        assert len(all_topics) == 2

        active = mgr.list_active()
        assert len(active) == 2


def test_update_and_version() -> None:
    """测试更新和版本递增。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="测试主题")
        assert topic.version == 1

        updated = mgr.update(topic.id, description="新描述")
        assert updated.version == 2
        assert updated.description == "新描述"


def test_lifecycle_state_machine() -> None:
    """测试生命周期状态转换。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="生命周期测试")

        # 初始状态
        assert topic.lifecycle_stage == LifecycleStage.EMERGING

        # 手动转换
        updated = mgr.update_lifecycle(topic.id, LifecycleStage.SPREADING)
        assert updated.lifecycle_stage == LifecycleStage.SPREADING


def test_auto_transition_emerging_to_spreading() -> None:
    """测试自动转换：EMERGING → SPREADING。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="自动转换测试")

        # 模拟扩散条件：讨论量上升 + 多源覆盖
        metrics = ConsensusMetrics(
            topic_id=topic.id,
            volume_trend="rising",
            source_count=3,
        )
        stage, changed = mgr.auto_transition(topic.id, metrics)
        assert stage == LifecycleStage.SPREADING
        assert changed is True


def test_auto_transition_to_fading() -> None:
    """测试自动转换 → FADING。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="消退测试")

        # 先推进到 SPREADING
        mgr.update_lifecycle(topic.id, LifecycleStage.SPREADING)

        # 模拟消退条件
        metrics = ConsensusMetrics(
            topic_id=topic.id,
            volume_score=0.1,
            volume_trend="falling",
        )
        stage, changed = mgr.auto_transition(topic.id, metrics)
        assert stage == LifecycleStage.FADING
        assert changed is True


def test_deactivate() -> None:
    """测试停用主题。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="停用测试")
        assert topic.is_active is True

        mgr.deactivate(topic.id)
        restored = mgr.get(topic.id)
        assert restored is not None
        assert restored.is_active is False

        # 不在活跃列表中
        active = mgr.list_active()
        assert len(active) == 0


def test_delete() -> None:
    """测试删除。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="删除测试")

        ok = mgr.delete(topic.id)
        assert ok is True
        assert mgr.get(topic.id) is None


def test_estimate_transition_probability() -> None:
    """测试转换概率估算。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = TopicManager(Path(tmpdir))
        topic = mgr.create(name="概率测试")

        # 高转换概率条件
        metrics = ConsensusMetrics(
            topic_id=topic.id,
            volume_trend="rising",
            source_count=4,
            sentiment_dispersion=0.2,  # 一致性强
            consensus_level=0.8,
        )
        prob = mgr.estimate_transition_probability(topic.id, metrics)
        assert prob > 0.5  # 高概率向下一阶段转换
