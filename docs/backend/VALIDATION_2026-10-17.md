# Nghiệm thu prototype web — 17/10/2026

## Phạm vi và mốc mã

- Worktree/nhánh: `codex/web-mongodb-upgrade`.
- Nền sửa lỗi: `02679bf`; backend/MongoDB/OCR: `c2ddc28`; giao diện: `23f8172`.
- Checkout gốc giữ HEAD `e033939b60a5507ffe9bd2b7b4675cd78f0a58d5`, không
  thay đổi tracked files. File kế hoạch untracked có sẵn được giữ nguyên.
- Mobile, deploy rộng và fine-tuning nằm ngoài đợt triển khai đã chọn.

## Kết quả tự động

| Hạng mục | Kết quả | Phạm vi |
| --- | --- | --- |
| Pytest tổng | **274 passed**, 3 deprecation warnings, 65.53 giây | tests/unit, integration, backend |
| Backend mới | 20 trường hợp trong bộ trên | MongoDB thật, UUID database/root riêng |
| Ruff | Đạt | meeting_backend, tests/backend, scripts/backend |
| TypeScript + Vite | Đạt | strict, noUnusedLocals, noUnusedParameters, production build |
| Prettier | Đạt | Frontend source và cấu hình |
| npm audit | 0 lỗ hổng được công cụ báo tại lần kiểm tra | Lockfile sau loại CLI khỏi dependency ứng dụng |
| API import | 50 OpenAPI paths; không nạp torch/mlx/transformers | Kiểm tra tiến trình import riêng |

Backend tests kiểm tra session/expiry/CSRF, vai trò và ownership, revision/busy,
upload sai không công bố nguồn, bằng chứng/quyền mẫu shared, sửa transcript và
stale, cancel/retry/recovery, fencing khi token lease thay đổi, backup/restore,
ZIP traversal, import dry-run/idempotency/hash/cleanup và các đầu vào tài liệu.
Manifest/ZIP của các lần xuất mới có meeting/job/transcript version ID thật;
đã chạy job đổi thể thức để đối chiếu các ID và giữ nguyên facts.

Ba warning là deprecation của FastAPI/Starlette TestClient và Silero VAD;
không phải bài kiểm thử bị bỏ qua hoặc model được giả lập trong smoke bên dưới.

## Kiểm tra model thực

### Audio và hồ sơ giọng

- Hai câu VIVOS ghép với khoảng lặng, **11.1875 giây**, một nguồn, 10 từ tham chiếu.
- API upload → queue → worker → pipeline thật → phiên bản transcript/artifact.
- Hai đoạn: “trở nên thụ động” và “cũng khiến cho họ dè dặt”.
- **WER = 0, CER = 0**, S/D/I đều 0 trên mẫu ngắn này; có clip bằng chứng.
- Tạo hồ sơ giọng từ mẫu qua worker thành công. Toàn smoke audio + voice khoảng
  47.97 giây trên máy phát triển, không dùng để suy ra tốc độ/độ chính xác chung.
- Nhãn cụm người lạ có ID; “chưa xác định” và “nói chồng” là trạng thái riêng.

### Biên bản LLM/FCM

- Transcript demo hiện có được sao chép, không ghi nguồn.
- Qwen3-4B-Instruct-2507 4-bit qua MLX, E5 multilingual-small và Fuzzy C-Means
  chạy thật bằng cache đã ghim revision.
- Kết quả: **37 facts, 4 cụm, 8 lần gọi model, 3 trang preview DOCX**.
- Đã chạy tổng quát + HD05 hai mặt; chi tiết rule-only và đổi sang ND30 cũng
  thành công. Đổi thể thức không gọi lại ASR/LLM.
- Sửa một trường giữ evidence của các trường và cập nhật DOCX/manifest/ZIP.
  Tạo lại giữ trường sửa tay còn hợp lệ cùng ID.
- Warning/ý bị giữ nguyên được lưu trong model_report; có preview và cơ chế
  rà soát, không khẳng định LLM luôn sửa đúng hoặc không thể thêm sai thông tin.

## Word, PDF, scan và OCR

Đã kiểm qua API/worker thật cho DOCX, DOC nhị phân, PDF có chữ, PDF scan và PNG.
Các bài chuyển đổi dùng LibreOffice/Poppler; OCR dùng Tesseract 5.5.3 vie+eng
và OpenCV phát hiện bảng kẻ. Mẫu kiểm thử scan có chữ tiếng Việt và bảng kẻ.

- Kết quả là Word chứa paragraph/table chỉnh sửa được, có preview.
- PDF/ảnh ban đầu luôn needs_review; phải duyệt mới được chọn để tạo biên bản.
- Lưu chữ sửa xong nhận diện lại trường rồi mới xác nhận duyệt.
- Đã tải ảnh của mẫu demo qua trình duyệt, mở màn hình đối chiếu và duyệt thành công.

**Giới hạn:** đây là kiểm tra chức năng trên mẫu rõ, chưa phải benchmark OCR.
Không hứa khôi phục tuyệt đối font, bảng gộp phức tạp, nhiều cột hoặc scan mờ/
chữ viết tay. PDF văn bản được dựng theo dòng chữ; bảng kẻ scan có tái dựng
cell. Tối đa 50 trang PDF, ảnh tối đa 40 megapixel. Điểm Tesseract là điểm nội
bộ engine, không phải xác suất đúng của trường. Bản gốc luôn giữ để đối chiếu.

## Kiểm tra Chrome

Smoke có thể chạy lại bằng `scripts/backend/browser_smoke.py` trên tài khoản
thử nghiệm; nhận mật khẩu từ env hoặc file JSON cục bộ và không ghi vào báo cáo.

- **13 trang** user/admin, desktop **1440×1000**, mobile **390×844**.
- Không phát hiện pageerror JavaScript hoặc tràn ngang viewport mobile trong smoke.
- Đã thao tác tạo/sửa nháp, sửa fact → worker/render → tải DOCX và đọc bằng
  python-docx, mở evidence, sửa transcript → stale.
- Tạo tài khoản trên UI; tài khoản user bị chặn API admin (403), không xem được
  cuộc họp người khác (404); route admin chuyển về trang user.
- Tạo backup qua UI, tải scan/duyệt mẫu, xem đối chiếu transcript và preview
  biên bản phiên bản cũ.

Ảnh/báo cáo cục bộ ở `data/app-qa/browser-qa/` và `data/app-qa/browser-final/`.
Các log chi tiết trong `/private/tmp/meeting-*-qa.log` là evidence phiên kiểm
tra trên máy này, không phải dữ liệu người dùng cần để chạy ứng dụng.

## Khôi phục dữ liệu thực tế

Backup của database QA (gồm run demo, audio, voice và phiên bản tài liệu) đã
được khôi phục sang database `meeting_app_restore_<id>`/root mới. Đã:

1. Đăng nhập bằng tài khoản được khôi phục, không tái sử dụng session cũ.
2. Kiểm tra SHA-256 tất cả artifact trong database khôi phục.
3. Đổi thể thức và tạo DOCX mới từ bản khôi phục thành công.
4. Xác nhận database nguồn còn nguyên. Database restore thử nghiệm được dọn.

Snapshot dùng các phiên bản bất biến và tham chiếu đang có; không tuyên bố
transaction phân tán database/filesystem. Khi bị kill có thể còn ứng viên hoặc
file staging chưa active. Prototype xử lý một job nặng mỗi data root; hủy chạy
model đợi checkpoint. Chưa có benchmark nhiều người dùng đồng thời.

## Bàn giao chạy local

Cấu hình dùng thật mặc định: `meeting_app_dev` + `data/app`, tách khỏi
`meeting_app_qa_20261017` + `data/app-qa`. Bản sạch hiển thị bước tạo admin đầu
tiên; không đưa mật khẩu QA hoặc tài khoản mẫu vào cấu hình phát hành.
Server cũ ở cổng 8000 được giữ tắt. Xem `QUICKSTART.md` để chạy, nhập dữ liệu
cũ và thực hiện kịch bản trình diễn.
