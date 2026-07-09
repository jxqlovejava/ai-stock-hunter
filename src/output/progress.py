# -*- coding: utf-8 -*-
r"""管道进度输出工具

借鉴 ai-gold-miner 的 logger.info + print 双通道模式：
- print() → 终端用户可见的进度/结果
- logging → 调试/诊断用

每个步骤使用 step_start / step_done 包裹，实现 [N/Total] 编号输出。
"""

from __future__ import annotations

import sys

TOTAL_STEPS = 10


def step_start(step_num: int, name: str, *, total: int = TOTAL_STEPS) -> None:
    """步骤开始 — 输出编号和名称。

    Usage:
        progress.step_start(1, "军规门禁")
        # ... 执行 ...
        progress.step_done("✅", "31/31 通过")
    """
    print(f"\n  [{step_num}/{total}] {name}...", end=" ", flush=True)


def step_done(icon: str = "✅", detail: str = "") -> None:
    """步骤完成 — 输出图标和可选详情。"""
    parts = [icon]
    if detail:
        parts.append(detail)
    print(" ".join(parts), flush=True)


def skip(step_num: int, name: str, reason: str, *, total: int = TOTAL_STEPS) -> None:
    """步骤跳过。"""
    print(f"\n  [{step_num}/{total}] {name} — ⏭️ {reason}", flush=True)


def info(msg: str) -> None:
    """输出缩进信息行。"""
    print(f"    {msg}", flush=True)


def warn(msg: str) -> None:
    """输出缩进警告。"""
    print(f"    ⚠️ {msg}", flush=True)


def section(title: str) -> None:
    """输出分隔标题 — 用于步骤内的子段落。"""
    print(f"\n    {'─'*50}")
    print(f"    {title}")
    print(f"    {'─'*50}", flush=True)


def header(symbol: str, name: str = "", mode: str = "daily") -> None:
    """分析开始头部。"""
    label = "选股分析" if mode == "full" else "日常监控"
    display = f"{name} ({symbol})" if name else symbol
    print(f"\n{'='*60}")
    print(f"  📊 {label}: {display}")
    print(f"{'='*60}", flush=True)


def footer() -> None:
    """分析结束底部。"""
    print(f"\n  ⚠️ AI分析结果，不构成投资建议。投资有风险，入市需谨慎。\n", flush=True)
