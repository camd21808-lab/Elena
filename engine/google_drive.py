"""engine/google_drive.py — optional Google OAuth layer + Drive API (drive.file).

The whole module talks to Google via the urllib stdlib only. The endpoint
constants (AUTH_URL / TOKEN_URL / REVOKE_URL / API) are module-level so tests
can point them at a local fake server. Feature is disabled when
SCANDE_GOOGLE_CLIENT_ID/SECRET are not configured.

Refresh tokens are stored DPAPI-protected per user via engine.accounts. A tiny
callback HTTP server on 127.0.0.1:<google_callback_port> completes the OAuth
loop, so linking works even without Drive for Desktop.
"""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from . import accounts, win_dpapi
from .config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com"

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file openid email"
ROOT_FOLDER_NAME = "Elena - Kho đề thi"

_TOKEN_TTL = 3600
_CACHE_LOCK = threading.Lock()
_token_cache: dict[int, tuple[str, float]] = {}
_folder_cache: dict[str, str] = {}

_states: dict[str, dict] = {}
_failures: dict[int, tuple[str, float]] = {}

_server_started = False
_server_lock = threading.Lock()


class GoogleLinkError(ValueError):
    """User-facing error for Google link / Drive operations."""


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _require_configured() -> None:
    if not configured():
        raise GoogleLinkError(
            "Chưa cấu hình Google (SCANDE_GOOGLE_CLIENT_ID) — xem hướng dẫn trong Settings"
        )


def _redirect_uri() -> str:
    return f"http://127.0.0.1:{settings.google_callback_port}/callback"


def _extract_email(token_data: dict) -> str:
    """Email from the OIDC id_token (always returned by Google's token endpoint)."""
    id_token = token_data.get("id_token")
    if id_token:
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if claims.get("email"):
                return claims["email"]
        except Exception:
            pass
    return token_data.get("email") or "Google account"


# ---------------------------------------------------------------------------
# OAuth link flow
# ---------------------------------------------------------------------------


def build_auth_url(user_id: int) -> str:
    _require_configured()
    state = secrets.token_urlsafe(24)
    with _CACHE_LOCK:
        _states[state] = {"user_id": user_id, "expires": time.time() + 300}
    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": DRIVE_FILE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{params}"


def _finish_link(state: str, code: str) -> None:
    with _CACHE_LOCK:
        info = _states.pop(state, None)
    if info is None or info["expires"] < time.time():
        raise GoogleLinkError("Phiên liên kết hết hạn — thử lại")
    user_id = info["user_id"]
    body = urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise GoogleLinkError(f"Google từ chối: {exc.code}")
    except URLError:
        raise GoogleLinkError("Mất kết nối mạng — thử lại")
    refresh = token_data.get("refresh_token")
    if not refresh:
        raise GoogleLinkError("Google không trả refresh_token — kiểm tra cấu hình OAuth")
    email = _extract_email(token_data)
    encrypted = win_dpapi.protect(refresh.encode("utf-8"))
    accounts.set_google_link(user_id, email, encrypted)
    access = token_data.get("access_token")
    if access:
        with _CACHE_LOCK:
            _token_cache[user_id] = (access, time.time() + int(token_data.get("expires_in", _TOKEN_TTL)))


def _record_failure(user_id: int | None, message: str) -> None:
    if user_id is None:
        return
    with _CACHE_LOCK:
        _failures[user_id] = (message, time.time())


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self._send(404, "Không tìm thấy")
            return
        params = parse_qs(parsed.query)
        state = (params.get("state") or [None])[0]
        code = (params.get("code") or [None])[0]
        error = (params.get("error") or [None])[0]
        if error:
            with _CACHE_LOCK:
                info = _states.pop(state, None) if state else None
            _record_failure(info["user_id"] if info else None, "Bạn đã huỷ liên kết Google")
            self._send(200, "Đã huỷ liên kết — bạn có thể đóng tab này")
            return
        if not state or not code:
            self._send(400, "Thiếu tham số callback")
            return
        try:
            _finish_link(state, code)
            self._send(200, "Đã liên kết tài khoản Google — bạn có thể đóng tab này")
        except GoogleLinkError as exc:
            with _CACHE_LOCK:
                info = _states.get(state)
            _record_failure(info["user_id"] if info else None, str(exc))
            self._send(400, str(exc))
        except Exception as exc:
            with _CACHE_LOCK:
                info = _states.get(state)
            _record_failure(info["user_id"] if info else None, f"Lỗi: {exc}")
            self._send(400, f"Lỗi: {exc}")

    def _send(self, code: int, message: str) -> None:
        body = (
            "<!doctype html><html><body style='font-family:Segoe UI,system-ui,sans-serif;"
            f"padding:2rem'><h2 style='color:#2b2620'>{message}</h2></body></html>"
        ).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args):  # quiet console
        pass


def _ensure_server() -> None:
    global _server_started
    with _server_lock:
        if _server_started:
            return
        try:
            server = ThreadingHTTPServer(("127.0.0.1", settings.google_callback_port), _CallbackHandler)
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True, name="google-callback").start()
            _server_started = True
        except OSError:
            print(
                f"[google_drive] Không mở được callback server trên cổng {settings.google_callback_port}",
                flush=True,
            )


_ensure_server()


def link_status(user_id: int) -> dict:
    link = accounts.get_google_link(user_id)
    failure = None
    with _CACHE_LOCK:
        rec = _failures.get(user_id)
        if rec and rec[1] > time.time() - 60:
            failure = rec[0]
    return {
        "linked": link is not None,
        "email": link["google_email"] if link else None,
        "failure": failure,
    }


def unlink(user_id: int) -> None:
    """Best-effort REVOKE then clear the stored link."""
    _require_configured()
    link = accounts.get_google_link(user_id)
    if link is None:
        raise GoogleLinkError("Chưa liên kết tài khoản Google")
    try:
        refresh = win_dpapi.unprotect(link["refresh_token_encrypted"]).decode("utf-8")
    except Exception:
        refresh = ""
    if refresh:
        try:
            req = Request(
                REVOKE_URL,
                data=urlencode({"token": refresh}).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urlopen(req, timeout=30):
                pass
        except Exception:
            pass  # best-effort
    accounts.clear_google_link(user_id)
    with _CACHE_LOCK:
        _token_cache.pop(user_id, None)
        _folder_cache.clear()


def get_linked_email(user_id: int) -> str | None:
    link = accounts.get_google_link(user_id)
    return link["google_email"] if link else None


# ---------------------------------------------------------------------------
# Token + Drive API
# ---------------------------------------------------------------------------


def get_access_token(user_id: int) -> str:
    _require_configured()
    now = time.time()
    with _CACHE_LOCK:
        cached = _token_cache.get(user_id)
    if cached and cached[1] > now + 60:
        return cached[0]
    link = accounts.get_google_link(user_id)
    if link is None:
        raise GoogleLinkError("Chưa liên kết tài khoản Google")
    try:
        refresh = win_dpapi.unprotect(link["refresh_token_encrypted"]).decode("utf-8")
    except Exception:
        raise GoogleLinkError("Phiên liên kết hết hạn — hãy liên kết lại")
    body = urlencode(
        {
            "refresh_token": refresh,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (400, 401):
            raise GoogleLinkError("Phiên liên kết hết hạn — hãy liên kết lại")
        raise GoogleLinkError("Mất kết nối mạng — thử lại")
    except URLError:
        raise GoogleLinkError("Mất kết nối mạng — thử lại")
    access = token_data.get("access_token")
    if not access:
        raise GoogleLinkError("Phiên liên kết hết hạn — hãy liên kết lại")
    expires = now + int(token_data.get("expires_in", _TOKEN_TTL))
    with _CACHE_LOCK:
        _token_cache[user_id] = (access, expires)
    return access


def _drive_request(user_id: int, method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    """Authed JSON-ish request. On 401 clears the cache and retries once with a
    freshly refreshed token; retries once on 5xx."""
    access = get_access_token(user_id)
    h = {"Authorization": f"Bearer {access}"}
    if headers:
        h.update(headers)
    req = Request(url, data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        if exc.code in (401, 403) and access:
            with _CACHE_LOCK:
                _token_cache.pop(user_id, None)
            try:
                fresh = get_access_token(user_id)
                h2 = {"Authorization": f"Bearer {fresh}"}
                if headers:
                    h2.update(headers)
                req2 = Request(url, data=data, headers=h2, method=method)
                with urlopen(req2, timeout=60) as resp:
                    return resp.status, resp.read()
            except HTTPError as exc2:
                return exc2.code, exc2.read()
        if exc.code >= 500:
            try:
                with urlopen(req, timeout=60) as resp2:
                    return resp2.status, resp2.read()
            except HTTPError as exc2:
                return exc2.code, exc2.read()
        return exc.code, exc.read()
    except URLError:
        raise GoogleLinkError("Mất kết nối mạng — thử lại")


def _find_folder(user_id: int, name: str, parent_id: str | None = None) -> str | None:
    q = "name='%s' and mimeType='application/vnd.google-apps.folder' and trashed=false" % name.replace("'", "\\'")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    url = f"{API}/drive/v3/files?{urlencode({'q': q})}&fields=files(id,name)&pageSize=100"
    status, raw = _drive_request(user_id, "GET", url)
    if status != 200:
        raise GoogleLinkError(f"Google từ chối: {status}")
    files = (json.loads(raw.decode("utf-8") or "{}").get("files") or [])
    return files[0]["id"] if files else None


def _create_folder(user_id: int, name: str, parent_id: str | None = None) -> str:
    meta: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    url = f"{API}/drive/v3/files"
    status, raw = _drive_request(
        user_id, "POST", url,
        data=json.dumps(meta).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if status not in (200, 201):
        raise GoogleLinkError(f"Google từ chối: {status}")
    fid = (json.loads(raw.decode("utf-8") or "{}").get("id") or "")
    if not fid:
        raise GoogleLinkError("Google từ chối: không nhận được id thư mục")
    return fid


def _get_or_create_folder(user_id: int, name: str, parent_id: str | None = None, cache_key: str = "") -> str:
    if cache_key:
        with _CACHE_LOCK:
            cached = _folder_cache.get(cache_key)
        if cached:
            return cached
    folder_id = _find_folder(user_id, name, parent_id)
    if folder_id is None:
        folder_id = _create_folder(user_id, name, parent_id)
    if cache_key:
        with _CACHE_LOCK:
            _folder_cache[cache_key] = folder_id
    return folder_id


def upload_file(user_id: int, local_path: Path, mon: str) -> dict:
    """Upload `local_path` into "Elena - Kho đề thi"/<mon>/. Returns {file_id, name}."""
    _require_configured()
    local_path = Path(local_path)
    if not local_path.is_file():
        raise GoogleLinkError("File không còn tồn tại trên ổ đĩa")
    root_id = _get_or_create_folder(user_id, ROOT_FOLDER_NAME, cache_key=f"{user_id}:root")
    folder_id = root_id
    if mon:
        folder_id = _get_or_create_folder(user_id, mon, parent_id=root_id, cache_key=f"{user_id}:mon:{mon}")
    metadata = json.dumps({"name": local_path.name, "parents": [folder_id]}).encode("utf-8")
    boundary = "elena-" + secrets.token_hex(8)
    payload = local_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8"),
            metadata,
            b"\r\n",
            f"--{boundary}\r\nContent-Type: application/pdf\r\n\r\n".encode("utf-8"),
            payload,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    url = f"{API}/upload/drive/v3/files?uploadType=multipart&fields=id,name"
    status, raw = _drive_request(
        user_id, "POST", url, data=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    if status not in (200, 201):
        raise GoogleLinkError(f"Google từ chối: {status}")
    data = json.loads(raw.decode("utf-8") or "{}")
    fid = data.get("id")
    if not fid:
        raise GoogleLinkError("Google từ chối: không nhận được id file")
    return {"file_id": fid, "name": data.get("name") or local_path.name}


def _list_pdf_files(user_id: int, folder_id: str, folder_name: str) -> list[dict]:
    q = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    url = f"{API}/drive/v3/files?{urlencode({'q': q})}&fields=files(id,name,size)&pageSize=1000"
    status, raw = _drive_request(user_id, "GET", url)
    if status != 200:
        raise GoogleLinkError(f"Google từ chối: {status}")
    files = (json.loads(raw.decode("utf-8") or "{}").get("files") or [])
    out: list[dict] = []
    for f in files:
        size = f.get("size")
        out.append(
            {
                "name": f.get("name") or "",
                "mon": folder_name,
                "file_id": f.get("id") or "",
                "size_hint": int(size) if size else None,
            }
        )
    return out


def list_cloud(user_id: int, mon: str = "") -> list[dict]:
    """PDFs in the linked Drive, per subject subfolder. mon= folder name."""
    _require_configured()
    root_id = _find_folder(user_id, ROOT_FOLDER_NAME)
    if root_id is None:
        return []
    if mon:
        sub_id = _find_folder(user_id, mon, parent_id=root_id)
        if sub_id is None:
            return []
        return _list_pdf_files(user_id, sub_id, mon)
    items: list[dict] = []
    q = f"'{root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    url = f"{API}/drive/v3/files?{urlencode({'q': q})}&fields=files(id,name)&pageSize=100"
    status, raw = _drive_request(user_id, "GET", url)
    if status != 200:
        raise GoogleLinkError(f"Google từ chối: {status}")
    folders = (json.loads(raw.decode("utf-8") or "{}").get("files") or [])
    items: list[dict] = []
    for folder in folders:
        items.extend(_list_pdf_files(user_id, folder["id"], folder.get("name") or ""))
    items.extend(_list_pdf_files(user_id, root_id, ""))
    return items


def download_file(user_id: int, file_id: str, dest: Path, _retried: bool = False) -> Path:
    """Stream a Drive file to `dest`. Returns the written path."""
    _require_configured()
    dest = Path(dest)
    url = f"{API}/drive/v3/files/{file_id}?alt=media"
    access = get_access_token(user_id)
    req = Request(url, headers={"Authorization": f"Bearer {access}"})
    try:
        with urlopen(req, timeout=120) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as out:
                shutil.copyfileobj(resp, out, length=1024 * 1024)
    except HTTPError as exc:
        if exc.code == 401 and not _retried:
            with _CACHE_LOCK:
                _token_cache.pop(user_id, None)
            return download_file(user_id, file_id, dest, _retried=True)
        if exc.code == 404:
            raise GoogleLinkError("File không còn tồn tại trên Drive")
        raise GoogleLinkError(f"Google từ chối: {exc.code}")
    except URLError:
        raise GoogleLinkError("Mất kết nối mạng — thử lại")
    return dest
