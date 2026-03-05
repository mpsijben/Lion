"""Session metadata store for API session endpoints."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SessionCreate, SessionInfo


@dataclass
class ApiSession:
    session_id: str
    created_at: datetime
    last_active: datetime
    provider: str | None = None
    cwd: str | None = None
    initial_context: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_info(self) -> SessionInfo:
        return SessionInfo(
            session_id=self.session_id,
            created_at=self.created_at,
            last_active=self.last_active,
            history_count=len(self.history),
            provider=self.provider,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "provider": self.provider,
            "cwd": self.cwd,
            "initial_context": self.initial_context,
            "config": self.config,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiSession":
        return cls(
            session_id=str(data["session_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_active=datetime.fromisoformat(data["last_active"]),
            provider=data.get("provider"),
            cwd=data.get("cwd"),
            initial_context=data.get("initial_context"),
            config=data.get("config") or {},
            history=data.get("history") or [],
        )


class SessionStore:
    """Simple persistent session store."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, ApiSession] = {}

    def load(self) -> None:
        for file in self.base_dir.glob("*/state.json"):
            try:
                data = json.loads(file.read_text())
                session = ApiSession.from_dict(data)
                self._sessions[session.session_id] = session
            except Exception:
                continue

    def create(self, request: SessionCreate) -> ApiSession:
        now = datetime.now(timezone.utc)
        session_id = uuid.uuid4().hex
        session = ApiSession(
            session_id=session_id,
            created_at=now,
            last_active=now,
            provider=request.provider,
            cwd=request.cwd,
            initial_context=request.initial_context,
            config=request.config,
        )
        self._sessions[session_id] = session
        self._persist(session)
        return session

    def get(self, session_id: str) -> ApiSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session_dir = self.base_dir / session_id
        if session_dir.exists():
            for child in session_dir.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                session_dir.rmdir()
            except OSError:
                pass
        return True

    def append_history(self, session_id: str, record: dict[str, Any]) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        session.history.append(record)
        session.last_active = datetime.now(timezone.utc)
        self._persist(session)

    def _persist(self, session: ApiSession) -> None:
        session_dir = self.base_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        state_file = session_dir / "state.json"
        state_file.write_text(json.dumps(session.to_dict(), indent=2))
