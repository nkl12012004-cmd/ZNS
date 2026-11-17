# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## OpenMap SketchUp 0.2.0 — Windows x64 Full

Bộ cài đã kèm Python, Pillow và OCR; plugin tự mở bộ xử lý khi chạy và tự dừng
khi đóng SketchUp. Đăng nhập Email/Google qua Supabase của bạn, không có xu,
tín dụng, gói trả phí hoặc tính lượt xuất.

### Tải xuống

- [Bộ cài Windows Full (.rbz)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.2.0/OpenMap_SketchUp_Full_0.2.0_Windows_x64.rbz)
- [Toàn bộ mã nguồn và bộ cài (.zip)](https://github.com/nkl12012004-cmd/ZNS/releases/download/openmap-v0.2.0/OpenMap_SketchUp_Open_Source_0.2.0.zip)
- [Release và SHA-256](https://github.com/nkl12012004-cmd/ZNS/releases/tag/openmap-v0.2.0)

Cài RBZ qua Extension Manager, đóng/mở lại SketchUp, mở OpenMap và điền
Supabase Project URL/public key trong **Cấu hình**. Không cần tự cài Python
hoặc chạy terminal ở chế độ Windows Full.

### Mã nguồn và hướng dẫn

- [Xem/chỉnh sửa mã nguồn](openmap-sketchup/)
- [Hướng dẫn cài Windows Full](openmap-sketchup/docs/INSTALL_WINDOWS_FULL_VI.md)
- [Cấu hình Supabase và hướng dẫn phát triển](openmap-sketchup/README_VI.md)
- [Cấu hình mẫu](openmap-sketchup/server/.env.example)
- [Đối chiếu tính năng](openmap-sketchup/docs/FEATURE_PORT.md)
- [Kết quả kiểm tra và giới hạn](openmap-sketchup/docs/VALIDATION.md)

Bản đồ 2D/3D, ảnh vệ tinh, DEM, đường/nhà/cây/nước OSM, OCR tọa độ,
ghép mảnh, SKP/OBJ/GLB đã có trong mã mới. Bộ cài được kiểm tra trên Windows:
25 bài kiểm tra server, Python/Pillow đóng kèm, OCR thực, HTTPS, Ruby
khởi động/khởi động lại, đường dẫn tiếng Việt và tự dừng khi tiến trình cha thoát.
[Nhật ký kiểm tra Windows](https://github.com/nkl12012004-cmd/ZNS/actions/runs/43996909891).

Chưa kiểm tra trực tiếp trong SketchUp Desktop hoặc với dự án Supabase thật
của bạn. Đây là bản viết lại độc lập; lõi mã hóa và Google Photorealistic 3D
độc quyền của MapSKP gốc chưa được khôi phục.

Mã mới phát hành MIT. Các tệp gốc đọc được trong thư mục tham chiếu và thư viện
đóng kèm giữ giấy phép riêng; xem [NOTICE](openmap-sketchup/NOTICE.md).
