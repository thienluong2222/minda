# Rà soát Minda trước đợt chỉnh sửa giao diện — 26/10/2026

## Kết luận

Bản web Minda hiện có nền tảng đủ để bắt đầu chỉnh sửa giao diện. Build, kiểm tra định dạng, lint backend và các kiểm thử đã chạy đều đạt sau khi chạy lại một kiểm thử phụ thuộc Quick Look ngoài sandbox. Kiểm tra trình duyệt chưa phát hiện lỗi JavaScript hoặc tràn ngang trang trong các trường hợp đã thử.

Nên ưu tiên khả năng đọc, điều hướng thu gọn, bảo vệ nội dung chưa lưu và bố trí màn hình biên bản. Chưa có thay đổi mã ứng dụng trong đợt rà soát này. Báo cáo là cơ sở chuẩn bị thiết kế, không phải nghiệm thu toàn bộ chất lượng suy luận hoặc mọi tình huống nghiệp vụ.

## 1. Xác định đúng bản cần sửa

- Worktree web: `/Users/thien/Documents/School/Luận văn/web_app`.
- Nhánh: `codex/web-mongodb-upgrade`; HEAD: `27c67aa` (`feat: add subtle accessible motion to Minda web`). Worktree sạch trước khi thêm báo cáo này.
- Frontend: `apps/web`, React 19, TypeScript, Vite, React Router, TanStack Query, Tailwind 4 và Radix.
- Backend: `src/meeting_backend`, FastAPI, MongoDB và worker riêng.
- Bản `src/meeting_pipeline/web` ở checkout gốc là demo cũ, không phải giao diện Minda cần sửa.
- Font Geist, icon và tài nguyên giao diện được đóng gói local.

Luồng cần tiếp tục hỗ trợ: mẫu tài liệu → cuộc họp/audio → transcript/người nói → biên bản → sửa/đối chiếu/xem trước → tải DOCX; bên cạnh đó là quản trị tài khoản, tác vụ, cấu hình, mẫu chung, backup và nhật ký.

## 2. Bằng chứng kiểm tra mới

| Kiểm tra | Kết quả | Phạm vi kết luận |
| --- | --- | --- |
| `npm run build` | Đạt | TypeScript và build production |
| `npm run format:check` | Đạt | Prettier cho frontend và cấu hình |
| Ruff `src/meeting_backend tests/backend` | Đạt | Lint backend mới và kiểm thử API |
| `pytest tests/backend -xq --tb=short` | **23 đạt** | MongoDB thật, database UUID và artifact root riêng theo fixture |
| `pytest tests/unit tests/integration -q --tb=short` | 256 đạt, 1 lỗi môi trường | Quick Look bị sandbox chặn, không tạo PNG |
| Chạy lại riêng `test_visual_qa_rendering` ngoài sandbox | **1 đạt** | Tổng cộng 257 ca unit/integration khác nhau đã đạt qua hai lượt; không tuyên bố toàn bộ suite đạt trong cùng một lượt |
| Browser smoke có `--check-motion` | **15 route đạt** | Đăng nhập, user/admin, thư viện mẫu, preview, modal, focus và reduced motion |
| 6 màn hình × 5 viewport | **30 trường hợp không tràn ngang trang** | 1440×1000, 1280×800, 1024×768, 768×1024, 390×844 |
| Lưu bản nháp qua wizard thật | **HTTP 201** | Các trường `preferred_template_id`, `preferred_format`, `preferred_mode` được API chấp nhận và lưu |
| Người dùng thường vào admin | Đạt | UI đưa về dashboard; API danh sách tài khoản trả 403 |
| Lỗi JavaScript ở các lượt browser | **0** | Không tương đương kiểm tra đầy đủ accessibility hoặc hiệu năng |

Browser chạy với dữ liệu giả trong database ngẫu nhiên `meeting_app_ui_review_<UUID>` và data root tạm; không đọc/sửa dữ liệu cuộc họp thật. API tạm dùng cổng 18010, không chạy worker hay model. Server đã dừng, database kiểm thử đã xóa và file credential tạm đã gỡ.

Hai trang preview là ảnh fixture ghi rõ “DỮ LIỆU KIỂM THỬ GIAO DIỆN”: lượt browser xác minh tải/giải mã ảnh, chuyển trang, giữ khung, lỗi/thử lại; không dùng chúng để kết luận chất lượng dựng DOCX. Các ca backend tài liệu là kiểm thử riêng.

Không chạy lại ASR/LLM/FCM end-to-end, không benchmark chất lượng lời văn, không kiểm trên Safari/Firefox hoặc thiết bị di động thật.

Bằng chứng máy đọc:

- [Browser smoke](../../artifacts/ui-review-2026-10-26/smoke/report.json)
- [Viewport, accessibility và thao tác wizard](../../artifacts/ui-review-2026-10-26/review.json)

## 3. Những điểm cần xử lý khi sửa giao diện

### A. Vấn đề đã tái hiện

**A1 — Menu thu gọn mất tên truy cập và ẩn đăng xuất. Ưu tiên cao trong đợt UI.**

Ở viewport 1024 px, chữ của menu bị `display: none`, trong khi `NavLink` không có `aria-label` hoặc tooltip. Accessibility snapshot chỉ còn các `link` không có tên. Nút đăng xuất cũng bị ẩn ở breakpoint thu gọn. Người dùng cần biết tên mục và vẫn truy cập được thao tác tài khoản khi cửa sổ hẹp.

Vị trí: `apps/web/src/app.tsx:237`, `apps/web/src/styles.css:2097`. Đề xuất: thêm tên truy cập cho link độc lập với chữ hiển thị, tooltip cho icon và đường truy cập tài khoản/đăng xuất ở mọi kích thước.

**A2 — Rời wizard làm mất nội dung chưa lưu. Ưu tiên cao trong đợt UI.**

Nhập tên ở `/meetings/new`, chuyển sang danh sách cuộc họp rồi quay lại: ô tên trở về rỗng, không có bước cảnh báo. Các giá trị chỉ nằm trong state của component. Đây là rủi ro mất công nhập trước khi lưu, không phải dữ liệu đã lưu bị xóa.

Vị trí: `apps/web/src/features/meetings/pages.tsx:394`. Đề xuất: có trạng thái chưa lưu và cảnh báo khi rời; có thể lưu nháp metadata khi phù hợp. File audio đã chọn cần thông báo rõ nếu phải chọn lại.

**A3 — Tab workspace chỉ biểu thị lựa chọn bằng CSS. Ưu tiên vừa.**

Accessibility snapshot liệt kê năm nút nhưng không cho biết tab đang được chọn. Mã hiện dùng `className="active"`, chưa có ngữ nghĩa tab/selected tương ứng.

Vị trí: `apps/web/src/features/meetings/workspace.tsx:617`. Đề xuất: dùng bộ Tabs có quản lý focus/bàn phím và `aria-selected`, hoặc mô hình điều hướng bằng link với trạng thái hiện tại phù hợp.

### B. Giới hạn và điểm cải thiện đã xác định từ mã/ảnh

| Điểm | Tác động | Hướng xử lý |
| --- | --- | --- |
| Chữ phụ, trạng thái và toolbar có nhiều cỡ 9–12 px; toolbar biên bản có cỡ 10 px | Cần đọc nhiều nội dung nhỏ, nhất là lúc đối chiếu tài liệu trên laptop | Tăng chữ nội dung và điều khiển quan trọng; kiểm lại màu chữ phụ trên nền thực tế |
| Token `:root` ở cả `index.css` và `styles.css`, nhiều màu/khoảng cách viết trực tiếp | Thay bảng màu hoặc bo góc dễ thiếu chỗ và phát sinh ghi đè CSS | Gom token màu, chữ, khoảng cách, radius và trạng thái; đổi theo lớp dùng chung trước |
| `styles.css` dài 2.731 dòng; `admin/pages.tsx` 1.158 dòng | Phạm vi ảnh hưởng khó theo dõi khi đổi layout hoặc bảng | Tách dần theo layout, thành phần và tính năng trong quá trình sửa; tránh viết lại toàn bộ cùng lúc |
| Biên bản chia hai cột cố định, facts có vùng cuộn riêng; bằng chứng/sửa mở modal | Chuyển qua lại nhiều khi rà soát dài; preview không có điều khiển zoom trong khung | Ưu tiên không gian đọc, cho thu gọn/điều chỉnh panel, mở căn cứ cạnh nội dung; giữ phương án mở trang đầy đủ |
| Bộ lọc trạng thái cuộc họp chỉ lọc 30 mục ở trang hiện tại | Có thể không thấy kết quả phù hợp ở trang khác; tổng số vẫn là tổng trước lọc | Nếu muốn lọc toàn danh sách, cần thêm filter ở API trước phân trang, đồng bộ total và URL; hiện UI đã ghi rõ giới hạn này |
| Màn hình người dùng có các lựa chọn “E5 + Fuzzy C-Means”, số cụm, field ID | Tăng gánh nặng hiểu thuật toán khi người dùng chỉ cần hoàn thiện biên bản | Dùng ngôn ngữ nghiệp vụ; đưa tham số sâu vào phần nâng cao hoặc quản trị theo phạm vi được chốt |
| API có `error.fields`, client chỉ chuyển code/message/request ID thành `ApiError` | Lỗi validation không được gắn trực tiếp vào trường nhập | Giữ thông tin lỗi từng trường và hiển thị cạnh ô nhập; vẫn có thông báo tổng quát |

Các điểm ở phần B là đề xuất cho đợt thiết kế hoặc giới hạn hiện có, không phải tất cả đều là lỗi chức năng.

## 4. Bản đồ file để bắt đầu sửa

| Phần cần sửa | File chính |
| --- | --- |
| Đăng nhập, sidebar, topbar, thông báo, route và phân vùng admin | `apps/web/src/app.tsx` |
| Token và Tailwind | `apps/web/src/index.css` |
| Layout, typography, bảng, panel, responsive | `apps/web/src/styles.css` |
| Chuyển động và reduced motion | `apps/web/src/motion.css` |
| Header, panel, loading/error/empty, modal, preview, action | `apps/web/src/components/common.tsx`, `components/ui/` |
| Dashboard, danh sách, wizard, thiết lập | `apps/web/src/features/meetings/pages.tsx` |
| Khung cuộc họp, tổng quan, tiến độ, lịch sử | `apps/web/src/features/meetings/workspace.tsx` |
| Transcript và người nói | `apps/web/src/features/meetings/transcript.tsx` |
| Biên bản, facts, căn cứ, cấu hình và preview | `apps/web/src/features/meetings/minutes.tsx` |
| Mẫu tài liệu và hồ sơ giọng | `apps/web/src/features/templates/pages.tsx` |
| Quản trị | `apps/web/src/features/admin/pages.tsx`, `features/admin/meetings.tsx` |
| Client API và kiểu dữ liệu | `apps/web/src/lib/api.ts`, `lib/types.ts` |

## 5. Thứ tự triển khai đề xuất

1. Chốt màn hình tham chiếu và mục tiêu của đợt đổi giao diện; dùng dashboard, wizard, transcript và biên bản làm bốn màn hình chuẩn.
2. Chuẩn hóa token, chữ, nút, input, trạng thái và shell. Sửa nhãn menu thu gọn, đường đăng xuất, focus và trạng thái tab trong bước này.
3. Hoàn thiện luồng người dùng: danh sách/tìm kiếm → wizard có bảo vệ nội dung chưa lưu → workspace. Chốt riêng việc mở rộng bộ lọc toàn danh sách vì có thay đổi API.
4. Ưu tiên màn hình biên bản: phân cấp hành động, vùng đọc/chỉnh sửa, bằng chứng, preview và trạng thái stale/đã lưu/đang xử lý.
5. Áp dụng thành phần đã ổn định sang mẫu, hồ sơ giọng và admin; chạy lại build, kiểm tra trình duyệt và kiểm thử API liên quan.

Khi đổi UI cần tiếp tục thể hiện đúng quyền owner/admin, revision/conflict, stale, active job, trạng thái OCR cần duyệt, đoạn nói chồng chưa có transcript và nguồn căn cứ của từng trường. Tiến độ cần phản ánh dữ liệu backend thực tế. Bản mobile vẫn là phạm vi phát triển sau theo context trước; lượt rà soát này chỉ kiểm độ thích ứng cơ bản của web.

## 6. Ảnh hiện trạng để đối chiếu

Toàn bộ ảnh dùng dữ liệu giả, lưu tại `artifacts/ui-review-2026-10-26/`.

- [Dashboard 1440 px](../../artifacts/ui-review-2026-10-26/1440-dashboard.png)
- [Biên bản 1280 px](../../artifacts/ui-review-2026-10-26/1280-minutes.png)
- [Wizard 1024 px — menu thu gọn](../../artifacts/ui-review-2026-10-26/1024-wizard.png)
- [Transcript 390 px](../../artifacts/ui-review-2026-10-26/390-transcript.png)
- [Modal biên bản trên mobile](../../artifacts/ui-review-2026-10-26/smoke/mobile-dialog.png)

Build đã tạo lại `apps/web/dist/` theo mã hiện tại; ảnh và JSON thuộc thư mục artifact đã được Git ignore. Báo cáo này là file mới duy nhất ngoài artifact trong worktree web. Các thay đổi có sẵn ở checkout gốc được giữ nguyên; không tạo commit trong đợt rà soát.
