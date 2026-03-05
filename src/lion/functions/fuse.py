"""fuse() - Fast multi-agent deliberation with a reaction round.

MVP semantics:
1. Parallel propose (same core as pride)
2. Lightweight cross-agent reaction (summary-based)
3. Single synthesis to final plan

Output contract is compatible with impl()/pair() consumers:
- plan
- deliberation_summary
- agent_summaries
- final_decision
"""

from __future__ import annotations

import concurrent.futures
import time

from ..context import ContextMode, select_context_mode
from ..display import Display
from ..memory import MemoryEntry
from .pride import (
    _converge,
    _extract_decision_summary,
    _extract_decisions,
    _extract_one_liner,
    _get_shared_context,
    _parallel_propose,
    _resolve_agents,
)


FUSE_REACTION_PROMPT = """You are Agent {agent_num} in a fast collaborative deliberation.

TASK: {prompt}

YOUR PROPOSAL SUMMARY:
{own_summary}

OTHER AGENTS' SUMMARIES:
{other_summaries}

Write a short reaction focused on:
1. What you agree with from others
2. What should change in your own approach
3. Any critical conflict that must be resolved in synthesis

Keep it concise and actionable (max ~10 lines).
Start directly with your reaction.
"""


def _build_reaction_prompt(
    prompt: str,
    agent_num: int,
    own_summary: str,
    other_summaries: str,
) -> str:
    return FUSE_REACTION_PROMPT.format(
        agent_num=agent_num,
        prompt=prompt,
        own_summary=own_summary,
        other_summaries=other_summaries,
    )


def _parallel_react(agents, prompt, proposals, cwd, memory, agent_lenses=None):
    """Run one lightweight cross-agent reaction round in parallel."""
    reactions = []
    agent_lenses = agent_lenses or [None] * len(agents)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}

        for i, agent in enumerate(agents):
            own = next((p for p in proposals if p["agent"] == f"agent_{i + 1}"), None)
            own_summary = _extract_one_liner(own["content"]) if own else "(no proposal)"

            others = []
            for p in proposals:
                if p["agent"] == f"agent_{i + 1}":
                    continue
                p_lens = p.get("lens")
                lens_label = f"::{p_lens.shortcode}" if p_lens else ""
                others.append(
                    f"- {p['agent']} ({p['model']}{lens_label}): {_extract_one_liner(p['content'])}"
                )

            reaction_prompt = _build_reaction_prompt(
                prompt=prompt,
                agent_num=i + 1,
                own_summary=own_summary,
                other_summaries="\n".join(others) if others else "(no other agents)",
            )
            futures[executor.submit(agent.ask, reaction_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            lens = agent_lenses[i] if i < len(agent_lenses) else None
            try:
                result = future.result()
            except Exception as e:
                Display.step_error(f"Agent {i + 1} react", str(e))
                continue

            if not result.success:
                continue

            reactions.append(
                {
                    "agent": f"agent_{i + 1}",
                    "content": result.content,
                    "model": result.model,
                    "lens": lens,
                }
            )

            memory.write(
                MemoryEntry(
                    timestamp=time.time(),
                    phase="fuse_react",
                    agent=f"agent_{i + 1}",
                    type="reaction",
                    content=result.content,
                    metadata={
                        "model": result.model,
                        "lens": lens.shortcode if lens else None,
                    },
                )
            )

            Display.agent_critique(i + 1, result.content[:150], lens)

    return reactions


def execute_fuse(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute fuse deliberation.

    fuse() is a faster deliberation primitive than pride() in MVP form:
    propose -> react -> converge.
    """
    agents, agent_lenses = _resolve_agents(step, config, prompt)
    n_agents = len(agents)

    # Determine context mode
    context_mode_str = step.kwargs.get("context", config.get("context_mode", "auto"))
    if context_mode_str == "auto":
        pipeline_steps = config.get("_pipeline_steps", [step])
        context_mode_str = select_context_mode(pipeline_steps, config)
    context_mode = ContextMode(context_mode_str)

    # Display names with optional lenses
    display_names = []
    for i, agent in enumerate(agents):
        lens = agent_lenses[i] if i < len(agent_lenses) else None
        if lens:
            display_names.append(f"{agent.name}::{lens.shortcode}")
        else:
            display_names.append(agent.name)

    Display.pride_start(n_agents, display_names)
    Display.phase("fuse", "Fast deliberation: propose -> react -> synthesize")

    shared_context = _get_shared_context(memory)

    # Phase 1: propose
    Display.phase("propose", "Agents propose in parallel...")
    proposals, packages = _parallel_propose(
        agents,
        prompt,
        cwd,
        memory,
        context_mode,
        shared_context,
        agent_lenses,
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

    agent_summaries = []
    for proposal in proposals:
        summary = _extract_one_liner(proposal["content"])
        lens = proposal.get("lens")
        agent_summaries.append(
            {
                "agent": proposal["agent"],
                "model": proposal["model"],
                "summary": summary,
                "confidence": proposal.get("confidence"),
                "lens": lens.shortcode if lens else None,
                "lens_name": lens.name if lens else None,
            }
        )

    # Phase 2: reaction round
    reactions = []
    if n_agents > 1:
        Display.phase("fuse_react", "Agents react to each other's summaries...")
        reactions = _parallel_react(
            agents,
            prompt,
            proposals,
            cwd,
            memory,
            agent_lenses,
        )

    # Phase 3: synthesis
    Display.phase("converge", "Synthesizing final fuse plan...")
    plan, confidence_map = _converge(
        agents[0],
        prompt,
        memory,
        cwd,
        packages,
        context_mode,
        agent_lenses,
        proposals,
        reactions,
        config,
    )

    final_decision = _extract_decision_summary(plan)

    return {
        "success": True,
        "plan": plan,
        "decisions": _extract_decisions(memory),
        "tokens_used": 0,  # TODO: aggregate from provider responses
        "deliberation_summary": memory.format_for_prompt(memory.read_all()),
        "agent_summaries": agent_summaries,
        "final_decision": final_decision,
        "confidence_map": confidence_map,
        "context_mode": context_mode_str,
        "fuse_rounds": 1,
    }
