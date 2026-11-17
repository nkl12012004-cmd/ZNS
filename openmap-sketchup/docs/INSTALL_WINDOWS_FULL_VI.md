# Cài SiteCraft 0.4.0 Windows Full

Tải [SiteCraft_Full_0.4.0_Windows_x64.rbz](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Full_0.4.0_Windows_x64.rbz)
từ Release `sitecraft-v0.4.0`. [Gói nguồn](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Source_0.4.0.zip)
cũng có bộ cài trong `SiteCraft/install/`. Đối chiếu
[SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SHA256SUMS.txt) khi cần.
Liên kết tải có hiệu lực sau khi Release được công bố; bản phát hành được kiểm
tra trên Windows trước khi công bố. Kết quả Windows đầy đủ đang được chốt.

1. Mở SketchUp → Window → Extension Manager → Install Extension…
2. Chọn `SiteCraft_Full_0.4.0_Windows_x64.rbz`.
3. Thoát hoàn toàn mọi cửa sổ SketchUp, rồi mở lại.
4. Extensions → SiteCraft → Mở SiteCraft. Chờ runtime khởi động lần đầu.
5. Chọn địa điểm, kích thước vùng, lớp dữ liệu và bấm Đưa vào SketchUp.

Bản Full mở thẳng bản đồ, không cần tài khoản, Supabase, xu hoặc tín dụng.
Tên và icon là SiteCraft; giao diện HTML dùng font SVN-Avo đã kèm trong gói.
Bản đồ, ảnh và dữ liệu địa hình cần Internet.

Gói cài cập nhật các đường dẫn `openmap_sketchup` đang có để giữ thiết lập cũ.
Nếu đang dùng máy chủ riêng, vào Cấu hình → Chạy trên máy này. Lỗi khởi động
có thể thử Khởi động lại bộ xử lý hoặc Mở thư mục cấu hình / log. Thư mục cache
Windows vẫn là `%LOCALAPPDATA%/OpenMapSketchUp/` để tương thích cài đặt cũ.

Địa hình và nhà được dựng bằng nguồn Python khôi phục của quy trình MapSKP.
Khi có SDK phù hợp, backend ghi SKP thật. Nếu SDK không có hoặc SketchUp không
đọc được tệp SDK, plugin dùng mesh/texture gốc để nạp. Nút SKP của tác vụ chỉ
lưu đúng tác vụ đó; sau fallback cần nạp và chọn đúng nhóm trước khi lưu.

Phần nguồn khôi phục đã được người dùng xác nhận công bố trong ZNS ngày
17/11/2026, theo giờ Việt Nam; các tệp đó giữ quyền gốc và không thuộc MIT.
Tạo/nạp SKP
native bằng SketchUp Desktop thật vẫn cần xác nhận trên Windows. Xem
[phạm vi kiểm tra](VALIDATION.md) và [quyền các thành phần](../NOTICE.md).
