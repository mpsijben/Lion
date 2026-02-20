"""Tests for lion.hook module."""

import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

from lion.hook import extract_summary, main


class TestExtractSummary:
    """Tests for extract_summary function."""

    def test_extract_valid_summary(self):
        """Test extracting valid LION_SUMMARY from stdout."""
        summary_data = {"success": True, "summary": "Lion completed"}
        stdout = f"Some output\nLION_SUMMARY:{json.dumps(summary_data)}\nMore output"

        result = extract_summary(stdout)
        assert result == summary_data

    def test_extract_summary_no_match(self):
        """Test extracting when no LION_SUMMARY present."""
        stdout = "Just some regular output\nNo summary here"
        result = extract_summary(stdout)
        assert result is None

    def test_extract_summary_empty_stdout(self):
        """Test extracting from empty stdout."""
        result = extract_summary("")
        assert result is None

    def test_extract_summary_none_stdout(self):
        """Test extracting from None stdout."""
        result = extract_summary(None)
        assert result is None

    def test_extract_summary_invalid_json(self):
        """Test extracting when JSON is invalid."""
        stdout = "LION_SUMMARY:not valid json"
        result = extract_summary(stdout)
        assert result is None

    def test_extract_summary_first_match(self):
        """Test that first valid LION_SUMMARY is extracted."""
        summary1 = {"success": True, "summary": "First"}
        summary2 = {"success": False, "summary": "Second"}
        stdout = f"LION_SUMMARY:{json.dumps(summary1)}\nLION_SUMMARY:{json.dumps(summary2)}"

        result = extract_summary(stdout)
        assert result["summary"] == "First"

    def test_extract_summary_complex_data(self):
        """Test extracting complex summary data."""
        summary_data = {
            "success": True,
            "summary": "Lion completed",
            "agent_summaries": [
                {"agent": "agent_1", "summary": "Built feature"},
                {"agent": "agent_2", "summary": "Reviewed code"},
            ],
            "final_decision": "Use approach A",
            "files_changed": ["src/main.py", "tests/test_main.py"],
            "duration": 45.5,
        }
        stdout = f"LION_SUMMARY:{json.dumps(summary_data)}"

        result = extract_summary(stdout)
        assert result == summary_data
        assert len(result["agent_summaries"]) == 2


class TestHookMain:
    """Tests for hook main function."""

    def test_non_lion_prompt_exits_silently(self, capsys):
        """Test that non-lion prompts exit with code 0."""
        hook_input = json.dumps({"prompt": "Just a regular prompt"})

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_invalid_json_exits_silently(self):
        """Test that invalid JSON input exits with code 0."""
        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value="not json"))):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 0

    def test_lion_prompt_triggers_subprocess(self):
        """Test that lion prompt triggers subprocess execution."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
            "cwd": "/tmp",
            "session_id": "test-123",
        })

        mock_result = MagicMock()
        mock_result.stdout = 'LION_SUMMARY:{"success": true, "summary": "Done"}'
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result) as mock_run:
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

                # Verify subprocess was called
                mock_run.assert_called_once()
                call_args = mock_run.call_args
                assert "-m" in call_args[0][0]
                assert "lion" in call_args[0][0]

    def test_lion_prompt_case_insensitive(self):
        """Test that lion prefix is case insensitive."""
        hook_input = json.dumps({
            "prompt": "LION Build a feature",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

    def test_lion_prompt_with_xml_tags(self):
        """Test that lion prompt is extracted from prompts with XML tags."""
        hook_input = json.dumps({
            "prompt": "<ide_opened_file>main.py</ide_opened_file>\nlion Build a feature",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result) as mock_run:
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0
                mock_run.assert_called_once()

    def test_outputs_context_for_claude(self, capsys):
        """Test that hook outputs context for Claude."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = 'LION_SUMMARY:{"success": true, "summary": "Feature built"}'
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert "<lion-result>" in captured.out
        assert "Feature built" in captured.out
        assert "</lion-result>" in captured.out

    def test_handles_subprocess_failure(self, capsys):
        """Test that subprocess failure is handled."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error occurred"
        mock_result.returncode = 1

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert "exit code 1" in captured.out

    def test_handles_subprocess_exception(self, capsys):
        """Test that subprocess exception is handled."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
            "cwd": "/tmp",
        })

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", side_effect=Exception("Process failed")):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

        captured = capsys.readouterr()
        assert "kon niet starten" in captured.out

    def test_sets_environment_variables(self):
        """Test that proper environment variables are set."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
            "cwd": "/tmp/project",
            "session_id": "session-abc",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result) as mock_run:
                with pytest.raises(SystemExit):
                    main()

                # Check environment variables
                call_kwargs = mock_run.call_args[1]
                env = call_kwargs["env"]
                assert env["LION_SESSION_ID"] == "session-abc"
                assert env["LION_CWD"] == "/tmp/project"

    def test_uses_default_cwd(self):
        """Test that default cwd is used when not provided."""
        hook_input = json.dumps({
            "prompt": "lion Build a feature",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result) as mock_run:
                with patch("lion.hook.os.getcwd", return_value="/default/cwd"):
                    with pytest.raises(SystemExit):
                        main()

                    call_kwargs = mock_run.call_args[1]
                    assert call_kwargs["cwd"] == "/default/cwd"


class TestHookEdgeCases:
    """Edge case tests for hook module."""

    def test_empty_prompt(self):
        """Test handling of empty prompt."""
        hook_input = json.dumps({"prompt": ""})

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 0

    def test_prompt_with_only_lion(self):
        """Test handling of prompt that's just 'lion'."""
        hook_input = json.dumps({"prompt": "lion"})

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with pytest.raises(SystemExit) as excinfo:
                main()
            # "lion" without space after is not a lion command
            assert excinfo.value.code == 0

    def test_prompt_lion_with_space_only(self):
        """Test handling of 'lion ' with just space."""
        hook_input = json.dumps({
            "prompt": "lion ",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result):
                with pytest.raises(SystemExit) as excinfo:
                    main()
                assert excinfo.value.code == 0

    def test_multiline_prompt_with_lion_in_middle(self):
        """Test multiline prompt where lion is not first."""
        hook_input = json.dumps({
            "prompt": "Some other content\nlion Build feature\nMore content",
            "cwd": "/tmp",
        })

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch.object(sys, "stdin", MagicMock(read=MagicMock(return_value=hook_input))):
            with patch("lion.hook.subprocess.run", return_value=mock_result) as mock_run:
                with pytest.raises(SystemExit):
                    main()
                # Should still trigger lion
                mock_run.assert_called_once()
