import statistics
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .config import settings

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover
    RapidOCR = None


@dataclass
class OcrBlock:
    text: str
    x: float
    y: float
    w: float
    h: float
    score: float


@dataclass
class OcrPageResult:
    blocks: list[OcrBlock] = field(default_factory=list)
    confidence: float = 1.0
    warning: bool = False


_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        if RapidOCR is None:
            raise RuntimeError("rapidocr_onnxruntime khong cai duoc tren Python nay")
        _engine = RapidOCR(params={"Global.det_limit_side_len": 1920})
    return _engine


def ocr_page(image_path: Path, max_side: int = 1920) -> OcrPageResult:
    img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = img.size
    scale = min(1.0, max_side / max(orig_w, orig_h))
    if scale < 1.0:
        img = img.resize((int(orig_w * scale), int(orig_h * scale)), Image.LANCZOS)

    import numpy as np

    result, _ = _get_engine()(np.array(img))
    blocks: list[OcrBlock] = []
    for item in result or []:
        pts, text, score = item[0], item[1], float(item[2])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        blocks.append(
            OcrBlock(
                text=str(text),
                x=min(xs) / scale,
                y=min(ys) / scale,
                w=(max(xs) - min(xs)) / scale,
                h=(max(ys) - min(ys)) / scale,
                score=score,
            )
        )

    if not blocks:
        return OcrPageResult(warning=True)

    confidence = statistics.mean(b.score for b in blocks)
    return OcrPageResult(
        blocks=blocks,
        confidence=confidence,
        warning=confidence < settings.ocr_confidence_warning,
    )
