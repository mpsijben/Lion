# Lion Syntax Reference

## Basics

```
lion "<prompt>" [-> function() [-> function() ...]]
```

**Note**: use single quotes to wrap the entire expression when using `->`, otherwise the shell interprets `>` as a redirect:

```bash
# Wrong - shell sees > as redirect:
lion "Build auth" -> pride(3)

# Correct - everything in single quotes:
lion '"Build auth" -> pride(3)'
```

Without a pipeline, Lion executes the task with a single agent:

```bash
lion '"Fix the login bug"'
```

---

## Model Selection

All functions that accept a provider support dot-syntax for model selection:

```bash
# Claude models
pride(claude)           # Default Claude model
pride(claude.haiku)     # Claude Haiku (cheapest, fastest)
pride(claude.sonnet)    # Claude Sonnet
pride(claude.opus)      # Claude Opus (most expensive, smartest)

# Gemini models
pride(gemini)           # Default Gemini model
pride(gemini.flash)     # Gemini Flash (cheap)
pride(gemini.pro)       # Gemini Pro

# Mixed models in a pride
pride(claude.haiku, claude.haiku, gemini.flash)  # 3 agents, mixed

# Model selection on other functions
review(claude.haiku)         # Cheap review
devil(claude.opus)           # Smartest devil's advocate
future(6m, gemini.flash)     # Cheap future review
task(5, claude.haiku)        # Cheap task decomposition
```

The config default can also specify a model:

```toml
[providers]
default = "claude.haiku"    # Always use haiku
```

---

## Pipeline Functions

Functions are chained with `->`. Each function receives the output of the previous one as input.

### Feedback Operator: `<->`

The `<->` operator creates a feedback loop: if a step finds issues, the last producer (e.g. pride) is re-run with the feedback as extra context. Then the feedback step is re-run to verify. Max 2 rounds.

```bash
# <-> = re-run producer with the SAME number of agents
lion '"Build auth" -> pride(5) <-> review()'

# <N-> = re-run producer with N agents (cheaper)
lion '"Build auth" -> pride(5) <1-> review()'

# Mix of operators
lion '"Build auth" -> pride(5) <1-> review() <-> devil() -> test() -> pr()'
```

Semantics:
- `<->` sends feedback back to the last producer (pride or test)
- The producer re-runs with the feedback + all previous deliberation context
- `<N->` specifies how many agents the re-run uses
- If the feedback step finds 0 issues: no re-run, pipeline continues normally

### task(n) -- Task Decomposition

Splits a large task into smaller, implementable subtasks. Each subtask runs through the rest of the pipeline independently.

```bash
lion '"Build e-commerce platform" -> task() -> pride(3) -> test()'      # Max 5 subtasks (default)
lion '"Build e-commerce platform" -> task(10) -> pride(3) -> test()'    # Max 10 subtasks
lion '"Build e-commerce platform" -> task(3) -> pride(3) -> test()'     # Max 3 subtasks
```

How it works:
1. AI analyzes the task and splits it into concrete subtasks
2. Subtasks are grouped by dependency (independent tasks can run in parallel)
3. Each subtask runs through everything after `task()` in the pipeline (e.g. `pride(3) -> test()`)

Ideal for:
- Large features spanning multiple components
- Tasks too big for a single pride() session
- Projects where you want structured progress tracking

### pride(n) -- Multi-Agent Deliberation

The heart of Lion. Starts N agents that independently propose an approach, critique each other's proposals, converge on a plan, and implement it.

```bash
lion '"Build auth system" -> pride(3)'                          # 3 agents (default provider)
lion '"Build auth system" -> pride(5)'                          # 5 agents (max 5)
lion '"Build auth system" -> pride(claude, gemini)'             # Mixed providers
lion '"Build auth system" -> pride(claude.haiku, claude.haiku)' # 2 haiku agents (cheap)
```

Internal phases:
1. **Propose** -- Each agent independently proposes an approach (parallel)
2. **Critique** -- Each agent critiques the other proposals (parallel)
3. **Converge** -- One agent synthesizes everything into a final plan
4. **Implement** -- The plan is built (writes files)

### fuse(n) -- Fast Deliberation

Runs a faster deliberation cycle than `pride()`:
1. Parallel propose
2. Lightweight cross-agent reaction
3. Final synthesis into a plan

```bash
lion '"Design auth architecture" -> fuse(3)'
lion '"Design auth architecture" -> fuse(claude, gemini, codex)'
```

### review() -- Code Review

Reviews code for bugs, style, performance, and edge cases.

```bash
lion '"Build API" -> pride(3) -> review()'
```

### test() -- Run Tests

Automatically detects the test framework (pytest, jest, vitest, mocha, go test, cargo test), runs the tests, and auto-fixes failing tests (max 3 attempts).

```bash
lion '"Build API" -> pride(3) -> test()'        # Run + auto-fix
lion '"Build API" -> pride(3) -> test(nofix)'   # Report only
```

### create_tests() -- Generate Tests

Forces test generation even if none exist. Analyzes code and creates comprehensive tests for all public functions/methods.

```bash
lion '"Build API" -> pride(3) -> create_tests()'          # Generate tests for everything
lion '"Build API" -> pride(3) -> create_tests(changed)'   # Only for changed files
lion '"Build API" -> pride(3) -> create_tests("api.py")'  # Specific file
```

Automatically generates:
- Unit tests for individual functions
- Edge cases (empty inputs, null values, boundaries)
- Error handling tests
- Happy path scenarios

### lint() -- Linting with Auto-Fix

Detects the linter (ruff, eslint, prettier, gofmt, rustfmt, etc.) and automatically fixes style issues.

```bash
lion '"Build API" -> pride(3) -> lint()'         # Auto-fix with detected linter
lion '"Build API" -> pride(3) -> lint(nofix)'    # Report only
lion '"Build API" -> pride(3) -> lint(ruff)'     # Specific linter
```

Supported linters per language:
- **Python**: ruff, black, flake8, pylint
- **TypeScript/JavaScript**: eslint, prettier, biome
- **Go**: gofmt, golangci-lint
- **Rust**: rustfmt, clippy

### typecheck() -- Type Checking

Runs the type checker (mypy, pyright, tsc, cargo check, go vet) and auto-fixes type errors with AI.

```bash
lion '"Build API" -> pride(3) -> typecheck()'          # Run + auto-fix
lion '"Build API" -> pride(3) -> typecheck(nofix)'     # Report only
lion '"Build API" -> pride(3) -> typecheck(strict)'    # Strict mode
```

Supported type checkers:
- **Python**: mypy, pyright
- **TypeScript**: tsc
- **Go**: go vet
- **Rust**: cargo check

### pr(branch) -- Create Pull Request

Creates a git branch, stages changes, generates a commit message via AI, and opens a PR via `gh` CLI.

```bash
lion '"Build API" -> pride(3) -> pr()'                          # Auto branch name
lion '"Build API" -> pride(3) -> pr("feature/stripe-checkout")' # Specific branch
```

### devil() -- Devil's Advocate

Challenges the consensus. Not about finding bugs (that's what review does), but challenging decisions, assumptions, and architecture choices.

```bash
lion '"Build payment system" -> pride(3) -> devil()'
lion '"Build payment system" -> pride(3) -> devil(aggressive)'  # Extra critical
lion '"Build payment system" -> pride(3) -> devil(gemini)'      # With specific provider
```

### future(Nm) -- Time-Travel Review

Evaluates code from the perspective of a developer N months in the future.

```bash
lion '"Build API" -> pride(3) -> future(6m)'           # 6 months
lion '"Build API" -> pride(3) -> future(1y)'           # 1 year
lion '"Build API" -> pride(3) -> future(6m, gemini)'   # With specific provider
```

### audit() -- Security Audit

OWASP top 10 check, dependency analysis, attack surface review.

```bash
lion '"Build auth" -> pride(3) -> audit()'
```

### onboard() -- Documentation

Generates onboarding documentation as if a new team member starts tomorrow.

```bash
lion '"Build feature" -> pride(3) -> onboard()'
```

---

## Available Lenses

Lenses steer agent attention. Use `::` syntax:

```bash
pride(claude::sec, gemini::arch, codex::quick)
```

| Lens | Full Name | Focus |
|------|-----------|-------|
| `sec` | security | Injection, auth, crypto, secrets |
| `arch` | architecture | Coupling, patterns, SOLID |
| `perf` | performance | N+1, memory, connection pooling |
| `quick` | pragmatic | Ship fast, minimal viable |
| `maint` | maintainability | Complexity, duplication |
| `dx` | developer experience | Naming, readability, docs |
| `data` | data integrity | Validation, consistency |
| `cost` | cost awareness | API calls, compute |
| `test_lens` | testability | Dependencies, interfaces |

---

## Examples

### Simple task (no pipeline)
```bash
lion '"Fix the typo in README"'
```

### Standard development flow
```bash
lion '"Build Stripe checkout" -> pride(3) -> review()'
```

### Full pipeline
```bash
lion '"Build payment system" -> pride(3) -> review() -> test() -> pr("feature/payments")'
```

### Small task with 2 agents
```bash
lion '"Refactor the API routes" -> pride(2)'
```

### Maximum quality
```bash
lion '"Build auth system" -> pride(5) -> devil() -> review() -> test() -> pr("feature/auth")'
```

### With feedback loops
```bash
lion '"Build auth system" -> pride(5) <1-> review() <-> devil() -> test() -> pr()'
```

### With test generation
```bash
lion '"Build payment API" -> pride(3) -> create_tests() -> test() -> pr()'
```

### Code quality pipeline
```bash
lion '"Refactor user module" -> pride(3) -> lint() -> typecheck() -> review()'
```

### Full quality pipeline
```bash
lion '"Build checkout flow" -> pride(3) -> create_tests() -> test() -> lint() -> typecheck() -> review() -> pr()'
```

### Split large tasks
```bash
lion '"Build e-commerce platform" -> task(5) -> pride(3) -> test() -> pr()'
```

---

## Custom Patterns (planned)

Save frequently used pipelines as reusable patterns:

```bash
lion pattern ship = -> pride(3) -> review() -> test() -> pr()
lion '"Build feature X" -> ship()'
```

---

## Configuration

Configuration in `~/.lion/config.toml`:

```toml
[providers]
default = "claude"

[complexity]
high_signals = ["build", "create", "design", "architect", "migrate"]
low_signals = ["fix", "bug", "typo", "rename", "change"]
high_pipeline = "pride(3)"
medium_pipeline = "pride(2)"
low_pipeline = ""
```

---

## Current Status

| Function | Status |
|----------|--------|
| task(n) | Working |
| pride(n) | Working |
| fuse(n) | Working |
| review() | Working |
| test() | Working |
| create_tests() | Working |
| lint() | Working |
| typecheck() | Working |
| pr(branch) | Working |
| devil() | Working |
| future(Nm) | Working |
| `<->` / `<N->` | Working |
| audit() | Working |
| onboard() | Working |
| Custom patterns | Not yet built |
| Mixed LLMs (`claude`, `gemini`, `codex`) | Working |
