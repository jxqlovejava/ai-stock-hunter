# -*- coding: utf-8 -*-
"""技术面铁律军规测试（借鉴《17年炒股心得》10 铁律）。

覆盖:
  - pattern_features 纯函数（乖离/换手/低价/跳空三连阳/量减价平/缩量新高）
  - checker r046-r050 触发逻辑
  - t0_decision 早盘急跌反包 (早盘大跌 >5% + 低点在上午 → 勿恐慌割肉)
  - divergence_consensus 缩量创新高加分项
  - risk_monitor 炸板潮 → 空仓检验(r020) 联动
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.analysis.divergence_consensus import DivergenceConsensusAnalyzer
from src.analysis.t0_decision import T0DecisionEngine
from src.data.schema import Bar, Resolution
from src.doctrine.checker import DoctrineChecker
from src.doctrine.pattern_features import (
    bias_vs_ma_pct,
    gap_up_three_yang,
    high_vol_price_flat,
    is_low_price,
    turnover_rate_extreme,
)
from src.doctrine.rules import MILITARY_RULES
from src.monitor.risk_monitor import RiskMonitor

_checker = DoctrineChecker()


def _warns(ctx: dict) -> list[str]:
    return [r.id for r in _checker.check("600519", ctx).warnings]


# ── pattern_features 纯函数 ──

def test_bias_vs_ma_pct_above():
    # 温和上涨 20 日，乖离为正
    closes = [10 + i * 0.2 for i in range(20)]
    bias = bias_vs_ma_pct(closes)
    assert bias is not None and bias > 0
    # 乖离率 ≈ (13.8/11.9 - 1) ≈ 15.97%
    assert 15.0 < bias < 17.0


def test_bias_vs_ma_pct_insufficient():
    assert bias_vs_ma_pct([1, 2, 3]) is None
    assert bias_vs_ma_pct([]) is None


def test_turnover_rate_extreme():
    assert turnover_rate_extreme(41.0) is True
    assert turnover_rate_extreme(40.0) is False
    assert turnover_rate_extreme(30.0) is False
    assert turnover_rate_extreme(None) is False


def test_is_low_price():
    assert is_low_price(5.9) is True
    assert is_low_price(6.0) is False
    assert is_low_price(8.0) is False
    assert is_low_price(None) is False


def test_gap_up_three_yang_positive():
    opens = [10.0, 10.5, 11.2, 12.0, 13.0]
    closes = [10.2, 10.8, 11.5, 12.5, 13.4]
    assert gap_up_three_yang(opens, closes) is True


def test_gap_up_three_yang_negative_on_missing_day():
    # 第 2 根跳空不满足（开盘低于昨收）
    opens = [10.0, 10.5, 10.8, 12.0, 13.0]
    closes = [10.2, 10.8, 11.5, 12.5, 13.4]
    assert gap_up_three_yang(opens, closes) is False


def test_gap_up_three_yang_insufficient():
    assert gap_up_three_yang([1, 2], [1, 2]) is False
    assert gap_up_three_yang(None, None) is False


def test_high_vol_price_flat_positive():
    # 高位 + 量缩 + 价平
    closes = [10.0 + i * 0.05 for i in range(57)] + [12.8, 12.9, 12.85]  # 60根，末尾 3 根价平
    closes = closes[-60:]
    closes[-60] = 10.0
    volumes = [1000] * 57 + [400, 380, 350]  # 近3根显著缩量
    assert high_vol_price_flat(closes, volumes) is True


def test_high_vol_price_flat_volume_not_shrunk():
    closes = [10.0 + i * 0.05 for i in range(57)] + [12.8, 12.9, 12.85]
    volumes = [1000] * 60  # 量未缩
    assert high_vol_price_flat(closes, volumes) is False


# ── checker r046-r050 ──

def test_r046_extreme_turnover():
    assert "r046" in _warns({"turnover_rate_pct": 45.0})
    assert "r046" not in _warns({"turnover_rate_pct": 30.0})
    assert "r046" not in _warns({})


def test_r046_suppressed_on_limit_up_launch_day():
    # 涨停启动日换手放大属正常 → 不触发"主力散户对打"警告
    assert "r046" not in _warns({"turnover_rate_pct": 45.0, "is_limit_up": True})


def test_r047_bias_too_wide():
    assert "r047" in _warns({"bias_vs_ma20_pct": 20.0})
    assert "r047" not in _warns({"bias_vs_ma20_pct": 10.0})
    assert "r047" not in _warns({})


def test_r048_low_price_trap():
    assert "r048" in _warns({"current_price": 5.5})
    assert "r048" not in _warns({"current_price": 8.0})
    assert "r048" not in _warns({})


def test_r049_gap_up_three_yang():
    assert "r049" in _warns({"gap_up_three_yang": True})
    assert "r049" not in _warns({"gap_up_three_yang": False})


def test_r050_high_vol_price_flat():
    assert "r050" in _warns({"high_vol_price_flat": True})
    assert "r050" not in _warns({"high_vol_price_flat": False})


def test_tech_iron_rules_registered():
    ids = {r.id for r in MILITARY_RULES}
    for rid in ("r046", "r047", "r048", "r049", "r050"):
        assert rid in ids


# ── t0_decision 早盘急跌反包 ──

def _bar(ts: datetime, o: float, h: float, l: float, c: float, vol: int = 10000) -> Bar:
    return Bar(symbol="600519", timestamp=ts, resolution=Resolution.MIN_5,
               open=o, high=h, low=l, close=c, volume=vol, amount=o * vol)


def _daily_bars() -> list[Bar]:
    start = datetime(2026, 8, 1, 15, 0)
    bars = []
    for i in range(8):
        ts = start + timedelta(days=i)
        o = 10.0 + i * 0.05
        bars.append(_bar(ts, o, o + 0.1, o - 0.1, o + 0.03))
    return bars


def _minute_bars(entries: list[tuple[str, float, float, float, float]]) -> list[Bar]:
    """构建 10+ 根 5 分钟 Bar（满足 MIN_MINUTE_BARS=10）。entries=(HH:MM, o, h, l, c)。"""
    day = datetime(2026, 8, 9)
    bars = []
    for hhmm, o, h, l, c in entries:
        hh, mm = map(int, hhmm.split(":"))
        ts = day.replace(hour=hh, minute=mm)
        bars.append(_bar(ts, o, h, l, c))
    while len(bars) < 10:  # 补齐到 10 根，保持形态
        last = bars[-1]
        ts = last.timestamp + timedelta(minutes=5)
        bars.append(_bar(ts, last.close, last.high + 0.01, last.low, last.close))
    return bars


def test_early_drop_rebound_detected():
    engine = T0DecisionEngine()
    # 早盘 09:35 急跌 6%（开盘10 → 低点9.4），随后反包
    minute = _minute_bars([
        ("09:30", 10.0, 10.05, 9.98, 10.0),
        ("09:35", 10.0, 10.0, 9.40, 9.55),
        ("09:40", 9.55, 9.70, 9.50, 9.65),
        ("09:45", 9.65, 9.80, 9.60, 9.75),
        ("09:50", 9.75, 9.85, 9.70, 9.80),
    ])
    result = engine.analyze("600519", _daily_bars(), minute, prev_close=10.0, name="贵州茅台")
    assert result.early_drop_rebound is True
    assert "反包" in result.intraday_pattern


def test_early_drop_rebound_afternoon_low_not_flagged():
    engine = T0DecisionEngine()
    # 低点出现在下午 14:00 → 不触发早盘反包
    minute = _minute_bars([
        ("09:30", 10.0, 10.05, 9.98, 10.0),
        ("10:00", 10.0, 10.0, 9.90, 9.95),
        ("13:00", 9.95, 9.95, 9.40, 9.50),
        ("14:00", 9.50, 9.60, 9.45, 9.55),
        ("14:30", 9.55, 9.60, 9.50, 9.58),
    ])
    result = engine.analyze("600519", _daily_bars(), minute, prev_close=10.0, name="贵州茅台")
    assert result.early_drop_rebound is False


# ── divergence_consensus 缩量创新高加分 ──

def test_consensus_new_high_control_bonus():
    n = 25
    closes = [10.0 * (1.005 ** i) for i in range(n)]
    volumes = [1000.0 * (0.9 ** i) for i in range(n)]  # 持续缩量，末根极低
    result = DivergenceConsensusAnalyzer().analyze(closes, volumes)
    assert result.phase.value == "CONSENSUS"
    assert result.new_high_control is True
    assert result.score >= 78.0  # 基础 75 + 3 加分
    assert any("缩量创新高" in s for s in result.signals)


def test_consensus_no_new_high_control_when_volume_not_half():
    # 新高考入但末根量比 >= 0.5 前窗均值 → 不触发"缩量新高"加分（仍为普通一致态）
    n = 20
    closes = [10.0 * (1.005 ** i) for i in range(n)]  # 单调上涨 → 末根为新高
    volumes = [1000.0] * 16 + [700.0, 650.0, 620.0, 600.0]  # 尾段温和缩量，末根 600
    prior_avg = sum(volumes[-19:-1]) / 19
    assert 0.5 * prior_avg < 600.0  # 末根量比 > 0.5 → 条件不满足
    result = DivergenceConsensusAnalyzer().analyze(closes, volumes)
    assert result.phase.value == "CONSENSUS"
    assert result.new_high_control is False


# ── risk_monitor 炸板潮 → 空仓检验联动 ──

def test_break_wave_alert_links_empty_position_check():
    alerts = RiskMonitor()._check_limit_up_sentiment(
        {"break_rate": 0.5, "zt_count": 20, "dt_count": 30}
    )
    assert len(alerts) == 1
    assert "空仓检验" in alerts[0].message
    assert "r020" in alerts[0].message
