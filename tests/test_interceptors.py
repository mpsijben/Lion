"""Tests for lion.interceptors module."""

import json
import pytest

from lion.interceptors.base import Chunk, StreamStats, StreamInterceptor
from lion.interceptors.claude import ClaudeInterceptor
from lion.interceptors.gemini import GeminiInterceptor
from lion.interceptors.codex import CodexInterceptor


class TestChunk:
    def test_fields(self):
        c = Chunk(source="claude", text="hello", raw='{"text":"hello"}',
                  timestamp=1.0, stream="stdout")
        assert c.source == "claude"
        assert c.text == "hello"
        assert c.stream == "stdout"


class TestStreamStats:
    def test_ttft_ms_none_when_no_data(self):
        stats = StreamStats()
        assert stats.ttft_ms is None

    def test_ttft_ms_calculated(self):
        stats = StreamStats(started_at=10.0, first_chunk_at=10.5)
        assert stats.ttft_ms == 500

    def test_ttft_ms_zero(self):
        stats = StreamStats(started_at=10.0, first_chunk_at=10.0)
        assert stats.ttft_ms == 0


class TestStreamInterceptorBase:
    def test_name(self):
        si = StreamInterceptor(cwd="/tmp")
        assert si.name == "base"

    def test_build_command_raises(self):
        si = StreamInterceptor()
        with pytest.raises(NotImplementedError):
            si.build_command("hello", resume=False)

    def test_parse_line_raises(self):
        si = StreamInterceptor()
        with pytest.raises(NotImplementedError):
            si.parse_line("line", "stdout")

    def test_chunks_raises_without_start(self):
        si = StreamInterceptor()
        with pytest.raises(RuntimeError, match="Process not started"):
            list(si.chunks())

    def test_terminate_noop_without_proc(self):
        si = StreamInterceptor()
        si.terminate()  # should not raise

    def test_env_sets_lion_no_recurse(self):
        si = StreamInterceptor()
        env = si._env()
        assert env["LION_NO_RECURSE"] == "1"


class TestClaudeInterceptor:
    def test_build_command_initial(self):
        ci = ClaudeInterceptor()
        cmd = ci.build_command("Write code", resume=False)
        assert cmd == ["claude", "-p", "Write code", "--verbose",
                       "--output-format", "stream-json",
                       "--dangerously-skip-permissions"]

    def test_build_command_resume(self):
        ci = ClaudeInterceptor()
        ci.session_id = "sess-123"
        cmd = ci.build_command("Continue", resume=True)
        assert "--resume" in cmd
        assert "sess-123" in cmd

    def test_build_command_resume_without_session(self):
        ci = ClaudeInterceptor()
        cmd = ci.build_command("Continue", resume=True)
        assert "--resume" not in cmd

    def test_parse_line_init_message(self):
        ci = ClaudeInterceptor()
        line = json.dumps({
            "type": "system", "subtype": "init",
            "session_id": "sess-abc"
        })
        chunks = ci.parse_line(line, "stdout")
        assert chunks == []
        assert ci.session_id == "sess-abc"

    def test_parse_line_assistant_text(self):
        ci = ClaudeInterceptor()
        line = json.dumps({
            "type": "assistant",
            "session_id": "sess-abc",
            "message": {"content": [{"text": "def hello():"}]}
        })
        chunks = ci.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert chunks[0].text == "def hello():"
        assert chunks[0].source == "claude"

    def test_parse_line_result_dedup(self):
        ci = ClaudeInterceptor()
        # First: assistant message
        ci.parse_line(json.dumps({
            "type": "assistant",
            "message": {"content": [{"text": "hello"}]}
        }), "stdout")
        # Then: result with same text -- should be deduped
        chunks = ci.parse_line(json.dumps({
            "type": "result", "result": "hello"
        }), "stdout")
        assert chunks == []

    def test_parse_line_result_new_text(self):
        ci = ClaudeInterceptor()
        ci._last_assistant_text = "old"
        chunks = ci.parse_line(json.dumps({
            "type": "result", "result": "new text"
        }), "stdout")
        assert len(chunks) == 1
        assert chunks[0].text == "new text"

    def test_parse_line_invalid_json(self):
        ci = ClaudeInterceptor()
        chunks = ci.parse_line("not json", "stdout")
        assert chunks == []

    def test_parse_line_stderr_ignored(self):
        ci = ClaudeInterceptor()
        chunks = ci.parse_line('{"type":"assistant"}', "stderr")
        assert chunks == []


class TestGeminiInterceptor:
    def test_build_command_initial(self):
        gi = GeminiInterceptor()
        cmd = gi.build_command("Write code", resume=False)
        assert cmd == ["gemini", "-o", "stream-json", "-p", "Write code"]

    def test_build_command_with_model(self):
        gi = GeminiInterceptor(model_hint="flash")
        cmd = gi.build_command("Write code", resume=False)
        assert cmd == ["gemini", "-o", "stream-json", "-m", "gemini-2.5-flash", "-p", "Write code"]

    def test_build_command_resume(self):
        gi = GeminiInterceptor()
        cmd = gi.build_command("Continue", resume=True)
        assert "--resume" in cmd
        assert "latest" in cmd
        assert "-p" in cmd

    def test_parse_line_json_response(self):
        gi = GeminiInterceptor()
        line = json.dumps({"response": "def hello():", "session_id": "gem-1"})
        chunks = gi.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert chunks[0].text == "def hello():"
        assert gi.session_id == "gem-1"

    def test_parse_line_multiline_json_buffering(self):
        gi = GeminiInterceptor()
        # First line: opening brace
        chunks1 = gi.parse_line("{", "stdout")
        assert chunks1 == []
        # Second line: content
        chunks2 = gi.parse_line('  "response": "hello"', "stdout")
        assert chunks2 == []
        # Third line: closing brace
        chunks3 = gi.parse_line("}", "stdout")
        assert len(chunks3) == 1
        assert chunks3[0].text == "hello"

    def test_parse_line_error(self):
        gi = GeminiInterceptor()
        line = json.dumps({"error": {"message": "rate limited"}})
        chunks = gi.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert "ERROR" in chunks[0].text

    def test_parse_line_stderr_ignored(self):
        gi = GeminiInterceptor()
        chunks = gi.parse_line('{"response":"hi"}', "stderr")
        assert chunks == []


class TestCodexInterceptor:
    def test_build_command_initial(self):
        ci = CodexInterceptor()
        cmd = ci.build_command("Write code", resume=False)
        assert cmd == ["codex", "exec", "--json", "Write code"]

    def test_build_command_resume(self):
        ci = CodexInterceptor()
        cmd = ci.build_command("Continue", resume=True)
        assert "resume" in cmd
        assert "--last" in cmd

    def test_parse_line_thread_started(self):
        ci = CodexInterceptor()
        line = json.dumps({"type": "thread.started", "thread_id": "t-123"})
        chunks = ci.parse_line(line, "stdout")
        assert chunks == []
        assert ci.session_id == "t-123"

    def test_parse_line_item_completed(self):
        ci = CodexInterceptor()
        line = json.dumps({
            "type": "item.completed",
            "item": {"text": "def hello():"}
        })
        chunks = ci.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert chunks[0].text == "def hello():"

    def test_parse_line_item_completed_with_content_list(self):
        ci = CodexInterceptor()
        line = json.dumps({
            "type": "item.completed",
            "item": {"content": [{"text": "hello"}, {"text": "world"}]}
        })
        chunks = ci.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert "hello" in chunks[0].text
        assert "world" in chunks[0].text

    def test_parse_line_item_delta(self):
        ci = CodexInterceptor()
        line = json.dumps({
            "type": "item.delta",
            "delta": {"text": "partial"}
        })
        chunks = ci.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert chunks[0].text == "partial"

    def test_parse_line_error(self):
        ci = CodexInterceptor()
        line = json.dumps({"type": "error", "message": "something failed"})
        chunks = ci.parse_line(line, "stdout")
        assert len(chunks) == 1
        assert "ERROR" in chunks[0].text

    def test_parse_line_invalid_json(self):
        ci = CodexInterceptor()
        chunks = ci.parse_line("not json", "stdout")
        assert chunks == []

    def test_parse_line_stderr_ignored(self):
        ci = CodexInterceptor()
        chunks = ci.parse_line('{"type":"error"}', "stderr")
        assert chunks == []
