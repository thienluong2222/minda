# Frontend Minda đã triển khai — 27/10/2026

Đã triển khai trực tiếp trong `apps/web`, build ra `apps/web/dist`. Giữ bảng màu trắng, xám, nút đen và xanh nhẹ; không thêm Three.js, WebGL hoặc thư viện mới. Các thay đổi bước 1–3 có sẵn trong thư mục làm việc được giữ lại.

Cập nhật sau khi thử audio thật: đã sửa lỗi sai số mili giây làm vùng chọn vượt số mẫu giải mã, đồng thời làm rõ thông báo từng lần xử lý. Xem [bản sửa và hướng dẫn áp dụng](TIMELINE_AUDIO_RANGE_FIX_2026-10-27.md).

## Các màn hình và thao tác mới

| Phần | Hành vi đã có |
| --- | --- |
| Khung ứng dụng | Điều hướng theo Công việc / Tài nguyên / Cá nhân; khu quản trị riêng. Menu điện thoại có giữ focus, đóng bằng Escape và trả focus. Bỏ footer, thông tin phiên bản và mô tả lặp trong vùng làm việc. |
| Tổng quan | Số liệu có liên kết tới danh sách tương ứng; công việc cần tiếp tục và cuộc họp gần đây. Không chiếm cột làm việc bằng lời giới thiệu quy trình. |
| Danh sách | Tìm và lọc trạng thái trước khi phân trang ở API, giữ bộ lọc trên URL. Có bộ lọc cần rà biên bản; kiểm tra cả trường hợp phiên bản đã duyệt không còn là bản hiện tại. |
| Tạo cuộc họp | Lưu nháp thông tin trong phiên trình duyệt theo tài khoản. Chọn nhiều nguồn riêng hoặc các phần nối tiếp của cùng nguồn. Giữ thứ tự file được chọn. File cần chọn lại sau khi tải lại trang. |
| Không gian cuộc họp | Nguồn âm thanh → Lời chép → Biên bản → Lịch sử; thông tin cuộc họp mở riêng. Ngày chỉ có ngày không bị thêm giờ giả. |
| Timeline | Kho file chưa xếp, mỗi nguồn một hàng, kéo đổi thứ tự/chuyển hàng/đặt thời điểm. Có nút và biểu mẫu thay thế cho kéo thả. Tạo, đổi tên, đổi thứ tự, bỏ nguồn; sửa vùng audio dùng, mốc và khoảng cách. |
| Khoảng gián đoạn | Phiên họp, giải lao, phần ngoài biên bản và giờ thực được khai báo riêng. Khoảng nghỉ chưa biết giữ `null`; thứ tự không bị đổi thành mốc thời gian đã xác nhận. |
| Lời chép | Tìm trên toàn bộ lời chép, lọc người nói/đoạn cần rà; trình bày 50 đoạn mỗi trang. Giữ nhãn thời gian cục bộ, ước lượng và đoạn ngoài biên bản. Đổi tên người nói/sửa lời chép vẫn tạo phiên bản theo API hiện có. |
| Biên bản | Mặc định đọc nội dung; sửa ngay tại mục. Căn cứ mở bên cạnh, thay đổi độ rộng bằng kéo hoặc bàn phím; màn hình hẹp mở căn cứ trong hộp riêng. Có chế độ xem trước Word, thu phóng, tải Word và gói căn cứ. |
| Nghe đối chiếu | Một trình nghe chung trong cuộc họp; khi nghe trong hộp rà soát, điều khiển nằm ngay trong hộp và dừng khi đóng. Vùng nghe từ file gốc tuân theo điểm vào/ra của đoạn. |
| Trạng thái | Bảo vệ nội dung đang sửa khi đổi phần, đổi bộ lọc hoặc rời trang. Giữ nội dung nhập khi có xung đột phiên bản; không lưu đè bằng revision mới. Hiện bản cũ, lỗi và thiếu mốc tại vị trí liên quan. |

Các nguồn đã căn thời gian có thể mở kết quả ánh xạ để phân biệt mốc do người dùng đặt, mốc khớp âm thanh, ước lượng và phần chưa có đồng hồ chung. Chỉ đọc báo cáo căn phù hợp với bố cục hiện tại.

## Phần backend hỗ trợ giao diện trong lần này

- Danh sách cuộc họp nhận bộ lọc trạng thái và áp dụng trước phân trang; phạm vi sở hữu và thùng rác vẫn được kiểm tra.
- API khả năng hệ thống trả giới hạn số file, số đoạn và thời lượng để frontend dùng cùng cấu hình backend.
- Không thay thuật toán hoặc tăng giới hạn thời lượng trong lần nâng cấp giao diện.

## Đã kiểm tra

- Build production: `tsc --noEmit && vite build` thành công.
- Prettier trên các file frontend thay đổi và Ruff trên các file backend/test thay đổi: đạt.
- **42/42 kiểm thử API đạt** với MongoDB thật, mỗi test dùng database và kho artifact riêng. Có kiểm tra mới cho lọc trước phân trang, quyền sở hữu, trạng thái cần rà và giới hạn frontend/backend.
- Kiểm tra trình duyệt bằng dữ liệu giả ở 1280 px, 1024 px và 390 px. Danh sách, nguồn và biên bản không làm tràn ngang toàn trang; bảng và timeline có vùng cuộn riêng. Các trang được đo có một H1.
- Tải hai WAV qua trình chọn file, lưu cùng một nguồn, đặt mốc, kéo phần thứ hai lên trước và tạo nguồn khác: dữ liệu tải lại từ API đúng thứ tự đã thao tác.
- Đối chiếu mã băm: audio gốc sau kéo thả giữ nguyên. Khoảng nghỉ và điểm bắt đầu chưa xác định vẫn là `null`.
- Sửa nháp biên bản rồi chuyển phần: xuất hiện xác nhận; chọn tiếp tục sửa giữ được nội dung. Trình nghe nằm trong hộp rà lời chép và đóng cùng hộp.
- Điều chỉnh cột bằng phím phải: độ rộng đổi từ 62 lên 67. Xem trước Word tải được ảnh 1082 × 1400 được render từ DOCX kiểm thử bằng LibreOffice/Poppler.
- Đặt lời chép kiểm thử vào trạng thái thiếu mốc: nút tạo biên bản bị vô hiệu và hiện hướng dẫn rà nguồn. Đã khôi phục trạng thái bộ dữ liệu kiểm thử sau kiểm tra.
- Không có cảnh báo/lỗi trong console trình duyệt ở lượt kiểm tra cuối.

Bằng chứng máy đọc được nằm trong `data/evaluations/frontend-implementation-20261027/`: `backend-tests.xml`, `responsive-review.json`, `browser-roundtrip.json`, `validation_summary.json`. `source_before.json` ghi mã băm trước sửa để phân biệt phần frontend lần này với thay đổi pipeline có sẵn.

## Ảnh giao diện

Ảnh dùng cuộc họp, lời chép và biên bản **giả lập để kiểm tra UI**. Đây không phải kết quả đánh giá chất lượng ASR/LLM hay nghiệm thu cuộc họp dài.

- [Timeline nhiều nguồn](../../artifacts/frontend-2026-10-27/timeline-desktop.png)
- [Biên bản và căn cứ trên máy tính](../../artifacts/frontend-2026-10-27/minutes-desktop.png)
- [Biên bản trên điện thoại](../../artifacts/frontend-2026-10-27/minutes-mobile.png)
- [Căn cứ trên điện thoại](../../artifacts/frontend-2026-10-27/evidence-mobile.png)
- [Nghe trong hộp rà lời chép](../../artifacts/frontend-2026-10-27/transcript-review-desktop.png)

## Cách mở bản mới

Frontend đã build. Với cấu hình hiện có, chạy từ thư mục `web_app`:

```bash
.venv-backend/bin/python scripts/backend/run_local.py
```

Mở `http://127.0.0.1:8010`; nếu ứng dụng đang chạy, tải lại trang để nhận giao diện mới. Hướng dẫn môi trường đầy đủ: [QUICKSTART](../backend/QUICKSTART.md). Không sử dụng địa chỉ và tài khoản trong môi trường kiểm thử để vận hành hệ thống thật.

## Phạm vi còn lại

Giới hạn hiện tại vẫn là **20 phút mỗi file và mỗi đồng hồ xử lý** theo cấu hình pipeline. Frontend đã chuẩn bị việc nhiều phần ghi và khoảng gián đoạn; xử lý bản ghi 30/60/120 phút, tiếp tục sau ngắt và giữ diễn biến đề xuất–thay đổi–kết luận vẫn thuộc bước 4–5. Bước 6 cần nghiệm thu toàn luồng trên audio họp thực tế. Lượt này không chạy lại suy luận ASR/LLM hay đo bộ nhớ của cuộc họp dài.

Chỉnh sửa nội dung biên bản vẫn dùng tác vụ nền để cập nhật Word; cần worker hoạt động theo quy trình hiện có. Giao diện mới giữ nguyên các cơ chế phiên bản, phân quyền và xuất tài liệu của backend.
