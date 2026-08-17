import datetime
import shutil
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from ..config import settings
from ..ocr import OcrPageResult, ocr_page
from ..pdfbuild import build_searchable_pdf, overlay_image_ocr_layer
from ..sanitize import sanitize_folder
from ..storage import clean_old_temp
from . import formats
from .formats import SOURCE_EXTS, count_html_images, family_of, is_image_ext, magic_matches, normalize_target
from .images import count_embedded_images, count_pdf_images, pdf_image_regions
from .libreoffice import LibreOfficeError, convert_via_lo

MAX_MB = 50


class ConvertError(Exception):
    def __init__(self, reason: str, transient: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.transient = transient


@dataclass
class Brief:
    ok: bool
    lines: list[str] = field(default_factory=list)
    warning: bool = False
    failure_reason: str | None = None

    def render(self) -> str:
        head = "THANH CONG" if self.ok else "THAT BAI"
        if self.ok and self.warning:
            head += " (CẢNH BÁO)"
        sep = "=" * 44
        return "\n".join([sep, f"[{head}]", *self.lines, sep])


@dataclass
class RunResult:
    brief: Brief
    result_path: Path | None = None
    elapsed: float = 0.0
    pages: int = 0
    images_kept: int = 0
    images_total: int = 0
    target: str = "pdf"


def _images_to_pdf(images: list[Path], out_path: Path) -> int:
    doc = fitz.open()
    try:
        for img in images:
            with fitz.open(str(img)) as src:
                pix = src[0].get_pixmap()
            page = doc.new_page(width=pix.width, height=pix.height)
            page.insert_image(page.rect, filename=str(img))
        doc.save(str(out_path), deflate=True, garbage=3)
    finally:
        doc.close()
    return len(images)


def _use_native_spreadsheet(ext: str, target_fmt: str) -> bool:
    # docx->xlsx, docx->csv, xlsx->xlsx, xlsx->csv không qua LibreOffice
    # (máy này thiếu filter xuất Calc). pdf->xlsx/csv để lại đường LO (park).
    return target_fmt in ("xlsx", "csv") and ext in ("docx", "xlsx")


def convert_file(
    src_path: Path,
    mon: str,
    target: str | None = None,
    out_dir: Path | None = None,
) -> RunResult:
    started = time.time()
    job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    temp_root = settings.temp_dir()
    clean_old_temp(temp_root)
    workdir = temp_root / f"convert_{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        target_fmt = normalize_target(target)
    except ValueError as exc:
        return _fail_brief(exc)
    mon = sanitize_folder(mon)
    if not mon:
        return _fail_brief(ConvertError("Tên môn học không hợp lệ"))

    src_path = Path(src_path)
    ext = src_path.suffix.lower().lstrip(".")
    if not src_path.is_file():
        return _fail_brief(ConvertError("File nguồn không tồn tại"))
    if ext not in SOURCE_EXTS:
        return _fail_brief(
            ConvertError(f"Định dạng chưa hỗ trợ: .{ext} (hỗ trợ: {', '.join(sorted(SOURCE_EXTS))})")
        )
    size_mb = src_path.stat().st_size / (1024 * 1024)
    if size_mb > settings.convert_max_mb:
        return _fail_brief(ConvertError(f"File vượt giới hạn {settings.convert_max_mb} MB ({size_mb:.1f} MB)"))
    if not magic_matches(src_path, ext):
        return _fail_brief(ConvertError("File hỏng hoặc đuôi không khớp nội dung thực tế"))

    src_count = count_embedded_images(src_path, ext)
    has_images = src_count is None or src_count > 0

    def attempt() -> dict:
        intermediate = _make_intermediate(src_path, ext, workdir)
        if not has_images:
            # Fast path: không ảnh → chuyển đổi trực tiếp, không OCR
            if target_fmt == "pdf":
                final = intermediate
                images_kept = 0
            elif _use_native_spreadsheet(ext, target_fmt):
                from .native_spreadsheet import native_spreadsheet_convert

                final = native_spreadsheet_convert(src_path, workdir, target_fmt)
                images_kept = 0
            else:
                final = convert_via_lo(src_path, workdir, target_fmt)
                images_kept = _count_output_images(final, target_fmt)
            note = f"File khong co anh - chuyen doi thuan, khong OCR"
            ocr_warnings: list[bool] = []
            return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": ocr_warnings}

        # Đường fidelity: nguồn có ảnh → ảnh đi qua nguyên lý scan-de
        if target_fmt == "pdf":
            regions = pdf_image_regions(intermediate)
            ocr_regions: list[list[tuple[tuple[float, float, float, float], OcrPageResult]]] = []
            ocr_warnings: list[bool] = []
            for page_idx, rects in enumerate(regions):
                page_ocr: list[tuple[tuple[float, float, float, float], OcrPageResult]] = []
                for i, rect in enumerate(rects):
                    ocr = _ocr_crop(intermediate, page_idx, rect, workdir, i)
                    page_ocr.append((rect, ocr))
                    ocr_warnings.append(ocr.warning)
                ocr_regions.append(page_ocr)
            final = workdir / f"{src_path.stem}.pdf"
            overlay_image_ocr_layer(intermediate, final, ocr_regions)
            images_kept = count_pdf_images(final)
            note = "Anh goc giu nguyen vi tri + lop text OCR an (tim kiem duoc)"
            return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": ocr_warnings}

        if target_fmt == "txt":
            final = _build_txt_with_image_ocr(intermediate, src_path.stem, workdir)
            return {"final": final, "images_kept": 0, "note": f"{src_count or '?'} anh da chuyen thanh text OCR", "ocr_warnings": []}

        # docx / html: LibreOffice trực tiếp từ nguồn office (ảnh giữ bởi LO)
        # Ngoại lệ: nguồn PDF/anh → LO không có export filter → dùng native PyMuPDF + python-docx
        fam = family_of(ext)
        if target_fmt == "docx" and fam in ("pdf", "image"):
            from .native_pdf import pdf_to_docx

            final = workdir / f"{src_path.stem}.docx"
            _, ocr_warnings = pdf_to_docx(intermediate, final, workdir)
            images_kept = _count_output_images(final, target_fmt)
            note = "Anh giu nguyen boi PyMuPDF + python-docx; text lay tu lop OCR an + OCR cho anh"
            return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": ocr_warnings}

        if target_fmt == "html" and fam in ("pdf", "image"):
            from .native_pdf import html_from_pdf

            final = workdir / f"{src_path.stem}.html"
            images_kept = html_from_pdf(intermediate, final)
            note = "Anh nhung base64 vao HTML; text lay tu lop OCR an"
            return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": []}

        if target_fmt in ("xlsx", "csv") and fam in ("pdf", "image"):
            raise ConvertError(
                f"Khong the chuyen anh/PDF sang {target_fmt.upper()} - dinh dang bang tinh khong nhan de thi quet. Chon PDF, DOCX, TXT hoac HTML"
            )

        if _use_native_spreadsheet(ext, target_fmt):
            from .native_spreadsheet import native_spreadsheet_convert

            final = native_spreadsheet_convert(src_path, workdir, target_fmt)
            images_kept = 0
            note = f"{src_count or '?'} anh bi bo (bang tinh khong giu anh); text tu paragraph + bang duoc trich nguyen"
            return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": []}

        final = convert_via_lo(src_path, workdir, target_fmt)
        images_kept = _count_output_images(final, target_fmt)
        note = "Anh giu nguyen boi LibreOffice; OCR alt-text cho dích nay la P1"
        return {"final": final, "images_kept": images_kept, "note": note, "ocr_warnings": []}

    try:
        try:
            outcome = attempt()
        except (LibreOfficeError, ConvertError, OSError) as exc:
            transient = getattr(exc, "transient", False)
            if transient and settings.retry_transient > 0:
                time.sleep(2)
                outcome = attempt()
            else:
                raise
    except (LibreOfficeError, ConvertError, ValueError) as exc:
        return _fail_brief(exc)
    except Exception as exc:
        return _fail_brief(exc, tb=True)

    final: Path = outcome["final"]
    images_kept: int = outcome["images_kept"]
    note: str = outcome["note"]
    ocr_warnings: list[bool] = outcome["ocr_warnings"]

    try:
        doc = fitz.open(str(final))
        pages = len(doc)
        doc.close()
    except Exception:
        pages = 0

    out_name = f"{src_path.stem}.{target_fmt}"
    dest_dir = out_dir or settings.convert_subject_dir(mon)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / out_name
        shutil.copy2(final, dest)
    except Exception as exc:
        return _fail_brief(exc, tb=True)

    size_kb = dest.stat().st_size / 1024
    elapsed = time.time() - started
    total_display = src_count if src_count is not None else "?"
    lines = [
        f"File: {dest}",
        f"Trang: {pages} | Kich thuoc: {size_kb / 1024:.2f} MB | Thoi gian: {elapsed:.0f}s",
        f"Anh: {images_kept}/{total_display} giu duoc | Dích: {target_fmt.upper()}",
        f"Anh duoc xu ly: {note}",
    ]
    warning = False
    if src_count is not None and images_kept < src_count and target_fmt not in ("txt", "csv", "xlsx"):
        lines.append(f"CẢNH BÁO: mat {src_count - images_kept} anh trong qua trinh chuyen doi")
        warning = True
    if any(ocr_warnings):
        lines.append("CẢNH BÁO: OCR confidence < 50% - text trong anh co the khong chuan, anh goc van nguyen ven")
        warning = True
    return RunResult(
        brief=Brief(ok=True, lines=lines, warning=warning),
        result_path=dest,
        elapsed=elapsed,
        pages=pages,
        images_kept=images_kept,
        images_total=src_count or 0,
        target=target_fmt,
    )


def _make_intermediate(src_path: Path, ext: str, workdir: Path) -> Path:
    fam = family_of(ext)
    if fam == "pdf":
        inter = workdir / "intermediate.pdf"
        shutil.copy2(src_path, inter)
        return inter
    if fam == "image":
        inter = workdir / "intermediate.pdf"
        _images_to_pdf([src_path], inter)
        return inter
    out = convert_via_lo(src_path, workdir, "pdf")
    inter = workdir / "intermediate.pdf"
    if out != inter:
        shutil.move(str(out), str(inter))
    return inter


def _ocr_crop(pdf_path: Path, page_idx: int, rect: tuple[float, float, float, float], workdir: Path, i: int) -> OcrPageResult:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_idx]
        pix = page.get_pixmap(clip=fitz.Rect(*rect), matrix=fitz.Identity, alpha=False)
        crop = workdir / f"crop_p{page_idx}_i{i}.png"
        pix.save(str(crop))
    finally:
        doc.close()
    return ocr_page(crop)


def _build_txt_with_image_ocr(intermediate: Path, stem: str, workdir: Path) -> Path:
    out = workdir / f"{stem}.txt"
    doc = fitz.open(str(intermediate))
    try:
        sections: list[str] = []
        for page_idx, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                sections.append(text)
            for i, info in enumerate(page.get_image_info()):
                rect = info.get("bbox")
                if not rect:
                    continue
                ocr = _ocr_crop(intermediate, page_idx, tuple(rect), workdir, i)
                blobs = [b.text for b in ocr.blocks if b.text.strip()]
                sections.append("".join(blobs) if blobs else "[anh khong nhan dien duoc]")
    finally:
        doc.close()
    out.write_text("\n\n".join(sections), encoding="utf-8-sig")
    return out


def _count_output_images(final: Path, target_fmt: str) -> int:
    if target_fmt == "pdf":
        return count_pdf_images(final)
    if family_of(target_fmt) == "zip":
        return count_embedded_images(final, target_fmt) or 0
    if target_fmt == "html":
        try:
            return count_html_images(final.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return 0
    if target_fmt == "txt":
        return 0
    return 0


def _fail_brief(exc: BaseException, tb: bool = False) -> RunResult:
    reason = getattr(exc, "reason", None) or str(exc)
    lines = [f"Ly do: {reason}"]
    if isinstance(exc, LibreOfficeError) and "LibreOffice" in reason:
        lines.append("Goi y: cai LibreOffice headless (tu 26.x) de su dung tinh nang chuyen doi")
    elif isinstance(exc, (ConvertError, ValueError)):
        lines.append("Goi y: kiem tra lai file (dinh dang, dung luong) hoac dung dinh dang nguon khac")
    else:
        lines.append("Goi y: chay lai; neu van loi, gui log cho developer")
        if tb:
            lines.append(traceback.format_exc())
    return RunResult(brief=Brief(ok=False, lines=lines, failure_reason=reason))
