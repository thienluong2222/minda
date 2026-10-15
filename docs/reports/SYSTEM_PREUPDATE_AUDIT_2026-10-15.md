# Kiểm tra hệ thống trước cập nhật — 15/10/2026

## 1. Mốc kiểm tra và phạm vi

- Nhánh: `codex/llm-fcm-minutes`.
- Mã nguồn được kiểm tra: `e1fb8c2c7b6bd1c4689c966610f1a137e44597c4`.
- Kiểm tra môi trường, cấu hình, SQLite, unit/integration/experiment tests, lint,
  type checking, suy luận model thật, HTTP demo và artifact của các run gần nhất.
- Không sửa mã nguồn hoặc cấu hình trong đợt kiểm tra. Không tải model mới.
- Ba timeline gốc đã được kiểm tra hash trước/sau và giữ nguyên.
- Giữ nguyên file có sẵn chưa được Git theo dõi:
  `docs/PLAN_FIX_SPEAKER_MULTI_SOURCE_HIGH_RISK_2026-10-03.md`.
- Log, script smoke và JSON chi tiết:
  [thư mục bằng chứng](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp).

## 2. Kết luận

Hệ thống khởi động được; model và các API chính hoạt động. Unit/integration tests
được xác nhận qua 214 bài đạt trong sandbox và bài Quick Look còn lại đạt khi chạy
với quyền macOS. Tuy nhiên, chất lượng giữ lời nói còn một lỗi đã tái hiện bằng
model thật: ASR đọc đúng nhưng bộ lọc midpoint xóa từ đầu/cuối câu.

Nên dùng mốc này làm baseline trước cập nhật. Chưa đủ cơ sở coi việc xuất DOCX thành
công hoặc phủ đủ ID là bằng chứng biên bản đúng hoàn toàn.

## 3. Môi trường và kiểm thử

| Hạng mục | Kết quả |
| --- | --- |
| Python | 3.11.14 |
| Doctor | 11 kiểm tra đều OK |
| FFmpeg/ffprobe | Có |
| SQLite | `PRAGMA quick_check` trả `ok` |
| Cache model | Có PhoWhisper-medium, pyannote segmentation, ECAPA, Qwen và E5 |
| Dung lượng trống tại lúc kiểm tra | Khoảng 23,19 GB |
| Unit + integration | 215 bài: ban đầu 214 đạt, 1 lỗi sandbox; bài lỗi chạy riêng đạt |
| Experiment tests không cần model | 21 đạt, 1 model smoke bị loại theo marker |
| Ruff toàn repo | 45 lỗi ở 4 file |
| Ruff format toàn repo | 5 file cần định dạng |
| Mypy toàn source | 4 lỗi `unused-ignore` ở 3 file; đã kiểm tra 93 file |
| Ruff phần minutes/web và script LLM mới | Đạt |
| Mypy minutes/web | Đạt, 17 source files |
| Git diff check | Đạt |

Lệnh kiểm thử:
```bash
.venv/bin/python -m pytest tests/unit tests/integration -q --durations=10
.venv/bin/python -m pytest tests/experiments -m 'not model_smoke and not dataset and not slow and not e2e' -q
.venv/bin/ruff check . --output-format=json
.venv/bin/ruff format --check .
.venv/bin/mypy src/meeting_pipeline
```

### Lỗi Quick Look do môi trường

`test_visual_qa_rendering` ban đầu gặp `qlmanage returned 255` trong sandbox.
Chạy lại riêng bài này với quyền macOS: **1 passed**. Không thay mã hoặc fixture.

Không coi lần chạy ban đầu là bộ test toàn repo đạt nguyên trạng trong sandbox.
Kết quả 215 bài được xác nhận từ lần chạy chính và lần chạy lại riêng bài bị chặn.

### Các lỗi kiểm tra mã sẵn có

Ruff:
- `scripts/benchmark_minutes_pipeline.py`: 35 lỗi.
- `tests/unit/test_minutes_f1_parser.py`: 7 lỗi.
- `tests/unit/test_minutes_f2_schema.py`: 2 lỗi.
- `tests/unit/test_minutes_f4_render.py`: 1 lỗi.

Mypy:
- `src/meeting_pipeline/evaluation/speaker_metrics.py:10`.
- `src/meeting_pipeline/fusion/model.py:14,15`.
- `src/meeting_pipeline/domain/speaker_classifier.py:10`.

Cả 4 lỗi là `type: ignore` không còn cần thiết trong môi trường hiện có.
Các file đã khớp HEAD khi bắt đầu audit; lỗi không phát sinh từ sửa mã trong đợt này.

Năm file formatter báo:
- `scripts/evaluate_speaker_multisource.py`.
- `scripts/prepare_speaker_only_run.py`.
- `src/meeting_pipeline/speaker/clustering.py`.
- `tests/unit/test_minutes_f3_facts.py`.
- `tests/unit/test_speaker_source_quality.py`.

Log: `pytest.log/xml`, `visual_retry.log/xml`, `experiments.log/xml`,
`ruff.json`, `format.log`, `mypy.log`, `mypy_minutes.log` trong thư mục bằng chứng.

## 4. Kiểm tra suy luận model thật

### Qwen + E5 + FCM

Chạy suy luận mới từ snapshot local:
- E5 tạo ma trận **6 × 384**, giá trị hữu hạn, chuẩn L2 xấp xỉ 1.
- Batch embedding chưa có cache trước phép kiểm tra.
- FCM chọn 2 nhóm trên 6 câu thử: 3 câu cấu trúc thư mục, 3 câu quyền truy cập.
  Silhouette **0,1911**, stability **1,0**.
- Qwen trả đúng JSON yêu cầu, 65 prompt tokens và 6 generation tokens,
  `finish_reason=stop`, `cache_hit=false`.
- Toàn bộ smoke khoảng **8,46 giây**, gồm nạp model và E5.
- Đây là kiểm tra khả năng chạy; không đánh giá chất lượng viết biên bản.
- Peak MLX của yêu cầu JSON rất ngắn khoảng **2,47 GB**; không đại diện RAM toàn máy
  hoặc mức bộ nhớ của một cuộc họp dài.

Bằng chứng: [runtime_smoke.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/runtime_smoke.json).

### Audio → pyannote → ECAPA → PhoWhisper → fusion

Chạy chính `MultiSourceFusionPipeline`, backend của demo, với audio VIVOS ghép
hai câu và khoảng im lặng, dài **11,1875 giây**, một nguồn, không enrollment.
Dùng cache weights hiện có; artifact và cache ASR của phép kiểm tra nằm riêng.
`torch.set_num_threads(2)` chỉ áp dụng trong tiến trình smoke.

- Pyannote được gọi 1 lần.
- Tạo 2 dòng timeline, cùng nhãn vô danh ổn định `Người lạ 1`.
- ASR và export hoàn tất, khoảng **96,01 giây** gồm nạp model và các bước pipeline.
- Không dùng thời gian này để suy ra tốc độ cuộc họp đa nguồn.

| Nội dung | Candidate ASR gốc | Sau lọc và fusion |
| --- | --- | --- |
| Câu 1 | trở nên thụ động | nên thụ động |
| Câu 2 | cũng khiến cho họ dè dặt | khiến cho họ dè |
| WER | 0% | 30% |
| CER | 0% | 31,71% |
| Số từ bị xóa so với 10 từ tham chiếu | 0 | 3 |

Các candidate đều được quality checker chấp nhận. Timestamp của “trở”, “cũng”,
“dặt” giao với core, nhưng midpoint nằm ngoài core nên bị xóa.
Smoke đạt về khả năng chạy; chất lượng giữ từ trên ca này còn lỗi.

Bằng chứng: [audio_smoke.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/audio_smoke.json),
[audio_smoke_boundaries.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/audio_smoke_boundaries.json).

## 5. Demo và API

Demo ban đầu chưa chạy ở cổng 8000. Đã khởi động lại bằng:
```bash
.venv/bin/meeting-pipeline serve --host 127.0.0.1 --port 8000
```

Không có job queued/running trước khi khởi động. Các kiểm tra GET đều trả HTTP 200:
- `/health`.
- `/api/minutes/models`.
- Trang chủ và `/static/demo.js`.
- Trang kết quả run mới nhất.
- API biên bản và danh sách người nói.
- Tải DOCX và ảnh preview trước/sau.

HTML kết quả có các điều khiển LLM, FCM và chế độ biên bản.
Đây là kiểm tra HTTP/HTML; chưa chạy lại thao tác giao diện bằng trình duyệt.

[Run mới nhất trên demo](http://127.0.0.1:8000/runs/e059954d-10e7-40d6-abe9-d7d7cf0fae4a).
Bằng chứng: [http_checks.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/http_checks.json).

## 6. Hai run ngày 10/10 sau pilot cũ

- `new test`: run `72d2d9a1-fbf2-4eee-95b4-03b130ee560e`.
- `Test 10/10`: run `9a4857a4-6ab9-4677-a18b-651f9bb3a784`.

SHA-256 của cả ba file upload trong mỗi run khớp ba audio điện thoại của
`fpt_tts_pilot_20261003`. Hai run cùng kịch bản, thứ tự nguồn khác nhau;
không tính là hai cuộc họp độc lập.

| Chỉ số | Kết quả trên mỗi run |
| --- | --- |
| Timeline | 15 dòng, đều `transcribed` |
| Dòng dưới 1 giây | 2 |
| Dòng overlap | 0 |
| Nhãn chưa xác định | 2 dòng, khoảng 107,3–107,7 giây |
| Danh sách người nói hiển thị | Minh / Lan / Huy, không trùng |
| WER transcript | 7,4427% |
| CER transcript | 5,3396% |
| S/D/I | 21 / 18 / 0 trên 524 đơn vị tham chiếu |
| WER sau sửa LLM | 7,2519% |
| CER sau sửa LLM | 5,2114% |
| Sửa transcript được chấp nhận | 1: “lan ngữ danh sách” → “lan gửi danh sách” |
| FCM | 4 cụm, silhouette 0,2588, stability 1,0 |
| Đoạn FCM mơ hồ | 5/16 |
| Phủ đủ ID nội dung hợp lệ | Có |

Chuẩn hóa để tính WER/CER: NFC, chữ thường, bỏ dấu câu, gộp khoảng trắng;
không đổi số viết bằng chữ. WER dùng đơn vị tách theo khoảng trắng.
Các chỉ số được tính trên artifact có sẵn, không chạy lại hai cuộc họp này.

Kết quả mới cập nhật nhận định trước đây “LLM chưa sửa được lỗi nào”:
nhận định đó đúng cho pilot cũ; hai run mới có một sửa đổi hữu ích.
Mức cải thiện còn rất nhỏ, chưa đủ kết luận khả năng sửa ASR tổng quát.

Ba DOCX được kiểm tra gồm hai run trên và pilot cũ:
ZIP CRC hợp lệ, XML đọc được, chỉ `word/document.xml` thay đổi so với mẫu
normalized; các phần còn lại và danh sách phần trong ZIP được giữ nguyên.
Không render lại toàn bộ tài liệu trong audit này; API preview hiện có đọc được.

Bằng chứng: [latest_run_checks.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/latest_run_checks.json),
[latest_minutes_checks.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/latest_minutes_checks.json).

## 7. Các điểm cần xử lý trước hoặc trong đợt cập nhật

### P1 — Mất từ do midpoint đã tái hiện trên model thật

Mã tại [segment_asr.py](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/asr/segment_asr.py:265)
chỉ giữ token có midpoint trong core. Đây là điều kiện sở hữu từ quá chặt
với timestamp ASR xấp xỉ.

Ngoài smoke mới, run gần nhất có các ví dụ:

| Từ | Timestamp tuyệt đối | Core | Midpoint bị loại |
| --- | --- | --- | --- |
| bộ | 8,64–9,48 | 0,30–8,75 | 9,06 |
| vắng | 16,33–17,33 | 9,50–16,60 | 16,83 |
| chỗ | 25,41–26,07 | 17,40–25,70 | 25,74 |

Các candidate đã được chấp nhận và có đoạn giao với core.
Cần tách quy tắc chống trùng ở biên clip ASR nội bộ khỏi quy tắc gán người nói,
đồng thời lưu lý do loại từ và đối chiếu clip liền kề.
Không áp dụng quy tắc giữ mọi candidate vô điều kiện.

Bằng chứng: [boundary_word_examples.json](/Users/thien/Documents/School/Luận văn/data/evaluations/system_preupdate_20261015_w4hkkfbp/boundary_word_examples.json).

### P1 — Một nguồn báo overlap có thể làm bỏ ASR ở mọi nguồn

[speaker_turns.py:114](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/pipeline/speaker_turns.py:114)
lấy số người lớn nhất giữa các nguồn.
[multi_source_fusion.py:528](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/pipeline/multi_source_fusion.py:528)
đưa vùng hai người nói vào hàng `not_run` và bỏ ASR.

Đã xác nhận đường mã còn nguyên; lỗi overlap giả có bằng chứng ở báo cáo 09/10.
Hai run FPT mới không xuất hiện overlap, nên chưa tái đánh giá lỗi này trên
một cuộc họp đa nguồn có overlap thật trong audit hôm nay.

### P2 — E5/FCM và đặt tên còn giới hạn chất lượng

- Chia đoạn theo dấu câu và giới hạn từ; chưa có bước tách ý ngữ nghĩa.
- Đoạn ngắn được ghép câu trước khi embedding, có thể bị nhiễm chủ đề.
- Tên cụm lấy từ batch biên tập đầu tiên hợp lệ, tối đa 6 đoạn; chưa tổng hợp
  toàn cụm hoặc kiểm tra khác biệt tên giữa các cụm.
- Cụm đầu của run mới mang tên “Biên bản họp nhóm dự án Sao Khuê”, chưa mô tả
  một chủ đề cụ thể.
- Membership mơ hồ được lưu, chưa được dùng để phân xử lại.
- Số cụm chỉ định tay bỏ qua một số ngưỡng chất lượng của chế độ tự động.
- Chưa có nhãn chủ đề hoặc tập cuộc họp độc lập để xác nhận chất lượng.

### P2 — Chất lượng viết và danh tính còn cần đối chiếu

Model report của run mới có bốn lần giữ câu gốc do nguy cơ thay đổi số/chủ thể/
trạng thái. Kiểm tra heuristic không phát hiện mọi sai lệch ngữ nghĩa.
Hai lượt ngắn còn chưa xác định danh tính; không suy ra lỗi nhận diện đã được
giải quyết hoàn toàn từ việc danh sách người nói hết trùng.

### P3 — Kiểm tra toàn repo và truy vết cấu hình

- Dọn 45 lỗi lint, 5 file format và 4 unused-ignore để có baseline sạch.
- Manifest run chưa lưu Git revision và toàn bộ cấu hình segmentation/ASR.
  Model revision đã có nhưng chưa đủ quy kết chênh lệch chất lượng cho một lần sửa mã.
- Tham số `minimum_silence_ms` được đưa vào VadConfig nhưng đường VAD pyannote
  hiện không dùng tham số này trong hàm trích khoảng; cần kiểm tra hợp đồng cấu hình
  khi có đợt cập nhật segmentation được chấp thuận.

## 8. Thứ tự đề xuất cho đợt tiếp theo

1. Sửa đường giữ từ và chống trùng ở biên; nghiệm thu bằng raw-ASR → final S/D/I
   trên các clip hiện có, gồm câu ngắn và biên đổi người.
2. Xử lý bất đồng overlap giữa các mic, giữ đầy đủ bằng chứng theo nguồn.
3. Cải thiện đơn vị embedding, tận dụng membership mơ hồ và đặt tên sau khi có
   đầy đủ nội dung cụm.
4. Bổ sung nhãn chủ đề nhỏ, đánh giá nhóm và biên bản trên tập riêng.
5. Làm sạch các kiểm tra mã và ghi Git/config vào manifest.

PDF/ảnh scan, OCR và fine-tuning vẫn thuộc phần chưa triển khai.
Các đề xuất trên chưa được áp dụng vào mã trong đợt audit.

## 9. Tài liệu liên quan

- [Hướng dẫn LLM–FCM](/Users/thien/Documents/School/Luận văn/docs/LLM_FCM_MINUTES.md).
- [Báo cáo pilot 10/10](/Users/thien/Documents/School/Luận văn/docs/reports/LLM_FCM_EVALUATION_2026-10-10.md).
- [Chẩn đoán mất từ 09/10](/Users/thien/Documents/School/Luận văn/docs/reports/LATEST_RUN_WORD_LOSS_DIAGNOSTIC_2026-10-09.md).
