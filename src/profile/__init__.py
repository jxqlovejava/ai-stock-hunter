# -*- coding: utf-8 -*-
"""用户画像持久化层。

从 src.learner.profile.ProfileTracker 获取评估结果，
持久化到本地 JSON 文件，供系统启动时加载和跨会话复用。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "user_profile.json")


def load_profile(path: str | None = None) -> dict | None:
    """加载持久化的用户画像。"""
    target = path or DEFAULT_PROFILE_PATH
    try:
        with open(target, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_profile(profile_data: dict, path: str | None = None) -> str:
    """保存用户画像到本地。"""
    target = path or DEFAULT_PROFILE_PATH
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False, default=str)
    return target


__all__ = ["load_profile", "save_profile", "DEFAULT_PROFILE_PATH"]
