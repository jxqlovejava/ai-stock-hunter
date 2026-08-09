# -*- coding: utf-8 -*-
"""确定性盘面快照锚定 (反幻觉) 测试。"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

from src.data.schema import Quote
from src.data.verified_snapshot import (
    VerifiedSnapshot,
    check_price_claims,
    get_verified_market_snapshot,
)


def _quote(price: float = 1712.5, source: str = "tencent") -> Quote:
    return Quote(
        symbol="600519",
        name="贵州茅台",
        price=price,
        change_pct=1.2,
        volume=10000,
        turnover=2_000_000_000.0,
        high=1720.0,
        low=1700.0,
        open=1705.0,
        prev_close=1692.0,
        source=source,
    )


def _snap() -> VerifiedSnapshot:
    return VerifiedSnapshot(
        symbol="600519",
        name="贵州茅台",
        price=1712.5,
        change_pct=1.2,
        turnover=2_000_000_000.0,
        cross_validated=True,
        dispute=False,
        source="tencent",
    )


class TestGetVerifiedSnapshot:
    def test_cross_validated(self):
        agg = mock.Mock()
        agg.get_cross_validated_quote.return_value = (_quote(), True, False)
        snap = get_verified_market_snapshot("600519", aggregator=agg)
        assert snap is not None
        assert snap.price == 1712.5
        assert snap.cross_validated is True
        assert snap.dispute is False

    def test_single_source(self):
        agg = mock.Mock()
        agg.get_cross_validated_quote.return_value = (_quote(), False, False)
        snap = get_verified_market_snapshot("600519", aggregator=agg)
        assert snap.cross_validated is False
        assert "单源未验证" in snap.anchor_block()

    def test_dispute_flagged(self):
        agg = mock.Mock()
        agg.get_cross_validated_quote.return_value = (_quote(), True, True)
        snap = get_verified_market_snapshot("600519", aggregator=agg)
        assert snap.dispute is True
        assert "[DISPUTED]" in snap.anchor_block()

    def test_no_quote_returns_none(self):
        agg = mock.Mock()
        agg.get_cross_validated_quote.return_value = (None, False, False)
        assert get_verified_market_snapshot("600519", aggregator=agg) is None

    def test_exception_defensive(self):
        agg = mock.Mock()
        agg.get_cross_validated_quote.side_effect = RuntimeError("boom")
        assert get_verified_market_snapshot("600519", aggregator=agg) is None


class TestCheckPriceClaims:
    def test_no_conflict(self):
        assert check_price_claims("当前价 1713 元，技术面健康", _snap()) == []

    def test_conflict_detected(self):
        conflicts = check_price_claims("当前价 1600 元，已破位", _snap())
        assert len(conflicts) == 1
        assert conflicts[0].claimed_price == 1600.0
        assert conflicts[0].snapshot_price == 1712.5
        assert conflicts[0].deviation_pct > 5.0

    def test_multiple_claims_dedup(self):
        conflicts = check_price_claims(
            "最新价 1600，当前价 1600，现价 1800", _snap()
        )
        claimed = sorted(c.claimed_price for c in conflicts)
        assert claimed == [1600.0, 1800.0]

    def test_empty_text(self):
        assert check_price_claims("", _snap()) == []

    def test_zero_snapshot_no_check(self):
        snap = _snap()
        snap.price = 0.0
        assert check_price_claims("当前价 1600", snap) == []


class TestAnchorBlock:
    def test_block_content(self):
        block = _snap().anchor_block()
        assert "1712.5" in block
        assert "双源交叉验证" in block


class TestTechnicalAnchor:
    def test_snapshot_wired_into_report(self):
        from src.routing.technical import TechnicalAnalyzer, TechnicalReport

        report = TechnicalReport(symbol="600519")
        with mock.patch(
            "src.data.verified_snapshot.get_verified_market_snapshot",
            return_value=_snap(),
        ):
            TechnicalAnalyzer()._anchor_snapshot(report)
        assert report.verified_snapshot is not None
        assert report.verified_snapshot.price == 1712.5  # DTO 对象直存
        assert "1712.5" in report.verified_snapshot.anchor_block()

    def test_market_derived_from_symbol(self):
        from src.routing.technical import TechnicalAnalyzer, TechnicalReport

        calls = []
        snap = _snap()

        def fake_get(symbol, market="SH"):
            calls.append(market)
            return snap

        report = TechnicalReport(symbol="000858")  # 深市
        with mock.patch(
            "src.data.verified_snapshot.get_verified_market_snapshot",
            side_effect=fake_get,
        ):
            TechnicalAnalyzer()._anchor_snapshot(report)
        assert calls == ["SZ"]  # 深市代码 → SZ

    def test_snapshot_missing_adds_gap(self):
        from src.routing.technical import TechnicalAnalyzer, TechnicalReport

        report = TechnicalReport(symbol="600519")
        with mock.patch(
            "src.data.verified_snapshot.get_verified_market_snapshot",
            return_value=None,
        ):
            TechnicalAnalyzer()._anchor_snapshot(report)
        assert report.verified_snapshot is None
        assert "verified_snapshot" in report.data_gaps
