# Lion -- Lens System

## Focused Perspectives for Multi-Agent Deliberation

---

## Table of Contents

1. [Why Lenses, Not Personas](#1-why-lenses-not-personas)
2. [Syntax](#2-syntax)
3. [How Lenses Work](#3-how-lenses-work)
4. [Built-in Lenses](#4-built-in-lenses)
5. [Custom Lenses](#5-custom-lenses)
6. [Auto-Assignment](#6-auto-assignment)
7. [Lenses in Each Phase](#7-lenses-in-each-phase)
8. [Integration with Context Packages](#8-integration-with-context-packages)
9. [Token Analysis](#9-token-analysis)
10. [Lens Combinations & Anti-Patterns](#10-lens-combinations--anti-patterns)
11. [Implementation Guide](#11-implementation-guide)
12. [File Structure](#12-file-structure)

---

## 1. Why Lenses, Not Personas

### What the research says

Academic studies on role-prompting show a clear pattern:

- **Vague personas have near-zero effect on accuracy.** Telling an LLM "You are a senior engineer" changes tone and jargon but not the quality of reasoning. The LLM already does its best regardless of assigned identity.
- **Task-relevant focus instructions measurably improve output.** Telling an LLM "Analyze this code ONLY for SQL injection, XSS, and auth bypass -- ignore everything else" produces dramatically better security analysis than "You are a security expert, review this code."
- **The mechanism is attention steering, not role-playing.** LLMs don't become better by pretending to be someone. They become better when their attention is constrained to a specific dimension.

### The distinction

```
PERSONA (identity-based, weak):
  "You are a senior software architect with 15 years of experience"
  → Model: "Okay, I'll use more formal language and mention design patterns"
  → Output: marginally different tone, same substance

LENS (attention-based, strong):
  "Analyze ONLY: separation of concerns, dependency direction,
   interface boundaries, and scaling bottlenecks. IGNORE: naming,
   style, implementation details, test coverage."
  → Model: "I will only look at these specific dimensions"
  → Output: deeper, more focused, non-overlapping with other agents
```

A persona says WHO you are. A lens says WHERE you look.

### Why this matters for Lion specifically

In a `pride(3)` without lenses, all 3 agents examine the same problem from roughly the same angle. This produces ~80% overlapping proposals -- a waste of tokens.

With lenses, each agent examines a different dimension. Overlap drops to ~10-20%. Three agents produce three times the unique insight, in fewer total tokens.

---

## 2. Syntax

### The `::` Operator

```bash
provider::lens
```

The double colon reads as "provider, through this lens." Clean, unambiguous, visually distinct from other syntax.

### Usage Examples

```bash
# Explicit lenses
lion '"Build payment API" -> pride(claude::arch, gemini::sec, codex::quick)'

# Mix lensed and unlensed agents
lion '"Build feature" -> pride(claude::arch, gemini, claude::sec)'

# Same provider, different lenses
lion '"Build auth" -> pride(claude::arch, claude::sec, claude::dx)'

# Lenses on review and other functions
lion '"Build API" -> pride(3) -> review(claude::sec)'

# Auto-assignment (Lion picks lenses based on task)
lion '"Build payment system" -> pride(3, lenses: auto)'

# Full names instead of shortcodes
lion '"Build API" -> pride(claude::architecture, gemini::security)'
```

### Lens on non-pride functions

Lenses work on any function that takes a provider:

```bash
# Security-focused review
lion '"Build auth" -> pride(3) -> review(claude::sec)'

# Architecture-focused devil's advocate
lion '"Build system" -> pride(3) -> devil(claude::arch)'

# Maintainability-focused future review
lion '"Build feature" -> pride(3) -> future(6m, claude::maint)'
```

---

## 3. How Lenses Work

### Without Lenses (current behavior)

```
pride(3) for "Build payment API":

  Agent 1: "Here's my complete proposal for the payment API.
            I'd use Express with a service layer, PostgreSQL,
            Stripe SDK, webhook handling, error middleware..."
            (~800 tokens, covers everything broadly)

  Agent 2: "Here's my complete proposal for the payment API.
            I'd use Express with repository pattern, PostgreSQL,
            Stripe Checkout, webhook verification..."
            (~800 tokens, 80% overlaps with Agent 1)

  Agent 3: "Here's my complete proposal for the payment API.
            I suggest a clean architecture with Stripe..."
            (~800 tokens, 75% overlaps with Agent 1 and 2)

  Total: ~2400 tokens generated
  Unique information: ~600 tokens (25%)
  Wasted overlap: ~1800 tokens (75%)
```

### With Lenses

```
pride(claude::arch, gemini::sec, codex::quick) for "Build payment API":

  Agent 1 (arch lens): "Architecture analysis:
    Service layer with PaymentService as facade.
    Repository pattern for data access, separating
    Stripe SDK behind PaymentGateway interface.
    Webhook processing as separate bounded context.
    Event-driven for order status updates."
    (~500 tokens, deep on architecture only)

  Agent 2 (sec lens): "Security analysis:
    Webhook signature verification required (HMAC SHA256).
    Idempotency keys to prevent duplicate charges.
    No PCI data in logs -- mask card numbers.
    Rate limit /checkout endpoint (10/min/user).
    CSRF token for checkout form submission."
    (~400 tokens, deep on security only)

  Agent 3 (quick lens): "Pragmatic path:
    Use Stripe Checkout Session -- hosted page, no PCI scope.
    Skip custom payment form entirely.
    3 files: routes/checkout.ts, services/stripe.ts, webhooks/stripe.ts.
    Use stripe CLI for local webhook testing.
    Ship in 2 hours, not 2 days."
    (~350 tokens, focused on fastest path)

  Total: ~1250 tokens generated
  Unique information: ~1100 tokens (88%)
  Overlap: ~150 tokens (12%)
```

**Half the tokens, triple the unique insights.**

### The Converge Phase (where it comes together)

The synthesizer receives three complementary analyses instead of three overlapping proposals:

```
"Agent 1 analyzed the architecture and recommends a service layer
 with a gateway interface. Agent 2 identified 5 security requirements
 including webhook verification and rate limiting. Agent 3 found that
 Stripe Checkout Session eliminates PCI scope entirely.

 My synthesis: Use Stripe Checkout (Agent 3's pragmatic approach)
 behind Agent 1's PaymentService facade (good architecture), with
 all of Agent 2's security requirements as hard constraints.

 This gives us: clean architecture + full security + ships fast."
```

That synthesis is only possible because each agent went DEEP on a different dimension rather than BROAD on everything.

---

## 4. Built-in Lenses

### The Lens Dataclass

```python
@dataclass
class Lens:
    """A focused perspective that steers agent attention."""
    name: str           # Full name: "Architecture"
    shortcode: str      # CLI shortcode: "arch"
    prompt_inject: str  # Injected into propose prompt
    critique_inject: str  # Injected into critique prompt
    best_models: list[str]  # Which LLMs work best with this lens
    token_overhead: int  # Approximate extra tokens in prompt
```

### Architecture (`arch`)

```python
"arch": Lens(
    name="Architecture",
    shortcode="arch",
    prompt_inject="""YOUR LENS: Architecture & Design
Focus ONLY on: system design, separation of concerns, dependency
direction, interface boundaries, module cohesion, and scaling patterns.

IGNORE: variable naming, code style, test coverage, security specifics,
and implementation details. If the architecture is sound but the code
is ugly, say the architecture is sound.

Go deep. Other agents cover other dimensions.""",
    critique_inject="""Review other proposals ONLY from an architecture perspective.
Does their approach have clean boundaries? Will it scale? Are dependencies pointing
the right direction? Do NOT critique their security or style choices.""",
    best_models=["claude", "gemini"],
    token_overhead=60,
)
```

### Security (`sec`)

```python
"sec": Lens(
    name="Security",
    shortcode="sec",
    prompt_inject="""YOUR LENS: Security
Focus ONLY on: input validation, authentication, authorization, injection
vulnerabilities (SQL, XSS, command), data exposure, secrets management,
OWASP top 10, and dependency vulnerabilities.

IGNORE: architecture elegance, performance optimization, code style, naming.
If the code is ugly but secure, say it's secure.

Treat every user input as hostile. Think like an attacker.""",
    critique_inject="""Review other proposals ONLY for security implications.
Does their architecture create attack surfaces? Does their pragmatic approach
cut security corners? What security constraints must they satisfy?""",
    best_models=["claude"],
    token_overhead=65,
)
```

### Performance (`perf`)

```python
"perf": Lens(
    name="Performance",
    shortcode="perf",
    prompt_inject="""YOUR LENS: Performance
Focus ONLY on: time complexity, database query efficiency (N+1 queries,
missing indexes, full table scans), memory allocation, caching opportunities,
connection pooling, and scaling bottlenecks.

IGNORE: code readability, security, naming conventions, test coverage.
If the code is unreadable but fast, say it's fast.

Think in terms of: what happens at 10x and 100x current load?""",
    critique_inject="""Review other proposals ONLY for performance implications.
Will their architecture create bottlenecks? Are there unnecessary round trips?
What will break first under load?""",
    best_models=["claude", "gemini"],
    token_overhead=60,
)
```

### Pragmatic (`quick`)

```python
"quick": Lens(
    name="Pragmatic",
    shortcode="quick",
    prompt_inject="""YOUR LENS: Pragmatic / Ship Fast
Focus ONLY on: what is the fastest path to working, tested code?

Minimize abstractions -- add them later when needed, not before.
Prefer standard library over external packages.
Prefer simple over clever. Prefer working over elegant.
Challenge any complexity that isn't paying for itself RIGHT NOW.
YAGNI (You Ain't Gonna Need It) is your guiding principle.

Count files. Fewer is better. Count dependencies. Fewer is better.
If you can do it in 50 lines instead of 200 with a pattern, do 50.""",
    critique_inject="""Review other proposals ONLY for unnecessary complexity.
Are they over-engineering? Adding abstractions nobody asked for? Using patterns
that won't pay off at current scale? What can be simplified or deferred?""",
    best_models=["codex", "claude"],
    token_overhead=70,
)
```

### Maintainability (`maint`)

```python
"maint": Lens(
    name="Maintainability",
    shortcode="maint",
    prompt_inject="""YOUR LENS: Maintainability
Focus ONLY on: will a developer who has never seen this code understand it
in 6 months? Evaluate naming clarity, function length, documentation needs,
separation of business logic from infrastructure, test coverage gaps, and
how easy it is to change one thing without breaking another.

IGNORE: performance optimization, security hardening, architecture theory.
The question is: can someone else work on this comfortably?""",
    critique_inject="""Review other proposals ONLY for maintainability.
Will a new team member understand this? Are there hidden dependencies?
Is business logic tangled with infrastructure? What will confuse people?""",
    best_models=["claude", "gemini"],
    token_overhead=55,
)
```

### Developer Experience (`dx`)

```python
"dx": Lens(
    name="Developer Experience",
    shortcode="dx",
    prompt_inject="""YOUR LENS: Developer Experience
Focus ONLY on: is this pleasant to work with as a developer?

Evaluate: error messages (helpful or cryptic?), debugging ease (can you
find what went wrong?), API ergonomics (intuitive or surprising?),
type safety, configuration simplicity, and documentation quality.

IGNORE: internal implementation quality, performance, security.
A beautiful API with ugly internals scores HIGH on this lens.""",
    critique_inject="""Review other proposals ONLY for developer experience.
Will developers enjoy using this? Are error messages helpful? Is the API
intuitive? What will frustrate someone integrating with this?""",
    best_models=["claude"],
    token_overhead=55,
)
```

### Data Integrity (`data`)

```python
"data": Lens(
    name="Data Integrity",
    shortcode="data",
    prompt_inject="""YOUR LENS: Data Integrity
Focus ONLY on: data consistency, race conditions, transaction boundaries,
migration safety (zero-downtime, reversible), backup/restore, audit trails,
cascading deletes, and foreign key integrity.

IGNORE: API design, code style, frontend concerns.
The question is: can data get corrupted, lost, or inconsistent?""",
    critique_inject="""Review other proposals ONLY for data integrity risks.
Can concurrent requests corrupt data? Are transactions scoped correctly?
Can the migration fail halfway and leave the database inconsistent?""",
    best_models=["claude", "gemini"],
    token_overhead=55,
)
```

### Cost Awareness (`cost`)

```python
"cost": Lens(
    name="Cost Awareness",
    shortcode="cost",
    prompt_inject="""YOUR LENS: Cost Awareness
Focus ONLY on: infrastructure and operational cost implications.

Every external API call, database query, storage write, compute cycle,
and bandwidth byte costs money. Flag anything that could cause surprise
bills at scale. Estimate monthly costs for 100, 10K, 1M requests/day.
Suggest cheaper alternatives where possible.

IGNORE: code quality, architecture elegance, security.
The question is: what will the cloud bill look like?""",
    critique_inject="""Review other proposals ONLY for cost implications.
What will their approach cost in production? Are there cheaper alternatives?
What's the cost difference between their approach and a simpler one?""",
    best_models=["gemini", "claude"],
    token_overhead=55,
)
```

### Testability (`test_lens`)

```python
"test_lens": Lens(
    name="Testability",
    shortcode="test_lens",
    prompt_inject="""YOUR LENS: Testability
Focus ONLY on: can this code be tested easily? Are there hard-coded
dependencies that prevent mocking? Is business logic separated from
I/O? Are edge cases identifiable? What test cases are needed?

IGNORE: performance, security, architecture theory.
List the specific test cases that should exist.""",
    critique_inject="""Review other proposals ONLY for testability.
Can their code be unit tested without spinning up databases?
What mocking is needed? What edge cases will be hard to test?""",
    best_models=["claude", "codex"],
    token_overhead=50,
)
```

### Lens Summary Table

| Shortcode | Name | Focus | Tokens | Best models |
|-----------|------|-------|--------|-------------|
| `arch` | Architecture | Design, boundaries, scaling | +60 | claude, gemini |
| `sec` | Security | OWASP, auth, injection, data | +65 | claude |
| `perf` | Performance | Speed, queries, caching, N+1 | +60 | claude, gemini |
| `quick` | Pragmatic | Ship fast, YAGNI, simplicity | +70 | codex, claude |
| `maint` | Maintainability | Readability, onboarding, change | +55 | claude, gemini |
| `dx` | Developer Experience | API ergonomics, errors, types | +55 | claude |
| `data` | Data Integrity | Consistency, transactions, migrations | +55 | claude, gemini |
| `cost` | Cost Awareness | Cloud bills, API pricing, scaling | +55 | gemini, claude |
| `test_lens` | Testability | Mocking, edge cases, coverage | +50 | claude, codex |

---

## 5. Custom Lenses

### Creating Custom Lenses

```bash
# From CLI
lion lens gdpr "Focus ONLY on: data storage locations, consent mechanisms,
  right to deletion, data processing agreements, cookie handling,
  and cross-border data transfers. Flag any PII that is stored without
  explicit consent. IGNORE: performance, code style, architecture."

lion lens hipaa "Focus ONLY on: PHI (Protected Health Information) handling,
  access controls, audit logging, encryption at rest and in transit,
  BAA requirements, and minimum necessary standard."

lion lens a11y "Focus ONLY on: accessibility. WCAG 2.1 AA compliance,
  screen reader support, keyboard navigation, color contrast ratios,
  focus management, and ARIA attributes."
```

### Storage Format

`~/.lion/lenses/custom.json`:

```json
{
    "gdpr": {
        "name": "GDPR Compliance",
        "shortcode": "gdpr",
        "prompt_inject": "Focus ONLY on: data storage locations...",
        "critique_inject": "Review other proposals ONLY for GDPR compliance...",
        "created": "2026-02-21T15:30:00Z"
    }
}
```

### Using Custom Lenses

```bash
# Use like built-in lenses
lion '"Build patient portal" -> pride(claude::hipaa, claude::sec, gemini::arch)'

# Combine built-in and custom
lion '"Build EU checkout" -> pride(claude::gdpr, claude::sec, codex::quick)'
```

### AI-Generated Custom Lenses

Lion can generate a lens from a description:

```bash
lion lens-generate "LEGO brick inventory management with color matching"

# Lion calls a cheap LLM to produce:
# Lens 'lego_inv' created:
#   Focus ONLY on: part identification accuracy, color matching under
#   different lighting, inventory count integrity, bag-to-piece mapping
#   correctness, and sort-order consistency. IGNORE: UI design,
#   API architecture, database optimization.
```

---

## 6. Auto-Assignment

### How `lenses: auto` Works

```bash
lion '"Build payment system" -> pride(3, lenses: auto)'
# Lion analyzes the prompt and picks: arch, sec, data
```

### Task-to-Lens Mapping

```python
TASK_LENS_MAP = [
    {
        "match": ["payment", "stripe", "checkout", "billing", "invoice"],
        "lenses": ["arch", "sec", "data"],
        "reason": "Payment systems need solid architecture, security, and data integrity",
    },
    {
        "match": ["auth", "login", "session", "jwt", "oauth", "sso", "password"],
        "lenses": ["sec", "arch", "dx"],
        "reason": "Auth is security-critical with user-facing API surface",
    },
    {
        "match": ["api", "endpoint", "route", "rest", "graphql"],
        "lenses": ["arch", "dx", "perf"],
        "reason": "APIs need clean design, good DX, and performance",
    },
    {
        "match": ["database", "migration", "schema", "model", "query"],
        "lenses": ["data", "perf", "maint"],
        "reason": "Database work centers on integrity, speed, and maintainability",
    },
    {
        "match": ["ui", "frontend", "component", "page", "form", "dashboard"],
        "lenses": ["dx", "perf", "maint"],
        "reason": "Frontend needs good UX, fast rendering, and maintainable components",
    },
    {
        "match": ["refactor", "cleanup", "tech debt", "reorganize"],
        "lenses": ["maint", "arch", "quick"],
        "reason": "Refactoring targets maintainability and architecture, pragmatically",
    },
    {
        "match": ["deploy", "docker", "ci", "pipeline", "kubernetes", "infra"],
        "lenses": ["quick", "sec", "cost"],
        "reason": "Infrastructure should ship fast, be secure, and be cost-aware",
    },
    {
        "match": ["scale", "performance", "optimize", "slow", "cache"],
        "lenses": ["perf", "arch", "cost"],
        "reason": "Performance needs profiling focus, architecture, cost awareness",
    },
    {
        "match": ["test", "coverage", "spec", "e2e", "integration test"],
        "lenses": ["test_lens", "maint", "quick"],
        "reason": "Testing needs testability analysis, maintainability, pragmatism",
    },
]

# Default when no keywords match
DEFAULT_LENSES = ["arch", "sec", "quick"]
```

### Implementation

```python
def auto_assign_lenses(prompt: str, n_agents: int) -> list[str]:
    """Select lenses based on the task prompt."""
    prompt_lower = prompt.lower()
    
    best_match = None
    best_score = 0
    
    for mapping in TASK_LENS_MAP:
        score = sum(1 for kw in mapping["match"] if kw in prompt_lower)
        if score > best_score:
            best_score = score
            best_match = mapping
    
    if best_match and best_score > 0:
        return best_match["lenses"][:n_agents]
    
    return DEFAULT_LENSES[:n_agents]
```

### Model-Lens Affinity

When using mixed LLMs with auto-assignment, Lion matches lenses to models that are best at each:

```python
def assign_lenses_to_providers(providers: list[str], lenses: list[str]) -> list[tuple]:
    """Match lenses to providers based on affinity."""
    assignments = []
    available_providers = list(providers)
    available_lenses = list(lenses)
    
    while available_providers and available_lenses:
        best_score = -1
        best_pair = None
        
        for p in available_providers:
            for l in available_lenses:
                lens_def = LENSES[l]
                score = 1.0 if p in lens_def.best_models else 0.5
                if score > best_score:
                    best_score = score
                    best_pair = (p, l)
        
        if best_pair:
            assignments.append(best_pair)
            available_providers.remove(best_pair[0])
            available_lenses.remove(best_pair[1])
    
    return assignments

# Example:
# providers = ["claude", "gemini", "codex"]
# lenses = ["sec", "arch", "quick"]
# Result: [("claude", "sec"), ("gemini", "arch"), ("codex", "quick")]
# Because claude is best for sec, gemini good for arch, codex best for quick
```

---

## 7. Lenses in Each Phase

### Propose Phase

Each agent receives the base task + their lens injection:

```python
def build_lensed_propose_prompt(task, agent_num, total, lens, shared_context=None):
    prompt = f"""You are Agent {agent_num} of {total} analyzing:

TASK: {task}
"""
    if shared_context:
        prompt += f"\nCODEBASE CONTEXT:\n{shared_context}\n"
    
    prompt += f"""
{lens.prompt_inject}

Other agents are analyzing from different angles.
You do NOT need to cover everything -- go DEEP on your area.

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
"""
    return prompt
```

**Key design:** The prompt explicitly says "other agents cover other angles." This gives the agent permission to go deep instead of broad.

### Critique Phase

Agents critique ONLY through their own lens:

```python
def build_lensed_critique_prompt(task, agent_num, own_lens, own_proposal,
                                  other_proposals):
    prompt = f"""You are Agent {agent_num} with the {own_lens.name} lens.

TASK: {task}

YOUR ANALYSIS ({own_lens.name}):
{own_proposal}

OTHER AGENTS' ANALYSES:
"""
    for other in other_proposals:
        prompt += f"""
--- Agent {other['num']} ({other['lens_name']} perspective) ---
{other['output']}
"""
    
    prompt += f"""
{own_lens.critique_inject}

Specifically:
1. What implications do their proposals have for {own_lens.name.lower()}?
2. Do any of their approaches conflict with your findings?
3. What constraints from YOUR analysis must their approaches satisfy?

Stay in your lane. Do not critique aspects outside your lens."""
    return prompt
```

**"Stay in your lane" is critical.** Without it, the security agent starts critiquing architecture, recreating the overlap problem. Each agent's critique is scoped to their lens, producing cross-pollination without redundancy.

### Converge Phase

The synthesizer receives labeled, non-overlapping analyses:

```python
def build_lensed_converge_prompt(task, proposals, critiques):
    prompt = f"""Synthesize these focused analyses into a final plan.

TASK: {task}

ANALYSES FROM DIFFERENT PERSPECTIVES:
"""
    for p in proposals:
        prompt += f"""
=== {p['lens_name'].upper()} PERSPECTIVE (Agent {p['num']}, {p['model']}) ===
Confidence: {p['confidence']}

{p['output']}

Warnings: {', '.join(p.get('warnings', ['none']))}
"""
    
    prompt += "\nCROSS-PERSPECTIVE CRITIQUES:\n"
    for c in critiques:
        prompt += f"[{c['lens_name']}→others]: {c['output']}\n\n"
    
    prompt += """Create the FINAL PLAN that:
1. Satisfies ALL high-confidence warnings as hard requirements
2. Integrates insights from every perspective
3. Where perspectives conflict, explain which takes priority and why
4. Marks each decision with the perspective(s) that support it

Format each decision:
DECISION: [what and why]
  Supported by: [lens names]
  Confidence: [STRONG/MODERATE/WEAK]
  Warnings addressed: [from which lens]
"""
    return prompt
```

### How Lenses Feed Into devil() and review()

After `distill()`, compressed context retains lens labels:

```
COMPRESSED CONTEXT (with lens labels):

  DECISION: Use Stripe Checkout Session (not custom form)
    Supported by: quick, sec
    Quick: eliminates PCI scope, ships in hours
    Sec: hosted page = Stripe handles card data, less attack surface
    Confidence: STRONG (2 lenses support, no dissent)

  DECISION: Repository pattern for payment data
    Supported by: arch
    Opposed by: quick (unnecessary abstraction for MVP)
    Confidence: MODERATE (1 supports, 1 opposes)
  
  DECISION: Webhook retry with exponential backoff
    Supported by: data
    Warning: data agent flagged idempotency as incomplete
    Confidence: WEAK (warning not fully resolved)

  UNRESOLVED: Rate limiting strategy
    Sec recommended 10/min/user
    Quick said "add later"
    → Needs resolution
```

The `devil()` now targets MODERATE and WEAK decisions, and unresolved conflicts between lenses.

---

## 8. Integration with Context Packages

### Lens-Enriched Context Packages

When lenses are active, context packages include lens-specific metadata:

```python
@dataclass
class LensedContextPackage(ContextPackage):
    """Context package extended with lens information."""
    
    lens: Optional[str] = None               # Lens shortcode
    lens_name: Optional[str] = None          # Lens full name
    lens_findings: list[str] = field(default_factory=list)
                                              # Key findings from this lens
    lens_warnings: list[str] = field(default_factory=list)
                                              # Warnings from this perspective
    cross_lens_concerns: list[str] = field(default_factory=list)
                                              # Concerns about OTHER agents' proposals
```

### Example Package

```python
LensedContextPackage(
    output="Architecture analysis: Service layer with PaymentGateway...",
    agent_id="agent_1",
    model="claude",
    
    # Standard context fields (from Layer 2)
    reasoning="Service layer provides clean separation and testability",
    alternatives=["Direct Stripe SDK calls: rejected, hard to swap providers"],
    uncertainties=["Should webhook processing be same service or separate?"],
    confidence=0.8,
    
    # Lens-specific fields
    lens="arch",
    lens_name="Architecture",
    lens_findings=[
        "Repository pattern fits existing codebase conventions",
        "Webhook processor should be separate bounded context",
    ],
    lens_warnings=[
        "PaymentService becoming god class -- split into Checkout and Subscription",
    ],
    cross_lens_concerns=[
        "Quick agent's minimal-files approach may create coupling",
    ],
)
```

### How Context + Lenses Combine

```
STANDARD CONTEXT PACKAGE (from Layer 2):
  output + reasoning + alternatives + uncertainties + confidence
  → Tells downstream agents WHAT was decided and WHY

LENS METADATA (from Lens System):
  lens + lens_findings + lens_warnings + cross_lens_concerns
  → Tells downstream agents FROM WHICH PERSPECTIVE and WHAT TO WATCH

COMBINED:
  devil() receives:
    "The architecture agent (confidence 0.8) recommends repository pattern,
     but warned about god class risk. The security agent (confidence 0.9)
     requires webhook HMAC verification. The pragmatic agent (confidence 0.85)
     opposed the repository pattern as over-engineering.
     
     WEAK POINTS: repository pattern (contested), rate limiting (unresolved)
     STRONG POINTS: Stripe Checkout (supported by 2 lenses)"

  → devil() knows exactly where to dig. No time wasted challenging
     strong, well-supported decisions.
```

### Parsing Lens Output

The standard context parser (from Layer 2) is extended:

```python
def parse_lensed_output(raw_output: str, agent_id: str, model: str,
                         lens: Lens, mode: ContextMode) -> LensedContextPackage:
    """Parse structured agent output into a LensedContextPackage."""
    
    # First, parse standard context fields
    base = parse_context_package(raw_output, agent_id, model, mode)
    
    # Then extract lens-specific fields
    sections = extract_sections(raw_output)
    
    return LensedContextPackage(
        # Inherit all standard fields
        **{k: v for k, v in base.__dict__.items()},
        
        # Add lens fields
        lens=lens.shortcode,
        lens_name=lens.name,
        lens_findings=parse_list(sections.get("key findings", "")),
        lens_warnings=parse_list(sections.get("warnings", "")),
        cross_lens_concerns=[],  # Populated during critique phase
    )
```

---

## 9. Token Analysis

### Direct Comparison

```
PRIDE(3) WITHOUT LENSES:
  3 agents × ~800 tokens output = ~2400 tokens
  Unique information: ~600 tokens (25%)
  Overlap waste: ~1800 tokens

PRIDE(3) WITH LENSES:
  3 agents × ~500 tokens output = ~1500 tokens
  Lens prompt overhead: 3 × ~60 tokens = ~180 tokens
  Total: ~1680 tokens
  Unique information: ~1350 tokens (80%)
  Overlap waste: ~330 tokens

SAVINGS: 30% fewer tokens, 125% more unique information
```

### Full Pipeline Comparison

```
Pipeline: pride(3) -> devil() -> review()

WITHOUT LENSES:
  pride propose:  2400 tokens (3 × 800)
  pride critique: 2400 tokens
  pride converge: 1200 tokens
  devil:          1500 tokens (unfocused, challenges everything equally)
  review:         1200 tokens (unfocused, reviews everything equally)
  TOTAL:          8700 tokens

WITH LENSES:
  pride propose:  1680 tokens (3 × 500 + 3 × 60 overhead)
  pride critique: 1500 tokens (shorter -- scoped to own lens)
  pride converge: 1200 tokens (same -- but richer input)
  devil:          1000 tokens (focused on weak/contested decisions)
  review:         1000 tokens (focused on flagged areas)
  TOTAL:          6380 tokens

  SAVING: 2320 tokens (27% reduction)
  QUALITY: dramatically higher due to non-overlapping analysis
```

### Why Lenses Save Tokens

Three mechanisms:

1. **Shorter proposals.** Agents don't need to cover everything, so they write less. A security-only analysis is naturally shorter than a full proposal.

2. **Shorter critiques.** "Stay in your lane" means less text per critique. No security agent writing 200 tokens about architecture.

3. **Focused downstream.** `devil()` and `review()` know where the weak points are, so they don't waste tokens challenging strong decisions.

### Token Cost of Lens Features

| Feature | Token cost | Token saving | Net |
|---------|-----------|--------------|-----|
| Lens prompt injection | +60/agent | -300/agent (shorter output) | -240/agent |
| Scoped critique | +0 | -100/agent (shorter critique) | -100/agent |
| Labeled converge | +50 (labels) | -0 | +50 total |
| Focused devil | +0 | -500 (focused) | -500 total |
| Focused review | +0 | -200 (focused) | -200 total |
| **Total pride(3) → devil → review** | **+230** | **-2550** | **-2320** |

---

## 10. Lens Combinations & Anti-Patterns

### Recommended Combinations by Task Type

```
PAYMENT SYSTEMS:     arch + sec + data
AUTH/LOGIN:          sec + arch + dx
REST API:            arch + dx + perf
DATABASE MIGRATION:  data + perf + maint
FRONTEND:            dx + perf + maint
REFACTORING:         maint + arch + quick
INFRASTRUCTURE:      quick + sec + cost
PERFORMANCE FIX:     perf + arch + cost
NEW MICROSERVICE:    arch + sec + quick
COMPLIANCE FEATURE:  gdpr/hipaa + sec + data
```

### Anti-Patterns (combinations to avoid)

**1. All soft lenses**
```bash
# BAD: all three lenses are "quality of life" -- no hard technical analysis
lion '"Build API" -> pride(claude::dx, claude::maint, claude::test_lens)'
```
Problem: no one examines architecture, security, or performance. You get a pleasant, well-tested, well-documented API with potential architectural flaws and security holes.

**Fix:** Always include at least one "hard" lens (arch, sec, perf, data) alongside soft lenses.

**2. Redundant lenses**
```bash
# BAD: arch and maint overlap heavily on code structure
lion '"Refactor module" -> pride(claude::arch, claude::maint, claude::dx)'
```
Problem: architecture and maintainability both examine code structure and separation of concerns. You get ~50% overlap, defeating the purpose of lenses.

**Fix:** If using similar lenses, one should be a "hard" technical lens. Replace `maint` with `sec` or `perf`.

**3. Adversarial combination**
```bash
# CAREFUL: quick fundamentally conflicts with arch and sec
lion '"Build feature" -> pride(claude::arch, claude::sec, claude::quick)'
```
Not always bad -- the conflict produces valuable tension. The pragmatist challenges over-engineering, and the architects challenge corner-cutting. But the converge step needs to handle conflicts well.

**Recommendation:** This is actually a GOOD combination when you want deliberate tension. Just ensure the converge prompt knows how to resolve conflicts.

**4. Too many lenses**
```bash
# BAD: 6 lenses is too many -- diminishing returns + token explosion
lion '"Build API" -> pride(claude::arch, claude::sec, claude::perf, 
                           claude::dx, claude::maint, claude::data)'
```
Problem: 6 focused analyses need a synthesizer that can juggle 6 perspectives. Context becomes overwhelming.

**Rule: 2-4 lenses is the sweet spot.** 3 is optimal for most tasks.

### The Golden Trio

For most backend tasks, this combination covers the critical dimensions with minimal overlap:

```bash
lion '"Build feature" -> pride(claude::arch, claude::sec, codex::quick)'
```

- `arch` ensures the design is solid
- `sec` ensures it's safe
- `quick` ensures it actually ships

The tension between `quick` and the other two produces healthy pushback against over-engineering while maintaining quality.

---

## 11. Implementation Guide

### Phase 1: Core Lens System (build first)

1. **Create the Lens dataclass and built-in lens definitions**
2. **Parse `::` syntax in the pipeline parser**
3. **Modify propose prompts to inject lens instructions**
4. **Modify critique prompts to scope to own lens**
5. **Modify converge prompt to handle labeled perspectives**

Estimated effort: 3-4 hours. This is mostly prompt engineering + parser changes.

### Phase 2: Auto-Assignment

1. **Implement keyword-to-lens mapping**
2. **Implement model-lens affinity matching**
3. **Add `lenses: auto` syntax parsing**

Estimated effort: 1-2 hours.

### Phase 3: Custom Lenses

1. **Add `lion lens <shortcode> <prompt>` CLI command**
2. **Store custom lenses in `~/.lion/lenses/custom.json`**
3. **Load custom lenses alongside built-ins**

Estimated effort: 1-2 hours.

### Phase 4: Integration with Context Packages

1. **Extend ContextPackage with lens fields**
2. **Modify context parser to extract lens metadata**
3. **Modify distill() to preserve lens labels**
4. **Modify devil/review prompts to use lens information**

Estimated effort: 2-3 hours. Depends on Layer 2 being implemented first.

### Phase 5: AI-Generated Lenses

1. **Add `lion lens-generate <description>` command**
2. **Build generation prompt**
3. **Validation and storage**

Estimated effort: 1 hour.

### Recommended Build Order

```
Phase 1: Core Lens System       ← Start here. Biggest impact.
Phase 2: Auto-Assignment        ← Quick win after Phase 1.
Phase 3: Custom Lenses          ← Enables domain-specific use.
Phase 4: Context Integration    ← Maximum power when combined with Layer 2.
Phase 5: AI-Generated Lenses    ← Polish. Nice to have.
```

### Parser Changes

The `::` operator needs to be recognized in the pipeline parser:

```python
# Current: pride(3) or pride(claude, gemini)
# New: pride(claude::arch, gemini::sec, codex::quick)
# New: pride(3, lenses: auto)

import re

def parse_pride_args(args_str: str) -> dict:
    """Parse pride() arguments including lens syntax."""
    
    # Check for lenses: auto
    if "lenses:" in args_str or "lenses :" in args_str:
        auto_match = re.search(r'lenses\s*:\s*(\w+)', args_str)
        n_match = re.search(r'(\d+)', args_str)
        return {
            "n_agents": int(n_match.group(1)) if n_match else 3,
            "lens_mode": auto_match.group(1) if auto_match else "auto",
            "agents": [],
        }
    
    # Check for provider::lens syntax
    agents = []
    parts = [p.strip() for p in args_str.split(",")]
    
    for part in parts:
        if "::" in part:
            provider, lens = part.split("::", 1)
            agents.append({"provider": provider.strip(), "lens": lens.strip()})
        elif part.strip().isdigit():
            # Just a number: pride(3)
            return {
                "n_agents": int(part.strip()),
                "lens_mode": None,
                "agents": [],
            }
        else:
            # Provider without lens: pride(claude, gemini)
            agents.append({"provider": part.strip(), "lens": None})
    
    return {
        "n_agents": len(agents),
        "lens_mode": "explicit",
        "agents": agents,
    }
```

---

## 12. File Structure

```
~/.lion/
├── lenses/
│   ├── __init__.py
│   ├── builtin.py          # Built-in lens definitions (arch, sec, perf, etc.)
│   ├── loader.py           # Load built-in + custom lenses
│   ├── custom.json         # User-defined custom lenses
│   ├── auto_assign.py      # Task-to-lens auto-assignment logic
│   └── affinity.py         # Model-lens affinity matching
│
├── context/                # (from Layer 2)
│   ├── package.py          # Extended with LensedContextPackage
│   ├── parser.py           # Extended to parse lens output sections
│   └── ...
│
├── prompts/
│   ├── propose_lensed.txt  # Propose prompt template with lens injection point
│   ├── critique_lensed.txt # Critique prompt scoped to agent's lens
│   ├── converge_lensed.txt # Converge prompt handling multiple perspectives
│   └── ...
│
└── pipeline/
    └── parser.py           # Extended to parse :: syntax
```

---

## Appendix A: Quick Reference

```
SYNTAX:
  provider::lens          # Apply a lens to a provider
  pride(3, lenses: auto)  # Auto-assign lenses based on task

BUILT-IN LENSES:
  arch       Architecture & design
  sec        Security
  perf       Performance
  quick      Pragmatic / ship fast
  maint      Maintainability
  dx         Developer experience
  data       Data integrity
  cost       Cost awareness
  test_lens  Testability

CUSTOM LENSES:
  lion lens <shortcode> "<focus instructions>"
  lion lens-generate "<domain description>"

RECOMMENDED COMBOS:
  Payment:   arch + sec + data
  Auth:      sec + arch + dx
  API:       arch + dx + perf
  Database:  data + perf + maint
  Frontend:  dx + perf + maint
  Default:   arch + sec + quick

TOKEN IMPACT:
  -27% fewer tokens than unlensed pride
  +125% more unique information per token
  2-4 lenses is the sweet spot (3 optimal)
```

## Appendix B: The Full Picture

```
lion '"Build Stripe payments" -> context() -> pride(claude::arch, claude::sec, codex::quick) -> distill() -> devil() -> review()'

Step 1: context()
  → Scans codebase, produces shared mental model (800 tokens)

Step 2: pride(claude::arch, claude::sec, codex::quick)
  → Agent 1 (arch): deep architecture analysis (~500 tokens)
  → Agent 2 (sec): deep security analysis (~400 tokens)
  → Agent 3 (quick): pragmatic path analysis (~350 tokens)
  → Cross-lens critique: each reviews others through own lens
  → Converge: synthesizes 3 complementary perspectives
  → Output: labeled decisions with confidence + lens support

Step 3: distill()
  → Compresses pride output, preserves lens labels
  → "STRONG (arch+sec): Stripe Checkout. MODERATE (arch vs quick): 
     repository pattern. WEAK: rate limiting strategy unresolved."

Step 4: devil()
  → Reads lens labels, targets MODERATE and WEAK decisions
  → "The repository pattern debate is unresolved. Also, your
     rate limiting gap is a real risk. Here's what to do."

Step 5: review()
  → Focuses on areas flagged by devil and lens warnings
  → Final quality check on the actual code

Result: Code that is architecturally sound (arch), secure (sec),
  and pragmatically shipped (quick) -- because each dimension
  had a dedicated agent that went DEEP instead of BROAD.
```

---

*Lenses transform Lion from "three agents having the same conversation" to "three specialists collaborating on different dimensions of the same problem." The difference is a brainstorming meeting where everyone talks over each other versus a design review where the architect, security engineer, and PM each bring their unique expertise.*

*Built for Lion by Menno Sijben, 2026.*