# Giữ từ ở biên ASR — 15/10/2026

## Mốc và phạm vi

- Mã trước sửa: `bdf505b`; mã sửa: `4451343` và `5f2b02a`, nhánh `codex/llm-fcm-minutes`.
- Policy: `interval_edges_seam_alignment_v1`.
- Sửa hậu xử lý từ và đối chiếu clip ASR cùng lượt nói.
- Giữ nguyên model, VAD, đồng bộ, phân cụm người nói và cấu hình LLM/FCM.
- Run cũ, transcript người dùng và biên bản đã chỉnh được giữ nguyên.
- Artifact đánh giá: [thư mục bằng chứng](/Users/thien/Documents/School/Luận văn/data/evaluations/asr_boundary_fix_20261015__h293dpp).

## 1. Thay đổi

### Giữ từ ở biên ngoài của lượt nói

Thay điều kiện midpoint tuyệt đối bằng quy tắc có loại biên:

- Giữ từ hợp lệ có midpoint trong core.
- Ở biên ngoài, giữ thêm từ có timestamp giao với core và vẫn nằm trong clip
  đã được chặn tại lượt khác/overlap.
- Từ hoàn toàn trong ngữ cảnh ngoài core được loại và ghi lý do.
- Từ khôi phục mang `time_status=uncertain`; không ép timestamp vào core.
- Timestamp vượt clip, đảo thứ tự hoặc điểm thời gian ngoài core bị loại và lưu bằng chứng.
- Từ có timestamp bắt đầu bằng kết thúc tại một điểm dương trong core được giữ chữ,
  đánh dấu `uncertain`, không tự kéo dài thời gian. Đây là trường hợp của từ “án”.
- Candidate `unreliable/failed/empty/not_run` không được phục hồi thành nội dung.

Mã: [boundary_words.py](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/asr/boundary_words.py:17),
[segment_asr.py](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/asr/segment_asr.py:160).

### Đối chiếu các clip cắt nội bộ

Backend đọc đủ kết quả của nhóm `asr_chunk_group_id` trước khi fusion nhóm đó.

- Chỉ so các clip liền nhau, thuộc cùng nhóm, core liên tiếp và audio có ngữ cảnh chung.
- Căn hàng chuỗi theo thứ tự; ghép các từ giống nhau khi timestamp đủ tương đồng.
- Điều kiện ghép hiện tại: khoảng giao ít nhất 50% thời lượng ngắn hơn và khoảng
  cách midpoint không quá `max(0.12 giây, nửa thời lượng ngắn hơn)`.
- Mỗi lần phát âm được gán một chủ sở hữu; một nhóm khớp không chứa hai từ từ
  cùng clip, nhằm bảo vệ lặp thật.
- Từ chỉ xuất hiện trong ngữ cảnh một clip có thể chuyển sang core phù hợp nếu
  nguồn tương ứng của core đó có ASR trạng thái `transcribed`.
- Không đối chiếu xuyên nhóm người nói hoặc overlap.
- Không đổi trạng thái một nguồn bị loại/chưa chạy để nhận từ. Nếu chưa tìm được
  chủ sở hữu hợp lệ, lưu `owner_source_unavailable` và cảnh báo cần rà soát.

Các ngưỡng ghép là heuristic phát triển, chưa được hiệu chỉnh trên tập giữ riêng.

### Truy vết và demo

- Thêm trường tùy chọn `SourceHypothesis.word_boundary_audit`; artifact cũ vẫn đọc được.
- Mỗi từ lưu chữ gốc, timestamp local/tuyệt đối, core/clip, quyết định, lý do,
  lượt đã nhận từ và lượt sở hữu.
- Có `word_boundary_audit.json` trong run và gói ZIP.
- Manifest và routing metadata lưu phiên bản policy, loại biên và group ID.
- Có clip `clips/asr_context/<turn>/<source>.wav` cho các trường hợp cần đối chiếu.
- Timeline đánh dấu cần kiểm tra và hiển thị bảng “Đối chiếu từ ở biên” cùng audio.
- Cảnh báo khôi phục/đối chiếu là thông tin rà soát, không tự làm adaptive router
  gọi thêm mic. Cảnh báo chất lượng ASR khác vẫn có tác dụng kích hoạt fallback.
- Cache decoder thô được tái sử dụng; policy được áp dụng sau khi đọc cache.

## 2. Kiểm thử

- **231 unit/integration tests đạt**, gồm 16 ca bổ sung so với baseline 215.
- Kiểm tra các từ đã mất: “trở”, “cũng”, “dặt”, “bộ”, “vắng”, “chỗ”.
- Kiểm tra timestamp lệch khiến một từ bị giữ hai lần hoặc bị cả hai clip bỏ.
- Giữ lặp thật “không không được” và cùng chữ ở hai thời điểm khác nhau.
- Kiểm tra chuyển từ chỉ có ở clip ngữ cảnh, nguồn đích bị loại, nhóm khác người,
  core không liên tiếp, timestamp không hợp lệ và candidate bị từ chối.
- Integration xác nhận đối chiếu trước fusion, cảnh báo, artifact và clip ngữ cảnh.
- Các kiểm thử overlap, người nói liền kề, adaptive routing, biên bản Word và web
  hiện có vẫn đạt.
- Ruff check/format đạt trên 8 file Python liên quan.
- Mypy đạt trên 5 file nguồn đổi, với `--follow-imports=silent`.
- Các lỗi toàn repo đã nêu trong audit trước cập nhật chưa được sửa trong đợt này.
- Ba cảnh báo deprecation sẵn có không chặn kiểm thử.

Log: `pytest.log/xml`, `mypy.log` trong thư mục bằng chứng.

## 3. Kiểm tra model thật

Chạy chính backend demo `MultiSourceFusionPipeline` với hai câu VIVOS ghép
khoảng im lặng, dài 11,1875 giây, một mic, không enrollment.
Model: pyannote segmentation-3.0, ECAPA và PhoWhisper-medium hiện có trong cache.

| Kết quả | Trước sửa | Sau sửa |
| --- | --- | --- |
| Câu 1 | nên thụ động | trở nên thụ động |
| Câu 2 | khiến cho họ dè | cũng khiến cho họ dè dặt |
| WER | 30% | 0% |
| CER | 31,71% | 0% |
| S/D/I | 0 / 3 / 0 | 0 / 0 / 0 |

Smoke model thật chạy trên `4451343`; phần giữ timestamp điểm được kiểm tra sau đó
bằng replay FPT và bộ 231 bài hồi quy.

ASR gốc trước sửa đã đọc đúng 10 từ; thay đổi khắc phục mất từ tại bộ lọc.
Sau sửa giữ đúng 10/10 từ trên ca tái hiện này, không chứng minh WER=0 trên cuộc họp dài.

Lượt sau sửa chạy suy luận thật với cache ASR riêng chưa có kết quả; khoảng 52,79 giây,
gồm nạp model và pipeline, giới hạn torch 2 luồng trong script kiểm tra.
Không dùng chênh lệch với 96 giây của audit để kết luận tối ưu tốc độ.

Bằng chứng: [audio_smoke.json](/Users/thien/Documents/School/Luận văn/data/evaluations/asr_boundary_fix_20261015__h293dpp/audio_smoke.json).
Run mới: `273f0cc0-0784-4619-9719-a6d2204bc3ae`.

## 4. Replay trên dữ liệu đã lưu

Replay dùng candidate thô được chấp nhận rõ ràng, giữ nguyên lịch clip, nguồn đã
được gọi và ranh giới/nhãn người nói. Reference chỉ dùng tính điểm sau xử lý.
Không chạy lại model hoặc áp dụng transcript tham chiếu để chọn từ.

| Dữ liệu | WER trước → sau | CER trước → sau | S/D/I trước | S/D/I sau |
| --- | --- | --- | --- | --- |
| FPT, 524 đơn vị | 7,44% → 4,20% | 5,34% → 1,92% | 21 / 18 / 0 | 22 / 0 / 0 |
| VIVOS, 349 đơn vị | 16,62% → 8,31% | 14,72% → 5,65% | 9 / 48 / 1 | 14 / 8 / 7 |

Chuẩn hóa NFC, chữ thường, bỏ dấu câu, gộp khoảng trắng; không chuẩn hóa số.
WER dùng đơn vị tách theo khoảng trắng.

- FPT: run `new-test/72d2d9a1-fbf2-4eee-95b4-03b130ee560e`.
- VIVOS: run `test-ng-y-9-10/e7657b55-243d-49d9-81e2-0328b1529a37`.
- Không có nguồn transcribed bị bỏ qua vì thiếu candidate thô được chấp nhận.
- Hash timeline/source hypotheses/manifest của cả hai run trước/sau replay khớp.
- Replay là phép đánh giá thay đổi hậu xử lý; không phải một run audio đa nguồn mới.

Bằng chứng:
[FPT replay](/Users/thien/Documents/School/Luận văn/data/evaluations/asr_boundary_fix_20261015__h293dpp/fpt_replay/boundary_replay.json),
[VIVOS replay](/Users/thien/Documents/School/Luận văn/data/evaluations/asr_boundary_fix_20261015__h293dpp/vivos_replay/boundary_replay.json).
Trong từng thư mục có transcript sau replay và `error_analysis.json`.

### Giới hạn quan sát được

Số từ thiếu giảm mạnh nhưng **VIVOS tăng insertion từ 1 lên 7 và substitution từ 9 lên 14**.
Phần lời ASR được giữ thêm có cả nhận sai/hallucination đã lọt quality checker,
ví dụ “cảm ơn”, “hẹn”. Không thêm blacklist các từ này vì chúng có thể là lời thật.

Vì vậy:

- Bản sửa xử lý mất từ do quyền sở hữu biên; chưa giải quyết mọi lỗi ASR.
- Các từ khôi phục và đoạn chưa xác định sở hữu vẫn cần đối chiếu âm thanh.
- Phần overlap từng bị bỏ ASR vẫn chưa có transcript để khôi phục.
- Timestamp lệch quá xa có thể không ghép được bản trùng; cần đánh giá thêm.
- Chủ sở hữu có nguồn chưa chạy/bị loại được giữ dưới dạng audit, không tự xuất bản từ.
- Hai kịch bản dùng chẩn đoán chưa phải tập đánh giá độc lập.

## 5. Cách chạy lại replay

Từ thư mục gốc:

```bash
.venv/bin/python scripts/replay_asr_boundary_words.py \
  --run-dir data/meetings/new-test/runs/72d2d9a1-fbf2-4eee-95b4-03b130ee560e \
  --reference data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json \
  --output data/evaluations/fpt_boundary_replay

.venv/bin/python scripts/replay_asr_boundary_words.py \
  --run-dir data/meetings/test-ng-y-9-10/runs/e7657b55-243d-49d9-81e2-0328b1529a37 \
  --reference data/generated/smoke/meeting_test_001/recipe.json \
  --output data/evaluations/vivos_boundary_replay
```

Công cụ không cho ghi output bên trong run nguồn. F6 đã học cần artifact gốc,
nên utility hiện từ chối replay run dùng `F6_LEARNED`.

## 6. Demo

Đã khởi động lại demo sau khi kiểm tra không có job chạy/chờ.
[Ca kiểm tra giữ đủ 10 từ](http://127.0.0.1:8000/runs/asr-boundary-smoke-20261015).

HTTP 200 đã xác nhận:

- Health.
- Trang ca mới và trang run cũ.
- Timeline mới có đủ hai câu.
- Bảng đối chiếu từ ở biên và audio ngữ cảnh có trong HTML.
- Tải JSON audit và WAV ngữ cảnh.

Bằng chứng: [http_checks.json](/Users/thien/Documents/School/Luận văn/data/evaluations/asr_boundary_fix_20261015__h293dpp/http_checks.json).

Bản sửa áp dụng cho các lượt audio mới. Run và DOCX cũ không tự thay đổi.
Tạo lại biên bản từ timeline cũ vẫn sử dụng chữ của timeline cũ; cần transcript mới
hoặc chỉnh transcript có đối chiếu trước khi tạo biên bản tương ứng.
