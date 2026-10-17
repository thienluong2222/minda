# Sửa lỗi không xem trước được DOCX — 17/10/2026

## Nguyên nhân đã tái hiện

Log tác vụ biên bản `89e65e78-100d-4ef5-a9b6-694e780bc31b` báo thiếu
LibreOffice/Poppler. Máy chỉ có bộ công cụ render đi kèm môi trường Codex,
chưa có bản cài dùng từ Terminal thông thường. Kiểm thử trong môi trường
Codex tìm được công cụ nhưng khi người dùng chạy launcher từ Terminal,
worker không tìm được nên lưu phiên bản với `previews: []`.

QuickLook đã tạo thumbnail một trang cho biên bản, nhưng thumbnail không phải
preview đầy đủ các trang mà giao diện yêu cầu. Vì vậy xuất Word vẫn thành
công trong khi khu vực xem trước không có trang nào.

## Thay đổi

- Cài Poppler và LibreOffice độc lập trên máy qua Homebrew.
- Thống nhất tìm công cụ ở `minutes/document_tools.py`: PATH, vị trí cài
  LibreOffice chuẩn trên macOS và các thư mục binary phổ biến. Nhận cả tên
  `soffice` và `libreoffice`.
- Renderer, chuyển DOC, đọc PDF scan và báo cáo khả năng hệ thống dùng cùng
  cách tìm công cụ. `doctor` cung cấp cả đường dẫn trong `preview_tools`.
- Launcher báo ngay khi thiếu công cụ render. Lần duyệt mẫu thành công xóa
  thông báo preview lỗi cũ khỏi metadata của phiên bản mới.
- Thêm `repair-previews` (mặc định chỉ liệt kê) và `repair-previews --apply`
  để bổ sung ảnh cho phiên bản mẫu/biên bản đã lưu mà không có ảnh.
- Lệnh phục hồi dùng khóa worker, ghi ảnh vào thư mục riêng, đăng ký artifact
  với đúng owner/resource và cập nhật metadata preview. Không chạy ASR/LLM,
  không ghi lại DOCX, facts, ZIP/manifest hoặc trạng thái rà soát.
- Browser smoke có `--template-id`; khi chọn mẫu hoặc biên bản, phải tải được
  ảnh và chuyển qua toàn bộ trang mới được báo đạt.

## Xác minh

### Kiểm thử tự động

```bash
PYTHONPATH=src .venv-backend/bin/python -m pytest \
  tests/unit/test_document_tools.py tests/unit/test_minutes_formatting.py tests/backend -q
```

**38 passed**, 2 warning deprecation từ FastAPI/Starlette, 49,60 giây.
Ruff và `git diff --check` đạt.

Bài kiểm tra mới bỏ PATH của Codex và Homebrew, chỉ giữ `/usr/bin:/bin`;
renderer vẫn tìm được công cụ ở vị trí cài chuẩn. Đã kiểm:

- Render DOCX hai trang và nhận PNG hợp lệ qua API.
- Phục hồi mẫu và biên bản thiếu ảnh; chạy lại không tạo thêm ảnh/phiên bản.
- SHA-256 DOCX/ZIP và facts, ID phiên bản, trạng thái đã rà soát không đổi.
- Người dùng khác xem được preview mẫu dùng chung; preview biên bản riêng
  vẫn trả 404.

### Chrome thực tế

Chạy với PATH Terminal thông thường, dùng database, tài khoản và server tạm:

- **14 trang** user/admin, không có lỗi JavaScript được ghi nhận.
- Mẫu DOCX và biên bản mới đều có **2 trang**; từng trang được tải và giải mã.
- Đã xem ảnh chụp màn hình: preview hiển thị nội dung, bộ chuyển trang và nút
  tải Word ở cả thư viện mẫu và tab biên bản.
- Không phát hiện tràn ngang viewport mobile trong smoke.
- Server/database thử nghiệm được dọn sau kiểm tra; server chính không được
  khởi động lại.

Ảnh và báo cáo: `data/evaluations/docx-preview-fix-20261017/`.

### Phục hồi dữ liệu đang có

Đã phục hồi trên database `meeting_app_dev`, thư mục `data/app`:

| Loại | Phiên bản | Số trang |
| --- | --- | --- |
| Mẫu | `299728bc-5e9f-47c4-973d-c0d4f60f39d9` | 2 |
| Biên bản | `65d75203-2aef-4535-a1b6-92e89e7bae4a` | 3 |

Đã so SHA-256 **4 file gốc** trước/sau, giữ nguyên nội dung phiên bản và
metadata cuộc họp/mẫu. Báo cáo phục hồi nằm tại
`data/app/maintenance/preview-repair-2026-10-17.json`.

Các ảnh phục hồi là dữ liệu dẫn xuất mới. File báo cáo/ZIP gốc giữ nguyên
trạng thái lúc xuất; metadata preview trên web được cập nhật theo lần phục hồi.

## Sử dụng

Khởi động web theo [QUICKSTART](QUICKSTART.md), mở lại mẫu hoặc tab Biên bản.
Tài liệu cũ đã có preview, không cần tải lại file hay tạo lại nội dung. Máy
khác cần cài công cụ render riêng theo phần hướng dẫn trong QUICKSTART.
