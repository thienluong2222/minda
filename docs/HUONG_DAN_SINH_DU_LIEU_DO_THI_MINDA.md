# Sinh dữ liệu tổng hợp để huấn luyện LLM xây đồ thị Minda

**Đích của bộ dữ liệu** là giúp Qwen trích đúng sự kiện, gắn đúng người, hạn và điều kiện, rồi nối đúng các sự kiện có quan hệ. Một kịch bản đã đạt cần kiểm được cả đáp án của từng bước lẫn trạng thái cuối của vấn đề, chẳng hạn hạn nào đang có hiệu lực và đoạn lời nào xác nhận hạn đó.

Sinh **kịch bản có đáp án trước**, sau đó hiện thực hóa thành lời chép tiếng Việt. Đối chiếu đáp án với chính lời chép đã sinh trước khi xuất JSONL. Dùng ma trận tình huống để chọn lô tiếp theo dựa trên số ca đã đạt. Quy trình sinh rồi lọc mẫu tương tự nguyên tắc của Self-Instruct. Thiết kế dưới đây dùng hợp đồng và các phép kiểm của Minda. [Self-Instruct](https://aclanthology.org/2023.acl-long.754/)

## Giao việc cho Antigravity

Mở repo Minda trong Antigravity. Giao file này cho agent và dùng yêu cầu sau để chạy vòng đầu.

```text
Thực hiện vòng thí điểm theo hướng dẫn sinh dữ liệu đồ thị Minda này.
Đọc các hợp đồng đồ thị, trích sự kiện, nối sự kiện và bộ kiểm của repo.
Chỉ ghi dữ liệu, công cụ và báo cáo của vòng thử vào artifacts/graph-synthetic-v1/.

Tạo ma trận 24 họ kịch bản gốc, chia tập theo họ trước khi sinh biến thể.
Sinh lời chép tiếng Việt giả lập từ kịch bản có đáp án. Chạy các bước
kiểm bằng mã và đối chiếu qua lượt chấm chỉ đọc lời chép. Xuất hai nhóm
JSONL cho trích sự kiện và nối sự kiện theo đúng prompt của runtime.

Hoàn tất vòng thử bằng báo cáo số mẫu đạt, ca bị loại, độ phủ còn thiếu
và lỗi mà runtime chưa biểu diễn được. Lưu kết quả theo case_id để có
thể tiếp tục từng lô. Vòng thử kết thúc ở bộ dữ liệu đã kiểm.
```

Đường dẫn trong prompt tính từ gốc repo `web_app`. Dùng lời chép và nhân vật giả lập. Các file mã và fixture tổng hợp đủ để agent đọc hợp đồng. Khi dùng Gemini để sinh dữ liệu cho Qwen, đối chiếu điều khoản của đúng dịch vụ và tài khoản. Gemini API/AI Studio có điều khoản giới hạn phát triển mô hình cạnh tranh. Antigravity có điều khoản riêng theo cách truy cập. [Antigravity Projects](https://antigravity.google/docs/projects?app=antigravity), [Điều khoản Antigravity](https://antigravity.google/terms), [Điều khoản Gemini API](https://aistudio.google.com/docs/terms#use-restrictions)

## 1. Hợp đồng cần khớp với Minda

| Bước | Đầu vào thực tế | Đích huấn luyện |
| --- | --- | --- |
| Trích sự kiện | `units`, `context`. Mỗi hàng có `unit_id`, `speaker`, `session_id`, `text`. | `items`. Cấu hình hiện tại bật dạng gọn `[unit_id, kind]` hoặc `[unit_id, kind, {...}]`. Một đơn vị chứa nhiều ý có thể có nhiều hàng với các đoạn `text` khác nhau. |
| Nối sự kiện | `events`, `context`. Mỗi hàng có `id`, `text`, `kind`, `session`. | `relations`. Mỗi cạnh có `source`, `target`, `kind`, `source_quote`, `target_quote` và `field` khi sửa thuộc tính. |
| Kiểm đồ thị kết quả | Sự kiện và cạnh đã trích được đưa qua bộ dựng và bộ kiểm đồ thị. | Đáp án chấm gồm cạnh có hiệu lực, lịch sử cập nhật, giá trị hiện hành và đoạn nguồn của giá trị đó. |

Lấy chuỗi `system`, cách chia lô và cách đổi ID từ repo. `u0` và `c0` là alias cục bộ của từng yêu cầu. Khi bước nối nhận sự kiện đã trích, nó dùng trường `session`, còn bước trích nhận `session_id`. Giữ đáp án kịch bản, mã họ, trạng thái kỳ vọng và lời giải trong dữ liệu chấm. Nội dung `user` của mẫu SFT chỉ gồm payload mà bước đó thực sự thấy. [Cấu hình](../configs/minutes.yaml), [Bộ trích](../src/meeting_pipeline/minutes/graph_builder.py#L33), [Bộ nối](../src/meeting_pipeline/minutes/graph_relations.py#L13)

- **Trích sự kiện.** Mỗi `unit_id` trong `units` cần xuất hiện ít nhất một lần. Khi tách nhiều ý, các đoạn trích phải bao phủ nội dung chữ và số của đơn vị, kể cả phủ định và điều kiện. `context` dùng để hiểu và dẫn căn cứ. Trong dạng gọn, lược các trường trống. `text` có thể lược khi sự kiện dùng nguyên đơn vị. `issue` là tên ngắn của vấn đề.
- **Nối sự kiện.** `source` thuộc lô `events` hiện tại. `target` đứng trước nguồn, xuất hiện trong đầu vào và cùng phiên. Hai câu trích khớp với `text` ở hai đầu và truy được về lời chép gốc. Dùng `{"relations":[]}` cho lô thật sự thiếu cạnh có căn cứ trong phạm vi nhìn thấy.
- **Cạnh cập nhật.** Với `amends`, `field` là `owner`, `deadline`, `condition` hoặc `document_version`. Giá trị mới được trích ở sự kiện cập nhật. Khi muốn mô phỏng một câu có nhiều chuyển trạng thái, ghi lại trường hợp bộ hậu xử lý hiện tại không thể xác nhận chúng trong phép chấm tương thích runtime.
- **Các phần do mã dựng.** Lấy ID lưu trữ, vị trí ký tự, cạnh kỹ thuật như `contains` và `evidenced_by`, cùng giá trị hiệu lực từ bộ dựng đồ thị. Đích SFT của hai bước dùng đúng trường mà prompt tương ứng yêu cầu. [Hợp đồng ontology](../src/meeting_pipeline/minutes/graph_contracts.py#L11), [Gắn căn cứ](../src/meeting_pipeline/minutes/graph_evidence.py#L49), [Cập nhật trạng thái](../src/meeting_pipeline/minutes/graph_state.py#L47)

### Quy tắc phân biệt nhãn

| Trường hợp | Đáp án phải thể hiện |
| --- | --- |
| Một người kể “Buổi họp tuần trước đã chốt phương án A” | Đây là thông tin được thuật lại trong buổi đang xét. Giữ dấu hiệu về buổi họp trước. |
| “Tôi đề nghị dùng A”, “Tôi đồng ý với A”, “Cuộc họp quyết định dùng A” | Lần lượt là đề xuất, đồng ý cá nhân và quyết định tập thể có căn cứ. Cạnh `accepts` cần chỉ được đúng ý đã thông qua. |
| “Xin mọi người biểu quyết” và lời công bố kết quả | Hành động mời và kết quả là hai sự kiện khác nhau. Giá trị phiếu chỉ lấy từ nguồn công bố. |
| “Mai giao Lan gửi hồ sơ” | Người nói, người giao và người nhận có thể là các vai khác nhau. `owner` của việc gửi là Lan, với căn cứ đúng mệnh đề. |
| “Tôi nhận gửi hồ sơ” từ lượt lời có người nói đã xác định | Có thể gắn người nhận theo tín hiệu tự nhận việc và metadata hợp lệ. Nếu danh tính người nói mơ hồ, giữ người phụ trách chưa xác định. |
| “Đề nghị lùi sang 17/6” và “Chốt lùi từ 15/6 sang 17/6” | Ý thứ nhất giữ hạn đang có nếu chưa có lời xác nhận. Ý thứ hai có thể sửa trường hạn khi xác định đúng nhiệm vụ đích. |
| “Gửi trước 17/6 nếu pháp chế duyệt” | Gắn đúng điều kiện cho việc tương ứng. Giữ các từ chỉ giới hạn như “trước” và “chậm nhất” khi chúng là một phần của giá trị trích. |
| “Sẽ gửi”, “được giao gửi” và “đã gửi” | Nội dung sự kiện thể hiện đúng mức cam kết và tình trạng hành động. Khi chấm, kiểm lỗi nâng việc dự kiến hoặc được giao thành đã hoàn thành. |
| Cùng chủ đề, trùng ngày hoặc trùng tên | Chỉ gắn cạnh khi lời nói chỉ ra đúng việc và quan hệ. Dùng các ca có hai đích nhìn giống nhau để kiểm chọn đích. |
| Nguồn nói rõ rằng “chưa chốt ngày” | Giữ thông tin chưa chốt và để trống hạn. Ghi riêng trường hợp ASR làm mất chữ khiến trạng thái không thể đọc được. |

Dùng `EventKind` trong mã làm danh sách nhãn sự kiện chuẩn. Dùng tám loại liên kết diễn ngôn mà prompt nối hỗ trợ, gồm `refers_to`, `supports`, `opposes`, `amends`, `withdraws`, `supersedes`, `accepts` và `depends_on`. Chỉ gán `filler` cho lời đệm hoặc lời chào thuần túy. [Danh sách loại sự kiện](../src/meeting_pipeline/minutes/graph_contracts.py#L11), [Danh sách cạnh cho LLM](../src/meeting_pipeline/minutes/graph_relations.py#L13)

## 2. Ma trận tình huống

Vòng thử đề xuất có **24 họ kịch bản gốc** với bốn họ cho mỗi dạng dưới đây. Mỗi họ có thể sinh thêm biến thể sau khi ca gốc vượt qua kiểm tra. Số này dùng để thử quy trình và xem các nhóm nào còn thiếu trước khi mở rộng.

| Dạng | Các ca cần có |
| --- | --- |
| **Một người trình bày** | Báo cáo tiến độ, thuyết minh phương án hoặc trình bày kết quả của mình. Có đoạn chỉ cung cấp thông tin, có đoạn đề xuất trong phần trình bày và có đoạn thuật lại kết luận từ buổi khác. |
| **Một người trình bày rồi hỏi đáp** | Hỏi làm rõ số liệu, trả lời ở lượt sau, đính chính chi tiết, câu hỏi bị ngắt hoặc còn bỏ ngỏ. |
| **Nhiều người thảo luận** | Hai đề xuất cạnh tranh, phản đối, ủng hộ, đồng ý cá nhân và nhiều ý xen kẽ. Có cuộc họp dừng ở thảo luận và có cuộc họp đi đến kết luận. |
| **Ra quyết định hoặc biểu quyết** | Mời biểu quyết, công bố số phiếu, chốt có điều kiện, hoãn, rút đề xuất, thay phương án hoặc xác nhận đúng phiên bản tài liệu. |
| **Giao việc và theo dõi** | Nhiều người và nhiều hạn trong cùng lượt, giao việc ở lượt sau, đổi người, đổi một hạn, điều kiện phụ thuộc và báo cáo việc đã hoàn thành. |
| **Họp hỗn hợp hoặc nhiều phiên** | Trình bày chuyển sang thảo luận, đổi chủ đề rồi quay lại, hai việc trùng ngày, một thay đổi xuất hiện sau nhiều lượt xen giữa hoặc một phiên nhắc lại nội dung của phiên khác. |

Phối từng dạng với nhiều bối cảnh như hoạt động lớp học, nhóm kỹ thuật, hội đồng, vận hành hoặc phối hợp liên phòng. Thay đổi cách xưng hô, mức trang trọng, độ dài lượt nói, số người tham gia thực tế và vị trí của bằng chứng trong cuộc họp. Đan xen câu dài, câu cụt, lời đệm và nhắc lại tự nhiên. Dùng thêm vài ca khai mạc, kết thúc và chuyển mục để mô hình gặp đủ lời thủ tục.

Trong mỗi lô, tạo các **cặp ca gần giống nhau** nhưng có đáp án khác ở đúng một điểm. Ví dụ cùng hai người và hai ngày, đổi đúng người nhận việc ở một ca. Ví dụ khác đặt cạnh việc đề nghị dời hạn và việc đã chốt dời hạn. Gắn tag cho các ca thiếu căn cứ, nhiều đích khả dĩ, quan hệ xa và lời nói có điều kiện. Chọn lô kế tiếp dựa trên số ca **đã đạt** của từng tag.

Sinh bản sạch trước. Trên một phần ca, tạo biến thể nhiễu có kiểm soát như mất từ, sai chữ số, nhầm nhãn người nói hoặc ranh giới câu. Ghi loại nhiễu và liên kết tới ca gốc. Chạy lại bộ tách và tính lại nhãn từ văn bản biến thể. Ví dụ nếu mất chữ “chưa”, dùng phần còn đọc được để đánh giá lại trạng thái. Đáp án của bản sạch không tự động trở thành đáp án của bản nhiễu.

## 3. Hồ sơ của một ca

Lưu một bản ghi nội bộ cho mỗi ca và biến thể. Đây là định dạng quản lý dữ liệu sinh. Mẫu JSONL cho Qwen được tạo từ bản ghi này theo hai hợp đồng ở trên.

| Nhóm | Trường cần lưu |
| --- | --- |
| Nguồn và phiên bản | `case_id`, `family_id`, `variant_of`, `split`, `meeting_mode`, `domain`, `tags`, `source_type: synthetic`, model sinh, phiên bản prompt và phiên bản/hàm dựng nhãn. |
| Lời chép | Danh sách lượt lời có `turn_id`, người nói, phiên, mốc thời gian mô phỏng và nguyên văn. Lưu bản lời chép thực sự dùng, kể cả bản nhiễu hoặc bản đã hiệu chỉnh. |
| Đáp án sự kiện | Một khóa sự kiện nội bộ, loại, trích nguyên văn, ID lượt/đơn vị, nhãn vấn đề ngắn, giá trị và căn cứ cho từng thuộc tính. Ghi rõ lý do khi một thuộc tính thiếu hoặc mơ hồ. |
| Đáp án cạnh | Khóa nguồn và đích, loại, thuộc tính sửa nếu có, trích nguyên văn hai đầu, trạng thái nhìn thấy đích trong ngữ cảnh. |
| Đáp án trạng thái | Theo từng sự kiện hoặc vấn đề, lưu giá trị gốc, giá trị hiệu lực, sự kiện xác nhận thay đổi và đoạn nguồn. Dùng để so với kết quả dựng đồ thị. |
| Kiểm tra | Kết quả kiểm bằng mã, bất đồng của lượt chấm, quyết định sửa hoặc loại, lý do và số lần thử. |

Khi chuyển lời chép sang `IndexedTurn`, dùng `asr_status="transcribed"` cho lượt mô phỏng đã có văn bản và truyền ánh xạ `metadata.turn_sessions` cho `make_graph_units`. Bộ tách chỉ nhận lượt có nội dung với trạng thái `transcribed` hoặc `user_edited`. Dữ liệu giả lập có thể dùng `tokens=[]`, `clip_path=None` và `confidence=None`. Mốc giây là mốc mô phỏng theo lượt nói. [Kiểu lượt lời](../src/meeting_pipeline/minutes/evidence_retrieval.py#L26), [Bộ tách đơn vị](../src/meeting_pipeline/minutes/graph_inputs.py#L39)

Có hai hệ tọa độ ký tự. `SourceSpan` dùng vị trí trong lượt lời. `EvidenceAnchor` dùng vị trí trong `GraphUnit.original`. Tính khoảng nửa mở `[start_char, end_char)` bằng Python trên đúng chuỗi được lưu. Khi văn bản đã qua hiệu chỉnh, kiểm riêng đoạn trích có thật trong payload và căn cứ còn truy được trong bản gốc. Nếu một cụm lặp ở nhiều chỗ, cần căn cứ đủ cụ thể để xác định đúng vị trí và mệnh đề. [SourceSpan và EvidenceAnchor](../src/meeting_pipeline/minutes/graph_contracts.py#L92)

## 4. Sinh và kiểm theo từng lô

### Lượt A — Dựng kịch bản có đáp án

Giao cho mô hình tổ hợp của ma trận, danh sách nhân vật hư cấu và các lỗi cần kiểm. Yêu cầu định trước ai thực sự phát biểu, sự kiện nào xảy ra, yếu tố nào còn bỏ ngỏ, và khi nào một thuộc tính thay đổi. Mỗi thay đổi cần có sự kiện cũ, sự kiện mới, trường thay đổi và dấu hiệu trong lời nói đủ để quy chiếu. Với cặp đối chứng, viết đáp án rõ ràng cho từng ca trước khi sinh lời thoại.

```text
Tạo kịch bản có cấu trúc cho tổ hợp đã giao. Ghi thứ tự phát biểu, người
nói, ý sự kiện, người được giao nếu có, giá trị thuộc tính, quan hệ với
ý trước và trạng thái cuối. Với mỗi dữ kiện quan trọng, ghi dấu hiệu
cần xuất hiện trong lời chép. Dùng tên và tình huống giả lập.
```

### Lượt B — Viết lời chép

Đưa kịch bản vào một lượt sinh riêng. Yêu cầu mô hình viết như đang nói trong cuộc họp và đặt dấu hiệu rõ ràng ở chỗ quan trọng. Cho phép ý phụ và câu đệm để lời thoại tự nhiên. Ngày, số, người nhận việc, kết luận, phủ định và điều kiện phải theo kịch bản. Sau khi sinh, cố định bản lời chép của ca trước khi chạy các phép kiểm.

```text
Viết lời chép cuộc họp tiếng Việt từ kịch bản. Mỗi lượt có turn_id,
người nói, phiên, mốc mô phỏng và lời nói. Có thể đổi cách diễn đạt
cho tự nhiên. Giữ đúng vai trò người nói, người nhận việc, thời hạn,
điều kiện và mức độ xác nhận đã nêu. Giữ các việc bỏ ngỏ ở trạng thái
bỏ ngỏ. Trả riêng danh sách lượt lời.
```

### Lượt C — Ánh xạ và đối chiếu

1. Chạy `make_graph_units` trên lời chép đã cố định. Dựng payload theo cách chia lô của runtime, kể cả cửa sổ ngữ cảnh và alias. Ưu tiên gọi đường chạy của repo với session kiểm thử để bắt chính payload phát ra. Nếu lượt thử dùng cách lấy ngữ cảnh khác production, ghi rõ trong báo cáo và xác nhận lại trên cửa sổ production trước khi dùng số đo end-to-end.
2. Ánh xạ đáp án sự kiện vào các đơn vị đã sinh. Xác thực bằng parser và các phép kiểm hiện có. Đoạn trích thuộc tính và hai đầu cạnh phải khớp đúng sự kiện. Nếu nguồn đích có nhiều ý cùng `unit_id`, dùng khóa sự kiện và trích đoạn để phân biệt.
3. Chạy **lượt chấm mù theo nguồn** trong ngữ cảnh mới. Chỉ cung cấp lời chép, các trường người nói và phiên mà runtime thấy, cùng quy tắc ontology. Với lượt chấm ở cấp lô, cung cấp đúng cửa sổ của lô. So với đáp án kịch bản ở bước sau. Nếu dùng cùng model cho cả hai lượt, ghi đây là đối chiếu tự động bằng cùng model.
4. Khi có bất đồng về dữ kiện quan trọng, hệ thống tìm đoạn căn cứ và phân loại lỗi. Nếu lời chép bỏ mất chứng cứ hoặc làm sai kịch bản, sinh lại lượt liên quan và chạy lại kiểm tra. Nếu lời chép nhất quán mà nhãn dự kiến sai, chỉ cập nhật nhãn khi có căn cứ rõ và vẫn giữ được loại ca cần sinh. Ca còn mơ hồ sau số lần thử đã cấu hình được lưu riêng kèm lý do.

```text
Chỉ đọc lời chép và ngữ cảnh được đưa. Trích các sự kiện và quan hệ
theo ontology Minda. Mỗi trường quan trọng cần có đoạn trích đủ
chứng minh người, việc, hạn và trạng thái tương ứng. Ghi rõ chỗ
chưa đủ căn cứ hoặc có nhiều cách quy chiếu. Dùng các ID xuất hiện
trong đầu vào.
```

### Lượt D — Xuất và thử lại với mã hiện tại

Xuất mỗi dòng JSONL dưới dạng `messages` gồm `system`, `user`, `assistant`. Lấy `system` từ prompt thật của bước đó, tuần tự hóa payload của `user` thành chuỗi JSON và tuần tự hóa đáp án của `assistant` thành chuỗi JSON. Chạy kiểm thử nạp lại từng dòng và đưa đầu ra mẫu qua parser thật. Khi nối cạnh, thử trước với sự kiện chuẩn để đo riêng bộ nối. Chạy thêm toàn pipeline để đo lỗi từ sự kiện tự trích truyền sang cạnh và trạng thái.

Một cạnh thật ở cấp cuộc họp có thể có đích ngoài cửa sổ. Ghi ca này như lỗi thiếu ngữ cảnh để chấm end-to-end. Giữ riêng nhóm thật sự không có quan hệ trong cửa sổ. Như vậy khi nhìn thấy `relations: []`, báo cáo vẫn phân biệt được hai nguyên nhân.

## 5. Ví dụ một ca dùng làm fixture

Hai lượt cùng phiên, theo thứ tự. Sau khi tách, giả sử hai đơn vị tương ứng có alias `u0` và `u1` trong lô.

> `u0` Giao Lan gửi dự thảo trước 15/6 nếu pháp chế duyệt.
>
> `u1` Chốt đổi hạn gửi dự thảo từ 15/6 sang trước 17/6.

Đầu ra của bước trích ở chế độ gọn.

```json
{
  "items": [
    ["u0", "task", {
      "issue": "gửi dự thảo",
      "owner": "Lan",
      "deadline": "trước 15/6",
      "condition": "nếu pháp chế duyệt"
    }],
    ["u1", "amendment", {
      "issue": "gửi dự thảo",
      "deadline": "trước 17/6"
    }]
  ]
}
```

Đầu ra của bước nối, với `c0` là sự kiện giao việc và `c1` là sự kiện chốt đổi hạn trong payload của bước này.

```json
{
  "relations": [
    {
      "source": "c1",
      "target": "c0",
      "kind": "amends",
      "field": "deadline",
      "source_quote": "Chốt đổi hạn gửi dự thảo từ 15/6 sang trước 17/6.",
      "target_quote": "Giao Lan gửi dự thảo trước 15/6 nếu pháp chế duyệt."
    }
  ]
}
```

Đáp án chấm sau khi dựng đồ thị gồm người phụ trách **Lan**, hạn ban đầu **trước 15/6**, hạn hiện hành **trước 17/6** và điều kiện **nếu pháp chế duyệt**. Căn cứ của hạn hiện hành đến từ `u1`. Căn cứ của người phụ trách, hạn ban đầu và điều kiện đến từ `u0`. Ca đối chứng có thể thay câu chốt bằng “Tôi đề nghị đổi hạn gửi dự thảo từ 15/6 sang trước 17/6.” Khi đó nhãn lượt sau là `proposal` và hạn hiện hành vẫn đọc theo lượt giao việc. [Fixture đổi hạn trong repo](../tests/unit/test_minutes_graph.py#L382)

## 6. Tiêu chí đưa mẫu vào tập huấn luyện

| Phép kiểm | Điều kiện đạt |
| --- | --- |
| JSON và hợp đồng | Từng dòng đọc được, đúng prompt và schema của bước tương ứng. ID và alias có trong payload, đúng vai trò. Khoảng ngữ cảnh và thứ tự đáp ứng runtime. |
| Căn cứ | Trích đoạn xuất hiện trong đúng đơn vị hoặc sự kiện. Khoảng ký tự tính lại khớp văn bản. Nhãn loại, người, hành động, hạn và điều kiện được đoạn nguồn hỗ trợ. |
| Phủ nội dung | Các đơn vị hiện tại có nhãn. Khi tách ý, phần chữ và số đều có trong các đoạn trích. Câu nói chưa rõ được ghi trong nhãn rà soát. |
| Quan hệ | Hai đầu hợp lệ, cùng phiên và đích đứng trước nguồn trong phạm vi bộ nối. Kiểm đúng loại và trường bị tác động. Một cạnh thay đổi trạng thái cần vượt bước kiểm bằng mã của Minda. |
| Trạng thái | So giá trị gốc, giá trị hiệu lực và căn cứ hiện hành với đáp án theo kịch bản đã đối chiếu lời chép. Đếm riêng ca đổi nhầm người hoặc ngày, đoán điều kiện, nâng đề xuất thành kết luận và nâng việc được giao thành đã làm. |
| Tách tập | `family_id` xuất hiện trong đúng một tập. Các biến thể cùng tình huống, đổi tên, nhiễu hoặc viết lại cùng cấu trúc được kiểm trùng và giữ cùng họ. |

Mẫu được xuất cho SFT cần vượt tất cả phép kiểm liên quan. Nếu một sự kiện hoặc cạnh hợp nghĩa nhưng bị từ chối do giới hạn hiện tại của mã, lưu riêng với nguyên nhân để đánh giá cải tiến hệ thống. Ghi số ca lỗi theo loại. Một lô bị loại nhiều vì đề tài khó cần được bổ sung lại, tránh để việc lọc làm biến mất các tình huống khó.

Ở vòng thí điểm, có thể chọn hai họ train, một họ dev và một họ test cho mỗi dạng cuộc họp, rồi cố định danh sách ID trước khi sinh biến thể. Dùng dev để sửa prompt và cách lọc. Sau khi ổn định, tạo thêm bộ test với họ kịch bản mới để đo mức tổng quát trên dữ liệu giả lập. Gói dữ liệu viết biên bản trước đây có thể cung cấp vài kịch bản tham chiếu và căn cứ dạng `unit_ids`. Các nhãn nút và cạnh vẫn cần đi qua quy trình đối chiếu ở đây. [Kế hoạch huấn luyện hiện có](PLAN_HUAN_LUYEN_LLM_BIEN_BAN_2026-11-17.md)

## 7. Đầu ra bàn giao và cách đọc báo cáo

Đề xuất cây thư mục cho agent khi thực hiện vòng sinh dữ liệu.

```text
artifacts/graph-synthetic-v1/
  scenarios.jsonl
  cases.jsonl
  split_manifest.json
  train/extract.jsonl
  train/relations.jsonl
  dev/extract.jsonl
  dev/relations.jsonl
  test/extract.jsonl
  test/relations.jsonl
  export_index.jsonl
  rejected.jsonl
  validation_report.md
```

Mỗi ca có khóa ổn định. Tiếp tục lô từ các ca chưa hoàn tất và tránh xuất trùng khi chạy lại. Lưu trong manifest phiên bản ontology, prompt, nguồn model, cấu hình cửa sổ, split và nguồn gốc biến thể. Trong `export_index.jsonl`, ghi đường dẫn tệp, số dòng, `case_id` và ID lô cho từng mẫu JSONL đã xuất. Chỉ mục này giúp truy ngược một dòng train về lời chép và quyết định lọc.

Báo cáo vòng đầu cần có số **họ kịch bản, cuộc họp, biến thể và mẫu JSONL** của từng tập. Liệt kê độ phủ theo dạng họp, loại sự kiện, cạnh, ca `relations: []`, ca thiếu ngữ cảnh và ca trạng thái chưa đủ căn cứ. Nêu số lỗi nghiêm trọng đã chặn, số mẫu bị loại và lý do theo nhóm. Tách số đo khớp cấu trúc khỏi số đo đúng ngữ nghĩa do lượt chấm xác định.

Khi đánh giá adapter, so với Qwen nền trên cùng đầu vào đã cố định. Đo đúng loại sự kiện, đúng thuộc tính và đoạn nguồn, đúng cặp nguồn–đích–loại cạnh–trường sửa, cùng trạng thái cuối của vấn đề. Báo riêng lỗi nguồn đích ngoài ngữ cảnh và lỗi chọn sai khi đích nằm trong ngữ cảnh. Bộ thử giả lập cho biết mô hình làm được gì trên các tình huống đã kiểm soát. Kết luận về cuộc họp thật cần một phép đo riêng.
