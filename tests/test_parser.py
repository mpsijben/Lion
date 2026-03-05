"""Tests for lion.parser module."""

import pytest
from lion.parser import (
    parse_lion_input,
    PipelineStep,
    _split_prompt_and_pipeline,
    _parse_step,
    _split_args,
    _parse_value,
)


class TestParseLionInput:
    """Tests for parse_lion_input function."""

    def test_simple_prompt_no_pipeline(self):
        """Test parsing a simple prompt without pipeline."""
        prompt, steps = parse_lion_input("Build a feature")
        assert prompt == "Build a feature"
        assert steps == []

    def test_quoted_prompt_no_pipeline(self):
        """Test parsing a quoted prompt without pipeline."""
        prompt, steps = parse_lion_input('"Build a feature"')
        assert prompt == "Build a feature"
        assert steps == []

    def test_single_quoted_prompt(self):
        """Test parsing a single-quoted prompt."""
        prompt, steps = parse_lion_input("'Build a feature'")
        assert prompt == "Build a feature"
        assert steps == []

    def test_prompt_with_single_pipeline_step(self):
        """Test parsing prompt with one pipeline step."""
        prompt, steps = parse_lion_input('"Build a feature" -> pride(3)')
        assert prompt == "Build a feature"
        assert len(steps) == 1
        assert steps[0].function == "pride"
        assert steps[0].args == [3]

    def test_prompt_with_multiple_pipeline_steps(self):
        """Test parsing prompt with multiple pipeline steps."""
        prompt, steps = parse_lion_input('"Build X" -> pride(3) -> review() -> test()')
        assert prompt == "Build X"
        assert len(steps) == 3
        assert steps[0].function == "pride"
        assert steps[0].args == [3]
        assert steps[1].function == "review"
        assert steps[1].args == []
        assert steps[2].function == "test"
        assert steps[2].args == []

    def test_pipeline_step_without_parens(self):
        """Test parsing pipeline step without parentheses."""
        prompt, steps = parse_lion_input('"Fix bug" -> review')
        assert prompt == "Fix bug"
        assert len(steps) == 1
        assert steps[0].function == "review"
        assert steps[0].args == []

    def test_pipeline_step_with_string_args(self):
        """Test parsing pipeline step with string arguments."""
        prompt, steps = parse_lion_input('"Build X" -> pride(claude, gemini)')
        assert prompt == "Build X"
        assert len(steps) == 1
        assert steps[0].function == "pride"
        assert steps[0].args == ["claude", "gemini"]

    def test_fuse_with_agent_count(self):
        """Test parsing fuse with numeric agent count."""
        prompt, steps = parse_lion_input('"Design auth" -> fuse(3)')
        assert prompt == "Design auth"
        assert len(steps) == 1
        assert steps[0].function == "fuse"
        assert steps[0].args == [3]

    def test_fuse_with_explicit_providers(self):
        """Test parsing fuse with explicit providers."""
        prompt, steps = parse_lion_input('"Design auth" -> fuse(claude, gemini, codex)')
        assert prompt == "Design auth"
        assert len(steps) == 1
        assert steps[0].function == "fuse"
        assert steps[0].args == ["claude", "gemini", "codex"]

    def test_pipeline_step_with_mixed_args(self):
        """Test parsing pipeline step with mixed argument types."""
        prompt, steps = parse_lion_input('"Build X" -> pr(feature/test)')
        assert prompt == "Build X"
        assert len(steps) == 1
        assert steps[0].function == "pr"
        assert steps[0].args == ["feature/test"]

    def test_unquoted_prompt_with_pipeline(self):
        """Test parsing unquoted prompt with pipeline."""
        prompt, steps = parse_lion_input("Build a feature -> pride(3)")
        assert prompt == "Build a feature"
        assert len(steps) == 1
        assert steps[0].function == "pride"
        assert steps[0].args == [3]

    def test_prompt_with_arrow_in_text(self):
        """Test prompt containing arrow that's not a pipeline separator."""
        # When quoted, arrow inside should be preserved
        prompt, steps = parse_lion_input('"Implement A -> B transformation" -> review()')
        assert prompt == "Implement A -> B transformation"
        assert len(steps) == 1
        assert steps[0].function == "review"

    def test_empty_input(self):
        """Test parsing empty input."""
        prompt, steps = parse_lion_input("")
        assert prompt == ""
        assert steps == []

    def test_whitespace_only(self):
        """Test parsing whitespace-only input."""
        prompt, steps = parse_lion_input("   ")
        assert prompt == ""
        assert steps == []

    def test_pipeline_with_nofix_arg(self):
        """Test parsing test step with nofix argument."""
        prompt, steps = parse_lion_input('"Fix tests" -> test(nofix)')
        assert prompt == "Fix tests"
        assert len(steps) == 1
        assert steps[0].function == "test"
        assert steps[0].args == ["nofix"]


class TestSplitPromptAndPipeline:
    """Tests for _split_prompt_and_pipeline function."""

    def test_double_quoted_prompt(self):
        """Test splitting double-quoted prompt."""
        prompt, pipeline = _split_prompt_and_pipeline('"Build feature" -> review()')
        assert prompt == "Build feature"
        assert pipeline == "review()"

    def test_single_quoted_prompt(self):
        """Test splitting single-quoted prompt."""
        prompt, pipeline = _split_prompt_and_pipeline("'Build feature' -> review()")
        assert prompt == "Build feature"
        assert pipeline == "review()"

    def test_no_pipeline(self):
        """Test splitting prompt with no pipeline."""
        prompt, pipeline = _split_prompt_and_pipeline('"Just a prompt"')
        assert prompt == "Just a prompt"
        assert pipeline == ""

    def test_unquoted_prompt(self):
        """Test splitting unquoted prompt."""
        prompt, pipeline = _split_prompt_and_pipeline("Build feature -> review()")
        assert prompt == "Build feature"
        assert pipeline == "review()"

    def test_unquoted_no_pipeline(self):
        """Test splitting unquoted prompt with no pipeline."""
        prompt, pipeline = _split_prompt_and_pipeline("Just a prompt")
        assert prompt == "Just a prompt"
        assert pipeline == ""


class TestParseStep:
    """Tests for _parse_step function."""

    def test_function_without_args(self):
        """Test parsing function without arguments."""
        step = _parse_step("review", {})
        assert step.function == "review"
        assert step.args == []
        assert step.kwargs == {}

    def test_function_with_empty_parens(self):
        """Test parsing function with empty parentheses."""
        step = _parse_step("review()", {})
        assert step.function == "review"
        assert step.args == []

    def test_function_with_integer_arg(self):
        """Test parsing function with integer argument."""
        step = _parse_step("pride(3)", {})
        assert step.function == "pride"
        assert step.args == [3]

    def test_function_with_multiple_args(self):
        """Test parsing function with multiple arguments."""
        step = _parse_step("pride(claude, gemini, codex)", {})
        assert step.function == "pride"
        assert step.args == ["claude", "gemini", "codex"]

    def test_function_with_kwargs(self):
        """Test parsing function with keyword arguments."""
        step = _parse_step("pride(n:3)", {})
        assert step.function == "pride"
        assert step.kwargs == {"n": 3}

    def test_saved_pattern(self):
        """Test parsing saved pattern."""
        config = {
            "patterns": {
                "quick": "review() -> test()",
            }
        }
        step = _parse_step("quick", config)
        assert step.function == "__pattern__"
        assert step.kwargs == {"name": "quick"}
        # The args should contain expanded steps
        assert len(step.args) == 2


class TestSplitArgs:
    """Tests for _split_args function."""

    def test_simple_args(self):
        """Test splitting simple arguments."""
        args = _split_args("a, b, c")
        assert args == ["a", " b", " c"]

    def test_quoted_args(self):
        """Test splitting quoted arguments."""
        args = _split_args('"hello, world", other')
        assert len(args) == 2

    def test_nested_brackets(self):
        """Test splitting with nested brackets."""
        args = _split_args("[a, b], c")
        assert len(args) == 2
        assert args[0] == "[a, b]"
        assert args[1] == " c"

    def test_empty_string(self):
        """Test splitting empty string."""
        args = _split_args("")
        assert args == []

    def test_single_arg(self):
        """Test splitting single argument."""
        args = _split_args("single")
        assert args == ["single"]


class TestParseValue:
    """Tests for _parse_value function."""

    def test_integer(self):
        """Test parsing integer value."""
        assert _parse_value("42") == 42
        assert _parse_value("0") == 0
        assert _parse_value("-1") == -1

    def test_string(self):
        """Test parsing string value."""
        assert _parse_value("hello") == "hello"
        assert _parse_value('"quoted"') == "quoted"

    def test_duration(self):
        """Test parsing duration value."""
        assert _parse_value("6m") == "6m"
        assert _parse_value("1y") == "1y"
        assert _parse_value("2w") == "2w"
        assert _parse_value("3d") == "3d"
        assert _parse_value("24h") == "24h"

    def test_list(self):
        """Test parsing list value."""
        result = _parse_value("[a, b, c]")
        assert result == ["a", "b", "c"]

    def test_empty_list(self):
        """Test parsing empty list."""
        result = _parse_value("[]")
        assert result == [""]

    def test_quoted_string(self):
        """Test parsing quoted string removes quotes."""
        assert _parse_value('"hello"') == "hello"
        assert _parse_value("'world'") == "world"


class TestPipelineStep:
    """Tests for PipelineStep dataclass."""

    def test_default_values(self):
        """Test PipelineStep default values."""
        step = PipelineStep(function="test")
        assert step.function == "test"
        assert step.args == []
        assert step.kwargs == {}

    def test_with_args(self):
        """Test PipelineStep with args."""
        step = PipelineStep(function="pride", args=[3, "claude"])
        assert step.function == "pride"
        assert step.args == [3, "claude"]

    def test_with_kwargs(self):
        """Test PipelineStep with kwargs."""
        step = PipelineStep(function="pr", kwargs={"branch": "main"})
        assert step.function == "pr"
        assert step.kwargs == {"branch": "main"}


class TestFeedbackOperator:
    """Tests for <-> and <N-> feedback operator parsing."""

    def test_basic_feedback_operator(self):
        """Test parsing basic <-> feedback operator."""
        prompt, steps = parse_lion_input('"Build X" -> pride(5) <-> review()')
        assert prompt == "Build X"
        assert len(steps) == 2
        assert steps[0].function == "pride"
        assert steps[0].feedback is False
        assert steps[1].function == "review"
        assert steps[1].feedback is True
        assert steps[1].feedback_agents is None  # Use original count

    def test_feedback_with_agent_count(self):
        """Test parsing <N-> operator with explicit agent count."""
        prompt, steps = parse_lion_input('"Build X" -> pride(5) <1-> review()')
        assert len(steps) == 2
        assert steps[1].feedback is True
        assert steps[1].feedback_agents == 1

    def test_feedback_with_larger_agent_count(self):
        """Test parsing <3-> operator."""
        prompt, steps = parse_lion_input('"Build X" -> pride(5) <3-> review()')
        assert steps[1].feedback is True
        assert steps[1].feedback_agents == 3

    def test_multiple_feedback_operators(self):
        """Test parsing multiple <-> operators in pipeline."""
        prompt, steps = parse_lion_input(
            '"Build X" -> pride(5) <1-> review() <-> devil() -> test()'
        )
        assert len(steps) == 4
        assert steps[0].function == "pride"
        assert steps[0].feedback is False
        assert steps[1].function == "review"
        assert steps[1].feedback is True
        assert steps[1].feedback_agents == 1
        assert steps[2].function == "devil"
        assert steps[2].feedback is True
        assert steps[2].feedback_agents is None
        assert steps[3].function == "test"
        assert steps[3].feedback is False

    def test_no_feedback_operators(self):
        """Test that regular -> does not set feedback flags."""
        prompt, steps = parse_lion_input('"Build X" -> pride(5) -> review() -> test()')
        for step in steps:
            assert step.feedback is False
            assert step.feedback_agents is None

    def test_feedback_operator_with_unquoted_prompt(self):
        """Test <-> with unquoted prompt."""
        prompt, steps = parse_lion_input("Build X -> pride(5) <-> review()")
        assert prompt == "Build X"
        assert len(steps) == 2
        assert steps[1].feedback is True

    def test_mixed_operators_complex(self):
        """Test complex pipeline with mixed operators."""
        prompt, steps = parse_lion_input(
            '"Auth system" -> pride(5) <1-> review() <-> devil() -> test() -> pr(feature/auth)'
        )
        assert prompt == "Auth system"
        assert len(steps) == 5
        assert steps[0].function == "pride"
        assert steps[0].feedback is False
        assert steps[1].function == "review"
        assert steps[1].feedback is True
        assert steps[1].feedback_agents == 1
        assert steps[2].function == "devil"
        assert steps[2].feedback is True
        assert steps[2].feedback_agents is None
        assert steps[3].function == "test"
        assert steps[3].feedback is False
        assert steps[4].function == "pr"
        assert steps[4].feedback is False

    def test_pipeline_step_feedback_defaults(self):
        """Test PipelineStep default feedback values."""
        step = PipelineStep(function="test")
        assert step.feedback is False
        assert step.feedback_agents is None


class TestEdgeCases:
    """Edge case tests for parser."""

    def test_very_long_prompt(self):
        """Test parsing very long prompt."""
        long_text = "Build " + "a " * 1000 + "feature"
        prompt, steps = parse_lion_input(f'"{long_text}" -> review()')
        assert prompt == long_text
        assert len(steps) == 1

    def test_special_characters_in_prompt(self):
        """Test parsing prompt with special characters."""
        prompt, steps = parse_lion_input('"Fix bug #123 & add feature @user" -> review()')
        assert prompt == "Fix bug #123 & add feature @user"
        assert len(steps) == 1

    def test_unicode_in_prompt(self):
        """Test parsing prompt with unicode characters."""
        prompt, steps = parse_lion_input('"Build feature with emoji 🦁" -> review()')
        assert prompt == "Build feature with emoji 🦁"
        assert len(steps) == 1

    def test_multiple_spaces_between_arrows(self):
        """Test parsing with multiple spaces around arrows."""
        prompt, steps = parse_lion_input('"Test"   ->   review()   ->   test()')
        assert prompt == "Test"
        assert len(steps) == 2

    def test_pipeline_with_path_arg(self):
        """Test parsing pipeline step with path argument."""
        prompt, steps = parse_lion_input('"Create PR" -> pr(feature/my-branch)')
        assert prompt == "Create PR"
        assert steps[0].args == ["feature/my-branch"]

    def test_case_insensitive_function_names(self):
        """Test that function names are normalized to lowercase."""
        prompt, steps = parse_lion_input('"Test" -> Devil() -> Review()')
        assert steps[0].function == "devil"
        assert steps[1].function == "review"

    def test_case_insensitive_with_args(self):
        """Test case normalization with arguments."""
        prompt, steps = parse_lion_input('"Test" -> Pride(3, claude)')
        assert steps[0].function == "pride"
        assert steps[0].args == [3, "claude"]

    def test_case_insensitive_bare_name(self):
        """Test case normalization for bare function name without parens."""
        step = _parse_step("Devil", {})
        assert step.function == "devil"
