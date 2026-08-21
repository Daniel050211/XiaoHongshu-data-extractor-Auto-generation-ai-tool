# -*- mode: python ; coding: utf-8 -*-
# 新聞 AI 桌面 App（佛山新聞線）PyInstaller spec
# 建置：python -m PyInstaller --noconfirm --clean XHSNewsAI.spec


a = Analysis(
    ['news_app_launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[('C:/Users/DanielHau/AppData/Local/Programs/Python/Python314/tcl', 'tcl')],
    hiddenimports=[
        'news_app', 'news_app.app', 'news_app.config', 'news_app.prompts',
        'news_app.serper', 'news_app.ai', 'news_app.store', 'news_app.email',
        'news_app.pipeline', 'news_app.web', 'news_app.mailwatch',
        'news_app.account_store', 'news_app.scheduler', 'news_app.sheets_sync',
        'xhs_report', 'xhs_report.config', 'xhs_report.emailer',
        'win32com', 'win32com.client', 'pythoncom',
        'gspread', 'yaml', 'dotenv', 'requests', 'jinja2',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='XHSNewsAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
