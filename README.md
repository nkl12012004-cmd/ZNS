# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## OpenMap SketchUp 0.3.0 — Windows x64 Full

**Mở thẳng bản đồ, không cần tài khoản hoặc Supabase.**
Bộ cài đã kèm Python, Pillow và OCR; bộ xử lý tự chạy/dừng theo SketchUp.
Không có xu, tín dụng hoặc tính lượt xuất.

### Tải xuống

- [Bộ cài Full 0.3.0 (.rbz)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.3.0/OpenMap_SketchUp_Full_0.3.0_Windows_x64.rbz)
- [Toàn bộ mã nguồn và bộ cài (.zip)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.3.0/OpenMap_SketchUp_Open_Source_0.3.0.zip)
- [Release và SHA-256](https://github.com/nkl12012004-cmd/ZNS/releases/tag/openmap-v0.3.0)

Cài RBZ qua Extension Manager, **thoát hoàn toàn mọi cửa sổ SketchUp**, mở lại
và vào Extensions → OpenMap SketchUp → Mở OpenMap. Không cần điền Supabase.

### Luồng bản đồ đã chuyển lại từ bản cũ

- Một bảng điều khiển chứa tùy chọn, tiến trình, tệp xuất và ghép mảnh.
- “Vệ tinh sạch” dùng Esri như bản cũ; giữ Google vệ tinh/hybrid/đường phố và OSM.
  Đổi lớp vệ tinh để xem cũng đổi nguồn ảnh xuất.
- Tìm có gợi ý khi gõ, phím mũi tên/Enter, bấm Tìm tới ngay kết quả đầu; có các
  nguồn tìm kiếm dự phòng. Địa điểm mẫu/OCR nằm cạnh ô tìm kiếm.
- OSM vùng nhỏ dùng XML trước và có nguồn dự phòng. Nếu mọi nguồn đều lỗi,
  vẫn giữ nền/địa hình và ghi rõ lớp thiếu; không tự nạp kết quả thiếu lớp.
- Không xuất ảnh Esri xám “chưa có dữ liệu” như ảnh hợp lệ; có hạ zoom và
  cảnh báo đúng mức ảnh nguồn. Kích thước file 4K không cam kết thêm chi tiết gốc.
- Ghép Bắc/Nam/Đông/Tây dùng mảnh nền vừa nạp; trám đồi không thay tham chiếu đó.
- Mặc định Hà Nội, 380 m, Vệ tinh sạch, ảnh 4K, lưới 64 như giao diện cũ.

### Mã nguồn và kiểm tra

- [Xem/chỉnh sửa mã nguồn](openmap-sketchup/)
- [Cài/nâng cấp Windows Full](openmap-sketchup/docs/INSTALL_WINDOWS_FULL_VI.md)
- [Đối chiếu tính năng với bản cũ](openmap-sketchup/docs/FEATURE_PORT.md)
- [Kết quả kiểm tra và giới hạn](openmap-sketchup/docs/VALIDATION.md)
- [Kiểm tra Windows 0.3.0](https://github.com/nkl12012004-cmd/ZNS/actions/runs/44007270317)

62 bài kiểm tra server, Playwright UI và Ruby preflight đã qua. Native Windows
kiểm tra Python/OCR đóng kèm, cấu hình cũ, Core HTTP, Maps URL, mesh/GLB,
đường dẫn Unicode, khởi động lại và dừng tiến trình con.
Dữ liệu thật Hà Nội/TP.HCM và địa chỉ tiếng Việt đã được thử; cấu hình Hà Nội
380m/4K/grid64 tạo ảnh hàng không thực và mô hình 17.641 tam giác.

SketchUp Desktop không có trên runner; import/Undo/placement thực tế cần được
xác nhận trong SketchUp. Giao diện/cách gọi đọc được đã được dùng để chuyển luồng;
lõi geocode/OSM/geometry bản cũ nằm trong mã hóa nên phần xử lý mới được viết
độc lập. Google Photorealistic 3D cũ chưa khôi phục.
Mã mới MIT; tệp tham chiếu và thư viện giữ giấy phép riêng:
[NOTICE](openmap-sketchup/NOTICE.md).
