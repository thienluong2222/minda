# Báo Cáo Benchmark So Sánh Nhận Diện Giọng Nói: ECAPA-TDNN vs MFCC + KNN Trên Dữ Liệu VIVOS

Báo cáo này ghi nhận kết quả thực nghiệm định lượng giữa hai phương pháp nhận diện danh tính người nói (Speaker Identification) được tích hợp trong hệ thống Pipeline:
1. **ECAPA-TDNN** (Deep Learning Speaker Embedding - 192 chiều).
2. **MFCC + KNN** (Classical Machine Learning Baseline - 120 chiều).

---

## 1. Dữ Liệu & Thiết Kế Thực Nghiệm

- **Tập dữ liệu**: [VIVOS Vietnamese Speech Dataset](https://ailab.hcmus.edu.vn/vivos) (thư mục `data/external/vivos/extracted/vivos/test/waves/`), gồm 19 người nói tiếng Việt với chất lượng ghi âm chuẩn 16 kHz.
- **Môi trường thực thi**: Apple Silicon (M-series, MPS/CPU), Python 3.11, `torchaudio`, `librosa`, `scikit-learn`.
- **Cấu hình mô hình**:
  - **ECAPA-TDNN**: Pretrained speechbrain/spkrec-ecapa-voxceleb (hoặc SpeechBrain trích xuất embedding 192 chiều), so khớp Cosine Similarity, `identity_threshold = 0.25`, `identity_margin = 0.05`.
  - **MFCC + KNN**: 20 MFCC tĩnh + 20 Delta + 20 Delta-Delta gom tụ Mean/Std thành vector 120 chiều, phân chia mẫu đăng ký bằng cửa sổ trượt 1.5s bước 0.5s; mô hình `KNeighborsClassifier(n_neighbors=5, metric='cosine', weights='distance')`.

---

## 2. Kết Quả Thực Nghiệm

### Thực Nghiệm 1: Phân Loại Đóng (Closed-Set Identification - 8 Người Nói)
- **Kịch bản**: 8 người tham gia cuộc họp tiêu chuẩn đã đăng ký trước (2 mẫu đăng ký/người).
- **Tập đánh giá**: 20 mẫu phát biểu/người $\rightarrow$ **160 mẫu âm thanh kiểm tra**.
- Tỷ lệ đoán ngẫu nhiên (Chance Level): $1/8 = 12.50\%$.

| Chỉ số đánh giá | ECAPA-TDNN (Deep Learning) | MFCC + KNN (Classical ML) | Nhận xét so sánh |
| :--- | :---: | :---: | :--- |
| **Độ chính xác Top-1 (Accuracy)** | **96.25%** (154/160 đúng) | **37.50%** (60/160 đúng) | ECAPA vượt trội **+58.75%**; MFCC+KNN cao gấp **3 lần** đoán mò |
| **Thời gian xử lý TB (Latency)** | **20.04 ms/mẫu** | **2.12 ms/mẫu** | MFCC + KNN nhanh hơn **~9.5 lần** |
| **Thời gian trung vị (Median Latency)**| **19.61 ms/mẫu** | **2.11 ms/mẫu** | Cực kỳ ổn định cho cả hai |
| **Tài nguyên mô hình (Footprint)** | Cần nạp Model (~80–100 MB weights) | Nhẹ (chỉ cần thư viện toán học cơ bản) | MFCC+KNN chạy tốt trên thiết bị nhúng/IoT |

---

### Thực Nghiệm 2: Phân Loại Mở (Open-Set Identification - Người Quen vs Người Lạ)
- **Kịch bản**: 5 người ĐÃ ĐĂNG KÝ (75 mẫu) và 5 người CHƯA ĐĂNG KÝ / Khách vãng lai (75 mẫu).
- **Tổng số mẫu kiểm tra**: **150 mẫu**.
- Ngưỡng cấu hình: `threshold = 0.25`, `margin = 0.05`.

| Chỉ số đánh giá | ECAPA-TDNN | MFCC + KNN | Ý nghĩa thực tế |
| :--- | :---: | :---: | :--- |
| **Nhận đúng người quen (TPR / Known Accuracy)** | **98.67%** (74/75) | **37.33%** (28/75) | Khả năng định danh thành viên đã đăng ký |
| **Từ chối đúng người lạ (TNR / Unknown Rejection)** | **26.67%** (20/75) | **13.33%** (10/75) | Khả năng đẩy người lạ vào nhóm `Speaker 1, 2...` |
| **Độ chính xác cân bằng (Balanced Accuracy)** | **62.67%** | **25.33%** | Trung bình cộng giữa TPR và TNR |

> **Lưu ý về TNR**: Với ngưỡng cosine mặc định `identity_threshold = 0.25`, mô hình ưu tiên bắt đúng người quen (Recall cao 98.67%). Nếu muốn tăng khả năng từ chối người lạ (TNR), chỉ cần nâng `identity_threshold` lên mức $0.45 - 0.55$ trong file cấu hình `configs/default.yaml`.

---

## 3. Phân Tích Kỹ Thuật Chuyên Sâu (Academic Discussion)

### 1. Vì sao ECAPA-TDNN đạt độ chính xác 96.25% trên tiếng Việt?
- **Khử nội dung ngữ âm (Phonetic Invariance)**: ECAPA-TDNN được huấn luyện với hàm mất mát mở rộng góc siêu cầu **AAM-Softmax (Additive Angular Margin Softmax)** trên hàng nghìn người nói. Quá trình này ép mô hình bỏ qua từ ngữ đang nói (nguyên âm, phụ âm gì) để tập trung duy nhất vào đặc tính sinh học của vòm họng, dây thanh quản và âm sắc người nói.
- **Tính khái quát hóa từ ít mẫu (Few-shot Enrollment)**: Chỉ với **2 câu nói ngắn** của người dùng trong tập VIVOS, vector trọng tâm (centroid) 192 chiều đã hội tụ đủ đặc trưng để đại diện cho người đó qua 20 câu kiểm tra có nội dung hoàn toàn khác biệt.

### 2. Bản chất của MFCC + KNN và lý do đạt 37.50%
- **Đặc trưng âm học vật lý thô**: MFCC biểu diễn năng lượng phổ tần số sau khi lọc qua thang Mel. Khi gom cụm toàn bộ câu nói bằng Mean và Standard Deviation (120 chiều), vector MFCC bị chi phối bởi các âm vị xuất hiện trong câu nói đó (ví dụ câu nhiều âm /a/, /o/ sẽ lệch phổ so với câu nhiều âm /i/, /u/).
- **Độ tương đồng giữa các người nói**: Trong tiếng Việt, các nguyên âm và thanh điệu có cấu trúc formant tương đối đồng nhất giữa những người cùng giới tính/vùng miền, khiến khoảng cách giữa hai câu nói của hai người khác nhau đôi khi lại gần hơn hai câu nói có ngữ âm khác biệt của cùng một người.
- **Tuy nhiên**, con số **37.50%** (so với 12.50% ngẫu nhiên) chứng minh rằng đặc trưng âm sắc cá nhân (formant trung bình và độ lệch phổ) vẫn được bảo toàn một phần trong 120 chiều MFCC.
- **Ưu thế tuyệt đối về tốc độ**: Tốc độ xử lý chỉ **2.12 ms/mẫu** (nhanh gấp ~9.5 lần ECAPA-TDNN) và hoàn toàn không phụ thuộc vào GPU hay bộ trọng số hàng trăm megabyte.

### 3. Đóng góp cho Luận Văn Tốt Nghiệp
- **Xây dựng đường cơ sở thực nghiệm vững chắc (Strong Empirical Baseline)**: Luận văn không chỉ đưa ra một mô hình Deep Learning đơn lẻ mà đã xây dựng một phương pháp truyền thống (MFCC + KNN) để so sánh đối chứng trực tiếp trên cùng một tập dữ liệu chuẩn tiếng Việt.
- **Minh chứng khoa học cho sự cần thiết của Deep Learning**: Kết quả định lượng (96.25% vs 37.50%) là bằng chứng thực nghiệm rõ ràng nhất chứng minh tại sao phương pháp trích xuất đặc trưng truyền thống không đủ đáp ứng bài toán nhận diện người nói tự do trong phòng họp, và tại sao kiến trúc Deep Learning như ECAPA-TDNN là lựa chọn tối ưu.
- **Tính linh hoạt của hệ thống**: Người dùng hoặc thiết bị phần cứng yếu vẫn có quyền lựa chọn phương pháp phù hợp thông qua giao diện Web Demo hoặc file cấu hình.

---

## 4. Tái Lập Thực Nghiệm (Reproducibility)

Để chạy lại toàn bộ quá trình benchmark và tự động xuất file kết quả JSON:
```bash
uv run python scripts/benchmark_speaker_id.py
```
Kết quả đo lường sẽ được lưu tự động tại [`docs/speaker_id_benchmark_vivos.json`](file:///Users/thien/Documents/School/Luận%20văn/docs/speaker_id_benchmark_vivos.json).
