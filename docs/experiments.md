# Thực nghiệm

Chưa có kết quả chất lượng. Không có số liệu nào được tuyên bố trước khi chạy M0-M6.
Hai cuộc họp cá nhân không được dùng để chọn threshold, weight hay nguồn tốt nhất.

## Smoke M0 ngày 2026-09-16

Host: macOS arm64, Python 3.11.14, CPU (Torch báo MPS không khả dụng).

| Thành phần | Snapshot | Kết quả smoke |
|---|---|---|
| Silero VAD | package 6.2.1 | Chạy trên 4 giây AAC giải mã, trả hai vùng speech |
| ECAPA | `0f99f2d...` | Chạy CPU 16 kHz, embedding shape `(1, 1, 192)` |
| SepFormer-WHAMR | `9950fd80...` | Chạy CPU 8 kHz, hai output shape `(1, 32000, 2)` |
| PhoWhisper-small | `a86b604c...` | Chạy CPU 16 kHz; segment timestamp token bắt đầu `0.02 s` |
| pyannote segmentation 3.0 | `e66f3d3b...` | Chạy CPU, powerset shape `(1, 589, 3)` |

Audio smoke lấy 4 giây từ `Nhan_1.aac` chỉ để kiểm tra API/model thật. Transcript không phải
nhãn, không được dùng làm điểm chất lượng hoặc calibration. Chưa chạy metric, dataset hay real-test.
Stack cuối lượt smoke: Torch/Torchaudio 2.6.0. Mọi model chạy từ snapshot local, không gửi audio
ra dịch vụ ngoài. Pyannote dùng allowlist metadata giới hạn để giữ loader `weights_only` an toàn.

## Trạng thái dữ liệu M2

Đã tải và kiểm ngân sách VIVOS, LibriWASN subset và VoxVietnam subset. Chưa có metric chất lượng,
calibration hoặc ablation. Việc dữ liệu sẵn sàng không được diễn giải là pipeline đã nghiệm thu.

Hai cuộc họp cá nhân sẽ chạy không enrollment theo yêu cầu người dùng. Báo cáo real-test giữ
speaker vô danh/unknown và không tính metric nhận diện theo tên; tên file chỉ là vị trí điện thoại.

## Real-test prototype ngày 2026-09-16

Cả hai cuộc họp chạy offline bằng checkpoint thật, không enrollment và không suy tên từ tên file.
Đây là kiểm tra chức năng end-to-end, không phải kết quả chất lượng có ground truth.

| Cuộc họp | Nguồn | Timeline rows | Rows thuộc vùng overlap | ASR có text | Trạng thái |
|---|---:|---:|---:|---:|---|
| `real-test-1` | 3 | 22 | 10 | 22 | succeeded |
| `real-test-2` | 2 | 27 | 10 | 27 | succeeded |

Mỗi run có decoded/aligned audio, clip gốc, clip processed dùng cho ASR, coverage, timeline,
manifest và export JSON/CSV/TXT/ZIP. Schema timeline và tính toàn vẹn ZIP đã được kiểm tra.
Chưa có nhãn tham chiếu nên không báo DER, SI-SDR, CER hoặc độ chính xác danh tính.

## Sửa theo review demo ngày 2026-09-16

- Clip separator được peak-limit chỉ theo hướng giảm gain, lưu PCM16 rồi đọc lại chính artifact
  đó cho ASR và ECAPA. Hai real-test chạy lại có peak tối đa khoảng 0,95 và không có clip chạm
  ngưỡng 0,999.
- Đồng bộ sửa chiều offset theo hợp đồng `t = u + b`; fixture event trễ 1 giây nay chờ `b=-1`.
- Separator nhận thêm context hai phía; ASR dài được chia theo `asr.max_chunk_seconds`.
- Có enrollment ECAPA tùy chọn và clustering vô danh ổn định. Real-test 1 tạo Speaker 1–3;
  real-test 2 tạo Speaker 1–2. Đây chỉ là nhãn track vô danh, không phải metric danh tính.
- Nguồn chọn dùng ba đặc trưng không còn cùng bão hòa từ một RMS; coefficients và temperature
  được đọc từ cấu hình. Chưa tuyên bố trọng số đã hiệu chuẩn.
