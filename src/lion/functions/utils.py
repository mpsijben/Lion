"""Shared utilities for Lion pipeline functions.

Contains common helpers for framework detection, file discovery,
and project structure analysis.
"""

import os
import json
from typing import Optional


# Test framework patterns (shared between test.py and create_tests.py)
TEST_FRAMEWORK_PATTERNS = {
    "pytest": {
        "files": ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"],
        "markers": ["import pytest", "def test_"],
        "command": ["pytest", "-v", "--tb=short"],
        "file_glob": "**/*test*.py",
        "test_pattern": "test_{name}.py",
        "language": "python",
    },
    "jest": {
        "files": ["jest.config.js", "jest.config.ts", "jest.config.json"],
        "markers": ["describe(", "it(", "test(", "expect("],
        "command": ["npm", "test", "--"],
        "file_glob": "**/*.test.{js,ts,tsx}",
        "test_pattern": "{name}.test.ts",
        "language": "typescript",
    },
    "vitest": {
        "files": ["vitest.config.ts", "vitest.config.js"],
        "markers": ["describe(", "it(", "test(", "expect("],
        "command": ["npm", "run", "test"],
        "file_glob": "**/*.test.{js,ts,tsx}",
        "test_pattern": "{name}.test.ts",
        "language": "typescript",
    },
    "mocha": {
        "files": [".mocharc.json", ".mocharc.js", ".mocharc.yaml"],
        "markers": ["describe(", "it(", "expect("],
        "command": ["npm", "test"],
        "file_glob": "**/*.test.js",
        "test_pattern": "{name}.test.js",
        "language": "javascript",
    },
    "go": {
        "files": ["go.mod"],
        "markers": ["func Test"],
        "command": ["go", "test", "-v", "./..."],
        "file_glob": "**/*_test.go",
        "test_pattern": "{name}_test.go",
        "language": "go",
    },
    "cargo": {
        "files": ["Cargo.toml"],
        "markers": ["#[test]", "#[cfg(test)]"],
        "command": ["cargo", "test"],
        "file_glob": "**/tests/*.rs",
        "test_pattern": "{name}_test.rs",
        "language": "rust",
    },
}

# Linter patterns for different languages
LINTER_PATTERNS = {
    "python": {
        "linters": [
            {"name": "ruff", "check": ["ruff", "--version"], "fix": ["ruff", "check", "--fix", "."], "format": ["ruff", "format", "."]},
            {"name": "black", "check": ["black", "--version"], "fix": ["black", "."]},
            {"name": "flake8", "check": ["flake8", "--version"], "fix": None},  # flake8 doesn't auto-fix
            {"name": "pylint", "check": ["pylint", "--version"], "fix": None},
        ],
        "files": ["*.py"],
        "config_files": ["pyproject.toml", "setup.cfg", ".flake8", "ruff.toml"],
    },
    "typescript": {
        "linters": [
            {"name": "eslint", "check": ["npx", "eslint", "--version"], "fix": ["npx", "eslint", "--fix", "."]},
            {"name": "prettier", "check": ["npx", "prettier", "--version"], "fix": ["npx", "prettier", "--write", "."]},
            {"name": "biome", "check": ["npx", "biome", "--version"], "fix": ["npx", "biome", "check", "--apply", "."]},
        ],
        "files": ["*.ts", "*.tsx", "*.js", "*.jsx"],
        "config_files": [".eslintrc.js", ".eslintrc.json", "eslint.config.js", ".prettierrc", "biome.json"],
    },
    "javascript": {
        "linters": [
            {"name": "eslint", "check": ["npx", "eslint", "--version"], "fix": ["npx", "eslint", "--fix", "."]},
            {"name": "prettier", "check": ["npx", "prettier", "--version"], "fix": ["npx", "prettier", "--write", "."]},
        ],
        "files": ["*.js", "*.jsx"],
        "config_files": [".eslintrc.js", ".eslintrc.json", "eslint.config.js", ".prettierrc"],
    },
    "go": {
        "linters": [
            {"name": "gofmt", "check": ["gofmt", "-h"], "fix": ["gofmt", "-w", "."]},
            {"name": "golangci-lint", "check": ["golangci-lint", "--version"], "fix": ["golangci-lint", "run", "--fix"]},
        ],
        "files": ["*.go"],
        "config_files": [".golangci.yml", ".golangci.yaml"],
    },
    "rust": {
        "linters": [
            {"name": "rustfmt", "check": ["rustfmt", "--version"], "fix": ["cargo", "fmt"]},
            {"name": "clippy", "check": ["cargo", "clippy", "--version"], "fix": ["cargo", "clippy", "--fix", "--allow-dirty"]},
        ],
        "files": ["*.rs"],
        "config_files": ["rustfmt.toml", ".rustfmt.toml", "clippy.toml"],
    },
}

# Type checker patterns
TYPE_CHECKER_PATTERNS = {
    "python": {
        "checkers": [
            {"name": "mypy", "check": ["mypy", "--version"], "command": ["mypy", "."]},
            {"name": "pyright", "check": ["pyright", "--version"], "command": ["pyright"]},
        ],
        "config_files": ["mypy.ini", "pyrightconfig.json", "pyproject.toml"],
    },
    "typescript": {
        "checkers": [
            {"name": "tsc", "check": ["npx", "tsc", "--version"], "command": ["npx", "tsc", "--noEmit"]},
        ],
        "config_files": ["tsconfig.json"],
    },
    "go": {
        "checkers": [
            {"name": "go vet", "check": ["go", "version"], "command": ["go", "vet", "./..."]},
        ],
        "config_files": ["go.mod"],
    },
    "rust": {
        "checkers": [
            {"name": "cargo check", "check": ["cargo", "--version"], "command": ["cargo", "check"]},
        ],
        "config_files": ["Cargo.toml"],
    },
}


def detect_project_language(cwd: str) -> Optional[str]:
    """Detect the primary language of the project.

    Returns:
        Language name (python, typescript, javascript, go, rust) or None.
    """
    # Check for language-specific files
    indicators = {
        "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
        "typescript": ["tsconfig.json"],
        "javascript": ["package.json"],  # Will be overridden by typescript if tsconfig exists
        "go": ["go.mod"],
        "rust": ["Cargo.toml"],
    }

    for lang, files in indicators.items():
        for f in files:
            if os.path.exists(os.path.join(cwd, f)):
                # TypeScript check takes priority over JavaScript
                if lang == "javascript":
                    if os.path.exists(os.path.join(cwd, "tsconfig.json")):
                        return "typescript"
                return lang

    # Count files by extension as fallback
    ext_counts = {}
    ext_to_lang = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
    }

    for root, dirs, files in os.walk(cwd):
        # Skip hidden dirs and common non-source dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in [
            'node_modules', 'venv', '.venv', '__pycache__', 'target', 'dist', 'build'
        ]]
        for f in files:
            ext = os.path.splitext(f)[1]
            if ext in ext_to_lang:
                lang = ext_to_lang[ext]
                ext_counts[lang] = ext_counts.get(lang, 0) + 1

    if ext_counts:
        return max(ext_counts, key=ext_counts.get)

    return None


def detect_test_framework(cwd: str) -> tuple[Optional[str], list[str]]:
    """Detect the test framework used in the project.

    Returns:
        Tuple of (framework_name, command) or (None, []) if not detected.
    """
    for framework, info in TEST_FRAMEWORK_PATTERNS.items():
        # Check for config files
        for config_file in info["files"]:
            if os.path.exists(os.path.join(cwd, config_file)):
                return framework, info["command"]

        # Check package.json for node projects
        package_json = os.path.join(cwd, "package.json")
        if framework in ["jest", "vitest", "mocha"] and os.path.exists(package_json):
            try:
                with open(package_json, "r") as f:
                    content = f.read()
                    if f'"{framework}"' in content:
                        return framework, info["command"]
            except Exception:
                pass

    # Check for pytest in requirements.txt or pyproject.toml
    for req_file in ["requirements.txt", "requirements-dev.txt", "pyproject.toml"]:
        req_path = os.path.join(cwd, req_file)
        if os.path.exists(req_path):
            try:
                with open(req_path, "r") as f:
                    content = f.read()
                    if "pytest" in content.lower():
                        return "pytest", TEST_FRAMEWORK_PATTERNS["pytest"]["command"]
            except Exception:
                pass

    # Check for test files directly
    for framework, info in TEST_FRAMEWORK_PATTERNS.items():
        if framework == "pytest":
            for root, dirs, files in os.walk(cwd):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in [
                    'node_modules', 'venv', '.venv', '__pycache__'
                ]]
                for f in files:
                    if f.startswith("test_") and f.endswith(".py"):
                        return "pytest", info["command"]
                    if f.endswith("_test.py"):
                        return "pytest", info["command"]

    return None, []


def detect_linter(cwd: str, language: Optional[str] = None) -> tuple[Optional[str], Optional[dict]]:
    """Detect available linter for the project.

    Args:
        cwd: Working directory
        language: Optional language to check for (auto-detected if None)

    Returns:
        Tuple of (linter_name, linter_config) or (None, None) if not detected.
    """
    import subprocess

    if language is None:
        language = detect_project_language(cwd)

    if language is None or language not in LINTER_PATTERNS:
        return None, None

    linter_info = LINTER_PATTERNS[language]

    # First check for config files to determine preferred linter
    for linter in linter_info["linters"]:
        # Try to run the check command to see if linter is installed
        try:
            subprocess.run(
                linter["check"],
                cwd=cwd,
                capture_output=True,
                timeout=10,
            )
            if linter["fix"]:  # Only return linters that can auto-fix
                return linter["name"], linter
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    return None, None


def detect_type_checker(cwd: str, language: Optional[str] = None) -> tuple[Optional[str], Optional[dict]]:
    """Detect available type checker for the project.

    Args:
        cwd: Working directory
        language: Optional language to check for (auto-detected if None)

    Returns:
        Tuple of (checker_name, checker_config) or (None, None) if not detected.
    """
    import subprocess

    if language is None:
        language = detect_project_language(cwd)

    if language is None or language not in TYPE_CHECKER_PATTERNS:
        return None, None

    checker_info = TYPE_CHECKER_PATTERNS[language]

    # Check for config files first
    has_config = False
    for config_file in checker_info["config_files"]:
        if os.path.exists(os.path.join(cwd, config_file)):
            has_config = True
            break

    # Try each checker
    for checker in checker_info["checkers"]:
        try:
            subprocess.run(
                checker["check"],
                cwd=cwd,
                capture_output=True,
                timeout=10,
            )
            return checker["name"], checker
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    return None, None


def get_source_files(cwd: str, language: Optional[str] = None) -> list[str]:
    """Get list of source files in the project.

    Args:
        cwd: Working directory
        language: Optional language filter

    Returns:
        List of relative file paths.
    """
    if language is None:
        language = detect_project_language(cwd)

    ext_map = {
        "python": [".py"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx"],
        "go": [".go"],
        "rust": [".rs"],
    }

    extensions = ext_map.get(language, [".py", ".ts", ".js", ".go", ".rs"])
    files = []

    skip_dirs = {
        'node_modules', 'venv', '.venv', '__pycache__',
        'target', 'dist', 'build', '.git', '.lion'
    }

    for root, dirs, filenames in os.walk(cwd):
        # Skip hidden and common non-source dirs
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]

        for f in filenames:
            if any(f.endswith(ext) for ext in extensions):
                rel_path = os.path.relpath(os.path.join(root, f), cwd)
                files.append(rel_path)

    return files


def get_test_files(cwd: str, framework: Optional[str] = None) -> list[str]:
    """Get list of test files in the project.

    Args:
        cwd: Working directory
        framework: Optional test framework name

    Returns:
        List of relative test file paths.
    """
    if framework is None:
        framework, _ = detect_test_framework(cwd)

    if framework is None:
        return []

    test_patterns = {
        "pytest": lambda f: (f.startswith("test_") or f.endswith("_test.py")) and f.endswith(".py"),
        "jest": lambda f: f.endswith(".test.ts") or f.endswith(".test.tsx") or f.endswith(".test.js"),
        "vitest": lambda f: f.endswith(".test.ts") or f.endswith(".test.tsx") or f.endswith(".test.js"),
        "mocha": lambda f: f.endswith(".test.js"),
        "go": lambda f: f.endswith("_test.go"),
        "cargo": lambda f: f.endswith("_test.rs") or "tests/" in f,
    }

    matcher = test_patterns.get(framework, lambda f: False)
    files = []

    skip_dirs = {
        'node_modules', 'venv', '.venv', '__pycache__',
        'target', 'dist', 'build', '.git', '.lion'
    }

    for root, dirs, filenames in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]

        for f in filenames:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, cwd)
            if matcher(rel_path):
                files.append(rel_path)

    return files


def read_file_content(filepath: str, max_size: int = 50000) -> str:
    """Read file content with size limit.

    Args:
        filepath: Path to file
        max_size: Maximum characters to read

    Returns:
        File content (truncated if needed).
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_size)
            if len(content) == max_size:
                content += "\n\n... [TRUNCATED] ..."
            return content
    except Exception as e:
        return f"Error reading file: {e}"
