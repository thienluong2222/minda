# Kiểm thử ontology và dàn ý biên bản Minda

## Thay đổi

| Phần | Triển khai | Căn cứ |
| --- | --- | --- |
| Ontology đồ thị 2.0 | `Event` lưu mệnh đề gốc. Thuộc tính trỏ tới đoạn chữ có vị trí trong lời chép gốc. Cạnh có kiểu và căn cứ hai đầu. Nút vấn đề tập hợp lịch sử và các sự kiện còn hiệu lực. Một cạnh sửa thời hạn cập nhật đúng thuộc tính, có thể truy cả hạn ban đầu và đoạn xác nhận hạn mới. | Một nhiệm vụ và các thuộc tính của nó có thể hình thành qua nhiều lượt nói. [Purver et al.](https://aclanthology.org/2007.sigdial-1.4/), [ExplainMeetSum](https://aclanthology.org/2023.acl-long.731/) |
| Dàn ý 3.0 | Lưu dàn ý chuẩn bị và dàn ý sau khi viết với ID đồ thị, phiên bản lời chép và ID dàn ý. Người dùng có thể đổi tên mục, xếp thứ tự, chuyển ý giữa các mục và chọn ý cần giữ. Tác vụ lưu bản mới, viết lại các mục có thay đổi và kế thừa các đoạn thuộc phần còn lại. | Kế hoạch kiểm soát cấu trúc, phần diễn đạt được kiểm riêng. [Step-by-Step](https://aclanthology.org/N19-1236/), [PlanGTG](https://aclanthology.org/2025.naacl-long.513/) |
| Sinh và kiểm | Bộ viết dùng thứ tự trong dàn ý. Bộ kiểm đối chiếu các câu đã đánh số với ý và đoạn nguồn. Luật chặn ca đổi chéo người với ngày khi nhận dạng được chủ thể và hạn trong câu. Bước kiểm cũng kiểm sự hiện diện của điều kiện và phiên bản tài liệu đã gắn. Lô bị từ chối được thử lại rồi tách nhỏ trước khi dùng đoạn nguồn. | Kiểm riêng lỗi thiếu ý và lỗi thêm hoặc đổi mệnh đề. [FActScore](https://aclanthology.org/2023.emnlp-main.741/), [SIEVE](https://aclanthology.org/2026.findings-aacl.184/) |
| Văn phong | Lọc quy tắc theo mục và vai trò của ý. Bộ nhớ tự động chỉ học từ bản sửa bố cục đã rà, có ánh xạ và giữ nguyên câu mang dữ kiện. Bản sửa diễn đạt rộng hơn có thể được thu thập để người rà đối chiếu mệnh đề khi tạo dữ liệu train. | Chấm độ tự nhiên và văn phong cùng với bảo toàn nội dung. [Oraby et al.](https://aclanthology.org/W18-5019/), [Mir et al.](https://aclanthology.org/N19-1049/) |

Mặc định viết tối đa bốn ý mỗi lô. Với cả cuộc họp, Minda có thể tạo dàn ý tự động. Sau khi đã có một phiên bản, người dùng chọn **Chỉnh dàn ý** trước khi tạo bản tiếp theo. Dàn ý 2.0 còn mở được để tra cứu. Tạo lại biên bản để có dàn ý 3.0 có thể chỉnh. Nếu lời chép đã có phiên bản mới, ứng dụng yêu cầu tạo lại để mỗi căn cứ trỏ đúng phiên bản lời chép.

## Kết quả trên dữ liệu sẵn có

Các lần chạy dùng Qwen cục bộ đã có. “Được ánh xạ” nghĩa là kiểm tự động chấp nhận các liên kết câu, ý và nguồn. “Trích nguồn” là số ý mà hệ thống giữ lại đoạn trích thay cho văn bản do mô hình viết.

| Dữ liệu | Ý trong dàn ý | ID có trong đầu ra | Được ánh xạ tự động | Trích nguồn |
| --- | ---: | ---: | ---: | ---: |
| Lời chép web đã lưu, 22 đơn vị, trước đợt thay đổi | 15 | 15 | Chưa đo | 0 |
| Lượt đầu với ontology và kiểm ánh xạ | 15 | 15 | 0 | 15 |
| Chạy lại lời chép web sau khi gửi các câu đánh số và giảm kích thước lô | 15 | 15 | 11 | 4 |
| Ca dev `MINDA-CORR-032` sau khi đổi cách ánh xạ | 5 | 5 | 4 | 1 |
| Ca dev `MINDA-CORR-032` ở bản chốt | 5 | 5 | 5 | 0 |

Lượt chạy lại lời chép web tạo 7 căn cứ thuộc tính và 12 nút vấn đề. Bốn đề xuất chuyển trạng thái thiếu căn cứ đủ mạnh để áp dụng. Hai mục lời chép chưa rõ vào danh sách đối chiếu. Số đếm 15/15 phản ánh ID đã có trong đầu ra, bao gồm các đoạn dùng nguồn. [Số đo chạy lại](../../../reports/minutes_graph/20261117/replay_summary.json), [Độ phủ và đoạn dùng nguồn](../../../reports/minutes_graph/20261117/web_transcript/coverage.json)

Trên bản sao biên bản web, phép thử đổi tên và đảo thứ tự hai ý của mục biểu quyết tạo dàn ý mới liên kết với bản trước. Tác vụ dùng lại đồ thị, giữ các đoạn của mục thảo luận và phân công, chạy hai lời gọi mô hình rồi xuất DOCX, ZIP và ảnh xem trước đủ trang. Hàm kiểm đối chiếu hash của tài liệu, manifest và nội dung gói ZIP. [Kết quả thử viết lại một mục](../../../reports/minutes_graph/20261117/outline_service_summary.json)

Ca dev bản chốt giữ trạng thái chưa chốt ngày, loại nhãn điều kiện sai gán vào cụm “giữ mốc dự kiến” và loại từ “phản bác” khi nguồn chỉ nói lịch chưa rõ. [Kết quả ca dev bản chốt](../../../reports/minutes_graph/20261117/dev_confirmed/summary.json)

Nhóm kiểm thử đồ thị và biên bản đạt 205 ca ở checkout web và 127 ca ở checkout chạy độc lập. Bảy kiểm thử API đồ thị, dàn ý và bộ nhớ văn phong đạt trên MongoDB tạm. Bản dựng giao diện hoàn tất.

## Điểm mới và giới hạn

Mã mới đọc và xác thực cấu trúc của 160 đồ thị 1.0 trong bộ báo cáo ngày 08/11. API dàn ý cũng có kiểm thử đọc dàn ý 2.0 và phân trang theo phiên bản.

Điểm mới trong Minda là có thể tra một thời hạn hiện hành đến đúng mệnh đề đã đổi hạn, vẫn xem được phát biểu trước đó, và đưa phần đã chọn qua một dàn ý có phiên bản. Ca hồi quy giữ hạn 15/6 trong phát biểu cũ, chiếu hạn 17/6 từ phát biểu cập nhật và giữ điều kiện phê duyệt. Ca hoán đổi hai ngày giữa hai đầu việc bị chặn ở tầng luật ngay cả khi tập ngày trong cả đoạn giống nguồn.

Lượt web này vẫn dùng đoạn nguồn cho 4/15 ý, trong khi bản cũ lưu 0/15. Việc đánh giá độ chính xác, độ đầy đủ ý nghĩa và văn phong cần người chấm độc lập trên nhiều cuộc họp. Một cạnh có trích đoạn có thể vẫn cần người rà cách diễn giải. Mô hình viết và mô hình kiểm trong lượt thử dùng chung Qwen. Các ca chuyển trạng thái đối nghịch được kiểm bằng fixture hồi quy. Hai lượt Qwen ở trên chưa có cạnh chuyển trạng thái được khẳng định, nên chưa đo được độ bao phủ trích xuất cạnh trên tập họp thực tế.

[Kế hoạch thảo luận huấn luyện LLM](../PLAN_HUAN_LUYEN_LLM_BIEN_BAN_2026-11-17.md)
