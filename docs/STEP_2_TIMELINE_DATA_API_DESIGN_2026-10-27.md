# Bước 2 — dữ liệu và thao tác cho timeline nhiều nguồn

Ngày: 27/10/2026. Trạng thái: **đã triển khai nền dữ liệu, API và hàm gọi từ giao diện; chưa dựng giao diện kéo thả**. Các mục thiết kế bên dưới là cơ sở; chi tiết hợp đồng hiện hành và phạm vi đã kiểm xem [báo cáo triển khai](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/STEP_1_2_IMPLEMENTATION_2026-10-27.md>).

Cập nhật sau bước 3: bố cục nhiều file/vùng cắt/mốc đã có bộ xử lý. `GET timeline` trả thêm `last_alignment` và `alignment_stale`; client có `getTimelineAlignment` để đọc ánh xạ từng đoạn. `resolved_positions` vẫn là vị trí suy từ khai báo, còn vị trí sau đối chiếu âm thanh nằm trong báo cáo căn thời gian. Xem [hợp đồng và kết quả bước 3](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/STEP_3_IMPLEMENTATION_2026-10-27.md>).

Mục tiêu: khi dựng giao diện tải file sau này, có thể hiển thị mỗi nguồn một hàng, nhiều phần audio nối tiếp trên hàng đó, kéo thả để đổi thứ tự/vị trí và chuyển nguồn. Bước 2 cần xây nền dữ liệu và thao tác cập nhật; giao diện timeline hoàn chỉnh làm sau. Phạm vi không gồm xử lý nhiều người nói đồng thời.

## 1. Các quyết định thiết kế

1. **Nguồn ghi khác file.** Một nguồn có nhiều file nối tiếp. Hàng timeline biểu diễn một thiết bị/luồng ghi theo khai báo, không phải một người nói. Người tải file cũng không tự động là thiết bị ghi hay người nói.
2. **Đoạn trên timeline khác file gốc.** Mỗi đoạn có mã ổn định và tham chiếu file/vùng audio gốc. Kéo thả chỉ đổi bố trí; không nối, cắt hoặc ghi đè file gốc. Một file có thể được tham chiếu bởi nhiều đoạn khi cần mô tả pause trong cùng file.
3. **Thứ tự khác thời gian.** Thứ tự trước/sau có thể đã biết trong khi khoảng nghỉ còn chưa rõ. Không tự coi xếp sát nhau trên màn hình là không có khoảng mất thời gian.
4. **Phiên họp/giải lao độc lập với hàng và file.** Một nguồn có thể ghi xuyên giờ nghỉ; một phiên có thể liên quan nhiều phần ghi từ nhiều nguồn.
5. **Mốc do người dùng đặt có nguồn gốc rõ.** Mốc kéo thả được ghi là bố trí do người dùng đặt, không phải mốc đã được âm thanh xác nhận. Kết quả tự động ở bước 3 phải là đề xuất có căn cứ và không âm thầm ghi đè mốc thủ công.

## 2. Mô hình dữ liệu cần chuẩn bị

Các trường dưới đây đã có hợp đồng trong backend và kiểu dữ liệu giao diện. Thời gian giao diện dùng mili giây nguyên, có gốc tương đối của cuộc họp; giờ thực có múi giờ được lưu riêng qua `clock_origin` nếu biết. Căn chính xác theo mẫu âm thanh ở bước 3 dùng ánh xạ riêng, không bị giới hạn bởi cách vẽ giao diện.

| Thành phần | Thông tin chính | Mục đích |
| --- | --- | --- |
| File audio (`asset`) | ID, tên, file/hash gốc, URL nghe, thời lượng, thông tin định dạng | Nguồn dữ liệu bất biến; tái sử dụng kho file hiện có |
| Hàng nguồn (`track`) | ID, tên hiển thị, thiết bị/luồng nếu biết, danh sách `clip_ids` có thứ tự | Nhiều file có thể nằm trên cùng hàng; thứ tự danh sách là nguồn thứ tự duy nhất |
| Đoạn trên timeline (`clip`) | ID, `asset_id`, vùng audio gốc, cách đặt thời gian, nguồn gốc mốc | Một khối để kéo thả; đổi thứ tự không đổi ID |
| Kho file chưa xếp | Danh sách file chưa được đặt vào hàng | Tải lên được trước khi biết nguồn/thứ tự; không gán mọi file vào cùng thời gian |
| Phiên/giải lao (`interval`) | ID, loại, nhãn, mốc đã biết hoặc liên kết ranh giới, trạng thái xác nhận | Quản lý nội dung cuộc họp, không suy từ VAD hoặc số file |
| Bố cục (`timeline`) | Phiên bản schema, các hàng/đoạn/kho chưa xếp/các khoảng | Đọc lại đầy đủ bố cục và cập nhật đồng bộ |

`source_ids` hiện tại đang chỉ tới các file tải lên. Khi triển khai, giữ nguyên ID và ý nghĩa lịch sử này để tương thích; thêm lớp hàng/đoạn ở trên, không đổi các ID cũ thành ID thiết bị.

Vùng audio của đoạn ban đầu là toàn file. Có thể dự trù `source_in_ms`/`source_out_ms` để hỗ trợ một file có nhiều khoảng capture; bước 2 không bắt buộc cung cấp giao diện cắt audio hoặc tự phát hiện pause. Nếu thời lượng mới chỉ là ước tính từ metadata, cần giữ trạng thái đó và kiểm lại trước khi xử lý chính xác.

### Cách đặt thời gian của một đoạn

Mỗi đoạn chỉ có **một** cách đặt làm căn cứ tại một thời điểm:

- **Có mốc (`anchored`):** `start_ms`, nguồn gốc mốc (`user`, `capture_log`, `audio_match`) và trạng thái xác nhận. Đây là vị trí so với gốc timeline đã khai báo, chưa tự chứng minh giờ thực.
- **Theo phần trước (`sequential`):** khoảng cách `gap_before_ms` bằng một số không âm, hoặc `null` khi chưa biết. `0` chỉ dùng khi được khai báo/xác nhận là nối liền. Đoạn đầu của hàng chưa có mốc cũng có thể ở trạng thái này, với gốc cục bộ chưa nối vào đồng hồ chung.

Ví dụ: phần 1 dài 30 phút; phần 2 đứng sau phần 1, `gap_before_ms=null`. Hệ thống biết thứ tự nhưng chưa biết phần 2 bắt đầu ở phút 30, 45 hay thời điểm khác. Giao diện có thể xếp các khối để thao tác, nhưng phải có dấu khoảng chưa rõ và không ghi vị trí vẽ tạm thành mốc thời gian.

Không lưu đồng thời thứ tự bằng cả chỉ số `order` và danh sách ID rồi để chúng mâu thuẫn. Vị trí tính được từ phần trước là giá trị suy ra, không phải một mốc độc lập để ghi đè qua lại. Vùng chưa nối được vào đồng hồ chung vẫn có thứ tự và thời gian cục bộ.

Khoảng cách đã xác nhận phải kèm cặp đoạn làm căn cứ trong thông tin nguồn gốc. Khi đổi thứ tự làm thay đổi đoạn đứng trước, không áp dụng khoảng cách cũ cho cặp mới: giữ căn cứ lịch sử và chuyển quan hệ mới sang cần rà/chưa biết, trừ khi thao tác đã cung cấp mốc hoặc khoảng cách thay thế rõ ràng.

## 3. Các thao tác giao diện cần dùng được

| Thao tác sau này | Thay đổi dữ liệu ở bước 2 cần hỗ trợ |
| --- | --- |
| Tải nhiều file vào một hàng đã chọn | Giữ file gốc; tạo các đoạn theo thứ tự người dùng chọn, khoảng cách chưa rõ nếu chưa xác nhận |
| Tải file chưa biết thuộc nguồn nào | Đưa vào kho chưa xếp; không đoán tất cả cùng thời gian hoặc cùng thiết bị |
| Kéo đổi thứ tự trong hàng | Di chuyển ID đoạn trước/sau ID đích; giữ nguyên file/vùng audio và các khoảng đã có căn cứ; kiểm mâu thuẫn với mốc cố định |
| Kéo theo trục thời gian | Cập nhật mốc tương đối hoặc khoảng cách do người dùng đặt, giữ nguồn gốc mốc; có thể bắt dính vào cuối đoạn trước |
| Kéo sang hàng khác | Chuyển tham chiếu đoạn giữa hai hàng trong một cập nhật; không đổi người tải lên hoặc thông tin file gốc |
| Đổi tên/sắp thứ tự hàng | Cập nhật trình bày; không thay đổi nội dung audio hay danh tính người nói |
| Bỏ đoạn khỏi bố cục | Bỏ tham chiếu sử dụng; không mặc định xóa file gốc |
| Xác nhận/đổi khoảng nghỉ | Lưu khoảng và căn cứ đã nhập; không đồng nhất giải lao với thiếu audio ở mọi nguồn |

Khi di chuyển qua một mốc đã biết, hệ thống phải trả rõ xung đột hoặc áp dụng ý định đổi mốc được gửi kèm; không âm thầm dịch mọi đoạn có mốc. Không xóa các khoảng đã biết chỉ để xếp khít. Nếu thời gian các phần trong cùng hàng mâu thuẫn, phản hồi để giao diện chỉ ra và cho sửa; không tự trộn audio. Những hàng khác nhau có thể ghi cùng một khoảng thời gian bình thường.

Giao diện lưu khi kết thúc thao tác kéo, không bắt buộc gửi từng điểm con trỏ. Mã đoạn ổn định và cập nhật theo phiên bản cũng tạo nền cho hoàn tác sau này, nhưng lịch sử hoàn tác đầy đủ không phải yêu cầu phải làm ngay ở bước 2.

## 4. Hợp đồng đọc/cập nhật cho giao diện

Đã có hai đường truy cập:

- `GET /meetings/{id}/timeline`: trả `schema_version`, revision hiện hành của cuộc họp và toàn bộ bố cục, kèm thông tin file tối thiểu để vẽ/nghe.
- `PATCH /meetings/{id}/timeline`: nhận revision đã đọc và một nhóm thao tác có cấu trúc như tạo hàng, thêm đoạn, chuyển đoạn, đặt mốc, cập nhật khoảng nghỉ. Chỉ lưu nếu toàn bộ nhóm hợp lệ.

Tái sử dụng cơ chế revision/quyền sửa cuộc họp hiện tại. Một thao tác chuyển hàng phải lưu cả việc bỏ ở hàng cũ và thêm ở hàng mới trong cùng lần cập nhật nguyên tử. Bố cục có thể lưu trong một tài liệu cuộc họp để áp dụng cơ chế này; nếu tách kho lưu, phải giữ nguyên bảo đảm nguyên tử. Không đặt yêu cầu triển khai phải phụ thuộc giao dịch nhiều tài liệu khi chưa kiểm môi trường MongoDB.

Backend phải kiểm file/đoạn thuộc đúng cuộc họp và người có quyền; ID tồn tại, không bị đặt lặp ngoài ý định; vùng audio hợp lệ; giá trị thời gian hợp lệ và bố cục không mâu thuẫn. Thao tác từ revision cũ bị từ chối rõ, không ghi đè dữ liệu mới. Không nhận đường dẫn file tùy ý từ giao diện.

Thay đổi thứ tự/vị trí/vùng audio/nguồn làm tăng phiên bản nội dung và khiến kết quả transcript/biên bản cũ cần cập nhật. Đổi màu, tên hiển thị hoặc thứ tự trình bày các hàng không tự buộc chạy lại ASR. Khi xử lý, job dùng một bản chụp bố cục với ID/hash; chưa cho sửa bố cục nội dung khi job đang chạy nếu chưa có cơ chế tách phiên bản phù hợp. Cách này giữ nhất quán với quy tắc khóa sửa hiện tại.

Tách giới hạn số nguồn/thiết bị khỏi giới hạn số file, đồng thời vẫn có giới hạn dung lượng/số đoạn hợp lý. Đường xử lý hiện tại còn giới hạn theo số file; cần cập nhật đồng bộ hợp đồng đầu vào pipeline, không chỉ nới giới hạn ở API.

Thông tin thời lượng, URL nghe và vùng audio đủ cho giao diện cơ bản. Dữ liệu hình sóng có thể bổ sung dưới dạng tài nguyên theo file, dùng lại giữa các đoạn; không đưa toàn waveform vào bố cục hoặc buộc chọn thư viện timeline ngay bây giờ.

## 5. Liên kết với đồng bộ và xử lý dài

Pipeline cần đọc bố cục để phân biệt nhiều phần của một nguồn với nhiều nguồn cùng ghi, giữ các khoảng chưa rõ và tham chiếu về file/vùng audio gốc. Không truyền danh sách file phẳng như thể tất cả là micro đồng thời. Nếu chưa triển khai được cách xử lý bố cục mới, phải báo tình huống chưa hỗ trợ thay vì âm thầm chạy đường cũ.

Bước 3 bổ sung các mốc và ánh xạ thời gian từ âm thanh. Thời gian nội dung transcript được suy từ vùng nguồn và ánh xạ đã chấp nhận; không dùng tọa độ màn hình. Bước 4 đọc vùng audio theo nhu cầu; không bắt buộc nối vật lý các file thành WAV lớn để phục vụ timeline.

Cuộc họp cũ thiếu bố cục không bị tự gán các file nối tiếp. Khi chuyển đổi, có thể biểu diễn mỗi file bằng một hàng tạm theo cách chúng từng được xử lý, đánh dấu quan hệ thời gian chưa xác nhận. Giữ kết quả lịch sử và yêu cầu rà trước khi xử lý lại theo bố cục mới.

## 6. Điều kiện hoàn thành bước 2

- [x] Một hàng chứa được nhiều file; nhiều hàng biểu diễn các nguồn ghi khác nhau.
- [x] Đọc → đổi thứ tự/chuyển hàng/đổi vị trí → lưu → đọc lại cho cùng bố cục và ID đoạn.
- [x] Hợp đồng phân biệt nguồn gốc mốc; thao tác nhập tay không được tự nhận là mốc đã xác minh. Việc nhập nhật ký/tìm mốc âm thanh còn ở bước tiếp theo.
- [x] Khoảng chưa biết giữ `null`, không biến thành 0 hoặc thành im lặng đã được ghi.
- [x] Một file có thể liên kết nhiều phiên; các khoảng được lưu độc lập, chưa tự động lọc nội dung.
- [x] Thao tác bố cục không sửa/xóa file gốc; thay đổi mốc có lịch sử và ghi nhận đối chiếu.
- [x] Chuyển hàng cập nhật nguyên tử; revision cũ hoặc tham chiếu ngoài quyền bị từ chối; đã thử hai yêu cầu lưu đồng thời.
- [x] Thay đổi bố cục nội dung đánh dấu kết quả cũ cần cập nhật; chỉnh tên/thứ tự trình bày hàng không làm đổi phiên bản nội dung.
- [x] Cuộc họp cũ được biểu diễn mà không ghi đổi khi đọc; API và worker cùng chặn bố cục chưa xử lý được, không đưa file nối tiếp vào đường xử lý song song.

Không cần dựng giao diện kéo thả hoàn chỉnh để nghiệm thu nền dữ liệu. Nhưng cần ví dụ dữ liệu nhiều hàng, nhiều phần ghi, khoảng chưa biết và kiểm các thao tác đọc/lưu để xác nhận giao diện sau này có thể dùng trực tiếp.

Liên quan: [kế hoạch tổng](</Users/thien/Documents/School/Luận văn/web_app/docs/PLAN_LONG_MEETINGS_PAUSE_RESUME_2026-10-27.md>).
