# Plan thảo luận: LLM nhẹ và biên bản từ DOCX, PDF, ảnh scan

**Ngày lưu:** 09/10/2026, theo múi giờ Việt Nam.  
**Trạng thái:** lưu yêu cầu và phương pháp đã thảo luận; chưa triển khai tính năng mới, chưa fine-tune hoặc đánh giá model.  
**Thứ tự công việc đã thống nhất:** lưu plan này → tiếp tục thảo luận cải tiến/tối ưu pipeline hiện có → sau đó mới cập nhật tính năng LLM và biên bản mới.

## 1. Mục đích và cách tra cứu

Tài liệu ghi lại các quyết định của người dùng, đề xuất kỹ thuật và những vấn đề còn phải đánh giá. Các mục “đề xuất” không được diễn giải thành tính năng đã hoàn thành hoặc lựa chọn đã được chứng minh tốt nhất.

| Nội dung cần tra cứu | Mục |
| --- | --- |
| Yêu cầu đầu vào/đầu ra và hai loại biên bản | 2–3 |
| Vai trò và giới hạn của LLM | 4–5 |
| Đọc mẫu, bảo toàn đề mục, tạo DOCX | 6 |
| Gom chủ đề bằng C-Means | 7 |
| Model nhẹ, dữ liệu và fine-tuning | 8–9 |
| Đánh giá và điều kiện triển khai | 10–11 |
| Nội dung thảo luận tiếp theo | 12 |

Repository mã hiện tại: `/Users/thien/Documents/School/Luận văn`. Nhánh lúc lưu: `codex/vad-speaker-asr-fusion`; HEAD được kiểm tra trong hội thoại: `f94216bd34c8c76bfef67be41b7a0b77f756e796`. Trước khi triển khai, kiểm tra lại mã, cấu hình và artifact vì trạng thái có thể thay đổi.

Tài liệu liên quan:

- `PROJECT_CONTEXT_HANDOFF_2026-10-06.md` ở `/Users/thien/Documents/ChatGPT/Luận văn/`: context bàn giao, cần đối chiếu với mã hiện hành.
- [Plan biên bản v1](PLAN_BIEU_MAU_BIEN_BAN_V1.md): kế hoạch trước đây cho `.doc`/`.docx`; PDF/scan trong tài liệu này là phạm vi mở rộng mới.
- [Plan speaker đa nguồn](PLAN_FIX_SPEAKER_MULTI_SOURCE_HIGH_RISK_2026-10-03.md): tài liệu đang có trong workspace, không ghi đè.

## 2. Các yêu cầu đã được người dùng chốt

1. Đầu vào biểu mẫu gồm **DOCX, PDF và ảnh scan/chụp tài liệu**.
2. Với mọi định dạng đầu vào được hỗ trợ, đầu ra là **DOCX có thể chỉnh sửa**. Văn bản và bảng phải là thành phần Word có thể sửa; chèn ảnh nguyên trang vào DOCX không đáp ứng yêu cầu này.
3. Có hai chế độ: **biên bản chi tiết** có sẵn các đề mục/chủ đề để điền, và **biên bản tổng quát** chỉ có vùng nội dung cuộc họp chung.
4. Với biên bản chi tiết, đầu ra phải khớp cấu trúc mẫu, **không chỉnh sửa đề mục**.
5. Với biên bản tổng quát, giữ các trường thông tin và cấu trúc ngoài vùng nội dung; bên trong vùng nội dung, chia thành các mục phù hợp với chủ đề thực sự được thảo luận.
6. Nội dung tổng quát **giữ đủ các ý công việc và quyết định**; có thể bỏ từ đệm, lời lặp và biên tập câu cho mạch lạc. Không tự biến tác vụ thành tóm tắt mạnh làm mất ý.
7. LLM có vai trò hiểu ngữ cảnh, sửa chính tả/lỗi ASR và chuyển văn nói thành văn viết phù hợp. Quyền chỉnh sửa cấu trúc tài liệu được giới hạn bằng mã.
8. Model cần đủ nhẹ. Máy đã kiểm tra trong hội thoại là MacBook Air M4, RAM thống nhất 16 GB; chưa có benchmark LLM trên máy này.
9. Người dùng làm dự án một mình và hiện chưa có tập cặp transcript–biên bản được người kiểm sửa để huấn luyện/đánh giá.
10. Tiếp tục thảo luận tối ưu pipeline hiện có **trước khi triển khai phần mở rộng này**.

## 3. Chính sách cho hai loại biên bản

| Thành phần | Biên bản chi tiết | Biên bản tổng quát |
| --- | --- | --- |
| Đề mục có sẵn | Giữ nguyên nội dung, thứ tự và cấp đề mục | Giữ nguyên đề mục ngoài vùng nội dung |
| Ngày, giờ, địa điểm, người tham gia… | Điền từ transcript/metadata có căn cứ | Xử lý tương tự |
| Nội dung | Ánh xạ ý vào đúng mục đã có | Gom ý thành chủ đề và tạo mục con trong vùng nội dung |
| Mục không có evidence | Giữ mục, để trống hoặc thể hiện chưa xác định theo chính sách mẫu | Không sinh thông tin để làm đầy văn bản |
| Vai trò LLM | Hiểu ngữ cảnh và biên tập nội dung được giao | Biên tập từng nhóm ý và diễn đạt tên chủ đề từ nội dung nhóm |
| DOCX | Điền vào mẫu/bản tái dựng có thể sửa | Tương tự, cho phép thêm mục con trong vùng nội dung |

Chế độ cần được xác định rõ và cho người dùng chỉnh khi mẫu mơ hồ. Không chỉ dựa vào tên file để chọn chế độ.

Ví dụ: nếu mẫu chi tiết có “Kết quả thực hiện nhiệm vụ kỳ trước” và “Nhiệm vụ kỳ tới”, hệ thống phải phân biệt thời điểm và ý nghĩa dù hai mục có nhiều từ giống nhau. Không đổi hai tên mục thành tên do LLM đề xuất.

## 4. Phân công trách nhiệm trong hệ thống

Luồng phương pháp đề xuất:

```text
DOCX / PDF / ảnh scan
  → đọc chữ, bảng, bố cục và vùng cần điền
  → cấu trúc mẫu thống nhất + đề mục/vùng được bảo vệ

Timeline từ pipeline âm thanh
  → sửa transcript tối thiểu, có lưu thay đổi
  → đơn vị ý nghĩa + mốc thời gian + evidence
  → chi tiết: ánh xạ vào đề mục có sẵn
     tổng quát: gom chủ đề trong vùng nội dung
  → LLM biên tập văn nói thành văn viết
  → kiểm tra căn cứ, bảo toàn ý và cấu trúc
  → render DOCX chỉnh sửa được
```

- **Parser/OCR:** đọc tài liệu và vị trí thực; giữ bảng, quan hệ bố cục, nhãn và vùng trống.
- **Embedding/retrieval:** tìm nội dung liên quan đến đề mục; biểu diễn ngữ nghĩa cho gom cụm.
- **Gom cụm:** tạo nhóm chủ đề cho chế độ tổng quát.
- **LLM:** hiểu ngữ cảnh, đề xuất sửa lỗi và biên tập câu trong phạm vi được giao. Có thể hỗ trợ ánh xạ ngữ nghĩa, nhưng phải trả ID đề mục/vùng có thật.
- **Validator/renderer:** quyết định vùng được phép sửa, kiểm tra ID, bảo toàn đề mục và xuất DOCX.

Một LLM có thể dùng chung trọng số cho các tác vụ với đầu vào/đầu ra khác nhau. OCR và embedding là thành phần chuyên dụng bổ sung; không bắt buộc giao tất cả công việc cho LLM.

Ngày, tên, số và quyết định vẫn cần bước tìm/chuẩn hóa thông tin có căn cứ trước khi điền. Gom chủ đề và câu văn trôi chảy không tự chứng minh fact đúng.

## 5. Sửa ASR và biên tập giữ nguyên ý

### 5.1. Hai tác vụ riêng bằng cùng model

**Sửa transcript:** sửa tối thiểu; đầu vào gồm lượt đang xét, ngữ cảnh trước/sau, thuật ngữ phù hợp và hypothesis ASR từ các nguồn khác nếu thực sự có. Giữ nguyên transcript gốc, lưu thay đổi và lý do. Không coi nguồn `not_run` là một hypothesis để đối chiếu.

**Biên tập biên bản:** bỏ từ đệm, sửa cấu trúc câu, gộp ý lặp và diễn đạt mạch lạc. Giữ chủ thể, hành động, thời gian, số lượng, điều kiện, phủ định và mức chắc chắn.

Tách hai bước giúp đo lỗi sửa ASR riêng với lỗi biên tập. Bản biên tập không được thay thế transcript gốc dùng để truy vết.

### 5.2. Các ràng buộc ngữ nghĩa

- Không biến đề xuất thành quyết định; không biến điều kiện thành cam kết chắc chắn.
- Không biến câu phủ định/bác bỏ thành chấp thuận.
- Không tự đặt người phụ trách, deadline, địa điểm hoặc kết quả biểu quyết.
- Khi một nội dung thay đổi trong cuộc họp, giữ được diễn biến và trạng thái cuối cùng có căn cứ.
- Không tự sửa tên, số hoặc ngày chỉ vì một phương án nghe hợp lý hơn. Thay đổi quan trọng cần evidence rõ, hoặc giữ trạng thái cần kiểm tra.
- LLM văn bản không thể phục hồi chắc chắn âm thanh đã mất hay phân biệt hai từ/số đều phù hợp ngữ cảnh. Trường hợp đó cần clip hoặc hypothesis khác.
- Kiểm tra ID/cấu trúc JSON là điều kiện cần; còn phải kiểm tra value có được evidence hỗ trợ hay không.

Ví dụ:

> Lời nói: “Em nghĩ hay là mình thử giao Lan làm, nhưng chưa chốt nhé.”

Diễn đạt phù hợp: “Có ý kiến đề xuất giao nhiệm vụ cho Lan; cuộc họp chưa thống nhất phương án này.”

“Cuộc họp thống nhất giao nhiệm vụ cho Lan” làm thay đổi sự thật và phải bị đánh dấu lỗi.

Các đoạn overlap đang bị pipeline bỏ qua hoặc không có transcript hợp lệ không được LLM tự hoàn thiện thành lời thoại/fact.

## 6. Đọc mẫu và xuất DOCX

### 6.1. DOCX

- Đọc trực tiếp paragraph, bảng, header/footer và cấu trúc liên quan.
- Giữ bản gốc; điền trên bản sao.
- Bảo vệ chữ đề mục, thứ tự, cấp đề mục và các vùng ngoài phạm vi cho phép.
- Giữ định dạng mẫu; kiểm tra ngắt trang, bảng và tràn nội dung sau khi điền.
- Với chế độ tổng quát, chỉ vùng nội dung cho phép sinh mục con.

### 6.2. PDF có chữ, PDF scan và ảnh

- PDF có chữ: lấy chữ và thông tin bố cục; trang/vùng ảnh trong PDF vẫn cần OCR khi cần thiết.
- PDF scan/ảnh: OCR kèm vị trí chữ, bảng và quan hệ giữa các vùng.
- Tái dựng thành DOCX có văn bản/bảng chỉnh sửa được.
- Bảo toàn đề mục trong mẫu gốc phụ thuộc cả độ đúng OCR. Các nhãn chưa rõ cần hiển thị để kiểm tra trước khi điền.
- Độ khớp cấu trúc và độ khớp hình thức phải được đánh giá riêng. Chưa có căn cứ để hứa giữ nguyên tuyệt đối bố cục của mọi scan.

PaddleOCR có bộ nhận dạng công bố hỗ trợ tiếng Việt, là ứng viên OCR để thử. Chưa chọn runtime cuối cùng và chưa đo tốc độ/chất lượng trên Mac M4 16 GB. Khả năng đọc chữ viết tay tiếng Việt cũng chưa được đánh giá.

## 7. Gom chủ đề cho biên bản tổng quát

Người dùng đề xuất **C-Means**. Phương pháp đang thảo luận hiểu là **Fuzzy C-Means (FCM)**; biến thể và cấu hình cuối cùng chưa được chốt.

### 7.1. Chuẩn bị đơn vị ý nghĩa

- Không gom cụm từng lượt ngắn độc lập như “đồng ý”, “phương án đó”. Giữ ngữ cảnh của lời tham chiếu.
- Ghép các lượt liên quan thành đơn vị ý nghĩa; tách lượt có nhiều chủ đề khi có thể.
- Giữ ID, người nói, thời gian, quan hệ với lượt gốc và warning.
- Dùng embedding hỗ trợ tiếng Việt; chọn model bằng đánh giá chất lượng và chi phí thực tế.

### 7.2. Chạy và chọn cấu hình FCM

- FCM nhận số cụm `c`; số chủ đề không được suy là đã tự xác định chỉ vì gọi thuật toán.
- Thử các số cụm phù hợp với lượng nội dung; cho phép trường hợp một chủ đề.
- Kiểm tra độ ổn định, độ tách biệt, cụm quá nhỏ và độ phù hợp ngữ nghĩa; không chỉ tối ưu một chỉ số nội tại.
- FCM có vấn đề đã được ghi nhận với dữ liệu nhiều chiều. Thử chuẩn hóa/giảm chiều khi cần và đo lại chất lượng; không mặc định giảm chiều luôn có lợi.
- Membership là mức thuộc cụm, không phải xác suất chủ đề đúng hoặc fact đúng.
- Ý có nhiều chủ đề cần xử lý rõ; tránh nhân đôi cùng một quyết định ở nhiều mục.

### 7.3. Từ cụm thành biên bản

- Giữ thứ tự diễn biến trong mỗi chủ đề, đặc biệt với đề xuất → phản đối → thay đổi → chốt.
- Lấy cụm từ/câu đại diện để đặt tên mục; LLM chỉ diễn đạt lại trong phạm vi nhóm nội dung đã xác định.
- Không cho LLM tự thêm chủ đề không có trong nhóm hoặc đổi cấu trúc ngoài vùng nội dung.
- Sắp mục theo lần xuất hiện đầu tiên trong cuộc họp là phương án đề xuất, cần thử với dữ liệu.
- Có thể hợp nhất ý lặp nhưng phải giữ các ý công việc và quyết định khác nhau.

So FCM với baseline gom cụm phân cấp trên cùng dữ liệu. Tiêu chí là đúng chủ đề, ít trộn ý, đủ nội dung và giữ diễn biến; chưa chốt FCM là phương pháp tốt nhất.

Biên bản chi tiết dùng ánh xạ vào đề mục có sẵn; không dùng FCM để thay hệ đề mục của mẫu.

## 8. Lựa chọn LLM nhẹ và phạm vi bảo đảm

Ứng viên đề xuất: **Qwen3-4B-Instruct-2507**, model văn bản 4B. Chưa có benchmark tiếng Việt theo các tác vụ này để chọn nó làm mặc định đã được xác nhận.

- Thử model gốc với prompt/schema ràng buộc trước khi fine-tune.
- Thử bản lượng tử hóa trên máy đích; đo bộ nhớ, tốc độ và chất lượng với độ dài ngữ cảnh thực tế.
- Model card công bố khả năng hiểu văn bản/làm theo chỉ dẫn không phải chứng cứ bảo đảm sửa ASR tiếng Việt hoặc điền biên bản luôn đúng.
- OCR cung cấp cấu trúc chữ cho LLM văn bản. Model đa phương thức như Qwen3.5-4B là lựa chọn mở nếu có nhu cầu đã đo; chưa được chốt.
- Dùng LoRA/QLoRA nếu dữ liệu và đánh giá cho thấy cần học thêm. Khả năng huấn luyện trên máy 16 GB cần thử; không suy từ việc inference chạy được rằng training cũng chạy được.

Ràng buộc bảo toàn đề mục/ID/vùng chỉnh sửa có thể kiểm tra bằng mã. Độ đúng sửa ASR, giữ ý và ánh xạ chủ đề cần đánh giá thực nghiệm, không thể bảo đảm chỉ bằng prompt hoặc lời tự nhận của model.

## 9. Dữ liệu khi người dùng làm dự án một mình

### 9.1. Điểm khởi đầu đang có

Bộ FPT TTS pilot có kịch bản, transcript tham chiếu và fact tham chiếu:

- `/Users/thien/Documents/ChatGPT/Luận văn/FPT_TTS_PILOT_2MIN/script.json`.
- `data/generated/fpt_tts_pilot_20261003/reference_facts.json`.
- `data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json`.

Đã kiểm tra có ca đề xuất bị bác, quyết định cuối, nhiệm vụ, biểu quyết và trường thiếu thông tin. Đây là dữ liệu tổng hợp; không chứng minh chất lượng trên cuộc họp thật. DOCX/fact do pipeline tạo ra không tự trở thành nhãn chuẩn.

### 9.2. Tạo dữ liệu có sự thật trước

| Tác vụ | Cách tạo | Căn cứ đáp án |
| --- | --- | --- |
| Sửa ASR | Lời thoại chuẩn → TTS → PhoWhisper hiện hành | Lời thoại gốc, kiểm tra âm thanh khi cần |
| Hiểu mẫu | Mẫu DOCX gán nhãn → PDF/ảnh với các biến đổi chất lượng | Nội dung/ý nghĩa trường đã xác định |
| Chuyển văn nói thành văn viết | Fact → hội thoại thể hiện fact → bản biên tập | Fact và câu thoại làm căn cứ, bản biên tập được rà lại |
| Gom chủ đề | Kịch bản nhiều chủ đề, có quay lại chủ đề cũ | Nhóm ý/diễn biến được xác định trước |

Kịch bản cần bao gồm: câu đã đúng phải giữ nguyên; tên/số/ngày; phủ định; điều kiện; đề xuất chưa chốt/bị bác; deadline thay đổi; nhiệm vụ thiếu owner/due; thông tin không xuất hiện; quyết định ở cuối cuộc họp.

LLM có thể hỗ trợ soạn dữ liệu nhưng output phải được kiểm tra. Sinh hội thoại và sinh đáp án bằng cùng model không tạo ra bộ đánh giá độc lập. Ưu tiên kiểm tra các fact quan trọng thay vì yêu cầu người dùng viết lại toàn bộ cuộc họp.

Pilot đã đề xuất: khoảng **20–30 kịch bản ngắn và 5–8 mẫu có cấu trúc khác nhau**. Đây là quy mô khởi đầu để phát hiện lỗi, chưa phải yêu cầu tối thiểu khoa học hay dữ liệu đủ cho tuyên bố tổng quát.

### 9.3. Tách tập và fine-tuning

- Tách train/dev/test theo kịch bản/cuộc họp và họ mẫu trước khi sinh biến thể.
- Cùng mẫu gốc xuất DOCX/PDF/ảnh, thêm mờ/nghiêng hoặc cùng kịch bản đổi tên/ngày vẫn thuộc cùng tập.
- Có tập kiểm tra nhỏ do người dùng tự rà; thêm một ít lời nói thật để đo khả năng chuyển từ TTS sang thực tế.
- Huấn luyện theo đoạn ngắn cho nhiệm vụ sửa tối thiểu và biên tập giữ ý, giảm công gán nhãn.
- Có mẫu không cần sửa và mẫu thiếu thông tin; không chỉ huấn luyện các ca sửa thành công.
- So model gốc với model fine-tuned trên cùng tập giữ riêng, rồi đánh giá bản lượng tử hóa sẽ triển khai.
- TTS/biến đổi ảnh giúp phát triển có kiểm soát; không dùng riêng các tập này để tuyên bố chất lượng trên họp và scan thực tế.

## 10. Đánh giá cần có

| Nhóm | Kiểm tra/chỉ số |
| --- | --- |
| Hiểu mẫu | Bỏ sót/trùng trường, ánh xạ đúng mục, điều kiện và quan hệ bảng |
| Bảo toàn tài liệu | Chữ/thứ tự/cấp đề mục, vùng ngoài phạm vi, định dạng/bảng/ngắt trang |
| OCR | Chữ và đề mục nhận dạng đúng, bảng/ô/vùng trống được phục hồi |
| Sửa ASR | WER/CER trước–sau với cùng chuẩn hóa; sửa đúng, sửa sai và lỗi tên/số/ngày/phủ định |
| Giữ ý | Bỏ sót ý, thêm ý không căn cứ, thay đổi đề xuất/quyết định hoặc điều kiện |
| Gom chủ đề | Trộn chủ đề, tách quá mức, ý quan trọng bỏ sót/trùng, mất diễn biến |
| Fact | Ngày/tên/vai trò/số/owner/due đúng; thiếu hoặc mâu thuẫn được xử lý đúng |
| Văn phong | Tự nhiên, mạch lạc, phù hợp biên bản và còn đủ ý |
| DOCX | Văn bản/bảng sửa được, mở được, không tràn/chồng nội dung |
| Hiệu năng | Thời gian từng stage, cold/warm, peak memory và tổng thời gian |

Đo luồng biên bản với transcript chuẩn để tách lỗi downstream, rồi với transcript ASR để đo end-to-end. Mọi fact/đoạn biên tập giữ liên kết tới evidence gốc. Không coi retrieval score, membership hay confidence LLM tự sinh là xác suất đúng đã hiệu chuẩn.

Chưa chốt ngưỡng số cho các chỉ số chất lượng. Chốt sau khi có baseline và ngân sách thực tế; không đưa số dự kiến vào báo cáo kết quả.

## 11. Thứ tự triển khai tương lai

1. **Thảo luận và tối ưu pipeline hiện có** theo mục 12; xác định baseline đáng tin cậy.
2. **Xây bộ ca pilot và nhãn**, tách tập trước khi mở rộng dữ liệu.
3. **Thử model gốc cho sửa/biên tập**, kiểm tra giữ ý và chi phí trên máy đích.
4. **Mở rộng đọc PDF/scan và DOCX tái dựng**, kiểm tra đề mục và khả năng sửa.
5. **Thử hai chế độ biên bản**, so FCM với baseline cho chế độ tổng quát.
6. **Fine-tune khi có lỗi lặp lại và dữ liệu phù hợp**, so với model gốc.
7. **Tích hợp sau khi đạt kiểm tra**, cho xem chỉnh sửa, evidence và các điểm chưa rõ.

Các bước trên là kế hoạch tương lai. Việc lưu tài liệu này không khởi chạy download model, sinh dữ liệu, training hoặc thay đổi pipeline.

## 12. Nội dung thảo luận tiếp theo: tối ưu pipeline hiện có

Người dùng yêu cầu ưu tiên phần này trước khi cập nhật tính năng mới. Mục tiêu của vòng tiếp theo là xác định lỗi và chi phí thực tế, rồi chọn thứ tự cải tiến; chưa tự triển khai theo plan này.

Các chủ đề đề xuất để xem xét:

- Đồng bộ/coverage và chất lượng nguồn đưa vào các stage sau.
- VAD, biên lượt nói, lượt quá ngắn và false-positive overlap; ảnh hưởng đến ASR và speaker.
- Nhận diện người chưa đăng ký, ambiguous và ngưỡng open-set; phân biệt chất lượng trên dữ liệu phát triển với held-out.
- Safe merge, chọn nguồn ASR adaptive, chi phí PhoWhisper-medium, cache và retry.
- Fusion thực sự đa nguồn so với lượt chỉ có một transcript hợp lệ; guard hallucination và cảnh báo.
- Evidence/provenance và khả năng tìm nguyên nhân một đoạn cần kiểm tra.
- Minutes baseline hiện có: M1 là stub; M3 opt-in, còn giới hạn ngữ cảnh/kiểm chứng và confidence cố định trong mã đã đọc. Không xem các điểm này là được giải quyết chỉ bằng đổi model.

Khi thảo luận, đối chiếu mã/config/manifest của run cụ thể. Các lỗi/số liệu trong handoff hoặc pilot cũ là điểm bắt đầu kiểm tra, không thay cho đánh giá HEAD mới.

## 13. Các điểm chưa chốt

- Model/runtime/quantization và cấu hình LoRA cuối cùng.
- OCR/parser cho PDF/scan; độ khớp hình thức cần đạt và phạm vi chữ viết tay.
- Cách xác định chế độ tự động khi mẫu mơ hồ.
- Biến thể C-Means, embedding, cách chọn số cụm và xử lý ý đa chủ đề.
- Ngưỡng chấp nhận sửa ASR, đánh giá giữ ý và thời gian xử lý.
- Bộ dữ liệu, nguồn mẫu có quyền sử dụng và khối lượng tự kiểm tra khả thi.
- Thứ tự tối ưu pipeline hiện có; sẽ được thảo luận tiếp.

## 14. Nguồn kỹ thuật đã tham khảo

Các nguồn hỗ trợ phương pháp; không chứng minh chất lượng riêng của hệ thống này.

- [Qwen3-4B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B).
- [PaddleOCR: PP-OCRv5 multilingual recognition](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md).
- [Fuzzy C-Means API và giới hạn với số chiều lớn](https://scikit-fuzzy.github.io/scikit-fuzzy/api/index.html#skfuzzy.cluster.cmeans).
- [Ví dụ chọn số cụm với FCM](https://scikit-fuzzy.github.io/scikit-fuzzy/auto_examples/plot_cmeans.html).
- [AgglomerativeClustering](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.AgglomerativeClustering.html).
- [ASR-EC Benchmark](https://aclanthology.org/2025.emnlp-industry.110/): đánh giá sửa ASR tiếng Trung; không ngoại suy thành kết quả tiếng Việt.
- [MLX-LM LoRA/QLoRA](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md).

## 15. Context ngắn để tiếp tục

> Dự án cần nhận mẫu DOCX/PDF/ảnh scan và xuất DOCX chỉnh sửa được. Biên bản chi tiết giữ nguyên đề mục; biên bản tổng quát chỉ sinh mục con trong vùng nội dung, giữ đủ ý công việc và quyết định, bỏ từ đệm/lời lặp. LLM nhẹ dùng để hiểu ngữ cảnh, sửa ASR tối thiểu và biên tập văn nói thành văn viết, có evidence và bảo toàn ý. Qwen3-4B-Instruct-2507 và Fuzzy C-Means là ứng viên chưa được đánh giá/chốt. Người dùng làm một mình, chưa có tập cặp transcript–biên bản người kiểm sửa; có FPT TTS pilot làm seed tổng hợp. Trước khi cập nhật tính năng mới, tiếp tục thảo luận cải tiến/tối ưu pipeline hiện có. Đọc plan này và kiểm tra mã/config/artifact hiện hành trước khi kết luận hoặc triển khai.
