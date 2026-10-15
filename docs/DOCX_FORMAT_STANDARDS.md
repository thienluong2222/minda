# Định dạng biên bản DOCX theo hai thể thức

Cập nhật ngày 15/10/2026. Áp dụng cho đầu vào DOC/DOCX; đầu ra chỉnh sửa được
là DOCX. Lựa chọn thể thức độc lập với chế độ biên bản chi tiết/tổng quát.

## Căn cứ và cấu hình

- [Nghị định 30/2020/NĐ-CP, bản gốc Chính phủ](https://datafiles.chinhphu.vn/cpp/files/vbpq/2020/03/30.signed.pdf): Phụ lục I và Mẫu 1.9 tại Phụ lục III.
- [Hướng dẫn 05-HD/VPTW ngày 27/5/2026, bản gốc Văn phòng Trung ương Đảng](https://tulieuvankien.dangcongsan.vn/upload/2006988/20260529/HD_05_VPTW_e1550.pdf): Phần II và Phụ lục 2. Thay thế Hướng dẫn 36-HD/VPTW năm 2018.

| Thuộc tính triển khai | `nd30_2020` | `hd05_2026` |
|---|---|---|
| Font nội dung | Times New Roman, đen, 14 pt | Times New Roman, đen, 14 pt |
| Trang | A4; giữ chiều ngang sẵn có | A4; giữ chiều ngang sẵn có |
| Lề trên/dưới/trái/phải | 20/20/30/15 mm | 20/20/30/15 mm |
| Giãn dòng nội dung | 1,15 | Exactly 20 pt |
| Thụt đầu dòng nội dung ngoài bảng | 10 mm | 10 mm |
| Khoảng cách sau đoạn nội dung | 6 pt | 6 pt |
| Tên biên bản | Đậm, 14 pt | Đậm, 16 pt |
| Trích yếu nhận diện được | Đậm, 14 pt; đường kẻ bên dưới | Đậm, 14 pt; năm dấu gạch nối bên dưới |
| Số văn bản | `Số: 01/BB-CQ` | `Số 01-BB/CQ` |
| Số trang | Trường PAGE, 14 pt, giữa lề trên; ẩn trang đầu | Như bên trái; cách mép trên 10 mm |
| In hai mặt | Không bật lề đối xứng | Cho phép lề đối xứng trái/phải |
| Khối ký họp thông thường | Thư ký trái, chủ tọa phải | Người ghi biên bản trái, chủ trì phải |

Các giá trị trên là giá trị được chọn trong phạm vi quy định; không phải mọi
thành phần đều dùng cùng cỡ chữ. Quốc hiệu 13 pt, tiêu ngữ 14 pt; tiêu đề Đảng
15 pt; cơ quan/số văn bản lần lượt 13 pt hoặc 14 pt theo thể thức.

## Cách dùng trong demo

1. Mở kết quả cuộc họp và phần **Biên bản Word**.
2. Chọn loại biên bản và **Thể thức trình bày**.
3. Mở **Bổ sung thông tin thể thức và người ký** khi cần nhập cơ quan, số và
   ký hiệu, địa danh/ngày ban hành, họ tên, nơi nhận hoặc người xác nhận chữ ký.
4. Tải DOC/DOCX và bấm **Xử lý biểu mẫu** để điền và định dạng.
5. Khi đã có biên bản, dùng **Áp dụng thể thức cho nội dung đã điền** để chỉ
   thay thể thức/thông tin trình bày. Nút này không chạy LLM, ASR hay FCM,
   không đổi trạng thái hoặc bằng chứng của các fact đã lưu.
6. Xem báo cáo, ảnh từng trang và tải DOCX. Thiếu cơ quan, số văn bản, ngày
   ban hành, người ký hoặc thẩm quyền xác nhận được liệt kê để hoàn thiện.

**Tạo lại từ transcript hiện có** vẫn là thao tác sinh lại nội dung. Các lựa
chọn thể thức được lưu khi sinh lại hoặc sửa fact. Ngày ban hành không lấy
tự động từ ngày họp; số văn bản không được hệ thống tự cấp.

## Cơ chế xử lý và bảo toàn dữ liệu

`normalize → parse/map → điền nội dung → format_minutes_document → kiểm tra → export`

- DOC được chuyển trên bản sao, ưu tiên LibreOffice với profile riêng;
  textutil là phương án dự phòng trên macOS. Khi có textutil, đối chiếu số
  lần xuất hiện các từ với nội dung DOCX. Đây không phải kiểm tra đầy đủ ảnh,
  bảng hay hộp văn bản; hạn chế chuyển đổi được ghi vào báo cáo.
- Hai cấu hình và phiên bản nằm trong `format_profiles.py`. Formatter không
  gọi mô hình. Giữ tên/thứ tự đề mục, đoạn và dữ kiện; các dòng chấm dài có
  thể chuyển thành tab leader của Word để tránh đẩy nhãn sang dòng khác.
- Nhận diện phần đầu dạng đoạn hoặc bảng hai cột thông thường, tạo lại phần
  đầu theo lựa chọn. Dùng bảng không viền, style và trường số trang Word.
- Họ tên ký lấy từ người dùng, vùng ký có sẵn hoặc fact đã có bằng chứng rõ.
  Chỉ tạo vùng ký; không tạo chữ ký, con dấu hoặc xác nhận thẩm quyền.
- Dấu hiệu người ký chuyên biệt, ghi chú lẫn trong phần đầu, hộp văn bản,
  đối tượng nhúng, header/footer bổ sung, số trang gõ tay hoặc phụ lục cần
  đối chiếu được báo để người dùng kiểm tra. Giữ lại dữ liệu chưa ánh xạ rõ.
  Trang ngang sẵn có được giữ và báo rà soát việc sử dụng cho bảng/biểu.
- Kiểm tra thứ tự và nội dung các đoạn được bảo vệ, A4, lề, font/cỡ chữ nội
  dung, giãn dòng, căn lề, trường PAGE và ẩn số trang đầu. Thay đổi có chủ ý
  ở thành phần thể thức hoặc nơi nhận nhập mới được theo dõi riêng.
- Lưu DOCX bằng cách ghép các phần OOXML cần sửa với các phần ZIP không liên
  quan của nguồn; giữ extension relationship/content type không nhận diện.
- Hash manifest được tính sau định dạng. Báo cáo và cấu hình nằm trong ZIP.
  Thao tác sinh/đổi thể thức/sửa fact có khóa và bản sao khôi phục khi lỗi.

## API và artifact

Upload multipart `POST /api/runs/{job_id}/template` nhận thêm:

- `format_standard`: `nd30_2020` (mặc định) hoặc `hd05_2026`.
- `two_sided`: boolean, chỉ dùng với Hướng dẫn 05.
- `document_metadata`: chuỗi JSON, có các trường được hiển thị trên giao diện.

`POST /api/runs/{job_id}/minutes/format` nhận JSON cùng cấu hình minutes;
chỉ áp dụng ba thuộc tính trên, giữ cấu hình nội dung trước đó.
`POST .../minutes/regenerate` nhận các thuộc tính mới trong `MinutesOptions`.

Artifact chính:

- `minutes/configuration.json`: thể thức, metadata nhập tay và cấu hình nội dung.
- `minutes/formatting_report.json`: phiên bản, nguồn quy định, kiểm tra, trường
  cần rà soát, thông tin chuyển DOC, các ảnh xem trước và phạm vi xem trước.
- `exports/completed.docx`, `exports/completed_minutes.zip`.
- `exports/minutes_preview/page-N.png`: các trang khi có LibreOffice/Poppler.

`checks_passed` chỉ nói các kiểm tra kỹ thuật đã đạt. `needs_review` cho biết
còn thông tin hoặc bố cục cần rà soát; không xác nhận thẩm quyền hay việc
ký phát hành. Ảnh xem trước tự động không thay cho bước kiểm tra của người dùng.

Nếu thiếu công cụ render nhiều trang, thử thumbnail Quick Look và ghi rõ
`thumbnail_only` hoặc `unavailable`. Chỉ dùng `all_pages` khi đã tạo đủ bộ ảnh.
PDF dùng nội bộ để render; tệp bàn giao chỉnh sửa được vẫn là DOCX.

Run cũ tiếp tục mở bình thường. Chỉ chuẩn hóa khi người dùng chủ động sinh,
đổi thể thức hoặc sửa thông tin; không tự viết lại hàng loạt biên bản cũ.

## Kiểm chứng

Xem [báo cáo triển khai và kiểm thử](reports/DOCX_FORMAT_UPDATE_2026-10-15.md).
