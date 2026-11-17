# SiteCraft 0.4.2 — bản đồ và địa hình cho SketchUp

SiteCraft mở thẳng bản đồ khi chạy Windows Full, không cần đăng nhập hoặc
Supabase, không có xu, tín dụng hay tính lượt xuất. Điều khiển vùng chọn,
địa hình, công trình, tiến trình, xuất tệp và ghép mảnh nằm trong một thanh bên.
Giao diện dùng các tệp SVN-Avo do người dùng cung cấp, có đủ bốn kiểu chữ.
Bản 0.4.2 thu nhỏ cây về chiều cao 4–6,5 m, tán rộng tối đa 4 m. Cụm tán lớn
trên ảnh có thể tạo 2–6 cây nhỏ khi có các đỉnh ảnh riêng rõ ràng. Địa hình DEM
vẫn giữ đủ vùng chữ nhật cùng thành/đáy khối, kể cả khi đã có nền phẳng.

Bản 0.4.0 chuyển sang **mã Python có thể đọc và sửa của bộ dựng MapSKP cũ**:
51 hàm dựng cảnh, 11 hàm tọa độ, 22 hàm texture mặt đứng/mái, 14 hàm ghi tệp
và 6 hàm tọa độ/OCR. Các mô-đun nằm trong `server/original_kernel/`; không còn
trình nạp `.marshal` hoặc `.pyc` trong thư mục này. Phần tích hợp Ruby/API/UI
của SiteCraft vẫn có mã nguồn riêng.

Người dùng đã xác nhận công bố SiteCraft cùng năm mô-đun nguồn khôi phục trong
repository `nkl12012004-cmd/ZNS` ngày 17/11/2026, theo giờ Việt Nam.
Các gói của Release `sitecraft-v0.4.2`:

- [SiteCraft_Full_0.4.2_Windows_x64.rbz](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Full_0.4.2_Windows_x64.rbz): bộ cài có runtime Windows.
- [SiteCraft_Source_0.4.2.zip](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SiteCraft_Source_0.4.2.zip): mã nguồn, tài liệu và bộ cài trong `install/`.
- [SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.2/SHA256SUMS.txt): checksum của hai gói.

Kiểm tra Windows của đúng gói là điều kiện phát hành bản 0.4.2.
Ghi chú thay đổi: [RELEASE_0.4.2.md](docs/RELEASE_0.4.2.md).

Bằng chứng của **bản 0.4.0** vẫn được giữ để đối chiếu: bản đó đã công bố sau [kiểm tra Windows đầy đủ](https://github.com/nkl12012004-cmd/ZNS/actions/runs/44022035961): 86 bài đạt, hai bài bỏ qua đúng điều kiện; OCR Tesseract, HTTPS, kết nối Ruby, khởi động lại và dừng worker theo tiến trình cha đều đạt.
Tệp 0.4.0 đã tải lại và kiểm tra SHA-256/CRC; bộ cài trong ZIP nguồn của bản đó trùng từng byte với RBZ phát hành.

Mã tích hợp mới giữ giấy phép MIT; mã MapSKP khôi phục và font giữ quyền gốc.
Chưa tìm thấy giấy phép nguồn mở cho mã gốc trong ZIP được cung cấp. Vì vậy,
“có mã nguồn chỉnh sửa được” không đồng nghĩa toàn bộ gói được cấp phép MIT.
Quyền gốc của các thành phần vẫn được giữ nguyên sau khi công bố.
Xem [NOTICE.md](NOTICE.md).

## Cài Windows Full

1. SketchUp → Extension Manager → Install Extension… → chọn
   `SiteCraft_Full_0.4.2_Windows_x64.rbz`.
2. Thoát hoàn toàn tất cả cửa sổ SketchUp rồi mở lại để nạp mã Ruby mới.
3. Extensions → SiteCraft → Mở SiteCraft, hoặc bấm biểu tượng trên toolbar.
4. Chờ bộ xử lý trên máy khởi động. Không cần điền Email, Google hay Supabase.
5. Tìm địa điểm hoặc dán tọa độ/link Google Maps, chọn vùng và các lớp cần dựng.
6. Bấm Đưa vào SketchUp; khi tác vụ xong, nạp mô hình hoặc lưu tệp xuất.

Windows Full kèm CPython 3.14.10, NumPy 2.5.3, Pillow 12.2.0, Requests 2.33.1
và Tesseract/English theo `tools/runtime.lock.json`. Không cần tự cài Python/pip.
Bản đồ, DEM và OSM vẫn cần Internet. Mục tiêu là Windows 10/11 x64 và SketchUp
Desktop có Ruby/HtmlDialog, từ 2021 trở lên. Người dùng đã xác nhận bản 0.4.0
chạy được trong SketchUp; việc lưu/mở SKP native bằng SDK thật chưa được nhóm
kiểm tra xác minh.

Cấu hình mặc định chạy bộ xử lý trên máy. Nếu đang dùng URL máy chủ riêng bị
lỗi, mở Cấu hình và chọn chạy trên máy này; có nút khởi động lại và mở log.
Đường dẫn nội bộ `openmap_sketchup`, biến `OPENMAP_*` và dữ liệu cấu hình cũ
được giữ để tương thích nâng cấp. Tên hiển thị của sản phẩm là SiteCraft.
Hướng dẫn 0.3.0 trong tài liệu cũ chỉ dùng để tham khảo; hướng dẫn 0.4.2 ở đây
và [ghi chú bản 0.4.2](docs/RELEASE_0.4.2.md) được ưu tiên.
[Ghi chú 0.4.1](docs/RELEASE_0.4.1.md) và [0.4.0](docs/RELEASE_0.4.0.md) giữ
lịch sử thay đổi cùng bằng chứng của các lần kiểm tra trước.

## Quy trình dựng đã chuyển từ bản cũ

Bộ dựng dùng lại cách lấy dữ liệu và tạo hình của mã gốc, thay cho hình học
xấp xỉ riêng của các bản OpenMap trước:

1. Chuyển vùng địa lý sang hệ tọa độ mét, tải các tile ảnh và ghép/cắt texture.
   Vệ tinh sạch dùng Esri; Google vệ tinh, hybrid và đường phố giữ cách chọn
   nguồn của bộ dựng gốc.
2. Tải DEM Terrarium, giải mã cao độ, nội suy lưới và dựng địa hình có thành
   cùng đáy khối. Nền phẳng và trám đồi giữ các nhánh dựng tương ứng của bản cũ.
3. Lấy đường/nhà/nước từ OpenFreeMap MVT, sau đó dùng Overpass khi dữ liệu chưa
   đủ. Cách chia vùng, cache, chọn nguồn dự phòng và xử lý giờ cao điểm được giữ.
4. Khi cần bù phần thiếu, đọc màu đường và footprint trong ảnh Google đường phố
   không nhãn, thu mảnh đường thành tim tuyến và tìm các khối nhà ứng viên.
5. Dựng đường theo địa hình; dựng nhà từ footprint, chiều cao/số tầng hoặc quy
   tắc suy ra của bản cũ. Nhà có thể có khối đế, tầng giật cấp, khối mái và gờ mái.
   Texture mặt đứng, mái và gờ được tạo bằng đúng bộ hàm đã khôi phục.
6. Chuyển cảnh sang OBJ/MTL/ảnh, GLB hoặc JSON nạp SketchUp bằng bộ ghi gốc.
   GLB có thêm bước sửa tương thích khi nhóm mặt bị gán texture nhưng thiếu UV.
   Nhánh SKP SDK được thử khi có môi trường Windows và DLL phù hợp; nếu chưa
   sẵn sàng, dùng mesh có thể chỉnh sửa để nạp và lưu bằng SketchUp.

Với GLB cần sửa, SiteCraft giữ tệp nguyên bản thành `<tên>_original.glb` và chỉ
đổi liên kết vật liệu trên nhóm mặt (primitive) thiếu UV: tạo bản sao vật liệu màu theo RGBA
của cảnh, bỏ texture không có tọa độ để ánh xạ. Hình học, UV đã có và toàn bộ
byte BIN/ảnh được giữ nguyên. Báo cáo nằm trong `original_manifest.glb_compatibility`.
Vì vậy GLB giao cho người dùng có thể khác byte tệp của bộ ghi gốc; tệp không
cần sửa được giữ đúng byte.

Nhà và ảnh mặt đứng vẫn là mô hình suy ra, không phải bản quét mặt đứng thật.
Bù dữ liệu từ màu bản đồ là phép ước lượng; khôi phục thuật toán không bổ sung
những công trình mà nguồn dữ liệu không có. Dữ liệu/ảnh của cùng một vùng có
thể thay đổi theo thời gian hoặc theo tình trạng dịch vụ.

## Giao diện và thao tác

- Một thanh bên chứa tùy chọn và tiến trình; chỉ vùng xem bản đồ chuyển 2D/3D.
- Tìm tên địa điểm, chọn gợi ý bằng chuột/phím, dán tọa độ thập phân/DMS hoặc
  link Google Maps có tọa độ; có OCR ảnh và dán ảnh từ clipboard.
- Preset 200/380/600/1000 m, nhập kích thước và kéo góc khung vùng chọn.
- Chọn nền phẳng/DEM, ảnh 1K–8K, độ phân giải lưới và hệ số cao độ.
- Bật riêng đường chính/ngõ, nhà cao/thấp tầng, nước và **Cây tán tròn**; chọn
  box trắng hoặc map công trình. Các lớp được nạp theo Group/Tag.
- Trong Tùy chỉnh chi tiết, **Mức nhận diện** có ba mức **Thận trọng / Chuẩn /
  Nhiều hơn**, cùng tùy chọn đối chiếu ảnh/OSM. Thiếu dấu hiệu tán riêng trên
  ảnh thì bỏ qua vị trí đó.
- Tự nạp sau khi dựng, nạp thủ công, OBJ + ảnh, GLB, SKP, mở thư mục xuất,
  bóng nắng, Undo và ghép các mảnh theo mốc chung.

Nếu thiếu một lớp dữ liệu, đọc cảnh báo của tác vụ trước khi nạp. Một vùng không
có nhà trong OSM có thể vẫn có nền/DEM hợp lệ. Tệp đã dựng cần được lưu sau khi
hoàn thành; bộ xử lý có thể dọn tác vụ và cache theo chính sách vận hành.

## Địa hình và cây trong bản 0.4.2

**Địa hình 3D** mặc định dùng DEM đủ vùng chữ nhật, giữ cao độ mép và khối đế
có thành/đáy như nhánh DEM thường của bộ dựng cũ. Nạp sau một mảnh phẳng
không tự chuyển sang trám đồi. **Trám đồi** là lựa chọn riêng cho trường hợp
cần nối đồi với nền phẳng; nhánh này cố ý hạ mép về nền và cắt theo chân đồi.
Mốc chung và độ dịch của mảnh vẫn được giữ; sửa lựa chọn nhánh không làm
thay đổi dữ liệu DEM gốc.

Cây có thân trụ ngắn và tán cầu với năm sắc xanh nhẹ, chiều cao **4–6,5 m**,
bán kính tán tối đa **2 m** (rộng 4 m). Giới hạn hiển thị này áp dụng cả khi
OSM có chiều cao lớn hơn. Tối đa **900 cây mỗi mảnh**, mỗi cây tối đa **200
tam giác**. Vị trí lấy từ tâm ứng viên tán riêng trên ảnh vệ tinh, xét viền,
kết cấu và tương phản ở nhiều tỷ lệ. Không rải cây ngẫu nhiên hoặc theo lưới
vào vùng xanh, rừng hay công viên. Cây được đặt trên mặt địa hình đã dựng và
lọc vị trí có nhà/đường/nước trong cảnh.

Với ứng viên tán rộng hơn 3 m theo bán kính, chỉ tạo nhóm **2–6 cây nhỏ** khi
ảnh có các đỉnh sáng/kết cấu riêng, cách nhau bởi vùng thấp hơn và nằm trong
vùng xanh đã xác nhận của tán gốc. Tán rộng nhưng trơn, không có thêm đỉnh rõ
ràng, vẫn dùng một cây nhỏ. Bán kính nhận từ ảnh được lưu riêng với bán kính
và chiều cao dùng để hiển thị mô hình.

Truy vấn OSM riêng bổ sung cây mà đường lấy MVT nhanh của bản cũ có thể bỏ
qua, để đối chiếu với ứng viên trên ảnh. Điểm OSM, nhãn rừng/hàng cây hoặc
nhãn công viên không tự tạo vị trí khi ảnh chưa có dấu hiệu tán tương ứng.
Tắt bổ sung từ ảnh chỉ giữ ứng viên tán có đối chiếu cây OSM.

Vùng xanh, màu và kết cấu đơn thuần không bảo đảm nhận ra đúng mọi cây, nhất
là ảnh ít chi tiết, tán sát nhau hoặc có bóng che. Ứng viên mơ hồ bị bỏ qua;
không tự lấp thêm cây vào chỗ chưa nhận ra tán. Đây là phương pháp xử lý ảnh
để tìm ứng viên, không phải mô hình AI đã huấn luyện hay dữ liệu trắc địa.
Kích thước tán và chiều cao mô hình vẫn là ước lượng. Cây được xuất cùng OBJ,
GLB, SKP hoặc mesh nạp SketchUp. Phần tích hợp mới nằm ngoài `original_kernel`;
năm mô-đun khôi phục được giữ nguyên.

## Phạm vi và giới hạn

Bằng chứng bộ dựng gốc từ bản 0.4.0: mã địa hình, nhà, texture và bộ ghi được
đối chiếu với chương trình gốc trong các ca đã kiểm tra; kết quả và giới hạn nằm trong
[VALIDATION.md](docs/VALIDATION.md). Một vùng Quỳnh Lưu dùng lại dữ liệu cache
cho cùng 7.316 đỉnh, 10.500 tam giác, vật liệu và texture như cảnh gốc.
87 bài kiểm tra máy chủ đạt, một bài bỏ qua đúng điều kiện. GLB mẫu sau sửa
tương thích đạt glTF Validator với 0 lỗi và 0 cảnh báo; đây không phải kiểm tra
mọi mô hình hoặc thay thế việc mở bằng SketchUp.

Người dùng đã xác nhận plugin 0.4.0 hoạt động trong SketchUp. Nhóm kiểm tra
chưa xác minh đầy đủ việc lưu/mở SKP bằng SDK thật trên Windows, vật liệu, Undo
và vị trí mảnh bằng SketchUp Desktop. Kiểm tra dấu vết lời gọi SDK hoặc tệp
OBJ/GLB không thay thế kiểm tra SKP native. Nhánh mesh/texture vẫn hỗ trợ nạp
và lưu mô hình qua SketchUp khi SDK không sẵn sàng.
Google Photorealistic 3D và cơ chế cập nhật/chữ ký/tài khoản của nhà cung cấp cũ
không nằm trong phạm vi khôi phục này. Nhánh chính sách native tùy chọn của mã
khôi phục được giữ nguyên; không tạo giấy phép hoặc chữ ký thay thế.

Ghép mảnh có mốc khác nhau dùng phép dịch trong hệ tọa độ cục bộ; đây không
phải công cụ trắc địa được chứng nhận. Giữ cùng mốc và hệ số cao độ trong dự án.
Nguồn ảnh, OSM/DEM và SDK có điều kiện cung cấp/giấy phép riêng.

## Chỉnh sửa và kiểm tra mã

```text
extension/openmap_sketchup.rb             đăng ký extension
extension/openmap_sketchup/main.rb        cầu nối Ruby/API
extension/openmap_sketchup/importer.rb    nạp mesh và vật liệu
extension/openmap_sketchup/ui/            giao diện và font SVN-Avo
server/openmap_server/original_engine.py  nối API với bộ dựng khôi phục
server/openmap_server/original_scene.py   chuyển cảnh giữ tọa độ/UV/vật liệu
server/openmap_server/glb_compat.py       sửa liên kết texture GLB khi thiếu UV
server/openmap_server/tree_geometry.py    thân trụ và tán cầu mới của SiteCraft
server/openmap_server/simple_trees.py     đặt cây tại tâm tán và lọc theo cảnh
server/openmap_server/canopy_detector.py  tìm ứng viên tán riêng trên ảnh
server/openmap_server/tree_data.py        truy vấn OSM riêng cho cây/vùng cây
server/original_kernel/                   5 mô-đun Python gốc đã khôi phục
server/original_kernel/recovery-manifest.json  kích thước và SHA-256 mã gốc
server/openmap_server/                    API, tác vụ, tìm kiếm và mã tích hợp
server/tests/                            kiểm tra mã tích hợp
tools/build.py                           xác minh mã nguồn và tạo gói cục bộ
```

Môi trường tự phát triển bộ dựng dùng CPython 3.14 và các dependency được ghim:

```sh
cd server
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Trên Windows dùng `.venv\Scripts\python.exe`; đặt
`PYTHONDONTWRITEBYTECODE=1` trước khi chạy để không sinh cache trong thư mục
mã khôi phục. Chế độ máy chủ riêng nâng cao có cấu hình Supabase riêng, không
cần cho Windows Full. Mẫu `server/.env.example` không chứa khóa thật; không
đưa `.env` vào gói hoặc repository.

Các lệnh UI/Ruby nằm trong `tools/package.json`. Để chuẩn bị gói cục bộ sau khi
hoàn thành kiểm tra:

```sh
python tools/prepare_runtime.py
python tools/build.py
```

Trình đóng gói kiểm tra SHA-256/kích thước của năm tệp nguồn, từ chối bytecode,
vault/armor và native binary trong `original_kernel`, giữ các thông báo font và
thư viện, loại `.env`, cache và kết quả thử nghiệm tạm. Gói nguồn vẫn có mã
kiểm tra. Build không tự upload hoặc tạo GitHub Release.
