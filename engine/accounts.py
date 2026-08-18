"""engine/accounts.py — Elena account system.

Supports SQLite (local) and PostgreSQL (Railway/production).
When DATABASE_URL env is set, uses psycopg2; otherwise SQLite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import settings

_DB_NAME = "accounts.db"
_PBKDF2_ALGO = "sha256"
_PBKDF2_ITER = 600_000
_PBKDF2_DKLEN = 32
_init_lock = threading.Lock()

_USE_PG = bool(os.getenv("DATABASE_URL"))


def _ph(sql: str) -> str:
    """Convert ? placeholders to %s for PostgreSQL."""
    if _USE_PG:
        return sql.replace("?", "%s")
    return sql

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS google_links (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    google_email TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    linked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""

_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS google_links (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    google_email TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    linked_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""


class AccountsError(ValueError):
    """User-facing error for account operations (Vietnamese messages)."""


def data_path() -> Path:
    return settings.data_dir() / _DB_NAME


def _get_pg_conn():
    """Get a psycopg2 connection from DATABASE_URL."""
    import psycopg2
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def init_db() -> None:
    with _init_lock:
        if _USE_PG:
            conn = _get_pg_conn()
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA_PG)
            finally:
                conn.close()
        else:
            path = data_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(path)) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA_SQLITE)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
                if "is_admin" not in cols:
                    conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")


@contextmanager
def _conn():
    if _USE_PG:
        conn = _get_pg_conn()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        init_db()
        conn = sqlite3.connect(str(data_path()))
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITER, dklen=_PBKDF2_DKLEN)
    return f"pbkdf2${_PBKDF2_ALGO}${_PBKDF2_ITER}${base64.b64encode(salt).decode('ascii')}${base64.b64encode(dk).decode('ascii')}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, hash_name, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac(hash_name, password.encode("utf-8"), salt, int(iterations), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _validate_password(password: str) -> None:
    if (
        not password
        or len(password) < 8
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
    ):
        raise AccountsError("Mật khẩu phải tối thiểu 8 ký tự, gồm chữ và số")


def _user_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "full_name": row[3],
        "created_at": row[5],
        "is_admin": bool(row[6]) if len(row) > 6 else False,
    }


def register(email: str, username: str, full_name: str, password: str) -> dict:
    email = (email or "").strip().lower()
    username_orig = (username or "").strip()
    username_key = username_orig.lower()
    full_name = (full_name or "").strip()
    if "@" not in email or len(email) < 3:
        raise AccountsError("Email không hợp lệ")
    if not username_key:
        raise AccountsError("Vui lòng nhập username")
    if not full_name:
        raise AccountsError("Vui lòng nhập họ tên")
    _validate_password(password)
    with _conn() as conn:
        if conn.execute(_ph("SELECT 1 FROM users WHERE lower(username) = ?"), (username_key,)).fetchone():
            raise AccountsError("Username đã tồn tại")
        try:
            if _USE_PG:
                cur = conn.execute(
                    "INSERT INTO users (email, username, full_name, password_hash, created_at) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (email, username_orig, full_name, _hash_password(password), time.time()),
                )
                uid = cur.fetchone()[0]
            else:
                cur = conn.execute(
                    "INSERT INTO users (email, username, full_name, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (email, username_orig, full_name, _hash_password(password), time.time()),
                )
                uid = cur.lastrowid
        except Exception:
            if conn.execute(_ph("SELECT 1 FROM users WHERE email = ?"), (email,)).fetchone():
                raise AccountsError("Email đã được đăng ký")
            raise AccountsError("Username đã tồn tại")
    return get_user(uid)


def verify_login(login: str, password: str) -> dict:
    login = (login or "").strip()
    if not login or not password:
        raise AccountsError("Email/Username hoặc mật khẩu không đúng")
    with _conn() as conn:
        row = conn.execute(
            _ph("SELECT id, email, username, full_name, password_hash, created_at, is_admin "
            "FROM users WHERE email = ? OR lower(username) = ?"),
            (login.lower(), login.lower()),
        ).fetchone()
    if row is None or not _verify_password(password, row[4]):
        raise AccountsError("Email/Username hoặc mật khẩu không đúng")
    return _user_row_to_dict(row)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute(
            _ph("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)"),
            (token, user_id, time.time()),
        )
    return token


def get_user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    with _conn() as conn:
        row = conn.execute(
            _ph("SELECT u.id, u.email, u.username, u.full_name, u.password_hash, u.created_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?"),
            (token,),
        ).fetchone()
    if row is None:
        return None
    return _user_row_to_dict(row)


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute(_ph("DELETE FROM sessions WHERE token = ?"), (token,))


def change_password(user_id: int, old_password: str, new_password: str) -> None:
    with _conn() as conn:
        row = conn.execute(_ph("SELECT password_hash FROM users WHERE id = ?"), (user_id,)).fetchone()
        if row is None:
            raise AccountsError("Không tìm thấy người dùng")
        if not _verify_password(old_password, row[0]):
            raise AccountsError("Mật khẩu cũ không đúng")
        _validate_password(new_password)
        conn.execute(_ph("UPDATE users SET password_hash = ? WHERE id = ?"), (_hash_password(new_password), user_id))


def get_user(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute(
            _ph("SELECT id, email, username, full_name, password_hash, created_at, is_admin FROM users WHERE id = ?"),
            (user_id,),
        ).fetchone()
    if row is None:
        raise AccountsError("Không tìm thấy người dùng")
    return _user_row_to_dict(row)


def get_pref(user_id: int, key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute(_ph("SELECT value FROM prefs WHERE user_id = ? AND key = ?"), (user_id, key)).fetchone()
    return row[0] if row else default


def set_pref(user_id: int, key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            _ph("INSERT INTO prefs (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value"),
            (user_id, key, value),
        )


def mount_enabled(user_id: int | None = None) -> bool:
    """Pref `use_mount`. Default True when no user/pref row (kept simple)."""
    if user_id is None:
        return True
    val = get_pref(user_id, "use_mount", "1") or "1"
    return val.strip().lower() in ("1", "true", "yes", "on")


def get_google_link(user_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            _ph("SELECT user_id, google_email, refresh_token_encrypted, linked_at "
            "FROM google_links WHERE user_id = ?"),
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row[0],
        "google_email": row[1],
        "refresh_token_encrypted": row[2],
        "linked_at": row[3],
    }


def set_google_link(user_id: int, email: str, encrypted_token: str) -> None:
    with _conn() as conn:
        conn.execute(
            _ph("INSERT INTO google_links (user_id, google_email, refresh_token_encrypted, linked_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET google_email = excluded.google_email, "
            "refresh_token_encrypted = excluded.refresh_token_encrypted, linked_at = excluded.linked_at"),
            (user_id, email, encrypted_token, time.time()),
        )


def clear_google_link(user_id: int) -> None:
    with _conn() as conn:
        conn.execute(_ph("DELETE FROM google_links WHERE user_id = ?"), (user_id,))


# ── Admin helpers ────────────────────────────────────────────────────────────

def list_all_users() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, email, username, full_name, created_at, is_admin FROM users ORDER BY id"
        ).fetchall()
    return [{"id": r[0], "email": r[1], "username": r[2], "full_name": r[3], "created_at": r[4], "is_admin": bool(r[5])} for r in rows]


def get_user_sessions(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            _ph("SELECT token, created_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC"),
            (user_id,),
        ).fetchall()
    return [{"token": r[0], "created_at": r[1]} for r in rows]


def delete_user(user_id: int) -> None:
    with _conn() as conn:
        conn.execute(_ph("DELETE FROM sessions WHERE user_id = ?"), (user_id,))
        conn.execute(_ph("DELETE FROM google_links WHERE user_id = ?"), (user_id,))
        conn.execute(_ph("DELETE FROM prefs WHERE user_id = ?"), (user_id,))
        conn.execute(_ph("DELETE FROM users WHERE id = ?"), (user_id,))


def admin_reset_password(user_id: int, new_password: str) -> None:
    _validate_password(new_password)
    with _conn() as conn:
        row = conn.execute(_ph("SELECT 1 FROM users WHERE id = ?"), (user_id,)).fetchone()
        if row is None:
            raise AccountsError("Không tìm thấy người dùng")
        conn.execute(_ph("UPDATE users SET password_hash = ? WHERE id = ?"), (_hash_password(new_password), user_id))


def get_stats() -> dict:
    with _conn() as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return {"total_users": user_count, "active_sessions": session_count}


def is_admin_user(user_id: int) -> bool:
    with _conn() as conn:
        row = conn.execute(_ph("SELECT is_admin FROM users WHERE id = ?"), (user_id,)).fetchone()
    return bool(row[0]) if row else False


def update_profile(user_id: int, email: str | None = None, username: str | None = None, full_name: str | None = None) -> dict:
    with _conn() as conn:
        existing = conn.execute(_ph("SELECT id, email, username, full_name FROM users WHERE id = ?"), (user_id,)).fetchone()
        if existing is None:
            raise AccountsError("Không tìm thấy người dùng")
        new_email = (email or existing[1]).strip().lower()
        new_username = (username or existing[2]).strip()
        new_full_name = (full_name or existing[3]).strip()
        if "@" not in new_email or len(new_email) < 3:
            raise AccountsError("Email không hợp lệ")
        if not new_username:
            raise AccountsError("Username không được để trống")
        if not new_full_name:
            raise AccountsError("Họ tên không được để trống")
        if new_email.lower() != existing[1].lower():
            dup = conn.execute(_ph("SELECT 1 FROM users WHERE lower(email) = ? AND id != ?"), (new_email.lower(), user_id)).fetchone()
            if dup:
                raise AccountsError("Email đã được sử dụng")
        if new_username.lower() != existing[2].lower():
            dup = conn.execute(_ph("SELECT 1 FROM users WHERE lower(username) = ? AND id != ?"), (new_username.lower(), user_id)).fetchone()
            if dup:
                raise AccountsError("Username đã tồn tại")
        conn.execute(_ph("UPDATE users SET email = ?, username = ?, full_name = ? WHERE id = ?"), (new_email, new_username, new_full_name, user_id))
    return get_user(user_id)


def admin_set_is_admin(user_id: int, is_admin: bool) -> None:
    with _conn() as conn:
        conn.execute(_ph("UPDATE users SET is_admin = ? WHERE id = ?"), (1 if is_admin else 0, user_id))
