# Đối chiếu phần chuyển từ giao diện/tính năng cũ

Gói ZIP cũ được dùng làm tài liệu và nguồn tham chiếu. Mã runtime mới được viết
độc lập với bộ dựng bản đồ mở, không có thanh toán. Windows Full 0.2.2 mở
thẳng bản đồ, không cần Supabase hoặc tài khoản.
11 tệp gốc đọc được đã được giữ nguyên trong `reference/mapskp_original_readable/`.

| Hạng mục quan sát được ở bản cũ | Bản mới |
| --- | --- |
| Bản đồ toàn màn hình, thẻ nổi, sáng/tối | Có |
| Tab xem 2D/3D, xoay/pan/zoom, căn giữa, khung dây | Có, viewer WebGL mới |
| Map phẳng Z=0 / Địa hình DEM | Có |
| Trám đồi lên lớp phẳng | Có, nội suy đưa rìa mảnh về Z=0 |
| Preset 200/380/600/1000 m, kích thước thủ công | Có |
| Kéo góc khung vùng chọn | Có |
| Tìm địa chỉ, tọa độ thập phân/DMS, link có tọa độ | Có |
| Gợi ý tìm kiếm trực tiếp | Chọn địa điểm mẫu và kết quả tìm; không gửi autocomplete liên tục đến Nominatim |
| OCR ảnh chụp/Ctrl+V ảnh | Có, Tesseract/eng đóng kèm trong Windows Full |
| Vệ tinh Esri, Google vệ tinh/hybrid/đường phố | Có; phụ thuộc khả dụng nguồn tile |
| OSM lớp xem 2D | Có; không dùng tile OSM để tải ảnh xuất hàng loạt |
| Ảnh 2K/4K/8K | Có, thêm 1K; 8K JPEG, tối đa 8192 |
| Lưới DEM, hệ số cao độ | Có |
| Đường chính/ngõ bật riêng | Có, Group/Tag riêng |
| Nhà cao/thấp tầng, số tầng mặc định | Có, mốc cao tầng 21 m |
| Box trắng hoặc map công trình | Có; map tạo thủ tục, không phải ảnh mặt đứng thật |
| Mái phẳng, mái trầm/bê tông, gờ mái | Có, hình học xấp xỉ |
| Mặt nước | Có, polygon OSM đơn giản; chưa dựng multipolygon có lỗ |
| Cây | Có, tại node OSM natural=tree; chưa tái tạo rừng tự động |
| Mốc chung, chọn Bắc/Nam/Đông/Tây | Có |
| Tự nạp sau khi dựng | Có |
| Lưu SKP, OBJ + texture, GLB | Có |
| Mở thư mục, bóng nắng, Undo | Có |
| Kéo-thả SKP tự ghép | Có cho metadata OpenMap; đọc metadata MapSKP cũ khi hợp lệ |
| Không di chuyển đối tượng cũ đã có khi bật plugin | Có; observer ghi nhận các đối tượng hiện có và chỉ xét mảnh mới thêm |
| Lõi Google Photorealistic 3D độc quyền | Không có nguồn gốc; không khôi phục |
| Auto-update dùng chữ ký nhà phát hành cũ | Không dùng; có script đóng gói mã mới |
| Runtime Windows tự chứa | Có, Python/Pillow/OCR; tự khởi động và dừng theo SketchUp |
| Cấu hình Supabase trong giao diện | Không cần trong Windows Full 0.2.2 |
| Đăng nhập | Windows Full 0.2.2 không yêu cầu; máy chủ riêng nâng cao vẫn có Supabase |
| Xu/tín dụng/gói trả phí/referral/đếm lượt | Không có trong runtime mới |

`reference/` không được nạp khi cài RBZ. Những tên API/callback, quota hay nội dung
thương mại còn trong tệp tham chiếu là nội dung gốc để đối chiếu, không thuộc
luồng vận hành của extension mới. Giấy phép của tệp gốc không bị tự thay đổi.
