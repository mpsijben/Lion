#!/usr/bin/env python3
"""Gemini ACP WAIT-gate POC.

Implements a simple checkpoint flow:
1) Start session and run first prompt
2) Inspect streamed assistant message chunks for WAIT marker
3) If marker seen: send either CONTINUE or correction prompt
4) If no marker: do nothing (model already finished turn)
"""

from __future__ import annotations

import argparse
import json
import queue
import time
from typing import Any

from acp_poc import GeminiACPClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gemini ACP WAIT-gate POC")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument(
        "--first-prompt",
        default=(
            "Output exactly two lines: STEP1_OK and WAITING_FOR_REVIEW::step_1. "
            "Then stop."
        ),
        help="First turn prompt that may emit WAIT marker",
    )
    parser.add_argument(
        "--wait-marker",
        default="WAITING_FOR_REVIEW::step_1",
        help="Marker that triggers the gate decision",
    )
    parser.add_argument(
        "--decision",
        choices=["continue", "correct"],
        default="continue",
        help="Action when WAIT marker is detected",
    )
    parser.add_argument(
        "--continue-prompt",
        default="CONTINUE. Now output exactly STEP2_OK and DONE.",
        help="Prompt used when decision=continue",
    )
    parser.add_argument(
        "--correction-prompt",
        default="Correction: output exactly STEP1_FIXED and DONE.",
        help="Prompt used when decision=correct",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout for each request",
    )
    parser.add_argument(
        "--suppress-stderr",
        action="store_true",
        help="Hide Gemini stderr noise",
    )
    return parser


def _text_part(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def _session_new(client: GeminiACPClient, cwd: str, timeout: float) -> str:
    resp = client.request(
        method="session/new",
        params={"cwd": cwd, "mcpServers": []},
        timeout=timeout,
        passthrough_notifications=False,
    )
    result = resp.get("result", {})
    if not isinstance(result, dict) or not result.get("sessionId"):
        raise RuntimeError(f"session/new failed: {resp}")
    return str(result["sessionId"])


def _run_turn_and_capture(
    client: GeminiACPClient,
    session_id: str,
    prompt: str,
    timeout: float,
) -> tuple[dict[str, Any], str]:
    req_id = str(client._request_id + 1)  # noqa: SLF001 - POC only
    client._request_id += 1  # noqa: SLF001 - POC only
    client._send(  # noqa: SLF001 - POC only
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {"sessionId": session_id, "prompt": _text_part(prompt)},
        }
    )

    captured_text: list[str] = []
    response: dict[str, Any] | None = None
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            msg = client._q.get(timeout=0.25)  # noqa: SLF001 - POC only
        except queue.Empty:
            continue

        if msg.stream == "stderr":
            if not client.suppress_stderr:
                print(f"[STDERR] {msg.raw}")
            continue

        payload = msg.payload
        print(f"[EVENT] {json.dumps(payload, ensure_ascii=True)}")

        if (
            payload.get("method") == "session/update"
            and isinstance(payload.get("params"), dict)
        ):
            params = payload["params"]
            update = params.get("update", {})
            if (
                isinstance(update, dict)
                and update.get("sessionUpdate") == "agent_message_chunk"
            ):
                content = update.get("content", {})
                if isinstance(content, dict) and content.get("type") == "text":
                    text = content.get("text", "")
                    if text:
                        captured_text.append(text)

        if payload.get("id") == req_id:
            response = payload
            break

    if response is None:
        raise TimeoutError("timeout waiting for session/prompt response")
    return response, "".join(captured_text)


def main() -> int:
    args = build_parser().parse_args()
    client = GeminiACPClient(cwd=args.cwd, suppress_stderr=args.suppress_stderr)
    try:
        client.start()
        init_resp = client.request(
            method="initialize",
            params={
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
            timeout=args.timeout,
            passthrough_notifications=False,
        )
        print("[INIT_RESPONSE]", json.dumps(init_resp, ensure_ascii=True))
        client.notify("initialized", {})
        print("[NOTIFY] initialized")

        session_id = _session_new(client, args.cwd, args.timeout)
        print("[SESSION_ID]", session_id)

        turn1_resp, turn1_text = _run_turn_and_capture(
            client=client,
            session_id=session_id,
            prompt=args.first_prompt,
            timeout=args.timeout,
        )
        print("[TURN1_RESULT]", json.dumps(turn1_resp, ensure_ascii=True))
        print("[TURN1_TEXT]", json.dumps(turn1_text, ensure_ascii=True))

        saw_wait = args.wait_marker in turn1_text
        print("[WAIT_SEEN]", saw_wait)
        if not saw_wait:
            print("[GATE] No WAIT marker; leaving stream as-is.")
            return 0

        follow_prompt = (
            args.continue_prompt
            if args.decision == "continue"
            else args.correction_prompt
        )
        print("[GATE_DECISION]", args.decision)
        print("[FOLLOWUP_PROMPT]", json.dumps(follow_prompt, ensure_ascii=True))

        turn2_resp, turn2_text = _run_turn_and_capture(
            client=client,
            session_id=session_id,
            prompt=follow_prompt,
            timeout=args.timeout,
        )
        print("[TURN2_RESULT]", json.dumps(turn2_resp, ensure_ascii=True))
        print("[TURN2_TEXT]", json.dumps(turn2_text, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
