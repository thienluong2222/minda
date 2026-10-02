# Đánh giá demo Meeting Pipeline — 16/09/2026

## 1. Kết luận

**Demo chạy được luồng tải nhiều file → xử lý bằng model thật → timeline → nghe và xuất file. Tuy nhiên, chưa đủ để nghiệm thu bài toán “ai nói gì” và tách lời của hai người nói đồng thời.**

Điểm cần xử lý trước là chất lượng và tính đúng đắn của đầu ra: clip tách giọng bị clipping khi lưu; chia đoạn làm mất ngữ cảnh; nhận diện/track người nói chưa được tích hợp; trọng số nguồn thường bằng nhau; đồng bộ có trường hợp nhận sai.

Giao diện đã khá gọn, phù hợp hướng minimalist. Cần bổ sung thông tin đối chiếu và trạng thái chất lượng, thay vì trang trí thêm.

Đây là đợt **kiểm tra và đánh giá**, không thay đổi mã ứng dụng, model, ngưỡng hay dữ liệu gốc. Không đọc thư mục tài liệu tham khảo. Các lần chạy mới dùng thư mục kiểm thử riêng, model đã tải sẵn và chế độ offline.

## 2. Phạm vi và phương pháp

- Đọc mã đang chạy, cấu hình, README, quyết định kỹ thuật và bộ kiểm thử.
- Kiểm tra hai kết quả có sẵn: `real-test-1` và `real-test-2`.
- Mở demo thực trên `127.0.0.1:8000`.
- Chạy một bản kiểm thử cùng mã trên `127.0.0.1:8001`, dữ liệu đầu ra riêng trong `/private/tmp/meeting-demo-review/`.
- Tải qua giao diện hai file thật `Nguyen_2.aac` và `Thien_2.aac`; chờ pipeline hoàn tất.
- Thử bộ lọc, phát audio trên trình duyệt, giao diện 390 px, API xuất file và HTTP Range.
- Chạy toàn bộ 13 test hiện có, Ruff, kiểm tra định dạng và Mypy.
- Đánh giá ASR trực tiếp trên 6 câu VIVOS test, 6 người khác nhau, seed `20260916`, mỗi câu 2–10 giây; chọn trước khi xem kết quả.
- Tạo một ca nói chồng có kiểm soát từ hai câu trong nhóm trên để kiểm tra mất thông tin khi đi qua pipeline.
- Kiểm tra độc lập clipping, trọng số, đồng bộ, giới hạn chiều dài ASR, đầu vào lỗi và phục hồi job.

Không có bản chép lời/người nói chuẩn cho hai cuộc họp cá nhân. Vì vậy **không công bố WER/CER/DER hoặc độ chính xác danh tính cho hai cuộc họp này**. Không thực hiện chấm nghe thủ công để tạo ground truth. Các kiểm tra số học và phát audio không được diễn giải thành đánh giá nghe chủ quan.

## 3. Kết quả kiểm thử

| Hạng mục | Kết quả quan sát |
|---|---|
| Test hiện có | 13/13 qua; 2 cảnh báo deprecation ở lớp TestClient |
| Ruff | Qua |
| Định dạng | 42 file đã đúng định dạng |
| Mypy | Qua, 23 file nguồn |
| Tải hai file thật qua UI | Thành công, chuyển sang trang đang xử lý rồi kết quả |
| Chạy lại cuộc họp 2 | 26,82 giây; 27 dòng; 10 dòng thuộc 5 vùng nói chồng |
| So với lần chạy cũ | 27/27 nội dung transcript giống nhau |
| Thiết lập đo thời gian | CPU, Torch giới hạn 4 luồng, model đã cache; không đại diện cho mọi máy/cấu hình |
| Bộ lọc nói chồng | 27 → 10 dòng; hoạt động |
| Bộ lọc “Cần kiểm tra” | Hoạt động; hiện tương đương nhãn nói chồng, chưa bao phủ lỗi ASR khác |
| Audio trên browser | Phát được; `readyState=4`, thời lượng 75,456 giây, không có lỗi media |
| HTTP Range | 206, trả đúng 100 byte được yêu cầu ở cả hai run |
| Xuất JSON/CSV/TXT/ZIP | 8/8 lượt yêu cầu API thành công cho hai run |
| ZIP | Hai gói kiểm tra CRC đều không có entry hỏng |
| Mobile 390 px | Không tràn ngang; các trường mất tiêu đề khi bảng chuyển thành khối dọc |
| File rỗng / 9 nguồn / quá giới hạn thử | Lần lượt trả 400 / 400 / 413 |
| File không phải audio | Được nhận 202, sau đó job chuyển failed; cần thông báo sớm hơn và rõ hơn |
| Tên chỉ chứa khoảng trắng | Được chấp nhận và lưu thành chuỗi rỗng |
| Khởi tạo lại app với job running cũ | Job vẫn running; không phục hồi/đổi trạng thái |

Bằng chứng: [browser-rerun-summary.json](reviews/2026-09-16/browser-rerun-summary.json), [api-and-dsp-audit.json](reviews/2026-09-16/api-and-dsp-audit.json).

### 3.1 ASR riêng trên giọng đọc sạch

| Mẫu | Lời chuẩn | Kết quả ASR |
|---|---|---|
| VIVOSDEV08_090 | Vì không có tiền đóng học phí | vì không có tiền đóng học phí. |
| VIVOSDEV09_142 | Về chuyện đang theo dõi bọn gián điệp nước ngoài | về chuyện đang theo dõi bọn gián điệp nước ngoài. |
| VIVOSDEV16_198 | Các phật tử hưởng ứng lời kêu gọi của thầy như thế nào | các phật tự hưởng ứng lời kêu gọi của thầy như thế nào. |
| VIVOSDEV18_240 | Mời tham dự cuộc thi viết ngắn một giờ không điện | mời tham dự cuộc thi viết ngắn một giờ không điện. |
| VIVOSDEV10_176 | Trong tình thế ấy chỉ đám trẻ ven sông | trong kình thế ấy chỉ đám trẻ ven sông. |
| VIVOSDEV11_160 | Ngụ ấp Hòn Ngang | ngủ ấp hoàng nhang. |

- Tổng audio: **20,499 giây**.
- CER gộp: **2,99%**.
- Lỗi token phân cách bằng khoảng trắng: **9,26%**; không gọi đây là WER theo từ tiếng Việt đã phân tách ngôn ngữ học.
- Chuẩn hóa: Unicode NFC, chữ thường, dấu câu thành khoảng trắng, gộp khoảng trắng, giữ dấu tiếng Việt. CER tính trên chuỗi đã chuẩn hóa, có khoảng trắng.
- Ba trong sáu câu đúng hoàn toàn sau chuẩn hóa.

Đây là phép chẩn đoán nhỏ với giọng đọc sạch, không phải benchmark đại diện cho cuộc họp. Chưa kiểm chứng độc lập mức trùng dữ liệu tiền huấn luyện/fine-tune của checkpoint với corpus. Kết quả chỉ cho thấy ASR riêng có thể đọc tốt những mẫu này; chưa có cơ sở đổi ASR chỉ từ những transcript xấu ở đầu ra toàn pipeline.

Bằng chứng và thời gian từng câu: [asr-benchmark.json](reviews/2026-09-16/asr-benchmark.json).

### 3.2 Ca nói chồng có lời chuẩn

Hai người đọc hai câu đầu trong bảng trên. ASR trực tiếp chép đúng cả hai câu.

Ca thử dài 5,875 giây: đặt câu A từ 0,5 giây, câu B từ 1,5 giây; tạo hai nguồn với hệ số lần lượt `A + 0.45 B` và `0.45 A + B`. Không thêm tiếng ồn, vọng phòng hoặc trôi đồng hồ. Khoảng file gốc có cả im lặng; không dùng biên file làm nhãn speech-frame để tính DER/OSD.

| Khoảng pipeline | Nói chồng | Transcript |
|---|---|---|
| 0,85–1,90 s | Không | vì không có tiền. |
| 1,90–2,60 s | Có, nhánh 1 | n. |
| 1,90–2,60 s | Có, nhánh 2 | đã học tiếng. |
| 2,60–4,35 s | Không | theo dõi bọn gián điệp nước ngoài. |

Pipeline phát hiện một vùng chồng nhưng **không khôi phục đủ hai câu**; mọi dòng vẫn lấy `source-1`, và track ID không nối người nói qua các vùng. Không cần suy diễn lỗi từ độ tự nhiên của câu: ca này có lời chuẩn để đối chiếu trực tiếp.

Bằng chứng: [controlled-overlap.json](reviews/2026-09-16/controlled-overlap.json). Đây là một ca kiểm thử dễ và nhỏ, chưa phải tỷ lệ lỗi nói chồng tổng quát.

## 4. Các vấn đề cần ưu tiên

### P1 — Clip phát lại bị clipping và khác đầu vào ASR

Vị trí: `src/meeting_pipeline/pipeline/prototype.py:303–304`, `:435–440`.

`sf.write` lưu WAV mặc định PCM16 trong khi đầu ra separator có thể vượt khoảng [-1, 1]. Sau khi lưu, `_transcribe` vẫn nhận mảng float chưa bị giới hạn này. Do đó `asr_input_artifact_id` không trỏ đến biểu diễn audio thực sự đã đưa vào ASR.

- 17/20 clip nói chồng từ hai cuộc họp có mẫu chạm gần full scale (ngưỡng đo `abs(sample) >= 0.999`).
- Clip `real-test-1/.../clips/processed/segment-9-track-1.wav`: **69,31%** mẫu gần full scale.
- Chạy lại separator cho đúng đoạn đó: đỉnh mảng float **11,713**, đỉnh file lưu **1,0**, sai khác lớn nhất **10,713**.
- ASR mảng float: “má này không vầy đâu ạ.”; ASR file phát lại: “mã này nó.”

**Cần sửa:** quy định gain/chuẩn hóa rõ trước khi xuất clip; lưu và đưa vào ASR đúng cùng một tín hiệu, ưu tiên đọc lại artifact đã chốt; giữ thông tin gain trong provenance. Nếu lưu float để bảo toàn tín hiệu, vẫn phải có chính sách biên độ phù hợp khi phát. Các đặc trưng so chất lượng nguồn phải được đo trước bước chuẩn hóa riêng từng clip.

**Nghiệm thu:** kiểm tra round-trip audio, không clipping do ghi file; ASR-input và clip đối chiếu khớp trong sai số định dạng; hồi quy đúng clip lỗi và các ca nói chồng có tham chiếu.

Bằng chứng: [clipping-reproduction.json](reviews/2026-09-16/clipping-reproduction.json).

### P1 — Chưa thực hiện đầy đủ “ai đang nói”

Vị trí: `prototype.py:224–257`, `:308–314` và các route trong `web/app.py`.

- 49/49 dòng của hai run có `speaker_id=null`, `speaker_status=unknown`.
- Model segmentation chỉ được dùng để đếm số người hoạt động; không sử dụng các slot để nối track người nói.
- `track_id` tạo mới theo từng region/nhánh, chưa có danh tính vô danh ổn định xuyên suốt cuộc họp.
- Có cấu trúc bảng enrollment trong storage nhưng chưa có luồng UI/API/enrollment/ECAPA nối vào prototype.

Tài liệu repo ghi nhận chủ ý không đăng ký giọng cho hai cuộc họp cá nhân. Có thể giữ chế độ đó cho chúng; **phần sản phẩm đăng ký người nói vẫn chưa hoàn thành** so với yêu cầu ban đầu.

**Cần sửa:** có profile đăng ký, trích embedding ECAPA từ mẫu support, nhận diện với ngưỡng/margin; nối track và giải hoán vị hai đầu ra separator; duy trì Speaker 1/2/... ổn định khi chưa biết tên; chỉ gán tên khi đủ bằng chứng. Tên điện thoại không phải nhãn người nói.

**Nghiệm thu:** test support/query khác nhau, người chưa đăng ký, đổi lượt và nói chồng; không đếm một người thành track mới sau mỗi lần ngắt.

### P1 — Cắt đoạn quá ngắn; ASR đoạn dài chưa được chia an toàn

Vị trí: `prototype.py:267`, `:299`, `:443–463`, `:504–519`.

- Hai cuộc họp có 18/49 dòng dưới 1 giây. Có đoạn nói chồng chỉ 0,25 giây.
- Chuyển trạng thái 1/2 người lập tức cắt region; separator nhận đúng crop ngắn, không có context như cấu hình dự kiến.
- Cấu hình `separation.chunk_seconds/context_seconds/overlap_seconds` và `asr.max_chunk_seconds=25` chưa chi phối luồng thực thi.
- Kiểm tra processor: đầu vào 40 giây tạo 3.000 frame, chỉ tương ứng cửa sổ 30 giây. `_transcribe` không có vòng chia cửa sổ hoặc xử lý phần còn lại.
- `max_new_tokens=128` cũng là giới hạn có thể cắt nội dung dài; chưa có cảnh báo kết thúc do giới hạn.

**Cần sửa:** làm mượt activity, dùng context trước/sau để tách, ánh xạ crop chính xác trở lại timeline; ghép lời theo track và ngắt tự nhiên; chia ASR theo giới hạn thực, nối kết quả không trùng; giữ riêng thời gian speech và thời gian context. Thêm cổng chất lượng sau tách, đánh dấu nhánh không đủ tiếng nói thay vì luôn chép lời.

**Nghiệm thu:** hai câu trong ca chồng phải được phục hồi và theo đúng người; thêm fixture lời liên tục >30 giây có nội dung riêng ở cuối để phát hiện mất đuôi. Chưa thể chốt chất lượng chỉ vì ASR trả text khác rỗng.

Bằng chứng: [long-input-check.json](reviews/2026-09-16/long-input-check.json), [controlled-overlap.json](reviews/2026-09-16/controlled-overlap.json).

### P1 — Trọng số chưa phản ánh chất lượng nguồn/người cần nghe

Vị trí: `prototype.py:282–284`, `:334–344`, `:404–406`.

`speech_presence=min(1,RMS/0.05)` và `speech_noise_contrast=min(1,RMS/0.02)` đều suy từ cùng RMS; không thực sự đo xác suất có lời hoặc tương phản tiếng nói/nền. Khi RMS ≥ 0,05 và chưa clipping, mọi nguồn cùng nhận chất lượng [1,1,1].

- Cuộc họp 1: **20/20 dòng có nhiều nguồn hợp lệ đều bằng trọng số**.
- Cuộc họp 2: **15/24 dòng có nhiều nguồn hợp lệ đều bằng trọng số**.
- Khi bằng nhau, `max` chọn nguồn đầu trong thứ tự tải; lựa chọn không phải bằng chứng nguồn gần người nói hơn.
- Hai nhánh overlap dùng cùng nguồn được chọn trước khi tách. `selection_weight` chép lại `identity_weight`; chưa có lựa chọn theo từng người sau nhận diện.
- Hệ số/temperature trong YAML chưa được truyền vào lời gọi `identity_weights`.

**Cần sửa:** lấy VAD/speech evidence thật, ước lượng nền trong khoảng hợp lệ, đo méo/clipping và chất lượng sau tách; hiệu chuẩn trên dev. Chọn nguồn theo từng track, thêm độ phù hợp embedding sau nhận diện, giữ tách biệt trọng số nhận diện và trọng số chọn ASR. Đổi thứ tự file không được làm thay đổi nội dung chỉ vì hòa điểm tùy ý.

**Nghiệm thu:** có ca một nguồn nhiều nhiễu dù to hơn, một nguồn mất coverage, hai người gần hai máy khác nhau; bảng trọng số giải thích được và nguồn được chọn vượt baseline nguồn cố định trên dữ liệu dev.

Bằng chứng: [existing-output-audit.json](reviews/2026-09-16/existing-output-audit.json), [api-and-dsp-audit.json](reviews/2026-09-16/api-and-dsp-audit.json).

### P1 — Đồng bộ còn nhận sai; chưa xử lý trôi đồng hồ

Vị trí: `pipeline/stages/synchronize.py:69–91`, `prototype.py:165–182`.

Điểm tốt: lệch đầu file của hai cuộc họp khá hợp lý (0,8 s; 8,64 s; 1,51 s). Kiểm tra tương quan waveform tại 12 cửa sổ sau đồng bộ thấy đỉnh trong khoảng |0,31–9,69| ms. Đây là kiểm tra dư lệch tương đối, có ảnh hưởng âm học, không phải sai số so với đồng hồ chuẩn.

Các lỗi độc lập:

1. Trong 10 cặp nhiễu điều biên độc lập, **6 cặp bị chấp nhận là đồng bộ**. Chỉ so peak/second-peak chưa đủ; đây là negative test, không phải ước lượng false-accept rate tổng quát.
2. Fixture hiện có trong `test_synchronization.py`: reference chứa event tại 0 s, source chứa cùng event tại 1 s. Theo `t=u+b`, đáp án phải `b=-1 s`. Hàm trả `+1 s`, và test hiện tại lại chờ `+1 s`, nên qua dù hai event lệch 2 giây sau mapping. Lấy trị tuyệt đối tương quan envelope có thể ưu tiên đỉnh âm không đúng.
3. Luồng chỉ ước lượng offset; `scale=1` và `drift_unresolved` cho các nguồn ngoài reference. `allow_drift=true` chưa bật được xử lý drift thực.
4. Nguồn alignment_failed bị bỏ khi phát hiện activity, nhưng vẫn có thể được xuất trong mục “Nguồn đã đồng bộ”.

**Cần sửa:** điều kiện tương quan đủ mạnh và đúng chiều, refine nhiều cửa sổ, kiểm tra nhất quán lag và lượng speech chung; fit affine/piecewise theo đặc tả; sửa ground truth của test; cách ly nguồn thất bại và báo rõ trên UI.

**Nghiệm thu:** offset âm/dương, nhiều cửa sổ, đồng hồ trôi, file khác cuộc họp và file không đủ speech; chỉ đánh dấu aligned khi bằng chứng đạt tiêu chí.

Bằng chứng: [sync-sign-reproduction.json](reviews/2026-09-16/sync-sign-reproduction.json), [api-and-dsp-audit.json](reviews/2026-09-16/api-and-dsp-audit.json).

### P2 — Coverage và truy vết clip cần chặt chẽ hơn

Vị trí: `prototype.py:289–298`, `:350–358`, `:399–419`.

- Khi một region đi qua điểm một file kết thúc và file khác bắt đầu, chưa chắc có một nguồn phủ cả region. Fixture coverage liên tục nhưng không có nguồn phủ toàn bộ đã làm pipeline ném `No eligible source for detected speech region`.
- `original_spans.start_sample/end_sample` được tính trên audio đã decode 16 kHz. Với file gốc 44,1 kHz, chúng không phải chỉ số mẫu ở bản gốc. Chưa ghi rõ sample rate/clock của span.
- “Original clip” thực chất lấy từ bản mono 16 kHz; cần ghi nhãn đúng để người đối chiếu không nhầm với bản gốc native-rate.
- UI chưa cho nghe original clip cạnh processed clip dù file đã được sinh.

**Cần sửa:** cắt tại coverage boundary hoặc dùng selected_spans rõ ràng; lưu native rate/sample map và transform chain; phân biệt missing coverage với im lặng; cung cấp nút A/B gốc–xử lý.

### P2 — Job chưa phục hồi và thông báo hoàn tất còn quá lạc quan

Vị trí: `web/app.py:37–77`, `:145–184`; `cli.py:124–127`.

- Mã demo dùng BackgroundTasks và khóa trong cùng process web; worker riêng/lease hiện chưa được nối vào demo.
- Sau khi app khởi tạo lại, job running cũ vẫn running vô hạn; test đã tái hiện.
- Giao diện chỉ có queued/running/failed/succeeded, không có giai đoạn, hủy hay tiếp tục.
- Mọi vùng ASR có text đều được tính transcribed; trạng thái “Hoàn tất” không phản ánh unknown, drift_unresolved hay chất lượng kém.
- Tên chỉ có khoảng trắng vẫn hợp lệ; file rỗng/quá dung lượng để lại file/thư mục upload chưa dọn.

**Cần sửa:** worker tách process theo đặc tả, trạng thái/lease bền vững, phục hồi interrupted, progress theo giai đoạn và hủy an toàn. Phân biệt “đã chạy xong” với “đã được kiểm tra chất lượng”. Validate tên sau strip và dọn upload lỗi.

## 5. Giao diện minimalist nên cải thiện thế nào?

### Cấu trúc đề xuất

Giữ nền sáng, một màu nhấn, font hệ thống. Ba khu vực chính:

1. **Người tham gia:** danh sách tên, mẫu đăng ký, thời lượng speech hữu ích, nút nghe và trạng thái sẵn sàng.
2. **Tạo cuộc họp:** tên, người tham gia, danh sách file đã chọn có tên/thời lượng; trường “đặt gần ai” tùy chọn và không dùng làm nhãn danh tính.
3. **Kết quả:** thanh tóm tắt + ba tab `Timeline`, `Nguồn âm thanh`, `Tải kết quả`.

### Những thay đổi hữu ích nhất

- Hiển thị `Nguyen_2.aac`, `Thien_2.aac` bên cạnh source ID. Người dùng không cần mở JSON để biết file nào được chọn.
- Mỗi dòng timeline gồm thời gian dạng `mm:ss`, người nói/Speaker ID, nội dung và nút nghe. Hai dòng nói chồng phải thể hiện cùng khoảng thời gian rõ ràng.
- Một panel chi tiết chỉ mở khi chọn đoạn: audio gốc, audio đã xử lý, bảng trọng số từng nguồn, lý do lựa chọn, cảnh báo và các tên ứng viên khi có.
- Dùng một bộ phát chung khi đối chiếu các nguồn tại cùng mốc; dừng nguồn cũ khi chuyển. Hiện mỗi audio control hoạt động độc lập, dễ phát nhiều nguồn cùng lúc và khó giữ cùng thời điểm.
- Trong tab nguồn, hiển thị khoảng coverage, offset, trạng thái drift, nguồn không dùng được; cho tải từng file aligned.
- Thanh trạng thái như: “Đã xử lý · 27 đoạn · 5 vùng nói chồng · 27 đoạn chưa xác định người nói”. Không chỉ ghi “Hoàn tất”.
- Progress theo bước: đọc file → đồng bộ → phân đoạn/tách → nhận diện → chép lời → xuất kết quả. Không cần phần trăm giả nếu chưa đo được.
- Đổi `unknown`, `overlap`, `succeeded` thành nhãn tiếng Việt phù hợp; dùng thông báo lỗi dễ hiểu và phần chi tiết kỹ thuật thu gọn.
- Mobile: giữ nhãn “Người nói”, “Nguồn”, “Thời gian” trong từng card; hiện tiêu đề bảng bị ẩn nên các giá trị đứng riêng thiếu ngữ cảnh.
- Giảm số audio control tải/hiển thị đồng thời; dùng panel chi tiết và phân trang/ảo hóa khi cuộc họp dài.

## 6. Thứ tự sửa và tiêu chí giao việc

| Thứ tự | Công việc | Điều kiện hoàn thành |
|---|---|---|
| 1 | Clip/ASR-input và provenance | Không clipping do serialize; nghe đúng tín hiệu dùng cho ASR; biết rate/clock của mọi span |
| 2 | Đồng bộ và coverage | Sửa fixture sai dấu; từ chối nguồn không liên quan; refine nhiều cửa sổ; không crash ở coverage boundary |
| 3 | Nói chồng và độ dài đoạn | Có context, chia ASR dài, kiểm chất lượng nhánh; ca hai câu không mất nội dung |
| 4 | Track và enrollment | Speaker ID ổn định, nhận tên từ support/query, xử lý unknown và hoán vị separator |
| 5 | Trọng số có ý nghĩa | Dùng quality evidence thật; chọn theo track; hiển thị giải thích và kiểm ablation |
| 6 | Demo dễ đối chiếu | Tên nguồn thật, A/B clip, trọng số, trạng thái chất lượng, tiến độ và phục hồi job |
| 7 | Đánh giá có ground truth | Bộ dev/test tách biệt, báo riêng sạch/mô phỏng/cuộc họp, không dùng hai cuộc họp cá nhân để tune |

Nên giao theo lỗi có bằng chứng và fixture tái hiện, tránh mở rộng tính năng trước khi các bước 1–3 ổn định. Chỉ cân nhắc thay mô hình sau khi đã loại được lỗi tiền/hậu xử lý và đo trên bộ kiểm thử phù hợp.

## 7. Bằng chứng và cách chạy lại

Các JSON đo đạc và script kiểm thử độc lập được lưu trong `docs/reviews/2026-09-16/`.

- `benchmark.py`: 6 mẫu ASR sạch, tái hiện clipping thật, kiểm giới hạn processor.
- `audit.py`: API/export/Range, đầu vào lỗi, trạng thái restart, trọng số, offset và negative cases.
- `overlap_check.py`: tạo hai nguồn nói chồng có lời chuẩn rồi chạy pipeline thật.
- `serve_review.py`: server kiểm thử riêng trên 8001, không ghi vào dữ liệu demo chính.

Chạy script từ môi trường `.venv` của dự án. Chúng dùng đường dẫn dự án hiện tại và output tạm `/private/tmp/meeting-demo-review/`; có thể đổi các biến ROOT/OUT khi chuyển máy. Không tự tải model hoặc gửi audio đến dịch vụ ASR ngoài.

Hai JSON phụ `existing-output-audit.json` và `sync-sign-reproduction.json` ghi rõ các phép đo/case; số liệu không phải đánh giá thống kê trên toàn dataset. Các artifact audio của lần chạy UI/mô phỏng mới ở thư mục tạm; hai run ban đầu và audio gốc vẫn ở nguyên vị trí trong dự án.

**Đánh giá cuối:** đủ để trình diễn luồng kỹ thuật ban đầu; chưa đủ để tuyên bố nhận diện người nói hoặc chép lời riêng hai người nói chồng đạt yêu cầu. Ưu tiên sửa tính đúng đắn của tín hiệu và phân đoạn, sau đó hoàn thiện nhận diện và UI đối chiếu.
