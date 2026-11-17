# ZNS
Zenith System - SketchUp plugin thiết kế &amp; sản xuất nội thất gỗ công nghiệp, nesting và xuất DXF CNC.

---

## SiteCraft 0.4.2 — bản đồ và địa hình cho SketchUp

Mở thẳng bản đồ, không cần đăng nhập/Supabase, xu hoặc tín dụng. Giao diện một
thanh bên, tên và icon SiteCraft, font SVN-Avo được kèm sẵn.

- [Bộ cài Windows Full (.rbz)](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Full_0.4.2_Windows_x64.rbz)
- [Mã nguồn và bộ cài (.zip)](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Source_0.4.2.zip)
- [Release và SHA-256](https://github.com/nkl12012004-cmd/ZNS/releases/tag/sitecraft-v0.4.2)

Cài qua Extension Manager, thoát hoàn toàn SketchUp rồi mở lại.
Extensions → SiteCraft → Mở SiteCraft.

### Bản 0.4.2

- Cây vừa tỷ lệ: cao 4–6,5 m, tán rộng tối đa 4 m. Cụm tán lớn có thể tách thành 2–6 cây nhỏ tại các đỉnh tán rõ trên ảnh; tán trơn không có thêm đỉnh chỉ giữ một cây nhỏ. Kích thước nhận từ ảnh được lưu riêng với kích thước mô hình.

- Cây có thân trụ và tán tròn với năm sắc xanh. Vị trí lấy từ tâm tán dò được
  trên ảnh vệ tinh bằng đường nét, kết cấu và tương phản; vùng thiếu bằng chứng
  để trống. Không rải theo lưới hay chỉ dựa vào vùng xanh/công viên. OSM chỉ đối
  chiếu ứng viên thấy trên ảnh. Nhận diện có thể bỏ sót/nhầm ở ảnh mờ, không phải
  bản kiểm kê cây được khảo sát. Có mức nhận diện Thận trọng/Chuẩn/Nhiều hơn.
- Địa hình 3D mặc định dựng DEM đầy đủ, giữ cao độ ở bốn mép và thành đế 4m.
  Không tự chuyển sang trám đồi sau khi đã tạo map phẳng. Trám đồi là lựa chọn
  riêng, chỉ áp dụng khi chủ động bật trên mô hình có mốc nền phẳng.
- Dùng quy trình dữ liệu/nhà/đường/xuất MapSKP đã khôi phục; năm mô-đun gốc
  giữ nguyên. Các bổ sung nằm trong mã tích hợp SiteCraft.

Windows Full chạy kiểm tra runtime, API, OCR và Ruby trước khi phát hành.
SketchUp Desktop/SDK save-load thật vẫn cần xác nhận trên máy đích. Các kiểm tra
không thay thế việc mở mô hình và kiểm tra hiển thị/Undo trong SketchUp.

- [Nguồn chỉnh sửa được](openmap-sketchup/)
- [Ghi chú 0.4.2](openmap-sketchup/docs/RELEASE_0.4.2.md)
- [Kiểm tra và giới hạn](openmap-sketchup/docs/VALIDATION.md)
- [Windows build](https://github.com/nkl12012004-cmd/ZNS/actions/workflows/openmap-windows-full.yml)
- [Quyền của mã gốc, font và thư viện](openmap-sketchup/NOTICE.md)

Mã tích hợp mới MIT. Nguồn phục hồi và font giữ quyền gốc; việc người dùng xác
nhận công bố không đổi quyền của các thành phần. Google Photorealistic 3D và
backend thương mại cũ không thuộc phần đã phục hồi.
