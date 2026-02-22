"""onboard() - Generate project onboarding documentation.

Analyzes the codebase and generates comprehensive onboarding documentation
for new developers. Addresses key questions:
- WHAT: What does this project do?
- WHY: Why does it exist?
- HOW: How does it work?
- WHERE: Where are the key components?
- GOTCHAS: What are the common pitfalls?
- TESTING: How to test?
- DEPLOYMENT: How to deploy? (optional, configurable)

Key design decisions (addressing devil's advocate review):
1. OUTPUT DESTINATION: Configurable via output_path kwarg, defaults to docs/ONBOARDING.md
2. VALIDATION: Lightweight validation of referenced files and section completeness
3. CONFIGURABLE SECTIONS: Sections defined in config.toml with sensible defaults
4. EXPLICIT CONTEXT GATHERING: gather_onboard_context() helper with defined file sources
5. EXISTING DOCS: Detects and uses existing docs as input context
"""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider, is_provider_name
from ..display import Display
from .utils import (
    detect_project_language,
    detect_test_framework,
    read_file_content,
)


# Default sections with prompts - can be overridden in config.toml
DEFAULT_SECTIONS = {
    "WHAT": {
        "title": "What is this project?",
        "prompt": "Describe what this project does, its main purpose, and the problem it solves.",
        "required": True,
    },
    "WHY": {
        "title": "Why does it exist?",
        "prompt": "Explain the motivation behind this project and why it was built.",
        "required": True,
    },
    "HOW": {
        "title": "How does it work?",
        "prompt": "Explain the high-level architecture and how the main components work together.",
        "required": True,
    },
    "WHERE": {
        "title": "Where is everything?",
        "prompt": "Describe the directory structure and where to find key components.",
        "required": True,
    },
    "GOTCHAS": {
        "title": "Common pitfalls",
        "prompt": "List common mistakes, confusing patterns, and things that might trip up new developers.",
        "required": False,
    },
    "TESTING": {
        "title": "Testing",
        "prompt": "Explain how to run tests and the testing strategy.",
        "required": False,
    },
    "DEPLOYMENT": {
        "title": "Deployment",
        "prompt": "Explain how to deploy the project.",
        "required": False,
    },
}

# Files to look for when gathering context
CONTEXT_FILES = [
    "README.md",
    "README.rst",
    "README.txt",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "DESIGN.md",
    "docs/README.md",
    "docs/index.md",
    "docs/architecture.md",
    # Package manifests
    "package.json",
    "pyproject.toml",
    "setup.py",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    # Configuration files
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.example",
]

# Maximum characters to read from each context file
MAX_CONTEXT_FILE_SIZE = 5000

# Maximum total context size
MAX_TOTAL_CONTEXT_SIZE = 30000


@dataclass
class OnboardContext:
    """Gathered context for onboarding documentation generation."""
    language: Optional[str]
    test_framework: Optional[str]
    existing_docs: dict[str, str]  # filename -> content
    directory_structure: str
    package_info: dict  # extracted from package.json/pyproject.toml etc.
    has_existing_onboarding: bool
    existing_onboarding_path: Optional[str]


@dataclass
class ValidationResult:
    """Result of validating generated documentation."""
    valid: bool
    missing_sections: list[str]
    invalid_file_references: list[str]
    warnings: list[str]


def gather_onboard_context(cwd: str) -> OnboardContext:
    """Gather context from the codebase for onboarding doc generation.

    This explicitly defines WHAT files are read for context,
    addressing the devil's advocate concern about vague context gathering.

    Args:
        cwd: Working directory to analyze

    Returns:
        OnboardContext with gathered information
    """
    # Detect language and test framework
    language = detect_project_language(cwd)
    test_framework, _ = detect_test_framework(cwd)

    # Read existing documentation files
    existing_docs = {}
    total_size = 0

    for filename in CONTEXT_FILES:
        filepath = os.path.join(cwd, filename)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            content = read_file_content(filepath, MAX_CONTEXT_FILE_SIZE)
            if content and not content.startswith("Error reading"):
                existing_docs[filename] = content
                total_size += len(content)
                if total_size > MAX_TOTAL_CONTEXT_SIZE:
                    break

    # Get directory structure
    directory_structure = _get_directory_structure(cwd)

    # Extract package info
    package_info = _extract_package_info(cwd, existing_docs)

    # Check for existing onboarding docs
    has_existing_onboarding = False
    existing_onboarding_path = None

    onboarding_candidates = [
        "docs/ONBOARDING.md",
        "ONBOARDING.md",
        "docs/onboarding.md",
        "docs/getting-started.md",
        "GETTING_STARTED.md",
    ]

    for candidate in onboarding_candidates:
        filepath = os.path.join(cwd, candidate)
        if os.path.exists(filepath):
            has_existing_onboarding = True
            existing_onboarding_path = candidate
            # Also read this into existing_docs if not already there
            if candidate not in existing_docs:
                content = read_file_content(filepath, MAX_CONTEXT_FILE_SIZE)
                if content and not content.startswith("Error reading"):
                    existing_docs[candidate] = content
            break

    return OnboardContext(
        language=language,
        test_framework=test_framework,
        existing_docs=existing_docs,
        directory_structure=directory_structure,
        package_info=package_info,
        has_existing_onboarding=has_existing_onboarding,
        existing_onboarding_path=existing_onboarding_path,
    )


def _get_directory_structure(cwd: str, max_depth: int = 3) -> str:
    """Get a tree-like directory structure for context.

    Args:
        cwd: Working directory
        max_depth: Maximum depth to traverse

    Returns:
        String representation of directory structure
    """
    skip_dirs = {
        'node_modules', 'venv', '.venv', '__pycache__', 'target',
        'dist', 'build', '.git', '.lion', '.tox', '.pytest_cache',
        '.mypy_cache', '.ruff_cache', 'coverage', '.coverage',
        'htmlcov', '.eggs', '*.egg-info',
    }

    lines = []

    def walk(path: str, prefix: str, depth: int):
        if depth > max_depth:
            return

        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return

        dirs = []
        files = []

        for entry in entries:
            if entry.startswith('.') and entry not in ['.env.example']:
                continue
            if entry in skip_dirs:
                continue
            if any(entry.endswith(s) for s in ['.egg-info', '.pyc', '.pyo']):
                continue

            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                dirs.append(entry)
            else:
                files.append(entry)

        # Show files first, then directories
        for i, f in enumerate(files[:10]):  # Limit files shown
            connector = "├── " if i < len(files) - 1 or dirs else "└── "
            lines.append(f"{prefix}{connector}{f}")

        if len(files) > 10:
            lines.append(f"{prefix}├── ... ({len(files) - 10} more files)")

        for i, d in enumerate(dirs[:10]):  # Limit dirs shown
            is_last = i == len(dirs) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{d}/")

            extension = "    " if is_last else "│   "
            walk(os.path.join(path, d), prefix + extension, depth + 1)

        if len(dirs) > 10:
            lines.append(f"{prefix}└── ... ({len(dirs) - 10} more directories)")

    lines.append(os.path.basename(cwd) + "/")
    walk(cwd, "", 1)

    # Truncate with indicator if too many lines
    if len(lines) > 100:
        truncated_lines = lines[:100]
        truncated_lines.append("... [DIRECTORY STRUCTURE TRUNCATED - showing first 100 lines] ...")
        return "\n".join(truncated_lines)
    return "\n".join(lines)


def _extract_package_info(cwd: str, existing_docs: dict[str, str]) -> dict:
    """Extract package information from manifest files.

    Args:
        cwd: Working directory
        existing_docs: Already-read document contents

    Returns:
        Dict with package info (name, version, description, etc.)
    """
    import json

    info = {}

    # Try package.json
    if "package.json" in existing_docs:
        try:
            data = json.loads(existing_docs["package.json"])
            info["name"] = data.get("name", "")
            info["version"] = data.get("version", "")
            info["description"] = data.get("description", "")
            info["main"] = data.get("main", "")
            info["scripts"] = list(data.get("scripts", {}).keys())
            info["type"] = "npm"
        except json.JSONDecodeError:
            pass

    # Try pyproject.toml
    if "pyproject.toml" in existing_docs and "type" not in info:
        content = existing_docs["pyproject.toml"]
        # Simple TOML parsing for common fields
        name_match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        version_match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        desc_match = re.search(r'^description\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)

        if name_match:
            info["name"] = name_match.group(1)
        if version_match:
            info["version"] = version_match.group(1)
        if desc_match:
            info["description"] = desc_match.group(1)
        info["type"] = "python"

    # Try Cargo.toml
    if "Cargo.toml" in existing_docs and "type" not in info:
        content = existing_docs["Cargo.toml"]
        name_match = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
        version_match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
        desc_match = re.search(r'^description\s*=\s*"([^"]+)"', content, re.MULTILINE)

        if name_match:
            info["name"] = name_match.group(1)
        if version_match:
            info["version"] = version_match.group(1)
        if desc_match:
            info["description"] = desc_match.group(1)
        info["type"] = "rust"

    # Try go.mod
    if "go.mod" in existing_docs and "type" not in info:
        content = existing_docs["go.mod"]
        module_match = re.search(r'^module\s+(\S+)', content, re.MULTILINE)
        if module_match:
            info["name"] = module_match.group(1)
        info["type"] = "go"

    return info


def validate_documentation(
    content: str,
    cwd: str,
    required_sections: list[str],
) -> ValidationResult:
    """Validate generated documentation.

    Addresses devil's advocate concern: "documentation can absolutely be validated"

    Checks:
    1. All required sections are present
    2. Referenced file paths actually exist
    3. Markdown parses correctly (basic check)

    Args:
        content: Generated documentation content
        cwd: Working directory for file reference checking
        required_sections: List of section names that must be present

    Returns:
        ValidationResult with validation details
    """
    missing_sections = []
    invalid_file_references = []
    warnings = []

    # Check for required sections
    content_lower = content.lower()
    for section in required_sections:
        # Look for section as a header (## Section or # Section)
        section_patterns = [
            f"## {section.lower()}",
            f"# {section.lower()}",
            f"**{section.lower()}**",
            f"### {section.lower()}",
        ]
        found = any(p in content_lower for p in section_patterns)
        if not found:
            missing_sections.append(section)

    # Check file references
    # Look for common patterns: `path/to/file`, path/to/file.ext, src/...
    file_patterns = [
        r'`([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)`',  # `file.ext`
        r'`(src/[a-zA-Z0-9_\-./]+)`',  # `src/...`
        r'`(lib/[a-zA-Z0-9_\-./]+)`',  # `lib/...`
        r'`(tests?/[a-zA-Z0-9_\-./]+)`',  # `test/...` or `tests/...`
    ]

    referenced_files = set()
    for pattern in file_patterns:
        matches = re.findall(pattern, content)
        referenced_files.update(matches)

    for filepath in referenced_files:
        # Skip common false positives
        if filepath.startswith("http") or filepath.startswith("//"):
            continue
        if "..." in filepath or "*" in filepath:
            continue
        if filepath in ["package.json", "README.md"]:  # Common references
            continue

        full_path = os.path.join(cwd, filepath)
        if not os.path.exists(full_path):
            invalid_file_references.append(filepath)

    # Basic markdown validation
    # Check for unclosed code blocks
    code_block_count = content.count("```")
    if code_block_count % 2 != 0:
        warnings.append("Unclosed code block detected (odd number of ```)")

    # Check for very short sections (might indicate incomplete generation)
    sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
    for section in sections[1:]:  # Skip content before first ##
        lines = section.strip().split('\n')
        if len(lines) > 1:
            section_name = lines[0].strip()
            section_content = '\n'.join(lines[1:]).strip()
            if len(section_content) < 50:
                warnings.append(f"Section '{section_name}' seems very short ({len(section_content)} chars)")

    valid = len(missing_sections) == 0 and len(invalid_file_references) == 0

    return ValidationResult(
        valid=valid,
        missing_sections=missing_sections,
        invalid_file_references=invalid_file_references,
        warnings=warnings,
    )


def _get_sections_config(config: dict) -> dict:
    """Get sections configuration from config, with defaults.

    Addresses devil's advocate concern: sections should be configurable,
    not hardcoded.

    Args:
        config: Lion configuration dict

    Returns:
        Dict of section name -> section config
    """
    # Get onboard config
    onboard_config = config.get("onboard", {})

    # Get custom sections if defined
    custom_sections = onboard_config.get("sections", {})

    # Get list of sections to include (defaults to all)
    include_sections = onboard_config.get("include_sections", list(DEFAULT_SECTIONS.keys()))

    # Get list of sections to exclude
    exclude_sections = onboard_config.get("exclude_sections", [])

    # Build final sections dict
    sections = {}

    for section_name in include_sections:
        if section_name in exclude_sections:
            continue

        if section_name in custom_sections:
            # Use custom section config
            sections[section_name] = {
                "title": custom_sections[section_name].get("title", section_name),
                "prompt": custom_sections[section_name].get("prompt", ""),
                "required": custom_sections[section_name].get("required", False),
            }
        elif section_name in DEFAULT_SECTIONS:
            # Use default section config
            sections[section_name] = DEFAULT_SECTIONS[section_name].copy()
        else:
            # New section without config - use name as title
            sections[section_name] = {
                "title": section_name,
                "prompt": f"Describe {section_name}.",
                "required": False,
            }

    return sections


def _build_onboard_prompt(
    prompt: str,
    context: OnboardContext,
    sections: dict,
    existing_doc_mode: str,
) -> str:
    """Build the prompt for the LLM to generate onboarding documentation.

    Args:
        prompt: User's original prompt
        context: Gathered codebase context
        sections: Sections configuration
        existing_doc_mode: How to handle existing docs ('replace', 'supplement', 'use_as_context')

    Returns:
        Full prompt string for the LLM
    """
    parts = []

    parts.append("""You are generating onboarding documentation for a software project.
Your goal is to help new developers understand the codebase quickly.

IMPORTANT GUIDELINES:
1. Be concise but comprehensive - new developers should get up to speed fast
2. Include specific file paths and code references where helpful
3. Only reference files that actually exist in the codebase
4. Focus on practical information, not marketing fluff
5. If you're uncertain about something, say so rather than guessing
""")

    # Add context about the project
    if context.language:
        parts.append(f"\nPROJECT LANGUAGE: {context.language}")

    if context.test_framework:
        parts.append(f"TEST FRAMEWORK: {context.test_framework}")

    if context.package_info:
        info = context.package_info
        parts.append(f"\nPACKAGE INFO:")
        if info.get("name"):
            parts.append(f"  Name: {info['name']}")
        if info.get("version"):
            parts.append(f"  Version: {info['version']}")
        if info.get("description"):
            parts.append(f"  Description: {info['description']}")
        if info.get("scripts"):
            parts.append(f"  Scripts: {', '.join(info['scripts'][:10])}")

    parts.append(f"\nDIRECTORY STRUCTURE:\n{context.directory_structure}")

    # Add existing documentation as context
    if context.existing_docs:
        parts.append("\nEXISTING DOCUMENTATION:")
        for filename, content in context.existing_docs.items():
            # Truncate large files
            if len(content) > 3000:
                content = content[:3000] + "\n... (truncated)"
            parts.append(f"\n--- {filename} ---\n{content}")

    # Handle existing onboarding docs
    if context.has_existing_onboarding:
        if existing_doc_mode == "supplement":
            parts.append(f"""
EXISTING ONBOARDING DOC FOUND: {context.existing_onboarding_path}
Mode: SUPPLEMENT
Generate NEW sections that complement the existing documentation.
Focus on gaps and areas not covered by the existing docs.
""")
        elif existing_doc_mode == "replace":
            parts.append(f"""
EXISTING ONBOARDING DOC FOUND: {context.existing_onboarding_path}
Mode: REPLACE
Generate a complete new onboarding document.
You may use the existing doc as reference but create fresh content.
""")
        else:  # use_as_context (default)
            parts.append(f"""
EXISTING ONBOARDING DOC FOUND: {context.existing_onboarding_path}
Mode: USE AS CONTEXT
Use the existing documentation as input context to generate improved/updated onboarding docs.
""")

    # Add section requirements
    parts.append("\nREQUIRED SECTIONS:")
    for section_name, section_config in sections.items():
        required_marker = "(REQUIRED)" if section_config.get("required") else "(optional)"
        parts.append(f"\n## {section_config['title']} {required_marker}")
        parts.append(f"   {section_config['prompt']}")

    # Add user prompt if any
    if prompt and prompt.strip():
        parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{prompt}")

    parts.append("""

OUTPUT FORMAT:
Generate the documentation in Markdown format.
Use ## for section headers.
Use code blocks with language tags for code examples.
Use bullet points for lists.

Start directly with the first section. Do not add a preamble or introduction before the first ## header.
""")

    return "\n".join(parts)


def _write_documentation(
    content: str,
    output_path: str,
    cwd: str,
) -> tuple[bool, str]:
    """Write documentation to the output file.

    Addresses devil's advocate concern: explicit output destination strategy.

    Args:
        content: Documentation content to write
        output_path: Relative path for output file
        cwd: Working directory

    Returns:
        Tuple of (success, absolute_path or error_message)
    """
    full_path = os.path.join(cwd, output_path)

    # Ensure directory exists
    dir_path = os.path.dirname(full_path)
    if dir_path:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            return False, f"Failed to create directory {dir_path}: {e}"

    # Write the file
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, full_path
    except IOError as e:
        return False, f"Failed to write file {full_path}: {e}"


def execute_onboard(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute onboarding documentation generation.

    Args:
        prompt: The original user prompt (additional instructions)
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with:
        - success: bool
        - content: generated documentation
        - output_path: where the file was written
        - files_changed: list of changed files
        - validation: ValidationResult dict
        - tokens_used: int
    """
    previous = previous or {}
    start_time = time.time()

    # Get configuration
    onboard_config = config.get("onboard", {})

    # Parse step arguments with defensive access (step.kwargs may be None)
    step_kwargs = step.kwargs or {}
    output_path = step_kwargs.get("output", onboard_config.get("output_path", "docs/ONBOARDING.md"))
    existing_doc_mode = step_kwargs.get("existing_docs", onboard_config.get("existing_doc_mode", "use_as_context"))
    validate = bool(step_kwargs.get("validate", onboard_config.get("validate", True)))
    write_file = bool(step_kwargs.get("write", onboard_config.get("write_file", True)))

    # Validate existing_doc_mode
    valid_modes = {"replace", "supplement", "use_as_context"}
    if existing_doc_mode not in valid_modes:
        raise ValueError(f"Invalid existing_doc_mode: {existing_doc_mode}. Must be one of {valid_modes}")

    # Get provider
    provider_name = None
    for arg in (step.args or []):
        arg_str = str(arg).lower()
        if arg_str != "^" and is_provider_name(arg_str):
            provider_name = arg_str
            break

    if not provider_name:
        provider_name = config.get("providers", {}).get("default", "claude")

    provider = get_provider(provider_name, config)

    Display.phase("onboard", "Gathering codebase context...")

    # Gather context
    context = gather_onboard_context(cwd)

    # Log context gathering
    try:
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="onboard",
            agent="context_gatherer",
            type="context",
            content=f"Gathered context: {len(context.existing_docs)} docs, "
                    f"language={context.language}, test_framework={context.test_framework}",
            metadata={
                "docs_found": list(context.existing_docs.keys()),
                "language": context.language,
                "test_framework": context.test_framework,
                "has_existing_onboarding": context.has_existing_onboarding,
            },
        ))
    except Exception as e:
        # Log memory write failures but don't fail the operation
        Display.notify(f"Warning: Failed to write to memory: {e}")

    # Get sections configuration
    sections = _get_sections_config(config)

    # Handle existing onboarding documentation
    if context.has_existing_onboarding:
        Display.notify(f"Found existing onboarding: {context.existing_onboarding_path} (mode: {existing_doc_mode})")

    # Build the prompt
    full_prompt = _build_onboard_prompt(prompt, context, sections, existing_doc_mode)

    Display.phase("onboard", "Generating documentation...")

    # Generate documentation
    result = provider.ask(full_prompt, "", cwd)

    if not result.success:
        Display.step_error("onboard", result.error or "Generation failed")
        return {
            "success": False,
            "error": result.error or "Documentation generation failed",
            "tokens_used": result.tokens_used,
            "files_changed": [],
        }

    if not result.content or not result.content.strip():
        Display.step_error("onboard", "Generation returned empty content")
        return {
            "success": False,
            "error": "Documentation generation returned empty content",
            "tokens_used": result.tokens_used,
            "files_changed": [],
        }

    content = result.content
    tokens_used = result.tokens_used
    final_model = result.model  # Track which model was used (may change after fix attempt)

    # Track cost for initial generation
    if cost_manager and tokens_used:
        cost_manager.add_cost(provider_name, tokens_used)

    # Validation
    validation_result = None
    if validate:
        Display.phase("onboard", "Validating documentation...")

        required_sections = [
            cfg.get("title", name) for name, cfg in sections.items()
            if cfg.get("required", False)
        ]

        validation_result = validate_documentation(content, cwd, required_sections)

        if validation_result.missing_sections:
            Display.notify(f"Missing sections: {', '.join(validation_result.missing_sections)}")

        if validation_result.invalid_file_references:
            Display.notify(f"Invalid file references: {', '.join(validation_result.invalid_file_references[:5])}")

        if validation_result.warnings:
            for warning in validation_result.warnings[:3]:
                Display.notify(f"Warning: {warning}")

        # If validation failed on required sections, attempt regeneration
        # Number of missing sections to attempt fixing is configurable
        max_sections_to_fix = onboard_config.get("max_sections_to_fix", 4)
        if validation_result.missing_sections and len(validation_result.missing_sections) <= max_sections_to_fix:
            Display.phase("onboard", "Attempting to fill missing sections...")

            fix_prompt = f"""The following required sections are missing from the documentation:
{', '.join(validation_result.missing_sections)}

Please generate ONLY these missing sections in the same format.
Use the same style as the rest of the document.

CONTEXT:
{context.directory_structure[:2000]}

Generate the missing sections now:"""

            fix_result = provider.ask(fix_prompt, "", cwd)
            if fix_result.success and fix_result.content:
                content = content + "\n\n" + fix_result.content
                tokens_used += fix_result.tokens_used
                final_model = fix_result.model  # Update to fix model

                # Track cost for fix attempt
                if cost_manager and fix_result.tokens_used:
                    cost_manager.add_cost(provider_name, fix_result.tokens_used)

                # Re-validate
                validation_result = validate_documentation(content, cwd, required_sections)

    # Write to file
    files_changed = []
    written_path = None
    write_error = None

    if write_file:
        Display.phase("onboard", f"Writing to {output_path}...")

        write_success, path_or_error = _write_documentation(content, output_path, cwd)

        if write_success:
            written_path = path_or_error
            files_changed.append(output_path)
            Display.notify(f"Documentation written to {output_path}")
        else:
            write_error = path_or_error
            Display.step_error("onboard", path_or_error)

    # Log completion
    duration = time.time() - start_time

    try:
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="onboard",
            agent="generator",
            type="documentation",
            content=content[:5000],  # Truncate for memory
            metadata={
                "model": final_model,
                "output_path": output_path,
                "written": write_file and written_path is not None,
                "duration": duration,
                "tokens_used": tokens_used,
                "validation": {
                    "valid": validation_result.valid if validation_result else None,
                    "missing_sections": validation_result.missing_sections if validation_result else [],
                    "invalid_refs": validation_result.invalid_file_references if validation_result else [],
                } if validation_result else None,
            },
        ))
    except Exception as e:
        # Log memory write failures but don't fail the operation
        Display.notify(f"Warning: Failed to write to memory: {e}")

    # If file write was requested but failed, return failure
    if write_file and write_error:
        return {
            "success": False,
            "error": write_error,
            "content": content,
            "output_path": output_path,
            "files_changed": [],
            "validation": {
                "valid": validation_result.valid,
                "missing_sections": validation_result.missing_sections,
                "invalid_file_references": validation_result.invalid_file_references,
                "warnings": validation_result.warnings,
            } if validation_result else None,
            "tokens_used": tokens_used,
            "context": {
                "language": context.language,
                "test_framework": context.test_framework,
                "has_existing_onboarding": context.has_existing_onboarding,
                "existing_onboarding_path": context.existing_onboarding_path,
            },
        }

    return {
        "success": True,
        "content": content,
        "output_path": output_path,
        "written_path": written_path,
        "files_changed": files_changed,
        "validation": {
            "valid": validation_result.valid,
            "missing_sections": validation_result.missing_sections,
            "invalid_file_references": validation_result.invalid_file_references,
            "warnings": validation_result.warnings,
        } if validation_result else None,
        "tokens_used": tokens_used,
        "context": {
            "language": context.language,
            "test_framework": context.test_framework,
            "has_existing_onboarding": context.has_existing_onboarding,
            "existing_onboarding_path": context.existing_onboarding_path,
        },
    }
