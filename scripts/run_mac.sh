#!/bin/bash

# Lấy đường dẫn tuyệt đối của thư mục chứa script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

echo "Đang khởi động Google Drive Sync Bot trên macOS..."

# Kiểm tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "Lỗi: Không tìm thấy python3. Vui lòng cài đặt Python từ python.org hoặc dùng brew."
    exit 1
fi

# Tạo venv nếu chưa có
if [ ! -d "venv" ]; then
    echo "Đang tạo môi trường ảo venv..."
    python3 -m venv venv
fi

# Kích hoạt venv và cài đặt dependencies
source venv/bin/activate
pip install -r requirements.txt

# Chạy bot
python3 main.py
