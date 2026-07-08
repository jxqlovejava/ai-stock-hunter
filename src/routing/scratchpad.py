# -*- coding: utf-8 -*-
"""分析草稿本 — 全链路事件的 JSONL 持久化。

AnalysisScratchpad 将管道中每个阶段的事件以 JSONL 格式持久化到磁盘，
支持事后审计、调试回放和去重检测。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.routing.events import (
    AnalysisEvent,
    DataFetchEvent,
    PipelineCompletedEvent,
    StageCompletedEvent,
    StageErrorEvent,
    StageEvent,
    StageStartedEvent,
)


class AnalysisScratchpad:
    """分析草稿本 — 事件持久化与去重检查。

    使用方式:
        pad = AnalysisScratchpad("600519")
        pad.add_stage_start("军规校验")
        pad.add_stage_end("军规校验", "通过 (31/31)", [])
        pad.close()
    """

    def __init__(self, symbol: str, output_dir: str = "output/scratchpad/"):
        """初始化草稿本。

        Args:
            symbol: 股票代码
            output_dir: 输出目录, 默认为 output/scratchpad/
        """
        self.symbol = symbol
        self.timestamp = datetime.now()
        self._closed = False

        # 构建输出文件路径
        ts_str = self.timestamp.strftime("%Y%m%d_%H%M%S")
        base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = base_dir / f"{symbol}_{ts_str}.jsonl"
        self._file_handle = open(self._file_path, "a", encoding="utf-8")  # noqa: SIM115

    @property
    def file_path(self) -> str:
        """草稿本 JSONL 文件的绝对路径。"""
        return os.path.abspath(self._file_path)

    # -----------------------------------------------------------------------
    # 写操作
    # -----------------------------------------------------------------------

    def add_event(self, event_type: str, data: dict) -> None:
        """添加一条通用事件记录。

        Args:
            event_type: 事件类型标识
            data: 事件数据字典
        """
        if self._closed:
            return
        record = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        self._file_handle.write(line + "\n")
        self._file_handle.flush()

    def add_stage_start(self, stage_name: str) -> None:
        """记录阶段开始。

        Args:
            stage_name: 阶段名称, 如 "军规校验" / "多维诊断"
        """
        self.add_event("stage_start", {
            "stage_name": stage_name,
        })

    def add_stage_end(
        self,
        stage_name: str,
        result_summary: str,
        warnings: list[str] | None = None,
    ) -> None:
        """记录阶段结束。

        Args:
            stage_name: 阶段名称
            result_summary: 结果摘要
            warnings: 警告列表
        """
        self.add_event("stage_end", {
            "stage_name": stage_name,
            "result_summary": result_summary,
            "warnings": warnings or [],
        })

    def record_event(self, event: StageEvent) -> None:
        """将 StageEvent 子类写入草稿本。

        Args:
            event: 任意 StageEvent 子类实例
        """
        self.add_event(event.discriminator, event.to_dict())

    # -----------------------------------------------------------------------
    # 读操作
    # -----------------------------------------------------------------------

    def get_stage_results(self) -> list[dict]:
        """读取草稿本中所有按阶段分组的记录。

        Returns:
            每条记录包含 event_type, timestamp, data 的列表
        """
        results: list[dict] = []
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except (FileNotFoundError, OSError):
            return results
        return results

    def get_stage_summary(self) -> dict[str, list[dict]]:
        """按 stage_name 分组返回所有阶段记录。

        Returns:
            {stage_name: [start_record, end_record]}
        """
        summary: dict[str, list[dict]] = {}
        for record in self.get_stage_results():
            data = record.get("data", {})
            stage_name = data.get("stage_name", "__unknown__")
            summary.setdefault(stage_name, []).append(record)
        return summary

    # -----------------------------------------------------------------------
    # 去重检测
    # -----------------------------------------------------------------------

    def dedup_check(self, query_signature: str) -> bool:
        """检测查询签名是否与草稿本中已有记录高度重复。

        使用 Jaccard 相似度 (基于字符 bigram)，
        阈值 0.85 以上视为重复。

        Args:
            query_signature: 查询标识字符串 (如用户原始 query 或规范化签名)

        Returns:
            True 如果检测到重复 (相似度 >= 0.85)
        """
        if not query_signature:
            return False

        query_bigrams = self._to_bigram_set(query_signature.lower())
        if not query_bigrams:
            return False

        for record in self.get_stage_results():
            data = record.get("data", {})
            # 从 summary、stage_name、result_summary 等字段中提取签名
            candidates = [
                data.get("result_summary", ""),
                data.get("stage_name", ""),
                str(data.get("warnings", "")),
            ]
            for candidate in candidates:
                if not candidate:
                    continue
                similarity = self._jaccard_similarity(
                    query_bigrams,
                    self._to_bigram_set(candidate.lower()),
                )
                if similarity >= 0.85:
                    return True
        return False

    # -----------------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------------

    def close(self) -> None:
        """关闭草稿本文件句柄，标记为已关闭。"""
        if self._closed:
            return
        try:
            self._file_handle.close()
        except Exception:
            pass
        self._closed = True

    def __enter__(self) -> "AnalysisScratchpad":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -----------------------------------------------------------------------
    # 内部工具
    # -----------------------------------------------------------------------

    @staticmethod
    def _to_bigram_set(text: str) -> set[tuple[str, str]]:
        """将字符串转为字符 bigram 集合用于 Jaccard 计算。"""
        if len(text) < 2:
            return {(text, "")}
        return {(text[i], text[i + 1]) for i in range(len(text) - 1)}

    @staticmethod
    def _jaccard_similarity(a: set, b: set) -> float:
        """计算两个集合的 Jaccard 相似度。"""
        if not a or not b:
            return 0.0
        intersection = a & b
        union = a | b
        return len(intersection) / len(union)
