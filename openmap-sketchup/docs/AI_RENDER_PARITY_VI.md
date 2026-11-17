# Đối chiếu SiteCraft Render AI với bộ tham khảo

Chuẩn tham khảo là bộ cài Nano Banana Render 2.6.14/Chrome Bridge 2.6.4 và các
video được cung cấp. Video cài đặt dùng bản cũ hơn 2.6.2/2.6.1. Chức năng và
luồng thao tác được đối chiếu riêng với chất lượng của model Google; việc viết
lại extension không huấn luyện lại hoặc nâng cấp model của Google.

## Các luồng cần giữ

1. Mở renderer → thấy khung nhìn SketchUp → cắt khung/tỷ lệ → thêm mô tả và
   ảnh tham chiếu → Render lấy lại khung hiện tại khi dùng nguồn SketchUp.
2. Đánh dấu vùng/mô tả riêng → gửi ảnh có đánh dấu; so sánh với bản sạch,
   giữ ghi chú khi dùng lại thiết lập và yêu cầu không vẽ nét đánh dấu vào ảnh.
3. Flow chạy trong tab đã ghép → nhận đúng ảnh mới → chỉnh tiếp/dùng tham
   chiếu/tải 2K/lưu → lịch sử ảnh trên máy.
4. Nếu bridge không dùng được: lưu ảnh nguồn, chép toàn bộ câu lệnh, mở Flow,
   tạo ảnh bằng tay rồi nhập kết quả; theo dõi ảnh tải về khi người dùng bật.

SiteCraft giữ thương hiệu/font riêng và một màn làm việc; bảng lịch sử/cấu
hình có thể dùng ngăn kéo. Vị trí bảng không được coi là thay thế cho một
chức năng thiếu. Mã, khóa, dịch vụ tài khoản và tài sản riêng của bộ tham
khảo không được đưa vào bản viết lại.

## Giới hạn cần phân biệt rõ

- Kiểm thử DOM/giao thức dùng dữ liệu giả lập; cầu nối Chrome→Python được thử
  bằng Chrome thật trên máy. Chưa chạy một lượt tạo ảnh qua tài khoản Google.
- Flow 2K là mục tải ảnh 2K; không phải model SR cục bộ hoặc cam kết 2×/4×.
  Quyền truy cập, hạn mức và thay đổi giao diện Google vẫn có hiệu lực.
- Chỉ nhận tự động khi có đủ bằng chứng về ảnh nguồn/câu lệnh/ảnh mới. Trường
  hợp không xác định được sẽ yêu cầu thao tác, tránh nhận nhầm ảnh khác.
- Theo dõi thư mục tải về cần người dùng chọn thư mục và xác nhận ứng viên;
  chỉ riêng thời điểm xuất hiện tệp không chứng minh tệp thuộc tác vụ Flow.
- Nhận diện dấu Gemini dùng nguồn MIT công khai cùng dòng thuật toán được
  bộ tham khảo ghi công, kèm bốn mẫu và notices. Nó chỉ hỗ trợ mẫu/vị trí đã
  biết; không đủ bằng chứng sẽ giữ nguyên ảnh. Dọn vùng tùy chọn là phép
  điền cục bộ riêng, có thể làm mờ nền phức tạp và không khôi phục chi tiết
  gốc bị che. Không coi hai phương pháp là nhận diện mọi logo.
- Không đưa tài khoản/dùng thử/thu xu của Nano Render vào SiteCraft. Đây là
  khác biệt theo yêu cầu người dùng; Google Flow vẫn dùng tài khoản Google.

Ghi rõ các điểm này khi bàn giao bản beta. Chỉ gọi luồng Flow là đã xác minh
đầu cuối sau một lượt thực tế trên phiên Google được người dùng sử dụng.
