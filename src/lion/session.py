"""Session history management for Lion pipelines.

Tracks pipeline execution with git commit hashes at each step, enabling
time-travel debugging, resume capabilities, and session replay.

Sessions are stored as individual files in ~/.lion/sessions/:
- session_<id>.json: Metadata (prompt, pipeline, status, timestamps)
- session_<id>.jsonl: Step data in append-only format for fast writes

Design principles:
- NO INDEX FILE: Direct file scanning avoids single point of failure
- JSONL for steps: Append-only writes avoid rewriting entire file
- Atomic writes: Use temp file + fsync + rename to prevent corruption
- Per-session file locking: Lock individual session files, not global
- Stable IDs: Sessions have short stable IDs (not position-based)
- Dedicated branches: Auto-commits go to lion/sessions/<id> branch
- Auto-cleanup: Configurable session retention with pruning
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Generator

logger = logging.getLogger(__name__)


# Maximum files to scan during session listing (for performance)
MAX_SESSION_SCAN = 500

# Default session retention
DEFAULT_MAX_SESSIONS = 100
DEFAULT_MAX_AGE_DAYS = 30

# Characters invalid in filenames across platforms (Windows is most restrictive)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_for_filename(text: str, max_length: int = 30) -> str:
    """Sanitize text for safe use in filenames across all platforms.

    Removes/replaces characters that are invalid on Windows, macOS, or Linux.
    Also handles edge cases like trailing dots/spaces (Windows) and
    reserved names.

    Args:
        text: Input text to sanitize
        max_length: Maximum length of output string

    Returns:
        Safe filename-compatible string
    """
    # Replace invalid characters with underscore
    sanitized = INVALID_FILENAME_CHARS.sub("_", text)
    # Replace sequences of whitespace with single underscore
    sanitized = re.sub(r"\s+", "_", sanitized)
    # Remove consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Strip leading/trailing underscores and dots (Windows issue)
    sanitized = sanitized.strip("_. ")
    # Truncate
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip("_. ")
    # If empty after sanitization, return a placeholder
    return sanitized or "session"


def _generate_short_id() -> str:
    """Generate a short, human-readable session ID.

    Format: 8 hex chars from UUID4, providing ~4 billion unique IDs.
    This is stable (won't change like position-based numbering) and
    easy to type/reference.

    Returns:
        8-character hex string like "a1b2c3d4"
    """
    return uuid.uuid4().hex[:8]


# Cross-platform file locking
if sys.platform == "win32":
    import msvcrt

    def _lock_file(f, exclusive: bool = True) -> None:
        """Acquire file lock (Windows)."""
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK if exclusive else msvcrt.LK_LOCK, 1)

    def _unlock_file(f) -> None:
        """Release file lock (Windows)."""
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_file(f, exclusive: bool = True) -> None:
        """Acquire file lock (Unix)."""
        fcntl.flock(f.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    def _unlock_file(f) -> None:
        """Release file lock (Unix)."""
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, data: dict, sync_directory: bool = False) -> None:
    """Write JSON atomically using temp file + fsync + rename.

    This prevents corruption from partial writes or crashes.
    Uses fsync to ensure durability before rename.

    Args:
        path: Target file path
        data: Dictionary to serialize as JSON
        sync_directory: If True, also fsync the directory after rename.
                       This adds latency (10-100ms on some systems) but
                       ensures durability across power loss. For session
                       metadata, this is usually overkill. Default: False.
    """
    # Write to temp file in same directory (for same-filesystem rename)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}_",
        suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename
        os.replace(tmp_path, path)
        # Optionally sync directory to ensure rename is durable (Unix only)
        # Windows doesn't support O_DIRECTORY, but also doesn't need it
        # as NTFS provides strong rename guarantees
        if sync_directory and sys.platform != "win32":
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (OSError, AttributeError):
                pass  # Best-effort; some filesystems don't support this
    except Exception:
        # Clean up temp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _append_jsonl(path: Path, data: dict) -> None:
    """Append a JSON line to a JSONL file atomically.

    For step data, this is much faster than rewriting the entire file.
    Uses append mode which is atomic on POSIX systems.

    Args:
        path: Target JSONL file path
        data: Dictionary to serialize as a JSON line
    """
    line = json.dumps(data) + "\n"
    with open(path, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _read_jsonl(path: Path) -> list[dict]:
    """Read all lines from a JSONL file.

    Args:
        path: JSONL file path

    Returns:
        List of parsed dictionaries
    """
    if not path.exists():
        return []

    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping corrupted JSONL line in %s", path)
                    continue
    return results


class StepStatus(str, Enum):
    """Status of a pipeline step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SessionStatus(str, Enum):
    """Status of a pipeline session."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class SessionStep:
    """A single step in a pipeline session.

    Attributes:
        step_number: 1-based index of this step in the pipeline
        function_name: Name of the pipeline function (e.g., "pride", "impl")
        commit_hash: Git commit hash after this step completed
        status: Step completion status (use StepStatus enum values)
        started_at: Unix timestamp when step started
        completed_at: Unix timestamp when step completed (None if not finished)
        error: Error message if step failed
        files_changed: List of files modified by this step
        tokens_used: Number of tokens consumed by this step
    """
    step_number: int
    function_name: str
    commit_hash: Optional[str] = None
    status: str = StepStatus.PENDING.value
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    files_changed: list[str] = field(default_factory=list)
    tokens_used: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStep":
        """Create from dictionary."""
        return cls(**data)

    @property
    def duration(self) -> Optional[float]:
        """Get step duration in seconds."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


@dataclass
class Session:
    """A pipeline execution session with step tracking.

    Attributes:
        session_id: Unique identifier for this session (stable, short hash)
        short_id: 8-char stable identifier for CLI reference
        prompt: The original prompt that started the pipeline
        pipeline: String representation of the pipeline (e.g., "pride(3) -> impl()")
        cwd: Working directory where the session was executed
        started_at: Unix timestamp when session started
        completed_at: Unix timestamp when session completed (None if not finished)
        status: Overall session status (use SessionStatus enum values)
        steps: List of pipeline steps with their commit hashes
        base_commit: Git commit hash at the start of the session
        session_branch: Dedicated git branch for this session's commits
        total_tokens: Total tokens used across all steps
        error: Error message if session failed
    """
    session_id: str
    prompt: str
    pipeline: str
    cwd: str
    started_at: float
    short_id: str = ""  # 8-char stable ID for CLI
    completed_at: Optional[float] = None
    status: str = SessionStatus.RUNNING.value
    steps: list[SessionStep] = field(default_factory=list)
    base_commit: Optional[str] = None
    session_branch: Optional[str] = None  # Dedicated branch for commits
    total_tokens: int = 0
    error: Optional[str] = None

    def __post_init__(self):
        """Generate short_id from session_id if not set."""
        if not self.short_id:
            # Extract the UUID portion from session_id for stable reference
            # session_id format: YYYYMMDD_HHMMSS_<uuid8>_<prompt-slug>
            parts = self.session_id.split("_")
            if len(parts) >= 3:
                self.short_id = parts[2]  # The UUID portion
            else:
                self.short_id = _generate_short_id()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization.

        Note: Steps are stored separately in JSONL format, not in this dict.
        """
        data = {
            "session_id": self.session_id,
            "short_id": self.short_id,
            "prompt": self.prompt,
            "pipeline": self.pipeline,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "base_commit": self.base_commit,
            "session_branch": self.session_branch,
            "total_tokens": self.total_tokens,
            "error": self.error,
            # Store step count for quick listing without loading steps
            "step_count": len(self.steps),
        }
        return data

    @classmethod
    def from_dict(cls, data: dict, steps: Optional[list[SessionStep]] = None) -> "Session":
        """Create from dictionary.

        Args:
            data: Session metadata dictionary
            steps: Optional list of steps (loaded separately from JSONL)
        """
        # Remove step_count as it's computed, not stored
        data = dict(data)
        data.pop("step_count", None)
        data.pop("steps", None)  # Ignore legacy steps in JSON

        session = cls(**data)
        if steps:
            session.steps = steps
        return session

    @property
    def duration(self) -> Optional[float]:
        """Get session duration in seconds."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    def get_step(self, step_number: int) -> Optional[SessionStep]:
        """Get a step by its number (1-based)."""
        for step in self.steps:
            if step.step_number == step_number:
                return step
        return None

    def get_commit_at_step(self, step_number: int) -> Optional[str]:
        """Get the commit hash at a specific step."""
        step = self.get_step(step_number)
        return step.commit_hash if step else None


class SessionManager:
    """Manages session storage and retrieval.

    Sessions are stored as individual files in ~/.lion/sessions/:
    - session_<id>.json: Metadata only (small, fast to read)
    - session_<id>.jsonl: Step data (append-only for fast writes)

    NO INDEX FILE is used. Session listing scans metadata files directly.
    With <1000 sessions at ~1KB each, listing completes in <100ms.

    Session identification:
    - Each session has a stable 8-char short_id (e.g., "a1b2c3d4")
    - Users can reference sessions by short_id OR by recency number
    - Recency numbers are computed dynamically, not stored

    Git integration:
    - Auto-commits go to dedicated branches: lion/sessions/<short_id>
    - This avoids polluting main branch history
    - Branches can be squashed/deleted after session ends
    """

    DEFAULT_SESSIONS_DIR = Path.home() / ".lion" / "sessions"
    MAX_SESSIONS = DEFAULT_MAX_SESSIONS

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        auto_commit: bool = False,
        sync_directory: bool = False,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ):
        """Initialize the session manager.

        Args:
            sessions_dir: Directory for session storage (default: ~/.lion/sessions/)
            auto_commit: If True, auto-commit git changes after each step.
                        Commits go to dedicated branch lion/sessions/<id>.
                        Default False to avoid any git overhead.
            sync_directory: If True, fsync directory after writes for extra
                          durability. Adds latency. Default False.
            max_sessions: Maximum sessions to retain. Default 100.
            max_age_days: Maximum age of sessions in days. Default 30.
        """
        self.sessions_dir = Path(sessions_dir) if sessions_dir else self.DEFAULT_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.auto_commit = auto_commit
        self.sync_directory = sync_directory
        self.max_sessions = max_sessions
        self.max_age_days = max_age_days

    def _get_session_metadata_path(self, session_id: str) -> Path:
        """Get the path to a session metadata file."""
        return self.sessions_dir / f"session_{session_id}.json"

    def _get_session_steps_path(self, session_id: str) -> Path:
        """Get the path to a session steps file (JSONL)."""
        return self.sessions_dir / f"session_{session_id}.jsonl"

    def _get_lock_path(self, session_id: str) -> Path:
        """Get the path to a session lock file."""
        return self.sessions_dir / f".session_{session_id}.lock"

    @contextmanager
    def _session_lock(self, session_id: str) -> Generator[None, None, None]:
        """Context manager for per-session file locking.

        Each session has its own lock file to allow concurrent access
        to different sessions without blocking.
        """
        lock_path = self._get_lock_path(session_id)
        lock_path.touch(exist_ok=True)
        with open(lock_path, "r+") as lock_file:
            _lock_file(lock_file, exclusive=True)
            try:
                yield
            finally:
                _unlock_file(lock_file)

    def _scan_sessions(self, limit: Optional[int] = None) -> list[dict]:
        """Scan session metadata files directly (no index).

        This replaces the index-based approach. Direct scanning is fast:
        - 1000 files at ~1KB each: <100ms on SSD
        - Sorted by mtime descending (most recent first)

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session metadata dicts, sorted by started_at descending
        """
        sessions = []
        max_to_scan = min(limit or MAX_SESSION_SCAN, MAX_SESSION_SCAN)

        # Get all metadata files with their mtimes for sorting
        metadata_files = []
        for path in self.sessions_dir.glob("session_*.json"):
            if path.name.endswith(".jsonl"):
                continue
            try:
                mtime = path.stat().st_mtime
                metadata_files.append((path, mtime))
            except OSError:
                continue

        # Sort by mtime descending and take limit
        metadata_files.sort(key=lambda x: x[1], reverse=True)
        metadata_files = metadata_files[:max_to_scan]

        # Load metadata from each file
        for path, _ in metadata_files:
            try:
                with open(path) as f:
                    data = json.load(f)
                sessions.append(data)
            except (json.JSONDecodeError, IOError, KeyError, TypeError):
                logger.warning("Skipping corrupted session file: %s", path)
                continue

        # Sort by started_at descending (most recent first)
        sessions.sort(key=lambda s: s.get("started_at", 0), reverse=True)

        if limit:
            sessions = sessions[:limit]

        return sessions

    def create_session(
        self,
        prompt: str,
        pipeline: str,
        cwd: str,
        base_commit: Optional[str] = None,
    ) -> Session:
        """Create a new session.

        Args:
            prompt: The original prompt
            pipeline: String representation of the pipeline
            cwd: Working directory
            base_commit: Git commit hash at session start

        Returns:
            The new Session object
        """
        # Generate session ID with stable short_id
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = _generate_short_id()
        prompt_slug = _sanitize_for_filename(prompt)
        session_id = f"{timestamp}_{short_id}_{prompt_slug}"

        # Generate dedicated branch name for this session's commits
        session_branch = f"lion/sessions/{short_id}" if self.auto_commit else None

        session = Session(
            session_id=session_id,
            short_id=short_id,
            prompt=prompt,
            pipeline=pipeline,
            cwd=cwd,
            started_at=time.time(),
            base_commit=base_commit,
            session_branch=session_branch,
        )

        # Write metadata file (no lock needed - new file)
        metadata_path = self._get_session_metadata_path(session_id)
        _atomic_write_json(metadata_path, session.to_dict(), sync_directory=self.sync_directory)

        # Create empty steps file
        steps_path = self._get_session_steps_path(session_id)
        steps_path.touch()

        # Create session branch if auto-commit is enabled
        if self.auto_commit and base_commit:
            self._create_session_branch(session, cwd)

        return session

    def _create_session_branch(self, session: Session, cwd: str) -> bool:
        """Create a dedicated branch for this session's commits.

        Args:
            session: Session object with session_branch set
            cwd: Working directory

        Returns:
            True if branch was created successfully
        """
        if not session.session_branch or not session.base_commit:
            return False

        try:
            # Create branch from base commit
            result = subprocess.run(
                ["git", "checkout", "-b", session.session_branch, session.base_commit],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning(
                    "Failed to create session branch %s: %s",
                    session.session_branch, result.stderr
                )
                return False
            return True
        except Exception as e:
            logger.warning("Failed to create session branch: %s", e)
            return False

    def save_session(self, session: Session) -> None:
        """Save session metadata to disk.

        Note: Steps are saved separately via record_step_* methods.

        Args:
            session: The session to save
        """
        with self._session_lock(session.session_id):
            metadata_path = self._get_session_metadata_path(session.session_id)
            _atomic_write_json(metadata_path, session.to_dict(), sync_directory=self.sync_directory)

    def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session by ID.

        Args:
            session_id: The session identifier (full or short)

        Returns:
            The Session object or None if not found
        """
        # Try full ID first
        metadata_path = self._get_session_metadata_path(session_id)
        if not metadata_path.exists():
            # Try to find by short ID
            session_id = self._resolve_short_id(session_id)
            if not session_id:
                return None
            metadata_path = self._get_session_metadata_path(session_id)

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path) as f:
                data = json.load(f)

            # Load steps from JSONL
            steps_path = self._get_session_steps_path(session_id)
            steps_data = _read_jsonl(steps_path)
            steps = [SessionStep.from_dict(s) for s in steps_data]

            return Session.from_dict(data, steps=steps)
        except (json.JSONDecodeError, IOError, KeyError, TypeError) as e:
            logger.warning("Failed to load session %s: %s", session_id, e)
            return None

    def _resolve_short_id(self, short_id: str) -> Optional[str]:
        """Resolve a short ID to full session ID.

        Args:
            short_id: 8-char short ID

        Returns:
            Full session_id or None if not found
        """
        if len(short_id) > 8:
            return None  # Already a full ID

        # Scan for matching session
        for path in self.sessions_dir.glob("session_*.json"):
            if path.name.endswith(".jsonl"):
                continue
            try:
                with open(path) as f:
                    data = json.load(f)
                if data.get("short_id") == short_id:
                    return data.get("session_id")
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def get_session_by_number(self, number: int) -> Optional[Session]:
        """Get a session by its recency number (1 = most recent).

        Note: Recency numbers are computed dynamically from file mtimes,
        not stored. This means the number for a given session may change
        as new sessions are created.

        Args:
            number: 1-based recency index

        Returns:
            The Session object or None if not found
        """
        sessions = self._scan_sessions(limit=number + 1)

        if number < 1 or number > len(sessions):
            return None

        session_id = sessions[number - 1].get("session_id")
        if not session_id:
            return None

        return self.load_session(session_id)

    def get_session_by_short_id(self, short_id: str) -> Optional[Session]:
        """Get a session by its stable short ID.

        This is the preferred way to reference sessions as short_id
        doesn't change (unlike recency numbers).

        Args:
            short_id: 8-character hex identifier

        Returns:
            The Session object or None if not found
        """
        session_id = self._resolve_short_id(short_id)
        if session_id:
            return self.load_session(session_id)
        return None

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """List recent sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session info dicts, sorted by recency
        """
        return self._scan_sessions(limit=limit)

    def record_step_start(
        self,
        session: Session,
        step_number: int,
        function_name: str,
        persist: bool = False,
    ) -> SessionStep:
        """Record the start of a pipeline step.

        Updates the in-memory session. Only persists to disk if persist=True.
        For performance, callers should batch persistence by only persisting
        on step completion or session completion.

        Args:
            session: The session to update
            step_number: 1-based step number
            function_name: Name of the pipeline function
            persist: If True, immediately save to disk

        Returns:
            The new SessionStep
        """
        step = SessionStep(
            step_number=step_number,
            function_name=function_name,
            status=StepStatus.RUNNING.value,
            started_at=time.time(),
        )
        session.steps.append(step)
        if persist:
            # Append step to JSONL file
            steps_path = self._get_session_steps_path(session.session_id)
            _append_jsonl(steps_path, step.to_dict())
        return step

    def record_step_complete(
        self,
        session: Session,
        step_number: int,
        commit_hash: Optional[str] = None,
        files_changed: Optional[list[str]] = None,
        tokens_used: int = 0,
        persist: bool = True,
    ) -> None:
        """Record the completion of a pipeline step.

        Args:
            session: The session to update
            step_number: 1-based step number
            commit_hash: Git commit hash after step completion
            files_changed: List of files modified
            tokens_used: Number of tokens consumed
            persist: If True, immediately save to disk (default: True for durability)
        """
        step = session.get_step(step_number)
        if step:
            step.status = StepStatus.COMPLETED.value
            step.completed_at = time.time()
            step.commit_hash = commit_hash
            step.files_changed = files_changed or []
            step.tokens_used = tokens_used
            session.total_tokens += tokens_used

        if persist:
            # Append completed step to JSONL (updates are appended, last wins)
            steps_path = self._get_session_steps_path(session.session_id)
            _append_jsonl(steps_path, step.to_dict())

    def record_step_failed(
        self,
        session: Session,
        step_number: int,
        error: str,
        persist: bool = True,
    ) -> None:
        """Record a step failure.

        Args:
            session: The session to update
            step_number: 1-based step number
            error: Error message
            persist: If True, immediately save to disk (default: True for durability)
        """
        step = session.get_step(step_number)
        if step:
            step.status = StepStatus.FAILED.value
            step.completed_at = time.time()
            step.error = error

        if persist:
            steps_path = self._get_session_steps_path(session.session_id)
            _append_jsonl(steps_path, step.to_dict())

    def complete_session(
        self,
        session: Session,
        success: bool = True,
        error: Optional[str] = None,
        squash_commits: bool = False,
    ) -> None:
        """Mark a session as complete.

        Args:
            session: The session to complete
            success: Whether the session completed successfully
            error: Error message if failed
            squash_commits: If True and auto_commit was enabled, squash the
                           session branch commits into a single commit
        """
        session.status = SessionStatus.COMPLETED.value if success else SessionStatus.FAILED.value
        session.completed_at = time.time()
        session.error = error

        # Save metadata
        with self._session_lock(session.session_id):
            metadata_path = self._get_session_metadata_path(session.session_id)
            _atomic_write_json(metadata_path, session.to_dict(), sync_directory=self.sync_directory)

        # Optionally squash session branch commits
        if squash_commits and session.session_branch and session.base_commit:
            self._squash_session_commits(session)

    def _squash_session_commits(self, session: Session) -> bool:
        """Squash all commits on session branch into one.

        Args:
            session: Session with session_branch and base_commit

        Returns:
            True if squash was successful
        """
        if not session.session_branch or not session.base_commit:
            return False

        try:
            # Soft reset to base commit, keeping changes staged
            result = subprocess.run(
                ["git", "reset", "--soft", session.base_commit],
                cwd=session.cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("Failed to reset for squash: %s", result.stderr)
                return False

            # Create squashed commit
            commit_msg = f"[lion] {session.prompt[:50]}\n\nPipeline: {session.pipeline}"
            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=session.cwd,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("Failed to create squash commit: %s", result.stderr)
                return False

            return True
        except Exception as e:
            logger.warning("Failed to squash session commits: %s", e)
            return False

    def interrupt_session(self, session: Session) -> None:
        """Mark a session as interrupted.

        Args:
            session: The session that was interrupted
        """
        session.status = SessionStatus.INTERRUPTED.value
        session.completed_at = time.time()

        with self._session_lock(session.session_id):
            metadata_path = self._get_session_metadata_path(session.session_id)
            _atomic_write_json(metadata_path, session.to_dict(), sync_directory=self.sync_directory)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session to delete (full or short ID)

        Returns:
            True if deleted, False if not found
        """
        # Resolve short ID if needed
        if len(session_id) <= 8:
            resolved = self._resolve_short_id(session_id)
            if resolved:
                session_id = resolved
            else:
                return False

        metadata_path = self._get_session_metadata_path(session_id)
        steps_path = self._get_session_steps_path(session_id)
        lock_path = self._get_lock_path(session_id)

        if not metadata_path.exists():
            return False

        # Delete files
        with self._session_lock(session_id):
            try:
                if metadata_path.exists():
                    metadata_path.unlink()
                if steps_path.exists():
                    steps_path.unlink()
            except OSError as e:
                logger.warning("Failed to delete session files: %s", e)
                return False

        # Clean up lock file
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass

        return True

    def prune_sessions(
        self,
        max_sessions: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> int:
        """Remove old sessions based on count and age limits.

        Args:
            max_sessions: Maximum sessions to keep (default: self.max_sessions)
            max_age_days: Maximum age in days (default: self.max_age_days)

        Returns:
            Number of sessions removed
        """
        max_sessions = max_sessions if max_sessions is not None else self.max_sessions
        max_age_days = max_age_days if max_age_days is not None else self.max_age_days

        # Get all sessions sorted by recency
        all_sessions = self._scan_sessions(limit=MAX_SESSION_SCAN)

        removed = 0
        now = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60

        for i, sess_info in enumerate(all_sessions):
            should_remove = False

            # Check count limit (keep first max_sessions)
            if i >= max_sessions:
                should_remove = True

            # Check age limit
            started_at = sess_info.get("started_at", 0)
            if now - started_at > max_age_seconds:
                should_remove = True

            if should_remove:
                session_id = sess_info.get("session_id")
                if session_id and self.delete_session(session_id):
                    removed += 1

        return removed

    def get_session_for_replay(self, session_id: str) -> Optional[dict]:
        """Get session data formatted for replay display.

        Args:
            session_id: The session to replay (full or short ID)

        Returns:
            Formatted session data for display
        """
        session = self.load_session(session_id)
        if not session:
            return None

        return {
            "session_id": session.session_id,
            "short_id": session.short_id,
            "prompt": session.prompt,
            "pipeline": session.pipeline,
            "cwd": session.cwd,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "duration": session.duration,
            "status": session.status,
            "base_commit": session.base_commit,
            "session_branch": session.session_branch,
            "total_tokens": session.total_tokens,
            "steps": [
                {
                    "step_number": step.step_number,
                    "function_name": step.function_name,
                    "commit_hash": step.commit_hash,
                    "status": step.status,
                    "duration": step.duration,
                    "files_changed": step.files_changed,
                    "tokens_used": step.tokens_used,
                    "error": step.error,
                }
                for step in session.steps
            ],
        }
