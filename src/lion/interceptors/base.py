"""Stream interceptor base class for CLI process-level LLM control.

Treats LLM CLIs as OS processes: start, stream, terminate, resume.
This is process-level orchestration, not prompt orchestration.

Ported from pair_poc/interceptors.py (proven across experiments 0-8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import queue
import subprocess
import threading
import time
from typing import Iterator


@dataclass
class Chunk:
    source: str
    text: str
    raw: str
    timestamp: float
    stream: str
    kind: str = "code"  # "code" or "thinking"


@dataclass
class StreamStats:
    chunk_count: int = 0
    first_chunk_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    errors: list[str] = field(default_factory=list)
    # Token usage captured from provider result events
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def ttft_ms(self) -> int | None:
        if self.started_at is None or self.first_chunk_at is None:
            return None
        return int((self.first_chunk_at - self.started_at) * 1000)


class StreamInterceptor:
    """Base class: start CLI, stream chunks, terminate, resume.

    Subclasses implement build_command() and parse_line() for each CLI.
    The threading + queue architecture handles non-blocking stdout/stderr
    pumping with __EOF__ sentinel detection for clean process completion.
    """

    name = "base"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        self.cwd = cwd
        self.model_hint = model_hint
        self.session_id: str | None = None
        self.stats = StreamStats()
        self._proc: subprocess.Popen[str] | None = None
        self._q: queue.Queue[tuple[str, str]] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._terminated_intentionally = False

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        raise NotImplementedError

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        raise NotImplementedError

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        return env

    def start(self, prompt: str, resume: bool = False) -> None:
        if self._proc and self._proc.poll() is None:
            raise RuntimeError(f"{self.name} process already running")

        # Drain stale data from previous run
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

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
            threading.Thread(
                target=self._pump_stream,
                args=("stdout", self._proc.stdout),
                daemon=True,
            ),
            threading.Thread(
                target=self._pump_stream,
                args=("stderr", self._proc.stderr),
                daemon=True,
            ),
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
                if self._proc.poll() is not None:
                    # Process exited -- wait for pump threads to finish
                    # so all output is queued before we check for empty.
                    for t in self._threads:
                        t.join(timeout=2)
                    if self._q.empty():
                        break
                continue

            if line == "__EOF__":
                eof_count += 1
                if eof_count >= 2 and self._q.empty():
                    break
                continue

            for chunk in self.parse_line(line=line, stream=stream_name):
                self.stats.chunk_count += 1
                if self.stats.first_chunk_at is None:
                    self.stats.first_chunk_at = chunk.timestamp
                yield chunk

        self.stats.ended_at = time.time()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        return_code = self._proc.returncode
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
        self.terminate()
        try:
            if self._proc:
                self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if self._proc:
                self._proc.kill()
        self.start(correction, resume=True)

    @staticmethod
    def _chunk(source: str, text: str, raw: str, stream: str,
               kind: str = "code") -> Chunk:
        return Chunk(
            source=source, text=text, raw=raw,
            timestamp=time.time(), stream=stream, kind=kind,
        )
