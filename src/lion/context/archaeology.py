"""Context Archaeology - Search previous runs for relevant context.

Uses lightweight keyword + file path matching to find relevant
historical context without requiring a vector database.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


class ContextArchaeologist:
    """Search previous runs for relevant context."""

    # Common words to ignore in keyword extraction
    STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "build", "create", "make",
        "add", "fix", "update", "implement", "bouw", "maak", "voeg", "toe",
        "this", "that", "these", "those", "and", "or", "but", "for", "with",
        "from", "into", "about", "some", "any", "all", "each", "every",
        "code", "file", "files", "function", "class", "method", "please",
    }

    def __init__(self, runs_dir: str, max_age_days: int = 90):
        """Initialize the archaeologist.

        Args:
            runs_dir: Path to the .lion/runs/ directory
            max_age_days: Ignore runs older than this
        """
        self.runs_dir = Path(runs_dir)
        self.max_age_days = max_age_days

    def find_relevant_runs(self, prompt: str, files_involved: list[str] = None,
                           max_results: int = 3) -> list[dict]:
        """Find previous runs relevant to the current task.

        Args:
            prompt: The user's prompt
            files_involved: List of file paths likely involved
            max_results: Maximum number of runs to return

        Returns:
            List of dicts with run_dir, score, and summary
        """
        files_involved = files_involved or []

        if not self.runs_dir.exists():
            return []

        # Extract keywords from prompt
        keywords = self._extract_keywords(prompt)

        candidates = []

        for run_dir in sorted(self.runs_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue

            # Skip if too old
            if not self._is_recent_enough(run_dir):
                continue

            memory_file = run_dir / "memory.jsonl"
            result_file = run_dir / "result.json"

            if not memory_file.exists():
                continue

            # Score relevance
            score = self._score_relevance(
                run_dir, keywords, files_involved, memory_file, result_file
            )

            if score > 0.3:  # Minimum relevance threshold
                candidates.append({
                    "run_dir": str(run_dir),
                    "score": score,
                    "summary": self._extract_summary(memory_file),
                    "date": self._extract_date(run_dir),
                })

        # Sort by relevance, return top N
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:max_results]

    def _extract_keywords(self, prompt: str) -> set[str]:
        """Extract meaningful keywords from prompt."""
        # Find all words of 3+ characters
        words = set(re.findall(r'\b\w{3,}\b', prompt.lower()))
        return words - self.STOPWORDS

    def _is_recent_enough(self, run_dir: Path) -> bool:
        """Check if run is within max_age_days."""
        try:
            date_str = run_dir.name[:10]
            run_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (datetime.now() - run_date).days
            return days_ago <= self.max_age_days
        except (ValueError, IndexError):
            return True  # Include if can't parse date

    def _score_relevance(self, run_dir: Path, keywords: set[str],
                         files: list[str], memory_file: Path,
                         result_file: Path) -> float:
        """Score how relevant a previous run is.

        Scoring factors:
        - Keyword matches in run directory name
        - File overlap with previous run's changed files
        - Keyword matches in memory content
        - Recency bonus
        """
        score = 0.0

        # Check run directory name for keyword matches
        run_name = run_dir.name.lower()
        keyword_matches = sum(1 for k in keywords if k in run_name)
        score += keyword_matches * 0.3

        # Check if same files were involved
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())
                previous_files = set(result.get("files_changed", []))
                file_overlap = len(set(files) & previous_files)
                score += file_overlap * 0.4
            except (json.JSONDecodeError, KeyError):
                pass

        # Check memory for keyword matches (sample first 2000 chars)
        try:
            memory_text = memory_file.read_text()[:2000].lower()
            content_matches = sum(1 for k in keywords if k in memory_text)
            score += content_matches * 0.1
        except Exception:
            pass

        # Recency bonus
        try:
            date_str = run_dir.name[:10]
            run_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (datetime.now() - run_date).days
            if days_ago < 7:
                score += 0.2
            elif days_ago < 30:
                score += 0.1
        except (ValueError, IndexError):
            pass

        return min(1.0, score)

    def _extract_summary(self, memory_file: Path) -> str:
        """Extract a brief summary from a run's memory."""
        decisions = []
        uncertainties = []

        try:
            for line in memory_file.read_text().split('\n'):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "decision":
                        decisions.append(entry["content"][:200])
                    elif entry.get("type") == "proposal":
                        content = entry["content"]
                        if "uncertain" in content.lower():
                            uncertainties.append(content[:100])
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

        summary = ""
        if decisions:
            summary += f"Decisions: {decisions[0][:200]}"
        if uncertainties:
            summary += f"\nUncertainties flagged: {uncertainties[0][:100]}"

        return summary or "No summary available"

    def _extract_date(self, run_dir: Path) -> Optional[str]:
        """Extract date from run directory name."""
        try:
            return run_dir.name[:10]
        except IndexError:
            return None

    def format_for_prompt(self, relevant_runs: list[dict],
                          max_tokens: int = 500) -> str:
        """Format relevant history for injection into agent prompts.

        Args:
            relevant_runs: List of relevant run dicts
            max_tokens: Maximum tokens for history context

        Returns:
            Formatted string for prompt injection
        """
        if not relevant_runs:
            return ""

        parts = ["RELEVANT PREVIOUS WORK:"]
        remaining_tokens = max_tokens

        for run in relevant_runs:
            date = run.get("date", "unknown date")
            summary = run.get("summary", "")

            entry = f"\n- [{date}] {summary}"
            entry_tokens = int(len(entry.split()) * 1.3)

            if entry_tokens > remaining_tokens:
                break

            parts.append(entry)
            remaining_tokens -= entry_tokens

        return "\n".join(parts) if len(parts) > 1 else ""


def detect_relevant_files(prompt: str, cwd: str) -> list[str]:
    """Detect files likely relevant to a prompt.

    Uses simple heuristics to identify file paths mentioned in the prompt
    or likely relevant based on keywords.

    Args:
        prompt: User's prompt
        cwd: Working directory

    Returns:
        List of file paths that might be relevant
    """
    files = []

    # Extract explicit file paths from prompt
    # Match patterns like: path/to/file.py, ./file.ts, src/component.tsx
    file_patterns = re.findall(
        r'\b[\w./\\-]+\.\w{1,10}\b',
        prompt
    )

    for pattern in file_patterns:
        full_path = os.path.join(cwd, pattern)
        if os.path.exists(full_path):
            files.append(pattern)

    # Extract potential directory references
    dir_patterns = re.findall(r'\b(src|lib|app|components|routes|api|tests?)/\w+', prompt)
    for pattern in dir_patterns:
        full_path = os.path.join(cwd, pattern)
        if os.path.isdir(full_path):
            files.append(pattern)

    return files
