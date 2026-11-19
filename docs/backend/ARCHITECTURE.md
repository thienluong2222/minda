# Kiến trúc backend cho bản web MongoDB

**Vị trí mã hiện tại:** toàn bộ cây dưới đây đã được hợp nhất trực tiếp tại thư mục gốc dự án trên nhánh `main`.

Ngày: 17/10/2026. **Trạng thái: đã triển khai trên `codex/web-mongodb-upgrade`.**
Người dùng đã đồng ý lộ trình web user/admin, MongoDB và PDF/scan–OCR; app mobile
để làm sau. Yêu cầu bổ sung: code/file backend gọn, dễ tìm và sửa lỗi thủ công,
bảo vệ khả năng chạy của dự án hiện có.

Mục 1–6 giữ thiết kế đã được duyệt để đối chiếu. **Mục 7** mô tả mã đã triển
khai và những vị trí được gộp lại để tránh tạo lớp/file rỗng. Xem thêm
`QUICKSTART.md` và `VALIDATION_2026-10-17.md` trong thư mục này.

## 1. Ranh giới dự án

Một repository, một dự án Python, hai package có trách nhiệm rõ:

```text
project/
├── apps/
│   └── web/                         # React: user/admin, cùng frontend
├── packages/
│   └── api-client/                  # Types/client TS, tạo khi ổn định API
├── src/
│   ├── meeting_pipeline/            # Pipeline và CLI hiện có
│   └── meeting_backend/             # Ứng dụng mới
├── tests/
│   ├── unit/                        # Kiểm thử pipeline hiện có
│   ├── integration/                 # Kiểm thử hiện có
│   ├── model_smoke/                 # Phép thử model hiện có
│   └── backend/                     # Kiểm thử backend mới theo module
├── configs/
│   ├── default.yaml                 # Cấu hình pipeline hiện có
│   ├── minutes.yaml                 # Text runtime hiện có
│   └── backend.yaml                 # Cấu hình ứng dụng, không chứa secret
├── scripts/
│   └── backend/                     # Công cụ vận hành/import, nếu cần wrapper
├── docs/
│   └── backend/                     # Kiến trúc, map module, hướng dẫn tra lỗi
├── data/
│   └── app/                         # Dữ liệu ứng dụng mới, không theo dõi Git
└── pyproject.toml                   # Bổ sung package/entry point/dependency
```

`meeting_backend` gọi `meeting_pipeline` qua adapter. Các thuật toán ASR/VAD,
speaker/fusion/FCM và renderer dùng được qua đường import hiện tại. Các công cụ
CLI và bài kiểm thử cũ tiếp tục là baseline. Build config cần bổ sung package
mới; dependency ứng dụng không được kéo theo nâng phiên bản model/runtime tùy ý.

## 2. Cấu trúc package ứng dụng

```text
src/meeting_backend/
├── __init__.py
├── main.py                          # create_app, lifespan, đăng ký route
├── cli.py                           # doctor, import, inspect, backup/restore
├── core/
│   ├── settings.py                  # Cấu hình riêng, env có prefix
│   ├── errors.py                    # Mã lỗi và exception nghiệp vụ
│   ├── logging.py                   # Request/job/run/stage correlation
│   └── security.py                  # Password/session, primitive kiểm tra quyền
├── api/
│   ├── router.py                    # Đăng ký /api/v1
│   ├── dependencies.py              # Current user, service/repo injection
│   └── exception_handlers.py        # Exception → HTTP response thống nhất
├── modules/
│   ├── auth/                        # Đăng nhập, đăng xuất, session
│   ├── users/                       # Tài khoản, vai trò, quyền quản trị
│   ├── meetings/                    # Metadata, nguồn, ownership, lưu trữ
│   ├── transcripts/                 # Đoạn nói, sửa text, revision, evidence
│   ├── speakers/                    # Hồ sơ giọng, nhãn/danh tính trong cuộc họp
│   ├── templates/                   # Mẫu riêng/chung, trường, version, duyệt
│   ├── minutes/                     # Facts, rà soát, phiên bản, yêu cầu xuất
│   ├── jobs/                        # Queue state, lease, retry/cancel, tiến độ
│   └── system/                      # Model/preset, audit, backup và đánh giá
├── infrastructure/
│   ├── mongodb/
│   │   ├── client.py                # Kết nối/lifecycle
│   │   ├── indexes.py               # Index theo owner/status/uniqueness
│   │   ├── validators.py            # MongoDB schema validators
│   │   └── migrations/              # Script có version, chạy có kiểm soát
│   └── artifacts/
│       ├── store.py                 # Resolve file có quyền qua service
│       ├── versions.py              # Staging, kiểm tra, publish phiên bản
│       └── backup.py                # Backup/restore database + artifact refs
├── integrations/
│   ├── audio_pipeline.py            # DTO/config → MultiSourceFusionPipeline
│   ├── minutes_pipeline.py          # DTO/config → MinutesService
│   └── speaker_registry.py          # Ownership + dữ liệu phù hợp registry/encoder
├── processing/
│   └── documents/                   # Phần mới PDF/OCR/layout/tái dựng DOCX
└── worker/
    ├── main.py                      # Entry point tiến trình worker
    ├── runner.py                    # Claim, heartbeat, resource gate, retry
    └── handlers/
        ├── transcribe.py
        ├── enroll_voice.py
        ├── generate_minutes.py
        └── ingest_document.py
```

Chỉ tạo module/file khi có công việc thực tế. Tách các phần system hoặc service
lớn thành file có tên chức năng khi cần; tránh một file `admin.py`, `service.py`
hoặc `utils.py` tập trung mọi nghiệp vụ. User/admin dùng cùng service dữ liệu,
khác quyền và thao tác; không sao chép hai bộ logic cho hai giao diện.

### Bố trí bên trong một module

```text
modules/minutes/
├── router.py                        # HTTP endpoint
├── schemas.py                       # Request/response và DTO typed
├── service.py                       # Quyền, revision, giữ evidence, yêu cầu job
├── repository.py                    # Query/update MongoDB của chức năng này
└── fact_merge.py                     # Tách khi logic ghép fact cần file riêng
```

Luồng đồng bộ thông thường:

```text
router → service → repository → MongoDB
```

Luồng xử lý nặng:

```text
router → service → enqueue job
worker → handler → integration/processing → pipeline hiện có
worker → kiểm tra artifact mới → publish version → cập nhật MongoDB
```

Router nhận/kiểm tra request và gọi service. Service chứa quy tắc ứng dụng;
repository giữ truy vấn PyMongo. API chỉ truy cập model/cache status nhẹ;
heavy imports, enrollment và inference chạy trong worker để mở trang/health
không khởi tạo model. Hợp đồng giữa các lớp dùng schema rõ ràng, tránh payload
dict tùy ý và thay toàn bộ bản ghi chỉ vì người dùng sửa một trường.

## 3. Tái sử dụng mã hiện tại

| Chức năng | Mã hiện có | Điểm tích hợp mới |
| --- | --- | --- |
| Xử lý audio đa nguồn | [MultiSourceFusionPipeline](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/pipeline/multi_source_fusion.py:256) | integrations/audio_pipeline.py và worker |
| Biên bản/định dạng/xuất | [MinutesService](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/minutes/service.py:105) | integrations/minutes_pipeline.py, version publisher |
| Đăng ký và tải hồ sơ giọng | [SpeakerRegistry](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/application/speakers.py:80) | adapter với quyền sở hữu và namespace riêng |
| Web/CLI demo cũ | [create_app](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/web/app.py:450), [CLI serve](/Users/thien/Documents/School/Luận văn/src/meeting_pipeline/cli.py:250) | Giữ để đối chiếu hồi quy; app mới đăng ký route riêng |

`meeting_pipeline` không phụ thuộc ngược vào MongoDB, auth hoặc frontend mới.
Các sửa lỗi đã duyệt vẫn cần sửa tại `web/app.py` và `minutes/service.py` cùng
điểm liên quan. Đây là thay đổi chủ đích, có commit và test riêng, không chỉ
được che bằng wrapper. Điểm tiến độ/cancellation mới nếu cần sửa core sẽ dùng
tham số/hook tùy chọn, giữ hành vi mặc định và có kiểm thử tương thích.

## 4. Cấu hình và dữ liệu dễ tra cứu

- `configs/backend.yaml`: cấu hình không bí mật của backend. Credential đọc
  từ env có prefix riêng, tài liệu chỉ ghi mẫu biến; log không in secret.
- Cấu hình pipeline dùng bản sao/snapshot cho từng job. Không sửa cấu hình
  toàn cục trong khi một tác vụ đang chạy.
- Model cache/runtime hiện có được tham chiếu qua cấu hình; giữ các revision
  đã ghim. Env backend phát triển riêng; runtime MLX hiện có tách biệt.
- MongoDB/database dev và test có tên riêng; test/import không chọn database
  thật bằng mặc định. Các fixture MongoDB được tách khỏi fixtures pipeline cũ.

```text
data/app/
├── uploads/                         # File gốc mới, có meeting/source ID
├── pipeline/                        # Cấu trúc run/manifest hiện có dưới root riêng
├── document_versions/               # DOCX, facts/schema snapshot, preview, ZIP
├── logs/
│   ├── api.log
│   ├── worker.log
│   └── jobs/<job_id>/                # Log và snapshot phục vụ chẩn đoán
├── staging/<operation_id>/          # Chưa publish
└── backups/<backup_id>/             # DB + manifest các artifact tương ứng
```

DB lưu mapping `meeting_id ↔ job_id ↔ run_id ↔ version_id ↔ artifact path`.
Giữ cấu trúc đầu ra pipeline bên trong root riêng, không đổi hàng loạt tên
artifact mà core đang tạo. Snapshot JSON để đọc/đối chiếu; MongoDB và tham chiếu
phiên bản đang publish là nguồn dữ liệu chuẩn cho ứng dụng.

Sửa dữ liệu bằng giao diện hoặc CLI có validation/revision/audit. Nếu cần nhập
bản JSON đã chỉnh tay để phục hồi, có command import riêng với dry-run và báo
cáo khác biệt; sửa file snapshot không tự làm thay đổi database đang dùng.

## 5. Map tra lỗi cho người bảo trì

| Vấn đề | Bắt đầu ở đâu | Kiểm tra tiếp |
| --- | --- | --- |
| Đăng nhập/quyền | modules/auth, modules/users | api/dependencies, core/security, session/owner |
| Lưu transcript/tên người | modules/transcripts, modules/speakers | revision/evidence và stale trong modules/minutes |
| Facts/DOCX/preview lệch | modules/minutes, infrastructure/artifacts/versions | integrations/minutes_pipeline rồi core MinutesService |
| MongoDB/query/import | module repository, infrastructure/mongodb | indexes, validators, migration report |
| Job kẹt/lỗi/model bận | modules/jobs, worker/runner, log theo job_id | handler, adapter, run manifest, resource lease |
| ASR/VAD/speaker/fusion | integrations/audio_pipeline và log stage | module tương ứng trong meeting_pipeline |
| PDF/OCR/mẫu sai | modules/templates, processing/documents | file gốc, OCR/layout report, normalized DOCX |

Log có timestamp, level, error code, request/job/meeting/run ID, stage và
revision khi liên quan; giữ traceback phía backend để sửa thủ công. UI hiện
thông báo có ý nghĩa và mã tra cứu. Tài liệu hướng dẫn lỗi và map module sẽ
được cập nhật bằng đường dẫn/command thật khi triển khai.

## 6. Cách hạn chế ảnh hưởng tới dự án hiện tại

1. Dùng nhánh `codex/` và worktree riêng từ mốc đã duyệt. Dữ liệu/runtime/config
   dev có ranh giới rõ; không thử migration trên dữ liệu đang sử dụng.
2. Giữ path/import core và các bài test cũ. App mới có entry point riêng;
   điều chỉnh build config chỉ để đóng gói/khởi động package mới.
3. Sửa bốn lỗi nền thành commit riêng kèm bài kiểm thử đã tái hiện; sau đó
   thêm MongoDB/API/frontend theo từng bước. Tránh trộn sửa thuật toán và UI.
4. Kiểm thử backend mới có mục tiêu riêng ở `tests/backend/`; test trình duyệt
   ở frontend. Chạy baseline cũ và model smoke tại các điểm tích hợp có nguy cơ.
5. MongoDB là database của app mới. Mã SQLite/JSON cũ phục vụ tương thích,
   đối chiếu và importer; không tạo hai nguồn trạng thái ứng dụng mới.
6. Migration/import có dry-run, idempotency, thống kê/hash và backup; giữ
   nguồn gốc cho đến khi nghiệm thu. Artifact mới publish theo version.
7. Khi có hook/schema mới, kiểm tra cả người gọi cũ và mới. Chỉ đưa phiên bản
   vào sử dụng sau khi kiểm thử dữ liệu, quyền và output đã đạt.

Cấu trúc tách biệt giúp kiểm soát thay đổi. Các thay đổi tới shared service
vẫn có rủi ro hồi quy và phải được kiểm thử; không khẳng định tuyệt đối rằng
mọi sửa đổi sẽ không ảnh hưởng dự án cũ.

## 7. Bố trí thực tế sau triển khai

- `main.py`: lifespan, handlers, middleware, đăng ký route và static frontend.
  Chưa cần tách thêm api/router hoặc exception_handlers cho số lượng mã hiện tại.
- `cli.py`: serve, worker, doctor, prepare-ocr, import-run và import-legacy.
- `modules/auth`, `meetings`, `transcripts`, `jobs`, `system`: router/service và
  schemas/repository theo công việc thực tế. Các module nhỏ users, speakers,
  templates giữ các endpoint đơn giản ở router, không tạo service/repo rỗng.
- `infrastructure/mongodb/client.py`: lifecycle, collections, validator, index,
  migration `001_initial`, audit và ràng buộc database với data root.
  `repository.py` giữ CRUD/ownership dùng chung; meetings có repository riêng.
- `infrastructure/artifacts/store.py`: stream upload, checksum, resolve trong
  root và artifact ID; `media.py`: ffprobe; `backup.py`: backup/restore.
- `integrations/audio_pipeline.py`: audio và voice registry theo owner.
  `minutes_pipeline.py`: snapshot, staging, core Word, kiểm tra, publish.
  `legacy_import.py`: đọc SQLite chỉ đọc, dry-run, copy/hash và idempotency.
- `processing/documents/ingest.py` và `ocr.py`: Word/PDF/ảnh → DOCX chỉnh được,
  Tesseract vie+eng, bảng kẻ OpenCV, OCR report và bước duyệt.
- `worker/context.py`: lease/cancel gate và CAS publication; `runner.py`:
  claim/heartbeat/recovery/dispatch. Handler nằm tại adapter/processing tương ứng.
- `apps/web/src/features/`: meetings, templates/voices, admin; types/client
  được giữ tại `lib/` trước khi có nhu cầu tách package api-client cho mobile.

API không import Torch/MLX/Transformers khi khởi động. Worker chạy một job nặng
tại một thời điểm; `flock` theo root, lease MongoDB và checkpoint ngăn worker
cũ công bố sau khi mất quyền. Hủy đang inference có thể phải chờ công đoạn xong.

Phiên bản được tạo bất biến. MongoDB lưu active pointer; staging/file ứng viên
có thể còn lại nếu tiến trình bị kill, nhưng không được trở thành bản active.
Không mô tả đây là transaction phân tán filesystem/MongoDB.

Thư mục thực tế bổ sung `templates/<id>/<job>/`, `voices/<owner>/speakers/`,
`imported/<meeting>/`, `backups/<job>.zip`, `restores/<id>/`. Log API tại
`logs/api.log`, log worker theo job tại `logs/jobs/<job>/worker.log`.

Database phải có prefix `meeting_app_` và gắn đúng data root. Restore tạo
database/root mới, đổi đường dẫn sidecar sau kiểm checksum; không ghi đè DB cũ.
Lệnh import-run/import-legacy có dry-run, kiểm hash, khóa fingerprint và chạy
lại không trùng theo nội dung + owner. Tài khoản/queue SQLite cũ không được
phát lại; registry giọng được tạo từ mẫu qua giao diện mới.
