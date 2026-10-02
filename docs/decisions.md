# Quyết định kỹ thuật

## 2026-09-16 — Trạng thái cấu hình

- Giữ nguyên model mặc định của đặc tả: Silero VAD, pyannote segmentation 3.0, SpeechBrain
  ECAPA, SepFormer-WHAMR và PhoWhisper-small.
- `configs/default.yaml` mang mode `development`; các ngưỡng nhận diện hiện chỉ là giá trị
  khởi điểm và không được trình bày là đã hiệu chuẩn.
- Revision model đã khóa theo metadata/snapshot thực nhận: pyannote
  `e66f3d3b9eb0873085418a7b813d3b369bf160bb`, ECAPA
  `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`, SepFormer
  `9950fd8055b38679d2af5bef2366b5dba600ec66`, PhoWhisper
  `a86b604c346caf7148c37512eafe783a16420adb`.
- Không thêm mô hình thay thế. WeSep chỉ được xét sau cổng chất lượng SepFormer theo đặc tả.

## 2026-09-16 — Tương thích stack ML M0

- `torch==2.6.0`, `torchaudio==2.6.0`, `pyannote.audio==3.3.2`,
  `speechbrain==1.1.1`, `transformers==4.57.6` import được cùng nhau trên Python 3.11 arm64.
- Tổ hợp resolver đầu tiên (`torch 2.14.0` / `torchaudio 2.11.0`) bị loại vì pyannote 3.3.2
  cần `torchaudio.AudioMetaData`, API không còn ở torchaudio 2.11. Đây là lỗi smoke thực tế,
  không phải suy đoán phiên bản.
- Cặp 2.5.1 nạp được pyannote nhưng bị loại: Transformers từ chối `torch.load` dưới 2.6 do
  CVE-2025-32434. Cặp 2.6.0 là mức tối thiểu bảo mật; adapter pyannote phải allowlist chính xác
  kiểu legacy cần thiết thay vì tắt cơ chế `weights_only` toàn cục.
- Danh sách metadata kiểm tra trực tiếp bằng `get_unsafe_globals_in_checkpoint`: `TorchVersion`,
  `Resolution`, `Specifications`, `Problem`. Adapter dùng `safe_globals` có phạm vi khi load;
  không đặt `weights_only=False` và không thay đổi loader toàn cục.
- CPU là đường kiểm chứng bắt buộc; MPS chỉ được ghi nhận lại sau khi khóa môi trường cuối.

## 2026-09-16 — Real-test cá nhân không dùng đăng ký

- Theo quyết định của người dùng, hai cuộc họp trong `dataset/voices/` không dùng enrollment,
  kể cả enrollment lấy từ một đoạn trong cùng cuộc họp.
- Real-test này chỉ đánh giá đồng bộ, phân đoạn/overlap, tách giọng, nối track vô danh,
  chọn nguồn, ASR và provenance. `speaker_id` phải để null, trạng thái `unknown`; tên file hoặc
  trường `Đặt gần` không được dùng làm nhãn.
- Không tính fixed-identity accuracy và không tuyên bố real-test này nghiệm thu yêu cầu nhận diện
  người theo tên. Cổng chức năng đó phải được kiểm bằng dữ liệu công khai có support/query riêng.
