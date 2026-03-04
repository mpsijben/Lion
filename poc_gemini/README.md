# Gemini ACP POC

This folder contains a minimal proof-of-concept for running Gemini CLI in ACP mode.

## File
- `poc_gemini/acp_poc.py`: JSON-RPC client over stdio for `gemini --experimental-acp`
- `poc_gemini/acp_turn_poc.py`: end-to-end prompt turn POC using `session/new` + `session/prompt`
- `poc_gemini/acp_wait_gate_poc.py`: WAIT marker gate POC (`continue` or `correct`)

## What this POC does
- Starts `gemini --experimental-acp`
- Sends `initialize`
- Sends `initialized` notification
- Optionally sends one custom JSON-RPC request
- Prints responses and async events

## Run

From repo root:

```bash
python poc_gemini/acp_poc.py init
```

Example custom request:

```bash
python poc_gemini/acp_poc.py request --method session/new --params '{"cwd":".","mcpServers":[]}'
```

If you want a different method:

```bash
python poc_gemini/acp_poc.py request --method '<method>' --params '{"k":"v"}'
```

Less noisy output:

```bash
python poc_gemini/acp_poc.py init --suppress-stderr
```

## Prompt Turn POC

Run one real prompt turn:

```bash
python poc_gemini/acp_turn_poc.py --prompt "Reply with exactly: GEMINI_ACP_OK" --suppress-stderr
```

Run a second prompt in the same session:

```bash
python poc_gemini/acp_turn_poc.py \
  --prompt "Reply with exactly: TURN1_OK" \
  --followup "Reply with exactly: TURN2_OK" \
  --suppress-stderr
```

## WAIT Gate POC

Continue path:

```bash
python poc_gemini/acp_wait_gate_poc.py \
  --decision continue \
  --suppress-stderr
```

Correction path:

```bash
python poc_gemini/acp_wait_gate_poc.py \
  --decision correct \
  --correction-prompt "Correction: output exactly STEP1_FIXED and DONE." \
  --suppress-stderr
```

## Notes
- ACP for Gemini CLI is experimental.
- Method names beyond `initialize`/`initialized` can vary by version.
- This is intentionally small: handshake-first so we can discover supported methods safely.
