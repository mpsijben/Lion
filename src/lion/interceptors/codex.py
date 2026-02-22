"""Codex (OpenAI) CLI stream interceptor.

Wraps `codex exec --json` with session resume via `codex exec resume --last`.
Parses JSONL events: thread.started, item.completed, item.delta, error.
Ported from pair_poc/interceptors.py CodexInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, StreamInterceptor


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
                text = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
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
