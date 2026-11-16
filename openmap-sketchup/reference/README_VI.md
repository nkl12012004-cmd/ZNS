# Nguồn MapSKP gốc đọc được

Thư mục `mapskp_original_readable/` giữ nguyên phần Ruby, HTML/JS/CSS, shim Python, cấu hình và icon trích từ ZIP người dùng cung cấp. Hash của từng tệp nằm trong `ORIGINAL_SOURCE_HASHES.json`.

Các tệp này dùng để đối chiếu và tiếp tục chuyển tính năng; không được nạp bởi extension OpenMap hoặc server mới. Mã runtime mới nằm trong `extension/` và `server/`.

Thông tin tác giả HiepAI/bản quyền 2026 được giữ nguyên. Không tìm thấy giấy phép nguồn mở cho phần gốc trong ZIP. LICENSE MIT của mã mới không áp dụng cho các tệp gốc này. Không tự đổi giấy phép mã gốc.

Lõi `core_ip.vlt`, mã C/C++ gốc của `mapskp_armor` và mã SaaS không có nguồn đọc được; chúng không được dùng làm runtime mới.
