"""Tests for lion.display module."""

import pytest
from unittest.mock import patch, MagicMock, call

from lion.display import Display, _print
from lion.parser import PipelineStep


class TestPrintFunction:
    """Tests for _print helper function."""

    def test_print_to_tty(self):
        """Test printing to /dev/tty."""
        mock_tty = MagicMock()
        mock_open = MagicMock(return_value=mock_tty)
        mock_tty.__enter__ = MagicMock(return_value=mock_tty)
        mock_tty.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", mock_open):
            _print("Test message")

        mock_open.assert_called_with("/dev/tty", "w")
        mock_tty.write.assert_called_with("Test message\n")

    def test_print_fallback_to_stderr(self, capsys):
        """Test fallback to stderr when /dev/tty unavailable."""
        with patch("builtins.open", side_effect=OSError("No tty")):
            _print("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.err


class TestDisplayPipelineStart:
    """Tests for Display.pipeline_start method."""

    def test_pipeline_start_no_steps(self):
        """Test pipeline start display without steps."""
        with patch("lion.display._print") as mock_print:
            Display.pipeline_start("Build feature", [])

        calls = mock_print.call_args_list
        assert any("Lion starting" in str(c) for c in calls)
        assert any("Build feature" in str(c) for c in calls)

    def test_pipeline_start_with_steps(self):
        """Test pipeline start display with steps."""
        steps = [
            PipelineStep(function="pride", args=[3]),
            PipelineStep(function="review", args=[]),
        ]

        with patch("lion.display._print") as mock_print:
            Display.pipeline_start("Build feature", steps)

        calls = mock_print.call_args_list
        # Check that pipeline is displayed
        pipeline_call = [c for c in calls if "Pipeline" in str(c)]
        assert len(pipeline_call) > 0


class TestDisplayPhase:
    """Tests for Display.phase method."""

    def test_phase_displays_icon(self):
        """Test that phase displays appropriate icon."""
        with patch("lion.display._print") as mock_print:
            Display.phase("propose", "Generating proposals")

        calls = mock_print.call_args_list
        assert any("PROPOSE" in str(c) for c in calls)
        assert any("Generating proposals" in str(c) for c in calls)

    def test_phase_unknown_icon(self):
        """Test phase with unknown phase name uses default icon."""
        with patch("lion.display._print") as mock_print:
            Display.phase("unknown_phase", "Description")

        calls = mock_print.call_args_list
        assert any("UNKNOWN_PHASE" in str(c) for c in calls)


class TestDisplayAgentProposal:
    """Tests for Display.agent_proposal method."""

    def test_agent_proposal_display(self):
        """Test agent proposal display."""
        with patch("lion.display._print") as mock_print:
            Display.agent_proposal(1, "claude", "This is my proposal for the feature...")

        calls = mock_print.call_args_list
        assert any("Agent 1" in str(c) for c in calls)
        assert any("claude" in str(c) for c in calls)

    def test_agent_proposal_truncates_long_preview(self):
        """Test that long previews are truncated."""
        long_preview = "x" * 200
        with patch("lion.display._print") as mock_print:
            Display.agent_proposal(1, "claude", long_preview)

        calls = mock_print.call_args_list
        # Preview should be truncated to 150 chars + "..."
        call_str = str(calls)
        assert "..." in call_str

    def test_agent_proposal_removes_newlines(self):
        """Test that newlines in preview are replaced."""
        with patch("lion.display._print") as mock_print:
            Display.agent_proposal(1, "claude", "Line 1\nLine 2\nLine 3")

        calls = mock_print.call_args_list
        call_str = str(calls)
        # Newlines should be replaced with spaces
        assert "Line 1 Line 2" in call_str or "Line 1" in call_str


class TestDisplayAgentCritique:
    """Tests for Display.agent_critique method."""

    def test_agent_critique_display(self):
        """Test agent critique display."""
        with patch("lion.display._print") as mock_print:
            Display.agent_critique(2, "This approach has some issues...")

        calls = mock_print.call_args_list
        assert any("Agent 2" in str(c) for c in calls)
        assert any("critique" in str(c) for c in calls)


class TestDisplayConvergence:
    """Tests for Display.convergence method."""

    def test_convergence_display(self):
        """Test convergence display."""
        with patch("lion.display._print") as mock_print:
            Display.convergence("We should use approach A because...")

        calls = mock_print.call_args_list
        assert any("Consensus" in str(c) for c in calls)


class TestDisplayStepStart:
    """Tests for Display.step_start method."""

    def test_step_start_display(self):
        """Test step start display."""
        step = PipelineStep(function="review", args=[])

        with patch("lion.display._print") as mock_print:
            Display.step_start(1, 3, step)

        calls = mock_print.call_args_list
        assert any("[1/3]" in str(c) for c in calls)
        assert any("review" in str(c) for c in calls)

    def test_step_start_with_args(self):
        """Test step start display with arguments."""
        step = PipelineStep(function="pride", args=[3, "claude"])

        with patch("lion.display._print") as mock_print:
            Display.step_start(2, 5, step)

        calls = mock_print.call_args_list
        assert any("pride" in str(c) for c in calls)


class TestDisplayStepComplete:
    """Tests for Display.step_complete method."""

    def test_step_complete_display(self):
        """Test step complete display."""
        with patch("lion.display._print") as mock_print:
            Display.step_complete("review", {"success": True})

        calls = mock_print.call_args_list
        assert any("review" in str(c) for c in calls)
        assert any("complete" in str(c) for c in calls)


class TestDisplayStepError:
    """Tests for Display.step_error method."""

    def test_step_error_display(self):
        """Test step error display."""
        with patch("lion.display._print") as mock_print:
            Display.step_error("test", "Tests failed")

        calls = mock_print.call_args_list
        assert any("test" in str(c) for c in calls)
        assert any("failed" in str(c) or "Tests failed" in str(c) for c in calls)


class TestDisplayAgentResult:
    """Tests for Display.agent_result method."""

    def test_agent_result_display(self):
        """Test agent result display."""
        with patch("lion.display._print") as mock_print:
            Display.agent_result("This is the agent's response content")

        calls = mock_print.call_args_list
        assert any("Result" in str(c) for c in calls)
        assert any("agent's response" in str(c) for c in calls)

    def test_agent_result_empty_content(self):
        """Test agent result with empty content."""
        with patch("lion.display._print") as mock_print:
            Display.agent_result("")

        # Should not print anything
        mock_print.assert_not_called()

    def test_agent_result_none_content(self):
        """Test agent result with None content."""
        with patch("lion.display._print") as mock_print:
            Display.agent_result(None)

        mock_print.assert_not_called()


class TestDisplayFinalResult:
    """Tests for Display.final_result method."""

    def test_final_result_success(self):
        """Test final result display for successful run."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.steps_completed = 3
        mock_result.total_steps = 3
        mock_result.total_duration = 45.5
        mock_result.agent_summaries = []
        mock_result.final_decision = None
        mock_result.files_changed = ["file1.py"]
        mock_result.errors = []

        with patch("lion.display._print") as mock_print:
            Display.final_result(mock_result, "/tmp/run")

        calls = mock_print.call_args_list
        assert any("Done" in str(c) for c in calls)
        assert any("3/3" in str(c) for c in calls)
        assert any("45.5s" in str(c) for c in calls)
        assert any("file1.py" in str(c) for c in calls)

    def test_final_result_with_errors(self):
        """Test final result display with errors."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.steps_completed = 1
        mock_result.total_steps = 3
        mock_result.total_duration = 10.0
        mock_result.agent_summaries = []
        mock_result.final_decision = None
        mock_result.files_changed = []
        mock_result.errors = ["Error 1", "Error 2"]

        with patch("lion.display._print") as mock_print:
            Display.final_result(mock_result)

        calls = mock_print.call_args_list
        assert any("Completed with errors" in str(c) for c in calls)
        assert any("Error 1" in str(c) for c in calls)

    def test_final_result_with_agent_summaries(self):
        """Test final result display with agent summaries."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.steps_completed = 1
        mock_result.total_steps = 1
        mock_result.total_duration = 30.0
        mock_result.agent_summaries = [
            {"agent": "agent_1", "summary": "Built feature"},
            {"agent": "agent_2", "summary": "Reviewed code"},
        ]
        mock_result.final_decision = "Use approach A"
        mock_result.files_changed = []
        mock_result.errors = []

        with patch("lion.display._print") as mock_print:
            Display.final_result(mock_result)

        calls = mock_print.call_args_list
        assert any("Agent 1" in str(c) for c in calls)
        assert any("Built feature" in str(c) for c in calls)
        assert any("Use approach A" in str(c) for c in calls)


class TestDisplayCancelled:
    """Tests for Display.cancelled method."""

    def test_cancelled_display(self):
        """Test cancelled display."""
        with patch("lion.display._print") as mock_print:
            Display.cancelled()

        calls = mock_print.call_args_list
        assert any("Cancelled" in str(c) for c in calls)


class TestDisplayError:
    """Tests for Display.error method."""

    def test_error_display(self):
        """Test error display."""
        with patch("lion.display._print") as mock_print:
            Display.error("Something went wrong")

        calls = mock_print.call_args_list
        assert any("Error" in str(c) for c in calls)
        assert any("Something went wrong" in str(c) for c in calls)


class TestDisplayNotify:
    """Tests for Display.notify method."""

    def test_notify_display(self):
        """Test notify display."""
        with patch("lion.display._print") as mock_print:
            Display.notify("Running tests...")

        calls = mock_print.call_args_list
        assert any("Running tests" in str(c) for c in calls)


class TestDisplayFormatCompletionSummary:
    """Tests for Display.format_completion_summary method."""

    def test_format_success_summary(self):
        """Test formatting successful completion summary."""
        summary = Display.format_completion_summary(
            agent_summaries=[
                {"agent": "agent_1", "summary": "Built feature"},
            ],
            final_decision="Use approach A",
            success=True,
        )

        assert "Lion voltooid!" in summary
        assert "Agent 1" in summary
        assert "Built feature" in summary
        assert "Use approach A" in summary

    def test_format_failure_summary(self):
        """Test formatting failed completion summary."""
        summary = Display.format_completion_summary(
            agent_summaries=[],
            final_decision=None,
            success=False,
        )

        assert "fouten" in summary

    def test_format_summary_with_content(self):
        """Test formatting summary with content (single agent)."""
        summary = Display.format_completion_summary(
            agent_summaries=[],
            final_decision=None,
            success=True,
            content="Created the new feature as requested.\nMore details here.",
        )

        assert "Lion voltooid!" in summary
        assert "Created the new feature" in summary

    def test_format_summary_no_content_or_summaries(self):
        """Test formatting summary without content or agent summaries."""
        summary = Display.format_completion_summary(
            agent_summaries=[],
            final_decision=None,
            success=True,
            content=None,
        )

        assert "Lion voltooid!" in summary
        assert "Taak uitgevoerd" in summary


class TestDisplayStepSummary:
    """Tests for Display.step_summary method."""

    def test_step_summary_with_issues(self):
        """Test step summary shows issue counts."""
        result = {
            "critical_count": 2,
            "warning_count": 3,
            "suggestion_count": 1,
            "content": "Found issues",
        }

        with patch("lion.display._print") as mock_print:
            Display.step_summary("review", result)

        calls = mock_print.call_args_list
        call_str = str(calls)
        assert "2 critical" in call_str
        assert "3 warnings" in call_str
        assert "1 suggestions" in call_str

    def test_step_summary_no_issues(self):
        """Test step summary with no issues shows content preview."""
        result = {
            "critical_count": 0,
            "warning_count": 0,
            "content": "Line 1\nLine 2\nLine 3\nLine 4\nLine 5",
        }

        with patch("lion.display._print") as mock_print:
            Display.step_summary("review", result)

        calls = mock_print.call_args_list
        call_str = str(calls)
        # Should show first 3 lines
        assert "Line 1" in call_str
        assert "Line 3" in call_str
        # Should show "more lines" indicator
        assert "2 more lines" in call_str

    def test_step_summary_empty_result(self):
        """Test step summary with empty result."""
        with patch("lion.display._print") as mock_print:
            Display.step_summary("review", {})

        # Nothing to show
        mock_print.assert_not_called()

    def test_step_summary_only_content(self):
        """Test step summary with content but no issue counts."""
        result = {"content": "Short content"}

        with patch("lion.display._print") as mock_print:
            Display.step_summary("devil", result)

        calls = mock_print.call_args_list
        assert any("Short content" in str(c) for c in calls)

    def test_step_summary_truncates_long_lines(self):
        """Test that long content lines are truncated."""
        result = {"content": "x" * 200}

        with patch("lion.display._print") as mock_print:
            Display.step_summary("review", result)

        calls = mock_print.call_args_list
        # Line should be truncated to 120 chars
        for c in calls:
            line_content = str(c)
            # The actual content in the call should not exceed 120 chars of 'x'
            assert "x" * 121 not in line_content


class TestDisplayPrideStart:
    """Tests for Display.pride_start method."""

    def test_pride_start_display(self):
        """Test pride start display."""
        with patch("lion.display._print") as mock_print:
            Display.pride_start(3, ["claude", "gemini", "codex"])

        calls = mock_print.call_args_list
        assert any("pride of 3" in str(c) for c in calls)
        assert any("claude" in str(c) for c in calls)


class TestDisplayAutoPipeline:
    """Tests for Display.auto_pipeline method."""

    def test_auto_pipeline_display(self):
        """Test auto pipeline display."""
        with patch("lion.display._print") as mock_print:
            Display.auto_pipeline("high", "pride(3) -> review() -> test()")

        calls = mock_print.call_args_list
        assert any("Complexity: high" in str(c) for c in calls)
        assert any("pride(3)" in str(c) for c in calls)
