# 佛山新聞 AI — 給同事/老闆的安裝說明（約 5 分鐘）

## 一、收到的檔案夾怎麼用

1. 解壓縮整個資料夾（保持結構，**exe 要和 config.yaml 在同一層**）
2. 雙擊 **`FoshanNewsAI.exe`**（第一次 Windows 可能顯示「已保護您的電腦」→ 按「更多資訊」→「仍要執行」）
3. 出現「佛山產業新聞 AI」視窗就是成功
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

## 五、常見問題

- **視窗開不出來**：確認 exe 在資料夾根目錄（與 config.yaml 同層），且資料夾有完整權限
- **搜尋失敗**：`.env` 的 `SERPER_API_KEY` 沒填或填錯
- **沒有通知信**：檢查 `EMAIL_PROVIDER` 與 key；用 Outlook 的要確認 Outlook 已登入且沒有跳出錯誤對話框
- **想從頭開始**：刪掉 `data/news.db`，歷史紀錄會清空（帳號設定不會動）

> 安全提醒：`.env` 含 API key，**不要**把 `.env` 連同資料夾一起寄出去；給別人用 `.env.example` 即可。
