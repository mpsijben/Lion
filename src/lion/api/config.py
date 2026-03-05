"""Configuration loading helpers for the API server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_lion_config() -> dict[str, Any]:
    """Load Lion config from standard locations."""
    candidates = [
        _project_root() / "config.toml",
        _project_root() / "config.default.toml",
        Path.home() / ".lion" / "config.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            import tomllib

            with path.open("rb") as f:
                return tomllib.load(f)
        except Exception:
            continue
    return {}


def get_api_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Get normalized API settings with safe defaults."""
    api_cfg = config.get("api", {})
    cors_origins = api_cfg.get(
        "cors_origins",
        [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
        ],
    )
    keys_raw = api_cfg.get("keys", [])
    keys: list[str]
    if isinstance(keys_raw, dict):
        keys = [str(v) for v in keys_raw.values() if str(v).strip()]
    elif isinstance(keys_raw, list):
        keys = [str(v) for v in keys_raw if str(v).strip()]
    else:
        keys = []

    return {
        "host": str(api_cfg.get("host", "127.0.0.1")),
        "port": int(api_cfg.get("port", 8000)),
        "job_ttl_seconds": int(api_cfg.get("job_ttl_seconds", 3600)),
        "cleanup_interval_seconds": int(api_cfg.get("cleanup_interval_seconds", 300)),
        "default_timeout_seconds": api_cfg.get("default_timeout_seconds"),
        "cors_origins": cors_origins,
        "keys": keys,
        "jobs_dir": str(
            Path(os.path.expanduser(api_cfg.get("jobs_dir", "~/.lion/api/jobs"))).resolve()
        ),
        "sessions_dir": str(
            Path(os.path.expanduser(api_cfg.get("sessions_dir", "~/.lion/api/sessions"))).resolve()
        ),
    }
