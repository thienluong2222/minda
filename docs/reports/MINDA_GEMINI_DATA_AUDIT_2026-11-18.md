# Kiểm định dữ liệu đồ thị do agent Gemini tạo

Ngày 18/11/2026 · Bộ `graph-synthetic-v1` · ontology Minda 2.0

**Bộ dữ liệu đạt kiểm tra định dạng và có thể dùng các mẫu đã rà để thử đường ống SFT.** Việc dùng cả gói để huấn luyện hoặc chốt bộ đánh giá cần một lượt sửa payload, đối chiếu nhãn và bổ sung tình huống. [Hướng dẫn sinh dữ liệu](../HUONG_DAN_SINH_DU_LIEU_DO_THI_MINDA.md)

## Đã kiểm trực tiếp

| Tập | Họ kịch bản | Ca đã xuất | `extract` | `relations` |
| --- | ---: | ---: | ---: | ---: |
| Train | 12 | 18 | 21 | 21 |
| Dev | 6 | 7 | 7 | 7 |
| Test | 6 | 8 | 8 | 8 |
| Tổng | 24 | 33 | 36 | 36 |

- **Tệp và bộ chia.** 72/72 dòng đúng `messages`, prompt khớp mã Minda, chỉ mục truy được về đúng ca và đúng lô. Số họ xuất hiện ở nhiều tập bằng 0. Số nhóm payload giống hệt giữa các tập cũng bằng 0. Hai cặp lô trùng nguyên đầu vào và nhãn nằm trong train, ở dòng 17 và 19 của mỗi tệp. Train có **20 đầu vào khác nhau cho mỗi tác vụ**. [Chỉ mục xuất](../../artifacts/graph-synthetic-v1/export_index.jsonl)
- **Nạp bằng Qwen3.** Cả 72 dòng khớp tiền tố chat template và có token kết thúc ở phần đáp án. Mẫu dài nhất có 1.048 token cả prompt lẫn đáp án. Số token đáp án cao nhất là 218. Số đo dùng tokenizer đang cấu hình cho Minda. [Cấu hình runtime](../../configs/minutes.yaml)
- **Phát lại nhãn qua mã Minda.** Dùng chính JSON trong `assistant`, đưa qua parser, hàm trích, hàm nối và bộ dựng đồ thị. Với cửa sổ đã xuất, 33/33 ca dựng được đồ thị hợp lệ, gồm **120 sự kiện, 75 thuộc tính có neo dẫn chứng, 35 cạnh** và **13 cạnh được áp dụng để cập nhật thuộc tính hoặc vòng đời**. Cả 83 điều kiện kiểm tra có khai báo trong `expected_state` khớp. Vì nguồn kiểm là đáp án đã ghi, các số này đo tính tương thích kỹ thuật và mức nhất quán của bộ nhãn. [Kết quả kiểm bằng mã](../../../reports/minutes_graph/20261118/gemini_data_audit/results.json) · [Mã phát lại](../../../reports/minutes_graph/20261118/gemini_data_audit/verify.py)

Các cặp đổi hạn đã chốt và đề nghị đổi hạn tái dựng đúng hạn hiệu lực. Cặp `case_tt_02_base` và `case_tt_02_swap_target` giữ hai nhiệm vụ cùng hạn, đổi đúng nhiệm vụ được chuyển sang Tâm theo câu nguồn. Đây là các ca kiểm hồi quy dùng được ngay. [Hồ sơ ca](../../artifacts/graph-synthetic-v1/cases.jsonl)

## Payload cần xuất lại

Agent đưa ba lượt gần nhất vào `context`. Runtime Minda còn bổ sung lượt trước đó theo độ tương đồng E5. Tính embedding bằng worker E5 đã có sẵn và gọi `extract_events` để bắt payload thật cho thấy **3/36 lô trích xuất** đổi cả ngữ cảnh lẫn alias. [Mã lấy ngữ cảnh](../../src/meeting_pipeline/minutes/graph_builder.py#L207)

| Ca | Lô tính từ 1 | Lượt được E5 thêm | Vai trò của thay đổi |
| --- | ---: | --- | --- |
| `case_mm_02_base` | 2 | `t1`, `t3` | Ba mã hiện tại chuyển từ `u3`–`u5` sang `u5`–`u7`. |
| `case_mm_02_out_of_window` | 2 | `t3` | Sáu mã hiện tại chuyển từ `u3`–`u8` sang `u4`–`u9`. |
| `case_mm_02_out_of_window` | 3 | `t1`, `t2`, `t3` | Mã của câu chốt đổi hạn đổi từ `u3` sang `u6`. Bước trích thấy lại nhiệm vụ gốc ở `t1`. |

Mình thử dựng lại payload và ánh xạ đáp án trong bộ nhớ. Cả ba lô phát lại thành công, cho cùng sự kiện và thuộc tính neo vào đúng nguồn.

`case_mm_02_out_of_window` có một bẫy khác ở bước nối. Bộ sinh cố ý cho `issue` của việc gốc và câu đổi hạn để trống. Khi thử gán cho hai nút nhãn có nguyên văn trong nguồn là “gửi biên bản bàn giao kho”, cơ chế truy hồi theo `issue` đưa việc gốc trở lại cửa sổ nối. Cần ghi rõ ca này đo tác động của **nhãn vấn đề bị thiếu**, đồng thời lưu hạn kỳ vọng toàn cuộc họp là “trước 15/8” cùng căn cứ `t13`. `case_mm_02_base` cũng mang tag `missing_target_in_window` dù cạnh đã xuất. [Kịch bản hai ca](../../artifacts/graph-synthetic-v1/scripts/scenarios_data.py#L842)

## Nhãn cần rà lại

| Ca | Vấn đề khi đối chiếu lời chép | Cách sửa |
| --- | --- | --- |
| `case_qa_03_base` · dev | `condition` của câu trả lời là “Khi đó”, một cụm quy chiếu chưa tự nêu điều kiện. Ca này cũng đưa `20/7`, ngày thi dự kiến, vào `deadline`. | Giữ cạnh quy chiếu về câu hỏi. Nếu muốn trích điều kiện từ câu trả lời, viết lại để nêu đủ “nếu phòng máy tầng ba chưa sửa xong”. Giữ ngày thi trong lời nguồn và dùng `deadline` cho hạn thực hiện công việc. |
| `case_md_04_base` · test | Cạnh `opposes` nối yêu cầu dành ngân sách cho hội thảo với phương án dành 60% cho video. Hai khoản có thể cùng tồn tại. | Thể hiện rõ sự phản đối mức 60% trong lời chép nếu muốn giữ `opposes`. |
| `case_qa_02_base` · train | Câu hỏi về **hạn nhận hồ sơ** được nối với câu trả lời về **ngày mở đơn**. Hai mốc khác nhau. | Viết lại câu đáp để nói rõ hạn nhận hồ sơ còn bỏ ngỏ hoặc làm rõ quan hệ giữa hai mốc. |
| `case_dv_01_base`, `case_dv_04_base` | Hai nút quyết định có `condition`. Dẫn chứng lưu cho cạnh `accepts` hoặc `supersedes` kết thúc trước mệnh đề điều kiện, trong khi vòng đời ở nút đích đã đổi. | Lấy đoạn trích bao gồm cả mệnh đề điều kiện và thêm ca đối chứng khi chưa có căn cứ điều kiện đã thỏa. |

Trong lần rà này mình đối chiếu nhãn đã xuất với lời chép và các đoạn dẫn. Hai hàm `blind_verify_*` của agent nhận đáp án làm tham số và chủ yếu kiểm chuỗi con, phạm vi ID và thứ tự. Gói hiện tại chưa có kết quả từ lượt chấm chỉ đọc lời chép, hoặc metadata lưu model sinh và phiên bản prompt sinh. Hash trong manifest là của prompt runtime. Mốc thời gian mô phỏng được điền khi tạo `IndexedTurn`, còn hồ sơ gốc lưu 0/120 lượt có đủ hai mốc. [Mã kiểm của agent](../../artifacts/graph-synthetic-v1/scripts/pipeline.py#L54)

## Độ phủ cần bổ sung trước khi mở rộng SFT

- **Dạng cuộc họp.** Gói có đủ 6 dạng và 5 bối cảnh. Mỗi ca có 2–13 lượt, trung vị 3 lượt, tối đa 3 người. Cả 120 đơn vị có đúng một sự kiện. Bổ sung bài trình bày nhiều ý trong một lượt, trao đổi từ bốn người, câu đính chính, lời ngập ngừng và tham chiếu qua nhiều lô.
- **Cặp đối chứng.** Cặp đổi hạn qua hai phiên ở `fam_mm_04` có 6 lượt ở bản đã chốt và 3 lượt ở bản đề nghị. Khi dùng cặp này để chấm khả năng phân biệt mức xác nhận, giữ cùng các lượt nền và chỉ đổi đúng câu mang tín hiệu chốt.
- **Các loại cạnh.** Train có 5/8 loại, thiếu `withdraws`, `supersedes` và `depends_on`. Dev có 0 cạnh `amends`, nên điểm dev hiện tại chưa đo được việc áp dụng đúng sửa hạn hoặc đổi người. Bảy cạnh `amends` toàn gói chỉ gồm 5 đổi hạn và 2 đổi người. Thêm ca sửa điều kiện và phiên bản tài liệu, cùng ca có căn cứ lẫn ca dễ nối nhầm.
- **Nhiễu lời chép và người nói.** Số ca nhiễu ASR được chấp nhận là 0. Tình huống mất từ “chưa” nằm ở `rejected.jsonl`. Ca người nói chưa xác định cũng bị loại, dù có thể giữ sự kiện nhận việc và thời hạn nếu nguồn đủ rõ rồi để trống người nhận. Bổ sung nhãn thiếu căn cứ để mô hình học cách giữ phần chắc chắn.

Thứ tự sửa phù hợp là xuất lại ba lô bằng luồng thực tế, bỏ các dòng trùng, rồi giao Gemini một lượt chấm mới chỉ có transcript, cửa sổ và ontology. Lưu các bất đồng và đoạn dẫn giải quyết chúng. Sau đó bổ sung những nhãn thiếu trong các họ kịch bản riêng của train, dev và test. Khi tập dev đã sửa, chạy lại đối chứng Qwen3 trên phiên bản đó để số đo trước và sau LoRA dùng cùng nhãn.
