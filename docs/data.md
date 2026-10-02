# Dữ liệu

Chỉ `dataset/` nằm trong phạm vi. Không đọc thư mục notes/tham khảo. Năm file AAC hiện có là
real-test; tên file là vị trí điện thoại gần người, không phải nhãn người nói.

## Nguồn đã tải ngày 2026-09-16

| Nguồn | Phiên bản | Giấy phép | Byte mạng thực nhận | Nội dung |
|---|---|---|---:|---|
| VIVOS | Zenodo 7068130 | CC BY-NC-SA 4.0 | 1.474.408.300 | Archive đầy đủ, MD5 nguồn hợp lệ, đã giải nén an toàn |
| LibriWASN | Zenodo 10952434 | CC BY 4.0 | 344.991.656 | OV20 session 4 và 5; mỗi session 3 điện thoại, Soundcard, VAD |
| VoxVietnam | HF `0ee77c8...` | CC BY-NC 4.0 | 812.349.571 | 10 test shards rải đều; repo gated, token không lưu trong manifest |

Tổng byte mạng dataset: **2.631.749.527**, dưới ngân sách 3.500.000.000. Dung lượng đĩa
khác byte mạng: VIVOS khoảng 3,1 GiB gồm archive+bản giải nén, LibriWASN 441 MiB,
VoxVietnam 789 MiB. Model cache khoảng 1,3 GiB được ghi riêng.

LibriWASN ZIP gốc 4.747.801.245 byte không được tải. Server trả HTTP 206; central directory
được đọc bằng range, sau đó chỉ các entry trong `manifests/libriwasn.json` được lấy. Soundcard
là trục nhãn tham chiếu; timestamp không áp trực tiếp lên điện thoại trước đồng bộ.

VoxVietnam có 6.980 phát ngôn, 37 speaker trong các shard đã chọn; 31 speaker có ít nhất
10 phát ngôn. `subset-index.json` giữ 31 × 10 row, seed 20260916, mỗi người 5 support-pool
và 5 query-pool không trùng. Đây là `public_test`, không dùng calibration hoặc fit scaler.
Subset này thuộc partition `test`, chưa được gọi là VoxVietnam-O; nhãn test tự động có giới hạn
đã được tác giả công bố. Khi có gói O chính thức phù hợp ngân sách sẽ đánh giá riêng.
