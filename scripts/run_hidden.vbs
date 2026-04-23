Set WinScriptHost = CreateObject("WScript.Shell")
' Chạy file bat ở chế độ ẩn (0)
WinScriptHost.Run Chr(34) & "run_windows.bat" & Chr(34), 0
Set WinScriptHost = Nothing
