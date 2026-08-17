import argparse
import sys
from pathlib import Path

from engine.convert import convert_file
from engine.convert.formats import TARGETS


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="convert",
        description="Chuyển đổi file bài tập/tài liệu sang định dạng khác. Ảnh trong file nguồn "
        "được giữ nguyên vẹn + thêm lớp text OCR (nguyên lý scan-de).",
    )
    parser.add_argument("file", help="Đường dẫn file nguồn (docx, doc, xlsx, pptx, pdf, ảnh, txt, html...)")
    parser.add_argument("mon", help="Tên môn học, quyết định folder đích D:\\Chuyen doi\\{Môn}\\")
    parser.add_argument("--to", choices=TARGETS, default="pdf", help="Định dạng đích (mặc định: pdf)")
    parser.add_argument("--out", help="Folder đích thay thế (mặc định: D:\\Chuyen doi\\{Môn}\\)")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else None
    result = convert_file(Path(args.file), args.mon, target=args.to, out_dir=out_dir)
    print(result.brief.render())
    return 0 if result.brief.ok else 1


if __name__ == "__main__":
    sys.exit(main())
