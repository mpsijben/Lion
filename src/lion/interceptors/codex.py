"""Codex (OpenAI) CLI stream interceptor.

Wraps `codex exec --json` with session resume via `codex exec resume --last`.
Parses JSONL events: thread.started, item.completed, item.delta, error.
Supports model selection via model_hint (e.g. "mini" -> o4-mini).

Ported from pair_poc/interceptors.py CodexInterceptor.
"""

from __future__ import annotations

import json

from .base import Chunk, InterceptorCapabilities, StreamInterceptor


# Map short hints to full OpenAI model names.
# Users write "codex.mini" and we pass "-m o4-mini" to the CLI.
CODEX_MODELS = {
    "mini": "o4-mini",
}


class CodexInterceptor(StreamInterceptor):
    name = "codex"

    def __init__(self, cwd: str = ".", model_hint: str | None = None) -> None:
        super().__init__(cwd=cwd, model_hint=model_hint)

    def build_command(self, prompt: str, resume: bool) -> list[str]:
        if resume:
            cmd = ["codex", "exec", "resume", "--last", prompt, "--json"]
        else:
            cmd = ["codex", "exec", "--json", prompt]
        if self.model_hint:
            model = CODEX_MODELS.get(self.model_hint, self.model_hint)
            cmd.extend(["-m", model])
        return cmd

    def capabilities(self) -> InterceptorCapabilities:
        # Current Lion path is codex exec/resume (app-server steer not wired yet).
        return InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=False,
            supports_steer=False,
            supports_live_input=False,
        )

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
            item_type = item.get("type", "")

            # Reasoning = chain-of-thought thinking
            if item_type == "reasoning":
                text = item.get("text", "")
                if text:
                    chunks.append(self._chunk(
                        self.name, text, line, stream, kind="thinking",
                    ))
                return chunks

            # command_execution contains code the model is writing/running
            if item_type == "command_execution":
                cmd = item.get("command", "")
                if cmd:
                    chunks.append(self._chunk(
                        self.name, cmd, line, stream, kind="tool_use",
                    ))
                return chunks

            # agent_message = text output to user
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
        elif msg_type == "turn.completed":
            usage = entry.get("usage", {})
            self.stats.input_tokens += usage.get("input_tokens", 0)
            self.stats.output_tokens += usage.get("output_tokens", 0)
        elif msg_type == "error":
            text = entry.get("message", "unknown error")
            chunks.append(self._chunk(self.name, f"ERROR: {text}", line, stream))
        return chunks
