# Facebook Page Publisher V8.1

Mục tiêu: đăng bài lên Page **Hóng Cùng Tôi** và đăng chuỗi bình luận bổ sung sau khi bài chính đã đăng thành công.

## Nguyên tắc an toàn

- Không hard-code token trong code/repo.
- Bài chính và comment là hai bước độc lập.
- Comment lỗi không xóa/rollback bài chính.
- Rerun không được đăng trùng nếu đã có state hoặc tìm thấy bài/comment có nội dung y hệt trong các mục gần nhất.
- Chỉ retry lỗi tạm thời/rate-limit; lỗi quyền như `#200` fail-fast.
- Queue mặc định trong repo là rỗng để workflow không thể vô tình đăng bài thật.

## GitHub Secrets cần tạo

- `FB_PAGE_ID` = Page ID của Hóng Cùng Tôi
- `FB_PAGE_ACCESS_TOKEN` = Page Access Token production

Token production cần được derive từ System User token đã test thành công với các quyền cần thiết cho flow hiện tại, gồm:
- `pages_manage_posts`
- `pages_manage_engagement`
- `pages_read_engagement`
- `pages_read_user_content`
- `pages_show_list`

## File đầu vào

Publisher đọc `facebook_publish_queue.json`:

```json
{
  "items": [
    {
      "publish_id": "event-unique-id",
      "event_id": "radar-event-id",
      "enabled": true,
      "message": "Nội dung bài chính đã duyệt",
      "comments": ["Bình luận 1", "Bình luận 2"]
    }
  ]
}
```

`publish_id` phải duy nhất và ổn định để chống đăng trùng.

## Test local / GitHub Actions

Dry run:

```bash
python facebook_publisher.py --queue facebook_publish_queue.json --dry-run
```

Chạy thật:

```bash
python facebook_publisher.py --queue facebook_publish_queue.json
```

Workflow `facebook-publish.yml` mặc định `dry_run=true`. Chỉ đổi sang false sau khi queue đã được duyệt.

## Kết quả trạng thái

`facebook_publish_state.json` lưu `post_id`, từng `comment_id`, trạng thái và lỗi. Nếu post thành công nhưng comment lỗi, rerun sẽ giữ nguyên post và chỉ thử hoàn tất comment còn thiếu.
