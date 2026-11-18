# Minda — tổ chức giao diện, nội dung và hiệu ứng Three.js

Ngày: 27/10/2026. Nghiên cứu tiếp theo của [khảo sát frontend](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/FRONTEND_UX_RESEARCH_2026-10-27.md>). Yêu cầu đã chốt: **giữ màu Minda hiện tại**, nâng cấp cách chia khu vực, bố trí chữ, giảm thông tin không giúp hoàn thành công việc; khảo sát thêm Three.js. Lượt này không thay mã ứng dụng hoặc cài dependency mới vào frontend.

## 1. Kết luận thiết kế

Minda nên tổ chức quanh ba công việc: **chuẩn bị nguồn → rà lời chép → hoàn thiện biên bản**. Điều hướng, tiêu đề, thanh công cụ và nội dung phải thể hiện rõ đang làm việc nào. Dành diện tích lớn nhất cho dữ liệu người dùng đang đọc hoặc sửa.

Mỗi thông tin cần có một lý do xuất hiện: giúp định vị, chọn việc, thực hiện, phát hiện vấn đề hoặc khôi phục sau lỗi. Lời chào, khẩu hiệu, mô tả lặp và thông số kỹ thuật có thể chuyển khỏi vùng làm việc. Các cảnh báo thiếu căn cứ, thời gian chưa rõ, chưa lưu và kết quả đã cũ vẫn cần hiện khi liên quan.

Three.js phù hợp cho một điểm nhấn nhận diện nhỏ ở trang đăng nhập/giới thiệu: logo có chiều sâu hoặc dải nét chuyển động ngắn theo bảng màu cũ. Transcript, biên bản, bảng quản trị và timeline thao tác ưu tiên nền yên, phản hồi gọn. Ưu tiên đầu tư theo thứ tự: **cấu trúc thông tin → chữ/nội dung → thao tác → hiệu ứng**.

Các bố cục, cỡ chữ và thời lượng chuyển động bên dưới là đề xuất để thử với Minda, chưa phải số đo tối ưu hoặc kết quả thử người dùng.

## 2. Căn cứ nghiên cứu

| Nguồn chính thức | Ý rút ra | Áp dụng cho Minda |
| --- | --- | --- |
| [NN/G — Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/) | Chức năng chuyên sâu/ít dùng có thể mở khi cần | Đưa cấu hình model, xuất gói căn cứ, log chi tiết vào khu vực phù hợp; giữ thao tác chính và cảnh báo ảnh hưởng quyết định ở ngoài. |
| [NN/G — Layer-Cake Scanning](https://www.nngroup.com/articles/layer-cake-pattern-scanning/) | Tiêu đề mô tả và phân nhóm rõ giúp tìm đúng phần | Nhóm theo công việc, tên đề mục rõ; tránh nhiều nhãn phụ viết hoa cùng nhắc lại một ý. Đây là quan sát hành vi đọc, không phải khuôn bắt buộc cho mọi màn hình. |
| [USWDS — Typography](https://designsystem.digital.gov/components/typography/) | Độ dài dòng, căn lề và khoảng dòng ảnh hưởng việc đọc | Khống chế chiều rộng văn bản; nội dung sửa trên web căn trái; preview DOCX giữ định dạng tài liệu. |
| [Carbon — Content](https://www.carbondesignsystem.com/building-blocks/foundations/content) | Nội dung giao diện có mục đích, nhất quán và hỗ trợ hành động | Một thuật ngữ cho một khái niệm, nhãn cụ thể; tiêu đề theo sentence case, diễn đạt lỗi bằng ngôn ngữ người dùng. |
| [W3C — Pause, Stop, Hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html) | Chuyển động tự khởi chạy trên 5 giây, hiện song song với nội dung, cần cơ chế dừng/ẩn/tạm dừng trừ ngoại lệ | Hiệu ứng nhận diện không chạy vô hạn cạnh form hoặc văn bản; cho điều khiển và bản tĩnh. Đây là tiêu chí mức A. |
| [MDN — prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion) | Có thể tôn trọng lựa chọn giảm chuyển động của hệ điều hành | Mặc định dùng bản tĩnh khi được yêu cầu; không dùng zoom/parallax lớn trên vùng làm việc. |

Đã đọc mã hiện tại của shell, dashboard/danh sách, form tạo họp, workspace, transcript và các vùng thao tác biên bản. Các nhận xét về nội dung dưới đây có thể đối chiếu chuỗi trong mã; chưa chạy lại kiểm thử giao diện production trong lượt này.

## 3. Phân chia ứng dụng rõ hơn

### Tầng toàn ứng dụng

Sidebar chia thành các nhóm có ý nghĩa:

- **Công việc:** Tổng quan, Cuộc họp.
- **Tài nguyên:** Mẫu biên bản, Hồ sơ giọng.
- **Tài khoản:** Thiết lập; Thùng rác và thao tác tài khoản ở vùng phụ vẫn truy cập được.
- **Quản trị hệ thống:** lối vào riêng theo quyền; tài khoản, tác vụ, cấu hình, sao lưu, nhật ký thuộc khu vực này.

Giữ một cơ chế tìm cuộc họp rõ ràng. Trên trang danh sách, thanh tìm kiếm/lọc là của danh sách; khi vào một cuộc họp, tìm trong lời chép là thao tác cục bộ và phải ghi rõ phạm vi. Không đặt hai ô tìm cùng phạm vi cạnh nhau.

Ngày hiện tại không cần chiếm vị trí cố định ở mọi trang. Thông tin phiên bản và “Không gian cục bộ” chuyển vào Thiết lập/Giới thiệu; nếu trạng thái vận hành thực sự ngăn xử lý, hiện thông báo ngay tại hành động đó.

### Tầng trong một cuộc họp

Một header gọn gồm lối về danh sách, tên cuộc họp, metadata cần thiết và trạng thái. Tiếp theo là điều hướng cục bộ:

**Nguồn âm thanh · Lời chép · Biên bản · Lịch sử**

Người nói nằm trong ngữ cảnh rà lời chép, có chế độ xem riêng khi cần. Thông tin cuộc họp có thể mở từ header hoặc mục Tổng quan nếu còn tác vụ độc lập cần quản lý. Giữ một mục Tổng quan chỉ khi nó giúp người dùng kiểm đầu vào/tiến độ; không lặp nguyên dashboard hoặc toàn bộ các tab khác.

Các mục này là khu vực làm việc có thể quay lại. Trạng thái điều kiện được thể hiện khi dữ liệu chưa sẵn sàng; không khóa cứng bằng một wizard tuyến tính sau khi đã có cuộc họp.

### Tầng của một màn hình

| Khu vực | Nội dung | Quy tắc |
| --- | --- | --- |
| Header | Tên đối tượng/công việc, trạng thái và metadata quan trọng | Tránh đồng thời breadcrumb, nhãn viết hoa và tiêu đề cùng lặp một khái niệm. Tên cuộc họp do người dùng nhập được giữ đầy đủ, có cách xem hết nếu cần rút gọn hiển thị. |
| Thanh công cụ | Tìm/lọc, thao tác chính và menu phụ theo ngữ cảnh | Đặt gần đối tượng chịu tác động. Mỗi nhóm hành động có thứ tự ưu tiên rõ. |
| Vùng làm việc | Timeline, lời chép hoặc nội dung biên bản | Chiếm diện tích chính; chiều rộng chữ có giới hạn đọc hợp lý. |
| Panel phụ | Căn cứ, thông tin mục đang chọn, preview hoặc cấu hình | Mở theo nhu cầu, không tự chiếm diện tích cho nội dung chưa liên quan. |
| Thông báo | Chưa lưu, lỗi, thiếu mốc, bản cũ, việc cần rà | Hiện đúng vị trí/quy mô; gộp thông báo cùng nguyên nhân và cho đi tới chỗ cần sửa. |

Trong viewport ứng dụng có một H1 chính. Các đề mục có H2/H3 theo cấu trúc nội dung, không chọn thẻ heading chỉ vì cần chữ lớn. Tài liệu preview có cấu trúc riêng của tài liệu.

## 4. Chính sách giữ, chuyển hoặc bỏ thông tin

| Nhóm | Khi xuất hiện | Ví dụ |
| --- | --- | --- |
| **Luôn thấy trong tác vụ** | Người dùng cần để làm đúng | Tên cuộc họp; nội dung đang sửa; trạng thái lưu; nguồn/đồng hồ đang dùng; nhãn trường bắt buộc; giới hạn file khi tải. |
| **Hiện khi có tình huống** | Một trạng thái làm thay đổi việc cần làm | Bản ghi chưa căn được, biên bản đã cũ, chưa có model sẵn sàng, thiếu trường bắt buộc, lỗi lưu. |
| **Mở khi cần** | Có ích cho một số lúc nhưng không thường xuyên | Toàn bộ căn cứ, lịch sử, tùy chọn tạo lại, gói căn cứ, thông tin định dạng và chẩn đoán kỹ thuật. |
| **Chuyển khỏi vùng làm việc/bỏ bản lặp** | Không giúp quyết định hay thao tác tại đây | Khẩu hiệu trên dashboard, “Các cuộc họp được cập nhật gần nhất” dưới “Cuộc họp gần đây”, footer thương hiệu lặp trên mọi trang. |

Hướng dẫn ban đầu hiện trong empty state hoặc trợ giúp có thể mở lại. Nhãn truy cập, mô tả lỗi và cảnh báo quan trọng không bị bỏ chỉ vì muốn giao diện ít chữ.

Việc tinh gọn áp dụng cho nội dung điều khiển và cách trình bày. Lời chép, tên, căn cứ và diễn biến cuộc họp vẫn giữ dữ liệu gốc; rút gọn để đọc có cách mở đầy đủ. Không biến việc dọn UI thành tự tóm tắt hoặc xóa nội dung cuộc họp.

## 5. Rà nội dung đang có: đề xuất cụ thể

| Vị trí/chuỗi hiện có | Đề xuất | Lý do |
| --- | --- | --- |
| Dashboard: “Chào …, một ngày làm việc rõ ràng.” | Tiêu đề “Tổng quan”, vùng “Cần tiếp tục” có cuộc họp/hành động thật | Đưa công việc lên đầu; tên người vẫn có ở tài khoản. |
| “Tiếp nối cuộc họp. Hoàn thiện từng biên bản.” | Bỏ khỏi dashboard đã có dữ liệu | Không thêm điều kiện hay hướng dẫn thao tác. |
| “Cuộc họp gần đây” + “Các cuộc họp được cập nhật gần nhất.” | Giữ tiêu đề, bỏ mô tả lặp | Tiêu đề đã đủ ý. |
| “QUY TRÌNH LÀM VIỆC / Từ bản ghi đến biên bản” ở cột phải dashboard | Chuyển vào lần dùng đầu/Trợ giúp | Nhường diện tích cho công việc thường xuyên. |
| Thẻ tổng số cuộc họp, biên bản và các mô tả cố định bên dưới | Giữ số liệu giúp quyết định, có lối mở danh sách tương ứng; ưu tiên việc cần rà | Không coi có nhiều thẻ là điều kiện để có dashboard chuyên nghiệp. |
| “Worker đang kết nối” | Ẩn trạng thái bình thường khỏi dashboard người dùng; chi tiết ở admin | Từ kỹ thuật không giúp lập biên bản. |
| “Worker chưa kết nối” | Khi cản xử lý: “Chưa thể xử lý lúc này” cùng hành động phù hợp trạng thái thật | Giữ thông tin cần biết, đổi cách diễn đạt. Không hứa thử lại nếu backend chưa cho phép. |
| “Tác vụ sẽ chạy khi worker sẵn sàng.” | “Đang chờ xử lý” | Giữ trạng thái; chẩn đoán chi tiết mở khi cần. |
| “Tiến độ được cập nhật theo công đoạn xử lý.” | Chỉ hiện tên công đoạn thực và tiến độ đo được | Bỏ mô tả cách UI vận hành lặp lại liên tục. |
| Sidebar “Không gian cục bộ / Phiên bản nghiên cứu 1.0” | Thiết lập → Giới thiệu | Thông tin ít dùng, không phải menu công việc. |
| Ngày hôm nay ở mọi header | Chỉ hiện ngày họp tại cuộc họp và ngày liên quan trong danh sách | Tránh nhầm ngày hệ thống với ngày họp. |
| Footer “Minda. · Meeting workspace” | Bỏ ở vùng làm việc | Thương hiệu đã có ở shell. |
| Footer nhắc rà nội dung ở mọi trang | Chuyển thành trạng thái và checklist trước khi xác nhận biên bản | Đặt lời nhắc tại quyết định cần chú ý. |
| Tab “Transcript” | “Lời chép” nhất quán với nút tìm và thông báo | Dùng tiếng Việt dễ hiểu cho người lập biên bản. |
| “… đoạn · Chỉnh sửa luôn tạo phiên bản mới.” | Giữ số đoạn; hướng dẫn phiên bản hiện lúc sửa đầu tiên hoặc tại Lịch sử | Giảm lặp, vẫn có thể tra cứu hành vi lưu. |
| “Nội dung & dữ liệu” | “Nội dung biên bản” hoặc đề mục đang rà | Cho biết cụ thể đối tượng làm việc. |
| “Chọn trường để sửa hoặc mở bằng chứng liên quan.” | Hành động “Sửa”, “Xem căn cứ” ngay tại mục | Người dùng thấy cách làm ở đúng chỗ. |
| “Cấu hình & tạo lại” | “Tạo lại biên bản”; tùy chọn trong panel tương ứng | Tên hành động nêu kết quả. Đổi mẫu/định dạng và tạo lại phải giữ khác biệt về tác động. |
| Tải DOCX và Gói bằng chứng ngang độ ưu tiên | “Tải Word” là hành động thường dùng; gói căn cứ trong menu Xuất | Giữ đủ chức năng, phân cấp theo việc chính. |
| “Có căn cứ” | Giữ như nhãn nguồn hỗ trợ; “Đã rà” là trạng thái xác nhận riêng | Có liên kết nguồn không chứng minh diễn giải AI đã đúng. |
| Thiếu giờ, người nói chưa rõ, thời gian cục bộ, bản cũ | Giữ nhãn cụ thể và lối đi sửa | Đây là thông tin cần thiết, không phải chữ thừa. |

Chuỗi mới trong bảng là đề xuất nội dung, chưa thay vào mã. Các nhãn xác nhận và hành động có thể cần thống nhất tiếp với mô hình trạng thái backend trước khi triển khai.

## 6. Bố trí chữ và mật độ thông tin

### Phân cấp chữ

Giữ font Geist đang đóng gói local. Chỉ tạo một số vai trò chữ dùng chung:

| Vai trò | Điểm bắt đầu để thử | Cách dùng |
| --- | --- | --- |
| Tiêu đề trang/đối tượng | 24–28 px, weight 600, line-height 1,3–1,4 | Tên trang hoặc tên cuộc họp; không dùng cỡ lớn để trang trí vùng làm việc. |
| Tiêu đề nhóm | 16–18 px, weight 600 | Đề mục, nhóm dữ liệu có ý nghĩa. |
| Chữ UI | 14 px, line-height khoảng 1,5 | Nhãn, menu, bảng và điều khiển thường dùng. |
| Lời chép/biên bản đang đọc sửa | 16 px, line-height khoảng 1,6–1,75 | Văn bản dài tiếng Việt; kiểm dấu, chữ dài và đoạn có số. |
| Metadata phụ | 12–13 px | Giờ cập nhật, số file, nguồn; giữ tương phản rõ, không dùng cho chỉ dẫn bắt buộc. |

Đây là thông số thử nghiệm của Minda, không phải mức tối thiểu do WCAG quy định. Giữ màu hiện tại; nếu một cặp chữ/nền đang có không đủ tương phản, ưu tiên dùng cặp màu phù hợp đã có trong bảng màu và cách bố trí rõ hơn, không tự thay nhận diện.

USWDS nêu khoảng dòng đọc phổ biến 45–90 ký tự và mục tiêu khoảng 66 cho văn bản dài. Với Minda, thử vùng chữ khoảng **60–75ch**, rồi kiểm tiếng Việt thực tế và panel bên cạnh. `ch` dựa trên bề rộng ký tự 0 của font, không phải phép đếm ký tự tiếng Việt. Không áp giới hạn này cho toàn bộ bảng hoặc timeline.

### Quy tắc trình bày

- Căn trái văn bản UI/lời chép; không căn giữa đoạn hướng dẫn dài. Văn bản trong DOCX/preview giữ định dạng mẫu.
- Các nhãn, giá trị, nút cùng loại có chung trục căn. Khoảng cách giữa nhóm lớn hơn khoảng cách trong nhóm; dùng nền/viền để thể hiện cấu trúc cần thiết, giảm card lồng nhau.
- Heading nói được nội dung bên dưới; bỏ nhãn phụ không thêm ngữ cảnh. Dùng sentence case; không viết hoa toàn bộ chỉ để tạo thứ bậc.
- Tên người, đơn vị, cuộc họp có cách xem hết. Không thu nhỏ chữ để ép vừa hoặc cắt mất phần phân biệt hai đối tượng.
- Bảng số căn phải, thời gian dùng chữ số cùng độ rộng khi cần so; thời gian dài có giờ, không quay vòng về `mm:ss`. Giữ nhãn đồng hồ cục bộ khi cần.
- Nội dung trọng yếu không phụ thuộc hover. Chú giải bổ sung có thể dùng tooltip, nhãn trường vẫn tồn tại.
- Có thể nhóm các lượt liền nhau của cùng người để giảm lặp nhãn trong UI, nhưng giữ ranh giới lượt/ID và căn cứ. Không gộp qua khoảng ghi thiếu hoặc đồng hồ khác nhau.
- Placeholder là ví dụ nhập, không thay nhãn. Lỗi gần trường và bản tóm tắt lỗi có liên kết khi form dài.

### Ngôn ngữ giao diện

Ưu tiên động từ + đối tượng/kết quả cho nút: “Tạo cuộc họp”, “Lưu thay đổi”, “Xem căn cứ”, “Tạo lại biên bản”. Tránh nút “Thực hiện”, “Xác nhận” đứng riêng khi không rõ tác động. Thông báo lỗi gồm việc gì xảy ra và hành động có thể làm, không đổ mã lỗi/model ra trước.

Thống nhất “Nguồn âm thanh”, “Lời chép”, “Biên bản”, “Căn cứ”, “Cần rà”, “Đã rà”, “Cần cập nhật”. Tên model, fusion, revision và log kỹ thuật ở cấu hình nâng cao/admin. Ngày giờ có quy ước thống nhất và không lẫn ngày họp với ngày cập nhật.

## 7. Bố cục đề xuất theo màn hình

| Màn hình | Phần chính | Phần mở thêm |
| --- | --- | --- |
| Tổng quan | Việc cần tiếp tục, cuộc họp cần rà, danh sách gần đây, tạo cuộc họp | Thống kê tổng quan có ích; hướng dẫn cho lần đầu. |
| Danh sách cuộc họp | Một thanh tìm/lọc, bảng có trạng thái và hành động, phân trang đúng toàn tập | Metadata ít dùng, hành động quản lý trong menu. |
| Nguồn âm thanh | Kho chưa xếp, hàng nguồn và các clip; vấn đề cần xử lý | Chi tiết clip/mốc/khớp âm thanh theo phần đang chọn. |
| Lời chép | Nội dung đọc liên tục, người nói/thời gian, player và tìm trong lời chép | Bộ lọc người nói/cần rà, căn cứ nguồn, lịch sử sửa. |
| Biên bản | Tài liệu là trung tâm; giữ hướng “Tập trung tài liệu” để tiếp tục thảo luận | Căn cứ của mục đang chọn, preview Word, tùy chọn xuất/tạo lại. Có thể dùng bố cục cạnh nhau khi cần rà liên tục. |
| Tài nguyên | Danh sách mẫu/hồ sơ và trạng thái sẵn sàng | Hướng dẫn tải/duyệt hiện ở bước liên quan. |
| Quản trị | Trạng thái vận hành và công việc quản trị cụ thể | Chi tiết kỹ thuật, lỗi, model, sao lưu và nhật ký theo tác vụ. |

“Tập trung tài liệu” là lựa chọn đã được xem trong phác thảo, chưa coi là người dùng đã chốt mọi chi tiết của bố cục này. Bảng màu cũ là yêu cầu đã chốt.

## 8. Nghiên cứu Three.js: dùng ở đâu và hiệu ứng nào

### Hiệu ứng nên thử

| Hướng | Nguồn tham khảo | Áp dụng đề xuất |
| --- | --- | --- |
| **Logo nét âm có chiều sâu** | [Three.js](https://github.com/mrdoob/three.js), [Drei Float](https://drei.docs.pmnd.rs/staging/float) | Một cụm thanh khối ở vùng giới thiệu màn đăng nhập. Xoay/nhô nhẹ rồi dừng; màu than đậm và xanh phụ cũ. Không chạy Float vô hạn theo mặc định. |
| **Dải đường/sóng trừu tượng** | [Ví dụ lines](https://threejs.org/examples/webgl_buffergeometry_lines.html), [particles waves](https://threejs.org/examples/webgl_points_waves.html) | Lấy ý về chiều sâu và nhịp chuyển động, giản lược mật độ/tốc độ; đặt ở vùng hình, tách khỏi chữ. Là đồ họa nhận diện, không phải waveform của bản ghi. |
| **Nền Vanta có kiểm soát** | [Vanta](https://www.vantajs.com/), [repository](https://github.com/tengbao/vanta) | Tham khảo tương tác nền. Chưa ưu tiên đưa nguyên bộ hiệu ứng vào Minda; ví dụ dùng phiên bản Three cũ và cần kiểm tương thích/cách dừng. |
| **Phản hồi thao tác** | Chuyển trạng thái, mở panel, chọn clip | Dùng CSS cho chuyển động ngắn như fade/translate. Chỉ thêm Three.js khi hiệu ứng thực sự cần cảnh 3D. |

Đã quan sát trực tiếp ví dụ particles waves và trang Vanta với hiệu ứng Birds. Hai trang minh họa khả năng render, không phải thử hiệu năng trên thiết bị mục tiêu hoặc bằng chứng rằng các hiệu ứng đó hợp với workspace. Ví dụ lines/Float được đọc qua trang/tài liệu chính thức. Không lấy nền đen hoặc màu rực của demo làm bảng màu mới.

### Phân bổ theo khu vực

- **Đăng nhập/giới thiệu:** có thể có một cảnh nhỏ. Form và thông tin cần đọc nằm ở lớp HTML tĩnh, tương phản độc lập với cảnh.
- **Lần dùng đầu:** cân nhắc minh họa ngắn chỉ khi giúp hiểu nguồn → lời chép → biên bản. Giữ bản tĩnh nếu đã đủ rõ.
- **Dashboard:** ưu tiên nội dung công việc; điểm nhấn nhận diện nếu có phải nhỏ và không làm dịch bố cục.
- **Timeline, transcript, biên bản, quản trị:** nền tĩnh. Hover/chọn/lưu có phản hồi ngắn. Dạng sóng và tiến độ dùng dữ liệu thật, không dùng chuyển động trang trí để giả tín hiệu hoặc kết quả.

Không đề xuất confetti khi xuất Word, chữ bay/chạy, nền hạt phía sau văn bản dài, parallax toàn trang hay con trỏ thay hình trong tác vụ đọc/sửa. Quyết định này dựa trên yêu cầu tập trung và lượng văn bản của Minda, chưa phải so sánh thử người dùng.

### Lựa chọn công nghệ và giới hạn

| Nguồn GitHub | Giấy phép đã đọc | Vai trò |
| --- | --- | --- |
| [mrdoob/three.js](https://github.com/mrdoob/three.js) | [MIT](https://github.com/mrdoob/three.js/blob/dev/LICENSE) | Một cảnh độc lập có thể dùng Three trực tiếp; cần quản lý vòng đời/resize/dispose. |
| [pmndrs/react-three-fiber](https://github.com/pmndrs/react-three-fiber) | [MIT](https://github.com/pmndrs/react-three-fiber/blob/master/LICENSE) | Nếu scene cần gắn với React; [README](https://github.com/pmndrs/react-three-fiber#readme) nêu Fiber 9 đi với React 19, Fiber 8 đi với React 18. Chọn phiên bản khớp peer dependencies. |
| [pmndrs/drei](https://github.com/pmndrs/drei) | [MIT](https://github.com/pmndrs/drei/blob/master/LICENSE) | Helper tùy nhu cầu; không thêm toàn bộ effect khi chỉ cần vài thanh khối. |
| [tengbao/vanta](https://github.com/tengbao/vanta) | [License dạng MIT](https://github.com/tengbao/vanta/blob/master/LICENSE.md) | Tham khảo nền dựng sẵn; không suy các ví dụ cũ sẽ chạy nguyên trạng với dependency hiện tại. |

Với một scene nhận diện nhỏ, thử Three trực tiếp trước để đánh giá lợi ích. Nếu cần nhiều thành phần scene phụ thuộc state React, cân nhắc Fiber/Drei sau khi thử tích hợp. Không đưa quyết định này thành thay đổi framework hoặc thư viện UI của Minda.

## 9. Quy tắc triển khai chuyển động

1. **Tải theo nhu cầu:** module 3D nằm ở route/khu vực giới thiệu; không buộc tải để đọc transcript hoặc biên bản. Nội dung/form vẫn dùng được khi module/WebGL lỗi.
2. **Dừng thật:** hết hiệu ứng thì ngừng lịch render; khi tab ẩn hoặc vùng hình ra khỏi viewport thì dừng. Quay lại không tự chạy lại gây phân tâm.
3. **Bản tĩnh và giảm chuyển động:** tôn trọng hệ điều hành; có nút xem/dừng. Không dùng canvas làm nơi duy nhất chứa tên, hướng dẫn hoặc trạng thái.
4. **Giải phóng tài nguyên:** dispose geometry/material/texture và renderer/listener khi rời khu vực. Giới hạn resolution/draw calls sau khi đo thiết bị mục tiêu.
5. **Không mặc định coi `demand` là đã hết render:** [Drei Float](https://drei.docs.pmnd.rs/staging/float) có thể liên tục invalidate khi bật `autoInvalidate`. Cần thực sự tắt chuyển động và kiểm không còn vòng lặp.
6. **Đo trước/sau:** đo tải trang, phản hồi nhập/click, ổn định bố cục, bộ nhớ và thời gian khung hình khi có/không có hiệu ứng. Kiểm cùng điều kiện thiết bị và xử lý audio; chưa có số đo trong nghiên cứu này.

[Three — Rendering on Demand](https://threejs.org/manual/pages/rendering-on-demand.html) giải thích việc chỉ render khi có thay đổi. [Cleanup](https://threejs.org/manual/pages/cleanup.html) nêu trách nhiệm giải phóng tài nguyên; [Fiber Scaling Performance](https://r3f.docs.pmnd.rs/advanced/scaling-performance) mô tả on-demand, tái sử dụng tài nguyên và điều chỉnh chất lượng. Các hướng này là căn cứ kỹ thuật; không bảo đảm scene nhẹ nếu chưa đo bản thực.

Thời lượng thử ban đầu: phản hồi UI khoảng 120–200 ms; mở panel khoảng 180–240 ms; cảnh nhận diện chạy một lần khoảng 2–3 giây rồi dừng. Đây là giá trị thiết kế để thử, không phải tiêu chuẩn hoặc thời gian đã đo tối ưu. Các trường hợp tự chạy dài hơn phải kiểm yêu cầu W3C tương ứng.

Mẫu kèm theo dùng Three.js thật cho logo/dải đường, tải module khi người xem yêu cầu, chạy ngắn rồi dừng, có bản tĩnh. Mẫu chỉ là minh họa, không có audio, API hoặc dữ liệu cuộc họp. Không thay cho kiểm tích hợp và kiểm hiệu năng production.

## 10. Đợt nâng cấp đề xuất và nghiệm thu

**Đợt đầu:** chốt bản đồ điều hướng, danh mục thuật ngữ và bảng giữ/chuyển/bỏ; dựng shell và header gọn; thay các chuỗi lặp; bảo vệ trạng thái chưa lưu/cảnh báo. Giữ màu cũ.

**Đợt hai:** chuẩn hóa chữ/khoảng cách, danh sách và workspace tài liệu; kiểm tên dài, văn bản tiếng Việt, một/hai panel, tìm/lọc đúng phạm vi. Tác vụ người dùng là căn cứ để chọn mật độ.

**Đợt ba:** thử cảnh 3D độc lập, có bản tĩnh đối chiếu; chỉ đưa vào khu vực đã chọn nếu không làm giảm khả năng hoàn thành tác vụ và vượt mức tài nguyên chấp nhận được.

Nghiệm thu bằng các tác vụ: tìm cuộc họp cần xử lý; xác định lỗi thiếu mốc; tìm/sửa một đoạn; xem nguồn của một quyết định; xác nhận và tải đúng phiên bản. Đo thời gian, thao tác nhầm, chỗ phải đọc lại và khả năng nhớ vị trí; không dùng số lượng chữ đã xóa hoặc FPS của trang demo làm điểm chất lượng UX.

Kiểm thủ công và tự động: cấu trúc heading/landmark, tên nút và phạm vi tìm, focus, keyboard, zoom 200%, nhiều viewport, reduced motion, không có WebGL, mất mạng khi tải module và rời/quay lại trang. Bản production cần đo tải/độ phản hồi/ổn định bố cục theo [Web Vitals](https://web.dev/articles/vitals); lượt nghiên cứu này chưa công bố mức đạt.

## 11. Phạm vi kết luận

Đã đọc nguồn chính thức, rà chuỗi trong mã, quan sát hai demo và chuẩn bị ví dụ riêng. Chưa sửa frontend production, chưa thực hiện bước 4–6, chưa thử khả dụng với người dùng hoặc đo hiệu năng trên máy triển khai. Các phân nhóm, nội dung thay thế và lựa chọn hiệu ứng là đề xuất có căn cứ để thảo luận và dựng mẫu tiếp.

Mẫu Three.js đã được mở trong trình duyệt: hiển thị bản tĩnh trước khi tải, tải scene khi bấm, dựng được hai hình, chuyển về trạng thái dừng và không có lỗi console ở các lượt quan sát. Chưa thử đổi thiết lập giảm chuyển động, giả lập mất WebGL/mạng hoặc đo số khung hình/bộ nhớ; các nhánh này mới được rà trong mã mẫu.

Danh mục nguồn, phạm vi kiểm và dấu kiểm tra frontend giữ nguyên: [research_evidence.json](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/frontend-content-motion-research-20261027/research_evidence.json>).
