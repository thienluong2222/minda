# Báo cáo Kiểm tra Rò rỉ Dữ liệu VIVOS (Data Audit Report)

**Trạng thái**: PASSED (Passed: True)  
**Tổng số câu**: 12,420  
**Số vi phạm**: 0  

---

## 1. Phân chia Split & Người nói (Speaker Disjointness)

| Split | Số người nói | Số câu tổng | Số câu Enrollment | Số câu Meeting | Tổng thời lượng (giờ) |
|---|---|---|---|---|---|
| **development** | 32 | 8,097 | 298 | 7,799 | 10.75h |
| **validation** | 14 | 3,563 | 143 | 3,420 | 4.17h |
| **test** | 19 | 760 | 197 | 563 | 0.75h |

---

## 2. Thống kê Văn bản

- Số câu văn bản chuẩn hóa phân biệt: **10,895**
- Số mẫu văn bản xuất hiện ở hơn 1 câu: **856**
- Tỷ lệ câu lặp văn bản giữa các người nói: **19.17%** (Được phép theo mục 6.1)

---

## 3. Danh sách Vi phạm (Violations)

- ✅ **Không phát hiện vi phạm rò rỉ dữ liệu nào.**
- ✅ 100% người nói giữa dev, val và test hoàn toàn tách biệt.
- ✅ 100% câu enrollment và meeting content hoàn toàn tách biệt.
- ✅ 100% file audio đúng định dạng WAV 16kHz mono, thời lượng khớp.
