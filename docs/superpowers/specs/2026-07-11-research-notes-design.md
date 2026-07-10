# Design: 投研笔记 (Research Notes)

**Date**: 2026-07-11
**Status**: approved
**Complexity**: Small

## Summary

长期投研讨论记录模块。双向触发（用户/Claude均可发起），结构化归档（摘要+关键点+标签+完整内容），三级状态流转（discussion→actionable→implemented），FTS5全文可检索。

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Naming | `src/memory/types.py:12` | `@dataclass` DTO with `frozen=False`, `field(default_factory=...)` |
| Errors | `src/memory/database.py:128` | `try/except sqlite3.OperationalError` → return empty list |
| Storage | `src/memory/store.py:18` | File-based Markdown store, daily-file layout |
| Search | `src/memory/search.py:31` | Hybrid FTS5 + optional vector, time-decay |
| CLI | `src/cli.py` | `_import_or_none` lazy import, `python -m src <cmd>` pattern |

## Data Model

```python
@dataclass
class ResearchNote:
    id: str              # slug: "2026-07-11-goldman-sachs-ai-value-chain"
    created_at: datetime
    updated_at: datetime
    topic: str           # 机构分析 | 系统设计 | 交易原则 | 书籍阅读 | 市场观察 | 其他
    tags: list[str]      # ["高盛", "AI", "机构信用"]
    trigger_by: str      # "user" | "claude"
    source: str          # URL / 书名 / "对话"
    summary: str         # 3-5句关键摘要
    key_points: list[str] # 关键要点
    full_discussion: str # 完整讨论内容
    status: str          # "discussion" | "actionable" | "implemented"
```

## Storage Layout

```
data/notes/
├── 2026-07-11-goldman-sachs-ai-value-chain.md
├── 2026-07-11-institution-credibility-framework.md
├── 2026-07-11-investment-system-five-layers.md
└── ...
```

Each note is a standalone Markdown file with YAML-like frontmatter (key: value pairs in a header block).

## Files to Change

| File | Action | Why |
|------|--------|-----|
| `src/notes/__init__.py` | CREATE | Module entry, exports |
| `src/notes/types.py` | CREATE | ResearchNote dataclass |
| `src/notes/store.py` | CREATE | Markdown file CRUD |
| `src/notes/search.py` | CREATE | FTS5 search wrapper |
| `src/cli.py` | UPDATE | Add `note` subcommand |
| `data/notes/` | CREATE | Notes storage directory |
| `tests/test_notes.py` | CREATE | Unit tests |

## CLI

```bash
python -m src note add --topic "机构分析" --source "https://..." --summary "..."
python -m src note list [--status discussion] [--tag "高盛"]
python -m src note search "<query>"
python -m src note show <id>
python -m src note promote <id> --status actionable
```

## Validation

```bash
pytest tests/test_notes.py -v
python -m src note list
python -m src note search "高盛"
```
