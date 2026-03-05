"""Tests for lion.functions.fuse module."""

from unittest.mock import MagicMock, patch

from lion.functions import FUNCTIONS
from lion.functions.fuse import execute_fuse
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestFuseRegistry:
    def test_fuse_in_functions_registry(self):
        assert "fuse" in FUNCTIONS
        assert callable(FUNCTIONS["fuse"])


class TestExecuteFuse:
    def test_execute_fuse_success(self, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="fuse", args=[3], kwargs={})

        agent1 = MagicMock()
        agent1.name = "claude"
        agent2 = MagicMock()
        agent2.name = "gemini"

        proposals = [
            {
                "agent": "agent_1",
                "content": "APPROACH: Use service layer and clear boundaries",
                "model": "claude",
                "confidence": 0.8,
                "lens": None,
            },
            {
                "agent": "agent_2",
                "content": "APPROACH: Start with schema and API contracts",
                "model": "gemini",
                "confidence": 0.7,
                "lens": None,
            },
        ]

        with patch("lion.functions.fuse.Display"):
            with patch("lion.functions.fuse._resolve_agents", return_value=([agent1, agent2], [None, None])):
                with patch("lion.functions.fuse._get_shared_context", return_value=""):
                    with patch("lion.functions.fuse._parallel_propose", return_value=(proposals, [])):
                        with patch("lion.functions.fuse._parallel_react", return_value=[]):
                            with patch(
                                "lion.functions.fuse._converge",
                                return_value=(
                                    "DECISION: Use service-oriented modules\n\nTASKS:\n1. Build API",
                                    {"agent_1": {"confidence": 0.8, "label": "HIGH"}},
                                ),
                            ):
                                result = execute_fuse(
                                    prompt="Build auth system",
                                    previous={},
                                    step=step,
                                    memory=memory,
                                    config=sample_config,
                                    cwd=".",
                                )

        assert result["success"] is True
        assert "plan" in result
        assert "final_decision" in result
        assert result["final_decision"].startswith("Use service-oriented modules")
        assert len(result["agent_summaries"]) == 2
        assert result["fuse_rounds"] == 1

    def test_execute_fuse_skips_reaction_for_single_agent(self, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="fuse", args=[1], kwargs={})

        agent = MagicMock()
        agent.name = "claude"

        proposals = [
            {
                "agent": "agent_1",
                "content": "APPROACH: Keep architecture simple",
                "model": "claude",
                "confidence": 0.9,
                "lens": None,
            }
        ]

        with patch("lion.functions.fuse.Display"):
            with patch("lion.functions.fuse._resolve_agents", return_value=([agent], [None])):
                with patch("lion.functions.fuse._get_shared_context", return_value=""):
                    with patch("lion.functions.fuse._parallel_propose", return_value=(proposals, [])):
                        with patch("lion.functions.fuse._parallel_react") as mock_react:
                            with patch(
                                "lion.functions.fuse._converge",
                                return_value=("DECISION: Keep it simple\n\nTASKS:\n1. Build", {}),
                            ):
                                result = execute_fuse(
                                    prompt="Build small feature",
                                    previous={},
                                    step=step,
                                    memory=memory,
                                    config=sample_config,
                                    cwd=".",
                                )

        assert result["success"] is True
        mock_react.assert_not_called()

    def test_execute_fuse_returns_error_when_all_proposals_fail(self, temp_run_dir, sample_config):
        memory = SharedMemory(temp_run_dir)
        step = PipelineStep(function="fuse", args=[2], kwargs={})

        agent1 = MagicMock()
        agent1.name = "claude"
        agent2 = MagicMock()
        agent2.name = "gemini"

        with patch("lion.functions.fuse.Display"):
            with patch("lion.functions.fuse._resolve_agents", return_value=([agent1, agent2], [None, None])):
                with patch("lion.functions.fuse._get_shared_context", return_value=""):
                    with patch("lion.functions.fuse._parallel_propose", return_value=([], [])):
                        result = execute_fuse(
                            prompt="Build auth system",
                            previous={},
                            step=step,
                            memory=memory,
                            config=sample_config,
                            cwd=".",
                        )

        assert result["success"] is False
        assert "All agents failed to propose" in result["error"]
