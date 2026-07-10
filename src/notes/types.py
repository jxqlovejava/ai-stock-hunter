"""Research note dataclasses.

ResearchNote: single discussion record with full provenance.
NoteStatus: lifecycle states (discussion → actionable → implemented).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


# ------------------------------------------------------------------
# status constants
# ------------------------------------------------------------------

class NoteStatus:
    """Lifecycle states for a research note."""

    DISCUSSION = "discussion"
    ACTIONABLE = "actionable"
    IMPLEMENTED = "implemented"

    ALL = {DISCUSSION, ACTIONABLE, IMPLEMENTED}

    @classmethod
    def valid(cls, status: str) -> bool:
        return status in cls.ALL


# ------------------------------------------------------------------
# topic constants
# ------------------------------------------------------------------

class NoteTopic:
    """Predefined topic categories."""

    INSTITUTION = "机构分析"
    SYSTEM_DESIGN = "系统设计"
    TRADING_PRINCIPLE = "交易原则"
    BOOK_READING = "书籍阅读"
    MARKET_OBSERVATION = "市场观察"
    OTHER = "其他"

    ALL = {
        INSTITUTION,
        SYSTEM_DESIGN,
        TRADING_PRINCIPLE,
        BOOK_READING,
        MARKET_OBSERVATION,
        OTHER,
    }

    @classmethod
    def valid(cls, topic: str) -> bool:
        return topic in cls.ALL


# ------------------------------------------------------------------
# dataclass
# ------------------------------------------------------------------

@dataclass
class ResearchNote:
    """A single research discussion record.

    Attributes:
        id: unique slug (e.g. "2026-07-11-goldman-sachs-ai")
        created_at: when first recorded
        updated_at: last modification time
        topic: category from NoteTopic
        tags: searchable keyword list
        trigger_by: who initiated ("user" | "claude")
        source: URL, book title, or "对话"
        summary: 3-5 sentence key summary
        key_points: bullet-point takeaways
        full_discussion: complete discussion content
        status: lifecycle state from NoteStatus
    """

    id: str
    created_at: datetime
    updated_at: datetime
    topic: str
    tags: list[str] = field(default_factory=list)
    trigger_by: str = "user"
    source: str = "对话"
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    full_discussion: str = ""
    status: str = NoteStatus.DISCUSSION

    def to_markdown(self) -> str:
        """Serialize to a Markdown file body."""
        lines = [
            f"---",
            f"id: {self.id}",
            f"created_at: {self.created_at.isoformat()}",
            f"updated_at: {self.updated_at.isoformat()}",
            f"topic: {self.topic}",
            f"tags: [{', '.join(self.tags)}]",
            f"trigger_by: {self.trigger_by}",
            f"source: {self.source}",
            f"status: {self.status}",
            f"---",
            "",
            f"# {self._title()}",
            "",
            f"## 摘要",
            f"",
            f"{self.summary}",
            "",
            f"## 关键要点",
            f"",
        ]
        for pt in self.key_points:
            lines.append(f"- {pt}")
        lines.extend([
            "",
            f"## 完整讨论",
            "",
            self.full_discussion,
        ])
        return "\n".join(lines)

    @staticmethod
    def from_markdown(text: str) -> "ResearchNote | None":
        """Parse a Markdown file back into a ResearchNote. Returns None on failure."""
        import re
        from datetime import datetime as dt

        try:
            # Must start with frontmatter delimiter
            if not text.strip().startswith("---"):
                return None

            lines = text.splitlines()
            frontmatter: dict = {}
            in_fm = False
            fm_lines: list[str] = []
            fm_delim_count = 0
            for line in lines:
                if line.strip() == "---":
                    fm_delim_count += 1
                    if fm_delim_count == 1:
                        in_fm = True
                        continue
                    elif fm_delim_count == 2:
                        break
                if in_fm:
                    fm_lines.append(line)

            # No frontmatter found
            if fm_delim_count < 2:
                return None

            for line in fm_lines:
                m = re.match(r"^(\w+):\s*(.*)", line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    frontmatter[key] = val

            # parse tags: "[tag1, tag2]"
            tags_str = frontmatter.get("tags", "[]")
            tags = [
                t.strip().strip('"').strip("'")
                for t in tags_str.strip("[]").split(",")
                if t.strip()
            ]

            # parse key_points from the "## 关键要点" section
            body = text.split("## 完整讨论", 1)
            before_discussion = body[0] if body else text
            key_points: list[str] = []
            kp_section = before_discussion.split("## 关键要点", 1)
            if len(kp_section) > 1:
                kp_text = kp_section[1]
                for line in kp_text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        key_points.append(stripped[2:])

            # parse summary from "## 摘要" section
            summary = ""
            sum_section = before_discussion.split("## 摘要", 1)
            if len(sum_section) > 1:
                sum_text = sum_section[1].split("## 关键要点", 1)[0]
                summary = sum_text.strip()

            # full discussion
            full_discussion = ""
            if "## 完整讨论" in text:
                fd = text.split("## 完整讨论", 1)[1].strip()
                full_discussion = fd

            return ResearchNote(
                id=frontmatter.get("id", ""),
                created_at=dt.fromisoformat(frontmatter.get("created_at", dt.now().isoformat())),
                updated_at=dt.fromisoformat(frontmatter.get("updated_at", dt.now().isoformat())),
                topic=frontmatter.get("topic", NoteTopic.OTHER),
                tags=tags,
                trigger_by=frontmatter.get("trigger_by", "user"),
                source=frontmatter.get("source", "对话"),
                summary=summary,
                key_points=key_points,
                full_discussion=full_discussion,
                status=frontmatter.get("status", NoteStatus.DISCUSSION),
            )
        except Exception:
            return None

    def _title(self) -> str:
        """Generate a display title from the note id."""
        parts = self.id.split("-", 3)
        if len(parts) >= 4:
            return parts[3].replace("-", " ").title()
        return self.id.replace("-", " ").title()

    def promote(self, new_status: str) -> None:
        """Transition to a new status. Raises ValueError if invalid."""
        if not NoteStatus.valid(new_status):
            raise ValueError(f"Invalid status: {new_status}")
        self.status = new_status
        self.updated_at = datetime.now()
