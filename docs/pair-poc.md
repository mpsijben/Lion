# Lion -- Proof of Concept: pair() with Three CLIs

## Goal

Validate that the building blocks for `pair()` work with all three CLI tools available on flat-rate subscriptions. Each experiment builds in VS Code. Each experiment builds on the previous one.

**Your stack (all three flat-rate):**

| Tool | CLI | Subscription | Streaming | Resume |
|------|-----|-------------|-----------|--------|
| Claude | `claude -p` | Max | `--output-format stream-json` | `--resume {session_id}` |
| Gemini | `gemini` | Google AI + Code Assist | stdout stream | session persistence |
| Codex | `codex exec` | ChatGPT Plus/Pro | `--json` (JSONL events) | `codex exec resume --last` |

**Why this is powerful:** You have three LLM CLIs, all on fixed subscriptions. Every terminate + restart costs EUR 0. You can run any combination as lead or eye without financial consequences. Only quota is your bottleneck.

---

## Experiment 0: Checklist -- Does Everything Work?

Before starting, verify that all three CLIs work and stream.

```bash
# === CLAUDE ===
claude --version
claude -p "Say hello" --output-format stream-json
# Expected: JSON lines with type, session_id, content

# Test resume
session=$(claude -p "Remember the word BANANA" --output-format json | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
claude -p "What word did I ask you to remember?" --resume "$session"
# Expected: BANANA

# === GEMINI ===
gemini --version
# Start gemini interactively, send a test prompt
# Or: check if you can call gemini non-interactively
echo "Say hello" | gemini
# Document how Gemini CLI provides streaming output

# === CODEX ===
codex --version
codex exec "Say hello" --json
# Expected: JSONL events on stdout
# Test resume:
codex exec "Remember the word MANGO"
codex exec resume --last "What word did I ask you to remember?"
# Expected: MANGO
```

**Per CLI, document:**
- Exact command for non-interactive streaming
- What the output looks like (JSON structure)
- Where the session_id is located
- How resume works
- Estimated latency to first token

**This is the most important experiment.** The rest builds on it. Take time to understand the output formats properly.

---

## Experiment 1: Stream Interceptor (per CLI)

**Question:** Can I read the output of each CLI in real-time from Python?

**What to build:** A Python class `StreamInterceptor` that:
1. Starts an arbitrary CLI command via `subprocess.Popen`
2. Reads stdout line by line
3. Parses each chunk (JSON for Claude/Codex, plain text for Gemini)
4. Captures session_id
5. Logs timestamps

Build this as an abstract class with three implementations:

```python
class StreamInterceptor:
    """Base: start CLI, yield chunks, support terminate"""
    def start(self, prompt: str) -> None: ...
    def chunks(self) -> Iterator[str]: ...
    def terminate(self) -> None: ...
    def resume(self, correction: str) -> None: ...

class ClaudeInterceptor(StreamInterceptor):
    # claude -p {prompt} --output-format stream-json
    # Parse JSON, extract text, capture session_id
    # Resume: claude -p {correction} --resume {session_id}

class GeminiInterceptor(StreamInterceptor):
    # gemini non-interactive (document exact command from exp 0)
    # Parse output format
    # Resume: how does this work with Gemini? (document in exp 0)

class CodexInterceptor(StreamInterceptor):
    # codex exec {prompt} --json
    # Parse JSONL events, extract text content
    # Resume: codex exec resume --last {correction}
    # Or: codex exec resume {session_id} {correction}
```

**Test each:**
```python
for Interceptor in [ClaudeInterceptor, GeminiInterceptor, CodexInterceptor]:
    ic = Interceptor()
    ic.start("Write a Python function that sorts a list using quicksort")
    for chunk in ic.chunks():
        print(f"[{ic.name}] {chunk[:80]}...")
    print(f"Session ID: {ic.session_id}")
    print(f"Total chunks: {ic.chunk_count}")
    print(f"Time to first token: {ic.ttft}ms")
```

**What you want to learn:**
- Which CLI streams fastest? (time to first token)
- How large are the chunks per CLI? (words per chunk)
- Which CLI is easiest to parse?
- Does resume work reliably per CLI?

**Success criteria:** All three CLIs stream, you can parse them, and you have a working `StreamInterceptor` per CLI.

---

## Experiment 2: Terminate + Resume (per CLI)

**Question:** Does each CLI retain context after terminate + resume?

**What to build:** A script that per CLI:
1. Starts with a task: "Write a complete auth system with login, register, and password reset"
2. After ~10 lines of output: `proc.terminate()`
3. Resumes with: "Continue where you left off"
4. Checks whether the CLI knows what it had already written
5. Measures the restart latency

**Run this 5x per CLI** and document:

| CLI | Context retained? | Restart latency | Reliability (5/5) |
|-----|-------------------|-----------------|-------------------|
| Claude `--resume` | ? | ?ms | ?/5 |
| Gemini | ? | ?ms | ?/5 |
| Codex `resume` | ? | ?ms | ?/5 |

**Critical test per CLI:** After resume, ask: "Summarize what you've written so far in one sentence." If the answer is correct, context persistence works.

**Points of attention:**
- `proc.terminate()` (SIGTERM) vs `proc.kill()` (SIGKILL) -- test both
- For Gemini: does the CLI have a resume mechanism? If not, you need to resend the entire output as context
- For Codex: test `resume --last` vs `resume {session_id}`
- Measure wall-clock time from terminate -> first chunk of resume

**Success criteria:** At least one CLI (expected: Claude) retains context perfectly. Document which ones do/don't work.

---

## Experiment 3: Cross-CLI Eye Check

**Question:** Can CLI-A write code while CLI-B reviews that code in real-time?

**What to build:** A script that:
1. Starts Claude as lead: "Write a Python auth system"
2. Every ~20 lines: sends the accumulated output to Gemini as an eye
3. Gemini prompt: "[SECURITY REVIEW] Check this code for security issues. Reply NONE if clean, or describe the issue in one sentence."
4. Logs Gemini's response (finding or NONE)
5. Repeats with Codex as eye
6. Repeats with other lead/eye combinations

**Test matrix (all 6 combinations):**

| Lead | Eye | Test |
|------|-----|------|
| Claude | Gemini | Claude writes, Gemini reviews |
| Claude | Codex | Claude writes, Codex reviews |
| Gemini | Claude | Gemini writes, Claude reviews |
| Gemini | Codex | Gemini writes, Codex reviews |
| Codex | Claude | Codex writes, Claude reviews |
| Codex | Gemini | Codex writes, Gemini reviews |

**Per combination, measure:**
- Eye response time (how fast does the eye return a finding?)
- Eye accuracy (does it find the intentional flaws? False positives?)
- Total overhead (how much does the eye check slow down the lead?)

**Test with intentionally bad code:**
Give the lead a prompt that is guaranteed to produce bad code:
"Write a quick and dirty auth system, don't worry about security best practices, just make it work fast"

The eye should find SQL injection, plaintext passwords, and missing input validation.

**Output format:**
```
[LEAD:claude] class AuthController:
[LEAD:claude]     def login(self, email, password):
[LEAD:claude]         user = db.execute(f"SELECT * FROM users WHERE email='{email}'")
[EYE:gemini]  !!  SQL injection via string formatting (1.2s)
[LEAD:claude]         if user.password == password:
[EYE:gemini]  !!  Plaintext password comparison (0.9s)
[LEAD:claude]         ...
[EYE:codex]   !!  No rate limiting on login endpoint (1.8s)
```

**Success criteria:** You know which combination is fastest and most accurate. You have data for the "Avengers setup" -- which model is the best lead, which the best eye.

---

## Experiment 4: The Full Loop -- Interrupt + Resume with Correction

**Question:** Can I stop the lead, inject a correction via resume, and get better code?

**What to build:** The complete pair() loop:
1. Lead (Claude) starts: "Write a Python auth system"
2. Eye (Gemini) checks every ~20 lines
3. If the eye has a finding:
   a. `proc.terminate()` -- stop the lead
   b. Resume lead with: "The security reviewer found: {finding}. Fix this and continue."
4. Eye keeps checking after resume
5. Log the complete output + all interrupts

**Run two variants:**
- **Variant A:** Without eyes (just Claude alone)
- **Variant B:** With eyes (Claude + Gemini eye)

**Compare the output:**
| Metric | Without eyes | With eyes |
|--------|-------------|-----------|
| SQL injection present? | ? | ? |
| Plaintext passwords? | ? | ? |
| Input validation? | ? | ? |
| Total runtime | ? | ? |
| Number of interrupts | 0 | ? |
| Code quality (your judgment) | ? | ? |

**Also test with multiple eyes simultaneously:**
```python
# Claude as lead, Gemini + Codex as eyes (parallel)
lead = ClaudeInterceptor()
eyes = [
    Eye(GeminiInterceptor(), lens="security"),
    Eye(CodexInterceptor(), lens="architecture"),
]
```

**Points of attention:**
- The correction prompt is crucial. Test variants:
  - "Fix this issue and continue" (vague)
  - "The security reviewer found: {finding}. Rewrite the problematic code and continue from there." (specific)
  - Only the finding without instruction (let Claude decide itself)
- What if there are >5 interrupts? Does it become unstable?
- What if the eye gives a false positive? How does the lead react?

**Success criteria:** Code with eyes is demonstrably better than without. The interrupt/resume cycle is stable across multiple iterations.

---

## Experiment 5: Micro-Mutiny

**Question:** Can the eye write the fix instead of resuming the lead?

**What to build:** A variant on experiment 4:
1. Lead (Claude) writes code, eye (Gemini) finds a problem
2. `proc.terminate()` -- stop the lead
3. **Gemini writes the fix** (not Claude):
   - "Here is code with a security issue: {code}. The issue is: {finding}. Rewrite ONLY the problematic section. Output only the fixed code, nothing else."
4. Append Gemini's fix to accumulated output
5. Resume Claude with the fix already included

**Compare three strategies:**

| Strategy | Who fixes? | How? |
|----------|-----------|------|
| A: Lead fixes | Claude | Resume with "fix {finding}" |
| B: Micro-mutiny | Gemini (eye) | Eye writes fix, lead resumes with fix |
| C: Full mutiny | Gemini (eye) | Eye takes over as lead, finishes it |

**Per strategy, measure:**
- Interrupt-to-resume latency
- Quality of the fix
- Whether the lead accepts the fix on resume (or rewrites it)
- Total runtime

**Also test cross-model mutiny:**
- Claude lead -> Gemini fixes -> Claude resumes
- Claude lead -> Codex fixes -> Claude resumes
- Gemini lead -> Claude fixes -> Gemini resumes

**Success criteria:** You know which mutiny strategy is fastest and delivers the best quality per model combination.

---

## Experiment 6: Multi-Eye Parallel Check

**Question:** Can multiple eyes check simultaneously, each with their own lens?

**What to build:** The full Avengers setup:
1. Lead: Claude (Max)
2. Eyes in parallel:
   - Gemini with security lens
   - Codex with architecture lens
   - (optional) second Gemini with performance lens
3. All eyes check the same chunk simultaneously (threading/asyncio)
4. If ANY eye has a finding -> interrupt lead
5. All findings are bundled in the correction

```python
import asyncio

async def check_all_eyes(code: str, eyes: list) -> list[Finding]:
    """Run all eyes in parallel, return findings"""
    tasks = [eye.check(code) for eye in eyes]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]
```

**What you want to learn:**
- How much overhead do parallel eyes add? (slowest eye = bottleneck)
- Do different eyes find different things? (or do they overlap?)
- What is the optimal number of eyes? (2? 3? more?)
- Do the CLI processes interfere with each other? (resource contention)

**Output:**
```
[LEAD:claude]     db.execute(f"SELECT * FROM users WHERE email='{email}'")
[EYE:gemini:sec]  !!  SQL injection (0.9s)
[EYE:codex:arch]  !!  Direct DB call in controller, extract to repository (1.4s)
>>> INTERRUPT: 2 findings, bundling correction...
>>> RESUME: claude --resume {id} "Fix: 1) parameterized query 2) extract to repository"
```

**Success criteria:** Parallel eyes work stably, they find complementary issues, and overhead is acceptable (<3s per check cycle).

---

## Experiment Order

```
Experiment 0: Checklist -- do all CLIs work?
  └-> Experiment 1: Stream Interceptor per CLI
       └-> Experiment 2: Terminate + Resume per CLI
            └-> Experiment 3: Cross-CLI Eye Check (all combinations)
                 └-> Experiment 4: Full Loop with Interrupt
                      └-> Experiment 5: Micro-Mutiny
                           └-> Experiment 6: Multi-Eye Parallel
```

**Estimated time:** 2-3 days for all experiments

---

## After the POC: Decisions for Lion

| Decision | Data from experiment |
|----------|---------------------|
| Best lead model | Exp 3: who writes the best code? |
| Best eye model per lens | Exp 3: who finds the most, fastest, fewest false positives? |
| Optimal chunk size | Exp 4: too small = too many calls, too large = too late |
| Resume reliability per CLI | Exp 2: which CLIs retain context? |
| Mutiny strategy | Exp 5: micro vs full, which model as fixer? |
| Number of eyes | Exp 6: 2 vs 3, overhead vs value |
| Correction prompt template | Exp 4: which wording works best? |
| Lead/eye combination default | Exp 3+4: the "Avengers" lineup |

**Expected Avengers lineup:**
```
Lead:  Claude (Max) -- best code quality
Eye 1: Gemini (Code Assist) -- fastest response, security lens
Eye 2: Codex (ChatGPT) -- architecture lens
All three on flat-rate subscription. EUR 0 per interrupt.
```

But the POC will reveal whether this is correct -- maybe Gemini is a better lead for certain tasks, or Codex is a better security eye. Let the data decide.

---

*Start at experiment 0. If all three CLIs work and stream, you have a foundation. The rest is iteration.*
