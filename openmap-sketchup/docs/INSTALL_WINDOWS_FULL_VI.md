# Cài Windows Full 0.3.0 — không cần đăng nhập

1. Tải `OpenMap_SketchUp_Full_0.3.0_Windows_x64.rbz` trong GitHub Release.
2. SketchUp → Extension Manager → Install Extension… → chọn RBZ mới.
3. Thoát hoàn toàn tất cả cửa sổ SketchUp, rồi mở lại. Chỉ đóng hộp thoại
   OpenMap chưa đủ để nạp mã Ruby mới khi nâng cấp từ 0.2.0.
4. Extensions → OpenMap SketchUp → Mở OpenMap.
5. Chờ bộ xử lý khởi động. Plugin tự mở bản đồ, không yêu cầu Email/Google,
   Supabase URL/public key, Python/pip hoặc terminal.

Bản 0.3.0 bỏ qua chế độ máy chủ riêng và URL đã lưu từ các bản trước;
mặc định khởi động bộ xử lý trên máy. URL cũ vẫn được giữ, nhưng chỉ được
dùng nếu chủ động chọn lại máy chủ riêng trong Cấu hình.

Nếu trước đây đã nhập Supabase, không cần xóa cấu hình: chế độ Windows Full mới
không dùng Supabase để mở bản đồ. Trong Cấu hình, chọn “Tự chạy trên máy Windows
này” nếu máy đang đặt chế độ máy chủ riêng.

Gói gồm CPython 3.14.10, Pillow 12.3.0, Tesseract 5.5.0, Leptonica 1.85.0 và OCR
model tiếng Anh. OCR đọc tọa độ qua nút chọn ảnh hoặc Ctrl+V ảnh.
Bộ xử lý tự dừng khi đóng SketchUp hoặc khi tiến trình cha kết thúc.

Bản 0.3.0 sửa đường gọi API cục bộ từng báo HTTP 0. Kết nối loopback trực tiếp
không đi qua proxy hệ thống; các callback UI vẫn chạy trên luồng chính SketchUp.
Nếu còn lỗi, mở Cấu hình → Khởi động lại bộ xử lý. Nếu đang ở máy chủ riêng,
bấm “Chạy trên máy này — không cần máy chủ riêng”. Nút Mở thư mục cấu hình / log
mở `%LOCALAPPDATA%/OpenMapSketchUp/`; xem `worker-<pid>.log` để chẩn đoán.

Hỗ trợ Windows 10/11 x64, SketchUp Desktop có Ruby/HtmlDialog (mục tiêu 2021+).
Nguồn dữ liệu bản đồ, DEM và OSM cần Internet. Không có xu hoặc tín dụng.

Máy chủ riêng là chế độ nâng cao, có cấu hình/xác thực riêng; không cần dùng
chế độ đó khi cài Windows Full.

Đây là bản viết lại độc lập. Phần lõi mã hóa/Google Photorealistic 3D của MapSKP
gốc chưa được khôi phục. Xem FEATURE_PORT.md để biết phạm vi chức năng cụ thể.

Tìm kiếm: gõ tên địa điểm để xem gợi ý, dùng phím mũi tên/Enter hoặc bấm Tìm để
đến ngay kết quả đầu. “Vệ tinh sạch” là Esri World Imagery như bản cũ. Thay lớp
vệ tinh cũng đổi nguồn ảnh xuất. Các lệnh dựng, tiến trình, tệp xuất và ghép mảnh
đã nằm trong cùng thanh bên; cuộn trong thanh để xem thêm, không cần đổi tab.

Nếu thấy cảnh báo thiếu OSM, nền/ảnh/địa hình vẫn có thể đã dựng xong. Plugin
không tự nạp kết quả thiếu lớp; bấm “Nạp nền/địa hình” nếu chấp nhận thiếu lớp,
hoặc dựng lại vùng đang chọn để thử nguồn dữ liệu lần nữa.
