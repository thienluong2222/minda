# Chạy prototype web user/admin

Hướng dẫn thao tác từng màn hình, quy trình tạo biên bản và các chức năng quản trị:
[Báo cáo hướng dẫn sử dụng web mới](../BAO_CAO_HUONG_DAN_SU_DUNG_WEB_MOI_2026-10-17.md).

**Thư mục hiện tại:** thư mục gốc của repository (đã hợp nhất toàn bộ frontend `apps/web`, backend `src/meeting_backend` và pipeline `src/meeting_pipeline` vào nhánh `main`). Chạy mọi lệnh bên dưới từ thư mục gốc dự án.

## 1. Môi trường và cài đặt

Prototype dùng macOS Apple Silicon, Python 3.11, Node 22.12+/24, MongoDB local,
FFmpeg/ffprobe, LibreOffice + Poppler cho preview và Tesseract cho OCR.
Trong checkout mới, tạo môi trường riêng:

```bash
UV_PROJECT_ENVIRONMENT=.venv-backend uv sync --locked --extra backend --extra ml --extra evaluation --extra dev
npm --prefix apps/web ci
npm --prefix apps/web run build
```

Worktree phát triển hiện tại đã có `.venv-backend`; runtime MLX và cache model
tham chiếu môi trường đang có. Không cần cài lại môi trường cũ. Chuẩn bị model
theo README pipeline và `docs/LLM_FCM_MINUTES.md`. Chuẩn bị trọng số OCR vie+eng:

```bash
.venv-backend/bin/python -m meeting_backend.cli prepare-ocr
.venv-backend/bin/python -m meeting_backend.cli doctor
```

OCR tải một lần từ revision được ghim, các lần inference chạy offline. Lệnh
prepare không cài binary Tesseract. Máy hiện tại có Tesseract 5.5.3; máy mới cần
cài các công cụ trên và bảo đảm `ffprobe`, `soffice`, `pdftoppm`, `tesseract`
có trên PATH. Giao diện đóng gói cả font tiếng Việt, không cần CDN.

### Công cụ xem trước DOCX trên máy macOS

Cài các công cụ cho máy chạy web/worker để sử dụng được từ Terminal:

```bash
brew install poppler
brew install --cask libreoffice
```

Renderer và `doctor` cùng tìm trên PATH, sau đó tìm trong vị trí cài đặt chuẩn
như `/Applications/LibreOffice.app` và `/opt/homebrew/bin`. Không cần môi trường
Codex để render. `doctor` trả cả `documents.preview` và `documents.preview_tools`.
Launcher cảnh báo khi thiếu công cụ; tác vụ tạo Word vẫn có thể hoàn tất mà
không có preview nếu chưa cài chúng.

Nếu tài liệu đã được tạo khi còn thiếu công cụ, khôi phục ảnh xem trước:

```bash
# Liệt kê phiên bản thiếu ảnh, chưa tạo ảnh
.venv-backend/bin/python -m meeting_backend.cli repair-previews
# Tạo ảnh và cập nhật tham chiếu
.venv-backend/bin/python -m meeting_backend.cli repair-previews --apply
```

Lệnh dùng database/data_dir hiện được cấu hình và khóa worker trong lúc sửa.
Chờ tác vụ đang chạy hoàn tất trước khi dùng. Chỉ bổ sung ảnh và metadata preview;
giữ nguyên DOCX, ZIP, facts, ID phiên bản và trạng thái rà soát. Chạy lại sẽ bỏ
qua phiên bản đã có đủ file ảnh. Ảnh phục hồi nằm dưới `data/app/previews/` với
quyền truy cập theo cuộc họp/mẫu tương ứng.

## 2. Khởi động

Chạy tại repository root, hai terminal nhận cùng cấu hình:

```bash
# Terminal A: API + frontend đã build
.venv-backend/bin/python -m meeting_backend.cli serve --port 8010

# Terminal B: xử lý nền
.venv-backend/bin/python -m meeting_backend.cli worker
```

Hoặc dùng `.venv-backend/bin/python scripts/backend/run_local.py` để chạy cả hai.
Mở `http://127.0.0.1:8010`. Lần đầu tự tạo tài khoản quản trị; không có mật khẩu
mặc định. Server/demo cũ ở cổng 8000 độc lập, không được lệnh này khởi động.
Frontend development tùy chọn: `npm --prefix apps/web run dev`; cổng 5173 proxy
`/api` sang 8010.

`configs/backend.yaml` chứa cấu hình không bí mật. Biến `MEETING_APP_*` ghi đè
YAML; path tương đối tính từ repository root. Ví dụ:

```bash
export MEETING_APP_MONGO_DATABASE=meeting_app_my_demo
export MEETING_APP_DATA_DIR=data/my-demo
```

Database phải có prefix `meeting_app_` và gắn đúng thư mục dữ liệu. Không đổi,
reset hoặc drop database của dự án khác. Local HTTP dùng cookie_secure=false;
nếu sau này chạy HTTPS đặt MEETING_APP_COOKIE_SECURE=true.

## 3. Kịch bản trình diễn

1. Admin tạo tài khoản user trong **Quản trị → Tài khoản**.
2. User tải mẫu Word/PDF/scan. Đối chiếu chữ, bảng, đề mục và trường trước khi
   duyệt PDF/ảnh. Muốn sửa chữ: lưu trước, nhận diện lại trường rồi mới duyệt.
3. Tạo hồ sơ giọng nếu có mẫu; có thể chép lời khi chưa có hồ sơ.
4. Tạo cuộc họp: thông tin → 1–8 nguồn → hồ sơ tham gia → mẫu/thể thức.
5. Chạy ASR, rà soát transcript, nghe clip và đổi nhãn người nói khi cần.
6. Tab **Biên bản** chọn chi tiết/tổng quát, LLM/FCM, ND30/HD05 và metadata
   ban hành/ký riêng; tạo biên bản từ transcript đã rà soát.
7. Sửa từng trường hoặc từng mục danh sách, đối chiếu phiên bản nguồn, xem các
   trang DOCX, xác nhận đã rà soát và tải Word để chỉnh tiếp.
8. **Lịch sử** cho xem/đối chiếu/khôi phục; khôi phục tạo phiên bản mới.
9. Admin quản lý job/log/preset/mẫu chung, audit, sao lưu và WER/CER từ tham
   chiếu thật. Không có nhãn người nói chuẩn thì không hiển thị DER giả định.

Trong admin, **Tài khoản** hiển thị mọi tài khoản (gồm tài khoản khóa khi chưa
lọc); **Cuộc họp** hiển thị metadata cuộc họp toàn hệ thống với bộ lọc chủ sở
hữu, trạng thái và thùng rác. Thẻ số liệu ở Tổng quan mở danh sách tương ứng.
Ô tìm kiếm đầu trang admin dẫn tới danh sách cuộc họp toàn hệ thống. Hai danh
sách tự cập nhật; báo lỗi rõ khi API không tải được. Các quyền đọc/chỉnh sửa
file và nội dung trong workspace cá nhân vẫn theo chủ sở hữu.

Đổi thể thức dùng facts đang lưu, không chạy ASR/LLM. Tạo lại nội dung giữ các
trường sửa tay hợp lệ còn cùng ID. Đổi nguồn/hồ sơ tham gia yêu cầu chạy lại
âm thanh; sửa transcript đánh dấu biên bản cũ stale. Không fine-tune ở đợt này.

## 4. Nhập kết quả cũ

Sau khi có tài khoản nhận dữ liệu, chạy dry-run trước:

```bash
.venv-backend/bin/python -m meeting_backend.cli import-run /duong/dan/run --username ten_admin --dry-run
.venv-backend/bin/python -m meeting_backend.cli import-run /duong/dan/run --username ten_admin

.venv-backend/bin/python -m meeting_backend.cli import-legacy /duong/dan/data/meetings --username ten_admin --sqlite /duong/dan/app.sqlite --dry-run
.venv-backend/bin/python -m meeting_backend.cli import-legacy /duong/dan/data/meetings --username ten_admin --sqlite /duong/dan/app.sqlite
```

Importer kiểm timeline/DOCX/ZIP, so SHA-256 các file sau copy, không ghi nguồn.
Cùng nội dung và owner chạy lại trả về cùng ID; fingerprint khác tạo bản nhập
mới. SQLite mở chỉ đọc để lấy tên/ID/trạng thái run. Không phát lại tài khoản
hoặc queue cũ. Registry giọng tạo lại từ mẫu qua web để có ownership rõ ràng.
Export cũ không kèm audio vẫn xem được bằng chứng chữ; UI báo khi thiếu clip.

## 5. Sao lưu và tra lỗi

**Quản trị → Sao lưu dữ liệu** đóng metadata, file được tham chiếu, run sidecar
và voice registry vào ZIP có checksum. Không gồm weights, log, sessions hoặc
queue cũ. File lớn được stream để hạn chế RAM.

Khôi phục luôn tạo `meeting_app_restore_<id>` và root mới. Kết quả cung cấp
hai biến database/data_dir; dừng API/worker, đổi cả hai rồi khởi động lại và
đăng nhập bằng tài khoản trong backup. DB hiện tại không bị ghi đè. Đường dẫn
trong JSON sidecar được đổi sau kiểm checksum để có thể tiếp tục sửa DOCX.

- Request: `data/app/logs/api.log`, tra bằng X-Request-ID.
- Job: `data/app/logs/jobs/<job-id>/worker.log`, hoặc trang admin job.
- 409 revision: tải bản mới trước khi gửi lại, không lưu đè tab khác.
- Hủy đang inference: đợi checkpoint; giao diện không mô phỏng phần trăm.
- Worker bị kill: khi lease hết hạn, worker mới đánh dấu interrupted hoặc
  khôi phục trạng thái đã publish. Thử lại từ UI.

```bash
PYTHONPATH=src .venv-backend/bin/python -m pytest tests/unit tests/integration tests/backend -q
.venv-backend/bin/python -m ruff check --no-cache src/meeting_backend tests/backend
npm --prefix apps/web run build
npm --prefix apps/web run format:check
```

Smoke trình duyệt chỉ đọc, dùng tài khoản thử nghiệm và Chrome đã cài:

```bash
MEETING_QA_PASSWORD='<mat-khau-kiem-thu>' .venv-backend/bin/python scripts/backend/browser_smoke.py --username ten_kiem_thu
```

Có thể dùng `--credentials-file` JSON cục bộ thay env, và `--meeting-id` để
kiểm thêm trang biên bản. Không commit file credential. Ảnh/report nằm trong
`data/evaluations/web_browser_smoke` mặc định.

Thêm `--template-id <id>` để kiểm bản xem trước mẫu. Với `--meeting-id` hoặc
`--template-id`, smoke yêu cầu có ảnh DOCX, kiểm tra ảnh đã giải mã được và
chuyển qua toàn bộ trang; không coi trang rỗng hoặc “Chưa có bản xem trước” là đạt.

Thêm `--check-motion` để kiểm chuyển động, polling giữ focus, chuyển bước,
logo, hộp thoại và chế độ giảm chuyển động trên desktop/mobile. Với biên bản
có ít nhất hai trang, kiểm thêm preview tải chậm và thử lại ảnh lỗi. Xem
[chi tiết triển khai và kết quả](UI_MOTION_2026-10-18.md).

Backend tests dùng MongoDB thật với database UUID riêng tự dọn. Test tài liệu
cần các binary và OCR cache. Không chạy test vào database đang trình diễn.
