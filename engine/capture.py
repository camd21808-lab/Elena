import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, Page, TimeoutError as PWTimeoutError, sync_playwright

from .adapters.base import SourceAdapter
from .config import settings


class CaptureError(Exception):
    def __init__(self, reason: str, permanent: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent


@dataclass
class CaptureResult:
    page_images: list[Path] = field(default_factory=list)
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _launch(playwright) -> Browser:
    if settings.use_system_chrome:
        try:
            return playwright.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            pass
    return playwright.chromium.launch(headless=True)


def _page_ready(page: Page, selector: str, idx: int) -> bool:
    return page.evaluate(
        """([sel, idx]) => {
            const el = document.querySelectorAll(sel)[idx];
            if (!el) return false;
            const img = el.querySelector('img');
            if (img) return img.complete && img.naturalWidth > 0;
            return el.getBoundingClientRect().height > 50;
        }""",
        [selector, idx],
    )


def _wait_page_ready(page: Page, selector: str, idx: int, tries: int = 30) -> bool:
    for _ in range(tries):
        if _page_ready(page, selector, idx):
            return True
        page.wait_for_timeout(500)
    return False


def _capture_page(page: Page, selector: str, idx: int, out_dir: Path, total: int) -> Path:
    el = page.locator(selector).nth(idx)
    el.scroll_into_view_if_needed(timeout=15000)
    bbox = el.bounding_box()
    if bbox is None or bbox["height"] < 50:
        raise CaptureError(f"Khong lay duoc kich thuoc trang {idx + 1}/{total}")

    viewport = page.viewport_size or {"width": 1280, "height": 1600}
    needed = int(bbox["height"]) + 150
    if needed > viewport["height"]:
        page.set_viewport_size({"width": viewport["width"], "height": needed})
        page.wait_for_timeout(600)
        el.scroll_into_view_if_needed(timeout=15000)
        bbox = el.bounding_box()
        if bbox is None:
            raise CaptureError(f"Trang {idx + 1}/{total} mat sau khi doi viewport")

    if not _wait_page_ready(page, selector, idx):
        raise CaptureError(
            f"Trang {idx + 1}/{total} khong render xong sau 15s (viewer block hoac mang cham)",
            permanent=False,
        )

    out = out_dir / f"page_{idx + 1:04d}.png"
    page.screenshot(
        clip={"x": bbox["x"], "y": bbox["y"], "width": bbox["width"], "height": bbox["height"]},
        path=str(out),
        animations="disabled",
    )
    if not out.exists() or out.stat().st_size < 1024:
        raise CaptureError(f"Screenshot trang {idx + 1}/{total} rong hoac loi", permanent=True)
    return out


def capture(url: str, adapter: SourceAdapter, out_dir: Path, max_pages: int = 200) -> CaptureResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 1600},
                device_scale_factor=2,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                locale="vi-VN",
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            try:
                page.goto(url, wait_until="load", timeout=45000)
            except PWTimeoutError:
                raise CaptureError("Trang khong tai duoc trong 45s (mang treo?)", permanent=False)
            page.add_style_tag(
                content="* { scroll-behavior: auto !important; transition: none !important; animation: none !important; }"
            )
            page.wait_for_timeout(2500)

            selector = adapter.page_selector
            pages = page.evaluate(adapter.page_elements_js())
            if not pages:
                raise CaptureError(
                    "Khong tim thay element trang cua tai lieu - viewer chua ho tro hoac bi chan",
                    permanent=True,
                )
            total = len(pages)
            if total > max_pages:
                raise CaptureError(f"Tai lieu qua nhieu trang ({total} > {max_pages})", permanent=True)

            result = CaptureResult()
            for i in range(total):
                shot = _capture_page(page, selector, i, out_dir, total)
                result.page_images.append(shot)
            result.page_count = total
            return result
        finally:
            browser.close()
