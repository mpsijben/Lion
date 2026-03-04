"""Tests for lion.providers module."""

import json
import pytest
from unittest.mock import patch, MagicMock

from lion.providers import get_provider, PROVIDERS
from lion.providers.base import Provider, AgentResult, set_quota_recorder
from lion.providers.claude import ClaudeProvider
from lion.providers.gemini import GeminiProvider
from lion.providers.codex import CodexProvider


class TestGetProvider:
    """Tests for get_provider function."""

    def test_get_claude_provider(self):
        """Test getting Claude provider."""
        provider = get_provider("claude")
        assert isinstance(provider, ClaudeProvider)
        assert provider.name == "claude"

    def test_get_gemini_provider(self):
        """Test getting Gemini provider."""
        provider = get_provider("gemini")
        assert isinstance(provider, GeminiProvider)
        assert provider.name == "gemini"

    def test_get_codex_provider(self):
        """Test getting Codex provider."""
        provider = get_provider("codex")
        assert isinstance(provider, CodexProvider)
        assert provider.name == "codex"

    def test_get_unknown_provider_raises(self):
        """Test that unknown provider raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            get_provider("unknown")
        assert "Unknown provider" in str(excinfo.value)
        assert "unknown" in str(excinfo.value)

    def test_providers_registry(self):
        """Test that PROVIDERS registry contains expected providers."""
        assert "claude" in PROVIDERS
        assert "gemini" in PROVIDERS
        assert "codex" in PROVIDERS

    def test_get_claude_with_model(self):
        """Test getting Claude provider with model selection."""
        provider = get_provider("claude.haiku")
        assert isinstance(provider, ClaudeProvider)
        assert provider.name == "claude.haiku"
        assert provider.model_override == "haiku"

    def test_get_claude_opus(self):
        """Test getting Claude provider with opus model."""
        provider = get_provider("claude.opus")
        assert provider.name == "claude.opus"
        assert provider.model_override == "opus"

    def test_get_gemini_with_model(self):
        """Test getting Gemini provider with model selection."""
        provider = get_provider("gemini.flash")
        assert isinstance(provider, GeminiProvider)
        assert provider.name == "gemini.flash"
        assert provider.model_override == "flash"

    def test_get_provider_without_model(self):
        """Test that provider without model has no override."""
        provider = get_provider("claude")
        assert provider.model_override is None

    def test_unknown_provider_with_model_raises(self):
        """Test that unknown provider with model raises ValueError."""
        with pytest.raises(ValueError):
            get_provider("unknown.model")


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_create_successful_result(self):
        """Test creating a successful result."""
        result = AgentResult(
            content="Response content",
            model="claude",
            tokens_used=500,
            duration_seconds=2.5,
            success=True,
        )

        assert result.content == "Response content"
        assert result.model == "claude"
        assert result.tokens_used == 500
        assert result.duration_seconds == 2.5
        assert result.success is True
        assert result.error is None

    def test_create_failed_result(self):
        """Test creating a failed result."""
        result = AgentResult(
            content="",
            model="gemini",
            tokens_used=0,
            duration_seconds=1.0,
            success=False,
            error="Connection timeout",
        )

        assert result.success is False
        assert result.error == "Connection timeout"


class TestClaudeProvider:
    """Tests for ClaudeProvider class."""

    def test_safe_env_sets_no_recurse(self):
        """Test that _safe_env sets LION_NO_RECURSE."""
        provider = ClaudeProvider()
        env = provider._safe_env()
        assert env["LION_NO_RECURSE"] == "1"

    def test_ask_success(self):
        """Test successful ask call."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Claude response", "is_error": False}
        ])
        mock_result.stderr = ""

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result):
            provider = ClaudeProvider()
            result = provider.ask("Test prompt")

        assert result.success is True
        assert result.content == "Claude response"
        assert result.model == "claude"

    def test_ask_with_model_override(self):
        """Test that model override adds --model flag to command."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Response", "is_error": False}
        ])
        mock_result.stderr = ""

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result) as mock_run:
            provider = ClaudeProvider(model="haiku")
            provider.ask("Test prompt")

        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "haiku" in cmd
        assert provider.name == "claude.haiku"

    def test_ask_without_model_no_flag(self):
        """Test that no model override means no --model flag."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Response", "is_error": False}
        ])
        mock_result.stderr = ""

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result) as mock_run:
            provider = ClaudeProvider()
            provider.ask("Test prompt")

        cmd = mock_run.call_args[0][0]
        assert "--model" not in cmd

    def test_ask_timeout(self):
        """Test ask with timeout."""
        import subprocess

        with patch("lion.providers.claude.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 300)):
            provider = ClaudeProvider()
            result = provider.ask("Test prompt")

        assert result.success is False
        assert "Timeout" in result.error

    def test_ask_non_zero_exit(self):
        """Test ask with non-zero exit code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error occurred"

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result):
            provider = ClaudeProvider()
            result = provider.ask("Test prompt")

        assert result.success is False
        assert result.error == "Error occurred"

    def test_ask_with_files(self):
        """Test ask_with_files includes file contents."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Response", "is_error": False}
        ])

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result) as mock_run:
            with patch("builtins.open", MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="file content"))),
                __exit__=MagicMock(return_value=False)
            ))):
                provider = ClaudeProvider()
                result = provider.ask_with_files("Prompt", ["file.py"])

        assert result.success is True
        # Check that prompt includes file content
        call_args = mock_run.call_args[0][0]
        prompt_arg_idx = call_args.index("-p") + 1
        assert "FILES:" in call_args[prompt_arg_idx]

    def test_implement_success(self):
        """Test successful implement call with streaming Popen."""
        # stream-json: each line is a JSON object
        stream_lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "implementing..."}]}}) + "\n",
            json.dumps({"type": "result", "result": "Code implemented", "is_error": False}) + "\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(stream_lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("lion.providers.claude.subprocess.Popen", return_value=mock_proc):
            provider = ClaudeProvider()
            result = provider.implement("Build feature")

        assert result.success is True
        assert result.content == "Code implemented"

    def test_parse_output_array_format(self):
        """Test parsing JSON array output format."""
        provider = ClaudeProvider()
        stdout = json.dumps([
            {"type": "content", "content": "some content"},
            {"type": "result", "result": "final result", "is_error": False}
        ])

        result = provider._parse_output(stdout, 1.0)

        assert result.content == "final result"
        assert result.success is True

    def test_parse_output_dict_format(self):
        """Test parsing JSON dict output format (fallback)."""
        provider = ClaudeProvider()
        stdout = json.dumps({"result": "response"})

        result = provider._parse_output(stdout, 1.0)

        assert result.content == "response"

    def test_parse_output_raw_text(self):
        """Test parsing raw text output."""
        provider = ClaudeProvider()
        stdout = "Raw text response"

        result = provider._parse_output(stdout, 1.0)

        assert result.content == "Raw text response"


class TestGeminiProvider:
    """Tests for GeminiProvider class."""

    def test_safe_env_sets_no_recurse(self):
        """Test that _safe_env sets LION_NO_RECURSE."""
        provider = GeminiProvider()
        env = provider._safe_env()
        assert env["LION_NO_RECURSE"] == "1"

    def test_ask_success(self):
        """Test successful ask call."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "response": "Gemini response",
            "stats": {"models": {"gemini": {"tokens": {"total": 100}}}}
        })

        with patch("lion.providers.gemini.subprocess.run", return_value=mock_result):
            provider = GeminiProvider()
            result = provider.ask("Test prompt")

        assert result.success is True
        assert result.content == "Gemini response"
        assert result.model == "gemini"
        assert result.tokens_used == 100

    def test_ask_timeout(self):
        """Test ask with timeout."""
        import subprocess

        with patch("lion.providers.gemini.subprocess.run", side_effect=subprocess.TimeoutExpired("gemini", 300)):
            provider = GeminiProvider()
            result = provider.ask("Test prompt")

        assert result.success is False
        assert "Timeout" in result.error

    def test_implement_uses_yolo_flag(self):
        """Test that implement uses --yolo flag with streaming Popen."""
        stream_lines = [
            json.dumps({"type": "message", "role": "assistant", "content": "Done"}) + "\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(stream_lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("lion.providers.gemini.subprocess.Popen", return_value=mock_proc) as mock_popen:
            provider = GeminiProvider()
            provider.implement("Build feature")

        call_args = mock_popen.call_args[0][0]
        assert "--yolo" in call_args

    def test_parse_output_empty_response(self):
        """Test parsing empty response."""
        provider = GeminiProvider()
        stdout = json.dumps({"response": "", "stats": {}})

        result = provider._parse_output(stdout, 1.0)

        assert result.success is True
        assert result.error == "gemini returned empty response"


class TestCodexProvider:
    """Tests for CodexProvider class."""

    def test_safe_env_sets_no_recurse(self):
        """Test that _safe_env sets LION_NO_RECURSE."""
        env = CodexProvider._safe_env()
        assert env["LION_NO_RECURSE"] == "1"

    def test_ask_success(self):
        """Test successful ask call."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"type": "item.completed", "item": {"text": "Codex response"}}\n'
            '{"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 100}}\n'
        )

        with patch("lion.providers.codex.subprocess.run", return_value=mock_result):
            provider = CodexProvider()
            result = provider.ask("Test prompt")

        assert result.success is True
        assert result.content == "Codex response"
        assert result.model == "codex"
        assert result.tokens_used == 150

    def test_ask_uses_full_auto(self):
        """Test that ask uses --full-auto flag."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"type": "item.completed", "item": {"text": "response"}}\n'

        with patch("lion.providers.codex.subprocess.run", return_value=mock_result) as mock_run:
            provider = CodexProvider()
            provider.ask("Test prompt")

        call_args = mock_run.call_args[0][0]
        assert "--full-auto" in call_args

    def test_implement_uses_bypass_sandbox(self):
        """Test that implement uses --dangerously-bypass-approvals-and-sandbox with streaming Popen."""
        stream_lines = [
            '{"type": "item.completed", "item": {"text": "done"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(stream_lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("lion.providers.codex.subprocess.Popen", return_value=mock_proc) as mock_popen:
            provider = CodexProvider()
            provider.implement("Build feature")

        call_args = mock_popen.call_args[0][0]
        assert "--dangerously-bypass-approvals-and-sandbox" in call_args

    def test_parse_output_multiple_items(self):
        """Test parsing output with multiple item.completed entries."""
        provider = CodexProvider()
        stdout = (
            '{"type": "item.completed", "item": {"text": "Part 1"}}\n'
            '{"type": "item.completed", "item": {"text": "Part 2"}}\n'
            '{"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 200}}\n'
        )

        result = provider._parse_output(stdout, 2.0)

        assert "Part 1" in result.content
        assert "Part 2" in result.content
        assert result.tokens_used == 300

    def test_parse_output_empty_response(self):
        """Test parsing empty response."""
        provider = CodexProvider()
        stdout = '{"type": "turn.completed", "usage": {}}\n'

        result = provider._parse_output(stdout, 1.0)

        assert result.success is True
        assert result.error == "codex returned empty response"

    def test_parse_output_invalid_json_lines(self):
        """Test parsing with invalid JSON lines."""
        provider = CodexProvider()
        stdout = (
            'not valid json\n'
            '{"type": "item.completed", "item": {"text": "valid"}}\n'
            'also invalid\n'
        )

        result = provider._parse_output(stdout, 1.0)

        assert result.content == "valid"


class TestProviderEdgeCases:
    """Edge case tests for providers."""

    def test_claude_empty_response_flagged(self):
        """Test that Claude empty response is flagged."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "", "is_error": False}
        ])

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result):
            provider = ClaudeProvider()
            result = provider.ask("Test")

        assert result.success is True
        assert result.error == "claude -p returned empty response"

    def test_claude_error_result(self):
        """Test Claude result with is_error=True."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Error message", "is_error": True}
        ])

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result):
            provider = ClaudeProvider()
            result = provider.ask("Test")

        assert result.success is False
        assert result.error == "Error message"

    def test_provider_with_custom_cwd(self):
        """Test provider respects custom working directory."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Done", "is_error": False}
        ])

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result) as mock_run:
            provider = ClaudeProvider()
            provider.ask("Test", cwd="/custom/path")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == "/custom/path"

    def test_provider_with_system_prompt(self):
        """Test provider with system prompt."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"type": "result", "result": "Done", "is_error": False}
        ])

        with patch("lion.providers.claude.subprocess.run", return_value=mock_result) as mock_run:
            provider = ClaudeProvider()
            provider.ask("Test", system_prompt="You are a helpful assistant")

        call_args = mock_run.call_args[0][0]
        assert "--system-prompt" in call_args
        assert "You are a helpful assistant" in call_args


class TestProviderQuotaTracking:
    """Tests for quota usage tracking integration."""

    def teardown_method(self):
        """Reset global quota recorder after each test."""
        set_quota_recorder(None)

    def test_gemini_ask_records_quota_usage(self):
        """Successful Gemini calls with tokens should be recorded."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "response": "Gemini response",
            "stats": {"models": {"gemini": {"tokens": {"total": 123}}}},
        })

        recorded = []
        set_quota_recorder(lambda model, tokens: recorded.append((model, tokens)) or True)

        with patch("lion.providers.gemini.subprocess.run", return_value=mock_result):
            provider = GeminiProvider()
            result = provider.ask("Test prompt")

        assert result.success is True
        assert recorded == [("gemini", 123)]

    def test_codex_ask_records_quota_usage(self):
        """Successful Codex calls with tokens should be recorded."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"type": "item.completed", "item": {"text": "Codex response"}}\n'
            '{"type": "turn.completed", "usage": {"input_tokens": 40, "output_tokens": 60}}\n'
        )

        recorded = []
        set_quota_recorder(lambda model, tokens: recorded.append((model, tokens)) or True)

        with patch("lion.providers.codex.subprocess.run", return_value=mock_result):
            provider = CodexProvider()
            result = provider.ask("Test prompt")

        assert result.success is True
        assert recorded == [("codex", 100)]

    def test_failed_call_does_not_record_quota_usage(self):
        """Failed provider calls should not be recorded."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error occurred"

        recorded = []
        set_quota_recorder(lambda model, tokens: recorded.append((model, tokens)) or True)

        with patch("lion.providers.codex.subprocess.run", return_value=mock_result):
            provider = CodexProvider()
            result = provider.ask("Test prompt")

        assert result.success is False
        assert recorded == []
