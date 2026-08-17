import os
from pathlib import Path

import fitz

from .ocr import OcrPageResult


class PdfBuildError(Exception):
    pass


_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _load_font() -> fitz.Font | None:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return fitz.Font(fontfile=path)
            except Exception:
                continue
    return None


def build_searchable_pdf(page_images: list[Path], ocr_pages: list[OcrPageResult], out_path: Path) -> int:
    from PIL import Image

    font = _load_font()
    doc = fitz.open()
    try:
        for i, img_path in enumerate(page_images):
            with Image.open(img_path) as pil:
                w, h = pil.size

            page = doc.new_page(width=w, height=h)
            page.insert_image(page.rect, filename=str(img_path))

            if font is not None and i < len(ocr_pages):
                tw = fitz.TextWriter(page.rect)
                for b in ocr_pages[i].blocks:
                    if not b.text.strip():
                        continue
                    pdf_x = b.x
                    pdf_y = h - b.y - b.h
                    size = max(4.0, b.h * 0.98)
                    try:
                        tw.append(fitz.Point(pdf_x, pdf_y + size), b.text, font=font, fontsize=size)
                    except Exception:
                        continue
                tw.write_text(page, render_mode=3, color=(0, 0, 0, 0))
        doc.save(str(out_path), deflate=True, garbage=3)
    finally:
        doc.close()
    return len(page_images)


def overlay_image_ocr_layer(
    pdf_path: Path,
    out_path: Path,
    ocr_regions: list[list[tuple[tuple[float, float, float, float], "OcrPageResult"]]],
) -> int:
    """Thêm lớp text OCR ẩn lên từng vùng ảnh (bbox điểm PDF) của PDF có sẵn."""
    font = _load_font()
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    try:
        for page_index, page in enumerate(doc):
            regions = ocr_regions[page_index] if page_index < len(ocr_regions) else []
            if not regions:
                continue
            page_h = page.rect.height
            tw = fitz.TextWriter(page.rect)
            appended = 0
            for (x0, y0, x1, y1), ocr in regions:
                for b in ocr.blocks:
                    if not b.text.strip():
                        continue
                    size = max(4.0, b.h * 0.98)
                    px = x0 + b.x
                    py = page_h - (y0 + b.y + b.h)
                    try:
                        tw.append(fitz.Point(px, py + size), b.text, font=font, fontsize=size)
                        appended += 1
                    except Exception:
                        continue
            if appended:
                tw.write_text(page, render_mode=3, color=(0, 0, 0, 0))
        doc.save(str(out_path), deflate=True, garbage=3)
    finally:
        doc.close()
    return page_count
