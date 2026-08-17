import zipfile
from pathlib import Path

import fitz

from .formats import family_of, is_image_ext

_MEDIA_DIRS = (
    "word/media/",
    "xl/media/",
    "ppt/media/",
    "media/",
    "Pictures/",
    "Object 1/",
)


def count_embedded_images(path: Path, ext: str) -> int | None:
    """Đếm ảnh nhúng trong file nguồn. Trả None khi không thể xác định (định dạng cũ)."""
    fam = family_of(ext)
    if fam == "image":
        return 1
    if fam == "plain":
        return 0
    if fam == "zip":
        return _count_zip_media(path)
    if fam == "pdf":
        return _count_pdf_images(path)
    if fam == "rtf":
        return _count_rtf_images(path)
    if fam == "html":
        return _count_html_images(path)
    return None


def _count_zip_media(path: Path) -> int | None:
    try:
        with zipfile.ZipFile(path) as z:
            names = [n.replace("\\", "/") for n in z.namelist()]
    except (zipfile.BadZipFile, OSError):
        return None
    count = 0
    for n in names:
        if n.startswith(_MEDIA_DIRS) and not n.endswith("/"):
            count += 1
    return count


def _count_pdf_images(path: Path) -> int:
    doc = fitz.open(str(path))
    try:
        seen: set[tuple[int, int]] = set()
        for page in doc:
            for img in page.get_images(full=True):
                seen.add((img[0], img[1]))
        return len(seen)
    finally:
        doc.close()


def _count_rtf_images(path: Path) -> int:
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    return data.count(b"\\pict")


def _count_html_images(path: Path) -> int:
    from .formats import count_html_images as _c

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return _c(text)


def pdf_image_regions(pdf_path: Path) -> list[list[tuple[float, float, float, float]]]:
    """Bounding box (x0, y0, x1, y1) điểm PDF của từng ảnh, theo từng trang."""
    doc = fitz.open(str(pdf_path))
    try:
        pages: list[list[tuple[float, float, float, float]]] = []
        for page in doc:
            rects: list[tuple[float, float, float, float]] = []
            for info in page.get_image_info():
                r = info.get("bbox")
                if r:
                    rects.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
            pages.append(rects)
        return pages
    finally:
        doc.close()


def count_pdf_images(pdf_path: Path) -> int:
    return _count_pdf_images(pdf_path)
