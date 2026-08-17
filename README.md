# Scan-de — đề thi → PDF searchable + chuyển đổi file giữ nguyên ảnh

- **Scan đề**: link tài liệu (Scribd) → PDF searchable, giữ nguyên ảnh/công thức, tự lưu `D:\Đề thi\{Môn}\`.
- **Chuyển đổi file**: file bài tập/tài liệu (docx, pdf, xlsx, pptx, ảnh...) → pdf/docx/txt/html/xlsx/csv. Chữ chuyển đổi thường (vẫn edit được); **ảnh trong file được giữ nguyên vẹn + thêm lớp text OCR ẩn** (nguyên lý scan-de) — không bao giờ hỏng hay mất. Lưu vào `D:\Chuyen doi\{Môn}\`.

## Kiến trúc

```
CLI (scan.cmd / convert.cmd) ──┐
                               ├──> engine (validate → capture/convert → RapidOCR → PyMuPDF)
Web UI (Vite) ──── tabs ───────┼──> FastAPI /jobs + /convert ──> queue ──> worker
                               │        (allowlist domain + magic-byte + rate limit + TTL)
```

- **engine/**: validate (SSRF check cho link; magic-byte + size cap cho file), adapter per-source, capture Playwright, OCR RapidOCR, build searchable PDF (ảnh nền + text layer ẩn), placement.
- **engine/convert/**: formats registry + ma trận định dạng, đếm/trích ảnh nhúng + vị trí (bbox), wrapper LibreOffice headless (`soffice --convert-to`), pipeline convert (fast path không OCR khi file không ảnh; đường fidelity khi có ảnh), verify ảnh giữ được.
- **api/**: FastAPI — `POST /jobs` (scan), `POST /convert` (upload multipart), `GET /jobs/{id}`, `GET /jobs/{id}/download`. Queue pluggable: in-process (mặc định) hoặc Redis/RQ (`SCANDE_QUEUE=redis`).
- **cli/scan.py + cli/convert.py**: loop cá nhân.
- **ui/**: Vite + React SPA 2 tab (Scan đề / Chuyển đổi file) × 3 màn (input → processing → result), palette "Living Nature".

## Chạy local (không cần Docker)

Yêu cầu: **LibreOffice** (để chuyển đổi định dạng office) — cài bản stable tại https://www.libreoffice.org/download/.

```powershell
# Scan đề (CLI loop cá nhân)
cd D:\App\scan-de
.\scan.cmd "https://www.scribd.com/document/941072088/...#fullscreen=1" "English" "Mock Test 3"

# Chuyển đổi file — ảnh trong file giữ nguyên + OCR
.\convert.cmd "D:\Downloads\bai tap.docx" "Toan 12"            # → D:\Chuyen doi\Toan 12\bai tap.pdf
.\convert.cmd "D:\Downloads\bai tap.docx" "Toan 12" --to txt   # ảnh chuyển thành text OCR

# API + UI
$env:PYTHONPATH = "D:\App\scan-de"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
cd ui; npm run dev   # http://localhost:5173
```

## Cấu hình (.env)

| Biến | Mặc định |
|---|---|
| `SCANDE_DOMAIN_ALLOWLIST` | `scribd.com,*.scribd.com,drive.google.com,docs.google.com` |
| `SCANDE_LOCAL_ROOT` | `D:\Đề thi` |
| `SCANDE_CONVERT_ROOT` | `D:\Chuyen doi` |
| `SCANDE_CONVERT_MAX_MB` | `50` (giới hạn file upload) |
| `SCANDE_SOFFICE` | `C:\Program Files\LibreOffice\program\soffice.exe` |
| `SCANDE_DRIVE_ROOT` | *(trống — để trống nếu chưa mount Google Drive)* |
| `SCANDE_QUEUE` | `inprocess` hoặc `redis` |
| `SCANDE_REDIS_URL` | `redis://localhost:6379/0` |
| `SCANDE_MAX_CONCURRENT` | `2` |
| `SCANDE_JOB_TIMEOUT` | `600` (giây) |
| `SCANDE_TEMP_TTL_HOURS` | `24` |
| `SCANDE_SYSTEM_CHROME` | `true` (dùng Chrome hệ thống; Docker dùng Chromium riêng) |

## Deploy bản chính thức lên cloud (không cần Docker local)

Máy local (Win10 1903, VT-x tắt) không chạy được Docker Desktop — nhưng cloud deploy **không cần Docker trên máy này**:

1. Push code lên GitHub (Railway/Fly/Render tự build Dockerfile).
2. Dùng `docker/docker-compose.yml` cho deploy nhiều service (redis + api + worker).
3. Đặt env: `SCANDE_QUEUE=redis`, `SCANDE_REDIS_URL`, `SCANDE_LOCAL_ROOT=/data/de-thi`, `SCANDE_SYSTEM_CHROME=false` (worker trong container có Chromium riêng — sandbox chuẩn).
4. Storage: thay folder local bằng S3/R2 (P1) khi cần scale.

Không cần cài Docker Desktop — máy này chạy local bằng queue in-process là đủ cho test.

## Lưu ý

- **Pháp lý**: chỉ dùng cho tài liệu cá nhân/giáo dục. Nội dung trả phí có watermark và vi phạm ToS nguồn.
- **Bảo mật**: allowlist domain + chặn IP private (SSRF) cho scan; magic-byte + size cap + TTL cho upload convert. Sandbox container đạt được khi deploy cloud (worker chạy trong container có Chromium riêng).
- **OCR**: RapidOCR (tiếng Việt) chạy CPU. Confidence < 50% → file vẫn xuất, brief đánh dấu CẢNH BÁO.
- **Convert + ảnh**: ảnh nhúng được đếm từ file nguồn; brief luôn báo `ảnh giữ được / tổng`. PDF = ảnh gốc + lớp text OCR ẩn; DOCX/HTML = ảnh giữ bởi LibreOffice (OCR alt-text là P1); TXT = ảnh chuyển thành text OCR; XLSX/CSV thường không giữ được ảnh (brief báo rõ).
