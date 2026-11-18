# Kế hoạch sửa Minda: họp dài và dừng/ghi tiếp

Ngày: 27/10/2026. Trạng thái: **đã triển khai bước 1–3 và frontend timeline nhiều nguồn**. Giao diện mới giữ bảng màu cũ, bỏ phần 3D, có kéo thả lưu thật và không tự lấp khoảng nghỉ chưa biết. Mở rộng thời lượng, phục hồi tiến độ và nghiệm thu trên bản ghi thực tế vẫn thuộc các phần tiếp theo. Bước 3 đã kiểm bằng dữ liệu tổng hợp và kiểm tra tích hợp; chưa nghiệm thu độ chính xác trên bản ghi điện thoại thực tế.

Frontend và phạm vi kiểm tra: [báo cáo triển khai giao diện](reports/FRONTEND_IMPLEMENTATION_2026-10-27.md).

Kết quả và hướng dẫn dùng API: [báo cáo triển khai bước 1–2](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/STEP_1_2_IMPLEMENTATION_2026-10-27.md>).

Hành vi xử lý hiện tại và giới hạn: [báo cáo triển khai bước 3](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/STEP_3_IMPLEMENTATION_2026-10-27.md>).

**Mục tiêu:** xử lý cuộc họp dài có giải lao hoặc dừng ghi rồi tiếp tục; giữ đầy đủ audio đã nhận, nối đúng thời gian khi có căn cứ và lập biên bản đúng diễn biến.

Phạm vi lần này không gồm xử lý nhiều người nói đồng thời.

## Thứ tự thực hiện

| Bước | Việc cần sửa | Điều kiện hoàn thành |
| --- | --- | --- |
| **1. Giữ đúng dữ liệu đầu vào** | Sửa lỗi cắt mất đầu bản ghi khi căn thời gian; dùng đúng cấu hình đồng bộ; thể hiện đúng trạng thái chưa căn chắc. Thống nhất kiểm tra định dạng/thời lượng ở bước tải lên và xử lý. | Không bỏ phần audio chỉ một máy ghi được; không báo đã căn khi chưa đủ căn cứ; file không phù hợp được báo rõ từ đầu. |
| **2. Chuẩn bị dữ liệu cho timeline nhiều nguồn** | Tách nguồn ghi, file gốc và đoạn trên timeline. Mỗi nguồn có một hàng chứa các phần audio nối tiếp; lưu thứ tự, vị trí hoặc khoảng cách đã biết/chưa rõ. Chuẩn bị thao tác cập nhật thứ tự/vị trí/chuyển hàng theo phiên bản để giao diện kéo thả dùng trực tiếp. Quản lý riêng phiên họp/giải lao. | Lưu rồi tải lại giữ nguyên bố cục; kéo thả không sửa file gốc hoặc làm mất căn cứ; nhiều file có thể thuộc một nguồn; vị trí trình bày không bị coi là giờ thực đã xác nhận. |
| **3. Căn thời gian theo từng đoạn** | Tìm các mốc âm thanh trước/sau gián đoạn; dùng ánh xạ riêng khi thời gian bị nhảy do pause. Theo dõi trôi đồng hồ trong phần liên tục và giữ vùng chưa xác định. | Nguồn pause có thể ghép đúng với nguồn liên tục khi đủ mốc; không tự đoán độ dài khoảng nghỉ khi mọi máy đều dừng. |
| **4. Xử lý dài và tiếp tục sau ngắt** | Đọc audio theo khối; giữ ASR theo đoạn ngắn đang có; lưu kết quả từng công đoạn. Nối lời và danh tính người nói qua các phần ghi. | Chạy lại tiếp tục được từ tiến độ đã lưu; không nhân đôi lời ở biên; đo được bộ nhớ và thời gian trên bản ghi 30/60/120 phút. |
| **5. Giữ đúng diễn biến trong biên bản** | Liên kết đề xuất, đính chính, rút lại và kết luận theo đề mục, kèm lời gốc. Phân biệt kết thúc phiên với kết thúc toàn cuộc; gắn phiếu với đúng đề mục/vòng. Thống nhất đầu ra model đã huấn luyện với ứng dụng. | Không bỏ lần đổi người phụ trách/điều kiện sau nghỉ; không nâng đề xuất chưa chốt thành quyết định; giờ và kết quả phiếu đúng phạm vi. |
| **6. Kiểm tra toàn luồng trước khi mở rộng** | Chạy bộ cuộc họp tiếng Việt có mốc đối chiếu, kiểm audio → transcript → biên bản và phục hồi sau ngắt. Đo chất lượng, bộ nhớ, thời gian và công sửa tay. | Chỉ công bố mức thời lượng/tình huống đã kiểm đạt; trường hợp thiếu căn cứ phải có dấu hiệu cần rà. |

## Các tình huống bắt buộc thử

- [ ] Họp liên tục 30, 60 và 120 phút.
- [ ] Giải lao 5–15 phút nhưng vẫn ghi; có im lặng hoặc nói chuyện ngoài nội dung.
- [ ] Dừng rồi ghi thành file mới, có hoặc thiếu mốc giờ bắt đầu.
- [ ] Một máy pause rồi ghi tiếp trong cùng file, máy khác ghi liên tục.
- [ ] Tất cả thiết bị cùng dừng, không biết chính xác độ dài khoảng nghỉ.
- [ ] Máy bật sớm, bật muộn; có trôi đồng hồ hoặc nhiều lần pause.
- [ ] Quyết định được sửa sau giải lao; có kết thúc phiên trước kết thúc toàn cuộc.
- [ ] Tiến trình bị ngắt rồi chạy tiếp; sửa mốc thời gian rồi xử lý lại phần liên quan.
- [x] Nền dữ liệu hỗ trợ một nguồn có nhiều file và nhiều hàng nguồn độc lập.
- [x] Đổi thứ tự/chuyển nguồn/đổi vị trí qua API rồi tải lại vẫn giữ đúng bố cục và mã đoạn.
- [x] Khoảng nghỉ chưa biết không bị tự đổi thành 0; thao tác sắp xếp không thay đổi file gốc hoặc tự xác nhận thời gian thực.
- [x] Thay đổi bố cục làm kết quả xử lý cũ cần cập nhật; thao tác từ bản dữ liệu cũ không ghi đè bản mới.
- [x] Kiểm tra tự động trên audio tổng hợp: file nối tiếp có khoảng nghỉ đã biết; khoảng nghỉ chưa biết giữ đồng hồ cục bộ; một hoặc nhiều lần pause; nguồn bật muộn; trôi đồng hồ; âm thanh lặp dễ ghép nhầm.
- [x] Kiểm tra tích hợp: vùng cắt đúng mẫu audio gốc; khoảng đệm không trở thành đầu vào ASR; nội dung loại khỏi biên bản vẫn giữ trong transcript nhưng không vào bộ trích xuất.

Các mục trên không thay cho nghiệm thu bản ghi họp thật ở bước 6. Giới hạn 20 phút mỗi file và mỗi đồng hồ xử lý vẫn còn.

## Yêu cầu timeline đã thống nhất cho bước 2

Giao diện đã có **mỗi nguồn một hàng**, các đoạn audio sắp theo chiều thời gian/thứ tự. Người dùng có thể kéo để đổi thứ tự, đổi vị trí và chuyển đoạn sang nguồn khác; các nút và hộp đặt mốc cung cấp cách thao tác thay thế. Giao diện dùng dữ liệu và thao tác cập nhật đã chuẩn bị ở bước 2.

File gốc được giữ riêng. Mỗi đoạn trên timeline có mã ổn định, tham chiếu file gốc và vùng audio sử dụng; không lấy tên file hoặc vị trí trong danh sách làm định danh. Thứ tự và mốc thời gian là hai thông tin khác nhau: biết phần nào trước chưa có nghĩa biết chính xác thời gian nghỉ ở giữa.

Thiết kế chi tiết, hợp đồng dữ liệu và các thao tác cho giao diện: [thiết kế bước 2](</Users/thien/Documents/School/Luận văn/web_app/docs/STEP_2_TIMELINE_DATA_API_DESIGN_2026-10-27.md>).

## Cách triển khai để dễ kiểm soát

**Bước 1–3 và frontend timeline đã có phần triển khai.** Giao diện dùng API lưu bố cục và báo cáo căn thời gian đã chuẩn bị. Bước 4 dùng kết quả này để mở rộng thời lượng, xử lý theo khối và tiếp tục sau ngắt. Bước 5 có thể chuẩn bị thiết kế song song, rồi kiểm toàn luồng khi transcript dài đã ổn định. Mỗi bước có kiểm tra riêng; bước 6 là nghiệm thu tổng thể.

Giữ các bộ phận ASR chia đoạn và cache đang có, bổ sung phần còn thiếu. Chỉ tăng giới hạn 20 phút hiện tại sau khi có xử lý theo khối và kết quả đo phù hợp. Với thời gian nghỉ không rõ, vẫn cho rà transcript theo từng phần và hiển thị khoảng chưa xác định.

Chốt định dạng đầu vào/đầu ra của phần biên tập mới trước khi sinh thêm dữ liệu huấn luyện quy mô lớn. Những lỗi về mất audio, thiếu mốc thời gian và mất tiến độ cần sửa ở pipeline.

Chưa ước lượng số ngày hoặc cam kết độ chính xác trước khi thử trên dữ liệu và máy thực tế.

Tham khảo: [báo cáo nghiên cứu và nguồn bài báo](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/LONG_MEETINGS_PAUSE_RESUME_RESEARCH_2026-10-27.md>).
