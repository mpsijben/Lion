#!/usr/bin/env python3
"""Gemini ACP turn POC.

Flow:
1) initialize + initialized
2) session/new
3) session/prompt with text part array
4) prints streamed session/update events and final result
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from acp_poc import GeminiACPClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gemini ACP prompt-turn POC")
    parser.add_argument(
        "--cwd",
        default=".",
        help="Working directory where Gemini ACP process runs",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: GEMINI_ACP_OK",
        help="Prompt text for the first ACP turn",
    )
    parser.add_argument(
        "--followup",
        default="",
        help="Optional second prompt in same session",
    )
    parser.add_argument(
        "--init-timeout",
        type=float,
        default=20.0,
        help="Initialize timeout in seconds",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=60.0,
        help="session/prompt timeout in seconds",
    )
    parser.add_argument(
        "--suppress-stderr",
        action="store_true",
        help="Hide Gemini stderr noise",
    )
    return parser


def _prompt_parts(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def _extract_session_id(response: dict[str, Any]) -> str:
    result = response.get("result", {})
    if not isinstance(result, dict):
        raise RuntimeError("session/new returned non-object result")
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("session/new did not return sessionId")
    return session_id


def run_prompt_turn(
    client: GeminiACPClient,
    session_id: str,
    prompt: str,
    timeout: float,
) -> dict[str, Any]:
    params = {
        "sessionId": session_id,
        "prompt": _prompt_parts(prompt),
    }
    return client.request(
        method="session/prompt",
        params=params,
        timeout=timeout,
        passthrough_notifications=True,
    )


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
            timeout=args.init_timeout,
            passthrough_notifications=False,
        )
        print("[INIT_RESPONSE]", json.dumps(init_resp, ensure_ascii=True))
        client.notify("initialized", {})
        print("[NOTIFY] initialized")

        session_resp = client.request(
            method="session/new",
            params={"cwd": args.cwd, "mcpServers": []},
            timeout=args.request_timeout,
            passthrough_notifications=False,
        )
        print("[SESSION_NEW]", json.dumps(session_resp, ensure_ascii=True))
        session_id = _extract_session_id(session_resp)
        print("[SESSION_ID]", session_id)

        first_resp = run_prompt_turn(
            client=client,
            session_id=session_id,
            prompt=args.prompt,
            timeout=args.request_timeout,
        )
        print("[TURN_RESULT_1]", json.dumps(first_resp, ensure_ascii=True))

        if args.followup:
            follow_resp = run_prompt_turn(
                client=client,
                session_id=session_id,
                prompt=args.followup,
                timeout=args.request_timeout,
            )
            print("[TURN_RESULT_2]", json.dumps(follow_resp, ensure_ascii=True))

        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
