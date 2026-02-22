"""POC runner for pair() experiments from docs/pair_poc.md.

Usage:
  python pair_poc/poc_runner.py exp0
  python pair_poc/poc_runner.py exp1
  python pair_poc/poc_runner.py exp2
  python pair_poc/poc_runner.py exp3
  python pair_poc/poc_runner.py exp4
  python pair_poc/poc_runner.py exp5
  python pair_poc/poc_runner.py exp6
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import re
import threading

from interceptors import (
    ClaudeInterceptor,
    CodexInterceptor,
    GeminiInterceptor,
    StreamInterceptor,
    collect_interceptor_chunks,
    run_interceptor,
)


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
HOMES = ROOT / ".homes"
DEFAULT_HOME_MODE = os.environ.get("PAIR_POC_HOME_MODE", "isolated").strip().lower()
VERBOSE = False
HEARTBEAT_SEC = 5.0
LIVE_LOG_PATH: Path | None = None


@dataclass
class CommandCheck:
    name: str
    command: list[str]
    success: bool
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    category: str = "unknown"


def ensure_dirs() -> None:
    OUT.mkdir(exist_ok=True, parents=True)
    (HOMES / "claude").mkdir(exist_ok=True, parents=True)
    (HOMES / "gemini").mkdir(exist_ok=True, parents=True)
    (HOMES / "codex").mkdir(exist_ok=True, parents=True)


def classify_failure(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if "invalid api key" in text or "please run /login" in text or "set an auth method" in text:
        return "auth"
    if "eperm" in text or "operation not permitted" in text:
        return "sandbox"
    if "stream disconnected" in text or "reconnecting" in text:
        return "network"
    if "timeout" in text:
        return "timeout"
    return "unknown"


def _run_cmd(name: str, cmd: list[str], *, home: Path | None = None, timeout: int = 40) -> CommandCheck:
    start = time.time()
    env = os.environ.copy()
    env["LION_NO_RECURSE"] = "1"
    if home:
        env["HOME"] = str(home.resolve())
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=ROOT.parent,
        )
        check = CommandCheck(
            name=name,
            command=cmd,
            success=p.returncode == 0,
            exit_code=p.returncode,
            duration_ms=int((time.time() - start) * 1000),
            stdout=p.stdout.strip(),
            stderr=p.stderr.strip(),
        )
        if not check.success:
            check.category = classify_failure(check.stdout, check.stderr)
        else:
            check.category = "ok"
        return check
    except subprocess.TimeoutExpired as e:
        return CommandCheck(
            name=name,
            command=cmd,
            success=False,
            exit_code=124,
            duration_ms=int((time.time() - start) * 1000),
            stdout=(e.stdout or "").strip() if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "").strip() if isinstance(e.stderr, str) else "timeout",
            category="timeout",
        )


def write_json(name: str, payload: Any) -> Path:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    return path


def log_event(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"{ts} {message}"
    if VERBOSE:
        print(line, flush=True)
    if LIVE_LOG_PATH:
        with LIVE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def make_interceptors(home_mode: str) -> list[StreamInterceptor]:
    if home_mode == "system":
        return [
            ClaudeInterceptor(home_dir=None, cwd=str(ROOT.parent)),
            GeminiInterceptor(home_dir=None, cwd=str(ROOT.parent)),
            CodexInterceptor(home_dir=None, cwd=str(ROOT.parent)),
        ]
    return [
        ClaudeInterceptor(home_dir=str(HOMES / "claude"), cwd=str(ROOT.parent)),
        GeminiInterceptor(home_dir=str(HOMES / "gemini"), cwd=str(ROOT.parent)),
        CodexInterceptor(home_dir=str(HOMES / "codex"), cwd=str(ROOT.parent)),
    ]


def exp0(home_mode: str) -> dict[str, Any]:
    checks: list[CommandCheck] = []
    for tool in ("claude", "gemini", "codex"):
        if shutil.which(tool):
            checks.append(_run_cmd(f"{tool}_version", [tool, "--version"]))
        else:
            checks.append(
                CommandCheck(
                    name=f"{tool}_version",
                    command=[tool, "--version"],
                    success=False,
                    exit_code=127,
                    duration_ms=0,
                    stdout="",
                    stderr=f"{tool} not found in PATH",
                )
            )

    test_home = None if home_mode == "system" else HOMES / "claude"
    checks.append(
        _run_cmd(
            "claude_stream_test",
            ["claude", "-p", "Say hello", "--verbose", "--output-format", "stream-json"],
            home=test_home,
        )
    )
    test_home = None if home_mode == "system" else HOMES / "gemini"
    checks.append(
        _run_cmd(
            "gemini_json_test",
            ["gemini", "-o", "json", "Say hello"],
            home=test_home,
        )
    )
    test_home = None if home_mode == "system" else HOMES / "codex"
    checks.append(
        _run_cmd(
            "codex_json_test",
            ["codex", "exec", "--json", "Say hello"],
            home=test_home,
        )
    )

    payload = {
        "experiment": "exp0",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "checks": [asdict(c) for c in checks],
    }
    write_json("exp0.json", payload)
    return payload


def exp1(home_mode: str) -> dict[str, Any]:
    prompt = (
        "Write a Python function that sorts a list using quicksort. "
        "Reply with plain text/code only. "
        "Do not use tools, do not read or write files, do not run commands."
    )
    runs = []
    for interceptor in make_interceptors(home_mode):
        run = run_interceptor(interceptor, prompt, on_event=log_event, heartbeat_sec=HEARTBEAT_SEC)
        runs.append(run)
    payload = {"experiment": "exp1", "home_mode": home_mode, "timestamp": int(time.time()), "runs": runs}
    write_json("exp1.json", payload)
    return payload


def exp2(home_mode: str) -> dict[str, Any]:
    data = []
    for interceptor in make_interceptors(home_mode):
        marker = f"LION-CTX-{interceptor.name.upper()}-{int(time.time())}"
        prompt = (
            f"Remember this token exactly: {marker}. "
            "Write exactly 30 lines of Python pseudocode for an auth system "
            "(login/register/reset). No explanations."
        )
        correction = (
            "Continue exactly where you stopped. "
            "Output code only, max 20 lines, no planning, no questions, no tool use."
        )
        first = run_interceptor(
            interceptor,
            prompt,
            max_lines=6,
            terminate_after=4.0,
            on_event=log_event,
            heartbeat_sec=HEARTBEAT_SEC,
        )
        resume_started = time.time()
        try:
            log_event(f"[{interceptor.name}] resume start")
            interceptor.resume(correction)
            second = {
                "name": interceptor.name,
                "resumed": True,
                "chunks": collect_interceptor_chunks(
                    interceptor,
                    max_lines=6,
                    terminate_after=30.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                    started_at=resume_started,
                ),
                "ttft_ms": interceptor.stats.ttft_ms,
                "errors": interceptor.stats.errors,
            }
            log_event(f"[{interceptor.name}] resume done")
        except Exception as e:
            second = {"name": interceptor.name, "resumed": False, "error": str(e)}
            log_event(f"[{interceptor.name}] resume failed error={e}")

        context_prompt = (
            "What token did I ask you to remember earlier in this conversation? "
            "Reply with only that exact token."
        )
        context_check = {
            "prompt": context_prompt,
            "output": [],
            "ttft_ms": None,
            "errors": [],
            "context_preserved": False,
        }
        try:
            log_event(f"[{interceptor.name}] context-check start")
            interceptor.resume(context_prompt)
            check_chunks = collect_interceptor_chunks(
                interceptor,
                max_lines=2,
                terminate_after=12.0,
                on_event=log_event,
                heartbeat_sec=HEARTBEAT_SEC,
            )
            joined = "\n".join(check_chunks).strip()
            preserved = marker in joined
            context_check = {
                "prompt": context_prompt,
                "output": check_chunks,
                "ttft_ms": interceptor.stats.ttft_ms,
                "errors": interceptor.stats.errors,
                "context_preserved": preserved,
            }
            log_event(f"[{interceptor.name}] context-check done preserved={preserved}")
        except Exception as e:
            context_check = {
                "prompt": context_prompt,
                "output": [],
                "ttft_ms": None,
                "errors": [str(e)],
                "context_preserved": False,
            }
            log_event(f"[{interceptor.name}] context-check failed error={e}")

        second["restart_latency_ms"] = int((time.time() - resume_started) * 1000)
        data.append(
            {
                "marker_token": marker,
                "initial": first,
                "resume": second,
                "context_check": context_check,
            }
        )
    payload = {"experiment": "exp2", "home_mode": home_mode, "timestamp": int(time.time()), "runs": data}
    write_json("exp2.json", payload)
    return payload


def _eye_prompt(lens: str, code: str) -> str:
    return (
        f"[{lens.upper()} REVIEW]\n"
        "Check this code for issues. Reply NONE if clean, else one short finding.\n\n"
        f"{code[:5000]}"
    )


def _strict_auth_prompt(*, include_decision_log: bool = False) -> str:
    """Reusable strict lead prompt for auth experiments."""
    base = (
        "Write ONLY Python code for a deliberately quick-and-dirty auth module with login/register/reset. "
        "Output exactly one python code block. "
        "Do NOT ask questions. Do NOT inspect files. Do NOT mention permissions. "
        "Do NOT run tools or commands."
    )
    if not include_decision_log:
        return base
    return (
        base
        + " After the code block, add a short section titled DECISIONS with 3 bullets "
          "explaining key tradeoffs. No questions."
    )


def _looks_like_code(text: str) -> bool:
    """Heuristic: determine whether model output contains actionable code."""
    lowered = text.lower()
    if "```python" in lowered:
        return True
    return "def " in lowered or "class " in lowered


def _coalesce_ms(value: int | None, fallback: int = 999999) -> int:
    """Return numeric ms value, preserving 0 as valid."""
    return fallback if value is None else value


def _extract_focus_snippet(code: str, finding: str, max_chars: int = 2500) -> str:
    """Try to send only relevant code section to fixer model."""
    if not code.strip():
        return code
    lowered_finding = finding.lower()
    candidate_funcs = ["_hash_password", "_verify_password", "login", "register", "reset_password"]
    if "hash" in lowered_finding or "password" in lowered_finding:
        candidate_funcs = ["_hash_password", "_verify_password", "login", "register"]
    for fn in candidate_funcs:
        m = re.search(rf"def\s+{re.escape(fn)}\s*\(.*?(?=\n\ndef\s+|\Z)", code, flags=re.S)
        if m:
            snippet = m.group(0)
            if len(snippet) <= max_chars:
                return snippet
    return code[:max_chars]


def exp3(home_mode: str) -> dict[str, Any]:
    home_opt = None if home_mode == "system" else str(HOMES / "claude")
    gem_home_opt = None if home_mode == "system" else str(HOMES / "gemini")
    codex_home_opt = None if home_mode == "system" else str(HOMES / "codex")
    lead_map = {
        "claude": ClaudeInterceptor(home_dir=home_opt, cwd=str(ROOT.parent)),
        "gemini": GeminiInterceptor(home_dir=gem_home_opt, cwd=str(ROOT.parent)),
        "codex": CodexInterceptor(home_dir=codex_home_opt, cwd=str(ROOT.parent)),
    }
    matrix = []
    for lead_name, lead in lead_map.items():
        for eye_name, eye in lead_map.items():
            if lead_name == eye_name:
                continue
            log_event(f"[matrix] lead={lead_name} eye={eye_name}")
            lead_run = run_interceptor(
                lead,
                "Write a quick and dirty Python auth system.",
                max_lines=30,
                on_event=log_event,
                heartbeat_sec=HEARTBEAT_SEC,
            )
            code_blob = "\n".join(lead_run["output"])
            eye_run = run_interceptor(
                eye,
                _eye_prompt("security", code_blob),
                max_lines=3,
                on_event=log_event,
                heartbeat_sec=HEARTBEAT_SEC,
            )
            matrix.append({"lead": lead_name, "eye": eye_name, "lead_run": lead_run, "eye_run": eye_run})
    payload = {"experiment": "exp3", "home_mode": home_mode, "timestamp": int(time.time()), "matrix": matrix}
    write_json("exp3.json", payload)
    return payload


def exp4(home_mode: str) -> dict[str, Any]:
    lead = ClaudeInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "claude"), cwd=str(ROOT.parent))
    eye = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))
    lead_prompt = _strict_auth_prompt()
    lead_run = run_interceptor(
        lead,
        lead_prompt,
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    code_blob = "\n".join(lead_run["output"])
    eye_run = run_interceptor(
        eye,
        _eye_prompt("security", code_blob),
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )

    finding = "\n".join(eye_run["output"]) or "No finding"
    corrected = {}
    if finding and "NONE" not in finding.upper():
        try:
            resume_prompt = (
                "The security reviewer found this issue:\n"
                f"{finding}\n"
                "Rewrite the problematic parts and continue. "
                "Output only one python code block. "
                "No explanations, no questions, no permission text."
            )
            lead.resume(resume_prompt)
            corrected = {
                "resumed": True,
                "output": collect_interceptor_chunks(
                    lead,
                    max_lines=2,
                    terminate_after=25.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                ),
                "ttft_ms": lead.stats.ttft_ms,
            }
        except Exception as e:
            corrected = {"resumed": False, "error": str(e)}
    payload = {
        "experiment": "exp4",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "lead": lead_run,
        "eye": eye_run,
        "finding": finding,
        "corrected": corrected,
        "quality_signals": {
            "lead_has_question": "?" in code_blob,
            "lead_mentions_permissions": "permission" in code_blob.lower(),
            "corrected_mentions_permissions": "permission" in "\n".join(corrected.get("output", [])).lower() if corrected else False,
        },
    }
    write_json("exp4.json", payload)
    return payload


def exp5(home_mode: str) -> dict[str, Any]:
    lead = ClaudeInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "claude"), cwd=str(ROOT.parent))
    eye = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))
    fallback_fixer = CodexInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "codex"), cwd=str(ROOT.parent))
    lead_prompt = _strict_auth_prompt()
    lead_run = run_interceptor(
        lead,
        lead_prompt,
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    code_blob = "\n".join(lead_run["output"])
    lead_has_code = _looks_like_code(code_blob)
    finding_run = run_interceptor(
        eye,
        _eye_prompt("security", code_blob),
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )

    finding = "\n".join(finding_run["output"])
    fix_run = {
        "name": eye.name,
        "session_id": getattr(eye, "session_id", None),
        "ttft_ms": None,
        "chunk_count": 0,
        "errors": [],
        "output": [],
    }
    if lead_has_code and finding and "NONE" not in finding.upper():
        focus_snippet = _extract_focus_snippet(code_blob, finding)
        fix_prompt = (
            "You are the fixer eye. Rewrite ONLY the problematic section of the given code.\n"
            "Output only one python code block. No explanation.\n"
            f"Issue: {finding}\n\nCode:\n{focus_snippet}"
        )
        fix_run = run_interceptor(
            eye,
            fix_prompt,
            max_lines=2,
            terminate_after=40.0,
            on_event=log_event,
            heartbeat_sec=HEARTBEAT_SEC,
        )
        if not _looks_like_code("\n".join(fix_run.get("output", []))):
            log_event("[exp5] primary fixer had no code patch; trying fallback fixer codex")
            fix_run = run_interceptor(
                fallback_fixer,
                fix_prompt,
                max_lines=2,
                terminate_after=40.0,
                on_event=log_event,
                heartbeat_sec=HEARTBEAT_SEC,
            )
            fix_run["fallback_used"] = True
            fix_run["primary_fixer"] = "gemini"

    try:
        if fix_run["output"]:
            lead.resume(
                "The reviewer suggested this patch:\n"
                + "\n".join(fix_run["output"])[:4000]
                + "\nIntegrate the patch and output only one final python code block."
            )
            resume_run = {
                "resumed": True,
                "output": collect_interceptor_chunks(
                    lead,
                    max_lines=2,
                    terminate_after=25.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                ),
                "ttft_ms": lead.stats.ttft_ms,
            }
        else:
            resume_run = {
                "resumed": False,
                "reason": "skipped_resume_no_fix",
                "output": [],
                "ttft_ms": None,
            }
    except Exception as e:
        resume_run = {"resumed": False, "error": str(e)}

    payload = {
        "experiment": "exp5",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "lead": lead_run,
        "finding": finding_run,
        "fix": fix_run,
        "resume": resume_run,
        "quality_signals": {
            "lead_has_code": lead_has_code,
            "finding_has_issue": bool(finding.strip()) and "NO CODE" not in finding.upper(),
            "fix_has_code": _looks_like_code("\n".join(fix_run.get("output", []))),
            "resume_has_code": _looks_like_code("\n".join(resume_run.get("output", []))),
            "fallback_used": bool(fix_run.get("fallback_used", False)),
        },
    }
    write_json("exp5.json", payload)
    return payload


def exp6(home_mode: str) -> dict[str, Any]:
    lead = ClaudeInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "claude"), cwd=str(ROOT.parent))
    sec_eye = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))
    arch_eye = CodexInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "codex"), cwd=str(ROOT.parent))

    lead_run = run_interceptor(
        lead,
        _strict_auth_prompt(),
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    code_blob = "\n".join(lead_run["output"])
    lead_has_code = _looks_like_code(code_blob)

    # POC simplification: sequential execution, JSON contains timings for comparison.
    sec_start = time.time()
    sec_run = run_interceptor(
        sec_eye,
        _eye_prompt("security", code_blob),
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    sec_elapsed = int((time.time() - sec_start) * 1000)

    arch_start = time.time()
    arch_run = run_interceptor(
        arch_eye,
        _eye_prompt("architecture", code_blob),
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    arch_elapsed = int((time.time() - arch_start) * 1000)

    findings = {
        "security": "\n".join(sec_run["output"]),
        "architecture": "\n".join(arch_run["output"]),
    }
    resume_payload: dict[str, Any] = {}
    try:
        any_finding = any(v.strip() and "NONE" not in v.upper() for v in findings.values())
        if lead_has_code and any_finding:
            lead.resume(
                "Fix these findings in the code and output only one final python code block:\n"
                f"1) security: {findings['security']}\n"
                f"2) architecture: {findings['architecture']}"
            )
            resume_payload = {
                "resumed": True,
                "output": collect_interceptor_chunks(
                    lead,
                    max_lines=2,
                    terminate_after=25.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                ),
                "ttft_ms": lead.stats.ttft_ms,
            }
        else:
            resume_payload = {
                "resumed": False,
                "reason": "skipped_resume_no_findings_or_no_code",
                "output": [],
                "ttft_ms": None,
            }
    except Exception as e:
        resume_payload = {"resumed": False, "error": str(e)}

    payload = {
        "experiment": "exp6",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "lead": lead_run,
        "eyes": {
            "security": {"run": sec_run, "elapsed_ms": sec_elapsed},
            "architecture": {"run": arch_run, "elapsed_ms": arch_elapsed},
        },
        "findings": findings,
        "resume": resume_payload,
        "quality_signals": {
            "lead_has_code": lead_has_code,
            "security_has_finding": bool(findings["security"].strip()) and "NONE" not in findings["security"].upper(),
            "architecture_has_finding": bool(findings["architecture"].strip()) and "NONE" not in findings["architecture"].upper(),
            "resume_has_code": _looks_like_code("\n".join(resume_payload.get("output", []))),
        },
    }
    write_json("exp6.json", payload)
    return payload


def exp7(home_mode: str) -> dict[str, Any]:
    """Code + decision-log experiment.

    Goal: capture not only code, but concise rationale behind choices
    without drifting into question/clarification mode.
    """
    lead = ClaudeInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "claude"), cwd=str(ROOT.parent))
    eye = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))

    lead_prompt = _strict_auth_prompt(include_decision_log=True)
    lead_run = run_interceptor(
        lead,
        lead_prompt,
        max_lines=3,
        terminate_after=30.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )
    lead_text = "\n".join(lead_run["output"])

    eye_prompt = (
        "[REVIEW:SECURITY+ARCH]\n"
        "Review both the code and DECISIONS section. "
        "Return one line for: 1) critical risk, 2) weak decision rationale, 3) suggested fix.\n\n"
        f"{lead_text[:7000]}"
    )
    eye_run = run_interceptor(
        eye,
        eye_prompt,
        max_lines=2,
        terminate_after=25.0,
        on_event=log_event,
        heartbeat_sec=HEARTBEAT_SEC,
    )

    review = "\n".join(eye_run["output"]).strip()
    corrected: dict[str, Any] = {}
    if review and "NONE" not in review.upper():
        try:
            lead.resume(
                "The reviewer found issues in code/decisions:\n"
                + review[:4000]
                + "\nRewrite and output exactly: one python code block + DECISIONS section with 3 bullets."
            )
            corrected = {
                "resumed": True,
                "output": collect_interceptor_chunks(
                    lead,
                    max_lines=3,
                    terminate_after=30.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                ),
                "ttft_ms": lead.stats.ttft_ms,
            }
        except Exception as e:
            corrected = {"resumed": False, "error": str(e)}

    corrected_text = "\n".join(corrected.get("output", [])) if corrected else ""
    payload = {
        "experiment": "exp7",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "lead": lead_run,
        "eye": eye_run,
        "review": review,
        "corrected": corrected,
        "quality_signals": {
            "lead_has_code": _looks_like_code(lead_text),
            "lead_has_decisions": "DECISIONS" in lead_text.upper(),
            "lead_has_questions": "?" in lead_text,
            "corrected_has_code": _looks_like_code(corrected_text),
            "corrected_has_decisions": "DECISIONS" in corrected_text.upper(),
        },
    }
    write_json("exp7.json", payload)
    return payload


def exp8(home_mode: str) -> dict[str, Any]:
    """Early-eye experiment with parallel startup probe.

    - Preflight eyes start immediately (before first lead chunk) to measure startup overlap.
    - Live eyes start on first lead chunk to do code-based review.
    """
    lead = ClaudeInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "claude"), cwd=str(ROOT.parent))
    sec_eye_live = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))
    arch_eye_live = CodexInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "codex"), cwd=str(ROOT.parent))
    sec_eye_pre = GeminiInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "gemini"), cwd=str(ROOT.parent))
    arch_eye_pre = CodexInterceptor(home_dir=None if home_mode == "system" else str(HOMES / "codex"), cwd=str(ROOT.parent))

    lead_started = time.time()
    startup_probe: dict[str, Any] = {
        "lead_start_epoch_ms": int(lead_started * 1000),
        "security_preflight": {"started": False, "start_delay_ms": None, "ttft_ms": None, "chunk_count": 0, "errors": []},
        "architecture_preflight": {"started": False, "start_delay_ms": None, "ttft_ms": None, "chunk_count": 0, "errors": []},
    }
    probe_lock = threading.Lock()

    def _run_preflight(role: str, interceptor: StreamInterceptor, lens: str) -> None:
        start_delay_ms = int((time.time() - lead_started) * 1000)
        run = run_interceptor(
            interceptor,
            f"[PRE-FLIGHT {lens.upper()}] You are about to review incoming auth code. "
            "Give a short watchlist of top 3 risks to look for in one sentence.",
            max_lines=2,
            terminate_after=18.0,
            on_event=log_event,
            heartbeat_sec=HEARTBEAT_SEC,
        )
        with probe_lock:
            startup_probe[role] = {
                "started": True,
                "start_delay_ms": start_delay_ms,
                "ttft_ms": run.get("ttft_ms"),
                "chunk_count": run.get("chunk_count", 0),
                "errors": run.get("errors", []),
                "output": run.get("output", []),
            }

    # Start preflight eyes immediately, before lead emits first chunk.
    pre_threads = [
        threading.Thread(target=_run_preflight, args=("security_preflight", sec_eye_pre, "security"), daemon=True),
        threading.Thread(target=_run_preflight, args=("architecture_preflight", arch_eye_pre, "architecture"), daemon=True),
    ]
    for t in pre_threads:
        t.start()
    log_event("[exp8] preflight eyes launched")

    lead.start(_strict_auth_prompt(), resume=False)
    log_event("[exp8] lead started; waiting for first chunk")

    lead_output: list[str] = []
    first_chunk_ts: float | None = None
    live_eye_results: dict[str, Any] = {
        "security": {"started": False, "start_delay_ms": None, "run": None},
        "architecture": {"started": False, "start_delay_ms": None, "run": None},
    }
    live_lock = threading.Lock()
    live_threads: list[threading.Thread] = []

    def _run_live_eye(role: str, interceptor: StreamInterceptor, lens: str, snapshot: str) -> None:
        start_delay_ms = int((time.time() - lead_started) * 1000)
        run = run_interceptor(
            interceptor,
            _eye_prompt(lens, snapshot),
            max_lines=2,
            terminate_after=25.0,
            on_event=log_event,
            heartbeat_sec=HEARTBEAT_SEC,
        )
        with live_lock:
            live_eye_results[role]["started"] = True
            live_eye_results[role]["start_delay_ms"] = start_delay_ms
            live_eye_results[role]["run"] = run

    for chunk in lead.chunks():
        lead_output.append(chunk.text)
        if first_chunk_ts is None:
            first_chunk_ts = chunk.timestamp
            startup_probe["lead_first_chunk_delay_ms"] = int((first_chunk_ts - lead_started) * 1000)
            snapshot = "\n".join(lead_output)
            log_event("[exp8] first lead chunk seen; launching live eyes")
            live_threads = [
                threading.Thread(target=_run_live_eye, args=("security", sec_eye_live, "security", snapshot), daemon=True),
                threading.Thread(target=_run_live_eye, args=("architecture", arch_eye_live, "architecture", snapshot), daemon=True),
            ]
            for t in live_threads:
                t.start()
        if len(lead_output) >= 2:
            lead.terminate(hard=False)

    for t in pre_threads:
        t.join(timeout=25.0)
    for t in live_threads:
        t.join(timeout=40.0)

    lead_run = {
        "name": lead.name,
        "session_id": lead.session_id,
        "ttft_ms": lead.stats.ttft_ms,
        "chunk_count": lead.stats.chunk_count,
        "errors": lead.stats.errors,
        "output": lead_output,
    }

    findings = {
        "security": "\n".join((live_eye_results["security"]["run"] or {}).get("output", [])),
        "architecture": "\n".join((live_eye_results["architecture"]["run"] or {}).get("output", [])),
    }

    resume_payload: dict[str, Any] = {}
    any_finding = any(v.strip() and "NONE" not in v.upper() for v in findings.values())
    if any_finding and lead.session_id:
        try:
            lead.resume(
                "Fix these findings in the code and output one final python code block:\n"
                f"1) security: {findings['security']}\n"
                f"2) architecture: {findings['architecture']}"
            )
            resume_payload = {
                "resumed": True,
                "output": collect_interceptor_chunks(
                    lead,
                    max_lines=2,
                    terminate_after=25.0,
                    on_event=log_event,
                    heartbeat_sec=HEARTBEAT_SEC,
                ),
                "ttft_ms": lead.stats.ttft_ms,
            }
        except Exception as e:
            resume_payload = {"resumed": False, "error": str(e)}
    else:
        resume_payload = {
            "resumed": False,
            "reason": "skipped_resume_no_findings_or_no_session",
            "output": [],
            "ttft_ms": None,
        }

    payload = {
        "experiment": "exp8",
        "home_mode": home_mode,
        "timestamp": int(time.time()),
        "lead": lead_run,
        "startup_probe": startup_probe,
        "eyes_early": live_eye_results,
        "findings": findings,
        "resume": resume_payload,
        "quality_signals": {
            "lead_has_code": _looks_like_code("\n".join(lead_output)),
            "first_eye_started_fast": any(
                _coalesce_ms(live_eye_results[r]["start_delay_ms"]) < 10000
                for r in ("security", "architecture")
            ),
            "preflight_started_before_first_chunk": (
                bool(startup_probe.get("lead_first_chunk_delay_ms") is not None)
                and (
                    _coalesce_ms(startup_probe["security_preflight"]["start_delay_ms"]) < startup_probe["lead_first_chunk_delay_ms"]
                    or _coalesce_ms(startup_probe["architecture_preflight"]["start_delay_ms"]) < startup_probe["lead_first_chunk_delay_ms"]
                )
            ) or (
                startup_probe.get("lead_first_chunk_delay_ms") is None
                and (
                    startup_probe["security_preflight"]["started"]
                    or startup_probe["architecture_preflight"]["started"]
                )
            ),
            "security_has_finding": bool(findings["security"].strip()) and "NONE" not in findings["security"].upper(),
            "architecture_has_finding": bool(findings["architecture"].strip()) and "NONE" not in findings["architecture"].upper(),
            "resume_has_code": _looks_like_code("\n".join(resume_payload.get("output", []))),
        },
    }
    write_json("exp8.json", payload)
    return payload


def print_summary(data: dict[str, Any]) -> None:
    print(f"experiment: {data['experiment']}")
    print(f"home_mode: {data.get('home_mode', DEFAULT_HOME_MODE)}")
    if "checks" in data:
        for c in data["checks"]:
            status = "OK" if c["success"] else "FAIL"
            cat = c.get("category", "unknown")
            print(f"- {c['name']}: {status} [{cat}] ({c['duration_ms']}ms)")
    if "runs" in data and isinstance(data["runs"], list):
        print(f"runs: {len(data['runs'])}")
    if "matrix" in data:
        print(f"pairs: {len(data['matrix'])}")


def main() -> None:
    global VERBOSE, HEARTBEAT_SEC, LIVE_LOG_PATH
    ensure_dirs()
    parser = argparse.ArgumentParser(description="Run pair() POC experiments.")
    parser.add_argument("experiment", choices=["exp0", "exp1", "exp2", "exp3", "exp4", "exp5", "exp6", "exp7", "exp8"])
    parser.add_argument(
        "--home-mode",
        choices=["isolated", "system"],
        default=DEFAULT_HOME_MODE,
        help="isolated: use pair_poc/.homes; system: use existing user HOME config",
    )
    parser.add_argument("--verbose", action="store_true", help="Print live progress events during execution.")
    parser.add_argument(
        "--heartbeat-sec",
        type=float,
        default=5.0,
        help="Heartbeat interval in seconds for live progress logs.",
    )
    args = parser.parse_args()
    VERBOSE = args.verbose
    HEARTBEAT_SEC = max(0.5, args.heartbeat_sec)
    LIVE_LOG_PATH = OUT / f"{args.experiment}.live.log"
    LIVE_LOG_PATH.write_text("", encoding="utf-8")
    log_event(f"[runner] experiment={args.experiment} home_mode={args.home_mode} heartbeat={HEARTBEAT_SEC}s")

    fn = globals()[args.experiment]
    result = fn(args.home_mode)
    print_summary(result)
    print(f"result_file: {OUT / (args.experiment + '.json')}")


if __name__ == "__main__":
    main()
