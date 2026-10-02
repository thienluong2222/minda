# Kế hoạch triển khai VAD, nhận diện người nói và chép lời cuộc họp đa nguồn

**Ngày lập:** 03/10/2026  
**Trạng thái:** Đặc tả giao việc; chưa triển khai mã.  
**Repository mã cần sửa:** /Users/thien/Documents/School/Luận văn  
**Nơi lưu kế hoạch này:** /Users/thien/Documents/ChatGPT/Luận văn  
**Mục tiêu:** Từ 1–8 điện thoại ghi cùng một cuộc họp tiếng Việt, tạo timeline “ai nói gì” có âm thanh đối chiếu; hệ thống hoạt động khi đăng ký đủ, đăng ký một phần hoặc không đăng ký người nào.

## 0. Cách dùng và phạm vi

Agent được giao **triển khai đầy đủ**, không chỉ viết một kế hoạch khác. Đầu tiên kiểm tra trạng thái repository mã, cấu hình và test hiện tại. Mã chạy của web demo là nguồn xác định hành vi thực tế; tài liệu cũ và số liệu báo cáo chỉ là ngữ cảnh. Nếu tên hàm/file đã đổi, áp dụng cùng hợp đồng ở vị trí tương ứng và ghi rõ thay đổi trong báo cáo bàn giao.

Đọc AGENTS.md nếu có trong repository mã. Không xem tên file gần một người, danh sách đăng ký hoặc biểu mẫu cuộc họp là nhãn sự thật rằng người ấy đang nói. Không dùng transcript do ASR tự sinh làm ground truth đánh giá ASR. Các ngưỡng trong tài liệu này là giá trị **khởi tạo thí nghiệm**; chỉ giữ sau khi hiệu chỉnh trên tập development và kiểm tra tập held-out.

Phạm vi công việc gồm Git, đồng bộ/đánh giá chất lượng nguồn khi cần, VAD phương án B, chia lượt và gom giọng toàn cuộc họp, nhận diện người đăng ký/người lạ, ASR medium và tối ưu tốc độ, dung hợp transcript nhiều nguồn, artifact, demo và kiểm thử. **Không triển khai điền biểu mẫu/biên bản** trong đợt này; tài liệu PLAN_OPTIMIZE_PIPELINE_AND_MEETING_MINUTES.md là kế hoạch hạng mục tiếp theo. Vùng hai người nói chồng nhau vẫn có đúng một dòng timeline với asr_status=not_run, text rỗng và clip gốc từng nguồn; không bật SepFormer hoặc tự đoán lời ở vùng đó.

### Những bất biến không được phá

1. Audio gốc không bị sửa. Mọi đoạn kết quả có [start_sec, end_sec) trên đồng hồ cuộc họp và ánh xạ được về mẫu âm thanh nguồn gốc.
2. “Người lạ 1”, “Người lạ 2” là **các giọng khác nhau trong một cuộc họp**. Tên hiển thị có thể đổi, ID nội bộ không đổi sau khi run hoàn tất. Không tự khẳng định Người lạ 1 ở hai cuộc họp khác nhau là cùng một cá nhân.
3. Không có mẫu đăng ký vẫn phải phân biệt những giọng có đủ bằng chứng. Người đã đăng ký nhưng không tham gia không được gán bừa vào transcript. Khi bằng chứng thiếu, dùng “Chưa xác định” và needs_review thay vì tạo thêm danh tính giả.
4. VAD xác định vùng có tiếng nói; diarization xác định các lượt/giọng; ASR xác định nội dung. Một vùng VAD không mặc định chỉ có một người.
5. Trọng số nguồn cho **nhận diện giọng** tách khỏi trọng số cho **transcript**. Raw cosine và điểm heuristic không được hiển thị là xác suất đúng.
6. Không nhân số phiếu độc lập theo số điện thoại: nhiều điện thoại cùng ghi **một phát biểu**, không phải nhiều lần người đó phát biểu.
7. Tất cả phương án nhanh hơn phải được chọn bằng phép đo wall time **toàn job** và quality gate; không chỉ dựa vào thời gian suy luận một clip.

## 1. Hiện trạng cụ thể cần thay đổi

| Thành phần | Hiện trạng đã xác minh | Việc cần giải quyết |
|---|---|---|
| Git | Repository mã chính chưa có .git. Thư mục kế hoạch đang mở có .git riêng. | Khởi tạo Git **trong repository mã chính**, không khởi tạo nhầm trong thư mục kế hoạch. |
| Tệp lớn | data/ gần 10 GB; dataset/ có audio thật; artifacts/ và reports/ chứa đầu ra; .gitignore mới bỏ data/ và một số cache. | Giữ dữ liệu tại chỗ nhưng không đưa vào commit; chỉ theo dõi mã, cấu hình, tài liệu, test và fixture nhỏ. |
| VAD/turn | multi_source_fusion.py chạy Silero VAD trên từng nguồn, rồi pyannote/segmentation-3.0 trên từng file đồng bộ. | Phương án B: dùng **một lần suy luận pyannote/nguồn** để sinh cả VAD và bằng chứng chia lượt. |
| Theo dõi giọng | speaker_turns.py khâu nhãn cục bộ theo cửa sổ và dùng một điện thoại tham chiếu toàn cục chọn theo RMS. | Gom embedding toàn cuộc họp, xếp nguồn theo từng lượt; không xem nhãn pyannote cục bộ là danh tính. |
| Đăng ký | speakers.py chỉ kiểm tra file >=1 giây và lấy trung bình embedding toàn file. | Chỉ trích vùng một người nói đủ sạch; lưu phiên bản encoder và chất lượng từng mẫu. |
| Nhận diện | _MultiSourceSpeakerAssigner gán tên cho từng lượt; ngưỡng ECAPA mặc định 0,25; người lạ được gom tham lam và khi hết chỗ có thể ép vào cụm cũ. | Quyết định tên ở cấp cụm giọng toàn cuộc họp; người lạ có cụm/ID ổn định; không ép gộp sai. |
| Điểm nguồn | vad_confidence hiện mặc định 0,8; snr_est là tỉ số phân vị năng lượng trong cùng đoạn; temperature=0,25 làm trọng số các nguồn gần bằng nhau. | Đặt đúng tên và ý nghĩa chỉ số, đo chất lượng phát ngôn, chọn/gạt nguồn có kiểm chứng. |
| ASR | PhoWhisper-medium CPU, giải mã từng lượt × mọi nguồn và có thể retry; từng có run hai nguồn 126 giây mất khoảng 26 phút. | Dùng cửa sổ có core/context, chỉ chạy thêm nguồn khi cần; kiểm tra backend nhanh bằng A/B. |
| Fusion | Có F0/F1/F3/F4/F5/F6, confusion network, evidence clips và word provenance; thiếu confidence thật ở một số run. | Sửa phân biệt “không chạy/không phủ” với phiếu xóa từ; căn 3+ nguồn; hiển thị điểm thực tế và lý do. |

Các vị trí cần đọc trước khi sửa: src/meeting_pipeline/pipeline/multi_source_fusion.py; audio/synchronization.py; pipeline/speaker_turns.py; adapters/pyannote_segmentation.py; application/speakers.py; speaker/encoder.py; asr/segment_asr.py; adapters/phowhisper_asr.py; pipeline/stages/chunking.py; pipeline/stages/transcript_stitching.py; fusion/features.py; fusion/confusion_network.py; fusion/baselines.py; domain/schemas.py; web/app.py và web/templates/result.html.

Benchmark speaker hiện có trong reports/speaker_identification/sid-benchmark-20260924/FINAL_REPORT.md cho thấy WeSpeaker ResNet34-LM đáng thử nhưng chưa chứng minh tốt trên cuộc họp thật: với 3 mẫu và cosine prototype, accuracy VIVOS test 99,93%, VoxVietnam test 86,33%; ECAPA tương ứng 96,73% và 80,20%. Không dùng số VIVOS làm độ chính xác dự kiến của demo. Ngưỡng trong frozen-calibration.json phụ thuộc encoder/K/miền; không sao chép giữa ECAPA và WeSpeaker.

## 2. Kiến trúc đích và thứ tự dữ liệu

~~~text
N nguồn gốc + 0..N hồ sơ đăng ký
  -> decode, coverage, đồng bộ và kiểm tra lệch đồng hồ
  -> pyannote segmentation-3.0 một lần/nguồn, cache kết quả
  -> VAD chung + local speaker activity + overlap flag
  -> các lượt chỉ có một người, loại bằng chứng quá yếu
  -> embedding theo lượt/nguồn, xếp chất lượng nguồn
  -> gom giọng toàn cuộc họp, tạo meeting_speaker_id
  -> so các cụm với hồ sơ đã đăng ký; cụm còn lại = Người lạ 1, 2, ...
  -> tạo ASR chunks có core/clip gắn lượt/người
  -> ASR nguồn tốt nhất; thêm nguồn khi cần
  -> căn từ và dung hợp transcript, giữ provenance
  -> timeline + aligned audio + clips + điểm nguồn + báo cáo
~~~

Nhận diện được quyết định bằng audio/embedding, không dùng chữ ASR để suy đoán giọng. ASR được chạy sau khi đã có lượt/cụm giọng sơ bộ; khi diarization chưa chắc chắn, transcript vẫn được giữ với nhãn cần xem lại. Không ghép waveform của các điện thoại thành một tín hiệu tổng mặc định: độ trễ đường truyền âm và đồng hồ riêng có thể gây comb filtering; phương án đầu là chọn/gộp **bằng chứng**, không cộng sóng.

### Hợp đồng danh tính

Mỗi timeline row nên có tối thiểu:

| Trường | Ý nghĩa |
|---|---|
| meeting_speaker_id | ID opaque, ổn định trong run/cuộc họp, ví dụ ms-0001; dùng cho cả người đăng ký và người lạ. |
| speaker_id | ID hồ sơ đăng ký **nếu khớp đủ chắc**; null với người lạ/chưa xác định. Giữ ý nghĩa cũ để tương thích. |
| speaker_status | identified / unknown / ambiguous; unknown + meeting_speaker_id là “người lạ đã phân biệt”, ambiguous + null là “chưa xác định”. |
| speaker_label | Tên đăng ký, “Người lạ 1”, “Người lạ 2” hoặc “Chưa xác định”. |
| speaker_evidence | encoder/revision, điểm ứng viên, margin, số giây giọng dùng được, cụm nguồn đóng góp, lý do nhận/từ chối. |
| source_evidence | Với mỗi nguồn: coverage, acoustic features thực, eligible/reason, identity_weight, ASR routing/status, transcript weight, clip đối chiếu. |

Tạo speaker_clusters.json theo schema version mới: cluster ID, các turn ID, centroid và model revision (embedding lưu trong artifact nhị phân không đưa vào JSON), số giây speech, nguồn đóng góp, quyết định match, anonymous ordinal, warnings. Label Người lạ N được gán **sau** khi gom cụm xong, sắp theo thời điểm xuất hiện đầu tiên của một lượt đủ tin cậy rồi theo cluster ID để phá hòa. Không đổi số thứ tự giữa các row hay giữa trang web và ZIP. Không tạo “Người lạ N” cho mỗi lượt ngắn không đủ dữ liệu. Không có giới hạn cứng số cụm người lạ dẫn đến ép gộp; nếu số cụm quá cao thì báo over-clustering/needs_review.

Nếu một người đăng ký bị tách thành nhiều cụm, có thể gán cùng speaker_id cho các cụm sau khi kiểm tra tính nhất quán; không cho hai giọng **thật sự đồng thời** nhận cùng một identity. Ràng buộc “khác người” chỉ áp dụng khi có bằng chứng nói đồng thời đáng tin, không áp dụng máy móc cho hai track đứng cạnh nhau.

## 3. WP0 — Git, an toàn dữ liệu và baseline tái lập

**Bước 0.1 — Git.** Trong repository mã chính, chạy pwd và git rev-parse --show-toplevel. Nếu đã có .git khi agent bắt đầu thì giữ lịch sử, không git init lại. Nếu chưa có, chỉnh .gitignore **trước khi git add**, rồi git init -b main. Theo dõi README.md, PIPELINE_IMPLEMENTATION_SPEC.md, pyproject.toml, uv.lock, .env.example, src/, tests/, configs/, docs/, scripts/, experiments/ và manifest nhỏ cần để tái lập. Không đưa dữ liệu nhạy cảm, bản ghi gốc, model weights, database hoặc run output lên Git.

Nội dung tối thiểu của .gitignore:

~~~gitignore
.DS_Store
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
playwright-report/
test-results/
*.log
*.sqlite
*.sqlite3
dataset/
data/
artifacts/
reports/
~~~

Thêm đúng đường dẫn thư mục “Tài liệu tham khảo” theo spelling/Unicode trên ổ nếu thư mục đó chỉ là notes riêng; không sửa/xóa nội dung. reports/ hiện có cả báo cáo hữu ích và đầu ra ~48 MB: **giữ nguyên bản gốc trên đĩa**, chép bản tóm tắt benchmark nhỏ và ngưỡng hiệu chỉnh được chốt sang docs/ và configs/calibration/ khi thật sự cần chạy pipeline; không để runtime phụ thuộc vào file bị ignore. Chỉ cho phép fixture âm thanh rất nhỏ, tổng dung lượng có kiểm soát, trong tests/fixtures/ nếu unit/integration test không thể tạo tại chỗ.

Trước commit đầu: git status --short --ignored; git check-ignore -v cho dataset/, data/, artifacts/, reports/, .env; stage bằng danh sách đường dẫn có chủ ý, xem git diff --cached --stat, git diff --cached --name-only, git diff --cached --check và quét **tên file** cùng nội dung staged để chắc không có token/âm thanh riêng. Không in giá trị token ra log. Nếu stage nhầm, bỏ stage, không xóa file. Commit baseline sạch; sau đó làm trên branch codex/vad-speaker-asr-fusion và commit theo WP. Không tạo remote/push khi chưa được yêu cầu.

**Bước 0.2 — Baseline.** Pin SHA của code, Python/uv.lock, model revisions, CPU/RAM, threads, config, số nguồn, thời lượng cuộc họp. Đo wall time và peak RAM cho decode, sync, Silero, pyannote, speaker embedding/clustering, từng ASR attempt, transcript fusion, artifact/export; tách model cold load và warm run. Tạo timings.json và run manifest; khi job lỗi vẫn ghi stage cuối và nguyên nhân. Chạy ít nhất: 1 nguồn VIVOS mô phỏng; 2 và 3 nguồn VIVOS mô phỏng; hai cuộc họp thật để smoke nếu đọc được, không dùng chúng làm kết luận accuracy nếu thiếu nhãn tay. Lưu báo cáo baseline nhỏ trong docs/ hoặc metadata trong data/ignored; không thay đổi âm thanh gốc.

**Gate WP0:** Git chỉ chứa mã/tài liệu/config/fixture nhỏ; dựng được môi trường từ README + uv.lock + model cache được chuẩn bị riêng; kết quả baseline có số đo và file manifest. Mọi hành vi đang có trong web/CLI đã được ghi để so sau.

## 4. WP1 — VAD phương án B dùng lại pyannote

**Điều kiện trước khi merge nguồn:** kiểm tra synchronize_multi_source_audio hiện mới ước lượng offset toàn file rồi đặt drift_ppm=0 dù config có allow_drift. Với bản ghi dài, đo offset ở nhiều cửa sổ speech chung (fine_window_seconds, long_recording_step_seconds), lọc outlier, fit affine time mapping hoặc piecewise khi có bằng chứng, ghi residual theo thời gian và valid_ranges. Khi không đủ cửa sổ khớp, giữ một nguồn làm timeline nhưng đánh dấu nguồn kia alignment_failed/drift_unresolved ở khoảng tương ứng; **không** cho nguồn lệch bỏ phiếu VAD/word merge. Bản gốc không bị resample đè; lưu mapping để cắt clip theo original sample. Chạy test offset, drift dương/âm, khoảng lặng dài và nguồn thiếu đầu/cuối. Đây là điều kiện đúng đắn của merge, không cần căn pha mức mẫu để gộp score.

1. Mở rộng PyannoteSegmentationAdapter để trả kết quả inference có metadata thời gian, model revision, shape, source ID. Gọi model **một lần cho mỗi nguồn đồng bộ** rồi cache theo hash audio chuẩn hóa + revision + step_seconds + sample rate + time mapping. Không gọi lại từ VAD và SpeakerTurnDetector.
2. Từ ba kênh local multilabel do Inference trả về, tạo chỉ số activity “có ít nhất một người” cho mỗi frame; xử lý overlap cửa sổ, biên file, vùng coverage và clock mapping. Chỉ số này là **điểm hoạt động**, không tuyên bố là xác suất được hiệu chuẩn. Nếu muốn dùng class powerset gốc, phải chứng minh cache/API trả đúng 7 class trước khi viết phép chuyển; không lặng lẽ áp công thức 7 class lên ma trận 3 kênh.
3. Tạo VAD interval cho từng nguồn với threshold, min_on, min_off và pad trong config mới. Gộp trên đồng hồ chung bằng nguồn hợp lệ và quy tắc bảo thủ: giữ một giọng chỉ được máy gần nghe thấy, nhưng ngăn một máy nhiễu làm toàn cuộc họp thành speech. Lưu supporting_source_ids, coverage, score summary, warnings. Đo và hiệu chỉnh các ngưỡng trên development, giữ profile Silero cũ làm A/B baseline trong thí nghiệm.
4. Dùng chính các frame/cửa sổ đã cache để suy local speaker activity và hai người đồng thời. Local speaker 1/2/3 của pyannote **không** là người thật toàn cuộc họp. Sửa SpeakerTurnDetector nhận dữ liệu cache thay vì đọc/chạy lại file. Giảm phụ thuộc vào một nguồn tham chiếu RMS toàn cuộc họp; mỗi khoảng cần evidence từng nguồn và cơ chế hòa giải label theo thời gian, sau đó chuyển cho bước gom embedding toàn cuộc họp.
5. Giữ vùng padding VAD để ASR có đủ đầu/cuối, nhưng danh tính và duration chỉ lấy speech-active frames. Overlap thật tiếp tục not_run; false-overlap cần đo vì mỗi vùng bỏ qua sẽ mất transcript.

**Kiểm thử WP1:** 0/1/2/3 nguồn, im lặng, nguồn nhiễu chỉ phát tiếng phi thoại, nguồn chỉ phủ nửa cuộc họp, biên dưới 250 ms, hai người đổi lượt trong một VAD region, chồng tiếng, nguồn lệch thời gian/drift. Mock adapter phải chứng minh đúng **một lần** segment_file/source/run. So Silero cũ và pyannote B bằng frame precision/recall/F1, missed speech, false alarm, fragmentation, boundary error, false-overlap và wall time. So sync residual trước/sau và xác nhận nguồn lệch bị gạt khỏi fusion đúng khoảng. Không chọn B thắng chỉ vì số vùng ít hơn.

**Gate WP1:** B tạo đủ interval + turn + clip cùng đồng hồ và schema cũ vẫn đọc được; trên tập có nhãn, báo cả chất lượng và chi phí. Nếu B chưa vượt chất lượng baseline, giữ nó ở chế độ thử, nêu rõ nguyên nhân; không tự điều chỉnh ngưỡng trên held-out.

## 5. WP2 — Hồ sơ đăng ký và gom giọng toàn cuộc họp

### 5.1. Đăng ký giọng

- Giữ API nhận 1–8 tệp hiện có nhưng kiểm tra **thời lượng tiếng nói thực**, không chỉ thời lượng file. Bắt đầu thử với tối thiểu khoảng 2 giây giọng hợp lệ/mẫu; gợi ý người dùng ghi 3 mẫu, mỗi mẫu vài giây, ở điều kiện ghi khác nhau. Một mẫu hợp lệ vẫn cho đăng ký nhưng trả cảnh báo “ít bằng chứng”. Ngưỡng nhận mẫu là config và phải test câu ngắn/ồn; không biến gợi ý thành rào cản vô lý.
- Dùng VAD/local speaker activity để loại im lặng, chồng tiếng và đoạn có khả năng nhiều người; kiểm tra clipping, đoạn mất tín hiệu và quá ít speech. Lưu đánh giá từng mẫu. Không tự giả định file mẫu chỉ có đúng người đăng ký nếu phát hiện giọng khác; yêu cầu thu lại hoặc đánh dấu không dùng.
- Trích embedding riêng từng mẫu sạch, L2 normalize, lưu model_id, full revision, preprocessing hash và từng vector/điểm chất lượng. Prototype là trung bình có kiểm soát, loại outlier sau khi so các mẫu; nếu chỉ có một mẫu thì dùng một vector nhưng giảm mức chắc chắn. Không để mẫu chất lượng thấp chi phối profile.
- Khi đổi ECAPA sang WeSpeaker, tính lại embedding từ audio đăng ký gốc; không so 192D ECAPA với 256D WeSpeaker. Nếu audio gốc không còn, báo cần đăng ký lại; không bỏ qua silently. Giữ hồ sơ và kết quả cũ đọc được theo version.

### 5.2. Trích embedding từ cuộc họp

- Từ turn một người của WP1, chỉ lấy speech-active interior, cắt mép ngắn để tránh lẫn tiếng người trước/sau; không dùng đoạn nói chồng, im lặng padding hoặc đoạn clip chỉ toàn zero. Nếu quá ngắn, đánh dấu “defer” thay vì zero-pad và coi 1 giây đệm là bằng chứng mới.
- Trích embedding cho từng nguồn đủ điều kiện. Một lượt <1,5–2 giây chỉ là bằng chứng yếu; khi có các lượt khác của cùng giọng, dùng chúng để suy nhãn rồi gán ngược. Cache embedding theo source/interval/encoder revision và batch nếu adapter cho phép. Giữ source_id và khoảng speech thật ở mọi vector.
- So ECAPA hiện có với WeSpeaker ResNet34-LM đã benchmark (pyannote/wespeaker-voxceleb-resnet34-LM@837717ddb9ff5507820346191109dc79c958d614) trong cùng protocol. MFCC-KNN chỉ là baseline. Chọn encoder theo open-set + diarization trên họp mô phỏng và tập họp thật có nhãn, xét cả latency; không chọn tự động theo một chỉ số VIVOS.

### 5.3. Gom giọng và gán tên

Triển khai **hai lượt offline** vì hệ xử lý sau cuộc họp:

1. **Seed pass:** lấy các lượt một người đủ dài/chất lượng; tạo graph embedding, so cosine đã chuẩn hóa. Gom bằng agglomerative clustering với ngưỡng học trên development (hoặc backend tương đương có thể tái lập); số người **không được nhập sẵn từ danh sách đăng ký**. Dùng ràng buộc cannot-link cho các nguồn/lượt có bằng chứng hai giọng đồng thời đủ tin cậy. Không dùng luật “hai track liên tiếp chắc chắn là hai người”. Ghi score của các cặp được/nếu không được gộp.
2. **Assignment pass:** lập centroid robust từ các seed trong mỗi cụm; gán lượt ngắn về cụm khi đủ score + margin; nếu không đủ, để ambiguous. Có thể cập nhật centroid từ lượt mới chỉ khi rất chắc và qua outlier gate; không cho lỗi ban đầu tự khuếch đại. Có một pass kiểm tra over-split/under-split: cùng giọng bị chia cụm và hai giọng bị gộp. Không giới hạn cứng số cụm người lạ rồi ép vào cụm gần nhất.
3. **Open-set match:** so **cụm** với hồ sơ đăng ký bằng điểm gộp từ nhiều lượt và từng nguồn. Có ngưỡng điểm tối thiểu, margin với người đứng thứ hai, số giây bằng chứng và cờ bất đồng nguồn. Ngưỡng phải theo encoder/K/độ dài/miền thu âm; raw cosine không là xác suất. Cụm không qua gate thành người lạ; không gán “người đăng ký gần nhất” cho mọi cụm. Hai cụm có thể trùng tên người đăng ký sau kiểm tra merge; nếu là hai giọng đồng thời thì đó là lỗi cần review.
4. **Ổn định nhãn:** gán meeting_speaker_id và “Người lạ N” ở cuối; lưu mapping một lần rồi dùng cùng mapping cho timeline, web, JSON/CSV/TXT/ZIP. Đổi tên sau bằng mapping/audit riêng, không chạy lại ASR, không tạo hồ sơ cá nhân liên cuộc họp nếu người dùng chưa xác nhận.

**Ca bắt buộc:** không có profile nhưng 2–3 người nói luân phiên; đăng ký một phần; một người lạ trở lại sau vài phút vẫn đúng “Người lạ 1”; hai người lạ giọng gần nhau; một giọng bị thay mic/xa-gần; tên file gần A nhưng B đang nói; clip <1 giây; hơn max_profiles cụm người lạ mà không ép merge; không có speech; false-overlap; hai người thật cùng nói không bị nhập thành một. Với trường hợp quá ít bằng chứng để phân biệt, xuất ambiguous và needs_review, không phát sinh nhãn tự tin sai.

**Gate WP2:** ba chế độ 0/partial/full enrollment chạy end-to-end; có speaker_clusters.json tái lập; mọi row giọng rõ có cùng meeting_speaker_id ở các lần xuất; profile model mismatch bị phát hiện. Báo DER/JER, pairwise clustering F1/ARI hoặc B-cubed, known-ID accuracy, unknown recall/false accept, tỉ lệ ambiguous, phân tầng theo lượt <2s/2–5s/>5s và nguồn gần/xa. Không tuyên bố độ chính xác họp thật khi chưa có nhãn thủ công.

## 6. WP3 — Chất lượng nguồn và merge cho nhận diện giọng

**Tách ba câu hỏi:** nguồn nào nghe thấy tiếng nói; nguồn nào giữ đặc trưng người nói tốt; nguồn nào chép từ tốt. Không dùng một audio_quality_score duy nhất để quyết định cả ba.

### 6.1. Đặc trưng đầu vào

| Chỉ số | Cách lấy và vai trò | Lưu ý |
|---|---|---|
| speech_seconds / speech_coverage | Tổng frame giọng thật trong turn theo WP1, tính trên nguồn có coverage. | Có thể thiếu do VAD sai; báo null nếu không đo được. |
| speech-vs-local-noise contrast | So năng lượng speech với khoảng nền lân cận của **cùng điện thoại**, tránh đoạn có người khác nói. | Đây chỉ là SNR proxy, không gọi “SNR thật” khi nhiễu thay đổi. |
| clipping / true dropout | Đếm vùng mẫu dính biên hoặc cả block không tín hiệu trong lúc speech. | Không coi mọi mẫu gần zero là dropout. |
| bandwidth / codec anomalies | Phát hiện clip bị lọc mạnh hoặc codec lỗi nếu cần. | Chỉ thêm nếu chứng minh dự báo lỗi ID/ASR. |
| sync coverage / residual | Kiểm tra cắt đúng đoạn nói theo mapping và file có mặt. | Quan trọng cho VAD/word alignment; score speaker không cần căn pha từng mẫu. |
| local speaker purity | Tỉ lệ frame một người, khoảng cách tới boundary/overlap. | Gate mạnh cho embedding. |
| embedding stability | So các phần đủ dài trong cùng lượt/cụm để phát hiện vector bất thường. | Không dùng trên clip quá ngắn; không tự xác nhận tên. |
| RMS, spectral flatness | Lưu để phân tích, có thể làm prior yếu. | Không dùng đơn lẻ để kết luận điện thoại gần người nói do AGC/vang. |

DRR, RT60 hoặc C50 là chỉ số âm học có ý nghĩa nhưng từ speech thông thường **không có room impulse response**; nếu thử blind estimator, gọi là estimate và chỉ giữ khi dự báo đúng lỗi ID trên development. Không cộng waveform thô. Giữ audio gốc để có thể nghe và kiểm tra có clipping do xuất file hay do đầu vào.

### 6.2. Chính sách quyết định theo lượt/cụm

- Viết SourceQuality riêng cho speaker ID, trả raw features, eligible, exclusion_reason và score dùng để xếp; khóa công thức/phiên bản trong manifest. Không dùng ASR confidence để chọn embedding vì ASR chưa chạy hoặc confidence không có.
- So bốn baseline cùng embedding/profile: nguồn cố định; top-1 theo chất lượng; trộn embedding cũ; **quality-gated weighted score fusion**. Với score fusion: mỗi nguồn đủ điều kiện tính cosine với mỗi profile; trung bình theo trọng số chuẩn hóa, sau đó tổng hợp các turn trong cụm với giới hạn đóng góp mỗi turn. Hai nguồn cùng ghi một phát biểu không được nhân xác suất như hai phát biểu độc lập. Với score thô chưa hiệu chuẩn, dùng trung bình có trọng số và ngưỡng hiệu chỉnh, không gọi là probability.
- Nếu nguồn tốt nhất vượt xa nguồn còn lại, dùng top-1; nếu nhiều nguồn đều đủ chất lượng và nhất trí, cho score fusion; nếu hai nguồn tốt nhưng ứng viên khác nhau, không trung bình để xóa mâu thuẫn: lấy thêm lượt khác trong cụm hoặc để needs_review. Khi chỉ một nguồn có coverage, nó được dùng nhưng lý do và độ thiếu bằng chứng phải hiện rõ.
- So embedding fusion và score fusion đúng cách: với embedding/profile đã L2 normalize và cùng trọng số cho mọi ứng viên, chúng cho **cùng thứ hạng top-1**; khác chủ yếu ở thang score/unknown rejection. Vì vậy thành công phải đến từ gate nguồn, trọng số, nhiều turn và calibration, không được tuyên bố chỉ đổi công thức làm tăng closed-set top-1.
- Hiệu chỉnh threshold cho known/unknown trên development với K=0/1/3/5, số người đăng ký 0/2/5/8, độ dài lượt và các điều kiện nhiễu/xa-gần. Lưu calibration artifact nhỏ có model revision và hash dữ liệu development dưới configs/calibration/. Không tái sử dụng ECAPA 0,65 hay WeSpeaker 0,60 từ benchmark câu đọc như ngưỡng họp; báo khi chưa đủ dữ liệu để hiệu chỉnh.

**Gate WP3:** báo bảng cùng một tập audio cho fixed/top-1/embedding/score và ablating từng feature. Chọn phương án theo known accuracy, unknown false accept/recall, độ ổn định Người lạ N, DER và thời gian. Giao diện phải thấy source ID, eligible/reason, raw features, identity_weight và điểm ứng viên; trọng số là đóng góp quyết định, không phải xác suất người đó nói.

## 7. WP4 — ASR theo vùng tiếng nói/lượt nói và giảm thời gian

Giữ vinai/PhoWhisper-medium@55a7e3eb6c906de891f8f06a107754427dd3be79 là baseline tiếng Việt, PhoWhisper-small là đối chứng. Agent có thể thử backend CTranslate2/faster-whisper trên **đúng revision medium** như kế hoạch trước, nhưng chỉ tích hợp nếu test tính năng, word timestamp, CER, RAM và wall time đạt gate. Không dùng model ID floating và không tự tải/đổi model khi job đang chạy. Transformers hiện tại vẫn là fallback đo được.

### 7.1. ASR chunks

1. Sau WP1/WP2 tạo AsrChunk với core_interval thuộc đúng một lượt/meeting_speaker_id; clip_interval gồm context 0,5–0,75 giây khi cùng giọng, nhưng không kéo giọng người khác/chồng tiếng qua ranh giới. Kích thước khởi đầu: target core 22 giây, max clip 25 giây như config hiện tại; đây là giới hạn, không ép lượt rất ngắn thành 22 giây âm thanh giả.
2. Gộp các lượt sát nhau **chỉ khi** là cùng cluster có độ chắc phù hợp, không có người khác chen vào. Nếu không gom được, vẫn giải mã lượt ngắn và đánh dấu chất lượng/timestamp yếu; không kéo cả VAD region qua nhiều người vào một nhãn. Giữ alternative vad_window_remap chỉ như thí nghiệm tách biệt khi có bộ nhãn boundary; không bật theo mặc định.
3. Mỗi từ thuộc một core theo midpoint/interval policy đã kiểm thử; context chỉ hỗ trợ model, không xuất trùng từ. Từ nằm đúng boundary hoặc thiếu ending timestamp mang time_status=uncertain; raw candidate và clip được lưu để nghe, không chế timestamp chắc chắn. Mapping clip time -> meeting time -> original sample cần round-trip.
4. Retry chỉ một lần khi quality guard phát hiện lỗi có thể phục hồi; log reason và config attempt. Kiểm tra warning “Whisper did not predict an ending timestamp”, lặp từ, phát ngôn rất ngắn, khoảng lặng và câu bị cắt giữa từ. Không tăng số attempt vô hạn hoặc giấu lỗi để tăng tỷ lệ “thành công”.

### 7.2. Chọn nguồn ASR thích nghi

- Trước ASR dùng quality **cho transcript** từ audio/speech coverage, clipping, nhiễu và khả năng cắt đúng vùng; không dùng điểm cosine speaker làm điểm ASR. Chạy top-1 trước. Nếu top-1 bị quality guard từ chối, timestamp hỏng, transcript bất thường hoặc chất lượng các nguồn quá sát nhau, chạy top-2. Khi cần kiểm chứng nội dung quan trọng hoặc 2 nguồn bất đồng mạnh, thử thêm nguồn theo ngân sách cấu hình.
- Các trigger không suy từ “đồng thuận từ” trước khi có ít nhất hai transcript. Không cho nguồn **chưa chạy ASR** bỏ phiếu trong mạng từ. Khi một nguồn được chạy, giữ raw transcript, status, thời gian, word timestamps, source clip và routing_reason.
- Có chế độ all-source để đối chứng và xuất đầy đủ từng nguồn khi người dùng muốn; so adaptive với all-source trên **cùng dữ liệu**. Khi chỉ chạy một nguồn, UI gọi đúng là “chọn nguồn”, không hiển thị như đã hòa nhiều transcript.
- Nạp model một lần/job; đo batching 1/2/4 và số threads 2/4/6 trên máy thật trước khi chọn; đo cả peak RAM. Cache ASR bằng audio hash + clip/core interval + model revision + decoding settings; thay đổi audio/turn/model/config phải làm cache mất hiệu lực. Không để cache chứa đường dẫn stale khiến provenance sai.

**Gate WP4:** chạy ablation per-turn cũ, safe-turn-merge, medium Transformers, medium CT2 (nếu tương thích), all-source và adaptive top-1/top-2. Chọn cấu hình nhanh nhất **trong các cấu hình qua quality gate**. Báo wall time job, RTF theo thời lượng họp và tổng input, số lần ASR/retry, CER/WER, speaker-attributed CER/WER, lỗi tên riêng/số, lỗi biên/timestamp, số đoạn bị bỏ. Mục tiêu kỹ thuật từ kế hoạch trước là giảm mạnh so mốc 26 phút/126 giây/2 nguồn; không hứa hệ số từ nghiên cứu chạy trên GPU sẽ lặp lại trên CPU của dự án.

## 8. WP5 — Merge transcript, giải thích và provenance

1. Trên những nguồn thật sự đã ASR và hợp lệ, căn từ theo timestamp + dynamic programming và xây confusion network. Kiểm tra 3–8 nguồn có insertion/deletion khác nhau; mỗi nguồn tối đa một candidate/bin, bin có interval hợp lệ và không đảo thứ tự.
2. Phân biệt **abstain** (không chạy, không có coverage, ASR failed/unreliable) với **epsilon** (nguồn có coverage và đã giải mã đáng tin nhưng không nghe thấy từ). Abstain không phải phiếu xóa. Khi word confidence từ model là null, API/UI giữ null; điểm 0,5 heuristic nếu dùng cho xếp hạng phải có tên khác, tuyệt đối không gọi “50% ASR confidence”.
3. Chạy F0 fixed, F1 best-source, F3 ROVER, F5 hiện tại và F5 sửa trên cùng hypotheses. F5 sửa chỉ chọn một từ từ nguồn phụ khi timestamp, âm học và vote ủng hộ; nếu bất đồng thiếu chứng cứ thì giữ nguồn tốt nhất và needs_review. Không tự thêm từ chỉ vì hai nguồn cùng hallucinate. F6 chỉ dùng nếu đã có tập huấn luyện nhãn đủ; không giả định có.
4. Kết quả mỗi đoạn/từ phải có selected_source_id hoặc selected_spans, tất cả candidate text/score, source đã chạy và chưa chạy, quyết định/hệ số, reason, word provenance và clip gốc từng nguồn tương ứng. Không để gán nhãn người nói ở cuối pipeline thay đổi text/clip đã chọn một cách ngầm.
5. Tách transcript_quality_score khỏi identity_quality_score trong config, API, artifact và UI. Bỏ cấu hình trọng số không được dùng hoặc nối nó vào hàm thực; đóng băng config snapshot cùng kết quả để mở run cũ vẫn đọc đúng ý nghĩa.

**Gate WP5:** ca A đúng/B thiếu từ; A thừa từ/B đúng; một nguồn failed; một nguồn không phủ; 3 nguồn lệch insertion; khác dấu tiếng Việt; token hóa/dấu câu; timestamp lệch; nhiều nguồn cùng hallucinate; 1 nguồn duy nhất; nguồn có từ đúng nhưng chất lượng thấp. So CER/WER và substitution/deletion/insertion, nguồn gốc mỗi từ, clip mở đúng mốc. Nếu F5 sửa thua F1 hoặc baseline mạnh nhất trên held-out, không đổi default một cách im lặng; báo thất bại và giữ chế độ thắng.

## 9. WP6 — Tích hợp web demo, CLI, artifact và tương thích

### 9.1. Giao diện minimalist

- Trang đầu: đăng ký mẫu giọng, danh sách hồ sơ đã có, thông báo chất lượng mẫu; tạo cuộc họp với nhiều file và participant_ids **có thể trống**; lựa chọn chế độ mặc định/so all-source nếu cần. Không bắt người dùng đăng ký mới cho mỗi cuộc họp.
- Khi chạy: stage hiện tại, tiến độ thật, elapsed time và số nguồn/đoạn đã xử lý. Không hiển thị phần trăm giả. Job lỗi nêu stage và artifact còn dùng được.
- Trang kết quả: tổng số người đăng ký được nhận, số cụm “Người lạ N” (đếm cụm, không đếm row), số đoạn ambiguous, số vùng overlap not_run; timeline lọc theo người/nguồn/review. Mỗi row cho thấy text, người nói, audio đại diện, clip từng nguồn, nguồn đã ASR/chưa ASR, điểm match và lý do.
- Bảng nguồn trong phần giải thích: coverage, speech seconds, acoustic features **đo được**, identity quality/weight, speaker candidate score, transcript quality/weight, ASR status, word agreement nếu có, trạng thái không đo được là null/N/A. Phân biệt “điểm tương đồng cosine”, “điểm xếp hạng” và “xác suất đã hiệu chuẩn”; không gộp thành một cột confidence.
- Cho đổi **nhãn hiển thị** “Người lạ N” trong cùng cuộc họp qua một thao tác sửa, lưu audit mapping và cập nhật mọi row/export mà không chạy lại model. Đổi nhãn không tự biến người lạ thành “đã xác thực”. Nếu muốn gộp vào hồ sơ đăng ký xuyên cuộc họp, cần thao tác xác nhận riêng và hồ sơ/version mới; không tự động theo tên.
- Các vùng overlap tiếp tục hiển thị đúng một row chưa chép lời, có clip gốc mỗi nguồn và cờ cần xem lại. UI không giả rằng Người lạ 1/2 đã được xác định trong vùng này.

### 9.2. API và artifact

POST /api/runs hiện nhận meeting_name, sources, participant_ids, identity_method, fusion_method. participant_ids vắng/trống phải hoạt động. Giữ các endpoint run/status/timeline/export đang có; thêm endpoint danh sách meeting speakers/rename label nếu chưa có, với kiểm tra ID, ký tự/tên hợp lệ và cập nhật atomic. Không truyền path người dùng làm artifact path trực tiếp; dùng bảo vệ đường dẫn hiện có. Web và CLI phải gọi cùng service xử lý, không tạo hai thuật toán nhận diện khác nhau.

Cây artifact mục tiêu trong data/meetings/<meeting_id>/runs/<run_id>/:

~~~text
manifest.json
timings.json
sync_metadata.json
aligned/<source_id>.wav
segmentation/<source_id>.npz
activity_regions.json
speaker_turns.json
speaker_clusters.json
speaker_decisions.json
asr_chunks.json
asr_routing.json
source_hypotheses.json
fusion_decisions.json
timeline.json
clips/original/...
clips/evidence/...
exports/result.json
exports/result.csv
exports/result.txt
exports/result.zip
~~~

Không bắt buộc đổi tên artifact cũ nếu làm gãy URL; chọn mapping rõ và ghi schema_version. JSON/CSV/TXT/ZIP phải giữ meeting_speaker_id, speaker_label, speaker_status và source provenance; aligned audio từng nguồn phải tải/nghe được; ZIP không nhân bản vô ích cùng audio dài. Với run schema 1.0/2.0 trước đây, hiển thị các field chưa có là “không có dữ liệu”, không suy ra Người lạ N từ row cũ. Lưu SHA256 input/config/model để truy vết; không đưa token hoặc absolute path riêng của máy vào export.

**Gate WP6:** chạy web thủ công và integration test với 0, một phần và đầy đủ đăng ký; tải 1/2/3 nguồn; nghe clip cùng mốc, mở aligned audio, xuất ZIP và kiểm tra tất cả path. Người lạ N xuất hiện nhất quán trên HTML/API/CSV/TXT/ZIP. Rename label không sửa bản audio hoặc kết quả nhận diện gốc. Mở run cũ không lỗi template.

## 10. WP7 — Đánh giá, lựa chọn cấu hình và bàn giao

### 10.1. Dữ liệu và tách tập

- **VIVOS synthetic nhiều điện thoại:** sinh recipe có 0/1/2/3+ người lạ, người đã đăng ký, vị trí mic, room RIR, gain/AGC proxy, nhiễu, clipping, dropout, start offset và drift. Dùng ground truth sạch chỉ để **đánh giá**, không cho vào feature inference. Chia speaker/utterance/meeting recipe rời nhau giữa dev và held-out; lưu seed + hash recipe. VIVOS là giọng đọc, không đại diện hoàn toàn cho họp tự nhiên.
- **VoxVietnam public subset:** đối chứng open-set encoder trong miền nhiều nhiễu hơn; không gọi đây là test nhiều điện thoại vì các file không đồng thời cùng một buổi. Không rò rỉ speaker/support/query giữa các split.
- **LibriWASN subset hiện có:** có thể dùng để smoke đồng bộ/diarization đa điện thoại và overlap flag; đây không phải tiếng Việt nên không dùng làm kết luận CER PhoWhisper tiếng Việt. Không tải toàn bộ bộ dữ liệu ngoài ngân sách đã chốt.
- **Hai cuộc họp thật hiện có:** smoke và nghe phân tích lỗi. Muốn đánh giá độ đúng tên/Người lạ N/CER thật, cần nhãn tay theo từng lượt + text; không dùng tiền tố tên file như nhãn người nói. Nếu chưa có nhãn, báo rõ “chưa thể kết luận accuracy thực địa” nhưng vẫn hoàn thành các ca chức năng và xuất demo.
- Khi sau này có cuộc họp mới, chia theo **cuộc họp**, không lấy turn của cùng cuộc họp vừa tune threshold vừa làm held-out. Chọn threshold/weights trên dev rồi đóng băng; báo sai số và khoảng tin cậy khi mẫu nhỏ.

### 10.2. Metrics và phép thử so sánh

| Tầng | Chỉ số bắt buộc |
|---|---|
| Đồng bộ | residual_ms theo khoảng thời gian, drift_ppm, coverage, tỉ lệ clip cắt đúng mốc. |
| VAD/turn | frame precision/recall/F1, missed speech/false alarm, boundary MAE, fragmentation, false-overlap/false-skip, DER/JER phần một người và báo riêng phần overlap. |
| Giọng chưa đăng ký | số cụm thật/dự đoán, pairwise clustering precision/recall/F1 hoặc B-cubed, over-split/under-split, tỷ lệ Người lạ N ổn định qua các lượt, ambiguous rate. |
| Giọng đã đăng ký | known accuracy/macro F1, confusion, false accept người lạ, unknown recall, false reject, calibration theo K/độ dài/nguồn. |
| ASR | CER/WER tiếng Việt, S/D/I, speaker-attributed CER/WER, tên riêng/số, hallucination/repetition, timestamp/boundary error. |
| Merge | fixed/top-1/embedding/score, F0/F1/F3/F5 cũ/F5 sửa, all-source/adaptive; source-choice error, oracle gap **chỉ trong đánh giá**, số từ có evidence 1/2+ nguồn, epsilon-caused deletion. |
| Hiệu năng | wall time toàn job, từng stage, cold/warm, số ASR calls/retries, RTF theo meeting duration và tổng audio input, peak RSS, dung lượng artifact. |

Ma trận ablation tối thiểu theo thứ tự: (A0) pipeline cũ khóa baseline; (A1) VAD B chung pyannote, giữ ASR/ID cũ; (A2) global clustering + unknown IDs với ECAPA, giữ source strategy cũ; (A3) source selection và score fusion, so ECAPA/WeSpeaker; (A4) ASR safe chunks, all-source; (A5) ASR adaptive; (A6) F5 sửa; (A7) toàn hệ thống. Mỗi hàng chỉ thay một nhóm yếu tố và chạy cùng input/config/model seed ở hai nhánh; báo bảng kết quả, không so các số không cùng điều kiện. F2 oracle chỉ là trần offline, không bao giờ là runtime default.

**Quality gate đặt trước khi xem held-out:** ưu tiên cấu hình nhanh nhất trong các cấu hình không làm tăng đáng kể CER/SA-CER, DER, false accept người lạ hoặc lỗi gán Người lạ N so với baseline mạnh nhất. Mốc thử ban đầu của kế hoạch ASR cũ là CER và SA-CER tăng không quá 1 điểm phần trăm tuyệt đối; với tập họp thật rất nhỏ, đây chỉ là mục tiêu thăm dò, phải báo số lượng ca và khoảng không chắc chắn. Chấp nhận cấu hình nhanh hơn **chỉ khi** chức năng 0/partial/full enrollment, provenance và overlap không lỗi. Nếu điều kiện tốc độ/độ chính xác không cùng đạt, giữ cấu hình chắc hơn và đưa số đo + nút thắt vào báo cáo, không hạ ngưỡng nghiệm thu để tuyên bố thành công.

### 10.3. Lệnh kiểm tra và ca tích hợp

Chạy từ repository mã:

~~~bash
uv sync --locked --all-extras
uv run pytest tests/unit tests/integration
uv run ruff check .
uv run ruff format --check .
uv run mypy src/meeting_pipeline
uv run meeting-pipeline doctor
uv run meeting-pipeline serve --host 127.0.0.1 --port 8000
~~~

Model smoke và browser e2e chạy riêng khi cache model đã chuẩn bị; test unit/integration dùng adapter giả và audio fixture nhỏ, không buộc tải model/mạng. Test cần kiểm **hành vi** thay vì sao chép công thức trong implementation:

1. 0 hồ sơ, hai giọng A-B-A-B: đúng hai meeting_speaker_id; A trở lại vẫn Người lạ 1; timeline chứa lời riêng từng lượt.
2. 1 hồ sơ A, giọng A-B-A-C: A hiện tên; B/C là hai Người lạ khác nhau; người đăng ký vắng mặt không được gán.
3. 3+ nguồn, một nguồn thiếu đầu/cuối, một nguồn méo: VAD không bỏ câu chỉ có một máy thu rõ; source gate không chọn nguồn thiếu; clip evidence đúng original sample.
4. Đổi thứ tự upload nhưng cùng audio và config: ID/label có thể chỉ khác source_id được chuẩn hóa; nội dung và thứ tự Người lạ N theo thời gian không đổi. Nếu source_id là thứ tự upload, chuẩn hóa trước khi so.
5. Nhiều lượt rất ngắn xen lời dài: short turn về đúng cụm khi đủ bằng chứng; lượt không đủ ở ambiguous, không sinh Người lạ mới vô hạn.
6. Hai người nói chồng: đúng một row not_run, text rỗng, clip gốc của mọi nguồn; không chạy ASR/ID giọng đó. False-overlap có metric và cảnh báo.
7. Một nguồn ASR failed/not_run: không tạo epsilon để xóa từ của nguồn tốt; 3+ nguồn có insertion ở các vị trí khác nhau không lệch bin.
8. PhoWhisper thiếu word ending timestamp: giữ raw output, retry có giới hạn và status đúng; không chế text/timestamp chắc chắn.
9. Profile ECAPA gặp encoder WeSpeaker: lỗi rõ hoặc tái mã hóa từ audio gốc; không dot product khác chiều.
10. Hết giới hạn max_profiles nhưng có thêm giọng lạ: không ép merge; cảnh báo đủ dữ liệu/chưa đủ dữ liệu theo trường hợp.
11. Kết quả cũ schema 1.0/2.0 vẫn mở được; export JSON/CSV/TXT/ZIP nhất quán và ZIP hợp lệ.
12. Git: git status sau commit không liệt kê dữ liệu/model đã stage; git check-ignore xác nhận đường dẫn lớn/private; clone sạch có thể cài và chạy test nhẹ sau khi chuẩn bị model riêng.

### 10.4. Định nghĩa hoàn thành

Đợt triển khai hoàn thành khi: tất cả ca chức năng ở trên qua; demo web thật chạy được từ upload tới timeline/export với 0/partial/full enrollment; có Người lạ N ổn định và trạng thái ambiguous trung thực; pyannote inference không bị gọi lặp bởi VAD/turn; ASR/merge nguồn có provenance; có bảng A/B thời gian/độ chính xác và lý do chọn default; code typed, module nhỏ, docstring/chú thích giải thích **vì sao** ở luật khó, không có logic trùng giữa web/CLI; README/config/schema/ADR cập nhật; các lệnh test/lint/typecheck đạt hoặc có lỗi môi trường được phân loại và cách tái hiện. Nếu thiếu ground truth thật, không được ghi “đạt accuracy trên họp thật”.

## 11. Bản đồ file và thứ tự commit đề xuất

| Work package | File hiện có cần xem/sửa | File mới hợp lý nếu chưa có |
|---|---|---|
| WP0 | .gitignore, README.md, configs/default.yaml, web/app.py, multi_source_fusion.py | docs/reports/baseline.md, timing service |
| WP1 | adapters/pyannote_segmentation.py, pipeline/speaker_turns.py, audio/synchronization.py, pipeline/stages/activity_detection.py | pipeline/stages/shared_segmentation.py, cache contract |
| WP2 | application/speakers.py, speaker/encoder.py, domain/speaker_classifier.py, domain/schemas.py | speaker/clustering.py, speaker/open_set.py, encoder adapter WeSpeaker |
| WP3 | fusion/features.py, speaker/identification.py, pipeline/multi_source_fusion.py | speaker/source_quality.py, configs/calibration/*.json |
| WP4 | adapters/phowhisper_asr.py, asr/segment_asr.py, asr/quality.py, pipeline/stages/chunking.py, transcript_stitching.py | ASR router, optional CT2 adapter |
| WP5 | fusion/confusion_network.py, fusion/alignment.py, fusion/baselines.py, fusion/provenance.py | fusion/decision_trace.py nếu schema hiện không đủ |
| WP6 | web/app.py, web/templates/, web/static/, storage/, domain/schemas.py | API speaker label mapping + migration khi cần |
| WP7 | evaluation/, tests/unit/, tests/integration/, docs/, README.md | benchmark runner/report schema, deterministic fixtures |

Đây là gợi ý phân lớp, **không** ép tạo file mới nếu module hiện tại có thể mở rộng gọn. Sau baseline commit, đề nghị commit tuần tự: Git/schema/timing; shared pyannote VAD; diarization/unknown; enrollment/encoder; source ID fusion; ASR/routing; transcript fusion; web/export; tests/docs. Mỗi commit phải chạy tập test liên quan; cuối cùng chạy toàn bộ. Ghi trong báo cáo bàn giao SHA commit từng giai đoạn, lệnh tái hiện benchmark và mọi decision gate đã qua/chưa qua. Không mở PR hoặc push nếu người giao việc chỉ yêu cầu local.

## 12. Cơ sở nghiên cứu và giới hạn áp dụng

Các nguồn dưới đây giải thích **lý do thử nghiệm**; không có nguồn nào chứng minh sẵn hệ số/trọng số tối ưu cho tiếng Việt ghi bằng điện thoại của dự án:

| Nguồn | Điều rút ra áp dụng cho kế hoạch |
|---|---|
| [Model card pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) và [Bredin, Interspeech 2023](https://www.isca-archive.org/interspeech_2023/bredin23_interspeech.html) | Segmentation 10 giây có local speaker/overlap; diarization toàn file cần embedding và global clustering. |
| [ECAPA-TDNN, Interspeech 2020](https://www.isca-archive.org/interspeech_2020/desplanques20_interspeech.html) và [WeSpeaker, Wang et al.](https://arxiv.org/abs/2210.17016) | Encoder pretrained cho few-shot embedding; lựa chọn bằng benchmark đúng miền, không fine-tune bằng vài mẫu cá nhân. |
| [VoxWatch, Peri et al.](https://arxiv.org/abs/2307.00169) và [quality calibration theo thời lượng/nhiễu](https://www.sciencedirect.com/science/article/abs/pii/S0167639315000643) | Open-set threshold chịu ảnh hưởng số người đăng ký, thời lượng, nhiễu; cần calibration và báo false accept/false reject. |
| [CHiME-7 baseline](https://www.chimechallenge.org/challenges/chime7/task1/baseline), [NTT CHiME-7](https://arxiv.org/abs/2309.12656), [DOVER-Lap](https://arxiv.org/abs/2011.01997) | Đa microphone có thể chọn kênh theo thời điểm hoặc late-fuse kết quả diarization; DOVER-Lap là phương án nâng cao, không bắt buộc cho hai điện thoại. |
| [ACE Challenge về DRR/RT60](https://research.tudelft.nl/en/publications/estimation-of-room-acoustic-parameters-the-ace-challenge/), [Android AGC](https://developer.android.com/reference/android/media/audiofx/AutomaticGainControl), [Shure về comb filtering](https://www.shure.com/damfiles/default/global/documents/publications/en/performance-production/microphone_techniques_for_recording_english.pdf-bb0469316afdb6118691d2f3f5e3ff01.pdf) | Gần mic thường tăng tỉ lệ âm trực tiếp, nhưng RMS bị AGC và độ vang làm lệch; không cộng waveform thô của máy độc lập. |
| [WhisperX, Interspeech 2023](https://www.isca-archive.org/interspeech_2023/bain23_interspeech.html), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | ASR theo cửa sổ và backend nhanh là ứng viên A/B; số tăng tốc trên GPU/tập khác không suy ra CPU của dự án. |
| [ROVER, NIST](https://www.nist.gov/publications/post-processing-system-yield-reduced-word-error-rates-recognizer-output-voting-error) | Căn nhiều giả thuyết và bầu chọn từ là baseline; một nguồn không chạy không được biến thành bằng chứng từ bị thiếu. |

## 13. Câu giao việc ngắn cho agent

“Hãy đọc và **triển khai đầy đủ** kế hoạch tại /Users/thien/Documents/ChatGPT/Luận văn/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md trên repository /Users/thien/Documents/School/Luận văn. Bắt đầu bằng WP0: khởi tạo Git sạch trong repository mã, hoàn thiện .gitignore để không commit dataset/data/model/audio/output và chốt baseline. Tiếp tục tuần tự các WP, không dừng ở việc sửa một module. Hệ thống phải tạo Người lạ 1/2 ổn định ngay cả khi không có hồ sơ đăng ký; VAD B dùng một lần suy luận pyannote/nguồn; ASR và merge đa nguồn có bằng chứng, thời gian và quality gate. Chạy test/lint/typecheck, chạy demo model thật nếu cache có sẵn, bàn giao commit SHA, bảng A/B, lỗi còn lại và cách tái hiện. Giữ vùng nói chồng not_run và không thực hiện phần biên bản trong đợt này.”
