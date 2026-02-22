# Bevindingen POC `pair()` (status: 2026-02-22)

## Scope

Doel was verifiëren of de bouwblokken uit `docs/pair_poc.md` haalbaar zijn met de beschikbare CLIs in deze omgeving.

## Samenvatting

- Ja, technisch is de POC-architectuur haalbaar (stream interceptors, terminate/resume-loop, eye-check flow).
- De grootste blockers zijn operationeel: authenticatie en netwerktoegang.
- Hierdoor is in deze run vooral infrastructuur gevalideerd, niet de volledige kwaliteitsevaluatie van alle experimenten.

## Wat werkt

1. CLI binaries aanwezig:
   - `claude --version` -> `2.1.3 (Claude Code)`
   - `gemini --version` -> `0.16.0`
   - `codex --version` -> `codex-cli 0.104.0`
2. Claude stream-json formaat is parsebaar als JSONL events (`system`, `assistant`, `result`).
3. Codex `--json` formaat is parsebaar als JSONL events (`thread.started`, `error`, `turn.failed`).
4. Lokale HOME-per-CLI binnen `pair_poc/.homes/*` voorkomt sandbox-schrijfproblemen naar je user-home.

## Gevonden blockers

1. Claude:
   - `--output-format stream-json` zonder `--verbose` geeft direct fout.
   - Zonder geldige login/API-key: `Invalid API key · Please run /login`.
   - In deze sandbox verscheen ook: `EMFILE: too many open files, watch` (stderr warning).
2. Gemini:
   - Zonder ingestelde auth (`settings.json` of env vars) faalt call:
     `Please set an Auth method ... GEMINI_API_KEY ...`.
3. Codex:
   - JSON stream start wel, maar request faalt door netwerk:
     `stream disconnected before completion: error sending request for url (https://api.openai.com/v1/responses)`.

## Conclusie op haalbaarheid per experiment

1. Experiment 0 (checklist): gedeeltelijk geslaagd.
   - Installatie + outputformats bevestigd.
   - End-to-end responsen geblokkeerd door auth/netwerk.
2. Experiment 1 (Stream Interceptor): geslaagd op implementatie, beperkt gevalideerd op live data.
3. Experiment 2 (Terminate + Resume): technisch geïmplementeerd, live validatie vereist werkende sessies.
4. Experiment 3-6 (Eye checks, interrupt loop, mutiny, multi-eye): runner-flow staat klaar; inhoudelijke metrics volgen na auth/netwerk fix.

## Aanbevolen vervolg

1. Zet auth lokaal in `pair_poc/.homes/*`:
   - Claude: login in de lokale HOME-context.
   - Gemini: `GEMINI_API_KEY` of settings in lokale `.gemini`.
   - Codex: zorg voor werkende API-connectiviteit.
2. Draai daarna in volgorde:
   - `python pair_poc/poc_runner.py exp0`
   - `python pair_poc/poc_runner.py exp1`
   - `python pair_poc/poc_runner.py exp2`
   - `python pair_poc/poc_runner.py exp3`
   - `python pair_poc/poc_runner.py exp4`
   - `python pair_poc/poc_runner.py exp5`
   - `python pair_poc/poc_runner.py exp6`
3. Gebruik `pair_poc/results/*.json` als bron voor de definitieve metric-tabellen.
