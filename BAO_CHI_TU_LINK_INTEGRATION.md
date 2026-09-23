# Tích hợp @bao-chi-tu-link vào Radar V8.2

## Vai trò

V8.2 không thay thế `@bao-chi-tu-link`. Radar chỉ làm ba việc trước biên tập:

1. phát hiện/xác minh sự kiện;
2. xếp hạng độ đáng đăng;
3. Monetization Preflight + risk routing.

Sau đó gói biên tập phải tuân theo contract của `@bao-chi-tu-link`.

## Mapping skill -> code

- Đọc/đối chiếu bài gốc -> `source_reader.py`
- Độ đáng đăng -> `editorial_v82.py`
- Monetization Preflight -> `monetization_preflight.py`
- Hai caption + hai bản tóm tắt + bình luận nguồn -> `build_draft_packets.py`
- Kiểm tra Community Standards / monetization / originality / copyright / engagement bait -> `draft_validator.py`
- Approval gate -> `prepare_facebook_queue.py`
- Đăng Page + comment -> `facebook_publisher.py`

## Quy tắc quyết định

- `POST`: có thể đi tiếp tới biên tập, vẫn cần review và approval.
- `POST_WITH_CAUTION`: được biên tập nhưng phải giữ cảnh báo rủi ro nội bộ và review kỹ.
- `SKIP`: không tạo draft/publisher queue.

Điểm editorial là điểm ưu tiên nội dung, **không phải điểm đúng/sai và không phải điểm bảo đảm kiếm tiền**.

## Originality và copyright

- Tóm tắt bài báo/đăng lại ảnh bên thứ ba không tự động trở thành nội dung nguyên bản.
- Credit không đồng nghĩa có quyền tái sử dụng ảnh/video.
- Nếu quyền ảnh/video không rõ, publisher text có thể tiếp tục nhưng media phải được review riêng.
- Không xóa watermark hoặc làm thay đổi ngữ cảnh ảnh nguồn.

## Quy tắc bài chính và comment

- Bài chính phải chứa dữ kiện cốt lõi.
- Comment chỉ bổ sung bối cảnh, số liệu, diễn biến phụ và link nguồn.
- Không engagement bait, watch bait hoặc cố ý giấu thông tin trọng yếu xuống comment.
- Bình luận nguồn phải có URL bài gốc đã đọc.

## Nội dung nhạy cảm

Tin về tử vong, thương tích, thảm họa, tội phạm, tình dục, chất cấm, tự hại hoặc tranh cãi có thể được phép đăng nhưng có rủi ro phân phối/kiếm tiền cao hơn. V8.2 không tự hứa nội dung sẽ đủ điều kiện kiếm tiền.

Tin liên quan chính trị/công quyền chỉ dùng ngôn ngữ trung tính, mô tả dữ kiện, hành động, phát biểu hoặc chính sách được nguồn xác nhận; không kêu gọi ủng hộ/phản đối và không xếp hạng chính trị.

## Giới hạn kỹ thuật

GitHub Actions không trực tiếp “gọi skill ChatGPT”. Repo hiện mã hóa **contract và prompt** của skill để tạo `radar_draft_packets_v82.json`. Bước sinh văn bản bằng model có thể được nối tự động ở giai đoạn sau; cho tới lúc đó, output draft vẫn phải qua review/approval trước publisher.
