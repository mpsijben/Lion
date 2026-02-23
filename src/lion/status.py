"""Status dashboard for Lion - quota tracking, session history, and active pipelines.

Provides:
- QuotaTracker: Track and persist token usage per model with daily limits
- SessionScanner: Parse JSONL run history to extract usage statistics
- ActivePipelineTracker: Detect running pipelines via PID files
- StatusDashboard: Aggregate all status information for display

Usage:
    from lion.status import StatusDashboard

    dashboard = StatusDashboard(config, runs_dir=Path("~/.lion/runs"))
    status = dashboard.get_status()
    dashboard.render()  # Rich-based terminal output
"""

import atexit
import json
import os
import platform
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Generator

# Cross-platform file locking
# On Unix/macOS, use fcntl; on Windows, use msvcrt
_PLATFORM = platform.system().lower()

if _PLATFORM == "windows":
    import msvcrt

    @contextmanager
    def _file_lock_shared(file_handle) -> Generator[None, None, None]:
        """Acquire a shared (read) lock on a file handle (Windows)."""
        try:
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            yield
        finally:
            try:
                file_handle.seek(0)
                msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

    @contextmanager
    def _file_lock_exclusive(file_handle) -> Generator[None, None, None]:
        """Acquire an exclusive (write) lock on a file handle (Windows)."""
        try:
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            yield
        finally:
            try:
                file_handle.seek(0)
                msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
else:
    import fcntl

    @contextmanager
    def _file_lock_shared(file_handle) -> Generator[None, None, None]:
        """Acquire a shared (read) lock on a file handle (Unix/macOS)."""
        try:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_SH)
            yield
        finally:
            try:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass

    @contextmanager
    def _file_lock_exclusive(file_handle) -> Generator[None, None, None]:
        """Acquire an exclusive (write) lock on a file handle (Unix/macOS)."""
        try:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass

# Rich is optional - graceful degradation if not available
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


@dataclass
class ModelUsage:
    """Token usage for a single model."""
    model: str
    tokens_used: int = 0
    daily_limit: int = 0
    requests: int = 0

    @property
    def usage_percent(self) -> float:
        """Return usage as percentage (0-100)."""
        if self.daily_limit <= 0:
            return 0.0
        return min(100.0, (self.tokens_used / self.daily_limit) * 100)

    @property
    def is_over_limit(self) -> bool:
        """Check if usage exceeds daily limit."""
        return self.daily_limit > 0 and self.tokens_used > self.daily_limit


@dataclass
class SessionInfo:
    """Information about a single run session."""
    run_id: str
    timestamp: float
    prompt: str
    steps_completed: int = 0
    total_steps: int = 0
    tokens_used: int = 0
    tokens_available: bool = False  # Whether token data was found in the run
    duration: float = 0.0
    success: bool = True
    models_used: list[str] = field(default_factory=list)

    @property
    def datetime(self) -> datetime:
        """Return timestamp as datetime."""
        return datetime.fromtimestamp(self.timestamp)


@dataclass
class ActivePipeline:
    """Information about a running pipeline."""
    pid: int
    run_id: str
    prompt: str
    started_at: float
    current_step: Optional[str] = None

    @property
    def elapsed(self) -> float:
        """Return elapsed time in seconds."""
        return time.time() - self.started_at


@dataclass
class StatusReport:
    """Aggregated status report from all trackers."""
    quota_usage: dict[str, ModelUsage]
    todays_sessions: list[SessionInfo]
    active_pipelines: list[ActivePipeline]
    total_tokens_today: int = 0
    total_sessions_today: int = 0
    quota_warnings: list[str] = field(default_factory=list)


class QuotaTracker:
    """Track and persist token usage per model with daily reset.

    Stores usage data in ~/.lion/quota.json with the format:
    {
        "date": "2024-01-15",
        "usage": {
            "claude": {"tokens": 50000, "requests": 25},
            "gemini": {"tokens": 30000, "requests": 15}
        }
    }

    IMPORTANT LIMITATIONS:
    ----------------------
    1. Per-machine tracking: Quota data is stored locally in ~/.lion/quota.json.
       If you use Lion from multiple machines (laptop, desktop, CI), each
       machine tracks usage separately. There is no centralized tracking.

    2. Concurrent access: Uses file locking (fcntl on Unix, msvcrt on Windows)
       to handle concurrent updates from multiple Lion processes on the same
       machine. However, this does not help with cross-machine scenarios.

    3. Best-effort accuracy: Token counts are approximations based on what
       providers report. Actual API billing may differ slightly.

    4. Daily reset: Usage resets at midnight local time. The reset is based
       on the local system clock, not a consistent timezone.

    For accurate billing tracking, always refer to your provider's dashboard.
    This quota tracking is intended for approximate usage awareness, not
    precise billing reconciliation.
    """

    def __init__(self, config: dict, quota_file: Optional[Path] = None):
        """Initialize the quota tracker.

        Args:
            config: Lion configuration dict, expects [quota] section
            quota_file: Path to quota.json. If None, uses ~/.lion/quota.json
        """
        self._config = config
        self._quota_config = config.get("quota", {})
        self._enabled = self._quota_config.get("enabled", True)
        self._daily_limits = self._quota_config.get("daily_limits", {})
        self._warn_threshold = self._quota_config.get("warn_threshold", 0.8)

        # Set up quota file path
        if quota_file:
            self._quota_file = quota_file
        else:
            lion_dir = Path.home() / ".lion"
            lion_dir.mkdir(exist_ok=True)
            self._quota_file = lion_dir / "quota.json"

        # Load current usage
        self._usage: dict[str, dict] = {}
        self._date: str = ""
        self._load()

    def _load(self) -> None:
        """Load quota data from file, resetting if date changed."""
        today = date.today().isoformat()

        if self._quota_file.exists():
            try:
                with open(self._quota_file) as f:
                    # Shared lock for reading
                    with _file_lock_shared(f):
                        data = json.load(f)

                # Check if it's a new day - reset if so
                if data.get("date") == today:
                    self._usage = data.get("usage", {})
                    self._date = today
                    return
            except (json.JSONDecodeError, OSError):
                pass

        # Reset for new day or on error
        self._usage = {}
        self._date = today
        self._save_locked()

    def _save_locked(self) -> None:
        """Save quota data to file with atomic write."""
        data = {
            "date": self._date,
            "usage": self._usage,
        }
        temp_path = None
        try:
            # Write to temp file then rename for atomicity
            parent_dir = self._quota_file.parent
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=parent_dir,
                prefix='.quota_',
                suffix='.tmp',
                delete=False
            ) as f:
                json.dump(data, f, indent=2)
                temp_path = f.name

            # Atomic rename
            os.rename(temp_path, self._quota_file)
        except OSError:
            # Clean up temp file on failure if it was created
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def record_usage(self, model: str, tokens: int) -> bool:
        """Record token usage for a model.

        Uses file locking to ensure atomic read-modify-write across
        concurrent Lion processes.

        Args:
            model: Model name (e.g., "claude", "gemini")
            tokens: Number of tokens used

        Returns:
            True if usage was recorded successfully, False if skipped due to
            lock acquisition failure (to preserve data integrity).
        """
        if not self._enabled:
            return True

        today = date.today().isoformat()

        # Use a lock file for coordinating concurrent updates
        lock_file = self._quota_file.parent / ".quota.lock"
        self._quota_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(lock_file, "w") as lock_f:
                # Exclusive lock for read-modify-write
                with _file_lock_exclusive(lock_f):
                    # Re-read current state under lock
                    if self._quota_file.exists():
                        try:
                            with open(self._quota_file) as f:
                                data = json.load(f)

                            # Check for day change
                            if data.get("date") == today:
                                self._usage = data.get("usage", {})
                            else:
                                self._usage = {}
                            self._date = today
                        except (json.JSONDecodeError, OSError):
                            self._usage = {}
                            self._date = today
                    else:
                        self._usage = {}
                        self._date = today

                    # Update usage
                    if model not in self._usage:
                        self._usage[model] = {"tokens": 0, "requests": 0}

                    self._usage[model]["tokens"] += tokens
                    self._usage[model]["requests"] += 1

                    # Save while still holding lock
                    self._save_locked()
                    return True
        except OSError:
            # Skip recording on lock failure to preserve data integrity
            # This is preferable to potentially losing updates from other processes
            return False

    def get_usage(self, model: str) -> ModelUsage:
        """Get usage statistics for a model.

        Args:
            model: Model name

        Returns:
            ModelUsage with current usage and limits
        """
        usage_data = self._usage.get(model, {"tokens": 0, "requests": 0})
        daily_limit = self._daily_limits.get(model, 0)

        return ModelUsage(
            model=model,
            tokens_used=usage_data["tokens"],
            daily_limit=daily_limit,
            requests=usage_data["requests"],
        )

    def get_all_usage(self) -> dict[str, ModelUsage]:
        """Get usage for all tracked models.

        Returns:
            Dict mapping model name to ModelUsage
        """
        # Include all models that have limits OR have been used
        all_models = set(self._daily_limits.keys()) | set(self._usage.keys())

        return {model: self.get_usage(model) for model in all_models}

    def get_warnings(self) -> list[str]:
        """Get quota warnings for models approaching/exceeding limits.

        Returns:
            List of warning messages
        """
        warnings = []

        for model, usage in self.get_all_usage().items():
            if usage.daily_limit <= 0:
                continue

            if usage.is_over_limit:
                warnings.append(
                    f"{model}: Exceeded daily limit ({usage.tokens_used:,} / {usage.daily_limit:,} tokens)"
                )
            elif usage.usage_percent >= self._warn_threshold * 100:
                warnings.append(
                    f"{model}: Approaching daily limit ({usage.usage_percent:.0f}% used)"
                )

        return warnings

    def reset(self) -> bool:
        """Reset all usage counters (for testing or manual reset).

        Uses file locking to ensure atomic reset across concurrent processes.

        Returns:
            True if reset was successful, False if skipped due to lock failure.
        """
        lock_file = self._quota_file.parent / ".quota.lock"
        self._quota_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(lock_file, "w") as lock_f:
                with _file_lock_exclusive(lock_f):
                    self._usage = {}
                    self._date = date.today().isoformat()
                    self._save_locked()
                    return True
        except OSError:
            return False


class SessionScanner:
    """Scan JSONL run history to extract session statistics.

    Parses memory.jsonl files from ~/.lion/runs/ to gather:
    - Token usage per session
    - Models used
    - Success/failure status
    - Duration and step counts

    Uses streaming parsing to avoid loading entire files into memory.
    """

    # Maximum number of runs to scan (prevents unbounded work)
    MAX_RUNS_TO_SCAN = 100

    def __init__(self, runs_dir: Path):
        """Initialize the session scanner.

        Args:
            runs_dir: Path to the runs directory (e.g., ~/.lion/runs)
        """
        self._runs_dir = runs_dir

    def scan_today(self, limit: int = 50) -> list[SessionInfo]:
        """Scan for sessions from today.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of SessionInfo for today's sessions, sorted by timestamp (newest first)
        """
        today_start = datetime.combine(date.today(), datetime.min.time()).timestamp()
        return self._scan_since(today_start, limit=limit)

    def scan_recent(self, hours: int = 24, limit: int = 50) -> list[SessionInfo]:
        """Scan for recent sessions.

        Args:
            hours: Number of hours to look back
            limit: Maximum number of sessions to return

        Returns:
            List of SessionInfo for recent sessions, sorted by timestamp (newest first)
        """
        since = time.time() - (hours * 3600)
        return self._scan_since(since, limit=limit)

    def _scan_since(self, since_timestamp: float, limit: int = 50) -> list[SessionInfo]:
        """Scan for sessions since a given timestamp.

        Uses file mtime for initial filtering to avoid parsing old files.
        Limits the number of directories scanned for performance.

        Args:
            since_timestamp: Unix timestamp to scan from
            limit: Maximum number of sessions to return

        Returns:
            List of SessionInfo, sorted by timestamp (newest first)
        """
        if not self._runs_dir.exists():
            return []

        # Collect candidate directories with their mtimes for sorting
        candidates = []
        try:
            for run_dir in self._runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue

                memory_file = run_dir / "memory.jsonl"
                if not memory_file.exists():
                    continue

                try:
                    mtime = memory_file.stat().st_mtime
                    if mtime >= since_timestamp:
                        candidates.append((run_dir, mtime))
                except OSError:
                    continue
        except OSError:
            return []

        # Sort by mtime descending (newest first) and limit scan scope
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:self.MAX_RUNS_TO_SCAN]

        # Parse only the needed runs
        sessions = []
        for run_dir, _ in candidates:
            if len(sessions) >= limit:
                break

            session = self._parse_run_streaming(run_dir)
            if session:
                sessions.append(session)

        # Already sorted by mtime, but re-sort by actual timestamp for accuracy
        sessions.sort(key=lambda s: s.timestamp, reverse=True)
        return sessions[:limit]

    def _parse_run_streaming(self, run_dir: Path) -> Optional[SessionInfo]:
        """Parse a single run directory using streaming to minimize memory.

        Only keeps first entry, last entry, and aggregated stats in memory.

        Args:
            run_dir: Path to the run directory

        Returns:
            SessionInfo or None if parsing fails
        """
        memory_file = run_dir / "memory.jsonl"

        if not memory_file.exists():
            return None

        try:
            first_entry = None
            last_entry = None
            total_tokens = 0
            tokens_found = False  # Track whether we found any token data
            models_seen = set()
            has_errors = False
            steps_completed = 0
            entry_count = 0

            step_phases = {"implement", "propose", "critique", "converge", "review", "test"}

            with open(memory_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry_count += 1

                    # Keep first entry
                    if first_entry is None:
                        first_entry = entry

                    # Always update last entry (will end up with actual last)
                    last_entry = entry

                    # Aggregate stats without storing all entries
                    metadata = entry.get("metadata", {}) or {}
                    tokens_in_entry = metadata.get("tokens_used", 0)
                    if tokens_in_entry > 0:
                        tokens_found = True
                        total_tokens += tokens_in_entry

                    model = metadata.get("model")
                    if model:
                        models_seen.add(model)

                    if entry.get("type") == "error" or entry.get("phase") == "error":
                        has_errors = True

                    if entry.get("phase") in step_phases:
                        steps_completed += 1

            if first_entry is None:
                return None

            # Get prompt from first entry or metadata
            prompt = first_entry.get("content", "")[:100]
            if first_entry.get("metadata", {}).get("prompt"):
                prompt = first_entry["metadata"]["prompt"][:100]

            # Get timestamps
            first_ts = first_entry.get("timestamp", memory_file.stat().st_mtime)
            last_ts = last_entry.get("timestamp", first_ts) if last_entry else first_ts
            duration = last_ts - first_ts

            return SessionInfo(
                run_id=run_dir.name,
                timestamp=first_ts,
                prompt=prompt,
                steps_completed=steps_completed,
                total_steps=steps_completed,
                tokens_used=total_tokens,
                tokens_available=tokens_found,
                duration=duration,
                success=not has_errors,
                models_used=list(models_seen),
            )

        except OSError:
            return None


class ActivePipelineTracker:
    """Track running pipelines via PID files with heartbeat-based staleness detection.

    Looks for .lion/active/*.pid files that contain:
    {
        "pid": 12345,
        "run_id": "2024-01-15_120000_Build_feature",
        "prompt": "Build a new feature",
        "started_at": 1705329600.0,
        "current_step": "impl",
        "last_heartbeat": 1705329660.0
    }

    Staleness Detection:
    -------------------
    A pipeline is considered stale (and cleaned up) if:
    1. The process with the given PID is no longer running, OR
    2. The process is running but doesn't look like a Python/Lion process
       (handles PID wraparound), OR
    3. The last_heartbeat is older than HEARTBEAT_TIMEOUT seconds
       (handles cases where process is hung/frozen)

    Pipelines should call update_heartbeat() periodically (e.g., every 30s)
    to indicate they are still active. If using the pipeline executor,
    this is handled automatically.
    """

    # Maximum time between heartbeats before considering a pipeline stale
    # If a pipeline hasn't sent a heartbeat in this time, it's assumed dead
    HEARTBEAT_TIMEOUT = 120  # seconds

    def __init__(self, lion_dir: Optional[Path] = None):
        """Initialize the pipeline tracker.

        Args:
            lion_dir: Path to .lion directory. If None, uses ~/.lion
        """
        if lion_dir:
            self._active_dir = lion_dir / "active"
        else:
            self._active_dir = Path.home() / ".lion" / "active"

    def get_active(self) -> list[ActivePipeline]:
        """Get list of currently running pipelines.

        Returns:
            List of ActivePipeline for running pipelines
        """
        pipelines = []

        if not self._active_dir.exists():
            return pipelines

        for pid_file in self._active_dir.glob("*.pid"):
            result = self._load_and_check_pipeline(pid_file)
            if result is not None:
                pipeline, is_running, should_cleanup = result
                if is_running:
                    pipelines.append(pipeline)
                elif should_cleanup:
                    # Only clean up if we confirmed the process is dead
                    try:
                        pid_file.unlink()
                    except OSError:
                        pass

        return pipelines

    def _load_and_check_pipeline(self, pid_file: Path) -> Optional[tuple[ActivePipeline, bool, bool]]:
        """Load pipeline info and check if process is running.

        Args:
            pid_file: Path to the PID file

        Returns:
            Tuple of (ActivePipeline, is_running, should_cleanup) or None if load failed.
            - is_running: True if the process is still running and not stale
            - should_cleanup: True if we should delete the PID file (process confirmed dead/stale)

            Returns None on parse failure to avoid deleting files that may be
            in the middle of being written by another process.
        """
        try:
            with open(pid_file) as f:
                data = json.load(f)

            pipeline = ActivePipeline(
                pid=data["pid"],
                run_id=data.get("run_id", "unknown"),
                prompt=data.get("prompt", "")[:100],
                started_at=data.get("started_at", time.time()),
                current_step=data.get("current_step"),
            )

            # Check if process is running via PID
            pid_is_running = self._is_running(pipeline.pid)

            if not pid_is_running:
                # Process is definitely dead - clean up
                return (pipeline, False, True)

            # Process PID exists, but check heartbeat for frozen/hung processes
            last_heartbeat = data.get("last_heartbeat")
            if last_heartbeat is not None:
                heartbeat_age = time.time() - last_heartbeat
                if heartbeat_age > self.HEARTBEAT_TIMEOUT:
                    # Pipeline hasn't sent heartbeat in too long - consider it stale
                    # This catches cases where the process is hung/frozen
                    return (pipeline, False, True)

            # Process is running and heartbeat is fresh (or no heartbeat tracking)
            return (pipeline, True, False)

        except json.JSONDecodeError:
            # File may be in the middle of being written - don't delete it
            return None
        except OSError:
            # File access error - don't delete, may be transient
            return None
        except KeyError:
            # Missing required 'pid' field - file is corrupt, but we can't
            # verify the process is dead without a PID, so don't delete
            return None

    def _load_pipeline(self, pid_file: Path) -> Optional[ActivePipeline]:
        """Load pipeline info from a PID file.

        Args:
            pid_file: Path to the PID file

        Returns:
            ActivePipeline or None if loading fails
        """
        try:
            with open(pid_file) as f:
                data = json.load(f)

            return ActivePipeline(
                pid=data["pid"],
                run_id=data.get("run_id", "unknown"),
                prompt=data.get("prompt", "")[:100],
                started_at=data.get("started_at", time.time()),
                current_step=data.get("current_step"),
            )
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def _is_running(self, pid: int) -> bool:
        """Check if a process is running.

        Uses multiple checks to verify the process is actually a Lion process:
        1. Signal 0 to check process exists
        2. Optionally verify process name contains 'python' or 'lion' (if psutil available)

        Args:
            pid: Process ID to check

        Returns:
            True if process is likely a running Lion process
        """
        try:
            os.kill(pid, 0)  # Signal 0 checks if process exists
        except OSError:
            return False

        # Process exists, try to verify it's a Python/Lion process
        # This helps avoid PID wraparound issues where a different process
        # gets the same PID as a dead Lion process
        try:
            import psutil
            proc = psutil.Process(pid)
            name = proc.name().lower()
            cmdline = " ".join(proc.cmdline()).lower()
            # Check if it looks like a Python/Lion process
            if "python" in name or "lion" in name or "lion" in cmdline:
                return True
            # If we can check but it doesn't look like Lion, assume stale
            return False
        except ImportError:
            # psutil not available, fall back to assuming process is valid
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def register(self, run_id: str, prompt: str) -> Path:
        """Register the current pipeline as active.

        Also registers an atexit handler to clean up the PID file when
        the process exits normally.

        Args:
            run_id: The run ID
            prompt: The pipeline prompt

        Returns:
            Path to the PID file
        """
        self._active_dir.mkdir(parents=True, exist_ok=True)

        pid = os.getpid()
        pid_file = self._active_dir / f"{pid}.pid"

        now = time.time()
        data = {
            "pid": pid,
            "run_id": run_id,
            "prompt": prompt[:500],
            "started_at": now,
            "last_heartbeat": now,  # Initial heartbeat
        }

        with open(pid_file, "w") as f:
            json.dump(data, f)

        # Register atexit handler to clean up on normal exit
        # This helps prevent stale PID files when processes exit normally
        def cleanup():
            try:
                if pid_file.exists():
                    pid_file.unlink()
            except OSError:
                pass

        atexit.register(cleanup)

        return pid_file

    def update_heartbeat(self) -> None:
        """Update the heartbeat timestamp for the current pipeline.

        Call this periodically (e.g., every 30 seconds) to indicate the
        pipeline is still active. If heartbeat is not updated within
        HEARTBEAT_TIMEOUT seconds, the pipeline will be considered stale.

        This is a no-op if the pipeline is not registered.
        """
        pid = os.getpid()
        pid_file = self._active_dir / f"{pid}.pid"

        if not pid_file.exists():
            return

        try:
            with open(pid_file) as f:
                data = json.load(f)

            data["last_heartbeat"] = time.time()

            with open(pid_file, "w") as f:
                json.dump(data, f)
        except (json.JSONDecodeError, OSError):
            pass

    def update_step(self, step_name: str) -> None:
        """Update the current step for this pipeline.

        Also updates the heartbeat timestamp since step updates indicate
        the pipeline is still active.

        Args:
            step_name: Name of the current step
        """
        pid = os.getpid()
        pid_file = self._active_dir / f"{pid}.pid"

        if not pid_file.exists():
            return

        try:
            with open(pid_file) as f:
                data = json.load(f)

            data["current_step"] = step_name
            data["last_heartbeat"] = time.time()  # Step update = heartbeat

            with open(pid_file, "w") as f:
                json.dump(data, f)
        except (json.JSONDecodeError, OSError):
            pass

    def unregister(self) -> None:
        """Unregister the current pipeline."""
        pid = os.getpid()
        pid_file = self._active_dir / f"{pid}.pid"

        try:
            pid_file.unlink()
        except OSError:
            pass


class StatusDashboard:
    """Aggregate status information and render dashboard.

    Combines:
    - Quota usage from QuotaTracker
    - Today's sessions from SessionScanner
    - Active pipelines from ActivePipelineTracker

    Handles missing directories and corrupted files gracefully with
    user-friendly messages.
    """

    def __init__(
        self,
        config: dict,
        runs_dir: Optional[Path] = None,
        lion_dir: Optional[Path] = None,
    ):
        """Initialize the status dashboard.

        Args:
            config: Lion configuration dict
            runs_dir: Path to runs directory. If None, uses ~/.lion/runs
            lion_dir: Path to .lion directory. If None, uses ~/.lion

        Note: Missing directories are handled gracefully - no exception is raised.
        The dashboard will show empty data with informative messages.
        """
        self._config = config
        self._init_errors: list[str] = []

        # Set up paths
        if lion_dir:
            self._lion_dir = lion_dir
        else:
            self._lion_dir = Path.home() / ".lion"

        if runs_dir:
            self._runs_dir = runs_dir
        else:
            self._runs_dir = self._lion_dir / "runs"

        # Check if lion_dir exists - if not, note it but continue
        if not self._lion_dir.exists():
            self._init_errors.append(
                f"Lion directory not found: {self._lion_dir}. "
                "Run a pipeline first to see stats here."
            )

        # Initialize trackers (they handle missing files gracefully)
        self._quota = QuotaTracker(config, self._lion_dir / "quota.json")
        self._sessions = SessionScanner(self._runs_dir)
        self._pipelines = ActivePipelineTracker(self._lion_dir)

    def get_status(self) -> StatusReport:
        """Get aggregated status report.

        Returns:
            StatusReport with all status information.
            Handles errors gracefully - missing data results in empty lists,
            not exceptions.
        """
        # Collect all warnings, including initialization errors
        warnings = list(self._init_errors)

        # Get quota usage (handles missing file gracefully)
        try:
            quota_usage = self._quota.get_all_usage()
            warnings.extend(self._quota.get_warnings())
        except Exception as e:
            quota_usage = {}
            warnings.append(f"Could not read quota data: {e}")

        # Get today's sessions (handles missing directory gracefully)
        try:
            todays_sessions = self._sessions.scan_today()
        except Exception as e:
            todays_sessions = []
            warnings.append(f"Could not read session history: {e}")

        # Get active pipelines (handles missing directory gracefully)
        try:
            active_pipelines = self._pipelines.get_active()
        except Exception as e:
            active_pipelines = []
            warnings.append(f"Could not read active pipelines: {e}")

        total_tokens = sum(s.tokens_used for s in todays_sessions)

        return StatusReport(
            quota_usage=quota_usage,
            todays_sessions=todays_sessions,
            active_pipelines=active_pipelines,
            total_tokens_today=total_tokens,
            total_sessions_today=len(todays_sessions),
            quota_warnings=warnings,
        )

    def render(self, use_json: bool = False) -> str:
        """Render the status dashboard.

        Args:
            use_json: If True, return JSON instead of formatted text

        Returns:
            Formatted dashboard string (or JSON)
        """
        status = self.get_status()

        if use_json:
            return self._render_json(status)

        if RICH_AVAILABLE:
            return self._render_rich(status)

        return self._render_plain(status)

    def _render_json(self, status: StatusReport) -> str:
        """Render status as JSON.

        Args:
            status: StatusReport to render

        Returns:
            JSON string
        """
        data = {
            "quota": {
                model: {
                    "tokens_used": usage.tokens_used,
                    "daily_limit": usage.daily_limit,
                    "usage_percent": usage.usage_percent,
                    "requests": usage.requests,
                }
                for model, usage in status.quota_usage.items()
            },
            "sessions_today": [
                {
                    "run_id": s.run_id,
                    "timestamp": s.timestamp,
                    "prompt": s.prompt,
                    "tokens_used": s.tokens_used if s.tokens_available else None,
                    "tokens_available": s.tokens_available,
                    "duration": s.duration,
                    "success": s.success,
                }
                for s in status.todays_sessions
            ],
            "active_pipelines": [
                {
                    "pid": p.pid,
                    "run_id": p.run_id,
                    "prompt": p.prompt,
                    "elapsed": p.elapsed,
                    "current_step": p.current_step,
                }
                for p in status.active_pipelines
            ],
            "summary": {
                "total_tokens_today": status.total_tokens_today,
                "total_sessions_today": status.total_sessions_today,
            },
            "warnings": status.quota_warnings,
        }

        return json.dumps(data, indent=2)

    def _render_rich(self, status: StatusReport) -> str:
        """Render status using Rich tables.

        Args:
            status: StatusReport to render

        Returns:
            Formatted string (rendered by Rich)
        """
        console = Console(record=True, force_terminal=True)

        # Title
        console.print()
        console.print(Panel.fit(
            "[bold blue]Lion Status Dashboard[/bold blue]",
            border_style="blue",
        ))

        # Warnings (including init errors and quota warnings)
        if status.quota_warnings:
            console.print()
            for warning in status.quota_warnings:
                # Distinguish info messages from actual warnings
                if "not found" in warning.lower() or "run a pipeline first" in warning.lower():
                    console.print(f"[dim]Info:[/dim] {warning}")
                else:
                    console.print(f"[yellow]Warning:[/yellow] {warning}")

        # Quota Usage Table
        console.print()
        quota_table = Table(
            title="Quota Usage",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        quota_table.add_column("Model", style="cyan")
        quota_table.add_column("Tokens Used", justify="right")
        quota_table.add_column("Daily Limit", justify="right")
        quota_table.add_column("Usage", justify="right")
        quota_table.add_column("Requests", justify="right")

        for model, usage in sorted(status.quota_usage.items()):
            # Color code usage percentage
            if usage.is_over_limit:
                pct_style = "bold red"
            elif usage.usage_percent >= 80:
                pct_style = "yellow"
            else:
                pct_style = "green"

            limit_str = f"{usage.daily_limit:,}" if usage.daily_limit > 0 else "-"
            pct_str = f"[{pct_style}]{usage.usage_percent:.0f}%[/{pct_style}]"

            quota_table.add_row(
                model,
                f"{usage.tokens_used:,}",
                limit_str,
                pct_str,
                str(usage.requests),
            )

        console.print(quota_table)

        # Today's Sessions Table
        console.print()
        sessions_table = Table(
            title=f"Today's Sessions ({status.total_sessions_today})",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        sessions_table.add_column("Time", style="dim")
        sessions_table.add_column("Prompt", max_width=40)
        sessions_table.add_column("Tokens", justify="right")
        sessions_table.add_column("Duration", justify="right")
        sessions_table.add_column("Status")

        for session in status.todays_sessions[:10]:  # Limit to 10 most recent
            time_str = session.datetime.strftime("%H:%M")
            prompt_str = session.prompt[:37] + "..." if len(session.prompt) > 40 else session.prompt
            duration_str = f"{session.duration:.1f}s" if session.duration > 0 else "-"
            status_str = "[green]OK[/green]" if session.success else "[red]FAIL[/red]"
            # Show token count or indicate unavailable
            tokens_str = f"{session.tokens_used:,}" if session.tokens_available else "[dim]-[/dim]"

            sessions_table.add_row(
                time_str,
                prompt_str,
                tokens_str,
                duration_str,
                status_str,
            )

        if status.total_sessions_today > 10:
            sessions_table.add_row(
                "...",
                f"[dim]({status.total_sessions_today - 10} more)[/dim]",
                "",
                "",
                "",
            )

        console.print(sessions_table)

        # Active Pipelines Table
        if status.active_pipelines:
            console.print()
            active_table = Table(
                title="Active Pipelines",
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
            )
            active_table.add_column("PID", style="cyan")
            active_table.add_column("Prompt", max_width=40)
            active_table.add_column("Step")
            active_table.add_column("Elapsed", justify="right")

            for pipeline in status.active_pipelines:
                prompt_str = pipeline.prompt[:37] + "..." if len(pipeline.prompt) > 40 else pipeline.prompt
                step_str = pipeline.current_step or "-"
                elapsed_str = f"{pipeline.elapsed:.0f}s"

                active_table.add_row(
                    str(pipeline.pid),
                    prompt_str,
                    step_str,
                    elapsed_str,
                )

            console.print(active_table)

        # Summary
        console.print()
        console.print(
            f"[dim]Total today: {status.total_tokens_today:,} tokens, "
            f"{status.total_sessions_today} sessions[/dim]"
        )
        console.print()

        return console.export_text()

    def _render_plain(self, status: StatusReport) -> str:
        """Render status as plain text (no Rich).

        Args:
            status: StatusReport to render

        Returns:
            Plain text string
        """
        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("  Lion Status Dashboard")
        lines.append("=" * 60)

        # Warnings (including init errors and quota warnings)
        if status.quota_warnings:
            lines.append("")
            for warning in status.quota_warnings:
                # Distinguish info messages from actual warnings
                if "not found" in warning.lower() or "run a pipeline first" in warning.lower():
                    lines.append(f"INFO: {warning}")
                else:
                    lines.append(f"WARNING: {warning}")

        # Quota Usage
        lines.append("")
        lines.append("Quota Usage:")
        lines.append("-" * 40)
        lines.append(f"{'Model':<15} {'Used':>10} {'Limit':>10} {'Usage':>8}")
        lines.append("-" * 40)

        for model, usage in sorted(status.quota_usage.items()):
            limit_str = f"{usage.daily_limit:,}" if usage.daily_limit > 0 else "-"
            lines.append(
                f"{model:<15} {usage.tokens_used:>10,} {limit_str:>10} {usage.usage_percent:>7.0f}%"
            )

        # Today's Sessions
        lines.append("")
        lines.append(f"Today's Sessions ({status.total_sessions_today}):")
        lines.append("-" * 60)

        for session in status.todays_sessions[:10]:
            time_str = session.datetime.strftime("%H:%M")
            prompt_str = session.prompt[:30] + "..." if len(session.prompt) > 30 else session.prompt
            status_str = "OK" if session.success else "FAIL"
            tokens_str = f"{session.tokens_used:>8,}" if session.tokens_available else "       -"
            lines.append(f"  {time_str}  {prompt_str:<35} {tokens_str} {status_str}")

        if status.total_sessions_today > 10:
            lines.append(f"  ... ({status.total_sessions_today - 10} more)")

        # Active Pipelines
        if status.active_pipelines:
            lines.append("")
            lines.append("Active Pipelines:")
            lines.append("-" * 40)

            for pipeline in status.active_pipelines:
                prompt_str = pipeline.prompt[:30] + "..." if len(pipeline.prompt) > 30 else pipeline.prompt
                lines.append(f"  PID {pipeline.pid}: {prompt_str} ({pipeline.elapsed:.0f}s)")

        # Summary
        lines.append("")
        lines.append(
            f"Total today: {status.total_tokens_today:,} tokens, "
            f"{status.total_sessions_today} sessions"
        )
        lines.append("")

        return "\n".join(lines)
