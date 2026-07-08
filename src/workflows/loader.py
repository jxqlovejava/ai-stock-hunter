# -*- coding: utf-8 -*-
"""技能加载器 — 从 .md 文件发现并加载技能。

文件格式：
  ---
  yaml frontmatter（SkillMetadata 字段）
  ---
  Markdown 正文（Skill.body）

用法：
  loader = SkillLoader()
  skills = loader.discover_skills("src/workflows/skills")
  skill = loader.load_skill("src/workflows/skills/dcf_valuation.md")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .types import Skill, SkillMetadata


class SkillLoader:
    """技能文件加载器。

    职责：
      - 递归扫描 skills 目录发现所有 .md 技能文件
      - 解析 YAML frontmatter + Markdown body
      - 返回 Skill 对象
    """

    _frontmatter_re = re.compile(
        r"^---\s*\n(.*?)\n---\s*\n?(.*)",
        re.DOTALL,
    )

    def discover_skills(self, skills_dir: str) -> dict[str, Skill]:
        """扫描 skills_dir 下所有 .md 文件，返回 {name: Skill} 字典。

        参数:
            skills_dir: 技能文件存放目录的绝对或相对路径。

        返回:
            技能名到 Skill 对象的映射字典。
        """
        base = Path(skills_dir).expanduser().resolve()
        if not base.is_dir():
            return {}

        result: dict[str, Skill] = {}
        for md_file in sorted(base.rglob("*.md")):
            try:
                skill = self.load_skill(str(md_file))
                result[skill.metadata.name] = skill
            except (ValueError, yaml.YAMLError) as exc:
                # 静默跳过格式异常的文件
                continue

        return result

    def load_skill(self, file_path: str) -> Skill:
        """加载单个 .md 技能文件。

        参数:
            file_path: 技能文件的绝对或相对路径。

        返回:
            解析后的 Skill 对象。

        异常:
            FileNotFoundError: 文件不存在。
            ValueError:      Frontmatter 解析失败或缺少必需元数据。
            yaml.YAMLError:  YAML 格式错误。
        """
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"技能文件不存在: {path}")

        raw = path.read_text(encoding="utf-8")

        match = self._frontmatter_re.match(raw)
        if not match:
            raise ValueError(
                f"缺少 YAML frontmatter（--- 包裹的元数据区域）: {file_path}"
            )

        frontmatter_text, body = match.groups()

        frontmatter: dict = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            raise ValueError(f"Frontmatter 不是有效的 YAML 字典: {file_path}")

        name = frontmatter.get("name")
        if not name:
            raise ValueError(f"Frontmatter 缺少 'name' 字段: {file_path}")

        metadata = SkillMetadata(
            name=str(name),
            description=str(frontmatter.get("description", "")),
            version=str(frontmatter.get("version", "1.0.0")),
            author=str(frontmatter.get("author", "")),
            category=str(frontmatter.get("category", "general")),
            requires=(
                list(frontmatter["requires"])
                if isinstance(frontmatter.get("requires"), list)
                else []
            ),
        )

        return Skill(
            metadata=metadata,
            body=body.strip(),
            file_path=str(path),
        )
