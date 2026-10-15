# LLM và Fuzzy C-Means cho biên bản

Cập nhật: 10/10/2026. Đây là bản tích hợp thử nghiệm dùng model gốc,
chưa fine-tune. Không sửa thêm VAD trong đợt này.

## Phạm vi hiện tại

- Nhận mẫu `.docx` và `.doc` qua bộ chuyển đổi hiện có; xuất DOCX chỉnh sửa được.
- Chi tiết: giữ đề mục, thứ tự và định dạng mẫu, điền vào các vùng trống có thật.
- Tổng quát: chỉ tạo các mục chủ đề bên trong một vùng nội dung đã chọn.
- Sửa transcript tối thiểu, biên tập văn nói, lưu đối chiếu và liên kết căn cứ.
- Tạo lại biên bản từ timeline đã có, không chạy lại âm thanh/ASR.
- PDF/ảnh scan và OCR vẫn là bước tiếp theo trong plan; giao diện đợt này chưa nhận chúng.

## Model và runtime

| Thành phần | Cấu hình |
| --- | --- |
| LLM | `mlx-community/Qwen3-4B-Instruct-2507-4bit` |
| Revision | `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b` |
| Embedding | `intfloat/multilingual-e5-small`, 384 chiều, masked mean + L2 |
| Revision embedding | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| Runtime | MLX-LM 0.29.1, MLX 0.32.3, Apple Silicon |
| Ngữ cảnh mỗi yêu cầu | Tối đa 6.144 token đầu vào và 2.048 token đầu ra |
| Gom cụm thử nghiệm | FCM, `m=1.3`, thử tối đa 4 cụm, có phương án một cụm |

Weights được tải một lần về `data/model_cache/minutes/hub` (khoảng 2,75 GB
cho hai bộ weights đã chọn). Khi xử lý, worker đọc snapshot local với chế độ
offline. Cache nằm trên đĩa; model vẫn cần RAM khi suy luận. Kết thúc một job
biên bản sẽ giải phóng worker. Không gửi transcript ra dịch vụ LLM bên ngoài.

Thiết lập từ thư mục gốc dự án:

```bash
uv sync --locked --all-extras
uv venv .venv-llm --python .venv/bin/python
uv pip install --python .venv-llm/bin/python -r requirements-minutes-mlx.txt
.venv/bin/python scripts/prepare_minutes_models.py
.venv/bin/meeting-pipeline serve --host 127.0.0.1 --port 8000
```

Runtime riêng tránh thay đổi bộ torch/ASR hiện có. Phiên bản và revision được
ghim trong `requirements-minutes-mlx.txt` và `configs/minutes.yaml`.
Không tự tải model khi mở giao diện hay gọi API tạo biên bản.

## Cách sử dụng demo

1. Mở một kết quả âm thanh và phần **Biên bản Word**.
2. Chọn **Chi tiết** hoặc **Tổng quát**, bật **Dùng LLM để hiểu và biên tập**.
3. Với tổng quát, bật **Gom chủ đề tự động** để chạy E5 + FCM.
4. Tải mẫu Word, hoặc bấm **Tạo lại từ transcript hiện có** khi đã có mẫu.
5. Nếu mẫu có nhiều vùng nội dung, chọn đúng trường nội dung; hệ thống không
   tự chọn một vùng mơ hồ.
6. Đọc các cảnh báo, đối chiếu căn cứ, sửa trường cần thiết rồi tải DOCX/ZIP.

Chế độ tổng quát yêu cầu bật LLM. Tắt FCM ở chế độ này tạo baseline một nhóm.
Chi tiết không dùng FCM để thay đề mục. Sau khi chỉnh transcript, biên bản LLM
được đánh dấu cần tạo lại. Các trường người dùng đã chỉnh được giữ khi tạo lại.
Chỉ một worker biên bản được phép chạy tại một thời điểm, kể cả giữa các tiến trình.

API:

```text
GET  /api/minutes/models
POST /api/runs/{job_id}/minutes/regenerate
GET  /api/runs/{job_id}/minutes
```

Body tạo lại, không cần upload lại mẫu:

```json
{
  "use_model": true,
  "mode": "general",
  "correct_transcript": true,
  "use_fcm": true,
  "clusters": null,
  "content_field_id": null
}
```

`clusters` cho phép yêu cầu số cụm; để `null` để thử/chọn tự động.
`content_field_id` cần thiết khi có nhiều vùng nội dung hợp lệ.

## Quy trình và các kiểm tra

```text
Mẫu Word → parser/anchor → schema cùng nhãn và đề mục gốc
Timeline → đơn vị ý nghĩa có ID, người nói và mốc thời gian
         → sửa tối thiểu, lưu gốc/đề xuất/quyết định chấp nhận
         → chuẩn hóa metadata có căn cứ
         → chi tiết: điền trường sẵn
           tổng quát: E5 → FCM → biên tập từng đơn vị
         → kiểm tra ID, số, phủ định/điều kiện → điền DOCX
         → chuẩn hóa thể thức đã chọn → kiểm tra và xem trước các trang
```

- Lượt không có transcript hợp lệ được liệt kê; LLM không đoán phần âm thanh mất.
- Không âm thầm cắt transcript dài; chia thành batch theo tokenizer thực.
  Ngữ cảnh bổ trợ được giới hạn token, mọi đơn vị nguồn vẫn có batch xử lý.
- Khi sửa transcript, thay đổi tên đã biết, số, phủ định/điều kiện hoặc sửa quá
  nhiều sẽ bị từ chối. Đây là kiểm tra bảo thủ, có thể giữ lại một lỗi ASR thật.
- Khi viết nội dung, mỗi item có đúng một ID nguồn; thiếu/trùng/thêm ID thì giữ
  các câu nguồn của batch. Thay đổi số, mất từ phủ định/điều kiện, mất tên chủ thể
  đã biết hoặc tự thêm trạng thái “đã” cũng bị chặn.
- Metadata ngày/giờ/số phiếu không giao hoàn toàn cho văn bản tự sinh; chuẩn hóa
  thông tin tường minh bằng mã. Không tự lấy ngày họp làm ngày ban hành.
- FCM thử nhiều seed, kiểm tra cụm quá nhỏ, tâm co, silhouette và độ ổn định;
  có thể giữ một cụm. Membership là độ thuộc cụm, không phải xác suất đúng.
- Chỉ một nhóm chủ đề chính sở hữu mỗi đơn vị, giữ thứ tự thời gian bên trong
  nhóm. Nhóm được xếp theo lần xuất hiện đầu tiên.
- Bước điền nội dung chỉ sửa `word/document.xml`. Từ cập nhật 15/10/2026,
  bước định dạng tiếp theo chuẩn hóa styles, lề, phần đầu, khối ký và số trang
  theo Nghị định 30 hoặc Hướng dẫn 05. Giữ câu chữ, thứ tự đề mục nội dung
  và bản mẫu gốc; bố cục và số trang có thể thay đổi. Các phần ZIP không liên
  quan được giữ lại. Xem [thể thức DOCX](DOCX_FORMAT_STANDARDS.md).
- Lỗi sinh biên bản khôi phục lại bộ template/minutes/export cũ.

## Artifact và khả năng truy vết

Trong mỗi run có:

- `minutes/corrections.json`: câu gốc, đề xuất sửa, chấp nhận/từ chối và lý do.
- `minutes/corrected_transcript.json`: bản sửa để đối chiếu, không ghi đè timeline gốc.
- `minutes/topics.json`: đơn vị nguồn, membership, nhóm, nội dung biên tập, ID coverage.
- `minutes/model_report.json`: revision, token, số lần gọi/cache hit, bộ nhớ, cảnh báo.
- `minutes/configuration.json`: lựa chọn người dùng.
- `exports/completed.docx` và ZIP có manifest/các báo cáo trên.

Cache phản hồi và embedding dùng để lặp lại thử nghiệm nhanh hơn. Báo cáo phân
biệt cache hit; không dùng thời gian cache hit để kết luận tốc độ inference.
Cache và artifact chứa transcript, nằm trong `data/` bị Git ignore, không phải
dữ liệu huấn luyện mới. Giữ chúng theo cùng chính sách dữ liệu của cuộc họp.

## Đánh giá lại trên dữ liệu sẵn có

```bash
.venv/bin/python scripts/benchmark_llm_fcm.py \
  --output data/evaluations/llm_fcm_20261010_release
```

Script so 8 ca: transcript tham chiếu và transcript ASR × baseline, chi tiết,
tổng quát một nhóm, tổng quát FCM. Fact tham chiếu không đưa vào prompt.
Kết quả và giới hạn tại
[báo cáo 10/10/2026](reports/LLM_FCM_EVALUATION_2026-10-10.md).

Đây mới là một kịch bản TTS và một họ mẫu, được dùng để phát triển cấu hình.
Chưa có tập độc lập để tuyên bố chất lượng tiếng Việt tổng quát. ID coverage
không chứng minh câu đã giữ đủ ngữ nghĩa. Bản nháp LLM luôn cần rà soát;
chưa có dữ liệu fine-tune, chưa huấn luyện model trong đợt này.
