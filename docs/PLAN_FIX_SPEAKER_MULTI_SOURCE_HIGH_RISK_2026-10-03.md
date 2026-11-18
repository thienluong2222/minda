# Kế hoạch sửa lỗi nguy cơ cao: nhận diện người nói đa nguồn

**Ngày lập:** 03/10/2026  
**Phạm vi:** WP2/WP3 của `PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md`, chỉ các lỗi mức cao và rất cao đã xác minh.  
**Repository:** `/Users/thien/Documents/School/Luận văn`  
**Đầu ra mong muốn:** Mỗi giọng có một danh tính ổn định trong cuộc họp, kể cả khi không đăng ký; nguồn sai đồng bộ/không nghe được giọng không được ảnh hưởng kết quả; P3 thực sự chạy và quyết định bất đồng có thể giải thích, kiểm thử được.

## 1. Nguyên tắc thực hiện

Agent được giao phải **sửa mã, kiểm thử và báo cáo kết quả thật**, không chỉ viết thêm tài liệu. Đọc `AGENTS.md` nếu có; kiểm tra `git status` trước khi sửa và giữ mọi thay đổi không thuộc nhiệm vụ. Không sửa ASR, transcript fusion, luồng biên bản hay bật tách tiếng nói chồng. Không đưa dữ liệu âm thanh, model weights, run output vào Git. Không dùng tên file, tên mẫu đăng ký hoặc transcript làm nhãn sự thật trong suy luận.

Giữ tương thích với các run cũ. Các trường JSON mới phải có schema version hoặc giá trị vắng mặt rõ nghĩa. Không tạo thêm ID người lạ cho một lượt quá yếu; dùng `ambiguous`/`needs_review`. Các điện thoại cùng ghi **một** phát biểu, không phải các quan sát độc lập về số lượt nói. Điểm cosine và trọng số heuristic không được trình bày là xác suất.

## 2. Baseline đã xác minh, không được che bằng số liệu giả lập

- Mốc mã khi lập plan: `ddb19b7`; xác nhận lại HEAD trước khi bắt đầu.
- Run FPT: `data/meetings/fpt-pilot-review/runs/fa8902eb-22b7-439f-a1a7-2965ae357afa/`. Có `aligned/source-{1,2,3}.wav`, `speaker_turns.json`, `sync_metadata.json`, `speaker_decisions.json`, `speaker_clusters.json`. Dữ liệu tham chiếu ở `/Users/thien/Documents/ChatGPT/Luận văn/FPT_TTS_PILOT_2MIN/meeting_audio/reference_segments.json`; mẫu đăng ký ở thư mục `pcm_16k/enrollment/` của bộ này. Đây là dữ liệu tổng hợp, không phải tập họp thật.
- Run trên có **3 giọng thật, 47 speaker turns, 28 clusters**, trong đó 26 clusters chỉ có một turn; 28 clusters đều khớp một trong ba người đăng ký. Nếu chạy lại cùng turns/embeddings với `profiles=[]`, kiểu chia cụm này có nguy cơ tạo quá nhiều nhãn người lạ.
- Có **66 cặp** turns khác local `track_id` nhưng **không giao nhau thời gian** trong cùng `speech_region_id`; điều kiện cannot-link hiện vẫn cấm chúng chung cụm.
- Cả **117** mục `source_evidence` trong run đều có `speech_coverage=1`, `local_speaker_purity=1`, `sync_status=synchronized`: các giá trị mặc định tại call site, không phải phép đo riêng từng nguồn.
- Run FPT có `activity_regions.json.backend=pyannote_shared` nhưng `manifest.json.models.vad=silero_vad`; sửa metadata trong phạm vi thay đổi artifact nếu chạm tới manifest.
- Bài kiểm thử chất lượng nguồn/gom cụm hiện qua; bài tích hợp cần `NUMBA_CACHE_DIR=/private/tmp/meeting-numba-cache` trong môi trường này. Script `scripts/benchmark_ablation_matrix.py` dùng mock ASR và các dòng RTF tương đối gán sẵn; **không** lấy đó làm bằng chứng P3 hoặc thời gian chạy thực.

## 3. Hợp đồng dữ liệu cần thống nhất trước khi sửa thuật toán

Tạo/chuẩn hóa kiểu dữ liệu nội bộ `SourceTurnEvidence` (có thể đổi tên cho hợp mã hiện tại), mỗi turn × source gồm:

| Nhóm | Trường tối thiểu và ý nghĩa |
| --- | --- |
| Thời gian | `source_id`, turn interval trên đồng hồ họp, `valid_coverage_interval`, `sync_status`, `local_sync_residual_ms` nếu đo được; `null` nếu không đo. |
| Hoạt động giọng | `speech_seconds`, `speech_coverage` từ frame speech của **nguồn đó**, `local_speaker_purity` từ tỉ lệ frame một người, `supporting_source` và `support_duration_sec`; không điền `1.0` khi thiếu dữ liệu. |
| Tín hiệu | SNR proxy, clipping, dropout, speech RMS tính trên vùng speech-active thích hợp; giữ `raw_features` và `quality_formula_version`. |
| Quyết định | `is_eligible`, `exclusion_reason`, `identity_quality_score`, `identity_weight`, `embedding_status`, score cosine theo ứng viên khi có profile, và lý do chọn/không chọn. |

Giữ `identity_weight` riêng với `selection_weight` của transcript. `identity_weight` phải là **trọng số thực dùng bởi policy**: P0/P1 chỉ một nguồn có trọng số 1; P2/P3 dùng các nguồn đủ điều kiện, tổng bằng 1; khi không nguồn nào hợp lệ thì tất cả bằng 0. Không xuất `0` thay `null` cho chỉ số chưa đo được. Cập nhật `speaker_decisions.json`, `speaker_clusters.json`, timeline và manifest theo hợp đồng; giữ parser của run cũ hoạt động.

## 4. Thứ tự sửa bắt buộc

### H1 — Sửa gom cụm và tính ổn định người lạ (nguy cơ rất cao)

**Mã chính:** `src/meeting_pipeline/speaker/clustering.py`, `pipeline/speaker_turns.py`, các test WP2.

1. Viết kiểm thử hồi quy trước: hai lượt cùng giọng, cùng VAD region, khác `track_id`, nối tiếp **không giao thời gian** vẫn được phép cùng cụm; hai lượt có **bằng chứng đồng thời thực** không được cùng cụm. `track_id` cục bộ không phải danh tính toàn cuộc họp.
2. Xây cannot-link chỉ từ overlap thời gian có chứng cứ local speaker activity đủ tin cậy. Không lấy điều kiện `speech_region_id` giống nhau và `track_id` khác nhau làm chứng cứ. Nếu thuật toán clustering không bảo toàn hard cannot-link, dùng bước kiểm tra/ràng buộc cụm sau gom hoặc backend constrained clustering; kiểm thử trên chuỗi A–B–A và A/B đồng thời.
3. Kiểm tra nguyên nhân 28 cụm: phân bố cosine cùng/khác giọng, độ dài turn, đoạn `unresolved`, ngưỡng `anonymous_cluster_threshold=0.1`, chất lượng embedding, cannot-link. Không chỉ nâng ngưỡng cho vừa con số 3. Hiệu chỉnh ngưỡng theo encoder và tập phát triển; thêm bước kiểm tra over-split/under-split với bằng chứng nhiều turn. Turn yếu được để `ambiguous` thay vì sinh một cụm mới tự tin.
4. Chạy lại **speaker-only** trên cùng aligned audio và turns, ba chế độ `profiles=[]`, một phần và đủ ba profile. Cùng giọng trở lại sau nhiều lượt phải giữ `meeting_speaker_id`/“Người lạ N” ổn định. Nếu nhiều cụm cùng khớp một profile, chỉ hợp nhất khi có bằng chứng embedding và không vi phạm cannot-link thật.

**Gate H1:** Không còn cặp *không đồng thời* bị cấm gộp chỉ vì khác local track. Trên các lượt đủ bằng chứng của ca FPT, ba giọng phải tạo ba danh tính ổn định ở chế độ không đăng ký; lượt yếu được đánh dấu ambiguous, không tạo người lạ thứ 4 trở lên. Báo số cluster, pairwise/B-cubed F1, số lượt ambiguous và ví dụ lỗi; nếu gate chưa đạt, báo nguyên nhân và không tuyên bố open-set đã xong. Không dùng đáp án FPT để ép kết quả suy luận.

### H2 — Nối coverage, đồng bộ và purity thật vào quality gate (nguy cơ cao)

**Mã chính:** `audio/synchronization.py`, `pipeline/stages/shared_segmentation.py`, `pipeline/speaker_turns.py`, `speaker/source_quality.py`, `speaker/clustering.py`, `pipeline/multi_source_fusion.py`.

1. Từ audio gốc và time mapping, lưu `valid_coverage_interval` từng nguồn **trước khi zero-pad**. Không coi đoạn zero-pad cuối file là audio hợp lệ. Truyền trạng thái đồng bộ và residual phù hợp cho mỗi lượt; nguồn `alignment_failed` phải bị loại. Với `drift_unresolved`, chỉ dùng vùng có residual cục bộ đạt gate đã định; nếu không có phép đo thì loại khỏi speaker fusion và nêu lý do. Nguồn tham chiếu được đánh dấu rõ là reference.
2. Từ cache pyannote, tính speech-active frames và số người cục bộ theo **từng nguồn/từng turn**. `supporting_source_ids` là chỉ báo sơ bộ; cần thêm thời lượng hỗ trợ, không coi một frame đơn lẻ là đủ. Nếu source không phủ hoặc không có speech hỗ trợ thì không trích embedding cho source đó. Tính purity trên frame thực; nguồn có dấu hiệu nhiều người trong cùng clip bị loại hoặc chuyển `needs_review` theo ngưỡng cấu hình.
3. Cắt embedding từ phần speech-active/interior nằm trong coverage của nguồn đó, tránh mép turn và khoảng im lặng. Đếm dropout trong phần đáng lẽ có speech, không trộn zero-pad/đoạn im lặng vào lỗi thiết bị. Giữ SNR là **proxy**; nếu cửa sổ nền chứa lời người khác, không tuyên bố đó là noise floor thật.
4. Bỏ fallback `compute_normalized_source_weights()` trả `{best_source: 1.0}` khi **mọi nguồn đều bị loại**. Trả không có nguồn hợp lệ; turn không có embedding phải thành ambiguous/needs_review. Ghi exclusion reason cho từng nguồn kể cả khi nguồn không có clip.

**Gate H2:** Test nguồn lỗi đồng bộ nhưng âm rất rõ, nguồn có file ngắn/zero-padding, nguồn không hỗ trợ lượt, nguồn bị chồng cục bộ, và tất cả nguồn đều không hợp lệ. Các nguồn đó có `identity_weight=0`, không tạo embedding/phiếu nhận diện. Artifact FPT mới phải có các giá trị coverage/purity/status được tính hoặc `null` có lý do; không còn tất cả đồng loạt nhận giá trị mặc định 1/1/“synchronized”.

### H3 — Triển khai P3 thật và chính sách bất đồng (nguy cơ cao)

**Mã chính:** `speaker/source_quality.py`, `speaker/clustering.py`, cấu hình identity, serialization và các test WP3.

1. Giữ P0 cố định, P1 top-1 và P2 embedding fusion làm baseline có thể chọn. Triển khai P3 ở **bước so cụm với profile**: với từng turn/source hợp lệ, tính cosine của embedding với từng profile cùng encoder/revision; trung bình score theo `identity_weight`; tổng hợp qua các turn với giới hạn đóng góp của một turn dài hoặc nhiều điện thoại. Không nhân các nguồn ghi cùng một phát biểu như các quan sát độc lập. P3 không thay thế bước gom cụm khi `profiles=[]`.
2. Nếu một nguồn vượt trội rõ theo ngưỡng đã hiệu chỉnh, cho phép top-1 và ghi lý do. Nếu từ hai nguồn chất lượng đủ cao trở lên, top candidate khác nhau với margin riêng đủ mạnh, **không** trung bình để che bất đồng: dùng các turn khác trong cụm, hoặc giữ cluster ID nhưng để danh tính đăng ký `ambiguous`/`needs_review`. Không tạo “Người lạ” chắc chắn từ một xung đột giữa hai profile đã đăng ký.
3. Hiệu chỉnh score threshold, margin, ngưỡng chênh chất lượng và ngưỡng bất đồng trên tập phát triển tách khỏi tập đánh giá; khóa theo encoder/revision và nguồn dữ liệu. Nếu chưa đủ dữ liệu, giữ default thận trọng và ghi `calibration_status=unvalidated`; không dùng ngưỡng benchmark câu đọc như bằng chứng hội họp.
4. Kiểm thử *đường chạy*, không chỉ helper: cấu hình P3 phải thực sự gọi score fusion và cho ra artifact score từng nguồn/ứng viên; P0/P1 chỉ hiển thị nguồn đã dùng. Test hai nguồn đồng thuận, hai nguồn bất đồng, một nguồn vượt trội, một nguồn bị loại, không có profile, profile một phần và nhiều nguồn cùng một turn.

**Gate H3:** P0/P1/P2/P3 tạo quyết định có thể tái lập và phân biệt ở nơi chính sách khác nhau; P3 không rơi ngầm về P2. Xung đột có reason và needs_review. `speaker_clusters.json` và timeline giữ cùng danh tính, người lạ và trạng thái ambiguous.

### H4 — Chứng minh chất lượng thay vì dùng báo cáo mô phỏng (nguy cơ cao)

1. Tạo script đánh giá speaker-only, ví dụ `scripts/evaluate_speaker_multisource.py`, nhận run có sẵn (`aligned/*.wav`, `speaker_turns.json`, `sync_metadata.json`), profile tùy chọn và ground truth **chỉ cho chấm điểm**. Cache embedding theo hash audio/interval/encoder để thử P0–P3 và ngưỡng mà không chạy ASR lại. Đầu ra nằm dưới `data/evaluations/` hoặc thư mục ignored; không sửa run gốc.
2. Dùng FPT như ca chẩn đoán có nhãn 0/partial/full enrollment. Tạo thêm bộ phát triển và bộ held-out độc lập từ VIVOS đa nguồn mô phỏng, tách speaker và câu gốc giữa hai bộ; hai cuộc họp thu thật hiện có chỉ dùng smoke nếu chưa có nhãn lượt nói. Không tune rồi tuyên bố accuracy trên chính FPT hoặc cùng người/câu ở held-out.
3. Báo từng policy: số cụm so với số giọng thật, pairwise/B-cubed F1 hoặc ARI, DER/JER nếu có alignment/reference phù hợp, known-ID accuracy, unknown false accept/recall, số lượt ambiguous, lỗi ngắn/dài, gần/xa, số nguồn bị gate, wall time của **speaker stage** và peak RAM nếu đo được. Ghi config, encoder revision, data split/hash, cold/warm cache, số nguồn và coverage. Không gán sẵn các mức “Rất tốt”, “0.36x” vào kết quả.
4. Sửa báo cáo ablation cũ: đánh dấu rõ là mock/simulation hoặc thay bằng báo cáo thực; không gọi A7 là P3 mặc định khi manifest/code chạy P2. Manifest của run mới phải lưu `speaker_fusion_policy`, phiên bản quality formula, ngưỡng và calibration status; `models.vad` phản ánh backend thực chạy.

**Gate H4:** Có bảng so sánh cùng tập audio cho bốn policy và ablation bỏ từng đặc trưng nguồn; số liệu lấy từ run/artifact thật, script tái lập được. Nếu P3 hoặc quality gate không hơn P1/P2 trên held-out, chọn cấu hình thắng thực tế và ghi kết luận bất lợi, không giữ P3 chỉ vì kế hoạch ban đầu.

## 5. Trình tự commit và kiểm tra cuối

Làm tuần tự để dễ bisect: (1) test + sửa cannot-link/over-split, (2) source evidence và quality gate, (3) P3 + bất đồng, (4) đánh giá + artifact/manifest + UI tối thiểu. Mỗi commit chỉ gồm mã, config, test, tài liệu nhỏ. Trước và sau mỗi bước chạy unit/integration liên quan; lệnh tham khảo:

```bash
NUMBA_CACHE_DIR=/private/tmp/meeting-numba-cache .venv/bin/python -m pytest -q tests/unit/test_speaker_source_quality.py tests/unit/test_global_speaker_clustering.py tests/integration/test_multi_source_fusion_pipeline.py -p no:cacheprovider
.venv/bin/python -m pytest -q tests/integration/test_web_demo.py -p no:cacheprovider
.venv/bin/python -m ruff check src/meeting_pipeline/speaker src/meeting_pipeline/pipeline tests/unit/test_speaker_source_quality.py tests/unit/test_global_speaker_clustering.py
.venv/bin/python -m mypy src/meeting_pipeline/speaker src/meeting_pipeline/pipeline
```

Kiểm tra lệnh theo dependency hiện có trước khi đổi môi trường; nếu lỗi do Numba cache, đặt cache trong `/private/tmp`, không sửa thuật toán để né lỗi môi trường. Chạy speaker-only FPT trước; chỉ chạy full demo sau khi H1–H3 qua và cần xác nhận timeline/UI. Kiểm tra 0, 1, 2, 3 nguồn; 0/partial/full enrollment; nguồn thiếu đầu/cuối; nguồn đồng bộ lỗi; lời nói chồng giữ `not_run` như thiết kế hiện tại.

**Bàn giao:** commit SHA, danh sách file đổi, bảng trước/sau từ cùng dữ liệu, artifact đường dẫn, số ca test qua, các gate H1–H4 và mục nào chưa đạt. Không tuyên bố hệ thống nhận diện người lạ ổn định hoặc P3 cải thiện chất lượng khi chưa có kết quả held-out. Các chỉ số chỉ thuộc trường hợp tổng hợp phải được ghi rõ là tổng hợp.
