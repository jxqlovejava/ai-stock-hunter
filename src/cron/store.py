# -*- coding: utf-8 -*-
"""JobStore — 基于 JSON 文件的定时任务持久化。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from .types import CronJob

logger = logging.getLogger(__name__)


def _default_jobs_path() -> Path:
    """默认 jobs 文件路径: ~/.baize/cron/jobs.json"""
    return Path.home() / ".baize" / "cron" / "jobs.json"


class JobStore:
    """持久化 Job 存储。

    使用 JSON 文件存储任务列表。文件路径可通过环境变量 CRON_JOBS_FILE 覆盖。
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        if file_path:
            self._path = Path(file_path)
        else:
            self._path = Path(
                os.environ.get("CRON_JOBS_FILE", str(_default_jobs_path()))
            )
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """确保父目录存在。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(job: CronJob) -> dict:
        d = {
            "id": job.id,
            "name": job.name,
            "enabled": job.enabled,
            "schedule_type": job.schedule_type,
            "schedule_value": job.schedule_value,
            "payload": job.payload,
            "fulfillment": job.fulfillment,
            "state": job.state,
            "active_window_start": job.active_window_start,
            "active_window_end": job.active_window_end,
            "active_days": job.active_days,
            "error_count": job.error_count,
            "max_errors": job.max_errors,
            "created_at": job.created_at,
            "last_run_at": job.last_run_at,
            "next_run_at": job.next_run_at,
        }
        # 清理 None 值（让 JSON 更干净）
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _from_dict(data: dict) -> CronJob:
        return CronJob(
            id=data.get("id", ""),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            schedule_type=data.get("schedule_type", "cron"),
            schedule_value=data.get("schedule_value", "0 9 * * 1-5"),
            payload=data.get("payload", ""),
            fulfillment=data.get("fulfillment", "keep"),
            state=data.get("state", "active"),
            active_window_start=data.get("active_window_start"),
            active_window_end=data.get("active_window_end"),
            active_days=data.get("active_days"),
            error_count=data.get("error_count", 0),
            max_errors=data.get("max_errors", 5),
            created_at=data.get("created_at", ""),
            last_run_at=data.get("last_run_at"),
            next_run_at=data.get("next_run_at"),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def load_jobs(self) -> list[CronJob]:
        """从 JSON 文件加载所有任务。"""
        if not self._path.exists():
            logger.info("Jobs file not found, returning empty list: %s", self._path)
            return []

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                logger.warning("Invalid jobs file format, resetting to empty.")
                return []
            return [self._from_dict(item) for item in data]
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load jobs file: %s", exc)
            return []

    def save_jobs(self, jobs: list[CronJob]) -> None:
        """将任务列表写入 JSON 文件。"""
        try:
            raw = json.dumps(
                [self._to_dict(j) for j in jobs],
                ensure_ascii=False,
                indent=2,
            )
            self._path.write_text(raw, encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save jobs: %s", exc)

    def add_job(self, job: CronJob) -> None:
        """添加新任务。"""
        jobs = self.load_jobs()
        jobs.append(job)
        self.save_jobs(jobs)

    def update_job(self, job_id: str, updates: dict) -> bool:
        """更新指定任务的部分字段。返回 True 表示找到并更新。"""
        jobs = self.load_jobs()
        for i, job in enumerate(jobs):
            if job.id == job_id:
                for key, value in updates.items():
                    if hasattr(job, key):
                        setattr(jobs[i], key, value)
                self.save_jobs(jobs)
                return True
        logger.warning("Job %s not found for update.", job_id)
        return False

    def remove_job(self, job_id: str) -> bool:
        """删除指定任务。返回 True 表示找到并删除。"""
        jobs = self.load_jobs()
        before = len(jobs)
        jobs = [j for j in jobs if j.id != job_id]
        if len(jobs) < before:
            self.save_jobs(jobs)
            return True
        logger.warning("Job %s not found for removal.", job_id)
        return False
