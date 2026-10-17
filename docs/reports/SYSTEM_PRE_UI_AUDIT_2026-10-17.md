# Kiểm tra hệ thống trước cập nhật giao diện — 17/10/2026

## 1. Mốc kiểm tra và kết luận

- Nhánh: `codex/llm-fcm-minutes`.
- Mã nguồn: `bdfcd8b6362d0ae20f3423bcc2c7c7c104c28503`.
- Phạm vi: môi trường, SQLite, kiểm thử tự động, model thật, các API phục vụ
  giao diện, thao tác chỉnh sửa và tính nhất quán của tài liệu xuất.
- Bằng chứng, script tái hiện và log:
  [pre_ui_audit_20261017_pukwivwo](/Users/thien/Documents/School/Luận văn/data/evaluations/pre_ui_audit_20261017_pukwivwo).

Pipeline và các model đang chạy được. Có **246 bài unit/integration đạt**,
**21 bài experiment đạt**. Tuy nhiên, bốn tình huống chỉnh sửa đã tái hiện lỗi
mà bộ kiểm thử hiện tại chưa phát hiện. Ba lỗi P1 liên quan đến mất dữ liệu
truy vết, xuất tài liệu không nhất quán và ghi dữ liệu khi yêu cầu bị từ chối.

**Nên sửa các lỗi P1 trước khi tích hợp giao diện mới với các thao tác lưu/sửa.**
Thiết kế giao diện có thể dùng mốc này làm baseline; chưa nên dùng kết quả
kiểm thử hiện có để kết luận toàn bộ luồng chỉnh sửa đã ổn định.

Đợt này chỉ kiểm tra và lưu báo cáo. Mã nguồn, cấu hình và giao diện chưa được sửa.
Các thao tác ghi được thử trên bản sao riêng, dùng database và job store riêng.
Không tải trọng số mới. Server web chính vẫn tắt; không có listener tại cổng 8000.
Đã đối chiếu SHA-256 trước/sau của 91 file gốc được chọn, tất cả giữ nguyên.
File có sẵn chưa được Git theo dõi
`docs/PLAN_FIX_SPEAKER_MULTI_SOURCE_HIGH_RISK_2026-10-03.md` được giữ nguyên.

## 2. Kết quả kiểm tra

| Hạng mục | Kết quả |
| --- | --- |
| Python | 3.11.14 |
| Doctor | 11 kiểm tra OK |
| SQLite chính | Mở chỉ đọc; `PRAGMA quick_check` trả `ok` |
| Dung lượng trống tại thời điểm đo | Khoảng 54,14 GiB |
| Unit + integration | 246 đạt, 3 cảnh báo, 43,01 giây |
| Experiment không cần model/dataset/e2e | 21 đạt, 1 deselected, 5,26 giây |
| HTTP trên app TestClient với dữ liệu sao chép | 9/9 endpoint đọc/tải trả 200 |
| JavaScript | `node --check` đạt |
| Ruff toàn repo | 45 lỗi ở 4 file, trùng baseline cũ |
| Ruff format | 5 file cần định dạng, trùng baseline cũ |
| Mypy toàn source | 4 lỗi `unused-ignore` ở 3 file; kiểm tra 96 source files |
| Kiểm tra dữ liệu gốc | 91/91 file có hash không đổi |

Các endpoint đọc/tải gồm trang chủ, health, trạng thái model, trang kết quả,
timeline, speakers, minutes, tải DOCX và tải ZIP. HTTP 200 chỉ chứng minh đường
đọc/tải hoạt động; các kiểm tra nội dung bên dưới mới phát hiện lỗi nhất quán.

Log: `pytest.log`, `pytest.xml`, `experiments.log`, `experiments.xml`,
`static_summary.json`, `ruff.log`, `format.log`, `mypy.log`, `doctor.log`,
`preflight.json`, `preservation_check.json` trong thư mục bằng chứng.

## 3. Bốn lỗi đã tái hiện

### P1 — Lưu biên bản dù không sửa vẫn mất bằng chứng và đổi trạng thái

**Tái hiện:** mở HTML trang kết quả trên bản sao của demo hiện có, lấy đúng
giá trị trong các textarea, dựng payload theo JavaScript hiện hành và bấm lưu
qua API `/minutes/facts`. Không thay đổi nội dung trường nào.

| Chỉ số | Trước | Sau |
| --- | --- | --- |
| Số trường | 37 | 37 |
| Tham chiếu bằng chứng | 50 | 0 |
| Trường được đánh dấu người dùng đã sửa | 0 | 37 |
| Trường từ `needs_review` thành `supported` | — | 11 |
| Kiểu của `attendees` | list | string |

Ba giá trị chuỗi rỗng khác cũng chuyển thành null. API trả 200. Việc đổi trạng
thái khiến giao diện có thể hiển thị đã có bằng chứng dù các tham chiếu đã mất.

**Nguyên nhân:** [demo.js:238](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/web/static/demo.js:238)
gửi lại tất cả trường dưới dạng text và tự suy ra `supported` từ việc có chữ;
payload không chứa evidence, confidence hoặc lý do rà soát.
[service.py:480](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/minutes/service.py:480)
dựng lại fact từ payload thiếu thông tin và đánh dấu toàn bộ là người dùng sửa.

**Hướng xử lý:** API nhận phần thay đổi theo `field_id`, ghép với fact đã lưu,
bảo toàn kiểu dữ liệu và thông tin truy vết. Quy định riêng cách đánh dấu người
dùng sửa/xác nhận; không dùng “có nội dung” để suy ra có bằng chứng. Lưu không
thay đổi phải giữ nguyên dữ liệu nghiệp vụ.

### P1 — Sửa transcript ở chế độ không dùng LLM bỏ qua bước định dạng

**Tái hiện:** tạo biên bản thực sự bằng `MinutesService`, chọn `hd05_2026`,
`use_model=False`; sau đó thêm dấu chấm vào đoạn transcript đầu tiên qua
`/edit-transcript`.

- API trả 200; cấu hình vẫn ghi `hd05_2026`.
- DOCX bị render lại từ mẫu normalized, mất style `Minutes Body`.
- Chiều rộng trang trở về 215,9 mm của mẫu thay vì khoảng 210 mm.
- Hash DOCX tải trực tiếp không khớp manifest.
- DOCX trong ZIP khác DOCX tải trực tiếp; preview/báo cáo định dạng không được
  tạo lại theo nội dung mới.

**Nguyên nhân:** [app.py:838](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/web/app.py:838)
có nhánh tự trích xuất và gọi renderer trực tiếp, bỏ qua service định dạng,
cập nhật manifest, đóng ZIP và tạo preview.

**Hướng xử lý:** đưa các đường render lại về một service chung, cập nhật đồng bộ
facts → DOCX → định dạng → preview → manifest → ZIP, có khóa và rollback cho
toàn bộ thao tác. Cần kiểm tra cả hai thể thức và cả hai chế độ có/không LLM.

### P1 — Sửa schema khi đang bận vẫn ghi một phần dữ liệu

**Tái hiện:** trên bản sao riêng, giữ `GENERATION_LOCK`, gửi lại danh sách field
hợp lệ qua `/template/schema`, sau đó giải phóng khóa.

- API trả 400 với thông báo đang tạo một biên bản khác.
- Schema revision vẫn tăng từ 1 lên 2; `proposed_by` thành `user_manual`.
- `facts.json` đã đổi nhưng DOCX chưa đổi.

**Nguyên nhân:** [service.py:574](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/minutes/service.py:574)
ghi audit/schema/facts trước khi gọi service render. Khóa chỉ được lấy ở bước
render, sau các lần ghi. Rollback của bước render cũng không bao phủ trạng thái
trước khi schema/facts bị ghi đè.

**Hướng xử lý:** lấy khóa trước lần ghi đầu tiên; bảo vệ và rollback toàn bộ
schema, audit, facts và exports trong cùng thao tác. Chuẩn hóa mã lỗi bận giữa
các endpoint; yêu cầu bị từ chối vì bận phải không thay đổi dữ liệu.

### P2 — Đổi tên người nói chưa cập nhật hoặc đánh dấu biên bản lỗi thời

**Tái hiện:** đổi nhãn `Minh` thành `Minh Audit` bằng `/rename-speaker` trên bản
sao demo có biên bản dùng LLM.

- API trả 200; timeline chứa tên mới.
- Facts và DOCX không đổi; DOCX vẫn có `Minh`, không có `Minh Audit`.
- Các trường `chairperson_name`, `discussion_summary`, `decisions` vẫn có tên cũ.
- Không có cờ stale trong model report, nên trang kết quả không báo cần tạo lại.

**Nguyên nhân:** [app.py:604](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/web/app.py:604)
chỉ cập nhật timeline, lịch sử đổi tên và exports transcript.

**Hướng xử lý:** theo dõi revision của transcript và danh tính; đánh dấu các
artifact phụ thuộc cần cập nhật. Hiển thị trạng thái đó trước khi tải tài liệu.
Không thay tên hàng loạt bằng phép thay chuỗi trong nội dung biên bản.

Bằng chứng của cả bốn lỗi: `api_probes.py`, `api_probes.json` và các run sao chép
trong `probes/`. Đây là kiểm tra API/HTML, chưa phải kiểm thử click bằng trình duyệt.

## 4. Model thật và hồi quy ASR

### Qwen, E5 và Fuzzy C-Means

- Qwen: `mlx-community/Qwen3-4B-Instruct-2507-4bit`, revision
  `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`.
- E5: `intfloat/multilingual-e5-small`, revision
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- Qwen thực sự suy luận, không dùng response cache ở lượt đầu: trả JSON hợp lệ,
  64 prompt tokens, 6 output tokens, khoảng 6,04 giây; peak MLX khoảng 2,47 GB.
  Đây là phép thử JSON ngắn, không đại diện cho thời gian tạo biên bản.
- Lượt đầu đọc embedding cũ từ cache và FCM tạo hai cụm.
- Đã chạy thêm sáu câu mới để kiểm tra E5 thực sự tính embedding: không cache
  hit; khoảng 2,90 giây; shape `6 × 384`, hữu hạn, L2 norm xấp xỉ 1.
- FCM trên sáu câu mới thử hai cụm: silhouette 0,1572, stability 0,2593;
  bị từ chối theo tiêu chí hiện tại và trả về một cụm dự phòng.

Điều này xác nhận runtime và cơ chế chọn/fallback hoạt động. Chưa chứng minh
chất lượng chia chủ đề hoặc chất lượng biên tập. Bộ sáu câu quá nhỏ và chưa có
nhãn đối chiếu; việc fallback cần được giao diện trình bày rõ cho người dùng.
Lượt thứ hai dùng lại response Qwen của lượt đầu; kết quả suy luận Qwen mới nằm
trong `warm_runtime_smoke.json`, embedding mới nằm trong `runtime_smoke.json`.

### Pipeline audio thực tế

Chạy `MultiSourceFusionPipeline`, cùng backend với demo, trên hai câu VIVOS
có sẵn, ghép thành 11,1875 giây với khoảng lặng. Dùng pyannote, ECAPA và
PhoWhisper-medium từ cache; một nguồn, không enrollment, không overlap.

- Segmentation suy luận một lần; tạo hai hàng timeline có transcript.
- Giữ đủ “trở nên thụ động” và “cũng khiến cho họ dè dặt”.
- WER/CER đều 0 trên đúng 10 từ tham chiếu này; S/D/I đều 0.
- Có `word_boundary_audit.json`, source hypotheses, speaker decisions và ZIP.
- Tổng thời gian khoảng 30,77 giây, gồm tải model và chạy pipeline.

Lỗi mất từ ở biên đã sửa trước đây không tái xuất hiện trên mẫu hồi quy này.
Không suy rộng kết quả sang cuộc họp dài, nhiều mic, đổi người hoặc nói chồng.
Bằng chứng: `audio_smoke.py`, `audio_smoke.json`, `audio_smoke.log`.

## 5. Tài liệu hiện có và giới hạn của đợt kiểm tra

Bản demo định dạng ngày 15/10 đang có 32 hàng timeline, 26 hàng có chữ; khoảng
thời gian hợp lệ. DOCX gốc có CRC/XML hợp lệ, khổ A4, style định dạng, hash khớp
manifest và bản trong ZIP. Cả ba trang preview tồn tại. Có 37 facts và 50 tham
chiếu bằng chứng. Bản smoke ASR đã lưu ngày 15/10 cũng có hai hàng hợp lệ.

Các kiểm tra trên là kiểm tra cấu trúc và tính nhất quán, không phải đối chiếu
thủ công từng trang hoặc chứng nhận tuân thủ thể thức. Xem `existing_run_checks.json`.

Chưa đánh giá lại VAD/diarization trên cuộc họp đa nguồn dài, false overlap,
chất lượng sửa ASR bằng LLM, đặt tên chủ đề hoặc độ đúng của toàn bộ biên bản.
Các giới hạn này vẫn cần theo dõi từ các báo cáo trước. PDF/ảnh scan, OCR và
fine-tuning không thuộc chức năng được nghiệm thu trong đợt này.

## 6. Mốc nghiệm thu đề xuất trước khi nối giao diện mới

1. Lưu không thay đổi không mất evidence, kiểu dữ liệu hoặc trạng thái rà soát;
   sửa một trường chỉ cập nhật trường đó cùng thông tin truy vết liên quan.
2. Sau mỗi thao tác chỉnh sửa thành công, DOCX trực tiếp, DOCX trong ZIP,
   manifest và preview phải thuộc cùng một phiên bản và giữ thể thức đã chọn.
3. Yêu cầu bị từ chối vì bận không ghi dữ liệu; lỗi giữa chừng khôi phục được cả
   schema/facts/exports. Các endpoint thống nhất cách báo bận.
4. Đổi transcript hoặc người nói làm hiện rõ biên bản cần cập nhật; không để
   tài liệu cũ được hiểu là đã phản ánh thay đổi mới.
5. Giao diện khôi phục đầy đủ cấu hình đã lưu, gồm chế độ biên bản, thể thức,
   metadata và vùng nội dung `content_field_id`; giữ riêng trạng thái chưa xác
   định người nói và nói chồng; hiển thị trường chưa có căn cứ/cụm fallback.
6. Bổ sung kiểm thử tích hợp theo bốn tình huống đã tái hiện, rồi kiểm thử hành
   trình trên trình duyệt khi giao diện mới sẵn sàng. Dọn baseline lint/type
   checking riêng để dễ quy lỗi phát sinh trong đợt cập nhật.

Thứ tự ưu tiên: sửa hợp đồng lưu facts → gom luồng xuất DOCX → khóa/rollback
schema → revision/stale → tích hợp và kiểm thử giao diện mới.
