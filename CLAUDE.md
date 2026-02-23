# Lion - Development Guide

## What is Lion?

Lion (Language for Intelligent Orchestration Networks) is a multi-agent AI framework for collaborative code development. It orchestrates multiple LLM instances through composable pipeline functions -- deliberation, review, testing, and deployment in a single CLI command.

## Project Structure

```
src/lion/               # Main source package
  lion.py               # CLI entry point (batch mode)
  parser.py             # Pipeline syntax parser (-> operator, functions, args)
  pipeline.py           # Pipeline execution engine
  memory.py             # SharedMemory - JSONL-based agent communication
  display.py            # Rich terminal rendering
  api.py                # REST API (FastAPI)
  hook.py               # Claude Code hook integration
  escalation.py         # Human-in-the-loop escalation

  functions/            # Pipeline functions (each is a standalone module)
    pride.py            # Multi-agent deliberation (propose/critique/converge)
    impl.py             # Code implementation (writes files)
    pair.py             # Real-time pair programming with stream interception
    review.py           # Code review (supports ^ self-healing)
    test.py             # Test runner with auto-fix
    devil.py            # Devil's advocate (challenges decisions)
    future.py           # Time-travel review
    create_tests.py     # Test generation
    lint.py             # Linting with auto-fix
    typecheck.py        # Type checking with auto-fix
    audit.py            # Security audit
    task.py             # Task decomposition
    distill.py          # Context compression
    context_build.py    # Shared context building
    onboard.py          # Documentation generation
    migrate.py          # Database migrations
    cost.py             # Cost analysis
    pr.py               # Pull request creation
    self_heal.py        # Self-healing coordinator

  providers/            # LLM provider abstractions
    base.py             # Abstract base class
    claude.py           # Anthropic Claude (via claude -p CLI)
    gemini.py           # Google Gemini (via gemini CLI)
    codex.py            # OpenAI Codex (via codex exec CLI)

  interceptors/         # Stream interception for pair()
    base.py             # Abstract StreamInterceptor
    claude.py           # Claude stream-json parser
    gemini.py           # Gemini stdout parser
    codex.py            # Codex JSONL parser

  lenses/               # Attention-steering system (9 built-in lenses)
    __init__.py         # Lens definitions and registry
    auto_assign.py      # Auto-assign lenses based on task keywords

  context/              # Layer 2: cross-agent context sharing
    package.py          # ContextPackage dataclass
    parser.py           # Parse structured output into context
    adapter.py          # Format context per LLM provider
    budget.py           # Token budget management
    archaeology.py      # Search previous run history
    prompts.py          # Context-related prompt templates

  cli/                  # Interactive REPL
    commands.py         # CLI command definitions
    repl.py             # prompt_toolkit REPL
    session.py          # Session management
    rich_renderer.py    # Rich rendering
    views.py            # CLI views

tests/                  # pytest test suite
docs/                   # Documentation
config.default.toml     # Default configuration (TOML)
```

## Key Patterns

### Pipeline Execution
The parser converts `"prompt" -> fn1() -> fn2()` into a list of `PipelineStep` objects. The pipeline executor runs them sequentially, passing output from each step to the next. The `<->` operator creates feedback loops, and `^` enables self-healing.

### Provider Abstraction
All LLM interaction goes through `providers/base.py`. Providers wrap CLI tools (claude, gemini, codex) via subprocess. Each provider handles streaming, token counting, and error recovery.

### Stream Interception
`pair()` uses `subprocess.Popen` to spawn a lead LLM process, intercepts the stdout stream, and feeds chunks to "eye" agents for real-time review. Eyes can trigger `proc.terminate()` to interrupt the lead, inject corrections, and resume.

### Shared Memory
Agents communicate through `SharedMemory` (JSONL file). Each entry has a phase (propose, critique, converge, implement), agent ID, and content. This enables cross-agent awareness without shared state.

### Context Modes
Three modes control how much metadata agents share: minimal (zero overhead), standard (reasoning + alternatives + confidence), rich (+ assumptions + beliefs + risks). Auto mode selects based on pipeline complexity.

## Commands

```bash
lion "prompt"                    # Batch mode, auto-selects pipeline
lion "prompt" -> pride(3)        # Explicit pipeline
lioncli                          # Interactive REPL
```

## Testing

```bash
pytest                           # Run all tests
pytest tests/test_parser.py      # Run specific test file
```

## Configuration

Default config: `config.default.toml`
User config: `~/.lion/config.toml`
Run history: `~/.lion/runs/`

## Conventions

- Never use em-dashes. Use regular dashes (-) or double dashes (--).
- Pipeline functions live in `src/lion/functions/` as standalone modules
- Each function module exports an `execute_<name>` function
- Providers are thin wrappers around CLI subprocess calls
- Tests mirror the source structure in `tests/`
- All documentation is in English
