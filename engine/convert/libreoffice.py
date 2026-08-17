import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from ..config import settings


class LibreOfficeError(Exception):
    def __init__(self, reason: str, transient: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.transient = transient


def find_soffice() -> Path:
    candidates = [
        Path(settings.soffice_path),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for c in candidates:
        if c.exists():
            return c
    found = shutil.which("soffice")
    if found:
        return Path(found)
    raise LibreOfficeError(
        "Khong tim thay LibreOffice (soffice.exe). Cai LibreOffice de su dung tinh nang nay.",
        transient=False,
    )


def _soffice_ok(proc, out: Path) -> bool:
    # Chỉ coi là thành công khi file đầu ra thực sự được tạo và không rỗng.
    # Không dựa vào exit code: LibreOffice có thể trả 0 nhưng không xuất được file
    # (vd thiếu filter xuất Calc) → sẽ bị bắt là lỗi rõ ràng ở dưới.
    return out.exists() and out.stat().st_size > 0


def _is_venv_path(path: str, venv_roots: set[Path]) -> bool:
    # Gọt khỏi PATH mọi thư mục nằm trong venv (chứa Scripts\ của venv, hoặc bất kỳ
    # path nào nằm dưới gốc venv như D:\App\scan-de\.venv). Python mà LibreOffice nhúng
    # sẽ không tìm thấy thư viện platform nếu PYTHONHOME/PYTHONPATH/venv rò vào môi trường.
    if not path.strip():
        return False
    try:
        p = Path(path)
        for root in venv_roots:
            rp = p.resolve()
            if rp == root or root in rp.parents:
                return True
    except OSError:
        return False
    return "\\Scripts\\" in path.replace("/", "\\").lower()


def convert_via_lo(src: Path, out_dir: Path, target: str, timeout: int | None = None) -> Path:
    from .formats import lo_filter_for

    soffice = find_soffice()
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = Path(settings.temp_dir()) / f"lo-profile-{uuid.uuid4().hex[:10]}"
    profile.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONSTARTUP", None)
    env.pop("PYTHONEXECUTABLE", None)
    env.pop("VIRTUAL_ENV", None)
    path_parts = env.get("PATH", "").split(os.pathsep)
    venv_roots = {Path(sys.prefix).resolve(), Path(sys.executable).resolve().parent.parent}
    stripped = [p for p in path_parts if not _is_venv_path(p, venv_roots)]
    if stripped != path_parts:
        env["PATH"] = os.pathsep.join(stripped)

    target_filter = lo_filter_for(target)
    timeout = timeout or min(300, settings.job_timeout_seconds)

    stderr_snapshots: list[str] = []

    def _run() -> Path:
        args = [
            str(soffice),
            "--headless",
            "--norestore",
            "--nologo",
            "--safe-mode",
            "-env:UserInstallation=file:///" + str(profile).replace("\\", "/"),
            "--convert-to",
            target_filter,
            "--outdir",
            str(out_dir),
            str(src),
        ]
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise LibreOfficeError(
                f"LibreOffice het thoi gian ({timeout}s) khi chuyen doi - file co the qua lon hoac hong",
                transient=True,
            ) from exc
        out = out_dir / f"{src.stem}.{target}"
        err = (proc.stderr or b"").decode("utf-8", "ignore")
        stderr_snapshots.append(err[-400:])
        if _soffice_ok(proc, out):
            return out
        if proc.returncode == 0 and not out.exists():
            reason = f"LibreOffice chuyen doi that bai (exit 0) - khong tao duoc file. Co the thieu filter xuat cua dinh dang dich."
        else:
            reason = f"LibreOffice chuyen doi that bai (exit {proc.returncode})"
        detail = err[-300:] if err else ""
        raise LibreOfficeError(
            f"{reason} {detail}".strip(),
            transient=True,
        )

    try:
        return _run()
    except LibreOfficeError as exc:
        if exc.transient and settings.retry_transient > 0:
            import time

            time.sleep(2)
            return _run()
        raise
