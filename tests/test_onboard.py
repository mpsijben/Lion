"""Tests for lion.functions.onboard module."""

import os
import pytest
from unittest.mock import patch, MagicMock

from lion.functions.onboard import (
    execute_onboard,
    gather_onboard_context,
    validate_documentation,
    _get_sections_config,
    _get_directory_structure,
    _extract_package_info,
    DEFAULT_SECTIONS,
)
from lion.parser import PipelineStep
from lion.memory import SharedMemory


class TestGatherOnboardContext:
    """Tests for gather_onboard_context function."""

    def test_gathers_readme(self, temp_dir):
        """Test that README.md is gathered."""
        with open(os.path.join(temp_dir, "README.md"), "w") as f:
            f.write("# My Project\nThis is a test project.")

        context = gather_onboard_context(temp_dir)

        assert "README.md" in context.existing_docs
        assert "test project" in context.existing_docs["README.md"]

    def test_detects_language(self, temp_dir):
        """Test language detection from project files."""
        with open(os.path.join(temp_dir, "pyproject.toml"), "w") as f:
            f.write('[project]\nname = "test"')

        context = gather_onboard_context(temp_dir)

        assert context.language == "python"

    def test_detects_existing_onboarding(self, temp_dir):
        """Test detection of existing onboarding docs."""
        docs_dir = os.path.join(temp_dir, "docs")
        os.makedirs(docs_dir)
        with open(os.path.join(docs_dir, "ONBOARDING.md"), "w") as f:
            f.write("# Onboarding\nWelcome!")

        context = gather_onboard_context(temp_dir)

        assert context.has_existing_onboarding is True
        assert context.existing_onboarding_path == "docs/ONBOARDING.md"

    def test_gathers_package_json(self, temp_dir):
        """Test gathering package.json for npm projects."""
        import json
        with open(os.path.join(temp_dir, "package.json"), "w") as f:
            json.dump({
                "name": "my-app",
                "version": "1.0.0",
                "description": "A test app",
                "scripts": {"test": "jest", "build": "tsc"}
            }, f)

        context = gather_onboard_context(temp_dir)

        assert context.package_info.get("name") == "my-app"
        assert context.package_info.get("version") == "1.0.0"
        assert "test" in context.package_info.get("scripts", [])

    def test_includes_directory_structure(self, temp_dir):
        """Test that directory structure is captured."""
        os.makedirs(os.path.join(temp_dir, "src"))
        os.makedirs(os.path.join(temp_dir, "tests"))
        with open(os.path.join(temp_dir, "src", "main.py"), "w") as f:
            f.write("# main")

        context = gather_onboard_context(temp_dir)

        assert "src/" in context.directory_structure
        assert "tests/" in context.directory_structure


class TestValidateDocumentation:
    """Tests for validate_documentation function."""

    def test_validates_required_sections_present(self, temp_dir):
        """Test validation passes when required sections are present."""
        content = """## What is this project?
This project does X.

## Why does it exist?
Because we needed X.

## How does it work?
It works like this.
"""
        result = validate_documentation(
            content, temp_dir,
            required_sections=["What is this project?", "Why does it exist?"]
        )

        assert result.valid is True
        assert len(result.missing_sections) == 0

    def test_detects_missing_required_sections(self, temp_dir):
        """Test validation detects missing required sections."""
        content = """## What is this project?
This project does X.
"""
        result = validate_documentation(
            content, temp_dir,
            required_sections=["What is this project?", "Why does it exist?"]
        )

        assert result.valid is False
        assert "Why does it exist?" in result.missing_sections

    def test_validates_file_references(self, temp_dir):
        """Test validation checks file references."""
        # Create an actual file
        with open(os.path.join(temp_dir, "existing.py"), "w") as f:
            f.write("# exists")

        content = """## Files
The main file is `existing.py` and another is `nonexistent.py`.
"""
        result = validate_documentation(content, temp_dir, required_sections=[])

        assert "nonexistent.py" in result.invalid_file_references
        assert "existing.py" not in result.invalid_file_references

    def test_detects_unclosed_code_blocks(self, temp_dir):
        """Test validation detects unclosed code blocks."""
        content = """## Example
```python
def foo():
    pass
"""  # Missing closing ```

        result = validate_documentation(content, temp_dir, required_sections=[])

        assert any("Unclosed code block" in w for w in result.warnings)

    def test_warns_on_short_sections(self, temp_dir):
        """Test validation warns on very short sections."""
        content = """## What
X.

## Why
Y.
"""
        result = validate_documentation(content, temp_dir, required_sections=[])

        # Should warn about short sections
        assert any("seems very short" in w for w in result.warnings)


class TestGetSectionsConfig:
    """Tests for _get_sections_config function."""

    def test_returns_defaults_when_no_config(self):
        """Test that default sections are returned when no config."""
        config = {}
        sections = _get_sections_config(config)

        assert "WHAT" in sections
        assert "WHY" in sections
        assert "HOW" in sections
        assert sections["WHAT"]["required"] is True

    def test_respects_include_sections(self):
        """Test that include_sections filters sections."""
        config = {
            "onboard": {
                "include_sections": ["WHAT", "WHY"]
            }
        }
        sections = _get_sections_config(config)

        assert "WHAT" in sections
        assert "WHY" in sections
        assert "HOW" not in sections
        assert "DEPLOYMENT" not in sections

    def test_respects_exclude_sections(self):
        """Test that exclude_sections removes sections."""
        config = {
            "onboard": {
                "include_sections": ["WHAT", "WHY", "DEPLOYMENT"],
                "exclude_sections": ["DEPLOYMENT"]
            }
        }
        sections = _get_sections_config(config)

        assert "WHAT" in sections
        assert "DEPLOYMENT" not in sections

    def test_uses_custom_section_config(self):
        """Test that custom section configs are used."""
        config = {
            "onboard": {
                "sections": {
                    "WHAT": {
                        "title": "Custom Title",
                        "prompt": "Custom prompt",
                        "required": False
                    }
                }
            }
        }
        sections = _get_sections_config(config)

        assert sections["WHAT"]["title"] == "Custom Title"
        assert sections["WHAT"]["prompt"] == "Custom prompt"
        assert sections["WHAT"]["required"] is False


class TestGetDirectoryStructure:
    """Tests for _get_directory_structure function."""

    def test_shows_files_and_dirs(self, temp_dir):
        """Test that both files and directories are shown."""
        os.makedirs(os.path.join(temp_dir, "src"))
        with open(os.path.join(temp_dir, "main.py"), "w") as f:
            f.write("")

        result = _get_directory_structure(temp_dir)

        assert "src/" in result
        assert "main.py" in result

    def test_skips_hidden_dirs(self, temp_dir):
        """Test that hidden directories are skipped."""
        os.makedirs(os.path.join(temp_dir, ".git"))
        os.makedirs(os.path.join(temp_dir, "src"))

        result = _get_directory_structure(temp_dir)

        assert ".git" not in result
        assert "src/" in result

    def test_skips_node_modules(self, temp_dir):
        """Test that node_modules is skipped."""
        os.makedirs(os.path.join(temp_dir, "node_modules", "dep"))
        os.makedirs(os.path.join(temp_dir, "src"))

        result = _get_directory_structure(temp_dir)

        assert "node_modules" not in result
        assert "src/" in result

    def test_respects_max_depth(self, temp_dir):
        """Test that max_depth limits traversal."""
        # Create deep structure
        os.makedirs(os.path.join(temp_dir, "a", "b", "c", "d", "e"))

        result = _get_directory_structure(temp_dir, max_depth=2)

        # Should show a/b/ but not deeper
        assert "a/" in result
        assert "b/" in result


class TestExtractPackageInfo:
    """Tests for _extract_package_info function."""

    def test_extracts_npm_info(self):
        """Test extraction from package.json."""
        import json
        existing_docs = {
            "package.json": json.dumps({
                "name": "my-app",
                "version": "2.0.0",
                "description": "Test app"
            })
        }

        info = _extract_package_info("/tmp", existing_docs)

        assert info["name"] == "my-app"
        assert info["version"] == "2.0.0"
        assert info["type"] == "npm"

    def test_extracts_pyproject_info(self):
        """Test extraction from pyproject.toml."""
        existing_docs = {
            "pyproject.toml": '''
[project]
name = "my-python-app"
version = "1.0.0"
description = "A Python app"
'''
        }

        info = _extract_package_info("/tmp", existing_docs)

        assert info["name"] == "my-python-app"
        assert info["version"] == "1.0.0"
        assert info["type"] == "python"

    def test_extracts_cargo_info(self):
        """Test extraction from Cargo.toml."""
        existing_docs = {
            "Cargo.toml": '''
[package]
name = "my-rust-app"
version = "0.1.0"
description = "A Rust app"
'''
        }

        info = _extract_package_info("/tmp", existing_docs)

        assert info["name"] == "my-rust-app"
        assert info["version"] == "0.1.0"
        assert info["type"] == "rust"


class TestExecuteOnboard:
    """Tests for execute_onboard function."""

    def test_onboard_success(self, temp_run_dir, sample_config, temp_dir):
        """Test successful onboarding doc generation."""
        # Setup: create a basic project structure
        with open(os.path.join(temp_dir, "README.md"), "w") as f:
            f.write("# Test Project\nA test project.")

        os.makedirs(os.path.join(temp_dir, "src"))
        with open(os.path.join(temp_dir, "src", "main.py"), "w") as f:
            f.write("# Main module")

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = """## What is this project?
This is a test project.

## Why does it exist?
For testing purposes.

## How does it work?
It runs tests.

## Where is everything?
Files are in src/.
"""
        mock_result.tokens_used = 500
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="Generate onboarding docs",
                    previous={},
                    step=PipelineStep(function="onboard"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is True
        assert "What is this project?" in result["content"]
        assert result["output_path"] == "docs/ONBOARDING.md"

    def test_onboard_writes_file(self, temp_run_dir, sample_config, temp_dir):
        """Test that onboard writes the output file."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Test\nContent"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(function="onboard"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is True
        assert len(result["files_changed"]) > 0

        # Check file was written
        output_path = os.path.join(temp_dir, "docs", "ONBOARDING.md")
        assert os.path.exists(output_path)
        with open(output_path) as f:
            assert "Content" in f.read()

    def test_onboard_custom_output_path(self, temp_run_dir, sample_config, temp_dir):
        """Test onboard with custom output path."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Custom\nContent"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(
                        function="onboard",
                        kwargs={"output": "GETTING_STARTED.md"}
                    ),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["output_path"] == "GETTING_STARTED.md"
        assert os.path.exists(os.path.join(temp_dir, "GETTING_STARTED.md"))

    def test_onboard_no_write(self, temp_run_dir, sample_config, temp_dir):
        """Test onboard without writing file."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Test\nContent"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(
                        function="onboard",
                        kwargs={"write": False}
                    ),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is True
        assert result["files_changed"] == []
        assert not os.path.exists(os.path.join(temp_dir, "docs", "ONBOARDING.md"))

    def test_onboard_validation_failure_triggers_fix(self, temp_run_dir, sample_config, temp_dir):
        """Test that validation failure triggers section regeneration."""
        mock_provider = MagicMock()

        # First call returns incomplete doc
        first_result = MagicMock()
        first_result.success = True
        first_result.content = """## What is this project?
Test project.
"""  # Missing WHY section
        first_result.tokens_used = 100
        first_result.model = "claude"

        # Second call fills in missing section
        second_result = MagicMock()
        second_result.success = True
        second_result.content = """## Why does it exist?
For testing.
"""
        second_result.tokens_used = 50
        second_result.model = "claude"

        mock_provider.ask.side_effect = [first_result, second_result]

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(function="onboard"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is True
        # Should have called provider twice (initial + fix)
        assert mock_provider.ask.call_count == 2
        # Final content should include both sections
        assert "What is this project?" in result["content"]
        assert "Why does it exist?" in result["content"]

    def test_onboard_handles_existing_docs(self, temp_run_dir, sample_config, temp_dir):
        """Test that existing docs are detected and used."""
        # Create existing onboarding doc
        docs_dir = os.path.join(temp_dir, "docs")
        os.makedirs(docs_dir)
        with open(os.path.join(docs_dir, "ONBOARDING.md"), "w") as f:
            f.write("# Existing Onboarding\nOld content.")

        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "## Updated\nNew content"
        mock_result.tokens_used = 100
        mock_result.model = "claude"
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(function="onboard"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["context"]["has_existing_onboarding"] is True
        assert result["context"]["existing_onboarding_path"] == "docs/ONBOARDING.md"

    def test_onboard_provider_failure(self, temp_run_dir, sample_config, temp_dir):
        """Test handling of provider failure."""
        mock_provider = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Provider error"
        mock_result.tokens_used = 0
        mock_provider.ask.return_value = mock_result

        with patch("lion.functions.onboard.get_provider", return_value=mock_provider):
            with patch("lion.functions.onboard.Display"):
                memory = SharedMemory(temp_run_dir)
                result = execute_onboard(
                    prompt="",
                    previous={},
                    step=PipelineStep(function="onboard"),
                    memory=memory,
                    config=sample_config,
                    cwd=temp_dir,
                )

        assert result["success"] is False
        assert "error" in result


class TestOnboardRegistry:
    """Tests for onboard function registry."""

    def test_onboard_in_registry(self):
        """Test that onboard is registered in FUNCTIONS."""
        from lion.functions import FUNCTIONS
        assert "onboard" in FUNCTIONS
        assert callable(FUNCTIONS["onboard"])
