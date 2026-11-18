# Sửa lỗi xử lý audio sau khi tải lên timeline

## Hiện tượng và nguyên nhân

Ba lần xử lý gần nhất của cuộc họp đang kiểm tra, lúc 20:16–20:18 ngày 27/10/2026, đều kết thúc với `Selected clip range exceeds decoded audio` tại bước kiểm tra vùng chọn. Tác vụ chưa đến bước chép lời. Khi kiểm tra lúc 20:23, worker còn gửi tín hiệu hoạt động nhưng không có tác vụ đang chạy; API vẫn phục vụ yêu cầu cập nhật giao diện. Terminal tiếp tục có hoạt động không đồng nghĩa lần xử lý audio còn chạy.

Timeline lưu điểm kết thúc bằng mili giây nguyên và làm tròn lên để không cắt đuôi bản ghi. Bộ xử lý lại so với số mẫu giải mã, dùng ngưỡng một mẫu tại 16 kHz, tương đương 0,0625 ms. Vì vậy các file WAV hợp lệ có thời lượng lẻ bị từ chối.

| File | Thời lượng giải mã | Điểm cuối trên timeline | Chênh lệch |
| --- | --- | --- | --- |
| phone_huy.wav | 119,588750 s | 119,589 s | 0,2500 ms |
| phone_lan.wav | 119,896125 s | 119,897 s | 0,8750 ms |
| phone_minh.wav | 119,7173125 s | 119,718 s | 0,6875 ms |

## Bản sửa

- So sánh điểm cuối trên cùng đơn vị mili giây làm tròn lên, có giới hạn một mẫu bổ sung cho sai số giải mã/resample. Khi đọc vẫn giới hạn ở mẫu audio thực, không tạo thêm audio hoặc giảm kiểm tra thời lượng chung.
- Vùng vượt quá dung sai vẫn bị từ chối và được báo bằng tiếng Việt.
- Đổi phép chuyển giây sang vị trí mẫu ở phần cắt cho ASR và lượt lời từ ép xuống số nguyên sang làm tròn gần nhất. Kiểm thử tìm thêm trường hợp số thực làm mất mẫu cuối dù vùng chọn hợp lệ.
- Thông báo tác vụ hiển thị nguyên nhân và dẫn tới đúng lần chạy. Lần đã kết thúc có thông báo kết thúc riêng, không hiện nút hủy như tác vụ còn chạy.
- Thông báo lấy lần mới nhất của từng tài nguyên và loại xử lý. Lần thành công hoặc bị hủy mới hơn không khiến lỗi cũ tiếp tục xuất hiện như kết quả hiện tại. Lịch sử trong database vẫn được giữ nguyên.

## Xác nhận

- 89 kiểm thử timeline, đồng bộ, cắt lượt lời, ranh giới ASR và kiểm tra đầu vào đạt. Có 4 ca WAV có thời lượng lẻ giữ nguyên từng mẫu qua luồng ASR kiểm thử, và ca vượt thực sự bị chặn.
- 9 kiểm tra chọn thông báo và dịch thông báo lỗi đạt, gồm lần chạy mới đang chạy/thành công/hủy, nhiều loại tác vụ và nhiều cuộc họp.
- TypeScript và build Vite đạt; Ruff và kiểm tra khoảng trắng đạt.
- Chạy lại bước giải mã và kiểm tra vùng chọn trên chính 3 file bị lỗi bằng mã mới: cả 3 vượt qua. Dừng trước căn âm thanh và ASR, không ghi kết quả vào database hoặc sửa file gốc. Đây không phải lần chạy suy luận đầy đủ.
- Kết quả kiểm tra: `data/evaluations/audio-range-fix-20261027/tests.xml`, `notification-check.json`, `affected-files-check.json`. Kiểm tra thông báo có thể chạy lại bằng `node data/evaluations/audio-range-fix-20261027/check-notifications.cjs` tại thư mục `web_app`.

## Áp dụng vào phiên đang chạy

Mã đã sửa và frontend đã build. Worker đang chạy trước bản sửa đã nạp module cũ vào bộ nhớ, cần khởi động lại để dùng bản sửa. Không tự dừng hoặc khởi động lại phiên người dùng đang kiểm tra.

Trong terminal chạy Minda, nhấn `Ctrl+C`, rồi tại thư mục `web_app` chạy lại:

```bash
.venv-backend/bin/python scripts/backend/run_local.py
```

Tải lại trang, mở cuộc họp và chọn xử lý lại âm thanh. Không cần tải lại ba file. Các trạng thái thất bại cũ trong lịch sử không tự chuyển thành thành công; lần chạy mới có mã và trạng thái riêng.
