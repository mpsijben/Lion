"""distill() - Context compression function.

Compresses accumulated context from previous pipeline steps.
Critical for long pipelines where context would otherwise balloon.

Example usage:
    lion "Build X" -> pride(5) -> distill() -> devil() -> review()

Without distill(), devil gets ALL 5 proposals + ALL 5 critiques +
the convergence plan = potentially 15,000+ tokens of context.
With distill(), devil gets a compressed summary = ~2,000 tokens.
"""

import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..context import DISTILL_PROMPT, estimate_tokens


def execute_distill(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute context compression.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, content, original_tokens, compressed_tokens, ratio
    """
    # Get provider (default to cheap provider for compression)
    context_config = config.get("context", {})
    provider_name = step.kwargs.get("provider",
                    context_config.get("distill_provider", "gemini"))

    # Fallback to default provider if specified provider not available
    try:
        provider = get_provider(provider_name, config)
    except Exception:
        provider_name = config.get("providers", {}).get("default", "claude")
        provider = get_provider(provider_name, config)

    Display.phase("distill", f"Compressing context using {provider_name}...")

    # Calculate current context size
    all_entries = memory.read_all()
    full_text = memory.format_for_prompt(all_entries)
    original_tokens = estimate_tokens(full_text)

    # Target: compress to 25% of original, minimum 500, maximum 3000
    target_tokens = max(500, min(3000, original_tokens // 4))

    # Build compression prompt
    distill_prompt = DISTILL_PROMPT.format(
        deliberation=full_text,
        token_count=original_tokens,
        target_tokens=target_tokens
    )

    start = time.time()
    result = provider.ask(distill_prompt, "", cwd)
    duration = time.time() - start

    if not result.success or not result.content:
        Display.step_error("distill", result.error or "Compression failed")
        return {
            "success": False,
            "content": "",
            "original_tokens": original_tokens,
            "compressed_tokens": 0,
            "ratio": 1.0,
            "tokens_used": result.tokens_used if result else 0,
        }

    compressed_tokens = estimate_tokens(result.content)
    ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

    # Track cost if manager provided
    if cost_manager and result.tokens_used:
        cost_manager.add_cost(provider_name, result.tokens_used)

    # Store compressed context in memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="distill",
        agent="distiller",
        type="compressed_context",
        content=result.content,
        metadata={
            "model": result.model,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "compression_ratio": ratio,
            "duration": duration,
        },
    ))

    Display.notify(
        f"Compressed {original_tokens} → {compressed_tokens} tokens "
        f"({ratio:.1%} of original)"
    )

    return {
        "success": True,
        "content": result.content,
        "compressed_context": result.content,
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "ratio": ratio,
        "tokens_used": result.tokens_used,
        "files_changed": previous.get("files_changed", []),
    }
