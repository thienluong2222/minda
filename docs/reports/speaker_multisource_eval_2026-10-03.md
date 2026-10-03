# Đánh giá speaker-only đa nguồn — 03/10/2026

Đây là phép đo bằng ECAPA và pyannote thật trên audio **tổng hợp**, không chạy lại ASR. Ground truth chỉ được đọc sau quyết định để chấm điểm. Bộ VIVOS development `meeting_development_001` và held-out `meeting_test_001` dùng ba người nói khác nhau hoàn toàn, không trùng utterance ID hoặc câu chuẩn. FPT là ca chẩn đoán riêng, không dùng để hiệu chỉnh ngưỡng. Ngưỡng hiện giữ mặc định, `calibration_status=unvalidated`.

## FPT chẩn đoán, cùng aligned audio và turns

| Chế độ không đăng ký | Cụm | Turn ambiguous | Pairwise F1 trên cùng 30 turn có nhãn và có gán cụm ở cả hai bản |
| --- | ---: | ---: | ---: |
| Run gốc (`fa8902eb…`) | 28 | 9 turn chưa có cụm trong tập so sánh | 0,023 |
| P2 sau H1–H3 | 3 | 7/39 turn đơn có nhãn | 1,000 |

Run gốc có 47 turn, 26/28 cụm chỉ chứa một turn. Bản mới tạo 3 nhãn “Người lạ N” ổn định trên 32/39 turn đơn có nhãn; 7 turn yếu giữ `ambiguous`, không sinh người lạ thứ tư. Pairwise F1 chỉ tính trên các turn được gán; không được diễn giải là độ chính xác trên toàn bộ audio. Trong 117 bằng chứng nguồn, run gốc ghi mặc định coverage/purity/status là 1/1/“synchronized”. Bản đánh giá mới có 95 nguồn đủ điều kiện, 22 bị loại; coverage và purity được đo từ cache pyannote, status lấy từ đồng bộ, giá trị thiếu là null có lý do.

## VIVOS mô phỏng, cùng dữ liệu cho P0–P3

Mỗi bộ có 3 nguồn và 3 giọng thật. Bảng dùng đăng ký đầy đủ. `Pairwise F1` loại các turn `ambiguous`, nên xem cùng cột “được chấm”. `Known-ID` lấy mẫu số là toàn bộ turn đơn có nhãn tham chiếu, kể cả ambiguous. Thời gian là speaker stage với embedding cache đã ấm, không gồm VAD/ASR hay khởi động model.

| Bộ / policy | Cụm | Pairwise F1 | Được chấm / có nhãn | Known-ID | Ambiguous | Speaker stage (giây) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development / P0 | 3 | 0,892 | 29/32 | 84,4% | 3 | 0,191 |
| Development / P1 | 2 | 0,913 | 29/32 | 84,4% | 3 | 0,190 |
| Development / P2 | 2 | 0,913 | 29/32 | 84,4% | 3 | 0,192 |
| Development / P3 | 2 | 0,913 | 29/32 | 84,4% | 3 | 0,192 |
| Held-out / P0 | 5 | 0,903 | 24/33 | 69,7% | 12 | 0,171 |
| Held-out / P1 | 3 | 1,000 | 24/33 | 72,7% | 12 | 0,172 |
| Held-out / P2 | 3 | 1,000 | 24/33 | 72,7% | 12 | 0,170 |
| Held-out / P3 | 3 | 1,000 | 24/33 | 72,7% | 12 | 0,167 |

Không đăng ký ai: held-out P2 cho 3 cụm và 12 turn ambiguous; development P2 chỉ cho 2 cụm dù có 3 giọng. Do đó chưa thể khẳng định open-set ổn định trên mọi cuộc họp. Khi chỉ đăng ký một trong ba người, held-out P2 **và P3** đều nhận nhầm 71,4% turn của người chưa đăng ký thành người có hồ sơ, unknown recall bằng 0. Đây là lỗi còn đáng kể. P3 giảm false accept ở FPT và development nhưng **không cải thiện held-out**; runtime tiếp tục mặc định P2, không đổi sang P3 theo kỳ vọng của plan.

## Ablation chất lượng nguồn trên held-out

Với P2, bỏ lần lượt SNR proxy, duration, clipping, dropout hoặc purity khỏi phép tính/gate thí nghiệm đều cho 3 cụm, pairwise F1 1,000 trên 24/33 turn được chấm và known-ID 72,7%. Bộ smoke này không chứng minh quality gate làm tăng accuracy. Coverage/sync vẫn giữ như điều kiện an toàn, không ablate. Các unit test chứng minh nguồn lỗi đồng bộ, zero-padding, không hỗ trợ speech, nói nhiều người và trường hợp mọi nguồn bị loại đều có trọng số 0; đó là kiểm thử tính đúng của gate, không phải chứng cứ cải thiện accuracy.

## Tái lập và giới hạn

Chạy `scripts/prepare_speaker_only_run.py` trên `data/generated/smoke/meeting_development_001` và `meeting_test_001`, sau đó chạy `scripts/evaluate_speaker_multisource.py` với `--reference`, `--profiles none|partial|full` và `--ablation none|snr|duration|clipping|dropout|purity`. FPT dùng run `fa8902eb…` cùng `--enrollment-dir data/generated/fpt_tts_pilot_20261003/pcm_16k/enrollment`. JSON đầu ra và cache embedding ở `data/evaluations/` (ignored). Mỗi JSON lưu hash audio, encoder revision, split, số nguồn, ngưỡng, cache hit/miss và thời gian speaker stage.

Chưa tính DER/JER hoặc hiệu năng theo khoảng cách gần/xa vì phép đo hiện gắn nhãn theo overlap turn, không có mapping frame-level đã thẩm định. Không dùng báo cáo A0–A7 mock cũ để suy ra tốc độ hay chất lượng end-to-end.

Ca tích hợp cuối chạy thật trên ba clip FPT 3 giây tại `data/meetings/speaker-h4-smoke-final/runs/08b74549-36e0-40dd-9d78-d969ca1830bb`. Manifest ghi đúng P2, `speaker_q_v3`, ngưỡng cụm 0,40 và VAD `pyannote_shared`; timeline có trọng số speaker và coverage/purity/status theo từng nguồn. Đây chỉ là smoke test tích hợp, không dùng để chấm chất lượng.
