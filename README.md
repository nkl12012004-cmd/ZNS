# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## SiteCraft 0.4.0 — bản đồ và địa hình cho SketchUp

Mở thẳng bản đồ, không cần đăng nhập hoặc Supabase, không có xu hay tín dụng.
Một thanh bên chứa chọn vùng, lớp dữ liệu, tiến trình, xuất và ghép mảnh.
Tên hiển thị SiteCraft, icon địa hình xanh/khối vàng và font SVN-Avo được kèm sẵn.

- [Bộ cài Windows Full (.rbz)](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Full_0.4.0_Windows_x64.rbz)
- [Mã nguồn và bộ cài (.zip)](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Source_0.4.0.zip)
- [Release và SHA-256](https://github.com/nkl12012004-cmd/ZNS/releases/tag/sitecraft-v0.4.0)

Cài RBZ bằng Extension Manager, thoát hoàn toàn SketchUp rồi mở lại.
Extensions → SiteCraft → Mở SiteCraft. Không cần cài Python riêng.

Bản này dùng mã Python chỉnh sửa được phục hồi từ bộ dựng MapSKP do người dùng
cung cấp: lấy dữ liệu OpenFreeMap MVT/Overpass, bù đường/nhà từ Google roadmap,
DEM, địa hình có thành/đáy, khối nhà có đế/tầng giật cấp/mái và texture tạo thủ tục.
Bộ ghi gốc tạo OBJ/MTL/ảnh và GLB; bước tương thích GLB sửa gán texture trên mặt
thiếu UV, giữ nguyên geometry/BIN và ảnh. Giữ riêng tệp GLB gốc khi có sửa.

Bộ dựng đầy đủ khớp 61 ca với thực thi gốc; cảnh Quỳnh Lưu dùng cache khớp
lưới/UV/texture/metadata. Linux: 87 bài máy chủ đạt, 1 bỏ qua đúng điều kiện;
kiểm tra UI, font, Ruby và glTF Validator đạt. [Kiểm tra Windows Full](https://github.com/nkl12012004-cmd/ZNS/actions/runs/44022035961) đã đạt: 86 bài máy chủ, OCR Tesseract, HTTPS, Ruby HTTP, restart và parent-exit cleanup; hai bài bỏ qua đúng điều kiện. SketchUp Desktop/SDK save-load thật vẫn cần xác nhận trên máy đích;
runner không thay thế kiểm tra import, Undo và hình thức hiển thị trong SketchUp.
Google Photorealistic 3D và backend thương mại cũ không thuộc phần đã phục hồi.

- [Xem/chỉnh sửa nguồn](openmap-sketchup/)
- [Cài và nâng cấp](openmap-sketchup/docs/INSTALL_WINDOWS_FULL_VI.md)
- [Phạm vi kiểm tra](openmap-sketchup/docs/VALIDATION.md)
- [Windows build và kiểm tra](https://github.com/nkl12012004-cmd/ZNS/actions/workflows/openmap-windows-full.yml)
- [Quyền của mã gốc, font và thư viện](openmap-sketchup/NOTICE.md)

Mã tích hợp mới MIT. Năm tệp Python phục hồi và font giữ quyền gốc; chưa xác
minh giấy phép nguồn mở cho phần gốc. Người dùng đã xác nhận công bố chúng
trong repository này; việc công bố không đổi quyền của các thành phần.
