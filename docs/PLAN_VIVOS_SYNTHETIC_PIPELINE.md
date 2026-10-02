# Kế hoạch triển khai pipeline họp đa nguồn chỉ dùng VIVOS

## 0. Mục đích tài liệu

Tài liệu này là đặc tả công việc cho agent triển khai. Agent phải bám theo thứ tự, hợp đồng dữ liệu, baseline, tiêu chí nghiệm thu và đầu ra được mô tả ở đây. Không tự ý đổi mô hình, bỏ baseline, thay cách chia dữ liệu hoặc dùng thêm tập dữ liệu khác mà không ghi thành đề xuất riêng.

Phiên bản này dùng **VIVOS làm nguồn âm thanh duy nhất**. Các mô hình pretrained được phép sử dụng, nhưng không được dùng LibriWASN, VoxVietnam, MUSAN, các cuộc họp tự thu hoặc bất kỳ corpus âm thanh bên ngoài nào để huấn luyện, hiệu chỉnh hay đánh giá.

Mục tiêu của giai đoạn này là:

1. Xây dựng pipeline hoàn chỉnh từ đăng ký người nói và nhiều file ghi âm đến timeline cuộc họp.
2. Tạo dữ liệu cuộc họp nhiều điện thoại có ground truth từ VIVOS.
3. Phát triển và so sánh các phương pháp chọn nguồn, nhận dạng người nói và gộp transcript.
4. Tạo demo tối giản có thể chạy cục bộ.
5. Tạo bộ đánh giá tái lập được để sau này thay dữ liệu mô phỏng bằng dữ liệu thật mà không viết lại pipeline.

Kết quả của giai đoạn này chỉ được mô tả là kết quả trên **dữ liệu đa nguồn mô phỏng từ VIVOS**. Không được suy diễn trực tiếp thành hiệu năng trên cuộc họp hoặc điện thoại thật.

---

## 1. Bài toán cần giải quyết

Đầu vào:

- Danh sách người tham gia và các file đăng ký giọng nói của từng người.
- Từ 3 đến 5 file âm thanh ghi cùng một cuộc họp.
- Các file có thể khác sample rate, codec, mức âm lượng, thời điểm bắt đầu và clock drift.

Đầu ra:

- Các file nguồn sau khi đồng bộ.
- Danh sách đoạn có tiếng nói trên một timeline chung.
- Người nói được gán cho từng đoạn.
- Transcript đã gộp từ các nguồn.
- Điểm chất lượng và mức đóng góp của từng nguồn.
- Nguồn chính của từng đoạn và audio clip từ nguồn đó để đối chiếu.
- Audio clip cùng khoảng thời gian từ mọi nguồn.
- Báo cáo chỉ số và bảng so sánh baseline.

Pipeline mục tiêu:

```text
VIVOS + transcript + speaker ID
        |
        v
Tách enrollment và nội dung họp theo speaker
        |
        v
Tạo canonical meeting timeline
        |
        v
Mô phỏng 3-5 thiết bị từ cùng một sự kiện âm thanh
        |
        v
Chuẩn hóa -> đồng bộ offset/drift -> timeline VAD chung
        |
        +-----------------------+
        |                       |
        v                       v
Speaker embedding          ASR cho segment x source
        |                       |
        v                       v
Gán người nói             Chấm chất lượng nguồn
        |                       |
        +-----------+-----------+
                    v
          Weighted transcript fusion
                    |
                    v
       Timeline + provenance + evidence audio
```

---

## 2. Phạm vi và các quyết định đã khóa

### 2.1. Trong phạm vi

- Tiếng Việt.
- Xử lý sau cuộc họp, không cần streaming thời gian thực.
- Dữ liệu phát triển, validation và test đều sinh từ VIVOS.
- Few-shot speaker identification bằng enrollment.
- Nhiều thiết bị ghi cùng một canonical meeting.
- Đồng bộ offset và clock drift.
- VAD trước ASR; mọi nguồn được cắt theo cùng một timeline.
- ASR riêng cho từng `segment x source`.
- Gộp transcript ở mức từ bằng ROVER/confusion network.
- Lưu provenance của từ và đoạn.
- Giao diện demo tối giản chạy cục bộ.

### 2.2. Chưa làm trong phiên bản này

- Tách hai người nói chồng bằng speech separation.
- Kết luận hiệu năng trên dữ liệu họp thật.
- Streaming và cập nhật transcript trực tiếp.
- Huấn luyện lại toàn bộ ASR, VAD hoặc speaker encoder.
- Nhận dạng cảm xúc, tóm tắt nội dung và phân tích chủ đề.
- Tích hợp cloud hoặc xác thực người dùng.

Schema phải giữ trường `overlap`, nhưng generator phiên bản đầu đặt `overlap=false`. Thiết kế module không được giả định vĩnh viễn chỉ có một người nói.

Benchmark chính là **closed-set**: mọi người xuất hiện trong cuộc họp đều đã đăng ký. Unknown-speaker detection là thí nghiệm phụ: tạo các phiên riêng có người cố ý không đăng ký, chọn ngưỡng trên validation và báo cáo riêng; không trộn kết quả này vào benchmark closed-set.

### 2.3. Quy tắc không được vi phạm

1. Không dùng transcript ground truth, simulation recipe hoặc oracle SNR làm feature ở inference.
2. Không để cùng speaker xuất hiện ở nhiều split.
3. Enrollment và câu dùng trong cuộc họp phải là các file khác nhau.
4. Không tạo cuộc họp độc lập cho từng điện thoại. Mọi điện thoại phải ghi cùng một canonical event.
5. Không chạy VAD độc lập để tạo timeline khác nhau cho mỗi nguồn.
6. Không chọn mô hình hoặc ngưỡng bằng kết quả test.
7. Không ghi đè file VIVOS gốc.
8. Không commit audio sinh ra, model checkpoint lớn, cache hoặc thông tin bí mật.

---

## 3. Stack kỹ thuật bắt buộc

Sử dụng Python 3.11 và quản lý dependency bằng `pyproject.toml`. Agent được dùng `uv` hoặc `pip`, nhưng phải cung cấp lệnh cài đặt rõ ràng và lock file nếu công cụ hỗ trợ.

### 3.1. Thư viện lõi

- `numpy`, `scipy`: xử lý tín hiệu và số học.
- `pandas` hoặc `polars`: manifest và báo cáo bảng.
- `soundfile`: đọc/ghi WAV.
- `librosa`: MFCC và đặc trưng âm thanh cơ bản.
- `torchaudio`: resampling và tensor audio.
- `pyroomacoustics`: mô phỏng phòng và RIR.
- `audiomentations`: augmentation không gian tham số đơn giản.
- `torch`: inference mô hình.
- `speechbrain`: ECAPA-TDNN mặc định.
- `transformers`: PhoWhisper.
- `silero-vad` hoặc torch hub package tương ứng: VAD.
- `scikit-learn`: KNN, Logistic Regression, calibration và metric.
- `jiwer`: WER và thành phần S/D/I.
- `pydantic`: kiểm tra schema/config.
- `PyYAML`: file cấu hình.
- `typer`: CLI.
- `streamlit`: giao diện demo.
- `pytest`, `pytest-cov`: kiểm thử.
- `ruff`: lint và format.
- `mypy`: static type checking cho mã lõi.

`ffmpeg` là dependency hệ thống dùng để chuẩn hóa codec và mô phỏng nén. Khi không có `ffmpeg`, chương trình phải báo lỗi có hướng dẫn, không được thất bại im lặng.

### 3.2. Mô hình mặc định

- VAD: Silero VAD pretrained.
- Speaker encoder: ECAPA-TDNN pretrained từ SpeechBrain.
- Speaker classifier mặc định: cosine nearest centroid từ enrollment prototype.
- ASR: `vinai/PhoWhisper-small` cho phát triển. Cho phép cấu hình model ID khác, nhưng báo cáo chuẩn phải dùng cùng một model cho tất cả baseline.
- Fusion learner: Logistic Regression có regularization và calibration nếu validation cho thấy cần thiết.

Model ID và revision/commit phải được pin trong config của run sau lần tải thành công đầu tiên. Không dùng alias `latest` trong thí nghiệm báo cáo.

Không fine-tune các mô hình lớn trong giai đoạn này. Chỉ học các thành phần nhẹ như source-quality model, fusion weights, ngưỡng unknown và calibration.

---

## 4. Cấu trúc repository yêu cầu

Nếu repository chưa có cấu trúc tương ứng, tạo như sau. Có thể điều chỉnh tên nhỏ để phù hợp mã hiện có, nhưng phải giữ ranh giới module.

Trước khi tạo cấu trúc, agent phải chạy preflight: kiểm kê repository, tìm `AGENTS.md`, xác định đường dẫn VIVOS và ghi lại phần mã có thể tái sử dụng. Ở thời điểm viết kế hoạch, checkout hiện tại chỉ thấy `audio-notes/` và chưa thấy source code hoặc VIVOS. Không được dùng nội dung `audio-notes/` làm yêu cầu kỹ thuật. Nếu VIVOS nằm ngoài project, chỉ lưu đường dẫn trong config cục bộ hoặc biến môi trường; không sao chép dữ liệu lớn vào Git và không tự tải corpus khác.

```text
.
├── README.md
├── pyproject.toml
├── .gitignore
├── configs/
│   ├── data/vivos.yaml
│   ├── simulation/{smoke,easy,moderate,stress}.yaml
│   ├── models/default.yaml
│   ├── fusion/default.yaml
│   ├── experiment/{smoke,full}.yaml
│   └── demo.yaml
├── src/meeting_pipeline/
│   ├── config.py
│   ├── schemas.py
│   ├── data/
│   │   ├── vivos.py
│   │   ├── manifest.py
│   │   ├── splitting.py
│   │   └── leakage.py
│   ├── simulation/
│   │   ├── meeting_recipe.py
│   │   ├── room.py
│   │   ├── device.py
│   │   ├── noise.py
│   │   └── render.py
│   ├── audio/
│   │   ├── io.py
│   │   ├── synchronization.py
│   │   ├── vad.py
│   │   ├── segmentation.py
│   │   └── quality.py
│   ├── speaker/
│   │   ├── encoder.py
│   │   ├── enrollment.py
│   │   ├── identification.py
│   │   └── aggregation.py
│   ├── asr/
│   │   ├── engine.py
│   │   ├── normalization.py
│   │   └── confidence.py
│   ├── fusion/
│   │   ├── alignment.py
│   │   ├── confusion_network.py
│   │   ├── baselines.py
│   │   ├── features.py
│   │   ├── model.py
│   │   └── provenance.py
│   ├── pipeline/
│   │   ├── meeting_pipeline.py
│   │   └── artifact_writer.py
│   ├── evaluation/
│   │   ├── sync_metrics.py
│   │   ├── vad_metrics.py
│   │   ├── speaker_metrics.py
│   │   ├── asr_metrics.py
│   │   ├── end_to_end_metrics.py
│   │   └── report.py
│   └── cli.py
├── app/
│   └── streamlit_app.py
├── scripts/
│   ├── prepare_vivos.py
│   ├── generate_meetings.py
│   ├── run_experiment.py
│   └── run_demo.sh
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── data/
│   ├── raw/                 # gitignored; VIVOS không được sửa
│   ├── manifests/
│   ├── recipes/
│   └── generated/           # gitignored
├── artifacts/               # gitignored
└── reports/
    ├── metrics/
    ├── tables/
    └── failure_cases/
```

Yêu cầu chất lượng mã:

- Type hint cho API công khai và cấu trúc dữ liệu.
- Docstring cho class/function công khai và thuật toán không hiển nhiên.
- Comment giải thích lý do hoặc công thức; không comment lặp lại câu lệnh.
- Không dùng `print` trong thư viện lõi; dùng `logging`.
- Không để đường dẫn tuyệt đối trong mã.
- Không đặt magic numbers; mọi ngưỡng nằm trong config.
- Module mô hình phải có interface để thay model mà không sửa pipeline.

---

## 5. Hợp đồng dữ liệu

Các schema dưới đây phải được định nghĩa bằng Pydantic và version hóa bằng trường `schema_version`.

### 5.1. VIVOS manifest

Mỗi dòng JSONL:

```json
{
  "schema_version": "1.0",
  "utterance_id": "VIVOS_...",
  "audio_path": "data/raw/vivos/...wav",
  "audio_sha256": "...",
  "speaker_id": "speaker_001",
  "text_raw": "...",
  "text_normalized": "...",
  "duration_sec": 3.42,
  "sample_rate": 16000,
  "split": "development"
}
```

### 5.2. Canonical meeting recipe

Recipe phải chứa:

- `meeting_id`, split, seed và profile.
- Danh sách speaker và enrollment utterance.
- Danh sách turn: source utterance, canonical start/end, speaker và transcript.
- Kích thước phòng, vị trí speaker và vị trí device.
- Tham số RIR của từng cặp `speaker x device`.
- Gain, SNR, noise, codec, dropout, clipping của từng device.
- Offset và drift thật của từng device.
- Hash manifest, config và phiên bản code nếu có Git commit.
- Mapping từ timestamp thiết bị về canonical timeline.

### 5.3. Segment

```json
{
  "schema_version": "1.0",
  "meeting_id": "meeting_001",
  "segment_id": "seg_0004",
  "start_sec": 14.21,
  "end_sec": 18.74,
  "overlap": false,
  "reference_speaker_id": "speaker_003",
  "reference_text": "nội dung chuẩn"
}
```

Các trường `reference_*` chỉ tồn tại trong artifact đánh giá, không được truyền vào inference service.

### 5.4. Source hypothesis

```json
{
  "meeting_id": "meeting_001",
  "segment_id": "seg_0004",
  "source_id": "phone_02",
  "text": "nội dung nhận dạng",
  "words": [
    {
      "word": "nội",
      "start_sec": 14.40,
      "end_sec": 14.71,
      "asr_confidence": 0.83
    }
  ],
  "audio_features": {},
  "asr_features": {},
  "audio_quality_score": 0.81,
  "transcript_quality_score": 0.89
}
```

### 5.5. Final timeline item

```json
{
  "meeting_id": "meeting_001",
  "segment_id": "seg_0004",
  "start_sec": 14.21,
  "end_sec": 18.74,
  "speaker_id": "speaker_003",
  "speaker_confidence": 0.91,
  "text": "nội dung đã được gộp",
  "transcript_confidence": 0.86,
  "primary_source_id": "phone_02",
  "source_scores": {
    "phone_01": 0.62,
    "phone_02": 0.89,
    "phone_03": 0.44
  },
  "word_provenance": [],
  "evidence_clips": {
    "phone_01": "clips/seg_0004/phone_01.wav",
    "phone_02": "clips/seg_0004/phone_02.wav",
    "phone_03": "clips/seg_0004/phone_03.wav"
  }
}
```

Mỗi word provenance tối thiểu phải chứa token đầu ra, confidence, các nguồn ủng hộ, điểm của từng nguồn và nguồn đại diện. `primary_source_id` là nguồn có tổng đóng góp cao nhất trong đoạn; nó không có nghĩa toàn bộ transcript chỉ lấy từ nguồn đó.

---

## 6. Chia VIVOS và kiểm soát rò rỉ dữ liệu

### 6.1. Split

Ưu tiên giữ split gốc của VIVOS nếu phù hợp, nhưng phải tạo ba tập chức năng:

- `development`: tạo dữ liệu học fusion/source score.
- `validation`: chọn ngưỡng, hyperparameter và model version.
- `test`: chỉ dùng một lần sau khi khóa cấu hình.

Yêu cầu:

- Speaker-disjoint giữa ba tập.
- Utterance-disjoint giữa enrollment và meeting content.
- Không reuse utterance giữa các split, kể cả dưới augmentation khác.
- Noise dạng VIVOS babble, nếu bật, chỉ lấy speaker/utterance trong cùng split và không lấy utterance mục tiêu.
- Text trùng nhau giữa các speaker được phép, nhưng phải báo tỷ lệ trùng trong data report.

### 6.2. Kiểm tra tự động

Viết command kiểm tra:

```bash
python -m meeting_pipeline.cli data audit --manifest data/manifests/vivos.jsonl
```

Command phải thất bại với exit code khác 0 nếu có:

- Speaker overlap giữa split.
- Utterance hoặc SHA-256 overlap giữa split.
- Enrollment overlap với meeting utterance.
- File thiếu, file hỏng, transcript rỗng.
- Sample rate/duration khác metadata ngoài tolerance.

Xuất `reports/data_audit.json` và `reports/data_audit.md`.

### 6.3. Quy mô mục tiêu

- Smoke: 2 cuộc x 2-3 phút.
- Development: tổng khoảng 180 phút canonical speech.
- Validation: tổng khoảng 60 phút.
- Test: tổng khoảng 60 phút.
- Mỗi cuộc: 3-5 người, 3-5 thiết bị, dài 5-10 phút.
- Khoảng nghỉ giữa lượt nói ở v1: ngẫu nhiên 0,6-1,2 giây.
- `merge_gap` của VAD phải nhỏ hơn khoảng nghỉ tối thiểu, mặc định không quá 0,3 giây, để một segment không chứa hai lượt của hai người khác nhau.

Nếu số lượng utterance của một speaker không đủ cả enrollment và meeting content, loại speaker đó và ghi lý do; không được hạ quy tắc chống rò rỉ.

---

## 7. Sinh cuộc họp và nhiều nguồn mô phỏng

### 7.1. Tạo canonical meeting

1. Chọn speaker trong đúng split.
2. Giữ riêng enrollment utterance trước.
3. Chọn các utterance còn lại và xếp thành lượt nói.
4. Chèn khoảng nghỉ theo config.
5. Tạo một canonical timeline duy nhất.
6. Render clean stem riêng cho từng speaker trên cùng timeline.
7. Đặt `overlap=false` cho mọi turn ở phiên bản này.

### 7.2. Render thiết bị

Với speaker `s` và device `d`:

```text
x_d(t) = sum_s [h_(s,d)(t) * y_s(t)] + n_d(t)
```

Trong đó:

- `y_s`: clean stem của speaker trên canonical timeline.
- `h_(s,d)`: RIR riêng cho cặp speaker-device.
- `n_d`: nhiễu riêng của device.

Ràng buộc bắt buộc:

- Mỗi source dùng cùng turn order, transcript và canonical timestamp.
- Khoảng cách/gain phải phụ thuộc cả speaker và device.
- Geometry gồm vị trí và hướng speaker/device phải nhất quán trong cả session; chỉ thay đổi khi recipe khai báo một movement event rõ ràng.
- Trong mỗi cuộc, ít nhất hai speaker có device gần nhất khác nhau.
- Không được convolve toàn bộ final mix bằng một RIR duy nhất rồi gọi đó là multi-device simulation.
- Lưu clean contribution của từng speaker ở chế độ debug để kiểm tra, nhưng không truyền vào inference.

### 7.3. Các profile

`easy`:

- SNR cao, ít vang.
- Offset nhỏ, không hoặc rất ít drift.
- Không codec degradation nghiêm trọng.

`moderate`:

- Mỗi speaker có một hoặc hai device tương đối gần.
- SNR, RT60, gain và codec khác nhau giữa nguồn.
- Có offset và drift đo được.

`stress`:

- Một số nguồn xa, vang hoặc có clipping/dropout.
- SNR thấp hơn và clock drift lớn hơn.
- Không tạo trường hợp bất khả thi cho tất cả nguồn cùng lúc; ít nhất một nguồn phải còn hiểu được trong phần lớn segment.

Các khoảng tham số cụ thể nằm trong YAML và phải được ghi trong báo cáo. Agent phải dùng giá trị thực tế hợp lý, có nguồn giải thích trong comment/config nếu cần, nhưng không được tối ưu tham số bằng test.

### 7.4. Nhiễu khi chỉ dùng VIVOS

Cho phép:

- White, pink, brown và speech-shaped noise sinh bằng thuật toán.
- Hum 50 Hz và harmonic.
- Impulse/click mức nhẹ.
- Room tone lấy từ vùng im lặng của chính file VIVOS sau khi kiểm tra không có tiếng nói.
- Babble tạo từ các utterance VIVOS khác trong cùng split, như một profile tùy chọn.

Không cho phép tải tập noise bên ngoài. Ground truth noise/SNR chỉ dùng để báo cáo mức khó, không dùng làm feature inference.

SNR ground truth phải được tính trên speech-active samples. Sau khi cộng các thành phần âm học mới áp device response, clock transform và codec. Peak normalization chỉ được dùng theo quy tắc cố định; clipping chỉ xuất hiện khi recipe chủ động bật augmentation và phải có nhãn.

### 7.5. Offset và drift

Sau khi render tín hiệu trên canonical timeline:

- Thêm start offset riêng cho từng device.
- Mô phỏng clock drift bằng resampling tỷ lệ rất nhỏ.
- Có thể thêm dropout/codec sau drift theo recipe.
- Lưu phép biến đổi thật để đánh giá đồng bộ.

### 7.6. Tính tái lập

- Seed cho Python, NumPy và PyTorch.
- Mọi random choice đi qua generator được truyền rõ ràng.
- Recipe lưu seed và toàn bộ tham số đã lấy mẫu.
- Cùng manifest, recipe, code và dependency phải tạo cùng waveform checksum hoặc sai khác số học trong tolerance được ghi rõ.
- Cache audio là tùy chọn; recipe và manifest mới là nguồn sự thật.

### 7.7. Command và nghiệm thu

```bash
python -m meeting_pipeline.cli simulate generate \
  --config configs/experiment/smoke.yaml
```

Kiểm tra tự động:

- Đúng số nguồn và thời lượng.
- Timeline và transcript giống recipe.
- Mỗi nguồn có cùng canonical event sau khi áp mapping thật.
- Device gần speaker A có direct-path energy của A cao hơn device xa trong phần lớn turn của A.
- Offset/drift đo trực tiếp từ waveform phù hợp recipe trong tolerance.
- Không có NaN, clipping ngoài cấu hình hoặc file rỗng.

---

## 8. Đồng bộ nhiều nguồn

### 8.1. Thuật toán

1. Decode và resample tất cả nguồn về 16 kHz mono, giữ file gốc.
2. Chọn reference source theo coverage/quality sơ bộ, không mặc định source đầu tiên.
3. Ước lượng coarse offset bằng GCC-PHAT hoặc normalized cross-correlation.
4. Chia file thành nhiều cửa sổ để ước lượng offset cục bộ.
5. Fit quan hệ offset theo thời gian bằng robust linear regression để tìm drift.
6. Resample/time-warp về canonical reference.
7. Cắt/pad để các nguồn có cùng timeline.
8. Tính alignment residual và cảnh báo nguồn không đáng tin.

Không dùng offset/drift trong recipe khi chạy thuật toán; recipe chỉ dùng để chấm điểm.

### 8.2. Artifact

- `aligned/<source_id>.wav`.
- `clean_reference.wav` chỉ trong bộ artifact đánh giá mô phỏng, không được đưa vào product inference.
- `sync_report.json`: offset/drift dự đoán, residual, cảnh báo.
- Đồ thị offset theo cửa sổ cho failure cases.

### 8.3. Metric và điều kiện qua bước

- Offset MAE, median và p95 theo mili giây.
- Drift error theo ppm.
- Residual alignment error theo cửa sổ.
- Tỷ lệ nguồn đồng bộ thành công.

Mục tiêu trên profile `moderate`:

- Median absolute alignment error không quá 20 ms.
- p95 không quá 50 ms.
- Không làm mất hoặc lặp vùng audio ở biên mà không ghi cảnh báo.

Nếu chưa đạt, agent phải sửa đồng bộ trước khi tối ưu fusion.

---

## 9. VAD và phân đoạn chung

### 9.1. Quy trình

1. Chạy Silero VAD trên các nguồn đã đồng bộ.
2. Chuẩn hóa posterior/score theo source nếu cần.
3. Tạo timeline chung bằng max hoặc quality-weighted aggregation của VAD score.
4. Áp min speech, min silence, merge gap và padding từ config.
5. Cắt cùng `[start, end]` từ mọi nguồn.

Không được để mỗi nguồn sinh một danh sách segment riêng cho các bước sau.

Giá trị khởi đầu cho smoke config: `min_speech=0.25s`, `merge_gap<=0.30s`, `padding=0.15s`, `max_segment=15s`. Các giá trị có thể đổi bằng validation. Segment quá ngắn để trích speaker embedding phải được pad trong giới hạn hoặc gắn cờ `insufficient_speaker_evidence`; không được tạo speaker confidence giả.

### 9.2. Đánh giá

- Frame precision, recall, F1.
- Event detection F1.
- Boundary absolute error với collar 200 ms.
- Over-segmentation và under-segmentation.

Ground-truth speech boundaries chỉ dùng chấm điểm và phân tích. Báo cáo đầu cuối bắt buộc dùng segment do VAD dự đoán, không dùng oracle segmentation.

Mục tiêu profile `moderate`: speech frame F1 tối thiểu 0,90. Profile `stress` được báo cáo riêng, không che bằng trung bình chung.

---

## 10. Enrollment và nhận dạng người nói

### 10.1. Enrollment

- Tạo thử nghiệm với tổng enrollment khoảng 5, 15 và 30 giây mỗi người.
- Trích ECAPA embedding cho từng file.
- L2-normalize embedding.
- Prototype là trung bình embedding rồi normalize lại.
- Lưu model ID, revision và checksum/config preprocessing.

### 10.2. Nhận dạng segment

Với mỗi segment:

1. Trích embedding từ từng source đủ chất lượng.
2. Tính cosine similarity với mọi prototype.
3. Tổng hợp score giữa nguồn bằng trọng số chất lượng không dùng ground truth.
4. Chọn speaker có score cao nhất.
5. Trả `unknown` nếu dưới ngưỡng đã chọn trên validation.

Baseline bắt buộc:

- Nguồn cố định.
- Nguồn tốt nhất theo `audio_quality_score`.
- Mean score không trọng số giữa nguồn.
- Quality-weighted multi-source score.
- Cosine nearest centroid mặc định; KNN là baseline bổ sung nếu đã có module benchmark.

### 10.3. Metric

- Accuracy.
- Macro precision, recall, F1.
- Confusion matrix.
- Unknown detection AUROC/F1 nếu có unknown trial.
- Thời gian inference và peak memory.
- Kết quả theo enrollment duration và simulation profile.

Mục tiêu định hướng trên `moderate`, enrollment 30 giây: macro-F1 tối thiểu 0,85. Nếu không đạt, agent không được thay đổi test; phải xuất phân tích lỗi theo speaker, SNR ước lượng và source.

---

## 11. ASR theo đoạn và nguồn

### 11.1. Quy trình

- Chạy PhoWhisper cho từng `segment x source`.
- Dùng cùng decoding config cho mọi baseline.
- Lưu text thô, text chuẩn hóa, token/word timestamp khi model hỗ trợ, confidence, no-speech probability và latency.
- Nếu không có word confidence trực tiếp, xây confidence từ token log probability và ghi rõ cách aggregate.
- Fusion text dùng sequence alignment; không phụ thuộc tuyệt đối vào timestamp từ ASR.

### 11.2. Chuẩn hóa tiếng Việt

Viết một module dùng chung cho reference và hypothesis:

- Unicode NFC.
- Lowercase theo config.
- Chuẩn hóa khoảng trắng.
- Chính sách dấu câu và số phải rõ ràng.
- Không bỏ dấu tiếng Việt.
- Không tự sửa từ bằng reference.

Phải có unit test cho dấu tiếng Việt, số, ký hiệu, khoảng trắng và câu rỗng.

Trong báo cáo chuẩn, CER là metric chính. WER được định nghĩa theo token tách bằng khoảng trắng của transcript VIVOS đã chuẩn hóa; không tự đưa word segmenter ngoài vào giữa các run.

### 11.3. Metric

- CER là chỉ số chính.
- WER là chỉ số phụ.
- Substitution, deletion và insertion.
- Real-time factor, latency/segment và peak memory.
- Kết quả theo source, profile và khoảng chất lượng.

---

## 12. Đặc trưng chấm chất lượng nguồn

Mỗi `segment x source` phải tạo một feature vector. Tối thiểu gồm:

### 12.1. Acoustic features quan sát được

- RMS hoặc LUFS.
- Estimated local SNR từ speech/non-speech region.
- VAD mean/min confidence.
- Clipping ratio.
- Dropout/silence-inside-speech ratio.
- Spectral flatness.
- Zero-crossing rate.
- Energy trong dải giọng nói.
- MFCC summary: mean/std, không đưa toàn chuỗi frame trực tiếp vào Logistic Regression.
- Reverberation proxy như SRMR nếu triển khai ổn định.
- Alignment residual.

### 12.2. ASR features

- Mean/min token log probability hoặc word confidence.
- No-speech probability.
- Compression ratio hoặc repetition score.
- Số token trên giây.
- Tỷ lệ token bất thường/rỗng.

### 12.3. Agreement features

- Số nguồn đồng ý với candidate word.
- Weighted agreement.
- Edit similarity giữa hypothesis và medoid hypothesis.
- Stability của nguồn ở các segment lân cận.

### 12.4. Chống leakage

`oracle_snr`, clean stem, reference text, reference speaker, true offset/drift và profile label không được nằm trong feature vector inference. Chúng chỉ dùng phân tầng báo cáo.

Chuẩn hóa feature chỉ bằng thống kê development. Fit scaler, imputer và classifier trong một `sklearn.Pipeline` để tránh leakage.

### 12.5. Hai loại điểm nguồn

Không dùng một tên `source quality` mơ hồ cho mọi stage. Phải tách:

- `audio_quality_score` trong `[0,1]`: chỉ dùng acoustic/VAD/sync feature quan sát được. Dùng cho chọn sync reference, weighting speaker score và chẩn đoán audio.
- `transcript_quality_score` trong `[0,1]`: dùng `audio_quality_score` cùng ASR/agreement feature. Dùng cho best-source transcript và fusion.

Phiên bản đầu tính `audio_quality_score` bằng weighted mean của các feature đã map về `[0,1]`; dấu và trọng số nằm trong config, chọn trên validation. Feature tốt như estimated SNR/VAD confidence mang dấu dương; clipping, dropout, reverberation và alignment residual mang dấu âm. Không dùng loudness đơn lẻ làm kết luận nguồn gần hơn.

Speaker score cho candidate `s` phải tổng hợp rõ ràng:

```text
speaker_score(s) = sum_d [w_d * cosine(e_d, prototype_s)] / sum_d w_d
w_d = max(epsilon, audio_quality_score_d) ^ temperature
```

`temperature` và ngưỡng unknown chỉ được chọn trên validation. `F1_BEST_SEGMENT` chọn hypothesis có `transcript_quality_score` cao nhất. Trường `source_scores` trong final timeline mặc định biểu diễn `transcript_quality_score`; UI phải ghi đúng tên, không gọi chung là khoảng cách tới người nói.

---

## 13. Gộp transcript có trọng số

### 13.1. Baseline bắt buộc

Mọi baseline phải chạy trên cùng split, ASR output và normalization:

- `F0_FIXED`: một source cố định được chọn trước validation/test.
- `F1_BEST_SEGMENT`: chọn toàn bộ transcript từ source có `transcript_quality_score` cao nhất ở segment.
- `F2_ORACLE_BEST`: chọn source có CER thấp nhất so với reference; chỉ là cận trên, không phải hệ thống hợp lệ.
- `F3_ROVER`: ROVER/confusion network không trọng số.
- `F4_ASR_WEIGHTED`: trọng số chỉ từ ASR confidence.
- `F5_RULE_WEIGHTED`: acoustic + ASR + agreement với trọng số cấu hình thủ công chọn trên validation.
- `F6_LEARNED`: Logistic Regression dự đoán xác suất candidate word đúng.

Không được bỏ `F0`, `F1`, `F3` hoặc `F6` dù kết quả xấu.

### 13.2. Word alignment và confusion network

1. Tokenize text đã chuẩn hóa.
2. Chọn backbone hypothesis bằng medoid hoặc confidence tổng thể.
3. Căn chỉnh các hypothesis bằng dynamic programming.
4. Xây confusion bins có insertion/deletion.
5. Tính vote cho mỗi candidate từ source confidence và candidate correctness probability.
6. Decode chuỗi cuối, cho phép epsilon/deletion.
7. Lưu toàn bộ provenance.

Các trường hợp lặp từ, câu rỗng, nguồn thiếu segment, punctuation và unequal tokenization phải có unit test.

### 13.3. Học fusion weights

- Căn candidate word development với reference để tạo nhãn đúng/sai.
- Group split hoặc group cross-validation theo `meeting_id`, không shuffle từng word độc lập.
- Fit Logistic Regression có class weighting nếu nhãn mất cân bằng.
- Chọn regularization/calibration bằng validation.
- Khóa scaler, feature list, coefficient, threshold và decoder config trước test.
- Test không được dùng để chọn feature hoặc hệ số.

### 13.4. Provenance

Mỗi từ đầu ra phải ghi:

- Candidate token.
- Các source đề xuất token đó.
- ASR confidence từng source.
- `audio_quality_score` và `transcript_quality_score` từng source.
- Agreement score.
- Xác suất đúng dự đoán.
- Source đại diện.

`primary_source_id` của đoạn là source có tổng mass đóng góp cao nhất. Cắt evidence clip từ source này, đồng thời giữ clip cùng timestamp từ mọi source để người dùng đối chiếu.

- Mỗi token provenance phải có `start_sec` và `end_sec` trên global timeline khi timestamp thật sự có sẵn. Timestamp local phải được đổi bằng sync mapping. Nếu model không cung cấp timestamp/confidence thì để `null` và tắt feature tương ứng; không được tạo giá trị giả.
- Dấu câu không có bằng chứng âm học phải có `representative_source_id=null` hoặc tuân theo một quy tắc gắn nguồn được mô tả và kiểm thử rõ ràng.

### 13.5. Metric và ablation

- CER, WER, S/D/I.
- Source switches trên phút và trên segment.
- Phần trăm từ lấy từ mỗi source.
- Runtime và compute multiplier so với ASR một nguồn.
- Runtime phải tách thời gian tải/warm-up model khỏi inference; báo rõ CPU/CUDA/MPS, model revision và batch size.
- Bootstrap confidence interval theo meeting, không bootstrap từng word.

Ablation bắt buộc:

1. ASR features.
2. Acoustic features.
3. Agreement features.
4. ASR + acoustic.
5. ASR + agreement.
6. Tất cả feature.

Điều kiện phát biểu “fusion cải thiện”:

- `F6_LEARNED` phải tốt hơn ít nhất một baseline tự động có ý nghĩa trên test.
- Không kém `F0_FIXED` quá 0,5 điểm CER tuyệt đối.
- Báo cáo khoảng tin cậy và số meeting; không chỉ đưa trung bình tổng.
- Nếu không đạt, vẫn hoàn thành pipeline nhưng kết luận phải ghi rõ fusion chưa cải thiện ổn định.

---

## 14. Ghép speaker và transcript thành timeline

Timeline cuối phải được tạo từ segment timeline chung:

- Timestamp lấy từ VAD đã map về canonical timeline.
- Speaker lấy từ multi-source speaker identification.
- Text lấy từ fusion.
- Confidence phải được hiệu chỉnh hoặc ghi rõ chỉ là score tương đối.
- Evidence clip được cắt từ audio đã đồng bộ, không cắt lại từ file chưa đồng bộ.

Metric đầu cuối:

- Speaker-attributed CER.
- Speaker-attributed WER.
- Tỷ lệ segment đúng speaker và transcript dưới một ngưỡng CER cấu hình.
- Timestamp boundary error.
- Tổng real-time factor.
- Peak memory.

Xuất failure case package cho các segment tệ nhất, gồm reference, mọi hypothesis, feature, quyết định fusion, provenance và audio từng source.

---

## 15. Artifact đầu ra chuẩn

Mỗi lần chạy tạo một thư mục bất biến:

```text
artifacts/runs/<run_id>/
├── resolved_config.yaml
├── environment.json
├── manifest_hash.json
├── logs/
├── synchronized_audio/
├── segments/
│   └── <segment_id>/
│       ├── phone_01.wav
│       ├── phone_02.wav
│       └── ...
├── hypotheses/
├── timeline.json
├── transcript.txt
├── sync_report.json
├── source_scores.csv
├── metrics.json
├── metrics_by_profile.csv
├── baseline_comparison.csv
├── provenance.jsonl
└── failure_cases/
```

`run_id` chứa timestamp và hash config ngắn. Không sửa artifact của run đã hoàn thành; chạy lại phải tạo run mới.

---

## 16. Giao diện demo tối giản

Sử dụng Streamlit, nhưng logic pipeline không được đặt trong file giao diện. UI chỉ gọi service/API Python đã kiểm thử.

### 16.1. Khu vực đăng ký

- Nhập tên hoặc speaker ID.
- Tải một hoặc nhiều file enrollment.
- Hiển thị thời lượng hợp lệ.
- Báo lỗi nếu quá ngắn, không đọc được hoặc không phát hiện tiếng nói.
- Cho phép xóa và đăng ký lại trước khi chạy.

### 16.2. Khu vực cuộc họp

- Tải từ 2 đến 5 file nguồn.
- Đặt tên nguồn hoặc dùng tên file.
- Hiển thị duration, sample rate và trạng thái kiểm tra.
- Nút `Xử lý cuộc họp` và progress theo stage.

### 16.3. Kết quả

- Tóm tắt trạng thái đồng bộ của mỗi nguồn.
- Trình phát các file đã đồng bộ.
- Timeline dạng bảng: thời gian, người nói, transcript, confidence và nguồn chính.
- Khi chọn một dòng, phát evidence clip từ nguồn chính.
- Cho phép chuyển sang clip cùng timestamp của nguồn khác.
- Hiển thị source scores, hypothesis từng nguồn và word provenance ở phần chi tiết, không làm rối màn hình chính.
- Tải `timeline.json`, `transcript.txt`, `baseline_comparison.csv` và audio đã đồng bộ.
- Có thể tải một ZIP chứa toàn bộ artifact dành cho người dùng; phải chống path traversal và không đưa ground truth/recipe vào product export mặc định.
- Luôn hiển thị nhãn `Dữ liệu mô phỏng từ VIVOS` khi demo đang dùng fixture synthetic.

Thiết kế:

- Bố cục một cột chính hoặc hai cột ở màn hình rộng.
- Màu trung tính, typography rõ, khoảng trắng đủ.
- Không dùng icon/emoji trang trí.
- Không hiển thị thuật ngữ kỹ thuật không cần thiết ở luồng chính.
- Lỗi phải nói rõ file/stage và cách khắc phục.

Demo development phải có nút hoặc command nạp sẵn một synthetic meeting smoke fixture. Demo production path không được đọc ground truth.

---

## 17. CLI bắt buộc

Tên option có thể điều chỉnh nhất quán, nhưng phải hỗ trợ tương đương:

```bash
# Chuẩn bị và audit VIVOS
python -m meeting_pipeline.cli data prepare --config configs/data/vivos.yaml
python -m meeting_pipeline.cli data audit --manifest data/manifests/vivos.jsonl

# Tạo dữ liệu mô phỏng
python -m meeting_pipeline.cli simulate generate --config configs/experiment/smoke.yaml
python -m meeting_pipeline.cli simulate generate --config configs/experiment/full.yaml

# Chạy một cuộc họp đầu cuối
python -m meeting_pipeline.cli pipeline run \
  --config configs/experiment/smoke.yaml \
  --meeting-id meeting_smoke_001

# Huấn luyện thành phần fusion nhẹ
python -m meeting_pipeline.cli fusion train \
  --config configs/fusion/default.yaml \
  --split development

# Đánh giá validation/test
python -m meeting_pipeline.cli evaluate run \
  --config configs/experiment/full.yaml \
  --split validation

# Sinh báo cáo
python -m meeting_pipeline.cli report build --run-dir artifacts/runs/<run_id>

# Chạy demo
streamlit run app/streamlit_app.py
```

Mỗi command phải có `--help`, exit code đúng và log stage đang chạy.

---

## 18. Kiểm thử

### 18.1. Unit test bắt buộc

- Parse VIVOS manifest và transcript.
- Split leakage detector.
- Enrollment/meeting disjoint check.
- Text normalization tiếng Việt.
- Timeline mapping device-to-canonical.
- Offset/drift application và inverse mapping.
- Segment padding/clamping ở biên.
- Acoustic feature không tạo NaN/Inf.
- Word edit alignment.
- Confusion bin insertion/deletion/repetition.
- Feature scaler không fit trên validation/test.
- Primary source và word provenance calculation.
- CER/WER/S/D/I bằng ví dụ biết trước.

### 18.2. Integration test bắt buộc

- Tạo fixture cực nhỏ từ waveform tổng hợp hoặc một sample VIVOS được cấu hình cục bộ.
- Chạy `recipe -> render -> sync -> VAD -> segment`.
- Với model adapters mock, chạy `enrollment -> speaker -> ASR -> fusion -> timeline`.
- Một smoke test có model thật được đánh dấu `slow` và có thể chạy riêng.
- Kiểm tra artifact schema và mọi đường dẫn evidence tồn tại.

### 18.3. Regression

- Cùng fixture/config/seed phải cho cùng recipe và metric trong tolerance.
- Lưu expected JSON nhỏ; không lưu audio lớn trong Git.
- Không snapshot toàn bộ log hoặc output phụ thuộc máy.

### 18.4. Lệnh chất lượng

```bash
ruff format --check .
ruff check .
mypy src/meeting_pipeline
pytest -q
pytest -q -m slow
```

README phải phân biệt test nhanh, test cần model và full experiment.

---

## 19. Báo cáo và bảng kết quả

Agent phải sinh báo cáo Markdown và CSV, không chỉ in ra console.

### 19.1. Bảng speaker identification

Các cột tối thiểu:

- Encoder/classifier.
- Enrollment duration.
- Fusion strategy giữa source.
- Accuracy, macro precision, recall, F1.
- Unknown F1 nếu có.
- Runtime và peak memory.
- Profile.

### 19.2. Bảng transcript fusion

Các cột tối thiểu:

- Method `F0` đến `F6`.
- CER, WER, substitutions, deletions, insertions.
- 95% bootstrap CI theo meeting.
- Source switches/minute.
- Runtime, real-time factor và compute multiplier.
- Profile.

### 19.3. Bảng đầu cuối

- Sync median/p95 error.
- VAD precision/recall/F1.
- Speaker macro-F1.
- CER/WER.
- Speaker-attributed CER/WER.
- Segment joint correctness.
- Total runtime và memory.

### 19.4. Phân tích

- Kết quả riêng `easy`, `moderate`, `stress`.
- Ablation theo nhóm feature.
- Failure cases điển hình.
- Giới hạn của dữ liệu mô phỏng.
- Không lựa chọn hoặc ẩn baseline dựa trên kết quả xấu.

---

## 20. Thứ tự thực hiện và cổng nghiệm thu

Agent phải thực hiện theo thứ tự. Không chuyển sang full experiment khi cổng trước chưa qua.

### Milestone 0 — Preflight

Công việc:

- Đọc `AGENTS.md` nếu có.
- Kiểm kê source code, config và tài liệu hiện có.
- Xác định vị trí VIVOS và định dạng transcript.
- Xác nhận môi trường Python, `ffmpeg`, CPU/CUDA/MPS và dung lượng đĩa.
- Ghi `reports/preflight.md`; không đọc hoặc chuyển `audio-notes/` thành yêu cầu.

Qua cổng khi:

- Có đường dẫn VIVOS cấu hình được và ít nhất một file đọc thành công, hoặc blocker được báo chính xác.
- Có quyết định rõ module nào tái sử dụng/module nào cần tạo.
- Không có download corpus ngoài VIVOS.

### Milestone 1 — Nền tảng repository

Công việc:

- Tạo cấu trúc package, config, logging và schema.
- Viết README cài đặt.
- Thiết lập lint, type check và test.

Qua cổng khi:

- Import package thành công.
- `ruff`, `mypy`, unit test nền tảng qua.
- Config smoke được resolve và validate.

### Milestone 2 — VIVOS manifest và split

Công việc:

- Parse VIVOS.
- Chuẩn hóa transcript.
- Tạo manifest, enrollment mapping và split.
- Viết audit chống leakage.

Qua cổng khi:

- Audit không có overlap.
- Báo cáo số speaker, utterance, duration theo split đầy đủ.
- Mọi enrollment file khác meeting file.

### Milestone 3 — Synthetic multi-device generator

Công việc:

- Canonical meeting recipe.
- Speaker stems.
- Per-speaker/per-device RIR.
- Noise, codec, offset và drift.
- Smoke fixtures và kiểm thử.

Qua cổng khi:

- Hai smoke meetings render thành công.
- Các source thật sự là cùng một event.
- Recipe có thể tái tạo waveform.
- Kiểm tra proximity và mapping qua.

### Milestone 4 — Đồng bộ và VAD

Công việc:

- GCC-PHAT/correlation.
- Sliding-window drift estimation.
- Aligned audio.
- Shared VAD timeline.

Qua cổng khi:

- Đạt mục tiêu alignment trên smoke/moderate.
- VAD F1 đạt mục tiêu trên moderate smoke.
- Segment timestamps giống nhau ở mọi source.

### Milestone 5 — Speaker identification và ASR

Công việc:

- Enrollment prototypes.
- Single/multi-source speaker baselines.
- PhoWhisper adapter.
- ASR artifact và metric.

Qua cổng khi:

- Một smoke meeting chạy hết speaker + ASR.
- Không dùng reference trong inference trace.
- Artifact có model/config version và latency.

### Milestone 6 — Transcript fusion

Công việc:

- Alignment và confusion network.
- F0-F6.
- Feature extraction, training và calibration.
- Provenance và evidence clips.

Qua cổng khi:

- Unit tests alignment/fusion qua.
- Tất cả baseline có kết quả trên smoke.
- Mỗi output word có provenance hợp lệ.
- Test feature path không chứa trường oracle/reference.

### Milestone 7 — Full experiment

Công việc:

- Sinh development/validation/test.
- Train trên development.
- Chọn config trên validation.
- Khóa config và chạy test một lần.
- Sinh bảng, CI, ablation và failure cases.

Qua cổng khi:

- Có data audit và run manifest.
- Có bảng F0-F6 và speaker benchmark.
- Kết quả tách theo profile.
- Kết luận đúng với số liệu, kể cả khi fusion không thắng.

### Milestone 8 — Demo

Công việc:

- Enrollment UI.
- Multi-file upload.
- Progress và error handling.
- Timeline, source scores, provenance và audio playback/download.

Qua cổng khi:

- Người dùng chạy được smoke fixture từ đầu đến cuối.
- Mỗi timeline row phát đúng evidence clip.
- Tải được aligned audio, timeline JSON và transcript.
- UI không phụ thuộc ground truth.

---

## 21. Quy trình làm việc bắt buộc cho agent

1. Đọc toàn bộ tài liệu này trước khi sửa code.
2. Kiểm tra repository và tái sử dụng module đúng nếu đã tồn tại; không tạo pipeline song song trùng chức năng.
3. Ghi một checklist ngắn theo Milestone 0-8 trong báo cáo tiến độ.
4. Thực hiện từng milestone và chạy test tương ứng trước khi chuyển bước.
5. Nếu model/dependency không tải được, hoàn thiện adapter, mock test và ghi chính xác blocker; không thay bằng mô hình khác một cách im lặng.
6. Nếu một ngưỡng nghiệm thu không đạt, giữ kết quả, phân tích lỗi và sửa nguyên nhân. Không sửa test data hoặc hạ tiêu chí để làm đẹp số liệu.
7. Không chạy full test nhiều lần để chọn kết quả. Mọi quyết định phải hoàn tất trên development/validation.
8. Ghi dependency, model ID/revision, seed, Git commit và resolved config trong mỗi run.
9. Sau mỗi milestone, cập nhật README và command tái lập.
10. Trước khi bàn giao, chạy toàn bộ quality commands và một smoke end-to-end.

Agent phải dừng và báo rõ thay vì tự suy đoán nếu gặp một trong các trường hợp:

- Không tìm thấy cấu trúc hoặc transcript VIVOS.
- Dữ liệu không đủ để tạo speaker-disjoint split.
- Cần tải thêm corpus âm thanh khác.
- Cần thay đổi phạm vi nói chồng.
- Cần dùng test để điều chỉnh thuật toán.
- Thay đổi schema làm mất tương thích artifact đã tạo.

Nếu chưa tìm thấy VIVOS, agent vẫn phải hoàn thành phần không phụ thuộc dữ liệu của Milestone 1, schema, adapter interface và test dùng fixture/mock. Sau đó báo chính xác đường dẫn/cấu trúc VIVOS cần cung cấp; không được đánh dấu các milestone dữ liệu là hoàn thành.

Agent không cần dừng để hỏi về lựa chọn cài đặt nhỏ đã được mô tả bằng interface/config và không ảnh hưởng hợp đồng đầu ra.

---

## 22. Definition of Done

Chỉ đánh dấu hoàn thành khi tất cả điều kiện sau đúng:

- [ ] Preflight xác định đúng repository và đường dẫn VIVOS; `audio-notes/` không được dùng làm đặc tả.
- [ ] Chỉ VIVOS được dùng làm corpus âm thanh.
- [ ] Manifest và split audit chứng minh không rò rỉ speaker/utterance.
- [ ] Enrollment tách khỏi meeting content.
- [ ] Có generator 3-5 thiết bị từ cùng canonical event.
- [ ] RIR/gain phụ thuộc từng cặp speaker-device.
- [ ] Recipe, seed và config tái tạo được dữ liệu.
- [ ] Đồng bộ offset/drift không đọc ground truth khi inference.
- [ ] Có một shared VAD timeline cho tất cả source.
- [ ] Speaker identification dùng enrollment prototype và chạy được trên speaker chưa thấy khi fit fusion.
- [ ] ASR chạy theo `segment x source`.
- [ ] Có đủ F0-F6 và oracle chỉ được dùng làm cận trên.
- [ ] Không có oracle/reference feature trong inference.
- [ ] Mỗi từ có provenance; mỗi đoạn có primary source và evidence clips.
- [ ] Có aligned audio, timeline JSON, transcript TXT và bảng chỉ số.
- [ ] Có báo cáo speaker, fusion, đầu cuối, ablation và failure cases.
- [ ] Test được chạy sau khi khóa cấu hình.
- [ ] Demo đăng ký, tải nhiều nguồn, xử lý, phát clip và tải artifact hoạt động.
- [ ] `ruff`, `mypy`, unit/integration test và smoke end-to-end qua.
- [ ] README đủ để một người khác cài đặt và tái lập smoke run.
- [ ] Báo cáo ghi rõ giới hạn của dữ liệu mô phỏng VIVOS.

---

## 23. Nội dung bàn giao cuối cùng

Agent phải gửi một báo cáo ngắn gồm:

1. Các module đã tạo hoặc sửa.
2. Lệnh cài đặt và lệnh chạy smoke/full/demo.
3. Đường dẫn artifact của run cuối.
4. Bảng chỉ số chính.
5. Các test đã chạy và kết quả.
6. Các ngưỡng nghiệm thu đạt/chưa đạt.
7. Các giới hạn hoặc blocker còn lại.
8. Những phần cần hiệu chỉnh khi dữ liệu họp thật được bổ sung.

Không được chỉ trả lời “đã hoàn thành” mà thiếu bằng chứng chạy, metric và đường dẫn artifact.
