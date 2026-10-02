# Kế hoạch benchmark encoder và bộ phân lớp nhận diện người nói

**Phiên bản:** 1.0 — 24/09/2026  
**Trạng thái:** Đã chốt phạm vi, chờ triển khai  
**Phạm vi:** Few-shot closed-set và open-set speaker identification  
**Tài liệu cấp trên:** [`../PIPELINE_IMPLEMENTATION_SPEC.md`](../PIPELINE_IMPLEMENTATION_SPEC.md)  
**Công việc song song:** [`TRANSCRIPTION_SEGMENTATION_IMPLEMENTATION_PLAN.md`](TRANSCRIPTION_SEGMENTATION_IMPLEMENTATION_PLAN.md)

## 0. Cách sử dụng tài liệu

Tài liệu này là yêu cầu triển khai chính thức cho benchmark nhận diện người nói bằng nhiều encoder và classifier. Mục tiêu là chọn mô hình cho pipeline dựa trên số đo tái lập được, không tích hợp trực tiếp mô hình mới vào sản phẩm trong cùng hạng mục.

Agent thực hiện phải đọc theo thứ tự:

1. `AGENTS.md` nếu repository có file này.
2. `PIPELINE_IMPLEMENTATION_SPEC.md`.
3. Toàn bộ tài liệu này.
4. `configs/evaluation.yaml`.
5. Benchmark và classifier hiện có:
   - `scripts/benchmark_speaker_id.py`;
   - `src/meeting_pipeline/domain/speaker_classifier.py`;
   - `src/meeting_pipeline/application/speakers.py`;
   - `docs/BENCHMARK_SPEAKER_ID_VIVOS.md`.

Quy ước:

- `BẮT BUỘC` là điều kiện nghiệm thu.
- `Khởi điểm` là tham số được chốt trước khi chạy test cuối, nhưng có thể hiệu chỉnh trên development.
- Mọi model revision, seed, episode và prediction phải được lưu để tái lập.
- Không dùng tập test để chọn encoder, classifier, hyperparameter hoặc threshold.
- Nếu phải khác tài liệu do API/checkpoint thực tế, ghi vào mục “Sai khác khi triển khai” kèm bằng chứng.

## 1. Bài toán và câu hỏi nghiên cứu

### 1.1. Bài toán

Mỗi người tham gia cung cấp rất ít mẫu giọng đăng ký. Với một phát ngôn mới, hệ thống phải:

1. Xác định đúng người nếu người đó đã đăng ký.
2. Trả `unknown` nếu người đó chưa đăng ký.
3. Hoạt động với K = 1, 3 và 5 mẫu đăng ký/người.
4. Chạy đủ nhanh để dùng trong pipeline xử lý cuộc họp offline.

Tên đúng của bài toán trong báo cáo là:

```text
few-shot open-set speaker identification
```

Không gọi đây là speaker authentication hoặc voice biometrics bảo mật vì benchmark không đánh giá spoofing, replay attack hoặc xác thực truy cập.

### 1.2. Câu hỏi nghiên cứu

Benchmark phải trả lời:

1. Encoder nào giữ thông tin danh tính tốt nhất trên giọng tiếng Việt?
2. K tăng từ 1 lên 3 và 5 cải thiện bao nhiêu?
3. Với cùng embedding, cosine prototype, KNN hay Linear SVM tốt hơn?
4. Mô hình có từ chối đúng người lạ không?
5. Chất lượng tăng có xứng với thời gian, bộ nhớ và kích thước model không?
6. Mô hình có khái quát từ VIVOS sang VoxVietnam không?

## 2. Phạm vi và quy tắc làm việc song song

### 2.1. Trong phạm vi

- Adapter cho nhiều speaker encoder.
- Episode generator có seed.
- Few-shot enrollment K = 1, 3, 5.
- Closed-set và open-set evaluation.
- Cosine prototype, KNN cosine và Linear SVM.
- Threshold calibration chỉ trên development.
- VIVOS development/test và VoxVietnam public test subset hiện có.
- Đo accuracy, precision, recall, F1 và thời gian.
- Lưu raw prediction, config, model revision và báo cáo Markdown/CSV/JSON.
- Chạy CPU bắt buộc; MPS chỉ là benchmark phụ nếu adapter hỗ trợ ổn định.

### 2.2. Ngoài phạm vi

Agent không được:

- Sửa `PrototypePipeline` để tích hợp mô hình thắng.
- Sửa VAD, ASR, synchronization, separation hoặc source fusion.
- Sửa schema timeline, web UI hoặc worker architecture.
- Fine-tune encoder trên VIVOS/VoxVietnam trong task này.
- Dùng hai cuộc họp cá nhân để tính accuracy/F1 khi chưa có ground truth.
- Tải thêm dataset ngoài dữ liệu đã có.
- Ghi đè báo cáo benchmark cũ.
- Thay threshold production trong `configs/default.yaml`.

### 2.3. Tránh xung đột với agent khác

Công việc phải nằm chủ yếu dưới:

```text
experiments/speaker_identification/
reports/speaker_identification/
tests/experiments/speaker_identification/
```

Không sửa các file mà agent VAD/ASR đang làm, đặc biệt:

```text
src/meeting_pipeline/config.py
src/meeting_pipeline/domain/schemas.py
src/meeting_pipeline/pipeline/prototype.py
src/meeting_pipeline/pipeline/stages/
src/meeting_pipeline/adapters/phowhisper_asr.py
configs/default.yaml
```

Nếu cần dùng logic hiện có, import hàm ổn định hoặc sao chép thuật toán tối thiểu vào package thí nghiệm kèm nguồn tham chiếu; không refactor production trong task này.

## 3. Encoder và đặc trưng

### 3.1. Danh sách bắt buộc

| ID | Encoder/đặc trưng | Model ID | Framework | Vai trò |
|---|---|---|---|---|
| E0 | MFCC 120 chiều | nội bộ | librosa | Baseline truyền thống |
| E1 | ECAPA-TDNN | `speechbrain/spkrec-ecapa-voxceleb` | SpeechBrain | Baseline deep learning hiện tại |
| E2 | X-vector TDNN | `speechbrain/spkrec-xvect-voxceleb` | SpeechBrain | Speaker embedding TDNN cổ điển |
| E3 | WeSpeaker ResNet34-LM | `pyannote/wespeaker-voxceleb-resnet34-LM` | pyannote.audio | Speaker embedding CNN/ResNet |
| E4 | WavLM Base Plus SV | `microsoft/wavlm-base-plus-sv` | Transformers | Self-supervised Transformer + X-vector head |

Nguồn chính thức:

- ECAPA: <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb>
- X-vector: <https://huggingface.co/speechbrain/spkrec-xvect-voxceleb>
- WeSpeaker: <https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM>
- WavLM SV: <https://huggingface.co/microsoft/wavlm-base-plus-sv>

### 3.2. Encoder tùy chọn

| ID | Encoder | Model ID | Điều kiện |
|---|---|---|---|
| E5 | TitaNet-Large | `nvidia/speakerverification_en_titanet_large` | Chỉ làm sau khi benchmark bắt buộc hoàn thành và NeMo smoke test thành công |

TitaNet không được làm hỏng môi trường chính. Nếu NeMo xung đột với Python/Torch/macOS:

- chạy trong môi trường `uv` tách biệt hoặc bỏ qua có ghi lý do;
- không thay lock file chính chỉ để ép TitaNet chạy;
- không coi việc bỏ TitaNet là thất bại của benchmark bắt buộc.

Nguồn: <https://huggingface.co/nvidia/speakerverification_en_titanet_large>

### 3.3. Model inventory và pin revision

Trước khi tải model mới, tạo:

```text
experiments/speaker_identification/model_inventory.json
```

Mỗi model ghi:

```json
{
  "model_id": "...",
  "resolved_revision": "full commit SHA",
  "framework": "...",
  "license": "...",
  "expected_or_reported_bytes": null,
  "actual_downloaded_bytes": null,
  "sample_rate": 16000,
  "status": "planned"
}
```

BẮT BUỘC:

- Không dùng floating `main` trong kết quả cuối.
- Lưu full resolved commit SHA.
- Dùng cache chung `data/model_cache` nhưng namespace theo model ID/revision.
- Không ghi token vào file, log hoặc report.
- Ghi dung lượng thực tế sau tải.
- Model mới phải load offline sau khi chuẩn bị.

### 3.4. Interface encoder thống nhất

```python
class SpeakerEncoder(Protocol):
    encoder_id: str
    model_id: str
    model_revision: str
    sample_rate: int
    embedding_dimension: int

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Return one finite, one-dimensional, L2-normalized embedding."""
```

Ràng buộc:

- Input mono float32 16 kHz.
- Output một vector 1-D hữu hạn.
- Output L2-normalized trong adapter hoặc ngay sau adapter theo một quy tắc chung.
- Không padding khác nhau giữa các encoder nếu model không bắt buộc.
- Nếu audio ngắn hơn minimum model duration, áp cùng chính sách pad và ghi policy vào config.
- Không load model khi import module.
- Model được lazy-load một lần mỗi process.
- CPU là device bắt buộc.

### 3.5. MFCC

MFCC chính dùng hàm tương đương `extract_mfcc_feature_vector` hiện tại:

- 20 MFCC;
- delta;
- delta-delta;
- mean/std pooling;
- vector 120 chiều;
- L2 normalization.

Benchmark chính dùng một vector trên một utterance để thống nhất đơn vị support/query. Cách MFCC window-KNN production hiện tại được chạy thêm dưới nhãn:

```text
legacy_mfcc_window_knn
```

Không trộn kết quả legacy vào phân tích factorial encoder × classifier mà không ghi rõ khác giao thức đặc trưng.

## 4. Bộ phân lớp

### 4.1. Cosine prototype

Với mỗi speaker:

```python
prototype = l2_normalize(mean(l2_normalize(support_embeddings), axis=0))
score = cosine(query_embedding, prototype)
```

Prediction closed-set là prototype có score cao nhất.

Prediction open-set dùng:

- top-1 score threshold;
- top-1 minus top-2 margin threshold.

Hai threshold được hiệu chỉnh riêng cho từng encoder và K.

### 4.2. KNN cosine

- Feature là embedding từng support utterance, không chỉ prototype.
- Metric `cosine`.
- `weights="distance"`.
- `n_neighbors` chọn từ `{1, 3, 5}` trên development.
- Không được lớn hơn tổng support vectors.
- Open-set score phải định nghĩa rõ, gồm nearest similarity và vote margin hoặc score tương đương.

### 4.3. Linear SVM

- Dùng `LinearSVC` hoặc linear `SVC` có decision function ổn định.
- `C` chọn từ `{0.1, 1.0, 10.0}` trên development.
- Nếu dùng scaler, fit scaler chỉ trên support của episode hoặc background development được mô tả rõ; không fit trên query/test.
- Không bật probability calibration trên test.
- Open-set dùng max decision score và top-1/top-2 margin được hiệu chỉnh trên development.

### 4.4. Legacy baselines

Phải giữ hai dòng tham chiếu:

```text
legacy_ecapa_cosine_threshold_0.25
legacy_mfcc_window_knn
```

Các dòng này tái hiện hành vi hiện tại. Chúng không được dùng để chọn threshold mới và không ghi đè báo cáo cũ.

## 5. Thiết kế hai vòng thí nghiệm

### 5.1. Vòng A — Sàng lọc encoder

Tất cả encoder E0–E4 dùng cosine prototype.

| Config | Encoder | Backend |
|---|---|---|
| A0 | MFCC | Cosine centroid |
| A1 | ECAPA | Cosine prototype |
| A2 | X-vector | Cosine prototype |
| A3 | WeSpeaker ResNet34 | Cosine prototype |
| A4 | WavLM Base Plus SV | Cosine prototype |

Chạy VIVOS development cho K = 1, 3, 5, closed-set và open-set.

Mục tiêu:

- kiểm tra adapter;
- hiệu chỉnh threshold;
- đo chất lượng và latency ban đầu;
- chọn encoder vào vòng B.

### 5.2. Quy tắc shortlist

Vòng B luôn giữ ECAPA làm baseline. Chọn hai encoder mới trong E2–E4 theo:

1. Macro F1 open-set trung bình qua K trên VIVOS development.
2. Nếu chênh lệch Macro F1 không quá 0,01, ưu tiên encoder có p95 latency thấp hơn.
3. Nếu encoder lỗi trên hơn 1% file hoặc không chạy offline ổn định, không shortlist dù metric cao.

Quyết định shortlist phải được ghi trước khi mở kết quả final test.

### 5.3. Vòng B — Encoder × classifier

Với ECAPA và hai encoder mới được shortlist, chạy:

- cosine prototype;
- KNN cosine;
- Linear SVM.

Tổng chính:

```text
3 encoders × 3 classifiers = 9 configurations
```

Thêm:

- MFCC + KNN cosine;
- MFCC + Linear SVM;
- hai legacy baselines.

TitaNet, nếu có, chỉ thêm một dòng cosine prototype trước. Chỉ mở rộng classifier sau khi core report hoàn thành.

## 6. Dữ liệu và split

### 6.1. VIVOS development/calibration

Dùng `VIVOS train` để:

- kiểm tra adapter;
- chọn KNN neighbors;
- chọn SVM C;
- chọn rejection threshold và margin;
- shortlist encoder.

Không báo kết quả này như final test.

### 6.2. VIVOS final test

Dùng `VIVOS test` để:

- đánh giá tiếng Việt sạch;
- so sánh với benchmark cũ;
- báo closed/open-set K = 1, 3, 5.

Không thay hyperparameter hoặc threshold sau khi xem kết quả.

### 6.3. VoxVietnam public test

Subset hiện có:

- 31 speaker đủ ít nhất 10 utterance;
- mỗi speaker có support pool 5 và query pool 5 không trùng;
- subset-index đã có seed và provenance.

Quy tắc:

- Chỉ dùng làm test khả năng khái quát.
- Không fit threshold hoặc chọn model trên VoxVietnam.
- Áp nguyên model/hyperparameter/threshold đã khóa từ VIVOS development.
- Báo rõ đây là subset từ partition test hiện có, không tự gọi là VoxVietnam-O.

### 6.4. Hai cuộc họp cá nhân

Chỉ dùng smoke test quan sát sau benchmark:

- pipeline có load encoder được không;
- danh tính có ổn định sơ bộ không;
- runtime có chấp nhận được không.

Không tính accuracy, precision, recall hoặc F1 do chưa có ground truth.

## 7. Episode protocol

### 7.1. Cấu hình khởi điểm

```yaml
seed: 20260924
few_shot_k: [1, 3, 5]
episodes: 30
known_speakers_per_episode: 5
unknown_speakers_per_episode: 5
queries_per_known_speaker: 5
queries_per_unknown_speaker: 5
sample_rate: 16000
device: cpu
```

### 7.2. Closed-set episode

Mỗi episode:

- chọn 5 known speakers;
- chọn K support utterances/người;
- chọn 5 query utterances/người, không trùng support;
- mọi query phải được gán vào một trong 5 known labels.

Tổng query khởi điểm:

```text
5 speakers × 5 queries = 25 queries/episode
```

### 7.3. Open-set episode

Mỗi episode:

- 5 known speakers như closed-set;
- thêm 5 unknown speakers không giao known;
- mỗi unknown speaker có 5 query;
- tất cả unknown speakers quy về nhãn đánh giá chung `unknown`.

Tổng query khởi điểm:

```text
25 known queries + 25 unknown queries = 50 queries/episode
```

### 7.4. Episode manifest

Sinh episode trước khi chạy model và lưu bất biến:

```text
episode_manifests/
├── vivos-development.json
├── vivos-test.json
└── voxvietnam-public-test.json
```

Mỗi record ghi:

- dataset/split;
- episode ID;
- seed;
- K;
- protocol closed/open;
- known/unknown speaker IDs;
- support paths hoặc row IDs;
- query paths hoặc row IDs;
- SHA-256 hoặc stable dataset identity.

BẮT BUỘC:

- Tất cả model dùng đúng cùng manifest.
- Support và query không giao nhau.
- Known và unknown speakers không giao nhau.
- Episode deterministic theo seed.
- Không chọn “file đầu tiên theo sort” làm giao thức final.
- Generator phải thất bại rõ nếu speaker không đủ utterance.

## 8. Calibration và chống rò rỉ

### 8.1. Development only

Hyperparameter và threshold chỉ được chọn từ VIVOS development.

Mỗi tổ hợp encoder/classifier/K có calibration record:

```json
{
  "encoder_id": "...",
  "classifier_id": "...",
  "few_shot_k": 3,
  "hyperparameters": {},
  "score_threshold": 0.0,
  "margin_threshold": 0.0,
  "objective": "macro_f1_open_set",
  "development_manifest_hash": "..."
}
```

### 8.2. Objective

Chọn cấu hình tối đa hóa:

```text
macro F1 open-set
```

Tie-break theo thứ tự:

1. Unknown recall cao hơn.
2. Known identification accuracy cao hơn.
3. p95 inference latency thấp hơn.

### 8.3. Final freeze

Trước khi chạy final test, ghi:

```text
calibration/frozen-calibration.json
```

Sau đó:

- không sửa file;
- không chọn lại threshold theo VIVOS test;
- không chọn lại threshold theo VoxVietnam;
- nếu phát hiện bug metric/code, tăng run ID và chạy lại toàn bộ từ calibration, không vá riêng test result.

## 9. Metric

### 9.1. Closed-set

Tính bằng scikit-learn với `zero_division=0`:

- accuracy;
- macro precision;
- macro recall;
- macro F1;
- confusion matrix;
- per-speaker recall để chẩn đoán.

Không cần micro precision/recall/F1 trong bảng chính vì với single-label multiclass chúng trùng hoặc gần tương đương accuracy và không thêm thông tin hữu ích.

### 9.2. Open-set

Nhãn đánh giá gồm known speaker IDs và một nhãn `unknown`.

Tính:

- overall accuracy;
- macro precision;
- macro recall;
- macro F1;
- known identification accuracy;
- unknown rejection rate/unknown recall;
- balanced accuracy;
- false accept rate cho unknown;
- false reject rate cho known;
- confusion matrix có `unknown`.

Known query dự đoán thành sai known speaker vẫn là lỗi.

### 9.3. Tổng hợp episode

Mỗi metric lưu từng episode. Báo cáo cuối ghi:

- mean;
- standard deviation;
- median;
- 95% bootstrap confidence interval trên episode, với seed cố định.

Không bootstrap từng utterance rồi bỏ qua cấu trúc episode.

### 9.4. Raw predictions

`predictions.csv` phải có ít nhất:

```text
run_id
dataset
split
protocol
episode_id
few_shot_k
encoder_id
classifier_id
query_id
true_speaker_id
is_known
predicted_speaker_id
predicted_unknown
top1_score
top2_score
margin
score_threshold
margin_threshold
correct
audio_duration_sec
feature_latency_ms
classifier_latency_ms
end_to_end_latency_ms
```

Không lưu waveform hoặc dữ liệu cá nhân mới trong report.

## 10. Đo thời gian và tài nguyên

### 10.1. Các thành phần thời gian

Đo riêng:

1. Cold model load time.
2. Feature/embedding extraction time.
3. Enrollment/prototype/fit time.
4. Classifier-only prediction time.
5. End-to-end warm inference time từ waveform đến open-set decision.

### 10.2. Thống kê thời gian

Báo cáo:

- mean;
- median;
- p95;
- real-time factor;
- enrollment milliseconds per speaker;
- cold load seconds.

```python
real_time_factor = processing_seconds / audio_duration_seconds
```

### 10.3. Quy tắc timing

- CPU là bảng chính.
- Ghi model/device/dtype, số thread, Python, Torch và hệ điều hành.
- Warm up encoder trước timing warm inference.
- Không tính download vào load time.
- Không dùng cache trong timing run.
- Accuracy run được dùng cache embedding.
- Timing không chạy song song giữa các encoder.
- Không assert latency tuyệt đối trong unit test.
- Nếu chạy MPS, báo bảng riêng và không trộn với CPU.

### 10.4. Tài nguyên

Ghi:

- model bytes trên đĩa;
- embedding dimension;
- peak RSS nếu đo ổn định được;
- số file cache và tổng cache bytes.

Không tuyên bố memory chính xác nếu công cụ đo không đáng tin trên macOS; ghi phương pháp đo.

## 11. Embedding cache

Accuracy evaluation dùng cache:

```text
data/evaluation_cache/speaker_embeddings/
└── <encoder-id>/
    └── <revision>/
        └── <audio-sha256>.npy
```

Cache metadata phải chứa:

- audio SHA-256;
- model ID/revision;
- preprocessing version;
- sample rate;
- embedding dimension;
- created timestamp;
- finite/norm validation.

Quy tắc:

- Ghi file tạm rồi atomic rename.
- Cache key thay đổi khi preprocessing/model thay đổi.
- Không dùng cache cho latency benchmark.
- Không serialize model object bằng pickle.
- Embedding lỗi/NaN không được cache như thành công.

## 12. Cấu trúc triển khai

Tạo package độc lập:

```text
experiments/speaker_identification/
├── README.md
├── config.yaml
├── run.py
├── contracts.py
├── audio.py
├── datasets.py
├── episodes.py
├── cache.py
├── metrics.py
├── timing.py
├── reporting.py
├── calibration.py
├── encoders/
│   ├── base.py
│   ├── mfcc.py
│   ├── speechbrain_ecapa.py
│   ├── speechbrain_xvector.py
│   ├── pyannote_wespeaker.py
│   ├── transformers_wavlm.py
│   └── nemo_titanet.py          # optional
└── classifiers/
    ├── base.py
    ├── cosine_prototype.py
    ├── cosine_knn.py
    └── linear_svm.py
```

Test:

```text
tests/experiments/speaker_identification/
├── test_datasets.py
├── test_episodes.py
├── test_cache.py
├── test_classifiers.py
├── test_open_set_decision.py
├── test_metrics.py
└── test_reporting.py
```

Không cần chuyển package này vào `src/meeting_pipeline` trước khi chọn được mô hình thắng.

## 13. CLI thí nghiệm

CLI tối thiểu:

```bash
uv run python -m experiments.speaker_identification.run validate-data
uv run python -m experiments.speaker_identification.run prepare-models
uv run python -m experiments.speaker_identification.run smoke-encoders
uv run python -m experiments.speaker_identification.run create-episodes
uv run python -m experiments.speaker_identification.run cache-embeddings
uv run python -m experiments.speaker_identification.run calibrate
uv run python -m experiments.speaker_identification.run evaluate
uv run python -m experiments.speaker_identification.run benchmark-time
uv run python -m experiments.speaker_identification.run report
```

Mỗi command:

- có `--config`;
- có `--run-id` hoặc sinh run ID bất biến;
- in đường dẫn artifact;
- không ghi đè output đã hoàn thành nếu thiếu `--force`;
- resume cache an toàn;
- lỗi thiếu model phải nêu model ID/revision và command chuẩn bị.

## 14. Cấu trúc output

```text
reports/speaker_identification/<run-id>/
├── config.snapshot.yaml
├── environment.json
├── model_inventory.json
├── dataset_inventory.json
├── episode_manifests/
├── calibration/
│   ├── search-results.csv
│   └── frozen-calibration.json
├── predictions/
│   ├── vivos-test.csv
│   └── voxvietnam-public-test.csv
├── metrics/
│   ├── metrics-by-episode.csv
│   ├── summary.csv
│   ├── summary.json
│   └── confusion-matrices/
├── timing/
│   ├── raw-timing.csv
│   └── summary.csv
├── encoder-screening.md
├── classifier-comparison.md
└── FINAL_REPORT.md
```

Mọi report phải tham chiếu manifest hash và frozen calibration hash.

## 15. Bảng kết quả bắt buộc

### 15.1. Encoder screening

| Dataset | Encoder | K | Accuracy | Macro P | Macro R | Macro F1 | Unknown recall | Latency ms | RTF |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

### 15.2. Encoder × classifier

| Dataset | Encoder | Classifier | K | Accuracy | Macro P | Macro R | Macro F1 | Known acc | Unknown recall | Balanced acc |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

### 15.3. Chi phí triển khai

| Encoder | Model bytes | Embedding dim | Load s | Enrollment ms/spk | Inference mean ms | p95 ms | RTF |
|---|---:|---:|---:|---:|---:|---:|---:|

Giá trị metric chính hiển thị dưới dạng `mean ± std`; 95% CI có thể đặt trong cột hoặc phụ lục.

## 16. Test bắt buộc

### 16.1. Dataset và episode

- Loader VIVOS lấy đúng speaker/file.
- Loader VoxVietnam dùng đúng subset index.
- Support/query không giao nhau.
- Known/unknown speakers không giao nhau.
- Cùng seed sinh cùng manifest byte-for-byte hoặc semantic hash giống nhau.
- Seed khác tạo episode khác.
- K=5 không lấy query từ support pool.
- Thiếu utterance tạo lỗi rõ ràng.

### 16.2. Encoder contract

Dùng fake encoder trong unit test:

- Output 1-D.
- Output hữu hạn.
- Norm gần 1.
- Input sai sample rate bị từ chối hoặc preprocess theo contract.
- Model không load khi import.
- Cache key đổi khi revision/preprocessing đổi.

Model smoke test có marker `model_smoke`:

- Mỗi encoder bắt buộc encode được cùng hai file VIVOS.
- Embedding cùng người và khác người đều hữu hạn.
- Ghi cosine để chẩn đoán, không đặt assertion chất lượng quá chặt trên hai mẫu.
- Lần chạy offline sau chuẩn bị không gọi mạng.

### 16.3. Classifier

- Cosine prototype tính đúng trên vector nhỏ biết trước.
- KNN dùng support labels đúng.
- SVM fit chỉ trên support.
- Closed-set luôn trả known label.
- Open-set trả unknown khi score dưới threshold.
- Margin threshold được áp đúng.
- Excluded speaker hoặc state anonymous của production không được rò vào evaluator.

### 16.4. Metric

- So sánh metric với ví dụ nhỏ tính tay.
- Known sai sang known khác bị tính lỗi.
- Unknown bị nhận thành known làm tăng false accept.
- Macro average dùng label set được ghi rõ.
- `zero_division=0` và trường hợp lớp không xuất hiện được xử lý ổn định.
- Episode aggregation và bootstrap deterministic.

### 16.5. Reporting

- CSV/JSON/Markdown có cùng số cấu hình.
- Mọi summary truy được về raw predictions.
- Không ghi đường dẫn chứa secret/token.
- Không ghi đè run cũ.
- Report phân biệt development và final test.

## 17. Cổng chất lượng

Trước khi báo hoàn thành:

```bash
uv run pytest -q
uv run mypy src/meeting_pipeline experiments/speaker_identification
uv run ruff check .
uv run ruff format --check .
```

Nếu mypy config hiện chỉ nhận package `meeting_pipeline`, agent có thể chạy thêm command/file list phù hợp cho package thí nghiệm nhưng không được bỏ type check package mới.

BẮT BUỘC:

- Unit test không tải model hoặc dataset qua mạng.
- Model smoke test được đánh dấu riêng.
- Không suppress warning/lỗi rộng để làm cổng xanh.
- Báo rõ lỗi baseline tồn tại trước thay đổi và regression mới.

## 18. Tiêu chí nghiệm thu

Hạng mục hoàn thành khi:

### 18.1. Reproducibility

- Có config snapshot, seed và environment.
- Tất cả model có full revision SHA.
- Có episode manifest cố định và hash.
- Có frozen calibration trước final test.
- Có raw prediction cho mọi summary metric.

### 18.2. Coverage thí nghiệm

- E0–E4 smoke test thành công hoặc model bắt buộc thất bại có bằng chứng kỹ thuật và không có thay thế âm thầm.
- Vòng A chạy đủ K = 1, 3, 5 và tối thiểu 30 episode/K trên development.
- Shortlist được chốt trước final test.
- Vòng B chạy đủ classifier đã định.
- VIVOS test và VoxVietnam public test đều có kết quả.
- Closed-set và open-set đều có kết quả.

### 18.3. Metric và timing

- Có accuracy, macro precision, macro recall, macro F1.
- Có known accuracy và unknown rejection cho open-set.
- Có mean/std và 95% CI trên episode.
- Có cold load, enrollment, classifier-only và end-to-end timing.
- Timing CPU không dùng embedding cache.

### 18.4. Tách khỏi production

- Không đổi classifier production hoặc threshold mặc định.
- Không sửa VAD/ASR pipeline.
- Không xóa benchmark/report cũ.
- Báo cáo cuối chỉ đề xuất mô hình thắng và task tích hợp tiếp theo.

## 19. Thứ tự triển khai và checkpoint

- [ ] B0 — Ghi baseline, kiểm tra dữ liệu/model cache và lập inventory.
- [ ] B1 — Tạo package thí nghiệm, config và contracts.
- [ ] B2 — Viết loader VIVOS/VoxVietnam và test chống leakage.
- [ ] B3 — Viết episode generator, manifest và deterministic tests.
- [ ] B4 — Viết interface encoder, MFCC và ECAPA adapters.
- [ ] B5 — Thêm X-vector adapter và smoke test offline.
- [ ] B6 — Thêm WeSpeaker adapter và smoke test offline.
- [ ] B7 — Thêm WavLM adapter và smoke test offline.
- [ ] B8 — Viết cosine/KNN/SVM backends và unit test.
- [ ] B9 — Viết metrics, timing, cache và reporting.
- [ ] B10 — Chạy Vòng A trên VIVOS development.
- [ ] B11 — Chốt shortlist và frozen calibration.
- [ ] B12 — Chạy Vòng B trên VIVOS final test.
- [ ] B13 — Chạy Vòng B trên VoxVietnam public test.
- [ ] B14 — Chạy timing benchmark không cache.
- [ ] B15 — Thử TitaNet tùy chọn nếu core đã hoàn thành.
- [ ] B16 — Xuất FINAL_REPORT và đề xuất integration task.
- [ ] B17 — Chạy toàn bộ cổng chất lượng và kiểm tra artifact.

Không mở final test trước B11. Nếu phát hiện bug sau B11 ảnh hưởng prediction/metric, tạo run mới và chạy lại calibration lẫn test.

## 20. Báo cáo hoàn tất bắt buộc

Agent phải trả về:

1. Model inventory và model revisions.
2. Dataset/episode manifest và kiểm tra leakage.
3. Kết quả Vòng A và lý do shortlist.
4. Kết quả Vòng B trên VIVOS test.
5. Kết quả áp nguyên cấu hình trên VoxVietnam.
6. Bảng timing CPU.
7. So sánh với benchmark ECAPA/MFCC cũ.
8. Confusion matrix và ví dụ lỗi chính.
9. Đề xuất một mô hình chất lượng cao và một mô hình nhẹ.
10. Các file tạo/sửa và kết quả quality gates.
11. Sai khác so với kế hoạch.
12. Task tích hợp tiếp theo, nhưng không tự tích hợp vào production.

Kết luận phải dựa trên số đo. Không gọi một mô hình “tối ưu” chỉ vì accuracy cao nhất trên một split.

## 21. Sai khác khi triển khai

Agent ghi sai khác theo mẫu:

```text
Ngày:
Checkpoint:
Yêu cầu gốc:
Thay đổi thực tế:
Lý do và bằng chứng:
Ảnh hưởng đến tính công bằng:
Kiểm thử bổ sung:
```

Hiện chưa có sai khác được chấp nhận.

## 22. Lệnh giao việc ngắn cho agent

```text
Hãy triển khai toàn bộ kế hoạch trong
docs/SPEAKER_IDENTIFICATION_BENCHMARK_PLAN.md.

Đọc AGENTS.md nếu có, PIPELINE_IMPLEMENTATION_SPEC.md, configs/evaluation.yaml và toàn bộ
benchmark plan trước khi sửa. Đây là công việc song song với agent VAD/ASR: chỉ làm trong
experiments/speaker_identification, reports/speaker_identification và test tương ứng; không sửa
pipeline production, config/schema đang được agent kia thay đổi hoặc threshold mặc định.

Thực hiện lần lượt B0–B17. Không mở final test trước khi shortlist và frozen calibration được
ghi lại. Tất cả model dùng cùng episode manifest; threshold chỉ chọn trên VIVOS development;
VoxVietnam chỉ dùng test. Chỉ báo hoàn thành khi raw predictions, bảng metric, bảng timing,
model revisions, manifests, report và quality gates đều đầy đủ. Nếu khác plan, ghi bằng chứng
vào mục “Sai khác khi triển khai”.
```
