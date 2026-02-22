"""Tiny mock CLI to validate stream parsing without external APIs.

Examples:
  python pair_poc/mock_cli.py claude "hello"
  python pair_poc/mock_cli.py gemini "hello"
  python pair_poc/mock_cli.py codex "hello"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid


def emit(line: str) -> None:
    print(line, flush=True)
    time.sleep(0.08)


def mock_claude(prompt: str) -> None:
    sid = str(uuid.uuid4())
    emit(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
    emit(
        json.dumps(
            {
                "type": "assistant",
                "session_id": sid,
                "message": {"content": [{"type": "text", "text": f"Claude mock: {prompt}"}]},
            }
        )
    )
    emit(json.dumps({"type": "result", "result": "done", "session_id": sid}))


def mock_gemini(prompt: str) -> None:
    sid = str(uuid.uuid4())
    emit(json.dumps({"response": f"Gemini mock: {prompt}", "session_id": sid}))


def mock_codex(prompt: str) -> None:
    tid = str(uuid.uuid4())
    emit(json.dumps({"type": "thread.started", "thread_id": tid}))
    emit(json.dumps({"type": "item.delta", "delta": {"text": "Codex mock stream chunk 1"}}))
    emit(json.dumps({"type": "item.delta", "delta": {"text": "Codex mock stream chunk 2"}}))
    emit(json.dumps({"type": "item.completed", "item": {"text": f"Codex mock final: {prompt}"}}))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tool", choices=["claude", "gemini", "codex"])
    p.add_argument("prompt")
    args = p.parse_args()

    if args.tool == "claude":
        mock_claude(args.prompt)
    elif args.tool == "gemini":
        mock_gemini(args.prompt)
    elif args.tool == "codex":
        mock_codex(args.prompt)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
