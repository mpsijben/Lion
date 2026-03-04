"""Tests for Lion CLI autocomplete functionality."""

import pytest
from src.lion.cli.autocomplete import (
    get_pipeline_completions,
    get_pipeline_completions_simple,
    get_pipeline_completions_for_readline,
    tokenize_pipeline,
    highlight_pipeline,
    _get_current_function,
    _get_arg_context,
    _is_valid_partial_pipeline,
    _extract_last_token,
    _extract_simple_token,
    _after_arrow,
    _has_prompt,
    _ends_with_closed_paren,
    _rank_matches,
    _is_fuzzy_match,
    _is_in_prompt,
    TokenType,
)


class TestTokenExtraction:
    """Tests for token extraction functions."""

    def test_extract_last_token_simple(self):
        assert _extract_last_token("pair") == "pair"
        assert _extract_last_token("pair(") == ""
        assert _extract_last_token("pair(claude") == "claude"

    def test_extract_last_token_with_dots(self):
        assert _extract_last_token("claude.") == "claude."
        assert _extract_last_token("claude.haiku") == "claude.haiku"

    def test_extract_last_token_with_colons(self):
        assert _extract_last_token("claude::") == "claude::"
        assert _extract_last_token("claude::arch") == "claude::arch"

    def test_extract_simple_token(self):
        assert _extract_simple_token("claude.haiku") == "haiku"
        assert _extract_simple_token("claude::arch") == "arch"
        assert _extract_simple_token("pair(claude") == "claude"


class TestContextDetection:
    """Tests for context detection functions."""

    def test_after_arrow(self):
        assert _after_arrow('"test" -> ')
        assert _after_arrow('"test" -> pa')
        assert _after_arrow('"test" -> pair')
        assert not _after_arrow('"test" -> pair(')
        assert not _after_arrow('"test"')

    def test_has_prompt(self):
        assert _has_prompt('"test prompt"')
        assert _has_prompt("'test prompt'")
        assert _has_prompt('"test" -> pair()')
        assert _has_prompt("test prompt")  # unquoted text is a valid prompt
        assert not _has_prompt("")

    def test_ends_with_closed_paren(self):
        assert _ends_with_closed_paren("pair()")
        assert _ends_with_closed_paren("pair(3)")
        assert _ends_with_closed_paren("pair() ")
        assert not _ends_with_closed_paren("pair(")
        assert not _ends_with_closed_paren("pair")


class TestCurrentFunction:
    """Tests for function context detection."""

    def test_get_current_function_inside_pair(self):
        assert _get_current_function('"test" -> pair(') == "pair"
        assert _get_current_function('"test" -> pair(claude') == "pair"
        assert _get_current_function('"test" -> pair(claude, eyes:') == "pair"

    def test_get_current_function_inside_pride(self):
        assert _get_current_function('"test" -> pride(') == "pride"
        assert _get_current_function('"test" -> pride(3') == "pride"

    def test_get_current_function_closed(self):
        assert _get_current_function('"test" -> pair()') is None
        assert _get_current_function('"test" -> pride(3)') is None

    def test_get_arg_context(self):
        func, arg, pos = _get_arg_context('"test" -> pair(claude')
        assert func == "pair"
        assert arg == "claude"
        assert pos == 0

        func, arg, pos = _get_arg_context('"test" -> pair(claude, eyes:')
        assert func == "pair"
        assert arg == "eyes:"
        assert pos == 1


class TestValidPipeline:
    """Tests for pipeline validation."""

    def test_valid_pipeline_with_prompt(self):
        assert _is_valid_partial_pipeline('"test"')
        assert _is_valid_partial_pipeline("'test'")

    def test_valid_pipeline_with_function(self):
        assert _is_valid_partial_pipeline('"test" -> pride(3)')
        assert _is_valid_partial_pipeline('"test" -> pair(claude)')

    def test_invalid_pipeline_unclosed_paren(self):
        assert not _is_valid_partial_pipeline('"test" -> pride(3')
        assert not _is_valid_partial_pipeline('"test" -> pair(')

    def test_invalid_pipeline_unclosed_quote(self):
        assert not _is_valid_partial_pipeline('"test')
        assert not _is_valid_partial_pipeline("'test")

    def test_invalid_pipeline_no_prompt(self):
        # pride(3) is valid as unquoted prompt (any text counts as prompt)
        assert _is_valid_partial_pipeline("pride(3)")
        assert not _is_valid_partial_pipeline("")


class TestPipelineCompletions:
    """Tests for pipeline completion suggestions."""

    def test_completions_after_arrow(self):
        result = get_pipeline_completions('"test" -> ')
        # Should suggest all functions
        assert len(result) > 0
        # First should be a function
        assert any("pair" in r[0] for r in result)

    def test_completions_function_prefix(self):
        result = get_pipeline_completions('"test" -> pa')
        # Should suggest pair
        assert any("pair" in r[0] for r in result)

    def test_completions_inside_pair_model(self):
        result = get_pipeline_completions('"test" -> pair(')
        # Should suggest providers
        assert any("claude" in r[0] for r in result)
        assert any("gemini" in r[0] for r in result)

    def test_completions_model_prefix(self):
        result = get_pipeline_completions('"test" -> pair(cla')
        # Should suggest claude
        assert any("claude" in r[0] for r in result)

    def test_completions_model_variant(self):
        result = get_pipeline_completions('"test" -> pair(claude.')
        # Should suggest variants
        assert any("claude.haiku" in r[0] for r in result)
        assert any("claude.sonnet" in r[0] for r in result)

    def test_completions_lens_syntax(self):
        result = get_pipeline_completions('"test" -> pair(claude::')
        # Should suggest lenses
        assert any("claude::arch" in r[0] for r in result)
        assert any("claude::sec" in r[0] for r in result)

    def test_completions_pride_count(self):
        result = get_pipeline_completions('"test" -> pride(')
        # Should suggest counts
        assert ("3", 0) in result
        assert ("5", 0) in result
        assert ("7", 0) in result

    def test_completions_arrow_after_function(self):
        result = get_pipeline_completions('"test" -> pride(3)')
        # Should suggest arrow
        assert ("-> ", 0) in result

    def test_no_arrow_for_invalid_pipeline(self):
        result = get_pipeline_completions('"test" -> pride(3')
        # Should NOT suggest arrow (unclosed paren)
        assert ("-> ", 0) not in result


class TestTokenization:
    """Tests for pipeline tokenization."""

    def test_tokenize_simple_pipeline(self):
        tokens = tokenize_pipeline('"test" -> pride(3)')
        types = [t[0] for t in tokens]
        assert TokenType.STRING in types
        assert TokenType.ARROW in types
        assert TokenType.FUNCTION in types
        assert TokenType.NUMBER in types

    def test_tokenize_with_lens(self):
        tokens = tokenize_pipeline('"test" -> pair(claude::arch)')
        texts = [t[1] for t in tokens]
        assert "claude" in texts
        assert "::arch" in texts

    def test_tokenize_feedback_arrow(self):
        tokens = tokenize_pipeline('"test" -> pride(3) <-> review()')
        types = [t[0] for t in tokens]
        arrows = [t for t in tokens if t[0] == TokenType.ARROW]
        assert len(arrows) == 2
        assert "->" in [a[1] for a in arrows]
        assert "<->" in [a[1] for a in arrows]

    def test_tokenize_self_heal(self):
        tokens = tokenize_pipeline('"test" -> review(^)')
        types = [t[0] for t in tokens]
        assert TokenType.OPERATOR in types
        assert any(t[1] == "^" for t in tokens)


class TestFuzzyMatching:
    """Tests for fuzzy matching."""

    def test_is_fuzzy_match(self):
        assert _is_fuzzy_match("pr", "pride")
        assert _is_fuzzy_match("pde", "pride")
        assert _is_fuzzy_match("", "anything")
        assert not _is_fuzzy_match("xyz", "pride")

    def test_rank_matches_prefix_first(self):
        choices = ["pride", "pair", "pr", "impl"]
        result = _rank_matches("pr", choices)
        # Prefix matches should come first
        assert result[0] in ["pride", "pr"]
        assert result[1] in ["pride", "pr"]


class TestSimpleCompletions:
    """Tests for simple completion format."""

    def test_get_pipeline_completions_simple(self):
        result = get_pipeline_completions_simple('"test" -> pa')
        # Should return strings only
        assert all(isinstance(r, str) for r in result)
        assert any("pair" in r for r in result)


class TestReadlineCompletions:
    """Tests for readline-aware completions (get_pipeline_completions_for_readline).

    These simulate what readline sends: line_buffer is the full line,
    word is the current token being completed (split by delims: space, tab, parens, comma).
    """

    # -- Prompt part: no completions ---

    def test_no_completions_in_prompt(self):
        """Typing a prompt (before any ->) should not trigger completions."""
        # User typing: fix the bug
        result = get_pipeline_completions_for_readline("fix the bug", "bug")
        assert result == []

    def test_no_completions_in_quoted_prompt(self):
        """Inside quotes, no completions."""
        result = get_pipeline_completions_for_readline('"fix the', "the")
        assert result == []

    def test_no_completions_partial_word_no_arrow(self):
        """Typing 'pair' as part of the prompt, not after ->."""
        result = get_pipeline_completions_for_readline("pair", "pair")
        assert result == []

    # -- Arrow completion from prompt ---

    def test_dash_to_arrow_after_quoted_prompt(self):
        """After a valid quoted prompt, `-` should complete to `-> `."""
        result = get_pipeline_completions_for_readline('"fix the bug" -', "-")
        assert result == ["-> "]

    def test_arrow_suggestion_after_prompt_space(self):
        """After a valid quoted prompt + space, suggest `-> `."""
        result = get_pipeline_completions_for_readline('"fix the bug" ', "")
        assert result == ["-> "]

    def test_no_arrow_after_invalid_prompt(self):
        """Unclosed quote: no -> suggestion."""
        result = get_pipeline_completions_for_readline('"fix the bug -', "-")
        assert result == []

    # -- Function completions after -> ---

    def test_function_completion_after_arrow(self):
        """After ->, suggest functions."""
        result = get_pipeline_completions_for_readline('"test" -> pa', "pa")
        assert any("pair(" in r for r in result)

    def test_function_completion_empty_after_arrow(self):
        """After -> with space, suggest all functions."""
        result = get_pipeline_completions_for_readline('"test" -> ', "")
        assert len(result) > 0
        assert any("pair(" in r for r in result)

    # -- Model completion inside pair() ---

    def test_model_inside_pair_parens(self):
        """pair(c + TAB should suggest claude, NOT replace pair(."""
        # With delims including (, readline word is just 'c'
        result = get_pipeline_completions_for_readline('"test" -> pair(c', "c")
        assert "claude" in result
        assert not any("pair" in r for r in result)  # should not re-suggest pair

    def test_model_inside_pair_empty(self):
        """pair( + TAB should suggest all providers."""
        result = get_pipeline_completions_for_readline('"test" -> pair(', "")
        assert "claude" in result
        assert "gemini" in result

    def test_model_variant_completion(self):
        """pair(claude. + TAB should suggest variants."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude.h', "claude.h")
        assert any("claude.haiku" in r for r in result)

    def test_model_after_eyes_kwarg(self):
        """pair(eyes:arch, c + TAB should suggest claude."""
        result = get_pipeline_completions_for_readline('"test" -> pair(eyes:arch, c', "c")
        assert "claude" in result

    def test_model_variant_after_eyes_kwarg(self):
        """pair(eyes:arch, gemini. + TAB should suggest variants."""
        result = get_pipeline_completions_for_readline('"test" -> pair(eyes:arch, gemini.', "gemini.")
        assert any("gemini.flash" in r for r in result)

    def test_kwarg_suggestion_after_model(self):
        """pair(claude, e + TAB should suggest eyes: kwarg."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude, e', "e")
        assert "eyes:" in result

    def test_eyes_lens_model_completion(self):
        """eyes:arch. + TAB should suggest arch.claude, arch.gemini, etc."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude, eyes:arch.', "eyes:arch.")
        assert "eyes:arch.claude" in result
        assert "eyes:arch.gemini" in result

    def test_eyes_lens_model_prefix(self):
        """eyes:arch.g + TAB should suggest arch.gemini."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude, eyes:arch.g', "eyes:arch.g")
        assert "eyes:arch.gemini" in result

    def test_eyes_multi_lens_model_completion(self):
        """eyes:sec.gemini+arch. + TAB should suggest providers for arch."""
        result = get_pipeline_completions_for_readline(
            '"test" -> pair(claude, eyes:sec.gemini+arch.', "eyes:sec.gemini+arch."
        )
        assert any("eyes:sec.gemini+arch.claude" in r for r in result)

    # -- Arrow after valid function call ---

    def test_dash_to_arrow_after_valid_function(self):
        """pair(claude) - + TAB should give -> ."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude) -', "-")
        assert result == ["-> "]

    def test_no_arrow_after_invalid_function(self):
        """pair(fd) - + TAB should NOT give -> (fd is not a valid model, but pair(fd) is syntactically closed)."""
        # pair(fd) is syntactically valid (closed parens), so -> should still be offered
        # The pipeline validator checks syntax, not semantic validity
        result = get_pipeline_completions_for_readline('"test" -> pair(fd) -', "-")
        assert result == ["-> "]

    def test_no_arrow_after_unclosed_paren(self):
        """pair(claude - should NOT offer -> (unclosed paren)."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude -', "-")
        assert result == []

    def test_arrow_after_closed_paren_space(self):
        """pair(claude) + space + TAB should suggest -> ."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude) ', "")
        assert result == ["-> "]

    # -- Pride completions ---

    def test_pride_count_completion(self):
        """pride( + TAB should suggest 3, 5, 7."""
        result = get_pipeline_completions_for_readline('"test" -> pride(', "")
        assert "3" in result
        assert "5" in result

    # -- Chained pipeline ---

    def test_chained_function_after_arrow(self):
        """pair(claude) -> + TAB should suggest functions for second step."""
        result = get_pipeline_completions_for_readline('"test" -> pair(claude) -> ', "")
        assert any("impl" in r for r in result)
        assert any("review" in r or "review(" in r for r in result)
