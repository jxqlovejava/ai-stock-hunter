# -*- coding: utf-8 -*-
"""JobExecutor — 通过子进程执行定时任务负载。

支持将 payload 作为 CLI 命令执行，并提供 A 股常用命令的快捷别名。
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 内置命令别名
# ------------------------------------------------------------------

_BUILTIN_COMMANDS: dict[str, str] = {
    "daily_close": "python -m src.cli scan --preset top10",
    "earnings_scan": "python -m src.cli sweep --preset earnings",
    "northbound_report": "python -m src.cli macro --northbound",
    "sentiment_check": "python -m src.cli sentiment",
    "alpha_scan": "python -m src.cli alpha-scan --limit 10",
    "market_overview": "python -m src.cli macro",
    "watchlist_sweep": "python -m src.cli sweep",
    "game_theory_snapshot": "python -m src.cli game-theory",
}

_DEFAULT_TIMEOUT_S = 300  # 5 分钟


class JobExecutor:
    """任务执行器 — 将 payload 作为 CLI 命令运行。"""

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT_S) -> None:
        self._timeout = timeout
        self._workdir: str = self._detect_workdir()

    @staticmethod
    def _detect_workdir() -> str:
        """检测项目工作目录。"""
        # 优先使用 CRON_WORKDIR 环境变量
        env_dir = os.environ.get("CRON_WORKDIR")
        if env_dir:
            return env_dir

        # 回退: 当前 src 所在项目的根目录
        src_path = Path(__file__).resolve().parent.parent.parent  # src/cron -> src -> project
        if (src_path / "pyproject.toml").exists() or (src_path / "setup.py").exists():
            return str(src_path)

        return os.getcwd()

    def resolve_command(self, payload: str) -> str:
        """将 payload 解析为实际 CLI 命令。

        支持:
          - 内置别名（daily_close / earnings_scan 等）
          - 原始 CLI 命令
        """
        payload = payload.strip()

        # 内置别名
        if payload in _BUILTIN_COMMANDS:
            return _BUILTIN_COMMANDS[payload]

        # "python -m ..." 模式 — 确保在正确的 venv 下运行
        if payload.startswith("python "):
            return payload

        # 原始 CLI 命令或脚本路径
        return payload

    def run_command(self, cmd: str) -> tuple[str, str, int]:
        """执行 CLI 命令，返回 (stdout, stderr, returncode)。

        Args:
            cmd: 要执行的命令字符串。

        Returns:
            (stdout, stderr, returncode)
        """
        resolved = self.resolve_command(cmd)
        logger.info("Executing command: %s", resolved)

        try:
            proc = subprocess.run(
                shlex.split(resolved),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=self._workdir,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            return stdout, stderr, proc.returncode
        except subprocess.TimeoutExpired:
            msg = f"Command timed out after {self._timeout}s: {resolved}"
            logger.error(msg)
            return "", msg, -1
        except FileNotFoundError:
            msg = f"Command not found: {shlex.split(resolved)[0]}"
            logger.error(msg)
            return "", msg, -2
        except OSError as exc:
            msg = f"OS error running command: {exc}"
            logger.error(msg)
            return "", msg, -3

    # ------------------------------------------------------------------
    # 内置命令管理
    # ------------------------------------------------------------------

    @staticmethod
    def list_builtins() -> dict[str, str]:
        """列出所有内置命令别名。"""
        return dict(_BUILTIN_COMMANDS)

    @staticmethod
    def register_builtin(name: str, command: str) -> None:
        """注册新的内置别名。"""
        _BUILTIN_COMMANDS[name] = command


# ── 默认主动任务注册 ──

def register_default_jobs():
    """注册系统默认的主动执行任务（开盘前/盘中/收盘后）。

    在 cli.py main() 启动时调用，确保 cron 有活跃任务。
    """
    # 1. 开盘前宏观快照 (每个交易日 09:15)
    JobExecutor.register_builtin(
        "pre_market_macro",
        "python -m src macro"
    )
    # 2. 盘中扫雷 (每 30 分钟)
    JobExecutor.register_builtin(
        "intraday_sweep",
        "python -m src sweep"
    )
    # 3. 收盘后情绪快照 (交易日 15:15)
    JobExecutor.register_builtin(
        "post_market_sentiment",
        "python -m src sentiment"
    )
    # 4. 收盘后恐慌套利扫描
    JobExecutor.register_builtin(
        "post_market_panic",
        "python -m src sweep --panic"
    )
    # 5. 产业链监控组扫描 (盘中 10:00/14:00 + 收盘后 15:30)
    JobExecutor.register_builtin(
        "monitor_group_scan",
        "python -m src.sentinel --mode monitor_group"
    )
