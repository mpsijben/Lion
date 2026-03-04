"""OpenAI Codex CLI provider - wraps `codex exec`."""

import subprocess
import json
import os
import time
from .base import Provider, AgentResult


class CodexProvider(Provider):
    name = "codex"

    def __init__(self, model=None, config=None):
        super().__init__(model, config)
        if model:
            self.name = f"codex.{model}"

    @staticmethod
    def _safe_env():
        """Create env that prevents recursive lion calls from child processes."""
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        return env

    def ask(self, prompt, system_prompt="", cwd="."):
        """Use codex exec --json for non-interactive queries."""
        system_prompt = self._get_effective_system_prompt(system_prompt)
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd = ["codex", "exec", "--json", "--full-auto", full_prompt]
        if cwd != ".":
            cmd.extend(["-C", cwd])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=f"Timeout after {self.timeout}s"
            )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=duration, success=False,
                error=result.stderr or f"Exit code {result.returncode}"
            )

        parsed = self._parse_output(result.stdout, duration)
        self._record_usage(parsed)
        return parsed

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        """Include file contents in the prompt."""
        file_contents = []
        for f in files:
            try:
                with open(f, "r") as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                file_contents.append(f"--- {f} --- (could not read)")

        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        """Use codex exec with streaming to make actual file changes.

        Streams output via Display.pair_lead_chunk() so the TUI can show
        progress in real time.
        """
        from ..display import Display

        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = [
            "codex", "exec", "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            impl_prompt,
        ]
        if cwd != ".":
            cmd.extend(["-C", cwd])

        env = self._safe_env()

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env,
            )
        except Exception as e:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=str(e),
            )

        # Stream JSONL output line by line
        lines_collected = []
        content = ""
        tokens = 0
        try:
            for line in proc.stdout:
                lines_collected.append(line)
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type")
                if msg_type == "item.completed":
                    item = entry.get("item", {})
                    item_type = item.get("type", "")
                    if item_type == "command_execution":
                        cmd_text = item.get("command", "")
                        if cmd_text:
                            Display.pair_lead_chunk(self.name, cmd_text)
                    else:
                        text = item.get("text", "")
                        if not text and isinstance(item.get("content"), list):
                            text = " ".join(
                                part.get("text", "")
                                for part in item["content"]
                                if isinstance(part, dict)
                            )
                        if text:
                            Display.pair_lead_chunk(self.name, text)
                            content = text if not content else content + "\n" + text
                elif msg_type == "item.delta":
                    delta = entry.get("delta", {})
                    text = delta.get("text")
                    if text:
                        Display.pair_lead_chunk(self.name, text)
                elif msg_type == "turn.completed":
                    usage = entry.get("usage", {})
                    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 1200s",
            )

        duration = time.time() - start

        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=duration, success=False,
                error=stderr or f"Exit code {proc.returncode}",
            )

        if content:
            agent_result = AgentResult(
                content=content, model=self.name, tokens_used=tokens,
                duration_seconds=duration, success=True,
            )
            self._record_usage(agent_result)
            return agent_result

        # Fallback: parse collected output
        full_stdout = "".join(lines_collected)
        parsed = self._parse_output(full_stdout, duration)
        self._record_usage(parsed)
        return parsed

    def _parse_output(self, stdout, duration):
        """Parse codex exec --json JSONL output.

        Each line is a JSON object. We look for:
        - type "item.completed" with item.text for the response
        - type "turn.completed" with usage for token counts
        """
        content = ""
        tokens = 0

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "item.completed":
                item = entry.get("item", {})
                text = item.get("text", "")
                if text:
                    content = text if not content else content + "\n" + text

            elif entry.get("type") == "turn.completed":
                usage = entry.get("usage", {})
                tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        if not content.strip():
            return AgentResult(
                content=content, model=self.name, tokens_used=tokens,
                duration_seconds=duration, success=True,
                error="codex returned empty response"
            )

        return AgentResult(
            content=content,
            model=self.name,
            tokens_used=tokens,
            duration_seconds=duration,
            success=True,
        )
