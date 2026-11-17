# SiteCraft 0.4.2

Bản này sửa cây quá lớn: cây có chiều cao **4–6,5 m**, bán kính tán tối đa
**2 m** (rộng tối đa 4 m). Cụm tán lớn trên ảnh có thể tạo một nhóm cây nhỏ
khi ảnh cho thấy các đỉnh riêng. Thân trụ ngắn, tán cầu và năm sắc xanh nhẹ
được giữ từ bản trước.

## Kích thước và vị trí cây

Trước đây mô hình dùng trực tiếp bán kính tán ước lượng từ ảnh; một vùng tán
rộng có thể thành một cây rất lớn. Bản 0.4.2 lưu bán kính nhận từ ảnh riêng với
bán kính và chiều cao dùng để dựng mô hình. Chiều cao hiển thị được giới hạn
4–6,5 m, kể cả khi thông tin chiều cao OSM lớn hơn. Đây là tỷ lệ cây minh họa
trong bối cảnh kiến trúc, không phải chiều cao đã đo tại hiện trường.

Ứng viên tán có bán kính lớn hơn 3 m được kiểm tra thêm. Chỉ tạo nhóm **2–6
cây nhỏ** khi có các đỉnh sáng/kết cấu riêng, có vùng thấp hơn giữa các đỉnh,
và các tâm nằm trong vùng xanh đã xác nhận của tán gốc. Tán rộng nhưng trơn,
không có thêm đỉnh rõ ràng, vẫn là một cây nhỏ. Không rải cây ngẫu nhiên hoặc
theo lưới ra ngoài vùng tán.

Điểm đặt vẫn phải có bằng chứng tán trên ảnh. Dữ liệu OSM dùng để đối chiếu;
điểm OSM hoặc nhãn rừng/công viên/hàng cây không tự tạo cây khi ảnh chưa đủ
bằng chứng. Các tâm được lọc theo nhà, đường, nước và mặt địa hình đã dựng.
Địa hình, footprint công trình, đường và cao độ mặt đất không bị thay đổi bởi
bước thu nhỏ/tách cụm cây.

Giới hạn vẫn là **900 cây mỗi mảnh**, mỗi cây tối đa **200 tam giác**; số cây
có thể giảm khi cảnh đã gần giới hạn tam giác. Trong Tùy chỉnh chi tiết, **Mức
nhận diện** có ba mức **Thận trọng / Chuẩn / Nhiều hơn**. Các mức điều chỉnh
lọc ứng viên theo ảnh, không thêm vị trí để đạt một số cây định trước.

Ảnh độ phân giải thấp, bóng che và các tán sát nhau có thể gây bỏ sót hoặc
nhầm ứng viên. Vị trí, kích thước và chiều cao mô hình là ước lượng từ ảnh và
nguồn đối chiếu; đây không phải mô hình AI đã huấn luyện hay dữ liệu trắc địa.

## Địa hình và xuất tệp

Giữ sửa lỗi DEM của 0.4.1: **Địa hình 3D** mặc định có đủ vùng chữ nhật, cao độ
mép, thành và đáy khối, kể cả sau khi nạp nền phẳng. **Trám đồi** chỉ chạy khi
người dùng chọn riêng trên mô hình có nền phẳng. Mốc chung và độ dịch cao độ
được giữ, áp một lần khi đặt mảnh; không hạ bốn mép DEM thường về Z = 0.

Cây được thêm vào cảnh trước cùng các bộ ghi OBJ/MTL/ảnh, GLB, SKP và mesh nạp
SketchUp. Năm mô-đun trong `original_kernel` không đổi. Windows Full tiếp tục
mở bản đồ trực tiếp, không cần đăng nhập/Supabase, xu hoặc tín dụng; giữ giao
diện một thanh bên và bốn kiểu font SVN-Avo.

## Cài và kiểm tra

Gói của Release `sitecraft-v0.4.2`:

- [SiteCraft_Full_0.4.2_Windows_x64.rbz](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Full_0.4.2_Windows_x64.rbz).
- [SiteCraft_Source_0.4.2.zip](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Source_0.4.2.zip).
- [SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SHA256SUMS.txt).

Cài RBZ bằng SketchUp → Extension Manager → Install Extension…, rồi thoát hết
SketchUp và mở lại để nạp mã mới. Dựng lại mảnh để áp dụng kích thước cây mới;
những nhóm đã nạp trước đó không tự thay đổi. Xem [README](../README_VI.md).

Ca kiểm tra ảnh tổng hợp với ba đỉnh rõ trong một tán lớn tạo ba cây nhỏ ở ba
tâm tương ứng. Ca có khoảng trống giữ tâm cây ngoài khoảng trống; vùng cỏ
đồng đều không tự sinh cây. Các ca này kiểm tra quy tắc tách cụm, không xác
nhận độ chính xác trên mọi ảnh thực tế.

Kiểm tra Windows của đúng gói là điều kiện phát hành 0.4.2. Bằng chứng của
[0.4.1](RELEASE_0.4.1.md) và [0.4.0](RELEASE_0.4.0.md) giữ riêng theo phiên bản;
không dùng kết quả bản cũ thay cho kiểm tra gói mới. Người dùng đã xác nhận
plugin hoạt động trong SketchUp; nhóm kiểm tra chưa xác minh đầy đủ lưu/mở
SKP native bằng SDK thật trên Windows. Khi SDK chưa sẵn sàng, mesh/texture
vẫn hỗ trợ nạp và lưu qua SketchUp.

Mã tích hợp mới giữ MIT; mã khôi phục và font giữ quyền gốc. Việc công bố nguồn
và bốn font đã được người dùng xác nhận. Xem [NOTICE.md](../NOTICE.md).
