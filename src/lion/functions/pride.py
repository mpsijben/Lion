"""pride() - Multi-agent deliberation.

The heart of Lion. Spawns multiple agents that:
1. Propose approaches independently (parallel)
2. Critique each other's proposals (parallel)
3. Converge on a consensus plan (single agent)
4. Implement the plan (with file editing)
"""

import concurrent.futures
import time

from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display

PROPOSE_PROMPT = """You are Agent {agent_num} in a team of {total_agents} working on this task:

TASK: {prompt}

WORKING DIRECTORY: {cwd}

Propose your approach. Be specific about:
1. Architecture and design decisions
2. Files to create or modify
3. Key implementation details
4. Potential risks or edge cases

Keep it concise but actionable."""

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
4. Your updated recommendation"""

CONVERGE_PROMPT = """You are the lead synthesizer. Your team proposed and critiqued approaches.

TASK: {prompt}

ALL PROPOSALS AND CRITIQUES:
{deliberation}

Create the FINAL PLAN:
1. Best elements from each proposal
2. All valid critiques addressed
3. Concrete task list for implementation

Format:
DECISION: [summary of approach and key choices]

TASKS:
1. [task description] | files: [file paths]
2. [task description] | files: [file paths] | depends_on: [1]
..."""

IMPLEMENT_PROMPT = """Implement this plan completely.

OVERALL GOAL: {prompt}

PLAN:
{plan}

Make all the actual code changes. Create and edit files as needed.
Be thorough and implement the full plan."""


def execute_pride(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute a pride deliberation."""

    agents = _resolve_agents(step, config)
    n_agents = len(agents)

    # Track agent summaries for final output
    agent_summaries = []

    Display.pride_start(n_agents, [a.name for a in agents])

    # PHASE 1: PROPOSE (parallel)
    Display.phase("propose", "Each agent proposes independently...")
    proposals = _parallel_propose(agents, prompt, cwd, memory)

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
        agent_summaries.append({
            "agent": proposal["agent"],
            "model": proposal["model"],
            "summary": summary,
        })

    # PHASE 2: CRITIQUE (parallel, skip if only 1 agent)
    if n_agents > 1:
        Display.phase("critique", "Agents review each other's proposals...")
        _parallel_critique(agents, prompt, proposals, cwd, memory)

    # PHASE 3: CONVERGE (single agent)
    Display.phase("converge", "Synthesizing into final plan...")
    plan = _converge(agents[0], prompt, memory, cwd)

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
    }


def _resolve_agents(step, config):
    """Determine which providers to use for the pride."""
    if step.args:
        first_arg = step.args[0]
        # Explicit providers: pride(claude, gemini)
        if isinstance(first_arg, str) and not str(first_arg).isdigit():
            return [get_provider(name, config) for name in step.args]
        # Number of agents: pride(3)
        n = int(first_arg)
        n = max(1, min(n, 5))  # Clamp between 1 and 5
        return [get_provider("claude", config) for _ in range(n)]
    # Default: 3 claude agents
    return [get_provider("claude", config) for _ in range(3)]


def _parallel_propose(agents, prompt, cwd, memory):
    """Run propose phase in parallel."""
    proposals = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            agent_prompt = PROPOSE_PROMPT.format(
                agent_num=i + 1,
                total_agents=len(agents),
                prompt=prompt,
                cwd=cwd,
            )
            futures[executor.submit(agent.ask, agent_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
            except Exception as e:
                Display.step_error(f"Agent {i + 1} propose", str(e))
                continue

            if not result.success:
                Display.step_error(f"Agent {i + 1} propose", result.error or "Unknown error")
                continue

            proposals.append({
                "agent": f"agent_{i + 1}",
                "content": result.content,
                "model": result.model,
                "tokens": result.tokens_used,
            })

            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{i + 1}",
                type="proposal",
                content=result.content,
                metadata={"model": result.model},
            ))

            Display.agent_proposal(i + 1, result.model, result.content[:150])

    return proposals


def _parallel_critique(agents, prompt, proposals, cwd, memory):
    """Run critique phase in parallel."""
    critiques = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            # Find this agent's proposal
            own = next((p for p in proposals if p["agent"] == f"agent_{i + 1}"), None)
            own_content = own["content"] if own else "(no proposal)"

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
            futures[executor.submit(agent.ask, critique_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
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
            })

            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="critique",
                agent=f"agent_{i + 1}",
                type="critique",
                content=result.content,
                metadata={"model": result.model},
            ))

            Display.agent_critique(i + 1, result.content[:150])

    return critiques


def _converge(lead_agent, prompt, memory, cwd):
    """Synthesize all proposals and critiques into a plan."""
    all_entries = memory.read_all()
    deliberation_text = memory.format_for_prompt(all_entries)

    # Truncate deliberation if too large (claude -p context limits)
    max_chars = 80000
    if len(deliberation_text) > max_chars:
        deliberation_text = deliberation_text[:max_chars] + "\n\n... (truncated for length)"

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
        metadata={"model": result.model if result else "unknown"},
    ))

    Display.convergence(content[:300])
    return content


def _implement(lead_agent, prompt, plan, cwd, memory):
    """Implement the converged plan by writing files."""
    impl_prompt = IMPLEMENT_PROMPT.format(
        prompt=prompt,
        plan=plan,
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
    # Take first meaningful line or first sentence
    lines = content.strip().split("\n")
    for line in lines:
        line = line.strip()
        # Skip headers, bullet points starting with numbers
        if line and not line.startswith("#") and len(line) > 10:
            # Truncate to ~100 chars at word boundary
            if len(line) > 100:
                truncated = line[:100].rsplit(" ", 1)[0]
                return truncated + "..."
            return line
    # Fallback: first 100 chars
    return content[:100].replace("\n", " ") + "..."


def _extract_decision_summary(plan):
    """Extract the DECISION line from a converged plan."""
    lines = plan.strip().split("\n")
    for line in lines:
        if line.strip().upper().startswith("DECISION:"):
            # Return everything after "DECISION:"
            decision = line.split(":", 1)[1].strip() if ":" in line else line
            # Truncate if too long
            if len(decision) > 150:
                return decision[:150].rsplit(" ", 1)[0] + "..."
            return decision
    # Fallback: first line of plan
    first_line = lines[0].strip() if lines else "Plan completed"
    if len(first_line) > 150:
        return first_line[:150].rsplit(" ", 1)[0] + "..."
    return first_line
