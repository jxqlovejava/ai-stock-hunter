# -*- coding: utf-8 -*-
"""AKShare 数据适配器。

封装 AKShare Python 库，提供:
  - 全市场股票列表 + 实时行情
  - 历史 K 线
  - 龙虎榜、融资融券、北向资金（独有数据）
  - 财务数据

注意: AKShare 依赖外部数据源，在受限网络环境下可能超时。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

from .base import DataProvider
from .schema import Financials, Quote


def _to_tx_symbol(symbol: str) -> str:
    """将纯数字代码转为腾讯格式（带市场前缀 sz/sh/bj）。"""
    if not symbol or len(symbol) < 6:
        return symbol
    # 已有前缀
    if symbol.startswith(("sz", "sh", "bj")):
        return symbol
    code = symbol[-6:] if len(symbol) > 6 else symbol
    first = code[0]
    if first in ("0", "2", "3"):
        return f"sz{code}"
    elif first in ("6", "9"):
        return f"sh{code}"
    elif first in ("4", "8"):
        return f"bj{code}"
    return f"sz{code}"  # 默认深交所


class AKShareProvider(DataProvider):
    """AKShare 数据适配器。"""

    source_name = "akshare"
    TIMEOUT = 60

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情（从全市场数据中查找）。"""
        try:
            df = self._get_spot()
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return Quote(
                symbol=symbol,
                name=str(r.get("名称", "")),
                price=float(r["最新价"]) if self._valid(r.get("最新价")) else 0.0,
                change_pct=float(r["涨跌幅"])
                if self._valid(r.get("涨跌幅"))
                else 0.0,
                volume=int(float(r.get("成交量", 0)))
                if self._valid(r.get("成交量"))
                else 0,
                turnover=float(r.get("成交额", 0))
                if self._valid(r.get("成交额"))
                else 0.0,
                high=float(r["最高"]) if self._valid(r.get("最高")) else None,
                low=float(r["最低"]) if self._valid(r.get("最低")) else None,
                open=float(r["今开"]) if self._valid(r.get("今开")) else None,
                prev_close=float(r["昨收"]) if self._valid(r.get("昨收")) else None,
                # 估值字段 — AKShare spot 数据包含市盈率/市净率/总市值
                pe_ttm=float(r["市盈率-动态"]) if self._valid(r.get("市盈率-动态")) else None,
                pb=float(r["市净率"]) if self._valid(r.get("市净率")) else None,
                market_cap=float(r["总市值"]) if self._valid(r.get("总市值")) else None,
                source=self.source_name,
            )
        except Exception:
            return None

    def get_all_quotes(self) -> list[Quote]:
        """获取全 A 股实时行情列表。"""
        try:
            df = self._get_spot()
            results = []
            for _, r in df.iterrows():
                try:
                    results.append(
                        Quote(
                            symbol=str(r.get("代码", "")),
                            name=str(r.get("名称", "")),
                            price=float(r["最新价"])
                            if self._valid(r.get("最新价"))
                            else 0.0,
                            change_pct=float(r["涨跌幅"])
                            if self._valid(r.get("涨跌幅"))
                            else 0.0,
                            volume=int(float(r.get("成交量", 0)))
                            if self._valid(r.get("成交量"))
                            else 0,
                            turnover=float(r.get("成交额", 0))
                            if self._valid(r.get("成交额"))
                            else 0.0,
                            # 估值字段 — AKShare spot 数据包含市盈率/市净率/总市值
                            pe_ttm=float(r["市盈率-动态"]) if self._valid(r.get("市盈率-动态")) else None,
                            pb=float(r["市净率"]) if self._valid(r.get("市净率")) else None,
                            market_cap=float(r["总市值"]) if self._valid(r.get("总市值")) else None,
                            source=self.source_name,
                        )
                    )
                except Exception:
                    continue
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Financials
    # ------------------------------------------------------------------

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4,
        report_period: str = "",
    ) -> list[Financials]:
        """获取最近 N 期财务数据。

        使用同花顺财务摘要 (stock_financial_abstract_ths)，
        字段: 报告期/净利润/营业总收入/净资产收益率/每股经营现金流 等。
        资产负债表数据通过 stock_balance_sheet_by_report_ths 补充。

        report_period: 历史回测报告期 (YYYY-MM-DD)，只返回 ≤ 该日期的报告期数据。
                       例如 "2025-09-01" → 只返回 2025-06-30 及之前的报告期。
        """
        try:
            # 主表: 利润表 + 部分资产负债表指标
            df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
            if df is None or df.empty:
                return []
            # 尝试补充资产负债表
            bs_data = {}
            try:
                bs_df = ak.stock_balance_sheet_by_report_ths(symbol=symbol)
                if bs_df is not None and not bs_df.empty:
                    for _, row in bs_df.iterrows():
                        period = str(row.get("报告期", ""))
                        bs_data[period] = row
            except Exception:
                pass

            results = []
            # 如果有 report_period 过滤，只保留 ≤ 该日期的报告期
            report_cutoff = None
            if report_period:
                try:
                    from datetime import datetime as _dt
                    report_cutoff = _dt.strptime(report_period, "%Y-%m-%d")
                except ValueError:
                    pass

            for _, r in df.tail(count).iterrows():
                try:
                    period = str(r.get("报告期", ""))
                    # 历史回测: 跳过晚于 as_of 的报告期
                    if report_cutoff:
                        try:
                            pdt = _dt.strptime(period, "%Y-%m-%d")
                            if pdt > report_cutoff:
                                continue
                        except ValueError:
                            pass
                    bs = bs_data.get(period, {})
                    # 计算 EPS = 净利润 / 总股本
                    total_shares_val = self._safe_float(r.get("总股本") or bs.get("总股本"))
                    np_val = self._safe_float(r.get("归母净利润") or r.get("净利润")) or 0.0
                    eps = round(np_val / total_shares_val, 4) if (total_shares_val and total_shares_val > 0) else None

                    results.append(
                        Financials(
                            symbol=symbol,
                            report_period=period,
                            revenue=self._safe_float(r.get("营业总收入")),
                            net_profit=np_val,
                            total_assets=self._safe_float(
                                bs.get("资产总计") or r.get("资产总计")
                            ),
                            total_liabilities=self._safe_float(
                                bs.get("负债合计") or r.get("负债合计")
                            ),
                            operating_cash_flow=self._safe_float(
                                r.get("每股经营现金流")
                            ),
                            roe=self._safe_float(r.get("净资产收益率")),  # 同花顺直接提供 ROE
                            eps=eps,
                            source=self.source_name,
                        )
                    )
                except Exception:
                    continue
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Historical K-line
    # ------------------------------------------------------------------

    def get_history(
        self, symbol: str, period: str = "daily", start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        """获取历史 K 线（腾讯源，push2.eastmoney.com 不可用时降级）。

        注意：stock_zh_a_hist (东财 push2) 在部分网络环境被阻断，
        改用 stock_zh_a_hist_tx (腾讯) 作为 AKShare 的 K 线数据源。
        """
        try:
            # 优先尝试东财源（数据更全），失败则降级到腾讯源
            try:
                return ak.stock_zh_a_hist(
                    symbol=symbol, period=period,
                    start_date=start_date, end_date=end_date,
                )
            except Exception:
                pass
            # 降级：腾讯源 — symbol 需要市场前缀
            tx_symbol = _to_tx_symbol(symbol)
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_symbol, start_date=start_date, end_date=end_date,
            )
            # 腾讯源列名: date/open/close/high/low/amount → 统一为 volume
            if "amount" in df.columns:
                df = df.rename(columns={"amount": "volume"})
            return df
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Unique data (no Guosen equivalent)
    # ------------------------------------------------------------------

    def get_dragon_tiger(self) -> pd.DataFrame:
        """获取今日龙虎榜数据（独有）。"""
        try:
            today = datetime.now().strftime("%Y%m%d")
            return ak.stock_lhb_detail_em(start_date=today, end_date=today)
        except Exception:
            return pd.DataFrame()

    def get_margin_trading(self) -> pd.DataFrame:
        """获取融资融券数据（独有）。"""
        try:
            return ak.stock_margin_detail_sse(date=datetime.now().strftime("%Y%m%d"))
        except Exception:
            return pd.DataFrame()

    def get_northbound_flow(self) -> pd.DataFrame:
        """获取北向资金流向。"""
        try:
            return ak.stock_hsgt_fund_flow_summary_em()
        except Exception:
            return pd.DataFrame()

    def get_sector_capital_flow(self) -> pd.DataFrame:
        """获取行业板块资金流向。"""
        try:
            return ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流向")
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """测试连通性。"""
        try:
            df = ak.stock_zh_a_spot()
            return df is not None and len(df) > 1000
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _spot_cache: pd.DataFrame | None = None
    _spot_cache_time: datetime | None = None

    def _get_spot(self) -> pd.DataFrame:
        """获取全市场行情（5 分钟缓存）。"""
        now = datetime.now()
        if (
            self._spot_cache is not None
            and self._spot_cache_time is not None
            and (now - self._spot_cache_time).seconds < 300
        ):
            return self._spot_cache
        self._spot_cache = ak.stock_zh_a_spot()
        self._spot_cache_time = now
        return self._spot_cache

    @staticmethod
    def _valid(val) -> bool:
        return val is not None and str(val) not in ("-", "", "nan", "None")

    @staticmethod
    def _safe_float(val) -> float | None:
        """安全转 float，支持中文单位（亿/万/%）。"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            if val != val:  # NaN
                return None
            return float(val)
        s = str(val).replace(",", "").replace("%", "").strip()
        if not s or s in ("False", "None", "--", "nan", ""):
            return None
        multiplier = 1.0
        if "亿" in s:
            s = s.replace("亿", "")
            multiplier = 100_000_000
        elif "万" in s:
            s = s.replace("万", "")
            multiplier = 10_000
        try:
            return float(s) * multiplier
        except (ValueError, TypeError):
            return None
