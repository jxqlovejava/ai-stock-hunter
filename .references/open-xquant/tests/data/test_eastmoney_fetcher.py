"""Tests for EastMoneyFetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from oxq.data.factors import EASTMONEY_FIELD_MAP, EastMoneyFetcher
from oxq.data.providers import FactorFetcher


def _make_abstract_df() -> pd.DataFrame:
    """Fake stock_financial_abstract response (pivot table: metrics x periods).

    Includes direct metrics and extra metrics needed for computed indicators.
    """
    return pd.DataFrame({
        "选项": [
            "常用指标", "常用指标", "常用指标", "常用指标",
            "常用指标", "常用指标", "常用指标", "财务风险",
        ],
        "指标": [
            "基本每股收益", "营业总收入", "净利润",
            "净资产收益率(ROE)", "每股净资产", "经营现金流量净额",
            "股东权益合计(净资产)", "权益乘数",
        ],
        "20240630": [29.42, 8.69e10, 4.16e10, 16.42, 179.83, 2.13e10, 2.28e11, 1.27],
        "20240331": [16.16, 4.59e10, 2.28e10, 8.87, 174.53, 7.45e9, 2.13e11, 1.15],
    })


class TestEastMoneyFetcher:
    def test_satisfies_protocol(self) -> None:
        fetcher = EastMoneyFetcher()
        assert isinstance(fetcher, FactorFetcher)

    def test_list_indicators(self) -> None:
        fetcher = EastMoneyFetcher()
        indicators = fetcher.list_indicators()
        assert len(indicators) == 12
        assert indicators == sorted(indicators)
        assert set(indicators) == set(EASTMONEY_FIELD_MAP)

    @patch("oxq.data.factors.akshare", create=True)
    def test_fetch_all_indicators(self, mock_ak: MagicMock) -> None:
        mock_ak.stock_financial_abstract.return_value = _make_abstract_df()

        fetcher = EastMoneyFetcher()
        df = fetcher.fetch("600519", "2024-01-01", "2024-12-31")

        assert df.index.name == "report_date"
        assert len(df) == 2
        # Check key indicator columns
        for col in ["eps", "revenue", "net_income", "roe", "book_value_per_share",
                     "operating_cash_flow", "total_assets", "total_shares"]:
            assert col in df.columns, f"Missing column: {col}"
        assert "period" in df.columns

        # Spot-check direct values
        row = df.loc[pd.Timestamp("2024-06-30")]
        assert row["eps"] == pytest.approx(29.42)
        assert row["revenue"] == pytest.approx(8.69e10)
        assert row["operating_cash_flow"] == pytest.approx(2.13e10)

        # Spot-check computed values
        # total_assets = equity * multiplier = 2.28e11 * 1.27
        assert row["total_assets"] == pytest.approx(2.28e11 * 1.27)
        # total_shares = equity / bvps = 2.28e11 / 179.83
        assert row["total_shares"] == pytest.approx(2.28e11 / 179.83)

    @patch("oxq.data.factors.akshare", create=True)
    def test_fetch_filters_by_period_annual(self, mock_ak: MagicMock) -> None:
        abstract = _make_abstract_df()
        # Add an annual column (12-31)
        abstract["20241231"] = [58.84, 1.74e11, 8.32e10, 32.84, 185.0, 4.26e10, 2.40e11, 1.25]

        mock_ak.stock_financial_abstract.return_value = abstract

        fetcher = EastMoneyFetcher()
        df = fetcher.fetch("600519", "2024-01-01", "2025-12-31", period="annual")

        assert len(df) == 1
        assert all(df["period"] == "annual")

    @patch("oxq.data.factors.akshare", create=True)
    def test_fetch_specific_indicators(self, mock_ak: MagicMock) -> None:
        mock_ak.stock_financial_abstract.return_value = _make_abstract_df()

        fetcher = EastMoneyFetcher()
        df = fetcher.fetch(
            "600519", "2024-01-01", "2024-12-31", indicators=["eps", "revenue"]
        )

        assert "eps" in df.columns
        assert "revenue" in df.columns
        # Only one API call (stock_financial_abstract)
        mock_ak.stock_financial_abstract.assert_called_once()

    @patch("oxq.data.factors.akshare", create=True)
    def test_fetch_empty_raises(self, mock_ak: MagicMock) -> None:
        # Abstract with no date columns in range
        mock_ak.stock_financial_abstract.return_value = _make_abstract_df()

        fetcher = EastMoneyFetcher()
        from oxq.core.errors import DownloadError

        with pytest.raises(DownloadError, match="No data returned"):
            fetcher.fetch("600519", "2030-01-01", "2030-12-31")
