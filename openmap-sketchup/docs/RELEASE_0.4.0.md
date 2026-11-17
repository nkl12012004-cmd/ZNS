# SiteCraft 0.4.0

Bản này đổi tên hiển thị thành **SiteCraft**, dùng font SVN-Avo do người dùng
cung cấp và đưa bộ dựng/xuất MapSKP đã khôi phục thành mã Python có thể chỉnh
sửa. Giao diện giữ một thanh bên cho tùy chọn, tiến trình và xuất tệp.
Windows Full mở thẳng bản đồ, không cần đăng nhập/Supabase hoặc xu/tín dụng.
Biểu tượng mới dùng khối hộp đường đồng mức màu xanh và khối hộp vàng theo
hình tham chiếu người dùng.

Người dùng đã xác nhận công bố bản này cùng năm mô-đun nguồn khôi phục trong
`nkl12012004-cmd/ZNS` ngày 17/11/2026, theo giờ Việt Nam.
Release `sitecraft-v0.4.0` được công bố sau khi kiểm tra Windows của đúng gói đạt.
Kết quả kiểm tra Windows đầy đủ chưa được ghi nhận tại thời điểm cập nhật này.

Liên kết tải có hiệu lực khi Release được công bố:

- [Bộ cài Windows Full](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Full_0.4.0_Windows_x64.rbz).
- [Gói mã nguồn](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Source_0.4.0.zip).
- [SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SHA256SUMS.txt).

## Thay đổi bộ dựng và xuất

Năm mô-đun gốc đều ở dạng `.py`: builder 51 hàm, tọa độ 11 hàm, texture 22 hàm,
bộ ghi 14 hàm và tọa độ/OCR 6 hàm. `recovery-manifest.json` ghi kích thước và
SHA-256 của từng tệp. Build từ chối `.marshal`, `.pyc`, thư mục cache, vault,
armor và native binary trong `server/original_kernel/`.

Quy trình được giữ từ bản cũ gồm ghép ảnh tile, DEM Terrarium, địa hình có thành
và đáy khối, đường theo địa hình, OpenFreeMap MVT/Overpass, bù đường và nhà từ
màu Google đường phố, chiều cao công trình, nhà có khối đế/tầng giật cấp/khối
mái và texture mặt đứng/mái/gờ tạo thủ tục. Bộ ghi OBJ/MTL/ảnh, GLB và JSON
fallback giữ cách xuất của mã gốc.

GLB có một bước sửa tương thích bên ngoài bộ ghi gốc. Nếu bộ ghi gán texture
cho nhóm mặt (primitive) không có UV, SiteCraft đổi riêng liên kết vật liệu đó sang bản
sao màu theo RGBA gốc. Hình học, UV đã có, byte BIN và ảnh không thay đổi.
Tệp gốc được giữ thành `<tên>_original.glb` khi có sửa; manifest ghi
`glb_compatibility` cùng hash và danh sách phần đã sửa. GLB không cần sửa trả
nguyên byte; GLB đã sửa không được mô tả là trùng byte toàn bộ với bản gốc.

Nhánh SDK chỉ sẵn sàng khi thật sự chạy trên Windows và tìm được DLL phù hợp.
Khi không có SDK, tác vụ giữ mesh/texture để nạp thành hình học có thể chỉnh
sửa và lưu trong SketchUp. Chưa xác nhận một tệp SKP native được tạo bằng SDK
thật hoặc nạp bằng SketchUp Desktop thật trong lần kiểm tra này.

## Cài và nâng cấp

1. Install Extension… trong Extension Manager, chọn RBZ SiteCraft 0.4.0.
2. Thoát hết SketchUp rồi mở lại; chỉ đóng hộp thoại plugin không nạp lại Ruby.
3. Extensions → SiteCraft → Mở SiteCraft, chờ bộ xử lý cục bộ mở bản đồ.
4. Nếu còn chọn máy chủ riêng cũ, vào Cấu hình và chuyển về chạy trên máy này.
5. Chọn địa điểm/vùng/lớp, dựng và kiểm tra cảnh báo trước khi nạp.

Không cần tạo dự án Supabase cho Windows Full. Runtime có Python/NumPy/Pillow/
Requests/Tesseract theo lockfile; dữ liệu bản đồ vẫn cần Internet. Các tên thư
mục `openmap_sketchup` được giữ để tương thích nâng cấp. Hướng dẫn 0.3.0 có tên
gói và phiên bản runtime cũ; dùng [README 0.4.0](../README_VI.md) cho bản này.

## Kiểm tra và quyền sử dụng

Đã đối chiếu bộ dựng 51 hàm qua 61 ca, cùng một cảnh Quỳnh Lưu từ cache có
7.316 đỉnh/10.500 tam giác và cùng fingerprint với chương trình gốc. Kiểm tra
texture cho 13 JPEG mặc định trùng từng byte; đầu ra thô của bộ ghi portable
trùng OBJ/MTL, GLB, gói cảnh và JSON/ảnh fallback trong các cảnh đã thử.
GLB giao cho người dùng đi qua bước sửa vật liệu thiếu UV nói trên khi cần.
Dấu vết lời gọi SDK
được kiểm tra tới ranh giới lưu tệp, không dùng SDK thật.
Runtime dependency công khai đã đạt trên Windows trong run 44017165169;
ca đó không chứa mã khôi phục và không xác nhận bộ dựng chạy trên Windows.
Bộ máy chủ cuối: 88 bài, 87 đạt và một bỏ qua đúng điều kiện. GLB mẫu sau sửa
đạt glTF Validator: 0 lỗi, 0 cảnh báo; hai primitive thiếu UV được sửa bằng một
bản sao vật liệu, vẫn giữ nguyên BIN/ảnh.
Xem [VALIDATION.md](VALIDATION.md) cho phạm vi và các bước còn cần xác nhận.

Mã tích hợp mới giữ MIT. Mã khôi phục và font giữ quyền gốc; chưa xác minh được
giấy phép nguồn mở cho chúng. Không mô tả toàn bộ gói là MIT hoặc đã mở nguồn
hợp pháp. Nhánh chính sách native tùy chọn vẫn được giữ, không tạo grant/chữ ký.

Việc công bố nguồn khôi phục đã được người dùng xác nhận; quyền gốc không đổi.
Trình build tạo gói và checksum; bước phát hành chỉ thực hiện sau kiểm tra Windows.
Xem [NOTICE.md](../NOTICE.md).
