"""Stream interceptors for Claude, Gemini and Codex CLIs.

This module is intentionally self-contained for POC work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from typing import Callable, Iterator


@dataclass
class Chunk:
    source: str
    text: str
    raw: str
    timestamp: float
    stream: str


@dataclass
class StreamStats:
    chunk_count: int = 0
    first_chunk_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ttft_ms(self) -> int | None:
        if self.started_at is None or self.first_chunk_at is None:
            return None
        return int((self.first_chunk_at - self.started_at) * 1000)


class StreamInterceptor:
    """Base class: start CLI, stream chunks, terminate, resume."""

    name = "base"

    def __init__(self, home_dir: str | None = None, cwd: str | None = None) -> None:
        self.home_dir = home_dir
        self.cwd = cwd or "."
        self.session_id: str | None = None
        self.stats = StreamStats()
        self._proc: subprocess.Popen[str] | None = None
        self._q: queue.Queue[tuple[str, str]] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._resume_hint: str | None = None
        self._terminated_intentionally = False

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        raise NotImplementedError

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        raise NotImplementedError

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        if self.home_dir:
            os.makedirs(self.home_dir, exist_ok=True)
            env["HOME"] = os.path.abspath(self.home_dir)
        return env

    def start(self, prompt: str, resume: bool = False) -> None:
        if self._proc and self._proc.poll() is None:
            raise RuntimeError(f"{self.name} process already running")

        self.stats = StreamStats(started_at=time.time())
        self._terminated_intentionally = False
        cmd = self.build_command(prompt=prompt, resume=resume)
        self._proc = subprocess.Popen(
            cmd,
            cwd=self.cwd,
            env=self._env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._threads = [
            threading.Thread(target=self._pump_stream, args=("stdout", self._proc.stdout), daemon=True),
            threading.Thread(target=self._pump_stream, args=("stderr", self._proc.stderr), daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _pump_stream(self, stream_name: str, stream_obj) -> None:
        if stream_obj is None:
            return
        for line in iter(stream_obj.readline, ""):
            self._q.put((stream_name, line.rstrip("\n")))
        self._q.put((stream_name, "__EOF__"))

    def chunks(self, poll_interval: float = 0.05) -> Iterator[Chunk]:
        if not self._proc:
            raise RuntimeError("Process not started")

        eof_count = 0
        while True:
            try:
                stream_name, line = self._q.get(timeout=poll_interval)
            except queue.Empty:
                if self._proc.poll() is not None and self._q.empty():
                    break
                continue

            if line == "__EOF__":
                eof_count += 1
                if eof_count >= 2 and self._proc.poll() is not None and self._q.empty():
                    break
                continue

            for chunk in self.parse_line(line=line, stream=stream_name):
                self.stats.chunk_count += 1
                if self.stats.first_chunk_at is None:
                    self.stats.first_chunk_at = chunk.timestamp
                yield chunk

        self.stats.ended_at = time.time()
        return_code = self._proc.wait(timeout=5)
        if (
            return_code != 0
            and not self._terminated_intentionally
            and self.stats.chunk_count == 0
        ):
            self.stats.errors.append(f"{self.name} exit={return_code}")

    def terminate(self, hard: bool = False) -> None:
        if not self._proc or self._proc.poll() is not None:
            return
        self._terminated_intentionally = True
        if hard:
            self._proc.kill()
        else:
            self._proc.terminate()

    def resume(self, correction: str) -> None:
        self.start(correction, resume=True)

    @staticmethod
    def _chunk(source: str, text: str, raw: str, stream: str) -> Chunk:
        return Chunk(source=source, text=text, raw=raw, timestamp=time.time(), stream=stream)


class ClaudeInterceptor(StreamInterceptor):
    name = "claude"

    def __init__(self, home_dir: str | None = None, cwd: str | None = None) -> None:
        super().__init__(home_dir=home_dir, cwd=cwd)
        self._last_assistant_text: str = ""

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = ["claude", "-p", prompt, "--verbose", "--output-format", "stream-json"]
        if resume and self.session_id:
            cmd.extend(["--resume", self.session_id])
        return cmd

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        if stream != "stdout":
            return chunks
        if not line.strip():
            return chunks
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return chunks

        msg_type = entry.get("type")
        if msg_type == "system" and entry.get("subtype") == "init":
            self.session_id = entry.get("session_id") or self.session_id
            self._last_assistant_text = ""
        elif msg_type == "assistant":
            message = entry.get("message", {})
            for part in message.get("content", []):
                text = part.get("text")
                if text:
                    self._last_assistant_text = text.strip()
                    chunks.append(self._chunk(self.name, text, line, stream))
            self.session_id = entry.get("session_id") or self.session_id
        elif msg_type == "result":
            self.session_id = entry.get("session_id") or self.session_id
            result_text = entry.get("result")
            if result_text and result_text.strip() and result_text.strip() != self._last_assistant_text:
                chunks.append(self._chunk(self.name, result_text, line, stream))
        return chunks


class GeminiInterceptor(StreamInterceptor):
    name = "gemini"

    def __init__(self, home_dir: str | None = None, cwd: str | None = None) -> None:
        super().__init__(home_dir=home_dir, cwd=cwd)
        self._json_buffer = ""
        self._resume_ref = "latest"

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = ["gemini", "-o", "json"]
        if resume:
            # Gemini CLI 0.16 uses --resume (latest/index), not --session-id.
            # "latest" is deterministic within a single interceptor flow.
            cmd.extend(["--resume", self._resume_ref])
        # Resume mode requires explicit --prompt (-p) according to Gemini CLI.
        cmd.extend(["-p", prompt])
        return cmd

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        if stream != "stdout":
            return chunks
        if not line.strip():
            return chunks

        # Gemini can emit pretty-printed multi-line JSON; buffer until parseable.
        stripped = line.strip()
        if self._json_buffer or stripped.startswith("{"):
            self._json_buffer = f"{self._json_buffer}\n{line}".strip()
            try:
                entry = json.loads(self._json_buffer)
                self._json_buffer = ""
            except json.JSONDecodeError:
                return chunks
        else:
            return chunks

        if isinstance(entry, dict):
            if "session_id" in entry and entry["session_id"]:
                self.session_id = entry["session_id"]
            response = entry.get("response")
            if response:
                chunks.append(self._chunk(self.name, response, line, stream))
            err = entry.get("error")
            if err and isinstance(err, dict):
                chunks.append(self._chunk(self.name, f"ERROR: {err.get('message', 'unknown')}", line, stream))
        return chunks


class CodexInterceptor(StreamInterceptor):
    name = "codex"

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        if resume:
            return ["codex", "exec", "resume", "--last", prompt, "--json"]
        return ["codex", "exec", "--json", prompt]

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        if stream != "stdout":
            return chunks
        if not line.strip():
            return chunks
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return chunks

        msg_type = entry.get("type")
        if msg_type == "thread.started":
            self.session_id = entry.get("thread_id") or self.session_id
        elif msg_type == "item.completed":
            item = entry.get("item", {})
            text = item.get("text", "")
            if not text and isinstance(item.get("content"), list):
                content = item.get("content")
                text = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            if text:
                chunks.append(self._chunk(self.name, text, line, stream))
        elif msg_type == "item.delta":
            delta = entry.get("delta", {})
            text = delta.get("text")
            if text:
                chunks.append(self._chunk(self.name, text, line, stream))
        elif msg_type == "error":
            text = entry.get("message", "unknown error")
            chunks.append(self._chunk(self.name, f"ERROR: {text}", line, stream))
        return chunks


def run_interceptor(
    interceptor: StreamInterceptor,
    prompt: str,
    *,
    max_lines: int | None = None,
    terminate_after: float | None = None,
    hard_terminate: bool = False,
    on_chunk: Callable[[Chunk], None] | None = None,
    on_event: Callable[[str], None] | None = None,
    heartbeat_sec: float = 5.0,
) -> dict:
    """Run one prompt and collect output for reporting."""
    if on_event:
        on_event(f"[{interceptor.name}] start")
    interceptor.start(prompt, resume=False)
    if on_event:
        on_event(f"[{interceptor.name}] spawned")
    started = time.time()
    out = collect_interceptor_chunks(
        interceptor=interceptor,
        max_lines=max_lines,
        terminate_after=terminate_after,
        hard_terminate=hard_terminate,
        on_chunk=on_chunk,
        on_event=on_event,
        heartbeat_sec=heartbeat_sec,
        started_at=started,
    )

    if on_event:
        on_event(
            f"[{interceptor.name}] done chunks={interceptor.stats.chunk_count} "
            f"ttft_ms={interceptor.stats.ttft_ms}"
        )
    return {
        "name": interceptor.name,
        "session_id": interceptor.session_id,
        "ttft_ms": interceptor.stats.ttft_ms,
        "chunk_count": interceptor.stats.chunk_count,
        "errors": interceptor.stats.errors,
        "output": out,
    }


def collect_interceptor_chunks(
    interceptor: StreamInterceptor,
    *,
    max_lines: int | None = None,
    terminate_after: float | None = None,
    hard_terminate: bool = False,
    on_chunk: Callable[[Chunk], None] | None = None,
    on_event: Callable[[str], None] | None = None,
    heartbeat_sec: float = 5.0,
    started_at: float | None = None,
) -> list[str]:
    """Collect chunks from an already-started interceptor with optional heartbeat logs."""
    out: list[str] = []
    started = started_at or time.time()
    last_heartbeat = started

    for chunk in interceptor.chunks():
        out.append(chunk.text)
        if on_chunk:
            on_chunk(chunk)
        if on_event:
            preview = chunk.text.replace("\n", " ")[:100]
            on_event(f"[{interceptor.name}] chunk#{len(out)} {preview}")
        now = time.time()
        if on_event and heartbeat_sec > 0 and now - last_heartbeat >= heartbeat_sec:
            on_event(
                f"[{interceptor.name}] heartbeat elapsed={int(now-started)}s chunks={len(out)}"
            )
            last_heartbeat = now
        if max_lines is not None and len(out) >= max_lines:
            if on_event:
                on_event(f"[{interceptor.name}] terminate reason=max_lines")
            interceptor.terminate(hard=hard_terminate)
            max_lines = None
        if terminate_after is not None and (time.time() - started) >= terminate_after:
            if on_event:
                on_event(f"[{interceptor.name}] terminate reason=timeout")
            interceptor.terminate(hard=hard_terminate)
            terminate_after = None
    return out


def shell_quote(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)
