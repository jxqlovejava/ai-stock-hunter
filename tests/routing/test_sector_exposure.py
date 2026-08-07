# -*- coding: utf-8 -*-
"""P3: 行业暴露注入 — _inject_sector_exposure 复活 risk_control._check_sector_cap。

全部为 mock 级测试，不触发网络。覆盖:
  ① 同行业其余持仓市值 / 权益 → sector_pct
  ② 无持仓 → 惰性 (不写 sector_pct)
  ③ 目标"未分类" → 惰性
  ④ total_equity=0 → 回退持仓市值总和为分母
  ⑤ 排除目标自身持仓 (避免与 target_weight 重复计数)
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.routing.orchestrator import Orchestrator

SYMBOL = "000001"
NAME = "测试"


class _Sector:
    def __init__(self, sw1):
        self.sw1_name = sw1


class _FakeClassifier:
    """全部 symbol → 同一行业 (电子)，便于断言聚合。"""

    def __init__(self, sw1="电子"):
        self._sw1 = sw1

    def classify(self, symbol, name):
        return _Sector(self._sw1)

    def classify_batch(self, symbols):
        return {s: _Sector(self._sw1) for s in symbols}


def _pos(symbol, quantity, last_price, entry_price=None):
    return SimpleNamespace(
        symbol=symbol, quantity=quantity,
        last_price=last_price,
        entry_price=entry_price if entry_price is not None else last_price,
    )


def _make_orch(classifier, positions, total_equity=100000.0):
    orch = object.__new__(Orchestrator)  # 绕过 __init__，只测该方法
    orch._sector_classifier = classifier
    orch.position_state_mgr = MagicMock()
    orch.position_state_mgr.get_all.return_value = positions
    portfolio = {"total_equity": total_equity}
    return orch, portfolio


# ═══════════════════════════════════════════════════════════════════
# ① 基本聚合
# ═══════════════════════════════════════════════════════════════════
def test_sector_pct_computed_from_same_industry_holdings():
    # 目标 000001 (电子) + 同行业 000002 (电子, 值20000) + 其他 600001 (电子, 值30000)
    # 目标自身 000001 持仓 值 10000 → 计入分母但不计入同行业
    orch, portfolio = _make_orch(
        _FakeClassifier("电子"),
        [
            _pos(SYMBOL, 1000, 10.0),      # 10000 (目标自身)
            _pos("000002", 2000, 10.0),    # 20000 同行业
            _pos("600001", 3000, 10.0),    # 30000 同行业(分类器全给电子)
        ],
        total_equity=100000.0,
    )
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    assert portfolio["sector_pct"] == round(0.5, 4)   # (20000+30000)/100000
    assert portfolio["sector_exposure"] == {"电子": round(0.5, 4)}


def test_sector_pct_excludes_target_itself():
    """目标自身已有大额持仓，不计入 same_industry_value (weight 已含目标)。"""
    orch, portfolio = _make_orch(
        _FakeClassifier("电子"),
        [
            _pos(SYMBOL, 10000, 10.0),   # 100000 (目标自身, 巨大)
            _pos("000002", 1000, 10.0),  # 10000 同行业
        ],
        total_equity=200000.0,
    )
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    assert portfolio["sector_pct"] == round(10000 / 200000, 4)  # 仅 000002


# ═══════════════════════════════════════════════════════════════════
# ② 惰性回退
# ═══════════════════════════════════════════════════════════════════
def test_sector_pct_noop_when_no_positions():
    orch, portfolio = _make_orch(_FakeClassifier("电子"), [])
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    assert "sector_pct" not in portfolio


def test_sector_pct_noop_when_target_unclassified():
    orch, portfolio = _make_orch(_FakeClassifier("未分类"), [_pos("000002", 2000, 10.0)])
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    assert "sector_pct" not in portfolio


def test_sector_pct_noop_when_classifier_missing():
    orch = object.__new__(Orchestrator)
    orch._sector_classifier = None
    orch.position_state_mgr = MagicMock()
    orch.position_state_mgr.get_all.return_value = [_pos("000002", 2000, 10.0)]
    portfolio = {"total_equity": 100000.0}
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    assert "sector_pct" not in portfolio


def test_sector_pct_falls_back_to_holdings_value():
    """total_equity=0 → 分母回退为全部持仓市值之和。"""
    orch, portfolio = _make_orch(
        _FakeClassifier("电子"),
        [
            _pos("000002", 2000, 10.0),   # 20000 同行业
            _pos("600001", 3000, 10.0),   # 30000 同行业
        ],
        total_equity=0,
    )
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)
    # 分母 = 50000 (持仓总市值), 同行业 = 50000 → 100%
    assert portfolio["sector_pct"] == 1.0


def test_sector_pct_silent_on_classifier_exception():
    """分类器抛异常 → 静默回退 (规则保持惰性)。"""

    class _Exploding:
        def classify(self, symbol, name):
            raise RuntimeError("network down")

    orch, portfolio = _make_orch(_Exploding(), [_pos("000002", 2000, 10.0)])
    orch._inject_sector_exposure(portfolio, SYMBOL, NAME)  # 不应抛错
    assert "sector_pct" not in portfolio
