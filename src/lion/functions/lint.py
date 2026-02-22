"""lint() - Auto-fix linting issues.

Detects the linter used in the project (ruff, eslint, etc.) and runs
auto-fix to clean up code style issues.
"""

import re
import subprocess
import time
from typing import Optional

from ..memory import MemoryEntry
from ..display import Display
from ..providers import get_provider
from .utils import (
    detect_project_language,
    detect_linter,
    LINTER_PATTERNS,
)
from .self_heal import self_heal_loop

FIX_LINT_ISSUES_PROMPT = """You are an expert software engineer.
The linter has identified issues in the codebase.

Your task is to fix ALL issues mentioned by the linter.
Edit the files directly and be thorough.

LINTER OUTPUT:
{linter_output}
"""


def execute_lint(prompt, previous, step, memory, config, cwd, cost_manager=None) -> dict:
    """Execute linting with auto-fix.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, linter, issues_fixed, output, etc.
    """
    # Defensive null check for previous
    previous = previous or {}

    Display.phase("lint", "Running linter with auto-fix...")

    # Parse arguments
    nofix = False
    specific_linter = None
    # Use step.self_heal as the single source of truth for ^ operator (set by parser)
    self_heal = step.self_heal if hasattr(step, 'self_heal') else False

    if step.args:
        for arg in step.args:
            arg_str = str(arg).lower()
            if arg_str == "nofix" or arg_str == "no_fix":
                nofix = True
            # Skip ^ since it's handled by parser setting step.self_heal
            elif arg_str != "^" and arg_str in ["ruff", "black", "eslint", "prettier", "biome", "gofmt", "rustfmt", "clippy"]:
                specific_linter = arg_str

    # Detect language
    language = detect_project_language(cwd)
    if not language:
        Display.notify("Could not detect project language, skipping lint")
        return {
            "success": True,
            "skipped": True,
            "reason": "Could not detect project language",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Detected language: {language}")

    # Find available linter
    if specific_linter:
        # Use specified linter
        linter_name = specific_linter
        linter_config = _find_linter_config(specific_linter, language)
    else:
        linter_name, linter_config = detect_linter(cwd, language)

    if not linter_config:
        Display.notify(f"No auto-fix linter found for {language}")
        return {
            "success": True,
            "skipped": True,
            "reason": f"No auto-fix linter available for {language}",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Using linter: {linter_name}")

    # Get max heal cost from config
    max_heal_cost = config.get("self_healing", {}).get("max_heal_cost")
    default_provider_name = config.get("providers", {}).get("default", "claude")

    # Run initial lint (with fix if not nofix)
    start = time.time()
    if nofix:
        success, output = _run_lint_check(linter_name, language, cwd)
        action = "check"
    else:
        success, output = _run_lint_fix(linter_config, cwd)
        action = "fix"

        # Also run formatter if available (e.g., ruff format after ruff check --fix)
        if success and linter_config.get("format"):
            Display.notify(f"Running formatter: {linter_name}")
            fmt_success, fmt_output = _run_command(linter_config["format"], cwd)
            output += f"\n\n--- Formatter output ---\n{fmt_output}"

    duration = time.time() - start

    # Parse issues from output
    issues = _parse_lint_issues(output, linter_name)

    Display.notify(f"Linting: {len(issues)} issues found")

    # Log initial run to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="lint",
        agent="linter",
        type="lint_run",
        content=output[:5000],
        metadata={
            "linter": linter_name,
            "language": language,
            "action": action,
            "success": success,
            "issues_count": len(issues),
            "duration": duration,
            "round": 0,
        },
    ))

    # If self-healing and there are issues, use shared self_heal_loop
    if self_heal and issues:
        llm_provider = get_provider(default_provider_name, config)

        # State for check function
        round_counter = [0]
        last_issues = [issues]
        last_output = [output]
        last_success = [success]

        def check_fn():
            """Run linter check and return (passed, issues, content, tokens)."""
            round_counter[0] += 1

            check_start = time.time()
            check_success, check_output = _run_lint_check(linter_name, language, cwd)
            check_duration = time.time() - check_start

            check_issues = _parse_lint_issues(check_output, linter_name)

            # Log to memory
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="lint",
                agent="linter",
                type="lint_run",
                content=check_output[:5000],
                metadata={
                    "linter": linter_name,
                    "language": language,
                    "action": "check",
                    "success": check_success,
                    "issues_count": len(check_issues),
                    "duration": check_duration,
                    "round": round_counter[0],
                },
            ))

            Display.notify(f"Lint check round {round_counter[0] + 1}: {len(check_issues)} issues")

            # Update state for final return
            last_issues[0] = check_issues
            last_output[0] = check_output
            last_success[0] = check_success

            passed = len(check_issues) == 0
            return passed, check_issues, check_output, 0  # linter doesn't use tokens

        def fix_prompt_builder(content: str) -> str:
            """Build fix prompt from linter output."""
            return FIX_LINT_ISSUES_PROMPT.format(linter_output=content)

        heal_result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=fix_prompt_builder,
            provider=llm_provider,
            cwd=cwd,
            max_rounds=2,
            max_cost=max_heal_cost,
            cost_manager=cost_manager,
            provider_name=default_provider_name,
            display_name="lint",
            initial_files_changed=previous.get("files_changed", []),
        )

        return {
            "success": last_success[0],
            "linter": linter_name,
            "language": language,
            "issues": heal_result.issues,
            "issues_count": len(heal_result.issues),
            "output": last_output[0],
            "auto_fixed": not nofix,
            "duration": duration,
            "files_changed": heal_result.files_changed,
            "tokens_used": heal_result.total_tokens,
            "lint_passed": heal_result.passed,
        }

    # Non-self-healing: return initial results
    lint_passed = len(issues) == 0

    return {
        "success": success,
        "linter": linter_name,
        "language": language,
        "issues": issues,
        "issues_count": len(issues),
        "output": output,
        "auto_fixed": not nofix,
        "duration": duration,
        "files_changed": previous.get("files_changed", []),
        "tokens_used": 0,
        "lint_passed": lint_passed,
    }


def _find_linter_config(linter_name: str, language: str) -> Optional[dict]:
    """Find linter config by name."""
    if language not in LINTER_PATTERNS:
        return None

    for linter in LINTER_PATTERNS[language]["linters"]:
        if linter["name"] == linter_name:
            return linter

    return None


def _run_lint_check(linter_name: str, language: str, cwd: str) -> tuple[bool, str]:
    """Run lint check without fix."""
    check_commands = {
        "ruff": ["ruff", "check", "."],
        "black": ["black", "--check", "."],
        "flake8": ["flake8", "."],
        "pylint": ["pylint", "**/*.py"],
        "eslint": ["npx", "eslint", "."],
        "prettier": ["npx", "prettier", "--check", "."],
        "biome": ["npx", "biome", "check", "."],
        "gofmt": ["gofmt", "-l", "."],
        "golangci-lint": ["golangci-lint", "run"],
        "rustfmt": ["cargo", "fmt", "--check"],
        "clippy": ["cargo", "clippy"],
    }

    command = check_commands.get(linter_name)
    if not command:
        return False, f"Unknown linter: {linter_name}"

    return _run_command(command, cwd)


def _run_lint_fix(linter_config: dict, cwd: str) -> tuple[bool, str]:
    """Run lint with auto-fix."""
    if not linter_config.get("fix"):
        return False, "This linter does not support auto-fix"

    return _run_command(linter_config["fix"], cwd)


def _run_command(command: list[str], cwd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = result.stdout + "\n" + result.stderr
        # For linters, return code 0 = no issues, 1 = issues found/fixed
        # We consider both as "success" for the lint function
        success = result.returncode in [0, 1]

        return success, output.strip()

    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {command[0]}"
    except Exception as e:
        return False, f"Error running command: {str(e)}"


def _parse_lint_issues(output: str, linter: str) -> list[dict]:
    """Parse lint issues from output."""
    issues = []

    if linter in ["ruff", "flake8", "pylint"]:
        # Pattern: file.py:line:col: CODE message
        pattern = r'([^:\s]+\.py):(\d+):(\d+):\s*(\w+)\s+(.+)'
        for match in re.finditer(pattern, output):
            issues.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "code": match.group(4),
                "message": match.group(5),
            })

    elif linter in ["eslint", "biome"]:
        # Pattern: file.ts:line:col: message
        pattern = r'([^:\s]+\.[jt]sx?):(\d+):(\d+):\s*(.+)'
        for match in re.finditer(pattern, output):
            issues.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "message": match.group(4),
            })

    elif linter in ["black", "prettier"]:
        # These formatters just list files that would change
        pattern = r'would reformat\s+([^\s]+)|^\s*([^:\s]+\.[a-z]+)$'
        for match in re.finditer(pattern, output, re.MULTILINE):
            filepath = match.group(1) or match.group(2)
            if filepath:
                issues.append({
                    "file": filepath,
                    "message": "File would be reformatted",
                })

    elif linter == "clippy":
        # Rust clippy: warning: message --> file.rs:line:col
        pattern = r'(warning|error):\s*(.+?)\s*-->\s*([^:]+):(\d+):(\d+)'
        for match in re.finditer(pattern, output):
            issues.append({
                "severity": match.group(1),
                "message": match.group(2),
                "file": match.group(3),
                "line": int(match.group(4)),
                "col": int(match.group(5)),
            })

    # Fallback: count lines that look like issues
    if not issues:
        issue_indicators = ["error", "warning", "Error", "Warning", ":"]
        for line in output.split("\n"):
            if any(ind in line for ind in issue_indicators) and len(line) > 10:
                if not line.startswith(("All", "Done", "Success", "No", "✓", "✔")):
                    issues.append({"raw": line.strip()})

    return issues[:100]  # Limit to 100 issues
