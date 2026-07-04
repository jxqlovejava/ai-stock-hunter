# -*- coding: utf-8 -*-
"""华泰证券 AI 增强适配器。

华泰 skill 不进入数据管道——仅用于 L1 分析中的 AI 解读增强。
与国信/AKShare 的适配器定位不同: 华泰返回自然语言 Markdown，不可靠提取结构化数据。

提供的增强能力:
  - diagnosisStock: 个股诊断报告（L1 分析师 AI 增强）
  - marketInsight: 市场洞察（宏观事件解读）
  - queryIndicator: 金融指标查询（补充国信/AKShare 无法覆盖的指标）
"""

from __future__ import annotations

import os
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

    def _run_skill(self, skill: str, tool: str, query: str) -> Optional[str]:
        """运行华泰 skill 工具。"""
        script = self._skill_dir / skill / f"{skill.replace('-', '_')}.py"
        if not script.exists():
            return None
        try:
            result = subprocess.run(
                ["python3", str(script), tool, "--query", query],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "HT_APIKEY": self._api_key},
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None
