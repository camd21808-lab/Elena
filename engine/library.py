"""
engine/library.py — "Kho đề thi": a local, searchable library of exam PDFs.

SQLite + FTS5. The full-text layer stores diacritic-insensitive, lowercased
text so that "ham so" matches "hàm số". Everything is local — no network.

Rows are deduplicated by (root, rel_path): root is one of 'local' | 'convert'
| 'drive' and rel_path is the path relative to that root's base folder. This
lets the same mount be re-indexed from different drive letters without
creating duplicates, and lets a copy of a file pushed to Google Drive be
indexed as a distinct drive row while the local copy is preserved.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import fitz

from .config import settings

_DB_NAME = "library.db"
_MARK_RE = re.compile(r"[\u0300-\u036f]")
_init_lock = threading.Lock()

# Google Drive File Stream "online-only" attributes (Windows).
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000

# Once-per-process guard so we back up the library DB a single time, right
# before a migration touches it, never on every call.
_backup_made = False

_NEW_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS de_thi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    ten TEXT,
    mon TEXT,
    lop TEXT,
    nam TEXT,
    loai TEXT,
    pages INTEGER,
    size INTEGER,
    mtime REAL,
    created_at REAL,
    indexed_at REAL,
    root TEXT,
    rel_path TEXT,
    UNIQUE(root, rel_path)
)
"""


class LibraryError(ValueError):
    """User-facing error for library operations (e.g. Drive not mounted)."""


def _library_dir() -> Path:
    env = os.getenv("SCANDE_LIBRARY_DIR")
    if env:
        return Path(env)
    return Path(settings.local_root).parent / "scan-de-library"


def _db_path() -> Path:
    return _library_dir() / _DB_NAME


def init_db() -> None:
    """Create tables if missing and run the versioned migration. Idempotent."""
    with _init_lock:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_NEW_SCHEMA_SQL)
            _migrate_to_drive_schema(conn)
            _migrate_to_cloud_schema(conn)
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS de_thi_fts USING fts5(text_norm)")


def _migrate_to_drive_schema(conn: sqlite3.Connection) -> None:
    """Rebuild de_thi with root/rel_path columns when the old schema is found.

    Old schema keyed rows on `path TEXT UNIQUE`. We rebuild into the new
    (root, rel_path)-keyed shape, preserving ids so the untouched FTS table
    keeps matching rowids. Backs up the DB file exactly once per process.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(de_thi)")]
    if "root" in cols and "rel_path" in cols:
        return
    _backup_db(conn)
    rows = conn.execute(
        "SELECT id, path, ten, mon, lop, nam, loai, pages, size, mtime, created_at, indexed_at "
        "FROM de_thi"
    ).fetchall()
    conn.execute("DROP TABLE de_thi")
    conn.execute(_NEW_SCHEMA_SQL)
    for row in rows:
        root, rel = _classify_path(row[1])
        conn.execute(
            "INSERT INTO de_thi (id, path, ten, mon, lop, nam, loai, pages, size, mtime, "
            "created_at, indexed_at, root, rel_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11], root, rel),
        )


def _migrate_to_cloud_schema(conn: sqlite3.Connection) -> None:
    """Add cloud_file_id / cloud_name columns when missing. Idempotent."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(de_thi)")]
    if "cloud_file_id" not in cols:
        conn.execute("ALTER TABLE de_thi ADD COLUMN cloud_file_id TEXT")
    if "cloud_name" not in cols:
        conn.execute("ALTER TABLE de_thi ADD COLUMN cloud_name TEXT")


def _backup_db(conn: sqlite3.Connection | None = None) -> Path | None:
    """Copy library.db to library.db.bak-<timestamp> before we touch it.

    Runs at most once per process (guarded by _backup_made). Flushes the WAL
    into the main file first so the copy reflects committed data.
    """
    global _backup_made
    if _backup_made:
        return None
    _backup_made = True
    path = _db_path()
    if not path.exists():
        return None
    if conn is not None:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{_DB_NAME}.bak-{ts}")
    try:
        shutil.copy2(path, bak)
    except OSError:
        return None
    return bak


@contextmanager
def _conn():
    init_db()
    conn = sqlite3.connect(str(_db_path()))
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = _MARK_RE.sub("", s)
    return s.lower()


def _read_pdf(path: Path) -> tuple[int, str]:
    try:
        doc = fitz.open(str(path))
    except Exception:
        return 0, ""
    try:
        pages = len(doc)
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        return pages, "\n".join(parts)
    finally:
        doc.close()


def extract_text(path) -> str:
    return _read_pdf(Path(path))[1]


def _count_pages(path: Path) -> int:
    return _read_pdf(path)[0]


def _root_base(root: str) -> Path | None:
    """Return the base folder for a root name, or None when not usable."""
    if root == "local":
        return Path(settings.local_root)
    if root == "convert":
        return Path(settings.convert_root)
    if root == "drive":
        if settings.drive_root:
            return Path(settings.drive_root)
        return None
    return None


def _norm_rel(rel: str) -> str:
    """Normalize a relative path for storage: forward slashes, no '..' surprises."""
    rel = os.path.normpath(rel or "")
    return rel.replace("\\", "/")


def _rel_for(path: Path, root: str) -> str:
    """Relative path of `path` under root's base folder (forward slashes).

    Falls back to the normalized absolute path when the file is not under the
    base (different drive / outside tree) so callers never crash.
    """
    base = _root_base(root)
    if base is None:
        return _norm_rel(str(path))
    try:
        rel = os.path.relpath(path, base)
    except (OSError, ValueError):
        return _norm_rel(str(path))
    return _norm_rel(rel)


def _is_under(path, base: Path) -> bool:
    """True when `path` (str or Path) is inside `base` (case-insensitive on Win)."""
    try:
        p = os.path.normcase(os.path.abspath(os.fspath(path)))
        b = os.path.normcase(os.path.abspath(os.fspath(base)))
        return os.path.commonpath([p, b]) == b
    except (OSError, ValueError):
        return False


def _classify_path(path_str: str) -> tuple[str, str]:
    """For migration backfill: infer (root, rel_path) from an absolute path."""
    for root in ("local", "convert", "drive"):
        base = _root_base(root)
        if base and _is_under(path_str, base):
            return root, _rel_for(Path(path_str), root)
    return "local", _norm_rel(os.path.abspath(path_str))


def _infer_root(path: Path) -> str:
    for root in ("local", "convert", "drive"):
        base = _root_base(root)
        if base and _is_under(path, base):
            return root
    return "local"


def is_online_only(path) -> bool:
    """True when `path` is an online-only (unhydrated) Drive File Stream file.

    Windows-only, detected via FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS / _ON_OPEN.
    Never triggers hydration. Non-Windows or an API failure returns False
    (safe default — the file is treated as normal).
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return False
    if attrs in (-1, 0xFFFFFFFF):
        return False
    recall = _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | _FILE_ATTRIBUTE_RECALL_ON_OPEN
    return bool(attrs & recall)


def index_file(path, mon: str = "", ten: str = "", lop: str = "", nam: str = "", loai: str = "", root: str | None = None) -> dict:
    """Insert or update a PDF's metadata + full-text row. Returns {id, created}.

    Dedup key is (root, rel_path). When an existing row is found under that
    key with a different absolute path (drive letter changed / moved), the
    stored path is updated in place. Online-only files are indexed metadata
    only (no extraction, so nothing hangs offline).
    """
    p = Path(path).resolve()
    if root is None:
        root = _infer_root(p)
    rel = _rel_for(p, root)
    if not ten.strip():
        ten = p.stem
    try:
        mtime = p.stat().st_mtime
        size = p.stat().st_size
    except OSError:
        mtime = 0.0
        size = 0
    if is_online_only(p):
        pages, text = 0, ""
    else:
        pages, text = _read_pdf(p)
    norm = normalize_text(text)
    now = time.time()
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, ten, mon, lop, nam, loai FROM de_thi WHERE root = ? AND rel_path = ?",
            (root, rel),
        ).fetchone()
        if row is not None:
            did = row[0]
            # Automated re-index (rescan / job hook) passes mostly empty metadata;
            # preserve any fields the user has edited.
            new_ten = ten if ten.strip() else row[1]
            new_mon = mon if mon.strip() else row[2]
            new_lop = lop if lop.strip() else row[3]
            new_nam = nam if nam.strip() else row[4]
            new_loai = loai if loai.strip() else row[5]
            conn.execute(
                "UPDATE de_thi SET path = ?, ten = ?, mon = ?, lop = ?, nam = ?, loai = ?, "
                "pages = ?, size = ?, mtime = ?, indexed_at = ?, root = ?, rel_path = ? WHERE id = ?",
                (str(p), new_ten, new_mon, new_lop, new_nam, new_loai, pages, size, mtime, now, root, rel, did),
            )
            created = False
        else:
            try:
                cur = conn.execute(
                    "INSERT INTO de_thi (path, ten, mon, lop, nam, loai, pages, size, mtime, "
                    "created_at, indexed_at, root, rel_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(p), ten, mon, lop, nam, loai, pages, size, mtime, now, now, root, rel),
                )
                did = cur.lastrowid
                created = True
            except sqlite3.IntegrityError:
                # Lost a race on UNIQUE(root, rel_path) — update the winner instead.
                conn.rollback()
                with sqlite3.connect(str(_db_path())) as conn2:
                    row2 = conn2.execute(
                        "SELECT id, ten, mon, lop, nam, loai FROM de_thi WHERE root = ? AND rel_path = ?",
                        (root, rel),
                    ).fetchone()
                    did = row2[0]
                    conn2.execute(
                        "UPDATE de_thi SET path = ?, pages = ?, size = ?, mtime = ?, indexed_at = ? WHERE id = ?",
                        (str(p), pages, size, mtime, now, did),
                    )
                    conn2.execute("DELETE FROM de_thi_fts WHERE rowid = ?", (did,))
                    if norm.strip():
                        conn2.execute("INSERT INTO de_thi_fts (rowid, text_norm) VALUES (?, ?)", (did, norm))
                    conn2.commit()
                return {"id": did, "created": False}
        conn.execute("DELETE FROM de_thi_fts WHERE rowid = ?", (did,))
        if norm.strip():
            conn.execute("INSERT INTO de_thi_fts (rowid, text_norm) VALUES (?, ?)", (did, norm))
    return {"id": did, "created": created}


def _index_meta_only(path: Path, meta: dict, root: str = "drive") -> None:
    """Metadata-only index (pages=0, no full text). Used as a safety fallback."""
    p = path.resolve()
    rel = _rel_for(p, root)
    now = time.time()
    try:
        mtime = p.stat().st_mtime
        size = p.stat().st_size
    except OSError:
        mtime, size = 0.0, 0
    with _conn() as conn:
        conn.execute("DELETE FROM de_thi WHERE root = ? AND rel_path = ?", (root, rel))
        cur = conn.execute(
            "INSERT INTO de_thi (path, ten, mon, lop, nam, loai, pages, size, mtime, created_at, "
            "indexed_at, root, rel_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(p), meta.get("ten") or p.stem, meta.get("mon") or "", meta.get("lop") or "",
             meta.get("nam") or "", meta.get("loai") or "", 0, size, mtime, now, now, root, rel),
        )
        conn.execute("DELETE FROM de_thi_fts WHERE rowid = ?", (cur.lastrowid,))


def _get_by_key(root: str, rel_path: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, path, ten, mon, lop, nam, loai, pages, size, mtime, created_at, indexed_at, "
            "root, rel_path, cloud_file_id, cloud_name "
            "FROM de_thi WHERE root = ? AND rel_path = ?",
            (root, rel_path),
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def rescan_roots(use_mount: bool | None = None) -> dict:
    """Walk local_root + convert_root (and drive_root when mounted) recursively
    and index every *.pdf.

    mon is the immediate parent folder name. Returns
    {indexed, updated, skipped} — skipped means file already indexed with an
    unchanged mtime and unchanged path. An unmounted drive is skipped silently.
    Passing use_mount=False skips the Drive mount even when it is present.
    """
    indexed = 0
    updated = 0
    skipped = 0
    seen: set[str] = set()
    roots: list[tuple[str, str]] = [
        ("local", settings.local_root),
        ("convert", settings.convert_root),
    ]
    if settings.drive_root and Path(settings.drive_root).is_dir() and use_mount is not False:
        roots.append(("drive", settings.drive_root))
    for root_name, root_dir in roots:
        root_path = Path(root_dir)
        if not root_path.is_dir():
            continue
        for pdf in root_path.rglob("*.pdf"):
            try:
                resolved = pdf.resolve()
            except OSError:
                resolved = pdf
            if str(resolved) in seen:
                continue
            seen.add(str(resolved))
            mon = pdf.parent.name if pdf.parent.name else ""
            try:
                mtime = pdf.stat().st_mtime
            except OSError:
                mtime = 0.0
            rel = _rel_for(resolved, root_name)
            existing = _get_by_key(root_name, rel)
            if existing is not None and abs(existing["mtime"] - mtime) < 0.5 and existing["path"] == str(resolved):
                skipped += 1
                continue
            result = index_file(resolved, mon=mon, root=root_name)
            if result["created"]:
                indexed += 1
            else:
                updated += 1
    return {"indexed": indexed, "updated": updated, "skipped": skipped}


def _make_snippet(text: str, terms: list[str]) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for t in terms:
        i = text.find(t)
        if i >= 0:
            start = max(0, i - 40)
            end = min(len(text), start + 120)
            out = text[start:end].strip()
            if start > 0:
                out = "…" + out
            if end < len(text):
                out = out + "…"
            return out
    return text[:120]


def search(q: str = "", mon: str = "", lop: str = "", nam: str = "", loai: str = "", root: str = "") -> list[dict]:
    """FTS5 full-text search (diacritic-insensitive) + metadata filters.

    root filter: '' (all) or one of 'local' | 'convert' | 'drive'. A
    comma-separated list (e.g. 'local,convert') is also accepted so the UI's
    "Máy" filter can cover both local and convert roots at once. ORDER BY
    indexed_at DESC. Each result includes a snippet and the item's root so the
    UI can badge it.
    """
    q_terms = [t.replace('"', " ").strip() for t in q.split() if t.strip()]
    where: list[str] = []
    params: list = []
    join = ""
    if q_terms:
        join = " JOIN de_thi_fts f ON f.rowid = d.id"
        where.append("de_thi_fts MATCH ?")
        params.append(" ".join(f'"{t}"' for t in q_terms))
    for col, val in (("mon", mon), ("lop", lop), ("nam", nam), ("loai", loai)):
        if val:
            where.append(f"d.{col} = ?")
            params.append(val)
    if root:
        roots = [r.strip() for r in root.split(",") if r.strip()]
        if roots:
            where.append(f"d.root IN ({', '.join('?' * len(roots))})")
            params.extend(roots)
    sql = (
        "SELECT d.id, d.path, d.ten, d.mon, d.lop, d.nam, d.loai, d.pages, d.size, "
        "d.created_at, d.indexed_at, d.root, d.rel_path, d.cloud_file_id, d.cloud_name"
        + (", f.text_norm" if join else ", ''") +
        f" FROM de_thi d{join}"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.indexed_at DESC"
    items: list[dict] = []
    with _conn() as conn:
        for row in conn.execute(sql, params).fetchall():
            item = {
                "id": row[0],
                "path": row[1],
                "ten": row[2],
                "mon": row[3],
                "lop": row[4],
                "nam": row[5],
                "loai": row[6],
                "pages": row[7],
                "size": row[8],
                "created_at": row[9],
                "indexed_at": row[10],
                "root": row[11],
                "rel_path": row[12],
                "cloud_file_id": row[13],
                "cloud_name": row[14],
            }
            item["snippet"] = _make_snippet(row[15] or "", q_terms)
            items.append(item)
    return items


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "path": row[1],
        "ten": row[2],
        "mon": row[3],
        "lop": row[4],
        "nam": row[5],
        "loai": row[6],
        "pages": row[7],
        "size": row[8],
        "mtime": row[9],
        "created_at": row[10],
        "indexed_at": row[11],
        "root": row[12],
        "rel_path": row[13],
        "cloud_file_id": row[14],
        "cloud_name": row[15],
    }


def get_meta(item_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, path, ten, mon, lop, nam, loai, pages, size, mtime, created_at, indexed_at, "
            "root, rel_path, cloud_file_id, cloud_name "
            "FROM de_thi WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        return None
    meta = _row_to_dict(row)
    meta.pop("mtime", None)
    return meta


def set_cloud_state(item_id: int, file_id: str, name: str) -> bool:
    """Record that a row's file was pushed to the linked Google Drive."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE de_thi SET cloud_file_id = ?, cloud_name = ? WHERE id = ?",
            (file_id, name, item_id),
        )
        return cur.rowcount > 0


def clear_cloud_state(item_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE de_thi SET cloud_file_id = NULL, cloud_name = NULL WHERE id = ?",
            (item_id,),
        )
        return cur.rowcount > 0


def update_meta(item_id: int, ten: str, mon: str, lop: str, nam: str, loai: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE de_thi SET ten = ?, mon = ?, lop = ?, nam = ?, loai = ? WHERE id = ?",
            (ten, mon, lop, nam, loai, item_id),
        )
        return cur.rowcount > 0


def delete(item_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM de_thi WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM de_thi_fts WHERE rowid = ?", (item_id,))
        return True


def stats() -> dict:
    result: dict = {"total": 0, "by_mon": {}, "by_lop": {}, "by_nam": {}, "by_loai": {}, "by_root": {}}
    with _conn() as conn:
        result["total"] = conn.execute("SELECT COUNT(*) FROM de_thi").fetchone()[0]
        for col in ("mon", "lop", "nam", "loai"):
            rows = conn.execute(
                f"SELECT {col}, COUNT(*) FROM de_thi WHERE {col} != '' GROUP BY {col}"
            ).fetchall()
            result[f"by_{col}"] = {r[0]: r[1] for r in rows}
        result["by_root"] = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT root, COUNT(*) FROM de_thi WHERE root IS NOT NULL AND root != '' GROUP BY root"
            ).fetchall()
        }
    return result


def drive_configured() -> bool:
    """True when SCANDE_DRIVE_ROOT is set (even if not currently mounted)."""
    return bool(settings.drive_root)


def drive_available() -> bool:
    """True when the Drive mount is configured AND currently mounted (folder exists)."""
    return bool(settings.drive_root) and Path(settings.drive_root).exists()


def to_drive(item_id: int) -> dict:
    """Copy a local/convert row's file into the Drive mount and index it there.

    The file is copied into drive_root/<parent-relative-layout>/<filename>
    mirroring its source folder. Returns {ok: true, path: str} on success.
    """
    meta = get_meta(item_id)
    if meta is None:
        raise LibraryError("Không tìm thấy đề thi")
    if meta["root"] == "drive":
        return {"ok": True, "note": "already"}
    if not drive_available():
        raise LibraryError("Drive chưa được gắn — kiểm tra Google Drive for Desktop")
    src = Path(meta["path"])
    if not src.is_file():
        raise LibraryError("File không còn tồn tại trên ổ đĩa")
    base = _root_base(meta["root"]) or Path(settings.local_root)
    try:
        rel = os.path.relpath(src, base)
    except (OSError, ValueError):
        rel = src.name
    dest = Path(settings.drive_root) / _norm_rel(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    try:
        index_file(dest, mon=meta["mon"], ten=meta["ten"], root="drive")
    except Exception:
        try:
            _index_meta_only(dest, meta, root="drive")
        except Exception:
            pass
    return {"ok": True, "path": str(dest)}
