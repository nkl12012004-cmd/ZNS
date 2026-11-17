# SiteCraft 0.4.0 — bản đồ và địa hình cho SketchUp

SiteCraft mở thẳng bản đồ khi chạy Windows Full, không cần đăng nhập hoặc
Supabase, không có xu, tín dụng hay tính lượt xuất. Điều khiển vùng chọn,
địa hình, công trình, tiến trình, xuất tệp và ghép mảnh nằm trong một thanh bên.
Giao diện dùng các tệp SVN-Avo do người dùng cung cấp, có đủ bốn kiểu chữ.

Bản 0.4.0 chuyển sang **mã Python có thể đọc và sửa của bộ dựng MapSKP cũ**:
51 hàm dựng cảnh, 11 hàm tọa độ, 22 hàm texture mặt đứng/mái, 14 hàm ghi tệp
và 6 hàm tọa độ/OCR. Các mô-đun nằm trong `server/original_kernel/`; không còn
trình nạp `.marshal` hoặc `.pyc` trong thư mục này. Phần tích hợp Ruby/API/UI
của SiteCraft vẫn có mã nguồn riêng.

Người dùng đã xác nhận công bố SiteCraft cùng năm mô-đun nguồn khôi phục trong
repository `nkl12012004-cmd/ZNS` ngày 17/11/2026, theo giờ Việt Nam.
Các gói của Release `sitecraft-v0.4.0`:

- [SiteCraft_Full_0.4.0_Windows_x64.rbz](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Full_0.4.0_Windows_x64.rbz): bộ cài có runtime Windows.
- [SiteCraft_Source_0.4.0.zip](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SiteCraft_Source_0.4.0.zip): mã nguồn, tài liệu và bộ cài trong `install/`.
- [SHA256SUMS.txt](https://github.com/nkl12012004-cmd/ZNS/releases/download/sitecraft-v0.4.0/SHA256SUMS.txt): checksum của hai gói.

Release được công bố sau khi kiểm tra Windows của đúng gói đạt. Các liên kết
tải có hiệu lực khi Release được công bố; kết quả Windows đầy đủ chưa được
ghi nhận tại thời điểm cập nhật tài liệu này.

Mã tích hợp mới giữ giấy phép MIT; mã MapSKP khôi phục và font giữ quyền gốc.
Chưa tìm thấy giấy phép nguồn mở cho mã gốc trong ZIP được cung cấp. Vì vậy,
“có mã nguồn chỉnh sửa được” không đồng nghĩa toàn bộ gói được cấp phép MIT.
Quyền gốc của các thành phần vẫn được giữ nguyên sau khi công bố.
Xem [NOTICE.md](NOTICE.md).

## Cài Windows Full

1. SketchUp → Extension Manager → Install Extension… → chọn
   `SiteCraft_Full_0.4.0_Windows_x64.rbz` đã được bàn giao.
2. Thoát hoàn toàn tất cả cửa sổ SketchUp rồi mở lại để nạp mã Ruby mới.
3. Extensions → SiteCraft → Mở SiteCraft, hoặc bấm biểu tượng trên toolbar.
4. Chờ bộ xử lý trên máy khởi động. Không cần điền Email, Google hay Supabase.
5. Tìm địa điểm hoặc dán tọa độ/link Google Maps, chọn vùng và các lớp cần dựng.
6. Bấm Đưa vào SketchUp; khi tác vụ xong, nạp mô hình hoặc lưu tệp xuất.

Windows Full kèm CPython 3.14.10, NumPy 2.5.3, Pillow 12.2.0, Requests 2.33.1
và Tesseract/English theo `tools/runtime.lock.json`. Không cần tự cài Python/pip.
Bản đồ, DEM và OSM vẫn cần Internet. Mục tiêu là Windows 10/11 x64 và SketchUp
Desktop có Ruby/HtmlDialog, từ 2021 trở lên; kiểm tra thực tế trong SketchUp
trên máy người dùng vẫn cần thực hiện.

Cấu hình mặc định chạy bộ xử lý trên máy. Nếu đang dùng URL máy chủ riêng bị
lỗi, mở Cấu hình và chọn chạy trên máy này; có nút khởi động lại và mở log.
Đường dẫn nội bộ `openmap_sketchup`, biến `OPENMAP_*` và dữ liệu cấu hình cũ
được giữ để tương thích nâng cấp. Tên hiển thị của sản phẩm là SiteCraft.
Hướng dẫn 0.3.0 trong tài liệu cũ chỉ dùng để tham khảo; hướng dẫn 0.4.0 ở đây
và [ghi chú bản 0.4.0](docs/RELEASE_0.4.0.md) được ưu tiên.

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
- Bật riêng đường chính/ngõ, nhà cao/thấp tầng, nước và cây; chọn box trắng hoặc
  map công trình. Các lớp được nạp theo Group/Tag.
- Tự nạp sau khi dựng, nạp thủ công, OBJ + ảnh, GLB, SKP, mở thư mục xuất,
  bóng nắng, Undo và ghép các mảnh theo mốc chung.

Nếu thiếu một lớp dữ liệu, đọc cảnh báo của tác vụ trước khi nạp. Một vùng không
có nhà trong OSM có thể vẫn có nền/DEM hợp lệ. Tệp đã dựng cần được lưu sau khi
hoàn thành; bộ xử lý có thể dọn tác vụ và cache theo chính sách vận hành.

## Phạm vi và giới hạn

Mã dựng địa hình, nhà, texture và bộ ghi được đối chiếu với chương trình gốc
trong các ca đã kiểm tra; kết quả và giới hạn nằm trong
[VALIDATION.md](docs/VALIDATION.md). Một vùng Quỳnh Lưu dùng lại dữ liệu cache
cho cùng 7.316 đỉnh, 10.500 tam giác, vật liệu và texture như cảnh gốc.
87 bài kiểm tra máy chủ đạt, một bài bỏ qua đúng điều kiện. GLB mẫu sau sửa
tương thích đạt glTF Validator với 0 lỗi và 0 cảnh báo; đây không phải kiểm tra
mọi mô hình hoặc thay thế việc mở bằng SketchUp.

Chưa xác minh việc ghi SKP bằng SDK thật trên Windows hoặc nạp hình học, vật
liệu, Undo và vị trí mảnh bằng SketchUp Desktop thật. Kiểm tra dấu vết lời gọi
SDK hoặc tệp OBJ/GLB không thay thế kiểm tra SKP native.
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
