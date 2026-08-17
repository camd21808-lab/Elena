import argparse
import sys

from engine.pipeline import derive_ky, run_scan


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scan",
        description="Scan đề thi từ link embed thành PDF searchable, lưu vào folder môn học.",
    )
    parser.add_argument("link", help="Link embed (Scribd) hoặc trang tài liệu")
    parser.add_argument("mon", help="Tên môn học, ví dụ 'Giải tích 1'")
    parser.add_argument("ten_de", help="Tên đề, ví dụ 'Đề giữa kỳ 2024'")
    parser.add_argument("--ky", choices=["HK1", "HK2"], help=f"Mặc định tự suy: {derive_ky()}")
    args = parser.parse_args()

    result = run_scan(args.link, args.mon, args.ten_de, ky=args.ky)
    print(result.brief.render())
    return 0 if result.brief.ok else 1


if __name__ == "__main__":
    sys.exit(main())
