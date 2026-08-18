"""新聞 AI 桌面 App 啟動器（PyInstaller exe 入口）。

雙擊 exe → 開桌面 App；帶 CLI 參數（如 --run）時，改用命令列模式，
讓 Windows 排程也能直接呼叫 exe。
"""
from __future__ import annotations

import sys

CLI_COMMANDS = {
    "--run", "--watch-mail", "--check-mail", "--serve", "--list", "--list-accounts",
    "--show", "--approve-direction", "--approve-script", "--cancel", "--cancel-all",
    "--resend-final", "--resend-direction", "--resend-script", "--retry-scripts",
}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in CLI_COMMANDS:
        from run_news import main as cli_main
        sys.argv[0] = "run_news.py"
        cli_main()
    else:
        from news_app.app import main as app_main
        app_main()


if __name__ == "__main__":
    main()
