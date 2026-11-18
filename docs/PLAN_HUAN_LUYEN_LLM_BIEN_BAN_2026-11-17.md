# Kế hoạch thảo luận huấn luyện LLM cho biên bản Minda

## Câu hỏi cần trả lời trước khi train

Trong điều kiện có cùng lời chép, Qwen mất ý ở bước trích xuất, chọn và sắp xếp, hay diễn đạt? Chạy trên cùng một nhóm ca với đồ thị tự trích xuất và đồ thị đã được người rà. Tiếp tục cho bộ sinh dàn ý đã được người rà. Ghi lỗi theo từng bước và theo từng trường quan trọng.

| Kết quả chẩn đoán | Can thiệp ưu tiên |
| --- | --- |
| Đúng khi cấp đồ thị chuẩn | Cải thiện trích xuất hành vi, giá trị thuộc tính và quan hệ cập nhật. |
| Đồ thị đúng, dàn ý tự động vẫn lược ý cần giữ | Sửa quy tắc chọn ý hoặc gán nhãn cho bộ lập dàn ý. |
| Đồ thị và dàn ý đều đúng, câu sinh vẫn sai hoặc phải trích nguồn thường xuyên | Thử SFT cho bộ viết, tập trung vào các lỗi được tái hiện. |
| Người chấm xác nhận câu đúng, verifier thường từ chối hoặc thiếu ánh xạ | Hiệu chỉnh verifier và hợp đồng đầu ra. Thử huấn luyện verifier riêng nếu lỗi còn phổ biến. |

Phép thử đồ thị chuẩn và việc gắn từng câu với nguồn vận dụng hai tác vụ sắp xếp và quy chiếu của PlanGTG cùng cách chú giải bằng chứng của ExplainMeetSum. [PlanGTG](https://aclanthology.org/2025.naacl-long.513/), [ExplainMeetSum](https://aclanthology.org/2023.acl-long.731/)

## Dữ liệu và hợp đồng

Gói ngày 26/10 có 144 mẫu train, 108 validation và 84 test, với các ID rời nhau ở ba tệp. Cả 12 ID trong `new_dev.jsonl` đều nằm trong 108 mẫu validation. Kiểm tra tiếp mức trùng theo họ tình huống. Bộ đã dùng để gỡ lỗi đồ thị phục vụ kiểm hồi quy. Xây một tập kiểm tra mới bằng những cuộc họp chưa tham gia việc viết prompt hay chọn checkpoint. Chia theo cuộc họp và họ tình huống trước khi tạo biến thể lỗi. [Giao thức đánh giá cũ](../artifacts/llm-next-round-v2-20261026/EVALUATION_PROTOCOL.md)

Mỗi ca dùng cho chấm nên có lời chép và phiên bản, sự kiện nguyên tử, các thuộc tính cùng đoạn dẫn chứng, quan hệ cập nhật nếu có, dàn ý, bản viết và nhãn của người chấm. Người rà cần phân biệt phát biểu đề xuất, quyết định tập thể, phân công, xác nhận hoàn thành và điều kiện chưa thỏa. Khi chọn một mệnh đề để chấm, truy về phạm vi ký tự trong lời chép và mốc của lượt lời.

- **Bộ viết.** Dựng ví dụ từ gói đầu vào mà runtime gửi thật, gồm các ý đã chọn theo thứ tự, giá trị hiệu lực và quy tắc văn phong theo mục. Đầu ra của chế độ compact là `title`, `text` và `evidence_ids` tùy trường hợp. Dùng bản viết đã rà và gắn cùng các mệnh đề đúng. Chuyển đổi các mẫu cũ dùng `paragraphs` và `unit_ids` sang hợp đồng này rồi kiểm lại bằng người.
- **Bộ trích xuất.** Lấy lời chép và ngữ cảnh như runtime. Nhãn cần có câu trích nguyên văn, kiểu sự kiện, thuộc tính gắn với đúng người và nhiệm vụ, và mảnh nguồn đủ để phân biệt hai đầu việc cùng ngày. Học riêng những ca có nhiều ý trong cùng lượt.
- **Bộ kiểm.** Xây cặp đúng và sai với hai nguồn có cùng tập ngày hoặc tên. Tạo lỗi đổi người và hạn, thay phiên bản tài liệu, lược điều kiện, biến “được giao” thành “đã làm” và biến đề xuất thành kết luận. Mỗi lỗi có vị trí câu và nguồn đối chiếu. Giữ riêng nhãn thiếu ý, thêm ý ngoài nguồn, mâu thuẫn và nguồn chưa đủ.
- **Văn phong.** Chọn cặp viết lại từ cùng dàn ý, đối chiếu trước và sau ở cấp mệnh đề. Chấm giọng trung tính, độ tự nhiên, cách nhóm ý, cách giữ tên ở chỗ cần phân biệt và sự cô đọng tại cùng độ đầy đủ. Các bản sửa làm đổi ý dùng cho ca học về nội dung. [Mir et al.](https://aclanthology.org/N19-1049/), [SIEVE](https://aclanthology.org/2026.findings-aacl.184/)

## Lượt thử trọng số

Adapter sẵn có dùng `Qwen/Qwen3-4B-Instruct-2507` revision `cdbee75f17c01a7cc42f958dc650907174af0554`, rank 8, alpha 16 và hai module `q_proj`, `v_proj`. Runtime web dùng snapshot MLX 4-bit của cùng họ mô hình. Cần kiểm tokenizer, chat template và các mệnh đề ra trên runtime đích trước khi dùng adapter. [Cấu hình adapter v1](../artifacts/llm-next-round-v2-20261026/baseline_adapter/adapter_config.json), [Cấu hình runtime hiện tại](../configs/minutes.yaml)

Nếu chẩn đoán xác nhận lỗi chính ở bộ viết, bắt đầu bằng một lượt SFT có kiểm soát với LoRA hoặc QLoRA. So sánh model nền, adapter v1 và một adapter học hợp đồng mới trên cùng gói đầu vào. Có thể thử một ứng viên khởi tạo từ model nền và một ứng viên học tiếp từ v1 nếu muốn đo ảnh hưởng của khởi tạo. Khóa tokenizer, revision, prompt, ngân sách sinh và cách chấm trước phép so sánh. Chọn checkpoint trên dev theo lỗi nội dung và tỷ lệ hoàn tất JSON. [LoRA, ICLR 2022](https://openreview.net/forum?id=nZeVKeeFYf9), [QLoRA, NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/hash/1feb87871436031bdc0f2beaa62a049b-Abstract-Conference.html)

Lưu revision, hash dữ liệu, prompt và checkpoint, seed, phần cứng, dtype, số token, EOS, thời gian và số trường hợp phải dùng đoạn nguồn. So sánh chất lượng của adapter còn cần thử tải đúng adapter vào runtime dự kiến phát hành, với các ca dài, ca lỗi JSON và ca có nhiều phiên.

## Cách chọn ứng viên và nội dung buổi thảo luận

Đo trên các cặp đầu ra của cùng cuộc họp. Chấm độc lập tỷ lệ mệnh đề có căn cứ và tỷ lệ ý bắt buộc được viết đúng, rồi báo lỗi theo chủ thể, nhiệm vụ, hạn, điều kiện và trạng thái. Báo thêm tỷ lệ ánh xạ tự động, trích nguồn, JSON hoàn tất và thời gian chạy. Chấm mù độ dễ đọc và công sửa tay. Rà chênh lệch giữa hai người chấm trước khi tổng hợp. [FActScore](https://aclanthology.org/2023.emnlp-main.741/)

1. Chọn ca đại diện và thống nhất nhãn được xem là lỗi nghiêm trọng.
2. Chốt phạm vi chia dữ liệu theo cuộc họp, người rà và điều kiện sử dụng lời chép trong môi trường train.
3. Xem kết quả phép thử đầu vào chuẩn để chọn huấn luyện bộ viết, bộ trích xuất hay bộ kiểm trước.
4. Chốt cấu hình thử và tiêu chí chọn checkpoint trước khi mở tập test mới.
