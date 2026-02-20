"""Tests for lion.functions module."""

import os
import pytest
from unittest.mock import patch, MagicMock

from lion.functions import FUNCTIONS
from lion.functions.review import execute_review, _extract_issues
from lion.functions.test import execute_test, _detect_framework, _run_tests, _extract_failures
from lion.functions.pr import (
    execute_pr,
    _generate_branch_name,
    _is_git_repo,
    _get_git_status,
    _get_main_branch,
)
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestFunctionsRegistry:
    """Tests for functions registry."""

    def test_registry_contains_expected_functions(self):
        """Test that FUNCTIONS registry contains expected functions."""
        assert "pride" in FUNCTIONS
        assert "review" in FUNCTIONS
        assert "test" in FUNCTIONS
        assert "pr" in FUNCTIONS
        assert "create_tests" in FUNCTIONS
        assert "create_test" in FUNCTIONS
        assert "lint" in FUNCTIONS
        assert "typecheck" in FUNCTIONS

    def test_all_functions_are_callable(self):
        """Test that all registered functions are callable."""
        for name, func in FUNCTIONS.items():
            assert callable(func), f"{name} should be callable"


class TestReviewFunction:
    """Tests for execute_review function."""

    def test_review_success(self, temp_run_dir, sample_config):
        """Test successful code review."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = """## Summary
Good code overall.

## Issues Found
### [WARNING] Missing error handling
- **Location**: src/main.py
- **Problem**: No try/catch
- **Fix**: Add error handling

## Recommendations
None
"""
        mock_result.tokens_used = 200
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.review.get_provider", return_value=mock_provider):
            with patch("lion.functions.review.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_review(
                    prompt="Build feature",
                    previous={"code": "def foo(): pass"},
                    step=PipelineStep(function="review"),
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        assert result["success"] is True
        assert result["review_passed"] is True  # No critical issues
        assert result["warning_count"] == 1

    def test_review_with_critical_issues(self, temp_run_dir, sample_config):
        """Test review that finds critical issues."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = """## Summary
Security issue found.

## Issues Found
### [CRITICAL] SQL Injection vulnerability
- **Location**: src/db.py
- **Problem**: User input not sanitized
- **Fix**: Use parameterized queries
"""
        mock_result.tokens_used = 150
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.review.get_provider", return_value=mock_provider):
            with patch("lion.functions.review.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_review(
                    prompt="Fix bug",
                    previous={"code": "SELECT * FROM users WHERE id = " + "user_input"},
                    step=PipelineStep(function="review"),
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        assert result["review_passed"] is False
        assert result["critical_count"] == 1

    def test_review_with_custom_provider(self, temp_run_dir, sample_config):
        """Test review with custom provider specified."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "Review complete"
        mock_result.tokens_used = 100
        mock_result.model = "gemini"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.review.get_provider", return_value=mock_provider) as mock_get:
            with patch("lion.functions.review.Display"):
                memory = SharedMemory(temp_run_dir)
                execute_review(
                    prompt="Review",
                    previous={},
                    step=PipelineStep(function="review", args=["gemini"]),
                    memory=memory,
                    config=sample_config,
                    cwd="/tmp",
                )

        mock_get.assert_called_with("gemini", sample_config)


class TestExtractIssues:
    """Tests for _extract_issues function."""

    def test_extract_critical_issues(self):
        """Test extracting critical issues."""
        content = """
### [CRITICAL] Security Issue
Details here

### [WARNING] Performance concern
More details
"""
        issues = _extract_issues(content)
        assert len(issues) == 2
        assert issues[0]["severity"] == "critical"
        assert issues[1]["severity"] == "warning"

    def test_extract_issues_case_insensitive(self):
        """Test that severity extraction is case insensitive."""
        content = """
### [critical] Issue 1
### [WARNING] Issue 2
### [Suggestion] Issue 3
"""
        issues = _extract_issues(content)
        assert len(issues) == 3
        assert issues[0]["severity"] == "critical"
        assert issues[1]["severity"] == "warning"
        assert issues[2]["severity"] == "suggestion"

    def test_extract_issues_no_issues(self):
        """Test extracting from content with no issues."""
        content = "Everything looks good!"
        issues = _extract_issues(content)
        assert issues == []


class TestTestFunction:
    """Tests for execute_test function."""

    def test_test_no_framework_detected(self, temp_run_dir, sample_config, temp_dir):
        """Test when no test framework is detected."""
        with patch("lion.functions.test.Display"):
            memory = SharedMemory(temp_run_dir)
            result = execute_test(
                prompt="Run tests",
                previous={},
                step=PipelineStep(function="test"),
                memory=memory,
                config=sample_config,
                cwd=temp_dir,
            )

        assert result["success"] is True
        assert result["skipped"] is True

    def test_test_success(self, temp_run_dir, sample_config, temp_dir):
        """Test successful test execution."""
        # Create pytest marker file
        with open(os.path.join(temp_dir, "pytest.ini"), "w") as f:
            f.write("[pytest]\n")

        mock_run_result = (True, "All tests passed")

        with patch("lion.functions.test._run_tests", return_value=mock_run_result):
            with patch("lion.functions.test.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_test(
                    prompt="Run tests",
                    previous={},
                    step=PipelineStep(function="test"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is True
        assert result["framework"] == "pytest"

    def test_test_with_nofix(self, temp_run_dir, sample_config, temp_dir):
        """Test with nofix argument."""
        with open(os.path.join(temp_dir, "pytest.ini"), "w") as f:
            f.write("[pytest]\n")

        mock_run_result = (False, "Test failed")

        with patch("lion.functions.test._run_tests", return_value=mock_run_result):
            with patch("lion.functions.test.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_test(
                    prompt="Run tests",
                    previous={},
                    step=PipelineStep(function="test", args=["nofix"]),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is False
        assert result["nofix"] is True


class TestDetectFramework:
    """Tests for _detect_framework function."""

    def test_detect_pytest(self, temp_dir):
        """Test detecting pytest framework."""
        with open(os.path.join(temp_dir, "pytest.ini"), "w") as f:
            f.write("[pytest]\n")

        framework, command = _detect_framework(temp_dir)
        assert framework == "pytest"
        assert "pytest" in command

    def test_detect_pytest_from_conftest(self, temp_dir):
        """Test detecting pytest from conftest.py."""
        with open(os.path.join(temp_dir, "conftest.py"), "w") as f:
            f.write("import pytest\n")

        framework, command = _detect_framework(temp_dir)
        assert framework == "pytest"

    def test_detect_jest(self, temp_dir):
        """Test detecting jest framework."""
        with open(os.path.join(temp_dir, "jest.config.js"), "w") as f:
            f.write("module.exports = {};\n")

        framework, command = _detect_framework(temp_dir)
        assert framework == "jest"

    def test_detect_no_framework(self, temp_dir):
        """Test when no framework is detected."""
        framework, command = _detect_framework(temp_dir)
        assert framework is None
        assert command == []


class TestRunTests:
    """Tests for _run_tests function."""

    def test_run_tests_success(self, temp_dir):
        """Test successful test run."""
        with patch("lion.functions.test.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="All tests passed",
                stderr=""
            )

            success, output = _run_tests(["pytest", "-v"], temp_dir)

        assert success is True
        assert "All tests passed" in output

    def test_run_tests_failure(self, temp_dir):
        """Test failed test run."""
        with patch("lion.functions.test.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Test failed"
            )

            success, output = _run_tests(["pytest"], temp_dir)

        assert success is False

    def test_run_tests_timeout(self, temp_dir):
        """Test test run timeout."""
        import subprocess

        with patch("lion.functions.test.subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 300)):
            success, output = _run_tests(["pytest"], temp_dir)

        assert success is False
        assert "timed out" in output


class TestPrFunction:
    """Tests for execute_pr function."""

    def test_pr_not_git_repo(self, temp_run_dir, sample_config, temp_dir):
        """Test PR creation in non-git directory."""
        with patch("lion.functions.pr.Display"):
            memory = SharedMemory(temp_run_dir)
            result = execute_pr(
                prompt="Create PR",
                previous={},
                step=PipelineStep(function="pr"),
                memory=memory,
                config=sample_config,
                cwd=temp_dir,
            )

        assert result["success"] is False
        assert "Not a git repository" in result["error"]

    def test_pr_no_changes(self, temp_run_dir, sample_config, git_repo):
        """Test PR when there are no changes."""
        with patch("lion.functions.pr.Display"):
            memory = SharedMemory(temp_run_dir)
            result = execute_pr(
                prompt="Create PR",
                previous={},
                step=PipelineStep(function="pr"),
                memory=memory,
                config=sample_config,
                cwd=git_repo,
            )

        assert result["success"] is True
        assert result["skipped"] is True


class TestGenerateBranchName:
    """Tests for _generate_branch_name function."""

    def test_basic_branch_name(self):
        """Test basic branch name generation."""
        name = _generate_branch_name("Build a new feature")
        assert name.startswith("feature/")
        assert "build" in name or "new" in name or "feature" in name

    def test_branch_name_removes_stop_words(self):
        """Test that stop words are removed."""
        name = _generate_branch_name("Fix the bug in the code")
        assert "the" not in name
        assert "in" not in name

    def test_branch_name_limits_length(self):
        """Test that branch name is limited in length."""
        long_prompt = "Build a very long feature with lots of words " * 10
        name = _generate_branch_name(long_prompt)
        assert len(name) <= 50

    def test_branch_name_fallback(self):
        """Test fallback when no meaningful words."""
        name = _generate_branch_name("a the in on")
        assert name.startswith("feature/")


class TestIsGitRepo:
    """Tests for _is_git_repo function."""

    def test_is_git_repo_true(self, git_repo):
        """Test detection of git repository."""
        assert _is_git_repo(git_repo) is True

    def test_is_git_repo_false(self, temp_dir):
        """Test detection of non-git directory."""
        assert _is_git_repo(temp_dir) is False


class TestGetGitStatus:
    """Tests for _get_git_status function."""

    def test_get_git_status_no_changes(self, git_repo):
        """Test git status with no changes."""
        has_changes, files = _get_git_status(git_repo)
        assert has_changes is False
        assert files == []

    def test_get_git_status_with_changes(self, git_repo):
        """Test git status with uncommitted changes."""
        # Create a new file
        with open(os.path.join(git_repo, "new_file.txt"), "w") as f:
            f.write("content")

        has_changes, files = _get_git_status(git_repo)
        assert has_changes is True
        assert "new_file.txt" in files


class TestGetMainBranch:
    """Tests for _get_main_branch function."""

    def test_get_main_branch(self, git_repo):
        """Test getting main branch name."""
        # Most init creates 'main' or 'master'
        branch = _get_main_branch(git_repo)
        assert branch in ["main", "master"]


class TestExtractFailures:
    """Tests for _extract_failures function in test module."""

    def test_extract_pytest_failures(self):
        """Test extracting failures from pytest output."""
        output = """
===== FAILURES =====
___ test_example ___

    def test_example():
>       assert 1 == 2
E       assert 1 == 2

test_file.py:5: AssertionError
===== 1 failed =====
"""
        failures = _extract_failures(output, "pytest")
        assert failures  # Should have extracted some failure info

    def test_extract_no_failures(self):
        """Test extracting from output with no failures."""
        output = "All tests passed!"
        failures = _extract_failures(output, "pytest")
        # Should return something even if no structured failures found
        assert isinstance(failures, str)
