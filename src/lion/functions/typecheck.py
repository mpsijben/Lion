"""typecheck() - Type checking function.

Runs the project's type checker (mypy, pyright, tsc, etc.) and optionally
uses AI to fix type errors.
"""

import re
import subprocess
import time
import os
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..escalation import Escalation
from .utils import (
    detect_project_language,
    detect_type_checker,
    TYPE_CHECKER_PATTERNS,
)
from .self_heal import estimate_cost


FIX_TYPE_ERRORS_PROMPT = """Fix the following type errors in the code.

TYPE CHECKER: {checker}
TYPE ERRORS:
{errors}

ORIGINAL TASK CONTEXT:
{context}

Fix the type errors by:
1. Adding proper type annotations
2. Fixing type mismatches
3. Adding type guards where needed
4. Using proper generic types

Make minimal changes to fix the type errors. Do not change functionality.
"""


def execute_typecheck(prompt, previous, step, memory, config, cwd, cost_manager=None) -> dict:
    """Execute type checking with optional auto-fix.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, errors, fixed, tokens_used, etc.
    """
    # Defensive null check for previous
    previous = previous or {}

    Display.phase("typecheck", "Running type checker...")

    # Parse arguments
    nofix = False
    strict = False
    self_heal = step.self_heal if hasattr(step, 'self_heal') else False
    if step.args:
        for arg in step.args:
            arg_str = str(arg).lower()
            if arg_str == "nofix" or arg_str == "no_fix":
                nofix = True
            elif arg_str == "strict":
                strict = True
            # Note: ^ is handled by parser setting step.self_heal, no need to check here

    # Detect language
    language = detect_project_language(cwd)
    if not language:
        Display.notify("Could not detect project language, skipping typecheck")
        return {
            "success": True,
            "skipped": True,
            "reason": "Could not detect project language",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    # For JavaScript, type checking doesn't apply
    if language == "javascript":
        Display.notify("JavaScript does not have static type checking, skipping")
        return {
            "success": True,
            "skipped": True,
            "reason": "JavaScript does not have static type checking",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Detected language: {language}")

    # Find type checker
    checker_name, checker_config = detect_type_checker(cwd, language)

    if not checker_config:
        Display.notify(f"No type checker found for {language}")
        return {
            "success": True,
            "skipped": True,
            "reason": f"No type checker available for {language}",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    Display.notify(f"Using type checker: {checker_name}")

    # Build command with optional strict mode
    command = checker_config["command"].copy()
    if strict:
        if checker_name == "mypy":
            command.append("--strict")
        elif checker_name == "pyright":
            command.extend(["--level", "strict"])
        elif checker_name == "tsc":
            command.append("--strict")

    total_tokens = 0
    fixed = False
    all_files_changed = previous.get("files_changed", [])
    last_output = ""
    last_errors = []

    # Get max heal cost from config for cost budget check
    max_heal_cost = config.get("self_healing", {}).get("max_heal_cost")
    cumulative_cost = 0.0

    MAX_SELF_HEAL_ROUNDS = 2
    for self_heal_round in range(MAX_SELF_HEAL_ROUNDS + 1):
        Display.notify(f"Type check round {self_heal_round + 1}/{MAX_SELF_HEAL_ROUNDS + 1}...")
        
        # Existing auto-fix loop (up to 3 attempts with built-in AI fix)
        max_retries = 3 if not nofix else 1
        attempt = 0
        current_errors_fixed = False

        while attempt < max_retries:
            attempt += 1
            Display.notify(f"Running type check (attempt {attempt}/{max_retries})...")

            start = time.time()
            success, output = _run_command(command, cwd)
            duration = time.time() - start

            last_output = output
            errors = _parse_type_errors(output, checker_name)
            last_errors = errors

            # Log to memory
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="typecheck",
                agent="type_checker",
                type="check_run",
                content=output[:5000],
                metadata={
                    "checker": checker_name,
                    "language": language,
                    "attempt": attempt,
                    "success": success,
                    "errors_count": len(errors),
                    "duration": duration,
                    "self_heal_round": self_heal_round,
                },
            ))

            if success or len(errors) == 0:
                current_errors_fixed = True
                break # All errors fixed in this inner loop

            # Type errors found
            Display.step_error("typecheck", f"Found {len(errors)} type error(s)")

            if nofix:
                break # No-fix mode, don't try AI fix

            # Try to auto-fix with built-in AI
            if attempt < max_retries:
                # Check cost budget before fix attempt
                if max_heal_cost and cumulative_cost >= max_heal_cost:
                    Display.notify(f"Cost limit reached ({cumulative_cost:.4f} >= {max_heal_cost}), stopping typecheck auto-fix")
                    break

                default_provider = config.get("providers", {}).get("default", "claude")
                Display.notify(f"Attempting built-in AI auto-fix with {default_provider}...")

                provider = get_provider(default_provider, config)

                # Format errors for prompt
                error_text = "\n".join([
                    f"- {e.get('file', 'unknown')}:{e.get('line', '?')}: {e.get('message', e.get('raw', 'Unknown error'))}"
                    for e in errors[:20]  # Limit to 20 errors
                ])

                fix_prompt = FIX_TYPE_ERRORS_PROMPT.format(
                    checker=checker_name,
                    errors=error_text,
                    context=prompt,
                )

                result = provider.implement(fix_prompt, cwd)
                total_tokens += result.tokens_used
                # Track cumulative cost using provider-specific rates
                cumulative_cost += estimate_cost(default_provider, result.tokens_used)

                if cost_manager and result.tokens_used:
                    cost_manager.add_cost(default_provider, result.tokens_used)

                if result.success:
                    fixed = True
                    # Note: AgentResult doesn't track files_changed; provider.implement() modifies files directly
                    memory.write(MemoryEntry(
                        timestamp=time.time(),
                        phase="typecheck",
                        agent="fixer",
                        type="fix",
                        content=result.content[:3000] if result.content else "",
                        metadata={
                            "attempt": attempt,
                            "model": result.model,
                            "self_heal_round": self_heal_round,
                        },
                    ))
                else:
                    # Fix failed
                    action = Escalation.agent_stuck(
                        "type_fixer",
                        f"Could not built-in AI auto-fix type errors: {result.error}",
                        retries_left=max_retries - attempt
                    )

                    if action == "skip":
                        break
                    elif action == "takeover":
                        return {
                            "success": False,
                            "takeover": True,
                            "checker": checker_name,
                            "errors": last_errors,
                            "errors_count": len(last_errors),
                            "output": last_output,
                            "attempts": attempt,
                            "files_changed": list(set(all_files_changed)),
                            "tokens_used": total_tokens,
                        }

        # End of inner auto-fix loop
        
        if current_errors_fixed:
            break # All errors fixed, no need for more self-heal rounds

        if not self_heal or len(last_errors) == 0:
            # If not self-healing, or no errors left, we're done
            break
        
        if self_heal_round == MAX_SELF_HEAL_ROUNDS:
            Display.notify("Max self-heal rounds reached. Continuing pipeline with remaining type errors.")
            break

        # Check cost budget before self-healing
        if max_heal_cost and cumulative_cost >= max_heal_cost:
            Display.notify(f"Cost limit reached ({cumulative_cost:.4f} >= {max_heal_cost}), stopping typecheck self-heal")
            break

        # Self-heal with LLM if critical errors still exist after built-in attempts
        Display.phase("typecheck", f"Self-healing remaining type errors (round {self_heal_round + 1}/{MAX_SELF_HEAL_ROUNDS})...")

        # We need a provider for LLM intervention here. Assume default provider.
        # This is already handled by `provider.implement` if `nofix` is false
        # and `MAX_RETRIES` has not been reached.
        # The self-healing here is for persistent errors *after* all built-in retries.

        default_provider_name = config.get("providers", {}).get("default", "claude")
        llm_provider = get_provider(default_provider_name, config)

        error_text = "\n".join([
            f"- {e.get('file', 'unknown')}:{e.get('line', '?')}: {e.get('message', e.get('raw', 'Unknown error'))}"
            for e in last_errors[:20]  # Limit to 20 errors
        ])
        fix_prompt = FIX_TYPE_ERRORS_PROMPT.format(
            checker=checker_name,
            errors=error_text,
            context=prompt,
        )

        result = llm_provider.implement(fix_prompt, cwd)
        total_tokens += result.tokens_used
        # Track cumulative cost using provider-specific rates
        cumulative_cost += estimate_cost(default_provider_name, result.tokens_used)
        if cost_manager and result.tokens_used:
            cost_manager.add_cost(default_provider_name, result.tokens_used)
        
        if not result.success:
            Display.step_error("typecheck", "Self-healing failed: " + (result.error or "Unknown error"))
            break

        fixed = True
        # Note: AgentResult doesn't track files_changed; provider.implement() modifies files directly
        Display.notify(f"Self-healing complete. Re-running type check to verify...")


    # typecheck_passed is True if no errors remain after all rounds
    typecheck_passed = len(last_errors) == 0

    # Return final state
    return {
        "success": len(last_errors) == 0,
        "checker": checker_name,
        "language": language,
        "errors": last_errors,
        "errors_count": len(last_errors),
        "output": last_output,
        "attempts": attempt,
        "fixed": fixed,
        "max_retries_exhausted": len(last_errors) > 0,
        "files_changed": list(set(all_files_changed)),
        "tokens_used": total_tokens,
        "typecheck_passed": typecheck_passed,
    }


def _run_command(command: list[str], cwd: str, timeout: int = 180) -> tuple[bool, str]:
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
        success = result.returncode == 0

        return success, output.strip()

    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {command[0]}"
    except Exception as e:
        return False, f"Error running command: {str(e)}"


def _parse_type_errors(output: str, checker: str) -> list[dict]:
    """Parse type errors from checker output."""
    errors = []

    if checker == "mypy":
        # Pattern: file.py:line: error: message
        pattern = r'([^:\s]+\.py):(\d+):\s*(error|warning):\s*(.+)'
        for match in re.finditer(pattern, output):
            errors.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "severity": match.group(3),
                "message": match.group(4),
            })

    elif checker == "pyright":
        # Pattern: file.py:line:col - error: message
        pattern = r'([^:\s]+\.py):(\d+):(\d+)\s*-\s*(error|warning|information):\s*(.+)'
        for match in re.finditer(pattern, output):
            errors.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "severity": match.group(4),
                "message": match.group(5),
            })

    elif checker == "tsc":
        # Pattern: file.ts(line,col): error TS####: message
        pattern = r'([^(\s]+)\((\d+),(\d+)\):\s*(error|warning)\s+TS\d+:\s*(.+)'
        for match in re.finditer(pattern, output):
            errors.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "severity": match.group(4),
                "message": match.group(5),
            })

    elif checker == "go vet":
        # Pattern: file.go:line:col: message
        pattern = r'([^:\s]+\.go):(\d+):(\d+):\s*(.+)'
        for match in re.finditer(pattern, output):
            errors.append({
                "file": match.group(1),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "message": match.group(4),
            })

    elif checker == "cargo check":
        # Pattern: error[E####]: message --> file.rs:line:col
        pattern = r'(error|warning)\[?\w*\]?:\s*(.+?)\s*-->\s*([^:]+):(\d+):(\d+)'
        for match in re.finditer(pattern, output):
            errors.append({
                "severity": match.group(1),
                "message": match.group(2),
                "file": match.group(3),
                "line": int(match.group(4)),
                "col": int(match.group(5)),
            })

    # Fallback: look for error-like lines
    if not errors:
        for line in output.split("\n"):
            if "error" in line.lower() and ":" in line:
                errors.append({"raw": line.strip()})

    return errors[:50]  # Limit to 50 errors
