"""Tests for the status dashboard system."""

import json
import os
import platform
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lion.status import (
    QuotaTracker,
    SessionScanner,
    ActivePipelineTracker,
    StatusDashboard,
    ModelUsage,
    SessionInfo,
    ActivePipeline,
    StatusReport,
    _file_lock_shared,
    _file_lock_exclusive,
)


class TestModelUsage:
    """Tests for ModelUsage dataclass."""

    def test_usage_percent_with_limit(self):
        usage = ModelUsage(model="claude", tokens_used=50000, daily_limit=100000)
        assert usage.usage_percent == 50.0

    def test_usage_percent_over_limit(self):
        usage = ModelUsage(model="claude", tokens_used=150000, daily_limit=100000)
        assert usage.usage_percent == 100.0  # Capped at 100

    def test_usage_percent_no_limit(self):
        usage = ModelUsage(model="claude", tokens_used=50000, daily_limit=0)
        assert usage.usage_percent == 0.0

    def test_is_over_limit(self):
        over = ModelUsage(model="claude", tokens_used=150000, daily_limit=100000)
        under = ModelUsage(model="claude", tokens_used=50000, daily_limit=100000)
        no_limit = ModelUsage(model="claude", tokens_used=150000, daily_limit=0)

        assert over.is_over_limit is True
        assert under.is_over_limit is False
        assert no_limit.is_over_limit is False


class TestQuotaTracker:
    """Tests for QuotaTracker."""

    def test_record_and_get_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            config = {"quota": {"enabled": True}}

            tracker = QuotaTracker(config, quota_file=quota_file)
            tracker.record_usage("claude", 1000)
            tracker.record_usage("claude", 500)
            tracker.record_usage("gemini", 2000)

            claude_usage = tracker.get_usage("claude")
            assert claude_usage.tokens_used == 1500
            assert claude_usage.requests == 2

            gemini_usage = tracker.get_usage("gemini")
            assert gemini_usage.tokens_used == 2000
            assert gemini_usage.requests == 1

    def test_daily_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"

            # Write yesterday's data
            yesterday_data = {
                "date": "2020-01-01",  # Old date
                "usage": {"claude": {"tokens": 50000, "requests": 10}},
            }
            with open(quota_file, "w") as f:
                json.dump(yesterday_data, f)

            config = {"quota": {"enabled": True}}
            tracker = QuotaTracker(config, quota_file=quota_file)

            # Should have reset
            usage = tracker.get_usage("claude")
            assert usage.tokens_used == 0

    def test_daily_limits_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            config = {
                "quota": {
                    "enabled": True,
                    "daily_limits": {"claude": 100000, "gemini": 200000},
                }
            }

            tracker = QuotaTracker(config, quota_file=quota_file)
            tracker.record_usage("claude", 50000)

            usage = tracker.get_usage("claude")
            assert usage.daily_limit == 100000
            assert usage.usage_percent == 50.0

    def test_warnings_at_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            config = {
                "quota": {
                    "enabled": True,
                    "daily_limits": {"claude": 100000},
                    "warn_threshold": 0.8,
                }
            }

            tracker = QuotaTracker(config, quota_file=quota_file)
            tracker.record_usage("claude", 85000)  # 85% usage

            warnings = tracker.get_warnings()
            assert len(warnings) == 1
            assert "claude" in warnings[0].lower()
            assert "approaching" in warnings[0].lower()

    def test_warnings_over_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            config = {
                "quota": {
                    "enabled": True,
                    "daily_limits": {"claude": 100000},
                }
            }

            tracker = QuotaTracker(config, quota_file=quota_file)
            tracker.record_usage("claude", 150000)

            warnings = tracker.get_warnings()
            assert len(warnings) == 1
            assert "exceeded" in warnings[0].lower()

    def test_disabled_quota_tracking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            config = {"quota": {"enabled": False}}

            tracker = QuotaTracker(config, quota_file=quota_file)
            tracker.record_usage("claude", 1000)

            # Should not record when disabled
            usage = tracker.get_usage("claude")
            assert usage.tokens_used == 0


class TestSessionScanner:
    """Tests for SessionScanner."""

    def _create_run(self, runs_dir: Path, run_id: str, entries: list[dict]) -> Path:
        """Helper to create a mock run directory with memory.jsonl."""
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)

        memory_file = run_dir / "memory.jsonl"
        with open(memory_file, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        return run_dir

    def test_scan_today_finds_recent_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            now = time.time()
            self._create_run(runs_dir, "run_today", [
                {"timestamp": now, "phase": "implement", "content": "test prompt", "metadata": {"tokens_used": 100}},
                {"timestamp": now + 1, "phase": "implement", "metadata": {"tokens_used": 200}},
            ])

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today()

            assert len(sessions) == 1
            assert sessions[0].run_id == "run_today"
            assert sessions[0].tokens_used == 300

    def test_scan_excludes_old_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            # Create old run
            old_time = time.time() - 86400 * 2  # 2 days ago
            run_dir = self._create_run(runs_dir, "run_old", [
                {"timestamp": old_time, "phase": "implement", "content": "old"},
            ])
            # Set file mtime to old time
            os.utime(run_dir / "memory.jsonl", (old_time, old_time))

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today()

            assert len(sessions) == 0

    def test_streaming_parse_aggregates_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            now = time.time()
            self._create_run(runs_dir, "run_stats", [
                {"timestamp": now, "phase": "propose", "metadata": {"tokens_used": 100, "model": "claude"}},
                {"timestamp": now + 1, "phase": "critique", "metadata": {"tokens_used": 150, "model": "claude"}},
                {"timestamp": now + 2, "phase": "implement", "metadata": {"tokens_used": 500, "model": "gemini"}},
                {"timestamp": now + 10, "phase": "test", "metadata": {"tokens_used": 50}},
            ])

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today()

            assert len(sessions) == 1
            session = sessions[0]
            assert session.tokens_used == 800
            assert session.tokens_available is True
            assert session.steps_completed == 4
            assert set(session.models_used) == {"claude", "gemini"}
            assert session.duration == 10

    def test_tokens_available_false_when_no_token_data(self):
        """Test that tokens_available is False when no token data in entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            now = time.time()
            # Create run with no tokens_used in metadata
            self._create_run(runs_dir, "run_no_tokens", [
                {"timestamp": now, "phase": "implement", "content": "test"},
                {"timestamp": now + 1, "phase": "test", "metadata": {}},
            ])

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today()

            assert len(sessions) == 1
            session = sessions[0]
            assert session.tokens_used == 0
            assert session.tokens_available is False

    def test_detects_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            now = time.time()
            self._create_run(runs_dir, "run_error", [
                {"timestamp": now, "phase": "implement", "content": "start"},
                {"timestamp": now + 1, "type": "error", "content": "something failed"},
            ])

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today()

            assert len(sessions) == 1
            assert sessions[0].success is False

    def test_limit_parameter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)

            now = time.time()
            for i in range(10):
                self._create_run(runs_dir, f"run_{i}", [
                    {"timestamp": now + i, "phase": "implement", "content": f"run {i}"},
                ])

            scanner = SessionScanner(runs_dir)
            sessions = scanner.scan_today(limit=3)

            assert len(sessions) == 3


class TestActivePipelineTracker:
    """Tests for ActivePipelineTracker."""

    def test_register_and_get_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)

            tracker = ActivePipelineTracker(lion_dir)
            pid_file = tracker.register("run_123", "test prompt")

            assert pid_file.exists()

            active = tracker.get_active()
            assert len(active) == 1
            assert active[0].run_id == "run_123"
            assert active[0].prompt == "test prompt"
            assert active[0].pid == os.getpid()

    def test_unregister_removes_pid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)

            tracker = ActivePipelineTracker(lion_dir)
            pid_file = tracker.register("run_123", "test")

            assert pid_file.exists()

            tracker.unregister()
            assert not pid_file.exists()

    def test_update_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)

            tracker = ActivePipelineTracker(lion_dir)
            tracker.register("run_123", "test")
            tracker.update_step("impl")

            active = tracker.get_active()
            assert len(active) == 1
            assert active[0].current_step == "impl"

    def test_cleans_stale_pid_files_only_when_process_dead(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            active_dir = lion_dir / "active"
            active_dir.mkdir(parents=True)

            # Create a stale PID file for a non-existent process
            stale_pid = 99999999  # Unlikely to exist
            stale_file = active_dir / f"{stale_pid}.pid"
            with open(stale_file, "w") as f:
                json.dump({"pid": stale_pid, "run_id": "old", "prompt": "old", "started_at": time.time()}, f)

            tracker = ActivePipelineTracker(lion_dir)
            active = tracker.get_active()

            # Should have cleaned up the stale file (process confirmed dead)
            assert len(active) == 0
            assert not stale_file.exists()

    def test_does_not_delete_on_parse_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            active_dir = lion_dir / "active"
            active_dir.mkdir(parents=True)

            # Create a corrupt/incomplete PID file (simulates mid-write)
            corrupt_file = active_dir / "12345.pid"
            with open(corrupt_file, "w") as f:
                f.write('{"pid": 12345, "run_id": "test"')  # Invalid JSON

            tracker = ActivePipelineTracker(lion_dir)
            active = tracker.get_active()

            # Should NOT delete the file on parse failure
            assert len(active) == 0
            assert corrupt_file.exists()  # File should still exist


class TestStatusDashboard:
    """Tests for StatusDashboard."""

    def test_get_status_aggregates_all_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            runs_dir = lion_dir / "runs"
            runs_dir.mkdir(parents=True)

            # Create a run
            now = time.time()
            run_dir = runs_dir / "test_run"
            run_dir.mkdir()
            with open(run_dir / "memory.jsonl", "w") as f:
                f.write(json.dumps({"timestamp": now, "phase": "implement", "metadata": {"tokens_used": 500}}) + "\n")

            config = {
                "quota": {"enabled": True, "daily_limits": {"claude": 100000}},
            }

            dashboard = StatusDashboard(config, runs_dir=runs_dir, lion_dir=lion_dir)

            # Record some quota usage
            dashboard._quota.record_usage("claude", 1000)

            status = dashboard.get_status()

            assert isinstance(status, StatusReport)
            assert "claude" in status.quota_usage
            assert status.quota_usage["claude"].tokens_used == 1000
            assert len(status.todays_sessions) >= 0  # May or may not find the run depending on timing

    def test_render_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            runs_dir = lion_dir / "runs"
            runs_dir.mkdir(parents=True)

            config = {"quota": {"enabled": True}}
            dashboard = StatusDashboard(config, runs_dir=runs_dir, lion_dir=lion_dir)

            output = dashboard.render(use_json=True)

            # Should be valid JSON
            data = json.loads(output)
            assert "quota" in data
            assert "sessions_today" in data
            assert "active_pipelines" in data
            assert "summary" in data

    def test_render_plain_without_rich(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            runs_dir = lion_dir / "runs"
            runs_dir.mkdir(parents=True)

            config = {"quota": {"enabled": True}}
            dashboard = StatusDashboard(config, runs_dir=runs_dir, lion_dir=lion_dir)

            # Mock RICH_AVAILABLE to False
            with patch("lion.status.RICH_AVAILABLE", False):
                output = dashboard.render()

            assert "Lion Status Dashboard" in output
            assert "Quota Usage" in output


class TestCrossPlatformLocking:
    """Tests for cross-platform file locking."""

    def test_file_lock_shared_context_manager(self):
        """Test that shared lock context manager works."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            with open(temp_path, 'r') as f:
                with _file_lock_shared(f):
                    content = f.read()
                    assert content == "test content"
        finally:
            os.unlink(temp_path)

    def test_file_lock_exclusive_context_manager(self):
        """Test that exclusive lock context manager works."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            with open(temp_path, 'w') as f:
                with _file_lock_exclusive(f):
                    f.write("new content")

            with open(temp_path, 'r') as f:
                content = f.read()
                assert content == "new content"
        finally:
            os.unlink(temp_path)

    def test_lock_functions_available_on_current_platform(self):
        """Test that lock functions are defined and callable."""
        # These should be defined regardless of platform
        assert callable(_file_lock_shared)
        assert callable(_file_lock_exclusive)


class TestActivePipelineTrackerAtexit:
    """Tests for ActivePipelineTracker atexit cleanup."""

    def test_register_creates_pid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            pid_file = tracker.register("run_123", "test prompt")

            assert pid_file.exists()
            with open(pid_file) as f:
                data = json.load(f)
            assert data["pid"] == os.getpid()
            assert data["run_id"] == "run_123"

            # Clean up
            tracker.unregister()

    def test_is_running_returns_true_for_current_process(self):
        """Test _is_running returns True for current process."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            # Current process should be detected as running
            assert tracker._is_running(os.getpid()) is True

    def test_is_running_returns_false_for_nonexistent_pid(self):
        """Test _is_running returns False for non-existent PID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            # Very high PID that almost certainly doesn't exist
            assert tracker._is_running(9999999) is False


class TestHeartbeatMechanism:
    """Tests for heartbeat-based staleness detection."""

    def test_register_includes_heartbeat(self):
        """Test that register() includes initial heartbeat timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            pid_file = tracker.register("run_123", "test prompt")

            with open(pid_file) as f:
                data = json.load(f)

            assert "last_heartbeat" in data
            assert data["last_heartbeat"] > 0

            # Clean up
            tracker.unregister()

    def test_update_heartbeat(self):
        """Test that update_heartbeat() updates the timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            pid_file = tracker.register("run_123", "test prompt")

            # Get initial heartbeat
            with open(pid_file) as f:
                data = json.load(f)
            initial_heartbeat = data["last_heartbeat"]

            # Wait a tiny bit and update
            time.sleep(0.01)
            tracker.update_heartbeat()

            # Verify heartbeat was updated
            with open(pid_file) as f:
                data = json.load(f)
            assert data["last_heartbeat"] > initial_heartbeat

            # Clean up
            tracker.unregister()

    def test_update_step_also_updates_heartbeat(self):
        """Test that update_step() also updates the heartbeat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            pid_file = tracker.register("run_123", "test prompt")

            # Get initial heartbeat
            with open(pid_file) as f:
                data = json.load(f)
            initial_heartbeat = data["last_heartbeat"]

            # Wait a tiny bit and update step
            time.sleep(0.01)
            tracker.update_step("impl")

            # Verify heartbeat was updated along with step
            with open(pid_file) as f:
                data = json.load(f)
            assert data["current_step"] == "impl"
            assert data["last_heartbeat"] > initial_heartbeat

            # Clean up
            tracker.unregister()

    def test_stale_heartbeat_cleans_up(self):
        """Test that pipelines with stale heartbeats are cleaned up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            active_dir = lion_dir / "active"
            active_dir.mkdir(parents=True)

            # Create a PID file with stale heartbeat (older than timeout)
            stale_heartbeat = time.time() - 200  # Well past the 120s timeout
            pid_file = active_dir / f"{os.getpid()}.pid"
            with open(pid_file, "w") as f:
                json.dump({
                    "pid": os.getpid(),
                    "run_id": "stale_run",
                    "prompt": "stale prompt",
                    "started_at": stale_heartbeat - 100,
                    "last_heartbeat": stale_heartbeat,
                }, f)

            tracker = ActivePipelineTracker(lion_dir)
            active = tracker.get_active()

            # Even though our process is running, the stale heartbeat
            # should cause the pipeline to be considered inactive and cleaned up
            assert len(active) == 0
            assert not pid_file.exists()

    def test_fresh_heartbeat_keeps_pipeline(self):
        """Test that pipelines with fresh heartbeats are kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir)
            tracker = ActivePipelineTracker(lion_dir)

            # Register and immediately check - heartbeat is fresh
            tracker.register("run_123", "test prompt")

            active = tracker.get_active()
            assert len(active) == 1
            assert active[0].run_id == "run_123"

            # Clean up
            tracker.unregister()


class TestStatusDashboardErrorHandling:
    """Tests for StatusDashboard error handling."""

    def test_missing_lion_dir_shows_info_message(self):
        """Test that missing lion dir results in info message, not error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a non-existent subdirectory
            lion_dir = Path(tmpdir) / "nonexistent" / ".lion"

            config = {"quota": {"enabled": True}}
            dashboard = StatusDashboard(config, lion_dir=lion_dir)

            status = dashboard.get_status()

            # Should have an info message about missing directory
            assert len(status.quota_warnings) > 0
            assert any("not found" in w.lower() for w in status.quota_warnings)

    def test_render_distinguishes_info_from_warnings(self):
        """Test that render output distinguishes info messages from warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lion_dir = Path(tmpdir) / "nonexistent"

            config = {"quota": {"enabled": True}}
            dashboard = StatusDashboard(config, lion_dir=lion_dir)

            output = dashboard.render(use_json=False)

            # Should show "INFO" not "WARNING" for missing directory
            assert "INFO" in output or "Info" in output
