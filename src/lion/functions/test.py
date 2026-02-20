"""test() - Test runner with auto-fix.

Detects the test framework (pytest/jest/etc), runs tests, captures failures,
and auto-fixes up to 3 retries using claude -p.
"""

import subprocess
import time
import os
import re
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..escalation import Escalation


# Framework detection patterns
FRAMEWORK_PATTERNS = {
    "pytest": {
        "files": ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"],
        "markers": ["import pytest", "def test_"],
        "command": ["pytest", "-v", "--tb=short"],
        "file_glob": "**/*test*.py",
    },
    "jest": {
        "files": ["jest.config.js", "jest.config.ts", "jest.config.json"],
        "markers": ["describe(", "it(", "test(", "expect("],
        "command": ["npm", "test", "--"],
        "file_glob": "**/*.test.{js,ts,tsx}",
    },
    "vitest": {
        "files": ["vitest.config.ts", "vitest.config.js"],
        "markers": ["describe(", "it(", "test(", "expect("],
        "command": ["npm", "run", "test"],
        "file_glob": "**/*.test.{js,ts,tsx}",
    },
    "mocha": {
        "files": [".mocharc.json", ".mocharc.js", ".mocharc.yaml"],
        "markers": ["describe(", "it(", "expect("],
        "command": ["npm", "test"],
        "file_glob": "**/*.test.js",
    },
    "go": {
        "files": ["go.mod"],
        "markers": ["func Test"],
        "command": ["go", "test", "-v", "./..."],
        "file_glob": "**/*_test.go",
    },
    "cargo": {
        "files": ["Cargo.toml"],
        "markers": ["#[test]", "#[cfg(test)]"],
        "command": ["cargo", "test"],
        "file_glob": "**/tests/*.rs",
    },
}

FIX_PROMPT = """The following test failures occurred. Fix the code to make the tests pass.

TEST COMMAND: {command}

TEST OUTPUT:
{output}

FAILING TEST DETAILS:
{failures}

ORIGINAL TASK:
{original_prompt}

Fix the issues in the code. Make minimal changes to fix the failing tests.
Do not modify the tests themselves unless they are clearly incorrect.
"""


def execute_test(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute test runner with optional auto-fix.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, test_output, fixed, attempts, etc.
    """
    # Check for nofix arg
    nofix = False
    if step.args:
        if "nofix" in step.args or "no_fix" in step.args:
            nofix = True

    max_retries = 3

    Display.phase("test", "Detecting test framework and running tests...")

    # Detect test framework
    framework, command = _detect_framework(cwd)

    if not framework:
        return {
            "success": True,
            "skipped": True,
            "reason": "No test framework detected",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Detected framework: {framework}")

    # Run tests
    attempt = 0
    last_output = ""
    fixed = False
    total_tokens = 0

    while attempt < max_retries:
        attempt += 1
        Display.notify(f"Running tests (attempt {attempt}/{max_retries})...")

        success, output = _run_tests(command, cwd)
        last_output = output

        # Log test run to memory
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="test",
            agent="test_runner",
            type="test_run",
            content=output[:5000],  # Truncate for memory
            metadata={
                "framework": framework,
                "attempt": attempt,
                "success": success,
            },
        ))

        if success:
            Display.notify("All tests passed!")
            return {
                "success": True,
                "test_output": output,
                "framework": framework,
                "attempts": attempt,
                "fixed": fixed,
                "files_changed": previous.get("files_changed", []),
                "tokens_used": total_tokens,
            }

        # Tests failed
        Display.step_error("test", f"Test failures detected (attempt {attempt})")

        if nofix:
            return {
                "success": False,
                "test_output": output,
                "framework": framework,
                "attempts": attempt,
                "nofix": True,
                "files_changed": previous.get("files_changed", []),
                "tokens_used": 0,
            }

        # Auto-fix with claude -p
        if attempt < max_retries:
            Display.notify("Attempting auto-fix with Claude...")

            # Extract failure details
            failures = _extract_failures(output, framework)

            provider = get_provider("claude", config)

            fix_prompt = FIX_PROMPT.format(
                command=" ".join(command),
                output=output[-8000:],  # Last 8KB of output
                failures=failures,
                original_prompt=prompt,
            )

            result = provider.implement(fix_prompt, cwd)
            total_tokens += result.tokens_used

            if result.success:
                fixed = True
                memory.write(MemoryEntry(
                    timestamp=time.time(),
                    phase="test",
                    agent="fixer",
                    type="fix",
                    content=result.content[:3000],
                    metadata={
                        "attempt": attempt,
                        "model": result.model,
                    },
                ))
            else:
                # Fix failed - ask user for help
                action = Escalation.agent_stuck(
                    "test_fixer",
                    f"Could not auto-fix test failures: {result.error}",
                    retries_left=max_retries - attempt
                )

                if action == "skip":
                    break
                elif action == "takeover":
                    return {
                        "success": False,
                        "takeover": True,
                        "test_output": output,
                        "framework": framework,
                        "attempts": attempt,
                        "files_changed": previous.get("files_changed", []),
                        "tokens_used": total_tokens,
                    }
                elif action.startswith("hint:"):
                    # Add hint to next fix attempt - continue loop
                    pass

    # Max retries exhausted
    return {
        "success": False,
        "test_output": last_output,
        "framework": framework,
        "attempts": attempt,
        "fixed": fixed,
        "max_retries_exhausted": True,
        "files_changed": previous.get("files_changed", []),
        "tokens_used": total_tokens,
    }


def _detect_framework(cwd: str) -> tuple[Optional[str], list[str]]:
    """Detect the test framework used in the project.

    Returns:
        Tuple of (framework_name, command) or (None, []) if not detected.
    """
    for framework, info in FRAMEWORK_PATTERNS.items():
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
                        return "pytest", FRAMEWORK_PATTERNS["pytest"]["command"]
            except Exception:
                pass

    # Check for test files directly
    for framework, info in FRAMEWORK_PATTERNS.items():
        if framework == "pytest":
            # Look for test_*.py or *_test.py
            for root, dirs, files in os.walk(cwd):
                # Skip hidden dirs and common non-test dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '.venv', '__pycache__']]
                for f in files:
                    if f.startswith("test_") and f.endswith(".py"):
                        return "pytest", info["command"]
                    if f.endswith("_test.py"):
                        return "pytest", info["command"]

    return None, []


def _run_tests(command: list[str], cwd: str) -> tuple[bool, str]:
    """Run the test command and return (success, output)."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        output = result.stdout + "\n" + result.stderr
        success = result.returncode == 0

        return success, output

    except subprocess.TimeoutExpired:
        return False, "Test execution timed out (5 minute limit)"
    except FileNotFoundError:
        return False, f"Test command not found: {command[0]}"
    except Exception as e:
        return False, f"Error running tests: {str(e)}"


def _extract_failures(output: str, framework: str) -> str:
    """Extract relevant failure information from test output."""
    failures = []

    if framework == "pytest":
        # Look for FAILED lines and assertion errors
        lines = output.split("\n")
        in_failure = False
        current_failure = []

        for line in lines:
            if "FAILED" in line or "ERROR" in line:
                in_failure = True
                current_failure = [line]
            elif in_failure:
                if line.strip().startswith("=") and len(line.strip()) > 10:
                    # End of failure section
                    failures.append("\n".join(current_failure))
                    in_failure = False
                    current_failure = []
                else:
                    current_failure.append(line)

        if current_failure:
            failures.append("\n".join(current_failure))

    elif framework in ["jest", "vitest", "mocha"]:
        # Look for failure markers
        lines = output.split("\n")
        in_failure = False
        current_failure = []

        for line in lines:
            if "FAIL" in line or "✕" in line or "✗" in line:
                in_failure = True
                current_failure = [line]
            elif in_failure:
                if line.strip() == "" and len(current_failure) > 5:
                    failures.append("\n".join(current_failure))
                    in_failure = False
                    current_failure = []
                else:
                    current_failure.append(line)

        if current_failure:
            failures.append("\n".join(current_failure))

    elif framework == "go":
        # Look for --- FAIL: lines
        pattern = r"--- FAIL:.*?(?=--- |FAIL\t|ok\t|\Z)"
        matches = re.findall(pattern, output, re.DOTALL)
        failures.extend(matches)

    elif framework == "cargo":
        # Look for failures section
        pattern = r"failures:.*?(?=test result:|\Z)"
        matches = re.findall(pattern, output, re.DOTALL)
        failures.extend(matches)

    if not failures:
        # Fallback: return last 2000 chars of output
        return output[-2000:]

    return "\n\n---\n\n".join(failures[:5])  # Max 5 failures
