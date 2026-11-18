# Minda — nghiên cứu giao diện toàn hệ thống và sản phẩm tham chiếu

Ngày: **06/11/2026**, Asia/Ho_Chi_Minh. Phạm vi: nghiên cứu, danh mục trang, luồng và tiêu chí hoàn thiện. Chưa thay mã ứng dụng hoặc cài dependency trong lượt này.

## 1. Định hướng

Thiết kế Minda thành một sản phẩm có ba lớp nối liền: **giới thiệu/hướng dẫn → không gian làm việc của người lập biên bản → vận hành/quản trị**. Trong mỗi lớp, người dùng biết đang ở đâu, làm gì tiếp theo, nội dung nào đã lưu và cách phục hồi nếu xử lý thất bại.

Đề xuất phối hợp tham chiếu:

- **Notta**: workspace đọc, sửa lời chép và nghe đối chiếu.
- **Fireflies**: thư viện cuộc họp, bộ lọc và điều hướng từ ghi chú về thời điểm nguồn.
- **MeetGeek/Fellow**: cấu trúc mẫu, chương trình họp và nội dung theo đề mục.
- **Granola**: vùng đọc/viết gọn, hạn chế điều khiển không liên quan.
- **Shadcn Admin**: khung user/admin, bảng, thiết lập và trạng thái dùng chung.
- **Meetily/Scriberr**: tham khảo sản phẩm local/self-hosted có mã nguồn.

Đây là đánh giá phù hợp cho Minda, không phải kết luận rằng một sản phẩm bên ngoài đáp ứng sẵn biên bản tiếng Việt nhiều nguồn hoặc thể thức Word của dự án. Bản tóm tắt họp, bản chép lời và biên bản chính thức là các đầu ra cần được trình bày đúng mục đích.

## 2. Website tương tự, nên xem phần nào

| Sản phẩm | Trang công khai và điểm xem | Áp dụng cho Minda |
| --- | --- | --- |
| **Notta** | [Website](https://www.notta.ai/en), [bố cục trang bản ghi có ảnh](https://support.notta.ai/hc/en-us/articles/37437047511195-Records-detail-page-screen-layout-and-functions-Notta-Web), [sửa transcript](https://support.notta.ai/hc/en-us/articles/15551607178395-Edit-transcripts), [xuất file](https://support.notta.ai/hc/en-us/articles/15289070397851-Download-transcription-file) | Phân biệt vùng lời chép, player, ghi chú và thanh thao tác; cho sửa, nghe, tìm và xuất từ cùng workspace. |
| **Fireflies** | [Website](https://fireflies.ai/), [thư viện cuộc họp có ảnh](https://guide.fireflies.ai/articles/4827382971-learn-about-fireflies-notebook), [ghi chú theo thời điểm](https://guide.fireflies.ai/articles/9547055509-fireflies-ai-meeting-summaries) | Danh sách cuộc họp có bộ lọc, thao tác nhanh; chọn ghi chú để tới phát biểu liên quan. |
| **MeetGeek** | [Website](https://meetgeek.ai/), [hướng dẫn mẫu](https://support.meetgeek.ai/en/articles/6021910-meeting-templates-quickstart-guide) | Thư viện mẫu phân nhóm; chọn mẫu, xem nội dung và preview trước khi dùng. Mẫu tóm tắt của MeetGeek không đồng nhất với mẫu DOCX có anchor của Minda. |
| **Otter** | [Website](https://otter.ai/), [tổ chức theo channel](https://help.otter.ai/hc/en-us/articles/360049379794-Channels-Overview), [quyền chia sẻ](https://help.otter.ai/hc/en-us/articles/360048338793-Share-a-conversation) | Tham khảo tìm lại cuộc họp và sự rõ ràng của quyền. Team/channel/chia sẻ là mở rộng có backend riêng, chưa tự đưa vào phạm vi lõi. |
| **Fellow** | [Website](https://fellow.ai/), [mẫu ghi chú/chương trình họp](https://help.fellow.ai/en/articles/2423913-meeting-note-templates) | Gắn đề mục, chương trình họp và việc tiếp theo với nội dung cuộc họp; phân biệt cấu trúc trước họp và nội dung được xác nhận sau họp. |
| **tl;dv** | [Website và minh họa sản phẩm](https://tldv.io/) | Tham khảo cách tiếp cận ghi chú và tri thức từ nhiều cuộc họp; CRM và tự động hóa chỉ là hướng tương lai nếu có nhu cầu. |
| **Granola** | [Website và ví dụ ghi chú](https://www.granola.ai/) | Vùng nội dung là trung tâm; cấu trúc đoạn và đề mục dễ đọc. Không mặc định đưa tính năng lịch/chat của nguồn vào Minda. |
| **Meetily** | [Website có demo tương tác](https://meetily.ai/), [GitHub](https://github.com/Zackriya-Solutions/meetily) | Gần hướng xử lý trên thiết bị; tham khảo nhóm transcript/summary/speaker. Demo trên website có nội dung Pro, cần đối chiếu từng tính năng với bản mã nguồn. |

Nguồn mã mở bổ sung: [Scriberr](https://github.com/rishikanthc/Scriberr) có reader lời chép, playback, ghi chú và tóm tắt; [Anarlog](https://github.com/fastrepl/anarlog), trước đây là Hyprnote, là tham chiếu notepad local-first. Lượt này chưa cài/chạy hai dự án và chưa chọn code để tích hợp. Trước khi dùng mã cần kiểm đúng file, revision và giấy phép tương ứng.

Nên bắt đầu xem **Notta → Fireflies → MeetGeek → Fellow**. Các bài trợ giúp có ảnh và mô tả màn hình bên trong hữu ích hơn chỉ xem hero của landing page. Lượt nghiên cứu đã mở hướng dẫn Notta trên trình duyệt và quan sát ảnh bố cục; các nhận xét khác dựa trên nguồn công khai chính thức, không phải kiểm thử bằng tài khoản sản phẩm.

## 3. Đối chiếu dự án hiện tại

Đã đọc route/component trong `apps/web/src`, tài liệu triển khai 27/10 và audit 02/11. Working tree có nhiều thay đổi từ các đợt trước; lượt nghiên cứu giữ nguyên các thay đổi đó. Không suy trạng thái hiện tại chỉ từ báo cáo ngày 26/10.

Nền đã có trong mã:

- Route user/admin; menu có nhãn truy cập; workspace gồm **Nguồn âm thanh → Lời chép → Biên bản → Lịch sử**, thông tin họp mở riêng.
- Timeline nhiều nguồn/phần nối tiếp, các mốc và khoảng nghỉ.
- Nháp wizard trong sessionStorage theo tài khoản; bộ lọc cuộc họp đi cùng truy vấn API và URL.
- Player đối chiếu, panel chia độ rộng, sửa nội dung tại chỗ, preview Word và zoom.
- `useUnsavedForm` bảo vệ một số form và chuyển trang; trong lần đọc này màn `TemplateDetail` chưa dùng hook đó.

“Có nền” chỉ xác nhận cấu trúc đã thấy trong mã. Nghiên cứu này không chạy lại suite hoặc nghiệm thu hành vi end-to-end của các phần trên. Các lỗi về căn cứ, phiên bản, dữ kiện trong [audit 02/11](SYSTEM_AUDIT_2026-11-02.md) cần đối chiếu lại khi triển khai; UI cần biểu diễn đúng kết quả thực của backend.

## 4. Danh mục 42 màn hình và trạng thái

Danh mục gồm trang độc lập, tab, chế độ, hộp và trạng thái phục hồi. **Không phải 42 URL độc lập.** Những phần nhỏ có thể tiếp tục dùng hộp hoặc panel nếu giữ được ngữ cảnh. Các route mới là đề xuất, chưa phải API/tính năng đã có.

### A. Giới thiệu và truy cập — 7

| Màn hình | Vị trí | Hiện trạng và hướng hoàn thiện |
| --- | --- | --- |
| Giới thiệu Minda | Đề xuất `/welcome` | Mới; mục đích sản phẩm, khả năng thực tế, ví dụ và CTA mở ứng dụng. |
| Hướng dẫn bắt đầu | Đề xuất `/guide` | Mới; hướng dẫn toàn luồng, file mẫu được ghi rõ, đường quay lại ứng dụng. |
| Trung tâm trợ giúp | Đề xuất `/help` | Mới; bài theo công việc, lỗi phổ biến, thông tin hỗ trợ có thật. |
| Thông tin xử lý dữ liệu | Đề xuất `/data-policy` | Mới; nơi lưu, xử lý, truy cập, backup và xóa theo cấu hình thật. |
| Đăng nhập | Component theo phiên; có thể tách `/login` | Có nền; lỗi trường nhập, lỗi kết nối và quay về link công việc. |
| Thiết lập lần đầu | Component setup; có thể tách `/setup` | Có nền; tạo admin đầu tiên, trạng thái một lần và hướng dẫn môi trường. |
| Hỗ trợ tài khoản | Đề xuất `/account-help` | Mới; theo cơ chế admin cấp/cấp lại hiện có. Email tự phục hồi cần backend bổ sung. |

Trang giới thiệu có thể dùng để trình diễn khi triển khai local. Chưa có yêu cầu mở đăng ký đại trà hoặc bán dịch vụ, nên pricing, checkout và subscription không phải điều kiện hoàn thiện của phạm vi này.

### B. Công việc — 11

| Màn hình | Vị trí | Hiện trạng và hướng hoàn thiện |
| --- | --- | --- |
| Tổng quan | `/` | Có nền; việc cần tiếp tục, dữ liệu gần đây và trạng thái thực. |
| Danh sách cuộc họp | `/meetings` | Có nền; tìm/lọc toàn tập, phân trang, thao tác nhanh. |
| Tạo cuộc họp | `/meetings/new` | Có nền; wizard 4 bước, nháp, validation, upload và xác nhận. |
| Nguồn âm thanh | `/meetings/:id?tab=sources` | Có nền; bố cục nhiều nguồn, khoảng gián đoạn, căn mốc và phương án thay kéo thả. |
| Lời chép | `?tab=transcript` | Có nền; đọc/sửa/tìm/nghe; mốc thời gian và phiên bản rõ ràng. |
| Người nói | Chế độ `?tab=speakers` | Có nền; không cần thêm mục sidebar. Chia/gộp/sửa danh tính từng lượt cần hợp đồng API riêng. |
| Biên bản | `?tab=minutes` | Có nền; nội dung, căn cứ, sửa, preview, thể thức và tải Word. |
| Lịch sử và đối chiếu | `?tab=history` | Có nền; bản đang dùng, bản cũ, đối chiếu và khôi phục. |
| Thông tin cuộc họp | `?tab=overview` | Có nền; metadata, thành phần và quản lý cuộc họp, cảnh báo tác động sửa. |
| Cần rà soát | Đề xuất `/review` | Mới; gom các đoạn/trường chưa xong và mở đúng vị trí/phiên bản. Cần API tổng hợp theo quyền. |
| Tác vụ của tôi | Đề xuất `/jobs` | Mới ở cấp trang; API và thông báo có nền. Cần danh sách, chi tiết lỗi và phục hồi theo khả năng thực. |

### C. Tài nguyên và cá nhân — 8

| Màn hình | Vị trí | Hiện trạng và hướng hoàn thiện |
| --- | --- | --- |
| Thư viện mẫu | `/templates` | Có nền; mẫu riêng/chung, mô tả, tìm/lọc và trạng thái duyệt. |
| Nhập mẫu | Hộp trong `/templates` | Có nền; theo dõi tải → chuẩn hóa/OCR → đối chiếu → duyệt. Chỉ tách route nếu luồng cần đủ không gian. |
| Rà soát mẫu | `/templates/:id` | Có nền; bản gốc/Word/trường điền; bảo vệ draft và duyệt đúng bản. |
| Hồ sơ giọng | `/voices` | Có nền; mẫu giọng, nghe lại, trạng thái và chất lượng mẫu. |
| Chi tiết hồ sơ giọng | Hộp hiện có; có thể `/voices/:id` | Mở rộng; trang riêng chỉ khi số mẫu/thao tác đủ lớn; API đổi thông tin cần được kiểm. |
| Thư viện biên bản | Đề xuất `/documents` | Mở rộng; tìm đầu ra Word theo họp/trạng thái, trỏ về cùng version gốc. Cần API danh sách. |
| Thùng rác | `/trash` | Có nền cho cuộc họp; các loại mẫu/giọng cần cơ chế backend nếu đưa vào. |
| Thiết lập cá nhân | `/settings` | Có nền; nhóm tài khoản, bảo mật, tùy chọn; phân biệt với preset quản trị. |

### D. Quản trị — 10

| Màn hình | Vị trí | Hiện trạng và hướng hoàn thiện |
| --- | --- | --- |
| Tổng quan hệ thống | `/admin` | Có nền; worker/hàng đợi/dung lượng/vấn đề, liên kết tới chi tiết. |
| Tài khoản và quyền | `/admin/users` | Có nền; tạo/khóa/phân vai trò/cấp lại; thao tác và lịch sử rõ. |
| Cuộc họp toàn hệ thống | `/admin/meetings` | Có nền; metadata theo owner/trạng thái/trash; không tự cấp quyền đọc nội dung riêng. |
| Tác vụ và log | `/admin/jobs` | Có nền; state, stage, lỗi, hủy/thử lại và lease/heartbeat. |
| Model và preset | `/admin/models` | Có nền; cấu hình thường dùng/nâng cao, khả năng model và hiệu lực preset. |
| Mẫu dùng chung | `/admin/templates` | Có nền; duyệt/phát hành/phiên bản, tác động thay mẫu. |
| Sao lưu và khôi phục | `/admin/backups` | Có nền; tiến độ, kết quả, kiểm file và DB/root khôi phục riêng. |
| Đánh giá thực nghiệm | `/admin/experiments` | Có nền; dữ liệu chuẩn, loại metric, phạm vi và so sánh kết quả thật. |
| Nhật ký hệ thống | `/admin/audit` | Có nền; tìm/lọc/phân trang/chi tiết cần đối chiếu năng lực API. |
| Tình trạng hệ thống | Đề xuất `/admin/system` hoặc mục riêng | Mới ở cấp trang; gom worker/model/OCR/preview/lưu trữ từ diagnostics, bổ sung số đo thật khi cần. |

### E. Phục hồi và ngoại lệ — 6

| Màn hình/trạng thái | Hành vi cần có |
| --- | --- |
| Không tìm thấy | Lối quay về, dữ liệu đã xóa hoặc link cũ theo quyền; đã có fallback route. |
| Không đủ quyền | Thông báo và điều hướng phù hợp; không lộ dữ liệu tài nguyên riêng. |
| Phiên hết hạn | Đăng nhập lại, giữ đường dẫn và draft phù hợp; có nền xác thực nhưng cần hoàn thiện luồng phục hồi. |
| API mất kết nối/bảo trì | Phân biệt với sai mật khẩu; thử lại và bảo vệ nội dung đang nhập. |
| Xung đột/nội dung chưa lưu | Giữ phần nhập, xem bản mới/đối chiếu, cảnh báo rời; phủ tất cả form liên quan. |
| Worker/tác vụ gián đoạn | Phân biệt `running` đã lưu với worker còn sống; hiển thị hướng xử lý đúng checkpoint/retry thực tế. |

## 5. Điều hướng và công việc xuyên trang

Đề xuất sidebar người dùng có nhóm **Công việc** (Tổng quan, Cuộc họp, Cần rà soát, Tác vụ), **Tài nguyên** (Mẫu biên bản, Hồ sơ giọng, Biên bản khi có nhu cầu), **Cá nhân** (Thùng rác, Thiết lập). Trợ giúp và tài khoản luôn truy cập được. Chi tiết của một cuộc họp nằm ở điều hướng trong workspace.

Các luồng phải khép kín:

1. Vào lần đầu → hiểu quy trình → tạo mẫu/hồ sơ nếu cần → tạo cuộc họp.
2. Tạo cuộc họp → upload/sắp nguồn → kiểm bố cục/mốc → bắt đầu xử lý → theo dõi → mở lời chép.
3. Lời chép → lọc cần rà → nghe căn cứ → sửa chữ/người nói → thấy phiên bản và biên bản cần cập nhật.
4. Chọn mẫu → tạo biên bản → sửa nội dung → đối chiếu căn cứ → preview → xác nhận rà → tải DOCX đúng version.
5. Nhập PDF/scan → OCR → đối chiếu với bản gốc → lưu/nhận diện trường → duyệt → mẫu sẵn sàng.
6. Tác vụ lỗi/gián đoạn → xem bước và đầu ra hiện có → khắc phục → thử lại/tiếp tục khi backend hỗ trợ → trở lại công việc.
7. Xóa mềm → thùng rác → khôi phục; lịch sử → đối chiếu → khôi phục thành phiên bản mới.
8. Admin → thấy vấn đề vận hành → mở job/log → hành động có quyền → kiểm kết quả và audit.

Thông báo phải mở **đúng tài nguyên và phần liên quan**; không đưa mọi thông báo về dashboard hoặc settings. Trở lại từ căn cứ/preview giữ vị trí đọc và lựa chọn đang làm.

## 6. Điều kiện để coi một trang hoàn thiện

- Có mục đích, hành động chính, đường vào/ra và trạng thái hiện tại rõ ràng.
- Dữ liệu thật hoạt động, hoặc ví dụ được ghi rõ; không chỉ là bảng/card trang trí.
- Có loading, rỗng lần đầu, không có kết quả sau lọc, lỗi và thử lại khi áp dụng.
- Có trạng thái lưu/chưa lưu/đang lưu/xung đột, quyền và tài nguyên đang bận khi áp dụng.
- Keyboard/focus, menu thu gọn, nhãn, nội dung tiếng Việt và resize hoạt động.
- Trường thiếu căn cứ, nguồn cũ, nói chồng, mốc ước lượng và preview lỗi không bị ẩn mất.
- API, revision và job phản ánh đúng trạng thái; nút xuất/khôi phục/tiếp tục có hành vi thực tương ứng.

Chạy theo các kịch bản đầy đủ, ví dụ “audio → Word”, “scan → mẫu đã duyệt”, “sửa lời chép → cập nhật biên bản”, “lỗi worker → phục hồi”, thay vì chỉ nghiệm thu ảnh chụp từng trang. Không dùng tiêu chí số lượng trang để thay cho khả dụng.

## 7. Nền UI và thứ tự thực hiện đề xuất

Tiếp tục dùng React/Vite/Tailwind, React Router và Radix/shadcn hiện có. [Shadcn Admin](https://github.com/satnaing/shadcn-admin) là bộ giao diện tham chiếu nhiều trang, nhưng dùng router và phần auth riêng; [Untitled UI](https://www.untitledui.com/react/components) cung cấp hệ component và nhiều ví dụ có phần PRO. Cần thích nghi vào nghiệp vụ và quyền hiện tại, không suy template có sẵn backend của Minda.

Giữ nhận diện Minda đang dùng theo các quyết định thiết kế trước: nền sáng/xám, chữ và nút than đậm, điểm xanh nhẹ. Chuẩn hóa token, cỡ chữ nội dung, toolbar, bảng, form, modal và trạng thái trước khi phủ nhiều trang. Trang giới thiệu có thể khác mật độ workspace nhưng vẫn cùng thương hiệu.

Thứ tự:

1. Chốt danh mục và luồng; nhận diện phần đã có nền, trang cần bổ sung và mở rộng tùy chọn.
2. Chuẩn hóa shell/component; dựng ba màn đại diện có dữ liệu: danh sách cuộc họp, workspace lời chép, workspace biên bản.
3. Phủ đồng bộ các trang công việc, mẫu, giọng, thiết lập và quản trị; hoàn thiện các luồng lỗi/phục hồi.
4. Thêm giới thiệu, hướng dẫn, trợ giúp; mở rộng trang tổng hợp rà soát/tác vụ khi API sẵn sàng.
5. Xem xét thư viện tài liệu, chi tiết hồ sơ giọng, team/chia sẻ hoặc tích hợp theo nhu cầu thực tế. Lịch, đăng ký đại trà, thanh toán, CRM và chat xuyên cuộc họp là phạm vi mở rộng, cần yêu cầu và backend riêng.

## 8. Phạm vi xác minh

Đã nghiên cứu nguồn chính thức được dẫn cạnh từng nhận xét; đọc mã route và một số component hiện tại. Đã tạo bản đồ tương tác để xem danh mục theo khu vực và mục đích từng màn hình. Không đăng nhập/tạo tài khoản bên ngoài, không tải audio/tài liệu thật lên sản phẩm khác, không chạy lại ASR/LLM hoặc bộ kiểm thử ứng dụng trong lượt này. Phần “mới/mở rộng” là đề xuất, chưa có triển khai.

Bản đồ đã kiểm trên trình duyệt: 5 nhóm hiển thị đủ 42 mục, thao tác chọn cập nhật chi tiết, giữ focus sau khi chọn và không có lỗi JavaScript ghi nhận. Ở lượt kiểm chiều rộng 360 px, phần gốc có `clientWidth=scrollWidth=328`, không tràn ngang; đây là kiểm tra bản đồ nghiên cứu, không phải kiểm thử lại ứng dụng Minda. Máy chủ xem trước tạm đã được dừng sau kiểm tra.

Tài liệu liên quan: [khảo sát thư viện 26/10](../backend/UI_LIBRARY_RESEARCH_2026-10-26.md), [UX 27/10](FRONTEND_UX_RESEARCH_2026-10-27.md), [nội dung/bố cục 27/10](FRONTEND_CONTENT_LAYOUT_MOTION_RESEARCH_2026-10-27.md), [triển khai frontend 27/10](FRONTEND_IMPLEMENTATION_2026-10-27.md).
