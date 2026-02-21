"""Tests for lion.lion module (main entry point)."""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from lion.lion import load_config, detect_complexity, main


# Helper to clear LION_NO_RECURSE for tests that need to test main()
@pytest.fixture
def clear_no_recurse():
    """Clear LION_NO_RECURSE env var for tests."""
    old_value = os.environ.pop("LION_NO_RECURSE", None)
    yield
    if old_value is not None:
        os.environ["LION_NO_RECURSE"] = old_value


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_no_file_exists(self, temp_dir):
        """Test loading config when no config file exists."""
        # Also patch expanduser to avoid ~/.lion/config.toml
        with patch("lion.lion.LION_DIR", temp_dir):
            with patch("os.path.expanduser", return_value=os.path.join(temp_dir, "nonexistent")):
                config = load_config()
                assert config == {}

    def test_load_config_from_config_toml(self, temp_dir):
        """Test loading config from config.toml."""
        config_content = b"""
[providers]
default = "claude"

[complexity]
high_signals = ["build", "create"]
"""
        config_path = os.path.join(temp_dir, "config.toml")
        with open(config_path, "wb") as f:
            f.write(config_content)

        with patch("lion.lion.LION_DIR", temp_dir):
            config = load_config()
            assert config["providers"]["default"] == "claude"
            assert "build" in config["complexity"]["high_signals"]

    def test_load_config_fallback_to_default(self, temp_dir):
        """Test loading config falls back to config.default.toml."""
        config_content = b"""
[providers]
default = "gemini"
"""
        config_path = os.path.join(temp_dir, "config.default.toml")
        with open(config_path, "wb") as f:
            f.write(config_content)

        with patch("lion.lion.LION_DIR", temp_dir):
            config = load_config()
            assert config["providers"]["default"] == "gemini"

    def test_load_config_prefers_config_over_default(self, temp_dir):
        """Test that config.toml takes precedence over config.default.toml."""
        # Create config.default.toml
        with open(os.path.join(temp_dir, "config.default.toml"), "wb") as f:
            f.write(b'[providers]\ndefault = "gemini"\n')

        # Create config.toml
        with open(os.path.join(temp_dir, "config.toml"), "wb") as f:
            f.write(b'[providers]\ndefault = "claude"\n')

        with patch("lion.lion.LION_DIR", temp_dir):
            config = load_config()
            assert config["providers"]["default"] == "claude"

    def test_load_config_handles_invalid_toml(self, temp_dir):
        """Test loading config handles invalid TOML gracefully."""
        config_path = os.path.join(temp_dir, "config.toml")
        with open(config_path, "wb") as f:
            f.write(b"this is not valid toml [[[")

        with patch("lion.lion.LION_DIR", temp_dir):
            with patch("os.path.expanduser", return_value=os.path.join(temp_dir, "nonexistent")):
                config = load_config()
                # Should return empty dict on parse error (falls through to no config)
                assert config == {}


class TestDetectComplexity:
    """Tests for detect_complexity function."""

    def test_high_complexity_signals(self):
        """Test detection of high complexity tasks."""
        config = {}
        assert detect_complexity("Build a complete system", config) == "high"
        assert detect_complexity("Create an architecture", config) == "high"
        assert detect_complexity("Design and architect the full solution", config) == "high"

    def test_low_complexity_signals(self):
        """Test detection of low complexity tasks."""
        config = {}
        assert detect_complexity("Fix a typo in the README", config) == "low"
        assert detect_complexity("Rename the variable", config) == "low"
        assert detect_complexity("Delete the unused file", config) == "low"

    def test_medium_complexity_default(self):
        """Test that ambiguous tasks return medium complexity."""
        config = {}
        assert detect_complexity("Add a feature", config) == "medium"
        # "update" is a low signal, so this is low complexity
        assert detect_complexity("Something neutral", config) == "medium"

    def test_custom_signals_from_config(self):
        """Test using custom signals from config.

        Note: The implementation uses config signals as ADDITIONAL signals,
        not REPLACEMENT signals. So we test that custom signals work alongside defaults.
        """
        config = {
            "complexity": {
                "high_signals": ["epic", "massive"],
                "low_signals": ["tiny", "minor"],
            }
        }
        # "epic" is a custom high signal but the default signals are still used
        # The implementation merges/adds these - but let's test the actual behavior
        # If custom signals completely replace defaults, "epic" alone would trigger high
        result = detect_complexity("Make an epic massive change", config)
        # With 2 high signals, should be high
        assert result == "high"

        result = detect_complexity("A tiny minor thing", config)
        # With 2 low signals, should be low
        assert result == "low"

    def test_case_insensitive(self):
        """Test that detection is case insensitive."""
        config = {}
        assert detect_complexity("BUILD a system", config) == "high"
        assert detect_complexity("FIX a BUG", config) == "low"

    def test_multiple_signals_high_wins(self):
        """Test that multiple high signals outweigh low."""
        config = {}
        # "build" + "create" + "design" (3 high) vs "fix" (1 low)
        result = detect_complexity("Build and create and design, also fix", config)
        assert result == "high"

    def test_empty_prompt(self):
        """Test empty prompt returns medium."""
        config = {}
        assert detect_complexity("", config) == "medium"


class TestMainFunction:
    """Tests for main() function."""

    def test_no_args_shows_help(self, capsys, clear_no_recurse):
        """Test that running with no args shows help."""
        with patch.object(sys, "argv", ["lion"]):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert "Lion" in captured.out
        assert "Usage:" in captured.out

    def test_recursive_call_blocked(self, capsys):
        """Test that recursive calls are blocked."""
        with patch.dict(os.environ, {"LION_NO_RECURSE": "1"}):
            with patch.object(sys, "argv", ["lion", "test prompt"]):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert "recursive call blocked" in captured.out

    def test_creates_run_directory(self, temp_dir, clear_no_recurse):
        """Test that main creates run directory."""
        with patch.dict(os.environ, {"LION_CWD": temp_dir}, clear=False):
            with patch.object(sys, "argv", ["lion", "test prompt"]):
                with patch("lion.lion.Display"):
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        mock_result = MagicMock()
                        mock_result.content = "Test result"
                        mock_result.success = True
                        mock_result.agent_summaries = []
                        mock_result.final_decision = None
                        mock_result.files_changed = []
                        mock_result.steps_completed = 1
                        mock_result.total_steps = 1
                        mock_result.total_duration = 1.0
                        mock_result.errors = []
                        MockExecutor.return_value.run.return_value = mock_result

                        main()

                        # Check that executor was called with correct params
                        call_kwargs = MockExecutor.call_args[1]
                        assert "run_dir" in call_kwargs
                        assert ".lion/runs" in call_kwargs["run_dir"]

    def test_hook_mode_outputs_json_summary(self, temp_dir, capsys, clear_no_recurse):
        """Test that hook mode outputs LION_SUMMARY."""
        with patch.dict(os.environ, {
            "LION_CWD": temp_dir,
            "LION_SESSION_ID": "test-session"
        }, clear=False):
            with patch.object(sys, "argv", ["lion", "test prompt"]):
                with patch("lion.lion.Display") as MockDisplay:
                    MockDisplay.format_completion_summary.return_value = "Lion voltooid!"
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        mock_result = MagicMock()
                        mock_result.content = "Test result"
                        mock_result.success = True
                        mock_result.agent_summaries = []
                        mock_result.final_decision = None
                        mock_result.files_changed = []
                        mock_result.steps_completed = 1
                        mock_result.total_steps = 1
                        mock_result.total_duration = 1.0
                        mock_result.errors = []
                        MockExecutor.return_value.run.return_value = mock_result

                        main()

        captured = capsys.readouterr()
        assert "LION_SUMMARY:" in captured.out

    def test_joins_multiple_args(self, temp_dir, clear_no_recurse):
        """Test that multiple args are joined into prompt."""
        with patch.dict(os.environ, {"LION_CWD": temp_dir}, clear=False):
            with patch.object(sys, "argv", ["lion", "Build", "a", "feature"]):
                with patch("lion.lion.Display"):
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        mock_result = MagicMock()
                        mock_result.content = ""
                        mock_result.success = True
                        mock_result.agent_summaries = []
                        mock_result.final_decision = None
                        mock_result.files_changed = []
                        mock_result.steps_completed = 0
                        mock_result.total_steps = 0
                        mock_result.total_duration = 1.0
                        mock_result.errors = []
                        MockExecutor.return_value.run.return_value = mock_result

                        main()

                        call_kwargs = MockExecutor.call_args[1]
                        assert call_kwargs["prompt"] == "Build a feature"


class TestMainExceptionHandling:
    """Tests for exception handling in main()."""

    def test_keyboard_interrupt_handling(self, temp_dir, capsys, clear_no_recurse):
        """Test that KeyboardInterrupt is handled gracefully."""
        with patch.dict(os.environ, {"LION_CWD": temp_dir}, clear=False):
            with patch.object(sys, "argv", ["lion", "test"]):
                with patch("lion.lion.Display"):
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        MockExecutor.return_value.run.side_effect = KeyboardInterrupt()

                        # Should not raise
                        main()

    def test_exception_handling_reraises(self, temp_dir, clear_no_recurse):
        """Test that other exceptions are re-raised."""
        with patch.dict(os.environ, {"LION_CWD": temp_dir}, clear=False):
            with patch.object(sys, "argv", ["lion", "test"]):
                with patch("lion.lion.Display"):
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        MockExecutor.return_value.run.side_effect = ValueError("Test error")

                        with pytest.raises(ValueError):
                            main()

    def test_hook_mode_outputs_error_summary(self, temp_dir, capsys, clear_no_recurse):
        """Test that hook mode outputs error summary on exception."""
        with patch.dict(os.environ, {
            "LION_CWD": temp_dir,
            "LION_SESSION_ID": "test-session"
        }, clear=False):
            with patch.object(sys, "argv", ["lion", "test"]):
                with patch("lion.lion.Display"):
                    with patch("lion.lion.PipelineExecutor") as MockExecutor:
                        MockExecutor.return_value.run.side_effect = ValueError("Test error")

                        with pytest.raises(ValueError):
                            main()

        captured = capsys.readouterr()
        assert "LION_SUMMARY:" in captured.out
        assert "Test error" in captured.out
