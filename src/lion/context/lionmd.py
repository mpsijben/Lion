"""LION.md project context loading.

Loads project-specific instructions from LION.md files in the directory hierarchy.
Files are searched from the working directory upward to the project root.

Usage:
    loader = LionMdLoader(cwd="/path/to/project")
    context = loader.load()  # Returns combined content from all LION.md files

    # With hierarchy (project -> directory specific)
    contexts = loader.load_hierarchy()  # Returns list of (path, content) tuples
"""

import os
from pathlib import Path
from typing import Optional


# Maximum file size to prevent memory issues
MAX_LIONMD_SIZE = 50000  # 50KB


def find_project_root(cwd: str) -> Optional[str]:
    """Find the project root directory.

    Looks for common project root indicators:
    - .git directory
    - pyproject.toml
    - package.json
    - Cargo.toml
    - go.mod
    - .lion directory

    Args:
        cwd: Current working directory

    Returns:
        Project root path or None if not found
    """
    current = Path(cwd).resolve()

    indicators = [
        ".git",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        ".lion",
    ]

    while current != current.parent:
        for indicator in indicators:
            if (current / indicator).exists():
                return str(current)
        current = current.parent

    return None


class LionMdLoader:
    """Loads LION.md project context files.

    LION.md files provide project-specific instructions to Lion agents.
    They can exist at multiple levels:
    - Project root: General project guidelines
    - Subdirectories: Component-specific instructions

    The loader combines all relevant LION.md files into a single context,
    with more specific (deeper) files taking precedence.
    """

    # Standard filenames to look for (in order of preference)
    FILENAMES = ["LION.md", ".lion.md", "lion.md"]

    def __init__(self, cwd: str, project_root: Optional[str] = None):
        """Initialize the loader.

        Args:
            cwd: Current working directory
            project_root: Project root directory (auto-detected if not provided)
        """
        self.cwd = Path(cwd).resolve()
        self.project_root = Path(project_root) if project_root else None

        if not self.project_root:
            root = find_project_root(str(self.cwd))
            self.project_root = Path(root) if root else self.cwd

    def _find_lionmd(self, directory: Path) -> Optional[Path]:
        """Find LION.md file in a directory.

        Args:
            directory: Directory to search

        Returns:
            Path to LION.md file or None if not found
        """
        for filename in self.FILENAMES:
            path = directory / filename
            if path.is_file():
                return path
        return None

    def _read_file(self, path: Path) -> Optional[str]:
        """Read a LION.md file with size limits.

        Args:
            path: Path to the file

        Returns:
            File contents or None if unreadable
        """
        try:
            size = path.stat().st_size
            if size > MAX_LIONMD_SIZE:
                # Read only the first portion
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read(MAX_LIONMD_SIZE)
                return content + f"\n\n[Truncated - file exceeded {MAX_LIONMD_SIZE} bytes]"

            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except (IOError, OSError, UnicodeDecodeError):
            return None

    def load(self) -> Optional[str]:
        """Load and combine all relevant LION.md files.

        Searches from project root to cwd, combining all found files.
        Project root content comes first, directory-specific content last.

        Returns:
            Combined LION.md content or None if no files found
        """
        hierarchy = self.load_hierarchy()
        if not hierarchy:
            return None

        # Combine with section headers
        parts = []
        for path, content in hierarchy:
            rel_path = path.relative_to(self.project_root) if self.project_root else path
            if str(rel_path) == ".":
                rel_path = "project root"
            parts.append(f"# Context from {rel_path}\n\n{content}")

        return "\n\n---\n\n".join(parts)

    def load_hierarchy(self) -> list[tuple[Path, str]]:
        """Load all LION.md files in the directory hierarchy.

        Returns:
            List of (directory_path, content) tuples, ordered from project root
            to current directory (most general to most specific)
        """
        results = []

        # Build path from project root to cwd
        paths_to_check = []
        current = self.cwd

        while current != self.project_root.parent and current != current.parent:
            paths_to_check.append(current)
            if current == self.project_root:
                break
            current = current.parent

        # Reverse to get root-to-cwd order
        paths_to_check.reverse()

        for directory in paths_to_check:
            lionmd_path = self._find_lionmd(directory)
            if lionmd_path:
                content = self._read_file(lionmd_path)
                if content:
                    results.append((directory, content))

        return results

    def has_context(self) -> bool:
        """Check if any LION.md files exist.

        Returns:
            True if at least one LION.md file exists
        """
        current = self.cwd
        while current != self.project_root.parent and current != current.parent:
            if self._find_lionmd(current):
                return True
            if current == self.project_root:
                break
            current = current.parent
        return False


def load_project_context(cwd: str) -> Optional[str]:
    """Convenience function to load LION.md context.

    Args:
        cwd: Current working directory

    Returns:
        Combined LION.md content or None if no files found
    """
    loader = LionMdLoader(cwd)
    return loader.load()


def format_for_prompt(context: str, max_tokens: int = 2000) -> str:
    """Format LION.md context for inclusion in a prompt.

    Args:
        context: Raw LION.md content
        max_tokens: Maximum approximate tokens (chars / 4)

    Returns:
        Formatted context string
    """
    max_chars = max_tokens * 4

    if len(context) > max_chars:
        context = context[:max_chars] + "\n\n[Context truncated...]"

    return f"""PROJECT CONTEXT (from LION.md):
{context}

---

Apply the above project-specific guidelines when responding."""
