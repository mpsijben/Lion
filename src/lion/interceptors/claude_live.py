"""Claude live stream-json interceptor (stdin kept open)."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

from .base import Chunk, InterceptorCapabilities, StreamInterceptor


class ClaudeLiveInterceptor(StreamInterceptor):
    name = "claude.live"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)
        self._proc: subprocess.Popen[str] | None = None
        self._threads: list[threading.Thread] = []
        self._turn_queue: queue.Queue[Chunk | None] = queue.Queue()
        self._active_turn = False
        self._turn_lock = threading.Lock()
        self._last_assistant_text = ""

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = [
            "claude",
            "-p",
            "--verbose",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]
        if self.model_hint:
            cmd.extend(["--model", self.model_hint])
        return cmd

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        return []

    def capabilities(self) -> InterceptorCapabilities:
        return InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=False,
            supports_wait_gate=True,
            supports_steer=True,
            supports_live_input=True,
        )

    def _set_active(self, value: bool) -> None:
        with self._turn_lock:
            self._active_turn = value

    def _is_active(self) -> bool:
        with self._turn_lock:
            return self._active_turn

    def _ensure_process(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            self.build_command("", False),
            cwd=self.cwd,
            env=self._env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._threads = [
            threading.Thread(target=self._pump_stdout, daemon=True),
            threading.Thread(target=self._pump_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _send_user(self, text: str) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("Claude live stdin unavailable")
        payload = {"type": "user", "message": {"role": "user", "content": text}}
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _pump_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        for _line in iter(self._proc.stderr.readline, ""):
            pass

    def _pump_stdout(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        for line in iter(self._proc.stdout.readline, ""):
            raw = line.rstrip("\n")
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = payload.get("type")
            if msg_type == "system" and payload.get("subtype") == "init":
                self.session_id = payload.get("session_id") or self.session_id
                continue

            if msg_type == "assistant":
                message = payload.get("message", {})
                for part in message.get("content", []):
                    ptype = part.get("type", "text")
                    text = part.get("text", "")
                    if not text:
                        continue
                    self._last_assistant_text = text.strip()
                    kind = "thinking" if ptype == "thinking" else "code"
                    self._turn_queue.put(
                        Chunk(
                            source=self.name,
                            text=text,
                            raw=raw,
                            timestamp=time.time(),
                            stream="stdout",
                            kind=kind,
                        )
                    )
                continue

            if msg_type == "result":
                usage = payload.get("usage", {})
                self.stats.input_tokens += usage.get("input_tokens", 0) + usage.get(
                    "cache_read_input_tokens", 0
                )
                self.stats.output_tokens += usage.get("output_tokens", 0)
                self.stats.cost_usd += payload.get("total_cost_usd", 0.0) or 0.0
                result_text = payload.get("result", "")
                if result_text and result_text.strip() != self._last_assistant_text:
                    self._turn_queue.put(
                        Chunk(
                            source=self.name,
                            text=result_text,
                            raw=raw,
                            timestamp=time.time(),
                            stream="stdout",
                            kind="code",
                        )
                    )
                self._set_active(False)
                self._turn_queue.put(None)

    def start(self, prompt: str, resume: bool = False) -> None:
        self.stats = type(self.stats)(started_at=time.time())
        self._ensure_process()
        self._turn_queue = queue.Queue()
        self._set_active(True)
        self._send_user(prompt)

    def chunks(self, poll_interval: float = 0.05):
        while True:
            try:
                item = self._turn_queue.get(timeout=poll_interval)
            except queue.Empty:
                if not self._is_active():
                    break
                continue
            if item is None:
                break
            self.stats.chunk_count += 1
            if self.stats.first_chunk_at is None:
                self.stats.first_chunk_at = item.timestamp
            yield item
        self.stats.ended_at = time.time()

    def resume(self, correction: str) -> None:
        self.start(correction, resume=True)

    def steer(self, guidance: str) -> bool:
        if not self._is_active():
            return False
        try:
            self._send_user(guidance)
            return True
        except Exception:
            return False

    def terminate(self, hard: bool = False) -> None:
        if not self._proc:
            return
        self._set_active(False)
        self._turn_queue.put(None)
        if hard and self._proc.poll() is None:
            self._proc.kill()
