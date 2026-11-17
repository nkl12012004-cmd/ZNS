# Cài Windows Full 0.2.0

1. Tải `OpenMap_SketchUp_Full_0.2.0_Windows_x64.rbz` từ GitHub Release.
2. SketchUp Desktop → Extension Manager → Install Extension… → chọn RBZ.
3. Đóng và mở lại SketchUp, đặc biệt khi nâng từ bản 0.1.0.
4. Mở Extensions → OpenMap SketchUp → Mở OpenMap.
5. Lần đầu, plugin tự cài runtime vào LocalAppData và mở bộ xử lý trên cổng riêng.
   Chờ thanh tiến trình hoàn tất; không cần Python, pip hoặc cửa sổ terminal.
6. Trong màn hình Cấu hình, nhập Supabase Project URL và public anon/publishable
   key của dự án bạn dùng. Không dùng service_role hoặc secret key.
7. Bấm Lưu, rồi đăng nhập Email/Google và dựng bản đồ.

Google cần bật provider Google ở dự án Supabase. Trong Authentication → URL
Configuration → Redirect URLs thêm `http://127.0.0.1:*/auth/callback**` vì mỗi
phiên SketchUp chọn cổng loopback riêng. Google Cloud redirect vẫn là callback
của Supabase, thường `https://YOUR_PROJECT.supabase.co/auth/v1/callback`.

Gói Full gồm CPython 3.14.10, Pillow 12.3.0, OCR Tesseract 5.5.1, Leptonica 1.85.0
và mô hình OCR tiếng Anh. OCR nhận tọa độ qua nút chọn ảnh hoặc Ctrl+V ảnh.
Bộ xử lý tự dừng khi đóng SketchUp, kể cả khi tiến trình cha kết thúc bất thường.

Cấu hình và cache nằm ở `%LOCALAPPDATA%/OpenMapSketchUp/`:

- `config.env`: Project URL và public key; không lưu mật khẩu/token đăng nhập.
- `runtime/`: runtime đã giải nén, có khóa cài đặt để nhiều SketchUp không xung đột.
- `worker-<pid>.log`: nhật ký khởi động bộ xử lý.

Có thể mở thư mục này hoặc khởi động lại bộ xử lý từ Cấu hình. Bản Full hỗ trợ
Windows 10/11 x64 với SketchUp Desktop có Ruby/HtmlDialog. SketchUp cần cho phép
extension nguồn mở chưa ký theo chính sách cài đặt đang dùng trên máy đó.

macOS/Linux và cách chạy máy chủ riêng vẫn có mã nguồn trong gói ZIP, nhưng
runtime tự chứa trong bản phát hành này là Windows x64.

Nguồn dữ liệu bản đồ/DEM/OSM và Supabase cần Internet. Plugin không có ví xu,
tín dụng hoặc tính lượt xuất; dịch vụ bên ngoài vẫn có chính sách vận hành riêng.

Đây là bản viết lại độc lập. Phần lõi mã hóa/Google Photorealistic 3D của MapSKP
gốc chưa được khôi phục. Xem FEATURE_PORT.md để biết phạm vi chức năng cụ thể.
