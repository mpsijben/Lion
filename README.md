# Lion - Language for Intelligent Orchestration Networks

A multi-agent AI framework that turns single-model coding into real-time collaborative development. Multiple LLM instances deliberate, challenge, and build together -- all from a single CLI command.

## What Lion Does

```
Human -> 1 prompt -> multiple AI brains -> deliberation -> consensus -> superior result
```

Instead of asking one AI to write code and hoping it gets it right, Lion orchestrates multiple agents that **propose** approaches independently, **critique** each other, **converge** on the best plan, and **implement** it together. Errors are caught during generation, not after.

## Quick Example

```bash
# Simple: just describe what you want
lion "Fix the login bug"

# With a pipeline: deliberate, implement, review, test, and ship
lion "Build auth system" -> pride(3) -> impl() -> review(^) -> test -> pr

# Real-time pair programming: Claude builds while security + architecture eyes watch
lion "Build payment API" -> pair(claude, eyes: sec+arch) -> test -> pr

# Mix LLM providers for cognitive diversity
lion "Design database schema" -> pride(claude, gemini, codex) -> impl() -> test
```

## Key Concepts

### Pipeline Functions

Functions chain with `->` like Unix pipes. Each step receives the output of the previous one.

| Function | Purpose |
|----------|---------|
| `pride(n)` | Multi-agent deliberation (propose - critique - converge) |
| `impl()` | Implementation -- writes actual code |
| `pair(model, eyes: lens+lens)` | Real-time pair programming with stream interruption |
| `fuse(n)` | Real-time simultaneous deliberation |
| `review(^)` | Code review (`^` = self-healing: fix issues automatically) |
| `devil(^)` | Devil's advocate -- challenges decisions, not bugs |
| `test` | Run tests with auto-fix |
| `lint(^)` | Lint with auto-fix |
| `typecheck(^)` | Type check with auto-fix |
| `create_tests()` | Generate test suite |
| `task(n)` | Decompose into subtasks |
| `future(6m)` | Time-travel review -- "will this hurt in 6 months?" |
| `audit()` | Security audit |
| `pr()` | Create pull request |

### Lenses

Lenses steer agent attention to specific dimensions. Not personas ("you are a security expert") but focused instructions ("analyze ONLY for injection, auth bypass, and secret exposure").

| Lens | Focus |
|------|-------|
| `sec` | Security: injection, auth, crypto, secrets |
| `arch` | Architecture: coupling, patterns, SOLID |
| `perf` | Performance: N+1 queries, memory, connection pooling |
| `dx` | Developer experience: naming, readability |
| `maint` | Maintainability: complexity, duplication |
| `quick` | Pragmatic: ship fast, minimal viable |
| `data` | Data integrity: validation, consistency |
| `cost` | Cost awareness: API calls, compute |
| `test_lens` | Testability: dependencies, interfaces |

### Multi-LLM Support

Lion supports multiple LLM providers, enabling genuine cognitive diversity:

| Provider | CLI | Models |
|----------|-----|--------|
| Claude (Anthropic) | `claude -p` | haiku, sonnet, opus |
| Gemini (Google) | `gemini` | flash, pro |
| Codex (OpenAI) | `codex exec` | default |

Mix providers in a single pipeline:

```bash
# Cheap deliberation, premium implementation
lion "Build feature" -> pride(gemini, gemini) -> impl(claude.sonnet)
```

### Self-Healing with `^`

The `^` operator on analysis functions means "if you find issues, fix them yourself":

```bash
lion "Build API" -> pride(3) -> impl() -> review(^) -> devil(^) -> test -> pr
```

`review(^)` finds 3 issues? It fixes them and verifies. No expensive re-deliberation needed.

### Real-Time Pair Programming

Lion's `pair()` function is process-level stream interception -- not prompt chaining. The lead agent generates code while "eyes" watch the output stream in real-time, triggering hard interrupts when they spot issues:

```
LEAD (claude) streams code...
  "class AuthController:"
  "  def login(self, request):"
  "    password = request.body['password']"
         ^
         | HARD INTERRUPT (security eye)
         | "Never use plaintext passwords. Use bcrypt."
  "    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())"
```

Errors caught at line 5, not line 95.

## Installation

```bash
# Clone the repository
git clone https://github.com/mpsijben/Lion.git
cd Lion

# Run the installer
./install.sh

# Or install manually with pip
pip install -e .
```

The installer creates CLI wrappers, installs the Claude Code hook, and copies the default config.

### Requirements

- Python 3.11+
- At least one LLM CLI tool:
  - [Claude Code](https://claude.ai) (Max subscription)
  - [Gemini CLI](https://ai.google.dev) (Code Assist)
  - [Codex CLI](https://openai.com) (ChatGPT Plus/Pro)

### Configuration

Default config lives at `~/.lion/config.toml`. See [config.default.toml](config.default.toml) for all options.

Key settings:
- `default_profile`: `cheap`, `balanced`, or `premium` (controls model selection per phase)
- `providers.default`: default LLM provider
- `context.default_mode`: `auto`, `minimal`, `standard`, or `rich`

## Usage

### Batch Mode

```bash
lion "Build a feature"                              # auto-selects pipeline
lion "Build auth" -> pride(3) -> impl() -> test     # explicit pipeline
```

### Interactive REPL

```bash
lioncli                    # start interactive session
lioncli --debug            # with debug output
```

In the REPL, tab completion understands context and suggests models, lenses, and functions.

## Architecture

```
src/lion/
  lion.py              # Main CLI entry point
  parser.py            # Pipeline syntax parser
  pipeline.py          # Pipeline execution engine
  memory.py            # Shared memory (JSONL) for agents
  display.py           # Rich terminal UI
  api.py               # REST API interface

  functions/           # Pipeline functions (24 total)
    pride.py           # Multi-agent deliberation
    impl.py            # Code implementation
    pair.py            # Real-time pair programming
    review.py          # Code review
    test.py            # Test execution + auto-fix
    devil.py           # Devil's advocate
    future.py          # Time-travel review
    ...

  providers/           # LLM provider integrations
    claude.py          # Anthropic Claude
    gemini.py          # Google Gemini
    codex.py           # OpenAI Codex

  interceptors/        # Stream interception for pair()
    claude.py          # Claude stream handler
    gemini.py          # Gemini stream handler
    codex.py           # Codex stream handler

  lenses/              # Attention-steering system
  context/             # Layer 2: cross-agent context sharing
  cli/                 # Interactive REPL
```

## Documentation

Detailed documentation lives in [docs/](docs/):

- [LION.md](docs/LION.md) -- Full specification
- [syntax.md](docs/syntax.md) -- Pipeline syntax reference
- [lenses.md](docs/lenses.md) -- Lens system guide
- [context.md](docs/context.md) -- Context ecosystem (Layer 2)
- [pair.md](docs/pair.md) -- Real-time pair programming & fuse
- [self-healing.md](docs/self-healing.md) -- Self-healing architecture & pride/impl split
- [cli.md](docs/cli.md) -- CLI design & implementation
- [pair-poc.md](docs/pair-poc.md) -- Pair programming proof of concept

## Status

Alpha (v0.1.0). Core pipeline, deliberation, providers, lenses, context system, and pair programming are implemented. See [LION.md](docs/LION.md) for the full roadmap.

## License

MIT
