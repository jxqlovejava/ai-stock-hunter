# -*- coding: utf-8 -*-
"""进化模块配置加载器。

从 YAML 文件加载可配置阈值，合并不完整配置与默认值。

用法:
    config = EvolutionConfigLoader.load()
    config = EvolutionConfigLoader.load("data/evolution_config.yaml")
    print(config.backtest.min_sharpe_ratio)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .schema import (
    BacktestThresholds,
    EvolutionConfig,
    MonitoringConfig,
    TrialThresholds,
)

logger = logging.getLogger(__name__)

# 默认配置路径
DEFAULT_CONFIG_PATH = "data/evolution_config.yaml"

# 内联默认配置
DEFAULT_CONFIG_YAML = """\
# 策略进化模块 — 可配置阈值
# 修改此文件后下次进化即生效，无需重启

backtest:
  min_sharpe_ratio: 0.5
  min_total_return: 0.10
  max_max_drawdown: 0.25
  min_trades: 20
  benchmark: "000300.SH"

trial:
  min_duration_days: 30
  min_trades: 10
  sharpe_superiority: 0.10
  max_drawdown_limit: 0.20
  benchmark: "000300.SH"

monitoring:
  check_interval_hours: 24
  degradation_window_days: 14
  auto_optimize_on_degrade: true
"""


class EvolutionConfigLoader:
    """进化配置加载器。

    从 YAML 加载，缺失字段用默认值填充。
    如果配置文件不存在，自动创建默认配置文件。

    用法:
        config = EvolutionConfigLoader.load()
        config = EvolutionConfigLoader.load("custom/path.yaml")
    """

    @staticmethod
    def load(path: Optional[str] = None) -> EvolutionConfig:
        """加载进化配置。

        Args:
            path: 配置文件路径，默认 data/evolution_config.yaml

        Returns:
            EvolutionConfig 合并默认值后的完整配置
        """
        config_path = path or DEFAULT_CONFIG_PATH
        raw = EvolutionConfigLoader._read_yaml(config_path)
        return EvolutionConfig.from_dict(raw)

    @staticmethod
    def _read_yaml(path: str) -> dict:
        """读取 YAML 文件，不存在时自动创建。"""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML 未安装，使用默认配置。pip install pyyaml")
            return {}

        full_path = Path(path)

        if not full_path.exists():
            logger.info("配置文件不存在，创建默认配置: %s", full_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data or {}
        except Exception as e:
            logger.warning("配置文件读取失败 (%s)，使用默认值: %s", path, e)
            return {}

    @staticmethod
    def reset(path: Optional[str] = None):
        """重置配置文件为默认值。"""
        config_path = path or DEFAULT_CONFIG_PATH
        full_path = Path(config_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
        logger.info("配置已重置: %s", full_path)

    @staticmethod
    def default_config() -> EvolutionConfig:
        """返回纯默认配置（不读文件）。"""
        return EvolutionConfig()
