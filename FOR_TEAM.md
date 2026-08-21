# 小紅書新聞AI — 給同事/老闆的安裝說明（約 5 分鐘）

## 一、收到的檔案夾怎麼用

1. 解壓縮整個資料夾（保持結構，**exe 要和 config.yaml 在同一層**）
2. 雙擊 **`XHSNewsAI.exe`**（第一次 Windows 可能顯示「已保護您的電腦」→ 按「更多資訊」→「仍要執行」）
3. 出現「小紅書新聞AI」視窗就是成功
4. 之後每天：開 App → 「執行」分頁按「立即執行新一輪」；審批在「審批」分頁，或收信後回覆 Email / 點表單連結

> 不需要安裝 Python、不需要開終端機。

## 二、打開之前要先填自己的設定

把資料夾裡的 **`.env.example` 複製成 `.env`**，填三個必要項目：

| 項目 | 去哪裡申請 | 用途 |
|---|---|---|
| `SERPER_API_KEY` | https://serper.dev | 新聞搜尋（必填） |
| `AI_API_KEY` | https://openrouter.ai/keys | AI 分析（必填） |
| `EMAIL_PROVIDER` + 寄信 key | 見下面「寄信」 | 通知信（建議填） |

也可直接開 App → 「設定」分頁填，存檔即生效。設定會存到 **exe 旁邊的 `.env`**，下次重開 App 會自動帶出，不需要重填。

## 三、寄信（重要）

程式預設用「本機 Outlook」寄信：**同一台電腦必須有安裝並登入 Outlook**。

如果不想依賴 Outlook，改用 API 寄信（推薦，最穩定）：

1. 註冊 https://sendgrid.com（免費 100 封/天）
2. Settings → Sender Authentication → **Single Sender Verification** 驗證自己的寄件信箱（不需 DNS）
3. Settings → API Keys → Create API Key
4. 在 `.env` 填：
   ```
   EMAIL_PROVIDER=sendgrid
   SENDGRID_API_KEY=SG.你的key
   EMAIL_FROM=你的信箱
   EMAIL_TO=收件人（逗號分隔）
   ```

不填寄信設定也能用 App 審批，只是收不到通知信。

## 四、帳號設定

- 帳號都在 `config/news_accounts/` 資料夾（一個帳號一個檔）
- 用 App 的「帳號」分頁管理即可（新增/編輯/啟用停用/預覽 prompt）
- `run_weekly.py` 的帳號名與新聞帳號名一致，新聞線才會讀到該帳號自己的週報回饋
- `XHSNewsAI.exe` 和 `XHSWeeklyReport.exe` 要放在**同一個資料夾**，新聞 App 是讀 exe 旁的 `data/xhs.db` 取得最新週報回饋；每週先跑週報、再跑新聞，就會自動用最新一週的建議

## 五、手機開審批表單（選填）

想讓同事用手機點 email 裡的連結填表單（像 n8n 那樣）：

1. 註冊自己的 ngrok 帳號（免費）：https://ngrok.com/download，下載 `ngrok.exe` 放回本資料夾
2. ngrok Dashboard 複製 Authtoken 與 Static Domain（例如 `你的名字.ngrok-free.dev`）
3. 第一次先登入一次：`ngrok config add-authtoken 你的Authtoken`
4. 在 `.env` 填：
   ```
   FORM_PUBLIC_URL=https://你的名字.ngrok-free.dev
   FORM_TOKEN=自己亂打的英文數字
   ```
5. 把 `start-ngrok.cmd` 裡的網址換成你自己的，雙擊執行（或放進「啟動」資料夾讓開機自動跑）
6. 打開 App → 之後 email 裡的表單連結就是手機可開的網址

> 提醒：表單只在「電腦開著 + App 開著 + 隧道跑著」時可用；手機第一次開會看到 ngrok 的「Visit Site」警示頁，點過去即可；`FORM_TOKEN` 是安全碼，不要外傳。

## 六、常見問題

- **視窗開不出來**：確認 exe 在資料夾根目錄（與 config.yaml 同層），且資料夾有完整權限
- **搜尋失敗**：`.env` 的 `SERPER_API_KEY` 沒填或填錯
- **沒有通知信**：檢查 `EMAIL_PROVIDER` 與 key；用 Outlook 的要確認 Outlook 已登入且沒有跳出錯誤對話框
- **想從頭開始**：刪掉 `data/news.db`，歷史紀錄會清空（帳號設定不會動）

> 安全提醒：`.env` 含 API key，**不要**把 `.env` 連同資料夾一起寄出去；給別人用 `.env.example` 即可。
