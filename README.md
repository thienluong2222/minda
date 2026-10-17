# Meeting Pipeline

Pipeline offline nhận diện người nói và chép lời cuộc họp tiếng Việt từ nhiều điện thoại,
triển khai theo `PIPELINE_IMPLEMENTATION_SPEC.md`.

## Trạng thái

### Prototype web user/admin + MongoDB

Bản web mới có đăng nhập/phân quyền, worker riêng, quản lý cuộc họp/mẫu/giọng,
rà soát transcript và biên bản, preview DOCX, lịch sử, quản trị và backup/restore.
Hỗ trợ DOC/DOCX, PDF văn bản, PDF scan và ảnh; PDF/ảnh qua bước duyệt trước khi dùng.

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
.venv-backend/bin/python scripts/backend/run_local.py
```

Mở `http://127.0.0.1:8010` và tạo tài khoản admin lần đầu. Xem
[cài đặt, sử dụng và nhập dữ liệu cũ](docs/backend/QUICKSTART.md),
[bố trí backend](docs/backend/ARCHITECTURE.md) và
[phạm vi kiểm thử](docs/backend/VALIDATION_2026-10-17.md).
Demo cũ ở cổng 8000 có entry point độc lập bên dưới.
 
CLI và web demo dùng backend dung hợp transcript đa nguồn và chạy end-to-end bằng model thật.
 
### VIVOS Synthetic Multi-Device Pipeline
Hệ thống xử lý cuộc họp tiếng Việt đa nguồn dựa hoàn toàn trên corpus âm thanh VIVOS theo đặc tả `docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md`.
- **Milestone 0 (Preflight & Inventory)**: ĐẠT. Kiểm kê môi trường, ffmpeg, VIVOS corpus (65 speakers, 12,420 files, 15.4h audio), model cache ngoại tuyến (PhoWhisper-small, ECAPA-TDNN, Silero VAD). Báo cáo tại `reports/preflight.md`.
- **Milestone 1 (Foundations, Configs & Contracts)**: ĐẠT. Thiết lập cây thư mục phân tầng, Pydantic contracts (`domain/contracts.py`) cho Utterance, Recipe, Segment, Hypothesis, Timeline, Provenance, cùng hệ thống YAML configs (`configs/data/`, `configs/simulation/`, `configs/models/`, `configs/fusion/`, `configs/experiment/`, `configs/demo.yaml`).
- **Milestone 2 (VIVOS Manifest, Split & Leakage Audit)**: ĐẠT. Quét 12,420 file VIVOS, chuẩn hóa tiếng Việt NFC, chia speaker-disjoint (32 dev, 14 val, 19 test) và tách riêng enrollment utterances. Lệnh `meeting-pipeline data audit` đạt 100% không vi phạm rò rỉ. Báo cáo tại `reports/data_audit.json` và `reports/data_audit.md`.
- **Milestone 3 (Synthetic Multi-Device Generator)**: ĐẠT. Xây dựng phòng 3D ShoeBox và RIR bằng `pyroomacoustics`, mô phỏng thiết bị (gain, offset, drift ppm, clipping, dropout), nhiễu chuẩn quy tắc VIVOS (white, pink, brown, hum 50Hz, room tone, VIVOS babble). Lệnh `meeting-pipeline simulate generate` sinh âm thanh đa thiết bị chuẩn 16kHz mono.
- **Milestone 4 (Multi-Source Synchronization & VAD)**: ĐẠT. Tự động chọn nguồn tham chiếu chất lượng cao, căn chỉnh coarse offset bằng tương quan vỏ năng lượng (envelope correlation) và bù drift. Fused Silero VAD tạo timeline hoạt động thống nhất với Frame F1 > 0.90 trên smoke/moderate.
- **Milestone 5 (Speaker Identification & Segment ASR)**: ĐẠT. Trích xuất prototype người nói (ECAPA-TDNN), nhận diện danh tính đa nguồn (4 baseline: fixed, best-quality, unweighted mean, quality-weighted). PhoWhisper trích xuất text, word timestamps, confidence và các đặc trưng âm học không rò rỉ (RMS, SNR ước lượng, clipping, dropout).
- **Milestone 6 (Transcript Fusion F0-F6 & Provenance)**: ĐẠT. Căn chỉnh từ qua dynamic programming, confusion network hỗ trợ insertion/deletion/substitution. Hoàn thiện 7 baseline F0–F6 (Fixed, Best-Segment, Oracle-Best, ROVER, ASR-Weighted, Rule-Weighted, Learned-Logistic). Truy vết nguồn gốc từ (WordProvenance) và trích xuất audio evidence clip cho từng thiết bị.

## Cài đặt

Yêu cầu macOS arm64, Python 3.11, `uv`, FFmpeg/ffprobe và đủ dung lượng cho model/dữ liệu.

```bash
uv sync --locked --all-extras
uv run meeting-pipeline doctor
```

Chấp nhận điều khoản của `pyannote/segmentation-3.0` bằng tài khoản Hugging Face của bạn,
sau đó chỉ đặt token trong environment:

```bash
export HF_TOKEN='<read token>'
uv run meeting-pipeline models prepare --config configs/default.yaml
```

Không đặt token trong YAML, SQLite, manifest hoặc log. `models prepare` tải weights vào
`data/model_cache`; lệnh `doctor` không tải mạng.

## Chạy local

Mở web demo trên máy local:

```bash
uv run meeting-pipeline serve --host 127.0.0.1 --port 8000
```

Truy cập `http://127.0.0.1:8000`. Có thể đăng ký tên và một hoặc nhiều mẫu giọng riêng bằng
ECAPA, sau đó chọn những người tham gia khi tạo cuộc họp và tải 1-8 bản ghi. Backend đồng bộ
các nguồn, tạo VAD timeline chung, chạy PhoWhisper cho từng `segment x source`, căn chỉnh từ và
dung hợp transcript bằng F1/F3/F4/F5/F6. Kết quả hiển thị transcript từng nguồn, trọng số,
word provenance, audio đã đồng bộ và evidence clip cùng timestamp của mọi thiết bị. Web chạy job
nền đơn luồng và cho tải JSON/CSV/TXT/ZIP.

Vùng được phát hiện có hai người nói đồng thời hiện được giữ thành một dòng timeline cần
kiểm tra, kèm clip gốc của từng nguồn. Demo tạm bỏ qua tách giọng, nhận diện người nói
và ASR cho vùng này; văn bản để trống thay vì đoán một người đang nói gì.

Hoặc chạy trực tiếp bằng CLI:

```bash
uv run meeting-pipeline run-files \
  --meeting-name demo \
  --fusion-method F5_RULE_WEIGHTED \
  recording-1.aac recording-2.aac
```

Kết quả nằm trong `data/meetings/demo/runs/<run-id>/`. Người khớp hồ sơ đủ ngưỡng được hiện tên;
người chưa đăng ký hoặc chưa đủ bằng chứng được giữ `unknown` nhưng mang nhãn ổn định
`Speaker 1`, `Speaker 2`,… Dữ liệu sinh ra ở `data/`; audio gốc trong `dataset/voices/` được giữ
nguyên.

## Biên bản Word với LLM và Fuzzy C-Means

Demo hỗ trợ Qwen3-4B 4-bit qua MLX, embedding multilingual-e5-small và FCM.
Có chế độ chi tiết giữ đề mục mẫu, tổng quát sinh chủ đề trong vùng nội dung,
và tạo lại DOCX từ transcript hiện có. Xem
[hướng dẫn cài đặt, sử dụng và giới hạn](docs/LLM_FCM_MINUTES.md).
PDF/scan đã được bổ sung ở **bản web MongoDB mới**; demo cũ giữ luồng Word.
Fine-tuning chưa thực hiện trong đợt này.

DOC/DOCX có thể xuất DOCX theo **Nghị định 30/2020/NĐ-CP** hoặc
**Hướng dẫn 05-HD/VPTW ngày 27/5/2026**. Có thể áp dụng lại thể thức cho
nội dung đã điền mà không chạy ASR/LLM. Xem [cách sử dụng và kiểm tra thể thức](docs/DOCX_FORMAT_STANDARDS.md).

## Dữ liệu

Kiểm tra kế hoạch trước khi tải:

```bash
uv run meeting-pipeline data plan --config configs/evaluation.yaml
```

Ngân sách mạng mặc định: VIVOS 1,5 GB, LibriWASN 1 GB, VoxVietnam 1 GB, tổng 3,5 GB
(GB thập phân). Đây không phải dung lượng đĩa cuối cùng. VoxVietnam cần quyền truy cập riêng.
Downloader không được tải archive LibriWASN 4–5 GB rồi xóa bớt để đạt ngân sách.

## Kiểm tra

```bash
uv run pytest tests/unit tests/integration
uv run ruff check .
uv run ruff format --check .
uv run mypy src/meeting_pipeline
```

Model smoke, browser Playwright và dataset tests là các bước riêng, không tự tải trong test nhanh.
