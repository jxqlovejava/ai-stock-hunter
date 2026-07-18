"""分歧/一致检测器 单元测试。

使用合成数据测试 DivergenceConsensusAnalyzer 的四种状态检测。
"""

import numpy as np
import pytest

from src.analysis.divergence_consensus import (
    DivergenceConsensusAnalyzer,
    DivergenceConsensusPhase,
    DivergenceConsensusResult,
    analyze_divergence_consensus,
)


# ---- 合成数据生成器 ----

def _synth_divergence(n: int = 40) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """放量横盘：价格窄幅震荡，成交量持续高于均量 1.5x。"""
    rng = np.random.default_rng(42)
    price = 10.0
    close = []
    high = []
    low = []
    volume = []
    # 前半段正常波动建立 baseline
    for i in range(n - 8):
        chg = rng.normal(0, 0.05)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.02)))
        low.append(price - abs(rng.normal(0, 0.02)))
        volume.append(rng.uniform(8000, 12000))
    # 最后 8 根：横盘 + 放量
    avg_vol = np.mean(volume)
    for i in range(8):
        chg = rng.normal(0, 0.01)  # 几乎不动
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.02)))
        low.append(price - abs(rng.normal(0, 0.02)))
        volume.append(avg_vol * 1.6)  # 1.6x 均量
    return (np.array(close), np.array(volume), np.array(high), np.array(low))


def _synth_consensus(n: int = 40) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """缩量连涨：最近 5 根连续收涨 + 量缩。"""
    rng = np.random.default_rng(99)
    close = []
    high = []
    low = []
    volume = []
    price = 10.0
    base_vol = 10000.0
    for i in range(n - 5):
        chg = rng.normal(0, 0.03)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.01)))
        low.append(price - abs(rng.normal(0, 0.01)))
        volume.append(base_vol + rng.normal(0, 500))
    # 最后 5 根：连续上涨 + 量缩
    vols = [8000, 6000, 4500, 3500, 2500]
    for i in range(5):
        price = price + 0.15  # 每根涨 1.5%
        close.append(price)
        high.append(price + 0.02)
        low.append(price - 0.01)
        volume.append(vols[i])
    return (np.array(close), np.array(volume), np.array(high), np.array(low))


def _synth_consensus_breaking(n: int = 45) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """一致转分歧：缩量上涨后一根放量冲高回落。"""
    rng = np.random.default_rng(123)
    close = []
    high = []
    low = []
    volume = []
    price = 10.0
    base_vol = 10000.0
    # 前半段正常波动建立 baseline volume
    for i in range(n - 8):
        chg = rng.normal(0, 0.03)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.02)))
        low.append(price - abs(rng.normal(0, 0.02)))
        volume.append(base_vol + rng.normal(0, 500))
    # 4 根确定性缩量上涨（一致）— 确保价格严格递增、量严格递减
    prev_price = close[-1]
    for i in range(4):
        price = prev_price + 0.25 + i * 0.05  # 确保 > 前一根
        close.append(price)
        high.append(price + 0.05)
        low.append(price - 0.04)
        volume.append(6000.0 - i * 1200)  # 6000, 4800, 3600, 2400
        prev_price = price
    # 1 根放量冲高回落（一致转分歧）: volume = 3x avg, 收跌
    reversal_c = prev_price - 0.2  # 收跌！
    reversal_h = prev_price + 0.6   # 冲高
    reversal_l = prev_price - 0.3   # 回落
    close.append(reversal_c)
    high.append(reversal_h)
    low.append(reversal_l)
    volume.append(base_vol * 3.0)  # 3x 均量
    # 加 3 根过渡数据
    for i in range(3):
        reversal_c = reversal_c - 0.05
        close.append(reversal_c)
        high.append(reversal_c + 0.03)
        low.append(reversal_c - 0.06)
        volume.append(base_vol + rng.normal(0, 200))
    return (np.array(close), np.array(volume), np.array(high), np.array(low))


def _synth_forming_consensus(n: int = 45) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """分歧转一致：横盘分歧后放量突破 + 缩量续涨。"""
    rng = np.random.default_rng(555)
    close = []
    high = []
    low = []
    volume = []
    price = 10.0
    base_vol = 10000.0
    # 前半段正常
    for i in range(n - 10):
        chg = rng.normal(0, 0.03)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.01)))
        low.append(price - abs(rng.normal(0, 0.01)))
        volume.append(base_vol + rng.normal(0, 500))
    # 5 根分歧横盘 + 放量
    for i in range(5):
        chg = rng.normal(0, 0.005)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.03)))
        low.append(price - abs(rng.normal(0, 0.03)))
        volume.append(base_vol * 1.5)  # 放量横盘
    # 1 根放量突破: volume > 1.5x avg, close near high
    break_price = price + 0.5
    close.append(break_price)
    high.append(break_price + 0.05)
    low.append(price - 0.02)
    volume.append(base_vol * 2.0)  # 2x 放量突破
    # 2 根缩量续涨
    for i in range(2):
        break_price = break_price + 0.15
        close.append(break_price)
        high.append(break_price + 0.03)
        low.append(break_price - 0.02)
        volume.append(base_vol * 0.8)  # 缩量 < 突破量
    # 再加一根
    close.append(break_price + 0.1)
    high.append(break_price + 0.15)
    low.append(break_price - 0.01)
    volume.append(base_vol * 0.7)
    return (np.array(close), np.array(volume), np.array(high), np.array(low))


def _synth_no_pattern(n: int = 40) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """随机游走，无明显模式。"""
    rng = np.random.default_rng(777)
    close = []
    high = []
    low = []
    volume = []
    price = 10.0
    for i in range(n):
        chg = rng.normal(0, 0.08)
        price = max(1.0, price + chg)
        close.append(price)
        high.append(price + abs(rng.normal(0, 0.02)))
        low.append(price - abs(rng.normal(0, 0.02)))
        volume.append(rng.uniform(8000, 12000))
    return (np.array(close), np.array(volume), np.array(high), np.array(low))


# ---- 测试类 ----

class TestDivergenceConsensusAnalyzer:
    """分歧/一致检测器单元测试。"""

    def test_data_insufficient(self):
        """少于 20 根 K 线返回数据不足。"""
        c = np.linspace(10, 11, 10)
        v = np.ones(10) * 10000
        result = analyze_divergence_consensus(c, v)
        assert result.phase == DivergenceConsensusPhase.DATA_INSUFFICIENT
        assert result.score == 50.0

    def test_detect_divergence(self):
        """检测放量横盘分歧状态。"""
        c, v, h, l = _synth_divergence()
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.phase == DivergenceConsensusPhase.DIVERGENCE
        assert result.score == 40.0
        assert result.volume_ratio >= 1.3

    def test_detect_consensus(self):
        """检测缩量连涨一致状态。"""
        c, v, h, l = _synth_consensus()
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.phase == DivergenceConsensusPhase.CONSENSUS
        assert result.score == 75.0
        assert result.consecutive_shrinking >= 3

    def test_detect_consensus_breaking(self):
        """检测一致转分歧。"""
        c, v, h, l = _synth_consensus_breaking()
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.phase == DivergenceConsensusPhase.CONSENSUS_BREAKING
        assert result.score == 30.0
        assert result.volume_ratio >= 2.0

    def test_detect_forming_consensus(self):
        """检测分歧转一致。"""
        c, v, h, _l = _synth_forming_consensus()
        result = analyze_divergence_consensus(c, v, h, _l)
        assert result.phase == DivergenceConsensusPhase.FORMING_CONSENSUS
        assert result.score == 65.0
        # 应该有放量突破信号
        assert any("放量突破" in s for s in result.signals)

    def test_no_pattern_random(self):
        """随机走势返回 DATA_INSUFFICIENT。"""
        c, v, h, l = _synth_no_pattern()
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.phase == DivergenceConsensusPhase.DATA_INSUFFICIENT

    def test_score_bounds(self):
        """所有场景下分数应在 0-100 内。"""
        cases = [
            _synth_divergence(),
            _synth_consensus(),
            _synth_consensus_breaking(),
            _synth_forming_consensus(),
            _synth_no_pattern(),
        ]
        for c, v, h, l in cases:
            result = analyze_divergence_consensus(c, v, h, l)
            assert 0 <= result.score <= 100, f"{result.phase}: score={result.score}"

    def test_to_dict(self):
        """to_dict() 包含所有关键字段。"""
        c, v, h, l = _synth_consensus()
        result = analyze_divergence_consensus(c, v, h, l)
        d = result.to_dict()
        assert "phase" in d
        assert "state" in d
        assert "score" in d
        assert "signals" in d
        assert "volume_ratio" in d
        assert "consecutive_shrinking" in d

    def test_state_property(self):
        """state 属性返回中文标签。"""
        c, v, h, l = _synth_consensus()
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.state == "一致"

    def test_consensus_prioritized_over_divergence(self):
        """一致检测优先级高于分歧。"""
        c, v, h, l = _synth_consensus()
        # 合成数据符合一致，应返回 CONSENSUS 而非 DIVERGENCE
        result = analyze_divergence_consensus(c, v, h, l)
        assert result.phase != DivergenceConsensusPhase.DIVERGENCE

    def test_configurable_thresholds(self):
        """自定义阈值生效。"""
        c, v, h, l = _synth_consensus()
        # 严格阈值：要求连续 10 根缩量（实际只有 5）
        analyzer = DivergenceConsensusAnalyzer(CONSENSUS_MIN_SHRINKING=10)
        result = analyzer.analyze(c, v, h, l)
        assert result.phase != DivergenceConsensusPhase.CONSENSUS

    def test_module_level_function(self):
        """模块级便捷函数正常工作。"""
        c, v, h, l = _synth_divergence()
        result = analyze_divergence_consensus(c, v, h, l)
        assert isinstance(result, DivergenceConsensusResult)
        assert result.phase == DivergenceConsensusPhase.DIVERGENCE
