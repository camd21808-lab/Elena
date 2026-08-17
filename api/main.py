import json
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.auth import require_user, router as auth_router
from api.jobs import backend
from engine import accounts, google_drive, library
from engine.config import settings
from engine.convert.formats import SOURCE_EXTS, magic_matches, normalize_target
from engine.google_drive import GoogleLinkError
from engine.sanitize import sanitize_filename_part, sanitize_folder
from engine.validate import LinkError, validate_link


@asynccontextmanager
async def lifespan(_: FastAPI):
    library.init_db()
    accounts.init_db()
    yield


app = FastAPI(title="Scan-de API", version="0.3.0", lifespan=lifespan)
app.include_router(auth_router)

_rescan_lock = threading.Lock()
_rescan_running = False

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

_RATE_WINDOW = 60.0
_RATE_LIMIT = 10
_requests: dict[str, list[float]] = {}

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}

_SAFE_NAME = re.compile(r"[^\w\u00C0-\u024F\-\. ()]+")


def _rate_limited(ip: str) -> bool:
    now = time.time()
    ts = [t for t in _requests.get(ip, []) if now - t < _RATE_WINDOW]
    if len(ts) >= _RATE_LIMIT:
        _requests[ip] = ts
        return True
    ts.append(now)
    _requests[ip] = ts
    return False


class JobRequest(BaseModel):
    link: str = Field(min_length=5, max_length=2000)
    mon: str = Field(min_length=1, max_length=200)
    ten_de: str = Field(min_length=1, max_length=300)
    ky: str | None = Field(default=None, pattern="^(HK1|HK2)$")


def _sanitize_name(name: str) -> str:
    name = Path(name).name
    name = _SAFE_NAME.sub("_", name)
    return name[:120]


def _unique_path(dest: Path) -> Path:
    """Return `dest`, or `stem (2).ext` / `stem (3).ext` … if taken."""
    if not dest.exists():
        return dest
    stem = dest.stem
    i = 2
    while True:
        candidate = dest.with_name(f"{stem} ({i}){dest.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


async def _save_upload(file: UploadFile, prefix: str, allowed: set[str]) -> Path:
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if not file.filename or ext not in allowed:
        raise ValueError(f"Định dạng chưa hỗ trợ: .{ext} (hỗ trợ: {', '.join(sorted(allowed))})")
    uploads = settings.temp_dir() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / f"{prefix}_{_sanitize_name(file.filename)}"
    limit = settings.convert_max_mb * 1024 * 1024
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                dest.unlink(missing_ok=True)
                raise ValueError(f"File vượt giới hạn {settings.convert_max_mb} MB")
            out.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("File rỗng")
    if ext == "pdf" and not _is_pdf(dest):
        dest.unlink(missing_ok=True)
        raise ValueError("File hỏng hoặc đuôi không khớp nội dung thực tế (không phải PDF)")
    return dest


def _is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _validate_protect_config(raw: str) -> dict:
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cấu hình JSON không hợp lệ: {exc}")
    if not isinstance(config, dict):
        raise ValueError("Cấu hình phải là một đối tượng JSON")
    regions = config.get("redact_regions")
    if regions is not None:
        if not isinstance(regions, list):
            raise ValueError("redact_regions phải là một mảng")
        for r in regions:
            if not isinstance(r, dict) or "page" not in r or "rect" not in r:
                raise ValueError("Mỗi vùng redact phải có 'page' và 'rect'")
            if not isinstance(r.get("page"), int) or r["page"] < 0:
                raise ValueError("'page' phải là số trang (>= 0)")
            rect = r.get("rect")
            if not (isinstance(rect, list) and len(rect) == 4 and all(isinstance(v, (int, float)) for v in rect)):
                raise ValueError("'rect' phải là mảng 4 số [x0, y0, x1, y1]")
    return config


@app.post("/jobs")
def create_job(req: JobRequest, request: Request, user: dict = Depends(require_user)):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "Qua nhieu yeu cau - thu lai sau 1 phut")
    try:
        validate_link(req.link)
    except LinkError as exc:
        return JSONResponse(status_code=400, content={"error": exc.reason})
    mon = sanitize_folder(req.mon)
    ten_de = sanitize_filename_part(req.ten_de)
    if not mon or not ten_de:
        return JSONResponse(status_code=400, content={"error": "Tên môn hoặc tên đề không hợp lệ"})
    job = backend.create_job(req.link, mon, ten_de, req.ky)
    backend.enqueue(job)
    return {"job_id": job.id, "status": job.status}


@app.post("/convert")
async def create_convert_job(
    request: Request,
    file: UploadFile = File(...),
    mon: str = Form(..., min_length=1, max_length=200),
    target: str = Form("pdf"),
    user: dict = Depends(require_user),
):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "Qua nhieu yeu cau - thu lai sau 1 phut")
    try:
        target_fmt = normalize_target(target)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if not file.filename or ext not in SOURCE_EXTS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Định dạng chưa hỗ trợ: .{ext} (hỗ trợ: {', '.join(sorted(SOURCE_EXTS))})"},
        )

    mon = sanitize_folder(mon)
    if not mon:
        return JSONResponse(status_code=400, content={"error": "Tên môn học không hợp lệ"})

    job = backend.create_convert_job("", mon, target_fmt)

    uploads = settings.temp_dir() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / f"{job.id}_{_sanitize_name(file.filename)}"

    limit = settings.convert_max_mb * 1024 * 1024
    written = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    dest.unlink(missing_ok=True)
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"File vượt giới hạn {settings.convert_max_mb} MB"},
                    )
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        return JSONResponse(status_code=400, content={"error": "File rỗng"})
    if not magic_matches(dest, ext):
        dest.unlink(missing_ok=True)
        return JSONResponse(
            status_code=400,
            content={"error": "File hỏng hoặc đuôi không khớp nội dung thực tế"},
        )

    job.source_file = str(dest)
    backend.enqueue(job)
    return {"job_id": job.id, "status": job.status}


@app.post("/protect/preview")
async def protect_preview(
    request: Request,
    file: UploadFile = File(...),
    terms: str = Form(""),
    user: dict = Depends(require_user),
):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "Qua nhieu yeu cau - thu lai sau 1 phut")
    try:
        path = await _save_upload(file, f"preview_{uuid.uuid4().hex[:8]}", {"pdf"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    term_list = list(dict.fromkeys(t.strip() for t in terms.splitlines() if t.strip()))
    if not term_list:
        path.unlink(missing_ok=True)
        return JSONResponse(status_code=400, content={"error": "Chưa nhập từ khoá cần xoá"})
    try:
        from engine.protect import preview_redaction

        result = preview_redaction(path, term_list)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Không đọc được PDF: {exc}"})
    finally:
        path.unlink(missing_ok=True)
    return result


@app.post("/protect")
async def create_protect_job(
    request: Request,
    file: UploadFile = File(...),
    config: str = Form(""),
    user: dict = Depends(require_user),
):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "Qua nhieu yeu cau - thu lai sau 1 phut")
    try:
        cfg = _validate_protect_config(config)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        dest = await _save_upload(file, f"protect_{uuid.uuid4().hex[:8]}", {"pdf"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    job = backend.create_protect_job(str(dest), json.dumps(cfg, ensure_ascii=False))
    backend.enqueue(job)
    return {"job_id": job.id, "status": job.status}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: dict = Depends(require_user)):
    job = backend.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job khong ton tai")
    return {
        "job_id": job.id,
        "status": job.status,
        "ok": job.ok,
        "brief": job.brief_lines,
        "error": job.error,
        "kind": job.kind,
        "target": job.target,
    }


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str, user: dict = Depends(require_user)):
    job = backend.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job khong ton tai")
    if job.status != "done":
        raise HTTPException(409, "Job chua hoan thanh")
    path = Path(job.result_path or job.pdf_path or "")
    if not path.is_file():
        raise HTTPException(410, "File da bi xoa (TTL het han)")
    ext = path.suffix.lower().lstrip(".")
    media = _MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/library")
def list_library(
    user: dict = Depends(require_user),
    q: str = "",
    mon: str = "",
    lop: str = "",
    nam: str = "",
    loai: str = "",
    root: str = "",
):
    items = library.search(q=q, mon=mon, lop=lop, nam=nam, loai=loai, root=root)
    link = accounts.get_google_link(user["id"])
    return {
        "items": items,
        "stats": library.stats(),
        "drive_available": library.drive_available(),
        "google_linked": link is not None,
        "google_email": link["google_email"] if link else None,
    }


@app.get("/library/stats")
def library_stats(user: dict = Depends(require_user)):
    return library.stats()


@app.post("/library/rescan")
def rescan_library(user: dict = Depends(require_user)):
    global _rescan_running
    if _rescan_running:
        raise HTTPException(409, "Đang dò lại thư mục — hãy chờ vài giây rồi thử lại")
    with _rescan_lock:
        if _rescan_running:
            raise HTTPException(409, "Đang dò lại thư mục — hãy chờ vài giây rồi thử lại")
        _rescan_running = True
        try:
            return library.rescan_roots(use_mount=accounts.mount_enabled(user["id"]))
        finally:
            _rescan_running = False


@app.post("/library/{item_id}")
def update_library_item(
    item_id: int,
    ten: str = Form(""),
    mon: str = Form(""),
    lop: str = Form(""),
    nam: str = Form(""),
    loai: str = Form(""),
    user: dict = Depends(require_user),
):
    ten = sanitize_filename_part(ten)
    mon = sanitize_folder(mon)
    ok = library.update_meta(item_id, ten, mon, lop, nam, loai)
    if not ok:
        raise HTTPException(404, "Không tìm thấy đề thi")
    return {"ok": True}


@app.post("/library/{item_id}/delete")
def delete_library_item(item_id: int, user: dict = Depends(require_user)):
    ok = library.delete(item_id)
    if not ok:
        raise HTTPException(404, "Không tìm thấy đề thi")
    return {"ok": True}


@app.post("/library/{item_id}/to-drive")
def to_drive_library_item(item_id: int, user: dict = Depends(require_user)):
    meta = library.get_meta(item_id)
    if meta is None:
        raise HTTPException(404, "Không tìm thấy đề thi")
    if meta.get("cloud_file_id"):
        return {"ok": True, "method": "already", "file_id": meta["cloud_file_id"]}
    link = accounts.get_google_link(user["id"])
    if link is not None:
        src = Path(meta["path"])
        if not src.is_file():
            return JSONResponse(status_code=409, content={"error": "File không còn tồn tại trên ổ đĩa"})
        try:
            res = google_drive.upload_file(user["id"], src, meta["mon"])
        except GoogleLinkError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": f"Lỗi khi upload lên Drive: {exc}"})
        library.set_cloud_state(item_id, res["file_id"], res["name"])
        return {"ok": True, "method": "google", "file_id": res["file_id"]}
    if library.drive_available():
        try:
            res = library.to_drive(item_id)
            return {"ok": True, "method": "mount", "path": res.get("path")}
        except library.LibraryError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": f"Lỗi máy chủ khi đưa lên Drive: {exc}"})
    return JSONResponse(
        status_code=409,
        content={"error": "Chưa liên kết Google và chưa cấu hình Drive — vào Cài đặt để liên kết"},
    )


@app.get("/library/cloud")
def library_cloud(user: dict = Depends(require_user)):
    link = accounts.get_google_link(user["id"])
    if link is None:
        return {"items": [], "linked": False}
    try:
        cloud = google_drive.list_cloud(user["id"])
    except GoogleLinkError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    existing = {i["cloud_file_id"] for i in library.search() if i.get("cloud_file_id")}
    items = [c for c in cloud if c["file_id"] not in existing]
    return {"items": items, "linked": True, "email": link["google_email"]}


@app.post("/library/cloud/{file_id}/download")
def library_cloud_download(
    file_id: str,
    user: dict = Depends(require_user),
    mon: str = "",
    name: str = "",
):
    link = accounts.get_google_link(user["id"])
    if link is None:
        raise HTTPException(409, "Chưa liên kết tài khoản Google")
    mon = sanitize_folder(mon)
    if not mon and mon != "":
        raise HTTPException(400, "Tên môn học không hợp lệ")
    fname = _sanitize_name(name) or (_sanitize_name(file_id) + ".pdf")
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    dest = _unique_path(settings.local_subject_dir(mon) / fname)
    try:
        path = google_drive.download_file(user["id"], file_id, dest)
    except GoogleLinkError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    library.index_file(path, mon=mon)
    return {"ok": True, "path": str(path)}


@app.get("/library/{item_id}/download")
def download_library_item(item_id: int, user: dict = Depends(require_user)):
    meta = library.get_meta(item_id)
    if meta is None:
        raise HTTPException(404, "Không tìm thấy đề thi")
    path = Path(meta["path"])
    if not path.is_file():
        if meta.get("root") == "drive":
            raise HTTPException(404, "File nằm trên Drive nhưng Drive chưa được gắn hoặc file chưa được tải về máy")
        raise HTTPException(404, "File không còn tồn tại trên ổ đĩa")
    base = (meta.get("ten") or "").strip() or path.stem
    filename = base if base.lower().endswith(".pdf") else f"{base}.pdf"
    return FileResponse(path, media_type=_MEDIA_TYPES.get("pdf", "application/pdf"), filename=filename)


class MountToggleBody(BaseModel):
    use_mount: bool


@app.get("/settings")
def get_settings(user: dict = Depends(require_user)):
    link = accounts.get_google_link(user["id"])
    return {
        "user": user,
        "google": {
            "linked": link is not None,
            "email": link["google_email"] if link else None,
            "configured": google_drive.configured(),
        },
        "drive": {
            "configured": library.drive_configured(),
            "available": library.drive_available(),
            "use_mount": accounts.mount_enabled(user["id"]),
        },
    }


@app.post("/settings/mount-toggle")
def settings_mount_toggle(body: MountToggleBody, user: dict = Depends(require_user)):
    accounts.set_pref(user["id"], "use_mount", "1" if body.use_mount else "0")
    return {"ok": True, "use_mount": body.use_mount}


@app.get("/health")
def health():
    return {"status": "ok"}
