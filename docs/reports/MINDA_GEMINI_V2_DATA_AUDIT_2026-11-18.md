# Kiểm định bộ dữ liệu đồ thị Minda v2

Ngày 18/11/2026 · Kiểm định độc lập bản xuất `graph-synthetic-v2`

**V2 đạt mốc số lượng và định dạng. Cần sửa nhãn, xuất lại các lô lệch runtime và làm mới các ca test lặp khung trước khi dùng cả gói cho SFT và đánh giá trước–sau LoRA.** Có thể lấy phần đã rà nguồn để thử nạp dữ liệu và lưu, nạp lại adapter. [Báo cáo của agent](../../artifacts/graph-synthetic-v2/validation_report.md)

## Những phần đã xác nhận

| Tập | Họ | Ca | Lô trích xuất | Lô nối quan hệ |
| --- | ---: | ---: | ---: | ---: |
| Train | 60 | 194 | 254 | 254 |
| Dev | 24 | 84 | 108 | 108 |
| Test | 30 | 100 | 130 | 130 |
| Tổng | 114 | 378 | 492 | 492 |

Mình đọc 984 lô, đối chiếu với chỉ mục và hồ sơ ca, nạp bằng tokenizer Qwen3 rồi phát lại qua parser và các hàm đồ thị của Minda. Cả 984 lô khớp chat template và có token kết thúc ở đáp án. Mẫu train dài nhất có **1.130 token**, tính cả prompt và đáp án. Với cửa sổ đã xuất, bộ dựng xử lý đủ **1.836 sự kiện**, và **652 trường hoặc điều kiện trạng thái đã khai báo** đều khớp. [Số liệu kiểm định](../../../reports/minutes_graph/20261118/gemini_v2_data_audit/results.json) · [Mã phát lại](../../../reports/minutes_graph/20261118/gemini_v2_data_audit/verify_v2.py)

Manifest SFT trỏ đúng hai tệp train. Bốn SHA-256 của train và dev khớp với tệp trên đĩa. Số `family_id` trùng giữa các tập và số nhóm payload giống hệt qua các tập đều bằng 0. Đầu vào test và đáp án dùng để chấm được lưu ở các tệp riêng. [Manifest train](../../artifacts/graph-synthetic-v2/train_manifest.json) · [Manifest chia tập](../../artifacts/graph-synthetic-v2/split_manifest.json)

## Lỗi ảnh hưởng đến huấn luyện

### 1. Một phần nhãn nối cạnh bị Minda loại

| Tập | Cạnh trong đáp án đã xuất | Cạnh thực sự được nhận | Cạnh bị loại | Lô nối bị ảnh hưởng |
| --- | ---: | ---: | ---: | ---: |
| Train | 226 | 190 | 36 | 28 |
| Dev | 96 | 80 | 16 | 12 |
| Test | 116 | 96 | 20 | 14 |
| Tổng | 438 | 366 | 72 | 54 |

Cả 72 cạnh là `refers_to` trong các ca hỏi đáp. Mã sinh thường lấy đúng 28 ký tự đầu của dẫn chứng. Ví dụ `fam_qa_01_base` có cụm “Độ trễ trung bình máy chủ tì” trong lúc lời nguồn còn tiếp tục chữ “tìm”. Hàm kiểm dẫn chứng yêu cầu khớp ranh giới từ, khiến đoạn đó bị loại. Có 56 cạnh bị loại có ít nhất một đầu trích cắt giữa từ. Kiểm JSON và các trạng thái đã khai báo vẫn chạy qua vì cạnh quy chiếu này không chuyển trạng thái hiệu lực. [Mã tạo quote](../../artifacts/graph-synthetic-v2/scripts/case_builder.py#L143) · [Hàm xác minh dẫn chứng](../../src/meeting_pipeline/minutes/graph_evidence.py#L23)

Mình thay các quote lỗi bằng nguyên văn hai sự kiện trong bộ nhớ và phát lại. `connect_events` nhận được **72/72 cạnh**. Khi sửa nguồn, lấy cụm nguyên văn đủ để xác định quan hệ, rồi đối chiếu số cạnh đã xuất với số cạnh thực sự được nhận trong phạm vi nhìn thấy.

### 2. E5 thật làm đổi một số lô trích xuất

Mình tính lại embedding của cả 76 ca trích nhiều lô bằng worker E5 của Minda. Agent đưa trực tiếp `unit.text` vào E5. Runtime dùng `contextual_texts`, có thể ghép câu trước vào câu ngắn hoặc câu quy chiếu trước khi tính embedding. Có **5/492 lô trích xuất** đổi ngữ cảnh, gồm 4 train và 1 test. Ba lô train đổi mã `u#`. Ví dụ `fam_qa_03_long_qa`, lô thứ hai thêm `t1` vào ngữ cảnh và chuyển `u4`, `u5` thành `u5`, `u6`. [Mã lấy embedding của agent](../../artifacts/graph-synthetic-v2/scripts/verify_and_export.py#L211) · [Mã runtime](../../src/meeting_pipeline/minutes/graph_topics.py#L169)

Thử dựng lại cả năm payload và ánh xạ lại mã trong bộ nhớ cho cùng các sự kiện đã gán. Khi xuất bản tiếp theo, dùng đúng tiền xử lý E5 và kiểm lại từng alias. Làm rõ thêm 19 ca ngoài cửa sổ. Các ca này để trống `issue` ở việc gốc và câu đổi hạn, đồng thời để trống `expected_state` toàn cuộc họp. E5 thật tìm được việc gốc ở bước trích trong cả 19 ca. Nhãn rỗng của một lô nối cần được ghi cùng đáp án đầy đủ ở cấp cuộc họp và lý do đích vắng mặt ở lô đó. [Mẫu sinh ca ngoài cửa sổ](../../artifacts/graph-synthetic-v2/scripts/case_builder.py#L638)

## Nhãn và tập đánh giá cần rà

- **Rà ngữ nghĩa.** Cả **984 lô** mang `awaiting_independent_llm_review: true`. Các hàm rà của agent nhận cả đáp án đã gán để kiểm chuỗi con và ID. Khi đối chiếu trực tiếp, `fam_qa_02_base` vẫn nối câu hỏi về hạn nhận hồ sơ với câu trả lời về ngày mở đơn. Có **19 cạnh `accepts` có điều kiện** mà quote nguồn bỏ mệnh đề “nếu”, trong lúc bộ dựng đã chuyển vòng đời nút đích sang `accepted`. Cần giữ mệnh đề điều kiện trong quote và rà rõ ngữ nghĩa hiệu lực. [Mã kiểm của agent](../../artifacts/graph-synthetic-v2/scripts/verify_and_export.py#L103)
- **Lặp khung qua split.** Sau khi thay các giá trị điền vào mẫu như chủ đề, người, hạn, phiên bản và phương án bằng tên trường, mình so nguyên văn khung câu, thứ tự người nói, loại sự kiện và hướng cạnh. **56/84 ca dev và 68/100 ca test** có cùng khung với một ca train theo phép kiểm này. Ví dụ hai ca đổi người phụ trách có cùng ba câu và cùng cạnh `e3 → e1` sửa `owner`, chỉ thay giá trị theo chủ đề. Phép kiểm của agent che số và ngày, nên bỏ sót các khung đổi cả tên một công việc. Test hiện tại phù hợp hơn để kiểm trên chủ đề mới trong các diễn biến quen thuộc. Cần họ test độc lập về diễn biến để đo khả năng tổng quát. [Mẫu sinh đổi người](../../artifacts/graph-synthetic-v2/scripts/case_builder.py#L503) · [Phép kiểm gần trùng của agent](../../artifacts/graph-synthetic-v2/scripts/verify_and_export.py#L287)
- **Thứ tự khóa dữ liệu.** Mã hiện tạo `cases.jsonl` cho cả ba tập rồi mới ghi hash train/dev, sau đó kiểm lại khi xuất các tệp test. Hash khớp xác nhận tính nhất quán của các tệp đã xuất. Lần tiếp theo cần ghi phiên bản train/dev trước khi bắt đầu sinh các họ test mới. [Luồng xuất của agent](../../artifacts/graph-synthetic-v2/scripts/verify_and_export.py#L331)

## Độ phủ cần bổ sung

| Tập | Đổi hạn | Đổi người | Sửa điều kiện | Sửa phiên bản |
| --- | ---: | ---: | ---: | ---: |
| Train | 30 | 10 | 4 | 0 |
| Dev | 12 | 4 | 4 | 4 |
| Test | 15 | 5 | 5 | 0 |

Bảng đếm cạnh `amends` trong lô nối đã xuất. V2 đã có đủ tám loại cạnh ở train và có 57 ca gắn nhãn nhiễu hoặc thiếu căn cứ trong toàn gói. Thiếu ca **sửa phiên bản** ở train và test khiến mục tiêu này chưa có cả dữ liệu học lẫn số đo test. Mã sinh chỉ bật biến thể sửa phiên bản cho dev. Toàn bộ 1.836 đơn vị vẫn có đúng một nhãn sự kiện mỗi đơn vị sau khi chạy bộ tách, nên cần thêm ca thực sự bắt buộc tách nhiều ý trong cùng đơn vị. [Điều kiện sinh ca đổi phiên bản](../../artifacts/graph-synthetic-v2/scripts/case_builder.py#L555)

Sửa quote và E5 trước, chạy lại tính toàn vẹn trên JSONL cuối, rồi rà nhãn từ lời chép trong lượt độc lập. Bổ sung họ sửa phiên bản cho train và test, đồng thời thay nhóm test lặp khung bằng diễn biến mới. Khóa lại bộ dữ liệu trước khi chạy đối chứng và huấn luyện LoRA.
