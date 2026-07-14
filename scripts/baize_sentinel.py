#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hermes cron 入口 — 白泽持仓哨兵。

用法（服务器）:
  /path/to/venv/bin/python /home/ubuntu/ai-stock-hunter/scripts/baize_sentinel.py

环境变量:
  BAIZE_ROOT           仓库根目录（默认脚本上级）
  BAIZE_POSITIONS      positions.json
  BAIZE_SENTINEL_STATE 状态文件
  BAIZE_SENTINEL_CONFIG 可选 JSON 配置

Hermes 约定: stdout 空=静默；有内容=投递微信。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BAIZE_ROOT", Path(__file__).resolve().parents[1]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sentinel.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
