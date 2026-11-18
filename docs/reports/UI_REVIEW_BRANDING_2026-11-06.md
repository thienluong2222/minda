# Kiểm tra giao diện và tích hợp nhận diện Minda

Ngày kiểm tra: **06/11/2026**. Phạm vi: giao diện mới sau khi agent triển khai, tích hợp logo người dùng đã chốt và sửa các lỗi hiển thị/tương tác phát hiện trong lần kiểm tra này.

## 1. Kết quả

- Đã tích hợp logo chữ, biểu tượng và favicon chính thức qua cấu hình nhận diện tập trung.
- Bản build hiện tại đã cập nhật; TypeScript, Prettier và lint backend đạt; **44 kiểm thử backend đạt**.
- Playwright trên Chrome thực hiện **78 lượt điều hướng**, gồm **36 tổ hợp trang/viewport** tại 1440×900, 1280×800, 1024×768, 768×1024, 390×844 và 360×800.
- Lượt cuối: không ghi nhận page error JavaScript, API 5xx, tràn ngang toàn trang, liên kết điều hướng bị cắt khỏi header, chữ hiển thị dưới 12 px hoặc mã database bị cắt trong các trang đã kiểm.
- Menu mobile: bố cục đúng; giữ focus qua 24 lần Tab, Escape đóng menu và trả focus về nút mở; chọn liên kết đóng menu và chuyển trang.
- Tài khoản user thường bị chặn ở khu vực admin. Dữ liệu thử dùng database riêng, server thử đã dừng và database/thư mục tạm đã được dọn.

## 2. Bộ nhận diện đã gắn

Nguồn: thư mục `/Users/thien/Downloads/Minda/`. Nội dung ba SVG được giữ nguyên; đã đối chiếu byte giữa nguồn, `public/branding` và bản build `dist/branding`.

| File người dùng | File trong `apps/web/public/branding/` | Sử dụng |
| --- | --- | --- |
| `1.svg` | `logo.svg` | Wordmark ngang 2000×650, nền trong suốt; trang công khai, đăng nhập/khởi tạo, sidebar mở của user/admin và menu mobile |
| `3.svg` | `logo-mark.svg` | Biểu tượng vuông nền trong suốt; rail và header mobile |
| `2.svg` | `favicon.svg` | Biểu tượng nền sáng bo góc; tab trình duyệt |

`apps/web/src/config/branding.ts` đã bật `fullLogoUrl` và tăng `assetVersion` lên `"2"`. HTML build chỉ có một favicon link, trỏ tới `/branding/favicon.svg?v=2`. Apple Touch Icon vẫn để `null` vì chưa có asset riêng.

Kiểm tra HTTP qua FastAPI: cả ba file trả **200**, MIME **`image/svg+xml`**, nội dung đúng SVG; file không tồn tại trả **404**. Đã giả lập lỗi tải wordmark và lỗi cả wordmark/mark để xác nhận fallback hoạt động.

Hướng dẫn thay ảnh tiếp theo: [BRANDING.md](../BRANDING.md).

## 3. Lỗi đã sửa

| Vấn đề phát hiện | Thay đổi |
| --- | --- |
| Logo chưa có kích thước giữ chỗ trước khi tải | `Brand` dành sẵn khung theo context; ảnh dùng `contain`, căn trái và giữ tỷ lệ. Khi giữ request ảnh rồi cho tải tiếp, khung public luôn là 180×36 px, không đổi vị trí/kích thước |
| Menu mobile có icon/chữ rơi xuống dòng, khác sidebar | Cho panel mobile dùng chung các quy tắc menu với sidebar |
| Menu mobile không đóng bằng Escape và chưa giữ focus | Dùng Radix Dialog hiện có để quản lý focus trap, Escape, nút đóng và trả focus; đóng khi điều hướng hoặc chuyển sang viewport desktop |
| Liên kết header public bị chồng/cắt ở mobile và tablet 768 px | Bố trí logo và navigation thành các hàng có chiều cao tự nhiên dưới 1024 px; auth header cũng xếp lại trên mobile |
| CSS cũ còn 13 quy tắc cỡ chữ 7–8 px | Thay bằng token metadata 12 px; tăng độ rõ chữ phụ trên các thẻ thống kê |
| Tên database dài vượt cột thông tin | Dùng cột `minmax(0, 1fr)` và cho nội dung dài xuống dòng |
| Ô tìm kiếm chung bị ép hẹp, chồng lên công cụ trên mobile | Ẩn ô tìm kiếm chung và vùng tài khoản trống dưới 768 px; giữ thanh công cụ gọn. Tìm kiếm tại danh sách cuộc họp vẫn hoạt động |

File giao diện đã điều chỉnh trong lần này: `src/config/branding.ts`, `src/components/brand.tsx`, `src/components/layouts/index.tsx`, `src/styles/layout.css`, `src/styles.css` trong `apps/web`; cùng ba asset và tài liệu nhận diện. Các thay đổi agent đã có được giữ lại.

## 4. Kiểm tra đã chạy

| Lệnh / kiểm tra | Kết quả |
| --- | --- |
| `npm --prefix apps/web run check` | Đạt ở baseline; các build sau tiếp tục chạy `tsc --noEmit` |
| `npm --prefix apps/web run build` | Đạt trên mã cuối, đã xuất `apps/web/dist` |
| `npm --prefix apps/web run format:check` | Đạt trên mã cuối |
| `.venv-backend/bin/python -m ruff check --no-cache src/meeting_backend tests/backend` | Đạt |
| `.venv-backend/bin/python -m pytest tests/backend -q --tb=short` | 44 passed, 2 cảnh báo deprecation từ thư viện; không có lỗi |
| `git diff --check` trên các file tracked đã sửa | Đạt |
| Byte nguồn/public/dist, favicon HTML, MIME/404, ảnh lỗi và ảnh tải chậm | Đạt |
| Browser QA public/auth, user, admin D01–D10, tài nguyên, workspace, 404, phân quyền và responsive | Đạt trong phạm vi ghi tại mục 1 |

Fixture có lời chép, biên bản, mẫu và hồ sơ giọng giả lập. DOCX fixture được tạo và render thành trang PNG thật để cung cấp dữ liệu hợp lệ cho giao diện. Không dùng nội dung cuộc họp thật trong ảnh hoặc báo cáo.

Phạm vi nghiệm thu lần này là route, layout, nhận diện, responsive, bàn phím/fallback và hồi quy backend. Chất lượng suy luận AI từ bản ghi âm thực tế cần đợt kiểm định pipeline riêng.

## 5. Bằng chứng

- [Kết quả máy đọc — lượt cuối](../../artifacts/ui-logo-integration-2026-11-06/verification.json)
- [Phát hiện tự động trước các sửa lỗi đầu tiên](../../artifacts/ui-logo-integration-2026-11-06/verification-before-fixes.json)
- [Dashboard với logo chính thức](../../artifacts/ui-logo-integration-2026-11-06/screenshots/03-dashboard-desktop.png)
- [Admin desktop](../../artifacts/ui-logo-integration-2026-11-06/screenshots/07-admin-desktop.png)
- [Admin dạng rail](../../artifacts/ui-logo-integration-2026-11-06/screenshots/11-admin-rail.png)
- [Admin mobile sau sửa](../../artifacts/ui-logo-integration-2026-11-06/screenshots/09-mobile-admin.png)
- [Menu mobile sau sửa](../../artifacts/ui-logo-integration-2026-11-06/screenshots/10-mobile-drawer.png)
- [Menu mobile trước sửa](../../artifacts/ui-logo-integration-2026-11-06/screenshots/10-mobile-drawer-before-fix.png)
- [Trang công khai mobile sau sửa](../../artifacts/ui-logo-integration-2026-11-06/screenshots/09-mobile-welcome.png)

Có 14 ảnh của lượt kiểm tra cuối cùng; các ảnh có hậu tố `before-fix` là bằng chứng trước sửa. Việc tích hợp hoàn tất ở local, không commit/push/deploy.
