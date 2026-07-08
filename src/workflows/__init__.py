# -*- coding: utf-8 -*-
"""Workflows — 技能与工作流系统。

基于 Dexter 设计，支持 YAML frontmatter + Markdown body 的技能定义、
多源发现、注册与查询。
"""

from __future__ import annotations

from .types import Skill, SkillMetadata
from .loader import SkillLoader
from .registry import SkillRegistry

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillLoader",
    "SkillRegistry",
]
