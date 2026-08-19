@echo off
rem 啟動 ngrok 隧道：把手機表單公開網址對應到本機 18765 埠
rem 已放入「啟動」資料夾，登入 Windows 時會自動背景執行
start "" /min "C:\Users\DanielHau\ngrok\ngrok.exe" http --url=https://unwary-mongoose-antarctic.ngrok-free.dev 18765
