"""
Startup script for Vetic Experience Manager Dashboard
------------------------------------------------------
Starts the FastAPI server (uvicorn) and opens an ngrok tunnel
on the permanent static domain: upriver-glutinous-spoiler.ngrok-free.dev

Usage:
    python run_ngrok.py
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

NGROK_EXE = (
    r"C:\Users\hp\AppData\Local\Microsoft\WinGet\Packages"
    r"\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
)
STATIC_DOMAIN = "upriver-glutinous-spoiler.ngrok-free.dev"
APP_PORT = 8000
UVICORN_CMD = [
    str(BASE_DIR / ".venv-1" / "Scripts" / "python.exe"),
    "-m", "uvicorn", "app:app",
    "--host", "0.0.0.0",
    "--port", str(APP_PORT),
]


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_app(timeout: int = 40) -> bool:
    url = f"http://127.0.0.1:{APP_PORT}/login"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(1)
    return False


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_server() -> subprocess.Popen | None:
    if is_port_open(APP_PORT):
        print(f"[INFO] FastAPI already running on port {APP_PORT}.")
        return None
    print("[INFO] Starting FastAPI server...")
    return subprocess.Popen(
        UVICORN_CMD,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


def start_ngrok() -> tuple[subprocess.Popen, list[str]]:
    print(f"[INFO] Starting ngrok tunnel -> https://{STATIC_DOMAIN}")
    proc = subprocess.Popen(
        [NGROK_EXE, "http", str(APP_PORT), "--domain", STATIC_DOMAIN, "--log", "stdout"],
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []

    def _reader():
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                # Print only key events
                if any(k in line for k in ["started tunnel", "url=", "ERR", "error"]):
                    print(line)

    threading.Thread(target=_reader, daemon=True).start()
    return proc, lines


if __name__ == "__main__":
    app_proc = None
    ngrok_proc = None

    try:
        app_proc = start_server()

        print("[INFO] Waiting for FastAPI to be ready...")
        if not wait_for_app(timeout=45):
            print("[ERROR] FastAPI did not start in time.")
            raise SystemExit(1)

        print("[INFO] FastAPI is ready!")
        ngrok_proc, _ = start_ngrok()

        # Give ngrok a moment to connect
        time.sleep(4)

        print("\n" + "=" * 60)
        print("  Dashboard is LIVE at:")
        print(f"  https://{STATIC_DOMAIN}")
        print("=" * 60)
        print("  Open this URL on any device / any network.")
        print("  Press Ctrl+C to stop everything.")
        print("=" * 60 + "\n")

        while True:
            if ngrok_proc.poll() is not None:
                print("[WARN] ngrok tunnel stopped unexpectedly.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        stop(ngrok_proc)
        stop(app_proc)
        print("[INFO] All services stopped.")
