# Minda — kết quả triển khai bước 3

Ngày: 27/10/2026. Thay đổi nằm trong working tree `web_app`, chưa commit. Đã có bộ xử lý timeline nhiều nguồn, căn âm thanh theo từng phần và xuất transcript kèm căn cứ từ file gốc. Giao diện kéo thả và mở rộng xử lý nhiều giờ chưa thuộc lần này.

## Hành vi đã có

| Tình huống | Cách xử lý |
| --- | --- |
| Nhiều file của cùng thiết bị, đã biết mốc hoặc khoảng nghỉ | Dùng đúng vùng audio, thứ tự và khoảng cách đã khai báo; khoảng không được ghi chỉ là đệm để xử lý, không được tính là audio có thật. |
| Hai thiết bị bật khác lúc | Tìm dấu âm thanh chung để nối đồng hồ; không còn chỉ tìm trong cửa sổ offset nhỏ của đường xử lý cũ. |
| Một nguồn pause rồi ghi tiếp trong cùng file, nguồn khác ghi liên tục | Tìm các cụm mốc trước/sau điểm nhảy, tạo ánh xạ riêng cho từng phần và chia lượt xử lý tại biên. |
| Đồng hồ trôi trong phần liên tục | Ước lượng hệ số thời gian và offset, rồi tinh chỉnh bằng tương quan waveform tại nhiều điểm. |
| Không có đối chiếu trực tiếp nhưng có nguồn trung gian | Ghép qua đường căn cứ không vòng; khi căn cứ bị mâu thuẫn, các phần phụ thuộc cũng chuyển sang cần rà. |
| Mọi thiết bị cùng dừng, không biết độ dài khoảng nghỉ | Giữ thứ tự đã khai báo và đồng hồ cục bộ cho phần chưa nối; không cộng sát thành một cuộc liên tục. |
| Âm thanh lặp hoặc mốc tự động mâu thuẫn với khai báo | Loại mốc mơ hồ hoặc giữ đề xuất để rà; không ghi đè bố cục người dùng. |
| Chọn một file thành nhiều vùng | Giữ ID đoạn và quy ngược về vị trí trong file gốc, theo mẫu audio đã giải mã. |
| Thời lượng container chỉ là ước tính | Khi chọn toàn file, dùng đủ độ dài sau giải mã dù ước tính dài hơn hoặc ngắn hơn thực; giữ cảnh báo và bố cục khai báo ban đầu. |
| Nội dung ngoài biên bản | Vẫn giữ trong transcript; chặn text và token của vùng `excluded` khỏi đầu vào trích xuất/biên tập biên bản. |

## Cách căn thời gian

Bộ mới tìm các đỉnh phổ cục bộ và cặp dấu âm thanh thưa, sàng các cặp bản ghi có khả năng chung nội dung, rồi tìm nhiều nhóm offset theo thời gian. Tương quan waveform tinh chỉnh các nhóm mốc và vị trí chuyển giữa hai ánh xạ. Phần liên tục dùng mô hình tuyến tính; điểm nhảy thời gian tạo phần riêng. Âm đơn lặp và một đoạn broadband xuất hiện nhiều lần có kiểm tra chống ghép mơ hồ.

Đây là bản triển khai thử nghiệm độc lập, lấy hướng từ fingerprint và đồng bộ nhiều bản ghi trong [báo cáo nghiên cứu](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/LONG_MEETINGS_PAUSE_RESUME_RESEARCH_2026-10-27.md>). Không phải bản tái hiện nguyên vẹn Panako, thuật toán Tsai hay DWACD. Các ngưỡng về số mốc, residual, điểm nhảy và trôi đồng hồ là ngưỡng kỹ thuật ban đầu, cần hiệu chỉnh bằng dữ liệu thực.

Phần biên chưa có mốc chỉ được ngoại suy khi đường căn đang dùng cùng một mô hình tuyến tính, với giới hạn `sync.max_offset_seconds` (mặc định 120 giây mỗi phía). Transcript đánh dấu `estimated` và `needs_review`; không gán residual đo được cho vùng ngoại suy. Vùng chuyển chưa xác định hoặc quá xa giữ đồng hồ cục bộ. `boundary_uncertainty_ms` mô tả độ rộng tìm kiếm số học, chưa phải khoảng tin cậy đã hiệu chuẩn.

Nếu không có mốc thủ công, chọn phần đầu dài nhất của một nguồn làm đồng hồ tham chiếu; không lấy phần ghi về sau làm gốc chỉ vì nó dài hơn. Đây là gốc tương đối của bản ghi tham chiếu, không xác nhận giờ thực hoặc toàn bộ thời lượng cuộc họp ngoài phần được ghi.

## Hợp đồng dữ liệu cho giao diện timeline

Các API lưu/sửa của bước 2 giữ nguyên. Upload bằng `timeline_mode=true` hoặc vào một hàng cụ thể dùng `alignment_mode=auto`; thao tác sửa cấu trúc cũng kích hoạt chế độ này. Bố cục cũ ở `legacy` và chỉ sửa trình bày vẫn dùng đường xử lý cũ, giữ hash nội dung cũ.

`GET /api/v1/meetings/{id}/timeline` có thêm:

- `last_alignment`: artifact báo cáo căn thời gian của lần xử lý gần nhất.
- `alignment_stale`: báo kết quả không còn tương ứng bố cục/nội dung hiện tại.
- `processing.mode`: `timeline` cho bộ mới; `legacy_auto` cho đường cũ. Bố cục trống, chưa xếp hết file hoặc không hợp lệ vẫn bị chặn trước khi nạp model.

Client đã có `getTimelineAlignment(view)` trong [timeline.ts](</Users/thien/Documents/School/Luận văn/web_app/apps/web/src/lib/timeline.ts>) và các kiểu `TimelineClockSpan`, `TimelineAlignmentReport` trong [types.ts](</Users/thien/Documents/School/Luận văn/web_app/apps/web/src/lib/types.ts>). Hàm trả `null` khi không có kết quả hoặc kết quả đã cũ.

`resolved_positions` là hình học suy từ bố cục khai báo. Hình học sau xử lý nằm trong `alignment.spans[clip_id]`, có thể gồm nhiều phần của cùng clip. Với thời gian `τ` tính từ đầu vùng đã chọn của clip:

```text
t_clock = scale × τ + offset
t_transcript = t_clock + meeting_origin_shift_sec   (chỉ khi clock_id = meeting)
t_file_gốc = source_in_ms / 1000 + τ
```

Không cộng gốc của phần cục bộ vào đồng hồ cuộc họp. Báo cáo có `origin` (`declared`, `reference`, `sequential`, `acoustic`, `extrapolated`, `local`), mốc hỗ trợ, residual, đường căn cứ `via`, xung đột và `proposed_spans`. Bố cục gốc và mốc người dùng không bị thay bằng kết quả tự động. Khi phát hiện phần cùng nguồn chồng sai vị trí, hệ thống chuyển phần đó và các phần phụ thuộc sang đồng hồ cục bộ, giữ đề xuất để đối chiếu.

Transcript có `clock_id`, nhãn phần, `time_status`, `meeting_start_sec/end_sec` và `component_timebase`. Thời gian cuộc họp bằng `null` ở phần chưa căn được. `recording_evidence` và `selected_recording_evidence` ghi file, clip, hàng nguồn, vùng mẫu audio và ánh xạ đã dùng. Chỉ số mẫu thuộc audio mono đã giải mã ở `decoded_sample_rate`, không phải byte hay khung mã hóa trong file nén.

Giao diện transcript hiện có nhãn thời gian cục bộ, thời gian ước lượng, nội dung ngoài biên bản và thông báo cần rà. Chưa có giao diện kéo thả. Danh tính người nói vô danh giữa các thành phần đồng hồ độc lập được đặt mã riêng để tránh nhận nhầm là cùng người; ID hồ sơ người nói đã đăng ký vẫn được giữ.

## Kết nối ASR và biên bản

Mỗi đồng hồ được dựng riêng theo hàng nguồn và tái sử dụng cùng đối tượng pipeline/model. Coverage là danh sách các vùng được ghi thật. VAD, chọn nguồn, crop người nói và ASR dùng danh sách này; nguồn chỉ có đệm ở một khoảng không được chọn ngay cả khi các nguồn còn lại đều chất lượng thấp. Lượt nói bị cắt ở ranh giới capture/ánh xạ/annotation; không nối lại hoặc lấy ngữ cảnh ASR xuyên ranh giới đó.

`timing_complete=false` khi còn phần cục bộ, xung đột hoặc annotation chưa xác định được đồng hồ. Thời lượng chung khi đó bằng `null`, vẫn có thời lượng riêng các thành phần và transcript để rà. API tạo biên bản, worker và bộ đọc căn cứ đều chặn dùng transcript này làm biên bản toàn cuộc. Sửa/khôi phục phiên bản transcript giữ trạng thái đồng hồ và hash bố cục tương ứng.

`timing_complete=true` chỉ cho biết các phần hiện xử lý đã có chung hệ tọa độ và không có xung đột phát hiện được. Trạng thái này vẫn có thể chứa mốc người dùng khai báo và phần ngoại suy cần rà; không chứng minh thời gian chính xác tuyệt đối hoặc không có pause chưa quan sát được. Chỉ một file đã nối các lần ghi, không có mốc/nguồn đối chiếu, không đủ để biết khoảng thời gian đã mất.

Đầu ra gồm `alignment.json`, `input_timeline.json`, manifest, transcript JSON/CSV/TXT/ZIP và các clip căn cứ. ZIP không chứa các bản WAV toàn bộ đã giải mã/dựng trung gian. TXT/CSV ghi rõ đồng hồ, không trình bày các phần cục bộ như một thời gian chung.

## Kiểm chứng và giới hạn

Kết quả cuối cùng, lệnh kiểm tra, dấu vân tay mã nguồn và log nằm trong [validation_summary.json](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/step3-implementation-20261027/validation_summary.json>).

- 151 kiểm tra pipeline đạt, gồm 12 ca căn thời gian và 8 ca tích hợp timeline. Có ca offset 144 giây, hai lần pause, drift 300 ppm, ghép qua nguồn trung gian, mốc thủ công mâu thuẫn, âm thanh lặp, bảo toàn vùng mẫu và loại nội dung ngoài biên bản.
- 39 kiểm tra backend/API đạt với MongoDB tạm riêng, có đường worker → transcript cục bộ → chặn biên bản và artifact căn thời gian.
- Bốn module lõi mới qua mypy nghiêm ngặt; lint/format Python và frontend đạt; TypeScript và bản build frontend đạt.
- Mypy toàn repo còn 74 chẩn đoán, trùng đường dẫn/nội dung/số lượng với Git HEAD trước thay đổi. Không tuyên bố toàn repo đã sạch lỗi kiểu.

Audio tổng hợp được decode/render thật qua FFmpeg; kiểm tra tích hợp dùng ASR và bộ chia lượt nói thay thế, không tải model. Chưa đo WER, độ đúng người nói, độ chính xác căn trên điện thoại thực, thời gian hoặc bộ nhớ cho cuộc họp dài. Không dùng các kết quả này để công bố chất lượng trên tiếng Việt thực tế.

Giới hạn vẫn là **1.200 giây mỗi file và mỗi khoảng đồng hồ dựng để xử lý**, gồm cả khoảng nghỉ trong khoảng đó. Dù fingerprint tính theo khối và file giải mã lưu trên đĩa, ASR/fusion chưa phải luồng xử lý nhiều giờ có checkpoint. Bước 4 cần xử lý theo khối, phục hồi sau ngắt và nối danh tính/lời nói giữa các phần; bước 5 cần mô hình hóa thay đổi quyết định sau giải lao. Giới hạn này không tự được nới ở bước 3.
