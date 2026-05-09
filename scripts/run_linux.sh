#!/bin/bash

# Lấy đường dẫn tuyệt đối của thư mục chứa script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

echo "🚀 Google Drive Sync Bot"
echo "========================="
echo "Chọn chế độ chạy:"
echo "  1) Chạy trực tiếp trên terminal (Ctrl+C để thoát)"
echo "  2) Cài đặt chạy ngầm bằng Systemd Service (tự khởi động cùng máy)"
echo ""
read -r -p "Nhập lựa chọn [1/2]: " choice

# Kiểm tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Lỗi: Không tìm thấy python3. Vui lòng cài đặt: sudo apt install python3 python3-venv"
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
    SERVICE_SRC="$SCRIPT_DIR/google-drive-sync.service"
    SERVICE_DEST="/etc/systemd/system/google-drive-sync.service"

    # Cảnh báo: nếu chưa xác thực Google thì service sẽ crash vì không có browser
    if [ ! -f "token.json" ]; then
        echo ""
        echo "⚠️  CẢNH BÁO: Chưa có file 'token.json'."
        echo "   Bạn cần chạy bot trực tiếp ít nhất 1 lần (chọn [1]) để hoàn thành xác thực Google."
        echo "   Sau đó mới có thể cài đặt chạy ngầm."
        exit 1
    fi

    # Điền đường dẫn thực vào file service
    BOT_DIR="$(pwd)"
    PYTHON_PATH="$BOT_DIR/venv/bin/python3"
    CURRENT_USER="$(whoami)"

    TMP_SERVICE="/tmp/google-drive-sync.service"
    sed "s|User=username|User=$CURRENT_USER|g; \
         s|WorkingDirectory=.*|WorkingDirectory=$BOT_DIR|g; \
         s|ExecStart=.*|ExecStart=$PYTHON_PATH $BOT_DIR/main.py|g" \
         "$SERVICE_SRC" > "$TMP_SERVICE"

    sudo cp "$TMP_SERVICE" "$SERVICE_DEST"
    sudo systemctl daemon-reload
    sudo systemctl enable google-drive-sync
    sudo systemctl start google-drive-sync

    echo ""
    echo "✅ Đã cài đặt và khởi động Bot chạy ngầm (systemd)!"
    echo "   - Bot sẽ tự động chạy lại mỗi khi máy khởi động."
    echo "   - Xem log: journalctl -u google-drive-sync -f"
    echo "   - Dừng bot: sudo systemctl stop google-drive-sync"
    echo "   - Gỡ cài đặt: sudo systemctl disable google-drive-sync"
else
    echo ""
    echo "▶️  Đang khởi động bot trực tiếp... (Bấm Ctrl+C để thoát)"
    python3 main.py
fi
