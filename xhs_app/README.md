# 小紅書每週分析系統（桌面應用程式）

這是現有系統的桌面 GUI 版，放在獨立資料夾 `xhs_app/`，不影響原系統。

## 執行

```powershell
cd "C:\Users\DanielHau\Documents\New prototype"
python xhs_app\app.py
```

（用 `pythonw xhs_app\app.py` 則不會顯示黑色主控台視窗。）

## 功能

- **運行**：測試執行（不寄信）／正式執行／跳過抓取重跑；即時顯示執行日誌；一鍵開啟最新 HTML 或 PDF 報告
- **設定**：圖形化編輯 `.env`（Apify、OpenRouter、寄信、收件人）
- **連結**：直接編輯 `data/posts.xlsx` 的帖文連結
- **說明**：使用提示

## 包裝成 exe（可選，給其他人免安裝 Python）

```powershell
pip install pyinstaller
pyinstaller --onedir --windowed --name XHSWeeklyReport xhs_app\app.py
```

注意：打包後需要把 `run_weekly.py`、`xhs_report/`、`config.yaml`、`requirements.txt`、
`.env.example`、`data/` 放在 exe 所在資料夾的上一層（程式以父資料夾為專案根目錄）。
