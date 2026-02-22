from __future__ import annotations

import sqlite3
import time

import pytest

from lion.quick_auth import AuthSystem


def test_register_login_validate_logout(tmp_path):
    auth = AuthSystem(db_path=str(tmp_path / "auth.db"))

    auth.register("alice", "supersecret123")
    token = auth.login("alice", "supersecret123")

    assert auth.validate_token(token) == "alice"

    auth.logout(token)
    assert auth.validate_token(token) is None


def test_invalid_credentials(tmp_path):
    auth = AuthSystem(db_path=str(tmp_path / "auth.db"))
    auth.register("bob", "supersecret123")

    with pytest.raises(ValueError, match="invalid credentials"):
        auth.login("bob", "wrong-password")


def test_duplicate_username(tmp_path):
    auth = AuthSystem(db_path=str(tmp_path / "auth.db"))
    auth.register("charlie", "supersecret123")

    with pytest.raises(ValueError, match="already exists"):
        auth.register("charlie", "anothersecret123")


def test_expired_token_is_rejected(tmp_path):
    auth = AuthSystem(db_path=str(tmp_path / "auth.db"))
    auth.register("dora", "supersecret123")
    token = auth.login("dora", "supersecret123")

    token_hash = auth._hash_token(token)
    with sqlite3.connect(str(tmp_path / "auth.db")) as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
            (int(time.time()) - 1, token_hash),
        )

    assert auth.validate_token(token) is None
