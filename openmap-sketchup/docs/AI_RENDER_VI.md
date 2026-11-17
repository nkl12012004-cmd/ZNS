# SiteCraft Render AI — bản thử nghiệm 0.5.0

Render AI nằm trong SiteCraft, mở bằng nút **Render AI**, menu Extensions →
SiteCraft → Render AI, hoặc nút thứ hai trên toolbar. Phần này dùng phiên
Google Flow trong Chrome của chính bạn. Extension Chrome chuyển ảnh/câu lệnh
và nhận kết quả; nó không chứa model AI chạy ngoại tuyến.

SiteCraft không thêm tài khoản, xu hay phí theo lượt. **Google Flow vẫn yêu cầu
đăng nhập Google, quyền sử dụng và hạn mức/phí của dịch vụ đó.** Việc tích hợp
không làm model Google mạnh hơn hoặc mở khóa gói dịch vụ. Chưa kiểm chứng chất
lượng/tốc độ trên phiên Flow thật trong môi trường xây dựng này.

## Cài và ghép nối

1. Cài RBZ Full 0.5.0 beta, thoát toàn bộ SketchUp rồi mở lại.
2. Mở Render AI → phần kết nối → **Mở thư mục extension**. Nếu dùng ZIP
   `SiteCraft_Flow_Bridge_0.5.0-beta.1.zip`, giải nén trước.
3. Trong Chrome mở `chrome://extensions`, bật Developer mode, chọn **Load
   unpacked**, trỏ vào thư mục có `manifest.json` của SiteCraft Flow Bridge.
   Không chọn cả ZIP hoặc thư mục cha.
4. Mở Google Flow trong Chrome, tự đăng nhập, mở dự án và chế độ tạo **ảnh**.
5. Trong SiteCraft tạo mã ghép nối. Bấm biểu tượng extension Chrome, chọn đúng
   cổng/mã rồi kết nối tab Flow bạn muốn dùng. Mã có thời hạn; nếu hết hạn hãy
   tạo mã mới. Bộ xử lý chọn cổng trống trong khoảng 17865–17872. Bản đầu chỉ
   cho một bộ xử lý dùng cùng một kho lịch sử AI; nếu có thông báo kho đang
   được sử dụng, đóng phiên SketchUp trước đó rồi kết nối lại.
6. Giữ tab Flow này mở. Nếu Chrome hỏi quyền truy cập mạng cục bộ, cho phép
   extension kết nối bộ xử lý SiteCraft trên `127.0.0.1`.

Tab đã ghép có thể chạy nền. Nếu cần thao tác click chuẩn như bộ tham khảo,
bật chế độ thao tác tin cậy trong popup và cấp quyền debugger khi Chrome hỏi;
bridge chỉ dùng nó với tab/tác vụ Flow đã ghép. Tự mở lại tab đã đóng là tùy
chọn riêng, mặc định tắt; không tự tạo lại lượt đã gửi nhưng chưa rõ kết quả.

Mã ghép nối chỉ ghép extension với bộ xử lý trên máy. Mật khẩu Google/cookie
không được đọc hoặc chuyển vào SiteCraft. Không chia sẻ mã khi chưa ghép nối.

## Dùng render và chỉnh ảnh

- **Chụp khung** lấy camera hiện tại của SketchUp; có thể bật bám camera, chọn
  kích thước/cạnh dài, tạm ẩn helpers hoặc mở/kéo thả/dán ảnh nguồn. Khi dùng
  nguồn SketchUp, Render chụp lại camera; nguồn ảnh từ máy/kết quả được giữ cố
  định. Nếu camera đổi khi có nét đánh dấu, plugin yêu cầu xác nhận trước khi
  thay nguồn. Các tùy chọn hiển thị khi chụp được khôi phục sau đó.
- Chọn khung cắt/tỷ lệ, thêm tối đa bốn ảnh tham chiếu, mô tả vật liệu/ánh sáng
  và chọn bám thiết kế/giữ camera. Các lựa chọn này là chỉ dẫn cho AI; kết quả
  vẫn có thể khác thiết kế. Có tỷ lệ tùy chỉnh, kéo/zoom khung, khung viewport
  trên SketchUp 2023+, vai trò/ghi chú ảnh tham chiếu và nhóm bối cảnh/phong
  cách/chi tiết bổ sung.
- Khoanh vùng, viết yêu cầu rồi render/chỉnh tiếp. Bản đầu gửi ảnh có đánh dấu
  và ghi chú; không giả định Flow cung cấp một API mask/inpainting chính xác.
- Theo dõi hàng đợi, so sánh trước/sau, dùng lại ảnh kết quả làm nguồn hoặc ảnh
  tham chiếu, lưu/mở ảnh bằng ứng dụng ngoài. Ảnh “trước” dùng bản sạch cùng
  khung cắt; có thể chọn ảnh đối chiếu khác. Lịch sử ảnh dùng thumbnail trên
  máy. Bắt đầu lượt mới hỏi thay lượt đang chạy; hàng đợi là tùy chọn riêng.
- **Flow 2K** thao tác mục tải 2K của ảnh trên Flow. Đây không phải cam kết
  upscale 2×/4×, không phải model super-resolution cục bộ, và không cam kết
  đầu ra 4K/8K. Nếu giao diện không hỗ trợ ảnh đó, plugin dừng và hướng dẫn
  thao tác thủ công thay vì tự tạo một ảnh khác.

Khi Flow yêu cầu đăng nhập, xác minh hoặc báo hết hạn mức, mở tab Flow và xử
lý trực tiếp. Nếu giao diện web thay đổi hoặc không nhận được đúng ảnh mới,
plugin chuyển sang cần thao tác; có thể tải ảnh trên Flow rồi nhập kết quả
thủ công vào đúng tác vụ. Không tự gửi lại một lần tạo ảnh có thể đã chạy.

## Câu lệnh trích từ bản mẫu

Catalog [nano_render_prompts.json](../reference/nano_render_prompts.json) giữ
94 mục text/template đọc được, kèm hash và vị trí nguồn. Giao diện dùng tối
đa 80 mục tùy thao tác: preset/vai trò, giữ thiết kế/camera, lệnh vùng sửa và
các đoạn ghép yêu cầu. Nội dung xem trước trùng câu lệnh đầy đủ gửi đi.

Hai câu nền đọc được là dữ liệu xem thử của giao diện mẫu, được đánh dấu
**Câu mẫu tham khảo** và cho phép sửa/chọn. Prompt nền của bản chạy thật nằm
trong Ruby mã hóa và chưa phục hồi. Không coi dữ liệu xem thử là bằng chứng
đã lấy được mặc định của bản chạy thật.

## Không dùng extension và công cụ ảnh

**Thao tác thủ công trên Flow** vẫn dùng được khi chưa ghép Chrome: lưu nguồn,
chép câu lệnh, mở Flow, tạo/tải ảnh rồi nhập kết quả. Có thể bật theo dõi một
thư mục tải về do bạn chọn; plugin chỉ đề xuất ảnh mới đã ghi xong và chờ bạn
xác nhận đúng tác vụ. Tệp tải dở/cũ/khác định dạng không được tự nhận.

Mở công cụ ảnh từ renderer để xử lý từng ảnh hoặc cả loạt:

- Nhận diện dấu Gemini dùng bốn mẫu/thuật toán MIT có nguồn gốc rõ ràng;
  không đủ bằng chứng sẽ giữ nguyên ảnh và báo không khớp.
- Dọn vùng chọn là phép nội suy cục bộ riêng, có thể làm nhòe nền phức tạp;
  không khôi phục được chi tiết bị che.
- So sánh rồi lưu thành tệp mới; không ghi đè ảnh/tệp gốc. Đây là xử lý ảnh
  trên máy, không gọi Google hoặc trừ hạn mức Flow.

## Ảnh bản đồ trước khi xuất

Tùy chọn **Xử lý ảnh nền qua Flow trước khi xuất** trong phần chi tiết bản đồ
mặc định tắt. Bản thử nghiệm chỉ dùng được luồng Flow 2K đã quan sát:

- Ảnh từ 2K trở lên được giữ nguyên; không gửi ảnh 4K/8K để lấy lại ảnh 2K.
- Đường, nhà và cây được nhận diện/dựng từ dữ liệu và ảnh gốc trước bước AI.
- Chỉ thay texture khi ảnh trả về lớn hơn, giữ tỷ lệ và vượt kiểm tra độ khớp
  ảnh. Không thay đỉnh, cao độ, khung cắt hay UV. Đây là kiểm tra bảo thủ bằng
  hình ảnh, **không phải chứng nhận độ chính xác địa lý** của ảnh sinh bởi AI.
- Nếu mất kết nối, ảnh sai khung hoặc không đạt kiểm tra, giữ texture gốc và
  hiện lý do. Nguồn gốc AI được ghi trong manifest, metadata origin của
  fallback/SKP và extras của GLB; các bộ ghi dùng cùng texture cuối.

Để bản đồ 4K/8K nét hơn thực sự, cần nguồn ảnh chất lượng cao hoặc backend
super-resolution riêng hỗ trợ độ phân giải tương ứng. Tích hợp Flow 2K không
thay thế được điều đó. Nên dùng Render AI để tạo ảnh phối cảnh trình bày, giữ
ảnh địa lý gốc cho công việc đo đạc/định vị.

## Kiến trúc và kiểm tra

Mã mới có thể sửa trong `extension/openmap_sketchup/ai_render.rb`,
`extension/openmap_sketchup/ui/ai.*`, `server/openmap_server/ai_render.py`,
`server/openmap_server/ai_texture.py` và `browser_extension/sitecraft_flow_bridge/`.
Không đưa chương trình Nano Render, tệp `.rbe`, khóa, tài khoản hoặc bộ cài
tham khảo vào gói chạy. Prompt text giữ nguồn/quyền gốc; thuật toán/mẫu dấu
MIT có LICENSE/provenance đi kèm. Giao thức: [AI_RENDER_PROTOCOL.md](AI_RENDER_PROTOCOL.md).

Ghép nối riêng từng extension, giới hạn ảnh/dung lượng, hàng đợi có lease và
khóa chống gửi trùng. Khởi động lại giữa một lần tạo ảnh chuyển sang cần kiểm
tra thủ công. Hủy không hoàn tác được xử lý đã gửi lên Google, và không đảm
bảo Google hoàn hạn mức. Lịch sử/ảnh nằm trong thư mục `ai` của cấu hình
SiteCraft trên máy; lưu ảnh qua hộp thoại sẽ tạo bản riêng ở nơi bạn chọn.

Kiểm thử tự động dùng ảnh và trang Flow giả lập. Chúng kiểm tra giao thức,
chọn đúng ảnh, khôi phục trạng thái, UI và texture; không gọi Google để tạo
ảnh và không chứng minh selector còn khớp mọi phiên bản Flow đang triển khai.
