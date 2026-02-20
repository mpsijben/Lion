"""Tests for lion.pipeline module."""

import os
import time
import pytest
from unittest.mock import patch, MagicMock

from lion.pipeline import PipelineExecutor, PipelineResult
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_create_basic_result(self):
        """Test creating a basic pipeline result."""
        result = PipelineResult(
            success=True,
            prompt="Test prompt",
            steps_completed=2,
            total_steps=2,
            outputs=[{"step": 1}, {"step": 2}],
            total_duration=5.0,
            total_tokens=1000,
            files_changed=["file1.py"],
            errors=[],
        )

        assert result.success is True
        assert result.prompt == "Test prompt"
        assert result.steps_completed == 2
        assert result.total_steps == 2
        assert len(result.outputs) == 2
        assert result.total_duration == 5.0
        assert result.total_tokens == 1000
        assert result.files_changed == ["file1.py"]
        assert result.errors == []
        assert result.agent_summaries == []
        assert result.final_decision is None
        assert result.content is None

    def test_result_with_agent_summaries(self):
        """Test result with agent summaries."""
        result = PipelineResult(
            success=True,
            prompt="Test",
            steps_completed=1,
            total_steps=1,
            outputs=[],
            total_duration=1.0,
            total_tokens=100,
            files_changed=[],
            errors=[],
            agent_summaries=[{"agent": "agent_1", "summary": "Done"}],
            final_decision="Use approach A",
        )

        assert len(result.agent_summaries) == 1
        assert result.final_decision == "Use approach A"

    def test_result_with_content(self):
        """Test result with content."""
        result = PipelineResult(
            success=True,
            prompt="Test",
            steps_completed=1,
            total_steps=1,
            outputs=[],
            total_duration=1.0,
            total_tokens=100,
            files_changed=[],
            errors=[],
            content="Agent output content",
        )

        assert result.content == "Agent output content"


class TestPipelineExecutor:
    """Tests for PipelineExecutor class."""

    def test_init(self, temp_run_dir, sample_config):
        """Test executor initialization."""
        executor = PipelineExecutor(
            prompt="Test prompt",
            steps=[],
            config=sample_config,
            run_dir=temp_run_dir,
            cwd="/tmp",
        )

        assert executor.prompt == "Test prompt"
        assert executor.steps == []
        assert executor.config == sample_config
        assert executor.run_dir == temp_run_dir
        assert executor.cwd == "/tmp"
        assert isinstance(executor.memory, SharedMemory)

    def test_expand_patterns(self, temp_run_dir, sample_config):
        """Test pattern expansion."""
        # Create a pattern step
        pattern_step = PipelineStep(
            function="__pattern__",
            args=[
                PipelineStep(function="review"),
                PipelineStep(function="test"),
            ],
            kwargs={"name": "quick"},
        )

        executor = PipelineExecutor(
            prompt="Test",
            steps=[pattern_step],
            config=sample_config,
            run_dir=temp_run_dir,
            cwd="/tmp",
        )

        # Pattern should be expanded
        assert len(executor.steps) == 2
        assert executor.steps[0].function == "review"
        assert executor.steps[1].function == "test"

    def test_run_no_steps_single_agent(self, temp_run_dir, sample_config):
        """Test running with no pipeline steps (single agent mode)."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "Agent response"
        mock_result.tokens_used = 500
        mock_provider.implement.return_value = mock_result

        with patch("lion.pipeline.get_provider", return_value=mock_provider):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Simple task",
                    steps=[],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is True
        assert result.content == "Agent response"
        assert result.steps_completed == 1
        assert result.total_steps == 1

    def test_run_with_single_step(self, temp_run_dir, sample_config):
        """Test running with a single pipeline step."""
        mock_func = MagicMock(return_value={
            "success": True,
            "content": "Review complete",
            "tokens_used": 200,
            "files_changed": [],
        })

        with patch("lion.pipeline.FUNCTIONS", {"review": mock_func}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Review code",
                    steps=[PipelineStep(function="review")],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is True
        assert result.steps_completed == 1
        mock_func.assert_called_once()

    def test_run_with_multiple_steps(self, temp_run_dir, sample_config):
        """Test running with multiple pipeline steps."""
        call_order = []

        def mock_review(*args, **kwargs):
            call_order.append("review")
            return {"success": True, "tokens_used": 100, "files_changed": []}

        def mock_test(*args, **kwargs):
            call_order.append("test")
            return {"success": True, "tokens_used": 150, "files_changed": []}

        with patch("lion.pipeline.FUNCTIONS", {"review": mock_review, "test": mock_test}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Build feature",
                    steps=[
                        PipelineStep(function="review"),
                        PipelineStep(function="test"),
                    ],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is True
        assert result.steps_completed == 2
        assert call_order == ["review", "test"]
        assert result.total_tokens == 250

    def test_run_unknown_function(self, temp_run_dir, sample_config):
        """Test running with unknown function."""
        with patch("lion.pipeline.FUNCTIONS", {}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[PipelineStep(function="unknown_func")],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is False
        assert "Unknown function: unknown_func" in result.errors

    def test_run_step_raises_exception(self, temp_run_dir, sample_config):
        """Test handling of step that raises exception."""
        def mock_failing_func(*args, **kwargs):
            raise ValueError("Step failed")

        with patch("lion.pipeline.FUNCTIONS", {"failing": mock_failing_func}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[PipelineStep(function="failing")],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is False
        assert any("Step failed" in e for e in result.errors)

    def test_run_collects_files_changed(self, temp_run_dir, sample_config):
        """Test that files_changed are collected from all steps."""
        def mock_step1(*args, **kwargs):
            return {"success": True, "tokens_used": 0, "files_changed": ["file1.py"]}

        def mock_step2(*args, **kwargs):
            return {"success": True, "tokens_used": 0, "files_changed": ["file2.py", "file1.py"]}

        with patch("lion.pipeline.FUNCTIONS", {"step1": mock_step1, "step2": mock_step2}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[
                        PipelineStep(function="step1"),
                        PipelineStep(function="step2"),
                    ],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        # Duplicates should be removed
        assert set(result.files_changed) == {"file1.py", "file2.py"}

    def test_run_collects_agent_summaries(self, temp_run_dir, sample_config):
        """Test that agent summaries are collected."""
        def mock_pride(*args, **kwargs):
            return {
                "success": True,
                "tokens_used": 500,
                "files_changed": [],
                "agent_summaries": [
                    {"agent": "agent_1", "summary": "Built feature"},
                    {"agent": "agent_2", "summary": "Reviewed code"},
                ],
                "final_decision": "Use approach A",
            }

        with patch("lion.pipeline.FUNCTIONS", {"pride": mock_pride}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[PipelineStep(function="pride", args=[3])],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert len(result.agent_summaries) == 2
        assert result.final_decision == "Use approach A"

    def test_run_passes_previous_output(self, temp_run_dir, sample_config):
        """Test that previous step output is passed to next step."""
        received_previous = []

        def mock_step1(*args, **kwargs):
            received_previous.append(kwargs.get("previous", {}).copy())
            return {"success": True, "tokens_used": 0, "files_changed": [], "data": "step1_output"}

        def mock_step2(*args, **kwargs):
            received_previous.append(kwargs.get("previous", {}).copy())
            return {"success": True, "tokens_used": 0, "files_changed": []}

        with patch("lion.pipeline.FUNCTIONS", {"step1": mock_step1, "step2": mock_step2}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test prompt",
                    steps=[
                        PipelineStep(function="step1"),
                        PipelineStep(function="step2"),
                    ],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                executor.run()

        # First step should receive initial previous with prompt
        assert "prompt" in received_previous[0]
        assert received_previous[0]["prompt"] == "Test prompt"

        # Second step should receive output from first step
        assert "data" in received_previous[1]
        assert received_previous[1]["data"] == "step1_output"

    def test_run_stops_on_error(self, temp_run_dir, sample_config):
        """Test that pipeline stops after error."""
        call_count = [0]

        def mock_step1(*args, **kwargs):
            call_count[0] += 1
            raise ValueError("Error in step 1")

        def mock_step2(*args, **kwargs):
            call_count[0] += 1
            return {"success": True, "tokens_used": 0, "files_changed": []}

        with patch("lion.pipeline.FUNCTIONS", {"step1": mock_step1, "step2": mock_step2}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[
                        PipelineStep(function="step1"),
                        PipelineStep(function="step2"),
                    ],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is False
        assert call_count[0] == 1  # Only first step was called
        assert result.steps_completed == 0

    def test_run_calculates_duration(self, temp_run_dir, sample_config):
        """Test that total duration is calculated."""
        def mock_slow_step(*args, **kwargs):
            time.sleep(0.1)
            return {"success": True, "tokens_used": 0, "files_changed": []}

        with patch("lion.pipeline.FUNCTIONS", {"slow": mock_slow_step}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[PipelineStep(function="slow")],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.total_duration >= 0.1


class TestPipelineExecutorSingleAgent:
    """Tests for single agent execution mode."""

    def test_single_agent_uses_default_provider(self, temp_run_dir, sample_config):
        """Test that single agent mode uses default provider from config."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "Response"
        mock_result.tokens_used = 100
        mock_provider.implement.return_value = mock_result

        with patch("lion.pipeline.get_provider", return_value=mock_provider) as mock_get:
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Simple task",
                    steps=[],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp/project",
                )

                executor.run()

        mock_get.assert_called_with("claude", sample_config)
        mock_provider.implement.assert_called_once()

    def test_single_agent_passes_cwd(self, temp_run_dir, sample_config):
        """Test that single agent mode passes working directory."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = ""
        mock_result.tokens_used = 0
        mock_provider.implement.return_value = mock_result

        with patch("lion.pipeline.get_provider", return_value=mock_provider):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Task",
                    steps=[],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/my/project",
                )

                executor.run()

        call_kwargs = mock_provider.implement.call_args[1]
        assert call_kwargs["cwd"] == "/my/project"


class TestPipelineExecutorEdgeCases:
    """Edge case tests for PipelineExecutor."""

    def test_empty_prompt(self, temp_run_dir, sample_config):
        """Test running with empty prompt."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = ""
        mock_result.tokens_used = 0
        mock_provider.implement.return_value = mock_result

        with patch("lion.pipeline.get_provider", return_value=mock_provider):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="",
                    steps=[],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is True
        assert result.prompt == ""

    def test_many_steps(self, temp_run_dir, sample_config):
        """Test running with many pipeline steps."""
        def mock_step(*args, **kwargs):
            return {"success": True, "tokens_used": 10, "files_changed": []}

        functions = {f"step{i}": mock_step for i in range(20)}

        with patch("lion.pipeline.FUNCTIONS", functions):
            with patch("lion.pipeline.Display"):
                steps = [PipelineStep(function=f"step{i}") for i in range(20)]
                executor = PipelineExecutor(
                    prompt="Many steps",
                    steps=steps,
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                )

                result = executor.run()

        assert result.success is True
        assert result.steps_completed == 20
        assert result.total_tokens == 200

    def test_cost_manager_integration(self, temp_run_dir, sample_config):
        """Test that cost manager is passed to steps."""
        mock_cost_manager = MagicMock()
        received_cost_manager = []

        def mock_step(*args, **kwargs):
            received_cost_manager.append(kwargs.get("cost_manager"))
            return {"success": True, "tokens_used": 0, "files_changed": []}

        with patch("lion.pipeline.FUNCTIONS", {"step": mock_step}):
            with patch("lion.pipeline.Display"):
                executor = PipelineExecutor(
                    prompt="Test",
                    steps=[PipelineStep(function="step")],
                    config=sample_config,
                    run_dir=temp_run_dir,
                    cwd="/tmp",
                    cost_manager=mock_cost_manager,
                )

                executor.run()

        assert received_cost_manager[0] is mock_cost_manager
