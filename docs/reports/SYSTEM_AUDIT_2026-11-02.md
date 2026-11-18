# Kiểm tra toàn hệ thống Minda — 02/11/2026

## Kết luận

Ghi nhận **11 mục tồn đọng đã xác nhận**: **7 lỗi chức năng**, **1 vấn đề vận hành/trạng thái**, **3 vấn đề chất lượng và khả năng tái lập kiểm thử**. Theo ưu tiên: **4 P1, 5 P2, 2 P3**. Ba nhóm tính năng chưa hoàn thiện được thống kê riêng, không cộng vào 11 lỗi.

Các bộ kiểm thử có sẵn đều đạt nhưng chưa bao phủ các tình huống sửa lời chép, phạm vi phiên họp/biểu quyết và hủy ngay lúc công bố kết quả. Vì vậy chưa nên coi hệ thống đã đủ ổn định để lập biên bản thực tế mà không rà soát.

Đợt này chỉ kiểm tra, tái hiện và viết báo cáo. **Không sửa mã nguồn, không hủy/chạy lại tác vụ thật, không khởi động lại ứng dụng chính, không thay dữ liệu cuộc họp thật.** Các thao tác ghi sử dụng MongoDB riêng tại cổng 27290 và tài khoản giả; frontend kiểm thử tại cổng 18013. Không tải mô hình mới.

## Phạm vi và bằng chứng

- Mã đang kiểm tra: nhánh `codex/web-mongodb-upgrade`, HEAD `27c67aa01e53e046388e195da9a329b4376f2e4a`, bao gồm các thay đổi chưa commit hiện có.
- Đối chiếu mã quản lý người dùng/phiên, phân quyền/CSRF, meeting/timeline, worker, biên bản, artifact/sao lưu và frontend.
- Kiểm thử unit, integration, experiment không yêu cầu dataset/model riêng, toàn bộ API và một model smoke PhoWhisper/Silero.
- Thử LLM Qwen và embedding E5 đang có bằng dữ liệu tổng hợp ngắn, chạy offline.
- Đối chiếu chỉ đọc các file/artifact và Word/ZIP đã lưu trong database ứng dụng thật.
- Tái hiện hành vi mới bằng script và giao diện trên dữ liệu giả. Không chạy lại toàn bộ suy luận cho cuộc họp thật.

Bằng chứng chi tiết: [thư mục kết quả](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/system-audit-20261102>). Mã băm trước/sau được ghi trong `source_before.json` và `validation_summary.json`.

## Kết quả các kiểm tra nền

| Kiểm tra | Kết quả |
| --- | --- |
| Unit + integration + experiment | **316 đạt**, 1 bài model encoder được loại khỏi nhóm chạy này |
| Backend API với MongoDB thật, database riêng mỗi test | **42 đạt** |
| Model smoke PhoWhisper/Silero trên mẫu VIVOS ngắn | **1 đạt** |
| Tổng kiểm thử Python thực sự đạt | **359** |
| Logic thông báo frontend | **9 kiểm tra đạt** |
| TypeScript + Vite production build | Đạt |
| Prettier toàn frontend | Đạt |
| Ruff `src tests` | Chưa đạt: **10 lỗi trong 3 file test**, không có lỗi Ruff trong `src` |
| Ruff format | **2 file test** cần định dạng; 215 file khác đạt |
| Mypy `src/meeting_pipeline` | Chưa đạt: **74 lỗi trong 22 file**, đã kiểm tra 103 source files |
| LLM thực | Sinh được JSON trong thử ngắn; khoảng 7,8 giây cho cả phiên thử LLM và embedding |
| Embedding thực | 2 câu, mỗi vector 384 chiều |
| Artifact thật | **262/262** file còn tồn tại và đúng SHA-256; đã đọc khoảng 347,6 MB |
| Word/ZIP/manifest thật | **7/7** phiên bản khớp; không có thư mục phiên bản bị thiếu |
| Console ở luồng UI kiểm tra | Không ghi nhận warning/error |

Model smoke ngắn xác nhận mô hình chạy được, không phải benchmark chất lượng trên cuộc họp nhiều giờ, nhiều điện thoại hay một mẫu đại diện cho toàn bộ văn bản hành chính. Không có số đo WER/DER hay chất lượng adapter mới được công bố từ lần kiểm tra này.

## Danh sách 11 mục tồn đọng

P1: nên sửa trước khi tin cậy nội dung biên bản. P2: ảnh hưởng truy vết, lưu/sửa, vận hành hoặc khả năng kiểm thử. P3: vấn đề bảo trì và chuẩn kiểm tra mã.

| Mã | Mức | Loại | Tồn đọng và bằng chứng |
| --- | --- | --- | --- |
| F01 | **P1** | Chức năng, tái hiện | Người dùng nhập/sửa chữ cho đoạn ASR `not_run`, `failed` hoặc `empty`: API trả 200 và lưu chữ, nhưng bước tạo đơn vị biên tập vẫn loại đoạn theo trạng thái ASR cũ. |
| F02 | **P1** | Chức năng, tái hiện | Giờ kết thúc lấy lần đầu xuất hiện, không phân biệt kết thúc phiên và toàn cuộc. Phiên đầu kết thúc 10 giờ, toàn cuộc 11 giờ: trả **10**, trạng thái `supported`. |
| F03 | **P1** | Chức năng, tái hiện | Các số biểu quyết thuộc nhiều nội dung/vòng bị ghép chung: tổng **20** từ A, tán thành **15** từ B, không tán thành **2** từ A, vẫn `supported`. |
| F04 | **P1** | Chức năng, tái hiện tại bước ghép dữ liệu | Tạo lại với nguồn mới vẫn giữ nguyên ô đã sửa tay và căn cứ/trạng thái cũ theo `field_id`. Giá trị mới **11** bị thay bằng **10**, vẫn `supported`, chưa đánh dấu xung đột của ô. |
| F05 | **P2** | Chức năng, tái hiện | Khi chuyển transcript sang đầu vào biên bản, liên kết clip được đặt ở thuộc tính mà bộ nạp không đọc. File audio còn, nhưng `IndexedTurn.clip_path` trở thành null. |
| F06 | **P2** | Chức năng, tái hiện | Hủy ngay trước công bố transcript: phiên bản đã được ghi vào database và xuất hiện trong Lịch sử dù `active_transcript_id` vẫn null. |
| F07 | **P2** | Chức năng, tái hiện trên trình duyệt | Sửa cấu hình trường của mẫu rồi chuyển trang: không có xác nhận chưa lưu; quay lại thì giá trị sửa bị mất. |
| O01 | **P2** | Vận hành/trạng thái, quan sát thật + đối chiếu mã | Database có một tác vụ `running` với heartbeat cuối ngày 27/10. Recovery chỉ chạy khi worker chạy lại; giao diện không có trạng thái riêng cho tác vụ mất heartbeat. |
| T01 | **P3** | Kiểm tra mã, chạy công cụ | Mypy còn 74 lỗi/22 file, gồm kiểu ndarray thiếu tham số, kiểu gán không phù hợp và ignore/cast thừa. Đây không phải 74 lỗi runtime đã tái hiện. |
| T02 | **P3** | Kiểm tra mã, chạy công cụ | Ruff còn 10 lỗi trong 3 file test; thêm 2 file test chưa đúng định dạng. Frontend format và production build đều đạt. |
| T03 | **P2** | Khả năng tái lập, xác nhận từ mã và Git | Một số test đọc một run cụ thể trong `data/meetings/...` bị Git ignore. Máy hiện tại có dữ liệu nên test đạt; checkout sạch không có run này sẽ không chạy được các test đó. |

### F01 — Chữ sửa tay chưa có hiệu lực ở phần biên tập

Đã tạo bốn trường hợp độc lập, sửa qua API thật, chuyển dữ liệu bằng `materialize_transcript`, sau đó gọi `load_indexed_turns` và `make_units`:

| Trạng thái ASR gốc | API sửa | Số đơn vị biên tập sau sửa |
| --- | --- | --- |
| not_run | 200 | **0** |
| failed | 200 | **0** |
| empty | 200 | **0** |
| transcribed | 200 | **1** |

Nguyên nhân: [transcripts/service.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/modules/transcripts/service.py:61>) lưu `user_edited` nhưng giữ trạng thái ASR; [evidence_retrieval.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_pipeline/minutes/evidence_retrieval.py:166>) không chuyển sang trạng thái hiệu lực của sửa tay; [text_engine.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_pipeline/minutes/text_engine.py:66>) chỉ nhận `transcribed` hoặc `user_edited`.

Hướng sửa: tách trạng thái nhận dạng gốc khỏi trạng thái chữ có hiệu lực; đưa chữ người dùng xác nhận vào bộ biên tập nhưng giữ nguyên dấu vết ASR và danh tính chưa rõ. Cần kiểm thêm trường hợp xóa chữ và đoạn thuộc khoảng loại khỏi biên bản.

### F02, F03 — Thiếu phạm vi phiên họp và vòng biểu quyết

Hai ca gọi trực tiếp bộ chuẩn hóa đang dùng trong pipeline, không dùng LLM:

- “Phiên một kết thúc lúc mười giờ.” rồi “Toàn bộ cuộc họp kết thúc lúc mười một giờ.” → ô kết thúc nhận **10** và căn cứ của phiên đầu.
- A: tổng 20, tán thành 18, không tán thành 2. B: mới công bố tán thành 15 → ô toàn cục thành **20/15/2**, đều có trạng thái có căn cứ.

Nguyên nhân: [structured_fields.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_pipeline/minutes/structured_fields.py:105>) giữ mốc đầu tiên bằng `setdefault`, còn số phiếu ghi đè riêng từng loại mà không gắn với đề mục/vòng. Kiểm tra tổng chỉ phục vụ tính phần trăm, chưa ngăn các ô đếm không nhất quán được đánh dấu `supported`.

Hướng sửa: gắn sự kiện với phiên/đề mục/vòng và vai trò dự kiến–đính chính–chốt. Chưa biết phạm vi thì giữ cần rà; không chỉ đổi thành “lấy lần cuối toàn cuộc”.

### F04 — Ô sửa tay cũ cần được đối chiếu khi có nguồn mới

Trong đường tạo lại, bộ sinh thử trả ô `end_time=11`; bản trước có `end_time=10`, `user_edited=true`, `supported` và căn cứ `old-turn`. Bước ghép vẫn đưa nguyên ô **10/supported/old-turn** vào lần render lại.

Nguyên nhân: [minutes_pipeline.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/integrations/minutes_pipeline.py:173>) giữ theo `field_id` mà chưa so sánh hiệu lực căn cứ hoặc mẫu. Sau công bố, cờ cũ toàn biên bản được tính theo revision đầu vào mới, không theo từng ô đã giữ.

Đây là tái hiện bước chuẩn bị/ghép dữ liệu bằng bộ sinh thay thế để quan sát chính xác payload; không phải một lần sinh LLM và xuất Word đầy đủ. Việc giữ giá trị người dùng là cần thiết, nhưng cần giữ riêng bản sửa cũ, hiện đề xuất mới và đánh dấu phải đối chiếu khi nguồn hoặc mẫu thay đổi.

### F05 — Liên kết audio mất ở đầu vào biên bản

Trong cả bốn ca F01, file clip gốc còn tồn tại. Trường hợp `transcribed` vẫn sinh đơn vị nội dung bình thường, nhưng `clip_path=null`, cho thấy lỗi này độc lập với F01.

[materialize_transcript](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/integrations/minutes_pipeline.py:27>) viết đường dẫn tuyệt đối vào `evidence_clip_artifact_id`. Bộ nạp lại dò `source_evidence`/`clip_path` tương đối với thư mục biên bản mới, nơi không có thư mục audio gốc. Cần thống nhất cách giải tham chiếu artifact, kiểm quyền và bảo toàn clip qua sinh/sửa/khôi phục. Audio gốc không bị xóa; trình nghe trong frontend có thể vẫn nghe được nhờ clip trên bản transcript.

### F06 — Phiên bản của tác vụ chưa công bố vẫn xuất hiện ở lịch sử

Dùng pipeline giả tạo nội dung nhưng đi qua code lưu thật; đặt yêu cầu hủy sau khi đăng ký file export, trước lần `Context.publish`:

- Publication bị từ chối đúng bằng `Cancelled`.
- `active_transcript_id` vẫn null.
- Database vẫn có **1 phiên bản transcript**, và API Lịch sử trả phiên bản đó.

[Audio integration](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/integrations/audio_pipeline.py:168>) tạo phiên bản trước bước công bố. Cần cleanup/rollback phần chưa công bố hoặc trạng thái committed được kiểm nhất quán ở lịch sử. Luồng minutes cũng ghi phiên bản trước công bố tại [minutes_pipeline.py](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/integrations/minutes_pipeline.py:243>); rủi ro tương tự đã thấy trong mã, chưa tái hiện riêng đường minutes.

### F07 — Bảo vệ chỉnh sửa chưa phủ màn hình mẫu

Trên tài khoản thử, đổi trường `end_time` từ `meeting_end_time` sang `meeting_start_time`, chưa lưu, bấm Cuộc họp. Trang chuyển ngay, không có hộp xác nhận. Quay lại trường trở về `meeting_end_time`.

[TemplateDetail](</Users/thien/Documents/School/Luận văn/web_app/apps/web/src/features/templates/pages.tsx:217>) chưa dùng cơ chế bảo vệ thay đổi như các màn lời chép/biên bản. Cần giữ draft hoặc cảnh báo khi đổi route, tải lại hoặc nhận phiên bản mới. Các form tải mẫu/hồ sơ giọng cũng cần rà áp dụng đồng bộ; lượt này chỉ tái hiện mất cấu hình trường trên TemplateDetail.

Bằng chứng: `ui-probes.json` và [ảnh giao diện thử sau khi quay lại](</Users/thien/Documents/School/Luận văn/web_app/artifacts/system-audit-2026-11-02/template-unsaved-loss.png>).

### O01 — Trạng thái tác vụ và tình trạng tiến trình cần tách rõ

Lúc **22:43 ngày 02/11**, database ứng dụng thật có 32 tác vụ: 26 thành công, 4 thất bại, 1 gián đoạn và 1 `running`. Heartbeat cuối của worker đang trỏ vào tác vụ `running` là **20:59 ngày 27/10**. Cổng 8010 không phản hồi tại lúc kiểm tra.

Không đủ căn cứ kết luận tiến trình bị treo suy luận hay đã được người dùng dừng chủ động. Dữ liệu xác nhận rằng trạng thái lưu không chứng minh tác vụ còn chạy. [Runner.recover](</Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend/worker/runner.py:31>) chỉ chạy trong worker; API/giao diện cần thể hiện heartbeat hết hạn và hướng xử lý an toàn. Không tự sửa trạng thái hoặc thử lại tác vụ thật trong lần audit.

### T03 — Test đạt trên máy hiện tại chưa chứng minh chạy được trên checkout sạch

[Unit facts](</Users/thien/Documents/School/Luận văn/web_app/tests/unit/test_minutes_f3_facts.py:23>) và [integration minutes](</Users/thien/Documents/School/Luận văn/web_app/tests/integration/test_minutes_web.py:23>) phụ thuộc run `data/meetings/1/runs/a6e814e4-ea36-4cc9-8992-ba60b9341ea5`. Git không theo dõi run này và đang ignore dữ liệu đó. Cần đưa fixture tối thiểu, có nguồn gốc rõ vào `tests/fixtures` hoặc dựng dữ liệu trong test. Lượt này xác nhận phụ thuộc từ mã/Git, chưa dựng một checkout sạch đầy đủ.

## Ba nhóm tính năng chưa hoàn thiện

| Nhóm | Hiện trạng | Cần tiếp tục |
| --- | --- | --- |
| G01 — Họp dài, tiếp tục sau ngắt | Vẫn giới hạn 1200 giây/file và mỗi nhóm đồng hồ xử lý. Có lease, recovery trạng thái và cache ASR; retry tạo run mới, chưa tiếp tục theo checkpoint từng stage. Hủy kiểm ở ranh giới lớn. | Bước 4: xử lý theo khối, checkpoint, hủy theo khối, đo 30/60/120 phút và không nhân đôi/mất lời ở biên. |
| G02 — Adapter đã huấn luyện | Runtime thực hiện `load(str(path))` với snapshot Qwen MLX gốc; chưa có cấu hình nạp adapter Colab. Writer đang yêu cầu `items` và từng `unit_id`; cần đối chiếu với hợp đồng paragraphs/nhiều ID của gói train. | Tích hợp adapter, thống nhất đầu ra và kiểm xuyên pipeline trước khi kết luận chất lượng train đã áp dụng vào web. |
| G03 — Rà danh tính người nói | Hồ sơ tham gia bị giới hạn 8. API đổi nhãn theo cả nhóm người nói, chưa có thao tác sửa danh tính từng lượt hoặc chia/gộp nhóm có lịch sử. | Mở rộng theo quy mô họp đã chọn và bổ sung luồng sửa nhầm từng lượt; kiểm bằng audio có nhãn thực tế. |

Thông tin bổ sung đã quan sát: trường Ghi chú cuộc họp được lưu nhưng metadata truyền vào bộ tạo biên bản hiện chỉ có tên/ngày/địa điểm. Không nên coi Ghi chú hay tài liệu ngoài audio đã là căn cứ đầu vào. Việc đưa chúng vào cần quy định nguồn và mục đích rõ; chưa tính đây là lỗi bắt buộc vì chưa chốt hợp đồng sử dụng Ghi chú.

## Những lỗi cũ không cộng lại vào tồn đọng

- Sai số làm tròn mili giây gây từ chối WAV đã có bản sửa trong mã và các test thời lượng lẻ đạt. Bốn lỗi còn lưu trong database là lịch sử ngày 27/10; không dùng chúng để kết luận mã hiện tại vẫn mắc lỗi này.
- Căn theo từng đoạn, giữ vùng đầu nguồn và khoảng chưa xác định đã có triển khai; không tiếp tục mô tả hệ thống như chỉ có một offset cho mọi bản ghi.
- Biên bản có cờ stale và phiên bản bất biến; kiểm tra hiện tại không tái hiện Word/ZIP lệch ở 7 phiên bản đã lưu.
- Phân trang phần hiển thị lời chép đã có. Tuy nhiên API vẫn tải toàn bộ segment và mỗi lần sửa sao chép phiên bản; chưa đo tải 1.000–5.000 lượt để kết luận mức ảnh hưởng.

## Thứ tự xử lý đề xuất

1. F01 và F04: bảo đảm chữ sửa tay có hiệu lực, đồng thời không giữ dữ kiện/căn cứ cũ như thể đã được nguồn mới xác nhận.
2. F02 và F03: phạm vi phiên, đề mục, vòng biểu quyết và trạng thái cuối; không đánh dấu `supported` khi mâu thuẫn.
3. F05 và F06: thống nhất giải tham chiếu căn cứ; lịch sử chỉ hiển thị phiên bản đã công bố.
4. F07 và O01: bảo vệ draft trên các form còn thiếu, trình bày đúng tình trạng worker/tác vụ.
5. G01–G03, rồi benchmark thực tế và tải lớn. Sửa T01–T03 để kiểm thử có thể tái lập khi chuyển máy hoặc đưa vào CI.

Chưa nghiệm thu cuộc họp dài thực tế, chưa đánh giá lại adapter trên tập kiểm độc lập trong pipeline web và chưa thực hiện kiểm thử xâm nhập/tải lớn. Lượt kiểm tra này không thay thế các bước đó.
