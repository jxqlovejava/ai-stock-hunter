"""债务周期阶段判定 + 美元潮汐方向 纯逻辑测试（无网络）。"""

from src.macro.debt_cycle import (
    CREDIT_PULSE_EXPAND,
    CREDIT_PULSE_CONTRACT,
    CREDIT_PULSE_FROTH,
    DebtCycleAnalyzer,
    DebtCyclePhase,
    DebtCycleResult,
    DollarTideSignal,
    DollarTideAnalyzer,
    NOMINAL_GDP_GROWTH,
)


def _result(signals: dict) -> DebtCycleResult:
    res = DebtCycleResult()
    res.signals = {"sf_growth": None, "credit_pulse": None, "dr007": None, **signals}
    return res


def test_credit_expansion_when_pulse_positive():
    """信贷脉冲 > 阈值 → 加杠杆/信用扩张。"""
    res = _result({"credit_pulse": CREDIT_PULSE_EXPAND + 0.5, "sf_growth": NOMINAL_GDP_GROWTH})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.CREDIT_EXPANSION


def test_deleveraging_when_pulse_negative():
    """信贷脉冲转负 → 去杠杆。"""
    res = _result({"credit_pulse": CREDIT_PULSE_CONTRACT - 0.5})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.DELEVERAGING


def test_asset_froth_when_strong_pulse_and_high_sf():
    """信贷脉冲强扩张 + 社融高 → 资产泡沫累积。"""
    res = _result({"credit_pulse": CREDIT_PULSE_FROTH + 1, "sf_growth": NOMINAL_GDP_GROWTH + 2})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.ASSET_FROTH


def test_neutral_when_no_data():
    """无数据 → 中性，不误判。"""
    res = _result({})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.NEUTRAL


def test_dr007_proxy_when_no_pulse():
    """信贷脉冲缺失 + DR007 高 → 去杠杆弱代理。"""
    res = _result({"dr007": 2.5})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.DELEVERAGING


def test_m1m2_proxy_when_no_pulse():
    """信贷脉冲缺失 + M1-M2 剪刀差走阔 → 扩张代理。"""
    res = _result({"m1_m2_gap": 2.0})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.CREDIT_EXPANSION
    # 剪刀差倒挂 → 收缩
    res2 = _result({"m1_m2_gap": -2.0})
    DebtCycleAnalyzer._classify_phase(res2)
    assert res2.phase == DebtCyclePhase.DELEVERAGING


def test_m1m2_proxy_bounded():
    """M1-M2 接近零 → 不触发扩张/收缩，走中性。"""
    res = _result({"m1_m2_gap": 0.2})
    DebtCycleAnalyzer._classify_phase(res)
    assert res.phase == DebtCyclePhase.NEUTRAL


def test_tide_outflow_when_rates_rise():
    """美债利率上升 → 美元潮汐流出。"""
    sig = DollarTideSignal(us10y_change_20d=25.0, dxy_change_20d=2.0, usdcny_change_20d=1.5)
    DollarTideAnalyzer()._classify_tide(sig)
    assert sig.tide_direction == "outflow"


def test_tide_inflow_when_rates_fall():
    """美债利率下行 + 人民币升值 → 流入。"""
    sig = DollarTideSignal(us10y_change_20d=-20.0, dxy_change_20d=-2.0, usdcny_change_20d=-1.5)
    DollarTideAnalyzer()._classify_tide(sig)
    assert sig.tide_direction == "inflow"


def test_tide_neutral_no_data():
    sig = DollarTideSignal()
    DollarTideAnalyzer()._classify_tide(sig)
    assert sig.tide_direction == "neutral"


def test_confidence_reflects_missing_data():
    """缺失数据越多，置信度越低，且不低于 0.3。"""
    res = _result({})
    c0 = DebtCycleAnalyzer._confidence(res)
    res2 = _result({"credit_pulse": 1.5, "sf_growth": 6.0, "dr007": 1.8})
    c1 = DebtCycleAnalyzer._confidence(res2)
    assert c1 >= c0
    assert c0 >= 0.3
