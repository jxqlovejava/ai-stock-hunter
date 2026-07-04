"""Tests for YFinanceFinancialFetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pandas as pd
import pytest

from oxq.data.factors import YFinanceFinancialFetcher
from oxq.data.providers import FactorFetcher


def _make_financials() -> pd.DataFrame:
    """Fake yfinance quarterly_financials. Note: index=field_name, columns=dates."""
    return pd.DataFrame(
        {
            pd.Timestamp("2024-06-30"): [5.67, 3.61e10, 2.15e10],
            pd.Timestamp("2024-03-31"): [4.82, 3.07e10, 1.83e10],
        },
        index=["Basic EPS", "Total Revenue", "Net Income"],
    )


def _make_balance_sheet() -> pd.DataFrame:
    return pd.DataFrame(
        {
            pd.Timestamp("2024-06-30"): [3.52e11, 6.82e10, 1.54e10],
            pd.Timestamp("2024-03-31"): [3.38e11, 6.55e10, 1.54e10],
        },
        index=["Total Assets", "Stockholders Equity", "Ordinary Shares Number"],
    )


def _make_cashflow() -> pd.DataFrame:
    return pd.DataFrame(
        {
            pd.Timestamp("2024-06-30"): [2.89e10],
            pd.Timestamp("2024-03-31"): [2.56e10],
        },
        index=["Operating Cash Flow"],
    )


class TestYFinanceFinancialFetcher:
    def test_satisfies_protocol(self):
        fetcher = YFinanceFinancialFetcher()
        assert isinstance(fetcher, FactorFetcher)

    def test_list_indicators(self):
        fetcher = YFinanceFinancialFetcher()
        indicators = fetcher.list_indicators()
        assert len(indicators) == 8
        assert indicators == sorted(indicators)
        expected = [
            "book_value_per_share",
            "eps",
            "net_income",
            "operating_cash_flow",
            "revenue",
            "roe",
            "total_assets",
            "total_shares",
        ]
        assert indicators == expected

    @patch("oxq.data.factors.yfinance", create=True)
    def test_fetch_all_indicators(self, mock_yf):
        mock_ticker = MagicMock()
        type(mock_ticker).quarterly_financials = PropertyMock(
            return_value=_make_financials()
        )
        type(mock_ticker).quarterly_balance_sheet = PropertyMock(
            return_value=_make_balance_sheet()
        )
        type(mock_ticker).quarterly_cashflow = PropertyMock(
            return_value=_make_cashflow()
        )
        mock_yf.Ticker.return_value = mock_ticker

        fetcher = YFinanceFinancialFetcher()
        df = fetcher.fetch("AAPL", "2024-01-01", "2024-12-31")

        assert df.index.name == "report_date"
        assert len(df) == 2

        # All 8 indicator columns present
        for col in [
            "eps", "revenue", "net_income", "roe", "total_shares",
            "total_assets", "book_value_per_share", "operating_cash_flow",
        ]:
            assert col in df.columns

        assert "publish_date" in df.columns
        assert "period" in df.columns

        # Spot-check values (row for 2024-06-30)
        row = df.loc[pd.Timestamp("2024-06-30")]
        assert row["eps"] == pytest.approx(5.67)
        assert row["total_assets"] == pytest.approx(3.52e11)
        assert row["operating_cash_flow"] == pytest.approx(2.89e10)

        # Computed fields
        assert row["roe"] == pytest.approx(2.15e10 / 6.82e10)
        assert row["book_value_per_share"] == pytest.approx(6.82e10 / 1.54e10)

    @patch("oxq.data.factors.yfinance", create=True)
    def test_publish_date_is_nat(self, mock_yf):
        mock_ticker = MagicMock()
        type(mock_ticker).quarterly_financials = PropertyMock(
            return_value=_make_financials()
        )
        type(mock_ticker).quarterly_balance_sheet = PropertyMock(
            return_value=_make_balance_sheet()
        )
        type(mock_ticker).quarterly_cashflow = PropertyMock(
            return_value=_make_cashflow()
        )
        mock_yf.Ticker.return_value = mock_ticker

        fetcher = YFinanceFinancialFetcher()
        df = fetcher.fetch("AAPL", "2024-01-01", "2024-12-31")

        assert df["publish_date"].isna().all()

    @patch("oxq.data.factors.yfinance", create=True)
    def test_fetch_annual(self, mock_yf):
        # Annual data uses financials/balance_sheet/cashflow (no quarterly_ prefix)
        annual_financials = pd.DataFrame(
            {
                pd.Timestamp("2024-12-31"): [22.50, 1.44e11, 8.60e10],
            },
            index=["Basic EPS", "Total Revenue", "Net Income"],
        )
        annual_balance = pd.DataFrame(
            {
                pd.Timestamp("2024-12-31"): [1.41e12, 2.73e11, 6.16e10],
            },
            index=["Total Assets", "Stockholders Equity", "Ordinary Shares Number"],
        )
        annual_cashflow = pd.DataFrame(
            {
                pd.Timestamp("2024-12-31"): [1.15e11],
            },
            index=["Operating Cash Flow"],
        )

        mock_ticker = MagicMock()
        type(mock_ticker).financials = PropertyMock(return_value=annual_financials)
        type(mock_ticker).balance_sheet = PropertyMock(return_value=annual_balance)
        type(mock_ticker).cashflow = PropertyMock(return_value=annual_cashflow)
        mock_yf.Ticker.return_value = mock_ticker

        fetcher = YFinanceFinancialFetcher()
        df = fetcher.fetch("AAPL", "2024-01-01", "2024-12-31", period="annual")

        assert len(df) == 1
        assert all(df["period"] == "annual")
