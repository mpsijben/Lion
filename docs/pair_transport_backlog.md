# Pair Transport Backlog (Claude + Codex + Gemini + Legacy Fallback)

This backlog turns the protocol insights into executable implementation phases.

## Phase 1 (Implemented)
- Add interceptor capability model (`supports_steer`, `supports_wait_gate`, etc.).
- Add pair mode routing:
  - `auto`
  - `interrupt`
  - `wait`
  - `steer` (currently falls back where unsupported)
- Add deferred findings strategy for `wait` mode:
  - findings are queued during generation
  - correction prompt is applied at natural turn boundary
- Keep hard-interrupt path as fallback.
- Keep legacy provider compatibility by default.

## Phase 2 (Next: Codex app-server transport)
1. Add `CodexAppServerTransport` in `src/lion/interceptors/` or `src/lion/transports/`.
2. Implement JSON-RPC lifecycle:
   - `initialize` / `initialized`
   - `thread/start`
   - `turn/start`
   - `turn/steer`
   - `turn/interrupt`
3. Map app-server events to `Chunk` stream (`agentMessage`, tool output, reasoning).
4. Add config switch:
   - `pair.codex_transport = exec|app_server|auto`
5. Promote `steer` mode to true steering when app-server path is active.

## Phase 3 (Next: Claude live stream-json input)
1. Add a dedicated Claude live session transport (stdin kept open).
2. Support multi-turn messaging in one subprocess:
   - first prompt
   - follow-up correction/continue prompts
3. Keep current `claude -p --resume` path as fallback.
4. Add config switch:
   - `pair.claude_transport = resume|live|auto`

## Phase 4 (Next: Gemini ACP transport hardening)
1. Move POC behavior into production transport abstraction.
2. Implement stable session methods:
   - `initialize` / `initialized`
   - `session/new`
   - `session/prompt`
3. Normalize `session/update` chunks to pair output stream.
4. Default Gemini to `wait` mode initially.

## Phase 5 (Unified policy + telemetry)
1. Introduce a provider-agnostic session transport interface.
2. Make `pair(mode:auto)` choose strategy by capabilities:
   - `steer` > `wait` > `interrupt`
3. Add telemetry per run:
   - selected mode
   - number of steers/interrupts/deferred applies
   - latency and token usage deltas by strategy

## Phase 6 (Legacy providers: Mistral/Vibe/etc.)
1. Keep `LegacyTransport` as always-available fallback.
2. If provider has no session transport, route automatically to:
   - `interrupt` mode
3. Ensure no behavior regression for unsupported providers.

