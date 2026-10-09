# Sửa phân mảnh lượt nói và danh sách người tham gia — 09/10/2026

## Phạm vi và phản hồi

Người dùng nhận thấy VAD tạo nhiều đoạn ngắn, cắt giữa lời nói gây khó cho ASR;
danh sách người tham gia bị trùng và đưa “Chưa xác định”, “Nói chồng” vào như tên người.
Đợt sửa này xử lý pipeline đang có, trước khi triển khai kế hoạch LLM và đầu vào PDF/scan.

Mốc code trước sửa: `f94216bd34c8c76bfef67be41b7a0b77f756e796`, nhánh
`codex/vad-speaker-asr-fusion`. Các thay đổi hiện nằm trong working tree.

## Nguyên nhân đã xác nhận

1. `multi_source_fusion.py` đặt giới hạn vùng VAD là 15 giây. Vùng có lời nói
   liên tục vẫn bị cắt đều theo giới hạn này, rồi lại bị tách theo lượt người nói.
2. `_decode` trong `speaker_turns.py` tính mẫu số bỏ phiếu riêng cho từng track.
   Khi hai cửa sổ pyannote gán nhãn cục bộ khác nhau cho cùng lời nói, nhiều track
   có thể đồng thời vượt ngưỡng dù không cửa sổ nào ghi nhận người nói đồng thời.
   Kết quả tạo vùng “nói chồng” giả và các mảnh ngắn ở biên cửa sổ.
3. Bước điền biên bản gom người theo chuỗi tên, không dùng đầy đủ ID và trạng thái.
   Nó còn chọn chủ trì/thư ký theo thứ tự chữ cái của tên, không theo phân công.
4. Giao diện dùng trạng thái danh tính `ambiguous` để hiển thị cả đoạn chưa xác định
   và vùng nói chồng, nên chưa diễn đạt rõ hai trường hợp.

## Thay đổi đã thực hiện

- Giữ vùng hoạt động VAD theo khoảng có tiếng nói; bỏ giới hạn cắt đều 15 giây.
  Giới hạn clip được thực hiện sau khi xác định và gộp lượt người nói.
- Tổng hợp số người nói từ bằng chứng đồng thời trong từng cửa sổ pyannote,
  giảm trọng số ở biên cửa sổ; số track cạnh tranh giữa các cửa sổ không tự tạo overlap.
- Nối khoảng hụt nhận diện tối đa 400 ms khi hai bên là đúng cùng một track đơn.
  Khoảng này được cấu hình qua `segmentation.turn_gap_bridge_ms`.
  Không dùng quy tắc này để hấp thụ lượt của track khác hoặc vùng nói chồng.
- Thêm tối đa 250 ms vào khoảng im lặng quanh lượt nói, chia khoảng trống với lượt
  liền kề để không vượt qua biên đổi người nói. Giữ các câu trả lời ngắn được nhận diện.
- Clip ASR dài được cắt gần vùng năng lượng thấp, cân bằng hai clip cuối để tránh
  đuôi quá ngắn. Clip tối đa 25 giây, ngữ cảnh 750 ms theo cấu hình hiện tại.
  Các clip thuộc cùng lượt có `asr_chunk_group_id`; ngữ cảnh qua biên cắt nội bộ
  được giữ nhưng vẫn bị chặn tại người khác hoặc overlap. Từ đúng tại biên nội bộ
  chỉ thuộc một core.
- Danh sách người tham gia ưu tiên ID hồ sơ (`speaker_id`), sau đó ID trong cuộc họp
  (`meeting_speaker_id`). Timeline cũ thiếu ID được chuẩn hóa tên về Unicode NFC,
  khoảng trắng và chữ hoa/thường. Cùng ID với nhiều tên hiển thị được gộp.
  Hai ID khác nhau không bị gộp chỉ vì trùng tên.
- “Chưa xác định” là trạng thái chưa gán được danh tính; “Nói chồng” là trạng thái
  có nhiều người nói cùng lúc. Hai trạng thái vẫn hiển thị riêng trên timeline,
  không được đưa vào danh sách người tham gia. Cụm “Người lạ N” ổn định vẫn được giữ
  để người dùng xác nhận danh tính.
- Danh sách suy từ người đã phát biểu mang `needs_review`: có thể thiếu người có mặt
  nhưng không nói. Chủ trì/thư ký chỉ được điền từ metadata đã cung cấp hoặc câu phân
  công rõ trong transcript; không có bằng chứng thì để `unknown`.
- Danh sách quản lý người nói trên web dùng cùng quy tắc gộp danh tính. Đổi tên một
  người có nhiều ID cụm cập nhật tất cả cụm cùng ID hồ sơ và ghi lại các ID trong audit.

## Đối chiếu trên artifact đã lưu

Run: `data/meetings/test-c-enroll/runs/3e27f5fa-08d8-443d-a8d3-c44ef62b1479`,
tên “Test có enroll”, dài khoảng 119,9 giây. Replay dùng các NPZ pyannote đã lưu và
cùng aligned audio, cùng nguồn tham chiếu `source-2`, cùng thông tin đồng bộ.
Không suy luận model lại, không thay đổi artifact hoặc biên bản người dùng đã sửa.

| Chỉ số ở bước chia lượt | Artifact trước sửa | Replay sau sửa |
| --- | ---: | ---: |
| Vùng VAD | 8 | 1 |
| Lượt thô, gồm các hàng overlap | 47 | 18 |
| Lượt đơn dưới 1 giây | 10 | 2 |
| Nhóm nói chồng | 4 | 0 |
| Tổng thời gian nói chồng | 5,8 giây | 0 giây |

Đây là mẫu tổng hợp FPT có 13 lượt tham chiếu và không có nói chồng theo
`data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json`.
Việc bỏ overlap trên ca này phù hợp dữ liệu tham chiếu; không có nghĩa hệ thống
được phép bỏ overlap thật. Test riêng kiểm tra giữ overlap thật qua cửa sổ đổi kênh.

Chạy bộ trích xuất mới trên **timeline cũ** cho danh sách `[Minh, Lan, Huy]`,
chủ trì `Minh`, thư ký `Lan`, với evidence trỏ tới lượt đã nêu phân công.
Đây là kiểm tra logic lấy thông tin, không phải transcript mới.

Chi tiết replay và các lượt mới: `pipeline_fragmentation_replay_2026-10-09.json`
trong cùng thư mục.

## Kiểm chứng

- 106 test liên quan đã qua, gồm unit và integration. Kiểm tra các trường hợp:
  nghỉ ngắn giữa cùng track; trả lời ngắn 200/300 ms của người khác; padding;
  nhãn cửa sổ bất đồng không tạo overlap; overlap thật qua cửa sổ đổi kênh;
  ASR clip dài, ngữ cảnh và sở hữu từ ở biên; ID trùng/tên trùng;
  vai trò thiếu, đề xuất hoặc phủ định; quản lý/đổi tên trên web; biên bản hiện có.
- `ruff check` qua trên các file Python đã đổi; `mypy` qua trên 10 file nguồn đã đổi.
- `git diff --check` qua. Không tải model hoặc thêm dependency.

## Giới hạn và bước tiếp theo

- Chưa chạy lại PhoWhisper thật sau sửa, nên chưa có kết luận WER/CER cải thiện.
  Chưa đo DER/JER trên dữ liệu người thật, nhiều tiếng ồn và nói chồng thật.
- Replay còn hai lượt thô dưới một giây gần biên đổi track khoảng giây 107.
  Không tự gán cùng danh tính chỉ để giảm số đoạn. Cần xem sau bước clustering và
  nghe clip nếu tiếp tục xử lý các mảnh này.
- Gộp theo ID sửa lỗi danh sách, không bảo đảm mô hình speaker đã gán ID đúng.
  Báo cáo `speaker_multisource_eval_2026-10-03.md` vẫn ghi nhận lỗi nhận nhầm người
  chưa đăng ký thành người có hồ sơ; cần đánh giá riêng trước khi kết luận ổn định.
- Run/timeline/DOCX đã lưu không tự được xử lý lại. Test chia đoạn cần một run mới;
  biên bản đã được người dùng sửa cần giữ các chỉnh sửa khi tạo lại.
- Thứ tự thảo luận tiếp: đo ASR trên clip mới và các từ sát biên; kiểm tra tính ổn định
  ID người nói, đặc biệt người chưa đăng ký; sau đó đo thời gian/RAM để tối ưu pipeline.
  Kế hoạch tính năng LLM vẫn nằm trong `docs/PLAN_LLM_BIEN_BAN_DOCX_PDF_SCAN_2026-10-09.md`.
