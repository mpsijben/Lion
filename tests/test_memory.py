"""Tests for lion.memory module."""

import os
import time
import json
import pytest
from lion.memory import SharedMemory, MemoryEntry


class TestMemoryEntry:
    """Tests for MemoryEntry dataclass."""

    def test_create_basic_entry(self):
        """Test creating a basic memory entry."""
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Test content",
        )
        assert entry.phase == "propose"
        assert entry.agent == "agent_1"
        assert entry.type == "proposal"
        assert entry.content == "Test content"
        assert entry.target is None
        assert entry.metadata is None

    def test_create_entry_with_optional_fields(self):
        """Test creating entry with optional fields."""
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="critique",
            agent="agent_2",
            type="critique",
            content="Critique content",
            target="agent_1",
            metadata={"score": 0.8},
        )
        assert entry.target == "agent_1"
        assert entry.metadata == {"score": 0.8}

    def test_entry_timestamp_is_float(self):
        """Test that timestamp is a float."""
        ts = time.time()
        entry = MemoryEntry(
            timestamp=ts,
            phase="test",
            agent="test",
            type="test",
            content="test",
        )
        assert isinstance(entry.timestamp, float)
        assert entry.timestamp == ts


class TestSharedMemory:
    """Tests for SharedMemory class."""

    def test_init_creates_directory(self, temp_dir):
        """Test that init creates the run directory."""
        run_dir = os.path.join(temp_dir, "new_run")
        memory = SharedMemory(run_dir)
        assert os.path.exists(run_dir)
        assert memory.filepath == os.path.join(run_dir, "memory.jsonl")

    def test_write_single_entry(self, temp_run_dir):
        """Test writing a single entry."""
        memory = SharedMemory(temp_run_dir)
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Test proposal",
        )
        memory.write(entry)

        # Verify file exists and contains entry
        assert os.path.exists(memory.filepath)
        with open(memory.filepath, "r") as f:
            line = f.readline()
            data = json.loads(line)
            assert data["phase"] == "propose"
            assert data["content"] == "Test proposal"

    def test_write_multiple_entries(self, temp_run_dir):
        """Test writing multiple entries."""
        memory = SharedMemory(temp_run_dir)

        for i in range(3):
            entry = MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{i}",
                type="proposal",
                content=f"Proposal {i}",
            )
            memory.write(entry)

        # Count lines in file
        with open(memory.filepath, "r") as f:
            lines = f.readlines()
            assert len(lines) == 3

    def test_read_all_empty_file(self, temp_run_dir):
        """Test reading from empty/non-existent file."""
        memory = SharedMemory(temp_run_dir)
        entries = memory.read_all()
        assert entries == []

    def test_read_all_with_entries(self, temp_run_dir):
        """Test reading all entries."""
        memory = SharedMemory(temp_run_dir)

        # Write some entries
        for i in range(3):
            entry = MemoryEntry(
                timestamp=time.time() + i,
                phase="propose",
                agent=f"agent_{i}",
                type="proposal",
                content=f"Proposal {i}",
            )
            memory.write(entry)

        # Read all
        entries = memory.read_all()
        assert len(entries) == 3
        assert all(isinstance(e, MemoryEntry) for e in entries)
        assert entries[0].agent == "agent_0"
        assert entries[2].agent == "agent_2"

    def test_read_phase(self, temp_run_dir):
        """Test reading entries by phase."""
        memory = SharedMemory(temp_run_dir)

        # Write entries in different phases
        phases = ["propose", "critique", "propose", "converge"]
        for i, phase in enumerate(phases):
            entry = MemoryEntry(
                timestamp=time.time() + i,
                phase=phase,
                agent=f"agent_{i}",
                type="test",
                content=f"Content {i}",
            )
            memory.write(entry)

        # Read by phase
        propose_entries = memory.read_phase("propose")
        assert len(propose_entries) == 2

        critique_entries = memory.read_phase("critique")
        assert len(critique_entries) == 1

        converge_entries = memory.read_phase("converge")
        assert len(converge_entries) == 1

        nonexistent = memory.read_phase("nonexistent")
        assert len(nonexistent) == 0

    def test_get_proposals(self, temp_run_dir):
        """Test getting proposal entries."""
        memory = SharedMemory(temp_run_dir)

        # Write proposal and non-proposal entries
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Proposal 1",
        ))
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="critique",
            agent="agent_2",
            type="critique",
            content="Critique 1",
        ))
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_3",
            type="proposal",
            content="Proposal 2",
        ))

        proposals = memory.get_proposals()
        assert len(proposals) == 2
        assert all(p.phase == "propose" for p in proposals)

    def test_get_critiques(self, temp_run_dir):
        """Test getting critique entries."""
        memory = SharedMemory(temp_run_dir)

        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Proposal 1",
        ))
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="critique",
            agent="agent_2",
            type="critique",
            content="Critique 1",
        ))

        critiques = memory.get_critiques()
        assert len(critiques) == 1
        assert critiques[0].phase == "critique"

    def test_get_decisions(self, temp_run_dir):
        """Test getting decision entries."""
        memory = SharedMemory(temp_run_dir)

        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="converge",
            agent="synthesizer",
            type="decision",
            content="Final decision",
        ))
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Proposal",
        ))

        decisions = memory.get_decisions()
        assert len(decisions) == 1
        assert decisions[0].type == "decision"

    def test_format_for_prompt(self, temp_run_dir):
        """Test formatting entries for prompt."""
        memory = SharedMemory(temp_run_dir)

        entries = [
            MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent="agent_1",
                type="proposal",
                content="First proposal",
            ),
            MemoryEntry(
                timestamp=time.time(),
                phase="critique",
                agent="agent_2",
                type="critique",
                content="Critique of first",
                target="agent_1",
            ),
        ]

        formatted = memory.format_for_prompt(entries)

        assert "[agent_1]" in formatted
        assert "First proposal" in formatted
        assert "[agent_2] -> [agent_1]" in formatted
        assert "Critique of first" in formatted

    def test_format_for_prompt_empty_list(self, temp_run_dir):
        """Test formatting empty entry list."""
        memory = SharedMemory(temp_run_dir)
        formatted = memory.format_for_prompt([])
        assert formatted == ""

    def test_entry_with_metadata_serialization(self, temp_run_dir):
        """Test that metadata is properly serialized."""
        memory = SharedMemory(temp_run_dir)

        entry = MemoryEntry(
            timestamp=time.time(),
            phase="test",
            agent="agent_1",
            type="test",
            content="Test content",
            metadata={"key": "value", "number": 42, "nested": {"a": 1}},
        )
        memory.write(entry)

        entries = memory.read_all()
        assert len(entries) == 1
        assert entries[0].metadata == {"key": "value", "number": 42, "nested": {"a": 1}}


class TestSharedMemoryEdgeCases:
    """Edge case tests for SharedMemory."""

    def test_write_entry_with_unicode(self, temp_run_dir):
        """Test writing entry with unicode content."""
        memory = SharedMemory(temp_run_dir)

        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Unicode content: 🦁 émoji テスト",
        )
        memory.write(entry)

        entries = memory.read_all()
        assert entries[0].content == "Unicode content: 🦁 émoji テスト"

    def test_write_entry_with_newlines(self, temp_run_dir):
        """Test writing entry with newlines in content."""
        memory = SharedMemory(temp_run_dir)

        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Line 1\nLine 2\nLine 3",
        )
        memory.write(entry)

        entries = memory.read_all()
        assert entries[0].content == "Line 1\nLine 2\nLine 3"

    def test_write_entry_with_special_json_chars(self, temp_run_dir):
        """Test writing entry with special JSON characters."""
        memory = SharedMemory(temp_run_dir)

        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content='Content with "quotes" and \\backslashes\\',
        )
        memory.write(entry)

        entries = memory.read_all()
        assert '"quotes"' in entries[0].content
        assert "\\backslashes\\" in entries[0].content

    def test_read_corrupted_jsonl(self, temp_run_dir):
        """Test reading file with corrupted JSON line."""
        memory = SharedMemory(temp_run_dir)

        # Write a valid entry
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content="Valid entry",
        )
        memory.write(entry)

        # Append invalid JSON
        with open(memory.filepath, "a") as f:
            f.write("not valid json\n")

        # Reading should skip invalid line and return valid entries
        # Note: current implementation doesn't handle this gracefully
        # This test documents current behavior
        with pytest.raises(json.JSONDecodeError):
            memory.read_all()

    def test_concurrent_writes(self, temp_run_dir):
        """Test that concurrent writes don't corrupt the file."""
        import threading

        memory = SharedMemory(temp_run_dir)
        entries_written = []
        lock = threading.Lock()

        def write_entry(agent_id):
            entry = MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{agent_id}",
                type="proposal",
                content=f"Proposal from {agent_id}",
            )
            memory.write(entry)
            with lock:
                entries_written.append(agent_id)

        threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All entries should be readable
        entries = memory.read_all()
        assert len(entries) == 10

    def test_large_content(self, temp_run_dir):
        """Test writing entry with large content."""
        memory = SharedMemory(temp_run_dir)

        large_content = "x" * 100000  # 100KB of content
        entry = MemoryEntry(
            timestamp=time.time(),
            phase="propose",
            agent="agent_1",
            type="proposal",
            content=large_content,
        )
        memory.write(entry)

        entries = memory.read_all()
        assert len(entries[0].content) == 100000
