"""Gemini CLI stream interceptor.

Wraps `gemini -o json` with session resume via --resume latest.
Handles multi-line JSON buffering for pretty-printed Gemini output.
Ported from pair_poc/interceptors.py GeminiInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, StreamInterceptor


class GeminiInterceptor(StreamInterceptor):
    name = "gemini"

    def __init__(self, cwd: str = ".") -> None:
        super().__init__(cwd=cwd)
        self._json_buffer = ""

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = ["gemini", "-o", "json"]
        if resume:
            cmd.extend(["--resume", "latest"])
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
                chunks.append(
                    self._chunk(
                        self.name,
                        f"ERROR: {err.get('message', 'unknown')}",
                        line,
                        stream,
                    )
                )
        return chunks
