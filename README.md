# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## OpenMap SketchUp 0.1.0 — mã nguồn và bộ cài

Bản viết lại có giao diện bản đồ 2D/3D, địa hình DEM, đường/nhà/cây/nước,
ghép mảnh và xuất SKP/OBJ/GLB. Đăng nhập Email/Google qua Supabase;
không có xu, tín dụng, gói trả phí hoặc tính lượt xuất.

### Tải xuống

- [Tải bộ cài OpenMap_SketchUp_0.1.0.rbz](https://github.com/nkl12012004-cmd/ZNS/raw/refs/heads/main/downloads/OpenMap_SketchUp_0.1.0.rbz)
- [Tải toàn bộ mã nguồn OpenMap_SketchUp_Open_Source_0.1.0.zip](https://github.com/nkl12012004-cmd/ZNS/raw/refs/heads/main/downloads/OpenMap_SketchUp_Open_Source_0.1.0.zip)
- [SHA-256 của hai gói](downloads/SHA256SUMS.txt)

### Mở mã và cài đặt

- [Mã nguồn có thể xem/chỉnh sửa trên GitHub](openmap-sketchup/)
- [Hướng dẫn cài server, cấu hình Supabase và cài RBZ](openmap-sketchup/README_VI.md)
- [Cấu hình Supabase mẫu](openmap-sketchup/server/.env.example)
- [Đối chiếu tính năng đã chuyển từ bản cũ](openmap-sketchup/docs/FEATURE_PORT.md)
- [Kết quả kiểm tra và giới hạn](openmap-sketchup/docs/VALIDATION.md)

Cần điền Project URL/public key Supabase và chạy server kèm theo trước khi
đăng nhập. Gói đã qua 18 kiểm tra Python, kiểm tra UI/WebGL, Ruby preflight
và xác thực GLB; cần thử trực tiếp trong SketchUp Desktop.

Mã runtime mới phát hành MIT. Các tệp MapSKP gốc đọc được trong thư mục
tham chiếu giữ thông tin bản quyền riêng; xem [NOTICE](openmap-sketchup/NOTICE.md).
