"""Tests for CLI REPL autocomplete helpers."""

from lion.cli.repl import _is_fuzzy_match, get_command_completions


def test_fuzzy_match_subsequence():
    """Subsequence characters should match in order."""
    assert _is_fuzzy_match("sprn", "session-prune")
    assert not _is_fuzzy_match("snrp", "session-prune")


def test_command_completion_prioritizes_prefix():
    """Prefix matches should come before fuzzy-only matches."""
    matches = get_command_completions(":se")
    assert matches
    assert matches[0].startswith(":se")


def test_command_completion_supports_fuzzy_fallback():
    """Fuzzy queries should still suggest useful commands."""
    matches = get_command_completions(":sprn")
    assert ":session-prune" in matches


def test_command_completion_case_insensitive():
    """Uppercase query should still resolve to lowercase commands."""
    matches = get_command_completions(":SR")
    assert ":sr" in matches


def test_non_command_input_has_no_completions():
    """Only :commands should be completed."""
    assert get_command_completions("session") == []
