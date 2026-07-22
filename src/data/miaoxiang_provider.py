# -*- coding: utf-8 -*-
"""妙想金融数据适配器 — 实现 DataProvider 接口。

基于东方财富权威数据库，通过 mx-data/mx-search/mx-xuangu CLI 脚本
提供行情、财务、资讯搜索、条件选股等能力。

与现有 Provider 的关系:
  - mootdx+腾讯 (主力) → mx-data (交叉验证) → 国信 → AKShare
  - mx-search: 替代东财新闻，信源质量更高
  - mx-xuangu: 全市场预筛选加速

认证: MX_APIKEY 环境变量
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .base import DataProvider
from .miaoxiang_adapter import MiaoXiangAdapter
from .schema import (
    BoardChange,
    ExecutiveProfile,
    ExecutiveTrade,
    Financials,
    FundamentalMetrics,
    NewsItem,
    Quote,
    RelatedParty,
    ScreeningResult,
)

logger = logging.getLogger(__name__)


class MiaoXiangProvider(DataProvider):
    """妙想金融数据 Provider。

    实现 DataProvider 接口，同时暴露独有能力:
      - search_news()       → mx-search 资讯搜索
      - get_related_parties() → mx-data 关联关系
      - screen_stocks()     → mx-xuangu 条件选股
      - moni_*()            → mx-moni 模拟交易
      - poster_*()          → mx-poster 社区发帖

    source_name = "miaoxiang"
    """

    source_name = "miaoxiang"

    def __init__(self, api_key: str | None = None, output_dir: str | None = None):
        self._adapter = MiaoXiangAdapter(api_key=api_key if api_key is not None else None, output_dir=output_dir)
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl_quote = timedelta(minutes=5)
        self._cache_ttl_fin = timedelta(hours=1)
        self._cache_ttl_news = timedelta(minutes=30)
        self._cache_ttl_executive = timedelta(hours=4)
        # 日限额追踪（镜像 GuosenProvider 模式）
        self._exhausted: bool = False
        self._consecutive_quota_errors: int = 0
        self._last_reset_date = datetime.now().date()

    # ------------------------------------------------------------------
    # 配额管理
    # ------------------------------------------------------------------

    def _maybe_reset_quota(self):
        """跨日自动重置配额状态。"""
        today = datetime.now().date()
        if self._last_reset_date != today:
            self._exhausted = False
            self._consecutive_quota_errors = 0
            self._last_reset_date = today
            logger.info("妙想: 新的一天，配额状态已重置")

    def is_exhausted(self) -> bool:
        """今日配额是否已耗尽。"""
        self._maybe_reset_quota()
        return self._exhausted

    def mark_exhausted(self):
        """标记今日配额已耗尽，后续调用跳过 mx。"""
        self._exhausted = True
        logger.warning("妙想: 日配额已耗尽 (status 113)，今日停止 mx 请求")

    def _check_quota_status(self):
        """每轮 mx 调用后检查适配器是否报告配额耗尽。

        需连续 2 次出现 status 113 才标记 exhausted，
        避免偶发错误导致误判（全天黑名单）。
        """
        if self._adapter.last_quota_exceeded:
            self._consecutive_quota_errors += 1
            if self._consecutive_quota_errors >= 2:
                self.mark_exhausted()
        else:
            self._consecutive_quota_errors = 0

    # ------------------------------------------------------------------
    # DataProvider 接口
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional[Quote]:
        """获取单只股票实时行情（mx-data NL查询 → Quote Schema）。"""
        cache_key = f"quote:{symbol}"
        cached = self._cache_get(cache_key, self._cache_ttl_quote)
        if cached is not None:
            return cached

        raw = self._adapter.query_data(f"{symbol} 最新价 涨跌幅 成交量 成交额 最高价 最低价 开盘价")
        if raw is None:
            return None

        try:
            quote = self._parse_quote_from_raw(symbol, raw, market)
            if quote:
                self._cache_set(cache_key, quote)
            return quote
        except Exception as e:
            logger.debug("解析 mx-data Quote 失败 (%s): %s", symbol, e)
            return None

    def get_financials(
        self, symbol: str, market: str = "SH", count: int = 4
    ) -> list[Financials]:
        """获取财务报表（mx-data NL查询 → Financials Schema）。"""
        cache_key = f"fin:{symbol}:{count}"
        cached = self._cache_get(cache_key, self._cache_ttl_fin)
        if cached is not None:
            return cached

        raw = self._adapter.query_financials(symbol)
        if raw is None:
            return []

        try:
            fin_list = self._parse_financials_from_raw(symbol, raw, count)
            if fin_list:
                self._cache_set(cache_key, fin_list)
            return fin_list
        except Exception as e:
            logger.debug("解析 mx-data Financials 失败 (%s): %s", symbol, e)
            return []

    def health_check(self) -> bool:
        """快速连通性检查。"""
        return self._adapter.health_check()

    # ------------------------------------------------------------------
    # 独有能力: mx-search 资讯搜索
    # ------------------------------------------------------------------

    def search_news(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[NewsItem]:
        """搜索金融资讯，返回 NewsItem 列表。"""
        if self.is_exhausted():
            return []

        cache_key = f"news:{query}"
        cached = self._cache_get(cache_key, self._cache_ttl_news)
        if cached is not None:
            return cached[:max_results]

        raw = self._adapter.search_news(query)
        if raw is None:
            self._check_quota_status()
            return []

        items = []
        for entry in (raw if isinstance(raw, list) else []):
            try:
                items.append(NewsItem(
                    title=entry.get("title", ""),
                    source=entry.get("source", entry.get("secuList", [{}])[0].get("secuName", "") if entry.get("secuList") else ""),
                    date=str(entry.get("date", entry.get("time", ""))),
                    content=entry.get("trunk", entry.get("content", "")),
                    secu_list=entry.get("secuList", []),
                    url=entry.get("url", ""),
                ))
            except Exception:
                continue

        self._cache_set(cache_key, items)
        return items[:max_results]

    def search_announcements(self, symbol: str) -> list[NewsItem]:
        """搜索个股最新公告。"""
        return self.search_news(f"{symbol} 最新公告")

    def search_research_reports(self, symbol: str) -> list[NewsItem]:
        """搜索个股最新研报。"""
        return self.search_news(f"{symbol} 最新研报")

    # ------------------------------------------------------------------
    # 独有能力: mx-data 关联关系
    # ------------------------------------------------------------------

    def get_related_parties(self, symbol: str) -> list[RelatedParty]:
        """获取个股关联方（十大股东/高管/子公司）。"""
        if self.is_exhausted():
            return []
        cache_key = f"related:{symbol}"
        cached = self._cache_get(cache_key, self._cache_ttl_fin)
        if cached is not None:
            return cached

        # 先查十大股东
        raw = self._adapter.query_data(f"{symbol} 十大股东")
        if raw is None:
            self._check_quota_status()
        parties = self._parse_related_from_raw(raw)

        # 补充关联公司
        raw2 = self._adapter.query_data(f"{symbol} 关联公司 子公司")
        if raw2 is None:
            self._check_quota_status()
        else:
            extra = self._parse_related_from_raw(raw2)
            seen = {p.entity_name for p in parties}
            for p in extra:
                if p.entity_name not in seen:
                    parties.append(p)

        self._cache_set(cache_key, parties)
        return parties

    def get_main_force_flow(self, symbol: str) -> Optional[dict]:
        """获取个股主力资金流向。"""
        return self._adapter.query_main_force_flow(symbol)

    # ------------------------------------------------------------------
    # 独有能力: mx-data 高管数据 (executive-data)
    # ------------------------------------------------------------------

    def get_executive_trades(self, symbol: str) -> list[ExecutiveTrade]:
        """获取高管增减持数据。"""
        if self.is_exhausted():
            return []
        cache_key = f"exec_trades:{symbol}"
        cached = self._cache_get(cache_key, self._cache_ttl_executive)
        if cached is not None:
            return cached

        raw = self._adapter.query_executive_trades(symbol)
        if raw is None:
            self._check_quota_status()
        result = self._parse_executive_trades_from_raw(raw)
        self._cache_set(cache_key, result)
        return result

    def get_executive_profiles(self, symbol: str) -> list[ExecutiveProfile]:
        """获取高管背景履历。"""
        if self.is_exhausted():
            return []
        cache_key = f"exec_profiles:{symbol}"
        cached = self._cache_get(cache_key, self._cache_ttl_executive)
        if cached is not None:
            return cached

        raw = self._adapter.query_executive_profiles(symbol)
        if raw is None:
            self._check_quota_status()
        result = self._parse_executive_profiles_from_raw(raw)
        self._cache_set(cache_key, result)
        return result

    def get_board_changes(self, symbol: str) -> list[BoardChange]:
        """获取董监高变动。"""
        if self.is_exhausted():
            return []
        cache_key = f"board_changes:{symbol}"
        cached = self._cache_get(cache_key, self._cache_ttl_executive)
        if cached is not None:
            return cached

        raw = self._adapter.query_board_changes(symbol)
        if raw is None:
            self._check_quota_status()
        result = self._parse_board_changes_from_raw(raw)
        self._cache_set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # 独有能力: mx-xuangu 条件选股
    # ------------------------------------------------------------------

    def screen_stocks(self, conditions: str) -> list[ScreeningResult]:
        """按条件筛选股票。委托给 mx-xuangu。"""
        if self.is_exhausted():
            return []
        raw = self._adapter.screen_stocks(conditions)
        if raw is None:
            self._check_quota_status()
            return []
        results = []
        for entry in raw:
            try:
                results.append(ScreeningResult(
                    symbol=entry.get("SECURITY_CODE", ""),
                    name=entry.get("SECURITY_SHORT_NAME", ""),
                    market=entry.get("MARKET_SHORT_NAME", ""),
                    price=float(entry["NEWEST_PRICE"]) if entry.get("NEWEST_PRICE") else None,
                    change_pct=float(entry["CHG"]) if entry.get("CHG") else None,
                    pe_ttm=None,  # mx-xuangu 返回字段不固定
                    extra_fields=entry,
                ))
            except Exception:
                continue
        return results

    def screen_by_industry(
        self, industry: str, extra_conditions: str = ""
    ) -> list[ScreeningResult]:
        """按行业/板块筛选。"""
        cond = f"{industry}板块" + (f" {extra_conditions}" if extra_conditions else "")
        return self.screen_stocks(cond)

    def screen_all_markets(self, conditions: str) -> list[ScreeningResult]:
        """全市场条件筛选（用于替代/增强 AKShare 全市场扫描）。"""
        return self.screen_stocks(conditions)

    # ------------------------------------------------------------------
    # 独有能力: mx-moni 模拟交易代理
    # ------------------------------------------------------------------

    def moni_get_positions(self) -> Optional[dict]:
        """查询模拟持仓。"""
        return self._adapter.moni_positions()

    def moni_get_balance(self) -> Optional[dict]:
        """查询模拟资金。"""
        return self._adapter.moni_balance()

    def moni_get_orders(self) -> Optional[dict]:
        """查询模拟委托。"""
        return self._adapter.moni_orders()

    def moni_place_trade(
        self,
        stock_code: str,
        trade_type: str,
        price: float,
        quantity: int,
        use_market_price: bool = False,
    ) -> Optional[dict]:
        """执行模拟买卖。"""
        return self._adapter.moni_trade(stock_code, trade_type, price, quantity, use_market_price)

    def moni_cancel_order(
        self, order_id: str = "", stock_code: str = "", cancel_all: bool = False
    ) -> Optional[dict]:
        """撤单。"""
        return self._adapter.moni_cancel(order_id, stock_code, cancel_all)

    # ------------------------------------------------------------------
    # 独有能力: mx-poster 社区发帖代理
    # ------------------------------------------------------------------

    def poster_post(self, title: str, html_text: str) -> Optional[dict]:
        """发布社区文章。"""
        return self._adapter.poster_post_article(title, html_text)

    # ------------------------------------------------------------------
    # 内部解析: mx-data JSON → Quote
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_quote_from_raw(raw: dict, symbol: str, market: str) -> Optional[Quote]:
        """将 mx-data 的 API 响应解析为 Quote。

        mx-data 响应结构:
          data.dataTableDTOList[]:
            .entityName       → 证券全称
            .table.headName   → ["日期", ...]
            .table.*          → 指标数值数组
            .nameMap          → {字段编码: 中文名}
            .indicatorOrder   → 指标列排序
        """
        data = raw.get("data", raw)
        dtos = data.get("dataTableDTOList", [])
        if not dtos:
            return None

        dto = dtos[0]
        name = dto.get("entityName", "")
        table = dto.get("table", {})
        name_map = dto.get("nameMap", {})
        indicator_order = dto.get("indicatorOrder", [])

        # 构建 中文名 → 数值 的映射
        values: dict[str, float] = {}
        for field_code, field_values in table.items():
            if field_code == "headName":
                continue
            chinese_name = name_map.get(field_code, field_code)
            if field_values and isinstance(field_values, list) and len(field_values) > 0:
                try:
                    values[chinese_name] = float(field_values[0])
                except (ValueError, TypeError):
                    values[chinese_name] = 0.0

        # 按中文名模糊匹配到 Quote 字段
        price = _find_value(values, ["最新价", "收盘价", "现价"])
        prev_close = _find_value(values, ["昨收", "前收盘价"])
        change_pct = _find_value(values, ["涨跌幅", "涨幅"])
        volume = int(_find_value(values, ["成交量", "成交数量"]) or 0)
        turnover = _find_value(values, ["成交额", "成交金额"])

        return Quote(
            symbol=symbol,
            name=name.split("(")[0].strip() if "(" in name else name,
            price=price or 0.0,
            change_pct=change_pct or 0.0,
            volume=volume,
            turnover=turnover or 0.0,
            high=_find_value(values, ["最高价", "最高"]),
            low=_find_value(values, ["最低价", "最低"]),
            open=_find_value(values, ["开盘价", "开盘"]),
            prev_close=prev_close,
            source="miaoxiang",
        )

    @staticmethod
    def _parse_financials_from_raw(
        raw: dict, symbol: str, count: int
    ) -> list[Financials]:
        """将 mx-data 财务查询响应解析为 Financials 列表。

        每个 dataTableDTO 对应一个指标的时间序列。
        多个 dto 的 headName 时间列对齐后合并为多期 Financials。
        """
        data = raw.get("data", raw)
        dtos = data.get("dataTableDTOList", [])
        if not dtos:
            return []

        # 收集所有时间点
        all_periods: dict[str, dict] = {}
        for dto in dtos:
            table = dto.get("table", {})
            name_map = dto.get("nameMap", {})
            head_names = table.get("headName", [])
            if not head_names:
                continue

            for field_code, field_values in table.items():
                if field_code == "headName":
                    continue
                chinese_name = name_map.get(field_code, field_code)
                for i, period in enumerate(head_names):
                    if period not in all_periods:
                        all_periods[period] = {}
                    if i < len(field_values):
                        try:
                            all_periods[period][chinese_name] = float(field_values[i])
                        except (ValueError, TypeError):
                            pass

        # 构建 Financials 列表（取最近 count 期）
        sorted_periods = sorted(all_periods.keys(), reverse=True)[:count]
        results = []
        for period in sorted_periods:
            vals = all_periods[period]
            results.append(Financials(
                symbol=symbol,
                report_period=period,
                revenue=_find_value(vals, ["营业总收入", "营业收入"]),
                net_profit=_find_value(vals, ["归母净利润", "净利润"]),
                total_assets=_find_value(vals, ["总资产", "资产总计"]),
                total_liabilities=_find_value(vals, ["总负债", "负债合计"]),
                operating_cash_flow=_find_value(vals, ["经营活动现金流净额", "经营活动产生的现金流量净额"]),
                source="miaoxiang",
            ))
        return results

    @staticmethod
    def _parse_related_from_raw(raw: Optional[dict]) -> list[RelatedParty]:
        """解析关联关系数据。"""
        if raw is None:
            return []
        data = raw.get("data", raw)
        entities = data.get("entityTagDTOList", [])
        results = []
        for ent in entities:
            results.append(RelatedParty(
                entity_name=ent.get("fullName", ent.get("secuName", "")),
                relation_type=ent.get("entityTypeName", ""),
                stake_pct=None,
                position=ent.get("className", ""),
                description=f"{ent.get('fullName', '')} ({ent.get('entityTypeName', '')})",
            ))
        return results

    @staticmethod
    def _parse_executive_trades_from_raw(raw: Optional[list[dict]]) -> list[ExecutiveTrade]:
        """解析高管增减持数据。输入为 _extract_table_rows 的行列表。"""
        if not raw:
            return []
        results = []
        for row in raw:
            try:
                results.append(ExecutiveTrade(
                    executive_name=row.get("高管姓名", row.get("股东名称", row.get("姓名", ""))),
                    position=row.get("职务", row.get("担任职务", "")),
                    trade_type="buy" if "增持" in str(row.get("变动方向", row.get("变动类型", ""))) else "sell",
                    trade_date=str(row.get("变动日期", row.get("交易日期", ""))),
                    volume=_safe_int(row.get("变动股数", row.get("变动数量"))),
                    price=_safe_float(row.get("交易均价", row.get("成交均价"))),
                    total_value=_safe_float(row.get("变动金额", row.get("交易金额"))),
                    change_after_trade_pct=_safe_float(row.get("变动后持股比例", row.get("变动后持股%"))),
                ))
            except Exception:
                continue
        return results

    @staticmethod
    def _parse_executive_profiles_from_raw(raw: Optional[list[dict]]) -> list[ExecutiveProfile]:
        """解析高管背景履历。输入为 _extract_table_rows 的行列表。"""
        if not raw:
            return []
        results = []
        for row in raw:
            try:
                results.append(ExecutiveProfile(
                    name=row.get("姓名", row.get("高管姓名", "")),
                    position=row.get("职务", row.get("现任职务", "")),
                    age=_safe_int(row.get("年龄")),
                    education=row.get("学历", row.get("教育背景", "")),
                    background=row.get("背景", row.get("履历", row.get("个人简介", ""))),
                    tenure_start=str(row.get("任职起始日", row.get("任职日期", ""))),
                ))
            except Exception:
                continue
        return results

    @staticmethod
    def _parse_board_changes_from_raw(raw: Optional[list[dict]]) -> list[BoardChange]:
        """解析董监高变动。输入为 _extract_table_rows 的行列表。"""
        if not raw:
            return []
        results = []
        for row in raw:
            try:
                results.append(BoardChange(
                    person_name=row.get("姓名", row.get("变动人", row.get("人员姓名", ""))),
                    old_position=row.get("原职务", row.get("变动前职务", "")),
                    new_position=row.get("新职务", row.get("变动后职务", "")),
                    change_date=str(row.get("变动日期", row.get("公告日期", ""))),
                    reason=row.get("变动原因", row.get("原因", "")),
                ))
            except Exception:
                continue
        return results

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str, ttl: timedelta):
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > ttl:
            del self._cache[key]
            return None
        return val

    def _cache_set(self, key: str, val):
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self):
        self._cache.clear()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find_value(values: dict[str, float], candidates: list[str]) -> float | None:
    """按中文名模糊匹配，返回第一个命中的数值。"""
    for key in candidates:
        # 精确匹配
        if key in values:
            return values[key]
        # 模糊匹配
        for k, v in values.items():
            if key in k or k in key:
                return v
    return None


def _safe_int(val) -> Optional[int]:
    """安全转换为 int，失败返回 None。"""
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").replace("，", "")))
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    """安全转换为 float，失败返回 None。"""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("，", ""))
    except (ValueError, TypeError):
        return None
