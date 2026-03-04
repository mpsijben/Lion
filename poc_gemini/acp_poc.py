#!/usr/bin/env python3
"""Minimal Gemini ACP proof-of-concept client.

Runs Gemini CLI in ACP mode over stdio and supports:
- initialize + initialized handshake
- sending arbitrary JSON-RPC requests
- receiving async notifications
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class RpcMessage:
    stream: str
    payload: dict[str, Any]
    raw: str


class GeminiACPClient:
    def __init__(self, cwd: str | None = None, suppress_stderr: bool = False) -> None:
        self.cwd = cwd
        self.suppress_stderr = suppress_stderr
        self.proc: subprocess.Popen[str] | None = None
        self._q: queue.Queue[RpcMessage] = queue.Queue()
        self._request_id = 0
        self._reader_threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.proc is not None:
            raise RuntimeError("process already started")
        self.proc = subprocess.Popen(
            ["gemini", "--experimental-acp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
        )
        self._reader_threads = [
            threading.Thread(
                target=self._pump,
                args=("stdout", self.proc.stdout),
                daemon=True,
            ),
            threading.Thread(
                target=self._pump,
                args=("stderr", self.proc.stderr),
                daemon=True,
            ),
        ]
        for thread in self._reader_threads:
            thread.start()

    def stop(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _pump(self, stream_name: str, stream_obj) -> None:
        if stream_obj is None:
            return
        for line in iter(stream_obj.readline, ""):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"_non_json": line}
            self._q.put(RpcMessage(stream=stream_name, payload=payload, raw=line))

    def _send(self, message: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("process stdin not available")
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = 20.0,
        passthrough_notifications: bool = True,
    ) -> dict[str, Any]:
        self._request_id += 1
        rid = str(self._request_id)
        self._send(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self._q.get(timeout=0.25)
            except queue.Empty:
                continue

            if msg.stream == "stderr":
                if not self.suppress_stderr:
                    print(f"[STDERR] {msg.raw}", file=sys.stderr)
                continue

            payload = msg.payload
            if payload.get("id") == rid:
                return payload

            if passthrough_notifications:
                self._print_event(msg)

        raise TimeoutError(f"timeout waiting for response to {method}")

    def read_events(self, duration_s: float = 2.0) -> None:
        deadline = time.time() + duration_s
        while time.time() < deadline:
            try:
                msg = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            if msg.stream == "stderr" and self.suppress_stderr:
                continue
            self._print_event(msg)

    @staticmethod
    def _print_event(msg: RpcMessage) -> None:
        prefix = "[STDERR]" if msg.stream == "stderr" else "[EVENT]"
        print(f"{prefix} {json.dumps(msg.payload, ensure_ascii=True)}")


def _parse_json_arg(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON for --params: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("--params JSON must be an object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gemini ACP POC client")
    parser.add_argument(
        "--cwd",
        default=".",
        help="Working directory where gemini process runs (default: current dir)",
    )
    parser.add_argument(
        "--init-timeout",
        type=float,
        default=20.0,
        help="Timeout for initialize request in seconds",
    )
    parser.add_argument(
        "--protocol-version",
        type=int,
        default=1,
        help="ACP protocol version for initialize params",
    )
    parser.add_argument(
        "--events-seconds",
        type=float,
        default=2.0,
        help="How long to keep reading async events after request",
    )
    parser.add_argument(
        "--suppress-stderr",
        action="store_true",
        help="Hide Gemini stderr noise (experiments/flags logs)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Only run ACP initialize handshake")
    init.add_argument(
        "--suppress-stderr",
        action="store_true",
        help="Hide Gemini stderr noise (experiments/flags logs)",
    )

    req = sub.add_parser("request", help="Run one JSON-RPC request after init")
    req.add_argument("--method", required=True, help="JSON-RPC method name")
    req.add_argument(
        "--params",
        default="{}",
        help="JSON object string for method params (default: {})",
    )
    req.add_argument(
        "--suppress-stderr",
        action="store_true",
        help="Hide Gemini stderr noise (experiments/flags logs)",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    client = GeminiACPClient(cwd=args.cwd, suppress_stderr=args.suppress_stderr)
    try:
        client.start()
        init_params = {
            "protocolVersion": args.protocol_version,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
        }
        init_resp = client.request(
            method="initialize",
            params=init_params,
            timeout=args.init_timeout,
        )
        print("[INIT_RESPONSE]", json.dumps(init_resp, ensure_ascii=True))

        client.notify("initialized", {})
        print("[NOTIFY] initialized")

        if args.command == "init":
            client.read_events(duration_s=args.events_seconds)
            return 0

        if args.command == "request":
            params = _parse_json_arg(args.params)
            resp = client.request(
                method=args.method,
                params=params,
                timeout=max(20.0, args.init_timeout),
            )
            print("[REQUEST_RESPONSE]", json.dumps(resp, ensure_ascii=True))
            client.read_events(duration_s=args.events_seconds)
            return 0

        parser.error("unknown command")
        return 2
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
