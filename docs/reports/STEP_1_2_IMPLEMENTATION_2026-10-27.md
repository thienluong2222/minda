# Minda — kết quả triển khai bước 1–2

Ngày: 27/10/2026. Thay đổi nằm trong working tree `web_app`. Phạm vi: lỗi ingest/đồng bộ nền, dữ liệu timeline nhiều nguồn, API lưu bố cục và các hàm gọi dành cho giao diện sau này. Không triển khai giao diện kéo thả hoặc xử lý nhiều người nói đồng thời.

**Lưu ý về phiên bản:** báo cáo này ghi lại trạng thái khi kết thúc bước 1–2. Các giới hạn `TIMELINE_PROCESSING_NOT_READY` ở mục 4 đã được thay bằng bộ xử lý bước 3 cho bố cục hợp lệ. Hành vi hiện hành xem [báo cáo bước 3](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/STEP_3_IMPLEMENTATION_2026-10-27.md>).

## 1. Bước 1 đã sửa

- Dịch gốc thời gian của toàn cuộc khi một nguồn bắt đầu sớm hơn máy chuẩn, giữ phần đầu riêng thay vì cắt bỏ. Coverage tính trước khi đệm cuối; có `origin_shift_sec`, `timeline_offset_sec` và `time_scale` để mô tả đồng hồ đầu ra. `offset_sec` giữ ý nghĩa so với máy chuẩn ban đầu cho chẩn đoán.
- Truyền các tham số sync thực từ cấu hình; bỏ giới hạn tìm offset hard-code 10 giây. Các cửa sổ đo drift dùng vị trí tương ứng sau căn thô.
- Giữ `drift_unresolved` khi chưa đo chắc, kể cả khi giá trị drift trả về bằng 0. Bản ghi ngắn không tự chứng minh đồng hồ không trôi; residual căn thô được tách khỏi residual drift.
- API và worker dùng chung cách probe luồng audio đầu tiên, kiểm thời lượng hữu hạn/dương và giới hạn thời lượng. File WebM thiếu stream duration có thể dùng container duration, được đánh dấu là ước tính. API từ chối vượt giới hạn ngay lúc nhận, hoàn tác các file/record mới của lần tải thất bại. Worker còn kiểm lại độ dài sau decode.
- Thời lượng công bố sau xử lý ưu tiên coverage của các nguồn căn được, thay vì chỉ lấy file gốc dài nhất.

Giới hạn hiện tại vẫn là **1.200 giây mỗi file** theo cấu hình. Chưa mở hỗ trợ nhiều giờ vì đọc theo khối và phục hồi công đoạn thuộc bước 4. Bộ ước lượng hiện vẫn là căn thô và drift tuyến tính; tìm fingerprint/ánh xạ gián đoạn nâng cao thuộc bước 3. Kiểm hoạt động ở cửa sổ drift hiện dùng biến thiên tín hiệu, chưa phải xác nhận lời nói bằng VAD.

## 2. Nền timeline đã có

- File gốc giữ ID/kho lưu hiện tại; hàng nguồn (`track`) và đoạn sử dụng file (`clip`) có ID riêng, ổn định khi di chuyển.
- Một hàng chứa nhiều file nối tiếp; một file có thể được tham chiếu bằng nhiều vùng audio. Phiên họp/giải lao được lưu riêng với hàng/file.
- Thứ tự duy nhất nằm trong `track.clip_ids`. Placement là mốc tương đối (`anchored`) hoặc quan hệ với phần trước (`sequential`). Khoảng chưa rõ giữ `null`; không đổi thành 0.
- Thay đoạn đứng trước làm khoảng cách cũ mất hiệu lực: giữ căn cứ cũ trong lịch sử, chuyển quan hệ mới sang chưa rõ. Những thay đổi về clip/mốc còn được ghi trong audit để đối chiếu; lịch sử gọn trên clip giữ 50 lần gần nhất.
- Có `clock_origin` lưu giờ thực kèm múi giờ, chuẩn hóa UTC; thao tác nhập tay chỉ được ghi là do người dùng khai báo. Chưa có luồng nhập nhật ký capture hoặc tìm mốc âm thanh tự động.
- Chuyển hàng/đổi thứ tự/đặt mốc có thể gửi trong một nhóm thao tác, lưu bằng một cập nhật MongoDB có kiểm revision. Sai một thao tác thì không lưu nhóm đó. Kiểm quyền sở hữu và tham chiếu file thuộc đúng cuộc họp.
- Thay đổi ảnh hưởng nội dung đặt lại trạng thái draft, đánh dấu transcript/biên bản cũ cần cập nhật và tăng phiên bản nội dung. Đổi tên hoặc thứ tự trình bày hàng không làm đổi hash nội dung.
- Khi tạo tác vụ, lưu bản chụp và hash timeline; worker kiểm lại trước khi nạp model. Kết quả có `input_timeline.json`, ánh xạ `source-N` sang ID file gốc và hash gắn phiên bản transcript. Bản sửa transcript kế tiếp kế thừa hash này.

Cuộc họp cũ được biểu diễn thành các hàng tạm riêng cho từng file, không tự đoán nối tiếp hoặc offset bằng 0. `GET` không ghi thay đổi vào cuộc họp. Chỉ khi cập nhật mới lưu timeline.

## 3. Hợp đồng cho giao diện sau này

Hàm đã có ở [timeline.ts](</Users/thien/Documents/School/Luận văn/web_app/apps/web/src/lib/timeline.ts>): `getTimeline`, `updateTimeline`, `uploadTimelineFiles`. Kiểu dữ liệu và thao tác ở [types.ts](</Users/thien/Documents/School/Luận văn/web_app/apps/web/src/lib/types.ts>); các hàm dùng cơ chế phiên đăng nhập/CSRF hiện tại.

| API | Cách dùng |
| --- | --- |
| `GET /api/v1/meetings/{id}/timeline` | Lấy revision, timeline, file có URL nghe, các vị trí tính được và trạng thái có thể xử lý |
| `PATCH /api/v1/meetings/{id}/timeline` | Gửi revision và nhóm operations; dùng revision trả về cho thao tác tiếp theo |
| `POST /api/v1/meetings/{id}/sources?revision=…&timeline_mode=true` | Tải file vào kho chưa xếp |
| Thêm `track_id=…` vào đường tải file | Tạo các đoạn vào cuối hàng đó; khoảng cách mặc định chưa biết |
| `POST /api/v1/meetings/{id}/process` | Kiểm khả năng xử lý bố cục trước khi tạo job, rồi lưu bản chụp đầu vào |

Các operation: `create_track`, `update_track`, `reorder_tracks`, `remove_track`, `add_clip`, `move_clip`, `set_placement`, `set_range`, `remove_clip`, `upsert_interval`, `remove_interval`, `set_clock_origin`.

Ví dụ sau khi tải file và lấy ID thực từ `assets`, tạo một hàng và đặt hai phần lên đó:

```json
{
  "revision": 2,
  "operations": [
    {"op": "create_track", "id": "phone-a", "name": "Điện thoại A"},
    {"op": "add_clip", "id": "part-a1", "track_id": "phone-a", "asset_id": "FILE_ID_1"},
    {"op": "add_clip", "id": "part-a2", "track_id": "phone-a", "asset_id": "FILE_ID_2"}
  ]
}
```

Khi thả `part-a2` trước `part-a1`, gửi `move_clip` với `clip_id=part-a2`, `track_id=phone-a`, `before_clip_id=part-a1`. Muốn đưa về cuối hàng thì bỏ `before_clip_id`. Muốn đặt thời gian thủ công thì gửi kèm placement hoặc dùng `set_placement`. Mốc giao diện là mili giây nguyên.

Chỉ gửi khi kết thúc kéo; không cần lưu từng vị trí con trỏ. `resolved_positions` giữ `null` khi chưa đủ mốc: giao diện có thể vẽ các khối tạm để sắp xếp nhưng không ghi tọa độ vẽ thành giờ thực. Mốc đã biết mâu thuẫn trong cùng hàng trả `TIMELINE_POSITION_CONFLICT`; hai hàng khác nhau có thể ghi cùng thời điểm.

Phản hồi `409 REVISION_CONFLICT` yêu cầu tải bố cục mới; không tự gửi đè revision mới. Đang xử lý thì khóa sửa bố cục. Mốc do người dùng nhập không được gửi như `audio_match/verified`.

Mặc định: tối đa 8 hàng nguồn, 128 file trong chế độ timeline và 512 clip. Đường upload cũ vẫn giữ giới hạn số file như trước. Dung lượng mỗi file dùng cấu hình hiện tại; tổng audio được giới hạn bằng số nguồn tối đa nhân dung lượng mỗi file để không tăng trần dung lượng chỉ vì tăng số phần ghi. Các giới hạn này có kiểm ở backend; số file không còn đại diện cho số thiết bị trong dữ liệu timeline.

## 4. Khả năng xử lý hiện tại và phần tiếp theo

**Đã làm xong nền lưu/sửa timeline; chưa có bộ đọc audio theo bố cục gián đoạn.** Hiện chỉ chạy đường xử lý cũ khi mỗi hàng đang dùng một file nguyên vẹn, chưa đặt mốc thủ công, không còn file chưa xếp và chưa có khoảng phiên/loại nội dung cần áp dụng. Bố cục nhiều file nối tiếp, vùng cắt hoặc mốc đặt trả `TIMELINE_PROCESSING_NOT_READY` cùng lý do, ở cả API lẫn worker. Không âm thầm coi các phần nối tiếp là các micro đồng thời.

Giao diện kéo thả chưa được dựng. Có thể xây trên API/hàm gọi đã có; phần xử lý theo vị trí/gián đoạn cần tiếp tục ở bước 3, xử lý dài theo khối ở bước 4 và áp dụng diễn biến/phiên vào biên bản ở bước 5. Nếu cần bỏ một file khỏi cuộc họp đã có timeline, bỏ các clip tham chiếu trước; thao tác này giữ file gốc trong kho.

## 5. Kiểm tra đã chạy

| Nhóm | Kết quả |
| --- | --- |
| Đồng bộ, ingest, cấu hình, chất lượng nguồn và tích hợp fusion với adapter thử | 42 passed ở lần kiểm cuối |
| Toàn bộ backend trên MongoDB thử riêng, gồm đồng thời lưu, trần dung lượng và khôi phục transcript | 38 passed ở lần kiểm cuối |
| Web | TypeScript và `npm run build` đạt |
| Mã nguồn | Ruff và kiểm whitespace đạt |

Hai nhóm Python cuối gồm 80 ca kiểm độc lập. MongoDB thử dùng thư mục tạm/cổng riêng; các test tạo database riêng và dọn sau mỗi ca. Không dùng database cuộc họp đang có.

Đã thử: phần đầu riêng 3 giây được giữ; nguồn bật muộn 45 giây tìm được với cửa sổ cấu hình; zero drift không che trạng thái chưa xác định; WebM/Opus thật do FFmpeg tạo; giới hạn thời lượng/hoàn tác upload; lưu–đọc bố cục; giữ hash file gốc; khoảng chưa biết; hủy hiệu lực khoảng cách khi đổi thứ tự; mốc có múi giờ; một file liên kết nhiều phiên; quyền truy cập; nhóm thao tác lỗi không lưu; hai yêu cầu cùng revision chỉ một yêu cầu thành công; kết quả cũ bị đánh dấu cần cập nhật; worker chặn đầu vào sai trước khi nạp model.

Không nạp lại các trọng số ASR/LLM để benchmark chất lượng trên audio họp dài thực tế. Các kiểm tra fusion dùng adapter thử; đây là kiểm hành vi pipeline và tính toàn vẹn dữ liệu, chưa phải WER hoặc điểm chất lượng biên bản thực tế.

Schema API để làm giao diện: [timeline-openapi.json](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/step12-implementation-20261027/timeline-openapi.json>). Bản ghi kiểm tra và checksum mã thay đổi: [validation_summary.json](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/step12-implementation-20261027/validation_summary.json>).
