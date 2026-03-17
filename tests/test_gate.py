"""Tests for lion.functions.gate module."""

import pytest
from unittest.mock import patch, MagicMock

from lion.functions import FUNCTIONS
from lion.functions.gate import (
    execute_gate,
    _show_previous,
    _revise_plan,
)
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestGateRegistry:
    def test_gate_in_functions_registry(self):
        assert "gate" in FUNCTIONS
        assert callable(FUNCTIONS["gate"])


class TestShowPrevious:
    @patch("lion.functions.gate._print_tty")
    def test_shows_plan(self, mock_print):
        _show_previous({"plan": "Step 1\nStep 2"})
        printed = "".join(call.args[0] for call in mock_print.call_args_list)
        assert "Step 1" in printed
        assert "Step 2" in printed

    @patch("lion.functions.gate._print_tty")
    def test_shows_final_decision(self, mock_print):
        _show_previous({"final_decision": "Use sessions"})
        printed = "".join(call.args[0] for call in mock_print.call_args_list)
        assert "Use sessions" in printed

    @patch("lion.functions.gate._print_tty")
    def test_shows_content_fallback(self, mock_print):
        _show_previous({"content": "Some output"})
        printed = "".join(call.args[0] for call in mock_print.call_args_list)
        assert "Some output" in printed

    @patch("lion.functions.gate._print_tty")
    def test_empty_previous(self, mock_print):
        _show_previous(None)
        mock_print.assert_called()

    @patch("lion.functions.gate._print_tty")
    def test_no_displayable_output(self, mock_print):
        _show_previous({"success": True, "tokens_used": 100})
        printed = "".join(call.args[0] for call in mock_print.call_args_list)
        assert "no displayable output" in printed


class TestExecuteGateApprove:
    @patch("lion.functions.gate._read_tty", return_value="")
    @patch("lion.functions.gate._print_tty")
    def test_enter_passes_through(self, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")
        previous = {"success": True, "plan": "Build auth with JWT"}

        result = execute_gate("Build auth", previous, step, memory, sample_config, "/tmp")

        assert result["success"] is True
        assert result["plan"] == "Build auth with JWT"

    @patch("lion.functions.gate._read_tty", return_value="")
    @patch("lion.functions.gate._print_tty")
    def test_approve_logs_to_memory(self, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")

        execute_gate("Build auth", {"plan": "x"}, step, memory, sample_config, "/tmp")

        entries = memory.read_all()
        assert any(e.type == "approve" for e in entries)


class TestExecuteGateAbort:
    @patch("lion.functions.gate._read_tty", return_value="q")
    @patch("lion.functions.gate._print_tty")
    def test_q_aborts(self, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")

        result = execute_gate("Build auth", {"plan": "x"}, step, memory, sample_config, "/tmp")

        assert result["success"] is False
        assert result["aborted"] is True

    @patch("lion.functions.gate._read_tty", return_value="quit")
    @patch("lion.functions.gate._print_tty")
    def test_quit_aborts(self, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")

        result = execute_gate("Build auth", {"plan": "x"}, step, memory, sample_config, "/tmp")

        assert result["success"] is False


class TestExecuteGateRevise:
    @patch("lion.functions.gate._read_tty", return_value="use sessions instead of JWT")
    @patch("lion.functions.gate._print_tty")
    @patch("lion.functions.gate._revise_plan", return_value="Revised: use sessions")
    def test_feedback_revises_plan(self, mock_revise, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")
        previous = {"success": True, "plan": "Build auth with JWT"}

        result = execute_gate("Build auth", previous, step, memory, sample_config, "/tmp")

        assert result["success"] is True
        assert result["plan"] == "Revised: use sessions"
        assert result["gate_feedback"] == "use sessions instead of JWT"
        mock_revise.assert_called_once()

    @patch("lion.functions.gate._read_tty", return_value="change approach")
    @patch("lion.functions.gate._print_tty")
    @patch("lion.functions.gate._revise_plan", return_value=None)
    def test_failed_revision_passes_through(self, mock_revise, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")
        previous = {"success": True, "plan": "Original plan"}

        result = execute_gate("Build auth", previous, step, memory, sample_config, "/tmp")

        assert result["success"] is True
        assert result["gate_feedback"] == "change approach"

    @patch("lion.functions.gate._read_tty", return_value="add rate limiting")
    @patch("lion.functions.gate._print_tty")
    @patch("lion.functions.gate._revise_plan", return_value="Plan with rate limiting")
    def test_revision_logs_to_memory(self, mock_revise, mock_print, mock_read, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="gate")

        execute_gate("Build auth", {"plan": "x"}, step, memory, sample_config, "/tmp")

        entries = memory.read_all()
        assert any(e.type == "feedback" for e in entries)
        assert any(e.type == "revised_plan" for e in entries)


class TestRevisePlan:
    def test_revise_calls_provider(self):
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "Revised plan"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.gate.get_provider", return_value=mock_provider):
            result = _revise_plan(
                {"plan": "Original"},
                "change X to Y",
                {"providers": {"default": "claude"}},
                "/tmp",
            )

        assert result == "Revised plan"
        mock_provider.ask.assert_called_once()
        call_args = mock_provider.ask.call_args[0][0]
        assert "Original" in call_args
        assert "change X to Y" in call_args

    def test_revise_returns_none_on_failure(self):
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.gate.get_provider", return_value=mock_provider):
            result = _revise_plan({"plan": "x"}, "feedback", {}, "/tmp")

        assert result is None
