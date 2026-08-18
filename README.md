# 小紅書每週數據分析與報告系統

每週固定一天自動：從 Excel / Google Sheets 讀取帖文連結 → Apify 抓取數據 → SQLite 儲存 → AI 分析 → 產生 HTML + CSV 報告 → 寄到上級郵箱。

## 快速開始

1. 安裝 Python（若尚未安裝）：<https://www.python.org/downloads/>
2. 安裝相依套件：
   ```powershell
   pip install -r requirements.txt
   ```
3. 把 `.env.example` 複製成 `.env`，填入：
   - `APIFY_API_KEY`（必填，Apify 後台 → Settings → API tokens）
   - `AI_API_KEY`（選填，OpenAI 或相容 API；未填時以「乾跑模式」產出報告）
   - `SMTP_USER` / `SMTP_PASSWORD` / `EMAIL_TO`（選填；Gmail 請用「應用程式密碼」）
4. 準備連結清單：
   - Excel：在 `data/posts.xlsx` 第一欄放帖文連結（表頭寫 `post_url` 或 `連結` 都可以）
   - 或改 `config.yaml` 的 `link_source.type: google`，填入 `google_sheet_id`；私人 sheet 需再給 service account JSON
5. 先試跑（不會寄信）：
   ```powershell
   python run_weekly.py --dry-run --run-date 2026-07-17
   ```
6. 正式跑：
   ```powershell
   python run_weekly.py
   ```

## 每週自動執行（Windows 工作排程器）

以管理員 PowerShell 執行（路徑請換成你的實際路徑）：

```powershell
schtasks /Create /TN "XHS Weekly Report" /TR "\"C:\path\to\python.exe\" \"C:\Users\DanielHau\Documents\New prototype\run_weekly.py\"" /SC WEEKLY /D FRI /ST 09:00 /F
```

## 週次規則

- 週次是固定 7 天區塊，由 `config.yaml` 的 `weeks.anchor` 起算：W1 = 7/1–7/7、W2 = 7/8–7/14…（可改）
- 程式會依執行日期自動找出「最新完整週」當目標、前一週當基準，不需要每週改設定
- 每篇帖文第一次被抓取標記為「初步」（新一週數據）；隔週第二次抓取後改為「完整」（數據已成熟）
- 已達「完整」狀態的連結不會再被抓取（節省 Apify 費用）；報告中「初步 vs 完整」區塊顯示同一批帖文兩次抓取的成長
- 想用現有資料重跑報告而不抓取：`python run_weekly.py --skip-scrape`

## 改用自動抓取帳號全部帖文（不需要維護連結清單）

如果分析對象是自己（或固定幾個）帳號，`config.yaml` 可以改：

```yaml
apify:
  mode: user_posts
  user_urls:
    - "https://www.xiaohongshu.com/user/profile/<id>"
```

這樣每週會自動抓帳號內最新帖文，依發布日期歸到對應週次，不必再手動貼連結。

## 常見問題

- **抓不到數據**：先確認 Apify actor 單獨在 console 跑得動、連結有效（xsec_token 會過期）
- **報告是乾跑模式**：`.env` 未填 `AI_API_KEY`
- **沒收到信**：
  - 本機網路會封鎖 SMTP 埠（25/465/587），請用郵件 API（走 443）：
    - **SendGrid**（推薦，單一寄件人驗證不需 DNS）：到 <https://sendgrid.com> 註冊 → Settings → Sender Authentication → Single Sender Verification 驗證寄件信箱（點確認信）→ 建立 API Key → 填入 `.env` 的 `SENDGRID_API_KEY`
    - **Brevo**：<https://brevo.com> 註冊後驗證寄件人，填入 `BREVO_API_KEY`
    - **Resend**：<https://resend.com> 需驗證整個網域（要 DNS 權限），填入 `RESEND_API_KEY`
  - `.env` 需填 `EMAIL_TO`（收件人）與 `EMAIL_FROM`（寄件人）
- **初步數據太多**：把 `min_window_hours` 調大（如 72），或改在週二/週三跑，讓最後一天數據更成熟
- **標題是空的**：此 actor 的 post_details 模式對部分帖文抓不到獨立標題（與 networkCapture 無關，實測開啟後欄位相同）；系統會自動用內容第一行當標題，若需要真實標題建議改用其他 actor 或 `user_posts` 模式

---

# 佛山產業新聞 AI（n8n「Schedule Trigger」線）

把 n8n 佛山工作流中 **14:00 Schedule Trigger 新聞線**（Serper 搜尋 → AI 方向選擇 → 審批 → 深度分析 → 小紅書腳本 → 審批 → Tagline/圖片 Prompt → 寄信）抽出來做成本機系統。小紅書爬蟲分析線（9:00）仍是上面的 `run_weekly.py`。

## 流程

1. 每天 14:00（可改）以 Serper 搜尋佛山產業新聞（AI / 機器人 / 新能源 / 新材料 / 無人機）
2. 自動合併、分類、寫入本地 SQLite（`data/news.db`，Google Sheets 同步為選配）
3. AI（OpenRouter，預設 `z-ai/glm-5.2`）從新聞中提煉 3 個分析方向，寄信通知
4. 在**桌面 App**（或 CLI）審批方向：方向1 / 方向2 / 方向3 / 拒絕全部（最多重試 2 次）
5. AI 依選定方向生成深度分析（1000–1600 字）
6. AI 生成 3 版小紅書腳本（反差型 / 數據型 / 判斷型），寄信通知審批
7. 在桌面 App 選擇要發布的版本（或拒絕重試）
8. AI 產出 Tagline + 圖片生成 Prompt，寄信到收件人信箱

## 快速開始

1. 在 `.env` 補上 `SERPER_API_KEY`（[serper.dev](https://serper.dev) 申請，新聞搜尋用）
2. 離線試跑（不寄信、不呼叫真實 AI，用內建假資料）：
   ```powershell
   $env:NEWS_AI_FAKE = "1"
   python run_news.py --run --dry-run --from-json data/fixtures/news_serper_sample.json
   python run_news.py --approve-direction 1 2 --dry-run
   python run_news.py --approve-script 1 3 --dry-run
   python run_news.py --show 1
   ```
3. 正式跑：`python run_news.py --run`（會寄方向選擇信，然後停在審批）
4. 審批：`python run_news.py --approve-direction <run> 1|2|3|reject "意見"`
   `python run_news.py --approve-script <run> 1|2|3|reject "意見"`
5. 桌面 App：`python run_news.py --app`（或雙擊 `Launch News App.cmd`）

## 每日自動執行

在 App「排程」分頁設定，或用 CLI：
```powershell
python -c "from news_app import scheduler; print(scheduler.apply_schedule(scheduler.load_config()))"
```
預設每天 14:00（香港時間）執行，任務名稱為「佛山新聞 AI」。

## 多帳號新聞線（每個帳號不同主題）

每個帳號放在 `config/news_accounts/` 資料夾（一個帳號一個 yaml 檔），
也可以直接寫在 `config.yaml` 的 `news.accounts`（兩者會合併）。每個帳號有自己的：

- `place`：地區/城市名（例如「台北」），模板裡殘留的「佛山」會全部換成它
- `query`：搜尋關鍵字（旅遊號搜旅遊、產業號搜產業）
- `audience` / `topics`：目標讀者與關注主題（會替換方向選擇、深度分析、腳本、Tagline 的 prompt）
- `tone` / `hashtags`：腳本語氣與常用標籤
- `prompt_directions` / `prompt_analysis` / `prompt_scripts` / `prompt_tagline`：選填，
  填了就用該帳號自己的完整 system prompt（空白時才用上面的 audience/topics/tone 自動替換）
- `email_to`：該帳號自己的收件人（不填用 `.env` 的 `EMAIL_TO`）
- 回饋與記憶：每個帳號讀**自己**的小紅書週報摘要（`xhs.db` 中同名帳號），定稿後寫入自己的記憶庫，下一輪繼續參考

執行：
```powershell
python run_news.py --run                       # 跑全部啟用帳號
python run_news.py --run --account 佛山旅遊號    # 只跑旅遊號
```

> 隔離原則：改 `佛山旅遊號.yaml` 只會影響旅遊號；其他帳號的設定完全不動。
> 即使某個帳號檔寫壞，也只會跳過該帳號（其他帳號照常執行）。

## Email 回覆審批（人不在電腦前也能批）

每封審批信的主旨都帶 `（#run 編號）`，內文附兩種審批方式：

1. **網頁表單**：點信內連結，瀏覽器填寫送出
2. **直接回覆 Email**：回覆該封信，第一行寫
   `方向1 / 方向2 / 方向3 / 拒絕全部`（腳本階段改寫 `版本1 / 版本2 / 版本3`），
   第二行開始寫修改意見

系統會自動讀取回覆並繼續流程：

- 桌面 App 開啟時：內建監看（`config.yaml` 的 `news.mail.watch: true`，每 45 秒檢查一次）
- 或常駐執行：`python run_news.py --watch-mail`
- 或排程定時檢查：`python run_news.py --check-mail`

> 預設用本機已登入的 Outlook 讀信；若要在別台電腦/手機也能收，可在 `.env` 設
> `EMAIL_IMAP_HOST / EMAIL_IMAP_USER / EMAIL_IMAP_PASSWORD`（Gmail 需「應用程式密碼」）。

## 給老闆/同事用的免安裝版（exe）

專案根目錄的 **`FoshanNewsAI.exe`** 是打包好的桌面 App（不需安裝 Python）：

- 雙擊 `FoshanNewsAI.exe`（或 `Launch News App.cmd`）直接開啟
- 打包後 exe 仍把「exe 所在資料夾」當成專案根目錄，所以 **exe 必須放在專案根目錄**，
  與 `config.yaml`、`.env`、`config/news_accounts/`、`data/` 同一層
- 程式碼改動後重新打包：
  ```powershell
  python -m PyInstaller --noconfirm --clean FoshanNewsAI.spec
  copy /Y dist\FoshanNewsAI.exe FoshanNewsAI.exe
  ```
- 換到別台電腦：把整個專案資料夾（含 exe、config.yaml、.env.example、config/news_accounts/、data/）壓縮帶過去；
  對方填自己的 `.env`（Serper / AI key、EMAIL_TO、寄信方式）即可
- 若要寄信穩定，建議用 SendGrid/Brevo API（exe 內的 Outlook 寄信依賴該電腦有 Outlook）

## 設定

- `.env`：`SERPER_API_KEY`、`AI_API_KEY`（OpenRouter）、`NEWS_AI_MODEL`、`EMAIL_FROM` / `EMAIL_TO`
- `config.yaml` 的 `news:` 段落：搜尋關鍵字、重試次數、Google Sheets 同步（`news.google.enabled: true` 並在 `.env` 設 `GOOGLE_SERVICE_ACCOUNT_JSON`）

## 測試

```powershell
python -m unittest tests.test_news_offline -v
```
