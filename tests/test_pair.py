"""Tests for lion.functions.pair module."""

import time
import pytest
from unittest.mock import patch, MagicMock

from lion.functions.pair import (
    Finding,
    EyeResult,
    EyeConfig,
    _get_lead_interceptor,
    _is_non_actionable_review,
    _resolve_pair_mode,
    _EyeChecker,
    _parse_eyes,
    _build_eye_prompt,
    _check_eye,
    _check_eyes_parallel,
    _build_correction_prompt,
    _build_lead_prompt,
    execute_pair,
)
from lion.lenses import get_lens
from lion.interceptors.base import Chunk, InterceptorCapabilities, StreamInterceptor
from lion.parser import parse_lion_input


class MockInterceptor(StreamInterceptor):
    """Mock interceptor that returns predefined chunks."""

    name = "mock"

    def __init__(self, response_text="NONE", cwd="."):
        super().__init__(cwd=cwd)
        self._response_text = response_text
        self._started = False
        self._terminated = False

    def build_command(self, prompt, resume):
        return ["echo", "mock"]

    def parse_line(self, line, stream):
        return []

    def start(self, prompt, resume=False):
        self._started = True
        self._terminated = False

    def chunks(self, poll_interval=0.05):
        if self._terminated:
            return
        yield Chunk(
            source=self.name,
            text=self._response_text,
            raw=self._response_text,
            timestamp=time.time(),
            stream="stdout",
        )

    def terminate(self, hard=False):
        self._terminated = True

    def resume(self, correction):
        self._terminated = False
        self._started = True


class WaitCapableLeadInterceptor(MockInterceptor):
    """Lead interceptor that advertises wait-gate support."""

    def capabilities(self):
        return InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=True,
            supports_steer=False,
            supports_live_input=False,
        )


class TestParseEyes:
    @patch("lion.functions.pair.get_interceptor")
    def test_parse_simple_eyes(self, mock_get):
        mock_get.return_value = MockInterceptor()
        eyes = _parse_eyes("sec+arch", "claude", "/tmp")
        assert len(eyes) == 2
        assert eyes[0].lens_name == "sec"
        assert eyes[1].lens_name == "arch"
        assert eyes[0].provider == "claude"
        assert eyes[1].provider == "claude"

    @patch("lion.functions.pair.get_interceptor")
    def test_parse_cross_model_eyes(self, mock_get):
        mock_get.return_value = MockInterceptor()
        eyes = _parse_eyes("sec.gemini+arch.codex", "claude", "/tmp")
        assert len(eyes) == 2
        assert eyes[0].lens_name == "sec"
        assert eyes[0].provider == "gemini"
        assert eyes[1].lens_name == "arch"
        assert eyes[1].provider == "codex"

    @patch("lion.functions.pair.get_interceptor")
    def test_parse_single_eye(self, mock_get):
        mock_get.return_value = MockInterceptor()
        eyes = _parse_eyes("sec", "claude", "/tmp")
        assert len(eyes) == 1
        assert eyes[0].lens_name == "sec"

    @patch("lion.functions.pair.get_interceptor")
    def test_parse_mixed_default_and_override(self, mock_get):
        mock_get.return_value = MockInterceptor()
        eyes = _parse_eyes("sec+arch.gemini+perf", "claude", "/tmp")
        assert len(eyes) == 3
        assert eyes[0].provider == "claude"
        assert eyes[1].provider == "gemini"
        assert eyes[2].provider == "claude"

    def test_parse_unknown_lens_raises(self):
        with pytest.raises(ValueError, match="Unknown lens"):
            _parse_eyes("nonexistent", "claude", "/tmp")


class TestEyeConfigName:
    def test_name_property(self):
        lens = get_lens("sec")
        ec = EyeConfig(
            lens_name="sec", lens=lens,
            provider="gemini", interceptor=MockInterceptor(),
        )
        assert ec.name == "gemini:sec"


class TestBuildEyePrompt:
    def test_includes_lens_inject(self):
        lens = get_lens("sec")
        prompt = _build_eye_prompt(lens, "def login(): pass")
        assert "Security" in prompt or "SECURITY" in prompt
        assert "def login(): pass" in prompt

    def test_includes_none_instruction(self):
        lens = get_lens("arch")
        prompt = _build_eye_prompt(lens, "code here")
        assert "NONE" in prompt

    def test_truncates_long_code(self):
        lens = get_lens("perf")
        long_code = "x = 1\n" * 10000
        prompt = _build_eye_prompt(lens, long_code)
        # Should not include the full code
        assert len(prompt) < len(long_code)


class TestCheckEye:
    def test_clean_response(self):
        lens = get_lens("sec")
        eye = EyeConfig(
            lens_name="sec", lens=lens,
            provider="mock", interceptor=MockInterceptor("NONE"),
        )
        result = _check_eye(eye, "def hello(): pass")
        assert result.status == "clean"
        assert result.finding is None

    def test_finding_response(self):
        lens = get_lens("sec")
        eye = EyeConfig(
            lens_name="sec", lens=lens,
            provider="mock",
            interceptor=MockInterceptor("SQL injection in login query"),
        )
        result = _check_eye(eye, "db.execute('SELECT * FROM users WHERE id=' + id)")
        assert result.status == "finding"
        assert result.finding is not None
        assert isinstance(result.finding, Finding)
        assert result.finding.lens == "sec"
        assert "SQL injection" in result.finding.description
        assert result.finding.eye_name == "mock:sec"

    def test_none_in_longer_response(self):
        lens = get_lens("arch")
        eye = EyeConfig(
            lens_name="arch", lens=lens,
            provider="mock",
            interceptor=MockInterceptor("NONE - code looks clean"),
        )
        result = _check_eye(eye, "class Good: pass")
        assert result.status == "clean"
        assert result.finding is None

    def test_empty_response(self):
        """Empty or whitespace-only response should be status 'empty'."""
        lens = get_lens("sec")
        for empty in ["", " ", "  \n  ", "\t"]:
            eye = EyeConfig(
                lens_name="sec", lens=lens,
                provider="mock", interceptor=MockInterceptor(empty),
            )
            result = _check_eye(eye, "some code")
            assert result.status == "empty", f"Expected 'empty' for response {empty!r}"
            assert result.finding is None

    def test_non_actionable_context_request_filtered(self):
        lens = get_lens("sec")
        eye = EyeConfig(
            lens_name="sec",
            lens=lens,
            provider="mock",
            interceptor=MockInterceptor(
                "I need to see the complete code to provide a proper security review."
            ),
        )
        result = _check_eye(eye, "partial code")
        assert result.status == "clean"
        assert result.finding is None


class TestCheckEyesParallel:
    def test_empty_eyes(self):
        assert _check_eyes_parallel([], "code") == []

    def test_all_clean(self):
        lens = get_lens("sec")
        eyes = [
            EyeConfig("sec", lens, "mock", MockInterceptor("NONE")),
            EyeConfig("arch", get_lens("arch"), "mock", MockInterceptor("NONE")),
        ]
        assert _check_eyes_parallel(eyes, "code") == []

    def test_one_finding(self):
        eyes = [
            EyeConfig("sec", get_lens("sec"), "mock",
                       MockInterceptor("SQL injection found")),
            EyeConfig("arch", get_lens("arch"), "mock",
                       MockInterceptor("NONE")),
        ]
        findings = _check_eyes_parallel(eyes, "code")
        assert len(findings) == 1
        assert findings[0].lens == "sec"

    def test_multiple_findings(self):
        eyes = [
            EyeConfig("sec", get_lens("sec"), "mock",
                       MockInterceptor("Security issue")),
            EyeConfig("arch", get_lens("arch"), "mock",
                       MockInterceptor("Architecture problem")),
        ]
        findings = _check_eyes_parallel(eyes, "code")
        assert len(findings) == 2


class TestBuildCorrectionPrompt:
    def test_formats_findings(self):
        findings = [
            Finding(lens="sec", description="SQL injection", eye_name="g:sec", latency=1.0),
        ]
        prompt = _build_correction_prompt(findings)
        assert "[SEC]" in prompt
        assert "SQL injection" in prompt
        assert "Fix" in prompt

    def test_multiple_findings(self):
        findings = [
            Finding(lens="sec", description="Issue 1", eye_name="g:sec", latency=1.0),
            Finding(lens="arch", description="Issue 2", eye_name="c:arch", latency=0.5),
        ]
        prompt = _build_correction_prompt(findings)
        assert "[SEC]" in prompt
        assert "[ARCH]" in prompt


class TestBuildLeadPrompt:
    def test_no_plan(self):
        prompt = _build_lead_prompt("Build auth", {})
        assert "Build auth" in prompt
        assert "PLAN" not in prompt

    def test_with_plan(self):
        prompt = _build_lead_prompt("Build auth", {
            "plan": "1. Create user model\n2. Add login endpoint",
            "deliberation_summary": "Decided on JWT",
        })
        assert "Build auth" in prompt
        assert "PLAN" in prompt
        assert "Create user model" in prompt
        assert "JWT" in prompt


class TestParserPairSyntax:
    """Verify existing parser handles pair() syntax correctly."""

    def test_pair_basic(self):
        prompt, steps = parse_lion_input('"Build auth" -> pair(claude, eyes: sec+arch)')
        assert prompt == "Build auth"
        assert len(steps) == 1
        assert steps[0].function == "pair"
        assert steps[0].args == ["claude"]
        assert steps[0].kwargs == {"eyes": "sec+arch"}

    def test_pair_cross_model(self):
        prompt, steps = parse_lion_input(
            '"Build API" -> pair(claude.opus, eyes: sec.gemini+arch.haiku)'
        )
        assert steps[0].function == "pair"
        assert steps[0].args == ["claude.opus"]
        assert steps[0].kwargs == {"eyes": "sec.gemini+arch.haiku"}

    def test_pair_no_args(self):
        prompt, steps = parse_lion_input('"Build auth" -> pair()')
        assert steps[0].function == "pair"
        assert steps[0].args == []

    def test_pair_in_pipeline(self):
        prompt, steps = parse_lion_input(
            '"Build auth" -> pride(3) -> pair(claude, eyes: sec+arch)'
        )
        assert len(steps) == 2
        assert steps[0].function == "pride"
        assert steps[1].function == "pair"

    def test_pair_with_three_eyes(self):
        prompt, steps = parse_lion_input(
            '"Build X" -> pair(claude, eyes: sec+arch+perf)'
        )
        assert steps[0].kwargs == {"eyes": "sec+arch+perf"}


class TestPairRegistration:
    def test_pair_in_functions_registry(self):
        from lion.functions import FUNCTIONS
        assert "pair" in FUNCTIONS
        assert FUNCTIONS["pair"] is execute_pair


class TestEyeChecker:
    """Tests for _EyeChecker background thread with streaming findings."""

    def _make_eyes(self, *responses):
        """Create eye configs with mock interceptors returning given responses."""
        lenses = ["sec", "arch", "perf"]
        eyes = []
        for i, resp in enumerate(responses):
            lens_name = lenses[i % len(lenses)]
            eyes.append(EyeConfig(
                lens_name=lens_name,
                lens=get_lens(lens_name),
                provider="mock",
                interceptor=MockInterceptor(resp),
            ))
        return eyes

    def test_poll_returns_none_when_idle(self):
        """poll() returns None when no check has been submitted."""
        checker = _EyeChecker(self._make_eyes("NONE"))
        assert checker.poll() is None

    def test_not_busy_initially(self):
        checker = _EyeChecker(self._make_eyes("NONE"))
        assert not checker.busy

    def test_submit_streams_finding(self):
        """A finding arrives via poll() after eyes complete."""
        checker = _EyeChecker(self._make_eyes("SQL injection found"))
        checker.submit("some code")
        findings = checker.drain()
        assert len(findings) == 1
        assert "SQL injection" in findings[0].description

    def test_clean_eyes_produce_no_findings(self):
        """When all eyes return NONE, drain returns empty list."""
        checker = _EyeChecker(self._make_eyes("NONE", "NONE"))
        checker.submit("clean code")
        findings = checker.drain()
        assert findings == []

    def test_drain_collects_all_findings(self):
        """drain() waits and returns all findings as a list."""
        checker = _EyeChecker(self._make_eyes(
            "SQL injection", "Bad architecture"
        ))
        checker.submit("code")
        findings = checker.drain()
        assert len(findings) == 2

    def test_drain_empty_on_clean(self):
        checker = _EyeChecker(self._make_eyes("NONE"))
        checker.submit("code")
        findings = checker.drain()
        assert findings == []

    def test_not_busy_after_drain(self):
        """busy is False after all eyes complete."""
        checker = _EyeChecker(self._make_eyes("NONE"))
        checker.submit("code")
        checker.drain()
        assert not checker.busy

    def test_multiple_sequential_submits(self):
        """Can submit multiple checks sequentially."""
        checker = _EyeChecker(self._make_eyes("NONE"))

        checker.submit("code 1")
        findings1 = checker.drain()
        assert findings1 == []

        checker.submit("code 2")
        findings2 = checker.drain()
        assert findings2 == []


class TestExecutePair:
    """Integration tests for execute_pair with mocked interceptors."""

    def _make_step(self, args=None, kwargs=None):
        from lion.parser import PipelineStep
        return PipelineStep(
            function="pair",
            args=args or ["mock"],
            kwargs=kwargs or {"eyes": "sec+arch"},
        )

    def _make_memory(self):
        mem = MagicMock()
        mem.write = MagicMock()
        return mem

    def _make_config(self):
        return {
            "providers": {"default": "claude"},
            "pair": {"first_check_lines": 3, "check_every_n_lines": 5, "max_interrupts": 3},
        }

    @patch("lion.functions.pair.get_interceptor")
    @patch("lion.functions.pair._get_git_status_snapshot")
    @patch("lion.functions.pair._extract_files_changed")
    def test_basic_pair_no_interrupt(self, mock_files, mock_git, mock_get):
        """Lead finishes without any eye findings."""
        # Lead produces code in chunks (less than check_interval lines)
        lead = MockInterceptor("def hello():\n    return 'world'\n")
        # Eyes return clean
        eye_interceptor = MockInterceptor("NONE")
        mock_get.side_effect = lambda name, cwd=".": lead if "mock" in name else eye_interceptor
        mock_git.return_value = set()
        mock_files.return_value = []

        step = self._make_step()
        result = execute_pair(
            prompt="Write hello world",
            previous={},
            step=step,
            memory=self._make_memory(),
            config=self._make_config(),
            cwd="/tmp",
        )

        assert result["success"] is True
        assert "hello" in result["code"]
        assert result["interrupts"] == 0

    @patch("lion.functions.pair.get_interceptor")
    @patch("lion.functions.pair._get_git_status_snapshot")
    @patch("lion.functions.pair._extract_files_changed")
    def test_pair_return_format(self, mock_files, mock_git, mock_get):
        """Verify the return dict has all expected keys."""
        lead = MockInterceptor("code output")
        mock_get.return_value = lead
        mock_git.return_value = set()
        mock_files.return_value = []

        step = self._make_step()
        result = execute_pair(
            prompt="Build something",
            previous={},
            step=step,
            memory=self._make_memory(),
            config=self._make_config(),
            cwd="/tmp",
        )

        assert "success" in result
        assert "code" in result
        assert "content" in result
        assert "files_changed" in result
        assert "tokens_used" in result
        assert "interrupts" in result
        assert "findings" in result
        assert "wall_clock" in result

    @patch("lion.functions.pair.get_interceptor")
    @patch("lion.functions.pair._get_git_status_snapshot")
    @patch("lion.functions.pair._extract_files_changed")
    def test_pair_wait_mode_defers_findings(self, mock_files, mock_git, mock_get):
        """Wait mode should queue findings and apply after turn completion."""
        lead = WaitCapableLeadInterceptor("line1\nline2\nline3\nline4\n")
        eye = MockInterceptor("Critical issue")

        def _factory(name, cwd="."):
            if name.startswith("mock"):
                return eye
            return lead

        mock_get.side_effect = _factory
        mock_git.return_value = set()
        mock_files.return_value = []

        from lion.parser import PipelineStep
        step = PipelineStep(
            function="pair",
            args=["claude"],
            kwargs={"eyes": "sec.mock", "mode": "wait", "transport": "legacy"},
        )
        config = self._make_config()
        config["pair"]["max_final_rounds"] = 1

        result = execute_pair(
            prompt="Build x",
            previous={},
            step=step,
            memory=self._make_memory(),
            config=config,
            cwd="/tmp",
        )

        assert result["success"] is True
        assert result["interrupts"] >= 1
        assert result["mode"]["selected"] == "wait"


class TestPairModeResolution:
    def test_auto_prefers_steer_then_wait_then_interrupt(self):
        caps = InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=True,
            supports_steer=True,
            supports_live_input=False,
        )
        assert _resolve_pair_mode("auto", caps) == "steer"

        caps = InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=True,
            supports_steer=False,
            supports_live_input=False,
        )
        assert _resolve_pair_mode("auto", caps) == "wait"

        caps = InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=False,
            supports_steer=False,
            supports_live_input=False,
        )
        assert _resolve_pair_mode("auto", caps) == "interrupt"

    def test_explicit_steer_falls_back(self):
        caps = InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=True,
            supports_steer=False,
            supports_live_input=False,
        )
        assert _resolve_pair_mode("steer", caps) == "wait"

        caps = InterceptorCapabilities(
            supports_resume=True,
            supports_interrupt=True,
            supports_wait_gate=False,
            supports_steer=False,
            supports_live_input=False,
        )
        assert _resolve_pair_mode("steer", caps) == "interrupt"


class TestFindingFilters:
    def test_non_actionable_patterns(self):
        assert _is_non_actionable_review("Please share the complete code.")
        assert _is_non_actionable_review("Not enough context for review.")
        assert not _is_non_actionable_review("SQL injection in login query.")


class TestLeadTransportSelection:
    @patch("lion.functions.pair.CodexAppServerInterceptor")
    @patch("lion.functions.pair.get_interceptor")
    def test_codex_auto_prefers_app_server(self, mock_get, mock_codex_cls):
        mock_codex = MagicMock()
        mock_codex_cls.return_value = mock_codex
        selected = _get_lead_interceptor(
            lead_model="codex",
            cwd="/tmp",
            pair_config={"codex_transport": "auto"},
        )
        assert selected is mock_codex
        mock_get.assert_not_called()

    @patch("lion.functions.pair.ClaudeLiveInterceptor")
    @patch("lion.functions.pair.get_interceptor")
    def test_claude_auto_prefers_live(self, mock_get, mock_live_cls):
        mock_live = MagicMock()
        mock_live_cls.return_value = mock_live
        selected = _get_lead_interceptor(
            lead_model="claude",
            cwd="/tmp",
            pair_config={"claude_transport": "auto"},
        )
        assert selected is mock_live
        mock_get.assert_not_called()

    @patch("lion.functions.pair.GeminiACPInterceptor")
    @patch("lion.functions.pair.get_interceptor")
    def test_gemini_auto_prefers_acp(self, mock_get, mock_acp_cls):
        mock_acp = MagicMock()
        mock_acp_cls.return_value = mock_acp
        selected = _get_lead_interceptor(
            lead_model="gemini",
            cwd="/tmp",
            pair_config={"gemini_transport": "auto"},
        )
        assert selected is mock_acp
        mock_get.assert_not_called()

    @patch("lion.functions.pair.ClaudeLiveInterceptor", side_effect=RuntimeError("boom"))
    @patch("lion.functions.pair.get_interceptor")
    def test_transport_falls_back_to_legacy(self, mock_get, _mock_live_cls):
        legacy = MockInterceptor("x")
        mock_get.return_value = legacy
        selected = _get_lead_interceptor(
            lead_model="claude",
            cwd="/tmp",
            pair_config={"claude_transport": "auto"},
        )
        assert selected is legacy
