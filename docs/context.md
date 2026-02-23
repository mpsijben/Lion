# Lion -- Layer 2: Context Ecosystem

## Complete Specification for Cross-Agent Context Sharing

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Design Philosophy: Token Budget](#2-design-philosophy-token-budget)
3. [Context Package Format](#3-context-package-format)
4. [Context Modes (User Controls)](#4-context-modes-user-controls)
5. [Implementation: Structured Prompts](#5-implementation-structured-prompts)
6. [Context Functions](#6-context-functions)
7. [Context Flow Through Pipeline](#7-context-flow-through-pipeline)
8. [Cross-LLM Context Adaptation](#8-cross-llm-context-adaptation)
9. [Belief States](#9-belief-states)
10. [Confidence Weighting](#10-confidence-weighting)
11. [Context Archaeology (Run History)](#11-context-archaeology-run-history)
12. [Token Budget Analysis](#12-token-budget-analysis)
13. [Implementation Guide](#13-implementation-guide)
14. [File Structure](#14-file-structure)

---

## 1. The Problem

### What happens today (in Lion and everywhere else)

```
pride(3):
  Agent 1 → "I propose using JWT tokens with 24h expiry..."
  Agent 2 → "I propose session-based auth with Redis..."
  Agent 3 → "I propose OAuth2 with refresh tokens..."

  Critique phase:
  Agent 1 gets: the TEXT of Agent 2 and 3's proposals
```

What Agent 1 does NOT get:
- **Why** Agent 2 chose sessions over JWT (reasoning)
- That Agent 2 **considered** JWT but rejected it because of revocation concerns (rejected alternatives)
- That Agent 3 is **uncertain** whether the app needs refresh tokens (uncertainties)
- That Agent 1's own proposal **assumes** low traffic and no microservices (hidden assumptions)

This is like a code review where you only see the final PR but not the commit history, not the Slack discussion that led to the approach, not the alternatives that were tried and abandoned.

### What we want

Every agent produces structured metadata alongside their output. Downstream agents (and pipeline functions like `devil()` and `review()`) receive not just WHAT was decided, but WHY, WHAT ELSE was considered, and WHERE the weak points are.

### The constraint

Context is expensive. Every extra token in context means:
- Higher cost (for API-based providers)
- Slower responses
- Risk of hitting context window limits
- Information dilution (too much context = agent ignores the important parts)

**The entire design of Layer 2 is built around this tension: maximum insight, minimum tokens.**

---

## 2. Design Philosophy: Token Budget

### Core Principle: Context Should Be Opt-In and Graduated

Not every task needs rich context. A simple `lion '"Fix typo in README"'` should not waste tokens on belief states and confidence scores. But `lion '"Redesign the entire auth system" -> pride(3) -> devil() -> future(6m)'` benefits enormously from rich context.

### Three Context Modes

| Mode | Extra tokens per agent | When to use | Default for |
|------|----------------------|-------------|-------------|
| **minimal** | ~0 extra | Simple tasks, single agent | No pipeline or simple pipeline |
| **standard** | ~200-400 extra | Multi-agent deliberation | `pride()` with 2-3 agents |
| **rich** | ~600-1000 extra | Complex architecture decisions | `pride()` + `devil()`/`future()` |

### Token Budget Breakdown

```
Standard pride(3) WITHOUT context (current):
  Propose:  3 × ~800 tokens output  = ~2400 tokens generated
  Critique: 3 × ~600 tokens input   = ~1800 tokens context added
  Total context overhead: ~1800 tokens

Standard pride(3) WITH standard context:
  Propose:  3 × ~1000 tokens output = ~3000 tokens generated (+25%)
  Critique: 3 × ~900 tokens input   = ~2700 tokens context added (+50%)
  Total context overhead: ~2700 tokens

  Extra cost: ~900 tokens = roughly 1 extra prompt worth
  Value gained: dramatically better critique quality
```

**The rule: Layer 2 should never more than double the context overhead of a pipeline step.** If it does, something is wrong and we should compress.

### Auto-Scaling

Lion automatically selects the context mode based on pipeline complexity:

```python
def select_context_mode(pipeline_steps, config):
    """Select context mode based on pipeline complexity."""
    
    # User override always wins
    if config.get("context_mode"):
        return config["context_mode"]
    
    # Count "deep thinking" functions
    deep_functions = {"devil", "future", "audit", "explain"}
    has_deep = any(s.function in deep_functions for s in pipeline_steps)
    
    pride_steps = [s for s in pipeline_steps if s.function == "pride"]
    max_agents = max((s.args[0] if s.args else 3 for s in pride_steps), default=0)
    
    if has_deep or max_agents >= 4:
        return "rich"
    elif pride_steps:
        return "standard"
    else:
        return "minimal"
```

---

## 3. Context Package Format

### The ContextPackage Dataclass

```python
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

class ContextMode(Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    RICH = "rich"

@dataclass
class ContextPackage:
    """Structured context produced by every agent alongside their output."""
    
    # Always present (minimal mode)
    output: str                          # The actual response/proposal/code
    agent_id: str                        # Which agent produced this
    model: str                           # Which LLM (claude, gemini, etc.)
    
    # Standard mode additions (~200-400 extra tokens)
    reasoning: Optional[str] = None      # WHY this approach was chosen
    alternatives: list[str] = field(default_factory=list)
                                         # What was considered but rejected (with reason)
    uncertainties: list[str] = field(default_factory=list)
                                         # What the agent is unsure about
    confidence: Optional[float] = None   # 0.0-1.0 overall confidence
    
    # Rich mode additions (~400-600 extra tokens on top of standard)
    assumptions: list[str] = field(default_factory=list)
                                         # What the agent assumes to be true
    risks: list[str] = field(default_factory=list)
                                         # Identified risks
    dependencies: list[str] = field(default_factory=list)
                                         # External dependencies being relied on
    files_examined: list[str] = field(default_factory=list)
                                         # Which files were read
    questions_for_team: list[str] = field(default_factory=list)
                                         # Questions this agent has for others

    def to_shared_memory(self) -> dict:
        """Serialize for JSONL storage."""
        data = {
            "output": self.output,
            "agent_id": self.agent_id,
            "model": self.model,
        }
        if self.reasoning:
            data["reasoning"] = self.reasoning
        if self.alternatives:
            data["alternatives"] = self.alternatives
        if self.uncertainties:
            data["uncertainties"] = self.uncertainties
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.assumptions:
            data["assumptions"] = self.assumptions
        if self.risks:
            data["risks"] = self.risks
        if self.dependencies:
            data["dependencies"] = self.dependencies
        if self.files_examined:
            data["files_examined"] = self.files_examined
        if self.questions_for_team:
            data["questions_for_team"] = self.questions_for_team
        return data

    def token_estimate(self) -> int:
        """Rough token estimate for this package's metadata (excluding output)."""
        tokens = 0
        if self.reasoning:
            tokens += len(self.reasoning.split()) * 1.3
        tokens += sum(len(a.split()) * 1.3 for a in self.alternatives)
        tokens += sum(len(u.split()) * 1.3 for u in self.uncertainties)
        tokens += sum(len(a.split()) * 1.3 for a in self.assumptions)
        tokens += sum(len(r.split()) * 1.3 for r in self.risks)
        tokens += sum(len(q.split()) * 1.3 for q in self.questions_for_team)
        return int(tokens)
```

### Minimal vs Standard vs Rich -- What Gets Collected

```
MINIMAL MODE:
  Agent output: "I propose JWT tokens with 24h expiry and..."
  (No extra context collected. Same as current Lion behavior.)

STANDARD MODE:
  Agent output: "I propose JWT tokens with 24h expiry and..."
  Reasoning: "JWT chosen for statelessness, fits our API-first design"
  Alternatives: [
    "Sessions + Redis: rejected because adds infrastructure complexity",
    "OAuth2 opaque tokens: rejected because overkill for our scale"
  ]
  Uncertainties: [
    "Not sure if 24h expiry is too long for payment-related endpoints",
    "Unclear if we need token rotation for mobile clients"  
  ]
  Confidence: 0.7

RICH MODE (adds to standard):
  Assumptions: [
    "Traffic stays under 10k requests/day",
    "No microservice decomposition planned",
    "Single database, no need for distributed sessions"
  ]
  Risks: [
    "JWT cannot be revoked after issuance without blacklist",
    "Token size grows with claims, impacts header size"
  ]
  Dependencies: ["jsonwebtoken npm package", "RS256 key pair management"]
  Files examined: ["auth/middleware.ts", "config/security.ts", "package.json"]
  Questions for team: [
    "Should we support multiple auth methods simultaneously?",
    "Is there a requirement for SSO integration later?"
  ]
```

---

## 4. Context Modes (User Controls)

### Automatic (default)

Lion picks the mode based on pipeline complexity (see section 2).

### Manual Override

```bash
# Force minimal (save tokens)
lion '"Build feature" -> pride(3) -> review()' --context minimal

# Force rich (maximum insight)
lion '"Build feature" -> pride(3) -> devil()' --context rich

# In config.toml
[context]
default_mode = "auto"  # auto | minimal | standard | rich
```

### Per-Function Override

```bash
# Rich context only for pride, minimal for review
lion '"Build feature" -> pride(3, context: rich) -> review(context: minimal)'
```

### Token Budget Cap

```toml
# In config.toml
[context]
max_context_tokens_per_step = 3000  # Hard cap on context metadata per pipeline step
max_total_context_tokens = 10000    # Hard cap for entire pipeline run
```

If the budget is exceeded, Lion automatically compresses context (see distill function in section 6).

---

## 5. Implementation: Structured Prompts

### How Context Gets Collected

The key insight: we don't need a separate "context extraction" step. We modify the agent prompts to ask for structured output. The agent produces context metadata as PART of its response, which Lion then parses.

### Standard Mode Propose Prompt

```
PROPOSE_PROMPT_STANDARD = """You are Agent {agent_num} of {total_agents} working on:

TASK: {prompt}

WORKING DIRECTORY: {cwd}

Propose your approach. Structure your response EXACTLY as follows:

## Approach
[Your proposed approach -- be specific about architecture, files, implementation]

## Reasoning
[1-3 sentences: WHY you chose this over alternatives]

## Alternatives Considered
- [Alternative 1]: [why rejected, max 1 sentence]
- [Alternative 2]: [why rejected, max 1 sentence]

## Uncertainties  
- [Thing you're genuinely unsure about]
- [Another uncertainty, if any]

## Confidence
[Single number 0.0-1.0]
"""
```

**Token overhead: ~50 tokens in the prompt + ~200-400 tokens in the structured response. Total: ~250-450 extra tokens per agent.**

### Rich Mode Propose Prompt

```
PROPOSE_PROMPT_RICH = """You are Agent {agent_num} of {total_agents} working on:

TASK: {prompt}

WORKING DIRECTORY: {cwd}

Propose your approach. Structure your response EXACTLY as follows:

## Approach
[Your proposed approach -- be specific about architecture, files, implementation]

## Reasoning
[1-3 sentences: WHY you chose this over alternatives]

## Alternatives Considered
- [Alternative 1]: [why rejected]
- [Alternative 2]: [why rejected]

## Uncertainties  
- [Thing you're genuinely unsure about]

## Assumptions
- [What you're assuming is true about the project/requirements]

## Risks
- [What could go wrong with this approach]

## Questions
- [Questions you'd want answered before committing to this approach]

## Confidence
[Single number 0.0-1.0]
"""
```

**Token overhead: ~80 tokens in prompt + ~500-800 tokens in response. Total: ~580-880 extra tokens per agent.**

### Standard Mode Critique Prompt (the big payoff)

This is where context packages shine. Instead of "here are the other proposals," agents get the full reasoning:

```
CRITIQUE_PROMPT_STANDARD = """You are Agent {agent_num} reviewing other proposals.

TASK: {prompt}

YOUR PROPOSAL:
{own_proposal_output}
Your reasoning: {own_reasoning}
Your uncertainties: {own_uncertainties}

OTHER PROPOSALS:

{for each other agent:}
--- Agent {n} ({model}) [confidence: {confidence}] ---
Proposal: {output}
Reasoning: {reasoning}
Rejected alternatives: {alternatives}
Uncertainties: {uncertainties}
{end for}

INSTRUCTIONS:
For each other proposal:
1. Do you AGREE with their reasoning? If not, why?
2. Do their uncertainties concern you?  
3. Look at what they REJECTED -- should any rejected alternative be reconsidered?
4. What did they think of that YOU missed?

Keep your critique focused and concise.
"""
```

**This is the core innovation.** Agent 1 doesn't just see "Agent 2 proposes sessions." Agent 1 sees "Agent 2 proposes sessions, reasoning: revocation concerns with JWT, rejected JWT because tokens can't be invalidated, uncertain about: Redis cluster complexity, confidence: 0.8."

Now Agent 1 can respond: "Agent 2's reasoning about JWT revocation is valid. However, their rejected alternative (JWT + blacklist) actually solves this -- I'd recommend reconsidering with a Redis-based blacklist. Their uncertainty about Redis cluster complexity is valid but solvable with managed Redis."

**That's a fundamentally richer critique. The extra ~200 tokens of context metadata per agent produces dramatically better cross-agent understanding.**

### Parsing Structured Output

```python
import re

def parse_context_package(raw_output: str, agent_id: str, model: str,
                          mode: ContextMode) -> ContextPackage:
    """Parse structured agent output into a ContextPackage."""
    
    pkg = ContextPackage(
        output=raw_output,
        agent_id=agent_id,
        model=model,
    )
    
    if mode == ContextMode.MINIMAL:
        return pkg
    
    # Extract sections using ## headers
    sections = extract_sections(raw_output)
    
    # Standard fields
    pkg.output = sections.get("approach", raw_output)
    pkg.reasoning = sections.get("reasoning", None)
    pkg.alternatives = parse_list(sections.get("alternatives considered", ""))
    pkg.uncertainties = parse_list(sections.get("uncertainties", ""))
    pkg.confidence = parse_confidence(sections.get("confidence", "0.5"))
    
    # Rich fields
    if mode == ContextMode.RICH:
        pkg.assumptions = parse_list(sections.get("assumptions", ""))
        pkg.risks = parse_list(sections.get("risks", ""))
        pkg.questions_for_team = parse_list(sections.get("questions", ""))
    
    return pkg


def extract_sections(text: str) -> dict:
    """Extract content under ## headers."""
    sections = {}
    current_header = None
    current_content = []
    
    for line in text.split('\n'):
        if line.startswith('## '):
            if current_header:
                sections[current_header] = '\n'.join(current_content).strip()
            current_header = line[3:].strip().lower()
            current_content = []
        else:
            current_content.append(line)
    
    if current_header:
        sections[current_header] = '\n'.join(current_content).strip()
    
    return sections


def parse_list(text: str) -> list[str]:
    """Parse markdown list items."""
    items = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('- '):
            items.append(line[2:].strip())
    return items


def parse_confidence(text: str) -> float:
    """Extract a confidence score."""
    try:
        numbers = re.findall(r'([01]\.?\d*)', text)
        if numbers:
            return min(1.0, max(0.0, float(numbers[0])))
    except (ValueError, IndexError):
        pass
    return 0.5  # Default
```

---

## 6. Context Functions

### context() -- Build Shared Mental Model

Runs BEFORE the pride. Creates a shared understanding of the codebase that all agents receive. This prevents agents from wasting their proposal tokens on rediscovering what the codebase looks like.

```bash
lion '"Build payment system" -> context() -> pride(3) -> review()'
```

**Why this saves tokens overall:** Without `context()`, each of the 3 agents in the pride independently examines the codebase and wastes ~500 tokens describing what they found. With `context()`, one agent does it once (~800 tokens), and the others don't repeat it. Net saving: ~700 tokens.

```python
CONTEXT_PROMPT = """Analyze the codebase for an upcoming task.

TASK: {prompt}
WORKING DIRECTORY: {cwd}

Create a concise context document (max 800 tokens) covering:

1. PROJECT STRUCTURE: Key directories and their purposes (3-5 lines)
2. TECH STACK: Languages, frameworks, databases in use (1-2 lines)
3. PATTERNS: Design patterns and conventions this project follows (2-3 lines)
4. RELEVANT FILES: Files most likely impacted by this task (list paths)
5. EXISTING DECISIONS: Architectural decisions already made that constrain this task (2-3 lines)
6. BOUNDARIES: What should NOT be changed (1-2 lines)

Be extremely concise. This will be shared with multiple agents.
"""
```

**Implementation:**

```python
def execute_context(prompt, previous, step, memory, config, cwd, cost_manager):
    """Build shared mental model for the pride."""
    
    # Use the cheapest available provider for context gathering
    provider_name = step.kwargs.get("provider", 
                    config.get("context", {}).get("provider", "default"))
    provider = get_provider(provider_name, config)
    
    result = provider.ask(
        CONTEXT_PROMPT.format(prompt=prompt, cwd=cwd),
        cwd=cwd
    )
    
    # Store as shared context
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="context",
        agent="context_builder",
        type="shared_context",
        content=result.content,
        metadata={"model": result.model, "tokens": result.tokens_used}
    ))
    
    return {
        "success": True,
        "shared_context": result.content,
        "tokens_used": result.tokens_used,
        "content": result.content,
    }
```

**Token cost:** ~800 tokens one-time. Saves ~500 tokens per pride agent because they don't need to rediscover codebase structure. Net: saves tokens with pride(3)+, costs tokens with pride(2)-.

**Recommendation:** Use `context()` when pride has 3+ agents or when the codebase is unfamiliar.

### distill() -- Context Compression

Compresses the accumulated context from previous pipeline steps. Critical for long pipelines where context would otherwise balloon.

```bash
lion '"Build X" -> pride(5) -> distill() -> devil() -> review()'
```

Without `distill()`, the devil gets ALL 5 proposals + ALL 5 critiques + the convergence plan = potentially 15,000+ tokens of context. With `distill()`, the devil gets a compressed summary = ~2,000 tokens.

```python
DISTILL_PROMPT = """Compress the following deliberation into its essential elements.

FULL DELIBERATION ({token_count} tokens):
{deliberation}

Create a compressed summary (target: under {target_tokens} tokens) that preserves:
1. DECISION: What was decided and the core reasoning (2-3 sentences)
2. KEY DISAGREEMENTS: Points where agents disagreed, unresolved (bullet list)
3. CRITICAL UNCERTAINTIES: Things the team is unsure about (bullet list)
4. NOTABLE REJECTED ALTERNATIVES: Alternatives worth remembering (bullet list)  
5. ASSUMPTIONS IN PLAY: What's being assumed true (bullet list)
6. CONFIDENCE MAP: Which decisions are strong vs weak

RULES:
- Lose ALL redundancy, pleasantries, and repetition
- Keep ALL unique insights, disagreements, and warnings
- If two agents said the same thing, mention it once
- Preserve the STRONGEST version of each argument
"""
```

**Implementation:**

```python
def execute_distill(prompt, previous, step, memory, config, cwd, cost_manager):
    """Compress accumulated context."""
    
    # Calculate current context size
    all_entries = memory.read_all()
    full_text = memory.format_for_prompt(all_entries)
    current_tokens = estimate_tokens(full_text)
    
    # Target: compress to 25% of original, minimum 500, maximum 3000
    target_tokens = max(500, min(3000, current_tokens // 4))
    
    # Use cheapest provider for compression
    provider_name = step.kwargs.get("provider",
                    config.get("context", {}).get("distill_provider", "gemini"))
    provider = get_provider(provider_name, config)
    
    result = provider.ask(
        DISTILL_PROMPT.format(
            deliberation=full_text,
            token_count=current_tokens,
            target_tokens=target_tokens
        ),
        cwd=cwd
    )
    
    # Store compressed context (replaces verbose context for downstream)
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="distill",
        agent="distiller",
        type="compressed_context",
        content=result.content,
        metadata={
            "original_tokens": current_tokens,
            "compressed_tokens": estimate_tokens(result.content),
            "compression_ratio": estimate_tokens(result.content) / current_tokens,
        }
    ))
    
    return {
        "success": True,
        "compressed_context": result.content,
        "original_tokens": current_tokens,
        "compressed_tokens": estimate_tokens(result.content),
        "tokens_used": result.tokens_used,
        "content": result.content,
    }
```

**Token analysis:**

```
pride(5) produces:      ~15,000 tokens of context
distill() costs:        ~800 tokens (compression prompt + response)
distill() produces:     ~2,000 tokens of compressed context
devil() receives:       ~2,000 tokens instead of ~15,000

Net saving: ~12,200 tokens for downstream steps
Cost: ~800 tokens for the distillation
ROI: massive -- especially when multiple functions follow
```

**Recommendation:** Always use `distill()` between pride(4+) and downstream functions. Optional for pride(2-3). Lion can auto-insert it when context exceeds a threshold.

### Auto-Distill (Smart Compression)

Lion can automatically compress when context exceeds a budget:

```python
class ContextBudgetManager:
    """Automatically manages context size across pipeline steps."""
    
    def __init__(self, config):
        self.max_per_step = config.get("context", {}).get(
            "max_context_tokens_per_step", 4000
        )
        self.max_total = config.get("context", {}).get(
            "max_total_context_tokens", 15000
        )
        self.total_used = 0
    
    def should_distill(self, current_context_tokens: int) -> bool:
        """Check if we need to compress before the next step."""
        return current_context_tokens > self.max_per_step
    
    def prepare_context_for_step(self, memory, step, config, cwd):
        """Get context for next step, auto-compressing if needed."""
        
        # Check if distilled context exists
        distilled = memory.read_phase("distill")
        if distilled:
            # Use most recent distillation
            return distilled[-1].content
        
        # Calculate raw context size
        relevant = self._get_relevant_entries(memory, step)
        context_text = memory.format_for_prompt(relevant)
        context_tokens = estimate_tokens(context_text)
        
        if self.should_distill(context_tokens):
            # Auto-compress
            compressed = self._auto_distill(context_text, context_tokens, config, cwd)
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="distill",
                agent="auto_distiller",
                type="compressed_context",
                content=compressed,
                metadata={"auto": True, "trigger": "budget_exceeded"}
            ))
            return compressed
        
        return context_text
    
    def _get_relevant_entries(self, memory, step):
        """Get only the memory entries relevant to this step."""
        all_entries = memory.read_all()
        
        # For devil/future: they need decisions + uncertainties
        if step.function in ("devil", "future"):
            return [e for e in all_entries 
                    if e.type in ("decision", "proposal", "compressed_context")]
        
        # For review: needs code + decisions
        if step.function == "review":
            return [e for e in all_entries 
                    if e.type in ("code", "decision", "compressed_context")]
        
        # Default: everything
        return all_entries
```

---

## 7. Context Flow Through Pipeline

### Visualization: How Context Moves

```
lion "Build payment system" -> context() -> pride(3) -> distill() -> devil() -> review()

Step 1: context()
  Input:  codebase scan
  Output: shared_context (800 tokens)
  
  ┌─────────────────────────────────┐
  │ SHARED CONTEXT                  │
  │ Stack: Node + Express + Postgres│
  │ Pattern: Repository pattern     │
  │ Relevant: routes/payments.ts,   │
  │   models/order.ts, lib/stripe.ts│
  │ Constraint: Must use existing   │
  │   Stripe integration            │
  └───────────────┬─────────────────┘
                  │ Injected into ALL pride agents
                  ▼
Step 2: pride(3, context: standard)
  
  Agent 1 (claude) receives: task + shared_context
  Agent 2 (gemini) receives: task + shared_context  
  Agent 3 (claude) receives: task + shared_context
  
  Each produces: ContextPackage with output + reasoning + 
                 alternatives + uncertainties + confidence
  
  Critique phase: each agent sees other agents' FULL packages
  
  Converge: synthesizer sees ALL packages + ALL critiques
  
  Output: plan + code + accumulated context (~8000 tokens)
  
                  │ 
                  ▼
Step 3: distill()
  
  Input:  ~8000 tokens of deliberation
  Output: ~2000 tokens compressed
  
  ┌─────────────────────────────────┐
  │ COMPRESSED CONTEXT              │
  │ Decision: Stripe Checkout +     │
  │   webhooks, repository pattern  │
  │ Disagreements: Agent 2 wanted   │
  │   PaymentIntent API instead     │
  │ Uncertainties: webhook retry    │
  │   strategy, idempotency keys    │
  │ Rejected: direct charge API     │
  │   (no SCA support)              │
  │ Assumptions: <1000 tx/day,      │
  │   single currency (EUR)         │
  │ Weak decisions: webhook error   │
  │   handling (confidence: 0.5)    │
  └───────────────┬─────────────────┘
                  │ 
                  ▼
Step 4: devil()
  
  Receives: compressed context (2000 tokens) + code
  
  The devil NOW KNOWS:
  - Where the team disagreed (attack those points)
  - Where confidence is low (challenge those decisions)
  - What was rejected (were those rejections correct?)
  - What's assumed (are those assumptions valid?)
  
  A devil WITHOUT context: "Have you considered error handling?"
  A devil WITH context: "Your webhook retry strategy has 0.5 
    confidence and Agent 2 already warned about this. Also, 
    your assumption of single currency won't survive the 
    first international customer. Here's what to do instead..."
  
                  │
                  ▼
Step 5: review()
  
  Receives: code + compressed context + devil's findings
  
  The reviewer NOW KNOWS:
  - Why the code is structured this way (reasoning)
  - What alternatives existed (don't suggest already-rejected approaches)
  - Where the known weak points are (focus review there)
  - What the devil flagged (verify those issues)
  
  A reviewer WITHOUT context: reviews everything equally
  A reviewer WITH context: focuses on webhook error handling
    (flagged by both Agent 2 and devil) and currency assumption
```

### Context Inheritance Rules

Not every function needs ALL accumulated context. The rules:

```python
CONTEXT_INHERITANCE = {
    # function: which context it receives
    
    "pride": {
        "receives": ["shared_context"],
        "generates": ["proposals", "critiques", "decisions", "code"],
    },
    
    "review": {
        "receives": ["code", "decisions", "compressed_context"],
        "ignores": ["raw_proposals", "raw_critiques"],
        # Reviewer doesn't need the full deliberation, just decisions + code
    },
    
    "devil": {
        "receives": ["decisions", "compressed_context", "code"],
        "focus_on": ["uncertainties", "weak_decisions", "assumptions"],
        # Devil specifically targets weak points
    },
    
    "future": {
        "receives": ["decisions", "code", "assumptions"],
        "ignores": ["deliberation_process"],
        # Future reviewer needs the result, not how we got there
    },
    
    "test": {
        "receives": ["code"],
        "ignores": ["all_context"],
        # Tests don't need context, just code
    },
    
    "audit": {
        "receives": ["code", "dependencies"],
        "ignores": ["deliberation_process"],
        # Auditor needs code + what external things it uses
    },
    
    "onboard": {
        "receives": ["code", "decisions", "compressed_context", "alternatives"],
        # Onboarding docs need the full picture: what, why, and what was rejected
    },
}
```

---

## 8. Cross-LLM Context Adaptation

### The Problem

Different LLMs respond to different context formats. Claude handles structured XML-like input well. Gemini works better with narrative text. Ollama (smaller models) can be overwhelmed by too much structure.

### The Solution: ContextAdapter

```python
class ContextAdapter:
    """Formats context packages for optimal comprehension per LLM."""
    
    def format(self, packages: list[ContextPackage], 
               target_provider: str,
               mode: ContextMode) -> str:
        """Format context packages for a specific provider."""
        
        if target_provider == "claude":
            return self._format_structured(packages, mode)
        elif target_provider == "gemini":
            return self._format_narrative(packages, mode)
        elif target_provider == "ollama":
            return self._format_compact(packages, mode)
        else:
            return self._format_structured(packages, mode)  # Default
    
    def _format_structured(self, packages, mode):
        """Claude: structured with clear sections."""
        parts = []
        for pkg in packages:
            section = f"Agent {pkg.agent_id} ({pkg.model})"
            if pkg.confidence is not None:
                section += f" [confidence: {pkg.confidence}]"
            section += f":\n"
            section += f"Proposal: {pkg.output}\n"
            
            if mode != ContextMode.MINIMAL:
                if pkg.reasoning:
                    section += f"Reasoning: {pkg.reasoning}\n"
                if pkg.alternatives:
                    section += "Rejected alternatives:\n"
                    for alt in pkg.alternatives:
                        section += f"  - {alt}\n"
                if pkg.uncertainties:
                    section += "Uncertainties:\n"
                    for unc in pkg.uncertainties:
                        section += f"  - {unc}\n"
            
            if mode == ContextMode.RICH:
                if pkg.assumptions:
                    section += "Assumptions:\n"
                    for asm in pkg.assumptions:
                        section += f"  - {asm}\n"
                if pkg.risks:
                    section += "Risks:\n"
                    for risk in pkg.risks:
                        section += f"  - {risk}\n"
            
            parts.append(section)
        
        return "\n---\n".join(parts)
    
    def _format_narrative(self, packages, mode):
        """Gemini: flowing narrative text."""
        parts = []
        for pkg in packages:
            text = f"Agent {pkg.agent_id} (using {pkg.model}"
            if pkg.confidence is not None:
                text += f", {int(pkg.confidence * 100)}% confident"
            text += f") proposed: {pkg.output}"
            
            if mode != ContextMode.MINIMAL:
                if pkg.reasoning:
                    text += f" Their reasoning: {pkg.reasoning}"
                if pkg.alternatives:
                    alt_text = "; ".join(pkg.alternatives)
                    text += f" They also considered but rejected: {alt_text}."
                if pkg.uncertainties:
                    unc_text = "; ".join(pkg.uncertainties)
                    text += f" They are uncertain about: {unc_text}."
            
            if mode == ContextMode.RICH:
                if pkg.assumptions:
                    asm_text = "; ".join(pkg.assumptions)
                    text += f" Key assumptions: {asm_text}."
            
            parts.append(text)
        
        return "\n\n".join(parts)
    
    def _format_compact(self, packages, mode):
        """Ollama: minimal, direct, no fluff."""
        parts = []
        for pkg in packages:
            text = f"[{pkg.agent_id}/{pkg.model}]"
            if pkg.confidence:
                text += f" conf:{pkg.confidence}"
            text += f"\n{pkg.output}"
            
            if mode != ContextMode.MINIMAL and pkg.uncertainties:
                text += f"\nUNSURE: {'; '.join(pkg.uncertainties)}"
            
            parts.append(text)
        
        return "\n---\n".join(parts)
```

### Token Impact of Adaptation

```
Same 3 proposals formatted for different providers:

Claude (structured):  ~450 context tokens
Gemini (narrative):   ~500 context tokens (+11%)
Ollama (compact):     ~250 context tokens (-44%)

The compact format for Ollama is not just shorter -- it's also
better for small models that get confused by verbose context.
```

---

## 9. Belief States

### What Are Belief States?

In robotics and game AI, every agent maintains an explicit representation of what it knows and what it thinks other agents know. This prevents agents from making proposals based on information they don't have.

In Lion, belief states are OPTIONAL and only tracked in rich mode.

### Implementation

```python
@dataclass
class BeliefState:
    """What an agent knows, believes, and thinks others know."""
    
    # What I know for certain (files I've read, tests I've run)
    knows: list[str]
    
    # What I believe but haven't verified
    believes: list[str]
    
    # What I think other agents probably don't know
    others_likely_missing: list[str]
```

### How It's Collected

Added to the RICH mode prompt:

```
## What You Know
- [Files you actually examined and facts you verified]

## What You Believe But Didn't Verify  
- [Assumptions based on naming conventions, patterns, etc.]

## What Others Might Miss
- [Things you discovered that aren't obvious from the task description]
```

### How It's Used

In the critique phase, Agent 2 sees:

```
Agent 1 knows: examined auth/middleware.ts, verified JWT is used
Agent 1 believes: refresh tokens are not implemented (didn't verify)
Agent 1 thinks you might miss: there's a legacy session system in auth/legacy.ts
```

Now Agent 2 can say: "Agent 1 is correct that there's a legacy session system. I verified -- it's still active for 3 routes. We need a migration strategy, not a replacement."

**Token cost:** ~100-150 extra tokens per agent in rich mode. Only collected in rich mode.

### When Belief States Are Worth It

- pride(3+) with mixed LLMs: agents have different "views" of the codebase
- Complex codebase with legacy code: prevents agents from making proposals based on outdated assumptions
- Tasks that touch multiple systems: prevents blind spots

---

## 10. Confidence Weighting

### Per-Decision Confidence

Not just overall confidence, but per-decision confidence for the converge step:

```python
@dataclass
class WeightedDecision:
    decision: str
    confidence: float
    supporting_agents: list[str]     # Which agents agreed
    dissenting_agents: list[str]     # Which agents disagreed
    strongest_argument_for: str      # Best argument in favor
    strongest_argument_against: str  # Best argument against
```

### How the Synthesizer Uses It

The converge prompt includes confidence information:

```
CONVERGE_PROMPT_WITH_CONFIDENCE = """
...

When creating the final plan, for each decision note:
- STRONG (3/3 agents agree, high confidence): implement as proposed
- MODERATE (2/3 agree, mixed confidence): implement but flag for review
- WEAK (split decision, low confidence): escalate to user or mark as TODO

Format each decision as:
[STRONG/MODERATE/WEAK] Decision: ... 
  For: [argument] | Against: [argument]
"""
```

### How Downstream Functions Use It

The `devil()` function specifically targets WEAK and MODERATE decisions:

```python
DEVIL_PROMPT_WITH_CONFIDENCE = """
...

THE TEAM'S DECISIONS:

STRONG DECISIONS (high agreement, high confidence):
{strong_decisions}
→ These are likely solid. Challenge only if you see a fundamental flaw.

MODERATE DECISIONS (partial agreement):
{moderate_decisions}
→ Dig into these. The team wasn't fully aligned. Why? Were the dissenters right?

WEAK DECISIONS (low agreement, low confidence):
{weak_decisions}
→ These are your primary targets. The team knows these are shaky.
  Break them open. Propose concrete alternatives.
"""
```

**Token cost:** ~50 extra tokens per decision in the converge output. The devil prompt is ~100 tokens longer. But the devil's output is dramatically more targeted and useful -- no time wasted challenging solid decisions.

---

## 11. Context Archaeology (Run History)

### The Concept

Lion stores every run in `~/.lion/runs/`. Context Archaeology means searching previous runs for relevant context when starting a new task.

### Implementation: Lightweight Semantic Search

We don't need a vector database. A simple keyword + file path matching approach works:

```python
import os
import json
import re
from pathlib import Path

class ContextArchaeologist:
    """Search previous runs for relevant context."""
    
    def __init__(self, runs_dir: str):
        self.runs_dir = Path(runs_dir)
    
    def find_relevant_runs(self, prompt: str, files_involved: list[str],
                           max_results: int = 3) -> list[dict]:
        """Find previous runs relevant to the current task."""
        
        # Extract keywords from prompt
        keywords = self._extract_keywords(prompt)
        
        candidates = []
        
        for run_dir in sorted(self.runs_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            
            result_file = run_dir / "result.json"
            memory_file = run_dir / "memory.jsonl"
            
            if not memory_file.exists():
                continue
            
            # Score relevance
            score = self._score_relevance(
                run_dir, keywords, files_involved, memory_file, result_file
            )
            
            if score > 0.3:  # Minimum relevance threshold
                candidates.append({
                    "run_dir": str(run_dir),
                    "score": score,
                    "summary": self._extract_summary(memory_file),
                })
        
        # Sort by relevance, return top N
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:max_results]
    
    def _extract_keywords(self, prompt: str) -> set[str]:
        """Extract meaningful keywords from prompt."""
        # Remove common words
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be",
                     "been", "being", "have", "has", "had", "do", "does",
                     "did", "will", "would", "could", "should", "may",
                     "might", "shall", "can", "build", "create", "make",
                     "add", "fix", "update", "implement", "bouw"}
        
        words = set(re.findall(r'\b\w{3,}\b', prompt.lower()))
        return words - stopwords
    
    def _score_relevance(self, run_dir, keywords, files, memory_file, result_file):
        """Score how relevant a previous run is."""
        score = 0.0
        
        # Check run directory name for keyword matches
        run_name = run_dir.name.lower()
        keyword_matches = sum(1 for k in keywords if k in run_name)
        score += keyword_matches * 0.3
        
        # Check if same files were involved
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())
                previous_files = set(result.get("files_changed", []))
                file_overlap = len(set(files) & previous_files)
                score += file_overlap * 0.4
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Check memory for keyword matches (sample first 2000 chars)
        try:
            memory_text = memory_file.read_text()[:2000].lower()
            content_matches = sum(1 for k in keywords if k in memory_text)
            score += content_matches * 0.1
        except Exception:
            pass
        
        # Recency bonus (newer runs slightly preferred)
        # Run dirs are named: 2026-02-20_153200_description
        try:
            date_str = run_dir.name[:10]
            from datetime import datetime, timedelta
            run_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (datetime.now() - run_date).days
            if days_ago < 7:
                score += 0.2
            elif days_ago < 30:
                score += 0.1
        except (ValueError, IndexError):
            pass
        
        return min(1.0, score)
    
    def _extract_summary(self, memory_file: Path) -> str:
        """Extract a brief summary from a run's memory."""
        decisions = []
        uncertainties = []
        
        try:
            for line in memory_file.read_text().split('\n'):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") == "decision":
                    decisions.append(entry["content"][:200])
                if entry.get("type") == "proposal":
                    # Extract uncertainties from proposals
                    content = entry["content"]
                    if "uncertain" in content.lower():
                        uncertainties.append(content[:100])
        except (json.JSONDecodeError, KeyError):
            pass
        
        summary = ""
        if decisions:
            summary += f"Decisions: {decisions[0][:200]}"
        if uncertainties:
            summary += f"\nUncertainties flagged: {uncertainties[0][:100]}"
        
        return summary or "No summary available"
    
    def format_for_prompt(self, relevant_runs: list[dict], 
                          max_tokens: int = 500) -> str:
        """Format relevant history for injection into agent prompts."""
        
        if not relevant_runs:
            return ""
        
        parts = ["RELEVANT PREVIOUS WORK:"]
        remaining_tokens = max_tokens
        
        for run in relevant_runs:
            entry = f"\n- {run['summary']}"
            entry_tokens = len(entry.split()) * 1.3
            
            if entry_tokens > remaining_tokens:
                break
            
            parts.append(entry)
            remaining_tokens -= entry_tokens
        
        return "\n".join(parts)
```

### How Archaeology Integrates

```python
# In the pipeline executor, before running pride():

if config.get("context", {}).get("archaeology", True):
    archaeologist = ContextArchaeologist(runs_dir)
    
    # Find relevant previous runs
    relevant = archaeologist.find_relevant_runs(
        prompt=prompt,
        files_involved=detect_relevant_files(prompt, cwd),
        max_results=3
    )
    
    if relevant:
        history_context = archaeologist.format_for_prompt(relevant, max_tokens=500)
        
        # Inject into pride's shared context
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="archaeology",
            agent="historian",
            type="historical_context",
            content=history_context,
            metadata={"runs_found": len(relevant)}
        ))
```

### Example

```
User runs: lion '"Fix the webhook timeout bug in Stripe"'

Lion searches runs/ and finds:
  - 2026-02-15_build_stripe_checkout (relevance: 0.85)
    Decisions: "Stripe Checkout Session with webhooks, 
      repository pattern. Agent 2 raised concern about 
      webhook retry logic being fragile. Webhook error 
      handling was marked as WEAK decision (confidence 0.5)."

Agent receives this in context:
  "RELEVANT PREVIOUS WORK:
   - 6 days ago, the team built Stripe checkout. An agent
     flagged webhook retry logic as fragile (low confidence
     decision). This may be related to your current bug."

Agent's response is now MUCH more targeted. Instead of
investigating from scratch, they go directly to the 
webhook retry logic that was already flagged as risky.
```

**Token cost:** ~500 tokens max for historical context. Zero extra LLM calls (pure Python file search). Massive time savings when fixing bugs or extending previous work.

### Configuration

```toml
[context]
archaeology = true           # Enable/disable
archaeology_max_results = 3  # Max previous runs to include
archaeology_max_tokens = 500 # Max tokens for history context
archaeology_max_age_days = 90 # Ignore runs older than this
```

---

## 12. Token Budget Analysis

### Complete Pipeline Comparison

```
PIPELINE: pride(3) -> devil() -> review()

WITHOUT LAYER 2 (current Lion):
  context():   0 tokens (doesn't exist)
  pride propose:  3 × 800  = 2,400 tokens generated
  pride critique: 3 × 800  = 2,400 tokens (2,400 context loaded)
  pride converge: 1 × 1000 = 1,000 tokens (4,800 context loaded)
  pride implement: 1 × 2000 = 2,000 tokens
  devil:        1 × 1500 = 1,500 tokens (5,800 context loaded)
  review:       1 × 1200 = 1,200 tokens (7,800 context loaded)
  
  TOTAL generated:  10,500 tokens
  MAX context load: 7,800 tokens (review step)

WITH LAYER 2 (minimal mode):
  Identical to above. Zero overhead.

WITH LAYER 2 (standard mode):
  context():   0 tokens (not in pipeline)
  pride propose:  3 × 1,000 = 3,000 tokens (+25%)
  pride critique: 3 × 900   = 2,700 tokens (3,300 context loaded)
  pride converge: 1 × 1,200 = 1,200 tokens (5,700 context loaded)
  pride implement: 1 × 2,000 = 2,000 tokens
  devil:        1 × 1,200 = 1,200 tokens (3,000 context loaded*)
  review:       1 × 1,000 = 1,000 tokens (4,000 context loaded*)
  
  * Devil and review get TARGETED context, not everything
  
  TOTAL generated:  11,100 tokens (+5.7%)
  MAX context load: 5,700 tokens (-27% because targeted context)
  
  Cost increase: ~600 tokens (~5.7%)
  Quality increase: dramatic (targeted critique, focused review)

WITH LAYER 2 (standard + distill):
  context():    800 tokens (shared context)
  pride propose:  3 × 1,000 = 3,000 tokens
  pride critique: 3 × 900   = 2,700 tokens
  pride converge: 1 × 1,200 = 1,200 tokens
  pride implement: 1 × 2,000 = 2,000 tokens
  distill():    800 tokens → produces 2,000 token summary
  devil:        1 × 1,200 = 1,200 tokens (2,000 context loaded)
  review:       1 × 1,000 = 1,000 tokens (3,000 context loaded)
  
  TOTAL generated:  12,700 tokens (+21%)
  MAX context load: 3,000 tokens (-62%!)
  
  Cost increase: ~2,200 tokens (21%)  
  Context load decrease: 62%
  Quality: best -- targeted, compressed, relevant context throughout

WITH LAYER 2 (rich + context + distill + archaeology):
  archaeology:  0 LLM tokens (pure Python search)
  context():    800 tokens
  pride propose:  3 × 1,300 = 3,900 tokens
  pride critique: 3 × 1,100 = 3,300 tokens
  pride converge: 1 × 1,400 = 1,400 tokens
  pride implement: 1 × 2,000 = 2,000 tokens
  distill():    800 tokens
  devil:        1 × 1,200 = 1,200 tokens (2,500 context)
  review:       1 × 1,000 = 1,000 tokens (3,500 context)
  
  TOTAL generated:  14,400 tokens (+37%)
  MAX context load: 3,500 tokens (-55%)
  
  Maximum quality. 37% more tokens but 55% less context bloat.
  The extra tokens are ALL high-signal information.
```

### Cost Summary Table

| Mode | Extra tokens | Context load | Quality | Best for |
|------|-------------|--------------|---------|----------|
| minimal | +0% | baseline | baseline | Simple tasks, budget saving |
| standard | +6% | -27% | high | Standard development |
| standard + distill | +21% | -62% | very high | Complex features |
| rich + all | +37% | -55% | maximum | Critical architecture decisions |

### The Key Insight

**Layer 2 can actually REDUCE the effective context load** even while generating more tokens. This is because:
1. `distill()` compresses verbose deliberation into signal
2. Context inheritance rules prevent irrelevant context from reaching downstream steps
3. Targeted context means agents focus on what matters, not wading through noise

---

## 13. Implementation Guide

### Phase 2A: Context Packages (implement first)

1. **Modify propose prompts** to include structured sections
2. **Build the parser** (`parse_context_package()`)
3. **Modify critique prompts** to present other agents' context metadata
4. **Store packages in shared memory** (extend MemoryEntry with context fields)
5. **Add `--context` CLI flag** for mode selection

Estimated effort: 2-3 hours. Low risk, high impact.

### Phase 2B: Context Functions

1. **Build `context()` function** -- shared mental model
2. **Build `distill()` function** -- context compression
3. **Build `ContextBudgetManager`** -- auto-distill when budget exceeded
4. **Add context inheritance rules** -- which function gets what context

Estimated effort: 3-4 hours. Medium complexity.

### Phase 2C: Context Adaptation

1. **Build `ContextAdapter`** -- format context per provider
2. **Integrate with provider system** -- adapter called before each LLM call

Estimated effort: 1-2 hours. Only useful once multi-LLM is implemented.

### Phase 2D: Archaeology

1. **Build `ContextArchaeologist`** -- keyword search over run history
2. **Integrate with pipeline start** -- auto-search before pride()
3. **Add configuration options** -- enable/disable, age limits

Estimated effort: 2-3 hours. Independent of other Layer 2 features.

### Phase 2E: Advanced (Belief States, Confidence Weighting)

1. **Add belief state sections** to rich mode prompts
2. **Add per-decision confidence** to converge prompt
3. **Modify devil prompt** to target weak decisions

Estimated effort: 2-3 hours. Only for rich mode, not needed for MVP.

### Recommended Build Order

```
2A: Context Packages      ← Start here. Biggest impact, lowest effort.
2B: distill()             ← Second. Essential for long pipelines.
2D: Archaeology           ← Third. Independent, useful immediately.
2B: context()             ← Fourth. Useful for large codebases.
2C: Context Adaptation    ← When multi-LLM is ready.
2E: Belief States etc.    ← Last. Polish. Rich mode only.
```

---

## 14. File Structure

```
~/.lion/
├── context/
│   ├── __init__.py
│   ├── package.py           # ContextPackage dataclass
│   ├── parser.py            # Parse structured agent output
│   ├── adapter.py           # Cross-LLM context formatting
│   ├── budget.py            # Token budget management + auto-distill
│   ├── archaeology.py       # Run history search
│   └── belief.py            # Belief state tracking (rich mode)
│
├── functions/
│   ├── context_build.py     # context() pipeline function
│   ├── distill.py           # distill() pipeline function
│   └── ...existing functions...
│
├── prompts/
│   ├── propose_minimal.txt  # Propose prompt for minimal mode
│   ├── propose_standard.txt # Propose prompt with context sections
│   ├── propose_rich.txt     # Propose prompt with full context
│   ├── critique_standard.txt# Critique prompt with context awareness
│   ├── critique_rich.txt    # Critique prompt with belief states
│   ├── converge_standard.txt# Converge prompt with confidence
│   └── devil_targeted.txt   # Devil prompt targeting weak decisions
│
└── runs/
    └── {run_id}/
        ├── memory.jsonl       # Now includes context package fields
        ├── context.json       # Shared mental model (if context() was used)
        ├── distilled.json     # Compressed context (if distill() was used)
        └── result.json        # Includes confidence map
```

---

## Appendix: Quick Reference

```
CONTEXT MODES:
  --context minimal     No extra context (current behavior)
  --context standard    Reasoning + alternatives + uncertainties + confidence
  --context rich        Above + assumptions + risks + beliefs + questions
  --context auto        Lion decides based on pipeline complexity (default)

CONTEXT FUNCTIONS:
  context()             Build shared codebase mental model before pride
  distill()             Compress accumulated context between steps

CONFIGURATION:
  [context]
  default_mode = "auto"
  max_context_tokens_per_step = 4000
  max_total_context_tokens = 15000
  archaeology = true
  archaeology_max_results = 3
  archaeology_max_age_days = 90
  distill_provider = "gemini"          # Use cheap provider for compression

TOKEN BUDGET GUIDE:
  minimal:  +0% tokens, baseline quality
  standard: +6% tokens, much better critique quality
  standard + distill: +21% tokens, 62% less context bloat
  rich + all: +37% tokens, maximum quality for critical decisions
```

---

*Layer 2 transforms Lion from "multiple agents answering the same question" to "multiple agents that understand each other's thinking." The difference is like a team that only reads each other's emails versus a team that sits in the same room and can see each other's whiteboards, hear their hesitations, and know their thought process.*

*Built for Lion v2.0 by Menno Sijben, 2026.*