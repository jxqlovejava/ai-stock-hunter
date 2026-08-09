"""DXY provider 测试 — mock 网络层，验证降级链 + 交叉验证逻辑。"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.macro import debt_cycle
from src.macro.dxy_provider import (
    MIN_BARS_FOR_CHANGE,
    DXY_CONSTANT,
    DxyData,
    _compute_dxy,
    _pct_change,
    fetch_dxy,
)
from src.macro.debt_cycle import (
    DebtCycleAnalyzer,
    DebtCycleResult,
    DollarTideAnalyzer,
    DollarTideSignal,
)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """默认拦截 TradingView 网络请求（非 tradingview 专项测试勿发起真实请求）。"""
    monkeypatch.setattr(
        "src.macro.dxy_provider._http_post_json",
        lambda url, payload, referer, timeout=6: {"data": []},
    )


# ---------------------------------------------------------------------------
# Mock 载荷构造
# ---------------------------------------------------------------------------

def _em_quote(dxy: float) -> dict:
    return {
        "data": {
            "f43": dxy,
            "f57": "UDI",
            "f58": "美元指数",
            "f60": round(dxy + 0.34, 2),
            "f170": -0.34,
        }
    }


def _em_hist(closes: list[float]) -> dict:
    """东财 K 线行: date,open,close,high,low,volume,amount"""
    lines = []
    d = date(2026, 6, 1)
    for c in closes:
        lines.append(f"{d.isoformat()},{c},{c},{c},{c},0,0.00")
        d += timedelta(days=1)
    return {"data": {"klines": lines}}


def _yahoo(closes: list[float]) -> dict:
    return {"chart": {"result": [{"indicators": {"quote": [{"close": closes}]}}]}}


def _frankfurter(jpy_series: list[float]) -> dict:
    """构造 ECB rates：JPY 逐日变化，其余 5 币种恒定 → DXY 序列确定。"""
    dates = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(len(jpy_series))]
    rates = {}
    for d, jpy in zip(dates, jpy_series):
        rates[d] = {"EUR": 0.86693, "JPY": jpy, "GBP": 0.74352, "CAD": 1.401, "SEK": 9.4889, "CHF": 0.81032}
    return {"rates": rates}


def _closes(n: int = MIN_BARS_FOR_CHANGE, last: float = 102.0) -> list[float]:
    """生成 n 根收盘序列，最后一根 = last（默认 100.0 → 102.0，20日变化 +2.0）。"""
    return [round(100.0 + i * (last - 100.0) / (n - 1), 4) for i in range(n)]


def _tv(dxy: float) -> dict:
    return {"data": [{"s": "TVC:DXY", "d": [dxy, "美元指数", "USD"]}]}


def _mock_http(em_quote=None, em_hist=None, yahoo=None, frankfurter=None, tradingview=None,
               em_raise=None, yh_raise=None, ff_raise=None, tv_raise=None):
    """按 URL 分发 mock 响应；raise 参数为要抛的异常类。
    frankfurter/tradingview 默认空 → 该源无效。"""

    def mock(url: str) -> dict:
        if tv_raise and "scanner.tradingview.com" in url:
            raise tv_raise("tradingview network error")
        if em_raise and "push2" in url:
            raise em_raise("eastmoney network error")
        if yh_raise and "query1.finance.yahoo.com" in url:
            raise yh_raise("yahoo network error")
        if ff_raise and "api.frankfurter.app" in url:
            raise ff_raise("frankfurter network error")
        if "scanner.tradingview.com" in url:
            return tradingview if tradingview is not None else {"data": []}
        if "api.frankfurter.app" in url:
            return frankfurter if frankfurter is not None else {"rates": {}}
        if "push2his.eastmoney.com" in url:
            if em_hist is None:
                raise AssertionError(f"unexpected hist url: {url}")
            return em_hist
        if "push2.eastmoney.com" in url:
            if em_quote is None:
                raise AssertionError(f"unexpected quote url: {url}")
            return em_quote
        if "query1.finance.yahoo.com" in url:
            if yahoo is None:
                raise AssertionError(f"unexpected yahoo url: {url}")
            return yahoo
        raise AssertionError(f"unexpected url: {url}")

    return mock


# ---------------------------------------------------------------------------
# _compute_dxy / _pct_change 纯函数
# ---------------------------------------------------------------------------

def test_compute_dxy_all_rates_unity():
    rates = {"EUR": 1.0, "JPY": 1.0, "GBP": 1.0, "CAD": 1.0, "SEK": 1.0, "CHF": 1.0}
    assert _compute_dxy(rates) == pytest.approx(DXY_CONSTANT)


def test_compute_dxy_missing_key_returns_none():
    rates = {"EUR": 1.0, "JPY": 1.0}  # 缺 GBP/CAD/SEK/CHF
    assert _compute_dxy(rates) is None


def test_compute_dxy_zero_division_safe():
    rates = {"EUR": 0.0, "JPY": 1.0, "GBP": 1.0, "CAD": 1.0, "SEK": 1.0, "CHF": 1.0}
    assert _compute_dxy(rates) is None


def test_pct_change():
    assert _pct_change(102.0, 100.0) == 2.0
    assert _pct_change(99.6, 100.0) == -0.4
    assert _pct_change(100.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# fetch_dxy 降级链 + 交叉验证
# ---------------------------------------------------------------------------

def test_tradingview_priority_and_cross_validate():
    """TradingView(真实源) 命中时优先取其值；change 由东财K线补齐；双源交叉验证通过。"""
    closes = _closes()  # 100.0 -> 102.0
    mock = _mock_http(em_quote=_em_quote(102.0), em_hist=_em_hist(closes), yahoo=_yahoo(closes))
    tv_mock = lambda url, payload, referer, timeout=6: _tv(102.0)  # noqa: E731
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock), \
         patch("src.macro.dxy_provider._http_post_json", side_effect=tv_mock):
        data = fetch_dxy()
    assert data.dxy == 102.0
    assert data.dxy_estimated is False  # TradingView 为真实源，非估算
    assert data.dxy_change_20d == 2.0
    assert data.source.startswith("tradingview")
    assert data.cross_validated is True


def test_tradingview_only_realtime_no_change():
    """仅 TradingView 可达 → 真实实时值，无 20日变化，单源未交叉验证。"""
    mock = _mock_http(em_raise=ConnectionError, yh_raise=ConnectionError, ff_raise=ConnectionError)
    tv_mock = lambda url, payload, referer, timeout=6: _tv(99.6)  # noqa: E731
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock), \
         patch("src.macro.dxy_provider._http_post_json", side_effect=tv_mock):
        data = fetch_dxy()
    assert data.dxy == 99.6
    assert data.dxy_estimated is False
    assert data.dxy_change_20d is None
    assert data.cross_validated is False


def test_tradingview_down_falls_back_to_others():
    """无 VPN（TradingView 不可达）→ 走东财/Yahoo 真实源，不阻塞。"""
    closes = _closes()
    mock = _mock_http(em_quote=_em_quote(102.0), em_hist=_em_hist(closes), yahoo=_yahoo(closes))
    tv_mock = lambda url, payload, referer, timeout=6: (_ for _ in ()).throw(  # noqa: E731
        ConnectionError("no vpn"))
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock), \
         patch("src.macro.dxy_provider._http_post_json", side_effect=tv_mock):
        data = fetch_dxy()
    assert data.dxy == 102.0
    assert data.source == "eastmoney+yahoo"
    assert "tradingview" not in data.source


def test_both_sources_consistent_cross_validated():
    closes = _closes()  # 100.0 -> 102.0
    mock = _mock_http(em_quote=_em_quote(102.0), em_hist=_em_hist(closes), yahoo=_yahoo(closes))
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy == 102.0
    assert data.dxy_change_20d == 2.0  # (102/100 - 1)*100
    assert data.cross_validated is True
    assert data.source == "eastmoney+yahoo"


def test_eastmoney_falls_back_to_frankfurter():
    jpy = _closes()  # 驱动 DXY 序列
    mock = _mock_http(frankfurter=_frankfurter(jpy), em_raise=ConnectionError)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.source == "frankfurter"
    assert data.dxy is not None
    assert data.dxy_change_20d is not None
    assert data.cross_validated is False  # 单源


def test_eastmoney_and_yahoo_down_uses_frankfurter():
    jpy = _closes()
    mock = _mock_http(frankfurter=_frankfurter(jpy), em_raise=ConnectionError, yh_raise=ConnectionError)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.source == "frankfurter"
    assert data.dxy is not None


def test_estimated_flags_when_only_frankfurter():
    """官方源全挂 → 估算值必须显式标记 estimated，禁止冒充实际 DXY。"""
    jpy = _closes()
    mock = _mock_http(frankfurter=_frankfurter(jpy), em_raise=ConnectionError, yh_raise=ConnectionError)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy_estimated is True
    assert data.change_estimated is True
    assert data.source == "frankfurter"


def test_dxy_official_but_change_estimated():
    """东财实时官方值 + Frankfurter 估算序列做20日变化 → 分开标记。"""
    def mock(url: str):
        if "push2his.eastmoney.com" in url:
            raise ConnectionError("hist down")
        if "push2.eastmoney.com" in url:
            return _em_quote(102.0)
        if "query1.finance.yahoo.com" in url:
            raise ConnectionError("yahoo down")
        if "api.frankfurter.app" in url:
            return _frankfurter(_closes())
        raise AssertionError(url)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy == 102.0
    assert data.dxy_estimated is False  # 官方实时值
    assert data.change_estimated is True  # 20日变化来自估算序列
    assert data.dxy_change_20d is not None


def test_all_sources_fail_returns_errors():
    mock = _mock_http(em_raise=ConnectionError, yh_raise=ConnectionError, ff_raise=ConnectionError)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy is None
    assert data.dxy_change_20d is None
    assert any("美元指数" in e for e in data.errors)


def test_divergent_sources_not_cross_validated():
    closes_em = _closes(last=102.0)
    closes_yh = _closes(last=105.0)  # 差 ~2.9% > 0.5%
    mock = _mock_http(em_quote=_em_quote(102.0), em_hist=_em_hist(closes_em), yahoo=_yahoo(closes_yh))
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.cross_validated is False


def test_any_two_sources_cross_validate():
    """东财/Yahoo 实时一致，Frankfurter 计算值偏离 → 仍算交叉验证通过。"""
    closes = _closes()
    jpy = _closes(last=160.0)  # 让 Frankfurter DXY 明显偏离
    mock = _mock_http(em_quote=_em_quote(102.0), em_hist=_em_hist(closes),
                      yahoo=_yahoo(closes), frankfurter=_frankfurter(jpy))
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.cross_validated is True  # 因 em+yahoo 一致
    assert data.dxy == 102.0  # 官方实时优先


def test_realtime_without_history_change_is_none():
    def mock(url: str):
        if "push2his.eastmoney.com" in url:
            raise ConnectionError("hist down")
        if "push2.eastmoney.com" in url:
            return _em_quote(99.6)
        if "query1.finance.yahoo.com" in url:
            raise ConnectionError("yahoo down")
        if "api.frankfurter.app" in url:
            raise ConnectionError("frankfurter down")
        raise AssertionError(url)
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy == 99.6
    assert data.dxy_change_20d is None
    assert data.source == "eastmoney"


def test_insufficient_bars_change_is_none():
    short = _closes(n=10, last=101.0)
    mock = _mock_http(em_quote=_em_quote(101.0), em_hist=_em_hist(short), yahoo=_yahoo(short))
    with patch("src.macro.dxy_provider._http_get_json", side_effect=mock):
        data = fetch_dxy()
    assert data.dxy == 101.0
    assert data.dxy_change_20d is None


# ---------------------------------------------------------------------------
# debt_cycle 集成（mock fetch_dxy，验证 _fetch_dxy 行为）
# ---------------------------------------------------------------------------

def test_debt_cycle_fetch_dxy_sets_fields():
    sig = DollarTideSignal()
    with patch.object(debt_cycle, "fetch_dxy", return_value=DxyData(
        dxy=99.6, dxy_change_20d=-1.2, source="eastmoney+yahoo", cross_validated=True,
    )):
        DollarTideAnalyzer()._fetch_dxy(sig)
    assert sig.dxy == 99.6
    assert sig.dxy_change_20d == -1.2
    assert sig.data_gaps == []


def test_debt_cycle_fetch_dxy_marks_single_source():
    sig = DollarTideSignal()
    with patch.object(debt_cycle, "fetch_dxy", return_value=DxyData(
        dxy=99.6, dxy_change_20d=-1.2, source="frankfurter", cross_validated=False,
    )):
        DollarTideAnalyzer()._fetch_dxy(sig)
    assert sig.dxy == 99.6
    assert any("单源" in g for g in sig.data_gaps)


def test_debt_cycle_fetch_dxy_gap_on_failure():
    sig = DollarTideSignal()
    with patch.object(debt_cycle, "fetch_dxy", return_value=DxyData(
        errors=["美元指数DXY 所有来源均失败"],
    )):
        DollarTideAnalyzer()._fetch_dxy(sig)
    assert sig.dxy is None
    assert "美元指数DXY 所有来源均失败" in sig.data_gaps


def test_debt_cycle_marks_estimated_value():
    """估算值必须标记 [ESTIMATED]，且 dxy_estimated 置位。"""
    sig = DollarTideSignal()
    with patch.object(debt_cycle, "fetch_dxy", return_value=DxyData(
        dxy=99.86, dxy_change_20d=-0.99,
        dxy_estimated=True, change_estimated=True,
        source="frankfurter", cross_validated=False,
    )):
        DollarTideAnalyzer()._fetch_dxy(sig)
    assert sig.dxy == 99.86
    assert sig.dxy_estimated is True
    assert any("[ESTIMATED]" in g for g in sig.data_gaps)


def test_debt_cycle_official_value_not_estimated():
    sig = DollarTideSignal()
    with patch.object(debt_cycle, "fetch_dxy", return_value=DxyData(
        dxy=99.6, dxy_change_20d=-0.34,
        dxy_estimated=False, change_estimated=False,
        source="eastmoney", cross_validated=False,
    )):
        DollarTideAnalyzer()._fetch_dxy(sig)
    assert sig.dxy == 99.6
    assert sig.dxy_estimated is False
    assert not any("[ESTIMATED]" in g for g in sig.data_gaps)


def test_confidence_penalized_when_dxy_estimated():
    res = DebtCycleResult()
    res.signals = {
        "sf_growth": 8.0, "credit_pulse": 2.0, "m1_m2_gap": 0.5,
        "dr007": 1.8, "dxy": 99.86, "us10y": 3.0, "usdcny": 7.2,
    }
    res.dollar_tide.dxy_estimated = True
    c_est = DebtCycleAnalyzer._confidence(res)
    res.dollar_tide.dxy_estimated = False
    c_official = DebtCycleAnalyzer._confidence(res)
    assert c_est == pytest.approx(c_official - 0.1)
