"""Claude CLI stream interceptor.

Wraps `claude -p --output-format stream-json` with session resume via --resume.
Ported from pair_poc/interceptors.py ClaudeInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, StreamInterceptor


class ClaudeInterceptor(StreamInterceptor):
    name = "claude"

    def __init__(self, cwd: str = ".") -> None:
        super().__init__(cwd=cwd)
        self._last_assistant_text: str = ""

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--verbose",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
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
            if (
                result_text
                and result_text.strip()
                and result_text.strip() != self._last_assistant_text
            ):
                chunks.append(self._chunk(self.name, result_text, line, stream))
        return chunks
