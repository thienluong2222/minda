# Kế hoạch triển khai giao diện Minda thống nhất

**Ngày:** 06/11/2026 · **Agent nhận bàn giao:** Gemini 4 Argon Medium, theo chỉ định của người dùng.  
**Loại tài liệu:** đặc tả và kế hoạch triển khai; chưa phải báo cáo hoàn thành.  
**Mục tiêu:** nâng toàn bộ web Minda thành sản phẩm chuyên nghiệp, gọn gàng, tối giản và nhất quán giữa mọi trang.  
**Quyết định của người dùng:** đồng ý các sản phẩm tham chiếu đã nghiên cứu, nhưng mọi tham chiếu phải được chuyển về một hệ thiết kế Minda duy nhất.

**Logo và favicon:** người dùng sẽ tự thiết kế. Agent triển khai cơ chế thay ảnh tập trung theo mục 3.3, dùng nhận diện hiện tại làm hiển thị tạm; không tự thiết kế logo chính thức.

Tài liệu này có đủ quyết định thiết kế, danh mục màn hình, phạm vi API, thứ tự thực hiện và tiêu chí bàn giao để agent bắt đầu. Các nguồn cuối tài liệu là bổ trợ; không cần đọc lại toàn bộ lịch sử chat.

## 1. Đọc trước khi triển khai

### 1.1. Đúng thư mục và đúng nền mã

```text
Thư mục làm việc: /Users/thien/Documents/School/Luận văn/web_app
Frontend:         apps/web
Backend:          src/meeting_backend
Core AI/Word:     src/meeting_pipeline
```

- `web_app` là worktree riêng, không phải thư mục frontend thuần. Checkout gốc bên ngoài còn chứa demo cũ; không sửa demo cũ cho nhiệm vụ này.
- Tại lúc lập plan: nhánh `codex/web-mongodb-upgrade`, HEAD `27c67aa`; có nhiều thay đổi **chưa commit** về pipeline, timeline, frontend và backend. Chúng là nền hiện hành, cần được giữ lại. HEAD không đại diện đầy đủ cho tính năng đang có.
- Khi bắt đầu, đọc `AGENTS.md` có áp dụng, ghi nhận `git status`, diff và file untracked liên quan. Không reset, clean, stash, checkout đè hoặc dựng lại từ HEAD làm mất thay đổi có sẵn.
- Giữ MongoDB, dữ liệu cuộc họp, audio, mẫu, model cache và các symlink runtime hiện tại. Không reset/import lại dữ liệu để làm giao diện mới hoạt động.
- Phạm vi thực hiện là local. Không tự commit, push, deploy hoặc gửi dữ liệu cuộc họp tới dịch vụ tham chiếu.

### 1.2. Nền công nghệ đã chọn

React 19 + TypeScript + Vite + Tailwind CSS 4 + React Router + TanStack Query; Radix/shadcn, Lucide, Sonner và Geist local. `components.json` đang dùng `radix-nova`, CSS variables và alias `@/`.

**Giữ nền này.** Dùng các primitive qua `radix-ui` và component shadcn hiện có. Không khởi tạo lại shadcn hoặc chép một template đè lên app. Untitled UI, Notta và các sản phẩm khác là tham chiếu bố cục/tương tác; không mang nguyên một hệ theme, router hoặc xác thực khác vào Minda.

### 1.3. Các khả năng phải kế thừa

Đã thấy trong mã và tài liệu hiện tại; phải kiểm tra lại khi bắt đầu, không coi là đã nghiệm thu:

- Nguồn audio nhiều hàng, file nối tiếp, điểm vào/ra, khoảng nghỉ, các mốc và khoảng chưa xác định.
- Wizard có nháp theo tài khoản; danh sách cuộc họp lọc tại API trước phân trang và giữ URL.
- Lời chép tìm/lọc/phân trang, sửa có phiên bản, người nói và nghe đối chiếu.
- Một player dùng chung; panel chia độ rộng; sửa biên bản tại mục; preview Word và zoom.
- Xác thực, CSRF, ownership, role admin/user, revision/conflict, job và active version.
- Nội dung chưa lưu được bảo vệ ở nhiều màn qua `useUnsavedForm`; cần phủ các form còn thiếu, nhất là rà mẫu.

Không thay thuật toán ASR/LLM/FCM, giới hạn xử lý hoặc định dạng Word trong nhiệm vụ giao diện. Nếu gặp lỗi core có sẵn, ghi bằng chứng và phạm vi ảnh hưởng; tiếp tục phần UI độc lập, không âm thầm sửa thuật toán hoặc che lỗi bằng dữ liệu giả.

## 2. Quyết định thiết kế bắt buộc

### 2.1. Một nhận diện xuyên suốt

**Minda là không gian làm việc lập biên bản.** Vùng nội dung, việc tiếp theo và căn cứ là trọng tâm.

| Tham chiếu | Chỉ lấy ý tưởng này | Chuyển về Minda như thế nào |
| --- | --- | --- |
| Notta | Đọc/sửa lời chép và nghe trong cùng workspace | Dùng typography, toolbar, player và panel chung của Minda |
| Fireflies | Thư viện cuộc họp, tìm/lọc, mở nguồn từ ghi chú | Dùng cùng bảng, bộ lọc, badge và deep link của Minda |
| MeetGeek/Fellow | Thư viện mẫu, đề mục, cấu trúc nội dung | Dùng cùng mẫu trang tài nguyên và trình rà mẫu của Minda |
| Granola | Vùng đọc/viết gọn và dễ tập trung | Giữ khoảng trống vừa đủ, chiều dài dòng đọc được, hành động phụ mở khi cần |
| Shadcn Admin | Shell, bảng và trang thiết lập | Là nền bố cục; giữ router, API, quyền và thương hiệu hiện có |

Mọi màn phải dùng cùng token, bộ icon, quy tắc nút, form, trạng thái và điều hướng. Không có trang dùng màu tím của template, trang khác dùng xanh dương hoặc một kiểu bo góc riêng.

### 2.2. Nguyên tắc bố trí

1. Mỗi trang có một H1, một mô tả ngắn khi thật sự cần và tối đa một hành động primary trong header. Nhóm công cụ chỉnh sửa có thể có primary riêng theo ngữ cảnh.
2. Header → toolbar → nội dung → phân trang; cùng vị trí tương đối trên các trang cùng loại.
3. Một lớp surface chính; không lồng card trong card chỉ để tạo khoảng cách. Thống kê chỉ hiện khi giúp chọn việc và lấy từ dữ liệu thật.
4. Nội dung thường dùng luôn thấy; cấu hình sâu và thao tác ít dùng đặt trong menu/panel phù hợp. Cảnh báo ảnh hưởng quyết định vẫn hiện cạnh nội dung.
5. Cùng một thao tác dùng cùng nhãn và vị trí. Dùng “Lời chép”, “Biên bản”, “Nguồn âm thanh”, “Căn cứ”, “Tạo lại”, “Xem trước Word”, “Tải Word” nhất quán.
6. Không thêm biểu đồ, ảnh minh họa lớn, khẩu hiệu, carousel, hiệu ứng nền hoặc thông số model vào vùng làm việc để lấp chỗ trống.

## 3. Hệ token chuẩn

Đây là giá trị thiết kế đã chọn cho lần triển khai. Tập trung định nghĩa tại một nơi, ánh xạ các biến Tailwind/shadcn sang đó; không rải mã màu trong từng trang.

### 3.1. Màu sắc — giữ nhận diện hiện tại

| Token Minda | Giá trị | Cách dùng |
| --- | --- | --- |
| `canvas` | `#f7f8fb` | Nền shell/sidebar |
| `surface` | `#ffffff` | Nội dung, menu, dialog |
| `surface-subtle` | `#f1f3f6` | Vùng phụ và hover nhẹ |
| `text` | `#1d2330` | Chữ chính |
| `text-secondary` | `#596573` | Mô tả, metadata và nhãn phụ |
| `border` | `#e6e8ee` | Đường chia trang/bảng; không thay focus |
| `control-border` | `#7c8796` | Biên ô nhập khi cần ranh giới điều khiển rõ |
| `primary` / `on-primary` | `#20242c` / `#ffffff` | Nút hành động chính |
| `accent` / `accent-soft` | `#3f7159` / `#edf4ef` | Điểm nhấn thương hiệu, liên kết và trạng thái có căn cứ |
| `warning` / `warning-soft` | `#8a5b12` / `#fff8e8` | Cần rà/thiếu thông tin |
| `danger` / `danger-soft` | `#a12f3a` / `#fff1f2` | Lỗi, mâu thuẫn và thao tác phá hủy |
| `info` / `info-soft` | `#335b85` / `#eef5ff` | Thông tin xử lý |
| `focus` | `#3f7159` | Outline 2 px, offset 2 px |

Màu trạng thái luôn đi cùng chữ/icon. Không dùng độ mờ để làm nhạt chữ nội dung còn hiệu lực. Đã tính sơ bộ: chữ phụ trên canvas khoảng 5,60:1; các cặp trạng thái khoảng 5,05–6,43:1; trắng trên primary khoảng 15,55:1. Agent vẫn phải kiểm trên nền và trạng thái render thực tế, gồm hover/focus/disabled.

### 3.2. Chữ, kích thước và khoảng cách

| Thành phần | Quy tắc |
| --- | --- |
| Font | Geist local hiện có; hỗ trợ đầy đủ dấu tiếng Việt; không phụ thuộc font CDN |
| H1 trang | 26 px / 600, line-height 1,3; mobile 22 px |
| Tiêu đề section | 18 px / 600; tiêu đề mục 16 px / 500–600 |
| Body, bảng, form | 14 px / 400–500; line-height 1,5–1,6 |
| Lời chép và biên bản khi đọc/sửa | 16 px, line-height 1,65; không ép nhỏ để giữ hai cột |
| Metadata | 12 px; không dùng 9–11 px cho nội dung có ý nghĩa |
| Spacing | 4, 8, 12, 16, 24, 32, 48 px; giữa section 24 hoặc 32 px |
| Radius | Control 6 px; surface 10 px; dialog 12 px |
| Control | Cao 40 px; bản compact 32 px cho toolbar phụ; icon button 36 px desktop, vùng chạm 44 px trên màn cảm ứng |
| Icon | Lucide 18 px trong control, 20 px trong navigation; stroke thống nhất |
| Shadow | Menu/dialog một mức nhẹ; bảng và section thường dùng đường chia |
| Motion | Phản hồi 120–180 ms, dialog tối đa 200 ms; không loop/parallax; tôn trọng reduced motion |

Ngày chỉ có ngày hiển thị `dd/mm/yyyy`; thời điểm xử lý có giờ và múi giờ theo cấu hình. Không tự thêm giờ vào ngày họp. Thời gian audio dùng formatter hiện có, giữ khác biệt mốc chung/cục bộ/ước lượng/chưa xác định.

### 3.3. Logo và favicon do người dùng tự thiết kế

**Kết quả cần đạt:** người dùng thay ảnh hoặc sửa đường dẫn tại một cấu hình là cập nhật nhận diện trên public pages, login, sidebar user/admin và tab trình duyệt; không phải sửa JSX/CSS ở từng trang.

#### Bộ asset và cấu hình

```text
apps/web/public/branding/
  logo.svg                 # Logo đầy đủ/wordmark do người dùng bổ sung
  logo-mark.svg            # Biểu tượng vuông cho sidebar thu gọn/mobile
  favicon.svg              # Biểu tượng tab trình duyệt
  apple-touch-icon.png     # Tùy chọn; chỉ khai báo khi có file

apps/web/src/config/branding.ts    # Cấu hình thuần, dùng chung cho app và Vite
apps/web/src/components/brand.tsx  # Thành phần Brand duy nhất
```

Cấu hình đích tối thiểu:

```ts
export const branding = {
  name: "Minda",
  fullLogoUrl: null as string | null,
  markLogoUrl: "/branding/logo-mark.svg",
  faviconUrl: "/branding/favicon.svg",
  appleTouchIconUrl: null as string | null,
  assetVersion: "1",
};
```

- Khi chưa có ảnh đầy đủ, `fullLogoUrl=null`: `Brand` ghép biểu tượng hiện tại với chữ Minda như fallback. Tái sử dụng SVG hiện có tại `src/assets/minda.svg` làm `logo-mark.svg`/`favicon.svg` tạm, giữ thông tin giấy phép của asset đó. Không tạo request tới `logo.svg` hoặc Apple icon chưa có file.
- Khi người dùng cung cấp wordmark, đặt file và đổi `fullLogoUrl` tại đây. Logo đầy đủ đã có chữ thì không ghép thêm chữ Minda lần nữa.
- Chấp nhận SVG, PNG hoặc WebP cho logo. Đổi định dạng thì đổi đuôi đường dẫn trong cấu hình. Favicon dùng SVG/PNG/ICO tương ứng trình duyệt, không lấy logo chữ dài làm favicon.
- `assetVersion` dùng làm query cache-busting chung cho logo/favicon, ví dụ `?v=2`. Không gắn theo `Date.now()` mỗi render.
- Cấu hình thuần, không import React/DOM/secret; Vite có thể đọc cùng cấu hình để tạo metadata và các thẻ icon trong `index.html`. Không duy trì một URL favicon khác trong HTML và một URL khác trong app. Các link icon phải đúng định dạng; không khai báo Apple icon vắng mặt.

#### Quy tắc component Brand

- Mọi vị trí hiển thị nhận diện gọi cùng `Brand`, với variant `full` hoặc `mark` và size được định nghĩa sẵn.
- Public/header: logo cao tối đa 36 px, rộng tối đa 180 px; login cao tối đa 40 px, rộng tối đa 200 px; sidebar mở cao tối đa 32 px, rộng tối đa 160 px; rail/mobile dùng mark 32×32 px.
- Ảnh dùng `object-fit: contain`, giữ tỷ lệ, không crop, kéo giãn, đổi màu hoặc tự thêm nền che thiết kế người dùng. Khoảng giữ chỗ ổn định để ảnh tải không làm nhảy menu.
- Nếu ảnh lỗi: mark hiện fallback biểu tượng/chữ hiện tại; full logo chuyển về mark + tên. Không có biểu tượng ảnh hỏng, vòng lặp request hoặc layout bị sập.
- Link logo có tên truy cập theo ngữ cảnh, ví dụ “Minda — Tổng quan”; ảnh bên trong link tránh đọc tên hai lần. Logo không có link thì có alt phù hợp.
- Không hardcode lại `AudioLines`/chữ thương hiệu ở các page sau khi đã có `Brand`. `AudioLines` vẫn được dùng như icon nghiệp vụ audio ở nơi khác.

#### Phục vụ asset khi chạy bản build

Vite dev phục vụ `public/branding` nhưng backend FastAPI hiện chỉ mount `/assets` rồi có SPA fallback. Agent phải bảo đảm bản production phục vụ được **`/branding/*` từ `apps/web/dist/branding` trước SPA fallback**, đúng MIME type; asset không tồn tại trả 404 thay vì trả `index.html`. Chỉ mount thư mục branding của web build, không mở thư mục upload/artifact/model cache. Các asset đang được bundle qua `/assets` vẫn hoạt động trong quá trình chuyển đổi.

#### Hướng dẫn thay ảnh phải bàn giao

Ghi hướng dẫn ngắn ở cuối báo cáo triển khai hoặc `docs/BRANDING.md`, gồm:

1. Đặt wordmark vào `apps/web/public/branding/logo.svg` và mark/favicon vào các đường dẫn chuẩn. Khuyến nghị wordmark nền trong suốt; mark vuông, nguồn raster khoảng 512×512 px; favicon SVG vuông hoặc PNG 32/64 px; Apple icon 180×180 px nếu dùng. Đây là gợi ý xuất file, không ép tỷ lệ logo đầy đủ.
2. Lần đầu có wordmark: đặt `fullLogoUrl="/branding/logo.svg"`. Các lần sau cùng đường dẫn chỉ cần thay file; đổi định dạng hoặc tên file thì sửa cấu hình một chỗ.
3. Tăng `assetVersion` khi muốn cập nhật cache. Với frontend được FastAPI phục vụ, chạy lại `npm --prefix apps/web run build`; sau đó tải lại trang. Nêu cách reload mạnh/mở lại tab nếu trình duyệt còn giữ favicon cũ.
4. Chỉ rõ file cấu hình và các kích thước hiển thị; thay ảnh không cần sửa từng trang hoặc đổi dữ liệu backend. Không yêu cầu người dùng cung cấp logo trước để hoàn thành phần giao diện còn lại.

## 4. Shell và responsive

### 4.1. Khung dùng chung

- `PublicLayout`: header logo + Hướng dẫn + Trợ giúp + Đăng nhập; footer gọn có thông tin dữ liệu.
- `AuthLayout`: logo, form rộng tối đa 400 px, trợ giúp tài khoản; trang đăng nhập và setup cùng cấu trúc.
- `AppLayout`: sidebar, header 64 px, main; user và admin dùng cùng shell, thay menu theo quyền/khu vực.
- `MeetingLayout`: breadcrumb, tên họp và trạng thái, truy cập thông tin, banner job khi liên quan, bốn mục **Nguồn âm thanh / Lời chép / Biên bản / Lịch sử**.
- Nội dung trang danh sách tối đa 1440 px và căn giữa; trang thiết lập/đọc thông tin tối đa 960 px; văn bản đọc tối đa khoảng 760 px. Workspace dùng toàn bộ chiều rộng còn lại.
- Main padding desktop 24 px, mobile 16 px. Không có khung app bo góc lớn với lề ngoài chiếm diện tích làm việc.

### 4.2. Quy tắc theo chiều rộng

| Chiều rộng | Sidebar và header | Nội dung |
| --- | --- | --- |
| ≥1280 px | Sidebar 240 px, người dùng được thu còn 72 px; header 64 px | Bảng đầy đủ; workspace hai panel khi vùng nội dung đủ rộng |
| 1024–1279 px | Mặc định rail 72 px, có nhãn truy cập và tooltip; vẫn có tài khoản/đăng xuất | Toolbar wrap hợp lý; không giảm font |
| 768–1023 px | Sidebar chuyển drawer, header có nút menu | Workspace ưu tiên một vùng nội dung; vùng phụ mở riêng |
| <768 px | Header 56 px, drawer tối đa 280 px và luôn nằm trong viewport | Nội dung một cột; action wrap; form dễ chạm |

Quyết định hai panel dựa trên **chiều rộng vùng workspace**, không chỉ viewport: từ 960 px trở lên dùng tỷ lệ ban đầu 60/40, main tối thiểu 520 px và phụ tối thiểu 320 px; nhỏ hơn mở căn cứ bằng drawer/dialog. Tái sử dụng `split-pane.tsx`, giữ chỉnh bằng bàn phím.

Bảng và timeline được cuộn ngang trong vùng có nhãn riêng; toàn trang không tràn ngang. Bảng mobile giữ cột tên/trạng thái/hành động và mở chi tiết hàng; không ẩn mất dữ liệu mà không có đường xem lại. Nếu player sticky cao khoảng 56 px, phải có khoảng đệm để không che dòng cuối.

### 4.3. Điều hướng đã chốt

User: **Công việc** — Tổng quan, Cuộc họp, Cần rà soát, Tác vụ; **Tài nguyên** — Mẫu biên bản, Hồ sơ giọng, Thư viện biên bản; **Cá nhân** — Thùng rác, Thiết lập. Trợ giúp và tài khoản luôn truy cập được.

Admin: Tổng quan, Tài khoản, Cuộc họp, Tác vụ, Model & preset; Mẫu dùng chung, Sao lưu, Đánh giá, Nhật ký, Tình trạng hệ thống. Có lối về không gian cá nhân.

Không đưa các tab của một cuộc họp lên sidebar toàn app. Các deep link cũ `?tab=overview`, `?tab=speakers` tiếp tục hoạt động. Đổi query phải giữ các giá trị không liên quan, ví dụ `tab`, `view`, `job`, từ khóa và bộ lọc đang dùng.

## 5. Bộ component và năm mẫu bố cục

Xây hoặc chuẩn hóa các thành phần sau trước khi phủ mọi trang. Giữ facade `components/common.tsx` nếu cần để các trang cũ tiếp tục import khi di chuyển dần.

| Thành phần chung | Trách nhiệm |
| --- | --- |
| `Brand` + cấu hình `branding.ts` | Logo đầy đủ/thu gọn, fallback, alt và đường dẫn nhận diện tập trung; favicon cùng nguồn cấu hình |
| `PageHeader`, `SectionHeader` | Tiêu đề, metadata và action đúng thứ bậc |
| `Toolbar`, `FilterBar`, `Pagination` | Tìm/lọc trên URL, reset filter, số kết quả và phân trang |
| `DataTable`, `RowActions` | Cùng kiểu header/hàng/menu; semantic table; dữ liệu rỗng/lỗi |
| `StatusBadge`, `InlineNotice`, `ErrorState`, `EmptyState`, `Skeleton` | Cùng hệ trạng thái; không render raw error/JSON làm nội dung chính |
| `FormField`, controls, `FormActions` | Label, required, hint, field error, busy và lỗi chung |
| `Dialog`, `ConfirmDialog`, `Drawer`, `Tooltip` | Radix, focus trap/return, Escape và tên truy cập |
| `MeetingNavigation`, `VersionNotice`, `JobStatus` | Context cuộc họp, bản đang dùng/cũ và công đoạn thực |
| `ReviewAudio`, `EvidencePanel`, `SplitPane`, `DocumentPreview` | Kế thừa hành vi hiện có và chuẩn hóa phần nhìn |
| `UnsavedChangesGuard` | Tái dùng hook hiện có, phủ cả mẫu/hồ sơ/form quản trị có chỉnh sửa |

Năm mẫu:

1. **Danh sách:** PageHeader → FilterBar → bảng/list → Pagination. Áp dụng cuộc họp, jobs, biên bản, user và audit.
2. **Tài nguyên:** PageHeader → search/filter → grid/list gọn → trang chi tiết. Áp dụng mẫu và hồ sơ giọng.
3. **Workspace:** MeetingLayout → toolbar ngữ cảnh → vùng chính + vùng phụ cần thiết → player dùng chung.
4. **Form/thiết lập:** header → nhóm trường theo section → action lưu; form dài tối đa hai cột desktop, một cột mobile.
5. **Thông tin/ngoại lệ:** nội dung ngắn, nguyên nhân có thể hiểu, một đường tiếp tục/quay lại; cùng component trạng thái.

## 6. Danh mục màn hình bắt buộc

42 mục dưới đây gồm trang, tab, chế độ, hộp và trạng thái; không tạo 42 URL hoặc 42 mục menu. “Kế thừa” là đọc/sửa trên mã hiện tại, không dựng lại từ mock. Các ID dùng để theo dõi nghiệm thu.

### A. Giới thiệu và truy cập — 7 mục

| ID | Màn hình / route cuối | Nội dung và hành vi tối thiểu |
| --- | --- | --- |
| A01 | Giới thiệu `/welcome` | Công dụng, ba bước audio → rà lời chép → Word, ví dụ có ghi rõ, CTA “Mở ứng dụng”; không có số liệu khách hàng/chứng nhận tự đặt |
| A02 | Hướng dẫn `/guide` | Hướng dẫn đầy đủ một luồng, chuẩn bị file/mẫu, cách sửa và xuất, giới hạn lấy theo cấu hình hiện hành |
| A03 | Trợ giúp `/help` | Nhóm Audio, Mẫu/OCR, Lời chép, Biên bản, Tài khoản; tìm bài trên dữ liệu hướng dẫn local; link đúng route |
| A04 | Thông tin dữ liệu `/data-policy` | Nêu đúng dữ liệu ở máy chủ triển khai, quyền, xử lý, backup và xóa; không tuyên bố mọi dữ liệu chỉ ở trình duyệt/thiết bị người dùng |
| A05 | Đăng nhập `/login` | Kế thừa API; field error; sai mật khẩu khác lỗi kết nối; đăng nhập xong về safe `returnTo` |
| A06 | Setup `/setup` | Tạo admin đầu tiên khi `/auth/status` cho phép; hệ đã setup thì đưa về login hoặc app |
| A07 | Hỗ trợ tài khoản `/account-help` | Hướng dẫn nhờ quản trị viên cấp/cấp lại; không dựng form gửi email khi chưa có dịch vụ |

`/` tiếp tục là dashboard đã đăng nhập. Public pages truy cập được khi chưa đăng nhập và không chờ MongoDB/auth để hiển thị nội dung tĩnh. Tách public/protected route thay cho early-return Login che mọi URL. Phiên 401 khác lỗi mạng/503. `returnTo` chỉ nhận đường dẫn nội bộ bắt đầu bằng một `/`, từ chối `//`, URL ngoài và vòng lặp auth.

### B. Công việc — 11 mục

| ID | Màn hình / route | Nội dung và hành vi tối thiểu |
| --- | --- | --- |
| B01 | Tổng quan `/` | Tối đa ba chỉ số hữu ích, công việc cần tiếp tục, họp gần đây; click số liệu mở filter đúng |
| B02 | Cuộc họp `/meetings` | Tên/ngày/trạng thái/cập nhật/hành động; search/status/page trên URL; lọc trước phân trang |
| B03 | Tạo họp `/meetings/new` | Bốn bước hiện có: thông tin → nguồn → hồ sơ → mẫu/xác nhận; giữ nháp và thứ tự file; nói rõ file cần chọn lại sau reload |
| B04 | Nguồn `?tab=sources` | Kho file, track và clip thật; nhập mốc/khoảng nghỉ; kéo và thao tác nút tương đương; save/conflict/busy rõ |
| B05 | Lời chép `?tab=transcript` | Search toàn lời chép, lọc người nói/cần rà, phân trang; click nghe, sửa và thấy phiên bản mới |
| B06 | Người nói `?tab=speakers` | Chế độ trong B05; đổi nhãn theo API hiện có, nghe mẫu đoạn; phân biệt người lạ, chưa xác định và nói chồng |
| B07 | Biên bản `?tab=minutes` | Nội dung/sửa tại mục, căn cứ, preview/zoom, template/options, stale/review và tải đúng version |
| B08 | Lịch sử `?tab=history` | Danh sách version, bản đang dùng, đối chiếu, khôi phục theo API; giữ nguồn của version đang xem |
| B09 | Thông tin `?tab=overview` | Metadata, thành phần và quản lý; cảnh báo thay đổi cần xử lý lại; bảo vệ draft |
| B10 | Cần rà `/review` | Gom việc cần rà theo quyền, có lý do và nút mở đúng tab/version; nguồn API mục 9 |
| B11 | Tác vụ `/jobs` | Jobs của chính user, state/stage/ngày; filter/pagination; lỗi, cancel/retry và mở tài nguyên liên quan |

### C. Tài nguyên và cá nhân — 8 mục

| ID | Màn hình / route | Nội dung và hành vi tối thiểu |
| --- | --- | --- |
| C01 | Mẫu `/templates` | Search, riêng/chung, trạng thái, loại file, mô tả/trường; CTA “Nhập mẫu” |
| C02 | Nhập mẫu `/templates/new` | Trang upload có danh sách định dạng/giới hạn đúng; gửi API hiện có rồi chuyển C03 theo dõi chuẩn hóa/OCR và duyệt |
| C03 | Chi tiết mẫu `/templates/:id` | Trường/đề mục + bản gốc/Word; sửa có draft guard; lưu → nhận diện lại → duyệt đúng bản; trạng thái job |
| C04 | Hồ sơ giọng `/voices` | Danh sách hồ sơ, số mẫu/chất lượng/trạng thái; tạo hồ sơ bằng hộp chung |
| C05 | Chi tiết giọng `/voices/:id` | Tên/thông tin, nghe từng mẫu, thêm mẫu, archive theo API; không tự thêm chức năng sửa embedding/chia người nói |
| C06 | Thư viện biên bản `/documents` | Một hàng cho bản biên bản đang active của mỗi họp; tìm/lọc reviewed/stale; mở B07 hoặc B08; tải đúng version |
| C07 | Thùng rác `/trash` | Họp đã xóa mềm, ngày/trạng thái và khôi phục; không thêm xóa vĩnh viễn hoặc trash mẫu/giọng chưa có API |
| C08 | Thiết lập `/settings` | Nhóm tài khoản/bảo mật và tùy chọn hỗ trợ thực; preset AI thuộc admin; không có toggle vô hiệu về nghiệp vụ |

### D. Quản trị — 10 mục

| ID | Màn hình / route | Nội dung và hành vi tối thiểu |
| --- | --- | --- |
| D01 | `/admin` | Số liệu vận hành thật, queue, worker, dung lượng và link tới vấn đề |
| D02 | `/admin/users` | Search/role/active; tạo, khóa, role, reset password; hộp chi tiết dùng cùng form/table |
| D03 | `/admin/meetings` | Metadata toàn hệ thống, owner/state/trash; không tự mở nội dung riêng của user khác |
| D04 | `/admin/jobs` | Search/filter, stage/state, lỗi/log, hành động hợp lệ và audit; nêu rõ phạm vi dữ liệu đang tải |
| D05 | `/admin/models` | Preset thường dùng/nâng cao, model/công cụ có sẵn, lưu revision; ghi hiệu lực tới tác vụ mới |
| D06 | `/admin/templates` và các route con `new`, `:id` | Mẫu chung, nhập/duyệt/quản lý theo quyền; dùng lại C01–C03 nhưng giữ shell/menu admin khi mở chi tiết |
| D07 | `/admin/backups` | Tạo backup, kết quả tải, khôi phục tới DB/root riêng; tiến độ và lỗi thực |
| D08 | `/admin/experiments` | Đánh giá theo reference thật; giữ metric/phạm vi/nguồn, không tự thêm biểu đồ hoặc điểm chưa có dữ liệu |
| D09 | `/admin/audit` | Nhật ký, filter/chi tiết, timestamp/actor/resource; log kỹ thuật không chứa token/mật khẩu |
| D10 | `/admin/system` | Worker heartbeat, queue, OCR, preview tools, model và storage; dùng overview/capabilities/health hiện có khi đủ |

### E. Trạng thái phục hồi — 6 mục

| ID | Trạng thái | Hành vi tối thiểu |
| --- | --- | --- |
| E01 | 404 | Route không tồn tại và tài nguyên không tìm thấy; có đường về phù hợp |
| E02 | 403 | Trạng thái tại route admin hoặc trong action; không tiết lộ tài nguyên riêng bị ẩn bằng 404 |
| E03 | Hết phiên | Giữ safe return path/draft phù hợp; login lại; xóa cache theo tài khoản khi đổi người dùng |
| E04 | API mất kết nối | Retry, trạng thái giữ nội dung đã có; không giả thành sai mật khẩu hoặc xóa draft |
| E05 | 409 / chưa lưu | Giữ phần người dùng nhập, cho xem bản mới/đối chiếu hoặc bỏ draft có xác nhận; không tự lưu bằng revision mới |
| E06 | Worker gián đoạn | `running` được lưu không đồng nghĩa đang chạy; hiện heartbeat và cách khắc phục thực; chỉ có “Tiếp tục” khi backend hỗ trợ checkpoint |

## 7. Ba màn hình chuẩn phải làm trước

Ba màn này là chuẩn hình thức để phủ phần còn lại, không phải mốc dừng để xin chọn lại template.

### 7.1. Danh sách cuộc họp

```text
Cuộc họp                                      [Tạo cuộc họp]
[Tìm cuộc họp................] [Trạng thái] [Bộ lọc thêm]
Tên cuộc họp        Ngày họp        Trạng thái      Cập nhật    ...
...
Số kết quả                                          Trước / Sau
```

Tìm kiếm giữ cơ chế submit hiện có; đổi filter reset về trang 1. “Không có cuộc họp” và “Không có kết quả lọc” dùng thông điệp/action khác nhau. Tên dài wrap tối đa hai dòng, có đường xem tên đầy đủ; metadata không đẩy action ra ngoài viewport.

### 7.2. Lời chép

```text
Cuộc họp > Tên họp                    [Trạng thái] [Thông tin]
Nguồn âm thanh | Lời chép | Biên bản | Lịch sử
[Tìm trong lời chép.......] [Người nói] [Chỉ phần cần rà]
Mốc + người nói        Nội dung lời chép       [Nghe] [Sửa]
...
Player chung: nguồn/đoạn, Play/Pause, thời điểm, tốc độ
```

Khi sửa, tập trung vào một đoạn; hiện nguồn/version và trạng thái thời gian. Polling không dựng lại input, đổi caret, phát lại animation hoặc mất lựa chọn. Sửa chữ không tự tạo timestamp mới. Khi không có clip khả dụng, nêu lý do thay vì nút nghe hỏng.

### 7.3. Biên bản

```text
Tên họp / Biên bản                     [Cần rà] [Tải Word]
[Nội dung | Xem trước Word]    [Cấu hình/Tạo lại] [Thao tác khác]
Nội dung theo đề mục 60%               Căn cứ / phiên bản 40%
  Tên trường / trạng thái                Lời phát biểu gốc
  Giá trị đọc được                       Người nói + mốc
  [Sửa] [Xem căn cứ]                      [Nghe đối chiếu]
```

- Mặc định đọc nội dung, sửa tại mục. Không mở nhiều editor độc lập nếu có thể làm người dùng bỏ sót phần chưa lưu.
- Căn cứ đi theo version nguồn của biên bản, không tự thay bằng transcript mới nhất. Cảnh báo khi nguồn mới hoặc field cần đối chiếu lại.
- “Xem trước Word” dùng renderer hiện có; fit-width, zoom 50–200%, bước 10%, chuyển trang, tải ảnh lỗi/thử lại. Không render một bản HTML giống Word rồi gọi đó là preview file xuất.
- Tải bản cũ vẫn phải thể hiện rõ tên/version/stale; không làm người dùng tưởng vừa tải nội dung nháp chưa được worker công bố.
- Đổi thể thức và tạo lại nội dung là hai hành động riêng về tác động. Các trường sửa tay vẫn phải tuân theo quy tắc giữ/đối chiếu của backend; không dùng styling để coi tất cả là đã có căn cứ.

## 8. Trạng thái, quyền và khả năng tiếp cận

| Trạng thái | Chuẩn xử lý chung |
| --- | --- |
| Loading đầu | Skeleton đúng cấu trúc; không nhảy giữa rỗng và có dữ liệu |
| Refetch nền | Giữ nội dung, focus và scroll; chỉ báo cập nhật nhỏ khi cần |
| Form invalid | Lỗi cạnh trường, summary khi nhiều lỗi, focus trường đầu; giữ `error.fields` từ API |
| Saving/job queued | Action disabled có nhãn rõ; giữ draft tới khi nhận xác nhận; tạo job chưa đồng nghĩa Word đã cập nhật |
| Error | Thông điệp theo thao tác, request ID trong chi tiết, retry khi an toàn |
| Busy/trash/stale | Nêu lý do action bị chặn và đường khắc phục; không chỉ dùng disabled không giải thích |
| Chưa có căn cứ/nói chồng | Giữ nhãn nghiệp vụ và nguồn gốc; không dùng nhãn thành người tham gia |

Kiểm quyền cả route lẫn API. Mọi danh sách cá nhân đều giới hạn owner. Admin quản trị metadata không mặc định được đọc audio/transcript/Word riêng của người khác. Artifact vẫn qua endpoint có kiểm quyền. Mutation giữ CSRF và revision/CAS; không thay bằng lưu đè lạc quan.

Dùng landmark, label, H1, `aria-current` cho navigation. Modal/drawer có tên, giữ focus, Escape và trả focus; không có điều khiển player ngoài dialog khiến người dùng phải vượt focus trap. Timeline có thao tác bằng nút/nhập thay cho kéo. Dấu trạng thái không chỉ dựa vào màu; cảnh báo động dùng `role=status/alert` phù hợp.

Mục tiêu kiểm chữ thường ≥4,5:1; chuẩn nội bộ control trên cảm ứng 44×44 px. Đây là lựa chọn thiết kế của Minda; WCAG 2.2 AA về kích thước mục tiêu có ngưỡng và ngoại lệ riêng, không mô tả 44 px là ngưỡng AA bắt buộc.

## 9. Phạm vi API bổ sung cho trang mới

Đọc OpenAPI/router thực tế trước khi viết. Tên dưới đây là **hợp đồng dự kiến**, chưa tồn tại chỉ vì được ghi trong plan. Giữ endpoint và dạng response cũ để frontend hiện tại không vỡ trong quá trình chuyển đổi.

### 9.1. Nhóm đọc `workspace` mới

Thêm module đọc nhỏ dưới `src/meeting_backend/modules/workspace/`, router prefix `/workspace`, include cùng prefix `/api/v1` như các module hiện có. Các đường dẫn trong bảng dưới là URL API đầy đủ. Không gọi model hoặc tạo artifact khi đọc danh sách. Dùng DTO tối thiểu, truy vấn có owner, filter trước phân trang, sort ổn định và index phù hợp.

| Endpoint dự kiến | Hợp đồng tối thiểu |
| --- | --- |
| `GET /api/v1/workspace/review?q=&kind=all&page=1&limit=30` | Một item cho một resource cần rà, gộp `reason_codes`; thông tin resource, target tab, version liên quan, cập nhật và số phần cần rà nếu có căn cứ. `kind`: `all`, `minutes`, `transcript`, `templates` |
| `GET /api/v1/workspace/documents?q=&review=all&page=1&limit=30` | Một item cho active minutes của mỗi meeting thuộc owner, chưa trashed; title/meeting/version/status/updated_at và tham chiếu artifact có quyền. `review`: `all`, `reviewed`, `needs_review`, `stale` |
| `GET /api/v1/workspace/jobs?q=&state=&kind=&page=1&limit=30` | Jobs của owner; filter trước pagination; trả stage/state/error/times/resource và hành động backend cho phép |

Response danh sách chung: `{items, total, page, limit}`; `limit` 1–100, mặc định 30. Không đếm/tìm trên 30 item đã tải rồi gọi đó là kết quả toàn bộ. Không tải toàn bộ transcript của từng họp theo kiểu N+1 để dựng trang tổng hợp.

Định nghĩa cần dùng nhất quán:

- `minutes_stale`: field stale hoặc revision nguồn của version không khớp input hiện tại; giữ lý do nếu có.
- `minutes_unreviewed`: active minutes khác reviewed version; reviewed chỉ hợp lệ khi không stale.
- `transcript_needs_review`: đếm cờ hiện có ở **active transcript**, không tự suy từ một ngưỡng confidence mới.
- `template_needs_review`: mẫu thuộc owner đang cần duyệt; mẫu shared của người khác không biến thành nhiệm vụ user được quyền duyệt.
- Link queue có thể mở các phần liên quan; không tự thêm mutation “Đánh dấu hoàn tất tất cả”. Mỗi phần dùng hành động rà hiện có.
- Documents không nhân bản nội dung/version và không coi facts draft là file Word đã công bố; lịch sử đầy đủ vẫn ở B08.

### 9.2. Hồ sơ giọng và diagnostics

- Bổ sung `GET /api/v1/speakers/{speaker_id}` nếu chưa có, kiểm owner/trash và trả samples cùng metadata tối thiểu. Dùng các mutation hiện có cho thêm mẫu/archive; không cần thêm API đổi thuật toán hoặc embedding.
- `/admin/system` trước hết dùng `/admin/overview`, `/capabilities`, `/health`; chỉ thêm DTO diagnostics read-only nếu thiếu dữ liệu thực sự cần hiển thị. Không lộ secret, environment hoặc full log cho user thường.
- API `/jobs` hiện trả tối đa 100 bản ghi dạng array; không thay response thành object làm hỏng notifications. Trang mới dùng endpoint có pagination riêng ở trên.
- Các bảng admin hiện có dùng API hiện có. Nếu thêm tìm/lọc toàn tập hoặc phân trang trên bảng đang giới hạn dữ liệu, mở rộng API tương ứng và có test; không diễn đạt bộ lọc cục bộ như tìm toàn hệ thống.

### 9.3. Giới hạn phạm vi

Không thêm đăng ký công khai, email delivery, team sharing, calendar sync, CRM, billing, chat xuyên cuộc họp hoặc tiếp tục inference theo checkpoint chỉ để làm đầy trang. Mỗi trang trong catalog vẫn phải có công việc thực: hướng dẫn đúng, đọc dữ liệu thật hoặc dùng mutation đã hỗ trợ. Nếu một chức năng cần backend lớn ngoài mục 9, ghi thành dependency cụ thể, không dựng nút giả hoặc báo thành công giả.

## 10. Bố trí mã và di chuyển CSS

```text
apps/web/src/
  app.tsx                         # Compose routes/layout; tránh chứa tất cả page
  index.css                       # Tailwind/font/theme mapping
  config/branding.ts              # Logo, favicon, tên và phiên bản cache
  styles/
    tokens.css                    # Nguồn giá trị màu/chữ/spacing/radius duy nhất
    base.css                      # Chữ/focus và reset tối thiểu
    layout.css                    # Shell và responsive
    components.css                # Thành phần layout dùng chung
  components/
    ui/                           # Radix/shadcn primitives
    common.tsx                    # Facade tương thích khi tách component dần
    brand.tsx                     # Nhận diện thay ảnh tập trung
    layouts/                      # Public/Auth/App/Meeting
    review-audio.tsx, split-pane.tsx
  features/
    public/                       # welcome, guide, help, data policy
    auth/                         # login, setup, account help; auth context
    meetings/                     # list/new/sources/transcript/minutes/history
    review/  documents/  jobs/     # Các trang tổng hợp mới
    templates/  voices/  settings/ admin/
  lib/                            # API, types, timeline, unsaved, formatter
```

Đây là cấu trúc đích; chuyển theo phần, không tạo hàng loạt file rỗng. Có thể giữ barrel export cũ trong lúc di chuyển. Không dựng API client trùng hoặc QueryClient mới cho mỗi khu vực.

Asset nhận diện nằm trong `apps/web/public/branding/` theo mục 3.3; cập nhật `vite.config.ts`, `index.html` và static mount trong `src/meeting_backend/main.py` đúng phạm vi phục vụ web build.

`tokens.css` là nơi duy nhất gán giá trị token. `index.css` giữ ánh xạ Tailwind; xóa các định nghĩa `:root` cạnh tranh trong `styles.css`/`workspace.css` sau khi đã chuyển và kiểm. Thay mã màu bằng token; giữ style theo chức năng khi cần. `styles.css` cũ được gỡ sau khi các selector còn dùng đã được chuyển, không tiếp tục thêm override ở cuối file để vá từng trang. Giữ `motion.css` gọn cho các hiệu ứng còn dùng.

Tách auth context khỏi `app.tsx` nếu cần tránh import vòng. Giữ đúng thứ tự QueryClient/Router/AuthProvider và cơ chế `useBlocker`. Không đổi React Router sang router của template.

## 11. Thứ tự thực hiện và đầu ra từng bước

Khi người dùng giao thực hiện plan này, agent tiến hành liên tục các bước dưới đây. Không dừng sau dashboard mẫu rồi coi toàn hệ thống đã xong. Các mục chưa hoàn thành phải ghi đúng ID và lý do thực tế.

| Bước | Công việc và file trọng tâm | Điều kiện xong |
| --- | --- | --- |
| P0 | Đọc trạng thái, route/API; lưu baseline danh sách file/diff và kết quả check dưới artifact riêng | Phân biệt thay đổi có sẵn, lỗi baseline và phạm vi sửa; không đụng dữ liệu thật |
| P1 | Token, chữ, primitive, Brand/config/asset nhận diện, layout, toolbar, bảng và trạng thái; chuẩn hóa CSS | Cùng token; shell responsive; logo/favicon thay tập trung và được phục vụ đúng ở dev/build |
| P2 | A01–A07 và public/protected routing, giữ safe return path | Public mở được không cần login; auth lỗi đúng; deep link và quyền giữ nguyên |
| P3 | B02, B05, B07 làm ba màn chuẩn; tiếp tục B01/B03/B04/B06/B08/B09 | Đọc/sửa/nghe/preview làm được trên fixture thật; polling không mất draft/focus |
| P4 | C01–C05/C07/C08; phủ template guard và cùng form/state | Nhập/rà mẫu, quản lý giọng, thiết lập và khôi phục họp hoạt động; style thống nhất |
| P5 | API mục 9 + B10/B11/C06 và D10 | Danh sách tổng hợp thật, owner-safe, filter trước pagination; không N+1 transcript |
| P6 | D01–D09 và E01–E06; rà tất cả ID còn lại | Mỗi trang cùng mẫu bố cục; phục hồi lỗi và hành động có quyền được kiểm |
| P7 | Kiểm tra toàn hệ thống, responsive, accessibility, performance cơ bản; dọn CSS chết | Ma trận mục 12 đạt, có ảnh và báo cáo delta; không chỉ có ảnh trang trạng thái tốt |

Không ấn định số giờ hoặc hiệu năng đạt được trước khi đo. Nếu baseline lỗi core hoặc binary thiếu, ghi phạm vi và bằng chứng; vẫn hoàn tất phần giao diện có thể thực hiện độc lập. Không ghi “đạt” cho bước chưa chạy.

## 12. Kiểm tra và nghiệm thu

### 12.1. Lệnh kiểm tra

Chạy từ `web_app`; môi trường đã có, không cần tự cài lại toàn bộ model:

```bash
npm --prefix apps/web run check
npm --prefix apps/web run build
npm --prefix apps/web run format:check
.venv-backend/bin/python -m ruff check --no-cache src/meeting_backend tests/backend
.venv-backend/bin/python -m pytest tests/backend -q --tb=short
```

Nếu thay module timeline/transcript/minutes/backend liên quan, chạy thêm kiểm thử hiện có đúng phần đó. Thêm test có ý nghĩa cho API tổng hợp, quyền, phân trang, auth redirect và bảo vệ draft; không viết snapshot/test chỉ lặp lại CSS.

Test/backend và browser mutations dùng database `meeting_app_ui_test_<UUID>` cùng data root riêng, chỉ cleanup đúng database của lượt chạy. Không thử backup/restore/xóa/reset password lên dữ liệu ứng dụng đang dùng. Credentials lấy từ env/file tạm, không ghi vào source, ảnh hoặc báo cáo.

Script `scripts/backend/browser_smoke.py` hiện có là điểm bắt đầu; đọc và cập nhật selector/flow khi nhãn hoặc route đổi. Không bỏ assertion quan trọng chỉ để script xanh. Kiểm preview phải xác nhận ảnh thật đã giải mã, không chấp nhận placeholder thay tài liệu.

### 12.2. Ma trận kịch bản bắt buộc

| ID kiểm | Kịch bản | Kết quả cần thấy |
| --- | --- | --- |
| T01 | Public → login → deep link; API offline; phiên hết hạn | Nội dung public hoạt động, lỗi đúng và quay lại công việc an toàn |
| T02 | User thường vào admin và đọc resource/artifact người khác | UI/API từ chối; dữ liệu riêng không bị lộ |
| T03 | Tạo nháp wizard, chuyển bước/rời trang/reload, quay lại | Metadata được giữ đúng user; nói rõ file cần chọn lại; không trộn draft giữa tài khoản |
| T04 | Upload audio fixture nhiều nguồn, sắp track/clip, nhập mốc và khoảng nghỉ | GET sau thao tác đúng dữ liệu; audio gốc giữ nguyên; không đổi `null` thành mốc giả |
| T05 | Search/filter/pagination lời chép, nghe clip, sửa và polling | Không mất nội dung/focus/caret; không phát nhiều audio; giữ version và mốc nguồn |
| T06 | Mẫu PDF/scan, sửa field, rời trang, lưu/duyệt | Guard hoạt động; rõ gốc/Word và version đã duyệt; file lỗi có hướng khắc phục |
| T07 | Biên bản đọc/sửa, mở căn cứ, preview hai trang, lỗi ảnh rồi retry | Đúng nguồn/version, sửa không mất; ảnh render thật, zoom và nút page đúng |
| T08 | 409 trong lúc sửa; transcript/timeline mới làm biên bản stale | Giữ draft; thấy bản mới và stale; không đánh dấu reviewed sai |
| T09 | Hủy/lỗi/interrupted/heartbeat hết hạn | Trạng thái rõ, hành động phục hồi đúng khả năng backend, không progress/ETA giả |
| T10 | `/review`, `/documents`, `/jobs` với hơn 30 item và hai owner | Total/filter/page đúng toàn tập; không đọc chéo owner; deep link đúng phần |
| T11 | User/admin toàn route, log, preset, backup/restore trên fixture | Mutation có CSRF/revision; thông báo và dữ liệu sau reload đúng |
| T12 | Bàn phím, modal/drawer, rail/sidebar, reduced motion | Tên truy cập, focus trap/return và nút thoát hoạt động; không che action/player |
| T13 | Thay logo đầy đủ/mark/favicon bằng asset kiểm thử, rồi khôi phục placeholder | Đổi tại một cấu hình; giữ tỷ lệ ở public/login/sidebar/mobile; favicon cập nhật theo version; asset build đúng MIME, file thiếu 404 và fallback không làm sập layout |

### 12.3. Kiểm hình thức và kích thước

- Mở tất cả route trong catalog ở desktop 1440×900; không lỗi JS, không trang chết, không link quay vòng. Các chế độ/hộp được kiểm trong route chứa chúng.
- Ba màn chuẩn B02/B05/B07 kiểm thêm 1280×800, 1024×768, 768×1024, 390×844 và 360×800. Kiểm nguồn, rà mẫu và bảng admin tối thiểu desktop + 390 px.
- So cạnh nhau ít nhất: danh sách họp, mẫu, user admin, lời chép, biên bản, settings. H1, toolbar, control, badge, khoảng cách và nền phải cùng quy tắc.
- Nội dung dài, tên tiếng Việt dài, không có dữ liệu, không kết quả tìm, lỗi API, busy, stale và thiếu căn cứ đều có mẫu kiểm.
- Chỉ bảng/timeline có cuộn ngang cục bộ khi cần; toàn app không tràn ngang ở các chiều rộng đã nêu. Text zoom 200% vẫn tìm được nội dung và action.
- Kiểm đọc bằng bàn phím và đo tương phản trên giao diện thực; không tuyên bố tuân thủ WCAG đầy đủ chỉ từ một lần chạy tự động.

### 12.4. Điều kiện bàn giao cuối

- [ ] Tất cả A01–E06 được thực hiện và có trạng thái kiểm rõ; không ghi trang đã xong chỉ vì có route/placeholder.
- [ ] Không có nút giả, dữ liệu thống kê giả, biểu đồ mẫu bị lẫn vào sản phẩm hoặc hành động luôn báo thành công.
- [ ] Một hệ token, font, icon và component; không còn style template riêng lẻ hoặc chồng override không kiểm soát.
- [ ] Logo/favicon do người dùng thay được qua asset + cấu hình tập trung; có fallback, không phụ thuộc ảnh mới để chạy app và đã bàn giao hướng dẫn thay/rebuild/cache.
- [ ] Các luồng audio → lời chép → biên bản → Word và mẫu → duyệt → sử dụng được kiểm với fixture.
- [ ] Quyền, revision, stale, active version, job và căn cứ được bảo toàn.
- [ ] Kết quả build/check/test/browser có lệnh, ngày, phạm vi, lỗi baseline và lỗi phát sinh phân biệt rõ.
- [ ] Có ảnh đại diện user/admin/public, desktop/mobile và trạng thái phục hồi; ghi rõ fixture hay dữ liệu thật.
- [ ] Báo cáo cuối nêu file đổi, API thêm, cách chạy và phần còn vướng cụ thể; không tự commit/push/deploy.

Lưu bằng chứng dưới `artifacts/ui-unified-2026-11-06/` hoặc thư mục có timestamp tương đương. Không đưa password/token hoặc dữ liệu cuộc họp thật vào artifact. Chỉ tạo báo cáo triển khai sau khi làm và kiểm, không sửa plan thành tuyên bố đã hoàn thành.

## 13. Prompt bàn giao có thể sao chép

```text
Bạn là agent thực thi giao diện cho dự án Minda. Hãy đọc và thực hiện toàn bộ:
docs/PLAN_UI_UNIFIED_MINDA_2026-11-06.md

Thư mục làm việc đúng:
/Users/thien/Documents/School/Luận văn/web_app

Mục tiêu: giao diện chuyên nghiệp, gọn, tối giản, thống nhất toàn hệ thống theo
token, component, bố cục và danh mục A01–E06 trong plan. Kế thừa toàn bộ thay đổi
chưa commit hiện có. Tham chiếu Notta/Fireflies/MeetGeek/Fellow/Granola về luồng
và cấu trúc; dùng Radix/shadcn hiện có để tạo một hệ thiết kế Minda duy nhất.
Logo và favicon do tôi tự thiết kế: triển khai Brand/config/asset theo mục 3.3,
để tôi thay ảnh dễ dàng tại một chỗ; giữ nhận diện tạm, không tự tạo logo mới.

Đọc trạng thái thực tế trước, thực hiện tuần tự P0–P7, bổ sung API read-only đúng
phạm vi mục 9 và kiểm theo mục 12. Không dừng ở mockup hoặc dashboard mẫu.
Không sửa thuật toán AI/Word, không reset dữ liệu, không làm mất mã đang sửa,
không chép template đè app và không tự commit/push/deploy.

Tiến hành các quyết định triển khai thường lệ trong phạm vi plan. Nếu gặp trở
ngại ngoài phạm vi, ghi ID, bằng chứng và phần phụ thuộc; hoàn tất các phần
độc lập còn lại. Bàn giao kết quả thực, ảnh kiểm tra, lệnh/check đã chạy và các
mục chưa hoàn thành cụ thể; không báo đạt cho kiểm thử chưa chạy.
```

## 14. Nguồn tham chiếu

- [Notta — bố cục bản ghi](https://support.notta.ai/hc/en-us/articles/37437047511195-Records-detail-page-screen-layout-and-functions-Notta-Web)
- [Fireflies — thư viện cuộc họp](https://guide.fireflies.ai/articles/4827382971-learn-about-fireflies-notebook)
- [MeetGeek — mẫu cuộc họp](https://support.meetgeek.ai/en/articles/6021910-meeting-templates-quickstart-guide)
- [Fellow — mẫu ghi chú](https://help.fellow.ai/en/articles/2423913-meeting-note-templates)
- [Granola](https://www.granola.ai/), [Shadcn Admin](https://github.com/satnaing/shadcn-admin), [shadcn/ui](https://github.com/shadcn-ui/ui)
- [W3C — tương phản chữ](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [kích thước mục tiêu](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [modal dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

Tài liệu dự án bổ trợ: [nghiên cứu toàn hệ thống 06/11](reports/UI_FULL_SYSTEM_RESEARCH_2026-11-06.md), [triển khai 27/10](reports/FRONTEND_IMPLEMENTATION_2026-10-27.md), [audit 02/11](reports/SYSTEM_AUDIT_2026-11-02.md). Đọc mã hiện tại khi các tài liệu lịch sử khác trạng thái thực tế.
