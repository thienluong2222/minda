# Sửa luồng xem tài khoản và cuộc họp trong admin — 17/10/2026

## Kết quả chẩn đoán

Database `meeting_app_dev` vẫn có **2 tài khoản và 2 cuộc họp**. Kiểm tra
chỉ đọc cho thấy API tài khoản trả đủ 2 bản ghi; không tái hiện lỗi mất tài
khoản trong database.

Các thiếu sót đã xác nhận:

- Chưa có API/trang danh sách cuộc họp toàn hệ thống: `/api/v1/admin/meetings`
  trả 404.
- Thẻ Tài khoản/Cuộc họp trên tổng quan chỉ có số lượng, chưa mở được danh sách.
- Tìm kiếm ở thanh đầu trang admin dẫn về `/meetings`, là danh sách cá nhân.
- Danh sách tài khoản chưa tự cập nhật, chưa có trạng thái tải/rỗng rõ ràng;
  tài khoản khóa dùng nhãn “Đã hủy”, dễ gây nhầm lẫn.

## Thay đổi

### Backend

- `modules/meetings/admin.py`: API `GET /api/v1/admin/meetings` dành riêng cho
  admin, trả metadata cuộc họp của mọi chủ sở hữu, tên/tên đăng nhập chủ sở
  hữu, số nguồn và tình trạng kết quả.
- Bộ lọc: từ khóa tên cuộc họp hoặc người sở hữu, `owner_id`, trạng thái,
  phạm vi thùng rác; phân trang ổn định, tối đa 100 dòng mỗi trang.
- `modules/users/router.py`: giữ dạng response danh sách hiện có; bổ sung
  lọc từ khóa/vai trò/hoạt động và số cuộc họp đang dùng/trong thùng rác cho
  từng tài khoản. Đếm bằng một truy vấn aggregate theo nhóm chủ sở hữu.
- Danh sách quản trị không trả nội dung ghi chú, transcript, tham chiếu file
  hay đường dẫn. Quyền workspace/file cá nhân vẫn theo chủ sở hữu.

### Giao diện

- Thêm **Cuộc họp** vào thanh điều hướng admin và trang danh sách riêng tại
  `/admin/meetings`.
- Thẻ số liệu trên tổng quan mở `/admin/users` và `/admin/meetings`.
- Tìm kiếm ở đầu trang admin dùng danh sách toàn hệ thống; đồng bộ từ khóa
  với ô tìm kiếm trong trang.
- Danh sách tài khoản có tìm kiếm, lọc, trạng thái tải/rỗng/lỗi, tải lại và
  tự cập nhật mỗi 5 giây. Phân biệt “Đang hoạt động” và “Đã khóa”.
- Nhấn số cuộc họp của tài khoản để lọc danh sách theo người sở hữu.
- Danh sách cuộc họp có bộ lọc phía server, phân trang, xem thông tin quản
  lý và tự cập nhật. Cuộc họp thuộc admin đang đăng nhập có nút mở workspace.
- Đã build lại frontend để launcher cổng 8010 phục vụ mã giao diện mới.

## Xác minh

### API và phân quyền

```bash
PYTHONPATH=src .venv-backend/bin/python -m pytest tests/backend/test_api.py \
  -k 'admin_lists or admin_user_filters or auth_csrf or ownership_and_revision' -q
```

**4 passed**, 19 deselected, 2 warning deprecation FastAPI/Starlette, 3,25 giây.
Các trường hợp gồm nhiều chủ sở hữu, tài khoản khóa, tìm kiếm ký tự đặc biệt,
lọc thùng rác/trạng thái, phân trang và chặn user thường khỏi API admin.
Admin xem được metadata quản lý nhưng vẫn không đọc workspace riêng của
người khác qua API cá nhân. Kiểm tra response không lộ password hash hoặc
tham chiếu nội dung riêng.

### Chrome

Chạy với database/tài khoản/server tạm riêng:

- Từ tổng quan mở đúng danh sách tài khoản và cuộc họp.
- Thấy cả admin, user thường và user đã khóa; thấy cuộc họp của nhiều owner.
- Liên kết số lượng, lọc chủ sở hữu và thùng rác hoạt động.
- Tìm kiếm đầu trang admin giữ đúng khu vực admin và tìm theo chủ sở hữu.
- Tạo tài khoản qua phiên khác; dòng tài khoản mới tự xuất hiện mà không
  tải lại trang thủ công.
- Kiểm lỗi API có thông báo, nút tải lại khôi phục được và có trạng thái rỗng.
- Danh sách user/cuộc họp không tràn ngang viewport mobile trong kiểm tra.
- Smoke **13 trang** đạt; có đối chiếu số dòng/tên trong hai danh sách với
  dữ liệu API, không chỉ kiểm tiêu đề trang. Không ghi nhận pageerror JS.

Ruff, Prettier, TypeScript/Vite và `git diff --check` đạt. Ảnh/báo cáo tại
`data/evaluations/admin-lists-fix-20261017/`.

Không đổi dữ liệu tài khoản/cuộc họp đang dùng. Server thử nghiệm và database
tạm đã được dọn; server chính giữ trạng thái tắt trước khi sửa.

## Cách mở sau cập nhật

Chạy launcher theo [QUICKSTART](QUICKSTART.md), đăng nhập admin rồi chọn
**Quản trị hệ thống → Tài khoản** hoặc **Quản trị hệ thống → Cuộc họp**.
Nếu còn mở một tab với giao diện cũ, tải lại tab sau khi khởi động server.
