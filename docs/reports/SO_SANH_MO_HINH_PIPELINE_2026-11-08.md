**Đối chiếu mô hình, chỉ số và cơ sở lựa chọn trong pipeline — 08/11/2026**

Tài liệu tổng hợp mã nguồn, cấu hình và kết quả đã lưu; không chạy lại suy luận mô hình. Nguồn chính là benchmark ngày 04/11/2026, chuyển đổi WeSpeaker ngày 05/11/2026 và thí nghiệm biên bản ngày 08/11/2026. Các kết luận dưới đây chỉ áp dụng trong phạm vi dữ liệu và cách đo tương ứng.

**1. Cấu hình đang dùng và phạm vi so sánh**

Luồng âm thanh mặc định: audio đa thiết bị → đồng bộ → Pyannote shared segmentation/VAD → lượt người nói → WeSpeaker và gom cụm/khớp hồ sơ → PhoWhisper-medium trên từng nguồn → dung hợp transcript. Luồng tài liệu có OCR khi cần; luồng biên bản dùng Qwen3-4B 4-bit, embedding multilingual-e5-small và nhánh FCM/evidence graph.

WeSpeaker đã thay ECAPA trong cấu hình hiện tại. Tài liệu cũ còn nhắc ECAPA/PhoWhisper-small không phản ánh đầy đủ mặc định mới. SepFormer có trong cấu hình nhưng nhánh xử lý overlap hiện được bỏ qua; không được trình bày như một bước đang giúp tăng chất lượng transcript ứng dụng.

| Thành phần | Mô hình/thuật toán hiện tại | Các đối chứng đã có kết quả | Chỉ số được đo |
|---|---|---|---|
| Phát hiện tiếng nói — VAD | Pyannote segmentation-3.0 dùng chung đầu ra với phân đoạn người nói | Silero VAD; SpeechBrain CRDNN-LibriParty; FunASR FSMN-VAD. Ba DiariZen cũng có phép đo VAD bổ sung | Frame precision, recall, F1, miss rate, false alarm rate; RTF, load time, peak RSS trong runtime |
| Phát hiện nói chồng và số người nói cục bộ | Pyannote segmentation-3.0 | DiariZen WavLM base-s80-md, large-s80-md, large-s80-md-v2 | Overlap precision, recall, F1, miss rate, false alarm rate; count MAE; runtime |
| Biểu diễn giọng nói | WeSpeaker ResNet34-LM, 256 chiều | MFCC-120; ECAPA-TDNN, 192 chiều; X-vector TDNN, 512 chiều; WavLM Base Plus SV, 512 chiều | Closed-set accuracy; open-set accuracy; macro-F1; known accuracy; unknown rejection; FAR; FRR; EER; ROC-AUC; CI, thời gian, RTF, peak RSS |
| Bộ phân lớp người nói | Cosine prototype | Cosine KNN; Linear SVM; Logistic Regression | Cùng bộ chỉ số nhận diện/open-set; thử enrollment K=1,3,5 trên mỗi encoder |
| Gom cụm người nói | Constrained AHC; ngưỡng hiện tại 0,50 | AHC ngưỡng cũ 0,40; AHC hiệu chuẩn; Spectral; DBSCAN; HDBSCAN, trên cả 5 encoder | ARI, NMI, B³-F1; speaker confusion rate với oracle turns; speaker count error; thời gian |
| Chép lời — ASR | PhoWhisper-medium; có lựa chọn small | PhoWhisper-small; PhoWhisper-large; Whisper-large-v3-turbo; wav2vec2-base-vietnamese-250h | WER, CER, S/D/I; first-decode WER; clean-control WER; noisy–clean delta; failure rate; RTF; peak RSS; CI và paired delta CI |
| Dung hợp transcript | Web mặc định F5_RULE_WEIGHTED_CORRECTED | F0_FIXED; F1_BEST_SEGMENT; F3_ROVER; F4_ASR_WEIGHTED; F5_RULE_WEIGHTED; F6_LEARNED | WER, CER, S/D/I trên giả thuyết dựng; WER trên diagnostic 3 cuộc họp chạy core thật |
| Embedding và gom chủ đề | multilingual-e5-small + FCM | multilingual-e5-base; paraphrase-multilingual-MiniLM-L12-v2; BGE-M3. Mỗi encoder đi với FCM, K-means, Agglomerative và HDBSCAN | ARI, NMI, collapse rate; silhouette và thời gian từng tài liệu; oracle-K=4 ARI diagnostic; thời gian embedding và peak RSS |
| Truy xuất bằng chứng | BM25 | TF-IDF; E5 dense; Hybrid RRF | Hit@2, Recall@2, MRR |
| OCR | Tesseract vie+eng, tessdata_fast | tessdata_best; EasyOCR Latin G2; VietOCR vgg_transformer; VietOCR vgg_seq2seq; Paddle Latin PP-OCRv5 mobile recognition | CER, raw CER, WER; exact match; failure rate; blank hallucinations; load/inference time; peak RSS; kiểm tra khả năng xuất chữ tiếng Việt |
| Tách hai giọng | SepFormer-WHAMR có sẵn, nhánh ứng dụng chưa bật | SepFormer-WHAM; SepFormer-Libri2Mix; ConvTasNet WHAM sepclean | SI-SDR, SI-SDR improvement, negative improvement rate; RTF, load time, peak RSS |
| Sinh biên bản | Qwen3-4B-Instruct-2507 4-bit qua MLX | Sáu biến thể A–F của pipeline trên cùng Qwen; bộ công cụ riêng để đối chiếu base/adapter/checkpoint | ID coverage; token-F1 với bản tham chiếu; word ratio; độ dài/số đoạn; lặp câu; số mới ngoài nguồn; fallback/retry; thời gian/token. Công cụ checkpoint đo JSON/schema, EOS và token budget |

K=1,3,5 trong thí nghiệm speaker là **số mẫu đăng ký cho mỗi người**, khác tham số số láng giềng của KNN. FCM, AHC, BM25 và các phương pháp fusion là thuật toán; MFCC là đặc trưng thủ công. Không nên gọi toàn bộ các thành phần này là mô hình học sâu.

**2. Ý nghĩa và cách đọc chỉ số**

Ký hiệu ↑: lớn hơn thường tốt hơn; ↓: nhỏ hơn thường tốt hơn. Một số chỉ số chỉ để mô tả/chẩn đoán, không có quy tắc tối ưu một chiều.

| Chỉ số | Ý nghĩa và cách diễn giải |
|---|---|
| WER ↓ | `(S + D + I) / N`: số phép thay, xóa, chèn token cần để khớp transcript chuẩn, chia số token chuẩn. 0 là khớp hoàn toàn; có thể vượt 100% nếu chèn nhiều. Trong benchmark tiếng Việt này, token theo khoảng trắng gần với âm tiết hơn là từ đã phân đoạn ngôn ngữ học |
| CER ↓ | Tỷ lệ phép sửa ở cấp ký tự. Hữu ích với lỗi dấu/chữ tiếng Việt; vẫn cần đọc lỗi cụ thể để biết có làm sai nghĩa hay không |
| S / D / I ↓ | Substitution: thay sai; deletion: bỏ mất; insertion: thêm thừa. Cho biết WER tăng do nhận sai, mất lời hay sinh thừa |
| First-decode WER ↓ | WER của ứng viên giải mã đầu tiên, trước các lần thử/guard tiếp theo. So với WER đầu ra cuối để phát hiện tác động của adapter/decoding, không chỉ của checkpoint |
| Paired clean WER; noisy–clean delta ↓ | Chép cùng lời nói ở bản sạch và bản mô phỏng suy giảm. Delta bằng WER mô phỏng trừ WER sạch; phản ánh độ suy giảm do điều kiện âm học |
| Frame precision ↑ | `TP/(TP+FP)`: trong các frame báo có tiếng nói/overlap, bao nhiêu frame đúng |
| Frame recall ↑ | `TP/(TP+FN)`: phát hiện được bao nhiêu tiếng nói/overlap thực sự có |
| F1 ↑ | `2PR/(P+R)`: cân bằng precision và recall. Frame F1 của VAD khác macro-F1 nhận diện người nói |
| Miss rate ↓ | `FN/(TP+FN)`: tỷ lệ frame dương tính bị bỏ sót |
| False alarm rate của VAD/overlap ↓ | Trong mã benchmark: `FP/(FP+TN)`, tức tỷ lệ frame âm tính bị báo nhầm. Không nhầm với `1 - precision` |
| Count MAE ↓ | Trung bình sai lệch tuyệt đối số người nói đồng thời từng frame; benchmark giới hạn số đếm tham chiếu/dự đoán ở tối đa 2 |
| Closed-set accuracy ↑ | Độ chính xác nhận diện trên truy vấn của người đã đăng ký khi buộc chọn trong danh sách; chưa kiểm tra khả năng từ chối người lạ |
| Open-set accuracy ↑ | Độ chính xác trên toàn bộ người đã đăng ký và người lạ, sau khi áp dụng ngưỡng từ chối |
| Macro-F1 ↑ | Tính F1 cho từng lớp rồi lấy trung bình để lớp nhiều mẫu không lấn át. Trong suite speaker mới, gồm 5 danh tính tương đối trong episode và 1 lớp unknown |
| Known accuracy ↑ | Tỷ lệ truy vấn của người đã đăng ký được gán đúng tên sau cơ chế từ chối |
| Unknown rejection ↑ | Tỷ lệ truy vấn người chưa đăng ký được giữ unknown đúng |
| FAR ↓ | Tỷ lệ truy vấn người lạ bị gán vào một danh tính đã đăng ký; với phép đo này bằng `1 - unknown rejection` |
| FRR ↓ | Tỷ lệ truy vấn người đã đăng ký bị từ chối thành unknown; không gồm trường hợp bị gán nhầm sang người đã đăng ký khác |
| EER ↓ | Điểm lỗi xác minh tại nơi false acceptance và false rejection gần bằng nhau khi quét ngưỡng. Mã lấy điểm ROC gần giao nhau nhất. Đây là diagnostic hậu nghiệm; ngưỡng này không được dùng để hiệu chuẩn lại ứng dụng trên test |
| ROC-AUC ↑ | Khả năng xếp điểm cặp cùng người cao hơn cặp khác người khi quét ngưỡng; 1 là phân biệt hoàn hảo, khoảng 0,5 gần ngẫu nhiên |
| ARI ↑ | Mức đồng thuận giữa cụm dự đoán và nhãn chuẩn sau hiệu chỉnh cơ hội ngẫu nhiên; 1 là trùng hoàn toàn, gần 0 là mức ngẫu nhiên, có thể âm |
| NMI ↑ | Thông tin chung chuẩn hóa giữa phân cụm và nhãn chuẩn, từ 0 đến 1. NMI không hiệu chỉnh cơ hội như ARI |
| B³-F1 ↑ | Đánh giá precision/recall của nhóm chứa từng mẫu rồi tổng hợp; giúp thấy việc gộp nhiều người vào một cụm hoặc tách một người thành nhiều cụm |
| Speaker confusion rate với oracle turns ↓ | Sau khi ghép nhãn cụm với danh tính chuẩn tối ưu, tỷ lệ lượt bị gán sai người. Đo trên ranh giới lượt đã biết; không phải DER toàn pipeline |
| Speaker count error ↓ | `abs(số cụm dự đoán - số người chuẩn)`, sau đó lấy trung bình qua cuộc họp |
| Collapse rate ↓ | Tỷ lệ tài liệu có nhiều chủ đề chuẩn nhưng bị thuật toán gom về một cụm |
| Silhouette ↑, dùng chẩn đoán | Độ gần với cụm đang thuộc so với cụm khác, trong khoảng -1 đến 1. Đo hình học embedding; không tự chứng minh đúng chủ đề |
| Oracle-K=4 ARI diagnostic | ARI của K-means khi được cung cấp số chủ đề thật là 4. Dùng tách vấn đề biểu diễn khỏi chọn số cụm; không phải một phương pháp tự động công bằng để triển khai |
| Hit@2 ↑ | Tỷ lệ truy vấn có ít nhất một đoạn liên quan trong 2 kết quả đầu |
| Recall@2 ↑ | Tỷ lệ tất cả đoạn liên quan của truy vấn được tìm thấy trong 2 kết quả đầu. Hit@2=100% vẫn có thể bỏ sót nhiều đoạn liên quan |
| MRR ↑ | Trung bình nghịch đảo hạng của đoạn liên quan đầu tiên; hạng 1 đạt 1, hạng 2 đạt 0,5 |
| Exact match ↑ | Tỷ lệ dòng OCR khớp hoàn toàn sau chuẩn hóa |
| Raw CER ↓ | CER trước chuẩn hóa; cho thấy cả khác biệt về cách viết/định dạng mà CER chuẩn hóa có thể bỏ qua |
| Blank hallucinations ↓ | Số mẫu ảnh trắng mà OCR vẫn sinh chữ; là số lượng mẫu, không phải phần trăm lỗi toàn tài liệu |
| Vietnamese charset eligibility | Checkpoint có thể xuất đủ chữ và dấu tiếng Việt hay không. Đây là điều kiện hợp lệ của đối chứng OCR, không phải điểm chất lượng |
| SI-SDR ↑ | Tỷ số tín hiệu nguồn đích so với méo/nhiễu còn lại, sau khi bỏ ảnh hưởng của một hệ số biên độ toàn cục; đơn vị dB |
| SI-SDR improvement ↑ | SI-SDR sau tách trừ SI-SDR của bản trộn đầu vào, trên cùng nguồn chuẩn; >0 là cải thiện theo phép đo đó |
| Negative improvement rate ↓ | Tỷ lệ hỗn hợp có SI-SDR improvement <0, tức tách làm tệ hơn bản trộn theo chỉ số này |
| DER ↓ | Lỗi diarization theo thời lượng: bỏ sót tiếng nói + báo nhầm tiếng nói + nhầm người, chia tổng thời lượng người nói tham chiếu. Diagnostic core lưu cả tính và bỏ overlap |
| JER ↓ | Lỗi Jaccard theo người nói sau ghép nhãn; xem độ giao/hợp giữa vùng thời gian chuẩn và dự đoán của từng người |
| ID/claim coverage ↑ | Tỷ lệ ID nguồn/claim cần giữ có mặt trong đầu ra/ledger. Kiểm tra truy vết và độ phủ cấu trúc; không xác nhận câu viết đúng nghĩa |
| Authored-reference token-F1 ↑, dùng tham khảo | `2 * số token trùng theo đa tập / (số token đầu ra + số token tham chiếu)`. Đo trùng từ với bản biên soạn, không kiểm tra quan hệ chủ thể, phủ định, điều kiện hay đúng fact |
| Body word ratio; số/độ dài đoạn | Tỷ lệ số token đầu ra/nguồn và các thống kê đoạn văn để mô tả mức nén/độ dài; không mặc định càng ngắn càng tốt |
| Duplicate sentence rate ↓ | Tỷ lệ câu lặp chính xác sau chuẩn hóa trong đầu ra; không bao quát lặp ý bằng câu khác |
| Numeric values outside source ↓ | Số giá trị số xuất hiện ngoài nguồn, sau chuẩn hóa giá trị. Không có số mới vẫn có thể viết sai người, sai trạng thái hay sai quan hệ |
| Source fallback rate; retry count | Tỷ lệ phải dùng lại nội dung nguồn và số lần thử viết lại do kiểm tra từ chối. Chẩn đoán khả năng viết lại và độ nghiêm của guard; không phải điểm đúng nghĩa độc lập |
| JSON/schema pass ↑ | Đầu ra phân tích được và tuân thủ cấu trúc bắt buộc. Không đồng nghĩa nội dung chính xác |
| EOS complete ↑; budget hits ↓ | Sinh đến token kết thúc hay bị hết giới hạn token. Không nên chấm nội dung bị cắt cụt như một đầu ra hoàn chỉnh |
| Failure rate ↓ | Tỷ lệ mẫu không có trạng thái thành công theo quy ước từng tác vụ. Một kết quả thành công kỹ thuật vẫn có thể sai nội dung |
| RTF ↓ | Thời gian xử lý / thời lượng audio. RTF=0,5 nghĩa là 10 giây audio mất khoảng 5 giây; RTF<1 nhanh hơn thời lượng thực |
| Load time; inference time; peak RSS ↓ | Thời gian nạp, thời gian suy luận và đỉnh bộ nhớ tiến trình. Peak RSS không nhất thiết bằng toàn bộ bộ nhớ GPU/MLX hay RAM toàn hệ thống |
| CI 95%; paired delta CI | Khoảng bất định bootstrap. ASR/speaker được lấy mẫu lại theo người nói nguồn thực tế để tránh coi các episode lặp là người độc lập. Với delta giữa hai mô hình, khoảng chứa 0 chưa xác lập chiều khác biệt trên mẫu này |

WER/CER được tính bằng khoảng cách chỉnh sửa theo [JiWER](https://jitsi.github.io/jiwer/). Cách hiểu ARI/NMI theo [tài liệu ARI](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html) và [tài liệu NMI của scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.normalized_mutual_info_score.html). SI-SDR theo [Le Roux và cộng sự, 2019](https://arxiv.org/abs/1811.02508). Công thức cụ thể trong bảng được đối chiếu thêm với mã benchmark của dự án.

**3. Kết quả ASR và cơ sở giữ PhoWhisper-medium**

Cùng 30 clip lượt nói không overlap từ audio VIVOS mô phỏng, 13 người nói nguồn, 294 token tham chiếu; mỗi clip có bản sạch đối ứng. Dùng nhóm kết quả `simulated_only`, MPS float16 trên Apple M4 16 GB. Bảng ghi đầu ra cuối của adapter, không chỉ lần giải mã đầu.

| Mô hình | WER ↓ | CER ↓ | RTF ↓ | Peak RSS tiến trình, GB thập phân ↓ |
|---|---:|---:|---:|---:|
| PhoWhisper-small | 31,97% | 21,97% | 1,13 | 2,04 |
| PhoWhisper-medium | 16,67% | 12,66% | 2,81 | 5,22 |
| PhoWhisper-large | 8,50% | 5,33% | 4,23 | 10,08 |
| Whisper-large-v3-turbo | 24,15% | 17,28% | 1,30 | 5,36 |
| wav2vec2-base-vietnamese-250h | 23,47% | 10,75% | 0,084 | 1,33 |

Có thể giải thích medium là lựa chọn cân bằng theo WER, tốc độ và tài nguyên: large có WER quan sát thấp hơn nhưng chậm và tốn bộ nhớ tiến trình hơn; small nhẹ hơn nhưng lỗi cao hơn. wav2vec2 rất nhanh và có CER thấp hơn medium, vì vậy không được viết medium tốt hơn trên mọi chỉ số.

Tất cả paired CI 95% của delta WER giữa các ứng viên và medium đều chứa 0; mẫu còn nhỏ nên chưa xác lập khác biệt. First-decode WER của medium là 11,90%, thấp hơn WER đầu ra cuối 16,67%: một phần lỗi nằm ở chuỗi decoding/retry/guard, cần tách khỏi năng lực checkpoint. Đây là diễn giải từ số đo, không phải bằng chứng medium tối ưu cho mọi cuộc họp thực.

**4. Kết quả speaker và cơ sở chọn WeSpeaker**

So sánh giữ cùng cosine prototype, enrollment K=3 và phép hiệu chuẩn trên validation. Macro-F1 sau cơ chế open-set:

| Encoder | Easy ↑ | Moderate ↑ | Stress ↑ |
|---|---:|---:|---:|
| MFCC-120 | 0,2938 | 0,1821 | 0,1162 |
| ECAPA-TDNN | 0,9098 | 0,8683 | 0,6518 |
| X-vector TDNN | 0,7226 | 0,6882 | 0,3077 |
| WeSpeaker ResNet34-LM | 0,9462 | 0,9347 | 0,7961 |
| WavLM Base Plus SV | 0,5943 | 0,5343 | 0,3630 |

WeSpeaker có macro-F1 quan sát cao nhất trong phép so sánh cố định này ở cả ba mức. Ở moderate, known accuracy khoảng 98,00%, unknown rejection 86,67%; ECAPA tương ứng 92,00% và 79,87%. WeSpeaker vẫn có FAR khoảng 13,33% ở moderate, nên không nên chỉ báo closed-set accuracy gần 100% rồi kết luận nhận diện hoàn hảo.

Đây là cơ sở thực nghiệm phù hợp cho việc thay ECAPA bằng WeSpeaker. Việc chuyển encoder và hồ sơ đã được thực hiện ngày 05/11. Không suy ra rằng cosine prototype là bộ phân lớp tốt nhất chỉ từ bảng này; kết luận về classifier phải xét toàn bộ ma trận 5 encoder × 4 classifier × 3 mức enrollment.

Gom cụm là bài toán riêng: với WeSpeaker, ARI oracle-turn của AHC ngưỡng 0,40 là 0,6346; hiệu chuẩn ngưỡng 0,50 tăng lên 0,8244; HDBSCAN đạt 0,8749. Vì vậy có bằng chứng hữu ích cho hiệu chuẩn AHC, nhưng chưa có bằng chứng AHC tốt nhất. Các số này dùng ranh giới lượt chuẩn, không phải DER end-to-end.

**5. VAD và overlap**

VAD F1 của các đối chứng chính: Silero 0,9407; Pyannote3 0,9392; CRDNN 0,9351; FSMN 0,9314. Chênh lệch điểm quan sát nhỏ; không đủ để lập luận chọn Pyannote vì F1 cao nhất.

Lý do kiến trúc có căn cứ trong mã là dùng cùng đầu ra Pyannote cho VAD, thông tin người nói cục bộ và overlap, đồng thời tái sử dụng cache. Đó là lý do tích hợp; chưa phải chứng minh tăng tốc bằng phép đo model thật nếu chỉ dựa vào benchmark mock cũ.

Overlap F1 theo nhãn phạm vi phát ngôn: Pyannote3 0,2807; DiariZen base 0,2519; DiariZen large 0,1484; DiariZen v2 0,0436. Nhãn phạm vi phát ngôn có cả im lặng bên trong; chẩn đoán bằng năng lượng nguồn khô làm thay đổi thứ hạng. Cần trình bày kết quả gắn với cách tạo nhãn, không khẳng định Pyannote vượt trội trên overlap thực.

**6. Embedding, FCM và truy xuất**

Benchmark thực hiện 4 encoder × 4 clusterer, không chỉ E5-small với FCM. Tập test có 30 tài liệu chủ đề được biên soạn theo template giữ riêng.

| Encoder | ARI với FCM ↑ | ARI với K-means ↑ |
|---|---:|---:|
| multilingual-e5-small | 0,3968 | 0,4983 |
| multilingual-e5-base | 0,4970 | 0,5067 |
| multilingual MiniLM-L12-v2 | 0,6177 | 0,7121 |
| BGE-M3 | 0,4061 | 0,5549 |

FCM chưa vượt K-means trên dữ liệu này. Điểm mạnh về thiết kế của FCM là membership mềm: một đơn vị nội dung có thể liên quan nhiều chủ đề; biến thể E/F tận dụng thông tin này trong graph. Đây là mục đích thiết kế, chưa chứng minh tạo biên bản tốt hơn. E5-small+FCM không nên được mô tả là tổ hợp có ARI cao nhất.

BM25, TF-IDF, E5 dense và Hybrid RRF đều có Hit@2=1,00 và MRR=1,00 trên 120 truy vấn. Recall@2 lần lượt 0,5000; 0,5000; 0,5000; 0,4979. Tập truy vấn hiện chưa phân biệt mạnh các phương pháp; BM25 có thể được giải thích bằng tính đơn giản và truy vết từ khóa, chưa thể khẳng định chất lượng vượt dense/hybrid.

**7. OCR và tách giọng**

OCR dùng cùng 30 chuỗi test được render thành dòng ảnh ở 3 điều kiện, thêm 3 mẫu trắng; tổng 93 mẫu cho mỗi mô hình. Đây là recognition trên crop dòng, không đánh giá đầy đủ bố cục trang, bảng, thứ tự đọc hoặc scan thật.

| OCR | CER chuẩn hóa, tất cả mẫu ↓ | Ghi chú |
|---|---:|---|
| Tesseract fast | 5,39% | Đối chứng ứng dụng hiện tại |
| Tesseract best | 5,03% | Có kết quả riêng về thời gian và exact match |
| EasyOCR Latin G2 | 6,28% | Có phép thử sinh chữ trên mẫu trắng |
| VietOCR vgg_transformer | 4,39% | CER quan sát thấp nhất trong nhóm đủ bảng chữ |
| VietOCR vgg_seq2seq | 5,08% | Đối chứng kiến trúc decoder khác |
| Paddle Latin PP-OCRv5 mobile rec | 54,45% | Checkpoint thiếu khả năng xuất đầy đủ chữ tiếng Việt; loại khỏi xếp hạng OCR đủ điều kiện |

Không có cơ sở gọi Tesseract chính xác nhất từ bảng này. Tích hợp OCR trang/tài liệu và chất lượng nhận dạng từng dòng cần được đánh giá riêng. Nhận xét về bảng chữ chỉ áp dụng checkpoint Paddle đã thử, không áp dụng toàn bộ hệ sinh thái PaddleOCR.

Tách giọng dùng 20 hỗn hợp tiếng Việt mô phỏng hai người, 8 kHz, ghép hoán vị đầu ra tối ưu và nguồn chuẩn là source image có vang:

| Mô hình | SI-SDR improvement, dB ↑ | Tỷ lệ cải thiện âm ↓ |
|---|---:|---:|
| SepFormer-WHAMR | -4,64 | 100% |
| SepFormer-WHAM | -3,60 | 85% |
| SepFormer-Libri2Mix | +4,99 | 20% |
| ConvTasNet WHAM sepclean | -1,43 | 85% |

Kết quả này không ủng hộ việc chọn WHAMR vì chất lượng tách cao nhất. Cần xét cả độ phù hợp nguồn đích khô/có vang và WER sau tách. Nhánh ứng dụng đang bỏ qua tách/ASR/identity trong overlap, nên số đo tách chưa chứng minh cải thiện hệ thống đang chạy.

**8. Dung hợp transcript**

| Phương pháp | Vai trò đối chứng |
|---|---|
| F0_FIXED | Dùng nguồn cố định |
| F1_BEST_SEGMENT | Chọn một nguồn cho từng đoạn theo chất lượng |
| F3_ROVER | Căn chỉnh và biểu quyết từ giữa các nguồn |
| F4_ASR_WEIGHTED | Biểu quyết có trọng số theo tín hiệu độ tin cậy ASR |
| F5_RULE_WEIGHTED | Trọng số theo quy tắc/chất lượng nguồn |
| F5_RULE_WEIGHTED_CORRECTED | Phiên bản F5 có hiệu chỉnh |
| F6_LEARNED | StandardScaler + Logistic Regression trên đặc trưng ứng viên |

Suite ngày 04/11 có 7 phương pháp trên; không có kết quả F2 oracle trong bảng tổng hợp này dù mã nền có khái niệm oracle.

Trên giả thuyết transcript dựng bằng lỗi có kịch bản, WER F0=19,34%, F5 corrected=21,04%, F6=21,12%. Diagnostic dùng giả thuyết ASR từ 3 cuộc họp core thật cho WER F0=22,03%; các phương pháp còn lại khoảng 26,27%. Đây là bằng chứng chưa cho thấy fusion vượt nguồn cố định trong tập đang có.

F5 corrected có thể được mô tả là lựa chọn tích hợp hiện tại, dùng chất lượng nguồn và lưu provenance. Không nên mô tả là đã thắng benchmark. F6 của benchmark được fit trên lỗi dựng ở development; trọng số đó không tự được nạp vào web. Web thiếu artifact F6 thì fallback về F5_RULE_WEIGHTED.

**9. Qwen và thí nghiệm biên bản**

Mô hình chạy là `mlx-community/Qwen3-4B-Instruct-2507-4bit`. Bộ ngày 08/11 so sánh cách tổ chức pipeline trên cùng mô hình:

| Biến thể | Thành phần được so sánh |
|---|---|
| A | Luồng FCM cũ, viết theo các đơn vị nguồn |
| B | Luồng viết narrative có chủ đề, bỏ phần trích xuất/quan hệ graph dùng để lập kế hoạch |
| C | Evidence graph, không dùng FCM |
| D | FCM + graph, gán chủ đề cứng |
| E | FCM + graph, dùng membership mềm |
| F | E + quy tắc phong cách học từ các sửa đổi; trong thí nghiệm dùng dữ liệu train làm surrogate |

Có 48 đầu ra thực tế từ 8 đoạn transcript biên soạn thuộc 7 họ tình huống. Tập đã dùng để sửa lỗi kỹ thuật, không còn là test giữ kín cho kết luận tổng quát hóa. 84 ca source-contract là kiểm tra cấu trúc; không phải 84 ca đánh giá nội dung LLM độc lập. Hai bản reference/ASR của pilot là hai đầu vào của cùng một cuộc họp mô phỏng TTS.

ID coverage tối thiểu bằng 1 cho cả sáu biến thể, nhưng vẫn có fallback và lỗi văn phong. Token-F1 với bản biên soạn của A khoảng 0,7449, F khoảng 0,6880; không thể dùng riêng token-F1 để chọn phương pháp viết biên bản tốt nhất. Chưa có đánh giá độc lập của người làm biên bản xác lập F tốt nhất. Thời gian có chia sẻ cache nên không dùng xếp hạng tốc độ suy luận độc lập.

Một bộ notebook ngày 26/10 được chuẩn bị để so base Qwen, adapter v1 và ứng viên exported step 6/checkpoint 12/checkpoint 18 trên 6 old-validation + 12 new-development. Chỉ số kỹ thuật: JSON/schema pass, EOS complete, budget hit, token sinh và thời gian. `reports/validation.json` của gói này ghi `actual_cuda_model_evaluation_executed=false`; chưa phải bằng chứng các checkpoint đã chạy đủ hoặc checkpoint nào tốt hơn. Cần phân biệt công cụ đã được kiểm cú pháp/điều phối với kết quả suy luận thực.

Chưa thấy kết quả so sánh Qwen với họ Llama/Gemma/Mistral trong các bộ vừa đối chiếu. Vì vậy có thể giải thích Qwen 4-bit bằng khả năng vận hành cục bộ và mức tài nguyên đã quan sát, nhưng chưa có bằng chứng trong dự án để gọi là LLM tốt nhất cho biên bản tiếng Việt.

**10. Điều kiện thí nghiệm và mức kết luận dùng cho luận văn**

Benchmark thành phần có 3 cuộc họp development, 9 validation, 30 test; điều kiện easy/moderate/stress dùng RT60 0,12/0,30/0,55 giây, SNR 25/15/5 dB và 1/2/4 mic. Âm thanh là phát ngôn tự nhiên VIVOS đặt trong phòng mô phỏng, không phải hội thoại tự phát; tiếng nói đồng thời tối đa 2 người. Speaker và nguồn enrollment/query được tách trong thiết kế thí nghiệm; không xác nhận được toàn bộ dữ liệu huấn luyện ban đầu của checkpoint công khai.

Classifier và các siêu tham số được chọn ở development/validation; không cập nhật trọng số neural trong bộ comparative ngày 04/11. Việc fit Logistic Regression, chọn threshold hoặc hệ số FCM khác với fine-tune encoder/ASR/LLM.

Diagnostic end-to-end có kết quả baseline ECAPA, calibrated ECAPA và WeSpeaker trên 3 cuộc họp mô phỏng, lưu WER/CER/DER/JER. Không nên coi các kết quả này là nghiệm thu chất lượng hội thoại thật. Module đồng bộ có offset MAE/median/p95 tính bằng ms và drift MAE tính bằng ppm, nhưng không có bảng đối chiếu checkpoint đồng bộ trong bộ comparative này.

Cách diễn đạt có thể dùng trong báo cáo:

> Mô hình được lựa chọn dựa trên vai trò trong hệ thống, kết quả đánh giá trên dữ liệu tiếng Việt và chi phí thực thi. WeSpeaker cho macro-F1 cao hơn ECAPA trong phép so sánh open-set cố định trên ba điều kiện mô phỏng. PhoWhisper-medium được giữ như một phương án cân bằng giữa lỗi chép lời và tài nguyên, dù PhoWhisper-large có WER quan sát thấp hơn. Với FCM, OCR, fusion, tách giọng và LLM, kết quả hiện có được dùng để nêu ưu điểm, hạn chế và hướng cải tiến; chưa xác lập toàn bộ cấu hình hiện tại là tối ưu cho cuộc họp thực.

**11. Xác nhận đã chạy và dữ liệu cụ thể của từng phép so sánh**

Đã đối chiếu bổ sung `execution_audit.json`, các file predictions và manifest. Các phép so sánh thành phần dưới đây đã có kết quả thực tế; phần ngoại lệ là công cụ so checkpoint Qwen và việc so Qwen với các họ LLM khác. “Đã chạy” không có nghĩa toàn bộ dữ liệu là cuộc họp thực, hoặc toàn bộ mô hình được bật trong ứng dụng.

| Phép so sánh | Trạng thái đã kiểm tra | Đầu vào thực tế và nguồn nhãn |
|---|---|---|
| 5 ASR | Đủ 18 dự đoán validation và 60 dự đoán test/mô hình | Validation: 9 clip mô phỏng + 9 bản sạch; test: 30 clip không overlap + 30 bản sạch đối ứng, 13 người nói và 294 token chuẩn ở mỗi nhóm test. Audio gốc và transcript người gán nhãn từ VIVOS |
| VAD/overlap | Đã chạy 7 cấu hình hoạt động; 4 có đầu ra đếm người/overlap | 30 đoạn cuộc họp test mô phỏng từ VIVOS, 9 validation cho hiệu chuẩn. Nhãn hoạt động/overlap theo thời điểm đặt phát ngôn vào bản mô phỏng, chưa phải nhãn frame do người nghe đánh dấu |
| 5 encoder × 4 classifier × enrollment K=1,3,5 | Có 180 hàng tổng hợp trên 3 điều kiện mô phỏng, thêm 120 hàng clean-reference trên 2 corpus | Nhánh mô phỏng: 325 phát ngôn VIVOS gốc × 3 điều kiện = 975 clip query và 616 clip enrollment sạch, trên các phần dữ liệu của 65 người. Test dùng 19 người. Nhánh clean-reference còn dùng VIVOS và VoxVietnam |
| Đối chiếu speaker trên VoxVietnam | Đã có kết quả đủ 5 encoder × 4 classifier × 3 mức enrollment | Subset 31 người, 155 clip support + 155 clip query. Có 30 episode/mức enrollment; mỗi episode lấy 5 người đã đăng ký, 5 người lạ và 50 query. Episode lặp không phải cuộc họp độc lập |
| Gom cụm người nói | Đã chạy 5 encoder × 5 cấu hình thuật toán | 9 ca validation và 30 ca test dựng từ embedding speaker VIVOS đã mô phỏng suy giảm; mỗi ca 3 người × 3 đoạn. Có nhãn người và ranh giới đoạn trước, khác với 30 bản audio cuộc họp của suite VAD |
| 7 fusion | Đã chạy; cần phân biệt hai loại bằng chứng | Chính: 120 lượt test thuộc 30 cuộc họp VIVOS, tạo lỗi transcript theo kịch bản để dựng giả thuyết. Bổ sung: 3 cuộc họp mô phỏng chạy core thật để lấy giả thuyết ASR |
| 4 encoder văn bản × 4 clusterer | Đã chạy 16 tổ hợp | 42 tài liệu chủ đề tự dựng: 3 development, 9 validation, 30 test; 16 đơn vị/tài liệu. Bốn nhãn: kinh phí, hạ tầng, nhân sự và tiến độ. Không phải transcript ASR của 42 bản ghi âm |
| 4 retrieval | Đã chạy | Dùng cùng tập văn bản chủ đề; test có 120 truy vấn, tức 4 truy vấn × 30 tài liệu. Nhãn liên quan theo chủ đề, không phải nhãn xác nhận fact |
| 6 OCR | Mỗi mô hình có 93 dự đoán test | 30 chuỗi gồm 24 câu VIVOS và 6 câu hành chính/biểu quyết tự dựng, render ở 3 mức suy giảm thành 90 ảnh; thêm 3 ảnh trắng. Có 30 ảnh validation riêng. Không phải 93 trang scan thật |
| 4 separator | Đã chạy | 20 hỗn hợp hai người test và 6 validation từ audio VIVOS mô phỏng; nguồn đích chuẩn là các source image có vang, 8 kHz |
| Qwen, biến thể A–F | Đã chạy, đủ 48 đầu ra | 8 đoạn transcript biên soạn từ `data/test.jsonl` của gói llm-next-round-v2, thuộc 7 họ tình huống. 84 ca test đầy đủ chỉ được kiểm tra source-contract; không phải 84 ca suy luận Qwen |
| Pilot biên bản reference/ASR | Đã chạy | Một cuộc họp mô phỏng bằng FPT TTS ngày 03/10; hai phiên bản transcript reference và ASR, không phải hai cuộc họp độc lập |
| Qwen base/adapter/checkpoint 6/12/18 | Chưa xác nhận hoàn thành suy luận trong gói kết quả đang có | Công cụ chuẩn bị để chạy 6 old-validation + 12 new-development; bản kiểm tra công cụ ghi `actual_cuda_model_evaluation_executed=false` |
| Qwen với Llama/Gemma/Mistral | Chưa có kết quả trong các bộ được đối chiếu | Chưa có tập dự đoán/metric tương ứng để lập bảng xếp hạng |

VIVOS được lưu tại `data/external/vivos/extracted/vivos/`; manifest `data/manifests/vivos.jsonl` có **12.420 phát ngôn, 65 người, khoảng 15,67 giờ**. Phân chia nội bộ: development 32 người/8.097 phát ngôn; validation 14 người/3.563 phát ngôn; test 19 người/760 phát ngôn. Các benchmark chỉ lấy tập con tương ứng, không chạy toàn bộ 12.420 phát ngôn cho mỗi phép đo.

Bộ audio cuộc họp mô phỏng có 42 bản: 3 development, 9 validation, 30 test. Riêng 30 bản test dài khoảng 12,22–19,98 giây/bản, tổng 485,60 giây, tức khoảng 8,09 phút theo timeline chuẩn, chưa nhân số mic. Vì vậy phải gọi là các ca mô phỏng ngắn; không được mô tả như 30 cuộc họp thực dài hàng chục phút.

LibriWASN có trong nguồn dữ liệu dự án nhưng không phải đầu vào cho các điểm comparative ngày 04/11 được nêu ở đây. Các bản ghi họp cá nhân phục vụ demo/kiểm tra chức năng cũng không phải nguồn của các điểm trong bảng tổng hợp này. Chất lượng trên cuộc họp thực vẫn cần một bộ riêng có transcript, nhãn người nói và biên bản do người kiểm chứng.

Manifest truy vết trực tiếp:

- [VIVOS gốc và các phần dữ liệu](</Users/thien/Documents/School/Luận văn/data/manifests/vivos.jsonl>).
- [VoxVietnam subset](</Users/thien/Documents/School/Luận văn/data/external/voxvietnam/subset-index.json>).
- [42 audio cuộc họp mô phỏng](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/simulation/manifest.json>).
- [Clip ASR](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/asr/manifest.json>), [speaker sạch](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/speaker/manifests.json>) và [speaker mô phỏng](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/speaker_synthetic/manifests.json>).
- [Dữ liệu chủ đề/truy xuất](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/text/manifest.json>), [ảnh OCR](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/ocr/manifest.json>) và [hỗn hợp tách giọng](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/separation/manifest.json>).
- [Transcript biên soạn cho LLM](</Users/thien/Documents/School/Luận văn/web_app/artifacts/llm-next-round-v2-20261026/data/test.jsonl>) và [audit thực thi benchmark](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/execution_audit.json>).

**Nguồn nội bộ để kiểm tra và trích số**

- [Cấu hình âm thanh hiện tại](</Users/thien/Documents/School/Luận văn/web_app/configs/default.yaml>) và [cấu hình Qwen/E5](</Users/thien/Documents/School/Luận văn/web_app/configs/minutes.yaml>).
- [Tổng hợp comparative benchmark 04/11](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/summary.json>) và [bảng CSV](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/summary.csv>).
- [Paired comparisons](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/paired_comparisons.json>), [xác minh EER/AUC](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/speaker_verification.json>) và [reference sensitivity](</Users/thien/Documents/School/Luận văn/reports/comparative_benchmark/20261104/reference_diagnostics.json>).
- [Chuyển WeSpeaker 05/11](</Users/thien/Documents/School/Luận văn/reports/wespeaker_migration/20261105/summary.json>) và [tình trạng F6](</Users/thien/Documents/School/Luận văn/reports/wespeaker_migration/20261105/F6_status.json>).
- [Tổng hợp biên bản 08/11](</Users/thien/Documents/School/Luận văn/reports/minutes_graph/20261108/summary.json>), [protocol A–F](</Users/thien/Documents/School/Luận văn/reports/minutes_graph/20261108/ablations_v5/protocol.json>) và [phân tích bản cuối](</Users/thien/Documents/School/Luận văn/reports/minutes_graph/20261108/ablations_v5/analysis.json>).
- [Trạng thái kiểm tra công cụ checkpoint](</Users/thien/Documents/School/Luận văn/web_app/artifacts/llm-checkpoint-comparison-20261026/reports/validation.json>).
- [Mã benchmark ASR](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/asr.py>), [speaker](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/speaker.py>), [VAD/overlap](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/segmentation.py>), [clustering/fusion](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/algorithms.py>), [text/retrieval](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/text.py>), [OCR](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/ocr.py>) và [separation](</Users/thien/Documents/School/Luận văn/experiments/comparative_benchmark/separation.py>).
