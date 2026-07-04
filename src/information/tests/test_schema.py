"""测试数据模型序列化/反序列化。"""

from datetime import datetime

from src.information.schema import (
    ConsensusMetrics,
    DivergenceSignal,
    DivergenceType,
    InfoPricingEstimate,
    InformationSignal,
    LifecycleStage,
    SentimentDirection,
    SignalType,
    Topic,
)


def test_topic_creation() -> None:
    """测试主题创建和默认值。"""
    topic = Topic(
        id="test-topic",
        name="测试主题",
        keywords=["AI", "算力"],
        related_stocks=["688256"],
    )
    assert topic.lifecycle_stage == LifecycleStage.EMERGING
    assert topic.is_active is True
    assert topic.version == 1


def test_topic_serialization() -> None:
    """测试 Pydantic 序列化/反序列化。"""
    topic = Topic(
        id="test-topic",
        name="测试主题",
        description="测试描述",
        keywords=["AI", "算力"],
        related_stocks=["688256", "688041"],
        related_sectors=["半导体"],
        core_hypothesis="AI需求驱动算力增长",
        verifiable_conditions=["华为昇腾出货量>100万"],
    )
    data = topic.model_dump(mode="json")
    restored = Topic(**data)
    assert restored.id == topic.id
    assert restored.name == topic.name
    assert restored.keywords == topic.keywords
    assert restored.related_stocks == topic.related_stocks


def test_consensus_metrics() -> None:
    """测试共识度指标计算值范围。"""
    m = ConsensusMetrics(
        topic_id="test",
        volume_score=0.7,
        volume_trend="rising",
        sentiment_mean=0.3,
        sentiment_dispersion=0.4,
        source_alignment="aligned",
        institution_retail_gap=0.2,
        consensus_level=0.6,
        estimated_alpha_remaining=0.4,
    )
    assert 0.0 <= m.consensus_level <= 1.0
    assert 0.0 <= m.estimated_alpha_remaining <= 1.0
    assert -1.0 <= m.sentiment_mean <= 1.0


def test_divergence_signal() -> None:
    """测试分歧信号模型。"""
    signal = DivergenceSignal(
        topic_id="test",
        source_a="weibo",
        source_b="huatai",
        divergence_type=DivergenceType.SENTIMENT,
        divergence_score=0.7,
        description="散户极度看好 vs 机构谨慎",
        tradable=True,
        suggested_action="关注机构研报后续方向",
    )
    assert signal.divergence_score >= 0.5
    assert signal.tradable is True


def test_info_pricing_estimate() -> None:
    """测试信息定价度模型。"""
    est = InfoPricingEstimate(
        topic_id="test",
        symbol="688256",
        event="华为发布昇腾910C",
        estimated_pricing_ratio=0.3,
        key_observation="信息仅被定价约30%",
    )
    assert 0.0 <= est.estimated_pricing_ratio <= 1.0
    assert est.pricing_round >= 1


def test_information_signal() -> None:
    """测试标准化信号输出。"""
    topic = Topic(id="test", name="测试", keywords=["AI"])
    signal = InformationSignal(
        topic_id=topic.id,
        topic_name=topic.name,
        signal_type=SignalType.CONSENSUS_BREACH,
        direction=SentimentDirection.BULLISH,
        strength=0.7,
        confidence=0.65,
        reasoning="共识度低于0.4，信息尚未扩散，存在Alpha机会",
        related_stocks=["688256"],
    )
    assert signal.strength > 0.5
    assert signal.confidence > 0.5
    assert signal.suggested_weight <= 0.5


def test_lifecycle_stage_enum() -> None:
    """测试生命周期枚举。"""
    assert LifecycleStage.EMERGING.value == "emerging"
    assert LifecycleStage.SPREADING.value == "spreading"
    assert LifecycleStage.CONSENSUS.value == "consensus"
    assert LifecycleStage.CROWDED.value == "crowded"
    assert LifecycleStage.FADING.value == "fading"
