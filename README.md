# MINDA — Hệ thống Chép lời & Lập Biên bản Cuộc họp Tiếng Việt Đa nguồn Offline

**MINDA** (*Multi-source Intelligent Meeting Documentation Assistant*) là hệ thống xử lý âm thanh cuộc họp tiếng Việt thu từ **1–8 thiết bị ghi âm độc lập** (điện thoại/máy ghi âm không đồng bộ), chạy **hoàn toàn offline trên Apple Silicon (macOS `arm64`)** để tạo:

1. **Bản chép lời (transcript) hợp nhất đa nguồn** kèm nhãn người nói, độ tin cậy từng từ (*word provenance*) và clip âm thanh đối chiếu cho từng thiết bị.
2. **Biên bản cuộc họp có cấu trúc** sinh từ đồ thị diễn biến hội thoại (*event–relation–state graph*) bằng LLM cục bộ (`Qwen3-4B-Instruct-2507-4bit` + `LoRA B` trên MLX), xuất file Word (`.docx`) chỉnh sửa được theo **Nghị định 30/2020/NĐ-CP** hoặc **Hướng dẫn 05-HD/VPTW (2026)**.
3. **Ứng dụng web Minda (User/Admin)** tích hợp MongoDB, hàng đợi xử lý nền đơn luồng, quản lý hồ sơ giọng nói, nạp mẫu Word/PDF/ảnh scan, rà soát biên bản, xem trước từng trang DOCX và sao lưu/khôi phục dữ liệu.

---

## 1. Kiến trúc Tổng thể & Luồng Xử lý

Toàn bộ mã nguồn đã được hợp nhất tại thư mục gốc gồm hai package Python độc lập (`meeting_pipeline` và `meeting_backend`) cùng giao diện React (`apps/web`):

```text
                        ┌──────────────────────────────────────────────┐
                        │        Ứng dụng Web Minda (apps/web)         │
                        │    React 19 · Vite · Tailwind · Cytoscape    │
                        └──────────────────────┬───────────────────────┘
                                               │ REST API (/api/v1)
                        ┌──────────────────────▼───────────────────────┐
                        │     Backend & Worker (src/meeting_backend)   │
                        │  FastAPI · MongoDB · ArtifactStore · Worker  │
                        │  PDF/Scan Ingest (pypdf + Tesseract + OpenCV)│
                        └──────────────┬───────────────┬───────────────┘
                                       │               │
         ┌─────────────────────────────▼───┐       ┌───▼────────────────────────────────────┐
         │  LUỒNG 1: AUDIO → TRANSCRIPT    │       │  LUỒNG 2: TRANSCRIPT → BIÊN BẢN DOCX   │
         │  (src/meeting_pipeline/)        │       │  (src/meeting_pipeline/minutes/)       │
         ├─────────────────────────────────┤       ├────────────────────────────────────────┤
         │ 1. Chuẩn hóa 16 kHz mono        │       │ 1. Nạp mẫu DOC/DOCX/PDF/Scan           │
         │    (ffmpeg/ffprobe, giữ gốc)    │       │    → doc_parser + SchemaMapper         │
         │ 2. Đồng bộ đa nguồn & Timeline  │       │ 2. Trích xuất trường cấu trúc NĐ 30    │
         │    - Offset & drift (100 Hz)    │       │    (ngày/giờ/biểu quyết deterministic) │
         │    - Pause/Resume landmarks     │       │ 3. Hiểu hội thoại bằng Đồ thị (MLX)    │
         │ 3. Phân đoạn & Chồng lấn        │       │    - Qwen3-4B 4-bit + LoRA B:          │
         │    - pyannote/segmentation-3.0  │       │      extract (sự kiện) → relations     │
         │    - silero_vad (guard biên)    │       │    - Suy luận trạng thái (graph_state) │
         │    - sepformer-whamr (cấu hình) │       │ 4. Gom chủ đề (tùy chọn tổng quát)     │
         │ 4. Nhận diện & Gom người nói    │       │    - multilingual-e5-small + FCM       │
         │    - WeSpeaker ResNet34-LM      │       │ 5. Biên tập & Kiểm chứng thực tế       │
         │    - P2_EMBEDDING_FUSION        │       │    - graph_editorial / graph_writer    │
         │ 5. ASR tiếng Việt (MLX Worker)  │       │    - Kiểm ID nguồn, số liệu, phủ định  │
         │    - PhoWhisper-medium MLX      │       │ 6. Render DOCX & Chuẩn hóa thể thức    │
         │    - Adaptive max=3, guard<0.8s │       │    - NĐ 30/2020 hoặc HD 05-HD/VPTW     │
         │ 6. Dung hợp & Truy vết          │       │    - Preview (LibreOffice + Poppler)   │
         │    - F5_RULE_WEIGHTED_CORRECTED │       │    - Đóng gói ZIP + kiểm toàn vẹn hash │
         │    - Tùy chọn Audio Delay&Sum   │       └────────────────────────────────────────┘
         └─────────────────────────────────┘
```

### Nguyên tắc tách biệt runtime
- **API web (`meeting_backend`)** không import Torch/MLX/Transformers khi khởi động; mọi tác vụ nặng (nhận dạng giọng, ASR, LLM, OCR) được đẩy qua hàng đợi MongoDB cho **worker đơn luồng** xử lý tuần tự với khóa `flock` và cơ chế lease/heartbeat.
- **ASR MLX (`.venv-asr-mlx`)** và **LLM MLX (`.venv-llm`)** chạy qua tiến trình worker con riêng (`scripts/asr_mlx_worker.py`, `scripts/minutes_model_worker.py`) để không xung đột phiên bản thư viện với môi trường PyTorch/Pyannote và giải phóng bộ nhớ sau khi hoàn tất.
- **Không tự tải model ngầm lúc suy luận:** toàn bộ trọng số được ghim `revision`/SHA-256 và chuẩn bị trước vào `data/model_cache/`; quá trình chạy thực tế hoàn toàn offline.

---

## 2. Cấu hình & Mô hình Mặc định Hiện tại

Các tham số thực thi được quản lý tập trung tại [`configs/default.yaml`](configs/default.yaml), [`configs/minutes.yaml`](configs/minutes.yaml) và [`configs/backend.yaml`](configs/backend.yaml):

| Giai đoạn | Mô hình / Thuật toán mặc định | Cấu hình chính |
| :--- | :--- | :--- |
| **Đồng bộ âm thanh** | Envelope 100 Hz + hồi quy drift + STFT landmark | `max_offset_seconds: 120`, `allow_drift: true`, `minimum_drift_inliers: 3` |
| **VAD & Phân đoạn** | `pyannote/segmentation-3.0` + `silero_vad` | `vad_threshold: 0.5`, `context_seconds: 10`, `step_seconds: 2.5` |
| **Tách giọng chồng lấn** | `speechbrain/sepformer-whamr` (8 kHz) | `chunk_seconds: 8`, `overlap_seconds: 1` |
| **Nhận diện người nói** | `pyannote/wespeaker-voxceleb-resnet34-LM` | `fusion_policy: P2_EMBEDDING_FUSION`, `identity_threshold: 0.4143`, `cluster_threshold: 0.50` |
| **ASR tiếng Việt** | `vinai/PhoWhisper-medium` (MLX worker; hỗ trợ `small`) | `auto_backend: mlx`, `fusion_mode: transcript`, `max_verification_sources: 3`, `audio_denoise: afftdn` |
| **Dung hợp đa nguồn** | `F5_RULE_WEIGHTED_CORRECTED` (confusion network) | Kết hợp chất lượng âm học + word confidence từ MLX; có nhánh nhanh `audio` (Delay-and-Sum + `afftdn`) |
| **LLM Đồ thị & Biên bản** | `mlx-community/Qwen3-4B-Instruct-2507-4bit` + `LoRA B` | Adapter `checkpoint-132` áp cho `extract` & `relations`; `input_token_budget: 6144`, `output_token_budget: 2048` |
| **Embedding & Gom chủ đề** | `intfloat/multilingual-e5-small` + Fuzzy C-Means | `max_clusters: 4`, `minimum_silhouette: 0.22`, `fuzziness: 1.3` |
| **OCR biểu mẫu** | `Tesseract` (`tessdata_fast` `vie+eng`) + OpenCV | Hỗ trợ `.docx`, `.doc`, PDF văn bản, PDF scan và ảnh |
| **Thể thức xuất Word** | `nd30_2020` (mặc định) / `hd05_2026` | Bảo toàn OOXML, kiểm toàn vẹn ZIP, preview ảnh bằng LibreOffice + Poppler |

---

## 3. Cấu trúc Thư mục Dự án

```text
.
├── apps/web/                   # Frontend React 19 + TypeScript + Vite (giao diện Minda User/Admin)
├── src/
│   ├── meeting_pipeline/       # Lõi pipeline AI: sync, VAD, speaker, ASR, fusion, graph minutes, DOCX
│   │   ├── adapters/           # Giao tiếp FFmpeg, MLX ASR, PhoWhisper, model registry
│   │   ├── audio/              # Đồng bộ offset/drift, acoustic fingerprint, timeline, signal fusion
│   │   ├── speaker/            # WeSpeaker/ECAPA encoder, enrollment, P0–P3 fusion, clustering
│   │   ├── asr/                # Segment ASR, adaptive routing, cache, guard biên/chất lượng
│   │   ├── fusion/             # Word alignment, confusion network, F0–F6, word provenance
│   │   ├── pipeline/           # MultiSourceFusionPipeline, speaker_turns, stages
│   │   ├── minutes/            # Parser DOCX, structured_fields, graph_*, FCM, renderer, NĐ30/HD05
│   │   └── simulation/         # Bộ sinh phòng họp đa thiết bị mô phỏng (pyroomacoustics + VIVOS)
│   └── meeting_backend/        # Backend FastAPI + MongoDB + Worker nền + Ingest PDF/OCR
│       ├── core/               # Settings, bảo mật/session, mã lỗi, logging
│       ├── modules/            # auth, users, meetings, transcripts, speakers, templates, minutes, jobs, system
│       ├── infrastructure/     # MongoDB client/indexes/validators, ArtifactStore, backup/restore
│       ├── integrations/       # Adapter nối sang MultiSourceFusionPipeline & MinutesService
│       ├── processing/         # Ingest DOC/DOCX/PDF/ảnh, OCR bảng OpenCV, render preview
│       └── worker/             # Worker claim/heartbeat/lease/cancellation
├── configs/                    # default.yaml, minutes.yaml, backend.yaml, cấu hình simulation/eval
├── scripts/                    # Worker MLX, script tải/chuyển model, launcher web, script benchmark cũ
├── experiments/
│   ├── benchmark_20261118/     # 13 script tái lập đầy đủ bộ benchmark Đợt 1–3
│   ├── comparative_benchmark/  # Bộ benchmark so sánh nền
│   ├── minutes_graph/          # Đánh giá đồ thị hội thoại & tốc độ sinh biên bản
│   └── speaker_identification/ # Đánh giá bộ mã hóa & hiệu chuẩn ngưỡng người nói
├── tests/                      # unit/, integration/, backend/, model_smoke/
├── reports/
│   ├── BENCHMARK_TONG_HOP_2026-11-18.md   # Báo cáo tổng hợp thực nghiệm Đợt 1–3
│   └── minutes_graph/20261118/            # Kết quả holdout LLM (Qwen3 / Qwen3.5 / Gemma4)
├── docs/                       # Tài liệu kiến trúc, hướng dẫn web, chuẩn thể thức DOCX, kiểm toán dữ liệu
├── manifests/                  # Manifest tải có ngân sách cho VIVOS, LibriWASN, VoxVietnam
├── references.md               # Tổng hợp toàn bộ nguồn tham khảo học thuật & kỹ thuật
└── pyproject.toml              # Khai báo package, extras (backend/ml/evaluation/dev) và CLI entry points
```

---

## 4. Cài đặt & Chuẩn bị Môi trường

### Yêu cầu hệ thống
- **Phần cứng/HĐH:** macOS Apple Silicon (`arm64`, khuyến nghị ≥ 16 GB Unified Memory).
- **Công cụ hệ thống:** Python `3.11`, [`uv`](https://docs.astral.sh/uv/), Node.js `22.12+` / `24`, MongoDB local (`mongodb://127.0.0.1:27017`), `ffmpeg`/`ffprobe`, `tesseract`, `poppler`, `LibreOffice`.

```bash
brew install ffmpeg tesseract poppler
brew install --cask libreoffice
```

### Bước 1 — Cài đặt các môi trường Python & build Frontend

```bash
# 1. Môi trường chính cho backend + pipeline + kiểm thử
UV_PROJECT_ENVIRONMENT=.venv-backend uv sync --locked --extra backend --extra ml --extra evaluation --extra dev

# (Tùy chọn) Hoặc môi trường mặc định .venv cho CLI pipeline
uv sync --locked --all-extras

# 2. Môi trường MLX tách biệt cho ASR (PhoWhisper MLX)
uv venv .venv-asr-mlx --python 3.11
uv pip install --python .venv-asr-mlx/bin/python -r requirements-asr-mlx.txt

# 3. Môi trường MLX tách biệt cho LLM biên bản (Qwen3-4B + LoRA B)
uv venv .venv-llm --python 3.11
uv pip install --python .venv-llm/bin/python -r requirements-minutes-mlx.txt

# 4. Build giao diện web React (apps/web/dist)
npm --prefix apps/web ci
npm --prefix apps/web run build
```

### Bước 2 — Chuẩn bị trọng số Model & OCR Offline

Chấp nhận điều khoản `pyannote/segmentation-3.0` trên Hugging Face, sao chép `.env.example` thành `.env` (hoặc đặt biến môi trường `HF_TOKEN`), tuyệt đối không commit token thật:

```bash
export HF_TOKEN='<your-hf-read-token>'

# 1. Tải model Audio/Speaker/ASR vào data/model_cache/
.venv-backend/bin/meeting-pipeline models prepare --config configs/default.yaml

# 2. Chuyển đổi PhoWhisper-medium sang định dạng MLX float16 cục bộ
.venv-asr-mlx/bin/python scripts/prepare_asr_mlx.py --download-converter

# 3. Tải LLM Qwen3-4B-Instruct-2507-4bit & embedding multilingual-e5-small
.venv-backend/bin/python scripts/prepare_minutes_models.py

# 4. Tải dữ liệu OCR Tesseract vie+eng
.venv-backend/bin/python -m meeting_backend.cli prepare-ocr

# 5. Kiểm tra tổng thể môi trường (không tải mạng)
.venv-backend/bin/meeting-pipeline doctor
.venv-backend/bin/python -m meeting_backend.cli doctor
```

> **Lưu ý về LoRA B adapter:** `configs/minutes.yaml` trỏ `adapter_path` tới trọng số fine-tune `LoRA B (checkpoint-132)` cùng mã kiểm SHA-256. Trọng số nhị phân (`~205 MB`) không lưu trên Git; nếu chưa có tệp adapter cục bộ, đặt `adapter_path: null` để chạy trực tiếp bằng mô hình nền `Qwen3-4B-Instruct-2507-4bit`.

---

## 5. Hướng dẫn Chạy Hệ thống

> Mọi lệnh dưới đây đều chạy từ **thư mục gốc của repository**.

### 5.1. Chạy Ứng dụng Web Minda (FastAPI + MongoDB + Worker — Khuyến nghị)

#### Bước 1 — Khởi động MongoDB cục bộ
Đảm bảo MongoDB đang lắng nghe tại `127.0.0.1:27017` (ví dụ trên macOS dùng Homebrew):

```bash
brew services start mongodb-community
# Kiểm tra cổng 27017 đã mở chưa
nc -z 127.0.0.1 27017 && echo "MongoDB OK"
```

#### Bước 2 — Build giao diện web (chỉ cần chạy lần đầu hoặc khi sửa `apps/web/`)

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
```

#### Bước 3 — Khởi động đồng thời API và Worker nền

```bash
.venv-backend/bin/python scripts/backend/run_local.py --port 8010
```

Hoặc chạy tách trên 2 cửa sổ terminal để dễ theo dõi log riêng:

```bash
# Terminal 1: FastAPI server + phục vụ giao diện apps/web/dist
.venv-backend/bin/python -m meeting_backend.cli serve --host 127.0.0.1 --port 8010

# Terminal 2: Worker xử lý nền đơn luồng (ASR, Speaker, LLM, OCR)
.venv-backend/bin/python -m meeting_backend.cli worker
```

#### Bước 4 — Sử dụng trên trình duyệt
Mở `http://127.0.0.1:8010` và thực hiện luồng cơ bản:
1. **Khởi tạo tài khoản quản trị** ở lần truy cập đầu tiên (không có mật khẩu mặc định).
2. *(Tùy chọn)* Tạo **Hồ sơ giọng nói** từ các mẫu thu âm sạch (hệ thống vẫn chép lời và gom nhãn `Speaker 1, 2,...` bình thường nếu chưa có hồ sơ).
3. Tải **Biểu mẫu biên bản** (`.docx`, `.doc`, PDF hoặc ảnh scan; riêng PDF/ảnh sẽ hiển thị màn hình đối chiếu & duyệt trước khi dùng).
4. **Tạo cuộc họp mới**: nhập thông tin, tải **1–8 file âm thanh** từ nhiều thiết bị, chọn thành viên tham gia và biểu mẫu → chạy tác vụ chép lời.
5. **Rà soát Transcript**: nghe lại evidence clip của từng thiết bị, kiểm tra độ tin cậy từ và đổi nhãn người nói nếu cần.
6. **Tạo & xuất Biên bản Word**: chuyển sang tab **Biên bản**, chọn chế độ chi tiết/tổng quát, chọn thể thức **NĐ 30/2020** (`nd30_2020`) hoặc **HD 05-HD/VPTW** (`hd05_2026`), xem trước từng trang DOCX và tải file `.docx`/`.zip`. Có thể **đổi thể thức** trên nội dung đã sinh mà không cần chạy lại ASR/LLM.

#### Tùy chỉnh biến môi trường (tùy chọn)
Có thể ghi đè [`configs/backend.yaml`](configs/backend.yaml) bằng biến `MEETING_APP_*` (tên database bắt buộc có tiền tố `meeting_app_`):

```bash
export MEETING_APP_MONGO_URI=mongodb://127.0.0.1:27017
export MEETING_APP_MONGO_DATABASE=meeting_app_demo
export MEETING_APP_DATA_DIR=data/app_demo
```

---

### 5.2. Chạy Chế độ Phát triển Frontend + Backend (Hot Reload)

Mở 3 terminal tại thư mục gốc:

```bash
# Terminal 1: Backend API (cổng 8010)
.venv-backend/bin/python -m meeting_backend.cli serve --host 127.0.0.1 --port 8010

# Terminal 2: Worker nền
.venv-backend/bin/python -m meeting_backend.cli worker

# Terminal 3: Vite dev server (cổng 5173, tự proxy /api sang 8010)
npm --prefix apps/web run dev
```

Truy cập `http://127.0.0.1:5173`.

---

### 5.3. Chạy Pipeline trực tiếp qua CLI (Không cần MongoDB)

Phù hợp khi cần xử lý nhanh file âm thanh từ dòng lệnh hoặc tích hợp script:

```bash
# 1. Kiểm tra nhanh môi trường & model cache (không tải mạng)
.venv-backend/bin/meeting-pipeline doctor --config configs/default.yaml

# 2. Chép lời & dung hợp 1–8 bản ghi âm cuộc họp
.venv-backend/bin/meeting-pipeline run-files \
  --meeting-name hop_giao_ban \
  --fusion-method F5_RULE_WEIGHTED \
  --config configs/default.yaml \
  path/to/phone1.m4a path/to/phone2.m4a
```

* Các chế độ `--fusion-method` hỗ trợ gồm `F0_FIXED`, `F1_BEST_SEGMENT`, `F3_ROVER`, `F4_ASR_WEIGHTED`, `F5_RULE_WEIGHTED` (mặc định).
* Toàn bộ đầu ra (transcript JSON/CSV/TXT, timeline, word provenance, audio đã đồng bộ và evidence clips) nằm trong `data/meetings/<meeting-name>/runs/<run-id>/`.

---

### 5.4. Tái lập Bộ Benchmark Thực nghiệm (Đợt 1–3)

Các script tái lập trong [`experiments/benchmark_20261118/`](experiments/benchmark_20261118/) xuất kết quả JSON/CSV về `reports/benchmark_20261118/`:

```bash
# Đợt 1 — 5 bài chạy nhanh (~5 phút)
.venv-backend/bin/python experiments/benchmark_20261118/run_wave1_sync_timeline.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave1_speaker_multisource.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave1_clustering.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave1_structured_export.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave1_ocr.py

# Đợt 2 — ASR MLX, Multi-source Fusion & Core E2E Replay
.venv-backend/bin/python experiments/benchmark_20261118/run_wave2_asr.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave2_fusion.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave2_core_e2e.py

# Đợt 3 — VAD/Separation/Retrieval, PDF/Backend, LLM LoRA B MLX & ASR đối chiếu lớn
.venv-backend/bin/python experiments/benchmark_20261118/run_wave3_audio_stages_and_retrieval.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave3_doc_and_backend.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave3_llm_mlx.py
.venv-backend/bin/python experiments/benchmark_20261118/run_wave3_asr_large.py
```

*(Một số bài đối chiếu Đợt 1/3 có so sánh thêm các engine phụ như `easyocr`, `vietocr`, `funasr` hoặc checkpoint đối chứng ngoài `configs/default.yaml`.)*

---

### 5.5. Lệnh Vận hành & Khắc phục Sự cố Thường gặp

```bash
# Kiểm tra đầy đủ trạng thái MongoDB, model cache, OCR và công cụ preview DOCX
.venv-backend/bin/python -m meeting_backend.cli doctor

# Khôi phục ảnh xem trước DOCX bị thiếu (chạy không --apply để xem trước danh sách)
.venv-backend/bin/python -m meeting_backend.cli repair-previews
.venv-backend/bin/python -m meeting_backend.cli repair-previews --apply

# Nhập kết quả từ bản pipeline/SQLite cũ vào Web Minda (khuyến nghị chạy --dry-run trước)
.venv-backend/bin/python -m meeting_backend.cli import-run /duong/dan/run --username admin --dry-run
.venv-backend/bin/python -m meeting_backend.cli import-legacy data/meetings --username admin --sqlite data/app.sqlite --dry-run
```

| Tình huống | Cách kiểm tra & xử lý |
| :--- | :--- |
| Báo thiếu `apps/web/dist/index.html` khi chạy `run_local.py` | Chạy `npm --prefix apps/web ci && npm --prefix apps/web run build`. |
| Không kết nối được MongoDB | Kiểm tra `brew services list` hoặc khởi động `mongod` trên cổng `27017`. |
| Xuất được DOCX nhưng không có ảnh xem trước | Cài `brew install poppler && brew install --cask libreoffice`, kiểm tra lại bằng `meeting_backend.cli doctor`, rồi chạy `repair-previews --apply`. |
| Lỗi không tìm thấy `LoRA B` adapter khi chạy LLM biên bản | Nếu chưa tải bộ weights adapter cục bộ, đặt `adapter_path: null` trong [`configs/minutes.yaml`](configs/minutes.yaml) để chạy mô hình nền `Qwen3-4B-Instruct-2507-4bit`. |
| Tra lỗi API hoặc tác vụ worker bị dừng | Xem `data/app/logs/api.log` (theo `X-Request-ID`) và `data/app/logs/jobs/<job-id>/worker.log`. |

---

## 6. Tóm tắt Kết quả Thực nghiệm (Benchmark Đợt 1–3)

Hệ thống đã được đánh giá toàn diện trên Apple MacBook Air M4 (16 GB) qua **12 hạng mục thực nghiệm** (tất cả script tái lập tại [`experiments/benchmark_20261118/`](experiments/benchmark_20261118/)). Báo cáo chi tiết đầy đủ bảng số liệu và kiểm định Bootstrap 95% CI nằm tại **[`reports/BENCHMARK_TONG_HOP_2026-11-18.md`](reports/BENCHMARK_TONG_HOP_2026-11-18.md)**.

| Thành phần | Cấu hình chọn | Kết quả nổi bật & Đối chiếu chính |
| :--- | :--- | :--- |
| **Đồng bộ đa nguồn** | `full_sync` (100 Hz env) + `resolve_clocks` | Offset MAE **`1,04–2,50 ms`** (từ `6.769 ms` no-sync); drift lớn giảm **`711,7 → 18,5 ppm`**; tách pause/resume cùng âm học **`12/12`** dưới `0,05 ms`. |
| **VAD** | `pyannote3_prod` + `silero_vad` | Frame F1 **`0,9372`** (`RTF 0,008`) và **`0,9350`** (`RTF 0,003`), FA thấp (`0,08–0,09`). |
| **Tách giọng chồng lấn** | `sepformer_whamr` | Đạt **`PIT WER = 87,61%`**, **`Best Stream = 51,61%`** với PhoWhisper-medium MLX (tốt hơn nhiều không tách `130,98%` và `libri2mix` `108,10%`). |
| **Nhận diện người nói** | `WeSpeaker` + `P2_EMBEDDING_FUSION` | Pairwise F1 **`0,8889`** (30 ca) / **`0,8611`** (20 ca đa mic), vượt `+16,6%` so với `ECAPA` (`0,7230`), đếm đúng **100%** số người ở nhóm 4-mic. |
| **ASR tiếng Việt** | `PhoWhisper-medium` (MLX) | Trên 563 câu VIVOS: **WER `5,03%`**, **CER `2,42%`**, `RTF 0,735`, word confidence `99,82%`. Nhanh gấp **`1,89×`** `PhoWhisper-large` (`4,73%`, khác biệt `-0,37%` không có ý nghĩa thống kê) và vượt xa `whisper-large-v3-turbo` (`13,44%`) hay `wav2vec2-vi` (`10,61%`). |
| **Dung hợp đa nguồn** | `F5_RULE_WEIGHTED_CORRECTED` + `Adaptive max=3` | Trên 24 ca đa mic: WER **`15,19%`** (giảm `-2,08%` có ý nghĩa thống kê so với `F0_FIXED` `17,46%`); `Adaptive max=3` tiết kiệm **`35,4%`** lượt ASR mà giữ WER `15,50%`. |
| **LLM Đồ thị Biên bản** | `Qwen3-4B MLX 4-bit` + `LoRA B` | Trên 60 ca Holdout `v2.1`: **Event F1 `0,8148`**, **Relation F1 `0,4467`**, **State Exact `0,3333` (`14/42`)**, median **`9,44 s/ca`** (`peak 3,68 GB`) — vượt Base MLX `+0,3639 Relation F1`, tương đương thống kê GPU NVIDIA L4 NF4 nhưng **nhanh gấp `5,27×`**. |
| **OCR & Xuất Word** | `Tesseract` + `OpenCV` / `DOCX Renderer` | Xuất DOCX đạt `zip_integrity = 100%`, `0/60` false positive ngày/giờ trên `v2.1`; OCR bảng OpenCV nhận `100%` trên trang phẳng (`Cell CER 1,78%` khi kết hợp VietOCR). |

---

## 7. Kiểm thử & Kiểm tra Chất lượng Mã

```bash
# Unit & Integration tests (480 bài kiểm thử pipeline + tích hợp)
PYTHONPATH=src .venv-backend/bin/python -m pytest tests/unit tests/integration -q

# Backend tests (57 bài kiểm thử FastAPI/MongoDB/Worker/OCR; tự tạo & dọn DB test riêng)
PYTHONPATH=src .venv-backend/bin/python -m pytest tests/backend -q

# Lint, Format & Type-check
.venv-backend/bin/python -m ruff check .
.venv-backend/bin/python -m mypy src/meeting_pipeline
npm --prefix apps/web run check
npm --prefix apps/web run format:check
```

---

## 8. Giới hạn Hiện tại & Hướng phát triển

- **Nhập mẫu PDF/ảnh scan:** Luồng `ingest.py` cho PDF/scan hiện tái dựng theo từng đoạn văn nên chưa bảo toàn cấu trúc bảng (`0/2` tables so với nạp `.docx`/`.doc` trực tiếp); bộ tách bảng OpenCV nhạy với góc nghiêng nhỏ (`~1,2°`) và cần bổ sung bước nắn thẳng ảnh (*deskew*).
- **Gom cụm chủ đề (`minimum_silhouette = 0,22`):** Ngưỡng hiện tại bảo vệ tốt khi các chủ đề tách biệt nhưng có xu hướng fallback về 1 cụm trên hội thoại ngắn liên mạch.
- **Tốc độ E2E biên bản:** Trên phiên họp 2 phút chạy lạnh (*uncached*), bước Audio Pipeline chỉ chiếm `~10–24%` (`50–103 s`), phần lớn thời gian nằm ở các lượt sinh/kiểm chứng biên tập của LLM (`320–443 s`).
- **Đánh giá thực địa:** Bộ benchmark hiện tại phủ đầy đủ dữ liệu chuẩn hóa/mô phỏng (`VIVOS`, `LibriWASN`, `Holdout v2.1`); đánh giá trên tập **cuộc họp tiếng Việt ghi âm thực tế** và tải hàng đợi MongoDB trực tiếp sẽ được thực hiện ở bước tiếp theo.

---

## 9. Tài liệu Tham khảo & Chi tiết

- **Báo cáo thực nghiệm tổng hợp (Đợt 1–3):** [`reports/BENCHMARK_TONG_HOP_2026-11-18.md`](reports/BENCHMARK_TONG_HOP_2026-11-18.md)
- **Danh mục tài liệu tham khảo toàn hệ thống:** [`references.md`](references.md)
- **Kiến trúc & vận hành Web Minda:** [`docs/backend/ARCHITECTURE.md`](docs/backend/ARCHITECTURE.md) · [`docs/backend/QUICKSTART.md`](docs/backend/QUICKSTART.md) · [`docs/BAO_CAO_HUONG_DAN_SU_DUNG_WEB_MOI_2026-10-17.md`](docs/BAO_CAO_HUONG_DAN_SU_DUNG_WEB_MOI_2026-10-17.md)
- **Chi tiết pipeline, LLM/FCM & Thể thức văn bản:** [`docs/pipeline.md`](docs/pipeline.md) · [`docs/LLM_FCM_MINUTES.md`](docs/LLM_FCM_MINUTES.md) · [`docs/DOCX_FORMAT_STANDARDS.md`](docs/DOCX_FORMAT_STANDARDS.md)
- **Sinh dữ liệu đồ thị & nhận diện thương hiệu:** [`docs/HUONG_DAN_SINH_DU_LIEU_DO_THI_MINDA.md`](docs/HUONG_DAN_SINH_DU_LIEU_DO_THI_MINDA.md) · [`docs/BRANDING.md`](docs/BRANDING.md)
