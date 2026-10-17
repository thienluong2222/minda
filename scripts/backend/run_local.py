"""Run API and worker together with the selected Python/environment; Ctrl+C stops both."""

import argparse
import signal
import subprocess
import sys
import threading
from pathlib import Path

from meeting_pipeline.minutes.document_tools import preview_tools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not (root / "apps/web/dist/index.html").is_file():
        raise SystemExit("Chạy npm --prefix apps/web ci và npm --prefix apps/web run build trước.")
    missing = [name for name, path in preview_tools().items() if not path]
    if missing:
        print(
            "Chưa có công cụ xem trước DOCX: "
            + ", ".join(missing)
            + ". Trên macOS: brew install poppler && brew install --cask libreoffice",
            flush=True,
        )
    stop = threading.Event()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, lambda *_: stop.set())
    processes = []
    try:
        for arguments in [["serve", "--port", str(args.port)], ["worker"]]:
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "meeting_backend.cli", *arguments], cwd=root
                )
            )
        print(f"Web: http://127.0.0.1:{args.port} · Ctrl+C để dừng API và worker.", flush=True)
        while not stop.wait(0.5):
            if any(process.poll() is not None for process in processes):
                break
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
