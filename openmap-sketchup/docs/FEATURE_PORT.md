# SiteCraft 0.4.0 — phần đã chuyển từ MapSKP

Bản 0.4.0 dùng mã Python đọc/sửa được khôi phục từ bộ dựng gốc. Phần giao diện,
API và cầu nối SketchUp là mã tích hợp mới. Tên sản phẩm là SiteCraft; font
SVN-Avo do người dùng cung cấp, giữ nguyên tệp và thông báo quyền gốc.

Đây là đối chiếu phạm vi chức năng, không phải tuyên bố mọi dịch vụ bên ngoài
hay mọi đầu ra SKP trên mọi máy đã được kiểm tra. Kết quả kiểm tra cụ thể nằm
trong [VALIDATION.md](VALIDATION.md).

| Phần của bản cũ | SiteCraft 0.4.0 |
| --- | --- |
| Tải và ghép tile ảnh, cắt theo vùng chọn | Dùng lại hàm gốc, giữ URL/cache/crop/resize và JPEG |
| Esri sạch, Google vệ tinh/hybrid/đường phố | Giữ nguồn chọn của bộ dựng gốc; cần dịch vụ còn hoạt động |
| Tọa độ WGS84/ENU, đơn vị mét, tile zoom | 11 hàm gốc đã khôi phục, đối chiếu số học chính xác |
| DEM Terrarium và nội suy lưới | Dùng lại giải mã, nội suy và mốc cao độ của gốc |
| Địa hình nổi có thành/đáy khối | Dùng lại `build_terrain_mesh_with_plinth`, không chỉ tấm ảnh phẳng |
| Nền phẳng và trám đồi | Giữ nhánh dựng phẳng/khối đồi và xử lý mốc/rìa của gốc |
| Dữ liệu đường, nhà và nước | Giữ giải mã OpenFreeMap MVT, Overpass chia vùng/cache/dự phòng |
| Giờ cao điểm và nguồn OSM thiếu dữ liệu | Giữ chiến lược MVT/Overpass và cờ suy giảm của gốc |
| Bù đường/nhà khi vector chưa đủ | Giữ phân loại màu Google đường phố, làm mảnh/truy tim và tìm khối nhà |
| Đường chính/ngõ theo địa hình | Giữ phân loại bề rộng và quét dải đường của gốc |
| Chiều cao nhà từ height/levels/footprint | Giữ quy tắc suy ra và biến thiên ổn định theo ID của gốc |
| Nhà có khối đế, tầng giật cấp, khối mái | Giữ dựng khối công trình của gốc, không chỉ extrude một hộp |
| Mặt đứng, mái, gờ mái | 22 hàm texture đã khôi phục; 8 mặt đứng + 4 mái + 1 gờ mặc định trùng byte |
| Nhà box trắng | Giữ nhánh vật liệu/hình học tương ứng của gốc |
| Mặt nước, công viên, cây | Giữ nhánh dựng cảnh và cây kiến trúc của gốc trong phạm vi dữ liệu có |
| OBJ + MTL + ảnh | Dùng bộ ghi gốc; tọa độ, UV, vật liệu và byte ảnh được đối chiếu |
| GLB, gói cảnh, JSON fallback | Dùng bộ ghi gốc; không dựng lại mesh bằng bộ ghi độc lập cũ |
| Ghi SKP bằng SDK | Mã 14 hàm được khôi phục; cần Windows và DLL tương thích thật, chưa kiểm tra lưu native thật |
| Nạp khi SDK chưa sẵn sàng | Có JSON/texture fallback thành hình học chỉnh sửa được trong SketchUp |
| Tọa độ từ văn bản/link và OCR ảnh | 6 hàm nguồn đã khôi phục; OCR Windows thật có giới hạn kiểm tra riêng |
| Tìm kiếm, gợi ý, tọa độ/DMS/link | Có luồng tìm kiếm trong UI mới; dịch vụ tìm địa danh vẫn là dịch vụ ngoài |
| Tùy chọn, tiến trình, xuất, ghép mảnh | Cùng một thanh bên; không chia thành ba bảng điều khiển |
| Chế độ xem 2D/3D, sáng/tối | Có; viewer/giao diện thuộc mã tích hợp mới |
| Tự nạp, Group/Tag, mở thư mục, bóng nắng, Undo | Có cầu nối Ruby; cần kiểm tra thao tác bằng SketchUp Desktop thật |
| Mốc chung và ghép các mảnh | Giữ thông tin tọa độ gốc qua adapter; ghép dự án xa nhau vẫn có giới hạn ENU |
| Runtime tự chứa | Windows Full có Python/NumPy/Pillow/Requests/OCR theo lockfile |
| Đăng nhập/Supabase | Không cần khi chạy Windows Full; máy chủ riêng là tùy chọn nâng cao |
| Xu/tín dụng/gói trả phí | Không có trong luồng tích hợp SiteCraft |
| Google Photorealistic 3D | Chưa khôi phục, không thuộc bộ dựng OSM/DEM này |
| Tài khoản/backend thương mại, chữ ký cập nhật cũ | Không chuyển thành backend SiteCraft |
| Chính sách native tùy chọn trong mã gốc | Giữ nhánh kiểm tra bình thường; không tạo giấy phép hoặc chữ ký thay thế |

Địa hình/nhà giống thuật toán gốc khi cùng dữ liệu và tham số trong những ca đã
đối chiếu. Cùng địa điểm nhưng khác ngày, tile, mức zoom hoặc dữ liệu OSM có thể
cho cảnh khác. Phần bù từ ảnh màu chỉ suy ra hình khối; không tạo dữ liệu khảo
sát hoặc mặt đứng thật. Việc chuyển mã không bảo đảm nguồn ảnh/OSM luôn đáp ứng.

`server/original_kernel/` chứa năm tệp `.py` khôi phục và manifest kiểm tra byte.
`reference/` giữ tệp gốc đọc được để đối chiếu, không được nạp lúc chạy RBZ.
Các thư mục này và font không tự trở thành MIT. Xem [NOTICE.md](../NOTICE.md).
Người dùng đã xác nhận công bố phần nguồn khôi phục trong ZNS ngày 17/11/2026; quyền của các thành phần được giữ nguyên.
