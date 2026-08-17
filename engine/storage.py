import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import accounts
from .config import settings
from .sanitize import sanitize_filename_part, sanitize_folder


class StorageError(Exception):
    pass


@dataclass
class PlacementResult:
    locations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def clean_old_temp(temp_root: Path, ttl_hours: float | None = None) -> None:
    ttl = settings.temp_ttl_hours if ttl_hours is None else ttl_hours
    if not temp_root.exists():
        return
    cutoff = time.time() - ttl * 3600
    for f in temp_root.rglob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


def place_pdf(pdf_path: Path, mon: str, filename: str, use_mount: bool | None = None) -> PlacementResult:
    result = PlacementResult()
    mon = sanitize_folder(mon)
    filename = sanitize_filename_part(filename)

    local_dir = settings.local_subject_dir(mon)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_target = local_dir / filename
    shutil.copy2(pdf_path, local_target)
    result.locations.append(str(local_target))

    if settings.drive_root:
        if use_mount is None:
            use_mount = accounts.mount_enabled(None)
        if use_mount:
            drive_dir = Path(settings.drive_root) / mon
            drive_dir.mkdir(parents=True, exist_ok=True)
            drive_target = drive_dir / filename
            shutil.copy2(pdf_path, drive_target)
            result.locations.append(str(drive_target))
        else:
            result.notes.append("Đã tắt lưu vào Drive gắn (mount) trong Cài đặt")
    else:
        result.notes.append("Chua cau hinh SCANDE_DRIVE_ROOT - chi luu local")

    return result
