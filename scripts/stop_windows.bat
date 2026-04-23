@echo off
setlocal
echo Đang tìm và dừng Google Drive Sync Bot...

:: Sử dụng PowerShell để tìm đúng tiến trình python đang chạy file main.py và kill nó
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { (Get-CimInstance Win32_Process -Filter \"ProcessId = $($_.Id)\").CommandLine -like '*main.py*' } | Stop-Process -Force"

if %ERRORLEVEL% EQU 0 (
    echo [OK] Đã dừng Bot thành công.
) else (
    echo [!] Không tìm thấy tiến trình Bot đang chạy hoặc đã dừng trước đó.
)

timeout /t 3
