"""Tests for the notification system."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from lion.notifications import (
    NotificationManager,
    NotificationResult,
    Notification,
    NotificationEvent,
    NotificationUrgency,
    MacOSNotifier,
    LinuxNotifier,
    PlyerNotifier,
    WindowsNotifier,
    DisabledNotifier,
    NoBackendNotifier,
    HeadlessNotifier,
    detect_platform,
    is_headless_environment,
    create_notification_manager,
    get_cached_manager,
    clear_manager_cache,
)


class TestNotificationResult:
    """Tests for NotificationResult dataclass."""

    def test_sent_result(self):
        result = NotificationResult.sent("macos-osascript")
        assert result.success is True
        assert result.skipped is False
        assert result.error is None
        assert result.backend == "macos-osascript"

    def test_skipped_disabled_result(self):
        result = NotificationResult.skipped_disabled("test reason")
        assert result.success is True
        assert result.skipped is True
        assert result.error is None
        assert result.reason == "test reason"

    def test_skipped_no_backend_result(self):
        result = NotificationResult.skipped_no_backend()
        assert result.success is False
        assert result.skipped is False
        assert result.error is not None
        assert "no" in result.error.lower() and "backend" in result.error.lower()
        assert result.reason == "no_backend"

    def test_failed_result(self):
        result = NotificationResult.failed("command failed", backend="linux-notify-send")
        assert result.success is False
        assert result.skipped is False
        assert result.error == "command failed"
        assert result.backend == "linux-notify-send"


class TestMacOSNotifier:
    """Tests for MacOSNotifier."""

    @patch("lion.notifications.detect_platform", return_value="darwin")
    @patch("lion.notifications.is_command_available", return_value=True)
    def test_is_available_on_macos(self, mock_cmd, mock_platform):
        notifier = MacOSNotifier()
        assert notifier.is_available() is True

    @patch("lion.notifications.detect_platform", return_value="linux")
    def test_not_available_on_linux(self, mock_platform):
        notifier = MacOSNotifier()
        assert notifier.is_available() is False

    @patch("lion.notifications.detect_platform", return_value="darwin")
    @patch("lion.notifications.is_command_available", return_value=True)
    @patch("subprocess.run")
    def test_send_success(self, mock_run, mock_cmd, mock_platform):
        mock_run.return_value = MagicMock(returncode=0)

        notifier = MacOSNotifier()
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is True
        assert result.backend == "macos-osascript"
        mock_run.assert_called_once()

    @patch("lion.notifications.detect_platform", return_value="darwin")
    @patch("lion.notifications.is_command_available", return_value=True)
    @patch("subprocess.run")
    def test_send_timeout(self, mock_run, mock_cmd, mock_platform):
        mock_run.side_effect = subprocess.TimeoutExpired("osascript", 5)

        notifier = MacOSNotifier()
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("lion.notifications.detect_platform", return_value="darwin")
    @patch("lion.notifications.is_command_available", return_value=True)
    @patch("subprocess.run")
    def test_send_with_sound(self, mock_run, mock_cmd, mock_platform):
        mock_run.return_value = MagicMock(returncode=0)

        notifier = MacOSNotifier()
        notification = Notification(title="Test", message="Hello", sound=True)
        notifier.send(notification)

        # Check that the script includes sound
        call_args = mock_run.call_args[0][0]
        script = call_args[2]  # osascript -e <script>
        assert 'sound name "default"' in script


class TestLinuxNotifier:
    """Tests for LinuxNotifier."""

    @patch("lion.notifications.detect_platform", return_value="linux")
    @patch("lion.notifications.is_command_available", return_value=True)
    def test_is_available_on_linux(self, mock_cmd, mock_platform):
        notifier = LinuxNotifier()
        assert notifier.is_available() is True

    @patch("lion.notifications.detect_platform", return_value="darwin")
    def test_not_available_on_macos(self, mock_platform):
        notifier = LinuxNotifier()
        assert notifier.is_available() is False

    @patch("lion.notifications.detect_platform", return_value="linux")
    @patch("lion.notifications.is_command_available", return_value=True)
    @patch("subprocess.run")
    def test_send_success(self, mock_run, mock_cmd, mock_platform):
        mock_run.return_value = MagicMock(returncode=0)

        notifier = LinuxNotifier()
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is True
        assert result.backend == "linux-notify-send"

    @patch("lion.notifications.detect_platform", return_value="linux")
    @patch("lion.notifications.is_command_available", return_value=True)
    @patch("subprocess.run")
    def test_urgency_mapping(self, mock_run, mock_cmd, mock_platform):
        mock_run.return_value = MagicMock(returncode=0)

        notifier = LinuxNotifier()
        notification = Notification(
            title="Test",
            message="Critical!",
            urgency=NotificationUrgency.CRITICAL
        )
        notifier.send(notification)

        call_args = mock_run.call_args[0][0]
        assert "--urgency" in call_args
        urgency_idx = call_args.index("--urgency")
        assert call_args[urgency_idx + 1] == "critical"


class TestDisabledNotifier:
    """Tests for DisabledNotifier."""

    def test_is_always_available(self):
        notifier = DisabledNotifier()
        assert notifier.is_available() is True

    def test_send_returns_skipped(self):
        notifier = DisabledNotifier()
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is True
        assert result.skipped is True
        assert "disabled" in result.reason.lower()


class TestNoBackendNotifier:
    """Tests for NoBackendNotifier."""

    def test_is_not_available(self):
        notifier = NoBackendNotifier()
        assert notifier.is_available() is False

    def test_send_returns_failure(self):
        notifier = NoBackendNotifier()
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is False
        assert result.skipped is False
        assert result.error is not None
        assert result.reason == "no_backend"


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_disabled_config(self):
        config = {"notifications": {"enabled": False}}
        manager = NotificationManager(config)

        assert manager.backend_name == "disabled"
        assert manager.is_enabled is False

    def test_event_filtering(self):
        config = {
            "notifications": {
                "enabled": True,
                "events": ["test_failed"],  # Only test_failed enabled
            }
        }

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)

            # pipeline_complete should be skipped (not in events list)
            result = manager.notify_pipeline_complete("test prompt", success=True)
            assert result.skipped is True

    def test_notify_pipeline_complete_formats_message(self):
        config = {"notifications": {"enabled": True}}

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)
            manager.notify_pipeline_complete(
                prompt="Build a feature",
                success=True,
                duration=10.5,
                steps_completed=3,
                total_steps=3,
            )

            # Check the notification was formatted correctly
            call_args = mock_notifier.send.call_args[0][0]
            assert "Lion:" in call_args.title
            assert "Build a feature" in call_args.title
            assert "successfully" in call_args.message
            assert "3/3" in call_args.message
            assert "10.5s" in call_args.message

    def test_notify_test_failed_uses_critical_urgency(self):
        config = {"notifications": {"enabled": True}}

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)
            manager.notify_test_failed(
                test_name="test_auth.py",
                error_message="AssertionError",
                failed_count=3,
            )

            call_args = mock_notifier.send.call_args[0][0]
            assert call_args.urgency == NotificationUrgency.CRITICAL


class TestWindowsNotifier:
    """Tests for WindowsNotifier."""

    @patch("lion.notifications.detect_platform", return_value="windows")
    def test_is_available_on_windows_with_plyer(self, mock_platform):
        notifier = WindowsNotifier()
        # Mock the plyer notifier to be available
        notifier._plyer_notifier._checked = True
        notifier._plyer_notifier._plyer = MagicMock()
        assert notifier.is_available() is True

    @patch("lion.notifications.detect_platform", return_value="linux")
    def test_not_available_on_linux(self, mock_platform):
        notifier = WindowsNotifier()
        assert notifier.is_available() is False

    @patch("lion.notifications.detect_platform", return_value="windows")
    def test_send_success(self, mock_platform):
        notifier = WindowsNotifier()
        # Mock the plyer notifier
        notifier._plyer_notifier._checked = True
        mock_plyer = MagicMock()
        notifier._plyer_notifier._plyer = mock_plyer

        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is True
        assert result.backend == "windows-plyer"
        mock_plyer.notify.assert_called_once()


class TestSoundSettingLogic:
    """Tests for sound setting logic in NotificationManager."""

    def test_sound_explicit_true_overrides_config_false(self):
        config = {"notifications": {"enabled": True, "sound": False}}

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)
            notification = Notification(title="Test", message="Hello", sound=True)
            manager.send(notification)

            # Check the notification sent had sound=True
            call_args = mock_notifier.send.call_args[0][0]
            assert call_args.sound is True

    def test_sound_explicit_false_overrides_config_true(self):
        config = {"notifications": {"enabled": True, "sound": True}}

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)
            notification = Notification(title="Test", message="Hello", sound=False)
            manager.send(notification)

            # Check the notification sent had sound=False
            call_args = mock_notifier.send.call_args[0][0]
            assert call_args.sound is False

    def test_sound_none_uses_config_default(self):
        config = {"notifications": {"enabled": True, "sound": True}}

        with patch.object(NotificationManager, "_select_notifier") as mock_select:
            mock_notifier = MagicMock()
            mock_notifier.send.return_value = NotificationResult.sent("mock")
            mock_select.return_value = mock_notifier

            manager = NotificationManager(config)
            notification = Notification(title="Test", message="Hello", sound=None)
            manager.send(notification)

            # Check the notification sent had sound=True from config
            call_args = mock_notifier.send.call_args[0][0]
            assert call_args.sound is True


class TestCreateNotificationManager:
    """Tests for the factory function."""

    def test_creates_fresh_instance_each_time(self):
        config1 = {"notifications": {"enabled": True}}
        config2 = {"notifications": {"enabled": False}}

        manager1 = create_notification_manager(config1)
        manager2 = create_notification_manager(config2)

        # They should be different instances with different configs
        assert manager1 is not manager2
        assert manager1.is_enabled is True
        assert manager2.is_enabled is False

    def test_default_config_when_none(self):
        manager = create_notification_manager(None)
        # Should not raise, should use defaults
        assert manager is not None


class TestManagerCaching:
    """Tests for notification manager caching."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_manager_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_manager_cache()

    def test_cached_manager_returns_same_instance(self):
        config = {"notifications": {"enabled": True}}

        manager1 = get_cached_manager(config)
        manager2 = get_cached_manager(config)

        # Same config object should return same manager
        assert manager1 is manager2

    def test_cached_manager_different_configs(self):
        config1 = {"notifications": {"enabled": True}}
        config2 = {"notifications": {"enabled": False}}

        manager1 = get_cached_manager(config1)
        manager2 = get_cached_manager(config2)

        # Different config objects should return different managers
        assert manager1 is not manager2

    def test_clear_manager_cache(self):
        config = {"notifications": {"enabled": True}}

        manager1 = get_cached_manager(config)
        clear_manager_cache()
        manager2 = get_cached_manager(config)

        # After clearing, should get a new instance
        assert manager1 is not manager2


class TestNotificationEventValidation:
    """Tests for NotificationEvent enum and validation."""

    def test_get_valid_names(self):
        valid_names = NotificationEvent.get_valid_names()
        assert "pipeline_complete" in valid_names
        assert "test_failed" in valid_names
        assert "input_needed" in valid_names
        assert len(valid_names) == 3

    def test_validate_event_names_all_valid(self):
        invalid = NotificationEvent.validate_event_names([
            "pipeline_complete",
            "test_failed",
        ])
        assert invalid == []

    def test_validate_event_names_with_typo(self):
        invalid = NotificationEvent.validate_event_names([
            "pipeline_complete",
            "pipline_complete",  # Typo
        ])
        assert invalid == ["pipline_complete"]

    def test_validate_event_names_multiple_invalid(self):
        invalid = NotificationEvent.validate_event_names([
            "foo",
            "bar",
            "pipeline_complete",
        ])
        assert set(invalid) == {"foo", "bar"}

    def test_manager_raises_on_invalid_event_name(self):
        config = {
            "notifications": {
                "enabled": True,
                "events": ["pipeline_complete", "typo_event"],
            }
        }

        with pytest.raises(ValueError) as exc_info:
            NotificationManager(config)

        assert "typo_event" in str(exc_info.value)
        assert "Invalid" in str(exc_info.value)


class TestHeadlessNotifier:
    """Tests for HeadlessNotifier."""

    def test_is_always_available(self):
        notifier = HeadlessNotifier("test reason")
        assert notifier.is_available() is True

    def test_send_returns_skipped(self):
        notifier = HeadlessNotifier("CI environment")
        notification = Notification(title="Test", message="Hello")
        result = notifier.send(notification)

        assert result.success is True
        assert result.skipped is True
        assert "headless" in result.reason.lower()
        assert "CI environment" in result.reason


class TestHeadlessEnvironmentDetection:
    """Tests for is_headless_environment function."""

    def test_detects_ci_environment(self):
        with patch.dict("os.environ", {"CI": "true"}, clear=False):
            is_headless, reason = is_headless_environment()
            assert is_headless is True
            assert "CI" in reason

    def test_detects_github_actions(self):
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=False):
            is_headless, reason = is_headless_environment()
            assert is_headless is True
            assert "GITHUB_ACTIONS" in reason

    def test_detects_gitlab_ci(self):
        with patch.dict("os.environ", {"GITLAB_CI": "true"}, clear=False):
            is_headless, reason = is_headless_environment()
            assert is_headless is True
            assert "GITLAB_CI" in reason

    def test_detects_docker(self):
        with patch("os.path.exists", return_value=True):
            is_headless, reason = is_headless_environment()
            assert is_headless is True
            assert "Docker" in reason

    @patch("lion.notifications.detect_platform", return_value="linux")
    def test_detects_ssh_without_display_on_linux(self, mock_platform):
        env = {"SSH_CONNECTION": "192.168.1.1 12345 192.168.1.2 22"}
        with patch.dict("os.environ", env, clear=True):
            with patch("os.path.exists", return_value=False):  # No /.dockerenv
                is_headless, reason = is_headless_environment()
                assert is_headless is True
                assert "SSH" in reason

    @patch("lion.notifications.detect_platform", return_value="linux")
    def test_linux_without_display(self, mock_platform):
        # No DISPLAY, no WAYLAND_DISPLAY, no SSH, no CI
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.exists", return_value=False):  # No /.dockerenv
                is_headless, reason = is_headless_environment()
                assert is_headless is True
                assert "display" in reason.lower()

    @patch("lion.notifications.detect_platform", return_value="darwin")
    def test_macos_not_headless_by_default(self, mock_platform):
        # macOS without CI/Docker/SSH
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.exists", return_value=False):
                is_headless, reason = is_headless_environment()
                assert is_headless is False
                assert reason == ""

    def test_manager_uses_headless_notifier_in_ci(self):
        config = {"notifications": {"enabled": True}}

        with patch.dict("os.environ", {"CI": "true"}, clear=False):
            with patch("os.path.exists", return_value=False):  # No /.dockerenv
                manager = NotificationManager(config)
                assert manager.backend_name == "headless"
