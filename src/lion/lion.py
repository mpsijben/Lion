"""Lion - Main CLI entry point."""

import sys
import os
import time
import json

from .parser import parse_lion_input
from .pipeline import PipelineExecutor
from .display import Display

LION_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_config():
    """Load config from config.toml if it exists."""
    for config_path in [
        os.path.join(LION_DIR, "config.toml"),
        os.path.join(LION_DIR, "config.default.toml"),
        os.path.expanduser("~/.lion/config.toml"),
    ]:
        if os.path.exists(config_path):
            try:
                import tomllib
                with open(config_path, "rb") as f:
                    return tomllib.load(f)
            except Exception:
                pass
    return {}


def detect_complexity(prompt: str, config: dict) -> str:
    """Detect task complexity using simple heuristics (0 tokens)."""
    prompt_lower = prompt.lower()
    high = config.get("complexity", {}).get("high_signals", [
        "build", "create", "design", "architect", "migrate",
        "refactor", "system", "complete", "full",
    ])
    low = config.get("complexity", {}).get("low_signals", [
        "fix", "bug", "typo", "rename", "change",
        "update", "move", "delete", "remove",
    ])

    high_score = sum(1 for s in high if s in prompt_lower)
    low_score = sum(1 for s in low if s in prompt_lower)

    if high_score > low_score + 1:
        return "high"
    elif low_score > high_score:
        return "low"
    else:
        return "medium"


def main():
    if len(sys.argv) < 2:
        print("\U0001f981 Lion - Language for Intelligent Orchestration Networks")
        print()
        print("Usage:")
        print('  lion "Build a feature"')
        print('  lion "Build a feature" -> pride(3)')
        print()
        print("Pipeline functions:")
        print("  pride(n)     Multi-agent deliberation")
        print("  review()     Code review")
        print("  test()       Run tests with auto-fix")
        print("  devil()      Devil's advocate challenge")
        print("  future(Nm)   Time-travel review")
        print("  audit()      Security audit")
        print("  pr(branch)   Create git PR")
        sys.exit(0)

    # Join all arguments (handles shell quoting)
    raw_input = " ".join(sys.argv[1:])

    # Load config
    config = load_config()

    # Parse input into prompt + pipeline
    prompt, pipeline_steps = parse_lion_input(raw_input, config)

    # No pipeline specified = single agent, no pride
    # User must explicitly request pride() in the pipeline

    # Get working directory
    cwd = os.environ.get("LION_CWD", os.getcwd())

    # Create run directory inside the project (.lion/runs/)
    run_id = (
        time.strftime("%Y-%m-%d_%H%M%S")
        + "_"
        + prompt[:30].replace(" ", "_").replace("/", "_")
    )
    run_dir = os.path.join(cwd, ".lion", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Execute pipeline
    executor = PipelineExecutor(
        prompt=prompt,
        steps=pipeline_steps,
        config=config,
        run_dir=run_dir,
        cwd=cwd,
    )

    # Running from hook? (hook sets LION_SESSION_ID)
    from_hook = "LION_SESSION_ID" in os.environ

    try:
        result = executor.run()

        # Show result in terminal (single agent content or pride decision)
        if result.content:
            Display.agent_result(result.content)
        elif result.final_decision:
            Display.agent_result(result.final_decision)

        Display.final_result(result)

        # LION_SUMMARY on stdout only when called from hook
        if from_hook:
            summary = Display.format_completion_summary(
                result.agent_summaries,
                result.final_decision,
                result.success,
                result.content,
            )
            summary_json = {
                "success": result.success,
                "summary": summary,
                "agent_summaries": result.agent_summaries,
                "final_decision": result.final_decision,
                "files_changed": result.files_changed,
                "duration": result.total_duration,
            }
            print(f"LION_SUMMARY:{json.dumps(summary_json)}")

    except KeyboardInterrupt:
        Display.cancelled()
        if from_hook:
            print(f"LION_SUMMARY:{json.dumps({'success': False, 'summary': 'Lion geannuleerd door gebruiker'})}")
    except Exception as e:
        Display.error(str(e))
        if from_hook:
            print(f"LION_SUMMARY:{json.dumps({'success': False, 'summary': f'Lion fout: {str(e)}'})}")
        raise
