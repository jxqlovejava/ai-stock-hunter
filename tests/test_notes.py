"""Tests for research notes module."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.notes import NoteSearch, NoteStatus, NoteStore, NoteTopic, ResearchNote


# ------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------


@pytest.fixture
def tmp_store():
    """Create a NoteStore backed by a temp directory."""
    with tempfile.TemporaryDirectory() as d:
        yield NoteStore(base_dir=d)


@pytest.fixture
def sample_note():
    """A minimal valid ResearchNote."""
    return ResearchNote(
        id="2026-07-11-test-note",
        created_at=datetime(2026, 7, 11, 10, 0, 0),
        updated_at=datetime(2026, 7, 11, 10, 0, 0),
        topic=NoteTopic.SYSTEM_DESIGN,
        tags=["测试", "系统"],
        trigger_by="user",
        source="对话",
        summary="这是一条测试笔记的摘要。",
        key_points=["要点一：测试存储", "要点二：测试搜索"],
        full_discussion="这是完整的讨论内容，用于测试存储和检索。",
        status=NoteStatus.DISCUSSION,
    )


# ------------------------------------------------------------------
# types
# ------------------------------------------------------------------


class TestResearchNote:
    def test_create_minimal(self):
        note = ResearchNote(
            id="test-1",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
        )
        assert note.id == "test-1"
        assert note.status == NoteStatus.DISCUSSION
        assert note.tags == []
        assert note.key_points == []

    def test_to_markdown_roundtrip(self, sample_note):
        md = sample_note.to_markdown()
        assert "---" in md
        assert "id: 2026-07-11-test-note" in md
        assert "## 摘要" in md
        assert "## 关键要点" in md
        assert "## 完整讨论" in md
        assert "这是一条测试笔记的摘要。" in md
        assert "要点一：测试存储" in md

    def test_from_markdown_roundtrip(self, sample_note):
        md = sample_note.to_markdown()
        parsed = ResearchNote.from_markdown(md)
        assert parsed is not None
        assert parsed.id == sample_note.id
        assert parsed.topic == sample_note.topic
        assert parsed.tags == sample_note.tags
        assert parsed.summary == sample_note.summary
        assert parsed.key_points == sample_note.key_points
        assert parsed.status == sample_note.status

    def test_from_markdown_invalid(self):
        assert ResearchNote.from_markdown("not valid markdown") is None
        assert ResearchNote.from_markdown("") is None

    def test_from_markdown_partial(self):
        md = """---
id: test-minimal
created_at: 2026-07-11T10:00:00
updated_at: 2026-07-11T10:00:00
topic: 其他
tags: []
trigger_by: user
source: 对话
status: discussion
---

# Test

## 摘要

minimal summary

## 关键要点

- point 1

## 完整讨论

full text here
"""
        note = ResearchNote.from_markdown(md)
        assert note is not None
        assert note.id == "test-minimal"
        assert note.summary == "minimal summary"
        assert note.key_points == ["point 1"]
        assert note.full_discussion == "full text here"

    def test_promote_valid(self, sample_note):
        sample_note.promote(NoteStatus.ACTIONABLE)
        assert sample_note.status == NoteStatus.ACTIONABLE

    def test_promote_invalid(self, sample_note):
        with pytest.raises(ValueError, match="Invalid status"):
            sample_note.promote("invalid_status")

    def test_promote_cycle(self, sample_note):
        sample_note.promote(NoteStatus.ACTIONABLE)
        assert sample_note.status == NoteStatus.ACTIONABLE
        sample_note.promote(NoteStatus.IMPLEMENTED)
        assert sample_note.status == NoteStatus.IMPLEMENTED
        sample_note.promote(NoteStatus.DISCUSSION)
        assert sample_note.status == NoteStatus.DISCUSSION


class TestNoteStatus:
    def test_valid_statuses(self):
        assert NoteStatus.valid(NoteStatus.DISCUSSION)
        assert NoteStatus.valid(NoteStatus.ACTIONABLE)
        assert NoteStatus.valid(NoteStatus.IMPLEMENTED)

    def test_invalid_status(self):
        assert not NoteStatus.valid("pending")
        assert not NoteStatus.valid("")


class TestNoteTopic:
    def test_valid_topics(self):
        for t in NoteTopic.ALL:
            assert NoteTopic.valid(t)

    def test_invalid_topic(self):
        assert not NoteTopic.valid("不存在的主题")


# ------------------------------------------------------------------
# store
# ------------------------------------------------------------------


class TestNoteStore:
    def test_save_and_get(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        loaded = tmp_store.get(sample_note.id)
        assert loaded is not None
        assert loaded.id == sample_note.id
        assert loaded.summary == sample_note.summary

    def test_get_missing(self, tmp_store):
        assert tmp_store.get("nonexistent-id") is None

    def test_list_all_empty(self, tmp_store):
        assert tmp_store.list_all() == []

    def test_list_all_with_notes(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        notes = tmp_store.list_all()
        assert len(notes) == 1
        assert notes[0].id == sample_note.id

    def test_list_filter_by_status(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        # create actionable note
        n2 = ResearchNote(
            id="2026-07-11-actionable",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            summary="actionable note",
            status=NoteStatus.ACTIONABLE,
        )
        tmp_store.save(n2)

        discussions = tmp_store.list_all(status=NoteStatus.DISCUSSION)
        assert len(discussions) == 1
        assert discussions[0].id == sample_note.id

        actionables = tmp_store.list_all(status=NoteStatus.ACTIONABLE)
        assert len(actionables) == 1
        assert actionables[0].id == n2.id

    def test_list_filter_by_topic(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        n2 = ResearchNote(
            id="2026-07-11-other-topic",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.BOOK_READING,
            summary="book note",
        )
        tmp_store.save(n2)

        system_notes = tmp_store.list_all(topic=NoteTopic.SYSTEM_DESIGN)
        assert len(system_notes) == 1
        assert system_notes[0].id == sample_note.id

    def test_list_filter_by_tag(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        n2 = ResearchNote(
            id="2026-07-11-no-match",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            tags=["不匹配"],
            summary="no match",
        )
        tmp_store.save(n2)

        matched = tmp_store.list_all(tag="测试")
        assert len(matched) == 1
        assert matched[0].id == sample_note.id

    def test_delete(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        assert tmp_store.delete(sample_note.id) is True
        assert tmp_store.get(sample_note.id) is None

    def test_delete_missing(self, tmp_store):
        assert tmp_store.delete("nonexistent") is False

    def test_update_status(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        updated = tmp_store.update_status(sample_note.id, NoteStatus.ACTIONABLE)
        assert updated is not None
        assert updated.status == NoteStatus.ACTIONABLE

    def test_update_status_missing(self, tmp_store):
        assert tmp_store.update_status("nonexistent", NoteStatus.ACTIONABLE) is None

    def test_update_status_invalid(self, tmp_store, sample_note):
        tmp_store.save(sample_note)
        assert tmp_store.update_status(sample_note.id, "invalid") is None

    def test_slugify(self):
        assert NoteStore.slugify("高盛 做多 中国 AI") == "高盛-做多-中国-ai"
        assert NoteStore.slugify("Test with https://example.com URL") == "test-with-url"
        assert NoteStore.slugify("   spaces   ") == "spaces"
        long_text = "a" * 100
        assert len(NoteStore.slugify(long_text)) <= 60


# ------------------------------------------------------------------
# search
# ------------------------------------------------------------------


class TestNoteSearch:
    @pytest.fixture
    def tmp_search(self):
        """Create NoteSearch with temp db."""
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "test_notes.db"
            s = NoteSearch(db_path=db_path)
            s.create_tables()
            yield s
            s.close()

    def test_create_tables(self, tmp_search):
        assert tmp_search.count() == 0

    def test_index_and_search(self, tmp_search, sample_note):
        tmp_search.index(sample_note)
        assert tmp_search.count() == 1

        results = tmp_search.search("测试")
        assert len(results) >= 1
        assert results[0]["note_id"] == sample_note.id

    def test_search_no_results(self, tmp_search):
        results = tmp_search.search("不存在的关键词")
        assert results == []

    def test_search_simple_fallback(self, tmp_search, sample_note):
        tmp_search.index(sample_note)
        results = tmp_search.search_simple("测试笔记")
        assert len(results) >= 1
        assert results[0]["note_id"] == sample_note.id

    def test_index_all(self, tmp_search, sample_note):
        n2 = ResearchNote(
            id="2026-07-11-second",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.BOOK_READING,
            summary="second note",
        )
        tmp_search.index_all([sample_note, n2])
        assert tmp_search.count() == 2

    def test_remove(self, tmp_search, sample_note):
        tmp_search.index(sample_note)
        assert tmp_search.count() == 1
        tmp_search.remove(sample_note.id)
        assert tmp_search.count() == 0

    def test_search_by_status(self, tmp_search, sample_note):
        tmp_search.index(sample_note)
        results = tmp_search.search("测试", status=NoteStatus.DISCUSSION)
        assert len(results) >= 1
        # should not find with wrong status filter
        results2 = tmp_search.search("测试", status=NoteStatus.IMPLEMENTED)
        assert len(results2) == 0


# ------------------------------------------------------------------
# repl
# ------------------------------------------------------------------


class TestNotesRepl:
    """Tests for the interactive notes REPL in src.cli."""

    @pytest.fixture
    def tmp_repl_search(self):
        """Create NoteSearch with temp db for REPL tests."""
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "repl_notes.db"
            s = NoteSearch(db_path=db_path)
            s.create_tables()
            yield s
            s.close()

    def _run_with_inputs(
        self,
        monkeypatch,
        inputs: list[str],
        tmp_store: NoteStore,
        tmp_repl_search: NoteSearch,
    ) -> None:
        """Run the REPL with a canned input sequence."""
        from src.cli import _run_notes_repl

        it = iter(inputs)
        monkeypatch.setattr("builtins.input", lambda _: next(it))
        _run_notes_repl(tmp_store, tmp_repl_search)

    def test_help_and_quit(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = ["help", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "add / a" in captured.out
        assert "list / ls" in captured.out
        assert "已退出笔记模式" in captured.out

    def test_add_note_interactive(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = [
            "add",
            "1",  # topic: first in sorted list
            "tag1, tag2",
            "对话",
            "test summary",
            "point one",
            "point two",
            "",  # end key points
            "discussion line",
            "",  # end discussion
            "quit",
        ]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "笔记已保存" in captured.out

        notes = tmp_store.list_all()
        assert len(notes) == 1
        assert notes[0].summary == "test summary"
        assert notes[0].tags == ["tag1", "tag2"]
        assert notes[0].key_points == ["point one", "point two"]
        assert "discussion line" in notes[0].full_discussion

    def test_list_notes(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        note = ResearchNote(
            id="2026-07-11-list-test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            summary="listable note",
        )
        tmp_store.save(note)
        tmp_repl_search.index(note)

        inputs = ["list", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "listable note" in captured.out

    def test_search_notes(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        note = ResearchNote(
            id="2026-07-11-search-test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            summary="searchable note content",
            full_discussion="unique keyword xyz123",
        )
        tmp_store.save(note)
        tmp_repl_search.index(note)

        inputs = ["search xyz123", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "searchable note content" in captured.out

    def test_promote_note(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        note = ResearchNote(
            id="2026-07-11-promote-test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            summary="promote me",
        )
        tmp_store.save(note)
        tmp_repl_search.index(note)

        inputs = ["promote 2026-07-11-promote-test --status actionable", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "笔记状态已更新" in captured.out

        updated = tmp_store.get("2026-07-11-promote-test")
        assert updated.status == NoteStatus.ACTIONABLE

    def test_delete_note(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        note = ResearchNote(
            id="2026-07-11-delete-test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            topic=NoteTopic.OTHER,
            summary="delete me",
        )
        tmp_store.save(note)
        tmp_repl_search.index(note)

        inputs = ["delete 2026-07-11-delete-test", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "笔记已删除" in captured.out
        assert tmp_store.get("2026-07-11-delete-test") is None

    def test_unknown_command(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = ["foobar", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "未知命令" in captured.out

    def test_reject_path_traversal_id(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = ["show ../../etc/passwd", "delete ../../../secrets", "promote bad--id --status actionable", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "笔记 ID 格式无效" in captured.out

    def test_empty_search_query(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = ["search", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "请输入搜索关键词" in captured.out

    def test_topics_command(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        inputs = ["topics", "quit"]
        self._run_with_inputs(monkeypatch, inputs, tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        for topic in NoteTopic.ALL:
            assert topic in captured.out

    def test_add_cancel_by_keyboard_interrupt(self, monkeypatch, tmp_store, tmp_repl_search, capsys):
        responses = iter(["add", "1", "tag", "对话", "summary"])

        def _raising_input(_prompt: str = ""):
            try:
                return next(responses)
            except StopIteration:
                raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _raising_input)
        from src.cli import _run_notes_repl

        _run_notes_repl(tmp_store, tmp_repl_search)
        captured = capsys.readouterr()
        assert "取消添加" in captured.out
        assert tmp_store.list_all() == []
