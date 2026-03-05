"""Pydantic models for the Lion REST API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Execution state for asynchronous pipeline jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StreamEventType(str, Enum):
    """SSE stream event types."""

    START = "start"
    PHASE = "phase"
    OUTPUT = "output"
    ERROR = "error"
    COMPLETE = "complete"


class PipelineRequest(BaseModel):
    """Request body for pipeline execution."""

    prompt: str = Field(..., min_length=1, description="Task prompt to execute")
    pipeline_expr: str | None = Field(
        default=None,
        description="Optional pipeline expression, e.g. 'pride(3) -> review()'",
    )
    provider: str | None = Field(default=None, description="Optional provider override")
    context_mode: str | None = Field(
        default=None,
        description="Context mode override: minimal|standard|rich|auto",
    )
    lens: str | None = Field(default=None, description="Optional lens shortcode")
    cwd: str | None = Field(default=None, description="Working directory for execution")
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Optional per-job timeout in seconds",
    )
    config_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Deep-merged config overrides for this request",
    )


class PipelineResponse(BaseModel):
    """Async execution acknowledgement."""

    job_id: str
    status: JobStatus
    created_at: datetime


class JobResult(BaseModel):
    """Job state/result payload for polling endpoints."""

    job_id: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    output: dict[str, Any] | None = None
    shared_memory_path: str | None = None
    run_dir: str | None = None
    cost: float | None = None
    error: str | None = None
    cancel_requested: bool = False
    session_id: str | None = None


class StreamEvent(BaseModel):
    """Serialized SSE event payload."""

    event_type: StreamEventType
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(BaseModel):
    """Create a new API session."""

    provider: str | None = None
    initial_context: str | None = None
    cwd: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SessionExecuteRequest(BaseModel):
    """Run a pipeline request inside an API session."""

    prompt: str = Field(..., min_length=1)
    pipeline_expr: str | None = None
    provider: str | None = None
    context_mode: str | None = None
    lens: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    config_overrides: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    """Session state response."""

    session_id: str
    created_at: datetime
    last_active: datetime
    history_count: int
    provider: str | None = None


class ApiErrorResponse(BaseModel):
    """Consistent error schema for DX-friendly API failures."""

    error_code: str
    message: str
    detail: str | None = None


class FunctionsResponse(BaseModel):
    """Available pipeline functions."""

    functions: list[str]


class ProvidersResponse(BaseModel):
    """Configured and available providers."""

    default_provider: str | None = None
    available: list[str]
    configured: list[str]


class PipelinesListResponse(BaseModel):
    """Recent pipeline runs."""

    jobs: list[JobResult]
