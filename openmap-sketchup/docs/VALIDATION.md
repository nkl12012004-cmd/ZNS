# SiteCraft 0.4.0 — phạm vi kiểm tra

Tài liệu này ghi các kiểm tra đã thực hiện cho mã khôi phục và chỉ rõ phần chưa
xác nhận. Người dùng đã đồng ý công bố SiteCraft 0.4.0 cùng năm mô-đun nguồn
khôi phục ngày 17/11/2026, theo giờ Việt Nam. Kết quả của OpenMap 0.3.0 hoặc
của runner cũ không được coi là kiểm tra đầy đủ cho SiteCraft 0.4.0.

## Đối chiếu với chương trình gốc

Oracle là các code object lấy cục bộ từ gói MapSKP do người dùng cung cấp,
không thay đổi logic chương trình gốc. Mã `.py` khôi phục được chạy riêng rồi
so kết quả. Các ca dữ liệu mạng dùng fixture hoặc cache; không gửi mã gốc lên
dịch vụ giải mã bên ngoài.

| Phần | Kết quả đã ghi nhận |
| --- | --- |
| Tọa độ/tile: 11 hàm | 60.458 phép đối chiếu, so bit float và byte/dtype/shape mảng |
| Texture: 22 hàm | 2.224 phép đối chiếu; đủ 13 JPEG mặc định trùng từng byte |
| Dữ liệu/mạng: 23 hàm trong builder | 37.935 phép đối chiếu; satellite JPEG, DEM float32, URL/cache/dự phòng, MVT/gzip/zlib, Overpass, morphology và vector từ Google roadmap |
| Hình học/địa hình/nhà | 12.032 phép đối chiếu trong bộ geometry; bao gồm đáy/thành địa hình, đường, nhà có tầng giật cấp và gờ/mái |
| Bộ dựng đầy đủ: 51 hàm | 61/61 ca khớp kiểu/dtype/shape, mảng, texture, vật liệu, lớp, origin và sự kiện tiến trình |
| Cảnh Quỳnh Lưu dùng cache | Cảnh gốc và mã nguồn mới cùng 7.316 đỉnh, 10.500 tam giác, 13 vật liệu, 4 lớp và cùng fingerprint hình học |
| Bộ ghi: 14 hàm | 27 tệp đầu ra thô của ba cảnh đối chiếu trùng byte: OBJ, MTL, texture, GLB, gói cảnh và JSON/ảnh fallback; chưa qua bước sửa tương thích GLB |
| Lời gọi SketchUp SDK | Đối chiếu qua DLL fixture tới ranh giới lưu, bao gồm chia chunk 16.001 tam giác và cảnh Quỳnh Lưu; không dùng SDK thật |
| Tọa độ/OCR: 6 hàm | 8 nhóm oracle đạt; parser, bounds, PowerShell template, luồng ảnh/subprocess fixture; chưa chạy OCR Windows thật |

Các bộ kiểm tra con có thể dùng chung hàm hoặc cùng cảnh; không cộng các số trên
thành một tổng ca độc lập. Kết quả không có nghĩa mọi đầu vào hoặc mọi kết hợp
tham số đều đã được thử.

Fingerprint cảnh Quỳnh Lưu:

```text
b013b958853c85ec824510e554703a624256b5905b62a6b71ae52a0386d7a980
```

Ca Quỳnh Lưu dùng 53 tệp cache không đổi, chặn mạng thực, so cảnh và tiến trình
với chương trình gốc. Đây không phải lần tải dữ liệu mới từ các nhà cung cấp.
Texture/data đã có được giữ đúng byte qua quy trình thử.

So oracle chạy cả hai chương trình trong cùng môi trường Linux CPython 3.14.10;
một số bộ dùng NumPy 2.5.5/Pillow 13.0.0. Runtime Windows được ghim NumPy 2.5.3/
Pillow 12.2.0 theo dependency gốc. Kết quả cùng môi trường không thay thế việc
chạy toàn bộ gói Windows với dependency được ghim.

## GLB giao cho người dùng và bản gốc của bộ ghi

Bộ ghi gốc có thể gán vật liệu texture cho nhóm mặt (primitive) không có UV. Adapter
`server/openmap_server/glb_compat.py` chạy sau bộ ghi, tạo bản sao vật liệu màu
từ RGBA gốc và chỉ chuyển liên kết vật liệu của những mặt bị ảnh hưởng.
Các mặt có UV giữ vật liệu ban đầu; hình học, chỉ số, UV, byte BIN/ảnh và các
chunk khác không bị đổi. Tệp đã tương thích trả nguyên byte mà không ghi lại JSON.

Khi có sửa, GLB thô được giữ thành `<tên>_original.glb`; GLB giao qua API là bản
đã sửa. `original_manifest.glb_compatibility` ghi hash trước/sau, hash BIN,
số primitive/vật liệu và danh sách chỉnh sửa. Đây là thay đổi có chủ đích ngoài bộ
ghi gốc: không tuyên bố toàn bộ GLB đã sửa trùng byte chương trình gốc.

Tám ca kiểm tra mới đạt, bao gồm tệp hợp lệ không đổi, dùng chung/tách bản sao vật
liệu, giữ RGBA và mọi chunk BIN/ảnh, nhiều liên kết texture, từ chối UV set
khác bị thiếu, extension chưa hỗ trợ và dữ liệu GLB/hình màu sai.

glTF Validator kiểm tra `original_preview_compat.glb`: **0 lỗi, 0 cảnh báo** và
4 thông tin về vật liệu gốc không còn được dùng nhưng vẫn giữ lại. Cùng fixture
thô trước sửa có 2 lỗi thiếu UV; bản sửa chuyển 2 primitive sang 1 bản sao vật
liệu. Đây là kết quả cho fixture đã nêu, không phải chứng nhận mọi GLB đầu ra.

## Kiểm tra trình đóng gói

Verifier đã được thử riêng bằng thư mục tạm có manifest nguồn hợp lệ, không chạy
build. Nó chấp nhận năm `.py` đúng kích thước/SHA-256 và từ chối tám tình huống:
marshal, pyc, đường dẫn armor, đường dẫn vault, DLL, native binary đổi đuôi,
sửa byte nguồn và đường dẫn manifest vượt khỏi thư mục được phép.

Quy tắc đóng gói loại `.env` và các biến thể chứa cấu hình thật, bytecode/cache,
log, `test-artifacts`, `test-results`, `node_modules` và các gói cũ. Mẫu `.env.example`,
mã kiểm tra và thông báo/font SVN-Avo được giữ. `original_kernel` phải chỉ có
năm nguồn `.py` được kê cùng các thông báo/manifest; build từ chối cache hoặc
payload nhị phân trong đó.

Việc tạo RBZ/ZIP cuối, kiểm tra CRC và ghi `SHA256SUMS.txt` cần được thực hiện
sau khi chốt nguồn/manifest/runtime. Build ghi tệp và checksum; Release
`sitecraft-v0.4.0` chỉ được công bố sau kiểm tra Windows của đúng gói.

## Kiểm tra tích hợp SiteCraft 0.4.0 trên Linux

- Bộ cuối 88 bài máy chủ: **87 đạt, một bỏ qua đúng điều kiện**, chạy trong
  18,098 giây trên CPython 3.14 Linux. Gồm tám ca GLB mới và sáu ca HTTP thực
  với bộ nguồn vừa khôi phục; bài bỏ qua dành cho interpreter không hỗ trợ.
- Mạng và xác thực ngoài bị chặn trong các ca HTTP: vẫn dựng/xuất bằng dữ liệu
  fixture nội bộ, đối chiếu mảng, UV, ảnh, tag và byte đầu ra của bộ ghi gốc.
- Đã thử hủy/tác vụ chưa xong, từ chối SKP native khi chưa có DLL, báo nguồn giảm
  khả dụng riêng với thiếu lớp, kiểm tra giới hạn đồng bộ, giữ hệ số mốc 2.5.
- Chromium UI đạt các luồng một thanh bên, tìm kiếm, sáng/tối, xuất, nạp, lỗi/hủy,
  tránh phản hồi cũ và khôi phục runtime. Phản hồi Ruby/API trong UI dùng fixture.
- Bốn SVN-Avo TTF tải thành công, computed font đúng ở nút/form/hộp cấu hình/widget;
  đầy đủ 104 ký tự tiếng Việt, không lỗi trình duyệt/font trong ca thử.
  Font được người dùng cho phép đóng kèm; quyền gốc và thông báo được giữ.
- Ruby Prism kiểm tra cú pháp 7 tệp đạt; preflight với 21 vật liệu và mesh gốc đạt.
  311 ca ghép mảnh so với hàm Ruby gốc đạt, gồm offset/scale/rotation/hill patch.
- Dependency runtime công khai đã kiểm tra trên Windows thật, run 44017165169:
  CPython/NumPy BLAS/Pillow JPEG/Unicode/HTTPS đạt, hash runtime trùng cục bộ.
  Ca này không chứa mã phục hồi và không xác nhận chạy bộ dựng trong Windows.

## Trạng thái kiểm tra Windows của gói đầy đủ

Lượt CI cho đúng gói SiteCraft 0.4.0, bao gồm năm mô-đun nguồn khôi phục, đang
được chuẩn bị/chạy; chưa có kết quả cuối trong tài liệu này. Không dùng run
dependency công khai 44017165169 để thay thế lượt kiểm tra đầy đủ này. Khi CI
đạt, gói được phát hành tại [sitecraft-v0.4.0](https://github.com/nkl12012004-cmd/ZNS/releases/tag/sitecraft-v0.4.0).

## Các kiểm tra còn cần trên môi trường đích

- Chạy bộ runtime Windows cho đúng RBZ SiteCraft 0.4.0; mã phục hồi hiện mới
  chạy tích hợp trên Linux. Kết quả dependency Windows không thay thế kiểm tra đó.
- Dùng Windows thật với `SketchUpAPI.dll` tương thích để ghi SKP, rồi mở tệp bằng
  SketchUp Desktop. Chưa tạo hoặc xác minh SKP native thật trong các ca trên.
- Nạp mesh/texture trong SketchUp, kiểm tra Undo, Group/Tag, bóng nắng, vị trí mảnh,
  lưu SKP và nâng cấp từ cài đặt cũ. Ruby fixture không mô phỏng geometry API.
- Chạy Windows OCR với ảnh thật, ngôn ngữ OCR đã cài và fallback Tesseract của
  runtime. Fixture subprocess không chứng minh Windows OCR có sẵn trên máy.
- Kiểm tra trực tiếp các nhà cung cấp ảnh/tìm kiếm/OSM/DEM. Fixture và cache không
  bảo đảm dịch vụ đang truy cập được, dữ liệu đủ hoặc hình mới nhất.
- Kiểm tra ca 8K/vùng lớn và thời gian/RAM thực trên máy đích.

Nhánh kiểm tra chính sách native tùy chọn được giữ nguyên. Ca thiếu grant hoặc
lỗi policy có đối chiếu lỗi; nhánh thành công dùng grant có chữ ký thật chưa
được thử vì không có grant hợp lệ. Không tạo grant hoặc bỏ qua kiểm tra.

Google Photorealistic 3D, backend tài khoản/thanh toán và chữ ký cập nhật của
MapSKP không thuộc phạm vi đã khôi phục. Mã gốc và font giữ quyền riêng, chưa
xác minh giấy phép nguồn mở. Việc người dùng đồng ý công bố nguồn khôi phục
không thay đổi quyền gốc hoặc đưa các tệp đó vào giấy phép MIT của mã tích hợp.
