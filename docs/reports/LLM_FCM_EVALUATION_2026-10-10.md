# Kiểm thử tích hợp LLM và FCM — 10/10/2026

## Phạm vi và dữ liệu

Thử model thật trên MacBook Air M4, RAM thống nhất 16 GB. Model Qwen3-4B
Instruct-2507 MLX 4-bit và multilingual-e5-small dùng snapshot đã ghim trong
`configs/minutes.yaml`. Không fine-tune, không sinh corpus mới, không chạy lại
ASR và không thay đổi VAD trong đợt tích hợp này.

- Transcript tham chiếu: `data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json`.
- Transcript ASR: run `test-c-enroll/3e27f5fa-08d8-443d-a8d3-c44ef62b1479`.
- Mẫu Word: `template/normalized.docx` của cùng run ASR.
- Thử 8 ca: hai đầu vào × baseline quy tắc, chi tiết LLM, tổng quát một nhóm,
  tổng quát E5 + FCM.
- Fact tham chiếu không được đưa vào prompt. Timeline gốc không bị ghi đè.
- Tham chiếu có 13 lượt, 37 đơn vị; ASR có 26 lượt được xử lý, 26 đơn vị,
  6 lượt không có transcript hợp lệ bị loại và báo rõ.

Đây là **một kịch bản TTS và một họ mẫu**, dùng để phát triển cấu hình.
Không phải tập đánh giá độc lập hoặc bằng chứng chất lượng trên cuộc họp thật.

## Cách đo và lặp lại

```bash
.venv/bin/python scripts/benchmark_llm_fcm.py \
  --output data/evaluations/llm_fcm_20261010_release
```

Script lưu DOCX, văn bản đã điền, cấu hình, sửa transcript, nhóm chủ đề và
báo cáo model riêng cho mỗi ca. Kết quả số ở
[llm_fcm_benchmark_20261010.json](llm_fcm_benchmark_20261010.json).

Thời gian đo lượt sinh thực có thể đã dùng cache ở bước sửa/schema, ghi rõ
số cache hit. Lượt kiểm tra cuối dùng lại đúng phản hồi thật từ cache để áp dụng
các validator cuối; thời gian đó không phải tốc độ sinh token của model.
Peak MLX là allocator của model; RSS là worker CPU, có thể chồng lặp với bộ nhớ
thống nhất và không đại diện tổng RAM toàn máy. Không cộng hai số này.

| Đầu vào | Chế độ | Lượt sinh/thử (giây) | Cache hit / yêu cầu | Kiểm tra cuối từ cache (giây) | Số cụm | 5 ô kiểm tra |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| reference | baseline | 0.50 | 0 / 0 | 0.24 | — | 2/5 |
| reference | detailed | 134.29 | 2 / 9 | 5.29 | 1 | 5/5 |
| reference | general | 5.24 | 9 / 9 | 3.57 | 1 | 5/5 |
| reference | fcm | 125.55 | 2 / 9 | 3.52 | 4 | 5/5 |
| asr | baseline | 0.27 | 0 / 0 | 0.25 | — | 2/5 |
| asr | detailed | 97.83 | 2 / 7 | 4.19 | 1 | 5/5 |
| asr | general | 5.10 | 7 / 7 | 4.22 | 1 | 5/5 |
| asr | fcm | 84.89 | 2 / 8 | 4.27 | 4 | 5/5 |

5 ô là chủ trì, thư ký, tổng phiếu, phiếu tán thành và phiếu không tán thành.
Baseline đạt 2/5; sáu ca LLM đạt 5/5. Đây chỉ là đối chiếu giá trị các ô này,
không phải độ chính xác toàn bộ biên bản. Cả 8 ca giữ nguyên các phần package
ngoài `word/document.xml`. Sáu ca LLM phủ đủ ID nguồn hợp lệ.

Peak MLX lớn nhất **3,08 GB**; RSS worker lớn nhất **2,58 GB** ở các lời gọi
đã đo. Không phải mức RAM tổng của toàn hệ thống. Bước sửa transcript nhận
**0 thay đổi** trên cả hai đầu vào. Với chuẩn hóa NFC, chữ thường, bỏ dấu câu,
gộp khoảng trắng (không chuyển số): WER **16,03% → 16,03%**, CER
**12,47% → 12,47%**; transcript tham chiếu có 524 từ sau chuẩn hóa.
Chưa có cải thiện ASR được quan sát trên pilot này.

## Những lỗi đã gặp và xử lý

1. Yêu cầu 4B điền toàn bộ các mảnh placeholder ngày/giờ và nội dung dài cùng
   lúc cho kết quả thiếu ID, JSON lỗi và nhầm mảnh trường. Đã tách chuẩn hóa
   metadata tường minh bằng mã; LLM giữ vai trò phân loại trường và biên tập.
2. Model có lúc gom nhiều ID vào một câu và bỏ ý. Đã yêu cầu mỗi item đúng một
   `unit_id`, giới hạn batch và kiểm tra đủ ID. Batch không đạt giữ câu nguồn;
   có cảnh báo, không coi việc xuất DOCX thành công là biên tập thành công.
3. Có câu tự thêm người nói, xưng hô hoặc chuyển việc được giao thành việc
   “đã” thực hiện. Đã thêm kiểm tra tên đã biết, số, phủ định/điều kiện và trạng
   thái hoàn thành. Các kiểm tra là heuristic bảo thủ, chưa chứng minh mọi
   biến đổi ngữ nghĩa đều được phát hiện.
4. Các dòng chấm tiếp nối từng lặp lại nội dung. Đã chỉ điền vùng đầu tiên,
   xóa dung lượng tiếp nối và giữ đúng đề mục gốc.
5. Câu mở đầu kết luận có nhiệm vụ/deadline ở câu sau. Đã lấy đủ lượt phát biểu
   kết luận và viết lại từng đơn vị, tránh chỉ lấy câu có từ khóa kết luận.
6. Kiểm tra Word phát hiện các placeholder giống nhau bị điền lệch khi ô đầu
   chưa rõ. Đã thay thế theo offset từ phải sang trái, cả paragraph và bảng;
   thêm regression test. Địa điểm được chặn ranh giới câu và giờ/ngày kết thúc
   để trống khi ASR thiếu căn cứ.
7. Mẫu cố định nói biên bản đã “cùng ký”, nhưng transcript nói chưa có chữ ký.
   Giữ câu của mẫu theo yêu cầu bảo toàn, để vùng ký trống và cảnh báo người dùng.

## FCM và chất lượng nội dung

Với `m=2`, embedding của pilot làm tâm cụm co và membership gần đều; kiểm tra
đã loại các phân hoạch đó về một cụm. Thử phát triển `m=1.3/1.5/1.7/2.0`
trên cùng pilot; hiện cấu hình `m=1.3`, tối đa 4 cụm. PCA tối đa 12 chiều dùng
khi fit, cosine silhouette đo trong không gian embedding gốc 384 chiều,
ba seed để đo ổn định. Đây là lựa chọn phát triển trên chính dữ liệu thử,
chưa phải cấu hình tối ưu có kiểm chứng trên tập giữ riêng.

FCM có nhóm liên quan đến tổ chức tài liệu và nhiệm vụ, nhưng vẫn trộn thời
gian/biểu quyết/hành chính với quyết định; một số tiêu đề còn chung chung.
Silhouette và độ ổn định không bảo đảm nhóm đúng chủ đề. Chưa so sánh với
gom cụm phân cấp hoặc nhãn chủ đề độc lập. Cần đánh giá thêm trước khi dùng
FCM làm mặc định chất lượng cao.

Nội dung được gắn liên kết ID tới căn cứ nhưng còn lời lặp, câu nguồn ở những vị trí
fallback và đôi chỗ chuyển văn nói chưa trọn vẹn. Mục kết luận hiện tìm theo
từ khóa/lượt phát biểu, có thể bỏ sót cách kết luận khác trên mẫu mới.
Chưa chứng minh ánh xạ đúng mọi mẫu chi tiết có nhiều chủ đề đặc thù.

| Nội dung rà trực tiếp | Transcript chuẩn + LLM | Transcript ASR + LLM |
| --- | --- | --- |
| Chủ trì/thư ký/thành viên khác | Minh / Lan / Huy | Đúng các ô metadata |
| Mở đầu và địa điểm | 09:00, 03/10/2026, B201 | Đúng sau chuẩn hóa địa điểm |
| Kết thúc | 09:02 cùng ngày | Để trống; lời kết thúc bị mất/không đủ căn cứ |
| Hạn 06/10 | Có nêu rút/bác bỏ, không coi là hạn cuối | Có câu bác bỏ, còn lời ASR lỗi |
| Lan danh sách trước 05/10, phân quyền trước công bố | Giữ được trong nội dung/kết luận | Có ý liên quan nhưng còn tên “làng” và câu đứt đoạn |
| Huy 20 tài liệu trước 12/10 | Giữ được trong nội dung/kết luận | Số/hạn còn có, chủ thể “quy” chưa được sửa đúng ở một số câu |
| Biểu quyết | 3 / 3 / 0, 100% | 3 / 3 / 0, 100% |
| Bản dùng trực tiếp không rà soát | Chưa chấp nhận | Chưa chấp nhận |

Bản ASR còn các mảnh `t`, `T`, `Đã`, `Nghe`, tên sai và câu thiếu. Một số câu
LLM diễn giải thêm từ các mảnh này vẫn lọt qua kiểm tra heuristic. Vì vậy bản
ASR minh họa là **kết quả thử nghiệm có lỗi**, chưa đạt yêu cầu văn phong/độ đúng
để sử dụng trực tiếp. Cần rà căn cứ/clip hoặc cải thiện đầu vào; thêm LLM hiện
chưa giải quyết được mất nội dung do pipeline âm thanh.

Đã xem đủ **18 trang của 6 DOCX LLM**, mỗi file 3 trang. Các bản tham chiếu
sau sửa renderer có hash PNG trùng bản đã xem; các trang ASR thay đổi được xem
lại. Không phát hiện chữ chồng/tràn. Giữ cả lỗi dấu ngoặc `Về việc)` có sẵn
trong mẫu và câu ký cố định theo chính sách bảo toàn. Câu qua trang và vùng ký
nhiều khoảng trắng kế thừa bố cục mẫu, không phải phần chữ bị mất.

Demo tạo lại thực trả HTTP 200 trên bản sao run; DOCX có văn bản khớp bản ASR
FCM đã kiểm tra. Mở [pilot trong demo](http://127.0.0.1:8000/runs/llm-fcm-pilot-20261010).
Run gốc được giữ nguyên.

## Kiểm tra tài liệu và mã

- DOCX là văn bản/paragraph Word chỉnh sửa được. Mọi phần ZIP ngoài
  `word/document.xml` được kiểm tra nguyên byte; không đổi styles, quan hệ,
  header/footer hoặc chữ ký của mẫu.
- Kiểm tra gốc/đầu ra bao gồm đề mục sẵn, nhãn, inline formatting và native
  paragraphs cho các chủ đề mới; không coi số trang tăng do thêm nội dung là
  lỗi bảo toàn mẫu.
- DOCX minh họa cuối được render bằng bộ Documents runtime/LibreOffice,
  kiểm tra từng trang; QA lưu ở `data/evaluations/llm_fcm_20261010_release/qa`.
- Kiểm thử có ca đổi số, mất số, đổi chủ thể, tự thêm hoàn thành, thiếu ID,
  output hết token, FCM co tâm, duplicate ownership, bảo toàn package và rollback.
- **72 kiểm thử đạt**; Ruff và mypy phần minutes/web (17 source files) đều qua.
  Hai cảnh báo deprecation sẵn có của Starlette/httpx/anyio không chặn kiểm thử.

## Giới hạn và bước tiếp theo

- Không có nhãn biên bản người kiểm sửa; chưa đo đầy đủ độ tự nhiên, giữ ý
  hoặc tỷ lệ hallucination trên tập độc lập. ID coverage không chứng minh
  semantic completeness; các câu LLM vẫn mang trạng thái cần kiểm tra.
- ASR đã mất/loại 6 lượt thì LLM văn bản không có căn cứ phục hồi phần đó.
- Kiểm tra số/từ bảo vệ có thể từ chối cả sửa hợp lệ; bảng cảnh báo cần được
  đọc cùng bản sửa và căn cứ. Model nhẹ hiện chạy được nhưng chưa đủ bằng
  chứng để bảo đảm sửa ASR và biên tập đúng trong mọi bối cảnh.
- Metadata hiện có bộ chuẩn hóa tiếng Việt bảo thủ; còn phải thử mâu thuẫn
  nhiều ngày, nhiều vòng biểu quyết, cách ghi thời gian và mẫu khác nhau.
- PDF có chữ, PDF scan, ảnh/OCR và DOCX tái dựng **chưa có trong increment này**.
- Tiếp theo: mở rộng số cuộc họp/mẫu và lập tập kiểm tra riêng, cải thiện đơn vị
  ngữ nghĩa/FCM, đo WER/CER và lỗi fact có phân loại, rồi mới quyết định dữ liệu
  và fine-tuning. Ưu tiên chất lượng nguồn ASR vẫn cần được thảo luận riêng.

Hướng dẫn sử dụng: [LLM_FCM_MINUTES.md](../LLM_FCM_MINUTES.md).
Yêu cầu đầy đủ và lịch sử quyết định:
[plan DOCX/PDF/scan](../PLAN_LLM_BIEN_BAN_DOCX_PDF_SCAN_2026-10-09.md).
