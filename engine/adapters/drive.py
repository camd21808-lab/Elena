import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import fitz

from .base import SourceAdapter
from ..validate import resolve_private_ip

_DRIVE_FILE_RE = re.compile(r"/file/d/([^/?#]+)")
_DRIVE_ID_RE = re.compile(r"[?&]id=([^&#]+)")
_DOC_RE = re.compile(r"/document/d/([^/?#]+)")
_SHEET_RE = re.compile(r"/spreadsheets/d/([^/?#]+)")
_SLIDES_RE = re.compile(r"/presentation/d/([^/?#]+)")
_DRIVE_FORM_RE = re.compile(r"/forms/d/([^/?#]+)")
_CONFIRM_RE = re.compile(r"confirm=([0-9A-Za-z_-]+)")

_IMAGE_SIGS = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webp"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)

_MAX_MB = 100

# Drive tải file có thể redirect (virus scan / confirm / content) tới các host
# thuộc Google — chặn mọi host khác (chống SSRF qua redirect lừa).
_REDIRECT_ALLOWED = (
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
    "lh3.googleusercontent.com",
    "lh4.googleusercontent.com",
    "lh5.googleusercontent.com",
    "googleusercontent.com",
    "googleapis.com",
)


def _cerr(reason: str, permanent: bool = True):
    from ..capture import CaptureError

    return CaptureError(reason, permanent)


def _redirect_ok(host: str) -> bool:
    host = host.lower()
    if host in _REDIRECT_ALLOWED:
        return True
    if host.endswith(".googleusercontent.com"):
        return True
    if host.endswith(".googleapis.com"):
        return True
    return False


class GoogleDriveAdapter(SourceAdapter):
    name = "gdrive"
    page_selector = ".page, .kix-page"

    def matches(self, url: str) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        return host in ("drive.google.com", "docs.google.com")

    def normalize(self, url: str) -> str:
        kind, doc_id = self._parse(url)
        return f"gdrive://{kind}/{doc_id}"

    def page_elements_js(self) -> str:
        return "() => Array.from(document.querySelectorAll('.page, .kix-page')).map(el => ({number: 0}))"

    def fetch_pages(self, url: str, out_dir: Path) -> list[Path]:
        """Táº£i file/export PDF tá»« Drive â†’ render tá»«ng trang thÃ nh áº£nh (khÃ´ng dÃ¹ng Playwright)."""
        kind, doc_id = self._parse(url)
        out_dir.mkdir(parents=True, exist_ok=True)

        if kind == "file":
            dl_url = self._file_download_url(doc_id)
        else:
            dl_url = (
                f"https://docs.google.com/{kind}/d/{doc_id}/export?format=pdf"
                if kind in ("document", "spreadsheets", "presentation")
                else f"https://drive.google.com/uc?export=download&id={doc_id}"
            )

        content, final_url = self._download(dl_url, doc_id)
        magic = content[:16]

        if magic.startswith(b"%PDF"):
            pdf_path = out_dir / "source.pdf"
            pdf_path.write_bytes(content)
            return render_pdf_to_images(pdf_path, out_dir)

        for sig, _ in _IMAGE_SIGS:
            if magic.startswith(sig):
                img_path = out_dir / "source_img"
                img_path.write_bytes(content)
                from PIL import Image

                img = Image.open(img_path)
                ext = img.format.lower() if img.format else "png"
                img_path = img_path.with_suffix(f".{ext}")
                img.save(img_path)
                return [img_path]

        head = content[:2000].decode("utf-8", "ignore")
        if b"confirm=" in content[:2000] or "<html" in head.lower():
            confirm = _CONFIRM_RE.search(head)
            if confirm:
                retry_url = f"{final_url}&confirm={confirm.group(1)}"
                content, _ = self._download(retry_url, doc_id)
                if content[:4] == b"%PDF":
                    pdf_path = out_dir / "source.pdf"
                    pdf_path.write_bytes(content)
                    return render_pdf_to_images(pdf_path, out_dir)
            raise _cerr(
                "File Google Drive khong tai duoc - can 'bat ky ai co link' de chia se (public)",
                permanent=True,
            )

        raise _cerr(
            "File Google Drive khong phai PDF/anh hoac khong truy cap duoc (quyen rieng tu)",
            permanent=True,
        )

    def _file_download_url(self, doc_id: str) -> str:
        return f"https://drive.google.com/uc?export=download&id={doc_id}"

    def _download(self, url: str, doc_id: str) -> tuple[bytes, str]:
        host = urlparse(url).hostname or ""
        private = resolve_private_ip(host)
        if private:
            raise _cerr(f"Host '{host}' giai ve IP noi bo ({private}) - bi chan", permanent=True)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
                final_url = resp.geturl()
        except Exception as exc:
            raise _cerr(
                f"Khong tai duoc file tu Google Drive: {exc}",
                permanent=False,
            ) from exc
        final_host = (urlparse(final_url).hostname or "").lower()
        if not _redirect_ok(final_host):
            raise _cerr(f"Drive redirect toi host khong cho phep ({final_host}) - bi chan", permanent=True)
        if len(content) > _MAX_MB * 1024 * 1024:
            raise _cerr(f"File Drive qua lon (>{_MAX_MB} MB)", permanent=True)
        if not content:
            raise _cerr("File Drive rong", permanent=True)
        return content, final_url

    def _parse(self, url: str) -> tuple[str, str]:
        m = _DRIVE_FORM_RE.search(url)
        if m:
            raise _cerr("Google Form khong chuyen doi duoc", permanent=True)
        m = _DOC_RE.search(url)
        if m:
            return "document", m.group(1)
        m = _SHEET_RE.search(url)
        if m:
            return "spreadsheets", m.group(1)
        m = _SLIDES_RE.search(url)
        if m:
            return "presentation", m.group(1)
        m = _DRIVE_FILE_RE.search(url)
        if m:
            return "file", m.group(1)
        m = _DRIVE_ID_RE.search(url)
        if m:
            return "file", m.group(1)
        raise _cerr(
            "Khong nhan dien duoc link Google Drive (dang: /file/d/ID/view, open?id=ID, /document/d/ID)",
            permanent=True,
        )


def render_pdf_to_images(pdf_path: Path, out_dir: Path, zoom: float = 2.0, max_pages: int = 200) -> list[Path]:
    doc = fitz.open(str(pdf_path))
    try:
        total = len(doc)
        if total > max_pages:
            raise _cerr(f"Tai lieu qua nhieu trang ({total} > {max_pages})", permanent=True)
        images: list[Path] = []
        matrix = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out = out_dir / f"page_{i + 1:04d}.png"
            pix.save(str(out))
            images.append(out)
        return images
    finally:
        doc.close()


