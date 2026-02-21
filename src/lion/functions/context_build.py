"""context() - Build shared mental model.

Runs BEFORE the pride. Creates a shared understanding of the codebase
that all agents receive. This prevents agents from wasting their
proposal tokens on rediscovering what the codebase looks like.

Example usage:
    lion "Build payment system" -> context() -> pride(3) -> review()

Why this saves tokens overall:
- Without context(), each of the 3 agents in the pride independently
  examines the codebase and wastes ~500 tokens describing what they found.
- With context(), one agent does it once (~800 tokens), and the others
  don't repeat it. Net saving: ~700 tokens.

Recommendation: Use context() when pride has 3+ agents or when the
codebase is unfamiliar.
"""

import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..context import CONTEXT_PROMPT, estimate_tokens


def execute_context(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Build shared mental model for the pride.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, content, shared_context, tokens_used
    """
    # Get provider (prefer cheap provider for context building)
    context_config = config.get("context", {})
    provider_name = step.kwargs.get("provider",
                    context_config.get("context_provider",
                    config.get("providers", {}).get("default", "claude")))

    try:
        provider = get_provider(provider_name, config)
    except Exception:
        provider_name = config.get("providers", {}).get("default", "claude")
        provider = get_provider(provider_name, config)

    Display.phase("context", f"Building shared context using {provider_name}...")

    # Build context prompt
    context_prompt = CONTEXT_PROMPT.format(
        prompt=prompt,
        cwd=cwd
    )

    start = time.time()
    result = provider.ask(context_prompt, "", cwd)
    duration = time.time() - start

    if not result.success or not result.content:
        Display.step_error("context", result.error or "Context building failed")
        return {
            "success": False,
            "content": "",
            "shared_context": "",
            "tokens_used": result.tokens_used if result else 0,
        }

    context_tokens = estimate_tokens(result.content)

    # Track cost if manager provided
    if cost_manager and result.tokens_used:
        cost_manager.add_cost(provider_name, result.tokens_used)

    # Store as shared context
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="context",
        agent="context_builder",
        type="shared_context",
        content=result.content,
        metadata={
            "model": result.model,
            "tokens": context_tokens,
            "duration": duration,
        },
    ))

    Display.notify(
        f"Built shared context ({context_tokens} tokens) "
        f"to share with all agents"
    )

    return {
        "success": True,
        "content": result.content,
        "shared_context": result.content,
        "tokens_used": result.tokens_used,
        "files_changed": previous.get("files_changed", []),
    }
