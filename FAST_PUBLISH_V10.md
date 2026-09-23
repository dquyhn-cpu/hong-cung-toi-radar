# HÓNG CÙNG TÔI — FAST PUBLISH V10

Mục tiêu: khi chủ dự án nói "đăng", thao tác publish phải ngắn, ổn định và không làm thay đổi asset đã duyệt.

## Kiến trúc mới

### 1. PREPARE — làm trước lệnh "đăng"
- Biên tập caption.
- Tạo ảnh master cuối.
- Chủ dự án duyệt.
- Lưu đúng file master.
- Kiểm tra decode, kích thước, hash.
- Queue chuyển sang APPROVED.

### 2. PUBLISH — khi chủ dự án nói "đăng"
Publisher chỉ được:
1. đọc package APPROVED;
2. xác minh hash/file;
3. upload nguyên bytes của ảnh;
4. đăng caption;
5. đăng comments;
6. trả post_id.

Không generate ảnh.
Không resize.
Không re-encode.
Không thay layout.
Không fallback sang ảnh khác.
Không cache/state artifact.
Không cài dependency không liên quan.

### 3. VERIFY — sau publish
- Kiểm tra hiển thị Page.
- Nếu đúng: PAGE_VERIFIED.
- Nếu sai: giữ lại bằng chứng lỗi và quay về PREPARE.
- Chỉ PAGE_VERIFIED mới được chuyển GROUP_READY.

## Quy tắc hiệu năng
- Lệnh "đăng" không được khởi tạo công việc biên tập hoặc tạo ảnh.
- Phần nặng phải hoàn tất trước APPROVED.
- Workflow publish chỉ dùng requests + Pillow.
- Dedupe bằng message trong các post gần nhất.
- Ảnh được upload exact bytes; Pillow chỉ dùng verify, không ghi lại file.

## Kỳ vọng
- Thời gian chờ chủ yếu còn lại là thời gian khởi động GitHub runner + Facebook API.
- Không còn các bước generate/convert/resize vốn gây chậm và làm giảm chất lượng.
