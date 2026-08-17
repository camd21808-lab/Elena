# Ghi chú tính năng Bảo vệ PDF (Elena)

## qpdf CLI
- Đã tải và đặt tại `tools/qpdf/bin/qpdf.exe` (bản v11.9.1 theo link trong đề bài
  không còn tồn tại → đã dùng bản mới nhất `v12.3.2`).
- `restrict_permissions()` ưu tiên dùng qpdf trên PATH, sau đó kiểm tra
  `tools/qpdf/bin/qpdf.exe`. Tham số khoá quyền: `--print=none`, `--modify=none`,
  `--extract=n`, `--annotate=n` (qpdf 12 không chấp nhận dạng `--print=` trống).

## Fallback pypdf
- Nếu không tìm thấy qpdf, `restrict_permissions()` tự động fallback sang pypdf
  (AES-256). Đã kiểm thử: file vẫn mã hoá AES-256 và khoá được quyền.
- Lưu ý API pypdf 6.x: `PdfWriter.encrypt()` không còn nhận `allow_print=...`
  mà dùng `permissions_flag` (`pypdf.constants.UserAccessPermissions`).
  Code thử `allow_*` trước, nếu `TypeError` thì chuyển sang `permissions_flag`.

## Phụ thuộc mới
- `pypdf`, `reportlab`, `cryptography` (pypdf cần `cryptography` cho mã hoá AES-256).
  Cài bằng: `.venv\Scripts\python.exe -m pip install pypdf reportlab cryptography`
- `pymupdf` (fitz) đã có sẵn.

## Hành vi pipeline (`protect_file`)
- Thứ tự: redact → watermark → sanitize → permissions → password (cuối cùng).
- Nếu bật cả "khoá quyền" lẫn "mật khẩu": bước khoá quyền đã mã hoá bằng đúng
  user_password + quyền hạn, bước mật khẩu chỉ đi qua để tránh mất quyền đã đặt.
- Nếu thiếu cả qpdf lẫn pypdf khi cần khoá quyền → `ValueError` bằng tiếng Việt,
  job hiển thị brief thất bại (không crash).
