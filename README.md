# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## OpenMap SketchUp 0.2.3 — Windows x64 Full, không cần đăng nhập

**Mở thẳng bản đồ, không cần tài khoản hoặc Supabase.**
Bộ cài đã kèm Python, Pillow và OCR; bộ xử lý tự chạy/dừng theo SketchUp.
Không có xu, tín dụng, gói trả phí hoặc tính lượt xuất.

### Tải xuống

- [Bộ cài Windows Full 0.2.3 (.rbz)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.2.3/OpenMap_SketchUp_Full_0.2.3_Windows_x64.rbz)
- [Toàn bộ mã nguồn và bộ cài (.zip)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.2.3/OpenMap_SketchUp_Open_Source_0.2.3.zip)
- [Release và SHA-256](https://github.com/nkl12012004-cmd/ZNS/releases/tag/openmap-v0.2.3)

Cài RBZ qua Extension Manager, **thoát hoàn toàn tất cả cửa sổ SketchUp** rồi
mở lại. Vào Extensions → OpenMap SketchUp → Mở OpenMap. Chờ bộ xử lý khởi động
để vào bản đồ; không cần nhập Supabase URL/public key.

### Thay đổi 0.2.3

- Mặc định khởi động bộ xử lý cục bộ khi nâng cấp, kể cả khi bản cũ lưu chế độ máy chủ riêng hoặc URL không còn hoạt động.
- Không suy ra chế độ từ URL cũ. Chỉ dùng máy chủ riêng khi chủ động chọn lại trong Cấu hình; lựa chọn mới được lưu.
- Khi máy chủ riêng lỗi, tự mở Cấu hình với nút “Chạy trên máy này — không cần máy chủ riêng”.
- Không cần xóa AppData, đăng nhập hoặc cấu hình Supabase để dùng bản Full.

### Mã nguồn và hướng dẫn

- [Xem/chỉnh sửa mã nguồn](openmap-sketchup/)
- [Cài và nâng cấp Windows Full](openmap-sketchup/docs/INSTALL_WINDOWS_FULL_VI.md)
- [Tính năng và hướng dẫn phát triển](openmap-sketchup/README_VI.md)
- [Đối chiếu tính năng](openmap-sketchup/docs/FEATURE_PORT.md)
- [Kết quả kiểm tra](openmap-sketchup/docs/VALIDATION.md)
- [Kiểm tra Windows 0.2.3](https://github.com/nkl12012004-cmd/ZNS/actions/runs/44001928903)

Đã kiểm tra cấu hình chế độ cũ và UI chuyển từ máy chủ riêng lỗi về cục bộ.\n28 bài kiểm tra server và UI fixture đã qua. Kiểm tra Windows chạy Python/OCR
đóng kèm, chính Core HTTP bridge của plugin, dựng và lấy mesh/GLB không cần
đăng nhập, proxy lỗi, đường dẫn tiếng Việt, khởi động lại và dọn tiến trình con.

SketchUp Desktop không có trên runner; lỗi trên máy người dùng cần được xác nhận
bằng cách mở bộ cài mới trong SketchUp. Import/Undo/placement thực tế chưa kiểm tra.
Đây là bản viết lại độc lập; lõi MapSKP mã hóa và Google Photorealistic 3D cũ
chưa khôi phục. Mã mới MIT; tệp tham chiếu và thư viện giữ giấy phép riêng:
[NOTICE](openmap-sketchup/NOTICE.md).
