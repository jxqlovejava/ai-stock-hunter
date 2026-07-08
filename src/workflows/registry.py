# -*- coding: utf-8 -*-
"""技能注册表 — 内存中的技能索引与查询。

用法：
  registry = SkillRegistry()
  registry.register(skill)
  skills = registry.list_all()
  dcf = registry.get("dcf-valuation")
  val_skills = registry.list_by_category("valuation")
"""

from __future__ import annotations

from typing import Optional

from .types import Skill, SkillMetadata


class SkillRegistry:
    """技能注册表。

    职责：
      - 注册 Skill 实例
      - 按名称查询 Skill
      - 列出全部元数据 / 按分类筛选
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册一个技能。

        已存在同名技能时覆盖并给出警告。

        参数:
            skill: 要注册的 Skill 对象。
        """
        name = skill.metadata.name
        if name in self._skills:
            exists = self._skills[name].file_path
        self._skills[name] = skill

    def get(self, name: str) -> Optional[Skill]:
        """按名称获取技能。

        参数:
            name: 技能名称。

        返回:
            对应的 Skill 对象，不存在时返回 None。
        """
        return self._skills.get(name)

    def list_all(self) -> list[SkillMetadata]:
        """列出所有已注册技能的元数据。

        返回:
            按名称排序的 SkillMetadata 列表。
        """
        return sorted(
            (s.metadata for s in self._skills.values()),
            key=lambda m: m.name,
        )

    def list_by_category(self, category: str) -> list[SkillMetadata]:
        """按分类列出技能的元数据。

        参数:
            category: 分类名称（大小写敏感）。

        返回:
            匹配分类的 SkillMetadata 列表，按名称排序。
        """
        return sorted(
            (s.metadata for s in self._skills.values() if s.metadata.category == category),
            key=lambda m: m.name,
        )
