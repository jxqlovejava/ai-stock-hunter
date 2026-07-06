# -*- coding: utf-8 -*-
"""白泽 (Baize) 配置管理。

从 .env 文件和环境变量加载配置，提供统一的配置访问入口。

使用:
    from src.config import config
    api_key = config.mx_apikey
    log_level = config.log_level
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 项目根目录 (ai-stock-hunter/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """尝试加载 .env 文件 (不强制要求 python-dotenv 已安装)。"""
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("已加载 .env: %s", env_path)
        else:
            logger.debug(".env 不存在，使用环境变量: %s", env_path)
    except ImportError:
        logger.debug("python-dotenv 未安装，跳过 .env 加载")


_load_dotenv()


# --- 环境变量名常量 ---
_ENV_MX_APIKEY = "MX_APIKEY"
_ENV_MX_API_URL = "MX_API_URL"
_ENV_GS_API_KEY = "GS_API_KEY"
_ENV_HT_APIKEY = "HT_APIKEY"
_ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
_ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
_ENV_LOG_LEVEL = "LOG_LEVEL"
_ENV_REALTIME_PRIORITY = "DATA_SOURCE_PRIORITY_REALTIME"
_ENV_FUNDAMENTALS_PRIORITY = "DATA_SOURCE_PRIORITY_FUNDAMENTALS"
_ENV_KLINE_PRIORITY = "DATA_SOURCE_PRIORITY_KLINE"
_ENV_CACHE_TTL_DAILY = "CACHE_TTL_DAILY"
_ENV_CACHE_TTL_MINUTE = "CACHE_TTL_MINUTE"
_ENV_CACHE_TTL_TICK = "CACHE_TTL_TICK"
_ENV_BACKTEST_INITIAL_CASH = "BACKTEST_INITIAL_CASH"
_ENV_BACKTEST_START_DATE = "BACKTEST_START_DATE"
_ENV_BACKTEST_END_DATE = "BACKTEST_END_DATE"


@dataclass
class Config:
    """白泽全局配置。

    所有字段从环境变量读取，优先级: 环境变量 > .env 文件 > 默认值。
    """

    # --- API 密钥 ---
    mx_apikey: str = field(
        default_factory=lambda: os.environ.get(_ENV_MX_APIKEY, "")
    )
    mx_api_url: str = field(
        default_factory=lambda: os.environ.get(
            _ENV_MX_API_URL, "https://mkapi2.dfcfs.com/finskillshub"
        )
    )
    gs_api_key: str = field(
        default_factory=lambda: os.environ.get(_ENV_GS_API_KEY, "")
    )
    ht_apikey: str = field(
        default_factory=lambda: os.environ.get(_ENV_HT_APIKEY, "")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get(_ENV_ANTHROPIC_API_KEY, "")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get(_ENV_OPENAI_API_KEY, "")
    )

    # --- 日志 ---
    log_level: str = field(
        default_factory=lambda: os.environ.get(_ENV_LOG_LEVEL, "INFO").upper()
    )

    # --- 数据源优先级 ---
    realtime_priority: list[str] = field(default_factory=list)

    fundamentals_priority: list[str] = field(default_factory=list)

    kline_priority: list[str] = field(default_factory=list)

    # --- 缓存 TTL (秒) ---
    cache_ttl_daily: int = field(default_factory=lambda: _env_int(_ENV_CACHE_TTL_DAILY, 21600))
    cache_ttl_minute: int = field(default_factory=lambda: _env_int(_ENV_CACHE_TTL_MINUTE, 1800))
    cache_ttl_tick: int = field(default_factory=lambda: _env_int(_ENV_CACHE_TTL_TICK, 300))

    # --- 回测 ---
    backtest_initial_cash: float = field(
        default_factory=lambda: _env_float(_ENV_BACKTEST_INITIAL_CASH, 1_000_000)
    )
    backtest_start_date: str = field(
        default_factory=lambda: os.environ.get(_ENV_BACKTEST_START_DATE, "20200101")
    )
    backtest_end_date: str = field(
        default_factory=lambda: os.environ.get(_ENV_BACKTEST_END_DATE, "20251231")
    )

    def __post_init__(self):
        """解析列表类配置。"""
        if not self.realtime_priority:
            raw = os.environ.get(_ENV_REALTIME_PRIORITY, "")
            self.realtime_priority = (
                [s.strip() for s in raw.split(",") if s.strip()]
                if raw
                else ["mootdx", "tencent", "guosen", "akshare"]
            )
        if not self.fundamentals_priority:
            raw = os.environ.get(_ENV_FUNDAMENTALS_PRIORITY, "")
            self.fundamentals_priority = (
                [s.strip() for s in raw.split(",") if s.strip()]
                if raw
                else ["mootdx", "guosen", "akshare"]
            )
        if not self.kline_priority:
            raw = os.environ.get(_ENV_KLINE_PRIORITY, "")
            self.kline_priority = (
                [s.strip() for s in raw.split(",") if s.strip()]
                if raw
                else ["mootdx", "akshare"]
            )

    @property
    def has_mx(self) -> bool:
        """妙想 API 是否已配置。"""
        return bool(self.mx_apikey)

    @property
    def has_guosen(self) -> bool:
        """国信 API 是否已配置。"""
        return bool(self.gs_api_key)

    @property
    def has_huatai(self) -> bool:
        """华泰 API 是否已配置。"""
        return bool(self.ht_apikey)

    @property
    def has_ai(self) -> bool:
        """AI 模型密钥是否已配置。"""
        return bool(self.anthropic_api_key or self.openai_api_key)

    def summary(self) -> str:
        """返回配置摘要（不泄露密钥内容）。"""
        lines = [
            "白泽配置摘要:",
            f"  妙想 API:    {'✓ 已配置' if self.has_mx else '✗ 未配置'}",
            f"  国信 API:    {'✓ 已配置' if self.has_guosen else '✗ 未配置'}",
            f"  华泰 API:    {'✓ 已配置' if self.has_huatai else '✗ 未配置'}",
            f"  AI 模型:     {'✓ 已配置' if self.has_ai else '✗ 未配置'}",
            f"  日志级别:    {self.log_level}",
            f"  行情优先级:  {' > '.join(self.realtime_priority)}",
            f"  财务优先级:  {' > '.join(self.fundamentals_priority)}",
            f"  K线优先级:   {' > '.join(self.kline_priority)}",
            f"  项目根目录:  {PROJECT_ROOT}",
        ]
        return "\n".join(lines)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# 全局单例
config = Config()
