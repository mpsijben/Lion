"""Git worktree management for parallel agent operations.

Phase 3 of pair.md: Worktree Provisioning

Enables isolated parallel execution of subtasks via git worktrees.
Each subtask gets its own worktree with a dedicated branch, allowing
multiple agents to work simultaneously without file conflicts.

Usage:
    manager = WorktreeManager(cwd="/path/to/repo")

    # Create worktrees for subtasks
    worktrees = manager.create_for_subtasks(subtasks)

    # Run tasks in isolation...

    # Test and merge
    for wt in worktrees:
        if manager.run_tests(wt):
            manager.merge(wt)
        else:
            # Handle failure
            pass

    # Cleanup
    manager.cleanup_all()
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .display import Display
from .memory import SharedMemory, MemoryEntry

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to a safe branch/directory name."""
    # Lowercase and replace spaces/special chars with dashes
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:50].strip("-")  # Limit length


@dataclass
class Worktree:
    """Represents a git worktree for isolated task execution."""
    path: str
    branch: str
    subtask_title: str
    subtask_index: int
    subtask_description: str = ""
    files: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    # State tracking
    completed: bool = False
    tests_passed: bool | None = None
    merged: bool = False
    error: str | None = None

    @property
    def name(self) -> str:
        """Short identifier for display."""
        return f"wt-{self.subtask_index}"


class WorktreeManager:
    """Manages git worktrees for parallel subtask execution.

    Core responsibilities:
    1. Create isolated worktrees for each subtask
    2. Track worktree state (created, tested, merged, cleaned)
    3. Run tests in worktrees before merge
    4. Handle merge conflicts via dedicated agent
    5. Clean up worktrees after completion

    Worktrees are created in a temporary directory to avoid cluttering
    the main repo. Each worktree has its own branch based on the current
    HEAD at creation time.
    """

    # Maximum concurrent worktrees to avoid disk pressure
    MAX_WORKTREES = 10

    def __init__(
        self,
        cwd: str,
        base_dir: str | None = None,
        memory: SharedMemory | None = None,
    ):
        """Initialize the worktree manager.

        Args:
            cwd: Path to the main git repository
            base_dir: Base directory for worktrees (default: temp dir)
            memory: SharedMemory for logging (optional)
        """
        self.cwd = os.path.abspath(cwd)
        self.memory = memory

        # Verify we're in a git repo
        if not self._is_git_repo():
            raise ValueError(f"Not a git repository: {cwd}")

        # Set up worktree base directory
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
            os.makedirs(self.base_dir, exist_ok=True)
        else:
            # Use temp directory with lion prefix
            self.base_dir = tempfile.mkdtemp(prefix="lion-worktrees-")

        # Track active worktrees
        self.worktrees: list[Worktree] = []

        # Get current branch/commit for worktree base
        self.base_ref = self._get_current_ref()

        self._log("worktree_init", f"WorktreeManager initialized at {self.base_dir}")

    def _is_git_repo(self) -> bool:
        """Check if cwd is a git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_current_ref(self) -> str:
        """Get current HEAD reference (branch name or commit hash)."""
        try:
            # Try to get branch name first
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip() != "HEAD":
                return result.stdout.strip()

            # Fall back to commit hash (detached HEAD)
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()[:12]
        except Exception:
            return "HEAD"

    def get_current_commit_hash(self, cwd: str | None = None) -> str | None:
        """Get the current commit hash (full SHA).

        Args:
            cwd: Working directory (default: self.cwd)

        Returns:
            Full commit hash or None if not in a git repo
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd or self.cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None

    def create_from_hash(
        self,
        commit_hash: str,
        branch_name: str,
        worktree_name: str | None = None,
    ) -> Worktree:
        """Create a worktree from a specific commit hash.

        Used for session resume to start from a known state.

        Args:
            commit_hash: Git commit hash to start from
            branch_name: Name for the new branch
            worktree_name: Name for the worktree directory (default: branch_name)

        Returns:
            Worktree object

        Raises:
            RuntimeError: If commit doesn't exist or worktree creation fails
        """
        # Verify commit exists
        result = self._run_git(["cat-file", "-t", commit_hash])
        if result.returncode != 0:
            raise RuntimeError(f"Commit {commit_hash} does not exist")

        # Clean up branch name
        if not branch_name.startswith("lion/"):
            branch_name = f"lion/{branch_name}"

        wt_name = worktree_name or slugify(branch_name.replace("lion/", ""))
        path = os.path.join(self.base_dir, f"lion-{wt_name}")

        # Ensure path doesn't exist
        if os.path.exists(path):
            shutil.rmtree(path)

        # Create the worktree with a new branch from the commit
        result = self._run_git([
            "worktree", "add",
            "-b", branch_name,
            path,
            commit_hash,
        ])

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Failed to create worktree from hash: {error}")

        worktree = Worktree(
            path=path,
            branch=branch_name,
            subtask_title=f"Resume from {commit_hash[:8]}",
            subtask_index=len(self.worktrees) + 1,
        )

        self.worktrees.append(worktree)

        self._log(
            "worktree_from_hash",
            f"Created worktree from commit {commit_hash[:8]} at {path}",
            {"branch": branch_name, "path": path, "commit": commit_hash},
        )

        Display.notify(f"Created worktree from {commit_hash[:8]}: {branch_name}")

        return worktree

    def has_uncommitted_changes(self, cwd: str | None = None) -> bool:
        """Check if there are uncommitted changes in the working directory.

        Args:
            cwd: Working directory to check (default: self.cwd)

        Returns:
            True if there are uncommitted changes
        """
        result = self._run_git(["status", "--porcelain"], cwd=cwd or self.cwd)
        return bool(result.stdout.strip())

    def reset_to_step(
        self,
        session,  # Session object from session.py
        step_number: int,
        branch_name: str | None = None,
        force: bool = False,
    ) -> Worktree | None:
        """Create a worktree reset to a specific session step.

        Used for resuming a session from a specific point. This creates a
        NEW worktree rather than modifying the current working directory,
        which is safer as it preserves any local changes.

        Args:
            session: Session object with step history
            step_number: Step number to reset to (1-based), or 0 for base commit
            branch_name: Name for the new branch (default: auto-generated)
            force: If True, skip uncommitted changes check. Default False.

        Returns:
            Worktree object or None if step doesn't have a commit hash

        Raises:
            ValueError: If there are uncommitted changes and force=False
        """
        # Safety check: warn about uncommitted changes in current directory
        # Note: We create a worktree (not reset current dir), so this is
        # just a warning to help users not lose track of their work
        if not force and self.has_uncommitted_changes():
            Display.notify(
                "Warning: Current directory has uncommitted changes. "
                "These will NOT be affected (new worktree is created)."
            )

        # Get the commit hash for the step
        commit_hash = session.get_commit_at_step(step_number)

        if not commit_hash:
            # Try to use base commit if step 0 (before any steps)
            if step_number == 0 and session.base_commit:
                commit_hash = session.base_commit
            else:
                Display.step_error(
                    "worktree",
                    f"Step {step_number} has no commit hash recorded"
                )
                return None

        # Generate branch name using short_id for readability
        if not branch_name:
            short_id = getattr(session, 'short_id', session.session_id[:8])
            branch_name = f"lion/resume-{short_id}-step{step_number}"

        try:
            short_id = getattr(session, 'short_id', session.session_id[:8])
            return self.create_from_hash(
                commit_hash=commit_hash,
                branch_name=branch_name,
                worktree_name=f"resume-{short_id}-step{step_number}",
            )
        except RuntimeError as e:
            Display.step_error("worktree", str(e))
            return None

    def create_commit(
        self,
        message: str,
        cwd: str | None = None,
    ) -> str | None:
        """Create a commit with all staged and unstaged changes.

        Used by pipeline to auto-commit after each step. Only creates a
        commit if there are actual changes to commit.

        Args:
            message: Commit message
            cwd: Working directory (default: self.cwd)

        Returns:
            Commit hash of the newly created commit, or None if:
            - No changes to commit
            - Commit failed for any reason
            - Repository is in a state that prevents committing

        Note:
            Returns the actual commit hash created, NOT HEAD (which could
            be different if the user made manual commits during the step).
        """
        work_dir = cwd or self.cwd

        # Check for changes (staged or unstaged)
        result = self._run_git(["status", "--porcelain"], cwd=work_dir)
        if not result.stdout.strip():
            # No changes to commit - this is normal for steps that
            # only read/analyze code without modifying files
            return None

        # Stage all changes
        result = self._run_git(["add", "-A"], cwd=work_dir)
        if result.returncode != 0:
            logger.warning("git add failed: %s", result.stderr)
            return None

        # Create commit and capture the hash directly from the output
        result = self._run_git(["commit", "-m", message], cwd=work_dir)
        if result.returncode != 0:
            # Commit failed - could be pre-commit hook, empty commit, etc.
            logger.warning("git commit failed: %s", result.stderr)
            return None

        # Get the hash of the commit we just created
        # Use rev-parse HEAD which gives us the actual commit just made
        return self.get_current_commit_hash(cwd=work_dir)

    def _log(self, event_type: str, content: str, metadata: dict | None = None):
        """Log to memory if available."""
        if self.memory:
            self.memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="worktree",
                agent="worktree_manager",
                type=event_type,
                content=content,
                metadata=metadata or {},
            ))

    def _run_git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
        """Run a git command and return the result."""
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.cwd,
            capture_output=True,
            text=True,
        )

    def create(self, subtask: dict, index: int) -> Worktree:
        """Create a worktree for a single subtask.

        Args:
            subtask: Subtask dict with title, description, files
            index: Subtask index (1-based)

        Returns:
            Worktree object
        """
        if len(self.worktrees) >= self.MAX_WORKTREES:
            raise RuntimeError(
                f"Maximum worktrees ({self.MAX_WORKTREES}) reached. "
                f"Clean up existing worktrees first."
            )

        title = subtask.get("title", f"subtask-{index}")
        slug = slugify(title)
        branch = f"lion/{slug}-{index}"
        path = os.path.join(self.base_dir, f"lion-{slug}-{index}")

        # Ensure path doesn't exist
        if os.path.exists(path):
            shutil.rmtree(path)

        # Create the worktree with a new branch
        result = self._run_git([
            "worktree", "add",
            "-b", branch,
            path,
            self.base_ref,
        ])

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Failed to create worktree: {error}")

        worktree = Worktree(
            path=path,
            branch=branch,
            subtask_title=title,
            subtask_index=index,
            subtask_description=subtask.get("description", ""),
            files=subtask.get("files", []),
        )

        self.worktrees.append(worktree)

        self._log(
            "worktree_created",
            f"Created worktree for '{title}' at {path}",
            {"branch": branch, "path": path, "subtask_index": index},
        )

        Display.notify(f"Created worktree: {branch}")

        return worktree

    def create_for_subtasks(self, subtasks: list[dict]) -> list[Worktree]:
        """Create worktrees for multiple subtasks.

        Args:
            subtasks: List of subtask dicts from task() decomposition

        Returns:
            List of Worktree objects
        """
        if len(subtasks) > self.MAX_WORKTREES:
            Display.notify(
                f"Warning: {len(subtasks)} subtasks exceeds max worktrees "
                f"({self.MAX_WORKTREES}). Some will run sequentially."
            )

        created = []
        for i, subtask in enumerate(subtasks[:self.MAX_WORKTREES]):
            try:
                wt = self.create(subtask, i + 1)
                created.append(wt)
            except Exception as e:
                Display.step_error("worktree", f"Failed to create worktree {i + 1}: {e}")
                self._log("worktree_error", str(e), {"subtask_index": i + 1})

        return created

    def list_active(self) -> list[Worktree]:
        """Return list of active (non-removed) worktrees."""
        return [wt for wt in self.worktrees if os.path.exists(wt.path)]

    def run_tests(
        self,
        worktree: Worktree,
        test_command: str | None = None,
        timeout: int = 300,
    ) -> bool:
        """Run tests in a worktree.

        Args:
            worktree: The worktree to test
            test_command: Custom test command (default: auto-detect)
            timeout: Test timeout in seconds

        Returns:
            True if tests pass, False otherwise
        """
        if not os.path.exists(worktree.path):
            worktree.error = "Worktree path does not exist"
            return False

        # Auto-detect test command if not provided
        if not test_command:
            test_command = self._detect_test_command(worktree.path)

        if not test_command:
            # No tests found - consider it passing
            Display.notify(f"[{worktree.name}] No tests found, skipping")
            worktree.tests_passed = True
            return True

        Display.notify(f"[{worktree.name}] Running tests: {test_command}")

        try:
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=worktree.path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            worktree.tests_passed = result.returncode == 0

            if worktree.tests_passed:
                Display.notify(f"[{worktree.name}] Tests passed")
                self._log(
                    "tests_passed",
                    f"Tests passed for {worktree.subtask_title}",
                    {"worktree": worktree.path},
                )
            else:
                error_output = result.stderr or result.stdout
                worktree.error = error_output[:1000] if error_output else "Tests failed"
                Display.step_error(
                    "worktree",
                    f"[{worktree.name}] Tests failed: {worktree.error[:200]}",
                )
                self._log(
                    "tests_failed",
                    f"Tests failed for {worktree.subtask_title}",
                    {"worktree": worktree.path, "error": worktree.error[:500]},
                )

            return worktree.tests_passed

        except subprocess.TimeoutExpired:
            worktree.error = f"Tests timed out after {timeout}s"
            worktree.tests_passed = False
            Display.step_error("worktree", f"[{worktree.name}] {worktree.error}")
            return False
        except Exception as e:
            worktree.error = str(e)
            worktree.tests_passed = False
            Display.step_error("worktree", f"[{worktree.name}] Test error: {e}")
            return False

    def _detect_test_command(self, path: str) -> str | None:
        """Auto-detect the test command for a project."""
        # Check for common test runners
        if os.path.exists(os.path.join(path, "package.json")):
            # Node.js project
            return "npm test"
        elif os.path.exists(os.path.join(path, "pyproject.toml")):
            return "pytest"
        elif os.path.exists(os.path.join(path, "setup.py")):
            return "pytest"
        elif os.path.exists(os.path.join(path, "Cargo.toml")):
            return "cargo test"
        elif os.path.exists(os.path.join(path, "go.mod")):
            return "go test ./..."
        elif os.path.exists(os.path.join(path, "Makefile")):
            # Check if Makefile has a test target
            with open(os.path.join(path, "Makefile")) as f:
                if "test:" in f.read():
                    return "make test"

        return None

    def merge(
        self,
        worktree: Worktree,
        target_branch: str | None = None,
        resolve_conflicts: Callable[[str, str], str | None] | None = None,
    ) -> bool:
        """Merge a worktree's branch back into the target branch.

        Args:
            worktree: The worktree to merge
            target_branch: Branch to merge into (default: base_ref)
            resolve_conflicts: Callback for conflict resolution (receives conflict info,
                               returns resolved content or None to abort)

        Returns:
            True if merge succeeds, False otherwise
        """
        if not os.path.exists(worktree.path):
            worktree.error = "Worktree path does not exist"
            return False

        target = target_branch or self.base_ref

        # First, commit any uncommitted changes in the worktree
        self._commit_worktree_changes(worktree)

        # Checkout target branch in main repo
        result = self._run_git(["checkout", target])
        if result.returncode != 0:
            worktree.error = f"Failed to checkout {target}: {result.stderr}"
            return False

        # Try to merge
        result = self._run_git(["merge", "--no-ff", worktree.branch, "-m",
                                f"Merge {worktree.branch}: {worktree.subtask_title}"])

        if result.returncode == 0:
            worktree.merged = True
            Display.notify(f"[{worktree.name}] Merged into {target}")
            self._log(
                "worktree_merged",
                f"Merged {worktree.branch} into {target}",
                {"worktree": worktree.path, "branch": worktree.branch},
            )
            return True

        # Check for conflicts
        if "CONFLICT" in result.stdout or "CONFLICT" in result.stderr:
            Display.notify(f"[{worktree.name}] Merge conflict detected")

            if resolve_conflicts:
                # Get conflict info
                conflict_result = self._run_git(["diff", "--name-only", "--diff-filter=U"])
                conflicted_files = conflict_result.stdout.strip().split("\n")

                conflict_info = f"Conflicted files: {', '.join(conflicted_files)}"

                # Try to resolve
                resolution = resolve_conflicts(conflict_info, worktree.subtask_title)

                if resolution:
                    # Stage resolved files and complete merge
                    self._run_git(["add", "."])
                    result = self._run_git(["commit", "-m",
                        f"Resolve conflicts for {worktree.branch}"])

                    if result.returncode == 0:
                        worktree.merged = True
                        Display.notify(f"[{worktree.name}] Conflicts resolved and merged")
                        self._log(
                            "conflict_resolved",
                            f"Resolved conflicts for {worktree.branch}",
                            {"files": conflicted_files},
                        )
                        return True

            # Abort the merge
            self._run_git(["merge", "--abort"])
            worktree.error = "Merge conflict - manual resolution required"
            self._log(
                "merge_conflict",
                f"Merge conflict for {worktree.branch}",
                {"worktree": worktree.path},
            )
            return False

        # Other merge error
        worktree.error = result.stderr or result.stdout or "Merge failed"
        Display.step_error("worktree", f"[{worktree.name}] Merge failed: {worktree.error[:200]}")
        return False

    def _commit_worktree_changes(self, worktree: Worktree):
        """Commit any uncommitted changes in a worktree."""
        # Check for changes
        result = self._run_git(["status", "--porcelain"], cwd=worktree.path)
        if not result.stdout.strip():
            return  # No changes

        # Stage and commit
        self._run_git(["add", "."], cwd=worktree.path)
        self._run_git([
            "commit", "-m",
            f"[lion] {worktree.subtask_title}\n\n{worktree.subtask_description}"
        ], cwd=worktree.path)

    def remove(self, worktree: Worktree, force: bool = False) -> bool:
        """Remove a worktree and optionally its branch.

        Args:
            worktree: The worktree to remove
            force: Force removal even if there are uncommitted changes

        Returns:
            True if removal succeeds
        """
        if not os.path.exists(worktree.path):
            # Already removed
            self.worktrees = [wt for wt in self.worktrees if wt.path != worktree.path]
            return True

        # Remove the worktree
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(worktree.path)

        result = self._run_git(args)

        if result.returncode != 0:
            if force or "untracked" not in result.stderr.lower():
                worktree.error = result.stderr or result.stdout
                Display.step_error("worktree", f"[{worktree.name}] Remove failed: {worktree.error[:200]}")
                return False

            # Try with force
            result = self._run_git(["worktree", "remove", "--force", worktree.path])
            if result.returncode != 0:
                worktree.error = result.stderr or result.stdout
                return False

        # Optionally delete the branch if merged
        if worktree.merged:
            self._run_git(["branch", "-d", worktree.branch])

        self.worktrees = [wt for wt in self.worktrees if wt.path != worktree.path]

        Display.notify(f"[{worktree.name}] Worktree removed")
        self._log(
            "worktree_removed",
            f"Removed worktree {worktree.path}",
            {"branch": worktree.branch, "merged": worktree.merged},
        )

        return True

    def cleanup_all(self, force: bool = False):
        """Remove all worktrees managed by this instance.

        Args:
            force: Force removal even with uncommitted changes
        """
        for worktree in list(self.worktrees):
            self.remove(worktree, force=force)

        # Clean up base directory if it's a temp dir and empty
        if self.base_dir.startswith(tempfile.gettempdir()):
            try:
                if os.path.exists(self.base_dir) and not os.listdir(self.base_dir):
                    os.rmdir(self.base_dir)
            except OSError:
                pass

        # Prune stale worktrees
        self._run_git(["worktree", "prune"])

        Display.notify("All worktrees cleaned up")
        self._log("cleanup_complete", "All worktrees removed")

    def get_status(self, check_paths: bool = False, include_details: bool = True) -> dict:
        """Get status summary of all worktrees.

        Args:
            check_paths: If True, verify each worktree path exists on disk.
                         Default False to avoid O(n) filesystem stat calls
                         when status is polled frequently.
            include_details: If True, include per-worktree details dict.
                             Default True. Set False when only counters are
                             needed to avoid O(n) dict allocation overhead.
        """
        # Single pass through worktrees to collect all metrics and details
        active = 0
        completed = 0
        tests_passed = 0
        merged = 0
        errors = 0
        worktree_details = [] if include_details else None

        for wt in self.worktrees:
            # Only check filesystem when explicitly requested
            if check_paths:
                if os.path.exists(wt.path):
                    active += 1
            else:
                # Assume active if not removed (tracked via list membership)
                if not wt.merged or wt.error:
                    active += 1
            if wt.completed:
                completed += 1
            if wt.tests_passed:
                tests_passed += 1
            if wt.merged:
                merged += 1
            if wt.error:
                errors += 1

            # Build details in same pass to avoid double iteration
            if include_details:
                worktree_details.append({
                    "name": wt.name,
                    "title": wt.subtask_title,
                    "path": wt.path,
                    "branch": wt.branch,
                    "completed": wt.completed,
                    "tests_passed": wt.tests_passed,
                    "merged": wt.merged,
                    "error": wt.error,
                })

        result = {
            "total": len(self.worktrees),
            "active": active,
            "completed": completed,
            "tests_passed": tests_passed,
            "merged": merged,
            "errors": errors,
        }

        if include_details:
            result["worktrees"] = worktree_details

        return result


class ConflictResolver:
    """Resolves merge conflicts using an LLM agent.

    When merge conflicts occur, this class formats the conflict information
    and uses an LLM to generate a resolution.

    Note: No caching is used because conflict state can change between
    resolution attempts (manual edits, partial fixes). Always reads fresh
    conflict content to ensure correct resolutions.
    """

    RESOLVE_PROMPT = """You are resolving a git merge conflict.

CONTEXT:
Branch being merged: {branch}
Task: {task_title}

CONFLICTED FILES:
{conflict_info}

CONFLICT MARKERS:
{conflict_content}

INSTRUCTIONS:
1. Analyze both versions of the code
2. Determine the intent of each change
3. Produce a merged version that:
   - Preserves functionality from both branches where possible
   - Resolves conflicts logically
   - Maintains code consistency
4. Output ONLY the resolved code, no explanations

If you cannot resolve the conflict safely, output exactly: CANNOT_RESOLVE
"""

    def __init__(self, provider, cwd: str, memory: SharedMemory | None = None):
        """Initialize the conflict resolver.

        Args:
            provider: LLM provider for generating resolutions
            cwd: Working directory (main repo)
            memory: SharedMemory for logging
        """
        self.provider = provider
        self.cwd = cwd
        self.memory = memory

    def resolve(
        self,
        conflict_info: str,
        task_title: str,
        conflict_content: str | None = None,
    ) -> str | None:
        """Attempt to resolve a merge conflict.

        Args:
            conflict_info: Description of the conflict (file names, etc.)
            task_title: Title of the subtask being merged
            conflict_content: Pre-fetched conflict content. If None, fetches
                              fresh content. Callers can pass cached content
                              for retry loops where conflict state hasn't
                              changed, avoiding repeated git/file I/O.

        Returns:
            Resolution instructions or None if cannot resolve
        """
        # Use provided content or fetch fresh
        if conflict_content is None:
            conflict_content = self._get_conflict_content()

        if not conflict_content:
            return None

        prompt = self.RESOLVE_PROMPT.format(
            branch=task_title,
            task_title=task_title,
            conflict_info=conflict_info,
            conflict_content=conflict_content[:10000],
        )

        result = self.provider.ask(prompt, "", self.cwd)

        if not result.success:
            return None

        content = result.content.strip()

        if "CANNOT_RESOLVE" in content:
            return None

        # Log resolution attempt
        if self.memory:
            self.memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="worktree",
                agent="conflict_resolver",
                type="conflict_resolved",
                content=f"Resolved conflict for {task_title}",
                metadata={"conflict_info": conflict_info[:500]},
            ))

        return content

    def _get_conflict_content(self) -> str:
        """Get the content of conflicted files with markers."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return ""

        files = result.stdout.strip().split("\n")
        content_parts = []
        max_chars_per_file = 3000

        for file_path in files[:5]:  # Limit to first 5 files
            full_path = os.path.join(self.cwd, file_path)
            if os.path.exists(full_path):
                try:
                    # Read only the first N chars to avoid memory spikes on large files
                    with open(full_path) as f:
                        content = f.read(max_chars_per_file)
                    content_parts.append(f"=== {file_path} ===\n{content}")
                except Exception:
                    pass

        return "\n\n".join(content_parts)
