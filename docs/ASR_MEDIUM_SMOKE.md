# PhoWhisper-medium: kiểm thử ban đầu và cơ chế chặn lỗi

Ngày 24/09/2026. Đây là **smoke test**, không phải kết luận độ chính xác trên cuộc họp.

## Cấu hình đang dùng

- Mặc định: `vinai/PhoWhisper-medium@55a7e3eb6c906de891f8f06a107754427dd3be79`.
- Đối chứng: `vinai/PhoWhisper-small@a86b604c346caf7148c37512eafe783a16420adb` qua `config.asr.for_variant("small")`.
- Cả hai snapshot ở `data/model_cache`; medium chiếm khoảng 2,8 GiB trên ổ. Không commit weights. Máy thử nghiệm có 16 GiB RAM và còn khoảng 23 GiB dung lượng ổ sau tải.
- Giải mã CPU; `max_new_tokens=min(224,max(32,ceil(10*clip_seconds)))`. Nếu kết quả lỗi, thử lại một lần với sampling nhiệt độ 0,3, `no_repeat_ngram_size=3`, `repetition_penalty=1.15`. Cấu hình thực của từng attempt được lưu trong `raw_asr_candidates`.
- `AsrQualityCheck` kiểm tra tốc độ từ, lặp từ/cụm/câu, dấu câu lặp, tỷ lệ nén, thiếu/sai/out-of-range timestamp. Ngưỡng trong `configs/default.yaml` là khởi đầu và cần hiệu chỉnh trên VIVOS validation; nguồn bị từ chối không góp transcript chính.
- PhoWhisper không trả word probability trong đường gọi hiện tại; `mean_confidence` và từng `asr_confidence` là `null`, điểm dùng để xếp nguồn là heuristic riêng, không phải xác suất ASR.

## Cùng hai clip đầu vào

| Clip | Mô hình | Kết quả cuối | Số từ | Thời gian CPU quan sát |
| --- | --- | --- | ---: | ---: |
| `Test1/seg_0002/source-1.wav`, 2,42 s | small | `n này dạ không tâm dã.` | 6 | 6,99 s |
| cùng clip | medium | `nó ở đây nè đổ đi giảm.` | 7 | 36,67 s |
| `VIVOSDEV02_R045.wav`, 3,625 s | small | `cô cứ nhè cái nọng cái chê.` | 7 | 7,36 s |
| cùng clip | medium | `cô cứ nhè cái nọng cái chê.` | 7 | 14,88 s |

`Test1` không có transcript chuẩn nên không đo WER/CER. Đầu ra cũ của clip này là 224 từ/2,42 s; sau guard, cả hai mô hình không phát hành chuỗi đó. Medium attempt đầu sinh `dạ....................`; guard từ chối và attempt hai trả kết quả ở bảng. Small attempt đầu trên VIVOS lặp một câu gần ba lần; guard mới từ chối và retry thành kết quả ở bảng. Cả bốn đầu ra cuối có word timestamps trong clip. Thời gian có lần bao gồm khởi tạo model và lần không, nên **không dùng bảng này để kết luận tốc độ tương đối**.

VIVOS có tham chiếu `CÔ CỨ NHÈ NGAY CÁI NỌNG CÁ TRÊ`. Sau chuẩn hóa như code đánh giá hiện có, cả hai kết quả cuối có WER 0,375 và CER 0,2667 **trên đúng một câu**. Cần chạy tập VIVOS test độc lập lớn hơn và chép tay các đoạn họp thực để chọn mô hình theo WER/CER, tỷ lệ từ chối/retry và thời gian/RAM.

## Trạng thái lỗi

- Đoạn VAD giả dương mà ASR trả rỗng ở cả hai attempt giữ `empty`; lỗi model generation ở cả hai attempt là `failed`.
- Text lặp/timestamp phi lý sau hai attempt là `unreliable`, `text=""`, `words=[]`, giữ raw candidate và warning để audit.
- Thiếu checkpoint pinned báo `ModelUnavailableError`, không đổi sang small tự động.

Các ngưỡng và kết quả trên mới là thử nghiệm ban đầu; chưa có số liệu độ chính xác theo người nói hoặc trên vùng nói chồng.
