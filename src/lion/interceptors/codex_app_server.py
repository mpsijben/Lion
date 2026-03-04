"""Codex app-server interceptor with turn/steer support.

This transport keeps a single long-lived `codex app-server` subprocess and
streams chunks from JSON-RPC notifications. It supports:
- turn/start
- turn/interrupt
- turn/steer
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

from .base import Chunk, InterceptorCapabilities, StreamInterceptor


class CodexAppServerInterceptor(StreamInterceptor):
    name = "codex.app_server"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)
        self._server_proc: subprocess.Popen[str] | None = None
        self._server_threads: list[threading.Thread] = []
        self._id_lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[str, queue.Queue[dict]] = {}
        self._pending_lock = threading.Lock()
        self._turn_queue: queue.Queue[Chunk | None] = queue.Queue()
        self._thread_id: str | None = None
        self._active_turn_id: str | None = None
        self._active_lock = threading.Lock()
        self._last_usage_total_tokens = 0

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        return ["codex", "app-server"]

    def parse_line(self, line: str, stream: str) -> list[Chunk]:
        return []

    def capabilities(self) -> InterceptorCapabilities:
        return InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=False,
            supports_steer=True,
            supports_live_input=True,
        )

    def _new_id(self) -> str:
        with self._id_lock:
            self._next_id += 1
            return str(self._next_id)

    def _start_server(self) -> None:
        if self._server_proc and self._server_proc.poll() is None:
            return

        self._server_proc = subprocess.Popen(
            self.build_command("", False),
            cwd=self.cwd,
            env=self._env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._server_threads = [
            threading.Thread(target=self._pump_stdout, daemon=True),
            threading.Thread(target=self._pump_stderr, daemon=True),
        ]
        for thread in self._server_threads:
            thread.start()
        self._initialize_server()
        self._ensure_thread()

    def _send(self, payload: dict) -> None:
        if not self._server_proc or not self._server_proc.stdin:
            raise RuntimeError("Codex app-server stdin unavailable")
        self._server_proc.stdin.write(json.dumps(payload) + "\n")
        self._server_proc.stdin.flush()

    def _request(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        rid = self._new_id()
        resp_q: queue.Queue[dict] = queue.Queue()
        with self._pending_lock:
            self._pending[rid] = resp_q
        self._send({"id": rid, "method": method, "params": params})
        try:
            response = resp_q.get(timeout=timeout)
            return response
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _notify(self, method: str, params: dict) -> None:
        self._send({"method": method, "params": params})

    def _initialize_server(self) -> None:
        resp = self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "lion-cli",
                    "title": "Lion CLI",
                    "version": "0.1.0",
                }
            },
            timeout=20.0,
        )
        if "error" in resp:
            raise RuntimeError(f"codex app-server initialize failed: {resp['error']}")
        self._notify("initialized", {})

    def _ensure_thread(self) -> None:
        if self._thread_id:
            return
        params = {}
        if self.model_hint:
            params["model"] = self.model_hint
        resp = self._request("thread/start", params, timeout=20.0)
        if "error" in resp:
            raise RuntimeError(f"codex app-server thread/start failed: {resp['error']}")
        self._thread_id = (
            resp.get("result", {}).get("thread", {}).get("id") or self._thread_id
        )
        if not self._thread_id:
            raise RuntimeError("codex app-server did not return thread id")
        self.session_id = self._thread_id

    def _pump_stderr(self) -> None:
        if not self._server_proc or not self._server_proc.stderr:
            return
        for _line in iter(self._server_proc.stderr.readline, ""):
            # Ignore verbose Codex warnings in stream mode.
            pass

    def _pump_stdout(self) -> None:
        if not self._server_proc or not self._server_proc.stdout:
            return
        for line in iter(self._server_proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            rid = payload.get("id")
            if rid is not None:
                with self._pending_lock:
                    resp_q = self._pending.get(str(rid))
                if resp_q is not None:
                    resp_q.put(payload)
                    continue

            self._handle_notification(payload)

    def _active_turn(self) -> str | None:
        with self._active_lock:
            return self._active_turn_id

    def _set_active_turn(self, turn_id: str | None) -> None:
        with self._active_lock:
            self._active_turn_id = turn_id

    def _handle_notification(self, payload: dict) -> None:
        method = payload.get("method")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}

        if method == "item/agentMessage/delta":
            turn_id = params.get("turnId")
            if turn_id and turn_id == self._active_turn():
                text = params.get("delta", "")
                if text:
                    self._turn_queue.put(
                        self._chunk(self.name, text, json.dumps(payload), "stdout")
                    )
            return

        if method == "item/reasoning/summaryTextDelta":
            turn_id = params.get("turnId")
            if turn_id and turn_id == self._active_turn():
                text = params.get("delta", "")
                if text:
                    self._turn_queue.put(
                        self._chunk(
                            self.name,
                            text,
                            json.dumps(payload),
                            "stdout",
                            kind="thinking",
                        )
                    )
            return

        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage", {}).get("last", {})
            if isinstance(usage, dict):
                tokens = usage.get("totalTokens", 0)
                if isinstance(tokens, int) and tokens > 0:
                    self._last_usage_total_tokens = tokens
            return

        if method == "turn/completed":
            completed_turn_id = params.get("turn", {}).get("id") or params.get("turnId")
            active_turn_id = self._active_turn()
            if completed_turn_id and active_turn_id and completed_turn_id == active_turn_id:
                self._set_active_turn(None)
                if self._last_usage_total_tokens > 0:
                    # App-server reports total token deltas; keep aggregate in input bucket.
                    self.stats.input_tokens += self._last_usage_total_tokens
                    self._last_usage_total_tokens = 0
                self._turn_queue.put(None)
            return

    def start(self, prompt: str, resume: bool = False) -> None:
        if resume:
            self.resume(prompt)
            return
        self.stats = type(self.stats)(started_at=time.time())
        self._start_server()
        if self._active_turn():
            raise RuntimeError("codex app-server turn already active")
        self._turn_queue = queue.Queue()
        resp = self._request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": prompt}],
            },
            timeout=30.0,
        )
        if "error" in resp:
            raise RuntimeError(f"codex app-server turn/start failed: {resp['error']}")
        turn_id = resp.get("result", {}).get("turn", {}).get("id")
        if not turn_id:
            raise RuntimeError("codex app-server did not return turn id")
        self._set_active_turn(turn_id)

    def chunks(self, poll_interval: float = 0.05):
        while True:
            try:
                item = self._turn_queue.get(timeout=poll_interval)
            except queue.Empty:
                if self._active_turn() is None:
                    break
                continue
            if item is None:
                break
            self.stats.chunk_count += 1
            if self.stats.first_chunk_at is None:
                self.stats.first_chunk_at = item.timestamp
            yield item
        self.stats.ended_at = time.time()

    def terminate(self, hard: bool = False) -> None:
        if hard:
            if self._server_proc and self._server_proc.poll() is None:
                self._server_proc.kill()
            return
        turn_id = self._active_turn()
        if not turn_id or not self._thread_id:
            return
        try:
            self._request(
                "turn/interrupt",
                {"threadId": self._thread_id, "turnId": turn_id},
                timeout=5.0,
            )
        except Exception:
            pass
        # Ensure local turn state is cleared so resume can start immediately.
        self._set_active_turn(None)
        self._turn_queue.put(None)

    def resume(self, correction: str) -> None:
        if self._active_turn():
            self.terminate()
        self.start(correction, resume=False)

    def steer(self, guidance: str) -> bool:
        turn_id = self._active_turn()
        if not turn_id or not self._thread_id:
            return False
        try:
            resp = self._request(
                "turn/steer",
                {
                    "threadId": self._thread_id,
                    "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": guidance}],
                },
                timeout=10.0,
            )
            return "error" not in resp
        except Exception:
            return False
