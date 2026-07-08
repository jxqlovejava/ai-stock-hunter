# -*- coding: utf-8 -*-
"""SQLite 持久化适配器 — 为 position_state 和 trade_tracker 提供 SQLite 存储。

SQLite 相比 JSON 的优势:
  - 原子写入（WAL 模式，崩溃安全）
  - 并发读（WAL 模式）
  - 数据校验（类型约束）
  - 支持 SQL 查询（不用全量加载）

用法:
    store = SQLiteStore("data/positions.db")
    store.upsert("position_states", {"symbol": "000001", "state_json": "{...}"})
    rows = store.select_all("position_states")
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SQLiteStore:
    """通用 SQLite 键值存储。

    每个表至少包含:
      - symbol TEXT PRIMARY KEY (或 id INTEGER PRIMARY KEY AUTOINCREMENT)
      - 业务列
      - updated_at TEXT (ISO 时间戳)
    """

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL，自动重连。"""
        try:
            return self.conn.execute(sql, params)
        except sqlite3.ProgrammingError:
            self._conn = None
            return self.conn.execute(sql, params)

    def upsert(
        self, table: str, data: dict, pk_col: str = "symbol",
    ) -> None:
        """插入或更新一行。

        Args:
            table: 表名
            data: 列名→值的字典
            pk_col: 主键列名
        """
        columns = list(data.keys())
        placeholders = ", ".join(["?" for _ in columns])
        col_names = ", ".join(columns)

        # SQLite UPSERT: INSERT ... ON CONFLICT DO UPDATE
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in columns if c != pk_col)

        sql = (
            f"INSERT INTO {table} ({col_names}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT({pk_col}) DO UPDATE SET {set_clause}"
        )

        values = tuple(data.get(c) for c in columns)
        self.execute(sql, values)
        self.conn.commit()

    def select_one(self, table: str, key: str, pk_col: str = "symbol") -> Optional[dict]:
        """按主键查询单行。"""
        rows = self.execute(
            f"SELECT * FROM {table} WHERE {pk_col}=?", (key,)
        ).fetchall()
        if not rows:
            return None
        return dict(rows[0])

    def select_all(self, table: str) -> list[dict]:
        """查询全表。"""
        rows = self.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(r) for r in rows]

    def delete(self, table: str, key: str, pk_col: str = "symbol") -> bool:
        """删除一行。"""
        cursor = self.execute(
            f"DELETE FROM {table} WHERE {pk_col}=?", (key,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def count(self, table: str) -> int:
        """返回表行数。"""
        row = self.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
        return int(row["cnt"]) if row else 0

    def table_exists(self, table: str) -> bool:
        """检查表是否存在。"""
        row = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None


# ------------------------------------------------------------------
# 预定义表结构
# ------------------------------------------------------------------

def init_position_states_table(store: SQLiteStore) -> None:
    """创建 position_states 表。"""
    store.execute("""
        CREATE TABLE IF NOT EXISTS position_states (
            symbol TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    store.conn.commit()


def init_trade_records_table(store: SQLiteStore) -> None:
    """创建 trade_records 表。"""
    store.execute("""
        CREATE TABLE IF NOT EXISTS trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            exit_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            shares INTEGER NOT NULL DEFAULT 0,
            direction TEXT NOT NULL DEFAULT 'LONG',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    store.conn.commit()
    # 按标的和时间查询索引
    store.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_symbol "
        "ON trade_records(symbol)"
    )
    store.conn.commit()
