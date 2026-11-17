# SiteCraft 0.4.1

Bản này thêm **cây thân trụ ngắn, tán tròn**, với năm sắc xanh nhẹ, đặt tại tâm
ứng viên tán riêng trên ảnh vệ tinh. Đồng thời sửa việc chọn địa hình: DEM
thường giữ đủ vùng và khối đế, không tự chuyển sang trám đồi khi đã có nền
phẳng. Các thay đổi tích hợp nằm ngoài bộ dựng MapSKP đã khôi phục; năm
mô-đun gốc không đổi.

Windows Full tiếp tục mở thẳng bản đồ, không cần đăng nhập/Supabase, xu hoặc
tín dụng. Giao diện giữ một thanh bên, tên SiteCraft và bốn kiểu font SVN-Avo.

## Địa hình DEM thường và trám đồi

Chọn **Địa hình 3D** mặc định dựng đủ lưới DEM trong vùng chữ nhật, giữ cao độ
bốn mép và khối đế có thành/đáy của nhánh dựng cũ. Một mảnh phẳng đã có trong
mô hình không còn tự kích hoạt cách dựng đồi với mép hạ về Z = 0.

**Trám đồi** chỉ chạy khi người dùng chọn riêng cho mô hình có nền phẳng. Nó
giữ cách cắt chân đồi và hạ mép của nhánh cũ. Hai chế độ cùng giữ mốc địa lý,
hệ số cao độ và độ dịch mảnh; không sửa các đỉnh để ép DEM thường về nền.

## Cây theo tán trên ảnh

Bật **Cây tán tròn**. Trong **Tùy chỉnh chi tiết**, chọn **Mức nhận diện**:
**Thận trọng / Chuẩn / Nhiều hơn**. Các mức thay đổi cách lọc ứng viên, không
tạo vị trí ngẫu nhiên để đạt số lượng. Vị trí được lấy từ tâm các ứng viên
tán riêng trên ảnh vệ tinh, dựa trên viền, kết cấu và
tương phản ở nhiều tỷ lệ. Không rải ngẫu nhiên hoặc tạo lưới cây trong vùng
xanh/rừng/công viên. Khi chưa có dấu hiệu một tán tương ứng, vị trí bị bỏ qua.

Mỗi cây tối đa **200 tam giác**, gồm thân trụ có nắp và tán cầu kín; tối đa
**900 cây mỗi mảnh**, còn phụ thuộc ngân sách tam giác của toàn cảnh. Thân
chạm địa hình đã dựng và nối vào tán; vị trí được lọc theo nhà, đường và mặt
nước có trong cảnh. Kích thước tán và chiều cao mô hình vẫn là ước lượng. Cây
đi qua cùng quy trình xuất OBJ, GLB, SKP và nạp mesh.

Truy vấn OSM riêng bổ sung cây mà nhánh MVT nhanh có thể bỏ qua, để đối chiếu
với ứng viên tán. Nhãn rừng/hàng cây/công viên hoặc điểm OSM chưa được ảnh
ủng hộ không tự sinh cây. Khi tắt bổ sung từ ảnh, chỉ giữ ứng viên tán có đối
chiếu cây OSM; trạng thái nguồn và vị trí đã chọn được ghi trong tác vụ.

Đây là xử lý ảnh để tìm ứng viên, không phải mô hình AI đã huấn luyện hoặc dữ
liệu trắc địa. Màu xanh và kết cấu đơn thuần không bảo đảm phát hiện đủ hay
đúng mọi cây. Ảnh độ phân giải thấp, bóng che và tán sát nhau có thể khiến
ứng viên không rõ hoặc bị bỏ qua. Không tự thêm cây để bù số lượng ở vùng
chưa nhận ra tán.

## Cài và kiểm tra

Gói của Release `sitecraft-v0.4.1`:

- [SiteCraft_Full_0.4.1_Windows_x64.rbz](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.1/SiteCraft_Full_0.4.1_Windows_x64.rbz).
- [SiteCraft_Source_0.4.1.zip](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.1/SiteCraft_Source_0.4.1.zip).
- [SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.1/SHA256SUMS.txt).

Cài RBZ bằng SketchUp → Extension Manager → Install Extension…, rồi thoát hết
SketchUp và mở lại. Hướng dẫn đầy đủ nằm trong [README](../README_VI.md).

Kiểm tra Windows của đúng gói là điều kiện phát hành 0.4.1. Bằng chứng Windows
của [bản 0.4.0](RELEASE_0.4.0.md) được giữ riêng và không thay thế kết quả của
bản này. Kiểm tra hình học cây đã xác nhận lưới kín, chiều mặt hướng ra ngoài,
không có tam giác suy biến tại cực tán, thân chạm đất và giao vào tán.

Kiểm tra DEM dùng lưới cao độ có bốn mép không phẳng: chế độ thường giữ nguyên
256 đỉnh/450 tam giác mặt trên và khối đế sâu 4 m; trường hợp đã có nền phẳng
giữ cùng dữ liệu và chỉ áp độ dịch cao độ một lần. Nhánh trám đồi chỉ chạy
khi được chọn rõ. Các mảng đỉnh, tam giác, UV và byte texture được đối chiếu
với nhánh tương ứng của mã gốc trong fixture ngoại tuyến.

Người dùng đã xác nhận bản 0.4.0 chạy được trong SketchUp. Nhóm kiểm tra chưa
xác minh việc lưu/mở SKP native bằng SDK thật trên Windows; khi SDK chưa sẵn
sàng, mesh/texture vẫn hỗ trợ nạp và lưu bằng SketchUp. Không coi kiểm tra
OBJ/GLB hoặc dấu vết lời gọi SDK là bằng chứng SKP native đã mở thành công.

Mã tích hợp mới giữ MIT; mã khôi phục và font giữ quyền gốc. Việc công bố nguồn
và bốn font đã được người dùng xác nhận. Xem [NOTICE.md](../NOTICE.md).
