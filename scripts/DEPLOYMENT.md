# Hướng dẫn triển khai (Deployment Guide)

Tài liệu này hướng dẫn cách chạy Bot ở các chế độ khác nhau trên Windows và Ubuntu.

---

## 1. Môi trường Windows

### A. Chạy trực tiếp (Hiện cửa sổ CMD)
- Double-click vào file `scripts/run_windows.bat`.
- Cửa sổ CMD sẽ hiện lên để bạn theo dõi log trực tiếp.

### B. Chạy ẩn (Background)
- Double-click vào file `scripts/run_hidden.vbs`.
- Bot sẽ chạy ngầm, không hiện cửa sổ. Để tắt, bạn phải vào **Task Manager** và kết thúc tiến trình `python.exe`.

### C. Chạy như một Service (Khuyên dùng cho Server)
Để bot tự động chạy khi bật máy mà không cần đăng nhập:
1. Tải công cụ **NSSM** (Non-Sucking Service Manager).
2. Mở CMD với quyền Admin, gõ: `nssm install GoogleDriveSync`.
3. Trong bảng hiện ra:
   - **Path**: Đường dẫn tới file `python.exe` trong venv (ví dụ: `C:\upload-bot\venv\Scripts\python.exe`).
   - **Startup directory**: Thư mục gốc của bot (ví dụ: `C:\upload-bot`).
   - **Arguments**: `main.py`.
4. Nhấn **Install service**.

---

## 2. Môi trường Ubuntu / Linux

### A. Chạy trực tiếp
Cấp quyền thực thi và chạy:
```bash
chmod +x scripts/run_linux.sh
./scripts/run_linux.sh
```

### B. Chạy ẩn bằng PM2 (Rất tiện lợi)
Nếu bạn chưa có PM2: `sudo npm install pm2 -g`
Chạy bot:
```bash
pm2 start main.py --name "drive-sync" --interpreter ./venv/bin/python3
# Lưu trạng thái để tự khởi động cùng OS
pm2 save
pm2 startup
```

### C. Chạy bằng Systemd Service
1. Sửa file `scripts/google-drive-sync.service`, thay đổi `username` và đường dẫn đúng với máy của bạn.
2. Copy file vào thư mục hệ thống:
   ```bash
   sudo cp scripts/google-drive-sync.service /etc/systemd/system/
   ```
3. Kích hoạt service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable google-drive-sync
   sudo systemctl start google-drive-sync
   ```
4. Kiểm tra trạng thái:
   ```bash
   sudo systemctl status google-drive-sync
   ```

---

## 3. Môi trường macOS (Macbook)

### A. Chạy trực tiếp
Cấp quyền thực thi và chạy file sh:
```bash
chmod +x scripts/run_mac.sh
./scripts/run_mac.sh
```

### B. Chạy ẩn bằng PM2
Tương tự như Linux, Mac sử dụng PM2 rất ổn định:
```bash
pm2 start main.py --name "drive-sync" --interpreter ./venv/bin/python3
pm2 save
```

### C. Chạy như một Background Service (Launchd)
Để bot tự khởi động cùng macOS:
1. Sửa file `scripts/com.user.googledrivesync.plist`: thay `yourname` và các đường dẫn thành đường dẫn thực tế trên Mac của bạn.
2. Copy file này vào thư mục LaunchAgents:
   ```bash
   cp scripts/com.user.googledrivesync.plist ~/Library/LaunchAgents/
   ```
3. Kích hoạt service:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.user.googledrivesync.plist
   ```
4. Để dừng service:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.user.googledrivesync.plist
   ```

---

## 📝 Lưu ý chung
- Luôn đảm bảo file `credentials.json` đã được đặt ở thư mục gốc trước khi chạy.
- Nếu chạy lần đầu ở môi trường Server không có giao diện (Headless Linux), bạn nên chạy trực tiếp trên máy cá nhân một lần để lấy file `token.json`, sau đó copy `token.json` lên Server.
