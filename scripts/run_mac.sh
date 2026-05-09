#!/bin/bash

# Lấy đường dẫn tuyệt đối của thư mục chứa script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

echo "🚀 Google Drive Sync Bot"
echo "========================="
echo "Chọn chế độ chạy:"
echo "  1) Chạy trực tiếp trên terminal (Ctrl+C để thoát)"
echo "  2) Cài đặt chạy ngầm tự động khi đăng nhập macOS (LaunchAgent)"
echo ""
read -r -p "Nhập lựa chọn [1/2]: " choice

# Kiểm tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Lỗi: Không tìm thấy python3. Vui lòng cài đặt Python từ python.org hoặc dùng brew."
    exit 1
fi

# Tạo venv nếu chưa có
if [ ! -d "venv" ]; then
    echo "📦 Đang tạo môi trường ảo venv..."
    python3 -m venv venv
fi

# Kích hoạt venv và cài đặt dependencies
source venv/bin/activate
pip install -q -r requirements.txt

if [ "$choice" == "2" ]; then
    PLIST_SRC="$SCRIPT_DIR/com.user.googledrivesync.plist"
    PLIST_DEST="$HOME/Library/LaunchAgents/com.user.googledrivesync.plist"

    # Cảnh báo: nếu chưa xác thực Google thì LaunchAgent sẽ crash vì không có browser
    if [ ! -f "token.json" ]; then
        echo ""
        echo "⚠️  CẢNH BÁO: Chưa có file 'token.json'."
        echo "   Bạn cần chạy bot trực tiếp ít nhất 1 lần (chọn [1]) để hoàn thành xác thực Google."
        echo "   Sau đó mới có thể cài đặt chạy ngầm."
        exit 1
    fi

    # Gỡ service cũ nếu đang chạy để tránh conflict
    launchctl unload "$PLIST_DEST" 2>/dev/null

    cp "$PLIST_SRC" "$PLIST_DEST"
    launchctl load "$PLIST_DEST"

    echo ""
    echo "✅ Đã cài đặt và khởi động Bot chạy ngầm!"
    echo "   - Bot sẽ tự động chạy lại mỗi khi bạn đăng nhập macOS."
    echo "   - Log được ghi vào: history.log"
    echo "   - Để dừng bot, chạy: scripts/stop_mac.sh"
else
    echo ""
    echo "▶️  Đang khởi động bot trực tiếp... (Bấm Ctrl+C để thoát)"
    python3 main.py
fi
