"""Pipeline execution orchestration for asynchronous API jobs."""

from __future__ import annotations

import asyncio
import copy
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from lion import display as display_module
from lion.display import Display
from lion.functions import FUNCTIONS
from lion.lenses import get_lens
from lion.parser import parse_lion_input
from lion.pipeline import PipelineExecutor
from lion.providers import is_provider_name

from .errors import ApiError, PipelineValidationError
from .job_store import JobStore
from .models import JobStatus, PipelineRequest, StreamEventType
from .session_store import SessionStore


_CONTEXT_MODES = {"minimal", "standard", "rich", "auto"}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_capture_local = threading.local()
_hook_lock = threading.Lock()
_hooks_installed = False


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _set_current_job(job_id: str | None) -> None:
    _capture_local.job_id = job_id


def _get_current_job() -> str | None:
    return getattr(_capture_local, "job_id", None)


def install_display_hooks(store: JobStore) -> None:
    """Install one-time display hooks to convert terminal output into SSE events."""
    global _hooks_installed

    with _hook_lock:
        if _hooks_installed:
            return

        original_print = display_module._print

        def patched_print(message):
            job_id = _get_current_job()
            if job_id:
                text = _strip_ansi(str(message)).strip()
                if text:
                    store.publish_event_threadsafe(
                        job_id,
                        StreamEventType.OUTPUT,
                        {"message": text},
                    )
            return original_print(message)

        display_module._print = patched_print

        _patch_display_method(store, "pipeline_start", StreamEventType.START, lambda args, _: {
            "prompt": args[0],
            "steps": len(args[1]),
        })
        _patch_display_method(store, "phase", StreamEventType.PHASE, lambda args, _: {
            "name": args[0],
            "description": args[1],
        })
        _patch_display_method(store, "step_error", StreamEventType.ERROR, lambda args, _: {
            "step": args[0],
            "error": args[1],
        })
        _patch_display_method(store, "error", StreamEventType.ERROR, lambda args, _: {
            "error": args[0],
        })
        _patch_display_method(store, "cancelled", StreamEventType.COMPLETE, lambda _args, _kwargs: {
            "status": "cancelled",
        })

        _hooks_installed = True


def _patch_display_method(
    store: JobStore,
    name: str,
    event_type: StreamEventType,
    payload_builder,
) -> None:
    original = getattr(Display, name)

    def wrapper(*args, **kwargs):
        job_id = _get_current_job()
        if job_id:
            try:
                payload = payload_builder(args, kwargs)
            except Exception:
                payload = {}
            store.publish_event_threadsafe(job_id, event_type, payload)
        return original(*args, **kwargs)

    setattr(Display, name, staticmethod(wrapper))


def _validate_balanced_syntax(text: str) -> None:
    quote_char = None
    for idx, char in enumerate(text):
        if char in ('"', "'"):
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
    if quote_char:
        raise PipelineValidationError(
            "Invalid pipeline syntax",
            "Unclosed quote in pipeline expression",
        )

    parens = 0
    for idx, char in enumerate(text):
        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
            if parens < 0:
                raise PipelineValidationError(
                    "Invalid pipeline syntax",
                    f"Unmatched ')' near position {idx + 1}",
                )

    if parens != 0:
        raise PipelineValidationError(
            "Invalid pipeline syntax",
            "Unbalanced parentheses in pipeline expression",
        )


def validate_request(request: PipelineRequest, config: dict[str, Any]) -> tuple[str, list[Any]]:
    """Validate request and parse prompt/steps with clear DX errors."""
    prompt = request.prompt.strip()
    if not prompt:
        raise PipelineValidationError("Prompt is required")

    pipeline_expr = request.pipeline_expr.strip() if request.pipeline_expr else ""

    if request.provider and not is_provider_name(request.provider):
        raise ApiError(
            400,
            "invalid_provider",
            f"Unknown provider '{request.provider}'",
            "Use one of: claude, gemini, codex (optionally with model suffix)",
        )

    if request.context_mode and request.context_mode not in _CONTEXT_MODES:
        raise ApiError(
            400,
            "invalid_context_mode",
            f"Unsupported context_mode '{request.context_mode}'",
            "Allowed values: minimal, standard, rich, auto",
        )

    if pipeline_expr:
        _validate_balanced_syntax(pipeline_expr)
        try:
            _, steps = parse_lion_input(f'"_api_prompt_" -> {pipeline_expr}', config)
        except Exception as exc:
            raise PipelineValidationError(
                "Invalid pipeline syntax",
                str(exc),
            ) from exc
        if not steps:
            raise PipelineValidationError(
                "Invalid pipeline syntax",
                "No executable steps found in pipeline_expr",
            )
    else:
        # Allow full inline syntax in prompt for convenience.
        try:
            parsed_prompt, steps = parse_lion_input(prompt, config)
            prompt = parsed_prompt
        except Exception as exc:
            raise PipelineValidationError(
                "Invalid pipeline syntax",
                str(exc),
            ) from exc

    unknown = [s.function for s in steps if s.function not in FUNCTIONS and s.function != "__pattern__"]
    if unknown:
        raise PipelineValidationError(
            "Unknown pipeline function",
            f"Unknown function(s): {', '.join(sorted(set(unknown)))}",
        )

    return prompt, steps


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _build_effective_config(base_config: dict[str, Any], request: PipelineRequest) -> dict[str, Any]:
    config = _deep_merge(base_config, request.config_overrides)
    if request.provider:
        config.setdefault("providers", {})["default"] = request.provider
    if request.context_mode:
        config["context_mode"] = request.context_mode
    if request.lens:
        lens = get_lens(request.lens)
        if not lens:
            raise ApiError(
                400,
                "invalid_lens",
                f"Unknown lens '{request.lens}'",
                "Use ':lens' in CLI to list available lens shortcodes",
            )
        config["_active_lens"] = lens
    return config


def _sanitize_for_path(value: str, max_len: int = 32) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return text[:max_len] if text else "run"


def _run_pipeline_sync(
    *,
    job_id: str,
    request: PipelineRequest,
    base_config: dict[str, Any],
    prompt: str,
    steps: list[Any],
    cwd: str,
) -> tuple[dict[str, Any], str, str]:
    _set_current_job(job_id)
    try:
        config = _build_effective_config(base_config, request)

        run_id = f"{time.strftime('%Y-%m-%d_%H%M%S')}_{job_id[:8]}_{_sanitize_for_path(prompt)}"
        run_dir = Path(cwd) / ".lion" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        executor = PipelineExecutor(
            prompt=prompt,
            steps=steps,
            config=config,
            run_dir=str(run_dir),
            cwd=cwd,
        )
        result = executor.run()

        payload: dict[str, Any] = {
            "success": result.success,
            "prompt": result.prompt,
            "steps_completed": result.steps_completed,
            "total_steps": result.total_steps,
            "total_duration": result.total_duration,
            "total_tokens": result.total_tokens,
            "files_changed": result.files_changed,
            "errors": result.errors,
            "agent_summaries": result.agent_summaries,
            "final_decision": result.final_decision,
            "content": result.content,
        }
        return payload, str(run_dir), str(run_dir / "memory.jsonl")
    finally:
        _set_current_job(None)


async def run_pipeline_job(
    *,
    store: JobStore,
    sessions: SessionStore,
    base_config: dict[str, Any],
    default_timeout_seconds: float | None,
    job_id: str,
) -> None:
    job = await store.get_job(job_id)
    if not job:
        return

    request = PipelineRequest(
        prompt=job.prompt,
        pipeline_expr=job.pipeline_expr,
        provider=job.provider,
        context_mode=job.context_mode,
        lens=job.lens,
        cwd=job.cwd,
        timeout_seconds=job.timeout_seconds,
        config_overrides=job.config_overrides,
    )

    try:
        prompt, steps = validate_request(request, base_config)
    except ApiError as exc:
        await store.set_result(
            job_id,
            status=JobStatus.FAILED,
            error=f"{exc.message}: {exc.detail}" if exc.detail else exc.message,
        )
        await store.publish_event(
            job_id,
            StreamEventType.ERROR,
            {
                "error_code": exc.error_code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.FAILED.value})
        return

    cwd = request.cwd or os.getcwd()
    if not Path(cwd).exists():
        await store.set_result(
            job_id,
            status=JobStatus.FAILED,
            error=f"Working directory does not exist: {cwd}",
        )
        await store.publish_event(
            job_id,
            StreamEventType.ERROR,
            {
                "error_code": "invalid_cwd",
                "message": "Working directory does not exist",
                "detail": cwd,
            },
        )
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.FAILED.value})
        return

    running = await store.mark_running(job_id)
    if not running:
        return
    if running.cancel_requested:
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.CANCELLED.value})
        return

    await store.publish_event(
        job_id,
        StreamEventType.START,
        {
            "message": "Pipeline execution started",
            "prompt": prompt,
            "steps": len(steps),
        },
    )

    timeout_seconds = request.timeout_seconds or default_timeout_seconds

    try:
        coro = asyncio.to_thread(
            _run_pipeline_sync,
            job_id=job_id,
            request=request,
            base_config=base_config,
            prompt=prompt,
            steps=steps,
            cwd=cwd,
        )
        if timeout_seconds:
            output, run_dir, shared_memory_path = await asyncio.wait_for(coro, timeout=timeout_seconds)
        else:
            output, run_dir, shared_memory_path = await coro

        stored = await store.get_job(job_id)
        if stored and stored.status == JobStatus.CANCELLED:
            # Job was cancelled while thread was running; keep cancelled state.
            await store.publish_event(
                job_id,
                StreamEventType.COMPLETE,
                {
                    "status": JobStatus.CANCELLED.value,
                    "message": "Cancellation requested; background execution finished",
                },
            )
            return

        status = JobStatus.COMPLETED if output.get("success", False) else JobStatus.FAILED
        await store.set_result(
            job_id,
            status=status,
            output=output,
            error="; ".join(output.get("errors", [])) if output.get("errors") else None,
            shared_memory_path=shared_memory_path,
            run_dir=run_dir,
        )

        if job.session_id:
            sessions.append_history(
                job.session_id,
                {
                    "timestamp": time.time(),
                    "prompt": prompt,
                    "status": status.value,
                    "job_id": job_id,
                    "summary": output.get("content") or output.get("final_decision") or "",
                },
            )

        await store.publish_event(
            job_id,
            StreamEventType.COMPLETE,
            {
                "status": status.value,
                "duration_seconds": output.get("total_duration"),
            },
        )

    except asyncio.TimeoutError:
        message = (
            f"Pipeline timed out after {timeout_seconds}s"
            if timeout_seconds
            else "Pipeline timed out"
        )
        await store.set_result(
            job_id,
            status=JobStatus.FAILED,
            error=message,
        )
        await store.publish_event(
            job_id,
            StreamEventType.ERROR,
            {
                "error_code": "timeout",
                "message": "Pipeline execution timeout",
                "detail": message,
            },
        )
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.FAILED.value})
    except PermissionError as exc:
        await store.set_result(job_id, status=JobStatus.FAILED, error=str(exc))
        await store.publish_event(
            job_id,
            StreamEventType.ERROR,
            {
                "error_code": "permission_denied",
                "message": "File permission error during pipeline execution",
                "detail": str(exc),
            },
        )
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.FAILED.value})
    except Exception as exc:
        await store.set_result(job_id, status=JobStatus.FAILED, error=str(exc))
        await store.publish_event(
            job_id,
            StreamEventType.ERROR,
            {
                "error_code": "execution_error",
                "message": "Pipeline execution failed",
                "detail": str(exc),
            },
        )
        await store.publish_event(job_id, StreamEventType.COMPLETE, {"status": JobStatus.FAILED.value})
