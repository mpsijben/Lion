"""In-memory + persisted async job registry for API pipeline runs."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JobResult, JobStatus, PipelineRequest, StreamEvent, StreamEventType


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobMetadata:
    """Internal mutable job state."""

    job_id: str
    status: JobStatus
    created_at: datetime
    prompt: str
    pipeline_expr: str | None = None
    provider: str | None = None
    context_mode: str | None = None
    lens: str | None = None
    cwd: str | None = None
    timeout_seconds: float | None = None
    config_overrides: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    output: dict[str, Any] | None = None
    shared_memory_path: str | None = None
    run_dir: str | None = None
    cost: float | None = None
    error: str | None = None
    cancel_requested: bool = False

    def to_job_result(self) -> JobResult:
        return JobResult(
            job_id=self.job_id,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            duration_seconds=self.duration_seconds,
            output=self.output,
            shared_memory_path=self.shared_memory_path,
            run_dir=self.run_dir,
            cost=self.cost,
            error=self.error,
            cancel_requested=self.cancel_requested,
            session_id=self.session_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "prompt": self.prompt,
            "pipeline_expr": self.pipeline_expr,
            "provider": self.provider,
            "context_mode": self.context_mode,
            "lens": self.lens,
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "config_overrides": self.config_overrides,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "output": self.output,
            "shared_memory_path": self.shared_memory_path,
            "run_dir": self.run_dir,
            "cost": self.cost,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobMetadata":
        return cls(
            job_id=str(data["job_id"]),
            status=JobStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            prompt=str(data.get("prompt", "")),
            pipeline_expr=data.get("pipeline_expr"),
            provider=data.get("provider"),
            context_mode=data.get("context_mode"),
            lens=data.get("lens"),
            cwd=data.get("cwd"),
            timeout_seconds=data.get("timeout_seconds"),
            config_overrides=data.get("config_overrides") or {},
            session_id=data.get("session_id"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            duration_seconds=data.get("duration_seconds"),
            output=data.get("output"),
            shared_memory_path=data.get("shared_memory_path"),
            run_dir=data.get("run_dir"),
            cost=data.get("cost"),
            error=data.get("error"),
            cancel_requested=bool(data.get("cancel_requested", False)),
        )


class JobStore:
    """Async-safe job storage with persistence and SSE fan-out."""

    def __init__(self, storage_dir: str | Path, ttl_seconds: int = 3600):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, JobMetadata] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[StreamEvent]]] = {}
        self._event_history: dict[str, list[StreamEvent]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def load_persisted(self) -> None:
        async with self._lock:
            for file in self.storage_dir.glob("*.json"):
                try:
                    data = json.loads(file.read_text())
                    job = JobMetadata.from_dict(data)
                    self._jobs[job.job_id] = job
                except Exception:
                    continue

    async def create_job(self, request: PipelineRequest, session_id: str | None = None) -> JobMetadata:
        job_id = uuid.uuid4().hex
        job = JobMetadata(
            job_id=job_id,
            status=JobStatus.QUEUED,
            created_at=utcnow(),
            prompt=request.prompt,
            pipeline_expr=request.pipeline_expr,
            provider=request.provider,
            context_mode=request.context_mode,
            lens=request.lens,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            config_overrides=request.config_overrides,
            session_id=session_id,
        )
        async with self._lock:
            self._jobs[job_id] = job
            self._persist_job(job)
        return job

    async def attach_task(self, job_id: str, task: asyncio.Task[Any]) -> None:
        async with self._lock:
            self._tasks[job_id] = task

    async def get_task(self, job_id: str) -> asyncio.Task[Any] | None:
        async with self._lock:
            return self._tasks.get(job_id)

    async def get_job(self, job_id: str) -> JobMetadata | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self, limit: int = 50) -> list[JobMetadata]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    async def mark_running(self, job_id: str) -> JobMetadata | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.status = JobStatus.RUNNING
            job.started_at = utcnow()
            self._persist_job(job)
            return job

    async def mark_cancel_requested(self, job_id: str) -> JobMetadata | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.cancel_requested = True
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                job.status = JobStatus.CANCELLED
                job.completed_at = utcnow()
                if job.started_at:
                    job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
            self._persist_job(job)
            return job

    async def set_result(
        self,
        job_id: str,
        *,
        status: JobStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        shared_memory_path: str | None = None,
        run_dir: str | None = None,
        cost: float | None = None,
    ) -> JobMetadata | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            # Preserve cancellation status as terminal outcome.
            if job.status == JobStatus.CANCELLED and status != JobStatus.CANCELLED:
                self._persist_job(job)
                return job

            job.status = status
            job.output = output
            job.error = error
            job.shared_memory_path = shared_memory_path
            job.run_dir = run_dir
            job.cost = cost
            job.completed_at = utcnow()
            if not job.started_at:
                job.started_at = job.created_at
            job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
            self._persist_job(job)
            return job

    async def publish_event(self, job_id: str, event_type: StreamEventType, data: dict[str, Any]) -> None:
        event = StreamEvent(event_type=event_type, timestamp=utcnow(), data=data)
        async with self._lock:
            history = self._event_history.setdefault(job_id, [])
            history.append(event)
            if len(history) > 1000:
                del history[: len(history) - 1000]

            for queue in list(self._subscribers.get(job_id, set())):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    continue

    def publish_event_threadsafe(self, job_id: str, event_type: StreamEventType, data: dict[str, Any]) -> None:
        if self._loop is None:
            return

        def _schedule() -> None:
            asyncio.create_task(self.publish_event(job_id, event_type, data))

        self._loop.call_soon_threadsafe(_schedule)

    async def get_event_history(self, job_id: str) -> list[StreamEvent]:
        async with self._lock:
            return list(self._event_history.get(job_id, []))

    async def subscribe(self, job_id: str) -> asyncio.Queue[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[StreamEvent]) -> None:
        async with self._lock:
            queues = self._subscribers.get(job_id)
            if not queues:
                return
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(job_id, None)

    async def cleanup_expired(self) -> int:
        """Remove terminal jobs older than TTL."""
        now = utcnow()
        removed = 0
        async with self._lock:
            expired_ids = []
            for job_id, job in self._jobs.items():
                if job.status not in TERMINAL_STATUSES:
                    continue
                reference = job.completed_at or job.created_at
                age = (now - reference).total_seconds()
                if age > self.ttl_seconds:
                    expired_ids.append(job_id)

            for job_id in expired_ids:
                self._jobs.pop(job_id, None)
                self._tasks.pop(job_id, None)
                self._event_history.pop(job_id, None)
                self._subscribers.pop(job_id, None)
                path = self.storage_dir / f"{job_id}.json"
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
                removed += 1
        return removed

    async def cleanup_worker(self, stop_event: asyncio.Event, interval_seconds: int = 300) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                await self.cleanup_expired()

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _persist_job(self, job: JobMetadata) -> None:
        path = self.storage_dir / f"{job.job_id}.json"
        path.write_text(json.dumps(job.to_dict(), indent=2))
