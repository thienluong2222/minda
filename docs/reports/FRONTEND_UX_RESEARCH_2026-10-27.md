# Nâng cấp frontend Minda: kết quả nghiên cứu UI/UX và GitHub

Ngày khảo sát: 27/10/2026. Phạm vi: frontend `web_app/apps/web`, các hợp đồng timeline sau bước 3 và nguồn công khai chính thức. Đây là nghiên cứu và đề xuất thiết kế; chưa thay mã ứng dụng, dependency, router hoặc cơ chế đăng nhập. Bước 4–6 chưa được triển khai trong lượt này.

**Yêu cầu đã chốt của người dùng:** giữ bảng màu Minda hiện tại. Nâng cấp bố cục, kiểu chữ, khoảng cách và thao tác dựa trên nhận diện cũ; màu của template chỉ là tham khảo. Phác thảo đã cập nhật về nền sáng, nút than đậm và các màu trạng thái hiện có.

Nghiên cứu tiếp theo về phân chia màn hình, giữ/chuyển/bỏ nội dung, bố trí chữ và Three.js: [FRONTEND_CONTENT_LAYOUT_MOTION_RESEARCH_2026-10-27.md](</Users/thien/Documents/School/Luận văn/web_app/docs/reports/FRONTEND_CONTENT_LAYOUT_MOTION_RESEARCH_2026-10-27.md>).

## 1. Quyết định đề xuất

Nâng Minda theo hướng **không gian làm việc cho người lập biên bản**: dễ đọc, thấy việc cần làm tiếp theo, đối chiếu lời gốc nhanh, sửa có lịch sử và biết phần nào còn chưa chắc.

Giữ React/Vite/Tailwind, React Router, TanStack Query và Radix/shadcn hiện có. Chuẩn hóa hệ component, token và bố cục; tham khảo Shadcn Admin cho khung ứng dụng, Untitled UI cho phân cấp và mật độ thông tin, chọn block phù hợp cho upload/form. Thiết kế riêng workspace audio/transcript/biên bản theo nghiệp vụ Minda. Không có template được khảo sát nào giải quyết sẵn toàn bộ luồng này.

Ba thay đổi có tác động lớn nhất:

1. **Workspace đối chiếu:** nội dung biên bản là vùng làm việc chính; căn cứ, lời chép và audio mở cạnh nội dung; bố cục điều chỉnh được.
2. **Luồng có trạng thái rõ:** nguồn âm thanh → lời chép → rà nội dung → xuất tài liệu, luôn biết đang ở đâu, còn thiếu gì và kết quả nào đã cũ.
3. **Nền giao diện nhất quán:** chữ dễ đọc, thao tác đủ lớn, bàn phím/focus hoạt động, form không làm mất công nhập và bảng lọc đúng toàn bộ dữ liệu.

Đây là lựa chọn dựa trên mức phù hợp với mã và công việc của Minda, chưa phải kết quả thử khả dụng với người dùng hoặc đo chi phí tích hợp.

## 2. Những gì đã kiểm tra

- Đọc manifest và cấu hình shadcn: React 19, Vite, Tailwind 4, Radix, Lucide, Sonner, React Router và TanStack Query; preset `radix-nova`, CSS variables và tài nguyên chữ đóng gói local.
- Đối chiếu `app.tsx`, `styles.css`, `index.css`, danh sách/tạo cuộc họp, workspace, transcript và kiểu dữ liệu timeline sau bước 3.
- Xem lại trực tiếp ảnh dashboard, transcript và biên bản ngày 26/10 trong `artifacts/ui-review-2026-10-26/`. Các ảnh là fixture kiểm giao diện, không phải cuộc họp thật; ảnh biên bản là preview giả lập. Không coi chúng là ảnh chụp ứng dụng mới trong lượt này.
- Đọc nguồn chính thức của Nielsen Norman Group, W3C/WAI, Microsoft Research, GOV.UK Design System; repository, README, manifest và thông tin license của các ứng viên bên dưới.
- Mở trình duyệt quan sát demo Shadcn Admin, preview sidebar Untitled UI và demo dnd-timeline. Chưa kiểm tích hợp, accessibility đầy đủ hoặc hiệu năng của chúng trong Minda.

Khảo sát ngày 26/10 đã đề xuất nền shadcn. Lần này bổ sung quy tắc UX cụ thể, xử lý bất định của AI, timeline nhiều nguồn, audio dài, tiêu chí nghiệm thu và cách kết nối với bước 4–6. Báo cáo cũ được giữ nguyên để phân biệt lịch sử.

## 3. Khoảng trống hiện tại cần nâng cấp

| Quan sát | Căn cứ | Hướng sửa |
| --- | --- | --- |
| Điều hướng thu gọn ẩn chữ và đăng xuất; link chưa có tên truy cập độc lập với chữ | `app.tsx` và breakpoint 1.050 px trong `styles.css`; kiểm trình duyệt cũ đã tái hiện, mã hiện tại vẫn có cấu trúc này | Tooltip và accessible name; tài khoản/đăng xuất luôn truy cập được. |
| Form tạo cuộc họp giữ dữ liệu trong state; chưa có cơ chế bảo vệ lúc rời trang | `NewMeeting` trong `features/meetings/pages.tsx`; báo cáo cũ đã tái hiện mất công nhập | Nháp và thông báo chưa lưu; khi quay lại giữ metadata, nói rõ nếu cần chọn lại file. |
| Bộ lọc trạng thái chỉ áp dụng lên `items` của trang đã tải | `Meetings` trong `pages.tsx` | API lọc trước phân trang; tổng kết quả và query URL phải thống nhất với bộ lọc. |
| Tab workspace mới thể hiện trạng thái bằng CSS | `workspace.tsx`, nhóm `workspace-tabs` | Dùng Tabs có ngữ nghĩa/focus/bàn phím hoặc điều hướng link có `aria-current` phù hợp. |
| Chữ phụ/toolbar/bảng có nhiều cỡ 9–12 px, một số màu chữ rất nhẹ | CSS và ảnh fixture đã xem | Tăng cỡ chữ quan trọng, đo tương phản trên nền thực; không thu nhỏ chữ để ép bảng vừa màn hình. |
| Token nền/màu/radius có nhiều nguồn ghi đè | `index.css`, `styles.css` | Một bộ token rõ cho nền, chữ, viền, trạng thái, khoảng cách và component. |
| Workspace biên bản chia cột khá cố định; phần sửa và căn cứ cần nhiều thao tác chuyển qua lại | Ảnh fixture và báo cáo readiness | Hai panel có thể điều chỉnh, căn cứ cạnh nội dung, preview có zoom/fit; chế độ tập trung tài liệu. |
| Backend đã có dữ liệu timeline, frontend chưa có màn hình thao tác tương ứng | Bước 2–3, `lib/timeline.ts` và `types.ts` | Dựng màn hình nguồn nhiều hàng, kho chưa xếp, vị trí khai báo và kết quả căn tự động tách rõ. |

Các mục đọc mã là kết luận về cấu trúc hiện tại. Không tuyên bố đã tái chạy toàn bộ browser smoke hoặc đo tương phản trực tiếp trong lượt nghiên cứu này.

## 4. Quy tắc UI/UX áp dụng cho Minda

### 4.1. Thấy trạng thái và biết việc tiếp theo

Theo [10 usability heuristics của Nielsen Norman Group](https://www.nngroup.com/articles/ten-usability-heuristics/), giao diện cần phản hồi trạng thái, dùng khái niệm quen thuộc, giảm ghi nhớ và giúp phục hồi lỗi. Áp dụng:

- Dashboard ưu tiên cuộc họp cần tiếp tục và biên bản cần rà, kèm hành động cụ thể.
- Tác vụ ghi rõ đang chuẩn bị audio, chép lời hay tạo biên bản; tỷ lệ tiến độ chỉ hiển thị khi có dữ liệu thực. Chưa đo được thời gian còn lại thì không dựng ETA giả.
- Lỗi cạnh thao tác/trường bị lỗi, có hướng khắc phục; tác vụ lỗi có lối thử lại khi backend cho phép.
- Cấu hình ít dùng nằm trong phần mở rộng; thao tác thường dùng luôn dễ thấy.
- Hiển thị đã lưu, đang lưu, lỗi lưu và nội dung chưa lưu; dùng lịch sử/hoàn tác phù hợp.

[Task list](https://design-system.service.gov.uk/components/task-list/) và [Check answers](https://design-system.service.gov.uk/patterns/check-answers/) của GOV.UK là tham chiếu cho việc thấy các phần còn thiếu, quay lại sửa và kiểm trước khi hoàn tất. Minda dùng mô hình tương tác này, không sao chép nguyên phong cách của cổng dịch vụ công Anh.

### 4.2. AI có thể sai: rà và sửa phải là thao tác chính

[Guidelines for Human-AI Interaction, CHI 2019](https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/) đề xuất làm rõ năng lực/giới hạn, hỗ trợ sửa nhanh và cho người dùng tiếp cận giải thích. Với Minda:

- Phân biệt **bản nháp AI**, **có lời gốc đối chiếu**, **cần rà**, **chưa đủ thông tin**, **đã sửa** và **đã được người dùng rà**. Một đoạn có căn cứ chưa đồng nghĩa kết luận đã đúng.
- Chọn nội dung mở đúng phát biểu và đoạn audio liên quan; chỉ nhảy tới phần đang đối chiếu, giữ vị trí đọc tài liệu.
- Đánh dấu giờ ước lượng, nguồn mốc và phần thời gian chưa xác định. Không hiện phần trăm tin cậy chưa hiệu chuẩn như xác suất đúng.
- Khi tạo lại, cho đối chiếu thay đổi và giữ rõ phần sửa tay; kết quả không còn khớp phiên bản transcript/timeline được ghi là cần cập nhật.
- Chỉ bật “Tiếp tục xử lý” khi bước 4 thực sự có phục hồi. Giao diện không được giả định backend đã hỗ trợ các bước tương lai.

### 4.3. Khả năng tiếp cận là điều kiện nghiệm thu

Mục tiêu thiết kế là các yêu cầu WCAG 2.2 AA liên quan; chưa có đánh giá tuân thủ đầy đủ.

| Yêu cầu có nguồn | Áp dụng |
| --- | --- |
| [Contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html): chữ thường tối thiểu 4,5:1, chữ lớn 3:1 theo định nghĩa chuẩn | Đo trên từng nền, gồm nhãn phụ, placeholder và trạng thái có ý nghĩa; không chỉ kiểm màu chủ đạo. |
| [Dragging movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html): có cách thao tác bằng con trỏ đơn mà không kéo, trừ các ngoại lệ | Timeline có “Đưa trước/sau”, “Chuyển nguồn” và “Đặt thời điểm”. Hỗ trợ bàn phím là yêu cầu riêng; chỉ có bàn phím chưa thay cho phương án bấm không kéo. |
| [Target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html): 24×24 CSS px hoặc đáp ứng ngoại lệ/khoảng cách | Thiết kế Minda ưu tiên điều khiển khoảng 40–44 px, nhất là trên cảm ứng; đây là lựa chọn thiết kế, không phải diễn giải mức AA thành bắt buộc 44 px. |
| [Focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html) | Player/thanh công cụ cố định không che hoàn toàn phần tử đang focus; bố trí để thấy rõ toàn bộ khi có thể. |
| [Tabs pattern của WAI-ARIA APG](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) | Vai trò và trạng thái chọn đúng, liên kết panel, thao tác bàn phím và focus có kiểm tra thực. |

Không dùng màu làm dấu hiệu duy nhất. Màu nguồn, nhãn trạng thái và cảnh báo có chữ/biểu tượng đi kèm. Chuyển động phục vụ phản hồi, tôn trọng reduced motion; thông báo tiến độ không giành focus liên tục.

## 5. Các nguồn GitHub phù hợp

Các đánh giá mức phù hợp dưới đây là nhận định cho Minda. “Có accessibility” trong tài liệu thư viện không thay cho kiểm tra giao diện sau tích hợp. Không dùng số sao làm tiêu chí chọn chính.

| Nguồn | Loại và giấy phép đã xác minh | Lấy phần nào cho Minda | Lưu ý / lựa chọn |
| --- | --- | --- | --- |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | Component/block, MIT; có [hướng dẫn Vite](https://ui.shadcn.com/docs/installation/vite) | Sidebar, Tabs, Dialog, Tooltip, Form, Table, Empty, Resizable; chuẩn hóa cùng token | **Nền chính.** Minda đã dùng Radix/shadcn. Giữ lựa chọn primitive nhất quán, không chạy lệnh nâng cấp hàng loạt chỉ vì registry có bản mới. |
| [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) | Template ứng dụng React/Vite, [MIT](https://github.com/satnaing/shadcn-admin/blob/main/LICENSE) | Shell, sidebar, toolbar, account menu, bảng và bố cục thiết lập | **Tham khảo khung ưu tiên.** [Manifest](https://github.com/satnaing/shadcn-admin/blob/main/package.json) dùng TanStack Router và Clerk; chọn layout/component rồi thích nghi với router và auth hiện tại. |
| [untitleduico/react](https://github.com/untitleduico/react) | Component React Aria/Tailwind; [MIT cho phần có trong repo, PRO riêng](https://github.com/untitleduico/react#license) | Phân cấp chữ, khoảng cách, form, bảng, empty state và cụm tài khoản | **Tham chiếu thị giác ưu tiên.** Chưa đề xuất thêm toàn bộ primitive React Aria bên cạnh Radix. Không coi mọi mẫu trên website là mã miễn phí. |
| [ephraimduncan/blocks — Blocks.so](https://github.com/ephraimduncan/blocks) | Block React/Tailwind/shadcn, [MIT](https://github.com/ephraimduncan/blocks/blob/main/LICENSE.md) | Upload, form layout, trạng thái rỗng và dialog chọn lọc | **Nguồn bổ sung.** Rà dependency, primitive, nhãn truy cập và style từng block; đổi cùng token Minda. |
| [TailAdmin/free-react-tailwind-admin-dashboard](https://github.com/TailAdmin/free-react-tailwind-admin-dashboard) | Template dashboard React/Tailwind, bản Free [MIT](https://github.com/TailAdmin/free-react-tailwind-admin-dashboard/blob/main/LICENSE.md) | Tham khảo màn quản trị, bảng, profile và settings | **Phương án hình thức thay thế.** Phạm vi style/dependency rộng hơn; chưa chọn làm nền của Minda. Free/PRO phải phân biệt theo đúng phần mã. |
| [samuelarbibe/dnd-timeline](https://github.com/samuelarbibe/dnd-timeline) | Timeline headless dựa dnd-kit, [MIT](https://github.com/samuelarbibe/dnd-timeline/blob/main/LICENSE) | Hàng nguồn, đoạn di chuyển/đổi độ dài, vùng nhìn và khả năng kết hợp virtualization | **Ứng viên thử trước.** [Manifest đã đọc](https://github.com/samuelarbibe/dnd-timeline/blob/main/packages/dnd-timeline/package.json) còn dùng types React 18 trong dev; chưa chứng minh phù hợp React 19 của Minda. Thời gian/coverage của backend phải là căn cứ. |
| [clauderic/dnd-kit](https://github.com/clauderic/dnd-kit) | Bộ kéo thả, MIT; có cảm biến bàn phím/con trỏ và live region trong tài liệu | Sắp xếp kho file, đổi hàng; phương án tự xây timeline nếu ứng viên trên không đáp ứng | **Lớp thao tác.** Không cài song song hai thế hệ API kéo thả khác nhau; cần chọn theo dependency của phương án timeline. |
| [katspaugh/wavesurfer.js](https://github.com/katspaugh/wavesurfer.js) | Waveform/playback, [BSD-3-Clause](https://github.com/katspaugh/wavesurfer.js/blob/main/LICENSE) | Dạng sóng, vị trí đang phát, vùng căn cứ audio và điều khiển nghe lại | **Ứng viên cho audio.** [Tài liệu cảnh báo file lớn](https://github.com/katspaugh/wavesurfer.js#questions) có thể hết bộ nhớ khi giải mã trong browser; dùng peaks tạo sẵn và audio phục vụ phù hợp. Đây không phải bộ đồng bộ nhiều máy. |
| [bvaughn/react-resizable-panels](https://github.com/bvaughn/react-resizable-panels) | Panel co giãn, [MIT](https://github.com/bvaughn/react-resizable-panels/blob/main/LICENSE.md) | Chia tài liệu/căn cứ, thu gọn và nhớ tỷ lệ panel | **Ưu tiên cho workspace**, thông qua wrapper tương thích như [Resizable của shadcn](https://ui.shadcn.com/docs/components/radix/resizable). Kiểm API/phiên bản, bàn phím và phương án một panel khi hẹp. |

Không đề xuất đổi sang Next.js hoặc thay toàn bộ auth chỉ để dùng một template. Chưa cần editor văn bản phong phú mới: ưu tiên sửa theo trường/nội dung và theo dõi căn cứ; chỉ chọn editor riêng nếu tác vụ thực cần và không làm mất liên kết DOCX/bằng chứng.

### Demo để xem

- [Shadcn Admin](https://shadcn-admin.netlify.app/) — đã quan sát dashboard: điều hướng, account và thanh công cụ có phân cấp gọn. Các biểu đồ doanh thu là dữ liệu mẫu, không phải nội dung nên chép vào Minda.
- [Untitled UI sidebar preview](https://www.untitledui.com/react/iframe/sidebar-navigation/sidebar-section-dividers-demo) — đã quan sát cách chia nhóm, tên mục và cụm tài khoản.
- [dnd-timeline](https://dnd-timeline-demo.vercel.app/) — đã quan sát các hàng và đoạn kéo thả; demo không phải bằng chứng rằng thao tác timeline Minda đã đáp ứng bàn phím, unknown gap hoặc lưu revision.
- [Blocks.so file upload](https://blocks.so/file-upload), [form layout](https://blocks.so/form-layout) — nguồn tham khảo block, cần chọn ví dụ cụ thể khi triển khai.

## 6. Bố cục sản phẩm đề xuất

### Điều hướng toàn ứng dụng

Giữ các nhóm Cuộc họp, Thư viện mẫu, Hồ sơ giọng và Thiết lập. Quản trị có khu vực riêng nhưng dùng cùng component và token. Dashboard đặt “Tiếp tục công việc” và “Cần rà” ở vị trí ưu tiên; số lượng thống kê chỉ dùng khi giúp quyết định việc tiếp theo.

Trong một cuộc họp, thứ tự chính là **Nguồn âm thanh → Lời chép → Biên bản**, bên cạnh Tổng quan/Lịch sử. Trang cho biết phần còn thiếu trước hành động tiếp theo, không chỉ dùng một nhãn “Có biên bản”. Người dùng có thể quay lại bước đã làm; trạng thái phụ thuộc phản ánh thay đổi dữ liệu.

### Nguồn âm thanh / timeline

- Kho file chưa xếp ở vị trí rõ, mỗi thiết bị/nguồn một hàng, nhiều clip ổn định ID trên cùng hàng.
- Có hai cách nhìn tương ứng dữ liệu: **thứ tự các phần** khi chưa có đồng hồ chung và **trục thời gian** khi đủ mốc. Không đặt mọi phần chưa rõ ở giây 0 trên trục chung.
- Phân biệt mốc do người dùng đặt, mốc khớp âm thanh, vùng ngoại suy và khoảng chưa xác định bằng nhãn/chú giải; có thể xem căn cứ chi tiết theo yêu cầu.
- Kéo đổi thứ tự khác kéo đặt thời điểm. Thao tác đặt mốc cần thể hiện rõ ý nghĩa; lưu một nhóm thao tác lúc thả, dùng revision hiện tại. Xung đột revision tải lại/đối chiếu, không tự ghi đè.
- Có menu/nút thay cho kéo. Bỏ clip khỏi bố cục phải phân biệt với xóa file gốc. Thông báo rõ nếu sửa bố cục làm transcript/biên bản cần cập nhật.
- Dùng `getTimeline`, `updateTimeline`, `uploadTimelineFiles`, `getTimelineAlignment` và các kiểu dữ liệu đã có. Chỉ hiển thị alignment khớp hash và chưa stale. Đây là phần có thể làm trước bước 4.

### Lời chép và nghe lại

Danh sách đọc liên tục, thời gian/người nói rõ, chỉnh ngay tại đoạn hoặc panel cạnh bên, player dùng chung. Chọn câu thì nghe đúng vùng/nguồn; phân biệt đồng hồ cục bộ và chung. Mặc định không tự cuộn giật trang khi người dùng đang sửa; có điều khiển theo vị trí phát. Phím tắt hiển thị trong trợ giúp, không chiếm phím khi đang nhập chữ.

Với transcript dài, chỉ dựng các dòng gần vùng nhìn và dùng ID ổn định; giữ tìm kiếm, điều hướng bằng bàn phím và liên kết đoạn khi virtualization. Tải/giải mã waveform theo nhu cầu, không tạo nhiều player đầy đủ cho mọi dòng.

### Biên bản và căn cứ

Đề xuất mặc định hai panel: **nội dung đang rà** và **căn cứ tương ứng**. Mở preview DOCX khi cần xem bố cục; cho fit/zoom và trở lại nội dung đang sửa. Ở màn hình rộng có thể mở đề mục + tài liệu + căn cứ; không ép ba cột lên laptop hẹp.

Có hai hướng để xem trong phác thảo: “Đối chiếu cạnh nhau” và “Tập trung tài liệu”. Chúng dùng dữ liệu minh họa, không kết nối API, không phát audio và không tạo file thật. Phác thảo minh họa cách xem căn cứ và ghi nhận đã rà, chưa phải frontend đã triển khai.

Gắn trạng thái ở đúng trường/đoạn, có bộ lọc việc cần rà và tóm tắt phần còn thiếu. Các quyết định thay đổi sau nghỉ/phiếu theo vòng ở bước 5 cần có vùng hiển thị diễn biến và liên kết phát biểu, không phải chỉ thêm một badge vào đoạn văn.

### Hình thức và responsive

Giữ nguyên bảng màu hiện tại theo yêu cầu người dùng: nền ngoài `#eef0f5`, khung/sidebar `#f7f8fb`, vùng nội dung trắng, chữ chính `#1d2330`, nút chính `#20242c`, viền `#e6e8ee` và xanh phụ `#3f7159`. Giữ nhóm màu trạng thái hiện có; xanh chỉ dùng theo vai trò đang có, không thay nút chính bằng xanh hoặc chuyển sang nền tối. Gom token để thống nhất cách dùng màu mà vẫn giữ nhận diện cũ. Font hiện tại có tiếng Việt và đóng gói local có thể giữ.

Các số dưới đây là điểm bắt đầu để dựng mẫu và thử, không phải chuẩn bắt buộc:

- Nội dung đọc/chỉnh khoảng 15–16 px; điều khiển chính 14 px; tránh đưa thông tin cần đọc thường xuyên về 9–10 px.
- Khoảng cách theo nhịp 4/8 px, radius vừa phải; token dùng xuyên suốt. Tránh để header/trang trí chiếm phần lớn màn hình làm việc.
- Ở 1.280–1.440 px ưu tiên hai panel vừa đọc; ba panel chỉ khi đủ chiều rộng. Cửa sổ hẹp chuyển panel thành chế độ xem nối tiếp hoặc drawer, giữ vị trí công việc.
- Trên điện thoại dùng một vùng làm việc chính, thao tác bấm thay kéo, vẫn truy cập được nghe lại và sửa. Timeline dày có chế độ danh sách tương đương.
- Tên cuộc họp dài, tên người/đơn vị dài, nhiều chữ tiếng Việt có dấu và trạng thái lỗi phải nằm trong bộ thử layout.

## 7. Thử nhỏ trước khi chốt thư viện

| Thử | Điều cần chứng minh |
| --- | --- |
| Timeline React 19 | Kéo và bấm đổi thứ tự/chuyển hàng/đặt mốc; clip không đổi ID; không biến unknown gap thành 0; mốc tự động tách khỏi thủ công; lỗi revision phục hồi được. |
| Waveform file dài | Backend tạo artifact peaks phù hợp; frontend không buộc giải mã tất cả file; kiểm seek/HTTP Range qua route có phân quyền, thời gian audio khớp căn cứ. Đo bộ nhớ thực, không dựa README. |
| Workspace panel | Điều chỉnh bằng bàn phím/con trỏ, thu gọn, nhớ tỷ lệ; focus không mất; ở 390/768/1.024/1.280/1.440 px vẫn đọc và sửa được. |
| Danh sách lớn | Tìm/lọc/phân trang đúng toàn tập, quay lại giữ vị trí; hàng nghìn lượt nói không tạo quá nhiều DOM/player. |

Peaks là dữ liệu để vẽ waveform, không thay audio và không xác nhận sự liên tục. Artifact peaks nhiều mức chi tiết và phục vụ audio dài cần được phối hợp với bước 4. Hiện chưa cài thư viện hoặc có benchmark các thử trên.

## 8. Thứ tự nâng cấp và liên hệ bước 4–6

| Đợt | Phạm vi | Có thể làm lúc nào |
| --- | --- | --- |
| A — Nền UI và lỗi dùng được | Token, chữ, shell, accessible names, account, tabs, form chưa lưu, lỗi/lưu/empty state, lọc danh sách đúng | Làm trước bước 4; có thể phát hành từng màn hình. |
| B — Workspace và nguồn âm thanh | Timeline trên API bước 2–3, đọc alignment, player/căn cứ dùng chung, panel co giãn, preview rõ | Làm ngay trên năng lực hiện có; chỉ ghi mức thời lượng đang hỗ trợ. |
| C — Họp dài và tiếp tục | Tiến độ theo khối, khả năng tiếp tục, waveform peaks, transcript nhiều dòng | Gắn với kết quả backend bước 4; bật chức năng khi đã kiểm đạt. |
| D — Diễn biến và rà quyết định | Trạng thái đề xuất/kết luận, phiên/đề mục/vòng phiếu, so thay đổi và giữ sửa tay | Gắn với dữ liệu bước 5. |
| E — Nghiệm thu sản phẩm | Tác vụ người dùng thật, accessibility, responsive, browser, hiệu năng và luồng xuất tài liệu | Bổ sung vào bước 6; không chỉ kiểm model. |

Chưa ước lượng số ngày trước khi chốt phạm vi màn hình và thử tích hợp. Mục tiêu là thay dần component/layout, giữ nghiệp vụ và hợp đồng API có thể đối chiếu.

## 9. Điều kiện nghiệm thu frontend

1. Người mới tạo một cuộc họp, tải/xếp nhiều file và biết vì sao chưa thể xử lý nếu thiếu mốc; không phải hiểu model hoặc worker.
2. Người rà tìm được một ý cần sửa, mở đúng lời/audio gốc, chỉnh và thấy trạng thái lưu/phiên bản; không mất vị trí khi đóng căn cứ.
3. Rời form, mất mạng lúc lưu, sửa từ tab cũ và tác vụ bị ngắt không làm mất thay đổi âm thầm hoặc báo hoàn tất sai.
4. Bộ lọc cho kết quả đúng cả dữ liệu ngoài trang hiện tại. Kết quả cũ và phần thời gian chưa xác định có nhãn/đường xử lý rõ.
5. Dùng bàn phím hoàn thành tác vụ cốt lõi; focus/dialog/tab đúng; kéo có phương án bấm; màu/tương phản và kích thước được đo trên giao diện thực. Chạy kiểm tự động kết hợp kiểm tay, không xem công cụ tự động là chứng nhận AA.
6. Kiểm nhiều kích thước và ít nhất các trình duyệt mục tiêu được chốt; không tràn trang hoặc thu chữ tới mức khó đọc. Audio có kiểm thực trên trình duyệt, không suy từ ảnh chụp.
7. So sánh trước/sau bằng cùng tác vụ: số thao tác, thời gian hoàn thành, lỗi người dùng, lượng sửa tay và ý kiến về độ rõ. Có thể bắt đầu nhóm nhỏ đại diện người lập/rà biên bản; không coi một nhóm nhỏ là chứng minh cho mọi người dùng.
8. Bản DOCX/preview vẫn đúng phiên bản đã rà; việc đổi giao diện không làm mất căn cứ, thao tác khôi phục hoặc trạng thái nội dung.

## 10. Giới hạn của nghiên cứu

Đã kiểm nguồn công khai và mã dự án; các lựa chọn thiết kế còn cần xác nhận qua mẫu và tác vụ thực. Chưa mua template, chưa sao chép mã ngoài vào ứng dụng, chưa chạy thử tích hợp các thư viện mới, chưa đo accessibility/hiệu năng hoặc phỏng vấn người dùng trong lượt này. Mốc thời lượng 20 phút của hệ thống vẫn giữ nguyên cho đến khi bước 4 được triển khai và kiểm chứng.

Thông tin giấy phép ở bảng phản ánh các file/repository đã xem, phân biệt phần miễn phí/PRO. Khi đưa mã vào cần chọn revision cụ thể và giữ thông báo license tương ứng; chưa đánh giá toàn bộ phụ thuộc bắc cầu.

Danh mục nguồn, ảnh đã xem, phạm vi thử phác thảo và dấu kiểm tra frontend không đổi so với sau bước 3: [research_evidence.json](</Users/thien/Documents/School/Luận văn/web_app/data/evaluations/frontend-ux-research-20261027/research_evidence.json>).
