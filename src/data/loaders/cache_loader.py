# -*- coding: utf-8 -*-
"""已核实缓存 Loader。

从 data/kline_cache 读取本地 CSV，作为最高优先级数据源。
缓存文件名格式: {code}_{start}_{end}_daily.csv
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src.data.loaders.base import DataLoader
from src.data.loaders.registry import register
from src.data.schema import Quote


@register
class VerifiedCacheLoader(DataLoader):
    """已核实本地缓存 Loader。"""

    name = "verified_cache"
    markets = ["a_share"]

    def __init__(self, cache_dir: str | Path | None = None):
        if cache_dir is None:
            self._cache_dir = Path(__file__).resolve().parents[4] / "data" / "kline_cache"
        else:
            self._cache_dir = Path(cache_dir)

    def is_available(self) -> bool:
        return self._cache_dir.exists()

    def _find_file(self, symbol: str, start_date: str, end_date: str) -> Optional[Path]:
        """按文件名模式匹配缓存文件。"""
        if not self._cache_dir.exists():
            return None
        # 支持 start/end 带 '-' 或纯数字
        start_norm = start_date.replace("-", "")
        end_norm = end_date.replace("-", "")
        pattern = f"{symbol}_{start_norm}_{end_norm}_daily.csv"
        candidate = self._cache_dir / pattern
        if candidate.exists():
            return candidate
        # 模糊匹配：只看 code 前缀
        for f in self._cache_dir.glob(f"{symbol}_*_daily.csv"):
            return f
        return None

    def get_history(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        period: str = "daily",
    ) -> pd.DataFrame:
        if period != "daily":
            return pd.DataFrame()
        path = self._find_file(symbol, start_date, end_date)
        if path is None:
            return pd.DataFrame()
        try:
            df = pd.read_csv(path)
            # 尝试识别日期列
            date_col = None
            for col in ["日期", "date", "trade_date", "datetime"]:
                if col in df.columns:
                    date_col = col
                    break
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col])
            # 附加来源引用
            from src.data.source_citation import make_citation
            citation = make_citation(
                provider="verified_cache",
                field="ohlcv",
                data_type="daily_bar",
                is_cached=True,
                source_tier="T1",
                nature="fact",
            )
            df.attrs["source_citation"] = citation
            return df
        except Exception:
            return pd.DataFrame()

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """从缓存最新一行构造 Quote。"""
        df = self.get_history(symbol)
        if df.empty:
            return None
        last = df.iloc[-1]
        price = float(last.get("收盘", last.get("close", 0)))
        if price == 0:
            return None
        change_pct = float(last.get("涨跌幅", 0))
        volume = int(float(last.get("成交量", 0)))
        turnover = float(last.get("成交额", 0))
        high = float(last.get("最高", last.get("high", 0))) or None
        low = float(last.get("最低", last.get("low", 0))) or None
        open_ = float(last.get("开盘", last.get("open", 0))) or None
        prev_close = float(last.get("昨收", last.get("pre_close", 0))) or None
        return Quote(
            symbol=symbol,
            name=symbol,
            price=price,
            change_pct=change_pct,
            volume=volume,
            turnover=turnover,
            high=high,
            low=low,
            open=open_,
            prev_close=prev_close,
            source="verified_cache",
        )
