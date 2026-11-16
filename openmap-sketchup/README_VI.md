# OpenMap SketchUp 0.1.0

Bản viết lại nguồn mở độc lập theo yêu cầu: **đăng nhập Email/Google qua Supabase,
không ví xu, không tín dụng, không mua gói, không tính lượt dựng/nạp/xuất.**
Toàn bộ mã runtime của bản mới có trong `extension/` và `server/`, phát hành MIT.
Nguồn gốc đọc được đi kèm trong `reference/` để đối chiếu, giữ riêng thông tin
bản quyền ban đầu; giấy phép MIT của mã mới không áp dụng cho phần tham chiếu đó.

Đây là một triển khai mới, không phải bản giải mã đầy đủ MapSKP v2.8.1.
Các tệp lõi mã hóa, thư viện native và dịch vụ tài khoản thương mại của bản gốc
không được dùng. Vì vậy, tài khoản Email/Google thuộc **dự án Supabase do bạn
cấu hình**, không tự động dùng dữ liệu tài khoản/dịch vụ của nhà cung cấp cũ.

## Tính năng đã triển khai

- Đăng nhập, đăng ký Email, đăng nhập Google PKCE, làm mới phiên và đăng xuất.
- Giữ phiên trong bộ nhớ của phiên SketchUp; không ghi mật khẩu/token xuống đĩa.
- Giao diện bản đồ toàn màn hình, thẻ điều khiển nổi, sáng/tối, preset kích thước,
  địa điểm mẫu, tùy chỉnh thu gọn; giữ luồng thao tác của giao diện cũ.
- Chọn tâm bằng kéo/zoom, kéo góc khung để đổi kích thước, tìm địa chỉ,
  dán tọa độ thập phân/DMS hoặc link Google Maps có tọa độ.
- Tải và ghép ảnh vệ tinh Esri/Google, bản đồ Google đường phố, texture
  1024/2048/4096/8192; có lớp OSM để xem bản đồ 2D.
- Nền phẳng Z=0 hoặc lưới địa hình DEM Terrarium, hệ số cao độ tùy chỉnh.
- Trám đồi lên nền phẳng: nội suy chuyển tiếp, rìa mảnh về Z=0.
- Bật/tắt riêng đường chính/ngõ; nhà cao/thấp tầng từ footprint và số tầng OSM.
- Box trắng hoặc map mặt đứng tạo thủ tục; mái phẳng, mái tông trầm/bê tông,
  gờ chắn mái. Số tầng mặc định và tên component tùy chỉnh.
- Mặt nước dạng polygon và cây tại các node OSM `natural=tree`.
- Mốc ENU/WGS84 chung trong mô hình; các mảnh mới dùng cùng đơn vị mét và mốc.
- Nạp vào các Group/Tag riêng, giữ thông tin nguồn và hỗ trợ Undo một thao tác.
- Tự nạp sau khi dựng; xuất OBJ + MTL + PNG/JPEG + metadata trong ZIP, GLB độc lập,
  lưu nhóm được chọn thành SKP; mở thư mục xuất và đồng bộ bóng nắng.
- Xem trước WebGL 3D: xoay, pan, zoom, căn giữa và khung dây.
- Metadata trong SKP xuất mới, tự ghép các mảnh kéo-thả mới thêm vào mô hình;
  đọc metadata công khai `MapSKP_Meta` / `__MAPSKP_META__` của SKP cũ khi có.
- OCR ảnh tọa độ và Ctrl+V ảnh, nếu máy chủ đã cài Tesseract.
- Tác vụ nền, tiến độ, hủy tác vụ; mỗi tài khoản chỉ lấy được tác vụ của mình.

Khối nhà là mô hình khối xấp xỉ từ OSM; map mặt đứng là ảnh tạo thủ tục,
không phải ảnh mặt đứng thật. Không có mesh Google Photorealistic 3D.
Footprint hỗ trợ các way khép kín đơn giản; chưa xử lý multipolygon có sân trong.
Đường là dải bề mặt đơn giản, chưa mô phỏng nút giao/cầu/hầm chi tiết.
Không dùng cơ chế cập nhật có chữ ký/gói thương mại của nhà cung cấp cũ.
Tương thích SKP cũ dựa trên metadata đọc được; file thiếu metadata không tự ghép.
Ghép các dự án có mốc xa nhau dùng phép dịch ENU gần đúng, không thay thế
quy trình đo đạc/trắc địa. Giữ nguyên mốc và hệ số cao độ để ghép các mảnh cùng dự án.
Nút chọn vùng kế bên là tiện ích
chọn vùng, không phải cam kết sai số hình học 0 mm ở mọi vĩ độ.

## Yêu cầu

- SketchUp Desktop có Ruby API/HtmlDialog, mục tiêu SketchUp 2021 trở lên.
- Python 3.10+ và Pillow; có thể chạy máy chủ trên cùng máy hoặc máy chủ riêng.
- Một dự án Supabase với URL và **public anon/publishable key**.
- Internet để xác thực và tải dữ liệu bản đồ/DEM/OSM.
- Tesseract OCR và dữ liệu ngôn ngữ `eng` nếu cần đọc tọa độ từ ảnh.
  Đặt đường dẫn chương trình vào `TESSERACT_BIN` trong `.env` nếu chưa có trong PATH.

## 1. Cấu hình Supabase

1. Tạo hoặc chọn dự án Supabase của bạn.
2. Trong Project Settings → API, lấy Project URL và public anon/publishable key.
   Không dùng `service_role` hoặc secret key.
3. Sao chép `server/.env.example` thành `server/.env`, điền:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_PUBLIC_KEY
PUBLIC_BASE_URL=http://127.0.0.1:8877
```

4. Trong Authentication → Providers, bật Email. Chọn chính sách xác nhận email
   theo nhu cầu; nếu bật xác nhận, người dùng phải xác nhận trước khi đăng nhập.
5. Để dùng Google, tạo OAuth Client kiểu Web application trong Google Cloud,
   bật Google provider ở Supabase và nhập Client ID/Client Secret **trong
   bảng điều khiển Supabase**, không đưa secret vào extension.
6. Google Authorized redirect URI là callback mà Supabase hiển thị, thường:
   `https://YOUR_PROJECT.supabase.co/auth/v1/callback`.
7. Trong Supabase Authentication → URL Configuration → Redirect URLs, thêm:
   `http://127.0.0.1:8877/auth/callback**`.

Google đăng nhập trong trình duyệt mặc định. Khi báo hoàn tất, quay lại SketchUp;
extension tự nhận phiên qua luồng PKCE. Authorization code chỉ dùng một lần;
trình duyệt không nhận access token qua URL của OpenMap.

## 2. Chạy máy chủ

Windows PowerShell, mở từ thư mục dự án:

```powershell
cd server
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Hoặc, sau khi điền `.env`, chạy `server/START_SERVER.cmd`.

macOS/Linux:

```sh
cd server
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Máy chủ mặc định: `http://127.0.0.1:8877`. Dừng bằng Ctrl+C.
Chỉ cần public key; backend xác minh access token thật bằng `/auth/v1/user` của
Supabase. Nếu chưa cấu hình, đăng nhập trả lỗi rõ ràng và các API bản đồ vẫn khóa.
Không có tài khoản demo, token đặc biệt hoặc luồng tự cho qua đăng nhập.

Nếu chạy từ máy khác, đặt `PUBLIC_BASE_URL` thành URL HTTPS thực tế, thêm URL
callback tương ứng trong Supabase và dùng HTTPS reverse proxy. Không dùng Python
HTTP server để phục vụ trực tiếp mật khẩu/token qua HTTP trên mạng công cộng.

## 3. Cài extension

Trong gói nguồn ZIP có `install/OpenMap_SketchUp_0.1.0.rbz`.

1. SketchUp → Extension Manager → Install Extension… → chọn file RBZ.
2. Mở Extensions → OpenMap SketchUp → Mở OpenMap hoặc bấm icon toolbar.
3. Bấm Cấu hình nếu máy chủ không ở địa chỉ mặc định.
4. Đăng nhập Email hoặc Google, chọn vùng và bấm Dựng bản đồ.
5. Khi xong, bấm Nạp vào SketchUp hoặc Xuất OBJ + ảnh.
6. Để lưu SKP, chọn Group OpenMap trong mô hình rồi bấm Lưu SKP đã chọn.

RBZ không ký chứng thực SketchUp. Khi môi trường cài đặt chỉ cho phép extension
đã ký, cần quản trị theo chính sách cài extension của máy đang dùng.

## Không có hệ thống xu/tín dụng

Mã mới không có bảng số dư, trừ xu, checkout, subscription hay đếm lượt xuất.
Giới hạn kích thước lưới, ảnh và hàng đợi nhằm giữ bộ nhớ/luồng xử lý ổn định,
không gắn với tài khoản hay thanh toán. Dữ liệu tác vụ nằm trong RAM; khởi động
lại server sẽ xóa chúng. Các kết quả cũ có thể được dọn khi quá một giờ hoặc khi
bộ nhớ kết quả đầy, vì vậy hãy nạp/lưu kết quả sau khi dựng xong.

Ảnh 8K dùng JPEG để giữ dung lượng hợp lý và cần nhiều RAM/thời gian tải hơn.
Các endpoint ảnh bản đồ có thể hạn chế khả dụng; có thể đổi nguồn trong giao diện.
Plugin không thu phí/lượt. Supabase, máy chủ và nguồn dữ liệu bên ngoài vẫn có
chính sách/dung lượng dịch vụ riêng; mã mới không thay đổi các chính sách đó.
Overpass có nguồn OSM API dự phòng; nếu cả hai không tải được dữ liệu, có thể
bỏ chọn Đường OSM/Khối nhà OSM để tiếp tục dựng nền và địa hình.

## Sửa mã, kiểm tra và đóng gói

```text
extension/openmap_sketchup.rb          đăng ký extension
extension/openmap_sketchup/main.rb     HTTP bất đồng bộ và cầu nối giao diện
extension/openmap_sketchup/importer.rb kiểm tra/nạp mesh, texture, Group/Tag
extension/openmap_sketchup/linking.rb  metadata và ghép SKP kéo-thả
extension/openmap_sketchup/ui/         HTML/CSS/JS/icon
server/openmap_server/auth.py          Supabase Email/Google PKCE
server/openmap_server/builder.py       tile, DEM, OSM, mesh và xuất OBJ
server/openmap_server/geo.py           WGS84/ENU, clip, triangulation
server/openmap_server/formats.py       GLB nhúng ảnh và mesh xem trước
server/openmap_server/ocr.py           gọi Tesseract tùy chọn
server/openmap_server/app.py           API và hàng đợi tác vụ
server/tests/                         kiểm tra API/xác thực/hình học
tools/build.py                        tạo RBZ và ZIP nguồn
```

Chạy kiểm tra Python:

```sh
cd server
python -m unittest discover -s tests -v
```

Kiểm tra UI với Node.js/Playwright, dùng cầu nối SketchUp và đăng nhập mô phỏng:

```sh
cd tools
npm install
npx playwright install chromium
npm run test:ui
npm run test:ruby
```

Đóng gói từ thư mục dự án: `python tools/build.py`.
Xem `docs/VALIDATION.md` để biết kết quả và giới hạn kiểm tra của bản bàn giao.
Xem `docs/FEATURE_PORT.md` để đối chiếu tính năng cũ và phần đã chuyển sang.
