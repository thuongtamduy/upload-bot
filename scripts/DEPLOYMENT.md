# Hướng dẫn triển khai (Deployment Guide)

Tài liệu này hướng dẫn cách chạy Bot ở các chế độ khác nhau trên Windows, Ubuntu và macOS.

---

## 1. Môi trường Windows

### A. Chạy trực tiếp (Hiện cửa sổ CMD)
- Double-click vào file `scripts/run_windows.bat`.
- Cửa sổ CMD sẽ hiện lên để bạn theo dõi log trực tiếp.

### B. Chạy ẩn (Background)
- Double-click vào file `scripts/run_hidden.vbs`.
- Bot sẽ chạy ngầm, không hiện cửa sổ.
- Để tắt, chạy file `scripts/stop_windows.bat`.

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

### A. Cấp quyền thực thi (chỉ làm 1 lần)
```bash
chmod +x scripts/run_linux.sh
```

### B. Chạy script (hỗ trợ 2 chế độ)
```bash
./scripts/run_linux.sh
```
Script sẽ hỏi bạn chọn chế độ:
- **[1] Chạy trực tiếp** trên terminal, xem log ngay, Ctrl+C để thoát.
- **[2] Cài Systemd Service** — Bot tự chạy khi máy khởi động lại.

> ⚠️ **Lưu ý quan trọng:** Lần đầu tiên bắt buộc phải chọn **[1]** để hoàn thành xác thực Google OAuth (cần mở trình duyệt). Sau khi có file `token.json` mới có thể cài chế độ **[2]**.

### C. Lệnh quản lý Systemd Service
```bash
# Xem log realtime
journalctl -u google-drive-sync -f

# Dừng bot
sudo systemctl stop google-drive-sync

# Gỡ cài đặt (không tự chạy khi khởi động nữa)
sudo systemctl disable google-drive-sync
```

### D. Chạy ẩn bằng PM2 (tuỳ chọn thay thế)
```bash
sudo npm install pm2 -g
pm2 start main.py --name "drive-sync" --interpreter ./venv/bin/python3
pm2 save && pm2 startup
```

---

## 3. Môi trường macOS

### A. Cấp quyền thực thi (chỉ làm 1 lần)
```bash
chmod +x scripts/run_mac.sh scripts/stop_mac.sh
```

### B. Chạy script (hỗ trợ 2 chế độ)
```bash
./scripts/run_mac.sh
```
Script sẽ hỏi bạn chọn chế độ:
- **[1] Chạy trực tiếp** trên terminal, xem log ngay, Ctrl+C để thoát.
- **[2] Cài LaunchAgent** — Bot tự chạy khi đăng nhập macOS, KeepAlive tự restart nếu crash.

> ⚠️ **Lưu ý quan trọng:** Lần đầu tiên bắt buộc phải chọn **[1]** để hoàn thành xác thực Google OAuth (cần mở trình duyệt). Sau khi có file `token.json` mới có thể cài chế độ **[2]**.

### C. Dừng bot (cả 2 chế độ)
```bash
./scripts/stop_mac.sh
```
Script này sẽ tự động gỡ LaunchAgent và kill tiến trình nếu còn sót lại.

---

## 📝 Lưu ý chung
- Luôn đảm bảo file `credentials.json` đã được đặt ở thư mục gốc trước khi chạy.
- Nếu chạy lần đầu ở môi trường Server/Headless không có giao diện, hãy chạy trực tiếp trên máy cá nhân một lần để lấy file `token.json`, sau đó copy `token.json` lên Server.
- Log được ghi vào file `history.log` ở thư mục gốc.
