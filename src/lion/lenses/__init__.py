"""Lens System for focused multi-agent deliberation.

A lens steers agent attention to a specific dimension (architecture, security,
performance, etc.) rather than having all agents examine everything broadly.
This produces deeper, non-overlapping analyses with less token waste.

Usage:
    provider::lens          # Apply a lens to a provider
    pride(3, lenses: auto)  # Auto-assign lenses based on task
"""

from dataclasses import dataclass


@dataclass
class Lens:
    """A focused perspective that steers agent attention."""

    name: str  # Full name: "Architecture"
    shortcode: str  # CLI shortcode: "arch"
    prompt_inject: str  # Injected into propose prompt
    critique_inject: str  # Injected into critique prompt
    best_models: list[str]  # Which LLMs work best with this lens
    token_overhead: int  # Approximate extra tokens in prompt


# Built-in lens definitions
LENSES: dict[str, Lens] = {}


def _register(lens: Lens) -> Lens:
    """Register a lens by both shortcode and full name."""
    LENSES[lens.shortcode] = lens
    LENSES[lens.name.lower()] = lens
    return lens


# Architecture lens
arch = _register(
    Lens(
        name="Architecture",
        shortcode="arch",
        prompt_inject="""YOUR LENS: Architecture & Design
Focus ONLY on: system design, separation of concerns, dependency
direction, interface boundaries, module cohesion, and scaling patterns.

SEVERITY FILTER: Only report issues that would cause REAL problems --
bugs, runtime failures, data loss, or blocking scaling to 10x users.
Do NOT report theoretical purity issues like "should use a port/protocol"
or "dependency direction could be cleaner" unless it actively prevents
the code from working or being extended for a concrete requirement.
A working monolith is fine. Imperfect module boundaries are fine.
Only flag architecture that is genuinely broken or blocking.

IGNORE: variable naming, code style, test coverage, security specifics,
and implementation details. If the architecture works and can be
reasonably extended, say it's sound.

Go deep on real problems. Skip theoretical improvements.""",
        critique_inject="""Review other proposals ONLY from an architecture perspective.
Does their approach have clean boundaries? Will it scale? Are dependencies pointing
the right direction? Do NOT critique their security or style choices.""",
        best_models=["claude", "gemini"],
        token_overhead=60,
    )
)

# Security lens
sec = _register(
    Lens(
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
)

# Performance lens
perf = _register(
    Lens(
        name="Performance",
        shortcode="perf",
        prompt_inject="""YOUR LENS: Performance
Focus ONLY on: time complexity, database query efficiency (N+1 queries,
missing indexes, full table scans), memory allocation, caching opportunities,
connection pooling, and scaling bottlenecks.

SEVERITY FILTER: Only report issues that would cause REAL performance
problems at realistic scale -- actual O(n^2) algorithms on large data,
actual memory leaks, actual missing indexes on frequently queried tables.
Do NOT report micro-optimizations like "list comprehension allocates
a temporary list" or "dict lookup could be O(1) instead of O(n) for n<100".
A few extra list scans over 10-50 items is fine. Small allocations are fine.
Only flag performance issues that would cause measurable user-facing
slowdowns or resource exhaustion at realistic production scale.

IGNORE: code readability, security, naming conventions, test coverage.
If the code is unreadable but fast, say it's fast.""",
        critique_inject="""Review other proposals ONLY for performance implications.
Will their architecture create bottlenecks? Are there unnecessary round trips?
What will break first under load?""",
        best_models=["claude", "gemini"],
        token_overhead=60,
    )
)

# Pragmatic / Ship Fast lens
quick = _register(
    Lens(
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
)

# Maintainability lens
maint = _register(
    Lens(
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
)

# Developer Experience lens
dx = _register(
    Lens(
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
)

# Data Integrity lens
data = _register(
    Lens(
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
)

# Cost Awareness lens
cost = _register(
    Lens(
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
)

# Testability lens
test_lens = _register(
    Lens(
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
)


def get_lens(name: str) -> Lens | None:
    """Get a lens by shortcode or full name (case-insensitive)."""
    return LENSES.get(name.lower())


def list_lenses() -> list[Lens]:
    """Return all unique built-in lenses."""
    seen = set()
    result = []
    for lens in LENSES.values():
        if lens.shortcode not in seen:
            seen.add(lens.shortcode)
            result.append(lens)
    return result


__all__ = [
    "Lens",
    "LENSES",
    "get_lens",
    "list_lenses",
    "arch",
    "sec",
    "perf",
    "quick",
    "maint",
    "dx",
    "data",
    "cost",
    "test_lens",
]
