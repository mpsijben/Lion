# Lion CLI -- Design & Implementation

## The Vision

```
lion > Build an auth system -> pair(claude, eyes: sec+arch) -> test -> pr
```

No quotes. No YAML. No config files. Type what you want in natural language, append a pipeline, and Lion handles the rest.

---

## Syntax

### Anatomy of a Lion Command

```
lion > Build an auth system -> pair(gemini, eyes: arch+dx) -> review(^) -> pr
       ─────────────────────    ──────────────────────────    ──────────    ──
       prompt (free text)      step 1: pair programming       step 2        step 3
```

**Rules:**
- Everything before the first `->` is the prompt (free text, any language)
- Everything after `->` are pipeline steps, split on `->`
- `^` refers to the output of the previous step
- No quotes needed around the prompt

### Available Primitives

| Primitive | What it does | Example |
|-----------|-------------|-----------|
| `pair(model, eyes: lens+lens)` | Lead builds, eyes review in real-time | `pair(claude, eyes: sec+arch)` |
| `impl()` | Simple implementation, no eyes | `impl()` |
| `review(^)` | Review output from previous step | `review(^)` |
| `test` | Run test suite | `test` |
| `pr` | Git add + commit + push + open PR | `pr` |
| `commit` | Git add + commit | `commit` |
| `fuse(n)` | Real-time deliberation with n agents | `fuse(3)` |
| `<template>` | Expands to saved pipeline | `safe`, `quick`, `thorough` |

### Available Models

| Model | CLI | Subscription |
|-------|-----|-----------|
| `claude` | `claude -p` | Max |
| `gemini` | `gemini` | Code Assist |
| `codex` | `codex exec` | ChatGPT |

### Available Lenses

| Lens | Focus |
|------|-------|
| `sec` | Security: injection, auth, crypto, secrets |
| `arch` | Architecture: coupling, patterns, SOLID |
| `perf` | Performance: N+1, memory, connection pooling |
| `dx` | Developer experience: naming, readability, docs |
| `test` | Testability: hard dependencies, missing interfaces |

### Examples

```
lion > Fix the login bug
lion > Build payment -> pair(claude, eyes: sec+perf)
lion > Refactor the database layer -> pair(gemini, eyes: arch) -> test -> pr
lion > Build complete API -> fuse(3) -> pair(claude, eyes: sec+arch+perf) -> test -> pr
```

---

## Autocomplete

### Context-Aware Completion

The autocomplete knows where you are in the command and suggests only relevant options:

```
lion > Build auth -> [TAB]
  pair()    fuse()    impl()    review()    test    pr    commit

lion > Build auth -> pair([TAB]
  claude    gemini    codex

lion > Build auth -> pair(claude, [TAB]
  eyes:

lion > Build auth -> pair(claude, eyes: [TAB]
  sec    arch    perf    dx    test

lion > Build auth -> pair(claude, eyes: sec+[TAB]
  arch    perf    dx    test

lion > Build auth -> pair(claude, eyes: sec+arch) -> [TAB]
  review()    test    pr    commit    pair()
```

### Completion Rules

| Context | Suggestions |
|---------|-------------|
| After `->` | All primitives: `pair()`, `fuse()`, `impl()`, `review()`, `test`, `pr`, `commit` |
| After `pair(` | Models: `claude`, `gemini`, `codex` |
| After `eyes:` | Lenses: `sec`, `arch`, `perf`, `dx`, `test` |
| After `+` (inside eyes) | Remaining lenses (minus already selected) |
| After `fuse(` | Number (agent count): `2`, `3`, `5` |
| After `review(` | `^` (output of previous step) |

### Extra Features

- **History**: arrow up for previous commands
- **Fuzzy matching**: type `sc` -> suggests `sec`
- **Syntax highlighting**: `->` operators and primitives in color
- **Multi-line**: `\` at end of line for long pipelines

---

## Architecture

### Python with prompt_toolkit (recommended for now)

```
lioncli/
├── cli.py              # REPL with prompt_toolkit
├── parser.py           # Splits input into prompt + pipeline
├── scheduler.py        # Spawns and manages CLI subprocesses
├── interceptors/
│   ├── base.py         # Abstract StreamInterceptor
│   ├── claude.py       # claude -p --output-format stream-json
│   ├── gemini.py       # gemini CLI
│   └── codex.py        # codex exec --json
├── eyes/
│   ├── eye.py          # Eye runner with parallel checks
│   └── lenses.py       # Lens prompt templates
├── primitives/
│   ├── pair.py         # pair() loop: lead + eyes + interrupt
│   ├── impl_.py        # impl(): simple generation
│   ├── review.py       # review(): check output
│   ├── fuse.py         # fuse(): multi-agent deliberation
│   └── git.py          # test, commit, pr: git integrations
└── config.py           # TOML config loading
```

### Why Python (for now)

| Factor | Python | Rust |
|--------|--------|------|
| Startup time | ~300ms | ~5ms |
| Iteration speed | Fast | Slow |
| Subprocess handling | Fine (`subprocess.Popen`) | Fine (`std::process`) |
| Autocomplete libs | `prompt_toolkit` (mature) | `rustyline`/`reedline` |
| Distribution | `pip install` or `pipx` | Single binary |
| When relevant | Now: iterate on design | Later: open source release |

The subprocess calls (Claude, Gemini, Codex) take 10-60+ seconds. Python's 300ms startup is noise on that signal. Rust's advantage (fast startup, single binary) only becomes relevant when distributing to others.

**The pattern:** Start in Python -> use daily -> stabilize the design -> rewrite to Rust for release. Codex did the same.

---

## Implementation: cli.py with prompt_toolkit

```python
#!/usr/bin/env python3
"""
Lion CLI -- Streaming-aware, interrupt-driven LLM scheduler.

Usage:
    lion                          # Start interactive REPL
    lion Build auth -> pair(...)  # Direct command
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pathlib import Path
import sys


# --- Tokens for the parser/completer ---

PRIMITIVES = ["pair", "fuse", "impl", "review", "test", "pr", "commit"]
MODELS = ["claude", "gemini", "codex"]
LENSES = ["sec", "arch", "perf", "dx", "test"]


# --- Context-aware Completer ---

class LionCompleter(Completer):
    """
    Understands where you are in the command and suggests
    only relevant options.
    """
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()
        
        # Determine context
        if self._after_arrow(text):
            # After -> : suggest primitives
            for p in PRIMITIVES:
                if p.startswith(word.lower()):
                    display = f"{p}()" if p in ("pair", "fuse", "review") else p
                    yield Completion(display, start_position=-len(word))
        
        elif self._inside_pair_model(text):
            # After pair( : suggest models
            for m in MODELS:
                if m.startswith(word.lower()):
                    yield Completion(m, start_position=-len(word))
        
        elif self._after_eyes(text):
            # After eyes: or + : suggest lenses
            used = self._get_used_lenses(text)
            for lens in LENSES:
                if lens not in used and lens.startswith(word.lower()):
                    yield Completion(lens, start_position=-len(word))
        
        elif self._inside_fuse(text):
            # After fuse( : suggest numbers
            for n in ["2", "3", "5"]:
                if n.startswith(word):
                    yield Completion(n, start_position=-len(word))
        
        elif self._inside_review(text):
            # After review( : suggest ^
            if "^".startswith(word):
                yield Completion("^", start_position=-len(word))
    
    def _after_arrow(self, text: str) -> bool:
        """Cursor is after a -> (possibly with spaces)"""
        stripped = text.rstrip()
        return stripped.endswith("->") or stripped.endswith("-> ")
    
    def _inside_pair_model(self, text: str) -> bool:
        """Cursor is after pair( but before the comma"""
        # pair( is open, no comma yet
        if "pair(" in text:
            after_pair = text.split("pair(")[-1]
            return "," not in after_pair and ")" not in after_pair
        return False
    
    def _after_eyes(self, text: str) -> bool:
        """Cursor is after eyes: or after a +"""
        if "eyes:" in text:
            after_eyes = text.split("eyes:")[-1]
            return ")" not in after_eyes
        return False
    
    def _get_used_lenses(self, text: str) -> set:
        """Which lenses are already selected?"""
        if "eyes:" not in text:
            return set()
        after_eyes = text.split("eyes:")[-1].split(")")[0]
        return {l.strip() for l in after_eyes.replace("+", " ").split() if l.strip()}
    
    def _inside_fuse(self, text: str) -> bool:
        if "fuse(" in text:
            after_fuse = text.split("fuse(")[-1]
            return ")" not in after_fuse
        return False
    
    def _inside_review(self, text: str) -> bool:
        if "review(" in text:
            after_review = text.split("review(")[-1]
            return ")" not in after_review
        return False


# --- Syntax highlighting style ---

LION_STYLE = Style.from_dict({
    "prompt":      "#ff8c00 bold",   # orange lion prompt
    "":            "#ffffff",         # default white
})


# --- REPL ---

def run_repl():
    history_file = Path.home() / ".lion" / "history"
    history_file.parent.mkdir(exist_ok=True)
    
    session = PromptSession(
        completer=LionCompleter(),
        history=FileHistory(str(history_file)),
        style=LION_STYLE,
    )
    
    print("🦁 Lion CLI -- Streaming LLM Scheduler")
    print("   Type a task, add -> pipeline, press Enter.")
    print("   Tab for autocomplete. Ctrl+D to exit.\n")
    
    while True:
        try:
            text = session.prompt("lion > ")
            if not text.strip():
                continue
            
            # Parse and execute
            execute(text)
            
        except KeyboardInterrupt:
            continue
        except EOFError:
            print("\nGoodbye!")
            break


def execute(command: str):
    """Parse a lion command and execute it."""
    from parser import parse_pipeline
    from scheduler import run_pipeline
    
    pipeline = parse_pipeline(command)
    run_pipeline(pipeline)


# --- Direct mode (non-interactive) ---

def main():
    if len(sys.argv) > 1:
        # Direct command: lion Build auth -> pair(claude, eyes: sec)
        command = " ".join(sys.argv[1:])
        execute(command)
    else:
        # Interactive REPL
        run_repl()


if __name__ == "__main__":
    main()
```

---

## Config: ~/.lion/config.toml

```toml
# ~/.lion/config.toml

# Defaults for pair()
default_lead = "claude"
default_eyes = ["gemini:sec", "codex:arch"]
check_every_lines = 20
max_interrupts = 10

# CLI commands per model
[models.claude]
cmd = "claude"
args = ["-p", "--output-format", "stream-json"]
resume_flag = "--resume"

[models.gemini]
cmd = "gemini"
args = []
# fill in resume specifics after POC experiment 0

[models.codex]
cmd = "codex"
args = ["exec", "--json"]
resume_cmd = ["codex", "exec", "resume"]

# Lens prompts (aanpasbaar)
[lenses.sec]
name = "Security"
prompt = """Check this code for security issues only.
Look for: SQL injection, XSS, plaintext passwords, missing auth,
hardcoded secrets, missing input validation, insecure crypto.
Reply NONE if clean. Otherwise one sentence."""

[lenses.arch]
name = "Architecture"
prompt = """Check this code for architecture issues only.
Look for: tight coupling, missing abstractions, SOLID violations,
god classes, missing error handling, wrong patterns.
Reply NONE if clean. Otherwise one sentence."""

[lenses.perf]
name = "Performance"
prompt = """Check this code for performance issues only.
Look for: N+1 queries, missing indexes, memory leaks, blocking I/O,
unnecessary allocations, missing connection pooling.
Reply NONE if clean. Otherwise one sentence."""

[lenses.dx]
name = "Developer Experience"
prompt = """Check this code for developer experience issues only.
Look for: confusing naming, missing docs, overly complex logic,
inconsistent patterns, poor error messages.
Reply NONE if clean. Otherwise one sentence."""

[lenses.test]
name = "Testability"
prompt = """Check this code for testability issues only.
Look for: hard dependencies, missing interfaces, global state,
tight coupling that prevents mocking, side effects in constructors.
Reply NONE if clean. Otherwise one sentence."""
```

---

## Terminal UI (TUI) -- Live Pipeline Visualization

The core of the UX: every pipeline step is a live panel. You can navigate between them while they're running. Inspired by Claude Code's streaming interface.

### Library: Textual

[Textual](https://textual.textualize.io/) is a Python TUI framework by Will McGuigan (same creator as Rich). It gives you:

- Live updating widgets (streaming text in real-time)
- Scrollable containers per panel
- Keyboard navigation (Tab, arrows, Enter)
- Collapsible/expandable sections
- Syntax highlighting for code
- All in the terminal, no browser

### The UX in Detail

**Step 1: You type your command in the REPL**

```
🦁 Lion CLI -- Streaming LLM Scheduler

lion > Build auth system -> pair(claude, eyes: sec+arch) -> test -> pr
```

**Step 2: The TUI activates -- pipeline sidebar + active panel**

```
╭─ Pipeline ──────────────────────────────────────────────────────────────────╮
│                                                                             │
│  ● pair(claude, eyes: sec+arch)        32s   2 interrupts                   │
│  ○ test                                waiting...                           │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯

╭─ ● pair(claude, eyes: sec+arch) ─── streaming... ──────────────────────────╮
│                                                                             │
│  from fastapi import APIRouter, HTTPException, Depends                      │
│  from passlib.context import CryptContext                                   │
│  from jose import jwt                                                       │
│  import bcrypt                                                              │
│                                                                             │
│  router = APIRouter(prefix="/auth")                                         │
│  pwd_context = CryptContext(schemes=["bcrypt"])                              │
│                                                                             │
│  class AuthService:                                                         │
│      def __init__(self, db: Database):                                      │
│          self.db = db                                                        │
│                                                                             │
│      async def register(self, email: str, password: str):                   │
│          if await self.db.users.find_one({"email": email}):                 │
│              raise HTTPException(409, "Email already registered")            │
│          hashed = pwd_context.hash(password)                                │
│          ▋                                                                  │
│                                                                             │
│  ╭─ Eyes ─────────────────────────────────────────────────────────────╮     │
│  │  gemini:sec   checking... ██░░░░                                   │     │
│  │  codex:arch   ✅ clean (1.2s)                                      │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
╰── Tab: next step │ ↑↓: scroll code │ i: interrupt log │ q: abort ──────╯
```

**Step 3: Eye finds an issue -- interrupt visible in the panel**

```
╭─ ● pair(claude, eyes: sec+arch) ─── 18s ── INTERRUPT #1 ──────────────────╮
│                                                                             │
│  ...                                                                        │
│      async def register(self, email: str, password: str):                   │
│          if await self.db.users.find_one({"email": email}):                 │
│              raise HTTPException(409, "Email already registered")            │
│          hashed = pwd_context.hash(password)                                │
│                                                                             │
│  ╭─ ⚠️  INTERRUPT #1 ────────────────────────────────────────────────╮     │
│  │  [gemini:sec] JWT secret is hardcoded. Use environment variable   │     │
│  │               or secrets manager.                                  │     │
│  │  Action: terminate → inject correction → resume                    │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
│  >>> Resuming with correction...                                            │
│                                                                             │
│      JWT_SECRET = os.environ["JWT_SECRET"]  # ← fixed                       │
│      ▋                                                                      │
│                                                                             │
│  ╭─ Eyes ─────────────────────────────────────────────────────────────╮     │
│  │  gemini:sec   ✅ clean (0.9s)                                      │     │
│  │  codex:arch   ✅ clean (1.1s)                                      │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
╰── Tab: next step │ ↑↓: scroll code │ i: interrupt log │ q: abort ──────╯
```

**Step 4: pair() complete -- automatically moves to test**

```
╭─ Pipeline ──────────────────────────────────────────────────────────────────╮
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)       47s   2 interrupts   184 lines       │
│  ● test                                running...                           │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯

╭─ ● test ─── pytest ────────────────────────────────────────────────────────╮
│                                                                             │
│  $ pytest tests/test_auth.py -v                                             │
│                                                                             │
│  tests/test_auth.py::test_register_new_user PASSED                          │
│  tests/test_auth.py::test_register_duplicate_email PASSED                   │
│  tests/test_auth.py::test_login_valid PASSED                                │
│  tests/test_auth.py::test_login_invalid_password PASSED                     │
│  tests/test_auth.py::test_jwt_token_generation PASSED                       │
│  tests/test_auth.py::test_password_reset_flow ▋ running...                  │
│                                                                             │
╰── Tab: prev/next step │ ↑↓: scroll │ q: abort ──────────────────────╯
```

**Step 5: You navigate back to pair() to review the code**

Press Tab or ↑ to go back to the pair() panel. It's complete, so you see the full output, scrollable:

```
╭─ Pipeline ──────────────────────────────────────────────────────────────────╮
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)       47s   2 interrupts   184 lines       │
│  ● test                                12/14 passed...                      │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯

╭─ ✅ pair(claude, eyes: sec+arch) ─── 47s ── 184 lines ─────────────────────╮
│                                                                             │
│  from fastapi import APIRouter, HTTPException, Depends                      │
│  from passlib.context import CryptContext                                   │
│  from jose import jwt                                                       │
│  import os                                                                  │
│                                                                             │
│  router = APIRouter(prefix="/auth")                                         │
│  pwd_context = CryptContext(schemes=["bcrypt"])                              │
│  JWT_SECRET = os.environ["JWT_SECRET"]                                      │
│                                                                             │
│  class AuthService:                                                         │
│      ...                                                                    │
│                                                                             │
│  ── Interrupts (2) ──────────────────────────────────────────────────       │
│  #1 [gemini:sec] JWT secret hardcoded → fixed with env var (18s)            │
│  #2 [codex:arch] Missing rate limiter on login → added (31s)                │
│                                                                             │
│  ▼ scroll for more (184 lines)                                              │
│                                                                             │
╰── Tab: next step │ ↑↓: scroll │ c: copy code │ q: back ──────────────╯
```

**Step 6: All done -- summary**

```
╭─ Pipeline ── DONE ──────────────────────────────────────────────────────────╮
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)       47s   2 interrupts   184 lines       │
│  ✅ test                               14/14 passed         8s              │
│  ✅ pr                                 PR #47 created       3s              │
│                                                                             │
│  Total: 58s │ 2 security fixes │ 0 architecture issues                      │
│                                                                             │
╰── Enter: back to lion > │ r: replay │ c: copy all code ─────────────────╯
```

### Navigation

| Key | Action |
|-------|-------|
| `Tab` | Jump to next pipeline step |
| `Shift+Tab` | Jump to previous pipeline step |
| `↑` `↓` | Scroll within the active panel |
| `Enter` | Collapse/expand a completed step |
| `:` | **Command mode** -- edit pipeline, inject, hot-swap eyes |
| `f` | **File tracker** -- show changed files |
| `d` | **Diff view** -- show full diff of selected file |
| `i` | Toggle interrupt log |
| `c` | Copy code output to clipboard |
| `q` | Abort current step / back to REPL |
| `r` | Replay: review the entire session |

### Status Indicators

| Icon | Meaning |
|-------|-----------|
| `○` | Waiting (not yet started) |
| `●` | Active (in progress) |
| `✅` | Completed (success) |
| `❌` | Failed |
| `⚠️` | Completed with warnings |
| `██░░` | Eye checking (progress bar) |

### File Tracker & Diff View

While pair() runs, Lion monitors `git status` and `git diff` to show which files the agent creates or modifies. Inspired by how Claude Code and Codex CLI show diffs, but integrated into the pipeline TUI.

**File tracker widget -- always visible in the pair() panel:**

```
╭─ ● pair(claude, eyes: sec+arch) ─── streaming... ──────────────────────────╮
│                                                                             │
│  ╭─ Files Changed (4) ───────────────────────────────────────────────╮     │
│  │  + auth/controller.py          new      87 lines                   │     │
│  │  + auth/models.py              new      34 lines                   │     │
│  │  ~ auth/routes.py              modified +12 -3                     │     │
│  │  ~ requirements.txt            modified +2                         │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
│      class AuthController:                                                  │
│          def __init__(self, db: Database):                                  │
│              self.db = db                                                    │
│          ▋                                                                  │
│                                                                             │
│  ╭─ Eyes ─────────────────────────────────────────────────────────────╮     │
│  │  gemini:sec   ✅ clean │ codex:arch   ✅ clean                     │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
╰── f: files │ d: diff │ Tab: next step │ : command ─────────────────────────╯
```

**Press `f` -- expanded file tracker with selection:**

```
╭─ Files Changed (4) ──── ↑↓ select │ Enter: open │ d: diff │ Esc: back ───╮
│                                                                             │
│  + auth/controller.py          new      87 lines    ← selected         │
│  + auth/models.py              new      34 lines                            │
│  ~ auth/routes.py              modified +12 -3                              │
│  ~ requirements.txt            modified +2                                  │
│                                                                             │
│  ── Preview: auth/controller.py ──────────────────────────────────────      │
│  from fastapi import APIRouter, HTTPException                               │
│  from passlib.context import CryptContext                                   │
│  ...                                                                        │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**Press `d` -- full diff view for the selected file:**

```
╭─ Diff: auth/routes.py ─── modified +12 -3 ─────────────────────────────────╮
│                                                                             │
│   15   from auth.controller import AuthController                           │
│   16                                                                        │
│   17 - @router.post("/login")                                               │
│   17 + @router.post("/login", dependencies=[Depends(rate_limit)])           │
│   18   async def login(request: LoginRequest):                              │
│   19 -     user = db.find_user(request.email)                               │
│   19 +     user = await db.find_user(request.email)                         │
│   20 -     if not user:                                                     │
│   20 +     if not user or not verify_password(request.password, user.hash): │
│   21 +         raise HTTPException(401, "Invalid credentials")              │
│   22 +     return create_token(user)                                        │
│   23                                                                        │
│   ...                                                                       │
│                                                                             │
╰── ↑↓: scroll │ n: next file │ p: prev file │ Esc: back ──────────────────╯
```

**File status icons:**

| Icon | Meaning |
|-------|-----------|
| `+` | New file (green) |
| `~` | Modified file (yellow) |
| `-` | Deleted file (red) |
| `→` | Renamed file (blue) |

**Implementation:**

```python
import subprocess
import asyncio


class FileTracker:
    """
    Monitors git status/diff while pair() runs.
    Updates automatically on each eye check cycle.
    """
    
    def __init__(self, workdir: str = "."):
        self.workdir = workdir
        self.files: list[FileChange] = []
    
    def refresh(self) -> list[dict]:
        """Poll git status and diff for current changes."""
        self.files = []
        
        # New and modified files
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=self.workdir
        )
        
        for line in status.stdout.strip().split("\n"):
            if not line:
                continue
            
            status_code = line[:2].strip()
            filepath = line[3:].strip()
            
            change = {
                "path": filepath,
                "status": self._parse_status(status_code),
                "lines_added": 0,
                "lines_removed": 0,
            }
            
            # Get diff stats for modified files
            if change["status"] in ("modified", "new"):
                diff_stat = subprocess.run(
                    ["git", "diff", "--numstat", "--", filepath],
                    capture_output=True, text=True, cwd=self.workdir
                )
                if diff_stat.stdout.strip():
                    parts = diff_stat.stdout.strip().split("\t")
                    change["lines_added"] = int(parts[0]) if parts[0] != "-" else 0
                    change["lines_removed"] = int(parts[1]) if parts[1] != "-" else 0
            
            self.files.append(change)
        
        return self.files
    
    def get_diff(self, filepath: str) -> str:
        """Get the full diff for a single file."""
        result = subprocess.run(
            ["git", "diff", "--", filepath],
            capture_output=True, text=True, cwd=self.workdir
        )
        if not result.stdout:
            # New file -- show full content as diff
            result = subprocess.run(
                ["git", "diff", "--cached", "--", filepath],
                capture_output=True, text=True, cwd=self.workdir
            )
        return result.stdout
    
    def _parse_status(self, code: str) -> str:
        return {
            "A": "new", "?": "new", "M": "modified",
            "D": "deleted", "R": "renamed",
        }.get(code, "modified")
```

### Color Scheme

```
Pipeline header         │  gold/orange (#ff8c00)
Active step indicator   │  bright green
Code output             │  syntax highlighted (via Pygments)
Eye: clean              │  green
Eye: finding            │  red/orange
Interrupt box           │  yellow border
Manual inject box       │  blue border
Pipeline modified       │  purple indicator
File: new (+)           │  green
File: modified (~)      │  yellow
File: deleted (-)       │  red
File: renamed (->)      │  blue
Diff: added lines       │  green
Diff: removed lines     │  red
Step completed          │  dimmed/gray (non-distracting)
Keyboard hints          │  subtle gray at bottom
```

---

## Live Pipeline Editing -- The Pipeline as a Living Thing

The pipeline is not "fire and forget". You can modify, extend, and steer it *while it's running*. This makes Lion interactive -- you and the agents work together.

### Command Mode: press `:`

Like Vim: press `:` and a mini-prompt appears at the bottom of the screen with its own autocomplete.

```
╭─ Pipeline ──────────────────────────────────────────────────────────────────╮
│                                                                             │
│  ● pair(claude, eyes: sec+arch)        32s   1 interrupt                    │
│  ○ test                                waiting...                           │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─── : to edit pipeline ───────────────────────────────────────────────╯
```

### Adding and Removing Steps

**Example: you see the code and want an extra review**

```
: add review(^) after pair
```

Pipeline updates live:

```
╭─ Pipeline ──── MODIFIED ────────────────────────────────────────────────────╮
│                                                                             │
│  ● pair(claude, eyes: sec+arch)        32s   1 interrupt                    │
│  ○ review(^)                           added just now ✨                    │
│  ○ test                                waiting...                           │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**Example: you want to run the devil's advocate**

```
: add devil(^) before test
```

```
╭─ Pipeline ──── MODIFIED ────────────────────────────────────────────────────╮
│                                                                             │
│  ● pair(claude, eyes: sec+arch)        32s   1 interrupt                    │
│  ○ review(^)                           added ✨                             │
│  ○ devil(^)                            added ✨                             │
│  ○ test                                waiting...                           │
│  ○ pr                                  waiting...                           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**Example: skip the PR, just commit**

```
: replace pr with commit
```

### Manual Inject -- You Are the Eye

The most powerful command: `inject`. You see something in the streaming output and send a correction to the lead, exactly like an eye does -- but manually.

**Scenario: the lead picks MongoDB but you want PostgreSQL**

```
╭─ ● pair(claude, eyes: sec+arch) ─── streaming... ──────────────────────────╮
│                                                                             │
│      db = MongoClient("mongodb://localhost:27017")                           │
│      collection = db.users                                                  │
│      ▋                                                                      │
│                                                                             │
╰─ : inject "Use PostgreSQL with SQLAlchemy, not MongoDB" ───────────────────╯
```

The lead is interrupted, your correction is injected, and it resumes:

```
╭─ ● pair(claude, eyes: sec+arch) ─── 24s ── INJECT ────────────────────────╮
│                                                                             │
│      db = MongoClient("mongodb://localhost:27017")                           │
│      collection = db.users                                                  │
│                                                                             │
│  ╭─ 👤 MANUAL INJECT ────────────────────────────────────────────────╮     │
│  │  "Use PostgreSQL with SQLAlchemy, not MongoDB"                     │     │
│  │  Action: terminate → inject correction → resume                    │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
│  >>> Resuming with your correction...                                       │
│                                                                             │
│      from sqlalchemy import create_engine, Column, String, Integer           │
│      from sqlalchemy.orm import declarative_base, Session                    │
│                                                                             │
│      engine = create_engine(os.environ["DATABASE_URL"])                      │
│      Base = declarative_base()                                              │
│                                                                             │
│      class User(Base):                                                      │
│          __tablename__ = "users"                                            │
│          ▋                                                                  │
│                                                                             │
│  ╭─ Eyes ─────────────────────────────────────────────────────────────╮     │
│  │  gemini:sec   ✅ clean (0.9s)                                      │     │
│  │  codex:arch   ✅ clean (1.1s)                                      │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
│                                                                             │
╰── Tab: next step │ : command mode │ ↑↓: scroll ───────────────────────╯
```

### Hot-Swap Eyes

You can even add or remove eyes *while pair() is running*:

```
: eyes add perf
```

```
│  ╭─ Eyes ─────────────────────────────────────────────────────────────╮     │
│  │  gemini:sec   ✅ clean (0.9s)                                      │     │
│  │  codex:arch   ✅ clean (1.1s)                                      │     │
│  │  gemini:perf  added ✨ (checking next cycle)                       │     │
│  ╰────────────────────────────────────────────────────────────────────╯     │
```

Or remove an eye that gives too many false positives:

```
: eyes remove arch
```

### All Command Mode Commands

| Command | What it does |
|----------|-------------|
| **Pipeline steps** | |
| `: add review(^) after pair` | Add step after pair |
| `: add devil(^) before test` | Add devil's advocate before test |
| `: add pair(gemini, eyes: perf) after test` | Another pair round |
| `: remove pr` | Remove a waiting step |
| `: replace test with test --coverage` | Replace a step |
| `: move test before review` | Move a step |
| **Flow control** | |
| `: pause` | Pause the active step (terminate, save session) |
| `: resume` | Resume the paused step |
| `: abort` | Stop the active step, continue with next |
| `: restart pair` | Restart a step from scratch |
| `: rerun pair` | Rerun a completed step with the same input |
| **Injections** | |
| `: inject "use PostgreSQL, not MongoDB"` | Send correction to the active lead |
| `: inject "add rate limiting to all endpoints"` | Send instruction to the lead |
| `: inject "stop, the approach is wrong. Use event sourcing"` | Course correction |
| **Eyes (hot-swap)** | |
| `: eyes add perf` | Add a lens to the active pair |
| `: eyes remove arch` | Remove a lens |
| `: eyes list` | Show active lenses |
| **Pipeline save** | |
| `: copy pipeline` | Copy current pipeline to clipboard |
| `: save pipeline as my_flow` | Save pipeline as reusable template |

### Command Mode Autocomplete

The command prompt has its own context-aware autocomplete:

```
: [TAB]
  add    remove    replace    move    pause    resume    abort
  restart    rerun    inject    eyes

: add [TAB]
  review(^)    devil(^)    pair()    test    commit    pr    impl()

: add review(^) [TAB]
  after    before

: add review(^) after [TAB]
  pair    test    pr                    ← only existing steps

: eyes [TAB]
  add    remove    list

: eyes add [TAB]
  perf    dx    test                   ← only lenses not yet active

: inject "[TAB]
  ← free text, no autocomplete
```

### Implementation

```python
class CommandInput(Static):
    """Mini-prompt at the bottom of the screen for pipeline commands."""
    
    def __init__(self):
        super().__init__()
        self.visible = False
    
    def on_key(self, event):
        if event.key == "escape":
            self.visible = False
            self.refresh()
        elif event.key == "enter":
            self.app.handle_command(self.value)
            self.visible = False
            self.refresh()


class LionApp(App):
    
    BINDINGS = [
        # ... bestaande bindings ...
        Binding("colon", "command_mode", "Command", key_display=":"),
    ]
    
    def action_command_mode(self):
        """Open the command prompt."""
        cmd_input = self.query_one(CommandInput)
        cmd_input.visible = True
        cmd_input.focus()
    
    async def handle_command(self, cmd: str):
        parts = cmd.strip().split(maxsplit=1)
        action = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        match action:
            case "add":
                await self._cmd_add(args)
            case "remove":
                await self._cmd_remove(args)
            case "replace":
                await self._cmd_replace(args)
            case "inject":
                await self._cmd_inject(args)
            case "pause":
                await self._cmd_pause()
            case "resume":
                await self._cmd_resume()
            case "abort":
                await self._cmd_abort()
            case "eyes":
                await self._cmd_eyes(args)
    
    async def _cmd_add(self, args: str):
        """Parse: 'review(^) after pair' or 'devil(^) before test'"""
        if " after " in args:
            step_def, _, target = args.partition(" after ")
            target = target.strip()
            new_step = self.parser.parse_step(step_def.strip())
            idx = self._find_step_index(target)
            self.steps.insert(idx + 1, new_step)
        elif " before " in args:
            step_def, _, target = args.partition(" before ")
            target = target.strip()
            new_step = self.parser.parse_step(step_def.strip())
            idx = self._find_step_index(target)
            self.steps.insert(idx, new_step)
        
        self._rebuild_panels()
        self._flash_modified()
    
    async def _cmd_inject(self, args: str):
        """You are the eye -- send a correction to the lead."""
        message = args.strip().strip("\"'")
        active = self._get_active_step()
        
        if active and hasattr(active, 'lead') and active.lead:
            active.lead.terminate()
            
            # Show inject box in TUI
            self.show_inject(self.active_step_index, {
                "message": message,
                "source": "manual",
            })
            
            # Resume with your correction
            active.lead.resume(
                f"User correction: {message}\n\n"
                f"Fix the above issue and continue implementing."
            )
    
    async def _cmd_eyes(self, args: str):
        """Hot-swap eyes on the active pair() step."""
        parts = args.split(maxsplit=1)
        sub_action = parts[0]  # add | remove | list
        
        active = self._get_active_step()
        if not active or active.type != "pair":
            return
        
        match sub_action:
            case "add":
                lens_name = parts[1].strip()
                new_eye = self._create_eye(lens_name)
                active.eyes.append(new_eye)
                self.update_eye_status(
                    self.active_step_index, new_eye.name, "waiting"
                )
            case "remove":
                lens_name = parts[1].strip()
                active.eyes = [e for e in active.eyes if e.lens != lens_name]
                self._remove_eye_widget(self.active_step_index, lens_name)
            case "list":
                # Show in status bar
                names = [e.name for e in active.eyes]
                self.notify(f"Active eyes: {', '.join(names)}")
    
    def _find_step_index(self, name: str) -> int:
        """Find a step by name (fuzzy match on prefix)."""
        for i, step in enumerate(self.steps):
            if step.name.startswith(name):
                return i
        return len(self.steps) - 1
    
    def _flash_modified(self):
        """Flash 'MODIFIED' in the pipeline sidebar."""
        sidebar = self.query_one("#pipeline-sidebar")
        sidebar.border_title = "Pipeline ── MODIFIED"
        sidebar.refresh()
```

### Scenario: Full Interactive Session

This is what a real session can look like with live editing:

```
lion > Build complete user management -> pair(claude, eyes: sec) -> test -> pr

# [pair() starts, you watch the streaming output]

# Hmm, no architecture review... add one
: eyes add arch

# [eye:arch also checking now, finds nothing]

# Oh wait, I want it to use PostgreSQL
: inject "Use PostgreSQL with SQLAlchemy, not SQLite"

# [lead interrupted, resumes with PostgreSQL]

# Actually I also want a review step before tests
: add review(^) after pair

# [pair() gaat verder...]
# [pair() done -> review(^) starts automatically]
# [review done -> test starts automatically]

# Tests fail! I want pair again with the errors
: add pair(claude, eyes: sec+arch) after test

# [test output forwarded to new pair() round]
# [pair() round 2 fixes the issues]
# [pr step running]

# Done!
```

You don't build the pipeline upfront -- you build it *while watching what happens*. Just like in an IDE you don't plan everything before starting, but adjust as you go.

---

## Pipeline Templates -- Composable Pipelines

Pipelines you use often are saved as templates. Templates aren't special syntax -- they're just pipeline steps you call by name. And templates can contain other templates.

### Config

```toml
# ~/.lion/config.toml

[pipelines]
quick = "pair(claude, eyes: sec) -> test"
safe = "pair(claude, eyes: sec+arch) -> review_cycle -> test -> pr"
thorough = "pair(claude, eyes: sec+arch+perf+dx) -> devil(^) -> test --coverage -> pr"
yolo = "impl() -> commit"
review_cycle = "review(^) -> devil(^)"
deploy = "test --coverage -> pr -> deploy_staging"
```

### Usage

Templates are steps. You append them after your prompt, just like any other step:

```
lion > Build payment system -> safe
lion > Fix login bug -> quick
lion > Build payment gateway -> thorough
lion > Change button color -> yolo
```

### Extending Templates

Because templates are just steps, you can add steps to them:

```
lion > Build auth -> safe -> deploy
# expands to:
#   Build auth -> pair(claude, eyes: sec+arch) -> review(^) -> devil(^) -> test -> pr -> deploy_staging

lion > Build API -> quick -> review(^)
# expands to:
#   Build API -> pair(claude, eyes: sec) -> test -> review(^)
```

### Templates in Templates

Templates can reference other templates. The parser expands recursively:

```toml
[pipelines]
review_cycle = "review(^) -> devil(^)"
safe = "pair(claude, eyes: sec+arch) -> review_cycle -> test -> pr"
full = "safe -> deploy"
```

```
lion > Build auth -> full
# expands to:
#   Build auth -> pair(claude, eyes: sec+arch) -> review(^) -> devil(^) -> test -> pr -> deploy_staging
```

### Copy Pipeline

After a session with live edits you want to save the pipeline. `: copy pipeline` copies the current pipeline (including all live edits) to clipboard:

```
: copy pipeline
# → clipboard: pair(claude, eyes: sec+arch) -> review(^) -> devil(^) -> test -> pr
```

Paste it in your next command:

```
lion > Build user management -> pair(claude, eyes: sec+arch) -> review(^) -> devil(^) -> test -> pr
```

Or save it as a template:

```
: save pipeline as my_flow
# -> adds to ~/.lion/config.toml:
# [pipelines]
# my_flow = "pair(claude, eyes: sec+arch) -> review(^) -> devil(^) -> test -> pr"
```

Then you use it from now on as:

```
lion > Build anything -> my_flow
```

### Parser: Template Expansion

```python
def expand_pipeline(steps: list[str], templates: dict[str, str]) -> list[str]:
    """
    Expandeer templates recursief.
    
    Input:  ["pair(claude, eyes: sec)", "safe", "deploy"]
    Output: ["pair(claude, eyes: sec)", "pair(claude, eyes: sec+arch)",
             "review(^)", "devil(^)", "test", "pr", "deploy_staging"]
    """
    expanded = []
    for step in steps:
        step_name = step.split("(")[0].strip()  # "pair(claude)" → "pair"
        
        if step_name in templates:
            # It's a template -- expand recursively
            sub_steps = templates[step_name].split("->")
            sub_steps = [s.strip() for s in sub_steps]
            expanded.extend(expand_pipeline(sub_steps, templates))
        else:
            # It's a regular step
            expanded.append(step)
    
    return expanded
```

---

## Two Modes

### 1. Interactive (REPL + TUI)

```bash
$ lion
🦁 Lion CLI -- Streaming LLM Scheduler
   Tab for autocomplete. Ctrl+D to exit.

lion > Build auth -> pair(claude, eyes: sec+arch) -> test -> pr
# ↑ REPL for input (prompt_toolkit)
# ↓ TUI for output (textual) -- panels, streaming, navigation
```

The REPL and TUI alternate:
1. **REPL** (prompt_toolkit): you type the command with autocomplete
2. **TUI** (textual): pipeline panels appear, you navigate and review
3. **REPL**: afterwards back to `lion >` for the next command

### 2. Direct (one-shot)

```bash
$ lion Build auth -> pair(claude, eyes: sec+arch) -> test -> pr
# Same TUI output, but exit when done
```

### 3. Headless (for scripts/CI)

```bash
$ lion --headless Build auth -> pair(claude, eyes: sec) -> test
# No TUI, plain text output, exit code 0/1
# Usable in CI/CD pipelines
```

---

## Implementation: TUI with Textual

### Architecture

```
lioncli/
├── cli.py                  # Entry point: REPL or direct mode
├── parser.py               # Splits input into prompt + pipeline
├── scheduler.py            # Spawns and manages CLI subprocesses
├── tui/
│   ├── app.py              # Textual App: the main TUI
│   ├── pipeline_sidebar.py # Pipeline overview (the steps)
│   ├── step_panel.py       # One step: streaming code + eyes
│   ├── eye_widget.py       # Eye status: checking/clean/finding
│   ├── interrupt_box.py    # Interrupt notification with finding
│   └── summary_view.py     # Summary view after pipeline completion
├── interceptors/
│   ├── base.py             # Abstract StreamInterceptor
│   ├── claude.py           # claude -p --output-format stream-json
│   ├── gemini.py           # gemini CLI
│   └── codex.py            # codex exec --json
├── eyes/
│   ├── eye.py              # Eye runner with parallel checks
│   └── lenses.py           # Lens prompt templates
├── primitives/
│   ├── pair.py             # pair() loop: lead + eyes + interrupt
│   ├── impl_.py            # impl(): simple generation
│   ├── review.py           # review(): check output
│   ├── fuse.py             # fuse(): multi-agent deliberation
│   └── git.py              # test, commit, pr: git integrations
└── config.py               # TOML config loading
```

### Core TUI: app.py

```python
"""
Lion TUI -- Live pipeline visualization with Textual.
"""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, RichLog, Label
from textual.reactive import reactive
from textual.binding import Binding


class PipelineStep:
    """Data model for one pipeline step."""
    
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.status = "waiting"     # waiting | active | done | failed
        self.output = ""
        self.interrupts = []
        self.duration = 0
        self.lines = 0
        self.eye_statuses = {}      # {"gemini:sec": "clean", "codex:arch": "checking"}


class StepPanel(ScrollableContainer):
    """
    Widget for one pipeline step.
    Toont streaming code output, eye status, en interrupts.
    """
    
    def __init__(self, step: PipelineStep):
        super().__init__()
        self.step = step
    
    def compose(self) -> ComposeResult:
        # Code output -- scrollbaar, live updating
        yield RichLog(id="code-output", highlight=True, markup=True)
        
        # Eyes status bar
        yield Horizontal(
            *[EyeStatus(name) for name in self.step.eye_statuses],
            id="eyes-bar"
        )
    
    def append_code(self, text: str):
        """Add streaming code -- becomes visible live."""
        self.query_one("#code-output", RichLog).write(text)
    
    def show_interrupt(self, finding: dict):
        """Show an interrupt box."""
        box = InterruptBox(finding)
        self.mount(box, before=self.query_one("#eyes-bar"))


class EyeStatus(Static):
    """Widget for the status of one eye."""
    
    status = reactive("waiting")
    
    def __init__(self, name: str):
        super().__init__()
        self.eye_name = name
    
    def render(self) -> str:
        icons = {
            "waiting": "○",
            "checking": "██░░",
            "clean": "✅",
            "finding": "⚠️",
        }
        icon = icons.get(self.status, "○")
        return f"  {self.eye_name}  {icon}  "


class InterruptBox(Static):
    """Widget for an interrupt notification."""
    
    def __init__(self, finding: dict):
        super().__init__()
        self.finding = finding
    
    def render(self) -> str:
        return (
            f"⚠️  INTERRUPT #{self.finding['number']}\n"
            f"[{self.finding['eye']}] {self.finding['description']}\n"
            f"Action: terminate → inject correction → resume"
        )


class PipelineSidebar(Static):
    """
    Sidebar with overview of all pipeline steps.
    Shows status, timing, and metrics per step.
    """
    
    def __init__(self, steps: list[PipelineStep]):
        super().__init__()
        self.steps = steps
    
    def render(self) -> str:
        lines = []
        for step in self.steps:
            icon = {"waiting": "○", "active": "●", "done": "✅", "failed": "❌"}[step.status]
            
            meta = ""
            if step.status == "active":
                meta = "streaming..."
            elif step.status == "done":
                parts = []
                if step.duration:
                    parts.append(f"{step.duration}s")
                if step.interrupts:
                    parts.append(f"{len(step.interrupts)} interrupts")
                if step.lines:
                    parts.append(f"{step.lines} lines")
                meta = "  ".join(parts)
            elif step.status == "waiting":
                meta = "waiting..."
            
            lines.append(f"  {icon} {step.name:<40} {meta}")
        
        return "\n".join(lines)


class LionApp(App):
    """
    De hoofd Lion TUI applicatie.
    
    Manages the pipeline sidebar and the active step panels.
    Navigate between steps with Tab/Shift+Tab.
    """
    
    CSS = """
    #pipeline-sidebar {
        dock: top;
        height: auto;
        max-height: 8;
        border: solid #ff8c00;
        padding: 0 1;
    }
    
    #step-panel {
        border: solid #4a9eff;
        padding: 0 1;
    }
    
    #eyes-bar {
        dock: bottom;
        height: 3;
        border: solid #666;
        padding: 0 1;
    }
    
    InterruptBox {
        border: solid #ffaa00;
        padding: 0 1;
        margin: 1 0;
    }
    
    .done #step-panel {
        border: solid #666;
    }
    """
    
    BINDINGS = [
        Binding("tab", "next_step", "Next step"),
        Binding("shift+tab", "prev_step", "Previous step"),
        Binding("i", "toggle_interrupts", "Interrupt log"),
        Binding("c", "copy_code", "Copy code"),
        Binding("q", "quit", "Quit"),
        Binding("r", "replay", "Replay"),
    ]
    
    active_step_index = reactive(0)
    
    def __init__(self, steps: list[PipelineStep]):
        super().__init__()
        self.steps = steps
        self.panels = {}
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield PipelineSidebar(self.steps, id="pipeline-sidebar")
        
        # Create a panel for each step, show only the active one
        for i, step in enumerate(self.steps):
            panel = StepPanel(step, id=f"step-{i}")
            panel.display = (i == 0)
            self.panels[i] = panel
            yield panel
        
        yield Footer()
    
    def action_next_step(self):
        """Tab: go to next step."""
        if self.active_step_index < len(self.steps) - 1:
            self.panels[self.active_step_index].display = False
            self.active_step_index += 1
            self.panels[self.active_step_index].display = True
    
    def action_prev_step(self):
        """Shift+Tab: go to previous step."""
        if self.active_step_index > 0:
            self.panels[self.active_step_index].display = False
            self.active_step_index -= 1
            self.panels[self.active_step_index].display = True
    
    # --- Interface for the scheduler ---
    
    def stream_to_step(self, step_index: int, text: str):
        """Scheduler calls this to add streaming output."""
        self.panels[step_index].append_code(text)
    
    def update_step_status(self, step_index: int, status: str):
        """Scheduler calls this on status change."""
        self.steps[step_index].status = status
        self.query_one("#pipeline-sidebar", PipelineSidebar).refresh()
        
        # Auto-navigate to the new active step
        if status == "active":
            self.panels[self.active_step_index].display = False
            self.active_step_index = step_index
            self.panels[step_index].display = True
    
    def show_interrupt(self, step_index: int, finding: dict):
        """Scheduler calls this on an interrupt."""
        self.panels[step_index].show_interrupt(finding)
    
    def update_eye_status(self, step_index: int, eye_name: str, status: str):
        """Scheduler calls this on eye status update."""
        self.steps[step_index].eye_statuses[eye_name] = status
        # Update the eye widget in the panel
        for widget in self.panels[step_index].query(EyeStatus):
            if widget.eye_name == eye_name:
                widget.status = status
```

### Scheduler → TUI Bridge

```python
"""
scheduler.py -- Connects the pipeline execution with the TUI.

The scheduler runs the pipeline steps sequentially.
On every event (stream chunk, interrupt, step complete)
wordt de TUI geüpdatet via de LionApp methods.
"""

import asyncio
from tui.app import LionApp, PipelineStep
from interceptors.claude import ClaudeInterceptor
from interceptors.gemini import GeminiInterceptor
from interceptors.codex import CodexInterceptor
from eyes.eye import Eye
from eyes.lenses import LENSES


async def run_pipeline(pipeline: dict, app: LionApp):
    """
    Execute the pipeline and update the TUI on every event.
    
    pipeline = {
        "prompt": "Build auth system",
        "steps": [
            {"type": "pair", "model": "claude", "eyes": ["sec", "arch"]},
            {"type": "test"},
            {"type": "pr"},
        ]
    }
    """
    
    for i, step in enumerate(pipeline["steps"]):
        app.update_step_status(i, "active")
        
        if step["type"] == "pair":
            await run_pair_step(i, pipeline["prompt"], step, app)
        elif step["type"] == "test":
            await run_test_step(i, app)
        elif step["type"] == "pr":
            await run_pr_step(i, app)
        
        app.update_step_status(i, "done")


async def run_pair_step(step_index: int, prompt: str, config: dict, app: LionApp):
    """
    Execute pair() with live TUI updates.
    """
    # Setup lead
    lead = _get_interceptor(config["model"])
    
    # Setup eyes
    eyes = []
    for lens_name in config.get("eyes", []):
        eye_interceptor = GeminiInterceptor()  # default eye backend
        eyes.append(Eye(eye_interceptor, lens_name, LENSES[lens_name]["prompt"]))
    
    # Init eye statuses in TUI
    for eye in eyes:
        app.update_eye_status(step_index, eye.name, "waiting")
    
    lead.start(prompt)
    interrupt_count = 0
    lines_since_check = 0
    
    for chunk in lead.chunks():
        # Stream to TUI -- appears live
        app.stream_to_step(step_index, chunk.text)
        lines_since_check += chunk.text.count("\n")
        
        if lines_since_check >= 20:
            lines_since_check = 0
            
            # Update eyes in TUI: checking...
            for eye in eyes:
                app.update_eye_status(step_index, eye.name, "checking")
            
            # Run eye checks parallel
            findings = await _check_eyes_async(eyes, chunk.accumulated)
            
            # Update eye statuses
            for eye in eyes:
                found = any(f.eye_name == eye.name for f in findings)
                app.update_eye_status(step_index, eye.name, 
                                       "finding" if found else "clean")
            
            if findings:
                interrupt_count += 1
                for f in findings:
                    app.show_interrupt(step_index, {
                        "number": interrupt_count,
                        "eye": f.eye_name,
                        "description": f.description,
                    })
                
                # Interrupt + resume
                correction = _build_correction(findings)
                lead.resume(correction)


def _get_interceptor(model: str):
    return {
        "claude": ClaudeInterceptor,
        "gemini": GeminiInterceptor,
        "codex": CodexInterceptor,
    }[model]()
```

---

## Config: ~/.lion/config.toml

```toml
# ~/.lion/config.toml

# Defaults
default_lead = "claude"
default_eyes = ["gemini:sec", "codex:arch"]
check_every_lines = 20
max_interrupts = 10

# TUI
[tui]
theme = "dark"                  # dark | light
show_clock = true
auto_navigate = true            # auto-jump to active step
show_eye_progress = true        # toon eye progress bars

# CLI commands per model
[models.claude]
cmd = "claude"
args = ["-p", "--output-format", "stream-json"]
resume_flag = "--resume"

[models.gemini]
cmd = "gemini"
args = []

[models.codex]
cmd = "codex"
args = ["exec", "--json"]
resume_cmd = ["codex", "exec", "resume"]

# Lens prompts (customizable + extensible)
[lenses.sec]
name = "Security"
prompt = """Check this code for security issues only.
Look for: SQL injection, XSS, plaintext passwords, missing auth,
hardcoded secrets, missing input validation, insecure crypto.
Reply NONE if clean. Otherwise one sentence."""

[lenses.arch]
name = "Architecture"
prompt = """Check this code for architecture issues only.
Look for: tight coupling, missing abstractions, SOLID violations,
god classes, missing error handling, wrong patterns.
Reply NONE if clean. Otherwise one sentence."""

[lenses.perf]
name = "Performance"
prompt = """Check this code for performance issues only.
Look for: N+1 queries, missing indexes, memory leaks, blocking I/O,
unnecessary allocations, missing connection pooling.
Reply NONE if clean. Otherwise one sentence."""

[lenses.dx]
name = "Developer Experience"
prompt = """Check this code for developer experience issues only.
Look for: confusing naming, missing docs, overly complex logic,
inconsistent patterns, poor error messages.
Reply NONE if clean. Otherwise one sentence."""

[lenses.test]
name = "Testability"
prompt = """Check this code for testability issues only.
Look for: hard dependencies, missing interfaces, global state,
tight coupling that prevents mocking, side effects in constructors.
Reply NONE if clean. Otherwise one sentence."""

# Custom lenses -- you add these
# [lenses.hipaa]
# name = "HIPAA Compliance"
# prompt = "Check for HIPAA violations..."
```

---

## Three Modes

### 1. Interactive (REPL → TUI → REPL)

```bash
$ lion
🦁 Lion CLI
lion > Build auth -> pair(claude, eyes: sec) -> test -> pr   # REPL (autocomplete)
# [TUI starts with panels and streaming]
# [done]
lion > _                                                      # back to REPL
```

### 2. Direct (TUI → exit)

```bash
$ lion Build auth -> pair(claude, eyes: sec) -> test -> pr
# [TUI with panels and streaming]
# [done -> exit]
```

### 3. Headless (plain text → exit code)

```bash
$ lion --headless Build auth -> pair(claude, eyes: sec) -> test
# Plain text output, no TUI
# Exit code 0 = success, 1 = test failed, 2 = interrupt limit
# For CI/CD pipelines and scripts
```

---

## Dependencies

```
prompt_toolkit   >= 3.0    # REPL, autocomplete, history
textual          >= 0.80   # TUI: panels, widgets, navigatie
rich             >= 13.0   # Syntax highlighting, formatting (textual dependency)
tomli            >= 2.0    # TOML config parsing (stdlib in Python 3.11+)
```

Four dependencies. All mature, actively maintained, by well-known maintainers.

---

## Notifications

When a pipeline runs long and you're working in another terminal, you want to know when it's done or when Lion needs your input.

```
╭─ 🦁 Lion ───────────────────────────────────╮
│                                              │
│  ⚠️  pair() needs your input                 │
│  Eye found issue, inject or continue?        │
│                                              │
│  Pipeline: Build auth -> safe                │
│                                              │
╰──────────────────────────────────────────────╯
```

| Event | Notification |
|-------|-------------|
| Pipeline complete | "✅ Pipeline done: 3/3 steps passed (58s)" |
| Test failed | "❌ test failed: 2 failures. Review needed." |
| Interrupt limit reached | "⚠️ pair() hit max interrupts. Inject or abort?" |
| Eye finds critical issue | "🔴 [sec] SQL injection found. Pipeline paused." |
| Lead crashed | "💥 claude crashed. Retry or switch model?" |

**Implementation:** `notify-send` op Linux, `osascript` op macOS, of `plyer` (Python cross-platform notificatie library).

```toml
# ~/.lion/config.toml
[notifications]
enabled = true
on_complete = true       # notify when pipeline completes
on_failure = true        # notify on test failure
on_input_needed = true   # notify when inject/choice needed
sound = true             # sound on notification
```

---

## Quota & Cost Dashboard

You're running on flat-rate subscriptions, but there are quota limits. `lion status` shows a dashboard:

```
$ lion status

🦁 Lion -- Status Dashboard

╭─ Quota ─────────────────────────────────────────────────────────╮
│                                                                  │
│  Claude (Max)         ████████████████░░░░  78% used today       │
│  Gemini (Code Assist) ██████░░░░░░░░░░░░░░  32% used today      │
│  Codex (ChatGPT)      ████████████░░░░░░░░  61% used today      │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯

╭─ Today's Sessions ──────────────────────────────────────────────╮
│                                                                  │
│  #1  Build auth -> safe              47s  2 interrupts  ✅       │
│  #2  Fix login bug -> quick          12s  0 interrupts  ✅       │
│  #3  Build payment -> thorough       83s  4 interrupts  ● running│
│                                                                  │
│  Total: 142s active │ 6 interrupts │ 2 completed                 │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
```

Also available as a widget in the TUI via `: status`:

```
: status
# -> shows quota bars at the bottom of the screen
```

**Quota tracking:** Lion counts CLI calls per provider. No exact tokens (those aren't visible on flat-rate), but the number of sessions, interrupts, and eye checks per day.

```toml
# ~/.lion/config.toml
[quota]
claude_daily_warn = 80    # warn at 80% estimated usage
gemini_daily_warn = 80
codex_daily_warn = 80
```

---

## Git Strategy: Worktrees, Commits & Resume

The core of Lion's persistence: every pipeline step gets a commit. This gives you time-travel to any step -- whether you're in a worktree, on a branch, or everything has been merged to main.

### How It Works

```
lion > Build auth -> pair(claude, eyes: sec+arch) -> review(^) -> test -> pr
```

Lion does the following:

```
1. git worktree add .lion/work/build-auth -b lion/build-auth
2. pair() runs in the worktree
3. pair() done -> auto-commit:
   "lion: pair(claude, eyes: sec+arch) - Build auth"        ← hash: a1b2c3d
4. review(^) runs
5. review() done -> auto-commit:
   "lion: review - Applied suggestions"                      ← hash: e4f5g6h
6. test runs (no commit, changes nothing)
7. pr -> squash merge lion/build-auth -> main
   "Add auth system"                                         ← 1 clean commit
8. Cleanup worktree
```

**Your main branch sees only:** `Add auth system` -- one clean commit.

**The worktree branch had:** every intermediate step as a separate commit with its hash.

### Resume: Jump to Any Step

**Scenario 1: Worktree still exists (session just finished)**

```
$ lion resume 1 --from review

╭─ Pipeline ── RESUME from review(^) ────────────────────────────────────────╮
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)    47s   commit: a1b2c3d  (preserved)     │
│  ♻️  review(^)                             reset to a1b2c3d → rerunning    │
│  ○ test                                   waiting (will rerun)              │
│  ○ pr                                     waiting (will rerun)              │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯

# What Lion does:
# git reset --hard a1b2c3d  (back to after pair, before review)
# Run review(^) again with pair's output as input
# Run test, pr normally
```

**Scenario 2: Everything already merged to main (days later)**

You built auth last week. It's already in main. Now you want to rerun the review with an extra devil(^) step.

```
$ lion history

  #  │ Tijd              │ Command              │ Steps                    │ Status
─────┼───────────────────┼───────────────────────┼──────────────────────────┼────────
  1  │ last week       │ Build auth -> safe    │ pair→review→test→pr      │ ✅
                         │                       │ a1b2c3d → e4f5g6h       │

$ lion resume 1 --from review -> devil(^) -> test -> pr
```

Lion does:

```
1. Finds session 1 -> reads the commit hashes from session JSON
2. Finds hash a1b2c3d (pair output) -- this exists in main's history
3. git worktree add .lion/work/resume-auth -b lion/resume-auth
4. git reset --hard a1b2c3d   <- back to exactly the state after pair()
5. Runs review(^) -> commit
6. Runs devil(^) -> commit
7. Runs test
8. pr -> squash merge to main
```

**The hash is the anchor.** It doesn't matter if the hash lives in a worktree, on a branch, or has long been in main. `git reset --hard <hash>` always takes you back to that exact state.

**Scenario 3: Resume from an even earlier point**

You want to rerun pair() entirely, but with a different model:

```
$ lion resume 1 --from pair(gemini, eyes: sec+arch) -> review(^) -> test -> pr
```

Lion:

```
1. Finds the hash BEFORE pair -> the parent commit or the branch start
2. Creates worktree from that point
3. Runs pair() again, now with Gemini as lead
4. Everything after runs normally
```

**Scenario 4: Resume with modified pipeline**

You're not bound to the original pipeline. Mix and match:

```
# Original was: pair → review → test → pr
# Now you want: pair's output -> devil -> pair again -> test --coverage -> pr

$ lion resume 1 --from devil(^) -> pair(claude, eyes: sec+perf) -> test --coverage -> pr
```

### Session JSON with Commit Hashes

```json
{
  "id": "2026-02-23_143200_build-auth",
  "command": "Build auth -> safe",
  "worktree": ".lion/work/build-auth",
  "branch": "lion/build-auth",
  "base_commit": "f0f0f0f",
  "steps": [
    {
      "name": "pair(claude, eyes: sec+arch)",
      "status": "done",
      "commit_hash": "a1b2c3d",
      "commit_msg": "lion: pair(claude, eyes: sec+arch) - Build auth",
      "files_changed": ["auth/controller.py", "auth/models.py", "auth/routes.py"],
      "interrupts": 2,
      "duration": 47,
      "session_id": "sess_abc123"
    },
    {
      "name": "review(^)",
      "status": "done",
      "commit_hash": "e4f5g6h",
      "commit_msg": "lion: review - Applied suggestions",
      "files_changed": ["auth/controller.py"],
      "interrupts": 0,
      "duration": 12,
      "session_id": "sess_def456"
    },
    {
      "name": "test",
      "status": "done",
      "commit_hash": null,
      "duration": 8
    },
    {
      "name": "pr",
      "status": "done",
      "commit_hash": "merged_xyz",
      "pr_number": 47,
      "duration": 3
    }
  ]
}
```

### In the TUI: Resume Flow

When you run `lion resume`, Lion shows the session with commit hashes and lets you select a step:

```
╭─ Resume Session #1: Build auth -> safe ─────────────────────────────────────╮
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)       a1b2c3d   47s   184 lines           │
│  ✅ review(^)                          e4f5g6h   12s                        │
│  ✅ test                               ───       8s    14/14 passed         │
│  ✅ pr                                 merged    3s    PR #47               │
│                                                                             │
│  ↑↓ select start point │ Enter: resume │ Esc: cancel                        │
│                                                                             │
│  Tip: You can modify the pipeline:                                          │
│  lion resume 1 --from review -> devil(^) -> test --coverage -> pr           │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

You select review, press Enter:

```
╭─ Pipeline ── RESUME from review(^) ────────────────────────────────────────╮
│                                                                             │
│  Creating worktree from a1b2c3d...                                          │
│                                                                             │
│  ✅ pair(claude, eyes: sec+arch)    a1b2c3d  (preserved)                   │
│  ♻️  review(^)                       rerunning...                            │
│  ○ test                              waiting                                │
│  ○ pr                                waiting                                │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

### Via Command Mode (in an active session)

You can also jump back from a running session:

```
: rerun review
# -> git reset --hard to commit before review
# -> runs review + everything after it again

: rerun review -> devil(^) -> test --coverage -> pr
# -> git reset --hard to commit before review
# -> runs the modified pipeline
```

### Worktree Lifecycle

```
┌─── Pipeline Start ────────────────────────────────────────────┐
│                                                                │
│  git worktree add .lion/work/<task-slug> -b lion/<task-slug>   │
│  Each step: auto-commit in the worktree                       │
│                                                                │
├─── Pipeline Done ─────────────────────────────────────────────┤
│                                                                │
│  pr step: squash merge -> main (1 clean commit)                │
│  Worktree stays for 24h (for resume)                           │
│  After 24h: auto-cleanup (configurable)                        │
│                                                                │
├─── Resume ────────────────────────────────────────────────────┤
│                                                                │
│  Worktree still exists?                                        │
│    -> git reset --hard <hash>                                  │
│  Worktree gone, but hash in main?                              │
│    -> git worktree add ... && git reset --hard <hash>          │
│  Hash no longer found?                                         │
│    -> Fresh start, no resume possible                          │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
import subprocess
from pathlib import Path
from dataclasses import dataclass


@dataclass
class StepCommit:
    step_name: str
    commit_hash: str
    commit_msg: str


class WorktreeManager:
    """
    Manages git worktrees and commit-per-step for Lion sessions.
    """
    
    def __init__(self, base_dir: str = ".lion/work"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_path: Path | None = None
        self.branch: str | None = None
        self.step_commits: list[StepCommit] = []
    
    def create(self, task_slug: str) -> Path:
        """Create a worktree for a new session."""
        self.branch = f"lion/{task_slug}"
        self.worktree_path = self.base_dir / task_slug
        
        subprocess.run([
            "git", "worktree", "add",
            str(self.worktree_path), "-b", self.branch
        ], check=True)
        
        return self.worktree_path
    
    def create_from_hash(self, task_slug: str, commit_hash: str) -> Path:
        """Create a worktree from an existing commit hash.
        
        Works whether the hash is in main, on a branch, or in an old worktree.
        The hash is the anchor -- git always finds it.
        """
        self.branch = f"lion/{task_slug}-resume"
        self.worktree_path = self.base_dir / f"{task_slug}-resume"
        
        # Create worktree on a new branch point
        subprocess.run([
            "git", "worktree", "add",
            str(self.worktree_path), "-b", self.branch, commit_hash
        ], check=True)
        
        return self.worktree_path
    
    def commit_step(self, step_name: str, message: str) -> str:
        """Commit the current state as a step snapshot."""
        subprocess.run(
            ["git", "add", "-A"],
            cwd=self.worktree_path, check=True
        )
        
        # Check if there's anything to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.worktree_path
        )
        
        if result.returncode != 0:  # there are changes
            commit_msg = f"lion: {step_name} - {message}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.worktree_path, check=True
            )
            
            # Get the hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.worktree_path, capture_output=True, text=True
            )
            commit_hash = hash_result.stdout.strip()
            
            self.step_commits.append(StepCommit(
                step_name=step_name,
                commit_hash=commit_hash,
                commit_msg=commit_msg
            ))
            
            return commit_hash
        
        return self.step_commits[-1].commit_hash if self.step_commits else ""
    
    def reset_to_step(self, step_index: int) -> None:
        """Reset the worktree to the state after a specific step."""
        if step_index < len(self.step_commits):
            target_hash = self.step_commits[step_index].commit_hash
            subprocess.run(
                ["git", "reset", "--hard", target_hash],
                cwd=self.worktree_path, check=True
            )
    
    def squash_merge_to_main(self, commit_message: str) -> None:
        """Squash merge all step-commits to main as 1 clean commit."""
        # From the main repo (not the worktree)
        subprocess.run([
            "git", "merge", "--squash", self.branch
        ], check=True)
        subprocess.run([
            "git", "commit", "-m", commit_message
        ], check=True)
    
    def cleanup(self) -> None:
        """Remove worktree and branch."""
        if self.worktree_path and self.worktree_path.exists():
            subprocess.run([
                "git", "worktree", "remove", str(self.worktree_path)
            ], check=True)
        if self.branch:
            subprocess.run([
                "git", "branch", "-D", self.branch
            ], check=False)  # branch may already be gone


class SessionResumer:
    """
    Resume a session from a specific step.
    
    Finds the commit hash, creates a worktree, 
    and runs the pipeline from that point.
    """
    
    def __init__(self, session: dict):
        self.session = session
        self.wt = WorktreeManager()
    
    def resume_from_step(self, step_name: str, new_pipeline: list | None = None):
        """
        Resume the session from a step.
        
        1. Finds the commit hash of the step BEFORE the specified step
        2. Creates a worktree from that hash
        3. Returns the pipeline that needs to run
        """
        steps = self.session["steps"]
        
        # Find the step index
        target_idx = None
        for i, step in enumerate(steps):
            if step["name"].startswith(step_name):
                target_idx = i
                break
        
        if target_idx is None:
            raise ValueError(f"Step '{step_name}' not found in session")
        
        # The hash of the step BEFORE is our starting point
        if target_idx == 0:
            # Resume from the beginning → use base_commit
            start_hash = self.session["base_commit"]
        else:
            start_hash = steps[target_idx - 1]["commit_hash"]
        
        # Create worktree from that hash
        task_slug = self.session["id"].split("_", 2)[-1]
        worktree_path = self.wt.create_from_hash(task_slug, start_hash)
        
        # Build the pipeline: everything from target_idx again
        if new_pipeline:
            remaining = new_pipeline
        else:
            remaining = [step["name"] for step in steps[target_idx:]]
        
        return {
            "worktree": worktree_path,
            "pipeline": remaining,
            "preserved_steps": steps[:target_idx],
            "start_hash": start_hash,
        }
```

### Config

```toml
# ~/.lion/config.toml
[git]
use_worktree = true                    # true = worktree per session
worktree_dir = ".lion/work"            # where worktrees live
auto_commit_per_step = true            # commit after each completed step
squash_on_pr = true                    # squash all step-commits on pr
cleanup_after_hours = 24               # auto-cleanup after 24 hours
branch_prefix = "lion/"                # prefix for Lion branches
```

---

## Session History & Replay

Every Lion session is saved with commit hashes, so you can always go back.

### `lion history`

```
$ lion history

🦁 Lion -- Session History

  #  │ Tijd              │ Command                    │ Steps                     │ Hashes
─────┼───────────────────┼─────────────────────────────┼───────────────────────────┼──────────────
  1  │ today 14:32     │ Build auth -> safe          │ pair→review→test→pr ✅    │ a1b2→e4f5
  2  │ today 11:15     │ Fix login bug -> quick      │ pair→test ✅              │ b2c3
  3  │ yesterday 16:45    │ Build payment -> thorough   │ pair→devil→test→pr ✅     │ c3d4→f6g7→h8i9
  4  │ yesterday 09:20    │ Refactor db -> safe         │ pair→review→test ⚠️       │ d4e5→g7h8

lion history> 
```

### `lion replay <nummer>`

Replays the session in the TUI -- streaming output, interrupts, and eye checks exactly as they happened, but sped up.

### `lion resume <nummer>`

Interactive: select a step to resume from.

```
$ lion resume 1
# -> shows all steps with hashes, select start point

$ lion resume 1 --from review
# -> resumes from review, everything after it runs again

$ lion resume 1 --from review -> devil(^) -> test --coverage -> pr
# -> resumes from review with modified pipeline

$ lion resume 1 --from pair(gemini, eyes: sec+perf)
# -> runs pair() again with different model, rest follows
```

### Storage

```
~/.lion/sessions/
├── 2026-02-23_143200_build-auth.json      # contains commit hashes per step
├── 2026-02-23_111500_fix-login.json
├── 2026-02-22_164500_build-payment.json
└── ...
```

---

## Error Recovery & Fallback

When a CLI crashes or refuses, Lion needs to handle it gracefully.

### Automatic Retry

```
[LEAD:claude] ▋ streaming...
[ERROR] claude process exited with code 1: "Rate limit exceeded"

>>> Auto-retry in 5s... (attempt 2/3)
>>> Resuming session...

[LEAD:claude] ▋ continuing...
```

### Model Fallback

When the primary lead fails repeatedly, Lion offers a fallback:

```
[ERROR] claude failed 3 times. 

╭─ Fallback ──────────────────────────────────────────────────────╮
│                                                                  │
│  Claude is unavailable. Options:                                 │
│                                                                  │
│  1. Switch lead to gemini (continue from current progress)       │
│  2. Switch lead to codex (continue from current progress)        │
│  3. Retry claude in 60s                                          │
│  4. Abort pipeline                                               │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
```

Or via command mode: `: fallback gemini`

### Config

```toml
# ~/.lion/config.toml
[recovery]
max_retries = 3
retry_delay = 5           # seconds
auto_fallback = false     # true = auto switch, false = ask first
fallback_order = ["gemini", "codex"]  # order for fallback
```

---

## Project Context: LION.md

Like `CLAUDE.md` for Claude Code, Lion supports a `LION.md` file in your project root. It's automatically passed to the lead and all eyes.

### Example: LION.md

```markdown
# Project: BricksPerBag

## Stack
- Python 3.12 + FastAPI
- PostgreSQL + SQLAlchemy  
- React + TypeScript frontend
- Docker Compose for development

## Conventions
- Type hints everywhere
- Async/await for all database calls
- Pydantic models for request/response
- Alembic for migrations
- pytest for tests

## Important
- All secrets via environment variables, never hardcoded
- API endpoints always with rate limiting
- All user input validated with Pydantic
- Database queries always via SQLAlchemy ORM, no raw SQL

## File structure
- src/api/       -> API routes
- src/models/    -> SQLAlchemy models
- src/services/  -> Business logic
- src/tests/     -> Test files
- migrations/    -> Alembic migrations
```

### How Lion Uses It

```python
def load_project_context() -> str:
    """Load LION.md if it exists in the current directory or parents."""
    for path in [Path.cwd(), *Path.cwd().parents]:
        lion_md = path / "LION.md"
        if lion_md.exists():
            return lion_md.read_text()
    return ""

def build_lead_prompt(task: str, context: str) -> str:
    """Combine task + project context for the lead."""
    if context:
        return f"""Project context:
{context}

Task: {task}"""
    return task

def build_eye_prompt(lens_prompt: str, context: str, code: str) -> str:
    """Combine lens + project context for the eye."""
    return f"""{lens_prompt}

Project context (use for your review):
{context}

Code to review:
```
{code}
```"""
```

The lead now knows you use PostgreSQL + SQLAlchemy, so it won't pick MongoDB. The security eye knows secrets must be via environment variables, so it flags hardcoded strings. The architecture eye knows you use async/await, so it flags blocking calls.

### Hierarchy (like CLAUDE.md)

```
~/.lion/LION.md              -> global preferences (always loaded)
~/project/LION.md            -> project-specific context
~/project/src/api/LION.md    → directory-specifieke overrides
```

---

## Roadmap

### v0.1 -- pair() + TUI foundation
- [ ] REPL with prompt_toolkit + context-aware autocomplete
- [ ] Parser: prompt + pipeline splitting on `->`
- [ ] StreamInterceptor for Claude, Gemini, Codex
- [ ] pair() loop with interrupt/resume
- [ ] TUI: pipeline sidebar + active step panel
- [ ] TUI: streaming code output with syntax highlighting
- [ ] TUI: eye status widgets (checking/clean/finding)
- [ ] TUI: interrupt boxes
- [ ] TUI: Tab navigation between steps
- [ ] TUI: command mode (`:`) with autocomplete
- [ ] TUI: `: inject` -- manual correction to lead
- [ ] TUI: `: add`/`: remove` -- add/remove steps
- [ ] TUI: `: eyes add`/`: eyes remove` -- hot-swap eyes
- [ ] TUI: `: pause`/`: resume`/`: abort` -- flow control
- [ ] TUI: file tracker + diff view (`f` and `d` keys)
- [ ] Git: WorktreeManager -- worktree per session
- [ ] Git: auto-commit per step with hash tracking
- [ ] Git: squash merge on `pr` step
- [ ] LION.md project context loading
- [ ] Config via ~/.lion/config.toml
- [ ] Command history
- [ ] Error recovery: auto-retry on crash

### v0.2 -- pipeline primitives + templates
- [ ] `test` primitive (pytest/npm test, output in panel)
- [ ] `pr` primitive (git add + commit + push + gh pr create)
- [ ] `commit` primitive
- [ ] `impl()` primitive (simple generation without eyes)
- [ ] Pipeline chaining: output step N → input step N+1
- [ ] `test` failure → back to `pair()` with error as correction
- [ ] Pipeline templates: `-> safe`, `-> quick`, `-> thorough`
- [ ] `: copy pipeline` en `: save pipeline as`
- [ ] Template expansie (templates in templates)

### v0.3 -- resume + operational
- [ ] Session history: `lion history` with commit hashes
- [ ] Session resume: `lion resume <nr> --from <step>`
- [ ] Resume with modified pipeline: `--from review -> devil(^) -> test`
- [ ] Resume from main (worktree from hash)
- [ ] Session replay: `lion replay <nr>`
- [ ] `: rerun <step>` from active session
- [ ] Desktop notifications (complete, failure, input needed)
- [ ] Quota dashboard: `lion status`
- [ ] Model fallback on repeated failure
- [ ] Worktree auto-cleanup after 24h

### v0.4 -- polish + advanced
- [ ] Fuzzy matching in autocomplete
- [ ] Headless mode for CI/CD
- [ ] Custom lenses via config
- [ ] Benchmark mode: `lion --benchmark "task"`
- [ ] LION.md hierarchy (global → project → directory)
- [ ] `devil(^)` primitive (devil's advocate review)

### v0.5 -- multi-agent
- [ ] `fuse()` primitive
- [ ] `task()` met parallelle worktrees
- [ ] Mutiny pattern: eye writes fix on interrupt
- [ ] Auto-complexity: detect which pipeline is needed

### v1.0 -- Rust rewrite (when design is stable)
- [ ] Rewrite core to Rust for single binary distribution
- [ ] `ratatui` for TUI (Rust equivalent of Textual)
- [ ] `reedline` for REPL (by Nushell team)
- [ ] Publish on crates.io and homebrew
- [ ] ~5ms startup, zero dependencies

---

*Ship v0.1 in Python. Use it daily. When the design is stable, rewrite to Rust.*