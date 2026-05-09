#!/bin/bash

PLIST_LABEL="com.user.googledrivesync"
PLIST_SRC="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/com.user.googledrivesync.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

echo "🛑 Đang dừng Google Drive Sync Bot..."

# Kiểm tra nếu service đang được load thì unload
if launchctl list | grep -q "$PLIST_LABEL"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null
    echo "✅ Đã dừng và gỡ service '$PLIST_LABEL' khỏi LaunchAgent."
else
    echo "⚠️  Service '$PLIST_LABEL' không đang chạy."
fi

# Kiểm tra xem tiến trình python main.py còn sót lại không thì kill luôn
PID=$(pgrep -f "main.py" 2>/dev/null)
if [ -n "$PID" ]; then
    kill "$PID"
    echo "✅ Đã kill tiến trình PID $PID (main.py)."
fi

echo ""
echo "💤 Bot đã được tắt hoàn toàn."
