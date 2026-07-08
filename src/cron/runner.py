# -*- coding: utf-8 -*-
"""JobRunner — 后台线程定时任务执行器。

核心循环:
  1. tick() 从 JobStore 加载所有任务
  2. 对每个任务调用 JobScheduler.is_due() 判断
  3. 到期的任务送入 execute_job()
  4. 执行结果回调 on_complete()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Set

from .executor import JobExecutor
from .schedule import JobScheduler
from .store import JobStore
from .types import CronJob, JobResult, JobState

logger = logging.getLogger(__name__)

# 默认 tick 间隔（秒）
_DEFAULT_TICK_INTERVAL = 60


class JobRunner:
    """后台线程任务运行器。

    用法:
        runner = JobRunner(store, scheduler, executor)
        runner.start()           # 启动后台线程
        ...
        runner.stop()            # 停止

    也可以手动 tick():
        runner.tick()            # 单次到期检查
    """

    def __init__(
        self,
        store: JobStore,
        scheduler: JobScheduler,
        executor: JobExecutor,
        tick_interval: int = _DEFAULT_TICK_INTERVAL,
        on_complete: Optional[Callable[[CronJob, JobResult], None]] = None,
    ) -> None:
        self._store = store
        self._scheduler = scheduler
        self._executor = executor
        self._tick_interval = tick_interval
        self._on_complete = on_complete

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 正在运行的任务 ID 集合（去重）
        self._running: Set[str] = set()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """在后台线程中启动 tick 循环。"""
        if self._thread and self._thread.is_alive():
            logger.warning("JobRunner already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="job-runner",
            daemon=True,
        )
        self._thread.start()
        logger.info("JobRunner started (tick=%ds).", self._tick_interval)

    def stop(self) -> None:
        """停止后台线程。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            logger.info("JobRunner stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def running_jobs(self) -> list[str]:
        """当前正在运行的任务 ID 列表。"""
        with self._lock:
            return list(self._running)

    # ------------------------------------------------------------------
    # 内部循环
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """后台线程主循环。"""
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Error in runner tick.")

            # 等间隔，但可被 stop() 中断
            self._stop_event.wait(timeout=self._tick_interval)

    # ------------------------------------------------------------------
    # 单次 tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """单次到期检查：加载任务、判断到期、执行。"""
        jobs = self._store.load_jobs()
        now = self._scheduler.now()

        for job in jobs:
            if not self._should_run(job, now):
                continue

            logger.info("Job due: %s (%s) — %s", job.id, job.name, job.payload)
            result = self.execute_job(job)

            if self._on_complete:
                try:
                    self._on_complete(job, result)
                except Exception:
                    logger.exception("on_complete callback failed for job %s", job.id)

    def _should_run(self, job: CronJob, now: datetime) -> bool:
        """判断任务是否可以执行（去重+到期）。"""
        if not job.enabled or job.state != JobState.ACTIVE:
            return False
        # 去重
        with self._lock:
            if job.id in self._running:
                logger.debug("Job %s already running, skip.", job.id)
                return False
        # 到期判断
        return self._scheduler.is_due(job, now)

    # ------------------------------------------------------------------
    # 执行单个任务
    # ------------------------------------------------------------------

    def execute_job(self, job: CronJob) -> JobResult:
        """执行单个任务并更新状态。

        此方法同步执行，调用方负责线程安全。
        """
        with self._lock:
            self._running.add(job.id)

        start = time.monotonic()
        try:
            stdout, stderr, returncode = self._executor.run_command(job.payload)
            elapsed_ms = (time.monotonic() - start) * 1000

            success = returncode == 0

            result = JobResult(
                job_id=job.id,
                success=success,
                output=stdout,
                error=stderr if not success else "",
                duration_ms=round(elapsed_ms, 1),
            )

            # 更新任务状态
            now_iso = datetime.now(timezone.utc).isoformat()
            updates: dict[str, object] = {
                "last_run_at": now_iso,
            }

            if success:
                updates["error_count"] = 0
                if job.fulfillment == "once":
                    updates["state"] = JobState.COMPLETED
                    updates["enabled"] = False
            else:
                new_count = job.error_count + 1
                updates["error_count"] = new_count
                if new_count >= job.max_errors:
                    updates["state"] = JobState.ERROR
                    logger.warning("Job %s disabled after %d errors.",
                                   job.id, new_count)

            # 更新 next_run_at
            next_str = self._scheduler.next_run(job)
            updates["next_run_at"] = next_str

            self._store.update_job(job.id, updates)

            # 同步日志
            status = "OK" if success else f"FAIL (code={returncode})"
            logger.info("Job %s %s in %.0fms", job.id, status, elapsed_ms)

            return result

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("Unexpected error executing job %s", job.id)
            return JobResult(
                job_id=job.id,
                success=False,
                error=str(exc),
                duration_ms=round(elapsed_ms, 1),
            )
        finally:
            with self._lock:
                self._running.discard(job.id)
