"""Tests for lion.worktree module."""

import os
import shutil
import subprocess
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from lion.worktree import (
    WorktreeManager,
    Worktree,
    ConflictResolver,
    slugify,
)


class TestSlugify:
    """Tests for the slugify helper function."""

    def test_basic_slugify(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert slugify("Test: Something!") == "test-something"

    def test_multiple_spaces(self):
        assert slugify("too   many   spaces") == "too-many-spaces"

    def test_underscores(self):
        assert slugify("snake_case_name") == "snake-case-name"

    def test_truncation(self):
        long_name = "a" * 100
        result = slugify(long_name)
        assert len(result) <= 50

    def test_strips_trailing_dashes(self):
        assert slugify("test---") == "test"
        assert slugify("---test") == "test"


class TestWorktreeDataclass:
    """Tests for the Worktree dataclass."""

    def test_name_property(self):
        wt = Worktree(
            path="/tmp/wt",
            branch="lion/test-1",
            subtask_title="Test Task",
            subtask_index=1,
        )
        assert wt.name == "wt-1"

    def test_default_values(self):
        wt = Worktree(
            path="/tmp/wt",
            branch="lion/test-1",
            subtask_title="Test",
            subtask_index=1,
        )
        assert wt.completed is False
        assert wt.tests_passed is None
        assert wt.merged is False
        assert wt.error is None
        assert wt.files == []


class TestWorktreeManagerInit:
    """Tests for WorktreeManager initialization."""

    def test_init_not_git_repo_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Not a git repository"):
            WorktreeManager(cwd=str(tmp_path))

    def test_init_with_git_repo(self, tmp_path):
        # Create a git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        manager = WorktreeManager(cwd=str(tmp_path))
        assert manager.cwd == str(tmp_path)
        assert manager.worktrees == []

        # Cleanup
        manager.cleanup_all()

    def test_init_with_custom_base_dir(self, tmp_path):
        # Create git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        base_dir = tmp_path / "worktrees"
        manager = WorktreeManager(cwd=str(tmp_path), base_dir=str(base_dir))
        assert manager.base_dir == str(base_dir)
        assert os.path.exists(base_dir)

        manager.cleanup_all()


class TestWorktreeManagerCreate:
    """Tests for WorktreeManager.create()."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a git repo with an initial commit."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        return tmp_path

    def test_create_worktree(self, git_repo):
        manager = WorktreeManager(cwd=str(git_repo))

        subtask = {
            "title": "Add Authentication",
            "description": "Implement user login",
            "files": ["auth.py"],
        }

        wt = manager.create(subtask, index=1)

        assert wt.subtask_title == "Add Authentication"
        assert wt.subtask_index == 1
        assert wt.subtask_description == "Implement user login"
        assert wt.files == ["auth.py"]
        assert "add-authentication" in wt.branch.lower()
        assert os.path.exists(wt.path)
        assert len(manager.worktrees) == 1

        manager.cleanup_all()

    def test_create_multiple_worktrees(self, git_repo):
        manager = WorktreeManager(cwd=str(git_repo))

        for i in range(3):
            subtask = {"title": f"Task {i + 1}"}
            manager.create(subtask, index=i + 1)

        assert len(manager.worktrees) == 3
        assert all(os.path.exists(wt.path) for wt in manager.worktrees)

        manager.cleanup_all()

    def test_create_for_subtasks(self, git_repo):
        manager = WorktreeManager(cwd=str(git_repo))

        subtasks = [
            {"title": "Task A", "description": "Do A"},
            {"title": "Task B", "description": "Do B"},
        ]

        worktrees = manager.create_for_subtasks(subtasks)

        assert len(worktrees) == 2
        assert worktrees[0].subtask_title == "Task A"
        assert worktrees[1].subtask_title == "Task B"

        manager.cleanup_all()


class TestWorktreeManagerGetStatus:
    """Tests for WorktreeManager.get_status()."""

    @pytest.fixture
    def manager_with_worktrees(self, tmp_path):
        """Create manager with some worktrees in various states."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        manager = WorktreeManager(cwd=str(tmp_path))

        subtasks = [
            {"title": "Task 1"},
            {"title": "Task 2"},
            {"title": "Task 3"},
        ]
        worktrees = manager.create_for_subtasks(subtasks)

        # Set various states
        worktrees[0].completed = True
        worktrees[0].tests_passed = True
        worktrees[0].merged = True

        worktrees[1].completed = True
        worktrees[1].tests_passed = True

        worktrees[2].error = "Test failed"

        yield manager, worktrees

        manager.cleanup_all()

    def test_get_status_counters(self, manager_with_worktrees):
        manager, _ = manager_with_worktrees
        status = manager.get_status(include_details=False)

        assert status["total"] == 3
        assert status["completed"] == 2
        assert status["tests_passed"] == 2
        assert status["merged"] == 1
        assert status["errors"] == 1
        assert "worktrees" not in status

    def test_get_status_with_details(self, manager_with_worktrees):
        manager, _ = manager_with_worktrees
        status = manager.get_status(include_details=True)

        assert "worktrees" in status
        assert len(status["worktrees"]) == 3

        # Check first worktree details
        wt0 = status["worktrees"][0]
        assert wt0["completed"] is True
        assert wt0["merged"] is True


class TestWorktreeManagerRunTests:
    """Tests for WorktreeManager.run_tests()."""

    @pytest.fixture
    def manager_with_worktree(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        manager = WorktreeManager(cwd=str(tmp_path))
        wt = manager.create({"title": "Test"}, index=1)

        yield manager, wt

        manager.cleanup_all()

    def test_run_tests_no_test_command(self, manager_with_worktree):
        manager, wt = manager_with_worktree

        # No test files, so no test command detected
        result = manager.run_tests(wt)

        assert result is True  # No tests = passing
        assert wt.tests_passed is True

    def test_run_tests_with_passing_command(self, manager_with_worktree):
        manager, wt = manager_with_worktree

        result = manager.run_tests(wt, test_command="true")

        assert result is True
        assert wt.tests_passed is True

    def test_run_tests_with_failing_command(self, manager_with_worktree):
        manager, wt = manager_with_worktree

        result = manager.run_tests(wt, test_command="false")

        assert result is False
        assert wt.tests_passed is False
        assert wt.error is not None


class TestWorktreeManagerMerge:
    """Tests for WorktreeManager.merge()."""

    @pytest.fixture
    def manager_with_changes(self, tmp_path):
        """Create manager with a worktree that has changes to merge."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        manager = WorktreeManager(cwd=str(tmp_path))
        wt = manager.create({"title": "Feature"}, index=1)

        # Make changes in worktree
        test_file = os.path.join(wt.path, "feature.py")
        with open(test_file, "w") as f:
            f.write("def feature(): pass\n")

        subprocess.run(["git", "add", "."], cwd=wt.path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add feature"],
            cwd=wt.path,
            capture_output=True,
        )

        yield manager, wt

        manager.cleanup_all()

    def test_merge_success(self, manager_with_changes):
        manager, wt = manager_with_changes

        result = manager.merge(wt)

        assert result is True
        assert wt.merged is True

        # Verify file exists in main repo
        assert os.path.exists(os.path.join(manager.cwd, "feature.py"))

    def test_merge_conflict_auto_resolve_success(self, manager_with_changes):
        manager, wt = manager_with_changes

        # Create same file differently on main and worktree to force conflict.
        shared_main = os.path.join(manager.cwd, "shared.txt")
        with open(shared_main, "w", encoding="utf-8") as f:
            f.write("main version\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=manager.cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Main change"],
            cwd=manager.cwd,
            capture_output=True,
        )

        shared_wt = os.path.join(wt.path, "shared.txt")
        with open(shared_wt, "w", encoding="utf-8") as f:
            f.write("worktree version\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=wt.path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Worktree change"],
            cwd=wt.path,
            capture_output=True,
        )

        def resolver(_conflict_info, _task_title, conflict_content=None):
            assert conflict_content is not None
            return "resolved version\n"

        result = manager.merge(wt, resolve_conflicts=resolver)

        assert result is True
        assert wt.merged is True
        with open(shared_main, "r", encoding="utf-8") as f:
            assert f.read() == "resolved version"

    def test_merge_conflict_auto_resolve_failure_aborts(self, manager_with_changes):
        manager, wt = manager_with_changes

        shared_main = os.path.join(manager.cwd, "conflict.txt")
        with open(shared_main, "w", encoding="utf-8") as f:
            f.write("main version\n")
        subprocess.run(["git", "add", "conflict.txt"], cwd=manager.cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Main conflict change"],
            cwd=manager.cwd,
            capture_output=True,
        )

        shared_wt = os.path.join(wt.path, "conflict.txt")
        with open(shared_wt, "w", encoding="utf-8") as f:
            f.write("worktree version\n")
        subprocess.run(["git", "add", "conflict.txt"], cwd=wt.path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Worktree conflict change"],
            cwd=wt.path,
            capture_output=True,
        )

        def unresolved(_conflict_info, _task_title, conflict_content=None):
            assert conflict_content is not None
            return "CANNOT_RESOLVE"

        result = manager.merge(wt, resolve_conflicts=unresolved)

        assert result is False
        assert wt.merged is False
        assert wt.error == "Merge conflict - manual resolution required"


class TestWorktreeManagerRemove:
    """Tests for WorktreeManager.remove()."""

    @pytest.fixture
    def manager_with_worktree(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        manager = WorktreeManager(cwd=str(tmp_path))
        wt = manager.create({"title": "Test"}, index=1)

        yield manager, wt

        # Cleanup any remaining
        try:
            manager.cleanup_all()
        except Exception:
            pass

    def test_remove_worktree(self, manager_with_worktree):
        manager, wt = manager_with_worktree

        path = wt.path
        result = manager.remove(wt)

        assert result is True
        assert not os.path.exists(path)
        assert wt not in manager.worktrees


class TestConflictResolver:
    """Tests for ConflictResolver."""

    def test_resolve_no_conflicts(self, tmp_path):
        """When no conflicts exist, resolve returns None."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)

        mock_provider = MagicMock()
        resolver = ConflictResolver(
            provider=mock_provider,
            cwd=str(tmp_path),
        )

        result = resolver.resolve("No files", "Test Task")
        assert result is None

    def test_resolve_with_provided_content(self):
        """When conflict_content is provided, uses it directly."""
        mock_provider = MagicMock()
        mock_provider.ask.return_value = MagicMock(
            success=True,
            content="def resolved(): pass"
        )

        resolver = ConflictResolver(
            provider=mock_provider,
            cwd="/tmp",
        )

        result = resolver.resolve(
            "file.py",
            "Test Task",
            conflict_content="<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>>"
        )

        assert result == "def resolved(): pass"
        mock_provider.ask.assert_called_once()

    def test_resolve_cannot_resolve(self):
        """When LLM returns CANNOT_RESOLVE, returns None."""
        mock_provider = MagicMock()
        mock_provider.ask.return_value = MagicMock(
            success=True,
            content="CANNOT_RESOLVE - too complex"
        )

        resolver = ConflictResolver(
            provider=mock_provider,
            cwd="/tmp",
        )

        result = resolver.resolve(
            "file.py",
            "Test Task",
            conflict_content="complex conflict"
        )

        assert result is None

    def test_resolve_provider_failure(self):
        """When provider fails, returns None."""
        mock_provider = MagicMock()
        mock_provider.ask.return_value = MagicMock(success=False)

        resolver = ConflictResolver(
            provider=mock_provider,
            cwd="/tmp",
        )

        result = resolver.resolve(
            "file.py",
            "Test Task",
            conflict_content="conflict"
        )

        assert result is None
