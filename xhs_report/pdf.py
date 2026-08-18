"""HTML 週報轉 PDF（使用 Edge headless，手機可直接開啟）。"""
from __future__ import annotations

import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def find_edge() -> Path | None:
    for p in EDGE_CANDIDATES:
        if p.exists():
            return p
    return None


def _rmtree(path: Path):
    try:
        for f in path.glob("*"):
            if f.is_dir():
                for g in f.glob("*"):
                    g.unlink(missing_ok=True)
                f.rmdir()
            else:
                f.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass


def _log_error(html_path, pdf_path, attempt: int, detail: str):
    try:
        log = Path("data/pdf_error.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] attempt {attempt}\n")
            f.write(f"  html: {html_path}\n  pdf: {pdf_path}\n  detail: {detail[:1500]}\n")
    except OSError:
        pass


def html_to_pdf(html_path: Path, pdf_path: Path) -> Path | None:
    edge = find_edge()
    if edge is None:
        print("[pdf] 找不到 Edge，跳過 PDF 產生")
        return None
    pdf_path = pdf_path.resolve()
    for attempt in (1, 2):
        profile = Path(tempfile.mkdtemp(prefix="edge_pdf_"))
        proc = None
        try:
            cmd = [
                str(edge),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--no-first-run",
                f"--user-data-dir={profile}",
                f"--print-to-pdf={pdf_path}",
                html_path.resolve().as_uri(),
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.time() + 100
            while time.time() < deadline:
                if pdf_path.exists() and pdf_path.stat().st_size > 0:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(1)
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                print(f"[pdf] 已產生：{pdf_path}")
                return pdf_path
            detail = ""
            try:
                _, err = proc.communicate(timeout=5)
                detail = err.decode("utf-8", "replace")[:2000]
            except Exception:  # noqa: BLE001
                pass
            _log_error(html_path, pdf_path, attempt, detail or "（無 stderr，可能逾時）")
            print(f"[pdf] 第 {attempt} 次嘗試失敗（逾時或無輸出）")
        except Exception as e:  # noqa: BLE001
            _log_error(html_path, pdf_path, attempt, str(e))
            print(f"[pdf] 第 {attempt} 次嘗試例外: {e}")
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=20)
                except Exception:  # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
            _rmtree(profile)
        time.sleep(1)
    print("[pdf] 轉 PDF 失敗（逾時或無輸出）")
    return None
