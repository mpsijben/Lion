"""Tests for the Textual TUI components."""

import threading
import time
import pytest

from lion.cli.tui import (
    CommandModeParser,
    PairControl,
    FileTracker,
    LionApp,
)
from lion.cli.tui_widgets import (
    StepState,
    FileChange,
    STATUS_ICONS,
)
from lion.cli.tui_bridge import (
    TUIBridge,
    PipelineStarted,
    PairStarted,
    StepStarted,
    StepCompleted,
    StepError,
    EyeFinding,
    PairInterrupt,
    EyeClean,
    PairCompleted,
    PairLeadChunk,
    PairCheckSubmitted,
    Notification,
    PhaseChanged,
)
from lion.display import Display
from lion.parser import PipelineStep


# -- CommandModeParser -------------------------------------------------------


class TestCommandModeParser:
    def test_inject(self):
        result = CommandModeParser.parse(":inject fix the bug")
        assert result.action == "inject"
        assert result.args["message"] == "fix the bug"

    def test_inject_quoted(self):
        result = CommandModeParser.parse(':inject "fix the bug"')
        assert result.action == "inject"
        assert result.args["message"] == "fix the bug"

    def test_pause(self):
        result = CommandModeParser.parse(":pause")
        assert result.action == "pause"

    def test_resume(self):
        result = CommandModeParser.parse(":resume")
        assert result.action == "resume"

    def test_abort(self):
        result = CommandModeParser.parse(":abort")
        assert result.action == "abort"

    def test_eyes_add(self):
        result = CommandModeParser.parse(":eyes add sec.gemini")
        assert result.action == "eyes_add"
        assert result.args["lens"] == "sec.gemini"

    def test_eyes_remove(self):
        result = CommandModeParser.parse(":eyes remove arch.codex")
        assert result.action == "eyes_remove"
        assert result.args["lens"] == "arch.codex"

    def test_eyes_list(self):
        result = CommandModeParser.parse(":eyes list")
        assert result.action == "eyes_list"

    def test_add_step_after(self):
        result = CommandModeParser.parse(":add review(^) after pair")
        assert result.action == "add_step"
        assert result.args["step"] == "review(^)"
        assert result.args["position"] == "after"
        assert result.args["target"] == "pair"

    def test_add_step_before(self):
        result = CommandModeParser.parse(":add test before pr")
        assert result.action == "add_step"
        assert result.args["step"] == "test"
        assert result.args["position"] == "before"
        assert result.args["target"] == "pr"

    def test_remove_step(self):
        result = CommandModeParser.parse(":remove test")
        assert result.action == "remove_step"
        assert result.args["target"] == "test"

    def test_empty(self):
        result = CommandModeParser.parse(":")
        assert result.action == "noop"

    def test_unknown(self):
        result = CommandModeParser.parse(":foobar")
        assert result.action == "unknown"
        assert result.args["raw"] == "foobar"

    def test_without_colon_prefix(self):
        result = CommandModeParser.parse("pause")
        assert result.action == "pause"


# -- PairControl -------------------------------------------------------------


class TestPairControl:
    def test_inject_and_pop(self):
        ctrl = PairControl()
        ctrl.inject("fix the bug")
        ctrl.inject("also add tests")
        items = ctrl.pop_injections()
        assert items == ["fix the bug", "also add tests"]
        assert ctrl.pop_injections() == []

    def test_inject_empty_ignored(self):
        ctrl = PairControl()
        ctrl.inject("")
        ctrl.inject("   ")
        assert ctrl.pop_injections() == []

    def test_add_remove_eyes(self):
        ctrl = PairControl()
        ctrl.add_eye("sec.gemini")
        ctrl.add_eye("arch.codex")
        ctrl.remove_eye("perf.claude")
        add, remove = ctrl.pop_eye_mutations()
        assert add == ["sec.gemini", "arch.codex"]
        assert remove == ["perf.claude"]
        assert ctrl.pop_eye_mutations() == ([], [])

    def test_pause_resume(self):
        ctrl = PairControl()
        assert not ctrl.paused
        ctrl.pause()
        assert ctrl.paused
        ctrl.resume()
        assert not ctrl.paused

    def test_abort(self):
        ctrl = PairControl()
        assert not ctrl.aborted
        ctrl.abort()
        assert ctrl.aborted

    def test_thread_safety(self):
        ctrl = PairControl()
        errors = []

        def writer():
            try:
                for i in range(100):
                    ctrl.inject(f"msg-{i}")
                    ctrl.add_eye(f"eye-{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    ctrl.pop_injections()
                    ctrl.pop_eye_mutations()
                    _ = ctrl.paused
                    _ = ctrl.aborted
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# -- StepState ---------------------------------------------------------------


class TestStepState:
    def test_defaults(self):
        step = StepState(name="pair(claude)")
        assert step.status == "waiting"
        assert step.elapsed == 0.0
        assert step.interrupts == 0
        assert step.lines == 0
        assert step.output == []
        assert step.eye_statuses == {}
        assert step.interrupt_log == []
        assert step.files_changed == []

    def test_status_icons(self):
        assert STATUS_ICONS["waiting"] == "\u25cb"
        assert STATUS_ICONS["active"] == "\u25cf"
        assert STATUS_ICONS["done"] == "\u2705"
        assert STATUS_ICONS["failed"] == "\u274c"
        assert STATUS_ICONS["paused"] == "\u23f8"
        assert STATUS_ICONS["aborted"] == "\u23f9"


# -- FileChange --------------------------------------------------------------


class TestFileChange:
    def test_defaults(self):
        fc = FileChange(path="src/main.py", status="modified")
        assert fc.lines_added == 0
        assert fc.lines_removed == 0

    def test_with_stats(self):
        fc = FileChange(path="src/main.py", status="modified", lines_added=10, lines_removed=3)
        assert fc.lines_added == 10
        assert fc.lines_removed == 3


# -- TUIBridge ---------------------------------------------------------------


class TestTUIBridge:
    def test_install_and_uninstall(self):
        """Bridge install patches Display, uninstall restores originals."""

        class FakeApp:
            def __init__(self):
                self.messages = []

            def post_message(self, msg):
                self.messages.append(msg)

        app = FakeApp()
        bridge = TUIBridge(app)

        # Save originals
        original_pair_start = Display.pair_start

        bridge.install()

        # Display.pair_start should now post a message
        Display.pair_start("claude", ["sec.gemini", "arch.codex"])
        assert len(app.messages) == 1
        assert isinstance(app.messages[0], PairStarted)
        assert app.messages[0].lead_name == "claude"
        assert app.messages[0].eye_labels == ["sec.gemini", "arch.codex"]

        bridge.uninstall()

        # Display.pair_start should be restored
        assert Display.pair_start == original_pair_start

    def test_bridge_routes_pair_finding(self):
        class FakeApp:
            def __init__(self):
                self.messages = []

            def post_message(self, msg):
                self.messages.append(msg)

        app = FakeApp()
        bridge = TUIBridge(app)
        bridge.install()

        try:
            Display.pair_finding("gemini:sec", "security", "SQL injection risk", 2.3)
            assert len(app.messages) == 1
            msg = app.messages[0]
            assert isinstance(msg, EyeFinding)
            assert msg.eye_name == "gemini:sec"
            assert msg.lens == "security"
            assert msg.description == "SQL injection risk"
            assert msg.latency == 2.3
        finally:
            bridge.uninstall()

    def test_bridge_routes_step_events(self):
        class FakeApp:
            def __init__(self):
                self.messages = []

            def post_message(self, msg):
                self.messages.append(msg)

        app = FakeApp()
        bridge = TUIBridge(app)
        bridge.install()

        try:
            step = PipelineStep(function="pair", args=["claude"])
            Display.step_start(1, 3, step)
            Display.step_complete("pair", {"success": True})
            Display.step_error("test", "assertion failed")

            assert len(app.messages) == 3
            assert isinstance(app.messages[0], StepStarted)
            assert isinstance(app.messages[1], StepCompleted)
            assert isinstance(app.messages[2], StepError)
            assert app.messages[2].error == "assertion failed"
        finally:
            bridge.uninstall()

    def test_bridge_routes_notifications(self):
        class FakeApp:
            def __init__(self):
                self.messages = []

            def post_message(self, msg):
                self.messages.append(msg)

        app = FakeApp()
        bridge = TUIBridge(app)
        bridge.install()

        try:
            Display.notify("something happened")
            assert len(app.messages) == 1
            assert isinstance(app.messages[0], Notification)
            assert app.messages[0].text == "something happened"
        finally:
            bridge.uninstall()


# -- LionApp step label generation ------------------------------------------


class TestLionAppStepLabel:
    def test_simple_function(self):
        step = PipelineStep(function="test")
        assert LionApp._step_label(step) == "test"

    def test_function_with_parens(self):
        step = PipelineStep(function="pair")
        assert LionApp._step_label(step) == "pair()"

    def test_function_with_args(self):
        step = PipelineStep(function="pride", args=[3])
        assert LionApp._step_label(step) == "pride(3)"

    def test_function_with_kwargs(self):
        step = PipelineStep(function="pair", kwargs={"eyes": "sec+arch"})
        assert LionApp._step_label(step) == "pair(eyes: sec+arch)"

    def test_function_with_args_and_kwargs(self):
        step = PipelineStep(function="pair", args=["claude"], kwargs={"eyes": "sec+arch"})
        assert LionApp._step_label(step) == "pair(claude, eyes: sec+arch)"
