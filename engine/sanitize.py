"""engine/sanitize.py — khử path traversal / ký tự nguy hiểm khỏi tên thư mục môn
và tên đề trước khi dùng làm đường dẫn file. Dùng ở API boundary + engine
(defense in depth) để không file nào rơi ra ngoài local_root / convert_root.
"""

import re

_FOLDER_SAFE = re.compile(r"[^\w\u00C0-\u024F\s\-()]+")
_PART_SAFE = re.compile(r"[^\w\u00C0-\u024F\s\-().,+]+")


def _strip_traversal(name: str) -> str:
    name = name.replace("\\", "/")
    name = re.sub(r"\.\.", "_", name)
    return name.strip(" ./")


def sanitize_folder(name: str, max_len: int = 100) -> str:
    """Tên thư mục môn học: không separator, không '..', chỉ chữ/số/dấu tiếng Việt."""
    name = _strip_traversal(name or "")
    name = _FOLDER_SAFE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len]


def sanitize_filename_part(name: str, max_len: int = 150) -> str:
    """Phần tên file (ten_de, tên nguồn...): như trên nhưng giữ thêm dấu chấm/phẩy."""
    name = _strip_traversal(name or "")
    name = _PART_SAFE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len]
