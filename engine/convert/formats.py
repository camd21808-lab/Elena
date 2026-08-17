import re
from pathlib import Path

TARGETS = ["pdf", "docx", "txt", "html", "xlsx", "csv"]

SOURCE_EXTS = {
    "docx", "doc", "xlsx", "xls", "pptx", "ppt",
    "odt", "ods", "odp", "rtf", "txt", "csv",
    "pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff", "html", "htm",
}

_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}
_ZIP_EXTS = {"docx", "xlsx", "pptx", "odt", "ods", "odp"}
_OLE_EXTS = {"doc", "xls", "ppt"}
_PLAIN_EXTS = {"txt", "csv"}

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_MAGIC = b"%PDF"


def family_of(ext: str) -> str:
    ext = ext.lower()
    if ext in _ZIP_EXTS:
        return "zip"
    if ext in _OLE_EXTS:
        return "ole"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext == "rtf":
        return "rtf"
    if ext in ("html", "htm"):
        return "html"
    if ext in _PLAIN_EXTS:
        return "plain"
    return "unknown"


def is_image_ext(ext: str) -> bool:
    return family_of(ext) == "image"


def magic_matches(path: Path, ext: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    fam = family_of(ext)
    if fam == "zip":
        return head.startswith(_ZIP_MAGIC)
    if fam == "ole":
        return head.startswith(_OLE_MAGIC)
    if fam == "pdf":
        return head.startswith(_PDF_MAGIC)
    if fam == "image":
        if ext == "png":
            return head.startswith(b"\x89PNG\r\n\x1a\n")
        if ext in ("jpg", "jpeg"):
            return head[:3] == b"\xff\xd8\xff"
        if ext == "webp":
            return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
        if ext == "bmp":
            return head[:2] == b"BM"
        if ext == "tiff":
            return head[:4] in (b"II*\x00", b"MM\x00*")
    if fam == "rtf":
        return head[:5].lower() == b"{\\rtf"
    if fam == "html":
        low = head.lower()
        return b"<!doctype html" in low or b"<html" in low
    if fam == "plain":
        return not head.startswith(b"\x00") and not head.startswith(_PDF_MAGIC) and not head.startswith(_ZIP_MAGIC)
    return False


def normalize_target(target: str | None) -> str:
    t = (target or "pdf").strip().lower().lstrip(".")
    if t not in TARGETS:
        raise ValueError(f"Định dạng đích không hỗ trợ: {t} (hỗ trợ: {', '.join(TARGETS)})")
    return t


_LO_EXT_FILTER = {
    "pdf": "pdf:writer_pdf_Export",
    "docx": "docx",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:XHTML Writer File",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "csv": "csv:Text - txt - csv (StarCalc)",
}

_HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def lo_filter_for(target: str) -> str:
    return _LO_EXT_FILTER.get(target, target)


def count_html_images(text: str) -> int:
    return len(_HTML_IMG_RE.findall(text))
