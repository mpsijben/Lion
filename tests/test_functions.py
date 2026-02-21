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
        assert "devil" in FUNCTIONS
        assert "future" in FUNCTIONS
        assert "task" in FUNCTIONS

    def test_all_functions_are_callable(self):
        """Test that all registered functions are callable."""
        for name, func in FUNCTIONS.items():
            assert callable(func), f"{name} should be callable"


class TestPridePrompts:
    """Tests for pride function prompts."""

    def test_converge_prompt_prevents_file_operations(self):
        """Test that CONVERGE_PROMPT tells the agent not to ask for file permissions."""
        from lion.functions.pride import CONVERGE_PROMPT
        assert "TEXT PLAN only" in CONVERGE_PROMPT
        assert "Do NOT ask for file permissions" in CONVERGE_PROMPT
        assert "Do NOT try to write" in CONVERGE_PROMPT

    def test_implement_prompt_includes_deliberation(self):
        """Test that IMPLEMENT_PROMPT has a deliberation_summary placeholder."""
        from lion.functions.pride import IMPLEMENT_PROMPT
        assert "{deliberation_summary}" in IMPLEMENT_PROMPT
        assert "DELIBERATION CONTEXT" in IMPLEMENT_PROMPT

    def test_implement_passes_deliberation_to_prompt(self, temp_run_dir, sample_config):
        """Test that _implement() includes deliberation context in the prompt."""
        from lion.functions.pride import _implement
        from lion.memory import SharedMemory, MemoryEntry

        memory = SharedMemory(temp_run_dir)
        memory.write(MemoryEntry(
            timestamp=1.0,
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Use FastAPI for the REST endpoint",
        ))

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "Implementation done"
        mock_result.tokens_used = 500
        mock_result.model = "claude"
        mock_agent.implement.return_value = mock_result

        with patch("lion.functions.pride.Display"):
            _implement(mock_agent, "Build REST API", "Use FastAPI", "/tmp", memory)

        # Check that the prompt passed to implement() contains deliberation
        call_args = mock_agent.implement.call_args
        prompt_sent = call_args[0][0]
        assert "FastAPI" in prompt_sent
        assert "DELIBERATION CONTEXT" in prompt_sent


class TestExtractOneLiner:
    """Tests for _extract_one_liner function."""

    def test_skips_markdown_headers(self):
        from lion.functions.pride import _extract_one_liner
        content = "# My Proposal\n## Architecture\nUse FastAPI with PostgreSQL for the backend."
        result = _extract_one_liner(content)
        assert "Use FastAPI" in result
        assert "#" not in result

    def test_skips_table_rows(self):
        from lion.functions.pride import _extract_one_liner
        content = "## Approach\n| Decision | Choice | Rationale |\n|----------|--------|-----------|\nI propose using FastAPI."
        result = _extract_one_liner(content)
        assert "|" not in result
        assert "FastAPI" in result

    def test_skips_bold_bullets(self):
        from lion.functions.pride import _extract_one_liner
        content = "## Plan\n- **Step 1**: Do something\nThis proposal focuses on building a REST API."
        result = _extract_one_liner(content)
        assert "REST API" in result

    def test_skips_ai_preamble(self):
        from lion.functions.pride import _extract_one_liner
        content = "Now I have a complete understanding of the codebase. Here's my proposed approach for implementing...\n\nAPPROACH: Use FastAPI with PostgreSQL"
        result = _extract_one_liner(content)
        assert "Now I have" not in result

    def test_prefers_structured_keywords(self):
        from lion.functions.pride import _extract_one_liner
        content = "Some preamble text.\nAPPROACH: Build a REST API with FastAPI\nMore details here."
        result = _extract_one_liner(content)
        assert "Build a REST API" in result

    def test_skips_various_preambles(self):
        from lion.functions.pride import _extract_one_liner
        preambles = [
            "I have analyzed the codebase and here is what I found.",
            "Let me provide my analysis of the code.",
            "After reviewing the code, I've found several issues.",
            "Based on my analysis of the project structure.",
            "I've reviewed the existing implementation.",
        ]
        for preamble in preambles:
            content = f"{preamble}\nThe actual meaningful content here."
            result = _extract_one_liner(content)
            assert result == "The actual meaningful content here."

    def test_truncates_long_lines(self):
        from lion.functions.pride import _extract_one_liner
        content = "A" * 200
        result = _extract_one_liner(content)
        assert len(result) <= 104  # 100 + "..."

    def test_fallback_on_no_prose(self):
        from lion.functions.pride import _extract_one_liner
        content = "# Header\n## Subheader\n---"
        result = _extract_one_liner(content)
        assert "..." in result


class TestExtractDecisionSummary:
    """Tests for _extract_decision_summary function."""

    def test_extracts_decision_line(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "# PLAN\n\nDECISION: Use FastAPI with JWT auth\n\nTASKS:\n1. Build endpoint"
        result = _extract_decision_summary(plan)
        assert "Use FastAPI with JWT auth" in result

    def test_extracts_markdown_decision(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "# FINAL PLAN\n\n## DECISION: Simple FastAPI Login API with UUID Tokens\n\nTASKS:"
        result = _extract_decision_summary(plan)
        assert "Simple FastAPI" in result

    def test_skips_header_in_fallback(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "# FINAL SYNTHESIZED PLAN\nUse approach A because it is simpler."
        result = _extract_decision_summary(plan)
        assert "#" not in result
        assert "approach A" in result

    def test_handles_no_decision_line(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "# Plan\n---\nJust do it."
        result = _extract_decision_summary(plan)
        assert "Just do it" in result

    def test_truncates_long_decision(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "DECISION: " + "x" * 200
        result = _extract_decision_summary(plan)
        assert len(result) <= 154  # 150 + "..."

    def test_skips_preamble_in_fallback(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "Now I have a complete picture. Let me create the final plan.\nUse FastAPI for the backend."
        result = _extract_decision_summary(plan)
        assert "Now I have" not in result
        assert "FastAPI" in result

    def test_decision_on_next_line(self):
        from lion.functions.pride import _extract_decision_summary
        plan = "# PLAN\n\nDECISION:\nUse FastAPI with JWT auth for the backend\n\nTASKS:"
        result = _extract_decision_summary(plan)
        assert "FastAPI" in result


class TestTaskFunction:
    """Tests for task decomposition."""

    def test_parse_subtasks(self):
        from lion.functions.task import _parse_subtasks
        content = """SUBTASK 1: Build user model
DESCRIPTION: Create the User model with SQLAlchemy
FILES: models/user.py, models/__init__.py
DEPENDS_ON: none
PARALLEL: yes

SUBTASK 2: Build auth endpoints
DESCRIPTION: Create login and register endpoints
FILES: routes/auth.py
DEPENDS_ON: 1
PARALLEL: no"""
        result = _parse_subtasks(content, 10)
        assert len(result) == 2
        assert result[0]["title"] == "Build user model"
        assert result[0]["parallel"] is True
        assert result[0]["depends_on"] == []
        assert result[1]["depends_on"] == [1]
        assert "models/user.py" in result[0]["files"]

    def test_parse_subtasks_respects_max(self):
        from lion.functions.task import _parse_subtasks
        content = """SUBTASK 1: Task A
DESCRIPTION: Do A
FILES: a.py
DEPENDS_ON: none
PARALLEL: yes

SUBTASK 2: Task B
DESCRIPTION: Do B
FILES: b.py
DEPENDS_ON: none
PARALLEL: yes

SUBTASK 3: Task C
DESCRIPTION: Do C
FILES: c.py
DEPENDS_ON: 1, 2
PARALLEL: no"""
        result = _parse_subtasks(content, 2)
        assert len(result) == 2

    def test_parse_subtasks_empty(self):
        from lion.functions.task import _parse_subtasks
        result = _parse_subtasks("No structured output here", 5)
        assert result == []


class TestBuildDependencyLevels:
    """Tests for dependency level grouping."""

    def test_independent_tasks(self):
        from lion.pipeline import _build_dependency_levels
        subtasks = [
            {"title": "A", "depends_on": [], "parallel": True},
            {"title": "B", "depends_on": [], "parallel": True},
        ]
        levels = _build_dependency_levels(subtasks)
        assert len(levels) == 1
        assert set(levels[0]) == {0, 1}

    def test_dependent_tasks(self):
        from lion.pipeline import _build_dependency_levels
        subtasks = [
            {"title": "A", "depends_on": []},
            {"title": "B", "depends_on": [1]},  # depends on task 1 (0-indexed: 0)
            {"title": "C", "depends_on": [2]},  # depends on task 2 (0-indexed: 1)
        ]
        levels = _build_dependency_levels(subtasks)
        assert len(levels) == 3
        assert levels[0] == [0]
        assert levels[1] == [1]
        assert levels[2] == [2]

    def test_mixed_dependencies(self):
        from lion.pipeline import _build_dependency_levels
        subtasks = [
            {"title": "A", "depends_on": []},
            {"title": "B", "depends_on": []},
            {"title": "C", "depends_on": [1, 2]},
        ]
        levels = _build_dependency_levels(subtasks)
        assert len(levels) == 2
        assert set(levels[0]) == {0, 1}
        assert levels[1] == [2]


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


class TestSummarizeProposal:
    """Tests for _summarize_proposal function."""

    def test_summarize_with_structured_sections(self):
        from lion.functions.pride import _summarize_proposal
        content = """## Approach
Use FastAPI with JWT authentication for the backend.

## Key Findings
- FastAPI is faster than Flask
- JWT is industry standard

## Warnings
- Rate limiting needed

## Reasoning
FastAPI provides async support natively.
"""
        result = _summarize_proposal(content)
        assert "FastAPI" in result
        assert "Approach:" in result
        assert "Key Findings:" in result
        assert "Warnings:" in result

    def test_summarize_without_sections_falls_back(self):
        from lion.functions.pride import _summarize_proposal
        content = "Just a raw text proposal without any headers or structure. " * 20
        result = _summarize_proposal(content, max_chars=100)
        assert len(result) <= 100

    def test_summarize_respects_max_chars(self):
        from lion.functions.pride import _summarize_proposal
        content = """## Approach
""" + "A" * 2000
        result = _summarize_proposal(content, max_chars=500)
        assert len(result) <= 500

    def test_summarize_empty_content(self):
        from lion.functions.pride import _summarize_proposal
        result = _summarize_proposal("")
        assert result == ""


class TestBuildConvergeContext:
    """Tests for _build_converge_context function."""

    def test_basic_converge_context(self):
        from lion.functions.pride import _build_converge_context
        proposals = [
            {
                "agent": "agent_1",
                "model": "claude",
                "content": "## Approach\nUse FastAPI\n\n## Warnings\n- Need auth",
                "confidence": 0.8,
                "lens": None,
            },
            {
                "agent": "agent_2",
                "model": "gemini",
                "content": "## Approach\nUse Django\n\n## Warnings\n- Complex setup",
                "confidence": 0.6,
                "lens": None,
            },
        ]
        critiques = [
            {"agent": "agent_1", "content": "Agent 2's Django approach is slower"},
        ]

        result = _build_converge_context(proposals, critiques, [])
        assert "Agent agent_1" in result
        assert "Agent agent_2" in result
        assert "CRITIQUES" in result

    def test_converge_context_respects_max(self):
        from lion.functions.pride import _build_converge_context
        proposals = [
            {
                "agent": "agent_1",
                "model": "claude",
                "content": "A" * 5000,
                "confidence": 0.8,
                "lens": None,
            },
        ]

        result = _build_converge_context(proposals, [], [], max_chars=500)
        assert len(result) <= 520  # 500 + "\n... (truncated)"

    def test_converge_context_includes_toon_metadata(self):
        from lion.functions.pride import _build_converge_context
        proposals = [
            {
                "agent": "agent_1",
                "model": "claude",
                "content": "## Approach\nTest",
                "confidence": 0.8,
                "lens": None,
            },
        ]
        result = _build_converge_context(proposals, [], [])
        # Should have TOON-encoded agent metadata
        assert "agents[" in result


class TestBuildImplementContext:
    """Tests for _build_implement_context function."""

    def test_extracts_decisions_and_warnings(self, temp_run_dir):
        from lion.functions.pride import _build_implement_context
        from lion.memory import SharedMemory, MemoryEntry

        memory = SharedMemory(temp_run_dir)
        memory.write(MemoryEntry(
            timestamp=1.0,
            phase="converge",
            agent="synthesizer",
            type="decision",
            content="DECISION: Use FastAPI with PostgreSQL",
        ))
        memory.write(MemoryEntry(
            timestamp=2.0,
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="## Approach\nUse FastAPI\n\n## Warnings\n- Need rate limiting\n- Add CORS",
        ))

        result = _build_implement_context(memory)
        assert "Decision:" in result
        assert "FastAPI" in result
        assert "rate limiting" in result

    def test_respects_max_chars(self, temp_run_dir):
        from lion.functions.pride import _build_implement_context
        from lion.memory import SharedMemory, MemoryEntry

        memory = SharedMemory(temp_run_dir)
        memory.write(MemoryEntry(
            timestamp=1.0,
            phase="converge",
            agent="synthesizer",
            type="decision",
            content="A" * 10000,
        ))

        result = _build_implement_context(memory, max_chars=500)
        assert len(result) <= 500
