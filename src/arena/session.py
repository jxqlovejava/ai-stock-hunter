# -*- coding: utf-8 -*-
"""内部策略竞技场 — 会话持久化。

ArenaSessionStore 负责 ArenaSession 的 JSON 序列化/反序列化，
支持 save / load / list / delete / compare_sessions。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .models import ArenaSession

logger = logging.getLogger(__name__)


class ArenaSessionStore:
    """竞技场会话持久化存储。

    每个 session 保存为独立的 JSON 文件：
        data/arena_sessions/<session_id>.json
    """

    DEFAULT_DIR = Path("data/arena_sessions")

    def __init__(self, storage_dir: Optional[Path] = None):
        self._dir = Path(storage_dir) if storage_dir else self.DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, session: ArenaSession) -> str:
        """保存会话到 JSON 文件，返回文件路径。"""
        filepath = self._filepath(session.session_id)
        try:
            data = session.to_dict()
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Arena session saved: %s", filepath)
        except (TypeError, OSError) as e:
            logger.warning("Failed to save arena session %s: %s", session.session_id, e)
        return str(filepath)

    def load(self, session_id: str) -> Optional[ArenaSession]:
        """从 JSON 文件加载会话。"""
        filepath = self._filepath(session_id)
        if not filepath.exists():
            logger.warning("Session not found: %s", session_id)
            return None
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return ArenaSession.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("Corrupted session file %s: %s", filepath, e)
            return None

    def delete(self, session_id: str) -> bool:
        """删除会话文件。"""
        filepath = self._filepath(session_id)
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        """列出所有会话的摘要信息。"""
        summaries = []
        for f in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                config = data.get("config", {})
                summaries.append({
                    "id": data.get("session_id", f.stem),
                    "created_at": data.get("created_at", ""),
                    "universe": config.get("universe_name", "?"),
                    "n_strategies": len(data.get("results", [])),
                    "winner": (
                        data["leaderboard"][0]["name"]
                        if data.get("leaderboard")
                        else "N/A"
                    ),
                    "n_insights": len(data.get("insights", [])),
                })
            except (json.JSONDecodeError, KeyError):
                summaries.append({
                    "id": f.stem,
                    "created_at": "?",
                    "universe": "?",
                    "n_strategies": 0,
                    "winner": "?",
                    "n_insights": 0,
                })
        return summaries

    def compare_sessions(
        self, session_ids: list[str]
    ) -> list[dict]:
        """跨会话对比 — 返回每个 session 中相同策略的指标变化。"""
        sessions = []
        for sid in session_ids:
            s = self.load(sid)
            if s:
                sessions.append(s)
        if len(sessions) < 2:
            return []

        # 按策略名分组
        by_name: dict[str, list[dict]] = {}
        for s in sessions:
            for r in s.results:
                if r.error:
                    continue
                by_name.setdefault(r.name, []).append({
                    "session_id": s.session_id,
                    "created_at": s.created_at,
                    "sharpe": r.sharpe_ratio,
                    "annual_return": r.annual_return_pct,
                    "max_drawdown": r.max_drawdown_pct,
                    "win_rate": r.win_rate_pct,
                })

        # 只保留出现在多个 session 中的策略
        result = []
        for name, records in by_name.items():
            if len(records) < 2:
                continue
            # 计算变化
            latest = records[0]
            previous = records[1]
            result.append({
                "strategy": name,
                "current": latest,
                "previous": previous,
                "sharpe_delta": latest["sharpe"] - previous["sharpe"],
                "return_delta": latest["annual_return"] - previous["annual_return"],
                "dd_delta": latest["max_drawdown"] - previous["max_drawdown"],
            })

        result.sort(key=lambda x: x["sharpe_delta"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _filepath(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"
