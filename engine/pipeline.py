import datetime
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import pdfbuild
from .adapters.base import get_adapter
from .capture import CaptureError, capture
from .config import settings
from .ocr import OcrPageResult, ocr_page
from .sanitize import sanitize_filename_part, sanitize_folder
from .storage import PlacementResult, clean_old_temp, place_pdf
from .validate import LinkError, validate_link


@dataclass
class Brief:
    ok: bool
    lines: list[str] = field(default_factory=list)
    warning: bool = False
    failure_reason: str | None = None

    def render(self) -> str:
        head = "THANH CONG" if self.ok else "THAT BAI"
        if self.ok and self.warning:
            head += " (CẢNH BÁO: OCR thap)"
        sep = "=" * 44
        return "\n".join([sep, f"[{head}]", *self.lines, sep])


@dataclass
class RunResult:
    brief: Brief
    pdf_path: Path | None = None
    elapsed: float = 0.0


def derive_ky() -> str:
    month = datetime.date.today().month
    return "HK1" if (month >= 8 or month <= 1) else "HK2"


def _transient(exc: BaseException) -> bool:
    if isinstance(exc, CaptureError):
        return not exc.permanent
    if isinstance(exc, LinkError):
        return not exc.permanent
    if isinstance(exc, TimeoutError):
        return True
    return False


def run_scan(raw_link: str, mon: str, ten_de: str, ky: str | None = None, out_dir: Path | None = None, use_mount: bool | None = None) -> RunResult:
    started = time.time()
    job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_root = settings.temp_dir()
    clean_old_temp(temp_root)
    workdir = out_dir or (temp_root / job_id)
    workdir.mkdir(parents=True, exist_ok=True)

    ky = ky or derive_ky()
    mon = sanitize_folder(mon)
    ten_de = sanitize_filename_part(ten_de)
    if not mon or not ten_de:
        return _fail_brief(ValueError("Tên môn hoặc tên đề không hợp lệ"))
    filename = f"{mon} - {ten_de} - {ky}.pdf"

    def attempt() -> tuple[list[Path], list[OcrPageResult]]:
        url = validate_link(raw_link)
        adapter = get_adapter(url)
        normalized = adapter.normalize(url)
        fetch = getattr(adapter, "fetch_pages", None)
        page_images: list[Path] | None = None
        if fetch is not None:
            try:
                page_images = fetch(normalized, workdir)
            except NotImplementedError:
                page_images = None
        if not page_images:
            captured = capture(normalized, adapter, workdir)
            page_images = captured.page_images
        ocr_pages: list[OcrPageResult] = []
        for img in page_images:
            ocr_pages.append(ocr_page(img))
        return page_images, ocr_pages

    try:
        try:
            page_images, ocr_pages = attempt()
        except Exception as exc:
            if _transient(exc) and settings.retry_transient > 0:
                time.sleep(2)
                page_images, ocr_pages = attempt()
            else:
                raise
    except (LinkError, CaptureError, ValueError) as exc:
        return _fail_brief(exc)
    except Exception as exc:
        return _fail_brief(exc, tb=True)

    pdf_path = workdir / filename
    try:
        page_count = pdfbuild.build_searchable_pdf(page_images, ocr_pages, pdf_path)
    except Exception as exc:
        return _fail_brief(exc, tb=True)

    warnings = [r.warning for r in ocr_pages if r.warning]
    avg_conf = (
        sum(r.confidence for r in ocr_pages if r.blocks) / max(1, sum(1 for r in ocr_pages if r.blocks))
        if ocr_pages
        else 0.0
    )

    placement: PlacementResult | None = None
    try:
        placement = place_pdf(pdf_path, mon, filename, use_mount=use_mount)
    except Exception as exc:
        return _fail_brief(exc, tb=True)

    size_kb = pdf_path.stat().st_size / 1024
    elapsed = time.time() - started
    lines = [
        f"File: {filename}",
        f"Trang: {page_count} | OCR text layer: {avg_conf * 100:.0f}% confidence",
        f"Kich thuoc: {size_kb / 1024:.2f} MB",
        f"Thoi gian: {elapsed:.0f}s",
        "Da luu:",
    ]
    lines += [f"  - {loc}" for loc in placement.locations]
    lines += [f"Ghi chu: {note}" for note in placement.notes]
    if warnings:
        lines.append("CẢNH BÁO: mot so trang OCR confidence < 50% - text khong copy duoc, anh goc van nguyen ven")
    brief = Brief(ok=True, lines=lines, warning=bool(warnings))
    return RunResult(brief=brief, pdf_path=pdf_path, elapsed=elapsed)


def _fail_brief(exc: BaseException, tb: bool = False) -> RunResult:
    reason = getattr(exc, "reason", None) or str(exc)
    lines = [f"Ly do: {reason}"]
    if isinstance(exc, (LinkError, CaptureError, ValueError)):
        lines.append("Goi y: kiem tra lai link (dinh dang, quyen truy cap, noi dung tra phi) hoac scan thu cong")
    else:
        lines.append("Goi y: chay lai; neu van loi, gui log cho developer")
        if tb:
            lines.append(traceback.format_exc())
    return RunResult(brief=Brief(ok=False, lines=lines, failure_reason=reason))
