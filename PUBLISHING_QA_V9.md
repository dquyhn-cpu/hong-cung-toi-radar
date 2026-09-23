# HÓNG CÙNG TÔI — PUBLISHING QA GATES V9

Mục tiêu: không cho phép một bài đã qua duyệt bị thay ảnh, giảm chất lượng hoặc phát tán sang Group trước khi Page được xác minh trực quan.

## Lifecycle bắt buộc

1. DRAFT
   - Nội dung/ảnh còn có thể sửa.
   - Tuyệt đối không publish.

2. APPROVED
   - Chủ dự án đã duyệt đúng caption, đúng ảnh master cuối.
   - Ảnh master phải được khóa bằng đúng file đã duyệt.
   - Chỉ được phép chuẩn hóa kỹ thuật không làm thay đổi thiết kế: decode, đổi RGB, encode JPEG/PNG, resize xuống nếu cần.
   - Cấm tự sinh ảnh mới, cấm thay layout, cấm upscale thumbnail.

3. PAGE_VERIFIED
   - Bài đã đăng Page.
   - Kiểm tra trực quan trên Facebook xác nhận: ảnh đầy đủ, không mảng xám, không mờ/bệt bất thường, text đúng, crop đúng, caption/comment đúng.
   - Nếu fail: xóa bài lỗi và quay lại DRAFT/APPROVED tùy nguyên nhân.

4. GROUP_READY
   - Chỉ được chuyển trạng thái này sau PAGE_VERIFIED.
   - Package group phải dùng chính caption + final asset đã PAGE_VERIFIED.
   - Không tái biên tập hoặc thay ảnh giữa Page và Group.

## Hard gates ảnh

- Không dùng thumbnail/preview làm master.
- Master phải có kích thước nguồn đủ lớn; không upscale để đạt chuẩn đăng.
- File phải decode toàn bộ thành công.
- Ảnh cuối phải RGB hoặc chuẩn tương thích Facebook.
- Phải kiểm tra kích thước, dung lượng, tỷ lệ và hash trước publish.
- Khi asset đã APPROVED, pipeline chỉ được chuẩn hóa file đó; nếu file mất/hỏng thì STOP.
- Không fallback sang ảnh khác.
- Không tự thiết kế ảnh thay thế.

## Quy tắc Group

Publisher Group sau này phải từ chối mọi item nếu lifecycle_status != GROUP_READY.
PAGE_VERIFIED là điều kiện bắt buộc trước GROUP_READY.

## Quy tắc lỗi

- Bất kỳ QA fail nào trước publish: STOP, không đăng.
- Page render lỗi: xóa Page post, không phát tán Group.
- Không coi API trả 200/OK là đủ để xác nhận chất lượng ảnh.
- Chất lượng hiển thị thực tế trên Facebook là cổng cuối.
