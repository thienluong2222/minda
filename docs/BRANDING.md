# Hướng dẫn thay thế Logo và Favicon cho Minda

Tài liệu này hướng dẫn cách thay thế bộ nhận diện (logo đầy đủ/wordmark, biểu tượng thu gọn và favicon) cho ứng dụng Minda mà không cần chỉnh sửa từng trang giao diện hay thay đổi dữ liệu backend.

---

## 1. Cấu trúc thư mục và file cấu hình

Toàn bộ tài nguyên nhận diện và cấu hình nằm tại hai vị trí duy nhất:

```text
apps/web/public/branding/
  logo.svg                 # Logo đầy đủ / wordmark chính thức
  logo-mark.svg            # Biểu tượng vuông cho sidebar thu gọn (rail) và mobile
  favicon.svg              # Biểu tượng tab trình duyệt
  apple-touch-icon.png     # Biểu tượng iOS/macOS (tùy chọn; chỉ khai báo khi có file thực tế)

apps/web/src/config/branding.ts    # Cấu hình nhận diện tập trung (dùng chung cho React + Vite HTML)
apps/web/src/components/brand.tsx  # Component hiển thị nhận diện dùng chung toàn ứng dụng
```

Bộ nhận diện chính thức hiện được cấu hình với `fullLogoUrl: "/branding/logo.svg"` và `assetVersion: "2"`:

| File đã tích hợp | File thiết kế người dùng cung cấp | Đặc điểm |
| --- | --- | --- |
| `logo.svg` | `1.svg` | Wordmark ngang 2000×650, nền trong suốt |
| `logo-mark.svg` | `3.svg` | Biểu tượng vuông 2000×2000, nền trong suốt |
| `favicon.svg` | `2.svg` | Biểu tượng vuông 2000×2000, nền xám sáng bo góc |

Các SVG giữ nguyên nội dung thiết kế của người dùng. Logo đầy đủ dùng trên trang công khai, xác thực và sidebar mở; biểu tượng dùng trên rail/mobile; favicon dùng trên tab trình duyệt.

Khi chưa có wordmark riêng (`fullLogoUrl: null`), component `Brand` tự động ghép biểu tượng `logo-mark.svg` cùng chữ **Minda** và không gửi request tới `logo.svg`.

---

## 2. Khuyến nghị kỹ thuật khi xuất file ảnh

1. **Logo đầy đủ / Wordmark (`logo.svg`, `.png` hoặc `.webp`):**
   - Nên xuất nền trong suốt (transparent), ưu tiên định dạng SVG.
   - Không bắt buộc tỷ lệ cố định; hệ thống tự co giãn theo `object-fit: contain` và giữ nguyên tỷ lệ gốc.
2. **Biểu tượng thu gọn (`logo-mark.svg`, `.png` hoặc `.webp`):**
   - Khung vuông 1:1 (nếu dùng ảnh raster PNG/WebP, khuyến nghị kích thước nguồn khoảng `512×512 px`).
3. **Favicon (`favicon.svg`, `.png` hoặc `.ico`):**
   - Khung vuông 1:1 (SVG vuông hoặc PNG `32×32 px` / `64×64 px`). Không dùng logo chữ ngang dài làm favicon.
4. **Apple Touch Icon (`apple-touch-icon.png` - tùy chọn):**
   - PNG vuông `180×180 px`. Chỉ cấu hình đường dẫn khi đã đặt file vào `apps/web/public/branding/`.

---

## 3. Kích thước hiển thị tự động theo vị trí

Component `Brand` dành sẵn khung chứa theo từng khu vực trước khi ảnh tải để giữ ổn định bố cục. Ảnh dùng `object-fit: contain`, căn trái và giữ nguyên tỷ lệ trong khung:

| Vị trí hiển thị (`context`) | Variant mặc định | Kích thước tối đa |
| --- | --- | --- |
| Header trang công khai (`public`) | `full` | Cao tối đa `36 px`, rộng tối đa `180 px` |
| Trang đăng nhập / khởi tạo (`login`) | `full` | Cao tối đa `40 px`, rộng tối đa `200 px` |
| Sidebar mở rộng (`sidebar`) | `full` | Cao tối đa `32 px`, rộng tối đa `160 px` |
| Sidebar thu gọn (`rail`) & Mobile (`mobile`) | `mark` | Vuông `32 × 32 px` |

> **Lưu ý:** Khi `fullLogoUrl` được khai báo và tải thành công, hệ thống chỉ hiển thị ảnh wordmark của bạn (không ghép thêm chữ `Minda` lần thứ hai). Nếu file ảnh bị lỗi đường dẫn hoặc hỏng, component tự động chuyển về biểu tượng dự phòng + tên ứng dụng để không vỡ giao diện.

---

## 4. Quy trình thay ảnh và cập nhật cache

### Bước 1: Đặt file vào thư mục `apps/web/public/branding/`
Chép các file thiết kế của bạn vào `apps/web/public/branding/` (ví dụ `logo.svg`, `logo-mark.svg`, `favicon.svg`).

### Bước 2: Cập nhật `apps/web/src/config/branding.ts`
Mở file `apps/web/src/config/branding.ts` và chỉnh sửa:

```ts
export const branding = {
  name: "Minda",
  fullLogoUrl: "/branding/logo.svg",          // Đặt đường dẫn khi có wordmark (hoặc để null nếu chỉ dùng mark + chữ)
  markLogoUrl: "/branding/logo-mark.svg",     // Đổi đuôi (.png, .webp, .svg) nếu thay định dạng
  faviconUrl: "/branding/favicon.svg",        // Đường dẫn favicon (.svg, .png, .ico)
  appleTouchIconUrl: null as string | null,   // Ví dụ: "/branding/apple-touch-icon.png" khi có file
  assetVersion: "2",                          // Tăng số phiên bản (ví dụ "1" -> "2") để làm mới cache trình duyệt
};
```

- Nếu lần sau bạn chỉ ghi đè nội dung file cùng tên (ví dụ giữ nguyên `/branding/logo.svg`), bạn chỉ cần tăng `assetVersion` (ví dụ lên `"3"`).
- Nếu đổi định dạng file (ví dụ từ `.svg` sang `.png`), hãy cập nhật đúng phần mở rộng trong `branding.ts`.

### Bước 3: Kiểm tra hoặc Build lại cho môi trường Production (FastAPI)
- **Khi chạy Vite dev server (`npm --prefix apps/web run dev`):** Thay đổi có hiệu lực ngay sau khi lưu file và tải lại trang.
- **Khi chạy bản build qua FastAPI (`apps/web/dist`):** Chạy lệnh build để Vite xuất `dist/index.html` và sao chép `dist/branding/*`:
  ```bash
  npm --prefix apps/web run build
  ```

### Bước 4: Làm mới cache Favicon trên trình duyệt
Trình duyệt thường lưu cache favicon lâu hơn ảnh thông thường. Sau khi tăng `assetVersion` và build lại:
1. Thực hiện **Hard Reload** trên trình duyệt:
   - macOS: `Cmd + Shift + R`
   - Windows/Linux: `Ctrl + Shift + R` (hoặc `Ctrl + F5`)
2. Nếu tab hiện tại vẫn giữ icon cũ trong bộ nhớ phiên, hãy đóng tab đó và mở lại địa chỉ ứng dụng ở một tab mới.

