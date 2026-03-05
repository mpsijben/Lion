# 🦁 LION - Language for Intelligent Orchestration Networks

## Complete Implementation Specification v1.0

---

## Table of Contents

1. [Vision & Core Concept](#1-vision--core-concept)
2. [What Makes Lion Unique](#2-what-makes-lion-unique)
3. [Architecture Overview](#3-architecture-overview)
4. [Installation & Integration](#4-installation--integration)
5. [User Interface & Syntax](#5-user-interface--syntax)
6. [Pipeline Functions Reference](#6-pipeline-functions-reference)
7. [Provider System (Multi-LLM)](#7-provider-system-multi-llm)
8. [Shared Memory & Agent Communication](#8-shared-memory--agent-communication)
9. [Escalation & Human Interaction](#9-escalation--human-interaction)
10. [Cost Optimization](#10-cost-optimization)
11. [Configuration](#11-configuration)
12. [Implementation Phases](#12-implementation-phases)
13. [File Structure](#13-file-structure)
14. [Detailed Implementation Guide](#14-detailed-implementation-guide)
15. [Custom Functions & Extensibility](#15-custom-functions--extensibility)
16. [Lion Self-Build Bootstrap](#16-lion-self-build-bootstrap)

---

## 1. Vision & Core Concept

### The Problem

Today, AI-assisted coding follows a single pattern:

```
Human → 1 prompt → 1 AI brain → 1 result
```

If the result is wrong, you retry. If the architecture is flawed, you only discover it later. If there's a better approach, no one challenges the AI's first instinct. You're limited by the biases, blind spots, and single perspective of one model.

### The Solution

Lion transforms this into:

```
Human → 1 prompt → multiple AI brains → deliberation → consensus → superior result
```

But crucially, Lion makes this **as easy as the single-prompt approach**. No new tools to learn, no configuration files to write, no framework code to maintain.

### The One-Liner

**Lion is composable Unix-style pipes for AI agent orchestration - multi-agent deliberation, adversarial review, and unique pipeline functions like `devil()` and `future()`, running inside Claude Code with cost-optimized multi-LLM support.**

### Core Principles

1. **Zero friction**: Typing `lion "do X"` must be as easy as typing a normal prompt
2. **Smart spending**: The orchestration layer is pure Python (zero tokens). Cost profiles and free LLMs (Gemini, Ollama) minimize spend on deliberation phases
3. **Composable**: Pipeline functions chain like Unix pipes: `-> pride(3) -> review() -> devil()`
4. **Smart defaults**: Lion chooses the right strategy if you don't specify one
5. **Extensible**: Anyone can add custom pipeline functions
6. **Multi-LLM**: Mix Claude, Gemini, Codex, Ollama - use the right brain for the right job
7. **Self-building**: Once the core works, all further Lion development happens through Lion itself

---

## 2. What Makes Lion Unique

### What Already Exists (and what Lion is NOT)

| Existing Tool | What It Does | Why Lion Is Different |
|---|---|---|
| CrewAI, AutoGen, LangGraph | Multi-agent frameworks in Python | Require Python setup (15-30 lines minimum, 100+ for production). Lion is one CLI line with zero boilerplate. |
| ChatDev, MetaGPT | Multi-agent software development | Role-based collaboration for code, but no composable pipeline syntax. Users can't mix/match steps or create custom flows. |
| Verdent | Parallel AI coding agents in VS Code | Multi-model but no user-facing pipeline composition, no deliberation-style debate. |
| LangChain LCEL | Pipe-style composition (`prompt \| model \| parser`) | Chains components, not deliberating agents. No built-in pride/devil/future functions. |
| RouteLLM, Martian | Smart model routing | Route to ONE model per query, don't make models collaborate |
| Claude Code hooks projects | Various hook-based automations | Task-specific, not a general orchestration language |

### What Lion Does That Nothing Else Does

#### 1. The Pipeline as First-Class Concept
While composable AI pipelines exist (LangChain LCEL chains components with `|`), no tool lets users compose **multi-agent deliberation, adversarial review, and deployment** in a single CLI line:
```
lion "Build X" -> pride(3) -> devil() -> future(6m) -> review() -> test() -> pr()
```
This is the Unix pipe philosophy applied to AI agent orchestration - not just model chaining, but agents that debate, challenge, and build together.

#### 2. Asymmetric Multi-LLM Deliberation
Multi-agent debate for software engineering exists (ChatDev, MetaGPT, AutoGen), but these frameworks use agents of the same model with different *personas*. Lion uses **structurally different LLMs** that have fundamentally different training, biases, and strengths:
```
-> pride(claude, gemini, codex)
```
This isn't role-playing - it's genuine cognitive diversity.

#### 3. Pipeline Functions as Reusable Building Blocks

The devil's advocate concept exists in AI (AWS Bedrock case studies, academic research), and code review/audit tools exist as standalone products. What's new is packaging these as **composable, named pipeline steps** that chain together:

- **`devil()`** - A contrarian agent that challenges the consensus. Not bug-finding (that's `review()`), but challenging assumptions, architecture decisions, and approach choices. "Your pride agreed on JWT tokens. Here's why that will hurt you in 6 months."

- **`future(Nm)`** - Time-travel review. An agent that evaluates your code from the perspective of N months in the future. No existing tool offers this perspective. "I'm a developer using this system 6 months from now. These are my frustrations and what I wish you'd built differently."

- **`onboard()`** - Generates documentation as if a new team member starts tomorrow. Not code comments, but "here's WHY we built it this way, what we considered and rejected, and what you need to know."

- **`cost()`** - Infrastructure cost assessment. Does NOT generate cost estimates (LLM numbers are unreliable). Instead generates a checklist of detected components with pricing calculator links and questions to answer.

- **`audit()`** - Security audit against OWASP top 10, dependency analysis, and attack surface review.

- **`explain()`** - Documents the architectural decisions and rationale, not the code itself.

- **`migrate()`** - Migration planning assistant. Does NOT generate migration plans (static analysis can't verify runtime behavior). Instead generates an assessment questionnaire with "VERIFY THIS ASSUMPTION" callouts.

#### 4. Orchestration via Claude Code Hook
Lion intercepts prompts at the `UserPromptSubmit` hook level - before Claude ever sees them. The orchestration logic (parsing, scheduling, agent coordination, shared memory management) happens in Python at zero token cost. The LLM calls themselves (propose, critique, converge, implement) do consume tokens - a `pride(3) -> review()` pipeline uses roughly ~13 LLM calls. Cost profiles (cheap/balanced/premium) and mixed free providers (Gemini, Ollama) help manage this overhead.

---

## 3. Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLAUDE CODE                          │
│                                                          │
│  User types: lion "Build auth" -> pride(3) -> review()   │
│                          │                               │
│              ┌───────────▼────────────┐                  │
│              │  UserPromptSubmit Hook │                  │
│              │  (intercepts "lion "*) │                  │
│              │  Exit code 2 = block   │                  │
│              └───────────┬────────────┘                  │
│                          │                               │
└──────────────────────────┼───────────────────────────────┘
                           │ Spawns separate process
                           │ (0 tokens)
                    ┌──────▼──────┐
                    │  LION CORE  │
                    │  (Python)   │
                    │             │
                    │ 1. Parse pipeline
                    │ 2. Resolve providers
                    │ 3. Execute steps
                    │ 4. Manage shared memory
                    │ 5. Handle escalation
                    │ 6. Display progress
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
    │  Claude    │   │  Gemini   │   │  Ollama   │
    │  claude -p │   │  gemini   │   │  ollama   │
    │            │   │           │   │  run      │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼──────┐
                    │   SHARED    │
                    │   MEMORY    │
                    │  (.jsonl)   │
                    └─────────────┘
```

### Data Flow for `pride(3) -> review()`

```
Step 1: PROPOSE (parallel)
  Lion → claude -p "Propose approach for: {prompt}" → proposal_1
  Lion → claude -p "Propose approach for: {prompt}" → proposal_2
  Lion → claude -p "Propose approach for: {prompt}" → proposal_3

Step 2: CRITIQUE (parallel)
  Lion → claude -p "Critique these proposals: {1,2,3}. You are agent 1." → critique_1
  Lion → claude -p "Critique these proposals: {1,2,3}. You are agent 2." → critique_2
  Lion → claude -p "Critique these proposals: {1,2,3}. You are agent 3." → critique_3

Step 3: CONVERGE (single)
  Lion → claude -p "Synthesize into final plan: {proposals + critiques}" → plan

Step 4: IMPLEMENT (parallel, based on plan)
  Lion → claude -p "Implement task 1 from plan: {plan}" → code_1
  Lion → claude -p "Implement task 2 from plan: {plan}" → code_2
  (tasks determined by plan, parallelized where no dependencies)

Step 5: REVIEW (single, next pipeline step)
  Lion → claude -p "Review this code: {all code from step 4}" → review_result

Step 6: OUTPUT
  Lion → display results in terminal
  Lion → apply code changes to filesystem
```

---

## 4. Installation & Integration

### Installation Script

```bash
#!/bin/bash
# install.sh - Lion installer

LION_DIR="$HOME/.lion"

# Create directory structure
mkdir -p "$LION_DIR"/{functions,providers,patterns,runs}

# Copy core files
cp -r ./lion/* "$LION_DIR/"

# Make executable
chmod +x "$LION_DIR/lion.py"
chmod +x "$LION_DIR/hook.py"

# Create symlink for global access
ln -sf "$LION_DIR/lion.py" /usr/local/bin/lion

# Install Claude Code hook
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# Create settings file if it doesn't exist
if [ ! -f "$CLAUDE_SETTINGS" ]; then
    mkdir -p "$HOME/.claude"
    echo '{}' > "$CLAUDE_SETTINGS"
fi

# Add UserPromptSubmit hook using Python to handle JSON safely
python3 << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
lion_hook_cmd = f"python3 {os.path.expanduser('~/.lion/hook.py')}"

with open(settings_path, 'r') as f:
    settings = json.load(f)

if 'hooks' not in settings:
    settings['hooks'] = {}

settings['hooks']['UserPromptSubmit'] = [
    {
        "hooks": [
            {
                "type": "command",
                "command": lion_hook_cmd
            }
        ]
    }
]

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print("✅ Lion hook installed in Claude Code settings")
EOF

# Create default config
if [ ! -f "$LION_DIR/config.toml" ]; then
    cp ./config.default.toml "$LION_DIR/config.toml"
fi

echo ""
echo "🦁 Lion installed successfully!"
echo ""
echo "Usage inside Claude Code:"
echo '  lion "Build a feature"'
echo '  lion "Build a feature" -> pride(3) -> review()'
echo ""
echo "Usage from terminal:"
echo '  lion "Build a feature"'
echo ""
echo "Config: ~/.lion/config.toml"
```

### Claude Code Hook (hook.py)

```python
#!/usr/bin/env python3
"""
Lion - UserPromptSubmit hook for Claude Code.
Intercepts prompts starting with "lion " and routes them
to the Lion orchestrator. Zero tokens consumed.
"""

import sys
import json
import subprocess
import os

LION_DIR = os.path.expanduser("~/.lion")

def main():
    # Read hook input from stdin (Claude Code sends JSON)
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)  # Not valid JSON, let it through

    # Extract the user's prompt
    prompt = hook_input.get("prompt", "").strip()

    # Check if this is a lion command
    if not prompt.lower().startswith("lion "):
        # Not a lion command - pass through to Claude Code normally
        sys.exit(0)

    # It IS a lion command - extract the actual prompt
    lion_input = prompt[5:].strip()  # Remove "lion " prefix

    # Get working directory from hook context
    cwd = hook_input.get("cwd", os.getcwd())
    session_id = hook_input.get("session_id", "unknown")

    # Start Lion orchestrator as a separate process
    # This runs independently - Claude Code doesn't wait for it
    env = os.environ.copy()
    env["LION_SESSION_ID"] = session_id
    env["LION_CWD"] = cwd

    subprocess.Popen(
        [sys.executable, os.path.join(LION_DIR, "lion.py"), lion_input],
        cwd=cwd,
        env=env,
        stdout=sys.stdout,  # Output goes to user's terminal
        stderr=sys.stderr,
    )

    # Exit code 2 = block the prompt from reaching Claude
    # Claude Code never sees this prompt, zero tokens consumed
    print("🦁 Lion intercepted. Orchestrating...", file=sys.stderr)
    sys.exit(2)

if __name__ == "__main__":
    main()
```

---

## 5. User Interface & Syntax

### Basic Syntax

```
lion <prompt> [-> <function>(<args>) [-> <function>(<args>) ...]]
```

### Usage Levels

#### Level 1: Beginner (no pipeline - Lion decides)
```
lion "Fix the login bug"
  → Lion detects: simple task → 1 agent

lion "Build a complete auth system"
  → Lion detects: complex task → pride(3) -> review() -> test()
```

#### Level 2: Intermediate (explicit pipeline)
```
lion "Build Stripe checkout" -> pride(3) -> review()
lion "Refactor the API" -> pride(3) -> devil() -> review() -> test()
```

#### Level 3: Power User (custom everything)
```
lion "Build payment system" -> pride(claude, gemini, codex) -> devil() -> future(6m) -> review(claude) -> test() -> audit() -> onboard() -> pr("feature/payments")
```

#### Level 4: Custom patterns & functions
```
lion pattern ship = -> pride(3) -> review() -> test() -> pr()
lion "Build feature X" -> ship()

lion function gdpr "Review for GDPR compliance, check data storage, consent, right to deletion"
lion "Build user registration" -> pride(3) -> gdpr() -> review()
```

### Feedback Operator (`<->` and `<N->`)

The `<->` operator creates a feedback loop in the pipeline. When a feedback step (like `review()` or `devil()`) finds issues, the pipeline automatically re-runs the last producer step (like `pride()`) with the feedback as extra context.

```
# <-> re-runs with the original agent count
lion "Build auth" -> pride(5) <-> review() -> test()
  - pride(5) generates code
  - review() finds 2 critical issues
  - pride(5) re-runs with review feedback + deliberation context
  - test() runs on the improved code

# <N-> re-runs with N agents (cost control)
lion "Build auth" -> pride(5) <1-> review() -> test()
  - pride(5) generates code
  - review() finds issues
  - pride(1) re-runs with 1 agent (cheaper, still has full context)

# Multiple feedback loops
lion "Build auth" -> pride(5) <1-> review() <-> devil() -> test() -> pr()
  - review feedback: re-run with 1 agent
  - devil feedback: re-run with 5 agents (original count)
```

**Rules:**
- `<->` sends feedback to the last "producer" step (the last step that generated code, typically `pride` or `test`)
- If the feedback step finds no issues, the re-run is skipped and the pipeline continues normally
- The re-run receives the original prompt, the previous deliberation summary, and the feedback content
- `<N->` overrides the agent count for the re-run (e.g., `<1->` for a cheap single-agent fix)

### Smart Defaults (Complexity Detection)

When no pipeline is specified, Lion uses heuristics (zero tokens):

```python
COMPLEXITY_SIGNALS = {
    "high": [
        "build", "bouw", "create", "design", "architect",
        "migrate", "refactor", "system", "systeem",
        "complete", "full", "hele", "entire"
    ],
    "low": [
        "fix", "bug", "typo", "rename", "change",
        "update", "color", "kleur", "text", "tekst",
        "move", "delete", "remove"
    ]
}

DEFAULT_PIPELINES = {
    "high":   "pride(3) -> review() -> test()",
    "medium": "pride(2) -> review()",
    "low":    ""  # single agent, no pipeline
}
```

---

## 6. Pipeline Functions Reference

### Core Functions

#### `pride(n)` - Multi-Agent Deliberation
The heart of Lion. Spawns N agents that propose, critique, and converge on a solution.

```
pride(3)                              # 3 Claude agents
pride(claude, gemini, codex)          # Mixed LLMs
pride(3, roles: [architect, builder, critic])  # Named roles
```

**Internal phases:**
1. **Propose**: Each agent independently proposes an approach
2. **Critique**: Each agent reads and critiques the others' proposals
3. **Converge**: One agent synthesizes into a final plan
4. **Implement**: Agents implement their parts (parallel where possible)

**Prompt templates:**

```
PROPOSE_PROMPT = """
You are Agent {n} in a pride of {total} working on this task:

TASK: {user_prompt}

PROJECT CONTEXT:
{codebase_summary}

RELEVANT FILES:
{relevant_files}

Propose your approach. Be specific about:
1. Architecture/design decisions
2. Files you would create or modify
3. Key implementation details
4. Potential risks or edge cases

Keep your proposal concise but complete.
"""

CRITIQUE_PROMPT = """
You are Agent {n} reviewing proposals from other agents.

TASK: {user_prompt}

YOUR PROPOSAL:
{own_proposal}

OTHER PROPOSALS:
{other_proposals}

For each other proposal:
1. What do you agree with?
2. What concerns do you have?
3. What did they think of that you missed?
4. What's your updated recommendation?
"""

CONVERGE_PROMPT = """
You are the synthesizer. Multiple agents have proposed and
critiqued approaches for this task:

TASK: {user_prompt}

PROPOSALS AND CRITIQUES:
{all_proposals_and_critiques}

Create the FINAL PLAN that:
1. Takes the best elements from each proposal
2. Addresses all valid critiques
3. Resolves any disagreements with clear reasoning
4. Produces a concrete implementation plan with specific tasks

Output format:
DECISION: [what we're building and why]
TASKS:
  - task_1: [description] | files: [files] | depends_on: []
  - task_2: [description] | files: [files] | depends_on: [task_1]
  ...
"""
```

#### `review()` - Code Review
A separate agent reviews all code changes for quality.

```
review()           # Claude reviews
review(gemini)     # Gemini reviews (free)
```

**Prompt template:**
```
REVIEW_PROMPT = """
Review the following code changes for:
1. Bugs and logic errors
2. Error handling completeness
3. Code style consistency with the existing codebase
4. Performance concerns
5. Missing edge cases

CODE CHANGES:
{diff}

EXISTING CODEBASE PATTERNS:
{codebase_patterns}

For each issue found, specify:
- Severity (critical / warning / suggestion)
- File and approximate location
- The problem
- Suggested fix

If issues are critical, provide the corrected code.
"""
```

#### `test()` - Test Runner
Runs existing tests. If tests fail, an agent fixes them (up to 3 retries).

```
test()             # Run and auto-fix
test(nofix)        # Run only, report failures
```

#### `pr(branch)` - Pull Request
Creates a git branch, commits changes, and optionally creates a PR.

```
pr()                          # Auto-named branch
pr("feature/stripe-checkout") # Named branch
```

### Unique Functions (exist nowhere else)

#### `devil()` - Contrarian / Devil's Advocate
Challenges the consensus. Does NOT look for bugs (that's review). Instead challenges **decisions, assumptions, and architectural choices**.

```
devil()            # Default devil's advocate
devil(aggressive)  # More aggressive challenging
```

**Prompt template:**
```
DEVIL_PROMPT = """
You are the Devil's Advocate. Your job is NOT to find bugs
(the review agent does that). Your job is to challenge the
DECISIONS and ASSUMPTIONS made by the team.

THE TEAM'S APPROACH:
{consensus_plan}

THE CODE THEY WROTE:
{code}

Challenge their work on these dimensions:
1. ASSUMPTIONS: What are they assuming that might not be true?
   (e.g., "they assume low traffic, but what if it 10x's")

2. ARCHITECTURE: Will this design scale? Is it the right pattern?
   Are they going to regret this choice in 6 months?

3. ALTERNATIVES: What approach did they NOT consider that might
   be fundamentally better?

4. DEPENDENCIES: Are they depending on something fragile?
   (external API, specific library version, platform feature)

5. FUTURE PAIN: What will cause problems when:
   - The team grows?
   - The data grows?
   - Requirements change (and they WILL change)?

For each challenge:
- State the assumption or decision you're challenging
- Explain WHY it's risky
- Propose a concrete alternative
- Rate severity: 🔴 rethink now / 🟡 consider / 🟢 minor concern

Be genuinely adversarial. Don't softball it. If the approach is
actually solid, say so - but really try to break it first.
"""
```

#### `future(Nm)` - Time-Travel Review
Evaluates code from the perspective of a developer N months in the future.

```
future(3m)         # 3 months from now
future(6m)         # 6 months from now
future(1y)         # 1 year from now
```

**Prompt template:**
```
FUTURE_PROMPT = """
You are a developer working on this project {time_period} from now.
The code below was written today. You've been using it in production
since then.

CODE:
{code}

ARCHITECTURE DECISIONS:
{decisions}

From your future perspective, write about:

1. FRUSTRATIONS: What drives you crazy about this code now that
   you've been living with it? What do you wish they'd done differently?

2. MISSING FEATURES: What do stakeholders/users keep asking for
   that this code makes very hard to add?

3. SCALING ISSUES: What broke or became painful as usage grew?

4. MAINTENANCE BURDEN: What takes way too long to debug or update?

5. WHAT THEY GOT RIGHT: What are you grateful they thought of?

6. IF I COULD GO BACK: What specific changes would you tell the
   original developers to make right now, today, that would save
   you enormous pain in the future?

Be specific. Use concrete scenarios. Don't be vague.
"""
```

#### `onboard()` - Onboarding Documentation
Generates documentation for a new team member.

```
onboard()          # Full onboarding doc
```

**Prompt template:**
```
ONBOARD_PROMPT = """
A new developer joins the team tomorrow. They need to understand
the code that was just written/changed.

Write onboarding documentation that explains:

1. WHAT: What does this code do? (high level, no jargon)
2. WHY: Why was it built this way? What alternatives were considered?
3. HOW: How does it work? Walk through the main flow.
4. WHERE: Which files matter? What's the entry point?
5. GOTCHAS: What's non-obvious? What will trip someone up?
6. TESTING: How to run tests, what they cover, what they don't.
7. DEPENDENCIES: What external services/APIs does this use?
8. DEPLOYMENT: Any special deployment considerations?

Write for a competent developer who doesn't know this specific
codebase. Use diagrams (ASCII) where helpful.

CODE:
{code}

DECISIONS MADE:
{decisions}
"""
```

#### `audit()` - Security Audit
```
AUDIT_PROMPT = """
Perform a security audit on the following code changes.

Check against:
1. OWASP Top 10 (injection, XSS, broken auth, etc.)
2. Dependency vulnerabilities (known CVEs)
3. Secrets/credentials accidentally included
4. Input validation completeness
5. Authentication/authorization gaps
6. Data exposure risks (PII, sensitive data in logs)
7. Rate limiting and abuse prevention

CODE CHANGES:
{diff}

DEPENDENCIES ADDED:
{new_dependencies}

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Category (OWASP reference if applicable)
- Location in code
- Attack scenario
- Remediation steps with code
"""
```

#### `cost()` - Infrastructure Cost Assessment

**IMPORTANT:** This function does NOT generate cost estimates. LLM-generated
cost numbers are unreliable because cloud pricing is complex, region-dependent,
and changes frequently. Users may make budget decisions based on hallucinated
estimates.

Instead, `cost()` generates:
1. A **cost checklist** of detected infrastructure components
2. **Pricing factors** you should look up for each component
3. **Direct links** to cloud pricing calculators
4. **Questions** about usage patterns that affect cost

```python
# Output structure (returned as structured JSON + markdown display)
{
    "components": [
        {
            "name": "aws-lambda",
            "type": "compute",
            "source_file": "serverless.yml",
            "confidence": "high",
            "pricing_factors": [
                "Number of requests per month",
                "Average execution duration (ms)",
                "Memory allocated (MB)"
            ],
            "pricing_calculator": "https://calculator.aws/#/createCalculator/Lambda",
            "questions": ["What's your expected requests per month?"],
            "assumptions": ["Public pricing, no reserved instances"]
        }
    ],
    "questions": ["What is your expected traffic?"],
    "assumptions": ["Single region deployment"],
    "next_steps": ["Use pricing calculators with YOUR usage data"]
}
```

The user plugs in real numbers using the pricing tools and their actual usage data.

#### `explain()` - Decision Documentation
```
EXPLAIN_PROMPT = """
Document the architectural decisions made in this code.

For each significant decision, create an ADR (Architecture
Decision Record) with:
- Title
- Context: What was the situation?
- Decision: What did we decide?
- Alternatives considered: What else was evaluated?
- Consequences: What are the trade-offs?
- Status: Accepted

CODE:
{code}

DELIBERATION HISTORY (if available):
{deliberation_log}
"""
```

#### `migrate()` - Migration Planning Assistant

**IMPORTANT:** This function does NOT generate migration plans. Static file
analysis cannot verify runtime dependencies, understand your specific failure
modes, or guarantee rollback procedures work with your state management.

A migration plan that says "use blue-green deployment" when your database
doesn't support multi-writer is actively harmful. Users following AI-generated
migration plans without verification is how outages happen.

Instead, `migrate()` generates:
1. A **migration assessment questionnaire** - questions you MUST answer
2. **Detected changes** requiring migration (schema, config, dependencies)
3. A **checklist of considerations** with "VERIFY THIS ASSUMPTION" callouts
4. **Links to documentation** for your detected tech stack

```python
# Output structure (returned as structured JSON + markdown display)
{
    "detected_changes": [
        {
            "change_type": "schema",
            "description": "Column addition detected",
            "file": "migrations/0042_add_user_email.py",
            "risk": "low",
            "confidence": "detected",
            "questions": ["Is this column nullable?"],
            "assumptions": ["VERIFY: Migration is backward-compatible"],
            "considerations": ["Can run without downtime if nullable"]
        }
    ],
    "questions": [
        {
            "question": "Do you have shared state between old and new versions?",
            "category": "state",
            "why_it_matters": "Shared state can cause data corruption during rollout",
            "options": ["No shared state", "Shared database", "Shared cache"]
        }
    ],
    "tech_stack_detected": ["django", "postgresql", "kubernetes"],
    "documentation_links": ["Django Migrations: https://..."],
    "assumptions": ["VERIFY: You have a staging environment"],
    "confidence_summary": "MEDIUM - verify all assumptions"
}
```

The user answers the questions, verifies assumptions, and creates their actual
migration plan based on this assessment.

---

## 7. Provider System (Multi-LLM)

### Provider Interface

```python
# providers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class AgentResult:
    content: str
    model: str
    tokens_used: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None

class Provider(ABC):
    """Base class for all LLM providers."""

    name: str

    @abstractmethod
    def ask(self, prompt: str, system_prompt: str = "",
            cwd: str = ".") -> AgentResult:
        """Send a prompt and get a response."""
        pass

    @abstractmethod
    def ask_with_files(self, prompt: str, files: list[str],
                       system_prompt: str = "",
                       cwd: str = ".") -> AgentResult:
        """Send a prompt with file context."""
        pass

    @abstractmethod
    def implement(self, prompt: str, cwd: str = ".") -> AgentResult:
        """Ask the agent to make code changes in the filesystem."""
        pass
```

### Claude Code Provider

```python
# providers/claude.py

import subprocess
import json
import time
from .base import Provider, AgentResult

class ClaudeProvider(Provider):
    name = "claude"

    def ask(self, prompt, system_prompt="", cwd="."):
        """Use claude -p for non-interactive single-turn."""
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd
        )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model="claude", tokens_used=0,
                duration_seconds=duration, success=False,
                error=result.stderr
            )

        try:
            output = json.loads(result.stdout)
            return AgentResult(
                content=output.get("result", result.stdout),
                model="claude",
                tokens_used=output.get("tokens_used", 0),
                duration_seconds=duration,
                success=True
            )
        except json.JSONDecodeError:
            return AgentResult(
                content=result.stdout,
                model="claude", tokens_used=0,
                duration_seconds=duration, success=True
            )

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        """Include file contents in the prompt."""
        file_contents = []
        for f in files:
            try:
                with open(f, 'r') as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                file_contents.append(f"--- {f} --- (could not read)")

        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        """Use claude -p to make actual file changes."""
        # claude -p with instructions to edit files
        impl_prompt = f"""
{prompt}

IMPORTANT: Make the actual code changes. Edit the files directly.
Create new files as needed. Do not just describe what to do - do it.
"""
        return self.ask(impl_prompt, cwd=cwd)
```

### Gemini Provider

```python
# providers/gemini.py

import subprocess
import time
from .base import Provider, AgentResult

class GeminiProvider(Provider):
    name = "gemini"

    def ask(self, prompt, system_prompt="", cwd="."):
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd = ["gemini", "-p", full_prompt]
        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd
        )
        duration = time.time() - start

        return AgentResult(
            content=result.stdout,
            model="gemini",
            tokens_used=0,  # Gemini CLI is free
            duration_seconds=duration,
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None
        )

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        file_contents = []
        for f in files:
            try:
                with open(f, 'r') as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                pass
        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        return self.ask(prompt, cwd=cwd)
```

### Ollama Provider (Local Models - Free)

```python
# providers/ollama.py

import subprocess
import time
from .base import Provider, AgentResult

class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model="llama3"):
        self.model = model

    def ask(self, prompt, system_prompt="", cwd="."):
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        cmd = ["ollama", "run", self.model, full_prompt]
        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd
        )
        duration = time.time() - start

        return AgentResult(
            content=result.stdout,
            model=f"ollama/{self.model}",
            tokens_used=0,
            duration_seconds=duration,
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None
        )

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        file_contents = []
        for f in files:
            try:
                with open(f, 'r') as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                pass
        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        return self.ask(prompt, cwd=cwd)
```

### API Provider (Generic - for any OpenAI-compatible API)

```python
# providers/api.py

import requests
import time
import os
from .base import Provider, AgentResult

class APIProvider(Provider):
    name = "api"

    def __init__(self, endpoint, model, api_key_env):
        self.endpoint = endpoint
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")

    def ask(self, prompt, system_prompt="", cwd="."):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.time()
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 4096
                },
                timeout=120
            )
            duration = time.time() - start
            data = response.json()

            return AgentResult(
                content=data["choices"][0]["message"]["content"],
                model=self.model,
                tokens_used=data.get("usage", {}).get("total_tokens", 0),
                duration_seconds=duration,
                success=True
            )
        except Exception as e:
            return AgentResult(
                content="", model=self.model, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=str(e)
            )

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        file_contents = []
        for f in files:
            try:
                with open(f, 'r') as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                pass
        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        return self.ask(prompt, cwd=cwd)
```

### Provider Registry

```python
# providers/__init__.py

from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .api import APIProvider

PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

def get_provider(name: str, config: dict = None):
    """Get a provider instance by name."""
    if name in PROVIDERS:
        return PROVIDERS[name]()

    # Check if it's an API provider from config
    if config and name in config.get("providers", {}):
        pconfig = config["providers"][name]
        if pconfig["type"] == "api":
            return APIProvider(
                endpoint=pconfig["endpoint"],
                model=pconfig["model"],
                api_key_env=pconfig["api_key_env"]
            )

    raise ValueError(f"Unknown provider: {name}")
```

---

## 8. Shared Memory & Agent Communication

### Format: JSONL (one JSON object per line)

```python
# memory.py

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class MemoryEntry:
    timestamp: float
    phase: str          # propose, critique, converge, implement, review, etc.
    agent: str          # agent identifier (e.g., "agent_1", "claude", "gemini")
    type: str           # proposal, critique, answer, question, decision, code, error
    content: str        # the actual content
    target: Optional[str] = None  # who this is directed at
    metadata: Optional[dict] = None  # extra data (files changed, etc.)

class SharedMemory:
    """JSONL-based shared memory for agent communication."""

    def __init__(self, run_dir: str):
        self.filepath = os.path.join(run_dir, "memory.jsonl")
        os.makedirs(run_dir, exist_ok=True)

    def write(self, entry: MemoryEntry):
        """Append an entry to shared memory."""
        with open(self.filepath, 'a') as f:
            f.write(json.dumps(asdict(entry)) + '\n')

    def read_all(self) -> list[MemoryEntry]:
        """Read all entries."""
        entries = []
        if not os.path.exists(self.filepath):
            return entries
        with open(self.filepath, 'r') as f:
            for line in f:
                if line.strip():
                    entries.append(MemoryEntry(**json.loads(line)))
        return entries

    def read_phase(self, phase: str) -> list[MemoryEntry]:
        """Read entries for a specific phase."""
        return [e for e in self.read_all() if e.phase == phase]

    def read_agent(self, agent: str) -> list[MemoryEntry]:
        """Read entries from a specific agent."""
        return [e for e in self.read_all() if e.agent == agent]

    def get_proposals(self) -> list[MemoryEntry]:
        """Get all proposals."""
        return self.read_phase("propose")

    def get_critiques(self) -> list[MemoryEntry]:
        """Get all critiques."""
        return self.read_phase("critique")

    def get_decisions(self) -> list[MemoryEntry]:
        """Get all decisions."""
        return [e for e in self.read_all() if e.type == "decision"]

    def format_for_prompt(self, entries: list[MemoryEntry]) -> str:
        """Format entries as text for including in prompts."""
        lines = []
        for e in entries:
            prefix = f"[{e.agent}]"
            if e.target:
                prefix += f" → [{e.target}]"
            lines.append(f"{prefix}: {e.content}")
        return "\n\n".join(lines)
```

### Example Memory Flow

```jsonl
{"timestamp":1708000001,"phase":"propose","agent":"agent_1","type":"proposal","content":"I propose using a service layer pattern with PaymentService...","target":null,"metadata":{"model":"claude"}}
{"timestamp":1708000002,"phase":"propose","agent":"agent_2","type":"proposal","content":"I suggest starting with the database schema...","target":null,"metadata":{"model":"gemini"}}
{"timestamp":1708000003,"phase":"propose","agent":"agent_3","type":"proposal","content":"Quick implementation: Stripe Checkout Session API...","target":null,"metadata":{"model":"claude"}}
{"timestamp":1708000010,"phase":"critique","agent":"agent_1","type":"critique","content":"Agent 2 makes a good point about schema-first, but misses webhook handling...","target":"agent_2","metadata":null}
{"timestamp":1708000011,"phase":"critique","agent":"agent_2","type":"critique","content":"Agent 1's service layer is solid. Agent 3's approach is too simple...","target":"agent_1","metadata":null}
{"timestamp":1708000020,"phase":"converge","agent":"synthesizer","type":"decision","content":"Final plan: 1) Schema migration 2) PaymentService 3) Webhooks 4) UI","target":null,"metadata":{"tasks":["schema","service","webhooks","ui"]}}
{"timestamp":1708000030,"phase":"implement","agent":"agent_1","type":"code","content":"Implemented schema migration","target":null,"metadata":{"files":["migrations/001_payments.sql"]}}
```

---

## 9. Escalation & Human Interaction

### When Lion Asks the User

Lion escalates to the user in these scenarios:

1. **No consensus after max rounds**: Agents can't agree
2. **Repeated failure**: An agent fails the same task 3 times
3. **Explicit user config**: The task type requires approval
4. **Ambiguity**: The prompt is too vague to act on

### Escalation Implementation

```python
# escalation.py

import sys
import json

class Escalation:
    """Handles communication with the user during a Lion run."""

    @staticmethod
    def ask_choice(question: str, options: list[str]) -> int:
        """Present a choice to the user, return the index."""
        print(f"\n🦁 Lion needs your input:\n")
        print(f"   {question}\n")
        for i, option in enumerate(options, 1):
            print(f"   [{i}] {option}")
        print()

        while True:
            try:
                choice = input("   Your choice: ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return idx
            except (ValueError, EOFError):
                pass
            print(f"   Please enter a number between 1 and {len(options)}")

    @staticmethod
    def ask_text(question: str) -> str:
        """Ask the user for free-text input."""
        print(f"\n🦁 Lion needs your input:\n")
        print(f"   {question}\n")
        return input("   > ").strip()

    @staticmethod
    def notify(message: str):
        """Display a notification to the user."""
        print(f"\n🦁 {message}")

    @staticmethod
    def show_deliberation(proposals: list, critiques: list):
        """Show the deliberation summary to the user."""
        print(f"\n🦁 Deliberation summary:\n")
        for i, p in enumerate(proposals, 1):
            agent_name = p.agent
            model = p.metadata.get("model", "unknown") if p.metadata else "unknown"
            print(f"   Agent {i} ({model}):")
            # Show first 200 chars of proposal
            preview = p.content[:200] + "..." if len(p.content) > 200 else p.content
            for line in preview.split('\n'):
                print(f"     {line}")
            print()

    @staticmethod
    def no_consensus(proposals: list, critiques: list) -> str:
        """Handle no-consensus scenario. Returns user's decision."""
        print(f"\n🦁 Pride could not reach consensus.\n")

        options = []
        for i, p in enumerate(proposals, 1):
            summary = p.content[:100] + "..." if len(p.content) > 100 else p.content
            options.append(f"Agent {i}'s approach: {summary}")
        options.append("Let the pride try one more round")
        options.append("Take over manually in Claude Code")

        choice = Escalation.ask_choice("Which approach should we go with?", options)

        if choice < len(proposals):
            return f"use_proposal:{choice}"
        elif choice == len(proposals):
            return "retry"
        else:
            return "takeover"

    @staticmethod
    def agent_stuck(agent_name: str, error: str) -> str:
        """Handle agent stuck scenario."""
        print(f"\n🦁 Agent '{agent_name}' is stuck.\n")
        print(f"   Error: {error}\n")

        choice = Escalation.ask_choice(
            "How should we proceed?",
            [
                "Give a hint to the agent",
                "Skip this task",
                "Take over in Claude Code"
            ]
        )

        if choice == 0:
            hint = Escalation.ask_text("Your hint:")
            return f"hint:{hint}"
        elif choice == 1:
            return "skip"
        else:
            return "takeover"
```

---

## 10. Cost Optimization

### Cost Profiles

```toml
# In config.toml

[profiles.cheap]
description = "Minimize Claude usage, use free providers for thinking"
propose = ["gemini", "gemini", "ollama"]
critique = ["gemini", "gemini", "ollama"]
converge = "claude"
implement = "claude"
review = "gemini"

[profiles.balanced]
description = "Mix of quality and cost"
propose = ["claude", "gemini", "gemini"]
critique = ["claude", "gemini", "gemini"]
converge = "claude"
implement = "claude"
review = "claude"

[profiles.premium]
description = "Maximum quality, all Claude"
propose = ["claude", "claude", "claude"]
critique = ["claude", "claude", "claude"]
converge = "claude"
implement = "claude"
review = "claude"
```

### Usage Estimation

```
Task: "Build Stripe checkout" -> pride(3) -> review()

Profile: cheap
  Propose:    3 × gemini/ollama  = 0 Claude prompts
  Critique:   3 × gemini/ollama  = 0 Claude prompts
  Converge:   1 × claude         = 1 Claude prompt
  Implement:  1 × claude         = ~5 Claude prompts
  Review:     1 × gemini         = 0 Claude prompts
  TOTAL: ~6 Claude prompts (vs ~15-20 without Lion)

Profile: balanced
  Propose:    1 claude + 2 gemini = 1 Claude prompt
  Critique:   1 claude + 2 gemini = 1 Claude prompt
  Converge:   1 × claude          = 1 Claude prompt
  Implement:  1 × claude          = ~5 Claude prompts
  Review:     1 × claude          = 2 Claude prompts
  TOTAL: ~10 Claude prompts

Profile: premium
  Propose:    3 × claude          = 3 Claude prompts
  Critique:   3 × claude          = 3 Claude prompts
  Converge:   1 × claude          = 1 Claude prompt
  Implement:  3 × claude          = ~9 Claude prompts
  Review:     1 × claude          = 2 Claude prompts
  TOTAL: ~18 Claude prompts
```

### Rate Limit Awareness

```python
# cost.py

class CostManager:
    """Tracks usage and prevents hitting rate limits."""

    def __init__(self, config):
        self.max_prompts_per_5h = config.get("max_prompts_per_5h", 200)
        self.prompts_used = 0
        self.session_start = time.time()

    def can_use(self, provider_name: str) -> bool:
        """Check if we can use this provider without hitting limits."""
        if provider_name in ["gemini", "ollama"]:
            return True  # Free providers, always ok

        if provider_name == "claude":
            return self.prompts_used < self.max_prompts_per_5h

        return True

    def record_use(self, provider_name: str, tokens: int = 0):
        """Record usage of a provider."""
        if provider_name == "claude":
            self.prompts_used += 1

    def suggest_profile(self, remaining_prompts: int) -> str:
        """Suggest a cost profile based on remaining budget."""
        if remaining_prompts > 100:
            return "premium"
        elif remaining_prompts > 30:
            return "balanced"
        else:
            return "cheap"
```

---

## 11. Configuration

### Default Config File: `~/.lion/config.toml`

```toml
# Lion Configuration

[general]
default_profile = "balanced"
max_pride_size = 5
max_retries = 3
max_deliberation_rounds = 2
verbose = false
run_history_dir = "~/.lion/runs"

[providers]
default = "claude"

[providers.claude]
type = "cli"
command = "claude"
args = ["-p", "{prompt}", "--output-format", "json"]

[providers.gemini]
type = "cli"
command = "gemini"
args = ["-p", "{prompt}"]

[providers.ollama]
type = "cli"
command = "ollama"
args = ["run", "llama3.1", "{prompt}"]
model = "llama3.1"

[providers.gpt4o]
type = "api"
endpoint = "https://api.openai.com/v1/chat/completions"
model = "gpt-4o"
api_key_env = "OPENAI_API_KEY"

# Cost profiles
[profiles.cheap]
propose = ["gemini", "gemini", "ollama"]
critique = ["gemini", "gemini", "ollama"]
converge = "claude"
implement = "claude"
review = "gemini"

[profiles.balanced]
propose = ["claude", "gemini", "gemini"]
critique = ["claude", "gemini", "gemini"]
converge = "claude"
implement = "claude"
review = "claude"

[profiles.premium]
propose = ["claude", "claude", "claude"]
critique = ["claude", "claude", "claude"]
converge = "claude"
implement = "claude"
review = "claude"

# Saved patterns
[patterns]
ship = "pride(3) -> review() -> test() -> pr()"
bulletproof = "pride(3) -> devil() -> future(6m) -> review() -> test() -> audit()"
quick = "review() -> test()"
explore = "pride(5) -> devil()"

# Complexity detection
[complexity]
high_signals = ["build", "bouw", "create", "design", "architect", "migrate", "refactor", "system", "systeem", "complete", "full"]
low_signals = ["fix", "bug", "typo", "rename", "change", "update", "color", "move", "delete", "remove"]
high_pipeline = "pride(3) -> review() -> test()"
medium_pipeline = "pride(2) -> review()"
low_pipeline = ""  # single agent, no pipeline
```

---

## 12. Implementation Phases

### Phase 1: Core (MVP) - "Lion can roar"
**Goal**: `lion "prompt" -> pride(3)` works from Claude Code.

Build:
- [x] `hook.py` - Intercepts `lion ` prefix in Claude Code
- [x] `lion.py` - Main CLI entry point
- [x] `parser.py` - Splits prompt from pipeline, parses pipeline functions
- [x] `providers/claude.py` - Claude Code CLI wrapper
- [x] `functions/pride.py` - Basic pride: propose → critique → converge → implement
- [x] `memory.py` - Shared JSONL memory
- [x] `display.py` - Terminal output formatting

Test: `lion "Build a hello world API" -> pride(3)` should produce working code.

### Phase 2: Pipeline & Review - "The pride hunts"
**Goal**: Full pipeline composition with review and test.

Build:
- [x] `pipeline.py` - Pipeline executor that chains functions
- [x] `functions/review.py` - Code review function
- [x] `functions/test.py` - Test runner with auto-fix
- [x] `functions/pr.py` - Git branch + PR creation
- [x] `escalation.py` - User interaction for stuck agents
- [x] Smart defaults - Complexity detection without LLM

Test: `lion "Build Stripe checkout" -> pride(3) -> review() -> test() -> pr("feature/stripe")` should produce reviewed, tested code on a branch.

### Phase 3: Unique Functions - "The king's weapons"
**Goal**: Functions that exist nowhere else.

Build:
- [x] `functions/devil.py` - Contrarian / devil's advocate
- [x] `functions/future.py` - Time-travel review
- [x] `functions/onboard.py` - Onboarding documentation
- [x] `functions/audit.py` - Security audit
- [ ] `functions/explain.py` - Decision documentation
- [x] `functions/cost.py` - Infrastructure cost estimation
- [x] `functions/migrate.py` - Migration plan generation

Test: `lion "Build auth system" -> pride(3) -> devil() -> future(6m) -> review()` should produce code that has been challenged, future-proofed, and reviewed.

### Phase 4: Multi-LLM - "The diverse pride"
**Goal**: Mixed LLM support.

Build:
- [x] `providers/gemini.py` - Gemini CLI wrapper
- [ ] `providers/ollama.py` - Local model wrapper
- [ ] `providers/api.py` - Generic API wrapper
- [x] Provider selection in pride syntax (implemented for available providers): `pride(claude, gemini, codex)`
- [x] Cost profiles (cheap, balanced, premium)
- [x] Cost tracking and rate limit awareness

Test: `lion "Build feature" -> pride(claude, gemini, ollama) -> review(claude)` should use multiple LLMs in deliberation.

### Phase 5: Patterns & Extensions - "The pride's wisdom"
**Goal**: Saved patterns and custom functions.

Build:
- [ ] `patterns.py` - Save and load custom patterns
- [ ] `custom_functions.py` - User-defined pipeline functions
- [ ] `lion pattern <name> = <pipeline>` command
- [ ] `lion function <name> "<description>"` command
- [ ] Per-project `.lion/` config directory
- [ ] Run history with results appended to run logs

Test: `lion pattern ship = -> pride(3) -> review() -> test() -> pr()` then `lion "Build X" -> ship()` should work.

### Phase 6: Self-Build - "Lion builds Lion"
**Goal**: Use Lion to develop Lion itself.

Once phases 1-5 are complete:
- All new Lion features are built using Lion
- `lion "Add websocket support to Lion" -> pride(3) -> devil() -> review() -> test()`
- Lion improves itself through its own pipeline

---

## 13. File Structure

```
~/.lion/
├── lion.py                     # Main CLI entry point
├── hook.py                     # Claude Code UserPromptSubmit hook
├── parser.py                   # Pipeline parser
├── pipeline.py                 # Pipeline executor
├── memory.py                   # Shared JSONL memory
├── escalation.py               # User interaction handler
├── display.py                  # Terminal UI / progress display
├── cost.py                     # Cost tracking and optimization
├── config.toml                 # User configuration
│
├── providers/
│   ├── __init__.py             # Provider registry
│   ├── base.py                 # Abstract provider interface
│   ├── claude.py               # Claude Code CLI provider
│   ├── gemini.py               # Gemini CLI provider
│   ├── ollama.py               # Ollama local model provider
│   └── api.py                  # Generic API provider
│
├── functions/
│   ├── __init__.py             # Function registry
│   ├── pride.py                # Multi-agent deliberation
│   ├── review.py               # Code review
│   ├── test.py                 # Test runner
│   ├── pr.py                   # Git PR creation
│   ├── devil.py                # Devil's advocate
│   ├── future.py               # Time-travel review
│   ├── onboard.py              # Onboarding docs
│   ├── audit.py                # Security audit
│   ├── explain.py              # Decision documentation
│   ├── cost_estimate.py        # Infra cost estimation
│   └── migrate.py              # Migration planning
│
├── patterns/
│   └── user_patterns.json      # Saved user patterns
│
├── custom_functions/
│   └── *.json                  # User-defined functions
│
└── runs/
    ├── 2026-02-20_153200_stripe_checkout/
    │   ├── memory.jsonl         # Deliberation log
    │   ├── result.json          # Final result summary
    │   └── diff.patch           # Code changes
    └── ...
```

---

## 14. Detailed Implementation Guide

### 14.1 Main Entry Point (lion.py)

```python
#!/usr/bin/env python3
"""
🦁 Lion - Language for Intelligent Orchestration Networks

Usage:
    lion "Build a feature"
    lion "Build a feature" -> pride(3) -> review()
    lion "Build a feature" -> pride(claude, gemini) -> devil() -> review()
"""

import sys
import os
import time
import tomllib
from parser import parse_lion_input
from pipeline import PipelineExecutor
from display import Display
from cost import CostManager

LION_DIR = os.path.expanduser("~/.lion")

def load_config():
    config_path = os.path.join(LION_DIR, "config.toml")
    if os.path.exists(config_path):
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    return {}

def detect_complexity(prompt: str, config: dict) -> str:
    """Detect task complexity using simple heuristics (0 tokens)."""
    prompt_lower = prompt.lower()
    high = config.get("complexity", {}).get("high_signals", [])
    low = config.get("complexity", {}).get("low_signals", [])

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
        print("🦁 Lion - Language for Intelligent Orchestration Networks")
        print()
        print("Usage:")
        print('  lion "Build a feature"')
        print('  lion "Build a feature" -> pride(3) -> review()')
        print()
        print("Pipeline functions:")
        print("  pride(n)     Multi-agent deliberation")
        print("  review()     Code review")
        print("  test()       Run tests with auto-fix")
        print("  devil()      Devil's advocate challenge")
        print("  future(Nm)   Time-travel review")
        print("  audit()      Security audit")
        print("  onboard()    Generate onboarding docs")
        print("  pr(branch)   Create git PR")
        sys.exit(0)

    # Join all arguments (handles shell quoting issues)
    raw_input = " ".join(sys.argv[1:])

    # Load config
    config = load_config()

    # Parse input into prompt + pipeline
    prompt, pipeline_steps = parse_lion_input(raw_input, config)

    # If no pipeline specified, detect complexity and use defaults
    if not pipeline_steps:
        complexity = detect_complexity(prompt, config)
        default_pipeline = config.get("complexity", {}).get(
            f"{complexity}_pipeline", ""
        )
        if default_pipeline:
            _, pipeline_steps = parse_lion_input(
                f'"{prompt}" -> {default_pipeline}', config
            )
            Display.auto_pipeline(complexity, default_pipeline)

    # Create run directory
    run_id = time.strftime("%Y-%m-%d_%H%M%S") + "_" + \
             prompt[:30].replace(" ", "_").replace("/", "_")
    run_dir = os.path.join(LION_DIR, "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Get working directory
    cwd = os.environ.get("LION_CWD", os.getcwd())

    # Initialize cost manager
    cost_mgr = CostManager(config)

    # Execute pipeline
    executor = PipelineExecutor(
        prompt=prompt,
        steps=pipeline_steps,
        config=config,
        run_dir=run_dir,
        cwd=cwd,
        cost_manager=cost_mgr
    )

    try:
        result = executor.run()
        Display.final_result(result)
    except KeyboardInterrupt:
        Display.cancelled()
    except Exception as e:
        Display.error(str(e))
        raise

if __name__ == "__main__":
    main()
```

### 14.2 Parser (parser.py)

```python
"""
Parse lion input into prompt and pipeline steps.

Examples:
    'Build a feature'
        → prompt="Build a feature", steps=[]

    'Build a feature -> pride(3) -> review()'
        → prompt="Build a feature", steps=[Step("pride", [3]), Step("review", [])]

    'Build X -> pride(claude, gemini) -> devil() -> review(claude)'
        → prompt="Build X", steps=[
            Step("pride", ["claude", "gemini"]),
            Step("devil", []),
            Step("review", ["claude"])
          ]
"""

import re
from dataclasses import dataclass
from typing import Any

@dataclass
class PipelineStep:
    function: str       # e.g., "pride", "review", "devil"
    args: list[Any]     # e.g., [3], ["claude", "gemini"], ["6m"]
    kwargs: dict        # e.g., {"roles": ["architect", "builder"]}

def parse_lion_input(raw: str, config: dict = None) -> tuple[str, list[PipelineStep]]:
    """Parse raw lion input into prompt and pipeline steps."""
    config = config or {}

    # Split on " -> " to separate prompt from pipeline
    parts = re.split(r'\s*->\s*', raw, maxsplit=1)

    prompt = parts[0].strip().strip('"').strip("'")

    if len(parts) < 2:
        return prompt, []

    pipeline_str = parts[1]

    # Split remaining on " -> "
    step_strings = re.split(r'\s*->\s*', pipeline_str)

    steps = []
    for step_str in step_strings:
        step_str = step_str.strip()
        if not step_str:
            continue

        step = parse_step(step_str, config)
        if step:
            steps.append(step)

    return prompt, steps

def parse_step(step_str: str, config: dict) -> PipelineStep:
    """Parse a single pipeline step like 'pride(3)' or 'review(claude)'."""

    # Check if it's a saved pattern
    patterns = config.get("patterns", {})
    if step_str.rstrip("()") in patterns:
        pattern_name = step_str.rstrip("()")
        pattern_pipeline = patterns[pattern_name]
        # Recursively parse the pattern (returns steps, we take the first)
        _, pattern_steps = parse_lion_input(f'"_" -> {pattern_pipeline}', config)
        # Return a meta-step that expands to multiple steps
        return PipelineStep(
            function="__pattern__",
            args=pattern_steps,
            kwargs={"name": pattern_name}
        )

    # Parse function name and arguments
    match = re.match(r'(\w+)\((.*?)\)', step_str)
    if not match:
        # No parentheses - treat as function with no args
        return PipelineStep(function=step_str, args=[], kwargs={})

    func_name = match.group(1)
    args_str = match.group(2).strip()

    if not args_str:
        return PipelineStep(function=func_name, args=[], kwargs={})

    # Parse arguments
    args = []
    kwargs = {}

    for arg in split_args(args_str):
        arg = arg.strip()
        if ':' in arg and not arg.startswith('"'):
            # Keyword argument: key: value
            key, value = arg.split(':', 1)
            kwargs[key.strip()] = parse_value(value.strip())
        else:
            args.append(parse_value(arg))

    return PipelineStep(function=func_name, args=args, kwargs=kwargs)

def split_args(args_str: str) -> list[str]:
    """Split comma-separated args, respecting brackets and quotes."""
    args = []
    depth = 0
    current = ""
    in_quotes = False

    for char in args_str:
        if char == '"':
            in_quotes = not in_quotes
        elif char in '([' and not in_quotes:
            depth += 1
        elif char in ')]' and not in_quotes:
            depth -= 1
        elif char == ',' and depth == 0 and not in_quotes:
            args.append(current)
            current = ""
            continue
        current += char

    if current.strip():
        args.append(current)

    return args

def parse_value(value: str) -> Any:
    """Parse a value string into appropriate type."""
    value = value.strip().strip('"').strip("'")

    # Integer
    try:
        return int(value)
    except ValueError:
        pass

    # Duration (e.g., "6m", "1y")
    if re.match(r'^\d+[mywdh]$', value):
        return value

    # List (e.g., [architect, builder])
    if value.startswith('[') and value.endswith(']'):
        items = value[1:-1].split(',')
        return [item.strip().strip('"') for item in items]

    # String (provider name, branch name, etc.)
    return value
```

### 14.3 Pipeline Executor (pipeline.py)

```python
"""Execute a parsed pipeline of steps."""

import time
from dataclasses import dataclass
from typing import Any, Optional
from parser import PipelineStep
from memory import SharedMemory
from display import Display
from providers import get_provider

# Import all pipeline functions
from functions.pride import execute_pride
from functions.review import execute_review
from functions.test import execute_test
from functions.devil import execute_devil
from functions.future import execute_future
from functions.pr import execute_pr
from functions.onboard import execute_onboard
from functions.audit import execute_audit
from functions.explain import execute_explain

# Function registry
FUNCTIONS = {
    "pride": execute_pride,
    "review": execute_review,
    "test": execute_test,
    "devil": execute_devil,
    "future": execute_future,
    "pr": execute_pr,
    "onboard": execute_onboard,
    "audit": execute_audit,
    "explain": execute_explain,
}

@dataclass
class PipelineResult:
    success: bool
    prompt: str
    steps_completed: int
    total_steps: int
    outputs: list[dict]
    total_duration: float
    total_tokens: int
    files_changed: list[str]
    errors: list[str]

class PipelineExecutor:
    def __init__(self, prompt, steps, config, run_dir, cwd, cost_manager):
        self.prompt = prompt
        self.steps = self._expand_patterns(steps)
        self.config = config
        self.run_dir = run_dir
        self.cwd = cwd
        self.cost_manager = cost_manager
        self.memory = SharedMemory(run_dir)
        self.outputs = []
        self.files_changed = []
        self.errors = []
        self.total_tokens = 0

    def _expand_patterns(self, steps):
        """Expand __pattern__ meta-steps into actual steps."""
        expanded = []
        for step in steps:
            if step.function == "__pattern__":
                expanded.extend(step.args)  # args contains the pattern's steps
            else:
                expanded.append(step)
        return expanded

    def run(self) -> PipelineResult:
        """Execute the full pipeline."""
        start_time = time.time()

        Display.pipeline_start(self.prompt, self.steps)

        # If no pipeline steps, just run a single agent
        if not self.steps:
            result = self._run_single_agent()
            return PipelineResult(
                success=result.get("success", False),
                prompt=self.prompt,
                steps_completed=1,
                total_steps=1,
                outputs=[result],
                total_duration=time.time() - start_time,
                total_tokens=self.total_tokens,
                files_changed=result.get("files_changed", []),
                errors=[]
            )

        # Execute pipeline steps sequentially
        # Each step receives the output of the previous step
        previous_output = {"prompt": self.prompt, "code": "", "decisions": []}

        for i, step in enumerate(self.steps):
            Display.step_start(i + 1, len(self.steps), step)

            func = FUNCTIONS.get(step.function)
            if not func:
                self.errors.append(f"Unknown function: {step.function}")
                Display.step_error(step.function, f"Unknown function")
                continue

            try:
                step_result = func(
                    prompt=self.prompt,
                    previous=previous_output,
                    step=step,
                    memory=self.memory,
                    config=self.config,
                    cwd=self.cwd,
                    cost_manager=self.cost_manager
                )

                self.outputs.append(step_result)
                self.total_tokens += step_result.get("tokens_used", 0)
                self.files_changed.extend(step_result.get("files_changed", []))

                # Pass output to next step
                previous_output = {
                    **previous_output,
                    **step_result
                }

                Display.step_complete(step.function, step_result)

            except Exception as e:
                self.errors.append(f"{step.function}: {str(e)}")
                Display.step_error(step.function, str(e))

                # Decide whether to continue or abort
                if step_result.get("critical", False):
                    break

        return PipelineResult(
            success=len(self.errors) == 0,
            prompt=self.prompt,
            steps_completed=len(self.outputs),
            total_steps=len(self.steps),
            outputs=self.outputs,
            total_duration=time.time() - start_time,
            total_tokens=self.total_tokens,
            files_changed=list(set(self.files_changed)),
            errors=self.errors
        )

    def _run_single_agent(self) -> dict:
        """Run a single agent without pipeline (for simple tasks)."""
        provider = get_provider(
            self.config.get("providers", {}).get("default", "claude"),
            self.config
        )
        result = provider.implement(self.prompt, cwd=self.cwd)
        return {
            "success": result.success,
            "content": result.content,
            "tokens_used": result.tokens_used,
            "files_changed": [],
        }
```

### 14.4 Pride Function (functions/pride.py)

```python
"""
pride() - Multi-agent deliberation.

The heart of Lion. Spawns multiple agents that:
1. Propose approaches independently (parallel)
2. Critique each other's proposals (parallel)
3. Converge on a consensus plan (single agent)
4. Implement the plan (parallel where possible)
"""

import concurrent.futures
import time
from memory import SharedMemory, MemoryEntry
from providers import get_provider
from escalation import Escalation
from display import Display

# Prompt templates
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

IMPLEMENT_PROMPT = """Implement this specific task as part of a larger plan.

OVERALL GOAL: {prompt}
FULL PLAN: {plan}

YOUR TASK: {task}

Make the actual code changes. Create/edit files as needed.
Be thorough but focused only on your assigned task."""


def execute_pride(prompt, previous, step, memory, config, cwd, cost_manager):
    """Execute a pride deliberation."""

    # Determine agents
    agents = _resolve_agents(step, config)
    n_agents = len(agents)

    Display.pride_start(n_agents, [a.name for a in agents])

    # PHASE 1: PROPOSE (parallel)
    Display.phase("propose", "Each agent proposes independently...")
    proposals = _parallel_propose(agents, prompt, cwd, memory)

    # PHASE 2: CRITIQUE (parallel)
    Display.phase("critique", "Agents review each other's proposals...")
    critiques = _parallel_critique(agents, prompt, proposals, cwd, memory)

    # Check for consensus
    max_rounds = config.get("general", {}).get("max_deliberation_rounds", 2)
    # For MVP, we do 1 round of propose + critique, then converge

    # PHASE 3: CONVERGE (single agent - use the strongest/first)
    Display.phase("converge", "Synthesizing into final plan...")
    plan = _converge(agents[0], prompt, memory, cwd)

    # PHASE 4: IMPLEMENT
    Display.phase("implement", "Building the solution...")
    implementation = _implement(agents[0], prompt, plan, cwd, memory)

    return {
        "success": True,
        "plan": plan,
        "code": implementation.get("code", ""),
        "decisions": _extract_decisions(memory),
        "files_changed": implementation.get("files_changed", []),
        "tokens_used": sum(p.get("tokens", 0) for p in proposals),
        "deliberation_summary": memory.format_for_prompt(memory.read_all()),
    }


def _resolve_agents(step, config):
    """Determine which providers to use for the pride."""
    if step.args:
        # Explicit providers: pride(claude, gemini, codex)
        if isinstance(step.args[0], str) and not step.args[0].isdigit():
            return [get_provider(name, config) for name in step.args]
        # Number of agents: pride(3)
        elif isinstance(step.args[0], int) or step.args[0].isdigit():
            n = int(step.args[0])
            profile_name = config.get("general", {}).get("default_profile", "balanced")
            profile = config.get("profiles", {}).get(profile_name, {})
            propose_providers = profile.get("propose", ["claude"] * n)
            return [get_provider(name, config) for name in propose_providers[:n]]
    # Default: 3 agents from default profile
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
                cwd=cwd
            )
            futures[executor.submit(agent.ask, agent_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            result = future.result()
            proposals.append({
                "agent": f"agent_{i+1}",
                "content": result.content,
                "model": result.model,
                "tokens": result.tokens_used
            })

            # Write to shared memory
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="propose",
                agent=f"agent_{i+1}",
                type="proposal",
                content=result.content,
                metadata={"model": result.model}
            ))

            Display.agent_proposal(i + 1, result.model, result.content[:150])

    return proposals


def _parallel_critique(agents, prompt, proposals, cwd, memory):
    """Run critique phase in parallel."""
    critiques = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {}
        for i, agent in enumerate(agents):
            own_proposal = proposals[i]["content"]
            other_proposals = "\n\n".join(
                f"Agent {j+1} ({p['model']}): {p['content']}"
                for j, p in enumerate(proposals) if j != i
            )

            critique_prompt = CRITIQUE_PROMPT.format(
                agent_num=i + 1,
                prompt=prompt,
                own_proposal=own_proposal,
                other_proposals=other_proposals
            )
            futures[executor.submit(agent.ask, critique_prompt, "", cwd)] = i

        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            result = future.result()
            critiques.append({
                "agent": f"agent_{i+1}",
                "content": result.content,
                "model": result.model,
            })

            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="critique",
                agent=f"agent_{i+1}",
                type="critique",
                content=result.content,
                metadata={"model": result.model}
            ))

            Display.agent_critique(i + 1, result.content[:150])

    return critiques


def _converge(lead_agent, prompt, memory, cwd):
    """Synthesize all proposals and critiques into a plan."""
    all_entries = memory.read_all()
    deliberation_text = memory.format_for_prompt(all_entries)

    converge_prompt = CONVERGE_PROMPT.format(
        prompt=prompt,
        deliberation=deliberation_text
    )

    result = lead_agent.ask(converge_prompt, "", cwd)

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="converge",
        agent="synthesizer",
        type="decision",
        content=result.content,
        metadata={"model": result.model}
    ))

    Display.convergence(result.content[:300])
    return result.content


def _implement(lead_agent, prompt, plan, cwd, memory):
    """Implement the converged plan."""
    impl_prompt = IMPLEMENT_PROMPT.format(
        prompt=prompt,
        plan=plan,
        task="Implement the full plan as described above."
    )

    result = lead_agent.implement(impl_prompt, cwd)

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="implement",
        agent="implementer",
        type="code",
        content=result.content,
        metadata={"model": result.model}
    ))

    return {
        "code": result.content,
        "files_changed": [],  # TODO: parse from claude output
        "tokens": result.tokens_used,
    }


def _extract_decisions(memory):
    """Extract key decisions from the deliberation."""
    decisions = memory.get_decisions()
    return [d.content for d in decisions]
```

### 14.5 Display Module (display.py)

```python
"""Terminal output formatting for Lion."""

import sys

# ANSI colors
LION = "\033[33m🦁\033[0m"  # Yellow lion
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

class Display:

    @staticmethod
    def pipeline_start(prompt, steps):
        print(f"\n{LION} Lion starting...")
        print(f"   {BOLD}Prompt:{RESET} {prompt}")
        if steps:
            pipeline_str = " -> ".join(
                f"{s.function}({', '.join(str(a) for a in s.args)})"
                for s in steps
            )
            print(f"   {BOLD}Pipeline:{RESET} {pipeline_str}")
        print()

    @staticmethod
    def auto_pipeline(complexity, pipeline):
        print(f"   {DIM}Complexity: {complexity} → auto pipeline: {pipeline}{RESET}")

    @staticmethod
    def pride_start(n, models):
        model_str = ", ".join(models)
        print(f"   {BLUE}▶ Starting pride of {n} ({model_str}){RESET}")

    @staticmethod
    def phase(name, description):
        icons = {
            "propose": "💭",
            "critique": "🔍",
            "converge": "🎯",
            "implement": "🔨",
        }
        icon = icons.get(name, "▶")
        print(f"\n   {icon} {BOLD}{name.upper()}{RESET}: {description}")

    @staticmethod
    def agent_proposal(num, model, preview):
        print(f"   ┌─ Agent {num} ({model}): {DIM}{preview}...{RESET}")

    @staticmethod
    def agent_critique(num, preview):
        print(f"   ├─ Agent {num} critique: {DIM}{preview}...{RESET}")

    @staticmethod
    def convergence(preview):
        print(f"   └─ {GREEN}Consensus:{RESET} {DIM}{preview}...{RESET}")

    @staticmethod
    def step_start(num, total, step):
        args_str = ", ".join(str(a) for a in step.args) if step.args else ""
        print(f"\n   [{num}/{total}] {BOLD}{step.function}({args_str}){RESET}")

    @staticmethod
    def step_complete(func_name, result):
        print(f"   {GREEN}✓{RESET} {func_name} complete")

    @staticmethod
    def step_error(func_name, error):
        print(f"   {RED}✗{RESET} {func_name} failed: {error}")

    @staticmethod
    def final_result(result):
        print(f"\n{'─' * 50}")
        if result.success:
            print(f"{LION} {GREEN}Done!{RESET}")
        else:
            print(f"{LION} {YELLOW}Completed with errors{RESET}")

        print(f"   Steps: {result.steps_completed}/{result.total_steps}")
        print(f"   Duration: {result.total_duration:.1f}s")
        if result.files_changed:
            print(f"   Files changed: {', '.join(result.files_changed)}")
        if result.errors:
            print(f"   {RED}Errors:{RESET}")
            for e in result.errors:
                print(f"     - {e}")
        print()

    @staticmethod
    def cancelled():
        print(f"\n{LION} Cancelled by user.")

    @staticmethod
    def error(message):
        print(f"\n{LION} {RED}Error:{RESET} {message}")
```

---

## 15. Custom Functions & Extensibility

### Adding a Custom Pipeline Function

Users can create custom functions in two ways:

#### Quick (from CLI):
```bash
lion function gdpr "Review for GDPR compliance: check data storage locations, consent mechanisms, right to deletion implementation, data processing agreements, and cookie handling."
```

This creates `~/.lion/custom_functions/gdpr.json`:
```json
{
    "name": "gdpr",
    "description": "Review for GDPR compliance...",
    "prompt_template": "Review the following code for GDPR compliance:\n\nCheck:\n1. Data storage locations and cross-border transfers\n2. Consent mechanisms\n3. Right to deletion implementation\n4. Data processing agreements\n5. Cookie handling and consent\n\nCODE:\n{code}\n\nDECISIONS:\n{decisions}\n\nFor each finding, specify:\n- Compliance status (COMPLIANT / NON-COMPLIANT / NEEDS REVIEW)\n- Specific regulation reference\n- Required action\n",
    "provider": "default",
    "created": "2026-02-20T15:32:00Z"
}
```

#### Advanced (Python file):
Create `~/.lion/functions/my_function.py`:

```python
def execute_my_function(prompt, previous, step, memory, config, cwd, cost_manager):
    """Custom pipeline function."""
    # Your logic here
    provider = get_provider("claude", config)
    result = provider.ask("Your custom prompt...", cwd=cwd)
    return {
        "success": True,
        "content": result.content,
        "tokens_used": result.tokens_used,
    }
```

### Saving Patterns

```bash
lion pattern ship = -> pride(3) -> review() -> test() -> pr()
lion pattern bulletproof = -> pride(3) -> devil() -> future(6m) -> review() -> test() -> audit()
lion pattern quick = -> review() -> test()
lion pattern explore = -> pride(5) -> devil()
```

Stored in `~/.lion/patterns/user_patterns.json`:
```json
{
    "ship": "pride(3) -> review() -> test() -> pr()",
    "bulletproof": "pride(3) -> devil() -> future(6m) -> review() -> test() -> audit()",
    "quick": "review() -> test()",
    "explore": "pride(5) -> devil()"
}
```

---

## 16. Lion Self-Build Bootstrap

### The Goal

Once Lion's core (Phase 1-2) is implemented, ALL further development should happen through Lion itself. This is both a practical goal and a proof of concept.

### Bootstrap Sequence

```bash
# Phase 1-2: Build core manually (or with regular Claude Code)
# This is the only manual coding needed

# Phase 3: Use Lion core to build unique functions
lion "Implement the devil() pipeline function for Lion. It should challenge architectural decisions and assumptions. Read the specification in LION.md for the prompt template and integration pattern." -> pride(3) -> review() -> test()

lion "Implement the future() pipeline function for Lion. It reviews code from a future developer's perspective. Read LION.md for details." -> pride(3) -> review() -> test()

# Phase 4: Use Lion to add multi-LLM support
lion "Add Gemini CLI provider to Lion. Follow the Provider interface in providers/base.py. Test with gemini -p." -> pride(claude, claude, claude) -> review() -> test()

# Phase 5: Use Lion to add patterns
lion "Implement the pattern save/load system for Lion. Users should be able to define patterns with 'lion pattern name = pipeline' and use them with 'lion prompt -> name()'" -> pride(3) -> devil() -> review() -> test()

# Phase 6: Lion improves itself
lion "The pride() function currently runs all proposals sequentially. Refactor to use true parallel execution with concurrent.futures." -> pride(3) -> devil() -> review() -> test()

lion "Add a --verbose flag to Lion that shows the full deliberation in real-time instead of summaries." -> pride(2) -> review()

lion "Add cost tracking to Lion. After each run, show how many Claude vs Gemini vs Ollama prompts were used and estimated cost." -> pride(3) -> review() -> test()
```

### The Meta Test

The ultimate validation of Lion is this:

```bash
lion "Review the entire Lion codebase. Find architectural issues, missing error handling, and opportunities for improvement. Be thorough." -> pride(3) -> devil() -> future(6m) -> audit()
```

If Lion can meaningfully review and improve itself, the concept is proven.

---

## Appendix A: Quick Reference Card

```
🦁 LION - Quick Reference

BASIC USAGE:
  lion "prompt"                           Auto-detect complexity
  lion "prompt" -> pride(3)               Explicit pipeline
  lion "prompt" -> fn() -> fn() -> fn()   Chained pipeline

CORE FUNCTIONS:
  pride(n)              n agents deliberate (default: 3)
  pride(a, b, c)        Specific LLMs deliberate
  review()              Code review
  test()                Run tests, auto-fix failures
  pr("branch")          Create git branch + PR

UNIQUE FUNCTIONS:
  devil()               Challenge assumptions & decisions
  future(Nm)            Review from N months in the future
  onboard()             Generate onboarding documentation
  audit()               Security audit (OWASP top 10)
  explain()             Document architectural decisions
  cost()                Infrastructure cost checklist (not estimates!)
  migrate()             Migration assessment questionnaire

PATTERNS:
  lion pattern ship = -> pride(3) -> review() -> test() -> pr()
  lion "prompt" -> ship()

CUSTOM FUNCTIONS:
  lion function gdpr "Review for GDPR compliance..."
  lion "prompt" -> gdpr()

PROFILES:
  lion "prompt" --profile cheap           Minimize Claude usage
  lion "prompt" --profile balanced        Mix quality & cost
  lion "prompt" --profile premium         All Claude

CONFIG: ~/.lion/config.toml
RUNS:   ~/.lion/runs/
```

---

## Appendix B: Why "Lion"?

- A **pride** of lions is the only social cat group - they hunt together
- The **lion** is the king - one goal, the pride executes
- Lions use **coordinated strategy** - not brute force
- "LION" = **L**anguage for **I**ntelligent **O**rchestration **N**etworks

---

*This document is the complete specification for Lion v1.0. Once the core is built, this document should be included in the project as `LION.md` and used by Lion itself as context for self-improvement.*

*Built by Menno Sijben, 2026.*
