"""api/auth.py — Elena account endpoints + the require_user dependency.

Local accounts (register/login/logout/me/change-password) plus the optional
Google Drive OAuth link flow (start/status/unlink). Everything except
/health and /auth/* in the app is gated behind require_user.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from engine import accounts, google_drive
from engine.accounts import AccountsError
from engine.google_drive import GoogleLinkError

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_RATE_WINDOW = 60.0
_AUTH_RATE_LIMIT = 5
_auth_fails: dict[str, list[float]] = {}
_auth_lock = threading.Lock()


def _too_many_logins(ip: str) -> bool:
    now = time.time()
    with _auth_lock:
        ts = [t for t in _auth_fails.get(ip, []) if now - t < _AUTH_RATE_WINDOW]
        _auth_fails[ip] = ts
        return len(ts) >= _AUTH_RATE_LIMIT


def _record_login_fail(ip: str) -> None:
    now = time.time()
    with _auth_lock:
        _auth_fails[ip] = [t for t in _auth_fails.get(ip, []) if now - t < _AUTH_RATE_WINDOW]
        _auth_fails[ip].append(now)


def _clear_login_fails(ip: str) -> None:
    with _auth_lock:
        _auth_fails.pop(ip, None)


class RegisterBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    username: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)


class LoginBody(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)


class ChangePasswordBody(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


class AdminResetPasswordBody(BaseModel):
    user_id: int
    new_password: str = Field(max_length=200)


def require_user(x_auth_token: str | None = Header(default=None, alias="X-Auth-Token")) -> dict:
    """FastAPI dependency: resolve the X-Auth-Token session to a user dict."""
    user = accounts.get_user_by_token(x_auth_token) if x_auth_token else None
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập")
    return user


@router.get("/status")
def auth_status():
    return {"ok": True}


@router.get("/admin", response_class=HTMLResponse)
def admin_page():
    from pathlib import Path
    html_path = Path(__file__).resolve().parent.parent / "ui" / "admin.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Admin page not found</h1>", status_code=404)


@router.post("/register")
def register(body: RegisterBody):
    try:
        user = accounts.register(body.email, body.username, body.full_name, body.password)
    except AccountsError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    return {"ok": True, "user": user}


@router.post("/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "unknown"
    if _too_many_logins(ip):
        raise HTTPException(429, "Thử lại sau 60 giây")
    try:
        user = accounts.verify_login(body.login, body.password)
    except AccountsError:
        _record_login_fail(ip)
        raise HTTPException(401, "Email/Username hoặc mật khẩu không đúng")
    _clear_login_fails(ip)
    token = accounts.create_session(user["id"])
    return {"ok": True, "token": token, "user": user}


@router.post("/logout")
def logout(
    user: dict = Depends(require_user),
    x_auth_token: str | None = Header(default=None, alias="X-Auth-Token"),
):
    if x_auth_token:
        accounts.delete_session(x_auth_token)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"user": user}


@router.post("/change-password")
def change_password(body: ChangePasswordBody, user: dict = Depends(require_user)):
    try:
        accounts.change_password(user["id"], body.old, body.new)
    except AccountsError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True}


@router.post("/google/start")
def google_start(user: dict = Depends(require_user)):
    try:
        url = google_drive.build_auth_url(user["id"])
    except GoogleLinkError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"url": url}


@router.post("/google/status")
def google_status(user: dict = Depends(require_user)):
    return google_drive.link_status(user["id"])


@router.post("/google/unlink")
def google_unlink(user: dict = Depends(require_user)):
    try:
        google_drive.unlink(user["id"])
    except GoogleLinkError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True}


# ── Admin endpoints ──────────────────────────────────────────────────────────

def _check_admin(user: dict):
    if not accounts.is_admin_user(user["id"]):
        raise HTTPException(403, "Chỉ admin mới truy cập được")


@router.get("/admin/users")
def admin_list_users(user: dict = Depends(require_user)):
    _check_admin(user)
    return {"users": accounts.list_all_users()}


@router.get("/admin/users/{user_id}")
def admin_get_user(user_id: int, user: dict = Depends(require_user)):
    _check_admin(user)
    try:
        u = accounts.get_user(user_id)
    except AccountsError:
        raise HTTPException(404, "Không tìm thấy")
    sessions = accounts.get_user_sessions(user_id)
    return {"user": u, "sessions": sessions}


@router.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, user: dict = Depends(require_user)):
    _check_admin(user)
    if user_id == user["id"]:
        return JSONResponse(status_code=400, content={"error": "Không thể xóa chính mình"})
    accounts.delete_user(user_id)
    return {"ok": True}


@router.post("/admin/reset-password")
def admin_reset_password(body: AdminResetPasswordBody, user: dict = Depends(require_user)):
    _check_admin(user)
    try:
        accounts.admin_reset_password(body.user_id, body.new_password)
    except AccountsError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True}


@router.get("/admin/stats")
def admin_stats(user: dict = Depends(require_user)):
    _check_admin(user)
    return accounts.get_stats()


# ── Profile management (any logged-in user) ─────────────────────────────────

class UpdateProfileBody(BaseModel):
    email: str | None = Field(default=None, max_length=200)
    username: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=200)


@router.post("/update-profile")
def update_profile(body: UpdateProfileBody, user: dict = Depends(require_user)):
    try:
        updated = accounts.update_profile(user["id"], body.email, body.username, body.full_name)
    except AccountsError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"ok": True, "user": updated}
