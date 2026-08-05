# -*- coding: utf-8 -*-
from src.doctrine.checker import DoctrineChecker
from src.doctrine.rules import MILITARY_RULES

_checker = DoctrineChecker()


def _ids():
    return {r.id for r in MILITARY_RULES}


def test_rules_registered():
    ids = _ids()
    assert "r037" in ids and "r038" in ids


def test_r037_triggers_on_sell_signal():
    ctx = {"chanlun_sell_signal": "sell"}
    dr = _checker.check("000001", ctx)
    assert "r037" in [w.id for w in dr.warnings]


def test_r037_triggers_on_zs_break():
    ctx = {"chanlun_zs_break": True}
    dr = _checker.check("000001", ctx)
    assert "r037" in [w.id for w in dr.warnings]


def test_r037_not_triggered_when_clean():
    ctx = {"chanlun_sell_signal": "", "chanlun_zs_break": False}
    dr = _checker.check("000001", ctx)
    assert "r037" not in [w.id for w in dr.warnings]


def test_r038_only_when_break_and_unconfirmed():
    ctx = {"chanlun_zs_break": True, "chanlun_buy_confirmed": False,
           "chanlun_bihuang_down": False}
    dr = _checker.check("000001", ctx)
    assert "r038" in [w.id for w in dr.warnings]


def test_r038_not_triggered_when_confirmed():
    ctx = {"chanlun_zs_break": True, "chanlun_buy_confirmed": True,
           "chanlun_bihuang_down": True}
    dr = _checker.check("000001", ctx)
    assert "r038" not in [w.id for w in dr.warnings]


def test_r038_not_triggered_without_break():
    ctx = {"chanlun_zs_break": False, "chanlun_buy_confirmed": False,
           "chanlun_bihuang_down": False}
    dr = _checker.check("000001", ctx)
    assert "r038" not in [w.id for w in dr.warnings]
