"""轻量级交互日志 — JSONL 追加写入，零依赖。

每行一条 JSON 记录：
  {"timestamp": "...", "command": "...", "args": [...], "summary": "...", "duration_ms": 123, "exit_code": 0}

长输出自动截断：保留前 500 字符 + 尾部 200 字符，清除 ANSI 转义码。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class InteractionLogger:
    """Append-only JSONL interaction log."""

    _MAX_PREFIX = 500
    _MAX_SUFFIX = 200

    def __init__(self, log_path: str | None = None) -> None:
        self.log_path = Path(
            log_path or Path(__file__).parent.parent.parent / "data" / "interaction_log.jsonl"
        ).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def log(
        self,
        command: str,
        args: list[str] | None = None,
        output: str = "",
        exit_code: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Append one interaction record."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "args": args or [],
            "summary": self._summarize(output),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def tail(self, n: int = 20) -> list[dict]:
        """Return the last N log entries."""
        lines = self._read_lines()
        return lines[-n:] if len(lines) > n else lines

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """Search log entries by keyword (case-insensitive)."""
        kw = keyword.lower()
        results: list[dict] = []
        for entry in reversed(self._read_lines()):
            if len(results) >= limit:
                break
            text = json.dumps(entry, ensure_ascii=False).lower()
            if kw in text:
                results.append(entry)
        return list(reversed(results))

    def recent_commands(self, n: int = 50) -> list[str]:
        """Return unique recent command names for analytics."""
        seen: set[str] = set()
        cmds: list[str] = []
        for entry in reversed(self._read_lines()):
            cmd = entry.get("command", "")
            if cmd not in seen:
                seen.add(cmd)
                cmds.append(cmd)
            if len(cmds) >= n:
                break
        return list(reversed(cmds))

    def stats(self) -> dict:
        """Basic usage statistics."""
        lines = self._read_lines()
        if not lines:
            return {"total": 0, "commands": {}}
        cmd_counts: dict[str, int] = {}
        total_duration = 0
        errors = 0
        for entry in lines:
            cmd = entry.get("command", "unknown")
            cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1
            total_duration += entry.get("duration_ms", 0)
            if entry.get("exit_code", 0) != 0:
                errors += 1
        return {
            "total": len(lines),
            "errors": errors,
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration // len(lines) if lines else 0,
            "top_commands": sorted(cmd_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _read_lines(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        entries: list[dict] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    @classmethod
    def _summarize(cls, text: str) -> str:
        """Truncate long output: prefix + suffix, strip ANSI codes."""
        if not text:
            return ""
        # strip ANSI escape codes
        clean = cls._strip_ansi(text).strip()
        if len(clean) <= cls._MAX_PREFIX + cls._MAX_SUFFIX + 50:
            return clean
        prefix = clean[:cls._MAX_PREFIX]
        suffix = clean[-cls._MAX_SUFFIX:]
        return f"{prefix}\n... [truncated {len(clean) - cls._MAX_PREFIX - cls._MAX_SUFFIX} chars] ...\n{suffix}"

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Remove ANSI escape sequences and emoji-rich formatting."""
        # ANSI CSI sequences
        ansi = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
        return ansi.sub("", text)
