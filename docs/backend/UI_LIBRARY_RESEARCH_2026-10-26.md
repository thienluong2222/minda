# Khảo sát GitHub cho giao diện Minda — 26/10/2026

## Đề xuất chính

Dùng **shadcn/ui làm hệ component chính**, tham khảo bố cục từ **satnaing/shadcn-admin**, và lấy **Untitled UI** làm tham chiếu về kiểu chữ, phân cấp thông tin, form và bảng. Chọn thêm block phù hợp từ **Blocks.so** cho upload, onboarding và dialog rồi chuẩn hóa theo cùng token của Minda.

Đây là đánh giá mức phù hợp với dự án sau khi đọc repository, tài liệu chính thức và xem một số demo. Chưa cài package, sao chép component hoặc chỉnh sửa giao diện. Chưa kiểm chứng tích hợp thực tế các thư viện mới.

## 1. Nền tảng hiện tại

Đã kiểm tra `apps/web/package.json` và `apps/web/components.json`:

- React 19, TypeScript, Vite và Tailwind CSS 4.
- `radix-ui`, Lucide, Sonner, TanStack Query; router hiện tại là React Router.
- shadcn đã cấu hình `radix-nova`, CSS variables, nền màu `neutral`, alias `@/`, không dùng React Server Components.
- UI hiện có nhiều CSS riêng trong `styles.css`; thay giao diện cần tổ chức lại token/layout, không chỉ bổ sung component mới.

Do đó nhóm React + Tailwind + shadcn/Radix có chi phí thích nghi dự kiến thấp hơn nhóm chuyển toàn bộ sang hệ primitive/theme khác. Đây là suy luận từ mã dự án và cấu trúc thư viện, chưa phải số đo thời gian triển khai.

## 2. Danh sách ngắn

| Nguồn GitHub | Loại | Điểm phù hợp với Minda | Giấy phép/phạm vi đã đọc | Đánh giá tích hợp |
| --- | --- | --- | --- | --- |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | Component và block mã nguồn | Sidebar, tabs, form, dialog, tooltip, data table, resizable panel; dễ tạo hệ thống nhất quán | MIT trong repository | **Ưu tiên làm nền**, giữ biến thể Radix phù hợp cấu hình hiện tại |
| [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) | Bộ giao diện ứng dụng mẫu | Shell, điều hướng, tìm kiếm lệnh, danh sách người dùng, tác vụ và thiết lập | MIT | **Ưu tiên tham khảo bố cục**; repo dùng TanStack Router và có phần Clerk, cần thích nghi với React Router/xác thực của Minda |
| [untitleduico/react](https://github.com/untitleduico/react) | Component và design system | Form, bảng, navigation, trạng thái, kiểu chữ và khoảng cách có hệ thống | Phần mã nguồn mở MIT; PRO có giấy phép riêng | **Tham chiếu thị giác mạnh**; component dùng React Aria, cần cân nhắc phạm vi thay đổi nếu tích hợp trực tiếp |
| [ephraimduncan/blocks](https://github.com/ephraimduncan/blocks) — Blocks.so | Các block React/Tailwind/shadcn | File upload, form layout, onboarding, dialog, sidebar và bảng | MIT | **Nguồn bổ sung chọn lọc**; kiểm từng dependency và chuẩn hóa style trước khi đưa vào app |
| [TailAdmin/free-react-tailwind-admin-dashboard](https://github.com/TailAdmin/free-react-tailwind-admin-dashboard) | Template dashboard | Khu vực admin với sidebar, profile, bảng, form và thống kê; README nêu React 19/Tailwind 4 | Bản Free MIT; PRO là phạm vi riêng | **Phương án phong cách thay thế**; demo có cả nội dung PRO, không coi mọi màn hình demo đều có trong repo miễn phí |
| [tremorlabs/tremor](https://github.com/tremorlabs/tremor) | Component cho dashboard/thống kê | Bảng, số liệu và biểu đồ cho vận hành/đánh giá thực nghiệm | Apache-2.0 | **Dùng có nhu cầu cụ thể**; package mẫu đang khai React 18, cần kiểm tương thích từng component với React 19 trước khi dùng |

Danh sách phân biệt component, block và mẫu ứng dụng. Nhận xét “phù hợp” là đánh giá cho nghiệp vụ Minda, không phải xếp hạng phổ biến hoặc bảo đảm chất lượng từ số sao GitHub.

## 3. Demo nên xem trước

### Hướng A — Tối giản, tập trung công việc: đề xuất cho Minda

- [Shadcn Admin — demo](https://shadcn-admin.netlify.app/)
- [Dashboard chính thức của shadcn](https://ui.shadcn.com/view/new-york-v4/dashboard-01)
- [Các block chính thức](https://ui.shadcn.com/blocks)

Đã quan sát trực tiếp dashboard của hai nguồn trên. Các mẫu dùng sidebar rõ ràng, header gọn, nền trung tính và cấu trúc bảng/thẻ thống nhất. Với Minda, nên chuyển trọng tâm sang cuộc họp cần tiếp tục, biên bản cần rà soát và tác vụ xử lý. Các biểu đồ doanh thu trong demo chỉ là nội dung minh họa của nguồn.

### Hướng B — SaaS chỉn chu, phân cấp thông tin rõ

- [Untitled UI — sidebar](https://www.untitledui.com/react/components/sidebar-navigations)
- [Untitled UI — tables](https://www.untitledui.com/react/components/tables)
- [Preview sidebar độc lập](https://www.untitledui.com/react/iframe/sidebar-navigation/sidebar-section-dividers-demo)

Đã xem trang component và preview sidebar độc lập. Có thể tham khảo độ rõ của nhãn, nhóm điều hướng, đường phân cách, cụm tài khoản và cách bố trí điều khiển. Mã nguồn mở và các ví dụ PRO cần được phân biệt theo từng component.

### Hướng C — Dashboard quản trị nhiều dữ liệu, điểm nhấn màu rõ

- [TailAdmin — demo](https://react-demo.tailadmin.com/)

Đã quan sát dashboard. Điểm nhấn xanh/tím rõ hơn hướng A; mẫu có nhiều màn hình vận hành. Phù hợp để cân nhắc cho admin nếu người dùng thích giao diện nhiều màu trạng thái. Trang demo có đánh dấu PRO cho một số mục.

### Block sát nghiệp vụ

- [Blocks.so — file upload](https://blocks.so/file-upload)
- [Blocks.so — form layout](https://blocks.so/form-layout)
- [Blocks.so — danh mục](https://blocks.so/)

Đã đọc danh mục và ví dụ chính thức. Các nhóm này sát với tải audio, tải mẫu tài liệu, wizard và các biểu mẫu quản trị.

## 4. Ánh xạ vào các màn hình Minda

| Màn hình | Hướng dùng |
| --- | --- |
| Shell user/admin | Sidebar + header + breadcrumb + account dropdown theo bố cục shadcn-admin, có nhãn/tooltip khi thu gọn |
| Dashboard | Các mục cần hoàn tất, cuộc họp gần đây, trạng thái xử lý và một hành động chính |
| Danh sách cuộc họp/admin | Data table, thanh tìm kiếm/lọc, phân trang; nếu lọc toàn tập thì API lọc trước phân trang |
| Wizard tạo cuộc họp | Form/stepper/upload block; thông báo lỗi cạnh trường, bảo vệ dữ liệu chưa lưu |
| Transcript | Toolbar gọn, danh sách có thứ bậc thời gian/người nói, panel căn cứ và audio |
| Biên bản | Panel thay đổi kích thước, tabs đúng ngữ nghĩa, editor theo trường, preview lớn, căn cứ mở cạnh nội dung |
| Mẫu và hồ sơ giọng | Upload, trạng thái xử lý/duyệt, empty state và menu thao tác đồng nhất |
| Thiết lập/admin | Form có phân nhóm, dialog có focus, phản hồi lưu/lỗi nhất quán |

Các thư viện cung cấp thành phần và mẫu tương tác; bố cục transcript/biên bản vẫn cần thiết kế riêng theo công việc thực tế của Minda.

## 5. Định hướng thị giác đề xuất

Các thông số dưới đây là đề xuất ban đầu, chưa phải quyết định đã chốt:

- Khung ứng dụng tận dụng chiều rộng cửa sổ; sidebar có thể thu gọn và luôn truy cập được tài khoản/đăng xuất.
- Nền trắng/xám nhạt, đường viền mảnh, một màu nhấn của thương hiệu Minda.
- Cỡ chữ nội dung khoảng 14–16 px, tăng ưu tiên đọc cho transcript và nội dung biên bản; nhãn trạng thái dễ nhìn.
- Bo góc vừa, shadow nhẹ; giảm số lớp card lồng nhau.
- Danh sách và toolbar có khoảng cách nhất quán; hành động chính/phụ rõ ràng.
- Màn hình biên bản ưu tiên diện tích tài liệu và khả năng đối chiếu, có điều chỉnh tỷ lệ panel.
- Chuyển động ngắn phục vụ phản hồi thao tác; tiếp tục hỗ trợ reduced motion.
- Dùng một bộ token và quy tắc component xuyên suốt user/admin.

Mẫu đầu tiên nên thể hiện đủ dashboard, danh sách cuộc họp và workspace biên bản để đánh giá cả hình thức lẫn công việc đọc/chỉnh sửa.

## 6. Nguồn đã xem nhưng chưa ưu tiên tích hợp

- [Ant Design](https://github.com/ant-design/ant-design): bộ component doanh nghiệp đầy đủ; hệ theme riêng làm phạm vi chuyển đổi rộng hơn so với tiếp tục shadcn. Có thể cân nhắc nếu chọn chủ đích thay toàn bộ hệ UI.
- [Magic UI](https://github.com/magicuidesign/magicui): phù hợp cho chuyển động và phần giới thiệu sản phẩm; nhu cầu trước mắt của Minda tập trung vào form, dữ liệu và tài liệu.
- **Origin UI đã chuyển thành coss ui**: [repository hiện tại](https://github.com/cosscom/ui), [tài liệu licensing](https://github.com/cosscom/ui/blob/main/LICENSING.md). Repo ghi giấy phép mặc định AGPLv3, các thư mục `apps/origin/` và `apps/ui/` có phạm vi MIT theo tài liệu. Vì vậy cần kiểm đúng đường dẫn nguồn; không suy toàn bộ repo hiện tại là MIT từ README Origin UI cũ. coss ui hiện giới thiệu dùng Base UI, khác primitive Radix của Minda.

## 7. Tài liệu kỹ thuật chính thức

- [shadcn/ui — Vite](https://ui.shadcn.com/docs/installation/vite)
- [shadcn/ui — Sidebar Radix](https://ui.shadcn.com/docs/components/radix/sidebar)
- [shadcn-admin — package manifest](https://github.com/satnaing/shadcn-admin/blob/main/package.json)
- [Untitled UI — README và giới hạn MIT/PRO](https://github.com/untitleduico/react#license)
- [Tremor — package manifest](https://github.com/tremorlabs/tremor/blob/main/package.json)

Nghiên cứu dựa trên các trang truy cập ngày 26/10/2026. Trước khi thực sự đưa code vào dự án, cần chọn component và revision cụ thể rồi kiểm build/hành vi liên quan; phiên khảo sát này chưa thay dependency hoặc lockfile.
