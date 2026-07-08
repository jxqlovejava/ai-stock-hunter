# -*- coding: utf-8 -*-
"""输出配置文件 (OutputProfile)。

定义不同输出渠道的格式化约束，使 formatter 能根据目标渠道
调整输出风格 (表格样式、Markdown 允许性、语言、语气等)。

Usage:
    from src.output.profiles import get_profile, OutputProfile

    # 按名字获取预设 profile
    profile = get_profile("wechat")

    # 自定义 profile
    custom = OutputProfile(
        name="telegram",
        table_style="simple",
        markdown_allowed=True,
        max_length=4096,
        language="zh",
        tone="professional",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# 样式常量
# ---------------------------------------------------------------------------

# 表格样式
TABLE_SIMPLE = "simple"         # 无框纯文本列
TABLE_GRID = "grid"             # 带边框网格
TABLE_PIPE = "pipe"             # Markdown 管道表格
TABLE_ROUNDED = "rounded"       # 圆角 ASCII 表格

# 语气
TONE_PROFESSIONAL = "professional"   # 专业/稳重
TONE_CONCISE = "concise"            # 简洁/精炼
TONE_FRIENDLY = "friendly"          # 友好/易懂
TONE_WARNING = "warning"            # 警示/紧急


@dataclass
class OutputProfile:
    """输出渠道配置。

    Attributes:
        name:           配置名，如 "cli"、"wechat"、"email"、"api"
        table_style:    表格渲染风格 (simple/grid/pipe/rounded)
        markdown_allowed: 是否允许 Markdown 格式 (粗体/列表/标题等)
        max_length:     最大字符数限制 (0 = 无限制)
        language:       输出语言代码 (zh/en)
        tone:           语气风格 (professional/concise/friendly/warning)
    """

    name: str = "cli"
    table_style: str = TABLE_PIPE
    markdown_allowed: bool = True
    max_length: int = 0
    language: str = "zh"
    tone: str = TONE_PROFESSIONAL

    @property
    def is_rich(self) -> bool:
        """是否支持富文本格式 (Markdown、彩色表格等)。"""
        return self.markdown_allowed

    @property
    def is_truncated(self) -> bool:
        """是否有长度限制。"""
        return self.max_length > 0

    @property
    def supports_emoji(self) -> bool:
        """是否支持 emoji。"""
        return self.name != "api"


# ---------------------------------------------------------------------------
# 预设 Profiles
# ---------------------------------------------------------------------------

CLIProfile = OutputProfile(
    name="cli",
    table_style=TABLE_ROUNDED,
    markdown_allowed=True,
    max_length=0,
    language="zh",
    tone=TONE_CONCISE,
)

WeChatProfile = OutputProfile(
    name="wechat",
    table_style=TABLE_SIMPLE,
    markdown_allowed=False,
    max_length=2048,
    language="zh",
    tone=TONE_FRIENDLY,
)

EmailProfile = OutputProfile(
    name="email",
    table_style=TABLE_GRID,
    markdown_allowed=True,
    max_length=0,
    language="zh",
    tone=TONE_PROFESSIONAL,
)

APIProfile = OutputProfile(
    name="api",
    table_style=TABLE_PIPE,
    markdown_allowed=False,
    max_length=0,
    language="zh",
    tone=TONE_CONCISE,
)

# 按名称索引
_PROFILES: dict[str, OutputProfile] = {
    "cli": CLIProfile,
    "wechat": WeChatProfile,
    "email": EmailProfile,
    "api": APIProfile,
}


def get_profile(name: str) -> OutputProfile:
    """按名称获取预设 OutputProfile。

    Args:
        name: "cli" | "wechat" | "email" | "api"

    Returns:
        OutputProfile 实例；未匹配时默认返回 CLIProfile。
    """
    return _PROFILES.get(name, CLIProfile)
