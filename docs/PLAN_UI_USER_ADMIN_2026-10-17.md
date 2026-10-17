# Đề xuất giao diện người dùng và admin — 17/10/2026

**Trạng thái:** bản nháp để thảo luận, chưa được duyệt triển khai.

Mốc mã nguồn tham chiếu: `75e978b`, nhánh `codex/llm-fcm-minutes`.
Tài liệu này ghi lại yêu cầu mới và các đề xuất. Các mục đề xuất không được
hiểu là chức năng đã có hoặc quyết định người dùng đã chốt.

## 1. Yêu cầu đã xác nhận

- Giao diện chuyên nghiệp hơn, tham khảo phong cách ảnh dashboard người dùng gửi.
- Có hai khu vực riêng: người dùng và admin.
- Phiên bản phục vụ prototype/báo cáo luận văn, chạy local; vẫn cần luồng nghiệp
  vụ hoàn chỉnh, quản lý dữ liệu và xử lý trạng thái thực tế.
- Thảo luận thiết kế, chức năng và kế hoạch trước khi thực hiện.
- Đã chốt trong phản hồi ngày 17/10: đăng nhập và phân quyền thật cho hai khu vực.
- Đã chốt trong phản hồi ngày 17/10: rà soát theo trường/nội dung, đối chiếu
  transcript và preview DOCX; tải DOCX để chỉnh tiếp bằng Word.
- Giữ các yêu cầu nghiệp vụ đã thống nhất: DOCX chỉnh sửa được; biên bản chi tiết
  bảo vệ đề mục; tổng quát chia chủ đề trong vùng nội dung; người dùng chọn
  thể thức hành chính hoặc văn bản Đảng.
- Yêu cầu PDF/ảnh scan từ kế hoạch trước vẫn còn. Backend hiện tại chỉ hỗ trợ
  mẫu DOC/DOCX; cần chốt OCR có thuộc cùng đợt cập nhật này hay không.

## 2. Phân tích ảnh tham khảo

Ảnh là dashboard tài chính theo phong cách tối giản, bề mặt sáng, các khối bo
góc và phân lớp nhẹ. Có thể gọi là phong cách dashboard mềm, thiên về đơn sắc;
không cần sao chép nội dung hay cấu trúc nghiệp vụ tài chính.

| Thành phần trong ảnh | Đặc điểm | Áp dụng vào hệ thống |
| --- | --- | --- |
| Khung ứng dụng | Nền xám lạnh, bề mặt trắng, góc lớn | Khung làm việc thống nhất cho hai khu vực |
| Thanh bên | Hẹp, icon nét mảnh, ít mục | Sidebar có icon và chữ tiếng Việt; có thể thu gọn |
| Thanh trên | Logo, tìm kiếm, thông báo, avatar | Tìm cuộc họp; thông báo xử lý/rà soát; tài khoản |
| Khối nhấn tối | Màu gần đen, nội dung ít | CTA chính hoặc trạng thái cần chú ý |
| Các khối nhỏ | Nền nhạt, số liệu gọn | Cuộc họp đang xử lý, cần rà soát, đã xuất |
| Danh sách trung tâm | Dòng thoáng, chia bằng đường mảnh | Cuộc họp gần đây và tác vụ cần hoàn tất |
| Panel phải | Thông tin bổ trợ tập trung | Checklist rà soát hoặc trạng thái hệ thống |
| Biểu đồ, vòng phần trăm | Hợp nghiệp vụ tài chính của ảnh | Chỉ dùng khi có số đo thật và ý nghĩa rõ |

### Hướng thiết kế đề xuất

- Bản sáng làm hướng chính: nền xám hơi xanh, khối trắng, chữ than, điểm nhấn
  đen/xanh đậm tiết chế. Màu trạng thái đi cùng chữ, không chỉ dựa vào màu.
- Bo góc khoảng 16–24 px, khung lớn khoảng 24–28 px; shadow nhẹ; không dùng
  hiệu ứng nổi lõm mạnh hoặc quá nhiều lớp card lồng nhau.
- Khoảng cách theo nhịp 8/16/24/32 px. Chữ giao diện dễ đọc tiếng Việt, nội dung
  dài khoảng 15–16 px. Tài liệu xem trước dùng font từ DOCX thực tế.
- Sidebar mặc định có nhãn, rộng khoảng 200–220 px trên desktop. Thu gọn được;
  điện thoại dùng menu phù hợp, không ép các cột xuống quá hẹp.
- Một hành động chính cho mỗi màn hình; điều khiển nâng cao nằm trong phần mở
  rộng. Giữ bố cục thoáng cho trang tổng quan; tăng mật độ hợp lý ở trang rà soát.
- Icon, font và tài nguyên giao diện được phục vụ local để demo không phụ thuộc
  kết nối mạng. Có focus bàn phím, nhãn điều khiển, trạng thái loading/disabled.

## 3. Cấu trúc tổng thể và phân quyền

Đề xuất cùng một ứng dụng/backend, hai bộ layout và điều hướng riêng:

```text
Đăng nhập
├── Người dùng: /app
│   ├── Tổng quan
│   ├── Cuộc họp của tôi
│   │   └── Tổng quan / Transcript / Người nói / Biên bản / Lịch sử
│   ├── Mẫu biên bản
│   ├── Hồ sơ giọng
│   └── Cài đặt cá nhân và thùng rác
└── Admin: /admin
    ├── Tổng quan hệ thống
    ├── Tác vụ xử lý
    ├── Tài khoản
    ├── Model và cấu hình
    ├── Mẫu dùng chung
    ├── Nhật ký và dữ liệu
    └── Đánh giá thực nghiệm
```

**Đã chốt:** đăng nhập và phân quyền thật. Đề xuất triển khai hai vai trò `user` và
`admin`. Admin có thể vào không gian
làm việc của chính mình; quyền quản trị không tự biến mọi dữ liệu người dùng
thành dữ liệu riêng của admin.

- Người dùng xem/sửa/tải cuộc họp, mẫu riêng và hồ sơ giọng thuộc quyền của mình.
- Mẫu chung do admin phát hành, người dùng sử dụng bản sao có phiên bản.
- Admin quản lý tài khoản, tác vụ, trạng thái model, cấu hình và nhật ký.
- Chốt rõ quyền admin xem nội dung cuộc họp khi hỗ trợ; ghi lại truy cập/thay đổi.
- Kiểm tra quyền ở API và đường tải file/clip/preview, không chỉ ẩn menu.
- Prototype có thể tạo sẵn tài khoản trình diễn và chức năng đổi mật khẩu;
  chưa cần phụ thuộc email, SSO hoặc dịch vụ bên ngoài.

## 4. Giao diện người dùng

### 4.1. Tổng quan

- Nút chính **Tạo cuộc họp**.
- Số cuộc họp đang xử lý, cần rà soát và đã xuất biên bản; thống nhất định nghĩa
  trước khi tính. “Đã xuất” không đồng nghĩa nội dung đã được người dùng xác nhận.
- Cuộc họp gần đây: tên, ngày họp, số nguồn, trạng thái, lần cập nhật, thao tác tiếp tục.
- Panel “Việc cần hoàn tất”: tên người nói chưa rõ, trường chưa có căn cứ, biên
  bản cần tạo lại sau khi transcript/danh tính thay đổi.
- Tìm kiếm, lọc theo trạng thái/ngày, sắp xếp; thông báo hoàn tất và lỗi ngay trong app.
- Thống kê lấy từ dữ liệu thật; không có biểu đồ trang trí hay “độ chính xác AI” tự suy ra.

### 4.2. Tạo cuộc họp

Wizard đề xuất:

1. **Thông tin:** tên, ngày/địa điểm nếu người dùng biết, ghi chú tùy chọn.
2. **Người tham gia:** chọn/tạo hồ sơ giọng hoặc bỏ qua enrollment; cho biết hồ
   sơ nào chưa đủ mẫu. Các thông tin nhập tay có nguồn riêng với nội dung ASR.
3. **Nguồn âm thanh:** 1–8 file theo giới hạn hiện tại; hiển thị tên, thời lượng,
   dung lượng, kết quả kiểm tra; đặt tên mic/thiết bị, bỏ file sai.
4. **Biên bản và xác nhận:** chọn mẫu riêng/mẫu chung, chi tiết/tổng quát, thể
   thức, metadata; cho phép chỉ tạo transcript rồi thêm mẫu sau.

Người dùng chọn chế độ nghiệp vụ. Phương pháp MFCC/ECAPA, F1/F3/F5, ngưỡng và
tham số FCM chuyển sang cấu hình quản trị/thực nghiệm. Tác vụ lưu preset/version
đã chọn để có thể tra cứu phương pháp thực tế sau này.

### 4.3. Theo dõi xử lý

- Các bước thực: kiểm tra tệp → đồng bộ → tách lượt/chép lời → dung hợp và gán
  người nói → tạo biên bản → định dạng/xem trước.
- Các bước thực tế có thể dùng chung model hoặc thực hiện kết hợp; trạng thái
  giao diện phải lấy từ sự kiện backend, không mô phỏng thứ tự đã xử lý.
- Hiển thị queued/running/failed/completed và bước hiện tại; phần trăm chỉ dùng
  khi có mẫu số/số đơn vị hoàn tất thật. Thời gian chờ dự kiến cần có cơ sở đo.
- Rời trang và mở lại vẫn theo dõi được. Lỗi chỉ rõ bước nào, đầu ra nào đã có,
  hướng khắc phục và cách tạo lượt thử lại.
- Hủy tác vụ đang chờ là mục tiêu ban đầu; hủy tác vụ đang chạy cần cơ chế dừng
  an toàn ở backend. Không gắn nút hủy chỉ để đóng giao diện.

### 4.4. Không gian một cuộc họp

**Tab Tổng quan:** metadata, người tham gia, nguồn ghi, trạng thái xử lý, trạng
thái rà soát và các file xuất hiện có.

**Tab Transcript:**

- Player nghe, timeline theo thời gian/người nói, tìm kiếm và lọc cần kiểm tra.
- Chọn đoạn để nghe clip có ngữ cảnh; đổi nguồn để đối chiếu nếu có.
- Xem transcript gốc và sửa tay; lưu khác biệt, người sửa và revision.
- Dữ liệu nguồn/confidence chi tiết mở theo yêu cầu. Diễn giải điểm model rõ
  ràng; không biểu diễn cosine/membership như xác suất đúng.
- Waveform và phát theo từ có thể thêm nếu timestamp đủ tin cậy; không để
  chuyển động player tạo cảm giác timestamp chính xác hơn dữ liệu thực tế.

**Tab Người nói:**

- Danh sách người tham gia và nhãn trong cuộc họp; đổi tên/ánh xạ hồ sơ bằng
  thao tác rõ ràng, có lịch sử. Gộp/tách người nói cần API chuyên biệt nếu bổ sung.
- Phân biệt đã xác định, người lạ và chưa xác định. Nói chồng là trạng thái
  đoạn âm thanh, không phải một người trong danh sách thành phần tham dự.
- Thay đổi danh tính phải cập nhật trạng thái phụ thuộc của biên bản.

**Tab Biên bản — màn hình trọng tâm:**

- Hai vùng chính: dữ liệu/nội dung cần điền và bản xem trước DOCX; căn cứ
  transcript/clip mở ở panel phụ. Có thể đổi tỷ lệ/thu gọn trên laptop.
- Chọn trường làm nổi vùng tương ứng trong bản xem trước nếu có ánh xạ; ngay
  cạnh là căn cứ và trạng thái cần rà soát/đã được người dùng xác nhận.
- Chi tiết: bảo vệ đề mục và phạm vi ngoài vùng cho phép sửa.
- Tổng quát: chỉnh câu và tên chủ đề bên trong vùng nội dung. Nếu cho gộp/tách/
  sắp xếp nhóm thủ công, phải bảo toàn liên kết ý nguồn và có hoàn tác/lịch sử.
- Metadata, ngày họp và ngày ban hành được tách rõ; không tự điền suy đoán.
- Đổi thể thức dùng facts đang có, không chạy lại ASR. Tạo lại nội dung phải
  báo ảnh hưởng tới phần người dùng đã sửa và giữ được các sửa hợp lệ.
- Có saved/unsaved/saving/error/stale; tải phiên bản cũ phải hiện rõ khi biên
  bản chưa phản ánh transcript/danh tính mới.
- DOCX là đầu ra chính. ZIP/bằng chứng là lựa chọn phụ. Bản xem trước lấy từ
  DOCX được xuất; không dùng một trang HTML gần giống để thay cho preview thật.

**Đã chốt:** prototype dùng biên tập theo trường và nội dung kèm đối chiếu
transcript và preview, rồi tải DOCX để sửa tiếp bằng Word. Trình soạn thảo tài
liệu giống Word trên web không thuộc phạm vi đã chọn trong đợt này.

**Tab Lịch sử:** các lần chạy, revision transcript/facts/danh tính, đổi mẫu,
đổi thể thức, người sửa và file xuất tương ứng; mở/so sánh phiên bản trước.
Khôi phục tạo revision mới để không làm mất lịch sử.

### 4.5. Thư viện mẫu và hồ sơ giọng

- Mẫu riêng/mẫu dùng chung: tải DOC/DOCX, xem trước, tên/loại mẫu, chọn chi
  tiết/tổng quát, kiểm tra đề mục và trường, phiên bản, lưu trữ hoặc bỏ sử dụng.
- Mẫu nhiều vùng nội dung cần chọn rõ `content_field_id`; khôi phục đúng lựa
  chọn đã lưu khi mở lại. Không yêu cầu người dùng sửa schema JSON trực tiếp.
- Hồ sơ giọng: xem/tạo/bổ sung mẫu, thông tin người tham gia, trạng thái mẫu;
  xử lý quyền sở hữu và xóa/lưu trữ. Đăng ký được không đồng nghĩa chắc chắn
  nhận diện đúng; phản hồi cần dựa vào kiểm tra thật.
- Thùng rác có khôi phục; xóa vĩnh viễn là thao tác riêng. Không tự đặt lịch
  xóa dữ liệu khi người dùng chưa chọn chính sách.

## 5. Giao diện admin

| Màn hình | Chức năng chính | Phạm vi prototype đề xuất |
| --- | --- | --- |
| Tổng quan | Tác vụ đang chạy/chờ/lỗi, dung lượng, cache model, sự kiện mới | Bắt buộc |
| Tài khoản | Tạo, khóa/mở, đổi vai trò, đặt lại mật khẩu, dữ liệu sở hữu | Bắt buộc nếu chọn phân quyền thật |
| Tác vụ | Xem giai đoạn, log, cấu hình đã chốt, lỗi, thử lại bằng lượt mới | Bắt buộc |
| Model | ID/revision/runtime, trọng số đã lưu, đang load/chạy/lỗi | Bắt buộc |
| Cấu hình | Preset mặc định, giới hạn upload, phương pháp pipeline; version | Bắt buộc ở mức preset đã kiểm tra |
| Mẫu chung | Đăng mẫu, xem trước, duyệt schema, phát hành phiên bản, lưu trữ | Bắt buộc |
| Nhật ký/dữ liệu | Ai sửa gì, lỗi, sao lưu/khôi phục có kiểm tra, dung lượng | Bắt buộc ở mức cơ bản |
| Đánh giá thực nghiệm | So sánh pipeline/model/config bằng tập kiểm thử | Rất phù hợp luận văn; sau luồng chính |

### Nguyên tắc quản trị

- Không mở hàng loạt tham số thô trong trang đầu. Dùng preset và phần nâng cao
  có kiểm tra hợp lệ; cấu hình mới không đổi tác vụ đang chạy.
- Trạng thái đã cache khác với đã load vào RAM hoặc đang suy luận. Kiểm tra
  health thông thường không làm tải model nặng vào RAM.
- Điều phối tài nguyên chung giữa ASR và LLM trên máy 16 GB; tránh để hai hàng
  đợi riêng tự chạy model nặng đồng thời. Cần kiểm tra scheduler thực tế trước
  khi thêm retry/cancel hoặc xử lý nhiều người dùng.
- Log hiển thị thông tin cần chẩn đoán, không hiển thị token, mật khẩu hay bí
  mật từ môi trường. Lưu audit hành động quản trị và thay đổi cấu hình.
- Tác vụ lỗi/khởi động lại không để UI báo chạy mãi; giữ kết quả một phần nếu
  hợp lệ và cho biết phần nào dùng được. Không hứa resume giữa chừng khi chưa có checkpoint.
- Bộ đo đánh giá: WER/CER khi có transcript tham chiếu; metric diarization/
  identity khi có nhãn; silhouette/stability cho FCM; thời gian và bộ nhớ theo
  phép đo. Thiếu ground truth thì ghi “chưa có dữ liệu đánh giá”.
- Giữ dữ liệu thực nghiệm tách khỏi cuộc họp nghiệp vụ; lưu dataset/config/
  model revision/Git revision để kết quả có thể tra lại.

## 6. Chức năng hiện có và phần phải bổ sung

| Khả năng | Hiện trạng đã đối chiếu mã | Công việc cho phiên bản mới |
| --- | --- | --- |
| Upload nhiều nguồn, enrollment, ASR/fusion | Có | Tổ chức luồng wizard; ownership, validation UX |
| Lịch sử kết quả | Danh sách job JSON và dò thư mục run | Danh sách theo người dùng, lọc/phân trang, meeting/run rõ ràng |
| Nghe clip, tìm/lọc transcript, đổi tên/sửa text | Có | Đồng bộ revision, lưu an toàn, bố cục rà soát |
| Word, LLM/E5/FCM, hai thể thức, DOCX/ZIP/preview | Có | Sửa lỗi lưu/xuất, cải thiện trình bày và truy vết |
| Thư viện mẫu tái sử dụng | Mẫu gắn với từng run | Registry mẫu riêng/chung và version |
| Tài khoản và phân quyền | Chưa có | Users, sessions, role, ACL cho mọi tài nguyên |
| Tiến độ theo giai đoạn | Job chỉ có queued/running/succeeded/failed | Sự kiện stage/unit, heartbeat, error state |
| Lịch sử phiên bản/hoàn tác đầy đủ | Có một số dấu vết rời rạc | Revision và snapshot nhất quán, xung đột khi lưu |
| Hủy, retry, sao lưu qua UI | Chưa có luồng quản trị hoàn chỉnh | API và cơ chế an toàn tương ứng |
| PDF/scan/OCR | Chưa triển khai | Pipeline đọc/tái dựng DOCX và màn hình kiểm tra OCR |
| Soạn thảo tài liệu như Word trên web | Chưa có | Hạng mục riêng nếu người dùng yêu cầu |

Backend hiện tại không có bảng users/role/session; mọi job/profile đang được
liệt kê chung. `DemoJobs` dò các run chưa đăng ký, nên khi thêm phân quyền phải
gán quyền dữ liệu cũ theo quy tắc rõ ràng, không tự đưa mọi run cho mọi tài khoản.
Không đồng nhất `job_id`, `run_id` và `meeting_id` trong thiết kế mới.

## 7. Thứ tự triển khai đề xuất sau khi chốt

### Giai đoạn A — Chốt thiết kế và luồng

- Chốt sitemap, style tokens, quyền user/admin và các trạng thái màn hình.
- Wireframe trang tổng quan, wizard, workspace, mẫu, hồ sơ giọng và admin.
- Chốt mức editor, phạm vi OCR, tiêu chí nghiệm thu và dữ liệu trình diễn.

### Giai đoạn B — Ổn định dữ liệu và API

- Sửa bốn lỗi đã tái hiện trong
  [báo cáo trước UI](/Users/thien/Documents/School/Luận văn/docs/reports/SYSTEM_PRE_UI_AUDIT_2026-10-17.md).
- Thống nhất cập nhật facts, schema, danh tính, renderer, định dạng, preview,
  manifest và ZIP; có revision, khóa và rollback bao phủ toàn thao tác.
- Bổ sung kiểm thử: lưu không đổi không mất evidence; sửa một trường không
  đổi các trường khác; request bị từ chối không ghi; mọi export cùng phiên bản.

### Giai đoạn C — Nền ứng dụng và người dùng

- Giữ FastAPI và pipeline hiện có. Đề xuất bước đầu dùng Jinja/CSS/JavaScript
  được tách module/component, thay layout và các trang; chưa bắt buộc thêm một
  frontend framework hay dịch vụ ngoài để đạt phong cách ảnh.
- Tách router/service khỏi `web/app.py` đang tập trung nhiều trách nhiệm.
- Nếu chốt auth: migration SQLite, tài khoản local, session, kiểm tra quyền,
  sở hữu tài nguyên, xử lý dữ liệu legacy; thêm kiểm thử hai tài khoản khác nhau.
- Xây dashboard, danh sách, wizard, theo dõi xử lý và workspace; phiên bản hóa
  mẫu/facts/exports; bảo toàn dữ liệu hiện có qua migration.

### Giai đoạn D — Admin và khả năng vận hành

- Tài khoản, jobs, cache/model, preset, mẫu chung, nhật ký, sao lưu cơ bản.
- Gắn stage events và điều phối tài nguyên; thử retry/hủy theo khả năng thực.
- Thêm màn hình thực nghiệm khi luồng nghiệp vụ đã ổn định.

### Giai đoạn E — Nghiệm thu prototype

- Một cuộc họp chạy từ upload đến DOCX; cả chi tiết và tổng quát; cả hai thể thức.
- Rà soát, sửa, đổi tên, tạo lại và tải tài liệu đúng phiên bản; giữ ý và đề mục.
- Thử file không hợp lệ, nguồn thiếu, nói chồng/chưa rõ người, model bận, model
  chưa cache, render lỗi, reload trang, tác vụ thất bại và khởi động lại.
- User A không đọc/sửa/tải tài nguyên user B qua URL/API trực tiếp; admin đúng quyền.
- Kiểm tra trình duyệt ở laptop và màn hình hẹp; keyboard, tiếng Việt, player,
  trạng thái trống/loading/error/saved/stale và tránh cuộn ngang toàn trang.
- Tài khoản/dữ liệu demo được đánh dấu, commit từng giai đoạn, tài liệu hướng
  dẫn và kịch bản trình bày luận văn.

## 8. Các điểm còn thảo luận

1. **Auth — đã chốt:** đăng nhập/phân quyền thật. Cần tiếp tục chốt chi tiết
   quyền sở hữu dữ liệu, quyền admin hỗ trợ và cách gán các run cũ.
2. **Editor — đã chốt:** rà soát theo trường/nội dung, đối chiếu transcript,
   preview DOCX và tải về để sửa tiếp bằng Word.
3. **PDF/scan:** triển khai OCR trong cùng phiên bản hay là giai đoạn tiếp theo?
   Dù chọn thời điểm nào, không quảng bá upload hỗ trợ khi backend chưa làm được.
4. **Nghiên cứu:** trang đánh giá thực nghiệm có thuộc đợt đầu hay làm sau
   dashboard/workspace/admin cơ bản?
5. **Nhận diện sản phẩm:** tên chính thức, logo và màu nhấn. Mockup thảo luận
   dùng tên tạm `Meeting / Notes`, các số liệu minh họa, không phải dashboard thật.

Phác thảo minh họa chỉ phục vụ thảo luận bố cục; không kết nối API và không thay
giao diện hệ thống đang có. Server web chính tiếp tục giữ trạng thái tắt.
