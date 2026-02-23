"""Desktop notification system for Lion pipeline events.

Provides cross-platform notifications using:
- macOS: osascript (native)
- Linux: notify-send (native)
- Fallback: plyer (if available)

Usage:
    from lion.notifications import NotificationManager

    manager = NotificationManager(config)
    result = manager.notify_pipeline_complete("Build feature X", success=True)
    if not result.success:
        print(f"Notification failed: {result.error}")
"""

import platform
import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NotificationEvent(Enum):
    """Notification event types that can be enabled/disabled in config.

    Use validate_event_names() to check config values against this enum.
    """
    PIPELINE_COMPLETE = "pipeline_complete"
    TEST_FAILED = "test_failed"
    INPUT_NEEDED = "input_needed"

    @classmethod
    def get_valid_names(cls) -> set[str]:
        """Get the set of valid event name strings."""
        return {e.value for e in cls}

    @classmethod
    def validate_event_names(cls, event_names: list[str]) -> list[str]:
        """Validate a list of event names against the enum.

        Args:
            event_names: List of event name strings from config

        Returns:
            List of invalid event names (empty if all valid)
        """
        valid_names = cls.get_valid_names()
        return [name for name in event_names if name not in valid_names]


class NotificationUrgency(Enum):
    """Urgency levels for notifications."""
    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


@dataclass
class Notification:
    """A notification to be displayed."""
    title: str
    message: str
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    sound: Optional[bool] = None  # None means use config default
    event_type: Optional[NotificationEvent] = None


@dataclass
class NotificationResult:
    """Result of a notification attempt with error details for debugging."""
    success: bool
    skipped: bool = False
    error: Optional[str] = None
    backend: Optional[str] = None
    reason: Optional[str] = None  # Why it was skipped/failed

    @classmethod
    def sent(cls, backend: str) -> "NotificationResult":
        """Create a successful result."""
        return cls(success=True, backend=backend)

    @classmethod
    def skipped_disabled(cls, reason: str = "event type disabled") -> "NotificationResult":
        """Create a skipped result (intentionally not sent)."""
        return cls(success=True, skipped=True, reason=reason)

    @classmethod
    def skipped_no_backend(cls) -> "NotificationResult":
        """Create a result indicating no backend is available.

        This is a failure condition - notifications were requested but
        cannot be delivered due to missing system capabilities.
        """
        return cls(
            success=False,
            skipped=False,
            error="No notification backend available on this system",
            reason="no_backend",
        )

    @classmethod
    def failed(cls, error: str, backend: Optional[str] = None) -> "NotificationResult":
        """Create a failed result with error details."""
        return cls(success=False, error=error, backend=backend)


def detect_platform() -> str:
    """Detect the current platform.

    Returns:
        One of: 'darwin' (macOS), 'linux', 'windows', or 'unknown'
    """
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    return "unknown"


def is_command_available(command: str) -> bool:
    """Check if a command is available on the system."""
    return shutil.which(command) is not None


def is_headless_environment() -> tuple[bool, str]:
    """Detect if running in a headless environment where notifications may fail.

    Checks for:
    - SSH sessions (SSH_CONNECTION or SSH_TTY environment variables)
    - Missing DISPLAY on Linux (no X11/Wayland session)
    - CI/CD environments (CI, GITHUB_ACTIONS, GITLAB_CI, etc.)
    - Docker containers (/.dockerenv file)
    - Screen/tmux without display forwarding

    Returns:
        Tuple of (is_headless: bool, reason: str).
        If is_headless is True, reason explains why.
    """
    import os

    # Check for CI/CD environments
    ci_indicators = [
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "TRAVIS",
        "CIRCLECI",
        "BUILDKITE",
        "CODEBUILD_BUILD_ID",
    ]
    for indicator in ci_indicators:
        if os.environ.get(indicator):
            return True, f"CI environment detected ({indicator})"

    # Check for Docker container
    if os.path.exists("/.dockerenv"):
        return True, "Docker container detected"

    # Check for SSH session
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        # SSH session - check if X11 forwarding is available
        current_platform = detect_platform()
        if current_platform == "linux":
            # On Linux, check if DISPLAY is set (X11 forwarding)
            if not os.environ.get("DISPLAY"):
                return True, "SSH session without X11 forwarding"
        elif current_platform == "darwin":
            # On macOS, SSH sessions typically can still show notifications
            # via osascript if the user is logged into the GUI
            pass

    # Check for missing display on Linux
    current_platform = detect_platform()
    if current_platform == "linux":
        display = os.environ.get("DISPLAY")
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        if not display and not wayland_display:
            return True, "No display available (DISPLAY and WAYLAND_DISPLAY not set)"

    return False, ""


class Notifier(ABC):
    """Abstract base class for notification backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this notifier backend."""
        pass

    @abstractmethod
    def send(self, notification: Notification) -> NotificationResult:
        """Send a notification.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult with success status and error details if failed
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this notifier backend is available on the system."""
        pass


class MacOSNotifier(Notifier):
    """macOS notification backend using osascript."""

    @property
    def name(self) -> str:
        return "macos-osascript"

    def is_available(self) -> bool:
        """Check if osascript is available (always true on macOS)."""
        return detect_platform() == "darwin" and is_command_available("osascript")

    def send(self, notification: Notification) -> NotificationResult:
        """Send notification using osascript.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult with success status and error details
        """
        if not self.is_available():
            return NotificationResult.failed(
                "osascript not available on this platform",
                backend=self.name
            )

        # Escape quotes in title and message
        title = notification.title.replace('"', '\\"')
        message = notification.message.replace('"', '\\"')

        # Build the AppleScript command
        script = f'display notification "{message}" with title "{title}"'

        # Add sound if requested
        if notification.sound:
            script += ' sound name "default"'

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return NotificationResult.sent(self.name)
        except subprocess.TimeoutExpired:
            return NotificationResult.failed(
                "osascript command timed out after 5 seconds",
                backend=self.name
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode() if e.stderr else "unknown error"
            return NotificationResult.failed(
                f"osascript failed: {stderr}",
                backend=self.name
            )
        except OSError as e:
            return NotificationResult.failed(
                f"Failed to execute osascript: {e}",
                backend=self.name
            )


class LinuxNotifier(Notifier):
    """Linux notification backend using notify-send."""

    # Map urgency levels to notify-send values
    URGENCY_MAP = {
        NotificationUrgency.LOW: "low",
        NotificationUrgency.NORMAL: "normal",
        NotificationUrgency.CRITICAL: "critical",
    }

    @property
    def name(self) -> str:
        return "linux-notify-send"

    def is_available(self) -> bool:
        """Check if notify-send is available."""
        return detect_platform() == "linux" and is_command_available("notify-send")

    def send(self, notification: Notification) -> NotificationResult:
        """Send notification using notify-send.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult with success status and error details
        """
        if not self.is_available():
            return NotificationResult.failed(
                "notify-send not available on this platform",
                backend=self.name
            )

        urgency = self.URGENCY_MAP.get(notification.urgency, "normal")

        cmd = [
            "notify-send",
            "--urgency", urgency,
            "--app-name", "Lion",
            notification.title,
            notification.message,
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=5,
                check=True,
            )
            return NotificationResult.sent(self.name)
        except subprocess.TimeoutExpired:
            return NotificationResult.failed(
                "notify-send command timed out after 5 seconds",
                backend=self.name
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode() if e.stderr else "unknown error"
            return NotificationResult.failed(
                f"notify-send failed: {stderr}",
                backend=self.name
            )
        except OSError as e:
            return NotificationResult.failed(
                f"Failed to execute notify-send: {e}",
                backend=self.name
            )


class PlyerNotifier(Notifier):
    """Cross-platform notification backend using plyer library.

    Plyer provides native notifications on Windows, macOS, and Linux.
    On Windows, this is the primary notification method.
    """

    def __init__(self):
        self._plyer = None
        self._checked = False
        self._import_error: Optional[str] = None

    @property
    def name(self) -> str:
        return "plyer"

    def _load_plyer(self):
        """Lazily load plyer to avoid import errors if not installed."""
        if self._checked:
            return self._plyer

        self._checked = True
        try:
            from plyer import notification as plyer_notification
            self._plyer = plyer_notification
        except ImportError as e:
            self._plyer = None
            self._import_error = str(e)

        return self._plyer

    def is_available(self) -> bool:
        """Check if plyer is available."""
        return self._load_plyer() is not None

    def send(self, notification: Notification) -> NotificationResult:
        """Send notification using plyer.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult with success status and error details
        """
        plyer = self._load_plyer()
        if plyer is None:
            error_msg = "plyer library not installed"
            if self._import_error:
                error_msg += f": {self._import_error}"
            return NotificationResult.failed(error_msg, backend=self.name)

        try:
            plyer.notify(
                title=notification.title,
                message=notification.message,
                app_name="Lion",
                timeout=10,
            )
            return NotificationResult.sent(self.name)
        except Exception as e:
            return NotificationResult.failed(
                f"plyer notification failed: {e}",
                backend=self.name
            )


class WindowsNotifier(Notifier):
    """Windows notification backend using plyer as the primary method.

    On Windows, we use plyer which wraps the Windows toast notification API.
    This is the recommended approach for Windows notifications.
    """

    def __init__(self):
        self._plyer_notifier = PlyerNotifier()

    @property
    def name(self) -> str:
        return "windows-plyer"

    def is_available(self) -> bool:
        """Check if we're on Windows and plyer is available."""
        return detect_platform() == "windows" and self._plyer_notifier.is_available()

    def send(self, notification: Notification) -> NotificationResult:
        """Send notification using plyer on Windows.

        Args:
            notification: The notification to send

        Returns:
            NotificationResult with success status and error details
        """
        if not self.is_available():
            if detect_platform() != "windows":
                return NotificationResult.failed(
                    "WindowsNotifier is only available on Windows",
                    backend=self.name
                )
            return NotificationResult.failed(
                "plyer library not installed - install with: pip install plyer",
                backend=self.name
            )

        result = self._plyer_notifier.send(notification)
        # Update the backend name to reflect Windows-specific usage
        if result.success:
            return NotificationResult.sent(self.name)
        return NotificationResult.failed(result.error or "Unknown error", backend=self.name)


class DisabledNotifier(Notifier):
    """Notifier for when notifications are intentionally disabled via config."""

    @property
    def name(self) -> str:
        return "disabled"

    def is_available(self) -> bool:
        return True

    def send(self, notification: Notification) -> NotificationResult:
        return NotificationResult.skipped_disabled("notifications disabled in config")


class HeadlessNotifier(Notifier):
    """Notifier for headless environments (CI, SSH, Docker, no display).

    Instead of failing silently or hanging waiting for a display, this
    gracefully skips the notification and returns a success result with
    a note explaining why it was skipped.
    """

    def __init__(self, reason: str):
        self._reason = reason

    @property
    def name(self) -> str:
        return "headless"

    def is_available(self) -> bool:
        return True

    def send(self, notification: Notification) -> NotificationResult:
        # In headless mode, we skip the notification but don't consider it an error
        return NotificationResult.skipped_disabled(
            f"headless environment: {self._reason}"
        )


class NoBackendNotifier(Notifier):
    """Notifier for when no backend is available on the system.

    This represents a failure condition - the user wants notifications
    but the system cannot deliver them.
    """

    @property
    def name(self) -> str:
        return "no_backend"

    def is_available(self) -> bool:
        return False

    def send(self, notification: Notification) -> NotificationResult:
        return NotificationResult.skipped_no_backend()


class NotificationManager:
    """Facade for sending notifications with config-based filtering.

    Automatically selects the appropriate backend based on platform
    and sends notifications only for enabled event types.

    Each instance is independent - there is no global singleton.
    Create a new manager for each context that needs different settings.
    """

    def __init__(self, config: dict):
        """Initialize the notification manager.

        Args:
            config: Lion configuration dict, expects [notifications] section

        Raises:
            ValueError: If config contains invalid event names (typos, etc.)
                This catches configuration errors early rather than silently
                ignoring misspelled event names.
        """
        self._raw_config = config
        self._notif_config = config.get("notifications", {})
        self._enabled = self._notif_config.get("enabled", True)
        self._sound = self._notif_config.get("sound", True)

        # Get events from config with defaults
        event_list = self._notif_config.get("events", [
            "pipeline_complete",
            "test_failed",
            "input_needed",
        ])

        # Validate event names against the enum to catch typos early
        invalid_events = NotificationEvent.validate_event_names(event_list)
        if invalid_events:
            valid_names = sorted(NotificationEvent.get_valid_names())
            raise ValueError(
                f"Invalid notification event name(s) in config: {invalid_events}. "
                f"Valid event names are: {valid_names}"
            )

        self._events = set(event_list)

        # Auto-detect and select the appropriate notifier
        self._notifier = self._select_notifier()

    def _select_notifier(self) -> Notifier:
        """Select the best available notifier for the current platform.

        Checks for headless environments first (CI, SSH, Docker, no display)
        to avoid hanging or failing mysteriously when notifications can't
        be delivered.
        """
        if not self._enabled:
            return DisabledNotifier()

        # Check for headless environment BEFORE trying any notifiers
        # This prevents hanging on display access in SSH/CI/Docker
        is_headless, headless_reason = is_headless_environment()
        if is_headless:
            return HeadlessNotifier(headless_reason)

        current_platform = detect_platform()

        # Try platform-specific notifiers first
        if current_platform == "darwin":
            notifier = MacOSNotifier()
            if notifier.is_available():
                return notifier

        if current_platform == "linux":
            notifier = LinuxNotifier()
            if notifier.is_available():
                return notifier

        if current_platform == "windows":
            notifier = WindowsNotifier()
            if notifier.is_available():
                return notifier

        # Fall back to plyer for any platform
        notifier = PlyerNotifier()
        if notifier.is_available():
            return notifier

        # No notifier available - this is a failure condition
        return NoBackendNotifier()

    def _is_event_enabled(self, event: NotificationEvent) -> bool:
        """Check if a notification event type is enabled."""
        return event.value in self._events

    @property
    def backend_name(self) -> str:
        """Return the name of the active notification backend."""
        return self._notifier.name

    @property
    def is_enabled(self) -> bool:
        """Return whether notifications are enabled."""
        return self._enabled

    def send(self, notification: Notification) -> NotificationResult:
        """Send a notification if enabled.

        Args:
            notification: The notification to send (not mutated)

        Returns:
            NotificationResult with success status and error details if failed
        """
        # Check if this event type is enabled
        if notification.event_type and not self._is_event_enabled(notification.event_type):
            return NotificationResult.skipped_disabled()

        # Determine sound setting: use notification's explicit setting if provided,
        # otherwise fall back to config default
        sound = notification.sound if notification.sound is not None else self._sound

        # Create a copy with sound setting applied (don't mutate input)
        notification_to_send = Notification(
            title=notification.title,
            message=notification.message,
            urgency=notification.urgency,
            sound=sound,
            event_type=notification.event_type,
        )

        return self._notifier.send(notification_to_send)

    def notify_pipeline_complete(
        self,
        prompt: str,
        success: bool = True,
        duration: Optional[float] = None,
        steps_completed: int = 0,
        total_steps: int = 0,
    ) -> NotificationResult:
        """Send a pipeline completion notification.

        Args:
            prompt: The pipeline prompt (used for title)
            success: Whether the pipeline completed successfully
            duration: Pipeline duration in seconds
            steps_completed: Number of steps completed
            total_steps: Total number of steps

        Returns:
            NotificationResult with success status and error details if failed
        """
        # Build title with truncated prompt
        prompt_preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
        title = f"Lion: {prompt_preview}"

        # Build message
        if success:
            status = "Pipeline completed successfully"
        else:
            status = "Pipeline completed with errors"

        parts = [status]
        if total_steps > 0:
            parts.append(f"Steps: {steps_completed}/{total_steps}")
        if duration is not None:
            parts.append(f"Duration: {duration:.1f}s")

        message = " - ".join(parts)

        notification = Notification(
            title=title,
            message=message,
            urgency=NotificationUrgency.NORMAL if success else NotificationUrgency.CRITICAL,
            event_type=NotificationEvent.PIPELINE_COMPLETE,
        )

        return self.send(notification)

    def notify_test_failed(
        self,
        test_name: str,
        error_message: str,
        failed_count: int = 0,
    ) -> NotificationResult:
        """Send a test failure notification.

        Args:
            test_name: Name of the failing test or test file
            error_message: Error message or summary
            failed_count: Number of failed tests

        Returns:
            NotificationResult with success status and error details if failed
        """
        title = f"Lion: Test Failed - {test_name}"

        if failed_count > 0:
            message = f"{failed_count} test(s) failed: {error_message[:100]}"
        else:
            message = error_message[:150]

        notification = Notification(
            title=title,
            message=message,
            urgency=NotificationUrgency.CRITICAL,
            event_type=NotificationEvent.TEST_FAILED,
        )

        return self.send(notification)

    def notify_input_needed(
        self,
        reason: str,
        context: Optional[str] = None,
    ) -> NotificationResult:
        """Send a notification that user input is needed.

        Args:
            reason: Why input is needed
            context: Additional context

        Returns:
            NotificationResult with success status and error details if failed
        """
        title = "Lion: Input Needed"

        if context:
            message = f"{reason} - {context[:100]}"
        else:
            message = reason

        notification = Notification(
            title=title,
            message=message,
            urgency=NotificationUrgency.NORMAL,
            event_type=NotificationEvent.INPUT_NEEDED,
        )

        return self.send(notification)


# Cache for notification managers to avoid repeated initialization
# Key is id(config), value is (config_id, manager)
# We use id() because configs are typically long-lived dict objects
_manager_cache: dict[int, NotificationManager] = {}


def create_notification_manager(config: Optional[dict] = None) -> NotificationManager:
    """Create a new NotificationManager with the given config.

    This is the preferred way to create managers - each call creates
    a fresh instance that respects the provided config.

    Args:
        config: Lion configuration dict. If None, uses default settings.

    Returns:
        A new NotificationManager instance
    """
    return NotificationManager(config or {})


def get_cached_manager(config: Optional[dict] = None) -> NotificationManager:
    """Get a cached NotificationManager for the given config.

    This function caches managers by config object identity (id()) to avoid
    repeatedly re-detecting platform and re-parsing config for the same
    configuration. Use this in convenience functions for better performance.

    Args:
        config: Lion configuration dict. If None, uses default settings.

    Returns:
        A cached or new NotificationManager instance
    """
    if config is None:
        config = {}

    config_id = id(config)
    if config_id not in _manager_cache:
        _manager_cache[config_id] = NotificationManager(config)
    return _manager_cache[config_id]


def clear_manager_cache() -> None:
    """Clear the manager cache. Useful for testing."""
    _manager_cache.clear()


def notify_pipeline_complete(
    prompt: str,
    success: bool = True,
    duration: Optional[float] = None,
    steps_completed: int = 0,
    total_steps: int = 0,
    config: Optional[dict] = None,
) -> NotificationResult:
    """Convenience function to send pipeline completion notification.

    Uses a cached NotificationManager to avoid repeated initialization
    overhead when the same config object is used across multiple calls.

    Args:
        prompt: The pipeline prompt
        success: Whether the pipeline completed successfully
        duration: Pipeline duration in seconds
        steps_completed: Number of steps completed
        total_steps: Total number of steps
        config: Config dict (required for proper behavior)

    Returns:
        NotificationResult with success status and error details if failed
    """
    manager = get_cached_manager(config)
    return manager.notify_pipeline_complete(
        prompt=prompt,
        success=success,
        duration=duration,
        steps_completed=steps_completed,
        total_steps=total_steps,
    )


def notify_test_failed(
    test_name: str,
    error_message: str,
    failed_count: int = 0,
    config: Optional[dict] = None,
) -> NotificationResult:
    """Convenience function to send test failure notification.

    Uses a cached NotificationManager to avoid repeated initialization
    overhead when the same config object is used across multiple calls.

    Args:
        test_name: Name of the failing test
        error_message: Error message
        failed_count: Number of failed tests
        config: Config dict (required for proper behavior)

    Returns:
        NotificationResult with success status and error details if failed
    """
    manager = get_cached_manager(config)
    return manager.notify_test_failed(
        test_name=test_name,
        error_message=error_message,
        failed_count=failed_count,
    )


def notify_input_needed(
    reason: str,
    context: Optional[str] = None,
    config: Optional[dict] = None,
) -> NotificationResult:
    """Convenience function to send input needed notification.

    Uses a cached NotificationManager to avoid repeated initialization
    overhead when the same config object is used across multiple calls.

    Args:
        reason: Why input is needed
        context: Additional context
        config: Config dict (required for proper behavior)

    Returns:
        NotificationResult with success status and error details if failed
    """
    manager = get_cached_manager(config)
    return manager.notify_input_needed(reason=reason, context=context)
