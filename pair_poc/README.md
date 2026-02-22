# pair_poc

POC-implementatie voor `docs/pair_poc.md`.

Alles in deze map is losgekoppeld van de bestaande Lion-runtime, zodat je veilig kunt experimenteren.

## Inhoud

- `interceptors.py`: basis `StreamInterceptor` + `ClaudeInterceptor`, `GeminiInterceptor`, `CodexInterceptor`
- `poc_runner.py`: runner voor experimenten `exp0` t/m `exp8`
- `mock_cli.py`: lokale mock om stream parsing te testen zonder externe API-calls
- `bevindingen.md`: eerste meetresultaten en blockers
- `POC_DOCUMENTATIE.md`: volledige POC-documentatie, experimentduiding en waarom deze test belangrijk is
- `results/`: JSON output per experiment (wordt automatisch aangemaakt)
- `.homes/`: lokale HOME-map per CLI voor sandbox-vriendelijke configbestanden

## Quickstart

```bash
cd /Users/mennosijben/Projects/lion
python pair_poc/poc_runner.py exp0
python pair_poc/poc_runner.py exp1
python pair_poc/poc_runner.py exp2
python pair_poc/poc_runner.py exp3
python pair_poc/poc_runner.py exp4
python pair_poc/poc_runner.py exp5
python pair_poc/poc_runner.py exp6
python pair_poc/poc_runner.py exp7
python pair_poc/poc_runner.py exp8
```

Met live progress:

```bash
python pair_poc/poc_runner.py exp2 --home-mode system --verbose --heartbeat-sec 3
```

`exp7` is bedoeld voor code + keuze-rationale (DECISIONS) in dezelfde run.
`exp8` start eyes vroeg (direct na eerste lead chunk) om near-real-time feedback te testen.

## HOME mode

Standaard gebruikt de runner `PAIR_POC_HOME_MODE` (default: `isolated`).

- `isolated`: gebruikt `pair_poc/.homes/*` (handig voor volledig lokale POC state)
- `system`: gebruikt je normale user-home (`~/.claude`, `~/.gemini`, `~/.codex`)

Voor jouw bestaande Lion-auth:

```bash
python pair_poc/poc_runner.py exp0 --home-mode system
python pair_poc/poc_runner.py exp1 --home-mode system
```

## Belangrijke notities

- Claude streaming met `--output-format stream-json` vereist ook `--verbose`.
- In sandbox-context schrijft elke CLI naar lokale HOME onder `pair_poc/.homes/*`.
- Als auth of netwerk ontbreekt, worden fouten in JSON-results vastgelegd in plaats van te crashen.
- Live events worden geschreven naar `pair_poc/results/expN.live.log`.
- Gemini CLI `0.16.x`: resume werkt via `--resume latest` en vereist prompt via `-p`.

## Mock test

```bash
python pair_poc/mock_cli.py claude "hello"
python pair_poc/mock_cli.py gemini "hello"
python pair_poc/mock_cli.py codex "hello"
```
