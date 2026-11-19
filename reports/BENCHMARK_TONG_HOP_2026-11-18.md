# BẢN TỔNG HỌP BENCHMARK HỆ THỐNG

**Phạm vi thực nghiệm:** Đánh giá toàn bộ các giai đoạn ngoài-LLM, pipeline cốt lõi, thành phần còn thiếu và tầng LLM `LoRA B` trên MLX trên mã nguồn hiện hành tại thư mục gốc (`HEAD 38204e16` kèm các chỉnh sửa mới nhất trong `src/` và `configs/`). Ngoại lệ duy nhất chưa đo là bộ **audio cuộc họp tiếng Việt thực tế** (người dùng tách sang bước sau) và throughput **`MongoDB queue` trực tiếp** (máy host chưa cài `mongod`).

**Môi trường & Runtime thực thi:**
* **Phần cứng:** Apple MacBook Air M4 · 16 GB Unified Memory · macOS `arm64`.
* **Môi trường:** `.venv-benchmark` (PyTorch `2.6.0`, Transformers `4.57.6`, Pyannote `3.3.2` / `segmentation-3.0`, WeSpeaker ResNet34-LM, SpeechBrain ECAPA/SepFormer/CRDNN, FunASR FSMN-VAD, Asteroid ConvTasNet, EasyOCR `1.7.2`, VietOCR, `pytesseract 0.3.13`), `.venv-asr-mlx` (`mlx 0.32.3`, `mlx-whisper 0.4.3` cho `vinai/PhoWhisper-medium@55a7e3eb`, `vinai/PhoWhisper-small@a86b604c`, `PhoWhisper-large`, `whisper-large-v3-turbo`), `.venv-llm` (`mlx-lm` cho `Qwen3-4B-Instruct-2507-4bit` + `LoRA B checkpoint-132`), và `web_app/.venv-backend` (FastAPI/Mongo/unit suite).
* **Thư mục script tái lập:** `experiments/benchmark_20261118/` · **Dữ liệu chi tiết (JSON/CSV):** `reports/benchmark_20261118/`.

---

## Tóm tắt Kết quả Chính theo 12 Hạng mục Benchmark (Đợt 1–3)

| Đợt | Hạng mục | Dữ liệu & Cỡ mẫu | Thời gian chạy | Phát hiện & Số liệu nổi bật |
| :-: | :--- | :--- | ---: | :--- |
| **1** | **1. Đồng bộ đa nguồn & Pause/Resume** | 24 ca `sim_short`, 18 ca VIVOS `90s` (offset ±18s, drift 40–1050 ppm), 24 ca pause/resume, 2 phiên `LibriWASN OV20` (4-mic) | `6,80 s` | `full_sync` đạt sai số offset **`1,04 ms`** (ngắn) và **`2,50 ms`** (dài ±18s, giảm từ `6.768,8 ms` no-sync). Drift `450–1050 ppm` giảm sai số **`711,7 → 18,5 ppm`**. `resolve_clocks` tách đúng **12/12 ca** pause/resume cùng âm học với sai số **`0,01–0,04 ms`**, nhưng bị mất landmark khi 2 mic cách xa trong phòng vang (`0/12`). |
| **1** | **2. Speaker Multisource `P0–P3`** | 30 ca `test` (`simulation/manifest`), 3 encoders × 4 policies × 3 mức profiles | `45,76 s` | **`E3_WeSpeaker` + `P2_EMBEDDING_FUSION`** dẫn đầu: Pairwise F1 đạt **`0,8889`** (toàn bộ 30 ca) và **`0,8611`** (20 ca đa mic), vượt `+16,6%` so với `ECAPA P2` (`0,7230`) và vượt `+11,1%` trên đa mic so với `P0/P1` (`0,7500`). |
| **1** | **3. Topic Clustering (`0.22/3` vs `0.08/2`)** | 30 tài liệu `text/manifest` + 60 ca `v2.1/test` + 84 ca `nrv2/test` | `116,81 s` | Nâng `minimum_silhouette = 0,22` giữ được `e5_small` (`ARI = 0,4199`, collapse `6,7%`) trên tập 4 chủ đề tách biệt, nhưng làm `e5_base`/`bge_m3` sụp về 1 cụm **`90%–96,7%`** và khiến `v2.1`/`nrv2` bị fallback về 1 cụm tới **`96,7%–100%`**. |
| **1** | **4. Structured Fields NĐ 30/2020 & Guard** | 3 template DOCX/DOC + 12 ca stress NĐ30 (54 checks) + 60 ca `v2.1` | `2,18 s` | Parse/render DOCX đạt `render_zip_integrity = True`; `0/60` false positive trên `v2.1`. Bộ kiểm tra stress đạt **`33/54` (`61,11%`)**, chỉ ra các ca regex chưa bắt được câu ghép `"bắt đầu... và kết thúc"`, đảo vị trí giờ bế mạc, hoặc từ xen giữa/mệnh đề `"dự kiến"` đi kèm `"nhưng thực tế"`. |
| **1** | **5. OCR Dòng đơn & Trang A4 Bảng biểu** | 93 ảnh dòng (`--psm 7`) + 18 trang A4 có bảng 4×5 (`clean/moderate/stress`) | `130,48 s` | Dòng đơn: `vietocr_transformer` thấp nhất (`CER = 4,39%`, `WER = 12,32%`), `tesseract_best` (`5,03%`). Trang bảng: OpenCV nhận **100%** bảng khi thẳng (`clean/moderate`, `Cell CER = 1,78%` với VietOCR), nhưng rớt xuống **`0%`** khi trang xoay nhẹ **`1,2°`** (`stress`). |
| **2** | **6. ASR MLX Runtime & Guard `< 0,8s`** | 563 câu VIVOS `test` + 136 câu `asr/manifest` + 80 đoạn biên `<0,8s` | `3.883,55 s` | Trên 563 câu VIVOS: **`PhoWhisper-medium MLX`** đạt **WER `5,03%`**, **CER `2,42%`**, `RTF = 0,735`, phủ word confidence `99,82%` — tốt hơn **`PhoWhisper-small MLX`** (`WER 6,55%`, `RTF = 0,211`) là **`-1,57%` (`95% CI [-2,31%, -0,84%]`)**. Trên MPS bị nhiều ca lỗi decode/chất lượng (`24,49%` ở `syn60` với `medium`, `57,48%` với `small`). |
| **2** | **7. Multi-source Fusion & Routing** | 24 ca đa mic (`12 × 2-mic`, `12 × 4-mic`, `96` turns vàng) | `1.002,12 s` | **`F5_RULE_WEIGHTED_CORRECTED` (`ALL`)** đạt **WER `15,19%`** (giảm `-2,08%` có ý nghĩa thống kê so với `F0_FIXED` `17,46%`, `95% CI [-3,65%, -0,63%]`). `Adaptive max=3` tiết kiệm **`35,4%`** lượt gọi ASR (`1,938` vs `3,0`) mà giữ WER `15,50%`. `AUDIO_DELAY_AND_SUM + afftdn` tốn `1,0` lượt ASR/turn nhưng fallback trễ `41/96` turns (`WER 17,87%`). |
| **2** | **8. Core End-to-End Replay (30 ca)** | Toàn bộ 30 ca `test` (`12 × 1-mic`, `9 × 2-mic`, `9 × 4-mic`) | `940,09 s` | `WeSpeaker` nâng Speaker `Pairwise F1` từ `0,7230` (`ECAPA`) → **`0,8889`** (riêng `4-mic`: **`0,5741 → 0,8889`**, đếm đúng `100%` số người nói). Toàn chuỗi với biên Pyannote: `C3 (Audio+afftdn)` đạt tổng `WER = 17,07%` (tốt hơn ở `2-mic`: `14,61%`), `C2 (Transcript F5)` đạt `17,64%`. |
| **3A** | **9. VAD, Overlap Separation, SafeMerge & Retrieval** | 30 ca `test` (`485,6s`), 20 mixture overlap, 120 + 110 truy vấn retrieval, 60 ca context | `1.319,97 s` | VAD: `pyannote3_prod` (`F1 0,9372`, `RTF 0,00799`) vs `silero_vad` (`0,9350`, `RTF 0,00286`). Overlap: `sepformer_whamr` dù `SI-SDR = -5,551 dB` lại cho **`PIT WER = 87,61%` (`best 51,61%`)**, tốt hơn nhiều `libri2mix` (`SI-SDR +4,047 dB`, `PIT WER 108,10%`). Retrieval `v2.1`: `bm25`/`tfidf` dẫn đầu (`MRR 0,9515`), `hybrid_rrf_e5_small` đạt `0,9333`. |
| **3B** | **10. Ingest PDF/Scan, Schema Mapper M1 & Backend** | 3 mẫu DOCX/DOC × 4 dạng PDF/Scan, `ArtifactStore` & FastAPI routes | `92,77 s` | `native_doc_docx` giữ **`2/2` bảng**, còn `vector_pdf` & `ocr_tesseract` mất **`0/2` bảng**. `SchemaMapper` `M1` builtin trả `not_run`, trong khi `Qwen3-4B MLX` nâng recall trên `chi_bo` (`0,4737 → 0,7368`) và `hop_chung` (`0,8947 → 1,0000`). `ArtifactStore` SHA-256 đạt `1.383–2.495 MB/s`. |
| **3C** | **11. LLM Holdout MLX (`LoRA B`), Downstream & Full E2E** | 60 ca Holdout `v2.1` (70 packets), 12 ca `generate_graph_minutes`, 2 phiên Audio→DOCX cold | `5.132,94 s` | **`LoRA B` chạy local MLX 4-bit** đạt `Event F1 = 0,8148`, `Relation F1 = 0,4467`, `State Exact = 0,3333 (14/42)` — tương đương thống kê bản Colab NF4 L4 (`95% CI Δ Relation [-0,158, +0,068]`) nhưng **nhanh gấp `5,27×`** (`9,44 s` vs `49,75 s`). Full Audio→DOCX `2 phút` cold mất `423–493 s` (`Zip OK 100%`). |
| **3D** | **12. ASR Đối chiếu Lớn (`PhoWhisper-large`, `Turbo`, `Wav2Vec2`)** | 136 câu `asr/manifest` + 563 câu VIVOS `test` | `6.111,64 s` | Trên 563 câu VIVOS: **`PhoWhisper-large MLX`** đạt `WER 4,73%` (`RTF 1,390`), hơn `medium MLX` (`5,03%`, `RTF 0,735`) **`-0,37%` (không có ý nghĩa thống kê, `95% CI [-1,21%, +0,45%]`)** nhưng chậm gấp **`1,89×`**. `whisper-large-v3-turbo MLX` đạt `13,44%`, `wav2vec2-vi CPU` đạt `10,61%` siêu nhanh **`RTF 0,031`**. |

---

# PHẦN I — CHI TIẾT ĐỢT 1 (5 BÀI CHẠY NHANH)

## 1. Đồng bộ Đa nguồn & Timeline Pause/Resume
**Script:** [`run_wave1_sync_timeline.py`](../experiments/benchmark_20261118/run_wave1_sync_timeline.py) · **Dữ liệu chi tiết:** [`wave1/sync_timeline/results.json`](benchmark_20261118/wave1/sync_timeline/results.json)

### 1.1. Đồng bộ liên tục (`synchronize_multi_source_audio`) trên tập ngắn và tập dài có offset/drift lớn
> *Lưu ý quy ước dấu:* Trong `simulation/device.py`, hàm `apply_start_offset(+X)` chèn `X` giây im lặng vào đầu file; hàm đồng bộ `synchronize_multi_source_audio` trả về `offset_sec = -X` để dịch ngược về gốc tham chiếu. Số liệu sai số dưới đây so sánh trực tiếp `-pred_offset_sec` với ground-truth offset đã chèn.

| Tập kiểm thử | Cấu hình | Số cặp nguồn | Offset MAE (ms) ↓ | Median (ms) ↓ | P95 (ms) ↓ | Drift MAE (ppm) ↓ | Tỷ lệ `drift_unresolved` |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `sim_short_24` (15–20s, offset `0,04–0,12s`, `drift=0`) | `offset_only` | 48 | **1,04** | 0,0 | 10,0 | 0,00 | 0,0% |
| `sim_short_24` (15–20s, offset `0,04–0,12s`, `drift=0`) | `full_sync` | 48 | **1,04** | 0,0 | 10,0 | 0,00 | 0,0% |
| `vivos_long_low_drift_12` (90s, offset `±2,5..18s`, drift `±40..120 ppm`) | `no_sync` | 24 | 6.768,75 | 5.700,0 | 15.305,0 | 64,81 | 0,0% |
| `vivos_long_low_drift_12` (90s, offset `±2,5..18s`, drift `±40..120 ppm`) | `offset_only` | 24 | **2,50** | 0,0 | 10,0 | 64,81 | 0,0% |
| `vivos_long_low_drift_12` (90s, offset `±2,5..18s`, drift `±40..120 ppm`) | `full_sync` | 24 | **2,50** | 0,0 | 10,0 | **59,00** | 0,0% |
| `vivos_high_drift_6` (90s, offset `4,2s`, drift `±450..1050 ppm`) | `offset_only` | 6 | 33,33 | 30,0 | 50,0 | 711,67 | 0,0% |
| `vivos_high_drift_6` (90s, offset `4,2s`, drift `±450..1050 ppm`) | **`full_sync`** | 6 | 33,33 | 30,0 | 50,0 | **18,48** | 0,0% |

* **Phát hiện giới hạn lượng tử hóa (`100 Hz` = `10 ms`/bin):** Bộ `synchronize_multi_source_audio` bắt offset lớn tới `±18s` gần như tuyệt đối (`MAE 2,5 ms`). Tuy nhiên ở băng thông drift thực tế `40–120 ppm` trong đoạn `90s`, độ trôi tích lũy chỉ khoảng `3,6–10,8 ms` (nhỏ hơn bước lượng tử `10 ms` của envelope `100 Hz`) nên hồi quy tuyến tính gần như ra `0,0 ppm` (`Drift MAE = 59,0 ppm`) trong khi vẫn gán cờ `drift_status = "aligned"`. Ngược lại, khi tổng trôi tích lũy vượt vài frame (`vivos_high_drift_6`, `> 40 ms`), **`full_sync` hạ sai số drift từ `711,67 ppm` xuống còn `18,48 ppm`** (`giảm 97,4%`).
* **Kiểm tra trên 2 phiên `LibriWASN OV20` (4 thiết bị thật: `Nexus`, `Pixel6a`, `Pixel7` so với `Soundcard`, cửa sổ 180s đầu):** Toàn bộ 6 cặp trả về `offset_sec = 0,0`, `drift_ppm = 0,0`, `residual_ms = 5,0`, `drift_status = "aligned"`, giữ nguyên độ tương quan bao năng lượng (`0,597–0,897`) do bản phát hành Zenodo OV20 đã được cắt đồng bộ sẵn về cùng gốc thời gian.

### 1.2. Tách đoạn Pause/Resume bằng `resolve_clocks` (`timeline_alignment.py` + `fingerprints.py`)
Thử nghiệm trên 12 kịch bản `90s`, thiết bị thứ hai ngắt ghi hình `14–24s` ở giữa cuộc họp rồi nối thẳng trong cùng một file:

| Điều kiện âm học | Số ca | Tỷ lệ bắt đủ ≥ 2 span âm học ↑ | `timing_complete` (gồm cả đuôi im lặng) | Sai số Span 2 nếu sync liên tục (ms) ↓ | Sai số Span 1 `resolve_clocks` (ms) ↓ | Sai số Span 2 `resolve_clocks` (ms) ↓ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Chung âm học + nhiễu 22 dB (`shared_acoustics_22db`)** | 12 | **100,0% (12/12)** | 16,67% (2/12)* | 34.041,67 | **0,01** | **0,04** |
| **Hai mic khác vị trí phòng vang (`cross_room_rir`, `rt60=0,28s`, 1,3 m)** | 12 | **0,0% (0/12)** | 8,33% (1/12) | 32.461,67 | 5.208,20 | 19.583,46 |

*\*Ghi chú:* Ở `shared_acoustics_22db`, cả 12/12 ca đều khôi phục chính xác **cả hai đoạn có tiếng nói** dưới `0,05 ms`; lý do `timing_complete = False` ở 10/12 ca là vì phần `~2–3s` **im lặng thuần túy cuối file** không có landmark STFT nên giữ nhãn `origin = "local"`. Ngược lại, trong phòng vang đa mic cách xa nhau (`cross_room_rir`), hàm băm đỉnh phổ STFT bị phá vỡ bởi khác biệt pha/đáp ứng xung phòng khiến không khớp được cặp landmark.

---

## 2. Multi-source Speaker Fusion (`P0–P3`) với WeSpeaker vs ECAPA vs WavLM
**Script:** [`run_wave1_speaker_multisource.py`](../experiments/benchmark_20261118/run_wave1_speaker_multisource.py) · **Dữ liệu chi tiết:** [`wave1/speaker_multisource/summary.csv`](benchmark_20261118/wave1/speaker_multisource/summary.csv)

Đánh giá trên toàn bộ **30 cuộc họp `test`** (`12 × 1-mic`, `9 × 2-mic`, `9 × 4-mic`) từ `simulation/manifest.json`, dùng Pyannote `segmentation-3.0` + `SpeakerTurnDetector` + ngưỡng calibration của từng encoder (`E3`: `0,50 / 0,4143 / 0,1085`; `E1`: `0,40 / 0,5076 / 0,0232`; `E4`: `0,15 / 0,8511 / 0,0`), với `k=3` mẫu enrollment sạch từ `VIVOS test` (+ 2 người ngoài đóng vai distractor):

| Encoder | Chính sách | `none` F1 (30 ca) ↑ | `none` F1 (20 đa mic) ↑ | Sai số đếm người ↓ | `partial` Known Acc ↑ | `partial` Unknown Reject ↑ | `full` Known Acc ↑ | Ambiguous Rate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`E3_WeSpeaker`** | `P0_FIXED_REFERENCE` | 0,8222 | 0,7500 | 0,467 | 0,6154 | 0,8125 | 0,5809 | 0,1571 |
| **`E3_WeSpeaker`** | `P1_TOP1_QUALITY` | 0,8222 | 0,7500 | 0,467 | 0,6250 | 0,8125 | 0,5882 | 0,1571 |
| **`E3_WeSpeaker`** | **`P2_EMBEDDING_FUSION` (mặc định)** | **0,8889** | **0,8611** | **0,400** | **0,6538** | 0,7812 | **0,6103** | 0,1571 |
| **`E3_WeSpeaker`** | `P3_WEIGHTED_SCORE_FUSION` | 0,8889 | 0,8611 | **0,400** | 0,5962 | **0,8438** | 0,5662 | 0,1571 |
| `E1_ECAPA` | `P0_FIXED_REFERENCE` | 0,7270 | 0,6746 | 0,667 | 0,5385 | 0,7500 | 0,5441 | 0,1571 |
| `E1_ECAPA` | `P1_TOP1_QUALITY` | 0,7159 | 0,6561 | 0,700 | 0,5385 | 0,7188 | 0,5368 | 0,1571 |
| `E1_ECAPA` | `P2_EMBEDDING_FUSION` | 0,7230 | 0,6680 | 0,733 | 0,5769 | 0,7500 | 0,5735 | 0,1571 |
| `E1_ECAPA` | `P3_WEIGHTED_SCORE_FUSION` | 0,7230 | 0,6680 | 0,733 | 0,4038 | 0,7500 | 0,4338 | 0,1771 |
| `E4_WavLM` | `P2_EMBEDDING_FUSION` | 0,3813 | 0,4000 | 2,000 | 0,2308 | 0,3750 | 0,1765 | 0,1240 |
| `E4_WavLM` | `P3_WEIGHTED_SCORE_FUSION` | 0,3813 | 0,4000 | 2,000 | 0,0000 | 0,9688 | 0,0000 | 0,2507 |

*(Đầy đủ 36 dòng cấu hình gồm cả `P0/P1` của `E4_WavLM` và chế độ `none` được lưu trong [`wave1/speaker_multisource/summary.csv`](benchmark_20261118/wave1/speaker_multisource/summary.csv).)*
* **Kết luận:** Trên 20 ca đa mic, **`P2_EMBEDDING_FUSION` cùng `E3_WeSpeaker`** cải thiện rõ rệt cả Pairwise F1 gom cụm (`0,7500 → 0,8611`, `+11,1%` so với P0/P1) lẫn độ chính xác nhận danh tính (`0,6538` partial, `0,6103` full) và giảm sai số đếm số lượng người nói xuống thấp nhất (`0,400`).

---

## 3. Topic Clustering (`minimum_silhouette = 0,22` vs `0,08`)
**Script:** [`run_wave1_clustering.py`](../experiments/benchmark_20261118/run_wave1_clustering.py) · **Dữ liệu chi tiết:** [`wave1/clustering/topic_summary.csv`](benchmark_20261118/wave1/clustering/topic_summary.csv), [`realistic_collapse_summary.csv`](benchmark_20261118/wave1/clustering/realistic_collapse_summary.csv)

### 3.1. Trên 30 tài liệu `text/manifest.json` (split `test`, 16 đơn vị/ca, 4 chủ đề chuẩn)

| Text Encoder | `fcm (0.08/min2)` ARI / Collapse | **`fcm (0.22/min3)` ARI / Collapse** | `kmeans (0.08/min2)` ARI | `kmeans (0.22/min3)` ARI | `agg (0.22/min3)` ARI | `hdbscan` ARI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`e5_small` (mặc định)** | 0,4023 / 0,0% | **0,4199 / 6,7%** (`2,87` cụm) | **0,4860** | 0,4183 (`13,3%`) | 0,0494 (`86,7%`) | 0,2907 |
| `e5_base` | 0,4906 / 0,0% | 0,0187 / **96,7%** | 0,5400 | 0,4049 (`33,3%`) | **0,6821** (`0%`) | 0,2857 |
| `minilm` | **0,7291 / 0,0%** | 0,4721 / 0,0% | 0,6981 | **0,7317** (`0%`) | 0,5945 (`0%`) | 0,4741 |
| `bge_m3` | 0,4021 / 0,0% | 0,0471 / **90,0%** | 0,5202 | 0,2126 (`60,0%`) | 0,1516 (`73,3%`) | 0,3177 |

### 3.2. Tác động Fallback về 1 cụm trên kịch bản hội thoại thực tế (`v21_test_60` & `nrv2_test_84`)
Với `e5_small` đang bật ở `configs/minutes.yaml`:

| Bộ dữ liệu | Số ca | `fcm_legacy (0.08/2)` Collapse Rate / Số cụm TB | **`fcm_current (0.22/3)` Collapse Rate / Số cụm TB** | `kmeans (0.22/3)` Collapse Rate | `hdbscan` Collapse Rate |
| :--- | ---: | :---: | :---: | :---: | :---: |
| `v21_test_60` | 60 | 50,00% / 1,500 cụm | **96,67% / 1,033 cụm** | 73,33% | 93,33% |
| `nrv2_test_84` | 84 | 23,81% / 1,929 cụm | **100,00% / 1,000 cụm** | 100,00% | 82,14% |

* **Phát hiện quan trọng cho luận văn:** Việc nâng `minimum_silhouette` từ `0,08` lên **`0,22`** giúp loại bỏ các phân cụm lỏng lẻo khi không rõ chủ đề (`e5_small` tăng nhẹ ARI lên `0,4199` trên bộ 4 chủ đề tách biệt), nhưng trên hội thoại liên mạch thực tế (hoặc với `e5_base`/`bge_m3`), ngưỡng **`0,22` quá khắt khe**, khiến **96,7%–100% cuộc họp bị ép fallback về 1 chủ đề duy nhất**. Cần lưu ý điểm đánh đổi này khi tinh chỉnh cấu hình dàn ý biên bản.

---

## 4. Structured Fields (NĐ 30/2020), Parser Biểu mẫu & Graph Export Guard
**Script:** [`run_wave1_structured_export.py`](../experiments/benchmark_20261118/run_wave1_structured_export.py) · **Dữ liệu chi tiết:** [`wave1/structured_export/results.json`](benchmark_20261118/wave1/structured_export/results.json)

* **Chuẩn hóa & ánh xạ 3 mẫu Word thực tế (`doc_parser` + `M0RuleSchemaMapper`):**
  * `bien_ban_hop_chi_bo.docx` (`.docx`): `26` anchors (gold `22`), `26` schema fields, recall nhóm `semantic_type` = `0,4737`, convert `0,009s` + parse/map `0,064s`.
  * `mau_bien_ban_hop_chung.doc` (`.doc` → DOCX qua LibreOffice `soffice`): `38` anchors (gold `23`), `38` schema fields, recall `semantic_type` = **`0,8947`**, convert `2,038s` + parse/map `0,005s`.
  * `bien_ban_ban_giao_thiet_bi.docx` (`.docx`): `24` anchors, `24` schema fields, convert `0,006s` + parse/map `0,011s`.
  * **Kiểm tra render DOCX & `guard_graph_export`:** Đầu ra `rendered_chung.docx` đạt **`render_zip_integrity = True`** (`ZipFile.testzip() is None`, SHA-256 `7a2a67b0dde307b719589123eb35fcfcd19d0ee6d948f3e98b283fdb91018c38`).
* **Kiểm tra sinh nhầm (`False Positive`) trên toàn bộ 60 transcript holdout `v2.1/test`:** Ghi nhận **`0/60`** trường hợp nhận nhầm ngày/giờ họp (`spurious_date_clock_hits = 0`) và **`0/60`** nhận nhầm biểu quyết (`spurious_vote_round_hits = 0`).
* **Kiểm tra quy tắc `structured_fields.py` trên 12 tình huống stress NĐ 30 (`54` kiểm tra con):** Đạt **`33/54` (`61,11%`)**. Các ca đạt 100% gồm `nd30_01` (số nói tiếng Việt `"hai mươi sáu"`, `"hai lăm phiếu"`), `nd30_06` (chặn `"chưa kiểm phiếu"`), `nd30_07` (biểu quyết kèm phiếu trắng), `nd30_08` (2 vòng biểu quyết) và `nd30_10` (thông qua biên bản bình thường), đồng thời ghi nhận các trường hợp thất bại trong bộ stress:
  1. `nd30_12`: Câu ghép `"bắt đầu lúc 13 giờ 05 phút và kết thúc lúc 15 giờ 20 phút"` trích được giờ kết thúc nhưng bỏ sót `start_hour`/`start_minute` (`got: null`).
  2. `nd30_03` & `nd30_11`: Câu chứa `"chiều ngày ... khai mạc lúc ..."` hoặc `"phòng hai không một"` khiến `day/month/year` và `start_hour/start_minute` trả `null`.
  3. `nd30_05`: Câu có cả `"dự kiến ... ngày 20/11/2026 nhưng thực tế ... 8h25 ngày 21/11/2026"` nhận nhầm `day = "20"` và bỏ sót `start_hour`/`start_minute`.
  4. `nd30_02` & `nd30_04`: Cấu trúc đảo `"Đến 16:45 toàn bộ cuộc họp bế mạc."` không trích được `end_hour`/`end_minute`; ca `nd30_04` trích đúng giờ kết thúc `10:45` (vượt bẫy `"Phần thảo luận kết thúc lúc 9h15"`), nhưng `start_minute` trả chuỗi `"00"` thay vì `"0"`.
  5. `nd30_09`: Câu `"Biên bản này hiện chưa có ai ký, sẽ ký sau khi rà soát."` chưa kích hoạt trạng thái `CONFLICTING` trên `PlaceholderType.FIXED_TEXT` (`signature_conflict = False`).

---

## 5. OCR Dòng đơn (`--psm 7`) & Trang A4 Bảng biểu (`--psm 3` + OpenCV)
**Script:** [`run_wave1_ocr.py`](../experiments/benchmark_20261118/run_wave1_ocr.py) · **Dữ liệu chi tiết:** [`wave1/ocr/line_summary.csv`](benchmark_20261118/wave1/ocr/line_summary.csv), [`page_table_summary.csv`](benchmark_20261118/wave1/ocr/page_table_summary.csv)

### 5.1. Nhận dạng Dòng đơn (`93` ảnh test = `30 clean + 30 moderate + 30 stress + 3 blank`)
*(Đối chiếu 5 engine chạy ổn định trên tập kiểm thử: Tesseract Fast/Best, EasyOCR, VietOCR Seq2Seq/Transformer).*

| Engine OCR | CER Tổng (93) ↓ | WER Tổng (93) ↓ | Clean CER | Moderate CER | Stress CER | Exact Match ↑ | Blank Hallucinations (/3) ↓ | Tổng thời gian |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tesseract_fast` (đang dùng web) | 0,0539 | 0,1783 | 0,0512 | 0,0499 | 0,0519 | 0,4624 | 3 | 10,91 s |
| `tesseract_best` | 0,0503 | 0,1699 | 0,0499 | 0,0459 | 0,0486 | **0,5161** | 2 | 14,29 s |
| `easyocr` | 0,0628 | 0,2381 | 0,0499 | 0,0486 | 0,0892 | 0,2903 | **1** | **2,29 s** |
| `vietocr_seq2seq` | 0,0508 | 0,1485 | 0,0452 | 0,0333 | 0,0472 | 0,4301 | 3 | 3,69 s |
| **`vietocr_transformer`** | **0,0439** | **0,1232** | **0,0259** | **0,0273** | **0,0419** | 0,5054 | 3 | 27,40 s |

### 5.2. Nhận dạng Trang A4 hoàn chỉnh & Bảng phân công 4×5 (`18` trang = `6` trang × `3` mức nhiễu)

| Cấu hình xử lý trang | Tổng 18 trang Page CER / WER | Clean Cell CER / EM | Moderate Cell CER / EM | Stress (nghiêng 1,2°) Table Detect / Cell EM | Giây / trang |
| :--- | :---: | :---: | :---: | :---: | ---: |
| `raw_tess_fast_psm3` (nguyên trang) | 0,1032 / 0,1527 | — | — | — | 0,347 s |
| `raw_tess_best_psm3` (nguyên trang) | **0,1025** / **0,1483** | — | — | — | 0,630 s |
| `prod_opencv_tess_fast` (`ocr.py` hiện tại) | 0,1221 / 0,1711 | 0,0667 / 0,8750 | 0,0778 / 0,8375 | **0,0% (0/6)** / 0,0000 | **0,331 s** |
| `prod_opencv_tess_best` (`ocr.py` + `tessdata_best`) | 0,1209 / 0,1658 | 0,0670 / **0,8917** | 0,0823 / 0,8229 | **0,0% (0/6)** / 0,0000 | 0,611 s |
| `opencv_cells_vietocr` (crop ô + VietOCR) | 0,1029 / 0,1539 | **0,0307** / 0,8167 | **0,0178** / **0,8708** | **0,0% (0/6)** / 0,0000 | 1,613 s |

* **Phát hiện kiến trúc cốt lõi của `ocr.py`:** Trên ảnh phẳng (`clean` và `moderate`), bộ lọc hình thái học OpenCV nhận diện đúng **100% (12/12)** cấu trúc bảng biểu, và khi kết hợp cắt từng ô đưa vào `VietOCR Transformer`, lỗi ký tự trong ô giảm mạnh xuống **`1,78%–3,07%`**. Tuy nhiên, chỉ với độ nghiêng rất nhỏ **`1,2°`** ở mức `stress`, kernel ngang/dọc trục tọa độ của `ocr.py` trượt hoàn toàn (`table_detect_rate` tụt từ `100% → 0%`), làm mất toàn bộ cấu trúc bảng nếu không bổ sung bước nắn thẳng ảnh (*deskew*) trước khi tách lưới.

---

# PHẦN II — CHI TIẾT ĐỢT 2 (3 BÀI TRUNG BÌNH TRÊN MLX + WESPEAKER + FUSION MỚI)

## 6. ASR tiếng Việt trên MLX Runtime (`PhoWhisper-medium` vs `small` & Guard `< 0,8s`)
**Script:** [`run_wave2_asr.py`](../experiments/benchmark_20261118/run_wave2_asr.py) · **Dữ liệu chi tiết:** [`wave2/asr_mlx/results.json`](benchmark_20261118/wave2/asr_mlx/results.json)

### 6.1. So sánh Tổng hợp trên Tập lớn (`vivos_test_563`, `manifest136`, `short80`, và đối chiếu `MPS`)

| Mô hình & Runtime | Tập dữ liệu | Số mẫu | Audio (s) | Wall (s) | RTF ↓ | WER ↓ | CER ↓ | Non-transcribed | Word Confidence Coverage (Mean) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`PhoWhisper-medium` (MLX)** | `vivos_test_563` | **563** | 1.982,2 | 1.456,9 | 0,7350 | **0,0503** | **0,0242** | **1** | **99,82% (0,9901)** |
| `PhoWhisper-small` (MLX) | `vivos_test_563` | **563** | 1.982,2 | **417,5** | **0,2106** | 0,0655 | 0,0310 | 2 | 99,64% (0,9868) |
| **`PhoWhisper-medium` (MLX)** | `manifest136` | 136 | 479,8 | 347,3 | 0,7238 | **0,0716** | **0,0404** | **0** | **100,0% (0,9850)** |
| `PhoWhisper-small` (MLX) | `manifest136` | 136 | 479,8 | **141,1** | **0,2940** | 0,1014 | 0,0546 | 0 | 100,0% (0,9785) |
| `PhoWhisper-medium` (MPS)* | `syn60` | 60 | 213,6 | 382,6 | 1,7912 | 0,2449 | 0,2313 | 13 | 0,0% (`None`) |
| `PhoWhisper-small` (MPS)* | `syn60` | 60 | 213,6 | 231,1 | 1,0817 | 0,5748 | 0,5231 | 26 | 0,0% (`None`) |

*\*Ghi chú kỹ thuật đối chiếu MPS:* Trong môi trường hiện hành (`PyTorch 2.6.0` + `Transformers 4.57.6`), pipeline HuggingFace Whisper trên thiết bị `mps` thường xuyên khiến `AsrQualityCheck` đánh rớt `13/60` (`medium`) và `26/60` (`small`) đoạn thành `non-transcribed`, đồng thời không cung cấp word-level `confidence`. Chuyển sang **MLX Worker** (`mlx 0.32.3`, `mlx-whisper 0.4.3`) khắc phục triệt để cả tốc độ, chất lượng giải mã lẫn điểm tin cậy từng từ.

* **Phân tích theo điều kiện nhiễu trên `manifest136`:**
  * `test` (`clean` / `moderate` / `stress`): `medium MLX` đạt WER **`5,91%` / `6,59%` / `10,99%`**; trong khi `small MLX` đạt `5,91%` / `7,14%` / `20,88%` (`small` xuống chất lượng rõ rệt khi gặp `stress`).
  * `synthetic_test` (`clean_control` / `easy` / `moderate` / `stress`): `medium MLX` đạt **`4,76%` / `6,67%` / `4,40%` / `16,33%`**; `small MLX` đạt `7,48%` / `6,67%` / `12,09%` / `22,45%`.
* **Kiểm định Paired Bootstrap 95% CI (5.000 lượt bốc lại):**
  * Trên `vivos_test_563` (`n = 563`): `PhoWhisper-medium MLX` thấp hơn `PhoWhisper-small MLX` là **`-1,57 điểm % WER`** (**`95% CI = [-2,31%, -0,84%]`**, không chứa 0 → khác biệt có ý nghĩa thống kê rõ rệt).
  * Trên `syn60` (`n = 60`): `PhoWhisper-medium MLX` (`mean WER = 6,49%`) vượt trội `PhoWhisper-medium MPS` (`27,45%`) là **`-20,95 điểm %`** (`95% CI = [-31,27%, -11,39%]`).
* **Kiểm chứng Guard đoạn ngắn (`short80` = `40` đoạn cắt `< 0,8s` + `40` đoạn ngắn `0,8–2,1s`):**
  * Nhóm `0,8–2,1s` (đủ điều kiện fallback CPU khi cần): **`medium MLX`** đạt **WER `9,19%`**, CER **`3,35%`**, `0/40` lỗi (`small MLX`: `13,51%` WER, `0/40` lỗi; `medium MPS`: `70,81%` WER, `28/40` lỗi).
  * Nhóm cắt cụt `< 0,8s` (`0,45–0,72s`, guard mới tắt CPU fallback): cả `medium MLX` (`WER 90,70%`, `7/40` non-transcribed) lẫn `small MLX` (`91,03%`, `6/40`) đều có WER rất cao do tín hiệu cắt cụt thiếu ngữ cảnh câu, xác nhận quyết định **không chạy CPU fallback cho mảnh `< 0,8s`** là hợp lý để tránh lãng phí thời gian CPU.

---

## 7. Multi-source Fusion (`F0–F5` vs `AUDIO_DELAY_AND_SUM` & `Adaptive Routing`)
**Script:** [`run_wave2_fusion.py`](../experiments/benchmark_20261118/run_wave2_fusion.py) · **Dữ liệu chi tiết:** [`wave2/fusion/results.json`](benchmark_20261118/wave2/fusion/results.json)

Chạy bằng **`PhoWhisper-medium MLX`** (đã có word `confidence` thật) trên **toàn bộ `24` cuộc họp đa mic (`12 × 2-mic` + `12 × 4-mic`, `96` lượt nói vàng)**:

| Phương pháp / Cấu hình | Số nguồn ASR TB/lượt | Số ca Audio Fallback (/96) | WER Tổng (96 turns) ↓ | CER Tổng ↓ | WER `2-mic` (48) ↓ | WER `4-mic` (48) ↓ | WER `stress` (32) ↓ |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `F0_FIXED` (chỉ `source-1`) | 3,00 | 0 | 0,1746 | 0,1164 | 0,1766 | 0,1727 | 0,3511 |
| `F1_BEST_SEGMENT` | 3,00 | 0 | 0,1550 | **0,1067** | 0,1511 | 0,1586 | 0,3135 |
| `F3_ROVER` | 3,00 | 0 | 0,1570 | 0,1123 | 0,1532 | 0,1606 | 0,3260 |
| `F4_ASR_WEIGHTED` | 3,00 | 0 | 0,1560 | 0,1103 | 0,1511 | 0,1606 | 0,3166 |
| `F5_RULE_WEIGHTED` | 3,00 | 0 | 0,1539 | 0,1089 | **0,1489** | 0,1586 | **0,3103** |
| **`F5_RULE_WEIGHTED_CORRECTED` (`ALL`)** | 3,00 | 0 | **0,1519** | 0,1086 | 0,1511 | **0,1526** | **0,3103** |
| `F5_CORRECTED_ADAPTIVE_MAX2` | 1,719 | 0 | 0,1663 | 0,1140 | 0,1511 | 0,1807 | 0,3511 |
| **`F5_CORRECTED_ADAPTIVE_MAX3` (mới)** | **1,938** | 0 | **0,1550** | 0,1093 | 0,1511 | **0,1586** | 0,3166 |
| `AUDIO_DELAY_SUM_RAW` (`none`) | **1,00** | 41 / 96 | 0,1767 | 0,1223 | 0,1553 | 0,1968 | 0,3699 |
| `AUDIO_DELAY_SUM_AFFTDN` (`afftdn`) | **1,00** | 41 / 96 | 0,1787 | 0,1237 | 0,1532 | 0,2028 | 0,3699 |
| *`F2_ORACLE_BEST` (cận trên tham chiếu)* | 3,00 | 0 | *0,1384* | *0,0932* | *0,1404* | *0,1365* | *0,2790* |

* **Paired Bootstrap 95% CI (n = 96 turns):**
  * `F5_RULE_WEIGHTED_CORRECTED` vs `F0_FIXED`: **`-2,08 điểm % WER`** (`95% CI = [-3,65%, -0,63%]`, không chứa 0). Word `confidence` thật từ MLX đã mở khóa khả năng sửa lỗi thực chất qua confusion network (đặc biệt trên nhóm **`4-mic`**: `17,27% → 15,26%`).
  * `Adaptive max=3` (cấu hình mới trong `configs/default.yaml`) chỉ tốn **`1,938` lần ASR/lượt** (giảm **35,4%** chi phí so với `all_source`, và chỉ `2,167/4` nguồn trên 4-mic) nhưng giữ WER `15,50%` vượt xa `max=2` (`16,63%`, đặc biệt cứu mảng `4-mic` từ `18,07% → 15,86%`).
  * `AUDIO_DELAY_AND_SUM` (`RAW` & `AFFTDN`) chạy rất nhanh (`124,93s` và `219,15s` cho 24 cuộc họp, chỉ `1` lần gọi ASR/lượt), nhưng trên bộ phòng vang mô phỏng ngắn có **`41/96` turns** (trong đó **`25/32` turns `stress`**) bị fallback vì độ tương quan/trễ cục bộ không đủ tin cậy, khiến WER tổng (`17,87%`) cao hơn `+3,16%` so với `F5_RULE_WEIGHTED_CORRECTED` (`95% CI = [+0,99%, +5,74%]`). Điều này lý giải hợp lý vì sao `configs/default.yaml` đặt mặc định `fusion_mode: transcript` và giữ `audio` như tùy chọn tốc độ cao.

---

## 8. Core End-to-End Replay trên toàn bộ 30 ca `test`
**Script:** [`run_wave2_core_e2e.py`](../experiments/benchmark_20261118/run_wave2_core_e2e.py) · **Dữ liệu chi tiết:** [`wave2/core_e2e/results.json`](benchmark_20261118/wave2/core_e2e/results.json)

Đánh giá cả chuỗi **Aligned Audio → Pyannote Shared Segmentation → SpeakerTurnDetector → GlobalSpeakerClusterer (`P2`) → Adaptive ASR (`PhoWhisper-medium MLX`) → Fusion** trên đủ **30 ca `test`** (`12 × 1-mic`, `9 × 2-mic`, `9 × 4-mic`):

| Cấu hình E2E | Tập con | Số ca | Speaker Pairwise F1 ↑ | Speaker Count Error ↓ | Corpus WER ↓ | Corpus CER ↓ | Wall (s/ca)* |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `C1_legacy_ecapa_transcript_f5` (`ECAPA`, `max_ver=2`) | **all_30** | 30 | 0,7230 | 0,733 | 0,1731 | **0,1124** | 17,77 s (cold) |
| **`C2_wespeaker_mlx_transcript_f5`** (`WeSpeaker`, `max_ver=3`) | **all_30** | 30 | **0,8889** | **0,400** | 0,1764 | 0,1177 | 2,04 s (warm cache)* |
| **`C3_wespeaker_mlx_audio_afftdn`** (`WeSpeaker`, `Audio+afftdn`) | **all_30** | 30 | **0,8889** | **0,400** | **0,1707** | 0,1136 | **11,53 s (cold)** |
| `C1` vs `C2` vs `C3` — `easy_10` | easy | 10 | 0,7524 / **0,9500** / **0,9500** | 0,7 / **0,2** / **0,2** | 0,0757 / **0,0733** / **0,0733** | 0,0371 / 0,0371 / **0,0354** | — |
| `C1` vs `C2` vs `C3` — `moderate_10` | moderate | 10 | 0,8167 / **0,9167** / **0,9167** | 0,9 / **0,7** / **0,7** | 0,1152 / 0,1152 / **0,1127** | **0,0764** / **0,0764** / **0,0764** | — |
| `C1` vs `C2` vs `C3` — `stress_10` | stress | 10 | 0,6000 / **0,8000** / **0,8000** | 0,6 / **0,3** / **0,3** | 0,3333 / 0,3457 / **0,3309** | **0,2305** / 0,2468 / 0,2357 | — |
| `C1` vs `C2` vs `C3` — `2mic` | 2-mic | 9 | 0,7619 / **0,8333** / **0,8333** | 1,000 / **0,778** / **0,778** | 0,1629 / 0,1629 / **0,1461** | 0,1074 / 0,1074 / **0,0884** | — |
| `C1` vs `C2` vs `C3` — `4mic` | 4-mic | 9 | 0,5741 / **0,8889** / **0,8889** | 0,667 / **0,000** / **0,000** | **0,1779** / 0,1887 / **0,1779** | **0,1119** / 0,1296 / 0,1296 | — |

*\*Ghi chú minh bạch về thời gian chạy (`mean_wall_sec`):* `C2` đạt `2,04 s/ca` vì dùng chung `AsrCache` đã ấm từ `C1` trên các lượt trùng nguồn (chỉ chạy mới nguồn thứ 3 của nhóm `4-mic`, mất `6,72 s/ca`); trong khi `C3` sử dụng waveform tổng hợp theo chế độ `audio` (khác khóa cache nguồn đơn lẻ) nên chạy ASR **cold 100%** chỉ mất **`11,53 s/ca`** (so với `17,77 s/ca` cold ở `C1`).

---

# PHẦN III — CHI TIẾT ĐỢT 3 (4 BÀI ĐÁNH GIÁ CÁC PHẦN CÒN THIẾU)

## 9. Đợt 3A — VAD/Overlap, Overlap Separation, `safe_merge` & Evidence Retrieval
**Script:** [`run_wave3_audio_stages_and_retrieval.py`](../experiments/benchmark_20261118/run_wave3_audio_stages_and_retrieval.py) · **Dữ liệu chi tiết:** [`wave3/audio_stages_retrieval/results.json`](benchmark_20261118/wave3/audio_stages_retrieval/results.json) (`1.319,97 s`, `peak_rss = 3.818,32 MB`).

### 9.1. VAD & Frame-level Overlap Detection (30 cuộc họp `test`, `485,6 s`)
| Nhiệm vụ | Mô hình | Số đoạn (`<0,8s`) | Precision ↑ | Recall ↑ | F1 ↑ | Miss Rate ↓ | False Alarm ↓ | RTF ↓ |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vad` | **`pyannote3_prod` (`segmentation-3.0`)** | 95 (`0`) | 0,9824 | 0,8959 | **0,9372** | 0,1041 | 0,0902 | 0,00799 |
| `vad` | **`silero_vad` (guard biên)** | 100 (`0`) | **0,9842** | 0,8904 | 0,9350 | 0,1096 | **0,0804** | 0,00286 |
| `vad` | `fsmn_vad` (`FunASR`) | 37 (`0`) | 0,8916 | **0,9749** | 0,9314 | **0,0251** | 0,6660 | **0,00190** |
| `vad` | `crdnn_vad` (`SpeechBrain`) | 74 (`0`) | 0,9138 | 0,9416 | 0,9275 | 0,0584 | 0,4988 | 0,00274 |
| `overlap_frame` | `pyannote3_prod` | 95 | 0,5421 | 0,1894 | 0,2807 | 0,8106 | 0,0058 | 0,00799 |

* **Nhận xét:** `pyannote3_prod` (`0,9372`) và `silero_vad` (`0,9350`, nhanh hơn `2,8×`) đạt F1 cao nhất và giữ báo động giả ở mức rất thấp (`0,080–0,090`), trong khi `fsmn_vad`/`crdnn_vad` bắt quá dư khoảng lặng (`FA = 0,50–0,67`). Bộ phát hiện frame chồng lấn của `pyannote3_prod` rất chặt về false alarm (`0,0058`) nhưng bỏ sót cao (`miss = 0,8106`, `recall = 0,1894`).

### 9.2. Overlap Separation với Chỉ số Kép (`SI-SDR` + `PhoWhisper-medium MLX PIT WER`, 20 mixture `test`)
| Mô hình | SI-SDR (dB) ↑ | ΔSI-SDR (dB) ↑ | PIT Mean WER ↓ | Best Stream WER ↓ | Sep RTF ↓ |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `no_separation_mixture` | -0,941 | 0,000 | 1,3098 | 0,8192 | 0,000 |
| **`sepformer_whamr` (mặc định `configs/default.yaml`)** | -5,551 | -4,610 | **0,8761** | **0,5161** | 0,491 |
| `sepformer_libri2mix` | **+4,047** | **+4,989** | 1,0810 | 0,6249 | 0,433 |
| `sepformer_wham` | -4,543 | -3,602 | 1,2725 | 0,9269 | 0,431 |
| `convtasnet` (`ConvTasNet_WHAM`) | -2,375 | -1,433 | 1,4774 | 1,1172 | **0,122** |

* **Phát hiện quan trọng cho thực nghiệm:** Nếu chỉ nhìn thước đo tín hiệu `SI-SDR`, `sepformer_libri2mix` (`+4,989 dB`) trông vượt trội hơn `sepformer_whamr` (`-4,610 dB`). Nhưng khi đưa hai luồng tách vào **ASR tiếng Việt (`PhoWhisper-medium MLX`)**, **`sepformer_whamr` đạt chất lượng chữ tốt nhất vượt trội** (`PIT Mean WER = 87,61%`, `Best Stream = 51,61%`), giảm mạnh so với không tách (`130,98%` / `81,92%`) và vượt hẳn `libri2mix` (`108,10%` / `62,49%`). Khẳng định sự cần thiết của đánh giá **chỉ số kép** thay vì chỉ dựa vào `SI-SDR`.

### 9.3. Ablation `safe_merge_speaker_turns` (30 ca `test`)
| Cấu hình | Single Turns | Turns `<0,8s` | Merged Groups | Cross-Speaker Contaminations | ASR Sources | Corpus WER ↓ | Corpus CER ↓ | Wall (s) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `safe_merge = False` | 139 | 27 (`19,42%`) | 0 | 0 | 321 | 0,1764 | 0,1177 | 548,98 (cold) |
| **`safe_merge = True` (`configs/default.yaml`)** | 137 | 27 (`19,71%`) | 1 | 1 | 319 | **0,1739** | **0,1149** | 13,41 (warm cache) |

### 9.4. Evidence Retrieval & Context Spans (`text_manifest_120`, `v2.1`, `60` cases)
| Phương pháp | `manifest_120` Hit@1 / MRR | `manifest_120` Recall@3 ↑ | `manifest_120` Time | `v21_rel_110` Hit@1 ↑ | `v21_rel_110` Hit@2 ↑ | `v21_rel_110` Recall@3 ↑ | `v21_rel_110` MRR ↑ | `v21_rel_110` Time |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`bm25`** | 1,0000 / 1,0000 | 0,6083 | **0,004 s** | **0,9091** | **0,9818** | **1,0000** | **0,9515** | **0,003 s** |
| **`tfidf`** | 1,0000 / 1,0000 | 0,6250 | 0,046 s | **0,9091** | **0,9818** | **1,0000** | **0,9515** | 0,042 s |
| **`hybrid_rrf_e5_small`** | 1,0000 / 1,0000 | 0,6625 | 4,440 s | 0,8727 | **0,9818** | **1,0000** | 0,9333 | 2,058 s |
| `e5_base` | 1,0000 / 1,0000 | 0,6396 | 7,024 s | 0,8727 | 0,9727 | **1,0000** | 0,9318 | 3,967 s |
| `bge_m3` | 1,0000 / 1,0000 | **0,7083** | 16,362 s | 0,8636 | 0,9727 | **1,0000** | 0,9273 | 10,326 s |
| **`e5_small` (mặc định)** | 1,0000 / 1,0000 | 0,6396 | 4,436 s | 0,8455 | **0,9818** | **1,0000** | 0,9197 | 2,055 s |
| `minilm` | 1,0000 / 1,0000 | 0,6542 | 2,955 s | 0,7909 | 0,9545 | 0,9818 | 0,8864 | 2,004 s |

* Kiểm tra `context_spans_v21` trên `60` ca: trích xuất đủ **`296/296` spans** khớp 100% số lượt nói. Trên `v21_gold_relations_110`, `bm25`/`tfidf` (`MRR 0,9515`, `3–42 ms`) và `hybrid_rrf_e5_small` (`MRR 0,9333`) vượt `e5_small` đơn lẻ (`0,9197`) vì tên biến/mã văn bản/chức danh cần khớp từ khóa chính xác.

---

## 10. Đợt 3B — Document Ingest PDF/Scan, Preview Render, Schema Mapper M1 & Backend
**Script:** [`run_wave3_doc_and_backend.py`](../experiments/benchmark_20261118/run_wave3_doc_and_backend.py) · **Dữ liệu chi tiết:** [`wave3/doc_and_backend/results.json`](benchmark_20261118/wave3/doc_and_backend/results.json) (`92,77 s`, `peak_rss = 696,57 MB`).

| Mẫu biểu mẫu | `native_doc_docx` (Anchors / Tables / Recall) | `vector_pdf` (`pdf_text`) | `scanned_flat_pdf` (`ocr_tesseract`) | `scanned_skew_1.2deg_pdf` (`ocr_tesseract`) | Preview (`render_document_pages`) |
| :--- | :--- | :--- | :--- | :--- | ---: |
| `bien_ban_hop_chi_bo.docx` (2t) | **26/26** · **2/2** · `0,4737` (`0,031s`) | 24/26 · **0/2** · `0,4211` (`0,063s`) | 15/26 · **0/2** · `0,2632` (`2,931s`) | 21/26 · **0/2** · `0,3684` (`2,869s`) | 2 trang · `1,200 s` |
| `mau_bien_ban_hop_chung.doc` (2t) | **38/38** · **2/2** · `0,8947` (`0,995s`) | 36/38 · **0/2** · `0,8421` (`0,022s`) | 23/38 · **0/2** · `0,5789` (`1,803s`) | 21/38 · **0/2** · `0,5789` (`1,687s`) | 2 trang · `1,105 s` |
| `bien_ban_ban_giao_thiet_bi.docx` (1t) | **24/24** · **2/2** · (`0,016s`) | 20/24 · **0/2** · (`0,020s`) | 12/24 · **0/2** · (`1,029s`) | 8/24 · **0/2** · (`1,009s`) | 1 trang · `1,078 s` |

* **Khoảng trống kiến trúc được chỉ ra rõ:** Nhánh tái cấu trúc PDF/Scan (`ingest.py`) hiện chỉ dựng các paragraph từ văn bản thuần nên **mất 100% bảng (`0/2` tables)** ở cả `vector_pdf` lẫn bản scan OCR; ngược lại đưa trực tiếp `.docx`/`.doc` bảo toàn toàn vẹn 100% anchor và bảng.
* **`SchemaMapper` `M0` vs `builtin M1` vs `Qwen3-4B MLX M1`:** Hàm `M1` tích hợp trả trạng thái `not_run` (`0,0006–0,0034 s`), còn gọi `Qwen3-4B MLX` với prompt `M1` nâng `semantic_type_recall` trên `bien_ban_hop_chi_bo` từ **`0,4737 → 0,7368`** (`33,415 s`, `26` fields) và trên `mau_bien_ban_hop_chung` từ **`0,8947 → 1,0000`** (`38,852 s`, `37` trường mapped).
* **Hạ tầng Web Backend (`ArtifactStore` & FastAPI):**
  * `ArtifactStore` SHA-256 register đạt **`1.383,0 MB/s`** (`5,0 MB` trong `0,0036 s`) và **`2.494,7 MB/s`** (`25,0 MB` trong `0,0100 s`), latency resolve ~`0,021 ms`.
  * Overhead middleware `OriginGuard` (`403`): `25/25` (`2,638 ms`); Router `404`: `25/25` (`1,771 ms`). Route `/api/v1/auth/login` trả HTTP `500` trong probe do `app.state.mongo` chưa khởi tạo (máy host chưa cài `mongod`, vì vậy benchmark MongoDB queue live chưa thực hiện được).

---

## 11. Đợt 3C — LLM `LoRA B` trên MLX 4-bit, Downstream `generate_graph_minutes` & Full Cold E2E
**Script:** [`run_wave3_llm_mlx.py`](../experiments/benchmark_20261118/run_wave3_llm_mlx.py) · **Dữ liệu chi tiết:** [`wave3/llm_mlx/results.json`](benchmark_20261118/wave3/llm_mlx/results.json) · [`holdout_lora_b/comparison.csv`](benchmark_20261118/wave3/llm_mlx/holdout_lora_b/comparison.csv) (`5.132,94 s`, `peak_rss = 2.269,74 MB`).

### 11.1. Holdout `v2.1` (`60` test cases, `30` families, `70` oracle packets)
| Cấu hình mô hình | Runtime / Phần cứng | Event F1 ↑ | Relation F1 ↑ | Oracle Relation F1 ↑ | State Exact ↑ | Correct (/42) | Median (s/ca) ↓ |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Qwen3-4B-Instruct-2507` (Base) | MLX 4-bit / Apple M4 | 0,6915 | 0,0828 | 0,2708 | 0,1190 | 5 | 20,67 s |
| `Qwen3 + LoRA B` (Colab ref) | NF4 / NVIDIA L4 | **0,8227** | **0,4874** | **0,5446** | **0,3810** | **16** | 49,75 s |
| **`Qwen3 + LoRA B` (Production Local)** | **MLX 4-bit / Apple M4** | **0,8148** | **0,4467** | **0,4713** | **0,3333** | **14** | **9,44 s** |

* **Chi tiết `LoRA B Local MLX` (`configs/minutes.yaml`):** `valid_graph = 59/60` (`98,33%`), `fallback_events = 0/292`, `first_pass_schema_ok = 63/70` (chỉ `2` retry, `accepted_by_parser = 70/70`), `literal_quotes_raw = 42/47` (`89,36%`), `Relation P = 0,5057 / R = 0,4000 (44 TP, 43 FP, 66 FN)`, `Peak MLX = 3,677 GB`.
* **Paired Bootstrap 10.000 lượt theo 30 `families`:**
  * `LoRA B MLX - Base MLX`: `Δ Relation F1 = +0,3639` (`95% CI = [+0,2202, +0,5145]`), `Δ State Exact = +0,2143` (`95% CI = [+0,0952, +0,3478]`) — **vượt Base MLX có ý nghĩa thống kê rất mạnh**.
  * `LoRA B MLX - Colab NF4 L4`: `Δ Relation F1 = -0,0407` (`95% CI = [-0,1582, +0,0684]`), `Δ State Exact = -0,0476` (`95% CI = [-0,1778, +0,0857]`) — khoảng tin cậy đều chứa `0`, chứng minh **chạy `LoRA B` local trên MLX 4-bit không mất mát chất lượng có ý nghĩa thống kê so với GPU L4 NF4**, đồng thời **tăng tốc `5,27×`** (`9,44 s` vs `49,75 s`).

### 11.2. Downstream `generate_graph_minutes` (`12` ca phân tầng × `6` modes) & Xuất DOCX/ZIP
| Cấu hình | Cụm TB | Multi-topic Rate | Mean Total (s) ↓ | Editorial/Writer (s) ↓ | Coverage Complete | Fallback Rate ↓ | Introduced Numbers | Dup Sent | Word Ratio | Zip OK | Peak MLX |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3_base_sil022` | 1,5 | 33,33% | 133,25 | 96,68 | 100% | **0,2795** | **0** | 0,0 | 1,124 | 100% | 4,434 GB |
| **`lora_b_mlx_sil022` (production)** | 1,5 | 33,33% | 109,63 | 87,73 | 100% | 0,2999 | 3 | 0,0 | **1,047** | 100% | 4,434 GB |
| `lora_b_mlx_sil012` (`sil=0,12`) | 1,5 | 33,33% | **107,79** | **86,04** | 100% | 0,2999 | 3 | 0,0 | **1,047** | 100% | 4,434 GB |

### 11.3. Full Cold Uncached Audio → Graph Minutes → DOCX/ZIP E2E (2 ca pilot ~`2 phút`)
| Kịch bản (`uncached`) | Số mic | Audio (s) | Audio Pipeline (s) | Minutes + DOCX (s) | Tổng E2E (s) | Total RTF | Segments | ASR WER ↓ | Zip Integrity |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `pilot_1mic_clean_uncached` | 1 | 119,72 | **50,17** | 443,02 | 493,18 | 4,120 | 12 | **0,0305** | `True` |
| `pilot_3mic_phones_uncached` | 3 | 119,59 | 103,03 | **319,95** | **422,98** | **3,537** | 16 | 0,0668 | `True` |

* **Điểm nghẽn E2E:** Bước `Audio Pipeline` chỉ mất `50–103 s` (`~10–24%` tổng thời gian), còn **76–90%** thời gian E2E nằm ở bước LLM `Editorial / Writer / Polish` viết và kiểm chứng biên bản (`320–443 s` cho ca 2 phút).

---

## 12. Đợt 3D — Đối chiếu ASR Khối lượng lớn (`PhoWhisper-large`, `Turbo`, `Wav2Vec2`)
**Script:** [`run_wave3_asr_large.py`](../experiments/benchmark_20261118/run_wave3_asr_large.py) · **Dữ liệu chi tiết:** [`wave3/asr_large/results.json`](benchmark_20261118/wave3/asr_large/results.json) (`6.111,64 s`, `peak_rss = 1.247,44 MB`, convert & xóa weight MLX tạm lần lượt từng model).

| Mô hình (Runtime) | Tập kiểm thử (Mẫu / Audio) | Wall (s) ↓ | RTF ↓ | Corpus WER ↓ | Corpus CER ↓ | Non-transcribed | Mean Word Conf | Conf Cov |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `PhoWhisper-medium` (MLX, Đợt 2 ref) | `manifest` (`136` / `479,82s`) | **347,31** | **0,7238** | **0,0716** | **0,0404** | 0 | 0,9850 | 100% |
| `PhoWhisper-large` (MLX, Đợt 3D) | `manifest` (`136` / `479,82s`) | 657,68 | 1,3707 | 0,0768 | 0,0456 | 0 | 0,9822 | 100% |
| `whisper-large-v3-turbo` (MLX, Đợt 3D) | `manifest` (`136` / `479,82s`) | 494,58 | 1,0308 | 0,2103 | 0,1454 | 0 | 0,9017 | 100% |
| `wav2vec2-base-vietnamese-250h` (CPU) | `manifest` (`136` / `479,82s`) | **14,54** | **0,0303** | 0,1752 | 0,0830 | 0 | — | 0,0% |
| `PhoWhisper-medium` (MLX, Đợt 2 ref) | `VIVOS test` (`563` / `1.982,21s`) | 1.456,89 | 0,7350 | 0,0503 | 0,0242 | 1 | **0,9901** | 99,82% |
| **`PhoWhisper-large` (MLX, Đợt 3D)** | `VIVOS test` (`563` / `1.982,21s`) | 2.755,66 | 1,3902 | **0,0473** | **0,0227** | 1 | 0,9894 | 99,82% |
| `whisper-large-v3-turbo` (MLX, Đợt 3D) | `VIVOS test` (`563` / `1.982,21s`) | 2.020,27 | 1,0192 | 0,1344 | 0,0799 | 1 | 0,9333 | 99,82% |
| `wav2vec2-base-vietnamese-250h` (CPU) | `VIVOS test` (`563` / `1.982,21s`) | **61,49** | **0,0310** | 0,1061 | 0,0423 | 0 | — | 0,0% |

* **Paired Bootstrap trên `563` câu VIVOS (so với `PhoWhisper-medium MLX`, `mean_a = 5,50%`):**
  * `PhoWhisper-large MLX` (`mean_b = 5,13%`): `mean_diff = -0,37%` (`95% CI = [-1,21%, +0,45%]` chứa 0 — **không có ý nghĩa thống kê**), trong khi **chậm hơn `1,89×`** (`RTF 1,390` vs `0,735`). Khẳng định giữ **`PhoWhisper-medium MLX`** trong `configs/default.yaml` là lựa chọn tối ưu tốc độ–chất lượng.
  * `whisper-large-v3-turbo MLX` (`mean_b = 17,98%`): **`+12,48% WER`** (`95% CI = [+9,84%, +15,47%]`) — không phù hợp cho tiếng Việt chuyên biệt bằng PhoWhisper.
  * `wav2vec2-base-vietnamese-250h` (`mean_b = 11,17%`): **`+5,68% WER`** (`95% CI = [+4,65%, +6,69%]`), không sinh word `confidence` cho ROVER/F5 nhưng chạy **`32× real-time` trên CPU (`RTF 0,031`)**.

---

# PHẦN IV — DỌN CACHE TIẾT KIỆM DUNG LƯỢNG & KIỂM THỬ SAU DỌN DẸP

Đã dọn sạch toàn bộ cache dư thừa/benchmark-only theo 3 pha (giữ nguyên toàn bộ `configs/default.yaml`, `configs/minutes.yaml`, `recycle_bin/`, `web_app/artifacts/minda-colab-v21`, `PhoWhisper-medium/small MLX`, `wespeaker`, `segmentation-3.0`, `sepformer-whamr`, `Qwen3-4B`, `e5-small`, `data/ocr_cache`):

| Giai đoạn dọn cache | Hạng mục đã gỡ / tối ưu | `df -h .` (Used / Avail) |
| :--- | :--- | ---: |
| **Trước Đợt 3** | Trạng thái ban đầu trước khi dọn | `185 GiB` / **`11 GiB`** |
| **Stage 1 (trước Đợt 3A)** | `web_app/data/app/` (`2,1 GB`), `data/evaluations/` (`362 MB`), `data/evaluation_cache/` (`222 MB`), `data/cache/`, `diarizen` (`~626 MB`), `wavlm` (`386 MB`), `xvect` (`31 MB`), `PP-OCRv5` (`7,8 MB`), symlink deduplicate `e5-small` (`+470 MB`), `.mypy`/`.ruff`/`.pytest_cache` | `182 GiB` / **`16 GiB`** |
| **Stage 2 (sau Đợt 3A)** | Xóa các model benchmark Đợt 3A: `bge-m3`, `e5-base`, `MiniLM-L12-v2`, `sepformer-wham`, `sepformer-libri2mix`, `ConvTasNet`, `fsmn-vad`, `crdnn-vad` | `178 GiB` / **`16–17 GiB`** |
| **Stage 3 (sau Đợt 3D)** | Xóa model benchmark Đợt 3D (`PhoWhisper-large` `5,8 GB`, `whisper-large-v3-turbo` `1,5 GB`, `wav2vec2-vi` `360 MB`, `PhoWhisper-small` HF bản gốc `926 MB` giữ lại `asr_mlx/vinai--PhoWhisper-small`), `reports/benchmark_20261118/cache` (`71 MB`), `.locks`, `__pycache__`/pytest cache (`data/model_cache` rút từ **`17 GB → 8,2 GB`**) | **`169 GiB`** / **`27 GiB`** |

**Kiểm chứng bộ test sau khi hoàn tất toàn bộ dọn dẹp Stage 3:**
* **Unit tests (`web_app/.venv-backend`):** `PYTHONPATH=src web_app/.venv-backend/bin/python -m pytest tests/unit -q` → **`454 passed, 1 warning in 34.92s`** (toàn bộ `tests/unit`, gồm cả hai file kiểm thử backend dùng `pymongo`).
* **Integration tests (`.venv`):** `.venv/bin/python -m pytest tests/integration -q` → **`45 passed, 2 warnings in 30.33s`**.

---

## Tổng kết Đề xuất Kỹ thuật & Bàn giao (Sau Đủ Đợt 1–3)

1. **Các quyết định kiến trúc trong `configs/default.yaml` & `configs/minutes.yaml` đã được chứng minh thực nghiệm đầy đủ:**
   * **Speaker ID:** `WeSpeaker E3` + `P2_EMBEDDING_FUSION` (`Pairwise F1 = 0,8889`, đếm `100%` chính xác trên `4-mic`).
   * **ASR & Fusion:** `PhoWhisper-medium MLX` (`WER 5,03%` VIVOS, nhanh gấp `1,89×` `PhoWhisper-large` mà chênh lệch `-0,37%` không có ý nghĩa thống kê) kết hợp word `confidence` mở khóa `F5_RULE_WEIGHTED_CORRECTED` (`WER 15,19%`) và `Adaptive max=3` (tiết kiệm `35,4%` chi phí ASR).
   * **Overlap Separation:** `sepformer_whamr` dù `SI-SDR` thấp vẫn cho **`PIT WER = 87,61%` (`best 51,61%`)** — vượt xa `libri2mix` (`108,10%`).
   * **LLM & Biên bản đồ thị (`LoRA B` trên Local MLX 4-bit):** Đạt `Event F1 = 0,8148`, `Relation F1 = 0,4467`, `State Exact = 0,3333` — vượt `Base MLX` rất mạnh (`+0,3639 Relation F1`) và tương đương thống kê GPU L4 NF4 trong khi **nhanh hơn `5,27×`** (`9,44 s` vs `49,75 s`), chạy khép kín audio→DOCX ZIP integrity `100%` trên MacBook Air 16 GB.
2. **Các giới hạn kỹ thuật cần nêu minh bạch khi bảo vệ / bàn giao:**
   * **Ingest PDF/Scan & Bảng OCR xoay nghiêng:** Reconstruct từ PDF/scan hiện làm rơi bảng (`0/2` tables); tách bảng OpenCV giảm từ `100% → 0%` ở độ nghiêng `1,2°` (cần deskew nếu xử lý ảnh chụp điện thoại).
   * **Topic Clustering (`minimum_silhouette = 0,22`):** Giữ ổn trên tập 4 chủ đề tách biệt, nhưng dễ gộp thành 1 cụm (`96,7%–100%` trên `v2.1/nrv2`, `66,7%` trên `12` ca phân tầng).
   * **NĐ 30/2020 & Introduced Numbers:** Bộ regex stress đạt `33/54` (`61,11%`) với câu giờ phức tạp; phần viết biên bản của `LoRA B` ghi nhận `3` con số phát sinh mới trên `12` ca downstream (`Base = 0`).
   * **Phần chưa bao phủ (đã tách sẵn):** Benchmark trên tập **cuộc họp tiếng Việt thực tế** và benchmark **MongoDB queue live** (`mongod`).
