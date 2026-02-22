"""Quick-and-dirty authentication system.

This module is intentionally simple and framework-free.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass

PBKDF2_ROUNDS = 310_000
SALT_SIZE = 16
TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24h


@dataclass
class AuthSystem:
    db_path: str = "auth.db"

    def __post_init__(self) -> None:
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
                """
            )

    def register(self, username: str, password: str) -> None:
        if len(username) < 3:
            raise ValueError("username must be at least 3 characters")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")

        password_hash, salt = self._hash_password(password)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, password_salt, created_at) VALUES(?,?,?,?)",
                    (username, password_hash, salt, int(time.time())),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("username already exists") from exc

    def login(self, username: str, password: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash, password_salt FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise ValueError("invalid credentials")

            if not self._verify_password(password, row["password_hash"], row["password_salt"]):
                raise ValueError("invalid credentials")

            raw_token = secrets.token_urlsafe(32)
            token_hash = self._hash_token(raw_token)
            now = int(time.time())
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES(?,?,?,?)",
                (token_hash, row["id"], now + TOKEN_TTL_SECONDS, now),
            )
            return raw_token

    def validate_token(self, raw_token: str) -> str | None:
        token_hash = self._hash_token(raw_token)
        now = int(time.time())

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.username, s.expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                return None

            if row["expires_at"] < now:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None

            return str(row["username"])

    def logout(self, raw_token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._hash_token(raw_token),))

    @staticmethod
    def _hash_password(password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(SALT_SIZE)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ROUNDS,
        )
        return (
            base64.b64encode(password_hash).decode("ascii"),
            base64.b64encode(salt).decode("ascii"),
        )

    @staticmethod
    def _verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
        expected_hash = base64.b64decode(stored_hash.encode("ascii"))
        salt = base64.b64decode(stored_salt.encode("ascii"))
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ROUNDS,
        )
        return secrets.compare_digest(password_hash, expected_hash)

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
