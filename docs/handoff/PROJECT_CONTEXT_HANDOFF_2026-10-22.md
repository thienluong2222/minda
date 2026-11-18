# MINDA — CONTEXT TOÀN HỆ THỐNG

**Ngày cập nhật:** 22/10/2026, múi giờ Asia/Ho_Chi_Minh.  
**Mục đích:** Chuyển bối cảnh toàn hệ thống sang hội thoại mới để tiếp tục phát triển, chẩn đoán lỗi, viết báo cáo luận văn và chuẩn bị trình diễn. Người dùng chỉ cần một file context cho lần bàn giao này, không tạo commit.  
**Phạm vi xác minh lần này:** Đọc mã nguồn, cấu hình, Git, tài liệu và báo cáo đã lưu; kiểm đường dẫn import và cổng TCP. Không chạy lại toàn bộ kiểm thử, không suy luận model, không mở server và không thay đổi dữ liệu ứng dụng trong lần lập context này.

## Mục lục

1. [Tóm tắt cần đọc trước](#1-tóm-tắt-cần-đọc-trước)
2. [Yêu cầu và quyết định đã chốt](#2-yêu-cầu-và-quyết-định-đã-chốt)
3. [Thư mục, Git và môi trường](#3-thư-mục-git-và-môi-trường)
4. [Kiến trúc và mã nguồn](#4-kiến-trúc-và-mã-nguồn)
5. [Pipeline âm thanh, người nói và ASR](#5-pipeline-âm-thanh-người-nói-và-asr)
6. [LLM, embedding và Fuzzy C-Means](#6-llm-embedding-và-fuzzy-c-means)
7. [Biểu mẫu, OCR, DOCX và preview](#7-biểu-mẫu-ocr-docx-và-preview)
8. [Giao diện người dùng và quản trị](#8-giao-diện-người-dùng-và-quản-trị)
9. [Database, phiên bản, bằng chứng và worker](#9-database-phiên-bản-bằng-chứng-và-worker)
10. [Mở, dừng, kiểm tra và khôi phục](#10-mở-dừng-kiểm-tra-và-khôi-phục)
11. [Bằng chứng kiểm thử và phạm vi kết luận](#11-bằng-chứng-kiểm-thử-và-phạm-vi-kết-luận)
12. [Hạn chế và hướng công việc tiếp theo](#12-hạn-chế-và-hướng-công-việc-tiếp-theo)
13. [Nghiên cứu cải thiện lời văn đã thảo luận](#13-nghiên-cứu-cải-thiện-lời-văn-đã-thảo-luận)
14. [Định vị dự thi và logo](#14-định-vị-dự-thi-và-logo)
15. [Mốc commit và tài liệu tham chiếu](#15-mốc-commit-và-tài-liệu-tham-chiếu)
16. [Checklist tiếp tục phiên làm việc](#16-checklist-tiếp-tục-phiên-làm-việc)

## 1. Tóm tắt cần đọc trước

- **Tên sản phẩm hiện tại: Minda.** Đây là hệ thống hỗ trợ lập biên bản cuộc họp tiếng Việt, có chép lời đa nguồn, người nói, mẫu tài liệu, biên bản có nguồn đối chiếu và DOCX chỉnh sửa được.
- **Bản web mới nằm tại `web_app/` ngay trong thư mục gốc dự án.** Đây là worktree Git riêng, có mã pipeline được checkout theo nhánh web; không phải thư mục frontend đơn lẻ.
- **Bản web mới đã triển khai**, gồm đăng nhập/phân quyền thật, user/admin, MongoDB, worker riêng, OCR, preview Word, lịch sử và backup/restore. Mobile được hoãn.
- **Luồng sử dụng hiện tại:** nhập mẫu → rà soát mẫu → tạo cuộc họp và tải audio → chạy chép lời → rà soát transcript/người nói → tạo biên bản → đối chiếu/sửa trường → xem trước → tải DOCX.
- **Bản demo cũ cổng 8000 và web mới cổng 8010 là hai ứng dụng riêng.** Không dùng trạng thái hoặc tài liệu của một ứng dụng để mặc định kết luận về ứng dụng còn lại.
- **LLM/E5/FCM đã chạy thật bằng model cache local; chưa fine-tune.** Dữ liệu transcript–biên bản do người kiểm sửa vẫn chưa có thành một tập độc lập.
- **Vấn đề chất lượng gần nhất người dùng nêu:** lời văn DOCX còn giống văn nói, thường chỉ thay xưng hô. Đã nghiên cứu và thảo luận phương pháp cải tiến; chưa triển khai bước cấu trúc ý nghĩa rồi viết thành đoạn.
- **Phần nói chồng hiện chưa có transcript tự động đầy đủ:** luồng đang dùng giữ audio và đánh dấu cần kiểm tra, bỏ qua separation/identity/ASR cho vùng overlap.
- **Tình trạng cổng quan sát lúc lập file:** không thấy listener trên 8000, 8010, 5173; MongoDB có listener tại `127.0.0.1:27017` và `[::1]:27017`. Đây là quan sát cổng, không xác nhận mọi worker nền đều đã dừng.
- **Mốc mã trước khi thêm tài liệu này:** checkout gốc `e033939`, nhánh web `27c67aa`. Những kết quả kiểm thử dưới đây có ngày và phạm vi riêng, không phải một lần nghiệm thu mới ngày 22/10.
- **Trạng thái khi chuyển hội thoại:** công việc hiện tại là bàn giao file context này. Chưa có yêu cầu triển khai phương pháp biên tập mới; hội thoại tiếp theo cần tiếp nhận yêu cầu mới của người dùng trước khi sửa tính năng.

## 2. Yêu cầu và quyết định đã chốt

### 2.1. Phạm vi sản phẩm

1. Hỗ trợ bản ghi cuộc họp tiếng Việt từ một hoặc nhiều thiết bị; người dùng có thể cung cấp hồ sơ giọng.
2. Nhận mẫu DOC/DOCX, PDF có chữ, PDF scan và ảnh. **Đầu ra chính luôn là DOCX chứa chữ/bảng có thể chỉnh sửa**, không chỉ chèn ảnh nguyên trang vào Word.
3. **Biên bản chi tiết:** giữ nguyên đề mục có sẵn và điền vào đúng vùng của mẫu.
4. **Biên bản tổng quát:** giữ cấu trúc ngoài vùng nội dung; trong vùng nội dung, tổ chức thành chủ đề từ cuộc họp.
5. Bảo toàn các ý công việc, điều kiện, đề xuất, ý kiến phản đối, quyết định và diễn biến thay đổi. Có thể bỏ từ đệm và lặp cơ học; không mặc định tóm tắt mạnh làm mất ý.
6. Giữ tên, số, ngày, chủ thể, phủ định, mức chắc chắn và trạng thái đề xuất/quyết định. Thiếu thông tin thì cần để trống hoặc rà soát, thay vì suy đoán để điền đủ mẫu.
7. Cho chọn cấu hình trình bày Nghị định 30/2020/NĐ-CP hoặc Hướng dẫn 05-HD/VPTW ngày 27/5/2026, theo tính năng đã triển khai.
8. Có đăng nhập và phân quyền thật trong prototype; tách khu vực người dùng và admin.
9. Chỉnh biên bản theo trường/nội dung, đối chiếu transcript và xem trước tài liệu. Chưa chọn xây dựng trình soạn thảo toàn trang giống Word trong web.
10. Database ứng dụng mới dùng **MongoDB**. Backend tổ chức theo module để dễ tìm và sửa thủ công.
11. Giữ khả năng chạy của pipeline/CLI/demo cũ; phát triển web tại worktree riêng. Các sửa lỗi shared core phải có phạm vi, commit và kiểm thử phù hợp.
12. Ưu tiên hoàn thiện web và chất lượng pipeline; ứng dụng Android/iOS để phát triển sau.

### 2.2. Cách làm việc và dữ liệu

- Người dùng làm dự án một mình; chưa có đội gán nhãn hoặc nguồn dữ liệu transcript–biên bản được người kiểm sửa.
- Đã đồng ý tải model từ Hugging Face vào cache và suy luận local. Cache vẫn là dữ liệu trên đĩa; chạy model vẫn cần RAM.
- Dữ liệu fine-tune được hoãn; hiện dùng dữ liệu có sẵn để kiểm thử và xác định lỗi trước.
- Người dùng từng yêu cầu commit cho các đợt triển khai để dễ quản lý. Riêng lần bàn giao context này, người dùng yêu cầu chỉ tạo một file và không commit. Khi có công việc triển khai tiếp theo, đối chiếu yêu cầu hiện hành; không gộp file/thay đổi ngoài phạm vi.
- Thay đổi server theo yêu cầu cụ thể. Việc đọc context hoặc cập nhật tài liệu không phải yêu cầu tự mở server.
- Các file tài liệu bàn giao là bối cảnh và lịch sử; trạng thái hiện tại cần đối chiếu mã, cấu hình và yêu cầu mới nhất trong hội thoại.

## 3. Thư mục, Git và môi trường

### 3.1. Các vị trí quan trọng

| Thành phần | Vị trí tuyệt đối |
| --- | --- |
| Thư mục gốc/checkout cũ | `/Users/thien/Documents/School/Luận văn` |
| Toàn bộ bản web mới | `/Users/thien/Documents/School/Luận văn/web_app` |
| Frontend | `/Users/thien/Documents/School/Luận văn/web_app/apps/web` |
| Backend mới | `/Users/thien/Documents/School/Luận văn/web_app/src/meeting_backend` |
| Pipeline dùng bởi web mới | `/Users/thien/Documents/School/Luận văn/web_app/src/meeting_pipeline` |
| Dữ liệu web mặc định | `/Users/thien/Documents/School/Luận văn/web_app/data/app` |
| Dữ liệu/evaluation pipeline cũ | `/Users/thien/Documents/School/Luận văn/data` |
| Worktree path cũ, hiện là symlink | `/Users/thien/.codex/worktrees/web-mongodb-upgrade/Luận văn` → `web_app` ở trên |

```text
Luận văn/
├── src/meeting_pipeline/           # Core/CLI/demo trong checkout gốc
├── configs/, scripts/, tests/
├── data/                           # Cache và kết quả pipeline cũ
├── .venv/, .venv-llm/
├── PROJECT_CONTEXT_HANDOFF_2026-10-22.md
└── web_app/                        # Worktree riêng của bản web mới
    ├── apps/web/                   # React/TypeScript
    ├── src/meeting_backend/        # API, MongoDB, worker, OCR
    ├── src/meeting_pipeline/       # Bản core tại nhánh web
    ├── configs/backend.yaml
    ├── configs/default.yaml
    ├── configs/minutes.yaml
    ├── data/app/
    ├── docs/backend/
    ├── artifacts/contest-registration/minda-brand/
    └── .venv-backend/
```

### 3.2. Ranh giới Git

- Checkout gốc: nhánh `codex/llm-fcm-minutes`, HEAD trước tài liệu này là `e033939b60a5507ffe9bd2b7b4675cd78f0a58d5`.
- Worktree web: nhánh `codex/web-mongodb-upgrade`, HEAD `27c67aa01e53e046388e195da9a329b4376f2e4a`.
- `web_app` được loại khỏi danh sách file của checkout gốc qua Git exclude. Chạy Git từ đúng workdir khi sửa web; không `git add` theo thư mục gốc rồi kỳ vọng đưa mã web vào nhánh gốc.
- Trước lần tạo file context này, worktree web sạch. Checkout gốc có sẵn một file untracked cần giữ nguyên:
  `docs/PLAN_FIX_SPEAKER_MULTI_SOURCE_HIGH_RISK_2026-10-03.md`.
- File kế hoạch untracked trên không thuộc đợt cập nhật context. Không coi nó là file rác hoặc tự đưa vào commit.
- Hai checkout chia sẻ repository Git nhưng có working tree/nhánh khác nhau. Một sửa đổi file trong checkout này không tự cập nhật file cùng tên trong checkout còn lại.

### 3.3. Runtime và symlink cần giữ

Trong `web_app` hiện có:

- `.venv-backend/`: môi trường Python riêng của backend mới.
- `.venv` → môi trường `.venv` ở checkout gốc.
- `.venv-llm` → môi trường `.venv-llm` ở checkout gốc.
- `data/model_cache` → `data/model_cache` ở checkout gốc.

Không xóa checkout gốc với giả định web đã hoàn toàn độc lập về runtime/cache. Lần kiểm tra 22/10 xác nhận import bằng `.venv-backend/bin/python` trỏ đúng vào hai package dưới `web_app/src/`.

Môi trường đích hiện tại là macOS Apple Silicon. Hội thoại trước ghi máy phát triển MacBook Air M4, RAM thống nhất 16 GB; đây không phải benchmark phần cứng mới trong lần tạo context này.

## 4. Kiến trúc và mã nguồn

### 4.1. Công nghệ đang dùng

| Lớp | Thành phần |
| --- | --- |
| Frontend | React 19, TypeScript, Vite 7, React Router, TanStack Query |
| UI | Tailwind CSS 4, Radix/shadcn, Sonner, Lucide, phông Geist đóng gói local |
| API | Python 3.11, FastAPI, Pydantic, PyMongo |
| Tác vụ nặng | Tiến trình worker riêng, queue/lease trong MongoDB, khóa theo data root |
| Dữ liệu ứng dụng | MongoDB + file artifact có checksum |
| Audio/ML | PyTorch, pyannote, SpeechBrain, Transformers, FFmpeg/ffprobe |
| LLM | Runtime MLX riêng, model 4-bit, snapshot ghim revision |
| Embedding/phân cụm | Transformers, NumPy, scikit-learn, scikit-fuzzy |
| DOCX/OCR/preview | python-docx/OOXML, pypdf, Tesseract, OpenCV, LibreOffice, Poppler |
| Legacy | CLI/demo cũ và SQLite vẫn tồn tại; MongoDB là nguồn trạng thái của web mới |

Luồng nhẹ: frontend → API `/api/v1` → service/repository → MongoDB.  
Luồng nặng: API enqueue → worker → adapter/processing → pipeline → kiểm artifact → publish version → cập nhật active pointer.

API mở trang/health không cần nạp Torch, MLX hoặc Transformers. Model được nạp trong tiến trình xử lý phù hợp.

### 4.2. Bố trí backend thực tế

```text
src/meeting_backend/
├── main.py                         # App, lifespan, middleware, routes, static
├── cli.py                          # Các lệnh vận hành có thật
├── core/                           # Settings, lỗi, logging, bảo mật
├── api/dependencies.py             # Current user/admin/database
├── modules/
│   ├── auth/  users/  meetings/  transcripts/  speakers/
│   └── templates/  minutes/  jobs/  system/
├── infrastructure/
│   ├── mongodb/                    # Collections, index, binding, repository
│   └── artifacts/                  # Store, media, backup/restore
├── integrations/                   # Audio, minutes, import legacy
├── processing/documents/           # Ingest, OCR, preview repair
└── worker/                         # Claim, lease, checkpoint, dispatch, publish
```

Một số module nhỏ giữ endpoint trong router; handler worker nằm tại adapter/processing tương ứng. Chưa tách `packages/api-client`; types/client frontend ở `apps/web/src/lib/`. Không chép nguyên cây file dự kiến trong tài liệu thiết kế rồi kết luận các file đó đã tồn tại.

### 4.3. File nên mở theo nhóm lỗi

| Vấn đề | File/nhóm file trong `web_app` |
| --- | --- |
| Đăng nhập, quyền, bootstrap | `src/meeting_backend/modules/auth/`, `api/dependencies.py`, `core/security.py` |
| Danh sách admin | `modules/meetings/admin.py`, `modules/users/router.py`, `apps/web/src/features/admin/` |
| Audio/speaker/ASR | `integrations/audio_pipeline.py`, `src/meeting_pipeline/pipeline/multi_source_fusion.py`, `asr/`, `speaker/` |
| Mất từ ở biên | `src/meeting_pipeline/asr/boundary_words.py`, `segment_asr.py`, `pipeline/stages/transcript_stitching.py` |
| Văn phong/giữ ý | `src/meeting_pipeline/minutes/text_engine.py`, `model_pipeline.py`, `model_runtime.py` |
| Gom cụm | `src/meeting_pipeline/minutes/topic_clustering.py`, `scripts/minutes_model_worker.py` |
| Mẫu/PDF/scan | `processing/documents/ingest.py`, `ocr.py`, `minutes/doc_parser.py`, `schema_mapper.py` |
| Facts, sửa trường, stale/version | `modules/minutes/`, `integrations/minutes_pipeline.py`, `minutes/service.py`, `fact_edits.py`, `transactions.py` |
| Thể thức/Word | `minutes/renderer.py`, `document_formatting.py`, `format_profiles.py` |
| Preview | `minutes/document_tools.py`, `visual_qa.py`, `processing/documents/previews.py`, frontend `components/common.tsx` |
| Job/backup/storage | `worker/`, `modules/jobs/`, `infrastructure/artifacts/`, `infrastructure/mongodb/` |
| Animation | `apps/web/src/motion.css`, `main.tsx`, `app.tsx`, `components/common.tsx`, `components/ui/dialog.tsx` |

## 5. Pipeline âm thanh, người nói và ASR

### 5.1. Luồng đang dùng bởi web

1. Nhận 1–8 bản ghi, kiểm file/media và lưu nguồn gốc.
2. Chuẩn hóa audio; ước lượng offset và drift để đồng bộ nhiều nguồn.
3. Chạy phân đoạn chung để lấy vùng lời nói và lượt người nói.
4. Trích embedding giọng, đối chiếu hồ sơ đã đăng ký hoặc gom người lạ thành nhãn ổn định.
5. Tạo clip/chunk ASR có ngữ cảnh, nhận dạng theo nguồn và kiểm chất lượng candidate.
6. Xử lý quyền sở hữu từ ở biên; căn hàng và dung hợp transcript theo preset.
7. Xuất timeline, transcript, hypothesis từng nguồn, trọng số, provenance và clip đối chiếu.

**Điểm cần ghi đúng:** luồng bình thường của `MultiSourceFusionPipeline` dùng **shared `pyannote/segmentation-3.0`** cho hoạt động lời nói/lượt nói. Cấu hình vẫn có `silero_vad` và có đường thay thế/legacy, nhưng không nên gọi toàn bộ backend web hiện tại là luồng chỉ dùng Silero.

### 5.2. Model/cấu hình âm thanh

- Phân đoạn: `pyannote/segmentation-3.0`.
- Embedding người nói: `speechbrain/spkrec-ecapa-voxceleb`.
- ASR mặc định: `vinai/PhoWhisper-medium`; có biến thể `small`.
- Web preset mặc định: `identity_method=prototype_cosine`, `fusion_method=F5_RULE_WEIGHTED_CORRECTED`, `asr_variant=medium`.
- CLI legacy có mặc định fusion khác (`F5_RULE_WEIGHTED`); luôn đọc preset/snapshot của job thay vì suy từ tên UI.
- Audio phân tích 16 kHz; giới hạn cấu hình nguồn tối đa 8, thời lượng pipeline tối đa 1.200 giây, upload 1.000.000.000 byte. Cần đọc thêm validation ở từng endpoint khi thay đổi giới hạn.
- Các mô-đun thử nghiệm/baseline MFCC/KNN, F0–F6, dữ liệu VIVOS và mô phỏng đa thiết bị vẫn tồn tại; không phải mọi baseline đều là preset mặc định đang chạy.

### 5.3. Người nói và overlap

- Người khớp hồ sơ đủ ngưỡng có thể được gắn danh tính; người lạ có cluster/label riêng.
- **“Chưa xác định” và “Nói chồng” là trạng thái, không phải hai người tham gia.** Không lấy chúng làm một danh tính hoặc tự thêm vào danh sách thành phần họp.
- Có code/cấu hình separation, nhưng **luồng web hiện tại bỏ qua separation, identity và ASR ở vùng overlap**, giữ một dòng cần kiểm tra cùng clip gốc; `asr_status=not_run`, có cảnh báo `overlap_skipped`.
- Vì vậy không tuyên bố đã chép đầy đủ phần nói chồng. LLM không có căn cứ để tự bù lời đã mất ở những vùng này.

### 5.4. Sửa mất từ ở biên đã triển khai

Policy: `interval_edges_seam_alignment_v1`.

- Giữ từ hợp lệ có midpoint trong core; ở biên ngoài, giữ thêm từ có khoảng thời gian giao core và nằm trong clip hợp lệ.
- Từ biên khôi phục có thể mang `time_status=uncertain`; không ép timestamp để tạo bằng chứng giả.
- Đối chiếu clip liền nhau cùng lượt/nhóm có phần audio chung; căn hàng chuỗi và gán một chủ sở hữu cho mỗi lần phát âm.
- Không ghép xuyên người nói hoặc overlap; không phục hồi candidate `failed/unreliable/empty/not_run` thành lời hợp lệ.
- Lưu `word_boundary_audit.json`, metadata policy và clip ngữ cảnh để kiểm tra.
- Đợt sửa này xử lý hậu kỳ/biên ASR, không phải thay đổi VAD. Giữ được thêm từ cũng có thể giữ thêm lỗi ASR; cần đánh giá deletion cùng insertion/substitution.

Người dùng đã từng phản ánh VAD tách quá nhiều đoạn, có lần 33 đoạn và mất từ. Sau đó đã yêu cầu tạm chưa sửa thêm VAD để ưu tiên LLM/phân cụm. Chưa có bằng chứng rằng mọi vấn đề phân đoạn đã được giải quyết.

### 5.5. Nhánh nghiên cứu, dữ liệu và baseline

- Core có mô-đun kiểm kê/chuẩn hóa VIVOS, tạo manifest, chia theo người nói và kiểm rò rỉ; tách mẫu đăng ký giọng khỏi các đoạn dùng đánh giá theo cấu hình thí nghiệm.
- Bộ sinh cuộc họp mô phỏng dùng phòng/đáp ứng xung và vị trí thiết bị; mô phỏng gain, lệch đồng hồ, drift, clipping, dropout và nhiễu. Mục tiêu là có ground truth để chẩn đoán từng thành phần.
- Các baseline fusion F0–F6 phục vụ đối chiếu nhiều cách chọn/căn hàng/tổng hợp hypothesis. Baseline oracle dùng reference để phân tích giới hạn, không phải lựa chọn có thể dùng khi suy luận cuộc họp chưa có đáp án.
- Có các nhóm đánh giá synchronization, VAD, speaker/diarization, ASR và fusion. WER/CER cần transcript chuẩn; DER cần nhãn người nói/thời gian chuẩn. Không có reference thì không tự sinh điểm chính xác.
- Cấu hình nghiên cứu nằm trong `configs/data/`, `simulation/`, `models/`, `fusion/`, `experiment/`, `evaluation.yaml` và `demo.yaml`. Chúng có thể mô tả đường nghiên cứu khác với preset web; phải ghi cấu hình thực sự dùng trong từng run.
- Dữ liệu tổng hợp, VIVOS và pilot TTS hỗ trợ phát triển có kiểm soát; chưa thay thế tập họp hành chính thật hoặc tập kiểm tra độc lập.

## 6. LLM, embedding và Fuzzy C-Means

### 6.1. Runtime hiện tại

Nguồn: `web_app/configs/minutes.yaml` và `requirements-minutes-mlx.txt`.

| Mục | Giá trị cấu hình |
| --- | --- |
| LLM | `mlx-community/Qwen3-4B-Instruct-2507-4bit` |
| Revision LLM | `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b` |
| Embedding | `intfloat/multilingual-e5-small` |
| Revision embedding | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| Python LLM | `.venv-llm/bin/python` |
| Cache | `data/model_cache/minutes/hub` |
| Token mỗi request | input 6.144; output 2.048 |
| Timeout | 240 giây |
| FCM runtime config | `m=1.3`, tự chọn tối đa 4 cụm, silhouette tối thiểu 0,08 |

- MLX/MLX-LM được ghim trong requirements; generate dùng temperature 0. Chưa fine-tune.
- Chuẩn bị weights một lần bằng script; inference đọc snapshot local, bật chế độ offline. API tạo biên bản không tự tải weights.
- Runtime LLM tách với backend/audio; giải phóng subprocess sau phiên xử lý. Có khóa tránh nhiều tiến trình sử dụng LLM đồng thời.
- E5 dùng tiền tố `query:`, masked mean pooling và chuẩn hóa L2; vector 384 chiều. Đầu vào vượt giới hạn 512 token của embedding báo lỗi, không âm thầm cắt.

### 6.2. Pipeline biên bản đang có

1. Đọc mẫu thành graph/anchors/schema; giữ ID, nhãn và vùng sửa được.
2. Tạo `MeaningUnit` từ lượt có transcript hợp lệ: tách theo dấu câu rồi chia chunk tối đa 65 từ cách bằng khoảng trắng. Đây chưa phải một cấu trúc sự kiện đã phân tích đầy đủ.
3. Tùy chọn sửa transcript tối thiểu, lưu câu gốc/đề xuất/quyết định chấp nhận.
4. Phân loại trường của mẫu, chuẩn hóa metadata tường minh và trích nội dung có ID nguồn.
5. Chi tiết: ánh xạ nội dung vào đề mục sẵn; không dùng FCM thay hệ đề mục.
6. Tổng quát: chọn đúng một vùng nội dung → E5 → FCM hoặc baseline một nhóm → LLM viết nội dung và đặt tên chủ đề.
7. Kiểm ID, số, tên, phủ định, điều kiện, trạng thái; render và áp dụng thể thức; xuất artifact/báo cáo.

Tổng quát cần bật LLM. Nếu có nhiều vùng nội dung khả dĩ phải chọn `content_field_id`, không tự chọn trường mơ hồ. Chi tiết có chế độ rule-only.

### 6.3. FCM thực tế làm gì?

- Chuẩn hóa vector. Nếu dữ liệu đủ lớn, PCA tối đa 12 chiều dùng cho fit; silhouette cosine được tính trên embedding gốc.
- Tự thử số cụm từ 2 đến giới hạn cấu hình/lượng đơn vị; mỗi số cụm chạy ba seed `0, 17, 42`.
- Kiểm cụm rỗng/quá nhỏ/co tâm, silhouette, độ ổn định ARI và mức membership phân biệt; không đạt thì dùng một nhóm.
- Đường tự chọn yêu cầu stability từ 0,6 và silhouette từ 0,08 theo cấu hình hiện tại. Ép số cụm có chính sách chấp nhận khác, không coi đó là cấu hình đã tối ưu.
- Mỗi đơn vị có **một nhóm chính**, xếp nhóm theo lần xuất hiện đầu tiên; giữ thứ tự đơn vị trong nhóm. Membership được lưu để chẩn đoán mơ hồ.
- Membership **không phải xác suất chủ đề đúng hoặc độ tin cậy của fact**.
- FCM gom nhóm; LLM đề xuất tên chủ đề từ nội dung nhóm. Tiêu đề hiện có thể còn chung chung, nhất là khi nhóm dài hoặc trộn ý.

### 6.4. Vì sao lời văn hiện chưa tự nhiên?

Đã xác minh tại `text_engine.py`, hàm `write_general`:

- Prompt yêu cầu **mỗi item đúng một `unit_id`**, cấm gộp các đơn vị, không tóm tắt/bỏ câu; mỗi item tối đa ba câu.
- Sau khi viết từng phần, hệ thống nối các item thành nội dung. Chưa có bước viết lại toàn bộ đoạn theo cấu trúc lập luận.
- Kiểm tra bảo thủ có thể trả về nguồn khi mất từ khóa phủ định/đề xuất/điều kiện, thay số/tên, thêm “đã” hoặc “cam kết”. Lỗi batch/ID cũng có fallback về câu nguồn.
- Vì kiểm tra có phần dựa trên từ khóa, một cách diễn đạt hợp lệ cũng có thể bị từ chối. Fallback bảo vệ nội dung nhưng giữ lại dấu vết văn nói.
- **Đủ ID không chứng minh đủ nghĩa.** Một item có thể còn lủng củng, bỏ nghĩa hoặc thêm nghĩa dù đã qua kiểm tra hình thức.
- Ở ba bản general đang lưu được kiểm tra trong cuộc thảo luận trước: lần lượt 5/16, 6/16 và 5/14 đơn vị giống nguyên nguồn; chưa phân loại từng fallback là cần thiết hay quá bảo thủ.

### 6.5. Artifact phục vụ tra lỗi

Trong một bộ kết quả minutes có thể có:

- `minutes/corrections.json`, `corrected_transcript.json`.
- `minutes/topics.json`: đơn vị, membership, nhóm chính, tên mục, câu biên tập, ID coverage.
- `minutes/model_report.json`: model/revision, lời gọi, cảnh báo, thời gian, bộ nhớ được đo.
- `minutes/configuration.json`, schema/facts và các báo cáo định dạng.
- `exports/completed.docx`, manifest, ZIP và preview.

Cache phản hồi/embedding có thể chứa transcript; không coi cache là dữ liệu đã được duyệt để huấn luyện hoặc là dữ liệu công khai. Thời gian cache hit không đại diện tốc độ inference mới.

## 7. Biểu mẫu, OCR, DOCX và preview

### 7.1. Các đầu vào đã triển khai ở web mới

| Đầu vào | Cách xử lý chính |
| --- | --- |
| DOCX | Đọc cấu trúc Word, paragraph/bảng/anchors trên bản sao |
| DOC | Chuyển bằng công cụ tài liệu rồi parse |
| PDF có chữ | Đọc text, tái dựng phần văn bản thành DOCX |
| PDF scan/ảnh | Render nếu cần, OCR `vie+eng`, phát hiện bảng kẻ bằng OpenCV, tái dựng DOCX |

- PDF/ảnh có bước đối chiếu và duyệt mẫu; chưa duyệt thì chưa dùng tạo biên bản.
- Khi sửa chữ trong mẫu: lưu → nhận diện lại trường → duyệt, để schema khớp văn bản.
- Giới hạn đã ghi trong bản triển khai: tối đa 50 trang PDF, ảnh 40 megapixel.
- Chưa có benchmark OCR đại diện; scan mờ, nhiều cột, bảng gộp phức tạp và chữ viết tay chưa được bảo đảm. Điểm OCR nội bộ không phải xác suất đúng của trường.
- Bảo toàn chữ đề mục từ scan còn phụ thuộc độ đúng OCR và bước duyệt.

### 7.2. Thể thức và xuất Word

- Hệ thống có profile `nd30_2020` và `hd05_2026`; metadata ban hành/ký được tách khỏi ngày họp, không tự suy ngày ban hành.
- Renderer điền trên bản sao; formatter điều chỉnh style, lề, header/footer, khối ký và số trang theo profile đã chọn.
- Đổi thể thức dùng facts đang lưu, không chạy lại ASR/LLM.
- Đề mục nội dung cần giữ theo chính sách mẫu; hình thức và số trang có thể thay đổi khi chuẩn hóa thể thức.
- Kiểm kỹ thuật/`checks_passed` không phải chứng nhận rằng toàn bộ tài liệu đúng ngữ nghĩa hoặc đủ điều kiện ban hành. Xác nhận rà soát không phải chữ ký số.
- Các tài liệu 10/10 nói chỉ sửa `word/document.xml` mô tả bước điền trước đó; sau cập nhật formatter 15/10 có thay đổi phần style/header/footer liên quan.

### 7.3. Preview đã sửa

- DOCX → PDF qua LibreOffice → PNG từng trang qua Poppler.
- Trước đây preview hỏng khi công cụ chỉ tìm thấy trong runtime Codex; đã bổ sung resolver dùng PATH và vị trí cài chuẩn, có CLI khôi phục preview cũ.
- Máy chạy web/worker cần LibreOffice/Poppler riêng; Word xuất được không đồng nghĩa preview đã có.
- Giao diện có khung giữ tỷ lệ, tải ảnh, trạng thái lỗi và thử lại; hiện dần sau khi ảnh tải thành công.
- `repair-previews --apply` bổ sung ảnh/metadata, giữ DOCX/ZIP/facts và ID phiên bản gốc.

## 8. Giao diện người dùng và quản trị

### 8.1. Người dùng

- Dashboard, danh sách/tìm kiếm cuộc họp, wizard tạo cuộc họp, thùng rác, cài đặt.
- Quản lý mẫu riêng, mẫu dùng chung được cấp quyền; xem/duyệt OCR và trường mẫu.
- Hồ sơ giọng, mẫu enrollment, chọn người tham gia.
- Workspace có thông tin, nguồn, transcript, người nói, biên bản và lịch sử.
- Nghe clip, tìm/sửa transcript, đổi nhãn; nhận cảnh báo khi biên bản cũ stale.
- Chọn chi tiết/tổng quát, bật LLM/FCM, chọn thể thức, sửa theo trường/danh sách, đối chiếu căn cứ và xem trước DOCX.
- Xem/đối chiếu/khôi phục lịch sử. Khôi phục tạo phiên bản mới.
- Xuất DOCX và gói bằng chứng; chỉnh tiếp bằng Word.

Routes chính: `/`, `/meetings`, `/meetings/new`, `/meetings/:id`, `/templates`, `/templates/:id`, `/voices`, `/trash`, `/settings`.

### 8.2. Quản trị

- Tổng quan, tài khoản, metadata cuộc họp toàn hệ thống, job/log, cấu hình/preset, mẫu dùng chung, backup/restore, đánh giá và audit.
- Routes: `/admin`, `/admin/users`, `/admin/meetings`, `/admin/jobs`, `/admin/models`, `/admin/templates`, `/admin/backups`, `/admin/experiments`, `/admin/audit`.
- Bản sửa 17/10 đã thêm danh sách cuộc họp toàn hệ thống, bộ lọc owner/trạng thái/trash, liên kết từ thẻ số liệu và ô tìm kiếm admin.
- Danh sách tài khoản có lọc vai trò/trạng thái, nhãn tài khoản khóa rõ ràng, trạng thái tải/rỗng/lỗi và cập nhật mỗi 5 giây.
- **Quyền admin quản trị metadata không tự cấp quyền đọc workspace, transcript hoặc file riêng của người dùng khác.** Không sửa ownership chỉ để làm nút xem nội dung xuất hiện.

### 8.3. Xác thực và quyền

- Bootstrap tạo admin đầu tiên khi database chưa có user; không có tài khoản/mật khẩu mặc định.
- Mật khẩu băm Argon2; session token opaque ngẫu nhiên, chỉ lưu hash token/CSRF trong database.
- Cookie session HttpOnly, SameSite Strict. Các endpoint đã xác thực có thay đổi dữ liệu yêu cầu CSRF; middleware kiểm Origin khi request gửi header này. Setup/login không dùng cùng cơ chế kiểm CSRF của endpoint đã xác thực. Session mặc định 24 giờ; có kiểm expiry và TTL index.
- Local HTTP đang dùng `cookie_secure=false`; triển khai HTTPS sau này cần cấu hình tương ứng.
- Resource riêng kiểm `owner_id`; sửa dữ liệu dùng revision/CAS và kiểm busy/trash. Không log/commit password, token hoặc file credential.

### 8.4. Thương hiệu và animation

- Tên Minda., tiêu đề tab và favicon đã cập nhật trong commit `88c6283`.
- Logo là biểu tượng sóng âm trên ô bo góc tối; chữ Minda và dấu chấm xanh. Icon lấy từ hệ Lucide, có giấy phép trong SVG nguồn; không mô tả đây là hình vẽ độc quyền mới.
- Commit `27c67aa`: hiệu ứng trang/tab, hover, wizard theo hướng, dấu tích, modal, preview, logo một lần khi hover/focus và menu mobile.
- Có `prefers-reduced-motion`; key route theo pathname, không dựng lại trang mỗi lần polling; giữ form, caret và focus.

## 9. Database, phiên bản, bằng chứng và worker

### 9.1. Nguồn trạng thái và cấu hình

Mặc định trong `configs/backend.yaml`:

```yaml
mongo_uri: mongodb://127.0.0.1:27017
mongo_database: meeting_app_dev
data_dir: data/app
pipeline_config: configs/default.yaml
model_cache_dir: data/model_cache
web_dist: apps/web/dist
session_hours: 24
cookie_secure: false
max_sources: 8
lease_seconds: 90
```

- Biến `MEETING_APP_*` ghi đè YAML; path tương đối được tính từ root `web_app`.
- Database phải có prefix `meeting_app_` và có `storage_binding` tới đúng data root. Đổi DB cần đi cùng root phù hợp.
- SQLite legacy chỉ dùng cho luồng cũ/import; không có hai nguồn trạng thái song song cho app mới.
- Các collection: `users`, `sessions`, `meetings`, `sources`, `speakers`, `templates`, `jobs`, `transcript_versions`, `transcript_segments`, `template_versions`, `minutes_versions`, `artifacts`, `audit_events`, `settings`, `schema_migrations`, `experiments`.

### 9.2. File lớn và phiên bản

```text
web_app/data/app/
├── uploads/
├── pipeline/
├── document_versions/
├── templates/
├── voices/
├── imported/
├── previews/
├── staging/
├── backups/
├── restores/
└── logs/
    ├── api.log
    └── jobs/<job-id>/worker.log
```

- MongoDB lưu metadata/ID/tham chiếu; audio, Word, preview và ZIP nằm trong artifact root.
- Artifact có checksum và quyền; tải qua ID có kiểm tra, không phục vụ thẳng toàn thư mục dữ liệu.
- Version được tạo bất biến; active pointer công bố bản đang dùng. Manifest/ZIP mới được gắn các ID ứng dụng thực.
- Sửa transcript làm minutes stale. Chỉnh thể thức không làm mới nội dung. Tạo lại biên bản giữ các trường sửa tay hợp lệ còn cùng ID.
- Đổi nguồn/hồ sơ tham gia cần chạy lại audio; không lấy biên bản cũ làm kết quả hợp lệ sau thay đổi đầu vào.

### 9.3. Worker

- Queue bền vững trong MongoDB; snapshot preset khi enqueue.
- Một job nặng tại một thời điểm cho mỗi data root; dùng file lock, lease, heartbeat và checkpoint.
- Hủy inference có thể phải chờ công đoạn đang chạy. UI không nên mô phỏng phần trăm không có căn cứ.
- Worker cũ mất lease không được publish; recovery xét resource đã công bố hay chưa để đánh dấu succeeded/interrupted.
- Không phải transaction phân tán MongoDB/filesystem: tiến trình bị kill có thể để file staging/ứng viên chưa active.

## 10. Mở, dừng, kiểm tra và khôi phục

### 10.1. Mở nhanh web mới trên máy đã chuẩn bị

```bash
cd "/Users/thien/Documents/School/Luận văn/web_app"
.venv-backend/bin/python scripts/backend/run_local.py
```

Mở `http://127.0.0.1:8010`. Launcher dùng cùng Python để chạy API và worker. **Ctrl+C ở terminal launcher dừng cả hai.** Đóng tab trình duyệt không dừng server. Lệnh này không mở demo cũ cổng 8000.

Chạy riêng khi cần tra lỗi, cùng cấu hình ở cả hai terminal:

```bash
# Terminal A
.venv-backend/bin/python -m meeting_backend.cli serve --port 8010
```

```bash
# Terminal B
.venv-backend/bin/python -m meeting_backend.cli worker
```

Dừng bằng Ctrl+C ở từng terminal. MongoDB là tiến trình riêng; dừng launcher không đồng nghĩa dừng MongoDB.

### 10.2. Cài đặt hoặc build khi cần

Python dự án yêu cầu 3.11 (`>=3.11,<3.12`); Node theo yêu cầu Vite, tài liệu dự án ghi 22.12+/24. Các binary: FFmpeg/ffprobe, Tesseract, LibreOffice, Poppler.

```bash
# Checkout mới; máy hiện tại đã có môi trường tương ứng
UV_PROJECT_ENVIRONMENT=.venv-backend uv sync --locked --extra backend --extra ml --extra evaluation --extra dev
npm --prefix apps/web ci
npm --prefix apps/web run build
```

```bash
# Chuẩn bị OCR một lần khi thiếu cache; lệnh này có tải mạng
.venv-backend/bin/python -m meeting_backend.cli prepare-ocr

# Kiểm môi trường/capabilities với MongoDB đang hoạt động
.venv-backend/bin/python -m meeting_backend.cli doctor
```

`doctor` khởi tạo kết nối/index/migration qua CLI, không phải phép kiểm filesystem thuần túy. Không dùng nó với cấu hình DB/root chưa xác định.

```bash
# Chuẩn bị LLM/E5 khi thiếu cache; không cần chạy lại mỗi lần mở web
.venv/bin/python scripts/prepare_minutes_models.py

# Sau sửa frontend
npm --prefix apps/web run build

# Development frontend tùy chọn: 5173 proxy /api về 8010
npm --prefix apps/web run dev
```

Runtime LLM có requirements riêng: `requirements-minutes-mlx.txt`. Không tự thay bản Torch/ASR hoặc cài lại mọi môi trường chỉ vì sửa UI.

### 10.3. Preview

```bash
# Trên máy macOS mới nếu chưa có công cụ
brew install poppler
brew install --cask libreoffice

# Xem danh sách phiên bản thiếu preview
.venv-backend/bin/python -m meeting_backend.cli repair-previews

# Sau khi các job đang chạy đã hoàn tất
.venv-backend/bin/python -m meeting_backend.cli repair-previews --apply
```

### 10.4. Nhập kết quả cũ

```bash
.venv-backend/bin/python -m meeting_backend.cli import-run /duong/dan/run --username tai_khoan_nhan --dry-run
.venv-backend/bin/python -m meeting_backend.cli import-run /duong/dan/run --username tai_khoan_nhan

.venv-backend/bin/python -m meeting_backend.cli import-legacy /duong/dan/data/meetings --username tai_khoan_nhan --sqlite /duong/dan/app.sqlite --dry-run
```

Importer giữ nguồn, kiểm hash, xử lý idempotency theo nội dung/owner. SQLite mở chỉ đọc để lấy metadata; không phát lại tài khoản hoặc queue cũ. Hồ sơ giọng được tạo qua luồng có ownership của web mới.

### 10.5. Backup và restore

- Thực hiện qua **Quản trị → Sao lưu dữ liệu**, hoặc API job đã xác thực; **chưa có lệnh backup/restore CLI**.
- Backup gồm metadata, file được tham chiếu, sidecar và voice registry; không gồm model weights/cache, log, session hoặc queue cũ.
- Restore kiểm cấu trúc/checksum, tạo `meeting_app_restore_<id>` và root mới, không ghi đè DB hiện tại.
- Sau restore: dừng API/worker, dùng đúng hai giá trị database/data root trả về, mở lại và đăng nhập mới. Restore không tự chuyển server đang chạy sang dữ liệu khôi phục.

```bash
export MEETING_APP_MONGO_DATABASE=meeting_app_restore_<id>
export MEETING_APP_DATA_DIR=/duong/dan/root/duoc/tra/ve
.venv-backend/bin/python scripts/backend/run_local.py
```

Hai giá trị trên là placeholder, không chạy nguyên mẫu. API backup/restore: `POST /api/v1/admin/backups`, `POST /api/v1/admin/backups/upload`, `POST /api/v1/admin/restore`.

### 10.6. Tra lỗi nhanh

| Hiện tượng | Kiểm trước |
| --- | --- |
| Không mở 8010 | Workdir, API/worker, build `apps/web/dist`, MongoDB, `data/app/logs/api.log` |
| Job ở queued | Worker và đúng cặp DB/root, lock/lease, log theo job |
| Không có preview | LibreOffice/Poppler, `preview_tools`, ảnh từng trang; cân nhắc repair |
| Admin không thấy danh sách | Mã/build sau `e7528f9`, `/admin/users`, `/admin/meetings`, bộ lọc/trash/owner |
| Admin không mở workspace của user khác | Đối chiếu chính sách ownership; không tự nới quyền |
| Không chọn được PDF/scan | Trạng thái duyệt mẫu và schema sau sửa chữ |
| 409 | Revision/busy/stale; tải bản mới, không lưu đè tab khác |
| DOCX còn lời nói nguyên văn | `model_report`, fallback, `topics.json`, tùy chọn LLM, trường sửa tay được giữ |
| Mất lời/tên người trùng | Timeline, source hypotheses, boundary audit, speaker state/cluster; tách nguyên nhân VAD, ASR, fusion và UI |

### 10.7. CLI và demo cũ

Nếu cần đối chiếu luồng cũ, chạy từ **checkout gốc**, trong terminal riêng:

```bash
cd "/Users/thien/Documents/School/Luận văn"
.venv/bin/meeting-pipeline serve --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`; Ctrl+C dừng demo này. Dữ liệu kết quả legacy nằm theo cấu trúc `data/meetings/<meeting>/runs/<run-id>/`; đọc README/CLI help trước khi chạy một job mới hoặc benchmark. Bản web MongoDB mới vẫn dùng root và database riêng.

## 11. Bằng chứng kiểm thử và phạm vi kết luận

Các con số dưới đây là kết quả đã ghi ở các mốc tương ứng. **Không có lần chạy lại toàn bộ test/model ngày 22/10 trong công việc tạo file này.**

| Mốc | Kết quả đã lưu | Giới hạn |
| --- | --- | --- |
| 10/10, LLM/FCM | 8 ca trên transcript tham chiếu/ASR; sáu ca LLM đạt 5/5 ô metadata đã chọn; xem 18 trang của 6 DOCX | Một kịch bản TTS/một họ mẫu dùng phát triển; không phải độ chính xác toàn biên bản |
| 10/10, sửa transcript bằng LLM | Nhận 0 thay đổi; WER pilot 16,03% → 16,03% | Chưa quan sát cải thiện ASR ở pilot này |
| 15/10, sửa biên | 231 unit/integration tests; smoke 10 từ WER 30% → 0% | Ca tái hiện ngắn; không đại diện họp dài |
| 15/10, replay FPT | WER 7,44% → 4,20% | Hậu xử lý candidate đã lưu, không phải suy luận audio mới |
| 15/10, replay VIVOS | WER 16,62% → 8,31% | Insertion tăng 1 → 7, substitution tăng 9 → 14 |
| 17/10, web | 274 tests passed, 3 deprecation warnings; lượt sau chuyển thư mục 67,95 giây | Snapshot kiểm thử ngày 17/10 |
| 17/10, model thật qua web | Audio 11,1875 giây/10 từ WER=CER=0; enrollment giọng thành công | Smoke chức năng ngắn |
| 17/10, biên bản qua web | 37 facts, 4 cụm, 8 lần gọi model, preview 3 trang | Xác nhận luồng chạy, chưa nghiệm thu văn phong/semantic completeness |
| 17/10, chuyển thư mục | Kiểm lại 51 artifact, 7 phiên bản Word và build | Không thay dữ liệu nguồn |
| 17/10, sửa preview | Chrome 14 trang; mẫu/biên bản thử nghiệm đều 2 trang. Phục hồi dữ liệu dev: mẫu 2 trang, biên bản 3 trang; 4 file gốc giữ hash | Hai phép kiểm thử và phục hồi riêng |
| 17/10, sửa admin | 4 ca pytest chọn lọc; browser smoke 13 trang; danh sách/lọc/polling/quyền đạt | Tài liệu và report có phạm vi riêng |
| 18/10, animation | Build/format/Ruff script đạt; Chrome 15 trang và 7 nhóm motion đạt | Không có bằng chứng chạy lại toàn bộ 274 tests ngày 18/10 |

Ruff, TypeScript/Vite, Prettier và kiểm quyền/restore đã được ghi trong các tài liệu nghiệm thu. `npm audit` không báo lỗ hổng tại lần kiểm 17/10; không diễn giải đó là kết quả quét bảo mật hiện tại.

### 11.1. Vị trí evidence

- AI/evaluation cũ nằm ở **checkout gốc**:
  - `data/evaluations/llm_fcm_20261010_release/`.
  - `data/evaluations/asr_boundary_fix_20261015__h293dpp/`.
  - `data/evaluations/docx_format_20261015/`.
- Evidence web nằm trong **`web_app`**:
  - `data/evaluations/docx-preview-fix-20261017/report.json`.
  - `data/evaluations/admin-lists-fix-20261017/report.json`.
  - `data/evaluations/motion-20261018/report.json` và ảnh.
  - Các thư mục QA cũ dưới `data/app-qa/` theo tài liệu nghiệm thu.

Không nhầm các đường dẫn có cùng tên `data/evaluations` giữa hai checkout. Không cộng peak MLX với RSS thành một chỉ số RAM tổng; không dùng cache hit làm tốc độ suy luận.

### 11.2. Lệnh kiểm thử khi phát triển tiếp

```bash
cd "/Users/thien/Documents/School/Luận văn/web_app"
PYTHONPATH=src .venv-backend/bin/python -m pytest tests/unit tests/integration tests/backend -q
.venv-backend/bin/python -m ruff check --no-cache src/meeting_backend tests/backend
npm --prefix apps/web run build
npm --prefix apps/web run format:check
```

Backend tests dùng MongoDB thật với DB/root UUID riêng; không trỏ test vào dữ liệu trình diễn. Model/dataset/browser là các gate riêng, không tự tải model khi chạy test nhanh.

Browser smoke: `scripts/backend/browser_smoke.py`, nhận `--username` và mật khẩu từ env/file credential local; có `--meeting-id`, `--template-id`, `--check-motion`. Không ghi hoặc commit credential. Xem QUICKSTART để dùng cờ cụ thể.

## 12. Hạn chế và hướng công việc tiếp theo

### 12.1. Hạn chế đang biết

1. **Văn phong DOCX:** còn câu nguyên nguồn, lời lặp và biên tập chưa trọn vẹn; per-unit writer hạn chế liên kết đoạn.
2. **Độ đúng ngữ nghĩa:** kiểm số/tên/từ khóa là heuristic, chưa phát hiện mọi lỗi. Có thể từ chối sửa hợp lệ hoặc cho lọt suy diễn.
3. **Chất lượng âm thanh:** chưa giải quyết mọi nguyên nhân phân đoạn/mất từ; phần overlap chưa được chép lời trong luồng hiện tại.
4. **Speaker:** hồ sơ/embedding/cluster cần thêm dữ liệu đánh giá; không coi unknown/overlap là người tham gia.
5. **FCM:** thông số đã thử trên pilot phát triển; chủ đề/tiêu đề có thể trộn/chung chung. Chưa chứng minh tốt hơn mọi baseline trên tập giữ riêng.
6. **Mẫu mới/OCR:** nhiều đề mục đặc thù, scan khó, bảng phức tạp/chữ tay chưa có benchmark đại diện.
7. **Dữ liệu:** chưa có bộ transcript–biên bản do người kiểm sửa để fine-tune hoặc đo khách quan trên miền hành chính.
8. **Vận hành:** prototype local, một job nặng/root, chưa benchmark tải nhiều người dùng, chưa deploy rộng hoặc có mobile native.

Các lỗi evidence/schema/stale được nêu trong audit trước UI ngày 17/10 có các bản sửa sau đó; phải đọc code và nghiệm thu web mới trước khi liệt kê chúng là lỗi chưa sửa hiện tại.

### 12.2. Hướng gần nhất đã thảo luận, chưa triển khai

Người dùng hiện tập trung vào lời văn đầu ra. Đề xuất đã nghiên cứu:

```text
Transcript có nguồn đối chiếu
  → Làm sạch văn nói và sửa lỗi có căn cứ
  → Phân tích các ý, chủ thể, thời gian, điều kiện và trạng thái phát biểu
  → Tổ chức ý theo đề mục/chủ đề, giữ liên kết hỏi–đáp/đính chính
  → Viết thành đoạn theo tiêu chí văn phong hành chính
  → Kiểm đủ ý và đúng nghĩa với nguồn, sửa có giới hạn
  → Render DOCX
```

**Chưa có trong code hiện tại:** semantic fact ledger, dialogue-act labeling, hợp nhất nhiều lượt thành đoạn theo kế hoạch ý, kiểm nghĩa độc lập hoặc bộ đánh giá A/B/C văn phong.

Phương án thử được đề xuất:

- A: pipeline hiện tại làm baseline.
- B: thêm tiêu chí và ví dụ văn phong, giữ quy trình hiện tại.
- C: thêm cấu trúc ý và cho phép viết theo đoạn; vẫn theo dõi đủ ý và nguồn bằng ánh xạ nhiều–nhiều.
- Chấm tách biệt độ tự nhiên, mạch lạc, văn phong hành chính, đầy đủ ý, đúng fact và công chỉnh sửa. Theo dõi riêng tên/số/ngày/phủ định, owner/due và đề xuất/quyết định.
- Thử trên model hiện có trước khi chọn fine-tune hoặc đổi model. Chưa có yêu cầu thực hiện C trong các lượt trao đổi gần nhất.

Không biến yêu cầu giữ đủ ý thành “tóm tắt thật ngắn”. Nếu một đề xuất bị rút hoặc deadline thay đổi, phải giữ diễn biến có ý nghĩa và trạng thái cuối có căn cứ.

### 12.3. Dữ liệu và fine-tuning về sau

- Có thể tạo dữ liệu theo hướng fact/kịch bản chuẩn → hội thoại → TTS/ASR → bản biên tập; thêm tên/số/ngày, phủ định, đổi deadline, phản đối, thiếu thông tin.
- Mẫu DOCX đã biết trường → PDF/ảnh biến đổi giúp thử OCR/schema, nhưng không thay tập scan thực tế.
- LLM hỗ trợ sinh cặp đúng/sai và ví dụ diễn đạt, sau đó lọc theo nguồn và rà soát. Output pipeline không tự trở thành nhãn chuẩn.
- Tách train/dev/test theo cuộc họp/kịch bản và họ mẫu trước khi sinh biến thể; giữ tập kiểm tra độc lập nhỏ có người rà.
- Quy mô pilot được thảo luận trước đây là gợi ý phát hiện lỗi, không phải ngưỡng dữ liệu khoa học bảo đảm fine-tune đủ tốt.
- LoRA/QLoRA/distillation chỉ là hướng mở khi có dữ liệu và đánh giá; khả năng inference không tự chứng minh khả năng training trên RAM 16 GB.

## 13. Nghiên cứu cải thiện lời văn đã thảo luận

Các bài được tra cứu trong cuộc hội thoại trước, không phải nghiên cứu thực nghiệm mới của dự án. Phần lớn đánh giá trên tiếng Anh hoặc miền khác; áp dụng vào hành chính tiếng Việt cần kiểm chứng.

| Hướng | Nguồn chính | Ý tưởng tham khảo |
| --- | --- | --- |
| Làm sạch văn nói | [DACL, LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.385/) | Dữ liệu disfluency tổng hợp, học từ dễ đến khó; chưa đủ cho tổ chức biên bản |
| Chức năng phát biểu | [DASum, IPM 2024](https://www.sciencedirect.com/science/article/pii/S0306457323003722) | Dùng dialogue acts để kết nối câu hỏi–trả lời và hiểu tương tác |
| Lập kế hoạch nội dung | [CoPERLex, Findings NAACL 2025](https://aclanthology.org/2025.findings-naacl.57/) | Cấu trúc sự kiện trung gian rồi sinh văn bản; nghiên cứu án lệ, không trực tiếp xác nhận chất lượng biên bản Việt |
| Chuyển phong cách giữ nghĩa | [STRAP, EMNLP 2020](https://aclanthology.org/2020.emnlp-main.55/) | Diễn đạt lại có kiểm soát và dữ liệu pseudo-parallel; kiểm cả nghĩa lẫn độ trôi chảy |
| Phản hồi và chỉnh sửa | [Self-Refine, 2023](https://arxiv.org/abs/2303.17651) | Viết nháp → nhận xét → sửa, không cần huấn luyện thêm; hiệu quả model 4B chưa đo |
| Đánh giá chi tiết | [FineSurE, ACL 2024](https://aclanthology.org/2024.acl-long.51/) | Kiểm từng câu và đối chiếu từng ý; tách faithfulness/completeness/conciseness |
| Học từ mô hình lớn | [Factual Dialogue Summarization via Learning from Large Language Models, COLING 2025](https://aclanthology.org/2025.coling-main.302/) | Sinh ví dụ đúng/sai và distillation/contrastive learning cho model nhỏ |

Tiêu chí văn phong đã đề xuất: khách quan, câu hoàn chỉnh, chủ thể rõ khi có căn cứ, thuật ngữ nhất quán, giảm lặp, giữ mức chắc chắn; không tự thêm mục đích/kết quả hoặc dùng “cuộc họp thống nhất” khi mới có đề xuất.

## 15. Mốc commit và tài liệu tham chiếu

### 15.1. Mốc triển khai

| Commit | Nội dung |
| --- | --- |
| `4451343`, `5f2b02a` | Khắc phục giữ từ/đối chiếu ở biên ASR |
| `bdfcd8b` | Profile trình bày DOCX ND30/HD05 |
| `e033939` | Thiết kế backend module và ranh giới tương thích; nền checkout gốc |
| `02679bf` | Sửa evidence, chỉnh tài liệu có rollback/transaction ở tầng core |
| `c2ddc28` | Backend MongoDB, API có xác thực, worker và OCR |
| `23f8172` | Giao diện người dùng/admin |
| `e301284` | Gắn manifest/ZIP với version ID ứng dụng |
| `e47dd5b` | Ghi nghiệm thu và luồng local |
| `3dc51f6` | Chuyển workspace web vào `web_app` |
| `7485943` | Hướng dẫn mở và sử dụng web |
| `2bcb7d8` | Sửa preview DOCX chạy ngoài runtime Codex |
| `e7528f9` | Sửa danh sách admin toàn hệ thống |
| `88c6283` | Đổi tên Minda và favicon |
| `27c67aa` | Animation nhẹ, có hỗ trợ reduced motion |

Ngày 19–22/10 trong hội thoại có nghiên cứu, chuẩn bị nội dung dự thi và xuất logo; không có commit tính năng mới sau `27c67aa` được xác nhận ở web tại thời điểm lập file này.

### 15.2. Tài liệu nên đọc

| Tài liệu | Vai trò |
| --- | --- |
| [Hướng dẫn sử dụng web](</Users/thien/Documents/School/Luận văn/web_app/docs/BAO_CAO_HUONG_DAN_SU_DUNG_WEB_MOI_2026-10-17.md>) | Mở/dừng, thao tác user/admin, luồng biên bản |
| [QUICKSTART](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/QUICKSTART.md>) | Runtime, lệnh, import, preview, QA |
| [Kiến trúc backend](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/ARCHITECTURE.md>) | Đọc mục 7 cho bố trí thực tế; mục trước có phần thiết kế |
| [Nghiệm thu 17/10](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/VALIDATION_2026-10-17.md>) | Bằng chứng backend/UI/model/OCR/restore |
| [Sửa preview](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/FIX_DOCX_PREVIEW_2026-10-17.md>) | Root cause và cách repair |
| [Sửa admin](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/FIX_ADMIN_LISTS_2026-10-17.md>) | Danh sách, bộ lọc, ownership và evidence |
| [Animation 18/10](</Users/thien/Documents/School/Luận văn/web_app/docs/backend/UI_MOTION_2026-10-18.md>) | Vị trí code, thời lượng, kiểm thử 15 trang/7 nhóm |
| [Thiết kế LLM/DOCX/PDF/scan](</Users/thien/Documents/School/Luận văn/web_app/docs/PLAN_LLM_BIEN_BAN_DOCX_PDF_SCAN_2026-10-09.md>) | Yêu cầu và lịch sử lựa chọn; không phải mọi dòng là trạng thái hiện tại |
| [LLM/FCM 10/10](</Users/thien/Documents/School/Luận văn/web_app/docs/LLM_FCM_MINUTES.md>) | Runtime và baseline; mô tả chưa có PDF/scan chỉ áp dụng increment/demo cũ |
| [Đánh giá LLM/FCM](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/LLM_FCM_EVALUATION_2026-10-10.md>) | Giới hạn pilot, fallback, chất lượng chưa đạt dùng trực tiếp |
| [Sửa mất từ ở biên](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/ASR_BOUNDARY_WORD_FIX_2026-10-15.md>) | Policy, smoke/replay và trade-off lỗi |
| [Thể thức DOCX](</Users/thien/Documents/School/Luận văn/web_app/docs/DOCX_FORMAT_STANDARDS.md>) | Chọn profile, metadata, giới hạn kiểm tra |

Ưu tiên code/config và nghiệm thu mới khi tài liệu lịch sử khác nhau. Không đọc một audit trước bản sửa rồi áp nguyên mọi kết luận vào web mới.

## 16. Checklist tiếp tục phiên làm việc

1. Đọc mục 1–3, xác định đúng workdir và Git branch; kiểm `git status` trước thay đổi.
2. Với công việc web, làm trong `/Users/thien/Documents/School/Luận văn/web_app`; giữ nguyên dữ liệu/cache/runtime symlink.
3. Xác định người dùng đang yêu cầu thảo luận, lập kế hoạch, sửa code hay chạy server. Lịch sử nghiên cứu chưa tự trở thành yêu cầu triển khai.
4. Nếu tiếp tục cải thiện DOCX, lấy output/transcript hiện có, đọc `topics.json` và `model_report.json`, phân loại câu giữ nguyên do fallback trước khi thay validator/prompt.
5. Giữ chính sách mẫu chi tiết, đủ ý tổng quát và khả năng truy về nguồn. Kiểm riêng tên/số/ngày, phủ định, điều kiện và đề xuất/quyết định.
6. Chọn test theo rủi ro của phần sửa; dùng DB/root thử nghiệm riêng. Ghi ngày, commit, dataset và phạm vi của kết quả.
7. Khi có yêu cầu commit cho công việc triển khai, chỉ đưa đúng file thuộc phạm vi; không đưa credential/audio/model cache hoặc file kế hoạch untracked có sẵn vào commit. Lần bàn giao context hiện tại không cần commit.
8. Cập nhật context khi có tính năng/quyết định mới, ghi rõ mục đã triển khai và mục còn đề xuất để phiên sau tiếp tục chính xác.

---

**Kết luận trạng thái:** Minda đã có prototype web và pipeline AI hoạt động, có cơ chế rà soát và DOCX chỉnh sửa được. Công việc cải thiện gần nhất đang ở bước thảo luận là nâng chất lượng lời văn bằng tổ chức ý và viết theo đoạn; chưa có triển khai hoặc benchmark độc lập chứng minh chất lượng văn phong hành chính đã đạt.
