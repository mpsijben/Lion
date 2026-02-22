"""Tests for lion.escalation module."""

import pytest
from unittest.mock import patch, MagicMock, call

from lion.escalation import Escalation, _read_tty, _print_tty


class TestPrintTty:
    """Tests for _print_tty helper function."""

    def test_print_to_tty(self):
        """Test printing to /dev/tty."""
        mock_tty = MagicMock()
        mock_open = MagicMock(return_value=mock_tty)
        mock_tty.__enter__ = MagicMock(return_value=mock_tty)
        mock_tty.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", mock_open):
            _print_tty("Test message")

        mock_open.assert_called_with("/dev/tty", "w")
        mock_tty.write.assert_called_with("Test message\n")

    def test_print_fallback_to_stderr(self, capsys):
        """Test fallback to stderr when /dev/tty unavailable."""
        with patch("builtins.open", side_effect=OSError("No tty")):
            _print_tty("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.err


class TestReadTty:
    """Tests for _read_tty helper function."""

    def test_read_from_tty(self):
        """Test reading from /dev/tty."""
        mock_tty = MagicMock()
        mock_tty.readline.return_value = "user input\n"

        def mock_open_fn(path, mode="r"):
            assert mode == "r+"
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock_tty)
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        with patch("builtins.open", mock_open_fn):
            result = _read_tty("Prompt: ")

        assert result == "user input"
        mock_tty.write.assert_called_with("Prompt: ")

    def test_read_tty_raises_on_no_tty(self):
        """Test that RuntimeError is raised when no tty available."""
        with patch("builtins.open", side_effect=OSError("No tty")):
            with pytest.raises(RuntimeError) as excinfo:
                _read_tty("Prompt: ")

        assert "Cannot read from /dev/tty" in str(excinfo.value)

    def test_read_tty_raises_on_eof(self):
        """Test that RuntimeError is raised when tty input is unavailable."""
        mock_tty = MagicMock()
        mock_tty.readline.return_value = ""

        def mock_open_fn(path, mode="r"):
            assert mode == "r+"
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock_tty)
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        with patch("builtins.open", mock_open_fn):
            with pytest.raises(RuntimeError) as excinfo:
                _read_tty("Prompt: ")

        assert "No interactive input available" in str(excinfo.value)


class TestEscalationAskChoice:
    """Tests for Escalation.ask_choice method."""

    def test_ask_choice_valid_selection(self):
        """Test valid choice selection."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):
                result = Escalation.ask_choice(
                    "Which option?",
                    ["Option A", "Option B", "Option C"]
                )

        assert result == 0  # First option (0-indexed)

    def test_ask_choice_second_option(self):
        """Test selecting second option."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="2"):
                result = Escalation.ask_choice(
                    "Which option?",
                    ["Option A", "Option B"]
                )

        assert result == 1

    def test_ask_choice_invalid_then_valid(self):
        """Test invalid input followed by valid input."""
        responses = iter(["invalid", "5", "2"])

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", side_effect=lambda _: next(responses)):
                result = Escalation.ask_choice(
                    "Which option?",
                    ["A", "B", "C"]
                )

        assert result == 1

    def test_ask_choice_displays_options(self):
        """Test that options are displayed."""
        with patch("lion.escalation._print_tty") as mock_print:
            with patch("lion.escalation._read_tty", return_value="1"):
                Escalation.ask_choice(
                    "Pick one",
                    ["First", "Second"]
                )

        calls = mock_print.call_args_list
        call_strs = [str(c) for c in calls]
        assert any("[1]" in s and "First" in s for s in call_strs)
        assert any("[2]" in s and "Second" in s for s in call_strs)


class TestEscalationAskText:
    """Tests for Escalation.ask_text method."""

    def test_ask_text_returns_input(self):
        """Test that ask_text returns user input."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="User's answer"):
                result = Escalation.ask_text("What is your name?")

        assert result == "User's answer"

    def test_ask_text_displays_question(self):
        """Test that question is displayed."""
        with patch("lion.escalation._print_tty") as mock_print:
            with patch("lion.escalation._read_tty", return_value="answer"):
                Escalation.ask_text("Enter your name:")

        calls = mock_print.call_args_list
        assert any("Enter your name:" in str(c) for c in calls)


class TestEscalationNotify:
    """Tests for Escalation.notify method."""

    def test_notify_displays_message(self):
        """Test that notify displays message."""
        with patch("lion.escalation._print_tty") as mock_print:
            Escalation.notify("Processing...")

        mock_print.assert_called()
        call_str = str(mock_print.call_args)
        assert "Processing" in call_str


class TestEscalationAgentStuck:
    """Tests for Escalation.agent_stuck method."""

    def test_agent_stuck_hint_option(self):
        """Test selecting hint option."""
        # Select "Give a hint" (option 1), then provide hint
        responses = iter(["1", "Use a different approach"])

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", side_effect=lambda _: next(responses)):
                result = Escalation.agent_stuck("test_agent", "Error message", retries_left=2)

        assert result.startswith("hint:")
        assert "Use a different approach" in result

    def test_agent_stuck_retry_option(self):
        """Test selecting retry option."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="2"):  # Retry with retries_left
                result = Escalation.agent_stuck("test_agent", "Error", retries_left=2)

        assert result == "retry"

    def test_agent_stuck_skip_option(self):
        """Test selecting skip option."""
        with patch("lion.escalation._print_tty"):
            # With retries_left=0, skip is option 2
            with patch("lion.escalation._read_tty", return_value="2"):
                result = Escalation.agent_stuck("test_agent", "Error", retries_left=0)

        assert result == "skip"

    def test_agent_stuck_takeover_option(self):
        """Test selecting takeover option."""
        with patch("lion.escalation._print_tty"):
            # With retries_left=0, takeover is option 3
            with patch("lion.escalation._read_tty", return_value="3"):
                result = Escalation.agent_stuck("test_agent", "Error", retries_left=0)

        assert result == "takeover"

    def test_agent_stuck_defaults_to_takeover_on_no_input(self):
        """Test fallback behavior when interactive input is unavailable."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", side_effect=RuntimeError("No tty input")):
                result = Escalation.agent_stuck("test_agent", "Error", retries_left=2)

        assert result == "takeover"


class TestEscalationNoConsensus:
    """Tests for Escalation.no_consensus method."""

    def test_no_consensus_use_proposal(self):
        """Test selecting a specific proposal."""
        proposals = [
            {"agent": "agent_1", "content": "Proposal 1", "model": "claude"},
            {"agent": "agent_2", "content": "Proposal 2", "model": "gemini"},
        ]

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):
                result = Escalation.no_consensus(proposals)

        assert result == "use_proposal:0"

    def test_no_consensus_retry(self):
        """Test selecting retry option."""
        proposals = [{"agent": "agent_1", "content": "Proposal", "model": "claude"}]

        with patch("lion.escalation._print_tty"):
            # Retry is option 2 (after 1 proposal)
            with patch("lion.escalation._read_tty", return_value="2"):
                result = Escalation.no_consensus(proposals)

        assert result == "retry"

    def test_no_consensus_takeover(self):
        """Test selecting takeover option."""
        proposals = [{"agent": "agent_1", "content": "Proposal", "model": "claude"}]

        with patch("lion.escalation._print_tty"):
            # Takeover is option 3 (after 1 proposal + retry)
            with patch("lion.escalation._read_tty", return_value="3"):
                result = Escalation.no_consensus(proposals)

        assert result == "takeover"

    def test_no_consensus_max_rounds_message(self):
        """Test that max rounds message is shown."""
        proposals = [{"agent": "agent_1", "content": "Proposal", "model": "claude"}]

        with patch("lion.escalation._print_tty") as mock_print:
            with patch("lion.escalation._read_tty", return_value="1"):
                Escalation.no_consensus(proposals, max_rounds_reached=True)

        calls = mock_print.call_args_list
        assert any("Maximum deliberation rounds" in str(c) for c in calls)


class TestEscalationConfirmAction:
    """Tests for Escalation.confirm_action method."""

    def test_confirm_action_yes(self):
        """Test confirming action."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):  # Yes
                result = Escalation.confirm_action("Delete file", "file.txt")

        assert result is True

    def test_confirm_action_no(self):
        """Test declining action."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="2"):  # No
                result = Escalation.confirm_action("Delete file")

        assert result is False

    def test_confirm_action_displays_details(self):
        """Test that action details are displayed."""
        with patch("lion.escalation._print_tty") as mock_print:
            with patch("lion.escalation._read_tty", return_value="1"):
                Escalation.confirm_action("Delete file", "This will remove data permanently")

        calls = mock_print.call_args_list
        assert any("Delete file" in str(c) for c in calls)
        assert any("permanently" in str(c) for c in calls)


class TestEscalationLowConfidence:
    """Tests for Escalation.low_confidence method."""

    def test_low_confidence_proceed(self):
        """Test selecting proceed anyway."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):
                result = Escalation.low_confidence(
                    "Complex refactoring",
                    "Many edge cases"
                )

        assert result == "proceed"

    def test_low_confidence_hint(self):
        """Test providing guidance."""
        responses = iter(["2", "Focus on the core logic first"])

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", side_effect=lambda _: next(responses)):
                result = Escalation.low_confidence(
                    "Complex task",
                    "Uncertain about approach"
                )

        assert result.startswith("hint:")
        assert "Focus on the core logic" in result

    def test_low_confidence_takeover(self):
        """Test selecting takeover."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="3"):
                result = Escalation.low_confidence(
                    "Complex task",
                    "Too uncertain"
                )

        assert result == "takeover"

    def test_low_confidence_displays_context(self):
        """Test that context and reason are displayed."""
        with patch("lion.escalation._print_tty") as mock_print:
            with patch("lion.escalation._read_tty", return_value="1"):
                Escalation.low_confidence(
                    "Refactoring authentication",
                    "Many different auth methods in use"
                )

        calls = mock_print.call_args_list
        assert any("authentication" in str(c) for c in calls)
        assert any("auth methods" in str(c) for c in calls)


class TestEscalationEdgeCases:
    """Edge case tests for Escalation module."""

    def test_ask_choice_with_long_options(self):
        """Test ask_choice with very long option text."""
        long_option = "This is a very long option that might need truncation " * 3

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):
                result = Escalation.ask_choice("Choose:", [long_option, "Short"])

        assert result == 0

    def test_agent_stuck_with_long_error(self):
        """Test agent_stuck with long error message."""
        long_error = "Error: " + "x" * 500

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="2"):  # Skip
                result = Escalation.agent_stuck("agent", long_error, retries_left=0)

        assert result == "skip"

    def test_no_consensus_with_many_proposals(self):
        """Test no_consensus with many proposals."""
        proposals = [
            {"agent": f"agent_{i}", "content": f"Proposal {i}", "model": "claude"}
            for i in range(5)
        ]

        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="3"):  # Third proposal
                result = Escalation.no_consensus(proposals)

        assert result == "use_proposal:2"

    def test_ask_choice_unicode_options(self):
        """Test ask_choice with unicode options."""
        with patch("lion.escalation._print_tty"):
            with patch("lion.escalation._read_tty", return_value="1"):
                result = Escalation.ask_choice(
                    "Choose emoji:",
                    ["🦁 Lion", "🐍 Snake", "🦀 Crab"]
                )

        assert result == 0
