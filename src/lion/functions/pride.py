"""pride() - Multi-agent deliberation.

The heart of Lion. Spawns multiple agents that:
1. Propose approaches independently (parallel)
2. Critique each other's proposals (parallel)
3. Converge on a consensus plan (single agent)
4. Implement the plan (with file editing)

Layer 2: Context Ecosystem integration
- Mode-aware prompts (minimal/standard/rich)
- ContextPackage parsing for structured output
- Cross-agent context sharing via ContextAdapter
- Confidence-weighted convergence
"""

import concurrent.futures
import time
from dataclasses import asdict

from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..lenses import get_lens, Lens
from ..lenses.auto_assign import auto_assign_lenses
from ..context import (
    ContextMode,
    ContextPackage,
    ContextAdapter,
    parse_context_package,
    select_context_mode,
    get_propose_prompt,
    get_critique_prompt,
    get_converge_prompt,
    PROPOSE_PROMPT_MINIMAL,
    PROPOSE_PROMPT_STANDARD,
    PROPOSE_PROMPT_RICH,
    CONVERGE_PROMPT_MINIMAL,
    CONVERGE_PROMPT_STANDARD,
)

# Legacy prompts for backwards compatibility (used in minimal mode)
PROPOSE_PROMPT = PROPOSE_PROMPT_MINIMAL

CRITIQUE_PROMPT = """You are Agent {agent_num} reviewing proposals from your team.

TASK: {prompt}

YOUR PROPOSAL:
{own_proposal}

OTHER PROPOSALS:
{other_proposals}

For each other proposal, state:
1. What you agree with
2. What concerns you
3. What they thought of that you missed
4. Your updated recommendation

Start DIRECTLY with your analysis -- no preamble."""

CONVERGE_PROMPT = CONVERGE_PROMPT_MINIMAL

IMPLEMENT_PROMPT = """Implement this plan completely.

OVERALL GOAL: {prompt}

PLAN:
{plan}

DELIBERATION CONTEXT:
{deliberation_summary}

Make all the actual code changes. Create and edit files as needed.
Be thorough and implement the full plan. Follow the PLAN above closely.
If the PLAN seems incomplete, use the DELIBERATION CONTEXT for guidance."""


def execute_pride(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute a pride deliberation."""

    agents, agent_lenses = _resolve_agents(step, config, prompt)
    n_agents = len(agents)

    # Determine context mode
    context_mode_str = step.kwargs.get("context", config.get("context_mode", "auto"))
    if context_mode_str == "auto":
        # Get all pipeline steps from config if available
        pipeline_steps = config.get("_pipeline_steps", [step])
        context_mode_str = select_context_mode(pipeline_steps, config)

    context_mode = ContextMode(context_mode_str)

    # Track agent summaries for final output
    agent_summaries = []

    # Build display names including lenses
    display_names = []
    for i, agent in enumerate(agents):
        lens = agent_lenses[i] if i < len(agent_lenses) else None
        if lens:
            display_names.append(f"{agent.name}::{lens.shortcode}")
        else:
            display_names.append(agent.name)

    Display.pride_start(n_agents, display_names)

    # Get shared context if available
    shared_context = _get_shared_context(memory)

    # PHASE 1: PROPOSE (parallel)
    Display.phase("propose", "Each agent proposes independently...")
    proposals, packages = _parallel_propose(
        agents, prompt, cwd, memory, context_mode, shared_context, agent_lenses
    )

    if not proposals:
        return {
            "success": False,
            "error": "All agents failed to propose",
            "tokens_used": 0,
            "files_changed": [],
            "agent_summaries": [],
            "final_decision": None,
        }

    # Extract 1-liner summaries from proposals
    for proposal in proposals:
        summary = _extract_one_liner(proposal["content"])
        lens = proposal.get("lens")
        agent_summaries.append({
            "agent": proposal["agent"],
            "model": proposal["model"],
            "summary": summary,
            "confidence": proposal.get("confidence"),
            "lens": lens.shortcode if lens else None,
            "lens_name": lens.name if lens else None,
        })

    # PHASE 2: CRITIQUE (parallel, skip if only 1 agent)
    if n_agents > 1:
        Display.phase("critique", "Agents review each other's proposals...")
        _parallel_critique(
            agents, prompt, proposals, packages, cwd, memory, context_mode,
            agent_lenses
        )

    # PHASE 3: CONVERGE (single agent)
    Display.phase("converge", "Synthesizing into final plan...")
    plan, confidence_map = _converge(
        agents[0], prompt, memory, cwd, packages, context_mode,
        agent_lenses, proposals
    )

    # Extract the decision from the converged plan
    final_decision = _extract_decision_summary(plan)

    # PHASE 4: IMPLEMENT (single agent, writes files)
    Display.phase("implement", "Building the solution...")
    implementation = _implement(agents[0], prompt, plan, cwd, memory)

    return {
        "success": True,
        "plan": plan,
        "code": implementation.get("code", ""),
        "decisions": _extract_decisions(memory),
        "files_changed": implementation.get("files_changed", []),
        "tokens_used": 0,
        "deliberation_summary": memory.format_for_prompt(memory.read_all()),
        "agent_summaries": agent_summaries,
        "final_decision": final_decision,
        "confidence_map": confidence_map,
        "context_mode": context_mode_str,
    }


def _resolve_agents(step, config, prompt=""):
    """Determine which providers and lenses to use for the pride.

    Returns (agents, lenses) where lenses is a list of Lens|None per agent.
    """
    default_provider = config.get("providers", {}).get("default", "claude")
    lenses_kwarg = step.kwargs.get("lenses")

    if step.args:
        first_arg = step.args[0]
        # Explicit providers (with optional lens): pride(claude::arch, gemini::sec)
        if isinstance(first_arg, str) and not str(first_arg).isdigit():
            agents = []
            agent_lenses = []
            for arg in step.args:
                if isinstance(arg, str) and "::" in arg:
                    provider_str, lens_str = arg.split("::", 1)
                    agents.append(get_provider(provider_str.strip(), config))
                    lens = get_lens(lens_str.strip())
                    agent_lenses.append(lens)
                else:
                    agents.append(get_provider(str(arg), config))
                    agent_lenses.append(None)

            return agents, agent_lenses

        # Number of agents: pride(3)
        n = int(first_arg)
        n = max(1, min(n, 5))  # Clamp between 1 and 5
        agents = [get_provider(default_provider, config) for _ in range(n)]

        # Handle lenses: auto
        if lenses_kwarg == "auto":
            lens_codes = auto_assign_lenses(prompt, n)
            agent_lenses = [get_lens(code) for code in lens_codes]
        else:
            agent_lenses = [None] * n

        return agents, agent_lenses

    # Default: 3 agents with default provider
    n = 3
    agents = [get_provider(default_provider, config) for _ in range(n)]

    if lenses_kwarg == "auto":
        lens_codes = auto_assign_lenses(prompt, n)
        agent_lenses = [get_lens(code) for code in lens_codes]
    else:
        agent_lenses = [None] * n

    return agents, agent_lenses


def _get_shared_context(memory) -> str:
    """Get shared context from previous context() step if available."""
    shared_entries = memory.read_by_type("shared_context")
    if shared_entries:
        return f"SHARED CONTEXT:\n{shared_entries[-1].content}\n"

    historical_entries = memory.read_by_type("historical_context")
    if historical_entries:
        return f"HISTORICAL CONTEXT:\n{historical_entries[-1].content}\n"

    return ""


def _build_lensed_propose(prompt, agent_num, total_agents, lens, cwd, shared_context=""):
    """Build a propose prompt with lens focus injected."""
    parts = [f"You are Agent {agent_num} of {total_agents} analyzing:\n\nTASK: {prompt}\n"]

    if shared_context:
        parts.append(f"CODEBASE CONTEXT:\n{shared_context}\n")

    parts.append(f"""
{lens.prompt_inject}

Other agents are analyzing from different angles.
You do NOT need to cover everything -- go DEEP on your area.

IMPORTANT: Start DIRECTLY with "## Analysis". No preamble, no "I understand", no "Let me analyze". Begin immediately with the structured output.

Structure your response:

## Analysis ({lens.name} perspective)
[Your focused analysis and recommendations]

## Key Findings
- [Most important finding from your perspective]
- [Other significant findings]

## Warnings
- [Things that MUST be addressed from your perspective]

## Confidence
[0.0-1.0]
""")

    return "\n".join(parts)


def _build_lensed_critique(prompt, agent_num, own_lens, own_proposal, other_proposals):
    """Build a critique prompt scoped to the agent's own lens."""
    parts = [f"""You are Agent {agent_num} with the {own_lens.name} lens.

TASK: {prompt}

YOUR ANALYSIS ({own_lens.name}):
{own_proposal}

OTHER AGENTS' ANALYSES:
"""]

    for other in other_proposals:
        lens_label = f" ({other['lens_name']} perspective)" if other.get('lens_name') else ""
        parts.append(f"""
--- Agent {other['num']}{lens_label} ---
{other['output']}
""")

    parts.append(f"""
{own_lens.critique_inject}

Specifically:
1. What implications do their proposals have for {own_lens.name.lower()}?
2. Do any of their approaches conflict with your findings?
3. What constraints from YOUR analysis must their approaches satisfy?

Stay in your lane. Do not critique aspects outside your lens.
Start DIRECTLY with your analysis -- no preamble.""")

    return "\n".join(parts)


def _build_lensed_converge(prompt, proposals, deliberation_text):
    """Build a converge prompt that handles labeled lens perspectives."""
    parts = [f"""Synthesize these focused analyses into a final plan.

IMPORTANT: You are creating a TEXT PLAN only. Do NOT ask for file permissions.
Do NOT try to write, create, or modify any files. Just output your plan as text.

TASK: {prompt}

ANALYSES FROM DIFFERENT PERSPECTIVES:
"""]

    for p in proposals:
        lens = p.get("lens")
        lens_label = f" ({lens.name} perspective)" if lens else ""
        confidence = p.get("confidence", "N/A")
        parts.append(f"""
=== {lens.name.upper() if lens else 'GENERAL'} PERSPECTIVE (Agent {p['agent']}, {p['model']}) ===
Confidence: {confidence}

{p['content'][:3000]}
""")

    parts.append(f"""
FULL DELIBERATION (proposals + critiques):
{deliberation_text}

Create the FINAL PLAN that:
1. Satisfies ALL high-confidence warnings as hard requirements
2. Integrates insights from every perspective
3. Where perspectives conflict, explain which takes priority and why
4. Marks each decision with the perspective(s) that support it

Format:
DECISION: [summary of approach and key choices]
  Supported by: [lens names / agent numbers]

TASKS:
1. [task description] | files: [file paths]
2. [task description] | files: [file paths] | depends_on: [1]
...""")

    return "\n".join(parts)


def _parallel_propose(agents, prompt, cwd, memory, context_mode, shared_context="",
                      agent_lenses=None):
    """Run propose phase in parallel with mode-aware prompts."""
    proposals = []
    packages = []
    agent_lenses = agent_lenses or [None] * len(agents)

    # Select prompt template based on mode
    if context_mode == ContextMode.RICH:
        prompt_template = PROPOSE_PROMPT_RICH
    elif context_mode == ContextMode.STANDARD:
        prompt_template = PROPOSE_PROMPT_STANDARD
    else:
        prompt_template = PROPOSE_PROMPT_MINIMAL

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            lens = agent_lenses[i] if i < len(agent_lenses) else None

            if lens:
                # Lensed propose: inject lens focus
                agent_prompt = _build_lensed_propose(
                    prompt, i + 1, len(agents), lens, cwd, shared_context
                )
            else:
                agent_prompt = prompt_template.format(
                    agent_num=i + 1,
                    total_agents=len(agents),
                    prompt=prompt,
                    cwd=cwd,
                    shared_context=shared_context,
                )
            futures[executor.submit(agent.ask, agent_prompt, "", cwd)] = (i, agent)

        for future in concurrent.futures.as_completed(futures):
            i, agent = futures[future]
            try:
                result = future.result()
            except Exception as e:
                Display.step_error(f"Agent {i + 1} propose", str(e))
                continue

            if not result.success:
                Display.step_error(f"Agent {i + 1} propose", result.error or "Unknown error")
                continue

            # Parse structured output into ContextPackage
            package = parse_context_package(
                result.content,
                agent_id=f"agent_{i + 1}",
                model=result.model,
                mode=context_mode
            )
            packages.append(package)

            lens = agent_lenses[i] if i < len(agent_lenses) else None

            proposals.append({
                "agent": f"agent_{i + 1}",
                "content": result.content,
                "model": result.model,
                "tokens": result.tokens_used,
                "confidence": package.confidence,
                "package": package,
                "lens": lens,
            })

            # Write to memory with context fields
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{i + 1}",
                type="proposal",
                content=result.content,
                metadata={
                    "model": result.model,
                    "context_mode": context_mode.value,
                    "lens": lens.shortcode if lens else None,
                },
                reasoning=package.reasoning,
                alternatives=package.alternatives,
                uncertainties=package.uncertainties,
                confidence=package.confidence,
                belief_state=asdict(package.belief_state) if package.belief_state else None,
            ))

            Display.agent_proposal(i + 1, result.model, result.content[:150], lens)

    return proposals, packages


def _parallel_critique(agents, prompt, proposals, packages, cwd, memory, context_mode,
                       agent_lenses=None):
    """Run critique phase in parallel with context awareness."""
    critiques = []
    adapter = ContextAdapter()
    agent_lenses = agent_lenses or [None] * len(agents)
    any_lensed = any(l is not None for l in agent_lenses)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            lens = agent_lenses[i] if i < len(agent_lenses) else None

            # Find this agent's proposal and package
            own = next((p for p in proposals if p["agent"] == f"agent_{i + 1}"), None)
            own_content = own["content"] if own else "(no proposal)"
            own_pkg = own.get("package") if own else None

            if any_lensed and lens:
                # Lensed critique: scoped to own lens
                other_formatted = []
                for p in proposals:
                    if p["agent"] == f"agent_{i + 1}":
                        continue
                    p_lens = p.get("lens")
                    other_formatted.append({
                        "num": p["agent"].replace("agent_", ""),
                        "lens_name": p_lens.name if p_lens else "General",
                        "output": p["content"],
                    })
                critique_prompt = _build_lensed_critique(
                    prompt, i + 1, lens, own_content, other_formatted
                )
            elif context_mode == ContextMode.MINIMAL:
                # Minimal mode: use original critique format
                other_proposals = "\n\n".join(
                    f"Agent {j + 1} ({p['model']}): {p['content']}"
                    for j, p in enumerate(proposals)
                    if p["agent"] != f"agent_{i + 1}"
                )

                critique_prompt = CRITIQUE_PROMPT.format(
                    agent_num=i + 1,
                    prompt=prompt,
                    own_proposal=own_content,
                    other_proposals=other_proposals,
                )
            else:
                # Standard/Rich mode: use context-aware critique
                # Get other packages
                other_packages = [pkg for pkg in packages if pkg.agent_id != f"agent_{i + 1}"]

                # Format using ContextAdapter
                other_proposals_formatted = adapter.format(
                    other_packages,
                    target_provider=agent.name,
                    mode=context_mode
                )

                # Build own context
                own_reasoning = own_pkg.reasoning if own_pkg else ""
                own_uncertainties = "; ".join(own_pkg.uncertainties) if own_pkg else ""
                own_assumptions = "; ".join(own_pkg.assumptions) if own_pkg else ""

                # Build belief states section for rich mode
                belief_states_formatted = ""
                if context_mode == ContextMode.RICH:
                    for pkg in other_packages:
                        if pkg.belief_state:
                            belief_states_formatted += f"\n{pkg.agent_id}:\n"
                            if pkg.belief_state.knows:
                                belief_states_formatted += f"  Knows: {'; '.join(pkg.belief_state.knows)}\n"
                            if pkg.belief_state.believes:
                                belief_states_formatted += f"  Believes: {'; '.join(pkg.belief_state.believes)}\n"
                            if pkg.belief_state.others_likely_missing:
                                belief_states_formatted += f"  Others might miss: {'; '.join(pkg.belief_state.others_likely_missing)}\n"

                from ..context.prompts import CRITIQUE_PROMPT_STANDARD, CRITIQUE_PROMPT_RICH

                if context_mode == ContextMode.RICH:
                    critique_prompt = CRITIQUE_PROMPT_RICH.format(
                        agent_num=i + 1,
                        prompt=prompt,
                        own_proposal_output=own_content,
                        own_reasoning=own_reasoning,
                        own_uncertainties=own_uncertainties,
                        own_assumptions=own_assumptions,
                        other_proposals_formatted=other_proposals_formatted,
                        belief_states_formatted=belief_states_formatted,
                    )
                else:
                    critique_prompt = CRITIQUE_PROMPT_STANDARD.format(
                        agent_num=i + 1,
                        prompt=prompt,
                        own_proposal_output=own_content,
                        own_reasoning=own_reasoning,
                        own_uncertainties=own_uncertainties,
                        other_proposals_formatted=other_proposals_formatted,
                    )

            futures[executor.submit(agent.ask, critique_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            lens = agent_lenses[i] if i < len(agent_lenses) else None
            try:
                result = future.result()
            except Exception as e:
                Display.step_error(f"Agent {i + 1} critique", str(e))
                continue

            if not result.success:
                continue

            critiques.append({
                "agent": f"agent_{i + 1}",
                "content": result.content,
                "model": result.model,
                "lens": lens,
            })

            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="critique",
                agent=f"agent_{i + 1}",
                type="critique",
                content=result.content,
                metadata={
                    "model": result.model,
                    "context_mode": context_mode.value,
                    "lens": lens.shortcode if lens else None,
                },
            ))

            Display.agent_critique(i + 1, result.content[:150], lens)

    return critiques


def _converge(lead_agent, prompt, memory, cwd, packages, context_mode,
              agent_lenses=None, proposals=None):
    """Synthesize all proposals and critiques into a plan with confidence weighting."""
    agent_lenses = agent_lenses or []
    any_lensed = any(l is not None for l in agent_lenses)

    all_entries = memory.read_all()
    deliberation_text = memory.format_for_prompt(all_entries)

    # Truncate deliberation if too large
    max_chars = 80000
    if len(deliberation_text) > max_chars:
        deliberation_text = deliberation_text[:max_chars] + "\n\n... (truncated for length)"

    # Build confidence map for standard/rich modes
    confidence_map = {}
    confidence_map_text = ""

    if context_mode != ContextMode.MINIMAL and packages:
        conf_lines = []
        for pkg in packages:
            conf = pkg.confidence if pkg.confidence is not None else 0.5
            label = "HIGH" if conf >= 0.7 else ("MODERATE" if conf >= 0.4 else "LOW")
            confidence_map[pkg.agent_id] = {"confidence": conf, "label": label}
            conf_lines.append(f"- {pkg.agent_id} ({pkg.model}): {conf} ({label})")

        confidence_map_text = "\n".join(conf_lines)

    # Use lensed converge prompt when lenses are active
    if any_lensed and proposals:
        converge_prompt = _build_lensed_converge(prompt, proposals, deliberation_text)
    elif context_mode == ContextMode.RICH:
        # Build assumption conflicts and belief summary for rich mode
        assumption_conflicts = _find_assumption_conflicts(packages)
        belief_summary = _build_belief_summary(packages)

        converge_prompt = CONVERGE_PROMPT_STANDARD.format(
            prompt=prompt,
            deliberation=deliberation_text,
            confidence_map=confidence_map_text or "No confidence data available",
        )
    elif context_mode == ContextMode.STANDARD:
        converge_prompt = CONVERGE_PROMPT_STANDARD.format(
            prompt=prompt,
            deliberation=deliberation_text,
            confidence_map=confidence_map_text or "No confidence data available",
        )
    else:
        converge_prompt = CONVERGE_PROMPT.format(
            prompt=prompt,
            deliberation=deliberation_text,
        )

    # Retry up to 2 times if converge returns empty
    result = None
    for attempt in range(3):
        result = lead_agent.ask(converge_prompt, "", cwd)

        if result.success and result.content and result.content.strip():
            break

        if attempt < 2:
            Display.step_error("converge", f"Empty response (attempt {attempt + 1}/3), retrying...")

    if not result or not result.content or not result.content.strip():
        # Fallback: use proposals as plan
        proposals = [e for e in all_entries if e.phase == "propose"]
        fallback = "DECISION: Using first agent's proposal as plan (converge failed).\n\nTASKS:\n"
        if proposals:
            fallback += proposals[0].content
        Display.step_error("converge", "All attempts returned empty, using fallback plan")
        content = fallback
    else:
        content = result.content

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="converge",
        agent="synthesizer",
        type="decision",
        content=content,
        metadata={
            "model": result.model if result else "unknown",
            "context_mode": context_mode.value,
            "confidence_map": confidence_map,
        },
    ))

    Display.convergence(content[:300])
    return content, confidence_map


def _find_assumption_conflicts(packages):
    """Find conflicting assumptions between agents."""
    conflicts = []
    for i, pkg1 in enumerate(packages):
        for pkg2 in packages[i+1:]:
            if pkg1.assumptions and pkg2.assumptions:
                # Simple keyword overlap check for conflicting assumptions
                for a1 in pkg1.assumptions:
                    for a2 in pkg2.assumptions:
                        a1_lower = a1.lower()
                        a2_lower = a2.lower()
                        # Check if one negates the other
                        if ("not" in a1_lower and "not" not in a2_lower) or \
                           ("not" not in a1_lower and "not" in a2_lower):
                            conflicts.append(f"{pkg1.agent_id}: '{a1}' vs {pkg2.agent_id}: '{a2}'")
    return conflicts


def _build_belief_summary(packages):
    """Build a summary of what agents know vs believe."""
    summary_parts = []
    for pkg in packages:
        if pkg.belief_state:
            part = f"{pkg.agent_id}:"
            if pkg.belief_state.knows:
                part += f"\n  Verified: {'; '.join(pkg.belief_state.knows[:3])}"
            if pkg.belief_state.believes:
                part += f"\n  Unverified: {'; '.join(pkg.belief_state.believes[:3])}"
            summary_parts.append(part)
    return "\n".join(summary_parts)


def _implement(lead_agent, prompt, plan, cwd, memory):
    """Implement the converged plan by writing files."""
    # Get deliberation summary as fallback context
    all_entries = memory.read_all()
    deliberation_summary = memory.format_for_prompt(all_entries)
    # Truncate to prevent overwhelming the implementer
    if len(deliberation_summary) > 40000:
        deliberation_summary = deliberation_summary[:40000] + "\n\n... (truncated)"

    impl_prompt = IMPLEMENT_PROMPT.format(
        prompt=prompt,
        plan=plan,
        deliberation_summary=deliberation_summary,
    )

    result = lead_agent.implement(impl_prompt, cwd)

    if not result.success:
        Display.step_error("implement", result.error or "Implementation failed")

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="implement",
        agent="implementer",
        type="code",
        content=result.content or "",
        metadata={"model": result.model},
    ))

    return {
        "code": result.content or "",
        "files_changed": [],
        "tokens": result.tokens_used,
    }


def _extract_decisions(memory):
    """Extract key decisions from the deliberation."""
    decisions = memory.get_decisions()
    return [d.content for d in decisions]


def _extract_one_liner(content):
    """Extract a concise 1-liner summary from proposal content."""
    # AI preamble patterns to skip (case-insensitive check)
    _PREAMBLE_STARTS = (
        "now i have",
        "i have analyzed",
        "i have a complete",
        "i have a comprehensive",
        "i've analyzed",
        "i've reviewed",
        "i now have",
        "let me ",
        "here's my ",
        "here is my ",
        "after analyzing",
        "after reviewing",
        "based on my analysis",
        "based on my review",
        "i'll provide",
        "i will provide",
        "perfect.",
        "perfect,",
        "perfect!",
        "perfect -",
        "great.",
        "great,",
        "great!",
        "great -",
        "excellent.",
        "excellent,",
        "excellent!",
        "understood.",
        "understood,",
        "understood!",
        "okay,",
        "okay.",
        "ok,",
        "ok.",
        "sure,",
        "sure.",
        "absolutely.",
        "absolutely,",
        "alright,",
        "alright.",
        "thank you",
        "thanks for",
        "i understand",
        "i'll analyze",
        "i will analyze",
        "i can see",
        "looking at",
    )

    # Look for structured content first: DECISION, APPROACH, PROPOSAL headers
    lines = content.strip().split("\n")
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper().lstrip("#").lstrip("*").strip()
        for keyword in ("DECISION:", "APPROACH:", "PROPOSAL:", "SUMMARY:"):
            if upper.startswith(keyword):
                after = stripped[stripped.upper().index(keyword.rstrip(":")) + len(keyword):]
                after = after.lstrip(":").lstrip("*").strip()
                if after and len(after) > 10:
                    if len(after) > 100:
                        return after[:100].rsplit(" ", 1)[0] + "..."
                    return after

    # Fallback: find first meaningful non-preamble line
    for line in lines:
        line = line.strip()
        if not line or len(line) <= 10:
            continue
        if line.startswith("#") or line.startswith("|") or line.startswith("---"):
            continue
        if line.startswith("- **") or line.startswith("* **"):
            continue
        # Skip AI preamble
        lower = line.lower()
        if any(lower.startswith(p) for p in _PREAMBLE_STARTS):
            continue
        if len(line) > 100:
            truncated = line[:100].rsplit(" ", 1)[0]
            return truncated + "..."
        return line
    # Last resort: first 100 chars, cleaned up
    return content[:100].replace("\n", " ").strip() + "..."


def _extract_decision_summary(plan):
    """Extract the DECISION line from a converged plan."""
    _PREAMBLE_STARTS = (
        "now i have",
        "i have a complete",
        "i have a comprehensive",
        "i've analyzed",
        "i've reviewed",
        "i now have",
        "let me ",
        "here's ",
        "here is ",
        "after analyzing",
        "after reviewing",
        "based on ",
        "perfect.",
        "perfect,",
        "perfect!",
        "great.",
        "great,",
        "great!",
        "excellent.",
        "excellent,",
        "understood.",
        "understood,",
        "okay,",
        "okay.",
        "i understand",
        "i'll analyze",
        "looking at",
        "thank you",
    )

    lines = plan.strip().split("\n")

    # First pass: look for explicit DECISION: line
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper().lstrip("#").lstrip("*").strip()
        if upper.startswith("DECISION:") or upper.startswith("DECISION :"):
            idx = stripped.upper().index("DECISION")
            after = stripped[idx + len("DECISION"):]
            decision = after.lstrip(":").lstrip("*").strip()
            # If DECISION: is on its own line, grab the next non-empty line
            if not decision:
                found_decision = False
                for next_line in lines[lines.index(line) + 1:]:
                    next_stripped = next_line.strip()
                    if next_stripped and not next_stripped.startswith("#"):
                        decision = next_stripped
                        found_decision = True
                        break
                if not found_decision:
                    continue
            if len(decision) > 150:
                return decision[:150].rsplit(" ", 1)[0] + "..."
            return decision

    # Fallback: first meaningful non-header, non-preamble line
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            continue
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _PREAMBLE_STARTS):
            continue
        if len(stripped) > 150:
            return stripped[:150].rsplit(" ", 1)[0] + "..."
        return stripped
    return "Plan completed"
