"""Gemini CLI provider - wraps `gemini` CLI."""

import subprocess
import json
import os
import time
import threading
from .base import Provider, AgentResult

# Class-level rate limiter shared across all GeminiProvider instances.
# Ensures parallel pride agents don't exhaust the API quota.
_gemini_lock = threading.Lock()
_gemini_last_call = 0.0
_GEMINI_MIN_INTERVAL = 4.0  # seconds between calls (15 RPM safe)


def _wait_for_rate_limit():
    """Wait if needed to respect Gemini rate limits."""
    global _gemini_last_call
    with _gemini_lock:
        now = time.time()
        elapsed = now - _gemini_last_call
        if elapsed < _GEMINI_MIN_INTERVAL:
            wait = _GEMINI_MIN_INTERVAL - elapsed
            time.sleep(wait)
        _gemini_last_call = time.time()


class GeminiProvider(Provider):
    name = "gemini"

    # Default to Flash - Pro Preview has severe capacity limits on free tier.
    # Override with gemini.gemini-3-pro-preview if you have a paid plan.
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, model=None, config=None):
        super().__init__(model or self.DEFAULT_MODEL, config)
        if model:
            self.name = f"gemini.{model}"
        self._session_id = None
        self._has_session = False

    def _safe_env(self):
        """Create env that prevents recursive lion calls from child processes
        and passes through the current session ID.
        """
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        if self._session_id:
            env["LION_SESSION_ID"] = self._session_id
        return env

    def ask(self, prompt, system_prompt="", cwd=".", resume=True):
        """Use gemini CLI for non-interactive single-turn queries."""
        _wait_for_rate_limit()

        system_prompt = self._get_effective_system_prompt(system_prompt)
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd = ["gemini", "-o", "json"]
        if self.model_override:
            cmd.extend(["-m", self.model_override])
        if resume and (self._has_session or self._session_id):
            # Gemini CLI uses --resume (latest/index) for session continuation.
            cmd.extend(["--resume", "latest"])
        cmd.extend(["-p", full_prompt])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=self.timeout,
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
        if parsed.session_id:
            self._session_id = parsed.session_id
        if parsed.success:
            self._has_session = True
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

    def ask_fresh(self, prompt, system_prompt="", cwd="."):
        """New session, for parallel propose calls."""
        return self.ask(prompt, system_prompt, cwd, resume=False)

    def implement(self, prompt, cwd="."):
        """Use gemini CLI with streaming to make actual file changes.

        Streams output via Display.pair_lead_chunk() so the TUI can show
        progress in real time.
        """
        from ..display import Display

        _wait_for_rate_limit()

        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = ["gemini", "-o", "stream-json", "--yolo"]
        if self.model_override:
            cmd.extend(["-m", self.model_override])
        if self._has_session or self._session_id:
            cmd.extend(["--resume", "latest"])
        cmd.extend(["-p", impl_prompt])

        env = self._safe_env()

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=cwd, env=env,
            )
        except Exception as e:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=str(e),
            )

        # Stream stdout, parsing Gemini stream-json (may be multi-line JSON)
        lines_collected = []
        json_buffer = ""
        result_content = ""
        session_id = None
        try:
            for line in proc.stdout:
                lines_collected.append(line)
                if not line.strip():
                    continue
                # Gemini may emit multi-line JSON; buffer until parseable
                stripped = line.strip()
                if json_buffer or stripped.startswith("{"):
                    json_buffer = f"{json_buffer}\n{line}".strip()
                    try:
                        entry = json.loads(json_buffer)
                        json_buffer = ""
                    except json.JSONDecodeError:
                        continue
                else:
                    continue

                if not isinstance(entry, dict):
                    continue

                if entry.get("session_id"):
                    session_id = entry["session_id"]

                entry_type = entry.get("type", "")
                if entry_type == "tool_use":
                    params = entry.get("parameters", {})
                    code = params.get("content", "") or params.get("command", "")
                    if code:
                        Display.pair_lead_chunk(self.name, code)
                elif entry_type == "message" and entry.get("role") == "assistant":
                    content = entry.get("content", "")
                    if content:
                        Display.pair_lead_chunk(self.name, content)
                        result_content += content
                elif entry_type == "result":
                    pass  # stats only
                elif "response" in entry:
                    resp = entry["response"]
                    if resp:
                        Display.pair_lead_chunk(self.name, resp)
                        result_content = resp

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

        if session_id:
            self._session_id = session_id
        self._has_session = True

        if result_content:
            agent_result = AgentResult(
                content=result_content, model=self.name, tokens_used=0,
                duration_seconds=duration, success=True,
                session_id=session_id,
            )
            self._record_usage(agent_result)
            return agent_result

        # Fallback: parse collected output as regular JSON
        full_stdout = "".join(lines_collected)
        parsed = self._parse_output(full_stdout, duration)
        if parsed.session_id:
            self._session_id = parsed.session_id
        self._record_usage(parsed)
        return parsed

    def _parse_output(self, stdout, duration):
        """Parse gemini -o json output.

        Gemini returns: {"response": "...", "stats": {...}, "session_id": "..."}
        """
        parsed_session_id = None
        try:
            output = json.loads(stdout)

            if isinstance(output, dict):
                content = output.get("response", "")
                tokens = 0
                stats = output.get("stats", {})
                for model_stats in stats.get("models", {}).values():
                    tokens += model_stats.get("tokens", {}).get("total", 0)
                parsed_session_id = output.get("session_id")

                parsed = AgentResult(
                    content=content,
                    model=self.name,
                    tokens_used=tokens,
                    duration_seconds=duration,
                    success=True,
                    session_id=parsed_session_id,
                )

                if not content.strip():
                    parsed.error = "gemini returned empty response"

                return parsed

        except json.JSONDecodeError:
            pass

        # Raw text fallback
        return AgentResult(
            content=stdout, model=self.name, tokens_used=0,
            duration_seconds=duration, success=True,
            session_id=parsed_session_id,
        )
