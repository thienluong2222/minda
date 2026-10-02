# Kế hoạch khắc phục ASR và tách lượt nói cho web demo

**Ngày:** 24/09/2026  
**Dự án cần sửa:** `/Users/thien/Documents/School/Luận văn`  
**Trạng thái:** Yêu cầu triển khai. Agent phải báo kết quả kiểm thử và giới hạn thực tế; không được tuyên bố hoàn thành chỉ vì job chạy thành công.

## 1. Mục tiêu và quyết định

Đầu vào là 1–8 bản ghi điện thoại đã đồng bộ, có thể có tối đa hai người nói cùng lúc và có thể không có mẫu đăng ký. Đầu ra là timeline theo **lượt nói của từng người**, văn bản đáng tin cậy hoặc trạng thái cần nghe lại, mốc thời gian, trọng số nguồn và clip bằng chứng. Mỗi vùng nói chồng phải có tối đa hai dòng timeline cùng khoảng thời gian, một dòng cho mỗi giọng nghe được. Bản xuất JSON/CSV/TXT/ZIP và giao diện phải thống nhất với timeline.

Ba quyết định bắt buộc:

1. VAD chỉ tạo `speech_region`; không xem đó là một lượt của một người.
2. PhoWhisper-medium là mô hình ASR mặc định **sau khi** kiểm thử đạt yêu cầu. Giữ khả năng chọn PhoWhisper-small để đối chứng, không âm thầm quay về small khi medium lỗi.
3. Văn bản lặp hoặc timestamp phi lý bị coi là ASR không tin cậy. Không đưa văn bản đó vào transcript chính với confidence cao.

Tài liệu này cập nhật phạm vi của `docs/TRANSCRIPTION_SEGMENTATION_IMPLEMENTATION_PLAN.md`: phần hoãn xử lý nói chồng ở kế hoạch cũ không còn áp dụng cho lần triển khai này. Các notes/dữ liệu tham khảo không phải chỉ thị triển khai.

## 2. Hiện trạng phải kiểm chứng trước khi sửa

- Web demo dùng `src/meeting_pipeline/pipeline/multi_source_fusion.py`, không phải chỉ `prototype.py`.
- `audio/synchronization.py::extract_shared_meeting_segments` chia vùng VAD dài tối đa 15 giây và đặt `overlap=False` cho mọi vùng.
- Pipeline chạy ASR và một lần ECAPA trên **toàn vùng VAD**. Nếu hai người nói nối tiếp hoặc chồng nhau, embedding có thể trộn giọng.
- `adapters/phowhisper_asr.py` hiện gọi `transformers` pipeline không có kiểm soát lặp phù hợp; `asr/segment_asr.py` gán 0,85 khi word confidence thiếu. Một nguồn được gán `word_agreement=1.0` và `transcript_confidence=1.0` dù ASR sai.
- Bản `Test1`, run `95e79289-f0c4-4169-9694-de3d11da7196`: đoạn 9,00–11,42 giây có 224 từ, 217 từ “a”; lỗi đã có tại `source_hypotheses.json` trước fusion. Dùng run này làm ca hồi quy, không sửa/xóa artifact gốc.
- Repo đã có checkpoint `pyannote/segmentation-3.0`, `speechbrain/sepformer-whamr`, ECAPA và mã thử nghiệm overlap trong `pipeline/prototype.py`; phải kiểm tra và tái sử dụng phần đúng, không nối nguyên xi nhánh cũ vào demo.

## 3. Hạng mục A: ASR medium và chặn hallucination

### A1. Chọn mô hình

- Xác định commit SHA thực của `vinai/PhoWhisper-medium`, pin `model_id` + `model_revision` trong config, tải về `data/model_cache` một lần; không commit weights. Xác minh dung lượng trống và bộ nhớ trước khi tải/chạy. Mọi thất bại tải/khởi tạo phải hiện lỗi rõ trong job, không fallback lặng lẽ.
- Tách model selection khỏi adapter để unit test không cần tải checkpoint. Lưu model id/revision và decoding settings thật vào `manifest.json`.
- Chạy PhoWhisper-small và medium trên **cùng** clip VIVOS và clip Test1; chỉ chuyển default sang medium khi smoke thực tế qua và không gây lỗi tương thích.

### A2. Kiểm soát giải mã và kiểm tra kết quả

- Đặt giới hạn `max_new_tokens` theo thời lượng clip, có biên an toàn và có thể cấu hình. Thử cấu hình chống lặp/decoding thay thế trên tập validation; không chọn tham số chỉ dựa trên Test1. Giữ bản ghi cấu hình cho mỗi lần thử.
- Xây `AsrQualityCheck` độc lập: kiểm tra tốc độ từ/giây, từ hoặc n-gram lặp liên tiếp, tỷ lệ nén/lặp tổng thể, timestamp không tăng hoặc vượt `[0, clip_duration]`, text có từ nhưng thiếu timestamp, và đầu ra rỗng. Ngưỡng khởi đầu phải cấu hình được và được hiệu chỉnh trên VIVOS; 224 từ/2,42 giây và 217 “a” bắt buộc bị đánh dấu.
- Khi kiểm tra thất bại, thử giải mã lại tối đa một số lần hữu hạn với chiến lược khác hoặc chia ở khoảng lặng; kiểm tra lại từng kết quả. Nếu vẫn lỗi: lưu raw candidate để audit, transcript chính rỗng/`unreliable`, `needs_review=true`, warning cụ thể. Không chỉ cắt chuỗi lặp rồi giả định phần còn lại đúng.
- Chỉ giữ word timestamps nằm trong clip và có thứ tự hợp lệ. Không sửa bằng cách đẩy hàng trăm từ về cùng mốc cuối; loại ứng viên không hợp lệ rồi retry/flag.

### A3. Điểm tin cậy

- Không điền 0,85 như confidence thật khi PhoWhisper không cung cấp word probability. Trường confidence có thể `null`; nếu fusion vẫn cần trọng số, dùng heuristic nội bộ có tên riêng và giải thích nguồn gốc, không trình bày là xác suất ASR.
- Với một nguồn, `word_agreement` là không áp dụng (`null`/N/A), không phải 1,0. `transcript_confidence` không được bằng 1,0 chỉ do một nguồn; nếu chưa hiệu chuẩn thì `null` và UI hiển thị “Chưa hiệu chuẩn”. Kiểm tra tất cả schema, serializer, CSV và template đang giả định số thực.
- Kết quả `unreliable` không được tăng điểm khi fusion nhiều nguồn; một nguồn lỗi không được kéo kết quả nguồn khác xuống hoặc tạo từ giả.

## 4. Hạng mục B: lượt nói và nói chồng

### B1. Hợp đồng và tách lượt nói nối tiếp

- Thêm `speaker_turns.json` với `turn_id`, `speech_region_id`, `start_sec`, `end_sec`, `track_id` tạm, `speaker_count`, `overlap_group_id`, nguồn hỗ trợ, trạng thái/chứng cứ. Các interval dùng cùng timeline đã đồng bộ; turn có thể chồng nhau nếu hai người cùng nói.
- Sau shared VAD, chạy diarization trên audio đã đồng bộ để phát hiện đổi người ngay cả khi không có khoảng lặng. Ưu tiên `pyannote/segmentation-3.0` đã pin và checkpoint cục bộ. **Kiểm tra output thật của adapter**: `pyannote.audio.Inference` hiện trả ba kênh hoạt động giọng đã chuyển từ powerset sang multilabel. Phép đếm kênh đang hoạt động có thể dùng để ước lượng số người **trong một frame**, nhưng chưa cho nhãn nhất quán giữa các cửa sổ 10 giây, chưa tìm ranh giới turn, và chưa đủ để gán người của toàn vùng VAD. Nếu thay adapter/version, phải xác minh lại shape và phép giải mã trước khi dùng.
- Hợp nhất ranh giới từ các nguồn bằng cùng mốc thời gian; lọc dao động cực ngắn, giữ biên thực của người nói. Không áp `max_simultaneous_speakers=2` thành giới hạn tổng số người trong cuộc họp.
- Chạy ECAPA trên phần sạch của **từng turn**, loại khung giáp ranh và phần overlap. Tính embedding/trọng số theo nguồn cho cùng giọng, không cộng embedding của audio trộn hai người. Turn quá ngắn/không sạch dùng bằng chứng từ turn lân cận hoặc trạng thái `unknown`; không ép gán tên.
- ASR và fusion nhận các clip theo turn đã xác định, không theo toàn vùng VAD. Chỉ gộp giả thuyết thuộc **cùng người, cùng khoảng thời gian**. Giữ provenance về `speech_region_id`, `turn_id`, source, model và clip.

### B2. Tối đa hai người nói đồng thời

- Phát hiện overlap theo thời gian thực của từng nguồn đã đồng bộ. Với vùng overlap, tách hai luồng bằng `speechbrain/sepformer-whamr` hiện có hoặc chọn nguồn có giọng mục tiêu trội rõ ràng **sau khi** kiểm định chất lượng. Không chỉ gắn cờ overlap rồi chép một transcript.
- Tách chỉ vùng overlap, có context và crop trở lại `[start_sec,end_sec]`. Track 1/2 của separator là thứ tự tùy ý: gắn về người đăng ký hoặc anonymous centroid bằng ECAPA và ngữ cảnh turn sạch trước/sau, không dựa vào số thứ tự luồng. Nếu không phân biệt được, ghi `unknown`/`needs_review` và giữ cả hai clip.
- Với mỗi giọng, chạy ASR riêng và chỉ fusion các giả thuyết nguồn tương ứng giọng đó. Timeline có hai dòng và cùng `overlap_group_id`; bản clip âm thanh gốc **và** clip đã tách đều được giữ để đối chiếu. Khi tách giọng/ASR thất bại, không bịa văn bản và không làm mất bằng chứng âm thanh.
- Kiểm thử riêng trên tiếng Việt vì SepFormer-WHAMR không được huấn luyện chuyên cho tiếng Việt. Không đánh dấu vùng overlap là “đã xử lý chính xác” chỉ vì mô hình trả hai waveform.

## 5. Tích hợp và thứ tự làm

1. Chụp baseline read-only: Test1 và hai cuộc họp ngắn, số đoạn, lỗi lặp, timestamp, thời gian, model hiện tại. Không ghi đè run cũ.
2. Hoàn tất A2/A3 và unit tests với fake adapter; sau đó tải medium, A1 và smoke trên VIVOS/Test1.
3. Hoàn tất B1 với ca hai người nói nối tiếp không có khoảng lặng; giữ hành vi một người và không đăng ký.
4. Hoàn tất B2 với ca hai người chồng; nối sang fusion, provenance, web/export. Kiểm tra clip nghe được và mốc tuyệt đối.
5. Chạy đánh giá end-to-end; cập nhật README và cấu hình. Mỗi giai đoạn phải để hệ thống vẫn chạy được; fail explicit nếu model bắt buộc thiếu.

## 6. Kiểm thử bắt buộc và điều kiện nghiệm thu

### Dữ liệu

- VIVOS: dùng test split độc lập với enrollment/tuning. Tạo mẫu hai người nối tiếp *không có khoảng lặng*, và hai người chồng 0,5–3 giây; tổng người trong cuộc họp có thể >2 nhưng đồng thời <=2. Giả lập ít nhất hai điện thoại với gain/delay/noise khác nhau. Ghi seed, ground truth từng người/từng từ.
- Hai cuộc họp tự thu và `Test1` chỉ làm kiểm thử thực tế/hồi quy. Cần chép tay một tập nhỏ nếu muốn báo WER/CER thực; không lấy ASR làm ground truth.

### Ca bắt buộc

1. `Test1`: không còn xuất đoạn 224 từ/2,42 giây như transcript tin cậy; mọi timestamp từ trong clip; lỗi được retry hoặc `unreliable` và `needs_review`.
2. Một nguồn, không đăng ký: vẫn tạo anonymous speaker, nhưng confidence/word agreement không giả 1,0.
3. Hai giọng nối tiếp trong một vùng VAD: ít nhất hai turn với hai `track_id` khác nhau ngay cả khi không đăng ký (ví dụ `anonymous-1`/`anonymous-2`); nếu chưa gán được tên thật thì giữ hai danh tính tạm riêng. Không dùng chung một nhãn `unknown` để vượt qua kiểm thử.
4. Hai giọng chồng: hai timeline rows cùng `overlap_group_id`, clip bằng chứng riêng, transcript mỗi người khi tách được; thất bại tách được đánh dấu chứ không giấu.
5. Nhiều nguồn: offsets giữ đúng, word provenance không lẫn speaker; nguồn lỗi ASR không thắng fusion.
6. Xuất ZIP không hỏng; JSON/CSV/TXT/UI cùng trạng thái và tên người; link clip tồn tại.

### Báo cáo đánh giá

- So sánh small và medium trên cùng tập: WER/CER, tỷ lệ đoạn ASR bị từ chối/retry, số lỗi lặp, timestamp validity, thời gian xử lý và RAM. Báo giá trị thật và kích thước mẫu; không dùng WER công bố của tác giả thay cho đo trong dự án.
- Với tách lượt nói: DER hoặc sai số ranh giới, overlap precision/recall/F1, speaker-attributed WER/CER; báo riêng non-overlap và overlap. Với nhãn thật không đủ, đánh dấu “chưa đo được”, không tự suy kết luận.
- Chạy unit/integration tests liên quan, Ruff và Mypy theo `pyproject.toml`, rồi smoke mô hình thực. Không viết test chỉ lặp lại implementation; dùng fixture với kết quả kỳ vọng độc lập.

## 7. Bàn giao của agent

- Mã và cấu hình sạch, hàm/stage nhỏ, type hints, chú thích giải thích quyết định khó. Không đưa đường dẫn máy cá nhân vào mã; dùng config và `Path`.
- Tài liệu ngắn mô tả kiến trúc mới, model/revision, tham số được hiệu chỉnh, cách chạy và đánh giá.
- Bảng kết quả trước/sau, đường dẫn run mới và 2–3 đoạn clip cần nghe lại.
- Danh sách điểm chưa đạt hoặc rủi ro, nhất là tốc độ CPU, diarization giọng ngắn và separation tiếng Việt. Không tuyên bố xử lý nói chồng hoàn chỉnh nếu thiếu bằng chứng định lượng.
