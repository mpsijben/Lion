"""Tests for self-healing behavior in validation functions.

Tests the shared self_heal_loop utility and the ^ operator functionality
across review, devil, future, lint, and typecheck functions.
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from lion.functions.self_heal import (
    self_heal_loop,
    extract_critical_issues,
    extract_warning_issues,
    extract_suggestion_issues,
    SelfHealResult,
)
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestSelfHealLoop:
    """Tests for the shared self_heal_loop function."""

    def test_passes_on_first_check(self):
        """Test that loop exits immediately if first check passes."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            return True, [], "All good", 100

        mock_provider = MagicMock()

        result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=lambda c: f"Fix: {c}",
            provider=mock_provider,
            cwd="/tmp",
            max_rounds=2,
        )

        assert result.passed is True
        assert result.issues == []
        assert check_count[0] == 1
        mock_provider.implement.assert_not_called()

    def test_attempts_fix_on_failure(self):
        """Test that loop attempts to fix issues when check fails."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            if check_count[0] == 1:
                return False, [{"severity": "critical", "title": "Bug"}], "Bug found", 100
            return True, [], "Fixed", 50

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.tokens_used = 200
        mock_provider.implement.return_value = mock_result

        result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=lambda c: f"Fix: {c}",
            provider=mock_provider,
            cwd="/tmp",
            max_rounds=2,
        )

        assert result.passed is True
        assert check_count[0] == 2
        mock_provider.implement.assert_called_once()

    def test_respects_max_rounds(self):
        """Test that loop stops after max_rounds."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            return False, [{"severity": "critical", "title": "Bug"}], "Still broken", 100

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.tokens_used = 200
        mock_provider.implement.return_value = mock_result

        with patch("lion.functions.self_heal.Display"):
            result = self_heal_loop(
                check_fn=check_fn,
                fix_prompt_builder=lambda c: f"Fix: {c}",
                provider=mock_provider,
                cwd="/tmp",
                max_rounds=2,
            )

        assert result.passed is False
        # Initial check + 2 rounds of fix + re-check
        assert check_count[0] == 3  # initial + 2 re-checks after fixes
        assert mock_provider.implement.call_count == 2

    def test_stops_on_cost_limit(self):
        """Test that loop stops when cost limit is reached."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            # Return 10M tokens to quickly exceed cost limit
            return False, [{"severity": "critical", "title": "Bug"}], "Broken", 10000000

        mock_provider = MagicMock()

        with patch("lion.functions.self_heal.Display"):
            result = self_heal_loop(
                check_fn=check_fn,
                fix_prompt_builder=lambda c: f"Fix: {c}",
                provider=mock_provider,
                cwd="/tmp",
                max_rounds=5,
                max_cost=0.001,  # Very low cost limit
            )

        assert result.cost_limit_reached is True
        mock_provider.implement.assert_not_called()

    def test_stops_on_fix_failure(self):
        """Test that loop stops when fix fails."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            return False, [{"severity": "critical", "title": "Bug"}], "Broken", 100

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Fix failed"
        mock_result.tokens_used = 100
        mock_provider.implement.return_value = mock_result

        with patch("lion.functions.self_heal.Display"):
            result = self_heal_loop(
                check_fn=check_fn,
                fix_prompt_builder=lambda c: f"Fix: {c}",
                provider=mock_provider,
                cwd="/tmp",
                max_rounds=2,
            )

        assert result.passed is False
        assert mock_provider.implement.call_count == 1

    def test_tracks_tokens(self):
        """Test that loop correctly tracks total tokens."""
        def check_fn():
            return True, [], "Good", 150

        mock_provider = MagicMock()

        result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=lambda c: f"Fix: {c}",
            provider=mock_provider,
            cwd="/tmp",
        )

        assert result.total_tokens == 150

    def test_extends_files_changed(self):
        """Test that files changed are properly tracked."""
        check_count = [0]

        def check_fn():
            check_count[0] += 1
            if check_count[0] == 1:
                return False, [{"severity": "critical"}], "Broken", 100
            return True, [], "Fixed", 50

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.tokens_used = 100
        mock_result.files_changed = ["fixed.py"]
        mock_provider.implement.return_value = mock_result

        result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=lambda c: f"Fix: {c}",
            provider=mock_provider,
            cwd="/tmp",
            initial_files_changed=["original.py"],
        )

        assert "original.py" in result.files_changed
        assert "fixed.py" in result.files_changed


class TestExtractIssues:
    """Tests for issue extraction helper functions."""

    def test_extract_critical_issues(self):
        """Test extracting critical issues."""
        issues = [
            {"severity": "critical", "title": "Bug 1"},
            {"severity": "warning", "title": "Issue 2"},
            {"severity": "critical", "title": "Bug 3"},
            {"severity": "suggestion", "title": "Idea 4"},
        ]
        critical = extract_critical_issues(issues)
        assert len(critical) == 2
        assert all(i["severity"] == "critical" for i in critical)

    def test_extract_warning_issues(self):
        """Test extracting warning issues."""
        issues = [
            {"severity": "critical", "title": "Bug 1"},
            {"severity": "warning", "title": "Issue 2"},
            {"severity": "warning", "title": "Issue 3"},
        ]
        warnings = extract_warning_issues(issues)
        assert len(warnings) == 2
        assert all(i["severity"] == "warning" for i in warnings)

    def test_extract_suggestion_issues(self):
        """Test extracting suggestion issues."""
        issues = [
            {"severity": "suggestion", "title": "Idea 1"},
            {"severity": "warning", "title": "Issue 2"},
        ]
        suggestions = extract_suggestion_issues(issues)
        assert len(suggestions) == 1
        assert suggestions[0]["title"] == "Idea 1"

    def test_extract_from_empty_list(self):
        """Test extracting from empty list."""
        assert extract_critical_issues([]) == []
        assert extract_warning_issues([]) == []
        assert extract_suggestion_issues([]) == []


class TestCaretOperatorParsing:
    """Tests for ^ operator parsing across all self-healing functions."""

    def test_review_parses_caret(self, temp_run_dir, sample_config):
        """Test that review parses ^ operator."""
        from lion.functions.review import execute_review

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Summary\nNo issues found"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.review.get_provider", return_value=mock_provider):
            with patch("lion.functions.review.Display"):
                memory = SharedMemory(temp_run_dir)
                step = PipelineStep(function="review", args=["^"])
                result = execute_review(
                    prompt="Test",
                    previous={},
                    step=step,
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        assert result["success"] is True

    def test_devil_parses_caret(self, temp_run_dir, sample_config):
        """Test that devil parses ^ operator."""
        from lion.functions.devil import execute_devil

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Summary\nNo critical challenges"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.devil.get_provider", return_value=mock_provider):
            with patch("lion.functions.devil.Display"):
                memory = SharedMemory(temp_run_dir)
                step = PipelineStep(function="devil", args=["^"])
                result = execute_devil(
                    prompt="Test",
                    previous={},
                    step=step,
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        assert result["success"] is True

    def test_future_parses_caret(self, temp_run_dir, sample_config):
        """Test that future parses ^ operator."""
        from lion.functions.future import execute_future

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Summary\nCode looks good from future perspective"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.future.get_provider", return_value=mock_provider):
            with patch("lion.functions.future.Display"):
                memory = SharedMemory(temp_run_dir)
                step = PipelineStep(function="future", args=["6m", "^"])
                result = execute_future(
                    prompt="Test",
                    previous={},
                    step=step,
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        assert result["success"] is True

    def test_lint_parses_caret(self, temp_run_dir, sample_config):
        """Test that lint parses ^ operator."""
        import os
        from lion.functions.lint import execute_lint

        # Use the parent of temp_run_dir as cwd (temp_run_dir is .lion/runs/test_run)
        cwd = os.path.dirname(os.path.dirname(os.path.dirname(temp_run_dir)))

        with patch("lion.functions.lint.detect_project_language", return_value="python"):
            with patch("lion.functions.lint.detect_linter", return_value=(None, None)):
                with patch("lion.functions.lint.Display"):
                    memory = SharedMemory(temp_run_dir)
                    step = PipelineStep(function="lint", args=["^"])
                    result = execute_lint(
                        prompt="Test",
                        previous={},
                        step=step,
                        memory=memory,
                        config=sample_config,
                        cwd=cwd,
                    )

        # Should skip because no linter found, but not crash
        assert result["skipped"] is True

    def test_typecheck_parses_caret(self, temp_run_dir, sample_config):
        """Test that typecheck parses ^ operator."""
        import os
        from lion.functions.typecheck import execute_typecheck

        # Use the parent of temp_run_dir as cwd (temp_run_dir is .lion/runs/test_run)
        cwd = os.path.dirname(os.path.dirname(os.path.dirname(temp_run_dir)))

        with patch("lion.functions.typecheck.detect_project_language", return_value="python"):
            with patch("lion.functions.typecheck.detect_type_checker", return_value=(None, None)):
                with patch("lion.functions.typecheck.Display"):
                    memory = SharedMemory(temp_run_dir)
                    step = PipelineStep(function="typecheck", args=["^"])
                    result = execute_typecheck(
                        prompt="Test",
                        previous={},
                        step=step,
                        memory=memory,
                        config=sample_config,
                        cwd=cwd,
                    )

        # Should skip because no type checker found, but not crash
        assert result["skipped"] is True


class TestCostBudgetCheck:
    """Tests for cost budget check in self-healing."""

    def test_review_respects_cost_limit(self, temp_run_dir):
        """Test that review stops when cost limit is reached."""
        from lion.functions.review import execute_review

        check_count = [0]

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = """## Summary
Bug found

## Issues Found
### [CRITICAL] Security issue
- **Problem**: SQL injection
"""
        mock_result.tokens_used = 10000000  # High token count to trigger cost limit
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        config = {
            "providers": {"default": "claude"},
            "self_healing": {"max_heal_cost": 0.001},  # Very low limit
        }

        with patch("lion.functions.review.get_provider", return_value=mock_provider):
            with patch("lion.functions.review.Display"):
                memory = SharedMemory(temp_run_dir)
                step = PipelineStep(function="review", args=["^"])
                result = execute_review(
                    prompt="Test",
                    previous={},
                    step=step,
                    memory=memory,
                    config=config,
                    cwd="/tmp",
                )

        # Should have stopped due to cost limit - implement should not be called
        mock_provider.implement.assert_not_called()


class TestSelfHealResult:
    """Tests for SelfHealResult dataclass."""

    def test_default_values(self):
        """Test default values in SelfHealResult."""
        result = SelfHealResult(
            passed=True,
            issues=[],
            content="Good",
            rounds_used=1,
            total_tokens=100,
            files_changed=[],
        )
        assert result.cost_limit_reached is False

    def test_all_fields(self):
        """Test all fields in SelfHealResult."""
        result = SelfHealResult(
            passed=False,
            issues=[{"severity": "critical"}],
            content="Bad",
            rounds_used=2,
            total_tokens=500,
            files_changed=["file.py"],
            cost_limit_reached=True,
        )
        assert result.passed is False
        assert len(result.issues) == 1
        assert result.cost_limit_reached is True
