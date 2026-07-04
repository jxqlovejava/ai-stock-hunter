"""Factor data: download from various sources and read locally."""

from __future__ import annotations

import importlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

from oxq.core.errors import DownloadError

# Human-readable name → World Bank indicator code
MACRO_INDICATOR_MAP: dict[str, str] = {
    "gdp": "NY.GDP.MKTP.CD",  # GDP (current USD)
    "gdp_per_capita": "NY.GDP.PCAP.CD",  # GDP per capita (current USD)
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "cpi": "FP.CPI.TOTL.ZG",  # CPI inflation (annual %)
}

# Backward-compatible alias
INDICATOR_MAP = MACRO_INDICATOR_MAP

FINANCIAL_INDICATORS: list[str] = [
    "total_shares",
    "eps",
    "book_value_per_share",
    "net_income",
    "operating_cash_flow",
    "total_assets",
    "revenue",
    "roe",
    "pe_ttm",
    "pb",
    "roa",
    "peg",
]


def resolve_factor_dir(dest_dir: Path | None = None, sub: str | None = None) -> Path:
    """Resolve factor data directory.

    Priority: parameter > $OXQ_DATA_DIR/factor > ~/.oxq/data/factor.

    Parameters
    ----------
    dest_dir : Path | None
        Explicit base directory.
    sub : str | None
        Subdirectory name (e.g. "macro", "financial"). Appended when provided.
    """
    if dest_dir is not None:
        base = dest_dir
    else:
        env = os.environ.get("OXQ_DATA_DIR")
        if env:
            base = Path(env) / "factor"
        else:
            base = Path.home() / ".oxq" / "data" / "factor"

    if sub is not None:
        return base / sub
    return base


def _fetch_world_bank(
    indicator_code: str,
    countries: list[str],
    start_year: int,
    end_year: int,
    timeout: int = 60,
    retries: int = 3,
) -> list[dict[str, Any]]:
    """Fetch data from World Bank API v2. Returns raw JSON records."""
    import time

    country_str = ";".join(countries)
    url = (
        f"https://api.worldbank.org/v2/country/{country_str}"
        f"/indicator/{indicator_code}"
        f"?date={start_year}:{end_year}&format=json&per_page=10000"
    )
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                body = json.loads(resp.read().decode())
            # World Bank returns [metadata, data] — data is the second element
            if not isinstance(body, list) or len(body) < 2 or body[1] is None:
                return []
            result: list[dict[str, Any]] = body[1]
            return result
        except (TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert World Bank JSON records to a DataFrame (index=year, cols=countries)."""
    rows: dict[int, dict[str, float | None]] = {}
    for rec in records:
        year = int(rec["date"])
        country = rec["countryiso3code"]
        value = rec["value"]
        if year not in rows:
            rows[year] = {}
        rows[year][country] = float(value) if value is not None else None

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "year"
    df = df.sort_index()
    # Reorder columns alphabetically for consistency
    df = df.reindex(sorted(df.columns), axis=1)
    return df


class WorldBankFetcher:
    """Fetch macro indicators from World Bank Open Data API.

    Implements the ``FactorFetcher`` protocol.
    """

    def fetch(
        self,
        target: str,
        start: str,
        end: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch indicator data from World Bank.

        Parameters
        ----------
        target : str
            Human-readable indicator name (e.g. "gdp", "cpi").
        start : str
            Start year (inclusive), e.g. "2020".
        end : str
            End year (inclusive), e.g. "2024".
        **kwargs
            countries : list[str] — ISO 3166-1 alpha-3 codes (required).

        Returns
        -------
        pd.DataFrame
            DataFrame with index=year (int), columns=country codes.
        """
        if target not in MACRO_INDICATOR_MAP:
            msg = (
                f"Unknown indicator '{target}'. "
                f"Available: {sorted(MACRO_INDICATOR_MAP)}"
            )
            raise ValueError(msg)

        countries: list[str] = kwargs.get("countries", [])
        indicator_code = MACRO_INDICATOR_MAP[target]

        try:
            records = _fetch_world_bank(
                indicator_code, countries, int(start), int(end)
            )
        except Exception as exc:
            msg = f"Failed to download '{target}' from World Bank: {exc}"
            raise DownloadError(msg) from exc

        if not records:
            msg = (
                f"No data returned for '{target}' "
                f"(countries={countries}, {start}-{end})."
            )
            raise DownloadError(msg)

        return _records_to_dataframe(records)

    def list_indicators(self) -> list[str]:
        """Return sorted list of available indicator names."""
        return sorted(MACRO_INDICATOR_MAP)


# Backward-compatible alias
WorldBankDownloader = WorldBankFetcher

# Mapping: indicator name -> chinese metric label in stock_financial_abstract
# None = computed from other metrics
EASTMONEY_FIELD_MAP: dict[str, str | None] = {
    "eps": "基本每股收益",
    "revenue": "营业总收入",
    "net_income": "净利润",
    "roe": "净资产收益率(ROE)",
    "book_value_per_share": "每股净资产",
    "operating_cash_flow": "经营现金流量净额",
    "total_assets": None,  # computed: equity * equity_multiplier
    "total_shares": None,  # computed: equity / bvps
    "pe_ttm": "市盈率(TTM)",
    "pb": "市净率(PB)",
    "roa": "总资产收益率(ROA)",
    "peg": None,  # computed: pe_ttm / (net_income_growth * 100)
}

# Extra metrics needed for computed indicators
_EASTMONEY_EXTRA_METRICS: list[str] = [
    "股东权益合计(净资产)",
    "权益乘数",
    "净利润同比增长率",
]


class EastMoneyFetcher:
    """Fetch A-share financial statement data via akshare (EastMoney source).

    Uses ``stock_financial_abstract`` (per-symbol, pivot table with metrics
    as rows and report periods as columns).  All 8 indicators come from this
    single API call — no notebook-incompatible tqdm widgets.

    Implements the ``FactorFetcher`` protocol.
    """

    def fetch(
        self,
        target: str,
        start: str,
        end: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch financial statement data for an A-share stock.

        Parameters
        ----------
        target : str
            Stock symbol (e.g. "600519").
        start : str
            Start date (inclusive), e.g. "2024-01-01".
        end : str
            End date (inclusive), e.g. "2024-12-31".
        **kwargs
            indicators : list[str] | None — specific indicators to fetch.
            period : str — "quarterly" (default) or "annual".
        """
        ak = globals().get("akshare") or importlib.import_module("akshare")

        requested: list[str] | None = kwargs.get("indicators")
        period: str = kwargs.get("period", "quarterly")
        wanted = set(requested) if requested else set(EASTMONEY_FIELD_MAP)

        # Fetch the pivot table: rows = metrics, columns = report periods
        abstract_df = ak.stock_financial_abstract(symbol=target)
        date_cols = [c for c in abstract_df.columns if c not in ("选项", "指标")]

        # Collect all needed metric labels (direct + extra for computed)
        all_labels: set[str] = set()
        for ind in wanted:
            if ind not in EASTMONEY_FIELD_MAP:
                continue
            label = EASTMONEY_FIELD_MAP[ind]
            if label is not None:
                all_labels.add(label)
        need_computed = bool(wanted & {"total_assets", "total_shares", "peg"})
        if need_computed:
            all_labels.update(_EASTMONEY_EXTRA_METRICS)
            all_labels.add("每股净资产")  # needed for total_shares

        # Build a lookup: label -> row values
        label_data: dict[str, pd.Series] = {}
        for label in all_labels:
            match = abstract_df[abstract_df["指标"] == label]
            if not match.empty:
                label_data[label] = match.iloc[0]

        # Build result rows per date
        result_rows: dict[pd.Timestamp, dict[str, Any]] = {}
        for date_str in date_cols:
            dt = pd.Timestamp(date_str)
            if dt < pd.Timestamp(start) or dt > pd.Timestamp(end):
                continue

            row: dict[str, Any] = {"publish_date": pd.NaT}

            # Direct-mapped indicators
            for ind in wanted:
                if ind not in EASTMONEY_FIELD_MAP:
                    continue
                label = EASTMONEY_FIELD_MAP[ind]
                if label is None:
                    continue
                if label in label_data:
                    val = label_data[label].get(date_str)
                    row[ind] = float(val) if pd.notna(val) else None
                else:
                    row[ind] = None

            # Computed: total_assets = equity * equity_multiplier
            if "total_assets" in wanted:
                equity_s = label_data.get("股东权益合计(净资产)")
                mult_s = label_data.get("权益乘数")
                if equity_s is not None and mult_s is not None:
                    eq = equity_s.get(date_str)
                    mu = mult_s.get(date_str)
                    if pd.notna(eq) and pd.notna(mu):
                        row["total_assets"] = float(eq) * float(mu)
                    else:
                        row["total_assets"] = None
                else:
                    row["total_assets"] = None

            # Computed: total_shares = equity / bvps
            if "total_shares" in wanted:
                equity_s = label_data.get("股东权益合计(净资产)")
                bvps_s = label_data.get("每股净资产")
                if equity_s is not None and bvps_s is not None:
                    eq = equity_s.get(date_str)
                    bv = bvps_s.get(date_str)
                    if pd.notna(eq) and pd.notna(bv) and float(bv) != 0:
                        row["total_shares"] = float(eq) / float(bv)
                    else:
                        row["total_shares"] = None
                else:
                    row["total_shares"] = None

            # Computed: peg = pe_ttm / net_income_growth_rate
            if "peg" in wanted:
                pe_val = row.get("pe_ttm")
                growth_s = label_data.get("净利润同比增长率")
                if pe_val is not None and growth_s is not None:
                    g = growth_s.get(date_str)
                    if pd.notna(pe_val) and pd.notna(g) and float(g) != 0:
                        row["peg"] = float(pe_val) / float(g)
                    else:
                        row["peg"] = None
                else:
                    row["peg"] = None

            result_rows[dt] = row

        if not result_rows:
            msg = f"No data returned for '{target}' ({start}-{end})."
            raise DownloadError(msg)

        # Build DataFrame
        df = pd.DataFrame.from_dict(result_rows, orient="index")
        df.index.name = "report_date"
        df = df.sort_index()

        # Add period column
        df["period"] = df.index.month.map(lambda m: "annual" if m == 12 else "quarterly")

        # Filter by period
        if period == "annual":
            df = df[df["period"] == "annual"]
        elif period == "quarterly":
            df = df[df["period"] == "quarterly"]

        return df

    def list_indicators(self) -> list[str]:
        """Return sorted list of available indicator names."""
        return sorted(EASTMONEY_FIELD_MAP)


# indicator -> (report_property, field_name) or None (computed)
YFINANCE_FIELD_MAP: dict[str, tuple[str, str] | None] = {
    "eps": ("financials", "Basic EPS"),
    "revenue": ("financials", "Total Revenue"),
    "net_income": ("financials", "Net Income"),
    "roe": None,  # computed: net_income / equity
    "total_assets": ("balance_sheet", "Total Assets"),
    "book_value_per_share": None,  # computed: equity / shares
    "operating_cash_flow": ("cashflow", "Operating Cash Flow"),
    "total_shares": ("balance_sheet", "Ordinary Shares Number"),
}

# Fields needed for computed indicators
_YFINANCE_EXTRA_FIELDS: dict[str, list[tuple[str, str]]] = {
    "roe": [("financials", "Net Income"), ("balance_sheet", "Stockholders Equity")],
    "book_value_per_share": [
        ("balance_sheet", "Stockholders Equity"),
        ("balance_sheet", "Ordinary Shares Number"),
    ],
}


class YFinanceFinancialFetcher:
    """Fetch US stock financial data via yfinance.

    Implements the ``FactorFetcher`` protocol.
    """

    def fetch(
        self,
        target: str,
        start: str,
        end: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch financial statement data for a US stock.

        Parameters
        ----------
        target : str
            Ticker symbol (e.g. "AAPL").
        start : str
            Start date (inclusive), e.g. "2024-01-01".
        end : str
            End date (inclusive), e.g. "2024-12-31".
        **kwargs
            period : str — "quarterly" (default) or "annual".
        """
        yf = globals().get("yfinance") or importlib.import_module("yfinance")

        period: str = kwargs.get("period", "quarterly")
        ticker = yf.Ticker(target)

        # Choose quarterly or annual properties
        if period == "annual":
            reports = {
                "financials": ticker.financials,
                "balance_sheet": ticker.balance_sheet,
                "cashflow": ticker.cashflow,
            }
        else:
            reports = {
                "financials": ticker.quarterly_financials,
                "balance_sheet": ticker.quarterly_balance_sheet,
                "cashflow": ticker.quarterly_cashflow,
            }

        # Collect all needed (report, field) pairs
        needed: set[tuple[str, str]] = set()
        for ind, mapping in YFINANCE_FIELD_MAP.items():
            if mapping is not None:
                needed.add(mapping)
            else:
                for pair in _YFINANCE_EXTRA_FIELDS[ind]:
                    needed.add(pair)

        # Gather all report dates from all reports
        all_dates: set[pd.Timestamp] = set()
        for report_key, report_df in reports.items():
            if report_df is not None and not report_df.empty:
                all_dates.update(report_df.columns)

        # Build rows for each report date
        rows: list[dict[str, Any]] = []
        for dt in sorted(all_dates):
            row: dict[str, Any] = {"report_date": dt, "publish_date": pd.NaT}

            # Determine period label
            if period == "annual":
                row["period"] = "annual"
            else:
                row["period"] = "annual" if dt.month == 12 else "quarterly"

            # Extract raw values from reports
            raw: dict[tuple[str, str], float | None] = {}
            for report_key, field_name in needed:
                report_df = reports.get(report_key)
                if (
                    report_df is not None
                    and not report_df.empty
                    and field_name in report_df.index
                    and dt in report_df.columns
                ):
                    raw[(report_key, field_name)] = float(report_df.loc[field_name, dt])
                else:
                    raw[(report_key, field_name)] = None

            # Fill direct-mapped indicators
            for ind, mapping in YFINANCE_FIELD_MAP.items():
                if mapping is not None:
                    row[ind] = raw.get(mapping)

            # Compute derived indicators
            net_income = raw.get(("financials", "Net Income"))
            equity = raw.get(("balance_sheet", "Stockholders Equity"))
            shares = raw.get(("balance_sheet", "Ordinary Shares Number"))

            if net_income is not None and equity and equity != 0:
                row["roe"] = net_income / equity
            else:
                row["roe"] = None

            if equity is not None and shares and shares != 0:
                row["book_value_per_share"] = equity / shares
            else:
                row["book_value_per_share"] = None

            rows.append(row)

        if not rows:
            msg = f"No data returned for '{target}' ({start}-{end})."
            raise DownloadError(msg)

        df = pd.DataFrame(rows)
        df["report_date"] = pd.to_datetime(df["report_date"])

        # Filter by date range
        df = df[
            (df["report_date"] >= pd.Timestamp(start))
            & (df["report_date"] <= pd.Timestamp(end))
        ]

        df = df.set_index("report_date").sort_index()
        return df

    def list_indicators(self) -> list[str]:
        """Return sorted list of available indicator names."""
        return sorted(YFINANCE_FIELD_MAP)


class FactorDownloader:
    """Download factor data via a FactorFetcher and persist locally.

    Parameters
    ----------
    fetcher : FactorFetcher
        Data source to fetch from.
    sub : str
        Subdirectory name (e.g. "macro", "financial").
    """

    def __init__(self, fetcher: Any, sub: str) -> None:
        self.fetcher = fetcher
        self.sub = sub

    def download(
        self,
        target: str,
        start: str,
        end: str,
        dest_dir: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Fetch data and save as parquet.

        If a file already exists, merges new data with existing
        (concat + drop_duplicates on index keeping last + sort_index).

        Returns
        -------
        Path
            Path to the saved parquet file.
        """
        df = self.fetcher.fetch(target, start, end, **kwargs)

        factor_dir = resolve_factor_dir(dest_dir, sub=self.sub)
        factor_dir.mkdir(parents=True, exist_ok=True)
        path = factor_dir / f"{target}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df])
            df = df[~df.index.duplicated(keep="last")]
            df = df.sort_index()

        df.to_parquet(path)
        return path

    def download_many(
        self,
        targets: list[str],
        start: str,
        end: str,
        dest_dir: Path | None = None,
        **kwargs: Any,
    ) -> dict[str, Path]:
        """Download multiple targets. Returns {target: path}."""
        result: dict[str, Path] = {}
        for target in targets:
            result[target] = self.download(target, start, end, dest_dir=dest_dir, **kwargs)
        return result

    def list_available(self) -> list[str]:
        """Delegate to fetcher's list_indicators."""
        return self.fetcher.list_indicators()


def read_factor(
    target: str,
    countries: list[str] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    data_dir: Path | None = None,
    sub: str = "macro",
    indicators: list[str] | None = None,
    point_in_time: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Read local factor data.

    Parameters
    ----------
    target : str
        Factor name (e.g. "gdp") or stock symbol (e.g. "600519").
    countries : list[str] | None
        Filter to these countries. None returns all available.
    start_year : int | None
        Filter start year (inclusive). Legacy param for macro data.
    end_year : int | None
        Filter end year (inclusive). Legacy param for macro data.
    data_dir : Path | None
        Override factor data directory.
    sub : str
        Subdirectory name (default "macro").
    indicators : list[str] | None
        Filter to these columns. Metadata columns (publish_date, period)
        are kept automatically when present.
    point_in_time : bool
        When True, filter by publish_date instead of report_date/index.
        Useful for avoiding look-ahead bias with financial data.
    start : str | None
        Start date string (inclusive), e.g. "2024-01-01".
    end : str | None
        End date string (inclusive), e.g. "2024-06-30".
        When ``point_in_time=True``, filters rows where
        ``publish_date <= end``.

    Returns
    -------
    pd.DataFrame
        DataFrame with factor data.
    """
    factor_dir = resolve_factor_dir(data_dir, sub=sub)
    path = factor_dir / f"{target}.parquet"
    if not path.exists():
        msg = f"Factor file not found: {path}"
        raise FileNotFoundError(msg)

    df = pd.read_parquet(path)

    if indicators is not None:
        metadata_cols = ["publish_date", "period"]
        keep = [c for c in indicators if c in df.columns]
        keep += [c for c in metadata_cols if c in df.columns and c not in keep]
        df = df[keep]

    # Date-based filtering (start/end strings)
    if point_in_time and "publish_date" in df.columns:
        if start is not None:
            df = df[df["publish_date"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["publish_date"] <= pd.Timestamp(end)]
    elif start is not None or end is not None:
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]

    # Legacy year-based filtering (start_year/end_year ints)
    if start_year is not None:
        df = df[df.index >= start_year]
    if end_year is not None:
        df = df[df.index <= end_year]

    if countries is not None:
        available = [c for c in countries if c in df.columns]
        df = df[available]

    return df
