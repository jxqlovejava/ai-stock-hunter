# -*- coding: utf-8 -*-
"""AKShare 数据适配器。

封装 AKShare Python 库，提供:
  - 全市场股票列表 + 实时行情
  - 历史 K 线
  - 龙虎榜、融资融券、北向资金（独有数据）
  - 财务数据

网络环境适配:
  - 自动检测 macOS 系统代理（如 Clash），为东财域名添加绕过规则
  - 探测 push2.eastmoney.com CDN 连通性，不可用时自动降级到 mootdx/腾讯
  - datacenter.eastmoney.com & emweb.securities.eastmoney.com 绕过代理后通常可用
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 网络环境配置 — 模块加载时执行一次
# ---------------------------------------------------------------------------

# 东财相关域名（AKShare 重度依赖）
_EM_DOMAINS = (
    "eastmoney.com",
    "eastmoney.com.cn",
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
    "datacenter.eastmoney.com",
    "emweb.securities.eastmoney.com",
)


def _bypass_system_proxy() -> None:
    """绕过 macOS 系统代理对东财域名的拦截。

    macOS 系统代理（如 Clash @ 127.0.0.1:7897）会通过
    urllib.request.getproxies() 自动注入到 requests.Session。
    为东财域名设置 NO_PROXY 可让 AKShare 直连，避免 ProxyError。
    """
    existing = os.environ.get("NO_PROXY", "")
    em_pattern = ",".join(_EM_DOMAINS)
    if existing:
        os.environ["NO_PROXY"] = f"{existing},{em_pattern}"
    else:
        os.environ["NO_PROXY"] = em_pattern
    # macOS 的 urllib 也读取小写版本
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    logger.debug("NO_PROXY set for eastmoney domains: %s", em_pattern)


@contextmanager
def _em_no_proxy():
    """临时禁用 requests 代理，用于东财域名请求。

    部分环境系统代理（如本地 Clash）未运行时会导致 requests 直接连接失败。
    此上下文管理器把 requests.get 替换为 trust_env=False 的 Session.get，
    请求结束后自动恢复。
    """
    import requests

    original_get = requests.get
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    requests.get = session.get
    try:
        yield
    finally:
        requests.get = original_get


def _check_push2_connectivity(timeout: float = 8.0) -> bool:
    """探测 push2.eastmoney.com API 端点是否可达。

    发送实际 API 请求测试连通性（仅探测 root path 不足以判断 API 是否被 WAF 封堵）。
    使用独立 Session（trust_env=False）绕过代理，避免代理干扰探测结果。
    """
    try:
        import requests as _requests

        s = _requests.Session()
        s.proxies = {"http": None, "https": None}
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        r = s.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "1", "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2", "fid": "f12",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12",
            },
            timeout=timeout,
        )
        return r.status_code == 200 and len(r.text) > 10
    except Exception as e:
        logger.warning("push2.eastmoney.com API 连通性探测失败: %s", e)
        return False


# 模块加载时配置
_bypass_system_proxy()
_PUSH2_UNAVAILABLE: bool = not _check_push2_connectivity()

if _PUSH2_UNAVAILABLE:
    logger.warning(
        "⚠️  push2.eastmoney.com 不可达 — AKShare 实时行情/历史K线(东财源)将降级到 mootdx/腾讯"
    )

# 延迟导入 AKShare（在 _bypass_system_proxy 之后）
import akshare as ak  # noqa: E402

from .base import DataProvider  # noqa: E402
from .schema import Financials, Quote  # noqa: E402

# ---------------------------------------------------------------------------
# AKShare 猴子补丁 — 为 push2 不可达环境自动降级
# ---------------------------------------------------------------------------

if _PUSH2_UNAVAILABLE:
    _orig_stock_zh_a_hist = ak.stock_zh_a_hist

    def _patched_stock_zh_a_hist(
        symbol: str = "000001",
        period: str = "daily",
        start_date: str = "19700101",
        end_date: str = "20500101",
        adjust: str = "",
        timeout: float | None = None,
    ) -> pd.DataFrame:
        """stock_zh_a_hist 的降级包装 — push2 不可达时自动走腾讯源。

        AKShare 原版走 push2his.eastmoney.com，该 CDN 在部分网络环境被 WAF 封堵。
        此补丁在原调用失败后自动降级到 stock_zh_a_hist_tx（腾讯源）。
        """
        # push2 不可达时直接走腾讯源，避免超时
        try:
            tx_symbol = _to_tx_symbol(symbol)
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_symbol, start_date=start_date, end_date=end_date,
            )
            # 统一列名：amount → volume
            if "amount" in df.columns:
                df = df.rename(columns={"amount": "volume"})
            return df
        except Exception:
            logger.debug("stock_zh_a_hist_tx also failed for %s", symbol, exc_info=True)
            return pd.DataFrame()

    ak.stock_zh_a_hist = _patched_stock_zh_a_hist
    logger.info("akshare.stock_zh_a_hist 已打补丁 → 自动降级到腾讯源")


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
        """获取单只股票实时行情（从全市场数据中查找）。

        支持带前缀 (sh600000) 和不带前缀 (600000) 两种代码格式。
        """
        try:
            df = self._get_spot()
            # 先精确匹配；失败则尝试加前缀匹配
            row = df[df["代码"] == symbol]
            if row.empty:
                # 尝试 AKShare 格式: 纯数字 → sh/sz/bj 前缀
                for prefix in ("sh", "sz", "bj"):
                    prefixed = prefix + symbol.strip().lower()
                    row = df[df["代码"] == prefixed]
                    if not row.empty:
                        break
            if row.empty:
                return None
            r = row.iloc[0]
            raw_symbol = str(r.get("代码", ""))
            raw_name = str(r.get("名称", ""))
            # 检测 ST
            is_st = None
            if raw_name:
                if "*ST" in raw_name or "＊ST" in raw_name:
                    is_st = True
                elif raw_name.startswith("ST"):
                    is_st = True
            return Quote(
                symbol=self._normalize_symbol(raw_symbol),
                name=raw_name,
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
                pe_ttm=None,
                pb=None,
                market_cap=None,
                is_st=is_st,
                source=self.source_name,
            )
        except Exception:
            return None

    def get_all_quotes(self) -> list[Quote]:
        """获取全 A 股实时行情列表。

        降级链: AKShare stock_zh_a_spot → 东财 push2 直连 HTTP。
        东财直连源可提供 PE/PB/市值（stock_zh_a_spot 不含这些字段）。
        """
        try:
            df = self._get_spot()
            results = []
            for _, r in df.iterrows():
                try:
                    raw_symbol = str(r.get("代码", ""))
                    raw_name = str(r.get("名称", ""))
                    # 去除 AKShare 交易所前缀 (bj/sh/sz) → 6 位纯数字代码
                    symbol = self._normalize_symbol(raw_symbol)
                    # 从名称检测 ST
                    is_st = None
                    if raw_name:
                        if "*ST" in raw_name or "＊ST" in raw_name:
                            is_st = True
                        elif raw_name.startswith("ST"):
                            is_st = True
                    results.append(
                        Quote(
                            symbol=symbol,
                            name=raw_name,
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
                            high=float(r["最高"]) if self._valid(r.get("最高")) else None,
                            low=float(r["最低"]) if self._valid(r.get("最低")) else None,
                            open=float(r["今开"]) if self._valid(r.get("今开")) else None,
                            prev_close=float(r["昨收"]) if self._valid(r.get("昨收")) else None,
                            # 降级源（东财直连）可提供估值字段
                            pe_ttm=float(r["市盈率-动态"])
                            if self._valid(r.get("市盈率-动态")) else None,
                            pb=float(r["市净率"])
                            if self._valid(r.get("市净率")) else None,
                            market_cap=float(r.get("总市值", 0))
                            if self._valid(r.get("总市值")) else None,
                            is_st=is_st,
                            source=self.source_name,
                        )
                    )
                except Exception:
                    continue
            return results
        except Exception:
            return []

    @staticmethod
    def _normalize_symbol(raw: str) -> str:
        """去除 AKShare 交易所前缀，统一为 6 位纯数字代码。

        "bj920000" → "920000"
        "sh600000" → "600000"
        "sz000001" → "000001"
        "600519"   → "600519"   (已是纯数字)
        """
        raw = raw.strip().lower()
        for prefix in ("bj", "sh", "sz"):
            if raw.startswith(prefix) and len(raw) > len(prefix):
                return raw[len(prefix):]
        return raw

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
        """获取历史 K 线。

        push2.eastmoney.com 不可用时跳过东财源，直接使用腾讯源。
        """
        # push2 CDN 被阻断时直接走腾讯源，避免 60s 超时等待
        if not _PUSH2_UNAVAILABLE:
            try:
                return ak.stock_zh_a_hist(
                    symbol=symbol, period=period,
                    start_date=start_date, end_date=end_date,
                )
            except Exception:
                logger.debug("stock_zh_a_hist (push2) failed, falling back to tx", exc_info=True)
        # 降级：腾讯源 — symbol 需要市场前缀
        try:
            tx_symbol = _to_tx_symbol(symbol)
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_symbol, start_date=start_date, end_date=end_date,
            )
            # 腾讯源列名: date/open/close/high/low/amount → 统一为 volume
            if "amount" in df.columns:
                df = df.rename(columns={"amount": "volume"})
            return df
        except Exception:
            logger.debug("stock_zh_a_hist_tx failed for %s", symbol, exc_info=True)
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

    def get_sector_capital_flow(self, indicator: str = "今日") -> pd.DataFrame:
        """获取行业板块资金流向。

        Args:
            indicator: 统计周期，支持 "今日" / "5日" / "10日"。
        """
        try:
            with _em_no_proxy():
                return ak.stock_sector_fund_flow_rank(
                    indicator=indicator, sector_type="行业资金流"
                )
        except Exception:
            return pd.DataFrame()

    def get_stock_money_flow(self, symbol: str) -> pd.DataFrame:
        """获取个股资金流向（AKShare 备用接口）。"""
        try:
            code = symbol.strip()[-6:]
            first = code[0]
            market = "sh" if first in ("6", "9") else "sz"
            return ak.stock_individual_fund_flow(stock=code, market=market)
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """测试连通性。

        使用 datacenter API 探测（不受 push2 CDN 阻断影响）；
        push2 不可用时仍可提供财务数据、龙虎榜、融资融券等非实时行情数据。
        """
        if _PUSH2_UNAVAILABLE:
            # push2 被封，测试 datacenter 是否可用（财务/龙虎榜/北向等依赖此域）
            try:
                import requests
                s = requests.Session()
                s.proxies = {"http": None, "https": None}
                s.trust_env = False
                r = s.get("https://datacenter.eastmoney.com/", timeout=10)
                return r.status_code < 500
            except Exception:
                return False
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
        """获取全市场行情（5 分钟缓存）。

        降级链: AKShare stock_zh_a_spot → 东财 push2 直连 HTTP → 空 DataFrame
        push2 不可达时自动降级到直连 HTTP（trust_env=False 绕过系统代理）。
        """
        now = datetime.now()
        if (
            self._spot_cache is not None
            and self._spot_cache_time is not None
            and (now - self._spot_cache_time).seconds < 300
        ):
            return self._spot_cache

        # Tier 1: AKShare stock_zh_a_spot (push2 可用时)
        if not _PUSH2_UNAVAILABLE:
            try:
                self._spot_cache = ak.stock_zh_a_spot()
                self._spot_cache_time = now
                if self._spot_cache is not None and len(self._spot_cache) > 0:
                    return self._spot_cache
            except Exception:
                logger.debug("stock_zh_a_spot failed", exc_info=True)

        # Tier 2: 东财 push2 直连 HTTP (绕过系统代理, trust_env=False)
        df = self._fetch_spot_fallback()
        if df is not None and len(df) > 0:
            self._spot_cache = df
            self._spot_cache_time = now
            return self._spot_cache

        # Tier 3: 无可用的全市场数据源
        self._spot_cache = pd.DataFrame()
        self._spot_cache_time = now
        return self._spot_cache

    @staticmethod
    def _fetch_spot_fallback() -> pd.DataFrame:
        """东财 push2 直连 HTTP 降级 — 绕过 AKShare 库直接请求 push2 API。

        使用 trust_env=False 绕过系统代理，在 AKShare 因代理/WAF 被封时仍可能连通。
        返回与 stock_zh_a_spot() 相同列名的 DataFrame。
        """
        try:
            from .eastmoney_fallback import fetch_em_all_stocks

            rows = fetch_em_all_stocks()
            if not rows:
                return pd.DataFrame()

            # 转换为 stock_zh_a_spot() 兼容的 DataFrame（中文列名）
            data = []
            for r in rows:
                data.append({
                    "代码": r.get("code", ""),
                    "名称": r.get("name", ""),
                    "最新价": r.get("price"),
                    "涨跌幅": r.get("change_pct"),
                    "涨跌额": r.get("change_amount"),
                    "成交量": r.get("volume"),
                    "成交额": r.get("turnover"),
                    "振幅": r.get("amplitude"),
                    "最高": r.get("high"),
                    "最低": r.get("low"),
                    "今开": r.get("open"),
                    "昨收": r.get("prev_close"),
                    "量比": r.get("volume_ratio"),
                    "换手率": r.get("turnover_rate"),
                    "市盈率-动态": r.get("pe_ttm"),
                    "市净率": r.get("pb"),
                    "总市值": r.get("market_cap"),
                })
            df = pd.DataFrame(data)
            logger.info(
                "东财 push2 直连获取 %d 只 A 股行情 (降级路径)", len(df)
            )
            return df
        except Exception:
            logger.debug("东财 push2 直连降级失败", exc_info=True)
            return pd.DataFrame()

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
