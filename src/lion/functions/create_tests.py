"""create_tests() - Force test generation.

Analyzes code and generates comprehensive tests even when no tests exist.
Uses AI to understand the code structure and create appropriate test cases.
"""

import os
import time
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider
from ..display import Display
from .utils import (
    detect_project_language,
    detect_test_framework,
    get_source_files,
    get_test_files,
    read_file_content,
    TEST_FRAMEWORK_PATTERNS,
)


CREATE_TESTS_PROMPT = """You are a test engineer. Analyze the following code and create comprehensive tests.

PROJECT LANGUAGE: {language}
TEST FRAMEWORK: {framework}

SOURCE FILES TO TEST:
{source_files}

EXISTING TESTS (for reference/style):
{existing_tests}

ORIGINAL TASK CONTEXT:
{context}

REQUIREMENTS:
1. Create tests for all public functions/methods/classes
2. Include edge cases and error handling tests
3. Follow the project's existing test style if tests exist
4. Use the detected test framework ({framework})
5. Name test files according to the framework convention

For each test file, output:
```{language}
# FILE: <test_file_path>
<test code>
```

Focus on:
- Unit tests for individual functions
- Integration tests for connected components
- Edge cases (empty inputs, null values, boundary conditions)
- Error handling (exceptions, invalid inputs)
- Happy path scenarios

Generate comprehensive, runnable tests.
"""

COVERAGE_ANALYSIS_PROMPT = """Analyze the following source code and identify what needs to be tested.

SOURCE CODE:
{source_code}

List all:
1. Public functions/methods that need tests
2. Classes that need tests
3. Critical code paths that should be tested
4. Edge cases that should be covered

Be specific about what each test should verify.
"""


def execute_create_tests(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute test generation for the project.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, tests_created, files, tokens_used, etc.
    """
    Display.phase("create_tests", "Analyzing code and generating tests...")

    # Parse arguments
    coverage_target = "all"  # all, changed, or specific file
    if step.args:
        if len(step.args) > 0:
            coverage_target = str(step.args[0])

    # Detect language and framework
    language = detect_project_language(cwd)
    framework, _ = detect_test_framework(cwd)

    if not language:
        Display.step_error("create_tests", "Could not detect project language")
        return {
            "success": False,
            "error": "Could not detect project language",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    # If no framework detected, suggest one based on language
    if not framework:
        framework = _suggest_framework(language)
        Display.notify(f"No test framework detected, suggesting: {framework}")
    else:
        Display.notify(f"Detected: {language} with {framework}")

    # Get source files to test
    if coverage_target == "changed":
        # Only test files that were changed in this pipeline
        source_files = previous.get("files_changed", [])
        source_files = [f for f in source_files if not _is_test_file(f, framework)]
    elif coverage_target != "all":
        # Specific file or pattern
        source_files = [f for f in get_source_files(cwd, language) if coverage_target in f]
    else:
        source_files = get_source_files(cwd, language)
        # Exclude test files
        source_files = [f for f in source_files if not _is_test_file(f, framework)]

    if not source_files:
        Display.notify("No source files to test")
        return {
            "success": True,
            "skipped": True,
            "reason": "No source files found to test",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Found {len(source_files)} source files to analyze")

    # Get existing tests for style reference
    existing_tests = get_test_files(cwd, framework)
    existing_test_content = ""
    if existing_tests:
        # Read first few test files for style reference
        for test_file in existing_tests[:3]:
            test_path = os.path.join(cwd, test_file)
            content = read_file_content(test_path, max_size=5000)
            existing_test_content += f"\n--- {test_file} ---\n{content}\n"

    # Read source files
    source_content = ""
    for src_file in source_files[:20]:  # Limit to 20 files to avoid context overflow
        src_path = os.path.join(cwd, src_file)
        content = read_file_content(src_path, max_size=10000)
        source_content += f"\n--- {src_file} ---\n{content}\n"

    # Build context from previous steps
    context = prompt
    if previous.get("plan"):
        context += f"\n\nImplementation plan:\n{previous['plan'][:2000]}"

    # Generate tests using AI
    provider = get_provider("claude", config)

    test_prompt = CREATE_TESTS_PROMPT.format(
        language=language,
        framework=framework,
        source_files=source_content,
        existing_tests=existing_test_content if existing_test_content else "No existing tests found.",
        context=context,
    )

    Display.notify("Generating tests with AI...")
    start = time.time()
    result = provider.implement(test_prompt, cwd)
    duration = time.time() - start

    total_tokens = result.tokens_used

    # Track cost
    if cost_manager and result.tokens_used:
        cost_manager.add_cost("claude", result.tokens_used)

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="create_tests",
        agent="test_generator",
        type="generation",
        content=result.content[:5000] if result.content else "",
        metadata={
            "language": language,
            "framework": framework,
            "source_files_count": len(source_files),
            "duration": duration,
            "success": result.success,
        },
    ))

    if not result.success:
        Display.step_error("create_tests", f"Test generation failed: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "files_changed": previous.get("files_changed", []),
            "tokens_used": total_tokens,
        }

    # Parse generated test files from output
    tests_created = _parse_test_files(result.content, language)

    Display.notify(f"Generated {len(tests_created)} test file(s)")

    # Write test files
    files_written = []
    for test_file, test_content in tests_created.items():
        test_path = os.path.join(cwd, test_file)
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        try:
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(test_content)
            files_written.append(test_file)
            Display.notify(f"Created: {test_file}")
        except Exception as e:
            Display.step_error("create_tests", f"Failed to write {test_file}: {e}")

    # Combine with previous files changed
    all_files_changed = list(set(previous.get("files_changed", []) + files_written))

    return {
        "success": True,
        "tests_created": len(files_written),
        "test_files": files_written,
        "framework": framework,
        "language": language,
        "tokens_used": total_tokens,
        "files_changed": all_files_changed,
        "duration": duration,
    }


def _suggest_framework(language: str) -> str:
    """Suggest a test framework based on language."""
    suggestions = {
        "python": "pytest",
        "typescript": "vitest",
        "javascript": "jest",
        "go": "go",
        "rust": "cargo",
    }
    return suggestions.get(language, "pytest")


def _is_test_file(filepath: str, framework: str) -> bool:
    """Check if a file is a test file."""
    filename = os.path.basename(filepath)

    if framework in ["pytest"]:
        return filename.startswith("test_") or filename.endswith("_test.py")
    elif framework in ["jest", "vitest"]:
        return ".test." in filename or ".spec." in filename
    elif framework == "mocha":
        return ".test." in filename
    elif framework == "go":
        return filename.endswith("_test.go")
    elif framework == "cargo":
        return "_test.rs" in filename or "/tests/" in filepath

    return False


def _parse_test_files(content: str, language: str) -> dict[str, str]:
    """Parse test files from AI output.

    Looks for patterns like:
    ```python
    # FILE: tests/test_example.py
    <code>
    ```

    Returns:
        Dict mapping file paths to content.
    """
    import re

    tests = {}

    # Pattern to match code blocks with file markers
    # Matches: ```language\n# FILE: path\n<code>```
    pattern = r'```(?:python|typescript|javascript|go|rust|ts|js)?\s*\n#\s*FILE:\s*([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

    for filepath, code in matches:
        filepath = filepath.strip()
        code = code.strip()
        if filepath and code:
            tests[filepath] = code

    # Alternative pattern: --- filename.py ---
    if not tests:
        pattern = r'---\s*([^\n]+\.(?:py|ts|js|go|rs))\s*---\n(.*?)(?=---|$)'
        matches = re.findall(pattern, content, re.DOTALL)
        for filepath, code in matches:
            filepath = filepath.strip()
            code = code.strip()
            if filepath and code and ("test" in filepath.lower() or "spec" in filepath.lower()):
                tests[filepath] = code

    # If still no tests found, try to extract any code block and create a default test file
    if not tests:
        pattern = r'```(?:python|typescript|javascript|go|rust|ts|js)?\s*\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            # Use first substantial code block
            for code in matches:
                if len(code) > 100 and ("def test_" in code or "describe(" in code or "func Test" in code):
                    ext_map = {
                        "python": "py",
                        "typescript": "ts",
                        "javascript": "js",
                        "go": "go",
                        "rust": "rs",
                    }
                    ext = ext_map.get(language, "py")
                    if language == "python":
                        tests[f"tests/test_generated.{ext}"] = code.strip()
                    elif language in ["typescript", "javascript"]:
                        tests[f"__tests__/generated.test.{ext}"] = code.strip()
                    elif language == "go":
                        tests["generated_test.go"] = code.strip()
                    elif language == "rust":
                        tests["tests/generated_test.rs"] = code.strip()
                    break

    return tests
