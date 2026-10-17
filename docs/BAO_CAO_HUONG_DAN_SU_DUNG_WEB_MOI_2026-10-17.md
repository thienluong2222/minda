# BÁO CÁO HƯỚNG DẪN MỞ VÀ SỬ DỤNG WEB MỚI

**Dự án:** Hệ thống hỗ trợ lập biên bản cuộc họp tiếng Việt từ nhiều nguồn ghi âm  
**Phiên bản tài liệu:** 17/10/2026  
**Phạm vi:** Bản web người dùng và quản trị viên, sử dụng MongoDB, chạy local phục vụ nghiên cứu và báo cáo luận văn.

## Mục lục

1. [Mục đích và luồng sử dụng](#1-mục-đích-và-luồng-sử-dụng)
2. [Cách mở, chạy và dừng web](#2-cách-mở-chạy-và-dừng-web)
3. [Đăng nhập và phân quyền](#3-đăng-nhập-và-phân-quyền)
4. [Các chức năng dành cho người dùng](#4-các-chức-năng-dành-cho-người-dùng)
5. [Hướng dẫn tạo một biên bản hoàn chỉnh](#5-hướng-dẫn-tạo-một-biên-bản-hoàn-chỉnh)
6. [Các chức năng dành cho quản trị viên](#6-các-chức-năng-dành-cho-quản-trị-viên)
7. [Trạng thái xử lý và cách khắc phục vấn đề thường gặp](#7-trạng-thái-xử-lý-và-cách-khắc-phục-vấn-đề-thường-gặp)
8. [Kịch bản trình diễn cho báo cáo luận văn](#8-kịch-bản-trình-diễn-cho-báo-cáo-luận-văn)
9. [Bố trí mã nguồn và dữ liệu](#9-bố-trí-mã-nguồn-và-dữ-liệu)
10. [Phạm vi và giới hạn của phiên bản hiện tại](#10-phạm-vi-và-giới-hạn-của-phiên-bản-hiện-tại)

## 1. Mục đích và luồng sử dụng

Web hỗ trợ quản lý cuộc họp, xử lý bản ghi âm, rà soát lời chép và tạo biên bản Word. Người dùng có thể dùng mẫu DOC/DOCX, PDF hoặc ảnh scan; kết quả biên bản được xuất thành **DOCX có thể chỉnh sửa tiếp bằng Word**.

Quy trình sử dụng chính:

```text
Chuẩn bị và duyệt mẫu tài liệu
              ↓
Tạo cuộc họp, tải bản ghi âm và chọn hồ sơ giọng nếu có
              ↓
Chạy xử lý âm thanh → rà soát transcript và nhãn người nói
              ↓
Chọn mẫu, loại biên bản, thể thức và tạo nội dung
              ↓
Đối chiếu bằng chứng → sửa các trường → xem trước DOCX
              ↓
Xác nhận đã rà soát → tải DOCX / gói bằng chứng
```

**Chép lời và tạo biên bản là hai bước riêng.** Sau khi xử lý âm thanh xong, người dùng rà soát transcript rồi chủ động yêu cầu tạo biên bản.

## 2. Cách mở, chạy và dừng web

### 2.1. Vị trí cần mở

Toàn bộ bản web mới nằm tại:

```text
/Users/thien/Documents/School/Luận văn/web_app
```

Mở thư mục `web_app` trong trình soạn thảo để xem frontend, backend, cấu hình và tài liệu của bản web mới. Các lệnh trong báo cáo này đều chạy **bên trong `web_app`**.

### 2.2. Mở nhanh trên máy hiện tại

Máy phát triển hiện tại đã có môi trường và bản build giao diện. Mở Terminal và chạy:

```bash
cd "/Users/thien/Documents/School/Luận văn/web_app"
.venv-backend/bin/python scripts/backend/run_local.py
```

Sau đó mở trình duyệt tại:

**[http://127.0.0.1:8010](http://127.0.0.1:8010)**

Lệnh trên chạy đồng thời:

- **API và giao diện:** nhận yêu cầu, quản lý dữ liệu, phục vụ các trang web.
- **Worker:** thực hiện tác vụ nền như ASR, OCR, tạo biên bản, xuất tài liệu và sao lưu.

MongoDB cần đang hoạt động tại địa chỉ đã cấu hình. Cấu hình mặc định hiện tại là `mongodb://127.0.0.1:27017`, database `meeting_app_dev` và thư mục file `data/app`.

Nếu web đã chạy, chỉ cần mở địa chỉ trên. Không cần chạy thêm một phiên server. Cổng **8010** dành cho bản web mới; demo cũ ở cổng **8000** có lệnh chạy riêng.

### 2.3. Dừng web

Tại Terminal đang chạy `run_local.py`, nhấn **Ctrl+C**. Launcher sẽ dừng cả API và worker mà nó đã khởi động.

Đóng tab trình duyệt chỉ đóng giao diện; server và tác vụ nền vẫn tiếp tục chạy. Nếu cần dừng trong lúc đang xử lý một cuộc họp, nên chờ tác vụ hoàn tất hoặc yêu cầu hủy trong giao diện trước.

### 2.4. Kiểm tra môi trường khi không mở được

Chạy:

```bash
cd "/Users/thien/Documents/School/Luận văn/web_app"
.venv-backend/bin/python -m meeting_backend.cli doctor
```

Kiểm tra các thành phần được báo thiếu hoặc không kết nối được. Bản prototype hiện tại sử dụng macOS Apple Silicon, Python 3.11, MongoDB, FFmpeg/ffprobe, LibreOffice, Poppler và Tesseract. Runtime LLM và cache trọng số cũng cần có để sử dụng các tác vụ AI tương ứng.

### 2.5. Chạy sau khi sửa mã giao diện

Khi sửa mã trong `apps/web/src`, cần build lại để cổng 8010 phục vụ giao diện mới:

```bash
npm --prefix apps/web run build
```

Nếu mới cài môi trường hoặc thay đổi dependency frontend, chạy `npm --prefix apps/web ci` trước khi build. Trong lúc phát triển, có thể dùng `npm --prefix apps/web run dev` để mở giao diện ở cổng 5173; API và worker vẫn cần chạy. Người chỉ sử dụng hoặc trình diễn hệ thống nên dùng cổng **8010**.

Hướng dẫn cài môi trường trên máy mới, chạy API/worker riêng và nhập kết quả từ bản cũ nằm trong [QUICKSTART](backend/QUICKSTART.md).

## 3. Đăng nhập và phân quyền

### 3.1. Lần đầu sử dụng database mới

Nếu database chưa có tài khoản, web hiển thị **“Thiết lập quản trị viên”**. Nhập tên hiển thị, tên đăng nhập và mật khẩu để tạo admin đầu tiên.

- Tên đăng nhập dài 3–48 ký tự, gồm chữ không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.
- Mật khẩu tài khoản mới dài 10–128 ký tự.
- Hệ thống **không có tên đăng nhập hoặc mật khẩu mặc định**.

Nếu đã có tài khoản, web hiển thị trang đăng nhập thông thường. Dữ liệu thuộc database đang được chọn trong cấu hình; tài khoản ở database thử nghiệm khác không tự xuất hiện tại đây.

### 3.2. Hai vai trò

| Vai trò | Chức năng chính |
| --- | --- |
| Người dùng — `user` | Quản lý cuộc họp, mẫu riêng, hồ sơ giọng, transcript và biên bản của mình; sử dụng mẫu dùng chung. |
| Quản trị viên — `admin` | Có không gian cá nhân và khu vực quản trị tài khoản, tác vụ, cấu hình, mẫu chung, sao lưu, đánh giá và nhật ký. |

Admin chọn **“Quản trị hệ thống”** để mở khu vực quản trị và **“Về không gian cá nhân”** để trở lại luồng làm việc với cuộc họp. Quyền quản trị hệ thống không tự cho phép đọc hoặc chỉnh sửa nội dung cuộc họp riêng của người khác qua các màn hình làm việc cá nhân.

### 3.3. Đổi mật khẩu và đăng xuất

Vào **Thiết lập**, nhập mật khẩu hiện tại và mật khẩu mới. Sau khi đổi mật khẩu, đăng nhập lại theo yêu cầu của hệ thống. Nút đăng xuất nằm ở thanh điều hướng bên trái. Nếu quên mật khẩu, nhờ admin đặt lại mật khẩu tài khoản.

## 4. Các chức năng dành cho người dùng

### 4.1. Các trang chính

| Trang | Nội dung và thao tác |
| --- | --- |
| **Tổng quan** | Theo dõi số cuộc họp, biên bản, mục cần rà soát, cuộc họp gần đây và trạng thái xử lý. |
| **Cuộc họp** | Tìm cuộc họp theo tên, xem danh sách, tạo mới và mở không gian làm việc của từng cuộc họp. |
| **Thư viện mẫu** | Tải mẫu, kiểm tra chữ/OCR, xác định trường cần điền, duyệt và sử dụng mẫu. |
| **Hồ sơ giọng** | Tạo hồ sơ từ mẫu giọng để hỗ trợ nhận diện người tham gia. |
| **Thùng rác** | Xem và khôi phục cuộc họp đã chuyển vào thùng rác. |
| **Thiết lập** | Đổi mật khẩu tài khoản. |

Chuông thông báo giúp theo dõi tác vụ. Các số liệu tổng quan là thống kê dữ liệu và trạng thái xử lý, không phải chỉ số độ chính xác của mô hình.

### 4.2. Không gian làm việc của một cuộc họp

| Tab | Chức năng |
| --- | --- |
| **Tổng quan** | Xem/sửa thông tin cuộc họp, quản lý nguồn âm thanh, chọn hồ sơ tham gia, bắt đầu hoặc chạy lại xử lý. |
| **Transcript** | Đọc lời chép theo đoạn và thời gian, tìm kiếm, lọc người nói/mục cần rà soát, nghe clip và sửa văn bản. |
| **Người nói** | Xem các nhóm người nói và đổi nhãn hiển thị. Theo dõi đoạn chưa xác định hoặc nói chồng. |
| **Biên bản** | Chọn mẫu và thể thức, tạo nội dung, sửa các trường, đối chiếu bằng chứng, xem trước các trang DOCX và tải kết quả. |
| **Lịch sử** | Xem phiên bản, đối chiếu transcript, xem/tải biên bản cũ và khôi phục thành phiên bản mới. |

## 5. Hướng dẫn tạo một biên bản hoàn chỉnh

### Bước 1 — Thêm và kiểm tra mẫu tài liệu

1. Vào **Thư viện mẫu → Thêm mẫu tài liệu**.
2. Nhập tên mẫu và chọn file: **DOC, DOCX, PDF, PNG, JPG/JPEG, TIF/TIFF**.
3. Chọn **“Tải lên & phân tích”** và chờ tác vụ hoàn tất.
4. Mở mẫu để kiểm tra hai phần: **“Trường dữ liệu”** và **“Đối chiếu chữ / OCR”**.

Hệ thống chuyển tài liệu về dạng Word để sử dụng. PDF có chữ được trích xuất văn bản; PDF scan và ảnh sử dụng OCR. Bản gốc được giữ để đối chiếu; có thể tải bản gốc, Word chuẩn hóa và báo cáo đọc tài liệu/OCR.

**Đối với PDF và ảnh, cần rà soát và duyệt trước khi dùng để tạo biên bản.** Kiểm tra chữ có dấu, thứ tự đoạn, bảng, đề mục và vị trí cần điền. Nếu OCR sai:

1. Sửa chữ ở tab **Đối chiếu chữ / OCR**.
2. Nếu thiếu vị trí điền, bổ sung chỗ trống như `____` hoặc dấu chấm tại vị trí phù hợp.
3. Bấm **“Lưu chữ & phân tích lại”** để hệ thống nhận diện lại các trường.
4. Kiểm tra ý nghĩa từng trường, điều chỉnh lựa chọn hoặc xóa trường nhận diện nhầm.
5. Tích **“Tôi đã đối chiếu nội dung và các trường với bản gốc”** rồi bấm **“Duyệt & lưu mẫu”**.

Lưu chữ và duyệt mẫu là hai bước riêng. Khi sửa chữ, cần kiểm tra lại các trường sau lần phân tích mới. Mẫu Word cũng nên được kiểm tra dù không luôn phải qua bước duyệt OCR bắt buộc.

Mẫu riêng do người sở hữu quản lý; mẫu dùng chung do admin cung cấp. Người dùng được sử dụng mẫu chung nhưng không sửa bản mẫu của người khác.

### Bước 2 — Tạo hồ sơ giọng nếu có dữ liệu

Vào **Hồ sơ giọng → Tạo hồ sơ giọng**, nhập tên và tải các mẫu nói của một người. Mỗi hồ sơ hỗ trợ tối đa 8 mẫu; có thể bổ sung bằng nút **“Thêm mẫu”**.

Nên dùng âm thanh rõ, một người nói, ít nhiễu và ít nói chồng. Sau khi worker xử lý, xem trạng thái và cảnh báo chất lượng. Hồ sơ sẵn sàng có thể được chọn làm người tham gia cuộc họp.

**Hồ sơ giọng không bắt buộc để chép lời.** Nhận diện tự động vẫn cần đối chiếu. Hồ sơ đang được cuộc họp chưa nằm trong thùng rác sử dụng cần được bỏ chọn khỏi cuộc họp đó trước khi lưu trữ hồ sơ.

### Bước 3 — Tạo cuộc họp và tải bản ghi âm

Vào **Cuộc họp**, chọn tạo cuộc họp mới. Trình tạo gồm bốn bước:

| Bước trên giao diện | Nội dung cần nhập |
| --- | --- |
| **Thông tin cuộc họp** | Tiêu đề bắt buộc; bổ sung ngày họp, địa điểm và ghi chú nếu có. |
| **Nguồn ghi âm** | Tải 1–8 bản ghi của cùng cuộc họp. |
| **Người tham gia** | Chọn hồ sơ giọng đã sẵn sàng nếu có, tối đa 8 hồ sơ. |
| **Mẫu & xác nhận** | Chọn mẫu đã duyệt hoặc chọn sau; đặt loại biên bản và thể thức mong muốn. |

Định dạng nguồn hỗ trợ gồm **WAV, MP3, M4A, AAC, FLAC, OGG, WEBM, MP4**; file phải có luồng âm thanh đọc được. Giới hạn mặc định là **1 GB mỗi file**, tối đa **8 nguồn** cho một cuộc họp.

Nếu có nhiều thiết bị, tải các bản ghi cùng cuộc họp để hệ thống đồng bộ và dung hợp. Không ghép bản ghi của các cuộc họp khác nhau thành các nguồn của một cuộc họp.

- **“Lưu bản nháp”**: lưu thông tin để hoàn thiện sau; chưa bắt buộc có audio.
- **“Tải lên & xử lý”**: tải nguồn và đưa tác vụ xử lý âm thanh vào hàng đợi.

Sau khi tạo, có thể quản lý nguồn tại tab **Tổng quan**. Nút **“Bắt đầu xử lý”** hoặc **“Xử lý lại âm thanh”** dùng để chạy ASR theo dữ liệu hiện tại.

### Bước 4 — Rà soát transcript và người nói

Khi xử lý âm thanh hoàn tất:

1. Mở tab **Transcript** để xem từng đoạn, mốc thời gian và nhãn người nói.
2. Dùng tìm kiếm, bộ lọc người nói hoặc bộ lọc cần rà soát để tìm đoạn cần kiểm tra.
3. Nghe clip tương ứng, đặc biệt với tên riêng, con số, thời hạn và quyết định.
4. Chọn sửa đoạn, điều chỉnh lời chép rồi **“Lưu thay đổi”**.
5. Mở tab **Người nói**, dùng **“Đổi nhãn”** để sửa tên hiển thị của nhóm người nói khi có căn cứ.

**“Chưa xác định”** và **“Nói chồng”** là trạng thái cần kiểm tra, không phải hai người tham gia. Các nhóm ẩn danh như “Speaker 1” cần được đối chiếu trước khi gán tên thật. Giao diện hiện hỗ trợ đổi nhãn; chưa cung cấp thao tác gộp/tách nhóm người nói thủ công.

Mỗi lần sửa transcript tạo phiên bản để truy lại. Đoạn thiếu lời chép hoặc nói chồng cần nghe và bổ sung bằng thông tin thực tế; không nên tự suy đoán nội dung chỉ từ ngữ cảnh.

### Bước 5 — Chọn cách tạo biên bản

Mở tab **Biên bản**, chọn mẫu sẵn sàng, loại biên bản và các tùy chọn.

| Lựa chọn | Cách sử dụng |
| --- | --- |
| **Chi tiết** | Dùng mẫu có đề mục/chủ đề định sẵn. Hệ thống điền vào các trường và giữ các đề mục của mẫu đã chuẩn hóa, rà soát. |
| **Tổng quát** | Dùng mẫu có vùng nội dung cuộc họp tổng hợp. Hệ thống tổ chức các ý trong transcript thành nội dung theo chủ đề. Chế độ này yêu cầu LLM. |
| **LLM** | Hỗ trợ hiểu ngữ cảnh, chuẩn hóa câu chữ và chuyển văn nói sang văn viết. Có tùy chọn sửa lỗi ASR; kết quả cần được đối chiếu. |
| **E5 + Fuzzy C-Means** | Tùy chọn hỗ trợ gom nhóm nội dung trong chế độ tổng quát. Có thể để hệ thống tự chọn số cụm hoặc nhập số cụm trong giới hạn giao diện. |

Trong chế độ tổng quát, mục **“Trường nội dung cuộc họp”** mặc định tự xác định trường đích. Khi giao diện đã liệt kê các trường, có thể chọn một trường cụ thể. Nội dung cần giữ các ý có căn cứ từ transcript; trường thiếu thông tin sẽ để trống hoặc được đánh dấu cần rà soát.

Chọn thể thức xuất tài liệu:

- **Hành chính · Nghị định 30/2020**.
- **Tài liệu Đảng · Hướng dẫn 05/2026**; có tùy chọn trình bày hai mặt tương ứng.

Trong phần thông tin bổ sung, điền cơ quan, số văn bản, địa danh/ngày ban hành, chủ trì, thư ký, nơi nhận và thông tin ký khi cần. **Ngày diễn ra cuộc họp và ngày ban hành văn bản là hai thông tin riêng.** Kiểm tra cả hai trước khi xuất.

Nhấn **“Tạo biên bản từ transcript”**. Tác vụ này dùng transcript hiện tại và chạy ở worker. Không cần chạy lại âm thanh chỉ để tạo biên bản lần đầu từ transcript đã có.

### Bước 6 — Rà soát và chỉnh sửa biên bản

Màn hình biên bản có danh sách trường/nội dung và phần xem trước các trang DOCX đã render. Có thể chuyển trang và mở ảnh trang để xem rõ hơn.

Các trạng thái nội dung gồm:

| Trạng thái | Ý nghĩa cần xử lý |
| --- | --- |
| **Có căn cứ** | Có nguồn tham chiếu hoặc đã được người dùng đối chiếu. Vẫn cần đọc trước khi sử dụng chính thức. |
| **Thiếu thông tin** | Chưa có đủ dữ liệu để điền. Bổ sung từ nguồn đã kiểm chứng nếu có. |
| **Cần rà soát** | Cần kiểm tra nội dung, cách hiểu hoặc câu chữ. |
| **Mâu thuẫn** | Có thông tin chưa thống nhất, cần xác minh trước khi chốt. |

Quy trình kiểm tra một trường:

1. Chọn nút bằng chứng của trường để xem đoạn transcript, người nói, thời gian và nghe clip nếu có.
2. Chọn **“Chỉnh sửa”** để sửa giá trị. Trường danh sách hỗ trợ sửa, thêm hoặc bỏ từng mục.
3. Chọn trạng thái phù hợp và ghi lý do sửa nếu cần. Chỉ đánh dấu đã đối chiếu sau khi kiểm tra nguồn.
4. Bấm **“Lưu & cập nhật tài liệu”**; chờ tác vụ tạo phiên bản và render lại DOCX.
5. Kiểm tra nội dung và bố cục trên bản xem trước mới.

Bằng chứng của một phiên bản biên bản được đối chiếu với **phiên bản transcript dùng để tạo biên bản đó**. Vì vậy vẫn truy được nguồn cũ sau khi transcript có chỉnh sửa mới. Kết quả nhập từ bản cũ có thể chỉ có bằng chứng chữ nếu gói nguồn không chứa audio.

### Bước 7 — Tạo lại nội dung hoặc chỉ đổi thể thức

Chọn **“Cấu hình & tạo lại”** khi cần thay đổi cấu hình:

| Thao tác | Kết quả |
| --- | --- |
| **Tạo biên bản từ transcript** | Tạo lại nội dung dựa trên transcript hiện tại và cấu hình đang chọn. Các trường sửa tay hợp lệ còn cùng ID được giữ lại; cần kiểm tra sau khi đổi mẫu. |
| **Chỉ cập nhật thể thức** | Dùng nội dung biên bản đang lưu để cập nhật thể thức và thông tin văn bản; không chạy lại ASR/LLM. |

**Cập nhật thể thức không lấy nội dung mới từ transcript.** Nếu transcript đã sửa và biên bản bị báo không còn cập nhật, cần tạo lại nội dung để đồng bộ.

### Bước 8 — Xác nhận và tải kết quả

Sau khi kiểm tra nội dung và preview:

1. Bấm **“Đã rà soát”** để ghi nhận việc rà soát phiên bản hiện tại. Hệ thống chặn xác nhận khi biên bản chưa cập nhật theo dữ liệu mới hoặc đang có tác vụ liên quan.
2. Bấm **“Tải DOCX”** để mở và chỉnh sửa tiếp bằng Word.
3. Bấm **“Gói bằng chứng”** nếu cần tải gói ZIP tài liệu và dữ liệu truy vết đi kèm.

Xác nhận rà soát trên web là dấu mốc công việc của phiên bản; chưa phải chữ ký số hoặc thủ tục ban hành văn bản.

### Bước 9 — Tra cứu lịch sử và khôi phục

Trong tab **Lịch sử**:

- Xem thời điểm, lý do thay đổi và phiên bản hiện hành.
- Dùng **“Đối chiếu nội dung”** để xem khác biệt transcript.
- Dùng **“Xem bản đã lưu”** để xem trước và tải DOCX của phiên bản biên bản cũ.
- Dùng **“Khôi phục”** để tạo một phiên bản mới từ bản cũ; lịch sử trước đó vẫn được giữ.

Phiên bản khôi phục có thể không khớp transcript hiện hành. Kiểm tra cảnh báo và tạo lại nội dung nếu cần trước khi xác nhận.

### Các thay đổi làm kết quả cần được cập nhật

| Thay đổi | Bước tiếp theo |
| --- | --- |
| Thêm/xóa nguồn âm thanh hoặc đổi hồ sơ người tham gia | Chạy lại xử lý âm thanh rồi kiểm tra transcript và tạo lại biên bản. |
| Sửa transcript hoặc nhãn người nói | Rà soát thay đổi và tạo lại nội dung biên bản. |
| Sửa thông tin cuộc họp liên quan đến biên bản | Kiểm tra cảnh báo cập nhật và tạo lại nội dung khi cần. |
| Chỉ đổi thể thức/thông tin ban hành của bản đang lưu | Có thể dùng “Chỉ cập nhật thể thức”. |
| Chuyển cuộc họp vào thùng rác | Khôi phục trong Thùng rác trước khi tiếp tục chỉnh sửa. |

Thùng rác hiện hỗ trợ chuyển cuộc họp vào và khôi phục; phiên bản và tài liệu được giữ lại. Giao diện chưa có chức năng xóa vĩnh viễn cuộc họp.

## 6. Các chức năng dành cho quản trị viên

Sau khi đăng nhập admin, chọn **Quản trị hệ thống**.

### 6.1. Tổng quan hệ thống

Theo dõi số tài khoản, cuộc họp, trạng thái tác vụ, worker, dung lượng đĩa và các công cụ xử lý. Dùng trang này để xác định hệ thống có sẵn sàng nhận tác vụ hay không.

Nhấn thẻ **Tài khoản** hoặc **Cuộc họp** để mở danh sách tương ứng. Ô tìm cuộc họp trên thanh đầu trang trong khu vực admin tìm trên toàn hệ thống.

### 6.2. Tài khoản

Admin có thể:

- Tạo tài khoản người dùng hoặc admin.
- Đổi vai trò, khóa/mở khóa tài khoản.
- Đặt lại mật khẩu tài khoản khác; phiên đăng nhập liên quan sẽ bị thu hồi theo thao tác bảo mật.

Giao diện có bảo vệ việc admin tự khóa hoặc tự hạ quyền tài khoản đang dùng. Người dùng không tự đăng ký công khai trong phiên bản hiện tại; admin tạo tài khoản cho người dùng.

Danh sách có tìm theo tên/tên đăng nhập, lọc vai trò và trạng thái hoạt động, nút **Làm mới**, trạng thái đang tải và thông báo lỗi. Danh sách tự cập nhật mỗi 5 giây; tài khoản khóa vẫn xuất hiện khi chọn tất cả. Mỗi tài khoản hiển thị số cuộc họp và số cuộc họp trong thùng rác; nhấn số lượng để mở danh sách theo người sở hữu.

### 6.3. Cuộc họp toàn hệ thống

Vào **Quản trị hệ thống → Cuộc họp** để xem cuộc họp của mọi tài khoản, gồm người sở hữu, ngày họp, trạng thái xử lý, số nguồn và tình trạng transcript/biên bản.

- Tìm theo tên cuộc họp hoặc tên/tên đăng nhập của người sở hữu.
- Lọc người sở hữu, trạng thái và phạm vi đang sử dụng/thùng rác/tất cả.
- Chuyển trang; bộ lọc áp dụng trên toàn bộ kết quả.
- Chọn **Thông tin** để xem thông tin quản lý của cuộc họp.
- Với cuộc họp thuộc chính tài khoản admin, chọn **Mở cuộc họp** để vào không gian làm việc.

Trang tự cập nhật mỗi 5 giây và có nút **Làm mới**. Các thông tin quản lý trên trang này không thay đổi quyền đọc/chỉnh sửa transcript, file và biên bản riêng trong không gian cá nhân.

### 6.4. Tác vụ xử lý

Xem tác vụ toàn hệ thống, chủ sở hữu, trạng thái, công đoạn và log. Có thể yêu cầu hủy tác vụ đang chờ/đang chạy, hoặc thử lại tác vụ thất bại, gián đoạn, đã hủy khi còn đủ điều kiện.

Hủy trong lúc mô hình đang suy luận có thể phải đợi đến điểm kiểm tra tiếp theo. Nếu dữ liệu đầu vào đã đổi, tạo yêu cầu xử lý mới thay vì thử lại tác vụ dùng dữ liệu cũ.

### 6.5. Mô hình & cấu hình

Xem môi trường thực thi, cache mô hình và trạng thái worker; chọn các preset xử lý được hệ thống cung cấp, gồm nhận diện giọng, ASR, phương pháp dung hợp, mặc định dùng LLM và thể thức mặc định.

Mỗi tác vụ lưu cấu hình tại thời điểm được đưa vào hàng đợi. Thay đổi preset áp dụng cho tác vụ mới. **Có trọng số trong cache không đồng nghĩa mô hình đang nằm trong RAM**; worker nạp mô hình khi cần. Trang này chưa có chức năng fine-tune mô hình.

### 6.6. Mẫu dùng chung

Admin tải, rà soát và cung cấp mẫu dùng chung cho các tài khoản. Quy trình kiểm tra OCR và trường dữ liệu giống thư viện mẫu cá nhân. Chỉ phát hành mẫu sau khi đối chiếu cấu trúc, chữ và vị trí cần điền.

### 6.7. Sao lưu dữ liệu

Trong **Sao lưu dữ liệu**, tạo tác vụ sao lưu, chờ hoàn tất rồi tải ZIP. Gói sao lưu gồm metadata và các file được tham chiếu, dữ liệu phụ trợ của lượt xử lý và hồ sơ giọng. Trọng số mô hình, log, phiên đăng nhập và hàng đợi tác vụ không được đóng gói.

Để khôi phục:

1. Tải gói ZIP lên và chọn **“Kiểm tra & khôi phục sang database mới”**.
2. Đọc và xác nhận yêu cầu khôi phục trên giao diện.
3. Chờ kiểm tra checksum và hoàn tất khôi phục.
4. Ghi lại database và thư mục dữ liệu mới trong kết quả.
5. Nếu muốn chuyển web sang bộ dữ liệu vừa khôi phục: dừng API/worker, đặt cả `MEETING_APP_MONGO_DATABASE` và `MEETING_APP_DATA_DIR` theo kết quả rồi khởi động lại.
6. Đăng nhập bằng tài khoản có trong bản sao lưu.

Khôi phục tạo database và thư mục mới; **không tự chuyển web đang chạy sang dữ liệu vừa khôi phục**. Hướng dẫn kỹ thuật nằm trong [QUICKSTART](backend/QUICKSTART.md#5-sao-lưu-và-tra-lỗi).

### 6.8. Đánh giá

Tạo lần đánh giá từ cuộc họp thuộc tài khoản admin, nhập văn bản tham chiếu đã được kiểm tra thủ công và ghi chú nếu có. Hệ thống tính **WER, CER**, thống kê lỗi thay thế/xóa/chèn và lưu thông tin phiên bản transcript phục vụ tái lập.

Các chỉ số này đo lỗi chép lời so với văn bản tham chiếu được nhập. Chúng không thay thế đánh giá người nói, chất lượng gom cụm hoặc mức độ đúng/đủ của biên bản. Cần nhiều mẫu đại diện để kết luận chất lượng chung.

### 6.9. Nhật ký hệ thống

Tra cứu các thao tác đã ghi nhận và lọc theo hành động/tài nguyên. Dùng nhật ký để xác định ai đã thực hiện thao tác quản trị, phục vụ kiểm tra sự cố và quản lý thay đổi.

## 7. Trạng thái xử lý và cách khắc phục vấn đề thường gặp

### 7.1. Ý nghĩa các trạng thái

| Trạng thái | Ý nghĩa |
| --- | --- |
| **Bản nháp** | Chưa đủ đầu vào hoặc cần chạy lại âm thanh sau thay đổi. |
| **Đang chờ** | Tác vụ đã được xếp hàng, chờ worker nhận xử lý. |
| **Đang xử lý** | Worker đang thực hiện tác vụ. |
| **Hoàn tất** | Tác vụ đã hoàn tất; vẫn cần rà soát chất lượng nội dung. |
| **Thất bại** | Tác vụ gặp lỗi; mở thông báo/log để xác định nguyên nhân. |
| **Gián đoạn** | Tác vụ không hoàn tất sau khi worker bị ngắt hoặc mất quyền xử lý. |
| **Đã hủy** | Yêu cầu hủy đã được xử lý. |

Tác vụ nền tiếp tục chạy khi đóng trang. Có thể mở lại cuộc họp để theo dõi. Khi đang có tác vụ liên quan, một số thao tác chỉnh sửa bị khóa để tránh dữ liệu thay đổi giữa lúc xử lý.

### 7.2. Tra lỗi nhanh

| Hiện tượng | Cách kiểm tra/xử lý |
| --- | --- |
| Trình duyệt không vào được cổng 8010 | Kiểm tra Terminal chạy server; chạy launcher nếu chưa chạy. Nếu báo cổng đã dùng, kiểm tra phiên server hiện có trước khi chạy thêm. |
| Web mở nhưng tác vụ ở “Đang chờ” lâu | Kiểm tra worker. Nếu chỉ chạy lệnh `serve`, cần chạy thêm `worker` với cùng cấu hình, hoặc dùng launcher chung. |
| Không kết nối được database | Kiểm tra MongoDB và `configs/backend.yaml`; dùng lệnh `doctor`. |
| Không thấy trang tạo admin đầu tiên | Database đang có tài khoản; đăng nhập bằng tài khoản đã tạo của database đó. |
| Không đăng nhập được | Kiểm tra tên tài khoản, mật khẩu, trạng thái khóa và database đang dùng; nhờ admin đặt lại mật khẩu nếu cần. |
| Mẫu không xuất hiện trong lựa chọn tạo biên bản | Chờ phân tích hoàn tất, kiểm tra trạng thái; với PDF/ảnh cần hoàn tất duyệt chữ và trường dữ liệu. |
| Không tạo được biên bản từ transcript cũ sau khi đổi nguồn | Chạy lại xử lý âm thanh; dữ liệu nguồn mới cần một transcript cập nhật. |
| Không xem trước được DOCX | Kiểm tra LibreOffice/Poppler bằng `doctor`. Nếu tài liệu đã tạo lúc thiếu công cụ, dùng `repair-previews --apply` theo [QUICKSTART](backend/QUICKSTART.md#công-cụ-xem-trước-docx-trên-máy-macos) rồi tải lại trang. |
| OCR không chạy | Kiểm tra Tesseract và trọng số `vie+eng`; xem bước `prepare-ocr` trong QUICKSTART. |
| Mô hình chưa sẵn sàng | Xem trang Mô hình & cấu hình, chạy `doctor` và chuẩn bị runtime/cache theo tài liệu AI. |
| File âm thanh bị từ chối | Kiểm tra định dạng, giới hạn 1 GB/file và có luồng âm thanh hợp lệ; hệ thống dùng `ffprobe` để kiểm tra. |
| Báo xung đột phiên bản/409 | Tải lại dữ liệu mới trước khi sửa; tránh lưu từ một tab đang giữ phiên bản cũ. |
| Biên bản báo chưa cập nhật sau khi sửa transcript | Tạo lại nội dung từ transcript hiện tại. Chỉ đổi thể thức không xử lý cảnh báo này. |

Vị trí log mặc định:

```text
data/app/logs/api.log
data/app/logs/jobs/<job-id>/worker.log
```

Nếu dùng thư mục dữ liệu khác, log nằm dưới thư mục dữ liệu tương ứng. Khi báo lỗi, ghi lại tên cuộc họp, thao tác, thời điểm, thông báo và ID tác vụ để tìm đúng log.

## 8. Kịch bản trình diễn cho báo cáo luận văn

Chuẩn bị một mẫu biên bản đã duyệt, một đoạn ghi âm ngắn rõ tiếng và tài khoản demo. Nếu trình diễn nhiều nguồn, dùng các bản ghi cùng cuộc họp.

| Thứ tự | Nội dung trình diễn | Kết quả cần cho thấy |
| --- | --- | --- |
| 1 | Đăng nhập và mở Tổng quan | Hai vai trò và không gian làm việc có phân quyền. |
| 2 | Mở thư viện mẫu | Có bản gốc, bản chuẩn hóa, trường dữ liệu và quy trình duyệt OCR. |
| 3 | Tạo cuộc họp, tải nguồn và chạy xử lý | Tác vụ thật được worker xử lý, có trạng thái và nguồn âm thanh. |
| 4 | Mở Transcript, nghe và sửa một đoạn | Người dùng đối chiếu được lời chép với âm thanh; có lịch sử sửa. |
| 5 | Kiểm tra Người nói | Phân biệt nhóm người nói, chưa xác định và nói chồng. |
| 6 | Tạo biên bản chi tiết hoặc tổng quát | Chọn được mẫu, LLM/FCM theo chế độ và thể thức tài liệu. |
| 7 | Sửa một trường, mở bằng chứng và xem DOCX | Nội dung có truy vết, bản xem trước cập nhật theo phiên bản mới. |
| 8 | Tải DOCX và mở bằng Word | Kết quả là tài liệu có thể chỉnh sửa. |
| 9 | Mở Lịch sử | Có thể xem lại/đối chiếu và khôi phục thành phiên bản mới. |
| 10 | Chuyển sang quản trị | Quản lý tài khoản, tác vụ/log, cấu hình, backup và đánh giá. |

Với phần trình diễn dùng LLM/OCR, chuẩn bị cache mô hình trước buổi báo cáo. Thời gian xử lý phụ thuộc độ dài ghi âm, số nguồn, số trang và cấu hình máy; giao diện không cam kết một thời gian cố định.

## 9. Bố trí mã nguồn và dữ liệu

Các đường dẫn dưới đây tính từ `web_app`:

| Vị trí | Nội dung |
| --- | --- |
| `apps/web/src/` | Mã giao diện React/TypeScript. |
| `apps/web/src/features/meetings/` | Danh sách cuộc họp, transcript, người nói, biên bản và lịch sử. |
| `apps/web/src/features/templates/` | Thư viện mẫu và hồ sơ giọng. |
| `apps/web/src/features/admin/` | Các màn hình quản trị. |
| `src/meeting_backend/` | API, phân quyền, MongoDB, tác vụ nền và tích hợp xử lý tài liệu. |
| `src/meeting_pipeline/` | Pipeline âm thanh, nhận diện người nói, ASR, LLM, E5/FCM và tạo Word. |
| `configs/backend.yaml` | Cấu hình ứng dụng web, database, thư mục dữ liệu và giới hạn tải lên. |
| `configs/default.yaml` | Cấu hình pipeline âm thanh. |
| `configs/minutes.yaml` | Cấu hình xử lý biên bản và LLM. |
| `scripts/backend/run_local.py` | Launcher chạy API và worker. |
| `data/app/` | File dữ liệu của ứng dụng mặc định: đầu vào, kết quả, phiên bản và log. |
| `docs/backend/` | Tài liệu cài đặt, kiến trúc và kiểm thử backend/web. |

MongoDB lưu metadata; các file lớn như âm thanh, tài liệu và preview nằm trong thư mục dữ liệu. Bản web hiện giữ nhánh Git `codex/web-mongodb-upgrade` riêng trong `web_app`; thực hiện thao tác Git cho bản web tại thư mục này.

Tài liệu tham khảo nội bộ:

- [Hướng dẫn kỹ thuật, cài đặt và nhập dữ liệu cũ](backend/QUICKSTART.md).
- [Kiến trúc và cách bố trí backend](backend/ARCHITECTURE.md).
- [Phạm vi và kết quả kiểm thử bản web](backend/VALIDATION_2026-10-17.md).
- [LLM, embedding E5 và Fuzzy C-Means](LLM_FCM_MINUTES.md).
- [Cấu hình và kiểm tra thể thức DOCX](DOCX_FORMAT_STANDARDS.md).

## 10. Phạm vi và giới hạn của phiên bản hiện tại

- Đã có đăng nhập/phân quyền, luồng cuộc họp, xử lý nền, thư viện mẫu/OCR, hồ sơ giọng, rà soát transcript/biên bản, preview DOCX, lịch sử và quản trị.
- Chỉnh sửa trên web theo trường/nội dung; chưa có trình soạn thảo toàn bộ trang như Word. DOCX tải về có thể chỉnh tiếp bằng Word.
- LLM và phân cụm hỗ trợ tổ chức, diễn đạt nội dung; vẫn cần kiểm tra tên người, số liệu, quyết định, nhiệm vụ và thời hạn với nguồn thực tế.
- PDF/ảnh scan có thể sai chữ hoặc bố cục khi chuẩn hóa, nhất là ảnh mờ, bảng phức tạp và tài liệu nhiều cột. Việc giữ đề mục của mẫu chi tiết dựa trên bản chuẩn hóa đã được đối chiếu, duyệt.
- Chọn ND30/HD05 giúp áp dụng cấu hình trình bày đã triển khai; người dùng vẫn cần kiểm tra thông tin cơ quan, thẩm quyền ký và nội dung trước khi sử dụng chính thức.
- Nhận diện người nói và ASR chưa bảo đảm đúng mọi trường hợp; đoạn nói chồng, nhiễu và lời nói không rõ cần rà soát.
- Chưa fine-tune LLM trong đợt cập nhật này. Chưa triển khai ứng dụng Android/iOS; bản hiện tại là web prototype chạy local.

