# -*- coding: utf-8 -*-
"""华泰证券 AI 增强适配器。

华泰 skill 优先级最高 — 行情/诊断/洞察首选源。
行情获取通过 queryIndicator 接口，解析 AI 返回的结构化数据。
不可用时自动降级到国信 → 腾讯 → mootdx → AKShare。

提供的增强能力:
  - get_quote: 实时行情（queryIndicator 解析）
  - diagnosisStock: 个股诊断报告（L1 分析师 AI 增强）
  - marketInsight: 市场洞察（宏观事件解读）
  - queryIndicator: 金融指标查询（补充国信/AKShare 无法覆盖的指标）
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional


class HuataiProvider:
    """华泰证券 AI 增强适配器。

    ⚠️ 重要: 华泰 skill 不适合回测数据管道。仅用于交互式 AI 分析增强。
    """

    source_name = "huatai"

    def __init__(self):
        self._api_key = os.environ.get("HT_APIKEY", "")
        if not self._api_key:
            # 尝试从配置文件读取
            config_path = Path.home() / ".htsc-skills" / "config"
            if config_path.exists():
                for line in config_path.read_text().splitlines():
                    if line.startswith("HT_APIKEY="):
                        self._api_key = line.split("=", 1)[1]
                        break
        self._skill_dir = Path.home() / ".claude" / "skills"

    @property
    def available(self) -> bool:
        """检查华泰 skill 是否可用。"""
        return bool(self._api_key) and (self._skill_dir / "query-indicator").exists()

    def health_check(self) -> bool:
        return self.available

    def diagnosis_stock(self, query: str) -> Optional[str]:
        """个股诊断。调用 financial-analysis skill 的 diagnosisStock 工具。"""
        return self._run_skill("financial-analysis", "diagnosisStock", query)

    def market_insight(self, query: str) -> Optional[str]:
        """市场洞察。调用 financial-analysis skill 的 marketInsight 工具。"""
        return self._run_skill("financial-analysis", "marketInsight", query)

    def query_indicator(self, query: str) -> Optional[str]:
        """金融指标查询。调用 query-indicator skill 的 queryIndicator 工具。"""
        return self._run_skill("query-indicator", "queryIndicator", query)

    # ------------------------------------------------------------------
    # 实时行情 (Phase: 华泰作为主数据源)
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str, market: str = "SH") -> Optional["Quote"]:
        """通过华泰 queryIndicator 获取实时行情。

        调用 query-indicator skill 查询最新价/涨跌幅/成交量等，
        解析 AI 返回的结构化数据为 Quote DTO。
        超时 8s，失败返回 None 以便降级到国信。
        """
        from src.data.schema import Quote

        exchange = "SH" if symbol.startswith(("6", "68")) else "SZ"
        query = (
            f"请查询A股{exchange}{symbol}的实时行情，返回以下字段的JSON: "
            f"symbol(代码), name(名称), price(最新价), change_pct(涨跌幅%), "
            f"volume(成交量手), turnover(成交额万元), "
            f"open(今开), high(最高), low(最低), prev_close(昨收), "
            f"pe_ttm(市盈率), pb(市净率)。"
            f"只返回JSON，不要其他文字。"
        )
        text = self._run_skill("query-indicator", "queryIndicator", query, timeout=8)
        if not text:
            return None
        return self._parse_quote_response(text, symbol)

    def _parse_quote_response(self, text: str, symbol: str) -> Optional["Quote"]:
        """解析华泰 AI 返回的行情数据为 Quote DTO。

        支持格式:
          1. JSON 对象: {"symbol":"600519","price":1520.5,...}
          2. 键值对: 最新价: 62.23 | 涨跌幅: -0.95% | ...
          3. Markdown 表格 (尽力解析)
        """
        from src.data.schema import Quote

        data: dict = {}

        # 尝试 JSON 解析
        json_match = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if json_match:
            try:
                import json
                raw = json.loads(json_match.group())
                data = {
                    "symbol": raw.get("symbol", symbol),
                    "name": raw.get("name", ""),
                    "price": raw.get("price"),
                    "change_pct": raw.get("change_pct"),
                    "volume": raw.get("volume"),
                    "open": raw.get("open"),
                    "high": raw.get("high"),
                    "low": raw.get("low"),
                    "prev_close": raw.get("prev_close"),
                    "pe_ttm": raw.get("pe_ttm"),
                    "pb": raw.get("pb"),
                }
            except (json.JSONDecodeError, KeyError):
                pass

        # 键值对解析 (回退)
        if not data.get("price"):
            patterns = {
                "price": r'(?:最新价|现价|price)[：:]\s*([\d.]+)',
                "name": r'(?:名称|股票名称|name)[：:]\s*([^\n\r|]+)',
                "change_pct": r'(?:涨跌幅|涨跌%|change)[：:]\s*([+-]?[\d.]+)',
                "volume": r'(?:成交量|volume)[：:]\s*([\d,]+)',
                "open": r'(?:今开|开盘|open)[：:]\s*([\d.]+)',
                "high": r'(?:最高|high)[：:]\s*([\d.]+)',
                "low": r'(?:最低|low)[：:]\s*([\d.]+)',
                "prev_close": r'(?:昨收|前收|prev)[：:]\s*([\d.]+)',
                "pe_ttm": r'(?:市盈率|PE|pe)[：:]\s*([\d.]+)',
                "pb": r'(?:市净率|PB|pb)[：:]\s*([\d.]+)',
            }
            for key, pat in patterns.items():
                if key in data and data[key] is not None:
                    continue
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    val = m.group(1).replace(",", "")
                    try:
                        data[key] = float(val)
                    except ValueError:
                        data[key] = val if key in ("name",) else None

        # 必须有价格才能构造 Quote
        price = data.get("price")
        if not price or not isinstance(price, (int, float)):
            return None

        volume = data.get("volume")
        if isinstance(volume, (int, float)):
            volume = int(volume * 100) if volume < 10000 else int(volume)  # 手→股

        turnover = data.get("turnover")
        if isinstance(turnover, (int, float)) and turnover < 10000:
            turnover = turnover * 10000  # 万元→元

        return Quote(
            symbol=symbol,
            name=str(data.get("name", "")),
            price=float(price),
            change_pct=float(data.get("change_pct", 0) or 0),
            volume=volume or 0,
            turnover=turnover or 0.0,
            open=float(data["open"]) if data.get("open") else None,
            high=float(data["high"]) if data.get("high") else None,
            low=float(data["low"]) if data.get("low") else None,
            prev_close=float(data["prev_close"]) if data.get("prev_close") else None,
            pe_ttm=float(data["pe_ttm"]) if data.get("pe_ttm") else None,
            pb=float(data["pb"]) if data.get("pb") else None,
            source="huatai",
        )

    def _run_skill(self, skill: str, tool: str, query: str, timeout: int = 60) -> Optional[str]:
        """运行华泰 skill 工具。"""
        script = self._skill_dir / skill / f"{skill.replace('-', '_')}.py"
        if not script.exists():
            return None
        try:
            result = subprocess.run(
                ["python3", str(script), tool, "--query", query],
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "HT_APIKEY": self._api_key},
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None
