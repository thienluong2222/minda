# Kiểm chứng cập nhật thể thức DOCX ngày 15 tháng 10 năm 2026

## Kết quả

Đã tích hợp hai thể thức Nghị định 30/2020/NĐ-CP và Hướng dẫn 05-HD/VPTW
ngày 27/5/2026 vào pipeline DOC/DOCX, API và demo. Chọn thể thức độc lập với
biên bản chi tiết/tổng quát. Có nút đổi thể thức bằng nội dung đã lưu, không
gọi mô hình. Hướng dẫn sử dụng: [DOCX_FORMAT_STANDARDS.md](../DOCX_FORMAT_STANDARDS.md).

## Kiểm thử tự động

- `pytest tests/unit tests/integration -q`: **246 passed**, ba cảnh báo
  dependency/deprecation có sẵn, 32,64 giây ở lần chạy cuối.
- 8 tổ hợp DOC/DOCX × chi tiết/tổng quát × hai thể thức: dùng mẫu thật,
  pipeline parse/map/fill và formatter thật; nội dung xác định để tách kiểm
  chứng định dạng khỏi sai số suy luận LLM. Không gọi lại LLM trong ma trận này.
- Kiểm tra câu phủ định, số liệu và tên/thứ tự đề mục sau định dạng.
- Kiểm tra bảng gộp ô, section ngang, ZIP part không liên quan, định dạng lại
  không nhân đôi PAGE, khối ký và phần xác nhận chữ ký.
- Trường trống/thiếu ký hiệu cơ quan, ghi chú lẫn trong phần đầu, nội dung
  footer chứa PAGE và danh sách nơi nhận nhập mới có ca hồi quy riêng.
- API kiểm tra upload lựa chọn, JSON metadata sai, enum sai, đổi thể thức,
  tải DOCX/ZIP, giữ fact/configuration và hoàn nguyên khi định dạng lỗi.
- Ruff check/format các file Python thay đổi: đạt; `node --check` demo.js: đạt.
- Mypy 5 module format_profiles/document_formatting/converter/visual_qa/service
  với `--follow-imports=silent`: đạt. Không suy rộng thành toàn repo đã đạt mypy.

Các ca Quick Look/Word cần dịch vụ macOS ngoài sandbox. Lần chạy trong sandbox
gặp lỗi Quick Look và fork của runtime; lần chạy ngoài sandbox đạt đầy đủ.

## Kiểm tra trực quan trên dữ liệu hiện có

Nguồn: `data/evaluations/llm_fcm_20261010_release/asr_fcm/exports/completed.docx`.
Đây là biên bản từ transcript ASR hiện có, không phải dữ liệu được người kiểm
sửa và không phải phép đo chất lượng LLM mới.

Hai bản sao trong `data/evaluations/docx_format_20261015/`:

- `nd30_2020/completed.docx`: 3 trang.
- `hd05_2026/completed.docx`: 3 trang, bật lề in hai mặt.
- Mỗi thư mục có báo cáo và `preview/page-N.png`, PDF dùng nội bộ để render.

Đã render bằng `render_docx.py` của skill Documents và xem đủ 6 trang:

- Quốc hiệu/tiêu đề Đảng, đường kẻ, tên biên bản và trích yếu có bố cục rõ.
- Ẩn số trang đầu; trang sau có số 2, 3. Lề trang chẵn của bản Đảng đổi bên.
- Khối ký người ghi/thư ký ở trái, chủ trì/chủ tọa ở phải; Minh/Lan lấy từ
  dữ kiện hỗ trợ trong run, không tạo chữ ký hoặc con dấu.
- Các kiểm tra nội dung được bảo vệ đều đạt; hash nguồn giữ nguyên.

Bản render đầu phát hiện đường kẻ tạo bằng thụt lề ngay trên đoạn tiêu đề
làm chữ xuống dòng. Đã sửa bằng đoạn đường kẻ riêng và render lại toàn bộ.
Dòng chấm dài chuyển thành Word tab leader để nhãn không bị tách vô lý.

Nguồn chưa có cơ quan, số văn bản, ngày ban hành/thẩm quyền ký Đảng và nơi nhận
đầy đủ, nên báo cáo vẫn yêu cầu rà soát. Các lỗi ASR/biên tập đã có trong nội
dung nguồn được giữ để đánh giá riêng; kiểm chứng này tập trung vào trình bày.

## Demo đang dùng

Đã tạo bản sao run riêng, không viết lại source/run cũ:

- Run: `data/evaluations/docx_format_20261015/demo_run`.
- Job: `docx-format-demo-20261015`.
- URL: `http://127.0.0.1:8000/runs/docx-format-demo-20261015#minutes-section`.
- Cấu hình ban đầu Hướng dẫn 05, in hai mặt; người dùng có thể đổi sang Nghị định 30.
- Kiểm tra HTTP trang kết quả, minutes JSON, tải DOCX và ảnh trang 1: đều 200.
- API minutes xác nhận `hd05_2026`, phạm vi `all_pages`, 3 ảnh xem trước.
- Giao diện thực tế hiển thị lựa chọn hai thể thức, nút áp dụng, trường bổ
  sung thông tin và báo cáo những mục cần hoàn thiện.

## Phạm vi và giới hạn

Chưa bổ sung PDF/scan/OCR, dữ liệu fine-tuning hoặc thay đổi ASR/VAD/FCM.
Bố cục khó nhận diện, hộp văn bản, ảnh và phụ lục cần đối chiếu riêng.
Đầu ra là bản nháp DOCX đã áp dụng các quy tắc kỹ thuật và có báo cáo kiểm
tra; việc hoàn thiện metadata và kiểm tra ký/phát hành thuộc bước người dùng rà soát.
