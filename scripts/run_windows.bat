@echo off
echo Đang khởi động Google Drive Sync Bot...
cd /d "%~dp0.."
if not exist venv (
    echo Đang tạo môi trường ảo venv...
    python -m venv venv
)
call venv\Scripts\activate
echo Đang cập nhật thư viện...
pip install -r requirements.txt
python main.py
pause
