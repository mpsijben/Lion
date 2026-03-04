"""Gemini ACP interceptor (experimental)."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

from .base import Chunk, InterceptorCapabilities, StreamInterceptor


class GeminiACPInterceptor(StreamInterceptor):
    name = "gemini.acp"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)
        self._proc: subprocess.Popen[str] | None = None
        self._threads: list[threading.Thread] = []
        self._turn_queue: queue.Queue[Chunk | None] = queue.Queue()
        self._id_lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[str, queue.Queue[dict]] = {}
        self._pending_lock = threading.Lock()
        self._session_id: str | None = None
        self._active_request_id: str | None = None
        self._active_lock = threading.Lock()
        self._active_started_at: float | None = None
        self._last_event_at: float | None = None
        # ACP can occasionally miss a terminal response event.
        # Guard the stream loop so pair() cannot hang indefinitely.
        self._max_turn_seconds = 180.0
        self._max_idle_seconds = 45.0

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        return ["gemini", "--experimental-acp"]

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        return []

    def capabilities(self) -> InterceptorCapabilities:
        return InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=False,
            supports_wait_gate=True,
            supports_steer=False,
            supports_live_input=True,
        )

    def _new_id(self) -> str:
        with self._id_lock:
            self._next_id += 1
            return str(self._next_id)

    def _set_active_request(self, rid: str | None) -> None:
        with self._active_lock:
            self._active_request_id = rid
            if rid is None:
                self._active_started_at = None
            else:
                now = time.time()
                self._active_started_at = now
                self._last_event_at = now

    def _active_request(self) -> str | None:
        with self._active_lock:
            return self._active_request_id

    def _send(self, payload: dict) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("Gemini ACP stdin unavailable")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict, timeout: float = 20.0) -> dict:
        rid = self._new_id()
        resp_q: queue.Queue[dict] = queue.Queue()
        with self._pending_lock:
            self._pending[rid] = resp_q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return resp_q.get(timeout=timeout)
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

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
        self._initialize()
        self._ensure_session()

    def _initialize(self) -> None:
        resp = self._request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
            timeout=20.0,
        )
        if "error" in resp:
            raise RuntimeError(f"gemini ACP initialize failed: {resp['error']}")
        self._notify("initialized", {})

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        resp = self._request(
            "session/new",
            {"cwd": self.cwd, "mcpServers": []},
            timeout=20.0,
        )
        if "error" in resp:
            raise RuntimeError(f"gemini ACP session/new failed: {resp['error']}")
        sid = resp.get("result", {}).get("sessionId")
        if not sid:
            raise RuntimeError("gemini ACP did not return sessionId")
        self._session_id = sid
        self.session_id = sid

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
            if not isinstance(payload, dict):
                # Ignore non-object JSON payloads; they are not ACP envelopes.
                continue

            self._last_event_at = time.time()

            rid = payload.get("id")
            if rid is not None:
                rid = str(rid)
                with self._pending_lock:
                    q = self._pending.get(rid)
                if q is not None:
                    q.put(payload)
                    continue
                if rid == self._active_request():
                    self._set_active_request(None)
                    self._turn_queue.put(None)
                    continue

            method = payload.get("method")
            params = payload.get("params", {})
            if not isinstance(params, dict):
                continue
            if method != "session/update":
                continue
            update = params.get("update", {})
            if not isinstance(update, dict):
                continue
            update_type = update.get("sessionUpdate")
            content = update.get("content", {})
            if not isinstance(content, dict):
                continue
            text = content.get("text", "")
            if not text:
                continue
            kind = "thinking" if update_type == "agent_thought_chunk" else "code"
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

    def start(self, prompt: str, resume: bool = False) -> None:
        self.stats = type(self.stats)(started_at=time.time())
        self._ensure_process()
        self._ensure_session()
        rid = self._new_id()
        self._turn_queue = queue.Queue()
        self._set_active_request(rid)
        self._send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "session/prompt",
                "params": {
                    "sessionId": self._session_id,
                    "prompt": [{"type": "text", "text": prompt}],
                },
            }
        )

    def chunks(self, poll_interval: float = 0.05):
        while True:
            try:
                item = self._turn_queue.get(timeout=poll_interval)
            except queue.Empty:
                active = self._active_request()
                if active is None:
                    break
                now = time.time()
                if (
                    self._active_started_at is not None
                    and now - self._active_started_at > self._max_turn_seconds
                ):
                    self.stats.errors.append("gemini.acp turn timeout")
                    self._set_active_request(None)
                    break
                if (
                    self._last_event_at is not None
                    and now - self._last_event_at > self._max_idle_seconds
                ):
                    self.stats.errors.append("gemini.acp idle timeout")
                    self._set_active_request(None)
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

    def terminate(self, hard: bool = False) -> None:
        self._set_active_request(None)
        self._turn_queue.put(None)
        if hard and self._proc and self._proc.poll() is None:
            self._proc.kill()
