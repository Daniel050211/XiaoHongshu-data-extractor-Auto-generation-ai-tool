# 部署指南：如何在自己的電腦上運行本系統

> 給團隊成員：跟著下面步驟，約 15 分鐘可以把系統跑起來。

## 目前的實際設定（團隊共用）

以下是目前系統實際使用的設定（機密金鑰除外），團隊成員請照此設定：

| 項目 | 設定值 |
|---|---|
| AI 平台 | OpenRouter（`AI_BASE_URL=https://openrouter.ai/api/v1`） |
| AI 模型 | `z-ai/glm-5.2` |
| 寄信方式 | 本機 Outlook（`EMAIL_PROVIDER=outlook`） |
| 寄件人 | `danielhau@k11byac.com` |
| 收件人 | `matthewhung@k11byac.com,danielhau@k11byac.com`（上級 + 自己） |
| 週次起點 | `2026-07-01`（W1 = 7/1–7/7，之後每 7 天一週） |
| 自動執行 | 每週五 09:00（Windows 工作排程） |
| 連結來源 | `data/posts.xlsx`（第一欄 `post_url`） |
| 報告輸出 | `data/reports/`（HTML + PDF + CSV） |
| 抓取模式 | Apify actor `svGBZz6n79YbeA3uS`，post_details |

> 🔑 **金鑰（機密）不寫在文件裡**：請向 Daniel 索取相同的 `.env` 檔案直接複製，或索取對應的 API key 自行填入。

> ⚠️ **Outlook 寄信注意**：`EMAIL_PROVIDER=outlook` 是用「本機已登入的 Outlook 帳號」寄出。若要在別人的電腦上運行，對方需用自己的 Microsoft 365 帳號登入 Outlook，並把 `EMAIL_FROM` 改成自己的信箱（或改用 SendGrid）。

## 換成自己的帳號（不共用 Daniel 的）需要改什麼

團隊可以共用設定（AI 模型、週次、報告格式），但建議**各用自己的帳號**。需要改的地方，全部在應用程式的「**設定**」頁籤（或直接改 `.env`）：

| 項目 | 要改的欄位 | 去哪裡申請 |
|---|---|---|
| 小紅書抓取 | `APIFY_API_KEY` | Apify → Settings → API tokens（actor 可沿用同一個，費用記在自己帳號） |
| 小紅書登入 Cookie（選填） | `APIFY_COOKIE_STRING` | 登入 xiaohongshu.com 後複製 Cookie |
| AI 分析 | `AI_API_KEY` | OpenRouter → Keys |
| AI 模型（可選） | `AI_MODEL` | 應用程式下拉選單（內含 414 個 OpenRouter 模型） |
| 寄信方式 | `EMAIL_PROVIDER` | outlook（自己登入自己的 Outlook）或 sendgrid |
| 寄件人 | `EMAIL_FROM` | 自己的信箱 |
| 收件人 | `EMAIL_TO` | 上級信箱（可再加上自己，用逗號分隔） |
| 每週執行時間 | 應用程式「排程」頁 | 自己設定 |

**不用改的**：`config.yaml` 的週次起點（2026-07-01）、Excel 格式、報告格式、Apify actor ID（`svGBZz6n79YbeA3uS` 是公開 actor，誰呼叫就記在誰的帳號）。

## 多帳號模式（同一個收件人，每個帳號一封報告）

- 每個小紅書帳號有**自己的一份 Excel**（預設放在 `data/accounts/<帳號名稱>.xlsx`）
- 在應用程式「**連結**」頁：點「**＋新增帳號**」→ 輸入帳號名稱 → 貼入該帳號的帖文連結 → 儲存
- 執行時自動**逐個帳號**處理：抓取 → 分析 → 各帳號獨立報告 → **各寄一封**（同一收件人）
- **錯誤隔離**：單一帳號連結失效/抓不到不會影響其他帳號；該帳號會標記失敗並繼續下一個
- 帳號清單存在 `data/accounts.json`（由應用程式管理）
- ⚠️ 帳號多時成本與時間會增加：每帳號每週一次 Apify 抓取 + 一次 AI 分析 + 一封郵件

## 0. 你需要準備什麼

- Windows 電腦（10 或 11）
- 整個專案資料夾的副本（含 `run_weekly.py`、`xhs_report/`、`config.yaml`、`requirements.txt`、`.env.example`、`data/posts.xlsx`）
- **自己的** API key（每個人都要自己申請，不要共用別人的）：
  - Apify API key（小紅書抓取）
  - OpenRouter API key（AI 分析，模型 `z-ai/glm-5.2`）
- 寄信方式二選一：
  - **本機 Outlook**（Microsoft 365 帳號，已登入 Outlook 桌面版）
  - 或 **SendGrid** API key
- 收件人 email（本團隊：`matthewhung@k11byac.com,danielhau@k11byac.com`）

## 1. 安裝 Python

1. 到 <https://www.python.org/downloads/> 下載 **Python 3.12–3.14**（Windows installer）
2. 安裝時**務必勾選「Add python.exe to PATH」**
3. 驗證（開新的命令提示字元）：
   ```powershell
   python --version
   ```

## 2. 安裝相依套件

在專案資料夾開啟 PowerShell，執行：
```powershell
cd "你的專案路徑"
pip install -r requirements.txt
```

## 3. 設定 .env

把 `.env.example` 複製成 `.env`，填入：

```ini
APIFY_API_KEY=<與團隊相同的 Apify key>
AI_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=z-ai/glm-5.2
AI_API_KEY=<與團隊相同的 OpenRouter key>

EMAIL_PROVIDER=outlook
EMAIL_FROM=danielhau@k11byac.com
EMAIL_TO=matthewhung@k11byac.com,danielhau@k11byac.com

# 如果用 SendGrid（不需要本機 Outlook）：
SENDGRID_API_KEY=<SendGrid key，選填>
```

> ⚠️ `.env` 含機密，不要上傳 git、不要分享給別人。

## 4. 放帖文連結

編輯 `data/posts.xlsx`：第一欄表頭 `post_url`，每列放一個帖文連結。

> 建議只放**本週 + 前一週**的帖文（系統只分析這兩個週次）。

## 4.5 啟動應用程式（不用懂指令）

- 雙擊 **`Launch XHS App.cmd`** → 應用程式直接開啟
- 雙擊 **`Create Desktop Shortcut.cmd`** → 在你的桌面建立「XHS Weekly Report」捷徑，之後雙擊捷徑即可

## 4.6 免安裝 Python 的版本（exe）

- 專案根目錄已有 **`XHSWeeklyReport.exe`**（約 33MB）——**不需要安裝 Python**
- 使用方法：雙擊 `XHSWeeklyReport.exe`，或雙擊 `Launch XHS App.cmd`（會自動優先使用 exe）
- ⚠️ **exe 必須放在專案根目錄**（與 `config.yaml`、`.env`、`data/` 同一層），因為它把「exe 所在資料夾」當成專案根目錄
- 若要寄出給別人：把**整個資料夾**壓縮打包（含 exe、config.yaml、.env.example、data/posts.xlsx、Launch XHS App.cmd、Create Desktop Shortcut.cmd）

## 5. 執行

```powershell
# 先測試（不寄信）
python run_weekly.py --dry-run

# 正式執行（抓取 → 分析 → PDF → 寄信）
python run_weekly.py

# 跳過抓取、只用現有資料重跑（省 Apify 費用）
python run_weekly.py --skip-scrape
```

成功的話，`data/reports/` 會出現 HTML + PDF + CSV，郵件會寄到收件人信箱。

## 6.（可選）每週五自動執行

以管理員 PowerShell 執行（路徑改成你的）：
```powershell
schtasks /Create /TN "XHS Weekly Report" /TR "\"C:\你的Python路徑\python.exe\" \"C:\你的專案路徑\run_weekly.py\"" /SC WEEKLY /D FRI /ST 09:00 /F
```

## 7. 常見問題

| 問題 | 原因 / 解法 |
|---|---|
| 抓不到帖文 | Apify key 錯誤，或 Excel 連結的 xsec_token 過期（重新從 App 分享） |
| 報告是「乾跑模式」 | `.env` 沒填 `AI_API_KEY` |
| 沒收到信 | `EMAIL_TO` 沒填；用 Outlook 方式但本機 Outlook 沒登入 |
| 用 Outlook 寄信失敗 | 需用你自己的 Microsoft 365 帳號登入 Outlook 桌面版；或改用 SendGrid |
| 網址報錯/權限不足 | 檢查 `.env` 路徑、Python 是否加入 PATH |

## 8. 系統架構（簡介）

```
Excel/Google Sheets 讀取連結 → Apify 抓取 → SQLite 儲存
→ 週次/初步完整標記 → GLM-5.2 AI 分析（執行摘要）
→ HTML + PDF + CSV 報告 → Outlook / SendGrid 寄信
```

詳細設定說明見 [README.md](README.md)。
