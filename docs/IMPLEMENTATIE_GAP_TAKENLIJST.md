# LION Implementation Gap Analysis and Task List

## Scope of this review
Compared based on:
- Documentation: `README.md`, `docs/LION.md`, `docs/syntax.md`, `docs/cli.md`, `docs/pair_transport_backlog.md`, `docs/self-healing.md`
- Implementation: `src/lion/**`
- Test coverage: `tests/**`

## Short summary
- A lot of core functionality is already built: pipeline, pride/impl split, pair with transport modes, self-healing (`^`), context layer, audit/onboard/cost/migrate.
- Documentation is outdated on multiple points compared to the codebase (especially `audit()`/`onboard()` and multi-LLM status).
- There are also real gaps: `fuse()` is missing, `explain()` is missing, `ollama/api` providers are missing, pattern/custom-function CLI is missing.

## What is demonstrably implemented
- Parser + pipeline + operators: `->`, `<->`, `<N->`, `=>`, lens syntax `::`.
- Functions present and registered: `pride`, `impl`, `review`, `test`, `pr`, `create_tests`, `lint`, `typecheck`, `future`, `devil`, `context`, `distill`, `task`, `onboard`, `audit`, `cost`, `migrate`, `pair`.
- Pair transport architecture with capability-based mode selection (`auto|interrupt|wait|steer`).
- Interceptors present for:
  - `ClaudeLiveInterceptor`
  - `CodexAppServerInterceptor`
  - `GeminiACPInterceptor`
- Providers present for `claude`, `gemini`, `codex`.
- Session/history/resume infrastructure is present.
- Tests exist for parser/pipeline/pair/interceptors/audit/onboard/self-healing.

## Found mismatches (docs vs code)
1. `docs/syntax.md` previously marked `audit()` and `onboard()` as planned/not built; this has now been corrected.
2. `docs/syntax.md` previously marked mixed-LLM as “Not yet built”; this has now been corrected.
3. `README.md` lists `fuse(n)` as a key function, but there is no `fuse` function/registration in code.
4. `docs/LION.md` phase checklists still show many items as unchecked that are already implemented.

## Still missing or incomplete
1. `fuse()` primitive is missing in `src/lion/functions` and the function registry.
2. `explain()` function is missing (but referenced in spec/phase overview).
3. `providers/ollama.py` and `providers/api.py` are missing (listed in LION phase 4).
4. CLI command layer for patterns/custom functions is missing:
   - `lion pattern <name> = <pipeline>`
   - `lion function <name> "<description>"`
5. REST API (`src/lion/api.py`) is still a minimal Hello World instead of an orchestration API.
6. Test coverage appears weaker around `cost()` and `migrate()` (no dedicated test modules found).
7. `pair_transport_backlog.md` contains “next phases” that are already partly implemented; backlog status is not synchronized.

## Prioritized task list

### P0 - Make documentation reliable
- [x] Update `docs/syntax.md` status table and sections for `audit()`, `onboard()`, mixed-LLM.
- [ ] Update `README.md` function overview so only actually available functions are marked as available (or mark `fuse` as planned).
- [ ] Synchronize `docs/LION.md` phase checklists with the current codebase.
- [ ] Synchronize `docs/pair_transport_backlog.md` with current implementation status.

Acceptance criteria:
- No “planned/not built” claims remain for features that exist in `src/` + tests.
- No “implemented” claims remain for features that are missing.

### P1 - Close functional gaps
- [x] Implement `fuse()` as a real pipeline function (MVP semantics + tests).
- [ ] Implement `explain()` and register it in parser/autocomplete/docs.
- [ ] Add `providers/ollama.py` and integrate it into provider registry.
- [ ] Evaluate and implement `providers/api.py` or remove the claim from docs if intentionally out of scope.

Acceptance criteria:
- Functions are present in `FUNCTIONS` registry.
- Parser + autocomplete support the syntax.
- Tests exist for happy path + failure path.

### P2 - Productization and DX
- [ ] Add CLI support for pattern management (`lion pattern ...`).
- [ ] Add (or explicitly drop) custom function mechanism per spec.
- [ ] Expand `src/lion/api.py` into a real run API (submit prompt/pipeline, status, results).
- [ ] Add dedicated tests for `cost()` and `migrate()`.

Acceptance criteria:
- End-to-end scenarios for pattern/API are demonstrably covered by tests.

## Recommended execution order
1. Do P0 first (low risk, high trust impact).
2. Then P1 (`fuse` and provider gaps define architectural direction).
3. Then P2 (DX/API product layer).

## Note
This analysis is based on static code/doc review; I did not run the full test suite in this step.
