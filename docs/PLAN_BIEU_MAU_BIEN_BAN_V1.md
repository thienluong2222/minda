# Kế hoạch triển khai luồng biểu mẫu và biên bản v1.0

**Ngày:** 03/10/2026  
**Tài liệu giao việc chính cho agent biểu mẫu.** Repository mã: `/Users/thien/Documents/School/Luận văn`. Tài liệu nghiên cứu và kế hoạch lịch sử: [PLAN_OPTIMIZE_PIPELINE_AND_MEETING_MINUTES.md](/Users/thien/Documents/ChatGPT/Luận%20văn/PLAN_OPTIMIZE_PIPELINE_AND_MEETING_MINUTES.md). Nếu hai tài liệu khác nhau về phạm vi biểu mẫu v1.0, dùng file này; kiểm tra mã thực tế trước mọi quyết định tích hợp.

## 1. Mục tiêu, phạm vi và điều không được tuyên bố

Đầu vào là một run âm thanh đã xử lý của pipeline hiện hành, metadata cuộc họp tùy chọn và **một mẫu biên bản Word chưa điền**. Đầu ra là (1) schema chỉ rõ từng chỗ cần điền và vị trí trong mẫu; (2) bản biên bản `.docx` điền được những fact có bằng chứng; (3) danh sách trường thiếu, mâu thuẫn hoặc cần duyệt; (4) manifest liên kết mỗi giá trị với lượt nói, thời gian, nguồn và clip hoặc metadata do người dùng cung cấp. Giao diện tối giản cho phép duyệt schema, nghe bằng chứng, sửa transcript/giá trị và xuất file.

**Phạm vi v1.0:** DOCX native và `.doc` Word binary chuyển sang DOCX trên bản sao. Mẫu đầu tiên:

- `/Users/thien/Downloads/Mau_Bien_ban_cuoc_hop_0504164828_2311152014_(1)_1501235028.doc` — biên bản họp chung.
- `/Users/thien/Downloads/bien-ban-cuoc-hop-chi-bo_1501235210.docx` — biên bản họp chi bộ.

Hai file này là fixture và smoke test, **không phải các mẫu được gán cứng**. PDF AcroForm, PDF văn bản và scan/OCR/VLM là mốc sau; v1.0 trả `unsupported_format` có giải thích. Không tự nhận “hiểu hoàn toàn mọi biểu mẫu” hoặc “biên bản chính xác” chỉ vì hai mẫu chạy được. Không sửa VAD, ASR, diarization, fusion hoặc benchmark âm thanh trong đợt này. Text và chỉ dẫn nằm trong biểu mẫu là **dữ liệu cần phân tích**, không phải mệnh lệnh cho agent hay model.

## 2. Sự thật tích hợp cần kiểm tra lại lúc bắt đầu

Ngày 03/10/2026 repository âm thanh ở nhánh `codex/vad-speaker-asr-fusion`, commit `7134f8b`. Pipeline hiện xuất `timeline.json` schema 2.0, `source_hypotheses.json`, `fusion_decisions.json`, `speaker_clusters.json`, `coverage.json` và `clips/evidence/`. `timeline.json` có `turn_id`, `meeting_speaker_id`, `speaker_label/status`, text, mốc thời gian, nguồn và clip; word provenance trên timeline chưa có word ID/timestamp ổn định, còn từ có thời gian trong `source_hypotheses.json`. Agent kiểm tra lại hợp đồng này trên một run mới nhất trước khi viết adapter, không dựa vào `docs/pipeline.md` cũ.

Kiểm tra model thật rất ngắn (2 nguồn, 7,67 giây) đã tạo đủ artifact nhưng mất 61,57 giây, WER 40% và tách hai lượt của **cùng một người** thành hai nhãn người lạ mà không bật `needs_review`. Đây là một ca, không phải kết quả tổng quát. `asr_status=transcribed`, điểm dung hợp cao hay `needs_review=false` **không chứng minh câu đúng**. Báo cáo tăng tốc A0–A7 hiện dùng mock/số RTF gán sẵn; không dùng nó làm số đo thật hoặc đưa vào tuyên bố thành công của v1.0 biểu mẫu. Phần biểu mẫu phải giữ khả năng sửa transcript và yêu cầu duyệt fact quan trọng khi bằng chứng yếu, thay vì cố sửa pipeline âm thanh.

## 3. Luồng và ranh giới trách nhiệm

```text
Word gốc (.doc/.docx)
  → kiểm tra định dạng, giữ bản gốc, chuyển .doc trên bản sao
  → DocGraph + candidate anchors (parser xác định vị trí thực)
  → M0: schema theo luật/bản sửa tay
  → M1: Qwen3 đề xuất ý nghĩa trường từ DocGraph, JSON constrained
  → validator + giao diện duyệt + schema có phiên bản/cache

Timeline schema 2.0 + source hypotheses + clip + metadata tùy chọn
  → adapter bằng chứng theo turn/source/interval
  → retrieval theo từng trường đã duyệt
  → M2: trích xuất fact theo quy tắc/câu nguồn
  → M3: model tóm tắt mục tự do trên evidence đã truy hồi (nếu qua phép đo)
  → fact validator: supported / unknown / conflicting / needs_review
  → điền vào bản sao Word + kiểm tra bố cục
  → completed.docx + schema/fact/evidence manifest + giao diện rà soát
```

Parser không gọi model âm thanh; schema mapper không nhận transcript; fact extractor không được tự sửa Word; renderer chỉ nhận schema/fact đã qua validator. Phân tích mẫu có thể chạy song song với audio. Sửa transcript, schema hoặc fact chỉ chạy lại phần phụ thuộc phía sau, **không chạy lại ASR**.

## 4. Hợp đồng dữ liệu bắt buộc

Mọi artifact có `schema_version`, `run_id`, hash file gốc/bản chuẩn hóa khi áp dụng, revision parser/model/prompt/config và thời gian tạo. Dùng kiểu dữ liệu Pydantic hoặc tương đương; tên lớp có thể đổi nếu repository đã có lớp phù hợp.

| Thành phần | Trường tối thiểu | Bất biến |
|---|---|---|
| `DocGraph` | `block_id`, thứ tự, loại block, text gốc, `section_path`, paragraph/table/cell/run path, style, candidate anchors | Có thể lần từ ID về đúng vị trí trong DOCX; không mất nhãn trong header/footer/bảng. |
| `CandidateAnchor` | `anchor_id`, block/path, start/end ở mức run hoặc content control, nhãn kề, vùng trống/nhóm lặp/chữ ký | Anchor do parser tạo; model không được phát minh ID. Hai chỗ trống trên cùng một dòng là hai ID. |
| `TemplateField` | `field_id`, `anchor_id`, nhãn gốc, semantic type, section, điều kiện, cardinality, nhóm lặp, `allowed_source_types`, `mapper_status`, lý do review | Mỗi candidate anchor ở đúng một field hoặc danh sách chưa map; không im lặng bỏ qua. |
| `EvidenceRef` | `run_id`, `turn_id`, `source_id`, `[start_sec,end_sec)`, clip path, source kind, optional word IDs/timestamps | Mọi tham chiếu tồn tại, nằm trong coverage; không tự tạo word ID/timestamp giả. |
| `MeetingFact` | field ID, value hoặc null, `supported/unknown/conflicting/needs_review`, evidence refs, lý do, revision transcript | Giá trị khẳng định quan trọng phải có evidence hoặc metadata được phép; mâu thuẫn không được render như sự thật. |

`allowed_source_types` gồm `transcript`, `meeting_metadata`, `computed_from_supported`, `user_review`. `custom` cho nhãn chưa biết; không ép mọi mẫu vào một danh sách loại trường cố định. Nếu cần ID từ, tạo ID dẫn xuất có phiên bản từ `(run_id, turn_id, source_id, word_index)` **chỉ khi** ánh xạ được sang từ/timestamp thực; nếu không, lưu bằng chứng cấp turn/source/clip và nêu rõ độ hạt. Model confidence chưa hiệu chuẩn để `null`, không hiển thị như xác suất đúng.

## 5. Gói công việc theo thứ tự

### F0 — Chốt baseline, dữ liệu chuẩn và phép đo

1. Kiểm tra repo, Git status, API web/CLI, cấu trúc run thực, các thay đổi đang có của agent khác. Ghi SHA/config/model revision của ca demo được dùng. Không làm lại audio.
2. Chốt bộ fixture: hai mẫu Word gốc; một run audio có sẵn hoặc cuộc họp FPT.AI đã tạo; transcript người sửa tay và bảng fact chuẩn cho ca đó. Mẫu chi bộ **không có cuộc họp tương ứng**: các trường không có chứng cứ phải để trống/review, không dựng một cuộc họp giả để lấp chỗ.
3. Tạo nhãn tay cho anchor/loại trường/section của hai mẫu và ít nhất **một họ mẫu Word chưa từng thấy** có quyền sử dụng; cùng họ mẫu hoặc bản sửa của nó không được nằm cả dev và test. Nếu chưa có mẫu mới hoặc biên bản chuẩn, vẫn hoàn thành smoke chức năng nhưng ghi `generalization_not_evaluated` thay vì công bố precision/recall tổng quát.
4. Định nghĩa `RunMetrics` cho riêng minutes: convert, parse, schema model cold/warm, validate/review, retrieval, extraction, render, tổng wall, peak RSS nếu đo được. Ghi số **đo bằng `perf_counter` lúc chạy thật** và số lượng field/turn/model call; không điền số dự kiến vào cột kết quả.

**Gate F0:** có manifest tái lập ca test, nhãn tay và danh sách dữ liệu thiếu; baseline M0 chạy được trước khi chọn M1.

### F1 — Đọc Word và giữ anchor thật

Kiểm MIME/chữ ký, kích thước, số trang và khả năng chỉnh sửa. Giữ bản gốc bất biến/SHA-256. `.doc` binary chuyển bằng LibreOffice headless trong thư mục tạm cô lập, ghi hash bản DOCX chuyển đổi và lỗi nếu chuyển thất bại; không đổi phần mở rộng để giả chuyển. Dùng `python-docx` và khi cần OOXML/`lxml` để giữ thứ tự paragraph/table/cell/header/footer/content control/runs. Dò chỗ trống dạng dòng chấm, ô trống, placeholder, vùng lặp và chữ ký; phân biệt nhãn/giải thích in sẵn với giá trị cần điền. Không thay chuỗi trực tiếp trên toàn XML làm mất style. Ghi `doc_graph.json`, candidate anchors và danh sách chưa hiểu.

**Gate F1:** cả hai mẫu qua parser và bản `.doc` chuyển đổi mở được; mỗi chỗ trống có anchor riêng hoặc cảnh báo cụ thể; không có anchor ngoài tài liệu. Render hai file trước/sau chuyển sang ảnh để rà bố cục, không chỉ kiểm tra DOCX có mở được.

### F2 — Hiểu mẫu bằng baseline và model, rồi duyệt

M0 là parser + luật + schema có thể sửa thủ công. M1 giữ nguyên anchors của M0 và dùng [`Qwen3-4B-Instruct-2507`](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) chạy **cục bộ** qua `llama.cpp`/runtime tương thích để ánh xạ ý nghĩa. Chỉ gửi `DocGraph` rút gọn gồm ID, nhãn, section và quan hệ bố cục; không gửi audio, transcript, tên người tham gia hoặc mẫu ra dịch vụ ngoài. Dùng JSON grammar/schema, giới hạn output và log model/prompt revision; không fine-tune khi chỉ có hai mẫu. Model trả `anchor_id` đã có, loại trường, điều kiện như “nếu có”, cardinality, nguồn được phép và lý do chưa chắc; model **không** trả giá trị cuộc họp.

Validator chặn JSON lỗi, anchor lạ, field trùng, candidate anchor bị bỏ quên, nhóm lặp/điều kiện không hợp lệ. Trường mơ hồ thành `needs_review`, không tự approve dựa vào “confidence” model. Giao diện cho người dùng sửa schema một lần và lưu audit; cache theo hash mẫu gốc + hash bản chuyển đổi + parser/schema/model/prompt revision + revision bản duyệt. Nếu model lỗi/không có weights, M0 và duyệt tay vẫn hoạt động, còn trạng thái M1 phải là `not_run/failed`, không báo M1 đã đạt.

**Gate F2:** hai mẫu cho schema có vị trí đúng và file `schema_proposal.json`, `schema.json`, `schema_review.json`; model thật được chạy trên ít nhất hai mẫu và kết quả được so với nhãn tay. Trường chưa map phải hiện công khai. Nếu chưa có model thật, không đánh dấu F2 hoàn tất dù unit tests mock qua.

### F3 — Tìm fact có chứng cứ và xử lý thiếu/mâu thuẫn

Adapter đọc artifact audio schema 2.0 và kiểm path/interval/clip. Tạo index turn; dùng BM25/tìm từ theo field làm baseline, chỉ thử embedding đa ngữ nếu nó cải thiện recall trên nhãn. Với trường ngày, tên, số, địa điểm: quy tắc + chuẩn hóa; mục tự do: M2 trích câu/bullet từ lượt liên quan, M3 thử model cục bộ sinh JSON **chỉ từ evidence đã truy hồi**. Chỉ ghi quyết định khi có sự chốt rõ, không biến đề xuất thành quyết định. Action item cần nhiệm vụ; owner/due chỉ khi được nói rõ hoặc metadata được phép. Số/tỷ lệ phiếu chỉ tính khi số đầu vào có chứng cứ, công thức và mẫu số phù hợp. Tên in trong mẫu không chứng minh người đó tham dự hoặc phát biểu.

Run thử hai nhánh trên **cùng schema, transcript, metadata**: (a) transcript do người kiểm sửa để đo riêng luồng minutes; (b) transcript ASR để đo lỗi end-to-end. Nếu chênh lệch, phân loại lỗi upstream vs retrieval vs extraction vs renderer. `asr_status=transcribed` không phải xác nhận; lượt ngắn, thiếu confidence thật, retry/timestamp warning, speaker không chắc hoặc evidence clip không khớp phải yêu cầu duyệt fact quan trọng. Cho sửa transcript trong UI với audit, rồi chạy lại F3–F5 mà không chạy audio.

**Gate F3:** mỗi fact có trạng thái và lý do, evidence tồn tại/đọc được; thiếu hoặc mâu thuẫn không biến thành câu khẳng định. Unit tests mock chỉ kiểm logic; kết luận chất lượng dùng ca có audio/transcript/fact chuẩn hoặc ghi rõ chưa thể đo.

### F4 — Điền bản sao Word và giao diện tối giản

Điền native anchor đã duyệt trên **bản sao**, giữ bảng/font/heading/thứ tự mục. Với `.doc` xuất `completed.docx`, giữ `.doc` gốc cho tải lại. Kiểm overflow, ngắt trang, bảng lặp và chữ ký; không tự thêm phụ lục nếu mẫu không cho phép. Manifest liên kết field → value/status → source kind → evidence turn/clip/time → anchor → model/config revision. Giao diện gồm tải mẫu, trạng thái xử lý, xem schema và chỗ cần duyệt, bản xem trước biên bản, timeline/bằng chứng có nút nghe và nút sửa. Không dùng icon/emoji như thành phần thông tin chính. Không có template vẫn chạy timeline cũ.

**Gate F4:** hai mẫu Word xuất file mở được; ảnh render trước/sau đã được người làm kiểm; không tràn/chồng trên ca thử; click từ giá trị đến clip hoặc metadata được phép; sửa schema/value không gọi ASR; run cũ vẫn mở được.

### F5 — Đánh giá thật, sửa tài liệu và bàn giao

So M0/M1 trên **cùng bộ mẫu** với anchor precision/recall, field precision/recall/F1, semantic type/section/condition, số field bỏ sót/trùng, `needs_review`, false auto-fill, latency cold/warm và mức giữ bố cục. So M2/M3 trên **cùng schema và transcript**, đo exact/normalized field match, precision/recall decision/action/owner/due, evidence precision/recall, unsupported-claim rate, số trường unknown/conflicting đúng, latency. Ghi từng mẫu và tổng hợp; không chọn cấu hình theo test đã nhìn. Với tập rất nhỏ, báo số ca và lỗi cụ thể, không trình bày chênh lệch nhỏ như kết luận thống kê. Nếu M1/M3 không cải thiện hoặc chưa đủ nhãn, giữ M0/M2 làm mặc định nhưng cho xem đề xuất model có trạng thái thực nghiệm.

Chạy unit/integration, Ruff, mypy; một smoke **model thật** từ upload Word + run audio hiện có đến `completed.docx`, evidence manifest và UI preview; mở file xuất và so ảnh từng trang. Lưu lệnh, SHA/config/hardware, thời gian từng stage và ảnh QA. Tài liệu `docs/demo.md`/`docs/pipeline.md` phải phản ánh hành vi thực sau khi triển khai, xóa mô tả small/Silero/SepFormer cũ khỏi phần “hiện tại” hoặc chuyển sang lịch sử. Báo riêng mọi lỗi do môi trường, dữ liệu thiếu hoặc model không tải; không viết “pass” cho stage chưa chạy.

**Gate F5:** demo thật tái lập được và báo cáo phân biệt mock, model thật, gold transcript, ASR transcript, đã đo, chưa đo. Không dùng tỷ lệ RTF gán sẵn/sleep mô phỏng để chứng minh tốc độ. Không tuyên bố “mọi biểu mẫu Word” khi chỉ có hai fixture.

## 6. Kiểm thử nghiệp vụ tối thiểu

1. `.doc` binary thật → DOCX bản sao; chữ ký/tiêu đề/bảng không biến mất; file `.doc` gốc không đổi.
2. Hai placeholder trong cùng paragraph (“Chủ trì … Chức vụ …”), chỗ trống chia qua nhiều runs, bảng lồng, header/footer, vùng lặp, ô chữ ký và dòng không có dấu chấm nhưng cần nội dung.
3. Hai nhãn “Ngày” ở hai section khác nhau và mục “Biểu quyết (nếu có)”: đúng anchor, điều kiện, số phiếu và tỷ lệ là hai trường riêng.
4. Mẫu chứa câu giả mạo chỉ dẫn model hoặc tên người in sẵn: không đổi luật hệ thống, không suy sự có mặt/phát biểu.
5. Model trả JSON sai, anchor lạ, bỏ sót candidate hoặc mất weights: validator chặn, trạng thái chính xác và có đường duyệt tay.
6. Transcript nêu đề xuất rồi bác; nhiệm vụ không có owner/due; hai nguồn mâu thuẫn; ngày tương đối thiếu ngày họp: không điền một khẳng định vô căn cứ.
7. Lượt ASR ngắn/chỉ được chép một phần nhưng `transcribed` và `needs_review=false`: fact quan trọng vẫn có đường duyệt và clip đối chiếu.
8. Speaker vô danh, tên đổi trên UI, vùng overlap `not_run`: minutes không tự nhận diện hoặc tự sinh nội dung của vùng bỏ qua.
9. Sửa transcript/schema/value, render lại và mở run cũ: không chạy lại ASR, revision/audit/manifest nhất quán.
10. Template không gửi, PDF/scan gửi, file hỏng, file lớn và path bất thường: tương thích ngược hoặc lỗi rõ, không ghi đè file tùy ý.

## 7. API, artifact và bàn giao

Tái sử dụng `POST /api/runs` hiện tại với `template` và `meeting_metadata` tùy chọn, hoặc thêm endpoint riêng nếu upload bất đồng bộ phù hợp hơn; giữ request cũ hoạt động. Endpoint đọc schema đề xuất/đã duyệt, duyệt schema, sửa transcript/fact, xem manifest và tải `completed.docx`; mọi sửa đổi có revision, kiểm quyền đường dẫn và audit. Không trả tên file người dùng như đường dẫn hệ thống.

```text
data/meetings/<meeting_id>/runs/<run_id>/
  timeline.json  source_hypotheses.json  fusion_decisions.json  clips/evidence/
  template/original.<doc|docx>  template/normalized.docx
  template/doc_graph.json  template/schema_proposal.json
  template/schema.json  template/schema_review.json
  minutes/facts.json  minutes/review.json  minutes/manifest.json
  minutes/timings.json  exports/completed.docx  exports/result.zip
```

`normalized.docx` chỉ bắt buộc với `.doc`; DOCX native có thể dùng bản sao và ghi rõ trong manifest. ZIP gồm Word kết quả và manifest/evidence cần đối chiếu, không nhân bản audio dài vô ích. Bàn giao: mã và test; file mô tả schema/API; báo cáo M0–M3 với số đo thật, nhãn và giới hạn; ảnh QA trước/sau; lệnh chạy demo; một ca điền mẫu chung từ audio thật có evidence; một ca mẫu chi bộ cho thấy trường thiếu ở `unknown/needs_review`. **Chỉ đánh dấu hoàn thành phần đã chạy, đã xem và có artifact.**

## 8. Nghiên cứu làm căn cứ, không thay thế phép đo dự án

- [FUNSD](https://arxiv.org/abs/1905.13538): hiểu form gồm nhận diện nội dung và liên kết vùng nhãn–giá trị; không chứng minh chất lượng trên Word Việt.
- [DocLLM](https://aclanthology.org/2024.acl-long.463/): ngữ nghĩa và bố cục đều quan trọng; ủng hộ việc đưa cấu trúc/quan hệ vào mapper, không chứng minh Qwen3 thắng trên hai mẫu của dự án.
- [Qwen3-4B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507): ứng viên local đa ngữ 4B; phải đo schema mapping và latency trên máy thực.
- [QMSum](https://aclanthology.org/2021.naacl-main.472/), [MeetingBank](https://aclanthology.org/2023.acl-long.906/) và [ExplainMeetSum](https://aclanthology.org/2023.acl-long.731/): căn cứ cho truy hồi đoạn họp theo mục và truy vết bằng chứng; không phải benchmark điền biên bản Word tiếng Việt.
