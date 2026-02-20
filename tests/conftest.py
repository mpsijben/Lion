"""Pytest configuration and shared fixtures."""

import os
import tempfile
import shutil
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    dirpath = tempfile.mkdtemp()
    yield dirpath
    shutil.rmtree(dirpath, ignore_errors=True)


@pytest.fixture
def temp_run_dir(temp_dir):
    """Create a temporary run directory with memory.jsonl support."""
    run_dir = os.path.join(temp_dir, ".lion", "runs", "test_run")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


@pytest.fixture
def sample_config():
    """Return a sample configuration dict."""
    return {
        "providers": {
            "default": "claude",
        },
        "complexity": {
            "high_signals": ["build", "create", "design", "architect"],
            "low_signals": ["fix", "bug", "typo", "rename"],
        },
        "patterns": {
            "quick": "review() -> test()",
            "full": "pride(3) -> review() -> test() -> pr()",
        },
    }


@pytest.fixture
def mock_cwd(temp_dir):
    """Create a mock working directory with basic project structure."""
    # Create basic Python project structure
    src_dir = os.path.join(temp_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    # Create a sample Python file
    with open(os.path.join(src_dir, "main.py"), "w") as f:
        f.write("def hello():\n    return 'Hello, World!'\n")

    # Create pyproject.toml
    with open(os.path.join(temp_dir, "pyproject.toml"), "w") as f:
        f.write('[project]\nname = "test-project"\nversion = "0.1.0"\n')

    return temp_dir


@pytest.fixture
def git_repo(temp_dir):
    """Create a temporary git repository."""
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=temp_dir,
        capture_output=True,
    )

    # Create initial commit
    with open(os.path.join(temp_dir, "README.md"), "w") as f:
        f.write("# Test Project\n")

    subprocess.run(
        ["git", "add", "."],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_dir,
        capture_output=True,
    )

    return temp_dir
