@echo off
rem 啟動 ngrok 隧道：把手機表單公開網址對應到本機 18765 埠
rem 別人使用時：把下方網址換成自己的 Static Domain，並把 ngrok.exe 放在本檔同一層
set "NGROK=%~dp0ngrok.exe"
if not exist "%NGROK%" set "NGROK=C:\Users\DanielHau\ngrok\ngrok.exe"
if not exist "%NGROK%" (
  echo 找不到 ngrok.exe，請到 https://ngrok.com/download 下載後放回本資料夾
  pause
  exit /b 1
)
start "" /min "%NGROK%" http --url=https://unwary-mongoose-antarctic.ngrok-free.dev 18765
