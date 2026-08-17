import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class PageSpec:
    page_number: int


class SourceAdapter(ABC):
    name: str = "base"
    page_selector: str = ".page"

    @abstractmethod
    def matches(self, url: str) -> bool: ...

    @abstractmethod
    def normalize(self, url: str) -> str: ...

    @abstractmethod
    def page_elements_js(self) -> str:
        """JS returning the list of page elements in reading order."""

    def fetch_pages(self, url: str, out_dir) -> list | None:
        """Tùy chọn: lấy ảnh trang trực tiếp (không cần Playwright). None = dùng capture."""
        raise NotImplementedError


class ScribdAdapter(SourceAdapter):
    name = "scribd"
    page_selector = ".outer_page"

    EMBED_RE = re.compile(r"/embeds/(?P<id>\d+)")
    DOCUMENT_RE = re.compile(r"/document/(?P<id>\d+)")

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "scribd.com" or host.endswith(".scribd.com")

    def normalize(self, url: str) -> str:
        embed = self.EMBED_RE.search(url)
        if embed:
            doc_id = embed.group("id")
        else:
            doc = self.DOCUMENT_RE.search(url)
            if not doc:
                raise ValueError("Khong nhan dien duoc ID Scribd trong link")
            doc_id = doc.group("id")
        return f"https://www.scribd.com/embeds/{doc_id}/content"

    def page_elements_js(self) -> str:
        return (
            "() => Array.from(document.querySelectorAll('.outer_page')).map(el => {"
            " const m = (el.id || '').match(/outer_page_(\\d+)/);"
            " return { number: m ? Number(m[1]) : 0 };"
            "}).filter(p => p.number > 0)"
        )


def get_adapter(url: str) -> SourceAdapter:
    for adapter in _all_adapters():
        if adapter.matches(url):
            return adapter
    raise ValueError(f"Khong co adapter cho URL nay: {url}")


def _all_adapters() -> list[SourceAdapter]:
    from .drive import GoogleDriveAdapter

    return [ScribdAdapter(), GoogleDriveAdapter()]
