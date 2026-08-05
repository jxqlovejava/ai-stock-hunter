# -*- coding: utf-8 -*-
"""期货现货价格领先信号源 — 为跨市场传导 lead-lag 管道注入"上游现货异动"。

数据源: AKShare ``futures_spot_price_daily``（生意社 100ppi 大宗商品现货价格 + 基差）。
  - 返回按 (date, symbol) 一行的现货价格，覆盖铜/铝/锂/金/银/工业硅 等国内期货品种。
  - 计算最近两个交易日的现货涨跌幅，超过 threshold 才产出信号。

设计原则（对齐 LeadSignalSource 可插拔接口）:
  - ``fetch()`` 返回 ``list[LeadSourceSignal]``；任何失败返回 ``[]``（优雅降级），
    绝不抛异常阻塞 lead-lag 管道。
  - 数据不可用时调用方自动回退到 ``SECTOR_MAP`` 配置驱动路径（现状行为不变）。
  - 现货异动一律标 ``[SPECULATION]`` 弱信号（上游→A股对标 2-4 周，doc 04 可信度 0.3 理念）。
  - 结果带 TTL 缓存，避免重复请求 100ppi。

使用:
    from src.data.commodity.futures_spot_source import FuturesSpotLeadSource
    src = FuturesSpotLeadSource(threshold_pct=2.0)
    signals = src.fetch()   # [LeadSourceSignal(category="commodity.CU", change_pct=...), ...]
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from src.data.us_sector_transmission import LeadSignalSource, LeadSourceSignal

logger = logging.getLogger(__name__)

# ── 品种元数据: symbol → 显示名 + 影响的 A 股板块 ────────────────────────
# sector 列表用于 LeadSignal.target_sectors，供 lead_signal_weak_adjust 匹配。
FUTURES_META: dict[str, dict] = {
    "CU": {"name": "沪铜", "sectors": ("铜", "有色金属", "电缆")},
    "AL": {"name": "沪铝", "sectors": ("铝", "有色金属")},
    "ZN": {"name": "沪锌", "sectors": ("有色金属",)},
    "NI": {"name": "沪镍", "sectors": ("有色金属",)},
    "SN": {"name": "沪锡", "sectors": ("有色金属",)},
    "PB": {"name": "沪铅", "sectors": ("有色金属",)},
    "AU": {"name": "沪金", "sectors": ("黄金", "贵金属")},
    "AG": {"name": "沪银", "sectors": ("黄金", "贵金属")},
    "LC": {"name": "碳酸锂", "sectors": ("锂电", "新能源车")},
    "SI": {"name": "工业硅", "sectors": ("光伏", "有机硅")},
    "RU": {"name": "天然橡胶", "sectors": ("橡胶",)},
    "SS": {"name": "不锈钢", "sectors": ("钢铁",)},
}

# 默认现货涨跌幅阈值(%) — 低于此值的日常波动忽略，避免噪音信号
DEFAULT_THRESHOLD_PCT = 2.0

# 结果缓存 TTL — 现货价格日度更新，缓存 6 小时足够
_CACHE_TTL = timedelta(hours=6)


class FuturesSpotLeadSource(LeadSignalSource):
    """上游现货价格异动信号源（商品期货现货价，AKShare/生意社）。

    用法:
        src = FuturesSpotLeadSource()
        signals = src.fetch()          # 全部已映射品种
        signals = src.fetch("CU")      # 只看沪铜（支持 "commodity.CU" 或 "CU"）

    任何网络/解析失败返回 ``[]``，不抛异常。
    """

    name: str = "futures_spot"

    def __init__(
        self,
        threshold_pct: float = DEFAULT_THRESHOLD_PCT,
        lookback_days: int = 8,
    ):
        self.threshold_pct = threshold_pct
        self.lookback_days = lookback_days
        self._cache: Optional[tuple[datetime, list[LeadSourceSignal]]] = None

    # ── 公开 API ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """检测底层数据源是否可用（akshare 已安装即可视为可用，网络失败走降级）。"""
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    def fetch(self, category: str = "") -> list[LeadSourceSignal]:
        """获取最近两个交易日的现货价格异动信号。

        Args:
            category: 空=全部已映射品种；"CU" 或 "commodity.CU"=单品种。

        Returns:
            list[LeadSourceSignal]；失败/无可用数据返回 []。
        """
        want_symbol = self._parse_category(category)
        try:
            signals = self._fetch_all()
        except Exception as exc:
            logger.debug("FuturesSpotLeadSource.fetch failed (degrade): %s", exc)
            return []
        if want_symbol:
            return [s for s in signals if s.category == f"commodity.{want_symbol}"]
        return signals

    # ── 内部实现 ──────────────────────────────────────────────────────

    def _fetch_all(self) -> list[LeadSourceSignal]:
        """拉取并计算所有已映射品种的现货涨跌幅（带 TTL 缓存）。"""
        now = datetime.now()
        if self._cache is not None and (now - self._cache[0]) < _CACHE_TTL:
            return self._cache[1]

        df = self._fetch_spot_df()
        if df is None or df.empty:
            self._cache = (now, [])
            return []

        signals = self._compute_change_signals(df)
        self._cache = (now, signals)
        return signals

    def _fetch_spot_df(self):
        """调用 akshare 拉取近 N 天现货价格 DataFrame。失败返回 None。"""
        try:
            import akshare as ak
        except ImportError:
            logger.debug("akshare 未安装，FuturesSpotLeadSource 降级为空")
            return None

        end = date.today()
        start = end - timedelta(days=self.lookback_days)
        df = ak.futures_spot_price_daily(
            start_day=start.strftime("%Y%m%d"),
            end_day=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return None
        return df

    @staticmethod
    def _parse_category(category: str) -> str:
        """把 category 参数解析为品种 symbol；空返回 ""。"""
        c = (category or "").strip()
        if not c:
            return ""
        if c.startswith("commodity."):
            c = c.split(".", 1)[1]
        return c.upper()

    def _compute_change_signals(self, df) -> list[LeadSourceSignal]:
        """按品种计算最近两个交易日的现货涨跌幅，超过阈值才产出信号。"""
        import pandas as pd

        if "symbol" not in df.columns or "spot_price" not in df.columns or "date" not in df.columns:
            logger.debug("现货 DataFrame 缺关键列，跳过")
            return []

        df = df.copy()
        df["date_str"] = df["date"].astype(str)

        out: list[LeadSourceSignal] = []
        for symbol, meta in FUTURES_META.items():
            sub = df[df["symbol"].astype(str).str.upper() == symbol]
            if sub.empty:
                continue
            sub = sub.sort_values("date_str")
            # 最近两个交易日
            recent_dates = sorted(sub["date_str"].unique())[-2:]
            if len(recent_dates) < 2:
                continue  # 数据不足两个交易日 → 无涨跌幅
            prev = sub[sub["date_str"] == recent_dates[-2]]["spot_price"]
            cur = sub[sub["date_str"] == recent_dates[-1]]["spot_price"]
            if prev.empty or cur.empty:
                continue
            try:
                prev_p = float(prev.iloc[0])
                cur_p = float(cur.iloc[0])
            except (TypeError, ValueError):
                continue
            if not prev_p or prev_p <= 0:
                continue
            change_pct = round((cur_p - prev_p) / prev_p * 100.0, 2)
            if abs(change_pct) < self.threshold_pct:
                continue  # 日常波动，忽略

            try:
                as_of = datetime.strptime(recent_dates[-1], "%Y%m%d").date()
            except ValueError:
                as_of = None
            out.append(LeadSourceSignal(
                category=f"commodity.{symbol}",
                name=meta["name"],
                change_pct=change_pct,
                as_of=as_of,
                source="akshare_futures_spot",
                target_sectors=meta["sectors"],
                confidence=0.6,
            ))
        return out
