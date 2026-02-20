"""pr() - Git branch and Pull Request creation.

Creates a git branch from the first arg (e.g., pr("feature/stripe")),
stages all changes, commits with a summary, and creates a PR using gh cli.
"""

import subprocess
import time
import re
from typing import Optional

from ..memory import MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..escalation import Escalation


COMMIT_MESSAGE_PROMPT = """Generate a concise git commit message for the following changes.

ORIGINAL TASK:
{prompt}

PLAN/DECISION:
{decision}

FILES CHANGED:
{files}

Write a commit message following conventional commits format:
- Start with a type: feat, fix, refactor, docs, test, chore
- Keep the first line under 72 characters
- Optionally add a body with more details

Output ONLY the commit message, nothing else.
"""

PR_BODY_PROMPT = """Generate a Pull Request description for the following changes.

ORIGINAL TASK:
{prompt}

PLAN/DECISION:
{decision}

FILES CHANGED:
{files}

COMMIT MESSAGE:
{commit_message}

Generate a PR description with:
## Summary
[1-3 bullet points describing the changes]

## Changes
[List of key changes made]

## Testing
[How to test the changes]

Output ONLY the PR body in markdown format.
"""


def execute_pr(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Create git branch, commit changes, and optionally create PR.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args (branch name)
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, branch, commit, pr_url, etc.
    """
    Display.phase("pr", "Creating git branch and pull request...")

    # Get branch name from args or generate one
    branch_name = None
    if step.args:
        branch_name = str(step.args[0])

    if not branch_name:
        # Generate branch name from prompt
        branch_name = _generate_branch_name(prompt)

    # Check if we're in a git repo
    if not _is_git_repo(cwd):
        return {
            "success": False,
            "error": "Not a git repository",
            "files_changed": previous.get("files_changed", []),
            "tokens_used": 0,
        }

    # Check for uncommitted changes
    has_changes, changed_files = _get_git_status(cwd)
    if not has_changes:
        return {
            "success": True,
            "skipped": True,
            "reason": "No changes to commit",
            "files_changed": [],
            "tokens_used": 0,
        }

    Display.notify(f"Found {len(changed_files)} changed files")

    # Get the main/master branch name
    main_branch = _get_main_branch(cwd)

    # Create and checkout new branch
    success, error = _create_branch(branch_name, cwd)
    if not success:
        # Branch might already exist or other error
        if "already exists" in error.lower():
            Display.notify(f"Branch {branch_name} already exists, using it")
            _checkout_branch(branch_name, cwd)
        else:
            return {
                "success": False,
                "error": f"Failed to create branch: {error}",
                "files_changed": previous.get("files_changed", []),
                "tokens_used": 0,
            }

    Display.notify(f"Created branch: {branch_name}")

    # Stage all changes
    _stage_all(cwd)

    # Generate commit message
    default_provider = config.get("providers", {}).get("default", "claude")
    provider = get_provider(default_provider, config)
    total_tokens = 0

    decision = previous.get("final_decision", "") or previous.get("plan", "")[:500]
    files_list = "\n".join(changed_files[:20])  # Limit to 20 files

    commit_prompt = COMMIT_MESSAGE_PROMPT.format(
        prompt=prompt,
        decision=decision,
        files=files_list,
    )

    result = provider.ask(commit_prompt, "", cwd)
    total_tokens += result.tokens_used

    commit_message = result.content.strip()
    if not commit_message:
        commit_message = f"feat: {prompt[:50]}"

    # Clean up commit message (remove markdown code blocks if present)
    commit_message = _clean_commit_message(commit_message)

    Display.notify(f"Commit message: {commit_message.split(chr(10))[0]}")

    # Commit changes
    success, error = _commit(commit_message, cwd)
    if not success:
        return {
            "success": False,
            "error": f"Failed to commit: {error}",
            "branch": branch_name,
            "files_changed": changed_files,
            "tokens_used": total_tokens,
        }

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="pr",
        agent="pr_creator",
        type="commit",
        content=commit_message,
        metadata={
            "branch": branch_name,
            "files": changed_files[:10],
        },
    ))

    # Push to remote
    success, error = _push(branch_name, cwd)
    if not success:
        # Might not have a remote or permission issues
        Display.notify(f"Could not push to remote: {error}")
        return {
            "success": True,
            "branch": branch_name,
            "commit_message": commit_message,
            "pushed": False,
            "push_error": error,
            "files_changed": changed_files,
            "tokens_used": total_tokens,
        }

    Display.notify(f"Pushed to origin/{branch_name}")

    # Check if gh cli is available and create PR
    if not _has_gh_cli():
        Display.notify("gh CLI not found, skipping PR creation")
        return {
            "success": True,
            "branch": branch_name,
            "commit_message": commit_message,
            "pushed": True,
            "pr_url": None,
            "pr_skipped": "gh CLI not installed",
            "files_changed": changed_files,
            "tokens_used": total_tokens,
        }

    # Generate PR body
    pr_prompt = PR_BODY_PROMPT.format(
        prompt=prompt,
        decision=decision,
        files=files_list,
        commit_message=commit_message,
    )

    result = provider.ask(pr_prompt, "", cwd)
    total_tokens += result.tokens_used

    pr_body = result.content.strip()
    pr_title = commit_message.split("\n")[0]

    # Create PR
    success, pr_url, error = _create_pr(pr_title, pr_body, main_branch, cwd)

    if not success:
        Display.notify(f"Could not create PR: {error}")
        return {
            "success": True,
            "branch": branch_name,
            "commit_message": commit_message,
            "pushed": True,
            "pr_url": None,
            "pr_error": error,
            "files_changed": changed_files,
            "tokens_used": total_tokens,
        }

    Display.notify(f"Created PR: {pr_url}")

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="pr",
        agent="pr_creator",
        type="pr",
        content=pr_body[:1000],
        metadata={
            "branch": branch_name,
            "pr_url": pr_url,
            "title": pr_title,
        },
    ))

    return {
        "success": True,
        "branch": branch_name,
        "commit_message": commit_message,
        "pushed": True,
        "pr_url": pr_url,
        "pr_title": pr_title,
        "files_changed": changed_files,
        "tokens_used": total_tokens,
    }


def _generate_branch_name(prompt: str) -> str:
    """Generate a branch name from the prompt."""
    # Extract key words
    words = re.sub(r'[^a-zA-Z0-9\s]', '', prompt.lower()).split()

    # Filter common words
    stop_words = {'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'and', 'or', 'is', 'it', 'this', 'that'}
    words = [w for w in words if w not in stop_words and len(w) > 2][:4]

    if not words:
        words = ["feature", "update"]

    branch = "feature/" + "-".join(words)

    # Ensure valid branch name
    branch = re.sub(r'[^a-zA-Z0-9/-]', '', branch)
    branch = branch[:50]  # Limit length

    return branch


def _is_git_repo(cwd: str) -> bool:
    """Check if directory is a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _get_git_status(cwd: str) -> tuple[bool, list[str]]:
    """Get git status and return (has_changes, changed_files)."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, []

    lines = result.stdout.strip().split("\n")
    files = [line[3:].strip() for line in lines if line.strip()]

    return len(files) > 0, files


def _get_main_branch(cwd: str) -> str:
    """Determine the main branch name (main or master)."""
    # Check for origin/main
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return "main"

    # Check for origin/master
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/master"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return "master"

    # Check local branches
    result = subprocess.run(
        ["git", "branch", "--list", "main"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if "main" in result.stdout:
        return "main"

    return "master"


def _create_branch(branch_name: str, cwd: str) -> tuple[bool, str]:
    """Create and checkout a new branch."""
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def _checkout_branch(branch_name: str, cwd: str) -> bool:
    """Checkout an existing branch."""
    result = subprocess.run(
        ["git", "checkout", branch_name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _stage_all(cwd: str) -> bool:
    """Stage all changes."""
    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _commit(message: str, cwd: str) -> tuple[bool, str]:
    """Commit staged changes."""
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def _push(branch_name: str, cwd: str) -> tuple[bool, str]:
    """Push branch to origin."""
    result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def _has_gh_cli() -> bool:
    """Check if gh CLI is available."""
    result = subprocess.run(
        ["gh", "--version"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _create_pr(title: str, body: str, base_branch: str, cwd: str) -> tuple[bool, Optional[str], str]:
    """Create a pull request using gh CLI.

    Returns (success, pr_url, error).
    """
    result = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base_branch],
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, None, result.stderr

    # Extract PR URL from output
    pr_url = result.stdout.strip()
    if not pr_url.startswith("http"):
        # Try to find URL in output
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if "github.com" in line and "/pull/" in line:
                pr_url = line.strip()
                break

    return True, pr_url, ""


def _clean_commit_message(message: str) -> str:
    """Clean up commit message from Claude response."""
    # Remove markdown code blocks
    message = re.sub(r'^```[a-zA-Z]*\n?', '', message)
    message = re.sub(r'\n?```$', '', message)

    # Remove leading/trailing whitespace
    message = message.strip()

    # Ensure first line is not too long
    lines = message.split("\n")
    if lines and len(lines[0]) > 72:
        first_line = lines[0][:69] + "..."
        lines[0] = first_line
        message = "\n".join(lines)

    return message
