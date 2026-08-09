"""军规 r051-r054 季节性风险窗口测试。"""

from src.doctrine.checker import DoctrineChecker

_checker = DoctrineChecker()


_SEASONAL_IDS = {"r051", "r052", "r053", "r054"}


def _warn_ids(ctx) -> set[str]:
    """返回触发的 warn 级军规 id 集合。"""
    result = _checker.check("600519", ctx)
    return {r.id for r in result.warnings}


def _seasonal_fired(ctx) -> set[str]:
    """只取季节性相关军规中触发的部分（忽略其他 WARN，如 r032/r033）。"""
    return _warn_ids(ctx) & _SEASONAL_IDS


def _base_ctx() -> dict:
    return {}


def test_r051_year_end_triggers_only_its_flag():
    ctx = _base_ctx() | {"seasonal_year_end_window": True}
    ids = _warn_ids(ctx)
    assert "r051" in ids
    assert "r052" not in ids and "r053" not in ids and "r054" not in ids


def test_r052_april_triggers_only_its_flag():
    ctx = _base_ctx() | {"seasonal_april_window": True}
    ids = _warn_ids(ctx)
    assert "r052" in ids and "r051" not in ids


def test_r053_august_triggers_only_its_flag():
    ctx = _base_ctx() | {"seasonal_august_window": True}
    ids = _warn_ids(ctx)
    assert "r053" in ids and "r051" not in ids


def test_r054_october_triggers_only_its_flag():
    ctx = _base_ctx() | {"seasonal_october_window": True}
    ids = _warn_ids(ctx)
    assert "r054" in ids and "r051" not in ids


def test_no_data_no_false_positive():
    """无季节性 ctx → 季节军规全部不触发（防御原则）。"""
    assert _seasonal_fired(_base_ctx()) == set()


def test_all_false_no_false_positive():
    """flag 全 False → 季节军规全部不触发。"""
    ctx = {
        "seasonal_year_end_window": False,
        "seasonal_april_window": False,
        "seasonal_august_window": False,
        "seasonal_october_window": False,
    }
    assert _seasonal_fired(ctx) == set()


def test_rule_ids_registered():
    """r051-r054 已注册且为 WARN 级。"""
    from src.doctrine.rules import MILITARY_RULES

    by_id = {r.id: r for r in MILITARY_RULES}
    for rid in ("r051", "r052", "r053", "r054"):
        assert rid in by_id, f"{rid} 未注册"
        assert by_id[rid].severity.value == "warn"
