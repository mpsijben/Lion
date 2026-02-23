"""Claude CLI stream interceptor.

Wraps `claude -p --output-format stream-json` with session resume via --resume.
Supports model selection via model_hint (e.g. "opus" -> claude-opus-4-0520).
Captures both thinking tokens and code output as separate chunk kinds.

Ported from pair_poc/interceptors.py ClaudeInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, StreamInterceptor


# Map short hints to full Claude model names.
# Users write "claude.opus" and we pass "--model claude-opus-4-0520" to the CLI.
CLAUDE_MODELS = {
    "opus": "claude-opus-4-0520",
    "sonnet": "claude-sonnet-4-0520",
    "haiku": "claude-haiku-4-0520",
}


class ClaudeInterceptor(StreamInterceptor):
    name = "claude"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)
        self._last_assistant_text: str = ""

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--verbose",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
        if self.model_hint:
            model = CLAUDE_MODELS.get(self.model_hint, self.model_hint)
            cmd.extend(["--model", model])
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
                part_type = part.get("type", "text")
                text = part.get("text")
                if text and part_type == "thinking":
                    chunks.append(self._chunk(
                        self.name, text, line, stream, kind="thinking",
                    ))
                elif part_type == "tool_use":
                    # Extract code from Write/Edit tool calls
                    inp = part.get("input", {})
                    tool_name = part.get("name", "")
                    code = ""
                    if tool_name == "Write":
                        code = inp.get("content", "")
                    elif tool_name == "Edit":
                        code = inp.get("new_string", "")
                    if code:
                        chunks.append(self._chunk(
                            self.name, code, line, stream, kind="tool_use",
                        ))
                elif text:
                    self._last_assistant_text = text.strip()
                    chunks.append(self._chunk(
                        self.name, text, line, stream, kind="code",
                    ))
            self.session_id = entry.get("session_id") or self.session_id

        elif msg_type == "result":
            self.session_id = entry.get("session_id") or self.session_id
            # Capture usage stats
            usage = entry.get("usage", {})
            self.stats.input_tokens += usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            self.stats.output_tokens += usage.get("output_tokens", 0)
            self.stats.cost_usd += entry.get("total_cost_usd", 0.0) or 0.0
            result_text = entry.get("result")
            if (
                result_text
                and result_text.strip()
                and result_text.strip() != self._last_assistant_text
            ):
                chunks.append(self._chunk(
                    self.name, result_text, line, stream, kind="code",
                ))
        return chunks
