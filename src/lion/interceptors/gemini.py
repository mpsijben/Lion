"""Gemini CLI stream interceptor.

Wraps `gemini -o stream-json` with session resume via --resume latest.
Supports model selection via model_hint (e.g. "flash" -> gemini-2.5-flash).

Ported from pair_poc/interceptors.py GeminiInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, StreamInterceptor


# Map short hints to full Gemini model names.
# Users write "gemini.flash" and we pass "-m gemini-2.5-flash" to the CLI.
GEMINI_MODELS = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "flash-lite": "gemini-2.0-flash-lite",
}


class GeminiInterceptor(StreamInterceptor):
    name = "gemini"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)
        self._json_buffer = ""

    def start(self, prompt: str, resume: bool = False) -> None:
        self._json_buffer = ""
        super().start(prompt, resume)

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = ["gemini", "-o", "stream-json"]
        if self.model_hint:
            model = GEMINI_MODELS.get(self.model_hint, self.model_hint)
            cmd.extend(["-m", model])
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

            entry_type = entry.get("type", "")

            # Tool use events contain code written by the model
            if entry_type == "tool_use":
                params = entry.get("parameters", {})
                tool_name = entry.get("tool_name", "")
                code = ""
                if "content" in params:
                    code = params["content"]
                elif "command" in params:
                    code = params["command"]
                if code:
                    chunks.append(self._chunk(
                        self.name, code, line, stream, kind="tool_use",
                    ))

            # Message events contain text output (only assistant messages)
            elif entry_type == "message":
                role = entry.get("role", "")
                if role == "assistant":
                    content = entry.get("content", "")
                    if content:
                        chunks.append(self._chunk(
                            self.name, content, line, stream,
                        ))

            # Result event contains usage stats
            elif entry_type == "result":
                stats = entry.get("stats", {})
                self.stats.input_tokens += stats.get("input_tokens", 0)
                self.stats.output_tokens += stats.get("output_tokens", 0)

            # Legacy/fallback: response field (older gemini versions)
            elif "response" in entry:
                response = entry["response"]
                if response:
                    chunks.append(self._chunk(
                        self.name, response, line, stream,
                    ))

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
