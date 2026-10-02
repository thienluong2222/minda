# Kịch bản demo local

1. Chạy `uv run meeting-pipeline doctor` và xác nhận mọi dòng đều `OK`.
2. Chạy `uv run meeting-pipeline serve --host 127.0.0.1 --port 8000`.
3. Đăng ký người tham gia bằng tên và một hoặc nhiều mẫu giọng; nếu không đăng ký, kết quả dùng nhãn Speaker 1/2/…
4. Nhập tên cuộc họp, tải 1–8 bản ghi cùng cuộc họp, chọn hồ sơ tham gia, ECAPA hoặc MFCC + KNN, rồi chọn F1/F3/F4/F5/F6 (mặc định F5).
5. Theo dõi trạng thái chờ/chạy/thành công/thất bại. Model chạy offline, một job tại một thời điểm.
6. Ở trang kết quả, xem tổng quan và đồng bộ từng nguồn; nghe hoặc tải các file audio trong `aligned/`.
7. Xem timeline “ai nói gì”, lọc người nói/nguồn/đoạn cần kiểm tra. Mở từng đoạn để đối chiếu transcript, chỉ số chất lượng, clip cùng timestamp của từng nguồn, quyết định nhận diện và nguồn gốc từng từ.
8. Tải JSON, CSV, TXT hoặc ZIP. Nếu F6 chuyển về F5, trang kết quả hiển thị cảnh báo từ manifest.

Tên chỉ được gán khi phương pháp nhận diện đã chọn khớp hồ sơ đủ ngưỡng và margin. Nếu không,
speaker giữ trạng thái `unknown` với nhãn vô danh ổn định; tên file không được dùng làm danh tính.
Trọng số chất lượng transcript ở cấp đoạn không phải tỷ lệ từ đã đóng góp. Các điểm nhận diện và
transcript confidence không phải xác suất chính xác đã hiệu chuẩn. Run schema 1.0 vẫn mở được
nhưng những chi tiết chưa lưu sẽ hiện “Chưa có dữ liệu”. Hiện tại demo chỉ phát hiện
vùng nói chồng: mỗi vùng có một dòng `not_run` trên timeline và clip gốc của mọi nguồn
để nghe lại. Demo không gọi SepFormer, ASR hay nhận diện người nói cho vùng này.
