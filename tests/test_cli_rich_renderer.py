"""Tests for the Rich context panel renderer.

Tests the collapsible/expandable display functionality using the rich library.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from lion.memory import MemoryEntry
from lion.cli.rich_renderer import (
    RICH_AVAILABLE,
    RichContextPanel,
    get_panel_renderer,
    get_terminal_width,
)


@pytest.fixture
def sample_entry():
    """Create a sample memory entry for testing."""
    return MemoryEntry(
        timestamp=time.time(),
        phase="propose",
        agent="agent_1",
        type="proposal",
        content="This is a test proposal with some content that is long enough to test truncation behavior in collapsed mode.",
        reasoning="This approach was chosen because it demonstrates the full capability of the system.",
        alternatives=["Alternative A: Use a different method", "Alternative B: Skip this step"],
        uncertainties=["Not sure if this is the best approach"],
        confidence=0.85,
    )


@pytest.fixture
def minimal_entry():
    """Create a minimal memory entry without Layer 2 data."""
    return MemoryEntry(
        timestamp=time.time(),
        phase="implement",
        agent="agent_2",
        type="code",
        content="def hello(): pass",
    )


class TestGetTerminalWidth:
    """Tests for terminal width detection."""

    def test_returns_integer(self):
        """get_terminal_width should return an integer."""
        width = get_terminal_width()
        assert isinstance(width, int)
        assert width > 0

    def test_returns_fallback_on_error(self):
        """Should return fallback value when detection fails."""
        with patch("shutil.get_terminal_size", side_effect=Exception("Failed")):
            width = get_terminal_width()
            assert width == 80


class TestRichContextPanelAvailability:
    """Tests for Rich availability detection."""

    def test_is_available_returns_bool(self):
        """is_available should return a boolean."""
        panel = RichContextPanel()
        assert isinstance(panel.is_available(), bool)

    def test_rich_available_constant(self):
        """RICH_AVAILABLE should be a boolean."""
        assert isinstance(RICH_AVAILABLE, bool)


class TestRichContextPanelIndicators:
    """Tests for collapse/expand indicators."""

    def test_collapsed_indicator_contains_index(self, sample_entry):
        """Collapsed indicator should contain the entry index."""
        panel = RichContextPanel()
        indicator = panel.render_collapsed_indicator(5)
        # Should contain +5 in some form
        assert "+5" in indicator or "[+5]" in indicator

    def test_expanded_indicator_contains_index(self, sample_entry):
        """Expanded indicator should contain the entry index."""
        panel = RichContextPanel()
        indicator = panel.render_expanded_indicator(3)
        # Should contain -3 in some form
        assert "-3" in indicator or "[-3]" in indicator

    def test_collapsed_indicator_is_string(self):
        """Collapsed indicator should return a string."""
        panel = RichContextPanel()
        indicator = panel.render_collapsed_indicator(0)
        assert isinstance(indicator, str)

    def test_expanded_indicator_is_string(self):
        """Expanded indicator should return a string."""
        panel = RichContextPanel()
        indicator = panel.render_expanded_indicator(0)
        assert isinstance(indicator, str)


class TestRichContextPanelRendering:
    """Tests for panel rendering."""

    def test_render_collapsed_panel_returns_string(self, sample_entry):
        """Rendering a collapsed panel should return a string."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=True)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_expanded_panel_returns_string(self, sample_entry):
        """Rendering an expanded panel should return a string."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_collapsed_panel_is_shorter(self, sample_entry):
        """Collapsed panel should be shorter than expanded."""
        panel = RichContextPanel()
        collapsed = panel.render_entry_panel(sample_entry, 0, collapsed=True)
        expanded = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        # Collapsed should be shorter (fewer lines)
        assert collapsed.count("\n") < expanded.count("\n")

    def test_expanded_panel_shows_reasoning(self, sample_entry):
        """Expanded panel should show reasoning field."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        assert "reasoning" in result.lower() or "Reasoning" in result

    def test_expanded_panel_shows_alternatives(self, sample_entry):
        """Expanded panel should show alternatives field."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        assert "alternative" in result.lower() or "Alternative" in result

    def test_collapsed_panel_shows_indicator(self, sample_entry):
        """Collapsed panel should show collapse indicator."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 5, collapsed=True)
        # Should show [+5] or similar indicator
        assert "+5" in result

    def test_expanded_panel_shows_index(self, sample_entry):
        """Expanded panel should show the entry index."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 3, collapsed=False)
        # Should show entry 3 in some form (index reference or panel title)
        assert "3" in result

    def test_respects_terminal_width(self, sample_entry):
        """Panel should respect terminal width parameter."""
        panel = RichContextPanel()
        narrow = panel.render_entry_panel(sample_entry, 0, collapsed=True, terminal_width=40)
        wide = panel.render_entry_panel(sample_entry, 0, collapsed=True, terminal_width=120)
        # Both should render without error
        assert isinstance(narrow, str)
        assert isinstance(wide, str)

    def test_minimal_entry_renders(self, minimal_entry):
        """Entry without Layer 2 data should still render."""
        panel = RichContextPanel()
        collapsed = panel.render_entry_panel(minimal_entry, 0, collapsed=True)
        expanded = panel.render_entry_panel(minimal_entry, 0, collapsed=False)
        assert isinstance(collapsed, str)
        assert isinstance(expanded, str)


class TestRichContextPanelFooterHint:
    """Tests for footer hint rendering."""

    def test_footer_hint_all_collapsed(self):
        """Footer hint should mention expand when all collapsed."""
        panel = RichContextPanel()
        hint = panel.render_footer_hint(collapsed_count=10, total=10)
        assert "expand" in hint.lower()

    def test_footer_hint_all_expanded(self):
        """Footer hint should mention collapse when all expanded."""
        panel = RichContextPanel()
        hint = panel.render_footer_hint(collapsed_count=0, total=10)
        assert "collapse" in hint.lower()

    def test_footer_hint_mixed_state(self):
        """Footer hint should show count when mixed state."""
        panel = RichContextPanel()
        hint = panel.render_footer_hint(collapsed_count=5, total=10)
        # Should show expanded count
        assert "5" in hint

    def test_footer_hint_returns_string(self):
        """Footer hint should return a string."""
        panel = RichContextPanel()
        hint = panel.render_footer_hint(collapsed_count=3, total=7)
        assert isinstance(hint, str)


class TestRichContextPanelSingleton:
    """Tests for the singleton panel renderer."""

    def test_get_panel_renderer_returns_instance(self):
        """get_panel_renderer should return a RichContextPanel."""
        renderer = get_panel_renderer()
        assert isinstance(renderer, RichContextPanel)

    def test_get_panel_renderer_returns_same_instance(self):
        """get_panel_renderer should return the same instance."""
        renderer1 = get_panel_renderer()
        renderer2 = get_panel_renderer()
        assert renderer1 is renderer2


class TestGracefulDegradation:
    """Tests for graceful degradation when rich is not installed."""

    def test_plain_fallback_renders(self, sample_entry):
        """Plain text fallback should work when rich is unavailable."""
        panel = RichContextPanel()
        # Force use of plain rendering
        result = panel._render_plain_entry(sample_entry, 0, collapsed=True)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_plain_fallback_shows_content(self, sample_entry):
        """Plain text fallback should show entry content."""
        panel = RichContextPanel()
        result = panel._render_plain_entry(sample_entry, 0, collapsed=True)
        # Should show part of the content
        assert "test" in result.lower() or "proposal" in result.lower()

    def test_plain_expanded_shows_reasoning(self, sample_entry):
        """Plain text expanded view should show reasoning."""
        panel = RichContextPanel()
        result = panel._render_plain_entry(sample_entry, 0, collapsed=False)
        assert "reasoning" in result.lower() or "Reasoning" in result


class TestConfidenceDisplay:
    """Tests for confidence score display."""

    def test_high_confidence_displayed(self, sample_entry):
        """High confidence (85%) should be displayed."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        assert "85" in result or "HIGH" in result

    def test_confidence_shown_in_expanded(self, sample_entry):
        """Confidence should be shown in expanded view."""
        panel = RichContextPanel()
        result = panel.render_entry_panel(sample_entry, 0, collapsed=False)
        assert "85" in result

    def test_low_confidence_handled(self):
        """Low confidence should be handled correctly."""
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Low confidence proposal",
            confidence=0.25,
        )
        panel = RichContextPanel()
        result = panel.render_entry_panel(entry, 0, collapsed=False)
        assert "25" in result or "LOW" in result
