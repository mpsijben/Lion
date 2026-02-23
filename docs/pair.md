# Lion -- Fuse, Pair & Multi-Swarm: Real-Time Agent Collaboration

## The Problem: Sequential Agents & Cascading Hallucinations

Every multi-agent framework today works like a 1990s corporate bureaucracy. Agent A writes 100 lines of code, stops, passes the baton to Agent B for review. Agent B writes a critique. Agent A rewrites everything. This is AutoGen. This is CrewAI. This is LangGraph.

The fundamental flaw: **if Agent A makes an architectural error on line 5, it still generates the remaining 95 lines before anyone notices.** Errors don't stay contained -- they cascade. The wrong database choice on line 5 leads to wrong schema on line 20, wrong queries on line 40, wrong error handling on line 60. By the time a reviewer sees it, the entire file is built on a broken foundation.

This is **Cascading Hallucinations**: errors that compound because feedback arrives too late.

```
pride(3) → impl() → review(^) → devil(^)

  propose × 3      [30s]    think, think, think
  critique × 3     [25s]    read everything, respond, read everything, respond
  converge         [20s]    synthesize everything
  implement        [60s]    build the whole thing ← errors compound here
  review           [15s]    find issues AFTER 60 seconds of building on them
  devil            [15s]    challenge AFTER everything is written
                   ═════
                   ~165 seconds
```

The temptation is to solve this by adding management layers -- a "tech lead" agent that reviews plans, a "project manager" agent that coordinates, a "QA" agent that validates. But AI agents don't have egos, don't need meetings to align, and can process vast amounts of context instantly. **Management is wasted tokens. Pure, real-time engineering collaboration is the solution.**

## What Lion Actually Is

Lion is not a "multi-agent framework". There are plenty of those.

**Lion is a streaming-aware, interrupt-driven, process-level LLM scheduler.**

The distinction matters. Most agent frameworks operate at the *prompt orchestration layer* -- they compose messages, chain API calls, and pass results between agents. They treat LLMs as functions: input → output → next function.

Lion operates at the *process orchestration layer*. It treats LLMs as **OS processes that can be scheduled, interrupted, killed, and resumed**. This is a systems-engineering perspective, not a prompt-engineering one.

The core mechanism: `subprocess.Popen` → stream interception → `terminate()` → `--resume`. That's process control, not prompt chaining.

**What this enables that prompt orchestration cannot:**

LLM generation is inherently **open loop** -- the model generates tokens sequentially with no external feedback until it finishes. Every framework that reviews output after generation accepts this. They add a review step, get feedback, regenerate. That's still open loop with a retry.

Lion turns LLM generation into a **closed loop control system**. The output stream is continuously monitored by observer processes (eyes). When the output deviates from acceptable parameters (security flaw, architectural mistake), a control signal fires (interrupt), the process adjusts (correction via resume), and generation continues on the corrected trajectory. Real-time feedback, not post-hoc retry.

```
Open loop (every other framework):
  prompt → [generate 200 lines] → review → "line 10 was wrong" → regenerate

Closed loop (Lion):
  prompt → [generate line 10] → eye detects deviation → interrupt → correct → [continue from line 11]
```

The difference: in open loop, the model builds 190 lines on a broken foundation before anyone notices. In closed loop, the error is caught at line 10 and corrected at line 12.

### Honest Positioning

**Is this idea conceptually unique?** No. Real-time feedback loops, multi-agent review, and stream interruption exist as concepts. Google's ADK blog describes "interruptibility" in streaming agents. AgentAsk (2025) formalizes edge-level intervention to prevent cascading errors.

**Is this implementation unique?** Yes. Nobody has productized this at the process level -- using CLI terminate + resume with session persistence, cross-model eyes on flat-rate subscriptions, and dynamic leader election (mutiny) where the observer becomes the writer. The existing multi-CLI tools (Claude Code Bridge, Claude Octopus, Claude-Code-Workflow) all operate turn-based or in parallel-but-independent modes. None do mid-generation stream interception with interrupt.

**The defensible claim is not "nobody thought of this" -- it's "nobody built this at the process level and shipped it."**

### When Lion Adds Value (and When It Doesn't)

**Lion's `pair()` is valuable when:**
- Tasks generate > ~300 lines (enough surface for cascading errors)
- Errors have high impact (security, infrastructure, payment logic)
- You're on flat-rate CLI subscriptions (interrupts cost €0)
- You can measure quality improvement vs baseline

**Lion's `pair()` is probably overkill for:**
- Small functions (< 50 lines)
- Snippets and prototyping
- Tasks where speed matters more than correctness
- Quick-and-dirty exploration

### Known Risks

Three risks that the POC must address with data:

**1. Interrupt cost > cascade cost.** If the eyes generate too many false positives, every interrupt adds latency (terminate → resume → restart) without improving quality. The net effect is slower output with the same number of bugs. The POC must measure false positive rate and compare total time with vs without eyes.

**2. Resume drift.** `--resume` preserves the session, but models may subtly lose coherence after multiple interrupt/resume cycles. After 5+ interrupts, the model might start repeating itself, contradicting earlier code, or losing track of the overall architecture. The POC must test stability across 1, 3, 5, and 10+ interrupts in a single session.

**3. Latency stacking.** Streaming + eye check + terminate + resume can accumulate latency that exceeds the cost of just letting the model finish and doing a post-hoc review + regeneration. For short tasks, the overhead of the control loop may exceed the cost of the cascade. The POC must measure wall-clock time for pair() vs solo + review and find the break-even task size.

## The Insight: Real Mob Programming

Watch a mob programming session. Five developers, one screen. The driver types, the navigators watch in real-time. Someone says "wait, that's not safe" *as the code is being written*. The driver adjusts immediately. No wasted work. No separate review phase. No 60 seconds of building on a mistake.

What if agents could work the same way?

## Two New Primitives

### `pair()` -- Live Pair Programming (Stream Interruption)

One Lead Agent implements code while multiple "Eye" Agents watch the output stream in real-time. If an Eye spots an issue, it triggers a **hard interrupt**, stopping the Lead mid-sentence, injecting the correction, and forcing an immediate pivot.

```
pair(claude.opus, eyes: sec+arch+perf):

  LEAD (claude.opus) streams code...
  ┃
  ┃  "class AuthController:"
  ┃  "  def login(self, request):"
  ┃  "    password = request.body['password']"
  ┃         ▲
  ┃         │ HARD INTERRUPT (security eye)
  ┃         │ "Never use plaintext passwords. Use bcrypt hashing."
  ┃
  ┃  "    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())"
  ┃  "    token = jwt.encode({'user_id': user.id}, SECRET)"
  ┃         ▲
  ┃         │ HARD INTERRUPT (security eye)
  ┃         │ "Add token expiry. Use RS256 not HS256 for production."
  ┃
  ┃  "    db.execute('SELECT * FROM users WHERE email=' + email)"
  ┃         ▲
  ┃         │ HARD INTERRUPT (architecture eye)
  ┃         │ "SQL injection. Use parameterized queries."
  ┃
  ┃  ... lead finishes file ...
  ┃
  ┃  Output: code that was reviewed WHILE being written.
  ┃  Cascading hallucinations caught at line 5, not line 95.
```

Each eye has a **lens** -- a focused domain of expertise:

| Eye | Lens | Watches for |
|-----|------|-------------|
| `sec` | Security | Auth flaws, injection, plaintext secrets, missing validation |
| `arch` | Architecture | Coupling, patterns, separation of concerns, SOLID violations |
| `perf` | Performance | N+1 queries, missing indexes, memory leaks, connection pooling |
| `test` | Testability | Untestable code, missing interfaces, hard dependencies |

**Eyes don't just critique -- they research.** When the security eye sees JWT usage, it can spawn a subagent to check current best practices and inject findings into the lead's stream. This is the **lead-listener pattern**: asymmetric enrichment via background research + interrupt.

```bash
# Pair programming with 2 eyes
lion '"Build auth" -> pair(claude.opus, eyes: sec+arch)'

# Cheap eyes, expensive lead
lion '"Build API" -> pair(claude.opus, eyes: sec.haiku+arch.haiku+perf.haiku)'
```

### `fuse(n)` -- Real-Time Deliberation

Replaces `pride(n)` for architectural planning. Instead of sequential propose → critique → converge rounds, `n` agents deliberate simultaneously, each seeing the others' partial output as it streams.

```
pride(3) -- sequential rounds:                    fuse(3) -- real-time:
  Agent A proposes        [10s]                    Agent A ──stream──▶
  Agent B proposes        [10s]                    Agent B ──stream──▶  all see each other
  Agent C proposes        [10s]                    Agent C ──stream──▶
  Agent A critiques all   [8s]                     ════════════════════
  Agent B critiques all   [8s]                     converged plan
  Agent C critiques all   [8s]
  Converger synthesizes   [20s]
  ═══════════════════════════════
  Total: ~74 seconds                               Total: ~30 seconds
```

How it works:

1. All agents start streaming their approach simultaneously
2. Every ~100 tokens, LION injects each agent's partial output into the others' streams
3. Agents dynamically react to peers -- agreeing, disagreeing, expanding -- mid-thought
4. Convergence happens organically within the stream, not as a separate phase
5. ~30 seconds, compared to ~74 seconds in sequential setups

This is validated by the **Group Think paper** (MediaTek, May 2025): token-level collaboration between concurrent reasoning threads yields **4× latency reduction** and **improved accuracy** -- even with models not specifically trained for collaboration.

```bash
# Fuse replaces pride for deliberation
lion '"Build payment system" -> fuse(3) -> impl()'

# With explicit models: mix cheap and expensive thinkers
lion '"Build auth" -> fuse(claude, gemini, claude) -> impl()'
```

## The Killer Combo: `fuse() → pair()`

For tasks that genuinely need architectural deliberation before building:

```bash
lion '"Build payment system" -> fuse(3) -> pair(claude.opus, eyes: sec+arch+perf)'
```

```
fuse(3):                                           [~30 sec]
  3 agents deliberate in real-time
  Agent A: "We should use Stripe's PaymentIntents API--"
  Agent B: "Agreed, but we need idempotency keys for--"
  Agent C: "And webhook verification, not polling--"
  → converged plan emerges from the stream

  ↓ plan flows into pair()

pair(claude.opus, eyes: sec+arch+perf):            [~60 sec]
  lead implements the plan
  security eye catches missing HMAC verification
  architecture eye suggests extracting a PaymentGateway interface
  performance eye flags synchronous webhook processing
  → code is reviewed AS it's written
                                                   ═════════
                                           Total:  ~90 seconds
```

But for most tasks, you don't need fuse() at all. pair() alone handles it:

```
"Build auth endpoint" → pair(claude, eyes: sec+arch):

  pair() alone:                                     [~44 sec]
    lead starts building, eyes watch
    architecture eye nudges toward bcrypt at line 5
    security eye catches missing rate limiting at line 30
    → correct code, no plan phase needed
                                                    ═════════
                                            Total:  ~44 seconds

  vs traditional fuse() → pair():                   [~90 sec]
    30 seconds of deliberation about something obvious
    + 60 seconds of building
    → same quality, 2× slower

  vs old sequential model:                          [~165 sec]
    plan [75s] → build [60s] → review [15s] → fix [15s]
    → same quality, 4× slower
```

## The Avengers Setup: Asymmetric Multi-LLM Synergy

Running 5 instances of Claude Opus simultaneously is absurdly expensive. `pair()` is designed for **asymmetric cost allocation**:

- **The Lead (The Builder):** A highly capable, expensive model (e.g., `claude.opus` or `claude.sonnet`) does the heavy lifting of writing complex, architecturally sound code.
- **The Eyes (The Watchers):** Hyper-fast, cheap, or free models (e.g., `gemini.flash`, `claude.haiku`, or a local `ollama` model) run as background listeners.

You get the architectural brilliance of Opus, safeguarded by the real-time, low-cost vigilance of Haiku and Gemini Flash.

```bash
# The Avengers: expensive lead, free/cheap eyes
lion '"Build payment system" -> pair(claude.opus, eyes: sec.gemini+arch.haiku+perf.gemini)'
```

**Cost model:** Eyes read a lot (consuming input tokens) but generate little (short findings). The lead generates all the code. Total cost is dominated by the lead -- eyes add ~10-20% overhead. With Gemini Flash's free tier (60 req/min, 1000/day), eyes can be literally free.

## From Single Task to Multi-Swarm Orchestrator

### The Problem: Context Bloat

Putting 10 agents on one task doesn't scale. Every agent needs to read everything every other agent has written. Context grows quadratically. Models lose focus. Quality drops.

### The Solution: Micro-Swarms (Pods)

Instead of one giant team, LION acts as a **Multi-Swarm Orchestrator** -- Kubernetes for AI agents.

When given an epic task, LION breaks it down using `task()` and spawns isolated micro-swarms. Each swarm is a small `pair()` unit (1 Lead + 2-3 Eyes) dedicated to a single feature.

```bash
# LION splits the epic into subtasks, each gets its own swarm
lion '"Build E-Commerce Platform" -> task(5) -> fuse(3) -> pair(claude.opus, eyes: sec+arch)'
```

Under the hood:

```
task(5) decomposes into:
  ├── Subtask 1: "Shopping Cart"
  ├── Subtask 2: "Auth System"
  ├── Subtask 3: "Payment Integration"
  ├── Subtask 4: "Product Catalog"
  └── Subtask 5: "Order Management"

Each subtask spawns a micro-swarm (Pod):

  Pod 1: pair(claude.sonnet, eyes: perf+arch)  → Shopping Cart
  Pod 2: pair(claude.sonnet, eyes: sec+arch)   → Auth System
  Pod 3: pair(claude.sonnet, eyes: sec+perf)   → Payment Integration
  Pod 4: pair(claude.sonnet, eyes: arch)        → Product Catalog
  Pod 5: pair(claude.sonnet, eyes: arch+perf)   → Order Management

  All 5 pods run in parallel.
```

Notice: each pod gets eyes relevant to its domain. Payment gets security + performance. Auth gets security + architecture. Cart gets performance + architecture. LION selects eyes based on subtask classification.

### The Secret Weapon: Parallel Git Worktrees

How do 5 swarms work on the same codebase simultaneously without overwriting each other's files or causing lock crashes?

**Git worktrees.**

```
main repo: /home/user/project/
  │
  ├── worktree: /tmp/lion-cart/     ← Pod 1 operates here
  ├── worktree: /tmp/lion-auth/     ← Pod 2 operates here
  ├── worktree: /tmp/lion-payment/  ← Pod 3 operates here
  ├── worktree: /tmp/lion-catalog/  ← Pod 4 operates here
  └── worktree: /tmp/lion-orders/   ← Pod 5 operates here
```

Each worktree is a real, full checkout of the repo on its own branch. Complete filesystem isolation. No file locks. No merge conflicts during development.

The flow:

1. `task()` decomposes the epic into subtasks
2. LION creates a temporary Git worktree per subtask (`git worktree add /tmp/lion-cart -b feature/cart`)
3. Each pod runs its `pair()` session exclusively in its worktree
4. All pods execute in parallel at maximum speed, in total isolation
5. Upon completion, LION runs automated tests in each worktree
6. If tests pass, LION merges worktree branches back into main (`git merge feature/cart`)
7. If merge conflicts arise, a dedicated `resolve()` agent handles them
8. Worktrees are cleaned up (`git worktree remove`)

```python
async def execute_multi_swarm(task: str, n_subtasks: int, lead_model: str):
    # Decompose task
    subtasks = await decompose_task(task, n_subtasks)
    
    # Provision worktrees
    worktrees = []
    for subtask in subtasks:
        branch = f"feature/{slugify(subtask.name)}"
        path = f"/tmp/lion-{slugify(subtask.name)}"
        run(f"git worktree add {path} -b {branch}")
        worktrees.append(WorkTree(path=path, branch=branch, subtask=subtask))
    
    # Spawn pods in parallel
    async with TaskGroup() as group:
        for wt in worktrees:
            eyes = select_eyes_for_subtask(wt.subtask)
            group.create_task(
                execute_pair(wt.subtask.description, lead_model, eyes, cwd=wt.path)
            )
    
    # Test and merge
    for wt in worktrees:
        test_result = run(f"cd {wt.path} && lion test()")
        if test_result.passed:
            run(f"git merge {wt.branch}")
        else:
            await fix_and_retry(wt)
        run(f"git worktree remove {wt.path}")
```

This is Kubernetes for AI agents: LION is the orchestrator, worktrees are pods, `pair()` sessions are containers, branches are namespaces.

## Why the Plan Phase Can Disappear

Traditional agent workflows front-load a heavy planning phase: multiple agents deliberate, critique, converge on an architecture -- *before a single line of code is written*. This takes 30-60 seconds and consumes 3+ CLI calls (which eat into your daily quota).

Why do they do this? Because without a plan, the implementation agent might pick the wrong approach and waste 200 lines of code. The plan is a **preemptive insurance policy against cascade**.

But with `pair()`, the eyes *are* the insurance. If the lead starts building the wrong architecture, the architecture eye catches it at line 10-20, not line 200. The cost of a wrong start is 10 lines + one interrupt (~2 seconds), not 200 lines + full review + full rewrite (~40+ seconds).

This changes the economics fundamentally:

```
Traditional (with plan):
  fuse(3) plan      [30-60s]  ← 3 CLI calls, insurance against bad architecture
  implement         [40s]
  review            [15s]
  rewrite           [20s]
                    ═════
                    ~105-135s, 5+ CLI calls from your daily quota

pair() without plan:
  pair(claude, eyes: sec+arch)  [44s]  ← eyes catch bad architecture live
                                ═════
                                ~44s, 1 lead + parallel eye calls

Savings: ~60-90 seconds AND 3+ fewer CLI calls against quota
```

The plan phase doesn't just cost time -- it costs quota. On Claude Max, Gemini Code Assist, and Codex subscriptions, you have daily request limits. Three agents deliberating burns three requests *before you start building*. With pair(), the eyes run as lightweight checks against the streaming output -- typically cheaper on quota than full deliberation sessions.

**When you still need a plan:**

The plan is not always unnecessary. For tasks where the wrong *fundamental* choice wastes everything (microservices vs monolith, SQL vs NoSQL, REST vs GraphQL), you need to deliberate before building. The eyes can't save you from choosing the wrong database -- they can only catch issues within the chosen architecture.

| Task | Pipeline | Why |
|------|----------|-----|
| "Fix the login bug" | `impl()` | Obvious what to do |
| "Build auth endpoint" | `pair(eyes: sec+arch)` | Pattern is known, eyes catch edge cases |
| "Add Stripe integration" | `pair(eyes: sec+perf)` | Standard integration, eyes catch payment gotchas |
| "Build e-commerce platform" | `fuse(3) -> task(5) -> pair()` | Needs architecture + parallel execution |
| "Migrate MongoDB to Postgres" | `fuse(3) -> pair(eyes: arch+perf)` | Needs strategy before touching code |

**The rule of thumb: if the wrong architectural choice wastes the entire implementation, deliberate first. Otherwise, just build with eyes.** For ~80% of tasks, `pair()` alone is enough. `fuse()` is for the ~20% where you genuinely need to think before building. `task()` is for when the work is too big for a single swarm.

This means the threshold for "do I need a plan?" shifts upward. Tasks that previously needed planning (medium complexity, 100-300 lines) can now go straight to `pair()` because the eyes provide continuous course correction. Only truly architectural decisions still need `fuse()`.

## Three Speeds (Not Four)

With pair() absorbing most of the plan phase's job, the pipeline simplifies:

```bash
# Speed 1 -- Solo: small, obvious tasks
lion '"Fix the login bug"'
# Just impl(). No overhead. <50 lines, pattern is clear.

# Speed 2 -- Pair: most tasks (the new default)
lion '"Build auth" -> pair(claude, eyes: sec+arch)'
# Live pair programming. Eyes replace both plan AND review.
# 50-300 lines. Covers ~80% of real work.

# Speed 3 -- Full pipeline: architectural decisions + large scope
lion '"Build SaaS platform" -> fuse(3) -> task(5) -> pair(claude, eyes: sec+arch+perf)'
# Deliberate → decompose → parallel pair in worktrees.
# 300+ lines, fundamental architecture choices.
```

The old four speeds (solo → pair → fuse+pair → multi-swarm) collapse because pair() makes fuse() optional for most tasks. The middle two speeds merge.

Auto-selection via complexity config:

```toml
[complexity]
large_signals = ["platform", "system", "saas", "migrate", "redesign", "architect"]
large_pipeline = "fuse(3) -> task(5) -> pair(claude, eyes: sec+arch+perf)"

medium_signals = ["build", "create", "add", "implement", "integrate"]
medium_pipeline = "pair(claude, eyes: sec+arch)"

small_signals = ["fix", "bug", "typo", "rename", "change", "update"]
small_pipeline = "impl()"
```

## How It Works Under the Hood

### Billing Reality: Why Max Subscription Changes Everything

Before diving into implementation, the billing model fundamentally shapes the architecture:

**Max subscription ($100-200/mo):** `claude -p` runs on your subscription allocation. Every terminate + restart costs €0 extra. You're limited by a 5-hour rolling quota and weekly caps, not by tokens. You can afford to be aggressive with interrupts.

**API key (pay-per-token):** Every restart re-sends all accumulated output as input tokens. 50 lines of code + 3 interrupts = paying for those 50 lines 4× as input. Interrupts have real cost.

**For Lion, the primary path targets Max subscribers** -- the people who already use Claude Code daily. This means `claude -p` with `--resume` is the optimal path, not the SDK.

### Three Implementation Paths for Stream Interruption

#### Path 1: CLI `--resume` (Primary -- Works on Max Subscription)

`claude -p` with `--output-format stream-json` gives real-time streaming output. When an eye finds an issue, LION terminates the process and resumes the same session with `--resume`. The session lives on disk -- **no context is lost**.

```python
import subprocess, json

def pair_cli_resume(task: str, eyes: list[Eye]):
    lead_output = ""
    session_id = None
    
    while not complete:
        # Build the command -- first call or resume
        cmd = ["claude", "-p", build_prompt(task, lead_output, findings=None),
               "--output-format", "stream-json"]
        if session_id:
            cmd.extend(["--resume", session_id])
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        
        chunk = ""
        for line in proc.stdout:
            # Parse stream-json: each line is a JSON message
            msg = json.loads(line)
            if msg.get("type") == "assistant" and "text" in msg:
                chunk += msg["text"]
                lead_output += msg["text"]
            
            # Capture session_id from first response
            if not session_id and "session_id" in msg:
                session_id = msg["session_id"]
            
            # Every ~200 tokens, let eyes analyze
            if should_check(chunk):
                findings = check_eyes_fast(eyes, lead_output)
                
                if findings:
                    proc.terminate()
                    proc.wait()
                    
                    # Resume SAME session with correction injected
                    # Context is preserved on disk via session_id
                    cmd = ["claude", "-p",
                           format_correction(findings),
                           "--resume", session_id,
                           "--output-format", "stream-json"]
                    chunk = ""
                    break
        else:
            complete = True
    
    return lead_output
```

**Why this is the right default:**
- ✅ Works on Max subscription (€0 per interrupt)
- ✅ Context preserved via `--resume` (session on disk)
- ✅ No SDK dependency, no API key needed
- ✅ Officially supported by Anthropic
- ⚠️ ~1-2s process restart latency per interrupt (acceptable)

#### Dynamic Leader Election: The Mutiny Pattern

Even with `--resume`, there's a restart penalty (~1-2 seconds to spin up a new CLI process). The Mutiny pattern eliminates this by letting the eye -- whose context is already *warm* -- write the fix directly.

**The insight:** When an eye finds a problem, it just spent tokens analyzing exactly that code. Its context is gloeiend heet. Why restart the lead and ask it to apply a fix it hasn't thought about, when the eye already has the solution loaded?

```
Normal flow (restart penalty):
  1. Lead (Claude) writes 50 lines
  2. Eye (Gemini) finds SQL injection on line 48
  3. Terminate lead, resume with correction     ← ~2s restart
  4. Lead applies the fix and continues

Mutiny flow (zero restart penalty):
  1. Lead (Claude) writes 50 lines
  2. Eye (Gemini) finds SQL injection on line 48
  3. Terminate lead                              ← context saved on disk
  4. Gemini writes ONLY the fix directly         ← context warm, zero penalty
  5. Resume lead with accumulated output          ← lead sees the fix as fait accompli
```

**The Asymmetric Problem & Micro-Mutiny**

With the Avengers setup (expensive lead, cheap eyes), letting a cheap eye take over permanently is a downgrade. The solution: **Micro-Mutiny** -- the eye writes only the fix (its context is warm for that), then hands back to the lead.

```python
def pair_cli_mutiny(task: str, lead_model: str, eyes: list[Eye]):
    lead_output = ""
    session_id = None
    
    while not complete:
        # Start/resume lead
        cmd = build_lead_cmd(task, lead_output, session_id)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        
        chunk = ""
        for line in proc.stdout:
            chunk += parse_stream(line)
            lead_output += chunk
            session_id = extract_session_id(line) or session_id
            
            if should_check(chunk):
                findings = check_eyes_fast(eyes, lead_output)
                
                if findings:
                    proc.terminate()
                    proc.wait()
                    
                    # MICRO-MUTINY: eye writes ONLY the fix
                    for finding in findings:
                        fix = run_eye_fix(
                            finding.eye,
                            code_so_far=lead_output,
                            issue=finding.description
                        )
                        lead_output += fix
                    
                    # Hand back to lead -- resume with fix included
                    chunk = ""
                    break
        else:
            complete = True
    
    return lead_output
```

**When to use full mutiny vs micro-mutiny:**

| Scenario | Strategy | Why |
|----------|----------|-----|
| Eye finds a localized bug (missing index, SQL injection) | Micro-mutiny: eye fixes, lead continues | Fix is scoped, lead is better for the big picture |
| Eye finds a fundamental architecture flaw | Full mutiny: eye takes over as lead | The original approach is wrong, whoever sees it clearest should drive |
| All eyes are the same model as lead (premium mode) | Full mutiny: whoever finds it, fixes it | No capability downgrade, fastest path wins |

This is Dynamic Leader Election for AI agents -- the watcher becomes the writer the moment it has the clearest view of the problem. No meetings, no handoffs, no restart penalty. The baton goes to whoever can run fastest *right now*.

#### Path 2: Claude Agent SDK (Upgrade -- Requires API Key)

The Agent SDK (`ClaudeSDKClient`) provides true in-process interrupt: the lead pauses mid-sentence, receives the correction, and continues without process restart. Zero latency penalty, zero context loss.

**Important billing caveat (as of Feb 2025):** The Agent SDK officially requires API key authentication. Anthropic's policy states that OAuth tokens from Max subscriptions should not be used in the SDK. Anthropic has sent mixed signals (saying "nothing changes" while also banning third-party OAuth usage), but for production use: **plan on API key billing for the SDK path.**

| API | Protocol | Interrupt | Billing |
|-----|----------|-----------|---------|
| Claude Agent SDK | `ClaudeSDKClient` | `interrupt()` method | API key (pay-per-token) |
| Gemini Live API | WebSocket | Auto-interrupt on new content | API key or free tier |

```python
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

async def pair_sdk(task: str, plan: str, lead_model: str, eyes: list[Eye]):
    lead = ClaudeSDKClient(ClaudeCodeOptions(model=lead_model))
    await lead.connect()
    await lead.query(f"Implement this plan:\n{plan}")
    
    eye_clients = {eye.name: ClaudeSDKClient(ClaudeCodeOptions(model=eye.model))
                   for eye in eyes}
    for client in eye_clients.values():
        await client.connect()
    
    lead_output = ""
    
    async for msg in lead.receive_response():
        lead_output += extract_text(msg)
        
        if should_check(lead_output):
            findings = await asyncio.gather(*[
                eye_clients[eye.name].query(
                    f"[{eye.lens} review] Current code:\n{lead_output}\n"
                    f"Any {eye.lens} issues? Be specific. Say NONE if clean."
                ) for eye in eyes
            ])
            
            critical = [f for f in findings if f != "NONE"]
            if critical:
                # TRUE INTERRUPT -- pauses mid-sentence, no context loss
                await lead.interrupt()
                await lead.query(
                    f"Corrections from reviewers:\n" +
                    "\n".join(f"[{eye.name}]: {finding}" 
                             for eye, finding in zip(eyes, findings) 
                             if finding != "NONE") +
                    f"\nAdjust your implementation and continue."
                )
    
    return lead_output
```

**Advantages over CLI path:** No process restart (~0ms interrupt vs ~2s), no disk I/O for session. But you pay per token and need API key management.

#### Path 3: Gemini as Eye (Free Tier -- Zero Cost Eyes)

Gemini Flash's free tier (60 req/min, 1000/day) makes it perfect for eyes. Eyes read a lot but generate little -- a perfect fit for a free API with generous rate limits.

```python
# Eye using Gemini free API -- costs literally nothing
def check_eye_gemini(eye: Eye, code: str) -> str | None:
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": 
                f"[{eye.lens} review] Check this code for {eye.lens} issues only.\n"
                f"Code:\n{code}\n"
                f"Reply NONE if clean, or describe the issue in one sentence."
            }]}]
        }
    )
    finding = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None if "NONE" in finding else finding
```

### Recommended Stack: Three CLIs on Subscription

With Claude Max, Gemini Code Assist, and Codex (ChatGPT) subscriptions, you have three CLI tools -- all flat-rate, all streamable, all with resume support:

| Tool | CLI | Streaming | Resume | Billing |
|------|-----|-----------|--------|---------|
| Claude | `claude -p --output-format stream-json` | ✅ JSON stream | `--resume {session_id}` | Max subscription |
| Gemini | `gemini` CLI | ✅ stdout | session persistence | Code Assist subscription |
| Codex | `codex exec --json` | ✅ JSONL events | `codex exec resume` | ChatGPT subscription |

Every terminate + restart costs €0 across all three tools. The only constraint is quota per tool.

This enables the true Avengers setup -- any model as lead, any as eye, all on flat-rate:

```bash
# Claude builds, Gemini + Codex watch (all on subscription)
lion '"Build auth" -> pair(claude, eyes: gemini.sec+codex.arch)'

# Gemini deliberates (free/subscription), Claude builds, Codex reviews
lion '"Build payment" -> fuse(gemini, gemini, gemini) -> pair(claude, eyes: codex.sec+gemini.perf)'

# Full mutiny: whoever sees the problem, fixes it
lion '"Build API" -> pair(claude, eyes: gemini+codex, mutiny: full)'
```

### `fuse()` Implementation

```python
async def execute_fuse(task: str, n_agents: int):
    clients = [ClaudeSDKClient(options) for _ in range(n_agents)]
    for client in clients:
        await client.connect()
        await client.query(f"Collaborate on: {task}")

    buffers = [""] * n_agents
    
    while not all_converged(buffers):
        for i, client in enumerate(clients):
            # Read ~100 tokens from this agent
            async for msg in client.receive_response():
                buffers[i] += extract_text(msg)
                if len(buffers[i]) > chunk_size:
                    await client.interrupt()
                    break
            
            # Inject this agent's thinking into all others
            for j, other in enumerate(clients):
                if j != i:
                    peer_context = format_peer_output(buffers, exclude=j)
                    await other.query(f"Peers are thinking:\n{peer_context}\n\nContinue.")
    
    return merge_outputs(buffers)
```

### Key Design Decisions

**Chunk size for fuse():** ~100 tokens. Too small → too many interrupts, context pollution. Too large → agents diverge too far before seeing each other.

**Interrupt threshold for pair():** ~200 tokens of new code. Eyes need enough context to spot patterns, but not so much that cascading hallucinations compound.

**Eye concurrency:** Eyes analyze in parallel (they look at different things). Only interrupt the lead if at least one eye finds a critical issue. Minor style issues are buffered and delivered at the end.

**Convergence detection for fuse():** When agents start agreeing on the same approach for ~2 consecutive chunks, convergence is reached. No explicit converge step needed.

**Cost model for pair():** Eyes use cheap models (Haiku, Gemini Flash). They read a lot but generate little. Lead uses expensive model (Opus/Sonnet). Eyes add ~10-20% overhead. With Gemini's free tier, eyes can be literally free.

**Worktree lifecycle:** Created on task start, destroyed after merge. Tests run in-worktree before merge. Merge conflicts trigger a dedicated resolve agent. Maximum 10 concurrent worktrees to avoid disk pressure.

## Why This Is Novel

No existing framework does real-time agent-to-agent streaming collaboration:

| Framework | Pattern | Timing | Isolation |
|-----------|---------|--------|-----------|
| AutoGen | Agents take turns | Sequential | Shared context |
| CrewAI | Task delegation | Sequential | Shared context |
| LangGraph | State machine transitions | Sequential | Shared state |
| Group Think (paper) | Token-level, single model | Concurrent | Single inference |
| **Lion pair()** | Lead streams + eyes interrupt | Concurrent, asymmetric | Per-agent context |
| **Lion fuse()** | Chunk-level across APIs | Concurrent, multi-model | Per-agent context |
| **Lion task() + worktrees** | Parallel swarms | Concurrent, isolated | Per-worktree filesystem |

No one else combines: real-time stream interruption + asymmetric cost allocation + multi-model mixing + filesystem isolation via worktrees. This is a fundamentally different architecture.

## Research Foundation

- **Group Think** (MediaTek, May 2025): Token-level collaboration yields 4× latency reduction, improved accuracy. Validates that concurrent LLM collaboration works even with models not trained for it.
- **MIT Multi-Agent Debate** (2023): Iterative feedback between agents improves factual accuracy and reasoning. Lion's `pride()` is based on this. `fuse()` is the real-time evolution.
- **Pair Programming Studies** (meta-analyses): Pair programming produces fewer defects per line of code. The navigator catches ~60% of defects in real-time that solo review would miss.
- **Mob Programming Studies**: Mob programming (1 driver, multiple navigators) outperforms pair programming for complex tasks due to cognitive diversity. Lion's `pair()` with multiple eyes is mob programming for AI.

## What This Means for Lion

Lion's value proposition:

> **Lion is the first framework where AI agents collaborate in real-time, not in turns.**
> **And the first to scale this with isolated parallel swarms via Git worktrees.**

The Unix-pipe syntax makes this accessible:

```bash
# Anyone can read this and understand what it does
lion '"Build auth" -> pair(claude.opus, eyes: sec+arch)'

# "Build auth with a lead developer and security + architecture reviewers watching live"

lion '"Build SaaS platform" -> task(5) -> fuse(3) -> pair(claude.opus, eyes: sec+arch+perf)'

# "Break the platform into 5 features, deliberate on architecture,
#  then pair-program each feature in parallel with security, architecture,
#  and performance reviewers -- each in its own isolated worktree"
```

No YAML configs. No agent class hierarchies. No graph definitions. Just a pipeline that reads like English and executes like a swarm.

---

## Implementation Roadmap

### Phase 1: The Stream Interceptor (Core Engine)

Build a unified `StreamInterceptor` abstraction that wraps all three CLIs (Claude, Gemini, Codex), streams their output, and supports terminate + resume. This is the foundation -- everything else builds on this.

1. Abstract `StreamInterceptor` base class with `start()`, `chunks()`, `terminate()`, `resume()`
2. `ClaudeInterceptor`: wraps `claude -p --output-format stream-json`, captures `session_id`, resumes via `--resume`
3. `GeminiInterceptor`: wraps `gemini` CLI, parses stdout stream, handles session persistence
4. `CodexInterceptor`: wraps `codex exec --json`, parses JSONL events, resumes via `codex exec resume`
5. `EyeRunner`: takes any interceptor + lens prompt, evaluates chunks, returns findings
6. Basic `pair()`: 1 lead interceptor + n eye interceptors running in parallel
7. Tests: verify interrupt/resume per CLI, verify cross-CLI eye checks work

**Reference implementation: `pair_poc/`**

The POC directory contains a working proof of concept of the full pair() loop. This is the code structure to port into Lion:

```
pair_poc/
├── interceptors/
│   ├── base.py           # Abstract StreamInterceptor
│   ├── claude.py          # ClaudeInterceptor
│   ├── gemini.py          # GeminiInterceptor
│   └── codex.py           # CodexInterceptor
├── eyes/
│   ├── eye.py             # Eye: interceptor + lens + check logic
│   └── lenses.py          # Lens prompts: sec, arch, perf, test
├── pair.py                # The pair() loop: lead + eyes + interrupt
├── benchmark.py           # Experiment 7: pair() vs solo+review
└── config.py              # CLI paths, models, chunk sizes
```

**`interceptors/base.py`** -- The abstract interface:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator
import subprocess
import time


@dataclass
class Chunk:
    text: str
    timestamp: float
    accumulated: str  # all text so far


class StreamInterceptor(ABC):
    """Base class for CLI stream interception.
    
    Treats LLM CLIs as OS processes: start, stream, terminate, resume.
    This is process-level orchestration, not prompt orchestration.
    """
    
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.accumulated: str = ""
        self.chunk_count: int = 0
        self.start_time: float = 0
        self.ttft: float | None = None  # time to first token
    
    @abstractmethod
    def _build_cmd(self, prompt: str, resume: bool = False) -> list[str]:
        """Build the CLI command for this provider."""
        ...
    
    @abstractmethod
    def _parse_line(self, line: str) -> str | None:
        """Parse a line of output into text content. Returns None if not content."""
        ...
    
    @abstractmethod
    def _extract_session_id(self, line: str) -> str | None:
        """Extract session ID from output line if present."""
        ...
    
    def start(self, prompt: str) -> None:
        cmd = self._build_cmd(prompt, resume=bool(self.session_id))
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )
        self.start_time = time.time()
    
    def chunks(self) -> Iterator[Chunk]:
        if not self.proc or not self.proc.stdout:
            return
        
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            
            # Try to extract session ID
            sid = self._extract_session_id(line)
            if sid:
                self.session_id = sid
            
            # Parse content
            text = self._parse_line(line)
            if text:
                self.accumulated += text
                self.chunk_count += 1
                if self.ttft is None:
                    self.ttft = time.time() - self.start_time
                yield Chunk(
                    text=text,
                    timestamp=time.time() - self.start_time,
                    accumulated=self.accumulated
                )
    
    def terminate(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait()
            self.proc = None
    
    def resume(self, correction: str) -> None:
        """Terminate current process and restart with correction."""
        self.terminate()
        prompt = f"{correction}\n\nContinue from where you left off."
        self.start(prompt)
```

**`interceptors/claude.py`** -- Claude CLI implementation:

```python
import json
from .base import StreamInterceptor


class ClaudeInterceptor(StreamInterceptor):
    name = "claude"
    
    def _build_cmd(self, prompt: str, resume: bool = False) -> list[str]:
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json"]
        if resume and self.session_id:
            cmd.extend(["--resume", self.session_id])
        return cmd
    
    def _parse_line(self, line: str) -> str | None:
        try:
            msg = json.loads(line)
            if msg.get("type") == "assistant":
                # Extract text from content blocks
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        return block["text"]
                    elif isinstance(block, str):
                        return block
        except json.JSONDecodeError:
            pass
        return None
    
    def _extract_session_id(self, line: str) -> str | None:
        try:
            msg = json.loads(line)
            return msg.get("session_id")
        except json.JSONDecodeError:
            return None
```

**`interceptors/gemini.py`** -- Gemini CLI implementation:

```python
from .base import StreamInterceptor


class GeminiInterceptor(StreamInterceptor):
    name = "gemini"
    
    def _build_cmd(self, prompt: str, resume: bool = False) -> list[str]:
        # Gemini CLI non-interactive mode
        # NOTE: exact flags depend on your gemini CLI version
        # Document the actual command from POC experiment 0
        return ["gemini", "-p", prompt]
    
    def _parse_line(self, line: str) -> str | None:
        # Gemini CLI outputs plain text or JSON depending on mode
        # Adapt based on experiment 0 findings
        if line.strip():
            return line
        return None
    
    def _extract_session_id(self, line: str) -> str | None:
        # Gemini session handling -- document from experiment 0
        return None
```

**`interceptors/codex.py`** -- Codex CLI implementation:

```python
import json
from .base import StreamInterceptor


class CodexInterceptor(StreamInterceptor):
    name = "codex"
    
    def _build_cmd(self, prompt: str, resume: bool = False) -> list[str]:
        if resume and self.session_id:
            return ["codex", "exec", "resume", self.session_id, prompt]
        return ["codex", "exec", "--json", prompt]
    
    def _parse_line(self, line: str) -> str | None:
        try:
            event = json.loads(line)
            # Codex JSONL events have different types
            if event.get("type") == "item.message":
                return event.get("content", "")
            elif event.get("type") == "turn.completed":
                # Extract final message
                return event.get("message", "")
        except json.JSONDecodeError:
            pass
        return None
    
    def _extract_session_id(self, line: str) -> str | None:
        try:
            event = json.loads(line)
            if event.get("type") == "thread.started":
                return event.get("thread_id")
        except json.JSONDecodeError:
            return None
```

**`eyes/lenses.py`** -- Lens prompt templates:

```python
LENSES = {
    "sec": {
        "name": "Security",
        "prompt": (
            "[SECURITY REVIEW] Check this code for security issues only. "
            "Look for: SQL injection, XSS, plaintext passwords, missing auth, "
            "hardcoded secrets, missing input validation, insecure crypto. "
            "Reply NONE if clean. Otherwise describe the issue in one sentence."
        ),
    },
    "arch": {
        "name": "Architecture",
        "prompt": (
            "[ARCHITECTURE REVIEW] Check this code for architecture issues only. "
            "Look for: tight coupling, missing abstractions, SOLID violations, "
            "god classes, missing error handling, wrong patterns. "
            "Reply NONE if clean. Otherwise describe the issue in one sentence."
        ),
    },
    "perf": {
        "name": "Performance",
        "prompt": (
            "[PERFORMANCE REVIEW] Check this code for performance issues only. "
            "Look for: N+1 queries, missing indexes, memory leaks, blocking I/O, "
            "unnecessary allocations, missing connection pooling. "
            "Reply NONE if clean. Otherwise describe the issue in one sentence."
        ),
    },
}
```

**`eyes/eye.py`** -- Eye runner:

```python
from dataclasses import dataclass
from interceptors.base import StreamInterceptor
import threading


@dataclass
class Finding:
    lens: str
    description: str
    eye_name: str
    latency: float  # seconds to get response


class Eye:
    """An eye watches code and reports findings.
    
    Each eye wraps a StreamInterceptor (any CLI) with a lens (review focus).
    Eyes run checks asynchronously -- they don't block the lead.
    """
    
    def __init__(self, interceptor: StreamInterceptor, lens: str, lens_prompt: str):
        self.interceptor = interceptor
        self.lens = lens
        self.lens_prompt = lens_prompt
        self.name = f"{interceptor.name}:{lens}"
    
    def check(self, code: str) -> Finding | None:
        """Send code to the eye's CLI for review. Returns Finding or None."""
        import time
        start = time.time()
        
        prompt = f"{self.lens_prompt}\n\nCode:\n```\n{code}\n```"
        
        self.interceptor.start(prompt)
        response = ""
        for chunk in self.interceptor.chunks():
            response += chunk.text
        
        latency = time.time() - start
        
        if "NONE" in response.upper():
            return None
        
        return Finding(
            lens=self.lens,
            description=response.strip(),
            eye_name=self.name,
            latency=latency
        )
```

**`pair.py`** -- The complete pair() loop:

```python
"""
pair() -- The core Lion primitive.

A streaming-aware, interrupt-driven, process-level pair programming loop.

Lead (any CLI) generates code.
Eyes (any CLI × any lens) monitor the stream in parallel.
On finding: terminate lead → inject correction → resume.

This is closed-loop control applied to LLM generation.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from interceptors.base import StreamInterceptor, Chunk
from eyes.eye import Eye, Finding


def pair(
    task: str,
    lead: StreamInterceptor,
    eyes: list[Eye],
    check_every_n_lines: int = 20,
    max_interrupts: int = 10,
    verbose: bool = True
) -> dict:
    """
    Execute the pair() loop.
    
    Returns:
        dict with: output, interrupts, wall_clock, findings
    """
    
    lead_output = ""
    findings_log: list[Finding] = []
    interrupt_count = 0
    lines_since_check = 0
    start_time = time.time()
    
    lead.start(task)
    
    complete = False
    while not complete and interrupt_count < max_interrupts:
        
        for chunk in lead.chunks():
            lead_output += chunk.text
            lines_since_check += chunk.text.count("\n")
            
            if verbose:
                print(f"[LEAD:{lead.name}] {chunk.text}", end="", flush=True)
            
            # Time to check?
            if lines_since_check >= check_every_n_lines:
                lines_since_check = 0
                
                # Run all eyes in parallel
                all_findings = _check_eyes_parallel(eyes, lead_output)
                
                if all_findings:
                    # INTERRUPT!
                    lead.terminate()
                    interrupt_count += 1
                    findings_log.extend(all_findings)
                    
                    if verbose:
                        for f in all_findings:
                            print(f"\n[EYE:{f.eye_name}] ⚠️  {f.description} ({f.latency:.1f}s)")
                    
                    # Build correction prompt
                    correction = _build_correction(all_findings)
                    
                    if verbose:
                        print(f"\n>>> INTERRUPT #{interrupt_count}: resuming with correction...")
                    
                    # Resume with correction
                    lead.resume(correction)
                    break  # restart the chunks() loop from resume
                else:
                    if verbose:
                        print(f"\n[EYES] ✅ clean ({len(eyes)} eyes checked)")
        else:
            # Lead finished without interrupt
            complete = True
    
    wall_clock = time.time() - start_time
    
    return {
        "output": lead_output,
        "interrupts": interrupt_count,
        "findings": findings_log,
        "wall_clock": wall_clock,
        "lines": lead_output.count("\n"),
    }


def _check_eyes_parallel(eyes: list[Eye], code: str) -> list[Finding]:
    """Run all eyes in parallel. Return list of findings (empty if all clean)."""
    findings = []
    
    with ThreadPoolExecutor(max_workers=len(eyes)) as pool:
        futures = {pool.submit(eye.check, code): eye for eye in eyes}
        
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                findings.append(result)
    
    return findings


def _build_correction(findings: list[Finding]) -> str:
    """Build a correction prompt from findings."""
    lines = ["Code reviewers found the following issues:\n"]
    for f in findings:
        lines.append(f"[{f.lens.upper()}]: {f.description}")
    lines.append("\nFix these issues in the code you've written and continue implementing.")
    return "\n".join(lines)


# ─── Example usage ───────────────────────────────────────────────

if __name__ == "__main__":
    from interceptors.claude import ClaudeInterceptor
    from interceptors.gemini import GeminiInterceptor
    from interceptors.codex import CodexInterceptor
    from eyes.lenses import LENSES
    
    # The Avengers setup:
    # Claude builds (Max subscription)
    # Gemini watches security (Code Assist subscription)
    # Codex watches architecture (ChatGPT subscription)
    
    lead = ClaudeInterceptor()
    
    eyes = [
        Eye(GeminiInterceptor(), "sec", LENSES["sec"]["prompt"]),
        Eye(CodexInterceptor(), "arch", LENSES["arch"]["prompt"]),
    ]
    
    result = pair(
        task=(
            "Write a complete Python auth system with: "
            "1) User registration with email validation "
            "2) Login with JWT tokens "
            "3) Password reset via email "
            "4) Rate limiting on all endpoints "
            "Include proper error handling and input validation."
        ),
        lead=lead,
        eyes=eyes,
        check_every_n_lines=20,
        verbose=True
    )
    
    print("\n" + "=" * 60)
    print(f"Done in {result['wall_clock']:.1f}s")
    print(f"Lines: {result['lines']}")
    print(f"Interrupts: {result['interrupts']}")
    print(f"Findings: {len(result['findings'])}")
    for f in result['findings']:
        print(f"  [{f.eye_name}] {f.description}")
```

### Phase 2: The `pair()` Primitive

Implement the Lead/Listener asymmetric routing with the stream interceptor.

1. Parser: recognize `pair(model, eyes: lens+lens)` syntax
2. Define standard lenses: `sec`, `arch`, `perf`, `test` with system prompts
3. `execute_pair()` with lead stream + eye evaluation + terminate/resume loop
4. Eye backend: Gemini Flash free API for zero-cost eyes
5. Mutiny pattern: eye writes fix on terminate, lead resumes with fix included
6. Integration: `pair()` as pipeline function that receives plan or task from upstream

### Phase 3: Worktree Provisioning

Add Git worktree automation to safely sandbox parallel agent operations.

1. `WorktreeManager`: create, list, merge, remove worktrees
2. Integration with `task()`: each subtask gets its own worktree
3. Post-completion: run tests per worktree, auto-merge on pass
4. Conflict resolution: dedicated agent for merge conflicts
5. Cleanup: worktree removal after merge

### Phase 4: The `fuse()` Primitive

Implement multi-session deliberation. Multiple `claude -p` processes run in parallel, periodically exchanging partial outputs via terminate/resume injection.

1. `execute_fuse()` with parallel CLI sessions + cross-injection
2. Convergence detection (semantic agreement across consecutive chunks)
3. Parser: recognize `fuse(n)` or `fuse(model, model, model)` syntax
4. Integration: `fuse()` output feeds into `pair()` or `impl()`

### Phase 5: SDK Migration (Optional -- for API key users)

Upgrade from CLI to Agent SDK for true in-process interrupt without process restart.

1. `ClaudeSDKClient` wrapper (requires API key, not Max subscription)
2. `GeminiLiveClient` wrapper for WebSocket-based eyes
3. Swap CLI backend → SDK backend as optional flag
4. Keep CLI as default for Max subscribers

### Phase 6: Auto-Complexity & Custom Eyes

1. Task classifier: parse prompt → assign complexity level → select pipeline
2. Config: `[complexity]` section with signal words and pipeline mappings
3. Custom lenses: user-defined eye system prompts in config
4. Example: `lion '"Build auth" -> pair(claude.opus, eyes: hipaa+gdpr)'`

---

*This is the future of Lion. Not agents taking turns -- agents working together. Not one giant team -- isolated swarms, each with a builder and watchers, running in parallel on their own branch of the codebase.*