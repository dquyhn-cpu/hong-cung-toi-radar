# Facebook Group Poster V1 — Hóng Cùng Tôi

Công cụ này **tách hoàn toàn** khỏi Page Publisher/Meta Graph API.

## Mục tiêu V1
- Chạy trên máy Windows của anh.
- Dùng trình duyệt Chromium riêng với session Facebook riêng.
- Anh đăng nhập Facebook thủ công một lần.
- Test **1 Group duy nhất** trước.
- Mặc định chỉ chuẩn bị composer + chụp preview, **không bấm Đăng**.
- Chỉ khi chạy thêm `--confirm-post` mới bấm nút Đăng.

## 1) Cài đặt

Mở PowerShell tại thư mục repo:

```powershell
cd group_poster
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## 2) Đăng nhập Facebook một lần

```powershell
python group_poster.py --login
```

Một cửa sổ Chromium riêng sẽ mở. Đăng nhập **tài khoản Facebook cá nhân có quyền đăng trong Group**, hoàn tất 2FA/checkpoint nếu có, rồi quay lại PowerShell bấm Enter.

Session được lưu tại:
`%USERPROFILE%\.hong-cung-toi\facebook-group-profile`

Không copy cookie/password sang GitHub.

## 3) Test Group đầu tiên ở chế độ preview

Group test đầu tiên:
`https://www.facebook.com/groups/782708824657028`

Tạo file `message.txt` và chọn một ảnh test, sau đó:

```powershell
python group_poster.py ^
  --group-url "https://www.facebook.com/groups/782708824657028" ^
  --message-file "message.txt" ^
  --image "C:\duong-dan\anh.jpg"
```

Tool sẽ:
1. mở Group;
2. mở composer;
3. điền nội dung;
4. tải ảnh;
5. chụp `output/group_post_preview.png`;
6. **dừng, không đăng**.

## 4) Khi preview đúng mới đăng thật

```powershell
python group_poster.py ^
  --group-url "https://www.facebook.com/groups/782708824657028" ^
  --message-file "message.txt" ^
  --image "C:\duong-dan\anh.jpg" ^
  --confirm-post
```

Sau khi bấm Đăng, tool chụp `output/group_post_after_submit.png`.

## Nguyên tắc an toàn
- Không bypass CAPTCHA/checkpoint/2FA.
- Không lưu password/token Facebook trong repo.
- Không dùng cookies ngoài browser profile cục bộ.
- Không chạy hàng loạt trước khi 1 Group test hoạt động ổn định.
- Nếu Group bật duyệt bài, tool chỉ có thể gửi bài vào hàng chờ; vẫn cần xác minh trạng thái.
- Facebook đổi UI có thể làm selector hỏng; khi đó sửa Group Poster, **không sửa Page Publisher**.

## Bước tiếp theo sau V1
Sau khi Group #1 test ổn định:
- thêm `groups.json`;
- thêm queue GROUP_READY;
- log kết quả từng Group;
- retry có giới hạn;
- dừng khi phát hiện checkpoint;
- không đăng lặp.
