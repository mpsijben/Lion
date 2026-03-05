# Lion -- Self-Healing Architecture & Pride/Impl Split

## Architecture Changes & New Features

This document describes implemented and ongoing changes to Lion based on analysis of the current codebase and architecture discussions. It covers the pride/impl split, self-healing steps, concurrency, session reuse, per-phase model selection, and smart LLM routing.

---

## 1. Pride/Impl Split

### Problem

Pride currently does two fundamentally different things in one function:

```
pride(3) = propose → critique → converge → implement
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^
           deliberation (thinking)           execution (building)
```

This makes it impossible to choose a different model for implementation, and it prevents composition -- you can't deliberate without building, or build without deliberating.

### Solution

Split pride into two functions:

- **`pride()`** -- pure deliberation: propose → critique → converge → produces a PLAN
- **`impl()`** -- execution: carries out the plan, writes files

```bash
# New: deliberation and building are separate steps
lion '"Build auth" -> pride(3) -> impl()'

# Deliberate with gemini (free), build with claude
lion '"Build auth" -> pride(gemini, gemini) -> impl(claude.sonnet)'

# Only produce a plan, don't build
lion '"Build auth" -> pride(3)'

# Build after devil feedback
lion '"Build auth" -> pride(3) -> devil(^) -> impl()'
```

### Impact on model selection

With the split, the ambiguity that arises from trying to put agents AND phases in the same args disappears:

```bash
# Args of pride = who THINKS (agents, horizontal)
pride(gemini, claude, codex)     # 3 different brains
pride(3)                          # 3x default model

# Args of impl = who BUILDS (model, singular)
impl()                            # default model
impl(claude.opus)                 # specific model
```

Two dimensions, two functions. No overlap, no ambiguity.

---

## 2. Self-Healing Steps: the `^` Operator

### Problem

The current feedback loop (`<->`) is inefficient:

```
# Current flow with <->
pride(3)  → propose/critique/converge/implement  [~13 LLM calls]
review()  → finds 3 critical issues              [1 LLM call]
pride(1)  → ENTIRE deliberation again            [~4 LLM calls]
review()  → checks again                         [1 LLM call]
                                         Total: ~19 LLM calls
```

Review already knows exactly what's wrong and what the fix should be. It's absurd to send that back to pride to redo the entire propose/critique/converge/implement cycle -- especially when it's just 1 agent.

### Solution

The `^` parameter on any analysis function means: "if you find issues, fix them yourself and verify."

```bash
review(^)          # find issues + fix them + verify
devil(^)           # challenge + fix criticals + verify
future(6m, ^)      # time-travel review + fix + verify
typecheck(^)       # type errors + fix + verify
lint(^)            # lint issues + fix + verify
```

It reads well visually in a pipeline -- you immediately see which steps self-heal:

```bash
lion '"Build auth" -> pride(3) -> impl() -> review(^) -> devil(^) -> test() -> pr()'
```

Internal flow of `review(^)`:

```
1. Analyze code                     [1 LLM call, provider.ask()]
2. Issues found?
   No  → done, continue pipeline
   Yes → Fix all issues directly    [1 LLM call, provider.implement()]
       → Verify own fixes           [1 LLM call, provider.ask()]
       → Still issues? Repeat (max 2 rounds)
                                     Total: 1-5 LLM calls
```

Compare with the old `<->` flow of ~19 calls. That's 4-5x less.

### `^` vs `<->`

The two operators are complementary:

```
^         self-heal: "I'll fix it myself"
<->       feedback: "someone else needs to redo this"
```

Rule of thumb: `^` for concrete code issues, `<->` for fundamental rethinking.

```bash
# Devil says "the entire architecture is wrong" → back to pride
lion '"Build auth" -> pride(3) -> impl() <-> devil()'

# Review finds "you're missing error handling in 3 functions" → fixes itself
lion '"Build auth" -> pride(3) -> impl() -> review(^)'
```

### Implementation

Every analysis function checks for `^` in its args:

```python
def execute_review(prompt, previous, step, memory, config, cwd, cost_manager=None):
    self_heal = "^" in (step.args or [])
    
    # Step 1: Analyze (as before)
    result = provider.ask(review_prompt, "", cwd)
    issues = _extract_issues(result.content)
    
    # Step 2: Self-heal if ^ and there are issues
    if self_heal and any(i["severity"] == "critical" for i in issues):
        fix_prompt = f"""Fix ALL issues found:\n{result.content}\n
Edit the files directly."""
        provider.implement(fix_prompt, cwd)
        
        # Step 3: Verify
        verify_result = provider.ask(review_prompt_for_updated_code, "", cwd)
        issues = _extract_issues(verify_result.content)
    
    return {"issues": issues, ...}
```

---

## 3. Concurrent Pipeline Operator: `=>`

### Problem

All pipeline steps currently run strictly sequentially. The next step waits until the previous one is 100% complete, even when that's not necessary.

### Solution

A new operator `=>` that means: "start as soon as there's enough output, without waiting."

```bash
# Sequential (current behavior): each step waits for the previous
lion '"Build auth" -> pride(3) -> impl() -> review() -> devil()'

# Concurrent: review and devil start as soon as impl writes files
lion '"Build auth" -> pride(3) -> impl() => review() => devil()'
```

### Semantics

```
->  "then"        Wait until previous step is fully complete
=>  "as soon as"  Start as soon as previous step has actionable output
```

The `=>` operator starts the next step as soon as the previous step has written files (for impl) or produced output (for other steps). Concretely:

```
impl() => review()
  impl writes files → review starts immediately with those files
  impl writes more files → review picks those up too

impl() => review() => devil()
  impl writes files → review AND devil start in parallel
  review and devil run independently of each other
```

### Rules

- `=>` after `impl()` -- starts as soon as first files are written
- `=>` after analysis steps (review, devil, future) -- those steps run in parallel
- `=>` after `pride()` -- starts as soon as the plan is ready (before execution)
- Steps after `=>` must not depend on each other's output (they're parallel)

### Examples

```bash
# Review and devil in parallel after implementation
lion '"Build API" -> pride(3) -> impl() => review(^) => devil(^)'

# Test and lint in parallel
lion '"Build API" -> pride(3) -> impl() => test() => lint() -> pr()'

# Everything sequential (explicit choice, some steps MUST be sequential)
lion '"Build API" -> pride(3) -> impl() -> review(^) -> test() -> pr()'
```

### Implementation

In the pipeline executor, steps after `=>` are grouped and run in parallel with `concurrent.futures.ThreadPoolExecutor`:

```python
# Parser recognizes => as concurrent delimiter
# Pipeline executor groups: [pride] -> [impl] => [review, devil] -> [pr]
#                            seq      seq       parallel            seq
```

---

## 4. Session Reuse with `--resume`

### Problem

Every `claude -p` call starts a new process, does authentication, and has to rediscover the entire codebase. For a `pride(3) -> impl() -> review()` pipeline, that's 10+ separate subprocess calls.

### Solution

Claude Code supports session reuse via `--resume`:

```python
# First call: capture the session_id
result = subprocess.run(
    ["claude", "-p", prompt, "--output-format", "json"],
    capture_output=True, text=True, cwd=cwd
)
data = json.loads(result.stdout)
session_id = data["session_id"]

# Subsequent calls: reuse session
result = subprocess.run(
    ["claude", "-p", next_prompt, "--resume", session_id,
     "--output-format", "json"],
    capture_output=True, text=True, cwd=cwd
)
```

### Strategy per pride phase

```
pride(3):
  propose_1 → claude -p (new, parallel)         # New: independent thinking
  propose_2 → claude -p (new, parallel)         # New: independent thinking
  propose_3 → claude -p (new, parallel)         # New: independent thinking
  critique   → claude -p (new or reuse lead)
  converge   → claude -p (new, save session_id)

impl():
  implement  → claude -p --resume session_id    # Reuse: already knows the plan

review(^):
  review     → claude -p --resume session_id    # Reuse: already knows all files
  fix        → claude -p --resume session_id    # Reuse: has full context
```

### Impact

- Propose calls remain separate sessions (cognitive diversity requires independent thinking)
- Converge → impl → review becomes one continuous session
- Saves context-building per call (codebase scan, file discovery)
- Runs on existing Pro/Max subscription, no extra API costs

### Provider changes

The `ClaudeProvider` gets session tracking:

```python
class ClaudeProvider(Provider):
    def __init__(self, model=None):
        super().__init__(model)
        self._session_id = None
    
    def ask(self, prompt, system_prompt="", cwd=".", resume=True):
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if resume and self._session_id:
            cmd.extend(["--resume", self._session_id])
        
        result = subprocess.run(cmd, ...)
        data = json.loads(result.stdout)
        self._session_id = data.get("session_id", self._session_id)
        return self._parse_output(result.stdout)
    
    def ask_fresh(self, prompt, system_prompt="", cwd="."):
        """New session, for parallel propose calls."""
        return self.ask(prompt, system_prompt, cwd, resume=False)
```

---

## 5. Per-Phase Model Selection via Profiles

### Problem (solved by pride/impl split)

The original challenge was: how do you select a different model per phase (propose, critique, converge, implement)? With the pride/impl split, the implement phase is already solved -- that's just `impl(claude.opus)`.

But within pride itself you still have propose, critique, and converge. For most users, profiles handle this cleanly.

### Profiles in config

```toml
# ~/.lion/config.toml

[profiles.cheap]
propose = "gemini.flash"
critique = "gemini.flash"
converge = "claude.haiku"

[profiles.balanced]
propose = "claude.haiku"
critique = "claude.haiku"
converge = "claude.sonnet"

[profiles.premium]
propose = "claude.sonnet"
critique = "claude.sonnet"
converge = "claude.sonnet"
```

Usage:

```bash
lion '"Build auth" -> pride(3) -> impl(claude.opus)' --profile cheap
# → propose+critique with gemini flash (free)
# → converge with claude haiku (cheap)
# → implement with claude opus (quality)
```

### Default profile

```toml
[general]
default_profile = "balanced"
```

### Interaction with explicit agents

When you specify explicit agents, that overrides the profile for deliberation phases:

```bash
# Profile is ignored for propose/critique, agents determine the model
pride(gemini, claude)  # gemini proposes as gemini, claude as claude
                        # converge: from profile (or first agent as fallback)
```

---

## 6. Smart LLM Routing: Gemini for Deliberation

### Rationale

The phases of a Lion pipeline have fundamentally different requirements:

| Phase | Requires | Best model | Cost |
|-------|----------|------------|------|
| propose | Creativity, broad knowledge | Gemini Flash / Haiku | Free / cheap |
| critique | Analytical ability | Gemini Flash / Haiku | Free / cheap |
| converge | Synthesis, decision-making | Sonnet | Medium |
| implement | Code writing, file editing | Sonnet / Opus | Expensive |
| review | Finding bugs | Haiku / Sonnet | Cheap |
| devil | Critical thinking | Sonnet | Medium |

### Optimal pipeline

```bash
lion '"Build payment system" -> pride(3) -> impl(claude.sonnet) -> review(^) -> devil() -> test() -> pr()' --profile cheap
```

With the `cheap` profile:

```
pride(3):
  propose × 3  → gemini.flash (free, parallel)
  critique × 3 → gemini.flash (free, parallel)
  converge     → claude.haiku (cheap)

impl():
  implement    → claude.sonnet (quality, with --resume from converge)

review(^):
  analyze      → claude.haiku (cheap, with --resume)
  fix          → claude.sonnet (quality, with --resume)

devil():
  challenge    → claude.haiku (cheap)

test():
  run tests    → subprocess, no LLM
  fix failures → claude.sonnet (if needed)
```

Gemini is free for 60 req/min and 1,000 req/day. That's more than enough for all deliberation.

### Gemini integration

Gemini CLI works identically to Claude CLI:

```bash
gemini -p "prompt" --output-format json
```

The existing `GeminiProvider` in `providers/gemini.py` needs to be extended with the same session reuse as the Claude provider.

---

## 7. Syntax Summary

### Operators

| Operator | Name | Meaning |
|----------|------|---------|
| `->` | Then | Sequential: wait until previous is complete |
| `=>` | As soon as | Concurrent: start as soon as previous has output |
| `<->` | Feedback | Send back to producer, re-deliberate |
| `<N->` | Feedback(N) | Same, with N agents in the re-run |

### Functions

| Function | Purpose | Args |
|----------|---------|------|
| `task(n)` | Split task into subtasks | n = max subtasks |
| `pride(n)` | Multi-agent deliberation (plan) | n = agents, or explicit providers |
| `pride(a, b)` | Deliberation with specific LLMs | provider names |
| `impl()` | Execute plan, write files | optional: model |
| `review()` | Code review (report only) | optional: model |
| `review(^)` | Code review + self-heal | self-heal mode |
| `devil()` | Challenge assumptions (report only) | optional: aggressive, model |
| `devil(^)` | Challenge + self-heal | self-heal mode |
| `test()` | Run tests + auto-fix | optional: nofix |
| `create_tests()` | Generate tests | optional: changed, filename |
| `lint()` | Linting + auto-fix | optional: nofix, specific linter |
| `typecheck()` | Type checking + auto-fix | optional: nofix, strict |
| `future(Nm)` | Time-travel review | N = months/years |
| `pr(branch)` | Create git branch + PR | optional: branch name |
| `audit()` | Security audit | available |
| `onboard()` | Onboarding documentation | available |

### Examples

```bash
# Simple task
lion '"Fix the typo in README"'

# Standard flow
lion '"Build Stripe checkout" -> pride(3) -> impl() -> review(^)'

# Maximum quality
lion '"Build auth" -> pride(5) -> impl(claude.opus) -> devil(^) -> review(^) -> test() -> pr()'

# Cheap: gemini deliberates, claude builds
lion '"Build API" -> pride(gemini, gemini, gemini) -> impl(claude.sonnet)'

# Concurrent review and devil
lion '"Build API" -> pride(3) -> impl() => review(^) => devil(^) -> test() -> pr()'

# Large task decomposition
lion '"Build e-commerce platform" -> task(5) -> pride(3) -> impl() -> test() -> pr()'

# Deliberate only, don't build
lion '"Should we use PostgreSQL or MongoDB?" -> pride(3) -> devil()'

# Feedback loop for fundamental architecture problems
lion '"Build auth" -> pride(3) -> impl() <-> devil() -> review(^) -> test() -> pr()'

# With profile
lion '"Build API" -> pride(3) -> impl() -> review(^)' --profile cheap
```

### Config

```toml
# ~/.lion/config.toml

[general]
default_profile = "balanced"
max_pride_size = 5
verbose = false

[providers]
default = "claude"

[profiles.cheap]
propose = "gemini.flash"
critique = "gemini.flash"
converge = "claude.haiku"

[profiles.balanced]
propose = "claude.haiku"
critique = "claude.haiku"
converge = "claude.sonnet"

[profiles.premium]
propose = "claude.sonnet"
critique = "claude.sonnet"
converge = "claude.sonnet"

[complexity]
high_signals = ["build", "create", "design", "architect", "migrate"]
low_signals = ["fix", "bug", "typo", "rename", "change"]
high_pipeline = "pride(3) -> impl() -> review(^)"
medium_pipeline = "pride(2) -> impl()"
low_pipeline = "impl()"
```

---

## 8. Implementation Order

### Phase 1: Pride/Impl split

1. Create `impl()` function in `functions/impl.py` (extract from current pride `_implement`)
2. Remove implement phase from `execute_pride`
3. Update `PRODUCER_FUNCTIONS` -- impl becomes the producer, not pride
4. Update all tests and documentation

### Phase 2: Self-healing (the `^` operator)

1. Add `^` parameter check to `execute_review`
2. After analysis: if `^` and issues → `provider.implement()` + verify
3. Same for `execute_devil`, `execute_future`, `lint`, `typecheck`
4. Update `_needs_refinement` to account for `^` mode

### Phase 3: Session reuse

1. Add `_session_id` tracking to `ClaudeProvider`
2. `ask_fresh()` for propose calls (new, parallel)
3. `ask()` with auto-resume for converge → impl → review chain
4. Pass session through pipeline context (not per-provider but per-run)

### Phase 4: Profiles

1. Parse `[profiles.*]` from config.toml
2. Add `--profile` CLI argument
3. `_resolve_agents` reads profile for per-phase model selection
4. Explicit agents override profile

### Phase 5: Concurrent operator `=>`

1. Extend parser: recognize `=>` as concurrent delimiter
2. Pipeline executor: group steps into sequential and parallel blocks
3. Execute parallel blocks with `ThreadPoolExecutor`
4. File-watching for `impl() => review()` trigger

### Phase 6: Gemini routing

1. Update `GeminiProvider` with session support
2. Default `cheap` profile with Gemini for deliberation
3. Test mixed pipelines: gemini propose + claude implement

---

## 9. Status

| Feature | Status |
|---------|--------|
| pride/impl split | Implemented |
| review(^) | Implemented |
| devil(^) | Implemented |
| Session reuse (--resume) | Implemented |
| Per-phase profiles | Implemented |
| `=>` concurrent operator | Implemented |
| Gemini for deliberation | Implemented |
| Custom patterns | Not yet built |
| Mixed LLMs (`claude`, `gemini`, `codex`) | Implemented |
| audit() | Implemented |
| onboard() | Implemented |

---

*This document describes the next iteration of Lion. Implementation follows the phases above -- each phase is independently deployable and testable.*
