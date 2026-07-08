# -*- coding: utf-8 -*-
"""技能与工作流 Pydantic 模型。

SkillMetadata → 技能元数据（名称、描述、版本、分类等）
Skill         → 完整技能定义（元数据 + 正文内容 + 文件路径）
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """技能元数据。"""

    name: str = Field(..., description="技能名称，如 dcf-valuation")
    description: str = Field("", description="技能简述")
    version: str = Field("1.0.0", description="版本号")
    author: str = Field("", description="作者")
    category: str = Field("general", description="分类标签，如 valuation / memo / sentiment")
    requires: list[str] = Field(
        default_factory=list,
        description="前置依赖的技能名称列表",
    )


class Skill(BaseModel):
    """完整技能定义。"""

    metadata: SkillMetadata = Field(..., description="技能元数据")
    body: str = Field("", description="技能正文（Markdown）")
    file_path: str = Field("", description="技能文件原始路径")
