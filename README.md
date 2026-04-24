# Google Drive Sync Bot 🚀
> Phát triển bởi **thuongtamduy** ([thuongtamduy.com](https://thuongtamduy.com))

Một công cụ mạnh mẽ và chuyên nghiệp để đồng bộ hóa dữ liệu thời gian thực giữa máy tính của bạn và Google Drive. Bot được thiết kế để hoạt động ổn định, hỗ trợ tải lên các tệp tin lớn, quản lý băng thông và thông báo qua Telegram.

## ✨ Tính năng nổi bật

- **Đồng bộ thời gian thực**: Tự động phát hiện thay đổi (thêm, sửa, xóa, đổi tên) và cập nhật lên Google Drive ngay lập tức.
- **True Resume Upload**: Hỗ trợ khôi phục phiên tải lên khi bị ngắt quãng (mất mạng, tắt máy), cực kỳ hữu ích cho các tệp tin hàng GB.
- **Đồng bộ hai chiều tùy chỉnh**:
    - **Upload**: Đẩy dữ liệu từ máy lên Drive.
    - **Download (Sync Back)**: Tự động kéo file từ Drive về máy nếu máy bị thiếu.
    - **Smart Deletion**: Tùy chọn giữ lại hoặc xóa file trên Drive khi file cục bộ bị xóa.
- **Giới hạn băng thông**: Kiểm soát tốc độ tải lên để không làm ảnh hưởng đến các công việc khác.
- **Thông báo Telegram**: Nhận thông báo ngay lập tức qua bot Telegram khi các tệp tin lớn được tải lên thành công.
- **Hệ thống Ignore**: Loại bỏ các file/thư mục không cần thiết (như `.git`, `node_modules`, `tmp`) thông qua file `.syncignore`.

## 🛠 Yêu cầu hệ thống

- Python 3.8 trở lên.
- Tài khoản Google có quyền truy cập Google Drive API.
- File `credentials.json` (từ Google Cloud Console).

## 🚀 Cài đặt

1. **Clone project hoặc tải mã nguồn về máy.**
2. **Cài đặt các thư viện cần thiết**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Cấu hình Google Drive API (Lấy `credentials.json`)**:
   - Truy cập [Google Cloud Console](https://console.cloud.google.com/).
   - **Tạo Project**: Nhấn vào "Select a project" -> "New Project" -> Đặt tên và nhấn "Create".
   - **Bật API**: Tìm kiếm "Google Drive API" trên thanh công cụ và nhấn "Enable".
   - **OAuth Consent Screen**:
     - Vào menu "APIs & Services" -> "OAuth consent screen".
     - Chọn "External" -> "Create".
     - Điền các thông tin bắt buộc (Tên app, Email hỗ trợ, Email admin). Nhấn "Save and Continue".
     - Ở mục "Test users", nhấn **"Add Users"** và nhập email Google của bạn vào. Đây là bước quan trọng để bạn có quyền đăng nhập.
   - **Tạo Credentials**:
     - Vào menu "Credentials" -> "Create Credentials" -> **"OAuth client ID"**.
     - Ở mục "Application type", chọn **"Desktop App"**.
     - Đặt tên và nhấn "Create".
   - **Tải file**: Nhấn vào biểu tượng tải xuống (Download JSON) của Client ID vừa tạo. Đổi tên file thành `credentials.json` và bỏ vào thư mục gốc của dự án.

## ⚙️ Cấu hình (`config.json`)

File `config.json` sẽ được tự động tạo khi bạn chạy bot lần đầu. Bạn có thể tùy chỉnh các thông số sau:

| Tham số | Mô tả |
| :--- | :--- |
| `DRIVE_FOLDER_ID` | ID của thư mục trên Google Drive mà bạn muốn đồng bộ vào. |
| `WATCH_FOLDERS` | Danh sách (mảng) các đường dẫn thư mục trên máy tính cần theo dõi (có thể dùng đường dẫn tuyệt đối). VD: `["thu-muc-1", "D:/thu-muc-2"]` |
| `MAX_UPLOAD_SPEED_MBPS` | Giới hạn tốc độ tải lên (MB/s). Đặt `0` để không giới hạn. |
| `TELEGRAM_BOT_TOKEN` | Token của bot Telegram (nếu muốn nhận thông báo). |
| `TELEGRAM_CHAT_ID` | ID chat Telegram của bạn. |
| `NOTIFY_SIZE_LIMIT_MB` | Chỉ gửi thông báo Telegram cho các file có dung lượng lớn hơn mức này. |
| `DELETE_REMOTE_FILES` | `true`: Xóa file trên Drive nếu máy cục bộ xóa. `false`: Luôn giữ file trên Drive. |
| `SYNC_REMOTE_TO_LOCAL` | `true`: Tải file từ Drive về máy nếu máy bị thiếu. |

## 📂 Quản lý tệp bỏ qua (`.syncignore`)

Bạn có thể tạo file `.syncignore` để liệt kê các mẫu file/thư mục không muốn đồng bộ. Ví dụ:
```text
# Bỏ qua các file ẩn
.*
# Bỏ qua thư mục rác
__pycache__/
node_modules/
# Bỏ qua định dạng file cụ thể
*.tmp
*.log
```

## 🎮 Sử dụng

Chạy bot bằng lệnh:
```bash
python main.py
```

- Trong lần đầu chạy, một cửa sổ trình duyệt sẽ hiện ra để bạn xác thực tài khoản Google.
- Sau khi xác thực, bot sẽ quét toàn bộ thư mục một lần để đồng bộ (Initial Sync).
- Sau đó, bot sẽ chạy ngầm và theo dõi mọi thay đổi để đồng bộ tức thì.
- Bấm `Ctrl + C` để dừng bot an toàn.

## 📝 Lưu ý

- Các file đang được sao chép hoặc đang bị chiếm dụng bởi ứng dụng khác sẽ được bot tạm thời bỏ qua và thử lại sau.
- Khi bật `SYNC_REMOTE_TO_LOCAL`, hãy cẩn thận nếu thư mục trên Drive có dung lượng quá lớn so với ổ cứng máy tính của bạn.

---
Chúc bạn sử dụng hiệu quả! 🛠️

## 📄 License

Project này được phát hành dưới bản quyền **MIT License**. Bạn hoàn toàn có quyền sử dụng, sửa đổi và phân phối lại mã nguồn này cho mục đích cá nhân hoặc thương mại.
